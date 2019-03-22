# Copyright (C) 2011-2013 Versile AS
#
# This file is part of Versile Python.
#
# Versile Python is free software: you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public License
# as published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""Module framework for resolving :term:`VER` encoded entities."""
from __future__ import print_function, unicode_literals

from threading import Lock

from versile.internal import _vexport
from versile.common.iface import abstract
from versile.common.util import VObjectIdentifier
from versile.orb.entity import VEntity, VTagged, VObject, VProxy
from versile.orb.entity import VTaggedParser, VTaggedParseError
from versile.orb.entity import VTaggedParseUnknown

__all__ = ['VModule', 'VModuleConverter', 'VModuleDecoder', 'VModuleError',
           'VModuleResolver', 'VERBase']
__all__ = _vexport(__all__)


class VModuleError(Exception):
    """Module operation error."""


class VModuleResolver(VTaggedParser):
    """Parser for :term:`VER` encoded entities.

    Holds a set of :class:`VModule` objects and enables parsing
    :class:`versile.orb.entity.VTagged` objects which are encoded
    according to the :term:`VER` specifications registered with those
    modules. Objects are parsed by dispatching to the appropriate
    module.

    :param modules:    modules to register with the resolver
    :type  modules:    list, tuple
    :param add_import: if True include globally registered modules
    :type  add_import: bool

    If *add_import* is set then :meth:`imports` is called and the
    returned modules are added to the set of modules registered
    with the resolver.

    """

    _imported_modules_lock = Lock()
    _imported_modules = set()

    # VSEModuleCodes codes of globally imported VSE modules which
    # are imported via VSEResolver.add_imports() or loading the
    # various versile.vse.* modules ; dictionary VSEcode -> module
    _imported_vse_modules = dict()

    # Determines whether imported VSE modules are enabled globally
    # as modules, the default is True.
    _enable_vse_modules = True

    # Also defined in versile.vse.const
    VSE_OID_PREFIX = (1, 3, 6, 1, 4, 1, 38927, 1)
    """OID prefix for :term:`VSE` entities."""

    def __init__(self, modules=tuple(), add_imports=False):
        super(VModuleResolver, self).__init__()
        self.__lock = Lock()
        self.__modules = set()
        self.__proxy = VModule()

        for module in modules:
            self.add_module(module)
        if add_imports:
            imports = self.imports()
            for module in imports:
                if module not in modules:
                    self.add_module(module)

    def decoder(self, obj):
        self.__lock.acquire()
        try:
            if not isinstance(obj, VTagged):
                raise VTaggedParseError('Object must be VTagged')
            value, tags = obj.value, obj.tags
            if not tags:
                raise VTaggedParseUnknown('No tags set on object')
            encoding, etags = VEntity._v_lazy_native(tags[0]), tags[1:]
            if not isinstance(encoding, (int, long) or encoding < -1):
                raise VTaggedParseUnknown()
            if encoding == -1:
                if len(etags) < 2:
                    raise VTaggedParseError()
                name, version = VEntity._v_lazy_native(etags[:2])
                mod_tags = etags[2:]
                try:
                    entry = self.__proxy.decoder_from_name(name, version)
                except VModuleError:
                    raise VTaggedParseUnknown()
                try:
                    return entry.decoder(value, *mod_tags)
                except Exception as e:
                    raise VTaggedParseError(e.args)

            oid_enc_type, oid_enc_len = encoding%10, encoding//10
            if oid_enc_type in (0, 1):
                if len(etags) < oid_enc_len:
                    raise VTaggedParseError()
                oid_tags, mod_tags = etags[:oid_enc_len], etags[oid_enc_len:]
                oid_tags = VEntity._v_lazy_native(oid_tags)
                for t in oid_tags:
                    if not isinstance(t, (int, long)) or t < 0:
                        raise VTaggedParseError()
            else:
                return VTaggedParseUnknown()
            if oid_enc_type == 1:
                oid_tags = self.VSE_OID_PREFIX + oid_tags
            oid = VObjectIdentifier(oid_tags)
            try:
                entry = self.__proxy.decoder_from_oid(oid)
            except VModuleError:
                raise VTaggedParseUnknown()
            try:
                return entry.decoder(value, *mod_tags)
            except Exception as e:
                raise VTaggedParseError(e.args)
        finally:
            self.__lock.release()

    def converter(self, obj):
        self.__lock.acquire()
        try:
            entry = None
            if isinstance(obj, object) and hasattr(obj, '__class__'):
                c = obj.__class__
                try:
                    entry = self.__proxy.converter_from_class(c)
                except VModuleError:
                    pass
            if not entry:
                try:
                    entry = self.__proxy.converter_from_type(type(obj))
                except VModuleError:
                    pass
            if not entry:
                raise VTaggedParseError('Could not find a converter')
            try:
                return entry.converter(obj)
            except Exception as e:
                raise VTaggedParseError('Error creating converter')
        finally:
            self.__lock.release()

    def add_module(self, module):
        """Adds a module to the set of modules handled by the resolver.

        :param module: module to register with the resolver
        :type  module: :class:`VModule`

        Adding the module will import the module decoders set on the
        module at the time of the import. Module decoders should not be
        added or removed on the module as long as it is registered
        with a resolver.

        """
        self.__lock.acquire()
        try:
            self.__modules.add(module)
            for entry in module.decoders:
                self.__proxy.add_decoder(entry)
            for entry in module.converters:
                self.__proxy.add_converter(entry)
        finally:
            self.__lock.release()

    def remove_module(self, module):
        """Removes a module from the set of modules handled by the resolver.

        :param module: module to remove
        :type  module: :class:`VModule`

        Removing a module will remove the module decoders which are set
        on the module at the time this method is called. If the module
        has been updated after the module was imported, the module may
        not be cleanly removed.

        """
        self.__lock.acquire()
        try:
            self.__modules.discard(module)
            for entry in module.decoders:
                self.__proxy.remove_decoder(entry)
            for entry in module.converters:
                self.__proxy.remove_converter(entry)
        finally:
            self.__lock.release()

    @classmethod
    def add_import(cls, module):
        """Registers a module as a globally available module.

        :param module: module object to add
        :type  module: :class:`VModule`

        The method is primarily intended for use by python
        modules. Modules can instantiate :class:`VModule` objects for
        any modules they define, and then use this method to register
        the modules.

        VSE modules should not be directly loaded with this mechanism.

        """
        with cls._imported_modules_lock:
            cls._imported_modules.add(module)

    @classmethod
    def vse_enabled(cls):
        """Returns status whether globally added VSE modules are enabled.

        :returns: True if loaded VSE modules are enabled
        :rtype:   bool

        """
        with cls._imported_modules_lock:
            return VModuleResolver._enable_vse_modules

    @classmethod
    def enable_vse(cls, status=True):
        """Enables or disables globally added VSE modules.

        :param status: if True enable, otherwise disable
        :type  status: bool

        Enables or disables VSE modules which have been registered by
        calling :meth:`versile.vse.VSEResolver.add_imports` or by
        loading the various relevant VSE modules, as globally
        registered modules.

        The default behavior is that VSE modules are be enabled.

        """
        with cls._imported_modules_lock:
            if VModuleResolver._enable_vse_modules != status:
                for mod in cls._imported_vse_modules.values():
                    if status:
                        cls._imported_modules.add(mod)
                    else:
                        cls._imported_modules.discard(mod)
            VModuleResolver._enable_vse_modules = status

    @classmethod
    def _add_vse_import(cls, vse_code, module):
        """Registers a VSE module as a globally available module.

        :param vse_code: corresponding module code
        :type  vse_code: int
        :param module:   module object to add
        :type  module:   :class:`VModule`

        The method is primarily intended for internal use by the VSE
        framework.

        """
        with cls._imported_modules_lock:
            perform_import = vse_code not in cls._imported_vse_modules
            if perform_import:
                cls._imported_vse_modules[vse_code] = module
        if perform_import and VModuleResolver._enable_vse_modules:
            cls.add_import(module)

    @classmethod
    def imports(cls):
        """Returns the modules registered with :meth:`add_import`\ .

        :returns: module objects registered with :meth:`add_import`
        :rtype:   tuple

        """
        with cls._imported_modules_lock:
            return tuple(cls._imported_modules)


class VModule(object):
    """Parses :term:`VER` encoded :class:`versile.orb.entity.VTagged` objects.

    Parses :class:`versile.orb.entity.VTagged` objects with tags match
    the tag definition of a :class:`VModuleDecoder` which has been
    registered with the module.

    """

    def __init__(self):
        super(VModule, self).__init__()
        self.__lock = Lock()

        self.__names = dict()
        self.__oids = dict()
        self.__decoders = set()

        self.__types = dict()
        self.__classes = dict()
        self.__converters = set()

    def add_decoder(self, entry):
        """Adds a module decoder.

        :param entry: entry to add
        :type  entry: :class:`VModuleDecoder`
        :raises:      :exc:`VModuleError`

        """
        self.__lock.acquire()
        try:
            if entry.name:
                _key = entry.name + (entry.version,)
                if _key in self.__names:
                    raise VModuleError('Name/version already registered')
                else:
                    self.__names[_key] = entry
            if entry.oid:
                if entry.oid in self.__oids:
                    raise VModuleError('OID already registered')
                self.__oids[entry.oid] = entry
            self.__decoders.add(entry)
        finally:
            self.__lock.release()

    def add_converter(self, entry):
        """Adds a module converter.

        :param entry: entry to add
        :type  entry: :class:`VModuleConverter`
        :raises:      :exc:`VModuleError`

        """
        self.__lock.acquire()
        try:
            for t in entry.types:
                if t in self.__types:
                    raise VModuleError('Type already registered')
                self.__types[t] = entry
            for c in entry.classes:
                if c in self.__classes:
                    raise VModuleError('Class already registered')
                self.__classes[c] = entry
            self.__converters.add(entry)
        finally:
            self.__lock.release()

    def remove_decoder(self, entry):
        """Removes a module entry.

        :param entry: entry to add
        :type  entry: :class:`VModuleDecoder`
        :raises:      :exc:`VModuleError`

        """
        self.__lock.acquire()
        try:
            if entry.name:
                _key = entry.name + (entry.version,)
                self.__names.pop(_key, None)
            if entry.oid:
                self.__oids.pop(entry.oid, None)
            self.__decoders.discard(entry)
        finally:
            self.__lock.release()

    def remove_converter(self, entry):
        """Removes a module converter.

        :param entry: entry to add
        :type  entry: :class:`VModuleConverter`
        :raises:      :exc:`VModuleError`

        """
        self.__lock.acquire()
        try:
            for t in entry.types:
                self.__types.pop(t, None)
            for c in entry.classes:
                self.__classes.pop(c, None)
            self.__converters.discard(entry)
        finally:
            self.__lock.release()

    def decoder_from_name(self, name, ver):
        """Returns the registered entry for the given name and version.

        :param name: the name resolved by the decoder
        :type  name: (unicode,)
        :param ver:  the version resolved by the decoder
        :type  ver:  (int,)
        :returns:    registered entry
        :rtype:      :class:`VModuleDecoder`
        :raises:     :exc:`VModuleError`

        Raises an exception if decoder is not registered.

        """
        self.__lock.acquire()
        try:
            entry = self.__names.get(name + (ver,), None)
            if not entry:
                raise VModuleError('Decoder for oid not registered')
            return entry
        finally:
            self.__lock.release()

    def decoder_from_oid(self, oid):
        """Returns the registered decoder for the given object identifier.

        :param oid:  module entry identifier
        :type  oid:  :class:`versile.common.util.VObjectIdentifier`
        :returns:    registered entry
        :rtype:      :class:`VModuleDecoder`
        :raises:     :exc:`VModuleError`

        Raises an exception if decoder is not registered.

        """
        self.__lock.acquire()
        try:
            entry = self.__oids.get(oid, None)
            if not entry:
                raise VModuleError('Decoder for oid not registered')
            return entry
        finally:
            self.__lock.release()

    def converter_from_type(self, typ):
        """Returns the registered converter for the given type.

        :param typ:  a type
        :type  typ:  :class:`types.TypeType`
        :returns:    registered converter
        :rtype:      :class:`VModuleConverter`
        :raises:     :exc:`VModuleError`

        Raises an exception if converter is not registered.

        """
        self.__lock.acquire()
        try:
            entry = self.__types.get(typ, None)
            if not entry:
                raise VModuleError('Converter for type not registered')
            return entry
        finally:
            self.__lock.release()

    def converter_from_class(self, c):
        """Returns the registered converter for the given type.

        :param c:  a type
        :type  c:  :class:`types.ClassType`
        :returns:  registered converter
        :rtype:    :class:`VModuleConverter`
        :raises:   :exc:`VModuleError`

        Raises an exception if converter is not registered.

        """
        self.__lock.acquire()
        try:
            entry = self.__classes.get(c, None)
            if not entry:
                raise VModuleError('Converter for class not registered')
            return entry
        finally:
            self.__lock.release()

    @classmethod
    def as_object(cls, value):
        """Returns a value as a :class:`versile.orb.entity.VObject`\ .

        :param value: value to convert
        :raises:      :exc:`exceptions.TypeError`

        Convenience method for derived classes. If *value* is a
        :class:`versile.orb.entity.VObject` then it is returned as-is,
        or if it is a :class:`versile.orb.entity.VProxy` then its
        underlying object is returned. Otherwise, an exception is
        raised.

        """
        if isinstance(value, VObject):
            obj = value
        elif isinstance(value, VProxy):
            obj = value()
        else:
            raise TypeError('Cannot represent as VObject')
        return obj

    @classmethod
    def name_tags(cls, name, version):
        """Return :term:`VER` tags for given name and version.

        :param name:    :term:`VER` encoding name
        :type  name:    (unicode,)
        :param version: :term:`VER` encoding version
        :type  version: (int,)
        :returns:       encoding tags
        :rtype:         tuple

        Convenience method for generating the appropriate tags for the
        :term:`VER` encoding format.

        """
        return (-1, name, version)

    @classmethod
    def oid_tags(cls, oid):
        """Return :term:`VER` tags for a provided (complete) object identifier.

        :param oid: object identifier
        :type  oid: :class:`versile.common.util.VObjectIdentifier`
        :returns:   encoding tags
        :rtype:     tuple

        """
        elements = oid.oid
        prefix = 10*len(elements)
        return (prefix,) + elements

    @property
    def decoders(self):
        """The set of decoders set on the module."""
        return frozenset(self.__decoders)

    @property
    def converters(self):
        """The set of converters set on the module."""
        return frozenset(self.__converters)


class VModuleDecoder(object):
    """A decoder entry that can be registered with a :class:`VModule`\ .

    :param name:    entry name (or None)
    :type  name:    (unicode,)
    :param ver:     entry version (or None)
    :type  ver:     (int,)
    :param oid:     entry object ID (or None)
    :type  oid:     :class:`versile.common.util.VObjectIdentifier`
    :param decoder: decoder for associated :class:`versile.orb.entity.VTagged`
    :type  decoder: callable

    At least one of *name* and *oid* must be set. Both or none of
    *name* and *ver* must be set.

    *decoder* should accept calls as ``decoder(value, *tags)`` to
    decode a :class:`versile.orb.entity.VTagged` where *value* is the
    value set on the object and *\*tags* are any remaining tags after
    the :term:`VER` header tags have been stripped.

    *decoder* should return a tuple ``(func, args)`` where *func* is a
    function that can produce a decoded object, and *args* is a
    :class:`list` of unconverted inputs to *func*. In order to create
    a decoded object the platform (internally) creates a list
    *_conv_args* of decoded and possibly native-converted
    representations of each element in *args*, and calls
    ``func(*_conv_args)`` to generate the resulting object.

    If the *func* element of the *decoder* return value is None, then
    no further processing is required and *args* must be a
    :class:`list` which holds one single element, which is the decoded
    object.

    """

    def __init__(self, name, ver, oid, decoder):
        if (name is None) != (name is None):
            raise VModuleError('Must set both name and version, or none')
        if not (name or oid):
            raise VModuleError('Name or OID must be set')
        self._name = name
        self._ver = ver
        self._oid = oid
        self._decoder = decoder

    @property
    def name(self):
        """Module entry name ((unicode,))"""
        return self._name

    @property
    def version(self):
        """Module entry version ((int,))"""
        return self._ver

    @property
    def oid(self):
        """Entry\'s oid (\ :class:`versile.common.util.VObjectIdentifier`\ )"""
        return self._oid

    @property
    def decoder(self):
        """Module entry decoder (callable)"""
        return self._decoder


class VModuleConverter(object):
    """A converter entry that can be registered with a :class:`VModule`\ .

    :param converter: converter
    :type  converter: callable
    :param types:   types this converter should lazy-convert
    :type  types:   (:class:`types.TypeType`\ ,)
    :param classes: classes this converter should lazy-convert
    :type  classes: (:class:`types.ClassType`\ ,)

    The *converter* argument should be the same format as the
    functions returned by :meth:`VEntity._v_converter`\ .

    *types* and/or *classes* must be defined.

    """

    def __init__(self, converter, types=tuple(), classes=tuple()):
        if not (types or classes):
            raise VModuleError('Must set types and/or classes')
        self._types = tuple(types)
        self._classes = tuple(classes)
        self._converter = converter

    @property
    def types(self):
        """Converter accepted types ((type,))"""
        return self._types

    @property
    def classes(self):
        """Converter accepted classes ((classobj,))"""
        return self._classes

    @property
    def converter(self):
        """Module entry converter (callable)"""
        return self._converter


@abstract
class VERBase(object):
    """A base class for :term:`VER` objects.

    The class is intended to be used with multiple inheritance. It
    should come before any :class:`versile.orb.entity.VEntity` as it
    overloads :meth:`_v_encode`\ .

    It is not a requirement that

    .. automethod:: _v_as_tagged
    .. automethod:: _v_encode

    """

    def _v_as_tagged(self, context):
        """Returns a tagged-entity representation of this object.

        :param ctx:  context
        :type  ctx:  :class:`versile.orb.entity.VIOContext`
        :returns:    tagged-entity representation
        :rtype:      :class:`versile.orb.entity.VTagged`

        """
        raise NotImplementedError()

    def _v_encode(self, context, explicit=True):
        """See :meth:`versile.orb.entity.VEntity._v_encode`\ .

        Implements encoding by calling :meth:`_v_as_tagged` to create
        a :class:`versile.orb.entity.VTagged` representation and then
        requests an encoding from that object.

        """
        return self._v_as_tagged(context)._v_encode(context, explicit=explicit)
