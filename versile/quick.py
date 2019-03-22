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

"""Quick access to frequently used classes."""
from __future__ import print_function, unicode_literals

from versile.internal import _vexport

from versile.common.processor import VProcessor, VProcessorError
from versile.common.util import VByteBuffer, VLockable, VResult, VNoResult
from versile.common.util import VHaveResult, VCancelledResult
from versile.conf import Versile
from versile.crypto import VCrypto, VCryptoException
from versile.crypto.auth import VAuth
from versile.crypto.rand import VUrandom
from versile.crypto.x509 import VX509Crypto, VX509Format
from versile.crypto.x509.cert import VX509Name, VX509Certificate
from versile.reactor.io.link import VLinkAgent
from versile.reactor.io.service import VOPService
from versile.reactor.io.sock import VSocketBase
from versile.reactor.io.url import VUrl
from versile.orb.entity import VBoolean, VBytes, VCallError, VFloat, VEntity
from versile.orb.entity import VException, VIOContext, VInteger, VNone
from versile.orb.entity import VObject, VProxy, VReference, VString
from versile.orb.entity import VTagged, VTuple, VSimulatedException
from versile.orb.error import VEntityError, VEntityReaderError
from versile.orb.error import VEntityWriterError, VLinkError
from versile.orb.external import VExternal, doc, doc_with
from versile.orb.external import meta, meta_as, publish
from versile.orb.service import VGatewayFactory
from versile.orb.url import VUrlException
from versile.orb.util import VLinkMonitor
from versile.orb.validate import vchk, vmax, vmin, vset, vtyp
from versile.vse import VSEResolver

__all__ = ['Versile', 'VUrl', 'VUrlException', 'VOPService',
           'VExternal', 'doc', 'doc_with',
           'meta', 'meta_as', 'publish', 'VBoolean', 'VBytes', 'VCallError',
           'VFloat', 'VEntity', 'VException', 'VIOContext', 'VInteger',
           'VNone', 'VObject', 'VProxy', 'VReference', 'VString',
           'VTagged', 'VTuple', 'VSimulatedException', 'VEntityError',
           'VEntityReaderError', 'VEntityWriterError', 'VLinkError',
           'VCrypto', 'VCryptoException', 'VAuth', 'VX509Name',
           'VX509Certificate', 'VUrandom', 'VX509Crypto', 'VX509Format',
           'VByteBuffer', 'VLockable', 'VProcessor', 'VProcessorError',
           'VResult', 'VHaveResult', 'VNoResult', 'VCancelledResult',
           'VGatewayFactory', 'VSEResolver', 'VLinkMonitor', 'socket_pair',
           'socket_vtp_link', 'link_pair', 'vchk', 'vmax', 'vmin',
           'vset', 'vtyp']
__all__ = _vexport(__all__)

socket_pair = VSocketBase.create_native_pair
"""See :meth:`versile.reactor.io.sock.VSocketBase.create_native_pair`\ ."""

socket_vtp_link = VLinkAgent.from_socket
"""See :meth:`versile.reactor.io.link.VLinkAgent.from_socket`\ ."""

link_pair = VLinkAgent.create_pair
"""See :meth:`versile.reactor.io.link.VLinkAgent.create_pair`\ ."""
