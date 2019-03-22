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

"""Reactor based on :func:`select.epoll`\ .

Only available on systems that support :func:`select.epoll`\ .

"""
from __future__ import print_function, unicode_literals

from select import epoll # Raises ImportError if no select.poll
import errno
import select

from collections import deque

from versile.internal import _vexport, _v_silent
from versile.reactor.waitr import VFDWaitReactor

__all__ = ['VEpollReactor']
__all__ = _vexport(__all__)

_POLLIN  = select.EPOLLIN
_POLLOUT = select.EPOLLOUT
_POLLERR = select.EPOLLERR
_POLLHUP = select.EPOLLHUP


class VEpollReactor(VFDWaitReactor):
    """Reactor which uses :func:`select.epoll` to controls it event loop.

    The reactor uses :func:`select.epoll` for non-blocking monitoring
    descriptors. It also employes an internal messaging system to
    allow other systems to wake up the event loop by signalling over
    an internal pipe system.

    Only available on systems that support :func:`select.epoll`\ .

    """
    # The reactor uses level-based epoll triggering

    def __init__(self, daemon=False):
        super(VEpollReactor, self).__init__(daemon=daemon)
        self.__poll = epoll()
        self.__rfd = set()
        self.__wfd = set()
        self.__robj = dict() # fd -> obj
        self.__wobj = dict() # fd -> obj

    def _fd_wait(self, timeout):
        if timeout is None:
            timeout = -1

        y_events = deque()
        try:
            p_events = self.__poll.poll(timeout)
        except IOError as e:
            # Return if interrupted by signal handler, not catching can
            # interfere e.g. with interactive use in a python interpreter
            if e.errno == errno.EINTR:
                return deque()
        except Exception as e:
            raise e
        for fd, event in p_events:
            _rd_event = event & _POLLIN
            _wr_event = event & _POLLOUT
            _err_event = event & _POLLERR

            _readable = fd in self.__rfd
            _writeable = fd in self.__wfd
            if _readable:
                f_obj = self.__robj.get(fd, None)
            else:
                f_obj = self.__wobj.get(fd, None)
            if f_obj is None:
                f_obj = fd

            if _err_event:
                y_events.append((self._FD_WRITE_ERROR, f_obj))
            else:
                if _rd_event:
                    obj = self.__robj.get(fd, None)
                    if obj is None:
                        obj = fd
                    y_events.append((self._FD_READ, f_obj))
                if _wr_event:
                    obj = self.__wobj.get(fd, None)
                    if obj is None:
                        obj = fd
                    y_events.append((self._FD_WRITE, f_obj))
        return y_events

    def _add_read_fd(self, fd):
        if not isinstance(fd, int):
            fd, f_obj = fd.fileno(), fd
        else:
            f_obj = None
        if fd < 0:
            raise IOError('Invalid file descriptor')
        if fd in self.__rfd:
            return

        if fd in self.__wfd:
            registered = True
            mask = _POLLIN | _POLLOUT | _POLLERR
        else:
            registered = False
            mask = _POLLIN | _POLLERR
        try:
            if registered:
                self.__poll.modify(fd, mask)
            else:
                self.__poll.register(fd, mask)
        except Exception as e:
            raise IOError('Failed to update poll object')
        else:
            self.__rfd.add(fd)
            if f_obj is not None:
                self.__robj[fd] = f_obj

    def _add_write_fd(self, fd):
        if not isinstance(fd, int):
            fd, f_obj = fd.fileno(), fd
        else:
            f_obj = None
        if fd < 0:
            raise IOError('Invalid file descriptor')
        if fd in self.__wfd:
            return

        if fd in self.__rfd:
            registered = True
            mask = _POLLIN | _POLLOUT | _POLLERR
        else:
            registered = False
            mask = _POLLOUT | _POLLERR
        try:
            if registered:
                self.__poll.modify(fd, mask)
            else:
                self.__poll.register(fd, mask)
        except Exception as e:
            raise IOError('Failed to update poll object')
        else:
            self.__wfd.add(fd)
            if f_obj is not None:
                self.__wobj[fd] = f_obj

    def _remove_read_fd(self, fd):
        if not isinstance(fd, int):
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
            if fd in self.__wfd:
                self.__poll.modify(fd, _POLLOUT | _POLLERR)
            else:
                try:
                    self.__poll.unregister(fd)
                except IOError as e:
                    _v_silent(e)
        except:
            raise IOError('Failed to update poll object')
        finally:
            self.__rfd.discard(fd)
            self.__robj.pop(fd, None)

    def _remove_write_fd(self, fd):
        if not isinstance(fd, int):
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
            if fd in self.__rfd:
                self.__poll.modify(fd, _POLLIN | _POLLERR)
            else:
                try:
                    self.__poll.unregister(fd)
                except IOError as e:
                    _v_silent(e)
        except:
            raise IOError('Failed to update poll object')
        finally:
            self.__wfd.discard(fd)
            self.__wobj.pop(fd, None)

    def _fd_done(self):
        self.__poll.close()
        self.__poll = None
        self.__rfd.clear()
        self.__wfd.clear()
        self.__robj.clear()
        self.__wobj.clear()

    def __purge_old_fd_obj(self, fd_obj):
        for f, o in self.__robj.items():
            if o is fd_obj:
                 old_rd_fd = f
                 break
        else:
            old_rd_fd = None

        for f, o in self.__wobj.items():
            if o is fd_obj:
                old_wr_fd = f
                break
        else:
            old_wr_fd = None

        # Return if no matches
        if old_rd_fd is None and old_wr_fd is None:
            return

        # Unregister file descriptor from poll object
        if old_rd_fd is not None:
            self.__rfd.discard(old_rd_fd)
            self.__robj.pop(old_rd_fd, None)
            try:
                self.__poll.unregister(old_rd_fd)
            except IOError as e:
                _v_silent(e)
        if old_wr_fd is not None:
            self.__wfd.discard(old_wr_fd)
            self.__wobj.pop(old_wr_fd, None)
            if old_wr_fd != old_rd_fd:
                try:
                    self.__poll.unregister(old_wr_fd)
                except IOError as e:
                    _v_silent(e)

        # Check if file descriptor used for another object in the other queue
        # and if so re-enable
        try:
            if old_rd_fd in self.__wfd:
                self.__poll.register(old_rd_fd, _POLLOUT | _POLLERR)
            elif old_wr_fd in self.__rfd:
                self.__poll.register(old_wr_fd, _POLLIN | _POLLERR)
        except:
            _v_silent(IOError('Problem unregistering old descriptor'))
