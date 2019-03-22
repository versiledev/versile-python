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

"""File descriptor related functionality."""
from __future__ import print_function, unicode_literals

import os
import select

from versile.internal import _vexport
from versile.common.iface import peer
from versile.reactor.io import IVByteHandle

__all__ = ['IVDescriptor']
__all__ = _vexport(__all__)


try:
    import fcntl
except Exception:
    __have_fcntl = True
else:
    __have_fcntl = False


class IVDescriptor(IVByteHandle):
    """File descriptor based byte handle."""

    @peer
    def close_io(self, reason):
        """Called by event handler to close I/O all directions.

        See :meth:`versile.reactor.io.IVByteHandle.close_io`

        """

    def fileno(self):
        """Returns a file descriptor which can be used with select()"""
