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

"""Implements :term:`VSE` containers.

Importing registers :class:`VContainerModule` as a global module.

"""
from __future__ import print_function, unicode_literals

import struct

from versile.internal import _vexport, _b2s, _s2b, _pyver
from versile.common.iface import abstract
from versile.common.util import VLockable, signedint_to_netbytes
from versile.common.util import netbytes_to_signedint
from versile.orb.entity import VEntity, VTagged, VTaggedParseError, VTuple
from versile.orb.entity import VBytes, VFloat
from versile.orb.module import VModuleResolver, VModule, VModuleConverter
from versile.orb.module import VERBase
from versile.vse.const import VSECodes, VSEModuleCodes

__all__ = ['VFrozenDict', 'VFrozenSet', 'VMultiArray',
           'VFrozenMultiArray', 'VArrayOfInt', 'VArrayOfLong',
           'VArrayOfVInteger', 'VArrayOfFloat', 'VArrayOfDouble',
           'VArrayOfVFloat', 'VContainerModule']
__all__ = _vexport(__all__)


class VFrozenDict(VERBase, VEntity, VLockable):
    """A dictionary of key-value pairs.

    :param value: dictionary to set up on
    :type  value: dict

    Internal dictionary is a shallow copy of *value*. Dictionary keys
    and values must be :class:`versile.orb.entity.VEntity`\ . If any
    keys or values in *value* are not of the correct type,
    lazy-conversion is attempted.

    .. automethod:: __getitem__
    .. automethod:: __iter__
    .. automethod:: __len__

    """

    def __init__(self, value):
        VLockable.__init__(self)
        self.__value = dict()
        lazy = VEntity._v_lazy
        for key, val in value.items():
            self.__value[lazy(key)] = lazy(val)

    def keys(self):
        """Similar to :meth:`dict.keys`\ ."""
        return tuple(iter(self))

    def values(self):
        """Similar to :meth:`dict.values`\ ."""
        return tuple(iter(self.__values.values()))

    def items(self):
        """Similar to :meth:`dict.items`\ ."""
        return tuple((key, val) for key, val in self.__value.items())

    def _v_as_tagged(self, context):
        tags = VSECodes.DICTIONARY.tags(context)
        data = []
        with self:
            for key, value in self.__value.items():
                data.append(key)
                data.append(value)
            data = tuple(data)
        return VTagged(data, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Returns decoder for :class:`versile.orb.entity.VTagged`."""
        if tags:
            raise VTaggedParseError('Encoding does not use residual tags')
        if not isinstance(value, VTuple):
            raise VTaggedParseError('Encoding value must be a tuple')
        l = len(value)
        if l % 2:
            raise VTaggedParseError('Value length must be an even number')

        def _assemble(args):
            keys, values = value[0:l:2], value[1:l:2]
            data = dict()
            for key, val in zip(keys, values):
                if key in data:
                    raise VTaggedParseError('Duplicate keys')
                data[key] = val
            try:
                return cls(data)
            except:
                raise VTaggedParseError('Error initializing dictionary')

        return(_assemble, list(value))

    def __getitem__(self, key):
        """Gets a dictionary value.

        :param key: dictionary key
        :type  key: :class:`versile.orb.entity.VEntity` or lazy-convertible
        :returns:   dictionary value for key
        :rtype:     :class:`versile.orb.entity.VEntity`
        :raises:    :exc:`exceptions.KeyError`

        """
        with self:
            key = VEntity._v_lazy(key)
            return self.__value[key]

    def __iter__(self):
        """Similar to :meth:`dict.__iter__`\ ."""
        return iter(self.__value)

    def __len__(self):
        """Similar to :meth:`dict.__len__`\ ."""
        return len(self.__value)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VFrozenSet(VERBase, VEntity):
    """A set of entities.

    :param values: set values
    :type  value:  set or iterable
    :param parser: parser for lazy-conversion (or None)
    :type  parser: :class:`versile.orb.entity.VTaggedParser`

    Creates an internal shallow copy of provided elements. Elements
    must be :class:`versile.orb.entity.VEntity` or lazy-convertible

    The set is immutable, similar to :class:`frozenset`\ , and
    lazy-converts to that type as its native value.

    .. automethod:: __iter__

    """

    def __init__(self, value, parser=None):
        if isinstance(value, VTuple):
            self.__value = frozenset(value)
        else:
            lazy = VEntity._v_lazy
            self.__value = frozenset(lazy(e, parser) for e in value)

    def _v_as_tagged(self, context):
        tags = VSECodes.SET.tags(context)
        value = tuple(self.__value)
        return VTagged(value, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding does not use residual tags')
        if not isinstance(value, VTuple):
            raise VTaggedParseError('Encoding value must be a tuple')
        return (cls, list(value))

    @classmethod
    def _v_converter(cls, obj):
        return (cls, list(iter(obj)))

    def _v_native_converter(self):
        return (frozenset, list(self.__value))

    def __iter__(self):
        """An iterator over the set's elements"""
        return iter(self.__value)

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return repr(self.__value)


class VMultiArray(VLockable):
    """An N-dimensional array of :class:`versile.orb.entity.VEntity`\ .

    :param dim:  array dimensions
    :type  dim:  (int,)
    :param data: array data (or None)
    :type  data: tuple, list, iterator, :class:`versile.orb.entity.VTuple`
    :param fill: default array element value if *data* is None
    :param lazy: if True lazy-convert elements to VEntity
    :type  lazy: bool

    Array elements must be :class:`versile.orb.entity.VEntity`\ . If
    any elements are not of the correct type, lazy-conversion is
    attempted.

    If *data* is provided, it must be a 1-dimensional list with the
    same sequencing as the object's :term:`VER` encoding.

    .. note::

        This class does *not* have a :term:`VER` representation and is
        not itself a :class:`versile.orb.entity.VEntity`\ . However,
        it can be converted to a :term:`VER`\ -enabled class by
        calling :meth:`frozen`\ .

    .. automethod:: __getitem__
    .. automethod:: __setitem__

    """
    def __init__(self, dim, data=None, fill=None, lazy=True):
        VLockable.__init__(self)
        if len(dim) < 1:
            raise TypeError('Minimum 1 dimension required')
        for d in dim:
            if d <= 0:
                raise TypeError('Each dimension must be >0')
        self._dim = tuple(dim)
        mul, m = [], 1
        for d in dim:
            mul.append(m)
            m *= d
        _len = m
        self.__mul = tuple(mul)
        if data is None:
            fill = VEntity._v_lazy(fill)
            self._data = [fill]*(_len)
        else:
            if isinstance(data, VTuple):
                self._data = list(e for e in data)
            else:
                if lazy:
                    _lazy = VEntity._v_lazy
                    self._data = self._val_type()(_lazy(e) for e in data)
                else:
                    self._data = self._val_type()(iter(data))
                    for e in self._data:
                        if not isinstance(e, VEntity):
                            raise TypeError('Invalid element type')
            if len(self._data) != _len:
                raise TypeError('Data has incorrect dimensions')

    def frozen(self):
        """Return a frozen version of this array.

        :returns: frozen array
        :rtype:   :class:`VFrozenMultiArray`

        """
        with self:
            return VFrozenMultiArray(self.dim, data=self._data, lazy=False)

    @property
    def dim(self):
        """Array dimensions ((int,))"""
        return self._dim

    @property
    def data(self):
        """Array values as a linear tuple (tuple)."""
        with self:
            return tuple(self._data)

    @classmethod
    def _val_type(cls):
        return list

    @classmethod
    def _str_prefix(cls):
        if _pyver == 2:
            return b'VMultiArray['
        else:
            return 'VMultiArray['

    def __getitem__(self, index):
        """Gets an element of the array.

        :param index: array index
        :type  index: (int,)
        :returns:     array value at index
        :raises:      :exc:`exceptions.IndexError`

        """
        with self:
            if len(index) != len(self._dim):
                raise IndexError('Index has incorrect length')
            for i, d in zip(index, self._dim):
                if not 0 <= i < d:
                    raise IndexError('Index out of range')
            pos = 0
            for i, m in zip(index, self.__mul):
                pos += i*m
            return self._data[pos]

    def __setitem__(self, index, value):
        """Sets an element of the array.

        :param index: array index
        :type  index: (int,)
        :param value: element value
        :type  value: :class:`versile.orb.entity.VEntity` or lazy-convertible
        :raises:      :exc:`exceptions.TypeError`\ ,
                      :exc:`exceptions.IndexError`

        """
        with self:
            if len(index) != len(self._dim):
                raise IndexError('Index has incorrect length')
            for i, d in zip(index, self._dim):
                if not 0 <= i < d:
                    raise IndexError('Index out of range')
            if not isinstance(value, VEntity):
                value = VEntity._v_lazy(value)
            pos = 0
            for i, m in zip(index, self.__mul):
                pos += i*m
            self._data[pos] = value

    def __fmt(self, fmt):
        with self:
            result = [self._str_prefix()]
            index = [0]*len(self._dim)
            first = True
            while True:
                if not first:
                    if _pyver == 2:
                        result.append(b', ')
                    else:
                        result.append(', ')
                first = False
                if _pyver == 2:
                    result.append(b'%s: %s' % (tuple(index), fmt(self[index])))
                else:
                    result.append('%s: %s' % (tuple(index), fmt(self[index])))
                for i in xrange(len(index)):
                    index[i] += 1
                    if index[i] < self._dim[i]:
                        break
                    else:
                        index[i] = 0
                else:
                    break
            if _pyver == 2:
                result.append(b']')
            else:
                result.append(']')
        if _pyver == 2:
            return(_b2s(b''.join(result)))
        else:
            return ''.join(result)

    def __str__(self):
        return self.__fmt(lambda x: str(x))

    def __repr__(self):
        return self.__fmt(lambda x: repr(x))


class VFrozenMultiArray(VERBase, VEntity, VMultiArray):
    """An N-dimensional array of :class:`versile.orb.entity.VEntity`\ .

    See :class:`VMultiArray` for arguments.

    This class is a :class:`versile.orb.entity.VEntity` and has a
    :term:`VER` encoded representation.

    The array is 'frozen' and immutable in the sense that elements
    cannot be replaced. However, the elements themselves do not have
    to be immutable.

    .. automethod:: __setitem__

    """
    def __init__(self, dim, data=None, fill=None, lazy=True):
        VEntity.__init__(self)
        VMultiArray.__init__(self, dim, data, fill, lazy)

    @classmethod
    def _val_type(cls):
        return tuple

    def _v_as_tagged(self, context):
        tags = VSECodes.MULTI_ARRAY.tags(context) + self._dim
        with self:
            tag_obj = VTagged(tuple(self._data), *tags)
        return tag_obj

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        dim = VEntity._v_lazy_native(tags)
        data = value
        _assemble = lambda args: cls(dim, data=args)
        return (_assemble, list(data))

    def __setitem__(self, index, value):
        """Raises an exception (setting items not allowed on frozen array)."""
        raise NotImplementedError()

    @classmethod
    def _str_prefix(cls):
        if _pyver == 2:
            return b'VFrozenMultiArray['
        else:
            return 'VFrozenMultiArray['


@abstract
class VArrayOf(VERBase, VEntity):
    """Abstract base class for arrays of typed data.

    :param values: array values
    :type  value:  iterable

    Creates an internal shallow copy of provided elements.

    .. automethod:: __iter__
    .. automethod:: __len__
    .. automethod:: __getitem__

    """

    def __init__(self, value):
        self._array = tuple(value)

    def __iter__(self):
        """An iterator over the set's elements"""
        return iter(self._array)

    def __len__(self):
        return len(self._array)

    def __getitem__(self, index):
        return self._array[index]

    def __str__(self):
        return str(self._array)

    def __repr__(self):
        return repr(self._array)


class VArrayOfInt(VArrayOf):
    """Base class for array of typed int32 data.

    :param values: array values
    :type  value:  iterable
    :raises:       :exc:`exceptions.TypeError`

    Creates an internal shallow copy of provided elements. Raises an
    exception if any of the provided elements are not an integer in
    range.

    .. automethod:: __iter__

    """

    def __init__(self, value):
        value = tuple(value)
        for _v in value:
            if _pyver == 2:
                if not isinstance(_v, (int, long)):
                    raise TypeError('All elements must be int')
            else:
                if not isinstance(_v, int):
                    raise TypeError('All elements must be int')
            if _v < -0x80000000 or _v > 0x7fffffff:
                raise TypeError('All elements must have an int32 value')
        super(VArrayOfInt, self).__init__(value)

    def _v_as_tagged(self, context):
        tags = VSECodes.ARRAY_OF_INT.tags(context)
        _chunks = []
        for _val in self._array:
            _chunks.append(struct.pack(b'>l', _val))
        value = VBytes(b''.join(_chunks))
        return VTagged(value, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding does not use residual tags')
        value = VEntity._v_lazy_native(value)
        if not isinstance(value, bytes):
            raise VTaggedParseError('Encoding value must be bytes data')

        if len(value) % 4 != 0:
            raise VTaggedParseError('Encoding must be multiple of 4 bytes')
        _nums = []
        _offset = 0
        while _offset < len(value):
            _nums.append(struct.unpack_from(b'>l', value, _offset)[0])
            _offset += 4
        result = VArrayOfInt(_nums)
        return (lambda x: x[0], [result])

    def _v_native_converter(self):
        return (lambda x: x[0], [self._array])


class VArrayOfLong(VArrayOf):
    """Base class for array of typed int64 data.

    :param values: array values
    :type  value:  iterable
    :raises:       :exc:`exceptions.TypeError`

    Creates an internal shallow copy of provided elements. Raises an
    exception if any of the provided elements are not an integer (or
    long) in range.

    .. automethod:: __iter__

    """

    def __init__(self, value):
        value = tuple(value)
        for _v in value:
            if _pyver == 2:
                if not isinstance(_v, (int, long)):
                    raise TypeError('All elements must be int')
            else:
                if not isinstance(_v, int):
                    raise TypeError('All elements must be int')
            if _v < -0x8000000000000000 or _v > 0x7fffffffffffffff:
                raise TypeError('All elements must have an int64 value')
        super(VArrayOfLong, self).__init__(value)

    def _v_as_tagged(self, context):
        tags = VSECodes.ARRAY_OF_LONG.tags(context)
        _chunks = []
        for _val in self._array:
            _chunks.append(struct.pack(b'>q', _val))
        value = VBytes(b''.join(_chunks))
        return VTagged(value, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding does not use residual tags')
        value = VEntity._v_lazy_native(value)
        if not isinstance(value, bytes):
            raise VTaggedParseError('Encoding value must be bytes data')

        if len(value) % 8 != 0:
            raise VTaggedParseError('Encoding must be multiple of 8 bytes')
        _nums = []
        _offset = 0
        while _offset < len(value):
            _nums.append(struct.unpack_from(b'>q', value, _offset)[0])
            _offset += 8
        result = VArrayOfLong(_nums)
        return (lambda x: x[0], [result])

    def _v_native_converter(self):
        return (lambda x: x[0], [self._array])


class VArrayOfVInteger(VArrayOf):
    """Base class for array of typed VInteger data.

    :param values: array values (python integer type)
    :type  value:  iterable
    :raises:       :exc:`exceptions.TypeError`

    Creates an internal shallow copy of provided elements. Raises an
    exception if any of the provided elements are not an integer (or
    long) in range.

    .. automethod:: __iter__

    """

    def __init__(self, value):
        value = tuple(value)
        for _v in value:
            if _pyver == 2:
                if not isinstance(_v, (int, long)):
                    raise TypeError('All elements must be int')
            else:
                if not isinstance(_v, int):
                    raise TypeError('All elements must be int')
        super(VArrayOfVInteger, self).__init__(value)

    def _v_as_tagged(self, context):
        tags = VSECodes.ARRAY_OF_VINTEGER.tags(context)
        _chunks = []
        for _val in self._array:
            _chunks.append(signedint_to_netbytes(_val))
        value = VBytes(b''.join(_chunks))
        return VTagged(value, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding does not use residual tags')
        value = VEntity._v_lazy_native(value)
        if not isinstance(value, bytes):
            raise VTaggedParseError('Encoding value must be bytes data')

        _nums = []
        _offset = 0
        while value:
            _num, _b_read = netbytes_to_signedint(value)
            if _num is None:
                raise VTaggedParseError('Invalid number encoding')
            _nums.append(_num)
            value = value[_b_read:]
        result = VArrayOfVInteger(_nums)
        return (lambda x: x[0], [result])

    def _v_native_converter(self):
        return (lambda x: x[0], [self._array])


class VArrayOfFloat(VArrayOf):
    """Base class for array of typed float32 data.

    :param values: array values
    :type  value:  iterable
    :raises:       :exc:`exceptions.TypeError`

    Creates an internal shallow copy of provided elements, which is
    converted to float32. Note that rounding errors may occur as values
    are converted to float. Raises an exception if any of the
    provided elements are not float, integer (or long).

    .. automethod:: __iter__

    """

    def __init__(self, value):
        value = tuple(value)
        for _v in value:
            if _pyver == 2:
                if not isinstance(_v, (float, int, long)):
                    raise TypeError('All elements must be float convertible')
            else:
                if not isinstance(_v, (float, int)):
                    raise TypeError('All elements must be float convertible')
        _gen = (struct.unpack(b'f', struct.pack(b'f', e))[0] for e in value)
        super(VArrayOfFloat, self).__init__(tuple(_gen))

    def _v_as_tagged(self, context):
        tags = VSECodes.ARRAY_OF_FLOAT.tags(context)
        _chunks = []
        for _val in self._array:
            _chunks.append(struct.pack(b'>f', _val))
        value = VBytes(b''.join(_chunks))
        return VTagged(value, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding does not use residual tags')
        value = VEntity._v_lazy_native(value)
        if not isinstance(value, bytes):
            raise VTaggedParseError('Encoding value must be bytes data')

        if len(value) % 4 != 0:
            raise VTaggedParseError('Encoding must be multiple of 4 bytes')
        _nums = []
        _offset = 0
        while _offset < len(value):
            _nums.append(struct.unpack_from(b'>f', value, _offset)[0])
            _offset += 4
        result = VArrayOfFloat(_nums)
        return (lambda x: x[0], [result])

    def _v_native_converter(self):
        return (lambda x: x[0], [self._array])


class VArrayOfDouble(VArrayOf):
    """Base class for array of typed float64 data.

    :param values: array values
    :type  value:  iterable
    :raises:       :exc:`exceptions.TypeError`

    Creates an internal shallow copy of provided elements, which is
    converted to float64. Note that rounding errors may occur as
    values are converted to float. Raises an exception if any of the
    provided elements are not float, integer (or long).

    .. automethod:: __iter__

    """

    def __init__(self, value):
        value = tuple(value)
        for _v in value:
            if _pyver == 2:
                if not isinstance(_v, (float, int, long)):
                    raise TypeError('All elements must be float convertible')
            else:
                if not isinstance(_v, (float, int)):
                    raise TypeError('All elements must be float convertible')
        _gen = (struct.unpack(b'>d', struct.pack(b'>d', e))[0] for e in value)
        super(VArrayOfDouble, self).__init__(tuple(_gen))

    def _v_as_tagged(self, context):
        tags = VSECodes.ARRAY_OF_DOUBLE.tags(context)
        _chunks = []
        for _val in self._array:
            _chunks.append(struct.pack(b'>d', _val))
        value = VBytes(b''.join(_chunks))
        return VTagged(value, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding does not use residual tags')
        value = VEntity._v_lazy_native(value)
        if not isinstance(value, bytes):
            raise VTaggedParseError('Encoding value must be bytes data')

        if len(value) % 8 != 0:
            raise VTaggedParseError('Encoding must be multiple of 8 bytes')
        _nums = []
        _offset = 0
        while _offset < len(value):
            _nums.append(struct.unpack_from(b'>d', value, _offset)[0])
            _offset += 8
        result = VArrayOfDouble(_nums)
        return (lambda x: x[0], [result])

    def _v_native_converter(self):
        return (lambda x: x[0], [self._array])


class VArrayOfVFloat(VArrayOf):
    """Base class for array of typed VFloat data.

    :param values: array of VFloat (or lazy-convertible)
    :type  value:  iterable
    :raises:       :exc:`exceptions.TypeError`

    Creates an internal shallow copy of provided elements. Raises an
    exception if any of the provided elements are not VFloat or
    lazy-convertible to VFloat.

    .. automethod:: __iter__

    """

    def __init__(self, value):
        _value = []
        for _v in value:
            if isinstance(_v, VFloat):
                _value.append(_v)
            else:
                try:
                    _value.append(VFloat(_v))
                except ValueError:
                    raise TypeError('All elements must be VFloat')
        super(VArrayOfVFloat, self).__init__(tuple(_value))

    def _v_as_tagged(self, context):
        tags = VSECodes.ARRAY_OF_VFLOAT.tags(context)
        _chunks = []
        for _val in self._array:
            _chunks.append(signedint_to_netbytes(_val._v_digits))
            _chunks.append(signedint_to_netbytes(_val._v_base))
            _chunks.append(signedint_to_netbytes(_val._v_exp))
        value = VBytes(b''.join(_chunks))
        return VTagged(value, *tags)

    @classmethod
    def _v_vse_decoder(cls, value, *tags):
        """Create object from VSE tag data"""
        if tags:
            raise VTaggedParseError('Encoding does not use residual tags')
        value = VEntity._v_lazy_native(value)
        if not isinstance(value, bytes):
            raise VTaggedParseError('Encoding value must be bytes data')

        _nums = []
        _offset = 0
        while value:
            _num, _b_read = netbytes_to_signedint(value)
            if _num is None:
                raise VTaggedParseError('Invalid number encoding')
            _nums.append(_num)
            value = value[_b_read:]
        if len(_nums) % 3 != 0:
            raise VTaggedParseError('Invalid number encoding')
        _vals = []
        for i in xrange(len(_nums)//3):
            _digits = _nums[3*i];
            _base = _nums[3*i + 1];
            _exp = _nums[3*i + 2];
            _vals.append(VFloat(_digits, _exp, base=_base))

        result = VArrayOfVFloat(_vals)
        return (lambda x: x[0], [result])

    def _v_native_converter(self):
        return (lambda x: x[0], [self._array])


class VContainerModule(VModule):
    """Module for :term:`VSE` containers.

    This module resolves the following classes:

    * :class:`VFrozenMultiArray`
    * :class:`VFrozenDict`
    * :class:`VFrozenSet`

    """
    def __init__(self):
        super(VContainerModule, self).__init__()

        # Add decoders for conversion from VTagged
        _decoder = VFrozenMultiArray._v_vse_decoder
        _entry = VSECodes.MULTI_ARRAY.mod_decoder(_decoder)
        self.add_decoder(_entry)

        _entry = VSECodes.DICTIONARY.mod_decoder(VFrozenDict._v_vse_decoder)
        self.add_decoder(_entry)

        _entry = VSECodes.SET.mod_decoder(VFrozenSet._v_vse_decoder)
        self.add_decoder(_entry)

        _entry = VSECodes.ARRAY_OF_INT.mod_decoder(VArrayOfInt._v_vse_decoder)
        self.add_decoder(_entry)

        _entry = VSECodes.ARRAY_OF_LONG.mod_decoder(VArrayOfLong._v_vse_decoder)
        self.add_decoder(_entry)

        _code = VSECodes.ARRAY_OF_VINTEGER
        _entry = _code.mod_decoder(VArrayOfVInteger._v_vse_decoder)
        self.add_decoder(_entry)

        _code = VSECodes.ARRAY_OF_FLOAT
        _entry = _code.mod_decoder(VArrayOfFloat._v_vse_decoder)
        self.add_decoder(_entry)

        _code = VSECodes.ARRAY_OF_DOUBLE
        _entry = _code.mod_decoder(VArrayOfDouble._v_vse_decoder)
        self.add_decoder(_entry)

        _code = VSECodes.ARRAY_OF_VFLOAT
        _entry = _code.mod_decoder(VArrayOfVFloat._v_vse_decoder)
        self.add_decoder(_entry)

        # Add encoders for lazy-conversion to VEntity
        _entry = VModuleConverter(VFrozenSet._v_converter, types=(frozenset,))
        self.add_converter(_entry)

_vmodule = VContainerModule()
VModuleResolver._add_vse_import(VSEModuleCodes.CONTAINER, _vmodule)
