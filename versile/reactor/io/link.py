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

"""Reactor based implementation of the :mod:`versile.orb.link` framework."""
from __future__ import print_function, unicode_literals

import threading
import time
import weakref

from versile.internal import _vexport, _v_silent
from versile.common.iface import multiface
from versile.common.log import VLogger
from versile.common.util import VLinearIDProvider, VResultException
from versile.crypto import VCrypto
from versile.crypto.auth import VAuth
from versile.crypto.rand import VUrandom
from versile.orb.entity import VInteger, VTuple, VObject, VCallError
from versile.orb.error import VLinkError
from versile.orb.link import VLink, VLinkConfig
from versile.reactor.io import VIOError, VIOControl, VIOMissingControl
from versile.reactor.io import VByteIOPair
from versile.reactor.io.tls import VTLSClient, VTLSServer
from versile.reactor.io.vec import VEntityWAgent, VEntitySerializer
from versile.reactor.io.vec import VEntitySerializerConfig
from versile.reactor.io.vts import VSecureClient, VSecureServer
from versile.reactor.io.vop import VOPClientBridge, VOPServerBridge
from versile.reactor.io.sock import VClientSocketAgent
from versile.reactor.quick import VReactor

__all__ = ['VLinkAgent', 'VLinkAgentConfig']
__all__ = _vexport(__all__)


@multiface
class VLinkAgent(VLink, VEntityWAgent):
    """Implements a :class:`versile.orb.link.VLink` as a reactor agent.

    :param reactor: a (running) reactor for the link
    :param conf:    additional configuration (default if None)
    :type  conf:    :class:`VLinkAgentConfig`

    Other arguments are similar to :class:`versile.orb.link.VLink`\ .

    The link is derived from a
    :class:`versile.reactor.io.vec.VEntityAgent`\ . It should be
    connected to a peer entity agent in order to establish
    communication with a link peer.

    If *reactor* is None and *conf.lazy_reactor* is True then a link
    reactor is lazy-created with a call to :meth:`_create_reactor`. If
    the reactor was lazy-created, then the link takes ownership of the
    reactor and shuts down the reactor when the link is shut down.

    .. warning::

        Similar to :class:`versile.orb.link.VLink` lazy-construction
        of processors, lazy-construction of reactors is primarily a
        convenience method for programs which operate a single
        link. As each reactor consumes a thread, using
        lazy-construction for running multiple links can cause reduced
        performance or exhaust the processor's available threads. When
        running multiple links, the program should create reactor(s)
        to be shared between links.

    .. automethod:: _create_reactor

    """

    def __init__(self, gateway=None, reactor=None, processor=None,
                 init_callback=None, context=None, auth=None, conf=None):
        # This statement must go before VLink.__init__ so overloaded
        # methods can safely assume self.reactor value is set
        if conf is None:
            conf = VLinkAgentConfig()
        if reactor is None:
            if conf.lazy_reactor:
                self.__lazy_reactor = True
                reactor = self._create_reactor()
            else:
                raise VLinkError('reactor or lazy_reactor must be provided')
        else:
            self.__lazy_reactor = False
        VEntityWAgent.__init__(self, reactor)
        VLink.__init__(self, gateway=gateway, processor=processor,
                       init_callback=init_callback, context=context,
                       auth=auth, conf=conf)
        if conf.str_encoding:
            self.str_encoding = conf.str_encoding

        self.__closing_input = self.__closing_output = False
        self._link_got_connect = False

        self._msg_id_provider = VLinearIDProvider()
        self.__send_msg_lock = threading.Lock()

        # Convenience logger interface which sets a prefix
        self.__logger = VLogger(prefix='Link')
        self.__logger.add_watcher(self.reactor.log)

    @classmethod
    def create_pair(cls, gw1=None, gw2=None, init_cback1=None,
                    init_cback2=None, reactor=None, processor=None,
                    internal=False, buf_size=None):
        """Creates and returns two locally connected link objects.

        :param gw1:         local gateway object for link1
        :type  gw1:         :class:`versile.orb.entity.VEntity`
        :param gw2:         local gateway object for link1
        :type  gw2:         :class:`versile.orb.entity.VEntity`
        :param init_cback1: handshake completion callback for link1
        :type  init_cback1: callable
        :param init_cback2: handshake completion callback for link2
        :type  init_cback2: callable
        :param internal:    if True set buffersizes for internal socket
        :type  internal:    bool
        :param buf_size:    if not None, override default buffersizes
        :type  buf_size:    int
        :returns:           two connecting links (link1, link2)
        :rtype:             (:class:`VLinkAgent`\ , :class:`VLinkAgent`\ )

        Remaining arguments are similar to :class:`VLinkAgent`\
        construction.

        If *internal* is True then buffer sizes in the link's
        consumer/producer chain are set to
        :attr:`DEFAULT_INT_LINK_BUFSIZE`\ , otherwise the socket and
        entity channel defaults are used. If *buf_size* is set then it
        is used as buffer size, regardless of the value of *internal*.

        """
        if gw1 is None:
            gw1 = VObject()
        if gw2 is None:
            gw2 = VObject()

        s1, s2 = VClientSocketAgent.create_native_pair()
        links = []
        for s, gw, cback in (s1, gw1, init_cback1), (s2, gw2, init_cback2):
            _link = cls.from_socket(sock=s, gw=gw, init_cback=cback,
                                    reactor=reactor, processor=processor,
                                    internal=internal, buf_size=buf_size)
            links.append(_link)
        links = tuple(links)
        return links

    @classmethod
    def from_socket(cls, sock, gw=None, init_cback=None, reactor=None,
                    processor=None, context=None, auth=None, internal=False,
                    buf_size=None, conf=None):
        """Creates a link node which interacts via a client socket.

        :param sock:     client socket to set up on
        :type  sock:     :class:`socket.socket`
        :param internal: if True set buffersizes for internal socket
        :type  internal: bool
        :param buf_size: if not None, override default buffersizes
        :type  buf_size: int
        :returns:        link
        :rtype:          :class:`VLinkAgent`

        Other arguments are similar to :class:`VLinkAgent`\ .

        *sock* should be an already connected client socket. The link
        is set up as an unencrypted :term:`VEC` serialized :term:`VOL`
        connection.

        If *internal* is True then buffer sizes in the link's
        consumer/producer chain are set to
        :attr:`DEFAULT_INT_LINK_BUFSIZE`\ , otherwise the socket and
        entity channel defaults are used. If *buf_size* is set then it
        is used as buffer size, regardless of the value of *internal*.

        This method is primarily intended for setting up links locally
        between local threads or processes.

        """
        link = cls(gateway=gw, reactor=reactor, processor=processor,
                   init_callback=init_cback, context=context, auth=auth,
                   conf=conf)
        bsize = buf_size
        if internal and bsize is None:
            bsize = cls.DEFAULT_INT_LINK_BUFSIZE
        SCls = VClientSocketAgent
        if bsize is None:
            csock = SCls(reactor=link.reactor, sock=sock, connected=True)
        else:
            csock = SCls(reactor=link.reactor, sock=sock, connected=True,
                         max_read=bsize, max_write=bsize)
        link_io = link.create_byte_agent(internal=internal,
                                            buf_size=buf_size)
        csock.byte_io.attach(link_io)
        return link

    def create_byte_agent(self, internal=False, buf_size=None, conf=None):
        """Creates a byte agent interface to the link.

        :param internal: if True set buffersizes for internal socket
        :type  internal: bool
        :param buf_size: if not None, override default buffersizes
        :type  buf_size: int
        :param conf:    serializer configuration (default if None)
        :type  conf:    :class:`versile.reactor.io.vec.VEntitySerializerConfig`
        :returns:        link byte consumer/producer pair
        :rtype:          :class:`versile.reactor.io.VByteIOPair`
        :raises:         :exc:`versile.orb.error.VLinkError`

        This is a convenience method for creating a byte
        producer/consumer pair for serialized link communication. It
        creates a
        :class:`versile.reactor.io.vec.VEntitySerializer`, attaches
        its entity interface to the link, and returns the serializer's
        byte interfaces.

        .. warning::

            The method should only be called once, and the link cannot
            be connected to other entity producer/consumer interfaces
            when this method is called.

        If *internal* is True then buffer sizes in the link's entity
        channel is set to :attr:`DEFAULT_INT_LINK_BUFSIZE`\ ,
        otherwise the entity channel default is used. If *buf_size* is
        set then it is used as buffer size, regardless of the value of
        *internal*. When *internal* or *buf_size* are set, they
        override buffer sizes set on a *conf* object.

        If a *conf* configuration object is not provided, a default
        configuration is set up with *conf.weakctx* set to True.

        """
        if self.entity_consume.producer or self.entity_produce.consumer:
            raise VLinkError('Consumer or producer already connected')
        if internal and buf_size is None:
            buf_size = self.DEFAULT_INT_LINK_BUFSIZE
        if conf is None:
            conf = VEntitySerializerConfig(weakctx=True)
        SerCls = VEntitySerializer
        if buf_size is not None:
            conf.rbuf_len = buf_size
            conf.max_write = buf_size
        ser = SerCls(reactor=self.reactor, ctx=self, conf=conf)
        ser.entity_io.attach(self.entity_io)
        return ser.byte_io

    def create_vop_client(self, key=None, identity=None, certificates=None,
                          p_auth=None, vts=True, tls=False, insecure=False,
                          crypto=None, internal=False, buf_size=None,
                          vec_conf=None, vts_conf=None):
        """Create a client VOP I/O channel interface to the link.

        :param key:          key for secure VOP
        :type  key:          :class:`versile.crypto.VAsymmetricKey`
        :param identity:     identity (or None)
        :type  identity:     :class:`versile.crypto.x509.cert.VX509Name`
        :param certificates: chain
        :type  certificates: :class:`versile.crypto.x509.cert.VX509Certificate`
                             ,
        :param p_auth:       connection authorizer
        :type  p_auth:       :class:`versile.crypto.auth.VAuth`
        :param vts:          if True allow VTS secure connections
        :type  vts:          bool
        :param tls:          if True allow TLS secure connections
        :type  tls:          bool
        :param insecure:     if True allow insecure connections
        :type  insecure:     bool
        :param crypto:       crypto provider (default if None)
        :type  crypto:       :class:`versile.crypto.VCrypto`
        :param internal:     if True set buffersizes for internal socket
        :type  internal:     bool
        :param buf_size:     if not None, override default buffersizes
        :type  buf_size:     int
        :returns:            byte consumer/producer pair
        :rtype:              :class:`versile.reactor.io.VByteIOPair`

        Creates a byte I/O interface to Versile Object Protocol for
        the role of :term:`VOP` client.

        Creating the byte I/O interface will also connect the
        resulting producer/consumer chain to the link. The link cannot be
        connected to any other I/O chain before or after this call is made.

        """
        f = self.__create_vop_agent
        return f(True, key=key, identity=identity, certificates=certificates,
                 p_auth=p_auth, vts=vts, tls=tls, insecure=insecure,
                 crypto=crypto, internal=internal, buf_size=buf_size,
                 vec_conf=vec_conf, vts_conf=vts_conf)

    def create_vop_server(self, key=None, identity=None, certificates=None,
                          p_auth=None, vts=True, tls=False, insecure=False,
                          crypto=None, internal=False, buf_size=None,
                          vec_conf=None, vts_conf=None):
        """Create a server VOP I/O channel interface to the link.

        See :meth:`create_vop_server`\ . This method is similar,
        except it Creates a byte I/O interface to Versile Object
        Protocol for the role of :term:`VOP` server.

        """
        f = self.__create_vop_agent
        return f(False, key=key, identity=identity, certificates=certificates,
                 p_auth=p_auth, vts=vts, tls=tls, insecure=insecure,
                 crypto=crypto, internal=internal, buf_size=buf_size,
                 vec_conf=vec_conf, vts_conf=vts_conf)

    def shutdown(self, force=False, timeout=None, purge=None):
        if timeout is None:
            timeout = self._force_timeout
        if purge is None:
            purge = self._purge_calls

        with self._status_cond:
            if not self._active:
                return
            elif not self._handshake_done:
                force=True
                purge=True
            was_closing, self._closing = self._closing, True
            if not was_closing:
                self._status_cond.notify_all()
                self._status_bus.push(self.status)
            if not was_closing:
                self.__shutdown_input()
            if not was_closing or force:
                self.__shutdown_output(force, purge)
            if self._active and not force and timeout is not None:
                # Register force-shutdown after <timeout> seconds
                self.reactor.schedule(timeout, self.shutdown, force=True,
                                      purge=purge)

    def set_handshake_timeout(self, timeout):
        """Sets a timeout for completion of a link handshake.

        :param timeout: the timeout in seconds
        :type  timeout: float
        :returns:       reference to the timeout call
        :rtype:         :class:`versile.reactor.VScheduledCall`

        """
        w_link = weakref.ref(self)
        def timeout_check():
            link = w_link()
            if link:
                if link._active and not link._handshake_done:
                    link.shutdown(force=True, purge=True)
        return self.reactor.schedule(timeout, timeout_check)

    @property
    def log(self):
        return self.__logger

    def _create_reactor(self):
        """Creates a default reactor for the link type.

        :returns: reactor

        Creates and starts a reactor before returning. Derived classes
        can override to have other reactors created.

        """
        reactor = VReactor()
        reactor.start()
        return reactor

    def __create_vop_agent(self, is_client, key, identity, certificates,
                           p_auth, vts, tls, insecure, crypto, internal,
                           buf_size, vec_conf, vts_conf):
        if p_auth is None:
            p_auth = VAuth()

        if not key:
            if identity is not None or certificates is not None:
                raise VUrlException('VOP credentials requires a key')
            elif not is_client and (vts or tls):
                raise VUrlException('server mode with VTS/TLS requires key')

        # Set up default crypto
        crypto = VCrypto.lazy(crypto)
        rand = VUrandom()

        bsize = buf_size
        if internal and bsize is None:
            bsize = VLinkAgent.DEFAULT_INT_LINK_BUFSIZE

        # Get VEC byte interface to link
        vec_io = self.create_byte_agent(internal=internal, buf_size=buf_size,
                                        conf=vec_conf)

        # Set up VOP multiplexer
        vts_factory = tls_factory = None
        if (vts):
            def _factory(reactor):
                if is_client:
                    Cls = VSecureClient
                else:
                    Cls = VSecureServer
                _vts = Cls(reactor=reactor, crypto=crypto,
                          rand=rand, keypair=key, identity=identity,
                          certificates=certificates, p_auth=p_auth,
                          conf=vts_conf)
                ext_c = _vts.cipher_consume
                ext_p = _vts.cipher_produce
                int_c = _vts.plain_consume
                int_p = _vts.plain_produce
                return (ext_c, ext_p, int_c, int_p)
            vts_factory = _factory
        if (tls):
            def _factory(reactor):
                if is_client:
                    Cls = VTLSClient
                else:
                    Cls = VTLSServer
                _tls = Cls(reactor=reactor, key=key, identity=identity,
                           certificates=certificates, p_auth=p_auth)
                ext_c = _tls.cipher_consume
                ext_p = _tls.cipher_produce
                int_c = _tls.plain_consume
                int_p = _tls.plain_produce
                return (ext_c, ext_p, int_c, int_p)
            tls_factory = _factory
        if is_client:
            Cls = VOPClientBridge
        else:
            Cls = VOPServerBridge
        vop = Cls(reactor=self.reactor, vec=vec_io, vts=vts_factory,
                  tls=tls_factory, insecure=insecure)

        # Return transport end-points
        return VByteIOPair(vop.external_consume, vop.external_produce)

    def __shutdown_input(self):
        with self._status_cond:
            self.__closing_input = True

            # Abort consumer interface input
            producer = self.entity_consume.producer
            if producer:
                self.reactor.schedule(0.0, producer.abort)

            # Pass exception to all local calls waiting for a result
            self._ref_calls_lock.acquire()
            try:
                calls = self._ref_calls.values()
                self._ref_calls.clear()
            finally:
                self._ref_calls_lock.release()
            for w_call in calls:
                call = w_call()
                if call:
                    try:
                        call.push_exception(VCallError())
                    except VResultException as e:
                        _v_silent(e)

    def __shutdown_output(self, force, purge):
        with self._status_cond:
            self.__closing_output = True

            if not force:
                # If purging, clear all queued processor calls for this link
                if purge:
                    self.processor.remove_group_calls(self)

                # If there are queued or running calls, just return - shutdown
                # will continue as a callback when queue has cleared
                if self.processor.has_group_calls(self):
                    return
                self._ongoing_calls_lock.acquire()
                try:
                    if self._ongoing_calls:
                        return
                finally:
                    self._ongoing_calls_lock.release()

                # No queued or running calls - proceed with closing output
                self.__shutdown_writer(force=False)

            else:
                self.__shutdown_writer(force=True)

    def __shutdown_writer(self, force):
        with self._status_cond:
            if not self._active:
                return
        if not force:
            output_closed = self.end_write(True)
        else:
            self.abort_writer()
            self._finalize_shutdown()

    def _data_ended(self, clean):
        self.reactor.schedule(0.0, self.shutdown, force=False,
                              timeout=self._force_timeout,
                              purge=self._purge_calls)

    def _consumer_aborted(self):
        self.reactor.schedule(0.0, self.shutdown, force=False,
                              timeout=self._force_timeout,
                              purge=self._purge_calls)

    def _producer_aborted(self):
        self.reactor.schedule(0.0, self.shutdown, force=True,
                              timeout=self._force_timeout,
                              purge=self._purge_calls)

    def _consumer_control(self):
        class _Control(VIOControl):
            def __init__(self, link):
                self.__link = link
            def connected(self, peer):
                # Process 'connected' state message (process only once)
                if not self.__link._link_got_connect:
                    self.__link._link_got_connect = True
                    self.__link.log.debug('Connected to %s' % peer)
                    _recv_lim = self.__link._config.vec_recv_lim
                    self.__link._set_receive_limit(_recv_lim)
                    self.__link.context._v_set_network_peer(peer)
                    self.__link._initiate_handshake()
            def authorize(self, key, certs, identity, protocol):
                # Log peer's claimed credentials on the link's call context
                _ctx = self.__link.context
                _ctx._v_set_credentials(key, certs)
                _ctx._v_set_claimed_identity(identity)
                _ctx._v_set_sec_protocol(protocol)
                # Perform link authorization and return result
                return self.__link._authorize()
            def notify_producer_attached(self, producer):
                # Request producer chain 'state'
                def request():
                    try:
                        _cons = self.__link.entity_consume
                        if not _cons.producer:
                            _v_silent(Exception('Notif. w/o producer'))
                            return
                        _cons.producer.control.req_producer_state(_cons)
                    except VIOMissingControl:
                        pass
                self.__link.reactor.schedule(0.0, request)
        return _Control(self)

    def _producer_attached(self):
        # Overriding means recv lim not set here, instead set when 'connected'
        try:
            _cons = self.entity_consume
            _cons.producer.control.req_producer_state(_cons)
        except VIOMissingControl:
            pass

    def _send_handshake_msg(self, msg):
        self.write((msg,))

    def _send_msg(self, msg_code, payload):
        """Sends a VLink protocol-level message to peer

        :param msg_code: message code for the message type
        :type  msg_code: int, long
        :param payload:  message data for this message type
        :type  payload:  :class:`versile.orb.entity.VEntity`
        :returns:        message ID sent to peer
        :raises:         :exc:`versile.orb.error.VLinkError`

        If a message ID is not provided, an ID is generated.

        """
        self.__send_msg_lock.acquire()
        try:
            msg_id = self._msg_id_provider.get_id()
            try:
                send_data = VTuple(VInteger(msg_id), VInteger(msg_code),
                                   payload)
                self.write((send_data,))
            except Exception as e:
                raise VLinkError('Could not send message')
            if self._keep_alive_send:
                self._keep_alive_s_t = time.time()
            return msg_id
        finally:
            self.__send_msg_lock.release()

    def _send_call_msg(self, msg_code, payload, checks=None):
        """Dispatch a message to the link peer.

        :param msg_code: message code (as specified by protocol)
        :type  msg_code: int, long
        :param payload:  message payload (as specified by protocol)
        :type  payload:  :class:`versile.orb.entity.VEntity`
        :param checks:   call result validation checks (or None)
        :returns:        associated registered reference call
        :raises:         :exc:`versile.orb.error.VLinkError`

        Should hold a lock on message sending while generating a
        message ID and dispatching the associated message, in order to
        prevent protocol violations for messages being sent out of
        order due to concurrent sending.

        For internal use by link infrastructure, and should normally
        not be invoked directly by an application.

        """
        self.__send_msg_lock.acquire()
        try:
            msg_id = self._msg_id_provider.get_id()
            call = self._create_ref_call(msg_id, checks=checks)
            try:
                send_data = VTuple(VInteger(msg_id), VInteger(msg_code),
                                   payload)
                self.write((send_data,))
            except Exception as e:
                raise VLinkError('Could not send message')
            return call
        finally:
            self.__send_msg_lock.release()

    def _data_received(self, data):
        if not self._active:
            # Link no longer active - handle silently by performing
            # (another) shutdown of the input
            self.__shutdown_input()
            return
        for obj in data:
            if self._protocol_handshake:
                try:
                    self._recv_handshake(obj)
                except VLinkError as e:
                    raise VIOError('VLink handshake error', e.args)
            else:
                try:
                    self._recv_msg(obj)
                except VLinkError as e:
                    raise VIOError('VLink protocol error', e.args)

    def _finalize_shutdown(self):
        super(VLinkAgent, self)._finalize_shutdown()

        # If reactor was lazy-created, schedule reactor to stop itself
        if self.__lazy_reactor:
            self.log.debug('Lazy-stopping link reactor')
            self.reactor.schedule(0.0, self.reactor.stop)

    def _shutdown_calls_completed(self):
        """Called when pending shutdown and final call completed."""
        # ISSUE - the call to __shutdown_writer could potentially
        # cause a deadlock as it locks status_cond
        self.__shutdown_writer(force=False)

    def _schedule_keep_alive_send(self, delay):
        if self._active and not self._closing:
            self.reactor.schedule(delay/1000., self._handle_keep_alive_send)

    def _schedule_keep_alive_recv(self, delay):
        if self._active and not self._closing:
            self.reactor.schedule(delay/1000., self._handle_keep_alive_recv)


class VLinkAgentConfig(VLinkConfig):
    """Configuration settings for a :class:`VLinkAgent`\ .

    :param lazy_reactor: if True then lazy-create a reactor
    :type  lazy_reactor: bool
    :param str_encoding: I/O context string encoding
    :type  str_encoding: bytes
    :param vec_recv_lim: max entities queued for VLink processing
    :type  vec_recv_lim: int

    Other keyword arguments *kargs* are similar to
    :class:`versile.orb.link.VLinkConfig`\ .

    """

    def __init__(self, lazy_reactor=True, str_encoding=b'utf8',
                 vec_recv_lim=10, **kargs):
        s_init = super(VLinkAgentConfig, self).__init__
        s_init(lazy_reactor=lazy_reactor, str_encoding=str_encoding,
               vec_recv_lim=vec_recv_lim, **kargs)
