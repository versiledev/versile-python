.. _lib_vop_channel:

Object Channel
==============

.. currentmodule:: versile.reactor.io.vop

This is the API documentation for the :mod:`versile.reactor.io.vop`
module which implements a reactor-based channel for implementing the
:term:`VOP` protocol.

The :term:`VOP` protocol is a byte-level protocol which provides
access to a :term:`VOL` link. It implements the scheme which resolves
a :term:`VRI` for a resource identified with the ``'vop://'``
scheme. :term:`VOP` negotiates a byte transport for the connection and
initiates :term:`VEC` and :term:`VOL` protocols over that transport.

An end-point of a :term:`VOP` connection takes a role as either
'server' or 'client' for this protocol. Normally a "listening" side of
the connection should take the role of server, and a "connecting" side
should take the role of client.

The client side of a connection is implemented by
:class:`VOPClientBridge` and the server side is implemented by
:class:`VOPServerBridge`\ .


Module APIs
-----------

Module API for :mod:`versile.reactor.io.vop`

.. automodule:: versile.reactor.io.vop
    :members:
    :show-inheritance:

