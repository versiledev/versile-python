.. _daemonize_recipe:

Daemonize a Service
===================

It is often desirable to execute a :term:`VPy` service as a 'system
service' (terminology differs between operating systems) which can be
managed with OS system service management tools.  This allows
e.g. configuring a server so the service is automatically started
during system boot. On Unix-based creating 'system services' typically
involves daemonizing the process which runs the service.

Below is a simple (Unix only) example how a
:class:`versile.orb.service.VService` can be run in a daemonized
process. The example uses the python package `python-daemon
<http://pypi.python.org/pypi/python-daemon/>`__ which implements
:pep:`3143`\ . The process writes its PID to a file and shuts down
upon receiving SIGTERM::

    #!/usr/bin/env python
    # Sets up a VOP service as a daemon using the python-daemon package.
    # Requires http://pypi.python.org/pypi/python-daemon/ and POSIX.

    import errno
    import fcntl
    import os
    import signal
    import sys
    import time

    import daemon # requires the python-daemon package

    from versile.demo import Echoer
    from versile.quick import VOPService, VCrypto, VUrandom


    # Pid file code based on http://code.activestate.com/recipes/577911/
    class PidFile(object):
        def __init__(self, path):
            self._path = path
            self._f = None

        def __enter__(self):
            self._f = open(self._path, "a+")
            try:
                fcntl.flock(self._f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError:
                raise SystemExit('PID file already locked')
            self._f.seek(0)
            self._f.truncate()
            self._f.write(b'%s' % os.getpid())
            self._f.flush()
            self._f.seek(0)
            return self._f

        def __exit__(self, *args):
            try:
                self._f.close()
            except IOError as err:
                if err.errno != errno.EBADF:
                    raise
            else:
                os.remove(self._path)


    # Simple daemon - a "real" daemon typically needs to drop privileges etc.,
    # see python-daemon documentation and PEP 3143 for details.
    class MyDaemon(daemon.DaemonContext):
        def __init__(self, pidfile):
            super(MyDaemon, self).__init__()
            self.pidfile = PidFile(pidfile)
            self.signal_map[signal.SIGTERM] = self.sigterm_handler

        def run(self):
            with self:
	        # For this demonstration we use a random server keypair
                _key_gen = VCrypto.lazy().rsa.key_factory.generate
                keypair = _key_gen(VUrandom(), 1024//8)
                self._service = VOPService(lambda: Echoer(), None)
                self._service.start()
                while True:
                    time.sleep(1)

        def sigterm_handler(self, *args):
            self._service.stop(stop_links=True, force=True)
            self._service.wait(stopped=True)
            sys.exit(0)


    if __name__ == '__main__':
        # Would normally use /var/run/*.pid
        daemon = MyDaemon('/tmp/mydaemon.pid')
        daemon.run()


Daemonizing the program does not by itself install it as a
system-level service, and the specific steps how to set up a service
are OS specific. Typically a 'daemon server program' as the above
example can be combined with scripts for `SysVInit
<http://en.wikipedia.org/wiki/Sysvinit>`__ or `upstart
<http://upstart.ubuntu.com/index.html>`__ to set up a system-level
service.

Note that non-Unix operating systems such as Windows uses other
mechanisms for setting up system-level services.
