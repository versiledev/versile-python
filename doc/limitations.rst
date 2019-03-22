.. _limitations:

Limitations
===========

As a strictly python-based implementation of Versile Platform, Versile
Python currently has a few limitations.

.. rubric:: Latency

The :term:`VPy` implementation's layered stack with multiple levels of
thread-locking and task queueing adds some latency to remote
calls. The round-trip time for performing a remote call which sends
and receives a small value between two local sockets is typically 3ms
latency (1.5 ms for the call and 1.5 ms for the return value). 3 ms
for a single call is typically acceptable, however if e.g. 1000 calls
are made in sequence then latency adds up to about 3 seconds which is
too much e.g. for a responsive UI.

.. note::

    If cumulative latency of sequential calls is too high, consider
    instead making remote calls as asynchronous calls using the
    "nowait" keyword. This way the net cumulative latency for multiple
    call becomes no more than the latency of one single blocking call.

.. rubric:: Bandwidth

The :term:`VPy` implementation performs significant data processing to
handle encoding/decoding of transferred data, and so available
bandwidth for data transferring data in remote method calls is CPU
bound.

As python threads are essentially limited to one single CPU core due
to the Global Interpreter Lock, the bandwidth limits are effectively a
global cumulative limit for links running in one single process. In
order to increase bandwidth by utilizing more cores ORB services must
be distributed on multiple processes.

.. note::

   :term:`VTS` with the :class:`versile.crypto.local.VLocalCrypto`
   provider is currently very slow due to slow native python
   implementation of the blowfish cipher, which is why PyCrypto should
   be installed whenever possible. However, though the local crypto
   provider is too slow for bandwidth-consuming tasks, it at least
   makes it possible to establish a :term:`VTS` based link on
   platforms where PyCrypto is not supported and perform
   lower-bandwidth tasks.
   
.. rubric:: Threading Performance

Due to the python GIL the multi-threaded :term:`VPy` implementation
can effectively only use one CPU core per process. In order to
leverage multiple cores then the service must be set up with multiple
processes. See the :ref:`process_recipe` recipe for an example how
this can be achieved.

.. rubric:: Network connections

The :term:`VOL` protocol requires a persistent stateful connection and
there is currently no way of re-connecting a failed network
connection. When a network connection is lost then the I/O context of
the associated link and any remote object references to the peer ORB
are invalidated.

.. rubric:: Python runtime

Though development snapshots have been tested with other runtimes than
CPython it it is not currently extensively or systematically tested
with those platforms and so it may currently run less stable on PyPy
and IronPython.

:term:`VPy` does is not currently able to reliably use :term:`TLS` on
other runtimes than CPython, so the :term:`VOP` protocol is not
supported with a :term:`TLS` transport on those platforms. This seems
to be partly due to inconsistent runtime implementations of the
:mod:`ssl` module. Also for IronPython and .Net there are some
peculiarities regarding Windows' handling of :term:`TLS` in .Net which
requires certificate CAs to be registered in Windows.

.. note::

   IronPython handling of :class:`bytes`\ , :class:`str` and
   :class:`unicode` has some differences from CPython due to the
   mapping to .Net types, which can be a source of problems when
   porting python code to IronPython.

:term:`VPy` does not work with cygwin due to issues with cygwin's
thread handling.
