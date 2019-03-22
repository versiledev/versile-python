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

"""Functionality for internal use by versile modules."""
from __future__ import print_function, unicode_literals

import sys
import platform

try:
    _vplatform = platform.python_implementation().lower()
except ValueError:
    _vplatform = 'ironpython'

__all__ = []


if _vplatform == 'ironpython':
    # This is a set of functions which act as IronPython wrappers for standard
    # CPython operations or types.

    # Python major version
    _pyver = 2
    # Transforms __all__ from bytes to unicode
    _vexport = lambda l: l
    # Use when IronPython requires 'str' instead of 'bytes'
    _b2s = lambda b: str(b)
    # Use when IronPython returns 'str' instead of 'bytes'
    _s2b = lambda s: bytes(s)
    # 'bytes' constructor is broken at least for int, should use this instead
    _val2b = lambda val: _s2b(str(val))
    # Implements ord()
    _b_ord = lambda b: ord(b)
    # Implements chr()
    _b_chr = lambda n: chr(n)
    # string/bytes split() method is broken, use this instead
    def _ssplit(s, substr):
        result = []
        start = 0
        while True:
            pos = s.find(substr, start)
            if pos >= 0:
                result.append(s[start:pos])
                start = pos + len(substr)
            else:
                result.append(s[start:])
                break
        return result
    # bytes '%' formatting is broken, use this
    def _bfmt(fmt, *args):
        return _s2b(_b2s(fmt) % args)
else:
    if sys.version_info[0] == 2:
        _pyver = 2
        _b2s = lambda b: b
        _s2b = lambda s: s
        _vexport = lambda l: [bytes(e) for e in l]
        _b_ord = lambda b: ord(b)
        _b_chr = lambda b: chr(b)
        _val2b = lambda val: bytes(val)
    else:
        _pyver = 3
        _vexport = lambda l: l
        _b2s = lambda b: str(b, 'utf8')
        _s2b = lambda s: bytes(s, 'utf8')
        _b_ord = lambda b: b
        _b_chr = lambda n: bytes((n,))  # TODO - TEMPORARY FIX
        _val2b = lambda val: _s2b(str(val))
    def _ssplit(s, substr):
        return s.split(substr)
    def _bfmt(fmt, *args):
        return fmt % args

def _v_silent(exc):
    """Receive a 'silent' exception.

    :param exc: exception
    :type  exc: :exc:`exceptions.Exceptions`

    Default ignores the exception and just does nothing. This function can be
    modified to debug ignored exceptions.

    """
    pass
