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

"""Cryptographic math functions."""
from __future__ import print_function, unicode_literals

from copy import copy
from random import randint

from versile.internal import _vexport

__all__ = ['egcd', 'euler_sieve', 'is_prime', 'miller_rabin',
           'mod_inv', 'next_prime']
__all__ = _vexport(__all__)


def euler_sieve(n):
    """Returns a list of all prime numbers <= n

    :param n: an integer
    :type  n: int, long
    :returns: list of all prime numbers 'p' such that p <= n
    :rtype:   list<int,long>

    Implements the `Sieve of Eratosthenes
    <http://en.wikipedia.org/wiki/Sieve_of_Eratosthenes>`__ as per
    Euler's algorithm.

    """
    candidates = range(n+1)
    fin = int(n**0.5)
    for i in xrange(2, fin+1):
        if not candidates[i]:
            continue
        candidates[2*i::i] = [None] * (n//i - 1)
    return [i for i in candidates[2:] if i]


# A list of small primes for internal use by this module
#
# Note: this value should be large enough that it goes well past
# the value 65537 due to the from_primes key generation algorithm,
# see versile.crypto.local.from_primes() for further comments
_SMALL_PRIMES = euler_sieve(100000)


def miller_rabin(num, k):
    """Miller-Rabin primality test on the number 'num'.

    :param num: number to test
    :type  num: int, long
    :param k:   number of test loops to execute
    :type  k:   int
    :returns:   True if probably prime, False if definitely not prime

    If return value is False then *num* is not a prime. If return
    value is True then the probability that *num* is noe a prime is
    less than 4**(-\ *k*\ ). Implements the `Miller-Rabin
    <http://en.wikipedia.org/wiki/Rabin_miller>`__ probabilistic
    primality test.

    """
    # Check valid number and special cases
    if not (isinstance(num, int) or isinstance(num, long)) or num < 2:
        raise Exception('Number to test must be an integer >= 2')
    if num % 2 == 0:
        return False
    if num == 2:
        return True

    # Find s, d so that num - 1 == d * 2**s
    s, d = (0, num - 1)
    while True:
        q, r = divmod(d, 2)
        if r == 1:
            break
        s += 1
        d = q

    for loop in xrange(k):
        a = randint(2, num - 2)
        x = pow(a, d, num)
        if x == 1 or x == (num - 1):
            continue
        for r in xrange(1, s):
            x = pow(x, 2, num)
            if x == 1:
                return False
            elif x == (num - 1):
                break
        else:
            return False
    return True


def is_prime(num, k):
    """Primality test whether 'num' is prime.

    See :func:`miller_rabin` for arguments and return value. This
    function is a convenience function for combining
    :func:`miller_rabin` with an euler sieve to reduce the number of
    large-number power modulo calculations.

    """
    if num % 2 == 0:
        return False
    if num == 2:
        return True
    # Euler sieve verification should be retained here in order for
    # from_primes() code not to revert to probabilistic primality tests
    for i in _SMALL_PRIMES:
        if num == i:
            return True
        elif (num % i) == 0:
            return False
    return miller_rabin(num, k)


def next_prime(num, k, callback=None):
    """Returns the first number n >= num which is (probably) a prime.

    :param num:      first number to check for primality
    :type  num:      int, long
    :param k:        number of Miller-Rabin test loops for primality check
    :type  k:        int
    :param callback: callback for the number of tested prime candidates
    :type  callback: callable
    :returns:        first number n >= num which satisfies primality test
    :rtype:          int, long

    Finds and returns the first number p >= n such that p satisfies
    the :func:`miller_rabin` primality test. See that function for
    interpretation of the *k* argument.

    If *callback* is set, it is called each time a new prime candidate
    is tested. It can be used for monitoring the process of prime
    number generation.

    """
    small_primes = set(copy(_SMALL_PRIMES))
    offset = 0
    known_factors = dict()
    while True:
        if offset in known_factors:
            # Skip any number which has been tagged via sieving
            for prime in known_factors[offset]:
                next_offset = offset + prime
                if not known_factors.has_key(next_offset):
                    known_factors[next_offset] = set()
                known_factors[next_offset].add(prime)
            known_factors.pop(offset, None)
        else:
            # Go through known_factors to see if a factor is found
            test_num = num + offset
            for prime in small_primes:
                if (test_num % prime) == 0:
                    next_offset = offset + prime
                    if not known_factors.has_key(next_offset):
                        known_factors[next_offset] = set()
                    known_factors[next_offset].add(prime)
                    small_primes.discard(prime)
                    break
            else:
                # No match via sieve - use miller_rabin()
                if miller_rabin(test_num, k):
                    return test_num
        offset += 1
        if callback:
            callback(offset)


def egcd(a, b):
    """Compute the greatest common divisor with Extended Euclidian Algorithm.

    :type a:  int, long
    :type b:  int, long
    :returns: (g, x, y), such that ax + by = g = gcd(a, b)
    :rtype:   int, long

    Based on the `Extended Euclidean algorithm
    <http://en.wikibooks.org/wiki/Algorithm_Implementation/Mathematics/Extended_Euclidean_algorithm>`__
    for computing greatest common divisors.

    """
    x, y = 0, 1
    u, v = 1, 0
    while a:
        q, r = b//a, b%a
        m, n = x - u*q, y - v*q
        b, a = a, r
        x, y, u, v = u, v, m, n
    return b, x, y


def mod_inv(a, m):
    """Returns the modular inverse of a modulo m.

    :param a: base
    :type  a: int, long
    :param m: modulo
    :type  m: int, long
    :returns: a^(-1) mod m (or None if no inverse exists)

    Uses :func:`egcd` to compute modular inverse.

    """

    g, x, y = egcd(a, m)
    if g != 1:
        return None
    else:
        return x % m
