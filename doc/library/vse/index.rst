.. _lib_vse:

Standard Entities
=================
.. currentmodule:: versile.vse

This is the API documentation for the implementation of the
:term:`VSE` specification. The :term:`VSE` standard defines a set of
higher-level data types which allows two link peers implementing the
complete :term:`VP` specification to pass these data types between
them. The data types are implemented as a set of python modules and
associated :class:`versile.orb.module.VModule` classes.

.. note::
   
   The :term:`VSE` standard currently defines only a small set of
   classes as development is initially focused on core :term:`VPy`
   internals.

See the following categories of available :term:`VSE` types:

.. hidden toctree (hidden for html)
.. toctree::
   :hidden:
   :maxdepth: 1
   :glob:
   
   container
   math
   native
   semantics
   stream
   time
   util

.. only:: html

    * :doc:`container`
    * :doc:`math`
    * :doc:`native`
    * :doc:`semantics`
    * :doc:`stream`
    * :doc:`time`
    * :doc:`util`

:class:`VSEResolver` is a module resolver which resolves all supported
:term:`VSE` types. The class method :meth:`VSEResolver.add_imports`
registers all :term:`VSE` modules as globally available modules.


Module APIs
-----------

Module API for :mod:`versile.vse`

.. automodule:: versile.vse
    :members:
    :show-inheritance:
