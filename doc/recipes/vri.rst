.. _resolve_vri_recipe:

Resolve a VRI
=============

A :term:`VRI` identifies a resource. Resolving a :term:`VRI` involves
establishing a :term:`VOL` link to a ORB which provides access to the
resource, and requesting the resource from the received gateway
object. Derived classes of :class:`versile.orb.url.VUrl` have
mechanisms for performing these operations, and an implementation is
typically retreived from :mod:`versile.quick`\ .

.. note::

    Due to technical details of the :term:`VOL` protocol for a link
    handshake, global license information must be set on
    :class:`versile.Versile` before a :class:`VLink` can be
    constructed. See :class:`versile.Versile` for more information.

In this recipe we explore a simple scenario for accessing a
:term:`VRI` resource without any protocol-level client authentication,
accessing a remote :class:`versile.demo.SimpleGateway` gateway object.

If the service from recipe ':ref:`listening_service_recipe`\ ' is
running on the system, the following code will resolve a :term:`VRI`
reference to a :term:`VOP` echo service resource::

    from versile.quick import VUrl
    echo_gw = VUrl.resolve('vop://localhost/text/echo/')
    print(echo_gw.echo('Please return this message'))
    del(echo_gw)

A link will normally be automatically shut down if no references
remain to any peer objects as in the previous example, including the
associated link. However, there may be situations where this does not
work due to interpreter implementation of the garbage collection or
potential remaining local or remote references. Explicitly shutting
down the link is "safer" if it is known that no other local or remote
code needs continued access to same link.

In any case, it is important that all links get properly shut down
when a program terminates, otherwise still-active link threads will
prevent the python interpreter from closing.

Performing explicit link shutdown requires VRI resolution in multiple
steps in order to obtain a reference to the link gateway (which
provides a reference to the link). When a top-level link gateway has
been obtained, multiple partial VRI resolutions for VRI path+query
components can be performed on the gateway object. Relative VRI
resolution has the advantage that each resolved resource will reuse
the existing link.

Below is an example which performs relative VRI resolution with
explicit link shutdown::

    from versile.quick import VUrl
    gw = VUrl.resolve('vop://localhost/')
    echo_gw = VUrl.relative(gw, '/text/echo/')
    print(echo_gw.echo('Please return this message'))
    gw._v_link.shutdown(force=True)

:term:`VRI`\ s can be resolved as a non-blocking operation. Below is
an example how this can be done. Note that due to asynchronous DNS
resolution effects this consumes one thread per pending peer-connect
operation. Below is an example of non-blocking resolution::

    from versile.quick import VUrl
    call = VUrl.resolve('vop://localhost/text/echo/', nowait=True)
    echo_gw = call.result(timeout=10.0)
    print(echo_gw.echo('Please return this message'))
    echo_gw = call = None

The above examples demonstrate access to a resource identified by a
:term:`VRI` with a *path* component but no *query* component.  A
:term:`VRI` which includes a query can be conveniently be constructed
with :meth:`versile.orb.url.VUrl.vri`\ . Below is an example of
including a *query* to perform a remote call as part of :term:`VRI`
resolution::

    from versile.quick import VUrl
    url = VUrl.vri('vtps', 'localhost', ('text', 'echo'), query_name='echo',
                   query_args=('Please return this message',))
    call = VUrl.resolve(url, nowait=True)
    return_msg = call.result(timeout=10.0)
    print(return_msg)
    call = None
