.. _logging_recipe:

Log Link Events
===============

.. currentmodule:: versile.reactor.waitr

For reactor based links with reactors inheriting from
:class:`VFDWaitReactor` the typical method for setting up reactor and
link logging is to call the class method
:meth:`VFDWaitReactor.set_default_log_watcher` at the start of the
program to set up a shared log watcher for all instantiated
reactors. 

The default behavior of the method is to log to the console. The below
code at the start of the program sets up logging to the console for
instantiated reactors::

    from versile.reactor.waitr import VFDWaitReactor
    VFDWaitReactor.set_default_log_watcher()

In order to set up logging to a file a
:class:`versile.common.log.VFileLog` can be passed as an
argument. Alternatively send a custom class deriver from
:class:`versile.common.log.VLogWatcher`\ .

Below is a complete example which initiates console logging and
performs a simple link operation which will generate log output::

    # Set up default reactor logging to console
    from versile.reactor.waitr import VFDWaitReactor
    VFDWaitReactor.set_default_log_watcher()
    
    # Simple link test which triggers log output
    from versile.demo import Echoer
    from versile.quick import Versile, link_pair
    Versile.set_agpl_internal_use()
    client = link_pair(gw1=None, gw2=Echoer())[0]
    echo_service = client.peer_gw()
    echo_service.echo(u'Test Call')
    client.shutdown()
