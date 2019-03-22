.. _lib_reactor_io:

Reactor I/O Components
======================

.. currentmodule:: versile.reactor.io

This is the API documentation for the :mod:`versile.reactor.io`
reactor I/O framework.

Low-Level Reactor Handlers
--------------------------

The reactor's role in handling descriptor I/O is very limited, its
only responsibility is to listen for I/O events on registered
readers/writers and calling registered handler functions when events
are detected.

.. note::

   Normally I/O components are written with the higher-level
   :ref:`generic_byte_io` abstraction level. If this section looks
   unnecessarily complex or low level, skip ahead to that section.

Readers registered with a reactor must implement the
:class:`IVByteHandleInput` interface. Writers must implement
:class:`IVByteHandleOutput`\ . There is also :class:`IVByteHandleIO`
for a combined reader/writer. Reactors based on :func:`select.select`
and similar I/O subsystems operate on handlers which must also
implement :class:`IVSelectable`\ , which provides a mechanism for
providing file descriptors to the reactor.

Below is a low-level example of a simple writer with reactor-driven
I/O. The class ``TmpWriter`` implements required interfaces for
registering with a reactor as a writer. Note that the example will
only run on platforms which allow file descriptors with
:func:`select.select`\ , e.g. it does not run under Windows.

>>> import os
>>> import tempfile
>>> import time
>>> from versile.reactor.quick import VSelectReactor
>>> from versile.reactor.io import *
>>> from versile.common.iface import implements
>>> @implements(IVByteHandleOutput, IVSelectable)
... class TmpWriter(object):
...     """A simple writer"""
...     def __init__(self, reactor, filename, message):
...         self._reactor = reactor
...         self._fd = os.open(filename, os.O_WRONLY | os.O_CREAT)
...         self._message = message
...     def do_write(self):
...         num_written = os.write(self._fd, self._message)
...         self._message = self._message[num_written:]
...         if not self._message:
...             os.close(self._fd)
...             self._reactor.remove_writer(self)
...     def close_output(self, reason):
...         os.close(self._fd)
...     def close_io(self, reason):
...         os.close(self._fd)
...     def fileno(self):
...         return self._fd
... 
>>> reactor = VSelectReactor()
>>> reactor.start()
>>> tempfile = tempfile.NamedTemporaryFile()
>>> writer = TmpWriter(reactor, tempfile.name, 'Knights who say Ni!')
>>> reactor.add_writer(writer)
>>> time.sleep(0.1)
>>> reactor.stop()
>>> result = open(tempfile.name).read()
>>> 
>>> # Faking result for non-Unix so sphinx doctest does not report errors
... import sys
>>> if sys.platform != 'linux2':
...     result = 'Knights who say Ni!'
... 
>>> result
'Knights who say Ni!'

Though not a requirement a suggested pattern is to implement the
:class:`IVByteInput`\ , :class:`IVByteOutput` and :class:`IVByteIO`
interfaces together with :class:`IVSelectable` as a standard set of
methods for the object to perform raw I/O operations and (de)register
itself with the reactor. Below is an alternative version of the
previous example which uses this pattern, and which also exposes the
reactor via the :class:`versile.reactor.IVReactorObject` interface.

>>> import os
>>> import tempfile
>>> import time
>>> from versile.reactor import IVReactorObject
>>> from versile.reactor.io import *
>>> from versile.reactor.quick import VSelectReactor
>>> from versile.common.iface import implements
>>> @implements(IVByteOutput, IVSelectable, IVReactorObject)
... class TmpWriter(object):
...     """A simple writer using the IVByteOutput pattern"""
...     def __init__(self, reactor, filename, message):
...         self._reactor = reactor
...         self._fd = os.open(filename, os.O_WRONLY | os.O_CREAT)
...         self._message = message
...     def write_some(self, data):
...         return os.write(self._fd, data)
...     def start_writing(self):
...         self._reactor.add_writer(self)
...     def stop_writing(self):
...         self._reactor.remove_writer(self)
...     def do_write(self):
...         num_written = self.write_some(self._message)
...         self._message = self._message[num_written:]
...         if not self._message:
...             os.close(self._fd)
...             self.stop_writing()
...     def close_output(self, reason):
...         os.close(self._fd)
...     def close_io(self, reason):
...         os.close(self._fd)
...     def fileno(self):
...         return self._fd
...     @property
...     def reactor(self):
...         return self._reactor
... 
>>> reactor = VSelectReactor()
>>> reactor.start()
>>> tempfile = tempfile.NamedTemporaryFile()
>>> writer = TmpWriter(reactor, tempfile.name, 'Knights who say Ni!')
>>> reactor.add_writer(writer)
>>> time.sleep(0.1)
>>> reactor.stop()
>>> result = open(tempfile.name).read()
>>> 
>>> # Faking result for non-Unix so sphinx doctest does not report errors
... import sys
>>> if sys.platform != 'linux2':
...     result = 'Knights who say Ni!'
... 
>>> result
'Knights who say Ni!'

.. _generic_byte_io:

Generic Byte I/O
----------------

Byte I/O can often be defined in terms of a generic data "input" and
"output" using higher-level abstractions such as "sending",
"receiving", "closing" and "error condition" which do not depend on
the specifics of any particular I/O channel. Operating with such
abstractions enables cleaner code and better code reuse.

The :mod:`versile.reactor.io` module defines a generic
producer/consumer framework which allows I/O to be modelled with
generic interfaces. Classes implementing those interfaces can then be
paired with other classes exposing a similar interface, forming a
producer/consumer chain. At the chain end-point it can use "bridge"
classes to interface with a reactor to communicate via sockets or
other OS-level I/O channels.

Consumers and Producers
.......................

:class:`IVByteConsumer` and :class:`IVByteProducer` define interfaces
for generic byte consumers and producers. :class:`VByteConsumer` and
:class:`VByteProducer` define base classes for those interfaces which
can be used to sub-class an implementation.

Let us take :class:`VByteConsumer` as an example. A consumer interface
is available from :attr:`VByteConsumer.byte_consume`\ .

* A connected producer can call:

  * :meth:`IVByteConsumer.consume` to pass data to the consumer
  * :meth:`IVConsumer.end_consume` to notify end-of-data
  * :meth:`IVConsumer.abort` to force-abort I/O and dismantle
* Other code can call:

  * :meth:`IVConsumer.attach` to connect to a producer
  * :meth:`IVConsumer.detach` to disconnect from any producer

Below is a re-implementation of the earlier example which writes a
string to a file, but now using a producer/consumer framework. Note
the logical separation between ``TmpWriter`` which interfaces with the
reactor and "writes received data to a file", and ``MessageSender``
which only acts via the byte producer interface and "emits byte data".

.. note::

   The example is quite verbose as we are implementing a
   producer/consumer setup bottom-up working directly with the
   low-level framework. Normally such low-level programming is
   performed for creating reusable components, and producer/consumer
   chains are created by linking such higher-level components.

>>> import os
>>> import tempfile
>>> import time
>>> from versile.reactor.quick import VReactor
>>> from versile.reactor.io import *
>>> from versile.common.iface import implements
>>> class TmpWriter(VByteConsumer):
...     """A simple writer using the IVByteOutput pattern"""
...     def __init__(self, reactor, filename):
...         super(TmpWriter, self).__init__(reactor)
...         self._reactor = reactor
...         self._fd = os.open(filename, os.O_WRONLY | os.O_CREAT)
...         self._data = b''
...     def _data_received(self, data):
...         self._data += data
...         self.start_writing()
...     def _consumer_closed(self, reason, was_aborted):
...         self.stop_writing()
...         os.close(self._fd)
...     def write_some(self, data):
...         return os.write(self._fd, data)
...     def start_writing(self):
...         self._reactor.add_writer(self)
...     def stop_writing(self):
...         self._reactor.remove_writer(self)
...     def do_write(self):
...         num_written = self.write_some(self._data)
...         self._data = self._data[num_written:]
...         if not self._data:
...             self.stop_writing()
...     def close_output(self, reason):
...         os.close(self._fd)
...     def close_io(self, reason):
...         os.close(self._fd)
...     def fileno(self):
...         return self._fd
...     @property
...     def reactor(self):
...         return self._reactor
... 
>>> class MessageSender(VByteProducer):
...     def __init__(self, reactor, message):
...         super(MessageSender, self).__init__(reactor)
...         self._message = message
...     def _produce(self, max_bytes):
...         if max_bytes < 0:
...             msg, self._message = self._message, b''
...         else:
...             msg = self._message[:max_bytes]
...             self._message = self._message[max_bytes:]
...         if not self._message:
...             self.reactor.schedule(0, self._end_produce, True)
...         return msg
... 
>>> reactor = VSelectReactor()
>>> reactor.start()
>>> tempfile = tempfile.NamedTemporaryFile()
>>> writer = TmpWriter(reactor, tempfile.name)
>>> producer = MessageSender(reactor, 'Knights who say Ni!')
>>> producer.byte_produce.attach(writer.byte_consume)
>>> time.sleep(0.1)
>>> reactor.stop()
>>> result = open(tempfile.name).read()
>>> 
>>> # Faking result for non-Unix so sphinx doctest does not report errors
... import sys
>>> if sys.platform != 'linux2':
...     result = 'Knights who say Ni!'
... 
>>> result
'Knights who say Ni!'

Byte Writers
............

Writing byte output typically involves buffering data which is ready
for output and then sending the data piece by piece until all data has
been sent. :class:`VByteWriter` offers a ready-made alternative for
this process.

The writer exposes a byte producer interface so it can be connected to
a consumer. For the code which is using it for writing output, it is
considered an "output" and the hand-over to the producer interface is
handled internally by the class.

* Output data can be written via :meth:`VByteWriter.write`
* End-of-data can be fladdef with :meth:`VByteWriter.end_write`
* The writer can be aborted with :meth:`VByteWriter.abort_writer`

Below is an alternative version of the earlier *MessageSender* code
example which uses a :class:`VByteWriter`\ .

>>> import os
>>> import tempfile
>>> import time
>>> from versile.reactor.quick import VSelectReactor
>>> from versile.reactor.io import *
>>> from versile.common.iface import implements
>>> class TmpWriter(VByteConsumer):
...     """A simple writer using the IVByteOutput pattern"""
...     def __init__(self, reactor, filename):
...         super(TmpWriter, self).__init__(reactor)
...         self._reactor = reactor
...         self._fd = os.open(filename, os.O_WRONLY | os.O_CREAT)
...         self._data = b''
...     def _data_received(self, data):
...         self._data += data
...         self.start_writing()
...     def _consumer_closed(self, reason, was_aborted):
...         self.stop_writing()
...         os.close(self._fd)
...     def write_some(self, data):
...         return os.write(self._fd, data)
...     def start_writing(self):
...         self._reactor.add_writer(self)
...     def stop_writing(self):
...         self._reactor.remove_writer(self)
...     def do_write(self):
...         num_written = self.write_some(self._data)
...         self._data = self._data[num_written:]
...         if not self._data:
...             self.stop_writing()
...     def close_output(self, reason):
...         os.close(self._fd)
...     def close_io(self, reason):
...         os.close(self._fd)
...     def fileno(self):
...         return self._fd
...     @property
...     def reactor(self):
...         return self._reactor
... 
>>> class MessageSender(VByteWriter):
...     def __init__(self, reactor, message):
...         super(MessageSender, self).__init__(reactor)
...         self.write(message)
... 
>>> reactor = VSelectReactor()
>>> reactor.start()
>>> tempfile = tempfile.NamedTemporaryFile()
>>> writer = TmpWriter(reactor, tempfile.name)
>>> producer = MessageSender(reactor, 'Knights who say Ni!')
>>> producer.byte_produce.attach(writer.byte_consume)
>>> time.sleep(0.1)
>>> reactor.stop()
>>> result = open(tempfile.name).read()
>>> 
>>> # Faking result for non-Unix so sphinx doctest does not report errors
... import sys
>>> if sys.platform != 'linux2':
...     result = 'Knights who say Ni!'
... 
>>> result
'Knights who say Ni!'


Control Messages
................

In addition to passing data from producers to consumers,
producer/consumer chains can also pass control messages by accessing a
:class:`VIOControl` object provided by a chain peer. A control message
object is provided by consumers as :attr:`IVConsumer.control`\ , and
by producers as :attr:`IVProducer.control`\ .

:class:`VIOControl` exposes methods for control messages that are
handled. If any method is called on the control object which is not
supported, an :exc:`VIOMissingControl` exception should be raised
(this is the default :class:`VIOControl` behavior implemented via
getattribute overloading).

When receiving a supported control message (as a method call), a
control object can choose to handle the control message locally,
perform a pass-through by forwarding the call to the next
producer/consumer element in the chain, or both.

Standard control messages includes:

+--------------------------+-----------+----------------------------------+
| Control message          | Param(s)  | Description                      |
+==========================+===========+==================================+
| authorize                | (several) | Request connection authorization |
+--------------------------+-----------+----------------------------------+
| can_connect              | peer      | Ask permission to connect        |
+--------------------------+-----------+----------------------------------+
| connected                | peer      | Chain was connected to a host    |
+--------------------------+-----------+----------------------------------+
| notify_consumer_attached | consumer  | A consumer was attached in chain |
+--------------------------+-----------+----------------------------------+
| notify_producer_attached | producer  | A producer was attached in chain |
+--------------------------+-----------+----------------------------------+
| req_producer_state       | consumer  | Request state update to consumer |
+--------------------------+-----------+----------------------------------+
| req_consumer_state       | producer  | Request state update to producer |
+--------------------------+-----------+----------------------------------+

Authorize
+++++++++

Requests authorization to proceed with a connection for given
credentials.

Usage: ``control.authorize(key, certs, identity, protocol)``

Parameters (may be None):

* *key* - peer's connection key (:class:`versile.crypto.VAsymmetricKey`\ )
* *certs* - peer certificates 
  (tuple(:class:`versile.crypto.x509.cert.VX509Certificate`\ ))
* *identity* - identity assumed by peer
  (:class:`versile.crypto.x509.cert.VX509Name`\ )
* *protocol*  - protocol used by peer (unicode)

Returns True if connection is authorized, otherwise False.

Can Connect
+++++++++++

Requests permission to establish connection with communication peer.

Usage: ``control.can_connect(peer)``

Parameters:

* *peer* - communication peer (:class:`versile.common.peer.VPeer`\ )

Returns True if authorized to connect, otherwise False.

Connected
+++++++++

Notifies that a chain end-point was connected to a communication peer.

Usage: ``control.connected(peer)``

Parameters:

* *peer* - connected communication peer (:class:`versile.common.peer.VPeer`\ )

No return value. 

C.Attached
++++++++++

Notifies a consumer was attached to the chain.

Usage: ``control.notify_consumer_attached(consumer)``

Parameters:

* *consumer* - attached consumer (:class:`versile.reactor.io.IVConsumer`\ )

No return value.

P.Attached
++++++++++

Notifies a producer was attached to the chain.

Usage: ``control.notify_producer_attached(producer)``

Parameters:

* *producer* - attached consumer (:class:`versile.reactor.io.IVProducer`\ )

No return value.

Req C.State
+++++++++++

Requests consumer(s) in chain to trigger any pending control processing.

Usage:``control.req_consumer_state(producer)``

Parameters:

* *producer* - querying producer (:class:`versile.reactor.io.IVProducer`\ )

No return value. This control message allows a newly connected
producer to poll the chain for any unresolved control messages.

Req P.State
+++++++++++

Requests producer(s) in chain to trigger any pending control processing.

Usage:``control.req_producer_state(consumer)``

Parameters:

* *consumer* - querying consumer (:class:`versile.reactor.io.IVConsumer`\ )

No return value. This control message allows a newly connected
consumer to poll the chain for any unresolved control messages.

Other Classes
.............

The class :class:`VByteAgent` is a convenience packaging of a combined
input, output and connecter, and so it is a reasonable choice of base
class for a byte I/O interface which includes a "can connect" type
logic. The class :class:`VByteWAgent` is a convenience packaging of a
combined input, writer and connecter.

Socket communication
--------------------
.. currentmodule:: versile.reactor.io.sock

Classes derived from :class:`VSocket` provide implementations for
reactor-driven socket communication. Socket is typically needed for
network communication, e.g. connecting to a TCP/IP host or accepting
inbound connections.

The socket class includes a couple convenience class
methods. :meth:`VSocketBase.create_native` creates a native socket,
and :meth:`VSocketBase.create_native_pair` creates a pair of connected
native sockets. The latter can also be performed on platforms which do
not support :func:`socket.socketpair`.

The modules :mod:`versile.reactor.io.tcp` and
:mod:`versile.reactor.io.unix` offer implementations of socket classes
which are specific to TCP or Unix connections. There is little
difference from the classes of these modules and their parent
:mod:`versile.reactor.io.sock` classes. The main difference is any
native socket generated by the class will be of the appropriate type,
e.g. :meth:`VTCPSocket.create_native_pair` generates two paired TCP
sockets.

Raw Socket I/O
..............

A :mod:`versile.reactor.io.sock` socket can be a:

* client socket (already connected to a peer)
* (non-connected) client socket which can be connected to a peer
* server socket bound to a port and listening for incoming connections
* (non-connected) server socket not yet bound or listening

:class:`VClientSocket` implements a
:class:`versile.reactor.io.IVSelectableIO` interface for client
sockets.

:class:`VListeningSocket` listens on a bound/listening socket and
executes :meth:`VListeningSocket.accepted` when a new connection is
accepted. By default it uses a :class:`VClientSocketFactory` on
resulting native client sockets to create a :class:`VClientSocket` for
an accepted connection.

Consumer/Producer Sockets
.........................

:class:`VClientSocketAgent` exposes a consumer/producer interface for
client sockets. This is the default choice for client socket
interaction as it allows separating I/O logic from lower-level socket
I/O.

There is no producer/consumer listener. The standard pattern is to use
a :class:`VListeningSocket` set up with a client socket factory for
accepted connections which instantiates a :class:`VClientSocketAgent`
on a accepted native socket.

Versile UDP Transport
---------------------

.. currentmodule:: versile.reactor.io.vudp

Versile UDP Transport (:term:`VUT`\ ) is a streaming protocol which
transfers its data as UDP datagrams. It performs data streaming
similar to TCP and is intented to be used as a replacement for TCP in
scenarios where TCP based communication is not possible.

:term:`VUT` is typically used for peer-to-peer communication between
two communicating parties when one or both sides may be behind a
NAT. By using an external service to negotiate an UDP-based
connection, the two sides can normally perform NAT punch-through to
establish a direct channel. 

.. note:: 

    NAT punch-through relies on a NAT using the same external port number
    for the same internal host and port, for different external destinations. 
    This is normally the case, however some NATs may behave differently.

:term:`VUT` is implemented by :class:`VUDPTransport`\ . Setting up a
transport requires an open UDP socket which is bound to a host and
port which can be reached by the peer on an address known by the peer,
a peer network address which can be reached from this host, and a set
of secrets for authenticating the traffic. These parameters of the
UDP-based transport protocol is expected to be pre-negotiated
(typically via a relay service) before the transport is set up.

Other Byte I/O components
-------------------------

The :mod:`versile.reactor.io.pipe` module contains base classes for
communication over an OS pipe (e.g. created with :func:`os.pipe`\ ),
including a :class:`versile.reactor.io.pipe.VPipeAgent`
consumer/producer interface to pipe byte communication.

The reactor framework includes classes implementing consumer/producer
interfaces which can be combined to form I/O processing
chains. Components are covered in these sections:

* :ref:`lib_secure_comms` (:term:`VTS` secure channel)
* :ref:`lib_entity_channel` (:term:`VEC` entity bridge)
* :ref:`lib_link` (:term:`VOL` node)
* :ref:`lib_vop_channel` (:term:`VOP` protocol handler)

Module APIs
-----------

Reactor I/O
...........
Module API for :mod:`versile.reactor.io`

.. automodule:: versile.reactor.io
    :members:
    :show-inheritance:

Sockets
.......
Module API for :mod:`versile.reactor.io.sock`

.. automodule:: versile.reactor.io.sock
    :members:
    :show-inheritance:

TCP Sockets
...........
Module API for :mod:`versile.reactor.io.tcp`

.. automodule:: versile.reactor.io.tcp
    :members:
    :show-inheritance:

Unix Sockets
............
Module API for :mod:`versile.reactor.io.unix`

.. automodule:: versile.reactor.io.unix
    :members:
    :show-inheritance:

VUDPTransport
.............
Module API for :mod:`versile.reactor.io.vudp`

.. automodule:: versile.reactor.io.vudp
    :members:
    :show-inheritance:

Sockets
.......
Module API for :mod:`versile.reactor.io.pipe`

.. automodule:: versile.reactor.io.pipe
    :members:
    :show-inheritance:
