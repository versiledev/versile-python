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

"""Reactor framework."""
from __future__ import print_function, unicode_literals

import collections
import types

from versile.internal import _vexport
from versile.common.iface import VInterface, implements
from versile.common.failure import VFailure
from versile.common.pending import VPendingException, VPendingAlreadyFired
from versile.common.pending import VPendingCancelled, VPendingTimeout

__all__ = ['IVCoreReactor', 'IVDescriptorReactor', 'IVReactorObject',
           'IVScheduledCall', 'IVTimeReactor', 'VFReactorException',
           'VFReactorStopped', 'VReactorException', 'VReactorStopped',
           'VScheduledCall']
__all__ = _vexport(__all__)


class IVCoreReactor(VInterface):
    """Interface for base reactor functionality"""

    def run(self):
        """Initiate reactor loop.

        The method executes the reactor loop and does not return until
        the reactor loop ends.

        """

    def call_when_running(self, callback, *args, **kargs):
        """Register a callback when reactor is started.

        :returns: reference to the call
        :rtype:   :class:`IVScheduledCall`

        Schedules callback(\*args, \*\*kargs) to be called when the
        reactor is started.

        """

    def started(self):
        """Called when the reactor is started.

        Called internally by the reactor just before entering reactor
        loop.

        """

    def stop(self):
        """Exit reactor loop."""

    @property
    def log(self):
        """Reactor :class:`versile.common.log.VLogger`\ ."""
        pass


class IVDescriptorReactor(VInterface):
    """Interface for reactors supporting descriptor I/O."""

    def add_reader(self, reader):
        """Register an input reader for event loop processing.

        :param reader: the reader to add
        :type  reader: :class:`versile.reactor.io.IVByteHandleInput`

        """

    def remove_reader(self, reader):
        """Stop processing events for an input reader.

        :param reader: the reader to stop processing
        :type  reader: :class:`versile.reactor.io.IVByteHandleInput`

        This will also cause the reactor to dereference the input.

        """

    def add_writer(self, writer):
        """Register an output writer for event loop processing.

        :param writer: the writer to add
        :type  writer: :class:`versile.reactor.io.IVByteHandleOutput`

        """

    def remove_writer(self, writer):
        """Stop processing events for an output writer.

        :param writer: the writer to stop processing
        :type  writer: :class:`versile.reactor.io.IVByteHandleOutput`

        This will also cause the reactor to dereference the output.

        """

    def remove_all(self):
        """Stops processing events for all registered inputs and outputs."""

    @property
    def readers(self):
        """Shallow copy of the current set of connected readers.

        Accessing this property is not thread-safe; threads other than
        the reactor thread cannot rely on the list not to be changed
        by the ractor..

        """

    @property
    def writers(self):
        """Shallow copy of the current set of connected writers.

        Accessing this property is not thread-safe; threads other than
        the reactor thread cannot rely on the list not to be changed
        by the ractor..

        """


class IVTimeReactor(VInterface):
    """Interface for reactors supporting timed task scheduling."""

    def time(self):
        """Returns the reactor's current time.

        :returns: reactor's current time
        :rtype:   float

        Time format is similar to :func:`time.time`

        """

    def execute(self, callback, *args, **kargs):
        """Execute callback in reactor thread.

        Arguments are similar to :meth:`schedule`\ . If the current
        thread is the reactor thread, *callback* is executed
        immediately; otherwise it is scheduled for execution by
        :meth:`schedule`\ .

        """

    def schedule(self, delay_time, callback, *args, **kargs):
        """Schedules a call for execution.

        :param delay_time: seconds until call can be executed
        :type  delay_time: float
        :param callback:   function to execute
        :type  callback:   callable
        :param args:       arguments to function
        :param kargs:      keyword arguments to function
        :returns:          reference to the scheduled call
        :rtype:            :class:`IVScheduledCall`

        Requests that reactor should executes the following after
        *delay_time*\ :

            callback(\*args, \*\*kargs)

        .. note::

             Execution is not guaranteed to occur at the given
             time. The exact time of execution depends on reactor
             implementation and the workload of the reactor's event
             loop. However, the function is guaranteed not to be
             executed *before* the set time.

        """

    def cg_schedule(self, delay_time, callgroup, callback, *args, **kargs):
        """Schedules a call for execution and associates with a call group.

        :param call_group: the call group to associate the call with

        Other parameters, return value and usage same as :meth:`schedule`\ .

        *callgroup* can be any object which can be used as a
        dictionary key, except None. The method associates the
        scheduled call to a call group. This allows identifying and/or
        removing pending calls by call group. This can be useful
        e.g. for a service which is shutting down and wants to clean
        up any pending calls it may have registered.

        """

    def add_call(self, call):
        """Schedules a call for execution from an :class:`IVScheduledCall`\ .

        :param call: the call to add
        :type  call: :class:`IVScheduledCall`

        Similar to :meth:`schedule` except all the information about
        the call is held by the provided object. Will only add the
        call if it is set to be 'active'.

        """

    def remove_call(self, call):
        """Unschedules an :class:`IVScheduledCall`\ .

        :param call: the call to remove
        :type  call: :class:`IVScheduledCall`

        The call must be a call which has been previously registered
        with the reactor (or received as a return value from
        scheduling a call with the reactor).

        """

    def cg_remove_calls(self, callgroup):
        """Remove all scheduled calls associated with a call group.

        :param callgroup: the call group to associate the call with

        """


class IVScheduledCall(VInterface):
    """Interface to a call which can be scheduled with a reactor."""

    def cancel(self):
        """Cancel execution of the call.

        Cancels the call if it has been registered with a reactor and
        has not yet been executed.

        """

    def delay(self, delay_time):
        """Delay execution of a scheduled call.

        :param delay_time: seconds delay to add to current schedule
        :type  delay_time: float

        """

    def reset(self, delay):
        """Reset execution time of a scheduled call.

        :param delay: seconds until execution from current time
        :type  delay: float

        """

    def execute(self):
        """Execute the call (invoked by the reactor to execute)."""

    @property
    def callgroup(self):
        """Call group the call is registered to (or None)"""

    @property
    def scheduled_time(self):
        """Reactor-time when call is scheduled to execute."""

    @property
    def active(self):
        """True if call is active (i.e. has not been cancelled)."""

    @property
    def executed(self):
        """True if the scheduled call has been executed."""


class IVReactorObject(object):
    """Interface to an object which holds a reference to a reactor."""

    @property
    def reactor(self):
        """The object's registered reactor"""


class VReactorException(Exception):
    """General exception for reactor operations."""


class VReactorStopped(VReactorException):
    """Indicates reactor has been stopped."""


class VFReactorException(VFailure):
    def __init__(self, *args, **kargs):
        super_init = super(VFReactorException, self).__init__
        super_init(VReactorException(*args, **kargs))

class VFReactorStopped(VFailure):
    def __init__(self, *args, **kargs):
        super_init = super(VFReactorStopped, self).__init__
        super_init(VReactorStopped(*args, **kargs))

@implements(IVScheduledCall, IVReactorObject)
class VScheduledCall(object):
    """A call which can be scheduled with a reactor.

    .. warning::

        Cannot be reliably called from outside the reactor thread.

    :param reactor:   reactor providing timer services
    :type  reactor:   :class:`IVTimeReactor`
    :param delay:     seconds until call is executed
    :type  delay:     float
    :param callgroup: call group for this call (or None)
    :type  callgroup: any object allowed as a dict key
    :param callback:  function to call
    :type  callback:  callable
    :param add_call:  if True then constructor adds call to reactor
    :type  add_call:  bool

    If *add_call* is True then the call is scheduled for executing
    during construction. Otherwise, the caller is responsible for
    adding the call with the reactor in order to complete call
    activation.

    Executes callback(\*args, \*\*kargs) when the registered call
    is executed.

    """

    def __init__(self, reactor, delay, callgroup, callback, add_call,
                 *args, **kargs):
        self.__start_time = reactor.time()
        self.__reactor = reactor
        self.__delay = delay
        self.__scheculed_time = self.__start_time + self.__delay
        self.__callgroup = callgroup
        self.__callback = callback
        self.__call_args = args
        self.__call_kargs = kargs
        self.__active = True
        self.__executed = False
        self.__active = True

        if add_call:
            reactor.add_call(self)

    def cancel(self):
        """See :meth:`IVScheduledCall.cancel`\ ."""
        self.__active = False # This statement must go first, see execute()
        self.__callback = self.__call_args = self.__call_kargs = None
        self.__reactor.remove_call(self)

    def delay(self, delay_time):
        """See :meth:`IVScheduledCall.delay`\ ."""
        if self.__active:
            self.__reactor.remove_call(self)
            self.__delay += delay_time
            self.__scheculed_time = self.__start_time + self.__delay
            self.__reactor.add_call(self)

    def reset(self, delay):
        """See :meth:`IVScheduledCall.reset`\ ."""
        if self.active:
            self.__reactor.remove_call(self)
            self.__start_time = self.__reactor.time()
            self.__delay = delay
            self.__scheculed_time = self.__start_time + self.__delay
            self.__reactor.add_call(self)

    def reset_if_earlier(self, delay):
        if self.active:
            r_time = self.__reactor.time()
            if r_time + delay < self.__scheculed_time:
                self.__reactor.remove_call(self)
                self.__start_time = r_time
                self.__delay = delay
                self.__scheculed_time = self.__start_time + self.__delay
                self.__reactor.add_call(self)

    def execute(self):
        """See :meth:`IVScheduledCall.execute`\ ."""
        # Copy call parameters first to avoid race conditions if cancel() is
        # called from outside the reactor thread
        call = self.__callback
        args, kargs = self.__call_args, self.__call_kargs
        if self.__active and not self.__executed:
            try:
                call(*args, **kargs)
            finally:
                self.__executed = True

    @property
    def callgroup(self):
        return self.__callgroup

    @property
    def reactor(self):
        """See :attr:`IVReactorObject.reactor`\ ."""
        return self.__reactor

    @property
    def scheduled_time(self):
        """See :attr:`IVScheduledCall.scheduled_time`\ ."""
        return self.__scheculed_time

    @property
    def active(self):
        """See :attr:`IVScheduledCall.active`\ ."""
        return self.__active

    @property
    def executed(self):
        """See :attr:`IVScheduledCall.executed`\ ."""
        return self.__executed

    def __cmp__(self, other):
        # Used for sorting scheduled calls in order of scheduled call time
        return cmp(self.scheduled_time, other.scheduled_time)

    def __lt__(self, other):
        # Used for python3 which ignores __cmp__
        return self.scheduled_time < other.scheduled_time
