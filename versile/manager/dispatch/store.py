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

"""Dispatcher and dispatch service definition store."""
from __future__ import print_function, unicode_literals

import os
import sqlite3

from versile.internal import _vexport, _val2b
from versile.common.iface import abstract
from versile.common.util import VLockable
from versile.manager.dispatch import VDispatchService, VDispatcher, VLoader
from versile.manager.dispatch import VDispatchException

__all__ = ['VDispatchStore', 'VDispatchStoreService',
           'VDispatchStoreDispatcher', 'VDispatchStoreRecord']
__all__ = _vexport(__all__)


@abstract
class VDispatchStoreRecord(object):
    """Base class for dispatch service and dispatcher definitions.

    :param autostart: if True should be automatically started
    :type  autostart: bool

    Abstract class, should not be directly instantiated.

    """
    def __init__(self, autostart):
        self._autostart = autostart
        self._loaders = []

    def add_loader(self, load_mod, load_path, load_as=None):
        """Adds a module loader.

        :param load_mod:  name of module to load
        :type  load_mod:  str
        :param load_path: paths to search for module
        :type  load_path: (str,)
        :param load_as:   name to load module as (or None)
        :type  load_as:   str

        Module name *load_mod* can be a '.' separated package reference.

        If *load_as* is None then the module name of load_mod is used.

        """
        self._loaders.append((load_mod, load_path, load_as))

    @property
    def autostart(self):
        """If True should be automatically started by a dispatcher (bool)."""
        return self._autostart

    @property
    def loaders(self):
        """Loader data set on object ((load_mod, load_path, load_as),)."""
        return tuple(self._loaders)


class VDispatchStoreService(VDispatchStoreRecord):
    """Dispatcher service definition which can be persisted in a store.

    :param name:      service name
    :type  name:      unicode
    :param autostart: if True should be automatically started
    :type  autostart: bool

    """

    def __init__(self, name, autostart=False):
        _s_init = super(VDispatchStoreService, self).__init__
        _s_init(autostart)
        self._name = name
        self._paths = []

    def add_path(self, path, script, script_result):
        """Adds a VRI path to be resolved by this service.

        :param path:          VRI (sub)path to resolve
        :type  path:          (unicode,)
        :param script:        script which generates a gateway factory
        :type  script:        str
        :param script_result: name of variable which holds script output
        :type  script_result: str

        When executed with :func:`compile` and :func:`exec` in a
        namespace which builtins symbols and includes loaded modules,
        *script* should generate a variable with name *script_result*
        in the namespace which is a
        :class:`versile.manager.dispatch.VDispatcherGwFactory` that
        generates gateway objects for this :term:`VRI` path.

        """
        self._paths.append((path, script, script_result))

    def load(self):
        """Loads a dispatch service from this dispatch service definition.

        :returns: loaded dispatch service
        :rtype:   :class:`versile.manager.dispatch.VDispatchService`

        Loads a service by loading all module loaders set on the
        object, for each :term: VRI` path executing the script
        generating a gateway factory for that path, and assembling a
        dispatch service object.

        """
        d_service = VDispatchService(self.name)

        loader = VLoader()
        for load_mod, load_path, load_as in self.loaders:
            if load_as is None:
                if '.' in load_mod:
                    load_as = load_mod.split('.')[-1]
                else:
                    load_as = load_mod
            mod = loader.load(load_mod, [load_path])
            loader.namespace[load_as] = mod

        for path, script, script_as in self.paths:
            loader.run_script(script)
            gw_factory = getattr(loader, script_as)
            d_service.add(path, gw_factory)

        return d_service

    @property
    def name(self):
        """Holds the name of the service (unicode)."""
        return self._name

    @property
    def paths(self):
        """Holds the paths resolved by the service ((unicode,),)."""
        return tuple(self._paths)


class VDispatchStoreDispatcher(VDispatchStoreRecord):
    """Dispatcher definition which can be persisted in a store.

    :param path:          :term:`VRI` path resolved by dispatcher
    :type  path:          (unicode,)
    :param script:        script which generates the dispatcher
    :type  script:        str
    :param script_result: name of variable which holds script output
    :type  script_result: str
    :param autostart:     if True should be automatically started
    :type  autostart:     bool

    """

    def __init__(self, path, script, script_result, autostart=False):
        _s_init = super(VDispatchStoreDispatcher, self).__init__
        _s_init(autostart)
        self._path = path
        self._script = script
        self._script_result = script_result

    def load(self):
        """Loads a dispatcher from this dispatcher definition.

        :returns: loaded dispatcher
        :rtype:   :class:`versile.manager.dispatch.VDispatcher`

        Similar to :meth:`VDispatchStoreService.load` except it loads
        a dispatcher.

        """
        loader = VLoader()
        for load_mod, load_path, load_as in self.loaders:
            if load_as is None:
                if '.' in load_mod:
                    load_as = load_mod.split('.')[-1]
                else:
                    load_as = load_mod
            mod = loader.load(load_mod, [load_path])
            loader.namespace[load_as] = mod

        loader.run_script(self.script)
        _dispatcher = getattr(loader, self.script_result)
        if not isinstance(_dispatcher, VDispatcher):
            raise VDispatchException('Not a dispatcher')
        return (self.path, _dispatcher)

    @property
    def path(self):
        """The :term:`VRI` path handled by the dispatcher (unicode,)."""
        return self._path

    @property
    def script(self):
        """Script which generates dispatcher for this definition (str)."""
        return self._script

    @property
    def script_result(self):
        """Name of the output of :attr:`script` in its namespace (str)."""
        return self._script_result


class VDispatchStore(VLockable):
    """A :mod:`sqlite3` based store for dispatcher and service definitions.

    :param filename: filename of store
    :type  filename: str
    :raises:         :exc:`exceptions.IOError`

    The store can be used for persisting definitions of :term:`VRI`
    path services and sub-path dispatchers which should be resolved by
    a :class:`versile.manager.dispatch.VDispatcher`\ . This is useful
    e.g. for initializing a dispatcher for a service which is
    automatically started by a booting system.

    """

    def __init__(self, filename):
        super(VDispatchStore, self).__init__()
        if not os.path.exists(filename):
            raise IOError('No such file')
        self._conn = sqlite3.connect(filename, check_same_thread=False)

    def add_service(self, service):
        """Adds a dispatch service definition to the store.

        :param service: service definition to add
        :type  service: :class:`VDispatchStoreService`
        :raises:        :exc:`versile.manager.dispatch.VDispatchException`

        Raises an exception if another service definition with the
        same name is already registered.

        """
        with self:
            c = self._conn.cursor()

            # Check service name does not already exist
            c.execute('select _id from services where name = ?',
                      (service.name,))
            if list(c):
                raise VDispatchException('Name already registered')

            # Insert service entry
            c.execute('insert into services values(null, ?, ?)',
                      (service.name,
                       int(service.autostart)
                       ))
            self._conn.commit()
            c.execute('select last_insert_rowid()')
            service_id = list(c)[0][0]

            # Add paths
            for _path, script, script_result in service.paths:
                _path = self._merge_path(_path)
                c.execute('insert into s_paths values(null, ?, ?, ?, ?)',
                          (service_id,
                           _path,
                           script,
                           script_result
                           ))

            # Add loaders
            for name, path, load_as in service.loaders:
                c.execute('insert into s_loaders values(null, ?, ?, ?, ?)',
                          (service_id,
                           name,
                           path,
                           load_as
                           ))

    def add_dispatcher(self, dispatcher):
        """Adds a dispatcher definition to the store.

        :param dispatcher: dispatcher definition to add
        :type  dispatcher: :class:`VDispatchStoreDispatcher`
        :raises:           :exc:`versile.manager.dispatch.VDispatchException`

        Raises an exception if another dispatcher definition with the
        same path is already registered.

        """
        with self:
            c = self._conn.cursor()

            # Check path does not already exist
            _path = self._merge_path(dispatcher.path)
            c.execute('select _id from dispatchers where path = ?', (_path,))
            if list(c):
                raise VDispatchException('Path already registered')

            # Insert dispatcher entry
            c.execute('insert into dispatchers values(null, ?, ?, ?, ?)',
                      (_path,
                       dispatcher.script,
                       dispatcher.script_result,
                       int(service.autostart)
                       ))
            self._conn.commit()
            c.execute('select last_insert_rowid()')
            dispatcher_id = list(c)[0][0]

            # Add loaders
            for name, path, load_as in dispatchers.loaders:
                c.execute('insert into d_loaders values(null, ?, ?, ?, ?)',
                          (dispatcher_id,
                           name,
                           path,
                           load_as
                           ))

    def get_service(self, name):
        """Returns a service definition registered for the provided name.

        :param name: service name
        :type  name: unicode
        :returns:    registered service definition
        :rtype:      :class:`VDispatchStoreService`
        :raises:     :exc:`versile.manager.dispatch.VDispatchException`

        Raises an exception if no service registered with provided name.

        """
        with self:
            c = self._conn.cursor()
            c.execute('select _id, name, autostart '
                      + 'from services where name = ?', (name,))
            _matches = list(c)
            if not _matches:
                raise VDispatchException('Name not registered')
            _id, name, autostart = _matches[0]
            service = VDispatchStoreService(name, autostart)

            c.execute('select name, script, script_result '
                      + 'from s_paths where services_id = ?', (_id,))
            for pathname, script, script_result in iter(c):
                _path = self._unmerge_path(pathname)
                service.add_path(_path, script, script_result)

            c.execute('select load_mod, load_path, load_as '
                      + 'from s_loaders where services_id = ?', (_id,))
            for load_mod, load_path, load_as in iter(c):
                service.add_loader(load_mod, load_path, load_as)

            return service

    def get_dispatcher(self, path):
        """Returns a dispatcher definition registered for the provided name.

        :param path: dispatcher :term:`VRI` path
        :type  path: (unicode,)
        :returns:    registered dispatcher definition
        :rtype:      :class:`VDispatchStoreDispatcher`
        :raises:     :exc:`versile.manager.dispatch.VDispatchException`

        Raises an exception if no dispatcher registered with provided path.

        """
        with self:
            _path = self._unmerge_path(path)
            c = self._conn.cursor()
            c.execute('select _id, script, script_result, autostart '
                      + 'from dispatchers where path = ?', (_path,))
            _matches = list(c)
            if not _matches:
                raise VDispatchException('Path not registered')
            _id, script, script_result, autostart = _matches[0]
            dispatcher = VDispatchStoreDispatcher(path, script,
                                                  script_result, autostart)

            c.execute('select load_mod, load_path, load_as '
                      + 'from d_loaders where dispatcher_id = ?', (_id,))
            for load_mod, load_path, load_as in iter(c):
                dispatcher.add_loader(load_mod, load_path, load_as)

            return dispatcher

    def set_service_autostart(self, name, state):
        """Sets the autostart property of a defined service.

        :param state: target autostart state
        :type  state: bool
        :param name:  service name
        :type  name:  unicode
        :raises:      :exc:`versile.manager.dispatch.VDispatchException`

        Raises an exception if no service registered with provided name.

        """
        with self:
            c = self._conn.cursor()
            c.execute('select _id from services where name = ?', (name,))
            _matches = list(c)
            if not _matches:
                raise VDispatchException('Name not registered')
            _id = _matches[0][0]
            c.execute('update services set autostart = ? where _id = ?',
                      (int(state), _id,))
            self._conn.commit()

    def set_dispatcher_autostart(self, path, state):
        """Sets the autostart property of a defined dispatcher.

        :param state: target autostart state
        :type  state: bool
        :param path:  dispatcher path
        :type  path:  (unicode,)
        :raises:      :exc:`versile.manager.dispatch.VDispatchException`

        Raises an exception if no dispatcher registered with provided path.

        """
        with self:
            c = self._conn.cursor()
            _path = self._unmerge_path(path)
            c.execute('select _id from dispatchers where path = ?', (_path,))
            _matches = list(c)
            if not _matches:
                raise VDispatchException('Path not registered')
            _id = _matches[0][0]
            c.execute('update dispatchers set autostart = ? where _id = ?',
                      (int(state), _id,))
            self._conn.commit()

    def remove_service(self, name):
        """Removes a service definition.

        :param name:  service name
        :type  name:  unicode
        :raises:      :exc:`versile.manager.dispatch.VDispatchException`

        Raises an exception if no service registered with provided name.

        """
        with self:
            c = self._conn.cursor()
            c.execute('select _id from services where name = ?', (name,))
            _matches = list(c)
            if not _matches:
                raise VDispatchException('Name not registered')
            _id = _matches[0][0]
            c.execute('delete from services where _id = ?',(_id,))
            c.execute('delete from s_paths where services_id = ?',(_id,))
            c.execute('delete from s_loaders where services_id = ?',(_id,))
            self._conn.commit()

    def remove_dispatcher(self, path):
        """Removes a dispatcher definition.

        :param path:  dispatcher path
        :type  path:  (unicode,)
        :raises:      :exc:`versile.manager.dispatch.VDispatchException`

        Raises an exception if no dispatcher registered with provided path.

        """
        with self:
            c = self._conn.cursor()
            _path = self._unmerge_path(path)
            c.execute('select _id from dispatchers where path = ?', (_path,))
            _matches = list(c)
            if not _matches:
                raise VDispatchException('Path not registered')
            _id = _matches[0][0]
            c.execute('delete from dispatchers where _id = ?',(_id,))
            c.execute('delete from d_loaders where services_id = ?',(_id,))
            self._conn.commit()

    def load(self):
        """Loads all autostarting dispatched services and dispatchers.

        :returns: dispatcher with loaded service
        :rtype:   :class:`versile.manager.dispatch.VDispatcher`

        Performs :meth:`VDispatchStoreService.load` on all service
        definitions and :meth:`VDispatchStoreDispatcher.load` on all
        dispatcher definitions which have the *autostart* property set
        to True. The resulting services and sub-path dispatchers are
        assembled and returned as a
        :class:`versile.manager.dispatch.VDispatcher` dispatcher
        object.

        """
        dispatcher = VDispatcher()

        for name in self.service_names:
            service = self.get_service(name)
            if not service.autostart:
                continue
            d_service = service.load()
            dispatcher.add_service(d_service)

        for path in self.dispatcher_paths:
            _disp = self.get_dispatcher(path)
            if not _disp.autostart:
                continue
            d_service = _disp.load()
            dispatcher.add_dispatcher(_disp)

        return dispatcher

    @classmethod
    def create(cls, filename):
        """Creates a new :mod:`sqlite3` dispatcher store database file.

        :param filename:  filename of the store
        :type  filename:  str
        :returns:         dispatch store
        :rtype:           :class:`VDispatchStore`
        :raises:          :exc:`exceptions.IOError`

        """
        if os.path.exists(filename):
            raise IOError('File already exists')
        conn = sqlite3.connect(filename, check_same_thread=False)

        # Tables for dispatched services

        c = conn.cursor()
        cmd = '''
        create table services (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            autostart INTEGER
        )'''
        c.execute(cmd)
        cmd = '''create table s_paths (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            services_id INTEGER,
            name TEXT,
            script TEXT,
            script_result TEXT
        )'''
        c.execute(cmd)
        cmd = '''create table s_loaders (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            services_id INTEGER,
            load_mod TEXT,
            load_path TEXT,
            load_as TEXT
        )'''
        c.execute(cmd)

        # Tables for dispatchers
        cmd = '''
        create table dispatchers (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE,
            script TEXT,
            script_result TEXT
            autostart INTEGER
        )'''
        c.execute(cmd)
        cmd = '''create table d_loaders (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            dispatcher_id INTEGER,
            load_mod TEXT,
            load_path TEXT,
            load_as TEXT
        )'''
        c.execute(cmd)

        conn.commit()
        return cls(filename)

    @property
    def service_names(self):
        """Service definition names registered in the store (unicode,)."""
        with self:
            c = self._conn.cursor()
            c.execute('select name from services')
            return tuple(row[0] for row in iter(c))

    @property
    def dispatcher_paths(self):
        """Dispatcher paths registered in the store ((unicode,),)."""
        with self:
            c = self._conn.cursor()
            c.execute('select path from dispatchers')
            return tuple(self._unmerge_path(row[0]) for row in iter(c))

    @classmethod
    def _merge_path(cls, path):
        if not isinstance(path, (tuple, list)):
            raise TypeError('Path must be tuple or list')
        for p in path:
            if '/' in p:
                raise ValueError('Path entries cannot contain \'/\'')
        return '/'.join(path)

    @classmethod
    def _unmerge_path(cls, pathname):
        return pathname.split('/')
