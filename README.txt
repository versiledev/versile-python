Versile Python -- implementation of Versile Platform

Copyright (C) 2011-2013 Versile AS

Versile Python is free software: you can redistribute it and/or
modify it under the terms of the GNU Lesser General Public License
as published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public
License along with this program.  If not, see <http://www.gnu.org/licenses/>.


Overview
--------

This is the source distribution of Versile Python for python
[>PY_VERSIONS<]. The latest source code is available from
https://github.com/versiledev/versile-python .

Versile Python comes in two distributions, one distribution for python
2.6+ and a second distribution for python 3.x. The two distributions share a
common codebase and the 3.x distribution is generated from the 2.x codebase
with the python '2to3' migration tool.

The latest stable release can also be downloaded from
http://www.sci4all.org/versile/ or installed from the python package index,
either "pip install versile-python2" (python v2.6+) or
"pip install versile-python3" (python v3.x).


Installation
------------

This package comes with a distutils installation script. To install
execute the following command in a shell:

    "python setup.py install"

Note the command may have to be executed with administrative
privileges (e.g. sudo or a root shell) and depending on setup a full
path to the executable may need to be provided. Also ensure the python
executable is compatible with python versions [>PY_VERSIONS<].

It is strongly recommended to also download and install PyCrypto
(https://www.dlitz.net/software/pycrypto/) if available on the
platform. When present it will significantly speed up cryptographic
methods and enable additional ciphers such as AES.

For testing or user-specific installations consider using virtualenv,
see http://pypi.python.org/pypi/virtualenv


Bugs and Patches
----------------

See https://github.com/versiledev/versile-python for latest version and
information how to report issues.


Documentation
-------------

Browse or download documentation at http://www.sci4all.org/versile/


Additional Information
----------------------

This is a beta release. APIs may change in later releases.
