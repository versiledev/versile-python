.. _python_recipe:

Access Native Python Objects
============================

The :term:`VSE` library defines mechanisms for accessing native python
types. This recipe shows how a reference to a native python object
interface can be passed over a link, and native python methods can be
seamlessly called from the remote side.

The below code defines a gateway which returns a python object
reference, and client-side code for accessing the object.

>>> from versile.vse.native.python import VPythonObject
>>> from versile.quick import *
>>> 
>>> # Load all VSE modules (including VNativeModule)
... VSEResolver.add_imports()
>>> 
>>> class Gateway(VExternal):
...     @publish(show=True, doc=True, ctx=False)
...     def get_python_list(self):
...         """Return a reference to a python list object."""
...         l = [5, -2, b'txt', 1.3]
...         return VPythonObject(l)
... 
>>> Versile.set_agpl_internal_use()
>>> VSEResolver.enable_vse()
>>> client_link = link_pair(gw1=None, gw2=Gateway())[0]
>>> gw = client_link.peer_gw()
>>> 
>>> # Retreive a python object reference and activate the proxy interface
... obj = gw.get_python_list()
>>> type(obj)
<class 'versile.vse.native.python.VPython2'>
>>> obj._v_activate()
>>> 
>>> # Perform remote operations on the remote list reference
... str(obj)
"[5, -2, 'txt', 1.3]"
>>> obj.append(100)
>>> obj = obj[2:]
>>> str(obj)
"['txt', 1.3, 100]"
>>> 
>>> client_link.shutdown()

.. testcleanup::

   from versile.conf import Versile
   Versile._reset_copyleft()
   VSEResolver.enable_vse(False)

As the example shows a reference to the remote list object can be
(mostly) accessed similarly to a local native object, due to
overloading on the local proxy interface.

.. note::

    In order to use the proxy interface on a reference to a native
    object, the :meth:`versile.vse.native.VNative._v_activate` method
    must be called first. This is a security feature in order to
    prevent accidentally accessing remote object features. However,
    once a reference has been activated, any native object references
    returned by performing actions on the object are also
    automatically activated.

Remote access to native objects can be a powerful feature. Combined
with proper authentication and authorization it enables use cases such
as remote scripting or remote system management.
