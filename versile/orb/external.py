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

"""Implementats the :term:`VOB` specification."""
from __future__ import print_function, unicode_literals

import inspect
import textwrap
from threading import RLock
import types

from versile.internal import _vexport, _v_silent
from versile.orb.entity import VObject, VNone, VString, VException
from versile.orb.entity import VEntityError, VCallError

__all__ = ['VExternal', 'doc', 'doc_with', 'meta', 'meta_as', 'publish']
__all__ = _vexport(__all__)


def meta(f):
    """Decorator to make a :class:`VExternal` method an external meta method.

    Example use::

        class MyClass(VExternal):
            @meta
            def my_meta_method(self, *args, **kargs):
                pass

    """
    f.meta = True
    f.meta_name = None
    return f

def meta_as(name):
    """Decorator to make a :class:`VExternal` method an external meta method.

    :param name: external name for the meta method
    :type  name: unicode

    Example use::

        class MyClass(VExternal):
            @meta_as(u'my_meta_method')
            def a_method(self, *args, **kargs):
                pass

    """
    if not isinstance(name, unicode):
        raise TypeError('@meta_as() name argument must be unicode')
    def decor(f):
        f.meta = True
        f.meta_name = name
        return f
    return decor

def doc(c):
    """Decorator to set external class doc string of a :class:`VExternal`\ .

    The decorator will use the python docstring of the class as the
    external string. The docstring must convert to Unicode, otherwise
    the decorator will raise an exception.

    Example use::

        @doc
        class MyClass(VExternal):
            \"\"\"This will get published\"\"\"

    """
    if not issubclass(c, VExternal):
        raise TypeError('@doc can only be applied to VExternal sub-classes')
    try:
        doc = c.__doc__
    except AttributeError:
        doc = None
    try:
        lines = doc.split('\n')
        if lines:
            first = lines[0]
            remaining = '\n'.join(lines[1:])
            if remaining:
                remaining = textwrap.dedent(remaining)
                doc = '\n'.join((first, remaining, ''))
            else:
                doc = first + '\n'
        else:
            doc = ''
    except:
        raise TypeError('was unable to normalize docstring indentation')
    try:
        doc = unicode(doc)
    except:
        raise TypeError('@doc docstring could not be converted to unicode')
    c._v_external_doc = doc
    return c

def doc_with(doc):
    """Decorator to set external class doc string of a :class:`VExternal`\ .

    :param doc: the doc string to use for the function or class
    :type  doc: unicode

    Example use::

        @doc_with(u'This will be the external doc string')
        class MyClass(VExternal):
            \"\"\"This is an internal docstring\"\"\"

    """
    if not isinstance(doc, unicode):
        raise TypeError('@doc_as docstring must be unicode')
    def decor(c):
        if not issubclass(c, VExternal):
            raise TypeError('can only use @doc_with on VExternal sub-classes')
        c._v_external_doc = doc
        return c
    return decor

def publish(name=None, doc=False, show=False, ctx=True):
    """Decorator for publishing a :class:`VExternal` method externally.

    Keyword arguments:

    :param name: if None, the method's internal name is used
    :type  name: unicode
    :param doc:  doc string, True for __doc__, or False for no doc
    :type  doc:  unicode, bool
    :param show: if True then include in methods() list
    :type  show: bool
    :param ctx:  if True then include session as a keyword argument
    :type  ctx:  bool

    If *doc* is a unicode string, then this is used as the
    documentation string. Otherwise, if doc is set to True and the
    method has a *__doc__* docstring set, then that string is used
    (after unicode conversion).

    Example use::

        class MyClass(VExternal):
            @publish(name=u'my_method_a', show=True, doc=True, ctx=False)
            def a_method(self, arg1, arg2):
                \"\"\"This doc string will be published\"\"\"
                pass
            @publish()
            def my_method_b(self, arg1, arg2, ctx=None):
                pass

    """
    # decor() requires copying arguments, otherwise it raises a
    # 'referenced before assignment' on the doc param
    _name, _doc, _ctx, _show = name, doc, ctx, show
    def decor(f):
        f.external = True
        if name:
            f.external_name = _name
        else:
            f.external_name = None

        if isinstance(_doc, unicode):
            f.external_doc = _doc
        elif isinstance(_doc, bool):
            if _doc:
                try:
                    doc = f.__doc__
                except AttributeError:
                    f.external_doc = None
                else:
                    if doc is None:
                        f.external_doc = None
                    else:
                        try:
                            lines = doc.split('\n')
                            if lines:
                                first = lines[0]
                                remaining = '\n'.join(lines[1:])
                                if remaining:
                                    remaining = textwrap.dedent(remaining)
                                    doc = '\n'.join((first, remaining, ''))
                                else:
                                    doc = first + '\n'
                            else:
                                doc = ''
                        except:
                            raise TypeError('unable to normalize docstring')
                        try:
                            doc = unicode(doc)
                        except Exception:
                            raise TypeError('cannot convert doc to unicode')
                        else:
                            f.external_doc = doc
            else:
                f.external_doc = None
        else:
            raise TypeError('Invalid use of @publish doc argument')

        if isinstance(_ctx, bool):
            f.external_noctx = not _ctx
        else:
            raise TypeError('Invalid use of @publish ctx argument')

        if isinstance(_show, bool):
            f.external_show = _show
        else:
            raise TypeError('Invalid use of @publish show argument')

        return f
    return decor


class VExternal(VObject):
    """A developer-friendly base class for remotely referencable objects.

    :class:`VExternal` offers convenient mechanisms for publishing
    python methods as external methods. It implements the :term:`VOB`
    specification for remote call conventions and remote object
    inspection.

    See :ref:`lib_external` for more information about how the class
    can be used.

    .. note::

        During construction the class inspects all attributes set on
        the object to identify published methods. This causes the
        constructor to resolve all attributes, which will also try to
        access any properties that are defined on the
        class. Exceptions raised while trying to access properties are
        ignored, however the class must make sure it is set up so that
        the constructor's attempts to access any @property does not
        trigger any error condition or deadlock.

    .. automethod:: _v_execute
    .. automethod:: _v_publish
    .. automethod:: _v_unpublish
    .. automethod:: _v_unpublish_by_name

    """

    def __init__(self, processor=None):
        super(VExternal, self).__init__(processor=processor)

        self.__methods = dict()         # external name -> method_data
        self.__method_names = dict()    # method_func -> external name
        self.__methods_lock = RLock()

        self.__meta = dict()            # meta name -> meta_data
        self.__meta_names = dict()      # method_func -> meta name

        for _attr_name in dir(self):
            try:
                method = getattr(self, _attr_name)
            except Exception as e:
                _v_silent(e)
                continue
            if not isinstance(method, types.MethodType):
                continue
            if hasattr(method, 'external') and method.external:
                method_func, instance_method = self._v_unwind_method(method)
                try:
                    doc = method.external_doc
                except AttributeError:
                    doc = None
                try:
                    ctx = not method.external_noctx
                except AttributeError:
                    ctx = True
                try:
                    show = method.external_show
                except AttributeError:
                    show = False
                method_data = _VMethodData(method_func, instance_method,
                                           doc, ctx, show)

                name = method.external_name
                if name is None:
                    name = unicode(method.__name__)
                self.__methods[name] = method_data
                self.__method_names[method_func] = name

            if hasattr(method, 'meta') and method.meta:
                name = method.meta_name
                if name is None:
                    name = unicode(method.__name__)
                method_func, instance_method = self._v_unwind_method(method)
                meta_data = _VMetaData(method_func, instance_method)
                self.__meta[name] = meta_data
                self.__meta_names[method_func] = name

    def _v_execute(self, *args, **kargs):
        """Executes remote method calls.

        :class:`VExternal` overrides the method for its internal use,
        and derived classes should not re-implement this
        method. Instead, derived classes should use the
        :class:`VExternal` method publishing mechanisms to create
        external methods.

        """
        if not args:
            raise VCallError('No method name or meta-call information.')
        m_name, args = args[0], args[1:]
        if isinstance(m_name, (type(None), VNone)):
            regular_call = False
            if not args:
                raise VCallError('Incomplete meta-call information.')
            m_name, args = args[0], args[1:]
        else:
            regular_call = True
        if m_name is None or not isinstance(m_name, (unicode, VString)):
            raise VCallError('Missing or invalid method name parameter')

        if regular_call:
            with self.__methods_lock:
                method_data = self.__methods.get(m_name, None)
            if not method_data:
                raise VCallError('Not a published external method')
            if not method_data.ctx:
                kargs.pop('ctx', None)
            func = method_data.method_func
            if method_data.instance_method:
                method = lambda *arg, **karg: func(self, *arg, **karg)
            else:
                _cls = self.__class__
                method = lambda *arg, **karg: func(_cls, *arg, **karg)
            # This may raise an exception which is propagated out
            return method(*args, **kargs)
        else:
            with self.__methods_lock:
                meta_data = self.__meta.get(m_name, None)
            if meta_data:
                func = meta_data.method_func
                if meta_data.instance_method:
                    method = lambda *arg, **karg: func(self, *arg, **karg)
                else:
                    _cls = self.__class__
                    method = lambda *arg, **karg: func(_cls, *arg, **karg)
                # This may raise an exception which is propagated out
                return method(*args, **kargs)
            else:
                raise VCallError('Not a provided meta method')

    def _v_publish(self, method, name=None, doc=False, ctx=True, show=False):
        """Publishes a method, making it externally callable.

        :param method: the method to publish
        :type  method: callable
        :raises:       :exc:`versile.orb.error.VEntityError`

        The other arguments are similar to the @\ :func:`publish`\
        . The method raises an exception if another method is already
        published under the same name.

        """
        with self.__methods_lock:
            if name is None:
                name = unicode(method.__name__)
            if name in self.__methods:
                raise VEntityError('Another method published with same name')
            method_func, instance_method = self._v_unwind_method(method)
            if isinstance(doc, unicode):
                doc = _doc
            elif isinstance(doc, bool):
                if doc:
                    try:
                        doc = method.__doc__
                    except AttributeError:
                        doc = None
                    else:
                        try:
                            doc = unicode(doc)
                        except Exception:
                            raise TypeError('cannot convert doc to unicode')
                        else:
                            doc = doc
                else:
                    doc = None
            else:
                raise TypeError('Invalid use of @publish doc argument')
            ctx = bool(ctx)
            show = bool(show)
            method_data = _VMethodData(method_func, instance_method,
                                       doc, ctx, show)
            self.__methods[name] = method_data
            self.__method_names[method_func] = name

    def _v_unpublish(self, method):
        """Unpublishes a method, making it no longer externally callable.

        :param method: the method to publish
        :type  method: callable

        """
        with self.__methods_lock:
            name = self.__method_names.pop(method.im_func, None)
            if name is not None:
                self.__methods.pop(name, None)

    def _v_unpublish_by_name(self, name):
        """Unpublishes a method, making it no longer externally available

        :param name: currently registered external name of the method
        :type  name: unicode

        If a method is registered as an external method with the
        provided name, it gets unpublished.

        """
        with self.__methods_lock:
            method_data = self.__methods.pop(name, None)
            if method_data:
                self.__method_names.pop(method_data.method_func, None)

    @meta_as('doc')
    def _v_doc(self, *args, **kargs):
        with self.__methods_lock:
            if not args:
                try:
                    doc = self._v_external_doc
                except AttributeError:
                    return None
                else:
                    return doc
            elif len(args) == 1:
                method_name = args[0]
                if not isinstance(method_name, (unicode, VString)):
                    raise VCallError('Method argument must be a VString')
                method_data = self.__methods.get(method_name, None)
                if method_data:
                    return method_data.doc
                else:
                    raise VException('Not an exposed method')
            else:
                raise VCallError('Invalid doc meta call format')

    @meta_as('methods')
    def _v_methods(self, **kargs):
        with self.__methods_lock:
            result = []
            for name, method_data in self.__methods.items():
                if method_data.show:
                    result.append(name)
            result.sort()
            return tuple(result)

    def _v_unwind_method(self, method):
        """Internal call to unwind the parameters of a method.

        :param method: instance method of 'cls'
        :type  method: callable
        :returns:      (function, is_instance_call)
        :raises:       :exc:`exceptions.RuntimeError`

        """
        if not inspect.ismethod(method):
            raise RuntimeError('Not a method')
        if method.im_self is self:
            is_instance_call = True
        elif method.im_self is self.__class__:
            is_instance_call = False
        else:
            raise RuntimeError('Not instance or class method of this object')
        return method.im_func, is_instance_call


class _VMethodData:
    def __init__(self, method_func, instance_method, doc, ctx, show):
        self.method_func = method_func
        self.instance_method = instance_method
        self.doc = doc
        self.ctx = ctx
        self.show = show


class _VMetaData:
    def __init__(self, method_func, instance_method):
        self.method_func = method_func
        self.instance_method = instance_method
