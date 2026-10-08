"""Block network access in tests unless marked @pytest.mark.live (CLAUDE.md rule)."""

import socket
from pathlib import Path

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


@pytest.fixture(scope="session")
def analysis_written(tmp_path_factory) -> tuple[Path, dict, dict]:
    """Every pair's phase-1 job on synthetic panels, assembled and written once per session
    (about 40 s): (clean dir, docs by pair id, summary)."""
    import analysis_synth as synth
    from poly_actor.analysis import run

    clean = tmp_path_factory.mktemp("clean")
    docs, summary = run.assemble(synth.all_jobs())
    run.write_all(docs, summary, clean)
    return clean, docs, summary
