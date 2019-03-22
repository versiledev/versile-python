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

"""Reactor-based implementation of the :term:`VEC` specification."""
from __future__ import print_function, unicode_literals

import collections
from threading import Lock
import weakref

from versile.internal import _b2s, _s2b, _bfmt, _ssplit, _vexport, _pyver
from versile.internal import _b_ord, _b_chr
from versile.common.iface import implements, abstract, final, peer, multiface
from versile.common.iface import VInterface
from versile.common.log import VLogger
from versile.common.util import VByteBuffer, VConfig
from versile.orb.entity import VEntity, VString, VEntityReaderError
from versile.reactor import IVReactorObject
from versile.reactor.io import VByteIOPair
from versile.reactor.io import IVConsumer, IVByteConsumer
from versile.reactor.io import IVProducer, IVByteProducer
from versile.reactor.io import VIOControl, VIOClosed, VIOError
from versile.reactor.io import VIOMissingControl

__all__ = ['IVEntityConsumer', 'IVEntityProducer', 'IVEntityWriter',
           'VEntityAgent', 'VEntityConsumer', 'VEntityProducer',
           'VEntitySerializer', 'VEntitySerializerConfig', 'VEntityWAgent',
           'VEntityWriter', 'VEntityIOPair']
__all__ = _vexport(__all__)


class IVEntityConsumer(IVConsumer):
    """Interface for a consumer of VEntity objects."""

    @peer
    def consume(self, product):
        """Consumes entity data from a connected producer.

        :param product: the data to consume
        :type  product: list of :class:`versile.orb.entity.VEntity`
        :returns:       new (cumulative) production limit
        :rtype:         int
        :raises:        :exc:`versile.reactor.io.VIOError`

        See :class:`versile.reactor.io.IVConsumer`

        """

    def attach_producer(self, producer):
        """Attach a producer.

        :param producer: producer to attach (or None)
        :type  producer: :class:`IVEntityProducer`
        :raises:         :exc:`versile.reactor.io.VIOError`

        See :meth:`versile.reactor.io.IVConsumer.attach_producer`

        """


class IVEntityProducer(IVProducer):
    """Interface for a producer of VEntity objects."""

    @peer
    def can_produce(self, limit):
        """Informs the producer it can deliver data to its consumer.

        :param limit: limit for cumulative number of produced entities
        :type  limit: int

        See :meth:`versile.reactor.io.IVProducer.can_produce`\ .

        *limit* is the cumulative number of objects transferred since
        the producer/consumer were connected. If *limit* is None or a
        negative number, this implies the consumer can receive
        unlimited objects.

        """

    def attach_consumer(self, consumer):
        """Attach a consumer.

        :param consumer: consumer to attach (or None)
        :type  consumer: :class:`IVEntityConsumer`
        :raises:         :exc:`versile.reactor.io.VIOError`

        See :meth:`versile.reactor.io.IVProducer.attach_producer`

        """


class IVEntityWriter(VInterface):
    """Interface for a generic writer for VEntity data."""

    def write(self, entities):
        """Write data to the writer's output.

        :param entity: tuple of :class:`versile.orb.entity.VEntity` data
        :type  entity: tuple
        :raises:       :exc:`versile.reactor.io.VIOClosed`,
                       :exc:`versile.reactor.io.VIOError`

        Buffers output data for writing. Data does not actually get
        written until it can be passed to a consumer.

        """

    def end_write(self, clean):
        """Closes writer output when write buffer becomes empty.

        :param clean: if True the output was closed cleanly
        :type  clean: bool

        Sends an end-of-data event to connected consumer once write
        buffer is empty.

        """

    def abort_writer(self):
        """Abort writer output and clear write output buffer.

        Calls :meth:`versile.reactor.io.IVProducer.abort` on the
        writer's parent producer.

        """


@implements(IVReactorObject)
class VEntitySerializer(object):
    """A producer/consumer bridge for serialized VEntity data.

    The bridge connects a consumer/producer interface for
    :class:`versile.orb.entity.VEntity` I/O with an interface for byte
    I/O. Enties are serialized to or decoded from byte data on the
    byte I/O interface. The byte I/O interface is available from the
    :attr:`byteio` property. The entity I/O interface is available as
    :attr:`entityio`\ .

    :param reactor:   reactor driving the socket's event handling
    :param ctx:       I/O context for entity serialization
    :type  ctx:       :class:`versile.orb.entity.VIOContext`
    :param conf:      additional configuration
    :type  conf:      :class:`VEntitySerializerConfig`

    .. note::

        In order to serialize referenced objects, the context in *ctx*
        must be a :class:`versile.orb.entity.VObjectIOContext`\ .

    """

    def __init__(self, reactor, ctx, conf=None):
        self.__reactor = reactor
        if conf is None:
            conf = VEntitySerializerConfig()
        self.__config = conf
        if not self.__config.weakctx:
            self.__ctx = ctx
        else:
            self.__ctx = weakref.ref(ctx)

        self.__handshaking = conf.handshake
        if self.__handshaking:
            self.__HANDSHAKE_MAXLEN = 32
            self.__handshake_data = []
            self.__handshake_len = 0
            if ctx.str_encoding:
                _hbytes = b''.join((b'VEC_DRAFT-0.8-', ctx.str_encoding,
                                    b'\n'))
                self.__handshake_send = VByteBuffer(_hbytes)
            else:
                self.__handshake_send = VByteBuffer(b'VEC_DRAFT-0.8\n')
        else:
            self.__handshake_send = None

        self._msg_max = conf.msg_max

        self.__bc_consumed = 0
        self.__bc_consume_lim = 0
        self.__bc_producer = None
        self.__bc_eod = False
        self.__bc_eod_clean = None
        self.__bc_rbuf = VByteBuffer()
        self.__bc_rbuf_len = conf.rbuf_len
        self.__bc_reader = None
        self.__bc_aborted = False

        self.__bp_produced = 0
        self.__bp_produce_lim = 0
        self.__bp_consumer = None
        self.__bp_wbuf = VByteBuffer()
        self.__bp_max_write = conf.max_write
        self.__bp_writer = None
        self.__bp_sent_eod = False

        self.__ec_consumed = 0
        self.__ec_consume_lim = 0
        self.__ec_producer = None
        self.__ec_eod = False
        self.__ec_eod_clean = None
        self.__ec_queue = collections.deque()
        self.__ec_buf_len = conf.ebuf_len
        self.__ec_aborted = False

        self.__ep_produced = 0
        self.__ep_produce_lim = 0
        self.__ep_consumer = None
        self.__ep_queue = collections.deque()
        self.__ep_sent_eod = False

        self.__bc_iface = self.__bp_iface = None
        self.__ec_iface = self.__ep_iface = None

        # Set up a local logger for convenience
        self.__logger = VLogger(prefix='VEC')
        self.__logger.add_watcher(self.reactor.log)

    def __del__(self):
        #self.__logger.debug('Dereferenced')
        pass

    @property
    def byte_consume(self):
        """Holds the Byte Consumer interface to the serializer."""
        cons = None
        if self.__bc_iface:
            cons = self.__bc_iface()
        if not cons:
            cons = _VByteConsumer(self)
            self.__bc_iface = weakref.ref(cons)
        return cons

    @property
    def byte_produce(self):
        """Holds the Byte Producer interface to the serializer."""
        prod = None
        if self.__bp_iface:
            prod = self.__bp_iface()
        if not prod:
            prod = _VByteProducer(self)
            self.__bp_iface = weakref.ref(prod)
        return prod

    @property
    def byte_io(self):
        """Byte interface (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.byte_consume, self.byte_produce)

    @property
    def entity_consume(self):
        """Holds the Entity Consumer interface to the serializer."""
        cons = None
        if self.__ec_iface:
            cons = self.__ec_iface()
        if not cons:
            cons = _VEntityConsumer(self)
            self.__ec_iface = weakref.ref(cons)
        return cons

    @property
    def entity_produce(self):
        """Holds the Entity Producer interface to the serializer."""
        prod = None
        if self.__ep_iface:
            prod = self.__ep_iface()
        if not prod:
            prod = _VEntityProducer(self)
            self.__ep_iface = weakref.ref(prod)
        return prod

    @property
    def entity_io(self):
        """VEntity interface (:class:`versile.reactor.io.VEntityIOPair`\ )."""
        return VEntityIOPair(self.entity_consume, self.entity_produce)

    @property
    def reactor(self):
        """Holds the object's reactor."""
        return self.__reactor

    @property
    def config(self):
        """The configuration object set on the entity serializer."""
        return self.__config

    @peer
    def _bc_consume(self, data, clim):
        if self.__bc_eod:
            raise VIOError('Consumer already received end-of-data')
        elif not self._bc_producer:
            raise VIOError('No connected producer')
        elif not data:
            raise VIOError('No data to consume')
        max_cons = self.__lim(self.__bc_consumed, self.__bc_consume_lim)
        if max_cons == 0:
            raise VIOError('Consume limit exceeded')
        if clim is not None and clim > 0:
            max_cons = min(max_cons, clim)

        buf_len = len(self.__bc_rbuf)
        self.__bc_rbuf.append_list(data.pop_list(max_cons))
        self.__bc_consumed += len(self.__bc_rbuf) - buf_len

        if self.__handshaking:
            self.__handshake()

        if not self.__handshaking:
            while self.__bc_rbuf:
                if not self.__bc_reader:
                    context = self.__ctx_ref
                    self.__bc_reader = VEntity._v_reader(context=context)
                try:
                    num_bytes = self.__bc_reader.read(self.__bc_rbuf)
                except VEntityReaderError:
                    raise VIOError('VEntity reader error - malformed data')
                else:
                    if (self._msg_max is not None
                        and 0 <= self._msg_max < self.__bc_reader.num_read):
                        raise VIOError('Byte consumer message limit exceeded')
                    if self.__bc_reader.done():
                        self.__ep_queue.append(self.__bc_reader.result())
                        self.__bc_reader = None
            self.__ep_produce()

        # Update and return consume limit
        max_add = self.__lim(len(self.__bc_rbuf), self.__bc_rbuf_len)
        if max_add >= 0:
            self.__bc_consume_lim = self.__bc_consumed + max_add
        else:
            self.__bc_consume_lim = -1
        return self.__bc_consume_lim

    @peer
    def _bc_end_consume(self, clean):
        if self.__bc_eod:
            return
        self.__bc_eod = True
        self.__bc_eod_clean = clean

        if self.__ep_consumer:
            if self.__bc_reader:
                self.__bc_eod_clean = False
                self.__bc_reader = None
            self.__ep_produce()
        else:
            self.__bc_abort()

    def _bc_abort(self):
        if not self.__bc_aborted:
            self.__bc_aborted = True
            self.__bc_eod = True
            self.__bc_rbuf.clear()
            self.__ep_queue.clear()
            if self.__ep_consumer:
                self.__ep_consumer.abort()
                self._ep_detach()
            if self.__bc_producer:
                self.__bc_producer.abort()
                self._bc_detach()

    def _bc_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._bc_attach, producer, rthread=True)
            return

        if self.__bc_producer is producer:
            return
        if self.__bc_eod:
            raise VIOError('Consumer already received end-of-data')
        elif self.__bc_producer:
            raise VIOError('Producer already connected')
        self.__bc_producer = producer
        self.__bc_consumed = 0
        self.__bc_consume_lim = self.__lim(len(self.__bc_rbuf),
                                           self.__bc_rbuf_len)
        producer.attach(self.byte_consume)
        producer.can_produce(self.__bc_consume_lim)

        # Notify attached chain
        try:
            producer.control.notify_consumer_attached(self.byte_consume)
        except VIOMissingControl:
            pass

    def _bc_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._bc_detach, rthread=True)
            return

        if self.__bc_producer:
            prod, self.__bc_producer = self.__bc_producer, None
            self.__bc_consumed = self.__bc_consume_lim = 0
            prod.detach()

    @peer
    def _bp_can_produce(self, limit):
        if not self.__bp_consumer:
            raise VIOError('No attached consumer')
        if limit is None or limit < 0:
            if (not self.__bp_produce_lim is None
                and not self.__bp_produce_lim < 0):
                self.__bp_produce_lim = limit
                self.reactor.schedule(0.0, self.__bp_do_produce)
        else:
            if (self.__bp_produce_lim is not None
                and 0 <= self.__bp_produce_lim < limit):
                self.__bp_produce_lim = limit
                self.reactor.schedule(0.0, self.__bp_do_produce)

    def _bp_abort(self):
        self._ec_abort()

    def _bp_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._bp_attach, consumer, rthread=True)
            return

        if self.__bp_consumer is consumer:
            return
        if self.__bp_consumer:
            raise VIOError('Consumer already attached')
        elif self.__bp_eod:
            raise VIOError('Producer already reached end-of-data')
        self.__bp_consumer = consumer
        self.__bp_produced = self.__bp_produce_lim = 0
        consumer.attach(self.byte_produce)

        if self.__ec_producer:
            self.__ec_consume_lim = self.__lim(len(self.__ec_queue),
                                               self.__ec_buf_len)
            self.__ec_producer.can_produce(self.__ec_consume_lim)

        # Notify attached chain
        try:
            consumer.control.notify_producer_attached(self.byte_produce)
        except VIOMissingControl:
            pass

    def _bp_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._bp_detach, rthread=True)
            return

        if self.__bp_consumer:
            cons, self.__bp_consumer = self.__bp_consumer, None
            cons.detach()
            self.__bp_produced = self.__bp_produce_lim = 0

    @peer
    def _ec_consume(self, product):
        if self.__ec_eod:
            raise VIOError('Consumer already received end-of-data')
        elif not self._ec_producer:
            raise VIOError('No connected producer')
        elif not product:
            raise VIOError('No data to consume')

        max_cons = self.__lim(self.__ec_consumed, self.__ec_consume_lim)
        if max_cons == 0 or 0 < max_cons < len(product):
            raise VIOError('Consume limit exceeded')
        self.__ec_queue.extend(product)
        self.__ec_consumed += len(product)

        self.__bp_do_produce()

        # Update and return consume limit
        max_add = self.__lim(len(self.__ec_queue), self.__ec_buf_len)
        if max_add >= 0:
            self.__ec_consume_lim = self.__ec_consumed + max_add
        else:
            self.__ec_consume_lim = -1
        return self.__ec_consume_lim

    @peer
    def _ec_end_consume(self, clean):
        if self.__ec_eod:
            return
        self.__ec_eod = True
        self.__ec_eod_clean = clean
        if not self.__bp_consumer:
            self._ec_abort()
            return
        self.__bp_do_produce()

    def _ec_abort(self):
        if not self.__ec_aborted:
            self.__ec_aborted = True
            self.__ec_eod = True
            self.__bp_wbuf.remove()
            self.__ec_queue.clear()
            if self.__bp_consumer:
                self.__bp_consumer.abort()
                self._bp_detach()
            if self.__ec_producer:
                self.__ec_producer.abort()
                self._ec_detach()

    def _ec_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._ec_attach, producer, rthread=True)
            return

        if self.__ec_producer is producer:
            return
        if self.__ec_eod:
            raise VIOError('Consumer already received end-of-data')
        elif self.__ec_producer:
            raise VIOError('Producer already connected')
        self.__ec_producer = producer
        self.__ec_consumed = 0
        self.__ec_consume_lim = self.__lim(len(self.__ec_queue),
                                           self.__ec_buf_len)
        producer.attach(self.entity_consume)
        producer.can_produce(self.__ec_consume_lim)

        # Notify attached chain
        try:
            producer.control.notify_consumer_attached(self.entity_consume)
        except VIOMissingControl:
            pass

    def _ec_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._ec_detach, rthread=True)
            return

        if self.__ec_producer:
            prod, self.__ec_producer = self.__ec_producer, None
            self.__ec_consumed = self.__ec_consume_lim = 0
            prod.detach()

    @peer
    def _ep_can_produce(self, limit):
        if not self.__ep_consumer:
            raise VIOError('No attached consumer')
        if limit is None or limit < 0:
            if (not self.__ep_produce_lim is None
                and not self.__ep_produce_lim < 0):
                self.__ep_produce_lim = limit
                self.reactor.schedule(0.0, self.__ep_produce)
        else:
            if (self.__ep_produce_lim is not None
                and 0 <= self.__ep_produce_lim < limit):
                self.__ep_produce_lim = limit
                self.reactor.schedule(0.0, self.__ep_produce)

    def _ep_abort(self):
        self._bc_abort()

    def _ep_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._ep_attach, consumer, rthread=True)
            return

        if self.__ep_consumer is consumer:
            return
        if self.__ep_consumer:
            raise VIOError('Consumer already attached')
        elif self.__ep_eod:
            raise VIOError('Producer already reached end-of-data')
        self.__ep_consumer = consumer
        self.__ep_produced = self.__ep_produce_lim = 0
        consumer.attach(self.entity_produce)

        # Notify attached chain
        try:
            consumer.control.notify_producer_attached(self.entity_produce)
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
            self.__ep_produced = self.__ep_produce_lim = 0

    @property
    def _bc_control(self):
        if self._ep_consumer:
            return self._ep_consumer.control
        else:
            return VIOControl()

    @property
    def _bc_producer(self):
        return self.__bc_producer

    @property
    def _bc_flows(self):
        return (self.entity_produce,)

    @property
    def _bc_twoway(self):
        return True

    @property
    def _bc_reverse(self):
        return self.byte_produce

    @property
    def _bp_control(self):
        if self._ec_producer:
            return self._ec_producer.control
        else:
            return VIOControl()

    @property
    def _bp_consumer(self):
        return self.__bp_consumer

    @property
    def _bp_flows(self):
        return (self.entity_consume,)

    @property
    def _bp_twoway(self):
        return True

    @property
    def _bp_reverse(self):
        return self.byte_consume

    @property
    def _ec_control(self):
        if self._bp_consumer:
            return self._bp_consumer.control
        else:
            return VIOControl()

    @property
    def _ec_producer(self):
        return self.__ec_producer

    @property
    def _ec_flows(self):
        return (self.byte_produce,)

    @property
    def _ec_twoway(self):
        return True

    @property
    def _ec_reverse(self):
        return self.entity_produce

    @property
    def _ep_control(self):
        if self._bc_producer:
            return self._bc_producer.control
        else:
            return VIOControl()

    @property
    def _ep_consumer(self):
        return self.__ep_consumer

    @property
    def _ep_flows(self):
        return (self.byte_consume,)

    @property
    def _ep_twoway(self):
        return True

    @property
    def _ep_reverse(self):
        return self.entity_consume

    def __bp_do_produce(self):
        if not self.__bp_consumer:
            return

        if self.__bp_eod:
            # If end-of-data was reached notify consumer
            if self.__bp_consumer and not self.__bp_sent_eod:
                self.__bp_consumer.end_consume(self.__ec_eod_clean)
                self.__bp_sent_eod = True
            return

        if (self.__bp_produce_lim is not None
            and 0 <= self.__bp_produce_lim <= self.__bp_produced):
            return
        old_lim = self.__bp_produce_lim

        if self.__handshake_send:
            if self.__bp_produce_lim is None or self.__bp_produce_lim < 0:
                max_write = self.__bp_max_write
            else:
                max_write = self.__bp_produce_lim - self.__bp_produced
            buf_len = len(self.__handshake_send)
            new_lim = self.__bp_consumer.consume(self.__handshake_send)
            self.__bp_produced += buf_len - len(self.__handshake_send)
            self.__bp_produce_lim = new_lim
            if not self.__handshake_send:
                self.__handshake_send = None
        if self.__handshaking:
            return

        if not (self.__bp_writer or self.__ec_queue or self.__bp_wbuf):
            return

        max_write = self.__lim(self.__bp_produced, self.__bp_produce_lim)
        bytes_left = self.__lim(0, max_write, self.__bp_max_write)
        entity_was_popped = False
        while bytes_left != 0 and (self.__bp_writer or self.__ec_queue):
            if not self.__bp_writer:
                entity = self.__ec_queue.popleft()
                entity_was_popped = True
                self.__bp_writer = entity._v_writer(self.__ctx_ref)
            data = self.__bp_writer.write(bytes_left)
            self.__bp_wbuf.append(data)
            bytes_left -= len(data)
            if self.__bp_writer.done():
                self.__bp_writer = None
        buf_len = len(self.__bp_wbuf)
        new_lim = self.__bp_consumer.consume(self.__bp_wbuf)
        self.__bp_produced += buf_len - len(self.__bp_wbuf)
        self.__bp_produce_lim = new_lim

        # If produce limit was updated, schedule another 'produce' batch
        if self.__bp_produce_lim != old_lim:
            self.reactor.schedule(0.0, self.__bp_do_produce)

        # If entity consume limit changed, notify producer
        if self.__ec_producer:
            old_lim = self.__ec_consume_lim
            max_add = self.__lim(len(self.__ec_queue), self.__ec_buf_len)
            if max_add >= 0:
                self.__ec_consume_lim = self.__ec_consumed + max_add
            else:
                self.__ec_consume_lim = -1
            if self.__ec_consume_lim != old_lim:
                self.reactor.schedule(0.0, self.__ec_send_limit)

    def __ec_send_limit(self):
        if self.__ec_producer:
            self.__ec_producer.can_produce(self.__ec_consume_lim)

    def __bc_send_limit(self):
        if self.__bc_producer:
            self.__bc_producer.can_produce(self.__bc_consume_lim)

    def __ep_produce(self):
        if self.__ep_consumer and not self.__ep_eod and self.__ep_queue:
            max_prod = self.__lim(self.__ep_produced, self.__ep_produce_lim)
            prod = None
            if max_prod < 0 or max_prod >= len(self.__ep_queue):
                prod = tuple(self.__ep_queue)
                self.__ep_queue.clear()
            elif max_prod > 0:
                prod = []
                for i in xrange(max_prod):
                    if self.__ep_queue:
                        prod.append(self.__ep_queue.popleft())
                    else:
                        break
            old_lim = self.__ep_produce_lim
            if prod:
                new_lim = self.__ep_consumer.consume(prod)
                self.__ep_produced += len(prod)
                self.__ep_produce_lim = new_lim
                if self.__ep_produce_lim != old_lim:
                    self.reactor.schedule(0.0, self.__ep_produce)

            # Check if bc consume limit changed, if so trigger a can_produce
            if self.__bc_producer:
                old_lim = self.__bc_consume_lim
                max_add = self.__lim(len(self.__bc_rbuf), self.__bc_rbuf_len)
                if max_add >= 0:
                    self.__bc_consume_lim = self.__bc_consumed + max_add
                else:
                    self.__bc_consume_lim = -1
                if self.__bc_consume_lim != old_lim:
                    self.reactor.schedule(0.0, self.__bc_send_limit)

        # If end-of-data was reached, notify connected consumer
        if self.__ep_eod and self.__ep_consumer:
            if not self.__ep_sent_eod:
                self.__ep_consumer.end_consume(self.__bc_eod_clean)
                self.__ep_sent_eod = True

    def __handshake(self):
        while (self.__bc_rbuf
               and self.__handshake_len < self.__HANDSHAKE_MAXLEN):
            byte = self.__bc_rbuf.pop(1)
            self.__handshake_data.append(byte)
            self.__handshake_len += 1
            if byte == b'\n':
                break
        else:
            if self.__handshake_len >= self.__HANDSHAKE_MAXLEN:
                raise VIOError('Handshake protocol exceeded byte limit')
        if self.__handshake_data and self.__handshake_data[-1] == b'\n':
            try:
                header = b''.join(self.__handshake_data)
                header = header[:-1]
                parts = _ssplit(header, b'-')
                if len(parts) not in (2, 3):
                    raise VIOError('Malformed header')
                name, version = parts[:2]
                if name != b'VEC_DRAFT':
                    raise VIOError('Requires protocol VEC')
                if _pyver == 2:
                    _allowed = [bytes(_b_chr(num)) for num in
                                range(ord('0'), ord('9')+1)]
                    _allowed.append(b'.')
                else:
                    # Using integers for python3
                    _allowed = range(ord('0'), ord('9')+1) + [ord('.')]
                for char in version:
                    if char not in _allowed:
                        raise VIOError('Illegal protocol version number')
                nums = version.split(b'.')
                version = [int(num) for num in nums]
                if version != [0, 8]:
                    raise VIOError('Protocol version %s not supported'
                                   % '.'.join([str(v) for v in version]))
                if len(parts) == 3:
                    codec = parts[2]
                    if (not isinstance(codec, bytes)
                        or codec not in VString._v_codecs()):
                        raise VIOError('Invalid string codec')
                    if self.__config.weakctx:
                        ctx = self.__ctx()
                    else:
                        ctx = self.__ctx
                    if ctx:
                        #self.__logger.debug('Peer codec %s' % _b2s(codec))
                        ctx.str_decoding = codec
            except VIOError as e:
                self._bc_abort()
                raise e
            else:
                self.__handshaking = False
                self.__handshake_data = None
                self.reactor.schedule(0.0, self.__bp_do_produce)

    @classmethod
    def __lim(self, base, *lims):
        """Return smallest (lim-base) limit, or -1 if all limits are <0"""
        result = -1
        for lim in lims:
            if lim is not None and lim >= 0:
                lim = max(lim - base, 0)
                if result < 0:
                    result = lim
                result = min(result, lim)
        return result

    @property
    def __bp_eod(self):
        return (self.__ec_eod and not self.__ec_queue
                and not self.__bp_writer and not self.__bp_wbuf)

    @property
    def __ep_eod(self):
        return self.__bc_eod and not self.__ep_queue

    @property
    def __ctx_ref(self):
        if not self.__config.weakctx:
            return self.__ctx
        else:
            ctx = self.__ctx()
            if ctx:
                return ctx
            else:
                raise VIOError('Lost reference to serializer context object')


@abstract
@implements(IVReactorObject, IVEntityConsumer)
class VEntityConsumer(object):
    """Base class for a :class:`versile.orb.entity.VEntity` consumer.

    The base class is intended for and primarily suited for a entity
    consumer end-points which do not deal with connectivity with a
    follow-on I/O processing chain.

    :param reactor: reactor providing services to the object

    .. automethod:: _data_received
    .. automethod:: _data_ended
    .. automethod:: _set_receive_limit
    .. automethod:: _producer_attached
    .. automethod:: _producer_detached
    .. automethod:: _consumer_control
    .. automethod:: _consumer_aborted

    """
    def __init__(self, reactor):
        self.__reactor = reactor
        self.__ec_iface = None

        self.__ec_producer = None
        self.__ec_consumed = 0
        self.__ec_consume_lim = 0
        self.__ec_eod = False
        self.__ec_eod_clean = None
        self.__ec_aborted = False

    @property
    def entity_consume(self):
        """Holds the Entity Consumer interface."""
        cons = None
        if self.__ec_iface:
            cons = self.__ec_iface()
        if not cons:
            cons = _VEntityConsumer(self)
            self.__ec_iface = weakref.ref(cons)
        return cons

    @property
    def reactor(self):
        return self.__reactor

    @abstract
    def _data_received(self, data):
        """Receive data from the attached producer.

        :param data: received :class:`versile.orb.entity.VEntity` data
        :type  data: tuple
        :returns:    number of additional entities that can be received
        :raises:     :exc:`versile.reactor.io.VIOError`

        Return value None or negative number means there is no limit
        on the number of objects that can be received.

        """
        raise NotImplementedError()

    @abstract
    def _data_ended(self, clean):
        """Receive notification of end-of-data from attached producer.

        :param clean: if True then data stream was closed cleanly
        :type  clean: bool

        """
        raise NotImplementedError()

    @final
    def _set_receive_limit(self, limit):
        """Sets non-cumulative production limit for the connected producer.

        :param limit: number of entities that can be received
        :type  limit: int
        :raises:      :exc:`versile.reactor.io.VIOError`

        If the limit is None or negative, this means the provider can
        send unlimited data.

        .. note::

            This method operates on non-cumulative limits.

        """
        if not self.__ec_producer:
            raise VIOError('No connected producer')

        old_lim = self.__ec_consume_lim
        if limit is None or limit < 0:
            self.__ec_consume_lim = limit
        else:
            self.__ec_consume_lim = self.__ec_consumed + limit
        if self.__ec_consume_lim != old_lim:
            self.__ec_producer.can_produce(self.__ec_consume_lim)

    def _producer_attached(self):
        """Called internally after a producer was attached.

        Default calls :meth:`_set_receive_limit` to set unlimited
        production limit. Derived classes can override.

        """
        self._set_receive_limit(None)

    def _producer_detached(self):
        """Called after a producer was detached.

        Default does nothing, derived classes can override.

        """
        pass

    def _consumer_control(self):
        """Called internally to provide a control object for the producer.

        :returns: control object
        :rtype:   :class:`versile.reactor.io.VIOControl`

        Default returns a plain control object which does not
        implement any control events. Derived classes can override to
        implement control message handling.

        """
        return VIOControl()


    def _consumer_aborted(self):
        """Called after the consumer was aborted.

        Default does nothing, derived classes can override.

        """
        pass

    @peer
    def _ec_consume(self, product):
        if self.__ec_eod:
            raise VIOError('Consumer already received end-of-data')
        elif not self.__ec_producer:
            raise VIOError('No connected producer')
        elif not product:
            raise VIOError('No data to consume')
        max_cons = self.__lim(self.__ec_consumed, self.__ec_consume_lim)
        if max_cons == 0 or 0 < max_cons < len(product):
            raise VIOError('Consume limit exceeded')

        self.__ec_consumed += len(product)
        non_cumul_lim = self._data_received(product)
        if non_cumul_lim is None or non_cumul_lim < 0:
            self.__ec_consume_lim = non_cumul_lim
        else:
            self.__ec_consume_lim = self.__ec_consumed + non_cumul_lim
        return self.__ec_consume_lim

    @peer
    def _ec_end_consume(self, clean):
        if self.__ec_eod:
            return
        self._data_ended(clean)
        self._ec_abort()

    def _ec_abort(self):
        if not self.__ec_aborted:
            self.__ec_aborted = True
            self.__ec_eod = True
            if self.__ec_producer:
                self.__ec_producer.abort()
            self._ec_detach()
            self._consumer_aborted()

    def _ec_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._ec_attach, producer, rthread=True)
            return

        if self.__ec_producer is producer:
            return
        if self.__ec_eod:
            raise VIOError('Consumer already received end-of-data')
        elif self.__ec_producer:
            raise VIOError('Producer already connected')
        self.__ec_producer = producer
        self.__ec_consumed = self.__ec_consume_lim = 0
        producer.attach(self.entity_consume)
        self._producer_attached()

        # Notify attached chain
        try:
            producer.control.notify_consumer_attached(self.entity_consume)
        except VIOMissingControl:
            pass

    def _ec_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._ec_detach, rthread=True)
            return

        if self.__ec_producer:
            prod, self.__ec_producer = self.__ec_producer, None
            self.__ec_consumed = self.__ec_consume_lim = 0
            prod.detach()
            self._producer_detached()
    @property

    def _ec_control(self):
        return self._consumer_control()

    @property
    def _ec_producer(self):
        return self.__ec_producer

    @property
    def _ec_flows(self):
        return tuple()

    @property
    def _ec_twoway(self):
        return False

    @property
    def _ec_reverse(self):
        raise NotImplementedError()

    @classmethod
    def __lim(self, base, *lims):
        """Return smallest (lim-base) limit, or -1 if all limits are <0"""
        result = -1
        for lim in lims:
            if lim is not None and lim >= 0:
                lim = max(lim - base, 0)
                if result < 0:
                    result = lim
                result = min(result, lim)
        return result


@abstract
@implements(IVReactorObject, IVEntityProducer)
class VEntityProducer(object):
    """Base implementation of a :class:`versile.orb.entity.VEntity` producer.

    The base class is intended for and primarily suited for an entity
    producer end-point which does not need to deal with connectivity
    to a follow-on I/O processing chain.

    :param reactor: reactor providing services to the object

    .. automethod:: _produce
    .. automethod:: _end_produce
    .. automethod:: _trigger_production
    .. automethod:: _producer_aborted
    .. automethod:: _producer_control
    .. automethod:: _consumer_attached
    .. automethod:: _consumer_detached

    """

    def __init__(self, reactor):
        self.__reactor = reactor
        self.__ep_iface = None

        self.__ep_consumer = None
        self.__ep_produced = 0
        self.__ep_produce_lim = 0
        self.__ep_eod = False
        self.__ep_eod_clean = None
        self.__ep_sent_eod = False
        self.__ep_aborted = False

    @property
    def entity_produce(self):
        """Holds the Entity Producer interface to the serializer."""
        prod = None
        if self.__ep_iface:
            prod = self.__ep_iface()
        if not prod:
            prod = _VEntityProducer(self)
            self.__ep_iface = weakref.ref(prod)
        return prod

    @property
    def reactor(self):
        return self.__reactor

    @abstract
    def _produce(self, max_entities):
        """Called internally to produce data for delivery to a consumer.

        :param max_entities: max entities to produce (or None if no limit)
        :type  max_entities: int
        :returns:            produced :class:`versile.orb.entity.VEntity` data
        :rtype:              tuple
        :raises:             :exc:`versile.reactor.io.VIOError`

        This method is called internally when the object has received
        an updated production limit and is able to send data, until no
        more data to send or production limit is reached.

        """
        raise NotImplementedError()

    def _end_produce(self, clean):
        """Registers end-of-data for the producer's data output.

        :param clean: if True production output was ended cleanly
        :type  clean: bool

        """
        self.__ep_eod = True
        self.__ep_eod_clean = False
        self._trigger_production()

    def _trigger_production(self):
        """Initiates a production cycle.

        This will trigger execution of :meth:`_produce` if there is
        available production capacity. Producer should call when it
        has new data available for production.

        """
        if self.__ep_consumer:
            max_prod = self.__lim(self.__ep_produced, self.__ep_produce_lim)
            if max_prod or (self.__ep_eod and not self.__ep_sent_eod):
                self.reactor.schedule(0.0, self.__ep_produce)

    def _consumer_attached(self):
        """Called after a consumer was attached.

        Default does nothing, derived classes can override.

        """
        pass

    def _consumer_detached(self):
        """Is called after a consumer was detached.

        Default does nothing, derived classes can override.

        """
        pass

    def _producer_control(self):
        """Called internally to provide a control object for the producer.

        :returns: control object
        :rtype:   :class:`versile.reactor.io.VIOControl`

        Default returns a plain control object which does not
        implement any control events. Derived classes can override to
        implement control message handling.

        """
        return VIOControl()

    def _producer_aborted(self):
        """Called after the producer was aborted.

        Default does nothing, derived classes can override.

        """
        pass

    @peer
    def _ep_can_produce(self, limit):
        if not self.__ep_consumer:
            raise VIOError('No attached consumer')
        if limit is None or limit < 0:
            if (not self.__ep_produce_lim is None
                and not self.__ep_produce_lim < 0):
                self.__ep_produce_lim = limit
                self.reactor.schedule(0.0, self.__ep_produce)
        else:
            if (self.__ep_produce_lim is not None
                and 0 <= self.__ep_produce_lim < limit):
                self.__ep_produce_lim = limit
                self.reactor.schedule(0.0, self.__ep_produce)

    def _ep_abort(self):
        if not self.__ep_aborted:
            self.__ep_aborted = True
            if self.__ep_consumer:
                self.__ep_consumer.abort()
            self._ep_detach()
            self._producer_aborted()

    def _ep_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._ep_attach, consumer, rthread=True)
            return

        if self.__ep_consumer is consumer:
            return
        if self.__ep_consumer:
            raise VIOError('Consumer already attached')
        elif self.__ep_eod:
            raise VIOError('Producer already reached end-of-data')
        self.__ep_consumer = consumer
        self.__ep_produced = self.__ep_produce_lim = 0
        consumer.attach(self.entity_produce)
        self._consumer_attached()

        # Notify attached chain
        try:
            consumer.control.notify_producer_attached(self.entity_produce)
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
            self.__ep_produced = self.__ep_produce_lim = 0
            self._consumer_detached()

    def __ep_produce(self):
        if self.__ep_consumer:
            if not self.__ep_eod:
                max_prod = self.__lim(self.__ep_produced,
                                      self.__ep_produce_lim)
                if max_prod != 0:
                    output = self._produce(max_prod)
                    if output:
                        self.__ep_consumer.consume(output)
                        self.__ep_produced += len(output)
            elif not self.__ep_sent_eod:
                self.__ep_consumer.end_consume(self.__ep_eod_clean)
                self.__ep_sent_eod = True

    @property
    def _ep_control(self):
        return self._producer_control()

    @property
    def _ep_consumer(self):
        return self.__ep_consumer

    @property
    def _ep_flows(self):
        return tuple()

    @property
    def _ep_twoway(self):
        return False

    @property
    def _ep_reverse(self):
        raise NotImplementedError()

    @classmethod
    def __lim(self, base, *lims):
        """Return smallest (lim-base) limit, or -1 if all limits are <0"""
        result = -1
        for lim in lims:
            if lim is not None and lim >= 0:
                lim = max(lim - base, 0)
                if result < 0:
                    result = lim
                result = min(result, lim)
        return result


class VEntityIOPair(object):
    """Holds a VEntity consumer/producer pair.

    :param cons: consumer
    :type  cons: :class:`VEntityConsumer`
    :param prod: producer
    :type  prod: :class:`VEntityProducer`

    Intended primarily as a convenience type for holding a
    consumer/producer pair when returning from functions or passing as
    arguments; also it allows a cleaner syntax for attaching two
    consumer/producer pairs.

    """

    def __init__(self, cons, prod):
        self._cons = cons
        self._prod = prod

    def attach(self, pair):
        """Attach to another consumer/producer pair.

        :param pair: pair to connect to
        :type  pair: :class:`VEntityIOPair`

        Attaches consumer of this pair to the producer of the provided
        pair, and attaches the producer of this pair to the consumer of
        the provided pair.

        """
        self._cons.attach(pair.producer)
        self._prod.attach(pair.consumer)

    @property
    def consumer(self):
        """Holds the consumer interface (\ :class:`VEntityConsumer`\ )."""
        return self._cons

    @property
    def producer(self):
        """Holds the consumer interface (\ :class:`VEntityConsumer`\ )."""
        return self._prod


@implements(IVEntityWriter)
class VEntityWriter(VEntityProducer):
    """A entity writer which sends output entities to a consumer.

    :param reactor: a reactor providing services to the object
    :type  reactor: :class:`versile.reactor.IVTimeReactor`
    :param max_obj: max entities to send to consumer per single consume()
    :type  max_obj: int

    .. automethod:: _produce
    .. automethod:: _producer_aborted

    """

    def __init__(self, reactor):
        super(VEntityWriter, self).__init__(reactor)
        self.__writer_lock = Lock()
        self.__write_buffer = collections.deque()
        self.__write_eod = False
        self.__write_eod_clean = None
        self.__write_triggered = False

    @final
    def write(self, entities):
        """See :meth:`IVEntityWriter.write`\ .

        This is a thread-safe method which can be called from outside
        reactor thread.

        """
        self.__writer_lock.acquire()
        try:
            if self.__write_eod:
                raise VIOClosed('Writer closed for further writing')
            for entity in entities:
                self.__write_buffer.append(entity)
            if not self.__write_triggered:
                self.__write_triggered = True
                self.reactor.schedule(0.0, self.__trigger_write)
        finally:
            self.__writer_lock.release()

    @final
    def end_write(self, clean=True):
        """See :meth:`IVEntityWriter.end_write`\ .

        This is a thread-safe method which can be called from outside
        reactor thread.

        """
        self.__writer_lock.acquire()
        try:
            if not self.__write_eod:
                self.__write_eod = True
                self.__write_eod_clean = clean
            if not self.__write_triggered:
                self.__write_triggered = True
                self.reactor.schedule(0.0, self.__trigger_write)
        finally:
            self.__writer_lock.release()

    @final
    def abort_writer(self):
        """See :meth:`IVEntityWriter.abort_writer`\ .

        This is a thread-safe method which can be called from outside
        reactor thread.

        """
        self.reactor.schedule(0.0, self._ep_abort)

    @final
    def _produce(self, max_len):
        """Implemented internally to produce data from write buffer.

        Derived classes should not override this method.

        """
        result = collections.deque()
        self.__writer_lock.acquire()
        try:
            while self.__write_buffer and (max_len is None or max_len != 0):
                result.append(self.__write_buffer.popleft())
                if max_len is not None and max_len > 0:
                    # Popped one VEntity -> reduce max_len by one
                    max_len -= 1
            if self.__write_eod and not self.__write_buffer:
                self.reactor.schedule(0.0, self._end_produce,
                                      self.__write_eod_clean)
            return tuple(result)
        finally:
            self.__writer_lock.release()

    def _producer_aborted(self):
        """Overloaded to clear write buffer when an abort event occurs.

        Derived classes should call the method on this class.

        """
        self.__writer_lock.acquire()
        try:
            self.__write_eod = True
            self.__write_buffer.clear()
        finally:
            self.__writer_lock.release()

    def __trigger_write(self):
        self.__writer_lock.acquire()
        try:
            if not self.__write_triggered:
                return
            self.__write_triggered = False
        finally:
            self.__writer_lock.release()
        self._trigger_production()


@abstract
@multiface
class VEntityAgent(VEntityConsumer, VEntityProducer):
    """A :class:`versile.orb.entity.VEntity` consumer and producer.

    The agent is a convenience base class which implements both a
    :class:`VEntityProducer` and :class:`VEntityConsumer` as
    full-duplex pair. The agent also includes a logger which
    interfaces with the reactor logger.

    :param reactor:    a reactor which provides services to the object
    :type  reactor:    :class:`versile.reactor.IVTimeReactor`
    :param log_prefix: if not None, prefix to use for object's logger
    :type  log_prefix: unicode

    """

    def __init__(self, reactor, log_prefix=None):
        VEntityConsumer.__init__(self, reactor)
        VEntityProducer.__init__(self, reactor)
        self.__log = reactor.log.create_proxy_logger(prefix=log_prefix)

    @classmethod
    def simple_factory(cls, *args, **kargs):
        """Creates and returns a simple factory for the class.

        :param args:  arguments for constructor
        :param kargs: keyword arguments to constructor

        The returned factory has a method build() which will construct
        a :class:`VEntityAgent`\ . Each agent is constructed by
        calling cls(\*args, \*\*kargs).

        """
        class _AgentFactory(object):
            def build(self):
                return cls(*args, **kargs)
        return _AgentFactory()

    @property
    def entity_io(self):
        """VEntity interface (:class:`versile.reactor.io.VEntityIOPair`\ )."""
        return VEntityIOPair(self.entity_consume, self.entity_produce)

    @property
    def log(self):
        """A logger for the agent."""
        return self.__log

    @property
    def _ec_twoway(self):
        return True

    @property
    def _ec_reverse(self):
        return self.entity_produce

    @property
    def _ep_twoway(self):
        return True

    @property
    def _ep_reverse(self):
        return self.entity_consume


@abstract
@multiface
class VEntityWAgent(VEntityConsumer, VEntityWriter):
    """A :class:`versile.orb.entity.VEntity` consumer and producer.

    The agent is a convenience base class which implements both a
    :class:`VEntityWriter` and :class:`VEntityConsumer` as full-duplex
    pair. The agent also includes a logger which interfaces with the
    reactor logger.

    :param reactor:    a reactor which provides services to the object
    :type  reactor:    :class:`versile.reactor.IVTimeReactor`
    :param log_prefix: if not None, prefix to use for object's logger
    :type  log_prefix: unicode

    """

    def __init__(self, reactor, log_prefix=None):
        VEntityConsumer.__init__(self, reactor)
        VEntityWriter.__init__(self, reactor)
        self.__log = reactor.log.create_proxy_logger(prefix=log_prefix)

    @classmethod
    def simple_factory(cls, *args, **kargs):
        """Creates and returns a simple factory for the class.

        :param args:  arguments for constructor
        :param kargs: keyword arguments to constructor

        The returned factory has a method build() which will construct
        a :class:`VEntityWAgent`\ . Each agent is constructed by
        calling cls(\*args, \*\*kargs).

        """
        class _AgentFactory(object):
            def build(self):
                return cls(*args, **kargs)
        return _AgentFactory()

    @property
    def log(self):
        """A logger for the agent."""
        return self.__log

    @property
    def entity_io(self):
        """VEntity interface (:class:`versile.reactor.io.VEntityIOPair`\ )."""
        return VEntityIOPair(self.entity_consume, self.entity_produce)

    @property
    def _ec_twoway(self):
        return True

    @property
    def _ec_reverse(self):
        return self.entity_produce

    @property
    def _ep_twoway(self):
        return True

    @property
    def _ep_reverse(self):
        return self.entity_consume


class VEntitySerializerConfig(VConfig):
    """Configuration settings for a :class:`VEntitySerializer`\ .

    :param weakctx:   if True then track the context as a weak reference
    :type  weakctx:   bool
    :param handshake: if True perform a VEntity Channel protocol handshake
    :type  handshake: bool
    :param rbuf_len:  maximum byte input data to buffer (unlimited if None)
    :type  rbuf_len:  int
    :param max_write: maximum byte output data to buffer (unlimited if None)
    :type  max_write: int
    :param msg_max:   max bytes of single protocol message (unlimited if None)
    :type  msg_max:   int
    :param ebuf_len:  max number of entities to hold in entity input buffer
    :type  ebuf_len:  int

    If *handshake* is True then a standard :term:`VP` VEntity Channel
    protocol handshake is performed on the byte interface before
    serialized data is sent or received. Otherwise, the protocol
    handshake is ignored and serialization starts immediately.

    *msg_max* is the maximum length in bytes of a single serialized
    message that is received by the channel's byte consumer interface.

    .. warning::

        If *msg_max* is not set then a peer will be able to send messages of
        unlimited length, which may exhaust available resources.

    """
    def __init__(self, weakctx=False, handshake=True, rbuf_len=0x4000,
                 max_write=0x4000, msg_max=101*1024**2, ebuf_len=3):
        s_init = super(VEntitySerializerConfig, self).__init__
        s_init(weakctx=weakctx, handshake=handshake, rbuf_len=rbuf_len,
               max_write=max_write, msg_max=msg_max, ebuf_len=ebuf_len)


@implements(IVByteConsumer)
class _VByteConsumer(object):
    def __init__(self, serializer):
        self.__proxy = serializer

    @peer
    def consume(self, data, clim=None):
        return self.__proxy._bc_consume(data, clim)

    def end_consume(self, clean):
        return self.__proxy._bc_end_consume(clean)

    def abort(self):
        return self.__proxy._bc_abort()

    def attach(self, producer):
        return self.__proxy._bc_attach(producer)

    def detach(self):
        return self.__proxy._bc_detach()

    @property
    def control(self):
        return self.__proxy._bc_control

    @property
    def producer(self):
        return self.__proxy._bc_producer

    @property
    def flows(self):
        return self.__proxy._bc_flows

    @property
    def twoway(self):
        return self.__proxy._bc_twoway

    @property
    def reverse(self):
        return self.__proxy._bc_reverse


@implements(IVByteProducer)
class _VByteProducer(object):
    def __init__(self, serializer):
        self.__proxy = serializer

    @peer
    def can_produce(self, limit):
        return self.__proxy._bp_can_produce(limit)

    def abort(self):
        return self.__proxy._bp_abort()

    def attach(self, consumer):
        return self.__proxy._bp_attach(consumer)

    def detach(self):
        return self.__proxy._bp_detach()

    @property
    def control(self):
        return self.__proxy._bp_control

    @property
    def consumer(self):
        return self.__proxy._bp_consumer

    @property
    def flows(self):
        return self.__proxy._bp_flows

    @property
    def twoway(self):
        return self.__proxy._bp_twoway

    @property
    def reverse(self):
        return self.__proxy._bp_reverse


@implements(IVEntityConsumer)
class _VEntityConsumer(object):
    def __init__(self, obj):
        self.__proxy = obj

    @peer
    def consume(self, product):
        return self.__proxy._ec_consume(product)

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


@implements(IVEntityProducer)
class _VEntityProducer(object):
    def __init__(self, obj):
        self.__proxy = obj

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
