.. _lib_dispatcher:

Service Dispatchers
===================
.. currentmodule:: versile.manager.dispatch

This is the API documentation for the :class:`VDispatcher` service
dispatcher and supporting classes.

.. todo::

    Should add more documentation, some example code, and a recipe

.. note::

    The dispatcher framework is not yet fully documented.

The :class:`VDispatcher` framework implements a gateway object which
can resolve :term:`VRI` references for multiple dispatched
:class:`VDispatchService` services or hand off sub-paths to other
dispatchers, allowing access to multiple services via a single gateway
object.

:class:`versile.manager.dispatch.store.VDispatchStore` enables storing
configuration for initializing a dispatcher in a file, and
instantiating a dispatcher from dispatcher configuration data.


Module APIs
-----------

Module API for :mod:`versile.manager.dispatch`

.. automodule:: versile.manager.dispatch
    :members:
    :show-inheritance:

Module API for :mod:`versile.manager.store`

.. automodule:: versile.manager.dispatch.store
    :members:
    :show-inheritance:
