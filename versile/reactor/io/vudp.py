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

"""Versile UDP Transport, a reliable UDP transport."""
from __future__ import print_function, unicode_literals

from collections import deque
import errno
import socket
import threading
import time
import weakref

from versile.internal import _vexport, _v_silent
from versile.internal import _pyver
from versile.common.iface import implements, abstract, final, peer
from versile.common.log import VLogger
from versile.common.peer import VSocketPeer
from versile.common.util import VByteBuffer, VResult
from versile.common.util import posint_to_netbytes, netbytes_to_posint
from versile.crypto.local import VLocalCrypto
from versile.crypto.rand import VUrandom
from versile.crypto.x509 import VX509Crypto, VX509Format
from versile.crypto.x509.cert import VX509Certificate
from versile.orb.entity import VException
from versile.orb.external import VExternal, publish
from versile.orb.validate import vchk, vtyp, vset
from versile.reactor import IVReactorObject
from versile.reactor.io import VByteIOPair
from versile.reactor.io import IVByteProducer, IVByteConsumer
from versile.reactor.io import IVSelectableInput, VFIOCompleted, VFIOLost
from versile.reactor.io import VIOControl, VIOMissingControl
from versile.reactor.io.link import VLinkAgent

__all__ = ['VUDPTransport', 'VUDPRelayedVOPConnecter',
           'VUDPRelayedVOPApprover', 'VUDPHostFilter']
__all__ = _vexport(__all__)


# Package size limit
_MTU = 576                        # IPv4 requirement
_IP4_H = 60                       # Max IPv4 header
_UDP_H = 8                        # UDP header
MAX_SEGMENT = _MTU-_IP4_H-_UDP_H  # Max segment size
_MAX_DGRAM = 65507

# Max data to include in a package
_FLG = 1
_SEQ = 8
_ACK = 8
_WIN = 8
_MAC = 20
MAX_DATA = MAX_SEGMENT-(_FLG+_SEQ+_ACK+_WIN+_MAC)

# Protocol handshake message
_PROTO_HELLO = b'VUDPTransport-0.8'

# Package header flags
FLAG_CLOSE = 0x80              # Notifies end-of-stream
FLAG_ACK_CLOSE = 0x40          # Acknowledges end-of-stream
FLAG_FAIL = 0x20               # Notifies of general failure
FLAG_MASK = 0xe0

# Flow control parameters
SSTHRESH = 65535/MAX_DATA      # Initial threshold for SSHTHRESH
MIN_RTO = 0.1                  # Minimum RTO
MAX_RTO = 60                   # Maximum RTO
DEFAULT_RTO = 3.0              # Default RTO - reduced from earlier default
#DEFAULT_RTO = 3.0             # Default retransmission timeout
RTO_INVALIDATE_BACKOFF = 5     # Num back-offs to invalidate SRTT/RTTVAR
HSHAKE_WIN = 128               # Window size during protocol handshake
DUP_ACK_RESEND = 3             # Number dup_ack to trigger forced re-send

# Timer handling
_MAX_TIMERS = 20                # Maximum active timers
_TIMER_REDUCE_FACTOR = 0.8      # Minimum reduction for adding timer


# Used internally for simulating (uniform) UDP package loss, must be when
# not testing. Holds avg lost packages per 100 datagrams (as an integer)
_SIM_LOSS_RATE = 0


@implements(IVReactorObject, IVSelectableInput)
class VUDPTransport():
    """Implements Versile UDP Transport for reliable streaming.

    :param reactor:   owning reactor
    :type  reactor:   :class:`versile.reactor.VReactor`
    :param sock:      bound UDP socket for the connection
    :type  sock:      :class:`socket.socket`
    :param peer:      peer network address
    :type  peer:      (string, int)
    :param secret:    local HMAC secret
    :type  secret:    bytes
    :param p_secret:  peer's HMAC secret
    :type  p_secret:  bytes
    :param buf_len:   length of receive/send buffers
    :type  buf_len:   int

    Performs :term:`VUT` reliable byte data streaming over UDP,
    intented to be used when reliable streaming is needed but TCP
    communication is not possible, such as peer-to-peer communication
    between hosts on separate internal networks. The UDP based scheme
    implements flow control and congestion avoidance mechanisms
    similar to TCP.

    *sock* is a bound UDP socket which is reachable by the peer on a
    network address known by the peer.

    *peer* is a network address to an UDP port for the peer side of
    the connection, which can be reached from this host (e.g. if the
    peer is behind a NAT, this must be the external facing host and
    port for the network route to the peer). This typically requires
    using a relay service to negotiate the UDP connection, which
    helps the two peers discover each others' external facing UDP
    port addresses using NAT hole-punching techniques.

    :term:`VUT` communication is secured by HMAC authentication.
    Transferred data is unencrypted, however each package is
    authenticated by a message digest which is protected by two
    secrets, one for each peer. The secrets should normally be
    negotiated via a relay service, and (if the relay can be trusted
    and connection to the relay is secure) is known only by the
    communicating parties and the relay.

    .. note::

        The UDP based transport is typically used to provide a byte
        transport for a :term:`VOP` based link. In order to secure a
        connection, the peers should use VOP with a secure transport
        mode.

        Establishing a separate secure connection layer on top of the
        UDP transport also enables additional authentication to be
        performed between the peers, in addition to securing the
        communication channel. This minimizes the role of a relay, and
        means a relay does not need to be fully trusted. This enables
        peer-based communication models which rely on central services
        only for relaying connections or discovering peers.

    """

    def __init__(self, reactor, sock, peer, secret, p_secret, buf_len=65536):

        self.__reactor = reactor
        sock.setblocking(False)
        self.__sock = sock
        self._peer = peer

        self.__secret = secret
        self.__peer_secret = p_secret
        self.__send_secret = secret + p_secret
        self.__recv_secret = p_secret + secret

        self._peer_validated = False
        self._peer_acked_hello = False
        self._validated = False
        self._failed = False              # True if connection has failed

        self._sock_enabled = True
        self._sock_closed = False         # If True the socket has been closed

        self._in_closed = False           # If True transport input is closed
        self._out_closed = False          # If True transport output is closed
        self._out_sent_close = False      # If True sent output 'close' to peer

        self._sbuf = VByteBuffer()
        self._sbuf_len = buf_len          # Max buffered send data w/in-flight
        self._sbuf_pos = 0                # Stream pos of send buffer start
        self._send_lim = HSHAKE_WIN       # End of peer's advertised window
        self._send_acked = 0              # Last acknowledged send position
        self._in_fl = dict()              # seq_num->[data, t_st, ret_t, #ret]
        self._in_fl_pos = deque()         # sorted pos index of in-flight data
        self._in_fl_num = 0               # amount in-flight data
        self._last_send_t = None          # timestamp for last data send

        self._num_dup_ack = 0             # Number consecutive duplicate ack

        self._rbuf = VByteBuffer()        # Receive data buffer
        self._rbuf_len = buf_len          # Max buffered read data
        self._rbuf_spos = 0               # Stream pos of recv buffer start
        self._recv_queue = dict()         # stream_pos -> data
        self._recv_win_end = 0            # End of advertised window
        _step = self._rbuf_len/5
        self._recv_win_step = _step       # Step size of inc adv.win
        self._recv_acked = 0              # Last acked position

        self._recv_closing = False        # True if input closing
        self._recv_close_pos = None       # Input end stream position

        self._force_ack = False           # If True force sending a package
        self._force_resend = False        # If True re-send first in-flight
        self._fast_recovery = False       # If True stream is in fast recovery

        self._srtt = None                 # Sample round-trip time
        self._rttvar = None               # Round-trip time variance
        self._rto = DEFAULT_RTO           # Retransmission timeout
        self._rto_num_backoff = 0         # Number of RTO back-off
        self._cwnd = 2.0                  # Cong.window as # in-flight segments
        self._ssthresh = SSTHRESH        # Slow-start threshold as # segments

        self._timers = set()              # Currently active timers

        self._ci = None
        self._ci_eod = False
        self._ci_eod_clean = None
        self._ci_producer = None
        self._ci_consumed = 0
        self._ci_lim_sent = 0
        self._ci_aborted = False

        self._pi = None
        self._pi_closed = False
        self._pi_consumer = None
        self._pi_produced = 0
        self._pi_prod_lim = 0
        self._pi_buffer = VByteBuffer()
        self._pi_aborted = False

        _hash_cls = VLocalCrypto().sha1
        self._hmac_fun = _hash_cls.hmac
        self._hmac_len = _hash_cls.digest_size()

        self.__tmp_buf = VByteBuffer()

        # Set up a convenience logger
        self.__logger = VLogger(prefix='VUDP')
        self.__logger.add_watcher(self.reactor.log)

        # Initialize send buffer with peer hello and start read/write
        self._sbuf.append(_PROTO_HELLO)

        # Write protocol hello and start reading
        self._send_packages()
        self.start_reading()

    @property
    def byte_consume(self):
        """Holds a :class:`IVByteConsumer` interface to the socket."""
        if not self._ci:
            ci = _VUDPTransportConsumer(self)
            self._ci = weakref.ref(ci)
            return ci
        else:
            ci = self._ci()
            if ci:
                return ci
            else:
                ci = _VUDPTransportConsumer(self)
                self._ci = weakref.ref(ci)
                return ci

    @property
    def byte_produce(self):
        """Holds a :class:`IVByteProducer` interface to the socket."""
        if not self._pi:
            pi = _VUDPTransportProducer(self)
            self._pi = weakref.ref(pi)
            return pi
        else:
            pi = self._pi()
            if pi:
                return pi
            else:
                pi = _VUDPTransportProducer(self)
                self._pi = weakref.ref(pi)
                return pi

    @property
    def byte_io(self):
        """Byte interface (\ :class:`versile.reactor.io.VByteIOPair`\ )."""
        return VByteIOPair(self.byte_consume, self.byte_produce)

    def do_read(self):
        """See :meth:`versile.reactor.io.IVByteHandleInput.do_read`\ ."""

        # Read limited datagrams to enable reactor to regain control
        for _iter in xrange(_MAX_DGRAM/MAX_DATA):
            if self._sock_closed:
                self.stop_reading()
                break

            try:
                dgram, address = self.__sock.recvfrom(65536)
            except socket.error as e:
                if e.errno != errno.EWOULDBLOCK:
                    self._p_abort()
                break

            if (address != self._peer):
                self._handle_invalid_peer()
                continue

            # Validate datagram HMAC
            if len(dgram) <= self._hmac_len:
                self._handle_invalid_hmac()
                continue
            payload = dgram[:(-self._hmac_len)]
            _hmac = dgram[(-self._hmac_len):]
            if _hmac != self._dgram_hmac(payload, self.__recv_secret):
                self._handle_invalid_hmac()
                continue

            # Validate datagram length does not exceed allowed max
            if len(dgram) > MAX_SEGMENT:
                self._fail('Maximum package size exceeded')
                break

            # Decode datagram payload
            self.__tmp_buf.clear()
            self.__tmp_buf.append(payload)
            # - flags
            if len(self.__tmp_buf) < 1:
                self.__fail('Datagram format error')
                break
            flags = self.__tmp_buf.pop(1)[0]
            if _pyver == 2:
                flags = ord(flags)
            # - sequence number
            _tmp = self.__tmp_buf.peek()
            num, _nread = netbytes_to_posint(_tmp)
            if num is None:
                self.__fail('Datagram format error')
                break
            self.__tmp_buf.pop(_nread)
            seq_num = num
            # - acknowledge number
            _tmp = self.__tmp_buf.peek()
            num, _nread = netbytes_to_posint(_tmp)
            if num is None:
                self.__fail('Datagram format error')
                break
            self.__tmp_buf.pop(_nread)
            ack_num = num
            # - advertised window
            _tmp = self.__tmp_buf.peek()
            num, _nread = netbytes_to_posint(_tmp)
            if num is None:
                self.__fail('Datagram format error')
                break
            self.__tmp_buf.pop(_nread)
            adv_win = num
            # - data
            data = self.__tmp_buf.pop()

            # Check for failure
            if flags & FLAG_FAIL:
                self.__fail('peer sent failure message')
                return

            # Process ack data
            if not self._peer_acked_hello and ack_num > 0:
                self._peer_acked_hello = True
                self.log.debug('peer acknowledged protocol hello')
                self.__validate()
            if ack_num > self._send_acked:
                for _pos in self._in_fl_pos:
                    _f_data, _f_stamp, _f_rt, _f_retries = self._in_fl[_pos]
                    if ack_num == _pos + len(_f_data):
                        break
                else:
                    # Acknowledge not aligned to any in-flight package, abort
                    self.__fail('Acknowledge of unknown position')
                    break
                while self._in_fl_pos and self._in_fl_pos[0] <= _pos:
                    _tmp_pos = self._in_fl_pos.popleft()
                    _tmp = self._in_fl.pop(_tmp_pos, None)
                    self._in_fl_num -= len(_tmp[0])

                # Update 'ack' point; exit fast recovery mode if any
                self._send_acked = ack_num
                self._num_dup_ack = 0

                # Update congestion window and end fast recovery if any
                if self._fast_recovery:
                    # End fast recovery
                    self._cwnd = self._ssthresh
                    self._fast_recovery = False
                elif self._cwnd <= self._ssthresh:
                    # Slow start, ref. RFC 2581
                    self._cwnd += 1.0
                else:
                    # Congestion avoidance, ref. RFC 2581
                    self._cwnd += 1.0/self._cwnd

                # If RTT can be measured, update parameters as per RFC 2988
                if _f_retries == 0:
                    _rtt = time.time() - _f_stamp
                    if self._srtt is None:
                        self._srtt = _rtt
                        self._rttvar = _rtt/2
                    else:
                        self._rttvar *= 0.75
                        self._rttvar += 0.25*abs(self._srtt-_rtt)
                        self._srtt *= 0.875
                        self._srtt += 0.125*_rtt
                    old_rto, self._rto = self._rto, self._srtt + 4*self._rttvar
                    self._rto_num_backoff = 0
                    # Enforce min/max on RTO as per RFC 793
                    self._rto = max(self._rto, MIN_RTO)
                    self._rto = min(self._rto, MAX_RTO)

                    # Lazy-set new timer for new RTO if RTO was reduced
                    if self._rto < old_rto and self._in_fl:
                        _tstamp = self._in_fl[self._in_fl_pos[0]][1]
                        delay = max(_tstamp+self._rto-time.time(), 0)
                        self._set_rto_timer(delay)
            else:
                # Detect duplicate ACK as per http://www.ietf.org/(...)
                # (...)mail-archive/web/tcpm/current/msg01200.html
                same_win = (ack_num+adv_win <= self._send_lim)
                if same_win and not data:
                    if self._in_fl and ack_num == self._send_acked:
                        self._num_dup_ack += 1

                        if self._num_dup_ack == DUP_ACK_RESEND:
                            # Initiate fast retransmit/recovery, ref. RFC 2581
                            self._ssthresh = max(len(self._in_fl)/2, 2)
                            self._cwnd = self._ssthresh + 3
                            self._force_resend = True
                            self._fast_recovery = True
                        elif self._num_dup_ack > DUP_ACK_RESEND:
                            self._cwnd += 1

                    elif not self._fast_recovery:
                        # Custom adaptation; do not reset dup_ack
                        # if already in fast recovery mode
                        self._num_dup_ack = 0

            # Process received data
            rbuf_data_added = False
            if data:
                if self._in_closed or self._recv_closing:
                    # Validate peer does not send out-of-bounds package
                    if seq_num + len(data) > self._recv_close_pos:
                        self.__fail('Got data past stream close position')
                        break

                if seq_num == self._recv_win_end:
                    # Allow peer to try send 1 octet past receive window
                    if len(data) > 1:
                        # Peer advertised window violation
                        self.__fail('Advertised window exceeded')
                        break
                    else:
                        # Ensure an 'ack' is sent to package
                        self._force_ack = True
                else:
                    # Handle regular data transfer

                    if seq_num+len(data) > self._recv_win_end:
                        # Peer advertised window violation
                        self.__fail('Advertised window exceeded')
                        break

                    _rbuf_next = self._rbuf_spos + len(self._rbuf)
                    if seq_num == _rbuf_next:
                        self._rbuf.append(data)
                        _rbuf_next += len(data)
                        rbuf_data_added = True
                        # Process receive queue
                        for _pos in sorted(self._recv_queue.keys()):
                            if _pos > _rbuf_next:
                                break
                            elif _pos == _rbuf_next:
                                _data = self._recv_queue.pop(_pos)
                                self._rbuf.append(_data)
                                _rbuf_next += len(_data)
                            else:
                                # Protocol violation, segment overlaps
                                self.__fail('Overlapping segments')
                                return
                    elif seq_num > _rbuf_next:
                        _spos, _epos = seq_num, seq_num+len(data)
                        # Check no overlaps with current queue
                        for _pos in sorted(self._recv_queue.keys()):
                            if _pos >= _epos:
                                break
                            _data = self._recv_queue[_pos]
                            if _pos == _spos and data == _data:
                                # Re-send of existing segment
                                break
                            elif _pos+len(_data) > _spos:
                                # Protocol violation, overlapping segments
                                self.__fail('Overlapping segments')
                                return
                        # Add segment to queue
                        self._recv_queue[seq_num] = data
                        # Force an immediate ack for out-of-order data,
                        # similar to RFC 2581
                        self._force_ack = True
                    else:
                        # Old data package, force an immediate ack for
                        # out-of-order data, similar to RFC 2581
                        self._force_ack = True

                if self._force_ack:
                    # Immediately resolve force-ack, in order to sent a
                    # package which can be identified as a 'duplicate ack'
                    self._send_force_ack()
                    self._force_ack = False

            if not self._peer_validated and data:
                # The first received data must be a protocol handshake
                hello = self._rbuf.pop()
                if hello != _PROTO_HELLO:
                    self.__fail('Invalid peer protocol handshake')
                    return
                self._peer_validated = True
                self._rbuf_spos += len(hello)
                self.log.debug('got valid peer protocol hello')

                # If needed force re-sending hello message to peer
                if not self._peer_acked_hello:
                    if self._in_fl.get(0, None) is not None:
                        self._force_resend = True

                self.__validate()

            # Handle 'close' flag
            if flags & FLAG_CLOSE:
                close_pos = seq_num + len(data)
                if self._recv_closing:
                    if self._recv_close_pos != close_pos:
                        self.__fail('inconsistent close flag use by peer')
                        return
                else:
                    # Check no conflict with buffered data
                    if self._rbuf_spos + len(self._rbuf) > close_pos:
                        self.__fail('close flag conflicts with other data')
                        return
                    for _pos, _data in self._recv_queue.items():
                        if _pos + len(_data) > close_pos:
                            self.__fail('close flag conflicts with other data')
                            return

                    # Set input 'closing' status
                    self._recv_closing = True
                    self._recv_close_pos = close_pos

                    # If no pending data, close input and force an 'ack'
                    if (not self._recv_queue
                        and self._rbuf_spos + len(self._rbuf) == close_pos):
                        self.close_input(VFIOCompleted())
                        self._force_ack = True

            # Handle 'ack_close' flag
            if flags & FLAG_ACK_CLOSE and not self._out_closed:
                if not self._ci_eod or self._sbuf:
                    # Premature ack_close means peer aborted the connection
                    self._c_abort()
                elif not self._in_fl:
                    self.close_output(VFIOCompleted())

            # Update send limit
            self._send_lim = max(self._send_lim, ack_num+adv_win)

            # If data was added, perform a production iteration
            if rbuf_data_added:
                # Data was added, perform a produce iteration
                self.__do_produce()

            # Perform a package send iteration
            self._send_packages()

        # Evaluate consume limit
        if self._validated and self._ci_producer:
            _old_lim = self._ci_lim_sent
            _cur_lim = (self._ci_consumed + self._sbuf_len
                        - len(self._sbuf) - self._in_fl_num)
            if _cur_lim > _old_lim:
                self._ci_lim_sent = _cur_lim
                self._ci_producer.can_produce(self._ci_lim_sent)

    def _send_packages(self):
        """Perform regular sending of packages to peer."""
        while True:
            # Ensure socket is open
            if self._sock_closed or not self._sock_enabled or not self.sock:
                break

            # Determine if we can send data (if not max_data will be zero)
            max_data = 0
            check_close = False
            if self._cwnd >= len(self._in_fl)+1:
                if self._sbuf:
                    if self._sbuf_pos < self._send_lim:
                        max_data = self._send_lim - self._sbuf_pos
                    elif self._sbuf_pos == self._send_lim:
                        # Allow single octet past adv window if RTO expired
                        if (self._last_send_t is None or
                            time.time()-self._last_send_t >= self._rto):
                            max_data = 1
                elif self._ci_eod and not self._out_sent_close:
                    check_close = True

            # Determine new ack number and advertised window size
            ack_num = self._rbuf_spos + len(self._rbuf)
            if self._validated:
                adv_end = self._rbuf_spos + self._rbuf_len
                adv_end -= adv_end % self._recv_win_step
            else:
                adv_end = HSHAKE_WIN

            # If nothing to send to peer, just return
            if self._force_resend and not self._in_fl:
                self._force_resend = False
            if not (max_data > 0 or check_close or ack_num > self._recv_acked
                    or adv_end > self._recv_win_end or self._force_ack
                    or self._force_resend):
                break

            # Compose a package for sending to peer
            if self._force_resend:
                _force_pos = self._in_fl_pos[0]
                _seq_num = _force_pos
                _b_seq_num = posint_to_netbytes(_seq_num)
                _b_ack_num = posint_to_netbytes(ack_num)
                _b_adv_win = posint_to_netbytes(adv_end-ack_num)
                data = self._in_fl[_force_pos][0]
            else:
                _seq_num = self._sbuf_pos
                _b_seq_num = posint_to_netbytes(_seq_num)
                _b_ack_num = posint_to_netbytes(ack_num)
                _b_adv_win = posint_to_netbytes(adv_end-ack_num)
                data = self._sbuf.peek(min(max_data, MAX_DATA))

            if data and self._last_send_t is not None:
                # Initialize "slow start" if it is more than one RTO
                # since the last data transmission, ref. RFC 2581
                if time.time()-self._last_send_t > self._rto:
                    self._cwnd = 2

            flag = self.__gen_flag(_seq_num + len(data))
            if _pyver == 2:
                fbyte = chr(flag)
            else:
                fbyte = bytes((flag,))

            pkg = b''.join((fbyte, _b_seq_num, _b_ack_num, _b_adv_win, data))
            pkg += self._dgram_hmac(pkg, self.__send_secret)

            try:
                if (_SIM_LOSS_RATE == 0
                    or VUrandom().number(0, 99) >= _SIM_LOSS_RATE):
                    self.sock.sendto(pkg, self._peer)
            except socket.error as e:
                if e.errno != errno.EWOULDBLOCK:
                    self._c_abort()
                break
            else:
                # Meta-data was sent, no need to force_ack
                self._force_ack = False

                if data:
                    if self._force_resend:
                        # Increase re-send counter and disable force resend
                        self._in_fl[_force_pos][1] = time.time()
                        self._in_fl[_force_pos][3] += 1
                        self._force_resend = False
                    else:
                        self._sbuf.pop(len(data))
                        _in_fl_pkg = [data, time.time(), self._rto, 0]
                        self._in_fl[self._sbuf_pos] = _in_fl_pkg
                        self._in_fl_pos.append(self._sbuf_pos)
                        self._in_fl_num += len(data)
                        self._sbuf_pos += len(data)

                    # Update time of last data transmission and set RTO timer
                    self._last_send_t = time.time()
                    self._set_rto_timer(self._rto)

                self._recv_acked = ack_num
                self._recv_win_end = adv_end
                if flag & FLAG_CLOSE:
                    self._out_sent_close = True

    def _resend_package(self, pos):
        """Re-sends package at position 'pos' in self._in_fl."""

        # Ensure socket is open
        if self._sock_closed or not self._sock_enabled or not self.sock:
            return

        _in_fl_pkg = self._in_fl.get(pos, None)
        if _in_fl_pkg is None:
            # Should never happen
            return

        # Determine new ack number and advertised window size
        ack_num = self._rbuf_spos + len(self._rbuf)
        if self._validated:
            adv_end = self._rbuf_spos + self._rbuf_len
            adv_end -= adv_end % self._recv_win_step
        else:
            adv_end = HSHAKE_WIN

        # Compose a package for sending to peer
        _seq_num = pos
        _b_seq_num = posint_to_netbytes(_seq_num)
        _b_ack_num = posint_to_netbytes(ack_num)
        _b_adv_win = posint_to_netbytes(adv_end-ack_num)
        data = _in_fl_pkg[0]

        flag = self.__gen_flag(_seq_num+len(data))
        if _pyver == 2:
            fbyte = chr(flag)
        else:
            fbyte = bytes((flag,))

        pkg = b''.join((fbyte, _b_seq_num, _b_ack_num, _b_adv_win, data))
        pkg += self._dgram_hmac(pkg, self.__send_secret)

        try:
            if (_SIM_LOSS_RATE == 0
                or VUrandom().number(0, 99) >= _SIM_LOSS_RATE):
                self.sock.sendto(pkg, self._peer)
        except socket.error as e:
            if e.errno != errno.EWOULDBLOCK:
                self._c_abort()
            return
        else:
            _in_fl_pkg[1] = time.time()
            # Custom logic, "backing off package's own resend timer"
            _in_fl_pkg[2] = min(2*_in_fl_pkg[2], self._rto)
            _in_fl_pkg[3] += 1
            self._set_rto_timer(_in_fl_pkg[2])

            self._recv_acked = ack_num
            self._recv_win_end = adv_end
            if flag & FLAG_CLOSE:
                self._out_sent_close = True

    def _send_force_ack(self):
        """Sends an ack package with no new information."""

        # Ensure socket is open
        if self._sock_closed or not self._sock_enabled or not self.sock:
            return

        _l_seq_num = self._sbuf_pos
        _l_ack_num= self._rbuf_spos + len(self._rbuf)
        _l_adv_win = self._recv_win_end - _l_ack_num

        _l_b_seq_num = posint_to_netbytes(_l_seq_num)
        _l_b_ack_num = posint_to_netbytes(_l_ack_num)
        _l_b_adv_win = posint_to_netbytes(_l_adv_win)
        _l_data = b''

        _l_flag = self.__gen_flag(_l_seq_num)
        if _pyver == 2:
            _l_fbyte = chr(_l_flag)
        else:
            _l_fbyte = bytes((_l_flag,))
        _l_pkg = b''.join((_l_fbyte, _l_b_seq_num, _l_b_ack_num,
                           _l_b_adv_win, _l_data))
        _l_pkg += self._dgram_hmac(_l_pkg, self.__send_secret)

        try:
            if (_SIM_LOSS_RATE == 0
                or VUrandom().number(0, 99) >= _SIM_LOSS_RATE):
                self.sock.sendto(_l_pkg, self._peer)
        except socket.error as e:
            if e.errno != errno.EWOULDBLOCK:
                self._c_abort()

    def __gen_flag(self, end_pos):
        """Returns flag for sending, when end_pos is end of data sent"""
        flag = 0x00
        # Handle setting 'close' flag
        if self._ci_eod:
            if end_pos == self._sbuf_pos + len(self._sbuf):
                flag |= FLAG_CLOSE
        if self._in_closed:
            flag |= FLAG_ACK_CLOSE
        return flag

    def _set_rto_timer(self, delay):
        """Sets a timer for the given timeout.

        Timer that is set depends on the current pool of timers. A
        timer will only be set if if the current pool is not maxed and
        sufficient reduction in time until next set timer is achieved.

        This handling is a trade-off between setting exact timers when
        RTO estimates are reduced, vs. the cost of re-normalizing
        reactor scheduled tasks when cancelled or delayed.

        """
        # Ensure no negative delays
        delay = max(delay, 0)

        if len(self._timers) >= _MAX_TIMERS:
            return

        cur_time = time.time()
        if not self._timers:
            _do_set = True
        else:
            _set_delay = max(min(self._timers)-cur_time, 0)
            # Must test with '<' here in order to avoid scheduling
            # multiple zero-delay tasks
            _do_set = (delay < _TIMER_REDUCE_FACTOR*_set_delay)

        if _do_set:
            timeout = cur_time+delay
            self.reactor.schedule(delay, self._handle_rto_timer, timeout)
            self._timers.add(timeout)

    def _handle_rto_timer(self, timeout):
        cur_time = time.time()

        # Flush all expired timers
        _expired = tuple(_tout for _tout in self._timers if _tout <= cur_time)
        for _exp in _expired:
            self._timers.discard(_exp)

        if self._in_fl:
            # Resend all expired in-flight packages
            for pos, in_fl_pkg in self._in_fl.items():
                _f_t_stamp, _f_delay = in_fl_pkg[1], in_fl_pkg[2]
                resend_t = _f_t_stamp + min(_f_delay, self._rto)
                if resend_t <= cur_time:
                    self._resend_package(pos)
                    # Back off the RTO timer, ref. RFC 2988
                    self._rto *= 2
                    self._rto = min(self._rto, MAX_RTO)
                    self._rto_num_backoff += 1
                    # Reset congestion window and threshold as per RFC 2581
                    self._ssthresh = max(len(self._in_fl)/2, 2)
                    self._cwnd = 1

            # Reset the RTO timer
            _future = deque()
            for in_fl_pkg in self._in_fl.values():
                _f_t_stamp, _f_delay = in_fl_pkg[1], in_fl_pkg[2]
                _future.append(_f_t_stamp + min(_f_delay, self._rto))
            self._set_rto_timer(min(_future)-cur_time)

        else:

            can_send = False
            should_force = False

            # If send buffer saturated with no window, send 1 octet if RTO
            if not self._out_closed:
                if self._sbuf and self._sbuf_pos == self._send_lim:
                    can_send = True

            # If waiting for ack_close, force ack if RTO timeout
            if self._out_sent_close and not self._out_closed:
                should_force = True
                can_send = True

            # If waiting to send, process if RTO or if not set a timeout
            if can_send:
                if (self._last_send_t is None or
                    cur_time-self._last_send_t >= self._rto):
                    if should_force:
                        self._force_ack = True
                    self._send_packages()
                    # Fake update to last_send_t to ensure new RTO offset
                    self._last_send_t = cur_time
                    # Back off the RTO timer
                    self._rto *= 2
                    self._rto = min(self._rto, MAX_RTO)
                    self._rto_num_backoff += 1
                else:
                    self._set_rto_timer(self._last_send_t+self._rto-cur_time)

        # Invalidate the SRTT/RTTVAR data if too many RTO back-off,
        # ref. optional approach described in RFC 2988
        if self._rto_num_backoff >= RTO_INVALIDATE_BACKOFF:
            self._srtt = None
            self._rttvar = None

    def close_input(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandleInput.close_input`\ ."""
        if self._in_closed:
            return True
        elif self._out_closed:
            return self.close_io(reason)

        self._in_closed = True
        self.log.debug('closed input only')
        self._in_closed_reason = reason
        self._input_was_closed(reason)
        return True

    def close_output(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandleOutput.close_output`\ ."""

        if self._out_closed:
            return True
        elif self._in_closed:
            return self.close_io(reason)

        self._out_closed = True
        self.log.debug('closed output only')
        self._out_closed_reason = reason
        self._output_was_closed(reason)
        return True

    def close_io(self, reason):
        """See :meth:`versile.reactor.io.IVByteHandle.close_io`\ ."""
        if not (self._in_closed and self._out_closed):
            in_was_closed = self._in_closed
            out_was_closed = self._out_closed
            self._in_closed = self._out_closed = True

            # Send an 'ack' before close, to ensure status flags are sent
            if not self._failed:
                self._force_ack = True
                self._send_packages()

            try:
                self.sock.close()
            except socket.error as e:
                _v_silent(e)
            self._sock_closed = True
            self.log.debug('closed')

            if not in_was_closed:
                self._in_closed_reason = reason
                self._input_was_closed(reason)
            if not out_was_closed:
                self._out_closed_reason = reason
                self._output_was_closed(reason)

            self.stop_reading()

        return True

    @final
    def start_reading(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteInput.start_reading`\ ."""
        if not self._sock_closed and self._sock_enabled and self.sock:
            self.reactor.add_reader(self, internal=internal)
            self._started_reading()

    @final
    def stop_reading(self, internal=False):
        """See :meth:`versile.reactor.io.IVByteInput.start_reading`\ ."""
        if self.sock:
            self.reactor.remove_reader(self, internal=internal)

    @property
    def reactor(self):
        """See :attr:`versile.reactor.IVReactorObject.reactor`\ ."""
        return self.__reactor

    @property
    def sock(self):
        """The transport's associated native socket."""
        return self.__sock

    @property
    def log(self):
        """Logger for the socket (:class:`versile.common.log.VLogger`\ )."""
        return self.__logger

    def fileno(self):
        """See :meth:`versile.reactor.io.IVSelectable.fileno`\ ."""
        if not self.__sock:
            raise VIOError('No socket')
        try:
            fd = self.__sock.fileno()
        except socket.error:
            return -1
        else:
            return fd

    def _started_reading(self):
        """Called internally before :meth:`start_reading` returns.

        Default does nothing, derived classes can override.

        """
        pass

    def _handle_invalid_peer(self):
        """Called internally if an datagram was received from invalid peer IP.

        Default does nothing, derived classes can override.

        """
        # Should consider adding mechanisms to decide whether to abort
        # if too many invalid packages, e.g. protect against DoS
        pass

    def _handle_invalid_hmac(self):
        """Called internally if a datagram failed to authenticate.

        Default does nothing, derived classes can override.

        """
        # Should consider adding mechanisms to decide whether to abort
        # if too many invalid packages, e.g. protect against DoS
        pass

    def _dgram_hmac(self, data, secret):
        """Computes VUDPTransport HMAC for the payload.

        :param data:    datagram payload
        :type  data:    bytes
        :param secret:  HMAC secret
        :type  secret:  bytes
        :returns:       message hmac
        :rtype:         bytes

        """
        return self._hmac_fun(secret, data)

    @peer
    def _c_consume(self, buf, clim):
        if self._out_closed:
            raise VIOClosed('UDP transport output is closed')
        elif self._ci_eod:
            raise VIOClosed('Consumer already reached end-of-data')
        elif not self._ci_producer:
            raise VIOError('No connected producer')
        elif self._ci_consumed >= self._ci_lim_sent:
            raise VIOError('Consume limit exceeded')
        elif not buf:
            raise VIOError('No data to consume')

        max_cons = self._sbuf_len - len(self._sbuf)
        max_cons = min(max_cons, self._ci_lim_sent - self._ci_consumed)
        if clim is not None and clim > 0:
            max_cons = min(max_cons, clim)

        indata = buf.pop(max_cons)
        self._sbuf.append(indata)
        self._ci_consumed += len(indata)

        # Trigger package sending in case more data can be sent
        self._send_packages()

        # Evaluate new consume limit
        _lim = (self._ci_consumed + self._sbuf_len
                    - len(self._sbuf) - self._in_fl_num)
        self._ci_lim_sent = max(self._ci_lim_sent, _lim)

        return self._ci_lim_sent

    def _c_end_consume(self, clean):
        if self._out_closed:
            raise VIOClosed('transport output already closed')
        elif self._ci_eod:
            return
        self._ci_eod = True
        self._ci_eod_clean = clean
        self._send_packages()

    def _c_abort(self):
        if not self._ci_aborted:
            self._ci_aborted = True
            self._ci_eod = True
            self._ci_consumed = self._ci_lim_sent = 0
            self._sbuf.clear()
            if not self._out_closed:
                self.close_output(VFIOCompleted())
            if self._ci_producer:
                self._ci_producer.abort()
                self._c_detach()

    def _c_attach(self, producer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._c_attach, producer, rthread=True)
            return

        if self._ci_producer is producer:
            return
        elif self._ci_producer:
            raise VIOError('Producer already attached')

        self._ci_producer = producer
        self._ci_consumed = self._ci_lim_sent = 0
        producer.attach(self.byte_consume)

        # Send a produce limit if connection has been validated
        if self._validated:
            self._ci_lim_sent = self._sbuf_len - len(self._sbuf)
            producer.can_produce(self._ci_lim_sent)

        # Notify attached chain
        try:
            producer.control.notify_consumer_attached(self.byte_consume)
        except VIOMissingControl:
            pass

    def _c_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._c_detach, rthread=True)
            return

        if self._ci_producer:
            prod, self._ci_producer = self._ci_producer, None
            prod.detach()
            self._ci_consumed =  self._ci_lim_sent = 0

    def _output_was_closed(self, reason):
        # No more output will be written, abort consumer
        self._c_abort()

    @property
    def _c_control(self):
        return self._c_get_control()

    def _c_get_control(self):
        return VIOControl()

    @property
    def _c_producer(self):
        return self._ci_producer

    @property
    def _c_flows(self):
        return tuple()

    @property
    def _c_twoway(self):
        return True

    @property
    def _c_reverse(self):
        return self.byte_produce()

    @peer
    def _p_can_produce(self, limit):
        if not self._pi_consumer:
            raise VIOError('No connected consumer')

        limit_changed = False
        if limit is None or limit < 0:
            if (not self._pi_prod_lim is None
                and not self._pi_prod_lim < 0):
                if self._pi_produced >= self._pi_prod_lim:
                    limit_changed = True
                self._pi_prod_lim = limit
        else:
            if (self._pi_prod_lim is not None
                and 0 <= self._pi_prod_lim < limit):
                if self._pi_produced >= self._pi_prod_lim:
                    limit_changed = True
                self._pi_prod_lim = limit

        if limit_changed:
            # Limits changed, trigger a (possible) produce operation
            self.reactor.schedule(0.0, self.__do_produce)

    def _p_abort(self):
        if not self._pi_aborted:
            self._pi_aborted = True
            self._pi_produced = self._pi_prod_lim = 0
            if not self._in_closed:
                self.close_input(VFIOCompleted())
            if self._pi_consumer:
                self._pi_consumer.abort()
                self._p_detach()

    def _p_attach(self, consumer, rthread=False):
        # Ensure 'attach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._p_attach, consumer, rthread=True)
            return

        if self._pi_consumer is consumer:
            return
        elif self._pi_consumer:
            raise VIOError('Consumer already attached')

        self._pi_produced = self._pi_prod_lim = 0
        self._pi_consumer = consumer
        consumer.attach(self.byte_produce)

        # Notify attached chain
        try:
            consumer.control.notify_producer_attached(self.byte_produce)
        except VIOMissingControl:
            pass

        # If already connected, schedule notification of 'connected' status
        if self._validated:
            control = consumer.control
            def notify():
                peer = VSocketPeer(socket.AF_INET, socket.SOCK_DGRAM,
                                   socket.SOL_UDP, self._peer)
                try:
                    control.connected(peer)
                except VIOMissingControl:
                    pass
            self.reactor.schedule(0.0, notify)

    def _p_detach(self, rthread=False):
        # Ensure 'detach' is performed in reactor thread
        if not rthread:
            self.reactor.execute(self._p_detach, rthread=True)
            return

        if self._pi_consumer:
            cons, self._pi_consumer = self._pi_consumer, None
            cons.detach()
            self._pi_produced = self._pi_prod_lim = 0

    def _input_was_closed(self, reason):
        if self._pi_consumer:
            # Notify consumer about end-of-data
            clean = isinstance(reason, VFIOCompleted)
            self._pi_consumer.end_consume(clean)
        else:
            self._p_abort()

    @property
    def _p_control(self):
        return self._p_get_control()

    def _p_get_control(self):
        class _Control(VIOControl):
            def __init__(self, transport):
                self.transport = transport
            def req_producer_state(self, consumer):
                # Send notification of socket connect status
                def notify():
                    if self.transport._validated:
                        _peer = self.transport._peer
                        peer = VSocketPeer(socket.AF_INET, socket.SOCK_DGRAM,
                                           socket.SOL_UDP, _peer)
                        try:
                            consumer.control.connected(peer)
                        except VIOMissingControl:
                            pass
                self.transport.reactor.schedule(0.0, notify)
        return _Control(self)

    @property
    def _p_consumer(self):
        return self._pi_consumer

    @property
    def _p_flows(self):
        return tuple()

    @property
    def _p_twoway(self):
        return True

    @property
    def _p_reverse(self):
        return self.byte_consume()

    def __validate(self):
        """Handles validation when """
        if not self._validated:
            if self._peer_validated and self._peer_acked_hello:
                self._validated = True
                self.log.debug('connection validated')

                # Re-initialize congestion window and slow start threshold,
                # so performance is not penalized by handshake timeouts
                self._cwnd = max(self._cwnd, 2)
                self._ssthresh = max(self._ssthresh, SSTHRESH)

                # If connected, notify connected consumer
                if self._p_consumer:
                    control = self._p_consumer.control
                    def notify():
                        peer = VSocketPeer(socket.AF_INET, socket.SOCK_DGRAM,
                                           socket.SOL_UDP, self._peer)
                        try:
                            self._p_consumer.control.connected(peer)
                        except VIOMissingControl:
                            pass
                    self.reactor.schedule(0.0, notify)

                # Schedule a send iteration, to advertise new window size
                self.reactor.schedule(0.0, self._send_packages)

                # If a producer is connected, send produce limit
                if self._ci_producer:
                    self._ci_lim_sent = self._sbuf_len - len(self._sbuf)
                    self._ci_producer.can_produce(self._ci_lim_sent)

    def __do_produce(self):
        if not self._pi_consumer:
            return

        if 0 <= self._pi_prod_lim <= self._pi_produced:
            return
        elif not self._validated:
            return

        if self._rbuf:
            old_len = len(self._rbuf)
            self._pi_prod_lim = self._pi_consumer.consume(self._rbuf)
            _prod = old_len - len(self._rbuf)
            self._pi_produced += _prod
            self._rbuf_spos += _prod

            # Perform a send iteration in case peer limits can be updated
            self._send_packages()

            # If more data can be produced, schedule another iteration
            if self._rbuf and not 0 <= self._pi_prod_lim <= self._pi_produced:
                self.reactor.schedule(0.0, self.__do_produce)

    def __fail(self, msg=None):
        """Fails a connection"""
        if not self._failed:
            if msg:
                self.log.debug('connection failed')
            else:
                self.log.debug('connection failed, %s' % msg)
            self._c_abort()
            self._p_abort()
            self.close_io(VFIOLost())
            self._failed = True


class VUDPRelayedVOPConnecter(VExternal):
    """A :term:`VUT` Relay client connecter for negotiating a :term:`VOP` link.

    :param is_client:  if True set up as a :term:`VOP` client
    :type  is_client:  bool
    :param udp_filter: filter for allowed UDP addresses (or None)
    :type  udp_filter: :class:`VUDPHostFilter`

    Remaining parameters are similar to the
    :class:`versile.reactor.io.link.VLinkAgent` constructor and the
    method :meth:`versile.reactor.io.link.VLinkAgent.create_vop_client`\ .

    Implements the :term:`VUT` Relay standard for negotiating a
    :term:`VOP` link over a Versile UDP Transport.

    When provided, *udp_filter* is applied to IP address provided by
    relay for UDP connections.

    .. warning::

        Without *udp_filter*, a malicious relay could cause a relayed
        connection to send UDP handshake packages to any reachable IP
        address.

    The consequences of being directed to a false UDP address is
    limited because of how the handshake protocol is designed, as (a)
    the peer's locally generated token is part of all such handshake
    messages, and (b) the back-off timer for
    re-transmissions. However, in order to protect against such
    scenarios, a filter can be provided. Such filters could e.g. deny
    sending traffic to private network addresses or localhost
    interfaces, or require that a relay UDP destination must be the
    same address as the host address which is providing relay
    :term:`VOP` services.

    """

    def __init__(self, is_client, gateway=None, reactor=None, processor=None,
                 init_callback=None, context=None, auth=None, link_conf=None,
                 key=None, identity=None, certificates=None, p_auth=None,
                 vts=True, tls=False, insecure=False, crypto=None,
                 internal=False, buf_size=None, vec_conf=None, vts_conf=None,
                 udp_filter=None):

        super(VUDPRelayedVOPConnecter, self).__init__()

        self._is_client = is_client
        self._udp_filter = udp_filter

        # VLinkAgent related parameters
        self._gateway = gateway
        self._reactor = reactor
        self._processor = processor
        self._init_callback = init_callback
        self._context = context
        self._auth = auth
        self._link_conf = link_conf

        # VOP transport related parameters
        self._key = key
        self._identity = identity
        self._certificates = certificates
        self._p_auth = p_auth
        self._vts = vts
        self._tls = tls
        self._insecure = insecure
        self._crypto = crypto
        self._internal = internal
        self._buf_size = buf_size
        self._vec_conf = vec_conf
        self._vts_conf = vts_conf

        self._sock = None
        self._external_udp = None      # External (host, port) UDP address
        self._link = None

        self._connect_host = None      # Host for initial UDP connect
        self._connect_port = None      # Port for initial UDP connect
        self._connect_l_token = None   # Local token for initial UDP connect
        self._connect_r_token = None   # Remote token for initial UDP connect

        self._udp_resend_t = None      # Current UDP resend time
        self._udp_max_resend = None    # Maximum UDP resend time
        self._timeout = None           # Timeout for handshake
        self._start_time = None        # Start time for UDP handshake
        self._timer = None             # Timer for timeouts

        self._num_confirm_calls = 0    # Number of calls to confirm_udp
        self._num_link_calls = 0       # Number of calls to link_to_peer

        # Asynchronous call result for link gateway
        class Result(VResult):
            def __init__(self, handler):
                super(Result, self).__init__()
                self._w_handler = weakref.ref(handler);
            def _cancel(self):
                _handler = self._w_handler()
                if _handler:
                    _handler._cancel()
        self._peer_gw = Result(self)

    @publish(show=True, ctx=False)
    def confirm_udp(self, host, port):
        if self._num_confirm_calls != 0:
            raise VException('May only call confirm_udp once')
        self._num_confirm_calls += 1
        vchk(host, vtyp(unicode), vset)
        vchk(port, vtyp(int, long), 1024<=port<=65535)
        # This will stop UDP handshake re-transmission
        self._external_udp = (host, port)

    @publish(show=True, ctx=False)
    def link_to_peer(self, host, port, l_sec, r_sec):
        if self._num_link_calls != 0:
            raise VException('May only call link_to_peer once')
        self._num_link_calls += 1
        vchk(host, vtyp(unicode), vset)
        vchk(port, vtyp(int, long), 1024<=port<=65535)
        vchk(l_sec, vtyp(bytes), len(l_sec)<=32)
        vchk(r_sec, vtyp(bytes), len(r_sec)<=32)
        link = VLinkAgent(gateway=self._gateway, reactor=self._reactor,
                          processor=self._processor,
                          init_callback=self._init_callback,
                          context=self._context, auth=self._auth,
                          conf=self._link_conf)

        # Perform filtering on peer UDP address; if denied reject connection
        if self._udp_filter and not self._udp_filter.allow_peer(host, port):
            if self._timer:
                self._timer.cancel()
            self._peer_gw.push_exception(VIOError('Peer denied by UDP filter'))
            return

        # Validate legal call sequence and client HMAC token
        _l_token = self._connect_l_token
        _exc = None
        if not (_l_token and self._connect_r_token):
            _exc = VIOError('Invalid call sequence')
        elif len(l_sec) > 32 or len(r_sec) > 32:
            _exc = VIOError('HMAC tokens must be maximum 32 bytes')
        if _exc:
            if self._timer:
                self._timer.cancel()
            self._peer_gw.push_exception(_exc)
            return


        if self._is_client:
            _vop_fun = link.create_vop_client
        else:
            _vop_fun = link.create_vop_server
        link_io = _vop_fun(key=self._key, identity=self._identity,
                           certificates=self._certificates,
                           p_auth=self._p_auth, vts=self._vts, tls=self._tls,
                           insecure=self._insecure, crypto=self._crypto,
                           internal=self._internal, buf_size=self._buf_size,
                           vec_conf=self._vec_conf, vts_conf=self._vts_conf)

        peer = (host, port)
        transport = VUDPTransport(link.reactor, self._sock, peer, l_sec, r_sec)
        transport.byte_io.attach(link_io)

        # Set up callbacks for returning link gateway
        def _res_handler(res):
            self._peer_gw.push_result(res)
            if self._timer:
                self._timer.cancel()
        def _exc_handler(exc):
            self._peer_gw.push_exception(exc)
            if self._timer:
                self._timer.cancel()
        link.async_gw().add_callpair(_res_handler, _exc_handler)
        self._link = link

    def connect_udp(self, host, port, l_token, r_token, min_resend=0.1,
                    max_resend=5.0, timeout=30):
        """Initiates a UDP handshake with relay.

        :param host:       UDP handshake hostname
        :type  host:       unicode
        :param port:       UDP handshake port
        :type  port:       int
        :param l_token:    local UDP handshake token
        :type  token:      bytes
        :param r_token:    relay UDP handshake token
        :type  token:      bytes
        :param min_resend: minimum re-transmission time (secs)
        :type  min_resend: float
        :param max_resend: maximum re-transmission time (secs)
        :type  max_resend: float
        :param timeout:    handshake timeout in seconds
        :type  timeout:    float
        :raises:           :exc:`versile.reactor.io.VIOError`

        If an UDP filter is registered on the connecter object, the
        filter is applied to host/port before connecting, and an
        exception is raised if the connection is rejected by the filter.

        """

        if self._udp_filter and not self._udp_filter.allow_relay(host, port):
            raise VIOError('UDP host/port rejected by connecter UDP filter')

        self._connect_host = host
        self._connect_port = port
        self._connect_l_token = l_token
        self._connect_r_token = r_token
        self._udp_resend_t = min_resend
        self._udp_max_resend = max_resend
        if timeout is not None:
            timeout = time.time() + timeout
        self._timeout = timeout

        self._start_time = time.time()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._send_udp_pkg()

        self._timer = threading.Timer(self._udp_resend_t, self._tick)
        self._timer.start()

    @property
    def peer_gw(self):
        """Peer gateway reference (:class:`versile.common.util.VResult`\ )"""
        return self._peer_gw

    def _tick(self):
        """Handler for re-transmit and timeout handler."""
        if self._peer_gw.has_result():
            return
        cur_time = time.time()
        if self._timeout is not None and cur_time >= self._timeout:
            self._cancel()
            return

        # If needed schedule new timer
        _tick_t = None
        if not self._external_udp:
            self._send_udp_pkg()
            self._udp_resend_t *= 2
            self._udp_resend_t = min(self._udp_resend_t, self._udp_max_resend)
            _tick_t = self._udp_resend_t
        if self._timeout is not None:
            if _tick_t is None:
                _tick_t = self._timeout-cur_time
            else:
                _tick_t = min(_tick_t, self._timeout-cur_time)
        if _tick_t is not None:
            self._timer = threading.Timer(_tick_t, self._tick)
            self._timer.start()

    def _send_udp_pkg(self):
        _addr = (self._connect_host, self._connect_port)
        token = self._connect_l_token+self._connect_r_token
        self._sock.sendto(token, _addr)

    def _cancel(self):
        """Cancels ongoing connect operation."""
        if self._timer:
            self._timer.cancel()
        if self._link:
            self._link.shutdown(True)
        if self._sock:
            self._sock.close()


@abstract
class VUDPRelayedVOPApprover(VExternal):
    """Base class for service provider for VUDP relayed service.

    :param udp_filter: filter for allowed UDP addresses (or None)
    :type  udp_filter: :class:`VUDPHostFilter`

    Implements the base mechanism for a service dispatched by a VUDP
    Relay. Abstract class, derived classes must implement
    :meth:`_approve`\ .

    See :class:`VUDPRelayedVOPConnecter` for information about UDP
    filters.

    """

    def __init__(self, udp_filter=None):
        super(VUDPRelayedVOPApprover, self).__init__()
        self._udp_filter = udp_filter
        self._rand = VUrandom()

    @publish(show=True, ctx=False)
    def approve(self, path, host, port, r_token, client_ip,
                client_key, client_certs):
        """Remote method called by link to initiate UDP based service.

        :param path:         path to requested resource
        :type  path:         (unicode,)
        :param host:         relay host address for UDP negotiation
        :type  host:         unicode
        :param port:         relay port number for UDP negotiation
        :type  port:         int
        :param r_token:      relay token for UDP authentication
        :type  r_token:      bytes
        :param client_ip:    client's IP address (or None)
        :type  client_ip:    unicode
        :param client_key:   client key, or NOne
        :type  client_key:   unicode
        :param client_certs: client certificate chain, or None
        :type  client_certs: (unicode,)
        :returns:            (connecter, l_token), or None
        :rtype:              (:class:`VUDPRelayedVOPConnecter`\ , bytes)

        Returns None if connection is rejected, otherwise a connecter
        and local token for initiating a connection. If approved then
        the connecter is allowed to start UDP handshake with the
        relay, even before this method has returned.

        """
        vchk(path, vtyp(tuple), vset)
        for item in path:
            vchk(item, vtyp(unicode), vset)
        vchk(host, vtyp(unicode), vset)
        vchk(port, vtyp(int, long), 1024<=port<=65535)
        vchk(r_token, vtyp(bytes), len(r_token)<=32)
        if client_ip is not None:
            vchk(client_ip, vtyp(unicode))
        if client_key is not None:
            vchk(client_key, vtyp(unicode))
        if client_certs is not None:
            vchk(client_certs, vtyp(tuple), len(client_certs)>0)
            for _cert in client_certs:
                vchk(_cert, vtyp(unicode), vset)

        # Parse client key and client certificates
        try:
            if client_key:
                client_key = VX509Crypto.import_public_key(client_key)
            if client_certs:
                _fun = VX509Certificate.import_cert
                _fmt = VX509Format.PEM_BLOCK
                client_certs = tuple(_fun(data, _fmt) for data in client_certs)
        except:
            return None

        # Perform filtering on relay's UDP host/port
        if self._udp_filter and not self._udp_filter.allow_relay(host, port):
            return None

        connecter = self.handle_approve(path, host, port, client_ip,
                                        client_key, client_certs)
        if connecter:
            l_token = self._rand(32)
            connecter.connect_udp(host, port, l_token, r_token)
            return (connecter, l_token)
        else:
            return None

    @abstract
    def handle_approve(self, path, host, port, client_ip,
                       client_key, client_certs):
        """Called internally by a relay to approve a link connection.

        :param client_key:   client key, or NOne
        :type  client_key:   :class:`versile.crypto.VAsymmetricKey`
        :param client_certs: client certificate chain, or None
        :returns:            connecter object, or None
        :rtype:              :class:`VUDPRelayedVOPConnecter`

        Remaining arguments are similar to :meth:`approve`\ .

        *client_certs* is a tuple with elements of type
        :class:`versile.crypto.x509.cert.VX509Certificate`

        Returns a connecter if approved, or None if not approved. The
        method :meth:`_connecter` can be used as a convenience method
        for generating a connecter object.

        If an UDP filter is registered on the object, it is performed
        on host/port before this method is called, so the method can
        assume if it is called then host/port was allowed.

        """
        raise NotImplementedError()

    def connecter(self, gateway, is_client=False, reactor=None,
                   processor=None, init_callback=None, context=None,
                   auth=None, link_conf=None, key=None, identity=None,
                   certificates=None, p_auth=None, vts=True, tls=False,
                   insecure=False, crypto=None, internal=False, buf_size=None,
                   vec_conf=None, vts_conf=None, udp_filter=None):
        """Convenience method for creating a connecter.

        Arguments similar to :class:`VUDPRelayedVOPConnecter`
        constructor. Intended primarily as a convenience method to be
        used from :meth:`_approve`\ .

        If *udp_filter* is None and a filter is set on the approver
        object, that filter is used.

        """
        if udp_filter is None:
            udp_filter = self._udp_filter
        _Cls = VUDPRelayedVOPConnecter
        return _Cls(is_client=is_client, gateway=gateway, reactor=reactor,
                    processor=processor, init_callback=init_callback,
                    context=context, auth=auth, link_conf=link_conf, key=key,
                    identity=identity, certificates=certificates,
                    p_auth=p_auth, vts=vts, tls=tls, insecure=insecure,
                    crypto=crypto, internal=internal, buf_size=buf_size,
                    vec_conf=vec_conf, vts_conf=vts_conf)


class VUDPHostFilter(object):
    """Filter for UDP addresses of relayed connection.

    The filter provides an allow/deny response for the host and port
    used during UDP handshake with a relay, and for the host and port
    used when initiating a peer-to-peer connection.

    The default implementation allows all connections, derived classes
    can override.

    """

    def allow_relay(self, host, port):
        """Requests allowing a UDP handshake to relay provided address.

        :param host: IP address
        :type  host: unicode
        :param port: UDP port number
        :type  port: unicode
        :returns:    True if allowed, False if denied
        :rtype:      bool

        """
        return True

    def allow_peer(self, host, port):
        """Requests allowing a :term:`VUT` handshake with peer UDP address.

        :param host: IP address
        :type  host: unicode
        :param port: UDP port number
        :type  port: unicode
        :returns:    True if allowed, False if denied
        :rtype:      bool

        """
        return True


@implements(IVByteConsumer)
class _VUDPTransportConsumer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def consume(self, data, clim=None):
        return self.__proxy._c_consume(data, clim)

    @peer
    def end_consume(self, clean):
        return self.__proxy._c_end_consume(clean)

    def abort(self):
        return self.__proxy._c_abort()

    def attach(self, producer):
        return self.__proxy._c_attach(producer)

    def detach(self):
        return self.__proxy._c_detach()

    @property
    def control(self):
        return self.__proxy._c_control

    @property
    def producer(self):
        return self.__proxy._c_producer

    @property
    def flows(self):
        return self.__proxy._c_flows

    @property
    def twoway(self):
        return self.__proxy._c_twoway

    @property
    def reverse(self):
        return self.__proxy._c_reverse


@implements(IVByteProducer)
class _VUDPTransportProducer(object):
    def __init__(self, parent):
        self.__proxy = parent

    @peer
    def can_produce(self, limit):
        return self.__proxy._p_can_produce(limit)

    def abort(self):
        return self.__proxy._p_abort()

    def attach(self, consumer):
        return self.__proxy._p_attach(consumer)

    def detach(self):
        return self.__proxy._p_detach()

    @property
    def control(self):
        return self.__proxy._p_control

    @property
    def consumer(self):
        return self.__proxy._p_consumer

    @property
    def flows(self):
        return self.__proxy._p_flows

    @property
    def twoway(self):
        return self.__proxy._p_twoway

    @property
    def reverse(self):
        return self.__proxy._p_reverse
