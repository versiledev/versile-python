.. _spec_modules:

Specifications
==============

:term:`Versile Python` is an implementation of :term:`Versile
Platform`\ . Below is an overview of :term:`VPy` module(s)
implementing individual platform specifications.

+-----------------------+-------------+-----------------------------------+
| Versile Standard      | Abbrev.     | Primary Module(s)                 |
+=======================+=============+===================================+
| Fundamental Entities  | :term:`VFE` | :mod:`versile.orb.entity`         |
+-----------------------+-------------+-----------------------------------+
| Entity Representation | :term:`VER` | :mod:`versile.orb.module`         |
+-----------------------+-------------+-----------------------------------+
| Standard Entities     | :term:`VSE` | :mod:`versile.vse`                |
+-----------------------+-------------+-----------------------------------+
| Object Behavior       | :term:`VOB` | :mod:`versile.orb.external`       |
+-----------------------+-------------+-----------------------------------+
| Entity Channel        | :term:`VEC` | :mod:`versile.reactor.io.vec`     |
+-----------------------+-------------+-----------------------------------+
| ORB Link              | :term:`VOL` | :mod:`versile.orb.link`\ ,        |
|                       |             | :mod:`versile.reactor.io.link`    |
+-----------------------+-------------+-----------------------------------+
| Object Protocol       | :term:`VOP` | :mod:`versile.reactor.io.vop`\ ,  |
|                       |             | :mod:`versile.reactor.io.url`\ ,  |
|                       |             | :mod:`versile.reactor.io.service` |
+-----------------------+-------------+-----------------------------------+
| Resource Identifier   | :term:`VRI` | :mod:`versile.orb.url`\ ,         |
|                       |             | :mod:`versile.reactor.io.url`     |
+-----------------------+-------------+-----------------------------------+
| Transport Security    | :term:`VTS` | :mod:`versile.reactor.io.vts`     |
+-----------------------+-------------+-----------------------------------+
| UDP Transport         | :term:`VUT` | :mod:`versile.reactor.io.vudp`    |
+-----------------------+-------------+-----------------------------------+
| Crypto Algorithms     | :term:`VCA` | :mod:`versile.crypto`             |
+-----------------------+-------------+-----------------------------------+
