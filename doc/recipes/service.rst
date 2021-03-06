.. _listening_service_recipe:

Running a Listening Service
===========================

Derived classes of :class:`versile.orb.service.VService` have standard
mechanisms for setting up a listening service. A service for the
:term:`VOP` protocol is typically set up using an implementing service
class imported from :mod:`versile.quick`\ .

The simplest scenario for setting up a :term:`VOP` service involves
setting up a service object with a gateway factory, authorizer, and a
service keypair. Below is a code example which runs a simple listening
service for a gateway object which provides :term:`VRI` resolution to
:class:`versile.demo.SimpleGateway` services::

    from versile.demo import SimpleGateway
    from versile.quick import VOPService, VCrypto, VUrandom
    # For this demonstration we use a random server keypair
    keypair = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 1024//8)
    # Set up and start service
    gw_factory = lambda: SimpleGateway()
    service = VOPService(gw_factory, auth=None, key=keypair)
    service.start()
    service.wait(stopped=True)

.. note::

    See ':ref:`resolve_vri_recipe`\ ' for a recipe how to connect to the
    service

The service in this example runs infinitely. In order create services
which can be stopped, the service needs to either include some
internal logic or interface for stopping the service by calling
:meth:`versile.orb.service.VService.stop`\ . Another approach is
daemonizing and trapping SIGTERM signal, see the recipe
':ref:`daemonize_recipe`\ ' for an example.
