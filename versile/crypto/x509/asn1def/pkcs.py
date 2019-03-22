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

""":term:`ASN.1` definitions for :term:`PKCS#1` and :term:`PKCS#10`\ ."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport
from versile.common.asn1 import *
from versile.common.util import VObjectIdentifier
from versile.crypto.x509.asn1def.cert import AlgorithmIdentifier, Name
from versile.crypto.x509.asn1def.cert import SubjectPublicKeyInfo

__all__ = ['Attribute', 'Attributes', 'CertificationRequest',
           'CertificationRequestInfo', 'DigestInfo', 'OtherPrimeInfo',
           'OtherPrimeInfos', 'RSAPrivateKey', 'RSAPublicKey', 'Version']
__all__ = _vexport(__all__)


### Public/private RSA keys

class RSAPublicKey(VASN1DefSequence):
    """RSAPublicKey structure specified by :term:`PKCS#1`\ ."""
    def __init__(self):
        super(RSAPublicKey, self).__init__(name='RSAPublicKey')
        self.add(VASN1DefInteger(), name='modulus')
        self.add(VASN1DefInteger(), name='publicExponent')


class RSAPrivateKey(VASN1DefSequence):
    """RSAPrivateKey structure specified by :term:`PKCS#1`\ ."""
    def __init__(self):
        super(RSAPrivateKey, self).__init__(name='RSAPrivateKey')
        self.add(Version(), name='version')
        self.add(VASN1DefInteger(), name='modulus')
        self.add(VASN1DefInteger(), name='publicExponent')
        self.add(VASN1DefInteger(), name='privateExponent')
        self.add(VASN1DefInteger(), name='prime1')
        self.add(VASN1DefInteger(), name='prime2')
        self.add(VASN1DefInteger(), name='exponent1')
        self.add(VASN1DefInteger(), name='exponent2')
        self.add(VASN1DefInteger(), name='coefficient')
        self.add(OtherPrimeInfos, name='otherPrimeInfos', opt=True)


class Version(VASN1DefInteger):
    """:term:`ASN.1` type for private key version"""
    def __init__(self):
        super(Version, self).__init__(name='Version')


class OtherPrimeInfos(VASN1DefSequenceOf):
    """:term:`ASN.1` type for OtherPrimeInfos"""
    def __init__(self):
        parser = OtherPrimeInfo()
        super(OtherPrimeInfos, self).__init__(parser, name='OtherPrimeInfos')


class OtherPrimeInfo(VASN1DefSequence):
    """:term:`ASN.1` type for OtherPrimeInfo"""
    def __init__(self):
        super(OtherPrimeInfo, self).__init__(name='OtherPrimeInfo')
        self.add(VASN1DefInteger(), name='prime')
        self.add(VASN1DefInteger(), name='exponent')
        self.add(VASN1DefInteger(), name='coefficient')


class DigestInfo(VASN1DefSequence):
    """:term:`ASN.1` type for DigestInfo"""
    def __init__(self):
        super(DigestInfo, self).__init__(name='DigestInfo')
        self.add(AlgorithmIdentifier(), name='digestAlgorithm')
        self.add(VASN1DefOctetString(), name='digest')


### Certification requests

class CertificationRequest(VASN1DefSequence):
    """CertificationRequest structure specified by :term:`PKCS#10`\ ."""
    def __init__(self, name=None):
        if name is None:
            name = 'CertificationRequest'
        super(CertificationRequest, self).__init__(explicit=False, name=name)
        self.add(CertificationRequestInfo(), name='certificationRequestInfo')
        self.add(AlgorithmIdentifier(), name='signatureAlgorithm')
        self.add(VASN1DefBitString(), name='signature')


class CertificationRequestInfo(VASN1DefSequence):
    """:term:`ASN.1` structure for CertificationRequestInfo."""
    def __init__(self, name=None):
        if name is None:
            name = 'CertificationRequestInfo'
        s_init = super(CertificationRequestInfo, self).__init__
        s_init(explicit=False, name=name)
        self.add(VASN1DefInteger(), name='version')
        self.add(Name(), name='subject')
        self.add(SubjectPublicKeyInfo(), name='subjectPKInfo')
        _def = self.ctx_tag_def(0, Attributes(), explicit=False)
        self.add(_def, name='attributes')


class Attributes(VASN1DefSetOf):
    """:term:`ASN.1` structure for Attributes."""
    def __init__(self, name=None):
        if name is None:
            name = 'Attributes'
        super(Attributes, self).__init__(Attribute(), name=name)


class Attribute(VASN1DefSequence):
    """:term:`ASN.1` structure for an Attributes.

    .. note:

        The 'Attribute' property is not fully supported.

    """
    def __init__(self, name=None):
        if name is None:
            name = 'Attribute'
        super(Attribute, self).__init__(explicit=False, name=name)
        self.add(VASN1DefObjectIdentifier(), name='type')
        # Attribute type not fully supported, for now using 'Universal' as a
        # substitute type for the 'values' element
        self.add(VASN1DefUniversal(), name='values')
