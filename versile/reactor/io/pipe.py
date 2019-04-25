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

"""Components for reactor-driven pipe I/O."""
from __future__ import print_function, unicode_literals

import errno
import fcntl
import os
import sys
import weakref

from versile.internal import _b2s, _s2b, _vplatform, _vexport, _v_silent
from versile.internal import _pyver
from versile.common.iface import implements, abstract, final, peer
from versile.common.log import VLogger
from versile.common.peer import VPipePeer
from versile.common.util import VByteBuffer
from versile.reactor import IVReactorObject
from versile.reactor.io import VIOClosed
from versile.reactor.io import VIOCompleted, VIOLost, VIOError, VIOException
from versile.reactor.io import VFIOCompleted, VFIOLost, IVByteIO
from versile.reactor.io import IVSelectable, IVSelectableIO, IVByteInput
from versile.reactor.io import IVByteProducer, IVByteConsumer
from versile.reactor.io import VHalfClose, VNoHalfClose
from versile.reactor.io import VIOControl, VIOMissingControl
from versile.reactor.io.descriptor import IVDescriptor

__all__ = ['VPipeBase', 'VPipeReader', 'VPipeWriter', 'VPipeAgent']
__all__ = _vexport(__all__)

# Workaround for Windows-specific error codes
if sys.platform == _b2s(b'win32') or _vplatform == 'ironpython':
    _errno_block   = (errno.EWOULDBLOCK, errno.WSAEWOULDBLOCK)
    _errno_connect = (errno.EINPROGRESS, errno.WSAEWOULDBLOCK)
else:
    _errno_block = (errno.EWOULDBLOCK,)
    _errno_connect = (errno.EINPROGRESS,)


@abstract
@implements(IVReactorObject, IVDescriptor, IVSelectable)
class VPipeBase(object):
    """Base class for reactor-driven OS pipe I/O.

    :param reactor:     reactor handling socket events
    :param fd:          pipe file descriptor
    :type  fd:          int
    :param hc_pol:      half-close policy
    :type  hc_pol:      :class:`versile.reactor.io.VHalfClosePolicy`
    :param close_cback: callback when closed (or None)
    :type  close_cback: callable

    The pipe is set to a non-blocking mode.

    *hc_pol* determines whether the pipe allows closing only one
    direction if the pipe has a peer. If *hc_pol* is None an
    :class:`versile.reactor.io.VHalfClose` instance is used.

    The file descriptor is closed when this object is deleted.

    This class is abstract and should not be directly instantiated.

    """

    def __init__(self, reactor, fd, hc_pol=None, close_cback=None):
        self.__reactor = reactor
        fcntl.fcntl(fd, fcntl.F_SETFL, os.O_NONBLOCK) # Set fd nonblocking
        self._fd = fd
        self._peer = None # weak reference
        if hc_pol is None:
            hc_pol = VHalfClose()
        self.__hc_pol = hc_pol
        self._close_cback = close_cback
        self._sent_close_cback = False

        # Set up a socket logger for convenience
        self.__logger = VLogger(prefix='Pipe')
        self.__logger.add_watcher(self.reactor.log)

    def __del__(self):
        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError as e:
                _v_silent(e)
        if self._close_cback and not self._sent_close_cback:
            try:
                self._close_cback()
            except Exception as e:
                self.log.debug('Close callback failed')
                _v_silent(e)

    @abstract
    def set_pipe_peer(self, peer):
        """Sets a peer pipe object for a reverse pipe direction.

        :param peer: peer pipe
        :type  peer: :class:`VPipeBase`

        If registered a peer pipe is used with :meth:`close_io` and
        for resolving half-close policies.

        """
        raise NotImplementedError()

    @abstract
    def close_io(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandle.close_io`\ ."""
        raise NotImplementedError()

    def fileno(self):
        """See :meth:`versile.reactor.io.IVSelectable.fileno`\ ."""
        return self._fd

    @property
    def peer(self):
        """A peer pipe registered with :meth:`set_pipe_peer`\ ."""
        if self._peer:
            return self._peer()
        else:
            return None

    @property
    def reactor(self):
        """See :attr:`versile.reactor.IVReactorObject.reactor`\ ."""
        return self.__reactor

    @property
    def log(self):
        """Logger for the socket (:class:`versile.common.log.VLogger`\ )."""
        return self.__logger

    def _get_hc_pol(self): return self.__hc_pol
    def _set_hc_pol(self, policy): self.__hc_pol = policy
    __doc = 'See :meth:`versile.reactor.io.IVByteIO.half_close_policy`'
    half_close_policy = property(_get_hc_pol, _set_hc_pol, doc=__doc)
    del(__doc)


@abstract
class VPipeReader(VPipeBase):
    """Base class for OS pipe I/O for reading.

    For construction arguments see :class:`VPipeBase`\ .

    This class is abstract and should not be directly instantiated.

    """

    def __init__(self, reactor, fd, hc_pol=None, close_cback=None):
        s_init = super(VPipeReader, self).__init__
        s_init(reactor=reactor, fd=fd, hc_pol=hc_pol, close_cback=close_cback)
        self._in_closed = False
        self._in_closed_reason = None

    def set_pipe_peer(self, peer):
        if peer is not None and not isinstance(peer, VPipeWriter):
            raise VIOError('Peer must be a pipe writer')
        self._peer = weakref.ref(peer)

    def close_input(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandleInput.close_input`\ ."""
        if not self._in_closed:
            self.log.debug('read shutdown')
            try:
                os.close(self._fd)
            except OSError as e:
                _v_silent(e)
            finally:
                self._fd = -1
                self._in_closed = True
                self._in_closed_reason = reason
            self._input_was_closed(reason)
        if self.peer is not None or not self.half_close_policy.half_in:
            self.close_io(reason)

    def close_io(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandle.close_io`\ ."""
        if self._in_closed and self.peer is None:
            return
        if self.peer is not None:
            _peer, self._peer = self.peer, None
            if _peer:
                _peer.close_output(reason)
        if not self._in_closed:
            self.close_input()
        if self._close_cback and not self._sent_close_cback:
            try:
                self._close_cback()
            except Exception as e:
                self.log.debug('Close callback failed')
                _v_silent(e)
            finally:
                self._sent_close_cback = True
        return True

    @abstract
    def do_read(self):
        """See :meth:`versile.reactor.io.IVByteHandleInput.do_read`\ ."""
        raise NotImplementedError()

    def read_some(self, max_len):
        """See :meth:`versile.reactor.io.IVByteInput.read_some`"""
        if self._in_closed:
            if isinstance(self._in_closed_reason, VFIOCompleted):
                raise VIOCompleted()
            else:
                raise VIOLost()
        try:
            data = os.read(self._fd, max_len)
            if _pyver == 2:
                data = _s2b(data)
        except OSError as e:
            if e.errno in _errno_block:
                return b''
            else:
                self.log.debug('Read got errno %s' % e.errno)
                raise VIOError('Pipe read error')
        else:
            if data:
                return data
            else:
                self.log.debug('Pipe read error')
                raise VIOError('Pipe read error')

    def start_reading(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteInput.start_reading`\ ."""
        if not self._in_closed and self._fd >= 0:
            self.reactor.add_reader(self, internal=internal)

    @final
    def stop_reading(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteInput.start_reading`\ ."""
        if self._fd >= 0:
            self.reactor.remove_reader(self, internal=internal)

    def _input_was_closed(self, reason):
        """Callback when input is closed.

        Default does nothing, derived classes can override.

        """
        pass


@abstract
class VPipeWriter(VPipeBase):
    """Base class for OS pipe I/O for writing.

    For construction arguments see :class:`VPipeBase`\ .

    This class is abstract and should not be directly instantiated.

    """

    def __init__(self, reactor, fd, hc_pol=None, close_cback=None):
        s_init = super(VPipeWriter, self).__init__
        s_init(reactor=reactor, fd=fd, hc_pol=hc_pol, close_cback=close_cback)
        self._out_closed = False
        self._out_closed_reason = None

    def set_pipe_peer(self, peer):
        if peer is not None and not isinstance(peer, VPipeReader):
            raise VIOError('Peer must be a pipe writer')
        self._peer = weakref.ref(peer)

    def close_output(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandleOutput.close_output`\ ."""
        if not self._out_closed:
            self.log.debug('write shutdown')
            try:
                os.close(self._fd)
            except OSError as e:
                _v_silent(e)
            finally:
                self._fd = -1
                self._out_closed = True
                self._out_closed_reason = reason
            self._output_was_closed(reason)
        if self.peer is not None or not self.half_close_policy.half_out:
            self.close_io(reason)

    def close_io(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandle.close_io`\ ."""
        if self._out_closed and self.peer is None:
            return
        if self.peer:
            _peer, self._peer = self.peer, None
            if _peer:
                _peer.close_input(reason)
        if not self._out_closed:
            self.close_output()
        if self._close_cback and not self._sent_close_cback:
            try:
                self._close_cback()
            except Exception as e:
                self.log.debug('Close callback failed')
                _v_silent(e)
            finally:
                self._sent_close_cback = True
        return True

    @abstract
    def do_write(self):
        """See :meth:`versile.reactor.io.IVByteHandleOutput.do_write`\ ."""
        raise NotImplementedError()

    def write_some(self, data):
        """See :meth:`versile.reactor.io.IVByteOutput.write_some`\ ."""
        if self._out_closed:
            if isinstance(self._out_closed_reason, VFIOCompleted):
                raise VIOCompleted()
            else:
                raise VIOLost()
        try:
            if _pyver == 2:
                data = _b2s(data)
            num_written = os.write(self._fd, data)
        except OSError as e:
            if e.errno in _errno_block:
                return 0
            else:
                self.log.debug('Write got errno %s' % e.errno)
                raise VIOError('Pipe read error')
        else:
            if num_written > 0:
                return num_written
            else:
                self.log.debug('Pipe write error')
                raise VIOError('Pipe write error')

    @final
    def start_writing(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteOutput.start_writing`\ ."""
        if not self._out_closed and self._fd >= 0:
            self.reactor.add_writer(self, internal=internal)

    @final
    def stop_writing(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteOutput.stop_writing`\ ."""
        if self._fd >= 0:
            self.reactor.remove_writer(self, internal=internal)

    def _output_was_closed(self, reason):
        """Callback when input is closed.

        Default does nothing, derived classes can override.

        """
        pass


class _VAgentReader(VPipeReader):
    """Pipe reader for a :class:`VPipeAgent`\ ."""

    def __init__(self, agent, reactor, fd, hc_pol=None, close_cback=None):
        s_init = super(_VAgentReader, self).__init__
        s_init(reactor=reactor, fd=fd, hc_pol=hc_pol, close_cback=close_cback)
        self.__agent = weakref.ref(agent)

    def do_read(self):
        """See :meth:`versile.reactor.io.IVByteHandleInput.do_read`\ ."""
        if self.__agent:
            self.__agent()._do_read()

    def _input_was_closed(self, reason):
        try:
            self.__agent()._input_was_closed(reason)
        except Exception as e:
            _v_silent(e)


class _VAgentWriter(VPipeWriter):
    """Pipe writer for a :class:`VPipeAgent`\ ."""

    def __init__(self, agent, reactor, fd, hc_pol=None, close_cback=None):
        s_init = super(_VAgentWriter, self).__init__
        s_init(reactor=reactor, fd=fd, hc_pol=hc_pol, close_cback=close_cback)
        self.__agent = weakref.ref(agent)

    def do_write(self):
        """See :meth:`versile.reactor.io.IVByteHandleOutput.do_write`\ ."""
        if self.__agent:
            self.__agent()._do_write()

    def _output_was_closed(self, reason):
        try:
            self.__agent()._output_was_closed(reason)
        except Exception as e:
            _v_silent(e)


@implements(IVByteConsumer, IVByteProducer)
class VPipeAgent(object):
    """Byte producer/consumer interface to a pipe reader/writer pair.

    :param read_fd:   read pipe file descriptor
    :type  read_fd:   int
    :param write_fd:  write pipe file descriptor
    :type  write_fd:  int
    :param max_read:  max bytes fetched per pipe read
    :type  max_read:  int
    :param max_write: max bytes written per pipe write
    :type  max_write: int
    :param wbuf_len:  buffer size of data held for writing (or None)
    :type  wbuf_len:  int

    The agent creates a :class:`VPipeReader` and :class:`VPipeWriter`
    for the provided pipe read/write descriptors which it uses for
    reactor driven pipe I/O communication.

    *max_read* is also the maximum size of the buffer for data read
    from the socket (so maximum bytes read in one read operation is
    *max_read* minus the amount of data currently held in the receive
    buffer).

    If *wbuf_len* is None then *max_write* is used as the buffer size.

    """
    def __init__(self, reactor, read_fd, write_fd, max_read=0x4000,
                 max_write=0x4000,
                 wbuf_len=None):
        self.__reactor = reactor

        self._reader = _VAgentReader(self, reactor, read_fd)
        self._writer = _VAgentWriter(self, reactor, write_fd)
        self._reader.set_pipe_peer(self._writer)
        self._writer.set_pipe_peer(self._reader)

        self._max_read = max_read
        self._max_write = max_write
        self._wbuf = VByteBuffer()
        if wbuf_len is None:
            wbuf_len = max_write
        self._wbuf_len = wbuf_len

        self._ci = None
        self._ci_eod = False
        self._ci_eod_clean = None
        self._ci_producer = None
        self._ci_consumed = 0
        self._ci_lim_sent = 0
        self._ci_aborted = False

        self._pi = None
        self._pi_closed = False
        self._pi_consumer = None
        self._pi_produced = 0
        self._pi_prod_lim = 0
        self._pi_buffer = VByteBuffer()
        self._pi_aborted = False

    @property
    def byte_consume(self):
        """Holds a :class:`IVByteConsumer` interface to the pipe reader."""
        if not self._ci:
            ci = _VPipeConsumer(self)
            self._ci = weakref.ref(ci)
            return ci
        else:
            ci = self._ci()
            if ci:
                return ci
            else:
                ci = _VPipeConsumer(self)
                self._ci = weakref.ref(ci)
                return ci

    @property
    def byte_produce(self):
        """Holds a :class:`IVByteProducer` interface to the pipe writer."""
        if not self._pi:
            pi = _VPipeProducer(self)
            self._pi = weakref.ref(pi)
            return pi
        else:
            pi = self._pi()
            if pi:
                return pi
            else:
                pi = _VPipeProducer(self)
                self._pi = weakref.ref(pi)
                return pi

    @property
    def byte_io(self):
        """Byte interface (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.byte_consume, self.byte_produce)

    @property
    def reactor(self):
        """Holds the reactor of the associated reader."""
        return self.__reactor

    @peer
    def _c_consume(self, buf, clim):
        if self._ci_eod:
            raise VIOClosed('Consumer already reached end-of-data')
        elif not self._ci_producer:
            raise VIOError('No connected producer')
        elif self._ci_consumed >= self._ci_lim_sent:
            raise VIOError('Consume limit exceeded')
        elif not buf:
            raise VIOError('No data to consume')

        max_cons = self._wbuf_len - len(self._wbuf)
        max_cons = min(max_cons, self._ci_lim_sent - self._ci_consumed)
        if clim is not None and clim > 0:
            max_cons = min(max_cons, clim)

        was_empty = not self._wbuf
        indata = buf.pop(max_cons)
        self._wbuf.append(indata)
        self._ci_consumed += len(indata)
        if was_empty:
            self._writer.start_writing(internal=True)
        return self._ci_lim_sent

    def _c_end_consume(self, clean):
        if self._ci_eod:
            return
        self._ci_eod = True
        self._ci_eod_clean = clean

        if not self._wbuf:
            self._writer.close_output(VFIOCompleted())
            if self._ci_producer:
                self._ci_producer.abort()
                self._c_detach()

    def _c_abort(self):
        if not self._ci_aborted:
            self._ci_aborted = True
            self._ci_eod = True
            self._ci_consumed = self._ci_lim_sent = 0
            self._wbuf.clear()
            self._writer.close_output(VFIOCompleted())
            if self._ci_producer:
                self._ci_producer.abort()
                self._c_detach()

    def _c_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._c_attach, producer, rthread=True)
            return

        if self._ci_producer is producer:
            return
        elif self._ci_producer:
            raise VIOError('Producer already attached')

        self._ci_producer = producer
        self._ci_consumed = self._ci_lim_sent = 0
        producer.attach(self.byte_consume)
        self._ci_lim_sent = self._wbuf_len
        producer.can_produce(self._ci_lim_sent)

        # Notify attached chain
        try:
            producer.control.notify_consumer_attached(self.byte_consume)
        except VIOMissingControl:
            pass

    def _c_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._c_detach, rthread=True)
            return

        if self._ci_producer:
            prod, self._ci_producer = self._ci_producer, None
            prod.detach()
            self._ci_consumed =  self._ci_lim_sent = 0

    def _do_write(self):
        if self._wbuf:
            data = self._wbuf.peek(self._max_write)
            try:
                num_written = self._writer.write_some(data)
            except VIOException:
                self._c_abort()
            else:
                if num_written > 0:
                    self._wbuf.remove(num_written)
                    if self._ci_producer:
                        self._ci_lim_sent = (self._ci_consumed + self._wbuf_len
                                             - len(self._wbuf))
                        self._ci_producer.can_produce(self._ci_lim_sent)
                if not self._wbuf:
                    self._writer.stop_writing()
                    if self._ci_eod:
                        self._c_abort()
        else:
            self._writer.stop_writing()

    def _output_was_closed(self, reason):
        # No more output will be written, abort consumer
        self._c_abort()

    @property
    def _c_control(self):
        return VIOControl()

    @property
    def _c_producer(self):
        return self._ci_producer

    @property
    def _c_flows(self):
        return tuple()

    @property
    def _c_twoway(self):
        return True

    @property
    def _c_reverse(self):
        return self.byte_produce()

    @peer
    def _p_can_produce(self, limit):
        if not self._pi_consumer:
            raise VIOError('No connected consumer')

        if limit is None or limit < 0:
            if (not self._pi_prod_lim is None
                and not self._pi_prod_lim < 0):
                if self._pi_produced >= self._pi_prod_lim:
                    self._reader.start_reading(internal=True)
                self._pi_prod_lim = limit
        else:
            if (self._pi_prod_lim is not None
                and 0 <= self._pi_prod_lim < limit):
                if self._pi_produced >= self._pi_prod_lim:
                    self._reader.start_reading(internal=True)
                self._pi_prod_lim = limit

    def _p_abort(self):
        if not self._pi_aborted:
            self._pi_aborted = True
            self._pi_produced = self._pi_prod_lim = 0
            self._reader.close_input(VFIOCompleted())
            if self._pi_consumer:
                self._pi_consumer.abort()
                self._p_detach()

    def _p_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._p_attach, consumer, rthread=True)
            return

        if self._pi_consumer is consumer:
            return
        elif self._pi_consumer:
            raise VIOError('Consumer already attached')

        self._pi_produced = self._pi_prod_lim = 0
        self._pi_consumer = consumer
        consumer.attach(self.byte_produce)

        # Notify attached chain
        try:
            consumer.control.notify_producer_attached(self.byte_produce)
        except VIOMissingControl:
            pass

    def _p_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._p_detach, rthread=True)
            return

        if self._pi_consumer:
            cons, self._pi_consumer = self._pi_consumer, None
            cons.detach()
            self._pi_produced = self._pi_prod_lim = 0

    def _do_read(self):
        if not self._pi_consumer:
            self._reader.stop_reading()

        if self._pi_prod_lim is not None and self._pi_prod_lim >= 0:
            max_read = self._pi_prod_lim - self._pi_produced
        else:
            max_read = self._max_read
        max_read = min(max_read, self._max_read)
        if max_read <= 0:
            self._reader.stop_reading()
            return
        try:
            data = self._reader.read_some(max_read)
        except Exception as e:
            self._p_abort()
        else:
            self._pi_buffer.append(data)
            if self._pi_buffer:
                self.pi_prod_lim = self._pi_consumer.consume(self._pi_buffer)

    def _input_was_closed(self, reason):
        if self._pi_consumer:
            # Notify consumer about end-of-data
            clean = isinstance(reason, VFIOCompleted)
            self._pi_consumer.end_consume(clean)
        else:
            self._p_abort()

    @property
    def _p_control(self):
        class _Control(VIOControl):
            def __init__(self, obj):
                self._obj = obj
            def req_producer_state(self, consumer):
                # Send 'connected' notification if pipe is not closed
                def notify():
                    if (self._obj._reader._fd >= 0
                        and self._obj._writer._fd >= 0):
                        try:
                            consumer.control.connected(VPipePeer())
                        except VIOMissingControl:
                            pass
                self._obj.reactor.schedule(0.0, notify)
        return _Control(self)

    @property
    def _p_consumer(self):
        return self._pi_consumer

    @property
    def _p_flows(self):
        return tuple()

    @property
    def _p_twoway(self):
        return True

    @property
    def _p_reverse(self):
        return self.byte_consume()


@implements(IVByteConsumer)
class _VPipeConsumer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def consume(self, data, clim=None):
        return self.__proxy._c_consume(data, clim)

    @peer
    def end_consume(self, clean):
        return self.__proxy._c_end_consume(clean)

    def abort(self):
        return self.__proxy._c_abort()

    def attach(self, producer):
        return self.__proxy._c_attach(producer)

    def detach(self):
        return self.__proxy._c_detach()

    @property
    def control(self):
        return self.__proxy._c_control

    @property
    def producer(self):
        return self.__proxy._c_producer

    @property
    def flows(self):
        return self.__proxy._c_flows

    @property
    def twoway(self):
        return self.__proxy._c_twoway

    @property
    def reverse(self):
        return self.__proxy._c_reverse


@implements(IVByteProducer)
class _VPipeProducer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def can_produce(self, limit):
        return self.__proxy._p_can_produce(limit)

    def abort(self):
        return self.__proxy._p_abort()

    def attach(self, consumer):
        return self.__proxy._p_attach(consumer)

    def detach(self):
        return self.__proxy._p_detach()

    @property
    def control(self):
        return self.__proxy._p_control

    @property
    def consumer(self):
        return self.__proxy._p_consumer

    @property
    def flows(self):
        return self.__proxy._p_flows

    @property
    def twoway(self):
        return self.__proxy._p_twoway

    @property
    def reverse(self):
        return self.__proxy._p_reverse
