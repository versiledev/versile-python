.. _lib_native:

Native Objects
==============
.. currentmodule:: versile.vse.native

The module :mod:`versile.vse.native` includes classes for :term:`VSE`
native objects.

Native Object Framework
-----------------------
.. currentmodule:: versile.vse.native

The module :mod:`versile.vse.native` implements a general framework
for interacting with :term:`VSE` native
objects. :class:`VNativeObject` is a base class for creating external
interfaces to local objects. :class:`VNative` is a base class for
creating proxy interfaces to remote objects interfaced with local
objects. :exc:`VNativeException` is a base class for native
exceptions.

:class:`versile.vse.native.module.VNativeModule` provides module
capabilities for decoding :class:`VNative` and
:exc:`VNativeException`\ , and has an interface for registering
handlers for decoding derived classes.

Python Objects
--------------
.. currentmodule:: versile.vse.native.python

The module :mod:`versile.vse.native.python` has an implementation of
the :term:`VSE` native type standards for the native type tags
'vse-python-2.x' and 'vse-python-3.x'.

Proxies to local python objects can be created with
:class:`VPythonObject` which derives either :class:`VPython2Object` or
:class:`VPython3Object` based on the version of the current python
runtime.

Depending on the :term:`VSE` encoding identifying an object as
belonging to either python 2.x or 3.x, references to remote python
objects are decoded as either :class:`VPython2` or :class:`VPython3`\
, and exceptions are decoded as either :class:`VPython2Exception`\ ,
:class:`VPython3Exception` or a lazy-native converted type.

The 'native python object' framework offers a lot of possibilities for
interacting with a remote python interpreter, e.g. it could be used
for remote scripting. The :class:`VPython2` and :class:`VPython3`
classes take full advantage of python getattribute overloading to
provide an almost seamless proxy to a remote object.

Below is a simple python 2.x example of remote python object
interaction which provides remote access to a python interpreter
:func:`eval` function and allows interaction with the result of the
eval operation.

.. warning::

    Direct re-use of this example is highly insecure as it leaves the
    system vulnerable, providing direct access to the python 'eval'
    function on a remote system and essentially giving the remote peer
    full access to the computer.

Combined with proper authentication and authorization (similar to
e.g. secure shell access to a system) native python access to
capabilities such as :func:`eval` can be a powerful tool for remote
system management.

>>> from versile.orb.external import VExternal, publish, doc
>>> from versile.quick import VCrypto, VUrandom, VOPService, VUrl
>>> from versile.vse import VSEResolver
>>> from versile.vse.native.python import VPythonObject
>>>
>>> # Load VSE modules
... VSEResolver.add_imports()
>>>
>>> @doc
... class VulnerableRemoteService(VExternal):
...     """A simple service object for receiving and echoing a VEntity."""
...     @publish(show=True, doc=True)
...     def python_eval(self, cmd):
...         """Performs eval on 'cmd'"""
...         # WARNING - leaves system vulnerable
...         return VPythonObject(eval(cmd))
...
>>> VSEResolver.enable_vse()
>>> # Set up remote service with random key
... key = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 512//8)
>>> service = VOPService(lambda: VulnerableRemoteService(), auth=None, key=key)
>>> service.start()
>>>
>>> # Interact with remote service
... gw = VUrl.parse('vop://localhost/').connect().resolve()
>>> l = gw.python_eval('[1, 3, 7, True, b\'some_data\', -5, 4, 8]')
>>> type(l)
<class 'versile.vse.native.python.VPython2'>
>>> l._v_activate() # Activate remote object aliasing
>>> type(l)
<class 'versile.vse.native.python.VPython2'>
>>> l.__class__
<type 'list'>
>>> l
[1, 3, 7, True, 'some_data', -5, 4, 8]
>>> l.reverse()
>>> l
[8, 4, -5, 'some_data', True, 7, 3, 1]
>>> l[2::2]
[-5, True, 3]
>>> l[5] = 123123123
>>> l
[8, 4, -5, 'some_data', True, 123123123, 3, 1]
>>>
>>> # Clean up
... gw._v_link.shutdown()
>>> service.stop(True)

.. testcleanup::

   VSEResolver.enable_vse(False)

Module APIs
-----------

Module API for :mod:`versile.vse.native`

.. automodule:: versile.vse.native
    :members:
    :show-inheritance:

Module API for :mod:`versile.vse.native.module`

.. automodule:: versile.vse.native.module
    :members:
    :show-inheritance:

Module API for :mod:`versile.vse.native.python`

.. automodule:: versile.vse.native.python
    :members:
    :show-inheritance:
