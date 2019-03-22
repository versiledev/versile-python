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

"""Implements :term:`VSE` math related types.

Importing registers :class:`VMathModule` as a global module.

"""
from __future__ import print_function, unicode_literals

import threading

from versile.internal import _vexport, _pyver
from versile.common.iface import abstract
from versile.orb.entity import VEntity, VTuple, VTagged, VTaggedParseError
from versile.orb.module import VModuleResolver, VModule
from versile.orb.module import VERBase
from versile.vse.const import VSECodes, VSEModuleCodes

__all__ = ['VPrefixedUnit', 'VDimensionalQuantity', 'VMathModule']
__all__ = _vexport(__all__)


class VPrefixedUnit(VERBase, VEntity):
    """Reference to a unit with a prefix.

    :param prefix: entity which can resolve as a prefix
    :param unit:   entity which can resolve as a unit

    """

    def __init__(self, prefix, unit):
        self._prefix = prefix
        self._unit = unit


    @property
    def prefix(self):
        """Associated prefix."""
        return self._prefix


    @property
    def unit(self):
        """Associated unit."""
        return self._unit


    @property
    def symbol(self):
        """Associated combined symbol.

        If a combined symbol cannot be generated, an alternative string
        is generated which uses the str() representation of the
        associated object instead.

        """
        s = ''
        try:
            s += self._prefix.symbol
        except:
            s += str(self._prefix)
        try:
            s += self._unit.symbol
        except:
            s += str(self._unit)
        return s


    def _v_as_tagged(self, context):
        tags = VSECodes.PREFIXED_UNIT.tags(context)
        value = (self._prefix, self._unit)
        return VTagged(value, *tags)


    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding takes no residual tags')
        if not isinstance(value, (tuple, VTuple)) or len(value) != 2:
            raise VTaggedParseError('Value must be a 2-tuple')
        _prefix, _unit = value
        return (lambda args: VPrefixedUnit(*args), [_prefix, _unit])


    @classmethod
    def _v_converter(cls, obj):
        return (lambda x: obj, [])


    def _v_native_converter(self):
        return (lambda x: self, [])


    def __str__(self):
        s = self.__unicode__()
        if _pyver == 2:
            s = s.encode('utf-8')
        return s


    def __unicode__(self):
        _fmt = 'VPrefixedUnit[%s:%s]'
        return _fmt % (unicode(self._prefix), unicode(self._unit))


    def __repr__(self):
        return self.__str__()


class VDimensionalQuantity(VERBase, VEntity):
    """Reference to a quantity with an associated dimension.

    :param quantity: entity which resolves as a dimensionless quantity
    :param unit:     entity which can resolve as a (possibly prefixed) unit

    """

    def __init__(self, quantity, unit):
        self._quantity = quantity
        self._unit = unit


    @property
    def quantity(self):
        """Associated quantity."""
        return self._quantity


    @property
    def unit(self):
        """Associated unit."""
        return self._unit


    def _v_as_tagged(self, context):
        tags = VSECodes.DIMENSIONAL_QUANTITY.tags(context)
        value = (self._quantity, self._unit)
        return VTagged(value, *tags)


    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding takes no residual tags')
        if not isinstance(value, (VTuple, tuple)) or len(value) != 2:
            raise VTaggedParseError('Value must be a 2-tuple')
        _quantity, _unit = value
        return (lambda args: VDimensionalQuantity(*args), [_quantity, _unit])


    @classmethod
    def _v_converter(cls, obj):
        return (lambda x: obj, [])


    def _v_native_converter(self):
        return (lambda x: self, [])


    def __str__(self):
        s = self.__unicode__()
        if _pyver == 2:
            s = s.encode('utf-8')
        return s


    def __unicode__(self):
        s = ''
        s += unicode(self._quantity)
        s += ' '
        try:
            s += self._unit.symbol
        except:
            s += unicode(self._unit)
        return s

    def __repr__(self):
        return self.__str__()


class VMathModule(VModule):
    """Module for :term:`VSE` math types.

    This module resolves the following classes:

    * :class:`VPrefixedUnit`
    * :class:`VDimensionalQuantity`

    """
    def __init__(self):
        super(VMathModule, self).__init__()

        # Add decoders for conversion from VTagged
        _decoder = VPrefixedUnit._v_vse_decoder
        _entry = VSECodes.PREFIXED_UNIT.mod_decoder(_decoder)
        self.add_decoder(_entry)

        _decoder = VDimensionalQuantity._v_vse_decoder
        _entry = VSECodes.DIMENSIONAL_QUANTITY.mod_decoder(_decoder)
        self.add_decoder(_entry)


_vmodule = VMathModule()
VModuleResolver._add_vse_import(VSEModuleCodes.MATH, _vmodule)
