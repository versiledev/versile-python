#!/usr/bin/env python
#
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

"""Release configuration and release pre-processing."""
from __future__ import print_function, unicode_literals

import os.path
import re
import sys


# Python version
if sys.version_info[0] == 2:
    _pyver = 2
else:
    _pyver = 3

# Release parameters for this release
version = '0.8'
release = version + '.5'

# Common macros, the macros are encapsulated inside '[>name<]', e.g.
# '[>RELEASE<]' is the 'RELEASE' macro.
MACROS = {'RELEASE': release}


# Macros for python 2.x and python 3.x release respectively. The _M tuple
# has elements in the format of (macro_name, v2_replace, v3_replace)
_M = (('PY_VER', '2', '3'),
      ('PY_V_POSTFIX', '2', '3'),
      ('PY_VERSIONS', 'v2.6 and v2.7', 'v3.x'))
V2MACROS = dict([(e[0], e[1]) for e in _M])
V3MACROS = dict([(e[0], e[2]) for e in _M])


def usage(exit_status=None):
    print(_USAGE)
    if exit_status is not None:
        exit(exit_status)


_USAGE = """
Usage: prepare [py_version] [source_dir] [dest_dir]

py_version      target python version, either '2' or '3'
source_dir      root directory of Versile Base
dest_dir        an empty directory

"""


def parse_args():
    if not len(sys.argv) != 3:
        print('Error: Invalid number of arguments')
        usage(1)
    py_ver, source_dir, dest_dir = sys.argv[1:4]

    # Validate py_ver
    try:
        py_ver = int(py_ver)
    except Exception:
        print('Error: Invalid python version')
        usage(1)
    else:
        if py_ver not in (2, 3):
            print('Error: Invalid python version')
            usage(1)

    # Validate source_dir and dest_dir
    if not os.path.isdir(source_dir):
        print('Error: Invalid source dir')
        usage(1)
    if not os.path.isdir(dest_dir):
        print('Error: Invalid dest dir')
        usage(1)

    return py_ver, source_dir, dest_dir


def check_copyright(data, prefix):
    """Validates copyright somewhere in top 3 lines

    :param data:   the content to validate
    :param prefix: a prefix on the line to be checked
    """
    if _pyver == 3 and isinstance(prefix, bytes):
        prefix = prefix.decode('utf8')
    p = re.compile(prefix + r' Copyright \(C\) 2\d\d\d.* Versile AS')
    for line in data.splitlines()[:3]:
        if p.search(line):
            return True
    return False


def copy_py_sourcedir(source, dest, pyver, skip=None):
    """Recursively parses and copies a python source directory."""
    dlist = os.listdir(source)
    for f in dlist:
        sf = os.path.join(source, f)
        df = os.path.join(dest, f)
        if skip and sf in skip:
            print('Skipping    %s' % sf)
            continue
        if os.path.isdir(sf):
            print('Adding dir  %s' % sf)
            os.mkdir(df, 0o755)
            copy_py_sourcedir(sf, df, pyver)
        else:
            copy_py_sourcefile(sf, df, pyver)


def copy_py_sourcefile(source, dest, pyver):
    """Parses and copies a python source file."""
    if source.endswith('.py'):
        print('Source File %s' % source)
        content = open(source).read()
        content = parse_macros(content, pyver)
        if not check_copyright(content, b'#'):
            raise RuntimeError('Missing copyright')
        else:
            open(dest, 'w').write(content)
    else:
        print('Skipping    %s' % source)


def parse_macros(s, pyver):
    # Set the appropriate macro set for this python version
    macros = list(MACROS.items())
    if pyver == 2:
        macros.extend(tuple(V2MACROS.items()))
    else:
        macros.extend(tuple(V3MACROS.items()))

    # Perform macro resolution
    for val, text in macros:
        s = re.sub('\\[>%s<\\]' % val, text, s)

    # Check no unresolved macros remain
    if re.search('\\[>.*<\\]', s):
        raise RuntimeError('Could not resolve all release macros')

    return s


if __name__ == '__main__':
    py_ver, source_top, dest_top = parse_args()

    from release import release
    if py_ver == 2:
        name = 'versile-python2'
    else:
        name = 'versile-python3'
    release_name = name + '-' + release

    print('Release parameters\n------------------')
    print('Python version : %s.x' % py_ver)
    print('Name           :', name)
    print('Release        :', release)
    print('Full name      :', release_name)

    # Create destination top directory
    dest_top = os.path.join(dest_top, release_name)
    if os.path.exists(dest_top):
        raise RuntimeError('Destination release directory already exists')
    else:
        try:
            os.mkdir(dest_top, 0o755)
        except Exception:
            print('Error: could not create %s' % dest_top)
            usage(1)
        print('Destination    : %s' % dest_top)

    # Copy sourcecode
    print('\nCopying source files\n----------------------')
    py_source_top = os.path.join(source_top, 'versile')
    py_dest_top = os.path.join(dest_top, 'versile')
    os.mkdir(py_dest_top, 0o755)
    copy_py_sourcedir(py_source_top, py_dest_top, py_ver)

    # Copy setup.py
    _setup = os.path.join(source_top, 'setup.py')
    print('Setup File  %s' % _setup)
    setup_dest = os.path.join(dest_top, 'setup.py')
    copy_py_sourcefile(_setup, setup_dest, py_ver)
    os.chmod(setup_dest, 0o755)

    # Copy individual files
    for fname in 'MANIFEST.in', 'LICENSE.txt', 'README.txt':
        content = open(os.path.join(source_top, fname)).read()
        content = parse_macros(content, py_ver)
        open(os.path.join(dest_top, fname), 'w').write(content)
