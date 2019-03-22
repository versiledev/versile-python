.. _process_recipe:

Use Multiple Processes
======================
.. currentmodule:: versile.orb.service

Multi-processing is a good mechanism for boosting :term:`VPy`
performance. The platform design and the python interpreter has some
limitations which limit the performance that can be achieved by a
single process:

1. The python GIL effectively limits performance of one process to one
   CPU core
2. With a native python :term:`VPy` implementation :term:`VOL` data
   transfer is largely CPU-bound

The two above effects limit :term:`VPy` performance, and the obvious
way to boost performance is to use multiple processes. However, even
in a multi-processing environment, if only one server process is
handling the traffic on the server's listening port then data-transfer
performance is still limited to one single core due to factor #2.

In this recipe we provide an example how a listening service can be
set up to route socket-level traffic to multiple independently running
processes. The example only works on Unix-based systems as it relies
on the ability to pass an open file descriptor to a new process.

.. note::

   :term:`VPy` multi-processing still in early stages, however it is
   one of the areas which should continue to evolve as the platform
   matures.

A service can be set up with multiple service instances listening on
the same bound socket (on Unix-based systems) by setting up the
following service structure:

* A :class:`VServiceController` controls all service nodes and load balances 
  nodes
* The controller instantiates service node processes with links to the
  controller
* Each node links its service to a :class:`VServiceNode`
* Each :class:`VServiceNode` is controlled by a connected
  :class:`VServiceController`

.. warning::
   
   The example in this recipe is simplified as it does not implement a
   mechanism and logic for shutting down the network, instead we just
   close it after 60 seconds. Alternatives include e.g. using the
   :ref:`daemonize_recipe` recipe on the controller process to trigger
   service shutdown.
   
Below is example code for setting up a service on four processes::

    #!/usr/bin/env python

    from multiprocessing import Process
    import time

    from versile.demo import Echoer
    from versile.orb.service import VServiceController, VServiceNode
    from versile.reactor.io.link import VLinkAgent
    from versile.reactor.quick import VReactor
    from versile.quick import *

    def node_process(l_sock, cntl_sock, server_key):
        """Set up controlled listening service and a link to the controller."""

        # Set up a listening service on l_sock controlled by a VServiceNode
	Versile.set_agpl_internal_use()
        node = VServiceNode()    
        service = VOPService(lambda: Echoer(), auth=None, sock=l_sock,
                             key=server_key, node=node)

        # Set up a link to the service controller, passing the node as the gw
        link = socket_vtp_link(sock=cntl_sock, gw=node, internal=True)
        
        # Wait for service to shut down before returning (which ends process)
        service.wait(stopped=True)
        link.shutdown()

    def main():
        Versile.set_agpl_internal_use()
	
        # Create a listening socket and service controller
        server_listen_sock = VOPService.create_socket()
        controller = VServiceController()

        # Shared processor/reactor for node control links (conserves resources)
        proc = VProcessor(workers=5)
        reactor = VReactor()
        reactor.start()

        # Generate a (random) key for the server VOP transport
        keypair = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 1024/8)

        # Start service nodes in new processes
        processes = []
        for i in xrange(4):
            s_sock, c_sock = socket_pair()
            _p_args = (server_listen_sock, c_sock, keypair)
            p = Process(target=node_process, args=_p_args)
            p.start()

            link = VLinkAgent.from_socket(sock=s_sock, gw=controller,
                                          processor=proc, reactor=reactor,
                                          internal=True)
            node = link.peer_gw()
            controller.add_node(node)
            processes.append(p)

        # Wait 60 seconds before terminating (HARDCODED in this example)
        time.sleep(60)

        # Terminate services
        controller.stop(stop_links=True, force=True)
        for p in processes:
            p.join()
        proc.stop()
        reactor.stop()


    if __name__ == '__main__':
        main()

When the above code is running, the :term:`VRI` ``vop://localhost/``
will resolve as an 'echoer' example gateway object. See the
:ref:`resolve_vri_recipe` recipe for information how to resolve.

As :term:`VPy` multiprocessing support continues to evolve, added
functionality should hopefully provide APIs which can further simplify
the above code example.

.. note::

    One obvious improvement to this example is to add mechanisms which
    allow the nodes to communicate between themselves. As a controller
    link is already set up between the controller process and each
    node process, a star-type network could easily be set up by adding
    a dispatcher object on the controller which is passed to each node
    when the controller link is set up. Once again this is an area we
    expect to see additional support in the platform.
