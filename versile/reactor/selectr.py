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

"""Reactor based on :func:`select.select`\ .

Only available on systems that support :func:`select.select`\ .

"""
from __future__ import print_function, unicode_literals

from collections import deque
import errno
import select

from versile.internal import _vexport, _v_silent
from versile.reactor.waitr import VFDWaitReactor

__all__ = ['VSelectReactor']
__all__ = _vexport(__all__)


class VSelectReactor(VFDWaitReactor):
    """Reactor which uses :func:`select.select` to controls it event loop.

    The reactor uses :func:`select.select` for non-blocking monitoring
    descriptors. It also employes an internal messaging system to
    allow other systems to wake up the event loop by signalling over
    an internal pipe system.

    Only available on systems that support :func:`select.select`\ .

    """

    def __init__(self, daemon=False):
        super(VSelectReactor, self).__init__(daemon=daemon)
        self.__rsel, self.__wsel, self.__sel = set(), set(), set()
        self.__sel_changed = True # Set True when a __*sel changed

    def _fd_wait(self, timeout):
        s_rsel, s_wsel, s_sel = self.__rsel, self.__wsel, self.__sel

        try:
            rsel, wsel, xsel = select.select(s_rsel, s_wsel, s_sel, timeout)
        except ValueError as e:
            bad_fds = set()
            for fd in s_sel:
                if isinstance(fd, int):
                    continue
                if fd.fileno() < 0:
                    bad_fds.add(fd)
            if bad_fds:
                for fd in bad_fds:
                    return ((self._FD_ERROR, fd),)
            else:
                raise
        except select.error as e:
            # Unspecified error, iterate all descriptors to identify
            events = deque()
            for _sock in s_rsel:
                try:
                    select.select([_sock], [], [_sock], 0.0)
                except:
                    events.append((self._FD_READ_ERROR, _sock))
            for _sock in s_wsel:
                try:
                    select.select([], [_sock], [_sock], 0.0)
                except:
                    events.append((self._FD_WRITE_ERROR, _sock))
            if events:
                return events
            else:
                # PLATFORM - IronPython - select.select sometimes
                # triggers this situation, unclear why - ignore for now
                self.__rlog.debug('unhandled select.error')
                _v_silent(Exception('unhandled select.error'))
        except IOError as e:
            # Return if interrupted by signal handler, not catching can
            # interfere e.g. with interactive use in a python interpreter
            if e.errno == errno.EINTR:
                return deque()
        else:
            events = deque()
            for fd in xsel:
                if fd not in s_sel:
                    continue
                events.append((self._FD_ERROR, fd))
            for fd in rsel:
                if fd not in s_rsel:
                    continue
                events.append((self._FD_READ, fd))
            for fd in wsel:
                if fd not in s_wsel:
                    continue
                events.append((self._FD_WRITE, fd))
            return events

    def _add_read_fd(self, fd):
        self.__rsel.add(fd)
        self.__sel.add(fd)
        self.__sel_changed = True

    def _add_write_fd(self, fd):
        self.__wsel.add(fd)
        self.__sel.add(fd)
        self.__sel_changed = True

    def _remove_read_fd(self, fd):
        self.__rsel.discard(fd)
        if fd not in self.__wsel:
            self.__sel.discard(fd)
        self.__sel_changed = True

    def _remove_write_fd(self, fd):
        self.__wsel.discard(fd)
        if fd not in self.__rsel:
            self.__sel.discard(fd)
        self.__sel_changed = True

    def _fd_done(self):
        self.__rsel.clear()
        self.__wsel.clear()
        self.__sel.clear()
