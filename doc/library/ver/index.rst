.. _lib_modules:

Entity Representation and Modules
=================================
.. currentmodule:: versile.orb.module

This is the API documentation for a module framework for :term:`VER`
encoded data structures. The :term:`VER` specifications defines
standards for representing ("encoding") higher level data types as a
:class:`versile.orb.entity.VTagged` structure. The module
:mod:`versile.orb.module` contains a framework for working with
modules that handle encoding/decoding for sets of :term:`VER` encoded
types.

Entity Representation
---------------------

:term:`VER` encoded types are identified by a "label" which is the
first *n* tags :class:`versile.orb.entity.VTagged`. The label defines
what kind of data is held/represented by the tag object, and it should
imply how tag object value and remaining tags are to be
interpreted. In order to properly parse tag object data a decoding
peer must recognize the identifier used.

The identifying "label" consists of a leading integer followed by
either (a) a label *name* and *version*, or (b) a sequence of integers
which refer to an :term:`Object Identifier` for the encoding. The
leading integer includes information about which type of label is used
and the number of label tags. See the :term:`VP` specification of
:term:`VER` for details regarding the encoded format.

:term:`VER` entities must inherit :class:`versile.orb.entity.VEntity`
(or a derived class) and must overload methods for serializing entity
data so it generates an appropriate :term:`VER` encoding. For 'dumb'
entities which do not derive from :class:`versile.orb.entity.VObject`
this typically means overloading
:meth:`versile.orb.entity.VEntity._v_encode`\ , as showed in the below
example.

>>> from versile.orb.entity import VEntity, VTagged, VIOContext
>>> from versile.orb.module import VModule
>>> class Triangle(VEntity):
...     """Triangle with integer dimensions."""
...     def __init__(self, a, b, c):
...         super(Triangle, self).__init__()
...         self._sides = (a, b, c)
...     def _v_encode(self, context, explicit=True):
...         tg = VModule.name_tags(name=(u'mypkg', u'triangle'), version=(1, 0))
...         tag_obj = VTagged(self._sides, *tg)
...         return tag_obj._v_encode(context, explicit=explicit)
...
>>> ctx = VIOContext()
>>> t = Triangle(3, 5, 9)
>>> data = t._v_write(ctx)
>>> data[:15]
'\xfe\x04\xf6\x03\x04\x06\n\x00\xf6\x02\xf5\x04\x05\xf5\x04'
>>> data[15:]
'\x08\xf6\x02\x02\x01triangleutf8mypkgutf8'

Encoding entities which derive from
:class:`versile.orb.entity.VObject` typically involves passing a
reference to the object as either the value of the encoded
:class:`versile.orb.entity.VTagged` or one of the tags. However, the
object cannot include itself as-is in the tag-structure as this would
cause infinite recursion for the tag object's encoder. Instead the
encoder should use the the output of
:meth:`versile.orb.entity.VObject._v_raw_encoder` as a reference to
the object embedded in the tag object representation.

>>> from versile.orb.entity import VTagged, VObjectIOContext
>>> from versile.orb.external import *
>>> from versile.orb.module import VModule
>>> class Square(VExternal):
...     """A square."""
...     def __init__(self, side_len):
...         super(Square, self).__init__()
...         self._side_len = side_len
...     @publish(show=True, doc=True)
...     def area(self):
...         """Returns the square's area."""
...         return self._side_len**2
...     def _v_encode(self, context, explicit=True):
...         ref = self._v_raw_encoder()
...         tg = VModule.name_tags(name=(u'mypkg', u'square'), version=(1, 0))
...         tag_obj = VTagged(ref, *tg)
...         return tag_obj._v_encode(context, explicit=explicit)
...
>>> ctx = VObjectIOContext()
>>> t = Square(4)
>>> data = t._v_write(ctx)
>>> data[:15]
'\xfe\x04\xfc\x02\x00\xf6\x02\xf5\x04\x05\xf5\x04\x06\xf6\x02'
>>> data[15:]
'\x02\x01squareutf8mypkgutf8'

Modules
-------

A :class:`VModule` is a container for a set of :term:`VER` definitions
and parsers. New modules can be created by sub-classing
:class:`VModule` and initializing module handlers in the constructor.

Modules can be registered with a :class:`versile.orb.link.VLink` so
received tag objects are matched with identifier "labels" recognized
by the module, and if the label is known then the module decodes the
:term:`VER` encoded format. When two communicating parties agree on a
set of :term:`VER` identifiers and encoded formats they can exchange
higher-level data types directly.

.. note::

   :term:`VP` defines a set :term:`VSE` of higher-level data types,
   see :ref:`lib_vse` for details.

Decoders
........

A :term:`VER` 'decoder function' is a callable which returns a data
structure that can be used to convert a
:class:`versile.orb.entity.VTagged` representation into a decoded
:class:`versile.orb.entity.VEntity`\ .

The decoder function takes the tag-encoding's *value* and *residual
tags* as arguments. The *residual tags* are the remaining tag object
tags after the leading :term:`VER` identifier/label tags have been
stripped away. The decoder must return a data structure which the
internal :term:`VPy` decoder algorithm can use to compose the decoded
object. See :class:`VModuleDecoder` constructor documentation for
details about decoder function arguments and return value.

A decoder function is held by a :class:`VModuleDecoder` objects which
can be registered with a module with :meth:`VModule.add_decoder`\
. Below is an example module which resolves a custom :term:`VER`
format.

>>> from versile.orb.entity import *
>>> from versile.orb.module import VModuleResolver, VModule, VModuleDecoder
>>> class Triangle(VEntity):
...     """Triangle with integer dimensions."""
...     def __init__(self, a, b, c):
...         super(Triangle, self).__init__()
...         self._sides = (a, b, c)
...     @property
...     def sides(self):
...         return self._sides
...     def _v_encode(self, context, explicit=True):
...         tg = VModule.name_tags(name=(u'mypkg', u'triangle'), version=(1, 0))
...         tag_obj = VTagged(self._sides, *tg)
...         return tag_obj._v_encode(context, explicit=explicit)
...     @classmethod
...     def _v_ver_decode(cls, value, *tags):
...         if tags:
...             raise VTaggedParseError('Illegal residual tags')
...         def _assemble(args):
...             args = VEntity._v_lazy_native(args)
...             return cls(*args)
...         return (_assemble, list(value))
...
>>> ctx = VIOContext()
>>> data = Triangle(3, 5, 9)._v_write(ctx)
>>>
>>> class MathModule(VModule):
...     def __init__(self):
...         super(MathModule, self).__init__()
...         _entry = VModuleDecoder(name=(u'mypkg', u'triangle'), ver=(1, 0),
...                                 oid=None, decoder=Triangle._v_ver_decode)
...         self.add_decoder(_entry)
...
>>> _module = MathModule()
>>> # This would register the module centrally ...
... VModuleResolver.add_import(_module)
>>> # ... however in this example we set up a resolver explicitly
... resolver = VModuleResolver(modules=(_module,))
>>>
>>> reader = VEntity._v_reader(ctx)
>>> reader.read(data)
41
>>> tagged = reader.result()
>>> type(tagged)
<class 'versile.orb.entity.VTagged'>
>>> decoder = resolver.decoder(tagged)
>>> f, args = decoder
>>> rec = f(args)
>>> type(rec)
<class 'Triangle'>
>>> rec.sides
(3, 5, 9)

The above example resolves a :term:`VER` encoding as a custom type
derived from :class:`versile.orb.entity.VEntity`\ . Another type of
:term:`VER` representation can be to type-cast a
:class:`versile.orb.entity.VObject` reference.

A "type-cast" tag object should be decoded as a sub-class of
:class:`versile.orb.entity.VProxy`\ . When this class is constructed
then the proxy class must be registered with the held (proxied) object
by calling :class:`versile.orb.entity.VObject._v_set_proxy_factory`\
. Below is an example of such a proxy class.

>>> from versile.orb.entity import *
>>> from versile.orb.module import VModuleResolver, VModule, VModuleDecoder
>>> from versile.orb.external import *
>>>
>>> class SquareProxy(VProxy):
...     def __init__(self, obj):
...         if isinstance(obj, VProxy):
...             obj = obj()
...         super(SquareProxy, self).__init__(obj)
...         if isinstance(obj, VReference):
...             obj._v_set_proxy_factory(self.__class__)
...     @classmethod
...     def _v_ver_decoder(cls, value, *tags):
...         if tags:
...             raise VTaggedParseError('Illegal extra tags for this encoding')
...         def _assemble(args):
...             value = args[0]
...             value = VEntity._v_lazy_native(value)
...             return cls(value)
...         return (_assemble, [value])
...
>>> class Square(VExternal):
...     """A square."""
...     def __init__(self, side_len):
...         super(Square, self).__init__()
...         self._v_set_proxy_factory(SquareProxy)
...         self._side_len = side_len
...     @publish(show=True, doc=True)
...     def area(self):
...         """Returns the square's area."""
...         return self._side_len**2
...     def _v_encode(self, context, explicit=True):
...         ref = self._v_raw_encoder()
...         tg = VModule.name_tags(name=(u'math', u'square'), version=(1, 0))
...         tag_obj = VTagged(ref, *tg)
...         return tag_obj._v_encode(context, explicit=explicit)
...
>>> ctx = VObjectIOContext()
>>> t = Square(4)
>>> data = t._v_write(ctx)
>>>
>>> class MathModule(VModule):
...     def __init__(self):
...         super(MathModule, self).__init__()
...         _entry = VModuleDecoder(name=(u'math', u'square'), ver=(1, 0),
...                                 oid=None, decoder=SquareProxy._v_ver_decoder)
...         self.add_decoder(_entry)
...
>>> _module = MathModule()
>>>
>>> # This would register the module centrally ...
... VModuleResolver.add_import(_module)
>>> # However in this example we set up a resolver explicitly
... resolver = VModuleResolver(modules=(_module,))
>>>
>>> reader = VEntity._v_reader(ctx)
>>> reader.read(data)
35
>>> tagged = reader.result()
>>> type(tagged)
<class 'versile.orb.entity.VTagged'>
>>> decoder = resolver.decoder(tagged)
>>> f, args = decoder
>>> rec = f(args)
>>> type(rec)
<class 'SquareProxy'>

Converters
..........

A 'converter' is a callable which returns a data structure which can
be used for converting a native data structure to a
:class:`versile.orb.entity.VEntity` representation. Converter
arguments and return value are similar to a decoder function.

By registering a converter function with a module using
:meth:`VModule.add_converter` the module can recognize registered
native types and use the provided converter function to create an
entity which represents the data. An example how this can be used is
:class:`versile.vse.container.VContainerModule` which can recognize
native :class:`frozenset` data structures and perform conversion to
:class:`versile.vse.container.VFrozenSet`\ .

Below is a (partial) example which implements lazy-conversion. Note
that this is an incomplete example, as it does not implement
:term:`VER` encoding or decoding showed in earlier examples.

>>> from versile.orb.entity import *
>>> from versile.orb.module import VModuleResolver, VModule, VModuleConverter
>>> class MyTriangle(object):
...     def __init__(self, a, b, c):
...         self._sides = (a, b, c)
...     @property
...     def sides(self):
...         return self._sides
...
>>> class Triangle(VEntity):
...     """Triangle with integer dimensions."""
...     def __init__(self, a, b, c):
...         super(Triangle, self).__init__()
...         self._sides = (a, b, c)
...     @property
...     def sides(self):
...         return self._sides
...     @classmethod
...     def _v_converter(cls, obj):
...         if not isinstance(obj, MyTriangle):
...             raise TypeError('Invalid native type')
...         a, b, c = obj.sides
...         def _assemble(args):
...             return cls(a, b, c)
...         return (_assemble, [])
...
>>> class MathModule(VModule):
...     def __init__(self):
...         super(MathModule, self).__init__()
...         _entry = VModuleConverter(Triangle._v_converter,
...                                   classes=(MyTriangle,))
...         self.add_converter(_entry)
...
>>> _module = MathModule()
>>> VModuleResolver.add_import(_module)
>>>
>>> resolver = VModuleResolver(modules=(_module,))
>>>
>>> some_triangle = MyTriangle(2, 5, 9)
>>> converter = resolver.converter(some_triangle)
>>> f, args = converter
>>> conv = f(args)
>>> type(conv)
<class 'Triangle'>
>>> conv.sides
(2, 5, 9)


Module Resolvers
----------------

A :class:`VModuleResolver` is a
:class:`versile.orb.entity.VTaggedParser` which holds a set of
:class:`VModule` modules registered with
:meth:`VModuleResolver.add_module`. A resolver can provide tag object
decoders for all :term:`VER` labels recognized by its registered
modules. A decoder can be retreived with
:meth:`versile.orb.entity.VTaggedParser.decoder`\ . The resolver
locates a decoder by inspecting tag object tags and dispatching to the
appropriate registered :class:`VModule`\ .

:term:`VPy` implements a convenient mechanism for lazy-registering
modules to a central register, allowing module resolvers to be
dynamically registered when associated python modules are
loaded. Modules can register themselves a globally available module
via the :meth:`VModuleResolver.add_import` class method. A list of all
modules registered via this mechanism can be retreived with the class
method :meth:`VModuleResolver.imports`\ . Below is an example of
setting up a module resolver which resolves such added 'imports'.

>>> from versile.orb.entity import VIOContext, VEntity
>>> from versile.orb.module import VModuleResolver
>>> from versile.vse.container import *
>>> array = VMultiArray((3, 4, 2))
>>> array = array.frozen()
>>> ctx = VIOContext()
>>> data = array._v_write(ctx)
>>>
>>> reader = VEntity._v_reader(ctx)
>>> reader.read(data)
34
>>> tagged = reader.result()
>>>
>>> # We can create a resolver this way because the versile.vse.container
... # module registers itself as an available 'import' when it is imported
... resolver = VModuleResolver(add_imports=True)
>>>
>>> decoder = resolver.decoder(tagged)
>>> f, args = decoder
>>> rec = f(args)
>>> type(rec)
<class 'versile.vse.container.VFrozenMultiArray'>

A module resolver can be registered with a
:class:`versile.orb.link.VLink` as a parser for
:class:`versile.orb.entity.VTagged` objects, by registering with the
associated :class:`versile.orb.link.VLinkConfig`\ . The link node will
then use that resolver to parse and resolve
:class:`versile.orb.entity.VTagged` objects received from the peer.

Module APIs
-----------

Module API for :mod:`versile.orb.module`

.. automodule:: versile.orb.module
    :members:
    :show-inheritance:
