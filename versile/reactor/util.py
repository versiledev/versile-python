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

"""Reactor framework utility classes."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport
from versile.common.pending import VTimedPending

__all__ = ['VReactorPending']
__all__ = _vexport(__all__)


class VReactorPending(VTimedPending):
    """Pending result which supports 'timeouts'.

    :param reactor: a time reactor

    By supplying a time reactor to :meth:`set_timeout`\ , a timeout
    can be set for the pending object.

    """

    def __init__(self, reactor, result=None):
        super(VReactorPending, self).__init__(result=result)
        self.__reactor = reactor
        self.__timeback = None


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
        if not (self.__cancelled or self._timed_out):
            if self.__timeback:
                self.__timeback.reset_if_earlier(seconds)
            else:
                callback = self.__timeout_callback
                self.__timeback = self.__reactor.schedule(seconds, callback)

    def cancel_timeout(self):
        """Cancels a timeout which has been set and is currently active.

        Cancels a timeout set with :meth:`set_timeout`

        """
        if self.__timeback:
            self.__timeback.cancel()
            self.__timeback = None

    @property
    def timeout(self):
        """Reference to a timeout which has been set.

        When a timeout has been set and has not expired or been
        cancelled, this property holds a :class:`VScheduledCall` which
        references the timeout. It can be used to e.g. reset the
        timer.

        """
        return self.__timeback

    def cancel(self):
        """Cancels the callback/failback processing chain.

        See :meth:`versile.common.pending.VPending`\ . Also cancels
        any timeout set on the object.

        """
        self.cancel_timeout()
        super(VReactorPending, self).cancel()

    def __timeout_callback(self):
        self._timed_out = True
        self.__timeback = None
        if not self.__cancelled:
            self.cancel()
