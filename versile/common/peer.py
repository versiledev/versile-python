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

"""Classes for referencing communication peers."""
from __future__ import print_function, unicode_literals

import socket
import threading

from versile.internal import _vexport
from versile.common.util import VResult

__all__ = ['VPeer', 'VSocketPeer', 'VIPSocketPeer', 'VUnixSocketPeer',
           'VPipePeer']
__all__ = _vexport(__all__)


class VPeer(object):
    """Reference to a communication 'peer'.

    A 'peer' could be e.g. an Internet host referenced by its network
    address, or a serial device.

    """

    @property
    def native(self):
        """Returns a peer reference in Python native format.

        :returns: peer reference

        Return value is context specific, e.g. for a network host it
        could return the host address. If native addresses are not
        applicable, returns None.

        """
        return None


class VSocketPeer(VPeer):
    """Base class for socket hosts.

    :param family:   socket family, ref. :attr:`socket.socket.family`
    :type  family:   int
    :param socktype: socket type, ref. :attr:`socket.socket.type`
    :type  socktype: int
    :param proto:    socket protocol, ref. :attr:`socket.socket.proto`
    :type  proto:    int
    :param sockaddr: actual network-level socket address
    :param req_addr: requested (e.g. DNS name) socket address

    .. automethod:: _peer_picker

    """

    def __init__(self, family, socktype, proto, sockaddr, req_addr=None):
        self._family = family
        self._socktype = socktype
        self._proto = proto
        self._sockaddr = sockaddr
        self._req_addr = req_addr

    def create_socket(self):
        """Generates a socket which matches peer parameters.

        :returns: socket
        :rtype:   :class:`socket.socket`

        """
        return socket.socket(self._family, self._socktype, self._proto)

    @classmethod
    def lookup_all(cls, host, port, family=0, socktype=0, proto=0,
                    nowait=False):
        """Performs host/port lookup and returns all matching records.

        :param host:     domain name to look up
        :param port:     port number to look up
        :param family:   socket family, ref. :attr:`socket.socket.family`
        :type  family:   int
        :param socktype: socket type, ref. :attr:`socket.socket.type`
        :type  socktype: int
        :param proto:    socket protocol, ref. :attr:`socket.socket.proto`
        :type  proto:    int
        :param nowait:   if True perform non-blocking operation
        :type  nowait:   bool
        :returns:        list of all resolved matchins socket peers
        :rtype:          (:class:`VSocketPeer`\ ,) or
                         :class:`versile.common.util.VResult`

        Socket address is retreived by calling :func:`socket.getaddrinfo`\ .

        If *nowait* is False then this method blocks until DNS lookup
        has completed. If *nowait* is True, then a new thread is
        created to perform socket resolution, and the result is passed
        as a :class:`versile.common.util.VResult`\ .

        .. warning::

             When this method is called with *nowait* True as a
             non-blocking call, each pending unresolved call will
             consume one thread. The calling application must take
             responsibility to limit the number of pending calls in
             order not to exhaust thread pool or other available
             resources.

        """
        if not nowait:
            slist = socket.getaddrinfo(host, port, family, socktype, proto)
            peers = []
            for p_family, p_type, p_proto, _cname, p_sockaddr in slist:
                if p_family in (socket.AF_INET, socket.AF_INET6):
                    SockCls = VIPSocketPeer
                elif p_family == socket.AF_UNIX:
                    SockCls = VUnixSocketPeer
                else:
                    SockCls = VSocketPeer
                peers.append(SockCls(p_family, p_type, p_proto, p_sockaddr,
                                     (host, port)))
            return tuple(peers)

        # Handle non-blocking operation by running in a new thread
        result = VResult()
        def _lookup_all():
            try:
                peers = cls.resolve_all(host, port, family, socktype, proto)
            except Exception as e:
                result.push_exception(e)
            else:
                result.push_result(peers)
        thread = threading.Thread(target=_lookup_all)
        thread.start()
        return result

    @classmethod
    def lookup(cls, host, port, family=0, socktype=0, proto=0,
               peer_picker=None, nowait=False):
        """Performs host/port lookup and returns one matching record.

        :param peer_picker: function which picks one peer (or None)
        :type  peer_picker: callable

        Other arguments are similar to :meth:`lookup_all`\ .

        The method calls :meth:`lookup_all` to generate a list of all
        matching peers, and returns one of the matches. If
        *peer_picker* is None, then :meth:`_peer_picker` is called to
        generate one peer result from the list (or None if no
        matches). if *peer_picker* is provided then that function is
        called instead, and the function should take arguments and
        return peer similar to :meth:`_peer_picker`\ .

        Asynchronous lookup behavior and related **warnings** are
        similar to :meth:`lookup_all`\ .

        """
        if peer_picker is None:
            peer_picker = cls._peer_picker

        if not nowait:
            peers = cls.lookup_all(host, port, family, socktype, proto)
            return peer_picker(peers)

        # Handle non-blocking operation by running in a new thread
        result = VResult()
        def _lookup():
            try:
                peers = cls.lookup_all(host, port, family, socktype, proto)
                peer = peer_picker(peers)
            except Exception as e:
                result.push_exception(e)
            else:
                result.push_result(peer)
        thread = threading.Thread(target=_lookup)
        thread.start()
        return result

    @classmethod
    def _peer_picker(cls, peers):
        """Internal call to choose one peer from a list of looked up peers.

        :param peers: list of peers
        :type  peers: (:class:`VSocketPeer`\ ,)
        :returns:     chosen peer (or None)
        :rtype:       :class:`VSocketPeer`

        The default implementation filters *peers* so that:

        * If an IP based protocol is in the set, that one is used
        * If a TCP protocol is available, only those are considered
        * If both IPv4 and IPv6 are returned, IPv4 is used
        * If a stream socket type is in the set, that one is used
        * Of remaining peers in list, the first one is used

        """
        ip4_peers = [p for p in peers if p.family == socket.AF_INET]
        if ip4_peers:
            peers = ip4_peers
        else:
            ip6_peers = [p for p in peers if p.family == socket.AF_INET6]
            if ip6_peers:
                peers = ip6_peers

        tcp_peers = [p for p in peers if p.proto == socket.IPPROTO_TCP]
        if tcp_peers:
            peers = tcp_peers

        s_peers = [p for p in peers if p.socktype == socket.SOCK_STREAM]
        if s_peers:
            peers = s_peers

        if peers:
            return peers[0]
        else:
            return None

    @classmethod
    def from_sock(cls, sock, sockaddr=None, req_addr=None):
        """Creates a :class:`VSocketPeer` for a socket and address.

        :param sock:     native socket
        :param sockaddr: native socket address
        :param req_addr: requested socket address (e.g. DNS lookup)
        :raises:         :exc:`exceptions.IOError`

        If sockaddr is None then :meth:`socket.socket.getpeername`\ is
        called to resolve socket per address. Raises an exception if
        socket address cannot be resolved with
        :meth:`socket.socket.getpeername`\ .

        """
        if sockaddr is None:
            sockaddr = sock.getpeername()
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            SockCls = VIPSocketPeer
        elif sock.family == socket.AF_UNIX:
            SockCls = VUnixSocketPeer
        else:
            SockCls = VSocketPeer
        return SockCls(sock.family, sock.type, sock.proto, sockaddr)

    @property
    def family(self):
        """Socket family, as used by :class:`socket.socket`\ ."""
        return self._family

    @property
    def socktype(self):
        """Socket type, as used by :class:`socket.socket`\ ."""
        return self._socktype

    @property
    def proto(self):
        """Socket protocol, as used by :class:`socket.socket`\ ."""
        return self._proto

    @property
    def address(self):
        """Socket address"""
        return self._sockaddr

    @property
    def req_addr(self):
        """Requested socket address."""
        return self._req_addr

    @property
    def native(self):
        """Native socket address"""
        return self.address

    def __str__(self):
        return 'Socket:%s' % str(self.native)


class VIPSocketPeer(VSocketPeer):
    """Base class for IP socket hosts."""

    def __init__(self, family, socktype, proto, sockaddr, req_addr=None):
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise TypeError('Not an IP socket')
        super(VIPSocketPeer, self).__init__(family, socktype, proto, sockaddr,
                                            req_addr)

    def is_local(self):
        """Returns True if socket address is a 'localhost'

        :returns: True if socket address is a 'localhost'
        :rtype:   bool

        """
        if self._family == socket.AF_INET:
            # Test IPv4 address is in 127.0.0.0/8
            components = self.host.split('.')
            return (components and components[0] == '127')
        else:
            # Test IPv6 address is ::1
            if self.host[-1] != '1':
                return False
            for c in self.host[:-1]:
                if c not in '0:':
                    return False
            else:
                return True

    @property
    def host(self):
        """The :class:`VSocketPeer`\ \'s 'host' component"""
        return self._sockaddr[0]

    @property
    def req_host(self):
        """The peer requested addresses 'host' component (or None)."""
        if self._req_addr is not None:
            return self._req_addr[0]
        return None

    @property
    def port(self):
        """The :class:`VSocketPeer`\ \'s 'port' component"""
        return self._sockaddr[1]

    @property
    def bound(self):
        """True if the address is a bound address."""
        return (self.port != 0)

    @property
    def ip_version(self):
        """Returns IP version number.

        :returns: IP version number
        :rtype:   int

        """
        if self._family == socket.AF_INET:
            return 4
        else:
            return 6

    @classmethod
    def from_sock(cls, sock, sockaddr=None, req_addr=None):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            raise TypeError('Not an IP socket')
        else:
            return VSocketPeer.from_sock(sock, sockaddr, req_addr)

    def __str__(self):
        if self.ip_version == 4:
            return 'IPv4:%s:%i' % (self.host, self.port)
        else:
            return 'IPv6:[%s]:%i' % (self.host, self.port)


class VUnixSocketPeer(VSocketPeer):
    """Base class for Unix socket hosts."""

    def __init__(self, family, socktype, proto, sockaddr, req_addr=None):
        if family != socket.AF_UNIX:
            raise TypeError('Not a Unix socket')
        s_init = super(VUnixSocketPeer, self).__init__
        s_init(family, socktype, proto, sockaddr, req_addr)

    @property
    def host(self):
        """The :class:`VSocketPeer`\ \'s 'host' component"""
        return self._sockaddr

    @property
    def req_host(self):
        """The peer requested addresses 'host' component (or None)."""
        return self._req_addr

    @property
    def bound(self):
        """True if the address is a bound address."""
        return bool(self._sockaddr)

    @classmethod
    def from_sock(cls, sock, sockaddr=None, req_addr=None):
        if sock.family != socket.AF_UNIX:
            raise TypeError('Not a Unix socket')
        else:
            return VSocketPeer.from_sock(sock, sockaddr, req_addr)

    def __str__(self):
        return 'Unix:\'%s\'' % self.host


class VPipePeer(VPeer):
    """OS pipe peer connection."""

    @property
    def native(self):
        """Native socket address"""
        return None

    def __str__(self):
        return 'OS pipe'
