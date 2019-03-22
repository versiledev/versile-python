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

"""Implements :term:`VSE` utility types.

Importing registers :class:`VUtilityModule` as a global module.

"""
from __future__ import print_function, unicode_literals

import inspect
import threading
import time

from versile.internal import _vexport
from versile.common.iface import abstract
from versile.crypto.rand import VUrandom
from versile.orb.entity import VEntity, VObject, VProxy, VTagged, VBoolean
from versile.orb.entity import VException, VCallError, VTaggedParseError
from versile.orb.external import VExternal, publish
from versile.orb.module import VModuleResolver, VModule
from versile.orb.module import VERBase
from versile.orb.validate import vchk, vtyp, vset
from versile.reactor.io.url import VUrl
from versile.reactor.io.vudp import VUDPRelayedVOPConnecter
from versile.vse.const import VSECodes, VSEModuleCodes

__all__ = ['VFunction', 'VFunctionProxy', 'VUDPRelay', 'VUDPRelayedVOP',
           'VPasswordLogin', 'VPasswordLoginHandler', 'VUtilityModule']
__all__ = _vexport(__all__)


class VFunction(VERBase, VExternal):
    """A function which can be remotely called.

    .. automethod:: __call__

    """

    def __init__(self, func, min_arg=None, max_arg=None, lazy_arg=True,
                 doc=None, lazy_doc=True):
        VExternal.__init__(self)

        self._func = func

        if min_arg is not None or max_arg is not None:
            if min_arg is None:
                min_arg = 0
            for arg in min_arg, max_arg:
                if arg is not None and arg < 0:
                    raise VException('Argument limit cannot be negative')
            if max_arg is not None and max_arg < min_arg:
                raise VException('Max arg limit cannot be < min arg limit')
        elif lazy_arg:
            spec = inspect.getargspec(func)
            if not spec.args:
                min_arg = 0
            elif spec.args[0] in ('self', 'cls'):
                min_arg = len(spec.args) - 1
            else:
                min_arg = len(spec.args)
            if spec.varargs is not None:
                max_arg = None
            elif spec.defaults is None:
                max_arg = min_arg
            else:
                max_arg = min_arg + len(spec.defaults)
        else:
            raise VException('Missing information about number of arguments')
        self._min_arg = min_arg
        self._max_arg = max_arg

        if doc:
            self._doc = doc
        elif lazy_doc:
            try:
                doc = getattr(func, '__doc__')
            except AttributeError:
                self._doc = None
            else:
                # Convert docstring to unicode (VString) ; this code was
                # borrowed from the versile.orb.external @doc decorator. If
                # conversion fails, documentation is set to None
                try:
                    lines = doc.split('\n')
                    if lines:
                        first = lines[0]
                        remaining = '\n'.join(lines[1:])
                        if remaining:
                            remaining = textwrap.dedent(remaining)
                            doc = '\n'.join((first, remaining, ''))
                        else:
                            doc = first + '\n'
                    else:
                        doc = ''
                except:
                    doc = None
                else:
                    try:
                        doc = unicode(doc)
                    except:
                        doc = None
                self._doc = doc

    def __call__(self, *args):
        """Returns *function(\*args)*\ ."""
        return self._func(*args)

    @publish(show=True, ctx=False)
    def peer_call(self, *args):
        """Perform function call.

        :param args: function arguments
        :returns:    function result
        :raises:     :exc:`versile.orb.entity.VCallError` or function exception

        """
        with self:
            func = self._func
            if func is None:
                raise VCallError('Function has been disabled')

        if ((self._min_arg is not None and len(args) < self._min_arg)
            or (self._max_arg is not None and len(args) > self._max_arg)):
            raise VCallError('Illegal number of call arguments')

        return func(*args)

    @publish(show=True, ctx=False)
    def peer_doc(self):
        """Return function documentation string.

        :returns: documentation string (or None)
        :rtype:   unicode

        """
        with self:
            if self._func is None:
                raise VCallError('Function has been disabled')
            return self._doc

    @property
    def proxy(self):
        """Holds a proxy to the function (:class:`VFunctionProxy`\ )"""
        return VFunctionProxy(self, self._min_arg, self._max_arg)

    def disable(self):
        """Disables and dereferences the locally held function."""
        with self:
            self._func = None
            self._doc = None

    def _v_as_tagged(self, context):
        tags = VSECodes.FUNCTION.tags(context) + (self._min_arg, self._max_arg)
        return VTagged(self._v_raw_encoder(), *tags)


class VFunctionProxy(VERBase, VEntity):
    """A reference to a function which can be called remotely.

    .. automethod:: __call__

    """

    def __init__(self, peer, min_arg, max_arg):
        self._peer = peer
        self._min_arg = min_arg
        self._max_arg = max_arg

    def __call__(self, *args, **kargs):
        """Perform a function call on the remote function reference.

        :param args:  arguments passed to the function
        :param kargs: call modifiers
        :returns:     call result
        :raises:      call exception

        Call modifiers (keywords) are passed to remote function
        execution, and can be any of the keyword arguments supported
        by :meth:`VObject._v_call`\ .

        If keywords are used to perform an asynchronous call
        (e.g. 'nowait'), then an asynchronous call reference is
        returned instead of an immediate call result.

        """
        return self._peer.peer_call(*args, **kargs)

    def doc(self, **kargs):
        """Returns a docstring for the remote function.

        :param kargs: call modifiers
        :returns:     call result
        :raises:      call exception

        Docstring is retreived as a remote call. Call modifiers take a
        similar role as :meth:`__call__`\ .

        """
        return self._peer.peer_doc(**kargs)

    def _v_as_tagged(self, context):
        tags = VSECodes.FUNCTION.tags(context) + (self._min_arg, self._max_arg)
        return VTagged(self._peer, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Returns decoder for :class:`versile.orb.entity.VTagged`."""
        if len(tags) != 2:
            raise VTaggedParseError('Encoding requires 2 residual tags')
        min_arg, max_arg = tags
        min_arg = VEntity._v_lazy_native(min_arg)
        max_arg = VEntity._v_lazy_native(max_arg)
        for arg in (min_arg, max_arg):
            if arg is None:
                continue
            if isinstance(arg, (int, long)) and arg >= 0:
                continue
            raise VTaggedParseError('Limit must be non-negative int or None')
        if min_arg is not None and max_arg is not None and max_arg < min_arg:
            raise VTaggedParseError('Max arguments must be None or > min args')
        if isinstance(value, VObject):
            value = value._v_proxy()
        if not isinstance(value, VProxy):
            raise VTaggedParseError('Encoding value must be object reference')
        return (lambda x: cls(*x), [value, min_arg, max_arg])


class VUDPRelay(VERBase, VEntity):
    """Relay for making a Versile UDP Transport connection.

    :param handler: reference to relay handler
    :type  handler: :class:`versile.orb.entity.VProxy`

    Implements the standard VUDP Relay procedure for negotiating a
    Versile UDP Transport peer connection.

    """

    def __init__(self, handler):
        self._handler = handler

    @property
    def handler(self):
        """Relay handler (:class:`versile.orb.entity.VProxy`\ )."""
        return self._handler

    def _v_as_tagged(self, context):
        tags = VSECodes.UDPRELAY.tags(context)
        return VTagged(self._handler, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Returns decoder for :class:`versile.orb.entity.VTagged`."""
        if tags:
            raise VTaggedParseError('Encoding should have no residual tags')
        if isinstance(value, VObject):
            value = value._v_proxy()
        if not isinstance(value, VProxy):
            raise VTaggedParseError('Encoding value must be object reference')
        return (lambda x: cls(*x), [value])


class VUDPRelayedVOP(VUDPRelay):
    """A VUDP Relay to a :term:`VOP` link.

    :param handler:       reference to relay handler
    :type  handler:       :class:`versile.orb.entity.VProxy`
    :param is_vop_client: if True is VOP client , otherwise server
    :type  is_vop_client: bool

    The held handler is a reference to a handler which implements the
    VUDP Relay 'Client Relay' interface.

    The relayed Versile UDP Transport must transport a :term:`VOP`
    link connection. As VOP connects two peers taking a role of
    'client' and 'server', each side of the connection must know which
    role to perform. The :attr:`is_vop_client` property defines which
    role this side of the connection should take.

    """

    def __init__(self, handler, is_vop_client):
        super(VUDPRelayedVOP, self).__init__(handler)
        self._is_vop_client = is_vop_client

    def relay_vop(self, gateway=None, reactor=None, processor=None,
                  init_callback=None, context=None, auth=None, link_conf=None,
                  key=None, identity=None, certificates=None, p_auth=None,
                  vts=True, tls=False, insecure=False, crypto=None,
                  internal=False, buf_size=None, vec_conf=None, vts_conf=None,
                  timeout=30, nowait=False, udp_filter=None):
        """Resolves a relayed :term:`VUT` connection as a :term:`VOP` link.

        :param timeout:   max seconds for resolving connection (or None)
        :type  timeout:   float
        :param nowait:    if True return async reference to result
        :type  nowait:    bool
        :returns:         gateway of resolved service
        :rtype:           :class:`versile.orb.entity.VProxy`

        Remaining parameters are similar to
        :class:`versile.reactor.io.vudp.VUDPRelayedVOPConnecter`\ .

        Automatically takes VOP client/server role depending on which
        configuration is set on the object.

        .. note::

            Keep in mind VOP servers which provide secure connections
            (which is the default) must provide a key pair for the
            connection

        If *nowait* is True then the result is returned as a
        :class:`versile.common.util.VResult`\ .

        .. warning::

            *udp_filter* can be applied to prevent a relay from directing
            relayed connection handshake to an arbitrary IP address, see
            :class:`versile.reactor.io.vudp.VUDPRelayedVOPConnecter`
            for more information.

        The method call negotiates a :term:`VUT` transport with a peer
        via the UDP relay and negotiates a :term:`VOP` link with the
        peer over the UDP based transport. The peer gateway of the
        negotiated link is returned as a result.

        """
        # Create client connecter for VUDPRelay client connect operation
        _Cls = VUDPRelayedVOPConnecter
        is_client = self._is_vop_client
        conn = _Cls(is_client=is_client, gateway=gateway, reactor=reactor,
                    processor=processor, init_callback=init_callback,
                    context=context, auth=auth, link_conf=link_conf, key=key,
                    identity=identity, certificates=certificates,
                    p_auth=p_auth, vts=vts, tls=tls, insecure=insecure,
                    crypto=crypto, internal=internal, buf_size=buf_size,
                    vec_conf=vec_conf, vts_conf=vts_conf,
                    udp_filter=udp_filter)

        # Initiate handshake
        cur_time = time.time()
        l_token = VUrandom()(32)
        rel_params = self._handler.connect(l_token, conn, nowait=True)

        # Set timer for relay connect timeout
        timer = None
        if timeout is not None:
            def _expire():
                conn.peer_gw.cancel()
                rel_params.cancel()
            timer = threading.Timer(timeout, _expire)
            timer.start()

        # Set handlers for performing connect
        def _result(res):
            try:
                vchk(res, vtyp(tuple), len(res) == 3)
                host, port, r_token = res
                vchk(host, vtyp(unicode), vset)
                vchk(port, vtyp(int, long), 1024<=port<=65535)
                vchk(r_token, vtyp(bytes), len(r_token)<=32)
            except:
                conn.peer_gw.cancel()
                return
            if timer:
                timer.cancel()
            tm_out = timeout
            if tm_out is not None:
                tm_out = max(timeout-(time.time()-cur_time), 0.0)
            conn.connect_udp(host, port, l_token, r_token, timeout=tm_out)
        def _error(exc):
            if timer:
                timer.cancel()
            rel_params.cancel()
            conn.peer_gw.cancel()
        rel_params.add_callpair(_result, _error)

        if nowait:
            return conn.peer_gw
        else:
            return conn.peer_gw.result()

    @property
    def is_vop_client(self):
        """If True this VOP side should take client role, otherwise server."""
        return self._is_vop_client

    def _v_as_tagged(self, context):
        tags = VSECodes.UDPRELAYEDVOP.tags(context) + (self._is_vop_client,)
        return VTagged(self._handler, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Returns decoder for :class:`versile.orb.entity.VTagged`."""
        if not tags or len(tags) != 1:
            raise VTaggedParseError('Encoding must have one residual tag tag')
        is_client = tags[0]
        if not isinstance(is_client, (bool, VBoolean)):
            raise VTaggedParseError('Residual tag must be boolean')
        if isinstance(value, VObject):
            value = value._v_proxy()
        if not isinstance(value, VProxy):
            raise VTaggedParseError('Encoding value must be object reference')
        return (lambda x: cls(*x), [value, is_client])


class VPasswordLogin(VERBase, VEntity):
    """References a login object for user/password authentication.

    :param handler: reference to login handler
    :type  handler: :class:`versile.orb.entity.VProxy`

    This type is normally returned when a client is attempting to
    access a resource e.g. via :term:`VRI` resolution which requires
    the client to be authenticated, and the client is not
    authenticated via other means (such as public-key verification on
    a secure transport).

    This class is typically not instantiated directly, but is resolved
    by a :term:`VSE` resolver when decoding a reference to a remote
    :class:`VPasswordLoginHandler`\ .

    """

    def __init__(self, handler):
        self._handler = handler

    def login(self, username, password, **kargs):
        """Performs a login attempt.

        :param user:     username
        :type  user:     unicode
        :param password: password
        :type  password: unicode
        :returns:        (login_status, resource)
        :rtype:          (bool, object)
        :raises:         :exc:`versile.orb.entity.VException`

        *login_status* should be True if authentication succeeded,
        otherwise False.

        If login succeeded and access to the requested resource was
        approved, *resource* should hold the resource which login
        granted access to. If login did not succeed, *resource* should
        normally be None.

        If authentication succeeded however the authenticated user is
        not authorized to access the requested resource, an exception
        should be raised.

        *kargs* are keyword arguments for a
        :class:`versile.orb.entity.VProxy` method call, such as
        'nowait' or 'oneway'.

        """
        return self._handler.login(username, password, **kargs)

    @property
    def handler(self):
        """Relay handler (:class:`versile.orb.entity.VProxy`\ )."""
        return self._handler

    def _v_as_tagged(self, context):
        tags = VSECodes.LOGIN.tags(context)
        return VTagged(self._handler, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Returns decoder for :class:`versile.orb.entity.VTagged`."""
        if tags:
            raise VTaggedParseError('Encoding should have no residual tags')
        if isinstance(value, VObject):
            value = value._v_proxy()
        if not isinstance(value, VProxy):
            raise VTaggedParseError('Encoding value must be object reference')
        if isinstance(value(), VPasswordLoginHandler):
            return (None, [value])
        return (lambda x: cls(*x), [value])


class VPasswordLoginHandler(VERBase, VExternal):
    """References a handler for providing user/password authentication.

    The class is abstract and must override :meth:`handle_login`\ .

    .. automethod:: _invalid_type_handler

    """

    def __init__(self):
        VExternal.__init__(self)

    @publish(show=True, ctx=True)
    def login(self, username, password, ctx):
        try:
            vchk(username, vtyp(unicode))
            vchk(password, vtyp(unicode))
        except:
            self._invalid_type_handler()
        return self.handle_login(username, password, ctx)

    @abstract
    def handle_login(self, username, password, ctx):
        """Performs a login attempt.

        :param ctx:  call context
        :type  ctx:  :class:`versile.orb.entity.VCallContext`

        See :meth:`VPasswordLogin.login` for other arguments and return
        values.

        Method is abstract and must be implemented by derived classes.

        """
        raise NotImplementedError()

    def _invalid_type_handler(self):
        """Called internally if username or password type validation fails.

        Default raises :exc:`versile.orb.entity.VCallError`\ , derived
        classes can override.

        """
        raise VCallError()

    def _v_as_tagged(self, context):
        tags = VSECodes.LOGIN.tags(context)
        return VTagged(self._v_raw_encoder(), *tags)


class VUtilityModule(VModule):
    """Module for :term:`VSE` utility types.

    This module resolves the following classes:

    * :class:`VFunction`\ , :class:`VFunctionProxy`
    * :class:`VUDPRelay`
    * :class:`VPasswordLogin`\ , :class:`VPasswordLoginHandler`

    """
    def __init__(self):
        super(VUtilityModule, self).__init__()

        # Add decoders for conversion from VTagged
        _decoder = VFunctionProxy._v_vse_decoder
        _entry = VSECodes.FUNCTION.mod_decoder(_decoder)
        self.add_decoder(_entry)

        _decoder = VUDPRelay._v_vse_decoder
        _entry = VSECodes.UDPRELAY.mod_decoder(_decoder)
        self.add_decoder(_entry)

        _decoder = VUDPRelayedVOP._v_vse_decoder
        _entry = VSECodes.UDPRELAYEDVOP.mod_decoder(_decoder)
        self.add_decoder(_entry)

        _decoder = VPasswordLogin._v_vse_decoder
        _entry = VSECodes.LOGIN.mod_decoder(_decoder)
        self.add_decoder(_entry)

_vmodule = VUtilityModule()
VModuleResolver._add_vse_import(VSEModuleCodes.UTIL, _vmodule)
