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

"""Framework for interface definitions for python classes."""
from __future__ import print_function, unicode_literals

import copy
import sys

from versile.internal import _vplatform, _vexport

__all__ = ['peer', 'VInterface', 'implements', 'implement', 'multiface',
           'final', 'abstract']
__all__ = _vexport(__all__)


def peer(method):
    """Decorator @peer for methods that should only be called by a 'peer'.

    For now this is only a way of visually showing this information.

    """
    return method

class VInterface(object):
    """Base class for interface definitions."""

    @classmethod
    def provided_by(cls, obj):
        """Returns True if interface is provided by object (or class).

        :param obj: an object (or class) to be checked
        :returns:   True if interface provided by the object (or class)
        :rtype:     bool

        """
        if not hasattr(obj, 'iv_interfaces'):
            return False
        if not isinstance(obj.iv_interfaces, _VInterfaceSet):
            return False
        for iface in obj.iv_interfaces:
            if issubclass(iface, cls):
                return True
        return False


class _VInterfaceSet(set):
    """Holds a list of implemented interfaces"""
    pass


def implements(*ifaces):
    """Class decorator @implements for implementing an interface.

    Note that use of this decorator will set the 'iv_interfaces'
    attribute on the class, which should not be used for other
    conflicting purposes.

    """
    def decor(c):
        if not hasattr(c, 'iv_interfaces'):
            c.iv_interfaces = _VInterfaceSet(ifaces)
        elif isinstance(c.iv_interfaces, _VInterfaceSet):
            c.iv_interfaces = copy.copy(c.iv_interfaces)
            for iface in ifaces:
                c.iv_interfaces.add(iface)
        elif (_vplatform == 'ironpython'
              and isinstance(c.iv_interfaces, (set, frozenset))):
            # Workaround for IronPython due to isinstance() issue
            c.iv_interfaces = copy.copy(c.iv_interfaces)
            for iface in ifaces:
                c.iv_interfaces.add(iface)
        else:
            raise TypeError('cls.iv_interfaces not of type _VInterfaceSet')
        return c
    return decor

def implement(*ifaces):
    """Sets and/or adds to a class' 'iv_interfaces' attribute.

    Can be used to declare interfaces inside a class definition.

    """
    frame = sys._getframe(1)
    f_locals = frame.f_locals
    if 'iv_interfaces' not in f_locals:
        f_locals['iv_interfaces'] = _VInterfaceSet()
    elif isinstance(f_locals['iv_interfaces'], _VInterfaceSet):
        f_locals['iv_interfaces'] = copy.copy(f_locals['iv_interfaces'])
    else:
        raise TypeError('cls.iv_interfaces is not of type _VInterfaceSet')
    for iface in ifaces:
        f_locals['iv_interfaces'].add(iface)

def multiface(c):
    """Decorator @multiface resolves interfaces with multiple inheritance.

    Use of the decorator will cause traversal of all base classes,
    adding all base classes' interfaces to the derived class.

    """
    if not hasattr(c, 'iv_interfaces'):
        c.iv_interfaces = _VInterfaceSet(ifaces)
    elif isinstance(c.iv_interfaces, _VInterfaceSet):
        c.iv_interfaces = copy.copy(c.iv_interfaces)
        for base in c.__bases__:
            if (hasattr(base, 'iv_interfaces')
                and isinstance(base.iv_interfaces, _VInterfaceSet)):
                for iface in base.iv_interfaces:
                    c.iv_interfaces.add(iface)
    elif (_vplatform == 'ironpython'
          and isinstance(c.iv_interfaces, (set, frozenset))):
        # Workaround for IronPython due to isinstance() issue
        c.iv_interfaces = copy.copy(c.iv_interfaces)
        for base in c.__bases__:
            if (hasattr(base, 'iv_interfaces')
                and isinstance(base.iv_interfaces, _VInterfaceSet)):
                for iface in base.iv_interfaces:
                    c.iv_interfaces.add(iface)
    else:
        raise TypeError('cls.iv_interfaces is not of type _VInterfaceSet')
    return c

def final(method):
    """Decorator @final for methods that should not be overridden.

    For now this is only a way of visually showing this information in
    the code.

    """
    return method


def abstract(entity):
    """Decorator @abstract for abstract methods or classes.

    An abstract class should not be directly instantiated, but needs
    to be sub-classed. An abstract method must be overridden in a
    derived class. For now this is only a way of visually showing this
    information in the code.

    """
    return entity
