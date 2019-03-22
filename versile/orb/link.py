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

"""Framework for the :term:`VOL` specification for links."""
from __future__ import print_function, unicode_literals

import collections
from threading import Lock
import time
import weakref

from versile.internal import _vexport
from versile.common.iface import abstract, peer
from versile.common.pending import VPending
from versile.common.processor import VProcessor
from versile.common.util import VCondition, VSimpleBus
from versile.common.util import VConfig
from versile.conf import Versile
from versile.orb.const import VMessageCode
from versile.orb.entity import VObject, VReference, VTuple, VBytes, VInteger
from versile.orb.entity import VNone, VBoolean, VString
from versile.orb.entity import VObjectIOContext, VReferenceCall
from versile.orb.entity import VEntity, VProxy, VException, VCallError
from versile.orb.entity import VObjectCall, VCallContext, VSimulatedException
from versile.orb.error import VLinkError
from versile.orb.module import VModuleResolver

__all__ = ['VHandshake', 'VLink', 'VLinkCallContext', 'VLinkConfig',
           'VLinkKeepAlive']
__all__ = _vexport(__all__)


@abstract
class VLink(VObjectIOContext):
    """Implements the :term:`VOL` specification for remote object interaction.

    .. note::

        :class:`VLink` is abstract and should not be directly
        instantiated.  Instead, a derived classes should be
        instantiated which integrates with an I/O sub-system for link
        peer interaction. One such class is
        :class:`versile.reactor.io.link.VLinkAgent`\ .

    :param gateway:       local gateway obj
    :type  gateway:       :class:`versile.orb.entity.VObject`\ ,
                          :class:`versile.orb.entity.VProxy`
    :param processor:     processor for remote calls
    :type  processor:     :class:`versile.common.processor.VProcessor`
    :param init_callback: callback when link handshake is completed
    :type  init_callback: callable
    :param context:       context for remote calls (or None)
    :type  context:       :class:`versile.orb.entity.VCallContext`
    :param auth:          authorizer for link peer credentials (or None)
    :type  auth:          callable
    :param config:        additional configuration (default if None)
    :type  config:        :class:`VLinkConfig`
    :raises:              :exc:`VLinkError`

    .. note::

        Copyleft license information must be globally configured for
        Versile Python on :class:`versile.Versile` before a link can
        be established.

    If *gateway* is None then a :class:`versile.orb.entity.VObject` is
    instantiated and used as a default gateway.

    If *processor* is None then a default processor is constructed and
    started.

    .. warning::

        The mechanism to lazy-construct a processor is a convenient
        convenient mechanism for setting up a link, however it is best
        used for applications which set up only a single link. If a
        program such as a server needs to set up several links, the
        process may run out of threads or there can be other
        performance penalties if each link sets up its own
        processor. For those situations, the program should instead
        set up processor(s) to share between multiple links.

    *init_callback* is called when a link handshake has been
    (successfully) completed. It can be used e.g. to perform a
    callback on the local gateway object, such as setting a reference
    to the negotiated link.

    *auth* is a callable auth(link)->[bool] which returns True if the
    link is authorized to be initiated, otherwise False. If *auth*
    raises an exception, this implies False. When appropriate, the
    function should update authorization data on the link's context
    object such as authorization status and peer's validated
    identity. The function is called internally by the link when peer
    credentials are provided, or when handshake is about to complete -
    whichever comes first. If *auth* is None then the link is allowed
    to be set up, but the link call context object's authorization
    data will not be updated.

    *auth* is only called once and the result of that first
    authorization is cached. If *auth* has not been called earlier, it
    is called during handshake after peer 'hello' message was received
    and before sending a handshake object. This if *auth* does not
    authorize the peer connection, a handshake object is never sent.

    *context* is an object which is passed as the context 'ctx'
    argument to remote method calls which is invoked from the link
    peer.

    See :ref:`lib_link` for general documentation regarding links.

    As per :term:`VOL` protocol specifications, global copyleft
    license information must be set to be used in link handshake. See
    :class:`versile.Versile` for information. If copyleft license
    information has not been globally configured, :exc:`VLinkError` is
    raised.

    .. automethod:: _create_handshake_obj

    """

    DEFAULT_INT_LINK_BUFSIZE = 0x80000
    """Default buffer sizes for internal links."""

    STATUS_HANDSHAKING = 1
    """Status associated with handshaking active link."""

    STATUS_RUNNING = 2
    """Status associated with post-handshake active link."""

    STATUS_CLOSING = 3
    """Status associated with active link."""

    STATUS_CLOSED = 4
    """Status associated with active link."""

    _KAP_DEQUE_LEN = 5
    """Length of recv keep-alive times (must be an odd number)"""

    def __init__(self, gateway=None, processor=None, init_callback=None,
                 context=None, auth=None, conf=None):
        """Initializes the link object."""
        super(VLink, self).__init__()
        if gateway is None:
            gateway = VObject()
        if processor is None:
            if conf.lazy_threads > 0:
                processor = VProcessor(conf.lazy_threads)
                self.__lazy_processor = True
            else:
                raise VLinkError('Must set processor or lazy_threads')
        else:
            self.__lazy_processor = False
        self.__processor = processor
        self._config = conf

        self.__entity_lazy = self._config.lazy_entity
        self.__native_lazy = self._config.lazy_native

        self._local_gw = gateway          # local_gw() replaces with weakref
        self._local_gw_lock = Lock()

        self._peer_gw = None              # peer_gw() replaces with weakref
        self._peer_gw_cond = VCondition() # notify when peer_gw is available
        self._peer_objcall = collections.deque()
        self._peer_hold = self._config.hold_peer

        self._status_cond = VCondition()
        self._status_bus = VSimpleBus()
        self._active = True
        self._protocol_handshake = True
        self._got_peer_hello = False
        self._closing = False

        self._handshake_obj = None
        self._handshake_done = False
        self._handshake_callback = init_callback
        self._force_timeout = self._config.force_timeout
        self._purge_calls = self._config.purge

        self._ongoing_calls = 0
        self._ongoing_calls_lock = Lock()
        self._ref_calls = dict()          # call_id -> wref(call)
        self._ref_calls_lock = Lock()

        self._keep_alive_send = None      # keep_alive send period (msec)
        self._keep_alive_s_t = None       # Last time a message was sent

        self._keep_alive_recv = None      # keep_alive recv period (msec)
        self._keep_alive_expire = None    # keep_alive expiry period (msec)
        self._keep_alive_spam = None      # keep_alive spam limit (msec)
        self._keep_alive_r_t = None       # Last time any msg was received
        self._keep_alive_r_lkap = None    # Time of last keep-alive message
        self._keep_alive_r_times = collections.deque()

        self._peer_copyleft = None        # Set to True/False during h.shake
        self._peer_lic = None         # If peer copyleft, set in h.shake
        self._peer_lic_url = None     # If peer copyleft, set in h.shake

        if context is None:
            factory = self._config.ctx_factory
            if factory:
                context = ctx_factory(self)
            else:
                context = VLinkCallContext(self)
        self.__context = context
        self._parser = self._config.parser
        if not self._parser and self._config.lazy_parser:
            self._parser = VModuleResolver(add_imports=True)

        if auth is None:
            auth = lambda l: True
        self._authorizer = auth
        self._authorized = None

        self._copyleft, self._lic, self._lic_url = Versile.copyleft()
        if self._copyleft is None:
            raise VLinkError('Global copyleft info not set on versile.Versile')

        # self._handlers has a circular reference to self which
        # prevents garbage collection. It must be cleared when the link is
        # shut down so the link object can be garbage collected.
        _MC = VMessageCode
        _h = { _MC.METHOD_CALL             : self._method_call,
               _MC.METHOD_CALL_VOID_RESULT : self._method_call_void_result,
               _MC.METHOD_CALL_NO_RETURN   : self._method_call_no_return,
               _MC.CALL_RESULT             : self._call_result,
               _MC.CALL_EXCEPTION          : self._call_exception,
               _MC.CALL_ERROR              : self._call_error,
               _MC.NOTIFY_DEREF            : self._notify_deref,
               _MC.CONFIRM_DEREF           : self._confirm_deref,
               _MC.KEEP_ALIVE              : self._keep_alive
               }
        self._handlers = _h

        # If init_timout was set, set a timer for non-completed handshake
        if self._config.init_timeout is not None:
            self.set_handshake_timeout(self._config.init_timeout)

    def __del__(self):
        pass

    @abstract
    def set_handshake_timeout(self, timeout):
        """Sets a timeout for completion of a link handshake.

        :param timeout: the timeout in seconds
        :type  timeout: float

        """
        raise NotImplementedError()

    def local_gw(self):
        """Returns the local gateway registered on the link.

        :returns: local link gateway
        :rtype:   :class:`versile.orb.entity.VProxy`
        :raises:  :exc:`versile.orb.error.VLinkError`

        The first time :meth:`local_gw` is called the link replaces
        its internal reference to the gateway with a weak
        reference. This enables garbage collection of the gateway if
        no other local or remote references are held.

        This method should normally only be called by the link
        :class:`VHandshake` object during link handshake, and it
        should be called only once.

        Raises an exception if the gateway is no longer available via
        the weak reference.

        """
        self._local_gw_lock.acquire()
        try:
            if not self._local_gw:
                raise VLinkError('Gateway extraction error')
            gw = self._local_gw
            if isinstance(gw, (VObject, VProxy)):
                self._local_gw = weakref.ref(gw)
            else:
                gw = gw()
        finally:
            self._local_gw_lock.release()
        if not gw:
            raise VLinkError('Gateway extraction error')
        if isinstance(gw, VObject):
            gw = gw._v_proxy()
        return gw

    def peer_gw(self, timeout=None):
        """Returns the peer gateway received from the peer during handshake.

        :param timeout: timeout in seconds
        :type  timeout: float
        :returns:       peer gateway, or None
        :rtype:         :class:`VProxy`
        :raises:        :exc:`versile.orb.error.VLinkError`

        If *timeout* is is >= 0, then the call waits for a peer
        gateway to become available, and returns None if a gateway is
        not available before *timeout* seconds has passed. If
        *timeout* is None or negative then the call blocks until the
        peer gateway is available.

        The first time :meth:`peer_gw` is called the link's internal
        reference to the peer gateway is replaced with a weak
        reference. The code which calls the method is responsible for
        maintaining a reference to the object, otherwise it may be
        garbage collected.

        Raises an exception if gateway is no longer available via the
        weak reference.

        """
        with self._peer_gw_cond:
            gw = self._peer_gw
            if not self._active or self._closing:
                raise VLinkError('Link is inactive or closing')
            if not gw:
                if timeout is not None and timeout > 0.0:
                    start_time = time.time()
                while timeout is None or timeout > 0.0:
                    self._peer_gw_cond.wait(timeout)
                    gw = self._peer_gw
                    if not self._active or self._closing:
                        raise VLinkError('Link is inactive or closing')
                    if gw:
                        break
                    elif timeout is not None and timeout > 0.0:
                        curr_time = time.time()
                        timeout -= curr_time - start_time
                        start_time = curr_time
                else:
                    return None
            if isinstance(gw, (VObject, VProxy)):
                self._peer_gw = weakref.ref(gw)
            else:
                gw = gw()
            if not gw:
                raise VLinkError('Gateway no longer referenced')
            if isinstance(gw, VObject):
                gw = gw._v_proxy()
            return gw

    def async_gw(self):
        """Returns peer gw as an asynchronous call result.

        :returns: asynchronous reference to peer gateway
        :rtype:  :class:`versile.orb.entity.VObjectCall`

        Similar to :meth:`peer_gw` except the return value is an
        asynchronous call result object.

        """
        with self._peer_gw_cond:
            result = VObjectCall()
            gw = self._peer_gw
            if gw:
                if not isinstance(gw, (VObject, VProxy)):
                    gw = gw()
                if gw:
                    if isinstance(gw, VObject):
                        gw = gw._v_proxy()
                    def job():
                        result.push_result(gw)
                else:
                    def job():
                        exception = VLinkError('Gateway no longer referenced')
                        result.push_exception(exception)
                self.processor.queue_call(job)
            else:
                self._peer_objcall.append(result)
            return result

    @abstract
    def shutdown(self, force=False, timeout=None, purge=None):
        """Shuts down the link.

        :param force:   if True then perform a force-shutdown
        :type  force:   bool
        :param timeout: if set, override any force-shutdown timeout set on link
        :type  timeout: float
        :param purge:   if set, override any 'purge' setting on link
        :type  purge:   bool

        Requests a shutdown of the link. If *force* is False then a
        normal shutdown is performed. A normal shutdown implies that
        the link:

        * no longer accepts inbound messages from link peer
        * waits for pending processor tasks to complete
        * waits for all outbound messages to link peer to be sent
        * shuts down when no tasks or output remain

        If *force* is True, then the link is immediately shut down,
        including stopping all communication with link peer and
        cancelling all pending calls registered on the link's
        processor.

        """
        raise NotImplementedError()

    @property
    def processor(self):
        """Holds the link's :class:`versile.common.processor.VProcessor`\ ."""
        return self.__processor

    @property
    def context(self):
        """Holds the link's context object (:class:`VLinkCallContext`\ )."""
        return self.__context

    @abstract
    @property
    def log(self):
        """Holds a :class:`versile.common.log.VLogger` for the link"""
        raise NotImplementedError()

    @property
    def closed(self):
        """True if the link was closed."""
        with self._status_cond:
            return not self._active

    @property
    def status(self):
        """Link status flag associated with current link status (int)."""
        with self._status_cond:
            if self._active:
                if self._closing:
                    return self.STATUS_CLOSING
                elif self._handshake_done:
                    return self.STATUS_RUNNING
                else:
                    return self.STATUS_HANDSHAKING
            else:
                return self.STATUS_CLOSED

    @property
    def handshake_done(self):
        """True if a link handshake is completed (bool)."""
        return self._handshake_done

    @property
    def config(self):
        """The configuration object set on the link."""
        return self._config

    @property
    def status_bus(self):
        """Bus for link status (:class:`versile.common.util.VSimpleBus`\ )"""
        return self._status_bus

    @property
    def peer_is_copyleft(self):
        """True if link peer software grants copyleft (type) rights.

        False if link peer software does not grant such rights. None if
        True/False status has not yet been decided in link handshake.

        """
        return self._peer_copyleft

    @property
    def peer_copyleft_license(self):
        """License type name if peer software grants copyleft (type) rights."""
        return self._peer_lic

    @property
    def peer_copyleft_url(self):
        """Url to software license/download if peer has copyleft license."""
        return self._peer_lic_url

    def register_status_listener(self, listener, push=True):
        """Registers a listener with the status bus.

        :param listener: listener to register
        :type  listener: :class:`versile.common.util.IVSimpleBusListener`
        :param push:     if True push current status to the status bus
        :type  push:     bool
        :returns:        (listener_ID, link_status)
        :rtype:          (int, int)

        Returned link status is the same as output of :attr:`status`\
        . When registering a status listener via this call, the caller
        is guaranteed to know the current status of the link before
        any new states are sent via the status bus.

        If *push* is True then the current status is pushed onto the
        status bus after the listener has been registered, before this
        method returns.

        """
        with self._status_cond:
            _id = self._status_bus.register(listener)
            _status = self.status
            if push:
                self._status_bus.push(_status)
            return (_id, _status)

    def _create_ref_call(self, call_id, checks=None):
        """Create and return a VReference call object.

        :param call_id: the ID of the VReference call
        :type  call_id: int, long
        :returns:       a reference call object
        :rtype:         :class:`versile.orb.entity.VReferenceCall`
        :raises:        :exc:`versile.orb.error.VLinkError`

        """
        self._ref_calls_lock.acquire()
        try:
            if call_id in self._ref_calls:
                raise VLinkError('call id already in use')
            call = VReferenceCall(self, call_id, checks=checks)
            self._ref_calls[call_id] = weakref.ref(call)
        finally:
            self._ref_calls_lock.release()
        return call

    def _remove_ref_call(self, call_id):
        """Remove the VReference call identified by call_id from call list.

        :param call_id: the ID of the VReference call
        :type  call_id: int, long

        """
        self._ref_calls_lock.acquire()
        try:
            self._ref_calls.pop(call_id, None)
        finally:
            self._ref_calls_lock.release()

    @abstract
    def _send_handshake_msg(self, msg):
        """Sends an initial protocol handshake message.

        :param msg: the handshake message
        :type  msg: :class:`versile.orb.entity.VEntity`

        """
        raise NotImplementedError()

    @abstract
    def _send_msg(self, msg_code, payload):
        """Dispatch a message to the link peer.

        :param msg_code: message code (as specified by protocol)
        :type  msg_code: int, long
        :param payload:  message payload (as specified by protocol)
        :type  payload:  :class:`versile.orb.entity.VEntity`
        :returns:        message ID sent to peer
        :raises:         :exc:`versile.orb.error.VLinkError`

        Should hold a lock on message sending while generating a
        message ID and dispatching the associated message, in order to
        prevent protocol violations for messages being sent out of
        order due to concurrent sending.

        If send keep-alive is enabled, must update _keep_alive_s_t
        with a timestamp when sending.

        For internal use by link infrastructure, and should normally
        not be invoked directly by an application.

        """
        raise NotImplementedError()

    @abstract
    def _send_call_msg(self, msg_code, payload, checks=None):
        """Dispatch a call message to the link peer.

        :param msg_code: message code (as specified by protocol)
        :type  msg_code: int, long
        :param payload:  message payload (as specified by protocol)
        :type  payload:  :class:`versile.orb.entity.VEntity`
        :param checks:   call result validation checks (or None)
        :returns:        associated registered reference call
        :raises:         :exc:`versile.orb.error.VLinkError`

        Should hold a lock on message sending while generating a
        message ID, registering the reference call, and dispatching
        the associated message, in order to prevent protocol violations
        for messages being sent out of order due to concurrent sending.

        For internal use by link infrastructure, and should normally
        not be invoked directly by an application.

        """
        raise NotImplementedError()

    def _initiate_handshake(self):
        """Create handshake object and send to peer."""
        self._send_handshake_msg(self._create_hello_msg())

    def _recv_handshake(self, message):
        """Receive a handshake message.

        :param message: message received from link peer
        :type  message: :class:`versile.orb.entity.VEntity`
        :raises:        :exc:`versile.orb.error.VLinkError`

        """
        if not self._got_peer_hello:
            if not isinstance(message, VTuple) or len(message) != 3:
                raise VLinkError('Invalid protocol hello message format')
            protocol, copyleft, version = message
            if not (isinstance(protocol, VBytes)
                    and isinstance(copyleft, VTuple)
                    and isinstance(version, VTuple)):
                raise VLinkError('Invalid hello message')
            for v_component in version:
                if not isinstance(v_component, VInteger):
                    raise VLinkError('Invalid hello message version')
            if protocol != b'VOL_DRAFT':
                raise VLinkError('Invalid protocol name')
            if len(copyleft) != 3:
                raise VLinkError('Invalid copyleft tuple')
            if tuple(version) != (0, 8):
                raise VLinkError('Invalid version number')

            # Validate copyleft handshake information
            _is_copyleft, _license, _url = copyleft
            if not isinstance(_is_copyleft, VBoolean):
                raise VLinkError('Invalid copyleft tuple, no Boolean')
            _is_copyleft = _is_copyleft._v_native();
            if _is_copyleft:
                if not (isinstance(_license, VString) and
                        isinstance(_url, VString)):
                    raise VLinkError('Invalid copyleft tuple, missing VString')
                _license, _url = _license._v_native(), _url._v_native()
                _lurl = _url.lower()
                if not (_lurl.startswith('http://') or
                        _lurl.startswith('https://') or
                        _lurl.startswith('vop://')):
                    raise VLinkError('Invalid copyleft tuple, malformed URL')
            else:
                if not (isinstance(_license, VNone) and
                        isinstance(_url, VNone)):
                    raise VLinkError('Invalid copyleft tuple, missing VNone')
                _license = _url = None
            self._peer_copyleft = _is_copyleft
            self._peer_lic = _license
            self._peer_lic_url = _url

            # Peer hello message was ok
            self._got_peer_hello = True

            # Authorize peer before proceeding
            if not self._authorize():
                self.log.debug('Peer not authorized, shutting down link.')
                self.shutdown(force=True, purge=True)

            # Create and pass handshake object
            self._handshake_obj = self._create_handshake_obj()
            self._send_handshake_msg(self._handshake_obj)
        else:
            if not isinstance(message, VReference):
                raise VLinkError('Invalid peer handshake message')
            peer_handshake_obj = message

            with self._status_cond:
                self._protocol_handshake = False
                self._status_cond.notify_all()

            handshake_obj, self._handshake_obj = self._handshake_obj, None
            handshake_obj._recv_peer(peer_handshake_obj)

    def _create_hello_msg(self):
        """Create hello message for initiating a handshake.

        :returns            : hello message
        :rtype              : :class:`versile.orb.entity.VEntity`

        """
        _copy = VTuple(self._copyleft, self._lic, self._lic_url)
        return VTuple(b'VOL_DRAFT', _copy, VTuple(0, 8))

    def _create_handshake_obj(self):
        """Creates a handshake object for performing link handshake.

        :returns: handshake object for link handshake
        :rtype:   :class:`VHandshake`, :class:`versile.orb.entity.VObject`

        This method is called internally during link handshake. The
        default implementation instantiates a :class:`VHandshake`\
        . Derived classes can override this implementation to return
        another handshake, to perform a non-standard handshake
        protocol.

        """
        return VHandshake(self)

    def _recv_msg(self, msg):
        """Receive and process a VLink protocol level message

        :param msg: the protocol-level message
        :type  msg: :class:`versile.orb.entity.VEntity`
        :raises:    :exc:`versile.orb.error.VLinkError`

        """
        if not self._active:
            # Link is not active, so this method is likely called due to
            # async I/O effects. Perform a shutdown just-in-case.
            self.shutdown()
        if not isinstance(msg, VTuple) or len(msg) != 3:
            raise VLinkError('VLink protocol message must be 3-tuple')
        msg_id, msg_code, msg_data = msg
        if (not (isinstance(msg_id, VInteger))
            or not (isinstance(msg_code, VInteger))):
            raise VLinkError('VLink protocol msg_id and msg_code must be int')
        msg_id = msg_id._v_native()
        msg_code = msg_code._v_native()

        if self._keep_alive_recv:
            self._keep_alive_r_t = time.time()

        handler = self._handlers.get(msg_code, None)
        if handler:
            handler(msg_id, msg_data)
        else:
            if not self._active:
                # Another thread shut down since method started, just return
                return
            else:
                raise VLinkError('Invalid VLink protocol message code')

    def _method_call(self, msg_id, msg_data):
        """Initiates a method call on an object.

        :param msg_id:   message ID (required)
        :type  msg_id:   int, long
        :param msg_data: a tuple of (object, arguments)
        :type  msg_data: :class:`versile.orb.entity.VTuple`

        """
        # msg_data type checked by __method_call
        self.__method_call(msg_id, msg_data, nores=False, noreturn=False)

    def _method_call_void_result(self, msg_id, msg_data):
        """Initiates a void-result method call on an object.

        :param msg_id:   message ID (required)
        :type  msg_id:   int, long
        :param msg_data: a tuple of (object, arguments)
        :type  msg_data: :class:`versile.orb.entity.VTuple`

        """
        # msg_data type checked by __method_call
        self.__method_call(msg_id, msg_data, nores=True, noreturn=False)

    def _method_call_no_return(self, msg_id, msg_data):
        """Initiates a void-result method call on an object.

        :param msg_id:   message ID (required)
        :type  msg_id:   int, long
        :param msg_data: a tuple of (object, arguments)
        :type  msg_data: :class:`versile.orb.entity.VTuple`

        """
        # msg_data type checked by __method_call
        self.__method_call(msg_id, msg_data, nores=True, noreturn=True)

    def _call_result(self, msg_id, msg_data):
        """Processes a result of an earlier method call.

        :param msg_id:   message ID (required)
        :type  msg_id:   int, long
        :param msg_data: a tuple of (call_id, result)
        :type  msg_data: :class:`versile.orb.entity.VTuple`

        """
        if not isinstance(msg_data, VTuple) or len(msg_data) != 2:
            raise VLinkError('Malformed VLink protocol call result message')
        call_id, result  = msg_data
        if not isinstance(call_id, VInteger):
            raise VLinkError('Malformed VLink protocol call result message')
        call_id = call_id._v_native()
        result = self._lazy_native(result)

        self._ref_calls_lock.acquire()
        try:
            w_call = self._ref_calls.get(call_id, None)
        finally:
            self._ref_calls_lock.release()
        if w_call:
            call = w_call()
            if call:
                call.push_result(result)

    def _call_exception(self, msg_id, msg_data):
        """Processes an exception of an earlier method call.

        :param msg_id:   message ID (required)
        :type  msg_id:   int, long
        :param msg_data: a tuple of (call_id, exception)
        :type  msg_data: :class:`versile.orb.entity.`VTuple`

        """
        if not isinstance(msg_data, VTuple) or len(msg_data) != 2:
            raise VLinkError('Malformed VLink protocol call result message')
        call_id, exception  = msg_data
        if not isinstance(call_id, VInteger):
            raise VLinkError('Malformed VLink protocol call result message')
        call_id = call_id._v_native()

        exception = self._lazy_native(exception)
        if not isinstance(exception, Exception):
            exception = VSimulatedException(exception)

        self._ref_calls_lock.acquire()
        try:
            w_call = self._ref_calls.get(call_id, None)
        finally:
            self._ref_calls_lock.release()
        if w_call:
            call = w_call()
            if call:
                call.push_exception(exception)

    def _call_error(self, msg_id, msg_data):
        """Processes an error notification of an earlier method call.

        :param msg_id:   message ID (required)
        :type  msg_id:   int, long
        :param msg_data: a call_id
        :type  msg_data: :class:`versile.orb.entity.`VInteger`

        """
        if not isinstance(msg_data, VInteger):
            raise VLinkError('Malformed VLink protocol call error message')
        call_id = msg_data._v_native()

        self._ref_calls_lock.acquire()
        try:
            w_call = self._ref_calls.get(call_id, None)
        finally:
            self._ref_calls_lock.release()
        if w_call:
            call = w_call()
            if call:
                call.push_exception(VCallError())

    def _notify_deref(self, msg_id, msg_data):
        """Processes a VObject dereference notification message.

        :param msg_id:   message ID (unused)
        :type  msg_id:   int, long
        :param msg_data: a tuple of (peer_id, recv_count)
        :type  msg_data: :class:`versile.orb.entity.`VTuple`

        """
        if not isinstance(msg_data, VTuple) or len(msg_data) != 2:
            raise VLinkError('Malformed VLink protocol deref message')
        peer_id, peer_recv_count = msg_data
        if (not isinstance(peer_id, (int, long, VInteger))
            or not isinstance(peer_recv_count, (int, long, VInteger))):
            raise VLinkError('Malformed VLink protocol deref message')
        peer_id = peer_id._v_native()
        peer_recv_count = peer_recv_count._v_native()

        performed_deref = False
        no_ref_left = False

        self._local_lock.acquire()
        try:
            local = self._local_obj.get(peer_id, None)
            if local:
                obj, send_count = local
                if send_count == peer_recv_count:
                    performed_deref = True
                    self._local_obj.pop(peer_id, None)
                    self._local_p_ids.pop(obj, None)
                    # Shut down link if no references remain
                    if not self._local_obj and not self._peer_obj:
                        no_ref_left = True
        finally:
            self._local_lock.release()

        if performed_deref:
            try:
                self._send_msg(VMessageCode.CONFIRM_DEREF, VInteger(peer_id))
            except VLinkError:
                # Shut down if sending message fails
                self.log.debug('_send_msg failed')
                self.shutdown(force=True, purge=True)
        if no_ref_left:
            self.shutdown()

    def _confirm_deref(self, msg_id, msg_data):
        """Processes a VReference dereference confirmation message.

        :param msg_id:   message ID (unused)
        :type  msg_id:   int, long
        :param msg_data: the peer ID for the object in question
        :type  msg_data: :class:`versile.orb.entity.`VInteger`

        """
        if not isinstance(msg_data, VInteger):
            raise VLinkError('Malformed VLink protocol deref confirm message')
        peer_id = msg_data._v_native()
        self._peer_lock.acquire()
        try:
            self._peer_obj.pop(peer_id, None)
            # Shut down link if no references remain
            _exit = (not self._local_obj and not self._peer_obj)
        finally:
            self._peer_lock.release()
        if _exit:
            self.shutdown()

    def _keep_alive(self, msg_id, msg_data):
        """Processes a keep-alive message.

        :param msg_id:   message ID (unused)
        :type  msg_id:   int, long
        :param msg_data: the peer ID for the object in question
        :type  msg_data: :class:`versile.orb.entity.`VInteger`

        """
        if not (msg_data is None or isinstance(msg_data, VNone)):
            raise VLinkError('Malformed VLink protocol keep-alive message')

        _last_kap = self._keep_alive_r_lkap
        self._keep_alive_r_lkap = time.time()
        if _last_kap is not None:
            _elapsed = int((self._keep_alive_r_lkap-_last_kap)*1000)
            self._keep_alive_r_times.append(_elapsed)
            if len(self._keep_alive_r_times) > self._KAP_DEQUE_LEN:
                self._keep_alive_r_times.popleft()

        if len(self._keep_alive_r_times) == self._KAP_DEQUE_LEN:
            _tmp = sorted(self._keep_alive_r_times)
            _median_elapsed = _tmp[len(_tmp)/2]
            if _median_elapsed < self._keep_alive_spam:
                self.log.debug('keep-alive spam detected, terminating')
                self.shutdown(force=True, purge=True)

    def _ref_deref(self, peer_id):
        """Notifies the link a remote object is no longer referenced

        See :meth:`versile.orb.entity.IVObjectContext._ref_deref`

        Overrides parent class behavior. Triggers a dereference
        message to the link peer. Should normally occur when a
        :class:`versile.orb.entity.`VReference` is garbage collected.

        """
        self._peer_lock.acquire()
        try:
            entry = self._peer_obj.get(peer_id, None)
        finally:
            self._peer_lock.release()

        if entry:
            w_ref, recv_count = entry
            msg_code = VMessageCode.NOTIFY_DEREF
            try:
                self._send_msg(msg_code, VTuple(peer_id, recv_count))
            except VLinkError:
                # Shut down if sending message fails
                self.log.debug('_send_msg failed')
                self.shutdown(force=True, purge=True)

    def _submit_peer_gw(self, gateway):
        """Registers a peer gateway received from handshake.

        This method should provide notification that the peer gateway
        is available.

        If peer_hold was set to False on the link, then the link's
        peer reference will be replaced with a weak reference, without
        waiting for peer_gw() or a callback to retreive a gw reference
        first.

        """
        with self._peer_gw_cond:
            self._peer_gw = gateway
            self._peer_gw_cond.notify_all()
            if self._peer_objcall:
                call_list = list(self._peer_objcall)
                self._peer_objcall.clear()
                # Callback counts as 'extraction', so switch to weakref
                self._peer_gw = weakref.ref(gateway)
                def job():
                    for call in call_list:
                        call.push_result(gateway)
                self.processor.queue_call(job)
            elif not self._peer_hold:
                # Link was configured not to hold a direct reference
                self._peer_gw = weakref.ref(gateway)

    def _finalize_shutdown(self):
        """Finalize shutdown, switching the link to inactive mode."""

        # Change status and signal the change
        with self._status_cond:
            self._active = False
            self._closing = False
            self._status_cond.notify_all()
            self._status_bus.push(self.status)

        # Signal for anyone waiting for a peer gateway
        with self._peer_gw_cond:
            self._peer_gw_cond.notify_all()

        # Clear _handlers ro remove circular refs back to the VLink
        self._handlers.clear()

        # Notify init_callback if set (schedule for processor to handle)
        if self._handshake_callback:
            cback, self._handshake_callback = self._handshake_callback, None
            self.processor.queue_call(cback, args=[None])

        # If link owns a lazy-created processor, then stop the processor
        if self.__lazy_processor:
            self.processor.stop()

    def _handshake_completed(self):
        """Notification to link that protocol handshake was completed."""
        self._handshake_done = True
        if self._handshake_callback:
            cback, self._handshake_callback = self._handshake_callback, None
            try:
                cback(self)
            except Exception as e:
                self.log.debug('Handshake callback error, shutting down link.')
                self.shutdown(force=True, purge=True)
        with self._status_cond:
            self._status_bus.push(self.status)
        self.log.debug('Handshake completed')

        # Initiate keep-alive handling
        if self._keep_alive_send:
            if not self._keep_alive_s_t:
                self._keep_alive_s_t = time.time()
            self._schedule_keep_alive_send(self._keep_alive_send)
        if self._keep_alive_recv:
            if not self._keep_alive_r_t:
                self._keep_alive_r_t = time.time()
            _exp = self._keep_alive_recv*self._config.keep_alive.expire_factor
            self._keep_alive_expire = int(_exp)
            _spam = self._keep_alive_recv*self._config.keep_alive.spam_factor
            self._keep_alive_spam = int(_spam)
            self._schedule_keep_alive_recv(self._keep_alive_expire)

    def _create_ref(self, peer_id):
        """Instantiate a reference for a peer ID on this context.

        :param peer_id:  the remote object's serialized object ID
        :type  peer_id:  int, long
        :returns:        reference
        :rtype:          :class:`VReference`

        Constructs a :class:`VLinkReference`\ .

        """
        return VLinkReference(self, peer_id)

    def _lazy_entity(self, data):
        """Performs lazy-conversion of output as set by link config.

        Only performs lazy-conversion if a peer gateway has been received
        from a peer (which means self._peer_gw is not None), which means
        the peer's side of the handshake has been completed.

        """
        _parser = None
        if self._peer_gw:
            _parser = self._parser
        if self.__entity_lazy:
            return VEntity._v_lazy(data, _parser)
        elif isinstance(data, VEntity):
            return data
        else:
            raise TypeError('Not lazy-converting and data not a VEntity')

    def _lazy_native(self, data):
        """Performs lazy-conversion of input as set by link config.

        Only performs lazy-conversion if a peer gateway has been received
        from a peer (which means self._peer_gw is not None), which means
        the peer's side of the handshake has been completed.

        """
        _parser = None
        if self._peer_gw:
            _parser = self._parser
        if self.__native_lazy:
            return VEntity._v_lazy_native(data, _parser)
        else:
            if _parser:
                return VEntity._v_lazy_parse(data, _parser)
            else:
                return data

    def _authorize(self):
        """Called internally to check whether authorized to set up link."""
        if self._authorized is None:
            try:
                self._authorized = self._authorizer(self)
            except Exception as e:
                self.log.debug('Authorize failed, %s' % e)
                self._authorized = False
        return self._authorized

    @abstract
    def _schedule_keep_alive_send(self, delay):
        """Schedules a keep-alive send check.

        :param delay: delay in milliseconds
        :type  delay: int, long

        """
        raise NotImplementedError()

    def _handle_keep_alive_send(self):
        """Handles a reactor scheduled keep-alive send check."""
        if not self._active or self._closing:
            return

        cur_time = time.time()
        elapsed = int((cur_time-self._keep_alive_s_t)*1000)
        send_delay = self._keep_alive_send - elapsed
        if send_delay <= 0:
            # Send keep-alive message to peer
            try:
                self._send_msg(VMessageCode.KEEP_ALIVE, VNone())
            except VLinkError:
                # Shut down if sending message fails
                self.log.debug('_send_msg failed')
                self.shutdown(force=True, purge=True)
            else:
                # Schedule new send keep-alive handler
                delay = self._keep_alive_send/1000.
                self._schedule_keep_alive_send(delay)
        else:
            self._schedule_keep_alive_send(send_delay)

    @abstract
    def _schedule_keep_alive_recv(self, delay):
        """Schedules a keep-alive recv check.

        :param delay: delay in milliseconds
        :type  delay: int, long

        """
        raise NotImplementedError()

    def _handle_keep_alive_recv(self):
        """Handles a reactor scheduled keep-alive recv check."""
        if not self._active or self._closing:
            return

        cur_time = time.time()
        elapsed = int((cur_time-self._keep_alive_r_t)*1000)
        recv_delay = self._keep_alive_expire - elapsed
        if recv_delay <= 0:
            self.log.debug('keep-alive check expired, terminating link')
            self.shutdown(force=True, purge=True)
        else:
            self._schedule_keep_alive_recv(recv_delay)

    def __method_call(self, msg_id, msg_data, nores, noreturn):
        if not isinstance(msg_data, (tuple, VTuple)) or len(msg_data) != 2:
            raise VLinkError('Malformed VLink protocol method call message')
        obj, args = msg_data
        if not isinstance(obj, VObject) or not isinstance(args, VTuple):
            raise VLinkError('Malformed VLink protocol method call message')
        if isinstance(obj, VReference) and obj._v_context is self:
            raise VLinkError('Cannot call method on peer\'s local object')

        # Lazy-convert msg_data to a native format
        args = self._lazy_native(args)

        processor = obj._v_processor
        if not processor:
            processor = self.processor
        if processor:
            x_args = (msg_id, obj, args, nores, noreturn)
            # Register call on processor with group=self
            processor.queue_call(self.__execute_call, args=x_args, group=self,
                                 start_callback=self.__call_start_cback,
                                 done_callback=self.__call_done_cback)
        else:
            raise VLinkError('No processor registered on object or link')

    def __execute_call(self, call_id, obj, args, nores, noreturn):
        try:
            result = obj._v_call(*args, nores=nores, ctx=self.__context)
        except Exception as e:
            if isinstance(e, VCallError):
                self.log.debug('VCallError %s' % e)
            if not noreturn:
                try:
                    if isinstance(e, VCallError):
                        self.__call_error(call_id)
                    else:
                        if isinstance(e, VSimulatedException):
                            e = e.value
                        self.__call_exception(call_id, e)
                except Exception as e:
                    # Shut down if sending message fails
                    self.log.debug('_send_msg failed')
                    self.shutdown(force=True, purge=True)
        else:
            if isinstance(result, VPending):
                def _callback(_result):
                    if nores:
                        _result = None
                    if not noreturn:
                        self.__call_result(call_id, _result)
                def _failback(_failure):
                    # Duplicates above exception handling
                    e = _failure.value
                    if isinstance(e, VCallError):
                        self.log.debug('VCallError %s' % e)
                    if not noreturn:
                        if isinstance(e, VCallError):
                            self.__call_error(call_id)
                        else:
                            if isinstance(e, VSimulatedException):
                                e = e.value
                            self.__call_exception(call_id, e)
                result.add_callpair(_callback, _failback)
            elif noreturn:
                return
            else:
                if nores:
                    result = None
                try:
                    self.__call_result(call_id, result)
                except:
                    # Shut down if sending message fails
                    self.log.debug('_send_msg failed')
                    self.shutdown(force=True, purge=True)

    def __call_result(self, call_id, result):
        # Lazy-convert result; send a call error if conversion fails
        try:
            result = self._lazy_entity(result)
        except TypeError:
            # Result cannot be passed, raise a generic call error
            self.__call_error(call_id)
            return

        msg_payload = VTuple(call_id, result)
        try:
            self._send_msg(VMessageCode.CALL_RESULT, msg_payload)
        except VLinkError:
            # Shut down if sending message fails
            self.log.debug('_send_msg failed')
            self.shutdown(force=True, purge=True)

    def __call_exception(self, call_id, exception):
        # Lazy-convert exception; send a call error if conversion fails
        try:
            exception = self._lazy_entity(exception)
        except TypeError:
            # Result cannot be passed, raise a generic call error
            self.__call_error(call_id)
            return

        msg_payload = VTuple(call_id, exception)
        try:
            self._send_msg(VMessageCode.CALL_EXCEPTION, msg_payload)
        except VLinkError as e:
            # Shut down if sending message fails
            self.log.debug('_send_msg failed')
            self.shutdown(force=True, purge=True)

    def __call_error(self, call_id):
        msg_payload = VInteger(call_id)
        try:
            self._send_msg(VMessageCode.CALL_ERROR, msg_payload)
        except VLinkError:
            # Shut down if sending message fails
            self.log.debug('_send_msg failed')
            self.shutdown(force=True, purge=True)

    def __call_start_cback(self):
        self._ongoing_calls_lock.acquire()
        try:
            self._ongoing_calls += 1
        finally:
            self._ongoing_calls_lock.release()

    def __call_done_cback(self):
        self._ongoing_calls_lock.acquire()
        try:
            self._ongoing_calls -= 1
            xit = (self._ongoing_calls == 0 and self._active and self._closing)
        finally:
            self._ongoing_calls_lock.release()
        if xit:
            with self.processor:
                if not self.processor.has_group_calls(self):
                    # No ongoing or pending calls - can continue shutdown
                    _cback = self._shutdown_calls_completed
                    self.processor.queue_call(_cback)

    @abstract
    def _shutdown_calls_completed(self):
        """Called when pending shutdown and final call completed."""
        raise NotImplementedError()



class VHandshake(VObject, VCondition):
    """Implements a :class:`VLink` link protocol handshake.

    When a :class:`VLink` performs a handshake with a peer, it first
    exchanges hello messages with the peer to verify the protocol, and
    then it hands over the handling of remaining protocol handshake to
    a :class:`VHandshake` object.

    The link calls :meth:`VLink._create_handshake_obj` internally to
    create a handshake object, which derived classes can overload to
    create a non-standard handshake. The link object calls
    :meth:`_handshake` when handshake object processing should be
    initiated.

    :param link: the link for the handshake
    :type  link: :class:`VLink`

    .. automethod:: _can_finish
    .. automethod:: _handshake
    .. automethod:: _recv_peer

    """

    def __init__(self, link):
        VObject.__init__(self)
        VCondition.__init__(self)
        self._wlink = weakref.ref(link)
        self._peer = None

        self._got_keep_alive = False

        self._allow_finish = False
        self._pending_finish = None
        self._sent_gw = False
        self._got_gw = False

    def __del__(self):
        """Shuts down link if handshake was not completed."""
        if not (self._sent_gw and self._got_gw):
            link = self._wlink()
            if link:
                link.shutdown(force=True, purge=True)

    @peer
    def finish(self):
        """Notification from link peer it is ready to complete the handshake.

        :returns: peer gateway
        :rtype:   :class:`VReference`, :class:`VProxy`

        This method is called externally by the :class:`VLink` peer to
        complete the handshake. It should be called only once.

        """
        with self:
            if self._sent_gw:
                # If finish() called more than once shut down the link
                link = self._wlink()
                if link:
                    link.shutdown(force=True, purge=True)
                raise VException('Handshake already finished')
            if self._allow_finish:
                self._sent_gw = True
                link = self._wlink()
                if self._got_gw:
                    self._peer = None
                    if link:
                        link._handshake_completed()
                if link:
                    local_gw = link.local_gw()
                    if isinstance(local_gw, VProxy):
                        local_gw = local_gw()
                    return local_gw
                else:
                    # This should never happen
                    raise VException('Internal error')
            else:
                self._pending_finish = VPending()
                return self._pending_finish

    @peer
    def keep_alive(self, keep_alive_t):
        """Request from peer this side of link should send keep-alive.

        :param keep_alive_t: requested keep-alive period in milliseconds
        :type  keep_alive_t: int, long
        :returns:            accepted keep-alive period
        :rtype:              int, long

        Accepted keep-alive period is the maximum of the requested
        period and the minimum allowed by this side of the link.

        """
        # Validate method is called only once
        if self._got_keep_alive:
            raise VCallError()
        self._got_keep_alive = True

        # Validate input argument
        if isinstance(keep_alive_t, VInteger):
            keep_alive_t = keep_alive_t._v_native()
        if not isinstance(keep_alive_t, (int, long)) or keep_alive_t <= 0:
            raise VCallError()

        link = self._wlink()
        if not link:
            raise VCallError()
        min_send_t = link._config.keep_alive.min_send
        send_t = max(min_send_t, keep_alive_t)
        link._keep_alive_send = send_t
        return send_t

    def _v_execute(self, *args, **kargs):
        """Enables remote call to :meth:`finish`"""
        with self:
            try:
                if len(args) == 1 and args[0] == 'finish':
                    return self.finish()
                elif len(args) == 2 and args[0] == 'keep_alive':
                    return self.keep_alive(args[1])
                else:
                    raise VCallError()
            except Exception as e:
                # Abort link if handshake triggers errors
                self._abort()
                raise e

    def _recv_peer(self, peer_handshake_obj):
        """Called by the link when peer handshake object is received.

        :param peer_handshake_obj: peer handshake object
        :type  peer_handshake_obj: :class:`versile.orb.entity.VReference`

        """
        with self:
            self._peer = peer_handshake_obj
            link = self._wlink()
            if link:
                link.processor.queue_call(self._handshake)
            else:
                # This should never happen
                raise VException('Internal error')

    def _handshake(self):
        """Start execution of handshake with the link peer.

        This method is executed by the link's processor after a peer
        handshake object is received.

        As the code is executed by a processor, any exceptions or
        error conditions need to be handled by the method. The
        processor may silently drop any raised exceptions.

        """
        link = self._wlink()
        if not link:
            raise VException('Internal error')

        # If defined on link, request keep-alive
        req_t = link._config.keep_alive.req_time
        if req_t is not None:
            granted_t = self._peer._v_call('keep_alive', req_t)
            if isinstance(granted_t, VInteger):
                granted_t = granted_t._v_native()
            if not isinstance(granted_t, (int, long)) or granted_t < req_t:
                raise VException('Invalid negotiated keep-alive from peer')
            link._keep_alive_recv = granted_t

        # Finish handshake
        self._can_finish()
        peer_gw = self._peer._v_call('finish')
        self._got_gw = True

        if (not isinstance(peer_gw, VReference)
            and not (isinstance(peer_gw, VProxy)
                     and isinstance(peer_gw(), VReference))):
            # Peer gw not an appropriate object, shut down the link
            if link:
                link.shutdown(force=True, purge=True)
            return
        if self._sent_gw:
            self._peer = None
            if link:
                link._handshake_completed()
        if link:
            link._submit_peer_gw(peer_gw)
        else:
            # This should never happen
            raise VException('Internal error')

    def _can_finish(self):
        """Called internally when the local side of the handshake can finish.

        This will register status that handshake can finish, and
        should trigger any delayed response to the peer on a
        previously requested call to :meth:`finish`\ .

        """
        with self:
            if self._pending_finish:
                link = self._wlink()
                if link:
                    local_gw = link.local_gw()
                    if isinstance(local_gw, VProxy):
                        local_gw = local_gw()
                    self._pending_finish.callback(local_gw)
                else:
                    # This should never happen
                    raise VException('Internal error')
                self._pending_finish = None
                self._sent_gw = True
                if self._got_gw:
                    self._peer = None
            else:
                self._allow_finish = True

    def _abort(self):
        """Aborts current link."""
        link = self._wlink()
        if link:
            link.shutdown(force=True, purge=True)


class VLinkReference(VReference):
    """Reference to a remote object over a :class:`VLink`\ .

    :param context: the reference's owning context
    :type  context: :class:`VLink`
    :param peer_id: the remote object's serialized object ID
    :type  peer_id: int, long

    .. automethod:: _v_call
    .. autoattribute:: _v_link

    """

    def __init__(self, context, peer_id):
        super(VLinkReference, self).__init__(context, peer_id)

    def _v_call(self, *args, **kargs):
        """Performs a remote call on the object.

        See :meth:`VObject._v_call`\ for general usage and arguments.

        Calling this method triggers a protocol message to the link
        peer to execute a method call on the remote object. The local
        link will only perform related message passing and dispatching
        of a remote call result or exception raised by the remote
        call.

        The *ctx* keyword argument is ignored as execution context is
        set internally on the link side which executes the call.

        """
        nowait = nores = oneway = False
        checks = None
        for key, val in kargs.items():
            if key == 'nowait':
                nowait = bool(val)
            elif key == 'nores':
                nores = bool(val)
            elif key == 'oneway':
                oneway = bool(val)
            elif key == 'ctx':
                pass
            elif key == 'vchk':
                if isinstance(val, (list, tuple)):
                    checks = tuple(val)
                else:
                    checks = (val,)
            else:
                raise TypeError('Invalid keyword argument')

        link = self._v_intctx

        # Lazy-convert arguments
        try:
            args = link._lazy_entity(args)
        except TypeError:
            raise VCallError('Cannot lazy-convert arguments')

        if oneway:
            msg_code = VMessageCode.METHOD_CALL_NO_RETURN
            try:
                link._send_msg(msg_code, VTuple(self, args))
            except:
                raise VCallError('Unable to send remote method call')
            return

        if nores:
            msg_code = VMessageCode.METHOD_CALL_VOID_RESULT
        else:
            msg_code = VMessageCode.METHOD_CALL
        try:
            call = link._send_call_msg(msg_code, VTuple(self, args),
                                       checks=checks)
        except Exception as e:
            raise VCallError('Unable to send remote method call')

        if nowait:
            return call
        else:
            return call.result()

    @property
    def _v_link(self):
        """Holds the reference's link context (:class:`VLink`\ )."""
        return self._v_context

class VLinkCallContext(VCallContext):
    """Call context for a link."""

    def __init__(self, link):
        super(VLinkCallContext, self).__init__()
        self.__link = weakref.ref(link)

    @property
    def link(self):
        """Holds the associated link (None if link dereferenced)."""
        return self.__link()


class VLinkConfig(VConfig):
    """Configuration settings for a :class:`VLink`\ .

    :param hold_peer:     if False drop peer gateway after handshake
    :type  hold_peer:     bool
    :param init_timeout:  timeout for shutdown unless link handshake completed
    :type  init_timeout:  float
    :param force_timeout: seconds from a shutdown to a forced shutdown
    :type  force_timeout: float
    :param purge:         if True purge processor calls after shutdown
    :type  purge:         bool
    :param lazy_threads:  number of workers for a lazy-created processor
    :type  lazy_threads:  int
    :param lazy_entity:   if True lazy-convert output to
                          :class:`versile.orb.entity.VEntity`
    :param lazy_native:   if True lazy-convert input from
                          :class:`versile.orb.entity.VEntity`
    :type  lazy_native:   bool
    :param parser:        parser for decoding VTagged objects
    :type  parser:        :class:`versile.orb.entity.VTaggedParser`
    :param lazy_parser:   if True and no parser set, lazy-create a parser
    :type  lazy_parser:   bool
    :param ctx_factory:   factory for link call context (default if None)
    :type  ctx_factory:   callable
    :param keep_alive:    keep-alive settings for link
    :type  keep_alive:    :class:`VLinkKeepAlive`

    If *hold_peer* to False then peer gateway reference is dropped
    after the handshake. This prevents holding a references to the
    gateway if it is known that it will never be used.

    If *lazy_threads* is positive and *processor* is None then the
    link will create and start its own processor. The link is
    considered to \"own\" the processor, and the link stops the
    processor when the link is shut down.

    If *lazy_native* is True then all received data passed to methods
    is lazy-converted from :class:`versile.orb.entity.VEntity` to a
    native type. This enables writing remote object methods which
    operate directly on the associated internal types.

    *parser* installs a module resolver which will convert recognized
    :class:`versile.orb.entity.VTagged` encoded objects. Arguments to
    remote methods will be sent as their converted representation. A
    parser is not activated for conversion until after the link
    handshake has been completed.

    If *lazy_parser* is True and no parser has been provided, a link
    should lazy-create a module resolver which includes globally
    registered modules.

    If set, *ctx_factory* should be a callable which takes the link as
    input and produces a :class:`versile.orb.link.VLinkCallContext`\
    . The factory is used by a link to create a call context object
    for the link if none has been explicitly defined for link
    construction.

    If set, *keep_alive* are keep-alive settings for negotiating
    keep-alive with the link peer.

    *kargs* is passed on as additional keywords to the parent
    constructor.

    """

    def __init__(self, hold_peer=True, init_timeout=None, force_timeout=None,
                 purge=False, lazy_threads=3, lazy_entity=True,
                 lazy_native=True, parser=None, lazy_parser=True,
                 ctx_factory=None, keep_alive=None, **kargs):
        if keep_alive is None:
            keep_alive = VLinkKeepAlive()
        s_init = super(VLinkConfig, self).__init__
        s_init(hold_peer=hold_peer, init_timeout=init_timeout,
               force_timeout=force_timeout, purge=purge,
               lazy_threads=lazy_threads, lazy_entity=lazy_entity,
               lazy_native=lazy_native, parser=parser, lazy_parser=lazy_parser,
               ctx_factory=ctx_factory, keep_alive=keep_alive, **kargs)


class VLinkKeepAlive(object):
    """Keep-alive settings for a link.

    :param req_time:      keep-alive period to request from peer (ms)
    :type  req_time:      int
    :param expire_factor: recv keep-alive factor for expiring link
    :type  expire_factor: float
    :param spam_factor:   recv keep-alive factor for too frequent keep-alive
    :type  spam_factor:   float
    :param min_send:      minimum allowed send keep-alive period (ms)
    :type  min_send:      int

    Time periods are in milliseconds. If req_time is None then no
    keep-alive is requested from peer.

    *expire_factor* is a factor applied to negotiated time for
    requested keep-alive time, such that if elapsed time since a link
    protocol message was received exceeds the negotiated keep-alive
    time multiplied by this factor, the link is terminated.

    *spam_factor* is applied to negotiated receive keep-alive. If the
    median time between keep-alive packages is less than this factor applied
    to negotiated keep-alive time, the peer is considered to be illegally
    spamming keep-alive packages, and the link should be terminated.

    *min_send* is the minimum allowed period for sending keep-alive
    packages to peer.

    """

    def __init__(self, req_time=None, expire_factor=1.5,
                 spam_factor=0.5, min_send=300000):
        self._req_time = req_time
        self._expire_factor = expire_factor
        self._spam_factor = spam_factor
        self._min_send = min_send

    @property
    def req_time(self):
        """Keep-alive time to request from peer (ms)."""
        return self._req_time

    @property
    def expire_factor(self):
        """Factor applied to negotiated recv keep-alive for link expiry."""
        return self._expire_factor

    @property
    def spam_factor(self):
        """Factor applied to negotiated recv keep-alive for detecting spam."""
        return self._spam_factor

    @property
    def min_send(self):
        """Minimum time between keep-alive packages sent to peer (ms)."""
        return self._min_send
