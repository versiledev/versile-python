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

""":term:`VSE` tag code constants."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport
from versile.common.util import VObjectIdentifier

__all__ = ['VSECodes', 'VSECode']
__all__ = _vexport(__all__)


class VSECode(object):
    """Tag code used in VSE encoding.

    Attributes set on the class hold a short-form of tag data. Use
    :meth:`tag_data` to create the expanded form.

    """

    # Also defined in versile.orb.module
    OID_PREFIX = (1, 3, 6, 1, 4, 1, 38927, 1)
    """OID prefix for Versile defined module standard entities."""

    def __init__(self, name, version, oid):
        self._name = name
        self._version = version
        self._oid = oid

    @property
    def oid_code(self):
        """Tag codes associated with OID (tuple), or None if no OID"""
        if self._oid:
            return (10*len(self._oid) + 1,) + self._oid
        else:
            return None

    @property
    def name_code(self):
        """Tag codes associated with name (tuple), or None if no name"""
        if self.__name:
            return -1, ('versile',) + self._name, self._version
        else:
            return None

    def tags(self, ctx):
        """Return tag codes for the given context.

        :param ctx:    context
        :type  ctx:    :class:`versile.orb.entity.VIOContext`
        :returns:      tag codes
        :rtype:        tuple

        """
        if ctx.mod_use_oid:
            if self._oid:
                return self.oid_code
            elif self._name:
                return self.name_code
        elif self._name:
            return self.name_code
        elif _oid:
            return self.oid_code
        raise RuntimeError('No oid or name defined')

    def mod_decoder(self, handler):
        """Generates a :class:`versile.orb.module.VModuleDecoder`\ .

        :param handler:  tag data parser
        :type  handler:  callable
        :returns:        module entry for provided data
        :rtype:          :class:`versile.orb.module.VModuleDecoder`

        """
        from versile.orb.module import VModuleDecoder
        _name, _oid = self._name, self._oid
        if _name:
            _name = ('versile',) + self._name
        if _oid:
            _oid = VObjectIdentifier(self.OID_PREFIX + self._oid)
        return VModuleDecoder(_name, self._version, _oid, handler)


class VSECodes(object):
    """Tag codes used in VSE encoding.

    Tag codes are defined as class attributes. Their type is
    :class:`VSECode`\ .

    """

    MULTI_ARRAY = VSECode(('container', 'frozenmultiarray'), (0, 8), (1, 1))
    """Tag code for :class:`versile.vse.container.VFrozenMultiArray`\ ."""

    DICTIONARY = VSECode(('container', 'frozendict'), (0, 8), (1, 2))
    """Tag code for :class:`versile.vse.container.VFrozenDict`\ ."""

    SET = VSECode(('container', 'frozenset'), (0, 8), (1, 3))
    """Tag code for :class:`versile.vse.container.VFrozenSet`\ ."""

    ARRAY_OF_INT = VSECode(('container', 'arrayofint'), (0, 8), (1, 4))
    """Tag code for :class:`versile.vse.container.VArrayOfInt`\ ."""

    ARRAY_OF_LONG = VSECode(('container', 'arrayoflong'), (0, 8), (1, 5))
    """Tag code for :class:`versile.vse.container.VArrayOfLong`\ ."""

    ARRAY_OF_VINTEGER = VSECode(('container', 'arrayofvinteger'), (0, 8),
                                (1, 6))
    """Tag code for :class:`versile.vse.container.VArrayOfVInteger`\ ."""

    ARRAY_OF_FLOAT = VSECode(('container', 'arrayoffloat'), (0, 8), (1, 7))
    """Tag code for :class:`versile.vse.container.VArrayOfFloat`\ ."""

    ARRAY_OF_DOUBLE = VSECode(('container', 'arrayofdouble'), (0, 8), (1, 8))
    """Tag code for :class:`versile.vse.container.VArrayOfDouble`\ ."""

    ARRAY_OF_VFLOAT = VSECode(('container', 'arrayofvfloat'), (0, 8), (1, 9))
    """Tag code for :class:`versile.vse.container.VArrayOfVFloat`\ ."""

    BYTE_STREAMER = VSECode(('stream', 'bytestreamer'), (0, 8), (2, 1))
    """Tag code for :class:`versile.vse.stream.VByteStreamer`\ ."""

    ENTITY_STREAMER = VSECode(('stream', 'entitystreamer'), (0, 8), (2, 2))
    """Tag code for :class:`versile.vse.stream.VByteStreamer`\ ."""

    NATIVE_OBJECT = VSECode(('native', 'object'), (0, 8), (3, 1))
    """Tag code for :class:`versile.vse.native.VNative`\ ."""

    NATIVE_EXCEPTION = VSECode(('native', 'exception'), (0, 8), (3, 2))
    """Tag code for :class:`versile.vse.native.VNativeException`\ ."""

    FUNCTION = VSECode(('util', 'function'), (0, 8), (4, 1))
    """Tag code for :class:`versile.vse.util.VFunction`\ ."""

    UDPRELAY = VSECode(('util', 'udprelay'), (0, 8), (4, 2))
    """Tag code for :class:`versile.vse.util.VUDPRelay`\ ."""

    UDPRELAYEDVOP = VSECode(('util', 'udp_vop'), (0, 8), (4, 3))
    """Tag code for :class:`versile.vse.util.VUDPRelayedVOP`\ ."""

    LOGIN = VSECode(('util', 'login'), (0, 8), (4, 4))
    """Tag code for :class:`versile.vse.util.VPasswordLogin`\ ."""

    UTCTIME = VSECode(('time', 'utctime'), (0, 8), (5, 1))
    """Tag code for :class:`versile.vse.time.VUTCTime`\ ."""

    CONCEPT = VSECode(('semantics', 'concept'), (0, 8), (6, 1))
    """Tag code for :class:`versile.vse.semantics.VConcept`\ ."""

    PREFIXED_UNIT = VSECode(('math', 'prefixedunit'), (0, 8), (7, 1))
    """Tag code for :class:`versile.vse.math.VPrefixedUnit`\ ."""

    DIMENSIONAL_QUANTITY = VSECode(('math', 'dimensionalquantity'),
                                   (0, 8), (7, 2))
    """Tag code for :class:`versile.vse.math.VDimensionalQuantity`\ ."""


class VSEModuleCodes(object):
    """Module codes used for globally registering VSE modules."""

    CONTAINER = 1
    """Module code for versile.vse.container"""

    NATIVE = 2
    """Module code for versile.vse.native.module"""

    STREAM = 3
    """Module code for versile.vse.stream"""

    UTIL = 4
    """Module code for versile.vse.util"""

    TIME = 5
    """Module code for versile.vse.time"""

    SEMANTICS = 6
    """Module code for versile.vse.semantics"""

    MATH = 7
    """Module code for versile.vse.math"""
