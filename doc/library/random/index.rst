.. _lib_rand:

Random Numbers
==============
.. currentmodule:: versile.crypto.rand

This is the API documentation for the :mod:`versile.crypto.rand`
module which implements mechanism for generating random and
pseudo-random data.

Byte Generator
--------------

Byte generation generally involves the procedure of requesting and
receiving *n* bytes of data. :class:`VByteGenerator` is an abstract
class which defines method for generating
data. :meth:`VByteGenerator.__call__` and :meth:`VByteGenerator.data`
generate byte data, and :meth:`VByteGenerator.number` generates an
integer.

Below is a simple example of using a (random) byte generator:

>>> from versile.crypto.rand import VUrandom
>>> gen = VUrandom()
>>> data = gen.data(10)
>>> (type(data), len(data))
(<type 'str'>, 10)
>>> data = gen(10)
>>> (type(data), len(data))
(<type 'str'>, 10)
>>> num = gen.number(0, 100)
>>> (type(num), 0 <= num <= 100)
(<type 'long'>, True)

Random Numbers
--------------

:class:`VUrandom` uses :func:`os.urandom` to generate random
numbers. The function may not be available on all platforms and the
properties of the generated numbers are OS dependent. E.g. on Linux it
reads from /dev/urandom which creates numbers which are often
considered "strong enough" for most purposes by combining
pseudo-random methods with mixing in entropy from the OS. However, for
truly cryptographically strong numbers it is not always considered to
be sufficient.

Hash Reducer
------------

:class:`VHashReducer` implements a hash reducer which feeds input data
from another generator through a hash function with a set ratio
between input data read and output data provided. This can be used to
take a larger set of data with low but evenly spread entropy, and
reduce it to a smaller data set which higher entropy per byte of data.

Below is an example which takes a source of input data and churns it
through a SHA1 hash, and for each output byte reading 10x as many
bytes from the output:

>>> from versile.crypto.local import VLocalCrypto
>>> from versile.crypto.rand import VUrandom, VHashReducer
>>> crypto = VLocalCrypto()
>>> hasher = crypto.sha1()
>>> input = VUrandom()
>>> output = VHashReducer(input, hasher, 10)
>>> data = output(10)
>>> (type(data), len(data))
(<type 'str'>, 10)

.. note::
   
   There should normally be little to gain from combining
   :class:`VUrandom` with a hash reducer as in the previous example,
   because there is little additional entropy introduced by the OS,
   and reading lots of data from the input will only reduce the amount
   of new entropy available to the OS. However, it makes sense to
   combine hash reduction with a source of new/additional entropy such
   as e.g. tracking random mouse movements.
   
Pseudo-Random Data
------------------

Pseudo-random data can be generated from a set of input parameters and
an algorithm which together will always generate the same output data
sequence. With a cryptographically strong algorithm for pseudo-random
data the generated data should (ideally) appear indistinguishable from
truly random data to an outsider.

:class:`VPseudoRandomHMAC` implements the :term:`HMAC` based
pseudo-random function specified by :rfc:`5246`\ . Below is an example
how it could be used:

>>> from versile.crypto import VCrypto
>>> from versile.crypto.rand import VPseudoRandomHMAC
>>> c = VCrypto.lazy()
>>> secret=b'some_shared_secret'
>>> seed = b'asdf908uasdfkjn34kjrthsa8odfhsdkjfh'
>>> pseudo_rand = VPseudoRandomHMAC(c.sha256, secret, seed)
>>> pseudo_rand(20)
'\x8a\xa5s?\x0b\xe8\xc1\x84}\x87"Y;\xaf\xa9\xd1@\x8a\xa5\xe5'
>>> pseudo_rand(20)
'\x0c\x98\xbc\x1b\x98\xfdQ\x96\x11~#\x83\xb4r\x82\xf5+w\x93\x81'

A general method for generating pseudo-random data is to use a
:class:`VTransformer` which performs block transformation on data from
a :class:`VByteGenerator` providing deterministic input data. A
transform can be set up to perform e.g. a block cipher in OFB mode to
generate pseudo-random data from the inputs. Below is an example which
uses a blowfish cipher with an incrementing input to generate
pseudo-random data:

>>> from versile.crypto.local import VLocalCrypto
>>> from versile.crypto.rand import VTransformer, VIncrementer
>>> indata = VIncrementer(1, b'\x00')
>>> crypto = VLocalCrypto()
>>> cipher = crypto.blowfish
>>> key = cipher.key_factory.load(b'keYdATa')
>>> transform = cipher.encrypter(key, mode=u'ofb')
>>> pseudo_rand = VTransformer(indata, transform, transform.blocksize)
>>> pseudo_rand(20)
'V\xd5t\x12\x94\xcd\xb9wL)\x83\x86\xb8\x9fL\n:3\xfc%'

Combining Generators
--------------------

:class:`VCombiner` combines the output of multiple generators and
performs an xor operation on all sources. This can be used e.g. to mix
random numbers generated from two separate sources, in order to
uniformly mix their entropy. Below is a generic example to show how
two sources can be mixed:

>>> from versile.crypto.rand import VConstantGenerator, VIncrementer
>>> from versile.crypto.rand import VCombiner
>>> source1 = VConstantGenerator(b'A')
>>> source2 = VIncrementer(1, b'\x00')
>>> combined = VCombiner(source1, source2)
>>> combined(10)
'A@CBEDGFIH'

Other Generators
----------------

:class:`VConstantGenerator` repeats a fixed byte sequence, e.g.

>>> from versile.crypto.rand import VConstantGenerator
>>> gen = VConstantGenerator(b'qwerty')
>>> gen(15)
'qwertyqwertyqwe'

:class:`VIncrementer` performs auto-incrementation on a block of fixed
side, interpreting the block as an unsigned integer and increasing by
1 for each new block. A couple examples:

>>> from versile.crypto.rand import VIncrementer
>>> gen1 = VIncrementer(3)
>>> gen1(15)
'\x00\x00\x00\x00\x00\x01\x00\x00\x02\x00\x00\x03\x00\x00\x04'
>>> gen2 = VIncrementer(2, b'AA')
>>> gen2(15)
'AAABACADAEAFAGA'

:class:`VProxyGenerator` converts a byte-generating function into a
:class:`VByteGenerator`\ , which is useful for APIs where a generator
is required. A code example:

>>> from versile.crypto.rand import VProxyGenerator
>>> const_output = lambda n: n*b'q'
>>> gen = VProxyGenerator(const_output)
>>> gen(10)
'qqqqqqqqqq'

Module APIs
-----------
Module API for :mod:`versile.crypto.rand`

.. automodule:: versile.crypto.rand
    :members:
    :show-inheritance:
