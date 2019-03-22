# Copyright (C) 2011-2013 Versile AS
#
# This file is part of Versile Python.
#
# Versile Python is free software: you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public License
# as published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""Crypto provider for :term:`X.509` related functionality."""
from __future__ import print_function, unicode_literals

import base64

from versile.internal import _b2s, _s2b, _vexport, _pyver
from versile.common.asn1 import VASN1Null, VASN1OctetString
from versile.common.util import VObjectIdentifier, VBitfield
from versile.common.util import posint_to_bytes, bytes_to_posint
from versile.common.util import encode_pem_block, decode_pem_block
from versile.crypto import VCrypto, VCryptoException, VAsymmetricKey
from versile.crypto.math import mod_inv
from versile.crypto.x509.asn1def.pkcs import RSAPublicKey, RSAPrivateKey
from versile.crypto.x509.asn1def.pkcs import DigestInfo, AlgorithmIdentifier

__all__ = ['VX509Crypto', 'VX509Format']
__all__ = _vexport(__all__)


class VX509Format:
    """Holds encoding types for :class:`X.509` objects."""

    ASN1 = 1
    """:term:`ASN.1` format."""

    DER = 2
    """:term:`ASN.1` :term:`DER`\ -encoded representation"""

    PEM = 3
    """:term:`PEM`\ -encoded :term:`DER`"""

    PEM_BLOCK = 4
    """:term:`PEM`\ -encoding encapsulated within BEGIN/END header"""


class VX509Crypto(VCrypto):
    """Base cryptographic provider for :term:`X.509`\ .

    Can be instantiated as a crypto provider, or functionality can be
    called as class methods.

    """

    @property
    def transforms(self):
        return ('x509_key_export_public', 'x509_key_export_private',
                'x509_key_import_public', 'x509_key_import_private',
                'emsa_pkcs1_v1_5')

    def transform(self, transform_name):
        if transform_name == 'x509_key_export_public':
            return self.export_public_key
        elif transform_name == 'x509_key_export_private':
            return self.export_private_key
        if transform_name == 'x509_key_import_public':
            return self.import_public_key
        elif transform_name == 'x509_key_import_private':
            return self.import_private_key
        elif transform_name == 'emsa_pkcs1_v1_5':
            return self.emsa_pkcs1_v1_5_encode
        else:
            raise NotImplementedError

    @classmethod
    def export_public_key(cls, key, fmt=VX509Format.PEM_BLOCK):
        """Exports a public key in PKCS#1 format.

        :param key: key to export
        :type  key: :class:`versile.crypto.VAsymmetricKey`
        :param fmt: format to export to
        :type  fmt: :class:`VX509Format` constant
        :returns:   exported key data

        Exports an encoding of the key's :term:`ASN.1` representation
        defined by :term:`PKCS#1`\, associated with the PEM header
        'BEGIN RSA PUBLIC KEY'.

        .. note::

            For the X.509 SubjectPublicKeyInfo encoding format (PEM
            header 'BEGIN PUBLIC KEY'), see
            :meth:`export_spki_public_key`\ .

        """
        if not isinstance(key, VAsymmetricKey):
            raise TypeError('Invalid key type')
        if key.cipher_name == 'rsa':
           if key.has_public:
               n, e = key.keydata[:2]

               asn1 = RSAPublicKey().create()
               asn1.append(n, name='modulus')
               asn1.append(e, name='publicExponent')
               if not asn1.validate():
                   raise VCryptoException('ASN.1 structure validation error')

               if fmt == VX509Format.ASN1:
                   return asn1
               der = asn1.encode_der()
               if fmt == VX509Format.DER:
                   return der
               if fmt == VX509Format.PEM:
                   if _pyver == 2:
                       return _s2b(base64.encodestring(_b2s(der)))
                   else:
                       return base64.encodebytes(der)
               elif fmt == VX509Format.PEM_BLOCK:
                   return encode_pem_block(b'RSA PUBLIC KEY', der)
               else:
                   raise VCryptoException('Invalid encoding')
        else:
            raise VCryptoException('Encoding not supported')


    @classmethod
    def export_private_key(cls, key, fmt=VX509Format.PEM_BLOCK):
        """Exports a private key (complete keypair) as PKCS#1.

        :param key: key to export
        :type  key: :class:`versile.crypto.VAsymmetricKey`
        :param fmt: format to export to
        :type  fmt: :class:`VX509Format` constant
        :returns:   exported key data

        Exports an encoding of the key's :term:`ASN.1` representation
        defined by :term:`PKCS#1`\, associated with the PEM header
        'BEGIN RSA PRIVATE KEY'.

        .. note::

            Whereas :term:`VPy` refers to complete keys as 'key
            pairs' and private keys as only the private component of
            the key, private keys in :term:`PKCS#1` refer to the
            complete key - thus the naming convention for this method.

        .. note::

            Exporting to the PKCS#8 key format (PEM header 'BEGIN
            PRIVATE KEY') is not supported.

        """
        if not isinstance(key, VAsymmetricKey):
            raise TypeError('Invalid key type')
        if key.cipher_name == 'rsa':
           if key.has_private:
               n, e, d, p, q = key.keydata
               params = (0, n, e, d, p, q, key._exp1, key._exp2, key._coeff)
               if None in params:
                   raise VCryptoException('X.509 parameters missing from key.')

               asn1 = RSAPrivateKey().create()
               asn1.append(0, name='version')
               asn1.append(n, name='modulus')
               asn1.append(e, name='publicExponent')
               asn1.append(d, name='privateExponent')
               asn1.append(p, name='prime1')
               asn1.append(q, name='prime2')
               asn1.append(key._exp1, name='exponent1')
               asn1.append(key._exp2, name='exponent2')
               asn1.append(key._coeff, name='coefficient')
               if not asn1.validate():
                   raise VCryptoException('ASN.1 structure validation error')

               if fmt == VX509Format.ASN1:
                   return asn1
               der = asn1.encode_der()
               if fmt == VX509Format.DER:
                   return der
               if fmt == VX509Format.PEM:
                   if _pyver == 2:
                       return _s2b(base64.encodestring(_b2s(der)))
                   else:
                       return base64.encodebytes(der)
               elif fmt == VX509Format.PEM_BLOCK:
                   return encode_pem_block(b'RSA PRIVATE KEY', der)
               else:
                   raise VCryptoException('Invalid encoding')
        else:
            raise VCryptoException('Encoding not supported')

    @classmethod
    def import_public_key(cls, data, fmt=VX509Format.PEM_BLOCK,
                          keytype='rsa', crypto=None):
        """Imports a PKCS#1 public key.

        :param data:    keydata to import
        :param fmt:     format to import from
        :type  fmt:     :class:`VX509Format` constant
        :param keytype: key type to import (or None)
        :param keytype: unicode
        :param crypto:  crypto provider (default if None)
        :type  crypto:  :class:`versile.crypto.VCrypto`
        :returns:       imported key
        :rtype:         :class:`versile.crypto.VAsymmetricKey`

        Imports an encoding of the key's :term:`ASN.1` representation
        defined by :term:`PKCS#1`\, associated with the PEM header
        'BEGIN RSA PUBLIC KEY'.

        .. note::

            For the X.509 SubjectPublicKeyInfo encoding format (PEM
            header 'BEGIN PUBLIC KEY'), see
            :meth:`import_spki_public_key`\ .

        """
        crypto = VCrypto.lazy(crypto)
        if fmt == VX509Format.PEM_BLOCK:
            heading, data = decode_pem_block(data)
            if heading == b'RSA PUBLIC KEY':
                if keytype is None:
                    keytype = 'rsa'
                elif keytype != 'rsa':
                    raise VCryptoException('Key type mismatch')
            else:
                raise VCryptoException('Key type not supported')
            fmt = VX509Format.DER
        elif fmt == VX509Format.PEM:
            if keytype != 'rsa':
                raise VCryptoException('Key type not supported')
            if _pyver == 2:
                data = _s2b(base64.decodestring(_b2s(data)))
            else:
                data = base64.decodebytes(data)
            fmt = VX509Format.DER
        if fmt == VX509Format.DER:
            asn1key, len_read = RSAPublicKey().parse_der(data)
            if len_read != len(data):
                raise VCryptoException('Public Key DER data overflow')
            data = asn1key
            fmt = VX509Format.ASN1
        if fmt == VX509Format.ASN1:
            if keytype != 'rsa':
                raise VCryptoException('Key type not supported')
            n = data.modulus.native()
            e = data.publicExponent.native()
            if not 0 < e < n:
                raise VCryptoException('Invalid key parameters')
            key_params = (n, e, None, None, None)
            return crypto.num_rsa.key_factory.load(key_params)

    @classmethod
    def import_private_key(cls, data, fmt=VX509Format.PEM_BLOCK,
                          keytype='rsa', crypto=None):
        """Imports a PKCS#1 private key (i.e. a complete keypair).

        :param data:    keydata to import
        :param fmt:     format to import from
        :type  fmt:     :class:`VX509Format` constant
        :param keytype: key type to import (or None)
        :param keytype: unicode
        :param crypto:  crypto provider (default if None)
        :type  crypto:  :class:`versile.crypto.VCrypto`
        :returns:       imported key
        :rtype:         :class:`versile.crypto.VAsymmetricKey`

        Imports an encoding of the key's :term:`ASN.1` representation
        defined by :term:`PKCS#1`\, associated with the PEM header
        'BEGIN RSA PRIVATE KEY'.

        .. note::

            Whereas :term:`VPy` refers to complete keys as 'key
            pairs' and private keys as only the private component of
            the key, private keys in :term:`PKCS#1` refer to the
            complete key - thus the naming convention for this method.

        .. note::

            Importing from the PKCS#8 PrivateKeyInfo encoding format
            (PEM header 'BEGIN PRIVATE KEY') is not supported.

        """
        crypto = VCrypto.lazy(crypto)
        if fmt == VX509Format.PEM_BLOCK:
            heading, data = decode_pem_block(data)
            if heading == b'RSA PRIVATE KEY':
                if keytype is None:
                    keytype = 'rsa'
                elif keytype != 'rsa':
                    raise VCryptoException('Key type mismatch')
            else:
                raise VCryptoException('Key type not supported')
            fmt = VX509Format.DER
        elif fmt == VX509Format.PEM:
            if keytype != 'rsa':
                raise VCryptoException('Key type not supported')
            if _pyver == 2:
                data = _s2b(base64.decodestring(_b2s(data)))
            else:
                data = base64.decodebytes(data)
            fmt = VX509Format.DER
        if fmt == VX509Format.DER:
            asn1key, len_read = RSAPrivateKey().parse_der(data)
            if len_read != len(data):
                raise VCryptoException('Public Key DER data overflow')
            data = asn1key
            fmt = VX509Format.ASN1
        if fmt == VX509Format.ASN1:
            if keytype != 'rsa':
                raise VCryptoException('Key type not supported')
            data = data.native(deep=True)
            version, n, e, d, p, q, exp1, exp2, coeff = data[:9]
            for _param in (e, d, p, q, exp1, exp2, coeff):
                if not 0 < _param < n:
                    raise VCryptoException('Invalid key parameter(s)')
            key_params = (n, e, d, p, q)
            return crypto.num_rsa.key_factory.load(key_params)

    @classmethod
    def export_spki_public_key(cls, key, fmt=VX509Format.PEM_BLOCK):
        """Exports a X.509 SPKI public key.

        :param key: key to export
        :type  key: :class:`versile.crypto.VAsymmetricKey`
        :param fmt: format to export to
        :type  fmt: :class:`VX509Format` constant
        :returns:   exported key data

        Exports an encoding of the key's :term:`ASN.1` representation
        defined by X.509 SubjectPublicKeyInfo encoding format,
        associated with the PEM header 'BEGIN PUBLIC KEY'.

        .. note::

            For the :term:`PKCS#1`\ encoding format (PEM header 'BEGIN
            RSA PUBLIC KEY'), see :meth:`export_public_key`\ .

        """
        if not isinstance(key, VAsymmetricKey):
            raise TypeError('Invalid key type')
        if key.cipher_name != 'rsa':
            raise VCryptoException('Encoding not supported')
        if key.has_public:
            n, e = key.keydata[:2]

            # Create spki structure
            from versile.crypto.x509.asn1def.cert import SubjectPublicKeyInfo
            asn1 = SubjectPublicKeyInfo().create()
            # - algorithm
            alg = AlgorithmIdentifier().create()
            _alg_id = VObjectIdentifier(1, 2, 840, 113549, 1, 1, 1)
            alg.append(_alg_id, name='algorithm')
            alg.append(VASN1Null(), name='parameters')
            asn1.append(alg, name='algorithm')
            # - keydata
            spk = cls.export_public_key(key, fmt=VX509Format.DER)
            spk = VBitfield.from_octets(spk)
            asn1.append(spk, name='subjectPublicKey')

            if not asn1.validate():
                raise VCryptoException('ASN.1 structure validation error')

            if fmt == VX509Format.ASN1:
                return asn1
            der = asn1.encode_der()
            if fmt == VX509Format.DER:
                return der
            if fmt == VX509Format.PEM:
                if _pyver == 2:
                    return _s2b(base64.encodestring(_b2s(der)))
                else:
                    return base64.encodebytes(der)
            elif fmt == VX509Format.PEM_BLOCK:
                return encode_pem_block(b'PUBLIC KEY', der)
            else:
                raise VCryptoException('Invalid encoding')

    @classmethod
    def import_spki_public_key(cls, data, fmt=VX509Format.PEM_BLOCK,
                               keytype='rsa', crypto=None):
        """Imports a X.509 SPKI public key.

        :param data:    keydata to import
        :param fmt:     format to import from
        :type  fmt:     :class:`VX509Format` constant
        :param keytype: key type to import (or None)
        :param keytype: unicode
        :param crypto:  crypto provider (default if None)
        :type  crypto:  :class:`versile.crypto.VCrypto`
        :returns:       imported key
        :rtype:         :class:`versile.crypto.VAsymmetricKey`

        Imports an encoding of the key's :term:`ASN.1` representation
        defined by X.509 SubjectPublicKeyInfo encoding format,
        associated with the PEM header 'BEGIN PUBLIC KEY'.

        .. note::

            For the :term:`PKCS#1`\ encoding format (PEM header 'BEGIN
            RSA PUBLIC KEY'), see :meth:`import_public_key`\ .

        """
        crypto = VCrypto.lazy(crypto)
        if fmt == VX509Format.PEM_BLOCK:
            heading, data = decode_pem_block(data)
            if heading == b'PUBLIC KEY':
                if keytype is None:
                    keytype = 'rsa'
                elif keytype != 'rsa':
                    raise VCryptoException('Key type mismatch')
            else:
                raise VCryptoException('Key type not supported')
            fmt = VX509Format.DER
        elif fmt == VX509Format.PEM:
            if keytype != 'rsa':
                raise VCryptoException('Key type not supported')
            if _pyver == 2:
                data = _s2b(base64.decodestring(_b2s(data)))
            else:
                data = base64.decodebytes(data)
            fmt = VX509Format.DER
        if fmt == VX509Format.DER:
            from versile.crypto.x509.asn1def.cert import SubjectPublicKeyInfo
            spki, len_read = SubjectPublicKeyInfo().parse_der(data)
            if len_read != len(data):
                raise VCryptoException('Public Key DER data overflow')
            data = spki
            fmt = VX509Format.ASN1
        if fmt == VX509Format.ASN1:
            if keytype != 'rsa':
                raise VCryptoException('Key type not supported')
            spki = data.native(deep=True)
            _alg, keydata = spki

            # Verify supported key type
            alg, _params = _alg
            if alg != VObjectIdentifier(1, 2, 840, 113549, 1, 1, 1):
                    raise VCryptoException('Unsupported key algorithm')

            # Import key from embedded DER data
            pub_key = cls.import_public_key(keydata.as_octets(),
                                            VX509Format.DER)
            return pub_key

    @classmethod
    def emsa_pkcs1_v1_5_encode(cls, msg, enc_len, hash_cls):
        """Encodes an EMSA-PKCS1-v1_5-ENCODE message digest.

        :param msg:      binary message to encode
        :type  msg:      bytes
        :param enc_len:  length of encoded message
        :type  enc_len:  int
        :param hash_cls: hash class for message hashing
        :type  hash_cls: :class:`versile.crypto.VHash`
        :returns:        encoded message of length *enc_len*
        :rtype:          bytes
        :raises:         :exc:`versile.crypto.VCryptoException`

        See :term:`PKCS#1` for details. When a strong hash function is
        used, this method produces an encoded representation of *msg*
        which is suitable for digital signatures.

        An exception is raised if the encoding cannot be made
        (typically because the message does not fit inside a bytes
        object of length *enc_len*\ due to the length of *hash_cls*
        hash method digests).

        """
        hasher = hash_cls(msg)
        der = DigestInfo().create()
        alg_id = hash_cls.oid()
        if not alg_id:
            raise VCryptoException('Hash algorithm not supported')
        seq = AlgorithmIdentifier().create()
        seq.append(alg_id, name='algorithm')
        seq.append(VASN1Null(), name='parameters')
        der.append(seq, name='digestAlgorithm')
        der.append(VASN1OctetString(hasher.digest()), name='digest')
        if not der.validate():
            raise VCryptoException('Internal ASN.1 validation error')
        param_T = der.encode_der()
        pad_len = enc_len - len(param_T) - 3
        if pad_len >= 0:
            param_PS = pad_len*b'\xff'
        else:
            raise VCryptoException('Encoding length too small')
        return b''.join((b'\x00', b'\x01', param_PS, b'\x00', param_T))

    @classmethod
    def rsassa_pkcs1_v1_5_sign(cls, key, hash_cls, msg, crypto=None):
        """Sign message with a RSSA PKCS #1 v1.5 Signature

        :param key:      private key for signing
        :type  key:      :class:`versile.crypto.VAsymmetricKey`
        :param hash_cls: hash type for signature
        :type  hash_cls: :class:`versile.crypto.VHash`
        :param msg:      message to sign
        :type  msg:      bytes
        :param crypto:   crypto provider (default if None)
        :type  crypto:   :class:`versile.crypto.VCrypto`
        :raises:         :exc:`versile.crypto.VCryptoException`
        :returns:        signature
        :rtype:          bytes

        Produces a signature as defined by :term:`PKCS#1`\ . Raises an
        exception if a signature cannot be produced for the
        combination of the provided *key* and *hash_cls*\ .

        .. note::

            Signatures require using a hash method which has an associated
            registered :meth:`versile.crypto.VHash.oid`\ . Also, key length
            must be sufficient to hold signature data.

        """
        crypto = VCrypto.lazy(crypto)

        # Create a digest
        enc_len = len(posint_to_bytes(key.keydata[0]))
        encoder = cls.emsa_pkcs1_v1_5_encode
        digest = bytes_to_posint(encoder(msg, enc_len, hash_cls))

        # Create the signature
        sig = crypto.num_cipher(key.cipher_name).decrypter(key)(digest)
        sig = posint_to_bytes(sig)
        return sig

    @classmethod
    def rsassa_pkcs1_v1_5_verify(cls, key, hash_cls, msg, sig, crypto=None):
        """Verifies an RSSA-PKCS1-v1_5 Signature

        :param key:      public key for sign check
        :type  key:      :class:`versile.crypto.VAsymmetricKey`
        :param hash_cls: hash type for signature
        :type  hash_cls: :class:`versile.crypto.VHash`
        :param msg:      message to verify
        :type  msg:      bytes
        :param sig:      signature to verify against message
        :type  sig:      bytes
        :param crypto:   crypto provider (default if None)
        :type  crypto:   :class:`versile.crypto.VCrypto`
        :returns:        True if signature verifies
        :rtype:          bool

        Verifies a signature as defined by :term:`PKCS#1`\ .

        """
        crypto = VCrypto.lazy(crypto)
        enc_len = len(posint_to_bytes(key.keydata[0]))
        encoder = cls.emsa_pkcs1_v1_5_encode

        # Create digest and convert both sig and digest to integer format
        sig = bytes_to_posint(sig)
        digest = bytes_to_posint(encoder(msg, enc_len, hash_cls))

        # Decipher signature and compare with computed digest
        orig = crypto.num_cipher(key.cipher_name).encrypter(key)(sig)

        return (digest == orig)
