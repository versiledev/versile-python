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

"""Demo classes for use in examples and testing.

.. warning::

    These classes are not formally part of the :term:`VPy` API and should
    not be used by production code. Classes in this module may be changed
    or removed at any time between releases.

"""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport
from versile.common.util import VLockable
from versile.manager.dispatch import VDispatcher, VDispatchService
from versile.manager.dispatch import VDispatchGwFactory
from versile.orb.entity import VException
from versile.orb.external import VExternal, publish, doc

__all__ = ['Echoer', 'SimpleGateway', 'Adder']
__all__ = _vexport(__all__)


@doc
class SimpleGateway(VDispatcher):
    """A simple directory which can provide an echo service resource."""

    def __init__(self):
        super(SimpleGateway, self).__init__()
        service = VDispatchService('simple_gw')
        service.add(('text', 'echo'), VDispatchGwFactory(lambda : Echoer()))
        service.add(('math', 'adder'), VDispatchGwFactory(lambda : Adder()))
        self.add_service(service)


@doc
class Echoer(VExternal):
    """A simple service object for receiving and echoing a VEntity."""

    @publish(show=True, doc=True, ctx=False)
    def echo(self, arg):
        """Returns the received argument.

        :param arg: argument to return
        :returns:   received argument

        """
        return arg


@doc
class Adder(VExternal, VLockable):
    """Service object for adding integers and tracking their sum."""

    def __init__(self):
        VExternal.__init__(self)
        VLockable.__init__(self)
        self._sum = 0

    @publish(show=True, doc=True, ctx=False)
    def add(self, value):
        """Adds received value and returns updated partial sum.

        :param value: the value to add
        :returns:     partial sum after value has been added

        """
        with self:
            self._sum += value
            return self._sum

    @publish(show=True, doc=True, ctx=False)
    def result(self):
        """Returns the sum of submitted values.

        :returns: result

        """
        with self:
            return self._sum

    @publish(show=True, doc=True, ctx=False)
    def reset(self):
        """Reset partial sum to zero."""
        with self:
            self._sum = 0
