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

"""Implements :term:`VSE` semantic types.

Importing registers :class:`VSemanticModule` as a global module.

"""
from __future__ import print_function, unicode_literals

import threading

from versile.internal import _vexport, _pyver
from versile.common.iface import abstract
from versile.orb.entity import VEntity, VTagged, VInteger, VTaggedParseError
from versile.orb.module import VModuleResolver, VModule
from versile.orb.module import VERBase
from versile.vse.const import VSECodes, VSEModuleCodes

__all__ = ['VConcept', 'VPlatformConcept', 'VEnWikipediaConcept',
           'VUrlConcept', 'VSemanticsModule']
__all__ = _vexport(__all__)


@abstract
class VConcept(VERBase, VEntity):
    """Reference to a physical or abstract concept.

    :param c_type: :term:`VSE` type code for :class:`VConcept`
    :type  c_type: int
    :param value:  internal representation for given type

    Abstract class, should not be directly instantiated.

    """

    """Type code for Versile Platform defined concept."""
    TYPE_VP_DEFINED = 1

    """Type code for English wikipedia."""
    TYPE_EN_WIKIPEDIA = 2

    """Type code for URL based concept."""
    TYPE_URL = 3


    def __init__(self, c_type, value):
        self._type = c_type
        self._value = value


    def get_equivalent(self, c_type):
        """VP equivalent representation(s) for another concept type.

        :param c_type: VP concept type, e.g. VConcept.TYPE_EN_WIKIPEDIA
        :type  c_type: int
        :returns:      equivalent representation(s) of that type
        :rtype:        (:class:`VConcept`\ , ...)

        Derived VP defined classes should override to add equivalency
        representations for other types than VConcept.TYPE_VP_DEFINED.

        """
        if c_type == self.TYPE_VP_DEFINED:
            return self.vp_defined_code
        return tuple()


    @property
    def equivalents(self):
        """A tuple of type codes for equivalency representations.

        :returns: tuple of type codes for available representations
        :rtype:   (int, int, ...)

        Default holds only the type set on the object itself. Derived
        classes can override.

        """
        return (self._type, )


    @property
    def vp_code(self):
        """If concept is defined by Versile Platform, has associated code.

        Default is None, derived classes may override. The main
        implication of a VP defined concept is it may be encoded
        more efficiently as a serialized representation.

        """
        return None


    def _v_as_tagged(self, context):
        tags = VSECodes.CONCEPT.tags(context) + (self._type,)
        value = self._value
        return VTagged(value, *tags)


    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if len(tags) != 1:
            raise VTaggedParseError('Encoding requires a single residual tag')
        tag = tags[0]
        if _pyver == 2:
            _itypes = (int, long, VInteger)
        else:
            _itypes = (int, VInteger)
        if not isinstance(tag, _itypes):
            raise VTaggedParseError('Residual tag must be an integer')

        _val = VEntity._v_lazy_native(value)

        if tag == VConcept.TYPE_URL:
            if not isinstance(_val, tuple) or len(_val) != 2:
                raise VTaggedParseError('Value must be an 2-tuple')
            for _tmp in _val:
                if _pyver == 2:
                    if not isinstance(_tmp, unicode):
                        raise VTaggedParseError('Value element must be string')
                else:
                    if not isinstance(_tmp, str):
                        raise VTaggedParseError('Value element must be string')
            _prefix, _postfix = _val

            try:
                _result = VUrlConcept.create(_prefix, _postfix)
            except Exception as e:
                raise VTaggedParseError(e)
            else:
                return (lambda x: _result, [])

        if tag == VConcept.TYPE_EN_WIKIPEDIA:
            if _pyver == 2:
                if not isinstance(_val, unicode):
                    raise VTaggedParseError('Value must be string')
            else:
                if not isinstance(_val, str):
                    raise VTaggedParseError('Value must be string')

            try:
                _result = VEnWikipediaConcept.create(_val)
            except Exception as e:
                raise VTaggedParseError(e)
            else:
                return (lambda x: _result, [])

        if tag == VConcept.TYPE_VP_DEFINED:
            if not isinstance(value, _itypes):
                raise VTaggedParseError('Value must be an integer')
            _val = VEntity._v_lazy_native(value)

            try:
                _result = VPlatformConcept.create(_val)
            except Exception as e:
                raise VTaggedParseError(e)
            else:
                return (lambda x: _result, [])


        raise VTaggedParseError('Invalid residual tag value')


    @classmethod
    def _v_converter(cls, obj):
        return (lambda x: obj, [])


    def _v_native_converter(self):
        return (lambda x: self, [])


    def __str__(self):
        if _pyver == 2:
            _fmt = b'VConcept[%s:%s]'
        else:
            _fmt = 'VConcept[%s:%s]'
        return _fmt % (str(self._type), str(self._value))


    def __repr__(self):
        return self.__str__()


@abstract
class VPlatformConcept(VConcept):
    """Reference to a :term:`VP` defined concept.

    :param concept_id: ID number of concept as defined by platform
    :type  concept_id: int
    :raises:           :exc:`exceptions.ValueError`

    Abstract class, should not be directly instantiated (but rather be
    instantiated by a derived class defined by the platform
    implementation). Raises an exception if the ID number is outside the
    range allowed by the platform specification.

    """

    # Maximum and minimum ID number values allowed by the standard
    _MIN_ID_VAL = 1
    _MAX_ID_VAL = 243

    # Lock on class properties
    _cls_lock = threading.RLock()
    #
    # Locked class properties:
    # Known concepts {concept_type_number->factory_method}
    _concepts = dict()
    # Wikipedia translations {identity->concept_type_number}
    _translations = dict()

    def __init__(self, concept_id):
        super(VPlatformConcept, self).__init__(c_type=VConcept.TYPE_VP_DEFINED,
                                               value=concept_id)
        if (concept_id < VPlatformConcept._MIN_ID_VAL
            or concept_id > VPlatformConcept._MAX_ID_VAL):
            raise ValueError('Illegal platform concept ID')


    @classmethod
    def create(self, concept_id):
        """Create concept object associated with identifier.

        :param concept_id: ID number of concept as defined by platform
        :type  concept_id: int
        :raises:           :exc:`exceptions:ValueError`

        Raises an exception is concept ID is not valid for the platform.

        """
        with VPlatformConcept._cls_lock:
            if not VPlatformConcept._concepts:
                # This will initialize concepts and translations
                VPlatformConcept._translate('')
            _fun = VPlatformConcept._concepts.get(concept_id, None)
            if _fun:
                return _fun()
            else:
                return VPlatformConcept(concept_id)


    @classmethod
    def codes(cls):
        """Returns an iterator over IDs of all platform concept types.

        :returns: iterator over all IDs
        :rtype:   iter(int)

        """
        with VPlatformConcept._cls_lock:
            if not VPlatformConcept._concepts:
                # This will initialize concepts and translations
                VPlatformConcept._translate('')
            return (key for key in VPlatformConcept._concepts.keys())


    def get_equivalent(self, c_type):
        """VP equivalent representation(s) for another concept type.

        See :meth:`VConcept.get_equivalent`\ .

        """
        if c_type == self.TYPE_VP_DEFINED:
            return (self, )
        else:
            return tuple()


    @property
    def equivalents(self):
        """A tuple of type codes for equivalency representations.

        See :attr:`VConcept.equivalents`\ .

        """
        return (self.TYPE_VP_DEFINED, self.TYPE_EN_WIKIPEDIA,
                self.TYPE_URL)


    @property
    def vp_code(self):
        """If concept is defined by Versile Platform, has associated code.

        See :attr:`VConcept.vp_code`\ .

        """
        return self._value


    @classmethod
    def _translate(cls, identifier):
        """Translates a Wikipedia identifier to a VP concept factory method.

        :returns: factory method (or None)
        :rtype:   callable

        If Wikipedia identifier is not recognized, returns None.

        """
        with VPlatformConcept._cls_lock:
            if not VPlatformConcept._concepts:
                # Initialize translations concepts and translations
                _units = []

                # Versile Semantics extension may not be available. If
                # it fails to load, generic 'platform concept' objects
                # will be instantiated.
                try:
                    import versile.ext.semantics.concept.internal as _mod
                except ImportError:
                    pass
                else:
                    _units.extend(_mod.load_concepts())

                def _f_gen(unit):
                    return lambda : unit()
                for _unit in _units:
                    _obj = _unit()
                    _fun = _f_gen(_unit)
                    if _obj.vp_code in VPlatformConcept._concepts:
                        raise RuntimeError('Duplicate platform concept ID')
                    VPlatformConcept._concepts[_obj.vp_code] = _fun
                    _typ = VPlatformConcept.TYPE_EN_WIKIPEDIA
                    for _id in _obj.get_equivalent(_typ):
                        VPlatformConcept._translations[_id] = _obj.vp_code
                    del(_fun)

            _c_id = VPlatformConcept._translations.get(identifier, None)
            if _c_id is not None:
                return VPlatformConcept._concepts[_c_id]
            else:
                return None


class VEnWikipediaConcept(VConcept):
    """Reference to a English Wikipedia referenced concept.

    Should not be directly instantiated, but instead be instatiated
    via the :meth:`create` factory method (which may instantiate
    another class).  See that method for description of parameters.

    """

    def __init__(self, identifier):

        # Validate appropriate type
        if _pyver == 2:
            _ftyp, _ttyp = str, unicode
        else:
            _ftyp, _ttyp = bytes, str
        if isinstance(identifier, _ftyp):
            try:
                identifier = _ttyp(identifier)
            except Exception as e:
                raise TypeError('Identifier must be (unicode) strings.')
        if not isinstance(identifier, _ttyp):
            raise TypeError('Identifier must be (unicode) strings.')

        _typ = VConcept.TYPE_EN_WIKIPEDIA
        super(VEnWikipediaConcept, self).__init__(c_type=_typ,
                                                  value=identifier)


    @classmethod
    def create(self, identifier):
        """Create concept object associated with identifier.

        :param identifier: identifier as a postfix to wikipedia top URL
        :type  identifier: unicode
        :raises:           :exc:`exceptions.TypeError`

        *identifier* should be a postfix to the URL
        'http://en.wikipedia.org/wiki/' or
        'https://en.wikipedia.org/wiki/' as the prefix for the
        associated URL based representation.

        Raises an exception if identifier is not of appropriate type.

        """
        # Check for up-conversion to VP defined type
        _fun = VPlatformConcept._translate(identifier)
        if _fun:
            return _fun()

        return VEnWikipediaConcept(identifier)


    def get_equivalent(self, c_type):
        """VP equivalent representation(s) for another concept type.

        See :meth:`VConcept.get_equivalent`\ .

        """
        if c_type == self.TYPE_EN_WIKIPEDIA:
            return (self, )
        elif c_type == self.TYPE_URL:
            return (VUrlConcept('http://en.wikipedia.org/wiki/', self._value),
                    VUrlConcept('https://en.wikipedia.org/wiki/', self._value))


    @property
    def equivalents(self):
        """A tuple of type codes for equivalency representations.

        See :attr:`VConcept.equivalents`\ .

        """
        return (self.TYPE_EN_WIKIPEDIA, self.TYPE_URL)


    def __str__(self):
        if _pyver == 2:
            _fmt = b'VEnWikipediaConcept[%s]'
        else:
            _fmt = 'VEnWikipediaConcept[%s]'
        return _fmt % str(self._value)


class VUrlConcept(VConcept):
    """Reference to a URL referenced concept.

    Should not be directly instantiated, but instead be instatiated
    via the :meth:`create` factory method (which may instantiate
    another class). See that method for description of parameters.

    """

    def __init__(self, prefix, postfix):

        # Validate appropriate type
        _tmp = []
        if _pyver == 2:
            _ftyp, _ttyp = str, unicode
        else:
            _ftyp, _ttyp = bytes, str
        for _val in prefix, postfix:
            if isinstance(_val, _ftyp):
                try:
                    _val = _ttyp(_val)
                except Exception as e:
                    raise TypeError('Pre/postfix must be (unicode) strings.')
            if isinstance(_val, _ttyp):
                _tmp.append(_val)
            else:
                raise TypeError('Pre/postfix must be (unicode) strings.')
        prefix, postfix = _tmp

        # Check valid prefix
        if '://' not in prefix:
            raise ValueError('Invalid prefix, must contain *://*/*')
        _tmp = prefix.split('://')
        _method, _residual = _tmp[0], '://'.join(_tmp[1:])
        if not _residual or not _residual.endswith('/'):
            raise VTaggedParseError('Invalid prefix, must contain *://*/')
        if not _method == _method.lower():
            raise VTaggedParseError('Invalid prefix, *:// must be lower case')

        super(VUrlConcept, self).__init__(VConcept.TYPE_URL, (prefix, postfix))


    @classmethod
    def create(self, prefix, postfix):
        """Create concept object associated with identifier.

        :param prefix:  URL prefix
        :type  prefix:  unicode
        :param postfix: URL postfix
        :type  postfix: unicode
        :raises:        :exc:`exceptions.ValueError`\ ,
                        :exc:`exceptions.TypeError`

        Associated URL is the concatenation of prefix and postfix. Prefix
        must be on the form *://*/ with a lower-case initial method name
        and ending with a slash. An exception is raised if an invalid
        format is detected.

        Prefix is a domain under which the concept is a unique
        reference to that concept (assuming the reference is a
        'primary' reference for a concept within the domain).

        Should not be directly instantiated, but instead be instatiated
        via the :meth:`create` factory method (which may instantiate
        another class).

        """
        # If possible, up-convert to Wikipedia type
        if (prefix in ('http://en.wikipedia.org/wiki/',
                       'https://en.wikipedia.org/wiki/')):
            return VEnWikipediaConcept.create(postfix)

        return VUrlConcept(prefix, postfix)


    def get_equivalent(self, c_type):
        """VP equivalent representation(s) for another concept type.

        See :meth:`VConcept.get_equivalent`\ .

        """
        if c_type == self.TYPE_EN_WIKIPEDIA:
            return (self, )
        elif c_type == self.TYPE_URL:
            return (VUrlConcept('http://en.wikipedia.org/wiki/', self._value),
                    VUrlConcept('https://en.wikipedia.org/wiki/', self._value))


    @property
    def equivalents(self):
        """A tuple of type codes for equivalency representations.

        See :attr:`VConcept.equivalents`\ .

        """
        return (self.TYPE_EN_WIKIPEDIA, self.TYPE_URL)


    def __str__(self):
        if _pyver == 2:
            _fmt = b'VUrlConcept[%s][%s]'
        else:
            _fmt = 'VUrlConcept[%s][%s]'
        return _fmt % (str(self._value[0]), str(self._value[1]))


class VSemanticsModule(VModule):
    """Module for :term:`VSE` semantics types.

    This module resolves the following classes:

    * :class:`VConcept`

    """
    def __init__(self):
        super(VSemanticsModule, self).__init__()

        # Add decoders for conversion from VTagged
        _decoder = VConcept._v_vse_decoder
        _entry = VSECodes.CONCEPT.mod_decoder(_decoder)
        self.add_decoder(_entry)


_vmodule = VSemanticsModule()
VModuleResolver._add_vse_import(VSEModuleCodes.SEMANTICS, _vmodule)
