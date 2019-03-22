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

"""Reactor based implementation of a :term:`VOP` access point."""
from __future__ import print_function, unicode_literals

import weakref

from versile.internal import _b2s, _s2b, _ssplit, _vexport, _b_ord, _b_chr
from versile.internal import _pyver
from versile.common.iface import implements, abstract, peer
from versile.common.log import VLogger
from versile.common.util import VByteBuffer
from versile.reactor import IVReactorObject
from versile.reactor.io import VByteIOPair
from versile.reactor.io import IVByteConsumer, IVByteProducer
from versile.reactor.io import VIOControl, VIOMissingControl, VIOError

__all__ = ['VOPBridge', 'VOPClientBridge', 'VOPServerBridge']
__all__ = _vexport(__all__)


@abstract
@implements(IVReactorObject)
class VOPBridge(object):
    """A reactor interface for the :term:`VOP` protocol.

    Handles :term:`VOP` handshake and setup of a :term:`VOL` link,
    negotiating a byte transport for the connection.

    .. note::

        The :term:`VOP` specification states that each side of a
        :term:`VOP` connection takes either the role of \"client\" or
        \"server\"\ . The classes :class:`VOPClientBridge` and
        :class:`VOPServerBridge` provide interfaces for the respective
        roles. The :class:`VOPBridge` class is abstract and should not
        be directly instantiated.

    :param reactor:  channel reactor
    :param vec:      :term:`VEC` channel for link
    :type  vec:      :class:`versile.reactor.io.VByteIOPair`
    :param vts:      factory for :term:`VTS` transport (or None)
    :type  vts:      callable
    :param tls:      factory for :term:`TLS` transport (or None)
    :type  tls:      callable
    :param insecure: if True allow unencrypted connections
    :type  insecure: boolean
    :raises:         :exc:`versile.reactor.io.VIOException`

    *vec* should be a byte I/O pair which will be connected to the
    internal (plaintext) side of the protocol's negotiated byte
    transport mechanism.

    The *vts* and *tls* arguments are functions which produce byte
    transports for the corresponding protocols. If not None then that
    transport is enabled for the :term:`VOP` handshake.

    *vts* and *tls* should take a reactor as an argument and return a
    4-tuple (transport_consumer, transport_producer, vec_consumer,
    vec_producer) where each consumer is a
    :class:`versile.reactor.io.VByteConsumer` and each producer is a
    :class:`versile.reactor.io.VByteProducer`\ . The first two
    elements are the external transport connecters and the last two
    elements are the internal connecters for serialized :term:`VEC`
    data.

    """

    def __init__(self, reactor, vec, vts=None, tls=None,
                 insecure=False):
        self.__reactor = reactor

        self._vec_consumer = vec.consumer
        self._vec_producer = vec.producer

        if not (vts or tls or insecure):
            raise VIOException('No transports enabled')

        self._vts_factory = vts
        self._tls_factory = tls
        self._allow_insecure = insecure

        self._handshaking = True
        self._handshake_error = False
        self._handshake_consumed = 0
        self._handshake_produced = 0

        self.__tc_producer = None
        self._tc_cons_lim = 0

        self.__tp_consumer = None
        self._tp_prod_lim = 0

        self.__ec_producer = None
        self._ec_cons_lim = 0

        self.__ep_consumer = None
        self._ep_prod_lim = 0

        self.__tc_iface = self.__tp_iface = None
        self.__ec_iface = self.__ep_iface = None

        # Set up a local logger for convenience
        self._logger = VLogger(prefix='VOP')
        self._logger.add_watcher(self.reactor.log)

    def __del__(self):
        #self._logger.debug('Dereferenced')
        pass

    @property
    def external_consume(self):
        """Holds an external interface to a :term:`VOP` protocol consumer."""
        cons = None
        if self.__ec_iface:
            cons = self.__ec_iface()
        if not cons:
            cons = _VExternalConsumer(self)
            self.__ec_iface = weakref.ref(cons)
        return cons

    @property
    def external_produce(self):
        """Holds an external interface to a :term:`VOP` protocol producer."""
        prod = None
        if self.__ep_iface:
            prod = self.__ep_iface()
        if not prod:
            prod = _VExternalProducer(self)
            self.__ep_iface = weakref.ref(prod)
        return prod

    @property
    def external_io(self):
        """External I/O (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.external_consume, self.external_produce)

    @property
    def reactor(self):
        """The object's reactor.

        See :class:`versile.reactor.IVReactorObject`

        """
        return self.__reactor

    @property
    def _transport_consume(self):
        """Holds an internal interface to the external consumer."""
        cons = None
        if self.__tc_iface:
            cons = self.__tc_iface()
        if not cons:
            cons = _VTransportConsumer(self)
            self.__tc_iface = weakref.ref(cons)
        return cons

    @property
    def _transport_produce(self):
        """Holds an internal interface to the external producer."""
        prod = None
        if self.__tp_iface:
            prod = self.__tp_iface()
        if not prod:
            prod = _VTransportProducer(self)
            self.__tp_iface = weakref.ref(prod)
        return prod

    @property
    def _transport_io(self):
        """Transport I/O (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self._transport_consume, self._transport_produce)

    @peer
    def _tc_consume(self, data, clim):
        if not self._tc_producer:
            raise VIOError('No connected producer')
        elif not data:
            raise VIOError('No data to consume')
        elif self._handshake_error:
            raise VIOError('Error during handshaking')

        if self._handshaking:
            raise VIOError('Handshaking not completed')

        if self._ep_consumer:
            _lim = self._ep_consumer.consume(data, clim)
            self._ep_prod_lim = _lim
            if _lim >= 0:
                _lim = max(_lim-self._handshake_produced, 0)
            self._tc_cons_lim = _lim

        return self._tc_cons_lim

    @peer
    def _tc_end_consume(self, clean):
        if self._handshake_error:
            return

        if self._handshaking:
            self._handshake_abort()
        else:
            if self._ep_consumer:
                return self._ep_consumer.end_consume(clean)
            else:
                self._tc_abort()

    def _tc_abort(self):
        if self._handshaking and not self._handshake_error:
            self._handshake_abort()
        else:
            if self._ep_consumer:
                self._ep_consumer.abort()
                self._ep_detach()
            if self._tc_producer:
                self._tc_producer.abort()
                self._tc_detach()

    def _tc_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._tc_attach, producer, rthread=True)
            return

        if self._handshake_error:
            raise VIOError('Earlier error during handshaking')
        elif self._tc_producer is producer:
            return
        elif self._tc_producer:
            raise VIOError('Producer already connected')

        self.__tc_producer = producer
        self._tc_cons_lim = 0
        producer.attach(self._transport_consume)

        if not self._handshaking:
            _lim = self._ec_cons_lim
            if _lim >= 0:
                _lim -= self._handshake_consumed
            producer.can_produce(_lim)

        try:
            producer.control.notify_consumer_attached(self._transport_consume)
        except VIOMissingControl:
            pass

    def _tc_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._tc_detach, rthread=True)
            return

        if self.__tc_producer:
            prod, self.__tc_producer = self.__tc_producer, None
            self._tc_cons_lim = 0
            prod.detach()

    @peer
    def _tp_can_produce(self, limit):
        if self._handshake_error:
            raise VIOError('Earlier error during handshaking')
        elif not self._tp_consumer:
            raise VIOError('No attached consumer')

        self._tp_prod_lim = limit

        if not self._handshaking and self._ec_producer:
            if limit >= 0:
                limit += self._handshake_consumed
            self._ec_producer.can_produce(limit)

    def _tp_abort(self):
        self._ec_abort()

    def _tp_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._tp_attach, consumer, rthread=True)
            return

        if self._handshake_error:
            raise VIOError('Earlier error during handshaking')
        elif self._tp_consumer is consumer:
            return
        elif self._tp_consumer:
            raise VIOError('Consumer already attached')

        self.__tp_consumer = consumer
        self._tp_prod_lim = 0
        consumer.attach(self._transport_produce)

        try:
            consumer.control.notify_producer_attached(self._transport_produce)
        except VIOMissingControl:
            pass

    def _tp_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._tp_detach, rthread=True)
            return

        if self.__tp_consumer:
            cons, self.__tp_consumer = self.__tp_consumer, None
            cons.detach()
            self._tp_prod_lim = 0

    @peer
    def _ec_consume(self, data, clim):
        if not self._ec_producer:
            raise VIOError('No connected external producer')
        elif not data:
            raise VIOError('No data to consume')
        elif self._handshake_error:
            raise VIOError('Earlier handshake error')

        # Handle handshake
        if self._handshaking:
            _len = len(data)
            self._handshake_consume(data, clim)
            if clim is not None:
                clim -= _len-len(data)

        # Handle post-handshake pass-through to transport
        if (not self._handshaking and self._tp_consumer
            and data and (clim is None or clim > 0)):
            _lim = self._tp_consumer.consume(data, clim)
            if _lim >= 0:
                _lim += self._handshake_consumed
            self._ec_cons_lim = _lim

        return self._ec_cons_lim

    @peer
    def _ec_end_consume(self, clean):
        if self._handshake_error:
            return

        if self._handshaking:
            self._handshake_abort()
        else:
            if self._tp_consumer:
                self._tp_consumer.end_consume(clean)

    def _ec_abort(self):
        if self._handshaking and not self._handshake_error:
            self._handshake_abort()
        else:
            if self._tp_consumer:
                self._tp_consumer.abort()
                self._tp_detach()
            if self._ec_producer:
                self._ec_producer.abort()
                self._ec_detach()

    def _ec_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed from reactor thread
        if not rthread:
            self.reactor.execute(self._ec_attach, producer, rthread=True)
            return

        if self._handshake_error:
            raise VIOError('Earlier error during handshaking')
        elif self._ec_producer is producer:
            return
        elif self._ec_producer:
            raise VIOError('Producer already connected')

        self.__ec_producer = producer
        self._ec_cons_lim = 0
        producer.attach(self.external_consume)

        try:
            producer.control.notify_consumer_attached(self.external_consume)
        except VIOMissingControl:
            pass

        # Trigger any handshake actions
        self._handshake_producer_attached()

    def _ec_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._ec_detach, rthread=True)
            return

        if self.__ec_producer:
            prod, self.__ec_producer = self.__ec_producer, None
            self._ec_cons_lim = 0
            prod.detach()

    @peer
    def _ep_can_produce(self, limit):
        if self._handshake_error:
            raise VIOError('Earlier error during handshaking')
        elif not self._ep_consumer:
            raise VIOError('No attached consumer')

        self._ep_prod_lim = limit

        if self._handshaking:
            self._handshake_can_produce()
        else:
            if self._tc_producer:
                if limit >= 0:
                    limit = max(limit-self._handshake_produced, 0)
                self._tc_cons_lim = limit
                self._tc_producer.can_produce(limit)

    def _ep_abort(self):
        self._tc_abort()

    def _ep_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._ep_attach, consumer, rthread=True)
            return

        if self._handshake_error:
            raise VIOError('Earlier error during handshaking')
        elif self._ep_consumer is consumer:
            return
        elif self._ep_consumer:
            raise VIOError('Consumer already attached')

        self.__ep_consumer = consumer
        self._ep_prod_lim = 0
        consumer.attach(self.external_produce)

        try:
            consumer.control.notify_producer_attached(self.external_produce)
        except VIOMissingControl:
            pass

    def _ep_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._ep_detach, rthread=True)
            return

        if self.__ep_consumer:
            cons, self.__ep_consumer = self.__ep_consumer, None
            cons.detach()
            self._ep_prod_lim = 0

    def _handshake_abort(self):
        if not self._handshake_error:
            self._logger.debug('Aborting')
            self._handshaking = False
            self._handshake_error = True
            self._ec_abort()
            self._ep_abort()

            # Abort VEC chain
            if self._vec_consumer:
                self._vec_consumer.abort()
            if self._vec_producer:
                self._vec_producer.abort()

            # Free up any held resources
            self._vec_consumer = None
            self._vec_producer = None
            self._vts_factory = None
            self._tls_factory = None

    @abstract
    def _handshake_producer_attached(self):
        """Notification handshake producer was attached."""
        raise NotImplementedError()

    @abstract
    def _handshake_consume(self, data, clim):
        """Consume handshake data."""
        raise NotImplementedError()

    @abstract
    def _handshake_can_produce(self):
        """Process can_produce during handshake."""
        raise NotImplementedError()

    def _handshake_complete(self, factory):
        """Finalizes handshake after sending/receiving hello messages."""
        self._handshaking = False

        # Initiate transport communication
        if (factory is None):
            # Plaintext transport
            self._tc_attach(self._vec_producer, True)
            self._tp_attach(self._vec_consumer, True)
        else:
            # Secure transport
            ext_cons, ext_prod, int_cons, int_prod = factory(self.reactor)
            self._tc_attach(ext_prod, True)
            self._tp_attach(ext_cons, True)
            int_cons.attach(self._vec_producer)
            int_prod.attach(self._vec_consumer)

        # Dereference any resouces held for the handshake
        self._vec_consumer = None
        self._vec_producer = None
        self._vts_factory = None
        self._tls_factory = None

        self._logger.debug('Completed handshake')


    @property
    def _tc_control(self):
        if self._ep_consumer:
            return self._ep_consumer.control
        else:
            return VIOControl()

    @property
    def _tc_producer(self):
        return self.__tc_producer

    @property
    def _tc_flows(self):
        return (self.external_produce,)

    @property
    def _tp_control(self):
        if self._ec_producer:
            return self._ec_producer.control
        else:
            return VIOControl()

    @property
    def _tc_twoway(self):
        return True

    @property
    def _tc_reverse(self):
        return self.transport_produce

    @property
    def _tp_consumer(self):
        return self.__tp_consumer

    @property
    def _tp_flows(self):
        return (self.external_consume,)

    @property
    def _tp_twoway(self):
        return True

    @property
    def _tp_reverse(self):
        return self.transport_consume

    @property
    def _ec_control(self):
        if self._tp_consumer:
            return self._tp_consumer.control
        else:
            return VIOControl()

    @property
    def _ec_producer(self):
        return self.__ec_producer

    @property
    def _ec_flows(self):
        return (self.transport_produce,)

    @property
    def _ec_twoway(self):
        return True

    @property
    def _ec_reverse(self):
        return self.external_produce

    @property
    def _ep_control(self):
        if self._tc_producer:
            return self._tc_producer.control
        else:
            return VIOControl()

    @property
    def _ep_consumer(self):
        return self.__ep_consumer

    @property
    def _ep_flows(self):
        return (self.transport_consume,)

    @property
    def _ep_twoway(self):
        return True

    @property
    def _ep_reverse(self):
        return self.external_consume



class VOPClientBridge(VOPBridge):
    """Client-side channel interface for the :term:`VOP` protocol.

    Implements the client side of a :term:`VOP` channel. See
    :class:`VOPBridge` for general information and constructor arguments.

    """

    def __init__(self, *args, **kargs):
        super(VOPClientBridge, self).__init__(*args, **kargs)

        self.__HSHAKE_MAXLEN = 64
        self.__sent_client_hello = False
        self.__have_server_response = False
        self.__buf = VByteBuffer()

        # Set up client hello message based on enabled protocols
        self.__buf.append(b'VOP_DRAFT-0.8 TRANSPORTS')
        if self._vts_factory:
            self.__buf.append(b':VTS')
        if self._tls_factory:
            self.__buf.append(b':TLS')
        if self._allow_insecure:
            self.__buf.append(b':PLAIN')
        self.__buf.append(b'\n')

    def _handshake_producer_attached(self):
        # Start listening only if client hello was sent
        if self.__sent_client_hello:
            self._ec_cons_lim = self.__HSHAKE_MAXLEN
            self._ec_producer.can_produce(self._ec_cons_lim)

    def _handshake_consume(self, data, clim):
        if (not self.__sent_client_hello or not self._handshaking
            or self._handshake_error):
            return

        num_read = 0
        while (data and (clim is None or num_read < clim)
               and len(self.__buf) < self.__HSHAKE_MAXLEN):
            _data = data.pop(1)
            self.__buf.append(_data)
            self._handshake_consumed += 1
            if (_pyver == 2 and _data[0] == b'\n'
                or _pyver == 3 and _data[0] == 0x0a):
                self.__have_server_response = True
                break
        else:
            if len(self.__buf) == self.__HSHAKE_MAXLEN:
                self._handshake_abort()

        if self.__have_server_response:
            # Parse the received hello message
            hello = self.__buf.pop()

            # Parse hello message and complete handshake
            hello = hello[:-1]
            if not hello[:28] == b'VOP_DRAFT-0.8 USE_TRANSPORT:':
                self._handshake_abort()
                return
            proto = hello[28:]
            if proto == b'VTS':
                if self._vts_factory:
                    self._logger.debug('Negotiated VTS transport')
                    self._handshake_complete(self._vts_factory)
                else:
                    self._handshake_abort()
            elif proto == b'TLS':
                if self._tls_factory:
                    self._logger.debug('Negotiated TLS transport')
                    self._handshake_complete(self._tls_factory)
                else:
                    self._handshake_abort()
            elif proto == b'PLAIN':
                if self._allow_insecure:
                    self._logger.debug('Negotiated insecure (plaintext) '
                                       + 'transport')
                    self._handshake_complete(None)
                else:
                    self._handshake_abort()
            else:
                self._handshake_abort()

    def _handshake_can_produce(self):
        if (not self._handshaking or self._handshake_error
            or self.__sent_client_hello):
            return

        # Send handshake message
        if (self._ep_consumer and (self._ep_prod_lim < 0
            or self._ep_prod_lim > self._handshake_produced)):
            old_len = len(self.__buf)
            self._ep_prod_lim = self._ep_consumer.consume(self.__buf)
            self._handshake_produced += old_len - len(self.__buf)
            if not self.__buf:
                self.__sent_client_hello = True

        if self.__sent_client_hello and self._ec_producer:
            self._ec_cons_lim = self.__HSHAKE_MAXLEN
            self._ec_producer.can_produce(self._ec_cons_lim)


class VOPServerBridge(VOPBridge):
    """Server-side channel interface for the :term:`VOP` protocol.

    Implements the server side of a :term:`VOP` channel. See
    :class:`VOPBridge` for general information and constructor arguments.

    """

    def __init__(self, *args, **kargs):
        super(VOPServerBridge, self).__init__(*args, **kargs)

        self.__HSHAKE_MAXLEN = 64
        self.__have_client_hello = False
        self.__buf = VByteBuffer()
        self.__negotiated_factory = None

    def _handshake_producer_attached(self):
        # Start listening for handshake message from client
        self._ec_cons_lim = self.__HSHAKE_MAXLEN
        self._ec_producer.can_produce(self._ec_cons_lim)

    def _handshake_consume(self, data, clim):
        if (self.__have_client_hello or not self._handshaking
            or self._handshake_error):
            return

        num_read = 0
        while (data and (clim is None or num_read < clim)
               and len(self.__buf) < self.__HSHAKE_MAXLEN):
            _data = data.pop(1)
            self.__buf.append(_data)
            self._handshake_consumed += 1
            if (_pyver == 2 and _data[0] == b'\n'
                or _pyver == 3 and _data[0] == 0x0a):
                self.__have_client_hello = True
                break
        else:
            if len(self.__buf) == self.__HSHAKE_MAXLEN:
                self._handshake_abort()

        if self.__have_client_hello:
            # Parse the received hello message
            hello = self.__buf.pop()
            hello = hello[:-1]


            if not hello[:25] == b'VOP_DRAFT-0.8 TRANSPORTS:':
                self._handshake_abort()
                return
            _protos = hello[25:].split(b':')
            protos = set()
            for p in _protos:
                if p == b'VTS' or p == b'TLS' or p == b'PLAIN':
                    if p not in protos:
                        protos.add(p)
                        continue
                self._handshake_abort()
                return

            if b'VTS' in protos and self._vts_factory:
                proto = b'VTS'
                self.__negotiated_factory = self._vts_factory
                self._logger.debug('Negotiated VTS transport')
            elif b'TLS' in protos and self._tls_factory:
                proto = b'TLS'
                self.__negotiated_factory = self._tls_factory
                self._logger.debug('Negotiated TLS transport')
            elif b'PLAIN' in protos and self._allow_insecure:
                proto = b'PLAIN'
                self.__negotiated_factory = None
                self._logger.debug('Negotiated insecure (plaintext) transport')
            else:
                self._handshake_abort()
                return

            # Prepare protocol return message
            self.__buf.append(b'VOP_DRAFT-0.8 USE_TRANSPORT:')
            self.__buf.append(proto)
            self.__buf.append(b'\n')

            # Initiate production
            if self._ep_prod_lim != 0:
                self.reactor.schedule(0, self._handshake_can_produce)

    def _handshake_can_produce(self):
        if (not self._handshaking or self._handshake_error
            or not self.__have_client_hello):
            return

        # Send handshake message
        if (self._ep_consumer and (self._ep_prod_lim < 0
            or self._ep_prod_lim > self._handshake_produced)):
            old_len = len(self.__buf)
            self._ep_prod_lim = self._ep_consumer.consume(self.__buf)
            self._handshake_produced += old_len - len(self.__buf)
            if not self.__buf:
                self._handshake_complete(self.__negotiated_factory)


@implements(IVByteConsumer)
class _VTransportConsumer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def consume(self, data, clim=None):
        return self.__proxy._tc_consume(data, clim)

    @peer
    def end_consume(self, clean):
        return self.__proxy._tc_end_consume(clean)

    def abort(self):
        return self.__proxy._tc_abort()

    def attach(self, producer):
        return self.__proxy._tc_attach(producer)

    def detach(self):
        return self.__proxy._tc_detach()

    @property
    def control(self):
        return self.__proxy._tc_control

    @property
    def producer(self):
        return self.__proxy._tc_producer

    @property
    def flows(self):
        return self.__proxy._tc_flows

    @property
    def twoway(self):
        return self.__proxy._tc_twoway

    @property
    def reverse(self):
        return self.__proxy._tc_reverse


@implements(IVByteProducer)
class _VTransportProducer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def can_produce(self, limit):
        return self.__proxy._tp_can_produce(limit)

    def abort(self):
        return self.__proxy._tp_abort()

    def attach(self, consumer):
        return self.__proxy._tp_attach(consumer)

    def detach(self):
        return self.__proxy._tp_detach()

    @property
    def control(self):
        return self.__proxy._tp_control

    @property
    def consumer(self):
        return self.__proxy._tp_consumer

    @property
    def flows(self):
        return self.__proxy._tp_flows

    @property
    def twoway(self):
        return self.__proxy._tp_twoway

    @property
    def reverse(self):
        return self.__proxy._tp_reverse


@implements(IVByteConsumer)
class _VExternalConsumer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def consume(self, data, clim=None):
        return self.__proxy._ec_consume(data, clim)

    @peer
    def end_consume(self, clean):
        return self.__proxy._ec_end_consume(clean)

    def abort(self):
        return self.__proxy._ec_abort()

    def attach(self, producer):
        return self.__proxy._ec_attach(producer)

    def detach(self):
        return self.__proxy._ec_detach()

    @property
    def control(self):
        return self.__proxy._ec_control

    @property
    def producer(self):
        return self.__proxy._ec_producer

    @property
    def flows(self):
        return self.__proxy._ec_flows

    @property
    def twoway(self):
        return self.__proxy._ec_twoway

    @property
    def reverse(self):
        return self.__proxy._ec_reverse


@implements(IVByteProducer)
class _VExternalProducer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def can_produce(self, limit):
        return self.__proxy._ep_can_produce(limit)

    def abort(self):
        return self.__proxy._ep_abort()

    def attach(self, consumer):
        return self.__proxy._ep_attach(consumer)

    def detach(self):
        return self.__proxy._ep_detach()

    @property
    def control(self):
        return self.__proxy._ep_control

    @property
    def consumer(self):
        return self.__proxy._ep_consumer

    @property
    def flows(self):
        return self.__proxy._ep_flows

    @property
    def twoway(self):
        return self.__proxy._ep_twoway

    @property
    def reverse(self):
        return self.__proxy._ep_reverse
