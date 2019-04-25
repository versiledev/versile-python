.. _lib_stream:

Streams
=======
.. currentmodule:: versile.vse.stream

The module :mod:`versile.vse.stream` includes classes enabling
streaming of data elements between two paired endpoints. It implements
:term:`VSE` defined streaming data types

* :class:`VByteStreamer` and :class:`VByteStreamerProxy` for byte data
* :class:`VEntityStreamer` and :class:`VEntityStreamerProxy` for entity data

:class:`VStreamModule` holds :term:`VSE` module handlers for streaming
classes, and the module registers itself with the module resolver
class when :mod:`versile.vse.stream` is imported.

Streaming Framework
-------------------

The framework enables streaming between two end points, by connecting
a local :class:`VStreamPeer` to a (remote) :class:`VStreamer`\ . The
framework is asymmetric as it connects end-point of different types,
and the end-points play different roles in the connection. A
:class:`VStreamer` is a streaming end-point that can be passed
remotely, whereas a :class:`VStreamPeer` is intended to be used
locally as an interface to a remote :class:`VStreamer`\ . A stream is
established by creating a :class:`VStreamPeer`\ , obtaining a
reference to a :class:`VStreamer` and connecting the stream peer to
the streamer.

The framework supports bi-directional streaming, as data can be sent
to and/or received from a :class:`VStreamer` depending on which modes
the streamer supports. If both sending and receiving is enabled the
:class:`VStreamPeer` can alternate between send-mode and receive-mode
for the stream, however only one direction may be active. For
scenarios that require simultaneously sending and receiving, one
stream must be set up for each direction.

Streamers
.........

:class:`VStreamer` is modelled as a lens onto a sequence of data
elements, represented as a :class:`VStreamerData` object. The data
sequence may be read from and/or written to, depending on the
properties of the streamer data. The framework has a fairly generic
model of 'streamer data', which may include repositioning (seeking)
the streamer's position on the streamer data, or moving streamer data
end points.

One example of streamer data is :class:`VByteSimpleFileStreamerData`
which provides a simple data interface for accessing a file. The class
supports reading and/or writing and seeking, which may be enabled or
disabled in a connected streamer. The start position of the streamer
data is always zero (as the 'start position' of a file can never
change), however the streamer data end-point is allowed to be moved
(e.g. truncating the data or writing past the current file end-point).

The streaming framework is generic and can in principle operate on any
type of sequenced data. In order to make this work, streamers use
:class:`VStreamBuffer` objects for holding buffered data and working
with data sequences. The stream buffer class is abstract, however
implementations are included for bytes data
(:class:`VByteStreamBuffer`\ ) and entity data
(:class:`VEntityStreamBuffer`\ ).

Stream Peers
............

:class:`VStreamPeer` can be connected to a :class:`VStreamer` with
:meth:`VStreamPeer.connect`\ . However, it is not intented to be used
directly by as an interface to the stream (which is also why most of
its methods are private). Instead, a :class:`VStream` object should be
created as a proxy for the stream peer.

The main reason why a :class:`VStream` is used as an access point to
the stream is to enable garbage collection. During handshake between a
streamer and a stream peer, each side of the connection will hold a
reference to the other object. This means the stream would stay alive
even after the stream peer was locally dereferenced. However, when
working through a :class:`VStream`\ , the stream peer at most holds a
weak reference to the stream object, and stream object garbage
collection will trigger a destructor which closes the stream.

Similar to streamers, a stream peer also uses :class:`VStreamBuffer`
objects for data buffering, allowing it to operate on arbitrary types
of sequenced data.

:class:`VStream` enables performing blocking and non-blocking stream
operations on the stream, however it requires proactively making calls
to the object's methods. In order to enable asynchronous operations to
react to conditions on the stream (e.g. 'data can be read'), a
:class:`VStreamObserver` can be connected to the stream. Registering
an observer will trigger stream notifications to the observer object,
and notifications can be handled by sub-classing
:class:`VStreamObserver` and overriding the receiving methods.

Streaming Byte Data
-------------------

The framework includes several classes to simplify creating streams
operating on :class:`bytes` data. The class :class:`VByteStreamer` is
a :term:`VSE` type which implements a standard streamer interface for
byte data. Its serialized entity encoding resolves as a
:class:`VByteStreamerProxy`\ . :class:`VByteStreamBuffer` can be used
as a can be used as a buffer for bytes data streamers and stream
peers.

Typically a stream would be set up by calling
:meth:`VByteStreamerProxy.connect` to create a stream peer and connect
it to the streamer. However, this could also be done manually by
obtaining a reference to the streamer from
:attr:`VByteStreamerProxy.streamer` and instantiating/connecting a
stream peer.

:class:`VByteFixedStreamerData` provides a read-only streamer data
interface to a memory-held :class:`bytes` object. It is typically
created and connected to a streamer by calling
:meth:`VByteStreamer.fixed` rather than instantiating directly. Below
is a complete example.

>>> from versile.quick import *
>>> from versile.vse.stream import *
>>> class Gateway(VExternal):
... 	@publish(show=True, ctx=False)
... 	def get_stream(self):
... 	    data = b'This byte data will be exposed as a readable stream'
... 	    streamer = VByteStreamer.fixed(data, seek_rew=True, seek_fwd=True)
... 	    return streamer.proxy()
...
>>> VSEResolver.enable_vse()
>>> key = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 512//8)
>>> service = VOPService(lambda: Gateway(), auth=None, key=key)
>>> service.start()
>>> # Obtain streamer reference
... gw = VUrl.resolve('vop://localhost/')
>>> streamer = gw.get_stream()
>>> type(streamer)
<class 'versile.vse.stream.VByteStreamerProxy'>
>>> # Set up stream and read all data
... stream = streamer.connect(readahead=True)
>>> stream.wait_status(active=True)
True
>>> while True:
... 	data = stream.recv(1000)
... 	if data:
... 	    print(repr(data))
... 	else:
... 	    break
...
'This byte data will be exposed as a readable stream'
>>> # Simulate shutting down link and service
... gw._v_link.shutdown()
>>> service.stop(True)

.. testcleanup::

   VSEResolver.enable_vse(False)

:class:`VByteSimpleFileStreamerData` provides a read/write streamer
data interface to a file. Below is a complete example which writes
data to and then reads it back off a remote byte streamer operating on
a file.

>>> import tempfile
>>> from versile.quick import *
>>> from versile.vse.stream import *
>>> class Gateway(VExternal):
...     @publish(show=True, ctx=False)
...     def get_stream(self):
...         _file = tempfile.NamedTemporaryFile()
...         filename = _file.name
...         DataCls = VByteSimpleFileStreamerData
...         data = DataCls(filename, 'r+', seek_rew=True, seek_fwd=True)
...         mode = (data.req_mode[0] | VStreamMode.READABLE |
...                 VStreamMode.WRITABLE | VStreamMode.SEEK_FWD |
...                 VStreamMode.SEEK_REW | VStreamMode.END_CAN_DEC |
...                 VStreamMode.END_CAN_INC | VStreamMode.CAN_MOVE_END)
...         w_buf = VByteStreamBuffer()
...         streamer = VByteStreamer(data, mode, w_buf)
...         return streamer.proxy()
...
>>> VSEResolver.enable_vse()
>>> key = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 512//8)
>>> service = VOPService(lambda: Gateway(), auth=None, key=key)
>>> service.start()
>>> # Obtain streamer reference
... gw = VUrl.resolve('vop://localhost/')
>>> streamer = gw.get_stream()
>>> # Set up stream
... stream = streamer.connect(readahead=True)
>>> stream.wait_status(active=True)
True
>>> # Write data to the file
... send_data = b'This is data which will be written to the file'
>>> while send_data:
...     num_sent = stream.send(send_data)
...     send_data = send_data[num_sent:]
...
>>> # Reposition and read written data
... stream.rseek(0)
>>> while True:
...     data = stream.recv(1000)
...     if data:
...         print(repr(data))
...     else:
...         break
...
'This is data which will be written to the file'
>>> # Simulate shutting down link and service
gw._v_link.shutdown()
>>> service.stop(True)

.. testcleanup::

   VSEResolver.enable_vse(False)

In addition to the provided byte streamer data classes, other streamer
data sources can be created by sub-classing :class:`VStreamerData`\ .


Streaming Entity Data
---------------------

The streaming framework supports generic data structures, and
:mod:`versile.vse.stream` has built-in support for streaming
:class:`versile.orb.entity.VEntity` data elements. Streaming entity
data is a powerful capability which offers a lot of possibilities.

* Streaming with objects instead of 'dumb' bytes data
* Byte-oriented streaming interleaving byte data with control messages
  or meta-data
* Passing sequences of entities too long to send as one tuple
* Sending entities when receiver may not need all elements

:class:`VEntityFixedStreamerData` provides a read-only streamer data
interface to a memory-held :class:`versile.orb.entity.VEntity` (or
lazy-convertible) object. It is typically created and connected to a
streamer by calling :meth:`VEntityStreamer.fixed` rather than
instantiating directly. Below is a complete example.

>>> from versile.quick import *
>>> from versile.vse.stream import *
>>> class Gateway(VExternal):
...         @publish(show=True, ctx=False)
...         def get_stream(self):
...             data = (2.5, False, u'Some Text', (0, 1))
...             streamer = VEntityStreamer.fixed(data, seek_rew=True,
...                                              seek_fwd=True)
...             return streamer.proxy()
...
>>> VSEResolver.enable_vse()
>>> key = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 512//8)
>>> service = VOPService(lambda: Gateway(), auth=None, key=key)
>>> service.start()
>>> # Obtain streamer reference
... gw = VUrl.resolve('vop://localhost/')
>>> streamer = gw.get_stream()
>>> type(streamer)
<class 'versile.vse.stream.VEntityStreamerProxy'>
>>> # Set up stream and read all data
... stream = streamer.connect(readahead=True)
>>> stream.wait_status(active=True)
True
>>>
>>> while True:
...         data = stream.recv(1000)
...         if data:
...             print(data)
...         else:
...             break
...
(2.5, False, u'Some Text', (0, 1))
>>> # Simulate shutting down link and service
... gw._v_link.shutdown()
>>> service.stop(True)

.. testcleanup::

   VSEResolver.enable_vse(False)

:class:`VEntityIteratorStreamerData` implements read-only streamer
data which interfaces to an iterable whose iterator yields entity (or
lazy-convertible) objects. The streamer data only allows accessing
data in sequence, and does not allow seeking. The streamer data is
typically not instantiated directly, but is instead created and
connected by calling :meth:`VEntityStreamer.iterator`\ . Below is a
complete example which uses this class. The example also uses
:meth:`VStream.iterator` to create an iterator for accessing elements
received from the remote streamer.

>>> from versile.quick import *
>>> from versile.vse.stream import *
>>> class Gateway(VExternal):
...         @publish(show=True, ctx=False)
...         def get_stream(self):
...             data = (2.5, False, u'Some Text', (0, 1))
...             streamer = VEntityStreamer.iterator(data)
...             return streamer.proxy()
...
>>> VSEResolver.enable_vse()
>>> key = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 512//8)
>>> service = VOPService(lambda: Gateway(), auth=None, key=key)
>>> service.start()
>>> # Obtain streamer reference
... gw = VUrl.resolve('vop://localhost/')
>>> streamer = gw.get_stream()
>>> # Set up stream
... stream = streamer.connect(readahead=True)
>>> stream.wait_status(active=True)
True
>>> # Read stream data
... for item in stream.iterator():
...     print(item)
...
2.5
False
Some Text
(0, 1)
>>> # Simulate shutting down link and service
... gw._v_link.shutdown()
>>> service.stop(True)

.. testcleanup::

   VSEResolver.enable_vse(False)

Using Observers
---------------

In the previous examples the 'client-side' of the stream connection
performs stream operations by making calls on a :class:`VStream`\
. However, this may not always be an appropriate pattern, e.g. for
code which needs to interact with several streams in parallell. For
such usage an asynchronous model with a :func:`select.select`\ -type
mechanism is required.

:class:`VStreamObserver` can be used with a :class:`VStream` to
provide handlers that are triggered upon receiving notifications of
events from the stream object. Below is a simple example which uses an
observer to trigger reading data from the stream.

>>> import time
>>> from versile.quick import *
>>> from versile.vse.stream import *
>>> class Gateway(VExternal):
...         @publish(show=True, ctx=False)
...         def get_stream(self):
...             data = (2.5, False, u'Some Text', (0, 1))
...             streamer = VEntityStreamer.fixed(data, seek_rew=True,
...                                              seek_fwd=True)
...             return streamer.proxy()
...
>>> VSEResolver.enable_vse()
>>> key = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 512//8)
>>> service = VOPService(lambda: Gateway(), auth=None, key=key)
>>> service.start()
>>> # Obtain streamer reference
... gw = VUrl.resolve('vop://localhost/')
>>> streamer = gw.get_stream()
>>> # Set up stream and read all data
... stream = streamer.connect(readahead=True)
>>> stream.wait_status(active=True)
True
>>> # Set up an observer
... class MyObserver(VStreamObserver):
...     def can_recv(self):
...         while True:
...             try:
...                 data = stream.recv(1000)
...             except VStreamTimeout:
...                 break
...             if data:
...                 print(data)
...             else:
...                 break
...
>>> observer = MyObserver(stream)
>>>
>>> # Trigger stream reading
... stream.rseek(0)
>>> time.sleep(0.05) # Wait briefly to let observer print its output
(2.5, False, u'Some Text', (0, 1))
>>> # Shut down link and service
... gw._v_link.shutdown()
>>> service.stop(True)

.. testcleanup::

   VSEResolver.enable_vse(False)


Module APIs
-----------

Module API for :mod:`versile.vse.stream`

.. automodule:: versile.vse.stream
    :members:
    :show-inheritance:
