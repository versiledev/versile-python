.. _lib_container:

Containers
==========
.. currentmodule:: versile.vse.container

The module :mod:`versile.vse.container` includes container classes for
:class:`versile.orb.entity.VEntity` data. The following :term:`VSE`
types are registered with :class:`VContainerModule`\ .

+----------------------------+-------------------------------+
| Type                       | Description                   | 
+============================+===============================+
| :class:`VFrozenDict`       | Immutable dictionary          |
+----------------------------+-------------------------------+
| :class:`VFrozenSet`        | Immutable set                 |
+----------------------------+-------------------------------+
| :class:`VFrozenMultiArray` | Immutable N-dimensional array |
+----------------------------+-------------------------------+

Below is an example of creating a :class:`VFrozenSet` container
object.

>>> from versile.vse.container import VFrozenSet
>>> fs = VFrozenSet(frozenset((1, 3, 5, 7)))
>>> type(fs)
<class 'versile.vse.container.VFrozenSet'>
>>> 3 in fs
True
>>> 4 in fs
False
>>> fs._v_native()
frozenset([1, 3, 5, 7])

The native type :class:`frozenset` is also recognized as a native type
which can be lazy-converted to an entity type, as seen in the below
example:

>>> from versile.orb.entity import VEntity
>>> from versile.vse import VSEResolver
>>> parser = VSEResolver()
>>> s = frozenset((1, 3, 5, 7))
>>> fs = VEntity._v_lazy(s, parser=parser)
>>> type(fs)
<class 'versile.vse.container.VFrozenSet'>


Module APIs
-----------

Module API for :mod:`versile.vse.container`

.. automodule:: versile.vse.container
    :members:
    :show-inheritance:
