# Copyright (C) 2011-2013 Versile AS
#
# This file is part of Versile Python.
#
# Versile Python is free software: you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public License
# as published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""Base class for reactors waiting on file descriptor I/O events."""
from __future__ import print_function, unicode_literals

from collections import deque
import copy
import heapq
import os
import sys
import threading
import time

from versile.internal import _b2s, _s2b, _ssplit, _vplatform, _vexport, _pyver
from versile.internal import _v_silent
from versile.common.iface import implements, final, abstract
from versile.common.log import VLogger, VConsoleLog, VLogEntryFormatter
from versile.reactor import VScheduledCall
from versile.reactor import VReactorException, VReactorStopped, IVCoreReactor
from versile.reactor import IVDescriptorReactor, IVTimeReactor
from versile.reactor.io import VFIOLost
from versile.reactor.log import VReactorLogger

__all__ = ['VFDWaitReactor']
__all__ = _vexport(__all__)


@abstract
@implements(IVCoreReactor, IVDescriptorReactor, IVTimeReactor)
class VFDWaitReactor(threading.Thread):
    """Base class for reactor which waits on multiple file descriptors.

    This class is abstract and should not be directly instantiated,
    instead a derived class should be used.

    The reactor provides descriptor event handling services for
    descriptors, and it provides timer services.

    :param daemon: if True run reactor thread as a daemonic thread
    :param daemon: bool

    If *daemon* is set, then the reactor thread object is set up
    as a daemon thread, by setting self.daemon=True. When the
    reactor is executed as a thread and the daemonic property is
    set, the thread will not block program exit and will be
    terminated if only daemon threads are running.

    The reactor is not started when it is created. Its event loop can
    either be run by calling :meth:`run` or by starting it as a
    thread.

    """

    # Internal message codes for message-driven actions
    (__ADD_READER, __REMOVE_READER, __ADD_WRITER,
     __REMOVE_WRITER, __STOP, __ADD_CALL, __REMOVE_CALL) = range(7)

    # Internal codes for internal I/O wait function
    _FD_READ = 1
    _FD_WRITE = 2
    _FD_ERROR = 0
    _FD_READ_ERROR = -1
    _FD_WRITE_ERROR = -2

    def __init__(self, daemon=False):
        super(VFDWaitReactor, self).__init__()
        if daemon:
            self.daemon = True
        self.name = 'VSelectReactor-' + str(self.name.split('-')[1])

        self.__readers, self.__writers = set(), set()

        self.__finished = False
        self.__thread = None

        if _vplatform == 'ironpython' or sys.platform == _b2s(b'win32'):
            self.__ctrl_is_pipe = False
            from versile.reactor.io.tcp import VTCPSocket
            self.__ctrl_r, self.__ctrl_w = VTCPSocket.create_native_pair()
        else:
            self.__ctrl_is_pipe = True
            self.__ctrl_r, self.__ctrl_w = os.pipe()
        self.__ctrl_queue = deque()
        self.__ctrl_msg_flag = False
        self.__ctrl_stop = False
        # Locks __ctrl_msg_flag, __ctrl_queue, writing to __ctrl_w
        self.__ctrl_lock = threading.Lock()

        self.__scheduled_calls = []          # heapq-ordered list
        self.__grouped_calls = {}
        self.__calls_lock = threading.Lock() # Locks scheduled/grouped calls
        self.__t_next_call = None            # Timestamp next call (or None)

        self.__core_log = VLogger()
        self.__logger = VReactorLogger(self)
        self.__logger.add_watcher(self.__core_log)
        # Reactor-only proxy logger which adds a prefix
        self.__rlog = self.__core_log.create_proxy_logger(prefix='Reactor')

    # Class default log watcher
    __default_log_watcher = None

    def run(self):
        """See :meth:`versile.reactor.IVCoreReactor.run`\ ."""
        if self.__finished or self.__thread:
            raise RuntimeError('Can only start reactor once')
        self.__thread = threading.current_thread()
        self.started()

        try:
            self._run()
        finally:
            # Clean up and free resources
            self.__finished = True
            if self.__ctrl_is_pipe:
                for pipe_fd in self.__ctrl_r, self.__ctrl_w:
                    try:
                        os.close(pipe_fd)
                    except Exception as e:
                        _v_silent(e)
            else:
                for pipe_f in self.__ctrl_r, self.__ctrl_w:
                    try:
                        pipe_f.close()
                    except Exception as e:
                        _v_silent(e)
            self.__readers.clear()
            self.__writers.clear()
            self.__ctrl_queue.clear()
            self.__scheduled_calls = []
            self.__grouped_calls.clear()
            self._fd_done()

    @final
    def _run(self):
        """Runs the reactor's event handling loop."""
        # Monitor control message pipe
        self._add_read_fd(self.__ctrl_r)

        s_calls = deque()
        while True:
            t_next_call = self.__t_next_call
            if t_next_call is not None:
                timeout = max(t_next_call - time.time(), 0)
            else:
                timeout = None

            for event, fd in self._fd_wait(timeout):
                if event == self._FD_ERROR:
                    if fd in (self.__ctrl_r, self.__ctrl_w):
                        self.__rlog.critical('Reactor message pipe failed')
                        raise VReactorException('Reactor message pipe error')
                    self.remove_reader(fd, internal=True)
                    self.remove_writer(fd, internal=True)
                    if not isinstance(fd, int):
                        fd.close_io(VFIOLost())
                    elif fd >= 0:
                        # WORKAROUND - poll.poll() on OSX some times produces
                        # descriptors that do not close cleanly; we ignore this
                        try:
                            os.close(fd)
                        except Exception as e:
                            _v_silent(e)
                elif event == self._FD_READ_ERROR:
                    if fd in (self.__ctrl_r, self.__ctrl_w):
                        self.__rlog.critical('Reactor message pipe failed')
                        raise VReactorException('Reactor message pipe error')
                    self.remove_reader(fd, internal=True)
                    if not isinstance(fd, int):
                        fd.close_input(VFIOLost())
                    elif fd >= 0:
                        # WORKAROUND - poll.poll() on OSX some times produces
                        # descriptors that do not close cleanly; we ignore this
                        try:
                            os.close(fd)
                        except Exception as e:
                            _v_silent(e)
                elif event == self._FD_WRITE_ERROR:
                    if fd in (self.__ctrl_r, self.__ctrl_w):
                        self.__rlog.critical('Reactor message pipe failed')
                        raise VReactorException('Reactor message pipe error')
                    self.remove_writer(fd, internal=True)
                    if not isinstance(fd, int):
                        fd.close_output(VFIOLost())
                    elif fd >= 0:
                        # WORKAROUND - poll.poll() on OSX some times produces
                        # descriptors that do not close cleanly; we ignore this
                        try:
                            os.close(fd)
                        except Exception as e:
                            _v_silent(e)
                elif event == self._FD_READ:
                    if ((self.__ctrl_is_pipe and fd == self.__ctrl_r)
                        or not self.__ctrl_is_pipe and fd is self.__ctrl_r):
                        messages = self.__msg_pop_all()
                        for code, data in messages:
                            self.__msg_process(code, data)
                            # Execute stop instruction immediately
                            if self.__ctrl_stop:
                                return
                        messages = code = data = None
                    elif fd in self.__readers:
                        try:
                            fd.do_read()
                        except:
                            # Should never happen if compliant do_read
                            self.__rlog.log_trace(lvl=self.log.ERROR) #DBG
                            self.__rlog.info('do_read() exception, aborting')
                            self.remove_reader(fd, internal=True)
                            fd.close_input(VFIOLost())
                elif event == self._FD_WRITE:
                    if fd in self.__writers:
                        try:
                            fd.do_write()
                        except:
                            # Should never happen if compliant do_write
                            self.__rlog.log_trace(lvl=self.log.ERROR) #DBG
                            self.__rlog.info('do_write() exception, aborting')
                            self.remove_writer(fd, internal=True)
                            fd.close_output(VFIOLost())
            if self.__ctrl_stop:
                return

            # Execute all timed-out scheduled calls
            if self.__scheduled_calls:
                self.__calls_lock.acquire()
                try:
                    loop_time = time.time()
                    _sc = self.__scheduled_calls
                    while _sc:
                        call = _sc[0]
                        if call.scheduled_time <= loop_time:
                            call = heapq.heappop(_sc)
                            s_calls.append(call)
                        else:
                            break
                    _sc = None
                    if s_calls:
                        for call in s_calls:
                            if call.callgroup:
                                callgroup = call.callgroup
                                group = self.__grouped_calls.get(callgroup,
                                                                 None)
                                if group:
                                    group.discard(call)
                                    if not group:
                                        self.__grouped_calls.pop(callgroup)
                        callgroup = None
                        if self.__scheduled_calls:
                            _t = self.__scheduled_calls[0].scheduled_time
                            self.__t_next_call = _t
                        else:
                            self.__t_next_call = None
                finally:
                    self.__calls_lock.release()
                for call in s_calls:
                    try:
                        call.execute()
                    except Exception as e:
                        self.__rlog.error('Scheduled call failed')
                        self.__rlog.log_trace(lvl=self.log.ERROR)
                s_calls.clear()

                # Lose any loop variable references
                call = fd = None

    def started(self):
        """See :meth:`versile.reactor.IVCoreReactor.started`\ .

        If a default log watcher has been set with
        :meth:`set_default_log_watcher`\ , then the default watcher is
        added to this reactor's logger.

        """
        if hasattr(self, '_default_log_watcher'):
            self.__core_log.add_watcher(self._default_log_watcher)

    @final
    def stop(self):
        """See :meth:`versile.reactor.IVCoreReactor.stop`\ ."""
        if self.__finished or self.__thread is None:
            return
        else:
            self.__msg_stop()

    @final
    def add_reader(self, reader, internal=False):
        """See :meth:`versile.reactor.IVDescriptorReactor.add_reader`\ ."""
        if self.__finished:
            raise VReactorStopped('Reactor was stopped.')
        elif internal or self.__is_reactor_thread():
            # TROUBLESHOOT - if 'internal' is set True from a
            # non-reactor thread, there can be all kinds of thread conflicts,
            # as the reactor relies on the 'internal parameter' as a promise.
            # In case of odd errors that indicate thread conflicts, can
            # perform a 'if internal and not self.__is_reactor_thread()'
            # debug check here
            try:
                self._add_read_fd(reader)
            except IOError as e:
                _v_silent(e) # Ignoring for now
            else:
                self.__readers.add(reader)
        else:
            self.__msg_add_reader(reader)

    @final
    def add_writer(self, writer, internal=False):
        """See :meth:`versile.reactor.IVDescriptorReactor.add_writer`\ ."""
        if self.__finished:
            raise VReactorStopped('Reactor was stopped.')
        elif internal or self.__is_reactor_thread():
            # TROUBLESHOOT - see add_reader comments regarding 'internal'
            try:
                self._add_write_fd(writer)
            except IOError as e:
                _v_silent(e) # Ignoring for now
            else:
                self.__writers.add(writer)
        else:
            self.__msg_add_writer(writer)

    @final
    def remove_reader(self, reader, internal=False):
        """See :meth:`versile.reactor.IVDescriptorReactor.remove_reader`\ ."""
        if internal or self.__is_reactor_thread():
            # TROUBLESHOOT - see add_reader comments regarding 'internal'
            if reader in self.__readers:
                self.__readers.discard(reader)
                self._remove_read_fd(reader)
        else:
            self.__msg_remove_reader(reader)

    @final
    def remove_writer(self, writer, internal=False):
        """See :meth:`versile.reactor.IVDescriptorReactor.remove_writer`\ ."""
        if internal or self.__is_reactor_thread():
            # TROUBLESHOOT - see add_reader comments regarding 'internal'
            if writer in self.__writers:
                self.__writers.discard(writer)
                self._remove_write_fd(writer)
        else:
            self.__msg_remove_writer(writer)

    @final
    def remove_all(self):
        """See :meth:`versile.reactor.IVDescriptorReactor.remove_all`\ .

        Should only be called by the reactor thread.

        """
        for r in self.readers():
            self.remove_reader(r)
        for w in self.writers():
            self.remove_writer(w)

    @final
    @property
    def readers(self):
        """See :attr:`versile.reactor.IVDescriptorReactor.readers`\ .

        Should only be called by the reactor thread.

        """
        return copy.copy(self.__readers)

    @final
    @property
    def writers(self):
        """See :attr:`versile.reactor.IVDescriptorReactor.writers`\ .

        Should only be called by the reactor thread.

        """
        return copy.copy(self.__writers)

    @final
    @property
    def log(self):
        """See :attr:`versile.reactor.IVCoreReactor.log`\ ."""
        return self.__logger

    def time(self):
        """See :meth:`versile.reactor.IVTimeReactor.time`"""
        return time.time()

    @final
    def execute(self, callback, *args, **kargs):
        """See :meth:`versile.reactor.IVTimeReactor.execute`\ ."""
        if self.__is_reactor_thread():
            return callback(*args, **kargs)
        else:
            return self.schedule(0.0, callback, *args, **kargs)

    @final
    def schedule(self, delay_time, callback, *args, **kargs):
        """See :meth:`versile.reactor.IVTimeReactor.schedule`"""
        return VScheduledCall(self, delay_time, None, callback,
                              True, *args, **kargs)

    @final
    def cg_schedule(self, delay_time, callgroup, callback, *args, **kargs):
        """See :meth:`versile.reactor.IVTimeReactor.cg_schedule`"""
        return VScheduledCall(self, delay_time, callgroup, callback,
                              True, *args, **kargs)

    @final
    def call_when_running(self, callback, *args, **kargs):
        """See :meth:`versile.reactor.IVCoreReactor.call_when_running`"""
        return self.schedule(0.0, callback, *args, **kargs)

    @final
    def add_call(self, call, internal=False):
        """See :meth:`versile.reactor.IVTimeReactor.add_call`\ ."""
        if not call.active:
            return
        if internal or self.__is_reactor_thread():
            # TROUBLESHOOT - see add_reader comments regarding 'internal'
            self.__calls_lock.acquire()
            try:
                heapq.heappush(self.__scheduled_calls, call)

                if call.callgroup:
                    callgroup = call.callgroup
                    group = self.__grouped_calls.get(callgroup, None)
                    if not group:
                        group = set()
                        self.__grouped_calls[callgroup] = group
                    group.add(call)

                # Update time of next call
                if self.__scheduled_calls:
                    _t = self.__scheduled_calls[0].scheduled_time
                    self.__t_next_call = _t
                else:
                    self.__t_next_call = None
            finally:
                self.__calls_lock.release()
        else:
            self.__msg_add_call(call)

    @final
    def remove_call(self, call, internal=False):
        """See :meth:`versile.reactor.IVTimeReactor.remove_call`\ ."""
        if internal or self.__is_reactor_thread():
            # TROUBLESHOOT - see add_reader comments regarding 'internal'
            self.__calls_lock.acquire()
            try:
                self.__remove_call(call)
            finally:
                self.__calls_lock.release()
        else:
            self.__msg_remove_call(call)

    def cg_remove_calls(self, callgroup):
        """See :meth:`versile.reactor.IVTimeReactor.cg_remove_calls`\ ."""
        self.__calls_lock.acquire()
        try:
            calls = copy.copy(self.__grouped_calls.get(callgroup, None))
            if calls:
                for call in calls:
                    self.__remove_call(call)
        finally:
            self.__calls_lock.release()

    @classmethod
    def set_default_log_watcher(cls, lvl=None, watcher=None):
        """Set a class default log watcher for reactor logging.

        :param lvl:     log level (or None)
        :type  lvl:     int
        :param watcher: log watcher (or None)
        :type  watcher: :class:`versile.common.log.VLogWatcher`

        Not thread-safe. Intended mainly to be called in the beginning
        of a program in order to set a watcher for general reactor log
        output. If no watcher is specified sets up default logging to
        the console. If lvl is not None then adds a filter to the
        watcher for the given debug level.

        """
        if watcher is None:
            watcher = VConsoleLog(VLogEntryFormatter())
        if lvl is not None:
            from versile.common.log import VLogEntryFilter
            class _Filter(VLogEntryFilter):
                def keep_entry(self, log_entry):
                    return log_entry.lvl >= lvl
            orig_watcher = watcher
            watcher = VLogger()
            watcher.add_watch_filter(_Filter())
            watcher.add_watcher(orig_watcher)
        VFDWaitReactor._default_log_watcher = watcher

    def _fd_wait(self, timeout):
        """Wait on I/O on registered file descriptors.

        Generator which yields tuples of (event, fd). *fd* is a file
        descriptor [either an integer or an object with fileno()]
        which was registered for reading or writing.

        *event* is one of :attr:`_FD_READ`\ , :attr:`_FD_WRITE` or
        :attr:`_FD_ERROR`\ .

        """
        raise NotImplementedError()

    def _add_read_fd(self, fd):
        """Called internally to add a reader.

        :param fd: file descriptor or object with fileno() method

        Should only be called by the reactor thread.

        """
        raise NotImplementedError()

    def _add_write_fd(self, fd):
        """Called internally to add a reader.

        :param fd: file descriptor or object with fileno() method

        Should only be called by the reactor thread.

        """
        raise NotImplementedError()

    def _remove_read_fd(self, fd):
        """Removes both internally and externally registered readers.

        :param fd: file descriptor or object with fileno() method

        Should only be called by the reactor thread.

        """
        raise NotImplementedError()

    def _remove_write_fd(self, fd):
        """Removes both internally and externally registered writers.

        :param fd: file descriptor or object with fileno() method

        Should only be called by the reactor thread.

        """
        raise NotImplementedError()

    def _fd_done(self):
        """Internal call to notify fd wait subsystem reactor loop has ended.

        Subsystem should use this to free any held resources.

        """
        raise NotImplementedError()


    def __is_reactor_thread(self):
        """Checks if running thread is the reactor thread.

        :returns: True if same, or if reactor not running as a thread

        This method is thread safe once the reactor loop has started
        as the reactor thread of a running reactor never changes.

        """
        return self.__thread in (None, threading.current_thread())

    def __remove_call(self, call):
        """Removes a call.

        The method assumes the caller holds a lock on self.__calls_lock

        """
        # This is an expensive operation as it requires full call heap
        # normalization, however __remove_call is typically used
        # infrequently, so a heap is used to optimize for adding and popping
        scheduled_time = call.scheduled_time
        _sc = self.__scheduled_calls
        for pos in xrange(len(_sc)):
            if _sc[pos] is call:
                break
        else:
            return

        _sc = _sc.pop(pos)
        heapy.heapify(_sc)
        self.__scheduled_calls, _sc = _sc, None

        callgroup = call.callgroup
        if callgroup and callgroup in self.__grouped_calls:
            group = self.__grouped_calls[callgroup]
            group.discard(call)
            if not group:
                self.__grouped_calls.pop(callgroup)
        self.__scheduled_calls.pop(pos)

        # Update time of next call
        if self.__scheduled_calls:
            self.__t_next_call = self.__scheduled_calls[0].scheduled_time
        else:
            self.__t_next_call = None

    def __msg_push(self, code, data):
        """Push internal message onto msg queue and interrupts event loop."""
        if self.__finished:
            # Not accepting messages if reactor has finished
            return

        self.__ctrl_lock.acquire()
        try:
            self.__ctrl_queue.append((code, data))
            if not self.__ctrl_msg_flag:
                if _pyver == 2:
                    if self.__ctrl_is_pipe:
                        os.write(self.__ctrl_w, _b2s(b'x'))
                    else:
                        self.__ctrl_w.send(_b2s(b'x'))
                else:
                    if self.__ctrl_is_pipe:
                        os.write(self.__ctrl_w, b'x')
                    else:
                        self.__ctrl_w.send(b'x')
                self.__ctrl_msg_flag = True
        finally:
            self.__ctrl_lock.release()

    def __msg_pop_all(self):
        """Pop all messages off the control queue.

        Can only be called when the I/O wait subsystem has confirmed
        the control pipe has data for reading, otherwise this call
        will block (possibly forever).

        """
        self.__ctrl_lock.acquire()
        try:
            # Clear internal messaging pipe (it holds max 1 byte)
            if self.__ctrl_is_pipe:
                os.read(self.__ctrl_r, 128)
            else:
                self.__ctrl_r.recv(128)
            queue, self.__ctrl_queue = self.__ctrl_queue, deque()
            self.__ctrl_msg_flag = False
            return queue
        finally:
            self.__ctrl_lock.release()

    def __msg_add_reader(self, reader):
        code, data = self.__ADD_READER, reader
        self.__msg_push(code, data)

    def __msg_remove_reader(self, reader):
        code, data = self.__REMOVE_READER, reader
        self.__msg_push(code, data)

    def __msg_add_writer(self, writer):
        code, data = self.__ADD_WRITER, writer
        self.__msg_push(code, data)

    def __msg_remove_writer(self, writer):
        code, data = self.__REMOVE_WRITER, writer
        self.__msg_push(code, data)

    def __msg_stop(self):
        code, data = self.__STOP, None
        self.__msg_push(code, data)

    def __msg_add_call(self, call):
        code, data = self.__ADD_CALL, call
        self.__msg_push(code, data)

    def __msg_remove_call(self, call):
        code, data = self.__REMOVE_CALL, call
        self.__msg_push(code, data)

    def __msg_process(self, code, data):
        if code == self.__ADD_READER:
            self.add_reader(data, True)
        elif code == self.__ADD_WRITER:
            self.add_writer(data, True)
        elif code == self.__REMOVE_READER:
            self.remove_reader(data, True)
        elif code == self.__REMOVE_WRITER:
            self.remove_writer(data, True)
        elif code == self.__STOP:
            self.__msg_process_stop()
        elif code == self.__ADD_CALL:
            self.add_call(data, True)
        elif code == self.__REMOVE_CALL:
            self.remove_call(data, True)
        else:
            raise RuntimeError('Unknown internal message code')

    def __msg_process_stop(self):
        self.__thread = None
        self.__finished = True
        self.__ctrl_stop = True
