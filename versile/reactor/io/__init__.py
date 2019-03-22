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

"""Framework and components for reactor-driven I/O."""
from __future__ import print_function, unicode_literals

import collections
from threading import Lock
import weakref

from versile.internal import _vexport
from versile.common.iface import VInterface
from versile.common.iface import implements, peer, final, abstract, multiface
from versile.common.failure import VFailure
from versile.common.util import VByteBuffer
from versile.reactor import IVReactorObject

__all__ = ['IVByteConsumer', 'IVByteHandle', 'IVByteHandleIO',
           'IVByteHandleInput', 'IVByteHandleOutput', 'IVByteIO',
           'IVByteInput', 'IVByteOutput', 'IVByteProducer', 'IVByteWriter',
           'IVConsumer', 'IVHalfClose', 'IVProducer', 'IVSelectable',
           'IVSelectableIO', 'IVSelectableInput', 'IVSelectableOutput',
           'VByteAgent', 'VByteConsumer', 'VByteProducer',
           'VByteWAgent', 'VByteWriter', 'VFIOCompleted', 'VFIOEnded',
           'VFIOError', 'VFIOException', 'VFIOLost', 'VHalfClose',
           'VHalfCloseInput', 'VHalfCloseOutput', 'VHalfClosePolicy',
           'VIOClosed', 'VIOCompleted', 'VIOControl', 'VIOEnded',
           'VIOError', 'VIOException', 'VIOLost', 'VIOMissingControl',
           'VNoHalfClose', 'VIOTimeout', 'VByteIOPair']
__all__ = _vexport(__all__)


class IVByteHandle(VInterface):
    """Base interface for byte I/O which can be driven by a reactor."""

    @peer
    def close_io(self, reason):
        """Called by event handler to close I/O all directions.

        :param reason: reason for closing
        :type  reason: :class:`versile.common.failure.VFailure`
        :returns:      True if channel was closed

        """


class IVByteHandleInput(IVByteHandle):
    """Interface for a byte input which can be driven by a reactor."""

    @peer
    def do_read(self):
        """Called by event handler to signal input is ready for reading.

        The method must either read data or stop further reading,
        otherwise the reactor may call do_read in an infinite loop. If
        an error condition occurs, the method is responsible for
        stopping reading and resolving any cleanup as appropriate.

        """

    @peer
    def close_input(self, reason):
        """Called by the reactor event handler to close input.

        :param reason: reason for closing
        :type  reason: :class:`versile.common.failure.VFailure`
        :returns:      True if channel was closed

        """


class IVByteHandleOutput(IVByteHandle):
    """Interface for a byte output which can be driven by a reactor."""

    @peer
    def do_write(self):
        """Called by event handler to signal input is ready for writing.

        The method must either write data or stop further writing,
        otherwise the reactor may call do_Write in an infinite
        loop. If an error condition occurs, the method is responsible
        for stopping writing and resolving any cleanup as appropriate.

        """

    @peer
    def close_output(self, reason):
        """Called by the reactor event handler to close output.

        :param reason: reason for closing
        :type  reason: :class:`versile.common.failure.VFailure`
        :returns:      True if channel was closed

        """


class IVByteHandleIO(IVByteHandleInput, IVByteHandleOutput):
    """Interface for byte I/O which can be driven by a reactor."""
    pass


class IVSelectable(IVByteHandle):
    """Interface for byte I/O objects which support :func:`select.select`\ ."""

    def fileno(self):
        """Returns a descriptor which can be used with :func:`select.select`\ .

        :returns: file descriptor
        :rtype:   int

        """


class IVSelectableInput(IVByteHandleInput, IVSelectable):
    """Interface to selectable byte input."""


class IVSelectableOutput(IVByteHandleOutput, IVSelectable):
    """Interface to selectable byte output."""


class IVSelectableIO(IVSelectableInput, IVSelectableOutput):
    """Interface to selectable byte I/O."""


class IVByteInput(IVByteHandleInput):
    """Interface to byte input with base methods for low-level I/O."""

    def read_some(self, max_len):
        """Perform non-blocking read.

        :param max_len: max bytes to read
        :returns:       data read
        :rtype:         bytes
        :raises:        :exc:`VIOException`

        Returns data that can be read, up to max_len bytes. Raises
        :exc:`VIOCompleted` or :exc:`VIOLost` if closed for input, or
        :exc:`VIOError` if read failed due to other error.

        """

    def start_reading(self):
        """Start listening for read events.

        When listening on an active event reactor, read events should
        invoke :meth:`read_some`\ .

        """

    def stop_reading(self):
        """Stop listening for read events.

        When not listening, :meth:`read_some` should not be invoked.

        """


class IVByteOutput(IVByteHandleOutput):
    """Interface to byte input with base methods for low-level I/O."""

    def write_some(self, data):
        """Perform non-blocking write.

        :param data: data to write
        :type  data: bytes
        :returns:    number of bytes written
        :raises:     :exc:`VIOException`

        Raises :exc:`VIOCompleted` or :exc:`VIOLost` if closed for
        output, or :exc:`VIOError` if write failed due to other error.

        """

    def start_writing(self):
        """Start listening for write events.

        When listening on an active event reactor, write events should
        invoke :meth:`write_some`\ .

        """

    def stop_writing(self):
        """Stop listening for write events.

        When not listening, :meth:`write_some` should not be invoked.

        """


class IVByteIO(IVByteHandleIO, IVByteInput, IVByteOutput):
    """Interface to byte I/O with base methods for low-level I/O."""

    @property
    def half_close_policy(self):
        """:class:`VHalfClosePolicy` how to handle I/O half-close."""


class IVConsumer(VInterface):
    """Interface to object which can receive data from a producer.

    The consumer is a generic abstraction for any object which can
    receive push data via the producer/consumer interface. It is not
    linked to any specific type of reactor loop or underlying I/O
    technology.

    The consumer is responsible for notifying the producer of its
    ability to receive data and tell the producer when it wants to
    close data transfer. Beyond that, it is the producer's
    responsibility to deliver data to the consumer.

    """

    @peer
    def consume(self, data):
        """Receive data from a connected producer.

        :param data:  data to consume
        :returns:     new (cumulative) production limit
        :rtype:       int
        :raises:      :exc:`VIOError`

        Type and use of *data* is context-specific (e.g. one consumer
        may consume byte data, another may consume objects).

        The consumer guarantees it will accept all received production
        data as long as the producer has complied with notified
        production limits.

        It is allowed for implementations of this method to call
        :meth:`IVProducer.can_produce` on the connected producer,
        within the execution context of this method. However, the
        inverse is not true (see :meth:`IVProducer.can_produce` for
        details).

        Not thread safe, should only be called by owning reactor thread.

        """

    def end_consume(self, clean):
        """Signals end-of-data for the data stream to the consumer.

        :param clean: if True then the stream was closed cleanly
        :type  clean: bool

        After the method has been called, :meth:`consume` no longer
        accepts new data. The consumer is responsible for performing
        any end-of-data processing, including e.g. notifying any
        consumers further down a processing chain.

        Not thread safe, should only be called by owning reactor thread.

        """

    def abort(self):
        """Aborts processing chain operation.

        Aborts any further processing. Should also abort and
        disconnect any producers/consumers in the processing chain
        that depend on this consumer's input.

        Not thread safe, should only be called by owning reactor thread.

        """

    def attach(self, producer):
        """Attach to a producer.

        :param producer: producer to attach to
        :type  producer: :class:`IVProducer`
        :raises:         :exc:`VIOError`

        The producer must be compatible with the particular type of
        consumer. The method is responsible for performing a callback
        to :meth:`IVProducer.attach` to make the reverse connection.

        Implementations of this method must be thread safe, allowing
        it to be called from outside the owning reactor's thread.

        """

    def detach(self):
        """Detach from any currently attached producer.

        When detaching, the method is responsible for performing a
        callback to :meth:`IVProducer.detach` to make the reverse
        detachment.

        Implementations of this method must be thread safe, allowing
        it to be called from outside the owning reactor's thread.

        """

    @property
    def control(self):
        """Holds a :class:`VIOControl` control message handler."""

    @property
    def producer(self):
        """Holds the connected :class:`IVProducer`\ ."""

    @property
    def flows(self):
        """Holds a tuple of consumers/producers in the processing flow.

        Does not include an attached producer or any :attr:`reverse`\ .

        """

    @property
    def twoway(self):
        """True if this consumer is part of a consumer/producer pair."""

    @property
    def reverse(self):
        """Holds the :class:`IVProducer` of a :attr:`twoway` pair.

        The property is only valid if :attr:`twoway` is set.

        """


class IVProducer(VInterface):
    """Interface to object which can deliver data to a consumer.

    The producer is a generic abstraction for any object which can
    push data over a producer/consumer interface. It is not linked to
    any specific type of reactor loop or underlying I/O technology.

    The producer is responsible for pushing data to a connected
    consumer when data is available and the consumer has notified it
    is ready to receive.

    """

    @peer
    def can_produce(self, limit):
        """Informs the producer it can deliver data to its consumer.

        :param limit: cumulative data quantity consumer can receive
        :type  limit: int
        :raises:      :exc:`VIOError`

        Sets a cumulative limit for the data quantity which consumer
        will accept. The cumulative limit is counted from when the
        producer/consumer pair were attached. The consumer will not
        accept data it has received already, and the producer should
        compare the limit with how much data it has already
        transmitted, in order to determine what data the consumer can
        receive.

        .. note::

            Implementations of this method are not allowed to make a
            direct call to :meth:`IVConsumer.consume` on the connected
            consumer. However, they may schedule a 'consume' call with
            the reactor's task scheduler, for delayed execution after
            the method has returned.

            The reason for this restriction is the producer and
            consumer could otherwise enter a long-running loop, which
            would cause the reactor to wait until the loop would
            finish, or other possible side effects such as exhausting
            the call stack.

        Not thread safe, should only be called by owning reactor thread.

        """

    def abort(self):
        """Aborts processing chain operation.

        Aborts any further processing. Should also abort and
        disconnect any producers/consumers in the processing chain
        that depend on this consumer's input.

        Not thread safe, should only be called by owning reactor thread.

        """

    def attach(self, consumer):
        """Attach to a consumer.

        :param consumer: consumer to attach to
        :type  consumer: :class:`IVConsumer`
        :raises:         :exc:`VIOError`

        The consumer must be compatible with the particular type of
        producer. The method is responsible for performing a callback
        to :meth:`IVConsumer.attach` to make the reverse connection.

        Implementations of this method must be thread safe, allowing
        it to be called from outside the owning reactor's thread.

        """

    def detach(self):
        """Detach from any currently attached consumer.

        When detaching, the method is responsible for performing a
        callback to :meth:`IVConsumer.detach` to make the reverse
        detachment.

        Implementations of this method must be thread safe, allowing
        it to be called from outside the owning reactor's thread.

        """

    @property
    def control(self, *args):
        """Holds a :class:`VIOControl` control message handler."""

    @property
    def consumer(self):
        """Holds the connected :class:`IVConsumer`\ ."""

    @property
    def flows(self):
        """Holds a tuple of consumers/producers in the processing flow.

        Does not include an attached producer or any :attr:`reverse`\ .

        """

    @property
    def twoway(self):
        """True if this consumer is part of a consumer/producer pair."""

    @property
    def reverse(self):
        """Holds the :class:`IVConsumer` of a :attr:`twoway` pair.

        The property is only valid if :attr:`twoway` is set.

        """


class IVByteConsumer(IVConsumer):
    """Interface to object which can receive byte data from a producer."""

    @peer
    def consume(self, data, clim=None):
        """Receive byte data from a connected producer.

        :param data:  contains data to consume
        :type  data:  :class:`versile.common.util.VByteBuffer`
        :param clim:  max bytes to consume (unlimited if None or <= 0)
        :type  clim:  int
        :returns:     new (cumulative) production limit
        :rtype:       int
        :raises:      :exc:`VIOError`

        See :class:`IVConsumer`\ . *clim* must be either >0 or None.

        Not thread safe, should only be called by owning reactor thread.

        """

    def attach(self, producer):
        """Attach a producer.

        :param producer: producer to attach
        :type  producer: :class:`IVByteProducer`
        :raises:         :exc:`VIOError`

        See :meth:`IVConsumer.attach`\ .

        Implementations of this method must be thread safe, allowing
        it to be called from outside the owning reactor's thread.

        """


class IVByteProducer(IVProducer):
    """Interface to object which can send byte data to a consumer."""

    @peer
    def can_produce(self, limit):
        """Informs the producer it can deliver data to its consumer.

        See :meth:`IVProducer.can_produce`\ .

        *limit* is the cumulative number of bytes transferred since
        the producer/consumer were connected. If *limit* is None or a
        negative number, this implies the consumer can receive
        unlimited data.

        Not thread safe, should only be called by owning reactor thread.

        """

    def attach(self, consumer):
        """Attach a consumer.

        :param consumer: consumer to attach (or None)
        :type  consumer: :class:`IVByteConsumer`
        :raises:         :exc:`VIOError`

        See :meth:`IVProducer.attach`\ .

        Implementations of this method must be thread safe, allowing
        it to be called from outside the owning reactor's thread.

        """


class IVByteWriter(VInterface):
    """Interface to a generic writer for byte data."""

    def write(self, data):
        """Write data to the writer's output.

        :param data: the data to write
        :type  data: bytes, list<bytes>
        :raises:       :exc:`versile.reactor.io.VIOClosed`,
                       :exc:`versile.reactor.io.VIOError`

        Buffers output data for writing. Data does not actually get
        written until it can be passed to a consumer.

        Implementations of this method must be thread safe, allowing
        it to be called from outside the owning reactor's thread.

        """

    def end_write(self, clean):
        """Closes writer output when write buffer becomes empty.

        :param clean: if True the output was closed cleanly
        :type  clean: bool

        Sends an end-of-data event to connected consumer once write
        buffer is empty.

        Implementations of this method must be thread safe, allowing
        it to be called from outside the owning reactor's thread.

        """

    def abort_writer(self):
        """Abort writer output and clear write output buffer.

        Calls :meth:`IVProducer.abort` on the
        writer's parent producer.

        Implementations of this method must be thread safe, allowing
        it to be called from outside the owning reactor's thread.

        """


class IVHalfClose(VInterface):
    """Interface to a policy for allowing I/O half-close."""

    @property
    def half_in(self):
        """If True allows half-closing input"""
        pass

    @property
    def half_out(self):
        """If True allows half-closing ouput"""
        pass


class VIOException(Exception):
    """General I/O exception."""


class VIOError(VIOException):
    """General I/O error."""


class VIOTimeout(VIOException):
    """I/O operation timeout."""


class VIOEnded(VIOException):
    """An I/O channel was disconnected or disrupted."""


class VIOMissingControl(VIOException):
    """Indicates a non-implemented producer/consumer control mechanism."""


class VIOClosed(VIOException):
    """An I/O channel was closed."""


class VIOCompleted(VIOEnded):
    """An I/O channel was disconnected cleanly.

    'Cleanly' depends on context. It could mean e.g. that an input
    channel was intentionally closed by the peer (for good or worse),
    or a an output channel was closed by the output channel's owner.

    """

class VIOLost(VIOEnded):
    """An I/O channel was not cleanly disconnected cleanly.

    Channel was disconnected without qualifying for being
    :exc:`VIOCompleted`

    """


class VFIOException(VFailure):
    """Convenience class for constructing a VFailure on a VIOException."""
    def __init__(self, *args, **kargs):
        """Sets up so self.value = VIOException(*args, **kargs)."""
        super(VFIOException, self).__init__(VIOException(*args, **kargs))

class VFIOError(VFailure):
    """Convenience class for constructing a VFailure on a VIOError."""
    def __init__(self, *args, **kargs):
        """Sets up so self.value = VIOError(*args, **kargs)."""
        super(VFIOError, self).__init__(VIOError(*args, **kargs))

class VFIOEnded(VFailure):
    """Convenience class for constructing a VFailure on a VIOEnded."""
    def __init__(self, *args, **kargs):
        """Sets up so self.value = VIOEnded(*args, **kargs)."""
        super(VFIOEnded, self).__init__(VIOEnded(*args, **kargs))

class VFIOCompleted(VFailure):
    """Convenience class for constructing a VFailure on a VIOCompleted."""
    def __init__(self, *args, **kargs):
        """Sets up so self.value = VIOCompleted(*args, **kargs)."""
        super(VFIOCompleted, self).__init__(VIOCompleted(*args, **kargs))

class VFIOLost(VFailure):
    """Convenience class for constructing a VFailure on a VIOLost."""
    def __init__(self, *args, **kargs):
        """Sets up so self.value = VIOLost(*args, **kargs)."""
        super(VFIOLost, self).__init__(VIOLost(*args, **kargs))


class VIOControl(object):
    """Base class for handling consumer/producer control events.

    Individual control handlers should be set up as methods on the
    :class:`VIOControl` object. When a control handler is looked up as
    an attribute on the object, if the handler is not available then
    :exc:`VIOMissingControl` should be raised.

    Default includes no individual handlers and overloads __getattr__
    to always raise :exc:`VIOMissingControl`\ . Derived classes should
    implement supported control handlers.

    """
    def __getattr__(self, attr):
        raise VIOMissingControl()


@abstract
@implements(IVReactorObject, IVByteConsumer)
class VByteConsumer(object):
    """Base class for a byte  consumer.

    The base class is intended for and primarily suited for byte
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
        self.__bc_iface = None

        self.__bc_producer = None
        self.__bc_consumed = 0
        self.__bc_consume_lim = 0
        self.__bc_eod = False
        self.__bc_eod_clean = None
        self.__bc_aborted = False

    @property
    def byte_consume(self):
        """Holds the Entity Consumer interface."""
        cons = None
        if self.__bc_iface:
            cons = self.__bc_iface()
        if not cons:
            cons = _VByteConsumer(self)
            self.__bc_iface = weakref.ref(cons)
        return cons

    @property
    def reactor(self):
        return self.__reactor

    @abstract
    def _data_received(self, data):
        """Receive data from the attached producer.

        :param data: received data
        :type  data: bytes
        :returns:    number of additional bytes that can be received
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
        if not self.__bc_producer:
            raise VIOError('No connected producer')

        old_lim = self.__bc_consume_lim
        if limit is None or limit < 0:
            self.__bc_consume_lim = limit
        else:
            self.__bc_consume_lim = self.__bc_consumed + limit
        if self.__bc_consume_lim != old_lim:
            self.__bc_producer.can_produce(self.__bc_consume_lim)

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
    def _bc_consume(self, data, clim):
        if self.__bc_eod:
            raise VIOError('Consumer already received end-of-data')
        elif not self.__bc_producer:
            raise VIOError('No connected producer')
        elif not data:
            raise VIOError('No data to consume')
        max_cons = self.__lim(self.__bc_consumed, self.__bc_consume_lim)
        if max_cons == 0:
            raise VIOError('Consume limit exceeded')
        if clim is not None and clim > 0:
            max_cons = min(max_cons, clim)
        cons_data = data.pop(max_cons)
        if cons_data:
            self.__bc_consumed += len(cons_data)
            non_cumul_lim = self._data_received(cons_data)
            if non_cumul_lim is None or non_cumul_lim < 0:
                self.__bc_consume_lim = non_cumul_lim
            else:
                self.__bc_consume_lim = self.__bc_consumed + non_cumul_lim
        return self.__bc_consume_lim

    @peer
    def _bc_end_consume(self, clean):
        if self.__bc_eod:
            return
        self._data_ended(clean)
        self._bc_abort()

    def _bc_abort(self):
        if not self.__bc_aborted:
            self.__bc_aborted = True
            self.__bc_eod = True
            if self.__bc_producer:
                self.__bc_producer.abort()
            self._bc_detach()
            self._consumer_aborted()

    def _bc_attach(self, producer):
        if self.__bc_producer is producer:
            return
        if self.__bc_eod:
            raise VIOError('Consumer already received end-of-data')
        elif self.__bc_producer:
            raise VIOError('Producer already connected')
        self.__bc_producer = producer
        self.__bc_consumed = self.__bc_consume_lim = 0
        producer.attach(self.byte_consume)
        self._producer_attached()
        try:
            producer.control.notify_consumer_attached(self.byte_consume)
        except VIOMissingControl:
            pass

    def _bc_detach(self):
        if self.__bc_producer:
            prod, self.__bc_producer = self.__bc_producer, None
            self.__bc_consumed = self.__bc_consume_lim = 0
            prod.detach()
            self._producer_detached()

    @property
    def _bc_control(self):
        return self._consumer_control()

    @property
    def _bc_producer(self):
        return self.__bc_producer

    @property
    def _bc_flows(self):
        return tuple()

    @property
    def _bc_twoway(self):
        return False

    @property
    def _bc_reverse(self):
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
@implements(IVReactorObject, IVByteProducer)
class VByteProducer(object):
    """Base implementation of a bytes producer.

    The base class is intended for and primarily suited for a bytes
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
        self.__bp_iface = None

        self.__bp_consumer = None
        self.__bp_produced = 0
        self.__bp_produce_lim = 0
        self.__bp_eod = False
        self.__bp_eod_clean = None
        self.__bp_sent_eod = False
        self.__bp_aborted = False

        self.__send_buff = VByteBuffer()

    @property
    def byte_produce(self):
        """Holds the Entity Producer interface to the serializer."""
        prod = None
        if self.__bp_iface:
            prod = self.__bp_iface()
        if not prod:
            prod = _VByteProducer(self)
            self.__bp_iface = weakref.ref(prod)
        return prod

    @property
    def reactor(self):
        return self.__reactor

    @abstract
    def _produce(self, max_bytes):
        """Called internally to produce data for delivery to a consumer.

        :param max_bytes: max number of bytes to produce (or None if no limit)
        :type  max_bytes: int
        :returns:         produced data
        :rtype:           bytes
        :raises:          :exc:`versile.reactor.io.VIOError`

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
        self.__bp_eod = True
        self.__bp_eod_clean = False
        self._trigger_production()

    def _trigger_production(self):
        """Initiates a production cycle.

        This will trigger execution of :meth:`_produce` if there is
        available production capacity. Producer should call when it
        has new data available for production.

        """
        if self.__bp_consumer:
            max_prod = self.__lim(self.__bp_produced, self.__bp_produce_lim)
            if max_prod or (self.__bp_eod and not self.__bp_sent_eod):
                self.reactor.schedule(0.0, self.__bp_produce)

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
    def _bp_can_produce(self, limit):
        if not self.__bp_consumer:
            raise VIOError('No attached consumer')
        if limit is None or limit < 0:
            if (not self.__bp_produce_lim is None
                and not self.__bp_produce_lim < 0):
                self.__bp_produce_lim = limit
                self.reactor.schedule(0.0, self.__bp_produce)
        else:
            if (self.__bp_produce_lim is not None
                and 0 <= self.__bp_produce_lim < limit):
                self.__bp_produce_lim = limit
                self.reactor.schedule(0.0, self.__bp_produce)

    def _bp_abort(self):
        if not self.__bp_aborted:
            self.__bp_aborted = True
            if self.__bp_consumer:
                self.__bp_consumer.abort()
            self._bp_detach()
            self._producer_aborted()

    def _bp_attach(self, consumer):
        if self.__bp_consumer is consumer:
            return
        if self.__bp_consumer:
            raise VIOError('Consumer already attached')
        elif self.__bp_eod:
            raise VIOError('Producer already reached end-of-data')
        self.__bp_consumer = consumer
        self.__bp_produced = self.__bp_produce_lim = 0
        consumer.attach(self.byte_produce)
        self._consumer_attached()
        try:
            consumer.control.notify_producer_attached(self.byte_produce)
        except VIOMissingControl:
            pass

    def _bp_detach(self):
        if self.__bp_consumer:
            cons, self.__bp_consumer = self.__bp_consumer, None
            cons.detach()
            self.__bp_produced = self.__bp_produce_lim = 0
            self._consumer_detached()

    def __bp_produce(self):
        if self.__bp_consumer:
            if not self.__bp_eod:
                max_prod = self.__lim(self.__bp_produced,
                                      self.__bp_produce_lim)
                if max_prod != 0:
                    output = self._produce(max_prod)
                    if output:
                        self.__send_buff.append(output)
                        self.__bp_consumer.consume(self.__send_buff)
                        if self.__send_buff:
                            raise VIOError('Consume error')
                        self.__bp_produced += len(output)
            elif not self.__bp_sent_eod:
                self.__bp_consumer.end_consume(self.__bp_eod_clean)
                self.__bp_sent_eod = True

    @property
    def _bp_control(self):
        return self._producer_control()

    @property
    def _bp_consumer(self):
        return self.__bp_consumer

    @property
    def _bp_flows(self):
        return tuple()

    @property
    def _bp_twoway(self):
        return False

    @property
    def _bp_reverse(self):
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


class VByteIOPair(object):
    """Holds a byte consumer/producer pair.

    :param cons: consumer
    :type  cons: :class:`VByteConsumer`
    :param prod: producer
    :type  prod: :class:`VByteProducer`

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
        :type  pair: :class:`VByteIOPair`

        Attaches consumer of this pair to the producer of the provided
        pair, and attaches the producer of this pair to the consumer of
        the provided pair.

        """
        self._cons.attach(pair.producer)
        self._prod.attach(pair.consumer)

    @property
    def consumer(self):
        """Holds the consumer interface (\ :class:`VByteConsumer`\ )."""
        return self._cons

    @property
    def producer(self):
        """Holds the consumer interface (\ :class:`VByteConsumer`\ )."""
        return self._prod


@implements(IVByteWriter)
class VByteWriter(VByteProducer):
    """A byte data writer which sends its output to a consumer.

    :param reactor: a reactor providing services to the object
    :param max_obj: max bytes to send consumer per single consume()
    :type  max_obj: int

    .. automethod:: _produce
    .. automethod:: _producer_aborted

    """

    def __init__(self, reactor):
        super(VByteWriter, self).__init__(reactor)
        self.__writer_lock = Lock()
        self.__write_buffer = VByteBuffer()
        self.__write_eod = False
        self.__write_eod_clean = None
        self.__write_triggered = False

    @final
    def write(self, data, lazy=True):
        """See :meth:`IVByteWriter.write`\ .

        This is a thread-safe method which can be called from outside
        reactor thread.

        """
        self.__writer_lock.acquire()
        try:
            if self.__write_eod:
                raise VIOClosed('Writer closed for further writing')
            self.__write_buffer.append(data)
            if not self.__write_triggered:
                self.__write_triggered = True
                self.reactor.schedule(0.0, self.__trigger_write)
        finally:
            self.__writer_lock.release()

    @final
    def end_write(self, clean=True):
        """See :meth:`IVByteWriter.end_write`\ .

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
        """See :meth:`IVByteWriter.abort_writer`\ .

        This is a thread-safe method which can be called from outside
        reactor thread.

        """
        self.reactor.schedule(0.0, self._bp_abort)

    @final
    def _produce(self, max_len):
        """Implemented internally to produce data from write buffer.

        Derived classes should not override this method.

        """
        self.__writer_lock.acquire()
        try:
            data = self.__write_buffer.pop(max_len)
            if self.__write_eod and not self.__write_buffer:
                self.reactor.schedule(0.0, self._end_produce,
                                      self.__write_eod_clean)
            return data
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
class VByteAgent(VByteConsumer, VByteProducer):
    """A byte data consumer and producer.

    The agent is a convenience base class which implements both a
    :class:`VByteProducer` and :class:`VByteConsumer` as full-duplex
    pair. The agent also includes a logger which interfaces with the
    reactor logger.

    :param reactor:    a reactor which provides services to the object
    :param log_prefix: if not None, prefix to use for object's logger
    :type  log_prefix: unicode

    """

    def __init__(self, reactor, log_prefix=None):
        VByteConsumer.__init__(self, reactor)
        VByteProducer.__init__(self, reactor)
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
    def byte_io(self):
        """Byte interface (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.byte_consume, self.byte_produce)

    @property
    def log(self):
        """A logger for the agent."""
        return self.__log

    @property
    def _bc_twoway(self):
        return True

    @property
    def _bc_reverse(self):
        return self.byte_produce

    @property
    def _bp_twoway(self):
        return True

    @property
    def _bp_reverse(self):
        return self.byte_consume


@abstract
@multiface
class VByteWAgent(VByteConsumer, VByteWriter):
    """A byte data consumer and producer.

    The agent is a convenience base class which implements both a
    :class:`VByteWriter` and :class:`VByteConsumer` as full-duplex
    pair. The agent also includes a logger which interfaces with the
    reactor logger.

    :param reactor:    a reactor which provides services to the object
    :param log_prefix: if not None, prefix to use for object's logger
    :type  log_prefix: unicode

    """

    def __init__(self, reactor, log_prefix=None):
        VByteConsumer.__init__(self, reactor)
        VByteWriter.__init__(self, reactor)
        self.__log = reactor.log.create_proxy_logger(prefix=log_prefix)

    @classmethod
    def simple_factory(cls, *args, **kargs):
        """Creates and returns a simple factory for the class.

        :param args:  arguments for constructor
        :param kargs: keyword arguments to constructor

        The returned factory has a method build() which will construct
        a :class:`VByteWAgent`\ . Each agent is constructed by
        calling cls(\*args, \*\*kargs).

        """
        class _AgentFactory(object):
            def build(self):
                return cls(*args, **kargs)
        return _AgentFactory()

    @property
    def byte_io(self):
        """Byte interface (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.byte_consume, self.byte_produce)

    @property
    def log(self):
        """A logger for the agent."""
        return self.__log

    @property
    def _bc_twoway(self):
        return True

    @property
    def _bc_reverse(self):
        return self.byte_produce

    @property
    def _bp_twoway(self):
        return True

    @property
    def _bp_reverse(self):
        return self.byte_consume


@implements(IVHalfClose)
class VHalfClosePolicy(object):
    """Policy for allowing I/O half-close.

    Some I/O channels such as sockets have the ability to half-close
    by shutting down one direction only. The policy object enables
    specifying for each direction whether half-close is allowed.

    """
    def __init__(self, half_in, half_out):
        """Set half-close policy for each direction

        :param half_in : if True allow half-close on input
        :param half_out: if True allow half-close on output

        """
        self.__half_in = half_in
        self.__half_out = half_out

    @property
    def half_in(self):
        """If True half-closing input is allowed."""
        return self.__half_in

    @property
    def half_out(self):
        """If True half-closing output is allowed."""
        return self.__half_out


class VHalfClose(VHalfClosePolicy):
    """Convenience class for policy allowing half-close in both directions."""
    def __init__(self):
        super(VHalfClose, self).__init__(True, True)


class VNoHalfClose(VHalfClosePolicy):
    """Convenience class for policy disallowing half-close entirely."""
    def __init__(self):
        super(VNoHalfClose, self).__init__(False, False)

class VHalfCloseInput(VHalfClosePolicy):
    """Convenience class for policy allowing half-close for input only."""
    def __init__(self):
        super(VHalfCloseInput, self).__init__(True, False)


class VHalfCloseOutput(VHalfClosePolicy):
    """Convenience class for policy allowing half-close for output only."""
    def __init__(self):
        super(VHalfCloseOutput, self).__init__(False, True)


@implements(IVByteConsumer)
class _VByteConsumer(object):
    def __init__(self, parent):
        self.__proxy = parent

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
    def __init__(self, parent):
        self.__proxy = parent

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
