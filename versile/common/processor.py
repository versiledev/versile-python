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

"""Generic thread-bases processor for executing queued function calls."""
from __future__ import print_function, unicode_literals

import threading
import weakref

from versile.internal import _vexport, _v_silent
from versile.common.util import VCondition, VResult


__all__ = ['VProcessor', 'VProcessorCall', 'VProcessorError',
           'VProcessorNoCall', 'VProcessorStopWorker' ]
__all__ = _vexport(__all__)


class VProcessorError(Exception):
    """General processor error."""


class VProcessorNoCall(Exception):
    """A processor call queue is empty."""


class VProcessorStopWorker(Exception):
    """A worker requesting a call should end its operation."""


class VProcessor(VCondition):
    """Generic task processor for function calls.

    The processor maintains a queue of function calls which are handed
    off to processor workers that execute the calls. The processor
    manages and maintains a set of worker threads which pick tasks off
    the processor's task queue. Calls can be queued with
    :meth:`queue_call`, which returns a :class:`VProcessorCall` object
    that enables the caller to interact with the call after it has
    been scheduled.

    .. note::

        Worker threads that have been initiated will not be stopped
        until the processor is requested to do so, calling either
        :meth:`stop` or :meth:`set_workers`\ .

    :param workers: number of workers to start
    :type  workers: int
    :param daemon:  if True then make worker threads daemonic
    :type  daemon:  bool
    :param lazy:    if True then lazy-start workers
    :type  lazy:    bool
    :param logger:  if True then log worker exceptions (or None)
    :type  logger:  :class:`versile.common.log.VLogger`

    If *daemon* is set, worker threads are configured to be
    daemonic. A program will exit if only daemon threads remain,
    meaning workers may terminate when the main program exits.

    If *lazy* is False then all worker threads will be immediately
    created, otherwise worker threads are created the first time
    their capacity is needed.

    If *logger* is provided then processor workers will log exceptions
    of executed calls to the provided logger, with a 'warn' logging
    level.

    """

    # Class processor
    _cls_processor = None
    _cls_processor_lock = threading.RLock()

    def __init__(self, workers, daemon=False, lazy=True, logger=False):
        super(VProcessor, self).__init__()
        self.__first_node = None
        self.__last_node = None
        self.__group_calls = dict()   # call_group -> set(call_node)
        self._queued_calls = 0
        self._active_calls = 0
        self._current_workers = 0
        self._target_workers = 0
        self.__daemon = daemon
        self.__log = logger

        self.set_workers(workers, lazy=lazy)

    @classmethod
    def cls_processor(cls, lazy=True, lazy_workers=5, lazy_daemon=False):
        """Returns a class processor.

        :param lazy:         if set, lazy-create a processor
        :type  lazy:         bool
        :param lazy_workers: if lazy_creating, number of workers to add
        :type  lazy_workers: int
        :param lazy_daemon:  if lazy_creating, use as 'daemon' argument
        :type  lazy_daemon:  bool

        The class processor is a processor which has been set on the
        class, which can be used as a shared resource throughout a
        program. This offers a convenient mechanism for instantiating
        only one sigle processor.

        """
        with cls._cls_processor_lock:
            if not cls._cls_processor and lazy:
                cls._cls_processor = VProcessor(lazy_workers)
            return cls._cls_processor

    @classmethod
    def lazy(cls, processor=None):
        """Returns the provided processor, or a class processor (if set)

        :param processor: a processor, or None
        :type  processor: :class:`VProcessor`
        :returns:         processor, or class processor
        :raises:          :exc:`VProcessorError`

        If 'processor' is set, then that object is
        returned. Otherwise, if a class processor has been created,
        then the class processor is returned. If no processor is
        available, then an exception is raised.

        """
        if processor:
            if isinstance(processor, VProcessor):
                return processor
            else:
                raise VProcessorError('Not a processor object')
        elif cls._cls_processor:
            return cls._cls_processor
        else:
            raise VProcessorError('No processor available')

    def queue_call(self, function, args=[], kargs={}, group=None,
                 result_only=False, start_callback=None, done_callback=None):
        """Push a function call onto the call queue.

        :param function:       the function to call
        :type  function:       callable
        :param args:           list of function arguments
        :param kargs:          dictionary of function keyword arguments
        :param group:          a call group for this call
        :type  group:          object
        :param result_only:    if True, call is removed if call is dereferenced
        :type  result_only:    bool
        :param start_callback: function to call when the job is started
        :type  start_callback: callable
        :param done_callback:  function to call when the job is completed
        :type  done_callback:  callable
        :returns:              call reference
        :rtype:                :class:`VProcessorCall`
        :raises:               :exc:`VProcessorError`

        Schedules function(\*args, \*\*kargs) for execution.

        If *result_only* is True, then the call is removed from the
        queue if it is detected that no code is interestedi n the
        result, meaning the :class:`VProcessorCall` associated with
        the call is dereferenced and garbage collected. If the call
        should be executed regardless, then *result_only* should be
        set to False (as is the default).

        If *start_callback* is set, it will be executed by the worker
        when the task is popped off the processor's queue - and will
        be executed while still holding a lock on the processor.

        Raises an exception if the call cannot be scheduled. The
        default implementation does not raise any exception, however
        derived classes may override.

        """
        with self:
            # Set up and queue the call
            node = _VCallNode()
            call = VProcessorCall(self, node, function, args, kargs)
            node.set_call(call, group=group, result_only=result_only,
                          start_cback=start_callback,
                          done_cback=done_callback)
            if self.__last_node:
                self.__last_node.insert_after(node)
                self.__last_node = node
            else:
                self.__first_node = self.__last_node = node
            if group:
                call_group = self.__group_calls.get(group, None)
                if not call_group:
                    call_group = set()
                    self.__group_calls[group] = call_group
                call_group.add(node)
            self._queued_calls += 1

            # If applicable lazy-start a worker to handle the call
            if ((self._queued_calls >= self._current_workers)
                and (self._current_workers < self._target_workers)):
                worker = _VProcessorWorker(self, self.__log)
                if self.__daemon:
                    worker.daemon = True
                worker.start()
                self._current_workers += 1

            self.notify()
            return call

    def has_group_calls(self, group):
        """Returns True if there are queued calls associated with a group.

        :param group: an object which represents the call group
        :returns:     True if the group has queued calls

        """
        with self:
            return group in self.__group_calls

    def remove_group_calls(self, group):
        """Remove all queued calls associated with a group.

        :param group: an object which represents the call group

        If group is None then no nodes will be returned.

        """
        with self:
            if not group:
                return
            group_calls = self.__group_calls.pop(group, None)
            while group_calls:
                self._remove_node(group_calls.pop())

    def workers(self):
        """Returns the currently set target number of workers.

        :returns: target number of workers

        Note that all target workers may not have been instantiated as
        threads (if lazy thread creation is defined on the processor).

        """
        with self:
            return self._target_workers

    def set_workers(self, workers, lazy=True):
        """Set the target number of workers.

        :param workers: number of workers to start
        :type  workers: int
        :param lazy:    if True then lazy-start workers
        :type  lazy:    bool

        If target workers was increased, this will add (or lazy-add)
        workers. If target workers was reduced, this will initiate
        shut down of non-active workers until number of workers is the
        same as the target.

        """
        with self:
            self._target_workers = workers
            if workers > self._current_workers and not lazy:
                while self._current_workers < workers:
                    worker = _VProcessorWorker(self, self.__log)
                    if self.__daemon:
                        worker.daemon = True
                    worker.start()
                    self._current_workers += 1
            elif workers < self._current_workers:
                self.notify()

    def stop(self, purge=False):
        """Stop all worker processing by shutting down all worker threads.

        :param purge: if True, then empty the call queue
        :type  purge: bool

        If *purge* is set to False, this is a convenience method for
        self.set_workers(0). It is possible to restart work by calling
        :meth:`set_workers`\ . If *purge* is set to True, this will
        cancel and dereference all nodes in the call queue.

        """
        with self:
            self.set_workers(0)
            if purge:
                while self.__last_node:
                    node = self.__last_node
                    node.call.cancel()
                    # This call should be redundant
                    self._remove_node(node)

    def _pop_call(self):
        """Pops the next call for execution.

        :returns: (a call for execution, start_callback, done_callback)
        :rtype:   tuple(:class:`VProcessorCall`, callable, callable)
        :raises:  :exc:`VProcessorNoCall`, :exc:`VProcessorStopWorker`

        Raises an exception if there is no call available, or if the
        worker which pops the call should end its operation.

        """
        with self:
            if self._target_workers < self._current_workers:
                self._current_workers -= 1
                if self._target_workers < self._current_workers:
                    self.notify()
                raise VProcessorStopWorker()
            if self.__first_node is None:
                raise VProcessorNoCall()
            node = self.__first_node
            # When extracting, clear properties on node - this is particularly
            # important because node has circular reference with its node.call
            call, node.call = node.call, None
            start_cback, node.start_cback = node.start_cback, None
            done_cback, node.done_cback = node.done_cback, None
            self._remove_node(self.__first_node)
            self._active_calls += 1
            return (call, start_cback, done_cback)

    def _call_done(self):
        """Notification from worker that processing of a call was completed."""
        with self:
            self._active_calls -= 1

    def _remove_node(self, node):
        """Remove call from call queue (if it is in queue).

        :param node: the queue node of the call to remove
        :type  node: :class:`_VCallNode`

        If the call is not in the queue (e.g. was never queued, was
        executed, or is being executed), then this call has no effect.

        """
        with self:
            if not node._prev:
                self.__first_node = node._next
            if not node._next:
                self.__last_node = node._prev
            node.remove()

            group = node.group
            if group:
                call_group = self.__group_calls.get(group, None)
                if call_group:
                    call_group.discard(node)
                if not call_group:
                    self.__group_calls.pop(group)
                node.group = None

            self._queued_calls -= 1

    def _deref_call(self, node):
        with self:
            if not node.is_result_only():
                self.remove_call(node)


class VProcessorCall(VResult):
    """Reference to a call queued with a :class:`VProcessor`\ .

    .. note::

        :class:`VProcessorCall` should normally not be instantiated
        directly, instead it is received as a result of calling
        :meth:`VProcessor.queue_call`\ .


    """

    def __init__(self, processor, node, function, f_args, f_kargs):
        super(VProcessorCall, self).__init__()
        self.__processor = weakref.ref(processor)
        self.__node = node
        self.__function = function
        self.__args = f_args
        self.__kargs = f_kargs

    def __del__(self):
        """Notify the processor that call object was dereferenced."""
        processor = self.__processor()
        if processor:
            processor._deref_call(self.__node)

    def _cancel(self):
        """Removes call from the processor queue if not already executed."""
        with self:
            processor = self.__processor()
            if processor:
                processor._remove_node(self.__node)
            self.__function = None
            self.__args = None
            self.__kargs = None

    def _execute(self):
        """Executes the call.

        Should only be called by the owning processor, and should only
        be called once. Call input data is dereferenced after the call
        was executed.

        """
        with self:
            f, args, kargs = self.__function, self.__args, self.__kargs
            self.__function = self.__args = self.__kargs = None
        try:
            result = f(*args, **kargs)
        except Exception as e:
            self.push_exception(e)
        else:
            self.push_result(result)


class _VProcessorWorker(threading.Thread):
    """A thread which retreives and executes queued function calls.

    Retreives and executes one queued method call at a time from a
    :class:`VProcessor`\ . If no calls are available, the worker waits
    until a call is ready for its execution. Upon signal from the
    processor, the worker terminates.

    """

    def __init__(self, processor, logger=False):
        """Initiates the processor worker.

        Should only be called by the owning VProcessor object.

        """
        super(_VProcessorWorker, self).__init__()
        self.__processor = processor
        self.__log = logger

    def run(self):
        processor = self.__processor
        while True:
            try:
                with processor:
                    try:
                        call, start_cback, done_cback = processor._pop_call()
                    except VProcessorNoCall:
                        processor.wait()
                        continue
                    except VProcessorStopWorker:
                        break
                    else:
                        if start_cback:
                            try:
                                start_cback()
                            except Exception as e:
                                if self.__log:
                                    self.__log.warn('worker start_cback fail')
                                    self.__log.log_trace(lvl=self.__log.WARN)
                                else:
                                    _v_silent(e)
                call._execute()
                if self.__log:
                    try:
                        call.result()
                    except Exception as e:
                        self.__log.warn('worker execute raised exception')
                        self.__log.log_trace(lvl=self.__log.WARN)

                processor._call_done()
                if done_cback:
                    try:
                        done_cback()
                    except Exception as e:
                        if self.__log:
                            self.__log.warn('worker done_cback failed')
                            self.__log.log_trace(lvl=self.__log.WARN)
                        else:
                            _v_silent(e)
            finally:
                # Make sure to dereference any object we don't need
                call = start_cback = done_cback = None


class _VCallNode(object):
    """Node in a double-linked list for representing a processor call queue."""

    def __init__(self):
        self._next = None
        self._prev = None
        self.call = None
        self.start_cback = None
        self.done_cback = None
        self.group = None

    def set_call(self, call, group, result_only, start_cback, done_cback):
        self.group = group
        if result_only:
            self.call = weakref.ref(call)
        else:
            self.call = call
        self.start_cback = start_cback
        self.done_cback = done_cback

    def is_result_only(self):
        return not isinstance(self.call, VProcessorCall)

    def remove(self):
        """Detaches from double-linked list and clears all attributes.

        Will only pop the node from the internal linked-list structure
        and does not handle end-point effects for external referances
        to the linked list. Nodes in processor node lists should only
        be cleared using :meth.`VProcessor._remove_node`\ .

        """
        if self._next:
            self._next._prev = self._prev
        if self._prev:
            self._prev._next = self._next
        self._next = self._prev = None

    def insert_after(self, node):
        if node._next or node._prev:
            raise VProcessorError('Node already connected')
        if self._next:
            self._next._prev = node
            node._next = self._next
        self._next = node
        node._prev = self

    def insert_before(self, node):
        if node._next or node._prev:
            raise VProcessorError('Node already connected')
        if self._prev:
            self._prev._next = node
            node._prev = self._prev
        self._prev = node
        node._next = self
