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

"""Support classes for transport level peer authorization."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport
from versile.crypto import VCryptoException
from versile.crypto.x509 import VX509Crypto, VX509Format
from versile.crypto.x509.cert import VX509Certificate

__all__ = ['VAuth']
__all__ = _vexport(__all__)


class VAuth(object):
    """Authority for authorizing a peer connection.

    :param key:    if True require peer to identify with a key
    :type  key:    bool
    :param cert:   if True require a peer certificate, otherwise False
    :type  cert:   bool
    :param root:   it True require root-validation of peer certificates
    :type  root:   bool
    :param ca:     CA root certs accepted (or None)
    :type  ca:     :class:`versile.crypto.x509.cert.VX509Certificate`\ ,
    :param public: if True accept :term:`Public CA` as root certificate
    :type  public: bool

    If *public* is True then the :term:`Public CA` is added to the *ca*
    root certificate list during construction, if not already included.

    .. note::

        Some combinations of input parameters may not be supported for
        some technologies, e.g. the :term:`TLS` implementation does
        not support *key* set to True without a set of root
        certificates (including any added :term:`Public CA`\ )

    An authority object can be used as a way to specify policies for
    secure communication channel negotiation. It can be used e.g. with
    :class:`versile.orb.url.VUrl` for establishing :term:`VOP`
    connections.

    """

    def __init__(self, key=False, cert=False, root=False,
                 ca=None, public=False):
        self._key = key
        self._cert = cert
        self._root = root
        if ca:
            ca = frozenset(ca)
        else:
            ca = frozenset()
        self._ca_list = ca
        self._public = public
        if public:
            self.add_public_ca()
        else:
            # As public is False, validate Public CA not in list of root certs
            _pubca_cert = self.public_ca(unsafe=True)[1]
            _pubca_der = _pubca_cert.export(fmt=VX509Format.DER)
            for _cert in self._ca_list:
                _cert_der = _cert.export(fmt=VX509Format.DER)
                if _pubca_der == _cert_der:
                    raise VCryptoException('Root certs include Public CA')

    def accept_host(self, host):
        """Request authorization to connect to a host

        :param host: host to approve
        :returns:    True if host is accepted, otherwise False
        :rtype:      bool

        Default returns True, derived classes can override.

        """
        return True

    def accept_credentials(self, key, identity, certificates):
        """Request authorization to proceed with connection given credentials.

        :param key:          peer public key
        :type  key:          :class:`versile.crypto.VAsymmetricKey`
        :param identity:     peer identity
        :type  identity:     :class:`versile.crypto.x509.cert.VX509Name`
        :param certificates: certificate chain
        :type  certificates: :class:`versile.crypto.x509.cert.VX509Certificate`\ ,
        :returns:            True if credentials are accepted, otherwise False
        :rtype:              bool

        Default returns True, derived classes can override.

        """
        return True

    def add_root_certificate(self, certificate):
        """Adds a certificate to the list of accepted root certificates.

        :param certificate: certificate to add
        :type  certificate: :class:`versile.crypto.x509.cert.VX509Certificate`

        """
        newlist = set(self._ca_list)
        newlist.add(certificate)
        self._ca_list = frozenset(newlist)

    def add_public_ca(self):
        """Adds :term:`Public CA` to the list of accepted root certificates."""
        pubca_key, pubca_cert = self.public_ca(unsafe=True)
        pubca_der = pubca_cert.export(fmt=VX509Format.DER)
        for cert in self._ca_list:
            cert_der = cert.export(fmt=VX509Format.DER)
            if pubca_der == cert_der:
                break
        else:
            self.add_root_certificate(pubca_cert)

    @classmethod
    def public_ca(self, **kargs):
        """Returns the :term:`Public CA` keypair and certificate.

        :param unsafe: must be set to True
        :type  unsafe: bool
        :returns:      (CA keypair, CA certificate)
        :rtype:        (\ :class:`versile.crypto.VAsymmetricKey`\ ,
                          :class:`versile.crypto.x509.cert.VX509Certificate`\ )
        :raises:       :exc:`versile.crypto.VCryptoException`

        The keyword argument *unsafe* must be set to True when calling
        this method, otherwise an exception is raised. This is a
        safety mechanism to help prevent accidental use of
        :term:`Public CA` crededentials. Using the key for encryption
        or certificate signing is inherently unsafe as the full
        :term:`Public CA` keypair is publicly available.

        .. warning::

            The :term:`Public CA` keypair should not be used for
            anything except signing non-certified keys for protocols
            which require a CA signature due to technical constraints

        """
        if 'unsafe' not in kargs or not kargs['unsafe']:
            raise VCryptoException('The "unsafe" keyword must be set.')
        _keyloader = VX509Crypto.import_private_key
        ca_key = _keyloader(_STD_CA_KEYDATA, fmt=VX509Format.PEM_BLOCK)
        _certloader = VX509Certificate.import_cert
        ca_cert = _certloader(_STD_CA_CERTDATA, fmt=VX509Format.PEM_BLOCK)
        return ca_key, ca_cert


    @property
    def require_key(self):
        """True if a peer key is required."""
        return self._key

    @property
    def require_cert(self):
        """True if a peer certificate is are required."""
        return self._cert

    @property
    def require_root(self):
        """True if then peer certificate chain must be root CA validated."""
        return self._root

    @property
    def root_certificates(self):
        """List of registered root certificates."""
        return self._ca_list


# Standard Public CA keypair data
_STD_CA_KEYDATA = b"""-----BEGIN RSA PRIVATE KEY-----
MIICXgIBAAKBgQDHcbuYAfS0duN3NQRqIPD2+vMnwfaiOBqsSSW5VM4DQMXOCrIzFnVlFP1j7Bt3
2q5YtO84xeTDFQ0Srw8MOQW74WTbVh2Vsc1lwDfWO9QA+tJegXp8H0BMTP6oFP2gKIkChFL3xDOD
iOuoxmPf6zS7KOKG/MFhtQJ0vszTe6LmYwIDAQABAoGAEqoFCSudr8m0bbJrcFcW1bYUTTMslm+z
p03NFvPlt443NJnxpTBD2irFr7UnuOahDDIadPCoAM2WhJoXSWiIrasLimVIHbphKXmMLq839emP
lqBZXiOKsd5gohTb0kdyeQUvKK59xyZJXafYQ9AfuDGOyOsVzlOe8Y7CUgtKxfECQQDsVrwLSwPJ
Bot+4NFepUN/a4bVNVbwGoNp/w8hDbR2Qb0lgHj03b7dnSCdH8x40lFLbbncjZbxevDXfqr36FE7
AkEA2AlDB8O1qTWOjGe/Y7rcTqJQ7y6K9BcoeLQxf0YnFUyi1/1z7hRKfUlGXjKEYf/j/SONeb/G
h7Pg/9AGIsVs+QJBAL0zyqL30PX0SWSvsq2kfF7bxDuX0hux/hazXHdHs3sgsb3+FddiVlSwX9Wq
CVWIehB6rVrF91sm4vyBqXmCANUCQQCRcnLhmF8G5Brr5rGRWG4Ytulcju5Ydfr2gQLOGJIZofYF
CwvxH1IjVaD9rG86d4isljIa5QWpuW5jbE+lO1wpAkEAr5ydd9xGEPEm1Qqf2+7R/EkxmOVQKcOt
uqgvqOHiPZljcumPMAaVrqf7hkyhdgNFN0Q2KF4Wy7yPSve3YTS1aw==
-----END RSA PRIVATE KEY-----
"""

# Standard Public CA certificate data
_STD_CA_CERTDATA = b"""-----BEGIN CERTIFICATE-----
MIICHTCCAYagAwIBAgIJAMq4ULK9waY7MA0GCSqGSIb3DQEBBQUAMCwxKjAoBgNVBAYMIUR1bW15
IFZUTFMgU2lnbmF0dXJlIE9yZ2FuaXphdGlvbjAiGA8yMDExMDEwMTAwMDAwMFoYDzIwNTAwMTAx
MDAwMDAwWjAsMSowKAYDVQQGDCFEdW1teSBWVExTIFNpZ25hdHVyZSBPcmdhbml6YXRpb24wgZ8w
DQYJKoZIhvcNAQEBBQADgY0AMIGJAoGBAMdxu5gB9LR243c1BGog8Pb68yfB9qI4GqxJJblUzgNA
xc4KsjMWdWUU/WPsG3farli07zjF5MMVDRKvDww5BbvhZNtWHZWxzWXAN9Y71AD60l6BenwfQExM
/qgU/aAoiQKEUvfEM4OI66jGY9/rNLso4ob8wWG1AnS+zNN7ouZjAgMBAAGjQzBBMA8GA1UdEwEB
/wQFMAMBAf8wHQYDVR0OBBYEFHWTTUoptf2PHv8oLvC3Gc/QD7/yMA8GA1UdDwEB/wQFAwMHBgAw
DQYJKoZIhvcNAQEFBQADgYEAQ2Kw/7XUM9sorAqb9A1YnaOsUgb9r/UIFNRoeWJnsjhlXhjxeco0
fv58VkuJDTLT6MixWVuNeuq5WxEupRru77twQPdUBLbP5SKvGF4MT0D4ONuuG1heoxraTpv0YnaK
9/2XX8ZiO3nsz110FeP9V5u3yHDt0ZUAFla69pR89cE=
-----END CERTIFICATE-----
"""
