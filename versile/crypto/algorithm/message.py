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

"""Implements :term:`VCA` message integrity validation."""
from __future__ import print_function, unicode_literals

from versile.internal import _b2s, _s2b, _vexport, _b_ord, _b_chr, _pyver
from versile.common.util import VByteBuffer, posint_to_bytes
from versile.crypto import VCryptoException

__all__ = ['VMessageDecrypter', 'VMessageEncrypter']
__all__ = _vexport(__all__)


class VMessageEncrypter(object):
    """Encrypter for encrypted messages with data integrity check.

    Implements the :term:`VP` VCrypto specification for plaintext
    message-encoding including data integrity validation. Plaintext is
    wrapped in a message which include 2-byte plaintext length,
    plaintext, plaintext hash and padding.

    :param encrypter:    transform for encryption
    :type  encrypter:    :class:`versile.crypto.VBlockTransform`
    :param hash_cls:     hash class for message integrity hash
    :type  hash_cls:     :class:`versile.crypto.VHash`
    :param pad_provider: provider of padding bytes for messages
    :type  pad_provider: callable
    :param mac_secret:   secret data for package authentication
    :type  mac_secret:   bytes

    .. automethod:: __call__

    """
    def __init__(self, encrypter, hash_cls, pad_provider, mac_secret):
        self._encrypter = encrypter
        self._hash_cls = hash_cls
        self._hash_len = hash_cls.digest_size()
        self._pad_provider = pad_provider
        self._mac_secret = mac_secret
        self._max_plaintext_len = 0x10000 # HARDCODED 2-byte message length
        self._plaintext_blocksize = encrypter.blocksize
        self._msg_num = 0

    def __call__(self, plaintext):
        """See :meth:`message`\ ."""
        return self.message(plaintext)

    def message(self, plaintext):
        """Returns an encrypted message for a provided plaintext.

        :param plaintext: the plaintext to encode and encrypt
        :type  plaintext: bytes
        :returns:         encrypted message-protected plaintext
        :rtype:           bytes
        :raises:          :exc:`versile.crypto.VCryptoException`

        Raises an exception if provided plaintext is longer than
        :attr:`max_plaintext_len`\ , meaning the plaintext is larger
        than what is allowed inside a single message. Empty plaintext
        is also not allowed.

        """
        plaintext_len = len(plaintext)
        if plaintext_len > self._max_plaintext_len:
            raise VCryptoException('Plaintext too long')
        elif not plaintext:
            raise VCryptoException('Empty plaintext not allowed')

        # Generate padding
        msg_len = 2 + plaintext_len + self._hash_len
        _bsize = self._plaintext_blocksize
        pad_len = msg_len % _bsize
        if pad_len:
            pad_len = _bsize - pad_len

        # Create message content
        encode_len = plaintext_len - 1
        if _pyver == 2:
            plain_len = (_s2b(_b_chr((encode_len & 0xff00) >> 8))
                         + _s2b(_b_chr(encode_len & 0xff)))
        else:
            plain_len = bytes((((encode_len & 0xff00) >> 8),
                               (encode_len & 0xff)))
        padding = self._pad_provider(pad_len)
        _mac_msg = b''.join((posint_to_bytes(self._msg_num), plain_len,
                             plaintext, padding))
        msg_hash = self._hash_cls.hmac(self._mac_secret, _mac_msg)
        msg = b''.join((plain_len, plaintext, padding, msg_hash))

        # Create encrypted message
        enc_msg = self._encrypter(msg)
        self._msg_num += 1
        return enc_msg

    @property
    def max_plaintext_len(self):
        """Maximum plaintext length allowed in a single message."""
        return self._max_plaintext_len


class VMessageDecrypter(object):
    """Decrypter for encrypted messages with data integrity check.

    Decodes encrypted plaintext messages in the format encrypted by
    :class:`VMessageEncrypter`\ .

    :param decrypter:   transform for decryption
    :type  decrypter:   :class:`versile.crypto.VBlockTransform`
    :param hash_cls:    hash class for message integrity hash
    :type  hash_cls:    :class:`versile.crypto.VHash`
    :param mac_secret:  secret data for package authentication
    :type  mac_secret:  bytes

    """

    def __init__(self, decrypter, hash_cls, mac_secret):
        self._decrypter = decrypter
        self._hash_cls = hash_cls
        self._mac_secret = mac_secret
        self._max_plaintext_len = 0x10000 # HARDCODED 2-byte message length
        self._cipher_blocksize = decrypter.blocksize
        self._hash_len = hash_cls.digest_size()
        self._read_buf = VByteBuffer()
        self._in_buf = VByteBuffer()
        self._msg_buf = VByteBuffer()
        self._have_len = False
        self._plaintext_blocksize = None
        self._plaintext_len = None
        self._invalid = False
        self._result = None
        self._msg_num = 0

    def reset(self):
        """Resets the decrypter to read a new message.

        :raises: :class:`VCryptoException`

        Raises an exception if ongoing decryption is not completed.

        """
        if self._result is None:
            raise VCryptoException('Ongoing decryption not completed')
        self._read_buf.remove()
        self._in_buf.remove()
        self._msg_buf.remove()
        self._have_len = False
        self._plaintext_len = None
        self._invalid = False
        self._result = None


    def read(self, data):
        """Reads encrypted message data.

        :param data: input data to decrypt and decode
        :type  data: bytes, :class:`versile.common.util.VByteBuffer`
        :returns:    number of bytes read
        :rtype:      int

        Reads only as much data as is required to complete processing
        a complete single message. If data is of type
        :class:`versile.common.util.VByteBuffer` then the data that
        was read will be popped off the buffer.

        .. note::

            When decryption of one message has completed,
            :meth:`reset` must be called before a new message can be
            read.

        """
        if isinstance(data, bytes):
            read_buf = self._read_buf
            read_buf.remove()
            read_buf.append(data)
        elif isinstance(data, VByteBuffer):
            read_buf = data
        else:
            raise TypeError('Input must be bytes or VByteBuffer')

        num_read = 0
        _pbsize = self._plaintext_blocksize
        _cbsize = self._cipher_blocksize
        while read_buf and self._result is None and not self._invalid:
            # First decode single block to get blocksize
            if not self._have_len:
                max_read = _cbsize - len(self._in_buf)
                enc_data = read_buf.pop(max_read)
                self._in_buf.append(enc_data)
                num_read += len(enc_data)
                if len(self._in_buf) == _cbsize:
                    enc_data = self._in_buf.pop()
                    block = self._decrypter(enc_data)
                    if _pbsize is None:
                        _pbsize = len(block)
                        self._plaintext_blocksize = _pbsize
                    self._msg_buf.append(block)
                    len_bytes = self._msg_buf.peek(2)
                    if _pyver == 2:
                        self._plaintext_len = 1 + ((_b_ord(len_bytes[0]) << 8)
                                                   + _b_ord(len_bytes[1]))
                    else:
                        self._plaintext_len = 1 + ((len_bytes[0] << 8)
                                                   + len_bytes[1])
                    self._have_len = True

            # If we have first block, decrypt more blocks as available/needed
            if self._have_len:
                msg_len = 2 + self._plaintext_len + self._hash_len
                pad_len = msg_len % _pbsize
                if pad_len:
                    pad_len = _pbsize - pad_len
                    msg_len += pad_len
                msg_left = msg_len - len(self._msg_buf)
                blocks_left = msg_left//_pbsize
                input_left = (blocks_left*_cbsize
                              - len(self._in_buf))
                in_data = read_buf.pop(input_left)
                num_read += len(in_data)
                self._in_buf.append(in_data)
                num_decode = len(self._in_buf)
                num_decode -= num_decode % _cbsize
                if num_decode > 0:
                    enc_data = self._in_buf.pop(num_decode)
                    self._msg_buf.append(self._decrypter(enc_data))
                elif len(self._msg_buf) != msg_len:
                    break

            if self._have_len and len(self._msg_buf) == msg_len:
                len_bytes = self._msg_buf.pop(2)
                plaintext = self._msg_buf.pop(self._plaintext_len)
                padding = self._msg_buf.pop(pad_len)
                msg_hash = self._msg_buf.pop(self._hash_len)

                _mac_msg = b''.join((posint_to_bytes(self._msg_num), len_bytes,
                                     plaintext, padding))
                if msg_hash == self._hash_cls.hmac(self._mac_secret, _mac_msg):
                    self._result = plaintext
                    self._msg_num += 1
                else:
                    self._invalid = True

        return num_read

    def done(self):
        """Returns True if decryption and decoding of a message was done.

        :returns: True if reading is done
        :rtype:   bool
        :raises:  :exc:`versile.crypto.VCryptoException`

        Raises an exception if the message failed to verify against
        the message hash, meaning the message cannot be trusted and
        could have been tampered with.

        """
        if self._invalid:
            raise VCryptoException('Message failed to verify')
        return (self._result is not None)

    def result(self):
        """Returns plaintext of a decrypted and decoded message.

        :returns: decoded plaintext
        :rtype:   bytes
        :raises:  :exc:`versile.crypto.VCryptoException`

        Should only be called if :meth:`done` indicates message
        parsing was completed, otherwise an exception may be raised
        due to incomplete message.

        Raises an exception if the message failed to verify against
        the message hash, meaning the message cannot be trusted and
        may have been tampered with.

        """
        if self._invalid:
            raise VCryptoException('Message failed to verify')
        elif self._result is None:
            raise VCryptoException('Message not yet fully decoded')
        return self._result

    def has_data(self):
        """Returns True if object holds any data

        :returns: True if holds data
        :rtype:   bool

        Returns False only if no data has been read since the object
        was instantiated or since the most recent :meth:`reset`\ .

        """
        return bool(self._read_buf or self._in_buf or
                    self._msg_buf or self._result)

    @property
    def max_plaintext_len(self):
        """Maximum plaintext length allowed in a message."""
        return self._max_plaintext_len
