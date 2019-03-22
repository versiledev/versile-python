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

""":term:`TLS` channel transport."""
from __future__ import print_function, unicode_literals

import datetime
import weakref

from versile.internal import _b2s, _s2b, _ssplit, _vexport, _b_ord, _b_chr
from versile.internal import _pyver
from versile.common.iface import implements, abstract, peer
from versile.common.log import VLogger
from versile.common.util import VByteBuffer, VConfig, VNamedTemporaryFile
from versile.crypto.auth import VAuth
from versile.crypto.rand import VUrandom
from versile.crypto.x509 import VX509Crypto, VX509Format
from versile.crypto.x509.cert import VX509Name
from versile.crypto.x509.cert import VX509CertificationRequest
from versile.reactor import IVReactorObject
from versile.reactor.io import VByteIOPair
from versile.reactor.io import IVByteConsumer, IVByteProducer
from versile.reactor.io import VIOControl, VIOMissingControl, VIOError
from versile.reactor.io.sock import VClientSocketAgent
from versile.reactor.io.tcp import VTCPSocket
from versile.reactor.io.tlssock import VTLSClientSocketAgent

__all__ = ['VTLSTransport', 'VTLSServer', 'VTLSClient']
__all__ = _vexport(__all__)


@abstract
@implements(IVReactorObject)
class VTLSTransport(object):
    """Generic :term:`TLS` transport for byte communication.

    Implements a generic producer/consumer based transport mechanism
    for :term:`TLS` communication. This enables generic use of the
    transport in a producer/consumer chain without having to associate it
    directly to an internet socket with :mod:`versile.reactor.io.tlssock`\ .

    :param reactor:      channel reactor
    :param key:          keypair for secure handshake
    :type  key:          :class:`versile.crypto.VAsymmetricKey`
    :param identity:     an identity to assume (or None)
    :type  identity:     :class:`versile.crypto.x509.cert.VX509Name`
    :param certificates: certificate chain
    :type  certificates: :class:`versile.crypto.x509.cert.VX509Certificate`\ ,
    :param p_auth:       connection authorizer
    :type  p_auth:       :class:`versile.crypto.auth.VAuth`
    :param buf_size:     buffer size for internal I/O buffers
    :type  buf_size:     int

    This class is abstract and should not be instantiated, instead use
    :class:`VTLSClient` or :class:`VTLSServer` depending on which role
    is being assumed.

    The implementation actually creates a pair of connected Internet
    sockets internally to perform :term:`TLS` conversion, in order to
    be able to use python's ssl module for handling the protocol. This
    should be transparent to users of this class, except some extra
    logging to the reactor logger performed by the inner socket pair.

    In order for the class to operate correctly, the internal socket
    pair must not be disabled or blocked by external firewalls,
    i.e. the code must be allowed to listen and make connections on
    the localhost interface.

    .. warning::

        As the transport uses :mod:`versile.reactor.io.tlssock`
        classes internally for its implementation, it also stores
        private keys insecurely. See documentation in the TLS sockets
        module for details.

    """

    def __init__(self, reactor, key, identity=None, certificates=None,
                 p_auth=None, buf_size=4096):
        if p_auth is None:
            p_auth = VAuth()

        self.__reactor = reactor

        # Set up an internal TCP socket connection for performing
        # TLS conversion via the python ssl module's TLS support
        ext_sock, int_sock = VTCPSocket.create_native_pair()

        # Set up agent for ciphertext communication
        cipher_sock = VClientSocketAgent(reactor, sock=ext_sock,
                                         connected=True, wbuf_len=buf_size)
        cipher_sock._set_logger()
        self.__c_consumer = cipher_sock.byte_consume
        self.__c_producer = cipher_sock.byte_produce

        # Set up plaintext agent which handles TLS protocol
        plain_sock = self._create_tls_socket(reactor, int_sock, key, identity,
                                             certificates, p_auth, buf_size)
        tls_logger = VLogger(prefix='TLS')
        tls_logger.add_watcher(reactor.log)
        plain_sock._set_logger(tls_logger)

        self.__p_consumer = plain_sock.byte_consume
        self.__p_producer = plain_sock.byte_produce

        # Replace ciphertext agent consumer control handling with a proxy
        # to the consumer attached to the TLS socket (if any)
        _p_prod = self.__p_producer
        def _cipher_c_control():
            if _p_prod.consumer:
                return _p_prod.consumer.control
            else:
                return VIOControl()
        cipher_sock._c_get_control = _cipher_c_control

        # Replace ciphertext agent producer control handling with a proxy
        # to the producer attached to the TLS socket (if any)
        _p_cons = self.__p_consumer
        def _cipher_p_control():
            if _p_cons.producer:
                return _p_cons.producer.control
            else:
                return VIOControl()
        cipher_sock._p_get_control = _cipher_p_control

        # Replace ciphertext agent consumer control handling with a proxy
        # to the ciphertext's connected producer
        _c_cons = self.__c_consumer
        def _plain_p_control():
            if _c_cons.producer:
                return _c_cons.producer.control
            else:
                return VIOControl()
        plain_sock._p_get_control = _plain_p_control

        # Replace plaintext agent consumer control handling with a proxy
        # to the ciphertext's connected consumer, while also
        # handling req_producer_state
        _c_prod = self.__c_producer
        def _plain_c_control():
            if _c_prod.consumer:
                proxy_control = _c_prod.consumer.control
            else:
                proxy_control = VIOControl()
            class _Control(VIOControl):
                def __getattr__(self, attr):
                    return proxy_control.attr
                def req_producer_state(self, consumer):
                    # Perform request pass-through
                    try:
                        proxy_control.req_producer_state(consumer)
                    except VIOMissingControl:
                        pass
                    # Pass TLS authorization information if available
                    if plain_sock._tls_handshake_done:
                        def notify():
                            _auth = plain_sock._tls_authorize_peer()
                            if not _auth:
                                # Not authorized, abort
                                plain_sock._c_abort()
                                plain_sock._p_abort()
                                cipher_sock._c_abort()
                                cipher_sock._p_abort()
                        reactor.schedule(0.0, notify)
            return _Control()
        plain_sock._c_get_control = _plain_c_control


    @property
    def plain_consume(self):
        """Holds a consumer interface to TLS transport plaintext."""
        return self.__p_consumer

    @property
    def plain_produce(self):
        """Holds a producer interface to TLS transport plaintext."""
        return self.__p_producer

    @property
    def plain_io(self):
        """Plaintext I/O (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.plain_consume, self.plain_produce)

    @property
    def cipher_consume(self):
        """Holds a consumer interface to TLS transport ciphertext."""
        return self.__c_consumer

    @property
    def cipher_produce(self):
        """Holds a producer interface to TLS transport ciphertext."""
        return self.__c_producer

    @property
    def cipher_io(self):
        """Ciphertext I/O (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.cipher_consume, self.cipher_produce)

    @property
    def reactor(self):
        """The object's reactor.

        See :class:`versile.reactor.IVReactorObject`

        """
        return self.__reactor

    @abstract
    def _is_server(cls):
        """Return True if transport takes a server role, oterwise False."""
        raise RuntimeException()

    @classmethod
    def _create_tls_socket(cls, reactor, sock, key, identity, certificates,
                           p_auth, buf_size=None):

        # Generate file 'certfile' with key and certificate information
        if not key:
            certfile = None
        else:
            if identity is None:
                identity = VX509Name()

            # Create a key file
            _fmt = VX509Format.PEM_BLOCK
            key_pem = VX509Crypto.export_private_key(key, fmt=_fmt)
            certfile = VNamedTemporaryFile(secdel=True)
            certfile.write(key_pem)

            if not certificates:
                # Create a Public CA signed certificate
                csr = VX509CertificationRequest.create(identity, key)
                serial = VUrandom().number(0, (1 << 64) - 1)
                _now = datetime.datetime.now()
                # HARDCODED - timespan for PCA signed certificate 10 years
                not_before = _now - datetime.timedelta(days=1)
                not_after = _now + datetime.timedelta(days=10*365)
                ca_key, ca_cert = VAuth.public_ca(unsafe=True)
                cert = csr.sign(serial=serial, issuer=ca_cert.issuer,
                                not_after=not_after, sign_key=ca_key,
                                not_before=not_before,)
                certificates = (cert,)

            # Write certificates to a file
            for cert in certificates:
                certfile.write(cert.export(fmt=VX509Format.PEM_BLOCK))
            certfile.close()

        # If root certificates are in use set up 'cafile' with CA roots
        if p_auth.require_root:
            cafile = VNamedTemporaryFile(secdel=True)
            for cert in p_auth.root_certificates:
                cafile.write(cert.export(VX509Format.PEM_BLOCK))
            cafile.close()
        else:
            cafile = None

        # Determine TLS certificate validation mode based on p_auth
        if p_auth.require_key:
            tls_val = VTLSClientSocketAgent.CERT_REQUIRED
        elif p_auth.require_root:
            tls_val = VTLSClientSocketAgent.CERT_OPTIONAL
        else:
            tls_val = VTLSClientSocketAgent.CERT_NONE

        # Set up TLS socket agent
        SCls = VTLSClientSocketAgent
        tls_sock = SCls(reactor=reactor, sock=sock, sock_is_tls=False,
                        tls_server=cls._is_server(), tls_keyfile=None,
                        tls_certfile=certfile, tls_cafile=cafile,
                        tls_req_cert=tls_val, tls_p_auth=p_auth,
                        close_cback=None, connected=True,
                        max_read=buf_size, max_write=buf_size)
        return tls_sock


class VTLSServer(VTLSTransport):
    """:term:`TLS` server transport for byte communication.

    Implements the server side of a :term:`TLS` transport. See
    :class:`VTLSTransport` for arguments and details.

    """

    # Raises ValueError if key not set
    def __init__(self, reactor, key, identity=None, certificates=None,
                 p_auth=None, buf_size=4096):
        if key is None:
            raise ValueError('Key must be provided for TLS server transport')
        s_init = super(VTLSServer, self).__init__
        s_init(reactor=reactor, key=key, identity=identity,
               certificates=certificates, p_auth=p_auth, buf_size=buf_size)

    @classmethod
    def _is_server(cls):
        return True


class VTLSClient(VTLSTransport):
    """:term:`TLS` client transport for byte communication.

    Implements the client side of a :term:`TLS` transport. See
    :class:`VTLSTransport` for arguments and details.

    """

    # Sets None as default for 'key'
    def __init__(self, reactor, key=None, identity=None, certificates=None,
                 p_auth=None, require_key=False, buf_size=4096):
        s_init = super(VTLSClient, self).__init__
        s_init(reactor=reactor, key=key, identity=identity,
               certificates=certificates, p_auth=p_auth, buf_size=buf_size)

    @classmethod
    def _is_server(cls):
        return False
