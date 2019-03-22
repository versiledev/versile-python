.. _setup:

Setup and Usage
===============

.. rubric:: Download

For information how to obtain Versile Python see `GitHub
<https://github.com/versiledev/versile-python>`__ and another project `website
<http://www.sci4all.org/versile/>`__ .

.. rubric:: Dependencies

If available on the target platform it is strongly recommended to also
download and install `PyCrypto
<https://www.dlitz.net/software/pycrypto/>`__\ . When present it will
significantly speed up cryptographic methods and enable additional
ciphers such as AES. PyCrypto is also available `from PyPI
<http://pypi.python.org/pypi/pycrypto/>`__\ . Unless installing
PyCrypto from a binary upstream release, installation requires a
working C compiler and build environment.

.. note::

   If PyCrypto cannot be installed then Versile Python secure
   transport performance is significantly reduced and AES is not
   available as a cipher.

.. rubric:: Install

The :term:`VPy` source distribution provided by Versile includes a
:mod:`distutils` setup.py script for installing Versile Python as a
set of module.

Installation with CPython can normally be performed with the following
shell command:

  ``python setup.py install``

Note the command may have to be executed with administrative
privileges (e.g. sudo or a root shell) and depending on setup a full
path to the executable may need to be provided. Also ensure the python
executable is compatible with either python 2.6 or 2.7.

.. note::

    Consider using `virtualenv
    <http://pypi.python.org/pypi/virtualenv>`__ for the installation

.. rubric:: Using

After installation then :term:`VPy` modules can be imported from the
target python environment, e.g.

>>> from versile.orb.entity import *
>>> s = VString(u'It works!')
>>> print(s)
It works!

.. rubric:: Other runtimes

We currently do not provide install instructions here for other python
runtimes than CPython. Development snapshots have been tested to work
with `PyPy <http://pypy.org/>`__ and `IronPython
<http://pypy.org/>`__\ . Also snapshots have been successfully used
with IronPython with the .Net script engine together with Visual
Studio 2010 and `Python Tools for Visual Studio
<http://pytools.codeplex.com/>`__\ .

.. note::

   :term:`VPy` currently does not work with :term:`TLS` for other
   runtimes, so for maximum platform compatibility use :term:`VTS` as
   the secure transport for :term:`VOP` links.
