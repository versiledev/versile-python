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

"""Implements :term:`VSE` native python 2.x and python 3.x objects."""
from __future__ import print_function, unicode_literals

import Queue
import weakref

from versile.internal import _vexport, _pyver
from versile.common.iface import abstract
from versile.orb.entity import VEntity, VTuple, VException, VCallError
from versile.orb.external import publish, doc_with
from versile.vse.native import VNativeObject, VNative, VNativeException
from versile.vse.container import VFrozenDict

__all__ = ['VBasePythonObject', 'VBasePython', 'VBasePythonException',
           'VPython2Object', 'VPython2', 'VPython2Exception',
           'VPython3Object', 'VPython3', 'VPython3Exception',
           'VPythonObject', 'VPython', 'VPythonException']
__all__ = _vexport(__all__)


@abstract
class VBasePythonObject(VNativeObject):
    """Base class for remote interfaces to native python objects.

    :param python_obj: the native python object

    This class is abstract and should not be directly instantiated.

    """
    # Class attributes which must be set on derived classes
    _v_python_tag = None
    _v_python_ptyp = None
    _v_python_exc = None

    def __init__(self, python_obj):
        super(VBasePythonObject, self).__init__()
        self._obj = python_obj

    __ext_doc = 'getattribute(attr) - return object attribute'
    @publish(show=True, doc=__ext_doc, ctx=False)
    def getattribute(self, attr):
        """Retreive an attribute on the object proxied by this class.

        :param attr: attribute identifier
        :type  attr: unicode

        """
        obj = self._obj
        _conv = self._v_convert_for_send

        # We override handling of some attributes
        if attr == '__dir__':
            return _conv(lambda : dir(obj))
        elif attr == '__iter__':
            return _conv(lambda : iter(obj))
        elif attr == '__next__':
            return _conv(lambda : next(obj))
        elif attr == '__str__':
            return _conv(lambda : str(obj))
        elif attr == '__repr__':
            return _conv(lambda : repr(obj))
        elif attr == '__unicode__':
            return _conv(lambda : unicode(obj))
        elif attr == '__nonzero__':
            return _conv(lambda : bool(obj))
        elif attr == '__getitem__':
            def _handler(*args, **kargs):
                if not args and len(kargs) == 1:
                    slice_data = kargs.get('slice', None)
                    if not slice_data or not isinstance(slice_data, tuple):
                        raise VCallError('Invalid keyword argument')
                    try:
                        start, stop, step = slice_data
                        s = slice(start, stop, step)
                    except:
                        raise VCallError('Invalid slice data')
                    return obj[s]
                elif len(args) and not kargs:
                    return obj[args[0]]
                else:
                    raise VCallError('Invalid call arguments')
            return _conv(_handler)

        # General handler
        if isinstance(attr, bytes):
            # Ensure 'attr' is sent as string
            attr = unicode(attr)
        try:
            result = getattr(obj, attr)
        except Exception as e:
            raise _conv(e)
        else:
            return _conv(result)

    __ext_doc = ('call(args, kargs) - perform call on (callable) object\n' +
                 '  args  - arguments (tuple)\n' +
                 '  kargs - keyword arguments (VFrozenDict)\n')
    @publish(show=True, doc=__ext_doc, ctx=False)
    def call(self, args, kargs):
        """Perform a call on the object proxied by this class.

        :param args:  arguments
        :type  args:  tuple, :class:`VTuple`
        :param kargs: keyword arguments
        :type  kargs: :class:`versile.vse.container.VFrozenDict`

        """
        # Validate argument format
        if not isinstance(args, (tuple, VTuple)):
            raise VCallError('Arguments must be a tuple')
        if not isinstance(kargs, VFrozenDict):
            raise VCallError('Keyword arguments must be a VFrozenDict')
        if kargs:
            keys, vals = zip(*(kargs.items()))
        else:
            keys = vals = tuple()

        # Resolve any VPythonObject as native object in the data structures
        args = self._v_obj_from_recv(args)
        keys, vals = self._v_obj_from_recv(keys), self._v_obj_from_recv(vals)
        kargs = dict(zip(keys, vals))

        # Execute call and convert result/exception
        try:
            result = self._obj(*args, **kargs)
        except Exception as e:
            e = self._v_convert_for_send(e)
            raise e
        else:
            result = self._v_convert_for_send(result)
            return result

    @classmethod
    def _v_convert_for_send(cls, result):
        """Parse 'result' for sending, into VEntity-compliant format."""
        try:
            return VEntity._v_lazy(result)
        except:
            if isinstance(result, Exception):
                if isinstance(result, VException):
                    return result
                # Try to up-convert local exception types
                args = [cls._v_convert_for_send(e) for e in result.args]
                name = cls._v_python_exc._CONVERSION.get(type(result), None)
                if name:
                    return cls._v_python_exc(name, *args)
                # If this failed, generate a non-standard VPythonException
                rcls = result.__class__
                e_name = '%s.%s' % (rcls.__module__, rcls.__name__)
                return cls._v_python_exc(e_name, *args)
            else:
                return cls(result)
        else:
            return result

    @classmethod
    def _v_obj_from_recv(cls, obj, activate=False):
        """Parses obj, converting VPythonObject to VPythonObject._obj

        Also lazy-native converts from VEntity to native representation.

        """
        t = type(obj)
        if t in (tuple, set, frozenset):
            return t(cls._v_obj_from_recv(e) for e in obj)
        elif isinstance(obj, VNativeObject):
            return obj._obj
        elif isinstance(obj, VBasePython) and activate:
            obj._v_activate()
            return obj
        elif isinstance(obj, VBasePythonException) and activate:
            obj._v_activate()
            obj = VEntity._v_lazy_native(obj)
            return obj
        else:
            try:
                return VEntity._v_lazy_native(obj)
            except:
                return obj

    def _v_native_ref(self):
        return self._v_python_vtyp(self, selv._v_native_tag())

    @classmethod
    def _v_native_tag(cls):
        return cls._v_python_tag


@doc_with('VSE native object which implements \'vse-python-2.x\'')
class VPython2Object(VBasePythonObject):
    """Implements a remote interface to a native python 2.x object.

    :param python_obj: the native python object

    Implements the :term:`VSE` native type standard for the
    'vse-python-2.x' native type tag.

    """
    # Some class attributes for this class are set outside the class
    # definition later in this module


@doc_with('VSE native object which implements \'vse-python-3.x\'')
class VPython3Object(VBasePythonObject):
    """Implements a remote interface to a native python 3.x object.

    :param python_obj: the native python object

    Implements the :term:`VSE` native type standard for the
    'vse-python-3.x' native type tag.

    """
    # Some class attributes for this class are set outside the class
    # definition later in this module


def _python_op(call_method):
    def perform_op(self, *args, **kargs):
        native_attr = VNative.__getattribute__
        active = native_attr(self, '_v_active')
        if active:
            func = getattr(self, call_method)
            return self._v_exec_and_conv(func, active, *args, **kargs)
        else:
            _func = getattr(VNative, call_method)
            result = _func(self, *args, **kargs)
            return result
    return perform_op


@abstract
class VBasePython(VNative):
    """Base class for proxy interfaces to remote python objects.

    :param obj: object implementing remote interface to native object
    :type  obj: :class:`versile.orb.entity.VObject`
    :param tag: :term:`VSE` encoding tag
    :type  tag: unicode

    When activated, the following effects apply:

    * The object overrides __getattribute__ to call 'getattribute' on
      the remote object. The __getattribute__ overloading is applied
      to all attributes except attributes prefixed with '_v_'.

    * The object overrides __call__ to direct all calls made on the
      object to 'call' on the remote object, including both call
      arguments and keyword arguments.

    * The object overrides __setattr__ so it is forwarded to the
      remote object as a __setattr__ call on the remote object

    When decoding a :class:`VBasePython` the decoder checks whether an
    attribute '_v_vse_native_python' is set on the remote-object
    reference. If it is not set, the decoder performs a complete
    decoding and sets the attribute to hold a weak reference to the
    decoded object.

    The class is abstract and should not be directly instantiated.

    """
    # Class attribute which must be set by derived classes
    _v_python_otyp = None

    def __init__(self, obj, tag):
        super(VBasePython, self).__init__(obj, tag)

    def __call__(self, *args, **kargs):
        native_attr = VNative.__getattribute__
        active = native_attr(self, '_v_active')
        if not active:
            raise TypeError('Python reference not callable until activated.')

        peer = native_attr(self, '_v_native_obj')

        # Package arguments for sending
        _conv = self._v_python_otyp._v_convert_for_send
        c_args = VTuple(_conv(e) for e in args)
        c_kargs = ((unicode(key), val) for key, val in kargs.items())
        c_kargs = tuple((_conv(key), _conv(val)) for key, val in c_kargs)
        c_kargs = VFrozenDict(dict(c_kargs))

        # Perform call on referenced peer and convert result or exception
        return self._v_exec_and_conv(peer.call, active, c_args, c_kargs)

    def _v_exec_and_conv(self, method, activate, *args, **kargs):
        native_attr = VNative.__getattribute__
        active = native_attr(self, '_v_active')
        _conv = self._v_python_otyp._v_obj_from_recv
        try:
            result = method(*args, **kargs)
        except Exception as e:
            raise _conv(e, activate=active)
        else:
            return _conv(result, activate=active)

    @classmethod
    def _v_vse_obj_decoder(cls, value):
        with value:
            decoded = getattr(value, '_v_vse_native_python', None)
            if decoded:
                decoded = decoded()
                if decoded:
                    return decoded
            decoded = cls(value)
            value._v_vse_native_python = weakref.ref(decoded)
            return decoded

    def __getattribute__(self, attr):
        native_attr = VNative.__getattribute__
        active = native_attr(self, '_v_active')
        if not active or attr.startswith('_v_'):
            return native_attr(self, attr)
        else:
            _conv = self._v_python_otyp._v_obj_from_recv
            peer = native_attr(self, '_v_native_obj')
            try:
                result = peer.getattribute(attr)
            except:
                raise AttributeError()
            else:
                return _conv(result, activate=active)

    def __dir__(self):
        native_attr = VNative.__getattribute__
        active = native_attr(self, '_v_active')

        if active:
            dir_func = self.__dir__
            result = self._v_exec_and_conv(dir_func, active)
            _conv = self._v_python_otyp._v_obj_from_recv
            return list(_conv(e) for e in iter(result))
        else:
            # Mimic __dir__ behavior
            return self.__dict__.keys()

    def __iter__(self):
        native_attr = VNative.__getattribute__
        active = native_attr(self, '_v_active')

        if active:
            iter_func = self.__iter__
            class _VPythonIterable(object):
                def __init__(self, it):
                    self.__it = it
                def __iter__(self):
                    return self
                def next(self):
                    return self.__next__()
                def __next__(self):
                    result = self.__it._v_exec_and_conv(self.__it.__next__,
                                                        activate=True)
                    return result
            return _VPythonIterable(iter_func())
        else:
            return VNative.__iter__(self)

    def __setattr__(self, attr, val):
        """When active, performs setattr on remote object"""
        native_attr = VNative.__getattribute__
        try:
            active = native_attr(self, '_v_active')
        except AttributeError:
            active = False

        if active:
            func = getattr(self, '__setattr__')
            return self._v_exec_and_conv(func, active, attr, val)
        else:
            VNative.__setattr__(self, attr, val)

    def __getitem__(self, item):
        native_attr = VNative.__getattribute__
        active = native_attr(self, '_v_active')

        # If 'slice', convert to tuple and send as keyword argument
        if active:
            func = getattr(self, '__getitem__')
            if isinstance(item, slice):
                slice_data = (item.start, item.stop, item.step)
                return self._v_exec_and_conv(func, active, slice=slice_data)
            else:
                return self._v_exec_and_conv(func, active, item)
        else:
            return VNative.__getitem__(self, item)

    # Overloaded various standard methods
    __delattr__      = _python_op('__delattr__')
    __str__          = _python_op('__str__')
    __repr__         = _python_op('__repr__')
    __contains__     = _python_op('__contains__')
    __countOf__      = _python_op('__countOf__')
    __indexOf__      = _python_op('__indexOf__')
    __setitem__      = _python_op('__setitem__')
    __delitem__      = _python_op('__delitem__')
    __reversed__     = _python_op('__reversed__')
    __len__          = _python_op('__len__')
    __nonzero__      = _python_op('__nonzero__')
    __hash__         = _python_op('__hash__')

    # Unary operator overload
    __truth__     =  _python_op('__truth__')
    __index__     =  _python_op('__index__')
    __abs__       =  _python_op('__abs__')
    __neg__       =  _python_op('__neg__')
    __inv__       =  _python_op('__inv__')
    __pos__       =  _python_op('__inv__')

    # Binary left operator overload
    __lt__        =  _python_op('__lt__')
    __le__        =  _python_op('__le__')
    __eq__        =  _python_op('__eq__')
    __ne__        =  _python_op('__ne__')
    __ge__        =  _python_op('__ge__')
    __gt__        =  _python_op('__gt__')
    __add__       =  _python_op('__add__')
    __and__       =  _python_op('__and___')
    __floordiv__  =  _python_op('__floordiv__')
    __lshift__    =  _python_op('__lshift__')
    __mod__       =  _python_op('__mod__')
    __mul__       =  _python_op('__mul__')
    __or__        =  _python_op('__or___')
    __pow__       =  _python_op('__pow__')
    __rshift__    =  _python_op('__rshift__')
    __sub__       =  _python_op('__sub__')
    __xor__       =  _python_op('__xor__')
    __concat__    =  _python_op('__concat__')
    __truediv__   =  _python_op('__truediv__')

    # Binary right operator overload
    __rlt__        =  _python_op('__rlt__')
    __rle__        =  _python_op('__rle__')
    __req__        =  _python_op('__req__')
    __rne__        =  _python_op('__rne__')
    __rge__        =  _python_op('__rge__')
    __rgt__        =  _python_op('__rgt__')
    __radd__       =  _python_op('__radd__')
    __rand__       =  _python_op('__rand___')
    __rfloordiv__  =  _python_op('__rfloordiv__')
    __rlshift__    =  _python_op('__rlshift__')
    __rmod__       =  _python_op('__rmod__')
    __rmul__       =  _python_op('__rmul__')
    __ror__        =  _python_op('__ror___')
    __rpow__       =  _python_op('__rpow__')
    __rrshift__    =  _python_op('__rrshift__')
    __rsub__       =  _python_op('__rsub__')
    __rxor__       =  _python_op('__rxor__')
    __rconcat__    =  _python_op('__rconcat__')
    __rtruediv__   =  _python_op('__rtruediv__')


class VPython2(VBasePython):
    """Implements a proxy interface to a remote python 2.x object.

    :param obj: object implementing remote interface to native object
    :type  obj: :class:`versile.orb.entity.VObject`

    Implements the :term:`VSE` native type standard for the
    'vse-python-2.x' native type tag.

    """
    # Some class attributes for this class are set outside the class
    # definition later in this module

    def __init__(self, obj):
        super(VPython2, self).__init__(obj, 'vse-python-2.x')


class VPython3(VBasePython):
    """Implements a proxy interface to a remote python 3.x object.

    :param obj: object implementing remote interface to native object
    :type  obj: :class:`versile.orb.entity.VObject`

    Implements the :term:`VSE` native type standard for the
    'vse-python-3.x' native type tag.

    """
    # Some class attributes for this class are set outside the class
    # definition later in this module

    def __init__(self, obj):
        super(VPython3, self).__init__(obj, 'vse-python-3.x')


@abstract
class VBasePythonException(VNativeException):
    """Base class for exceptions raised by remote native python objects.

    :param tag:  :term:`VSE` encoding tag
    :type  tag:  unicode
    :param args: exception e.args values

    Implements lazy-native conversion to native python exceptions for
    a large set of exceptions (see :attr:`_NATIVE_CONVERSION` for a
    list).

    This class is abstract and should not be directly instantiated.

    """

    def __init__(self, tag, *args):
        super(VBasePythonException, self).__init__(tag, *args)

    def _v_native_converter(self):
        if self.args and self._v_active:
            e_name, args = self.args[0], self.args[1:]
            Cls = self._NATIVE_CONVERSION.get(e_name, None)
            if Cls:
                return (None, [Cls(args)])
        return (None, [self])

    @classmethod
    def _v_vse_exc_decoder(cls, *args):
        return cls(*args)


    # Conversion table for lazy-native conversion to native exceptions
    _NATIVE_CONVERSION = {
        'exceptions.ArithmeticError': ArithmeticError,
        'exceptions.AssertionError': AssertionError,
        'exceptions.AttributeError': AttributeError,
        'exceptions.BaseException': BaseException,
        'exceptions.BufferError': BufferError,
        'exceptions.BytesWarning': BytesWarning,
        'exceptions.DeprecationWarning': DeprecationWarning,
        'exceptions.EOFError': EOFError,
        'exceptions.EnvironmentError': EnvironmentError,
        'exceptions.Exception': Exception,
        'exceptions.FloatingPointError': FloatingPointError,
        'exceptions.FutureWarning': FutureWarning,
        'exceptions.GeneratorExit': GeneratorExit,
        'exceptions.IOError': IOError,
        'exceptions.ImportError': ImportError,
        'exceptions.ImportWarning': ImportWarning,
        'exceptions.IndentationError': IndentationError,
        'exceptions.IndexError': IndexError,
        'exceptions.KeyError': KeyError,
        'exceptions.KeyboardInterrupt': KeyboardInterrupt,
        'exceptions.LookupError': LookupError,
        'exceptions.MemoryError': MemoryError,
        'exceptions.NameError': NameError,
        'exceptions.NotImplementedError': NotImplementedError,
        'exceptions.OSError': OSError,
        'exceptions.OverflowError': OverflowError,
        'exceptions.PendingDeprecationWarning': PendingDeprecationWarning,
        'Queue.Empty': Queue.Empty,
        'exceptions.ReferenceError': ReferenceError,
        'exceptions.RuntimeError': RuntimeError,
        'exceptions.RuntimeWarning': RuntimeWarning,
        'exceptions.StandardError': StandardError,
        'exceptions.StopIteration': StopIteration,
        'exceptions.SyntaxError': SyntaxError,
        'exceptions.SyntaxWarning': SyntaxWarning,
        'exceptions.SystemError': SystemError,
        'exceptions.SystemExit': SystemExit,
        'exceptions.TabError': TabError,
        'exceptions.TypeError': TypeError,
        'exceptions.UnboundLocalError': UnboundLocalError,
        'exceptions.UnicodeDecodeError': UnicodeDecodeError,
        'exceptions.UnicodeEncodeError': UnicodeEncodeError,
        'exceptions.UnicodeError': UnicodeError,
        'exceptions.UnicodeTranslateError': UnicodeTranslateError,
        'exceptions.UnicodeWarning': UnicodeWarning,
        'exceptions.UserWarning': UserWarning,
        'exceptions.ValueError': ValueError,
        'exceptions.Warning': Warning,
        'exceptions.ZeroDivisionError': ZeroDivisionError
        }

    # Conversion table for converting to VPythonException
    _CONVERSION = dict((val, key) for key, val in _NATIVE_CONVERSION.items())


class VPython2Exception(VBasePythonException):
    """Implements exceptions raised by remote native python 2.x objects.

    :param args: exception e.args values

    Implements the :term:`VSE` native type standard for the
    'vse-python-2.x' native type tag.

    """

    def __init__(self, *args):
        super(VPython2Exception, self).__init__('vse-python-2.x', *args)


class VPython3Exception(VBasePythonException):
    """Implements exceptions raised by remote native python 3.x objects.

    :param args: exception e.args values

    Implements the :term:`VSE` native type standard for the
    'vse-python-3.x' native type tag.

    """

    def __init__(self, *args):
        super(VPython3Exception, self).__init__('vse-python-3.x', *args)


# Set required class attributes on python 2.x classes - these are set
# outside the class definition due to python module parsing order
VPython2Object._v_python_tag = 'vse-python-2.x'
VPython2Object._v_python_ptyp = VPython2
VPython2Object._v_python_exc = VPython2Exception
VPython2._v_python_otyp = VPython2Object


# Set required class attributes on python 3.x classes - these are set
# outside the class definition due to python module parsing order
VPython3Object._v_python_tag = 'vse-python-3.x'
VPython3Object._v_python_ptyp = VPython3
VPython3Object._v_python_exc = VPython3Exception
VPython3._v_python_otyp = VPython3Object


# Create convenience classes for accessing the appropriate classes for
# the current python version
if _pyver == 2:
    class VPythonObject(VPython2Object):
        """Remote interface to native python objects.

        Convenience class for invoking the appropriate implementation
        of :class:`VBasePythonObject` for this python version.

        """
    class VPython(VPython2):
        """Proxy interfaces to remote python objects.

        Convenience class for invoking the appropriate implementation
        of :class:`VBasePython` for this python version.

        """
    class VPythonException(VPython2Exception):
        """Exceptions raised by remote native python objects.

        Convenience class for invoking the appropriate implementation
        of :class:`VBasePythonException` for this python version.

        """
else:
    class VPythonObject(VPython3Object):
        """Remote interface to native python objects.

        Convenience class for invoking the appropriate implementation
        of :class:`VBasePythonObject` for this python version.

        """
    class VPython(VPython3):
        """Proxy interfaces to remote python objects.

        Convenience class for invoking the appropriate implementation
        of :class:`VBasePython` for this python version.

        """
    class VPythonException(VPython3Exception):
        """Exceptions raised by remote native python objects.

        Convenience class for invoking the appropriate implementation
        of :class:`VBasePythonException` for this python version.

        """
