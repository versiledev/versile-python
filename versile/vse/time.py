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

"""Implements :term:`VSE` time related types.

Importing registers :class:`VTimeModule` as a global module.

"""
from __future__ import print_function, unicode_literals

import calendar
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal

from versile.internal import _vexport, _pyver
from versile.orb.entity import VEntity, VTagged, VFloat, VTuple
from versile.orb.error import VEntityError
from versile.orb.module import VModuleResolver, VModule, VModuleConverter
from versile.orb.module import VERBase
from versile.vse.const import VSECodes, VSEModuleCodes

__all__ = ['VUTCTime']
__all__ = _vexport(__all__)


class _UTC(tzinfo):
    """Time zone info class for UTC. Used with datetime objects."""

    def utcoffset(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        if _pyver == 2:
            return b'UTC'
        else:
            return 'UTC'

    def dst(self, dt):
        return timedelta(0)



class VUTCTime(VERBase, VEntity):
    """Time reference as Coordinated Universal Time (UTC).

    The class may be constructed in one of two ways; the first format
    is ``VUTCTime(datetime)`` where *datetime* is a
    ``datetime.datetime``\ object. The object must be timezone aware.

    Alternatively, ``VUTCTime(days, secs)`` where *days* is the day
    number (an integer) since POSIX time epoch (Jan 1, 1970 UTC), and
    *secs* is the number of seconds into day (must be positive). Valid
    number of *secs* vs. the UTC standard must be numbers 0 <= *secs*
    < *N*, where *N* is normally 86400 but may also be 86399, 86401,
    or 86402 depending on whether leap seconds are applied on the
    particular date.

    In order to ensure the time value of this structure is not
    undefined due to illegal number of seconds vs. UTC standard, any
    integer component of the number *secs* which exceeds the allowed
    values for any given day is ignored. *secs* must be a value that
    can be resolved as a real number. Furthermore, if secs is sent
    as an integer or a base-10 or base-2 floating point number, then
    it may not fall outside the range 0 <= *secs* < 86402.

    Raises :exc:`exceptions.ValueError` or :exc:`exceptions.TypeError`
    if there is a conversion problem.

    """

    # Time zone info object for UTC references
    _utc = _UTC()

    def __init__(self, *args):
        if len(args) == 1:
            _dt = args[0]
            if not isinstance(_dt, datetime):
                raise TypeError('Single argument must be datetime object')
            try:
                _dt = _dt.astimezone(self._utc)
            except:
                raise ValueError('Datetime must be TZ aware (have time zone)')
            _conv = VUTCTime._v_converter(_dt)[1][0]
            args = (_conv.days, _conv.secs)

        if len(args) == 2:
            if _pyver == 2:
                _int_types = (int, long)
            else:
                _int_types = (int,)

            days = VEntity._v_lazy_native(args[0])
            secs = VEntity._v_lazy_native(args[1])
            if not isinstance(days, _int_types):
                raise TypeError('Days component must be an int (or long)')
            if not isinstance(secs, _int_types):
                # Later if such types are implemented, check for other
                # structures than VFloat that may be resolved as a number
                if not isinstance(secs, (Decimal, float, VFloat)):
                    raise TypeError('Secs must be integer or floating point')

                if not isinstance(secs, VFloat):
                    # Verify 'secs' is within allowed boundaries
                    if not (0 <= secs < 86402):
                        raise ValueError('Secs outside allowed boundaries')

            self.__days = days
            self.__secs = secs
        else:
            raise ValueError('Illegal number of arguments')

    @classmethod
    def now(cls):
        """Returns a time object for the current time.

        :returns: current time
        :rtype:   :class:`VUTCTime`

        """
        _dt = datetime.utcnow()
        _dt = _dt.replace(tzinfo=cls._utc)
        return VUTCTime(_dt)

    @classmethod
    def from_timestamp(cls, t_stamp):
        """Generates time object from a POSIX timestamp.

        :param t_stamp: POSIX timestamp
        :type  t_stamp: float
        :returns:       time object
        :rtype:         :class:`VUTCTime`

        """
        _dt = datetime.utcfromtimestamp(t_stamp)
        _dt = _dt.replace(tzinfo=cls._utc)
        return VUTCTime(_dt)

    @classmethod
    def tzinfo_utc(cls):
        """Returns a timezone object for the UTC timezone.

        :returns: UTC timezone object
        :rtype:   :class:`datetime.tzinfo`

        """
        return cls._utc

    @property
    def days(self):
        """Day number since January 1, 1970 (or before if negative)."""
        return self.__days

    @property
    def secs(self):
        """Number of seconds into day."""
        return self.__secs

    def _v_as_tagged(self, context):
        tags = VSECodes.UTCTIME.tags(context)
        value = (self.__days, self.__secs)
        return VTagged(value, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding does not use residual tags')
        if not isinstance(value, VTuple) or len(value) != 2:
            raise VTaggedParseError('Encoding value must be a 2-tuple')
        result = cls(*value)
        return (lambda x: x[0], [result])

    @classmethod
    def _v_converter(cls, obj):
        try:
            obj = obj.astimezone(cls._utc)
        except:
            raise VEntityError('Datetime object is not timezone aware')

        # Converts from datetime (which does not encode leap seconds)
        secs = calendar.timegm(obj.utctimetuple())
        days = secs // 86400
        secs -= days*86400
        secs += (Decimal(obj.microsecond) / 1000000)
        result = cls(days, secs)
        return (None, [result])

    def _v_native_converter(self):
        # Attempt conversion to datetime structure. Converts only
        # if conversion can be performed exactly.

        if _pyver == 2:
            _int_types = (int, long)
        else:
            _int_types = (int,)
        if (isinstance(self.__secs, _int_types)
            or isinstance(self.__secs, (float, Decimal))):

            _tstamp = self.__days*86400 + self.__secs

            if ((_tstamp*1000000) - ((_tstamp*1000000) // 1)) == 0:
                # Has only microseconds precision, can attempt conversion
                try:
                    result = datetime.utcfromtimestamp(_tstamp)
                    result = result.replace(tzinfo=self._utc)
                except Exception as e:
                    # Unable to convert, e.g. numbers out of bound for
                    # datetime. Passing because catch-all immediately after
                    pass
                else:
                    return (None, [result])

        # Could not convert to native type, return self
        return (None, [self])


    def __str__(self):
        # Try to convert to datetime
        _conv = self._v_native_converter()[1][0]
        if isinstance(_conv, datetime):
            return str(_conv)
        else:
            return ('UTC[1970.01.01 + %s days + %ss]'
                    % (self.__days, self.__secs))

    def __repr__(self):
        return self.__str__()



class VTimeModule(VModule):
    """Module for :term:`VSE` time related types.

    This module resolves the following classes:

    * :class:`VUTCTime`

    """
    def __init__(self):
        super(VTimeModule, self).__init__()

        # # Add decoders for conversion from VTagged
        _decoder = VUTCTime._v_vse_decoder
        _entry = VSECodes.UTCTIME.mod_decoder(_decoder)
        self.add_decoder(_entry)

        # Add encoders for lazy-conversion to VEntity
        _entry = VModuleConverter(VUTCTime._v_converter, types=(datetime,))
        self.add_converter(_entry)


_vmodule = VTimeModule()
VModuleResolver._add_vse_import(VSEModuleCodes.TIME, _vmodule)
