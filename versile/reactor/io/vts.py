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
"""Reactor based implementation of the :term:`VTS` specification."""
from __future__ import print_function, unicode_literals

import weakref

from versile.internal import _b2s, _s2b, _ssplit, _vexport, _b_ord, _b_chr
from versile.internal import _pyver
from versile.common.iface import implements, abstract, peer
from versile.common.log import VLogger
from versile.common.util import VByteBuffer, VConfig, bytes_to_posint
from versile.crypto import VCrypto, VCryptoException
from versile.crypto.rand import VUrandom, VConstantGenerator
from versile.crypto.rand import VPseudoRandomHMAC
from versile.crypto.x509 import VX509Format
from versile.crypto.x509.cert import VX509Certificate, VX509Name
from versile.orb.entity import VEntity, VIOContext
from versile.reactor import IVReactorObject
from versile.reactor.io import VByteIOPair
from versile.reactor.io import IVByteConsumer, IVByteProducer
from versile.reactor.io import VIOControl, VIOMissingControl, VIOError

__all__ = ['VSecure', 'VSecureClient', 'VSecureConfig', 'VSecureServer']
__all__ = _vexport(__all__)


@abstract
@implements(IVReactorObject)
class VSecure(object):
    """Channel bridge for a :term:`VTS` secure transport.

    The bridge connects a byte consumer/producer interface for
    plaintext I/O with an interface for ciphertext I/O. The plaintext
    interface is available from the :attr:`plain_io` property. The
    ciphertext I/O interface is available as :attr:`cipher_io`\ .

    .. note::

        The specification states that each side of a secure channel
        takes either the role of \"client\" or \"server\"\ . The
        classes :class:`VSecureClient` and :class:`VSecureServer`
        provide base classes for the respective roles. The
        :class:`VSecure` class is abstract and should not be directly
        instantiated.

    The ciphertext interface performs a protocol handshake and secure
    connection handshake before plaintext/ciphertext conversion is
    initiated.

    :param reactor:      channel reactor
    :param keypair:      keypair for secure handshake
    :type  keypair:      :class:`versile.crypto.VAsymmetricKey`
    :param identity:     an identity to assume (or None)
    :type  identity:     :class:`versile.crypto.x509.cert.VX509Name`
    :param certificates: certificate chain
    :type  certificates: :class:`versile.crypto.x509.cert.VX509Certificate`\ ,
    :param p_auth:       connection authorizer
    :type  p_auth:       :class:`versile.crypto.auth.VAuth`
    :param crypto:       crypto provider (default if None)
    :type  crypto:       :class:`versile.crypto.VCrypto`
    :param rand:         secure rand generator (def. if None)
    :type  rand:         :class:`versile.crypto.rand.VByteGenerator`
    :param conf:         additional configuration
    :type  conf:         :class:`VSecureConfig` (default if None)

    If set *identity* specifies what identity is being assumed for the
    connection. If *certificates* is set then it defines a certificate
    chain associated with *keypair*\ , which may include an identity
    set on the certificate. Only one of *identity* and *certificates*
    should be set.

    When *p_auth* is set then the object is queried whether the peer
    connection can be approved.

    .. automethod:: _peer_pub_key_received

    """

    def __init__(self, reactor, keypair, identity=None, certificates=None,
                 p_auth=None, crypto=None, rand=None, conf=None):
        self.__reactor = reactor
        self._crypto = VCrypto.lazy(crypto)
        if rand is None:
            rand = VUrandom()
        self._rand = rand
        self._keypair = keypair
        self._identity = identity
        self._certificates = certificates
        self._p_auth = p_auth
        if conf is None:
            conf = VSecureConfig()
        self._config = conf

        # Generate list of (available) handshake hash methods
        hhashes = []
        for hname in self._config.hhashes:
            if hname in self._crypto.hash_types:
                hhashes.append(hname)
            elif self._config.hreq:
                raise VCryptoException('Hash method not available')
        if not hhashes:
            raise VCryptoException('No hash methods available from provider')
        self._hmac_hashes = tuple(hhashes)

        # Generate list of (available) ciphers
        ciphers = []
        for cname, modes in self._config.ciphers:
            if cname in self._crypto.block_ciphers:
                cm = []
                c = self._crypto.block_cipher(cname)
                for m in modes:
                    if m in c.modes:
                        cm.append(m)
                    elif self._config.creq:
                        raise VCryptoException('Cipher mode not available')
                if cm:
                    ciphers.append((cname, tuple(cm)))
            elif self._config.creq:
                raise VCryptoException('Cipher not available from provider')
        if not ciphers:
            raise VCryptoException('No ciphers available from provider')
        self._ciphers = tuple(ciphers)

        # Generate list of (available) hash methods
        hashes = []
        for hname in self._config.hashes:
            if hname in self._crypto.hash_types:
                hashes.append(hname)
            elif self._config.hreq:
                raise VCryptoException('Hash method not available')
        if not hashes:
            raise VCryptoException('No hash methods available from provider')
        self._hashes = tuple(hashes)

        max_keylen = conf.max_keylen
        if max_keylen is None:
            self._max_keylen = None
        else:
            self._max_keylen = bytes_to_posint(max_keylen*b'\xff')

        self._peer_pub_key = None
        self._peer_certificates = None
        self._peer_identity = None
        self._msg_encrypter = None
        self._msg_decrypter = None

        self.__have_protocol = False
        self.__PROTO_MAXLEN = 32
        self.__proto_data = []
        self.__proto_len = 0
        self.__proto_send = VByteBuffer(b'VTS_DRAFT-0.8\n')
        self._can_send_proto = False

        self._handshaking = None
        self._end_handshaking = False
        self._handshake_reader = None
        self._handshake_writer = None
        self._handshake_handler = None

        self.__pc_producer = None
        self.__pc_consumed = 0
        self.__pc_consume_lim = 0
        self.__pc_eod = False
        self.__pc_eod_clean = None
        self.__pc_aborted = False
        self.__pc_rbuf = VByteBuffer()
        self.__pc_rbuf_len = conf.rbuf_len

        self.__pp_consumer = None
        self.__pp_produced = 0
        self.__pp_produce_lim = 0
        self.__pp_closed = False
        self.__pp_wbuf = VByteBuffer()
        self.__pp_max_write = conf.max_write
        self.__pp_sent_eod = False

        self.__cc_producer = None
        self.__cc_consumed = 0
        self.__cc_consume_lim = 0
        self.__cc_eod = False
        self.__cc_eod_clean = None
        self.__cc_aborted = False
        self.__cc_rbuf = VByteBuffer()
        self.__cc_rbuf_len = conf.rbuf_len

        self.__cp_consumer = None
        self.__cp_produced = 0
        self.__cp_produce_lim = 0
        self.__cp_closed = False
        self.__cp_wbuf = VByteBuffer()
        self.__cp_max_write = conf.max_write
        self.__cp_sent_eod = False

        self.__pc_iface = self.__pp_iface = None
        self.__cc_iface = self.__cp_iface = None

        # Set up a local logger for convenience
        self._logger = VLogger(prefix='VTS')
        self._logger.add_watcher(self.reactor.log)

    def __del__(self):
        self._logger.debug('Dereferenced')

    @property
    def plain_consume(self):
        """Holds the plaintext consumer interface to the VTS bridge."""
        cons = None
        if self.__pc_iface:
            cons = self.__pc_iface()
        if not cons:
            cons = _VPlaintextConsumer(self)
            self.__pc_iface = weakref.ref(cons)
        return cons

    @property
    def plain_produce(self):
        """Holds the plaintext producer interface to the VTS bridge."""
        prod = None
        if self.__pp_iface:
            prod = self.__pp_iface()
        if not prod:
            prod = _VPlaintextProducer(self)
            self.__pp_iface = weakref.ref(prod)
        return prod

    @property
    def plain_io(self):
        """Plaintext I/O (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.plain_consume, self.plain_produce)

    @property
    def cipher_consume(self):
        """Holds the plaintext consumer interface to the VTS bridge."""
        cons = None
        if self.__cc_iface:
            cons = self.__cc_iface()
        if not cons:
            cons = _VCiphertextConsumer(self)
            self.__cc_iface = weakref.ref(cons)
        return cons

    @property
    def cipher_produce(self):
        """Holds the plaintext producer interface to the VTS bridge."""
        prod = None
        if self.__cp_iface:
            prod = self.__cp_iface()
        if not prod:
            prod = _VCiphertextProducer(self)
            self.__cp_iface = weakref.ref(prod)
        return prod

    @property
    def cipher_io(self):
        """Ciphertext I/O (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.cipher_consume, self.cipher_produce)

    @property
    def reactor(self):
        """The object's reactor.

        See :class:`versile.reactor.IVReactorObject`

        """
        return self.__reactor

    @property
    def config(self):
        """The configuration object set on the channel bridge."""
        return self._config

    def _gen_keys(self, s_seed, c_seed):
        """Generates a set of keys for a negotiated handshake.

        :param s_seed: server keyseed
        :type  s_seed: bytes
        :param c_seed: server keyseed
        :type  c_seed: bytes
        :returns:      (c_key, c_iv, c_mac), (s_key, s_iv, s_mac)

        """
        keyseed = b'vts key expansion' + s_seed + c_seed
        hmac_cls = self._crypto.hash_cls(self._hmac_name)
        cipher = self._crypto.block_cipher(self._cipher_name)
        _prf = VPseudoRandomHMAC(hmac_cls, b'', keyseed)
        c_key = cipher.key_factory.generate(_prf)
        s_key = cipher.key_factory.generate(_prf)
        c_iv = _prf(cipher.blocksize(c_key))
        s_iv = _prf(cipher.blocksize(s_key))
        c_mac = _prf(cipher.blocksize(c_key))
        s_mac = _prf(cipher.blocksize(s_key))

        return (c_key, c_iv, c_mac), (s_key, s_iv, s_mac)

    @peer
    def _pc_consume(self, data, clim):
        if self.__pc_eod:
            raise VIOError('Consumer already received end-of-data')
        elif not self._pc_producer:
            raise VIOError('No connected producer')
        elif not data:
            raise VIOError('No data to consume')
        max_cons = self.__lim(self.__pc_consumed, self.__pc_consume_lim)
        if max_cons == 0:
            raise VIOError('Consume limit exceeded')
        if clim is not None and clim > 0:
            max_cons = min(max_cons, clim)

        buf_len = len(self.__pc_rbuf)
        self.__pc_rbuf.append_list(data.pop_list(max_cons))
        self.__pc_consumed += len(self.__pc_rbuf) - buf_len

        self._cp_do_produce()

        # Update plaintext consume limit and return
        self.__pc_update_lim()
        return self.__pc_consume_lim

    @peer
    def _pc_end_consume(self, clean):
        if self.__pc_eod:
            return
        self.__pc_eod = True
        self.__pc_eod_clean = clean

        if self.__cp_consumer:
            self._cp_do_produce()
        else:
            self.__pc_abort()

    def _pc_abort(self):
        if not self.__pc_aborted:
            self.__pc_aborted = True
            self.__pc_eod = True
            # Clear buffers
            self.__pc_rbuf.remove()
            self._msg_encrypter = None
            self.__cp_wbuf.remove()
            # Abort interfaces
            if self.__cp_consumer:
                self.__cp_consumer.abort()
                self._cp_detach()
            if self.__pc_producer:
                self.__pc_producer.abort()
                self._pc_detach()

    def _pc_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._pc_attach, producer, rthread=True)
            return

        if self.__pc_producer is producer:
            return
        if self.__pc_eod:
            raise VIOError('Consumer already received end-of-data')
        elif self.__pc_producer:
            raise VIOError('Producer already connected')
        self.__pc_producer = producer
        self.__pc_consumed = self.__pc_consume_lim = 0
        producer.attach(self.plain_consume)
        if not self._handshaking and self.__have_protocol:
            self._enable_plaintext()
        try:
            producer.control.notify_consumer_attached(self.plain_consume)
        except VIOMissingControl:
            pass

    def _pc_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._pc_detach, rthread=True)
            return

        if self.__pc_producer:
            prod, self.__pc_producer = self.__pc_producer, None
            self.__pc_consumed = self.__pc_consume_lim = 0
            prod.detach()

    @peer
    def _pp_can_produce(self, limit):
        if not self.__pp_consumer:
            raise VIOError('No attached consumer')
        if limit is None or limit < 0:
            if (not self.__pp_produce_lim is None
                and not self.__pp_produce_lim < 0):
                self.__pp_produce_lim = limit
                self.reactor.schedule(0.0, self.__pp_do_produce)
        else:
            if (self.__pp_produce_lim is not None
                and 0 <= self.__pp_produce_lim < limit):
                self.__pp_produce_lim = limit
                self.reactor.schedule(0.0, self.__pp_do_produce)

    def _pp_abort(self):
        self._cc_abort()

    def _pp_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._pp_attach, consumer, rthread=True)
            return

        if self.__pp_consumer is consumer:
            return
        if self.__pp_consumer:
            raise VIOError('Consumer already attached')
        elif self.__pp_eod:
            raise VIOError('Producer already reached end-of-data')
        self.__pp_consumer = consumer
        self.__pp_produced = self.__pp_produce_lim = 0
        consumer.attach(self.plain_produce)

        if self.__cc_producer:
            self.__cc_consume_lim = self.__lim(len(self.__cc_rbuf),
                                               self.__cc_rbuf_len)
            self.__cc_producer.can_produce(self.__cc_consume_lim)
        try:
            consumer.control.notify_producer_attached(self.plain_produce)
        except VIOMissingControl:
            pass

    def _pp_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._pp_detach, rthread=True)
            return

        if self.__pp_consumer:
            cons, self.__pp_consumer = self.__pp_consumer, None
            cons.detach()
            self.__pp_produced = self.__pp_produce_lim = 0

    @peer
    def _cc_consume(self, data, clim):
        if self.__cc_eod:
            raise VIOError('Consumer already received end-of-data')
        elif not self._cc_producer:
            raise VIOError('No connected producer')
        elif not data:
            raise VIOError('No data to consume')

        max_cons = self.__lim(self.__cc_consumed, self.__cc_consume_lim)
        if max_cons == 0:
            raise VIOError('Consume limit exceeded')
        if clim is not None and clim > 0:
            max_cons = min(max_cons, clim)

        buf_len = len(self.__cc_rbuf)
        self.__cc_rbuf.append_list(data.pop_list(max_cons))
        self.__cc_consumed += len(self.__cc_rbuf) - buf_len

        # If True then run a produce() cycle before method returns
        cipher_produce = plain_produce = False

        # Perform protocol handshake
        if not self.__have_protocol:
            cipher_produce = True
            self.__consume_protocol()

        if self._handshaking and self.__have_protocol:
            cipher_produce = True
            if self.__cc_rbuf and self._handshake_reader:
                num_read = self._handshake_reader.read(self.__cc_rbuf)
                _lim = self._config.hshake_lim
                if (_lim is not None
                    and 0 <= _lim < self._handshake_reader.num_read):
                    raise VIOError('Handshake message limit exceeded')
                if self._handshake_reader.done():
                    result = self._handshake_reader.result()._v_native()
                    self._handshake_reader = None
                    self.reactor.schedule(0.0, self._handshake_handler, result)

        # Handshake is now supposed to be completed
        if not self._handshaking and self.__have_protocol:
            plain_produce = True
            while self.__cc_rbuf:
                num_read = self._msg_decrypter.read(self.__cc_rbuf)
                try:
                    decrypted = self._msg_decrypter.done()
                except VCryptoException:
                    # Critical error, aborting the cc interface
                    self.reactor.schedule(0.0, self._cc_abort)
                    raise VIOError('Ciphertext decryption error')
                else:
                    if decrypted:
                        self.__pp_wbuf.append(self._msg_decrypter.result())
                        self._msg_decrypter.reset()

        # Run produce/update cycle
        if cipher_produce:
            self.reactor.schedule(0.0, self._cp_do_produce)
        if plain_produce:
            self.__pp_do_produce()

        # Update and return ciphertext consumer limit
        self.__cc_update_lim()
        return self.__cc_consume_lim

    @peer
    def _cc_end_consume(self, clean):
        if self.__cc_eod:
            return
        self.__cc_eod = True
        self.__cc_eod_clean = clean

        if self.__pp_consumer:
            self.__pp_do_produce()
        else:
            self.__cc_abort()

    def _cc_abort(self):
        if not self.__cc_aborted:
            self.__cc_aborted = True
            self.__cc_eod = True
            # Clear buffers
            self.__pp_wbuf.remove()
            self._msg_decrypter = None
            self.__cc_rbuf.remove()
            # Perform cascading abort
            if self.__pp_consumer:
                self.__pp_consumer.abort()
                self._pp_detach()
            if self.__cc_producer:
                self.__cc_producer.abort()
                self._cc_detach()

    def _cc_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._cc_attach, producer, rthread=True)
            return

        if self.__cc_producer is producer:
            return
        if self.__cc_eod:
            raise VIOError('Consumer already received end-of-data')
        elif self.__cc_producer:
            raise VIOError('Producer already connected')
        self.__cc_producer = producer
        self.__cc_consumed = 0
        self.__cc_consume_lim = self.__lim(len(self.__cc_rbuf),
                                           self.__cc_rbuf_len)
        producer.attach(self.cipher_consume)
        producer.can_produce(self.__cc_consume_lim)
        try:
            producer.control.notify_consumer_attached(self.cipher_consume)
        except VIOMissingControl:
            pass

    def _cc_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._cc_detach, rthread=True)
            return

        if self.__cc_producer:
            prod, self.__cc_producer = self.__cc_producer, None
            self.__cc_consumed = self.__cc_consume_lim = 0
            prod.detach()

    @peer
    def _cp_can_produce(self, limit):
        if not self.__cp_consumer:
            raise VIOError('No attached consumer')
        if limit is None or limit < 0:
            if (not self.__cp_produce_lim is None
                and not self.__cp_produce_lim < 0):
                self.__cp_produce_lim = limit
                self.reactor.schedule(0.0, self._cp_do_produce)
        else:
            if (self.__cp_produce_lim is not None
                and 0 <= self.__cp_produce_lim < limit):
                self.__cp_produce_lim = limit
                self.reactor.schedule(0.0, self._cp_do_produce)

    def _cp_abort(self):
        self._pc_abort()

    def _cp_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._cp_attach, consumer, rthread=True)
            return

        if self.__cp_consumer is consumer:
            return
        if self.__cp_consumer:
            raise VIOError('Consumer already attached')
        elif self.__cp_eod:
            raise VIOError('Producer already reached end-of-data')
        self.__cp_consumer = consumer
        self.__cp_produced = self.__cp_produce_lim = 0
        consumer.attach(self.cipher_produce)

        if self.__pc_producer:
            if not self._handshaking and self.__have_protocol:
                self._enable_plaintext()
        try:
            consumer.control.notify_producer_attached(self.cipher_produce)
        except VIOMissingControl:
            pass

    def _cp_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._cp_detach, rthread=True)
            return

        if self.__cp_consumer:
            cons, self.__cp_consumer = self.__cp_consumer, None
            cons.detach()
            self.__cp_produced = self.__cp_produce_lim = 0

    @property
    def _pc_control(self):
        if self._cp_consumer:
            return self._cp_consumer.control
        else:
            return VIOControl()

    @property
    def _pc_producer(self):
        return self.__pc_producer

    @property
    def _pc_flows(self):
        return (self.cipher_produce,)

    @property
    def _pp_control(self):
        class _Control(VIOControl):
            def __init__(self, vts):
                self.__vts = vts
            def req_producer_state(self, consumer):
                # Perform request pass-through
                prod = self.__vts.cipher_consume.producer
                if prod:
                    try:
                        prod.control.req_producer_state(consumer)
                    except VIOMissingControl:
                        pass
                # Provide authorization information
                if self.__vts._peer_pub_key:
                    def notify():
                        cons = self.__vts.plain_produce.consumer
                        if cons:
                            try:
                                key = self.__vts._peer_pub_key
                                certs = self.__vts._peer_certificates
                                identity = self.__vts._peer_identity
                                _auth = cons.control.authorize
                                result = _auth(key, certs, identity, 'VTS')
                            except VIOMissingControl:
                                pass
                            else:
                                if not result:
                                    # Connection not authorized, abort
                                    self.reactor.schedule(0.0, self._pc_abort)
                                    self.reactor.schedule(0.0, self._pp_abort)
                    self.__vts.reactor.schedule(0.0, notify)
        return _Control(self)

    @property
    def _pc_twoway(self):
        return True

    @property
    def _pc_reverse(self):
        return self.plain_produce

    @property
    def _pp_consumer(self):
        return self.__pp_consumer

    @property
    def _pp_flows(self):
        return (self.cipher_consume,)

    @property
    def _pp_twoway(self):
        return True

    @property
    def _pp_reverse(self):
        return self.plain_consume

    @property
    def _cc_control(self):
        if self._pp_consumer:
            return self._pp_consumer.control
        else:
            return VIOControl()

    @property
    def _cc_producer(self):
        return self.__cc_producer

    @property
    def _cc_flows(self):
        return (self.plain_produce,)

    @property
    def _cc_twoway(self):
        return True

    @property
    def _cc_reverse(self):
        return self.cipher_produce

    @property
    def _cp_control(self):
        if self._pc_producer:
            return self._pc_producer.control
        else:
            return VIOControl()

    @property
    def _cp_consumer(self):
        return self.__cp_consumer

    @property
    def _cp_flows(self):
        return (self.plain_consume,)

    @property
    def _cp_twoway(self):
        return True

    @property
    def _cp_reverse(self):
        return self.cipher_consume

    def _enable_plaintext(self):
        if self.__pc_producer and not self.__pc_eod:
            old_lim = self.__pc_consume_lim
            self.__pc_update_lim()
            if self.__pc_consume_lim != old_lim:
                self.reactor.schedule(0.0, self.__pc_send_limit)

    def __pc_update_lim(self):
        if self.__pc_producer and not self.__pc_eod:
            if not self._handshaking and self.__have_protocol:
                max_add = self.__lim(len(self.__pc_rbuf), self.__pc_rbuf_len)
                if max_add >= 0:
                    self.__pc_consume_lim = self.__pc_consumed + max_add
                else:
                    self.__pc_consume_lim = -1

    def __pc_send_limit(self):
        if self.__pc_producer:
            self.__pc_producer.can_produce(self.__pc_consume_lim)

    def __pp_do_produce(self):
        if not self.__pp_consumer:
            return

        if self.__pp_eod:
            if self.__pp_consumer and not self.__pp_sent_eod:
                self.__pp_consumer.end_consume(self.__cc_eod_clean)
                self.__pp_sent_eod = True
            return

        if self.__pp_wbuf:
            if (self.__pp_produce_lim is not None
                and 0 <= self.__pp_produce_lim <= self.__pp_produced):
                return

            old_lim = self.__pp_produce_lim
            max_write = self.__lim(self.__pp_produced, self.__pp_produce_lim)
            if max_write < 0:
                max_write = self.__pp_max_write
            max_write = min(max_write, self.__pp_max_write)
            buf_len = len(self.__pp_wbuf)
            if max_write != 0:
                _l = self.__pp_consumer.consume(self.__pp_wbuf, clim=max_write)
                self.__pp_produce_lim = _l
                self.__pp_produced += buf_len - len(self.__pp_wbuf)

            # If produce limit was updated, schedule another 'produce' batch
            if self.__pp_produce_lim != old_lim:
                self.reactor.schedule(0.0, self.__pp_do_produce)

            # Plaintext produce may have enabled consuming more ciphertext
            if self.__cc_producer and not self.__cc_eod:
                old_lim = self.__cc_consume_lim
                self.__cc_update_lim()
                if self.__cc_consume_lim != old_lim:
                    self.reactor.schedule(0.0, self.__cc_send_limit)

    def __cc_update_lim(self):
        if self.__cc_producer and not self.__cc_eod:
            # Do not update ciphertext consume limit if plaintext
            # produce buffer holds more data than cc read buffer limit
            if (self.__have_protocol and not self._handshaking
                and (self.__pp_produce_lim is not None
                     and self.__pp_produce_lim >= 0)
                and (self.__cc_rbuf_len is not None
                     and len(self.__pp_wbuf) >= self.__cc_rbuf_len >= 0)):
                return

            max_add = self.__lim(len(self.__cc_rbuf), self.__cc_rbuf_len)
            if max_add >= 0:
                self.__cc_consume_lim = self.__cc_consumed + max_add
            else:
                self.__cc_consume_lim = -1

    def __cc_send_limit(self):
        if self.__cc_producer:
            self.__cc_producer.can_produce(self.__cc_consume_lim)

    def _cp_do_produce(self):
        if not self.__cp_consumer:
            return

        if self.__cp_eod:
            if self.__cp_consumer and not self.__cp_sent_eod:
                self.__cp_consumer.end_consume(self.__pc_eod_clean)
                self.__cp_sent_eod = True
            return

        if (self.__cp_produce_lim is not None
            and 0 <= self.__cp_produce_lim <= self.__cp_produced):
            return

        if self.__proto_send and self._can_send_proto:
            max_write = self.__lim(self.__cp_produced, self.__cp_produce_lim)
            if max_write < 0:
                max_write = self.__cp_max_write
            max_write = min(max_write, self.__cp_max_write)
            if max_write != 0 and self.__proto_send:
                buf_len = len(self.__proto_send)
                new_lim = self.__cp_consumer.consume(self.__proto_send,
                                                     clim=max_write)
                self.__cp_produce_lim = new_lim
                self.__cp_produced += buf_len - len(self.__proto_send)
                if not self.__proto_send:
                    self.__proto_send = None
                    #self._logger.debug('Sent protocol hello')
            return

        if self._handshaking and self.__have_protocol:
            if self._handshake_writer:
                max_write = self.__lim(self.__cp_produced,
                                       self.__cp_produce_lim)
                if max_write < 0:
                    max_write = self.__cp_max_write
                max_write = min(max_write, self.__cp_max_write)
                if max_write != 0:
                    send_data = self._handshake_writer.write(max_write)
                    self.__cp_wbuf.append(send_data)
                    new_lim = self.__cp_consumer.consume(self.__cp_wbuf)
                    self.__cp_produce_lim = new_lim
                    if self.__cp_wbuf:
                        raise VIOError('Consume limit violation')
                    self.__cp_produced += len(send_data)
                if self._handshake_writer.done():
                    self._handshake_writer = None
                    if self._end_handshaking:
                        # Handshake complete, enable plaintext
                        self._handshaking = False
                        self._enable_plaintext()
                        self._logger.debug('Handshake completed')

        if not self._handshaking and self.__have_protocol:
            while self.__cp_wbuf or self.__pc_rbuf:
                if (self.__cp_produce_lim is not None
                    and 0 <= self.__cp_produce_lim <= self.__cp_produced):
                    break
                if self.__cp_wbuf:
                    # Write from ciphertext output buffer
                    max_write = self.__lim(self.__cp_produced,
                                           self.__cp_produce_lim)
                    if max_write < 0:
                        max_write = self.__cp_max_write
                    max_write = min(max_write, self.__cp_max_write)
                    if max_write != 0:
                        buf_len = len(self.__cp_wbuf)
                        new_lim = self.__cp_consumer.consume(self.__cp_wbuf,
                                                             clim=max_write)
                        self.__cp_produce_lim = new_lim
                        self.__cp_produced += buf_len - len(self.__cp_wbuf)
                else:
                    # Create new ciphertext from plaintext buffer
                    data = self.__pc_rbuf.pop()
                    msg = self._msg_encrypter.message(data)
                    self.__cp_wbuf.append(msg)

            # Plaintext consume limits may have changed
            if self.__pc_producer and not self.__pc_eod:
                old_lim = self.__pc_consume_lim
                self.__pc_update_lim()
                if self.__pc_consume_lim != old_lim:
                    self.reactor.schedule(0.0, self.__pc_send_limit)

    def _error_dismantle(self):
        """Can use for critical errors to shut down and dismantle."""
        for prod in (self._cc_producer, self._pc_producer):
            if prod:
                prod.abort()
        for cons in (self._cp_consumer, self._pp_consumer):
            if cons:
                cons.abort()

    @abstract
    def _init_handshake(self):
        """Called locally when protocol hello handshake is complete."""
        raise NotImplementedError()

    def _peer_pub_key_received(self, pub_key):
        """Called when a peer public key is received to approve the key.

        :param pub_key: public key received from peer

        This method is called internally during channel handshake; if
        it returns True then the handshake is allowed to proceed,
        otherwise the handshake is aborted.

        The default behavior is to invoke the *auth* parameter that
        was passed to the object when created, by calling
        auth(pub_key) and returning the result. If *auth* was not
        provided (i.e. set to None), then the default behavior is to
        return True.

        """
        if self._config.auth:
            return self._config.auth(pub_key)
        else:
            return True

    def _authorize_identity(self, key, certs, identity):
        """Requests identity authorization from connected plaintext cons chain.

        :returns: True if authorized or no authorization information
        :rtype:   bool

        If the plaintext producer has a connected consumer, a control
        request is sent to request authorization. If there is no
        consumer or the control message cannot be delivered, this is
        considered to be a confirmation of authorization.

        """
        if self.__pp_consumer:
            try:
                cntl = self.__pp_consumer.control
                result = cntl.authorize(key, certs, identity, 'VTS')
            except VIOMissingControl:
                return True
            else:
                return result
        else:
            return True

    def _parse_id_or_certs(self, key, data):
        """

        :param key:  public key
        :type  key:  :class:`versile.crypto.VAsymmetricKey`
        :param data: Identity/Certificate data
        :returns:    (identity, certificate_chain)
        :raises:     :exc:`versile.reactor.io.VIOError`

        """
        if data is None:
            return None, None

        if not (isinstance(data, tuple) and len(data) == 2
                and isinstance(data[0], bool)):
            raise VIOError('Illegal data types')
        is_cert, cdata = data
        if is_cert:
            if not isinstance(cdata, tuple) or not cdata:
                raise VIOError('Illegal certificate list types')
            clist = []
            for cd in cdata:
                if not isinstance(cd, bytes):
                    raise VIOError('Illegal certificate')
                try:
                    c = VX509Certificate.import_cert(cd, fmt=VX509Format.DER)
                except VCryptoException:
                    raise VIOError('Illegal certificate data')
                if (self._max_keylen is not None
                    and 0 <= self._max_keylen < c.subject_key.keydata[0]):
                    raise VIOError('Certificate key exceeds max length')

                if clist and not clist[-1].certified_by(c):
                    raise VIOError('Certificate chain does not validate')
                clist.append(c)

            if key.keydata != clist[0].subject_key.keydata:
                raise VUIError('Peer key does not match first certificate')
            # Should validate subject key matches first certificate
            certificates = tuple(clist)
            identity = certificates[0].subject
            return identity, certificates
        else:
            if not isinstance(cdata, bytes):
                raise VIOError('Illegal identity data type')
            try:
                name = VX509Name.import_name(cdata, fmt=VX509Format.DER)
            except VCryptoException:
                raise VIOError('Illegal identity data')
            return name, None

    def _blockcipher_enc_entity(self, entity, keyseed):
        """Creates a blockcipher encrypted message

        :param entity: entity to encrypt (or lazy-convertible)
        :type  entity: :class:`versile.orb.entity.VEntity`
        :returns:      encrypted message
        :rtype:        bytes

        """
        data = VEntity._v_lazy(entity)._v_write(VIOContext())
        cipher = self._crypto.block_cipher(self._cipher_name)
        hmac_cls = self._crypto.hash_cls(self._hmac_name)
        _prf = VPseudoRandomHMAC(hmac_cls, b'', keyseed)
        key = cipher.key_factory.generate(_prf)
        key_iv = _prf(cipher.blocksize())
        hash_cls = self._crypto.hash_cls(self._hash_name)
        _cfun = cipher.msg_encrypter(hash_cls, self._config.padder, key,
                                     iv=key_iv, mode=self._cipher_mode)
        return _cfun(data)

    def _blockcipher_dec_entity(self, data, keyseed):
        """Deciphers a blockcipher encrypted message

        :param data: data to decrypt
        :type  data: bytes
        :returns:    decrypted entity
        :rtype:      lazy-converted :class:`versile.orb.entity.VEntity`
        :raises:     :exc:`versile.crypto.VCryptoException`

        """
        cipher = self._crypto.block_cipher(self._cipher_name)
        hmac_cls = self._crypto.hash_cls(self._hmac_name)
        _prf = VPseudoRandomHMAC(hmac_cls, b'', keyseed)
        key = cipher.key_factory.generate(_prf)
        key_iv = _prf(cipher.blocksize())
        hash_cls = self._crypto.hash_cls(self._hash_name)
        _dec = cipher.msg_decrypter(hash_cls, key, iv=key_iv,
                                    mode=self._cipher_mode)
        num_read = _dec.read(data)
        if num_read != len(data) or not _dec.done():
            raise VCryptoException('Data did not decrypt')
        entity_data = _dec.result()

        try:
            reader = VEntity._v_reader(VIOContext())
            num_read = reader.read(entity_data)
        except:
            raise VCryptoException('Could not convert to VEntity')
        else:
            if not (reader.done() and num_read == len(entity_data)):
                raise VCryptoException('Could not convert to VEntity')
        return reader.result()._v_native()

    def _asymm_enc_entity(self, entity, key):
        """Creates an asymmetric cipher encrypted message

        :param entity: entity to encrypt (or lazy-convertible)
        :type  entity: :class:`versile.orb.entity.VEntity`
        :param key:  asymmetric key for encryption
        :type  key:  :class:`versile.crypto.VAsymmetricKey`
        :returns:    encrypted entity
        :rtype:      bytes
        :raises:     :exc:`versile.crypto.VCryptoException`

        """
        data = VEntity._v_lazy(entity)._v_write(VIOContext())
        pk_cipher = self._crypto.block_cipher(key.cipher_name)
        hash_cls = self._crypto.hash_cls(self._hash_name)
        _enc = pk_cipher.msg_encrypter(hash_cls, self._config.padder, key)
        return _enc(data)

    def _asymm_dec_entity(self, data, key):
        """Deciphers an asymmetric cipher encrypted message

        :param data: data to decrypt
        :type  data: bytes
        :param key:  asymmetric key for decryption
        :type  key:  :class:`versile.crypto.VAsymmetricKey`
        :returns:    decrypted entity
        :rtype:      lazy-converted :class:`versile.orb.entity.VEntity`
        :raises:     :exc:`versile.crypto.VCryptoException`

        """

        hash_cls = self._crypto.hash_cls(self._hash_name)
        pk_cipher = self._crypto.block_cipher(key.cipher_name)
        dec = pk_cipher.msg_decrypter(hash_cls, key)
        num_read = dec.read(data)
        if not (dec.done() and num_read == len(data)):
            raise VCryptoException('Data package did not decrypt cleanly')
        entity_data = dec.result()
        try:
            reader = VEntity._v_reader(VIOContext())
            num_read = reader.read(entity_data)
        except:
            raise VCryptoException('Data did not decrypt as a VEntity')
        else:
            if not (reader.done() and num_read == len(entity_data)):
                raise VCryptoException('Data did not decrypt as a VEntity')
        return reader.result()._v_native()

    def _gen_msg_enc(self, key, key_iv, key_mac):
        cipher = self._crypto.block_cipher(self._cipher_name)
        hash_cls = self._crypto.hash_cls(self._hash_name)
        return cipher.msg_encrypter(hash_cls, self._config.padder, key,
                                    iv=key_iv, mode=self._cipher_mode,
                                    mac_secret=key_mac)

    def _gen_msg_dec(self, key, key_iv, key_mac):
        cipher = self._crypto.block_cipher(self._cipher_name)
        hash_cls = self._crypto.hash_cls(self._hash_name)
        return cipher.msg_decrypter(hash_cls, key, iv=key_iv,
                                    mode=self._cipher_mode,
                                    mac_secret=key_mac)

    def __consume_protocol(self):
        while self.__cc_rbuf and self.__proto_len < self.__PROTO_MAXLEN:
            byte = self.__cc_rbuf.pop(1)
            self.__proto_data.append(byte)
            self.__proto_len += 1
            if byte == b'\n':
                break
        else:
            if self.__proto_len >= self.__PROTO_MAXLEN:
                raise VIOError('Handshake protocol exceeded %s byte limit'
                               % self.__PROTO_MAXLEN)
        if self.__proto_data and self.__proto_data[-1] == b'\n':
            try:
                header = b''.join(self.__proto_data)
                header = header[:-1]
                parts = _ssplit(header, b'-')
                if len(parts) != 2:
                    raise VIOError('Malformed header (%s parts)' % len(parts))
                name, version = parts
                if name != b'VTS_DRAFT':
                    raise VIOError('Requires protocol VTS')
                if _pyver == 2:
                    _allowed = [bytes(_b_chr(num)) for num in
                                range(ord('0'), ord('9')+1)] + [b'.']
                else:
                    # Using integers for python3
                    _allowed = range(ord('0'), ord('9')+1) + [ord('.')]
                for char in version:
                    if char not in _allowed:
                        raise VIOError('Illegal protocol version number')
                parts = version.split(b'.')
                version = [int(part) for part in parts]
                if version != [0, 8]:
                    raise VIOError('Protocol version %s not supported'
                                   % '.'.join([str(v) for v in version]))
            except VIOError as e:
                self.reactor.schedule(0.0, self._error_dismantle)
                raise e
            else:
                #self._logger.debug('Received protocol hello')
                self.__have_protocol = True
                self._can_send_proto = True
                self._handshaking = True
                self._init_handshake()

    @classmethod
    def __lim(self, base, *lims):
        """Return smallest (lim-base) limit, or -1 if all limits are <0"""
        result = -1
        for lim in lims:
            if lim is not None and lim >= 0:
                lim = max(lim - base, 0)
                if result < 0:
                    result = lim
                result = min(result, lim)
        return result

    @property
    def __pp_eod(self):
        return self.__cc_eod and not (self.__cc_rbuf or self.__pp_wbuf
                                      or (self._msg_decrypter and
                                          self._msg_decrypter.has_data))

    @property
    def __cp_eod(self):
        return self.__cc_eod and not (self.__pc_rbuf or self.__cp_wbuf)

class VSecureClient(VSecure):
    """Client-side channel bridge for a :term:`VTS` secure transport.

    Implements the client side of a :term:`VTS` channel. See :class:`VSecure`
    for general information and constructor arguments.

    """

    def __init__(self, *args, **kargs):
        super(VSecureClient, self).__init__(*args, **kargs)
        self._can_send_proto = True
        if self._keypair is None:
            if self._identity is not None or self._certificates is not None:
                raise TypeError('Identity/certificates requires key')

    def _init_handshake(self):
        self._rand_c = self._rand(32)
        self._srand_c = self._rand(32)
        self._send_hello()

    # VTS protocol step 2: client sends handshake data
    def _send_hello(self):
        msg = (self._hmac_hashes, self._ciphers, self._hashes, self._rand_c,
               self._config.max_keylen, self._config.hshake_lim)
        writer = VEntity._v_lazy(msg)._v_writer(VIOContext())
        self._handshake_reader = VEntity._v_reader(VIOContext())
        self._handshake_writer = writer
        self._handshake_handler = self._send_pubkey
        self.reactor.schedule(0.0, self._cp_do_produce)

    # VTS protocol step 4: client sends public key and secret1
    def _send_pubkey(self, data):
        try:
            # Validate input data format (s_credentials handled further down)
            try:
                (hmac_name, cipher_name, cipher_mode, hash_name, s_rand,
                 s_pubdata, s_credentials, max_keylen, hshake_lim) = data
            except ValueError:
                raise VIOError('Could not unpack data')
            if not (isinstance(hmac_name, unicode)
                    and isinstance(cipher_name, unicode)
                    and isinstance(cipher_mode, unicode)
                    and isinstance(hash_name, unicode)
                    and isinstance(s_rand, bytes)
                    and isinstance(s_pubdata, tuple) and len(s_pubdata) == 2):
                raise VIOError('Illegal data types')
            d_ciphers = dict(self._ciphers)
            if not hmac_name in self._hmac_hashes:
                raise VIOError('Invalid HMAC hash method name')
            if not (cipher_name in d_ciphers
                    and cipher_mode in d_ciphers[cipher_name]):
                raise VIOError('Invalid cipher name or mode')
            if not hash_name in self._hashes:
                raise VIOError('Invalid hash name')
            s_pub_name, s_pub_keydata = s_pubdata
            if not isinstance(s_pub_name, unicode):
                raise VIOError('Invalid public key cipher name')
            if (max_keylen is None or
                isinstance(max_keylen, int) and max_keylen > 0):
                self._peer_max_keylen = max_keylen
            else:
                raise VIOError('Invalid peer max key length')
            if (hshake_lim is None or
                isinstance(hshake_lim, int) and hshake_lim > 0):
                self._peer_hshake_lim = hshake_lim
            else:
                raise VIOError('Invalid peer max key length')
            if len(s_rand) < 32:
                raise VIOError('Minimum 32 bytes random data required')

            # Store received parameters
            self._hmac_name = hmac_name
            self._cipher_name = cipher_name
            self._cipher_mode = cipher_mode
            self._hash_name = hash_name
            self._rand_s = s_rand

            # Reconstruct server public key
            try:
                if s_pub_name not in self._config.pub_ciphers:
                    raise VCryptoException('Not a supported PK cipher')
                s_pub_cipher = self._crypto.block_cipher(s_pub_name)
                s_pub_key = s_pub_cipher.key_factory.load(s_pub_keydata)
                if (self._max_keylen is not None
                    and 0 <= self._max_keylen < s_pub_key.keydata[0]):
                    raise VIOError('Peer public key exceeds max length')
                self._peer_pub_key = s_pub_key
            except:
                raise VIOError('Could not initialize server public key')
            else:
                if not self._peer_pub_key_received(s_pub_key):
                    raise VIOError('Server public key was rejected')

            # Parse identity/certificates data
            _id_data = self._parse_id_or_certs(s_pub_key, s_credentials)
            self._peer_identity, self._peer_certificates = _id_data

            # Perform authorization on received credentials
            if self._p_auth:
                if self._p_auth.require_key and not self._peer_pub_key:
                    raise VIOError('Authorization requires a peer key')
                if self._p_auth.require_cert and not self._peer_certificates:
                    raise VIOError('Authorization requires certificates')
                if self._p_auth.require_root and self._peer_certificates:
                    last_c = self._peer_certificates[-1]
                    _fmt = VX509Format.DER
                    for ca_cert in self._p_auth.root_certificates:
                        if last_c.export(fmt=_fmt) == ca_cert.export(fmt=_fmt):
                            # Last certificate is an accepted root cert
                            break
                        if last_c.certified_by(ca_cert):
                            # Last certificate is signed by an accepted root
                            break
                    else:
                        raise VIOError('Authorization requires root CA')
                _adef = self._p_auth.accept_credentials
                if not _adef(key=self._peer_pub_key,
                             identity=self._peer_identity,
                             certificates=self._peer_certificates):
                    raise VIOError('Server credentials not authorized')
            if not self._authorize_identity(self._peer_pub_key,
                                            self._peer_certificates,
                                            self._peer_identity):
                raise VIOError('Server public key is not authorized')

            # Prepare data for peer - client secure random data
            self._srand_c = self._rand(32)
            # - client public key
            if self._keypair:
                _pubkey = self._keypair.public
                pubkeydata = (_pubkey.cipher_name, _pubkey.keydata)
            else:
                pubkeydata = None
            # - client credentials
            if self._identity is not None:
                _der = self._identity.export(fmt=VX509Format.DER)
                credentials = (False, _der)
            elif self._certificates is not None:
                ders = []
                for cert in self._certificates:
                    ders.append(cert.export(fmt=VX509Format.DER))
                credentials = (True, tuple(ders))
            else:
                credentials = None

            # Prepare message to peer - plaintext content
            padding = b'' # Could add data here to randomize length
            msg = (pubkeydata, credentials, padding)
            # - encrypted content
            block_rand = self._rand(32)
            keyseed = b'vts client sendkey' + block_rand + self._srand_c
            enc_msg = self._blockcipher_enc_entity(msg, keyseed)
            # - plaintext header
            hash_cls = self._crypto.hash_cls(self._hash_name)
            _msg_data = VEntity._v_lazy(msg)._v_write(VIOContext())
            _msg_hash = hash_cls(_msg_data).digest()
            header = (self._srand_c, block_rand, _msg_hash)
            # - encrypted header
            enc_header = self._asymm_enc_entity(header, s_pub_key)
            # - prepare combined message for peer
            send_msg = (enc_header, enc_msg)
            writer = VEntity._v_lazy(send_msg)._v_writer(VIOContext())
            self._handshake_writer = writer
            if self._keypair:
                # Sending client key, prepare for executing step 6
                self._handshake_handler = self._get_server_secret
                self._handshake_reader = VEntity._v_reader(VIOContext())
            else:
                # Not sending key, initiate delayed finalization
                s_keyseed = self._rand_s + self._rand_c + self._srand_c
                c_keyseed = self._rand_c + self._rand_s + self._srand_c
                _cdata, _sdata = self._gen_keys(s_keyseed, c_keyseed)
                c_key, c_iv, c_mac = _cdata
                s_key, s_iv, s_mac = _sdata
                self._msg_encrypter = self._gen_msg_enc(c_key, c_iv, c_mac)
                self._msg_decrypter = self._gen_msg_dec(s_key, s_iv, s_mac)
                self._end_handshaking = True
            self.reactor.schedule(0.0, self._cp_do_produce)
        except VIOError as e:
            self.reactor.schedule(0.0, self._error_dismantle)
            raise e

    # VTS protocol step 6: client receives secret2
    def _get_server_secret(self, data):
        try:
            # Decrypt received data
            if not isinstance(data, bytes):
                raise VIOError('Invalid received data package')
            try:
                decoded = self._asymm_dec_entity(data, self._keypair)
            except VCryptoException as e:
                raise VIOError(e.args)

            # Validate input data has valid format
            srand_s = decoded
            if not isinstance(srand_s, bytes):
                raise VIOError('Illegal data types')
            if len(srand_s) < 32:
                raise VIOError('Minimum 32 bytes random data required')

            # Store received parameters
            self._srand_s = srand_s
            s_keyseed = (self._rand_s + self._rand_c +
                         self._srand_s + self._srand_c)
            c_keyseed = (self._rand_c + self._rand_s +
                         self._srand_c + self._srand_s)
            _cdata, _sdata = self._gen_keys(s_keyseed, c_keyseed)
            c_key, c_iv, c_mac = _cdata
            s_key, s_iv, s_mac = _sdata
            self._msg_encrypter = self._gen_msg_enc(c_key, c_iv, c_mac)
            self._msg_decrypter = self._gen_msg_dec(s_key, s_iv, s_mac)

            # We have completed handshake, switch handshaking state
            self._logger.debug('Client handshake completed')
            self._handshaking = False
            # Handshaking complete, set/update plaintext prod limit
            self._enable_plaintext()
            self.reactor.schedule(0.0, self._cp_do_produce)
        except VIOError as e:
            self.reactor.schedule(0.0, self._error_dismantle)
            raise e


class VSecureServer(VSecure):
    """Server-side channel bridge for a :term:`VTS` secure transport.

    Implements the server side of a :term:`VTS` channel. See :class:`VSecure`
    for general information and constructor arguments.

    """

    def _init_handshake(self):
        self._handshake_reader = VEntity._v_reader(VIOContext())
        self._handshake_handler = self._ack_hello

    # VTS protocol step 3: server sends crypto schemes and public key
    def _ack_hello(self, data):
        try:
            # Validate input data has valid format
            try:
                hhashes, ciphers, hashes, c_rand, max_keylen, hshake_lim = data
            except ValueError:
                raise VIOError('Could not unpack data')
            if not (isinstance(hhashes, tuple) and isinstance(ciphers, tuple)
                    and isinstance(hashes, tuple)
                    and isinstance(c_rand, bytes)):
                raise VIOError('Illegal data types')
            if (max_keylen is None or
                isinstance(max_keylen, int) and max_keylen > 0):
                self._peer_max_keylen = max_keylen
            else:
                raise VIOError('Invalid peer max key length')
            if (hshake_lim is None or
                isinstance(hshake_lim, int) and hshake_lim > 0):
                self._peer_hshake_lim = hshake_lim
            else:
                raise VIOError('Invalid peer max key length')
            for cipher in ciphers:
                if not (isinstance(cipher, tuple) and len(cipher) == 2):
                    raise VIOError('Illegal ciphers list')
                c_name, c_modes = cipher
                if not (isinstance(c_name, unicode) and
                        isinstance(c_modes, tuple)):
                    raise VIOError('Illegal ciphers list')
                for c_mode in c_modes:
                    if not isinstance(c_mode, unicode):
                        raise VIOError('Illegal ciphers list')
            for _hash in hhashes:
                if not isinstance(_hash, unicode):
                    raise VIOError('Illegal handshake hash list')
            for _hash in hashes:
                if not isinstance(_hash, unicode):
                    raise VIOError('Illegal hash list')
            if len(c_rand) < 32:
                raise VIOError('Minimum 32 bytes random data required')

            # Store received random data
            self._rand_c = c_rand

            # Determine handshake hash method, cipher method and hash method
            for _hash in self._hmac_hashes:
                if _hash in hhashes:
                    self._hmac_name = _hash
                    break
            else:
                raise VIOError('Could not negotiate HMAC hash method')
            d_ciphers = dict(ciphers)
            for cipher, modes in self._ciphers:
                if cipher in d_ciphers:
                    for mode in modes:
                        if mode in d_ciphers[cipher]:
                            break
                    else:
                        continue
                    self._cipher_name, self._cipher_mode = cipher, mode
                    break
            else:
                raise VIOError('Could not negotiate cipher+mode')
            for _hash in self._hashes:
                if _hash in hashes:
                    self._hash_name = _hash
                    break
            else:
                raise VIOError('Could not negotiate message encryption hash')

            # Generate server random data and prepare public key for export
            self._rand_s = self._rand(32)
            pubkey = self._keypair.public
            pubkeydata = (pubkey.cipher_name, pubkey.keydata)

            # Prepare a package of 'credentials' for sending to peer
            if self._identity is not None:
                _der = self._identity.export(fmt=VX509Format.DER)
                credentials = (False, _der)
            elif self._certificates is not None:
                ders = []
                for cert in self._certificates:
                    ders.append(cert.export(fmt=VX509Format.DER))
                credentials = (True, tuple(ders))
            else:
                credentials = None

            # Prepare return value for peer and prepare receiving a response
            msg = (self._hmac_name, self._cipher_name, self._cipher_mode,
                   self._hash_name, self._rand_s, pubkeydata, credentials,
                   self._config.max_keylen, self._config.hshake_lim)
            writer = VEntity._v_lazy(msg)._v_writer(VIOContext())
            self._handshake_writer = writer
            self._handshake_handler = self._get_pubkey
            self._handshake_reader = VEntity._v_reader(VIOContext())
            self.reactor.schedule(0.0, self._cp_do_produce)
        except VIOError as e:
            self.reactor.schedule(0.0, self._error_dismantle)
            raise e

    # VTS protocol step 5: server sends secret2
    def _get_pubkey(self, data):
        try:
            # Validate format of data package
            if not isinstance(data, tuple) or not len(data) == 2:
                raise VIOError('Invalid received data package')
            for e in data:
                if not isinstance(e, bytes):
                    raise VIOError('Invalid received data package')
            enc_header, enc_msg = data

            # Decode and parse header
            try:
                header = self._asymm_dec_entity(enc_header, self._keypair)
            except VCryptoException as e:
                raise VIOError(e.args)

            if not (isinstance(header, tuple) and len(header) == 3):
                raise VIOError('Invalid header')
            for e in header:
                if not isinstance(e, bytes):
                    raise VIOError('Invalid header')
            srand_c, block_rand, msg_hash = header
            if len(srand_c) < 32:
                raise VIOError('Minimum 32 bytes random data required')
            if len(block_rand) < 32:
                raise VIOError('Minimum 32 bytes random data required')

            # Decode and parse content
            keyseed = b'vts client sendkey' + block_rand + srand_c
            hash_cls = self._crypto.hash_cls(self._hash_name)
            try:
                msg = self._blockcipher_dec_entity(enc_msg, keyseed)
            except VCryptoException as e:
                raise VIOError(e.args)
            _msg_data = VEntity._v_lazy(msg)._v_write(VIOContext())
            if hash_cls(_msg_data).digest() != msg_hash:
                raise VIOError('Header and content hash value mismatch')

            if not (isinstance(msg, tuple) and len(msg) == 3):
                raise VIOError('Invalid content')
            c_keydata, c_credentials, padding = msg

            # Store received parameters
            self._srand_c = srand_c

            # Reconstruct client public key
            if c_keydata is not None:
                # Client sent keydata
                if not (isinstance(c_keydata, tuple) and len(c_keydata) == 2):
                    raise VIOError('Illegal data types')
                c_pub_name, c_pub_keydata = c_keydata
                if not isinstance(c_pub_name, unicode):
                    raise VIOError('Invalid public key cipher name')
                try:
                    if c_pub_name not in self._config.pub_ciphers:
                        raise VCryptoException('Not a supported PK cipher')
                    c_pub_cipher = self._crypto.block_cipher(c_pub_name)
                    c_pub_key = c_pub_cipher.key_factory.load(c_pub_keydata)
                    if (self._max_keylen is not None
                        and 0 <= self._max_keylen < c_pub_key.keydata[0]):
                        raise VIOError('Peer public key exceeds max length')
                    self._peer_pub_key = c_pub_key
                except:
                    raise VIOError('Could not initialize server public key')
                else:
                    if not self._peer_pub_key_received(c_pub_key):
                        raise VIOError('Server public key was rejected')
            else:
                # Client did not send a key
                self._peer_pub_key = c_pub_key = None

            # Parse identity/certificates data
            _id_data = self._parse_id_or_certs(c_pub_key, c_credentials)
            self._peer_identity, self._peer_certificates = _id_data
            if not c_pub_key and (self._peer_identity is not None
                                  or self._peer_certificates is not None):
                raise VIOError('Client send credentials without sending key')

            # Perform authorization of received credentials
            if self._p_auth:
                if self._p_auth.require_key and not self._peer_pub_key:
                    raise VIOError('Authorization requires a peer key')
                if self._p_auth.require_cert and not self._peer_certificates:
                    raise VIOError('Authorization requires certificates')
                if self._p_auth.require_root and self._peer_certificates:
                    last_c = self._peer_certificates[-1]
                    _fmt = VX509Format.DER
                    for ca_cert in self._p_auth.root_certificates:
                        if last_c.export(fmt=_fmt) == ca_cert.export(fmt=_fmt):
                            # Last certificate is an accepted root cert
                            break
                        if last_c.certified_by(ca_cert):
                            # Last certificate is signed by an accepted root
                            break
                    else:
                        raise VIOError('Authorization requires root CA')
                _adef = self._p_auth.accept_credentials
                if not _adef(key=self._peer_pub_key,
                             identity=self._peer_identity,
                             certificates=self._peer_certificates):
                    raise VIOError('Server credentials not authorized')
            if not self._authorize_identity(self._peer_pub_key,
                                            self._peer_certificates,
                                            self._peer_identity):
                raise VIOError('Client\'s public key is not authorized')

            if self._peer_pub_key:
                # Peer sent key, send srand_s and initiate delayed finalization
                self._srand_s = self._rand(32)
                msg = self._asymm_enc_entity(self._srand_s, c_pub_key)
                writer = VEntity._v_lazy(msg)._v_writer(VIOContext())
                self._handshake_writer = writer
                s_keyseed = (self._rand_s + self._rand_c +
                             self._srand_s + self._srand_c)
                c_keyseed = (self._rand_c + self._rand_s +
                             self._srand_c + self._srand_s)
                self._end_handshaking = True
            else:
                # No peer key, skip step 6 and initiate immediate finalization
                s_keyseed = self._rand_s + self._rand_c + self._srand_c
                c_keyseed = self._rand_c + self._rand_s + self._srand_c
                self._handshaking = False
            _cdata, _sdata = self._gen_keys(s_keyseed, c_keyseed)
            c_key, c_iv, c_mac = _cdata
            s_key, s_iv, s_mac = _sdata
            self._msg_encrypter = self._gen_msg_enc(s_key, s_iv, s_mac)
            self._msg_decrypter = self._gen_msg_dec(c_key, c_iv, c_mac)

            self.reactor.schedule(0.0, self._cp_do_produce)
        except VIOError as e:
            self.reactor.schedule(0.0, self._error_dismantle)
            raise e


class VSecureConfig(VConfig):
    """Configuration settings for a :class:`VSecureConfig`\ .

    :param hhashes:      allowed handshake hash methods (default if None)
    :type  hashes:       (hash_name,)
    :param ciphers:      allowed ciphers/modes (def. if None)
    :type  ciphers:      ((c_name, (mode_name,)),)
    :param creq:         if False require use of all ciphers/modes
    :type  creq:         bool
    :param hashes:       allowed msg validation hash methods (def. if None)
    :type  hashes:       (hash_name,)
    :param creq:         if False require use of all hash methods
    :type  creq:         bool
    :param pub_ciphers:  allowed public key ciphers (default if None)
    :type  pub_ciphers:  (c_name,)
    :param padder:       padding generator (def. if None)
    :type  padder:       :class:`versile.crypto.rand.VByteGenerator`
    :param rbuf_len:     max bytes to consume (unlimited if None)
    :type  rbuf_len:     int
    :param max_write:    max bytes to produce (unlimited if None)
    :type  max_write:    int
    :param hshake_lim:   max length of handshake message (unlimited if None)
    :type  hshake_lim:   int
    :param max_keylen:   max key length in bytes (unlimited None)
    :type  max_keylen:   int (or None)
    :param auth:         callback function for approving peer public key
    :type  auth:         callable
    :param crypto:       crypto provider (or None)
    :type  crypto:       :class:`versile.crypto.VCrypto`

    Default values are:

    +-------------+-------------------------------------------------+
    | Parameter   | Default Value                                   |
    +=============+=================================================+
    | hhashes     | ``('sha256',)``                                 |
    +-------------+-------------------------------------------------+
    | ciphers     | (``('aes256', ('cbc', 'ofb'))``\ ,              |
    |             | ``('blowfish', ('cbc', 'ofb'))``\ ,             |
    |             | ``('blowfish128', ('cbc', 'ofb'))``\ )          |
    +-------------+-------------------------------------------------+
    | hashes      | ``('sha1',)``                                   |
    +-------------+-------------------------------------------------+
    | pub_ciphers | ``('rsa',)``                                    |
    +-------------+-------------------------------------------------+
    | padder      | :class:`versile.crypto.rand.VConstantGenerator` |
    +-------------+-------------------------------------------------+

    If *ciphers* is None, the default list will be filtered to only
    include ciphers that are provided by *crypto* (or a default
    provider if *crypto* is None).

    If *creq* is True then require all ciphers defined must be
    available, and similarly if *hreq* is True require all hash
    methods defined must be available. If any of the combinations are
    not supported by the channel's crypto provider, an exception is
    raised during channel construction.

    *hshake_lim* specifies a limit for the length of a handshake
    message during protocol handshake. Setting this parameter provides
    protection against attacks based on malformed handshake packages.

    *max_keylen* specifies the maximum key length which is accepted
    for public key operations on keys received from peer, including
    both peer's key and key received in peer certificates. Setting
    this limit provides protection against attacks based on over-size
    keys which would otherwise cause the end-point to perform
    resource-intensive modular arithmetics which could otherwise cause
    the program to block or exhaust available resources.

    .. warning::

        If *hshake_lim* and *max_keylen* are not set then the
        transport is vulnerable to attacks from malformed handshake
        messages of unauthenticated peers.

    *auth* is a function which receives a peer public key and returns
    True if the key is approved. The function is called by the default
    implementation of :meth:`_peer_pub_key_received`\ .

    .. note::

        *auth* callback is useful for public key log-in/authentication
        to higher-level protocols.

    """

    def __init__(self, hhashes=None, ciphers=None, creq=False, hashes=None,
                 hreq=False, pub_ciphers=None, padder=None, rbuf_len=0x4000,
                 max_write=0x4000, hshake_lim=16384, max_keylen=(4096//8),
                 auth=None, crypto=None):
        # If changing defaults here, make sure to also update class docstring
        if hhashes is None:
            hhashes = ('sha256',)

        if ciphers is None:
            # Setting default list of ciphers; only include ciphers and
            # modes which are available from the crypto provider
            _crypto = VCrypto.lazy(crypto)
            _ciphers = []
            for _cname in ('aes256', 'blowfish', 'blowfish128'):
                if _cname in _crypto.block_ciphers:
                    _cipher = _crypto.block_cipher(_cname)
                    _modes = []
                    for _mname in ('cbc', 'ofb'):
                        if _mname in _cipher.modes:
                            _modes.append(_mname)
                    if _modes:
                        _ciphers.append((_cname, tuple(_modes)))
            ciphers = tuple(_ciphers)

        if hashes is None:
            hashes = ('sha1',)
        if pub_ciphers is None:
            pub_ciphers = ('rsa',)
        if padder is None:
            padder = VConstantGenerator(b'\x00')

        s_init = super(VSecureConfig, self).__init__
        s_init(hhashes=hhashes, ciphers=ciphers, creq=creq, hashes=hashes,
               hreq=hreq, pub_ciphers=pub_ciphers, padder=padder,
               rbuf_len=rbuf_len, max_write=max_write, hshake_lim=hshake_lim,
               max_keylen=max_keylen, auth=auth)


@implements(IVByteConsumer)
class _VPlaintextConsumer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def consume(self, data, clim=None):
        return self.__proxy._pc_consume(data, clim)

    @peer
    def end_consume(self, clean):
        return self.__proxy._pc_end_consume(clean)

    def abort(self):
        return self.__proxy._pc_abort()

    def attach(self, producer):
        return self.__proxy._pc_attach(producer)

    def detach(self):
        return self.__proxy._pc_detach()

    @property
    def control(self):
        return self.__proxy._pc_control

    @property
    def producer(self):
        return self.__proxy._pc_producer

    @property
    def flows(self):
        return self.__proxy._pc_flows

    @property
    def twoway(self):
        return self.__proxy._pc_twoway

    @property
    def reverse(self):
        return self.__proxy._pc_reverse


@implements(IVByteProducer)
class _VPlaintextProducer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def can_produce(self, limit):
        return self.__proxy._pp_can_produce(limit)

    def abort(self):
        return self.__proxy._pp_abort()

    def attach(self, consumer):
        return self.__proxy._pp_attach(consumer)

    def detach(self):
        return self.__proxy._pp_detach()

    @property
    def control(self):
        return self.__proxy._pp_control

    @property
    def consumer(self):
        return self.__proxy._pp_consumer

    @property
    def flows(self):
        return self.__proxy._pp_flows

    @property
    def twoway(self):
        return self.__proxy._pp_twoway

    @property
    def reverse(self):
        return self.__proxy._pp_reverse


@implements(IVByteConsumer)
class _VCiphertextConsumer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def consume(self, data, clim=None):
        return self.__proxy._cc_consume(data, clim)

    @peer
    def end_consume(self, clean):
        return self.__proxy._cc_end_consume(clean)

    def abort(self):
        return self.__proxy._cc_abort()

    def attach(self, producer):
        return self.__proxy._cc_attach(producer)

    def detach(self):
        return self.__proxy._cc_detach()

    @property
    def control(self):
        return self.__proxy._cc_control

    @property
    def producer(self):
        return self.__proxy._cc_producer

    @property
    def flows(self):
        return self.__proxy._cc_flows

    @property
    def twoway(self):
        return self.__proxy._cc_twoway

    @property
    def reverse(self):
        return self.__proxy._cc_reverse


@implements(IVByteProducer)
class _VCiphertextProducer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def can_produce(self, limit):
        return self.__proxy._cp_can_produce(limit)

    def abort(self):
        return self.__proxy._cp_abort()

    def attach(self, consumer):
        return self.__proxy._cp_attach(consumer)

    def detach(self):
        return self.__proxy._cp_detach()

    @property
    def control(self):
        return self.__proxy._cp_control

    @property
    def consumer(self):
        return self.__proxy._cp_consumer

    @property
    def flows(self):
        return self.__proxy._cp_flows

    @property
    def twoway(self):
        return self.__proxy._cp_twoway

    @property
    def reverse(self):
        return self.__proxy._cp_reverse
