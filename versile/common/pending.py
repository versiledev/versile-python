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

"""Mechanisms for asynchronous call result in single-thread environment."""
from __future__ import print_function, unicode_literals

import collections
import types

from versile.internal import _vexport, _v_silent
from versile.common.failure import VFailure
from versile.common.iface import abstract

__all__ = ['VPendingException', 'VPendingAlreadyFired', 'VPendingCancelled',
           'VPendingTimeout', 'VFPendingException', 'VFPendingAlreadyFired',
           'VFPendingCancelled', 'VFPendingTimeout', 'pending',
           'VPending', 'VTimedPending', 'VPendingList']
__all__ = _vexport(__all__)


class VPendingException(Exception):
    """General VPending exception."""


class VPendingAlreadyFired(VPendingException):
    """VPending object was previously fired."""


class VPendingCancelled(VPendingException):
    """VPending object was cancelled."""


class VPendingTimeout(VPendingCancelled):
    """VPending object was cancelled due to a timeout."""


class VFPendingException(VFailure):
    """Convenience class for creating a pending exception VFailure."""
    def __init__(self, *args, **kargs):
        super_init = super(VFPendingException, self).__init__
        super_init(VPendingException(*args, **kargs))

class VFPendingAlreadyFired(VFailure):
    """Convenience class for creating an already fired VFailure."""
    def __init__(self, *args, **kargs):
        super_init = super(VFPendingAlreadyFired, self).__init__
        super_init(VPendingAlreadyFired(*args, **kargs))

class VFPendingCancelled(VFailure):
    """Convenience class for creating a pending cancelled VFailure."""
    def __init__(self, *args, **kargs):
        super_init = super(VFPendingCancelled, self).__init__
        super_init(VPendingCancelled(*args, **kargs))

class VFPendingTimeout(VFailure):
    """Convenience class for creating a timeout VFailure."""
    def __init__(self, *args, **kargs):
        super_init = super(VFPendingTimeout, self).__init__
        super_init(VPendingTimeout(*args, **kargs))


def pending(f):
    """Decorator @pending for converting a generator (or function).

    :param f: a function or generator
    :type  f: callable, generator
    :returns: modified function

    Converts a generator into a function which returns
    :class:`VPending`\ , with the generator's processing as its
    callback/failback chain and the final value yielded by the
    generator as the pending call object's callback value (or a throws
    exception as its failback). If *f* is not a generator but a
    regular function, it converts it into a function which returns the
    function result as a :class:`VPending`\ .

    """
    def decorated(*args, **kargs):
        result = f(*args, **kargs)
        if isinstance(result, types.GeneratorType):
            processor = _VPendingGenerator(result)
            return processor()
        else:
            pending = VPending.as_pending(result)
            return pending
    return decorated


class _VPendingGenerator(object):
    """VPending result and call-chain wrapper for a generator."""

    def __init__(self, generator):
        self.__generator = generator

    def __call__(self):
        self.__result = VPending()

        try:
            value = next(self.__generator)
        except StopIteration:
            self.__result.callback(None)
        except Exception as e:
            value = VFailure(e)
            self.__process(is_success=False, value=value)
        else:
            self.__process(is_success=True, value=value)

        return self.__result

    def __process(self, is_success, value):
        while not isinstance(value, VPending):
            try:
                if is_success:
                    result = self.__generator.send(value)
                else:
                    result = self.__generator.throw(value.value)
            except StopIteration:
                self.__result.callback(value)
                return
            except Exception as e:
                is_success = False
                value = VFailure(e)
                self.__result.callback(value)
                return
            else:
                is_success = True
                value = result
        value.add_callpair(self.__callback, self.__failback)

    def __callback(self, result):
        self.__process(is_success=True, value=result)

    def __failback(self, failure):
        self.__process(is_success=False, value=failure)


class VPending(object):
    """References to the result of a pending (asynchronous) call.

    The class enables functions to return references to results that
    may not be available at the time the function wants to
    return. Observers that are interested in the result can register
    callback functions to receive results when they are ready.

    :param result: if not None, result of the pending object

    If *result* is provided and is an instance of :class:`Exception`
    or :class:`versile.common.failure.VFailure`\ , it has the same
    effect as firing *result* as a failback immediately after
    construction. Otherwise, if provided it has the same effect as
    firing a callback immediately after construction.

    .. automethod: __del__

    """

    def __init__(self, result=None):
        self.__callchain = collections.deque()
        self.__fired = False
        self.__result = None
        self.__result_is_failure = None
        self.__paused = False
        self.__cancelled = False
        self.__canceller = None
        self._timed_out = False  # For derived classes supporting timers

        if result is not None:
            if isinstance(result, VFailure):
                self.__result = result
                self.__result_is_failure = True
            elif isinstance(result, Exception):
                self.__result = VFailure(result)
                self.__result_is_failure = True
            else:
                self.__result = result
                self.__result_is_failure = False
            self.__fired = True

    def __del__(self):
        """If not fired or non-empty callchain perform self.cancel().

        As the object is no longer referenced, it will not receive any
        additional firing of results or failures. This effectively
        implies cancelling of the remaining callback pipeline (which
        is what this destructor does).

        """
        if not self.__fired or self.__callchain:
            self.cancel()

    @classmethod
    def as_pending(self, obj):
        """Returns an object as a VPending

        :param obj: the object to wrap
        :returns:   wrapped object
        :rtype:     :class:`VPending`

        If *obj* is a :class:`VPending` the object is returned as-is,
        otherwise VPending(obj) is returned.

        """
        if isinstance(obj, VPending):
            return obj
        else:
            return VPending(result=obj)

    def add_callpair(self, callback, failback, cargs=[], ckargs={},
                     fargs=[], fkargs={}):
        """Registers a callback and failback to the result processing chain.

        :param callback: callback to execute
        :type  callback: callable
        :param failback: failback to execute
        :type  failback: callable

        When the call processing chain fires a normal result 'result'
        to this call pair, then *callback*\ (result, \*cargs, \*\*ckargs)
        is executed and the result is used in the call chain.

        If call chain fires a failure 'fail' to this call pair, then
        *failback*\ (fail, \*fargs, \*\*kargs) is executed and the
        result is used in the call chain.

        If *callback* or *failback* is None, then a pass-through
        function is used instead.

        """
        if callback is None and failback is None:
            raise TypeError('Callback and failback cannot both be None')
        if ((cargs and not isinstance(cargs, (tuple, list)))
            or (fargs and not isinstance(fargs, (tuple, list)))):
            raise TypeError('cargs/fargs must be tuple or list')
        if ((ckargs and not isinstance(ckargs, dict))
            or (fkargs and not isinstance(fkargs, dict))):
            raise TypeError('ckargs/fkargs must be dict')
        entry = []
        if callback:
            entry.append((callback, cargs, ckargs))
        else:
            entry.append(None)
        if failback:
            entry.append((failback, fargs, fkargs))
        else:
            entry.append(None)
        self.__callchain.append(entry)
        # Process chain in case it has already been fired
        self.__process_chain()

    def add_callback(self, callback, *args, **kargs):
        """Adds a callback-only step to the chain.

        Convenience method for:

            add_callbacks(callback=callback, failback=None,
            cargs=args, ckargs=kargs)

        """
        self.add_callpair(callback=callback, failback=None,
                          cargs=args, ckargs=kargs)

    def add_failback(self, failback, *args, **kargs):
        """Adds a failback-only step to the chain.

        Convenience method for:

            add_callbacks(callback=None, failback=failback,
            fargs=args, fkargs=kargs)

        """
        self.add_callpair(callback=None, failback=failback,
                          fargs=args, fkargs=kargs)

    def add_both(self, function, *args, **kargs):
        """Add a function as both a callback and failback.

        Convenience method for:

            add_callbacks(callback=function, failback=function,
            cargs=args, ckargs=kargs, fargs=args, fkargs=kargs)

        """
        self.add_callpair(callback=function, failback=function,
                          cargs=args, ckargs=kargs, fargs=args, fkargs=kargs)

    def add_failresult(self, result):
        """Adds a failback which returns 'result'.

        Convenience method for:

            add_failback(lambda arg: result)

        """
        def failback(reason):
            return result
        self.add_failback(failback)

    def set_canceller(self, canceller):
        """Set a canceller function for the object.

        :param canceller: the canceller function to set
        :type  canceller: callable

        If the :class:`VPending` is cancelled before its input chain
        has been cancelled, then the registered canceller function (if
        any) is called.

        """
        self.__canceller = canceller

    def callback(self, result):
        """Registers a result of the operation referenced by the object.

        :param result: the result of the asynchronous operation
        :raises:       :exc:`VPendingAlreadyFired`

        Registering a result will initiate processing of any
        registered callback/failback chain. A result or failure can be
        registered only once. If attempting to register more than
        once, an exception will be raised.

        """
        if self.__fired:
            raise VPendingAlreadyFired('Can only callback/failback once')
        self.__fired = True
        self.__result = result
        self.__result_is_failure = False
        self.__process_chain()

    def failback(self, failure=None):
        """Registers a failure of the operation referenced by the object.

        :param failure: failure information for the operation
        :type  failure: :class:`versile.common.failure.VFailure`
        :raises:        :exc:`VPendingAlreadyFired`

        Registering a failure will initiate processing of any
        registered callback/failback chain. A result or failure can be
        registered only once. If attempting to register more than
        once, an exception will be raised.

        """
        if self.__fired:
            raise VPendingAlreadyFired('Can only callback/failback once')
        self.__fired = True
        if not isinstance(failure, VFailure):
            failure = VFailure(failure)
        self.__result = failure
        self.__result_is_failure = True
        self.__process_chain()

    def cancel(self):
        """Cancels the callback/failback processing chain.

        If a callback or failback has not yet been registered, then
        the canceller function (if registered) is called. If
        callback/failback chain processing has not completed, then any
        lower-level VPending being waited on are cancelled, and the
        next failback registered on the chain is called with
        :class:`VFPendingCancelled` as failure reason.

        """
        self.__cancelled = True
        self.cancel_timeout()  # Do not need a timeout if already cancelled
        if not self.__fired and self.__canceller:
            self.__canceller()
        elif self.__fired and isinstance(self.__result, VPending):
            self.__result.cancel()
        self.__process_chain()

    def pause(self):
        """Pauses execution of callback/failback chain.

        When results are fired in the chain and the chain is paused,
        then the next callback/failback steps in the chain are not
        executed until the chain is unpaused.

        Note that sub-chains will cause pause/unpause on their parent
        chains which may conflict with calling this externally on the
        chain. This call is primarily intended for use internally by
        sub-chains. Also note that pausing not affect timeouts.

        """
        self.__paused = True

    def unpause(self):
        """Unpauses a call chain which has been paused

        Unpauses call chains which have been paused with
        :meth:`pause`\ .

        """
        self.__paused = False
        self.__process_chain()

    def __process_chain(self):
        while (self.__callchain and (self.__fired or self.__cancelled)
               and not self.__paused):
            call, fail = self.__callchain.popleft()
            if not self.__cancelled:
                val = self.__result
                if self.__result_is_failure:
                    nxt = fail
                else:
                    nxt = call
            else:
                if not self._timed_out:
                    val = VFPendingCancelled()
                else:
                    val = VFPendingTimeout()
                nxt = fail
            call = fail = None
            if nxt:
                callback, args, kargs = nxt
                try:
                    result = callback(val, *args, **kargs)
                    self.__result = result
                    if isinstance(result, VPending):
                        result.add_callpair(self.__subchain_callback,
                                            self.__subchain_failback)
                        self.pause()
                        break
                    self.__result_is_failure = isinstance(result, VFailure)
                except Exception as e:
                    self.__result = VFailure(e)
                    self.__result_is_failure = True
                finally:
                    callback = args = kargs = val = result = None

    def __subchain_callback(self, result):
        self.__result = result
        self.__result_is_failure = False
        self.unpause()

    def __subchain_failback(self, result):
        self.__result = result
        self.__result_is_failure = True
        self.unpause()


@abstract
class VTimedPending(VPending):
    """Pending result which supports 'timeouts'.

    Abstract class, should not be directly instantiated. Derived
    classes must implement a timer mechanism.

    This class enables setting a timeout directly on the pending
    object.

    """

    @abstract
    def set_timeout(self, seconds):
        """Sets a timeout on firing the VPending.

        :param seconds: timeout in seconds
        :type  seconds: float

        When the timeout expires, the chain is cancelled with
        :exc:`VPendingTimeout`. If the chain has not yet fired, it
        will call a canceller similar to :meth:`cancel`\ .

        If a timeout is already set, this will call reset_if_earlier
        on the timeout, which will change its scheduled timeout only
        if the new schedule is earlier than the previously set
        schedule - otherwise the original schedule is retained.

        If the object has alread cancelled or timed out, the timeout
        has no effect.

        """
        raise NotImplementedError()

    @abstract
    def cancel_timeout(self):
        """Cancels a timeout which has been set and is currently active.

        Cancels a timeout set with :meth:`set_timeout`

        """
        raise NotImplementedError()

    @abstract
    @property
    def timeout(self):
        """Reference to a timeout which has been set.

        When a timeout has been set and has not expired or been
        cancelled, this property holds a :class:`VScheduledCall` which
        references the timeout. It can be used to e.g. reset the
        timer.

        """
        raise NotImplementedError()

    def cancel(self):
        """Cancels the callback/failback processing chain.

        See :meth:`versile.common.pending.VPending`\ . Also cancels
        any timeout set on the object.

        """
        self.cancel_timeout()
        super(VReactorPending, self).cancel()


class VPendingList(VPending):
    """Monitors callback/failback of a list of :class:`VPending` objects.

    The object fires a callback when a callback/failback has been
    received from all monitored :class:`VPending` objects.  The
    callback result delivered is a list of tuples (did_succeed,
    result) where 'did_succeed' is True if the result was a normal
    result, or False if it was a failure.

    :param pending_list: list of objects to monitor
    :type  pending_list: list<\ :class:`VPending`\ >

    """

    def __init__(self, pending_list):
        if not isinstance(pending_list, (list, tuple)):
            raise TypeError('pending_list must be a list or tuple')
        for p in pending_list:
            if not isinstance(p, VPending):
                raise TypeError('pending_list members must be VPending')
        super(VPendingList, self).__init__()
        self.__results = [None] * len(pending_list)
        if not pending_list:
            self.__fire_callback()
        else:
            self.__pending_list = {}
            for i in xrange(len(pending_list)):
                p = pending_list[i]
                self.__pending_list[i] = p
                p.add_callpair(self.__callback, self.__failback,
                               cargs=[i], fargs=[i])

    def callback(self, result):
        raise VPendingException('Cannot call externally on VPendingList')

    def failback(self, failure=None):
        super(VPendingList, self).failback(failure)
        # Cancel remaining pending results - they would anyways be ignored
        self.cancel()

    def cancel(self):
        for p in self.__pending_list.values():
            p.cancel()
        super(VPendingList, self).cancel()

    def __callback(self, result, pos):
        if pos not in self.__pending_list:
            raise VPendingException('Invalid list position reference')
        self.__results[pos] = (True, result)
        self.__pending_list.pop(pos)
        if not self.__pending_list:
            self.__fire_callback()

    def __failback(self, result, pos):
        if pos not in self.__pending_list:
            raise VPendingException('Invalid list position reference')
        self.__results[pos] = (False, result)
        self.__pending_list.pop(pos)
        if not self.__pending_list:
            self.__fire_callback()

    def __fire_callback(self):
        try:
            super(VPendingList, self).callback(self.__results)
        except VPendingException as e:
            # Just ignore exceptions here - this should mean an error was
            # already propagated, e.g. the deferred was cancelled
            _v_silent(e)
