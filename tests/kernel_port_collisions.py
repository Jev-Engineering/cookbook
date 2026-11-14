"""Make kernel starts lose the race for a port, for real (#328).

On Windows, under load, a kernel sometimes dies at start with ``ZMQError: Address in use``.
jupyter_client chooses a kernel's five ports by binding a probe socket to port 0 for each and
closing it, and the kernel binds the ports it was given only when it has started, seconds later on
a loaded machine; anything else on the machine that takes one of the ports in between (another
kernel start, an outgoing connection) makes the kernel's bind fail, and the kernel exits.

``PortCollisions`` reproduces that exactly, without depending on the timing: as soon as
jupyter_client has written a kernel's connection file it opens a listening socket on that kernel's
shell port, so the kernel that follows fails the way it does there and the manager reports
"Kernel died before replying to kernel_info". The first ``count`` starts are given that treatment,
every later one is left alone.

This is a plain module (not a test file) loaded by path, because tests/ is not a package; the
tests that run the tool in a subprocess import it from a ``sys.path`` entry instead.
"""

from __future__ import annotations

import os
import socket

from jupyter_client.connect import ConnectionFileMixin


class PortCollisions:
    """Take the shell port of the next ``count`` kernel starts. ``starts`` lists the shell port
    each start was given, in order (all of them, taken or not)."""

    def __init__(self, count: int) -> None:
        self.left = count
        self.starts: list[int] = []
        self._held: list[socket.socket] = []
        self._original = ConnectionFileMixin.write_connection_file

    def install(self) -> PortCollisions:
        original = self._original
        collisions = self

        def write_connection_file(manager, **kwargs):
            # jupyter_client writes the file once per manager and skips it if it is written.
            first = not (
                manager._connection_file_written and os.path.exists(manager.connection_file)
            )
            original(manager, **kwargs)
            if first:
                collisions._start(manager.ip, manager.shell_port)

        ConnectionFileMixin.write_connection_file = write_connection_file
        return self

    def uninstall(self) -> None:
        ConnectionFileMixin.write_connection_file = self._original
        for taker in self._held:
            taker.close()
        self._held.clear()

    def _start(self, ip: str, port: int) -> None:
        self.starts.append(port)
        if self.left <= 0:
            return
        self.left -= 1
        taker = socket.socket()
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: nothing else may share the port
            taker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        taker.bind((ip, port))
        taker.listen()
        self._held.append(taker)
