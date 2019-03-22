.. _lib_entity_channel:

Entity Channel
==============

.. currentmodule:: versile.reactor.io.vec

This is the API documentation for the :mod:`versile.reactor.io.vec`
module which implements a reactor-based channel for passing
:class:`versile.orb.entity.VEntity` data.

:class:`VEntitySerializer` and derived classes implement a bridge
between two producer/consumer interfaces. On the higher-level side the
interfaces passes :class:`versile.orb.entity.VEntity` data and on the
lower-level side the interface sends and receives a serialized
representation of entities. This allows higher-level producer/consumer
components to interact at a :class:`versile.orb.entity.VEntity` level.

Producer/Consumer Interface
---------------------------

The module defines interfaces for entity producers and consumers,
similar to :ref:`lib_reactor_io` interfaces for standard byte
communication.

* :class:`IVEntityConsumer` for consumers
* :class:`IVEntityProducer` for producers
* :class:`IVEntityWriter` for a writer

For serialized byte data the standard :ref:`lib_reactor_io` interfaces
are used.

Bridge for Serialized Data
--------------------------

The module implements classes that bridge between byte and entity
communication. The classes implement the :term:`VEC` entity channel
specifications for the serialized communication on the byte
interface. The protocol implementation includes an initial handshake
before serialized entities can be sent or received, and the byte
communication peer must provide a proper handshake.

The class :class:`VEntitySerializer` implements the bridge between a
byte-communication interface and a VEntity-communication interface. An
interface for byte communication is available from
:attr:`VEntitySerializer.byte_consume` and
:attr:`VEntitySerializer.byte_produce`\ . An entity interface at
:attr:`VEntitySerializer.entity_consume` and
:attr:`VEntitySerializer.entity_produce`\ .

The typical use case for a :class:`VEntitySerializer` is to connect
the entity producer/consumer interface to a
:class:`versile.reactor.io.link.VLinkAgent` to set up a reactor-based
consumer/producer chain passing serialized :term:`VOL` data through
the byte-data side of the serializer.

Base Classes for Entity Communication
-------------------------------------

Similar to :mod:`versile.reactor.io` this module defines a number of
classes for creating entity data consumers and producers, which can be
attached to another entity interface.

Below is an overview of the available base classes, see
:ref:`lib_reactor_io` for an overview of the various types of base
classes.

+--------------------------+-------------------------------------------+
| Entity communication     | Similar class for byte communication      |
+==========================+===========================================+
| :class:`VEntityConsumer` | :class:`versile.reactor.io.VByteConsumer` |
+--------------------------+-------------------------------------------+
| :class:`VEntityProducer` | :class:`versile.reactor.io.VByteProducer` |
+--------------------------+-------------------------------------------+
| :class:`VEntityWriter`   | :class:`versile.reactor.io.VByteWriter`   |
+--------------------------+-------------------------------------------+
| :class:`VEntityAgent`    | :class:`versile.reactor.io.VByteAgent`    |
+--------------------------+-------------------------------------------+
| :class:`VEntityWAgent`   | :class:`versile.reactor.io.VByteWAgent`   |
+--------------------------+-------------------------------------------+


Module APIs
-----------

Module API for :mod:`versile.reactor.io.vec`

.. automodule:: versile.reactor.io.vec
    :members:
    :show-inheritance:

