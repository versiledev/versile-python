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

"""Module for :term:`VSE` native objects.

Importing registers :class:`VNativeModule` as a global module.

"""
from __future__ import print_function, unicode_literals

from threading import Lock

from versile.internal import _vexport, _v_silent

from versile.orb.entity import VEntity
from versile.orb.entity import VString, VTuple, VTaggedParseError
from versile.orb.module import VModuleResolver, VModule, VModuleError
from versile.vse.const import VSECodes, VSEModuleCodes
from versile.vse.native import VNative

__all__ = ['VNativeModule']
__all__ = _vexport(__all__)


class VNativeModule(VModule):
    """Module for :term:`VSE` native objects.

    :param activates: if True decoded objects are activated
    :type  activates: bool
    :param add_types: if True auto-register handlers for included native types
    :type  add_types: bool

    This module resolves: :class:`versile.vse.native.VNativeObject`\
    and :exc:`VNativeException`\ .

    Implementations of native types can be registered with
    :meth:`add_native_handler`\ , which causes the module to dispatch
    decoding of encoded native objects to handlers with a matching
    'native type' residual tag.

    If the module is created with *activates* set to True, then
    decoded :class:`versile.vse.native.VNative` and
    :exc:`versile.vse.native.VNativeException` objects are
    automatically activated.

    """
    def __init__(self, activates=False, add_types=True):
        super(VNativeModule, self).__init__()
        self.__lock = Lock()
        self.__activates = activates
        self.__handlers = dict() # native typ tag -> (obj_decoder, exc_decoder)

        # Add decoder for conversion from VNativeObject
        _decoder = self._vse_obj_decoder
        _entry = VSECodes.NATIVE_OBJECT.mod_decoder(_decoder)
        self.add_decoder(_entry)

        # Add decoder for conversion from VNativeException
        _decoder = self._vse_exc_decoder
        _entry = VSECodes.NATIVE_EXCEPTION.mod_decoder(_decoder)
        self.add_decoder(_entry)

        if add_types:
            # Register Python Native Type
            try:
                import versile.vse.native.python as py_native
            except Exception as e:
                _v_silent(e)
            else:
                # Register python 2.x objects
                tag = 'vse-python-2.x'
                obj_dec = py_native.VPython2._v_vse_obj_decoder
                obj_exc = py_native.VPython2Exception._v_vse_exc_decoder
                self.add_native_handler(tag, obj_dec, obj_exc)

                # Register python 3.x objects
                tag = 'vse-python-3.x'
                obj_dec = py_native.VPython3._v_vse_obj_decoder
                obj_exc = py_native.VPython3Exception._v_vse_exc_decoder
                self.add_native_handler(tag, obj_dec, obj_exc)

    def add_native_handler(self, tag, obj_decoder, exc_decoder):
        """Adds native code type handler for a specified native type tag.

        :param tag:         tag code for the native object type
        :type  tag:         unicode
        :param obj_decoder: decoder for :class:`versile.vse.native.VNative`
        :type  obj_decoder: callable
        :param exc_decoder: :exc:`versile.vse.native.VNativeException` decoder
        :type  exc_decoder: callable

        *obj_decoder* takes a single
        :class:`versile.orb.entity.VObject` as
        argument. *exc_decoder* takes a variable number of arguments
        which are the e.args values registered on the exception.

        """
        self.__lock.acquire()
        try:
            if tag in self.__handlers:
                raise VModuleError('Tag already registered')
            self.__handlers[tag] = (obj_decoder, exc_decoder)
        finally:
            self.__lock.release()

    def remove_native_handler(self, tag):
        """Removes the native code handler for specified code tag.

        :param tag:         tag code for the native object type
        :type  tag:         unicode

        """
        self.__lock.acquire()
        try:
            self.__handlers.pop(tag, None)
        finally:
            self.__lock.release()

    def _v_get_activates(self): return self.__activates
    def _v_set_activates(self, activates): self.__activates = activates
    _v_activates = property(_v_get_activates, _v_set_activates, None,
                            'True if module activates instantiated VNative.')

    def _vse_obj_decoder(self, value, *tags):
        if len(tags) != 1 or not isinstance(tags[0], VString):
            raise VTaggedParseError('Invalid residual tag format')
        residual_tag = VEntity._v_lazy_native(tags[0])

        self.__lock.acquire()
        try:
            decoders = self.__handlers.get(residual_tag, None)
        finally:
            self.__lock.release()

        if decoders:
            obj_decoder, exc_decoder = decoders
            decoded = obj_decoder(value)
        else:
            decoded = VNative(value, residual_tag)

        if self.__activates:
            decoded._v_activate()

        return (lambda args: decoded, [])

    def _vse_exc_decoder(self, value, *tags):
        if len(tags) != 1 or not isinstance(tags[0], VString):
            raise VTaggedParseError('Invalid residual tag format')
        residual_tag = VEntity._v_lazy_native(tags[0])
        if not isinstance(tags, (tuple, VTuple)):
            raise VTaggedParseError('Invalid value format')

        self.__lock.acquire()
        try:
            decoders = self.__handlers.get(residual_tag, None)
        finally:
            self.__lock.release()

        if decoders:
            obj_decoder, exc_decoder = decoders
            decoded = exc_decoder(*value)
        else:
            decoded = VNativeException(residual_tag, *value)

        if self.__activates:
            decoded._v_activate()

        return (lambda args: decoded, [])

_vmodule = VNativeModule()
VModuleResolver._add_vse_import(VSEModuleCodes.NATIVE, _vmodule)
