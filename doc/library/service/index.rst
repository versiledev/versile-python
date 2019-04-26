.. _lib_service:

Services
========
.. currentmodule:: versile.orb.service

This is the API documentation for :class:`VService` service objects.

Running a "service" typically involves listening on a network
interface and setting up a link implementing the service protocol on
each inbound connection. Implementations of the abstract class
:class:`VService` are intended to provide a convenient mechanism for
setting up such services.

An implementation of :term:`VOP` services is available from
:mod:`versile.quick`\ . :term:`VPy` provides a reactor-based
implementation; when using reactor-specific features or service
configuration objects then the service class should be imported from
that module.

Service Classes
---------------
.. currentmodule:: versile.reactor.io.service

:term:`VPy` provides the reactor based :class:`VOPService`
implementation of the :term:`VOP` protocol.

The minimum information required for setting up a service is a factory
for link gateway objects. There are several other arguments and
methods that can be overloaded to further customize service object
behavior, refer to the service class documentation for details.

:term:`VOP` services can use either a secure :term:`VTS` transport, a
secure :term:`TLS` transport, or insecure unencrypted transports. The
transport is negotiated between client/server during a protocol
handshake. :class:`VOPService` default allows only secure connections,
and is by default to only allow :term:`VTS` transports due to some
limititations in how :term:`TLS` support is currently implemented. It
can be configured to allow :term:`TLS` and allowing insecure
connections.

Below is a simple example which sets up a :term:`VOP` service, using a
random server key pair. In this version we also use
:mod:`versile.quick` to simplify import statements.

>>> from versile.demo import Echoer
>>> from versile.quick import VOPService, VCrypto, VUrandom
>>> # Create (insecure) example keypair
... keypair = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 512//8)
>>> # Set up and start service
... gw_factory = lambda: Echoer()
>>> service = VOPService(gw_factory, auth=None, key=keypair)
>>> service.start()
>>> # Later, to stop the service:
... service.stop(True)

.. note::

   :class:`VOPService` takes an *auth* argument which is passed to new
   client links during link construction. See
   :class:`versile.orb.link.VLink` for details how it is used. It is a
   required constructor argument in order to force service initiators
   to explicitly declare a handler for authorization (or None).

Service Configuration
---------------------
.. currentmodule:: versile.orb.service

Instantiated :class:`VService` objects take a :class:`VServiceConfig`
object as one of their construction parameters. When provided this
object defines service configuration properties in addition to those
passed directly as constructor arguments. See ':ref:`lib_url`\ ' for
examples of :class:`versile.orb.url.VUrl` configuration properties
which are also relevant for services.

Stopping Services
-----------------

Listening services normally run until they they are explicitly terminated.

* A service can terminate itself by calling :meth:`versile.orb.service.VService.stop`\ .
* See the :ref:`daemonize_recipe` recipe for an example how to handle SIGTERM.
* A service can be shut down "the hard way" by sending SIGKILL.

Module APIs
-----------

Services
........
Module API for :mod:`versile.orb.service`

.. automodule:: versile.orb.service
    :members:
    :show-inheritance:

Reactor Services
................
Module API for :mod:`versile.reactor.io.service`

.. automodule:: versile.reactor.io.service
    :members:
    :show-inheritance:
