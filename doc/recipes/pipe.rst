.. _process_pipe:

Link to ORB via pipe
====================
.. currentmodule:: versile.reactor.io.pipe

The :class:`VPipeAgent` class enables reactor-driven producer/consumer
byte communication for OS pipes on platforms which support
:func:`select.select` on pipe file descriptors, inluding a process'
standard input and standard output. Such byte communication channels
can be used with reactor link implementations to establish a link
between two processes.

Pipe-connected links can be used e.g. to create programs which provide
link interaction capabilities via its standard input and standard
output, and which could also be remotely accessed over secure channels
such as Secure Shell connections.

Below is a simple (Unix) example program which provides a :term:`VEC`
serialized :term:`VOL` link over its standard input and standard
output providing access to a :mod:`versile.demo` example gateway::

    #!/usr/bin/env python

    import sys

    from versile.demo import SimpleGateway
    from versile.reactor.io.link import VLinkAgent
    from versile.reactor.io.pipe import VPipeAgent

    # Set up a link on stdin/stdout
    link = VLinkAgent(gateway=SimpleGateway())
    pipe = VPipeAgent(link.reactor, sys.stdin.fileno(), sys.stdout.fileno())
    link_io = link.create_byte_agent()
    pipe.byte_io.attach(link_io)

    # Obtain gateway and dereference; link terminates when shut down by peer
    gw = link.peer_gw()
    del(gw)

Assuming this program is placed in ``'/tmp/link_prg'`` with execute
permissions and access to required python modules, the following code
will execute this program as a separate process, establish a link to
the program's standard input/ouput, and interact with the gateway
provided by the program::

    #!/usr/bin/env python

    import os
    import subprocess

    from versile.quick import VUrl
    from versile.reactor.io.link import VLinkAgent
    from versile.reactor.io.pipe import VPipeAgent

    # Create a pipe for sub-process communication
    rd, peer_wr = os.pipe()
    peer_rd, wr = os.pipe()

    # Initiate child subprocess
    child = subprocess.Popen(['/tmp/link_prg'], stdin=peer_rd, stdout=peer_wr)

    # Set up link interaction from the master side
    link = VLinkAgent()
    pipe = VPipeAgent(link.reactor, rd, wr)
    link_io = link.create_byte_agent()
    pipe.byte_io.attach(link_io)

    # Test link
    gw = link.peer_gw()
    echoer = VUrl.relative(gw, '/text/echo/')
    _msg = u'Brave, brave sir Robin'
    print('Received test string: %s' % echoer.echo(_msg))

    # Terminate link
    link.shutdown()

With a simple modification the code would instead interact with a
remote link-providing program over Secure Shell. Assuming the user
with the current used ID and can connect to 'ssh.example.com' without
providing a passwords (e.g. after setting up an ssh agent and adding a
password), with the link-providing program residing at the same path
on that server, the following code will interact with the program
remotely over ssh::

    #!/usr/bin/env python

    import os
    import subprocess

    from versile.quick import VUrl
    from versile.reactor.io.link import VLinkAgent
    from versile.reactor.io.pipe import VPipeAgent

    # Create a pipe for sub-process communication
    rd, peer_wr = os.pipe()
    peer_rd, wr = os.pipe()

    # Initiate child subprocess
    child = subprocess.Popen(['ssh', 'ssh.example.com', '/tmp/link_prg'],
                              stdin=peer_rd, stdout=peer_wr)

    # Set up link interaction from the master side
    link = VLinkAgent()
    pipe = VPipeAgent(link.reactor, rd, wr)
    link_io = link.create_byte_agent()
    pipe.byte_io.attach(link_io)

    # Test link
    gw = link.peer_gw()
    echoer = VUrl.relative(gw, '/text/echo/')
    _msg = u'Brave, brave sir Robin'
    print('Received test string: %s' % echoer.echo(_msg))

    # Terminate link
    link.shutdown()
