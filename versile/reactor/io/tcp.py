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

"""Reactor I/O components for TCP sockets."""
from __future__ import print_function, unicode_literals

import socket

from versile.internal import _vexport
from versile.common.iface import implements, multiface
from versile.reactor.io import VIOError
from versile.reactor.io.sock import *

__all__ = ['IVTCPSocket', 'VTCPClientSocket', 'VTCPClientSocketAgent',
           'VTCPListeningSocket', 'VTCPSocket']
__all__ = _vexport(__all__)


class IVTCPSocket(IVSocket):
    """Interface to a TCP :class:`versile.reactor.io.sock.IVSocket`\ ."""

    def _get_nodelay(self): pass
    def _set_nodelay(self, status): pass
    nodelay = property(_get_nodelay, _set_nodelay, None,
                       'Status whether TCP_NODELAY is set on the TCP socket.')

    def _get_keep_alive(self): pass
    def _set_keep_alive(self, status): pass
    keep_alive = property(_get_keep_alive, _set_keep_alive, None,
                          'Status whether SO_KEEPALIVE is set on ' +
                          'the TCP socket.')


@implements(IVTCPSocket)
class _VTCPBase(object):
    @classmethod
    def create_native(cls):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(0)
        return sock

    @classmethod
    def create_native_pair(cls, interface='127.0.0.1'):
        """Creates a native TCP socket pair

        :param interface: the interface to use when not using built-in
        :returns:         two paired native sockets (sock1, sock2)

        """
        if hasattr(socket, 'socketpair'):
            try:
                s1, s2 = socket.socketpair(socket.AF_INET)
                s1.setblocking(0)
                s2.setblocking(0)
            except socket.error:
                pass
            else:
                return (s1, s2)
        try:
            s = socket.socket(socket.AF_INET)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((interface, 0))
            s.listen(1)

            cs1 = socket.socket(socket.AF_INET)
            cs1.connect(s.getsockname())
            cs2, host2 = s.accept()
            if host2 == cs1.getsockname():
                s.close()
                return (cs1, cs2)
            else:
                s.close()
                raise VIOError('Could not create socket pair')
        except socket.error:
            raise VIOError('Could not create socket pair')

    def _get_no_delay(self):
        return self.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
    def _set_no_delay(self, status):
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, status)
    no_delay = property(_get_no_delay, _set_no_delay)

    def _get_keep_alive(self):
        return self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
    def _set_keep_alive(self, status):
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, status)
    keep_alive = property(_get_keep_alive, _set_keep_alive)


@multiface
class VTCPSocket(_VTCPBase, VSocketBase):
    """TCP version of :class:`versile.reactor.io.sock.VSocket`\ .

    Also implements :class:`IVTCPSocket`\ .

    """


@multiface
class VTCPClientSocket(_VTCPBase, VClientSocket):
    """TCP version of :class:`versile.reactor.io.sock.VClientSocket`\ .

    Also implements :class:`IVTCPSocket`\ .

    """


@multiface
class VTCPListeningSocket(_VTCPBase, VListeningSocket):
    """TCP version of :class:`versile.reactor.io.sock.VListeningSocket`\ .

    Also implements :class:`IVTCPSocket`\ .

    """


class VTCPClientSocketAgent(_VTCPBase, VClientSocketAgent):
    """TCP version of :class:`versile.reactor.io.sock.VClientSocketAgent`\ .

    Also implements :class:`IVTCPSocket`\ .

    """
