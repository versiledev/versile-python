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

"""Implements the :term:`VFE` specification."""
from __future__ import print_function, unicode_literals

from collections import deque
from decimal import Decimal
import operator
from threading import Lock
import traceback
import weakref

from versile.internal import _b2s, _s2b, _vexport, _b_ord, _b_chr, _pyver
from versile.common.iface import abstract
from versile.common.pending import VPending
from versile.common.util import VByteBuffer, VLockable
from versile.common.util import posint_to_netbytes, signedint_to_netbytes
from versile.common.util import netbytes_to_posint, netbytes_to_signedint
from versile.common.util import VLinearIDProvider, VResult
from versile.orb.const import VEntityCode
from versile.orb.error import VEntityError, VEntityReaderError
from versile.orb.error import VEntityWriterError

__all__ = ['VBoolean', 'VBooleanDecoder', 'VBytes', 'VBytesDecoder',
           'VCallContext', 'VCallError', 'VFloat', 'VFloatDecoder',
           'VEntity', 'VEntityDecoder', 'VEntityDecoderBase',
           'VEntityReader', 'VEntityWriter', 'VException',
           'VExceptionDecoder', 'VIOContext', 'VInteger',
           'VIntegerDecoder', 'VNone', 'VNoneDecoder', 'VObject',
           'VObjectCall', 'VObjectDecoder', 'VObjectIOContext', 'VProxy',
           'VReference', 'VReferenceCall', 'VReferenceDecoder',
           'VSimulatedException', 'VString', 'VStringDecoder', 'VTagged',
           'VTaggedDecoder', 'VTaggedParseError', 'VTaggedParseUnknown',
           'VTaggedParser', 'VTuple', 'VTupleDecoder']
__all__ = _vexport(__all__)


# Local reference to VSEResolver, tracked locally in order to
# avoid circular import references
_imported = False
_VSEResolver = None
_VArrayOfInt = None
_VArrayOfLong = None
_VArrayOfVInteger = None
_VArrayOfFloat = None
_VArrayOfDouble = None
_VArrayOfVFloat = None

def _import():
    global _imported
    if not _imported:
        global _VSEResolver
        from versile.vse import VSEResolver
        _VSEResolver = VSEResolver

        global _VArrayOfInt, _VArrayOfLong, _VArrayOfVInteger
        global _VArrayOfFloat, _VArrayOfDouble, _VArrayOfVFloat
        from versile.vse.container import VArrayOfInt, VArrayOfLong
        from versile.vse.container import VArrayOfVInteger, VArrayOfFloat
        from versile.vse.container import VArrayOfDouble, VArrayOfVFloat
        _VArrayOfInt, _VArrayOfLong = VArrayOfInt, VArrayOfLong
        _VArrayOfVInteger, _VArrayOfFloat = VArrayOfVInteger, VArrayOfFloat
        _VArrayOfDouble, _VArrayOfVFloat = VArrayOfDouble, VArrayOfVFloat

        _imported = True

def _meta_op1(oper, cast):
    """Convenience function to generate general operator f(a) overloads."""
    def perform_op(a):
        if isinstance(a, VEntity):
            a = a._v_value
        if cast:
            return VEntity._v_lazy(oper(a))
        else:
            return oper(a)
    return perform_op

def _meta_op2(oper, cast):
    """Covenience function to generate general operator f(a,b) overloads."""
    def perform_op(a, b):
        if isinstance(a, VEntity):
            a = a._v_value
        if isinstance(b, VEntity):
            b = b._v_value
        if cast:
            return VEntity._v_lazy(oper(a, b))
        else:
            return oper(a, b)
    return perform_op


class VEntityReader(object):
    """Reader for decoding a serialized VEntity.

    .. automethod:: __iter__

    """

    def __init__(self):
        """Set up the reader for decoding."""
        self.__lock = Lock()            # lock for method access
        self.__d_iterators = deque()    # decoder iterators, FIFO
        self.__h_decoder = None         # currently active header decoder
        self.__e_results = deque()      # embedded (interim) results, LIFO
        self.__p_decoder = None         # current payload processor
        self.__p_decoders = deque()     # payload processers, LIFO
        self.__num_decoders = 0         # number of initiated entity decoders
        self.__bytes_read = 0           # number of bytes read
        self.__len_payloads = 0         # header-reported length of payloads
        self.__buffer = VByteBuffer()   # buffer for use in read operations
        self.__initialized = False      # True if initialized with a decoder
        self.__result = None            # result of read operation
        self.__done = False             # True if finished and has result
        self.__failed = False           # indicates whether reader has failed

    def read(self, data):
        """Read input data.

        :param data: byte data to decode
        :type  data: bytes, :class:`versile.common.util.VByteBuffer`
        :returns:    number of bytes read
        :raises:     :exc:`versile.orb.error.VEntityReaderError`

        If data is received in a
        :class:`versile.common.util.VByteBuffer`\ , then the data that
        is read is also popped off the buffer.

        """
        self.__lock.acquire()
        try:
            if self.__failed:
                raise VEntityReaderError('Reader had an earlier failure')
            elif not self.__initialized:
                raise VEntityReaderError('Reader has no decoder')
            elif self.__done:
                raise VEntityReaderError('Reader is done')
            elif isinstance(data, bytes):
                self.__buffer.remove()
                self.__buffer.append(data)
                data = self.__buffer
            elif not isinstance(data, VByteBuffer):
                raise TypeError('Data must be bytes or VByteBuffer')

            try:
                bytes_read = 0

                # Process headers
                while self.__h_decoder or self.__d_iterators:
                    if not self.__h_decoder and self.__d_iterators:
                        try:
                            self.__h_decoder = next(self.__d_iterators[-1])
                        except StopIteration:
                            self.__d_iterators.pop()
                            continue
                    if not data:
                        break

                    decoder = self.__h_decoder
                    decode_result = decoder.decode_header(data)
                    num_decoded, done, min_obj, min_payload = decode_result
                    # NOTE - could check  ^--obj/bytes--^  limits here
                    bytes_read += num_decoded
                    if done:
                        self.__len_payloads += decoder.get_payload_len()
                        embedded_decoders = decoder.get_embedded_decoders()
                        if embedded_decoders:
                            dec_iter, num_dec = embedded_decoders
                            self.__d_iterators.append(dec_iter)
                            self.__num_decoders += num_dec
                        else:
                            num_dec = 0
                        p_decoder_entry = (decoder, num_dec)
                        self.__p_decoders.append(p_decoder_entry)
                        self.__h_decoder = None
                if self.__h_decoder or self.__d_iterators:
                    self.__bytes_read += bytes_read
                    return bytes_read

                # Process payloads
                while self.__p_decoder or self.__p_decoders:
                    if not self.__p_decoder:
                        payload_entry = self.__p_decoders.pop()
                        self.__p_decoder, num_embedded = payload_entry
                        if num_embedded > 0:
                            embedded = []
                            for i in xrange(num_embedded):
                                embedded.append(self.__e_results.pop())
                            self.__p_decoder.put_embedded_results(embedded)
                    decoder = self.__p_decoder
                    num_decoded, done = decoder.decode_payload(data)
                    bytes_read += num_decoded
                    if done:
                        self.__e_results.append(decoder.result())
                        self.__p_decoder = None
                    elif not data:
                        break
                if self.__p_decoder or self.__p_decoders:
                    self.__bytes_read += bytes_read
                    return bytes_read

                # Assemble and return final result
                if len(self.__e_results) != 1:
                    raise VEntityReaderError('Could not create result')
                self.__result = self.__e_results.popleft()
                self.__done = True

                self.__bytes_read += bytes_read
                return bytes_read
            except VEntityReaderError:
                self.__failed = True
                raise
            finally:
                self.__buffer.remove()
        finally:
            self.__lock.release()

    def done(self):
        """Returns True if entity decoding has finished.

        :returns: True if decode finished and result is ready
        :rtype:   bool

        When True is returned, :meth:`result` retreives the result.

        """
        self.__lock.acquire()
        try:
            if self.__failed:
                raise VEntityReaderError('Reader had an earlier failure')
            return self.__done
        finally:
            self.__lock.release()

    def result(self):
        """Returns the decoded object.

        :returns: decoded object
        :raises:  :exc:`versile.orb.error.VEntityReaderError`

        """
        self.__lock.acquire()
        try:
            if self.__failed:
                raise VEntityReaderError('Reader had an earlier failure')
            elif not self.__done:
                raise VEntityReaderError('Decoding not finished')
            return self.__result
        finally:
            self.__lock.release()

    def set_decoder(self, decoder):
        """Sets a decoder for the reader.

        :param decoder: if set, start reading with this as the decoder
        :type  decoder: :class:`VEntityDecoderBase`
        :raises:        :exc:`versile.orb.error.VEntityReaderError`

        If the reader has been used for decoding without calling
        :meth:`reset` afterwards, an exception is raised.

        """
        self.__lock.acquire()
        try:
            if self.__failed:
                raise VEntityReaderError('Reader had an earlier failure')
            elif self.__initialized:
                raise VEntityReaderError('Reader already decoding')
            self.__set_decoder(decoder)
        finally:
            self.__lock.release()

    def reset(self):
        """Resets the reader to a state as if it was newly constructed.

        .. note::

            The reset also clears any registered decoder. Before it us
            used for reading, a decoder must be set with
            :meth:`set_decoder`\ .

        """
        self.__lock.acquire()
        try:
            self.__d_iterators.clear()
            self.__h_decoder = None
            self.__e_results.clear()
            self.__p_decoder = None
            self.__p_decoders.clear()
            self.__num_decoders = 0
            self.__bytes_read = 0
            self.__len_payloads = 0
            self.__buffer.remove()
            self.__initialized = False
            self.__result = None
            self.__done = False
            self.__failed = False
        finally:
            self.__lock.release()

    @property
    def num_read(self):
        """Total bytes read since construction or last reset (int)."""
        return self.__bytes_read

    def __iter__(self):
        """Returns a generator which reads an entity from input data.

        :returns: generator for reading a :class:`VEntity`

        Generator takes bytes data as send() input. Each iteration
        yields a tuple (num_read, result). 'num_read' is the number of
        bytes that was read. If the entity is fully read then 'result'
        is set, otherwise it is None.

        """
        def generator():
            bytes_read = 0
            while not self.__done:
                data = yield (bytes_read, None)
                bytes_read = self.read(data)
            else:
                yield (bytes_read, self.__result)
        gen = generator()
        next(gen)
        return gen

    def __set_decoder(self, decoder):
        if not isinstance(decoder, VEntityDecoderBase):
            raise VEntityReaderError('Decoder must be a VEntityDecoderBase')
        elif self.__initialized:
            raise VEntityReaderError('Decoder was already initialized')
        self.__h_decoder = decoder
        self.__num_decoders = 1
        self.__initialized = True


class VIOContext(object):
    """I/O context for immutable :class:`VEntity` objects.

    The context defines serialization parameters for writing or
    reading serialized :class:`VEntity` data.

    .. note::

        :class:`VObject` and derived types require a
        :class:`VObjectIOContext` for object serialization I/O.

    """

    def __init__(self):
        self.__str_encoding = self.__str_decoding = None
        self.__mod_use_oid = True

    def set_codec(self, codec):
        """Sets :attr:`str_encoding` and :attr:`str_decoding`\ .

        :param codec: string codec for encoding and decoding
        :type  codec: bytes

        """
        self.str_encoding = codec
        self.str_decoding = codec

    def __get_str_encoding(self): return self.__str_encoding
    def __set_str_encoding(self, enc): self.__str_encoding = enc
    str_encoding = property(__get_str_encoding, __set_str_encoding, None)
    """Holds codec name for string encoding set on the context.

    The property can be get or set. If None (the default) then no
    string encoding scheme is defined on the context (and must be
    included in :class:`VString` serialization per individual
    object). If set then it is used as a default encoding.

    Encoding scheme is a bytes value. Typically b'utf8' is used.

    """

    def __get_str_decoding(self): return self.__str_decoding
    def __set_str_decoding(self, dec): self.__str_decoding = dec
    str_decoding = property(__get_str_decoding, __set_str_decoding, None)
    """Holds codec name for string decoding set on the context.

    The property can be get or set. If None (the default) then no
    string decoding scheme is defined on the context (and must be
    included in :class:`VString` serialization per individual
    object). If set then it is used as the default codec for decoding
    :class:`VString` objects which do not specify a codec.

    Decoding scheme is a bytes value. Typically b'utf8' is used.

    """

    def __get_mod_use_oid(self): return self.__mod_use_oid
    def __set_mod_use_oid(self, use): self.__mod_use_oid = use
    mod_use_oid = property(__get_mod_use_oid, __set_mod_use_oid, None)
    """If True use OID as default when encoding module-registered entities."""


class VObjectIOContext(VIOContext):
    """I/O context for any :class:`VEntity` including :class:`VObject`\ .

    An object I/O context includes methods for managing an ID space
    for the serialization for the context, both for local references
    to :class:`VObject` and for :class:`VReference` references to
    remote objects.

    The default :class:`VObjectIOContext` implementation implements an
    ID space for objects, however it does not implement behavior for
    :meth:`_ref_deref`. To handle dereference notifications, the
    method must be overridden in a derived class.

    .. automethod:: _local_to_peer_id
    .. automethod:: _local_from_peer_id
    .. automethod:: _local_add_send
    .. automethod:: _ref_from_peer_id
    .. automethod:: _ref_add_recv
    .. automethod:: _ref_deref
    .. automethod:: _create_ref

    """
    def __init__(self):
        super(VObjectIOContext, self).__init__()
        self._local_obj = dict()     # peer_id -> (VObject, send_count)
        self._local_p_ids = dict()   # VObject -> peer_id
        self._local_lock = Lock()

        self._peer_id_provider = VLinearIDProvider()
        self._peer_obj = dict()      # peer_id -> (weak(VRef), recv_count)
        self._peer_lock = Lock()

    def _local_to_peer_id(self, obj, lazy=False):
        """Returns peer ID for a local :class:`VObject`\ .

        :param obj:  object to generate ID for
        :type  obj:  :class:`VObject`
        :param lazy: if True lazy-create an ID for the object
        :type  lazy: bool
        :returns:    peer id
        :rtype:      int, long
        :raises:     :exc:`versile.orb.error.VEntityError`

        If the object is not local in this context (because it
        references an object on the peer side), an exception is
        raised.

        If 'lazy' is True and the object does not have a prior ID
        registered, this will register the object and create an
        ID. Note that after registration the object will have zero
        send count, and the caller is responsible or adding a send
        with :meth:`_add_send`\ .

        The method is intended for internal use and should normally
        not be invoked directly by an application.

        """
        if isinstance(obj, VObject):
            if isinstance(obj, VReference) and obj._v_context is self:
                raise VEntityError('Not a local object in this context')
        else:
            raise VEntityError('Object must be a VObject')

        self._local_lock.acquire()
        try:
            peer_id = self._local_p_ids.get(obj, None)
            if not peer_id:
                if lazy:
                    peer_id = self._peer_id_provider.get_id()
                    self._local_p_ids[obj] = peer_id
                    self._local_obj[peer_id] = (obj, 0)
                else:
                    raise VEntityError('Could not retreive object for peer_id')
            return peer_id
        finally:
            self._local_lock.release()

    def _local_from_peer_id(self, peer_id):
        """Returns the local :class:`VObject` corresponding to a peer ID.

        :param peer_id: peer ID of the object
        :type  peer_id: int, long
        :returns:       :class:`versile.orb.entity.VObject`
        :raises:        :exc:`versile.orb.error.VEntityError`

        Raises an exception if the object could not be referenced from
        the peer ID.

        The method is intended for internal use and should normally
        not be invoked directly by an application.

        """
        self._local_lock.acquire()
        try:
            entry = self._local_obj.get(peer_id, None)
            if not entry:
                raise VEntityError('No object matching peer ID')
            obj, send_count = entry
            return obj
        finally:
            self._local_lock.release()

    def _local_add_send(self, peer_id):
        """Increases the send count for a local :class:`VObject`\ .

        :param peer_id: the peer ID of the local :class:`VObject`
        :type  peer_id: int, long
        :raises:        :exc:`versile.orb.error.VEntityError`

        If the object is not local in this context (because it
        references an object on the peer side), an exception is
        raised. An exception is also raised if the object is not
        registered as a local object in this context.

        The method is intended for internal use and should normally
        not be invoked directly by an application.

        """
        self._local_lock.acquire()
        try:
            entry = self._local_obj.get(peer_id, None)
            if not entry:
                raise VEntityError('Peer id not registered')
            obj, send_count = entry
            self._local_obj[peer_id] = (obj, send_count+1)
        finally:
            self._local_lock.release()

    def _ref_from_peer_id(self, peer_id, lazy=False):
        """Returns a peer object reference for a given peer object ID.

        :param peer_id: the ID of the peer object
        :type  peer_id: int, long
        :param lazy:    if True lazy-creates :class:`VReference` for peer id
        :type  lazy:    bool
        :returns:       :class:`versile.orb.entity.VReference`
        :raises:        :exc:`versile.orb.error.VEntityError`

        .. note::

            If lazy-created, the object will be created with a receive
            count of zero and the caller is responsible for calling
            :meth:`_ref_add_recv`\ .

        Raises an exception if 'lazy' is False and the peer id is not
        registered.

        The method is intended for internal use and should normally
        not be invoked directly by an application.

        """
        self._peer_lock.acquire()
        try:
            entry = self._peer_obj.get(peer_id, None)
            if entry:
                w_ref, recv_count = entry
                obj = w_ref()
                if not obj:
                    # Local reference garbage collected while new copies in
                    # transit; resolve by creating a new local VReference
                    obj = self._create_ref(peer_id)
                    self._peer_obj[peer_id] = (weakref.ref(obj), recv_count)
            if not entry:
                if lazy:
                    obj = self._create_ref(peer_id)
                    self._peer_obj[peer_id] = (weakref.ref(obj), 0)
                else:
                    raise VEntityError('Peer id not registered')
            return obj
        finally:
            self._peer_lock.release()

    def _ref_add_recv(self, peer_id):
        """Increases the receive count for a peer object.

        :param peer_id: peer object reference
        :type  peer_id: int, long
        :raises:        :exc:`versile.orb.error.VEntityError`

        Raises an exception if the object is not registered or if the
        object is not local in this context.

        The method is intended for internal use and should normally
        not be invoked directly by an application.

        """
        self._peer_lock.acquire()
        try:
            entry = self._peer_obj.get(peer_id, None)
            if not entry:
                raise VEntityError('Peer id not registered')
            w_ref, recv_count = entry
            self._peer_obj[peer_id] = (w_ref, recv_count+1)
        finally:
            self._peer_lock.release()

    def _ref_deref(self, peer_id):
        """Notifies the context a remote object is no longer referenced.

        :param peer_id: peer object reference
        :type  peer_id: int, long

        The default implementation does nothing. Derived classes can
        override to handle dereference notifications.

        The method is intended for internal use and should normally
        not be invoked directly by an application.

        """
        pass

    def _create_ref(self, peer_id):
        """Instantiate a reference for a peer ID on this context.

        :param peer_id:  the remote object's serialized object ID
        :type  peer_id:  int, long
        :returns:        reference
        :rtype:          :class:`VReference`

        Default constructs a :class:`VReference`\ , derived classes
        can instantiate sub-classes of :class:`VReference`\ .

        """
        return VReference(self, peer_id)


@abstract
class VEntityDecoderBase(object):
    """Decoder for serialized :class:`VEntity` data.

    The decoder decodes an entity or a the top level header/payload
    data of a composite object. For composite objects it relies on
    external code to perform decoding of embedded data. Such decoded
    is implemented by :class:`VEntityReader`\ .

    :param context: context for :class:`VEntity` I/O
    :type  context: :class:`VIOContext`
    :param explicit: if True decode an explicit encoding
    :type  explicit: bool

    """
    def __init__(self, context, explicit=True):
        self.__context = context

    @abstract
    def decode_header(self, data):
        """Decodes header data.

        :param data: byte data to decode
        :type  data: :class:`versile.common.util.VByteBuffer`
        :returns:    (num_read, done, min_obj, min_payload)

        * 'num_read' is the number of bytes read (data read is also popped
          off the data buffer)
        * 'done' is True if header decoding was completed
        * 'min_obj' estimates the minimum number of objects decoding will
          generate
        * 'min_payload' estimates the minimum number of payload bytes
          that will be generated.

        The 'min_obj' and 'min_payload' values are exact once the
        header has been fully decoded. The reason why they are
        provided during decoding is because it allows estimating
        overflow situations ahead of time.

        """
        raise NotImplementedError()

    @abstract
    def get_payload_len(self):
        """Returns payload length as defined by the header.

        :returns: payload length (in bytes)
        :raises:  :exc:`versile.orb.error.VEntityReaderError`

        Should only be called after the header was fully read,
        otherwise an exception is raised.

        """
        raise NotImplementedError()

    @abstract
    def get_embedded_decoders(self):
        """Returns an iterator which generates decoders for embedded entities.

        :returns: (iter(decoder), num_decoders) *or* None
        :raises:  :exc:`versile.orb.error.VEntityReaderError`

        Should return None if there are no embedded entities to
        decode. Should only be called after header was fully read,
        otherwise will raise an exception.

        .. note::

            Results of processing embedded decoders must be passed back to
            this decoder with :meth:`put_embedded_results`\ .

        """
        raise NotImplementedError()

    @abstract
    def put_embedded_results(self, result):
        """Feeds result of decoders for embedded entity data.

        :param result: processed decoded results for received decoders
        :type  result: list(:class:`VEntity`\ )

        Should only be called after retreiving decoders with
        method:`get_embedded_decoders` and should only be called once.

        """
        raise NotImplementedError()

    @abstract
    def decode_payload(self, data):
        """Decodes the payload component of a the entity's encoding.

        :param data: byte data to decode
        :type  data: :class:`versile.common.util.VByteBuffer`
        :returns:    (num_read, done)
        :raises:     :exc:`versile.orb.error.VEntityReaderError`

        * 'num_read' is number of bytes read (data read is popped off
          the buffer)
        * 'done' is True if payload parsing was completed

        Should only be called after header has been decoded and
        embedded results have been resolved.

        The method must accept an empty buffer as a valid input.

        """
        raise NotImplementedError()

    @abstract
    def result(self):
        """Returns a :class:`VEntity` that has been fully decoded.

        :returns: decoded result
        :rtype:   :class:`VEntity`
        :raises:  :class:`versile.orb.error.VEntityReaderError`

        Raises an exception if result is not available

        """
        raise NotImplementedError()

    @property
    def context(self):
        """Holds the :class:`VIOContext` which is set on the object."""
        return self.__context


class VEntityWriter(object):
    """Writer which serializes a :class:`VEntity` as byte data.

    :param context:  entity I/O context
    :type  context:  :class:`VIOContext`
    :param explicit: if True use explicit encoding
    :type  explicit: bool

    .. automethod:: __iter__

    """

    def __init__(self, context, explicit=True):
        self.__lock = Lock()
        self.__context = context
        self.__explicit = explicit
        self.__entity = None
        self.__buffer = VByteBuffer()
        self.__initialized = False
        self.__failed = False

    def write(self, num_bytes=None):
        """Generate and return the next data for the serialized encoding.

        :param num_bytes: max number of bytes to write
        :type  num_bytes: int
        :returns:         serialized byte data
        :rtype:           bytes
        :raises:          :exc:`versile.orb.error.VEntityWriterError`

        If num_bytes is negative or None then all remaining data is
        written. If all serialized data has previously been written
        then b'' is returned.

        The method returns the maximum amount of data that can be
        generated.

        """
        self.__lock.acquire()
        try:
            if self.__failed:
                raise VEntityWriterError('Writer had an earlier failure')
            elif not self.__initialized:
                raise VEntityWriterError('Writer not initialized')
            if num_bytes is not None and num_bytes >= 0:
                return self.__buffer.pop(num_bytes)
            else:
                return self.__buffer.pop()
        finally:
            self.__lock.release()

    def done(self):
        """Return True if entity has been fully written

        :returns: True if entity was fully written
        :rtype:   bool
        :raises:  :exc:`versile.orb.error.VEntityWriterError`

        """
        self.__lock.acquire()
        try:
            if self.__failed:
                raise VEntityWriterError('Writer had an earlier failure')
            elif not self.__initialized:
                raise VEntityWriterError('Writer not initialized')
            return not self.__buffer
        finally:
            self.__lock.release()

    def reset(self):
        """Reset the writer to a state as if it was newly constructed.

        Aborts any ongoing writing and dereferences any current
        results or interim data.

        """
        self.__lock.acquire()
        try:
            self.__entity = None
            self.__initialized = False
            self.__failed = False
            self.__buffer.remove()
        finally:
            self.__lock.release()

    def set_entity(self, entity):
        """Set a :class:`VEntity` to decode.

        :param entity: entity to encode
        :type  entity: :class:`VEntity`
        :raises:       :exc:`versile.orb.error.VEntityWriterException`

        If the writer is already initialized with another entity then
        an exception is raised. To reuse the writer it must be
        :meth:`reset` first.

        """
        self.__lock.acquire()
        try:
            if self.__failed:
                raise VEntityWriterError('Writer had an earlier failure')
            elif self.__initialized:
                raise VEntityWriterError('Writer already active')
            self.__set_entity(entity)
        finally:
            self.__lock.release()

    def __iter__(self):
        """Returns a generator for serialized :class:`VEntity` data.

        :returns: generator for writing serialized data

        The returned generator takes num_bytes as send() input and
        yields up to num_bytes of bytes data per iteration. When the
        iterator completes (and if no exceptions have been raised),
        then the entity has been fully written.

        """
        def generator():
            data = b''
            while not self.done():
                num_bytes = yield data
                data = self.write(num_bytes)
            else:
                yield data
        gen = generator()
        next(gen)
        return gen

    def __set_entity(self, entity):
        if not isinstance(entity, VEntity):
            raise VEntityWriterError('Object must be a VEntity')
        elif self.__initialized:
            raise VEntityWriterError('Decoder was already initialized')

        # Perform entity encoding
        h_data = deque()
        p_data = deque()
        embedded = deque()
        embedded.appendleft((entity, self.__explicit))
        while embedded:
            obj, explicit = embedded.popleft()
            header, emb, payload = obj._v_encode(context=self.__context,
                                              explicit=explicit)
            for data in header:
                h_data.append(data)
            payload.reverse()
            for data in payload:
                p_data.appendleft(data)
            emb.reverse()
            for e in emb:
                embedded.appendleft(e)
        self.__buffer.remove()
        for data in h_data:
            self.__buffer.append(data)
        for data in p_data:
            self.__buffer.append(data)
        self.__entity = entity
        self.__initialized = True


@abstract
class VEntity(object):
    """Base class for data types of the :term:`VP` VEntity specification.

    See :ref:`lib_entities` for an overview of general usage.

    .. automethod:: _v_lazy
    .. automethod:: _v_lazy_native
    .. automethod:: _v_converter
    .. automethod:: _v_top_converter
    .. automethod:: _v_native_converter
    .. automethod:: _v_top_native_converter
    .. automethod:: _v_native
    .. automethod:: _v_encode
    .. automethod:: _v_decoder
    .. automethod:: _v_writer
    .. automethod:: _v_write
    .. automethod:: _v_reader

    """

    @classmethod
    def _v_lazy(cls, obj, parser=None):
        """Performs lazy conversion of obj to a VEntity object.

        :param obj:    object to convert
        :param parser: parser for :term:`VER` encoded entities (or None)
        :type  parser: :class:`versile.orb.module.VTaggedParser`
        :returns:      lazy-converted object
        :rtype:        :class:`VEntity`
        :raises:       :exc:`exceptions.TypeError`

        The following type conversions apply:

        +-------------------------+---------------------+
        | From                    | To                  |
        +=========================+=====================+
        | :class:`VEntity`        | :class:`VEntity`    |
        +-------------------------+---------------------+
        | bool                    | :class:`VBoolean`   |
        +-------------------------+---------------------+
        | bytes                   | :class:`VBytes`     |
        +-------------------------+---------------------+
        | float                   | :class:`VFloat`     |
        +-------------------------+---------------------+
        | int, long               | :class:`VInteger`   |
        +-------------------------+---------------------+
        | None                    | :class:`VNone`      |
        +-------------------------+---------------------+
        | unicode                 | :class:`VString`    |
        +-------------------------+---------------------+
        | tuple                   | :class:`VTuple`     |
        +-------------------------+---------------------+

        Example conversion:

        >>> from versile.orb.entity import *
        >>> VEntity._v_lazy(u'Runny cheese')
        u'Runny cheese'
        >>> type(_)
        <class 'versile.orb.entity.VString'>

        """
        if isinstance(obj, VEntity):
            return obj

        class Node:
            def __init__(self, items, parent, parent_index, aggregator):
                self.items = items
                self.unprocessed_index = 0
                self.parent = parent
                self.parent_index = parent_index
                self.aggregator = aggregator

        node = Node([obj], None, None, lambda l : l[0])
        while True:
            if node.unprocessed_index<len(node.items):
                index = node.unprocessed_index
                node.unprocessed_index = node.unprocessed_index+1
                obj = node.items[index]
                f, obj_split = cls._v_top_converter(obj, parser)
                if f is None:
                    # Object was fully converted in obj_split[0]
                    node.items[index] = obj_split[0]
                else:
                    # Create a new tree level for converting object
                    node.unprocessed_index = index
                    new_node = Node(obj_split, node, index, f)
                    node = new_node
            elif node.parent:
                # Delete node and go back up one level
                converted = node.aggregator(node.items)
                parent = node.parent
                parent_index = node.parent_index
                del(node)
                node = parent
                node.items[parent_index] = converted
                node.unprocessed_index = node.unprocessed_index+1
            else:
                # We are done, perform final conversion and break
                result = node.aggregator(node.items)
                break
        return result


    @classmethod
    def _v_lazy_native(cls, obj, parser=None):
        """Attempts conversion of a :class:`VEntity` to a native type.

        :param obj:      object to convert
        :type  obj:      :class:`VEntity`
        :param parser:   a :class:`VTagged` object decode parser
        :type  parser:   :class:`VTaggedParser`
        :returns:        converted obj, or obj if conversion not possible

        If the object cannot be converted or if obj is not a
        :class:`VEntity`\ , obj is returned. This is the case e.g. for
        classes that do not have a native representation such as
        :class:`VLocal`\ , :class:`VProxy` or :class:`VTagged`\ .

        >>> from versile.orb.entity import *
        >>> s = VString(u'Favourite color')
        >>> type(s)
        <class 'versile.orb.entity.VString'>
        >>> VEntity._v_lazy_native(s)
        u'Favourite color'
        >>> type(_)
        <type 'unicode'>

        """
        class Node:
            def __init__(self, items, parent, parent_index, aggregator):
                self.items = items
                self.unprocessed_index = 0
                self.parent = parent
                self.parent_index = parent_index
                self.aggregator = aggregator

        node = Node([obj], None, None, lambda l : l[0])
        while True:
            if node.unprocessed_index<len(node.items):
                index = node.unprocessed_index
                node.unprocessed_index = node.unprocessed_index+1
                obj = node.items[index]
                f, obj_split = cls._v_top_native_converter(obj, parser)
                if f is None:
                    # Object was fully converted in obj_split[0]
                    node.items[index] = obj_split[0]
                else:
                    # Create a new tree level for converting object
                    node.unprocessed_index = index
                    new_node = Node(obj_split, node, index, f)
                    node = new_node
            elif node.parent:
                # Traverse back one level, deleting leaf node
                converted = node.aggregator(node.items)
                parent = node.parent
                parent_index = node.parent_index
                del(node)
                node = parent
                node.items[parent_index] = converted
                node.unprocessed_index = node.unprocessed_index+1
            else:
                # We are done, perform final conversion and break
                result = node.aggregator(node.items)
                break
        return result

    @classmethod
    def _v_lazy_parse(cls, obj, parser=None):
        """Performs parsing on a :class:`VEntity`.

        :param obj:      object to parse
        :type  obj:      :class:`VEntity`
        :param parser:   a :class:`VTagged` object decode parser
        :type  parser:   :class:`VTaggedParser`
        :returns:        parsed obj

        Traverses *obj*, attempting conversion of :class:`VTagged`
        objects with *parser*.

        """
        class Node:
            def __init__(self, items, parent, parent_index, aggregator):
                self.items = items
                self.unprocessed = set(range(len(items)))
                self.parent = parent
                self.parent_index = parent_index
                self.aggregator = aggregator

        node = Node([obj], None, None, lambda l : l[0])
        while True:
            if node.unprocessed:
                index = node.unprocessed.pop()
                obj = node.items[index]
                f, obj_split = cls._v_parse_converter(obj, parser)
                if f is None:
                    # Object was fully converted in obj_split[0]
                    node.items[index] = obj_split[0]
                else:
                    # Create a new tree level for converting object
                    node.unprocessed.add(index)
                    new_node = Node(obj_split, node, index, f)
                    node = new_node
            elif node.parent:
                # Traverse back one level, deleting leaf node
                converted = node.aggregator(node.items)
                parent = node.parent
                parent_index = node.parent_index
                del(node)
                node = parent
                node.items[parent_index] = converted
                node.unprocessed.discard(parent_index)
            else:
                # We are done, perform final conversion and break
                result = node.aggregator(node.items)
                break
        return result

    @abstract
    @classmethod
    def _v_converter(cls, obj):
        """Returns a converter for lazy-converting to :class:`VEntity`

        :param obj: the object to convert
        :returns:   (f, obj_list)

        *obj_list* is a list of objects which should be individually
        converted in additional conversion. *f* is a function to
        aggregate the list of converted objects into the final
        conversion result. If *f* is None then no further conversion
        is needed, and *obj_list* instead holds the item which should
        be used.

        This method is intended for internal use by :term:`VPy`\ .

        """
        raise NotImplementedError()

    @classmethod
    def _v_top_converter(cls, obj, parser):
        """Returns a converter for lazy-converting to :class:`VEntity`

        :param obj:    the object to convert
        :param parser: parser for :term:`VER` encoded entities (or None)
        :type  parser: :class:`versile.orb.module.VTaggedParser`
        :returns:      (f, obj_list)
        :raises:       :exc:`exceptions.TypeError`

        *obj_list* is a list of objects which should be individually
        converted in additional conversion. *f* is a function to
        aggregate the list of converted objects into the final
        conversion result. If *f* is None then no further conversion
        is needed, and *obj_list* instead holds the item which should
        be used.

        This method is intended for internal use by :term:`VPy`\ .

        """
        if isinstance(obj, VEntity):
            return (None, [obj])

        # Get default converter
        converter = _VENTITY_LAZY_CONVERTER.get(type(obj), None)

        # Handle tuples as a special case, due to possible
        # lazy array conversion
        if isinstance(obj, tuple):
            # Ensure VSEResolver and VArrayOf types are loaded
            global _import
            _import()

            global _VSEResolver
            if _VSEResolver.lazy_arrays():
                # Lazy array conversion is enabled, inspect tuple
                # elements for the appropriate elements
                _int = _vinteger = _float = _vfloat = False
                for o in obj:
                    # This test is needed because python evaluates
                    # isinstance(True, int) and isinstance(False, int)
                    # as 'True'
                    if isinstance(o, bool):
                        break

                    if _pyver == 2:
                        if isinstance(o, (int, long)):
                            _int = True
                            continue
                    else:
                        if isinstance(o, int):
                            _int = True
                            continue
                    if isinstance(o, float):
                        _float = True
                    elif isinstance(o, VInteger):
                        _vinteger = True
                    elif isinstance(o, VFloat):
                        _vfloat = True
                    else:
                        break
                else:
                    # No elements of known non-matching type, attempt
                    # VSE array conversion

                    # Hold converted type, if any
                    _lazy = None

                    if _vinteger:
                        # Convert to native type
                        def _conv(item):
                            if isinstance(item, VInteger):
                                return item._v_native()
                            else:
                                return item
                        obj = tuple(_conv(o) for o in obj)
                        _int = True

                    if _int and (_float or _vfloat):
                        # If mixed int/float, handle as floating point
                        # based type
                        _int = False

                    if _int:
                        # Integer based encoding
                        _long = False
                        _big = False
                        for o in obj:
                            if not (-0x80000000 <= o <= 0x70000000):
                                _long = True
                            if (o < -0x8000000000000000 or
                                o > 0x7000000000000000):
                                _big = True
                                break
                        if _big:
                            global _VArrayOfVInteger
                            _lazy = _VArrayOfVInteger(obj)
                        elif _long:
                            global _VArrayOfLong
                            _lazy = _VArrayOfLong(obj)
                        else:
                            global _VArrayOfInt
                            _lazy = _VArrayOfInt(obj)
                    else:
                        # If any VFloat, attempt lazy-conversion
                        if _vfloat:
                            def _conv(item):
                                if isinstance(item, VFloat):
                                    return item._v_native()
                                else:
                                    return item
                            obj = tuple(_conv(o) for o in obj)

                        # Attempt VArrayOfDouble encoding
                        try:
                            global _VArrayOfDouble
                            _lazy = _VArrayOfDouble(obj)
                        except TypeError:
                            # Attempt VArrayOfFloat encoding
                            try:
                                global _VArrayOfVFloat
                                _lazy = _VArrayOfVFloat(obj)
                            except TypeError:
                                pass

                    # If a VSE array type was generated, return a
                    # converter for it
                    if _lazy is not None:
                        return (lambda x: x[0], [_lazy])

        if converter:
            return converter(obj)
        if parser:
            try:
                return parser.converter(obj)
            except:
                raise TypeError('Parser could not lazy-convert')
        raise TypeError('Could not lazy-convert')

    @classmethod
    def _v_parse_converter(cls, obj, parser):
        """Returns a converter for parsing a :class:`VEntity`

        :param obj:    the object to parse
        :param parser: parser for :term:`VER` encoded entities (or None)
        :type  parser: :class:`versile.orb.module.VTaggedParser`
        :returns:      (f, obj_list)
        :raises:       :exc:`exceptions.TypeError`

        Similar return value as :meth:`_v_top_native_converter`\
        . This method is intended for internal use by :term:`VPy`\ .

        """
        if isinstance(obj, VTuple):
            return (VTuple, [e for e in obj])
        elif isinstance(obj, VException):
            def _parse(args):
                return VException(*args)
            return (_parse, [e for e in obj._v_value])
        elif isinstance(obj, VTagged):
            if parser:
                try:
                    decoder = parser.decoder(obj)
                except:
                    return (None, [obj])
                else:
                    return decoder
            else:
                return (None, [obj])
        elif isinstance(obj, VEntity):
            return (None, [obj])
        else:
            raise TypeError('Requires VEntity')

    def _v_native_converter(self):
        """Returns a converter for converting the entity to native type.

        :returns: (f, obj_list)

        *obj_list* is a list of objects which should be individually
        converted in additional conversion. *f* is a function to
        aggregate the list of converted objects into the final
        conversion result. If *f* is None then no further conversion
        is needed, and *obj_list* instead holds the item which should
        be used.

        This method is intended for internal use by :term:`VPy`\ .

        Default provides return values for a conversion which just
        references the entity itself. Derived classes can override.

        """
        return (None, [self])

    @classmethod
    def _v_top_native_converter(cls, obj, parser=None):
        """Returns a converter for converting an object to native type.

        :param obj:      the object to convert
        :param parser:   a :class:`VTagged` object parser
        :type  parser:   :class:`VTaggedParser`
        :returns:        (f, obj_list)

        *obj_list* is a list of objects which should be individually
        converted in additional conversion. *f* is a function to
        aggregate the list of converted objects into the final
        conversion result. If *f* is None then no further conversion
        is needed, and *obj_list* instead holds the item which should
        be used.

        This method is intended for internal use by :term:`VPy`\ .

        """
        if isinstance(obj, VEntity):
            if isinstance(obj, VTagged) and parser:
                try:
                    # Parse to a native representation
                    f, args = parser.native_decoder(obj)
                except Exception as e:
                    return obj._v_native_converter()
                else:
                    return (f, args)
            else:
                return obj._v_native_converter()
        elif isinstance(obj, list):
            return (list, list(obj))
        elif isinstance(obj, tuple):
            return (tuple, list(obj))
        else:
            return (None, [obj])

    def _v_native(self, deep=True):
        """Returns a platform-specific representation of the entity.

        :param deep: if False will not traverse composite entity structures
        :type  deep: bool
        :returns:    native platform representation of entity

        Derived classes which cannot be converted are left as-is.

        """
        if deep:
            return self._v_lazy_native(self)
        else:
            f, obj_list = self._v_native_converter()
            return f(obj_list)

    @abstract
    def _v_encode(self, context, explicit=True):
        """Return the outer layer of the object's serialized byte encoding.

        :param context:  I/O context
        :type  context:  :class:`VIOContext`
        :param explicit: if True use explicit serialized encoding
        :type  explicit: bool
        :returns:        (header, (embedded_obj, explicit), payload)
        :rtype:          ((bytes,), ((:class:`VEntity`\ , bool),), (bytes,))

        This method is intended for internal use by :term:`VPy`\
        . Programs should normally use :meth:`_v_write` or
        :meth:`_v_writer` to generate serialized data.

        """
        raise NotImplementedError()

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        """Returns a decoder for the class' serialized representation.

        :param context:  I/O context for decoding
        :type  context:  :class:`VIOContext`
        :param explicit: if True decode explicit serialized representation
        :type  explicit: bool
        :returns:        decoder
        :rtype:          :class:`VEntityDecoderBase`
        :raises:         :exc:`versile.orb.error.VEntityReaderError`

        This method is intended for internal use by :term:`VPy`\
        . Programs should normally create use
        :meth:`VEntity._v_reader` to instantiate a reader for
        reconstructing an entity from serialized data, or instantiate
        a :class:`VEntityReader` of the appropriate type.

        """
        if not explicit:
            raise VEntityReaderError('VEntity level decoder must be explicit')
        return VEntityDecoder(context)

    def _v_writer(self, context, explicit=True):
        """Returns a writer for the entity's serialized byte encoding.

        :param context:  I/O context for encoding
        :type  context:  :class:`VIOContext`
        :param explicit: if True encode the explicit serialized representation
        :type  explicit: bool
        :returns:        a writer
        :rtype:          :class:`VEntityWriter`

        """
        writer = VEntityWriter(context, explicit)
        writer.set_entity(self)
        return writer

    def _v_write(self, context):
        """Return the entity's (explicit) serialized byte encoding.

        :param context: I/O context for encoding
        :type  context: :class:`VIOContext`
        :returns:       entity's serialized representation
        :rtype:         bytes

        Convenience method for entity._v_writer(context).write()

        """
        return self._v_writer(context).write()

    @classmethod
    def _v_reader(cls, context, explicit=True):
        """Returns a reader for the class' serialized representation.

        :param context:  I/O context for decoding
        :type  context:  :class:`VIOContext`
        :param explicit: if True decode the explicit serialized representation
        :type  explicit: bool
        :returns:        reader
        :rtype:          :class:`VEntityReader`

        """
        reader = VEntityReader()
        reader.set_decoder(cls._v_decoder(context=context, explicit=explicit))
        return reader


class VEntityDecoder(VEntityDecoderBase):
    """Decodes a VEntity from its serialized representation.

    The decoder is a generic decoder for any standard
    :class:`VEntity`\ . It infers entity type from the header and
    invokes the appropriate decoder for the entity.

    Note that :class:`VEntityDecoder` can only be set up for
    'explicit' encoding, constructing with explicit=False will trigger
    an exception..

    """
    def __init__(self, context, explicit=True):
        if not explicit:
            raise VEntityReaderError('VEntityDecoder requires \'explicit\'')
        super(VEntityDecoder, self).__init__(context)
        self.__decoder = None
        self.__result = None
        self.__has_result = False
        self.__code_only = False

    def decode_header(self, data):
        if self.__decoder:
            return self.__decoder.decode_header(data)
        elif not data:
            return (0, False, 1, 0)

        if _pyver == 2:
            code = _b_ord(data.peek(1))
        else:
            code = data.peek(1)[0]
        if code < VEntityCode.START:
            self.__decoder = VInteger._v_decoder(self.context)
        else:
            decode_gen = _VENTITY_DECODE_GEN.get(code, None)
            if not decode_gen:
                raise VEntityReaderError('Could not parse object type')
            self.__decoder = decode_gen(self.context)

        return self.__decoder.decode_header(data)

    def get_payload_len(self):
        if not self.__code_only:
            return self.__decoder.get_payload_len()
        else:
            return 0

    def get_embedded_decoders(self):
        if not self.__code_only:
            return self.__decoder.get_embedded_decoders()
        else:
            return None

    def put_embedded_results(self, result):
        if not self.__code_only:
            self.__decoder.put_embedded_results(result)

    def decode_payload(self, data):
        if not self.__code_only:
            return self.__decoder.decode_payload(data)
        else:
            return (0, True)

    def result(self):
        if not self.__has_result:
            self.__result = self.__decoder.result()
            self.__has_result = True
        return self.__result


class VInteger(VEntity):
    """Implementation of the :term:`VP` VInteger data type.

    A :class:`VInteger` is an arbitrary-precision signed integer.

    Overloads binary operators *lt, le, eq, ne, ge, gt, add, and,
    floordiv, lshift, mod, mul, or, pow, rshift, sub, xor, concat,
    contains, countOf, getitem*

    Overloads unary operators *truth, index, abs, neg, hash, len, iter*

    :param value: integer value
    :type  value: int, long, :class:`VInteger`
    :raises:      :exc:`exceptions.TypeError`

    Example:

    >>> from versile.orb.entity import VInteger
    >>> VInteger(5)
    5
    >>> type(_) #doctest: +NORMALIZE_WHITESPACE
    <class 'versile.orb.entity.VInteger'>

    """

    def __setattr__(self, *args):
        raise TypeError("can't modify immutable instance")
    __delattr__ = __setattr__

    def __init__(self, value):
        if isinstance(value, (int, long)):
            super(VInteger, self).__setattr__('_v_value', value)
        elif isinstance(value, VInteger):
            super(VInteger, self).__setattr__('_v_value', value._v_value)
        else:
            raise TypeError('Value must be an integer')

    @classmethod
    def _v_converter(cls, obj):
        return (None, [VInteger(obj)])

    def _v_native_converter(self):
        return (lambda l: l[0], [self._v_value])

    def _v_native(self, deep=True):
        return self._v_value

    def _v_encode(self, context, explicit=True):
        result = []
        if explicit:
            if self._v_value >= VEntityCode.START - 1:
                if _pyver == 2:
                    result.append(_s2b(_b_chr(VEntityCode.VINT_POS)))
                else:
                    result.append(bytes((VEntityCode.VINT_POS,)))
                encode_v_value = self._v_value - (VEntityCode.START - 1)
                result.append(posint_to_netbytes(encode_v_value))
            elif self._v_value < -1:
                if _pyver == 2:
                    result.append(_s2b(_b_chr(VEntityCode.VINT_NEG)))
                else:
                    result.append(bytes((VEntityCode.VINT_NEG,)))
                encode_v_value = -(self._v_value + 2)
                result.append(posint_to_netbytes(encode_v_value))
            else:
                if _pyver == 2:
                    result.append(_s2b(_b_chr(self._v_value + 1)))
                else:
                    result.append(bytes((self._v_value + 1,)))
        else:
            result.append(signedint_to_netbytes(self._v_value))
        return (result, [], [])

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VIntegerDecoder(context, explicit)

    # Operator overload. Skipped truediv, inv, pos
    __lt__        = __rlt__       =  _meta_op2(operator.lt, cast=False)
    __le__        = __rle__       =  _meta_op2(operator.le, cast=False)
    __eq__        = __req__       =  _meta_op2(operator.eq, cast=False)
    __ne__        = __rne__       =  _meta_op2(operator.ne, cast=False)
    __ge__        = __rge__       =  _meta_op2(operator.ge, cast=False)
    __gt__        = __rgt__       =  _meta_op2(operator.gt, cast=False)
    __add__       = __radd__      =  _meta_op2(operator.add, cast=True)
    __and__       = __rand__      =  _meta_op2(operator.and_, cast=True)
    __floordiv__  = __rfloordiv__ =  _meta_op2(operator.floordiv, cast=True)
    __lshift__    = __rlshift__   =  _meta_op2(operator.lshift, cast=True)
    __mod__       = __rmod__      =  _meta_op2(operator.mod, cast=True)
    __mul__       = __rmul__      =  _meta_op2(operator.mul, cast=True)
    __or__        = __ror__       =  _meta_op2(operator.or_, cast=True)
    __pow__       = __rpow__      =  _meta_op2(operator.pow, cast=True)
    __rshift__    = __rrshift__   =  _meta_op2(operator.rshift, cast=True)
    __sub__       = __rsub__      =  _meta_op2(operator.sub, cast=True)
    __xor__       = __rxor__      =  _meta_op2(operator.xor, cast=True)
    __concat__    = __rconcat__   =  _meta_op2(operator.concat, cast=True)
    __truth__                     =  _meta_op1(operator.truth, cast=False)
    __index__                     =  _meta_op1(operator.index, cast=False)
    __abs__                       =  _meta_op1(operator.abs, cast=True)
    __neg__       = __rneg__      =  _meta_op1(operator.neg, cast=True)

    def __hash__(self):
        return hash(self._v_value)

    def __str__(self):
        return self._v_value.__str__()

    def __unicode__(self):
        return unicode(self._v_value)

    def __repr__(self):
        return self._v_value.__repr__()


class VIntegerDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VInteger` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VIntegerDecoder, self).__init__(context)
        self.__explicit = explicit
        self.__data = b''
        self.__result = None
        self.__have_code = False

    def decode_header(self, data):
        if self.__result is not None:
            return (0, True, 1, 0)
        elif not data:
            return (0, False, 1, 0)

        num_read = 0
        if self.__explicit:
            if not self.__have_code:
                if _pyver == 2:
                    code = _b_ord(data.pop(1))
                else:
                    code = data.pop(1)[0]
                num_read += 1
                if code < VEntityCode.START:
                    self.__result = VInteger(code - 1)
                    self.__data = None
                    return (num_read, True, 1, 0)
                elif code == VEntityCode.VINT_POS:
                    self.__have_code = True
                    self.__positive = True
                    self.__conv_func = netbytes_to_posint
                    self.__offset = VEntityCode.START - 1
                    self.__flip_sign = False
                elif code == VEntityCode.VINT_NEG:
                    self.__have_code = True
                    self.__positive = False
                    self.__conv_func = netbytes_to_posint
                    self.__offset = 2
                    self.__flip_sign = True
                else:
                    raise VEntityReaderError('Invalid VInteger code')
            if not data:
                return (num_read, False, 1, 0)
        else:
            self.__conv_func = netbytes_to_signedint
            self.__offset = 0
            self.__flip_sign = False

        old_len = len(self.__data)
        self.__data = b''.join((self.__data, data.peek()))
        number, meta = self.__conv_func(self.__data)
        if number is not None:
            to_pop = meta - old_len
            num_read += to_pop
            data.pop(to_pop)
            number += self.__offset
            if self.__flip_sign:
                number = -number
            self.__result = VInteger(number)
            self.__data = None
            return (num_read, True, 1, 0)
        else:
            num_read += len(data)
            data.pop()
            return (num_read, False, 1, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        return None

    def put_embedded_results(self, result):
        raise VEntityReaderError('Not applicable')

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class VBoolean(VEntity):
    """Implementation of the :term:`VP` VBoolean data type.

    A :class:`VBoolean` represents a boolean value.

    Overloads binary operators *lt, le, eq, ne, ge, gt, add, and,
    lshift, mul, or, pow, rshift, sub, xor*

    Overloads unary operators *truth, index, abs, neg, hash*

    :param value: boolean value
    :type  value: bool, :class:`VBoolean`

    Example:

    >>> from versile.orb.entity import VBoolean
    >>> VBoolean(True)
    True
    >>> type(_)
    <class 'versile.orb.entity.VBoolean'>

    """

    def __init__(self, value):
        if isinstance(value, bool):
            super(VBoolean, self).__setattr__('_v_value', value)
        elif isinstance(value, VBoolean):
            super(VBoolean, self).__setattr__('_v_value', value._v_value)
        else:
            raise TypeError('Value must be a boolean')

    def __setattr__(self, *args):
        raise TypeError("can't modify immutable instance")
    __delattr__ = __setattr__

    @classmethod
    def _v_converter(cls, obj):
        return (None, [VBoolean(obj)])

    def _v_native_converter(self):
        return (lambda l: l[0], [self._v_value])

    def _v_native(self, deep=True):
        return self._v_value

    def _v_encode(self, context, explicit=True):
        if _pyver == 2:
            if self._v_value:
                return ([_s2b(_b_chr(VEntityCode.VBOOL_TRUE))], [], [])
            else:
                return ([_s2b(_b_chr(VEntityCode.VBOOL_FALSE))], [], [])
        else:
            if self._v_value:
                return ([bytes((VEntityCode.VBOOL_TRUE,))], [], [])
            else:
                return ([bytes((VEntityCode.VBOOL_FALSE,))], [], [])

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VBooleanDecoder(context, explicit)

    # Operator overload. Skipped: floordiv, mod, truediv, concat, inv, pos
    __lt__        = __rlt__       =  _meta_op2(operator.lt, cast=False)
    __le__        = __rle__       =  _meta_op2(operator.le, cast=False)
    __eq__        = __req__       =  _meta_op2(operator.eq, cast=False)
    __ne__        = __rne__       =  _meta_op2(operator.ne, cast=False)
    __ge__        = __rge__       =  _meta_op2(operator.ge, cast=False)
    __gt__        = __rgt__       =  _meta_op2(operator.gt, cast=False)
    __add__       = __radd__      =  _meta_op2(operator.add, cast=True)
    __and__       = __rand__      =  _meta_op2(operator.and_, cast=True)
    __lshift__    = __rlshift__   =  _meta_op2(operator.lshift, cast=True)
    __mul__       = __rmul__      =  _meta_op2(operator.mul, cast=True)
    __or__        = __ror__       =  _meta_op2(operator.or_, cast=True)
    __pow__       = __rpow__      =  _meta_op2(operator.pow, cast=True)
    __rshift__    = __rrshift__   =  _meta_op2(operator.rshift, cast=True)
    __sub__       = __rsub__      =  _meta_op2(operator.sub, cast=True)
    __xor__       = __rxor__      =  _meta_op2(operator.xor, cast=True)
    __truth__                     =  _meta_op1(operator.truth, cast=False)
    __index__                     =  _meta_op1(operator.index, cast=False)
    __abs__                       =  _meta_op1(operator.abs, cast=True)
    __neg__       = __rneg__      =  _meta_op1(operator.neg, cast=True)

    def __hash__(self):
        return hash(self._v_value)

    def __str__(self):
        return self._v_value.__str__()

    def __unicode__(self):
        return unicode(self._v_value)

    def __repr__(self):
        return self._v_value.__repr__()


class VBooleanDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VBoolean` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VBooleanDecoder, self).__init__(context)
        self.__result = None

    def decode_header(self, data):
        if self.__result is not None:
            return (0, True, 1, 0)
        elif not data:
            return (0, False, 1, 0)
        if _pyver == 2:
            code = _b_ord(data.pop(1))
        else:
            code = data.pop(1)[0]
        if code == VEntityCode.VBOOL_TRUE:
            self.__result = VBoolean(True)
        elif code == VEntityCode.VBOOL_FALSE:
            self.__result = VBoolean(False)
        else:
            raise VEntityError('Invalid VBoolean type code')
        return (1, True, 1, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        return None

    def put_embedded_results(self, result):
        raise VEntityReaderError('Not applicable')

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class VNone(VEntity):
    """Implementation of the :term:`VP` VNone data type.

    A :class:`VNone` entity represents the python 'None' value.

    Overloads binary operators *lt, le, eq, ne, ge, gt*

    Overloads unary operators *hash*

    As None is a special python entity, this object does not fully
    simulate None in the way that e.g. VInteger implements much of int
    behaviour via overloaded operators.

    .. warning::

        In particular, one should never do a 'is None' comparison
        directly on a VNone object

    Note the following example:

    >>> from versile.orb.entity import VNone
    >>> none = VNone()
    >>> none is None
    False
    >>> none._v_native() is None
    True

    """

    def __setattr__(self, *args):
        raise TypeError("can't modify immutable instance")
    __delattr__ = __setattr__

    def __init__(self):
        super(VNone, self).__setattr__('_v_value', None)

    @classmethod
    def _v_converter(cls, obj):
        return (None, [VNone()])

    def _v_native_converter(self):
        return (lambda l: l[0], [None])

    def _v_native(self, deep=True):
        return None

    def _v_encode(self, context, explicit=True):
        if _pyver == 2:
            return ([_s2b(_b_chr(VEntityCode.VNONE))], [], [])
        else:
            return ([bytes((VEntityCode.VNONE,))], [], [])

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VNoneDecoder(context, explicit)

    # Operator overload. Skipped: add, and, floordiv, lshift, mod, mul, or,
    # pow, rshift, sub, truediv, xor, concat, truth, index, abs, inv,
    # neg, pos
    __lt__        = __rlt__       =  _meta_op2(operator.lt, cast=False)
    __le__        = __rle__       =  _meta_op2(operator.le, cast=False)
    __eq__        = __req__       =  _meta_op2(operator.eq, cast=False)
    __ne__        = __rne__       =  _meta_op2(operator.ne, cast=False)
    __ge__        = __rge__       =  _meta_op2(operator.ge, cast=False)
    __gt__        = __rgt__       =  _meta_op2(operator.gt, cast=False)

    def __hash__(self):
        return hash(None)

    def __str__(self):
        return None.__str__()

    def __unicode__(self):
        return unicode(None)

    def __repr__(self):
        return None.__repr__()


class VNoneDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VNone` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VNoneDecoder, self).__init__(context)
        self.__explicit = explicit
        self.__has_result = False

    def decode_header(self, data):
        if not self.__explicit:
            return (0, True, 1, 0)

        if self.__has_result:
            return (0, True, 1, 0)
        elif not data:
            return (0, False, 1, 0)

        if _pyver == 2:
            code = _b_ord(data.pop(1))
        else:
            code = data.pop(1)[0]
        if code == VEntityCode.VNONE:
            self.__has_result = True
        else:
            raise VEntityError('Invalid VNone type code')
        return (1, True, 1, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        return None

    def put_embedded_results(self, result):
        raise VEntityReaderError('Not applicable')

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__has_result or not self.__explicit:
            return VNone()
        else:
            raise VEntityReaderError('Result not ready')


class VFloat(VEntity):
    """Implementation of the :term:`VP` VFloat data type.

    A :class:`VFloat` holds an arbitrary-length floating point number which
    can be represented in any base. The value of the entity is:

      self.\ :attr:`_v_digits` \* (\ self.\ :attr:`_v_base_` \*\* self.\
      :attr:`_v_exp`\ )

    Operator overloading on :class:`VFloat` is currently not
    implemented.

    Numbers will not be converted to a native type if the number
    cannot be represented exactly by the native type, i.e. conversion
    is only performed if a compatible native type exists and there is
    no loss of precision.

    There are several supported construction methods:

    * VFloat(<float>)   (constructed as base-2)
    * VFloat(<Decimal>) (constructed as base-10)
    * VFloat(<integer>, base=[base])
    * VFloat(digits, exp, base=[base])
    * VFloat(<VFloat>)

    >>> from versile.orb.entity import *
    >>> from decimal import Decimal
    >>> VFloat(2.25)
    2.25
    >>> VFloat(Decimal('10.3'))
    Decimal('10.3')
    >>> VFloat(93)
    Decimal('93')
    >>> VFloat(93, base=2)
    93.0
    >>> VFloat(42, -5, base=7)
    'VFloat[42 * 7^(-5)]'

    .. automethod:: _v_native

    """

    def __setattr__(self, *args):
        raise TypeError("can't modify immutable instance")
    __delattr__ = __setattr__

    def __init__(self, *args, **named):
        super(VFloat, self).__init__()
        super(VFloat, self).__setattr__('_cached_decimal', None)
        if len(args) == 0 or len(args) > 2 or len(named) > 1:
            raise ValueError('Incorrect parameters')
        if len(args) == 1 and isinstance(args[0], VFloat):
            if len(named) > 0:
                raise ValueError('Too many parameters')
            num = args[0]
            super(VFloat, self).__setattr__('_v_digits', num._v_digits)
            super(VFloat, self).__setattr__('_v_base', num._v_base)
            super(VFloat, self).__setattr__('_v_exp', num._v_exp)
            super(VFloat, self).__setattr__('_cached_decimal',
                                            num._cached_decimal)
            return
        elif len(args) == 1 and isinstance(args[0], Decimal):
            if len(named) > 0:
                raise ValueError('Too many parameters')
            d_tuple = args[0].as_tuple()
            digits_str = ''
            for c in d_tuple[1]:
                digits_str += str(c)
            digits = int(digits_str)
            if d_tuple[0]:
                digits = -digits
            super(VFloat, self).__setattr__('_v_digits', digits)
            super(VFloat, self).__setattr__('_v_base', 10)
            super(VFloat, self).__setattr__('_v_exp', d_tuple[2])
            return
        elif len(args) == 1 and isinstance(args[0], float):
            if len(named) > 0:
                raise ValueError('Too many parameters')
            hex_str = args[0].hex()
            negative = (hex_str[0] == '-')
            digits_str = hex_str.rsplit('0x')[-1].rsplit('-0x')[-1]
            split_1 = digits_str.split('p')
            split_2 = split_1[0].split('.')
            split_2[1] = split_2[1].rstrip('0')
            digit_str = split_2[0] + split_2[1]
            digits = int(digit_str, 16)
            if negative:
                digits = -digits
            exp = int(split_1[1]) - 4*len(split_2[1])
            super(VFloat, self).__setattr__('_v_digits', digits)
            super(VFloat, self).__setattr__('_v_base', 2)
            super(VFloat, self).__setattr__('_v_exp', exp)
            return

        if len(named) == 1:
            if named.has_key('base'):
                base = named['base']
            else:
                raise ValueError('Unknown parameter')
        else:
            base = 10
        if len(args) == 1:
            nums = [args[0], base, 0]
        else:
            nums = [args[0], base, args[1]]
        for i in xrange(len(nums)):
            v = nums[i]
            if isinstance(v, (int, long)):
                pass
            elif isinstance(v, VInteger):
                nums[i] = v._v_value
            else:
                raise TypeError('Parameter must be an integer')
        digits, base, exp = nums
        if base < 2:
            raise ValueError('Base must be positive and >= 2')
        super(VFloat, self).__setattr__('_v_digits', digits)
        super(VFloat, self).__setattr__('_v_base', base)
        super(VFloat, self).__setattr__('_v_exp', exp)

    @classmethod
    def _v_converter(cls, obj):
        return (None, [VFloat(obj)])

    def _v_native_converter(self):
        return (lambda l: l[0], [self._v_native()])

    def _v_native(self, deep=True):
        """Returns a platform-specific representation of object value.

        See :meth:`VEntity._v_native`

        * Base-10 is converted to Decimal
        * Base-2 is converted to float only if the value can be
          represented as float without loss of precision

        If the number is not base-10 or base-2, or if the number
        cannot be exactly represented in a native value, the entity
        itself is returned.

        >>> from versile.orb.entity import *
        >>> d = VFloat(2.25)
        >>> d._v_native()
        2.25
        >>> type(_)
        <type 'float'>
        >>> d = VFloat(3, -4, base=5)
        >>> d._v_native()
        'VFloat[3 * 5^(-4)]'
        >>> type(_)
        <class 'versile.orb.entity.VFloat'>

        """
        if self._v_base == 10:
            if not self._cached_decimal:
                digit_list = [int(c) for c in str(abs(self._v_digits))]
                if self._v_digits >= 0:
                    sign = 0
                else:
                    sign = 1
                value = Decimal((sign, digit_list, self._v_exp)).normalize()
                super(VFloat, self).__setattr__('_cached_decimal', value)
            return self._cached_decimal
        elif self._v_base == 2:
            # Return as a float if it can precisely represent the value
            digit_str = _s2b(hex(self._v_digits)).strip(b'L')
            pre_point = digit_str.index(b'x') + 2
            num_after = len(digit_str) - pre_point
            if num_after == 0:
                digit_str = digit_str + b'.0'
                exp = self._v_exp
            else:
                digit_str = b''.join((digit_str[:pre_point], b'.',
                                     digit_str[pre_point:]))
                exp = self._v_exp + 4*num_after
            if exp > 0:
                hex_str = b''.join((digit_str, b'p+', _s2b(str(exp))))
            else:
                hex_str = b''.join((digit_str, b'p', _s2b(str(exp))))
            candidate = float.fromhex(_b2s(hex_str))
            converted = VFloat(candidate)
            if (self._v_exp == converted._v_exp):
                if (self._v_digits == converted._v_digits):
                    return candidate
            elif (self._v_exp > converted._v_exp):
                exp_diff = self._v_exp - converted._v_exp
                if (self._v_digits * 2**exp_diff == converted._v_digits):
                    return candidate
            else:
                exp_diff = converted._v_exp - self._v_exp
                if (self._v_digits == converted._v_digits * 2**exp_diff):
                    return candidate

            # Can not fit the base-2 in a float
            return self
        else:
            # Can only return for base-10 or base-2
            return self

    def _v_encode(self, context, explicit=True):
        if _pyver == 2:
            if self._v_base == 2:
                code = [_s2b(_b_chr(VEntityCode.VFLOAT_2))]
            elif self._v_base == 10:
                code = [_s2b(_b_chr(VEntityCode.VFLOAT_10))]
            else:
                code = [_s2b(_b_chr(VEntityCode.VFLOAT_N))]
        else:
            if self._v_base == 2:
                code = [bytes((VEntityCode.VFLOAT_2,))]
            elif self._v_base == 10:
                code = [bytes((VEntityCode.VFLOAT_10,))]
            else:
                code = [bytes((VEntityCode.VFLOAT_N,))]
        embedded = []
        embedded.append((VInteger(self._v_digits), False))
        if self._v_base not in (2, 10):
            embedded.append((VInteger(self._v_base), False))
        embedded.append((VInteger(self._v_exp), False))
        return (code, embedded, [])

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VFloatDecoder(context, explicit)

    def __hash__(self):
        # Currently will compute the same hash if all components digits,
        # base and exponent are the same. Two numbers can represent the
        # same (normalized) value, but have different hash values. E.g.
        # the numbers 4*10^0 and 1*2^2 both represent the number '4'
        return hash((self._v_digits, self._v_base, self._v_exp))

    def __str__(self):
        native = self._v_native()
        if native is not self:
            return native.__str__()
        else:
            return ''.join(('VFloat[', str(self._v_digits), ' * ',
                            str(self._v_base), '^(', str(self._v_exp), ')]'))

    def __unicode__(self):
        return unicode(self.__str__())

    def __repr__(self):
        native = self._v_native()
        if native is not self:
            return native.__repr__()
        else:
            return ''.join(('\'VFloat[', str(self._v_digits), ' * ',
                            str(self._v_base), '^(', str(self._v_exp), ')]\''))


class VFloatDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VFloat` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VFloatDecoder, self).__init__(context)
        self.__result = None
        self.__have_code = False
        self.__base = None
        self.__num_objects = None

    def decode_header(self, data):
        if self.__result is not None or self.__have_code:
            return (0, True, self.__num_objects, 0)
        elif not data:
            return (0, False, 3, 0)

        if _pyver == 2:
            code = _b_ord(data.pop(1))
        else:
            code = data.pop(1)[0]
        if code == VEntityCode.VFLOAT_2:
            self.__base = 2
            self.__num_objects = 3
        elif code == VEntityCode.VFLOAT_10:
            self.__base = 10
            self.__num_objects = 3
        elif code == VEntityCode.VFLOAT_N:
            self.__base = None
            self.__num_objects = 4
        else:
            raise VEntityReaderError('Invalid VFloat code')
        self.__have_code = True
        return (1, True, self.__num_objects, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        if self.__base is not None:
            num_dec = 2
        else:
            num_dec = 3
        decoders = []
        for i in xrange(num_dec):
            decoders.append(VInteger._v_decoder(self.context, explicit=False))
        return (iter(decoders), num_dec)

    def put_embedded_results(self, result):
        if ((self.__base is not None and len(result) != 2)
            or (self.__base is None and len(result) != 3)):
            raise VReaderError('Invalid number of embedded results')
        for item in result:
            if not isinstance(item, VInteger):
                raise VReaderError('Embedded results must be integers')
        digits = result[0]._v_native()
        exp = result[-1]._v_native()
        if self.__base:
            base = self.__base
        else:
            base = result[1]._v_native()
            if base < 2:
                raise VReaderError('Invalid base')
        self.__result = VFloat(digits, exp, base=base)

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class VTuple(VEntity):
    """Implementation of the :term:`VP` VTuple data type.

    :class:`VTuple` holds an tuple of :class:`VEntity` elements.

    Overloads binary operators *lt, le, eq, ne, ge, gt, add, and,
    lshift, mul, or, pow, rshift, sub, xor, contains, countOf,
    getitem, indexOf*

    Overloads unary operators *truth, index, len*

    Calling :meth:`VTuple._v_native` generates a native tuple with
    each element lazy-converted to its native representation.

    Supported construction methods includes:

    * VTuple(tuple(<obj>, <obj>, ...), [lazy=<bool>])
    * VTuple(<obj>, <obj> [, ...], [lazy=<bool>])
    * VTuple(<VTuple>, [lazy=<bool>])

    If *lazy* is True (the default) then *obj* values are
    lazy-converted to :class:`VEntity`\ , otherwise all *obj*
    values must be a :class:`VEntity`\ .

    The method may raise :exc:`exceptions.TypeError` or
    :exc:`exceptions.ValueError`\ .

    Examples:

    >>> from versile.orb.entity import *
    >>> VTuple((VInteger(2), VNone(), VBoolean(False)))
    (2, None, False)
    >>> VTuple((2, None, False))
    (2, None, False)
    >>> VTuple(VInteger(2), VNone(), VBoolean(False))
    (2, None, False)
    >>> VTuple(2, None, False)
    (2, None, False)
    >>> VTuple(VTuple(2, None, False))
    (2, None, False)
    >>> try:
    ...   VTuple(2, None, False, lazy=False)
    ... except:
    ...   print('Exception raised')
    ...
    Exception raised

    """

    def __init__(self, *obj, **modify):
        if len(obj) == 0:
            obj_list = []
        elif len(obj) == 1:
            obj_list = obj[0]
        else:
            obj_list = obj
        if modify.has_key('lazy'):
            lazy = modify['lazy']
            if not isinstance(lazy, bool):
                raise TypeError('lazy= parameter must be bool')
            if len(modify) > 1:
                raise ValueError('modify can only set lazy=')
        else:
            lazy = True
            if len(modify) > 0:
                raise ValueError('modify can only set lazy=')
        if isinstance(obj_list, VTuple):
            obj_list = obj_list._v_value
        try:
            obj_iter = iter(obj_list)
        except TypeError:
            raise TypeError('VTuple must be constructed on iterable list')
        value = []
        for obj in obj_iter:
            if isinstance(obj, VEntity):
                value.append(obj)
            elif lazy:
                try:
                    value.append(VEntity._v_lazy(obj))
                except:
                    TypeError('Could not lazy-convert object to VEntity')
            else:
                raise TypeError('All VTuple elements must be VEntity\'s')
        super(VTuple, self).__setattr__('_v_value', tuple(value))

    def __setattr__(self, *args):
        raise TypeError("can't modify immutable instance")
    __delattr__ = __setattr__

    @classmethod
    def _v_converter(cls, obj):
        if isinstance(obj, VTuple):
            return (None, [obj])
        elif isinstance(obj, (list, tuple)):
            return (cls, list(obj))
        else:
            raise VEntityError('Not supported type for VTuple lazy conversion')

    def _v_native_converter(self):
        return (tuple, list(self._v_value))

    def _v_encode(self, context, explicit=True):
        if explicit:
            if _pyver == 2:
                header = [_s2b(_b_chr(VEntityCode.VTUPLE))]
            else:
                header = [bytes((VEntityCode.VTUPLE,))]
        else:
            header = []
        header.append(posint_to_netbytes(len(self._v_value)))
        embedded = [(e, True) for e in self._v_value]
        return (header, embedded, [])

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VTupleDecoder(context, explicit)

    # Some additional left-only list related operator overloads
    def __contains__(self, val):
        for obj in self._v_value:
            if obj == val:
                return True
        return False

    def __countOf__(self, val):
        count = 0
        for obj in self._v_value:
            if obj == val:
                count += 1
        return count

    def __getitem__(self, index):
        return VEntity._v_lazy(self._v_value[index])

    def __indexOf__(self, val):
        count = 0
        for obj in self._v_value:
            if obj == val:
                return count
            count += 1
        raise ValueError('Value not in list')

    def __len__(self):
        return len(self._v_value)

    def __iter__(self):
        return iter(self._v_value)

    # Operator overload. Skipped: floordiv, mod, truediv, concat, abs, inv,
    # neg, pos
    __lt__        = __rlt__       =  _meta_op2(operator.lt, cast=False)
    __le__        = __rle__       =  _meta_op2(operator.le, cast=False)
    __eq__        = __req__       =  _meta_op2(operator.eq, cast=False)
    __ne__        = __rne__       =  _meta_op2(operator.ne, cast=False)
    __ge__        = __rge__       =  _meta_op2(operator.ge, cast=False)
    __gt__        = __rgt__       =  _meta_op2(operator.gt, cast=False)
    __add__       = __radd__      =  _meta_op2(operator.add, cast=True)
    __and__       = __rand__      =  _meta_op2(operator.and_, cast=True)
    __lshift__    = __rlshift__   =  _meta_op2(operator.lshift, cast=True)
    __mul__       = __rmul__      =  _meta_op2(operator.mul, cast=True)
    __or__        = __ror__       =  _meta_op2(operator.or_, cast=True)
    __pow__       = __rpow__      =  _meta_op2(operator.pow, cast=True)
    __rshift__    = __rrshift__   =  _meta_op2(operator.rshift, cast=True)
    __sub__       = __rsub__      =  _meta_op2(operator.sub, cast=True)
    __xor__       = __rxor__      =  _meta_op2(operator.xor, cast=True)
    __truth__                     =  _meta_op1(operator.truth, cast=False)
    __index__                     =  _meta_op1(operator.index, cast=False)

    def __hash__(self):
        return hash(self._v_value)

    def __str__(self):
        return self._v_value.__str__()

    def __unicode__(self):
        return unicode(self._v_value)

    def __repr__(self):
        return self._v_value.__repr__()


class VTupleDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VTuple` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VTupleDecoder, self).__init__(context)
        self.__explicit = explicit
        self.__data = b''
        self.__result = None
        self.__have_code = False
        self.__min_objects = 1

    def decode_header(self, data):
        if self.__result is not None:
            return (0, True, self.__min_objects, 0)
        elif not data:
            return (0, False, self.__min_objects, 0)

        num_read = 0
        if not self.__have_code:
            if self.__explicit:
                if _pyver == 2:
                    code = _b_ord(data.pop(1))
                else:
                    code = data.pop(1)[0]
                num_read += 1
                if code == VEntityCode.VTUPLE:
                    self.__have_code = True
                else:
                    raise VReaderError('Invalid VTuple code')
            else:
                self.__have_code = True
        if not data:
            return (num_read, False, self.__min_objects, 0)

        old_len = len(self.__data)
        self.__data = b''.join((self.__data, data.peek()))
        number, meta = netbytes_to_posint(self.__data)
        if number is not None:
            num_read += meta - old_len
            data.pop(meta - old_len)
            self.__elements = number
            self.__min_objects = number + 1
            self.__data = None
            return (num_read, True, self.__min_objects, 0)
        else:
            num_read += len(data)
            data.pop()
            min_int_bytes = meta[0]
            if min_int_bytes is None:
                self.__min_objects = 1
            else:
                self.__min_objects = 1 + 0x1 << (min_int_bytes-1)
            return (num_read, False, self.__min_objects, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        if self.__elements == 0:
            self.__result = VTuple()
            return None
        else:
            def decoders():
                for i in xrange(self.__elements):
                    yield VEntity._v_decoder(self.context)
            return (decoders(), self.__elements)

    def put_embedded_results(self, result):
        self.__result = VTuple(result)

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class VBytes(VEntity):
    """Implementation of the :term:`VP` VBytes data type.

    :class:`VBytes` is an immutable byte vector similar to 'bytes'.

    Overloads binary operators *lt, le, eq, ne, ge, gt, add, concat*

    Overloads unary operators *truth, hash*

    :param value: byte array
    :type  value: bytes, :class:`VBytes`

    Example initialization:

    >>> from versile.orb.entity import *
    >>> VBytes(b'zxcvb')
    'zxcvb'
    >>> type(_)
    <class 'versile.orb.entity.VBytes'>

    """

    def __setattr__(self, *args):
        raise TypeError("can't modify immutable instance")
    __delattr__ = __setattr__

    def __init__(self, value):
        if isinstance(value, bytes):
            super(VBytes, self).__setattr__('_v_value', value)
        elif isinstance(value, bytearray):
            super(VBytes, self).__setattr__('_v_value', bytes(value))
        elif isinstance(value, VBytes):
            super(VBytes, self).__setattr__('_v_value', value._v_value)
        else:
            raise TypeError('Value must be a bytes or bytearray object')

    @classmethod
    def _v_converter(cls, obj):
        if isinstance(obj, VBytes):
            return (None, [obj])
        elif isinstance(obj, bytes):
            return (None, [VBytes(obj)])
        else:
            raise VEntityError('Not supported type for VBytes lazy conversion')

    def _v_native_converter(self):
        return (lambda l: l[0], [self._v_native()])

    def _v_native(self, deep=True):
        return self._v_value

    def _v_encode(self, context, explicit=True):
        if explicit:
            if _pyver == 2:
                header = [_s2b(_b_chr(VEntityCode.VBYTES))]
            else:
                header = [bytes((VEntityCode.VBYTES,))]
        else:
            header = []
        header.append(posint_to_netbytes(len(self._v_value)))
        return (header, [], [self._v_value])

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VBytesDecoder(context, explicit)

    # Additional left-only list related operator overloads
    def __contains__(self, val):
        for obj in self._v_value:
            if obj == val:
                return True
        return False

    def __countOf__(self, val):
        count = 0
        for obj in self._v_value:
            if obj == val:
                count += 1
        return count

    def __getitem__(self, index):
        return VBytes(self._v_value[index])

    def __len__(self):
        return len(self._v_value)

    def __iter__(self):
        for b in self._v_value:
            yield VBytes(b)

    # Operator overload. Skipped: and, floordiv, lshift, mod, mul, or, pow,
    # rshift, sub, trudiv, xor, index, abs, inv, neg, pos
    __lt__        = __rlt__       =  _meta_op2(operator.lt, cast=False)
    __le__        = __rle__       =  _meta_op2(operator.le, cast=False)
    __eq__        = __req__       =  _meta_op2(operator.eq, cast=False)
    __ne__        = __rne__       =  _meta_op2(operator.ne, cast=False)
    __ge__        = __rge__       =  _meta_op2(operator.ge, cast=False)
    __gt__        = __rgt__       =  _meta_op2(operator.gt, cast=False)
    __add__       = __radd__      =  _meta_op2(operator.add, cast=True)
    __concat__    = __rconcat__   =  _meta_op2(operator.concat, cast=True)
    __truth__                     =  _meta_op1(operator.truth, cast=False)

    def __hash__(self):
        return hash(self._v_value)

    def __str__(self):
        return self._v_value.__str__()

    def __unicode__(self):
        return unicode(self._v_value)

    def __repr__(self):
        return self._v_value.__repr__()


class VBytesDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VBytes` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VBytesDecoder, self).__init__(context)
        self.__explicit = explicit
        self.__elements = 0
        self.__result = None
        self.__have_code = False
        self.__min_payload = 0
        self.__data = b''
        self.__payload = []
        self.__payload_read = 0

    def decode_header(self, data):
        if self.__result is not None:
            return (0, True, 1, self.__min_payload)
        elif not data:
            return (0, False, 1, self.__min_payload)

        num_read = 0
        if not self.__have_code:
            if self.__explicit:
                if _pyver == 2:
                    code = _b_ord(data.pop(1))
                else:
                    code = data.pop(1)[0]
                num_read += 1
                if code == VEntityCode.VBYTES:
                    self.__have_code = True
                else:
                    raise VReaderError('Invalid VTuple code')
            else:
                self.__have_code = True
        if not data:
            return (num_read, False, 1, self.__min_payload)

        old_len = len(self.__data)
        self.__data = b''.join((self.__data, data.peek()))
        number, meta = netbytes_to_posint(self.__data)
        if number is not None:
            num_read += meta - old_len
            data.pop(meta - old_len)
            self.__elements = number
            self.__min_payload = number
            self.__data = None
            return (num_read, True, 1, self.__min_payload)
        else:
            num_read += len(data)
            data.pop()
            min_int_bytes = meta[0]
            if min_int_bytes is None:
                self.__min_payload = 0
            else:
                self.__min_payload = 0x1 << (min_int_bytes-1)
            return (num_read, False, 1, self.__min_payload)

    def get_payload_len(self):
        return self.__elements

    def get_embedded_decoders(self):
        return None

    def put_embedded_results(self, result):
        raise NotImplementedError()

    def decode_payload(self, data):
        if self.__elements == 0:
            self.__result = VBytes(b'')
            return (0, True)
        max_read = self.__elements - self.__payload_read
        data_read = data.pop(max_read)
        self.__payload.append(data_read)
        self.__payload_read += len(data_read)
        if self.__elements == self.__payload_read:
            self.__result = VBytes(b''.join(self.__payload))
            self.__payload = None
            return (len(data_read), True)
        else:
            return (len(data_read), False)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class VString(VEntity):
    """Implementation of the :term:`VP` VString data type.

    :class:`VString` holds a string value (similar to 'unicode')

    Overloads binary operators *lt, le, eq, ne, ge, gt, add, concat*

    Overloads unary operators *truth, hash*

    :param value: string value
    :type  value: unicode, :class:`VString`

    >>> from versile.orb.entity import *
    >>> VString(u'confused cat')
    u'confused cat'
    >>> type(_)
    <class 'versile.orb.entity.VString'>

    .. automethod:: _v_encode
    .. automethod:: _v_codecs

    """

    def __setattr__(self, *args):
        raise TypeError("can't modify immutable instance")
    __delattr__ = __setattr__

    def __init__(self, value):
        if isinstance(value, unicode):
            super(VString, self).__setattr__('_v_value', value)
        elif isinstance(value, VString):
            super(VString, self).__setattr__('_v_value', value._v_value)
        else:
            raise TypeError('Value must be a bytes or bytearray object')

    @classmethod
    def _v_converter(cls, obj):
        if isinstance(obj, VString):
            return (None, [obj])
        elif isinstance(obj, unicode):
            return (None, [VString(obj)])
        else:
            raise VEntityError('Not supported type for VString lazy conv.')

    def _v_native_converter(self):
        return (lambda l: l[0], [self._v_native()])

    def _v_native(self, deep=True):
        return self._v_value

    def _v_encode(self, context, explicit=True, encoding=None):
        """Return the object's serialized byte encoding.

        See :meth:`VEntity._v_encode`

        The added argument *encoding*, if set, is the string encoding
        scheme to use (e.g. b'utf8'). If None, then b'utf8' is used as
        the default.

        """
        if encoding is not None:
            if context and encoding == context.str_encoding:
                include_encoding = False
            else:
                if encoding not in self._v_codecs():
                    raise VEntityError('String codec not supported')
                include_encoding = True
        elif context and context.str_encoding:
            encoding = context.str_encoding
            include_encoding = False
        else:
            encoding = b'utf8'
            include_encoding = True

        if _pyver == 2:
            if include_encoding:
                header = [_s2b(_b_chr(VEntityCode.VSTRING_ENC))]
            else:
                header = [_s2b(_b_chr(VEntityCode.VSTRING))]
        else:
            if include_encoding:
                header = [bytes((VEntityCode.VSTRING_ENC,))]
            else:
                header = [bytes((VEntityCode.VSTRING,))]

        embedded = []
        if include_encoding:
            embedded.append((VBytes(encoding), False))
        if _pyver == 2:
            _encoded = _s2b(self._v_value.encode(_b2s(encoding)))
        else:
            _encoded = self._v_value.encode(_b2s(encoding))
        embedded.append((VBytes(_encoded), False))

        return (header, embedded, [])

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VStringDecoder(context, explicit)

    @classmethod
    def _v_codecs(cls):
        """Returns a list of supported :term:`VFE` string codecs.

        :returns: supported string codecs
        :rtype:   (bytes,)

        """
        return (b'utf8', b'utf16')

    # Additional left-only list related operator overloads
    def __contains__(self, val):
        for obj in self._v_value:
            if obj == val:
                return True
        return False

    def __countOf__(self, val):
        count = 0
        for obj in self._v_value:
            if obj == val:
                count += 1
        return count

    def __getitem__(self, index):
        return VString(self._v_value[index])

    def __len__(self):
        return len(self._v_value)

    def __iter__(self):
        for b in self._v_value:
            yield VString(b)

    # Operator overload. Skipped: and, floordiv, lshift, mod, mul, or, pow,
    # rshift, sub, truediv, xor, index, abs, inv, neg, pos
    __lt__        = __rlt__       =  _meta_op2(operator.lt, cast=False)
    __le__        = __rle__       =  _meta_op2(operator.le, cast=False)
    __eq__        = __req__       =  _meta_op2(operator.eq, cast=False)
    __ne__        = __rne__       =  _meta_op2(operator.ne, cast=False)
    __ge__        = __rge__       =  _meta_op2(operator.ge, cast=False)
    __gt__        = __rgt__       =  _meta_op2(operator.gt, cast=False)
    __add__       = __radd__      =  _meta_op2(operator.add, cast=True)
    __concat__    = __rconcat__   =  _meta_op2(operator.concat, cast=True)
    __truth__                     =  _meta_op1(operator.truth, cast=False)

    def __hash__(self):
        return hash(self._v_value)

    def __str__(self):
        return self._v_value.__str__()

    def __unicode__(self):
        return self._v_value

    def __repr__(self):
        return self._v_value.__repr__()


class VStringDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VString` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VStringDecoder, self).__init__(context)
        self.__result = None
        self.__have_code = False
        self.__include_codec = None
        self.__min_objects = 2

    def decode_header(self, data):
        if self.__result is not None:
            return (0, True, self.__min_objects, 0)
        elif not data:
            return (0, False, self.__min_objects, 0)

        num_read = 0
        if not self.__have_code:
            if _pyver == 2:
                code = _b_ord(data.pop(1))
            else:
                code = data.pop(1)[0]
            num_read += 1
            if code == VEntityCode.VSTRING:
                    self.__have_code = True
                    self.__include_codec = False
                    self.__min_objects = 2
            elif code == VEntityCode.VSTRING_ENC:
                self.__have_code = True
                self.__include_codec = True
                self.__min_objects = 3
            else:
                raise VReaderError('Invalid VString code')
        return (num_read, True, self.__min_objects, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        if self.__include_codec:
            num_embedded = 2
        else:
            num_embedded = 1
        def embedded():
            for i in xrange(num_embedded):
                yield VBytes._v_decoder(self.context, explicit=False)
        return (embedded(), num_embedded)

    def put_embedded_results(self, result):
        codec = None
        if self.__include_codec:
            codec = result[0]._v_native()
            raw_string = result[1]._v_native()
        elif self.context:
            raw_string = result[0]._v_native()
            codec = self.context.str_decoding
        if codec is None:
            raise VEntityReaderError('Cannot decode, no codec defined')

        try:
            if _pyver == 2:
                value = unicode(_b2s(raw_string), encoding=_b2s(codec))
            else:
                value = str(raw_string, encoding=_b2s(codec))
        except:
            raise VEntityReaderError('Invalid encoding name or encoding')
        else:
            self.__result = VString(value)

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class VException(VEntity, Exception):
    """Implementation of the :term:`VP` VException data type.

    :class:`VException` represents an exception.

    The class plays an important role for remote method calls as they
    can be passed as remote objects, so a :class:`VException` that is
    raised by a method can be caught by a remote peer.

    A :class:`VException` can hold arguments similar to standard
    python exceptions. The argument values must be :class:`VEntity`
    data. Arguments can be accessed via the self.\ :attr:`args`
    attribute, or similar to a :class:`VTuple`\ .

    Example use:

    >>> from versile.orb.entity import *
    >>> e = VException(u'Problems', 3, False) # Arguments are lazy-converted
    >>> e.args
    (u'Problems', 3, False)
    >>> e.args[0]
    u'Problems'
    >>> len(e)
    3
    >>> e[0]
    u'Problems'
    >>> try:
    ...    raise e
    ... except VException:
    ...    print('caught an exception')
    ...
    caught an exception

    The exception can be constructed as

      ``VException([0 or more <obj>], [lazy=bool])``

    If lazy=True (default) *obj* values are are lazy-converted to
    :class:`VEntity`\ , otherwise they must be :class:`VEntity`\ .

    Example use:

    >>> from versile.orb.entity import *
    >>> VException(VInteger(4), VBoolean(False), VBytes(b'12345'))
    (4, False, '12345')
    >>> VException(4, False, b'12345')
    (4, False, '12345')

    """

    def __setattr__(self, *args):
        raise TypeError("can't modify immutable instance")
    __delattr__ = __setattr__

    def __init__(self, *args, **keywords):
        lazy = True
        for key, val in keywords.items():
            if key == 'lazy':
                lazy = val
            else:
                raise VException('Unknown keyword argument')
        if lazy:
            v_args = []
            for arg in args:
                v_args.append(VEntity._v_lazy(arg))
        else:
            v_args = args
            for arg in args:
                if not isinstance(arg, VEntity):
                    raise VEntityError('VException arguments must be VEntity')
        n_args = VEntity._v_lazy_native(v_args)
        Exception.__init__(self, *n_args)
        super(VException, self).__setattr__('_v_value', tuple(v_args))

    @classmethod
    def _v_converter(cls, obj):
        if isinstance(obj, VException):
            return (None, [obj])
        elif isinstance(obj, Exception):
            return (cls, list(obj.args))
        else:
            raise VEntityError('Not supported type for VException lazy conv.')

    def _v_native_converter(self):
        return (None, [self])

    def _v_native(self, deep=True):
        return self

    def _v_encode(self, context, explicit=True):
        if explicit:
            if _pyver == 2:
                header = [_s2b(_b_chr(VEntityCode.VEXCEPTION))]
            else:
                header = [bytes((VEntityCode.VEXCEPTION,))]
        else:
            header = []
        embedded = [(VTuple(self._v_value), False)]
        return (header, embedded, [])

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VExceptionDecoder(context, explicit)

    # Additional left-only list related operator overloads
    def __contains__(self, val):
        for obj in self._v_value:
            if obj == val:
                return True
        return False

    def __countOf__(self, val):
        count = 0
        for obj in self._v_value:
            if obj == val:
                count += 1
        return count

    def __getitem__(self, index):
        return VEntity._v_lazy(self._v_value[index])

    def __indexOf__(self, val):
        count = 0
        for obj in self._v_value:
            if obj == val:
                return count
            count += 1
        raise ValueError('Value not in list')

    def __len__(self):
        return len(self._v_value)

    def __iter__(self):
        return iter(self._v_value)

    # Operator overload. Skipped: floordiv, mod, truediv, concat, abs, inv,
    # neg, pos
    __lt__        = __rlt__       =  _meta_op2(operator.lt, cast=False)
    __le__        = __rle__       =  _meta_op2(operator.le, cast=False)
    __eq__        = __req__       =  _meta_op2(operator.eq, cast=False)
    __ne__        = __rne__       =  _meta_op2(operator.ne, cast=False)
    __ge__        = __rge__       =  _meta_op2(operator.ge, cast=False)
    __gt__        = __rgt__       =  _meta_op2(operator.gt, cast=False)
    __add__       = __radd__      =  _meta_op2(operator.add, cast=True)
    __and__       = __rand__      =  _meta_op2(operator.and_, cast=True)
    __lshift__    = __rlshift__   =  _meta_op2(operator.lshift, cast=True)
    __mul__       = __rmul__      =  _meta_op2(operator.mul, cast=True)
    __or__        = __ror__       =  _meta_op2(operator.or_, cast=True)
    __pow__       = __rpow__      =  _meta_op2(operator.pow, cast=True)
    __rshift__    = __rrshift__   =  _meta_op2(operator.rshift, cast=True)
    __sub__       = __rsub__      =  _meta_op2(operator.sub, cast=True)
    __xor__       = __rxor__      =  _meta_op2(operator.xor, cast=True)
    __truth__                     =  _meta_op1(operator.truth, cast=False)
    __index__                     =  _meta_op1(operator.index, cast=False)

    def __hash__(self):
        return hash(self._v_value)

    def __str__(self):
        return self._v_value.__str__()

    def __unicode__(self):
        return unicode(self._v_value)

    def __repr__(self):
        return self._v_value.__repr__()


class VExceptionDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VException` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VExceptionDecoder, self).__init__(context)
        self.__explicit = explicit
        self.__result = None
        self.__have_code = False

    def decode_header(self, data):
        if self.__result is not None:
            return (0, True, 2, 0)
        elif not data:
            return (0, False, 2, 0)

        num_read = 0
        if not self.__have_code:
            if self.__explicit:
                if _pyver == 2:
                    code = _b_ord(data.pop(1))
                else:
                    code = data.pop(1)[0]
                num_read += 1
                if code == VEntityCode.VEXCEPTION:
                    self.__have_code = True
                else:
                    raise VReaderError('Invalid VException code')
        return (num_read, True, 2, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        return (iter([VTuple._v_decoder(self.context, explicit=False)]), 1)

    def put_embedded_results(self, result):
        values = list(iter(result[0]))
        self.__result = VException(*values)

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class VTagged(VEntity):
    """Implementation of the :term:`VP` VTagged data type.

    :class:`VTagged` holds a :class:`VEntity` *value* and an ordered
    list of :class:`VEntity` *tags*\ . It exists primarily to enable
    higher-level protocols to define higher-level data types which are
    derived from library :class:`VEntity` data types.

    Example use:

    >>> from versile.orb.entity import *
    >>> temp = VTagged(20, (u'unit', u'Celsius'), (u'location', u'Iceland'))
    >>> temp.value
    20
    >>> temp.tags
    ((u'unit', u'Celsius'), (u'location', u'Iceland'))

    A :class:`VTagged` object by itself is a 'dumb' object, the value
    and tags are just entities and the :class:`VTagged` does not know
    how to interpret them or what they mean. It is up to higher level
    protocols to define tag formats and assign meaning to tags.

    :param value: entity value
    :param tags:  entity tags
    :param kargs: lazy=[True|False]
    :raises:      :exc:`exceptions.ValueError`

    If the keyword 'lazy' is True (the default) then *value* and
    *tags* are lazy-converted to :class:`VEntity`\ , otherwise
    they must be :class:`VEntity`\ .

    Example use:

    >>> from versile.orb.entity import *
    >>> t1 = VTagged(20)
    >>> t1.value
    20
    >>> t1.tags
    ()
    >>> t2 = VTagged(20, 'unit', 'Celsius')
    >>> t2.value
    20
    >>> t2.tags
    ('unit', 'Celsius')

    """

    def __setattr__(self, *args):
        raise TypeError("can't modify immutable instance")
    __delattr__ = __setattr__

    def __init__(self, value, *tags, **kargs):
        lazy = True
        for prop, val in kargs.items():
            if prop == 'lazy':
                lazy = val
            else:
                raise VException('Unknown keyword argument')
        if lazy:
            value = VEntity._v_lazy(value)
            v_tags = []
            for tag in tags:
                v_tags.append(VEntity._v_lazy(tag))
        else:
            if not isinstance(value, VEntity):
                raise VEntityError('Value must be a VEntity')
            v_tags = tags
            for tag in v_tags:
                if not isinstance(tag, VEntity):
                    raise VEntityError('Tags must be VEntity')

        merged = [value]
        merged.extend(tags)
        super(VTagged, self).__setattr__('_v_value', value)
        super(VTagged, self).__setattr__('_v_tags', tuple(v_tags))

    @property
    def value(self):
        """Holds the value set on the :class:`VTagged`"""
        return self._v_value

    @property
    def tags(self):
        """Holds the tags set on the :class:`VTagged`"""
        return self._v_tags

    @classmethod
    def _v_converter(cls, obj):
        if isinstance(obj, VTagged):
            return (None, [obj])
        else:
            raise VEntityError('Cannot lazy-convert to VTagged')

    def _v_native_converter(self):
        return (None, [self])

    def _v_native(self, deep=True):
        return self

    def _v_encode(self, context, explicit=True):
        if explicit:
            if _pyver == 2:
                header = [_s2b(_b_chr(VEntityCode.VTAGGED))]
            else:
                header = [bytes((VEntityCode.VTAGGED,))]
        else:
            header = []
        combined = (self._v_value, ) + self._v_tags
        embedded = [(VTuple(combined), False)]
        return (header, embedded, [])

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VTaggedDecoder(context, explicit)

    def __hash__(self):
        _list = [self._v_value] + list(self._v_tags)
        return hash(tuple(_list))

    def __str__(self):
        if _pyver == 2:
            _fmt = b'VTagged(%s:%s)'
        else:
            _fmt = 'VTagged(%s:%s)'
        return _fmt % (self._v_value.__str__(), self._v_tags.__str__())

    def __unicode__(self):
        return 'VTagged(%s:%s)' % (unicode(self._v_value),
                                   unicode(self._v_tags))

    def __repr__(self):
        return repr(self.__str__())


class VTaggedDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VTagged` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VTaggedDecoder, self).__init__(context)
        self.__explicit = explicit
        self.__result = None
        self.__have_code = False

    def decode_header(self, data):
        if self.__result is not None:
            return (0, True, 2, 0)
        elif not data:
            return (0, False, 2, 0)

        num_read = 0
        if not self.__have_code:
            if self.__explicit:
                if _pyver == 2:
                    code = _b_ord(data.pop(1))
                else:
                    code = data.pop(1)[0]
                num_read += 1
                if code == VEntityCode.VTAGGED:
                    self.__have_code = True
                else:
                    raise VReaderError('Invalid VTagged code')
        return (num_read, True, 2, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        return (iter([VTuple._v_decoder(self.context, explicit=False)]), 1)

    def put_embedded_results(self, result):
        result = list(iter(result[0]))
        if len(result) < 0:
            raise VEntityReaderError('Malformed VTagged encoding - no value')
        value = result[0]
        tags = result[1:]
        self.__result = VTagged(value, *tags)

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class VTaggedParser(object):
    """Parser for :term:`VER` encoded entities.

    The role of the parser is typically to resolve a set of
    specifications for higher-level :term:`VER` data types which are
    encoded as :class:`VTagged`\ , and to instantiate the appropriate
    implementing classes.

    """

    def decoder(self, obj):
        """Generates decoder for :class:`VTagged`.

        :param obj:  entity to convert
        :type  obj:  :class:`VTagged`
        :returns:    converter
        :rtype:      callable
        :raises:     :exc:`VTaggedParseError`

        Raises an exception if a converter could not be retreived for
        *obj*. The returned decoder should be the same format as the
        value returned by :meth:`VEntity._v_native_converter`\ . The
        converter should convert to a :class:`VEntity` representation.

        Default raises :exc:`VTaggedParseUnknown`\ , derived classes
        should override.

        """
        raise VTaggedParseUnknown()

    def native_decoder(self, obj):
        """Generates decoder for decoding to a native format

        See :meth:`decoder`\ . The returned decoder has an added
        conversion step which tries to lazy-convert :meth:`decoder`
        output to a native representation.

        """
        f, args = self.decoder(obj)
        def _lazy_converter(args):
            decoded = f(args)
            return VEntity._v_lazy_native(decoded)
        return (_lazy_converter, args)

    def converter(self, obj):
        """Generates converter for converting to :class:`VEntity`\ .

        :param obj: object to convert
        :returns:   converter
        :rtype:     callable
        :raises:    :exc:`VTaggedParseError`, :exc:`VTaggedParseUnknown`

        Raises an exception if a converter could not be retreived for
        *obj*. The returned converter should be the same format as the
        value returned by :meth:`VEntity._v_converter`\ .

        Default raises :exc:`VTaggedParseUnknown`\ , derived classes
        should override.

        """
        raise VTaggedParseUnknown()


class VTaggedParseError(Exception):
    """:class:`VTagged` parser error."""


class VTaggedParseUnknown(Exception):
    """:class:`VTagged` format not supported by parser."""


class VObject(VEntity, VLockable):
    """Implementation of the :term:`VP` VObject data type.

    :param processor: processor for executing method calls on this object
    :type  processor: :class:`versile.common.processor.VProcessor`

    :class:`VObject` is an object which can be remotely referenced.

    Object behavior should be implemented by overloading
    :meth:`_v_execute`\ . See :ref:`lib_entities` for more information
    regarding use.

    If a processor is not registered, then in order to execute
    asynchronous remote methods either a default processor needs
    to be set on the VObject class, or a processor must be
    provided for the method call.

    A processor can be set or changed later by calling
    :meth:`_v_set_processor`\ .

    As the class inherits from :class:`versile.common.util.VLockable`
    it can be used as a lock in 'with' statements, enabling
    synchronization on the object itself. This is used for providing
    thread-safety for some atomic internal operations such as
    :meth:`_v_proxy`\ .

    .. automethod:: _v_call
    .. automethod:: _v_encode
    .. automethod:: _v_execute
    .. automethod:: _v_proxy
    .. automethod:: _v_raw_encoder
    .. automethod:: _v_set_class_processor
    .. automethod:: _v_set_processor
    .. automethod:: _v_set_proxy_factory

    """

    # Global class processor - used when processor not set on the object
    _v_class_processor = None

    @classmethod
    def _v_set_class_processor(cls, processor, lazy=True):
        """Sets a default processor for the class.

        :param processor: the processor to set
        :type  processor: :class:`versile.common.processor.VProcessor`
        :param lazy:      if True, lazy-set class processor
        :type  lazy:      bool

        The class processor is used as a default processor for
        asynchronous remote calls to :meth:`_v_call` when a processor
        has not been set on the object itself.

        If lazy is True then the class processor will only be set if
        it has not been set already.

        """
        if not lazy or cls._v_class_processor is None:
            cls._v_class_processor = processor

    def __init__(self, processor=None):
        VEntity.__init__(self)
        VLockable.__init__(self)

        self.__processor = processor
        self.__proxy = None
        self.__proxy_lock = Lock()
        self.__proxy_factory = None

    def _v_set_processor(self, processor):
        """Sets a processor for the object.

        :param processor: the processor to set
        :type  processor: :class:`versile.common.processor.VProcessor`

        The processor is used as a default for the object for
        asynchronous remote calls to :meth:`_v_call`\ .

        """
        self.__processor = processor

    def _v_call(self, *args, **kargs):
        """Perform a remote call on the object.

        :param args:  call parameters passed to the method
        :param kargs: see below
        :returns:     call return value *or* call reference
        :rtype:       :class:`VEntity`, lazy-convertible, :class:`VObjectCall`
        :raises:      :exc:`VException`\ , :exc:`VCallError`\ ,
                      :exc:`VSimulatedException`

        The 'args' parameter holds all externally provided data for
        the call. The interpretation is implementation specific,
        e.g. a common convention is to use the first argument as a
        'method name' for the call, however this is not required.

        Optional keyword arguments:

        +---------+-------------------------------------------------------+
        | Keyword | Description                                           |
        +=========+=======================================================+
        | nowait  | If set return :class:`VObjectCall` instead of result  |
        +---------+-------------------------------------------------------+
        | nores   | If set then result value is always None               |
        +---------+-------------------------------------------------------+
        | oneway  | If set then no call result or exception is provided   |
        +---------+-------------------------------------------------------+
        | ctx     | If set, ctx is a 'context' for the call               |
        +---------+-------------------------------------------------------+
        | vchk    | If set, perform 'vchk validation' on provided checks  |
        +---------+-------------------------------------------------------+

        The method invokes :meth:`_v_execute` to perform the actual
        call execution.

        When the call is performed as non-blocking by specifying
        *nowait* or *oneway* then the call will be scheduled for
        execution by the object's processor. If no processor or class
        processor is set then an exception is raised.

        If an exception other than :exc:`VCallError` or
        :exc:`VSimulatedException` is raised by :meth:`_v_execute`
        then an attempt is made to lazy-convert the exception to a
        VException. If lazy-conversion fails then the exception is
        replaced by a :exc:`VCallError`\ . If
        :exc:`VSimulatedException` was raised then lazy-conversion is
        performed on the :attr:`VSimulatedException.value` and if the
        result is not an exception then it is re-wrapped as a
        :exc:`VSimulatedException`\ .

        When *oneway* is set, then the method returns None, there is
        no result and the call does not provide any feedback regarding
        call completion or any exceptions raised.

        When 'vchk' is set, then :func:`versile.orb.validate.vchk`
        validation is performed with the provided value as validation
        criteria. If the value is a list or tuple then the elements
        are used as validation criteria, otherwise the provided value
        is used as a single validation criteria.

        """
        nowait = nores = oneway = False
        ctx = checks = None
        for key, val in kargs.items():
            if key == 'nowait':
                nowait = bool(val)
            elif key == 'nores':
                nores = bool(val)
            elif key == 'oneway':
                oneway = bool(val)
            elif key == 'ctx':
                ctx = val
            elif key == 'vchk':
                if isinstance(val, (list, tuple)):
                    checks = tuple(val)
                else:
                    checks = (val,)
            else:
                raise TypeError('Invalid keyword argument')

        if nowait or oneway:
            if not self._v_processor:
                # Asynchronous operation requires a processor
                raise VCallError('No object processor')
            call = VObjectCall(checks=checks)
            def execute():
                try:
                    result = self._v_execute(*args, ctx=ctx)
                except Exception as e:
                    if not oneway:
                        if not isinstance(e, VCallError):
                            if isinstance(e, VSimulatedException):
                                e = e.value
                            try:
                                e = VEntity._v_lazy(e)
                            except TypeError:
                                e = VCallError()
                            if not isinstance(e, Exception):
                                e = VSimulatedException(e)
                        call.push_exception(e)
                else:
                    if not oneway:
                        if isinstance(result, VPending):
                            def _callback(_result):
                                if nores:
                                    _result = None
                                call.push_result(_result)
                            def _failback(_failure):
                                e = _failure.value
                                if not isinstance(e, VCallError):
                                    if isinstance(e, VSimulatedException):
                                        e = e.value
                                    try:
                                        e = VEntity._v_lazy(e)
                                    except TypeError:
                                        e = VCallError()
                                    if not isinstance(e, Exception):
                                        e = VSimulatedException(e)
                                call.push_exception(e)
                            result.add_callpair(_callback, _failback)
                        else:
                            if nores:
                                result = None
                            call.push_result(result)
            self._v_processor.queue_call(execute)
            if oneway:
                return None
            else:
                return call
        else:
            try:
                result = self._v_execute(*args, ctx=ctx)
            except Exception as e:
                if not isinstance(e, VCallError):
                    if isinstance(e, VSimulatedException):
                        e = e.value
                    try:
                        # NEW: include a trace with VCallError
                        _trace = traceback.format_exc()
                        e = VEntity._v_lazy(e)
                    except TypeError:
                        e = VCallError(e, _trace)
                    if not isinstance(e, Exception):
                        e = VSimulatedException(e)
                raise e
            else:
                if isinstance(result, VPending):
                    call = VObjectCall(checks=checks)
                    def _callback(_result):
                        if nores:
                            _result = None
                        call.push_result(_result)
                    def _failback(_failure):
                        e = _failure.value
                        if not isinstance(e, VCallError):
                            if isinstance(e, VSimulatedException):
                                e = e.value
                            try:
                                # NEW: include a trace with VCallError
                                _trace = traceback.format_exc()
                                e = VEntity._v_lazy(e)
                            except TypeError:
                                e = VCallError(e, _trace)
                            if not isinstance(e, Exception):
                                e = VSimulatedException(e)
                        call.push_exception(e)
                    result.add_callpair(_callback, _failback)
                    return call.result()
                else:
                    if nores:
                        result = None
                    return result

    @classmethod
    def _v_converter(cls, obj):
        if isinstance(obj, VObject):
            return (None, [obj])
        else:
            raise VEntityError('Cannot lazy-convert to VObject')

    def _v_native_converter(self):
        return (None, [self._v_proxy()])

    def _v_native(self, deep=True):
        return self._v_proxy()

    def _v_encode(self, context, explicit=True):
        """Returns the object's serialized byte encoding.

        See :meth:`VEntity._v_encode` for information about parameters
        and general usage.

        A :class:`VObject` requires a :class:`VObjectIOContext` for
        the serialization. Also note that the serialized
        representation is only value for the particular I/O context as
        long as that context exists. See :ref:`lib_entities` for more
        information regarding serializing :class:`VObject` data.

        .. note::

            The last point is important; the only thing linking an
            object to a serialized ID is the context object. When that
            context no longer exists, the ID no longer holds any
            meaning.

        """
        if not isinstance(context, VObjectIOContext):
            raise VEntityError('Encoding VObject requires an object context')
        if _pyver == 2:
            header = [_s2b(_b_chr(VEntityCode.VREF_LOCAL))]
        else:
            header = [bytes((VEntityCode.VREF_LOCAL,))]
        peer_id = context._local_to_peer_id(self, lazy=True)
        context._local_add_send(peer_id)
        return (header, [(VInteger(peer_id), False)], [])

    def _v_raw_encoder(self):
        """Returns an object which has a method for writing 'untagged' format.

        :returns: object with a '_v_encode' method for 'untagged' writing

        This method can be used for creating :class:`VTagged` based
        overloaded encoding formats for :class:`VObject`\ , to avoid
        infinite recursion when the :class:`VObject` itself has to be
        referenced inside the encoded format.

        """
        return _VObjectRawEncoder(self)

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VObjectDecoder(context, explicit)

    def _v_proxy(self):
        """Retreives (and lazy-creates) a :class:`VProxy` for this object.

        :returns: a proxy to this object
        :rtype:   :class:`VProxy`

        """
        self.__proxy_lock.acquire()
        try:
            if self.__proxy:
                proxy = self.__proxy()
                if proxy:
                    return proxy
            if self.__proxy_factory:
                proxy = self.__proxy_factory(self)
            else:
                proxy = VProxy(self)
            self.__proxy = weakref.ref(proxy)
        finally:
            self.__proxy_lock.release()
        return proxy

    def _v_set_proxy_factory(self, factory):
        """Sets a factory for creating object proxies.

        :param factory: a callable which produces a :class:`VProxy`
        :type  factory: callable

        Intended for use by implementations of higher level objects.

        """
        self.__proxy_factory = factory

    def __get_processor(self):
        if self.__processor:
            return self.__processor
        else:
            return self._v_class_processor
    def __set_processor(self, processor):
        self.__processor = processor
    _v_processor = property(__get_processor, __set_processor)
    """Holds a processor set on the object, or the class processor."""

    def _v_execute(self, *args, **kargs):
        """Execute a remote call on the object.

        :param args:  call arguments
        :param kargs: see below
        :returns:     call result
        :rtype:       :class:`VEntity` (or lazy-convertible),
                      :class:`versile.common.pending.VPending`
        :raises:      :class:`VCallError`\ , or exception raised by the call

        Keyword arguments:

        +---------+-------------------------------------------------------+
        | Keyword | Description                                           |
        +=========+=======================================================+
        | ctx     | If set, a context for the call                        |
        +---------+-------------------------------------------------------+

        The default implementation raises VCallError; sub-classes can
        override to implement remote method calls.

        .. note::

            This method is intended for class-internal implementation
            of method call execution and is not meant to be called
            externally. Remote calls should be performed by calling
            :meth:`_v_call` or use a :class:`VProxy`\ .

        The method may return
        :class:`versile.common.pending.VPending`, in which case it is
        interpreted by :meth:`_v_call` as an asynchronous call result
        whose result will be available later. Using this mechanism can
        a useful way to free up processor resources, not having to
        block a worker thread until a result is available when the
        call is made in an asynchronous mode.

        Note that when a call is invoked in a blocking mode on a local
        VObject via :meth:`_v_call` then the thread will block until
        the :class:`VPending` result is available (possibly forever),
        so use with caution.

        :class:`VCallError` should be raised if there is a problem
        with the specification of the call itself, e.g. the call could
        not be invoked because provided call parameters are not
        valid. When a call triggers an exception because of an error
        condition for the call's execution, a :class:`VException`
        should be raised.

        """
        raise VCallError()


class VObjectDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VObject` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VObjectDecoder, self).__init__(context)
        self.__result = None
        self.__have_code = False

    def decode_header(self, data):
        if self.__result is not None:
            return (0, True, 1, 0)
        elif not data:
            return (0, False, 1, 0)

        num_read = 0
        if not self.__have_code:
            if _pyver == 2:
                code = _b_ord(data.pop(1))
            else:
                code = data.pop(1)[0]
            num_read += 1
            if code == VEntityCode.VREF_REMOTE:
                self.__have_code = True
            else:
                raise VReaderError('Invalid VObject code')
        return (num_read, True, 1, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        return (iter([VInteger._v_decoder(self.context, explicit=False)]), 1)

    def put_embedded_results(self, result):
        peer_id = result[0]._v_native()
        try:
            obj = self.context._local_from_peer_id(peer_id)
        except VEntityError as e:
            raise VEntityReaderError(e.args)
        else:
            self.__result = obj

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class _VObjectRawEncoder(VObject):
    def __init__(self, obj):
        super(_VObjectRawEncoder, self).__init__()
        self.__obj = obj

    def _v_encode(self, context, explicit=True):
        return VObject._v_encode(self.__obj, context, explicit=explicit)


class VReference(VObject):
    """Reference to a remote :term:`VP` VObject data type.

    :class:`VReference` is a reference to a peer :class:`VObject`
    within the context of a :class:`VObjectIOContext`\ . See
    :ref:`lib_entities` for more information regarding use.

    :param context: the reference's owning context
    :type  context: :class:`VObjectIOContext`
    :param peer_id: the remote object's serialized object ID
    :type  peer_id: int, long

    A :class:`VReference` should normally not be directly
    instantiated by a program, instead a reference is generated by
    using a :class:`VEntityReader` on a serialized representation
    of a peer :class:`VObject`.

    .. automethod:: __del__
    .. automethod:: _v_call
    .. autoattribute:: _v_context

    """

    def __init__(self, context, peer_id):
        super(VReference, self).__init__()
        self._v_intctx = context
        self._v_peer_id = peer_id

    def __del__(self):
        """Overloaded destructor.

        The destructor notifies the :class:`VObjectIOContext` of the
        :class:`VReference` of the dereference event. This enables the
        context to perform follow-up action. The functionality is used
        e.g. by a link to send a remote dereference message to the
        link's peer.

        """
        self._v_intctx._ref_deref(self._v_peer_id)

    @abstract
    def _v_call(self, *args, **kargs):
        """Performs a remote call on the object.

        See :meth:`VObject._v_call`\ for general usage and arguments.

        This method is abstract and should be implemented by derived
        classes.

        """
        raise NotImplementedError()

    @classmethod
    def _v_converter(cls, obj):
        if isinstance(obj, VReference):
            return (None, [obj])
        else:
            raise VEntityError('Cannot lazy-convert to VObject')

    def _v_encode(self, context, explicit=True):
        if not isinstance(context, VObjectIOContext):
            raise VEntityError('Encoding VReference requires object context')
        # If contexts do not match encode as a VObject
        if context is not self._v_intctx:
            super_encode = super(VReference, self)._v_encode
            return super_encode(context=context, explicit=explicit)

        if _pyver == 2:
            header = [_s2b(_b_chr(VEntityCode.VREF_REMOTE))]
        else:
            header = [bytes((VEntityCode.VREF_REMOTE,))]
        return (header, [(VInteger(self._v_peer_id), False)], [])

    def _v_raw_encoder(self):
        """Returns an object which has a method for writing 'untagged' format.

        :returns: object with a '_v_encode' method for 'untagged' writing

        This method can be used for creating :class:`VTagged` based
        overloaded encoding formats for :class:`VObject`\ , to avoid
        infinite recursion when the :class:`VObject` itself has to be
        referenced inside the encoded format.

        """
        return _VReferenceRawEncoder(self)

    @classmethod
    def _v_decoder(cls, context, explicit=True):
        return VReferenceDecoder(context, explicit)

    @property
    def _v_context(self):
        """The reference's context (:class:`VObjectIOContext`\ )."""
        return self._v_intctx


class VReferenceDecoder(VEntityDecoderBase):
    """Decoder for reading a :class:`VReference` from serialized data."""

    def __init__(self, context, explicit=True):
        super(VReferenceDecoder, self).__init__(context)
        self.__result = None
        self.__have_code = False

    def decode_header(self, data):
        if self.__result is not None:
            return (0, True, 1, 0)
        elif not data:
            return (0, False, 1, 0)

        num_read = 0
        if not self.__have_code:
            if _pyver == 2:
                code = _b_ord(data.pop(1))
            else:
                code = data.pop(1)[0]
            num_read += 1
            if code == VEntityCode.VREF_LOCAL:
                self.__have_code = True
            else:
                raise VReaderError('Invalid VObject code')
        return (num_read, True, 1, 0)

    def get_payload_len(self):
        return 0

    def get_embedded_decoders(self):
        context = self.context
        return (iter([VInteger._v_decoder(context, explicit=False)]), 1)

    def put_embedded_results(self, result):
        peer_id = result[0]._v_native()
        context = self.context
        ref = context._ref_from_peer_id(peer_id, lazy=True)
        context._ref_add_recv(peer_id)
        self.__result = ref

    def decode_payload(self, data):
        return (0, True)

    def result(self):
        if self.__result is not None:
            return self.__result
        else:
            raise VEntityReaderError('Result not ready')


class _VReferenceRawEncoder(VObject):
    def __init__(self, ref):
        super(_VReferenceRawEncoder, self).__init__()
        self.__ref = ref

    def _v_encode(self, context, explicit=True):
        return VReference._v_encode(self.__ref, context, explicit=explicit)


class VProxy(object):
    """Proxy for a :class:`VObject` or :class:`VReference`\ .

    Overrides __getattr__ to generate a callable which attempts to
    invoke a remote method call on the proxied object, using the
    attribute name as the first argument for the remote call.

    A proxy is normally generated by calling :class:`VObject._v_proxy`
    on the source object.

    Below is an example of using a proxy:

    >>> from versile.orb.entity import *
    >>> class Adder(VObject):
    ...   def _v_execute(self, *args, **kargs):
    ...     if len(args) != 3 or args[0] != u'add':
    ...       raise VCallError()
    ...     return args[1] + args[2]
    ...
    >>> adder = Adder()
    >>> proxy = adder._v_proxy()
    >>> type(proxy.add)
    <class 'versile.orb.entity._VProxyMethod'>
    >>> proxy.add(2, 5)
    7

    See :ref:`lib_entities` for more information how a :class:`VProxy`
    can be used, including use of the special 'meta' attribute to make
    'meta calls' as defined by the :term:`VP` specification.

    When lazy-conversion is enabled on a VOL link associated with a
    proxy object which references a remote object (which is the
    default), then input arguments for remote calls are lazy-converted
    (if possible) to :class:`VEntity` derived types using
    :meth:`VEntity._v_lazy` standard lazy conversion plus any lazy
    conversion implemented by modules associated with the links.

    Similarly, when lazy-native conversion is enabled on a VOL link
    associated with a proxy object which references a remote object
    (which is the default), then :class:`VEntity` derived return
    values of remote calls are lazy-native converted (if possible) to
    a native type or another appropriate type using
    :meth:`VEntity._v_lazy_native` standard lazy native conversion,
    plus any lazy native conversion implemented by modules associated
    with the links.

    :param obj: object which is proxied
    :type  obj: :class:`VObject`


    .. automethod:: __call__
    .. automethod:: __getattr__
    .. automethod:: __dir__

    """

    def __init__(self, obj):
        if not isinstance(obj, VObject):
            raise TypeError('Object must be a VObject')
        self._v_object = obj

    def __call__(self):
        """Returns the object proxied by this object.

        :returns: proxied object
        :rtype:   :class:`VObject`, :class:`VReference`

        """
        return super(VProxy, self).__getattribute__('_v_object')

    def __getattr__(self, attr):
        """Overloads to return object for calling remote methods.

        The returned object can be called through __call__ , and the
        arguments will be passed to the object's call() method with
        the provided arguments and keyword arguments.

        If attr is of type 'bytes', it will be converted to unicode as
        the method name passed to __call__ - which may trigger an
        exception if conversion cannot be made.

        When the attribute u'meta' is provided, the returned object
        will have additional functionality. In addition to making it
        possible to call a remote method named 'meta' on the object
        (if it exists), it aliases getattribute on the object to
        return an object for a meta-call on the object.

        An exception to the above is if *attr* starts with '_v_',
        which is the namespace reserved for internal use. When *attr*
        has this prefix, getattr performs
        ``return getattr(self(), attr)``\ .

        """
        if attr.startswith('_v_'):
            return getattr(self(), attr)
        if isinstance(attr, bytes):
            attr = unicode(attr)
        if attr == 'meta':
            return _VProxyMethodAndOrMeta(self, attr)
        else:
            return _VProxyMethod(self, attr)

    def __dir__(self):
        """Returns a list of exposed remote method names.

        Returns same result as calling meta.methods() on the
        object. This allows e.g. tab extensions to be used for exposed
        remote methods in an interactive python shell.

        """
        return list(self.meta.methods())

    @classmethod
    def _v_converter(cls, obj):
        if isinstance(obj, VProxy):
            obj = super(VProxy, obj).__getattribute__('_v_object')
            return (None, [obj])
        else:
            raise VEntityError('Cannot lazy-convert from non-VProxy')


class _VProxyMethod(object):
    """Callable for performing a remote method call for a set method name."""
    def __init__(self, proxy, method_name):
        self._obj = proxy()
        self._method_name = method_name

    def __call__(self, *args, **kargs):
        return self._obj._v_call(self._method_name, *args, **kargs)


class _VProxyMethodAndOrMeta(object):
    """Callable for performing a remote method call for a method name 'meta'.

    Also provides further aliasing to generate another callable with
    None as the initial argument and the aliased attribute as the
    'meta call' type method name.

    """
    def __init__(self, proxy, method_name):
        self._obj = proxy()
        self._method_name = method_name

    def __call__(self, *args, **kargs):
        super_getattr = super(_VProxyMethodAndOrMeta, self).__getattribute__
        obj = super_getattr('_obj')
        method_name = super_getattr('_method_name')
        return obj._v_call(method_name, *args, **kargs)

    def __getattribute__(self, attr):
        """Return an object which calls a meta method by given name.

        If attr is of type 'bytes', it will be converted to unicode as
        the method name passed to __call__ - which may trigger an
        exception if conversion cannot be made.

        """
        if isinstance(attr, bytes):
            attr = unicode(attr)
        obj = super(_VProxyMethodAndOrMeta, self).__getattribute__('_obj')
        proxy = obj._v_proxy()
        return _VProxyMetaMethod(proxy, attr)


class _VProxyMetaMethod(object):
    """Encapsulates access to a remote method call()."""
    def __init__(self, proxy, method_name):
        self._obj = proxy()
        self._method_name = method_name

    def __call__(self, *args, **kargs):
        return self._obj._v_call(None, self._method_name, *args, **kargs)


class VObjectCall(VResult):
    """Holds a reference to a remote call made on a :class:`VObject`\ .

    :param checks: checks performed on call result (or None)

    A :class:`VObjectCall` is generated by :meth:`VObject._v_call`
    when an asynchronous call is performed. It should normally not be
    instantiated directly by other code.

    """

    def __init__(self, checks=None):
        super(VObjectCall, self).__init__()
        self._checks = checks

    def push_result(self, result):
        if self._checks:
            from versile.orb.validate import vchk
            try:
                vchk(result, *(self._checks))
            except Exception as e:
                return self.push_exception(e)
        super(VObjectCall, self).push_result(result)


class VReferenceCall(VObjectCall):
    """Holds a reference to a remote call to a :class:`VObject`\ .

    Similar use as :class:`VObjectCall`\ .

    .. automethod:: __del__

    """

    def __init__(self, link, call_id, checks=None):
        super(VReferenceCall, self).__init__(checks=checks)
        self._link = link
        self._call_id = call_id

    def __del__(self):
        """Discards the call from the link's reference call dictionary."""
        if self._link:
            self._link._remove_ref_call(self._call_id)

    def _cancel(self):
        """Discards the call from the link's reference call dictionary."""
        with self:
            if self._link:
                self._link._remove_ref_call(self._call_id)

    def _post_push_cleanup(self):
        if self._link:
            self._link._remove_ref_call(self._call_id)
            self._link = None


class VCallError(Exception):
    """Indicates a VObject call could not be performed.

    The exception indicates an error with resolving how to perform the
    (e.g. method could not be resolved), and should not be confused
    with exceptions raised by a valid call.

    """


class VCallContext(dict, VLockable):
    """Context object for remote calls.

    A call context object can be used by links and other communication
    contexts to hold data which can be exposed internally as 'context
    information' to internal methods implementing published external
    methods, providing information about the context and providing a
    mechanism for holding session data.

    Some operations have been overloaded with thread safe versions
    which acquire a lock on the object when performing: get, pop,
    __getitem__, __setitem__, __delitem__. For other operations that
    are not thread-safe, or performing multiple operations which
    affect thread safety, caller should acquire a lock to the object
    first.

    .. automethod:: _v_set_network_peer
    .. automethod:: _v_set_identity
    .. automethod:: _v_set_claimed_identity
    .. automethod:: _v_set_credentials
    .. automethod:: _v_set_sec_protocol
    .. automethod:: _v_authorize

    """

    def __init__(self):
        dict.__init__(self)
        VLockable.__init__(self)
        self._network_peer = None
        self._credentials = (None, tuple())
        self._claimed_identity = None
        self._identity = None
        self._sec_protocol = None
        self._authorized = False

    @property
    def network_peer(self):
        """Identifies the network peer this context is connected to."""
        with self:
            return self._network_peer

    @property
    def identity(self):
        """Identifies a verified identity assumed by peer.

        When this attribute is set, it implies use of the peer's right
        to use this identity has been verified. It will only be provided
        if :attr:`authorized` is True.

        """
        with self:
            if self.authorized:
                return self._identity
            else:
                return None

    @property
    def claimed_identity(self):
        """Identifies an (unauthenticated) identity claimed by the peer.

        Note that this is simply an identity claimed by the peer,
        which has not been validated or in any way authorized.

        """
        with self:
            return self._claimed_identity

    @property
    def credentials(self):
        """Credentials peer used to authenticate itself (key, cert_chain).

        When *key* is available, it should have been validated to be
        held by the communication peer.

        *cert_chain* may have been validated to be a valid chain which
        is a valid chain for *key*, however this is not guaranteed and
        this setter does not perform such a check. In order to be
        sure, the certificate chain must be validated when used.

        """
        with self:
            return self._credentials

    @property
    def sec_protocol(self):
        """Protocol used for securing handshake of credentials (unicode)."""
        with self:
            return self._sec_protocol

    @property
    def authorized(self):
        """True if peer has been authenticated."""
        with self:
            return self._authorized

    def _v_set_network_peer(self, peer):
        """Sets network peer.

        :param peer: network peer identifier

        """
        with self:
            self._network_peer = peer

    def _v_set_claimed_identity(self, identity):
        """Sets the peer's claimed identity.

        :param identity: identity claimed by peer

        The 'claimed identitiy' is an identity the peer has claimed it
        is assuming. It does not imply this is a valid identity for
        the peer, and it does not imply any authorization of the peer
        for this identity.

        """
        with self:
            self._claimed_identity = identity

    def _v_set_identity(self, identity):
        """Sets the peer's verified identity.

        :param identity: identity verified to be assumed by peer

        This should only be set for an identity which is known to
        belong to and be assumed by peer. Also, :attr:`authorized`
        must be True in order for the peer's verified identity to be
        available as :attr:`identity`\ .

        """
        with self:
            self._claimed_identity = identity

    def _v_set_credentials(self, key, cert_chain=tuple()):
        """Set credentials.

        :param key:        key peer authenticated with
        :type  key:        :class:`versile.crypto.VAsymmetricKey`
        :param cert_chain: certificate chain for peer key
        :type  cert_chain: tuple

        *cert_chain* is a tuple of
        :class:`versile.crypto.x509.cert.VX509Certificate`\ .

        This method should only be called with a *key* argument that
        is validated to be held by the communication peer. Otherwise,
        authorization could be subject to man-in-the-middle attacks.

        .. warning::

            Never call this method with a *key* argument which has not been
            validated by a secure protocol to be held by the peer.

        The certificate chain may have been validated to be a valid
        chain which is a valid chain for *key*, however this is not
        guaranteed and this setter does not perform such a check. In
        order to be sure, the certificate chain must be validated when
        used.

        """
        with self:
            self._credentials = (key, cert_chain)

    def _v_set_sec_protocol(self, protocol):
        """Set secure protocol name.

        :param protocol: name of secure protocol
        :type  protocol: unicode

        """
        with self:
            self._sec_protocol = protocol

    def _v_authorize(self, authorized=True):
        """Sets authorization status."""
        with self:
            self._authorized = authorized

    def get(self, name, *args):
        with self:
            return dict.get(self, name, *args)

    def pop(self, name, *args):
        with self:
            return dict.pop(self, name, *args)

    def __getitem__(self, name):
        with self:
            return dict.__getitem__(self, name)

    def __setitem__(self, name, value):
        with self:
            return dict.__setitem__(self, name, value)

    def __delitem__(self, name):
        with self:
            return dict.__delitem__(self, name)


class VSimulatedException(Exception):
    """Wraps a non-exception value as an exception.

    :param value: the non-exception value held by this object

    The wrapper can be used to raise non-exception values from
    remotely callable methods (which is otherwise not allowed in
    Python); the owning link will then use the held value as the
    exception passed to the peer.

    A link can use this wrapper when it receives a raised exception as
    the result of a remote method call, when the result does not
    resolve as a subclass of :class:`exceptions.Exception`\ . The link
    should wrap the result using this class before providing as a
    method exception.

    """
    def __init__(self, value):
        super(VSimulatedException, self).__init__(value)

    @property
    def value(self):
        """Value held by the exception."""
        return self.args[0]


# This must come after class definitions so class names are defined.
# Decoders for VREF_LOCAL and VREF_REMOTE are swapped because
# decoding serialized data is performed from a peer context
_VENTITY_DECODE_GEN = { VEntityCode.VINT_POS    : VInteger._v_decoder,
                        VEntityCode.VINT_NEG    : VInteger._v_decoder,
                        VEntityCode.VBOOL_TRUE  : VBoolean._v_decoder,
                        VEntityCode.VBOOL_FALSE : VBoolean._v_decoder,
                        VEntityCode.VNONE       : VNone._v_decoder,
                        VEntityCode.VFLOAT_2    : VFloat._v_decoder,
                        VEntityCode.VFLOAT_10   : VFloat._v_decoder,
                        VEntityCode.VFLOAT_N    : VFloat._v_decoder,
                        VEntityCode.VTUPLE      : VTuple._v_decoder,
                        VEntityCode.VBYTES      : VBytes._v_decoder,
                        VEntityCode.VSTRING     : VString._v_decoder,
                        VEntityCode.VSTRING_ENC : VString._v_decoder,
                        VEntityCode.VEXCEPTION  : VException._v_decoder,
                        VEntityCode.VTAGGED     : VTagged._v_decoder,
                        VEntityCode.VREF_LOCAL  : VReference._v_decoder,
                        VEntityCode.VREF_REMOTE : VObject._v_decoder
                        }

# This must come after class definitions so class names are defined
_VENTITY_LAZY_CONVERTER = { int        : VInteger._v_converter,
                            bool       : VBoolean._v_converter,
                            type(None) : VNone._v_converter,
                            float      : VFloat._v_converter,
                            Decimal    : VFloat._v_converter,
                            tuple      : VTuple._v_converter,
                            bytes      : VBytes._v_converter,
                            VProxy     : VProxy._v_converter
                            }
if _pyver == 2:
    _VENTITY_LAZY_CONVERTER[long] = VInteger._v_converter
    _VENTITY_LAZY_CONVERTER[unicode] = VString._v_converter
else:
    _VENTITY_LAZY_CONVERTER[str] = VString._v_converter
