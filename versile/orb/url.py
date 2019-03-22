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

""".. Framework for resolving :term:`VRI` identifiers."""
from __future__ import print_function, unicode_literals

import urllib
import urlparse

from versile.internal import _vexport, _v_silent, _val2b, _s2b, _pyver
from versile.common.util import VConfig, VLockable, VResult, VResultException
from versile.orb.entity import VProxy
from versile.orb.link import VLink
from versile.vse.container import VFrozenDict


__all__ = ['VUrl', 'VUrlException', 'VUrlResolver', 'VUrlConfig',
           'VUrlData']
__all__ = _vexport(__all__)


class VUrlException(Exception):
    """VUrl exception"""


class VUrl(object):
    """Reference to a :term:`VRI` identifying a resource.

    The :class:`VUrl` should not be instantiated directly, instead the
    :meth:`parse` factory method should be used.

    """

    def connect(self, gw=None, key=None, identity=None, certificates=None,
                auth=None, p_auth=None, crypto=None, internal=False,
                buf_size=None, conf=None, nowait=False):
        """Connects to peer and initiates :term:`VOL` handshake.

        :param gw:           local gateway object
        :type  gw:           :class:`versile.orb.entity.VObject`
        :param key:          key to use for the connection
        :type  key:          :class:`versile.crypto.VAsymmetricKey`
        :param identity:     identity (or None)
        :type  identity:     :class:`versile.crypto.x509.cert.VX509Name`
        :param certificates: chain
        :type  certificates: :class:`versile.crypto.x509.cert.VX509Certificate`
                             ,
        :param auth:         link-level peer authorizer
        :type  auth:         callable
        :param p_auth:       connection authorizer
        :type  p_auth:       :class:`versile.crypto.auth.VAuth`
        :param crypto:       crypto provider (default if None)
        :type  crypto:       :class:`versile.crypto.VCrypto`
        :param internal:     if True set buffersizes for internal socket
        :type  internal:     bool
        :param buf_size:     if not None, override default buffersizes
        :type  buf_size:     int
        :param conf:         additional configuration (default if None)
        :type  conf:         :class:`VUrlConfig`
        :param nowait:       if True perform non-blocking connect operation
        :type  nowait:       bool
        :returns:            resolver for accessing the target link resource
        :rtype:              :class:`VUrlResolver` or
                             :class:`versile.common.util.VResult`

        If *identity* is set it specifies what identity is being
        assumed for the connection. If *certificates* is set then it
        defines a certificate chain associated with *keypair*\ , which
        may include an identity set on the certificate. Only one of
        *identity* and *certificates* should be set.

        When *auth* is provided it is passed as the *auth* argument to
        a created link, see :class:`versile.orb.link.VLink` for
        details.

        When *p_auth* is set then the object is queried whether the
        peer connection can be approved. If *p_auth* is not set then a
        default :class:`versile.crypto.auth.VAuth` is constructed and
        used instead.

        If *internal* is True then buffer sizes in the
        consumer/producer chain of client sockets are set to
        :attr:`DEFAULT_INT_LINK_BUFSIZE`\ , otherwise the socket and
        entity channel defaults are used. If *buf_size* is set then it
        is used as buffer size, regardless of the value of *internal*.

        If a configuration object is passed in *conf*, the settings on
        that object will influence how the connection is set up. See
        configuration object documentation for details.

        If *nowait* is True then the result is returned as a
        :class:`versile.common.util.VResult` and a non-blocking URL
        address resolution is triggered.

        .. warning::

            Non-blocking address resolution consumes one thread until
            the address has been resolved (even if the operation is
            cancelled). The caller must take care not to initiate too
            many parallell method calls.

        Note that all parameters may not be supported by all schemes,
        e.g. :term:`VOP` with insecure plaintext transport does not
        support use of key, identity or certificates (as the protocol
        uses a plaintext channel).

        For a :term:`VOP` connection if *p_auth* is provided then an
        :meth:`versile.crypto.auth.VAuth.accept_host` check is
        performed, however
        :meth:`versile.crypto.auth.VAuth.accept_credentials` is not
        performed (as credentials are not exchanged with peer).

        The :term:`VOP` protocol with :term:`VTS` or :term:`TLS`
        transports support connecting with key and specified
        certificates, key and identity, key only, or without a key.

        .. warning::

            :term:`TLS` exchanges public keys, certificate chains and
            identities in plaintext before secure encrypted
            communication is initiated, both from the server side and
            client side.

        :term:`VTS` does not have the above limitation as client-side
        keys and certificate chains are sent encrypted to the server,
        so passing client credentials is secure if server is trusted.

        When connecting with a :term:`TLS` transport and (server) peer
        key validation is required then *p_auth* needs to be provided
        and the req_cert property set to True.

        Abstract method, derived classes must implement.

        """
        raise NotImplementedError()

    @classmethod
    def parse(cls, url):
        """Parses a :term:`VRI` and creates a :class:`VUrl` reference.

        :param url: a :term:`VRI` string for the resource
        :type  url: unicode
        :returns:   :class:`VUrl` identifying the resource.

        This is an abstract method, derived classes must implement.

        """
        raise NotImplementedError()

    @classmethod
    def resolve(cls, url, gw=None, key=None, identity=None, certificates=None,
                auth=None, p_auth=None, crypto=None, internal=False,
                buf_size=None, conf=None, nowait=False):
        """Parses, connects and resolves a URL.

        :param nowait: if True perform non-blocking resolve
        :type  nowait: bool
        :returns:      target resource (when resolved)
        :rtype:        :class:`versile.orb.entity.VEntity` or
                       :class:`versile.common.util.VResult`

        Other arguments are the same as :meth:`parse`\ ,
        :meth:`connect` and :meth:`VUrlResolver.resolve`\ .

        Resolution of target resource is equivalent (blocking call) to::

          url = cls.parse(url)
          ures = url.connect(gw, key, identity, certificates, auth, p_auth,
                             crypto, internal, buf_size, conf)
          result = ures.resolve()

        For a non-blocking call, the returned result reference may be
        cancelled. See :meth:`connect` and
        :meth:`VUrlResolver.resolve` for more information about
        non-blocking connect and resolve.

        """
        if not nowait:
            _res = cls.resolve
            call = _res(url=url, gw=gw, key=key, identity=identity,
                        certificates=certificates, auth=auth, p_auth=p_auth,
                        crypto=crypto, internal=internal, buf_size=buf_size,
                        conf=conf, nowait=True)
            return call.result()

        url = cls.parse(url=url)
        result = cls._create_cls_resolve_result()
        result._connect(url=url, gw=gw, key=key, identity=identity,
                        certificates=certificates, auth=auth,
                        p_auth=p_auth, crypto=crypto,
                        internal=internal, buf_size=buf_size,
                        conf=conf)
        return result

    @classmethod
    def resolve_with_link(cls, url, gw=None, key=None, identity=None,
                          certificates=None, auth=None, p_auth=None,
                          crypto=None, internal=False, buf_size=None,
                          conf=None, nowait=False):
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
                        conf=conf, nowait=True)
            return call.result()

        url = cls.parse(url=url)
        result = cls._create_cls_resolve_result(gw_only=False)
        result._connect(url=url, gw=gw, key=key, identity=identity,
                        certificates=certificates, auth=auth,
                        p_auth=p_auth, crypto=crypto,
                        internal=internal, buf_size=buf_size,
                        conf=conf)
        return result

    @classmethod
    def relative(cls, gw, relative_vri, nowait=False):
        """Resolves a partial VRI relative to a top-level gateway.

        :param gw:           top-level gateway for resolving relative VRI
        :param relative_vri: relative VRI (path and/or query)
        :type  relative_vri: unicode
        :param nowait:       if True return reference to pending result
        :type  nowait:       bool
        :returns:            target resource (when resolved)
        :rtype:              :class:`versile.orb.entity.VEntity` or
                             :class:`versile.common.util.VResult`
        :raises:             :exc:`VUrlException`

        Call result is similar to :meth:`resolve`\ .

        Top-level *gw* must be a top-level gateway returned by a link,
        e.g. resolved by a VRI with an empty path and query.

        *relative_vri* should (only) include the *path* and *query*
        VRI components, and must start with a leading '/' character.

        """
        return VUrlResolver.relative(gw, relative_vri, nowait)

    @classmethod
    def vri(self, scheme, domain, path, query_name=None, query_args=None,
            query_kargs=None, port=None):
        """Generates a :term:`VRI` for provided data.

        :param scheme:      scheme
        :type  scheme:      unicode
        :param domain:      domain
        :type  domain:      unicode
        :param path:        path components
        :type  path:        (unicode,)
        :param query_name:  query name
        :type  query_name:  unicode
        :param query_args:  unnamed query arguments
        :param query_kargs: named query arguments
        :type  query_kargs: dict
        :param port:        port number (default if None)
        :type  port:        int
        :returns:           generated :term:`VRI`
        :rtype:             unicode
        :raises:            :exc:`VUrlException`

        Query argument values are lazy-converted to the appropriate
        representation.

        """
        try:
            if _pyver == 3:
                if (not isinstance(scheme, str) or not isinstance(domain, str)
                    or query_name and not isinstance(query_name, str)):
                    raise VUrlException('VRI components must be strings')
                for p in path:
                    if not isinstance(p, str):
                        raise VUrlException('VRI path must be strings')
                if query_kargs:
                    for k in query_kargs.keys():
                        if not isinstance(k, str):
                            raise VUrlException('VRI keyword must be string')

            scheme = scheme.lower()
            if scheme != 'vop':
                raise VUrlResolver('Invalid scheme')
            for c in domain:
                if c in (':/&='):
                    raise VUrlResolver('Illegal domain character')
            encoder = VUrlResolver.encode
            path = (encoder(e) for e in path)
            query_name = encoder(query_name)
            def _lazy(val):
                if isinstance(val, bool):
                    if val:
                        return 'bool:True'
                    else:
                        return 'bool:False'
                elif isinstance(val, (int, long)):
                    return 'int:%s' % str(val)
                elif (val.startswith('bool:') or val.startswith('int:')
                      or val.startswith('str:')):
                    return 'str:' + val
                else:
                    return val
            if query_args:
                query_args = (_lazy(val) for val in query_args)
            else:
                query_args = tuple()
            _kargs = dict()
            if query_kargs:
                for key, val in query_kargs.items():
                    _kargs[encoder(key)] = _lazy(val)
            query_kargs = _kargs

            result = list()
            result.extend((scheme, '://', domain))
            if port is not None:
                result.extend((':', _val2b(port)))
            result.append('/')
            for p in path:
                result.extend((p, '/'))
            if query_name:
                result.append(query_name)
                if query_args or query_kargs:
                    result.append('?')
                first = True
                if query_args:
                    for arg in query_args:
                        if not first:
                            result.append('&')
                        first = False
                    result.append(encoder(arg))
                if query_kargs:
                    for key, val in query_kargs:
                        if not first:
                            result.append('&')
                        first = False
                    key, val = encoder(key), encoder(val)
                    result.extend((key, '=', val))
            return ''.join(result)
        except VUrlException as e:
            raise e
        except Exception as e:
            raise VUrlException(e.args)

    @classmethod
    def _create_cls_resolve_result(cls, gw_only=True):
        return _ClsResolveResult(gw_only=gw_only)


class VUrlResolver(VLockable):
    """Resolves the :term:`VRI` resource for a connected :class:`VUrl`\ .

    :param link:    the link of the connection
    :type  link:    :class:`versile.orb.link.VLink`
    :param urldata: parsed :term:`VRI` data of the :class:`VUrl`
    :type  urldata: :class:`VUrlData`

    This class should not be instantiated directly, instead it should
    be created and returned by calling :meth:`VUrl.connect`\ .

    """

    def __init__(self, link, urldata):
        super(VUrlResolver, self).__init__()
        self._link = link
        self._urldata = urldata
        self._resolve_called = False

    def resolve(self, nowait=False):
        """Resolves the resource.

        :param nowait: if True return reference to pending result
        :type  nowait: bool
        :returns:      target resource (when resolved)
        :rtype:        :class:`object` or :class:`versile.common.util.VResult`
        :raises:       :exc:`VUrlException`\ , :exc:`exception.Exception`

        If *nowait* is False then the call is blocking and returns the
        resolved resource. If *nowait* is True then a reference to the
        resource is returned as an asynchronous call result.

        Raises :exc:`VUrlException` if VRI path could not be
        resolved. If a query fails for a resolved path, the generated
        remote exception is raised.

        This method or :meth:`resolve_with_link` should only be called
        once.

        """
        if not nowait:
            return self.resolve(nowait=True).result()

        with self:
            if self._resolve_called:
                raise VUrlException('resolve() was already called')
            self._resolve_called = True

        path, query = self._urldata.path, self._urldata.query
        if query:
            query_args = (query[0],) + query[1]
            if query[2]:
                query_args += (VFrozenDict(query[2]),)

        result = _ResolveResult(self._link)
        resource = VResult()
        proc = self._link.processor

        if not query:
            resource.add_callpair(result.push_result,
                                  result.push_exception)
        else:
            def _query(obj):
                if not result.cancelled:
                    call = proc.queue_call(obj._v_call, query_args)
                    call.add_callpair(result.push_result,
                                      result.push_exception)
            resource.add_callpair(_query, result.push_exception)

        gateway = self._link.async_gw()
        if not path:
            gateway.add_callpair(resource.push_result,
                                 resource.push_exception)
        else:
            def _resource(gw):
                if not result.cancelled:
                    call = proc.queue_call(gw.urlget, (path,))
                    def _urlget_fail(exc):
                        _exc = VUrlException('URL path did not resolve')
                        resource.push_exception(_exc)
                    call.add_callpair(resource.push_result, _urlget_fail)
            gateway.add_callpair(_resource, result.push_exception)

        # Set up monitor feedback for the link, so an exception is
        # generated if the link fails before the call is completed
        _link = self._link
        class Listener(object):
            def bus_push(self, obj):
                if obj == VLink.STATUS_HANDSHAKING:
                    # Link status not yet resolved, just return
                    return
                if obj == VLink.STATUS_RUNNING:
                    # Do nothing, just let the listener unregister below
                    pass
                elif obj == VLink.STATUS_CLOSING:
                    result.push_exception(VUrlException('Link failed'))
                elif obj == VLink.STATUS_CLOSED:
                    result.push_exception(VUrlException('Link failed'))
                _link.status_bus.unregister_obj(self)
                result._listener = None
        _listener = Listener()
        result._listener = _listener
        _id = self.link.register_status_listener(_listener)

        return result

    def resolve_with_link(self, nowait=False):
        """Resolves the resource.

        :param nowait: if True return reference to pending result
        :type  nowait: bool
        :returns:      (resolved_resource, link)
        :rtype:        (:class:`object`\ , :class:`versile.orb.link.VLink`\ )
                       or :class:`versile.common.util.VResult`
        :raises:       :exc:`VUrlException`\ , :exc:`exception.Exception`

        Similar to :meth:`resolve` except the resolved resource is
        returned together with the link which was resolved.

        This method or :meth:`resolve` should only be called once.

        """
        if not nowait:
            return self.resolve_with_link(nowait=True).result()

        call = self.resolve(nowait=True)
        class _Result(VResult):
            def _cancel(self):
                call.cancel()
        result = _Result()
        _link = self.link
        def _res(res):
            result.push_result((res, _link))
        call.add_callpair(_res, result.push_exception)

        return result

    @classmethod
    def relative(cls, gw, relative_vri, nowait=False):
        """See :meth:`VUrl.relative`\ ."""
        if not nowait:
            return cls.relative(gw, relative_vri, nowait=True).result()

        # Parse path/query components
        if not relative_vri or not relative_vri[0] == '/':
            raise VUrlException('Relative VRI must start with \'/\'')
        if _pyver == 3 and not isinstance(relative_vri, str):
            raise VUrlException('Relative VRI must be a string')
        elif _pyver == 2 and isinstance(relative_vri, bytes):
            _vri = 'vop://dummy' + relative_vri
        else:
            _vri = 'vop://dummy' + relative_vri
        _urldata = VUrlData(_vri)
        path, query = _urldata.path, _urldata.query
        if query:
            query_args = (query[0],) + query[1]
            if query[2]:
                query_args += (VFrozenDict(query[2]),)

        # Resolve relative VRI relative to 'gw'
        result = VResult()
        resource = VResult()

        if not query:
            resource.add_callpair(result.push_result,
                                  result.push_exception)
        else:
            def _query(obj):
                if not result.cancelled:
                    if not isinstance(obj, VProxy):
                        obj = obj._v_proxy()
                    fun = getattr(obj, query_args[0])
                    call = fun(*query_args[1:], nowait=True)
                    call.add_callpair(result.push_result,
                                      result.push_exception)
            resource.add_callpair(_query, result.push_exception)

        if not path:
            resource.push_result(gw)
        else:
            call = gw.urlget(path, nowait=True)
            def _urlget_fail(exc):
                _exc = VUrlException('URL path did not resolve')
                resource.push_exception(_exc)
            call.add_callpair(resource.push_result, _urlget_fail)

        return result

    @property
    def link(self):
        """The link for the connected URL being resolved."""
        return self._link

    @classmethod
    def encode(self, s):
        """Encode a percent-encoded UTF8-encoded.

        :param s: string to decode
        :type  s: unicode
        :return:  encoded string
        :type  s: unicode
        :raises:  :exc:`VUrlException`

        """
        try:
            return urllib.quote(s)
        except:
            raise VUrlException()

    @classmethod
    def decode(self, s):
        """Decode a percent-encoded UTF8-encoded.

        :param s: string to decode
        :type  s: unicode
        :return:  decoded string
        :rtype:   unicode
        :raises:  :exc:`VUrlException`

        """
        try:
            return urllib.unquote(s)
        except:
            raise VUrlException('Could not decode from percent-encoded UTF8')


class VUrlData(object):
    """Parses a :term:`VRI` string and exposes its components as attributes.

    :param url: :term:`VRI` string for the resource
    :type  url: unicode
    :raises:    :exc:`VUrlException`

    URLs are resolved from a format
    ``'scheme://domain:port/path/[query_name[?query_args]]'`` where
    *query_args* has the format ``'name1=value1&name2=value2[..]'``

    """
    def __init__(self, url):
        if _pyver == 3 and not isinstance(url, str):
            raise VUrlException('VRI must be a string')
        parsed = urlparse.urlparse(url)

        self._scheme = parsed.scheme.lower()

        loc = parsed.netloc

        # Extract port number (if any)
        if ':' in loc:
            domain, port = loc.rsplit(':', 1)
            if ']' in port:
                # This is an IPv6 address without port
                domain = loc
                port=None
            else:
                try:
                    port = int(port)
                except:
                    raise VUrlException('Invalid port (not a number)')
        else:
            domain, port = loc, None

        # Validate domain
        if not domain:
            raise VUrlException('No domain set')
        elif ':' in domain:
            if not domain[0] == '[' and domain[-1] == ']':
                # Illegal except for IPv6 literal addresses
                raise VUrlException('\':\' character not allowed in domain')

        self._domain, self._port = domain, port

        _path = parsed.path.strip()
        if not _path.startswith('/'):
            raise VUrlException('Invalid path, must start with \'/\'')
        _plist = _path.split('/')
        path = _plist[1:-1]
        query = None
        decoder = VUrlResolver.decode
        if _plist[-1]:
            sval = _plist[-1]
            param_list = []
            q_args = []
            q_kargs = []
            if '?' in sval:
                try:
                    q_name, _params = sval.split('?')
                    q_name = decoder(q_name)
                except:
                    raise VUrlException('Invalid parameter format')
                args = _params.split('&')
                for arg in args:
                    if '=' in arg:
                        try:
                            key, value = arg.split('=')
                            key, value = decoder(key), decoder(value)
                        except:
                            raise VUrlException('Invalid parameter format')
                        try:
                            value = self.convert_value(value)
                        except ValueError:
                            raise VUrlException('Value conversion error')
                        q_kargs.append([decoder(e) for e in key, value])
                    else:
                        value = decoder(arg)
                        try:
                            value = self.convert_value(value)
                        except ValueError:
                            raise VUrlException('Value conversion error')
                        q_args.append(value)
            else:
                q_name = sval
            query = (q_name, tuple(q_args), dict(q_kargs))
        self._path = tuple(decoder(e) for e in path)
        for r in self._path:
            if not r:
                raise VUrlException('Illegal (empty) path component')
        self._query = query

    @classmethod
    def convert_value(cls, value):
        """Converts values to a type-casted version.

        :param value: unicode
        :raises:      :exc:`exceptions.ValueError`

        Performs conversion as per the :term:`VRI` specification. If a
        recognized type qualifier is included but the string is
        invalid for the conversion, an exception is raised.

        If *value* has a leading keyword which is not recognized,
        *value* is returned as-is.

        """
        if not ':' in value:
            return value
        keyword, value = value.split(':', 1)
        if keyword == 'str':
            return value
        elif keyword == 'int':
            return int(value)
        elif keyword == 'bool':
            if value == 'True':
                return True
            elif value == 'False':
                return False
            else:
                raise ValueError()
        else:
            return value

    @property
    def scheme(self):
        """The :term:`VRI` scheme."""
        return self._scheme

    @property
    def domain(self):
        """The :term:`VRI` domain component."""
        return self._domain

    @property
    def port(self):
        """The :term:`VRI` port component (None if not set)."""
        return self._port

    @property
    def path(self):
        """The :term:`VRI` path component (q_name, args, kargs)."""
        return self._path

    @property
    def query(self):
        """:term:`VRI` query parameters (unicode, dict)."""
        return self._query


class VUrlConfig(VConfig):
    """Configuration settings for a :class:`VUrl`\ .

    :param link_config:  link configuration
    :type  link_config:  :class:`versile.orb.link.VLinkConfig`

    Additional configurations can be set in *kargs*\ .

    """
    def __init__(self, link_config, **kargs):
        super(VUrlConfig, self).__init__(link_config=link_config, **kargs)


class _ResolveResult(VResult):
    def __init__(self, link):
        super(_ResolveResult, self).__init__()
        self._link = link
    def _cancel(self):
        with self:
            if self._link:
                self._link.shutdown(force=True)
                self._link = None


class _ClsResolveResult(VResult):
    def __init__(self, gw_only=True):
        super(_ClsResolveResult, self).__init__()
        self._c_result = self._r_result = None
        self._gw_only = gw_only

    def _connect(self, url, gw, key, identity, certificates, auth, p_auth,
                 crypto, internal, buf_size, conf, **kargs):
        with self:
            self._c_result = url.connect(gw=gw, key=key, identity=identity,
                                         certificates=certificates, auth=auth,
                                         p_auth=p_auth, crypto=crypto,
                                         internal=internal, buf_size=buf_size,
                                         conf=conf, nowait=True, **kargs)
            self._c_result.add_callpair(self._resolve, self._failback)

    def _resolve(self, resolver):
        with self:
            if not self.cancelled:
                self._c_result = None
                if self._gw_only:
                    self._r_result = resolver.resolve(nowait=True)
                else:
                    self._r_result = resolver.resolve_with_link(nowait=True)
                self._r_result.add_callpair(self._wrapup, self._failback)

    def _wrapup(self, result):
        if not self.cancelled:
            with self:
                self._r_result = None
            self.push_result(result)

    def _failback(self, exc):
        self._cancel()
        self.push_exception(exc)

    def _cancel(self):
        with self:
            if self._c_result:
                result, self._c_result = self._c_result, None
                try:
                    result.cancel()
                except VResultException as e:
                    _v_silent(e)
            if self._r_result:
                result, self._r_result = self._r_result, None
                try:
                    result.cancel()
                except VResultException as e:
                    _v_silent(e)
