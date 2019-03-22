.. _lib_demo:

Demo Classes
============
.. currentmodule:: versile.demo

The module :mod:`versile.demo` includes classes or functionality which
can be used is used in :term:`VPy` code examples and can be used in
:term:`VPy` testing.

.. warning::
   
   :mod:`versile.demo` is not formally part of the :term:`VPy`
   library. Its APIs is unstable and may change or be removed in any
   release. External code should never use these classes. The only
   time you should use them is when running code examples or doing
   simple interactive testing.

Classes defined in this module are primarily intended for enabling
simpler documentation code examples.

Current Module Content
----------------------

* :class:`Echoer` implements a simple
  :class:`versile.orb.external.VExternal`
* :class:`Adder` tracks a rolling partial sum and demonstrates stateful
  remote objects
* :class:`SimpleGateway` provides a link gateway for simulating
  :term:`VRI` access to a :class:`Echoer` and :class:`Adder`

Module APIs
-----------

Module API for :mod:`versile.demo`

.. automodule:: versile.demo
    :members:
    :show-inheritance:
