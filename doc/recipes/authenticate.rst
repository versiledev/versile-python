.. _authentication_recipe:

Authenticate a Client
=====================

The :term:`VOP` protocol with a secure :term:`VTS` or :term:`TLS`
transport uses public-key identities for client/server authentication,
which is the default choice of :term:`VP` user authentication. The
only truly secure way to assert an identity in a networked environment
is to link channel security to a secret associated with the identity
which is also used to secure the communication channel. With
:term:`VP` this comes practically for free.

In this recipe we will set up a simple server which authenticates an
identity provided by a client, and either allows or rejects the client
connection based on provided identity. We will use a :term:`VDI` based
client identity, see the :ref:`vdi_recipe` recipe for more
information.

There are several :term:`VOP` protocol features for authentication
which we will not be demonstrated in this recipe. We will only use
link-level authentication, however it is also possible to include
(additional) :term:`VTS` or :term:`TLS` transport-level
authentication. Another feature we are not using here is a client can
provide a certificate chain which validates the client's identity
public key and possibly also associated identity meta-data such as an
email address or organization name.

For this example we are not using any of those features, which however
still makes it orders of magnitude more robust than the standard web
based user+password based authentication.

For this recipe we will implement a service which accepts only one
single client identity for connections. Unless the appropriate public
key is provided and validated during the handshake, the client
connection will be rejected by the server. The client identity will be
the same as we generated in the :ref:`vdi_recipe` recipe, which
the client has at some point used to register itself with the service.

We set up a service with an authentication "hook" which matches the
client's public key with the known registered accepted client
identity. Beyond this addition the example is almost exactly the same
as the unauthenticated :ref:`listening_service_recipe` recipe. Below
is example service code::

    from versile.demo import SimpleGateway
    from versile.quick import Versile, VOPService, VCrypto
    from versile.quick import VUrandom, VX509Crypto

    Versile.set_agpl_internal_use()

    # We import an identity for the one identity which is authorized to connect
    client_ascii_id = """
    -----BEGIN RSA PUBLIC KEY-----
    MIGJAoGBALkqxpBVNvrPb0qgDqcggDXcPc1hzsaIp1Z+hCrYtcSbeQz3rJzQYJra1ujXplY/TUBB
    Ux3lA6wnoXO/C/Zx8rUk3hnZXn9iMbbZsN3mxEBhVy6q9l9DhRikFs0ZjKokK3i91RooqUfLJTKa
    nGGqw1q7VKKGytomWF05302kxF3NAgMBAAE=
    -----END RSA PUBLIC KEY-----
    """
    client_id = VX509Crypto.import_public_key(client_ascii_id.strip())

    # Set up an authorizer function for us in service link initiation
    def auth(link):
        key, cert_chain = link.context.credentials
        return (key.keydata == client_id.keydata)

    # Set up and start service - here we use a random server keypair
    keypair = VCrypto.lazy().rsa.key_factory.generate(VUrandom(), 1024/8)
    gw_factory = lambda: SimpleGateway()
    service = VOPService(gw_factory, auth=auth, key=keypair)
    service.start()
    service.wait(stopped=True)

On the client side we construct the client's identity from the
identity's associated secret data, and pass it as a key for the
:term:`VOP` transport. Below is example client code for connecting
with a server running with the above server code::

    from versile.quick import Versile, VUrl, VCrypto, VX509Crypto

    Versile.set_agpl_internal_use()
    
    # Construct client identity from identity secret data
    purpose  = 'Versily Python Demo Services'
    personal = 'I like Monty Python humor'
    password = 'kLqnr37ubG'
    identity = VCrypto.lazy().dia(1024, purpose, personal, password)

    # Connect to service, authenticating the client with decentral identity
    echo_gw = VUrl.resolve(b'vop://localhost/text/echo/', key=identity)
    print(echo_gw.echo('Please return this message'))
    del(echo_gw)

Notice the simplicity of the above code examples and using :term:`VDI`
based identification. With the client identity embedded into the
:term:`VTS` or :term:`TLS` transport itself, man-in-the-middle attacks
are eliminated by protecting all data with the client identity itself.

.. note::

    Another interesting benefit of this scheme is it is not possible
    to steal user passwords by hacking into a server - because there
    are no passwords to steal. A hacker would only be able to obtain
    the public component of the identity, but would never be able to
    assume that identity based only on information obtained from a
    server [the identity is however of course vulnerable to attacks
    such as keylogging or a compromised client computer which would
    enable an attacked to obtain the identity].

The server code example uses a simple hard-coded authentication
function which accepts only one single key. However, the function is
easily substituted with any other user management and authorization
component.

Note that in addition to authorizing a client, the ``auth()`` function
can also make changes on the link's
:class:`versile.orb.entity.VCallContext` context object. This may
include setting the context's *identity* property for a link-side
representation of the client's identity which has it has registered as
an associated identity to the client's provided (keypair) identity,
such as an email address or service user name.
