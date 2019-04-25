.. _overview:

Overview
========

:term:`Versile Python` is an implementation for python v2.6+ and
v3.x of :term:`Versile Platform`\ .

Python combines remarkable power with clear syntax and
:term:`VPy` makes service interaction particularly easy. By taking
advantage of flexible python language capabilities, :term:`VPy` offers
a natural syntax for interacting with remote objects as if they were
local.

This overview provides an at-a-glance introduction to some of the
:term:`VPy` capabilities, also additional capabilities are highlighted
in more depth in the :ref:`recipes` section.

.. note::

    The platform is a fairly large and complex framework, so in order
    to get detailed lower level information the :ref:`library` is your
    best source. Also the :term:`VP` specifications is a good
    supplement as it defines protocol and standards implemented by the
    platform.

Python versions
---------------

Versile Python is available as two separate distributions, one for
python v2.6+ and another for v3.x. The two distributions are
functionally equivalent. This API documentation is written in the
style and syntax of python2 including code examples. When applying to
python3, keep in mind syntax differences (e.g. instead of *unicode*
use *str*).

.. _service_interaction_overview:

Service Interaction
-------------------

A program can interact with a remote program or service by creating a
:class:`versile.orb.link.VLink` node and establishing a communication
channel with a peer implementing the :term:`VOP` protocol. After link
handshake completes the program can interact with the peer by
performing remote method calls on peer objects, passing values and
object references to the peer as serializable
:class:`versile.orb.entity.VEntity` data.

Remote object interaction
.........................

Below is a simple example which establishes two locally connected
:class:`versile.orb.link.VLink` end points and then interacts with an
"echo service" reference received from one link peer. Notice the call
to ``echoer.echo()`` as if *echoer* was a local object.

>>> from versile.demo import Echoer
>>> from versile.quick import link_pair
>>> client = link_pair(gw1=None, gw2=Echoer())[0]
>>> echoer = client.peer_gw()
>>> echoer.echo(u'Slartibartfast')
u'Slartibartfast'
>>> client.shutdown()

The platform offers convenient mechanisms for making non-blocking
calls. The below example performs the same call as above, however it
does so with a non-blocking mode and waits maximum 10 seconds for a
call result. Notice the natural syntax.

>>> from versile.demo import Echoer
>>> from versile.quick import link_pair
>>> client = link_pair(gw1=None, gw2=Echoer())[0]
>>> echoer = client.peer_gw()
>>> call = echoer.echo(u'Slartibartfast', nowait=True)
>>> call.result(timeout=10.)
u'Slartibartfast'
>>> client.shutdown()


Setting up a listening service
..............................

The :class:`versile.orb.service` module provides high-level mechanisms
for setting up listening services. Below is a minimalistic example of
setting up a secure :term:`VOP` service which listens for incoming
connections. For each new connection a :class:`versile.orb.link.VLink`
is set up and an *Echoer* gateway object is instantiated and
passed to the peer.

For this example we generate a random server keypair, however the keys
would normally be imported. Notice how little code is required.

>>> from versile.demo import Echoer
>>> from versile.quick import VOPService, VCrypto, VUrandom
>>> keypair = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 1024//8)
>>> service = VOPService(lambda: Echoer(), auth=None, key=keypair)
>>> service.start()
>>> # Simulate (later) service termination on server side
... service.stop(True)

Below is a rewritten version which explicitly passes a gateway object
factory to the service, making the example slightly more readable at
the expense of a few extra lines.

>>> from versile.demo import Echoer
>>> from versile.quick import VOPService, VGatewayFactory
>>> from versile.quick import VCrypto, VUrandom
>>> keypair = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 1024//8)
>>> class GwFactory(VGatewayFactory):
...     def build(self):
...         return Echoer()
...
>>> service = VOPService(GwFactory(), auth=None, key=keypair)
>>> service.start()
>>> # Simulate (later) service termination on server side
... service.stop(True)

Listenening services can also be set up by working directly with
low-level reactor producer/consumer processing elements mechanisms to
set up an I/O chain.

.. note::

   Listening services normally run until they they are terminated. A
   service can terminate itself by calling
   :meth:`versile.orb.service.VService.stop`\ . See the
   :ref:`daemonize_recipe` recipe for an example how to set up a
   service as a daemon with handlers for SIGTERM. Alternatively a
   service can be killed "the hard way" by sending SIGKILL.

Similar to links, global license information must be set on
:class:`versile.Versile` before services can be constructed.

Connecting to a remote object broker
....................................

The typical method for establishing a VLink connection to an ORB is
via a :class:`versile.orb.url.VUrl`\ , which resolves the resource
referenced by a URL. Assuming the echo service object of the earlier
example was served by a remote :term:`VOP` service on 'localhost',
the service could be accessed via :meth:`versile.orb.url.VUrl.resolve`
as showed in the below example.

>>> from versile.demo import Echoer
>>> from versile.quick import VOPService, VCrypto, VUrandom, VUrl
>>> keypair = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 1024//8)
>>> service = VOPService(lambda: Echoer(), auth=None, key=keypair)
>>> service.start()
>>> # Connect to service via URL
... echo_gw = VUrl.resolve('vop://localhost/')
>>> echo_gw.echo(u'Slartibartfast')
u'Slartibartfast'
>>> # Perform explicit link termination
... echo_gw._v_link.shutdown()
>>> # Simulate (later) server-side service termination
... service.stop(True)

Links can also be set up by working directly with low-level reactor
producer/consumer processing elements mechanisms to set up an I/O
chain.

.. note::

    The reliable way to end a link and free up its resources is to
    explicitly terminate the link as we did with the call to
    ``shutdown()`` in the previous example. If all links are not
    terminated before exiting then a program may hang due to
    unfinished threads. Links will normally automatically close when
    no remote references remain in either direction, however due to
    garbage collection effects this is not always a reliable
    mechanism.

Creating remote-enable objects
..............................

By sub-classing :class:`versile.orb.external.VExternal` creating
remote-enabled classes which implement the :term:`VOB` standard is
almost as easy as creating local-only python classes.

Below is an example implementation of an echo service similar to the
example echo service class we imported in the earlier examples. Notice
the code has very little overhead::

    from versile.orb.external import VExternal

    @doc
    class MyEchoer(VExternal):
        """Echo service - receive and return objects."""

        @publish(show=True, doc=True, ctx=False)
        def echo(self, arg):
            """Returns the received argument."""
            return arg

Remote object inspection
........................

When the remote object complies with the :term:`VOB` standard it is
also possible to perform remote inspection of published methods or
documentation. Below is an example.

>>> from versile.demo import Echoer
>>> from versile.quick import link_pair
>>> client, server = link_pair(gw1=None, gw2=Echoer())
>>> service = client.peer_gw()
>>> type(service)
<class 'versile.orb.entity.VProxy'>
>>> service.meta.doc()
u'A simple service object for receiving and echoing a VEntity.\n'
>>> service.meta.methods()
(u'echo',)
>>> dir(service)
[u'echo']
>>> service.meta.doc(u'echo').splitlines()[0]
u'Returns the received argument.'
>>> service.echo(u'Slartibartfast')
u'Slartibartfast'
>>> client.shutdown()

Higher Level Data Types
.......................

The :term:`VSE` framework defines a standard set of higher-level data
types, and it is also possible to define custom data types via the
:term:`VER` framework to pass other data types between link
peers. Below is an example which passes an immutable dictionary.

>>> from versile.vse.container import VFrozenDict
>>> from versile.quick import VSEResolver, VExternal
>>> from versile.quick import publish, doc, link_pair
>>>
>>> @doc
... class ExampleService(VExternal):
...     """Example service - can return a hardcoded dictionary."""
...     @publish(show=True, doc=True, ctx=False)
...     def get_dict(self):
...         """Returns a hardcoded dictionary."""
...         return VFrozenDict({1:100, 2:150})
...
>>> VSEResolver.enable_vse()
>>> client, server = link_pair(gw1=None, gw2=ExampleService())
>>> service = client.peer_gw()
>>> d = service.get_dict()
>>> type(d)
<class 'versile.vse.container.VFrozenDict'>
>>> print(d)
{1: 100, 2: 150}
>>> client.shutdown()

.. testcleanup::

   VSEResolver.enable_vse(False)

There is More ...
.................

This was only a high-level overview of some basic :term:`VPy` usage,
however we have really just scratched the surface of the API. Refer to
the :ref:`library` for additional details.

Other Functionality
-------------------

In order to support the implementation of :term:`Versile Platform`\ ,
:term:`VPy` incluces additional infrastructure for e.g. asynchronous
communication and threaded task execution. Several of these
capabilities have been implemented as stand-alone modules which can be
used for other purposes than interacting with the :term:`VP`
framework. Below are some examples.

.. _reactor_overview:

Reactor
.......

:term:`VPy` implements a reactor for :term:`Reactor Pattern` based
concurrent operations and asynchronous I/O. The framework was
primarily developed to provide a modular framework for setting up and
running :term:`VOL` links. For details about the framework see
:ref:`lib_reactor` and :ref:`lib_reactor_io`\ . Below is a simple
example how the reactor framework can be used to run scheduled events.

>>> import time
>>> from versile.reactor.selectr import VSelectReactor
>>> reactor = VSelectReactor()
>>> def output(msg):
...     print('Message is: %s' % msg)
...
>>> reactor.start()
>>> colors = ('red', 'green', 'blue')
>>> for i in xrange(len(colors)):
...     _call = reactor.schedule(0.01*(i+1), output, colors[i])
...
>>> time.sleep(0.1)
Message is: red
Message is: green
Message is: blue
>>> reactor.stop()

.. _processor_overview:

Processor
.........
.. currentmodule:: versile.common.processor

Whereas :term:`VOL` asynchronous I/O uses a single-thread reactor
pattern, links' received remote method calls are executed with a
thread-based task processor. The processor is a :class:`VProcessor`
which schedules tasks for execution and manages a set of worker
threads. Below is a simple example how to set up a processor.

>>> import time
>>> from versile.common.processor import VProcessor
>>> proc = VProcessor(workers=1)
>>> def output(msg):
...     print('Message is: %s' % msg)
...
>>> colors = ('red', 'green', 'blue')
>>> _call = proc.queue_call(time.sleep, args=(0.01,))
>>> for i in xrange(len(colors)):
...     _call = proc.queue_call(output, args=(colors[i],))
...
>>> time.sleep(0.1)
Message is: red
Message is: green
Message is: blue
>>> proc.stop()
