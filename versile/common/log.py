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

"""Logging framework with logging related classes."""
from __future__ import print_function, unicode_literals

import copy
import logging
import sys
import time
import traceback

from versile.internal import _vexport, _pyver, _v_silent
from versile.common.iface import abstract
from versile.common.util import VLockable

__all__ = ['VLogEntry', 'VLogEntryFormatter', 'VLogEntryFilter',
           'VLogWatcher', 'VLogger', 'VFileLog', 'VConsoleLog']
__all__ = _vexport(__all__)


class VLogEntry(object):
    """A log entry.

    :param msg:     log entry message
    :type  msg:     unicode
    :param lvl:     log level
    :type  lvl:     int
    :param prefix:  prefix for the log message (or None)
    :type  prefix:  unicode
    :param tstamp:  a timestamp for the log entry (time.time() format)
    :type  tstamp:  float

    """

    def __init__(self, msg, lvl, prefix=None, tstamp=None):
        if not isinstance(msg, (unicode, bytes)):
            raise TypeError('Message must be unicode [or bytes]')
        if prefix and not isinstance(prefix, (unicode, bytes)):
            raise TypeError('When set, prefix must be unicode [or bytes]')
        if isinstance(msg, bytes):
            # Unknown encoding, convert to 'repr' representation
            msg = unicode(repr(msg)[1:-1])
        if prefix and isinstance(prefix, bytes):
            # Unknown encoding, convert to 'repr' representation
            prefix = unicode(repr(prefix)[1:-1])
        self.__msg = msg
        self.__lvl = lvl
        self.__prefix = prefix
        if tstamp is None:
            self.__tstamp = time.time()
        else:
            self.__tstamp = tstamp

    @property
    def msg(self): return self.__msg
    """Log entry message"""

    @property
    def tstamp(self): return self.__tstamp
    """Log entry timestamp"""

    @property
    def lvl(self): return self.__lvl
    """Log entry's log level"""

    @property
    def prefix(self): return self.__prefix
    """Log entry's specified prefix (or None)"""


class VLogEntryFormatter(object):
    """Formatter for converting log entries into unicode strings.

    .. automethod:: _protect

    """

    def format_entry(self, log_entry):
        """Formats a log entry, returning a unicode representation.

        :param log_entry: the log entry
        :type  log_entry: :class:`VLogEntry`
        :returns:         a unicode representation
        :rtype:           unicode

        """
        sub = [time.strftime('%H:%M:%S', time.localtime(log_entry.tstamp))]
        # sub = [time.strftime('%Y-%m-%d-%H-%M-%S',
        #                      time.localtime(log_entry.tstamp))]
        sub.append('%i' % log_entry.lvl)
        if log_entry.prefix:
            prefix = self._protect(log_entry.prefix, escape='\\') + ': '
        else:
            prefix = ''
        msg = prefix + self._protect(log_entry.msg, escape='\\') + '\r\n'
        sub.append(msg)
        return ' '.join(sub)

    def _protect(self, msg, escape=None):
        """Returns a string which does not break any newlines.

        :param msg:    message to protect
        :type  msg:    unicode
        :param escape: escape character, or None
        :type  excape: unicode

        If escape is not None, it should be a unicode character which
        is used to escape unsafe characters which are removed. The escape
        character will also escape itself.

        """
        if escape:
            msg = msg.replace(escape, 2*escape)
            msg = msg.replace('\r', escape + 'r')
            msg = msg.replace('\n', escape + 'n')
        else:
            msg = msg.replace('\r', '')
            msg = msg.replace('\n', '')
        return msg

class VLogEntryFilter(VLockable):
    """Filter for log entries."""

    def __init__(self):
        super(VLogEntryFilter, self).__init__()

    @abstract
    def keep_entry(self, log_entry):
        """Returns True if entry should be retained.

        :param log_entry: the log entry to filter
        :type  log_entry: :class:`VLogEntry`
        :returns:         True if log entry should be retained
        :rtype:           bool

        Default returns True, derived classes can override.

        """
        return True


@abstract
class VLogWatcher(VLockable):
    """Base class for receiving log entries from a logger.

    Typically performs end-point processing of a log entry, such as
    writing to disk or writing to a console.

    .. note::

        This class is abstract and should not be directly instantiated.

    .. automethod:: _watch

    """
    def __init__(self):
        super(VLogWatcher, self).__init__()
        self.__log_filters = set()

    def watch(self, log_entry):
        """Receive a log entry from a logger.

        :param log_entry: received log entry
        :type  log_entry: :class:`VLogEntry`

        Calls :meth:`_watch` internally to process a log entry after
        filtering.

        """
        with self:
            for log_filter in self.__log_filters:
                if not log_filter.keep_entry(log_entry):
                    return
            self._watch(log_entry)

    def _watch(self, log_entry):
        """Processes a received log entry after filtering.

        :param log_entry: a log entry
        :type  log_entry: :class:`VLogEntry`

        Called by :meth:`watch` internally to process a log entry
        after filtering. Default does nothing, derived classes should
        override.

        """
        pass

    def add_watch_filter(self, log_filter):
        """Add a filter for log entries.

        :param log_filter: log entry filter
        :type  log_filter: :class:`VLogEntryFilter`

        """
        with self:
            self.__log_filters.add(log_filter)

    def remove_watch_filter(self, log_filter):
        """Remove a filter for log entries.

        :param log_filter: log entry filter
        :type  log_filter: :class:`VLogEntryFilter`

        """
        with self:
            self.__log_filters.discard(log_filter)


class VLogger(VLogWatcher):
    """A logger which can accept log messages.

    New log entries are passed to connected :class:`VLogWatcher`
    objects which have been registered on the logger. A logger is also
    itself a :class:`VLogWatcher` and can be set up to receive log
    entries from another logger.

    :param prefix:  default prefix for log messages
    :type  prefix:  unicode
    :param logging: if True then the logging is enabled
    :type  logging: bool

    """

    # Setting constants here so no need to reference logging module
    CRITICAL = logging.CRITICAL
    """Log level for 'critical' level"""
    ERROR    = logging.ERROR
    """Log level for 'error' level"""
    WARN     = logging.WARN
    """Log level for 'warn' level"""
    INFO     = logging.INFO
    """Log level for 'info' level"""
    DEBUG    = logging.DEBUG
    """Log level for 'debug' level"""

    def __init__(self, prefix=None, logging=True):
        super(VLogger, self).__init__()
        self.__log_watchers = set()
        self.__log_filters = set()
        self.__logging = logging
        self.__default_prefix = prefix

    def create_proxy_logger(self, prefix=None, logging=True):
        """Creates a logger with this log set up as a watcher.

        :returns: logger
        :rtype:   :class:`VLogger`

        For other arguments see :class:`VLogger` construction.

        """
        logger = VLogger(prefix=prefix, logging=logging)
        logger.add_watcher(self)
        return logger

    def start_logging(self):
        """Starts log processing.

        If the logger has not been started, received log entries are
        ignored.

        """
        with self:
            self.__logging = True

    def stop_logging(self):
        """Stops log processing.

        If the logger has not been started, received log entries are
        ignored.

        """
        with self:
            self.__logging = False

    def log(self, message, lvl, prefix=None, tstamp=None):
        """Logs a log entry.

        :param message: message to log
        :type  message: unicode
        :param lvl:     log level
        :type  lvl:     int
        :param prefix:  prefix for the log message (or None)
        :type  prefix:  unicode
        :param tstamp:  timestamp for the log entry (time.time() format)
        :type  tstamp:  float

        *lvl* should be an integer conforming to the logging module
        format, e.g. utilize constants such as :attr:`VLogger.INFO`\ .

        """
        with self:
            prefix = self.__prefix(prefix)
            log_entry = VLogEntry(message, lvl, prefix=prefix, tstamp=tstamp)
            self._watch(log_entry)

    def log_trace(self, lvl, prefix=None, tstamp=None):
        """Log an exception trace of a current exception.

        :param lvl:     log level
        :type  lvl:     int
        :param prefix:  prefix for the log message (or None)
        :type  prefix:  unicode
        :param tstamp:  a timestamp for the log entry (time.time() format)
        :type  tstamp:  float

        Generates a series of messages which have information about
        the exception, and submits them individually via :meth:`log`\

        """
        prefix = self.__prefix(prefix)
        exc_type, exc_value, exc_traceback = sys.exc_info()
        trace = traceback.extract_tb(exc_traceback)
        msg_list = ['Traceback (most recent call last):']
        for filename, lineno, funcname, text in trace:
            msg = '  File \"%s\", %i, in %s' % (filename, lineno, funcname)
            msg_list.append(msg)
        msg_list.append(repr(exc_value))
        for msg in msg_list:
            self.log(msg, lvl=lvl, prefix=prefix, tstamp=tstamp)

    def critical(self, message, prefix=None, tstamp=None):
        """Log a message with :attr:`VLogger.CRITICAL` lvl.

        For other arguments see :meth:`log`\ .

        """
        prefix = self.__prefix(prefix)
        self.log(message, self.CRITICAL, prefix=prefix, tstamp=tstamp)

    def warn(self, message, prefix=None, tstamp=None):
        """Log a message with :attr:`VLogger.WARN` lvl.

        For other arguments see :meth:`log`\ .

        """
        prefix = self.__prefix(prefix)
        self.log(message, self.WARN, prefix=prefix, tstamp=tstamp)

    def error(self, message, prefix=None, tstamp=None):
        """Log a message with :attr:`VLogger.ERROR` lvl.

        For other arguments see :meth:`log`\ .

        """
        prefix = self.__prefix(prefix)
        self.log(message, self.ERROR, prefix=prefix, tstamp=tstamp)

    def info(self, message, prefix=None, tstamp=None):
        """Log a message with :attr:`VLogger.INFO` lvl.

        For other arguments see :meth:`log`\ .

        """
        prefix = self.__prefix(prefix)
        self.log(message, self.INFO, prefix=prefix, tstamp=tstamp)

    def debug(self, message, prefix=None, tstamp=None):
        """Log a message with :attr:`VLogger.DEBUG` lvl.

        For other arguments see :meth:`log`\ .

        """
        prefix = self.__prefix(prefix)
        self.log(message, self.DEBUG, prefix=prefix, tstamp=tstamp)

    def add_watcher(self, log_watcher):
        """Add a watcher to the logger.

        :param log_watcher: log watcher to add
        :type  log_watcher: :class:`VLogWatcher`

        Attached log watchers receive log entries from the logger when
        the logger is active (i.e. started).

        """
        with self:
            self.__log_watchers.add(log_watcher)

    def remove_watcher(self, log_watcher):
        """Remove a watcher from the the logger.

        :param log_watcher: log watcher to remove
        :type  log_watcher: :class:`VLogWatcher`

        """
        with self:
            self.__log_watchers.discard(log_watcher)

    def add_filter(self, log_filter):
        """Add a filter to the logger.

        :param log_filter: the filter to add
        :type  log_filter: :class:`VLogEntryFilter`

        Log entries which are evaluated as False by one of the
        attached filters, are dropped without being passed to a
        watcher.

        """
        with self:
            self.__log_filters.add(log_filter)

    def remove_filter(self, log_filter):
        """Removes a filter from the logger.

        :param log_filter: filter to remove
        :type  log_filter: :class:`VLogEntryFilter`

        """
        with self:
            self.__log_filters.discard(log_filter)

    @property
    def logs(self): return copy.copy(self.__logs)
    """Log watchers registered on this logger"""

    @property
    def logging(self): return self.__logging
    """True if logger is started, or False if it is stopped."""

    def _watch(self, log_entry):
        with self:
            for log_filter in self.__log_filters:
                if not log_filter.keep_entry(log_entry):
                    return
            for log_watcher in self.__log_watchers:
                log_watcher.watch(log_entry)

    def __prefix(self, prefix):
        if prefix:
            return prefix
        else:
            return self.__default_prefix


class VFileLog(VLogWatcher):
    """Log watcher which logs to a file.

    :param f:         file object which is open for writing
    :type  f:         file
    :param formatter: unicode formatter for log entries
    :type  formatter: :class:`VLogEntryFormatter`
    :param encoding:  string encoding for writing to file
    :type  encoding:  bytes

    """

    def __init__(self, f, formatter, encoding='utf8'):
        super(VFileLog, self).__init__()
        self.__file = f
        self.__formatter = formatter
        self.__encoding = encoding

    def _watch(self, log_entry):
        msg = self.__formatter.format_entry(log_entry)
        # ISSUE - the .encode() step has some times been observed to
        # block without throwing exceptions, even though input is
        # valid. Suspect there is a threading issue involving GIL
        data = msg.encode(self.__encoding)
        self.__file.write(data)
        try:
            self.__file.flush()
        except AttributeError as e:
            # Some sandbox environments provide a file-like object for
            # writing which provides write() but not flush(), if flush()
            # is not available we just ignore it
            _v_silent(e)

    @property
    def formatter(self): return self.__formatter


class VConsoleLog(VFileLog):
    """Log watcher which logs input to sys.stderr.

    :param formatter: a unicode formatter for log entries
    :type  formatter: :class:`VLogEntryFormatter`

    """

    def __init__(self, formatter):
        if _pyver == 2:
            super(VConsoleLog, self).__init__(sys.stderr, formatter)
        else:
            # Ref http://bugs.python.org/issue4571 for python3
            super(VConsoleLog, self).__init__(sys.stderr.buffer, formatter)
