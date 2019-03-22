.. _lib_external:

.. currentmodule:: versile.orb.external

External Objects
================

This is the API documentation for the :mod:`versile.orb.external`
module which provides the base class :class:`VExternal` and decorators
for creating remotely referenceable :term:`VOB` compliant classes.

:class:`VExternal` is the default choice of base class for objects
which can be remotely referenced and accessed. It exposes a
developer-friendly interface with a clean and readable syntax. Working
directly with the parent class :class:`versile.orb.entity.VObject`
should only be required for implementing objects that are not
:term:`VOB` compliant or special situations which require lower-level
manipulation.

.. note::

    Unless there is some very special non-standard requirement that
    dictates otherwise, use :class:`VExternal` as the base class for
    remotely referenceable objects, not
    :class:`versile.orb.entity.VObject`\ .

Defining external classes with VExternal
----------------------------------------

:class:`VExternal` keeps a register of which methods can be called
remotely. The set of remote methods can be dynamically altered during
runtime. Decorators defined by :mod:`versile.orb.external` also offer
a nice declarative syntax for class definitions to declare methods as
remote.

The below example shows how :class:`VExternal` inheritance and
decorators can be used to create a class for objects which can be
remotely referenced. Notice there is almost no code overhead, just one
decorator per method::

    from versile.orb.external import *

    @doc
    class Adder(VExternal):
        """Tracks a rolling sum."""

        def __init__(self):
            super(Adder, self).__init__()
            self.__sum = 0

        @publish(show=True, doc=True, ctx=False)
        def add(self, number):
            """Adds to rolling sum, usage add(number)."""
            with self:
                self.__sum += number

        @publish(show=True, doc=True, ctx=False)
        def result(self):
            """Returns rolling sum result, usage result()."""
            with self:
                return self.__sum
        
        def private_method(self):
            """This method is not externally visible."""
            pass

As the example shows methods can be published with the :func:`publish`
decorator. Keyword arguments includes:

* Setting 'show=True` makes the method externally visible in a call to
  the 'meta.methods()' remote object inspection mechanism
* Setting 'doc=True' publishes the docstring of the method as the string
  returned by the 'meta.doc()' remote object inspection mechanism
* Setting 'ctx=False' instructs the base class not to pass a method
  call context object as a keyword argument (useful if the method does
  not care about the context)

Also note that the :class:`VExternal` holds a :class:`threading.RLock`
which can be synchronized on by using a ``with`` statement.

Below is an alternative implementation which does not publish any
documentation and which takes context arguments::

    from versile.orb.external import *
    
    class AlternativeAdder(VExternal):
        """This doc is not published externally."""
	
        def __init__(self):
	    super(AlternativeAdder, self).__init__()
            self.__sum = 0
	    
        @publish(show=True)
        def add(self, number, ctx=None):
            """This doc is not published externally."""
            with self:
	        self.__sum += number
		
        @publish(show=True)
        def result(self, ctx=None):
            """This doc is not published externally."""
            with self:
                return self.__sum
		
        def private_method(self):
            """This method is not externally visible."""
            pass

A :term:`VOB` meta-method can be enabled with one of the decorators
:func:`meta` or :func:`meta_as` (not showed in the example).

Calling methods on VExternal objects
------------------------------------

By using a :class:`versile.orb.entity.VProxy` to access a
:class:`VExternal` object or reference, the object can be accessed
with the natural and developer-friendly proxy object API to
:term:`VOB` interfaces. Below is an example an instance of the Adder
class can be accessed via a :class:`versile.orb.entity.VProxy`\ .

>>> from versile.demo import Adder
>>> adder = Adder()
>>> proxy = adder._v_proxy()
>>> for i in xrange(10):
...     _temp_result = proxy.add(i)
... 
>>> proxy.result()
45

Remote inspection of referenced objects
---------------------------------------

:class:`versile.orb.entity.VProxy` overloads the attribute *meta* to
provide an interface to the standard :term:`VOB` inspection mechanisms
which are supported by :class:`VExternal`\ . The below example shows
how a proxy for an instance of the Adder class in an earlier example
can be remotely inspected:

>>> from versile.demo import Adder
>>> adder = Adder()
>>> proxy = adder._v_proxy()
>>> proxy.meta.methods()
(u'add', u'reset', u'result')
>>> dir(proxy)
[u'add', u'reset', u'result']
>>> proxy.meta.doc()
u'Service object for adding integers and tracking their sum.\n'
>>> proxy.meta.doc(u'add').splitlines()[0]
u'Adds received value and returns updated partial sum.'

Notice the following:

* :class:`versile.orb.entity.VProxy` overloads ``dir()`` to return the
  same value as ``proxy.meta.methods()``
* ``adder.private_method`` does not show up in ``dir()`` as the method
  is not remotely published
* ``proxy.meta.doc()`` retreives a class or method docstring

The proxy object has a smart handling of the *meta* attribute which
avoids constraining the namespace for methods. In the above example,
``proxy.meta`` returns an object which can resolve as either a regular
method or a meta method. If a call is made directly on that object
then it is treated as a regular call. Otherwise, it is treated as a
gateway to meta methods. This means regular method published with the
name 'meta' can still be called.

Publishing and unpublishing methods
-----------------------------------

Methods can be dynamically published during runtime by calling
:meth:`VExternal._v_publish`\ . They can be dynamically removed with
:meth:`VExternal._v_unpublish` or
:meth:`VExternal._v_unpublish_by_name`\ .

The below example shows how a method can be unpublished, making it no
longer remotely accessible. Note that an access via a
:class:`versile.orb.entity.VProxy` is considered to be "remote" and
uses only the external interface, even if the object exists locally.

>>> from versile.orb.external import *
>>> class YouGetOnlyTwoShots(VExternal):
...     def __init__(self):
...         super(YouGetOnlyTwoShots, self).__init__()
...         self._shots_left = 2
...     @publish(show=True, ctx=False)
...     def shoot(self):
...         with self:
...             self._shots_left -= 1
...             if self._shots_left == 0:
...                 self._v_unpublish(self.shoot)
...             return u'Nice shooting!'
... 
>>> shooter = YouGetOnlyTwoShots()._v_proxy()
>>> while True:
...     try:
...         result = shooter.shoot()
...     except:
...         print('Could not shoot, aborting')
...         break
...     else:
...         print(result)
... 
Nice shooting!
Nice shooting!
Could not shoot, aborting

Validating method arguments
---------------------------
.. currentmodule:: versile.orb.validate

External objects typically operate across security boundaries where
the peer cannot be fully trusted, and so method arguments typically
need to be validated. If a peer is allowed to violate argument type
requirements set by the API, value constraints or otherwise feed the
method illegal or out-of-range values, this is a major potential
source of security exploits or instability problems.

The :mod:`versile.orb.validate` module includes several convenience
functions for validating input arguments. At the core of the
validation is the :func:`vchk` function which can perform a set of
checks on an argument and raise an exception if any check fails. A
simple example:

>>> from versile.orb.validate import *
>>> arg = 5
>>> vchk(arg, vtyp(int, long))
>>> try:
...   vchk(arg, vtyp(unicode))
... except:
...   print('This check threw an exception')
... 
This check threw an exception

The :func:`vchk` function can take single-argument validation
functions as validator arguments, or boolean values which are fed
directly into the function. This allows using whichever version is
semantically nicer. The following :func:`vchk` tests are equivalent:

>>> from versile.orb.validate import *
>>> arg = 60
>>> vchk(arg, vtyp(u'int'), vmin(0), vmax(100, False))
>>> vchk(arg, vtyp(u'int'), 0 <= arg < 100)
>>> vchk(arg, vtyp(u'int'), lambda x: 0 <= x, lambda x: x < 100)
>>> vchk(arg, vtyp(u'int'), lambda x: 0 <= x < 100)

The following provided functions can be used to create tests:

+--------------+------------------------+
| Function     | Description            |
+==============+========================+
| :func:`vtyp` | Validate type          |
+--------------+------------------------+
| :func:`vmin` | Validate minimum value |
+--------------+------------------------+
| :func:`vmax` | Validate maximum value |
+--------------+------------------------+

The following functions can be used directly as tests:

+--------------+----------------------------+
| Function     | Description                |
+==============+============================+
| :func:`vset` | Validate value is not None |
+--------------+----------------------------+

Below is an example how validation is used in a class derived from
:class:`versile.orb.external.VExternal`, which shows how invalid
arguments raise exceptions which prevent the method from executing.

>>> from versile.orb.external import *
>>> from versile.orb.validate import *
>>> class PosIntAdder(VExternal):
...     @publish(show=True, ctx=False)
...     def add(self, m, n):
...         # Validate input arguments
...         for arg in m, n:
...             vchk(arg, vtyp(u'int'), vmin(1))
...         return m + n
... 
>>> adder = PosIntAdder()._v_proxy()
>>> adder.add(10, 23)
33
>>> for args in ((10, 23), (0, 4), (5, -1)):
...     try:
...         result = adder.add(*args)
...     except:
...         print('Exception adding', args)
...     else:
...         print('Added', args, 'result', result)
... 
('Added', (10, 23), 'result', 33)
('Exception adding', (0, 4))
('Exception adding', (5, -1))


Module APIs
-----------

External Objects
................
Module API for :mod:`versile.orb.external`

.. automodule:: versile.orb.external
    :members:
    :show-inheritance:

Validation
..........
Module API for :mod:`versile.orb.validate`

.. automodule:: versile.orb.validate
    :members:
    :show-inheritance:
