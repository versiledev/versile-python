.. _vri_gateway_recipe:

Define a Gateway for VRIs
=========================

The :term:`VRI` specification defines a standard for how remote
resources are obtained from an ORB.

:term:`VRI` resolution involves obtaining a top-level gateway object
from a :term:`VOL` peer. If the :term:`VRI` has a *path* component it
is resolved by calling the :term:`VOB` method ``urlget`` on the
gateway. The parameters to ``urlget`` is a tuple of path components to
be resolved.

In order to enable a gateway to be used for resolving :term:`VRI`
resources, the method ``urlget`` must be published which provides path
resolution. Below is a simple example class (which is currently
included in the :mod:`versile.demo` module)::

    from versile.demo import Echoer, Adder
    from versile.quick import *
    
    @doc
    class SimpleGateway(VExternal):
        """A simple directory which can provide an echo service resource."""
        
        @publish(show=True, doc=True, ctx=False)
        def urlget(self, path):
            """Provides VRI-based access to some service objects."""
            if path == (u'text', u'echo'):
                return Echoer()
            elif path == (u'math', u'adder'):
                return Adder()
            else:
                raise VException('Invalid path')

If this gateway was running as a :term:`VOP` service on localhost, an
echoer could be obtained as ``vop://localhost/text/echo/``\ .
