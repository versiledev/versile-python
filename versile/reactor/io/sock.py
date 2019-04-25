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
"""Components for reactor-driven socket I/O."""
from __future__ import print_function, unicode_literals

import errno
import socket
import sys
import weakref

from versile.internal import _b2s, _s2b, _vplatform, _vexport, _v_silent
from versile.internal import _pyver
from versile.common.iface import implements, abstract, final, peer
from versile.common.log import VLogger
from versile.common.peer import VSocketPeer
from versile.common.util import VByteBuffer
from versile.reactor import IVReactorObject
from versile.reactor.io import VByteIOPair, VIOClosed
from versile.reactor.io import VIOCompleted, VIOLost, VIOError, VIOException
from versile.reactor.io import VFIOCompleted, VFIOLost, IVByteIO
from versile.reactor.io import IVSelectable, IVSelectableIO, IVByteInput
from versile.reactor.io import IVByteProducer, IVByteConsumer
from versile.reactor.io import VHalfClose, VNoHalfClose
from versile.reactor.io import VIOControl, VIOMissingControl
from versile.reactor.io.descriptor import IVDescriptor

__all__ = ['IVClientSocket', 'IVSocket', 'VClientSocket',
           'VClientSocketAgent', 'VClientSocketFactory',
           'VListeningSocket', 'VSocket', 'VSocketBase']
__all__ = _vexport(__all__)

# Workaround for Windows-specific error codes
if sys.platform == _b2s(b'win32') or _vplatform == 'ironpython':
    _errno_block   = (errno.EWOULDBLOCK, errno.WSAEWOULDBLOCK)
    _errno_connect = (errno.EINPROGRESS, errno.WSAEWOULDBLOCK)
else:
    _errno_block = (errno.EWOULDBLOCK,)
    _errno_connect = (errno.EINPROGRESS,)


class IVSocket(IVDescriptor, IVSelectable):
    """Interface for a general socket descriptor."""

    @classmethod
    def create_native(cls):
        """Creates a native socket.

        :returns: :class:`socket.socket`

        """

    @classmethod
    def create_native_pair(cls):
        """Creates two paired (connected) sockets.

        :returns: socket pair
        :rtype:   :class:`socket.socket`\ , :class:`socket.socket`
        :raises:  :exc:`versile.reactor.io.VIOError`

        """


class IVClientSocket(IVSocket, IVByteIO):
    """Interface to a client socket."""

    def connect(self, peer):
        """Connect client socket to a peer.

        :param peer: peer to connect to
        :type  peer: :class:`versile.common.peer.VSocketPeer`
        :returns:    True if success
        :rtype:      bool or :class:`versile.common.pending.VPending`

        """


@abstract
@implements(IVReactorObject, IVSocket)
class VSocketBase(object):
    """Base class for reactor-driven sockets.

    :param reactor:     reactor handling socket events
    :param sock:        native socket
    :type  sock:        :class:`socket.socket`
    :param hc_pol:      half-close policy
    :type  hc_pol:      :class:`versile.reactor.io.VHalfClosePolicy`
    :param close_cback: callback when closed (or None)
    :type  close_cback: callable

    The socket is set to a non-blocking mode. If *sock* is None then a
    socket is created with :meth:`create_native`\ .

    *hc_pol* determines whether the socket object allows closing only
    the socket input or output. If *hc_pol* is None an
    :class:`versile.reactor.io.VHalfClose` instance is used.

    This class is abstract and not intended to be directly
    instantiated. Instead, :class:`VSocket` or derived classes should
    be used.

    """

    def __init__(self, reactor, sock=None, hc_pol=None, close_cback=None):
        self.__reactor = reactor
        if not sock:
            sock = self.create_native()
        sock.setblocking(False)
        self.__sock = sock
        if hc_pol is None:
            hc_pol = VHalfClose()
        self.__hc_pol = hc_pol
        self._sock_close_cback = close_cback
        self._sock_sent_close_cback = False

        # Set up a socket logger for convenience
        self.__logger = VLogger(prefix='Sock')
        self.__logger.add_watcher(self.reactor.log)

    def __del__(self):
        if self._sock_close_cback and not self._sock_sent_close_cback:
            try:
                self._sock_close_cback()
            except Exception as e:
                self.log.debug('Close callback failed')
                _v_silent(e)

    @abstract
    def close_io(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandle.close_io`\ ."""
        self._sock_shutdown_rw()
        self.log.debug('close()')
        try:
            self.sock.close()
        except socket.error as e:
            _v_silent(e)
        return True

    def fileno(self):
        """See :meth:`versile.reactor.io.IVSelectable.fileno`\ ."""
        if not self.__sock:
            raise VIOError('No socket')
        try:
            fd = self.__sock.fileno()
        except socket.error:
            return -1
        else:
            return fd

    @classmethod
    def create_native(cls):
        """Creates a native socket.

        :returns: native socket

        The created socket is set up as non-blocking.

        """
        sock = socket.socket()
        sock.setblocking(0)
        return sock

    @classmethod
    def create_native_pair(cls):
        """Returns two native paired (connected) sockets.

        :returns: two paired native sockets
        :rtype:   :class:`socket.socket`\ , :class:`socket.socket`
        :raises:  :exc:`versile.reactor.io.VIOError`

        """
        # Use native socket.socketpair() if available
        if hasattr(socket, 'socketpair'):
            try:
                pair = socket.socketpair()
            except:
                raise VIOError('Could not create socket pair')
            else:
                return pair
        # Use local TCP socket implementation as a workaround
        from versile.reactor.io.tcp import VTCPSocket
        return VTCPSocket.create_native_pair()


    @property
    def reactor(self):
        """See :attr:`versile.reactor.IVReactorObject.reactor`\ ."""
        return self.__reactor

    @property
    def sock(self):
        """The :class:`VSocketBase`\ \'s associated native socket."""
        return self.__sock

    @property
    def log(self):
        """Logger for the socket (:class:`versile.common.log.VLogger`\ )."""
        return self.__logger

    def _set_logger(self, logger=None, safe=False):
        """Replace current logger with a different logger.

        If logger is None, a non-connected logger is put in place.

        """
        if not safe:
            self.reactor.schedule(0.0, self._set_logger, logger, True)
            return
        if logger is None:
            logger = VLogger()
        self.__logger = logger

    def _get_hc_pol(self): return self.__hc_pol
    def _set_hc_pol(self, policy): self.__hc_pol = policy
    __doc = 'See :meth:`versile.reactor.io.IVByteIO.half_close_policy`'
    half_close_policy = property(_get_hc_pol, _set_hc_pol, doc=__doc)
    del(__doc)

    def _sock_shutdown_read(self):
        """Internal call to shut down the socket for reading."""
        try:
            self.stop_reading()
            self.sock.shutdown(socket.SHUT_RD)
        except socket.error as e:
            _v_silent(e)

    def _sock_shutdown_write(self):
        """Internal call to shut down the socket for writing."""
        try:
            self.stop_writing()
            self.sock.shutdown(socket.SHUT_WR)
        except socket.error as e:
            _v_silent(e)

    def _sock_shutdown_rw(self):
        """Internal call to shut down the socket for reading and writing."""
        try:
            if not self._sock_in_closed:
                self.stop_reading()
            if not self._sock_out_closed:
                self.stop_writing()
            self.sock.shutdown(socket.SHUT_RDWR)
        except socket.error as e:
            _v_silent(e)


    def _sock_replace(self, sock):
        """Internal call to replace the native socket with *sock*\ ."""
        self.__sock = sock

    def _connect_transform(self, sock):
        """Returns a transformed native socket.

        :param sock: socket to transform
        :type  sock: :class:`socket.socket`
        :returns:    transformed socket
        :rtype:      :class:`socket.socket`

        Called internally when the socket is connected. The native
        socket is then replaced with the return value of this
        method. Default returns the same socket, derived classes can
        override.

        """
        return sock


@abstract
@implements(IVSelectableIO)
class VSocket(VSocketBase):
    """Base class for a socket with methods for low-level I/O.

    For construction arguments see :class:`VSocketBase`\ .

    """

    def __init__(self, reactor, sock=None, hc_pol=None, close_cback=None):
        super_init = super(VSocket, self).__init__
        super_init(reactor=reactor, sock=sock, hc_pol=hc_pol,
                   close_cback=close_cback)
        self._sock_in_closed = self._sock_out_closed = False
        self._sock_in_closed_reason = self._sock_out_closed_reason = None

        self._sock_enabled   = False # State for enabled I/O on socket
        self._sock_connected = False # State when low-level peer connection
        self._sock_active    = False # State when any handshake was completed
        self._sock_verified  = False # True if data has been sent or received
        self._was_connected  = False # Has socket had a 'connected' status
        self._sock_peer = None       # Socket peer for connected client socket

    def _set_sock_enabled(self):
        """Enables socket monitoring by reacttor.

        Used internally by the socket to set internal status to
        'enabled' and initiate reactor reading/writing on the native
        socket.

        """
        if not self._sock_enabled:
            self._sock_enabled = True
            self.start_reading()
            self.start_writing()
            self._sock_was_enabled()

    def _set_sock_connected(self):
        """Sets the socket's status to 'connected'.

        Used internally to inform the socket has been connected to a peer.

        """
        if self._sock_enabled and not self._sock_connected:
            if self._sock_conclude_connect():
                self._sock_connected = True
                self._was_connected = True
                sock = self._connect_transform(self.sock)
                if sock is not self.sock:
                    self._sock_replace(sock)
                    self.log.debug('Replaced native socket')
                self._sock_was_connected()
            else:
                self.close_io(VFIOLost())
            self.log.debug('Connected')

    def _set_sock_active(self):
        """Sets the socket's status to 'active'.

        Sets the socket's status to 'active'. This should follow any
        post-connect handshake, e.g. :term:`TLS` sockets should only
        change status to active once the secure communication layer
        has been negotiated.

        """
        self.log.debug('Activating for read/write')
        self._sock_active = True
        self.start_reading()
        self.start_writing()

    def _sock_was_enabled(self):
        """Called internally when the socket has been enabled.

        Default does nothing, derived classes can override.

        """
        pass

    def _sock_conclude_connect(self):
        """Called internally before completing connecting with a peer.

        :returns: True if connect can finish
        :rtype:   bool

        Default starts reading/writing and returns True.

        """
        self.start_reading()
        self.start_writing()
        return True

    def _sock_was_connected(self):
        """Called internally after the socket was connected to a peer.

        Default does nothing.

        """
        pass

    def _sock_do_activation_read(self):
        """Perform activation handshake read.

        :returns: True if pre-active handshake was completed
        :rtype:   bool

        Default returns True.

        """
        return True

    def _sock_do_activation_write(self):
        """Perform activation handshake write.

        :returns: True if pre-active handshake was completed
        :rtype:   bool

        Default returns True.

        """
        return True

    def _sock_conclude_activation(self):
        """Called internally before completing activation.

        :returns: True if activation can complete
        :rtype:   bool

        Default returns True.

        """
        return True

    def _sock_activated(self):
        """Called internally after socket was activated.

        Default does nothing.

        """
        pass

    @abstract
    def active_do_read(self):
        """Perform read operation when active.

        Similar to :meth:`do_read` and called by :meth:`do_read` when
        socket status is 'active'.

        Abstract method, derived classes must override.

        """
        raise NotImplementedError()

    @abstract
    def active_do_write(self):
        """Perform write operation when active.

        Similar to :meth:`do_write` and called by :meth:`do_write`
        when socket status is 'active'.

        Abstract method, derived classes must override.

        """
        raise NotImplementedError()

    def close_input(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandleInput.close_input`\ ."""
        if self._sock_out_closed or not self.half_close_policy.half_in:
            return self.close_io(reason)
        elif not self._sock_in_closed:
            self.log.debug('read shutdown')
            self._sock_shutdown_read()
            self._sock_in_closed = True
            self._sock_in_closed_reason = reason
            self._input_was_closed(reason)

    def _input_was_closed(self, reason):
        """Called internally when input was closed, default does nothing."""
        pass

    def close_output(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandleOutput.close_output`\ ."""
        if self._sock_in_closed or not self.half_close_policy.half_out:
            return self.close_io(reason)
        elif not self._was_connected:
            # If socket has not yet been connected, close fully
            return self.close_io(reason)
        elif not self._sock_out_closed:
            self.log.debug('write shutdown')
            self._sock_shutdown_write()
            self._sock_out_closed = True
            self._sock_out_closed_reason = reason
            self._output_was_closed(reason)
        return self._sock_out_closed

    def _output_was_closed(self, reason):
        """Called internally when output was closed, default does nothing."""
        pass

    def close_io(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandle.close_io`\ ."""
        if not (self._sock_in_closed and self._sock_out_closed):
            in_was_closed = self._sock_in_closed
            out_was_closed = self._sock_out_closed

            #self.log.debug('rw shutdown')
            self._sock_shutdown_rw()
            self.log.debug('close()')
            try:
                self.sock.close()
            except socket.error:
                pass
            self._sock_in_closed = self._sock_out_closed = True
            self._sock_in_closed_reason = self._sock_out_closed_reason = reason
            if not in_was_closed:
                self._input_was_closed(reason)
            if not out_was_closed:
                self._output_was_closed(reason)
            if (self._sock_close_cback and self._sock_in_closed
                and self._sock_out_closed):
                try:
                    self._sock_close_cback()
                except Exception as e:
                    self.log.debug('Close callback failed')
                    _v_silent(e)
                finally:
                    self._sock_sent_close_cback = True
        return self._sock_in_closed and self._sock_out_closed

    def do_read(self):
        """See :meth:`versile.reactor.io.IVByteHandleInput.do_read`\ ."""
        try:
            if self._sock_in_closed:
                self.stop_reading()
            elif not self._sock_enabled:
                self.stop_reading()
            elif not self._sock_connected:
                self.stop_reading()
            elif not self._sock_active:
                if self._sock_do_activation_read():
                    if self._sock_conclude_activation():
                        self._set_sock_active()
                        self._sock_activated()
                    else:
                        self.close_io(VFIOLost())
            else:
                self.active_do_read()
        except VIOCompleted as e:
            self.close_input(VFIOCompleted(e))
        except VIOLost as e:
            self.close_input(VFIOLost(e))

    def read_some(self, max_len):
        """See :meth:`versile.reactor.io.IVByteInput.read_some`"""
        if not self.was_connected:
            raise VIOError('Socket was not connected')
        if self._sock_in_closed:
            if isinstance(self._sock_in_closed_reason, VFIOCompleted):
                raise VIOCompleted()
            else:
                raise VIOLost()
        if not self.sock:
            raise VIOError('No socket')
        try:
            if _pyver == 2:
                data = _s2b(self.sock.recv(max_len))
            else:
                data = self.sock.recv(max_len)
        except IOError as e:
            if e.errno in _errno_block:
                return b''
            elif (e.errno in (errno.EPIPE, errno.ENOTCONN)
                  and not self._sock_verified):
                    # ISSUE - these have been seen to be raised after
                    # socket thinks it is connected due to select() event,
                    # however ignoring it causes the connection to be
                    # 'resumed'. For now we log a message and resume.
                    self.log.debug('Ignoring post-connect read errno %s'
                                  % e.errno)
                    return b''
            else:
                self.log.debug('Read got errno %s' % e.errno)
                raise VIOError('Socket read error, errno %s' % e.errno)
        else:
            if not data:
                raise VIOCompleted()
            self._sock_verified = True
            return data

    def start_reading(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteInput.start_reading`\ ."""
        if not self._sock_in_closed and self._sock_enabled and self.sock:
            self.reactor.add_reader(self, internal=internal)
            self._started_reading()

    @final
    def stop_reading(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteInput.start_reading`\ ."""
        if self.sock:
            self.reactor.remove_reader(self, internal=internal)

    def do_write(self):
        """See :meth:`versile.reactor.io.IVByteHandleOutput.do_write`\ ."""
        try:
            if self._sock_out_closed:
                self.stop_writing()
            elif not self._sock_enabled:
                self.stop_reading()
            elif not self._sock_connected:
                # Write event indicates socket is now connected
                if not self._sock_peer:
                    try:
                        self._sock_peer = VSocketPeer.from_sock(self.sock)
                    except IOError as e:
                        # ISSUE - current handling of this exc causes
                        # reactor to loop until getpeername resolves
                        self.log.debug('getpeername failed errno %s' % e.errno)
                        return
                self._set_sock_connected()
            elif not self._sock_active:
                if self._sock_do_activation_write():
                    if self._sock_conclude_activation():
                        self._set_sock_active()
                        self._sock_activated()
                    else:
                        self.close_io(VFIOLost())
            else:
                self.active_do_write()
        except VIOCompleted as e:
            self.close_input(VFIOCompleted(e))
        except VIOLost as e:
            self.close_input(VFIOLost(e))

    def write_some(self, data):
        """See :meth:`versile.reactor.io.IVByteOutput.write_some`\ ."""
        if not self.was_connected:
            raise VIOError('Socket not connected')
        if self._sock_out_closed:
            if isinstance(self._sock_out_closed_reason, VFIOCompleted):
                raise VIOCompleted()
            else:
                raise VIOLost()
        if not self.sock:
            raise VIOError('No socket')
        try:
            if _pyver == 2:
                num_written = self.sock.send(_b2s(data))
            else:
                num_written = self.sock.send(data)
        except IOError as e:
            if e.errno in _errno_block:
                return 0
            elif (e.errno in (errno.EPIPE, errno.ENOTCONN)
                  and not self._sock_verified):
                # ISSUE - these have been seen to be raised after
                # socket thinks it is connected due to select() event,
                # however ignoring it causes the connection to be
                # 'resumed'. For now we log a message and resume.
                self.log.debug('Ignoring post-connect write errno %s'
                              % e.errno)
                return 0
            else:
                self.log.debug('Write got errno %s' % e.errno)
                raise VIOError('Socket write error, errno %s' % e.errno)
        else:
            self._sock_verified = True
            return num_written

    @final
    def start_writing(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteOutput.start_writing`\ ."""
        if not self._sock_out_closed and self._sock_enabled and self.sock:
            self.reactor.add_writer(self, internal=internal)

    @final
    def stop_writing(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteOutput.stop_writing`\ ."""
        if self.sock:
            self.reactor.remove_writer(self, internal=internal)

    @property
    def was_connected(self):
        """See :attr:`IVConnectedSocket.was_connected`"""
        return self._was_connected

    def _started_reading(self):
        """Called internally before :meth:`start_reading` returns.

        Default does nothing, derived classes can override.

        """
        pass


@abstract
@implements(IVClientSocket)
class VClientSocket(VSocket):
    """Client socket which performs byte channel socket I/O.

    :param connected: if True socket is already connected
    :type  connected: bool

    For other construction arguments see :class:`VSocket`\ . If *sock*
    is set, it must be a non-connected socket which can be connected
    with :meth:`socket.socket.connect`\ .

    """

    def __init__(self, reactor, sock=None, hc_pol=None, close_cback=None,
                 connected=False):
        super_init = super(VClientSocket, self).__init__
        if hc_pol is None:
            hc_pol = VHalfClose()
        super_init(reactor=reactor, sock=sock, hc_pol=hc_pol,
                   close_cback=close_cback)

        if connected:
            def _connect(sock):
                sock._set_sock_enabled()
                try:
                    sock._sock_peer = VSocketPeer.from_sock(sock.sock)
                except IOError as e:
                    sock.start_writing()
                else:
                    sock._set_sock_connected()
            self.reactor.execute(_connect, self)

    def connect(self, peer):
        """Connects to a peer.

        :param peer: peer to connect to
        :type  peer: :class:`versile.common.peer.VSocketPeer`
        :raises:     :exc:`versile.reactor.io.VIOError`

        Default creates a new native socket which is set up with
        *peer* socket parameters and performs :func:`sock.connect` on
        *peer.address*. The :class:`VClientSocket` then registers
        itself with the the reactor for writing to detect connect
        success. Upon immediate failure the socket is closed. Derived
        classes can override.

        """
        try:
            sock = peer.create_socket()
            sock.setblocking(False)
            # The discarded socket is discarded, so we close before replacing
            if self.sock:
                try:
                    self.sock.close()
                except socket.error as e:
                    _v_silent(e)
            self._sock_replace(sock)
            if not self._can_connect(peer):
                self.close_io(VFIOLost())
                raise VIOError('Not allowed to connect to host')
            self._sock_peer = peer
            self._set_sock_enabled()
            self.sock.connect(peer.address)
        except IOError as e:
            if e.errno in _errno_connect:
                self.start_writing()
            else:
                raise
        except Exception as e:
            self.log.debug('Connect exception')
            self.close_io(VFIOLost())
        else:
            self._set_sock_connected()

    def _can_connect(self, peer):
        """Called internally to validate whether a connection can be made.

        :param peer: peer to connect to
        :type  peer: :class:`versile.common.peer.VPeer`
        :returns:    True if connection is allowed
        :rtype:      bool

        Default returns True.

        """
        return True


@implements(IVByteInput)
class VListeningSocket(VSocket):
    """Base class for socket which listens for inbound connections.

    The object is set up on a native socket which is bound to a port
    and set up for listening. The event handler will accept inbound
    connections and hand off resulting client sockets to
    :meth:`accepted`\ .

    :param reactor:      the socket's event handler
    :type  reactor:      :class:`versile.reactor.IVDescriptorReactor`
    :param sock:         native socket (must be bound and listening)
    :type  sock:         :class:`socket.socket`
    :param bound:        if True *sock* is already bound
    :param listening:    if True *sock* is already listening
    :param factory:      factory for client sockets on new connections
    :type  factory:      :class:`VClientSocketFactory`
    :param controlled:   if True listening socket is controlled
    :type  controlled:   bool
    :param accept_cback: callback when client accepted (or None)
    :type  accept_cback: callable
    :param client_close: callback when client closed (or None)
    :type  client_close: callable

    """

    def __init__(self, reactor, sock, bound=False, listening=False,
                 factory=None, controlled=False, accept_cback=None,
                 client_close=None):
        super_init = super(VListeningSocket, self).__init__
        super_init(reactor=reactor, sock=sock, hc_pol=VNoHalfClose())

        self._bound = bound
        self._listening = listening
        self._factory = factory
        self._controlled = controlled
        self._can_accept = not controlled
        self._accept_cback = accept_cback
        self._client_close = client_close

        if bound and listening:
            self._set_sock_enabled()
            self._set_sock_connected()
            self._set_sock_active()

    def bind(self, host):
        """Bind to network interface.

        :param host: native socket address

        This method should not be called if the socket is already bound.

        """
        if self._bound:
            raise VIOError('Socket already bound')
        self.sock.bind(host)
        self._bound = True

    def listen(self, num_listen):
        """Start listening on bound network interface.

        :param num_listen: max pending connection requests
        :type  num_listen: int

        """
        if not self._bound:
            raise VIOError('Socket not bound')
        if self._listening:
            raise VIOError('Socket already listening')
        self.sock.listen(num_listen)
        self._listening = True
        self._set_sock_enabled()
        self._set_sock_connected()
        self._set_sock_active()

    def start_writing(self):
        """Does nothing (listening socket does not support writing)."""
        pass

    def stop_writing(self):
        """Does nothing (listening socket does not support writing)."""
        pass

    @final
    def active_do_read(self):
        """Detects connecting client sockets as 'read' events.

        Accepts an incoming connection and calls :meth:`accepted` with
        the native client socket of the new client connection.

        """
        if not self._can_accept:
            self.stop_reading()
        try:
            sock, address = self.sock.accept()
        except Exception as e:
            self.log.debug('Socket accept() exception, dropping connection')
        else:
            if self._controlled:
                self._can_accept = False
                self.stop_reading()
            self.accepted(sock, address)
            if self._accept_cback:
                try:
                    self._accept_cback()
                except Exception as e:
                    self.log.debug('Accept callback failed')
                    _v_silent(e)

    @abstract
    def accepted(self, sock, address):
        """Called by the listener when a client socket was accepted.

        :param sock:    client socket for accepted connection
        :type  sock:    :class:`socket.socket`
        :param address: address of the connected socket

        Default instantiates with a factory (if received), otherwise
        raises an exception. Derived classes may override.

        """
        if self._factory:
            c_sock = self._factory.build(sock=sock,
                                         close_cback=self._client_close)
        else:
            raise NotImplementedError('No socket factory class')

    def can_accept(self, thread_sep=False):
        """If listener is controlled, authorize to accept a client socket.

        This authorizes the listener to perform only one single
        accept() operation. If the listener is not controlled, this call
        has no effect.

        This call is thread safe, as it uses the socket's reactor for
        thread separation.

        """
        if not self._controlled:
            return
        if not thread_sep:
            self.reactor.schedule(0.0, self.can_accept, True)
            return
        if not self._can_accept:
            self._can_accept = True
            self.start_reading()

@abstract
@implements(IVReactorObject)
class VClientSocketFactory(object):
    """Base class for a :class:`VClientSocket` factory for listeners.

    :param reactor: reactor for socket event handling

    """

    def __init__(self, reactor):
        self.__reactor = reactor

    @abstract
    def build(self, sock, close_cback=None):
        """Creates a :class:`VClientSocket` for a native socket.

        :param sock:        native socket
        :type  sock:        :class:`socket.socket`
        :param close_cback: callback when socket is closed (or None)
        :type  close_cback: callable
        :returns:           created client socket
        :rtype:             :class:`VClientSocket`

        The returned client socket should be in a 'connected' state.

        """
        raise NotImplementedError()

    @property
    def reactor(self):
        """See :class:`versile.reactor.IVReactorObject`\ ."""
        return self.__reactor


class VClientSocketAgent(VClientSocket):
    """A :class:`VClientSocket` with a byte producer/consumer interface.

    :param max_read:  max bytes fetched per socket read
    :type  max_read:  int
    :param max_write: max bytes written per socket send
    :type  max_write: int
    :param wbuf_len:  buffer size of data held for writing (or None)
    :type  wbuf_len:  int

    *max_read* is also the maximum size of the buffer for data read
    from the socket (so maximum bytes read in one read operation is
    *max_read* minus the amount of data currently held in the receive
    buffer).

    If *wbuf_len* is None then *max_write* is used as the buffer size.

    """
    def __init__(self, reactor, sock=None, hc_pol=None, close_cback=None,
                 connected=False, max_read=0x4000, max_write=0x4000,
                 wbuf_len=None):
        self._max_read = max_read
        self._max_write = max_write
        self._wbuf = VByteBuffer()
        if wbuf_len is None:
            wbuf_len = max_write
        self._wbuf_len = wbuf_len

        self._ci = None
        self._ci_eod = False
        self._ci_eod_clean = None
        self._ci_producer = None
        self._ci_consumed = 0
        self._ci_lim_sent = 0
        self._ci_aborted = False

        self._pi = None
        self._pi_closed = False
        self._pi_consumer = None
        self._pi_produced = 0
        self._pi_prod_lim = 0
        self._pi_buffer = VByteBuffer()
        self._pi_aborted = False

        # Parent __init__ must be called after local attributes are
        # initialized due to overloaded methods called during construction
        super_init = super(VClientSocketAgent, self).__init__
        super_init(reactor=reactor, sock=sock, hc_pol=hc_pol,
                   close_cback=close_cback, connected=connected)

    @property
    def byte_consume(self):
        """Holds a :class:`IVByteConsumer` interface to the socket."""
        if not self._ci:
            ci = _VSocketConsumer(self)
            self._ci = weakref.ref(ci)
            return ci
        else:
            ci = self._ci()
            if ci:
                return ci
            else:
                ci = _VSocketConsumer(self)
                self._ci = weakref.ref(ci)
                return ci

    @property
    def byte_produce(self):
        """Holds a :class:`IVByteProducer` interface to the socket."""
        if not self._pi:
            pi = _VSocketProducer(self)
            self._pi = weakref.ref(pi)
            return pi
        else:
            pi = self._pi()
            if pi:
                return pi
            else:
                pi = _VSocketProducer(self)
                self._pi = weakref.ref(pi)
                return pi

    @property
    def byte_io(self):
        """Byte interface (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.byte_consume, self.byte_produce)

    def _can_connect(self, peer):
        """Called internally to validate whether a connection can be made.

        :param peer: peer to connect to
        :type  peer: :class:`versile.common.peer.VPeer`
        :returns:    True if connection is allowed
        :rtype:      bool

        If the socket is connected to a byte consumer, sends a control
        request for 'can_connect(peer)'. If that control message
        returns a boolean, this is used as the _can_connect
        result. Otherwise, True is returned.

        """
        if self._pi_consumer:
            try:
                return self._pi_consumer.control.can_connect(peer)
            except VIOMissingControl:
                return True
        else:
            return True

    def _sock_was_connected(self):
        super(VClientSocketAgent, self)._sock_was_connected()
        if self._p_consumer:
            # Notify producer-connected chain about 'connected' status
            control = self._p_consumer.control
            def notify():
                try:
                    control.connected(self._sock_peer)
                except VIOMissingControl:
                    pass
            self.reactor.schedule(0.0, notify)

    @peer
    def _c_consume(self, buf, clim):
        if self._ci_eod:
            raise VIOClosed('Consumer already reached end-of-data')
        elif not self._ci_producer:
            raise VIOError('No connected producer')
        elif self._ci_consumed >= self._ci_lim_sent:
            raise VIOError('Consume limit exceeded')
        elif not buf:
            raise VIOError('No data to consume')

        max_cons = self._wbuf_len - len(self._wbuf)
        max_cons = min(max_cons, self._ci_lim_sent - self._ci_consumed)
        if clim is not None and clim > 0:
            max_cons = min(max_cons, clim)

        was_empty = not self._wbuf
        indata = buf.pop(max_cons)
        self._wbuf.append(indata)
        self._ci_consumed += len(indata)
        if was_empty:
            self.start_writing(internal=True)
        return self._ci_lim_sent

    def _c_end_consume(self, clean):
        if self._ci_eod:
            return
        self._ci_eod = True
        self._ci_eod_clean = clean

        if not self._wbuf:
            self.close_output(VFIOCompleted())
            if self._ci_producer:
                self._ci_producer.abort()
                self._c_detach()

    def _c_abort(self, force=False):
        if not self._ci_aborted or force:
            self._ci_aborted = True
            self._ci_eod = True
            self._ci_consumed = self._ci_lim_sent = 0
            self._wbuf.clear()
            if not self._sock_out_closed:
                self.close_output(VFIOCompleted())
            if self._ci_producer:
                self._ci_producer.abort()
                self._c_detach()

    def _c_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._c_attach, producer, rthread=True)
            return

        if self._ci_producer is producer:
            return
        elif self._ci_producer:
            raise VIOError('Producer already attached')

        self._ci_producer = producer
        if self._sock_out_closed:
            self.reactor.schedule(0.0, self._c_abort, True)
        else:
            self._ci_consumed = self._ci_lim_sent = 0
            producer.attach(self.byte_consume)
            self._ci_lim_sent = self._wbuf_len
            producer.can_produce(self._ci_lim_sent)

        # Notify attached chain
        try:
            producer.control.notify_consumer_attached(self.byte_consume)
        except VIOMissingControl:
            pass

    def _c_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._c_detach, rthread=True)
            return

        if self._ci_producer:
            prod, self._ci_producer = self._ci_producer, None
            prod.detach()
            self._ci_consumed =  self._ci_lim_sent = 0

    def active_do_write(self):
        if self._wbuf:
            data = self._wbuf.peek(self._max_write)
            try:
                num_written = self.write_some(data)
            except VIOException:
                self._c_abort()
            else:
                if num_written > 0:
                    self._wbuf.remove(num_written)
                    if self._ci_producer:
                        self._ci_lim_sent = (self._ci_consumed + self._wbuf_len
                                             - len(self._wbuf))
                        self._ci_producer.can_produce(self._ci_lim_sent)
                if not self._wbuf:
                    self.stop_writing()
                    if self._ci_eod:
                        self._c_abort()
        else:
            self.stop_writing()

    def _output_was_closed(self, reason):
        # No more output will be written, abort consumer
        self._c_abort()

    @property
    def _c_control(self):
        return self._c_get_control()

    # Implements _c_control in order to be able to override _c_control
    # behavior by overloading as a regular method
    def _c_get_control(self):
        return VIOControl()

    @property
    def _c_producer(self):
        return self._ci_producer

    @property
    def _c_flows(self):
        return tuple()

    @property
    def _c_twoway(self):
        return True

    @property
    def _c_reverse(self):
        return self.byte_produce()

    @peer
    def _p_can_produce(self, limit):
        if not self._pi_consumer:
            raise VIOError('No connected consumer')

        if limit is None or limit < 0:
            if (not self._pi_prod_lim is None
                and not self._pi_prod_lim < 0):
                if self._pi_produced >= self._pi_prod_lim:
                    self.start_reading(internal=True)
                self._pi_prod_lim = limit
        else:
            if (self._pi_prod_lim is not None
                and 0 <= self._pi_prod_lim < limit):
                if self._pi_produced >= self._pi_prod_lim:
                    self.start_reading(internal=True)
                self._pi_prod_lim = limit

    def _p_abort(self, force=False):
        if not self._pi_aborted or force:
            self._pi_aborted = True
            self._pi_produced = self._pi_prod_lim = 0
            if not self._sock_in_closed:
                self.close_input(VFIOCompleted())
            if self._pi_consumer:
                self._pi_consumer.abort()
                self._p_detach()

    def _p_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._p_attach, consumer, rthread=True)
            return

        if self._pi_consumer is consumer:
            return
        elif self._pi_consumer:
            raise VIOError('Consumer already attached')

        self._pi_produced = self._pi_prod_lim = 0
        self._pi_consumer = consumer
        consumer.attach(self.byte_produce)

        # Notify attached chain
        try:
            consumer.control.notify_producer_attached(self.byte_produce)
        except VIOMissingControl:
            pass

        # If closed, pass notification
        if self._sock_in_closed:
            self.reactor.schedule(0.0, self._p_abort, True)

    def _p_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._p_detach, rthread=True)
            return

        if self._pi_consumer:
            cons, self._pi_consumer = self._pi_consumer, None
            cons.detach()
            self._pi_produced = self._pi_prod_lim = 0

    def active_do_read(self):
        if not self._pi_consumer:
            self.stop_reading()

        if self._pi_prod_lim is not None and self._pi_prod_lim >= 0:
            max_read = self._pi_prod_lim - self._pi_produced
        else:
            max_read = self._max_read
        max_read = min(max_read, self._max_read)
        if max_read <= 0:
            self.stop_reading()
            return
        try:
            data = self.read_some(max_read)
        except Exception as e:
            self._p_abort()
        else:
            self._pi_buffer.append(data)
            if self._pi_buffer:
                self.pi_prod_lim = self._pi_consumer.consume(self._pi_buffer)

    def _input_was_closed(self, reason):
        if self._pi_consumer:
            # Notify consumer about end-of-data
            clean = isinstance(reason, VFIOCompleted)
            self._pi_consumer.end_consume(clean)
        else:
            self._p_abort()

    @property
    def _p_control(self):
        return self._p_get_control()

    # Implements _p_control in order to be able to override _p_control
    # behavior by overloading as a regular method
    def _p_get_control(self):
        class _Control(VIOControl):
            def __init__(self, sock):
                self.__sock = sock
            def req_producer_state(self, consumer):
                # Send notification of socket connect status
                def notify():
                    if self.__sock._sock_peer:
                        try:
                            consumer.control.connected(self.__sock._sock_peer)
                        except VIOMissingControl:
                            pass
                self.__sock.reactor.schedule(0.0, notify)
        return _Control(self)

    @property
    def _p_consumer(self):
        return self._pi_consumer

    @property
    def _p_flows(self):
        return tuple()

    @property
    def _p_twoway(self):
        return True

    @property
    def _p_reverse(self):
        return self.byte_consume()


@implements(IVByteConsumer)
class _VSocketConsumer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def consume(self, data, clim=None):
        return self.__proxy._c_consume(data, clim)

    @peer
    def end_consume(self, clean):
        return self.__proxy._c_end_consume(clean)

    def abort(self):
        return self.__proxy._c_abort()

    def attach(self, producer):
        return self.__proxy._c_attach(producer)

    def detach(self):
        return self.__proxy._c_detach()

    @property
    def control(self):
        return self.__proxy._c_control

    @property
    def producer(self):
        return self.__proxy._c_producer

    @property
    def flows(self):
        return self.__proxy._c_flows

    @property
    def twoway(self):
        return self.__proxy._c_twoway

    @property
    def reverse(self):
        return self.__proxy._c_reverse


@implements(IVByteProducer)
class _VSocketProducer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def can_produce(self, limit):
        return self.__proxy._p_can_produce(limit)

    def abort(self):
        return self.__proxy._p_abort()

    def attach(self, consumer):
        return self.__proxy._p_attach(consumer)

    def detach(self):
        return self.__proxy._p_detach()

    @property
    def control(self):
        return self.__proxy._p_control

    @property
    def consumer(self):
        return self.__proxy._p_consumer

    @property
    def flows(self):
        return self.__proxy._p_flows

    @property
    def twoway(self):
        return self.__proxy._p_twoway

    @property
    def reverse(self):
        return self.__proxy._p_reverse
