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

""".. Reactor logger."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport
from versile.common.log import VLogger

__all__ = ['VReactorLogger']
__all__ = _vexport(__all__)


class VReactorLogger(VLogger):
    """Logger which executes in the reactor's event loop."""

    def __init__(self, reactor, prefix=None, logging=True):
        """

        prefix  - default prefix for log messages without explicit prefix
        logging - if True then the logger is started with logging enabled

        """
        super(VReactorLogger, self).__init__(prefix=prefix, logging=logging)
        self.__reactor = reactor

    def create_proxy_logger(self, prefix=None, logging=True):
        logger = VReactorLogger(self.__reactor, prefix=prefix, logging=logging)
        logger.add_watcher(self)
        return logger

    def log(self, message, lvl, prefix=None, tstamp=None):
        """

        message and prefix (if any) should be unicode, or will be
        converted to unicode

        lvl should be an integer conforming to the logging module
        format, e.g. utilize constants such as logging.INFO

        """
        call = super(VReactorLogger, self).log
        self.__reactor.schedule(0, call, message, lvl, prefix, tstamp)

    def add_watcher(self, log_watcher):
        call = super(VReactorLogger, self).add_watcher
        self.__reactor.schedule(0, call, log_watcher)

    def remove_watcher(self, log_watcher):
        call = super(VReactorLogger, self).discard_watcher
        self.__reactor.schedule(0, call, log_watcher)

    def add_filter(self, log_filter):
        call = super(VReactorLogger, self).add_filter
        self.__reactor.schedule(0, call, log_filter)

    def remove_filter(self, log_filter):
        call = super(VReactorLogger, self).remove_filter
        self.__reactor.schedule(0, call, log_filter)
