"""Block network access in tests unless marked @pytest.mark.live (CLAUDE.md rule)."""

import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "::1", "localhost"):
            return original(self, address)
        raise RuntimeError(f"Network access in tests is blocked (tried {address}). Mark as live.")

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host in ("127.0.0.1", "::1", "localhost", None):
            return original_gai(host, *args, **kwargs)
        raise RuntimeError(f"DNS lookup in tests is blocked (tried {host}). Mark as live.")

    original = socket.socket.connect
    original_gai = socket.getaddrinfo
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
