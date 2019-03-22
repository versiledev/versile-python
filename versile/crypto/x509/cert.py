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

"""Implements (a subset of standards for) :term:`X.509` certificates."""
from __future__ import print_function, unicode_literals

import base64
import datetime
from hashlib import sha1

from versile.internal import _b2s, _s2b, _vexport, _pyver
from versile.common.asn1 import VASN1Base, VASN1Definition, VASN1Null
from versile.common.asn1 import VASN1Tag, VASN1Exception, VASN1BitString
from versile.common.util import VObjectIdentifier, VBitfield
from versile.common.util import posint_to_bytes, bytes_to_posint
from versile.common.util import decode_pem_block, encode_pem_block
from versile.crypto import VCryptoException
from versile.crypto.x509 import VX509Crypto, VX509Format
from versile.crypto.x509.asn1def.cert import *
from versile.crypto.x509.asn1def.pkcs import *

__all__ = ['VX509CertificationRequest', 'VX509AuthorityKeyIdentifier',
           'VX509BasicConstraint', 'VX509Certificate',
           'VX509CertificateExtension', 'VX509InvalidSignature',
           'VX509KeyUsage', 'VX509Name', 'VX509SubjectKeyIdentifier']
__all__ = _vexport(__all__)


# SHA1 hash class for internal use in this module
from versile.crypto.local import VLocalCrypto
_mod_sha1_cls = VLocalCrypto().sha1


class VX509InvalidSignature(VCryptoException):
    """Invalid signature exception for a :term:`X.509` certificate."""


class VX509Certificate(object):
    """An :term:`X.509` certificate as specified by :rfc:`5280`\ .

    :param asn1_cert: :term:`ASN.1` certificate data
    :type  asn1_cert: :class:`versile.common.asn1.VASN1Base`

    External code should normally use :meth:`create` to create
    certificate objects, sign a :class:`VX509CertificationRequest`\ ,
    or import from certificate data with :meth:`import_cert`\ .

    """

    def __init__(self, asn1_cert):
        self._cert = asn1_cert
        tbs_cert, sign_alg, sign_val = self._cert

        # Read main certificate data
        # - version
        _version = tbs_cert.version.native()
        self._version = _version.value.native()
        self.__validate_criteria(self._version in (0, 1, 2))
        # - serial
        self._serial = tbs_cert.serialNumber.native()
        # - signature algorithm
        self._sign_alg, tmp = tbs_cert.signature.native()
        self.__validate_criteria(tmp is None)
        self.__validate_type(self._sign_alg, VObjectIdentifier)
        # - issuer
        self._issuer = VX509Name.import_name(tbs_cert.issuer)
        # - validity
        _validity = tbs_cert.validity.native(deep=True)
        self._not_before = _validity[0]
        self._not_after = _validity[1]
        # - subject
        self._subject = VX509Name.import_name(tbs_cert.subject)
        # - subject public key
        _sk_alg, _sk_data = tbs_cert.subjectPublicKeyInfo.native(deep=True)
        _sk_alg, tmp = _sk_alg
        self.__validate_criteria(tmp is None)
        self.__validate_type(_sk_alg, VObjectIdentifier)
        _pkcs_oid = (1, 2, 840, 113549, 1, 1, 1)
        self.__validate_criteria(_sk_alg.oid == _pkcs_oid)
        # [import RSA PKCS #1 v1.5 Key Transport Algorithm]
        _importer = VX509Crypto.import_public_key
        self._subject_key = _importer(_sk_data.as_octets(), VX509Format.DER)

        # Read optional issuer/subject unique id values
        self._issuer_unique = self._subject_unique = None
        if hasattr(tbs_cert, 'issuerUniqueId'):
            self.__validate_criteria(self._version in (1, 2))
            self._issuer_unique = tbs_cert.issuerUniqueId.value.native()
        if hasattr(tbs_cert, 'subjectUniqueId'):
            self.__validate_criteria(self._version in (1, 2))
            self._subject_unique = tbs_cert.issuerUniqueId.value.native()

        # Read certificate extensions
        if hasattr(tbs_cert, 'extensions'):
            self._extensions = list()
            for extension in tbs_cert.extensions.value:
                ext = VX509CertificateExtension.parse_asn1(extension)
                self._extensions.append(ext)
        else:
            self._extensions = tuple()

        # Decode certificate signature
        _sign_alg, tmp = sign_alg.native(deep=True)
        self.__validate_criteria(tmp is None)
        self.__validate_type(_sign_alg, VObjectIdentifier)
        if _sign_alg != self._sign_alg:
            raise VX509InvalidSignature('Signature algorithm mismatch')
        self._sign_val = sign_val.native(deep=True)
        self.__validate_type(self._sign_val, VBitfield)

    def export(self, fmt=VX509Format.PEM_BLOCK):
        """Export the certificate.

        :param fmt:     format to export to
        :type  fmt:     :class:`versile.crypto.x509.VX509Format` constant
        :returns:       exported certificate data

        """
        if fmt == VX509Format.ASN1:
            return self._cert
        der = self._cert.encode_der()
        if fmt == VX509Format.DER:
            return der
        if fmt == VX509Format.PEM:
            if _pyver == 2:
                return _s2b(base64.encodestring(_b2s(der)))
            else:
                return base64.encodebytes(der)
        elif fmt == VX509Format.PEM_BLOCK:
            return encode_pem_block(b'CERTIFICATE', der)
        else:
            raise VCryptoException('Invalid encoding')

    def verify_key(self, key, issuer=None):
        """Verifies the key that was used for signing the certificate.

        :param key:     issuer's public key to validate against
        :param key:     :class:`versile.crypto.VAsymmetricKey`
        :param issuer:  issuer data (or None)
        :type  issuer:  :class:`VX509Name`
        :returns:       True if certificate was signed with *key*
        :rtype:         bool
        :raises:        :exc:`versile.crypto.VCryptoException`

        If *issuer* is not None, then the certificate's issuer data is
        compared with the provided *issuer* data. The method only
        returns True if the certificate's signature validates with
        *key* and the certificate's issuer data matches *issuer* \ .

        """
        if self._sign_alg == VObjectIdentifier(1, 2, 840, 113549, 1, 1, 5):
            # Validate with 'RSASSA PKCS #1 v1.5 Verify'
            tbs_cert = self._cert[0]
            msg = tbs_cert.encode_der()
            v_func = VX509Crypto.rsassa_pkcs1_v1_5_verify
            signature = self._sign_val.as_octets()
            verifies = v_func(key, _mod_sha1_cls, msg, signature)
            if not verifies:
                return False
            else:
                if issuer is None:
                    return True
                if set(issuer.keys()) != set(self._issuer.keys()):
                    return False
                for key in issuer:
                    if issuer[key] != self._issuer[key]:
                        return False
                return True
        else:
            raise VCryptoException('Signature method not supported')

    def certified_by(self, certificate, verify_time=True, tstamp=None,
                     x509_ext=True, strict=True):
        """Returns True if provided certificate validates this certificate.

        :param certificate: certificate for issuer of this certificate
        :type  certificate: :class:`VX509Certificate`
        :param verify_time: if True verify for *tstamp*
        :type  verify_time: bool
        :param tstamp:      timestamp to verify if verifying (or None)
        :type  tstamp:      :class:`datetime.datetime`
        :param x509_ext:    if True validate appropriate X.509 extensions
        :type  x509_ext:    bool
        :param strict:      if True validate issuer has CA signature permission
        :type  strict:      bool
        :returns:           True if certified
        :rtype:             bool

        If *tstamp* is None then the system's current UTC time is used.

        """
        _cert = certificate

        # Verify match with issuer information and key
        if not (self.verify_key(key=_cert.subject_key, issuer=_cert.subject)):
            return False

        # Verify matching key identifiers
        ixt = dict(((e.oid, e) for e in certificate.extensions))
        sxt = dict(((e.oid, e) for e in self.extensions))
        if (VX509SubjectKeyIdentifier.IDENTIFIER in ixt
            or VX509AuthorityKeyIdentifier.IDENTIFIER in sxt):
            ski = ixt.get(VX509SubjectKeyIdentifier.IDENTIFIER, None)
            aki = sxt.get(VX509AuthorityKeyIdentifier.IDENTIFIER, None)
            if ski is None or aki is None:
                return False
            if ski.identifier != aki.identifier:
                return False

        # Verify timestamp
        if verify_time:
            if tstamp is None:
                tstamp = datetime.datetime.now()
            if (tstamp < certificate.valid_not_before
                or tstamp > certificate.valid_not_after):
                return False

        # Validate issuer's signature rights
        if strict:
            if (VX509BasicConstraint.IDENTIFIER not in ixt
                or VX509SubjectKeyIdentifier.IDENTIFIER not in ixt
                or VX509KeyUsage.IDENTIFIER not in ixt):
                return False
            basic = ixt[VX509BasicConstraint.IDENTIFIER]
            if not basic.is_ca:
                return False
            usage = ixt[VX509KeyUsage.IDENTIFIER]
            if not usage.bits & usage.KEY_CERT_SIGN:
                return False

        return True

    def sign(self, csr, serial, not_after, sign_key,
             extensions=None, not_before=None, subject_unique=None,
             strict=True):
        """Sign a certification request with issuer from this certificate.

        :param csr:       certification request
        :type  csr:       :class:`VX509CertificationRequest`
        :param sign_key:  keypair for signing cert
        :type  sign_key:  :class:`versile.crypto.VAsymmetricKey`
        :param strict:    if True validate issuer has CA signature permission
        :type  strict:    bool
        :returns:         signed certificate
        :rtype:           :class:`VX509Certificate`
        :raises:          :class:`versile.crypto.VCryptoException`

        *sign_key* should be the issuer's keypair for signing the
        certificate.

        Sets AuthorizedKeyIdentifier data on the signed certificate
        based on SubjectIdentifier data of the certification
        request. If provided extensions already includes an
        AuthorizedKeyIdentifier, the provided extension is used
        instead, however an exception is raised if the key identifier
        does not match a subject key identifier set on the issuer.

        """
        if sign_key.public.keydata != self.subject_key.keydata:
            raise VCryptoException('Sign key does not match issuer public key')
        if extensions is None:
            extensions = tuple()
        extensions = list(extensions)

        # Hold issuer/subject extensions as dictionaries
        ixt = dict(((e.oid, e) for e in self.extensions))
        sxt = dict(((e.oid, e) for e in extensions))

        if strict:
            if (VX509BasicConstraint.IDENTIFIER not in ixt
                or VX509SubjectKeyIdentifier.IDENTIFIER not in ixt
                or VX509KeyUsage.IDENTIFIER not in ixt):
                raise VCryptoException('Issuer lacks required CA extensions')
            basic = ixt[VX509BasicConstraint.IDENTIFIER]
            if not basic.is_ca:
                raise VCryptoException('Issuer is not a CA')
            usage = ixt[VX509KeyUsage.IDENTIFIER]
            if not usage.bits & usage.KEY_CERT_SIGN:
                raise VCryptoException('Issuer does not have sign permission')

        if VX509SubjectKeyIdentifier.IDENTIFIER in ixt:
            identifier = ixt[VX509SubjectKeyIdentifier.IDENTIFIER].identifier
            if VX509AuthorityKeyIdentifier.IDENTIFIER in sxt:
                set_id = sxt[VX509AuthorityKeyIdentifier.IDENTIFIER].identifier
                if set_id != identifier:
                    raise VCryptoException('Authority Key Identifier mismatch')
            else:
                aki_ext = VX509AuthorityKeyIdentifier(identifier=identifier)
                extensions.append(aki_ext)

        issuer_unique = self.subject_unique_id
        cert = csr.sign(serial=serial, issuer=self.subject,
                        not_after=not_after, sign_key=sign_key,
                        extensions=extensions, not_before=not_before,
                        issuer_unique=issuer_unique,
                        subject_unique=subject_unique)
        return cert

    def sign_ca(self, csr, serial, not_after, sign_key,
                extensions=None, not_before=None, path_len=None,
                usage_bits=None, subject_unique=None, strict=True):
        """Sign a certification request granting it CA permissions.

        Similar to :meth:`sign`\ . Calls
        :meth:`VX509CertificateExtension.ca_extensions` to generate a
        set of extensions for CA permissions and adds the resulting
        set to *extensions*\ .

        """
        if extensions is None:
            extensions = tuple()
        extensions = list(extensions)
        _ca_ext_fun = VX509CertificateExtension.ca_extensions
        ext = _ca_ext_fun(csr.subject_key, path_len, usage_bits)
        extensions.extend(ext)
        return self.sign(csr=csr, serial=serial, not_after=not_after,
                         sign_key=sign_key, extensions=extensions,
                         not_before=not_before, subject_unique=subject_unique,
                         strict=strict)

    @classmethod
    def create(cls, serial, issuer, not_after, subject,
               subject_key, sign_key, extensions=None, not_before=None,
               issuer_unique=None, subject_unique=None, version=None):
        """Creates a certificate from certificate data.

        :param serial:         certificate serial number
        :type  serial:         int
        :param issuer:         certificate issuer
        :type  issuer:         :class:`VX509Name`
        :param not_after:      latest valid time
        :type  not_after:      :class:`datetime.datetime` or
                               :class:`datetime.timedelta`
        :param subject:        certificate subject
        :type  subject:        :class:`VX509Name`
        :param sign_key:       issuer's keypair
        :type  sign_key:       :class:`versile.crypto.VAsymmetricKey`
        :param extensions:     certificate extensions
        :type  extensions:     :class:`VX509CertificateExtension`\ ,
        :param not_before:     earliest valid time
        :type  not_before:     :class:`datetime.datetime` or
                               :class:`datetime.timedelta`
        :param issuer_unique:  issuer unique ID
        :type  issuer_unique:  bytes
        :param subject_unique: subject unique ID
        :type  subject_unique: bytes
        :param version:        certificate version
        :type  version:        int
        :returns:              generated certificate
        :returns:              :class:`VX509Certificate`

        Certificate is only valid for timestamps between *not_before*
        and *not_after*. If a timedelta is provided for *not_after* or
        *not_before* then the timedelta is taken from the current
        system UTC time. If *not_before* is None then the current time
        mins 5 minutes is used.

        *sign_key* will be used to sign the certificate.

        If *version* is None then the certificate version is
        automatically set based on certificate parameters.

        """
        _create = cls.create_tbs
        tbs = _create(serial=serial, issuer=issuer, not_before=not_before,
                      not_after=not_after, subject=subject,
                      subject_key=subject_key, issuer_unique=issuer_unique,
                      subject_unique=subject_unique, extensions=extensions,
                      version=version)
        return cls.create_from_tbs(tbs_cert=tbs, sign_key=sign_key)

    @classmethod
    def create_from_tbs(cls, tbs_cert, sign_key):
        """Creates a certificate from an :term:`ASN.1` TBS Certificate.

        :param tbs_cert: input :term:`ASN.1` data
        :param sign_key: issuer's keypair
        :type  sign_key: :class:`versile.crypto.VAsymmetricKey`
        :returns:        generated certificate
        :returns:        :class:`VX509Certificate`

        *sign_key* will be used to sign the certificate. Intended
        mainly for internal use.

        """
        # Compute signature
        msg = tbs_cert.encode_der()
        sign_alg = tbs_cert.signature.algorithm.native()
        if sign_alg == VObjectIdentifier(1, 2, 840, 113549, 1, 1, 5):
            f_sign = VX509Crypto.rsassa_pkcs1_v1_5_sign
            sign_val = f_sign(sign_key, _mod_sha1_cls, msg)
            sign_val = VBitfield.from_octets(sign_val)
        else:
            raise VCryptoException('Signature algorithm not supported')

        # Create certificate
        _def_cert = Certificate()
        cert = _def_cert.create()
        cert.append(tbs_cert, name='TbsCertificate')
        _alg = cert.c_app('signatureAlgorithm')()
        _alg.c_app('algorithm', sign_alg)()
        _alg.append(VASN1Null(), name='parameters')
        cert.c_app('signatureValue', sign_val)()
        if not cert.validate():
            raise VASN1Exception('Internal ASN.1 structure validation error')

        return cls(asn1_cert=cert)


    @classmethod
    def create_tbs(cls, serial, issuer,  not_after, subject, subject_key,
                   extensions=None, not_before=None, issuer_unique=None,
                   subject_unique=None, version=None):
        """Creates :term:`ASN.1` TBS Certificate data for provided arguments.

        :returns: :term:`ASN.1` TBS Certificate data
        :rtype:   :class:`versile.common.asn1.VASN1Base`

        Input arguments are similar to :meth:`create`\ . The method is
        intended mainly for internal use.

        """
        _ctag = lambda(n): VASN1Tag(VASN1Tag.CONTEXT, n)
        _def_tbs = TBSCertificate()
        tbs_cert = _def_tbs.create()
        if not_before is None:
            not_before = -datetime.timedelta(seconds=300)
        if isinstance(not_before, datetime.timedelta):
            not_before = datetime.datetime.utcnow() + not_before
        if isinstance(not_after, datetime.timedelta):
            not_after = datetime.datetime.utcnow() + not_after

        if version is None:
            if extensions:
                version = 2
            elif issuer_unique or subject_unique:
                version = 1
            else:
                version = 0
        _v_is_def = (version == 0)
        tbs_cert.c_app('version', version)(is_default=_v_is_def)
        tbs_cert.c_app('serialNumber', serial)()
        _sig = tbs_cert.c_app('signature')()
        _alg = VObjectIdentifier(1, 2, 840, 113549, 1, 1, 5)
        _sig.c_app('algorithm', _alg)()
        _sig.append(VASN1Null(), name='parameters')

        tbs_cert.append(issuer.export(), name='issuer')

        _val = tbs_cert.c_app('validity')()
        _val.append(not_before, name='notBefore')
        _val.append(not_after, name='notAfter')

        tbs_cert.append(subject.export(), name='subject')

        if subject_key.cipher_name != 'rsa':
            raise VCryptoException('Key type not supported')
        _skey = tbs_cert.c_app('subjectPublicKeyInfo')()
        _key_alg = _skey.c_app('algorithm')()
        _key_alg.append(VObjectIdentifier((1, 2, 840, 113549, 1, 1, 1)))
        _key_alg.append(VASN1Null())
        _key_data = VX509Crypto.export_public_key(subject_key, VX509Format.DER)
        _key_data = VBitfield.from_octets(_key_data)
        _skey.c_app('subjectPublicKey', _key_data)()

        if issuer_unique:
            _unique_id = VBitfield.from_octets(issuer_unique)
            tbs_cert.c_app('issuerUniqueId', _unique_id)()
        if subject_unique:
            _unique_id = VBitfield.from_octets(subject_unique)
            tbs_cert.c_app('subjectUniqueId', _unique_id)()

        if extensions:
            _extensions = tbs_cert.c_app('extensions')().value
            for ext in extensions:
                _extensions.append(ext.encode_asn1())

        if not tbs_cert.validate():
            raise VASN1Exception('Internal ASN.1 structure validation error')

        return tbs_cert

    @classmethod
    def import_cert(cls, data, fmt, exact=True, bytes_read=False):
        """Import certificate from encoded representation.

        :param data:       certificate data to import
        :param fmt:        data format to import from
        :type  fmt:        :class:`VX509Format` constant
        :param exact:      if True require DER data contains exactly one cert
        :type  exact:      bool
        :param bytes_read: if True return a 2-tuple including bytes read
        :type  bytes_read: bool
        :returns:          imported certificate
        :rtype:            :class:`VX509Certificate`
        :raises:           :class:`versile.crypto.VCryptoException`

        If *bytes_read* is True and the certificate is imported from
        :term:`PEM` or :term:`DER` data, then a tuple (certificate,
        bytes_read) which includes the number of :term:`DER` bytes
        read is returned.

        """
        orig_fmt = fmt
        if fmt == VX509Format.PEM_BLOCK:
            label, data = decode_pem_block(data)
            if label != b'CERTIFICATE':
                raise VCryptoException('Invalid ASCII block label')
            fmt = VX509Format.DER
        elif fmt == VX509Format.PEM:
            if _pyver == 2:
                data = _s2b(base64.decodestring(_b2s(data)))
            else:
                data = base64.decodebytes(data)
            fmt = VX509Format.DER
        if fmt == VX509Format.DER:
            asn1data, num_read = Certificate().parse_der(data)
            if exact and num_read != len(data):
                raise VCryptoException('Certificate data overflow')
            data = asn1data
            fmt = VX509Format.ASN1
        if fmt == VX509Format.ASN1:
            cert = cls(asn1_cert=data)
            if bytes_read and orig_fmt != VX509Format.ASN1:
                return (cert, num_read)
            return cert
        else:
            raise VCryptoException('Import format not recognized.')

    @property
    def version(self):
        """Version (int)."""
        return self._version

    @property
    def serial(self):
        """Serial number (int)."""
        return self._serial

    @property
    def sign_algorithm(self):
        """Sign alg. (\ :class:`versile.common.util.VObjectIdentifier`)."""
        return self._sign_alg

    @property
    def issuer(self):
        """Issuer (\ :class:`VX509Name`\ )."""
        return self._issuer

    @property
    def valid_not_before(self):
        """Valid-not-before (\ :class:`datetime.datetime`\ , UTC)."""
        return self._not_before

    @property
    def valid_not_after(self):
        """Valid-not-after (\ :class:`datetime.datetime`\ , UTC)."""
        return self._not_after

    @property
    def subject(self):
        """Subject (\ :class:`VX509Name`\ )."""
        return self._subject

    @property
    def subject_key(self):
        """Subject public key (\ :class:`versile.crypto.VASymmetricKey`\ )."""
        return self._subject_key

    @property
    def issuer_unique_id(self):
        """Issuer unique ID (int)"""
        return self._issuer_unique

    @property
    def subject_unique_id(self):
        """Subject unique ID (int)"""
        return self._subject_unique

    @property
    def extensions(self):
        """Certificate extensions (:class:`VX509CertificateExtension`\ ,)"""
        return self._extensions

    @property
    def extension_ids(self):
        """Set of object identifiers of registered extensions."""
        return frozenset((e.oid for e in self._extensions))

    @classmethod
    def __validate_type(cls, data, type):
        if not isinstance(data, type):
            raise VCryptoException('Invalid certificate data')

    @classmethod
    def __validate_criteria(cls, *criteria):
        for c in criteria:
            if not c:
                raise VCryptoException('Invalid certificate data')


class VX509CertificationRequest(object):
    """Certification request, implementing request as per :term:`PKCS#10`\ .

    :param asn1_req: :term:`ASN.1` certification request data
    :type  asn1_req: :class:`versile.common.asn1.VASN1Base`

    External code should normally use :meth:`create` or
    :meth:`import_request` to create a certification request.

    .. note::

        The Certification Request 'attributes' property is not
        properly supported.

    """

    def __init__(self, asn1_req):
        self._request = asn1_req
        req_info, sign_alg, sign_val = self._request

        # Read request info data
        # - version
        self._version = req_info.version.native()
        self.__validate_criteria(self._version == 0)
        # - subject
        self._subject = VX509Name.import_name(req_info.subject)
        # - subject public key
        _sk_alg, _sk_data = req_info.subjectPKInfo.native(deep=True)
        _sk_alg, tmp = _sk_alg
        self.__validate_criteria(tmp is None)
        self.__validate_type(_sk_alg, VObjectIdentifier)
        _pkcs_oid = (1, 2, 840, 113549, 1, 1, 1)
        self.__validate_criteria(_sk_alg.oid == _pkcs_oid)
        # [import RSA PKCS #1 v1.5 Key Transport Algorithm]
        _importer = VX509Crypto.import_public_key
        self._subject_key = _importer(_sk_data.as_octets(), VX509Format.DER)
        # - attributes
        self._attributes = req_info.attributes.native()
        # Read signature algorithm
        _sign_alg, tmp = sign_alg.native(deep=True)
        self.__validate_criteria(tmp is None)
        self.__validate_type(_sign_alg, VObjectIdentifier)
        self._sign_alg = _sign_alg
        # Read signature value
        self._sign_val = sign_val.native(deep=True)

    @classmethod
    def create(cls, subject, subject_keypair, attributes=None):
        """Creates a certification request.

        :param subject:         certificate subject
        :type  subject:         :class:`VX509Name`
        :param subject_keypair: subject keypair
        :type  subject_keypair: :class:`versile.crypto.VAsymmetricKey`
        :returns:               signed certification request
        :rtype:                 :class:`VX509CertificationRequest`

        *subject_keypair* will be used for signing the certification
        request.

        """
        _create = cls.create_req_info
        req_info = _create(subject=subject, subject_key=subject_keypair.public,
                           attributes=attributes)
        return cls.create_from_req_info(req_info=req_info,
                                        subject_keypair=subject_keypair)

    @classmethod
    def create_from_req_info(cls, req_info, subject_keypair):
        """Creates a request from input :term:`ASN.1` data.

        :param req_info:        input :term:`ASN.1` data
        :param subject_keypair: subject keypair
        :type  subject_keypair: :class:`versile.crypto.VAsymmetricKey`
        :returns:               signed certification request
        :rtype:                 :class:`VX509CertificationRequest`

        Intended mainly for internal use. *subject_keypair* will be
        used for signing the certification request.

        """
        # Compute signature
        msg = req_info.encode_der()
        sign_alg = VObjectIdentifier(1, 2, 840, 113549, 1, 1, 5)
        sign_key = subject_keypair
        f_sign = VX509Crypto.rsassa_pkcs1_v1_5_sign
        sign_val = f_sign(sign_key, _mod_sha1_cls, msg)
        sign_val = VBitfield.from_octets(sign_val)

        # Create certificate
        _def_cert = CertificationRequest()
        cert = _def_cert.create()
        cert.append(req_info, name='certificationRequestInfo')
        _alg = cert.c_app('signatureAlgorithm')()
        _alg.c_app('algorithm', sign_alg)()
        _alg.append(VASN1Null(), name='parameters')
        cert.c_app('signature', sign_val)()
        if not cert.validate():
            raise VASN1Exception('Internal ASN.1 structure validation error')

        return cls(asn1_req=cert)


    @classmethod
    def create_req_info(cls, subject, subject_key, attributes=None):
        """Create :term:`ASN.1` request data

        :returns: :term:`ASN.1` request data
        :rtype:   :class:`versile.common.asn1.VASN1Base`

        Input arguments are similar to :meth:`create`\ . The method is
        intended mainly for internal use.

        .. note::

            The 'attributes' property is not properly supported.

        """
        _ctag = lambda(n): VASN1Tag(VASN1Tag.CONTEXT, n)
        req_info = CertificationRequestInfo().create()
        req_info.c_app('version', 0)()
        req_info.append(subject.export(), name='subject')
        if subject_key.cipher_name != 'rsa':
            raise VCryptoException('Key type not supported')
        _skey = req_info.c_app('subjectPKInfo')()
        _key_alg = _skey.c_app('algorithm')()
        _key_alg.append(VObjectIdentifier((1, 2, 840, 113549, 1, 1, 1)))
        _key_alg.append(VASN1Null())
        _key_data = VX509Crypto.export_public_key(subject_key, VX509Format.DER)
        _key_data = VBitfield.from_octets(_key_data)
        _skey.c_app('subjectPublicKey', _key_data)()

        # 'attributes' is currently not properly supported, if set it must
        # be an already created ASN.1 of the appropriate structure.
        if attributes:
            req_info.append(attributes, name='attributes')
        else:
            req_info.c_app('attributes')()

        return req_info

    def verify(self):
        """Verifies the certification request's signature.

        :returns:       True if certification request verifies
        :rtype:         bool
        :raises:        :exc:`versile.crypto.VCryptoException`

        Validates the requests's subject key was used to sign the
        request.

        """
        if self._sign_alg == VObjectIdentifier(1, 2, 840, 113549, 1, 1, 5):
            # Validate with 'RSASSA PKCS #1 v1.5 Verify'
            req_info = self._request[0]
            msg = req_info.encode_der()
            v_func = VX509Crypto.rsassa_pkcs1_v1_5_verify
            signature = self._sign_val.as_octets()
            verifies = v_func(self.subject_key, _mod_sha1_cls, msg, signature)
            return verifies
        else:
            raise VCryptoException('Signature method not supported')

    # Currently ignores the 'attributes' property of the Certification Request
    def sign(self, serial, issuer, not_after, sign_key, extensions=None,
             not_before=None, issuer_unique=None, subject_unique=None,
             version=None):
        """Creates a certificate which signs this certification request.

        :returns: signed certificate
        :rtype:   :class:`VX509Certificate`

        Arguments are similar to :meth:`VX509Certificate.create`\
        . Subject and subject key information is taken from the
        certification request.

        .. warning:

            Currently this implementation ignores any 'attributes' parameters
            set on the certification request.

        """
        _create = VX509Certificate.create
        c = _create(serial=serial, issuer=issuer, not_before=not_before,
                    not_after=not_after, subject=self.subject,
                    subject_key=self.subject_key, sign_key=sign_key,
                    issuer_unique=issuer_unique, subject_unique=subject_unique,
                    extensions=extensions, version=version)
        return c

    def self_sign(self, serial, not_after, sign_key, extensions=None,
                  not_before=None, unique_id=None, version=None):
        """Creates a self-signed certificate for this certification request.

        :returns: signed certificate
        :rtype:   :class:`VX509Certificate`

        Arguments are similar to :meth:`create`\ . Issuer information
        is taken from the certification request (as issuer and subject
        are the same).

        """
        issuer = self.subject
        issuer_unique = subject_unique = unique_id
        return self.sign(serial=serial, issuer=issuer, not_before=not_before,
                         not_after=not_after, sign_key=sign_key,
                         issuer_unique=issuer_unique,
                         subject_unique=subject_unique, extensions=extensions,
                         version=version)

    def self_sign_ca(self, serial, not_after, sign_key, extensions=None,
                     not_before=None, path_len=None, usage_bits=None,
                     unique_id=None, version=None):
        """Creates a self-signed CA certificate for this certification request.

        Similar to :meth:`self_sign`\ with the difference that this
        method calls :meth:`VX509CertificateExtension` to generate a
        set of root CA certificate extensions, and appends to provided
        *extensions*\ .

        """
        if extensions is None:
            extensions = tuple()
        extensions = list(extensions)
        _ca_ext_fun = VX509CertificateExtension.ca_extensions
        ca_ext = _ca_ext_fun(self.subject_key, path_len, usage_bits)
        extensions.extend(ca_ext)
        return self.self_sign(serial=serial,  not_after=not_after,
                              sign_key=sign_key, extensions=extensions,
                              not_before=not_before, unique_id=unique_id,
                              version=version)

    @classmethod
    def import_request(cls, data, fmt):
        """Imports a certification request from encoded request data.

        :param data: certification request data to import
        :param fmt:  data format to import from
        :type  fmt:  :class:`VX509Format` constant
        :returns:    imported certificate
        :rtype:      :class:`VX509CertificationRequest`
        :raises:     :class:`versile.crypto.VCryptoException`

        """
        if fmt == VX509Format.PEM_BLOCK:
            label, data = decode_pem_block(data)
            if label != b'CERTIFICATE REQUEST':
                raise VCryptoException('Invalid ASCII block label')
            fmt = VX509Format.DER
        elif fmt == VX509Format.PEM:
            if _pyver == 2:
                data = _s2b(base64.decodestring(_b2s(data)))
            else:
                data = base64.decodebytes(data)
            fmt = VX509Format.DER
        if fmt == VX509Format.DER:
            asn1data, num_read = CertificationRequest().parse_der(data)
            if num_read != len(data):
                raise VCryptoException('Certificate data overflow')
            data = asn1data
            fmt = VX509Format.ASN1
        if fmt == VX509Format.ASN1:
            return cls(asn1_req=data)
        else:
            raise VCryptoException('Import format not recognized.')

    def export(self, fmt=VX509Format.PEM_BLOCK):
        """Exports the certificate.

        :param fmt:     format to export to
        :type  fmt:     :class:`versile.crypto.x509.VX509Format` constant
        :returns:       exported certificate

        """
        if fmt == VX509Format.ASN1:
            return self._request
        der = self._request.encode_der()
        if fmt == VX509Format.DER:
            return der
        if fmt == VX509Format.PEM:
            if _pyver == 2:
                return _s2b(base64.encodestring(_b2s(der)))
            else:
                return base64.encodebytes(der)
        elif fmt == VX509Format.PEM_BLOCK:
            return encode_pem_block(b'CERTIFICATE REQUEST', der)
        else:
            raise VCryptoException('Invalid encoding')

    @property
    def version(self):
        """Version (int)."""
        return self._version

    @property
    def subject(self):
        """Subject (\ :class:`VX509Name`\ )."""
        return self._subject

    @property
    def subject_key(self):
        """Subject public key (\ :class:`versile.crypto.VASymmetricKey`\ )."""
        return self._subject_key

    @property
    def attributes(self):
        """Certification request attributes"""
        return self._attributes

    @property
    def sign_algorithm(self):
        """Sign alg. (\ :class:`versile.common.util.VObjectIdentifier`)."""
        return self._sign_alg

    @classmethod
    def __validate_type(cls, data, type):
        if not isinstance(data, type):
            raise VCryptoException('Invalid certificate data')

    @classmethod
    def __validate_criteria(cls, *criteria):
        for c in criteria:
            if not c:
                raise VCryptoException('Invalid certificate data')


class VX509Name(dict):
    """Holds an :term:`X.509` Name.

    :param kargs: values to initialize
    :raises:      :exc:`versile.crypto.VCryptoException`

    For each *name=value* provided as a *kargs* argument, the
    operation ``self[self.oid(name)] = value`` is performed during
    construction. *value* must be unicode (if it is bytes then it is
    converted to unicode).

    A :class:`VX509Name` is set up as a dictionary where the keys are
    object identifiers for allowed properties and the value is the
    corresponding set value. The method :meth:`oid` provides a
    convenience method for generating object identifier based on
    property name. Also, :meth:`__getattr__` is overloaded for
    convenient access to values.

    .. automethod:: __getattr__

    """

    def __init__(self, **kargs):
        super(VX509Name, self).__init__()
        for name, value in kargs.items():
            if isinstance(value, bytes):
                value = unicode(bytes)
            if not isinstance(value, unicode):
                raise VCryptoException('Values must be unicode')
            oid = self.oid(name)
            if oid:
                self[oid] = value
            else:
                raise VCryptoException('Keyword not recognized')


    @classmethod
    def import_name(cls, data, fmt=VX509Format.ASN1, exact=True,
                    bytes_read=False):
        """Imports a name from encoded data.

        :param data:       :term:`X.509` Name data to import
        :param fmt:        data format to import from
        :type  fmt:        :class:`VX509Format` constant
        :param exact:      if True require DER data contains exactly one name
        :type  exact:      bool
        :param bytes_read: if True return a 2-tuple including bytes read
        :type  bytes_read: bool
        :returns:          parsed name object
        :rtype:            :class:`VX509Name`
        :raises:           :class:`versile.crypto.VCryptoException`

        If *bytes_read* is True and the name s imported from
        :term:`PEM` or :term:`DER` data, then a tuple (name,
        bytes_read) which includes the number of :term:`DER` bytes
        read is returned.

        """
        orig_fmt = fmt
        if fmt == VX509Format.DER:
            asn1data, num_read = RDNSequence().parse_der(data)
            if exact and num_read != len(data):
                raise VCryptoException('DER data overflow')
            data = asn1data
            fmt = VX509Format.ASN1
        if fmt == VX509Format.ASN1:
            data = data.native(deep=True)
            cls.__validate_type(data, tuple)
            name = cls()
            for item in data:
                cls.__validate_type(item, frozenset)
                cls.__validate_criteria(len(item) == 1)
                key, value = tuple(item)[0]
                cls.__validate_type(key, VObjectIdentifier)
                cls.__validate_type(value, unicode)
                name[key] = value
            if bytes_read and orig_fmt != VX509Format.ASN1:
                return (name, num_read)
            return name
        else:
            raise VCryptoException('Import format not recognized.')

    def export(self, fmt=VX509Format.ASN1):
        """Exports name object data.

        :param fmt: format to export to
        :type  fmt: :class:`versile.crypto.x509.VX509Format`
        :returns:   exported data

        """
        asn1data = RDNSequence().create()
        for key, val in self.items():
            _pair = AttributeTypeAndValue().create()
            _pair.append(key, name='type')
            _pair.append(val, name='value')
            _rdn = asn1data.c_app()()
            _rdn.add(_pair)
        if fmt == VX509Format.ASN1:
            return asn1data
        der = asn1data.encode_der()
        if fmt == VX509Format.DER:
            return der
        else:
            raise VCryptoException('Invalid encoding')

    @classmethod
    def oid(cls, name):
        """Returns an object identifier associated with a parameter name.

        :param name: parameter name
        :type  name: unicode
        :returns:    corresponding oid
        :rtype:      :class:`versile.common.util.VObjectIdentifier`

        Supported names includes commonName, serialNumber,
        organizationName, stateOrProvindeName, streetAddress,
        countryName. Returns None if *name* is not known.

        """
        if name == 'commonName':
            num = 3
        elif name == 'serialNumber':
            num = 5
        elif name == 'organizationName':
            num = 6
        elif name == 'stateOrProvinceName':
            num = 8
        elif name == 'streetAddress':
            num = 9
        elif name == 'countryName':
            num = 10
        else:
            return None
        return VObjectIdentifier((2, 5, 4, num))

    def __getattr__(self, attr):
        """Return a dictionary element by the associated X.509 name element.

        :attr:    name of X.509 Name property
        :returns: associated registered value (or None)

        Equivalent to ``self.get(self.oid(attr), None)``\ . Will only
        return results for name elements understood by :meth:`oid`\
        . Returns None if an associated value is not registered.

        """
        return self.get(self.oid(attr), None)

    @classmethod
    def __validate_type(cls, data, type):
        if not isinstance(data, type):
            raise VCryptoException('Invalid certificate data')

    @classmethod
    def __validate_criteria(cls, *criteria):
        for c in criteria:
            if not c:
                raise VCryptoException('Invalid certificate data')


class VX509CertificateExtension(object):
    """Base class for a certificate extensions.

    :param oid:      extension's ID
    :type  oid:      :class:`versile.common.util.VObjectIdentifier`
    :param critical: True if extension is registered as critical
    :type  critical: bool
    :param value:    extension data
    :type  value:    bytes

    """

    def __init__(self, oid, critical, value):
        self._oid = oid
        self._critical = critical
        self._value = value

    def encode_asn1(self):
        """Encodes the extension as :term:`ASN.1` data.

        :returns: encoded extension
        :rtype:   :class:`versile.common.asn1.VASN1Base`

        """
        obj = Extension().create()
        obj.c_app('extnID', self.oid)()
        obj.c_app('critical', self._critical)(is_default=(not self._critical))
        obj.c_app('extnValue', self._value)()
        return obj

    def encode_der(self):
        """Encodes the extension's :term:`ASN.1` represntation as :term:`DER`.

        :returns: encoded extension
        :rtype:   bytes

        """
        asn1 = self.encode_asn1()
        return asn1.encode_der()

    @classmethod
    def parse_asn1(cls, ext):
        """Create an extension object from :term:`ASN.1` extension data

        :param ext: :term:`ASN.1` extension object
        :type  ext: :class:`versile.common.asn1.VASN1Base`
        :returns:   parsed extension object
        :rtype:     :class:`VX509CertificateExtension`
        :raises:    :class:`VCryptoException`

        *ext* should be a
        :class:`versile.crypto.x509.asn1def.cert.Extension`

        """
        if not isinstance(ext, VASN1Base) or ext.asn1def is Extension:
            raise TypeError('Invalid input data')
        oid, critical, value = ext.native()
        return cls.parse_data(oid, critical, value)

    @classmethod
    def parse_data(cls, oid, critical, value):
        """Create an extension by parsing extension data.

        :param oid:      extension ID
        :type  oid:      :class:`versile.common.util.VObjectIdentifier`
        :param critical: True if extension is registered as critical
        :type  critical: bool
        :param value:    extension data
        :type  value:    bytes
        :returns:        parsed extension object
        :rtype:          :class:`VX509CertificateExtension`

        This method is called by :meth:`parse_asn1` to parse data held
        by the :term:`ASN.1` extension entry. It tries to generate an
        extension of a supported extension-specific type, or otherwise
        falls back to :class:`VX509CertificateExtension`.

        """
        if oid == BasicConstraints.id_ce:
            return VX509BasicConstraint.parse_data(oid, critical, value)
        elif oid == SubjectKeyIdentifier.id_ce:
            return VX509SubjectKeyIdentifier.parse_data(oid, critical, value)
        elif oid == KeyUsage.id_ce:
            return VX509KeyUsage.parse_data(oid, critical, value)
        elif oid == AuthorityKeyIdentifier.id_ce:
            return VX509AuthorityKeyIdentifier.parse_data(oid, critical, value)
        else:
            return VX509CertificateExtension(oid, critical, value)

    @classmethod
    def ca_extensions(cls, ca_pub_key, path_len=None, usage_bits=None):
        """Generates certificate extensions for a Certificate Authority.

        :param ca_pub_key: CA's public key
        :type  ca_pub_key: :class:`versile.crypto.VAsymmetricKey`
        :param path_len:   certificate path length constraint (or None)
        :type  path_len:   int
        :param usage_bit:  flags for :class:`VX509KeyUsage` (or None)
        :type  usage_bits: :class:`versile.common.util.VBitfield`
        :returns:          CA extensions
        :rtype:            tuple(\ :class:`VX509CertificateExtension`\ ,)

        :meth:`VX509SubjectKeyIdentifier.key_to_identifier` is used
        with *ca_pub_key* to create an identifier for the key.

        *path_len* is used for :class:`VX509BasicConstraint`
        construction (None means there is no constraint on
        length).

        *usage_bits* are used as input to
        :class:`VX509KeyUsage`\ , if None then the certificate is set
        up with :attr:`VX509KeyUsage.KEY_CERT_SIGN` and
        :attr:`VX509KeyUsage.CRL_SIGN`\ .

        """
        xts = list()
        xts.append(VX509BasicConstraint(is_ca=True, critical=True,
                                        path_len=path_len))
        _ski = VX509SubjectKeyIdentifier.key_to_identifier(ca_pub_key)
        xts.append(VX509SubjectKeyIdentifier(_ski))
        if not usage_bits:
            usage_bits = VX509KeyUsage.KEY_CERT_SIGN | VX509KeyUsage.CRL_SIGN
        xts.append(VX509KeyUsage(usage_bits))
        return tuple(xts)

    @property
    def oid(self):
        """Extension's object identifier."""
        return self._oid

    @property
    def critical(self):
        """True if extension is registered as critical."""
        return self._critical

    @property
    def value(self):
        """Extension's 'value' octets for its :term:`ASN.1` representation."""
        return self._value


class VX509BasicConstraint(VX509CertificateExtension):
    """An :term:`X.509` BasicConstraint extension.

    :param is_ca:    if True the public key belongs to a CA
    :type  is_ca:    bool
    :param critical: if True the extension is critical
    :type  critical: bool
    :param path_len: maximum following certificates (or None)
    :type  path_len: int

    If *path_len* is None then there is no path length constraint.

    """

    def __init__(self, is_ca, critical, path_len=None):
        self._is_ca = is_ca
        self._path_len = path_len

        oid = self.IDENTIFIER
        asn1 = BasicConstraints().create()
        asn1.c_app('cA', is_ca)()
        if path_len is not None:
            asn1.c_app('pathLenConstraint', path_len)()
        value = asn1.encode_der()
        super(VX509BasicConstraint, self).__init__(oid, critical, value)

    @classmethod
    def parse_data(cls, oid, critical, value):
        if oid != BasicConstraints.id_ce:
            raise VCryptoException('Bad object identifier')
        obj, num_read = BasicConstraints().parse_der(value)
        if num_read != len(value):
            raise VCryptoException('Bad extension value DER encoding')
        is_ca = obj.cA.native()
        if 'pathLenConstraint' in obj.names:
            path_len = obj.pathLenConstraint.native()
            if path_len < 0:
                raise VCryptoException('Invalid path length')
        else:
            path_len = None
        return cls(is_ca, critical, path_len)

    @property
    def is_ca(self):
        """isCa property set on extension."""
        return self._is_ca

    @property
    def path_len(self):
        """pathLengthConstraint property set on extension."""
        return self._path_len

    IDENTIFIER = BasicConstraints.id_ce
    """Object identifier for the extension type."""


class VX509SubjectKeyIdentifier(VX509CertificateExtension):
    """An :term:`X.509` SubjectKeyIdentifier extension.

    :param identifier: key identifier
    :type  identifier: bytes

    """

    def __init__(self, identifier):
        self._identifier = identifier
        oid = self.IDENTIFIER
        critical = False
        asn1 = SubjectKeyIdentifier().create(identifier)
        value = asn1.encode_der()
        super(VX509SubjectKeyIdentifier, self).__init__(oid, critical, value)

    @classmethod
    def parse_data(cls, oid, critical, value):
        if oid != SubjectKeyIdentifier.id_ce:
            raise VCryptoException('Bad object identifier')
        obj, num_read = SubjectKeyIdentifier().parse_der(value)
        if num_read != len(value):
            raise VCryptoException('Bad extension value DER encoding')
        identifier = obj.native()
        return cls(identifier)

    @classmethod
    def key_to_identifier(cls, key):
        """Generates key identifier octets from a public key.

        :param key: public key or keypair
        :type  key: :class:`versile.crypto.VAsymmetricKey`
        :returns:   generated key identifier
        :rtype:     bytes

        Implements the key identifier generation scheme (1) defined in
        :rfc:`5280` section 4.2.1.2.

        """
        der = VX509Crypto.export_public_key(key, fmt=VX509Format.DER)
        bits = VBitfield.from_octets(der)
        derbits = VASN1BitString(bits).encode_der()
        _ber_dec = VASN1Definition._ber_dec_tagged_content
        ((tag_data, content, definite, short), num_read) = _ber_dec(derbits)
        hasher = sha1()
        hasher.update(content[1:])
        if _pyver == 2:
            return _s2b(hasher.digest())
        else:
            return hasher.digest()

    @property
    def identifier(self):
        """Key identifier set on extension."""
        return self._identifier

    IDENTIFIER = SubjectKeyIdentifier.id_ce
    """Object identifier for the extension type."""


class VX509KeyUsage(VX509CertificateExtension):
    """An :term:`X.509` KeyUsage extension.

    :param bits: bit field with bitwise OR of key usage flags
    :type  bits: :class:`versile.common.util.VBitfield`

    *bits* should be a bitwise OR of one of the flags set on this
    class: :attr:`DIGITAL_SIGNATURE`\, :attr:`NON_REPUDIATION`\ ,
    :attr:`KEY_ENCIPHERMENT`\ , :attr:`DATA_ENCIPHERMENT`\ ,
    :attr:`KEY_AGREEMENT`\ , :attr:`KEY_CERT_SIGN`\ ,
    :attr:`CRL_SIGN`\ , :attr:`ENCIPHER_ONLY`\ ,
    :attr:`DECIPHER_ONLY`\ , :attr:`IDENTIFIER`\ .

    Flags can be tested with a bitwise AND with :attr:`bits`\ .

    """

    def __init__(self, bits):
        if len(bits.bits) > 9:
            raise TypeError('Bitfield too long')
        self._bits = bits
        oid = self.IDENTIFIER
        critical = True
        asn1 = KeyUsage().create(bits)
        value = asn1.encode_der()
        super(VX509KeyUsage, self).__init__(oid, critical, value)

    @classmethod
    def parse_data(cls, oid, critical, value):
        if oid != KeyUsage.id_ce:
            raise VCryptoException('Bad object identifier')
        obj, num_read = KeyUsage().parse_der(value)
        if num_read != len(value):
            raise VCryptoException('Bad extension value DER encoding')
        bits = obj.native()
        return cls(bits)

    @property
    def bits(self):
        """Bits set on extension (:class:`versile.common.util.VBitfield`\ )."""
        return self._bits

    DIGITAL_SIGNATURE = VBitfield((1,) + 8*(0,))
    """Extension flag for digitalSignature."""

    NON_REPUDIATION= VBitfield((0, 1) + 7*(0,))
    """Extension flag for nonRepudiation."""

    KEY_ENCIPHERMENT = VBitfield(2*(0,) + (1,) + 6*(0,))
    """Extension flag for keyEncipherment."""

    DATA_ENCIPHERMENT= VBitfield(3*(0,) + (1,) + 5*(0,))
    """Extension flag for dataEncipherment."""

    KEY_AGREEMENT = VBitfield(4*(0,) + (1,) + 4*(0,))
    """Extension flag for KEY_AGREEMENT."""

    KEY_CERT_SIGN = VBitfield(5*(0,) + (1,) + 3*(0,))
    """Extension flag for keyCertSign."""

    CRL_SIGN = VBitfield(6*(0,) + (1,) + 2*(0,))
    """Extension flag for cRLSign."""

    ENCIPHER_ONLY = VBitfield(7*(0,) + (1,) + 1*(0,))
    """Extension flag for encipherOnly."""

    DECIPHER_ONLY = VBitfield(8*(0,) + (1,))
    """Extension flag for decipherOnly."""

    IDENTIFIER = KeyUsage.id_ce
    """Object identifier for the extension type."""


class VX509AuthorityKeyIdentifier(VX509CertificateExtension):
    """An :term:`X.509` AuthorityKeyIdentifier extension.

    :param identifier: authority key identifier
    :type  identifier: bytes
    :param issuer:     certificate issuer
    :param serial:     certificate serial number
    :type  serial:     int

    *issuer* should be an object created from the
    :class:`versile.crypto.x509.asn1def.cert.GeneralName` definition.

    When used, *issuer* and *serial* must both be set.

    """

    def __init__(self, identifier=None, issuer=None, serial=None):
        self._identifier = identifier
        self._issuer = issuer
        self._serial = serial

        oid = self.IDENTIFIER
        critical = False
        asn1 = AuthorityKeyIdentifier().create()
        if identifier is not None:
            asn1.c_app('keyIdentifier', identifier)()
        if issuer is not None:
            asn1.append(issuer, name='authorityCertIssuer')
        if serial is not None:
            asn1.c_app('authorityCertSerialNumber', serial)()
        der = asn1.encode_der()
        super(VX509AuthorityKeyIdentifier, self).__init__(oid, critical, der)

    @classmethod
    def parse_data(cls, oid, critical, value):
        if oid != AuthorityKeyIdentifier.id_ce:
            raise VCryptoException('Bad object identifier')
        if critical:
            raise VCryptoException('Extension should not be maked critical')
        obj, num_read = AuthorityKeyIdentifier().parse_der(value)
        if num_read != len(value):
            raise VCryptoException('Bad extension value DER encoding')

        identifier = issuer = serial = None
        if 'keyIdentifier' in obj.names:
            identifier = obj.keyIdentifier.value.native()
        if 'authorityCertIssuer' in obj.names:
            issuer = obj.authorityCertIssuer.native()
        if 'authorityCertSerialNumber' in obj.names:
            serial = obj.authorityCertSerialNumber.native()
        return cls(identifier, issuer, serial)

    @property
    def identifier(self):
        """Key identifier set on extension."""
        return self._identifier

    @property
    def issuer(self):
        """Isser set on extension."""
        return self._issuer

    @property
    def serial(self):
        """Serial number set on extension."""
        return self._serial

    IDENTIFIER = AuthorityKeyIdentifier.id_ce
    """Object identifier for the extension type."""
