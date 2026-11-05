"""Offline guard for replay (spec 011 FR-004, research R4): no network while readers run.

`no_network()` patches `socket.socket.connect`/`connect_ex`, `socket.create_connection` and `socket.getaddrinfo` so
any attempt to reach another host raises `NetworkForbidden` and is counted. Loopback and Unix sockets stay allowed:
the engine's own database lives there, and it is not "the network" a replay must not touch.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


class NetworkForbidden(OSError):
    """A network call was attempted inside `no_network()`."""


@dataclass
class Guard:
    attempts: int = 0
    last: str | None = None


_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", ""}


def _local_host(host: Any) -> bool:
    if host is None:
        return True
    h = host.decode() if isinstance(host, bytes) else str(host)
    if h.lower() in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(h.split("%")[0]).is_loopback
    except ValueError:
        return False


def _local_address(address: Any) -> bool:
    if isinstance(address, (str, bytes)):  # AF_UNIX path
        return True
    if isinstance(address, tuple) and address:
        return _local_host(address[0])
    return False


@contextmanager
def no_network() -> Iterator[Guard]:
    guard = Guard()
    orig_connect, orig_connect_ex = socket.socket.connect, socket.socket.connect_ex
    orig_create, orig_gai = socket.create_connection, socket.getaddrinfo

    def refuse(what: str) -> NetworkForbidden:
        guard.attempts += 1
        guard.last = what
        return NetworkForbidden(f"network access during an offline replay: {what}")

    def connect(self: socket.socket, address: Any) -> None:
        if not _local_address(address):
            raise refuse(f"connect {address!r}")
        return orig_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        if not _local_address(address):
            raise refuse(f"connect_ex {address!r}")
        return orig_connect_ex(self, address)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        if not _local_address(address):
            raise refuse(f"create_connection {address!r}")
        return orig_create(address, *args, **kwargs)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _local_host(host):
            raise refuse(f"getaddrinfo {host!r}")
        return orig_gai(host, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.create_connection = create_connection  # type: ignore[assignment]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    try:
        yield guard
    finally:
        socket.socket.connect = orig_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = orig_connect_ex  # type: ignore[method-assign]
        socket.create_connection = orig_create
        socket.getaddrinfo = orig_gai
