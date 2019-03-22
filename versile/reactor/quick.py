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

"""Exports reactors for waiting on file descriptor I/O available on the OS.

The module exports the reactor it believes to be the best performing
on the system as the class :class:`VReactor`.

"""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport, _v_silent

_reactors = []
_r_cls = None


try:
    from versile.reactor.selectr import VSelectReactor
except ImportError as e:
    _v_silent(e)
else:
    _reactors.append('VSelectReactor')
    _r_cls = VSelectReactor

try:
    from versile.reactor.pollr import VPollReactor
except ImportError as e:
    _v_silent(e)
else:
    _reactors.append('VPollReactor')
    _r_cls = VPollReactor

try:
    from versile.reactor.kqueuer import VKqueueReactor
except ImportError as e:
    _v_silent(e)
else:
    _reactors.append('VKqueueReactor')
    import sys
    if sys.platform != 'darwin':
        # PLATFORM - would normally have set VKqueueReactor as the default
        # for OSX, however the select-based reactor performed better in
        # initial testing, so for now keeping that as a default reactor on OSX
        _r_cls = VKqueueReactor

try:
    from versile.reactor.epollr import VEpollReactor
except ImportError as e:
    _v_silent(e)
else:
    _reactors.append('VEpollReactor')
    _r_cls = VEpollReactor

if _r_cls:
    VReactor = _r_cls
    _reactors.append('VReactor')
if _reactors:
    __all__ = _reactors
    __all__ = _vexport(__all__)
