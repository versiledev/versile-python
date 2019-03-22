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

"""Reactor based on :func:`select.kqueue`\ .

Only available on systems that support :func:`select.kqueue`\ .

"""
from __future__ import print_function, unicode_literals

from select import kqueue, kevent # Raises ImportError if no select.poll
import errno
import select

from collections import deque

from versile.internal import _vexport, _v_silent
from versile.reactor.waitr import VFDWaitReactor

__all__ = ['VKqueueReactor']
__all__ = _vexport(__all__)

_KQ_FILTER_READ = select.KQ_FILTER_READ
_KQ_FILTER_WRITE = select.KQ_FILTER_WRITE
_KQ_EV_ADD = select.KQ_EV_ADD
_KQ_EV_DELETE = select.KQ_EV_DELETE
_KQ_EV_EOF = select.KQ_EV_EOF
_KQ_EV_ERROR = select.KQ_EV_ERROR


class VKqueueReactor(VFDWaitReactor):
    """Reactor which uses :func:`select.kqueue` to controls it event loop.

    The reactor uses :func:`select.kqueue` for non-blocking monitoring
    descriptors. It also employes an internal messaging system to
    allow other systems to wake up the event loop by signalling over
    an internal pipe system.

    Only available on systems that support :func:`select.kqueue`\ .

    """
    # The reactor uses level-based triggering

    def __init__(self, daemon=False):
        super(VKqueueReactor, self).__init__(daemon=daemon)
        self.__kqueue = kqueue()
        self.__rfd = set()
        self.__wfd = set()
        self.__robj = dict() # fd -> obj
        self.__wobj = dict() # fd -> obj

    def _fd_wait(self, timeout):
        if timeout is not None and timeout < 0:
            timeout = None

        y_events = deque()
        # HARDCODED - listening for maximum 1M events, as kqueue.control does
        # not support passing 'unlimited'
        try:
            p_events = self.__kqueue.control(None, 0x100000, timeout)
        except IOError as e:
            # Return if interrupted by signal handler, not catching can
            # interfere e.g. with interactive use in a python interpreter
            if e.errno == errno.EINTR:
                return deque()
        except Exception as e:
            raise e
        for event in p_events:
            fd = event.ident
            _rd_event = (event.filter == _KQ_FILTER_READ)
            _wr_event = (event.filter == _KQ_FILTER_WRITE)
            _error = event.flags & _KQ_EV_ERROR or event.flags & _KQ_EV_EOF

            if _rd_event:
                f_obj = self.__robj.get(fd, None)
                if f_obj is None:
                    f_obj = fd
                if _error:
                    y_events.append((self._FD_READ_ERROR, f_obj))
                else:
                    y_events.append((self._FD_READ, f_obj))
            if _wr_event:
                f_obj = self.__wobj.get(fd, None)
                if f_obj is None:
                    f_obj = fd
                if _error:
                    y_events.append((self._FD_WRITE_ERROR, f_obj))
                else:
                    y_events.append((self._FD_WRITE, f_obj))
        return y_events

    def _add_read_fd(self, fd):
        if not isinstance(fd, (int, long)):
            fd, f_obj = fd.fileno(), fd
        else:
            f_obj = None
        if fd < 0:
            raise IOError('Invalid file descriptor')
        if fd in self.__rfd:
            return

        try:
            ev = kevent(fd, _KQ_FILTER_READ, _KQ_EV_ADD)
            self.__kqueue.control([ev], 0)
        except Exception as e:
            raise IOError('Failed to update kqueue object: %s' % e)
        else:
            self.__rfd.add(fd)
            if f_obj is not None:
                self.__robj[fd] = f_obj

    def _add_write_fd(self, fd):
        if not isinstance(fd, (int, long)):
            fd, f_obj = fd.fileno(), fd
        else:
            f_obj = None
        if fd < 0:
            raise IOError('Invalid file descriptor')
        if fd in self.__wfd:
            return

        try:
            ev = kevent(fd, _KQ_FILTER_WRITE, _KQ_EV_ADD)
            self.__kqueue.control([ev], 0)
        except Exception as e:
            raise IOError('Failed to update kqueue object: %s' % e)
        else:
            self.__wfd.add(fd)
            if f_obj is not None:
                self.__wobj[fd] = f_obj

    def _remove_read_fd(self, fd):
        if not isinstance(fd, (int, long)):
            fd, f_obj = fd.fileno(), fd
        else:
            f_obj = None
        if fd < 0:
            # With proper sequencing of removing vs. closing in the
            # reactor thread, this should not happen - however, in
            # case it does, we check here whether f_obj is registered
            # with self.__robj or self.__wobj and if so remove the associated
            # (no longer valid) descriptor.
            if f_obj:
                self.__purge_old_fd_obj(f_obj)
            _v_silent(IOError('Tried to _remove_read_fd invalid descriptor'))
            return
        if fd not in self.__rfd:
            return

        try:
            ev = kevent(fd, _KQ_FILTER_READ, _KQ_EV_DELETE)
            self.__kqueue.control([ev], 0)
        except Exception as e:
            raise IOError('Failed to update kqueue object: %s' % e)
        finally:
            self.__rfd.discard(fd)
            self.__robj.pop(fd, None)

    # Apply isinstance(int, long) also to poll, epoll etc.
    def _remove_write_fd(self, fd):
        if not isinstance(fd, (int, long)):
            fd, f_obj = fd.fileno(), fd
        else:
            f_obj = None
            fd = fd.fileno()
        if fd < 0:
            # With proper sequencing of removing vs. closing in the
            # reactor thread, this should not happen - however, in
            # case it does, we check here whether f_obj is registered
            # with self.__robj or self.__wobj and if so remove the associated
            # (no longer valid) descriptor.
            if f_obj:
                self.__purge_old_fd_obj(f_obj)
            _v_silent(IOError('Tried to _remove_read_fd invalid descriptor'))
            return
        if fd not in self.__wfd:
            return

        try:
            ev = kevent(fd, _KQ_FILTER_WRITE, _KQ_EV_DELETE)
            self.__kqueue.control([ev], 0)
        except Exception as e:
            raise IOError('Failed to update kqueue object: %s' % e)
        finally:
            self.__wfd.discard(fd)
            self.__wobj.pop(fd, None)

    def _fd_done(self):
        self.__kqueue.close()
        self.__kqueue = None
        self.__rfd.clear()
        self.__wfd.clear()
        self.__robj.clear()
        self.__wobj.clear()

    def __purge_old_fd_obj(self, fd_obj):
        for f, o in self.__robj.items():
            if o is fd_obj:
                try:
                    self._remove_read_fd(f)
                except Exception as e:
                    _v_silent(e)
                break

        for f, o in self.__wobj.items():
            if o is fd_obj:
                try:
                    self._remove_write_fd(f)
                except Exception as e:
                    _v_silent(e)
                break
