.. _lib_reactor:

Reactor Framework
=================

This is the API documentation for the :mod:`versile.reactor` framework
for :term:`Reactor Pattern` based processing.

Reactors
--------
.. currentmodule:: versile.reactor

A reactor runs as a single thread, detecting events and dispatching to
handlers for those events. It is in many ways similar to an 'event
loop' type framework. The module :mod:`versile.reactor` defines a
interfaces for reactor implementations, including:

+------------------------------+-----------------------------------+
| Interface                    | Description                       |
+==============================+===================================+
| :class:`IVCoreReactor`       | Base start/stop functionality     |
+------------------------------+-----------------------------------+
| :class:`IVDescriptorReactor` | Event handling for descriptor I/O |
+------------------------------+-----------------------------------+
| :class:`IVTimeReactor`       | Timers for scheduled events       |
+------------------------------+-----------------------------------+

:term:`VPy` implements a set of reactors based on
:func:`select.select` and similar mechanisms for monitoring events on
file descriptors. Some reactors use monitoring subsystems which are
not available on all operating systems, so all reactors are not
available on all platforms. Implemented reactors (depending on
platform) includes:

+-----------------------------------------------+-----------------------------+
| Reactor                                       | Subsystem                   |
+===============================================+=============================+
| :class:`versile.reactor.quick.VSelectReactor` | :func:`select.select`       |
+-----------------------------------------------+-----------------------------+
| :class:`versile.reactor.quick.VPollReactor`   | :func:`select.poll`         |
+-----------------------------------------------+-----------------------------+
| :class:`versile.reactor.quick.VEpollReactor`  | :func:`select.epoll`        |
+-----------------------------------------------+-----------------------------+
| :class:`versile.reactor.quick.VKQueueReactor` | :func:`select.kqueue`       |
+-----------------------------------------------+-----------------------------+

The module :mod:`versile.reactor.quick` provides a convenient
mechanism for creting a reactor class. It exports only those reactor
implementations which are available the platform, and it exports one
of the available reactors as :class:`versile.reactor.quick.VReactor`
(using the fastest available I/O subsystem).

Starting and stopping a reactor
-------------------------------

A reactor can be started via :meth:`IVCoreReactor.run` which yields
control of the thread to the reactor. The method does not return until
reactor is stopped, typically that the reactor stopt itself by calling
:meth:`IVCoreReactor.stop`.

Below is an example of starting a reactor. Notice we use a callback to
request that the reactor should stop immediately after starting
(otherwise it would never return as we have not registered any events
the reactor should listen for).

>>> from versile.reactor.quick import VReactor
>>> reactor = VReactor()
>>> def stop_after_starting():
...     reactor.stop()
... 
>>> call = reactor.call_when_running(stop_after_starting)
>>> type(call)
<class 'versile.reactor.VScheduledCall'>
>>> reactor.run()

Reactors inherit :class:`threading.Thread` and can also be executed as
a thread by calling :meth:`threading.Thread.start`\ .

.. warning::

   Reactor thread execution is not thread-safe. Code executed by the
   reactor thread is free to assume it has full control of its
   execution context. This is the standard pattern for a reactor
   framework, otherwise asynchronous reactor programming would become
   incredibly complex. When other threads are running in parallell
   with the reactor (which is typically the case when operating
   :term:`VOL` links), those threads are responsible for
   de-conflicting with the reactor thread.

A key mechanism for other threads to de-conflict from the reactor
thread is to make the reactor execute the possibly conflicting code,
by passing a function to the reactor's thread-safe
:class:`IVTimeReactor.execute` method.

Another thread-safe reactor method is :meth:`IVCoreReactor.stop` which
enables other threads a mechanism to stop the reactor. Below is
example code which starts a reactor and then waits 0.01 seconds before
it (externally) shutting down the reactor.

>>> import time
>>> from versile.reactor.quick import VReactor
>>> reactor = VReactor()
>>> reactor.start()
>>> time.sleep(0.01)
>>> reactor.stop()

Scheduling calls
----------------

Calls can be scheduled for execution by using the reactor's
:class:`IVTimeReactor` interface. Below is an example of a reactor
which is scheduled to print a statement after (minimum) 0.01 seconds.

>>> import time
>>> from versile.reactor.quick import VReactor
>>> reactor = VReactor()
>>> reactor.start()
>>> def printer(n):
...   print('The number is', n)
... 
>>> call = reactor.schedule(0.01, printer, 42)
>>> type(call)
<class 'versile.reactor.VScheduledCall'>
>>> time.sleep(0.1) #Below output is from signal_result while mainthread sleeps
('The number is', 42)
>>> reactor.stop()

Notice that :meth:`IVTimeReactor.schedule` returns an object which is
a reference to the scheduled call. This object can be used to
e.g. cancel or delay the call.

Asynchronous Calls
------------------
.. currentmodule:: versile.common.pending

The reactor runs in a single thread responding to events as they
arrive before moving on to the next event. If the processing of a
single event takes too long or blocks then everything else gets
delayed. Avoiding time-consuming event processing should be dealt with
by designing event handlers so they execute in a reasonably short
amount of time. The second is more tricky as it requires a mechanism
for functions to return before their result is available.

In order to enable a function to return before its result is ready the
:mod:`versile.common.pending` module can be used. Below is an example
how a scheduled function signal_result uses a :class:`VPending` object
to pass a result, and how another method async_result is set up to
receive the result when it becomes available.

>>> import time
>>> from versile.reactor.quick import VReactor
>>> from versile.common.pending import VPending
>>> reactor = VReactor()
>>> reactor.start()
>>> async_result = VPending()
>>> def printer(n):
...     print('The number is', n)
... 
>>> async_result.add_callback(printer)
>>> def signal_result(n, pending):
...     pending.callback(n)
... 
>>> call = reactor.schedule(0.01, signal_result, 2, async_result)
>>> type(call)
<class 'versile.reactor.VScheduledCall'>
>>> time.sleep(0.1)# Below output is from signal_result while mainthread sleeps
('The number is', 2)
>>> reactor.stop()

In th above example the :class:`VPending` result object is used in an
"inverse direction". Normally rather than passing it as an argument it
is the return value of a function, and the receiver registers a
handler for processing the result when it is available.

Reactor I/O
-----------
.. currentmodule:: versile.reactor

Handlers for I/O events can be registered with the reactor through its
:class:`IVDescriptorReactor` interface. Handlers must implement
:class:`versile.reactor.io.IVByteHandleInput` for reading and must
implement :class:`versile.reactor.io.IVByteHandleOutput`\ for
writing. Also, as the implemented reactors rely on
:func:`select.select` or similar mechanisms to detect I/O events,
handlers must implement :class:`versile.reactor.io.IVSelectable`\ .

Input and output handlers can be registered with the reactor by using
the :meth:`IVDescriptorReactor.add_reader` and
:meth:`IVDescriptorReactor.add_writer` methods. They can be removed
from the reactor event loop by calling
:meth:`IVDescriptorReactor.remove_reader` or
:meth:`IVDescriptorReactor.remove_writer`\ .

Below is a simple example which uses higher-level I/O component to
register a socket with the reactor, and a byte I/O agent which
processes socket data. The components register themselves with the
reactor when the appropriate events occur, which is why there is no
explicit calls to add_reader or add_writer.

>>> import socket
>>> from versile.common.peer import VSocketPeer
>>> from versile.common.util import VByteBuffer, VCondition
>>> from versile.reactor.quick import VReactor
>>> from versile.reactor.io.sock import VClientSocketAgent
>>> from versile.reactor.io import VByteWAgent, VIOControl
>>> reactor = VReactor()
>>> reactor.start()
>>> class SimpleAgent(VByteWAgent):
...     def __init__(self, reactor):
...         super(SimpleAgent, self).__init__(reactor)
...         self.cond = VCondition()
...         self.msg = VByteBuffer()
...     def _consumer_control(self):
...         agent = self
...         class _Control(VIOControl):
...             def connected(self, peer):
...                 agent.write(b'GET / HTTP/1.1\r\nHost: www.w3.org\r\n\r\n')
...         return _Control()
...     def _data_received(self, data):
...         self.msg.append(data)
...         return len(data)
...     def _data_ended(self, clean):
...         with self.cond:
...             self.cond.notify_all()
...         self.reactor.stop()
... 
>>> sock = VClientSocketAgent(reactor)
>>> agent = SimpleAgent(reactor)
>>> sock.byte_io.attach(agent.byte_io)
>>> peer = VSocketPeer.lookup('www.w3.org', 80, socktype=socket.SOCK_STREAM)
>>> sock.connect(peer)
>>> with agent.cond:
...      agent.cond.wait()
...
>>> print(agent.msg.peek(22)) #doctest: +NORMALIZE_WHITESPACE
HTTP/1.1 200 OK
Date:

For information about higher level components which can be registered
with a reactor I/O event loop see :ref:`lib_reactor_io`\ .

.. note::
   
   A program should normally use the higher level
   :ref:`lib_reactor_io` components instead of working directly with
   reactor descriptor event handlers. This avoids cumbersome low-level
   I/O handling and creates more portable and reusable code.

Logging
-------

A reactor provides a logger as :class:`IVCoreReactor.log`\ . The
logger should be an instance of :class:`versile.common.log.VLogger`\ .

Below is an example how the logger can be used. Normally just calling
:meth:`versile.reactor.waitr.VFDWaitReactor.set_default_log_watcher`
without arguments is sufficient to set up a default console logger. In
this example we have included additional additional overhead to create
a custom log formatter, and used reactor scheduling to execute a
complete code example with deterministic output.

>>> # Set up a custom logger which does not include timestamp     
... from __future__ import print_function, unicode_literals
>>> import time
>>> from versile.reactor.quick import VReactor
>>> from versile.common.log import VConsoleLog, VLogWatcher
>>> class MyLogWatcher(VLogWatcher):
...     def _watch(self, log_entry):
...         print('%s %s' % (log_entry.lvl, log_entry.msg))
... 
>>> # Log an example log message
... reactor = VReactor()
>>> logger = reactor.log
>>> logger.add_watcher(MyLogWatcher())
>>> reactor.start()
>>> call = reactor.schedule(0.01, logger.log, u'No soup for you!', logger.INFO)
>>> time.sleep(0.1)
20 No soup for you!
>>> reactor.stop()

For more information about logging see :mod:`versile.common.log`\ .

Module APIs
-----------

Reactors
........
Module API for :mod:`versile.reactor`

.. automodule:: versile.reactor
    :members:
    :show-inheritance:

Quick Reactors
..............
Module API for :mod:`versile.reactor.quick`

.. automodule:: versile.reactor.quick
    :members:
    :show-inheritance:

Utility Classes
...............
Module API for :mod:`versile.reactor.util`

.. automodule:: versile.reactor.util
    :members:
    :show-inheritance:

Wait Reactors
..............
Module API for :mod:`versile.reactor.waitr`

.. automodule:: versile.reactor.waitr
    :members:
    :show-inheritance:
