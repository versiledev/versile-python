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

"""Reactor components for :term:`TLS` socket I/O."""
from __future__ import print_function, unicode_literals

import errno
import socket
import ssl
import sys

from versile.internal import _vplatform, _vexport, _b2s
from versile.common.iface import multiface, abstract
from versile.crypto.x509 import VX509Format
from versile.crypto.x509.cert import VX509Certificate
from versile.reactor.io import VFIOCompleted, VFIOLost
from versile.reactor.io import VIOError, VIOCompleted, VIOLost
from versile.reactor.io import VIOMissingControl
from versile.reactor.io.sock import VClientSocket, VClientSocketAgent

__all__ = ['VTLSClientBase', 'VTLSClientSocket', 'VTLSClientSocketAgent']
__all__ = _vexport(__all__)

# Workaround for Windows-specific error codes
if sys.platform == 'win32' or _vplatform ==  'ironpython':
    _errno_wouldblock = (errno.EWOULDBLOCK, errno.WSAEWOULDBLOCK)
else:
    _errno_wouldblock = (errno.EWOULDBLOCK,)


@abstract
class VTLSClientBase(object):
    """Base class for TLS client sockets.

    :param tls_wrapped:  if True socket is already TLS wrapped
    :type  tls_wrapped:  bool
    :param tls_server:   if True socket is TLS server-side, otherwise client
    :type  tls_server:   bool
    :param tls_keyfile:  TLS keypair file, filename or None
    :type  tls_keyfile:  :class:`file`, unicode
    :param tls_certfile: TLS certificate file, filename or None
    :type  tls_certfile: :class:`file`, unicode
    :param tls_cafile:   TLS root CA list file, filename or None
    :type  tls_cafile:   :class:`file`, unicode
    :param tls_req_cert: peer certificate requirement code
    :type  tls_req_cert: int
    :param tls_p_auth:   peer authorizer object (or None)
    :type  tls_p_auth:   :class:`versile.crypto.auth.VAuth`

    This class is abstract and should not be directly
    instantiated. Programs should instead use
    :class:`VTLSClientSocket` or :class:`VTLSClientSocketAgent`\ .

    *tls_req_cert* should be one of :attr:`CERT_NONE`\ ,
    :attr:`CERT_OPTIONAL` or :attr:`CERT_REQUIRED`\ .

    """

    def __init__(self, tls_wrapped, tls_server, tls_keyfile, tls_certfile,
                 tls_cafile, tls_req_cert, tls_p_auth=None):
        self._tls_wrapped = tls_wrapped
        self._tls_server = tls_server
        if tls_keyfile and not isinstance(tls_keyfile, (bytes, unicode)):
            self._tls_keyfile = tls_keyfile
            self._tls_keyfile_name = tls_keyfile.name
        else:
            self._tls_keyfile = None
            self._tls_keyfile_name = tls_keyfile
        if tls_certfile and not isinstance(tls_certfile, (bytes, unicode)):
            self._tls_certfile = tls_certfile
            self._tls_certfile_name = tls_certfile.name
        else:
            self._tls_certfile = None
            self._tls_certfile_name = tls_certfile
        if tls_cafile and not isinstance(tls_cafile, (bytes, unicode)):
            self._tls_cafile = tls_cafile
            self._tls_cafile_name = tls_cafile.name
        else:
            self._tls_cafile = None
            self._tls_cafile_name = tls_cafile
        self._tls_req_cert = tls_req_cert
        self._tls_p_auth = tls_p_auth
        self._tls_handshake_done = False
        self._tls_peer_key = None          # Peer key (post-handshake)
        self._tls_peer_identity = None     # Peer identity (post-handshake)
        self._tls_peer_cert = None         # Peer certificates (post-handshake)
        self._tls_read_pending = False

    CERT_NONE = ssl.CERT_NONE
    """No peer certificate validation."""

    CERT_OPTIONAL = ssl.CERT_OPTIONAL
    """Validate peer certificate if provided."""

    CERT_REQUIRED = ssl.CERT_REQUIRED
    """Peer certificates and certificate validation required."""

    def read_some(self, max_len):
        """See :meth:`versile.reactor.io.IVByteInput.read_some`.

        .. note::

            Whereas :meth:`versile.reactor.io.sock.VSocket.read_some`
            is non-blocking, reading on a TLS socket is a blocking
            operation. This is due to limitations of the python 2.6
            ssl module. If non-blocking behavior is required, then
            :func:`select.select` or similar should be called to check
            whether the socket has data.

        This method may not return data even though data was available
        on the underlying socket when the method was called. This is
        because the TLS layer can only provide data when a full
        encrypted frame has been received.

        """
        if not self.was_connected:
            raise VIOError('Socket was not connected')
        if self._sock_in_closed:
            if isinstance(self._sock_in_closed_reason, VFIOCompleted):
                raise VIOCompleted()
            else:
                raise VIOLost()
        if not self.sock:
            raise VIOError('No socket')
        self._tls_read_pending = False
        try:
            data = self.sock.read(max_len)
        except IOError as e:
            if e.errno in _errno_wouldblock:
                return b''
            elif (e.errno in (errno.EPIPE, errno.ENOTCONN)
                  and not self._sock_verified):
                    # ISSUE - see VSocket.read_some comments
                    self.log.debug('Ignoring post-connect read errno %s'
                                  % e.errno)
                    return b''
            else:
                self.log.debug('Read got errno %s' % e.errno)
                raise VIOError('Socket read error, errno %s' % e.errno)
        except ssl.SSLError as e:
            if e.args[0] in (ssl.SSL_ERROR_WANT_READ,
                             ssl.SSL_ERROR_WANT_WRITE):
                # Full frame of decrypted data not yet available
                return b''
        else:
            if not data:
                raise VIOCompleted()
            if self.sock.pending():
                self.log.debug('SSL data pending')
                self._tls_read_pending = True
                self.reactor.schedule(0.0, self.do_read)
            self._sock_verified = True
            return data

    def write_some(self, data):
        """See :meth:`versile.reactor.io.IVByteOutput.write_some`\ .

        .. note::

            Whereas :meth:`versile.reactor.io.sock.VSocket.write_some`
            is non-blocking, writing to a TLS socket is a blocking
            operation. This is due to limitations of the python 2.6
            ssl module. If non-blocking behavior is required then
            :func:`select.select` or similar should be called to check
            whether the socket is ready for writing.

        """
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
            num_written = self.sock.write(data)
        except IOError as e:
            if e.errno in _errno_wouldblock:
                return 0
            elif (e.errno in (errno.EPIPE, errno.ENOTCONN)
                  and not self._sock_verified):
                # ISSUE - see VSocket.write_some comments
                self.log.debug('Ignoring post-connect write errno %s'
                              % e.errno)
                return 0
            else:
                self.log.debug('Write got errno %s' % e.errno)
                raise VIOError('Socket write error, errno %s' % e.errno)
        else:
            self._sock_verified = True
            return num_written

    def connect(self, peer):
        """Initiates a :term:`TLS` connection.

        :param peer: peer to connect to
        :type  peer: :class:`versile.common.peer.VSocketPeer`
        :raises:     :exc:`versile.reactor.io.VIOError`

        .. note::

            Whereas :meth:`versile.reactor.io.sock.VClientSocket.connect` is
            non-blocking, the TLS connect method is blocking. This is due to
            limitations of the python 2.6 ssl module.

        """
        try:
            # Implementation is similar to VClientSocket.connect(), however
            # the socket is set in blocking mode (due to TLS handshake)
            sock = peer.create_socket()
            pre_timeout = sock.gettimeout()
            sock.setblocking(True)
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
            self.sock.connect(peer.address)
        except Exception as e:
            self.log.debug('Connect exception')
            self.close_io(VFIOLost())
        else:
            self.sock.settimeout(pre_timeout)
            self._set_sock_enabled()
            self._set_sock_connected()

    def _started_reading(self):
        """Overload so pending read triggers a do_read cycle."""
        if self._tls_read_pending:
            self.reactor.schedule(0.0, self.do_read)

    def _connect_transform(self, sock):
        """Overrides the post-connect transform to set up an SSL socket."""
        if not self._tls_wrapped:
            # Setting socket non-blocking ref http://bugs.python.org/issue1251
            # Note that wrapping implies using sock.read/write for I/O and
            # no longer being able to shut down socket in single direction
            sock.setblocking(False)
            _wfun = ssl.wrap_socket
            sock = _wfun(sock, server_side=self._tls_server,
                         cert_reqs=self._tls_req_cert,
                         keyfile=self._tls_keyfile_name,
                         certfile=self._tls_certfile_name,
                         ca_certs=self._tls_cafile_name,
                         ssl_version=ssl.PROTOCOL_TLSv1,
                         do_handshake_on_connect=False)
        return sock

    def _sock_do_activation_read(self):
        if not self._tls_handshake_done:
            try:
                self.sock.do_handshake()
            except ssl.SSLError as e:
                if e.args[0] == ssl.SSL_ERROR_WANT_READ:
                    self.log.debug('do_handshake rd want_read')
                    self.start_reading()
                    self.stop_writing()
                    return False
                elif e.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                    self.log.debug('do_handshake rd want_write')
                    self.stop_reading()
                    self.start_writing()
                    return False
                else:
                    raise VIOError('SSL handshake problem', e.args)
            except AttributeError:
                # ISSUE - workaround for ssl async problem, stop
                # socket I/O for 1.0s
                self.log.debug('do_handshake rd attr.err')
                self.stop_reading()
                self.stop_writing()
                def _wakeup():
                    self.start_reading()
                    self.start_writing()
                self.reactor.schedule(1.0, _wakeup) # HARDCODED wait time
            else:
                self.log.debug('TLS handshake was completed')
                if self.__finalize_tls_handshake():
                    self._tls_handshake_done = True
                    self.log.debug('TLS connection authorized')
                else:
                    self.close_io(VFIOLost())
                    raise VIOLost('TLS connection was not authorized')
        return self._tls_handshake_done

    def _sock_do_activation_write(self):
        if not self._tls_handshake_done:
            try:
                self.sock.do_handshake()
            except ssl.SSLError as e:
                if e.args[0] == ssl.SSL_ERROR_WANT_READ:
                    self.log.debug('do_handshake wr want_read')
                    self.start_reading()
                    self.stop_writing()
                    return False
                elif e.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                    self.log.debug('do_handshake wr want_write')
                    self.stop_reading()
                    self.start_writing()
                    return False
                else:
                    raise VIOError('SSL handshake problem')
            except AttributeError:
                # ISSUE - workaround for ssl async problem, stop
                # socket I/O for 1.0s
                self.log.debug('do_handshake wr attr.err')
                self.stop_reading()
                self.stop_writing()
                def _wakeup():
                    self.start_reading()
                    self.start_writing()
                self.reactor.schedule(1.0, _wakeup) # HARDCODED wait time
            else:
                self.log.debug('TLS handshake was completed')
                if self.__finalize_tls_handshake():
                    self._tls_handshake_done = True
                    self.log.debug('TLS connection authorized')
                else:
                    self.close_io(VFIOLost())
                    raise VIOLost('TLS connection was not authorized')
        return self._tls_handshake_done

    def __finalize_tls_handshake(self):
        """

        :returns: True if TLS connection is allowed to proceed post-handshake

        """
        # Extract peer certificate, key and identity information
        peer_cert = self.sock.getpeercert(binary_form=True)
        if peer_cert:
            # getpeercert returns only one single certificate, the rest
            # of the chain is not exposed, so retreiving only one cert
            _cfun = VX509Certificate.import_cert
            self._tls_peer_cert = _cfun(peer_cert, fmt=VX509Format.DER)
            self.log.debug('Got peer certificate')

        if self._tls_peer_cert:
            _cert = self._tls_peer_cert
            self._tls_peer_key = _cert.subject_key
            self._tls_peer_identity = _cert.subject

        if self._tls_p_auth:
            if not self._tls_p_auth.accept_host(self._sock_peer):
                return False
            _afun = self._tls_p_auth.accept_credentials
            if not _afun(key=self._tls_peer_key,
                         identity=self._tls_peer_identity,
                         certificates=(self._tls_peer_cert,)):
                return False

        # Perform peer authorization check set on the class
        if not self._tls_authorize_peer():
            return False
        return True

    def _tls_authorize_peer(self):
        """Internal call to authorize the peer"""
        return True

    def _sock_shutdown_read(self):
        """Overrides internal call to shut down socket for reading.

        Does nothing, as SSL sockets (seemingly) don't play well with
        socket half-close.

        """
        self.stop_reading()

    def _sock_shutdown_write(self):
        """Overrides internal call to shut down socket for writing.

        Does nothing, as SSL sockets (seemingly) don't play well with
        socket half-close.

        """
        self.stop_writing()


@multiface
class VTLSClientSocket(VTLSClientBase, VClientSocket):
    """A :term:`TLS`\ -secured client socket.

    See :class:`VTLSClientBase` for *tls_* arguments and
    :class:`versile.reactor.io.sock.VClientSocket` for remaining
    arguments.

    The socket uses the :mod:`ssl` module for its :term:`TLS` layer
    implementation. Due to technical limitations with the module
    implementation in python 2.x the socket has some constraints
    compared to :class:`versile.reactor.io.sock.VClientSocket`\ :

    * :meth:`VTLSClientBase.connect` operation is blocking
    * :meth:`VTLSClientBase.read_some` is blocking
    * :meth:`VTLSClientBase.write_some` is blocking

    In python 2.x the :mod:`ssl` module requires that keypairs are
    passed in files, which is why this socket implementation has this
    behavior. Though it is fairly common pattern on hardened servers
    to have certificates stored on the filesystem, for other systems
    committing this data to the file system may pose a significant
    risk. When storing key files is not acceptable, the
    :mod:`versile.reactor.io.vts` implementation of :term:`VTS` may be
    a better option.

    .. note::

        Due to technical limitations in the :mod:`ssl` module, the
        only certificate from the peer's connection chain that is
        exposed from the TLS layer is the certificate of the
        connection peer's key. Though the peer certificate chain may
        be validated by :mod:`ssl`\ , the chain that will be passed to
        :meth:`versile.crypto.auth.VAuth.accept_credentials` will
        consist of only one single certificate.

    """
    def __init__(self, reactor, sock_is_tls=False, tls_keyfile=None,
                 tls_certfile=None, tls_cafile=None, tls_server=False,
                 tls_req_cert=ssl.CERT_NONE, tls_p_auth=None, sock=None,
                 hc_pol=None, close_cback=None, connected=False):
        tls_init = VTLSClientBase.__init__
        tls_init(self, tls_wrapped=sock_is_tls, tls_server=tls_server,
                 tls_keyfile=tls_keyfile, tls_certfile=tls_certfile,
                 tls_cafile=tls_cafile, tls_req_cert=tls_req_cert,
                 tls_p_auth=tls_p_auth)
        VClientSocket.__init__(self, reactor=reactor, sock=sock, hc_pol=hc_pol,
                               close_cback=close_cback, connected=connected)


class VTLSClientSocketAgent(VTLSClientBase, VClientSocketAgent):
    """A :term:`TLS`\ -secured client socket with producer/consumer interface.

    See :class:`VTLSClientBase` for *tls_* arguments and
    :class:`versile.reactor.io.sock.VClientSocketAgent` for remaining
    arguments. Usage is similar to :class:`VTLSClientSocket` \ , refer
    to the documentation of that class for details.

    .. warning::

       Make sure to read how the implementation uses temporary files
       to store keypairs.

    """
    def __init__(self, reactor, sock_is_tls=False, tls_keyfile=None,
                 tls_certfile=None, tls_cafile=None, tls_server=False,
                 tls_req_cert=VTLSClientBase.CERT_NONE, tls_p_auth=None,
                 sock=None, hc_pol=None, close_cback=None, connected=False,
                 max_read=4096, max_write=4096, wbuf_len=4096):
        tls_init = VTLSClientBase.__init__
        tls_init(self, tls_wrapped=sock_is_tls, tls_server=tls_server,
                 tls_keyfile=tls_keyfile, tls_certfile=tls_certfile,
                 tls_cafile=tls_cafile, tls_req_cert=tls_req_cert,
                 tls_p_auth=tls_p_auth)
        VClientSocketAgent.__init__(self, reactor=reactor, sock=sock,
                                    hc_pol=hc_pol, close_cback=close_cback,
                                    connected=connected, max_read=max_read,
                                    max_write=max_write, wbuf_len=wbuf_len)

    def _tls_authorize_peer(self):
        cons = self.byte_produce.consumer
        if cons:
            try:
                _auth = cons.control.authorize
                result = _auth(self._tls_peer_key, self._tls_peer_cert,
                               self._tls_peer_identity, 'TLS')
            except VIOMissingControl:
                return True
            else:
                return result
        else:
            return True
