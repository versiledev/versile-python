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

from distutils.core import setup
import os


# Release number
release = '[>RELEASE<]'
py_version = [>PY_VER<]

# General settings
provides = 'versile_python[>PY_V_POSTFIX<]'
author = 'Versile AS'
author_email = '48810296+versiledev@users.noreply.github.com'
url = 'https://github.com/versiledev/versile-python'

# LGPL related settings
name = 'versile-python[>PY_V_POSTFIX<]'
long_name = 'Versile Python'
lic = 'GNU Lesser GPL v3 License'

ldesc = """

Versile Python
--------------

Versile Python is an implementation of Versile Platform for python
[>PY_VERSIONS<]. Lates source code is on
`GitHub <https://github.com/versiledev/versile-python>`__ .
See `website <http://www.sci4all.org/versile/>`__
for documentation and additional information.

Versile Platform
----------------

Versile Platform is a set of open protocols enabling object-level
service interaction between heterogenous technologies. The protocols
are designed to enable simple yet flexible and powerful patterns for
interacting with remote services or running services.

"""
ldesc = ldesc.strip() + '\n'

# Package meta-data
cf = ['Development Status :: 4 - Beta',
      'Intended Audience :: Developers',
      'License :: OSI Approved :: GNU Lesser General Public License v3',
      'Natural Language :: English',
      'Operating System :: MacOS :: MacOS X',
      'Operating System :: Microsoft :: Windows',
      'Operating System :: POSIX',
      'Operating System :: Unix',
      'Topic :: Communications',
      'Topic :: Internet',
      'Topic :: Software Development :: Libraries :: Python Modules',
      'Topic :: Software Development :: Object Brokering'
      ]
if py_version == 2:
    cf.extend(['Programming Language :: Python :: 2.6',
               'Programming Language :: Python :: 2.7'
               ])
elif py_version == 3:
    cf.append('Programming Language :: Python :: 3')


# Packages under ./versile/
packages = []
for dirpath, dirs, files in os.walk('versile'):
    if '__init__.py' in files:
        packages.append(dirpath.replace(os.path.sep, '.'))


if __name__ == '__main__':
    setup(name=name,
          version=release,
          description=long_name,
          long_description=ldesc,
          provides=[provides],
          author=author,
          author_email=author_email,
          maintainer=author,
          maintainer_email=author_email,
          url=url,
          packages=packages,
          keywords=['versile'],
          classifiers=cf,
          license=lic
          )
