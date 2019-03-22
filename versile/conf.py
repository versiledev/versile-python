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


"""Global Versile Python configuration."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport

__all__ = ['Versile']
__all__ = _vexport(__all__)


class Versile(object):
    """Global Versile Python configuration.

    This class used to track license information from before licensing
    was changed to the LGPL v3. Its use is deprecated and it is retained
    solely for compatibility.

    """

    # Hardcoded after license was changed to LGPLv3
    _copyleft = True
    _copyleft_license = 'LGPLv3'
    _copyleft_url = 'https://www.gnu.org/licenses/lgpl.txt'

    @classmethod
    def set_agpl(cls, url, other_lic=None):
        """Deprecated after change to LGPLv3 and has no effect."""
        pass

    @classmethod
    def set_agpl_internal_use(cls):
        """Deprecated after change to LGPLv3 and has no effect."""
        pass

    @classmethod
    def set_commercial(cls):
        """Deprecated after change to LGPLv3 and has no effect."""
        pass

    @classmethod
    def copyleft(cls):
        """Returns configured Versile Python copyleft license information.

        :returns: tuple of license information
        :rtype:   (bool, unicode, unicode)

        Returns 3-tuple of the following elements:

        * True if set to run with copyleft license, otherwise False
        * If copyleft license, the configured license name(s)
        * If copyleft license, URL to license and download instructions

        """
        return (Versile._copyleft, Versile._copyleft_license,
                Versile._copyleft_url)

    @classmethod
    def _reset_copyleft(cls):
        """Deprecated after change to LGPLv3 and has no effect."""
        pass
