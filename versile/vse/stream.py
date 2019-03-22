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

"""Implements :term:`VSE` stream objects.

Importing registers :class:`VStreamModule` as a global module.

"""
from __future__ import print_function, unicode_literals

import collections
import threading
import time
import weakref

from versile.internal import _vexport, _v_silent, _pyver

from versile.common.iface import abstract
from versile.common.util import VByteBuffer, VLockable
from versile.orb.entity import VEntity, VTagged, VBytes, VException
from versile.orb.entity import VProxy, VInteger, VTuple, VCallError
from versile.orb.external import VExternal, publish
from versile.orb.module import VModule, VModuleResolver, VERBase
from versile.orb.validate import vchk, vtyp, vmin
from versile.orb.util import VSequenceCaller, VSequenceCallQueue
from versile.vse.const import VSECodes, VSEModuleCodes

__all__ = ['VByteFixedStreamerData', 'VByteSimpleFileStreamerData',
           'VByteStreamBuffer', 'VByteStreamer', 'VByteStreamerProxy',
           'VEntityFixedStreamerData', 'VEntityIteratorStreamerData',
           'VEntityStreamBuffer', 'VEntityStreamer', 'VEntityStreamerProxy',
           'VStream', 'VStreamBuffer', 'VStreamerData', 'VStreamer',
           'VStreamError', 'VStreamErrorCode', 'VStreamException',
           'VStreamFailure', 'VStreamInvalidPos', 'VStreamMode',
           'VStreamModule', 'VStreamObserver', 'VStreamPeer',
           'VStreamPos', 'VStreamTimeout']
__all__ = _vexport(__all__)


# Default values for stream operation peer limits

_BPKG = 10           # byte data max push packages
_BSIZE = 1000000     # byte data max size per package
_BLIM = _BPKG*_BSIZE # byte data rolling write limit
_EPKG = 10           # entity data max push packages
_ESIZE = 1000        # entity data max size per package
_ELIM = _EPKG*_ESIZE # entity data rolling write limit
_CALLS = 5           # max pending calls (in addition to push packages)


class VStreamException(Exception):
    """General stream operation exception."""


class VStreamError(VStreamException):
    """Stream operation error."""


class VStreamInvalidPos(VStreamError):
    """Stream position was invalidated by peer."""


class VStreamFailure(VStreamError):
    """Stream (permanent) failure."""


class VStreamTimeout(VStreamException):
    """Stream operation timeout."""


class VStreamMode(object):
    """Mode flag constants for streams."""

    READABLE = 0x0001
    """Mode bit for readable stream."""

    WRITABLE = 0x0002
    """Mode bit for writable stream."""

    START_BOUNDED = 0x0004
    """Mode bit for bounded stream data start position."""

    START_CAN_DEC = 0x0008
    """Mode bit indicating stream data start position may decrease."""

    START_CAN_INC = 0x0010
    """Mode bit indicating stream data start position may increase."""

    CAN_MOVE_START = 0x0020
    """Mode bit indicating stream is allowed to move start position."""

    END_BOUNDED = 0x0040
    """Mode bit for bounded stream data end position."""

    END_CAN_DEC = 0x0080
    """Mode bit indicating stream data end position may decrease."""

    END_CAN_INC = 0x0100
    """Mode bit indicating stream data end position may increase."""

    CAN_MOVE_END = 0x0200
    """Mode bit indicating stream is allowed to move end position."""

    SEEK_REW = 0x0400
    """Mode bit indicating reverse-seeking is allowed."""

    SEEK_FWD = 0x0800
    """Mode bit indicating forward-seeking is allowed."""

    FIXED_DATA = 0x1000
    """Mode bit indicating stream data cannot be modified by any source."""

    DATA_LOCK = 0x02000
    """Mode bit indicating stream data can only be modified by this source."""

    START_LOCK = 0x4000
    """Mode bit indicating start pos can only be modified by this streamer."""

    END_LOCK = 0x8000
    """Mode bit indicating end pos can only be modified by this streamer."""

    @classmethod
    def validate(cls, mode):
        """Validates whether provided mode is a valid combination.

        :param mode: bitwise OR of mode flags
        :type  mode: int
        :raises:     :exc:`VStreamError`

        Raises an exception if illegal combinations are found such as
        e.g.  combining 'writable' with 'const', or stream not being
        readable or writable.

        """
        if not mode & (cls.READABLE | cls.WRITABLE):
            raise VStreamError('Stream must be readable or writable')
        if mode & cls.WRITABLE and mode & cls.FIXED_DATA:
            raise VStreamError('Constant stream data cannot be writable')
        if mode & cls.CAN_MOVE_START and not mode & (cls.START_CAN_DEC |
                                                     cls.START_CAN_INC):
            raise VStreamError('Invalid start position move flag combination')
        if mode & cls.CAN_MOVE_END and not mode & (cls.END_CAN_DEC |
                                                   cls.END_CAN_INC):
            raise VStreamError('Invalid end position move flag combination')


class VStreamPos(object):
    """Constants for stream position references."""

    ABS = 1
    """Code for absolute position reference."""

    START = 2
    """Code for position reference relative to the data set start."""

    END = 3
    """Code for position reference relative to the data set end."""

    CURRENT = 4
    """Code for position reference relative to current position.

    This position reference is only used locally and is not allowed as
    a remote position reference, but must be converted to an absolute
    reference first. This is because buffering and other
    synchronization, which can cause 'current position' to be
    different for a local stream object and a connected peer stream
    object.

    """


class VStreamErrorCode(object):
    """Error codes for stream peer error notifications."""

    GENERAL = 1
    """General stream error for current context."""

    INVALID_POS = 2
    """Current position was invalidated (no longer in range of data set)."""

    @classmethod
    def exc_cls(cls, code):
        """Returns an exception class appropriate for the given code.

        :param code: stream error code
        :type  code: int
        :returns:    exception class

        """
        if code == cls.GENERAL:
            return VStreamError
        elif code == cls.INVALID_POS:
            return VStreamInvalidPos
        else:
            return VStreamError


@abstract
class VStreamerData(object):
    """Data which can be accessed with a :class:`VStreamer`\ .

    Stream data may support reading and/or writing, and other
    operations such as seek operations.

    A connected :class:`VStreamer` should be set up with mode settings
    which are appropriate for the features available on a connected
    :class:`VStreamerData` object. Also, a connected streamer must
    operate on the same data type as the stream data object.

    This class is abstract and should not be directly instantiated.

    .. automethod:: _notify_endpoints

    """

    NOTIFY_ENDPOINTS = 0x01
    """Notification flag for changes to stream data endpoints."""

    def __init__(self):
        self.__streamer = None
        self.__notify_flags = 0x00
        self.__notify_lock = threading.Lock()

    @abstract
    def read(self, max_num):
        """Reads data from current position.

        :param max_num: maximum elements to read
        :type  max_num: int
        :returns:       data read

        Returns empty data set if end-of-stream was reached for the
        current data set boundary. If less than *max_num* elements are
        read then this implies the (current) end-of-stream delimiter
        was reached after the returned data.

        The method should only be called by the object's controlling
        :class:`VStreamer`\ .

        The method may update streamer data endpoints. If a
        controlling streamer tracks streamer data endpoints, it should
        poll updated :attr:`endpoints` after calling this method to
        get new endpoint information.

        """
        raise NotImplementedError()

    @abstract
    def write(self, data):
        """Writes data at current position.

        :param data: data to write
        :raises:     :class:`VStreamError`

        Writing data will overwrite the corresponding data elements in
        the data set after the current position. The method must
        accept and 'write' all received data, otherwise it should
        raise an exception if all data could not be written.

        The method should only be called by the object's controlling
        :class:`VStreamer`\ .

        The method may update streamer data endpoints. If a
        controlling streamer tracks streamer data endpoints, it should
        poll updated :attr:`endpoints` after calling this method to
        get new endpoint information.

        """
        raise NotImplementedError()

    @abstract
    def seek(self, pos, pos_ref):
        """Repositions the data set to a new position.

        :param pos:     position relative to *pos_ref*
        :type  pos:     int
        :param pos_ref: position reference point
        :type  pos_ref: int
        :returns:       resulting (absolute) position
        :rtype:         int

        *pos_ref* can be :attr:`VStreamPos.ABS`\ ,
        :attr:`VStreamPos.CURRENT`\ , :attr:`VStreamPos.START` or
        :attr:`VStreamPos.END`\ .

        The method should only be called by the object's controlling
        :class:`VStreamer`\ .

        The method may update streamer data endpoints. If a
        controlling streamer tracks streamer data endpoints, it should
        poll updated :attr:`endpoints` after calling this method to
        get new endpoint information.

        """
        raise NotImplementedError()

    @abstract
    def trunc_before(self):
        """Truncate streamer data before current position.

        :raises: :exc:`VStreamError`

        When successfully called, the current position becomes the
        start position of the streamer data.

        The method must be implemented on derived classes which
        support the mode flags :attr:`VStreamMode.CAN_MOVE_START` and
        :attr:`VStreamMode.START_CAN_INC`\ .

        The method should only be called by the object's controlling
        :class:`VStreamer`\ .

        The method may update streamer data endpoints. If a
        controlling streamer tracks streamer data endpoints, it should
        poll updated :attr:`endpoints` after calling this method to
        get new endpoint information.

        """
        raise NotImplementedError()

    @abstract
    def trunc_after(self):
        """Truncate streamer data after current position.

        :raises: :exc:`VStreamError`

        When successfully called, the current position becomes the
        last element of the streamer data set.

        The method must be implemented on derived classes which
        support the mode flags :attr:`VStreamMode.CAN_MOVE_END` and
        :attr:`VStreamMode.END_CAN_DEC`\ .

        The method should only be called by the object's controlling
        :class:`VStreamer`\ .

        The method may update streamer data endpoints. If a
        controlling streamer tracks streamer data endpoints, it should
        poll updated :attr:`endpoints` after calling this method to
        get new endpoint information.

        """
        raise NotImplementedError()

    @abstract
    def close(self):
        """Closes access to streamer data.

        This enables streamer data resources to be freed up. Closing
        streamer data will close any current context, and opening new
        contexts after closing is not allowed.

        The method should only be called by the object's controlling
        :class:`VStreamer`\ .

        """
        raise NotImplementedError()

    def set_streamer(self, streamer):
        """Sets streamer for callbacks.

        :param streamer: connected streamer
        :type  streamer: :class:`VStreamer`
        :raises:         :class:`VStreamError`

        Will only hold a weak reference to connected streamer. Raises
        an exception if streamer already set.

        Notifications can be enabled with :meth:`enable_notifications`\ .

        """
        self.__notify_lock.acquire()
        try:
            if self.__streamer:
                raise VStreamError('Stream already registered')
            self.__streamer = weakref.ref(streamer)
        finally:
            self.__notify_lock.release()

    def enable_notifications(self, flags):
        """Enables notifications to a registered streamer.

        :param flags: bitwise OR of notifications to enable
        :type  flags: int
        :raises:      :class:`VStreamError`

        *flags* should be a bitwise OR of one or more of (currently only)
        :attr:`NOFITY_ENDPOINTS`

        """
        self.__notify_lock.acquire()
        try:
            self.__notify_flags |= flags
        finally:
            self.__notify_lock.release()

    def disable_notifications(self, flags):
        """Disables notifications to a registered streamer.

        Similar to :meth:`enable_notifications`\ , except this method
        disables notifications for the bits set in *flags*\ .

        """
        self.__notify_lock.acquire()
        try:
            self.__notify_flags |= flags
            self.__notify_flags ^= flags
        finally:
            self.__notify_lock.release()

    @abstract
    @property
    def pos(self):
        """Current (absolute) stream position"""
        raise NotImplementedError()

    @abstract
    @property
    def endpoints(self):
        """Current data end points as (first_pos, end_pos+1).

        If either endpoint is unbounded, it is represented instead as
        None.

        """
        raise NotImplementedError()

    @abstract
    @property
    def req_mode(self):
        """Required mode flags for streamer (mode_bits, mask)."""
        raise NotImplementedError()

    @abstract
    @property
    def opt_mode(self):
        """Optional mode flags for streamer (mode_bits)."""
        raise NotImplementedError()

    def _notify_endpoints(self):
        """Internal call to notify streamer of endpoint change.

        If a peer streamer has been registered with range change
        notification enabled, a notification is passed to the
        streamer.

        The notification should only be triggered whenever one of the
        end-point positions of the stream data changes, and it should
        not be called by the streamer data's controlling
        :class:`VStreamer` (which keeps track of the end-point effects
        of operations it performs itself).

        """
        self.__notify_lock.acquire()
        try:
            if (not self.__notify_flags & self.NOTIFY_ENDPOINTS
                or self.__streamer is None):
                return
            streamer = self.__streamer()
            if streamer is None:
                self.__streamer = None
                return
        finally:
            self.__notify_lock.release()
        try:
            streamer._notify_endpoints()
        except Exception as e:
            _v_silent(e)
            with self.__notify_lock:
                self.__notify_flags |= self.NOTIFY_ENDPOINTS
                self.__notify_flags ^= self.NOTIFY_ENDPOINTS


class VByteFixedStreamerData(VStreamerData):
    """Memory-cached read-only bytes data source for streaming.

    :param data: streamer data
    :type  data: bytes

    """

    def __init__(self, data):
        super(VByteFixedStreamerData, self).__init__()
        self._data = data
        self._len = len(data)
        self._pos = 0

    def read(self, max_num):
        if self._data is None:
            raise VStreamError('Streamer data was closed')
        start_pos = self._pos
        end_pos = start_pos + max_num
        end_pos = min(end_pos, self._len)
        result = self._data[start_pos:end_pos]
        self._pos += len(result)
        return result

    def seek(self, pos, pos_ref):
        if self._data is None:
            raise VStreamError('Streamer data was closed')
        if pos_ref == VStreamPos.END:
            pos += self._len
        elif pos_ref == VStreamPos.CURRENT:
            pos += self._pos
        elif pos_ref not in (VStreamPos.ABS, VStreamPos.START):
            raise VStreamError('Invalid seek pos reference')
        if pos < 0 or pos > self._len:
            raise VStreamError('Out-of-range seek position')
        self._pos = pos
        return self._pos

    def close(self):
        self._data = None

    @property
    def pos(self):
        return self._pos

    @property
    def endpoints(self):
        return (0, self._len)

    @property
    def req_mode(self):
        mode = (VStreamMode.READABLE | VStreamMode.START_BOUNDED |
                VStreamMode.END_BOUNDED | VStreamMode.FIXED_DATA)
        mask = (mode | VStreamMode.WRITABLE | VStreamMode.START_CAN_DEC |
                VStreamMode.START_CAN_INC | VStreamMode.CAN_MOVE_START |
                VStreamMode.END_CAN_DEC | VStreamMode.END_CAN_INC |
                VStreamMode.CAN_MOVE_END | VStreamMode.DATA_LOCK |
                VStreamMode.START_LOCK | VStreamMode.END_LOCK)
        return (mode, mask)

    @property
    def opt_mode(self):
        return VStreamMode.SEEK_REW | VStreamMode.SEEK_FWD


class VByteSimpleFileStreamerData(VStreamerData, VLockable):
    """Streamer data interface to a file.

    :param filename: name of file
    :type  filename: unicode
    :param fmode:    file mode for opening file
    :type  fmode:    unicode
    :param seek_rew: if True allow reverse-seeking
    :type  seek_rew: bool
    :param seek_fwd: if True allow forward-seeking
    :type  seek_fwd: bool
    :raises:         :exc:`exceptions.ValueError`

    The *fmode* argument is similar to :meth:`file.open`\ . Only
    binary mode is supported. If binary mode is not set, 'b' is
    appended to fmode. If text mode is specified (if *fmode* contains
    the character 't'), an exception is raised.

    This class is 'simple' in the sense it requires exclusive streamer
    data control of the file. It is assumed that the streamer data
    object has full control of the file, and no other process or code
    is modifying file content. This also implies multiple streamer
    data objects can operate on the same file if they are all set up
    in read-only mode, however if streamer data is writable then only
    one single streamer data object is allowed on any single file.

    The streamer data does not allow seeking past the current
    end-of-file. However, for a writable file it allows moving the
    end-point by writing past the current end-point.

    """

    def __init__(self, filename, fmode, seek_rew=False, seek_fwd=False):
        VStreamerData.__init__(self)
        VLockable.__init__(self)

        req_mode = VStreamMode.START_BOUNDED | VStreamMode.END_BOUNDED
        req_none = VStreamMode.START_CAN_INC | VStreamMode.START_CAN_DEC
        opt_mode = (VStreamMode.DATA_LOCK | VStreamMode.START_LOCK |
                    VStreamMode.END_LOCK)

        # Ensure file has binary mode
        if 't' in fmode:
            raise ValueError('File text mode not supported')
        if 'b' not in fmode:
            if _pyver == 2:
                if isinstance(fmode, str):
                    fmode += b'b'
                else:
                    fmode += u'b'
            else:
                fmode += 'b'

        if 'r' in fmode or '+' in fmode:
            opt_mode |= VStreamMode.READABLE
        else:
            req_none |= VStreamMode.READABLE

        if 'w' in fmode or '+' in fmode:
            opt_mode |= VStreamMode.WRITABLE
            opt_mode |= VStreamMode.END_CAN_DEC
            opt_mode |= VStreamMode.END_CAN_INC
            opt_mode |= VStreamMode.CAN_MOVE_END
        else:
            req_none |= VStreamMode.WRITABLE
            req_none |= VStreamMode.END_CAN_DEC
            req_none |= VStreamMode.END_CAN_INC
            req_none |= VStreamMode.CAN_MOVE_END

        if seek_rew:
            opt_mode |= VStreamMode.SEEK_REW
        else:
            req_none |= VStreamMode.SEEK_REW

        if seek_fwd:
            opt_mode |= VStreamMode.SEEK_FWD
        else:
            req_none |= VStreamMode.SEEK_FWD

        self._req_mode = req_mode
        self._req_mask = req_mode | req_none
        self._opt_mode = opt_mode

        try:
            self._f = open(filename, fmode)
            self._pos = self._f.tell()
            self._f.seek(0, 2)
            self._len = self._f.tell()
            self._f.seek(self._pos)
        except:
            raise VStreamError('File I/O error during construction')

    def read(self, max_num):
        with self:
            try:
                data = self._f.read(max_num)
            except:
                raise VStreamError('File read() error')
            self._pos += len(data)
            return data

    def write(self, data):
        with self:
            try:
                self._f.write(data)
            except:
                raise VStreamError('File write() error')
            self._pos += len(data)
            if self._pos > self._len:
                self._len = self._pos
            return len(data)

    def seek(self, pos, pos_ref):
        with self:
            if (pos_ref == VStreamPos.ABS
                or pos_ref == VStreamPos.START):
                if pos < 0:
                    raise VStreamError('Cannot seek to negative position')
                elif pos > self._len:
                    raise VStreamError('Cannot seek past end of file')
                try:
                    self._f.seek(pos)
                except:
                    raise VStreamError('Seek operation error')
            elif pos_ref == VStreamPos.END:
                if pos > 0:
                    raise VStreamError('Cannot seek past end of file')
                elif pos > self._len:
                    raise VStreamError('Cannot seek to negative position')
                try:
                    self._f.seek(pos, 2)
                except:
                    raise VStreamError('Seek operation error')
            else:
                raise VStreamError('Invalid position reference')
            try:
                self._pos = self._f.tell()
            except:
                raise VStreamError('File tell() error')
            return self._pos

    def trunc_after(self):
        with self:
            if self._len > self._pos:
                try:
                    self._f.truncate()
                except IOError:
                    raise VStreamError('File truncation operation error')
                else:
                    self._len = self._pos

    def close(self):
        with self:
            self._f.close()

    @property
    def pos(self):
        with self:
            return self._pos

    @property
    def endpoints(self):
        with self:
            return (0, self._len)

    @property
    def req_mode(self):
        return (self._req_mode, self._req_mask)

    @property
    def opt_mode(self):
        return self._opt_mode


class VEntityFixedStreamerData(VStreamerData):
    """Memory-cached read-only entity data for streaming.

    :param data: streamer data
    :type  data: :class:`versile.orb.entity.VTuple`\, tuple or list
    :param allow_native: if True allow native entity representation
    :type  allow_native: bool

    If *allow_native* is False then *data* must be a
    :class:`versile.orb.entity.VTuple` (which holds
    :class:`versile.orb.entity.VEntity`\ data elements).

    If *allow_native* is True then *data* may be a regular tuple which
    holds either entity elements or native-type representations of
    entity data elements. If *data* is a :class:`list` then it is
    converted to a tuple.

    """

    def __init__(self, data, allow_native=True):
        super(VEntityFixedStreamerData, self).__init__()
        if isinstance(data, list):
            data = tuple(data)
        self._data = data
        self._allow_native = allow_native
        self._len = len(data)
        self._pos = 0

        if not allow_native:
            if not isinstance(data, VTuple):
                raise VStreamError('Data must be a VTuple')

    def read(self, max_num):
        if self._data is None:
            raise VStreamError('Streamer data was closed')
        start_pos = self._pos
        end_pos = start_pos + max_num
        end_pos = min(end_pos, self._len)
        result = self._data[start_pos:end_pos]
        if not self._allow_native:
            result = VTuple(result)
        self._pos += len(result)
        return result

    def seek(self, pos, pos_ref):
        if self._data is None:
            raise VStreamError('Streamer data was closed')
        if pos_ref == VStreamPos.END:
            pos += self._len
        elif pos_ref == VStreamPos.CURRENT:
            pos += self._pos
        elif pos_ref not in (VStreamPos.ABS, VStreamPos.START):
            raise VStreamError('Invalid seek pos reference')
        if pos < 0 or pos > self._len:
            raise VStreamError('Out-of-range seek position')
        self._pos = pos
        return self._pos

    def close(self):
        self._data = None

    @property
    def pos(self):
        return self._pos

    @property
    def endpoints(self):
        return (0, self._len)

    @property
    def req_mode(self):
        mode = (VStreamMode.READABLE | VStreamMode.START_BOUNDED |
                VStreamMode.END_BOUNDED | VStreamMode.FIXED_DATA)
        mask = (mode | VStreamMode.WRITABLE | VStreamMode.START_CAN_DEC |
                VStreamMode.START_CAN_INC | VStreamMode.CAN_MOVE_START |
                VStreamMode.END_CAN_DEC | VStreamMode.END_CAN_INC |
                VStreamMode.CAN_MOVE_END | VStreamMode.DATA_LOCK |
                VStreamMode.START_LOCK | VStreamMode.END_LOCK)
        return (mode, mask)

    @property
    def opt_mode(self):
        return VStreamMode.SEEK_REW | VStreamMode.SEEK_FWD


class VEntityIteratorStreamerData(VStreamerData):
    """Streamer data interface to an entity iterator.

    :param iterator:     iterable yielding entity objects
    :type  iterator:     iterable
    :param buf_len:      buffer length
    :type  buf_len:      int
    :param allow_native: if True allow native entity representation
    :type  allow_native: bool

    If *allow_native* is True then *iterable* must yield
    :class:`versile.orb.entity.VEntity`\ , otherwise it may also yield
    native-type representations of entity elements.

    """

    def __init__(self, iterable, buf_len=_ESIZE, allow_native=True):
        super(VEntityIteratorStreamerData, self).__init__()
        try:
            self._iterator = iter(iterable)
        except:
            raise TypeError('Could not create iterator from iterable')
        self._buf_len = buf_len
        self._allow_native = allow_native
        self._buf = collections.deque()
        self._finished = False
        self._pos = 0
        self.__update_buffer()

    def read(self, max_num):
        if self._buf is None:
            raise VStreamError('Streamer data was closed')

        result = collections.deque()
        if self._buf or not self._finished:
            num_left = max_num
            while self._buf and num_left > 0:
                result.append(self._buf.popleft())
                num_left -= 1
                if not self._buf:
                    self.__update_buffer()
            self.__update_buffer()
            if not self._buf:
                self._finished = True

        if self._allow_native:
            result = tuple(result)
        else:
            result = VTuple(result)
        self._pos += len(result)
        return result

    def close(self):
        self._buf = None

    @property
    def pos(self):
        return self._pos

    @property
    def endpoints(self):
        if self._buf is None:
            raise VStreamError('Streamer data was closed')
        return (self._pos, self._pos + len(self._buf))

    @property
    def req_mode(self):
        mode = (VStreamMode.READABLE | VStreamMode.START_BOUNDED |
                VStreamMode.END_BOUNDED | VStreamMode.FIXED_DATA)
        mask = (mode | VStreamMode.WRITABLE | VStreamMode.START_CAN_DEC |
                VStreamMode.START_CAN_INC | VStreamMode.CAN_MOVE_START |
                VStreamMode.END_CAN_DEC | VStreamMode.END_CAN_INC |
                VStreamMode.CAN_MOVE_END | VStreamMode.SEEK_REW |
                VStreamMode.SEEK_FWD | VStreamMode.DATA_LOCK |
                VStreamMode.START_LOCK | VStreamMode.END_LOCK)
        return (mode, mask)

    @property
    def opt_mode(self):
        return 0x0

    def __update_buffer(self):
        if not self._finished:
            max_add = self._buf_len - len(self._buf)
            for i in xrange(max_add):
                try:
                    item = next(self._iterator)
                except StopIteration:
                    self._finished = True
                    break
                else:
                    self._buf.append(item)


class VStreamer(VExternal):
    """Streaming interface to a stream data source.

    :param streamdata: connected stream data source
    :type  streamdata: :class:`VStreamerData`
    :param mode:       mode flags
    :type  mode:       int
    :param wbuf:       write data buffer (or None)
    :type  wbuf:       :class:`VStreamBuffer`
    :param w_lim:      max pending data elements for peer write operations
    :type  w_lim:      int
    :param w_step:     peer write limit increment (or None)
    :type  w_step:     int
    :param w_pkg:      max pending write data push packages
    :type  w_pkg:      int
    :param w_size:     max elements per write push package
    :type  w_size:     int
    :param max_calls:  max parallell calls in addition to write push calls
    :type  max_calls:  int
    :param r_pkg:      max pending read push packages (or None)
    :type  r_pkg:      int
    :param r_size:     max elements per read push package (or None)
    :type  r_size:     int

    *mode* is a bitwise or of a set of the following flags:
    :attr:`VStreamMode.READABLE`\ , :attr:`VStreamMode.WRITABLE`\ ,
    :attr:`VStreamMode.START_BOUNDED`\ ,
    :attr:`VStreamMode.START_CAN_INC`\ ,
    :attr:`VStreamMode.START_CAN_DEC`\ ,
    :attr:`VStreamMode.END_BOUNDED`\ ,
    :attr:`VStreamMode.END_CAN_INC`\ ,
    :attr:`VStreamMode.END_CAN_DEC`\ , :attr:`VStreamMode.SEEK_FWD`\ ,
    :attr:`VStreamMode.SEEK_REW`\ , :attr:`VStreamMode.FIXED_DATA`\ ,
    :attr:`VStreamMode.DATA_LOCK`\ , :attr:`VStreamMode.START_LOCK`
    and :attr:`VStreamMode.END_LOCK`\ .  Either readable or writable
    must be set (or both). The streamer mode is fixed after it has
    been set (changing mode requires setting up another stream with another
    streamer).

    If :attr:`VStreamMode.WRITABLE` is set then *wbuf* must be
    set. The data type of the elements held by the write buffer must
    be the same as the streamer and the stream data operates on.

    If *w_step* is None then it is set to half of *w_size* (rounded
    up). *w_lim* and *w_step* can be modified by calling calling
    :meth:`set_write_buffering`\ .

    *r_pkg* and *r_size* are locally set limits. If not None, read
    limits received from a connected stream peer during connect
    handshake will be truncated so they do not exceed local limits.

    A :class:`VStreamer` publishes remotely accessible methods for
    interacting with stream data. A remote :class:`VStreamPeer` object
    can connect to the streamer by calling :meth:`peer_connect` to
    perform a streamer-connection handshake.

    """

    # ctx mode values
    _READING = 1
    _WRITING = 2

    def __init__(self, streamdata, mode, wbuf, w_lim,  w_step, w_pkg, w_size,
                 max_calls, r_pkg, r_size):
        super(VStreamer, self).__init__()

        # Validate streamdata allows the set mode
        req_mode, req_mask = streamdata.req_mode
        if mode & req_mask != req_mode:
            raise VStreamError('Mismatch with required streamer data mode.')
        max_bits = req_mask | streamdata.opt_mode
        if (mode | max_bits) ^ max_bits:
            raise VStreamError('All mode bits not supported by streamer data.')

        # Other validation
        VStreamMode.validate(mode)
        if mode & VStreamMode.WRITABLE and not wbuf:
            raise VStreamError('Writable stream must have a write buffer')

        self._streamdata = streamdata
        self._mode = mode
        self._w_buf = wbuf

        self._failed = False             # If True the streamer has failed
        self._done = False               # True when cleanly closed

        self._call_lim = w_pkg + max_calls
        self._calls = VSequenceCallQueue(self._call_lim)
        self._w_num = w_pkg
        self._w_size = w_size

        self._peer = None
        self._caller = VSequenceCaller()

        self._ctx_mode = 0               # Current streamer mode
        self._ctx = None                 # Msg ID which initiated current ctx
        self._ctx_spos = streamdata.pos  # Current context start position
        self._ctx_rpos = 0               # Current context relative position
        self._ctx_err = False            # Error condition on current context
        self._ctx_err_code = None        # Error code for error condition

        self._r_num = None               # Max number of pending peer read push
        self._r_size = None              # Max size of a peer read push

        self._r_rel_pos_lim = 0          # Relative read position limit
        self._r_eos = None               # Read end-of-stream mode
        self._r_sent_eos = False         # True if end-of-stream was sent
        self._r_pending = 0              # Number of pending read push calls

        self._w_rel_lim = 0
        self._w_recv = 0
        self._w_pending = 0

        self._peer_r_num = None
        self._peer_r_size = None
        self._local_r_num = r_pkg
        self._local_r_size = r_size

        # Initializes self._w_buf_lim and self._w_buf_step
        self.set_write_buffering(w_lim, w_step)

        # Start tracking streamdata endpoints
        self._start, self._end = streamdata.endpoints
        streamdata.set_streamer(self)
        streamdata.enable_notifications(VStreamerData.NOTIFY_ENDPOINTS)

    @publish(show=True, ctx=False)
    def peer_connect(self, peer, call_lim, r_num, r_size):
        """Connect a peer stream object with the streamer.

        :param peer:     connecting peer
        :type  peer:     :class:`versile.orb.entity.VProxy`
        :param call_lim: max pending calls (in addition to *r_num*)
        :type  call_lim: int
        :param r_num:    max allowed pending read push calls
        :type  r_num:    int
        :param r_size:   max elements per read push call
        :type  r_size:   int
        :returns:        (mode, pos, call_lim, w_num, w_size)
        :rtype:          tuple(int)

        *peer* must implement the :class:`VStreamPeer` published
        methods.

        Returned *mode* is a bitwise or of the :class:`VStreamer` mode
        bits for the stream. *pos* is the current absolute stream
        position. *call_lim* is the max pending calls accepted by
        streamer in addition to write push calls. *w_num* is the max
        pending write push calls accepted by streamer. *w_size* is the
        max number of elements per write push call.

        Should only be called by a connecting peer, and should only be
        called once.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        peer, call_lim, r_num = conv(peer), conv(call_lim), conv(r_num)
        r_size = conv(r_size)

        # Validate argument type/range
        try:
            vchk(peer, vtyp(VProxy))
            for arg in call_lim, r_num, r_size:
                vchk(arg, vtyp('int'), vmin(1))
        except Exception as e:
            self._fail(msg='Invalid peer_connect arguments')
            raise e

        with self:
            if self._peer or self._done:
                raise VException('Can only connect once')
            self._peer = peer
            self._caller.set_limit(call_lim)

            self._peer_r_num = self._r_num = r_num
            if self._local_r_num is not None:
                self._r_num = min(self._r_num, self._local_r_num)
            self._peer_r_size = self._r_size = r_size
            if self._local_r_size is not None:
                self._r_size = min(self._r_size, self._local_r_size)

            pos = self._ctx_spos + self._ctx_rpos

            res = (self._mode, pos, self._call_lim, self._w_num, self._w_size)
            res = VEntity._v_lazy(res)
            return res

    @publish(show=True, ctx=False)
    def peer_read_start(self, msg_id, pos, pos_ref, eos):
        """Initiate a read context.

        :param msg_id:   :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:   int
        :param pos:      target read position vs. pos_ref (or None)
        :type  pos:      int
        :param pos_ref:  reference for *pos*
        :param pos_ref:  int
        :param end_eos:  if True endpoint triggers end-of-stream
        :type  end_eos:  bool

        If *pos* is None then the current position is used if the
        previous context was a write context. Initiating a new read
        context with *pos* set to None is not allowed.

        *pos_ref* should be either :attr:`VStreamPos.ABS`\ ,
        :attr:`VStreamPos.START` or :attr:`VStreamPos.END`\ .

        If *end_eos* is True then reaching the current end delimiter
        of stream data causes an end-of-stream to be sent to the
        streamer's peer.

        The streamer acknowledges the new read context by calling
        :meth:`VStreamPeer.peer_notify_push` on the connected peer.

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id, pos, pos_ref = conv(msg_id), conv(pos), conv(pos_ref)
        eos = conv(eos)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            if pos is not None:
                vchk(pos, vtyp('int'))
                vchk(pos_ref, vtyp('int'))
            elif pos_ref is not None:
                raise VException('If pos is None, pos_ref must be None')
            vchk(eos, vtyp(bool))
        except Exception as e:
            self._fail(msg='Invalid peer_read_start arguments')
            raise e

        with self:
            if self._failed or self._done: return
            if not self._mode & VStreamMode.READABLE:
                self._fail(msg='Stream not readable') ; return
            if pos is not None:
                if pos_ref not in (VStreamPos.ABS, VStreamPos.START,
                                   VStreamPos.END):
                    self._fail(msg='Invalid position reference') ; return
            handler, calldata = self._peer_rstart, (msg_id, pos, pos_ref, eos)
            return self._calls.queue(msg_id, handler, calldata)

    @publish(show=True, ctx=False)
    def peer_write_start(self, msg_id, pos, pos_ref):
        """Initiate a write context.

        Parameters are similar to :meth:`peer_read_start` except it does
        not take an *eos* parameter, as write-mode does not generate
        end-of-stream information.

        If *pos* is None then the current position is used if the
        previous context was a read context. Initiating a new write
        context with *pos* set to None is not allowed.

        .. note::

            Initiating a write context with *pos* set to None or
            relative to the current position could cause unwanted side
            effects as read-ahead will normally cause streamer
            position to be different from the current position tracked
            on a connected peer stream object.

        The streamer acknowledges the new read context by calling
        :meth:`VStreamPeer.peer_notify_push` on the connected peer.

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id, pos, pos_ref = conv(msg_id), conv(pos), conv(pos_ref)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            if pos is not None:
                vchk(pos, vtyp('int'))
                vchk(pos_ref, vtyp('int'))
            elif pos_ref is not None:
                raise VException('If pos is None, pos_ref must be None')
        except Exception as e:
            self._fail(msg='Invalid peer_write_start arguments')
            raise e

        with self:
            if self._failed or self._done: return
            if not self._mode & VStreamMode.WRITABLE:
                self._fail(msg='Stream not writable') ; return
            if pos is not None:
                if pos_ref not in (VStreamPos.ABS, VStreamPos.START,
                                   VStreamPos.END):
                    self._fail(msg='Invalid position reference') ; return
            handler, calldata = self._peer_wstart, (msg_id, pos, pos_ref)
            return self._calls.queue(msg_id, handler, calldata)

    @publish(show=True, ctx=False)
    def peer_read_lim(self, msg_id, rel_pos):
        """Sets a new read push limit for the current read context.

        :param msg_id:   :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:   int
        :param rel_pos:  read push delimiter after read context start position
        :type  rel_pos:  int

        *rel_pos* must be larger than any previously sent read push
        delimiter. Calling this method is only allowed when in a read
        context that was initiated with :meth:`peer_read_start`\ .

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id, rel_pos = conv(msg_id), conv(rel_pos)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            vchk(rel_pos, vtyp('int'), vmin(1))
        except Exception as e:
            self._fail(msg='Invalid peer_read_lim arguments')
            raise e

        with self:
            if self._failed or self._done: return
            return self._calls.queue(msg_id, self._peer_rlim, (rel_pos,))

    @publish(show=True, ctx=False)
    def peer_write_push(self, msg_id, write_ctx, data):
        """Pushes write data to an active write context.

        :param msg_id:    :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:    int
        :param write_ctx: call ID of the first call of current context
        :type  write_ctx: int
        :param data:      data to push (cannot be empty)

        Pushing write data is only allowed when in a write context
        which was initiated with :meth:`peer_write_start`\ . It is subject
        to write push limits that were negotiated when calling
        :meth:`peer_connect`\ .

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id, write_ctx = conv(msg_id), conv(write_ctx)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            vchk(write_ctx, vtyp('int'), vmin(0))
            if not self._w_buf.valid_data(data):
                raise VException('Invalid wpush data')
        except Exception as e:
            self._fail(msg='Invalid peer_write_push arguments')
            raise e

        with self:
            if self._failed or self._done: return

            self._w_pending += 1
            if self._w_pending > self._w_num:
                self._fail(msg='Too many pending write push') ; return
            if not self._w_buf.valid_data(data):
                self._fail(msg='Invalid write push data') ; return
            len_data = self._w_buf.len_data(data)
            if len_data == 0:
                self._fail(msg='Write push without data') ; return
            if len_data > self._w_size:
                self._fail(msg='Write package too big') ; return

            handler, calldata = self._peer_wpush, (write_ctx, data)
            return self._calls.queue(msg_id, handler, calldata)

    @publish(show=True, ctx=False)
    def peer_trunc_before(self, msg_id):
        """Truncates all stream data before current position.

        The stream must be in write mode and the streamer mode must
        allow start position increases and moving the start position.

        Calling this method resets the context ID to *msg_id*. The
        stream peer mey only call this method after it has received
        :meth:`VStreamPeer.peer_set_start_pos` notification for the
        previous write context.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id = conv(msg_id)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
        except Exception as e:
            self._fail(msg='Invalid peer_trunc_before arguments')
            raise e

        with self:
            if self._failed or self._done: return
            if not (self._mode & VStreamMode.CAN_MOVE_START
                    and self._mode & VStreamMode.START_CAN_INC):
                self._fail(msg='Illecal truncate operation') ; return
            return self._calls.queue(msg_id, self._peer_trunc_before,
                                     (msg_id,))

    @publish(show=True, ctx=False)
    def peer_trunc_after(self, msg_id):
        """Truncates all stream data after current position.

        The stream must be in write mode and the streamer mode must
        allow end position decreases and moving the end position.

        When a stream peer calls this method, any previously received write
        limit on the stream peer is invalidated. If writing is allowed after
        truncation, the streamer needs to send a new limit.

        Calling this method resets the context ID to *msg_id*. The
        stream peer mey only call this method after it has received
        :meth:`VStreamPeer.peer_set_start_pos` notification for the
        previous write context.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id = conv(msg_id)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
        except Exception as e:
            self._fail(msg='Invalid peer_trunc_after arguments')
            raise e

        with self:
            if self._failed or self._done: return
            if not (self._mode & VStreamMode.CAN_MOVE_END
                    and self._mode & VStreamMode.END_CAN_DEC):
                self._fail(msg='Illecal truncate operation') ; return
            return self._calls.queue(msg_id, self._peer_trunc_after, (msg_id,))

    @publish(show=True, ctx=False)
    def peer_close(self, msg_id):
        """Closes the stream connection.

        :param msg_id:   :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:   int

        Causes the streamer to close its side of the stream and
        acknowledge closing by calling :meth:`VStreamPeer.peer_closed`
        to the connected peer before freeing up stream resources.

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id = conv(msg_id)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
        except Exception as e:
            self._fail(msg='Invalid peer_close arguments')
            raise e

        with self:
            if self._failed or self._done: return
            return self._calls.queue(msg_id, self._peer_close, tuple())

    @publish(show=True, ctx=False)
    def peer_fail(self, msg_id, msg=None):
        """Informs the streamer the stream connection has failed.

        :param msg_id:    :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:    int
        :param msg:       error message (or None)
        :type  msg:       unicode

        Signal from the connected stream peer that a critical failure
        occured on the peer end of the stream. The streamer should abort
        all current streamer operation and free related resources.

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id, msg = conv(msg_id), conv(msg)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            if msg is not None:
                vchk(msg, vtyp(unicode))
        except Exception as e:
            self._fail(msg='Invalid peer_fail arguments')
            raise e

        with self:
            if self._failed or self._done: return
            return self._calls.queue(msg_id, self._peer_fail, (msg,))

    def set_write_buffering(self, num, step=None):
        """Set write buffering limits for received write push data.

        :param num:  max write push data that can be received
        :type  num:  int
        :param step: increment step for updating write push limits (or None)
        :type  step: int

        The *num* limit is the maximum write push limit (relative to
        peer position) that can be sent to peer. If *step* is None
        then it is set equal to half of *num* (rounded up).

        """
        if step is None:
            step = num//2 + num%2
        with self:
            self._w_buf_lim = num
            self._w_buf_step = step
            if self._ctx_mode == self._WRITING:
                self.__update_wlim()

    def _notify_endpoints(self):
        """Notification from streamer data that its data range changed.

        This method should only be called by a streamer data object
        which has had this streamer registered with its
        :meth:`VStreamerData.set_streamer`\ .

        .. warning::

            This method should not be called from inside any streamer
            data methods which are being called by its associated
            streamer, as executing this method interferes with the
            streamer's internal state.

        """
        with self:
            if self._streamdata and (self._failed or self._done
                                     or self._ctx_err):
                d_func = self._streamdata.disable_notifications
                d_func(VStreamerData.NOTIFY_ENDPOINTS)
            else:
                self.__poll_endpoints()
                if not self._ctx_err and self._ctx_mode == self._READING:
                    # Range may have expanded to allow reading more data
                    self._perform_read()

    def _peer_rstart(self, msg_id, pos, pos_ref, eos):
        if self._failed or self._done: return
        if self._ctx_mode == self._READING and pos is None:
            self._fail(msg='Invalid read context position') ; return
        if self._ctx_mode == self._WRITING:
            self._w_buf.end_context()

        self.__clear_ctx_data()

        old_pos = self._ctx_spos + self._ctx_rpos
        new_pos = None

        # Pre-validation of seek operation
        if pos is not None:
            if not self._mode & (VStreamMode.SEEK_REW | VStreamMode.SEEK_FWD):
                self._fail(msg='Stream does not support seek') ; return
            if pos_ref == VStreamPos.ABS:
                new_pos = pos
                if new_pos > old_pos and not self._mode & VStreamMode.SEEK_FWD:
                    self._fail(msg='Forward seek not allowed') ; return
                elif (new_pos < old_pos
                      and not self._mode & VStreamMode.SEEK_REW):
                    self._fail(msg='Reverse seek not allowed') ; return

        if pos is None:
            new_pos = self._ctx_spos + self._ctx_rpos
        elif new_pos is None or new_pos != old_pos:
            # Seek to new position and post-validate result
            try:
                new_pos = self._streamdata.seek(pos, pos_ref)
            except VStreamFailure:
                self._fail(msg='Seek related failure') ; return
            except VStreamException:
                raise VException('Could not initiate reading')
            else:
                if new_pos > old_pos and not self._mode & VStreamMode.SEEK_FWD:
                    self._fail(msg='Forward seek not allowed') ; return
                elif (new_pos < old_pos
                      and not self._mode & VStreamMode.SEEK_REW):
                    self._fail(msg='Reverse seek not allowed') ; return

        # Initialize resulting read mode parameters
        self._ctx_mode = self._READING
        self._ctx = msg_id
        self._ctx_err = False
        self._ctx_err_code = None
        self._r_eos = eos
        self._ctx_spos, self._ctx_rpos = new_pos, 0

        # Notify peer of the resulting position
        cdata = (self._ctx, self._ctx_spos)
        try:
            self._caller.call(self._peer.peer_set_start_pos, cdata)
        except VCallError:
            self._fail(msg='Could not perform remote call')

        # Update end-point information
        self.__poll_endpoints()

    def _peer_wstart(self, msg_id, pos, pos_ref):
        if self._failed or self._done: return
        if self._ctx_mode == self._WRITING and pos is None:
            self._fail(msg='Invalid write start position') ; return

        self.__clear_ctx_data()

        old_pos = self._ctx_spos + self._ctx_rpos
        new_pos = None

        # Pre-validation of seek operation
        if pos is not None:
            if not self._mode & (VStreamMode.SEEK_REW | VStreamMode.SEEK_FWD):
                self._fail(msg='Seek not allowed') ; return
            if pos_ref == VStreamPos.ABS:
                new_pos = pos
                if new_pos > old_pos and not self._mode & VStreamMode.SEEK_FWD:
                    self._fail(msg='Forward seek not allowed') ; return
                elif (new_pos < old_pos
                      and not self._mode & VStreamMode.SEEK_REW):
                    self._fail(msg='Reverse seek not allowed') ; return

        if pos is None:
            new_pos = self._ctx_spos + self._ctx_rpos
        elif new_pos is None or new_pos != old_pos:
            # Seek to new position and post-validate result
            try:
                new_pos = self._streamdata.seek(pos, pos_ref)
            except VStreamFailure:
                self._fail(msg='Seek operation failure') ; return
            except VStreamException:
                raise VException('Could not initiate reading')
            else:
                if (new_pos > old_pos
                    and not self._mode & VStreamMode.SEEK_FWD):
                    self._fail(msg='Forward seek not allowed') ; return
                elif (new_pos < old_pos
                      and not self._mode & VStreamMode.SEEK_REW):
                    self._fail(msg='Reverse seek not allowed') ; return

        # Initialize write mode parameters
        self._ctx_mode = self._WRITING
        self._ctx = msg_id
        self._ctx_err = False
        self._ctx_err_code = None
        self._ctx_spos, self._ctx_rpos = new_pos, 0
        self._w_rel_lim = 0
        self._w_recv = 0
        self._w_buf.new_context(self._ctx_spos)

        # Notify peer of the resulting position
        cdata = (self._ctx, self._ctx_spos)
        try:
            self._caller.call(self._peer.peer_set_start_pos, cdata)
        except VCallError:
            self._fail(msg='Could not perform remote call')

        self.__update_wlim()

        # Update end-point information
        self.__poll_endpoints()

    def _peer_rlim(self, rel_pos):
        with self:
            if self._failed or self._done or self._ctx_err: return
            if not self._mode & VStreamMode.READABLE:
                self._fail(msg='Stream not readable') ; return
            if self._ctx_err:
                raise VException('Error condition on read context')

            if rel_pos <= self._r_rel_pos_lim:
                self._fail(msg='Illegal read limit') ; return
            self._r_rel_pos_lim = rel_pos
            self._perform_read()

    def _peer_wpush(self, write_ctx, data):
        with self:
            if self._failed or self._done or self._ctx_err: return

            self._w_pending -= 1

            # Validate context
            if write_ctx != self._ctx:
                return
            if self._ctx_mode != self._WRITING:
                self._fail(msg='Write push without write mode') ; return

            # Push data onto write buffer unless data overflow
            len_data = self._w_buf.len_data(data)
            if self._w_recv + len_data > self._w_rel_lim:
                self._fail(msg='Write limit exceeded') ; return

            try:
                self._streamdata.write(data)
            except StreamError:
                self._fail(msg='Streamer data write error') ; return
            else:
                self._w_buf.write(data)
                self._w_recv += len_data
                self._ctx_rpos += len_data
                # Update endpoint information
                self.__poll_endpoints()
                # Update write limit
                self.__update_wlim()

    def _peer_trunc_before(self, msg_id):
        with self:
            if self._failed or self._done or self._ctx_err:
                return
            if self._ctx_mode != self._WRITING:
                self._fail(msg='Truncate requires write context') ; return
            try:
                self._streamdata.trunc_before()
            except StreamError:
                # Set context error condition
                self._set_error() ; return
            else:
                # Truncation updates the context ID
                self._ctx = msg_id
                # Update endpoint information
                self.__poll_endpoints()

    def _peer_trunc_after(self, msg_id):
        with self:
            if self._failed or self._done or self._ctx_err:
                return
            if self._ctx_mode != self._WRITING:
                self._fail(msg='Truncate requires write context') ; return
            try:
                self._streamdata.trunc_after()
            except StreamError:
                # Set context error condition
                self._set_error() ; return
            else:
                # Truncation updates the context ID
                self._ctx = msg_id
                # Update endpoint information
                self.__poll_endpoints()
                # Truncation resets write limit, reset and send new limit
                self._w_rel_lim = self._w_recv
                self.__update_wlim()

    def _peer_close(self):
        with self:
            if self._failed or self._done or self._ctx_err: return
            self._done = True
            if self._streamdata:
                self._streamdata.close()
            try:
                self._caller.call(self._peer.peer_closed, tuple())
            except VCallError:
                self._fail(msg='Could not perform remote call')
            self.__cleanup()

    def _peer_fail(self, msg):
        with self:
            if not self._failed:
                self._failed = True
                self.__cleanup()

    def _perform_read(self):
        """Internal call to perform a read operation.

        Raises exceptions, these need to be handled by caller; e.g. if
        call result is not passed back to peer, then caller must
        employ another mechanism to notify of the error condition.

        """
        with self:
            if self._failed or self._done:
                return
            elif not self._mode & VStreamMode.READABLE:
                return
            elif self._r_sent_eos:
                return
            elif self._ctx_err:
                raise VException('Error condition on read context')

            end_of_data = False
            while (self._r_pending < self._r_num and not self._ctx_err
                   and not end_of_data):
                max_push = max(self._r_rel_pos_lim - self._ctx_rpos, 0)
                max_push = min(max_push, self._r_size)
                if max_push <= 0:
                    break

                # Read data for sending to peer
                try:
                    data = self._streamdata.read(max_push)
                except VStreamFailure:
                    self._fail(msg='Seek operation failure')
                except VStreamException:
                    self._set_error() ; break
                else:
                    if len(data) < max_push:
                        end_of_data = True

                # Send data to peer
                eos = bool(end_of_data and self._r_eos)
                if data or eos:
                    calldata = (self._ctx, data, eos)
                    callback = self._rpush_callback
                    try:
                        self._caller.call(self._peer.peer_read_push, calldata,
                                          callback=callback,
                                          failback=self._fail)
                    except VCallError:
                        self._fail(msg='Could not perform remote call')
                    self._ctx_rpos += len(data)
                    self._r_pending += 1
                    if eos:
                        self._r_sent_eos = True

                # Update endpoint information
                self.__poll_endpoints()

    def _rpush_callback(self, result):
        with self:
            if self._failed or self._done: return
            self._r_pending -= 1
            if self._ctx_mode == self._READING:
                self._perform_read()

    def _fail(self, exc=None, msg=None):
        """Sets a general failure condition and schedules peer notification.

        Takes an unused *exc* parameter so it can serve as a failback.

        """
        if not self._failed or self._done:
            self._failed = True
            if exc and msg is None and e.message:
                msg = e.message
            if self._peer:
                try:
                    self._caller.call(self._peer.peer_fail, (msg,))
                except VCallError as e:
                    # Ignoring as stream was already failed
                    _v_silent(e)
            self.__cleanup()

    def _set_error(self, code=VStreamErrorCode.GENERAL):
        """Sets error condition and reports to peer (max once per rcontext)."""
        if not self._ctx_err:
            self._ctx_err = True
            self._ctx_err_code = code
            try:
                self._caller.call(self._peer.peer_error, (self._ctx, code),
                                  failback=self._fail)
            except VCallError:
                self._fail(msg='Could not perform remote call')

    def __update_wlim(self):
        """Tests whether to update write limit based on write-ahead."""
        with self:
            if self._failed or self._done: return
            if not self._ctx_mode & self._WRITING: return
            lim = self._ctx_rpos + self._w_buf_lim
            lim -= lim % self._w_buf_step
            if not ((self._mode & VStreamMode.END_CAN_INC
                     and self._mode & VStreamMode.CAN_MOVE_END)
                    or self._end is None):
                # If not END_CAN_INC, ensure no writing past endpoint
                _max_to_end = max(0, self._end-self._ctx_spos)
                lim = min(lim, _max_to_end)
            if lim > self._w_rel_lim:
                self._w_rel_lim = lim
                calldata = (self._ctx, self._w_rel_lim)
                try:
                    self._caller.call(self._peer.peer_write_lim, calldata)
                except VCallError:
                    self._fail(msg='Could not perform remote call')

    def __poll_endpoints(self):
        """Updates streamer end-points by polling streamer data.

        :returns: True if endpoints were changed
        :rtype:   bool

        If the current position is no longer inside range of endpoints,
        an invalid position error condition is set on this context.

        """
        old_range = self._start, self._end
        new_range = self._streamdata.endpoints
        self._start, self._end = new_range
        pos = self._ctx_spos + self._ctx_rpos
        if not ((self._start is None or self._start <= pos)
                and (self._end is None or pos <= self._end)):
            self._set_error(code=VStreamErrorCode.INVALID_POS)
        return (new_range != old_range)

    def __clear_ctx_data(self):
        """Clears (most) current context settings.

        Does not modify self._ctx_spos or self._ctx_rpos

        """
        self._ctx_mode = 0
        self._ctx = None
        self._ctx_err = False
        self._ctx_err_code = None
        self._r_rel_pos_lim = 0
        self._r_eos = None
        self._r_sent_eos = False
        self._w_rel_lim = 0
        self._w_recv = 0

    def __cleanup(self):
        self.__clear_ctx_data()
        if self._streamdata:
            self._streamdata.close()
        self._streamdata = None
        self._peer = None
        self._calls.clear()


class VByteStreamer(VERBase, VStreamer):
    """Streamer for byte data.

    Arguments are similar to :class:`VStreamer`\ .

    This streamer operates on :class:`bytes` data, and so
    *streamdata*, *wbuf* and a connected peer are also required to
    operate on bytes data. The byte streamer is a :term:`VSE` standard
    type and its tagged encoding is resolved as a
    :class:`VByteStreamerProxy`\ .

    """
    def __init__(self, streamdata, mode, wbuf=None, w_lim=_BLIM,
                 w_step=None, w_pkg=_BPKG, w_size=_BSIZE, max_calls=_CALLS,
                 r_pkg=_BPKG, r_size=_BSIZE):
        VStreamer.__init__(self, streamdata=streamdata, mode=mode, wbuf=wbuf,
                           w_lim=w_lim, w_step=w_step, w_pkg=w_pkg,
                           w_size=w_size, max_calls=max_calls,
                           r_pkg=r_pkg, r_size=r_size)

    def proxy(self):
        """Returns a proxy to the streamer.

        :returns: streamer proxy
        :rtype:   :class:`VByteStreamerProxy`

        """
        return VByteStreamerProxy(self, self._mode)

    @classmethod
    def fixed(cls, data, seek_rew=False, seek_fwd=False, wbuf=None,
              w_lim=_BLIM,w_step=None, w_pkg=_BPKG, w_size=_BSIZE,
              max_calls=_CALLS, r_pkg=_BPKG, r_size=_BSIZE):
        """Creates a byte streamer connected to fixed byte streamer data.

        :param data:     fixed data for the connected byte streamer
        :type  data:     bytes
        :param seek_rew: if True allow reverse-seek on streamer
        :type  seek_rew: bool
        :param seek_fwd: if True allow forward-seek on streamer
        :type  seek_fwd: bool
        :returns:        byte streamer for provided data
        :rtype:          :class:`VByteStreamer`

        Other arguments are similar to the :class:`VByteStreamer` constructor.

        This is a convenience method which creates a
        :class:`VByteFixedStreamerData` data source which takes
        its data from *data* and returns a connected streamer.

        """
        streamdata = VByteFixedStreamerData(data)
        mode = streamdata.req_mode[0]
        if seek_rew:
            mode |= VStreamMode.SEEK_REW
        if seek_fwd:
            mode |= VStreamMode.SEEK_FWD
        return cls(streamdata=streamdata, mode=mode, wbuf=wbuf, w_lim=w_lim,
                   w_step=w_step, w_pkg=w_pkg, w_size=w_size,
                   max_calls=max_calls, r_pkg=r_pkg, r_size=r_size)

    def _v_as_tagged(self, context):
        """Encode same format as :meth:`VByteStreamerProxy._v_as_tagged`\ ."""
        tags = VSECodes.BYTE_STREAMER.tags(context) + (self._mode,)
        return VTagged(self._v_raw_encoder(), *tags)


class VByteStreamerProxy(VERBase, VEntity):
    """Reference to a remote :class:`VByteStreamer`\ implementation.

    :param streamer: streamer reference
    :type  streamer: :class:`versile.orb.entity.VObject`
    :param mode:     mode bits for the streamer
    :type  mode:     int

    This class is the type decoded by the :term:`VSE` standard
    representation of a :class:`VByteStreamer`\ . It is normally not
    directly instantiated, but is instead instantiated as a result of
    decoding an encoded :term:`VSE` representation.

    """

    def __init__(self, streamer, mode):
        self._streamer = streamer
        self._mode = mode

    def connect(self, r_buf=None, eos_policy=True, readahead=False,
                r_pkg=_BPKG, r_size=_BSIZE, max_calls=_CALLS, w_pkg=_BPKG,
                w_size=_BSIZE):
        """Initiate a stream connection with the referenced streamer.

        :param r_buf:      read buffer for byte data (or None)
        :type  r_buf:      :class:`VStreamBuffer`
        :param eos_policy: use as default read eos mode for stream
        :type  eos_policy: bool
        :param readahead:  if True enable stream readahead
        :type  readahead:  bool
        :param r_pkg:      max pending read push calls
        :type  r_pkg:      int
        :param r_size:     max elements per read push call
        :type  r_size:     int
        :param max_calls:  max pending calls in addition to read push
        :type  max_calls:  int
        :param w_pkg:      max pending write push calls
        :type  w_pkg:      int
        :param w_size:     max elements per write push call
        :type  w_size:     int
        :returns:          stream peer connecting to referenced streamer
        :rtype:            :class:`VStream`

        If *r_buf* is None a default :class:`VByteStreamBuffer` is
        created and used as the stream's buffer for received data.

        This method generates a local-side stream object which
        connects with the referenced streamer. The method should only
        be called once.

        It is also possible to create a connection without calling
        this method, by retreiving a reference to the streamer as
        :attr:`streamer` and creating and connecting a local stream
        object.

        """
        if r_buf is None:
            r_buf = VByteStreamBuffer()
        stream = VStreamPeer(r_buf=r_buf, r_pkg=r_pkg, r_size=r_size,
                             max_calls=max_calls, mode=self._mode,
                             w_pkg=w_pkg, w_size=w_size)
        stream.set_eos_policy(eos_policy)
        if readahead:
            stream._enable_readahead()
        return stream.connect(self.streamer)

    @property
    def streamer(self):
        """Holds a :class:`versile.orb.entity.VProxy` streamer reference."""
        return self._streamer._v_proxy()

    @property
    def mode(self):
        """Holds the mode set on the stream."""
        return self._mode

    def _v_as_tagged(self, context):
        """Must encode same format as :meth:`VByteStreamer._v_as_tagged`\ ."""
        tags = VSECodes.BYTE_STREAMER.tags(context) + (self._mode,)
        return VTagged(self._streamer._v_raw_encoder(), *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        if len(tags) != 1:
            raise VTaggedParseError('Encoding requires one residual tag')
        mode = tags[0]
        if not isinstance(mode, (int, long, VInteger)):
            raise VTaggedParseError('Invalid residual tag')
        def _assemble(args):
            value = args[0]
            value = VModule.as_object(value)
            return cls(value, mode=mode)
        return(_assemble, [value])


class VEntityStreamer(VERBase, VStreamer):
    """Streamer for :class:`versile.orb.entity.VEntity` data.

    Arguments are similar to :class:`VStreamer`\ .

    The streamer operates on :class:`versile.orb.entity.VEntity` data
    or native representations of entity types. *streamdata*, *wbuf*
    and a connected peer are also required to operate on
    :class:`versile.orb.entity.VEntity` data (or native
    representations). The byte streamer is a :term:`VSE` standard type
    and its tagged encoding is resolved as a
    :class:`VEntityStreamerProxy`\ .

    """
    def __init__(self, streamdata, mode, wbuf=None, w_lim=_ELIM,
                 w_step=None, w_pkg=_EPKG, w_size=_ESIZE, max_calls=_CALLS,
                 r_pkg=_EPKG, r_size=_ESIZE):
        VStreamer.__init__(self, streamdata=streamdata, mode=mode, wbuf=wbuf,
                           w_lim=w_lim, w_step=w_step, w_pkg=w_pkg,
                           w_size=w_size, max_calls=max_calls,
                           r_pkg=r_pkg, r_size=r_size)

    def proxy(self):
        """Returns a proxy to the streamer.

        :returns: streamer proxy
        :rtype:   :class:`VEntityStreamerProxy`

        """
        return VEntityStreamerProxy(self, self._mode)

    @classmethod
    def fixed(cls, data, allow_native=True, seek_rew=False, seek_fwd=False,
              wbuf=None, w_lim=_ELIM, w_step=None, w_pkg=_EPKG, w_size=_ESIZE,
              max_calls=_CALLS, r_pkg=_EPKG, r_size=_ESIZE):
        """Creates an entity streamer connected to fixed entity streamer data.

        :param data:         streamer data
        :type  data:         :class:`versile.orb.entity.VTuple` or tuple
        :param allow_native: if True allow native entity representation
        :type  allow_native: bool
        :param seek_rew:     if True allow reverse-seek on streamer
        :type  seek_rew:     bool
        :param seek_fwd:     if True allow forward-seek on streamer
        :type  seek_fwd:     bool
        :returns:            byte streamer for provided data
        :rtype:              :class:`VEntityStreamer`

        Other arguments are similar to the :class:`VEntityStreamer`
        constructor.

        This is a convenience method which creates a
        :class:`VEntityFixedStreamerData` data source which
        takes its data from *data* and returns a connected streamer.

        """
        streamdata = VEntityFixedStreamerData(data, allow_native)
        mode = streamdata.req_mode[0]
        if seek_rew:
            mode |= VStreamMode.SEEK_REW
        if seek_fwd:
            mode |= VStreamMode.SEEK_FWD
        return cls(streamdata=streamdata, mode=mode, wbuf=wbuf, w_lim=w_lim,
                   w_step=w_step, w_pkg=w_pkg, w_size=w_size,
                   max_calls=max_calls, r_pkg=r_pkg, r_size=r_size)

    @classmethod
    def iterator(cls, iterable, buf_len=_ESIZE, allow_native=True, wbuf=None,
                 w_lim=_ELIM, w_step=None, w_pkg=_EPKG, w_size=_ESIZE,
                 max_calls=_CALLS, r_pkg=_EPKG, r_size=_ESIZE):
        """Creates an entity streamer which feeds from an  iterator.

        :param iterator:     iterable yielding entity objects
        :type  iterator:     iterable
        :param buf_len:      buffer length
        :type  buf_len:      int
        :param allow_native: if True allow native entity representation
        :type  allow_native: bool
        :returns:            byte streamer for provided data
        :rtype:              :class:`VEntityStreamer`

        Other arguments are similar to the :class:`VEntityStreamer`
        constructor.

        This is a convenience method which creates a
        :class:`VEntityIteratorStreamerData` data source which
        feeds from *iterable* and returns a connected streamer.

        """
        SDCls = VEntityIteratorStreamerData
        streamdata = SDCls(iterable, buf_len, allow_native)
        mode = streamdata.req_mode[0]
        return cls(streamdata=streamdata, mode=mode, wbuf=wbuf, w_lim=w_lim,
                   w_step=w_step, w_pkg=w_pkg, w_size=w_size,
                   max_calls=max_calls, r_pkg=r_pkg, r_size=r_size)

    def _v_as_tagged(self, context):
        """Encode same as :meth:`VEntityStreamerProxy._v_as_tagged`\ ."""
        tags = VSECodes.ENTITY_STREAMER.tags(context) + (self._mode,)
        return VTagged(self._v_raw_encoder(), *tags)


class VEntityStreamerProxy(VERBase, VEntity):
    """Reference to a remote :class:`VEntityStreamer`\ implementation.

    :param streamer: streamer reference
    :type  streamer: :class:`versile.orb.entity.VObject`
    :param mode:     mode bits for the streamer
    :type  mode:     int

    This class is the type decoded by the :term:`VSE` standard
    representation of a :class:`VEntityStreamer`\ . It is normally not
    directly instantiated, but is instead instantiated as a result of
    decoding an encoded :term:`VSE` representation.

    """

    def __init__(self, streamer, mode):
        self._streamer = streamer
        self._mode = mode

    def connect(self, r_buf=None, eos_policy=True, readahead=False,
                r_pkg=_EPKG, r_size=_ESIZE, max_calls=_CALLS, w_pkg=_EPKG,
                w_size=_ESIZE):
        """Initiate a stream connection with the referenced streamer.

        :param r_buf:      read buffer for byte data (or None)
        :type  r_buf:      :class:`VStreamBuffer`
        :param eos_policy: use as default read eos mode for stream
        :type  eos_policy: bool
        :param readahead:  if True enable stream readahead
        :type  readahead:  bool
        :param r_pkg:      max pending read push calls
        :type  r_pkg:      int
        :param r_size:     max elements per read push call
        :type  r_size:     int
        :param max_calls:  max pending calls in addition to read push
        :type  max_calls:  int
        :param w_pkg:      max pending write push calls
        :type  w_pkg:      int
        :param w_size:     max elements per write push call
        :type  w_size:     int
        :returns:          stream peer connecting to referenced streamer
        :rtype:            :class:`VStream`

        If *r_buf* is None a default :class:`VByteStreamBuffer` is
        created and used as the stream's buffer for received data.

        This method generates a local-side stream object which
        connects with the referenced streamer. The method should only
        be called once.

        It is also possible to create a connection without calling
        this method, by retreiving a reference to the streamer as
        :attr:`streamer` and creating and connecting a local stream
        object.

        """
        if r_buf is None:
            r_buf = VEntityStreamBuffer()
        stream = VStreamPeer(r_buf=r_buf, r_pkg=r_pkg, r_size=r_size,
                             max_calls=max_calls, mode=self._mode,
                             w_pkg=w_pkg, w_size=w_size)
        stream.set_eos_policy(eos_policy)
        if readahead:
            stream._enable_readahead()
        return stream.connect(self.streamer)

    @property
    def streamer(self):
        """Holds a :class:`versile.orb.entity.VProxy` streamer reference."""
        return self._streamer._v_proxy()

    @property
    def mode(self):
        """Holds the mode set on the stream."""
        return self._mode

    def _v_as_tagged(self, context):
        """Encodes same format as :meth:`VEntityStreamer._v_as_tagged`\ ."""
        tags = VSECodes.ENTITY_STREAMER.tags(context) + (self._mode,)
        return VTagged(self._streamer._v_raw_encoder(), *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        if len(tags) != 1:
            raise VTaggedParseError('Encoding requires one residual tag')
        mode = tags[0]
        if not isinstance(mode, (int, long, VInteger)):
            raise VTaggedParseError('Invalid residual tag')
        def _assemble(args):
            value = args[0]
            value = VModule.as_object(value)
            return cls(value, mode=mode)
        return(_assemble, [value])


@abstract
class VStreamBuffer(object):
    """Internal :class:`VStreamer` and :class:`VStreamPeer` stream data buffer.

    Internal buffering features have been abstracted in order to
    separate stream handling of 'data elements' from the type-specific
    handling of those elements.

    Buffer methods for reading or writing data always operate on an
    absolute data element position in the stream, so it would be
    possible e.g. to implement derived classes which cache data which
    has been read from or written to a stream, if the stream mode indicate
    the stream can be cached.

    Abstract base class, should not be instantiated.

    """

    @abstract
    def new_context(self, pos, can_cache=False):
        """Changes to a new buffer context and repositions the buffer.

        :param pos:       new (absolute) position in buffer
        :type  pos:       int
        :param can_cache: if True buffer may cache data
        :type  can_cache: bool

        If *can_cache* then any data pushed to the buffer can be
        cached for later reading (however the buffer is not required
        to perform such caching).

        The method may be called while another context is already
        active, without calling :meth:`end_context` first.

        """
        raise NotImplementedError()

    @abstract
    def end_context(self):
        """Ends current buffer context.

        Calling this method enables the buffer to release any
        resources tied to the previously active context. It is allowed
        to call this method also when not in an active context.

        """
        raise NotImplementedError()

    @abstract
    def write(self, data, advance=False):
        """Write data onto the buffer's current write position.

        :param data:    data elements to write
        :param advance: if True advance read position to write position
        :type  advance: bool

        """
        raise NotImplementedError()

    @abstract
    def read(self, max_read):
        """Read data from current read position.

        :param max_read: max elements to read
        :type  max_read: int
        :returns:        data read

        Returns an empty data set if no data could be read.

        Advances the read position to the end of the data read. If the
        read position was moved past the previous write position
        during read, then the write position should be automatically
        moved to read position.

        """
        raise NotImplementedError()

    @abstract
    @property
    def max_read(self):
        """Holds max data elements that can be read from current pos (int)."""
        raise NotImplementedError()

    @abstract
    @property
    def rpos(self):
        """Holds the current buffer read position (int)."""
        raise NotImplementedError()

    @abstract
    @property
    def wpos(self):
        """Holds the current buffer write position (int)."""
        raise NotImplementedError()

    @abstract
    def valid_data(self, data):
        """True if data is valid for this buffer type.

        :param data: data elements
        :returns:    True if valid type
        :rtype:      bool

        """
        raise NotImplementedError()

    @abstract
    @classmethod
    def has_data(cls, data):
        """True if data holds any data elements.

        :param data: data elements
        :returns:    True if *data* holds one or more elements
        :rtype:      bool

        """
        raise NotImplementedError()

    @abstract
    @classmethod
    def len_data(cls, data):
        """Returns number of elements held by data.

        :param data: data elements
        :returns:    number of elements held by *data*
        :rtype:      int

        """
        raise NotImplementedError()

    @abstract
    @classmethod
    def first(cls, data, num):
        """Returns first elements of a data elements object.

        :param data: data elements
        :param num:  max elements to return
        :type  num:  int
        :returns:    the first *num* elements of *data*

        If *num* is larger than the number of elements available, then
        all elements are returned.

        """
        raise NotImplementedError()

    @abstract
    @classmethod
    def popfirst(cls, data, num):
        """Returns data elements after popping the first *num* elements.

        :param data: data elements
        :param num:  intiial elements to pop
        :type  num:  int
        :returns:    remaining elements of *data*

        If *num* is larger than the number of elements available, then
        empty data is returned.

        """
        raise NotImplementedError()

    @abstract
    @classmethod
    def join(cls, data_list):
        """Joins the data in provided list and returns the result.

        :param data_list: list or tuple of data subsets
        :returns:         joined data subset of appropriate type

        Each element in *data_list* must be of a type accepted by
        :meth:`valid_data`\ .

        """
        raise NotImplementedError()

    @abstract
    @classmethod
    def empty_data(cls):
        """Returns an empty data elements object.

        :returns: empty data set

        """
        raise NotImplementedError()


class VByteStreamBuffer(VStreamBuffer):
    """Simple stream buffer for byte data.

    The buffer operates on :class:`bytes` data (passed remotely as
    :class:`versile.orb.entity.VBytes`\ ). It does not perform any
    data caching.

    """

    def __init__(self):
        self._rpos = self._wpos = 0
        self._data = VByteBuffer()

    def new_context(self, pos, can_cache=False):
        self._rpos = self._wpos = pos
        self._data.clear()

    def end_context(self):
        self._rpos = self._wpos = 0
        self._data.clear()

    def write(self, data, advance=False):
        self._wpos += len(data)
        if advance:
            self._rpos = self._wpos
            self._data.clear()
        else:
            self._data.append(data)

    def read(self, max_read):
        data = self._data.pop(max_read)
        self._rpos += len(data)
        if self._wpos < self._rpos:
            self._wpos = self._rpos
        return data

    @property
    def max_read(self):
        return len(self._data)

    @property
    def rpos(self):
        return self._rpos

    @property
    def wpos(self):
        return self._wpos

    def valid_data(self, data):
        return isinstance(data, (bytes, VBytes))

    @classmethod
    def has_data(cls, data):
        return bool(data)

    @classmethod
    def len_data(cls, data):
        return len(data)

    @classmethod
    def first(cls, data, num):
        return data[:num]

    @classmethod
    def popfirst(cls, data, num):
        return data[num:]

    @classmethod
    def join(cls, data_list):
        b_elements = []
        for item in data_list:
            if isinstance(item, bytes):
                b_elements.append(item)
            else:
                b_elements.append(item._v_value)
        return b''.join(b_elements)

    @classmethod
    def empty_data(cls):
        return b''


class VEntityStreamBuffer(VStreamBuffer):
    """Simple stream buffer for byte data.

    :param allow_native: if True allow native entity representations
    :type  allow_native: bool

    The buffer operates on :class:`versile.orb.entity.VEntity`
    data. If *allow_native* is True then native type representations
    as returned by :meth:`versile.orb.entity.VEntity._v_lazy_native`
    are also allowed (and type-checking is not performed). The class
    does not perform any data caching.

    """

    def __init__(self, allow_native=True):
        self._allow_native = allow_native
        self._rpos = self._wpos = 0
        self._data = collections.deque()

    def new_context(self, pos, can_cache=False):
        self._rpos = self._wpos = pos
        self._data.clear()

    def end_context(self):
        self._rpos = self._wpos = 0
        self._data.clear()

    def write(self, data, advance=False):
        if not self._allow_native:
            for item in data:
                if not isinstance(item, VEntity):
                    raise VStreamError('Invalid data type')

        self._wpos += len(data)
        if advance:
            self._rpos = self._wpos
            self._data.clear()
        else:
            for item in data:
                self._data.append(item)

    def read(self, max_read):
        data = collections.deque()
        for i in xrange(max_read):
            if self._data:
                data.append(self._data.popleft())
            else:
                break
        data = tuple(data)
        self._rpos += len(data)
        if self._wpos < self._rpos:
            self._wpos = self._rpos
        return data

    @property
    def max_read(self):
        return len(self._data)

    @property
    def rpos(self):
        return self._rpos

    @property
    def wpos(self):
        return self._wpos

    def valid_data(self, data):
        if self._allow_native:
            # If accepting native we only check wrapper is tuple or VTuple
            return isinstance(data, (tuple, VTuple))
        else:
            # Not accepting native, check wrapper and all elements
            if not isinstance(data, VTuple):
                return False
            for item in data:
                if not isinstance(data, VEntity):
                    return False
            return True

    @classmethod
    def has_data(cls, data):
        return bool(data)

    @classmethod
    def len_data(cls, data):
        return len(data)

    @classmethod
    def first(cls, data, num):
        return data[:num]

    @classmethod
    def popfirst(cls, data, num):
        return data[num:]

    @classmethod
    def join(cls, data_list):
        result = []
        for item in data_list:
            result.extend(item)
        return tuple(result)

    @classmethod
    def empty_data(cls):
        return VTuple()


class VStreamPeer(VExternal):
    """Stream interface which interacts with a :class:`VStreamer`.

    :param r_buf:      stream data buffer
    :type  r_buf:      :class:`VStreamBuffer`
    :param r_pkg:      max pending read push packages
    :type  r_pkg:      int
    :param r_size:     max elements per read push package
    :type  r_size:     int
    :param max_calls:  max parallell calls in addition to read push calls
    :type  max_calls:  int
    :param mode:       required stream mode (or None)
    :type  mode:       int
    :param w_pkg:      max pending write push packages
    :type  w_pkg:      int
    :param w_size:     max elements per write push package
    :type  w_size:     int

    A :class:`VStreamPeer` is a local access point to a stream which
    receives and/or sends data by interacting with a remote streamer
    object. Stream operations are initiated by calling :meth:`connect`
    to connect with a remote streamer peer.

    Normally the stream peer object is not used directly, instead
    stream access is performed via a :class:`VStream` proxy object
    returned by :meth:`connect`\ , as this enables garbage collection
    of streams that are no longer in use.

    If *mode* is not None then it is a required mode for the peer
    streamer, and validation is performed during peer connect
    handshake that the peer's mode is identical to this mode. If mode
    information differs then the stream is failed during handshake.

    *w_pkg* and *w_size* are locally set limits. If not None, write
    limits received from a connected stream peer during connect
    handshake will be truncated so they do not exceed local limits.

    A default read-ahead limit is set on the class which is the
    product of *r_pkg* and *r_size*,
    ref. :meth:`VStream.set_readahead`. However, read-ahead is enabled
    by default and needs to be explicitly enabled (see
    :meth:`VStream.enable_readahead`\ ). The default read-ahead limit
    can be overridden by setting another read-ahead limit before
    enabling read-ahead.

    """

    # Codes for read-mode and write-mode
    _READING, _WRITING = 1, 2

    def __init__(self, r_buf, r_pkg=_BPKG, r_size=_BSIZE, max_calls=_CALLS,
                 mode=None, w_pkg=_BPKG, w_size=_BSIZE):
        super(VStreamPeer, self).__init__()

        # Lock/notifier for all I/O handling
        self._cond = threading.Condition()

        self._buf = r_buf
        self._connected = False
        self._done = False            # If True has initiated peer_close()
        self._failed = False          # If True stream has a failure condition
        self._closed = False          # If True has completed peer_close()

        self._mode = None
        self._req_mode = mode

        self._call_lim = r_pkg + max_calls
        self._calls = VSequenceCallQueue(self._call_lim)

        self._r_num = r_pkg
        self._r_size = r_size
        self._r_pending = 0

        self._w_num = None
        self._w_size = None
        self._w_pending = 0

        self._peer = None
        self._caller = VSequenceCaller()

        self._ctx_mode = 0            # Current stream mode
        self._ctx = None              # First msg_id of current context
        self._ctx_err = False         # Error condition on current context
        self._ctx_err_code = None     # Error code for error condition
        self._delayed_seek = None     # Delayed seek info for first context

        self._rel_pos = 0             # Relative position in current context
        self._spos = None             # Start position current context

        self._r_ahead = False         # If True read-ahead is limited
        self._r_ahead_lim = 0         # Limit on read-ahead
        self._r_ahead_step = 0        # Step on read-ahead
        self._set_readahead(r_pkg*r_size)

        self._r_request_eos = True    # If True set EOS for new read contexts

        self._r_rel_lim = 0           # Current rel.position receive limit
        self._r_recv = 0              # Amount data received in context
        self._r_eos = False           # If True then EOS was reached

        self._w_rel_lim = 0
        self._w_sent = 0

        self._peer_w_num = None
        self._peer_w_size = None
        self._local_w_num = w_pkg
        self._local_w_size = w_size

        self._observers = set()

    @publish(show=True, ctx=False)
    def peer_set_start_pos(self, msg_id, ctx, pos):
        """Notify of streamer's start position of the current context.

        :param msg_id:   :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:   int
        :param ctx:      first call ID of current context
        :type  ctx:      int
        :param pos:      absolute start position of context
        :type  pos:      int

        This call is made by a peer in response to starting a new read
        context or write context.

        Should only be called by a connected peer, and can only be
        sent once per context

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id, ctx, pos = conv(msg_id), conv(ctx), conv(pos)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            vchk(ctx, vtyp('int'), vmin(0))
            vchk(pos, vtyp('int'))
        except Exception as e:
            self._fail(msg='Invalid peer_set_start_pos arguments')
            raise e

        with self._cond:
            if self._failed or self._done: return
            handler, calldata = self._peer_set_start_pos, (ctx, pos)
            return self._calls.queue(msg_id, handler, calldata)

    @publish(show=True, ctx=False)
    def peer_read_push(self, msg_id, read_ctx, data, eos):
        """Pushes read data to a read context.

        :param msg_id:    :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:    int
        :param write_ctx: call ID of the receiving read context
        :type  write_ctx: int
        :param data:      data to push (cannot be empty unless *eos* is True)
        :param eos:       if True then end-of-stream after 'data'

        It is not allowed to push read data for a read context after
        *eos* was sent for that context. Also, the caller is
        responsible for making sure that all read push limits are
        followed.

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id, read_ctx, eos = conv(msg_id), conv(read_ctx), conv(eos)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            vchk(read_ctx, vtyp('int'), vmin(0))
            if not self._buf.valid_data(data):
                raise VException('Invalid read push data')
            vchk(eos, vtyp(bool))
        except Exception as e:
            self._fail(msg='Invalid peer_read_push arguments')
            raise e

        with self._cond:
            if self._failed or self._done: return

            self._r_pending += 1
            if self._r_pending > self._r_num:
                self._fail(msg='Too many read packages') ; return
            if not self._buf.valid_data(data):
                self._fail(msg='Invalid read push data') ; return
            len_data = self._buf.len_data(data)
            if len_data == 0 and not eos:
                self._fail(msg='Invalid read push package') ; return
            if len_data > self._r_size:
                self._fail(msg='Read push package too large') ; return

            handler, calldata = self._peer_rpush, (read_ctx, data, eos)
            return self._calls.queue(msg_id, handler, calldata)

    @publish(show=True, ctx=False)
    def peer_write_lim(self, msg_id, write_ctx, rel_pos):
        """Sets a new write push limit for the current read context.

        :param msg_id:    :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:    int
        :param write_ctx: first call ID of the target write context
        :type  write_ctx: int
        :param rel_pos:   write push delimiter after write ctx start position
        :type  rel_pos:   int

        *rel_pos* must be larger than any previously sent write push
        delimiter for this context.

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id, write_ctx = conv(msg_id), conv(write_ctx)
        rel_pos = conv(rel_pos)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            vchk(write_ctx, vtyp('int'), vmin(0))
            vchk(rel_pos, vtyp('int'))
        except Exception as e:
            self._fail(msg='Invalid peer_write_lim arguments')
            raise e

        with self._cond:
            if self._failed or self._done: return
            calldata = (write_ctx, rel_pos)
            return self._calls.queue(msg_id, self._peer_wlim, calldata)

    @publish(show=True, ctx=False)
    def peer_closed(self, msg_id):
        """Acknowledges a peer streamer has closed the stream.

        :param msg_id:    :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:    int

        Acknowledges the streamer received and processed a call to
        :meth:`VStreamer.peer_close`\ .

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id = conv(msg_id)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
        except Exception as e:
            self._fail(msg='Invalid peer_closed arguments')
            raise e

        with self._cond:
            if self._failed or self._closed: return
            return self._calls.queue(msg_id, self._peer_closed, tuple())

    @publish(show=True, ctx=False)
    def peer_fail(self, msg_id, msg=None):
        """Informs the streamer the stream connection has failed.

        :param msg_id:    :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:    int
        :param msg:       error message (or None)
        :type  msg:       unicode

        Signal from the connected stream peer that a critical failure
        occured on the peer end of the stream. The streamer should abort
        all current streamer operation and free related resources.

        Should only be called by a connected peer.

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id = conv(msg_id)
        msg = conv(msg)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            if msg is not None:
                vchk(msg, vtyp(unicode))
        except Exception as e:
            self._fail(msg='Invalid peer_fail arguments')
            raise e

        with self._cond:
            if self._failed or self._closed: return
            return self._calls.queue(msg_id, self._peer_fail, (msg,))

    @publish(show=True, ctx=False)
    def peer_error(self, msg_id, ctx, code):
        """Notifies of an error condition on a context.

        :param msg_id:    :class:`versile.orb.util.VSequenceCaller` call ID
        :type  msg_id:    int
        :param ctx:       first call ID of the affected context
        :type  ctx:       int
        :param code:      error code
        :type  code:      int

        The error condition only applies to the given context, and it
        is stilled allowed to try to initiate new contexts. This is
        different from :meth:`peer_fail` (which sets a general failure
        condtion preventing any further stream operation).

        """

        # Convert arguments to native type
        conv = VEntity._v_lazy_native
        msg_id, ctx, code = conv(msg_id), conv(ctx), conv(code)

        # Validate argument type/range
        try:
            vchk(msg_id, vtyp('int'), vmin(0))
            vchk(ctx, vtyp('int'), vmin(0))
            vchk(code, vtyp('int'))
        except Exception as e:
            self._fail(msg='Invalid peer_error arguments')
            raise e

        with self._cond:
            if self._failed or self._done: return
            handler, calldata = self._peer_error, (ctx, code)
            return self._calls.queue(msg_id, handler, calldata)

    def connect(self, peer):
        """Connect the stream to a peer :class:`VStreamer`\ .

        :param peer:  peer to connect with
        :type  peer:  :class:`versile.orb.entity.VProxy`
        :returns:     stream proxy
        :rtype:       :class:`VStream`

        The returned stream proxy should be used for all further
        interaction with the stream, and references to this stream
        peer object can be dropped (as the stream proxy will hold a
        reference).

        This method should only be called once.

        """
        with self._cond:
            if self._peer:
                raise VStreamError('Peer already connected')
            elif self._failed or self._done:
                raise VStreamError('Stream already done or failed')
            self._peer = peer
            call = peer.peer_connect(self, self._call_lim, self._r_num,
                                     self._r_size, nowait=True)
            call.add_callpair(self.__connect_callback, self.__connect_failback)
            return VStream(self)

    def _wait_status(self, connected=False, active=False, done=False,
                     failed=False, closed=False, timeout=None):
        """See :class:`VStream.wait_status`\ ."""
        with self._cond:
            if timeout is not None and timeout > 0.0:
                start_time = time.time()
            while timeout is None or timeout >= 0.0:
                if ((connected and self._connected)
                    or (active and self._active)
                    or (done and self._done)
                    or (failed and self._failed)
                    or (closed and self._closed)):
                    return True
                if timeout == 0.0:
                    break
                self._cond.wait(timeout)
                if timeout is not None and timeout > 0.0:
                    curr_time = time.time()
                    timeout -= curr_time - start_time
                    start_time = curr_time
            else:
                return False

    def _set_readahead(self, num, step=None):
        """See :class:`VStream.set_readahead`\ ."""
        if step is None:
            step = num//2 + num%2
        with self._cond:
            self._r_ahead_lim = num
            self._r_ahead_step = step

            if self._r_ahead:
                self.__update_rlim()

    def _enable_readahead(self):
        """See :class:`VStream.enable_readahead`\ ."""
        with self._cond:
            self._r_ahead = True
            self.__update_rlim()

    def _disable_readahead(self, at_rel_pos=None):
        """See :class:`VStream.disable_readahead`\ ."""
        # ISSUE: at_rel_pos currently ignored
        with self._cond:
            self._r_ahead = False

    def _recv(self, max_num, timeout=None):
        """See :class:`VStream.recv`\ ."""
        with self._cond:
            if self._failed:
                raise VStreamFailure('General stream failure')
            if self._done:
                raise VStreamError('Stream was closed')

            if self._ctx_mode != self._READING:
                if self._delayed_seek:
                    pos, pos_base = self._delayed_seek
                    self._delayed_seek = None
                else:
                    pos = pos_base = None
                self.__start_read_ctx(pos, pos_base, self._r_request_eos)
            elif self._ctx_err:
                Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                raise Exc('Error condition on read context')

            # If read buffer is empty, lazy-send new read limits to peer
            if self._buf.max_read == 0:
                if self._r_ahead:
                    self.__update_rlim()
                elif self._r_rel_lim - self._rel_pos < max_num:
                    self._r_rel_lim = self._rel_pos + max_num
                    cdata = (self._r_rel_lim,)
                    try:
                        self._caller.call(self._peer.peer_read_lim, cdata)
                    except VCallError:
                        self._fail(msg='Could not perform remote call')

            # Wait for read buffer data
            r_ctx = self._ctx
            if timeout is not None and timeout > 0.0:
                start_time = time.time()
            while timeout is None or timeout >= 0.0:
                if self._ctx != r_ctx:
                    # Local context has changed
                    raise VStreamError('Local context changed')
                if self._failed:
                    raise VStreamFailure('General stream failure')
                elif self._done:
                    raise VStreamError('Stream was closed')
                elif self._ctx_err:
                    Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                    raise Exc('Error condition on read context')
                data = self._buf.read(max_num)
                if data:
                    self._rel_pos += self._buf.len_data(data)
                    self.__update_rlim()
                    return data
                elif self._r_eos:
                    return self._buf.empty_data()
                if timeout == 0.0:
                    break
                self._cond.wait(timeout)
                if timeout is not None and timeout > 0.0:
                    curr_time = time.time()
                    timeout -= curr_time - start_time
                    start_time = curr_time
            else:
                raise VStreamTimeout()

    def _send(self, data, timeout):
        """See :class:`VStream.send`\ ."""
        with self._cond:
            if self._failed:
                raise VStreamFailure('General stream failure')
            elif self._done:
                raise VStreamError('Stream was closed')

            if self._ctx_mode != self._WRITING:
                if self._delayed_seek:
                    pos, pos_base = self._delayed_seek
                    self._delayed_seek = None
                else:
                    pos = pos_base = None
                self.__start_write_ctx(pos, pos_base)
            elif self._ctx_err:
                Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                raise Exc('Error condition on read context')

            # If 'data' is empty, just return
            if not self._buf.has_data(data):
                return 0

            # Enter wait loop for sending data
            w_ctx = self._ctx
            if timeout is not None and timeout > 0.0:
                start_time = time.time()
            while timeout is None or timeout >= 0.0:
                if self._failed:
                    raise VStreamFailure('General stream failure')
                elif self._done:
                    raise VStreamError('Stream was closed')
                elif self._ctx != w_ctx:
                    raise VStreamError('Context was changed')
                elif self._ctx_err:
                    Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                    raise Exc('Error condition on read context')

                max_send = max(self._w_rel_lim - self._w_sent, 0)
                max_send = min(max_send, self._w_size)
                if (self._w_pending < self._w_num and max_send > 0
                    and self._spos is not None):
                    send_data = self._buf.first(data, max_send)
                    calldata = (self._ctx, send_data)
                    callback = self._wpush_callback
                    try:
                        self._caller.call(self._peer.peer_write_push, calldata,
                                          callback=callback,
                                          failback=self._fail)
                    except VCallError:
                        self._fail(msg='Could not perform remote call')
                    self._buf.write(send_data, advance=True)
                    self._w_pending += 1
                    num_sent = self._buf.len_data(send_data)
                    self._rel_pos += num_sent
                    self._w_sent += num_sent
                    return num_sent
                if timeout == 0.0:
                    break
                self._cond.wait(timeout)
                if timeout is not None and timeout > 0.0:
                    curr_time = time.time()
                    timeout -= curr_time - start_time
                    start_time = curr_time
            else:
                raise VStreamTimeout()

    def _close(self):
        """See :class:`VStream.close`\ ."""
        with self._cond:
            self._done = True
            # Status changed, notify
            self._cond.notify_all()
            try:
                msg_id = self._caller.call(self._peer.peer_close, tuple())
            except VCallError:
                self._fail(msg='Could not perform remote call')

    def _rseek(self, pos, pos_ref=VStreamPos.ABS, timeout=None):
        """See :class:`VStream.rseek`\ ."""
        with self._cond:
            if pos_ref == VStreamPos.CURRENT:
                # Translate to absolute reference
                pos += self._pos(timeout=timeout)
                pos_ref = VStreamPos.ABS
            self.__seek_to(pos, pos_ref, timeout)
            self.__start_read_ctx(pos, pos_ref, self._r_request_eos)

    def _wseek(self, pos, pos_ref=VStreamPos.ABS, timeout=None):
        """See :class:`VStream.wseek`\ ."""
        with self._cond:
            if pos_ref == VStreamPos.CURRENT:
                # Translate to absolute reference
                pos += self._pos(timeout=timeout)
                pos_ref = VStreamPos.ABS
            self.__seek_to(pos, pos_ref, timeout)
            self.__start_write_ctx(pos, pos_ref)

    def _seek(self, pos, pos_ref=VStreamPos.ABS, timeout=None):
        """See :class:`VStream.seek`\ ."""
        with self._cond:
            if not self._mode & (VStreamMode.SEEK_REW | VStreamMode.SEEK_FWD):
                raise VStreamError('Stream does not allow seek operations')
            if self._ctx_mode == self._READING:
                return self._rseek(pos, pos_ref, timeout=timeout)
            elif self._ctx_mode == self._WRITING:
                return self._wseek(pos, pos_ref, timeout=timeout)
            else:
                if pos_ref == VStreamPos.CURRENT:
                    # Translate to absolute reference
                    pos += self._pos(timeout=timeout)
                    pos_ref = VStreamPos.ABS
                self._delayed_seek = (pos, pos_ref)

    def _pos(self, timeout=None):
        """See :class:`VStream.tell`\ ."""
        with self._cond:
            if timeout is not None and timeout > 0.0:
                start_time = time.time()
            while timeout is None or timeout >= 0.0:
                if self._failed:
                    raise VStreamFailure('General stream failure')
                elif self._done:
                    raise VStreamError('Stream was closed')
                elif self._ctx_err:
                    Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                    raise Exc('Context has error condition')

                if self._spos is not None:
                    return self._spos + self._rel_pos
                if timeout == 0.0:
                    break
                self._cond.wait(timeout)
                if timeout is not None and timeout > 0.0:
                    curr_time = time.time()
                    timeout -= curr_time - start_time
                    start_time = curr_time
            else:
                raise VStreamTimeout()

    def _trunc_before(self, timeout=None):
        """See :class:`VStream.trunc_before`\ ."""
        with self._cond:
            if not (self._mode & VStreamMode.CAN_MOVE_START
                    and self._mode & VStreamMode.START_CAN_INC):
                raise VStreamError('Stream does not allow start truncation')
            if self._ctx_mode != self._WRITING:
                raise VStreamError('Must be in write-mode when truncating')
            if self._failed:
                raise VStreamFailure('General stream failure')
            elif self._done:
                raise VStreamError('Stream was closed')
            elif self._ctx_err:
                Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                raise Exc('Error condition on read context')

            # Wait for a start position to be present on the context
            w_ctx = self._ctx
            if timeout is not None and timeout > 0.0:
                start_time = time.time()
            while timeout is None or timeout >= 0.0:
                if self._ctx != w_ctx:
                    raise VStreamError('Context was changed')
                if self._failed:
                    raise VStreamFailure('General stream failure')
                elif self._done:
                    raise VStreamError('Stream was closed')
                elif self._ctx_err:
                    Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                    raise Exc('Error condition on read context')
                if self._spos is not None:
                    break
                if timeout == 0.0:
                    break
                self._cond.wait(timeout)
                if timeout is not None and timeout > 0.0:
                    curr_time = time.time()
                    timeout -= curr_time - start_time
                    start_time = curr_time
            else:
                raise VStreamTimeout()

            # We have a start position so allowed to truncate
            try:
                msg_id = self._caller.call(self._peer.peer_trunc_before,
                                           tuple(), failback=self._fail)
            except VCallError:
                self._fail(msg='Could not perform remote call')
                raise VStreamFailure('Could not perform remote call')
            else:
                # Truncation updates the context ID
                self._ctx = msg_id

    def _trunc_after(self, timeout=None):
        """See :class:`VStream.trunc_after`\ ."""
        with self._cond:
            if not (self._mode & VStreamMode.CAN_MOVE_END
                    and self._mode & VStreamMode.END_CAN_DEC):
                raise VStreamError('Stream does not allow end truncation')
            if self._ctx_mode != self._WRITING:
                raise VStreamError('Must be in write-mode when truncating')
            if self._failed:
                raise VStreamFailure('General stream failure')
            elif self._done:
                raise VStreamError('Stream was closed')
            elif self._ctx_err:
                Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                raise Exc('Error condition on read context')

            # Wait for a start position to be present on the context
            w_ctx = self._ctx
            if timeout is not None and timeout > 0.0:
                start_time = time.time()
            while timeout is None or timeout >= 0.0:
                if self._ctx != w_ctx:
                    raise VStreamError('Context was changed')
                if self._failed:
                    raise VStreamFailure('General stream failure')
                elif self._done:
                    raise VStreamError('Stream was closed')
                elif self._ctx_err:
                    Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                    raise Exc('Error condition on read context')
                if self._spos is not None:
                    break
                if timeout == 0.0:
                    break
                self._cond.wait(timeout)
                if timeout is not None and timeout > 0.0:
                    curr_time = time.time()
                    timeout -= curr_time - start_time
                    start_time = curr_time
            else:
                raise VStreamTimeout()

            # We have a start position so allowed to truncate
            try:
                msg_id = self._caller.call(self._peer.peer_trunc_after,
                                           tuple(), failback=self._fail)
            except VCallError:
                self._fail(msg='Could not perform remote call')
                raise VStreamFailure('Could not perform remote call')
            else:
                # Truncation updates the context ID
                self._ctx = msg_id

                # Truncation invalidates any previous write limit
                self._w_rel_lim = self._w_sent

    def set_eos_policy(self, req_eos):
        """See :class:`VStream.set_eos_policy`\ .

        This method may be called before the object is connected to a
        peer streamer.

        """
        with self._cond:
            self._r_request_eos = req_eos

    def _add_observer(self, observer):
        """See :class:`VStream.add_observer`\ ."""
        with self._cond:
            has_observer = False
            remove_set = set()
            for o_weak in self._observers:
                o = o_weak()
                if o is observer:
                    has_observer = True
                elif o is None:
                    remove_set.add(o_weak)
            for o_weak in remove_set:
                self._observers.discard(o_weak)
            if not has_observer:
                self._observers.add(weakref.ref(observer))

    def _remove_observer(self, observer):
        """See :class:`VStream.remove_observer`\ ."""
        with self._cond:
            remove_set = set()
            for o_weak in self._observers:
                o = o_weak()
                if o is observer or o is None:
                    remove_set.add(o_weak)
            for o_weak in remove_set:
                self._observers.discard(o_weak)

    @property
    def _active(self):
        return self._connected and not (self._done or self._closed
                                        or self._failed)

    def _peer_set_start_pos(self, ctx, pos):
        with self._cond:
            if self._failed or self._done or self._ctx_err: return
            if self._spos is not None:
                self._fail(msg='Too many position notifications') ; return
            if self._ctx == ctx:
                self._spos = pos
                can_cache = (self._mode & VStreamMode.FIXED_DATA
                             or self._mode & VStreamMode.DATA_LOCK)
                self._buf.new_context(pos, can_cache=can_cache)
                self._cond.notify_all()

    def _peer_rpush(self, read_ctx, data, eos):
        with self._cond:
            if self._failed or self._done or self._ctx_err: return
            self._r_pending -= 1

            # Validate context
            if read_ctx != self._ctx:
                return
            if self._ctx_mode != self._READING:
                self._fail(msg='Read push without read mode') ; return

            # rpush only allowed after start position was specified
            if self._spos is None:
                self._fail(msg='Read push without position') ; return

            # cannot send data or eos after eos already sent
            if self._r_eos:
                self._fail(msg='Read push after end-of-stream') ; return

            # Check data or overflow
            len_data = self._buf.len_data(data)
            if self._r_recv + len_data > self._r_rel_lim:
                self._fail(msg='Read push limit exceeded') ; return

            # Push data to buffer and send I/O notification
            if self._observers:
                had_data = (self._buf.max_read > 0)
            self._buf.write(data)
            self._r_recv += len_data
            if eos:
                self._r_eos = True
            self._cond.notify_all()

            # Notify any stream observers
            if self._observers and len_data > 0 and not had_data:
                for o_weak in self._observers:
                    obs = o_weak()
                    if obs:
                        try:
                            obs.can_recv()
                        except Exception as e:
                            _v_silent(e)

    def _peer_wlim(self, write_ctx, rel_pos):
        with self._cond:
            if self._failed or self._done or self._ctx_err: return

            # Validate context
            if write_ctx != self._ctx:
                return
            elif self._ctx_mode != self._WRITING:
                self._fail(msg='Write limit requires write mode') ; return
            elif self._ctx_err:
                Exc = VStreamErrorCode.exc_cls(self._ctx_err_code)
                raise Exc('Error condition on write context')

            # write lim only allowed after start position was specified
            if self._spos is None:
                self._fail(msg='Write limit without position') ; return

            if rel_pos <= self._w_rel_lim:
                self._fail(msg='Illegal write limit') ; return
            if self._observers:
                could_write = (self._w_rel_lim > self._w_sent)
            self._w_rel_lim = rel_pos
            self._cond.notify_all()

            # Notify any stream observers
            if (self._observers and not could_write
                and self._w_rel_lim > self._w_sent):
                for o_weak in self._observers:
                    obs = o_weak()
                    if obs:
                        try:
                            obs.can_send()
                        except Exception as e:
                            _v_silent(e)

    def _peer_closed(self):
        with self._cond:
            if self._failed or self._closed or self._ctx_err: return
            self._closed = True
            self._cond.notify_all()
            # Notify any stream observers
            if self._observers:
                for o_weak in self._observers:
                    obs = o_weak()
                    if obs:
                        try:
                            obs.closed()
                        except Exception as e:
                            _v_silent(e)
            self.__cleanup()

    def _peer_fail(self, msg):
        with self._cond:
            if not self._failed:
                self._failed = True
                # Notify any stream observers
                for o_weak in self._observers:
                    obs = o_weak()
                    if obs:
                        try:
                            obs.failed()
                        except Exception as e:
                            _v_silent(e)
                self.__cleanup()

    def _peer_error(self, ctx, code):
        with self._cond:
            if self._failed or self._done or self._ctx_err: return
            if ctx == self._ctx:
                self._ctx_err = True
                self._ctx_err_code = code
                self._cond.notify_all()
                # Notify any stream observers
                for o_weak in self._observers:
                    obs = o_weak()
                    if obs:
                        try:
                            obs.ctx_error()
                        except Exception as e:
                            _v_silent(e)

    def _wpush_callback(self, result):
        with self._cond:
            if self._failed or self._done: return
            was_peak = (self._w_pending == self._w_num)
            self._w_pending -= 1
            if self._ctx_mode == self._WRITING and was_peak:
                self._cond.notify_all()

    def _fail(self, exc=None, msg=None):
        """Sets a general failure condition and schedules peer notification.

        Takes an unused *exc* parameter so it can serve as a failback.

        """
        with self._cond:
            if not self._failed or self._done:
                self._failed = True
                self._cond.notify_all()

                if exc and msg is None and e.message:
                    msg = e.message
                if self._peer:
                    try:
                        self._caller.call(self._peer.peer_fail, (msg,))
                    except VCallError as e:
                        # Ignoring as stream was already failed
                        _v_silent(e)
                # Notify any stream observers
                for o_weak in self._observers:
                    obs = o_weak()
                    if obs:
                        try:
                            obs.failed()
                        except Exception as e:
                            _v_silent(e)
                self.__cleanup()

    def __start_read_ctx(self, pos, pos_base, eos):
        """Set up a read context.

        Position must be already translated (VStreamPos.CURRENT
        is not allowed)

        """
        self.__clear_ctx_data()
        self._ctx_mode = self._READING
        cdata = (pos, pos_base, self._r_request_eos)
        try:
            self._ctx = self._caller.call(self._peer.peer_read_start, cdata)
        except VCallError:
            self._fail(msg='Could not perform remote call')
        self.__update_rlim()

    def __start_write_ctx(self, pos, pos_base):
        """Set up a read context.

        Position must be already translated (VStreamPos.CURRENT
        is not allowed)

        """
        self.__clear_ctx_data()
        self._ctx_mode = self._WRITING
        try:
            self._ctx = self._caller.call(self._peer.peer_write_start,
                                          (pos, pos_base))
        except VCallError:
            self._fail(msg='Could not perform remote call')

    def __seek_to(self, pos, pos_ref, timeout):
        """Caller must hold a lock on self._cond

        Position must be already translated (VStreamPos.CURRENT
        is not allowed)

        """
        if not self._mode & (VStreamMode.SEEK_REW | VStreamMode.SEEK_FWD):
            raise VStreamError('Stream does not allow seek operations')
        if pos_ref == VStreamPos.ABS and self._spos is not None:
            cur_pos = self._spos + self._rel_pos
            if pos == cur_pos:
                return # Already at pos
            if pos > cur_pos and not self._mode & VStreamMode.SEEK_FWD:
                raise VStreamError('Forward seek not allowed')
            if pos < cur_pos and not self._mode & VStreamMode.SEEK_REW:
                raise VStreamError('Backward seek not allowed')

    def __update_rlim(self):
        """Tests whether to update read limit based on read-ahead."""
        with self._cond:
            if not self._ctx_mode & self._READING or not self._r_ahead:
                return
            lim = self._rel_pos + self._r_ahead_lim
            lim -= lim % self._r_ahead_step
            if lim > self._r_rel_lim:
                self._r_rel_lim = lim
                try:
                    self._caller.call(self._peer.peer_read_lim,
                                      (self._r_rel_lim,))
                except VCallError:
                    self._fail(msg='Could not perform remote call')

    def __connect_callback(self, res):
        with self._cond:
            self._mode, self._spos, clim, w_num, w_size = res

            # Validate received data
            try:
                vchk(self._mode, vtyp('int'), vmin(0))
                vchk(self._spos, vtyp('int'))
                for arg in clim, w_num, w_size:
                    vchk(arg, vtyp('int'), vmin(1))
            except Exception as e:
                self._fail()
                raise e

            if self._req_mode is not None and self._req_mode != self._mode:
                self._fail(msg='Streamer peer mode mismatch') ; return
            # Also validate mode is a legal combination
            VStreamMode.validate(self._mode)

            self._peer_w_num = self._w_num = w_num
            if self._local_w_num is not None:
                self._w_num = min(self._w_num, self._local_w_num)
            self._peer_w_size = self._w_size = w_size
            if self._local_w_size is not None:
                self._w_size = min(self._w_size, self._local_w_size)

            self._connected = True
            self._caller.set_limit(clim)
            self._cond.notify_all()

    def __connect_failback(self, exception):
        with self._cond:
            self._fail(msg='Connect failure')

    def __clear_ctx_data(self):
        """Clears all current context settings."""
        self._ctx_mode = 0
        self._ctx = None
        self._ctx_err = False
        self._ctx_err_code = None
        self._spos = None
        self._rel_pos = 0
        self._r_rel_lim = 0
        self._r_recv = 0
        self._r_eos = False
        self._w_rel_lim = 0
        self._w_sent = 0
        self._buf.end_context()

    def __cleanup(self):
        self.__clear_ctx_data()
        self._peer = None
        self._calls = None
        self._observers.clear()


class VStream(object):
    """Stream proxy for accessing a connected :class:`VStreamPeer`\ .

    :param stream: stream peer to proxy
    :type  stream: :class:`VStreamPeer`

    See :class:`VStreamPeer` for details about e.g. read-ahead.

    """

    def __init__(self, stream):
        self._stream = stream

    def __del__(self):
        """When stream object is dereferenced, close or fail stream."""
        with self._stream._cond:
            if not self._stream._connected:
                self._stream._fail(msg='Stream no longer referenced')
            elif self._stream._active:
                self._stream._close()

    def wait_status(self, connected=False, active=False, done=False,
                    failed=False, closed=False, timeout=None):
        """Wait for a stream state to occur.

        :param connected: if True wait for :attr:`connected`
        :type  connected: bool
        :param active:    if True wait for :attr:`active`
        :type  active:    bool
        :param done:      if True wait for :attr:`done`
        :type  done:      bool
        :param failed:    if True wait for :attr:`failed`
        :type  failed:    bool
        :param closed:    if True wait for :attr:`closed`
        :type  closed:    bool
        :param timeout:   max seconds to wait (or None)
        :type  timeout:   float
        :returns:         True if condition was met before timeout
        :rtype:           bool

        The method returns when one of the states being listened for
        is set to a 'True' status, or when the timeout expires.

        """
        return self._stream._wait_status(connected, active, done, failed,
                                         closed, timeout)

    def set_readahead(self, num, step=None):
        """Sets a read-ahead limit for receiving data.

        :param num:  maximum data elements to read-ahead
        :type  num:  int
        :param step: step increment of read-ahead (or None)
        :type  step: int

        If *step* is None then the default is num/2 (rounded up).

        Read-ahead makes the stream request read data from the
        streamer peer which is buffered locally for reading. This has
        a number of effects:

        * Read data is transferred before requested locally
        * Can dramatically improve stream bandwidth and latency performance
          (especially when tuned in combination with stream settings for
          maximum pending read push calls and max read push package size),
          compensating for round-trip latency effects of performing
          individual remote calls
        * Steals bandwidth of buffering data which is never read locally
        * De-couples local stream position and peer streamer position as
          peer streamer advances faster than local stream, which means
          the local stream must be careful about performing seek operations
          relative to the 'current' position

        Setting read-ahead parameters does not activate read-ahead,
        this requires calling :meth:`enable_readahead`\ .

        """
        return self._stream._set_readahead(num, step)

    def enable_readahead(self):
        """Enables read-ahead on reading contexts.

        See :meth:`set_readahead` for information about the effects
        and consequences of using read-ahead.

        """
        return self._stream._enable_readahead()

    def disable_readahead(self, at_rel_pos=None):
        """Disable read-ahead on reading contexts.

        :param at_rel_pos: requested position to stop read-ahead
        :type  at_rel_pos: int

        """
        return self._stream._disable_readahead(at_rel_pos)

    def recv(self, max_num, timeout=None):
        """Reads stream data from the current read context.

        :param max_num: max elements to read
        :type  max_num: int
        :param timeout: max seconds to wait for data (or None)
        :type  timeout: float
        :returns:       data elements read
        :raises:        :exc:`VStreamTimeout`\ , :exc:`VStreamError`

        The stream should normally have an active read context when
        calling this method. If a set of empty data elements is
        returned then end-of-stream was reached. Raises
        :exc:`VStreamTimeout` if no data could be read before timeout
        expired.

        The method may return fewer than *max_num* elements, however
        if returned data is not empty this does not imply
        end-of-stream.

        If the stream currently has an active write context, calling
        this method will initiate a new read context on the current
        position.

        """
        return self._stream._recv(max_num, timeout)

    def read(self, num=None, bsize=1024*1024):
        """Reads stream data from the current read context.

        :param num:   elements to read (or None)
        :type  num:   int
        :param bsize: maximum block size for recv operations
        :type  bsize: int
        :returns:     data elements read
        :raises:      :exc:`VStreamError`

        If *num* is None then all data is read from the stream until
        end-of-stream is reached (note end-of-stream policy must be
        True).

        This is a convenience method for performing blocking read
        operations until a given amount of data has been read or
        end-of-stream is reached. The method uses the lower-level
        method :meth:`recv` for reading.

        .. note::

            Use :meth:`recv` for lower-level capabilities such as
            non-blocking I/O

        The stream should normally have an active read context when
        calling this method. If a set of empty data elements is
        returned then end-of-stream was reached.

        The method may return fewer than *num* elements if
        end-of-stream was reached. If the stream end-of-stream policy
        is not set to True then the call will block indefinitely when
        reaching the stream boundary.

        If the stream currently has an active write context, calling
        this method will initiate a new read context on the current
        position.

        """
        buf = self._stream._buf  # Provides various class methods for data
        sub_seq = []
        num_read = 0

        while num is None or num_read < num:
            if num is None:
                recv_lim = bsize
            else:
                recv_lim = num - num_read
            data = self._stream._recv(recv_lim)
            if not buf.has_data(data):
                break
            sub_seq.append(data)
            num_read += buf.len_data(data)

        return buf.join(sub_seq)

    def send(self, data, timeout=None):
        """Writes data to a current active stream write context.

        :param data:    data to write
        :param timeout: max seconds to wait for data (or None)
        :type  timeout: float
        :returns:       number of elements sent
        :rtype:         int
        :raises:        :exc:`VStreamTimeout`\ , :exc:`VStreamException`

        Returns the number of elements that could be written, which
        may be less than the number of elements held by *data*. Raises
        :exc:`VStreamTimeout` if no data could be written before
        timeout expired.

        .. note::

            There is no guarantee that accepted data was actually
            received and processed as expected by a peer streamer, it
            only acknowledges that data was sent to the peer streamer.

        If the stream currently has an active read context, calling
        this method will initiate a new write context on the current
        position.

        .. warning::

            Due to read-ahead buffering effects, the start position of
            the peer streamer's resulting write context may not be
            deterministic. In order to control position, :meth:`wseek`
            should be called first (if seek is allowed on stream), or
            read-ahead must be disabled.

        """
        return self._stream._send(data, timeout)

    def write(self, data):
        """Writes data to a current active stream write context.

        :param data: data to write
        :raises:     :exc:`VStreamException`

        This is a convenience method for performing blocking write
        operations until all data has been written. The method uses
        the lower-level method :meth:`send` for sending.

        .. note::

            Use :meth:`send` for lower-level capabilities such as
            non-blocking I/O

        Writes all data before returning. If all data could not be
        written or an error condition occurs while reading, an
        exception is raised.

        .. note::

            There is no guarantee that accepted data was actually
            received and processed as expected by a peer streamer, it
            only acknowledges that data was sent to the peer streamer.

        If the stream currently has an active read context, calling
        this method will initiate a new write context on the current
        position.

        .. warning::

            Due to read-ahead buffering effects, the start position of
            the peer streamer's resulting write context may not be
            deterministic. In order to control position, :meth:`wseek`
            should be called first (if seek is allowed on stream), or
            read-ahead must be disabled.

        """
        buf = self._stream._buf # Provides various class methods for data
        while buf.has_data(data):
            num_sent = self.send(data)
            data = buf.popfirst(data, num_sent)

    def rseek(self, pos, pos_ref=VStreamPos.ABS, timeout=None):
        """Seeks to a new stream position and starts a new read context.

        Seek arguments are similar to :class:`VStreamerData.seek`\ .

        """
        return self._stream._rseek(pos, pos_ref, timeout)

    def wseek(self, pos, pos_ref=VStreamPos.ABS, timeout=None):
        """Seeks to a new stream position and starts a new write context.

        :param timeout: timeout in seconds (or None)
        :type  timeout: float
        :raises:        :class:`VStreamTimeout`\ , :class:`VStreamError`

        Other seek arguments are similar to
        :class:`VStreamerData.seek`\ . If seek operation cannot be
        initiated before timeout expires, :class:`VStreamTimeout` is
        raised. This should typically be because a seek operation is
        attempted which is relative to the current position, but the
        current absolute position cannot be determined before timeout
        expires.

        """
        return self._stream._wseek(pos, pos_ref, timeout)

    def seek(self, pos, pos_ref=VStreamPos.ABS, timeout=None):
        """Seeks to a new stream position.

        Arguments are similar to :meth:`wseek`\ .

        Starts a new context of same type as any current active
        context, e.g. if the stream has a current active read context,
        then a new read context is initiated.

        If there is no current active context, the position is logged
        as the position and position reference to be used if a new
        context is lazy-started without position information.

        """
        return self._stream._seek(pos, pos_ref, timeout)

    def pos(self, timeout=None):
        """Returns the current (absolute) stream position.

        :returns: current (absolute) stream position
        :rtype:   int
        :raises: :exc:`VStreamTimeout`\ , :exc:`VStreamError`

        Returned stream position is the current local stream position,
        which is at the beginning of any locally buffered data. A
        position may not always be available due to synchronization
        effects with the peer streamer; if the method times out before
        a position is available then :exc:`VStreamTimeout` is raised.

        """
        return self._stream._pos(timeout)

    def trunc_before(self, timeout=None):
        """Truncates stream data before current position.

        :param timeout: timeout in seconds (or None)
        :type  timeout: float
        :raises:        :class:`VStreamTimeout`\ , :class:`VStreamError`

        If truncation cannot be initiated before timeout expires,
        :class:`VStreamTimeout` is raised. This should typically be
        because the peer has not yet acknowledged the current context
        by sending a start position notification.

        The stream must be in write-mode when this method is called.

        """
        return self._stream._trunc_before(timeout)

    def trunc_after(self, timeout=None):
        """Truncates stream data after current position.

        :param timeout: timeout in seconds (or None)
        :type  timeout: float
        :raises:        :class:`VStreamTimeout`\ , :class:`VStreamError`

        If truncation cannot be initiated before timeout expires,
        :class:`VStreamTimeout` is raised. This should typically be
        because the peer has not yet acknowledged the current context
        by sending a start position notification.

        The stream must be in write-mode when this method is called.

        """
        return self._stream._trunc_after(timeout)

    def iterator(self, timeout=None, close=True):
        """Returns an iterator for data elements.

        :param timeout: timeout in seconds for an iteration (or None)
        :type  timeout: float
        :param close:   if True close stream when iterator completes
        :type  close:   bool
        :returns:       iterator for data elements
        :rtype:         iterator

        The stream must be set up with end-of-stream policy set to
        'True' so the iterator can detect end-of-stream. The stream
        must also readable.

        The iterator reads one element with :meth:`recv` to read
        objects until end-of-stream is reached. *timeout* is applied
        to each individual 'next' operation on the iterator, and
        :exc:`VStreamTimeout` is raised if the iteration times
        out. The 'next' operation may also raise other
        :exc:`VStreamError` exceptions if there are error conditions
        on the stream.

        If *close* is True then the stream is closed after the
        iterator completes.

        The iterator assumes it has complete control of stream I/O,
        and no other methods should be called on this stream object
        until the iterator has completed or is no longer used.

        """
        if not self._stream._mode & VStreamMode.READABLE:
            raise VStreamError('Stream not readable')
        return _VStreamIterator(self, timeout, close)

    def close(self):
        """Closes the stream.

        Initiates stream close with the peer streamer. No other stream
        operations should be performed on the stream object after
        calling this method.

        """
        return self._stream._close()

    def set_eos_policy(self, req_eos):
        """Sets end-of-stream policy for new read contexts.

        :param req_eos: if True request end-of-stream on new read contexts
        :type  req_eos: bool

        The policy is only applied to new read contexts, and does not apply
        to any current active read context.

        """
        return self._stream.set_eos_policy(req_eos)

    @property
    def connected(self):
        """True if stream was (sometime) successfully connected to a peer."""
        with self._stream._cond:
            return self._stream._connected

    @property
    def active(self):
        """True if stream was connected and is not done, failed or closed."""
        return self._stream._active

    @property
    def done(self):
        """True if stream has been locally closed."""
        with self._stream._cond:
            return self._stream._done

    @property
    def closed(self):
        """True if stream was closed and peer acknowledged closing."""
        with self._stream._cond:
            return self._stream._closed

    @property
    def failed(self):
        """True if stream has failed."""
        with self._stream._cond:
            return self._stream._failed

    def add_observer(self, observer):
        """Adds an observer for stream event notifications.

        :param observer: receiver of notifications
        :type  streamer: :class:`VStreamObserver`

        Will only hold a weak reference to registered observers.

        """
        return self._stream._add_observer(observer)

    def remove_observer(self, observer):
        """Remove observer from list of observers receiving notifications.

        :param observer: receiver of notifications
        :type  streamer: :class:`VStreamObserver`

        """
        return self._stream._remove_observer(observer)


class VStreamObserver(object):
    """Base class for receiving notifications from a :class:`VStream`\ .

    :param stream: stream to observe
    :type  stream: :class:`VStream`

    """

    def __init__(self, stream):
        self._stream = stream
        self._stream.add_observer(self)

    def __del__(self):
        if self._stream:
            self._stream.remove_observer(self)

    def disable(self):
        """Disable this observer, unregistering from any observed stream."""
        if self._stream:
            self._stream.remove_observer(self)
            self._stream = None

    def can_recv(self):
        """Called by observed stream when data available for reading.

        Only called as an 'edge' call, when the stream receives data
        available for reading after it had no data available for
        reading.

        Default does nothing, derived classes can override.

        """
        pass

    def can_send(self):
        """Called by observed stream when data available for writing.

        Only called as an 'edge' call, when the stream can send data
        when it previously could not.

        Default does nothing, derived classes can override.

        """

    def closed(self):
        """Called by observed stream when peer streamer acknowledges close.

        Default does nothing, derived classes can override.

        """
        pass

    def ctx_error(self):
        """Called by observed stream when an error is set on current context.

        Default does nothing, derived classes can override.

        """
        pass

    def failed(self):
        """Called by observed stream when a failure condition is set on stream.

        Default does nothing, derived classes can override.

        """
        pass


# Used by :meth:`VStream.iterator`
class _VStreamIterator(object):
    def __init__(self, stream, timeout, close):
        self._stream = stream
        self._timeout = timeout
        self._close = close
        self._done = False

    def __iter__(self):
        return self

    def next(self):
        if self._done:
            raise StopIteration()
        # This may raise stream exceptions
        data = self._stream.recv(max_num=1, timeout=self._timeout)
        if data:
            return data[0]
        else:
            self._done = True
            if self._close:
                self._stream.close()
            self._stream = None
            raise StopIteration()


class VStreamModule(VModule):
    """Module for stream objects.

    The module resolves :class:`VByteSink` and :class:`VByteSource`\ .

    """
    def __init__(self):
        super(VStreamModule, self).__init__()

        _decoder = VByteStreamerProxy._v_vse_decoder
        self.add_decoder(VSECodes.BYTE_STREAMER.mod_decoder(_decoder))

        _decoder = VEntityStreamerProxy._v_vse_decoder
        self.add_decoder(VSECodes.ENTITY_STREAMER.mod_decoder(_decoder))

_vmodule = VStreamModule()
VModuleResolver._add_vse_import(VSEModuleCodes.STREAM, _vmodule)
