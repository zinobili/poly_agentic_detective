import importlib

import pytest

from poly_actor import config


@pytest.mark.parametrize(
    "module",
    [
        "poly_actor",
        "poly_actor.config",
        "poly_actor.ingest",
        "poly_actor.store.db",
        "poly_actor.align",
        "poly_actor.analysis",
        "poly_actor.dashboard",
    ],
)
def test_modules_import(module):
    importlib.import_module(module)


def test_root_is_the_repo():
    # Editable/src-checkout install only: ROOT must be the folder holding pyproject.toml.
    assert (config.ROOT / "pyproject.toml").is_file()
    assert (config.ROOT / "src" / "poly_actor").is_dir()


def test_ensure_dirs_creates_raw_and_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(config, "CLEAN_DIR", tmp_path / "clean")
    config.ensure_dirs()
    config.ensure_dirs()  # idempotent
    assert (tmp_path / "raw").is_dir() and (tmp_path / "clean").is_dir()


def test_network_is_blocked_in_tests():
    import socket

    with pytest.raises(RuntimeError, match="blocked"):
        socket.create_connection(("203.0.113.1", 80), timeout=1)  # TEST-NET-3, no DNS
    with pytest.raises(RuntimeError, match="blocked"):
        socket.getaddrinfo("example.com", 80)


def test_duckdb_connects(tmp_path, monkeypatch):
    from poly_actor.store import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    monkeypatch.setattr(db, "ensure_dirs", lambda: None)
    con = db.connect()
    assert con.execute("select 1").fetchone() == (1,)
    con.close()
