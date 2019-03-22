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

"""Reactor I/O components for Unix sockets."""
from __future__ import print_function, unicode_literals

import os
import socket
import tempfile

from versile.internal import _vexport
from versile.common.iface import implements, multiface
from versile.reactor.io import VIOError
from versile.reactor.io.sock import *

__all__ = ['IVUnixSocket', 'VUnixClientSocket', 'VUnixClientSocketAgent',
           'VUnixListeningSocket', 'VUnixSocket']
__all__ = _vexport(__all__)


class IVUnixSocket(IVSocket):
    """Interface to a Unix :class:`versile.reactor.io.sock.IVSocket`\ ."""
    pass


class _VUnixBase(object):
    @classmethod
    def create_native(cls):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.setblocking(0)
        return sock

    @classmethod
    def create_native_pair(cls):
        """Create native Unix socket pair

        :returns: two paired native sockets (sock1, sock2)

        """
        if hasattr(socket, 'socketpair'):
            try:
                s1, s2 = socket.socketpair(socket.AF_UNIX)
                s1.setblocking(0)
                s2.setblocking(0)
            except socket.error:
                pass
            else:
                return (s1, s2)
        try:
            s = socket.socket(socket.AF_UNIX)
            cs1 = socket.socket(socket.AF_UNIX)
        except socket.error:
            raise VIOError('Could not create Unix socket')
        try:
            tempdir = tempfile.mkdtemp()
            s_file = os.path.join(tempdir, 's_file.socket')
            c_file = os.path.join(tempdir, 'c_file.socket')
            s.bind(s_file)
            cs1.bind(c_file)
            s.listen(1)
            cs1.connect(s_file)
            cs2, h = s.accept()
            if cs1.getpeername() == s_file and cs2.getpeername() == c_file:
                return (cs1, cs2)
            else:
                raise VIOError('Could not create socket pair')
        except socket.error:
            raise VIOError('Could not create socket pair')
        finally:
            s.close()
            os.remove(s_file)
            os.remove(c_file)
            os.rmdir(tempdir)


@multiface
class VUnixSocket(_VUnixBase, VSocketBase):
    """Unix version of :class:`versile.reactor.io.sock.VSocket`\ .

    Also implements :class:`IVUnixSocket`\ .

    """


@multiface
class VUnixClientSocket(_VUnixBase, VClientSocket):
    """Unix version of :class:`versile.reactor.io.sock.VClientSocket`\ .

    Also implements :class:`IVUnixSocket`\ .

    """


@multiface
class VUnixListeningSocket(_VUnixBase, VListeningSocket):
    """Unix version of :class:`versile.reactor.io.sock.VListeningSocket`\ .

    Also implements :class:`IVUnixSocket`\ .

    """


class VUnixClientSocketAgent(_VUnixBase, VClientSocketAgent):
    """Unix version of :class:`versile.reactor.io.sock.VClientSocketAgent`\ .

    Also implements :class:`IVUnixSocket`\ .

    """
