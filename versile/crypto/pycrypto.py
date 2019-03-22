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

"""Crypto provider using crypto functions from 3rd party library PyCrypto."""
from __future__ import print_function, unicode_literals

from Crypto.Hash import SHA
from Crypto.Cipher import Blowfish, AES
from Crypto.PublicKey import RSA

from versile.internal import _s2b, _vexport
from versile.common.util import VObjectIdentifier
from versile.crypto import VCrypto, VHash, VCryptoException
from versile.crypto import VBlockCipher, VBlockTransform, VNumCipher
from versile.crypto import VNumTransform, VKeyFactory, VKey, VAsymmetricKey
from versile.crypto import VRSAKeyFactory
from versile.crypto.math import is_prime, mod_inv

__all__ = ['PyCrypto']
__all__ = _vexport(__all__)


class PyCrypto(VCrypto):
    """Crypto provider which uses the 3rd party pycrypto library.

    Provides the following cryptographic methods:

    +----------------+-------------------------------------------------------+
    | Domain         | Methods                                               |
    +================+=======================================================+
    | Hash types     | sha1                                                  |
    +----------------+-------------------------------------------------------+
    | Block ciphers  | blowfish, aes128, aes192, and aes256 in cbc/ofb modes |
    +----------------+-------------------------------------------------------+
    | Num ciphers    | rsa                                                   |
    +----------------+-------------------------------------------------------+

    .. note::

        This provider relies on the 3rd library `PyCrypto
        <http://pycrypto.org/>`__ for encryption\ . If the associated
        python modules are not available then this provider cannot be
        instantiated.

    """

    @property
    def hash_types(self):
        return ('sha1' , )

    def hash_cls(self, hash_name):
        # ISSUE - SHA256 was faulty in an earlier version of PyCrypto, ref.
        # https://bugs.launchpad.net/ubuntu/+source/python-crypto/+bug/191683
        # Because of this SHA256 is (for now) not included with this provider
        # as it is anyways provided by the local crypto provider which uses
        # the implementation of the python standard library
        hash_oid = None
        if hash_name == 'sha1':
            hash_cls = SHA
            hash_oid = VObjectIdentifier(1, 3, 14, 3, 2, 26)
        else:
            raise VCryptoException('Hash function not supported')
        class PyCryptoHash(VHash):
            _hash_cls = hash_cls
            @classmethod
            def name(cls):
                return hash_name
            @classmethod
            def oid(cls):
                return hash_oid
            @classmethod
            def digest_size(cls):
                return cls._hash_cls.digest_size
            def __init__(self, data=None):
                self._hash = hash_cls.new()
                super(PyCryptoHash, self).__init__(data=data)
            def update(self, data):
                self._hash.update(data)
            def digest(self):
                return self._hash.digest()
        return PyCryptoHash

    @property
    def block_ciphers(self):
        return ('blowfish', 'blowfish128', 'aes128', 'aes192', 'aes256', 'rsa')

    def block_cipher(self, cipher_name):
        if cipher_name == 'blowfish':
            return _PyBlowfish()
        elif cipher_name == 'blowfish128':
            return _PyBlowfish128()
        elif cipher_name[:3] == 'aes':
            if cipher_name == 'aes128':
                return _PyAES(128//8)
            elif cipher_name == 'aes192':
                return _PyAES(192//8)
            elif cipher_name == 'aes256':
                return _PyAES(256//8)
        elif cipher_name == 'rsa':
            num_cipher = self.num_cipher('rsa')
            return num_cipher.block_cipher()
        else:
            raise VCryptoException('Cipher not supported by this provider')

    @property
    def num_ciphers(self):
        return ('rsa',)

    def num_cipher(self, cipher_name):
        if cipher_name == 'rsa':
            return _PyRSANumCipher()
        else:
            raise VCryptoException('Cipher not supported by this provider')

    def import_ascii_key(self, keydata):
        name, data = VKeyFactory._decode_ascii(keydata)
        if name.startswith('VERSILE RSA'):
            return self.rsa.key_factory.import_ascii(keydata)
        else:
            raise VCryptoException()


class _PyBlockCipher(VBlockCipher):
    def __init__(self, *args):
        super_init=super(_PyBlockCipher, self).__init__
        super_init(*args)

    def encrypter(self, key, iv=None, mode='cbc'):
        keydata = self._keydata(key)
        if iv is None:
            iv = self.blocksize(key)*b'\x00'
        return self._transform(keydata, iv, mode, encrypt=True)

    def decrypter(self, key, iv=None, mode='cbc'):
        keydata = self._keydata(key)
        if iv is None:
            iv = self.blocksize(key)*b'\x00'
        return self._transform(keydata, iv, mode, encrypt=False)

    def _transform(self, keydata, iv, mode, encrypt):
        raise NotImplementedError()

    def _keydata(self, key):
        if isinstance(key, VKey):
            if key.cipher_name == self.name:
                return key.keydata
            else:
                raise VCryptoException('Key ciphername mismatch')
        raise TypeError('Key must be bytes or a Key object')

    @property
    def key_factory(self):
        raise NotImplementedError()


class _PyBlockTransform(VBlockTransform):
    def __init__(self, keydata, iv, mode, encrypt, blocksize):

        super(_PyBlockTransform, self).__init__(blocksize=blocksize)

        if not isinstance(keydata, bytes) or not 1 <= len(keydata) <= 56:
            raise VCryptoException('Invalid key data')
        elif not isinstance(iv, bytes) or len(iv) != self.blocksize:
            raise VCryptoException('Invalid initialization vector')

        self.__encrypt = bool(encrypt)
        self.__cipher = self._pycrypto_cipher(keydata, iv, mode)

    def _pycrypto_cipher(self, keydata, iv, mode):
        raise NotImplementedError()

    def _transform(self, data):
        if self.__encrypt:
            return self.__cipher.encrypt(data)
        else:
            return self.__cipher.decrypt(data)


class _PyKeyFactory(VKeyFactory):
    def generate(self, source, length, p=None):
        min_l, max_l, size_inc = self.constraints()
        if not min_l <= length <= max_l or length % size_inc:
            raise VCryptoException('Invalid key length')
        keydata = source(length)
        return self._key_from_keydata(keydata)

    def _key_from_keydata(self, keydata):
        raise NotImplementedError()

    def load(self, keydata):
        if not isinstance(keydata, bytes):
            raise VCryptoException('Keydata must be in bytes format')
        min_l, max_l, size_inc = self.constraints()
        if not min_l <= len(keydata) <= max_l or len(keydata) % size_inc:
            raise VCryptoException('Invalid key length')
        return self._key_from_keydata(keydata)


class _PyKey(VKey):
    def __init__(self, name, keydata):
        super(_PyKey, self).__init__(name)
        self.__keydata = keydata

    @property
    def keydata(self):
        return self.__keydata


class _PyBlowfish(_PyBlockCipher):
    def __init__(self, name='blowfish'):
        super_init=super(_PyBlowfish, self).__init__
        super_init(name, ('cbc', 'ofb'), True)

    def blocksize(self, key=None):
        return 8

    def c_blocksize(self, key=None):
        return 8

    def _transform(self, keydata, iv, mode, encrypt):
        return _PyBlowfishTransform(keydata, iv, mode, encrypt)

    @property
    def key_factory(self):
        return _PyBlowfishKeyFactory()


class _PyBlowfish128(_PyBlowfish):
    def __init__(self):
        super(_PyBlowfish128, self).__init__(name='blowfish128')

    @property
    def key_factory(self):
        return _PyBlowfish128KeyFactory()


class _PyBlowfishTransform(_PyBlockTransform):
    def __init__(self, keydata, iv, mode, encrypt):
        super_init = super(_PyBlowfishTransform, self).__init__
        super_init(keydata, iv, mode, encrypt, blocksize=8)

    def _pycrypto_cipher(self, keydata, iv, mode):
        if mode == 'cbc':
            _mode = Blowfish.MODE_CBC
        elif mode == 'ofb':
            _mode = Blowfish.MODE_OFB
        else:
            raise VCryptoException('Mode not supported')
        return Blowfish.new(keydata, _mode, iv)


class _PyBlowfishKeyFactory(_PyKeyFactory):
    def __init__(self, max_len=56):
        super_init = super(_PyBlowfishKeyFactory, self).__init__
        super_init(min_len=1, max_len=max_len, size_inc=1)

    def generate(self, source, length=56, p=None):
        return super(_PyBlowfishKeyFactory, self).generate(source, length, p)

    def _key_from_keydata(self, keydata):
        return _PyBlowfishKey(keydata)


class _PyBlowfish128KeyFactory(_PyBlowfishKeyFactory):
    def __init__(self, max_len=16):
        super(_PyBlowfish128KeyFactory, self).__init__(max_len=max_len)

    def generate(self, source, length=16, p=None):
        _super = super(_PyBlowfish128KeyFactory, self).generate
        return _super(source=source, length=length, p=p)

    def _key_from_keydata(self, keydata):
        if len(keydata) > 16:
            raise VCryptoException('Maximum key length is 128 bits')
        return _PyBlowfish128Key(keydata)


class _PyBlowfishKey(_PyKey):
    def __init__(self, keydata, name='blowfish'):
        super(_PyBlowfishKey, self).__init__(name, keydata)


class _PyBlowfish128Key(_PyBlowfishKey):
    def __init__(self, keydata):
        super(_PyBlowfish128Key, self).__init__(keydata, name='blowfish128')


class _PyAES(_PyBlockCipher):
    def __init__(self, keylen):
        if keylen not in (16, 24, 32):
            raise VCryptoException('Not a supported AES key length')
        else:
            self.__keylen = keylen
        super_init=super(_PyAES, self).__init__
        super_init('aes%s' % self.__keylen, ('cbc', 'ofb'), True)

    def blocksize(self, key=None):
        return 16

    def c_blocksize(self, key=None):
        return 16

    def _transform(self, keydata, iv, mode, encrypt):
        return _PyAESTransform(self.__keylen, keydata, iv, mode, encrypt)

    @property
    def key_factory(self):
        return _PyAESKeyFactory(self.__keylen)


class _PyAESTransform(_PyBlockTransform):
    def __init__(self, keylen, keydata, iv, mode, encrypt):
        super_init = super(_PyAESTransform, self).__init__
        super_init(keydata, iv, mode, encrypt, blocksize=16)
        self.__keylen = keylen

    def _pycrypto_cipher(self, keydata, iv, mode):
        if mode == 'cbc':
            _mode = AES.MODE_CBC
        elif mode == 'ofb':
            _mode = AES.MODE_OFB
        else:
            raise VCryptoException('Mode not supported')
        return AES.new(keydata, _mode, iv)


class _PyAESKeyFactory(_PyKeyFactory):
    def __init__(self, keylen):
        super_init = super(_PyAESKeyFactory, self).__init__
        super_init(min_len=keylen, max_len=keylen, size_inc=1)
        self.__keylen = keylen

    def generate(self, source, length=None, p=None):
        if length is None:
            length = self.__keylen
        return super(_PyAESKeyFactory, self).generate(source, length, p)

    def _key_from_keydata(self, keydata):
        return _PyAESKey(self.__keylen, keydata)


class _PyAESKey(_PyKey):
    def __init__(self, keylen, keydata):
        super(_PyAESKey, self).__init__('aes%s' % keylen, keydata)


class _PyRSANumCipher(VNumCipher):
    def __init__(self):
        super_init = super(_PyRSANumCipher, self).__init__
        super_init(name='rsa', symmetric=False)

    def encrypter(self, key):
        keydata = self._keydata(key)
        return _PyRSANumTransform(keydata, encrypt=True)

    def decrypter(self, key):
        keydata = self._keydata(key)
        return _PyRSANumTransform(keydata, encrypt=False)

    @property
    def key_factory(self):
        return _PyRSAKeyFactory()

    def _keydata(self, key):
        if isinstance(key, VAsymmetricKey) and key.cipher_name == 'rsa':
            return key.keydata
        else:
            raise VCryptoException('Invalid key type')


class _PyRSANumTransform(VNumTransform):
    def __init__(self, keydata, encrypt):
        def _convert(num):
            if num is not None:
                return long(num)
            else:
                return None
        self.__keydata = [_convert(item) for item in keydata]
        n, e, d = self.__keydata[:3]

        if encrypt:
            if e is None:
                raise VCryptoException('Encrypt requires public key')
            py_key = RSA.construct((n, e))
            self.__transform = lambda num: py_key.encrypt(num, None)[0]
        else:
            if d is None:
                raise VCryptoException('Decrypt requires private key')
            if e is not None:
                py_key = RSA.construct((n, e, d))
                self.__transform = lambda num: py_key.decrypt(num)
            else:
                # Rephrase as 'encrypt', PyCrypto does not have private-only
                py_key = RSA.construct((n, d))
                self.__transform = lambda num: py_key.encrypt(num, None)[0]

    def transform(self, num):
        if isinstance(num, int):
            num = long(num)
        elif not isinstance(num, long):
            raise VCryptoException('Transformed number must be int or long')
        return self.__transform(num)

    @property
    def max_number(self):
        return self.__keydata[0] - 1


class _PyRSAKeyFactory(VRSAKeyFactory):
    def __init__(self):
        super_init = super(_PyRSAKeyFactory, self).__init__
        super_init(min_len=2, max_len=None, size_inc=1)

    def generate(self, source, length, p=None, callback=None):
        """Generates and returns a key with given key length.

        :param callback: if not None, a callback function for progress
        :type  callback: callable

        Usage and other arguments are similar to
        :meth:`versile.crypto.VKeyFactory.generate`\ .

        If callback is defined, then callback(n) is called with 'n' the number
        of key generation operation that have been performed.

        Note that pycrypto does not support specifying the 'p'
        parameter and will raise an exception if it is not set to
        None.

        If *length* is < 1024 or is not a multiple of 512/8, then
        :class:`versile.crypto.VLocalProvider` is used instead for
        generating the key (as newer versions of pycrypto do not
        accept those parameters for key generation).

        """
        if p is not None:
            raise VCryptoException('PyCrypto does not support setting p arg')
        if length < (1024//8) or length % (512//8):
            from versile.crypto.local import VLocalCrypto
            kf = VLocalCrypto().rsa.key_factory
            return kf.generate(source, length, callback=callback)
        if callback:
            class C:
                def __init__(self):
                    self.iterations = 0
                def cback(self, *args):
                    self.iterations += 1
                    callback(self.iterations)
            c = C()
            key = RSA.generate(length*8, source, c.cback)
        else:
            key = RSA.generate(length*8, source)
        keydata = (key.n, key.e, key.d, key.p, key.q)
        return _PyRSAKey(keydata)

    @classmethod
    def from_primes(cls, p, q):
        n = p*q
        t = (p-1)*(q-1)
        e = 65537

        # Handle the (normally very, very low probability) special
        # case that n is a small number - this may the case for
        # some test code using small primes
        if e >= n:
            e = n/2 + n%2

        while t % e == 0:
            e += 1
            # The value 56 is hardcoded for a high probability test -
            # however - see versile.crypto.math._SMALL_PRIMES doc -
            # with that variable set properly, the test is expected to
            # nearly always be resolved based on deterministic Euler
            # sieve tests
            while not is_prime(e, 56): # HARDCODED
                e += 1
        d = mod_inv(e, t)
        if d is None:
            raise VCryptoException('Could not generate key')
        if (d*e) % t == 1:
            keydata = (n, e, d, p, q)
            return _PyRSAKey(keydata)
        else:
            raise VCryptoException('Could not generate key')

    def import_ascii(self, keydata):
        name, num_data = self._decode_ascii(keydata)
        if not name.startswith(b'VERSILE RSA '):
            raise VCryptoException()
        name = name[12:]
        numbers = self._decode_numbers(num_data)
        if name == b'KEY PAIR':
            if len(numbers) != 5:
                raise VCryptoException()
            keydata = tuple(numbers)
        elif name == b'PUBLIC KEY':
            if len(numbers) != 2:
                raise VCryptoException()
            keydata = (numbers[0], numbers[1], None)
        elif name == b'PRIVATE KEY':
            if len(numbers) != 2:
                raise VCryptoException()
            keydata = (numbers[0], None, numbers[1])
        else:
            raise VCryptoException()
        return _PyRSAKey(keydata)

    def load(self, keydata):
        return _PyRSAKey(keydata)


class _PyRSAKey(VAsymmetricKey):
    def __init__(self, keydata):
        super(_PyRSAKey, self).__init__('rsa')

        if not isinstance(keydata, (tuple, list)) or len(keydata) != 5:
            raise VCryptoException('RSA key data must be 5-tuple')
        for item in keydata:
            if not (item is None or
                    isinstance(item, (int, long)) and item >= 0):
                raise VCryptoException('Invalid key data')
        n, e, d, p, q = keydata
        if n is None:
            raise VCryptoException('RSA n parameter cannot be None')
        if e is None and d is None:
            raise VCryptoException('RSA e and d params cannot both be None')
        for _param in (e, d, p, q):
            if _param is not None and not 0 < _param < n:
                raise VCryptoException('Invalid parameter')
        if p is None != q is None:
            raise VCryptoException('p and q cannot both be None')
        if p is not None and p*q != n:
            raise VCryptoException('p*q != n')
        self.__keydata = keydata
        # Parameters for X.509 encoding, access via properties
        self.__exp1 = self.__exp2 = self.__coeff = None

    @property
    def has_private(self):
        return (self.__keydata[2] is not None)

    @property
    def has_public(self):
        return (self.__keydata[1] is not None)

    @property
    def private(self):
        n, e, d = self.__keydata[:3]
        return _PyRSAKey((n, None, d, None, None))

    @property
    def public(self):
        n, e, d = self.__keydata[:3]
        return _PyRSAKey((n, e, None, None, None))

    def merge_with(self, key):
        if self.name != key.name:
            raise VCryptoException('Key cipher types do not match')
        if self.keydata[0] != key.keydata[0]:
            raise VCryptoException('Key modulos do not match')
        if self.has_public and key.has_public:
            if self.keydata[1] != key.keydata[1]:
                raise VCryptoException('Key public component mismatch')
        if self.has_private and key.has_private:
            if self.keydata[2] != key.keydata[2]:
                raise VCryptoException('Key private component mismatch')
        if self.has_private:
            n = self.keydata[0]
            e = key.keydata[1]
            d = self.keydata[2]
        else:
            n = self.keydata[0]
            e = self.keydata[1]
            d = key.keydata[2]
        if None in (n, e, d):
            raise VCryptoException('Incomplete key data, cannot merge')
        # Try to recover p, q factors
        p, q = self.keydata[3:]
        if key.keydata[3] is not None:
            p = key.keydata[3]
        if key.keydata[4] is not None:
            q = key.keydata[4]
        if p is None or q is None:
            p = q = None
        elif p*q != n:
            raise VCryptoException('Got p,q, however p*q != n')
        return _PyRSAKey((n, e, d, p, q))

    def export_ascii(self):
        if self.has_private and self.has_public:
            name = b'KEY PAIR'
            numbers = self.keydata
        elif self.has_private:
            name = b'PRIVATE KEY'
            numbers = (self.keydata[0], self.keydata[2])
        elif self.has_public:
            name = b'PUBLIC KEY'
            numbers = (self.keydata[0], self.keydata[1])
        else:
            raise VCryptoException()
        name = b'VERSILE RSA ' + name
        return self._encode_ascii(name, numbers)

    @property
    def keydata(self):
        return self.__keydata

    @property
    def _exp1(self):
        if self.__exp1 is None:
            d, p = self.__keydata[2], self.__keydata[3]
            if d is None or p is None:
                raise VCryptoException()
            self.__exp1 = d % (p-1)
        return self.__exp1

    @property
    def _exp2(self):
        if self.__exp2 is None:
            d, q = self.__keydata[2], self.__keydata[4]
            if d is None or q is None:
                raise VCryptoException()
            self.__exp2 = d % (q-1)
        return self.__exp2

    @property
    def _coeff(self):
        if self.__coeff is None:
            p, q = self.__keydata[3], self.__keydata[4]
            if p is None or q is None:
                raise VCryptoException()
            self.__coeff = mod_inv(q, p)
        return self.__coeff
