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

"""Framework for setting up :term:`VOL` listening services."""

from __future__ import print_function, unicode_literals

import copy
import socket
import time

from versile.internal import _vexport

from versile.common.iface import abstract
from versile.common.processor import VProcessor
from versile.common.util import VLockable, VConfig, VCondition, VNoResult
from versile.conf import Versile
from versile.orb.entity import VException
from versile.orb.error import VLinkError
from versile.orb.external import VExternal, publish

__all__ = ['VGatewayFactory', 'VService', 'VServiceConfig',
           'VServiceController', 'VServiceNode']
__all__ = _vexport(__all__)


@abstract
class VService(VLockable):
    """Listening service for instantiating links on inbound connections.

    :param gw_factory:   factory method for link gateway objects
    :type  gw_factory:   callable
    :param auth:         link peer authorizer (or None)
    :type  auth:         callable
    :param key:          key pair for secure transport (or None)
    :type  key:          :class:`versile.crypto.VAsymmetricKey`
    :param identity:     an identity to assume (or None)
    :type  identity:     :class:`versile.crypto.x509.cert.VX509Name`
    :param certificates: cert chain (or None)
    :type  certificates: :class:`versile.crypto.x509.cert.VX509Certificate`\ ,
    :param p_auth:       peer communication authorizer (or None)
    :type  p_auth:       :class:`versile.crypto.auth.VAuth`
    :param processor:    processor for service (or None)
    :type  processor:    :class:`versile.common.processor.VProcessor`
    :param sock:         socket to listen on (or None)
    :type  sock:         :class:`socket.socket`
    :param node:         link initiation node (or None)
    :type  node:         :class:`VServiceNode`
    :param internal:     if True set buffersizes for internal socket
    :type  internal:     bool
    :param buf_size:     if not None, override default buffersizes
    :type  buf_size:     int
    :param conf:         additional configuration (default if None)
    :type  conf:         :class:`VServiceConfig`
    :raises:             :exc:`VLinkError`

    Other arguments are similar to :class:`versile.orb.link.VLink`\ .

    .. note::

        Copyleft license information must be globally configured for
        Versile Python on :class:`versile.Versile` before a service
        can be established.

    .. note::

        Some of the arguments are not used by all service protocols,
        e.g.  *key*, *identity* and *certificates* are not used by the
        VTP protocol, and are ignored.

    *gw_factory* is a :class:`versile.orb.service.VGatewayFactory` or
    similar factory method, which returns either a
    :class:`versile.orb.entity.VObject` gateway object, or a tuple of
    a gateway object and a gateway callback method (callable) for when
    the link is activated. If *gw_factory* is None then
    :meth:`_create_gw` is used as the factory (which must then be
    overloaded in a derived class).

    *auth* is passed to links constructed by the service, see
    :class:`versile.orb.link.VLink` for information about its use.

    If a *p_auth* authorizer is provided, accept_host (only)
    validation is performed in sockets produced by a factory
    created by :meth:`_create_factory`\ .

    If *sock* is provided, it must be already bound and set
    listening. An already bound *sock* will override any configuration
    setting for interface or port number.  If *sock* is None, a
    default socket is created and bound.

    If *node* is provided then the service is being controlled and may
    only accept a new connection and initiate a new link when
    authorized by the controlled. The service registers itself with
    the node during construction by calling
    :meth:`VServiceNode.register_service`\ . If *node* is None then
    the service is not being controlled and accepts any incoming
    connections.

    If *internal* is True then buffer sizes in the consumer/producer
    chain of client sockets are set to
    :attr:`DEFAULT_INT_LINK_BUFSIZE`\ , otherwise the socket and
    entity channel defaults are used. If *buf_size* is set then it is
    used as buffer size, regardless of the value of *internal*.

    .. note::

        The difference between *auth* and *p_auth* is *auth* acts on
        the link layer and interacts with settings on a link's call
        context object, whereas *p_auth* acts on the lower
        communication layers.

    When a link is instantiated, it should be instantiated with a deep
    copy of *conf.link_config* as the link's configuration.

    When started, the service will accept incoming connections and
    instantiate a link on each new client connection.

    As per :term:`VOL` protocol specifications, global copyleft
    license information must be set to be used in link handshakes. See
    :class:`versile.Versile` for information. If copyleft license
    information has not been globally configured, :exc:`VLinkError` is
    raised, because the service would not be able to establish links
    for incoming connections.

    This is an abstract class that should not be directly instantiated.

    .. automethod:: _activate
    .. automethod:: _stop_listener
    .. automethod:: _stop_threads
    .. automethod:: _link_added
    .. automethod:: _link_closed
    .. automethod:: _schedule

    """

    def __init__(self, gw_factory, auth, key, identity, certificates, p_auth,
                 processor, sock, node, internal, buf_size, conf):
        super(VService, self).__init__()
        if Versile.copyleft()[0] is None:
            raise VLinkError('Global copyleft info not set on versile.Versile')
        if gw_factory is None:
            gw_factory = self._create_gw
        self._gw_factory = gw_factory
        self._auth = auth
        self._keypair = key
        self._identity = identity
        self._certificates = certificates
        self._p_auth = p_auth
        if processor:
            self._processor = processor
            self._owns_processor = False
        elif conf.lazy_threads > 0:
            self._processor = VProcessor(conf.lazy_threads)
            self._owns_processor = True
        else:
            self._processor = None
            self._owns_processor = False
        self._sock = sock
        self._node = node
        self._internal = internal
        self._buf_size = buf_size
        self._config = conf

        self._links = set()
        self._started = False  # True if service was started
        self._active = False   # True if service is currently active
        self._status_cond = VCondition()

        # This should be at the end of the constructor
        if node:
            node.register_service(self)

    @abstract
    def start(self):
        """Starts the service.

        Binds to an interface and starts listening for
        connections. This method should only be called once.

        """
        raise NotImplementedError()

    def stop(self, stop_links, force=False, thread_sep=False):
        """Stops the service.

        :param stop_links: if True then stop currently active links
        :type  stop_links: bool
        :param force:      if True and stop_links is True, use force shutdown
        :type  force:      bool
        :param thread_sep: internal argument for thread separation
        :type  thread_sep: bool

        This method should only be called after a service has
        previously been started. It can be called multiple times and
        with different arguments (e.g. call once without stopping
        links, call later after a timeout to also stop links).

        """
        if not thread_sep:
            self._schedule(self.stop, stop_links, force, True)
        with self:
            if self._active:
                self._stop_listener()
                if not self._links:
                    # No links, can shut down threads
                    self._stop_threads()
            if stop_links:
                shutdown_links = copy.copy(self._links)
            else:
                shutdown_links = tuple()
        for link in shutdown_links:
            link.shutdown(force=force)

    def wait(self, timeout=None, started=False, active=False, stopped=False):
        """Waits for one of the set states.

        :param timeout: timeout in seconds
        :type  timeout: float
        :param started: if True wait for 'started'
        :type  started: bool
        :param active:  if True wait for 'active'
        :type  active:  bool
        :param stopped: if True wait for 'stopped'
        :type  stopped: bool
        :raises:        :exc:`versile.common.util.VNoResult`

        """
        if not (started or active or stopped):
            raise TypeError('One of the states must be set to True')
        done = lambda: (started and self.started or active and self.active
                        or stopped and self.stopped)
        with self._status_cond:
            if done():
                return
            if timeout:
                start_time = time.time()
            while True:
                if timeout:
                    current_time = time.time()
                    if current_time > start_time + timeout:
                        raise VNoResult()
                    wait_time = start_time + timeout - current_time
                    self._status_cond.wait(wait_time)
                else:
                    self._status_cond.wait()
                if done():
                    break

    @classmethod
    def create_socket(cls, interface='', port=0, bind=True, listen=10,
                      reuse=True):
        """Creates a listening socket for creating a service.

        :param interface: interface to bind to
        :type  interface: unicode
        :param port:      port to bind to
        :type  port:      int
        :param bind:      if True bind the socket
        :type  bind:      bool
        :param listen:    argument for socket.listen() if binding
        :type  listen:    int
        :param reuse:     if True set up address reuse on socket
        :type  reuse:     True

        The returned socket can be used as a *sock* argument for the
        :class:`VService` constructor.

        """
        sock = socket.socket()
        if reuse:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if bind:
            sock.bind((interface, port))
            sock.listen(listen)
        return sock

    @property
    def links(self):
        """Holds a set of currently active links"""
        return self._links

    @property
    def started(self):
        """True if service has been started."""
        return self._started

    @property
    def active(self):
        """True if service is currently active."""
        return self._active

    @property
    def stopped(self):
        """True if service was started and later stopped."""
        return self._started and not self._active

    @property
    def node(self):
        """:class:`VServiceNode` registered on this service, or None."""
        return self._node

    @abstract
    def _can_accept(self):
        """Called by a node to authorize service to accept a client.

        Should only be called after a service has been started, otherwise
        raises an exception.

        """
        raise NotImplementedError()

    def _link_added(self, link):
        """Called internally when a new link is added.

        :param link: the link that was added
        :type  link: :class:`versile.orb.link.VLink`

        Default does nothing, derived classes can overload.

        """
        pass

    def _link_closed(self, link):
        """Called internally when a link was closed.

        :param link: the link that was closed
        :type  link: :class:`versile.orb.link.VLink`

        Default does nothing, derived classes can overload.

        """
        pass

    def _add_link(self, link, thread_sep=False):
        """Internal call to register a new link with the service object.

        :param link:       link to register
        :type  link:       :class:`versile.orb.link.VLink`
        :param thread_sep: internal argument for thread separation
        :type  thread_sep: bool

        Each new link that is instantiated on a new connection must be
        registered with the service object.

        """
        if not thread_sep:
            self._schedule(self._check_if_link_inactive, link, True)
        with self:
            self._links.add(link)
            def callback():
                self._check_if_link_inactive(link)
            link._status_cond.add_callback(callback)
            self._link_added(link)

    def _check_if_link_inactive(self, link, thread_sep=False):
        """Internal call to notify of a link event.

        :param link:       the link that triggered the event
        :type  link:       :class:`versile.orb.link.VLink`
        :param thread_sep: internal argument for thread separation
        :type  thread_sep: bool

        """
        if not thread_sep:
            self._schedule(self._check_if_link_inactive, link, True)

        # This must be done outside the 'with' statement to avoid
        # possible deadlocks
        link_closed = link.closed

        with self:
            if link in self._links and link_closed:
                self._links.discard(link)
                self._link_closed(link)
                if not self._active and not self._links:
                    # No links, can shut down threads
                    self._stop_threads()

    @abstract
    def _schedule(self, func, *args, **kargs):
        """Internal call to schedule thread-separated execution of a call.

        :param func:  function to call
        :type  func:  callable
        :param args:  function args
        :param kargs: function keyword args

        Used by internal methods for thread separation of callbacks.

        """
        raise NotImplementedError()

    def _activate(self):
        """Internal call that must be made when service is activated."""
        with self._status_cond:
            self._started = True
            self._active = True
            self._status_cond.notify_all()

    @abstract
    def _create_gw(self):
        """Create a gateway for a link instantiated by service.

        :returns: see :meth:`__init__` *gw_factory* argument return value

        Default raises an exception and must be overloaded in derived
        classes which allow passing None as a gateway factory argument
        to __init__.

        """
        raise NotImplementedError()

    @abstract
    def _stop_listener(self):
        """Internal call to stop service from listening on new connections."""
        raise NotImplementedError()

    @abstract
    def _stop_threads(self):
        """Internal call to stop all running service threads."""
        raise NotImplementedError()


class VGatewayFactory(object):
    """Factory for creating link gateway objects.

    .. automethod:: __call__

    """

    def __call__(self):
        """See :meth:`build`\ ."""
        return self.build()

    @abstract
    def build(self):
        """Construct a gateway object for link initiation.

        :returns: either gateway object, or a (gateway, init_method) tuple
        :rtype:   :class:`VObject` or (:class:`VObject`\ , callable)

        Abstract method, derived classes must implement.

        """
        return NotImplementedError()


class VServiceConfig(VConfig):
    """Configuration settings for a :class:`VService`\ .

    :param lazy_threads: number of workers for a lazy-created processor
    :type  lazy_threads: int
    :param link_config:  link configuration
    :type  link_config:  :class:`versile.orb.link.VLinkConfig`

    Additional configurations can be set in *kargs*\ .

    """
    def __init__(self, lazy_threads, link_config, **kargs):
        s_init = super(VServiceConfig, self).__init__
        s_init(lazy_threads=lazy_threads, link_config=link_config, **kargs)


class VServiceController(VExternal):
    """Controller object for a set of service nodes.

    :param max_clients:      max total clients (or None)
    :type  max_clients:      int
    :param max_node_clients: max clients per node (or None)
    :type  max_node_clients: int

    Controls a set of services via associated :class:`VServiceNode`
    handlers for those services. As both classes inherit from
    :class:`versile.orb.external.VExternal`\ , they can interact over
    a link - allowing nodes to be controlled e.g. between separate
    processes.

    .. automethod:: _process

    """

    def __init__(self, max_clients=None, max_node_clients=None):
        super(VServiceController, self).__init__()
        self._nodes = dict()    # node -> number active clients
        self._approved = set()  # nodes authorized to accept
        self._max_clients = max_clients
        self._max_node_clients = max_node_clients

    @publish(show=True, doc=True, ctx=False)
    def accepted(self, node):
        """Callback from a node informing it accepted a client connection.

        :param node: node which accepted a connection
        :type  node: :class:`VServiceNode`

        Should be called exactly once per each new connection.

        This is a published external method.

        """
        with self:
            num = self._nodes.get(node, None)
            if num is not None:
                num += 1
                self._nodes[node] = num
                self._approved.discard(node)
            self.__process()

    @publish(show=True, doc=True, ctx=False)
    def closed(self, node):
        """Callback from a node informing a client connection was closed.

        :param node: node which closed a connection.
        :type  node: :class:`VServiceNode`

        Should be called exactly once per each closed client connection.

        This is a published external method.

        """
        with self:
            num = self._nodes.get(node, None)
            if num is not None:
                num -= 1
                self._nodes[node] = max(num, 0)
            self.__process()

    def add_node(self, node):
        """Adds a node to the set of nodes managed by the controller.

        :param node: node to add
        :type  node: :class:`VServiceNode`

        As part of registering the node, this method will call
        :meth:`VServiceNode.start_service` to register itself with the
        node as a controller and start the node service.

        """
        with self:
            self._nodes[node] = 0
            node.start_service(self)
            self.__process()

    def stop(self, stop_links, force):
        """Stops services for all registered nodes.

        Calls :meth:`VServiceNode.stop_service` on all registered
        nodes and clears the list of registered nodes.

        """
        with self:
            for h in self._nodes:
                # Ignore the call response (for now)
                call = h.stop_service(stop_links, force, nowait=True)
            self._nodes.clear()
            self._approved.clear()

    def _process(self):
        """Called internally when changes to nodes or client connections.

        :returns: nodes to authorize
        :rtype:   frozenset

        Returns a set of nodes which should be authorized to accept a
        client connection (if any). Any returned nodes will receive a
        call to :meth:`VCallNode.can_accept` authorizing a connection.

        This method is called internally after a node was added or
        after a notification that a node client connection was
        accepted or closed.

        The default implementation returns a set with a single node
        which is the node with the fewest current client connections,
        except if max connections or max node connection limit
        capacities set on the controller have been exceeded then an
        empty set is returned. Derived classes can override.  the
        fewest connections).

        """
        with self:
            if not self._nodes or self._approved:
                return frozenset()
            d = dict()
            for h, num in self._nodes.items():
                d[num] = h
            min_num = min(d.keys())
            h = d[min_num]
            return frozenset((h,))

    def __process(self):
        with self:
            # Abort processing if limits are exceeded
            if (self._max_clients is not None
                or self._max_node_clients is not None):
                _mc, _mnc = self._max_clients, self._max_node_clients
                available_node = False
                tot_clients = 0
                for num in self._nodes.values():
                    if _mnc is None or num < _mnc:
                        available_node = True
                    tot_clients += num
                if _mc is not None and tot_clients >= _mc:
                    return # Total client limit reached
                if not available_node:
                    return # No client node with available capacity

            nodes = self._process()
            for h in nodes:
                if h not in self._approved:
                    # Ignoring call result (for now)
                    call = h.can_accept(nowait=True)
                    self._approved.add(h)


class VServiceNode(VExternal):
    """Manages a service on behalf of a controller.

    Allows a :class:`VServiceController` to interact with a
    :class:`VService` which is managed by this class.

    When a node is used, it should be registered with the
    :class:`VService` when it is created, as the *node* argument. The
    service constructor takes responsibility for registering the
    service with the node, by calling :meth:`register_service`\ .

    The service cannot be started before the node is registered (which
    is also normally not be possible when the service registers itself
    with the node during construction).

    """

    def __init__(self):
        super(VServiceNode, self).__init__()
        self._service = None
        self._cntl = None

    @publish(show=True, doc=True, ctx=False)
    def start_service(self, cntl):
        """Registers a controller and starts the node's service.

        Should only be called by the node's controller, when it
        registers itself.

        This is a published external method.

        """
        with self:
            if not self._service:
                raise VException('Service not registered')
            if self._cntl:
                raise VException('Controller already registered')
            self._cntl = cntl
            self._service.start()

    @publish(show=True, doc=True, ctx=False)
    def stop_service(self, stop_links, force):
        """Requests the node's service to stop.

        Should only be called by the node's controller.

        This is a published external method.

        """
        with self:
            if self._service:
                self._service.stop(stop_links=stop_links, force=force)
            self._service = None
            self._cntl = None

    @publish(show=True, doc=True, ctx=False)
    def can_accept(self):
        """Authorizes the node's service to accept a single client connection.

        Should only be called by the node's controller.

        This is a published external method.

        """
        with self:
            if self._service:
                self._service._can_accept()

    def register_service(self, service):
        """Registers a service with this node, which the node will manage.

        :param service: service to register
        :type  service: :class:`VService`

        Should normally not be called by program code; a
        :class:`VService` is responsible for calling this method
        during its construction when it receives a *node* argument.

        """
        with self:
            if self._service:
                raise Exception('Service already set')
            if service._started:
                raise Exception('Service was already started')
            self._service = service

    def accepted(self):
        """Callback function for the node's service that it accepted a client.

        When a callback is received, the node's controller is informed
        that a client connection was accepted.

        """
        with self:
            if self._cntl:
                self._cntl.accepted(self)

    def closed(self):
        """Callback function for the node's service that a client was closed.

        When a callback is received, the node's controller is informed
        that a client connection was closed.

        """
        with self:
            if self._cntl:
                self._cntl.closed(self)
