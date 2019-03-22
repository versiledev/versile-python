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

"""Various utility classes."""
from __future__ import print_function, unicode_literals

import base64
from collections import deque
import os
import tempfile
import threading
import time
import weakref

from versile.internal import _b2s, _s2b, _bfmt, _vexport, _v_silent, _pyver
from versile.internal import _b_ord, _b_chr
from versile.common.iface import abstract, VInterface

__all__ = ['VBitfield', 'VByteBuffer', 'VCondition', 'VConfig',
           'VLinearIDProvider', 'VLockable', 'VResult', 'VResultException',
           'VNoResult', 'VCancelledResult', 'VHaveResult', 'VSimpleBus',
           'IVSimpleBusListener', 'VNamedTemporaryFile', 'VObjectIdentifier',
           'VStatus', 'VUniqueIDProvider', 'bytes_to_posint',
           'bytes_to_signedint', 'decode_pem_block', 'encode_pem_block',
           'netbytes_to_posint', 'netbytes_to_signedint', 'posint_to_bytes',
           'posint_to_netbytes', 'signedint_to_bytes', 'signedint_to_netbytes']
__all__ = _vexport(__all__)


class VByteBuffer(object):
    """Holds a FIFO buffer of bytes data.

    :param data: data to place in buffer
    :type  data: bytes

    The class aims to improve performance by holding a list of
    buffered bytes objects until they have been fully read, and
    minimizing byte object join operations, performing only when
    needed.

    Atomic operation methods are thread-safe.

    .. automethod:: __len__

    """

    def __init__(self, data=None):
        self._chunks = deque()
        self._length = 0
        self._start = 0
        self.__lock = threading.Lock()
        if data:
            self.append(data)

    def append(self, chunk):
        """Appends bytes data to the end of the buffer.

        :param chunk: data to append to buffer
        :type  chunk: bytes

        """
        self.__lock.acquire()
        try:
            self._chunks.append(chunk)
            self._length += len(chunk)
        finally:
            self.__lock.release()

    def append_list(self, chunks):
        """Appends block(s) of bytes data to the end of the buffer.

        :param chunks: data to append to buffer
        :type  chunks: tuple(bytes)

        """
        self.__lock.acquire()
        try:
            for chunk in chunks:
                self._chunks.append(chunk)
                self._length += len(chunk)
        finally:
            self.__lock.release()

    def pop_list(self, num_bytes=-1):
        """Pops a list of byte chunks from the start of the buffer.

        :param num_bytes: number of bytes to pop
        :type  num_bytes: int
        :returns:         list of byte chunks
        :rtype:           list<bytes>

        If *num_bytes* <0 then all data in the buffer is returned. If
        fewer than *num_bytes* are available, then all available bytes
        in the buffer are returned.

        """
        self.__lock.acquire()
        try:
            result = []
            start = self._start
            length = self._length
            if num_bytes < 0:
                num_bytes = length
            bytes_left = num_bytes
            while self._chunks and bytes_left:
                current = self._chunks[0]
                current_len = len(current)
                current_left = current_len - start
                bytes_to_read = min(current_left, bytes_left)
                if start == 0:
                    if bytes_to_read == current_left:
                        result.append(current)
                        self._chunks.popleft()
                        start = 0
                        length -= bytes_to_read
                    else:
                        result.append(current[:bytes_to_read])
                        start += bytes_to_read
                        length -= bytes_to_read
                else:
                    if bytes_to_read == current_left:
                        result.append(current[start:])
                        self._chunks.popleft()
                        start = 0
                        length -= bytes_to_read
                    else:
                        end_pos = start + bytes_to_read
                        result.append(current[start:end_pos])
                        start += bytes_to_read
                        length -= bytes_to_read
                bytes_left -= bytes_to_read
            self._start = start
            self._length = length
        finally:
            self.__lock.release()
        return result

    def pop(self, num_bytes=-1):
        """Pops data from the start of the buffer.

        :param num_bytes: number of bytes to pop
        :type  num_bytes: int
        :returns:         popped data
        :rtype:           bytes

        If *num_bytes* <0 then all data in the buffer is returned. If
        fewer than *num_bytes* are available, then all available bytes
        in the buffer are returned.

        """
        return b''.join(self.pop_list(num_bytes))

    def peek_list(self, num_bytes=-1):
        """Retreives data from the start of the buffer without popping.

        Similar to :meth:`pop_list`\ , but leaves returned data in the
        buffer.

        """
        self.__lock.acquire()
        try:
            result = []
            if self._length > 0:
                start = self._start
                if num_bytes < 0:
                    num_bytes = self._length
                bytes_left = num_bytes
                chunk_it = iter(self._chunks)
                current = next(chunk_it)
                while bytes_left:
                    current_len = len(current)
                    current_left = current_len - start
                    bytes_to_read = min(current_left, bytes_left)
                    if start == 0:
                        if bytes_to_read == current_left:
                            result.append(current)
                            start = 0
                            bytes_left -= bytes_to_read
                            try:
                                current = next(chunk_it)
                            except StopIteration:
                                break
                        else:
                            result.append(current[:bytes_to_read])
                            start += bytes_to_read
                            bytes_left -= bytes_to_read
                            break
                    else:
                        if bytes_to_read == current_left:
                            result.append(current[start:])
                            start = 0
                            bytes_left -= bytes_to_read
                            try:
                                current = next(chunk_it)
                            except StopIteration:
                                break
                        else:
                            end_pos = start + bytes_to_read
                            result.append(current[start:end_pos])
                            start += bytes_to_read
                            bytes_left -= bytes_to_read
                            break
        finally:
            self.__lock.release()
        return result

    def peek(self, num_bytes=-1):
        """Retreives data from the buffer without popping.

        Similar to :meth:`pop`\ , but leaves returned data in the buffer.

        """
        return b''.join(self.peek_list(num_bytes))

    def remove(self, num_bytes=-1):
        """Removes data from the start of the buffer.

        :param num_bytes: number of bytes to remove
        :type  num_bytes: int
        :returns:         number of bytes removed
        :rtype:           int

        If *num_bytes* <0 or fewer than *num_bytes* are available then
        all data in the buffer is removed.

        """
        self.__lock.acquire()
        try:
            start = self._start
            length = self._length
            if num_bytes < 0:
                num_bytes = length
            bytes_left = num_bytes
            while self._chunks and bytes_left:
                current = self._chunks[0]
                current_len = len(current)
                current_left = current_len - start
                bytes_to_remove = min(current_left, bytes_left)
                if start == 0:
                    if bytes_to_remove == current_left:
                        self._chunks.popleft()
                        start = 0
                        length -= bytes_to_remove
                    else:
                        start += bytes_to_remove
                        length -= bytes_to_remove
                else:
                    if bytes_to_remove == current_left:
                        self._chunks.popleft()
                        start = 0
                        length -= bytes_to_remove
                    else:
                        end_pos = start + bytes_to_remove
                        start += bytes_to_remove
                        length -= bytes_to_remove
                bytes_left -= bytes_to_remove
            self._start = start
            num_removed = self._length - length
            self._length = length
        finally:
            self.__lock.release()
        return num_removed

    def clear(self):
        """Clears the buffer."""
        self.__lock.acquire()
        try:
            self._chunks.clear()
            self._length = 0
            self._start = 0
        finally:
            self.__lock.release()

    def __len__(self):
        """Overloads the len() operator to return number of bytes in buffer."""
        # This seems to be required for 64-bit systems
        length = self._length
        if isinstance(length, long):
            length = int(length)
        return length

@abstract
class VUniqueIDProvider(object):
    """Base class for generators of unique integer ids.

    .. automethod:: __call__

    """

    def __init__(self):
        self._lock = threading.Lock()

    def __call__(self):
        """See :meth:`get_id`"""
        return self.get_id()

    @abstract
    def get_id(self):
        """Generates the next unique id.

        :returns: next ID generated by the provider
        :rtype:   int, long

        This is a thread safe operation, each call must be guaranteed
        to return a unique id.

        """
        raise NotImplementedError()

    @abstract
    def peek_id(self):
        """Peeks at the next id which will be generated.

        :returns: estimated next ID
        :rtype:   int, long

        Note that due to concurrency, if multiple threads are using
        the provider then peek_id may not provide the same result as a
        follow-on call to :meth:`get_id`\ , if another thread
        generated an ID between those two calls.

        """
        raise NotImplementedError()


class VLinearIDProvider(VUniqueIDProvider):
    """Generator for a linear series of unique ids, starting with 1.

    Each new generated ID equals the previously generated ID plus one.

    """
    def __init__(self):
        super(VLinearIDProvider, self).__init__()
        self._next_id = 1

    def get_id(self):
        self._lock.acquire()
        try:
            unique_id = self._next_id
            self._next_id = unique_id + 1
        finally:
            self._lock.release()
        return unique_id

    def peek_id(self):
        return self._next_id


class VCondition(object):
    """A :class:`threading.Condition` which supports callbacks.

    :param lock:     a lock to register on (or create a new lock if None)
    :type  lock:     :class:`threading.RLock`
    :param callback: a list of callback functions (or ignore if None)
    :type  callback: list(function)

    Callback functions should take no arguments, so they can be
    invoked as 'function()' when performing a callback.

    """

    def __init__(self, lock=None, callback=None):
        if lock:
            self.__cond = threading.Condition(lock)
        else:
            self.__cond = threading.Condition()
        if callback:
            self.__callback = set(callback)
        else:
            self.__callback = set()
        self.__callback_lock = threading.RLock()

    def __enter__(self):
        self.acquire()

    def __exit__(self, type, value, traceback):
        self.release()

    def acquire(self, *args, **kargs):
        """Same as :meth:`threading.Condition.acquire`\ ."""
        return self.__cond.acquire(*args, **kargs)

    def add_callback(self, callback):
        """Adds a callback for notifyAll.

        :param callback: a function that can be called without arguments
        :type  callback: callable

        """
        self.__callback_lock.acquire()
        try:
            self.__callback.add(callback)
        finally:
            self.__callback_lock.release()

    def notify(self, *args, **kargs):
        """Same as :meth:`threading.Condition.notify`\ ."""
        return self.__cond.notify(*args, **kargs)

    def notifyAll(self):
        """Performs callbacks in addition to a regular notifyAll.

        Invokes callback() on all registered callback functions after
        performing notifyAll on the underlying Condition object.

        """
        result = self.__cond.notifyAll()
        if self.__callback:
            self.__callback_lock.acquire()
            try:
                for callback in self.__callback:
                    callback()
            finally:
                self.__callback_lock.release()
        return result

    def notify_all(self):
        """See :meth:`notifyAll`\ ."""
        return self.notifyAll()

    def quick_notify_all(self):
        """Acquires lock, performs :meth:`notifyAll`, and releases the lock."""
        self.__cond.acquire()
        try:
            self.notifyAll()
        finally:
            self.__cond.release()

    def remove_callback(self, callback):
        """Removes a notification callback.

        :param callback: a function that can be called without arguments
        :type callback:  callable

        If *callback* is not currently not registered, the function will
        silently return without raising any exception.

        """
        self.__callback_lock.acquire()
        try:
            self.__callback.discard(callback)
        finally:
            self.__callback_lock.release()

    def release(self):
        """Same as :meth:`threading.Condition.release`\ ."""
        return self.__cond.release()

    def wait(self, *args, **kargs):
        """Same as :meth:`threading.Condition.wait`\ ."""
        return self.__cond.wait(*args, **kargs)


class VStatus(VCondition):
    """Holds a state/status and enables notification of state changes.

    :param status:   initial status
    :param callback: callback function to register for status notifications
    :type  callback: callable

    .. warning::

        Should not be directly instantiated, instead use
        :meth:`class_with_states` as an object factory.

    .. automethod: __call__

    """

    @classmethod
    def class_with_states(cls, *states):
        """Generates a derived class with given states as class attributes.

        :param states: string for each state to register on the class
        :type  states: iterable
        :returns:      class with *states* as class attributes

        """
        class VStatusWithStates(cls):
            def __init__(self, status, callback=None):
                super(VStatusWithStates, self).__init__(status, callback)
            @classmethod
            def _validate_status(cls, status):
                return (isinstance(status, int)
                        and 0 <= status < cls._num_states)
        VStatusWithStates._num_states = len(states)
        for i in xrange(len(states)):
            if hasattr(VStatusWithStates, states[i]):
                raise ValueError('Illegal state name', state[i])
            setattr(VStatusWithStates, states[i], i)
        return VStatusWithStates

    def __init__(self, status, callback=None):
        super(VStatus, self).__init__(callback=callback)
        if not self._validate_status(status):
            raise TypeError('Invalid state')
        self._status = status

    def __call__(self):
        """Returns :attr:`status`\ ."""
        return self._status

    @property
    def status(self):
        """The current status set on the object."""
        return self._status

    def update(self, new_status, notify=True):
        """Updates the status set on the object.

        :param new_status: new status to set
        :param notify:     if True then send notification
        :type  notify:     bool

        If *notify* is True, the method will lock and notify using the
        parent class' condition functionality.

        """
        if notify:
            self.acquire()
        try:
            if not self._validate_status(new_status):
                raise TypeError('Invalid state')
            old_status = self._status
            self._status = new_status
            if notify and old_status != new_status:
                self.notify_all()
        finally:
            if notify:
                self.release()

    def wait_status(self, is_status=None, not_status=None, timeout=None,
                    hook=None):
        """Wait for the given status and return True if condition met.

        :param is_status:  a status, or a list/tuple of states
        :param not_status: a status, or a list/tuple of states
        :param timeout:    timeout in seconds, or None
        :param hook:       function called when checks are made (or None)
        :type  hook:       function f()
        :returns:          True if condition was met (within timeout)
        :rtype:            bool

        Returns true when (status in is_status) or (status not in not_status)

        """
        if is_status is None and not_status is None:
            raise ValueError('is_status and not_status cannot both be None')
        if (is_status is not None
            and not isinstance(is_status, (tuple, list))):
            is_status = (is_status,)
        if (not_status is not None
            and not isinstance(not_status, (tuple, list))):
            not_status = (not_status,)
        wait_time = timeout
        if timeout is not None and timeout > 0.0:
            wtime = 0.0
            start = time.time()
        self.acquire()
        try:
            while True:
                if hook:
                    hook()
                if is_status is not None and self._status in is_status:
                    return True
                if not_status is not None and self._status not in not_status:
                    return True
                self.wait(wait_time)
                if timeout is not None and timeout > 0.0:
                    new_time = time.time()
                    wtime += new_time - start
                    start = new_time
                    wait_time = timeout - wtime
                    if wait_time <= 0.0:
                        return False
        finally:
            self.release()

    @classmethod
    def _validate_status(cls, status):
        """Return True if 'status' is a valid state."""
        return True


class VLockable(object):
    """Base class for objects which implement object synchronization.

    Holds an internal :class:`threading.RLock` which performs
    locking. Overrides :meth:`__enter__` and :meth:`__exit__` so the
    object can be used in 'with' statements.

    """
    def __init__(self, *args, **kargs):
        """Sets up the lock.

        args, kargs arguments are passed to :class:`threading.RLock`
        constructor.

        """
        self.__lock = threading.RLock(*args, **kargs)

    def __enter__(self):
        self.__lock.acquire()

    def __exit__(self, type, value, traceback):
        self.__lock.release()


class VResultException(Exception):
    """Base class for VResult related exceptions"""


class VNoResult(VResultException):
    """Result of an asynchronous operation is not yet available."""


class VCancelledResult(VResultException):
    """Asynchronous operation was cancelled."""


class VHaveResult(VResultException):
    """Asynchronous operation result was already provided."""


class VResult(VCondition):
    """A result of an operation which may be asynchronous.

    .. automethod:: _post_push_cleanup
    .. automethod:: _cancel

    """

    def __init__(self):
        super(VResult, self).__init__()
        self._has_result = False
        self._cancelled = False
        self._pushed_cancelled = False
        self._is_exception = None
        self._result = None
        self._callbacks = deque()
        self._failbacks = deque()

    def has_result(self):
        """Returns True if the remote call result is ready.

        :returns: call completion status
        :rtype:   bool

        """
        return self._has_result

    def wait(self, timeout=None):
        """Waits up to a set timeout until a result is ready.

        :param timeout: timeout in seconds, or None
        :type  timeout: float
        :raises:        :exc:`VNoResult`

        Waits up to *timeout* seconds. Raises :exc:`VNoResult` if
        *timeout* expired before a result was available.

        """
        if self._has_result:
            return
        if timeout:
            start_time = time.time()
        with self:
            while True:
                if timeout is not None and timeout > 0.0:
                    current_time = time.time()
                    if current_time > start_time + timeout:
                        raise VNoResult()
                    wait_time = start_time + timeout - current_time
                    super(VResult, self).wait(wait_time)
                else:
                    super(VResult, self).wait()
                if self._has_result:
                    break

    def result(self, timeout=None):
        """Returns the call result.

        :param timeout: seconds to wait for a result, or None
        :type  timeout: float
        :returns:       call result
        :raises:        :exc:`VNoResult`, :exc:`Exception`

        Waits up to *timeout* seconds until a result is ready. If the
        call triggered an exception then this method will raise the
        passed exception instead of returning a call return value.

        Raises :exc:`VNoResult` if *timeout* expired before a result
        was ready.

        """
        self.wait(timeout)
        if not self._is_exception:
            return self._result
        else:
            raise self._result

    def cancel(self):
        """Cancels a pending operation.

        If a result has already been provided, this method has no
        effect. Otherwise, the following operations are performed
        (only the first time :meth:`cancel` is called):

        * internal status is set to 'cancelled'
        * :meth:`_cancel` is called
        * call result is set to a :exc:`VCancelledResult` exception

        Depending on the particular implementation of :meth:`_cancel`\
        , this method may or may not cause the actual processing which
        produces the result to be cancelled.

        """
        with self:
            push_cancel = False
            if not self._cancelled:
                push_cancel = True
                self._cancelled = True
                self._cancel()
        if push_cancel:
            self.silent_push_exception(VCancelledResult())

    def add_callpair(self, callback, failback, processor=None):
        """Adds a callback and a failback function for a call result.

        Similar to calling :meth:`add_callback` and
        :meth:`add_failback` as follows:

        add_callback(callback, processor)
        add_failback(failback, processor)

        .. note::

            One key difference from otherwise making the two above
            calls in sequence is is both additions will be resolved
            while a lock is held on the object. This can avoid some
            possible race conditions

        """
        with self:
            if self._has_result:
                if not self._is_exception:
                    self.add_callback(callback, processor=processor)
                else:
                    self.add_failback(failback, processor=processor)
            else:
                self._callbacks.append((self, callback, processor))
                self._failbacks.append((self, failback, processor))


    def add_callback(self, callback, processor=None):
        """Adds a callback function for a call result.

        :param callback:  the callback to be called
        :type  callback:  callable
        :param processor: processor to execute callback
        :type  processor: :class:`versile.common.processor.VProcessor`

        When a non-exception result is ready, callback(result) is
        called on the callback. If processor is set then the callback
        is put on the processor queue for execution - otherwise it is
        executed when the result is available (which is likely
        performed by the reactor thread so it should be a quickly
        executing and non-blocking callback). If result was already
        provided, the callback is immediately resolved.

        """
        execute_now = False
        with self:
            if self._has_result:
                if not self._is_exception:
                    if processor is None:
                        execute_now = True
                        execute_arg = self._result
                    else:
                        processor.queue_call(callback, [self._result])
            else:
                # Including self in order to make sure a reference is held
                # until a result is ready
                self._callbacks.append((self, callback, processor))

        # Outside 'with' clause to avoid locking during callback execution
        if execute_now:
            try:
                callback(execute_arg)
            except Exception as e:
                _v_silent(e)

    def add_failback(self, failback, processor=None):
        """Adds a callback function for a call result.

        :param failback:  the callback to be called
        :type  failback:  callable
        :param processor: processor to execute failback
        :type  processor: :class:`versile.common.processor.VProcessor`

        When an exception result is ready, failback(result) is called
        on the failback. If processor is set then the failback is put
        on the processor queue for execution - otherwise it is
        executed when the result is available (which is likely
        performed by the reactor thread so it should be a quickly
        executing and non-blocking failback). If an exception was
        already provided, the callback is immediately resolved.

        """
        execute_now = False
        with self:
            if self._has_result:
                if self._is_exception:
                    if processor is None:
                        execute_now = True
                        execute_arg = self._result
                    else:
                        processor.queue_call(failback, [self._result])
            else:
                # Including self in order to make sure a reference is held
                # until a result is ready
                self._failbacks.append((self, failback, processor))

        # Outside 'with' clause to avoid locking during callback execution
        if execute_now:
            try:
                failback(execute_arg)
            except Exception as e:
                _v_silent(e)


    def push_result(self, result):
        """Used by a result provider to push a call result when ready.

        :param result: the result of the call
        :raises:       :exc:`VHaveResult`, :exc:`VCancelledResult`

        Raises an exception if a result was already provided, or if the
        operation was already cancelled.

        """
        with self:
            if self._cancelled:
                raise VCancelledResult()
        self.__push_call_result(result, is_exception=False)

    def push_exception(self, exception):
        """Used by a result provider to push a call exception when ready.

        :param exception: exception raised by the call
        :type  exception: :exc:`Exception`
        :raises:          :exc:`VHaveResult`, :exc:`VCancelledResult`

        Raises an exception if a result was already provided, or if the
        operation was already cancelled.

        """
        with self:
            if self._cancelled:
                if (not isinstance(exception, VCancelledResult)
                    or self._pushed_cancelled):
                    raise VCancelledResult()
                self._pushed_cancelled = True
        self.__push_call_result(exception, is_exception=True)

    def silent_push_result(self, result):
        """Used by a result provider to push a call result when ready.

        :param result: the result of the call

        Similar to :meth:`push_result`\ , but silently discards any
        exception raised by that method. Useful for producing cleaner
        and more readable code when the caller intends to ignore those
        exceptions.

        """
        try:
            self.push_result(result)
        except VHaveResult:
            pass
        except VCancelledResult:
            pass

    def silent_push_exception(self, exception):
        """Used by a result provider to push a call exception when ready.

        :param exception: exception raised by the call
        :type  exception: :exc:`Exception`

        Similar to :meth:`push_exception`\ , but silently discards any
        exception raised by that method. Useful for producing cleaner
        and more readable code when the caller intends to ignore those
        exceptions.

        """
        try:
            self.push_exception(exception)
        except VHaveResult:
            pass
        except VCancelledResult:
            pass

    @property
    def cancelled(self):
        """True if operation was cancelled."""
        with self:
            return self._cancelled

    def _cancel(self):
        """Called internally by :meth:`cancel`\ . Default does nothing."""
        pass

    def _post_push_cleanup(self):
        """Called internally after a result was pushed, before callbacks.

        Default does nothing. Derived classes can override to add cleanup
        handling.

        """
        pass

    def __push_call_result(self, result, is_exception):
        """Used by a link to push a result when ready."""
        with self:
            if self._has_result:
                raise VHaveResult()
            self._result = result
            self._is_exception = is_exception
            self._has_result = True
            self._post_push_cleanup()
            self.notify_all()

            # Process callbacks or failbacks processing
            if not is_exception:
                callbacks, self._callbacks = self._callbacks, deque()
                self._failbacks.clear()
            else:
                callbacks, self._failbacks = self._failbacks, deque()
                self._callbacks.clear()

        # Outside 'with' clause to avoid locking during callback execution
        while callbacks:
            call, callback, processor = callbacks.popleft()
            if not processor:
                try:
                    callback(self._result)
                except Exception as e:
                    _v_silent(e)
            else:
                processor.queue_call(callback, [self._result])


class VSimpleBus(VLockable):
    """Simple bus for passing objects to a set of registered listeners."""

    def __init__(self):
        super(VSimpleBus, self).__init__()
        self._listeners = dict()              # listener_id -> listener
        self._l_id_gen = VLinearIDProvider()

    def register(self, listener):
        """Registers a listener for receiving message bus objects.

        :param listener: listener for message bus objects
        :type  listener: :class:`IVSimpleBusListener`
        :returns:        listener ID for the listener

        Added listeners are tracked only with weak references. It is
        the responsibility of the caller to retain a reference until
        the listener can be unregistered.

        """
        with self:
            _id = self._l_id_gen.get_id()
            self._listeners[_id] = weakref.ref(listener)
            return _id

    def unregister_id(self, listener_id):
        """Unregisters a listener from the bus.

        :param listener_id: the bus' ID for the listener
        :type  listener_id: int

        """
        with self:
            self._listeners.pop(listener_id, None)

    def unregister_obj(self, listener):
        """Unregisters a listener from the bus.

        :param listener: listener object registered with the bus

        In order for unregister to successfully unregister the correct
        listener, the provided listener must satisfy an 'is'
        relationship with the previously registered listener.

        """
        with self:
            _ids = set()
            for key, val in self._listeners.items():
                _listener = val()
                if _listener is None or _listener is listener:
                    _ids.add(key)
            for _id in _ids:
                self._listeners.pop(_id, None)

    def push(self, obj):
        """Pushes an object to all bus listeners.

        :param obj: obj to push

        If any listener throws an exception when the object is pushed
        to the listener, the listener is unregistered.

        .. note::

            It is important to know that an object push is resolved
            immediately within the context of this method, and so the
            target listeners must take care not to perform any action
            which could perform a dead-lock with the code which
            triggered sending the object.

        """
        with self:
            _discard_ids = set()
            for _id, _w_listener in self._listeners.items():
                _listener = _w_listener()
                if _listener is None:
                    _discard_ids.add(_id)
                else:
                    try:
                        _listener.bus_push(obj)
                    except:
                        _discard_ids.add(_id)
            for _id in _discard_ids:
                self._listeners.pop(_id, None)


class IVSimpleBusListener(VInterface):
    """Interface for :class:`VSimpleBus` listeners."""

    def bus_push(self, obj):
        """Receive an object from a bus the listener is registered with.

        :param object: object received from a bus

        .. note::

            Implementations of this method must take care not to trigger any
            deadlock with the code that pushed the object onto the bus.

        """


class VObjectIdentifier(object):
    """Represents an :term:`Object Identifier`\ .

    :param oid: object identifier
    :type  oid: int,

    """

    def __init__(self, *oid):
        if len(oid) == 1 and isinstance(oid, (tuple, list)):
            self._oid = tuple(oid[0])
        else:
            self._oid = oid

    @property
    def oid(self):
        """Object identifier data as a tuple(int)."""
        return self._oid

    def __cmp__(self, other):
        if not isinstance(other, VObjectIdentifier):
            raise TypeError()
        return cmp(self.oid, other.oid)

    def __str__(self):
        if _pyver == 2:
            return _b2s(b'.'.join([_s2b(str(e)) for e in self._oid]))
        else:
            return '.'.join([str(e) for e in self._oid])

    def __repr__(self):
        if _pyver == 2:
            return _b2s(b'\'' + _s2b(str(self)) + b'\'')
        else:
            return '\'' + str(self) + '\''

    def __hash__(self):
        return hash(self._oid)

    def __eq__(self, other):
        return isinstance(other, VObjectIdentifier) and other.oid == self.oid


class VBitfield(object):
    """Represents a bit field.

    :param bits: tuple of (0, 1) bits
    :type  bits: int,

    Represented internally as a tuple of (0, 1) values. The first bit
    is the most siginficant bit, e.g. (1, 0, 0) represents the value
    0x04.

    The class overloads :meth:`__and__`\ , :meth:`__or__` and
    :meth:`truth`, allowing bitwise AND/OR on the object with another
    :class:`VBitfield` and allowing a truth check whether any bits are
    set.

    .. automethod:: __or__
    .. automethod:: __and__

    """

    def __init__(self, bits):
        if not isinstance(bits, (tuple)):
            raise TypeError('Value must be a tuple')
        for item in bits:
            if not isinstance(item, int) or item not in (0, 1):
                raise TypeError('Elements must be 0 or 1')
        self.__bits = bits

    def as_octets(self):
        """Returns the value as octets representation.

        :returns: octets representation of bitfield
        :rtype:   bytes

        """
        num_bytes = len(self.bits) / 8
        if len(self.bits) % 8:
            num_bytes += 1
        bits = str(self)
        as_num = int(bits, 2)
        result = posint_to_bytes(as_num)
        padding = num_bytes - len(result)
        if padding:
            result = padding*b'\x00' + result
        return result

    @classmethod
    def from_octets(cls, data):
        """Creates a bitfield from byte data.

        :param data: octet data for constructing the bitfield
        :type  data: bytes
        :returns:    resulting bitfield
        :rtype:      :class:`VBitfield`

        Octets should be ordered from most significant to least
        significant byte. The produced bitfield includes a full
        representation of octet data including any leading zero-bits.

        """
        num_bits = len(data)*8
        data = bytes_to_posint(data)
        bits = bin(data) # NEW - old is: bits = _s2b(bin(data))
        bits = bits[2:]
        bits = tuple([int(e) for e in bits])
        padding = num_bits - len(bits)
        if padding:
            bits = padding*(0,) + bits
        return cls(bits)

    @property
    def bits(self):
        """Value as a tuple of bits (first bit is most significant bit)."""
        return self.__bits

    def __or__(self, other):
        """Performs bitwise OR with *other*.

        :param other: other bitfield
        :type  other: :class:`VBitfield`

        The result has the same bitfield length as the maximum
        bitfield length of the two ORed objects. Zero-bits are
        left-padded to the shortest bitfield.

        """
        if not isinstance(other, VBitfield):
            raise TypeError('Can only do bitwise or with VBitfield')
        bits_a = self.bits
        bits_b = other.bits
        min_len= min(len(bits_a), len(bits_b))
        max_len = max(len(bits_a), len(bits_b))
        diff = max_len - min_len
        if len(bits_a) < max_len:
            bits_a = diff*(0,) + bits_a
        else:
            bits_b = diff*(0,) + bits_b
        result_bits = tuple(a | b for a, b in zip(bits_a, bits_b))
        return VBitfield(result_bits)

    def __and__(self, other):
        """Performs bitwise AND with *other*.

        :param other: other bitfield
        :type  other: :class:`VBitfield`

        The result has the same bitfield length as the maximum
        bitfield length of the two ANDed objects. Zero-bits are
        left-padded to the shortest bitfield.

        """
        if not isinstance(other, VBitfield):
            raise TypeError('Can only do bitwise or with VBitfield')
        bits_a = self.bits
        bits_b = other.bits
        min_len= min(len(bits_a), len(bits_b))
        max_len = max(len(bits_a), len(bits_b))
        diff = max_len - min_len
        if len(bits_a) < max_len:
            bits_a = diff*(0,) + bits_a
        else:
            bits_b = diff*(0,) + bits_b
        result_bits = tuple(a & b for a, b in zip(bits_a, bits_b))
        return VBitfield(result_bits)

    def truth(self):
        """Truth value of bitfield.

        :returns: True if one or more bits are set
        :rtype:   bool

        """
        return bool(max(self.bits))

    def __str__(self):
        return ''.join([str(e) for e in self.__bits])

    def __repr__(self):
        return '\'%s\'' % str(self)

    def __hash__(self):
        return hash(self.bits)

    def __eq__(self, other):
        return isinstance(other, VBitfield) and other.bits == self.bits


class VConfig(dict):
    """Configuration settings.

    :param kargs: key-value pairs to be set

    Instances of this class can hold configuration settings, which can
    be used e.g. as an input for constructors. This can help reducing
    the complexity of __init__ argument lists.

    """

    def __init__(self, **kargs):
        super(VConfig, self).__init__()
        super(VConfig, self).__setattr__('_cblock', threading.RLock())
        super(VConfig, self).__setattr__('_callback', dict())
        for key, value in kargs.items():
            self[key] = value

    def copy(self, deep=True):
        """Creates a copy of the configuration object.

        :param deep: if True make a deep copy of any held :class:`VConfig`
        :param deep: bool
        :returns:    copied configuration
        :rtype:      :class:`VConfig`

        This method is useful e.g. for creating a copy of a
        configuration settings template.

        The return type should be the same as the object. The method
        relies on being able to instantiate the class by passing a set
        of keywords. Derived classes with different __init__ argument
        format will not work reliably with this method.

        """
        if not deep:
            d = self
        else:
            d = dict()
            for key, val in self.items():
                if isinstance(val, VConfig):
                    d[key] = val.copy(deep=True)
                else:
                    d[key] = val
        return self.__class__(**d)

    def add_callback(self, obj, method):
        """Registers a callback for configuration changes.

        :param obj:    object to receive callback
        :param method: method name to call on object
        :type  method: unicode
        :raises:       :exc:`AttributeError`

        Performs ``getattr(obj, method)(name, new_value)`` when
        a configuration value is set or modified.

        The class will only hold a weak reference to *obj*\ .

        .. warning::

            Callback(s) are performed within the context of the thread
            that set or modified a parameter. When registering a
            callback, the registering code is responsible for avoiding
            deadlock situation and if necessary passing the callback via
            some mechanism that provides thread separation.

        Raises an exception if getattr(obj, method) does not resolve at
        the time this method is invoked.

        Any exceptions when performing a callback is silently ignored.

        """
        # This tests whether obj.method (currently) resolves
        _tmp = getattr(obj, method)

        with self._cblock:
            dead = set()
            for wref in self._callback:
                o = wref()
                if not o:
                    dead.add(wref)
                elif o is obj:
                    break
            else:
                self._callback[weakref.ref(obj)] = method
            for d in dead:
                self._callback.pop(d, None)

    def remove_callback(self, obj):
        """Removes the object from the list of callback receivers.

        :param obj: object to no longer receive callback

        """
        with self._cblock:
            dead = set()
            for wref in self._callback:
                o = wref()
                if not o or o is obj:
                    dead.add(wref)
            for d in dead:
                self._callback.pop(d, None)

    def __callback(self, name, value):
        with self._cblock:
            dead = set()
            for wref, method in self._callback.items():
                o = wref()
                if not o:
                    dead.add(wref)
                else:
                    try:
                        getattr(o, method)(name, value)
                    except Exception as e:
                        _v_silent(e)
            for d in dead:
                self._callback.pop(d, None)

    def __getattr__(self, name):
        try:
            return self[name]
        except:
            raise AttributeError()

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        self.pop(name)

    def __setitem__(self, name, value):
        # Overloaded so we can trigger callback mechanisms
        super(VConfig, self).__setitem__(name, value)
        self.__callback(name, value)

    def __delitem__(self, name):
        # Overloaded so could trigger a callback mechanism
        super(VConfig, self).__delitem__(name)


class VNamedTemporaryFile(object):
    """Creates a temporary named file-like object.

    :param suffix:   argument passed to :func:`tempfile.mkstemp`
    :param prefix:   argument passed to :func:`tempfile.mkstemp`
    :param dir:      argument passed to :func:`tempfile.mkstemp`
    :param delete:   if True then delete file when object is garbage collection
    :type  delete:   bool
    :param secdel:   if True then overwrite file before deleting
    :type  secdel:   bool

    If *delete* is set then the file is closed and deleted when this
    object is garbage collected. If *delete* and *secdel* are True
    then the file is overwritten with random data from
    :func:`os.urandom` before the file is deleted.

    .. warning::

        Setting *delete* and *secdel* provides a mechanism for secure
        deletion of temporary files, however as this runs during garbage
        collection there is no guarantee deletion is ever run.

    """
    def __init__(self, suffix='', prefix='tmp', dir=None, delete=True,
                 secdel=False):
        self._delete = delete
        self._secdel = secdel

        fd, fname = tempfile.mkstemp(suffix, prefix, dir)
        self._file = open(fname, 'r+b')
        os.close(fd)

    def __del__(self):
        self.close()
        if self._secdel:
            sf = open(self._file.name, 'r+b')
            sf.seek(0, 2)
            num_write = sf.tell()
            sf.seek(0)
            while num_write > 0:
                # HARDCODED - write data in chunks of 1024 bytes, this
                # will normally write more bytes than is held in file -
                # this is deliberate as it helps obfuscateinformation
                # about file length
                sf.write(os.urandom(1024))
                num_write -= min(num_write, 1024)
            sf.close()
        if self._delete:
            os.remove(self._file.name)

    def close(self, *args, **kargs):
        return self._file.close(*args, **kargs)

    def closed(self, *args, **kargs):
        return self._file.closed(*args, **kargs)

    def fileno(self, *args, **kargs):
        return self._file.fileno(*args, **kargs)

    def flush(self, *args, **kargs):
        return self._file.flush(*args, **kargs)

    def isatty(self, *args, **kargs):
        return self._file.isatty(*args, **kargs)

    def readable(self, *args, **kargs):
        return self._file.readable(*args, **kargs)

    def readline(self, *args, **kargs):
        return self._file.readline(*args, **kargs)

    def readlines(self, *args, **kargs):
        return self._file.readlines(*args, **kargs)

    def seek(self, *args, **kargs):
        return self._file.seek(*args, **kargs)

    def seekable(self, *args, **kargs):
        return self._file.seekable(*args, **kargs)

    def tell(self, *args, **kargs):
        return self._file.tell(*args, **kargs)

    def truncate(self, *args, **kargs):
        return self._file.truncate(*args, **kargs)

    def writable(self, *args, **kargs):
        return self._file.writable(*args, **kargs)

    def writelines(self, *args, **kargs):
        return self._file.writelines(*args, **kargs)

    def peek(self, *args, **kargs):
        return self._file.peek(*args, **kargs)

    def read(self, *args, **kargs):
        return self._file.read(*args, **kargs)

    def read1(self, *args, **kargs):
        return self._file.read1(*args, **kargs)

    def write(self, *args, **kargs):
        return self._file.write(*args, **kargs)

    @property
    def name(self):
        return self._file.name

    def __iter__(self):
        return iter(self._file)



def posint_to_bytes(number):
    """Converts a non-negative integer to a byte representation.

    :param number: non-negative integer
    :type  number: int, long
    :returns:      a byte array representation
    :rtype:        bytes

    The byte array representation is the integer's standard binary
    representation with zero-padding of most significant bits, with
    the first byte as the most significant byte.

    """
    if number < 0:
        raise TypeError('Number must be a non-negative integer')

    hex_str = hex(number)
    hex_str_len = len(hex_str)
    if hex_str[-1] == 'L':
        hex_str_len -= 1
    offset = hex_str_len % 2
    num_bytes = (hex_str_len // 2) + offset - 1

    data = []
    if _pyver == 2:
        if offset:
            data.append(_s2b(_b_chr(int(hex_str[2], 16))))
        for i in xrange(num_bytes - offset):
            pos = 2 + 2*i + offset
            data.append(_s2b(_b_chr(int(hex_str[pos:(pos+2)], 16))))
        return b''.join(data)
    else:
        if offset:
            data.append(int(hex_str[2], 16))
        for i in xrange(num_bytes - offset):
            pos = 2 + 2*i + offset
            data.append(int(hex_str[pos:(pos+2)], 16))
        return bytes(data)

def posint_to_netbytes(number):
    """Converts a non-negative integer to a :term:`VP` byte representation.

    :param number: non-negative integer
    :type  number: int, long
    :returns:      netbyte representation
    :rtype:        bytes

    Encodes to bytes using the standard format specified in :term:`VP`
    specifications.

    """
    if not isinstance(number, (int, long)) or number < 0:
        raise TypeError('Number must be a non-negative integer')

    if number <= 246:
        if _pyver == 2:
            return _s2b(_b_chr(number))
        else:
            return bytes((number,))

    encoding = []
    number -= 247
    data = posint_to_bytes(number)
    len_data = len(data)
    if len_data <= 8:
        if _pyver == 2:
            encoding.append(_s2b(_b_chr(246 + len_data)))
        else:
            encoding.append(bytes((246 + len_data,)))
    else:
        # Allow recursion - other resources exhausted before call stack
        encoding.append(b'\xff')
        encoding.append(posint_to_netbytes(len_data - 9))

    encoding.append(data)
    return b''.join(encoding)

def signedint_to_bytes(number):
    """Converts an integer to a byte representation.

    :param number: integer to convert
    :type  number: int, long
    :returns:      bytes

    * Encodes non-negative integers as (2*abs(number))
    * Encodes negative integers as (2*abs(number) + 1).

    """
    if not isinstance(number, (int, long)):
        raise TypeError('Number must be an integer')
    if number >= 0:
        return posint_to_bytes(2*number)
    else:
        return posint_to_bytes((-2)*number + 1)

def signedint_to_netbytes(number):
    """Converts an integer to a :term:`VP` byte representation.

    :param number: integer to convert
    :type  number: int, long
    :returns:      netbyte representation
    :rtype:        bytes

    Encodes to bytes using the standard format specified in :term:`VP`
    specifications.

    .. note::

        byte representation of 'unsigned' vs 'signed' integers are
        different; a non-negative integer must be decoded with the
        same 'unsigned' or 'signed' version that it was encoded with.

    """
    if not isinstance(number, (int, long)):
        raise TypeError('Number must be an integer')

    if number >= 0:
        return posint_to_netbytes(2*number)
    else:
        return posint_to_netbytes((-2)*number + 1)

def bytes_to_posint(data):
    """Converts non-negative integer byte representation to integer.

    :param data: the byte data to convert
    :type  data: bytes
    :returns:    converted value
    :rtype:      int, long

    Decodes the format generated by :meth:`posint_to_bytes`\ .

    """
    hex_list = [hex(_b_ord(b))[2:].zfill(2) for b in data]
    hex_string = ''.join(hex_list)
    return int(hex_string, 16)

def netbytes_to_posint(data):
    """Converts non-negative integer from a :term:`VP` bytes representation.

    :param data: netbyte data to convert
    :type  data: bytes
    :returns:    (number, bytes_read), _or_ (None, (min_bytes, max_bytes))
    :rtype:      (int/long, int/long)

    If integer could be fully decoded, returns (number, bytes_read)

    If integer could not be fulle decoded, returns (None, (min_bytes,
    max_bytes)) where min_bytes and max_bytes are the (so far) known
    constraints for the number of bytes in the integer's standard byte
    encoding (i.e. length of associated :meth:`posint_to_bytes`
    encoding). Any of these may be None if an estimate cannot be made.

    The reason for providing min_bytes/max_bytes information is it
    provides the caller an ability to detect and handle out-of-bound
    numbers without fully decoding the integer. This can be used to
    mitigate e.g. malicious encoding of netbytes representations of
    numbers which would never encode and possibly exhausting computer
    resources..

    Note that due to some effects of the netbytes encoding, the
    min_bytes and max_bytes values are the constraints for
    representing the (number - 247), so the constraints for 'number'
    may be 1 byte more.

    See :meth:`posint_to_netbytes` for information about encoding.

    """
    if not data:
        return (None, (None, None))

    first_byte = _b_ord(data[0])
    if first_byte <= 246:
        return (first_byte, 1)

    len_data = len(data)
    if first_byte < 255:
        num_bytes = first_byte - 246
        if len_data >= num_bytes + 1:
            int_data = data[1:(num_bytes+1)]
            number = bytes_to_posint(int_data) + 247
            return (number, num_bytes + 1)
        else:
            return (None, (num_bytes, num_bytes))

    num_bytes, val_info = netbytes_to_posint(data[1:])
    if num_bytes is not None:
        num_bytes += 9
        bytes_read = val_info
        if len_data >= num_bytes + bytes_read + 1:
            int_data = data[(bytes_read+1):(bytes_read+num_bytes+1)]
            number = bytes_to_posint(int_data) + 247
            return (number, 1 + bytes_read + num_bytes)
        else:
            return (None, (num_bytes, num_bytes))
    else:
        min_bytes, max_bytes = val_info
        if min_bytes is None:
            min_bytes = 9
        return (None, (min_bytes, max_bytes))

def bytes_to_signedint(data):
    """Converts signed integer byte representation to integer.

    :param data: the byte data to convert
    :type  data: bytes
    :returns:    converted value
    :rtype:      int, long

    See :meth:`signedint_to_bytes` for encoding.

    """
    unsigned = bytes_to_posint(data)
    if unsigned & 0x1:
        return -(unsigned >> 1)
    else:
        return unsigned >> 1

def netbytes_to_signedint(data):
    """Converts signed integer from network suitable byte representation.

    :param data: netbyte data to convert
    :type  data: bytes
    :returns:    (number, bytes_read), _or_ (None, (min_bytes, max_bytes))
    :rtype:      (int/long, int/long)

    See :meth:`netbytes_to_posint` for information about parameters
    and return value. See :meth:`signedint_to_netbytes` for
    information about encoding.

    """
    (unsigned, call_info) = netbytes_to_posint(data)
    if unsigned is not None:
        if unsigned & 0x1:
            return (-(unsigned >> 1), call_info)
        else:
            return (unsigned >> 1, call_info)
    else:
        return (None, call_info)


def decode_pem_block(block):
    """Decodes a :term:`PEM` formatted block with BEGIN/END delimiters.

    :param block: data block to decode
    :type  block: bytes
    :returns:     (block name, block data)
    :rtype:       (bytes, bytes)
    :raises:      :exc:`ValueError`

    """
    block = block.strip()
    l = block.splitlines()
    header, ending = l[0].strip(), l[-1].strip()
    if not header.startswith(b'-----BEGIN '):
        raise ValueError('Bad block format')
    if not ending.startswith(b'-----END '):
        raise VCryptoException('Bad block format')
    for s in header, ending:
        if not s.endswith(b'-----'):
            raise ValueError('Bad block format')
    header, ending = header[11:-5], ending[9:-5]
    if header != ending:
        raise ValueError('Block header and ending do not match')
    data = b'\n'.join(l[1:-1])
    if _pyver == 2:
        data = _s2b(base64.decodestring(_b2s(data)))
    else:
        data = base64.decodebytes(data)
    return (header, data)


def encode_pem_block(header, data):
    """Encodes a :term:`PEM` formatted block with BEGIN/END delimiters.

    :param header: header name for BEGIN/END
    :type  header: bytes
    :param data:   data to encode in block
    :type  data:   bytes
    :returns:      base64-encoded block with BEGIN/END
    :rtype:        bytes

    Below is an example of its usage and the format it generates:

    >>> from versile.common.util import *
    >>> data = b''.join(chr(e) for e in xrange(60, 70))
    >>> data
    '<=>?@ABCDE'
    >>> pem_block = encode_pem_block('CUSTOM', data)
    >>> print(pem_block) #doctest: +NORMALIZE_WHITESPACE
    -----BEGIN CUSTOM-----
    PD0+P0BBQkNERQ==
    -----END CUSTOM-----
    >>> name, rec = decode_pem_block(pem_block)
    >>> name
    'CUSTOM'
    >>> rec
    '<=>?@ABCDE'

    """
    top = b''.join((b'-----BEGIN ', header, b'-----\n'))
    if _pyver == 2:
        data = _s2b(base64.encodestring(_b2s(data)))
    else:
        data = base64.encodebytes(data)
    bottom = b''.join((b'-----END ', header, b'-----\n'))
    return b''.join((top, data, bottom))
