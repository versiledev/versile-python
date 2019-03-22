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

""".. Framework for performing input argument validation."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport
from decimal import Decimal

from versile.orb.entity import VNone, VException, VInteger, VFloat

__all__ = ['vchk', 'vmax', 'vmin', 'vset', 'vtyp']
__all__ = _vexport(__all__)


def vchk(val, *args):
    """Validates a value against a number of provided tests.

    :param val:  the value to check
    :param args: test(s) to execute, or boolean value
    :type  args: callable, bool
    :raises:     :exc:`versile.orb.entity.VException`

    For each test function in *args* the function performs
    *test(val)*\ . If any test returns False or if any of the boolean
    values in *args* are False, then an exception is raised. Otherwise
    the function returns without any return value.

    """
    try:
        for arg in args:
            if callable(arg):
                result = bool(arg(val))
            else:
                result = bool(val)
            if not result:
                raise VException()
    except:
        raise VException()

def vtyp(*types):
    """Creates a test for a value type comparison.

    :param types: type information (see below)
    :returns:     a function which validates type
    :rtype:       callable

    Each 'types' argument can be either a type, or a string which
    represents certain set of types. The following string values are
    supported:

    +--------+----------------------------------------------------+
    | String | Meaning                                            |
    +========+====================================================+
    | 'int'  | int, long                                          |
    +--------+----------------------------------------------------+
    | 'vint' | int, long, :class:`versile.orb.entity.VInteger`    |
    +--------+----------------------------------------------------+
    | 'dec'  | float, Decimal                                     |
    +--------+----------------------------------------------------+
    | 'vdec' | float, Decimal, :class:`versile.orb.entity.VFloat` |
    +--------+----------------------------------------------------+
    | 'num'  | 'int' or 'dec'                                     |
    +--------+----------------------------------------------------+
    | 'vnum' | 'vint' or 'vdec'                                   |
    +--------+----------------------------------------------------+

    Example usage:

    >>> from versile.orb.validate import vtyp
    >>> test = vtyp(unicode, 'vint')
    >>> test(u'coconut')
    True
    >>> test(b'coconut')
    False
    >>> test(42)
    True
    >>> test(42L)
    True
    >>> test(42.0)
    False
    >>> # Resolves to True because isinstance(True, int) resolves to True
    ... test(True) #doctest: +NORMALIZE_WHITESPACE
    True

    """
    def chk(val):
        for typ in types:
            if isinstance(typ, (bytes, unicode)):
                if typ == 'int' or typ == 'num':
                    if isinstance(val, (int, long)):
                        return True
                if typ == 'vint' or typ == 'vnum':
                    if isinstance(val, (int, long, VInteger)):
                        return True
                if typ == 'dec' or typ == 'num':
                    if isinstance(val, (float, Decimal)):
                        return True
                if typ == 'vdec' or typ == 'vnum':
                    if isinstance(val, (float, Decimal, VFloat)):
                        return True
            elif isinstance(val, typ):
                return True
        return False
    return chk


def vmin(min_val, inc=True):
    """Creates a test which compares a value with a minimum value.

    :param min_val: minimum value to test for
    :param inc:     if True then include endpoint
    :type  inc:     bool
    :returns:       a test which compares a value with a set minimum
    :rtype:         callable

    Example usage:

    >>> from versile.orb.validate import vmin
    >>> test = vmin(100)
    >>> test(99) #doctest: +NORMALIZE_WHITESPACE
    False
    >>> test(100) #doctest: +NORMALIZE_WHITESPACE
    True
    >>> test(101) #doctest: +NORMALIZE_WHITESPACE
    True

    """
    def chk(val):
        if inc:
            return (val >= min_val)
        else:
            return (val > min_val)
    return chk

def vmax(max_val, inc=True):
    """Creates a test which compares a value with a maximum value.

    :param max_val: maximum value to test for
    :param inc:     if True then include endpoint
    :type  inc:     bool
    :returns:       a test which compares a value with a set maximum
    :rtype:         callable

    Example usage:

    >>> from versile.orb.validate import vmax
    >>> test = vmax(100)
    >>> test(101) #doctest: +NORMALIZE_WHITESPACE
    False
    >>> test(100) #doctest: +NORMALIZE_WHITESPACE
    True
    >>> test(99)  #doctest: +NORMALIZE_WHITESPACE
    True

    """
    def chk(val):
        if inc:
            return (val <= max_val)
        else:
            return (val < max_val)
    return chk

def vset(val):
    """Tests whether a value is not None

    :param val: a value to test
    :returns:   True if value is not None
    :rtype:     bool

    Will also return True if the value is an instance of
    :class:`versile.orb.entity.VNone` (which represents None).

    Example usage:

    >>> from versile.orb.validate import vset
    >>> from versile.orb.entity import VNone
    >>> vset(1)
    True
    >>> vset(0)
    True
    >>> vset(u'hi')
    True
    >>> vset(None)
    False
    >>> vset(VNone())
    False

    """
    return (val is not None and not isinstance(val, VNone))
