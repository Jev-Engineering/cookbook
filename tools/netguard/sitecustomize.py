"""Python-level network guard for notebook runs in CI (#69).

Put this folder on ``PYTHONPATH`` and Python imports it at start-up, in the notebook kernel too
(``tools/execute_notebook.py`` passes ``PYTHONPATH`` on; it strips only ``JEV_COOKBOOK_*`` and
``TYPESAFE_*``). From then on any attempt to leave the machine fails at once with
``NetworkBlocked``, an ``OSError``:

* ``connect``, ``connect_ex`` and ``sendto`` to an address that is not loopback;
* name resolution (``getaddrinfo`` and the ``gethostby*`` functions) of any name other than
  ``localhost`` and a loopback address, so no DNS query is made either.

Unix sockets and loopback (the kernel talks to the notebook runner over loopback) stay open.
This guard cannot stop native code that opens its own sockets, which is why CI also runs the
notebooks in a network namespace with no route out. See ``docs/notebook-ci.md``.
"""

from __future__ import annotations

import ipaddress
import socket

MESSAGE = (
    "network access is blocked while cookbook notebooks run in CI "
    "(tools/netguard/sitecustomize.py): a recipe must run offline from its fixtures"
)


class NetworkBlocked(OSError):
    """An attempt to reach a non-loopback address while the guard is installed."""


def _is_loopback(host: object) -> bool:
    if host is None or host == "":
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host.lower() in ("localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _check_address(address: object) -> None:
    # AF_UNIX addresses are str or bytes paths; AF_INET and AF_INET6 are tuples (host, port, ...).
    if isinstance(address, tuple) and address and not _is_loopback(address[0]):
        raise NetworkBlocked(f"{MESSAGE}; refused {address[0]!r}")


def install() -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto
    real_getaddrinfo = socket.getaddrinfo
    real_gethostbyname = socket.gethostbyname
    real_gethostbyname_ex = socket.gethostbyname_ex
    real_gethostbyaddr = socket.gethostbyaddr

    def connect(self, address):
        _check_address(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check_address(address)
        return real_connect_ex(self, address)

    def sendto(self, data, *args):
        # sendto(data, address) or sendto(data, flags, address): the address is the last argument.
        if args:
            _check_address(args[-1])
        return real_sendto(self, data, *args)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            raise NetworkBlocked(f"{MESSAGE}; refused to resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    def gethostbyname(host):
        if not _is_loopback(host):
            raise NetworkBlocked(f"{MESSAGE}; refused to resolve {host!r}")
        return real_gethostbyname(host)

    def gethostbyname_ex(host):
        if not _is_loopback(host):
            raise NetworkBlocked(f"{MESSAGE}; refused to resolve {host!r}")
        return real_gethostbyname_ex(host)

    def gethostbyaddr(host):
        if not _is_loopback(host):
            raise NetworkBlocked(f"{MESSAGE}; refused to resolve {host!r}")
        return real_gethostbyaddr(host)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = gethostbyname
    socket.gethostbyname_ex = gethostbyname_ex
    socket.gethostbyaddr = gethostbyaddr


install()
