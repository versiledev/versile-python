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

"""Byte data channel end-point for producer/consumer chain."""
from __future__ import print_function, unicode_literals

import collections
from threading import Lock, Condition
import weakref

from versile.internal import _b2s, _s2b, _bfmt, _ssplit, _vexport, _pyver
from versile.internal import _b_ord, _b_chr
from versile.common.iface import implements, abstract, final, peer, multiface
from versile.common.iface import VInterface
from versile.common.log import VLogger
from versile.common.util import VByteBuffer, VConfig
from versile.orb.entity import VEntity, VString, VEntityReaderError
from versile.reactor import IVReactorObject
from versile.reactor.io import IVConsumer, IVByteConsumer
from versile.reactor.io import IVProducer, IVByteProducer
from versile.reactor.io import VIOControl, VIOClosed, VIOError
from versile.reactor.io import VIOMissingControl, VIOTimeout

__all__ = ['VByteChannel']
__all__ = _vexport(__all__)


@implements(IVReactorObject)
class VByteChannel(object):
    """Producer/consumer end-point for byte data.

    :param reactor:  reactor driving the socket's event handling
    :param buf_len:  buffer length for read operations
    :type  buf_len:  int

    This class is primarily intended for debugging byte producer/consumer
    I/O chains.

    """

    def __init__(self, reactor, buf_len=4096):
        self.__reactor = reactor
        self.__buf_len = buf_len

        self.__bc_consumed = 0
        self.__bc_consume_lim = 0
        self.__bc_producer = None
        self.__bc_eod = False
        self.__bc_eod_clean = None
        self.__bc_rbuf = VByteBuffer()
        self.__bc_rbuf_len = buf_len
        self.__bc_reader = None
        self.__bc_aborted = False
        self.__bc_cond = Condition()
        self.__bc_scheduled_lim_update = False

        self.__bp_produced = 0
        self.__bp_produce_lim = 0
        self.__bp_consumer = None
        self.__bp_eod = False
        self.__bp_eod_clean = None
        self.__bp_wbuf = VByteBuffer()
        self.__bp_wbuf_len = buf_len
        self.__bp_writer = None
        self.__bp_sent_eod = False
        self.__bp_aborted = False
        self.__bp_cond = Condition()
        self.__bp_scheduled_produce = False

        self.__bc_iface = self.__bp_iface = None

        # Set up a local logger for convenience
        self.__logger = VLogger(prefix='ByteChannel')
        self.__logger.add_watcher(self.reactor.log)

    def __del__(self):
        self.__logger.debug('Dereferenced')

    def recv(self, max_read, timeout=None):
        """Receive input data from byte channel.

        :param max_read: max bytes to read (unlimited if None)
        :type  max_read: int
        :param timeout:  timeout in seconds (blocking if None)
        :type  timeout:  float
        :returns:        data read (empty if input was closed)
        :rtype:          bytes
        :raises:         :exc:`versile.reactor.io.VIOTimeout`\ ,
                         :exc:`versile.reactor.io.VIOError`

        """
        if timeout:
            start_time = time.time()
        with self.__bc_cond:
            while True:
                if self.__bc_rbuf:
                    if max_read is None:
                        result = self.__bc_rbuf.pop()
                    elif max_read > 0:
                        result = self.__bc_rbuf.pop(max_read)
                    else:
                        result = b''

                    # Trigger updating can_produce in reactor thread
                    if not self.__bc_scheduled_lim_update:
                        self.__bc_scheduled_lim_update = True
                        self.reactor.schedule(0.0, self.__bc_lim_update)

                    return result
                elif self.__bc_aborted:
                    raise VIOError('Byte input was aborted')
                elif self.__bc_eod:
                    if self.__bc_eod_clean:
                        return b''
                    else:
                        raise VIOError('Byte input was closed but not cleanly')

                if timeout == 0.0:
                    raise VIOTimeout()
                elif timeout is not None and timeout > 0.0:
                    current_time = time.time()
                    if current_time > start_time + timeout:
                        raise VIOTimeout()
                    wait_time = start_time + timeout - current_time
                    self.__bc_cond.wait(wait_time)
                else:
                    self.__bc_cond.wait()

    def send(self, data, timeout=None):
        """Receive input data from byte channel.

        :param data:     data to write
        :type  data:     bytes
        :type  max_read: int
        :param timeout:  timeout in seconds (blocking if None)
        :type  timeout:  float
        :returns:        number bytes written
        :rtype:          int
        :raises:         :exc:`versile.reactor.io.VIOTimeout`\ ,
                         :exc:`versile.reactor.io.VIOError`

        """
        if timeout:
            start_time = time.time()
        with self.__bp_cond:
            while True:
                if self.__bp_aborted:
                    raise VIOError('Byte output was aborted')
                elif self.__bp_eod:
                    raise VIOError('Byte output was closed')
                if not data:
                    return 0
                max_write = self.__bp_wbuf_len - len(self.__bp_wbuf)
                if max_write > 0:
                    write_data = data[:max_write]
                    self.__bp_wbuf.append(write_data)

                    # Trigger reactor production
                    if not self.__bp_scheduled_produce:
                        self.__bp_scheduled_produce = True
                        self.reactor.schedule(0.0, self.__bp_do_produce)

                    return len(write_data)

                if timeout == 0.0:
                    raise VIOTimeout()
                elif timeout is not None and timeout > 0.0:
                    current_time = time.time()
                    if current_time > start_time + timeout:
                        raise VIOTimeout()
                    wait_time = start_time + timeout - current_time
                    self.__bc_cond.wait(wait_time)
                else:
                    self.__bc_cond.wait()

    def close(self):
        """Closes the connection."""
        def _close():
            if not self.__bp_aborted and not self.__bp_eod:
                self.__bp_eod = True
                self.__bp_eod_clean = True
                self.__bp_do_produce()
            if not self.__bc_aborted and not self.__bc_eod:
                self.__bc_eod = True
                self.__bc_eod_clean = True
        self.reactor.schedule(0.0, _close)

    def abort(self):
        """Aborts the connection."""
        def _abort():
            self._bc_abort()
            self._bp_abort()
        self.reactor.schedule(0.0, _abort)

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
    def reactor(self):
        """Holds the object's reactor."""
        return self.__reactor

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

        with self.__bc_cond:
            buf_len = len(self.__bc_rbuf)
            self.__bc_rbuf.append_list(data.pop_list(max_cons))
            self.__bc_consumed += len(self.__bc_rbuf) - buf_len

            # Update consume limit
            max_add = self.__lim(len(self.__bc_rbuf), self.__bc_rbuf_len)
            if max_add >= 0:
                self.__bc_consume_lim = self.__bc_consumed + max_add
            else:
                self.__bc_consume_lim = -1

            # Notify data is available
            self.__bc_cond.notify_all()

        return self.__bc_consume_lim

    @peer
    def _bc_end_consume(self, clean):
        if self.__bc_eod:
            return
        self.__bc_eod = True
        self.__bc_eod_clean = clean

        with self.__bc_cond:
            self.__bc_cond.notify_all()

    def _bc_abort(self):
        if not self.__bc_aborted:
            with self.__bc_cond:
                self.__bc_aborted = True
                self.__bc_eod = True
                if self.__bc_producer:
                    self.__bc_producer.abort()
                    self._bc_detach()
                self.__bc_cond.notify_all()

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
                if not self.__bp_scheduled_produce:
                    self.__bp_scheduled_produce = True
                    self.reactor.schedule(0.0, self.__bp_do_produce)
        else:
            if (self.__bp_produce_lim is not None
                and 0 <= self.__bp_produce_lim < limit):
                self.__bp_produce_lim = limit
                if not self.__bp_scheduled_produce:
                    self.__bp_scheduled_produce = True
                    self.reactor.schedule(0.0, self.__bp_do_produce)

    def _bp_abort(self):
        if not self.__bp_aborted:
            with self.__bp_cond:
                self.__bp_aborted = True
                self.__bp_wbuf.remove()
                if self.__bp_consumer:
                    self.__bp_consumer.abort()
                    self._bp_detach()
                self.__bp_cond.notify_all()

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

    @property
    def _bc_control(self):
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

    def __bc_lim_update(self):
        self.__bc_scheduled_lim_update = False

        if not self.__bc_producer or self.__bc_aborted or self.__bc_eod:
            return

        old_lim = self.__bc_consume_lim
        self.__bc_consume_lim = self.__lim(len(self.__bc_rbuf),
                                           self.__bc_rbuf_len)
        if old_lim != self.__bc_consume_lim:
            self.__bc_producer.can_produce(self.__bc_consume_lim)

    def __bp_do_produce(self):
        self.__bp_scheduled_produce = False

        if not self.__bp_consumer:
            return

        with self.__bp_cond:
            if self.__bp_eod:
                # If end-of-data was reached notify consumer
                if self.__bp_consumer and not self.__bp_sent_eod:
                    self.__bp_consumer.end_consume(self.__bp_eod_clean)
                    self.__bp_sent_eod = True
                return

            if (self.__bp_produce_lim is not None
                and 0 <= self.__bp_produce_lim <= self.__bp_produced):
                return

            old_lim = self.__bp_produce_lim
            max_write = self.__lim(self.__bp_produced, self.__bp_produce_lim)
            if max_write != 0 and self.__bp_wbuf:
                old_len = len(self.__bp_wbuf)
                new_lim = self.__bp_consumer.consume(self.__bp_wbuf)
                self.__bp_produced += self.__bp_wbuf_len - len(self.__bp_wbuf)
                self.__bp_produce_lim = new_lim
                if old_len != len(self.__bp_wbuf):
                    self.__bp_cond.notify_all()

            # Schedule another if produce limit was updated and buffer has data
            if self.__bp_wbuf and self.__bp_produce_lim != old_lim:
                if not self.__bp_scheduled_produce:
                    self.__bp_scheduled_produce = True
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
