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

"""Utility classes for :term:`VOL` interaction."""
from __future__ import print_function, unicode_literals

from collections import deque
import threading

from versile.internal import _vexport, _v_silent
from versile.common.iface import abstract
from versile.common.pending import VPending
from versile.common.util import VLockable, VCancelledResult
from versile.orb.link import VLink


__all__ = ['VSequenceCaller', 'VSequenceCallQueue',
           'VSequenceCallException', 'VLinkMonitor']
__all__ = _vexport(__all__)


class VSequenceCallException(Exception):
    """Call queue exception."""


class VSequenceCaller(object):
    """A call queue which manages a limit on the number of pending calls.

    :param call_limit: maximum pending calls
    :type  call_limit: int

    Queues remote calls for execution and initiates in sequence, with
    a maximum number of pending calls. Calls are made with a prefix
    argument which is a call ID number, so that the receiving peer can
    use the call ID argument to resolve calls in sequence. The call ID
    of the first call is 0, and for each following call the ID is
    increased by none.

    """

    def __init__(self, call_limit=0):
        self._call_queue = deque()
        self._call_lim = call_limit
        self._pending = 0
        self._next_msg_id = 0
        self._lock = threading.Lock()

    def call(self, method, args, callback=None, failback=None):
        """Queues a peer call for execution.

        :param method:   remote method to call
        :type  method:   callable
        :param args:     arguments to method
        :type  args:     tuple
        :param callback: function to call with call result (or None)
        :type  callback: callable
        :param failback: function to call with exception result (or None)
        :type  failback: callable
        :returns:        call_id passed to peer
        :rtype:          int

        The remote method *method* must be a
        :class:`versile.orb.entity.VProxy` style method which accepts
        the 'nowait' keyword argument. The call is performed as

            ``method(call_id, *args, nowait=True)``

        If the call returns a result, then ``callback(result)`` is
        called. If it raises an exception then ``failback(exc)`` is
        called.

        """
        self._lock.acquire()
        try:
            msg_id = self._next_msg_id
            self._next_msg_id += 1
            if 0 <= self._call_lim <= self._pending:
                self._call_queue.append((method, msg_id, args,
                                         callback, failback))
                return msg_id
            else:
                self._pending += 1
        finally:
            self._lock.release()
        self.__call(method, msg_id, args, callback, failback)
        return msg_id

    def set_limit(self, call_limit):
        """Sets a new call limit for maximum number of pending calls.

        :param call_limit: maximum pending calls
        :type  call_limit: int

        """
        self._lock.acquire()
        try:
            self._call_lim = call_limit
        finally:
            self._lock.release()
        self.__process_queue()

    def __call(self, method, msg_id, args, callback, failback):
        """Internal call execution.

        Caller is responsible for increasing self._pending before calling.

        """
        call = method(msg_id, *args, nowait=True)
        res_cback = lambda res: self.__result_cback(res, msg_id, callback)
        err_cback = lambda res: self.__error_cback(res, msg_id, failback)
        call.add_callpair(res_cback, err_cback)

    def __result_cback(self, value, msg_id, callback=None):
        """Internal callback handling of completed calls."""
        self._lock.acquire()
        try:
            self._pending -= 1
        finally:
            self._lock.release()
        if callback:
            try:
                callback(value)
            except Exception as e:
                _v_silent(e)
        self.__process_queue()

    def __error_cback(self, exc, msg_id, failback=None):
        """Internal callback handling of calls which raised exception."""
        self._lock.acquire()
        try:
            self._pending -= 1
        finally:
            self._lock.release()
        if failback:
            try:
                failback(exc)
            except Exception as e:
                _v_silent(e)
        self.__process_queue()

    def __process_queue(self):
        """Execute all calls which can be activated."""
        calls = deque()
        self._lock.acquire()
        try:
            while ((self._call_lim is None or self._pending < self._call_lim)
                   and self._call_queue):
                calls.append(self._call_queue.popleft())
                self._pending += 1
        finally:
            self._lock.release()

        while calls:
            method, msg_id, args, cback, fback = calls.popleft()
            self.__call(method, msg_id, args, cback. fback)


class VSequenceCallQueue(object):
    """Resolves peer calls in order, enforcing a limit on max parallell calls..

    :param call_lim: maximum pending calls
    :type  call_lim: int

    Resolves calls with an associated call ID in increasing order. It
    is typically used to resolve calls generated by a
    :class:`VSequenceCaller`\ .

    """

    def __init__(self, call_lim):
        self._lim = call_lim
        self._calls = dict()
        self._next_id = 0
        self._lock = threading.Lock()

    def queue(self, call_id, call, args):
        """Queues a call for execution.

        :param call_id: call ID for determining sequence
        :type  call_id: int
        :param call:    call to execute
        :type  call:    callable
        :param args:    arguments to call
        :type  args:    tuple
        :returns:       reference to call result
        :rtype:         :class:`versile.common.pending.VPending`
        :raises:        :exc:`VSequenceCallException`

        The call is resolved when all lower call IDs have been
        resolved. When resolved, the following is executed and the
        result is registered with the returned asynchronous result:

            ``call(*args)``

        If the call limit has been exceeded (i.e. the limit has been
        reached on the number of queued calls but the queue cannot be
        resolved) then an exception is raised.

        """
        self._lock.acquire()
        try:
            if call_id < self._next_id:
                raise VSequenceCallException()
            if self._lim is not None:
                if call_id >= self._next_id + self._lim - len(self._calls):
                    raise VSequenceCallException()
            if call_id in self._calls:
                raise VSequenceCallException()
            result = VPending()
            self._calls[call_id] = (call, args, result)
        finally:
            self._lock.release()

        self.__process_queue()
        return result

    def clear(self):
        """Clears all calls from queue"""
        self._lock.acquire()
        try:
            self._calls.clear()
        finally:
            self._lock.release()

    def __process_queue(self):
        """Assumes caller holds a lock."""
        calls = deque()
        self._lock.acquire()
        try:
            while self._next_id in self._calls:
                calls.append(self._calls.pop(self._next_id))
                self._next_id += 1
        finally:
            self._lock.release()

        while calls:
            call, args, result = calls.popleft()
            try:
                res = call(*args)
            except Exception as e:
                result.failback(e)
            else:
                result.callback(res)


@abstract
class VLinkMonitor(VLockable):
    """Link monitor which attempts to keep a link operating.

    :param hold_gw:       if True hold a reference to peer gateway
    :type  hold_gw:       bool
    :param timeout:       timeout (secs) for establishing new link
    :type  timeout:       float
    :param min_retry_t:   minimum secs before retry setting up link
    :type  min_retry_t:   float
    :param max_retry_t:   maximum secs before retry setting up link
    :type  max_retry_t:   float
    :param retry_backoff: retry time multiplier for each new attempt
    :type  retry_backoff: float
    :param logger:        logger (or None)
    :type  logger:        :class:`versile.common.log.VLogger`

    When the monitor is active it will try to set up and maintain a
    link which is set up by :meth:`_create_link`\ . If setting up the
    link times out or an existing link fails, the link is terminated
    and the monitor tries to set up a new link to replace the timed
    out or failed link.

    When an attempt is made to set up a link and the attempt fails or
    times out, a new attempt is made after a delay, which for the
    first attempt is *min_retry_t*. For each new attempt until a link
    is successfully set up, the retry time is multiplied by
    *retry_backoff*, until it reaches a maximum value of *max_retry_t*
    seconds.

    .. note::

        Control mechanisms such as :class:`VLinkMonitor` are useful
        for operating decentral services which are dispatched through
        a central resource, when availability of the connecting
        network or the peer service is not guaranteed.

    The class is abstract and derived classes must implement
    :meth:`_create_link`\ .

    .. automethod:: _create_link
    .. automethod:: _link_connected
    .. automethod:: _link_lost

    """
    def __init__(self, hold_gw=False, timeout=30, min_retry_t=1,
                 max_retry_t=600, retry_backoff=2.0, logger=None):
        super(VLinkMonitor, self).__init__()

        self._hold_gw = hold_gw
        self._timeout = timeout
        self._min_retry_t = min_retry_t
        self._max_retry_t = max_retry_t
        self._retry_backoff = retry_backoff
        self._logger = logger

        self._retry_t = self._min_retry_t

        self._gw = None                          # Current link's gateway
        self._link = None                        # Current link
        self._link_call = None                   # Current link resolving call
        self._listener = None                    # Link status listener

        self._active = False                     # Link controller is active

        self._timer = None

    def start(self):
        """Starts the monitor and initializes link control.

        If not already running, starting the monitor will cause the
        monitor to initialize a link and start link control.

        """
        with self:
            if not self._active:
                self._log('Starting monitor')
                self._active = True
                self._new_link()

    def stop(self):
        """Stops the monitor and terminates any current link."""
        with self:
            if self._active:
                self._log('Stopping monitor')
                self._active = False
                self._log('Terminating any active link')
                self._terminate_link()

    @abstract
    def _create_link(self):
        """Creates a new link.

        :return: asynchronous call result to a (gateway, link)
        :rtype:  :class:`versile.common.util.VResult`

        The asynchronous call result should throw an exception if link
        setup fails, and when successful it should return as a result
        a tuple of a link gateway object and the connected
        :class:`versile.orb.link.VLink`\ .

        .. note::

            The return values of this method should be similar to
            :meth:`versile.orb.url.VUrl.resolve_with_link`\ .

        """
        raise NotImplementedError

    def _link_connected(self, link, gw):
        """Called internally when a link is connected.

        :param link: connected link
        :type  link: :class:`versile.orb.link.VLink`
        :param gw:   link's peer gateway

        Default does nothing, derived classes can override.

        """

    def _link_lost(self):
        """Called internally when a link is lost.

        Default does nothing, derived classes can override.

        """

    @property
    def link(self):
        """Current link, or None (:class:`versile.orb.link.VLink`\ )"""
        return self._link

    @property
    def peer_gw(self):
        """Peer gateway of currently active link, if held (or None)."""
        return self._gw

    @property
    def logger(self):
        """Logger registered on the monitor (or None)."""
        return self._logger

    def _new_link(self):
        with self:
            self._log('Initiating link')
            # Terminate any old link
            self._terminate_link()

            # Initialize new link
            self._link_call = self._create_link()
            self._link_call.add_callpair(self.__link_result, self.__link_exc)

            # Set a timer for timing out the link
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self._timeout, self.__link_timeout)
            self._timer.start()

    def _terminate_link(self):
        with self:
            self._listener = None
            _link, self._link = self._link, None
            if _link:
                _link.shutdown()
            _link_call, self._link_call = self._link_call, None
            if _link_call:
                _link_call.cancel()
            _timer, self._timer = self._timer, None
            if _timer:
                    _timer.cancel()

    def _running(self, listener):
        with self:
            if listener is self._listener:
                pass

    def _closing(self, listener):
        with self:
            if listener is self._listener:
                pass

    def _closed(self, listener):
        with self:
            if listener is self._listener:
                self._log('Lost current link')
                self._terminate_link()
                self._link_lost()
                if self._active:
                    self._new_link()

    def __link_result(self, result):
        with self:
            self._link_call = None
            if not self._active:
                self._terminate_link()
                return
            _gw, self._link = result
            if self._hold_gw:
                self._gw = _gw
            else:
                self._gw = None
            self._listener = _LinkControlListener(self)
            _timer, self._timer = self._timer, None
            if _timer:
                _timer.cancel()
            self._retry_t = self._min_retry_t
            self._link_connected(self._link, _gw)
        self._link.register_status_listener(self._listener)
        self._log('Link connected')

    def __link_exc(self, exc):
        with self:
            if isinstance(exc, VCancelledResult):
                # Cancelled internally, handled elsewhere
                return
            self._log('Setting up link failed')
            self._link_call = None
            _timer, self._timer = self._timer, None
            if _timer:
                _timer.cancel()
            if self._active:
                self.__schedule_retry()

    def __link_timeout(self):
        with self:
            self._log('Link timeout')

            _timer, self._timer = self._timer, None
            if _timer:
                _timer.cancel()

            _call, self._link_call = self._link_call, None
            if _call:
                _call.cancel()

            if self._active and self._link is None:
                if not self._link_call:
                    self.__schedule_retry()

    def __schedule_retry(self):
        if self._active:
            if self._timer:
                return
            _timer, self._timer = self._timer, None
            if _timer:
                _timer.cancel()
            def retry():
                if self._active and not self._link:
                    self._new_link()
            _retry_t = self._retry_t
            self._retry_t *= self._retry_backoff
            self._retry_t = min(self._retry_t, self._max_retry_t)
            self._timer = threading.Timer(_retry_t, retry)
            self._timer.start()
            self._log('Scheduled retry in %s seconds' % _retry_t)

    def _log(self, msg):
        if self._logger:
            self._logger.debug('VLinkMonitor: %s' % msg)


class _LinkControlListener(object):
    """Listener for the VLinkMonitor class."""
    def __init__(self, controller):
        super(_LinkControlListener, self).__init__()
        self._controller = controller
    def bus_push(self, obj):
        if obj == VLink.STATUS_RUNNING:
            self._controller._running(self)
        elif obj == VLink.STATUS_CLOSING:
            self._controller._closing(self)
        elif obj == VLink.STATUS_CLOSED:
            self._controller._closed(self)
