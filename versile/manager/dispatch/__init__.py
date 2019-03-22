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

"""Service dispatching."""
from __future__ import print_function, unicode_literals

import collections
import imp
import inspect

from versile.internal import _vexport, _val2b, _pyver
from versile.common.util import VLockable
from versile.orb.entity import VTuple, VString, VCallError
from versile.orb.external import VExternal, publish
from versile.orb.validate import vchk, vtyp

__all__ = ['VDispatcher', 'VDispatchService', 'VDispatchGwFactory',
           'VLoader', 'VDispatchException']
__all__ = _vexport(__all__)


class VDispatchException(Exception):
    """Dispatcher operation exception"""


class VDispatchService(VLockable):
    """Service interface which can be dispatched with a :class:`VDispatcher`

    :param sname: service name
    :type  sname: unicode
    :param auth:  service authorizer (or None)
    :type  auth:  :class:`versile.crypto.auth.VAuth`

    """

    def __init__(self, sname, auth=None):
        super(VDispatchService, self).__init__()
        self._name = sname
        self._auth = auth
        self._paths = dict()     # path_comp -> dict or gw_factory
        self._locked = False

    def add(self, path, gw_factory):
        """Add a VRI path resolved by this service.

        :param path:       URL path or sub-path
        :type  path:       (unicode,)
        :param gw_factory: factory for URL gateway object
        :type  gw_factory: :class:`VDispatchGwFactory`
        :raises:           :exc:`VDispatchException`

        Paths are relative to the top level of any service dispatcher
        the service is registered with.

        An exception is raised if the service object has been locked
        earlied by a dispatcher which registered the service.

        """
        with self:
            if self._locked:
                raise VDispatchException('Object is locked')
            _path_dict_add(gw_factory, path, self._paths)

    def remove(self, path):
        """Removes a VRI path resolved by this service.

        :param path:       URL path or sub-path
        :type  path:       (unicode,)
        :raises:           :exc:`VDispatchException`

        An exception is raised if the service object has been locked
        earlied by a dispatcher which registered the service.

        """
        with self:
            if self._locked:
                raise VDispatchException('Object is locked')
            _path_dict_remove(path, self._paths)

    @property
    def name(self):
        """Service name associated with the dispatched service (unicode)."""
        return self._name

    @property
    def auth(self):
        """Authorizer associated with the dispatched service (unicode)."""
        return self._auth

    def _lock(self):
        """Prevents modifications. Set by dispatcher when activated."""
        with self:
            self._locked = True


class VDispatcher(VExternal):
    """Dispatches resolution of URLs to service handlers.

    By using a dispatcher as the main gateway entry point for a
    listening service, multiple services can be served from the same
    listening service and port number.

    """

    def __init__(self):
        super(VDispatcher, self).__init__()
        self._services = dict()      # sname -> VDispatchService
        self._dispatchers = dict()   # VDispatcher -> set(path)
        self._paths = dict()         # path_comp -> dict _or_ VDispatchService
                                     #              _or_ VDispatcher
    @publish(show=True, ctx=True)
    def urlget(self, path, ctx=None):
        """Resolve a service URL.

        This method implements the :term:`VRI` standard for remote
        method access to URI resources.

        """
        # Check path has correct type
        vchk(path, vtyp(tuple, VTuple))
        if _pyver == 2:
            _styp = unicode
        else:
            _styp = str
        for p in path:
            vchk(p, vtyp(_styp, VString))

        # Resolve path
        with self:
            parsed = _path_dict_parse(path, self._paths)
        if parsed is None:
            raise VCallError('VRI does not resolve')
        node, residual_path = parsed

        if residual_path:
            if not isinstance(node, VDispatcher):
                raise VCallError('VRI does not resolve')
            return node.urlget(path=residual_path, ctx=ctx)
        else:
            if not isinstance(node, tuple) or len(node) != 2:
                raise VCallError('VRI does not resolve')
            _service, _gw = node
            _auth = _service.auth
            if _auth:
                _key, _cert = ctx.credentials
                _claimed = ctx.claimed_identity
                try:
                    allowed = _auth.accept_host(ctx.network_peer)
                    if allowed:
                        allowed = _auth.accept_credentials(_key, _claimed,
                                                           _cert)
                except:
                    raise VCallError('Not authorized')
                else:
                    if not allowed:
                        raise VCallError('Not authorized')
            if not isinstance(_gw, VDispatchGwFactory):
                raise VCallError('VRI does not resolve')
            return _gw.build(ctx=ctx)

    def add_service(self, service):
        """Registers a service with the dispatcher.

        :param service: dispatched service to add
        :type  service: :class:`VDispatchService`
        :raises:        :exc:`VDispatchException`

        Raises an exception if another service is already registered
        with the same service name, or if there is a patch conflict.

        """
        with self:
            with service:
                # Check name not already registered
                if service.name in self._services:
                    raise VDispatchException('Name already registered')

                # Check no path conflicts
                _service_paths = _path_dict_to_list(service._paths)
                for p in _service_paths:
                    if _path_dict_has_subpath(p, self._paths):
                        raise VDispatchException('Path conflict: %s' % p)

                # Lock the service to prevent path changes on service object
                service._lock()

            # Add the service
            self._services[service.name] = service
            for p in _service_paths:
                gw = _path_dict_parse(p, service._paths)[0]
                _path_dict_add((service, gw), p, self._paths)

    def add_dispatcher(self, dispatcher, path):
        """Registers a dispatcher for a path node

        :param dispatcher: dispatcher to add
        :type  dispatcher: :class:`VDispatcher`
        :param path:       path to apply dispatcher
        :type  path:       (unicode,)
        :raises:           :exc:`VDispatchException`

        Raises an exception if there is a path conflict.

        """
        with self:
            # Check dispatcher not already registered on same path
            disp_entry = self._dispatchers.get(dispatcher, None)
            if disp_entry and path in disp_entry:
                raise VDispatchException('Already registered on same path')

            # Check no path conflict
            if _path_dict_has_subpath(path, self._paths):
                raise VDispatchException('Path conflict: %s' % p)

            # Add the dispatcher
            if not disp_entry:
                disp_entry = set()
                self._dispatchers[dispatcher] = disp_entry
            disp_entry.add(path)
            _path_dict_add(dispatcher, path, self._paths)

    def remove_service(self, sname):
        """Unregisters a service from dispatched URLs

        :param sname: name of the service to remove
        :type  sname: unicode
        :raises:      :exc:`VDispatchException`

        Raises an exception if no service is registered with the
        provided name.

        """
        with self:
            service = self._services.pop(sname, None)
            if service is None:
                raise VDispatchException('No such service')

            _service_paths = _path_dict_to_list(service._paths)
            for p in _service_paths:
                _path_dict_remove(p, self._paths)

    def remove_dispatcher(self, path):
        """Unregisters a dispatcher from the provided path

        :param path:       path to remove dispatcher
        :type  path:       (unicode,)

        Raises an exception if no dispatcher is associated with path.

        """
        with self:
            for disp, paths in self._dispatchers.items():
                if path in paths:
                    break
            else:
                raise VDispatchException('No dispatcher set for path')

            paths.discard(path)
            if not paths:
                self._dispatchers.pop(disp, None)

    @property
    def services(self):
        """Currently dispatched services ((:class:`VDispatchService`\ ,))"""
        return self._services.values()


class VDispatchGwFactory(object):
    """Factory for gateways of a dispatched service.

    :param func: function constructing a gateway object
    :type  func: callable

    This class is primarily intended as an abstract class to be
    sub-classed for creating factories for service gateway objects.

    Passing *func* is a convenience mechanism for setting up a factory
    without sub-classing.

    :meth:`build` uses the :mod:`inspect` to check what types of
    arguments *func* takes. If it takes no arguments or it only takes
    one argument 'self' or 'cls' then it is used for constructing
    gateway objects as ``func()``\ , otherwise it is called as
    ``func(ctx=ctx)``\ .

    """

    def __init__(self, func=None):
        self._func = func

    def build(self, ctx):
        """Creates and returns a gateway object

        :returns: gateway object
        :rtype:   :class:`versile.orb.entity.VObject`

        """
        if self._func:
            spec = inspect.getargspec(self._func)
            if spec.args and not (len(spec.args) == 1
                                  and (spec.args[0] == 'self'
                                       or spec.args[1] == 'cls')):
                return self._func(ctx=ctx)
            elif spec.varargs or spec.keywords or spec.defaults:
                return self._func(ctx=ctx)
            else:
                return self._func()
        else:
            raise NotImplementedError()


class VLoader(object):
    """Load a dispatch service or a dispatcher.

    :param builtins: if True add builtins to loader :attr:`namespace`
    :type  builtins: bool

    .. automethod:: __getattr__

    """

    def __init__(self, builtins=True):
        self.__namespace = dict()
        if builtins:
            _b_str = _vexport(['__builtins__'])[0]
            self.__namespace[_b_str] = globals()[_b_str]

    @classmethod
    def load(cls, modname, path):
        """Loads a module from the provided path.

        :param modname: a python module name
        :type  modname: str
        :param path:    module search path
        :type  path:    [str,]
        :returns:       loaded module
        :rtype:         module
        :raises:        `exceptions.ImportError`

        Uses :func:`imp.find_module` and :func:`load_module` to load
        the module. The method supports *modname* module names with
        packages separated by '.' and recursively traverses *path* to
        try to import such modules.

        """
        names = modname.split('.')
        name = names[0]

        for p in path:
            try:
                _file, pathname, desc = imp.find_module(name, [p])
            except ImportError as e:
                continue

            try:
                mod = imp.load_module(name, _file, pathname, desc)
            except Exception as e:
                continue
            finally:
                if _file:
                    _file.close()

            if len(names) > 1:
                try:
                    mod = cls.load('.'.join(names[1:]), mod.__path__)
                except ImportError as e:
                    continue
            return mod
        else:
            raise ImportError('Could not load the module')

    def run_script(self, script):
        """Executes a script in the loader's namespace.

        :param script: python script to execute
        :type  script: str

        """
        code = compile(script, '<string>', 'exec')
        exec code in self.namespace

    @property
    def namespace(self):
        """Namespace used for executing :meth:`load` (dict)."""
        return self.__namespace

    def __getattr__(self, attr):
        """Overloads to retreive attributes from :attr:`namespace`"""
        try:
            return self.namespace[attr]
        except:
            raise AttributeError()


# Module-internal path parsing functions

def _path_dict_parse(path, path_dict):
    """Parses a path in a path dictionary.

    :param path     : path to parse
    :type  path     : (unicode,)
    :param path_dict: a dict -> (dict or obj) structure
    :type  path_dict: :class:`dict`
    :returns:         (obj, residual_path) if match, or None
    :rtype:           (object, (unicode,))

    Returns None *path* does not resolve fully or partly do a sub-node
    of *path_dict*.

    """
    val = path_dict
    for i in xrange(len(path)):
       p = path[i]
       if p in path_dict:
           val = path_dict[p]
           if not isinstance(val, dict):
               break
           path_dict = val
       else:
           break

    if isinstance(val, dict):
        return None
    else:
        return (val, path[(i+1):])

def _path_dict_to_list(path_dict):
    result = []
    _stack = collections.deque([(tuple(), path_dict)])
    while _stack:
        top, _dict = _stack.popleft()
        for key, val in _dict.items():
            if isinstance(val, dict):
                _stack.append(((top + (key,)), val))
            else:
                result.append(top + (key,))
    return result

def _path_dict_has_full_path(path, path_dict):
    parsed = _path_dict_parse(path, path_dict)
    return (parsed is not None and not parsed[1])

def _path_dict_has_subpath(path, path_dict):
    parsed = _path_dict_parse(path, path_dict)
    return (parsed is not None)

def _path_dict_add(obj, path, path_dict):
    """Adds a path object to a path dictionary."""
    for p in path[:-1]:
        if p not in path_dict:
            path_dict[p] = dict()
        _d = path_dict[p]
        if not isinstance(_d, dict):
            raise VDispatchException('Path conflict')
        path_dict = _d
    if path[-1] in path_dict:
        raise VDispatchException('Path conflict')
    path_dict[path[-1]] = obj

def _path_dict_remove(path, path_dict):
    """Adds a path object to a path dictionary."""

    # Remove end node
    _followed = collections.deque()
    for p in path[:-1]:
        if p not in path_dict:
            raise VDispatchException('Invalid path')
        _d = path_dict[p]
        if not isinstance(path_dict, dict):
            raise VDispatchException('Invalid path')
        _followed.appendleft((path_dict, p, _d))
        path_dict = _d
    path_dict.pop(path[-1], None)

    # Traverse back up and remove any dead sub-trees
    for parent, name, child in _followed:
        _stack = collections.deque(child.values())
        while _stack:
            item = _stack.popleft()
            if isinstance(item, dict):
                for _item in item.values():
                    _stack.append(_item)
            else:
                return
        else:
            parent.pop(name, None)
