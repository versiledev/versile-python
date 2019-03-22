.. _stream_recipe:

Stream Data
===========
.. currentmodule:: versile.vse.stream

The module :mod:`versile.vse.stream` enables streaming data between
ORBs. In this recipe we provide simple examples of entity based streaming
and byte data streaming.

.. note::

    Working with the streaming framework is mostly quite
    straight-forward, however due to the complex asynchronous
    interaction between a stream and a streamer there are some complex
    mechanisms that need to be understood in order to properly use
    streams. See :mod:`versile.vse.stream` documentation for
    information.

Entity Streaming
----------------

We take as a starting point the *NameSorter* class of the
:ref:`vob_recipe` recipe, and converting its output of sorted names to
a stream. Below is a modified (and simplified) class::

    from versile.vse.stream import VEntityStreamer
    from versile.quick import *

    class NameSorter(VExternal):

        def __init__(self):
            super(NameSorter, self).__init__()
            self._names = []

        @publish(ctx=False)
        def add(self, name):
            with self:
                self._names.append(name)

        @publish(ctx=False)
        def reset(self):
            with self:
                names, self._names = self._names, []
            names.sort()
            return VEntityStreamer.fixed(names).proxy()

Below is an example of obtaining a reference to a streamer proxy and
connecting it to a local stream object. The local stream object is
used to iterate through all stream data.

>>> from versile.vse.stream import VEntityStreamer
>>> from versile.quick import *
>>> class NameSorter(VExternal):
...     def __init__(self):
...         super(NameSorter, self).__init__()
...         self._names = []
...     @publish(ctx=False)
...     def add(self, name):
...         with self:
...             self._names.append(name)
...     @publish(ctx=False)
...     def reset(self):
...         with self:
...             names, self._names = self._names, []
...         names.sort()
...         return VEntityStreamer.fixed(names).proxy()
... 
>>> Versile.set_agpl_internal_use()
>>> VSEResolver.enable_vse()
>>> client_link = link_pair(gw1=None, gw2=NameSorter())[0]
>>> name_service = client_link.peer_gw()
>>> 
>>> for i in (5, 3, 4, 1, 2):
...     name_service.add(u'John Doe #%s' % i)
... 
>>> streamer = name_service.reset()
>>> type(streamer)
<class 'versile.vse.stream.VEntityStreamerProxy'>
>>> stream = streamer.connect(readahead=True)
>>> stream.set_eos_policy(True)
>>> stream.wait_status(active=True)
True
>>> 
>>> for item in stream.iterator():
...     print(item)
... 
John Doe #1
John Doe #2
John Doe #3
John Doe #4
John Doe #5
>>> client_link.shutdown()

.. testcleanup::

   from versile.conf import Versile
   Versile._reset_copyleft()
   VSEResolver.enable_vse(False)

Byte Streaming
--------------

The :term:`VP` streaming framework supports streaming in both
directions if enabled on the peer streamer, though only one direction
can be active at any one time. In this example we set up a server-side
byte streamer which interfaces to a file and allows writing to,
seeking on and reading from the file. The :class:`VStream` stream
proxy provides I/O methods which enable reading and writing data using
methods similar to sockets or file objects.

Below is an example which defines a remote-enabled class *Gateway*
which can provide a streamer which accesses streamer data from a file,
and test code which connects a :class:`VStream` to the stream and
performs write and read operations.

>>> import tempfile
>>> from versile.vse.stream import *
>>> from versile.quick import *
>>> 
>>> class Gateway(VExternal):
...     @publish(show=True, ctx=False)
...     def get_file_stream(self):
...         _file = tempfile.NamedTemporaryFile()
...         data = VByteSimpleFileStreamerData(_file.name, 'r+',
...                                            seek_rew=True, seek_fwd=True)
...         mode = (data.req_mode[0] | VStreamMode.READABLE |
...                 VStreamMode.WRITABLE | VStreamMode.SEEK_FWD |
...                 VStreamMode.SEEK_REW | VStreamMode.END_CAN_DEC |
...                 VStreamMode.END_CAN_INC | VStreamMode.CAN_MOVE_END)
...         w_buf = VByteStreamBuffer()
...         return VByteStreamer(data, mode, w_buf).proxy()
... 
>>> Versile.set_agpl_internal_use()
>>> VSEResolver.enable_vse()
>>> client_link = link_pair(gw1=None, gw2=Gateway())[0]
>>> gw = client_link.peer_gw()
>>> 
>>> # Obtain a streamer reference and set up a local stream
... streamer = gw.get_file_stream()
>>> stream = streamer.connect(readahead=True)
>>> stream.wait_status(active=True)
True
>>> 
>>> # Write data to the stream
... stream.wseek(0)
>>> stream.write(b'This is an important message')
>>> 
>>> # Read back data from the stream
... stream.set_eos_policy(True)
>>> stream.enable_readahead()
>>> stream.rseek(0)
>>> result = stream.read()
>>> print('Read data from stream: %s' % result)
Read data from stream: This is an important message
>>> 
>>> stream.close()
>>> client_link.shutdown()

.. testcleanup::

   from versile.conf import Versile
   Versile._reset_copyleft()
   VSEResolver.enable_vse(False)

In this example (and the earlier entity streaming example) we used
some of the most accessible classes and methods of the streaming
framework. Creating custom streamer and streamer data objects can be
somewhat complex, however there is great potential for reuse of the
resulting components and is worth the effort.
