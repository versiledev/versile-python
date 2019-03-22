.. _lib_util:

Utility Classes
===============
.. currentmodule:: versile.vse.util

The module :mod:`versile.vse.util` includes :term:`VSE` utility
classes. 

The following :term:`VSE` types are registered with
:class:`VUtilityModule`\ .

+-------------------------+--------------------------------------------+
| Type                    | Description                                | 
+=========================+============================================+
| :class:`VFunctionProxy` | Remotely callable function                 |
+-------------------------+--------------------------------------------+
| :class:`VUDPRelay`      | Relay for :term:`VUT` transport            |
+-------------------------+--------------------------------------------+
| :class:`VUDPRelayedVOP` | Relay for :term:`VOP` over :term:`VUT`     |
+-------------------------+--------------------------------------------+
| :class:`VPasswordLogin` | User/password login for accessing resource |
+-------------------------+--------------------------------------------+

Below is an example of creating a function and accessing it via an
associated :class:`VFunctionProxy` (which can be remotely
decoded).

>>> from versile.vse.util import *
>>> def f(a, b):
...     return a*b
... 
>>> vf = VFunction(f)
>>> proxy = vf.proxy
>>> type(proxy)
<class 'versile.vse.util.VFunctionProxy'>
>>> proxy(3, 4)
12

Note that :class:`VFunction` can be passed directly as an entity; it
will encode to a :term:`VER` format which decodes as a
:class:`VFunctionProxy`\ .

Module APIs
-----------

Module API for :mod:`versile.vse.util`

.. automodule:: versile.vse.util
    :members:
    :show-inheritance:
