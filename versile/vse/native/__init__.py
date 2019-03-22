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

"""Implements :term:`VSE` native objects."""
from __future__ import print_function, unicode_literals

from collections import deque
import time

from versile.internal import _vexport
from versile.common.iface import abstract
from versile.orb.entity import VEntity, VTagged, VReference
from versile.orb.entity import VString, VTuple, VTaggedParseError
from versile.orb.external import VExternal
from versile.orb.module import VERBase
from versile.vse.const import VSECodes

__all__ = ['VNativeObject', 'VNative', 'VNativeException']
__all__ = _vexport(__all__)


@abstract
class VNativeObject(VERBase, VExternal):
    """Implements :term:`VSE` native access to a local object.

    A reference to this object is typically included in the object's
    :term:`VER` encoding, and it is the gateway for accessing or
    performing operations on the local object.

    The external interface is individual to each native type, and this
    base class does not impose any particular interface.

    The object must have a 'native tag' defined which specifies the
    native type (interface) implemented by this class. Tag values
    prefixed with 'vse-' are reserved for use by the :term:`VSE`
    standard. Derived classes must implement :meth:`_v_native_tag` so
    it provides the correct tag value.

    When decoding a :class:`VNativeObject` representation, it should
    be resolved as a :class:`VNative` which provides a proxy-type
    interface for accessing the native object. Derived classes must
    implement :meth:`_v_native_ref` which should instantiate the
    appropriave sub-class of :class:`VNative`\ .

    This class is abstract, only derived classes should be
    instantiated.

    .. automethod:: _v_native_ref
    .. automethod:: _v_native_tag

    """

    def __init__(self, *args, **kargs):
        VExternal.__init__(self, *args, **kargs)

    def _v_as_tagged(self, context):
        tags = VSECodes.NATIVE_OBJECT.tags(context) + (self._v_native_tag(),)
        return VTagged(self._v_raw_encoder(), *tags)

    @abstract
    def _v_native_ref(self):
        """Returns a proxy alias to this object

        :returns: native reference to this object
        :rtype:   :class:`VNative`

        Abstract, derived classes must implement.

        """
        raise NotImplementedError()

    @abstract
    @classmethod
    def _v_native_tag(cls):
        """Return the native tag of this native type.

        :returns: native tag
        :rtype:   unicode

        The 'native tag' is used as the residual tag in the object's
        :term:`VER` encoding.

        Abstract, derived classes must implement.

        """
        raise NotImplementedError


class VNative(VERBase, VEntity):
    """Implements an aliasing interface to a local or remote native object.

    :param obj: object implementing remote interface to native object
    :type  obj: :class:`versile.orb.entity.VObject`
    :param tag: native tag of *obj*\ \'s native type
    :type  tag: unicode

    A :class:`VNative` should provide mechanisms for accessing a
    (remotely referenced) native object. This base class does not
    provide any such mechanisms, as the appropriate mechanisms are
    specific to the particular native type. However, the remote
    native-object reference can always be retreived via
    :class:`VNative` :attr:`_v_native_obj`\ .

    The object initially starts in a 'passive' state and should only
    provide remote-object interfaces once it has been
    'activated'. Activation is performed by calling
    :meth:`_v_activate`\ . This is a security measure in order to
    ensure provided native-object interfaces are not unintentionally
    accessed.

    Derived classes may use __getattribute__ overloading of
    :class:`VNative` for provided aliased interfaces, however a few
    limitations apply. Getattribute overloading service may be only
    provided after the object has been activated. Also, attribute names
    prefixed with '_v_' may not be overloaded.

    The object's current activation state can be retreived by
    performing the following operation (which is a bit cumbersome,
    however it ensures derived-class getattribute aliasing does not
    interfere)

        ``VNative.__getattribute__(self, '_v_active'``

    When the object is in an 'active' state, it is permitted to
    instantiate other :class:`VNative` objects and set them to be
    'active' (this is the typical pattern). Otherwise, instantiated
    objects may not be 'active'. Also, when the object is 'active' it
    is allowed to convert return values from remote operations to
    native types.

    .. automethod:: _v_activate
    .. autoattribute: _v_native_obj

    """
    def __init__(self, obj, tag):
        if not isinstance(obj, VReference):
            if isinstance(obj, VNativeObject):
                if obj._v_native_tag() != tag:
                    raise VTaggedParseError('VNative tag mismatch')
            else:
                raise VTaggedParseError('Not a VReference or VNativeObject')

        VEntity.__init__(self)
        self._v_int_native_obj = obj._v_proxy()
        self._v_tag = tag
        self._v_active = False

    def _v_as_tagged(self, context):
        tags = VSECodes.NATIVE_OBJECT.tags(context) + (self._v_tag,)
        return VTagged(self._v_native_obj()._v_raw_encoder(), *tags)

    def _v_activate(self):
        """Activates the object."""
        if not self._v_active:
            self._v_active = True

    @property
    def _v_native_obj(self):
        """Implementing remote-obj (:class:`versile.orb.entity.VProxy`\ )."""
        return self._v_int_native_obj


class VNativeException(VERBase, VEntity, Exception):
    """Implements an exception raised by a remote native-type object.

    :param tag:  native tag of the exceptions native-type
    :type  tag:  unicode
    :param args: exception e.args values

    The :exc:`VNativeException` mechanism allows raising exceptions
    which can be identified as native exceptions, and native types may
    define standards for how the exception is encoded and interpreted.

    Similar to :class:`VNative` a native exception must be 'activated'
    before it is allowed to enable any remote aliasing interfaces, or
    activate remote objects provided via this object.

    .. automethod:: _v_activate

    """
    def __init__(self, tag, *args):
        self._v_tag = tag
        self._v_args = args
        self._v_active = False

    def _v_as_tagged(self, context):
        tags = VSECodes.NATIVE_EXCEPTION.tags(context) + (self._v_tag,)
        return VTagged(self._v_args, *tags)

    def _v_activate(self):
        """Activates the object."""
        if not self._v_active:
            self._v_active = True

    @property
    def args(self):
        """Arguments set on the exception."""
        return self._v_args
