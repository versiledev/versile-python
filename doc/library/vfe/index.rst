.. _lib_entities:
.. currentmodule:: versile.orb.entity

Entities and Referenced Objects
===============================

This is the API documentation for the implementation of the
:term:`VFE` specification including data entities, objects and object
references.

VEntity
-------

The class :class:`VEntity` is an entity which implements a :term:`VP`
VEntity type. Derived entity classes with serialization defined by
:term:`VP` can be passed between :term:`VOL` peers.

Method names of library VEntity classes generally have a name starting
with a '_v_' prefix, even for public methods. The reason for this
deviation from standard python conventions is to avoid collisions
between API methods and method names of derived classes for referenced
objects.
     

Data Types
..........

The module :mod:`versile.orb.entity` defines the :class:`VEntity`
classes listed in the below table. Classes of type 'Data' hold a
single immutable data value. Object and Reference classes ('Obj/Ref')
hold an object or a reference to a remote object. 'Composite' classes
are containers for other :class:`VEntity` objects.

+---------------------+-----------+------------------------------------+
| Class               | Type      | Description                        |
+=====================+===========+====================================+
| :class:`VBoolean`   | Data      | Boolean (True/False)               |
+---------------------+-----------+------------------------------------+
| :class:`VBytes`     | Data      | Byte vector                        |
+---------------------+-----------+------------------------------------+
| :class:`VFloat`     | Data      | Arbitrary-precision floating point |
+---------------------+-----------+------------------------------------+
| :class:`VInteger`   | Data      | Arbitrary-size signed integer      |
+---------------------+-----------+------------------------------------+
| :class:`VNone`      | Data      | Represents 'no value'              |
+---------------------+-----------+------------------------------------+
| :class:`VString`    | Data      | String                             |
+---------------------+-----------+------------------------------------+
| :class:`VObject`    | Obj/Ref   | Object which can be referenced     |
+---------------------+-----------+------------------------------------+
| :class:`VReference` | Obj/Ref   | Reference to an object             |
+---------------------+-----------+------------------------------------+
| :class:`VException` | Composite | Exception                          |
+---------------------+-----------+------------------------------------+
| :class:`VTagged`    | Composite | One value with 0+ tags             |
+---------------------+-----------+------------------------------------+
| :class:`VTuple`     | Composite | An n-tuple of elements             |
+---------------------+-----------+------------------------------------+

Converting to/from native types
...............................

Most of the above data types are representations of a native python
type and can be created directly from that type with the class
constructor. Data types which map directly to/from a native type can
be lazy-converted to a :class:`VEntity` with the
:meth:`VEntity._v_lazy` class method.

>>> from versile.orb.entity import *
>>> VInteger(3)
3
>>> VFloat(0.125)
0.125
>>> VBytes(b'\x00\x01\x02')
'\x00\x01\x02'
>>> VString(u'hello')
u'hello'
>>> VTuple((3, u'hello'))
(3, u'hello')
>>> VTuple(3, u'hello')
(3, u'hello')
>>> # Simplest method is to use lazy-conversion
... entity = VEntity._v_lazy(42)
>>> type(entity)
<class 'versile.orb.entity.VInteger'>

Note that a :class:`VTuple` can be lazy-created from a tuple, however
a list object will not. This is a design decision because
:class:`VTuple` element sequencing is immutable, whereas :class:`list`
objects are not.

>>> from versile.orb.entity import *
>>> VEntity._v_lazy((1, 2, 3))
(1, 2, 3)
>>> try:
...   VEntity._v_lazy([1, 2, 3])
... except:
...   print('exception')
... 
exception

:class:`VEntity` objects can be converted to a native type with the
:class:`VEntity._v_native` method, or with the
:class:`VEntity._v_lazy_native` class method. If an object cannot be
converted to a native type, a reference to the object itself is
typically returned.

>>> from versile.orb.entity import *
>>> entity = VInteger(42)
>>> entity._v_native()
42
>>> type(_)
<type 'int'>
>>> VEntity._v_lazy_native(entity)
42
>>> type(_)
<type 'int'>

Working with VEntity data
.........................

Several :class:`VEntity` classes overload python operators, often
allowing the classes to be used similar to their corresponding native
types. Overloading is documented for the individual classes.

>>> from versile.orb.entity import *
>>> VInteger(3) + VInteger(4)
7
>>> type(_)
<class 'versile.orb.entity.VInteger'>
>>> t = VTuple(1, 4, 6)
>>> list(iter(t))
[1, 4, 6]
>>> len(t)
3

Serializing VEntity data
........................

Serialization is defined by the :term:`VFE` specifications. Entities
can be serialized by calling :meth:`VEntity._v_write` on the
entity. Serializing data types which do not include objects or
references requires a :class:`VIOContext`\ .

>>> from versile.orb.entity import *
>>> ctx = VIOContext()
>>> VInteger(1024)._v_write(ctx)
'\xef\xf8\x02\x1b'
>>> VInteger(392)._v_write(ctx)
'\xef\x9a'
>>> VBoolean(True)._v_write(ctx)
'\xf2'
>>> VTuple(10, 11, 12)._v_write(ctx)
'\xf6\x03\x0b\x0c\r'

An entity can also be serialized by calling :meth:`VEntity._v_write`
to create a :class:`VEntityWriter`\ .

>>> from versile.orb.entity import *
>>> ctx = VIOContext()
>>> writer = VInteger(1024)._v_writer(ctx)
>>> writer.write(65536)
'\xef\xf8\x02\x1b'
>>> # Can also use as an iterator (but slower)
... writer = VInteger(1024)._v_writer(ctx)
>>> b''.join(list(iter(writer)))
'\xef\xf8\x02\x1b'

Serialization of :class:`VObject` or composite types which include
such objects requires a :class:`VObjectIOContext` instead of the above
:class:`VIOContext`\ . This is because remote references involves code
for handling local and remote object ID spaces.

Applications normally do not need to deal with serialization when
passing entities over a :term:`VOL` as this is handled by the link.

Reconstructing from serialized data
...................................

A :class:`VEntity` can be reconstructed from its serialized
representation by using a :class:`VEntityReader`\ . The reader
requires a context object similar to serialization methods. Typically
a reader is created by calling the class method
:meth:`VEntity._v_reader`\ .

>>> from versile.orb.entity import *
>>> ctx = VIOContext()
>>> data = VString(u'coconut')._v_write(ctx)
>>> data
'\xf5\x04\x07coconututf8'
>>> reader = VEntity._v_reader(ctx)
>>> reader.read(data)
14
>>> reader.done()
True
>>> reader.result()
u'coconut'
>>> type(_)
<class 'versile.orb.entity.VString'>

.. _lib_vobject:

Objects and References
----------------------

VEntity includes a class :class:`VObject` for objects which can be
remotely referenced, and :class:`VReference` for references to remote
:class:`VObject` objects. The class :class:`VProxy` can be used as a
proxy mechanism for accessing an object or reference using the same
interface.

VObject
.......

The class :class:`VObject` represents an object that may be remotely
referenced. It includes low-level functionality for enabling external
interaction with the object. Applications should normally not work
with VObject directly, but instead use the higher level
:ref:`lib_external` mechanisms which implement the :term:`VOB`
standard interface conventions and offers more API support for the
programmer.

.. note::

   For higher-level programming you should normally use
   :ref:`lib_external` instead of working directly with
   :class:`VObject`

:class:`VObject` instantiation is normally performed without
arguments, though a processor may be explicitly defined (which is then
used for handling remote method calls on the object). Serialization is
similar to other VEntity objects, except it requires a
:class:`VObjectIOContext` which manages the object ID space for a
context.

.. warning::
   
   :class:`VObjectIOContext` does not implement handling of object
   dereferences, which needs to be implemented in derived
   classes. E.g. :class:`versile.orb.link.VLink` overrides context
   behavior to integrate with the :term:`VOL` protocol specifications
   for dereferencing remote objects.

I/O with :class:`VObjectIOContext` assumes serialized data is passed
between two communicating parties, where each serialization of data by
one party is decoded (exactly once) by the other. The split
encode/decode responsibility matters because an object ID which is
serialized as a "local ID" by the writer must be interpreted as a
"remote ID" by a peer relative to the ID space which that peer is
managing.

.. note::

    :class:`VObjectIOContext` data serialized in one context should
    only be reconstructed in the communication peer's context

Below is a simple example of object instantiation and serialization to
show it uses the same serialization mechisms as other :class:`VEntity`
objects. The example simulates communication between two parties which
each operate with their own I/O context setup.

Notice how a local :class:`VObject` on side 'A' resolves as a
:class:`VReference` when it is reconstructed by side 'B', and how that
reference on the 'B' side reconstructs to the original object.

>>> from versile.orb.entity import *
>>> # From the point of view of side 'A'
... ctx_a = VObjectIOContext()
>>> orig_a = VObject()
>>> data = orig_a._v_write(ctx_a)
>>> # From the point of view of side 'B'
... ctx_b = VObjectIOContext()
>>> reader = VEntity._v_reader(ctx_b)
>>> reader.read(data)
2
>>> ref_b = reader.result()
>>> type(ref_b)
<class 'versile.orb.entity.VReference'>
>>> ref_b is orig_a
False
>>> data2 = ref_b._v_write(ctx_b)
>>> # From the point of view of side 'A'
... reader = VEntity._v_reader(ctx_a)
>>> reader.read(data2)
2
>>> obj_a = reader.result()
>>> obj_a is orig_a
True

External methods
................

The :term:`VOL` specifications defines a protocol for making "remote
calls" on a :class:`VObject` to access object functionality, which is
the primary reason why references are useful in the first place.

A remote call is just a list of :class:`VEntity` elements passed to
the object. Classes derived from :class:`VObject` can override
:meth:`VObject._v_execute` to define a handler for a remote call. The
handler is invoked by another method :meth:`VObject._v_call` which is
the low-level interface for calling a method on an object.

.. note::

   When using the standard :term:`VOB` call convention, the first
   argument in a remote call argument list is considered to be a
   "method name" in the form of a string, as is the standard for
   :ref:`lib_external`\ . However it is possible to use other schemes.

The :meth:`VObject._v_execute` method should do one of the following:

* Return a :class:`VEntity` result of the call
* Raise a :class:`VException` if the call could be
  parsed but not properly executed
* Raise :class:`VCallError` if the call could not
  be parsed (i.e. a problem with the call itself)

When working with a layer which performs lazy-conversion on
:class:`VEntity` data (such as a link with lazy-conversion enabled) it
is sufficient to return data which can be lazy-converted to
:class:`VEntity`, and arguments received may also be data which has
been lazy-converted to a native type.

Below is a simple example of an object which performs a remote 'add'
operation. The example assumes input/output data is lazy-converted, so
the example does not use :class:`VEntity` data types for arguments or
return values.

>>> from versile.orb.entity import *
>>> class Adder(VObject):
...   def _v_execute(self, *args, **kargs):
...     if len(args) >= 2 and args[0] == u'add':
...       try:
...         result = sum((args[1:]))
...       except:
...         raise VException(u'Add error')
...       else:
...         return result
...     else:
...       raise VCallError(u'Invalid call')
... 
>>> adder = Adder()
>>> # Note that _v_call is normally not called directly, see comments
... adder._v_call(u'add', 1, 2, 3, 4, 5)
15
>>> try:
...   adder._v_call(u'add', 1, u'not_a_number', 3, 4, 5)
... except Exception as e:
...   print('exception:', e)
... 
('exception:', (u'Add error',))
>>> try:
...   adder._v_call(u'multiply', 1, 2, 3, 4, 5)
... except Exception as e:
...   print('exception:', e)
... 
('exception:', VCallError(u'Invalid call',))

.. note::

   Applications should normally not call :meth:`VObject._v_call`
   directly, but instead work through a :class:`VProxy` reference to
   the object.

:meth:`VObject._v_execute` can also take a keyword argument *ctx*
which is a context object for the call. This is a mechanism which is
not exposed externally in the :term:`VOL` protocol but can be used to
pass seession data internally, such as information about an
authenticated user. See method documentation for details.

Object references
.................

The class :class:`VReference` represents a reference to a remote
:class:`VObject`\ . The reference is tracked internally as a remote
object ID registered on a :class:`VObjectIOContext`\ . A
:class:`VReference` acts as a placeholder for a remote object and
enables performing actions on a remote object (via a link).

The below example shows how we could call the "Adder" class of the
earlier example via a remote reference. Note that the example includes
some code for setting up a link context, to generate a remote
reference we can interact with. The real meat of the example is the
call to :meth:`VReference._v_call`\ .

>>> # Various code to set up a link context with a remote object reference
... from versile.orb.entity import *
>>> from versile.quick import Versile, link_pair
>>> class Adder(VObject):
...   def _v_execute(self, *args, **kargs):
...     if len(args) >= 2 and args[0] == u'add':
...       try:
...         result = sum((args[1:]))
...       except:
...         raise VException(u'Add error')
...       else:
...         return result
...     else:
...       raise VCallError(u'Invalid call')
... 
>>> Versile.set_agpl_internal_use()
>>> l1, l2 = link_pair(None, Adder())
>>> remote = l1.peer_gw()
>>> # This line is here because 'remote' is a VProxy
... reference = remote()
>>> # THE REAL MEAT OF THIS EXAMPLE
... type(reference)
<class 'versile.orb.link.VLinkReference'>
>>> reference._v_call(u'add', 1, 2, 3, 4, 5)
15
>>> # Overhead code for shutting down the link
... l1.shutdown()

.. testcleanup::

   from versile.conf import Versile
   Versile._reset_copyleft()

So the pieces are starting to come together; when the appropriate link
and processor infrastructure is set up, method calls on
:class:`VReference` can be performed via the
:meth:`VReference._v_call`\ , similar to how a local :class:`VObject`
operates. In fact a :class:`VReference` is a child class of
:class:`VObject`, which is for two reasons:

* The reference supports the same external functionality with the same
  set of methods as a referencable object, including method calls and
  serialization
* An object which is a reference in one :class:`VObjectIOContext` can
  be interpreted as a native object object in another
  :class:`VObjectIOContext`\ , allowing an object to be referenced via
  multiple contexts.

The last point requires some explanation. Suppose three programs A, B
and C are connected by communication links A-B and B-C .

* An object obj\ :sub:`a` passed to B becomes ref\ :sub:`b` at the B
  side
* The serialized data received by B would not make any sense to C
  which has no shared context with A, so it cannot be passed to C by B
* However, as ref\ :sub:`b` can also be interpreted as an object, it
  can be passed by B as a 'reference to a local object' to C, received
  as ref\ :sub:`c`
* The end result is ref\ :sub:`c` points to ref\ :sub:`b` which points
  to obj\ :sub:`a`

Programs should normally not interact directly with :class:`VObject`
or :class:`VReference` object, but instead work via the
:class:`VProxy` mechanism. That way they can be transparently accessed
via the same programmer-friendly interfaces.

Accessing objects and references via VProxy
...........................................

The syntax for performing remote method calls directly on a
:class:`VObject` or :class:`VReference` can be a bit cumbersome and
verbose, and so the :class:`VProxy` class is the preferred mechanism
for accessing objects and references. It uses aliasing to dynamically
generate remote calls with the attribute name as the first argument
passed as a string, as is the typical call convention for remote
objects.

Below is a modification of the earlier remote call example where the
call is now being performed directly on the proxy object. Notice how
we call add() on 'remote' which is a proxy for the remote object
reference, just as if it had been a local object.

>>> # Initialization code to set up a link with a remote object reference     
... from versile.orb.entity import *
>>> from versile.quick import Versile, link_pair
>>> class Adder(VObject):
...   def _v_execute(self, *args, **kargs):
...     if len(args) >= 2 and args[0] == u'add':
...       try:
...         result = sum((args[1:]))
...       except:
...         raise VException(u'Add error')
...       else:
...         return result
...     else:
...       raise VCallError(u'Invalid call')
... 
>>> Versile.set_agpl_internal_use()
>>> l1, l2 = link_pair(None, Adder())
>>> remote = l1.peer_gw()
>>> # HERE WE INTERACT WITH THE REMOTE OBJECT VIA A VPROXY
... type(remote)
<class 'versile.orb.entity.VProxy'>
>>> remote.add(1, 2, 3, 4, 5)
15
>>> l1.shutdown()

.. testcleanup::

   from versile.conf import Versile
   Versile._reset_copyleft()

The reference to 'add' generates a callable which will trigger the
appropriate remote call for this method name. The below code shows
what is going on:

>>> # Set up link
... from versile.orb.entity import *
>>> from versile.quick import Versile, link_pair
>>> class Adder(VObject):
...   def _v_execute(self, *args, **kargs):
...     if len(args) >= 2 and args[0] == u'add':
...       try:
...         result = sum((args[1:]))
...       except:
...         raise VException(u'Add error')
...       else:
...         return result
...     else:
...       raise VCallError(u'Invalid call')
... 
>>> Versile.set_agpl_internal_use()
>>> l1, l2 = link_pair(None, Adder())
>>> remote = l1.peer_gw()
>>> # Demonstrated functionality
... caller = remote.add
>>> type(caller)
<class 'versile.orb.entity._VProxyMethod'>
>>> caller(1, 2, 3, 4, 5)
15
>>> type(remote)
<class 'versile.orb.entity.VProxy'>
>>> remote.add(1, 2, 3, 4, 5)
15
>>> # Shut down link
... l1.shutdown()

.. testcleanup::

   from versile.conf import Versile
   Versile._reset_copyleft()

A proxy can be created from a :class:`VObject` or :class:`VReference`
via the :meth:`VObject._v_proxy` method. The object or reference can
be retreived from the proxy by invoking :meth:`VProxy.__call__`\
. Note that a processor needs to be registered with the proxy during
creation in order to support some of the call modes mentioned
later. Below is a simple example of conversion to/from proxy objects:

>>> from versile.orb.entity import *
>>> obj = VObject()
>>> proxy = obj._v_proxy()
>>> type(proxy)
<class 'versile.orb.entity.VProxy'>
>>> proxied = proxy()
>>> proxied is obj
True

The :class:`VProxy` class also supports making 'meta-calls' as defined
by the :term:`VOB` standard, see :ref:`lib_external` documentation for
details.

:class:`VProxy` provides a convenient interface for performing
asynchronous calls or making calls with other supported call modes, by
using keywords to set the call mode. The below code shows how the
earlier remote method call could be performed in non-blocking mode.

>>> # Set up link
... from versile.orb.entity import *
>>> from versile.quick import Versile, link_pair
>>> class Adder(VObject):
...   def _v_execute(self, *args, **kargs):
...     if len(args) >= 2 and args[0] == u'add':
...       try:
...         result = sum((args[1:]))
...       except:
...         raise VException(u'Add error')
...       else:
...         return result
...     else:
...       raise VCallError(u'Invalid call')
... 
>>> Versile.set_agpl_internal_use()
>>> l1, l2 = link_pair(None, Adder())
>>> remote = l1.peer_gw()
>>> # Demonstrated functionality
... call = remote.add(1, 2, 3, 4, 5, nowait=True)
>>> call.wait()
>>> call.result()
15
>>> # Shut down link
... l1.shutdown()

.. testcleanup::

   from versile.conf import Versile
   Versile._reset_copyleft()


Module APIs
-----------

Entities
........
Module API for :mod:`versile.orb.entity`

.. automodule:: versile.orb.entity
    :members:
    :show-inheritance:

Errors
......
Module API for :mod:`versile.orb.error`

.. automodule:: versile.orb.error
    :members:
    :show-inheritance:

Util
....
Module API for :mod:`versile.orb.util`

.. automodule:: versile.orb.util
    :members:
    :show-inheritance:
