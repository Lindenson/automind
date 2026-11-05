"""The replay's socket guard (spec 011 T008): a network call inside it raises and is counted."""

import socket

import httpx
import pytest

from automind.acquisition.replay.offline import NetworkForbidden, no_network


async def test_httpx_request_inside_guard_raises_and_is_counted():
    with no_network() as guard:
        async with httpx.AsyncClient(timeout=2) as client:
            with pytest.raises((NetworkForbidden, httpx.ConnectError)):
                await client.get("https://example.com/")
    assert guard.attempts == 1
    assert "example.com" in (guard.last or "")


def test_sync_connect_raises():
    with no_network() as guard, pytest.raises(NetworkForbidden):
        socket.create_connection(("93.184.216.34", 80), timeout=1)
    assert guard.attempts == 1


def test_guard_restores_on_exit():
    orig = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)
    with no_network():
        assert socket.socket.connect is not orig[0]
    assert (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo) == orig


def test_loopback_is_not_the_network():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        with no_network() as guard:
            c = socket.create_connection(srv.getsockname(), timeout=1)
            c.close()
        assert guard.attempts == 0
    finally:
        srv.close()


def test_fixture_counts(no_network):
    with pytest.raises(NetworkForbidden):
        socket.getaddrinfo("example.org", 443)
    assert no_network.attempts == 1
