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

"""Various debugging functions."""
from __future__ import print_function, unicode_literals

import code
import inspect
import logging
import signal
import sys
import threading
import traceback

from versile.internal import _vexport

__all__ = ['debug_to_console', 'debug_to_file', 'debug_to_watcher',
           'disable_debugging', 'critical', 'warn', 'error', 'info',
           'debug', 'ldebug', 'log_thread', 'log_lock', 'console',
           'stack_all', 'print_trace', 'debug_trace', 'print_etrace',
           'debug_etrace', 'sigusr1', 'LOG_LVL_THREAD', 'LOG_LVL_LOCK',
           'DEBUG', 'WARN', 'CRITICAL', 'ERROR', 'LDEBUG',
           'DEBUG_TRACE', 'DEBUG_ETRACE']
__all__ = _vexport(__all__)


"""Custom log level for thread-operation level logging"""
LOG_LVL_THREAD = 8

"""Custom log level for lock-level logging"""
LOG_LVL_LOCK = 6

logging.addLevelName(LOG_LVL_THREAD, 'THREAD')
logging.addLevelName(LOG_LVL_LOCK, 'LOCK')

"""Debug Logger."""
debug_log = None
__debug_lock = threading.RLock()


def debug_to_console(lvl=None, formatter=None):
    """Add debug logging to the console.

    :param lvl:       debug level to log
    :type  lvl:       int
    :param formatter: formatter for log entries
    :type  formatter: :class:`versile.common.log.VLogEntryFormatter`

    Will only add console logging if :func:`debug_to_console`\
    :func:`debug_to_file` or :func:`debug_to_watcher` has not already
    been called.

    """
    global debug_log
    global __debug_lock
    with __debug_lock:
        if not debug_log:
            from versile.common.log import VLogger, VConsoleLog
            from versile.common.log import VLogEntryFormatter
            debug_log = VLogger()
            if formatter is None:
                formatter = VLogEntryFormatter()
            watcher = VConsoleLog(formatter=formatter)
            if lvl is not None:
                class Filter(VLogEntryFilter):
                    def keep_entry(self, log_entry):
                        return (log_entry.lvl >= lvl)
                watcher.add_watch_filter(Filter())
            debug_log.add_watcher(watcher)

def debug_to_file(filename, mode='wb', lvl=None, formatter=None):
    """Add debug logging to a file.

    :param filename:  name of file to log to
    :param mode:      file open mode
    :param lvl:       debug level to log
    :type  lvl:       int
    :param formatter: formatter for debug log entries
    :type  formatter: :class:`versile.common.log.VLogEntryFormatter`

    Will only add console logging if :func:`debug_to_console`\
    :func:`debug_to_file` or :func:`debug_to_watcher` has not already
    been called.

    """
    global debug_log
    global __debug_lock
    with __debug_lock:
        if not debug_log:
            from versile.common.log import VLogger, VFileLog
            from versile.common.log import VLogEntryFormatter
            debug_log = VLogger()
            if formatter is None:
                formatter = VLogEntryFormatter()
            watcher = VFileLog(open(filename, mode), formatter=formatter)
            if lvl is not None:
                class Filter(VLogEntryFilter):
                    def keep_entry(self, log_entry):
                        return (log_entry.lvl >= lvl)
                watcher.add_watch_filter(Filter())
            debug_log.add_watcher(watcher)

def debug_to_watcher(watcher):
    """Add debug logging to a log watcher.

    :param watcher:  log watcher to log to
    :type  watcher:  :class:`versile.common.log.VLogWatcher`

    Will only add console logging if :func:`debug_to_console`\
    :func:`debug_to_file` or :func:`debug_to_watcher` has not already
    been called.

    """
    global debug_log
    global __debug_lock
    with __debug_lock:
        if not debug_log:
            from versile.common.log import VLogger
            debug_log = VLogger()
            debug_log.add_watcher(watcher)

def disable_debugging():
    """Disables any debugging by removing the debug logger."""
    global debug_log
    global __debug_lock
    with __debug_lock:
        debug_log = None

def critical(*arg):
    """Log critical error message."""
    global debug_log
    global __debug_lock
    with __debug_lock:
        if debug_log:
            l = [unicode(s) for s in arg]
            msg = ' '.join(l)
            debug_log.critical(msg)

def warn(*arg):
    """Log warning."""
    global debug_log
    global __debug_lock
    with __debug_lock:
        if debug_log:
            l = [unicode(s) for s in arg]
            msg = ' '.join(l)
            debug_log.warn(msg)

def error(*arg):
    """Log error message."""
    global debug_log
    global __debug_lock
    with __debug_lock:
        if debug_log:
            l = [unicode(s) for s in arg]
            msg = ' '.join(l)
            debug_log.error(msg)

def info(*arg):
    """Log info message."""
    global debug_log
    global __debug_lock
    with __debug_lock:
        if debug_log:
            l = [unicode(s) for s in arg]
            msg = ' '.join(l)
            debug_log.info(msg)

def debug(*arg):
    """Log debug message."""
    global debug_log
    global __debug_lock
    with __debug_lock:
        if debug_log:
            l = [unicode(s) for s in arg]
            msg = ' '.join(l)
            debug_log.debug(msg)

def ldebug(*arg):
    """Log debug message with source linenumber."""
    lineno = inspect.currentframe().f_back.f_lineno
    debug('%4i:' % lineno, *arg)

def log_thread(msg, log_name, data=None):
    """Log thread-level debug message."""
    global debug_log
    global __debug_lock
    with __debug_lock:
        if debug_log:
            if data is not None:
                s = ' | '.join(('N/A', msg, log_name, str(data)))
            else:
                s = ' | '.join(('N/A', msg, log_name))
            debug_log.log(LOG_LVL_THREAD, s)

def log_lock(typ, msg, log_name, data=None):
    """Log lock-level debug message."""
    global debug_log
    global __debug_lock
    with __debug_lock:
        if debug_log:
            if data:
                s = ' | '.join((typ, msg, log_name, data))
            else:
                s = ' | '.join((typ, msg, log_name))
            debug_log.log(LOG_LVL_LOCK, s)

def console(local=None, msg=None):
    """Launch an interactive console with message."""
    if msg is None:
        msg = ''
    if local:
        code.InteractiveConsole(local).interact(msg)
    else:
        code.InteractiveConsole().interact(msg)

def stack_all():
    """Return a string with a stack trace of all threads."""
    trace = []
    for threadId, stack in sys._current_frames().items():
        trace.append('Stack trace ThreadID: %s\n' % threadId)
        for fname, lineno, name, line in traceback.extract_stack(stack):
            trace.append('File: "%s", line %d, in %s\n' %
                         (fname, lineno, name))
            if line:
                trace.append("  %s\n" % (line.strip()))
        trace.append('\n')
    return ''.join(trace)

def print_trace():
    """Print a stack trace."""
    traceback.print_stack()

def debug_trace():
    """Print a stack trace if debugging is on."""
    global __logging
    if __logging:
        print_trace()

def print_etrace():
    """Prints an exception stack trace."""
    traceback.print_exc()

def debug_etrace():
    """Print an exception stack trace if debugging is on."""
    global __logging
    if __logging:
        print_etrace()

def sigusr1(trace=True):
    """Register a signal to open an interactive console on SIGUSR1."""
    def debug(sig, frame):
        d={'_frame':frame}
        d.update(frame.f_globals)
        d.update(frame.f_locals)

        if trace:
            console(d, stack_all())
        else:
            console(d)
    signal.signal(signal.SIGUSR1, debug)

# Capitalized aliases for functions
CRITICAL = critical
WARN = warn
ERROR = error
INFO = info
DEBUG = debug
LDEBUG = ldebug
DEBUG_TRACE = debug_trace
DEBUG_ETRACE = debug_etrace
