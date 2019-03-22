.. _lib_quick:

Quick Access
============
.. currentmodule:: versile.quick

The module :mod:`versile.quick` provides quick access to frequently
used classes and functions.

The module also aliases implementations for some abstract base
classes, e.g. :class:`VOPService` provides a :term:`VOP` protocol
implementation of :class:`versile.orb.service.VService`\ , and
:func:`link_pair` provides a function which returns two paired
implementations of the abstract :class:`versile.orb.link.VLink`
class.

For high-level use in applications which do not need to concern itself
with the particular implementation that is used, it is often most
efficient to import classes or functions from :mod:`versile.quick`\
. However, if an application needs to manipulate the APIs of a
particular implementation such as using a shared reactor in the
:class:`versile.reactor.io.service.VOPService` implementation of
:term:`VOP` services, the class should be imported from its parent
module.

Global configuration
--------------------

+--------------------------+-------------------------------------------------+
| Exports                  | Alias For                                       |
+==========================+=================================================+
| :class:`Versile`         | :class:`versile.conf.Versile`                   |
+--------------------------+-------------------------------------------------+

URLs and Services
-----------------

+--------------------------+-------------------------------------------------+
| Exports                  | Alias For                                       |
+==========================+=================================================+
| :class:`VUrl`            | :class:`versile.reactor.io.url.VUrl`            |
+--------------------------+-------------------------------------------------+
| :class:`VOPService`      | :class:`versile.reactor.io.service.VOPService`  |
+--------------------------+-------------------------------------------------+
| :class:`VGatewayFactory` | :class:`versile.orb.service.VGatewayFactory`    |
+--------------------------+-------------------------------------------------+

Links
-----

+-----------------------+-----------------------------------------+
| Exports               | Alias For                               |
+=======================+=========================================+
| :class:`VLinkMonitor` | :class:`versile.orb.util.VLinkMonitor`  |
+-----------------------+-----------------------------------------+

Entities
--------

+-------------------------+-----------------------------------------+
| Exports                 | Alias For                               |
+=========================+=========================================+
| :class:`VBoolean`       | :class:`versile.orb.entity.VBoolean`    |
+-------------------------+-----------------------------------------+
| :class:`VBytes`         | :class:`versile.orb.entity.VBytes`      |
+-------------------------+-----------------------------------------+
| :class:`VEntity`        | :class:`versile.orb.entity.VEntity`     |
+-------------------------+-----------------------------------------+
| :class:`VFloat`         | :class:`versile.orb.entity.VFloat`      |
+-------------------------+-----------------------------------------+
| :class:`VException`     | :class:`versile.orb.entity.VException`  |
+-------------------------+-----------------------------------------+
| :class:`VIOContext`     | :class:`versile.orb.entity.VIOContext`  |
+-------------------------+-----------------------------------------+
| :class:`VInteger`       | :class:`versile.orb.entity.VInteger`    |
+-------------------------+-----------------------------------------+
| :class:`VNone`          | :class:`versile.orb.entity.VNone`       |
+-------------------------+-----------------------------------------+
| :class:`VObject`        | :class:`versile.orb.entity.VObject`     |
+-------------------------+-----------------------------------------+
| :class:`VProxy`         | :class:`versile.orb.entity.VProxy`      |
+-------------------------+-----------------------------------------+
| :class:`VReference`     | :class:`versile.orb.entity.VReference`  |
+-------------------------+-----------------------------------------+
| :class:`VString`        | :class:`versile.orb.entity.VString`     |
+-------------------------+-----------------------------------------+
| :class:`VTagged`        | :class:`versile.orb.entity.VTagged`     |
+-------------------------+-----------------------------------------+
| :class:`VTuple`         | :class:`versile.orb.entity.VTuple`      |
+-------------------------+-----------------------------------------+

VExternal
---------

+----------------------+-----------------------------------------+
| Exports              | Alias For                               |
+======================+=========================================+
| :class:`VExternal`   | :class:`versile.orb.external.VExternal` |
+----------------------+-----------------------------------------+
| :func:`doc`          | :func:`versile.orb.external.doc`        |
+----------------------+-----------------------------------------+
| :func:`doc_with`     | :func:`versile.orb.external.doc_with`   |
+----------------------+-----------------------------------------+
| :func:`meta`         | :func:`versile.orb.external.meta`       |
+----------------------+-----------------------------------------+
| :func:`meta_as`      | :func:`versile.orb.external.meta_as`    |
+----------------------+-----------------------------------------+
| :func:`publish`      | :func:`versile.orb.external.publish`    |
+----------------------+-----------------------------------------+

Standard Entities
-----------------

+----------------------+-----------------------------------------+
| Exports              | Alias For                               |
+======================+=========================================+
| :class:`VSEResolver` | :class:`versile.vse.VSEResolver`        |
+----------------------+-----------------------------------------+

Argument validation
-------------------

+----------------------+-----------------------------------------+
| Exports              | Alias For                               |
+======================+=========================================+
| :func:`vchk`         | :func:`versile.orb.validate.vchk`       |
+----------------------+-----------------------------------------+
| :func:`vmax`         | :func:`versile.orb.validate.vmax`       |
+----------------------+-----------------------------------------+
| :func:`vmin`         | :func:`versile.orb.validate.vmin`       |
+----------------------+-----------------------------------------+
| :func:`vset`         | :func:`versile.orb.validate.vset`       |
+----------------------+-----------------------------------------+
| :func:`vtyp`         | :func:`versile.orb.validate.vtyp`       |
+----------------------+-----------------------------------------+

Cryptography/Security
---------------------

+---------------------------+----------------------------------------------------+
| Exports                   | Alias For                                          |
+===========================+====================================================+
| :class:`VCrypto`          | :class:`versile.crypto.VCrypto`                    |
+---------------------------+----------------------------------------------------+
| :class:`VAuth`            | :class:`versile.crypto.auth.VAuth`                 |
+---------------------------+----------------------------------------------------+
| :class:`VUrandom`         | :class:`versile.crypto.rand.VUrandom`              |
+---------------------------+----------------------------------------------------+
| :class:`VX509Certificate` | :class:`versile.crypto.x509.cert.VX509Certificate` |
+---------------------------+----------------------------------------------------+
| :class:`VX509Crypto`      | :class:`versile.crypto.x509.VX509Crypto`           |
+---------------------------+----------------------------------------------------+
| :class:`VX509Format`      | :class:`versile.crypto.x509.VX509Format`           |
+---------------------------+----------------------------------------------------+
| :class:`VX509Name`        | :class:`versile.crypto.x509.cert.VX509Name`        |
+---------------------------+----------------------------------------------------+

Common classes
--------------

+----------------------------+----------------------------------------------+
| Exports                    | Alias For                                    |
+============================+==============================================+
| :class:`VByteBuffer`       | :class:`versile.common.util.VByteBuffer`     |
+----------------------------+----------------------------------------------+
| :class:`VLockable`         | :class:`versile.common.util.VLockable`       |
+----------------------------+----------------------------------------------+
| :class:`VProcessor`        | :class:`versile.common.processor.VProcessor` |
+----------------------------+----------------------------------------------+
| :class:`VResult`           | :class:`versile.common.util.VResult`         |
+----------------------------+----------------------------------------------+


Exceptions
----------

+----------------------------+-------------------------------------------------+
| Exports                    | Alias For                                       |
+============================+=================================================+
| :exc:`VCallError`          | :exc:`versile.orb.entity.VCallError`            |
+----------------------------+-------------------------------------------------+
| :exc:`VCancelledResult`    | :exc:`versile.common.util.VCancelledResult`     |
+----------------------------+-------------------------------------------------+
| :exc:`VCryptoException`    | :exc:`versile.crypto.VCryptoException`          |
+----------------------------+-------------------------------------------------+
| :exc:`VEntityError`        | :exc:`versile.orb.error.VEntityError`           |
+----------------------------+-------------------------------------------------+
| :exc:`VEntityReaderError`  | :exc:`versile.orb.error.VEntityReaderError`     |
+----------------------------+-------------------------------------------------+
| :exc:`VEntityWriterError`  | :exc:`versile.orb.error.VEntityWriterError`     |
+----------------------------+-------------------------------------------------+
| :exc:`VHaveResult`         | :exc:`versile.common.util.VHaveResult`          |
+----------------------------+-------------------------------------------------+
| :exc:`VLinkError`          | :exc:`versile.orb.error.VLinkError`             |
+----------------------------+-------------------------------------------------+
| :exc:`VNoResult`           | :exc:`versile.common.util.VNoResult`            |
+----------------------------+-------------------------------------------------+
| :exc:`VProcessorError`     | :exc:`versile.common.processor.VProcessorError` |
+----------------------------+-------------------------------------------------+
| :exc:`VSimulatedException` | :exc:`versile.orb.entity.VSimulatedException`   |
+----------------------------+-------------------------------------------------+
| :exc:`VUrlException`       | :exc:`versile.orb.url.VUrlException`            |
+----------------------------+-------------------------------------------------+

Functions
---------

+-------------------------+----------------------------------------------------------------+
| Exports                 | Alias For                                                      |
+=========================+================================================================+
| :func:`link_pair`       | :meth:`versile.reactor.io.link.VLinkAgent.create_pair`         |
+-------------------------+----------------------------------------------------------------+
| :func:`socket_pair`     | :meth:`versile.reactor.io.sock.VSocketBase.create_native_pair` |
+-------------------------+----------------------------------------------------------------+
| :func:`socket_vtp_link` | :meth:`versile.reactor.io.link.VLinkAgent.from_socket`         |
+-------------------------+----------------------------------------------------------------+
