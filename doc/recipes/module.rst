.. _module_recipe:

Create a Custom Data Type
=========================
.. currentmodule:: versile.orb.module

Custom data types can be created by creating
:class:`versile.orb.entity.VEntity` classes which overload entity
serialization to a :term:`VER` format, providing a decoder for
instantiating the data type from serialized data, registering with a
:class:`VModule` and registering the module with a :term:`VOL` link.

Below is a definition of a class for handling a custom *Person* data
type which holds a first name and last name. The class overloads
``_v_encode`` in order to provide a :term:`VER` serialized
representation, and has a class method for reconstructing from a
tagged-value represented object::

    from versile.quick import VEntity

    class Person(VEntity):
        def __init__(self, firstname, lastname):
            super(Person, self).__init__()
            self._name = (firstname, lastname)

        @property
        def name(self):
            return self._name

        def _v_encode(self, context, explicit=True):
            tg = VModule.name_tags(name=(u'custom', u'person'), version=(1, 0))
            tag_obj = VTagged(self._name, *tg)
            return tag_obj._v_encode(context, explicit=explicit)

        @classmethod
        def _v_ver_decode(cls, value, *tags):
            if tags:
                raise VTaggedParseError('Illegal residual tags')
            def _assemble(args):
                args = VEntity._v_lazy_native(args)
                return cls(*args)
            return (_assemble, list(value))

Due to ``_v_encode`` overloading the type will always serialize with
the appropriate :term:`VER` representation, however in order for a
receiving link to recognize the type it needs to be somehow registered
with the link. :term:`VPy` uses :class:`VModule` objects for indexing
type decoding capabilities. Below is a module which can decode the
*Person* class::

    from versile.orb.module import VModuleResolver, VModule, VModuleDecoder

    class CustomModule(VModule):
        def __init__(self):
            super(CustomModule, self).__init__()
            _entry = VModuleDecoder(name=(u'custom', u'person'), ver=(1, 0),
                                    oid=None, decoder=Person._v_ver_decode)
            self.add_decoder(_entry)

Below we bring it all together in a complete code example, which
passes *Person* data over a link.

>>> from versile.quick import *
>>> from versile.orb.module import VModuleResolver, VModule, VModuleDecoder
>>>
>>> class Person(VEntity):
...     def __init__(self, firstname, lastname):
...         super(Person, self).__init__()
...         self._name = (firstname, lastname)
...     @property
...     def name(self):
...         return self._name
...     def _v_encode(self, context, explicit=True):
...         tg = VModule.name_tags(name=(u'custom', u'person'), version=(1, 0))
...         tag_obj = VTagged(self._name, *tg)
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
>>> class CustomModule(VModule):
...     def __init__(self):
...         super(CustomModule, self).__init__()
...         _entry = VModuleDecoder(name=(u'custom', u'person'), ver=(1, 0),
...                                 oid=None, decoder=Person._v_ver_decode)
...         self.add_decoder(_entry)
...
>>> # Register as a globally available module
... _module = CustomModule()
>>> VModuleResolver.add_import(_module)
>>>
>>> class Gateway(VExternal):
...     @publish(show=True)
...     def person(self, firstname, lastname):
...         return Person(firstname, lastname)
...
>>> client_link = link_pair(gw1=None, gw2=Gateway())[0]
>>> gw = client_link.peer_gw()
>>>
>>> obj = gw.person(u'John', u'Doe')
>>> type(obj)
<class 'Person'>
>>> obj.name
(u'John', u'Doe')
>>>
>>> client_link.shutdown()

Because we registered *CustomModule* as a globally available module
before the link is instantiated, each link adds the module to its set
of data types that are recognized and decoded. This is the default
behavior of an instantiated link, which can be overridden in link
configuration (e.g. provide a specific module resolver).

.. note::

    The *Person* object received when calling ``person()`` is not the
    same object as the one which was passed by the remote gateway - it
    has been serialized as a :term:`VER` data structure and
    reconstructed on the client side as a new object.

The :term:`VER` framework can also be used for other approaches to
encode and decode data types such as providing a type-cast framework
for remote objects. Also modules have additional features such as
registering native types for lazy-construction to an entity
representation. See :ref:`lib_modules` for more details
