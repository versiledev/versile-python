.. _lib_crypto:

Cryptography
============

This is the API documentation for the :term:`VPy` library of
cryptographic methods.

Crypto Providers
----------------
.. currentmodule:: versile.crypto

Cryptographic methods are provided by :class:`VCrypto` objects which
may implement methods locally or using 3rd party crypto
libraries. :term:`VPy` currently implements two crypto providers, one
local implementation and one 3rd party system.

The local provider :class:`versile.crypto.local.VLocalCrypto` is
implemented by :term:`VPy` as pure-python and does not rely on any 3rd
party libraries, so it is always available to :term:`VPy` as a crypto
provider. However, as the provider is pure-python any methods which
use algorithms that are not provided by the python language or
standard library (such as block ciphers) are significantely slower
than optimized 3rd party alternatives, and is usually not the best
choice when performance matters. Instantiating a local provider is a
trivial operation:

>>> from versile.crypto.local import *
>>> crypto = VLocalCrypto()
>>> crypto.hash_types
(u'sha1', u'sha224', u'sha256', u'sha384', u'sha512', u'md5')

The provider :class:`versile.crypto.pycrypto.PyCrypto` uses the
`PyCrypto <http://pycrypto.org/>`__ library for the underlying
encryption. This 3rd party library is widely available and is
typically available from Linux distribution package repositories.

.. note::

     PyCrypto was only available for python 2.x when this
     documentation was released.

Default Providers
-----------------

A default crypto provider can be registered with the :class:`VCrypto`
class by calling :meth:`VCrypto.set_default`\ , and a registered
default can be retreived with :meth:`VCrypto.default`\ .

The typical and most convenient way to retreive a default crypto
provider is to call :meth:`VCrypto.lazy` which retreives a registered
default provider and lazy-registers a new :class:`VDefaultCrypto`
provider if none is already registered.

>>> from versile.crypto import *
>>> crypto = VCrypto.lazy()
>>> type(crypto)
<class 'versile.crypto.VDefaultCrypto'>

:class:`VDefaultCrypto` which is a default provider which acts as a
proxy (:class:`VProxyCrypto`\ ) for available crypto providers. When
looking up cryptographic methods it searches embedded providers in a
defined order for an implementation to use. :class:`VDefaultCrypto`
first looks for supported 3rd party providers and uses a local
provider as a fallback.

Hash Functions
--------------

Hash functions are implemented as :class:`VHash` objects. A list of
hash methods supported by a provider can be retreived from
:attr:`VCrypto.hash_types`\ . A :class:`VHash` implementing a hash
methods can be instantiated by calling :meth:`VCrypto.hash_cls`\
. :class:`VCrypto` also supports getattribute overloading so a hash
method can be created by referring to it as an attribute using the
hash method name. Below is an example how to retreive a class
implementing SHA1:

>>> from versile.crypto.local import VLocalCrypto
>>> crypto = VLocalCrypto()
>>> crypto.hash_types
(u'sha1', u'sha224', u'sha256', u'sha384', u'sha512', u'md5')
>>> crypto.hash_cls(u'sha1')
<class 'versile.crypto.local.HashCls'>
>>> # This is equivalent to the previous statement
... crypto.sha1
<class 'versile.crypto.local.HashCls'>

Data is fed to a hash method with :meth:`VHash.update`\ . An initial
set of data can also be passed to the Hash method constructor. A
digest of all data that has been fed can be generated with
:meth:`VHash.digest`\ . Below is a simple example:

>>> from versile.crypto.local import VLocalCrypto
>>> crypto = VLocalCrypto()
>>> hash_cls = crypto.sha1
>>> h = hash_cls()
>>> h.update(b'Dazed and Confused')
>>> h.digest()
'\xef+\xfc\xb3WS\x85\xd3\xbd{\x0fp\xbe\xa6\xe5#\x9bo\x16\xd7'
>>> # Equivalent to the above
... h2 = hash_cls(b'Dazed ')
>>> h2.update(b'and Confused')
>>> h2.digest()
'\xef+\xfc\xb3WS\x85\xd3\xbd{\x0fp\xbe\xa6\xe5#\x9bo\x16\xd7'
>>> # Or as a 1-liner
... crypto.sha1(b'Dazed and Confused').digest()
'\xef+\xfc\xb3WS\x85\xd3\xbd{\x0fp\xbe\xa6\xe5#\x9bo\x16\xd7'

.. _lib_block_ciphers:

Block Ciphers
-------------

Block ciphers are implemented as :class:`VBlockCipher` objects. A list
of ciphers implemented by a provider can be listed from
:attr:`VCrypto.block_ciphers` and a cipher object can be created with
:attr:`VCrypto.block_cipher`\ . Providers also support creating block
ciphers by using their name as a provider attribute. Below is an
example how to instantiate a blowfish cipher:

>>> from versile.crypto.local import VLocalCrypto
>>> crypto = VLocalCrypto()
>>> crypto.block_ciphers
(u'blowfish', u'blowfish128', u'rsa')
>>> cipher = crypto.block_cipher(u'blowfish')
>>> type(cipher)
<class 'versile.crypto.local._VLocalBlowfish'>
>>> # Equivalent to the above
... cipher2 = crypto.blowfish
>>> type(cipher2)
<class 'versile.crypto.local._VLocalBlowfish'>

The block chaining modes supported by a cipher is available in
:attr:`VBlockCipher.modes`\ .

Cipher Keys
...........

:class:`VBlockCipher.key_factory` provides a :class:`VKeyFactory`
which can be used for importing or generating cipher keys. Factory
methods includes:

* :meth:`VKeyFactory.load` to load a key from keydata format
* :meth:`VKeyFactory.generate` to generate a key from random data
* :meth:`VKeyFactory.import_ascii` to import from an ASCII key format

A key is represented as a :class:`VKey` which is created by a key
factory. The keydata associated with a key can be retreived as
:attr:`VKey.keydata` and can be exported to an ASCII format with
:meth:`VKey.export_ascii`\ . Below is an example how to load a cipher
key for the 'blowfish' cipher:

>>> from versile.crypto.local import VLocalCrypto
>>> crypto = VLocalCrypto()
>>> cipher = crypto.blowfish
>>> key = cipher.key_factory.load(b'tHisISthEKey')
>>> type(key)
<class 'versile.crypto.local._VLocalBlowfishKey'>

Encryption
..........

Encryption and decryption are implemented as :class:`VBlockTransform`
objects which transform blocks of input data into blocks of output
data.

.. note::

   Unless padding is employed, plaintext input blocks (encryption)
   must align with the block size :meth:`VBlockCipher.blocksize`\ ,
   and ciphertext input blocks (decryption) must align with
   :meth:`VBlockCipher.c_blocksize`\ .

:class:`VBlockTransform` encryption transforms can be generated from a
block cipher with :meth:`VBlockCipher.encrypter`\ . Similarly,
decryption transforms can be generated with
:meth:`VBlockCipher.decrypter`\ . Below is a simple example of
encryption and decryption:

>>> from versile.crypto.local import VLocalCrypto
>>> crypto = VLocalCrypto()
>>> cipher = crypto.blowfish
>>> key = cipher.key_factory.load(b'tHisISthEKey')
>>> cipher.modes
(u'cbc', u'ofb')
>>> iv = b'\x00'*cipher.blocksize()
>>> plaintext = b'Platform' # Plaintext 8 bytes, which is the blocksize
>>> enc = cipher.encrypter(key, iv=iv, mode=u'cbc')
>>> ciphertext = enc(plaintext)
>>> ciphertext
'j\xda\x99\x9a(\xaf\xea\x9d'
>>> dec = cipher.decrypter(key, iv=iv, mode=u'cbc')
>>> recovered = dec(ciphertext)
>>> recovered
'Platform'

Asymmetric Ciphers
------------------

An asymmetric cipher (as used in this context) is a cipher which uses
different keys for encryption and decryption. This asymmetry is the
basis for public-key crypto systems.

:term:`VPy` implements the asymmetric RSA public-key cipher. RSA
defines inverse number transform operating on sets {0, 1, ..., N-1} of
non-negative integers. RSA is available as a number transform, and
:term:`VPy` also defines a scheme for using it as a block transform
operating on byte data (examples on this further down).

Number ciphers supported by a provider are listed in
:attr:`VCrypto.num_ciphers` and can be instantiated as a
:class:`VNumCipher` with :meth:`VCrypto.num_cipher`\ .

.. warning::

    A number cipher should not be instantiated via attribute name
    aliasing on the provider, as this would instead generate a block
    cipher version of the number cipher. Use
    :meth:`VCrypto.num_cipher`\ .

Below is an example of instantiating an RSA cipher:

>>> from versile.crypto.local import VLocalCrypto
>>> crypto = VLocalCrypto()
>>> crypto.num_ciphers
(u'rsa',)
>>> cipher = crypto.num_cipher(u'rsa')
>>> type(cipher)
<class 'versile.crypto.local._VLocalRSANumCipher'>

Keys
....

Keys and key factories have a similar interfaces as
:ref:`lib_block_ciphers`\ . RSA keys are asymmetric and inherit
:class:`VAsymmetricKey`\ . A full key consists of both a public
component and a private component. Typically the private component
(and the full key pair) is kept secret, whereas the public component
is made available to other parties. The public key component of a key
is :attr:`VAsymmetricKey.public` and the private key component is
:attr:`VAsymmetricKey.private`\ .

.. warning::

   Using secure keypairs is critical for RSA security. This includes a
   *good source of random data* for creating keys, sufficiently robust
   *primality tests*, and a key of *sufficient key length*\ . Please
   refer to texts on RSA public key encryption for details.

Below is a simple example of loading an RSA key.

>>> from versile.crypto.local import VLocalCrypto
>>> crypto = VLocalCrypto()
>>> rsa = crypto.num_cipher(u'rsa')
>>> # Very small cryptographically insecure key used for demo purposes
... keydata = (718546788653400655712839, 65537, 134210159755337038488281)
>>> keydata += (838440040387, 857004381997)
>>> key = rsa.key_factory.load(keydata)
>>> print(key.export_ascii().strip())        #doctest: +NORMALIZE_WHITESPACE
-----BEGIN VERSILE RSA KEY PAIR-----
/wGYKH/c6DhNBNFQ+P8K/wEca4weZZPK7uHi+8M267bM+8eJcRY2
-----END VERSILE RSA KEY PAIR-----
>>> public_key = key.public
>>> print(public_key.export_ascii().strip()) #doctest: +NORMALIZE_WHITESPACE
-----BEGIN VERSILE RSA PUBLIC KEY-----
/wGYKH/c6DhNBNFQ+P8K
-----END VERSILE RSA PUBLIC KEY-----

Number Cipher
.............

Number encryption and decryption are implemented as
:class:`VNumTransform` objects. Note that the transformed numbers must
be non-negative integers that are smaller in value than the modulus of
the RSA keypair. The maximum value that can be transformed is
:class:`VNumTransform.max_number`\ .

Below is an example of encryption and decryption:

>>> from versile.crypto.local import VLocalCrypto
>>> crypto = VLocalCrypto()
>>> rsa = crypto.num_cipher(u'rsa')
>>> # Very small cryptographically insecure key used for demo purposes
... keydata = (718546788653400655712839, 65537, 134210159755337038488281)
>>> keydata += (838440040387, 857004381997)
>>> key = rsa.key_factory.load(keydata)
>>> enc = rsa.encrypter(key)
>>> # Notice this equals the key's N value minus 1
... enc.max_number
718546788653400655712838L
>>> encrypted = enc(42)
>>> encrypted
61348330318669279811463L
>>> dec = rsa.decrypter(key)
>>> decrypted = dec(encrypted)
>>> decrypted
42L

Block Cipher
............

Number ciphers operating on inteegr sets {0, 1, ..., N-1} can be
converted into block ciphers by interpreting blocks of data as a
number. The maximum block size depends on the *N* value of the key and
ciphertext blocks will normally be one byte longer than plaintext
blocks.

A number cipher is converted into a block cipher by calling
:meth:`VNumCipher.block_cipher`\ . Alternatively, using the number
cipher name as an attribute on a crypto provider will instantiate the
associated block cipher. See :ref:`lib_block_ciphers` for general info
about block ciphers.

Below is an example of RSA block cipher encryption and decryption:

>>> from versile.crypto.local import VLocalCrypto
>>> from versile.crypto.rand import VUrandom
>>> crypto = VLocalCrypto()
>>> rsa = crypto.num_cipher(u'rsa').block_cipher()
>>> type(rsa)
<class 'versile.crypto.algorithm.numblock.VNumBlockCipher'>
>>> # Equivalent to the above
... rsa = crypto.rsa
>>> type(rsa)
<class 'versile.crypto.algorithm.numblock.VNumBlockCipher'>
>>> key = rsa.key_factory.generate(VUrandom(), 512//8)
>>> rsa.modes
(u'cbc',)
>>> rsa.blocksize(key)
53
>>> iv=rsa.blocksize(key)*b'\x00'
>>> plaintext = rsa.blocksize(key)*b'z'
>>> plaintext
'zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz'
>>> enc = rsa.encrypter(key, iv=iv)
>>> ciphertext = enc(plaintext)
>>> len(ciphertext)
64
>>> dec = rsa.decrypter(key, iv=iv)
>>> recovered = dec(ciphertext)
>>> recovered
'zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz'

Data Integrity
--------------
.. currentmodule:: versile.crypto.algorithm.message

Encryption with the appropriate chain modes protects plaintext from
eavesdropping. It does however not protect from attacks involving
tampering with ciphertext, which causes decoding to return different
data from the original plaintext, and which can cause information
about the plaintext to leak and worst-case enable a 3rd party to learn
how to decode the ciphertext.

In order to protect against and tampering, plaintext must be wrapped
in a format which includes checksum validation or similar mechanisms
which will not resolve correctly (with near-100% probability) if the
ciphertext has been changed. :term:`VCA` defines a plaintext message
format for data integrity validation which is implemented by the
:mod:`versile.crypto.algorithm.message` module.

:class:`VMessageEncrypter` sets up as a wrapper around a
:class:`versile.crypto.VBlockTransform`\ , encapsulating plaintext in
the standard message format before it gets encrypted. It applies a
number generator for adding required padding to align message length
with cipher block sizes so that messages of any length can be
encrypted.

Similarly, :class:`VMessageDecrypter` sets up as a wrapper around a
:class:`versile.crypto.VBlockTransform` for decryption, which
reconstructs plaintext from a message-encoded format and validates any
decrypted plaintext provided as output by the message decrypter has
not been tampered with.

.. note::

    Message encrypters and decrypters can also be generated directly
    from a block cipher object by using
    :class:`versile.crypto.VBlockCipher.msg_encrypter` and
    :class:`versile.crypto.VBlockCipher.msg_decrypter`\ .

Below is an example of message encryption and decryption:

>>> from versile.crypto.local import VLocalCrypto
>>> from versile.crypto.rand import VConstantGenerator
>>> crypto = VLocalCrypto()
>>> cipher = crypto.blowfish
>>> key = cipher.key_factory.load(b'tHisISthEKey')
>>> msg_hash_cls = crypto.sha1
>>> padder = VConstantGenerator(b'\x00')
>>> plaintext = b'This is great!'
>>> enc = cipher.msg_encrypter(msg_hash_cls, padder, key, mode=u'cbc')
>>> ciphertext = enc(plaintext)
>>> # Show the first bytes of ciphertext
... ciphertext[:10]
'[td~\x96\x1f\xb9\xe4\xe6\x8e'
>>> dec = cipher.msg_decrypter(msg_hash_cls, key, mode=u'cbc')
>>> dec.read(ciphertext)
40
>>> dec.done()
True
>>> dec.result()
'This is great!'

Below we can see an example what can happen if the message has been
tampered with. In this example the ciphertext has corrupted the
internal message data so it is expecting a larger plaintext message
than the data it being fed to the decoder. This causes the decoder not
to provide as a result as the decoder is still waiting for the message
it is expecting to be completed, and no plaintext is provided.

>>> from versile.crypto.local import VLocalCrypto
>>> from versile.crypto.rand import VConstantGenerator
>>> crypto = VLocalCrypto()
>>> cipher = crypto.blowfish
>>> key = cipher.key_factory.load(b'tHisISthEKey')
>>> msg_hash_cls = crypto.sha1
>>> padder = VConstantGenerator(b'\x00')
>>> plaintext = b'This is great!'
>>> enc = cipher.msg_encrypter(msg_hash_cls, padder, key, mode=u'cbc')
>>> ciphertext = enc(plaintext)
>>> tampered_with = chr(ord(ciphertext[0])^0xff) + ciphertext[1:]
>>> dec = cipher.msg_decrypter(msg_hash_cls, key, mode=u'cbc')
>>> dec.read(tampered_with)
40
>>> try:
...     dec.done()
... except Exception as e:
...     print('exception:', e)
...
False

If we modify the above example to keep feeding the decoder data until
it has enough information to validate the internal message, the
corrupted data will cause the message not to validate (with near 100%
probability), and an exception is raised. Once again no plaintext is
provided by the decoder that has not been validated.

>>> from versile.crypto.local import VLocalCrypto
>>> from versile.crypto.rand import VConstantGenerator
>>> crypto = VLocalCrypto()
>>> cipher = crypto.blowfish
>>> key = cipher.key_factory.load(b'tHisISthEKey')
>>> msg_hash_cls = crypto.sha1
>>> padder = VConstantGenerator(b'\x00')
>>> plaintext = b'This is great!'
>>> enc = cipher.msg_encrypter(msg_hash_cls, padder, key, mode=u'cbc')
>>> ciphertext = enc(plaintext)
>>> tampered_with = chr(ord(ciphertext[0])^0xff) + ciphertext[1:]
>>> tampered_with += 65535*b'\x00'
>>> dec = cipher.msg_decrypter(msg_hash_cls, key, mode=u'cbc')
>>> dec.read(tampered_with)
58176
>>> try:
...     dec.done()
... except Exception as e:
...     print('exception:', e)
...
('exception:', VCryptoException(u'Message failed to verify',))

Decentral Identities
--------------------
.. currentmodule:: versile.crypto

Decentral identities are defined by the :term:`VDI` specification. It
provides a standard mechanism for representing an identity as an RSA
keypair where the public key identifies the identity and the private
key component can be used to prove ownership of the
identity. Identities are generated from a set of secret data
(essentially a password plus optional meta-data unique to each
identity).

.. note::

   The decentral identity scheme essentially offers the security
   offered by a public-key based scheme for authentication, combined
   with the convenience of associating the identity to a password
   which is possible to memorize, and mechanisms for creating identity
   variations without having to remember a unique password for each
   service.

:term:`VPy` implements the Decentral (Key) Scheme A defined by the
standard, which is identified as 'dia' and implemented as
:class:`VDecentralIdentitySchemeA`\ .

A 'dia' decentral identity produces a public keypair from secret
passphrase data consisting of three components: *purpose*, *personal*
and *password*. The *purpose* component enables use of the same
*personal* and *password* data for generating different identities,
just by changing this field. Including a *personal* helps protect
against brute-force dictionary attacks by introducing additional
entropy and making it 'personal'. The *password* component protects
the identity and should be long and complex.

.. warning::

   The *password* should typically be minimum 13-14 characters that
   are randomly generated from lower-case letters, upper-case letters
   and numbers when combined with *personal* information, or 15-16
   random characters. If the password is not randomly generated then
   it must be much longer to collect the same amount of entropy. See
   the :term:`VDI` specifications for a discussion of security vs
   password length.

   A sufficiently strong password is critical. Though computionally
   expensive, for simple passwords the scheme is subject to
   brute-force attacks or dictionary attacks. The trade-off is the
   user must accept memorizing a few (as few as the user wants, though
   at least one) very complex passwords, in return for a highly secure
   set of identities which can be used with multiple services.

Below is an example of generating an identity (effectively an RSA
keypair) from input data. Note that 512 bit identities are not
considered 'secure', and identities should probably be minimum 1024
bits.

>>> from versile.crypto import VCrypto
>>> c = VCrypto.lazy()
>>> bits = 512 # Note 512 bits is not enough for a secure identity
>>> purpose = 'example.com'
>>> personal = 'I love Monty Python movies'
>>> password = 'jrWd9j4Lgmf9FD'
>>> identity = c.dia(bits, purpose, personal, password)
>>>
>>> from versile.crypto.x509 import VX509Crypto
>>> exported_id = VX509Crypto.export_public_key(identity.public)
>>> print(exported_id) #doctest: +NORMALIZE_WHITESPACE
-----BEGIN RSA PUBLIC KEY-----
MEgCQQDCa6SwHqZji29iYbakPbF4GTnNMkmbzMA8QS6k2zKoVPq2e4V7WrfUwmBLddcQ31T/et5d
qprsOU/4mXwbTpRNAgMBAAE=
-----END RSA PUBLIC KEY-----

.. note::

    There is a trade-off with number of bits vs. performance as
    identity generation is a costly process which increases
    exponentially with key length, and which needs to be performed
    every time the identity is generated from the secret protecting
    the identity.

X.509
-----
.. currentmodule:: versile.crypto.x509

:term:`X.509` (and :term:`PKCS#1`\ ) are central to many of todays'
most important standards for public key infrastructure and secure
communication such as :term:`TLS`\ . The :term:`VTS` standard was also
designed to use :term:`X.509` certificates to enable similar APIs and
usage as :term:`TLS`\ .

The module :mod:`versile.crypto.x509` includes a crypto provider
:class:`VX509Crypto` which implements some algorithms used by
:term:`X.509` including :term:`PKCS#1` key import/export, message
digest and signatures. Below is an example of performing RSA key
import/export and creating/validating signatures.

>>> from versile.crypto import VCrypto
>>> from versile.crypto.x509 import VX509Crypto, VX509Format
>>> # Import RSA keypair
... key_pem_data = """
... -----BEGIN RSA PRIVATE KEY-----
... MIIBOgIBAAJBAJJ44kaPQzDWsZXlHqbDT1xFBOQQ1Ty1EO9l1GCNKd1QhTclRMwN9pNANCeBQYJ2
... 7bE/gKZ39NMQ1vsnErp2sJECAwEAAQJBAIiDZBlxQqVNJBxZfBTfKaMMrL9HNQasl0kYdjU6vA8I
... o2hamapxjLZho0i7+Fs0dYHRFxbmfWfL7TUG3a0JtXECIQCid3Gm5EhNSzmMEJNyyNH3UVRkHMG5
... OxTTFXhhCADBFQIhAObMKoUTpxHBLJEnbJxOCYfID9sRY8Qtlht0tI37APiNAiBmjS7YQdDBuXIh
... z3TDR7ABhPzYFK7T1U9Xzn2mAf834QIgNHG4R70LfbFTmzhGKc5hxATl9XWiIfXp4htG2+xpcBEC
... ICfax59efa52z/uKBAJ8QQkdKbmvOx5NDfabJbIJ6lbK
... -----END RSA PRIVATE KEY-----
... """
>>> key_pem_data = key_pem_data.strip()
>>> key = VX509Crypto.import_private_key(key_pem_data, fmt=VX509Format.PEM_BLOCK)
>>> type(key)
<class 'versile.crypto.pycrypto._PyRSAKey'>
>>> # Export the key's public key component
... print(VX509Crypto.export_public_key(key.public, fmt=VX509Format.PEM_BLOCK)) #doctest: +NORMALIZE_WHITESPACE
-----BEGIN RSA PUBLIC KEY-----
MEgCQQCSeOJGj0Mw1rGV5R6mw09cRQTkENU8tRDvZdRgjSndUIU3JUTMDfaTQDQngUGCdu2xP4Cm
d/TTENb7JxK6drCRAgMBAAE=
-----END RSA PUBLIC KEY-----
>>> # Create and verify an RSSA PKCS#1 v1.5 signature
... msg = b'None shall pass'
>>> sha1 = VCrypto.lazy().sha1
>>> signature = VX509Crypto.rsassa_pkcs1_v1_5_sign(key, sha1, msg)
>>> signature[:(len(signature)/2)]
'\x80x\x01Fcz@\\wD\x9d\xa1]R\x1f\\\x84\xb0\xbc\x17\xd8\x8fK\xc9eI\xf0\xae~\x9fH]'
>>> signature[(len(signature)/2):]
'\xe7vq\xd5\x85\xb5dx\x8f\x9e<N\x95\x0e\xfbS4\xca\xa5\xbb(;\xff]\x146n\xe1\xc4\xbflO'
>>> VX509Crypto.rsassa_pkcs1_v1_5_verify(key, sha1, msg, signature)
True
>>> signature = b'\x00' + signature[1:]
>>> VX509Crypto.rsassa_pkcs1_v1_5_verify(key, sha1, msg, signature)
False

Internally the :term:`X.509` framework uses :mod:`versile.common.asn1`
for working with ASN.1 data and uses data structures defined in
:mod:`versile.crypto.x509.asn1def.cert` and
:mod:`versile.crypto.x509.asn1def.pkcs`\ .

Certificates
------------
.. currentmodule:: versile.crypto.x509.cert

:term:`X.509` certificates are defined by :rfc:`5280` . Certificates
enable an *issuer* to certify the *identity* of a *subject*\ , the
subject's possession of a *subject key*\ , and rights granted to the
subject by the issuer (e.g. Certificate Authority rights to certify
other subjects).

Certificate trust chains are used e.g. in :term:`TLS`\ , and web
browsers are typically configured to only allow interaction with web
servers which provide a chain of certificates which can be traced back
to a known trusted root certificate of a Certificate Authority.

:class:`VX509Certificate` implements :term:`X.509` certificate
capabilities. It is not a complete implementation of the :term:`X.509`
standard, but it implements a significant set of functionality
allowing it to be used in common use cases. Certificates can be
created with :meth:`VX509Certificate.create`\ . They can also be
created by first creating a :class:`VX509CertificationRequest` and then
signing the request.

Below is an example of creating a self-signed Root CA certificate,
creating a certification request for a second certificate and signing
that second certificate by the Root CA.

>>> import datetime
>>> from versile.crypto import VCrypto
>>> from versile.crypto.x509 import VX509Crypto, VX509Format
>>> from versile.crypto.x509.cert import VX509Certificate, VX509Name
>>> from versile.crypto.x509.cert import VX509CertificationRequest
>>> # Generate self-signed Root CA certificate
... pem = """
... -----BEGIN RSA PRIVATE KEY-----
... MIIBOgIBAAJBAJJ44kaPQzDWsZXlHqbDT1xFBOQQ1Ty1EO9l1GCNKd1QhTclRMwN9pNANCeBQYJ2
... 7bE/gKZ39NMQ1vsnErp2sJECAwEAAQJBAIiDZBlxQqVNJBxZfBTfKaMMrL9HNQasl0kYdjU6vA8I
... o2hamapxjLZho0i7+Fs0dYHRFxbmfWfL7TUG3a0JtXECIQCid3Gm5EhNSzmMEJNyyNH3UVRkHMG5
... OxTTFXhhCADBFQIhAObMKoUTpxHBLJEnbJxOCYfID9sRY8Qtlht0tI37APiNAiBmjS7YQdDBuXIh
... z3TDR7ABhPzYFK7T1U9Xzn2mAf834QIgNHG4R70LfbFTmzhGKc5hxATl9XWiIfXp4htG2+xpcBEC
... ICfax59efa52z/uKBAJ8QQkdKbmvOx5NDfabJbIJ6lbK
... -----END RSA PRIVATE KEY-----
... """
>>> pem = pem.strip()
>>> root_key = VX509Crypto.import_private_key(pem)
>>> subject = VX509Name(organizationName=u'The Root CA Company')
>>> csr = VX509CertificationRequest.create(subject, root_key)
>>> serial = 234987234782
>>> not_before  = datetime.datetime(2010, 01, 01)
>>> not_after  = datetime.datetime(2020, 01, 01)
>>> root_cert = csr.self_sign_ca(serial=serial, not_after=not_after,
...                              sign_key=root_key, not_before=not_before)
>>> print(root_cert.export(fmt=VX509Format.PEM_BLOCK)) #doctest: +NORMALIZE_WHITESPACE
-----BEGIN CERTIFICATE-----
MIIBeDCCASKgAwIBAgIFNrZUpd4wDQYJKoZIhvcNAQEFBQAwHjEcMBoGA1UEBgwTVGhlIFJvb3Qg
Q0EgQ29tcGFueTAiGA8yMDEwMDEwMTAwMDAwMFoYDzIwMjAwMTAxMDAwMDAwWjAeMRwwGgYDVQQG
DBNUaGUgUm9vdCBDQSBDb21wYW55MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAJJ44kaPQzDWsZXl
HqbDT1xFBOQQ1Ty1EO9l1GCNKd1QhTclRMwN9pNANCeBQYJ27bE/gKZ39NMQ1vsnErp2sJECAwEA
AaNDMEEwDwYDVR0TAQH/BAUwAwEB/zAdBgNVHQ4EFgQUsdeiw/O1aKlfNxer4yx5X6W89RgwDwYD
VR0PAQH/BAUDAwcGADANBgkqhkiG9w0BAQUFAANBAEHVIxsEy95HfG490SUxklbZZ5POpUDkBiWt
ZVEjTI3//vQ+OuETYNm5KAnvWgCRH31IUKRko575u37gCHYGSzc=
-----END CERTIFICATE-----
>>> # Generate Root-signed certificate
... pem = """
... -----BEGIN RSA PRIVATE KEY-----
... MIIBOQIBAAJBAIj0jH/2AtxnNiLfOT1ojx0yOZB8eG5SjGa+TdXEpvKgNF9pqy00x3irntTXH8tg
... TWyLHd82khgL7oUe23Gc/FkCAwEAAQJAWppOCKlboyu0qMU8PN/bLdl4M5nkojeCIsZq/6ylNYTD
... ZcFMkzL7SkAb/wtdIztLvyMfjrO3HVbNoiWkPl2isQIhAJ5dGBi5QJtKKIElCJZeVIQLDejFXSMe
... +tymV4DxE1HPAiEA3WSFF/0PsmvmZP7onEggvgGIvazs7nuGArmnpLwXoVcCICrmmVKJTQFEk7h4
... qdzibQ7gV8JJRTPwfpEr1uStakhtAiBAQyA64VLAGH/Myw0b5/fRD0Lww5QWeTZh7h/SOmKliwIg
... SCn18UcnxuXgu33Q/9MR/ExWqoNiToc0GFGdu5r46IQ=
... -----END RSA PRIVATE KEY-----
... """
>>> pem = pem.strip()
>>> other_key = VX509Crypto.import_private_key(pem)
>>> subject = VX509Name(organizationName=u'Some ToBeCertified Company')
>>> csr = VX509CertificationRequest.create(subject, other_key)
>>> serial = 93763247234
>>> not_before  = datetime.datetime(2010, 01, 01)
>>> not_after  = datetime.datetime(2020, 01, 01)
>>> other_cert = root_cert.sign(csr=csr, serial=serial, not_after=not_after,
...                             sign_key=root_key, not_before=not_before)
>>> print(other_cert.export(fmt=VX509Format.PEM_BLOCK)) #doctest: +NORMALIZE_WHITESPACE
-----BEGIN CERTIFICATE-----
MIIBXzCCAQmgAwIBAgIFFdS5nIIwDQYJKoZIhvcNAQEFBQAwHjEcMBoGA1UEBgwTVGhlIFJvb3Qg
Q0EgQ29tcGFueTAiGA8yMDEwMDEwMTAwMDAwMFoYDzIwMjAwMTAxMDAwMDAwWjAlMSMwIQYDVQQG
DBpTb21lIFRvQmVDZXJ0aWZpZWQgQ29tcGFueTBcMA0GCSqGSIb3DQEBAQUAA0sAMEgCQQCI9Ix/
9gLcZzYi3zk9aI8dMjmQfHhuUoxmvk3VxKbyoDRfaastNMd4q57U1x/LYE1six3fNpIYC+6FHttx
nPxZAgMBAAGjIzAhMB8GA1UdIwQYMBaAFLHXosPztWipXzcXq+MseV+lvPUYMA0GCSqGSIb3DQEB
BQUAA0EAaHyClgeaGF7JKO6FXvr0Ow+atyyul1PjTGlifl9X3eD9CwWPw6jUfkpAzTmO2Hhfg247
hSnMs2bKltNthgUI8Q==
-----END CERTIFICATE-----

Below is the output of ``openssl x509 -text`` on the exported root
certificate from the example ...

.. code-block:: none

    Certificate:
        Data:
            Version: 3 (0x2)
            Serial Number:
                36:b6:54:a5:de
            Signature Algorithm: sha1WithRSAEncryption
            Issuer: C=The Root CA Company
            Validity
                Not Before: Jan  1 00:00:00 2010 GMT
                Not After : Jan  1 00:00:00 2020 GMT
            Subject: C=The Root CA Company
            Subject Public Key Info:
                Public Key Algorithm: rsaEncryption
                RSA Public Key: (512 bit)
                    Modulus (512 bit):
                        00:92:78:e2:46:8f:43:30:d6:b1:95:e5:1e:a6:c3:
                        4f:5c:45:04:e4:10:d5:3c:b5:10:ef:65:d4:60:8d:
                        29:dd:50:85:37:25:44:cc:0d:f6:93:40:34:27:81:
                        41:82:76:ed:b1:3f:80:a6:77:f4:d3:10:d6:fb:27:
                        12:ba:76:b0:91
                    Exponent: 65537 (0x10001)
            X509v3 extensions:
                X509v3 Basic Constraints: critical
                    CA:TRUE
                X509v3 Subject Key Identifier:
                    B1:D7:A2:C3:F3:B5:68:A9:5F:37:17:AB:E3:2C:79:5F:A5:BC:F5:18
                X509v3 Key Usage: critical
                    Certificate Sign, CRL Sign
        Signature Algorithm: sha1WithRSAEncryption
            41:d5:23:1b:04:cb:de:47:7c:6e:3d:d1:25:31:92:56:d9:67:
            93:ce:a5:40:e4:06:25:ad:65:51:23:4c:8d:ff:fe:f4:3e:3a:
            e1:13:60:d9:b9:28:09:ef:5a:00:91:1f:7d:48:50:a4:64:a3:
            9e:f9:bb:7e:e0:08:76:06:4b:37

... and below is the output of ``openssl x509 -text`` on the exported
root-signed certificate.

.. code-block:: none

    Certificate:
        Data:
            Version: 3 (0x2)
            Serial Number:
                15:d4:b9:9c:82
            Signature Algorithm: sha1WithRSAEncryption
            Issuer: C=The Root CA Company
            Validity
                Not Before: Jan  1 00:00:00 2010 GMT
                Not After : Jan  1 00:00:00 2020 GMT
            Subject: C=Some ToBeCertified Company
            Subject Public Key Info:
                Public Key Algorithm: rsaEncryption
                RSA Public Key: (512 bit)
                    Modulus (512 bit):
                        00:88:f4:8c:7f:f6:02:dc:67:36:22:df:39:3d:68:
                        8f:1d:32:39:90:7c:78:6e:52:8c:66:be:4d:d5:c4:
                        a6:f2:a0:34:5f:69:ab:2d:34:c7:78:ab:9e:d4:d7:
                        1f:cb:60:4d:6c:8b:1d:df:36:92:18:0b:ee:85:1e:
                        db:71:9c:fc:59
                    Exponent: 65537 (0x10001)
            X509v3 extensions:
                X509v3 Authority Key Identifier:
                    keyid:B1:D7:A2:C3:F3:B5:68:A9:5F:37:17:AB:E3:2C:79:5F:A5:BC:F5:18

        Signature Algorithm: sha1WithRSAEncryption
            68:7c:82:96:07:9a:18:5e:c9:28:ee:85:5e:fa:f4:3b:0f:9a:
            b7:2c:ae:97:53:e3:4c:69:62:7e:5f:57:dd:e0:fd:0b:05:8f:
            c3:a8:d4:7e:4a:40:cd:39:8e:d8:78:5f:83:6e:3b:85:29:cc:
            b3:66:ca:96:d3:6d:86:05:08:f1

:class:`VX509CertificateExtension` is a base class for :term:`X.509`
v3 extensions. Supported extensions includes
:class:`VX509BasicConstraint`\ , :class:`VX509SubjectKeyIdentifier`\ ,
:class:`VX509KeyUsage` and :class:`VX509AuthorityKeyIdentifier`\ .

:class:`VX509Name` holds a :term:`X.501` distinguished name structure
which is used in certificates to identify subjects and issuers. Below
are some examples how to use this class.

>>> from versile.crypto.x509.cert import VX509Name
>>> name = VX509Name(organizationName=u'Zed Leppelin')
>>> name
{'2.5.4.6': u'Zed Leppelin'}
>>> name[name.oid('streetAddress')] = u'Stairway St. 100'
>>> name[name.oid('countryName')] = u'GB'
>>> name
{'2.5.4.9': u'Stairway St. 100', '2.5.4.10': u'GB', '2.5.4.6': u'Zed Leppelin'}


Math functions
--------------
.. currentmodule:: versile.crypto.math

The :mod:`versile.crypto.math` module includes a set of mathematical
functions which are used in various cryptographic methods:

+----------------------+-----------------------------------------------------+
| Function             | Description                                         |
+======================+=====================================================+
| :func:`euler_sieve`  | Sieve of Erathosthenes, filter prime numbers        |
+----------------------+-----------------------------------------------------+
| :func:`miller_rabin` | Miller-Rabin primality test                         |
+----------------------+-----------------------------------------------------+
| :func:`is_prime`     | Derived primality test                              |
+----------------------+-----------------------------------------------------+
| :func:`egcd`         | Extended Euclidian Alg. for greatest common divisor |
+----------------------+-----------------------------------------------------+
| :func:`mod_inv`      | Modular inverse                                     |
+----------------------+-----------------------------------------------------+


Module APIs
-----------

Crypto
......
Module API for :mod:`versile.crypto`

.. automodule:: versile.crypto
    :members:
    :show-inheritance:

Local Provider
..............
Module API for :mod:`versile.crypto.local`

.. automodule:: versile.crypto.local
    :members:
    :show-inheritance:

PyCrypto Provider
.................
Module API for :mod:`versile.crypto.pycrypto`

.. automodule:: versile.crypto.pycrypto
    :members:
    :show-inheritance:

X.509 Crypto
............
Module API for :mod:`versile.crypto.x509`

.. automodule:: versile.crypto.x509
    :members:
    :show-inheritance:

X.509 Certificates
..................
Module API for :mod:`versile.crypto.x509.cert`

.. automodule:: versile.crypto.x509.cert
    :members:
    :show-inheritance:

ASN.1 Structures
................
Module API for :mod:`versile.crypto.x509.asn1def.cert` and
:mod:`versile.crypto.x509.asn1def.pkcs`\ .

.. automodule:: versile.crypto.x509.asn1def.cert
    :members:
    :show-inheritance:

.. automodule:: versile.crypto.x509.asn1def.pkcs
    :members:
    :show-inheritance:

Message Format
..............
Module API for :mod:`versile.crypto.algorithm.message`

.. automodule:: versile.crypto.algorithm.message
    :members:
    :show-inheritance:

Math Functions
..............
Module API for :mod:`versile.crypto.math`

.. automodule:: versile.crypto.math
    :members:
    :show-inheritance:
