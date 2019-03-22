.. _lib_link:

Links to Object Brokers
=======================

This is the API documentation for links implementing the :term:`VOL`
specification.

Links to ORBs
-------------
.. currentmodule:: versile.orb.link

:class:`VLink` provides an I/O processing chain end-point for
interacting with a remote connected ORB, implementing the :term:`VOL`
protocol. Links enable applications to interact with remote services
and exchange data using higher-level data types.

.. note::
   
   :class:`VLink` is an abstract class that should not be instantiated
   directly, as it relies on derived classes to implement link
   functionality. :term:`VPy` provides an implementation of
   :ref:`lib_reactor_link`\ .

Link classes can be instantiated and set up manually, however the
typical pattern is to set up a link by:

* Using :class:`versile.quick.VUrl` to resolve a :term:`VRI`
* Accepting a :class:`versile.orb.service.VService` client connection
* Setting up a local paired link with :func:`versile.quick.link_pair`

Link I/O
........

:class:`VLink` is an abstract class, and it is up to derived classes
to define an I/O subsystem. A link interacts with its peer by
exchanging serialized :class:`versile.orb.entity.VEntity` data using
the standard link protocol.

.. note::

    Due to technical details of the :term:`VOL` protocol for a link
    handshake, global license information must be set on
    :class:`versile.Versile` before a :class:`VLink` can be
    constructed. See :class:`versile.Versile` for more information.

When serializing :ref:`lib_entities`\ , a context object is required
for serializing and reconstructing byte data. :class:`VLink` is a
sub-class of :class:`versile.orb.entity.VObjectIOContext`\ , which
allows serializing not just immutable data types but also object
references. The link implements an ID spaces for local objects and
peer objects, ensuring references are properly resolved within the
communication context with the peer.

When interfacing a link with code that performs entity serialization
(such as :class:`versile.reactor.io.vec.VEntitySerializer`\ ), the
link object should be used as the context object for entity
serialization.

Link Handshake
..............

When a :term:`VOL` communication path is established between a
:class:`VLink` and a peer link node, a link protocol handshake is
performed before the link is fully active. The handshake which is
performed after the exchange of an initial "hello" protocol message is
implemented by a :class:`VHandshake` object.  The handshake completes
after a local gateway object has been sent to the link peer and a
*peer gateway object* has been received from the peer.

.. note::
   
   The local gateway object sent to the peer must be a
   :class:`versile.orb.entity.VObject` and gateway object received
   from peer must be a :class:`versile.orb.entity.VReference` (which
   may be lazy-converted).
   
For a standard :term:`VOL` handshake the default handshake should be
used, however it is possible to use an alternative handshake by
overloading :meth:`VLink._create_handshake_obj` and sub-classing
:class:`VHandshake`\ .

Using a VLink
.............

When a :class:`VLink` has completed a handshake it enters an active
state where the link can perform operations on peer objects it holds
references to, and the peer can perform operations on local objects
which it has obtained references to.

The peer gateway object can be retreived with :meth:`VLink.peer_gw`
which blocks until a gateway object is available (i.e. handshake
completed) or a set timeout expires. The peer gateway can
alternatively be retreived as an asynchronous call result with the
non-blocking :meth:`VLink.async_gw`\ method.

.. warning::
   
   :meth:`VLink.peer_gw` or :meth:`VLink.async_gw` reliably produce a
   gateway object only the first time it is called. When a gateway is
   returned the :class:`VLink` replaces its internal reference to the
   gateway object with a weak reference. Callers are responsible for
   maintaining a reference to the peer gateway object.

The reason why the link replaces its peer gateway reference with a
weak reference is to be able to enable garbage collection of all
references to peer objects, including the peer gateway. The
:term:`VOL` protocol enables link peers to pass information about
resources which are no longer referenced, and allows a link to detect
a situation where no references to/from a link peer exist and the link
should be shut down.

Garbage collection of references can trigger link shutdown, however
this is not a bullet-proof mechanism because (a) references may still
exist somewhere, (b) the link peer may still hold references to local
resources, or (b) an error condition on the link may have prevented
proper resolution of reference counts. A link can be explicitly
terminated with :meth:`VLink.shutdown`\ .

.. note::

    The reliable way to terminate a link is to call
    :meth:`VLink.shutdown`\ .

.. _lib_maintaing_links:

Maintaining Links
-----------------
.. currentmodule:: versile.orb.util

Links can fail for various reasons, typically because of a network
problem between link peers, or because the peer terminated its link
service. For situations where a program should maintain a link to a
central resource, control mechanisms need to be used to detect link
failure and perform attempt to re-connect. This could be e.g. a sensor
which is providing sensor readings to a central analysis service, and
which needs to maintain a link to that service.

The class :class:`VLinkMonitor` is a base class which can be used as a
monitor and control mechanism for operating a link with attempts to
re-connect if the link fails.

.. _lib_reactor_link:

Reactor Link I/O
----------------
.. currentmodule:: versile.reactor.io.link

As mentioned the :class:`versile.orb.link.VLink` class is abstract and
should not be directly instantiated. :term:`VPy` provides a
reactor-based link implementation in :mod:`versile.reactor.io.link`\ ,
implementing the link class as a :class:`VLinkAgent`\ .

:class:`VLinkAgent` is a sub-class of
:class:`versile.reactor.io.vec.VEntityAgent` which can be attached to
an entity producer/consumer, such as a
:class:`versile.reactor.io.vec.VEntitySerializer`\
. :meth:`VLinkAgent.create_byte_agent` is a convenience method for
creating a :class:`versile.reactor.io.VByteAgent` interface which can
be connected to an entity producer/consumer. See :ref:`lib_reactor_io`
for details how to interface this class with other reactor framework
components.

Module APIs
-----------

Links
.....
Module API for :mod:`versile.orb.link`

.. automodule:: versile.orb.link
    :members:
    :show-inheritance:

Reactor Links
.............
Module API for :mod:`versile.reactor.io.link`

.. automodule:: versile.reactor.io.link
    :members:
    :show-inheritance:

