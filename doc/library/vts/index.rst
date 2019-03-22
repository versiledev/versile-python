.. _lib_secure_comms:

Secure Communication
====================

This is the API documentation for :term:`VTS` and :term:`TLS` secure
encrypted channels for byte communication.

Versile Transport Security
--------------------------
.. currentmodule:: versile.reactor.io.vts

:mod:`versile.reactor.io.vts` implements the :term:`VTS` standard for
secure communication, integrating with the :ref:`lib_reactor_io`
framework to expose producer/consumer interfaces for plaintext data. 

A secure channel is implemented as a bridge between two byte I/O
interfaces. The :term:`VTS` protocol is asymmetric with a client-side
and a server-side of the connection. The client side is implemented by
:class:`VSecureClient`\ and the server side is implemented by
:class:`VSecureServer`\ . The standard convention is that a host
listening on a socket and accepting incoming connections takes the
role of "server", and connecting nodes take the role of "client".

Producer/consumer interfaces to the plaintext transmitted over the
encrypted channel is exposed via :attr:`VSecure.plain_consume` and
:attr:`VSecure.plain_produce`\ . Similarly, interfaces to the
ciphertext side which performs :term:`VTS` and carries encrypted
channel data is exposed via :attr:`VSecure.cipher_consume` and
:attr:`VSecure.cipher_produce`\ .

Transport Layer Security
------------------------
.. currentmodule:: versile.reactor.io.tlssock

:mod:`versile.reactor.io.tlssock` implements a
:class:`VTLSClientSocketAgent` reactor producer/consumer interface to
socket communication secured by a :term:`TLS` transport, as well as a
class :class:`VTLSClientSocket` for lower level I/O. The :term:`VPy`
implementation uses the python :mod:`ssl` module for handling the
underlying :term:`TLS` connection.

.. currentmodule:: versile.reactor.io.tls

:mod:`versile.reactor.io.tls` implements a generic producer/consumer
channel bridge for a :term:`TLS` transport, which allows it to be used
for other scenarios than a connection directly to an Internet
socket. A bridge for a TLS server is available from
:class:`VTLSServer` and a bridge for a TLS client is available from
:class:`VTLSClient`\ . The current implementation of the channel
bridge uses a pair of internally connected sockets in order to enable
use the python ssl module to imlement the TLS protocol.

.. currentmodule:: versile.reactor.io.tlssock

.. warning::
   
   The implementation of :term:`TLS` sockets and the generic
   producer/consumer bridge relies on storing key pairs insecurely in
   files, refer to :class:`VTLSClientSocket` for details.


Peer Authorization
------------------
.. currentmodule:: versile.crypto.auth

Establishing secure connections typically involves a decision whether
to allow completion of a secure channel with peer based on credentials
provided by peer and the peer's address on a network. :class:`VAuth`
provides an abstraction for defining authorization policies and us
used in some of the interfaces for setting up a secure :term:`VOP`
connection with a :term:`VTS` or :term:`TLS` transport.

.. note::
   
   :class:`VAuth` is typically not the only authorization mechanism in
   use, e.g. it comes in addition to authorization performed by
   trapping an authorization request control message in a reactor I/O
   producer/consumer chain.

If a :class:`VAuth` authorization request is denied then a secure
connection should be terminated. If it is approved then the connection
is allowed to proceed, however the connection may still be terminated
by other authorization schemes in effect (such as a
:class:`versile.orb.link.VLink` level approval of peer credentials).

Module APIs
-----------

VTS channel
...........
Module API for :mod:`versile.reactor.io.vts`

.. automodule:: versile.reactor.io.vts
    :members:
    :show-inheritance:

TLS sockets
...........
Module API for :mod:`versile.reactor.io.tlssock`

.. automodule:: versile.reactor.io.tlssock
    :members:
    :show-inheritance:

TLS bridge
..........
Module API for :mod:`versile.reactor.io.tls`

.. automodule:: versile.reactor.io.tls
    :members:
    :show-inheritance:

Authorizers
...........
Module API for :mod:`versile.crypto.auth`

.. automodule:: versile.crypto.auth
    :members:
    :show-inheritance:
