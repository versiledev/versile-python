.. _glossary:

Glossary
========

.. glossary::

  ASN.1
    `Abstract Syntax Notation One <http://en.wikipedia.org/wiki/Asn.1>`__\ , a    standard for representing, encoding, transmitting, and decoding data.

  DER
    `Distinguished Encoding Rules
    <http://en.wikipedia.org/wiki/Distinguished_Encoding_Rules>`__\ , a
    message-transfer syntax specified by :term:`X.690`

  HMAC
    Hash-based Message Authentication Algorithm. One standard for HMAC is
    defined in :rfc:`2104`\ .

  Object Identifier
    An Object Identifier is an identifier used to name an object in an
    hierarchical namespace (see `wikipedia
    <http://en.wikipedia.org/wiki/Object_identifier>`__\ ).

  PEM
    `Privacy-Enhanced Mail
    <http://en.wikipedia.org/wiki/Base64#Privacy-enhanced_mail>`__\ , which
    defines a base64 encoding of binary data. Used for e.g. storing
    certificates or keys in '.pem files' in a format with BEGIN/END
    delimiters.

  PKCS#1
    `PKCS #1: RSA Cryptography Standard
    <http://www.rsa.com/rsalabs/node.asp?id=2125>`__

  PKCS#10
    `PKCS #10: Certification Request Syntax Standard
    <http://www.rsa.com/rsalabs/node.asp?id=2132>`__

  Public CA
    Certificate Authority credentials (key pair, self-signed root certificate)
    published by `Versile`\ . It can be used when keys/certificates need to
    be transmitted without root CA validation, however the technology used
    (e.g. :term:`TLS`\ ) requires formal validation with a registered root CA.

  Reactor Pattern
      An event handling pattern for handling service requests delivered
      concurrently to a service handler by one or more inputs (see
      `wikipedia <http://en.wikipedia.org/wiki/Reactor_pattern>`__\ )

  TLS
     Transport Layer Security, defined by :rfc:`5246`

  VCA
    The :term:`VP` Versile Crypto Algorithms standard

  VER
    The :term:`VP` Versile Entity Representation standard

  VFE
    The :term:`VP` Versile Fundamental Entities standard

  VEC
    The :term:`VP` Versile Entity Channel standard

  Versile
    See :term:`Versile AS`\ .

  Versile AS
    The company behind :term:`Versile Platform` and :term:`Versile Python`\ .

  Versile Platform
   An open service interaction platform standard.

  Versile Python
    The product documented by this specification.

  VDI
    The :term:`VP` Versile Decentral Identities standard

  VOB
    The :term:`VP` Versile Object Behavior standard

  VOL
    The :term:`VP` Versile ORB Link standard

  VOP
    The :term:`VP` Versile Object Protocol standard, a protocol for
    :term:`VOL` and :term:`VEC` over a negotiated connection byte
    transport (either :term:`VTS`\ , :term:`TLS` or plaintext)

  VP
    :term:`Versile Platform`

  VPy
    :term:`Versile Python`

  VRI
    The :term:`VP` Versile Resource Identifier standard

  VSE
    The :term:`VP` Versile Standard Entities standard

  VTS
    The :term:`VP` Versile Transport Security standard

  VUT
    The :term:`VP` Versile UDP Transport standard

  X.501
    An ITU-T standard for open systems interconnection directory models.

  X.509
    An ITU-T standard for public key infrastructure, single sign-on and
    privilege management infrastructure
    (see `wikipedia <http://en.wikipedia.org/wiki/X.509>`__\ )

  X.680
    Standard for :term:`ASN.1` basic notation

  X.690
    Standard for :term:`ASN.1` encoding rules for Basic Encoding Rules (BER),
    Canonical Encoding Rules (CER) and Distinguished Encoding Rules
    (\ :term:`DER`\ )
