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

""":term:`ASN.1` data structures, definitions and encoding/decoding."""
from __future__ import print_function, unicode_literals

import collections
import datetime
import time

from versile.internal import _b2s, _s2b, _val2b, _bfmt, _vexport, _pyver
from versile.internal import _b_ord, _b_chr
from versile.common.iface import abstract
from versile.common.util import VBitfield, VObjectIdentifier
from versile.common.util import posint_to_bytes, bytes_to_posint

__all__ = ['VASN1Exception', 'VASN1Tag', 'VASN1Base', 'VASN1Null',
           'VASN1Boolean', 'VASN1Integer', 'VASN1BitString',
           'VASN1OctetString', 'VASN1ObjectIdentifier', 'VASN1Enumerated',
           'VASN1UTF8String', 'VASN1NumericString', 'VASN1PrintableString',
           'VASN1IA5String', 'VASN1VisibleString', 'VASN1UTCTime',
           'VASN1GeneralizedTime', 'VASN1UniversalString', 'VASN1Sequence',
           'VASN1SequenceOf', 'VASN1Set', 'VASN1SetOf', 'VASN1Tagged',
           'VASN1Unknown', 'VASN1Definition', 'VASN1DefUniversal',
           'VASN1DefUnknown', 'VASN1DefNull', 'VASN1DefBoolean',
           'VASN1DefInteger', 'VASN1DefBitString', 'VASN1DefOctetString',
           'VASN1DefObjectIdentifier', 'VASN1DefEnumerated',
           'VASN1DefUTF8String', 'VASN1DefNumericString',
           'VASN1DefPrintableString', 'VASN1DefIA5String',
           'VASN1DefVisibleString', 'VASN1DefUTCTime',
           'VASN1DefGeneralizedTime', 'VASN1DefUniversalString',
           'VASN1DefSequenceOf', 'VASN1DefSequence', 'VASN1DefSetOf',
           'VASN1DefSet', 'VASN1DefChoice', 'VASN1DefTagged']
__all__ = _vexport(__all__)


class VASN1Exception(Exception):
    """General :term:`ASN.1` operation exception"""


class VASN1Tag(object):
    """An :term:`ASN.1` tag.

    :param tag_cls:    tag class of the tag
    :type  tag_cls:    int
    :param tag_number: tag number
    :type  tag_number: int

    The tag class uses bit mask 0xc0 and should have the value
    :const:`UNIVERSAL` (generally reserved), :const:`APPLICATION`\ ,
    :const:`CONTEXT` or :const:`PRIVATE`\ .

    """

    UNIVERSAL   = 0x00
    """Tag class for Universal tag encoding."""

    APPLICATION = 0x40
    """Tag class for Application tag encoding."""

    CONTEXT     = 0x80
    """Tag class for Context-Specific tag encoding."""

    PRIVATE     = 0xc0
    """Tag class for Private tag encoding."""

    def __init__(self, tag_cls, tag_number):
        if tag_cls != tag_cls & 0xc0:
            raise VASN1Exception('Invalid tag class')
        self._tag_cls = tag_cls
        self._tag_number = tag_number

    def encode_der(self, constructed):
        """Encodes identifier octets for the tag.

        :param constructed: if True use constructed mode
        :returns:           identifier octets
        :rtype:             bytes

        """
        return self._ber_enc_identifier(self._tag_cls, constructed,
                                        self._tag_number)

    @classmethod
    def from_der(cls, data):
        """Create tag from :term:`DER` data

        :param data: :term:`DER` data
        :type  data: bytes
        :returns:    ((tag, is_constructed), bytes_read)
        :rtype:      ((\ :class:`VASN1Tag`\ , bool), int)

        """
        _data, num_read = cls._ber_dec_identifier(data)
        tag_cls, constructed, tag_number = _data
        return (cls(tag_cls, tag_number), constructed), num_read

    @classmethod
    def ctx(cls, tag_number):
        """Create context-specific tag from tag number.

        :param tag_number: tag number
        :type  tag_number: int
        :returns:          context-specific tag
        :rtype:            :class:`VASN1Tag`

        """
        return cls(cls.CONTEXT, tag_number)

    @property
    def tag_class(self):
        """Tag class of the tag."""
        return self._tag_cls

    @property
    def tag_number(self):
        """Tag number of the tag."""
        return self._tag_number

    @classmethod
    def _ber_enc_identifier(cls, tag_class, is_constructed, tag):
        first = tag_class
        if is_constructed:
            first |= 0x20
        if tag < 31:
            first |= tag
            result = posint_to_bytes(first)
        else:
            first |= 0x1f
            result = collections.deque()
            bt = _s2b(bin(tag))[2:]
            while bt:
                next_octet = bt[-7:]
                bt = bt[:-7]
                next_octet = int(next_octet, 2) # from base-2
                next_octet |= 0x80
                result.appendleft(next_octet)
            right_octet = result.pop()
            right_octet &= 0x7f
            result.append(right_octet)
            result.appendleft(first)
            result = b''.join([_s2b(_b_chr(e)) for e in result])
        return result

    @classmethod
    def _ber_dec_identifier(cls, data):
        """Decodes a tag from :term:`BER` encoded octet identifier data.

        :param data: :term:`BER` encoded tag octet identifier
        :type  data: bytes
        :returns:    ((tag_class, is_constructed, tag_number), bytes_read)
        :rtype:      ((int, bool, int), int)

        """
        if not data:
            raise VASN1Exception('Incomplete data')
        pos = 0
        first = _b_ord(data[0])
        tag_class = first & 0xc0
        is_constructed = bool(first & 0x20)
        if first & 0x1f < 0x1f:
            tag = first & 0x1f
        else:
            tag = []
            while True:
                pos += 1
                try:
                    next_byte = _b_ord(data[pos])
                except IndexError:
                    raise VASN1Exception('Incomplete data')
                tag.append(bytes(bin(next_byte))[2:][-7:].zfill(7))
                if not next_byte & 0x80:
                    break
            tag = int(b''.join(tag), 2) # from base-2
        return ((tag_class, is_constructed, tag), pos+1)

    def __eq__(self, other):
        if not isinstance(other, VASN1Tag):
            return False
        return (other._tag_cls == self._tag_cls
                and other._tag_number == self._tag_number)

    def __ne__(self, other):
        return not (self.__eq__(other))

    def __hash__(self):
        return hash((self._tag_cls, self._tag_number))

    def __str__(self):
        if _pyver == 2:
            if self._tag_cls == self.UNIVERSAL:
                tc = b'UNIVERSAL '
            elif self._tag_cls == self.APPLICATION:
                tc = b'APPLICATION '
            elif self._tag_cls == self.PRIVATE:
                tc = b'PRIVATE '
            else:
                tc = b''
            return _b2s(_bfmt(b'[ %s%s ]', tc, self._tag_number))
        else:
            if self._tag_cls == self.UNIVERSAL:
                tc = 'UNIVERSAL '
            elif self._tag_cls == self.APPLICATION:
                tc = 'APPLICATION '
            elif self._tag_cls == self.PRIVATE:
                tc = 'PRIVATE '
            else:
                tc = ''
            return '[ %s%s ]' % (tc, self._tag_number)

    def __repr__(self):
        if _pyver == 2:
            return _b2s(_bfmt(b'\'%s\'', str(self)))
        else:
            return '\'%s\'' % str(self)


@abstract
class VASN1Base(object):
    """Base class for :term:`ASN.1` objects.

    :param name:       a name for the :term:`ASN.1` type (or None)
    :type  name:       unicode
    :param definition: a definition of the :term:`ASN.1` type (or None)
    :type  definition: :class:`VASN1Definition`

    """

    def __init__(self, name=None, definition=None):
        self.__name = name
        self.__def = definition

    @abstract
    @property
    def tag(self):
        """Identifier (tag) of the :term:`ASN.1` object."""
        raise NotImplementedError

    @abstract
    def native(self, deep=True):
        """Returns a python-native representation of the value.

        :param deep: if True perform deep native-conversion
        :type  deep: bool
        :returns:    native representation, or self

        """
        raise NotImplementedError

    @abstract
    def encode_der(self, with_tag=True):
        """Returns the object's :term:`DER` representation.

        :param with_tag: if True include identifier octets
        :type  with_tag: bool
        :returns:        :term:`DER` encoding
        :rtype:          bytes

        """
        raise NotImplementedError

    def validate(self, strict=False):
        """Validates against the object's definition (if set).

        :param strict: if True require a definition must be registered
        :type  strict: bool
        :returns:      True if validated (or not strict and no definition)

        Validation is performed by :term:`DER` encoding and then using
        the :attr:`asn1def` definition set on the object to parse.

        """
        if not self.__def:
            return not strict
        try:
            der = self.encode_der()
            obj = self.__def.parse_der(der)
        except VASN1Exception as e:
            return False
        else:
            return True

    @property
    def asn1name(self):
        """Type name set for the object."""
        return self.__name

    @property
    def asn1def(self):
        """:class:`VASN1Definition` set for the object."""
        return self.__def

    @classmethod
    def lazy(cls, value):
        """Lazy-converts a native value to :class:`VASN1Base`\ .

        :param value: the value to convert
        :returns:     lazy-converted object
        :rtype:       :class:`VASN1Base`
        :raises:      :exc:`VASN1Exception`

        Raises an exception if value cannot be converted. Types are
        lazy-converted as follows:

        +----------------------------+--------------------------------+
        | Native type                | :class:`VASN1Base` type        |
        +============================+================================+
        | :class:`VASN1Base`         | self                           |
        +----------------------------+--------------------------------+
        | None                       | :class:`VASN1Null`             |
        +----------------------------+--------------------------------+
        | bool                       | :class:`VASN1Boolean`          |
        +----------------------------+--------------------------------+
        | int, long                  | :class:`VASN1Integer`          |
        +----------------------------+--------------------------------+
        | unicode                    | :class:`VASN1UTF8String`       |
        +----------------------------+--------------------------------+
        | bytes                      | :class:`VASN1OctetString`      |
        +----------------------------+--------------------------------+
        | VBitfield                  | :class:`VASN1BitString`        |
        +----------------------------+--------------------------------+
        | VObjectIdentifier          | :class:`VASN1ObjectIdentifier` |
        +----------------------------+--------------------------------+
        | set, frozenset             | :class:`VASN1Set`              |
        +----------------------------+--------------------------------+
        | tuple, list                | :class:`VASN1Sequence`         |
        +----------------------------+--------------------------------+
        | :class:`datetime.datetime` | :class:`VASN1GeneralizedTime`  |
        +----------------------------+--------------------------------+

        """
        if isinstance(value, VASN1Base):
            return value
        elif value is None:
            return VASN1Null()
        elif isinstance(value, bool):
            return VASN1Boolean(value)
        elif isinstance(value, (int, long)):
            return VASN1Integer(value)
        elif isinstance(value, unicode):
            return VASN1UTF8String(value)
        elif isinstance(value, bytes):
            return VASN1OctetString(value)
        elif isinstance(value, datetime.datetime):
            return VASN1GeneralizedTime(value)
        elif isinstance(value, VObjectIdentifier):
            return VASN1ObjectIdentifier(value)
        elif isinstance(value, VBitfield):
            return VASN1BitString(value)
        elif isinstance(value, (set, frozenset)):
            return VASN1Set(value)
        elif isinstance(value, (tuple, list)):
            return VASN1Sequence(value)
        else:
            raise VASN1Exception('Cannot lazy-convert value')

    @classmethod
    def _ber_enc_length_definite(cls, length, short=True):
        """Returns :term:`BER` definite encoding of content octets length.

        :param length: the length to encode
        :type  length: int
        :param short:  if True, then use short form if possible
        :type  short:  int
        :returns:      :term:`BER` definite length encoding
        :rtype:        bytes

        """
        if length <= 0x7f and short:
            if _pyver == 2:
                return _s2b(_b_chr(length))
            else:
                return bytes((length,))
        else:
            length_bytes = posint_to_bytes(length)
            if len(length_bytes) >= 0x7f:
                raise VASN1Exception('Length overflow')
            if _pyver == 2:
                first_byte = _s2b(_b_chr(len(length_bytes) | 0x80))
            else:
                first_byte = bytes((len(length_bytes) | 0x80,))
            return first_byte + length_bytes

    @classmethod
    def _ber_enc_length_indefinite(cls):
        """Returns :term:`BER` indefinite length code.

        :returns:      :term:`BER` indefinite length code
        :rtype:        bytes

        """
        return b'\x80' # NEW, old was return _s2b(_b_chr(0x80))

    @classmethod
    def _ber_enc_content_definite(cls, content):
        """Returns :term:`BER` content encoding for definite length.

        :param content: content to encode
        :type  content: bytes
        :returns:       encoded content
        :rtype:         bytes

        """
        return content

    @classmethod
    def _ber_enc_content_indefinite(cls, content):
        """Returns :term:`BER` content encoding for indefinite length.

        :param content: content to encode
        :type  content: bytes
        :returns:       encoded content
        :rtype:         bytes

        """
        return content + b'\x00\x00'

    @classmethod
    def _ber_enc_tagged_content(cls, tag_class, is_constructed, tag, content,
                               definite=True, short=True):
        """Return :term:`BER` encoding for general tagged content.

        :param tag_class:      tag class of the tag (bits 0xc0)
        :type  tag_class:      int
        :param is_constructed: if True then constructed tag
        :type  is_constructed: bool
        :param tag:            tag ID of the tag
        :type  tag:            int
        :param content:        binary content
        :type  content:        bytes
        :param definite:       if True encode as definite-length
        :type  definite:       bool
        :param short:          if True use short-length encoding if possible
        :type  short:          bool
        :returns:              :term:`BER` encoded content
        :rtype:                bytes

        """
        identifier = VASN1Tag._ber_enc_identifier(tag_class, is_constructed,
                                                  tag)
        if definite:
            length = cls._ber_enc_length_definite(len(content), short=short)
            content = cls._ber_enc_content_definite(content)
        else:
            length = cls._ber_enc_length_indefinite()
            content = cls._ber_enc_content_indefinite(content)
        return b''.join((identifier, length, content))


class VASN1Null(VASN1Base):
    """An :term:`ASN.1` Null value.

    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, name=None, definition=None):
        if name is None:
            name = 'NULL'
        super(VASN1Null, self).__init__(name=name, definition=definition)

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return None

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_null()
        if with_tag:
            # X.690: Null always has primitive encoding
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x05')[0][0]

    @classmethod
    def _ber_enc_null(cls):
        return b'\x00'

    def __hash__(self):
        return hash(None)

    def __eq__(self, other):
        return isinstance(other, VASN1Null) or other is None

    def __str__(self):
        return str(None)

    def __repr__(self):
        return repr(None)


class VASN1Boolean(VASN1Base):
    """An :term:`ASN.1` Boolean value.

    :param value:      the object's value
    :type  value:      bool
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'BOOLEAN'
        super(VASN1Boolean, self).__init__(name=name, definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_boolean(self.__value)
        if with_tag:
            # X.690: Boolean always has primitive encoding
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x01')[0][0]

    @classmethod
    def _ber_enc_boolean(cls, value, true_val=b'\xff'):
        if _pyver != 2 and isinstance(true_val, bytes):
            true_val = true_val[0]
        if not 0 < _b_ord(true_val) <= 0xff:
            raise VASN1Exception('Content byte must be a non-zero byte')
        if value:
            if _pyver == 2:
                return b'\x01' + true_val
            else:
                return b'\x01' + bytes((true_val,))
        else:
            return b'\x01\x00'

    def __hash__(self):
        return hash(bool(self.__value))

    def __eq__(self, other):
        return ((isinstance(other, VASN1Boolean)
                 and self.__value == other.native())
                or self.__value == other)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1Integer(VASN1Base):
    """An :term:`ASN.1` Integer value.

    :param value:      the object's value
    :type  value:      int, long
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'INTEGER'
        super(VASN1Integer, self).__init__(name=name, definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_integer(self.__value)
        if with_tag:
            # X.690: Integer always has primitive encoding
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x02')[0][0]

    @classmethod
    def _ber_enc_int_family(cls, value):
        if value == 0:
            return b'\x01\x00'
        elif value > 0:
            content = posint_to_bytes(value)
            if _b_ord(content[0]) & 0x80:
                content = b'\x00' + content
            return cls._ber_enc_length_definite(len(content)) + content
        else:
            block = posint_to_bytes(-value)
            value = (1 << (8*len(block))) + value
            content = posint_to_bytes(value)
            return cls._ber_enc_length_definite(len(content)) + content

    @classmethod
    def _ber_enc_integer(cls, value):
        return cls._ber_enc_int_family(value)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


# Does not support BER constructed encoding
class VASN1BitString(VASN1Base):
    """An :term:`ASN.1` BitString value.

    :param value:      the object's value
    :type value:       :class:`versile.common.util.VBitfield`
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'BIT STRING'
        super(VASN1BitString, self).__init__(name=name, definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_bitstring(self.__value, definite=True)
        if with_tag:
            # X.690 section 10.2 specifies DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x03')[0][0]

    @classmethod
    def _ber_enc_bitstring(cls, value, definite):
        """

        :type value:     :class:`versile.common.util.VBitfield`
        :param definite: if True encode with definite content length

        """
        bits = value.bits
        padding = len(bits) % 8
        if padding:
            padding = 8 - padding
            bits = bits + padding*(0,)
        if _pyver == 2:
            first_byte = _s2b(_b_chr(padding))
        else:
            first_byte = bytes((padding,))
        if _pyver == 2:
            bits = b''.join([_s2b(_b_chr(_b_ord(b'0')+e)) for e in bits])
        else:
            bits = bytes([e+ord('0') for e in bits])
        octets = (bits[i:i+8] for i in xrange(0, len(bits), 8))
        if _pyver == 2:
            octets = b''.join([_s2b(_b_chr(int(str(e), 2))) for e in octets])
        else:
            octets = bytes([int(_b2s(e), 2) for e in octets])
        content = first_byte + octets
        if definite:
            return cls._ber_enc_length_definite(len(content)) + content
        else:
            return (cls._ber_enc_length_indefinite()
                    + cls._ber_enc_content_indefinite(content))

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


# Does not support constructed BER encoding
class VASN1OctetString(VASN1Base):
    """An :term:`ASN.1` Octet String value.

    :param value:      the object's value
    :type  value:      bytes
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'OCTET STRING'
        super(VASN1OctetString, self).__init__(name=name,
                                               definition=definition)
        if not isinstance(value, bytes):
            # PLATFORM - added check due to IronPython str/bytes handling
            raise TypeError('VASN1OctetString value must be bytes')
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_octet_string(self.__value)
        if with_tag:
            # X.690 section 10.2 specifies DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x04')[0][0]

    @classmethod
    def _ber_enc_family(cls, value):
        return cls._ber_enc_length_definite(len(value)) + value

    @classmethod
    def _ber_enc_octet_string(cls, value):
        return cls._ber_enc_family(value)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


# Does not support relative object identifiers, only absolute
class VASN1ObjectIdentifier(VASN1Base):
    """An :term:`ASN.1` Object Idenfifier value.

    :param value:      the object's value
    :type value:       :class:`versile.common.util.VObjectIdentifier`
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'OBJECT IDENTIFIER'
        super(VASN1ObjectIdentifier, self).__init__(name=name,
                                                    definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_object_identifier(self.__value)
        if with_tag:
            # X.690 specifies octet identifier always has primitive encoding
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the universal ASN.1 ObjectIdentifier type."""
        return VASN1Tag.from_der(b'\x06')[0][0]

    @classmethod
    def _ber_enc_object_identifier(cls, value):
        """

        :type value: :class:`versile.common.util.VObjectIdentifier`

        """
        oid = value.oid
        oid = (40*oid[0]+oid[1],) + tuple(oid[2:])
        content = []
        for o in oid:
            result = collections.deque()
            bt = _s2b(bin(o))[2:]
            while bt:
                next_octet = bt[-7:]
                bt = bt[:-7]
                next_octet = int(_b2s(next_octet), 2) # from base-2
                next_octet |= 0x80
                result.appendleft(next_octet)
            right_octet = result.pop()
            right_octet &= 0x7f
            result.append(right_octet)
            if _pyver == 2:
                result = b''.join([bytes(_b_chr(e)) for e in result])
            else:
                result = bytes(result)
            content.append(result)
        content = b''.join(content)
        return cls._ber_enc_length_definite(len(content)) + content

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1Enumerated(VASN1Base):
    """An :term:`ASN.1` Enumerated value.

    :param value:      the object's value
    :type  value:      int, long
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'ENUMERATED'
        super(VASN1Enumerated, self).__init__(name=name, definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_enum(self.__value)
        if with_tag:
            # X.690: Enumerated always has primitive encoding
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x0a')[0][0]

    @classmethod
    def _ber_enc_enum(cls, value):
        return VASN1Integer._ber_enc_int_family(value)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1UTF8String(VASN1Base):
    """An :term:`ASN.1` UTF8String value.

    :param value:      the object's value
    :type  value:      unicode
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'UTF8String'
        super(VASN1UTF8String, self).__init__(name=name, definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_utf8_string(self.__value)
        if with_tag:
            # X.690 section 10.2 specifies DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x0c')[0][0]

    @classmethod
    def _ber_enc_utf8_string(cls, value):
        """

        :type value: unicode

        """
        payload = bytes(value.encode('utf8'))
        return VASN1OctetString._ber_enc_family(payload)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1NumericString(VASN1Base):
    """An :term:`ASN.1` NumericString value.

    :param value:      the object's value
    :type  value:      unicode
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'NumericString'
        super(VASN1NumericString, self).__init__(name=name,
                                                 definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_numeric_string(self.__value)
        if with_tag:
            # X.690 section 10.2 specifies DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x12')[0][0]

    @classmethod
    def _ber_enc_numeric_string(cls, value):
        """

        :type value: unicode

        """
        for c in value:
            if c not in '0123456789 ':
                raise VASN1Exception('Illegal Numeric String character')
        payload = bytes(value)
        return VASN1OctetString._ber_enc_family(payload)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1PrintableString(VASN1Base):
    """An :term:`ASN.1` PrintableString value.

    :param value:      the object's value
    :type  value:      unicode
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'PrintableString'
        super(VASN1PrintableString, self).__init__(name=name,
                                                   definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_printable_string(self.__value)
        if with_tag:
            # X.690 section 10.2 specifies DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x13')[0][0]

    @classmethod
    def _ber_enc_printable_string(cls, value):
        """

        :type value: unicode

        """
        for c in value.lower():
            if c not in 'abcdefghijklmnopqrstuvwxyz0123456789 \'()+,-./:=?':
                raise VASN1Exception('Illegal Printable String character')
        if _pyver == 2:
            payload = bytes(value)
        else:
            payload = bytes(value, 'utf8')
        return VASN1OctetString._ber_enc_family(payload)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1IA5String(VASN1Base):
    """An :term:`ASN.1` IA5String value.

    :param value:      the object's value
    :type  value:      unicode
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'IA5String'
        super(VASN1IA5String, self).__init__(name=name, definition=definition)
        if _pyver == 2:
            if max((_b_ord(v) for v in value)) > 0x7f:
                raise TypeError('Illegal non-ASCII characters')
        else:
            if max(ord(v) for v in value) > 0x7f:
                raise TypeError('Illegal non-ASCII characters')
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_ia5string(self.__value)
        if with_tag:
            # X.690 section 10.2 specifies DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x16')[0][0]

    @classmethod
    def _ber_enc_ia5string(cls, value):
        """

        :type value: unicode

        """
        try:
            if _pyver == 2:
                payload = bytes(value)
            else:
                payload = bytes(value, 'utf8')
        except:
            raise VASN1Exception('Illegal non-ASCII characters')
        if max((_b_ord(v) for v in payload)) > 0x7f:
            raise VASN1Exception('Illegal non-ASCII characters')
        return VASN1OctetString._ber_enc_family(payload)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1VisibleString(VASN1Base):
    """An :term:`ASN.1` VisibleString value.

    :param value:      the object's value
    :type  value:      unicode
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'VisibleString'
        super(VASN1VisibleString, self).__init__(name=name,
                                                 definition=definition)
        if _pyver == 2:
            if (max((_b_ord(v) for v in value)) > 0x7f
                or min((_b_ord(v) for v in value)) < 0x20):
                raise TypeError('Illegal non-visible ASCII characters')
        else:
            if (max((ord(v) for v in value)) > 0x7f
                or min((ord(v) for v in value)) < 0x20):
                raise TypeError('Illegal non-visible ASCII characters')
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_visiblestring(self.__value)
        if with_tag:
            # X.690 section 10.2 specifies DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x1a')[0][0]

    @classmethod
    def _ber_enc_visiblestring(cls, value):
        """

        :type value: unicode

        """
        try:
            if _pyver == 2:
                payload = bytes(value)
            else:
                payload = bytes(value, 'utf8')
        except:
            raise VASN1Exception('Illegal non-visible ASCII characters')
        if (max((_b_ord(v) for v in payload)) > 0x7f
            or min((_b_ord(v) for v in payload)) < 0x20):
            raise VASN1Exception('Illegal non-visible ASCII characters')
        return VASN1OctetString._ber_enc_family(payload)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1UTCTime(VASN1Base):
    """An :term:`ASN.1` UTCTime value.

    :param value:      the object's value
    :type  value:      :class:`datetime.datetime`
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'UTCTime'
        super(VASN1UTCTime, self).__init__(name=name, definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_utc_time(self.__value)
        if with_tag:
            # GeneralizedTime is [UNIVERSAL 23] IMPLICIT VisibleString
            # X.690 section 8.14.3 plus 10.2 defines DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x17')[0][0]

    @classmethod
    def _ber_enc_utc_time(cls, value):
        """

        :type value: :class:`datetime.datetime`

        """
        payload = _s2b(value.strftime('%y%m%d%H%M%SZ'))
        return VASN1OctetString._ber_enc_family(payload)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1GeneralizedTime(VASN1Base):
    """An :term:`ASN.1` GeneralizedTime value.

    :param value:      the object's value
    :type  value:      :class:`datetime.datetime`
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'GeneralizedTime'
        super(VASN1GeneralizedTime, self).__init__(name=name,
                                                   definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_generalized_time(self.__value)
        if with_tag:
            # GeneralizedTime is [UNIVERSAL 24] IMPLICIT VisibleString
            # X.690 section 8.14.3 plus 10.2 defines DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x18')[0][0]

    @classmethod
    def _ber_enc_generalized_time(cls, value):
        """

        :type value: :class:`datetime.datetime`

        """
        payload = _s2b(value.strftime('%Y%m%d%H%M%S'))
        micro = value.microsecond
        if micro:
            micro = _val2b(micro).zfill(6)
            if _pyver == 2:
                while micro[-1] == b'0':
                    micro = micro[:-1]
            else:
                while micro[-1] == 0x00:
                    micro = micro[:-1]
            if micro:
                payload += b'.' + micro
        payload += b'Z'
        return VASN1OctetString._ber_enc_family(payload)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VASN1UniversalString(VASN1Base):
    """An :term:`ASN.1` UniversalString value.

    :param value:      the object's value
    :type  value:      unicode
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    """
    def __init__(self, value, name=None, definition=None):
        if name is None:
            name = 'UniversalString'
        super(VASN1UniversalString, self).__init__(name=name,
                                                   definition=definition)
        self.__value = value

    @property
    def tag(self):
        return self.univ_tag()

    def native(self, deep=True):
        return self.__value

    def encode_der(self, with_tag=True):
        payload = self._ber_enc_universal_string(self.__value)
        if with_tag:
            # X.690 section 10.2 specifies DER uses primitive form
            return self.tag.encode_der(constructed=False) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x1c')[0][0]

    @classmethod
    def _ber_enc_universal_string(cls, value):
        """

        :type value: unicode

        """
        if _pyver == 2:
            payload = _s2b(value.encode('utf-32'))
        else:
            payload = value.encode('utf-32')
        return VASN1OctetString._ber_enc_family(payload)


class VASN1Sequence(VASN1Base):
    """An :term:`ASN.1` Sequence.

    :param value:      values to append (or None)
    :type  value:      list, tuple
    :param explicit:   if True set default explicit tagged value encoding
    :type  explicit:   bool
    :param lazy:       if True then lazy-convert values to :class:`VASN1Base`
    :type  lazy:       bool
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    If *value* is not None then sequence elements are added by adding
    *value* elements with explicit encoding and no outer tag.

    If *explicit* is True then tagged values by default are explicit,
    otherwise they are by default implicit. This can be used as a
    mechanism to specify tag defaults (as specified by an
    :term:`ASN.1` type's associated module, ref. :term:`X.680`\ ).

    The class overloads getattr so any non-defined attribute is
    handled as a lookup to :meth:`named_element` for a registered
    element of the associated name.

    """

    def __init__(self, value=None, explicit=True, lazy=True,
                 name=None, definition=None):
        if name is None:
            name = 'SEQUENCE'
        super(VASN1Sequence, self).__init__(name=name, definition=definition)
        self.__value = []
        self.__explicit = True
        self.__named = dict()
        if value:
            for item in value:
                self.append(item, lazy=lazy)

    def __getattr__(self, attr):
        result = self.__named.get(attr, None)
        if result is not None:
            return result
        else:
            raise AttributeError()

    def append(self, value, name=None, is_default=False, lazy=True):
        """Appends a value to the list

        :param value:        the value to append
        :param name:         a name associated with the parameter, or None
        :type  name:         unicode
        :param is_default:   if True, value is the default for the element
        :type  is_default:   bool
        :param lazy:         if True, lazy-convert value to :class:`ASN1Base`
        :type  lazy:         bool

        .. warning::

            If *is_default* is True then as per :term:`DER` encoding
            spec that element is not included in a :term:`DER`
            encoding of the object. Conversely, if the element is the
            default value for the associated type specification, if
            *is_default* is not correctly set then encoded :term:`DER`
            data will not decode correctly by a parser for that type.

        """
        if lazy:
            value = VASN1Base.lazy(value)
        if not isinstance(value, VASN1Base):
            raise VASN1Exception('Sequence members must be VASN1Base')
        self.__value.append((value, is_default))
        if name:
            if name in self.__named:
                raise VASN1Exception('Name already in use')
            else:
                self.__named[name] = value

    def c_app(self, name, *args, **kargs):
        """Creates an object and a method for appending as an element.

        :param name: the name of the element registered on :meth:`asn1def`
        :type  name: unicode
        :returns:    a function which appends a constructed object
        :rtype:      callable

        This method is a convenience method for creating and adding an
        element which conforms with a derived class of
        :class:`VASN1DefSequence`\ . The following code::

            f = self.c_app(name, *args, **kargs)(**args2, **kargs2)

        Is equivalent to::

            obj = self.asn1def.named_def(name).create(*args, **kargs)
            if 'name' not in kargs2:
                kargs2['name'] = name
            self.append(obj, *args2, **kargs2)

        .. note::

            This method returns a function, not an object. This is done in
            order to enable separating object creation arguments from
            sequence append arguments.

        """
        obj = self.asn1def.named_def(name).create(*args, **kargs)
        app_method = self.append
        def append(*args2, **kargs2):
            if 'name' not in kargs2:
                kargs2['name'] = name
            app_method(obj, *args2, **kargs2)
            return obj
        return append

    def native(self, deep=True):
        if deep:
            it = (v[0].native(deep=True) for v in self.__value)
            return tuple(it)
        else:
            return tuple((v[0] for v in self.__value))

    def named_element(self, name):
        """Returns an element registered with the associated name.

        :param name: element name
        :type  name: unicode
        :returns:    named sequence element

        """
        return self.__named[name]

    def encode_der(self, with_tag=True):
        payloads = []
        for val, is_default in self.__value:
            # DER encoding specifies default elements are not included
            if not is_default:
                item_der = val.encode_der()
                payloads.append(item_der)
        payload = self._ber_enc_sequence(payloads)
        if with_tag:
            # X.690: Sequence always has constructed encoding
            return self.tag.encode_der(constructed=True) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x30')[0][0]

    @property
    def tag(self):
        return self.univ_tag()

    @property
    def names(self):
        """A list of names for sequence elements registered with name."""
        return self.__named.keys()

    @classmethod
    def _ber_enc_seq_family(cls, elements):
        """

        :param elements: a list or tuple of encoded sequence elements

        """
        content_len = 0
        for e in elements:
            content_len += len(e)
        result = [cls._ber_enc_length_definite(content_len)]
        result.extend(elements)
        return b''.join(result)

    @classmethod
    def _ber_enc_sequence(cls, elements):
        """

        :param elements: a list or tuple of encoded sequence elements

        """
        return cls._ber_enc_seq_family(elements)

    def __iter__(self):
        return (v[0] for v in self.__value)

    def __len__(self):
        return len(self.__value)

    def __getitem__(self, pos):
        return self.__value[pos][0]

    def __str__(self):
        return str(self.native())

    def __repr__(self):
        return repr(self.native())


class VASN1SequenceOf(VASN1Sequence):
    """An :term:`ASN.1` Sequence Of.

    :param value:      values to append (or None)
    :type  value:      list, tuple
    :param explicit:   if True set default explicit tagged value encoding
    :type  explicit:   bool
    :param lazy:       if True then lazy-convert values to :class:`VASN1Base`
    :type  lazy:       bool
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    If *value* is not None then sequence elements are added adding
    *value* elements with explicit encoding and no outer tag.

    If *explicit* is True then tagged values by default are explicit,
    otherwise they are by default implicit. This can be used as a
    mechanism to specify tag defaults (as specified by an
    :term:`ASN.1` type's associated module, ref. :term:`X.680`\ ).

    Sequence elements initialized this way are registered as members
    with explicit encoding and no outer tag.

    """

    def __init__(self, value=None, explicit=True, lazy=True,
                 name=None, definition=None):
        if name is None:
            name = 'SEQUENCE OF'
        super(VASN1SequenceOf, self).__init__(value=value, explicit=explicit,
                                              lazy=lazy, name=name,
                                              definition=definition)

    def c_app(self, *args, **kargs):
        """Creates an object and a method for appending as an element.

        :returns:    a function which appends a constructed object
        :rtype:      callable

        This method is a convenience method for creating and adding an
        element which conforms with a derived class of
        :class:`VASN1DefSequenceOf`\ . The following code::

            f = self.c_app(*args, **kargs)(**args2, **kargs2)

        Is equivalent to::

            obj = self.asn1def.asn1def.create(*args, **kargs)
            self.append(obj, *args2, **kargs2)

        .. note::

            This method returns a function, not an object. This is done in
            order to enable separating object creation arguments from
            sequence append arguments.

        """
        obj = self.asn1def.asn1def.create(*args, **kargs)
        app_method = self.append
        def append(*args2, **kargs2):
            app_method(obj, *args2, **kargs2)
            return obj
        return append


class VASN1Set(VASN1Sequence):
    """An :term:`ASN.1` Set.

    :param value:      values to append
    :type  value:      list, tuple, set
    :param explicit:   if True set default explicit tagged value encoding
    :type  explicit:   bool
    :param lazy:       if True then lazy-convert values to :class:`VASN1Base`
    :type  lazy:       bool
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    If *value* is not None then set elements are added by adding
    *value* elements with explicit encoding and no outer tag.

    If *explicit* is True then tagged values by default are explicit,
    otherwise they are by default implicit. This can be used as a
    mechanism to specify tag defaults as specified by an X.680 Module.

    """

    def __init__(self, value=None, explicit=True, lazy=True,
                 name=None, definition=None):
        if name is None:
            name = 'SET'
        super(VASN1Set, self).__init__(value=value, explicit=explicit,
                                       lazy=lazy, name=name,
                                       definition=definition)

    def add(self, *args, **kargs):
        """Convenience method for :meth:`append`\ .

        Same as :meth:`append`\ . This method is added because 'add'
        is the syntax for adding elements associated with python
        native sets.

        """
        return self.append(*args, **kargs)

    # Overloaded to return a set type
    def native(self, deep=True):
        return frozenset(super(VASN1Set, self).native(deep=deep))

    def encode_der(self, with_tag=True):
        seq_der = super(VASN1Set, self).encode_der(with_tag=False)

        # Decomponstruct and reorder sequence elements
        elements, tmp = VASN1DefSequence._ber_dec_sequence(seq_der)
        payload = VASN1Sequence._ber_enc_sequence(sorted(elements))
        if with_tag:
            # X.690: Set always has constructed encoding
            return self.tag.encode_der(constructed=True) + payload
        else:
            return payload

    @classmethod
    def univ_tag(cls):
        """Tag for the associated universal type.

        :returns: tag
        :rtype:   :class:`VASN1Tag`

        """
        return VASN1Tag.from_der(b'\x31')[0][0]

    @classmethod
    def _ber_enc_set(cls, elements):
        """

        :param elements: a list or tuple of encoded sequence elements

        """
        return VASN1Sequence._ber_enc_seq_family(elements)


class VASN1SetOf(VASN1Set):
    """An :term:`ASN.1` Set Of.

    :param value:      values to append (or None)
    :type  value:      list, tuple
    :param explicit:   if True set default explicit tagged value encoding
    :type  explicit:   bool
    :param lazy:       if True then lazy-convert values to :class:`VASN1Base`
    :type  lazy:       bool
    :param name:       :term:`ASN.1` name (or None)
    :type  name:       unicode
    :param definition: type definition (or None)
    :type  definition: :class:`VASN1Definition`

    If *value* is not None then sequence elements are added by adding
    *value* elements with explicit encoding and no outer tag.

    If *explicit* is True then tagged values by default are explicit,
    otherwise they are by default implicit. This can be used as a
    mechanism to specify tag defaults (as specified by an
    :term:`ASN.1` type's associated module, ref. :term:`X.680`\ ).

    """

    def __init__(self, value=None, explicit=True, lazy=True,
                 name=None, definition=None):
        if name is None:
            name = 'SET OF'
        super(VASN1SetOf, self).__init__(value=value, explicit=explicit,
                                         lazy=lazy, name=name,
                                         definition=definition)

    def c_app(self, *args, **kargs):
        """Creates an object and a method for appending as an element.

        :returns:    a function which appends a constructed object
        :rtype:      callable

        This method is a convenience method for creating and adding an
        element which conforms with a derived class of
        :class:`VASN1DefSequenceOf`\ . The following code::

            f = self.c_app(*args, **kargs)(**args2, **kargs2)

        Is equivalent to::

            obj = self.asn1def.asn1def.create(*args, **kargs)
            self.append(obj, *args2, **kargs2)

        .. note::

            This method returns a function, not an object. This is done in
            order to enable separating object creation arguments from
            sequence append arguments.

        """
        obj = self.asn1def.asn1def.create(*args, **kargs)
        app_method = self.add
        def append(*args2, **kargs2):
            app_method(obj, *args2, **kargs2)
            return obj
        return append


class VASN1Tagged(VASN1Base):
    """An :term:`ASN.1` tagged value.

    :param value:      the :term:`ASN.1` value to tag
    :param tag:        the tag to set
    :type  tag:        :class:`VASN1Tag`
    :param explicit:   if True tag as explicit, otherwise implicit (or None)
    :type  explicit:   bool
    :param lazy:       if True lazy-convert value to :class:`VASN1Base`
    :type  lazy:       bool
    :param name:       a name for the ASN.1 type (or None)
    :type  name:       unicode
    :param definition: a definition of the ASN.1 type
    :type  definition: :class:`VASN1Definition`

    If *explicit* is None then the *explicit* property is instead
    derived from the identifier octets of a :term:`DER` encoding of
    the held *value*\ . Otherwise, if True explicit encoding is used,
    and if False then implicit encoding is used.

    """

    def __init__(self, value, tag, explicit, lazy=True, name=None,
                 definition=None):
        super(VASN1Tagged, self).__init__(name=name, definition=definition)
        if lazy:
            value = VASN1Base.lazy(value)
        if explicit is None:
            raise VASN1Exception('\'explicit\' must be True or False')
        self.__value = value
        self.__tag = tag
        self.__explicit = explicit

    def native(self, deep=True):
        return self

    def encode_der(self, with_tag=True):
        val_der = self.__value.encode_der()
        (val_tag, val_constructed), v_len = VASN1Tag.from_der(val_der)

        if self.__explicit:
            # Use explicit encoding, with tag set to 'constructed'
            _enc = VASN1Base._ber_enc_tagged_content
            result = _enc(self.__tag.tag_class, True, self.__tag.tag_number,
                          val_der)
        else:
            # Use implicit encoding, with same tag mode as the held value
            result = self.__tag.encode_der(constructed=val_constructed)
            result += val_der[v_len:]

        if not with_tag:
            # Strip tag from the result
            (res_tag, res_cons), r_len = VASN1Tag.from_der(result)
            result = result[r_len:]
        return result

    @property
    def tag(self):
        return self.__tag

    @property
    def value(self):
        """Value held by the tagged data object."""
        return self.__value

    def __str__(self):
        if _pyver == 2:
            return _b2s(_bfmt(b'%s %s', self.__tag, self.__value))
        else:
            return '%s %s' % (self.__tag, self.__value)

    def __repr__(self):
        if _pyver == 2:
            return _b2s(_bfmt(b'%s %s', repr(self.__tag), repr(self.__value)))
        else:
            return '%s %s' % (repr(self.__tag), repr(self.__value))


class VASN1Unknown(VASN1Base):
    """An :term:`ASN.1` data object of unknown encoding.

    :param data:     :term:`DER` encoded data
    :type  data:     bytes
    :param explicit: if True then the encoded data has explicit encoding
    :type  explicit: bool

    The class is useful for holding an element in an :term:`ASN.1`
    data structure which could not be parsed.

    """
    def __init__(self, data, explicit=True):
        self.__data = data
        self.__explicit = explicit

    @property
    def tag(self):
        return VASN1Tag.from_der(self.__data)[0][0]

    def native(self, deep=True):
        return self

    def encode_der(self, with_tag=True):
        if self.__explicit:
            return self.__data
        else:
            raise VASN1Exception('Explicit encoding not known')


class VASN1Definition(object):
    """Definition of an :term:`ASN.1` data type.

    :param name: definition name (or None)
    :type  name: unicode

    """

    def __init__(self, name=None):
        self.__name = name

    @abstract
    def parse_der(self, data, with_tag=True, lazy=False):
        """Parses :term:`DER` data for this definition and returns value.

        :param data:     :term:`DER` encoded data to parse
        :type  data:     bytes
        :param with_tag: if True :term:`DER` data includes identifier octets
        :type  with_tag: bool
        :param lazy:     if True lazy-convert result to native representation
        :type  lazy:     bool
        :returns:        (parsed_object, bytes_parsed)
        :rtype:          (:class:`VASN1Base`\ , int)

        """
        raise NotImplementedError

    def create(self, *args, **kargs):
        """Creates an appropriate :term:`ASN.1` object for this definition.

        :returns: generated object
        :rtype:   :class:`VASN1Base`

        Provided *args* and *kargs* are passed to the __init__ method
        of the constructed class. If not set on *kargs* (usually they
        should not be set), then keyword arguments are generated and
        passed for the keywords *name* and *definition* referring to
        the definition that :meth:`create` was called on.

        """
        if 'name' in kargs or 'definition' in kargs:
            raise VASN1Exception('Cannot set name or definition in create()')
        kargs['name'] = self.__name
        kargs['definition'] = self
        return self._create(*args, **kargs)

    @abstract
    @property
    def tag(self):
        """:class:`VASN1Tag` for this type definition (or None)."""
        return None

    @property
    def asn1name(self):
        """Type name of this :term:`ASN.1` type"""
        return self.__name

    @abstract
    def _create(self, *args, **kargs):
        """Create an object of appropriate type for this definition.

        Called by :meth:`create`\ . Derived classes can overload this
        method to overload object creation for :meth:`create`\ .

        """
        raise NotImplementedError()

    @classmethod
    def _ber_dec_length(cls, data):
        """

        Returns (definite, length, short, bytes_read)

        """
        if not data:
            raise VASN1Exception('Incomplete data')
        first = _b_ord(data[0])
        if first <= 0x7f:
            return (True, first, True, 1)
        elif first == 0x80:
            return (False, None, None, 1)
        else:
            num_bytes = first & 0x7f
            if len(data) < num_bytes + 1:
                raise VASN1Exception('Incomplete data')
            num_data = data[1:(num_bytes+1)]
            return (True, bytes_to_posint(num_data), False, num_bytes+1)

    @classmethod
    def _ber_dec_content_definite(cls, data, length):
        """

        Returns (content, num_read)

        """
        if len(data) < length:
            raise VASN1Exception('Incomplete data')
        return (data[:length], length)

    @classmethod
    def _ber_dec_content_indefinite(cls, data):
        """

        Returns (content, num_read)

        """
        pos = data.find(b'\x00\x00')
        if pos < 0:
            raise VASN1Exception('No content delimiter')
        return (data[:pos], pos+2)

    @classmethod
    def _ber_dec_tagged_content(cls, data):
        """Create encoding for general tagged content.

        :returns: ((tag_data, content, definite, short), num_read)

        Here tag_data is (tag_class, is_constructed, tag)

        """
        tag_data, tag_len = VASN1Tag._ber_dec_identifier(data)
        definite, length, short, len_read = cls._ber_dec_length(data[tag_len:])
        _data = data[(tag_len+len_read):]
        if definite:
            content, content_len = cls._ber_dec_content_definite(_data, length)
        else:
            content, content_len = cls._ber_dec_content_indefinite(_data)
        tot_read = tag_len + len_read + content_len
        return (tag_data, content, definite, short), tot_read


class VASN1DefUniversal(VASN1Definition):
    """Definition for an undetermined universal type.

    :param allow_unknown: if True also parse unknown types
    :type  allow_unknown: bool
    :param name:          definition name (or None)
    :type  name:          unicode

    This class behaves similarly to a :class:`VASN1DefChoice` which
    allows all the supported universal types. If *allow_unknown* is
    True then unknown types are returned as :class:`VASN1Unknown`\ .

    """

    def __init__(self, allow_unknown=False, name=None):
        self.__allow_unknown=allow_unknown
        self.__name = name

    def parse_der(self, data, with_tag=True, lazy=False):
        if not data:
            raise VASN1Exception('No data')
        tag = data[0]
        if _pyver == 2 and tag == b'\x01' or tag == 0x01:
            asn1def = VASN1DefBoolean(name=self.__name)
        elif _pyver == 2 and tag == b'\x02' or tag == 0x02:
            asn1def = VASN1DefInteger(name=self.__name)
        elif _pyver == 2 and tag == b'\x03' or tag == 0x03:
            asn1def = VASN1DefBitString(name=self.__name)
        elif _pyver == 2 and tag == b'\x04' or tag == 0x04:
            asn1def = VASN1DefOctetString(name=self.__name)
        elif _pyver == 2 and tag == b'\x05' or tag == 0x05:
            asn1def = VASN1DefNull(name=self.__name)
        elif _pyver == 2 and tag == b'\x06' or tag == 0x06:
            asn1def = VASN1DefObjectIdentifier(name=self.__name)
        elif _pyver == 2 and tag == b'\x0a' or tag == 0x0a:
            asn1def = VASN1DefEnumerated(name=self.__name)
        elif _pyver == 2 and tag == b'\x0c' or tag == 0x0c:
            asn1def = VASN1DefUTF8String(name=self.__name)
        elif _pyver == 2 and tag == b'\x12' or tag == 0x12:
            asn1def = VASN1DefNumericString(name=self.__name)
        elif _pyver == 2 and tag == b'\x13' or tag == 0x13:
            asn1def = VASN1DefPrintableString(name=self.__name)
        elif _pyver == 2 and tag == b'\x16' or tag == 0x16:
            asn1def = VASN1DefIA5String(name=self.__name)
        elif _pyver == 2 and tag == b'\x17' or tag == 0x17:
            asn1def = VASN1DefUTCTime(name=self.__name)
        elif _pyver == 2 and tag == b'\x18' or tag == 0x18:
            asn1def = VASN1DefGeneralizedTime(name=self.__name)
        elif _pyver == 2 and tag == b'\x1a' or tag == 0x1a:
            asn1def = VASN1DefVisibleString(name=self.__name)
        elif _pyver == 2 and tag == b'\x1c' or tag == 0x1c:
            asn1def = VASN1DefUniversalString(name=self.__name)
        elif _pyver == 2 and tag == b'\x30' or tag == 0x30:
            # Default parse Sequence as a sequence of universal types
            _allow = self.__allow_unknown
            _uasn1def = VASN1DefUniversal(allow_unknown=_allow)
            asn1def = VASN1DefSequenceOf(_uasn1def, name=self.__name)
        elif _pyver == 2 and tag == b'\x31' or tag == 0x31:
            # Default parse Sequence as a sequence of universal types
            _allow = self.__allow_unknown
            _uasn1def = VASN1DefUniversal(allow_unknown=_allow)
            asn1def = VASN1DefSetOf(_uasn1def, name=self.__name)
        elif self.__allow_unknown:
            asn1def = VASN1DefUnknown()
        else:
            raise VASN1Exception('Not a supported universal type')
        return asn1def.parse_der(data, lazy=lazy)

class VASN1DefUnknown(VASN1Definition):
    """Definition for an unknown type encoding.

    This definition parses data as :class:`VASN1Unknown`\ .

    """
    def parse_der(self, data, with_tag=True, lazy=False):
        if not data:
            raise VASN1Exception('No data')
        return VASN1Unknown(data, explicit=with_tag), len(data)


class VASN1DefNull(VASN1Definition):
    """Definition for the :term:`ASN.1` Null type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x05' or data[0] == 0x05:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_null(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(), num_read

    @property
    def tag(self):
        return VASN1Null.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1Null(*args, **kargs)

    @classmethod
    def _ber_dec_null(cls, data):
        if (len(data) < 1 or _pyver == 2 and data[0] != b'\x00'
            or _pyver == 3 and data[0] != 0):
            raise VASN1Exception('Invalid coding')
        return (None, 1)


class VASN1DefBoolean(VASN1Definition):
    """Definition for the :term:`ASN.1` Boolean type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x01' or data[0] == 0x01:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_boolean(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1Boolean.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1Boolean(*args, **kargs)

    @classmethod
    def _ber_dec_boolean(cls, data):
        if len(data) < 2:
            raise VASN1Exception('Incomplete data')
        if _pyver == 2:
            if data[0] != b'\x01':
                raise VASN1Exception('Invalid data')
            return ((data[1] != b'\x00'), 2)
        else:
            if data[0] != 0x01:
                raise VASN1Exception('Invalid data')
            return ((data[1] != 0x00), 2)


class VASN1DefInteger(VASN1Definition):
    """Definition for the :term:`ASN.1` Integer type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x02' or data[0] == 0x02:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_integer(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1Integer.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1Integer(*args, **kargs)

    @classmethod
    def _ber_dec_int_family(cls, data):
        if not data:
            raise VASN1Exception('Incomplete data')
        definite, length, short, num_bytes = cls._ber_dec_length(data)
        if not definite:
            raise VASN1Exception('Indefinite representation not supported')
        if length < 1:
            raise VASN1Exception('Integer content length must be positive')
        tot_length = num_bytes + length
        if len(data) < tot_length:
            raise VASN1Exception('Incomplete data')
        content = data[num_bytes:tot_length]
        if _b_ord(content[0]) & 0x80:
            return (bytes_to_posint(content)
                    - (1 << (8*len(content))), tot_length)
            pass
        else:
            return (bytes_to_posint(content), tot_length)

    @classmethod
    def _ber_dec_integer(cls, data):
        return cls._ber_dec_int_family(data)


class VASN1DefBitString(VASN1Definition):
    """Definition for the :term:`ASN.1` BitString type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x03' or data[0] == 0x03:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_bitstring(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1BitString.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1BitString(*args, **kargs)

    @classmethod
    def _ber_dec_bitstring(cls, data):
        if not data:
            raise VASN1Exception('Incomplete data')
        definite, length, short, num_bytes = cls._ber_dec_length(data)
        if definite:
            tot_length = num_bytes + length
            content = data[num_bytes:tot_length]
        else:
            content, length = cls._ber_dec_content_indefinite(data[num_bytes:])
            tot_length = num_bytes + length
        if length < 1:
            raise VASN1Exception('Incomplete data')
        elif length == 1:
            if (_pyver == 2 and data[num_bytes] == b'\x00'
                or data[num_bytes] == 0x00):
                return VBitfield(tuple()), tot_length
            else:
                raise VASN1Exception('Invalid encoding')
        else:
            if len(data) < tot_length:
                raise VASN1Exception('Incomplete data')
            pad_len = _b_ord(content[0])
            if pad_len > 7:
                raise VASN1Exception('Invalid encoding')
            bits = b''.join([_s2b(bin(_b_ord(e)))[2:].zfill(8)
                             for e in content[1:]])
            if pad_len:
                bits = bits[:(-pad_len)]
            bits = tuple((_b_ord(b)-ord('0') for b in bits))
            return VBitfield(bits), tot_length


class VASN1DefOctetString(VASN1Definition):
    """Definition for the :term:`ASN.1` OctetString type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x04' or data[0] == 0x04:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_octet_string(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1OctetString.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1OctetString(*args, **kargs)

    @classmethod
    def _ber_dec_family(cls, data):
        if not data:
            raise VASN1Exception('Incomplete data')
        definite, length, short, num_bytes = cls._ber_dec_length(data)
        if not definite:
            raise VASN1Exception('Indefinite length not supported')
        tot_length = num_bytes + length
        if len(data) < tot_length:
            raise VASN1Exception('Incomplete data')
        return data[num_bytes:tot_length], tot_length

    @classmethod
    def _ber_dec_octet_string(cls, data):
        return VASN1DefOctetString._ber_dec_family(data)

class VASN1DefObjectIdentifier(VASN1Definition):
    """Definition for the :term:`ASN.1` ObjectIdentifier type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x06' or data[0] == 0x06:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_object_identifier(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1ObjectIdentifier.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1ObjectIdentifier(*args, **kargs)

    @classmethod
    def _ber_dec_object_identifier(cls, data):
        if not data:
            raise VASN1Exception('Incomplete data')
        definite, length, short, num_bytes = cls._ber_dec_length(data)
        if not definite:
            raise VASN1Exception('Indefinite length not supported')
        tot_length = num_bytes + length
        if len(data) < tot_length:
            raise VASN1Exception('Incomplete data')
        content = data[num_bytes:tot_length]
        oid = []
        buf = []
        if _pyver == 2:
            for octet in (_b_ord(e) for e in content):
                buf.append(_s2b(bin(octet))[2:][-7:].zfill(7))
                if not octet & 0x80:
                    oid.append(int(_b2s(b''.join(buf)), 2)) # from base-2
                    buf = []
        else:
            for octet in content:
                buf.append(_s2b(bin(octet))[2:][-7:].zfill(7))
                if not octet & 0x80:
                    oid.append(int(_b2s(b''.join(buf)), 2)) # from base-2
                    buf = []
        if buf:
            raise VASN1Exception('Incomplete data')
        if len(oid) < 1:
            raise VASN1Exception('OID must have a value')
        oid = [oid[0]//40, oid[0]%40] + oid[1:]
        return VObjectIdentifier(oid), tot_length


class VASN1DefEnumerated(VASN1Definition):
    """Definition for the :term:`ASN.1` Enumerated type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x0a' or data[0] == 0x0a:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = ber_dec_enum(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1Enumerated.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1Enumerated(*args, **kargs)

    @classmethod
    def _ber_dec_enum(cls, data):
        return VASN1DefInteger._ber_dec_int_family(data)


class VASN1DefUTF8String(VASN1Definition):
    """Definition for the :term:`ASN.1` UTF8String type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x0c' or data[0] == 0x0c:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_utf8_string(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1UTF8String.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1UTF8String(*args, **kargs)

    @classmethod
    def _ber_dec_utf8_string(cls, data):
        payload, num_read = VASN1DefOctetString._ber_dec_family(data)
        try:
            if _pyver == 2:
                result = unicode(str(payload), encoding='utf8')
            else:
                result = str(payload, encoding='utf8')
        except Exception as e:
            raise VASN1Exception('Could not parse UTF-8 content')
        else:
            return result, num_read


class VASN1DefNumericString(VASN1Definition):
    """Definition for the :term:`ASN.1` NumericString type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x12' or data[0] == 0x12:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_numeric_string(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1NumericString.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1NumericString(*args, **kargs)

    @classmethod
    def _ber_dec_numeric_string(cls, data):
        payload, num_read = VASN1DefOctetString._ber_dec_family(data)
        for c in payload:
            if c not in b'0123456789 ':
                raise VASN1Exception('Illegal Numeric String character')
        if _pyver == 2:
            return unicode(payload), num_read
        else:
            return str(payload, encoding='utf8'), num_read


class VASN1DefPrintableString(VASN1Definition):
    """Definition for the :term:`ASN.1` PrintableString type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x13' or data[0] == 0x13:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_printable_string(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1PrintableString.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1PrintableString(*args, **kargs)

    @classmethod
    def _ber_dec_printable_string(cls, data):
        payload, num_read = VASN1DefOctetString._ber_dec_family(data)
        for c in payload.lower():
            if c not in b'abcdefghijklmnopqrstuvwxyz0123456789 \'()+,-./:=?':
                raise VASN1Exception('Illegal Printable String character')
        if _pyver == 2:
            return unicode(payload), num_read
        else:
            return str(payload, encoding='utf8'), num_read


class VASN1DefIA5String(VASN1Definition):
    """Definition for the :term:`ASN.1` IA5String type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x16' or data[0] == 0x16:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_ia5string(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1IA5String.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1IA5String(*args, **kargs)

    @classmethod
    def _ber_dec_ia5string(cls, data):
        payload, num_read = VASN1DefOctetString._ber_dec_family(data)
        if max((_b_ord(e) for e in payload)) > 127:
            raise VASN1Exception('Illegal non-ASCII character')
        if _pyver == 2:
            return unicode(payload), num_read
        else:
            return str(payload, encoding='utf8'), num_read


class VASN1DefVisibleString(VASN1Definition):
    """Definition for the :term:`ASN.1` VisibleString type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x1a' or data[0] == 0x1a:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_visiblestring(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1VisibleString.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1VisibleString(*args, **kargs)

    @classmethod
    def _ber_dec_visiblestring(cls, data):
        payload, num_read = VASN1DefOctetString._ber_dec_family(data)
        if (max((_b_ord(e) for e in payload)) > 0x7f
             or min((_b_ord(e) for e in payload)) < 0x20):
            raise VASN1Exception('Illegal non-visible ASCII character')
        if _pyver == 2:
            return unicode(payload), num_read
        else:
            return str(payload, encoding='utf8'), num_read


class VASN1DefUTCTime(VASN1Definition):
    """Definition for the :term:`ASN.1` UTCTime type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x17' or data[0] == 0x17:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_utc_time(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1UTCTime.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1UTCTime(*args, **kargs)

    @classmethod
    def _ber_dec_utc_time(cls, data):
        """

        :type data: bytes
        :rtype:     (:class:`datetime.datetime`, int)

        """
        payload, num_read = VASN1DefOctetString._ber_dec_family(data)
        if not payload:
            raise VASN1Exception('Incomplete data')
        if (_pyver == 2 and payload[-1] != b'Z'
            or _pyver == 3 and payload[-1] != ord('Z')):
            raise VASN1Exception('Invalid data')
        payload = payload[:-1]
        try:
            tdata = time.strptime(_b2s(payload), _b2s(b'%y%m%d%H%M%S'))[:6]
            value = datetime.datetime(*tdata)
        except Exception as e:
            raise VASN1Exception('Could not parse date/time information')
        return value, num_read

class VASN1DefGeneralizedTime(VASN1Definition):
    """Definition for the :term:`ASN.1` GeneralizedTime type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x18' or data[0] == 0x18:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_generalized_time(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1GeneralizedTime.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1GeneralizedTime(*args, **kargs)

    @classmethod
    def _ber_dec_generalized_time(cls, data):
        """

        :type data: bytes
        :rtype:     (:class:`datetime.datetime`, int)

        """
        payload, num_read = VASN1DefOctetString._ber_dec_family(data)
        if not payload:
            raise VASN1Exception('Incomplete data')
        if (_pyver == 2 and payload[-1] != b'Z'
            or _pyver == 3 and payload[-1] != ord('Z')):
            raise VASN1Exception('Invalid data')
        components = payload[:-1].split(b'.')
        if len(components) not in (1, 2):
            raise VASN1Exception('Incomplete or invalid data')
        try:
            tdata = time.strptime(_b2s(components[0]), '%Y%m%d%H%M%S')[:6]
            value = datetime.datetime(*tdata)
        except:
            raise VASN1Exception('Could not parse date/time information')
        if len(components) == 2:
            micro = components[1]
            len_micro = len(micro)
            if len_micro > 6:
                raise VASN1Exception('Sub-microsec resolution not supported')
            try:
                micro = int(micro)
            except:
                raise VASN1Exception('Could not parse fractional seconds')
            micro *= 10**(6-len_micro)
            value = value.replace(microsecond=micro)
        return value, num_read


class VASN1DefUniversalString(VASN1Definition):
    """Definition for the :term:`ASN.1` UniversalString type."""

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x1c' or data[0] == 0x1c:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        val, num_read = self._ber_dec_universal_string(data)
        if with_tag:
            num_read += 1
        if lazy:
            return val, num_read
        else:
            return self.create(val), num_read

    @property
    def tag(self):
        return VASN1UniversalString.univ_tag()

    def _create(self, *args, **kargs):
        return VASN1UniversalString(*args, **kargs)

    @classmethod
    def _ber_dec_universal_string(cls, data):
        payload, num_read = VASN1DefOctetString._ber_dec_family(data)
        try:
            if _pyver == 2:
                result = unicode(_b2s(payload), encoding='utf-32')
            else:
                result = str(payload, encoding='utf-32')
        except Exception as e:
            raise VASN1Exception('Could not parse UTF-32 content')
        else:
            return result, num_read


class VASN1DefSequenceOf(VASN1Definition):
    """Definition for the :term:`ASN.1` Sequence Of type.

    :param asn1def: asn1def for sequence elements
    :type  asn1def: :class:`VASN1Definition`
    :param name:    name for this data type (or None)
    :type  name:    unicode

    """
    def __init__(self, asn1def, name=None):
        super(VASN1DefSequenceOf, self).__init__(name=name)
        self.__asn1def = asn1def

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x30' or data[0] == 0x30:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        elements, num_read = VASN1DefSequence._ber_dec_sequence(data)
        result = self.create()
        for item in elements:
            item, item_len = self.__asn1def.parse_der(item)
            result.append(item)
        if lazy:
            result = result.native(deep=True)
        if with_tag:
            num_read += 1
        return result, num_read

    @property
    def tag(self):
        return VASN1Sequence.univ_tag()

    @property
    def asn1def(self):
        """The :class:`VASN1Definition` for sequence elements."""
        return self.__asn1def

    def _create(self, *args, **kargs):
        return VASN1SequenceOf(*args, **kargs)


class VASN1DefSequence(VASN1Definition):
    """Definition for the :term:`ASN.1` Sequence type.

    :param explicit: if True default use explicit tagged value encoding
    :type  explicit: bool
    :param name:     name for this data type (or None)
    :type  name:     unicode

    If *explicit* is True then tagged values by default are explicit,
    otherwise they are by default implicit. This can be used as a
    mechanism to specify tag defaults as specified by an X.680 Module.

    The class overloads getattr so any non-defined attribute is
    handled as a lookup to :meth:`named_def` for a registered element
    definition of the associated name.

    """
    def __init__(self, explicit=True, name=None):
        super(VASN1DefSequence, self).__init__(name=name)
        self.__items = []
        self.__names = dict()       # name -> asn1def
        self.__explicit = explicit

    def __getattr__(self, attr):
        result = self.__names.get(attr, None)
        if result is not None:
            return result
        else:
            raise AttributeError()

    def add(self, asn1def, name=None, opt=False, default=None):
        """Adds a sequence element definition.

        :param asn1def:   a asn1def for the element
        :type  asn1def:   :class:`VASN1Definition`
        :param name:      name reference for the element, or None
        :type  name:      unicode
        :param opt:       if True, the element is optional
        :type  opt:       bool
        :param default:   default value for the element, or None
        :type  default:   :class:`VASN1Base`

        """
        if name and name in self.__names:
            raise VASN1Exception('Name already in user')
        self.__items.append((asn1def, name, opt, default))
        self.__names[name] = asn1def

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x30' or data[0] == 0x30:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        elements, num_read = self._ber_dec_sequence(data)
        result = self.create()
        items = iter(elements)
        item = None
        for asn1def, name, opt, default in self.__items:
            try:
                if not item:
                    item = next(items)
            except StopIteration:
                if default:
                    result.append(VASN1Base.lazy(default), name=name,
                                  is_default=True)
                    continue
                elif not opt:
                    raise VASN1Exception('Required element missing')
            else:
                (_tag, _constructed), tmp = VASN1Tag.from_der(item)
                if asn1def.tag and asn1def.tag != _tag:
                    # Handle non-matching tags
                    if default is not None:
                        result.append(VASN1Base.lazy(default), name=name,
                                      is_default=True)
                        continue
                    elif opt:
                        continue
                    else:
                        raise VASN1Exception('Required element missing')
                item, item_len = asn1def.parse_der(item)
                result.append(item, name=name)
                item = None
        try:
            next(items)
        except StopIteration:
            pass
        else:
            raise VASN1Exception('Unprocessed sequence elements')

        if lazy:
            result = result.native(deep=True)
        if with_tag:
            num_read += 1
        return result, num_read

    def ctx_tag_def(self, tag_number, value_def, explicit=None):
        """Creates an returns a tagged value or context-specific tag.

        :param tag_number: context-specific tag's tag number
        :type  tag_number: int
        :param value_def:  definition for the tag's value
        :type  value_def:  :class:`VASN1Definition`
        :param explicit:   if True use explicit tagging, otherwise implicit
        :type  explicit:   bool, None
        :returns:          tagged value definition
        :rtype:            :class:`VASN1DefTagged`

        If *explicit* is None then the explicit encoding property of
        the containing sequence if used.

        """
        tag = VASN1Tag.ctx(tag_number)
        if explicit is None:
            explicit = self.__explicit
        return VASN1DefTagged(tag=tag, asn1def=value_def, explicit=explicit)

    def named_def(self, name):
        """Returns the definition registered with the given name.

        :param name: name the definition was registered with
        :type  name: unicode
        :returns:    associated definition
        :rtype:      :class:`VASN1Definition`
        :raises:     :exc:`VASN1Exception`

        """
        asn1def = self.__names.get(name, None)
        if asn1def is not None:
            return asn1def
        else:
            raise VASN1Exception('No definition registered for the given name')

    @property
    def tag(self):
        return VASN1Sequence.univ_tag()

    @property
    def names(self):
        """A set of names for registered named definitions."""
        return frozenset(self.__names.keys())

    def _create(self, *args, **kargs):
        if 'explicit' not in kargs:
            kargs['explicit'] = self.__explicit
        return VASN1Sequence(*args, **kargs)

    @classmethod
    def _ber_dec_seq_family(cls, data):
        """

        Returns (tuple(encoded_elements), num_read)

        """
        if not data:
            raise VASN1Exception('Incomplete data')
        definite, length, short, num_bytes = cls._ber_dec_length(data)
        if not definite:
            raise VASN1Exception('Indefinite length not supported')
        tot_length = num_bytes + length
        if len(data) < tot_length:
            raise VASN1Exception('Incomplete data')
        content = data[num_bytes:tot_length]

        # Parse content, splitting up into separate encoded elements
        result = []
        while content:
            tag_data, tag_bytes_read = VASN1Tag._ber_dec_identifier(content)
            _tuple = cls._ber_dec_length(content[tag_bytes_read:])
            definite, length, sh, l_read = _tuple
            if not definite:
                start_pos = tag_bytes_read + l_read
                _tuple = cls._ber_dec_content_indefinite(content[start_pos:])
                _content, length = _tuple
            _length = tag_bytes_read + l_read + length
            if len(content) < _length:
                raise VASN1Exception('Incomplete data')
            result.append(content[:_length])
            content = content[_length:]

        return (tuple(result), tot_length)


    @classmethod
    def _ber_dec_sequence(cls, data):
        """

        Returns (encoded_payload, num_read)

        """
        return cls._ber_dec_seq_family(data)


class VASN1DefSetOf(VASN1Definition):
    """Definition for the :term:`ASN.1` Set Of type.

    :param asn1def: asn1def for set elements
    :type  asn1def: :class:`VASN1Definition`
    :param name:    name for this data type (or None)
    :type  name:    unicode

    """
    def __init__(self, asn1def, name=None):
        super(VASN1DefSetOf, self).__init__(name=name)
        self.__asn1def = asn1def

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x31' or data[0] == 0x31:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        elements, num_read = VASN1DefSequence._ber_dec_sequence(data)
        result = self.create()
        for item in elements:
            item, item_len = self.__asn1def.parse_der(item)
            result.append(item)
        if lazy:
            result = result.native(deep=True)
        if with_tag:
            num_read += 1
        return result, num_read

    @property
    def tag(self):
        return VASN1Set.univ_tag()

    @property
    def asn1def(self):
        """The :class:`VASN1Definition` for set elements."""
        return self.__asn1def

    def _create(self, *args, **kargs):
        return VASN1SetOf(*args, **kargs)


class VASN1DefSet(VASN1Definition):
    """Definition for the :term:`ASN.1` Set type.

    :param explicit: if True default use explicit tagged value encoding
    :type  explicit: bool
    :param name:     name for this data type (or None)
    :type  name:     unicode

    If *explicit* is True then tagged values by default are explicit,
    otherwise they are by default implicit. This can be used as a
    mechanism to specify tag defaults as specified by an X.680 Module.

    """
    def __init__(self, explicit=True, name=None):
        super(VASN1DefSet, self).__init__(name=name)
        self.__items = dict()
        self.__names = dict()       # name -> asn1def
        self.__explicit = explicit

    def add(self, asn1def, name=None, opt=False, default=None):
        """Adds a set element definition.

        :param asn1def:   a asn1def for the element
        :type  asn1def:   :class:`VASN1Definition`
        :param name:      name reference for the element, or None
        :type  name:      unicode
        :param opt:       if True, the element is optional
        :type  opt:       bool
        :param default:   default value for the element, or None
        :type  default:   :class:`VASN1Base`

        """
        if name and name in self.__names:
            raise VASN1Exception('Name already in user')
        _tag = asn1def.tag
        if not _tag:
            raise VASN1Exception('Set definitions must have a tag')
        self.__items[_tag] = (asn1def, name, opt, default)
        self.__names[name] = asn1def

    def parse_der(self, data, with_tag=True, lazy=False):
        if with_tag:
            if _pyver == 2 and data[0] == b'\x31' or data[0] == 0x31:
                data = data[1:]
            else:
                raise VASN1Exception('Explicit tag mismatch')
        elements, num_read = self._ber_dec_set(data)
        result = self.create()
        dec_tags = set()  # Track tags that have been decoded
        for item in elements:
            (_tag, _constructed), _tmp = VASN1Tag.from_der(item)
            p_data = self.__items.get(_tag, None)
            if not p_data:
                raise VASN1Exception('Invalid tag for the Set')
            asn1def, name, opt, default = p_data
            dec_tags.add(_tag)

            item, item_len = asn1def.parse_der(item)
            result.add(item, name=name)

        # Fill in default values and validate no required elements missing
        for tag, val in self.__items.items():
            if tag not in dec_tags:
                asn1def, name, opt, default = val
                if default:
                    result.add(VASN1Base.lazy(default), name=name,
                               is_default=True)
                elif not opt:
                    raise VASN1Exception('Set missing required components')

        if lazy:
            result = result.native(deep=True)
        if with_tag:
            num_read += 1
        return result, num_read

    def ctx_tag_def(self, tag_number, value_def, explicit=None):
        """Creates an returns a tagged value or context-specific tag.

        :param tag_number: context-specific tag's tag number
        :type  tag_number: int
        :param value_def:  definition for the tag's value
        :type  value_def:  :class:`VASN1Definition`
        :param explicit:   if True use explicit tagging, otherwise implicit
        :type  explicit:   bool, None
        :returns:          tagged value definition
        :rtype:            :class:`VASN1DefTagged`

        If *explicit* is None then the explicit encoding property of
        the containing sequence if used.

        """
        tag = VASN1Tag.ctx(tag_number)
        if explicit is None:
            explicit = self.__explicit
        return VASN1DefTagged(tag=tag, asn1def=value_def, explicit=explicit)

    def named_def(self, name):
        """Returns the definition registered with the given name.

        :param name: name the definition was registered with
        :type  name: unicode
        :returns:    associated definition
        :rtype:      :class:`VASN1Definition`
        :raises:     :exc:`VASN1Exception`

        """
        asn1def = self.__names.get(name, None)
        if asn1def is not None:
            return asn1def
        else:
            raise VASN1Exception('No definition registered for the given name')

    @property
    def tag(self):
        return VASN1Sequence.univ_tag()

    def _create(self, *args, **kargs):
        if 'explicit' not in kargs:
            kargs['explicit'] = self.__explicit
        return VASN1Set(*args, **kargs)

    @classmethod
    def _ber_dec_set(cls, data):
        """

        Returns (encoded_payload, num_read)

        """
        return VASN1DefSequence._ber_dec_seq_family(data)


class VASN1DefChoice(VASN1Definition):
    """Definition for the :term:`ASN.1` Choice element.

    :param name:     definition name (or None)
    :type  name:     unicode
    :param explicit: if True use explicit encoding as default
    :type  explicit: bool

    """

    def __init__(self, name=None, explicit=True):
        super(VASN1DefChoice, self).__init__(name=name)
        self.__asn1defs = dict()
        self.__named = dict()    # name -> asn1def
        self.__explicit = explicit

    def add(self, asn1def, name=None):
        """Adds a choice definition.

        :param asn1def:  asn1def for the tag
        :type  asn1def:  :class:`VASN1Definition`
        :param name:     name associated with Choice element, or None
        :type  name:     unicode
        :raises:         :exc:`VASN1Exception`

        If a tag cannot be extracted from *asn1def* or there is
        already a definition registered which uses the same tag, an
        exception is raised.

        """
        tag = asn1def.tag
        if not tag:
            raise VASN1Exception('Tag required')
        if tag in self.__asn1defs:
            raise VASN1Exception('Tag already registered')
        if name in self.__named:
            raise VASN1Exception('Name already in use')
        self.__asn1defs[tag] = asn1def
        if name is not None:
            self.__named[name] = asn1def

    def parse_der(self, data, with_tag=True, lazy=False):
        if not with_tag:
            raise VASN1Exception('Choice cannot parse from implicit')
        (tag, constructed), tmp = VASN1Tag.from_der(data)
        asn1def = self.__asn1defs.get(tag, None)
        if asn1def:
            return asn1def.parse_der(data, with_tag, lazy)
        else:
            raise VASN1Exception('\'Choice\' tag not recognized')

    def ctx_tag_def(self, tag_number, value_def, explicit=None):
        """Creates an returns a tagged value or context-specific tag.

        :param tag_number: context-specific tag's tag number
        :type  tag_number: int
        :param value_def:  definition for the tag's value
        :type  value_def:  :class:`VASN1Definition`
        :param explicit:   if True use explicit tagging, otherwise implicit
        :type  explicit:   bool, None
        :returns:          tagged value definition
        :rtype:            :class:`VASN1DefTagged`

        If *explicit* is None then the explicit encoding property of
        the containing sequence if used.

        """
        tag = VASN1Tag.ctx(tag_number)
        if explicit is None:
            explicit = self.__explicit
        return VASN1DefTagged(tag=tag, asn1def=value_def, explicit=explicit)

    def named_def(self, name):
        """Returns the definition registered with the given name.

        :param name: name the definition was registered with
        :type  name: unicode
        :returns:    associated definition
        :rtype:      :class:`VASN1Definition`
        :raises:     :exc:`VASN1Exception`

        """
        asn1def = self.__names.get(name, None)
        if asn1def is not None:
            return asn1def
        else:
            raise VASN1Exception('No definition registered for the given name')


class VASN1DefTagged(VASN1Definition):
    """Definition for an :term:`ASN.1` tagged data element.

    :param tag:      the associated tag
    :type  tag:      :class:`VASN1Tag`
    :param asn1def:  definition for the embedded value
    :type  asn1def:  :class:`VASN1Definition`
    :param explicit: default *explicit* argument used for :meth:`create`
    :type  explicit: bool
    :param name:     definition name (or None)
    :type  name:     unicode

    """

    def __init__(self, tag, asn1def, explicit, name=None):
        super(VASN1DefTagged, self).__init__(name=name)
        if explicit is None:
            raise VASN1Exception('\'explicit\' must be True or False')
        self.__tag = tag
        self.__asn1def = asn1def
        self.__explicit = explicit

    def parse_der(self, data, with_tag=True, lazy=False):
        if not with_tag:
            raise VASN1Exception('VASN1DefTagged can only parse with_tag')

        if with_tag:
            dec = self._ber_dec_tagged_content
            (_td, content, _def, _sh), num_read = dec(data)
            tag, constructed = VASN1Tag(_td[0], _td[2]), _td[1]
            if tag != self.__tag:
                raise VASN1Exception('Tag mismatch')
            _tmp, tag_len = VASN1Tag.from_der(data)
        else:
            (_def, _len, _sh, _l_read) = self._ber_dec_length(data)
            if _def:
                _c_dec = self._ber_dec_content_definite
            else:
                _c_dec = self._ber_dec_content_indefinite
            _c_len, content = _c_dec(data[_l_read:])
            num_read = _l_read + _c_len
            tag_len = 0

        # Below decoding does not validate 'constructed vs primitive'
        # encoding requirement, ref. X.690 section 8.14
        if self.__explicit:
            result, p_read = self.__asn1def.parse_der(content,
                                                     with_tag=with_tag,
                                                     lazy=lazy)
            if p_read != len(content):
                raise VASN1Exception('Illegal encoding')
        else:
            _p = self.__asn1def.parse_der
            result, p_read = _p(data[tag_len:], with_tag=False, lazy=lazy)
            if p_read + tag_len != num_read:
                raise VASN1Exception('Illegal encoding')

        result = self.create(result, explicit=self.__explicit)
        return result, num_read

    @property
    def tag(self):
        return self.__tag

    @property
    def explicit(self):
        """True if *explicit* was set, otherwise False."""
        return self.__explicit

    def _create(self, *args, **kargs):
        if 'value' not in kargs and not args:
            # If no value provided, create a default
            kargs['value'] = self.__asn1def.create()
        if 'tag' not in kargs:
            kargs['tag'] = self.__tag
        if 'explicit' not in kargs:
            kargs['explicit'] = self.__explicit
        return VASN1Tagged(*args, **kargs)
