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

""":term:`ASN.1` definitions for :term:`X.509` certificates."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport
from versile.common.asn1 import *
from versile.common.util import VObjectIdentifier

__all__ = ['AlgorithmIdentifier', 'AnotherName', 'AttributeType',
           'AttributeTypeAndValue', 'AttributeValue',
           'AuthorityKeyIdentifier', 'BasicConstraints', 'Certificate',
           'CertificateSerialNumber', 'Extension', 'Extensions',
           'GeneralName', 'GeneralNames', 'KeyIdentifier', 'KeyUsage',
           'Name', 'RDNSequence', 'RelativeDistinguishedName',
           'SubjectKeyIdentifier', 'SubjectPublicKeyInfo', 'TBSCertificate',
           'Time', 'UniqueIdentifier', 'Validity', 'Version']
__all__ = _vexport(__all__)


class Certificate(VASN1DefSequence):
    """The Certificate data structure specified by :rfc:`5280`\ ."""
    def __init__(self, name=None):
        if name is None:
            name = 'Certificate'
        super(Certificate, self).__init__(name=name)
        self.add(TBSCertificate(), name='TbsCertificate')
        self.add(AlgorithmIdentifier(), name='signatureAlgorithm')
        self.add(VASN1DefBitString(), name='signatureValue')


class TBSCertificate(VASN1DefSequence):
    """TBSCertificate of a :class:`Certificate`"""
    def __init__(self, name=None):
        if name is None:
            name = 'TBSCertificate'
        super(TBSCertificate, self).__init__(explicit=True, name=name)

        _def = self.ctx_tag_def(0, Version())
        self.add(_def, name='version', opt=True, default=_def.create(0))
        self.add(CertificateSerialNumber(), name='serialNumber')
        self.add(AlgorithmIdentifier(), name='signature')
        self.add(Name(), name='issuer')
        self.add(Validity(), name='validity')
        self.add(Name(), name='subject')
        self.add(SubjectPublicKeyInfo(), name='subjectPublicKeyInfo')
        _def = self.ctx_tag_def(1, UniqueIdentifier(), explicit=False)
        self.add(_def, name='issuerUniqueId', opt=True)
        _def = self.ctx_tag_def(2, UniqueIdentifier(), explicit=False)
        self.add(_def, name='subjectUniqueId', opt=True)
        _def = self.ctx_tag_def(3, Extensions())
        self.add(_def, name='extensions', opt=True)


class Version(VASN1DefInteger):
    """:term:`ASN.1` type for certificate version."""
    def __init__(self, name=None):
        if name is None:
            name = 'Version'
        super(Version, self).__init__(name=name)


class CertificateSerialNumber(VASN1DefInteger):
    """:term:`ASN.1` type for certificate serial number."""
    def __init__(self, name=None):
        if name is None:
            name = 'CertificateSerialNumber'
        super(CertificateSerialNumber, self).__init__(name=name)


class AlgorithmIdentifier(VASN1DefSequence):
    """:term:`ASN.1` type for algorithm identifier."""
    def __init__(self, name=None):
        if name is None:
            name = 'AlgorithmIdentifier'
        super(AlgorithmIdentifier, self).__init__(explicit=True, name=name)
        self.add(VASN1DefObjectIdentifier(), name='algorithm')
        self.add(VASN1DefUniversal(allow_unknown=True), name='parameters')


class Name(VASN1DefChoice):
    """:term:`ASN.1` structure for :term:`X.509` Name."""
    def __init__(self, name=None):
        if name is None:
            name = 'Name'
        super(Name, self).__init__(name=name)
        self.add(RDNSequence())


class RDNSequence(VASN1DefSequenceOf):
    """Sequence of RDN used to represent a :class:`Name`\ ."""
    def __init__(self, name=None):
        if name is None:
            name = 'RDNSequence'
        asn1def = RelativeDistinguishedName()
        super(RDNSequence, self).__init__(asn1def, name=name)


class RelativeDistinguishedName(VASN1DefSetOf):
    """RelativeDistinguishedName type held by :class:`RDNSequence`\ ."""
    def __init__(self, name=None):
        if name is None:
            name = 'RelativeDistinguishedName'
        asn1def = AttributeTypeAndValue()
        super(RelativeDistinguishedName, self).__init__(asn1def, name=name)


class AttributeTypeAndValue(VASN1DefSequence):
    """Attribute Type and Value."""
    def __init__(self, name=None):
        if name is None:
            name='AttributeTypeAndValue'
        super(AttributeTypeAndValue, self).__init__(explicit=True, name=name)
        self.add(AttributeType(), name='type')
        self.add(AttributeValue(), name='value')


class AttributeType(VASN1DefObjectIdentifier):
    """Attribute Type of an :class:`AttributeTypeAndValue`."""
    def __init__(self, name=None):
        if name is None:
            name = 'AttributeType'
        super(AttributeType, self).__init__(name=name)


class AttributeValue(VASN1DefUniversal):
    """Attribute Value of an :class:`AttributeTypeAndValue`."""
    def __init__(self, name=None):
        if name is None:
            name='AttributeValue'
        super(AttributeValue, self).__init__(allow_unknown=True, name=name)


class Validity(VASN1DefSequence):
    """:term:`ASN.1` type for certificate validity."""
    def __init__(self, name=None):
        if name is None:
            name = 'Validity'
        super(Validity, self).__init__(explicit=True, name=name)
        self.add(Time(), name='notBefore')
        self.add(Time(), name='notAfter')


class Time(VASN1DefChoice):
    """:term:`ASN.1` type for time value of certificate :class:`Validity`\ ."""
    def __init__(self, name=None):
        if name is None:
            name = 'Time'
        super(Time, self).__init__(name=name)
        self.add(VASN1DefUTCTime())
        self.add(VASN1DefGeneralizedTime())


class SubjectPublicKeyInfo(VASN1DefSequence):
    """:term:`ASN.1` type for subject key information."""
    def __init__(self, name=None):
        if name is None:
            name = 'SubjectPublicKeyInfo'
        super(SubjectPublicKeyInfo, self).__init__(explicit=True, name=name)
        self.add(AlgorithmIdentifier(), name='algorithm')
        self.add(VASN1DefBitString(), name='subjectPublicKey')


class UniqueIdentifier(VASN1DefBitString):
    """:term:`ASN.1` type for cert subject or issuer unique identifier."""
    def __init__(self, name=None):
        if name is None:
            name = 'UniqueIdentifier'
        super(UniqueIdentifier, self).__init__(name=name)


class Extensions(VASN1DefSequenceOf):
    """:term:`ASN.1` type for certificate extension list."""
    def __init__(self, name=None):
        if name is None:
            name = 'Extensions'
        asn1def = Extension()
        super(Extensions, self).__init__(asn1def, name=name)


class Extension(VASN1DefSequence):
    """:term:`ASN.1` type for an individual certificate extension."""
    def __init__(self, name=None):
        if name is None:
            name = 'Extension'
        super(Extension, self).__init__(explicit=True, name=name)
        self.add(VASN1DefObjectIdentifier(), name='extnID')
        self.add(VASN1DefBoolean(), name='critical', opt=True,
                 default=False)
        self.add(VASN1DefOctetString(), name='extnValue')


class KeyIdentifier(VASN1DefOctetString):
    """:term:`ASN.1` type for KeyIdentifier."""
    def __init__(self, name=None):
        if name is None:
            name = 'KeyIdentifier'
        super(KeyIdentifier, self).__init__(name=name)


class SubjectKeyIdentifier(KeyIdentifier):
    """:term:`ASN.1` type for SubjectKeyIdentifier extension value.

    The extension must appear in all conforming CA certificates (basic
    constraint with 'cA' field set to True). The value must be the
    value placed in the key identifier field of the Authority Key
    Identifier extension. The extension *must not* be marked critical.

    """

    def __init__(self, name=None):
        if name is None:
            name = 'SubjectKeyIdentifier'
        super(SubjectKeyIdentifier, self).__init__(name=name)

    id_ce = VObjectIdentifier(2, 5, 29, 14)
    """Extension identifier"""


class KeyUsage(VASN1DefBitString):
    """:term:`ASN.1` type for KeyUsage extension value.

    Significante of bits held:

    +-----+------------------+
    | Bit | Usage            |
    +=====+==================+
    |  0  | digitalSignature |
    +-----+------------------+
    |  1  | nonRepudiation   |
    +-----+------------------+
    |  2  | keyEncipherment  |
    +-----+------------------+
    |  3  | dataEncipherment |
    +-----+------------------+
    |  4  | keyAgreement     |
    +-----+------------------+
    |  5  | keyCertSign      |
    +-----+------------------+
    |  6  | cRLSign          |
    +-----+------------------+
    |  7  | encipherOnly     |
    +-----+------------------+
    |  8  | decipherOnly     |
    +-----+------------------+

    Should be marked 'critical' when used as an extension.

    """
    def __init__(self, name=None):
        if name is None:
            name = 'KeyUsage'
        super(KeyUsage, self).__init__(name=name)

    id_ce = VObjectIdentifier(2, 5, 29, 15)
    """Extension identifier"""


class BasicConstraints(VASN1DefSequence):
    """:term:`ASN.1` type for BasicConstraints extension value.

    Must be included as 'critical' in all CA certificates.

    """
    def __init__(self, explicit=False, name=None):
        if name is None:
            name = 'BasicConstraints'
        super(BasicConstraints, self).__init__(name=name)
        self.add(VASN1DefBoolean(), name='cA', default=False)
        self.add(VASN1DefInteger(), name='pathLenConstraint', opt=True)

    id_ce = VObjectIdentifier(2, 5, 29, 19)
    """Extension identifier"""


class AuthorityKeyIdentifier(VASN1DefSequence):
    """:term:`ASN.1` type for AuthorityKeyIdentifier extension value.

    The extension must be included for CA-generated certificates,
    except for self-signed certficates.

    authorityCertIssuer and authorityCertSerialNumber must either both
    be present, or both be absent. The extension *must not* be marked
    critical.

    """
    def __init__(self, name=None):
        if name is None:
            name = 'AuthorityKeyIdentifier'
        super(AuthorityKeyIdentifier, self).__init__(explicit=False, name=name)

        _def = self.ctx_tag_def(0, KeyIdentifier())
        self.add(_def, name='keyIdentifier', opt=True)
        _def = self.ctx_tag_def(1, GeneralNames())
        self.add(_def, name='authorityCertIssuer', opt=True)
        _def = self.ctx_tag_def(2, CertificateSerialNumber())
        self.add(_def, name='authorityCertSerialNumber', opt=True)

    id_ce = VObjectIdentifier(2, 5, 29, 35)
    """Extension identifier"""


class GeneralNames(VASN1DefSequenceOf):
    """:term:`ASN.1` data type for GeneralNames."""
    def __init__(self, name=None):
        if name is None:
            name = 'GeneralNames'
        asn1def = GeneralName()
        super(GeneralNames, self).__init__(asn1def, name=name)


class GeneralName(VASN1DefChoice):
    """:term:`ASN.1` data type for GeneralName."""
    def __init__(self, name=None):
        if name is None:
            name = 'GeneralName'
        super(GeneralName, self).__init__(name=name)

        _tdef = self.ctx_tag_def
        self.add(_tdef(0, AnotherName()), name='otherName')
        self.add(_tdef(1, VASN1DefIA5String()), name='rfc822Name')
        self.add(_tdef(2, VASN1DefIA5String()), name='dNSName')
        # context tag 3 not (yet) supported
        self.add(_tdef(4, Name()), name='directoryName')
        # context tag 5 not (yet) supported
        self.add(_tdef(6, VASN1DefIA5String()),
                 name='uniformResourceIdentifier')
        self.add(_tdef(7, VASN1DefOctetString()), name='iPAddress')
        self.add(_tdef(8, VASN1DefObjectIdentifier()), name='registeredID')


class AnotherName(VASN1DefSequence):
    """:term:`ASN.1` data type for AnotherName."""
    def __init__(self, name=None):
        if name is None:
            name = 'AnotherName'
        super(AnotherName, self).__init__(name=name)
        _ctag = lambda n: VASN1Tag(VASN1Tag.CONTEXT, n)
        self.add(VASN1DefObjectIdentifier(), name='type-id')
        _def = self.ctx_tag_def(0, VASN1DefUniversal(allow_unknown=True))
        self.add(_def, name='value')
