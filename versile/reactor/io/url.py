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

""".. Reactor based implementations of :mod:`versile.orb.url` classes."""
from __future__ import print_function, unicode_literals

import datetime
import socket

from versile.internal import _vexport
from versile.common.iface import abstract
from versile.common.peer import VSocketPeer
from versile.common.util import VNamedTemporaryFile
from versile.common.util import VResult
from versile.crypto import VCrypto
from versile.crypto.auth import VAuth
from versile.crypto.rand import VUrandom
from versile.crypto.x509 import VX509Crypto, VX509Format
from versile.crypto.x509.cert import VX509Name
from versile.crypto.x509.cert import VX509CertificationRequest
from versile.orb.url import VUrlException, VUrlResolver, VUrl as OrbUrl
from versile.orb.url import VUrlData, VUrlConfig
from versile.reactor.io import VFIOLost
from versile.reactor.io.sock import VClientSocketAgent
from versile.reactor.io.vec import VEntitySerializerConfig
from versile.reactor.io.link import VLinkAgent, VLinkAgentConfig
from versile.reactor.io.tls import VTLSClient
from versile.reactor.io.tlssock import VTLSClientSocketAgent
from versile.reactor.io.vop import VOPClientBridge
from versile.reactor.io.vts import VSecureClient, VSecureConfig

__all__ = ['VUrl', 'VOPUrlConfig', 'VOPInsecureUrlConfig']
__all__ = _vexport(__all__)


@abstract
class VUrl(OrbUrl):
    """Reference to a :term:`VRI` identifying a resource.

    The class uses the reactor framework for setting up and resolving

    Should not be instantiated directly, instead use :meth:`parse`\ .

    """

    def __init__(self, urldata):
        self._urldata = urldata
        domain, port = urldata.domain, urldata.port
        if port is None:
            port = self._default_port()
        self._address = (domain, port)

    @classmethod
    def parse(cls, url):
        urldata = VUrlData(url)
        scheme = urldata.scheme
        if scheme == 'vop':
            return _VopUrl(urldata)
        else:
            raise VUrlException('URL scheme not supported')

    def connect(self, gw=None, key=None, identity=None, certificates=None,
                auth=None, p_auth=None, crypto=None, internal=False,
                buf_size=None, conf=None, nowait=True, reactor=None,
                processor=None):
        """See :meth:`versile.orb.url.VUrl.connect`

        :param reactor:   a (running) reactor for the link
        :param processor: processor for remote calls
        :type  processor: :class:`versile.common.processor.VProcessor`

        Other arguments are similar to
        :meth:`versile.orb.url.VUrl.connect`\ . If provided *reactor*
        and *processor* arguments are passed to the
        :class:`versile.reactor.io.link.VLinkAgent` constructor when
        setting up the link. If they are None then the link
        lazy-creates its own reactor and/or processor.

        .. warning::

            When connecting over VTLS and *key* is provided, the
            reactor :term:`TLS` framework stores key and certificate
            data in :class:`VNamedTemporaryFile` files. This is due to
            the limitations of the current TLS implementation. Writing
            keys and certificates to the file system is a security
            risk - make sure implications are understood before using.

        Different protocols require different types for the *conf*
        argument. A configuration object of the appropriate type can
        be instantiated with :meth:`default_config`\ . This allows
        setting configuration options which are common to all
        protocols, such as link configuration.

        """
        raise NotImplementedError()

    @classmethod
    def resolve(cls, url, gw=None, key=None, identity=None, certificates=None,
                auth=None, p_auth=None, crypto=None, internal=False,
                buf_size=None, conf=None, nowait=False, reactor=None,
                processor=None):
        """See :meth:`versile.orb.url.VUrl.resolve`\ .

        :param reactor:   a (running) reactor for the link
        :param processor: processor for remote calls
        :type  processor: :class:`versile.common.processor.VProcessor`

        Similar to :meth:`versile.orb.url.VUrl.resolve` but adds
        *reactor* and *processor* as optional keyword arguments which
        are passed to :meth:`connect`\ . This enables setting reactor
        and/or processor for the link of the resolved VRI.

        """
        if not nowait:
            _res = cls.resolve
            call = _res(url=url, gw=gw, key=key, identity=identity,
                        certificates=certificates, auth=auth, p_auth=p_auth,
                        crypto=crypto, internal=internal, buf_size=buf_size,
                        conf=conf, reactor=reactor, processor=processor,
                        nowait=True)
            return call.result()

        url = cls.parse(url=url)
        result = cls._create_cls_resolve_result()
        result._connect(url=url, gw=gw, key=key, identity=identity,
                        certificates=certificates, auth=auth,
                        p_auth=p_auth, crypto=crypto,
                        internal=internal, buf_size=buf_size,
                        conf=conf, reactor=reactor,
                        processor=processor)
        return result

    @classmethod
    def resolve_with_link(cls, url, gw=None, key=None, identity=None,
                          certificates=None, auth=None, p_auth=None,
                          crypto=None, internal=False, buf_size=None,
                          conf=None, nowait=False, reactor=None,
                          processor=None):
        """Parses, connects and resolves a URL.

        :returns:      (target resource, link)
        :rtype:        (:class:`object`\ , :class:`versile.orb.link.VLink`\ )
                       or :class:`versile.common.util.VResult`

        Arguments and use is similar to :meth:`resolve`\ , but returns
        a resolved resource together with the associated link, instead
        of returning only the resource.

        """
        if not nowait:
            _res = cls.resolve_with_link
            call = _res(url=url, gw=gw, key=key, identity=identity,
                        certificates=certificates, auth=auth, p_auth=p_auth,
                        crypto=crypto, internal=internal, buf_size=buf_size,
                        conf=conf, reactor=reactor, processor=processor,
                        nowait=True)
            return call.result()

        url = cls.parse(url=url)
        result = cls._create_cls_resolve_result(gw_only=False)
        result._connect(url=url, gw=gw, key=key, identity=identity,
                        certificates=certificates, auth=auth,
                        p_auth=p_auth, crypto=crypto,
                        internal=internal, buf_size=buf_size,
                        conf=conf, reactor=reactor,
                        processor=processor)
        return result


    @classmethod
    def default_config(cls):
        """Returns a default configuration object of appropriate type.

        :returns: an instantiated configuration object
        :rtype:   :class:`VUrlConfig`

        Protocols require different configuration object
        structure. This method allows instantiating an object and
        manipulating e.g. link-level configuration objects which are
        common to all configuration classes.

        """
        raise NotImplementedError()

    @classmethod
    def _default_port(self):
        return 43400


class _VopUrl(VUrl):
    """Implements :class:`VUrl` for the :term:`VOP` protocol."""

    def __init__(self, urldata):
        if urldata.scheme != 'vop':
            raise VUrlException('Invalid URL scheme')
        super(_VopUrl, self).__init__(urldata)

    def connect(self, gw=None, key=None, identity=None, certificates=None,
                auth=None, p_auth=None, crypto=None, internal=False,
                buf_size=None, conf=None, nowait=False, reactor=None,
                processor=None):
        if not nowait:
            _res = self.connect
            call = _res(gw=gw, key=key, identity=identity,
                        certificates=certificates, auth=auth, p_auth=p_auth,
                        crypto=crypto, internal=internal, buf_size=buf_size,
                        conf=conf, reactor=reactor, processor=processor,
                        nowait=True)
            return call.result()

        if p_auth is None:
            p_auth = VAuth()
        if conf is None:
            conf = VOPUrlConfig()

        if not key and (identity is not None or certificates is not None):
            raise VUrlException('VOP credentials requires sending a key')

        link_config = conf.link_config
        # Add the VEC config as a property on the link configuration
        # so it can be also accessed via the link config object
        link_config.vec_config = conf.vec_config

        link = VLinkAgent(gateway=gw, auth=auth, conf=link_config,
                          reactor=reactor, processor=processor)

        # Set up default crypto
        crypto = VCrypto.lazy(crypto)
        rand = VUrandom()

        bsize = buf_size
        if internal and bsize is None:
            bsize = VLinkAgent.DEFAULT_INT_LINK_BUFSIZE

        # Get VEC byte interface to link
        vec_io = link.create_byte_agent(internal=internal, buf_size=buf_size,
                                        conf=conf.vec_config)

        # Set up VOP multiplexer
        vts_factory = tls_factory = None
        if (conf.enable_vts):
            def _factory(reactor):
                Cls = VSecureClient
                vts = Cls(reactor=reactor, crypto=crypto,
                          rand=rand, keypair=key, identity=identity,
                          certificates=certificates, p_auth=p_auth,
                          conf=conf.vts_config)
                ext_c = vts.cipher_consume
                ext_p = vts.cipher_produce
                int_c = vts.plain_consume
                int_p = vts.plain_produce
                return (ext_c, ext_p, int_c, int_p)
            vts_factory = _factory
        if (conf.enable_tls):
            def _factory(reactor):
                Cls = VTLSClient
                tls = Cls(reactor=reactor, key=key, identity=identity,
                          certificates=certificates, p_auth=p_auth)
                ext_c = tls.cipher_consume
                ext_p = tls.cipher_produce
                int_c = tls.plain_consume
                int_p = tls.plain_produce
                return (ext_c, ext_p, int_c, int_p)
            tls_factory = _factory
        allow_insecure = conf.allow_insecure
        Cls = VOPClientBridge
        vop = Cls(reactor=link.reactor, vec=vec_io, vts=vts_factory,
                  tls=tls_factory, insecure=allow_insecure)

        if bsize is None:
            sock = VClientSocketAgent(reactor=link.reactor)
        else:
            sock = VClientSocketAgent(reactor=link.reactor, max_read=bsize,
                                      max_write=bsize)
        def _connecter(peer):
            sock.connect(peer)
            sock.byte_io.attach(vop.external_io)
            return VUrlResolver(link, self._urldata)

        result = _ConnectResult(link)
        def _cback(peer):
            if not result.cancelled:
                result.push_result(_connecter(peer))
        def _fback(exc):
            result.cancel()
        peer_res = VSocketPeer.lookup(host=self._address[0],
                                      port=self._address[1],
                                      socktype=socket.SOCK_STREAM,
                                      nowait=True)
        peer_res.add_callpair(_cback, _fback)
        return result

    @classmethod
    def default_config(cls):
        return VOPUrlConfig()

    @classmethod
    def _default_port(self):
        return 4433


class VOPUrlConfig(VUrlConfig):
    """Base reactor URL configuration settings for VOP protocol.

    :param link_config:  link configuration (default if None)
    :type  link_config:  :class:`versile.orb.link.VLinkAgentConfig`
    :param vec_config:   entity channel configuration (default if None)
    :type  vec_config:   :class:`versile.reactor.io.VEntitySerializerConfig`
    :param enable_vts:     if True enable the VTS transport
    :type  enable_vts:     bool
    :param enable_tls:     if True enable the TLS transport
    :type  enable_tls:     bool
    :param allow_insecure: if True allow insecure unencrypted transport
    :type  allow_insecure: bool
    :param vts_config:     VTS configuration (default if None)
    :type  vts_config:     :class:`versile.reactor.io.vts.VSecureConfig`

    For other parameters see :class:`VUrlConfig`\ .

    """
    def __init__(self, link_config=None, vec_config=None,
                 enable_vts=True, enable_tls=False, allow_insecure=False,
                 vts_config=None, **kargs):
        if link_config is None:
            link_config = VLinkAgentConfig()
        if vec_config is None:
            vec_config = VEntitySerializerConfig()
        if vts_config is None:
            vts_config = VSecureConfig()
        s_init = super(VOPUrlConfig, self).__init__
        s_init(link_config=link_config, vec_config=vec_config,
               enable_vts=enable_vts, enable_tls=enable_tls,
               allow_insecure=allow_insecure, vts_config=vts_config, **kargs)


class VOPInsecureUrlConfig(VOPUrlConfig):
    """Base reactor URL configuration settings for an insecure VOP protocol.

    Defaults with settings for operating an insecure connection
    without any encryption. For parameters see :class:`VOPUrlConfig`\ .

    .. warning::

        This configuration should be used with caution, and only for
        connections that are made in protected environments where
        security is controlled via other mechanisms.

    """
    def __init__(self, link_config=None, vec_config=None,
                 enable_vts=False, enable_tls=False, allow_insecure=True,
                 vts_config=None, **kargs):
        if vts_config is None:
            vts_config = VSecureConfig()
        s_init = super(VOPInsecureUrlConfig, self).__init__
        s_init(link_config=link_config, vec_config=vec_config,
               enable_vts=enable_vts, enable_tls=enable_tls,
               allow_insecure=allow_insecure, vts_config=vts_config, **kargs)


class _ConnectResult(VResult):
    def __init__(self, link):
        super(_ConnectResult, self).__init__()
        self._link = link
    def _cancel(self):
        with self:
            if self._link:
                self._link.shutdown(force=True)
                self._link is None
