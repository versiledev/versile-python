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

"""Reactor based implementation of the :mod:`versile.orb.service` framework."""

from __future__ import print_function, unicode_literals

import datetime
import socket

from versile.internal import _vexport
from versile.common.iface import abstract
from versile.common.util import VNamedTemporaryFile
from versile.crypto import VCrypto
from versile.crypto.auth import VAuth
from versile.crypto.rand import VUrandom
from versile.crypto.x509 import VX509Crypto, VX509Format
from versile.crypto.x509.cert import VX509Name
from versile.crypto.x509.cert import VX509CertificationRequest
from versile.orb.entity import VObject
from versile.orb.service import VService, VServiceConfig
from versile.reactor.io import VIOCompleted, VFIOLost
from versile.reactor.io.vec import VEntitySerializerConfig
from versile.reactor.io.link import VLinkAgent, VLinkAgentConfig
from versile.reactor.io.sock import VListeningSocket, VClientSocketAgent
from versile.reactor.io.sock import VClientSocketFactory
from versile.reactor.io.tlssock import VTLSClientSocketAgent
from versile.reactor.io.tls import VTLSServer
from versile.reactor.io.vts import VSecureServer, VSecureConfig
from versile.reactor.io.vop import VOPServerBridge
from versile.reactor.quick import VReactor

__all__ = ['VReactorService', 'VLinkAgentFactory', 'VOPService',
           'VReactorServiceConfig', 'VOPServiceConfig',
           'VOPInsecureServiceConfig']
__all__ = _vexport(__all__)


@abstract
class VReactorService(VService):
    """Base class for reactor :class:`VService`\ implementations.

    :param conf:    configuration (default if None)
    :type  conf:    :class:`VReactorServiceConfig`
    :param reactor: externally managed reactor, or None
    :raises:        :exc:`versile.orb.error.VLinkError`

    Other arguments are similar to
    :class:`versile.orb.service.VService`\ .

    When a link is instantiated, it is instantiated with a deep copy
    of *conf.link_config* as the link's configuration, and a deep copy
    of *conf.vec_config* is added as a property on that link config
    instance with the name 'vec_config'.

    This class is abstract and should not be directly instantiated.

    """

    def __init__(self, gw_factory, auth, key, identity, certificates, p_auth,
                 processor, sock, node, internal, buf_size, conf, reactor):
        s_init = super(VReactorService, self).__init__
        s_init(gw_factory=gw_factory, auth=auth, key=key, identity=identity,
               certificates=certificates, p_auth=p_auth, processor=processor,
               sock=sock, node=node, internal=internal, buf_size=buf_size,
               conf=conf)
        if reactor:
            self._reactor = reactor
            self._owns_reactor = False
        else:
            self._reactor = VReactor()
            self._owns_reactor = True

        self._listener = None

    def start(self):
        if self._owns_reactor:
            self._reactor.start()

        csock_factory = self._create_factory()

        if self._sock:
            bound = listening = True
        else:
            self._sock = socket.socket()
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bound = listening = False

        if self._node:
            cntled = True
            a_back = self._node.accepted
            c_back = self._node.closed
        else:
            cntled = False
            node = a_back = c_back = None

        Cls = VListeningSocket
        self._listener = Cls(self._reactor, sock=self._sock, bound=bound,
                             listening=listening, factory=csock_factory,
                             controlled=cntled, accept_cback=a_back,
                             client_close=c_back)
        if not bound:
            address = (self._config.iface, self._config.port)
            self._listener.bind(address)
            self._listener.listen(10)

        self._activate()

    @property
    def reactor(self):
        """Holds the service's reactor."""
        return self._reactor

    def _create_factory(self):
        byteio_factory = self._create_byte_agent_factory()
        p_auth = self._p_auth
        class _SockFactory(VClientSocketFactory):
            def __init__(self, reactor, internal, buf_size):
                super(_SockFactory, self).__init__(reactor)
                self._internal = internal
                self._buf_size = buf_size

            def build(self, sock, close_cback=None):
                bsize = self._buf_size
                if self._internal and bsize is None:
                    bsize = VLinkAgent.DEFAULT_INT_LINK_BUFSIZE
                SCls = VClientSocketAgent
                if bsize is None:
                    sock = SCls(reactor=self.reactor, sock=sock,
                                close_cback=close_cback, connected=True)
                else:
                    sock = SCls(reactor=self.reactor, sock=sock,
                                close_cback=close_cback, connected=True,
                                max_read=bsize, max_write=bsize)
                if p_auth:
                    # Perform peer authorization validation on socket
                    if not p_auth.accept_host(sock._sock_peer):
                        sock.close_io(VFIOLost())
                        return sock
                byte_io = byteio_factory.build()
                sock.byte_io.attach(byte_io)
                return sock
        return _SockFactory(self._reactor, self._internal, self._buf_size)

    def _can_accept(self):
        with self:
            if not self._listener:
                raise Exception('Service not started, can_accept not allowed')
            self._listener.can_accept()

    def _schedule(self, func, *args, **kargs):
        self._reactor.schedule(0.0, func, *args, **kargs)

    def _stop_listener(self):
        with self._status_cond:
            if self._active:
                self._listener.close_io(VIOCompleted())
                self._active = False
                self._status_cond.notify_all()

    def _stop_threads(self):
        with self:
            if self._owns_reactor:
                self._reactor.stop()
            if self._owns_processor:
                self._processor.stop()

    @abstract
    def _create_byte_agent_factory(self):
        raise NotImplementedError()


class VOPService(VReactorService):
    """Listening service for the :term:`VOP` protocol.

    :param conf:         configuration (default if None)
    :type  conf:         :class:`VOPServiceConfig`
    :param crypto:       crypto provider (or None)
    :type  crypto:       :class:`versile.crypto.VCrypto`
    :raises:             :exc:`exceptions.ValueError`\ ,
                         :exc:`versile.orb.error.VLinkError`

    See :class:`versile.reactor.io.service.VReactorService` for
    other parameters.

    *key*, *identity* and *certificates* are used by the :term:`VTS`
    and :term:`TLS` transports.

    An exception is raised if *key* is None and :term:`VTS` or :term:`TLS`
    is enabled for the service.

    """
    def __init__(self, gw_factory, auth, key=None, identity=None,
                 certificates=None, p_auth=None, processor=None, sock=None,
                 node=None, internal=False, buf_size=None, conf=None,
                 reactor=None, crypto=None):
        if p_auth is None:
            p_auth = VAuth()
        if conf is None:
            conf = VOPServiceConfig()
        if (key is None and (conf.enable_vts or conf.enable_tls)):
            raise ValueError('Key cannot be None if VTS or TLS enabled')
        s_init = super(VOPService, self).__init__
        s_init(gw_factory=gw_factory, auth=auth, key=key, identity=identity,
               certificates=certificates, p_auth=p_auth, processor=processor,
               sock=sock, node=node, internal=internal, buf_size=buf_size,
               conf=conf, reactor=reactor)
        self._crypto = VCrypto.lazy(crypto)

    @classmethod
    def create_socket(cls, interface='', port=4433, bind=True, listen=10,
                      reuse=True):
        s_func = VReactorService.create_socket
        return s_func(interface=interface, port=port, bind=bind, listen=listen,
                      reuse=reuse)

    def _create_byte_agent_factory(self):
        Cls = _VOPByteAgentFactory
        return Cls(service=self, reactor=self._reactor,
                   processor=self._processor, gw_factory= self._gw_factory,
                   keypair=self._keypair, identity=self._identity,
                   certificates=self._certificates, p_auth=self._p_auth,
                   crypto=self._crypto, internal=self._internal,
                   buf_size=self._buf_size)


class VLinkAgentFactory(object):
    """Factory for creating link objects.

    Factory for :class:`versile.reactor.io.link.VLinkAgent`\ objects.

    """

    def build(self, gateway, reactor, processor, init_callback,
              context, auth, conf):
        """Creates a link.

        :return: created link
        :rtype:  :class:`versile.reactor.io.link.VLinkAgent`

        Arguments are similar to
        :class:`versile.reactor.io.link.VLinkAgent`\ .

        """
        link = VLinkAgent(gateway=gateway, reactor=reactor,
                          processor=processor, init_callback=init_callback,
                          context=context, auth=auth, conf=conf)
        return link


class VReactorServiceConfig(VServiceConfig):
    """Config for a :class:`versile.reactor.io.service.VReactorService`\ .

    :param port:         listening port
    :type  port:         int
    :param link_factory: factory for links (or None)
    :type  link_factory: :class:`VLinkAgentFactory`
    :param iface:        the interface to listen to (or None)
    :type  iface:        str
    :param lazy_threads: workers for lazy-created processor
    :type  lazy_threads: int
    :param link_config:  link config (or None)
    :type  link_config:  :class:`versile.reactor.io.link.VLinkAgentConfig`
    :param vec_config:   entity channel config (or None)
    :type  vec_config:   :class:`versile.reactor.io.vec.VEntitySerializerConfig`

    Additional configurations can be set in *kargs*\ .

    """
    def __init__(self, port, link_factory=None, iface='', lazy_threads=5,
                 link_config=None, vec_config=None, **kargs):
        if link_factory is None:
            link_factory = VLinkAgentFactory()
        if vec_config is None:
            vec_config = VEntitySerializerConfig()
        if iface is None:
            iface = ''
        if link_config is None:
            link_config = VLinkAgentConfig(hold_peer=False)
        s_init = super(VReactorServiceConfig, self).__init__
        s_init(port=port, link_factory=link_factory, iface=iface,
               lazy_threads=lazy_threads, link_config=link_config,
               vec_config=vec_config, **kargs)


class VOPServiceConfig(VReactorServiceConfig):
    """Configuration settings for a :class:`VOPService`\ .

    :param enable_vts:     if True enable :term:`VTS` transport
    :type  enable_vts:     bool
    :param enable_tls:     if True enable :term:`TLS` transport
    :type  enable_tls:     bool
    :param allow_insecure: if True allow insecure transport
    :type  allow_insecure: bool
    :param vts_config:     :term:`VTS` config (or None)
    :type  vts_config:     :class:`versile.reactor.io.vts.VSecureConfig`

    See :class:`VReactorServiceConfig` for other parameters.

    """
    def __init__(self, port=4433, link_factory=None, iface='', lazy_threads=5,
                 link_config=None, vec_config=None, enable_vts=True,
                 enable_tls=False, allow_insecure=False, vts_config=None,
                 **kargs):
        if enable_vts and vts_config is None:
            vts_config = VSecureConfig()
        s_init = super(VOPServiceConfig, self).__init__
        s_init(port=port, link_factory=link_factory, iface=iface,
               lazy_threads=lazy_threads, link_config=link_config,
               vec_config=vec_config, enable_vts=enable_vts,
               enable_tls=enable_tls, allow_insecure=allow_insecure,
               vts_config=vts_config, **kargs)


class VOPInsecureServiceConfig(VReactorServiceConfig):
    """Configuration settings for an insecure :class:`VOPService`\ .

    For parameters see :class:`VOPServiceConfig`\ . Defaults to
    allowing insecure transport without secure transports.

    .. warning::

        Should be used with caution as it sets up plaintext byte
        transport which is insecure. Should only be used in controlled
        environments where security is managed with other mechanisms.

    """
    def __init__(self, port=4433, link_factory=None, iface='', lazy_threads=5,
                 link_config=None, vec_config=None, enable_vts=False,
                 enable_tls=False, allow_insecure=True, vts_config=None,
                 **kargs):
        if enable_vts and vts_config is None:
            vts_config = VSecureConfig()
        s_init = super(VOPInsecureServiceConfig, self).__init__
        s_init(port=port, link_factory=link_factory, iface=iface,
               lazy_threads=lazy_threads, link_config=link_config,
               vec_config=vec_config, enable_vts=enable_vts,
               enable_tls=enable_tls, allow_insecure=allow_insecure,
               vts_config=vts_config, **kargs)


class _ByteAgentFactory(object):
    def __init__(self, service, reactor, processor, gw_factory):
        self._service = service
        self._reactor = reactor
        self._processor = processor
        self._gw_factory = gw_factory

    def build(self):
        gw_data = self._gw_factory()
        if isinstance(gw_data, VObject):
            gw, gw_init = gw_data, None
        else:
            gw, gw_init = gw_data

        # Create a deep copy of link configuration; add a copy of the VEC
        # config as a property 'vec_config' on the link configuration
        link_config = self._service._config.link_config.copy()
        vec_config = self._service._config.vec_config.copy()
        auth = self._service._auth
        link_config.vec_config = vec_config

        link = self._create_link(gw=gw, gw_init=gw_init, context=None,
                                 auth=auth, link_config=link_config)
        self._service._add_link(link)
        return self._create_byte_agent(link)

    def _create_link(self, gw, gw_init, context, auth, link_config):
        """

        :param gw:          gateway object for link
        :param gw_init:     callback for completed handshake
        :param context:     link context object
        :param link_config: config data for link

        link_config may be modified by the link, so caller should make sure
        each created link gets its own copy.

        """
        factory = self._service._config.link_factory
        link = factory.build(gw, self._reactor, self._processor, gw_init,
                             context=context, auth=auth, conf=link_config)
        return link

    def _create_byte_agent(self, link):
        raise NotImplementedError()


class _VOPByteAgentFactory(_ByteAgentFactory):
    def __init__(self, service, reactor, processor, gw_factory,
                 keypair, identity, certificates, p_auth, crypto,
                 internal, buf_size):
        s_init = super(_VOPByteAgentFactory, self).__init__
        s_init(service, reactor, processor, gw_factory)
        self._keypair = keypair
        self._identity = identity
        self._certificates = certificates
        self._p_auth = p_auth
        self._crypto = crypto
        self._internal = internal
        self._buf_size = buf_size
        self._rand = VUrandom()

    def _create_byte_agent(self, link):
        config = self._service._config
        ba_fun = link.create_byte_agent
        vec_io = ba_fun(internal=self._internal, buf_size=self._buf_size,
                        conf=config.vec_config)

        vts_factory = tls_factory = None
        if (config.enable_vts):
            def _factory(reactor):
                Cls = VSecureServer
                vts = Cls(reactor=reactor, crypto=self._crypto,
                          rand=self._rand, keypair=self._keypair,
                          identity=self._identity,
                          certificates=self._certificates,
                          p_auth=self._p_auth, conf=config.vts_config)
                ext_c = vts.cipher_consume
                ext_p = vts.cipher_produce
                int_c = vts.plain_consume
                int_p = vts.plain_produce
                return (ext_c, ext_p, int_c, int_p)
            vts_factory = _factory
        if (config.enable_tls):
            def _factory(reactor):
                Cls = VTLSServer
                tls = Cls(reactor=reactor, key=self._keypair,
                          identity=self._identity,
                          certificates=self._certificates,
                          p_auth=self._p_auth)
                ext_c = tls.cipher_consume
                ext_p = tls.cipher_produce
                int_c = tls.plain_consume
                int_p = tls.plain_produce
                return (ext_c, ext_p, int_c, int_p)
            tls_factory = _factory
        allow_insecure = config.allow_insecure

        Cls = VOPServerBridge
        vop = Cls(reactor=self._reactor, vec=vec_io, vts=vts_factory,
                  tls=tls_factory, insecure=allow_insecure)
        return vop.external_io
