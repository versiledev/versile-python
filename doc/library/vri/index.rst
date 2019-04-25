.. _lib_url:

Resource Identifiers
====================
.. currentmodule:: versile.orb.url

:class:`VUrl` provides a mechanism for resolving a resource accessible
over the :term:`VOP` protocol and identified by a :term:`VRI`\ .

A :class:`VUrl` can assist with parsing a :term:`VRI`\ , establishing
a link to the ORB providing the resource and and retreiving the
resource from the link gateway object. The :class:`VUrl` base class is
abstract and :term:`VPy` provides :class:`versile.reactor.io.url.VUrl`
which is a reactor based implementation.

When it is not important which :class:`VUrl` implementation is used,
the most convenient way to obtain an implementation is by importing
from :mod:`versile.quick`\ .

Setting up links with VUrl
--------------------------

A :term:`VRI` can be parsed and resolved in one step with the class
method :meth:`VUrl.resolve`\ . Below is an example which obtains a
reference to a resource. Note that the example has overhead to set up
the service; a client would only execute code in the 'client-side
code' section.

>>> # Server-side code to set up a VOP service
... from versile.demo import Echoer
>>> from versile.quick import VOPService, VCrypto, VUrandom
>>> server_key = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 1024//8)
>>> gw_factory = lambda: Echoer()
>>> service = VOPService(gw_factory, auth=None, key=server_key)
>>> service.start()
>>>
>>> # CLIENT-SIDE CODE - connect with VUrl
... from versile.quick import VUrl
>>> resource = VUrl.resolve('vop://localhost/')
>>> resource.echo(u'Test message')
u'Test message'
>>> resource._v_link.shutdown()
>>>
>>> # Server-side service termination
... service.stop(True)

Alternatively, the steps involved in obtaining a reference of parsing
a :term:`VRI`\ , connecting to an ORB and resolving a resource on the
peer can be performed in separate steps.

* Parse a VRI with :meth:`VUrl.parse` returning a :class:`VUrl`
* Connecting to the owning ORB with :meth:`VUrl.connect`
* Use :meth:`VUrlResolver.resolve` to retreive the resource from peer

Below is another version of the earlier example which performs these
three steps in sequence:

>>> # Server-side code to set up a VOP service
... from versile.demo import Echoer
>>> from versile.quick import VOPService, VCrypto, VUrandom
>>> server_key = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 1024//8)
>>> gw_factory = lambda: Echoer()
>>> service = VOPService(gw_factory, auth=None, key=server_key)
>>> service.start()
>>>
>>> # CLIENT-SIDE CODE - connect with VUrl
... from versile.quick import VUrl
>>> url = VUrl.parse('vop://localhost/')
>>> resolver = url.connect()
>>> resource = resolver.resolve()
>>> resource.echo(u'Test message')
u'Test message'
>>> resource._v_link.shutdown()
>>>
>>> # Server-side service termination
... service.stop(True)

.. note::

   :meth:`VUrl.resolve`\ , :meth:`VUrl.connect` and
   :meth:`VUrlResolver.resolve` can be performed as non-blocking
   operations by providing a *nowait* keyword, see documentation for
   details.

The above examples import an implementation of :class:`VUrl` from
:mod:`versile.quick`\ . If implementation-specific capabilities are to
be used, then the required implementation should be imported directly
instead.

:term:`VPy` provides the reactor-based implementation
:class:`versile.reactor.io.url.VUrl`\ , which is the implementation
provided by :mod:`versile.quick`\ . In some cases it may be desirable
to work with this class directly. Below is an alternative version of
the earlier example which uses the specific implementation.

.. todo::

   When implemented should include an example of sharing reactor and
   processor between multiple VUrls

>>> # Server-side code to set up a VOP service
... from versile.demo import Echoer
>>> from versile.quick import VOPService, VCrypto, VUrandom
>>> server_key = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 1024//8)
>>> gw_factory = lambda: Echoer()
>>> service = VOPService(gw_factory, auth=None, key=server_key)
>>> service.start()
>>>
>>> # CLIENT-SIDE CODE - connect with VUrl
... from versile.reactor.io.url import VUrl
>>> resource = VUrl.resolve('vop://localhost/')
>>> resource.echo(u'Test message')
u'Test message'
>>> resource._v_link.shutdown()
>>>
>>> # Server-side service termination
... service.stop(True)

As the examples show, :class:`VUrl` provides a very convenient
mechanism for easily and quickly accessing :term:`VRI` resources.

VUrl configuration
------------------

Several properties of a link set up by a :class:`VUrl` can be
configured by passing a :class:`VUrlConfig` configuration object to
:meth:`VUrl.connect`\ , see documentation of the relevant
configuration objects for details.

An example of one such configuration option is the default
configuration setting to lazy-create a :term:`VER` parser for any
modules which have been imported at the time the call to
:meth:`VUrl.connect` is made. Callers need to make sure any required
modules have already been loaded (e.g. by calling
:meth:`versile.vse.VSEResolver.add_imports` for :term:`VSE` classes),
or supply a configuration object which provides a
parser. Alternatively, lazy-creation of a :term:`VER` resolver can be
switched off by setting the appropriate option on the configuration
object.

The above example is just one configuration setting, see
:class:`VUrlConfig` documentation for additional options.

Module APIs
-----------

URLs
....
Module API for :mod:`versile.orb.url`

.. automodule:: versile.orb.url
    :members:
    :show-inheritance:

Reactor URLs
............
Module API for :mod:`versile.reactor.io.url`

.. automodule:: versile.reactor.io.url
    :members:
    :show-inheritance:
