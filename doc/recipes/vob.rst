.. _vob_recipe:

Create an External Object
=========================
.. currentmodule:: versile.orb.external

Classes for instantiating objects that can be externally referenced
are easily created with the :class:`VExternal` base class and
decorators defined in the :mod:`versile.orb.external`
module. Resulting objects will also comply with :term:`VOB`
specifications.

Below is an example of a class which buffers added names until as
request is made to reset the buffer and return all buffered names in
sorted order::

    from versile.quick import *

    @doc
    class NameSorter(VExternal):
        """Buffers and sorts names."""

        def __init__(self):
            super(NameSorter, self).__init__()
            self._names = []

        @publish(show=True, doc=True, ctx=False)
        def add(self, name):
            """Appends a name to the name buffer."""
            vchk(name, vtyp(unicode), vset)
            with self:
                self._names.append(name)

        @publish(show=True, doc=True, ctx=False)
        def reset(self):
            """Clears the buffer and returns (sorted) buffered names."""
            with self:
                names, self._names = self._names, []
            return tuple(sorted(names))

        @publish(ctx=True)
        def dummy(self, ctx=None):
            return repr((ctx.credentials, ctx.identity))

Some key features to be aware of from the example class definition:

* :class:`VExternal` constructor must be called
* The :func:`publish` decorator is used to declare methods as externally
  available and set meta-data
* Methods published with *ctx=True* (i.e. ``dummy`` in the example) an
  internal link context keyword argument is provided to the method
* :class:`VExternal` holds a re-entrant lock that can be synchronized
  on using a ``with`` statement.
* We used the :func:`versile.orb.validate.vchk` mechanisms for input
  argument validation

The *ctx=True* allows a method to access a link's
:class:`versile.orb.entity.VCallContext` object. This object holds
information about an identity that may have been authenticated for the
link, and can also be used to hold other link session data.

Below is an example which demonstrates remote use of the class.

>>> from versile.quick import *
>>> @doc
... class NameSorter(VExternal):
...     """Buffers and sorts names."""
...     def __init__(self):
...         super(NameSorter, self).__init__()
...         self._names = []
...     @publish(show=True, doc=True, ctx=False)
...     def add(self, name):
...         """Appends a name to the name buffer."""
...         vchk(name, vtyp(unicode), vset)
...         with self:
...             self._names.append(name)
...     @publish(show=True, doc=True, ctx=False)
...     def reset(self):
...         """Clears the buffer and returns (sorted) buffered names."""
...         with self:
...             names, self._names = self._names, []
...         return tuple(sorted(names))
...     @publish(ctx=True)
...     def dummy(self, ctx=None):
...         return repr((ctx.credentials, ctx.identity))
...
>>> client_link = link_pair(gw1=None, gw2=NameSorter())[0]
>>> name_service = client_link.peer_gw()
>>>
>>> name_service.add(u'John Doe')
>>> name_service.add(u'Jane Doe')
>>> name_service.add(u'James Tiberius Kirk')
>>> name_service.reset()
(u'James Tiberius Kirk', u'Jane Doe', u'John Doe')
>>>
>>> # Client is not authorized with an identity so no interesting result
... name_service.dummy()
'((None, ()), None)'
>>>
>>> # Because VExternal implements VOB, standard meta-calls can be used
... dir(name_service)
[u'add', u'reset']
>>> name_service.meta.doc()
u'Buffers and sorts names.\n'
>>> name_service.meta.doc(u'add')
u'Appends a name to the name buffer.\n'
>>>
>>> client_link.shutdown()

Note how the object can be accessed remotely with the same syntax as
if it were local. Also observe the use of *meta* calls for remote
inspection, which we got "for free" with the :func:`publish` decorator
declarations.
