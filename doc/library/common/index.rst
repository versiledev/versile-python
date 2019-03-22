.. _lib_common:

Common Functionality
====================
.. currentmodule:: versile.common.util

This is the API documentation for various :term:`VPy` utility classes
and functions.

Utility Classes
---------------

:class:`VByteBuffer` is a FIFO byte buffer for byte data. It offers a
convenient interface and aims to be efficient by holding data as a
list of appended byte chunks and only performing join operations when
required.

>>> from versile.common.util import *
>>> buf = VByteBuffer()
>>> buf.append(b'This is a')
>>> buf.append(b'buffer example')
>>> buf.pop(3)
'Thi'
>>> buf.peek(3)
's i'
>>> buf.pop(3)
's i'
>>> buf.pop()
's abuffer example'

:class:`VBitfield` holds a sequence of bits. The number of bits can be
any length.

>>> from versile.common.util import VBitfield
>>> b1 = VBitfield((1, 0, 0, 1))
>>> b2 = VBitfield((1, 1, 0, 0, 0))
>>> b1 & b2
'01000'
>>> b1 | b2
'11001'
>>> b1.as_octets()
'\t'
>>> VBitfield.from_octets(b'\xf0\x0f')
'1111000000001111'


:class:`VObjectIdentifier` represents a formal :term:`Object
Identifier`\ . It is a convention for identifying objects which is
used in several standards such as e.g. :term:`X.509`\ .

>>> from versile.common.util import VObjectIdentifier
>>> # This is the identifier for country name for X.501 Distinguished Names
... oid = VObjectIdentifier((2, 5, 4, 6))
>>> oid
'2.5.4.6'
>>> oid.oid
(2, 5, 4, 6)

:class:`VUniqueIDProvider` is a simple (abstract) framework for
generating unique IDs. :class:`VLinearIDProvider` is an implementation
which generates integers.

>>> from versile.common.util import VLinearIDProvider
>>> id_gen = VLinearIDProvider()
>>> id_gen.get_id()
1
>>> id_gen.get_id()
2
>>> id_gen.get_id()
3
>>> id_gen.peek_id()
4
>>> id_gen.get_id()
4

:class:`VResult` provides a mechanism for referencing an asynchronous
call result in a threaded environment, with methods for a provider to
register the result of an operation when available, and methods for a
consumer to wait on the result.

.. note::

    :class:`VResult` may appear redundant to
    :class:`versile.common.pending.VPending`\ , however the key words
    here are 'threaded environment'. The latter is designed to operate
    in a single-thread environment such as a reactor.

Below is a simple example.

>>> from versile.common.util import VResult
>>> from threading import Timer
>>> result = VResult()
>>> def operation():
...     result.push_result(42)
... 
>>> t = Timer(0.02, operation)
>>> t.start()
>>> result.result()
42

:class:`VSimpleBus` is a bus for pushing objects to subscribed
listeners. Below is an example.

>>> from versile.common.util import VSimpleBus
>>> bus = VSimpleBus()
>>> class Listener(object):
...     def bus_push(self, obj):
...         print('Listener got %s' % obj)
... 
>>> listener = Listener()
>>> bus.register(listener)
1
>>> bus.push(42)
Listener got 42
>>> 

:class:`VConfig` inherits :class:`dict` and is designed to hold a set
of configuration key-value properties. It provides convenient getattr
and setattr overloading to access configuration values.

>>> from versile.common.util import VConfig
>>> conf = VConfig(max_len=13, prefix=u'temp')
>>> conf.keys()
['max_len', 'prefix']
>>> conf['max_len']
13
>>> conf.max_len
13

:class:`VNamedTemporaryFile` inherits :class:`file` and instantiating
the class generates a named temporary file similar to files generated
by :func:`tempfile.NamedTemporaryFile`\ . It may be configured so that
the file is deleted when the instantiated object is garbage collected
(this is the default behaviour), and if the *secdel* construction
argument is True then the file is overwritten with random data before
it is deleted.

.. note::

   Secure deletion is not a robust security feature as it depends on
   execution of __del__ during garbage collection. Refer to
   :class:`VNamedTemporaryFile` for details.

Below is a simple example of creating and using a temporary file.

>>> from versile.common.util import VNamedTemporaryFile
>>> f = VNamedTemporaryFile(secdel=True)
>>> f.write(b'this file will be securely deleted when garbage collected')
>>> f.seek(0)
>>> f.read()
'this file will be securely deleted when garbage collected'
>>> del(f)


Synchronization
---------------

:class:`VCondition` is an alternative to
:class:`threading.VCondition`\ . It can hold a list of callback
functions which are called when one of the notify methods is called on
the condition. The class supports using the 'with' statement.

>>> from versile.common.util import VCondition
>>> cond = VCondition()
>>> with cond:
...     cond.notify_all()
... 

:class:`VLockable` implements :class:`threading.RLock` locking and is
intended for use as a base class for objects which require the ability
to synchronize on themselves using the 'with' statement.

>>> from versile.common.util import VLockable
>>> class MyClass(VLockable):
...     def __init__(self, start_num):
...         super(MyClass, self).__init__()
...         self._num = start_num
...     def get_and_add(self):
...         with self:
...             result, self._num = self._num, self._num+1
...             return result
... 
>>> obj = MyClass(10)
>>> obj.get_and_add()
10
>>> obj.get_and_add()
11

:class:`VStatus` is a sub-class of :class:`VCondition` which tracks a
set of states and notifies of state changes.

>>> from versile.common.util import VStatus
>>> StatusClass = VStatus.class_with_states('ready', 'waiting')
>>> status = StatusClass(StatusClass.ready)
>>> status.status
0
>>> status.update(status.waiting)
>>> status.status
1
>>> status.wait_status(is_status=status.ready, timeout=0.1)
False

Processors
----------
.. currentmodule:: versile.common.processor

:term:`VOL` links implement a task-oriented infrastructure. As remote
method calls are received from a peer the link protocol handler needs
to queue incoming tasks for execution. As tasks may potentially take a
long time to execute, the (reactor-driven) protocol handler cannot
execute such tasks itself in its own thread. Instead it needs to
dispatch the tasks to be handled by other threads.

:class:`VProcessor` implements a simple framework for queueing tasks
for execution, with a set of workers that pick tasks from a task queue
one at a time. Below is an example that starts a processor, schedules
some calls for execution, and then stops the processor.

>>> import time
>>> from versile.common.processor import VProcessor
>>> proc = VProcessor(workers=5)
>>> def task(msg):
...     print(msg)
... 
>>> def schedule_tasks():
...     for i in xrange(4):
...         time.sleep(0.01)
...         call = proc.queue_call(task, args=['This is task %s' % i])
...     time.sleep(0.1)
... 
>>> schedule_tasks()
This is task 0
This is task 1
This is task 2
This is task 3
>>> proc.stop()

.. note::
   
   Once created the processor will automatically start worker
   thread(s) to handle any scheduled calls. When worker threads have
   been started they will run until the processor is stopped with
   :meth:`VProcessor.stop` or the number of workers is reduced with
   :meth:`VProcessor.set_workers`\ .

Instantiating multiple processors with many workers can potentially
lead to a very large number of threads and potentially exhausting max
number of threads. One alternative mechanism is to use a global
processor for the entire environment.

A class processor can be lazy-created with
:meth:`VProcessor.cls_processor`\ . It can also be used as a fallback
option for a (missing) processor object by calling
:meth:`VProcessor.lazy`\ . Note that the class processor is just a
regular processor, and e.g. needs to be stopped before the program
terminates. Below is an example of using a global class processor.

>>> from versile.common.processor import VProcessor
>>> proc = VProcessor.cls_processor(lazy=True, lazy_workers=3)
>>> proc2 = VProcessor.cls_processor()
>>> proc is proc2
True
>>> proc3 = VProcessor.lazy()
>>> proc3 is proc
True
>>> proc.stop()

When a call is scheduled with :meth:`VProcessor.queue_call` then it
returns a :class:`VProcessorCall` handle to the call. The handler can
be used to wait for a call result, set a callback for a call result,
or cancel a call that has not yet been executed.

>>> from versile.common.processor import VProcessor
>>> proc = VProcessor(workers=5)
>>> def adder(a, b):
...     return a + b
... 
>>> call = proc.queue_call(adder, (13, 5))
>>> call.result()
18
>>> proc.stop()

Pending Call Results
--------------------
.. currentmodule:: versile.common.pending

Single-threaded operations such as the :ref:`lib_reactor` that execute
asynchronous code require a mechanism for a function to return a value
which informs the caller that a result is "not yet ready", while
providing a way to do something with the result when it does become
available.

:class:`VPending` is a class for holding a result of an operation that
may not yet be completed. A result of an operation can be either a
regular result, or a :class:`versile.common.failure.VFailure` which
represents an exception condition (similar to an exception).

.. note::

   :class:`VPending` objects are intended to be used in
   single-threaded environments with asynchronous code such as a
   reactor thread. For threaded environments use
   :class:`versile.common.util.VResult`\ .

A provider of a result can return a :class:`VPending` object as a
handle to the result. Whenever the result is ready, the provider can
call :meth:`VPending.callback` or :meth:`VPending.failback` to
register the result.

A recipient of a result can use :meth:`VPending.add_callpair`\ ,
:meth:`VPending.add_callback`\ , :meth:`VPending.add_failback` or
:meth:`VPending.add_both` to register callback functions to receive a
call result or call failure when it is available. Multiple handler
(pairs) can be registered, each pair receiving the result or failure
of the previous handler pair.

Below is a simple example of a :class:`VPending` in action:

>>> from versile.common.pending import VPending
>>> import threading
>>> import time
>>> def async_func(a, b):
...     result = VPending()
...     def delayed_op():
...         result.callback(a+b)
...     threading.Timer(0.1, delayed_op).start()
...     return result
... 
>>> def print_result(n):
...     print('result: %s' % n)
... 
>>> result = async_func(10, 7)
>>> type(result)
<class 'versile.common.pending.VPending'>
>>> result.add_callback(print_result)
>>> time.sleep(0.2) # Below output is from callback while main thread sleeps
result: 17

There are additional mechanisms that can be used when working with
:class:`VPending`\ , see class method documentation for more details.

Interfaces
----------
.. currentmodule:: versile.common.iface

:class:`VInterface` is a mechanism for describing an interface which
can be implemented by a class, somewhat similar to how 'interfaces'
are used in languages such as Java.

A :class:`VInterface` is primarily a mechanism for documenting
interfaces in a way that it can be documented with standard python
mechanisms and refererred to as a python entity. However, it can also
be formally registered with a class as an interface supported by that
class, and a progran then test whether a class claims to support that
interface.

Below is a simple example which creates an interface definition and
registers the interface with a class using the :func:`implements`
decorator.

>>> from versile.common.iface import *
>>> class AddInterface(VInterface):
...    """Adder which can add two numbers."""
...    def do_add(self, a, b):
...       """Returns a+b."""
... 
>>> @implements(AddInterface)
... class Adder:
...    def do_add(self, a, b):
...       return a + b
... 
>>> adder = Adder()
>>> AddInterface.provided_by(adder)
True
>>> AddInterface.provided_by(Adder)
True

.. note::
   
   A class will inherit the interface definitions registered on a
   parent class, however when inheriting multiple classes which have
   defined interfaces, the decorator :func:`multiface` must be added.

The :mod:`versile.common.iface` module also a set of decorators which
can be used as syntactic sugar. They currently have no other function
than documenting the code, however this could change later.

* :func:`abstract` indicates a method must be defined in derived classes
* :func:`final` indicates a method should not be redefined
* :func:`peer` indicates a method should only be called by certain
  peer objects

Logging
-------
.. currentmodule:: versile.common.log

The module :mod:`versile.common.log` implements a generic logging
framework.

A logger is essentially a dispatcher that connects with log watchers
which perform actions like writing log entries to the console or a
file. A logger can also be used as a watcher and receive messages from
another logger.

* Log messages are written to a :class:`VLogger`\ . The logger
  represents log entries as :class:`VLogEntry` objects.
* The logger uses registered :class:`VLogEntryFilter` filters to
  filter new received log entries.
* Retained entries are passed to registered :class:`VLogWatcher`
  objects.
* Log watchers may use a :class:`VLogEntryFormatter` to format a log
  entry for human reading.

The library includes watcher :class:`VFileLog` and
:class:`VConsoleLog` for writing log entries to a file or the console.

Below is an example which creates a logger and registers a log
message. The example defines a custom log watcher which hides
timestamps, in order to produce deterministic output. Alternatively we
could have used the :class:`VConsoleLog` log watcher.

>>> # Set up a custom logger which does not include timestamp
... from versile.common.log import VLogger, VLogWatcher
>>> logger = VLogger()
>>> class MyLogWatcher(VLogWatcher):
...     def _watch(self, log_entry):
...         print('%s %s: %s'
...               % (log_entry.lvl, log_entry.prefix, log_entry.msg))
... 
>>> logger.add_watcher(MyLogWatcher())
>>> logger.info(u'Done Rendering', prefix=u'MyRenderSW')
20 MyRenderSW: Done Rendering


ASN.1
-----
.. currentmodule:: versile.common.asn1

The module :mod:`versile.common.asn1` contains a framework for working
with :term:`ASN.1` data structures.

The module is not a full implementation, however it includes
sufficient functionality to enable encoding and decoding basic
:term:`X.509` certificates and RSA-key data.

Instances of :class:`VASN1Base` and derived classes hold an
:term:`ASN.1` object, and a :term:`DER` encoded representation can be
generated with :meth:`VASN1Base.encode_der`\ . The following types are
supported.

+------------------+----------------------------------------------------+
| ASN.1 type       | Implemented as                                     |
+==================+====================================================+
| BitString        | :class:`VASN1BitString`                            |
+------------------+----------------------------------------------------+
| Boolean          | :class:`VASN1Boolean`                              |
+------------------+----------------------------------------------------+
| Enumerated       | :class:`VASN1Enumerated`                           |
+------------------+----------------------------------------------------+
| GeneralizedTime  | :class:`VASN1GeneralizedTime`                      |
+------------------+----------------------------------------------------+
| IA5String        | :class:`VASN1IA5String`                            |
+------------------+----------------------------------------------------+
| Integer          | :class:`VASN1Integer`                              |
+------------------+----------------------------------------------------+
| Null             | :class:`VASN1Null`                                 |
+------------------+----------------------------------------------------+
| NumericString    | :class:`VASN1NumericString`                        |
+------------------+----------------------------------------------------+
| OctetString      | :class:`VASN1OctetString`                          |
+------------------+----------------------------------------------------+
| ObjectIdentifier | :class:`VASN1ObjectIdentifier`                     |
+------------------+----------------------------------------------------+
| PrintableString  | :class:`VASN1PrintableString`                      |
+------------------+----------------------------------------------------+
| Set              | :class:`VASN1Set`\ , :class:`VASN1SetOf`           |
+------------------+----------------------------------------------------+
| Sequence         | :class:`VASN1Sequence`\ , :class:`VASN1SequenceOf` |
+------------------+----------------------------------------------------+
| UniversalString  | :class:`VASN1UniversalString`                      |
+------------------+----------------------------------------------------+
| UTCTime          | :class:`VASN1UTCTime`                              |
+------------------+----------------------------------------------------+
| UTF8String       | :class:`VASN1UTF8String`                           |
+------------------+----------------------------------------------------+

Below is a simple example how to create an object and perform
encoding, including a simplified version which uses lazy-construction.

>>> from versile.common.asn1 import *
>>> # Alternative 1: fully specified object structure
... seq = VASN1Sequence()
>>> seq.append(VASN1Integer(4))
>>> seq.append(VASN1UTF8String(u'hello'))
>>> seq.encode_der()
'0\n\x02\x01\x04\x0c\x05hello'
>>> # Alternative 2: lazy-constructed object structure
... seq2 = VASN1Base.lazy((4, u'hello'))
>>> seq2.encode_der()
'0\n\x02\x01\x04\x0c\x05hello'

Instances of :class:`VASN1Tagged` hold an explicitly or implicitly tag
of another :class:`VASN1Base` object. A tag is represented as a
:class:`VASN1Tag`\ . Below is a simple example of working with tags:

>>> from versile.common.asn1 import *
>>> i = VASN1Integer(42)
>>> tag = VASN1Tag(VASN1Tag.APPLICATION, 14)
>>> tagged = VASN1Tagged(i, tag, explicit=True)
>>> tagged
'[ APPLICATION 14 ]' 42
>>> tagged.encode_der()
'n\x03\x02\x01*'

An :term:`ASN.1` type can be defined as a :class:`VASN1Definition`
object, and a defined type can be decoded from :term:`DER` with
:meth:`VASN1Definition.parse_der`\ . The following definition classes
are defined.

+------------------+----------------------------------------------------+
| ASN.1 type       | Implemented as                                     |
+==================+====================================================+
| BitString        | :class:`VASN1DefBitString`                         |
+------------------+----------------------------------------------------+
| Boolean          | :class:`VASN1DefBoolean`                           |
+------------------+----------------------------------------------------+
| Choice           | :class:`VASN1DefChoice`                            |
+------------------+----------------------------------------------------+
| Enumerated       | :class:`VASN1DefEnumerated`                        |
+------------------+----------------------------------------------------+
| GeneralizedTime  | :class:`VASN1DefGeneralizedTime`                   |
+------------------+----------------------------------------------------+
| IA5String        | :class:`VASN1DefIA5String`                         |
+------------------+----------------------------------------------------+
| Integer          | :class:`VASN1DefInteger`                           |
+------------------+----------------------------------------------------+
| Null             | :class:`VASN1DefNull`                              |
+------------------+----------------------------------------------------+
| NumericString    | :class:`VASN1DefNumericString`                     |
+------------------+----------------------------------------------------+
| OctetString      | :class:`VASN1DefOctetString`                       |
+------------------+----------------------------------------------------+
| ObjectIdentifier | :class:`VASN1DefObjectIdentifier`                  |
+------------------+----------------------------------------------------+
| PrintableString  | :class:`VASN1DefPrintableString`                   |
+------------------+----------------------------------------------------+
| Set              | :class:`VASN1DefSet`\ , :class:`VASN1DefSetOf`     |
+------------------+----------------------------------------------------+
| Sequence         | :class:`VASN1DefSequence`\ ,                       |
|                  | :class:`VASN1DefSequenceOf`                        |
+------------------+----------------------------------------------------+
| UniversalString  | :class:`VASN1DefUniversalString`                   |
+------------------+----------------------------------------------------+
| UTCTime          | :class:`VASN1DefUTCTime`                           |
+------------------+----------------------------------------------------+
| UTF8String       | :class:`VASN1DefUTF8String`                        |
+------------------+----------------------------------------------------+
| <tagged value>   | :class:`VASN1DefTagged`                            |
+------------------+----------------------------------------------------+
| <any universal>  | :class:`VASN1DefUniversal`                         |
+------------------+----------------------------------------------------+

Below is a simple code example of using a definition to decode an
object from a :term:`DER` representation.

>>> from versile.common.asn1 import *
>>> _def = VASN1DefInteger()
>>> obj, bytes_parsed = _def.parse_der(b'\x02\x01*')
>>> obj, type(obj)
(42, <class 'versile.common.asn1.VASN1Integer'>)
>>> # Same using universal decoder
... _def = VASN1DefUniversal(allow_unknown=False)
>>> obj, bytes_parsed = _def.parse_der(b'\x02\x01*')
>>> obj, type(obj)
(42, <class 'versile.common.asn1.VASN1Integer'>)

Below is another example which decodes the sequence object encoded in
an earlier example:

>>> from versile.common.asn1 import *
>>> # Using sequence definition for the outer encoding
... _def = VASN1DefSequenceOf(VASN1DefUniversal())
>>> obj, num_parsed = _def.parse_der(b'0\n\x02\x01\x04\x0c\x05hello')
>>> obj, type(obj)
((4, u'hello'), <class 'versile.common.asn1.VASN1SequenceOf'>)
>>> # Alternative decoding using only Universal definition
... _def = VASN1DefUniversal()
>>> obj, num_parsed = _def.parse_der(b'0\n\x02\x01\x04\x0c\x05hello')
>>> obj, type(obj)
((4, u'hello'), <class 'versile.common.asn1.VASN1SequenceOf'>)

Definition classes for sequences and sets have limited support for
definining composite :term:`ASN.1` types. Type definition classes can
be construction in a format which loosely resembles how types are
defined in standard :term:`X.680` notation.

Below is a simple example which defines a type 'MyType'. The use of
:meth:`VASN1Sequence.c_app` for 'create and append' is somewhat
special as it creates an object to append and returns a method for
performing the actual append operation (allowing separation of
create-arguments and append-argument). Also note that sequence
elements and type definition elements must be appended in the correct
sequence.

>>> from versile.common.asn1 import *
>>> # Constructing a composite type
... class MyType(VASN1DefSequence):
...     def __init__(self, name=None):
...         if name is None:
...             name = 'MyType'
...         super(MyType, self).__init__(name=name, explicit=True)
...         # Add a 'name' parameter
...         self.add(VASN1DefUTF8String(), name='name')
...         # Add an optional 'age' parameter
...         self.add(VASN1DefInteger(), name='age', opt=True)
...         # Add an optional 'salutation' parameter tagged with context-tag 0
...         _def = self.ctx_tag_def(0, VASN1DefUTF8String())
...         self.add(_def, name='salutation', opt=True)
... 
>>> # Creating a composite object
... obj = MyType().create()
>>> obj.asn1name, type(obj.asn1def)
('MyType', <class 'MyType'>)
>>> obj.c_app('name', u'John Doe')()
u'John Doe'
>>> obj.c_app('age', 42)()
42
>>> obj.c_app('salutation', u'Dr.')()
'[ 0 ]' u'Dr.'
>>> # Encoding and decoding
... der = obj.encode_der()
>>> der
'0\x14\x0c\x08John Doe\x02\x01*\xa0\x05\x0c\x03Dr.'
>>> MyType().parse_der(der)
((u'John Doe', 42, '[ 0 ]' u'Dr.'), 22)

Debugging
---------
.. currentmodule:: versile.common.debug

The module :mod:`versile.common.debug` includes mechanisms which can
be useful for debugging.

:func:`debug_to_console`\ , :func:`debug_to_file` or
:func:`debug_to_watcher` activates global debug logging for module
debug message logging functions. :func:`disable_debugging` disables
previously configured global debugging.

The following functions can be used to log a debug message (with
associated log levels), :func:`debug`, :func:`info`\ , :func:`warn`\ ,
:func:`error`\ , and :func:`critical`\ .:func:`ldebug` adds
information about what line number in the source file the log entry is
performed. All of these methods can also be used with capitalized
method name, making it easier to spot in code. The functions have no
effect unless global debugging is enabled.

Some other convenience methods:

* :func:`print_trace` prints a stack trace
* :func:`debug_trace` logs a stack trace
* :func:`print_etrace` prints an exception trace
* :func:`debug_etrace` logs an exception trace
* :func:`console` launches an interactive console
* :func:`sigusr1` traps SIGUSR1 to launch an interactive console

Below is a simple example which prints a debug message. For this
example we have set up a custom log watcher which strips timestamp
information in order to produce deterministic output; alternatively we
could have used :func:`debug_to_console` to set up default console
logging. Note that the call to :func:`debug_to_watcher` has a global
effect and should only be called once for the whole program.

>>> from versile.common.debug import *
>>> from versile.common.log import VLogger, VLogWatcher
>>> class MyLogWatcher(VLogWatcher):
...     def _watch(self, log_entry):
...         print('%s %s: %s'
...               % (log_entry.lvl, log_entry.prefix, log_entry.msg))
... 
>>> debug_to_watcher(MyLogWatcher())
>>> DEBUG('no need for \'print\' to debug code')
10 None: no need for 'print' to debug code
>>> # Disable global debugging
... disable_debugging()

Utility Functions
-----------------
.. currentmodule:: versile.common.util 

Below is an overview of additional utility functions not covered above:

* :func:`posint_to_bytes` converts a non-negative integer to a byte
  representation, :func:`bytes_to_posint` performs the inverse operation.
* :func:`signedint_to_bytes` converts a signed integer to a
  (:term:`VP` specific) byte representation,
  :func:`bytes_to_signedint` performs the inverse operation.
* :func:`posint_to_netbytes` converts a non-negative integer to the :term:`VP`   "netbytes" integer representation, :func:`netbytes_to_posint` performs the 
  inverse operation.
* :func:`signedint_to_netbytes` converts a signed integer to a
  netbytes representation, :func:`netbytes_to_signedint` performs the
  inverse operation.
* :func:`encode_pem_block` and :func:`decode_pem_block` convert binary
  data to/from a :term:`PEM` representation.

Module APIs
-----------

ASN.1
.....
Module API for :mod:`versile.common.asn1`

.. automodule:: versile.common.asn1
    :members:
    :show-inheritance:

Failure
.......
Module API for :mod:`versile.common.failure`

.. automodule:: versile.common.failure
    :members:
    :show-inheritance:

Debugging
.........
Module API for :mod:`versile.common.debug`

.. automodule:: versile.common.debug
    :members:
    :show-inheritance:

Interfaces
..........
Module API for :mod:`versile.common.iface`

.. automodule:: versile.common.iface
    :members:
    :show-inheritance:

Logging
.......
Module API for :mod:`versile.common.log`

.. automodule:: versile.common.log
    :members:
    :show-inheritance:

Async Calls
...........
Module API for :mod:`versile.common.pending`

.. automodule:: versile.common.pending
    :members:
    :show-inheritance:

Peer
....
Module API for :mod:`versile.common.peer`

.. automodule:: versile.common.peer
    :members:
    :show-inheritance:

Processor
.........
Module API for :mod:`versile.common.processor`

.. automodule:: versile.common.processor
    :members:
    :show-inheritance:

Utility
.......
Module API for :mod:`versile.common.util`

.. automodule:: versile.common.util
    :members:
    :show-inheritance:
