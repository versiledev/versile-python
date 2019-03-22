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

""".. Constants and enum structures."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport

__all__ = ['VEntityCode', 'VMessageCode']
__all__ = _vexport(__all__)


class VEntityCode(object):
    """Type codes used in VEntity serialization.

    The byte serialization of :class:`versile.orb.entity.VEntity` uses
    the first byte as a type code for the object. This class specifies
    some of the type codes used.

    In addition, byte values which are smaller than VEntityCode.START
    is interpreted as an integer (with an offset). This allows
    (frequently passed) small integers to be represented as a single
    byte.

    """

    START       = 0xef
    """First code used - lower numbers are used to hold integers."""

    VINT_POS    = 0xef
    """Object code for VInteger"""

    VINT_NEG    = 0xf0
    """Object code for negative VInteger"""

    VBOOL_FALSE = 0xf1
    """Object code for VBoolean with value False."""

    VBOOL_TRUE  = 0xf2
    """Object code for VBoolean with value True."""

    VBYTES      = 0xf3
    """Object code for VBytes."""

    VSTRING     = 0xf4
    """Object code for VString without explicit encoding."""

    VSTRING_ENC = 0xf5
    """Object code for VString with explicit encoding"""

    VTUPLE      = 0xf6
    """Object code for VTuple."""

    VEXCEPTION  = 0xf7
    """Object code for VException."""

    VNONE       = 0xf8
    """Object code for VNone."""

    VFLOAT_10   = 0xf9
    """Object code for base-10 VFloat."""

    VFLOAT_2    = 0xfa
    """Object code for base-2 VFloat."""

    VFLOAT_N    = 0xfb
    """Object code for base-n (n not in [2, 10]) VFloat."""

    VREF_LOCAL  = 0xfc
    """Object code for a local VObject reference."""

    VREF_REMOTE = 0xfd
    """Object code for a remote VObject reference."""

    VTAGGED    = 0xfe
    """Object code for VTagged."""


class VMessageCode(object):
    """Mesage codes for the VLink message protocol.

    Two connected VLink nodes interact by passing messages in the form
    of :class:`versile.orb.entity.VTuple` objects. The first element
    of each message tuple is a message code which specifies what type
    of message it carries. Based on the message code of a received
    message, the VLink node can decide how to parse data contained in
    the message and how it should be processed.

    """

    METHOD_CALL              = 0x01
    """Submit a method call."""

    METHOD_CALL_VOID_RESULT  = 0x02
    """Submit a method call requesting empty (void) return value."""

    METHOD_CALL_NO_RETURN    = 0x03
    """Submit a method call requesting no return (value or exception)."""

    CALL_RESULT              = 0x04
    """Pass a call result in response to an earlier received method call."""

    CALL_EXCEPTION           = 0x05
    """Pass a call exception in response to an earlier received method call."""

    CALL_ERROR               = 0x06
    """Notify a call could not be performed.

    Note this is different from CALL_EXCEPTION, as CALL_ERROR indicates that
    the call could not be properly invoked - whereas CALL_EXCEPTION means
    the call could be invoked but the call itself failed.

    """

    NOTIFY_DEREF             = 0x07
    """Notify of a local dereference of a remotely referenced object."""

    CONFIRM_DEREF            = 0x08
    """Notifies a local object no longer has no remaining remote references."""

    KEEP_ALIVE               = 0x09
    """Sends a keep-alive notification."""
