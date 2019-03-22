.. _vdi_recipe:

Construct a Decentral Identity
==============================

:term:`VDI` makes working with keypairs for authentication as simple
as using user+password combination (actually even simpler), and is
immensely more versatile in how it can be used and what security it
offers for authentication.

The :term:`VOP` protocol with a secure :term:`VTS` or :term:`TLS`
consider a keypair to *be* an identity because the only information
that a secure handshake can verify with near-absolute certainty is
that the communicating peer is in possession of the full identity
keypair.

Using keypairs as identities is much more powerful and robust than the
standard web pattern of a "username + password". Though :term:`TLS`
supports client-side public-key authentication it is rarely used on
the web. Most people are not willing to copy 1024-bit RSA keys between
devices they use, or pay for a recognized CA to sign their key. Most
:term:`TLS` implementations also seem to be designed towards handling
server/client symmetrically, requiring certificate chains and root CA
validation also of clients, which is clearly overkill for an average
user. With :term:`VDI` the problems of using :term:`TLS` client
authentication are essentially eliminated.

:term:`VDI` is the mechanism of choice for generating a public-key
based identity. Below is an example of creating an identity and
exporting it as a :term:`X.509` public key.

>>> from versile.quick import VCrypto, VX509Crypto
>>> purpose  = 'Versily Python Demo Services'
>>> personal = 'I like Monty Python humor'
>>> password = 'kLqnr37ubG'
>>> identity = VCrypto.lazy().dia(1024, purpose, personal, password)
>>> type(identity)
<class 'versile.crypto.local._VLocalRSAKey'>
>>> x509_pubkey = VX509Crypto.export_public_key(identity.public)
>>> print(x509_pubkey) #doctest: +NORMALIZE_WHITESPACE
-----BEGIN RSA PUBLIC KEY-----
MIGJAoGBANpspNSQPXlq/tEBIq8pT31WYzcKFtX8b41k9ec5YqiJhgOf9WyK0UqTScOzLiySKun2
XBVjXRhok5kvyT32K+JYh2VwoOnS0J6KFOhaatKMvDmVIFyhAdZ7xC3+jf1zT0n/vAQE0+DEGKfS
de7je8eA/T4C7uwLKn98aY+oudFtAgMBAAE=
-----END RSA PUBLIC KEY-----

And that is really all there is to it. ``identity`` is a regular RSA
key pair which can be used as an identity, and which can be used with
all methods and interfaces which accept a key pair.

.. note::

    Using a key pair for authentication is not only a much more secure
    and convenient way to represent an identity - it also eliminates
    the need for central identity management. This offers a *major
    paradigm shift* compared to today's standard web based models
    where a central service authenticates the user for a set of
    services.
    
    With a decentral identity, the user creates keypair based
    identities locally and can identify with the public key component
    towards any service (s)he registers the identity with. The same
    identity can easily be used with multiple services, and the user
    can prove to each service (s)he is in possession of the full
    identity keypair.

    Another key benefit is the user can create multiple identities
    with very minor differences in the input data which create the
    identity, which eliminates the problem of remembering passwords
    and identities for multiple services. The user can create as many
    or few identities as (s)he likes for using with services, and use
    minor variations (even readable) which cause the identities to
    appear completely different. To an external party it will be
    impossible to detect that multiple identities have been created
    from (almost) the same input data.
