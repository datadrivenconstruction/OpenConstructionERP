"""Embedded-PostgreSQL runtime helper: boot -> set URLs -> connect -> shutdown.

Exercises app.core.embedded_pg directly (the helper the CLI wires into
_setup_env). Gated to the PG lane like the rest of tests/pg.
"""

from __future__ import annotations

import os

import pytest

from app.core import embedded_pg


def test_emit_stage_writes_marker(capsys) -> None:
    """emit_stage prints a stable, parseable STAGE marker on stdout."""
    embedded_pg.emit_stage("pg", "start", "Starting embedded PostgreSQL")
    out = capsys.readouterr().out
    assert "STAGE:pg:start:Starting embedded PostgreSQL" in out

    embedded_pg.emit_stage("server", "done")
    out = capsys.readouterr().out
    assert "STAGE:server:done" in out


def test_emit_stage_strips_newlines(capsys) -> None:
    embedded_pg.emit_stage("migrate", "progress", "line one\nline two")
    out = capsys.readouterr().out
    # One marker, no embedded newline in the detail.
    lines = [ln for ln in out.splitlines() if ln.startswith("STAGE:")]
    assert len(lines) == 1
    assert "line one line two" in lines[0]


def test_int_env(monkeypatch) -> None:
    monkeypatch.delenv("OE_PG_BOOT_TIMEOUT", raising=False)
    assert embedded_pg._int_env("OE_PG_BOOT_TIMEOUT", 600) == 600
    monkeypatch.setenv("OE_PG_BOOT_TIMEOUT", "120")
    assert embedded_pg._int_env("OE_PG_BOOT_TIMEOUT", 600) == 120
    monkeypatch.setenv("OE_PG_BOOT_TIMEOUT", "not-a-number")
    assert embedded_pg._int_env("OE_PG_BOOT_TIMEOUT", 600) == 600
    monkeypatch.setenv("OE_PG_BOOT_TIMEOUT", "0")
    assert embedded_pg._int_env("OE_PG_BOOT_TIMEOUT", 600) == 600


def test_port_from_pidfile(tmp_path) -> None:
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    # A recovering postmaster.pid: first four lines present (pid, dir, start, port).
    (pgdata / "postmaster.pid").write_text("12345\n" + str(pgdata) + "\n1700000000\n54999\n")
    assert embedded_pg._port_from_pidfile(pgdata) == 54999

    # Too short to know the port yet (early recovery).
    (pgdata / "postmaster.pid").write_text("12345\n" + str(pgdata) + "\n")
    assert embedded_pg._port_from_pidfile(pgdata) is None


def test_clear_stale_pidfile_removes_dead(tmp_path, monkeypatch) -> None:
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    pidfile = pgdata / "postmaster.pid"
    pidfile.write_text("999999\n" + str(pgdata) + "\n1700000000\n54999\n")
    # Force the liveness check to report the pid as dead.
    monkeypatch.setattr(embedded_pg, "_pid_alive", lambda _pid: False)
    embedded_pg._clear_stale_pidfile(pgdata.resolve())
    assert not pidfile.exists()


def test_clear_stale_pidfile_keeps_live(tmp_path, monkeypatch) -> None:
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    pidfile = pgdata / "postmaster.pid"
    pidfile.write_text("4321\n" + str(pgdata) + "\n1700000000\n54999\n")
    # A live postmaster's pidfile must never be deleted.
    monkeypatch.setattr(embedded_pg, "_pid_alive", lambda _pid: True)
    embedded_pg._clear_stale_pidfile(pgdata.resolve())
    assert pidfile.exists()


def test_initdb_args_force_c_locale(tmp_path) -> None:
    """initdb is always pre-created with an explicit ASCII-safe --locale=C.

    Regression guard for the Turkish-Windows boot hang: without --locale=C the
    bundled initdb inherits a non-ASCII OS locale name ("Turkish_Türkiye.1254")
    and aborts, leaving the cluster stuck "recovering" forever.
    """
    args = embedded_pg._initdb_args(tmp_path / "pgdata")
    assert "--locale=C" in args
    # Stay byte-for-byte compatible with pixeltable so it skips its own initdb.
    assert "--encoding=utf8" in args
    assert "--auth=trust" in args
    assert args[-2:] == ("-D", str(tmp_path / "pgdata"))
    assert "postgres" in args  # superuser name must match pixeltable's


def test_apply_ascii_locale_env_sets_c(monkeypatch) -> None:
    for key in embedded_pg._ASCII_LOCALE_ENV:
        monkeypatch.delenv(key, raising=False)
    embedded_pg._apply_ascii_locale_env()
    assert os.environ["LC_ALL"] == "C"
    assert os.environ["LANG"] == "C"
    assert os.environ["LC_CTYPE"] == "C"
    assert os.environ["LC_COLLATE"] == "C"


def test_pre_initialize_cluster_noop_on_posix(tmp_path, monkeypatch) -> None:
    """On POSIX the env-var locale fix is enough, so pre-init is a no-op."""
    monkeypatch.setattr(embedded_pg.os, "name", "posix")
    assert embedded_pg._pre_initialize_cluster(tmp_path / "pgdata") is False


def test_pre_initialize_cluster_skips_when_already_inited(tmp_path, monkeypatch) -> None:
    """A cluster that already has PG_VERSION is never re-initialised."""
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "PG_VERSION").write_text("16\n")
    monkeypatch.setattr(embedded_pg.os, "name", "nt")
    assert embedded_pg._pre_initialize_cluster(pgdata) is False


def test_pre_initialize_cluster_passes_c_locale_on_windows(tmp_path, monkeypatch) -> None:
    """On Windows, a fresh cluster is pre-created via initdb --locale=C."""
    import sys
    import types

    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    monkeypatch.setattr(embedded_pg.os, "name", "nt")

    calls: dict[str, object] = {}

    def fake_pgexec(command, args, **_kwargs):
        calls["command"] = command
        calls["args"] = tuple(args)
        (pgdata / "PG_VERSION").write_text("16\n")  # simulate a real initdb
        return ""

    fake_mod = types.ModuleType("pixeltable_pgserver.pgexec")
    fake_mod.pgexec = fake_pgexec
    if "pixeltable_pgserver" not in sys.modules:
        monkeypatch.setitem(sys.modules, "pixeltable_pgserver", types.ModuleType("pixeltable_pgserver"))
    monkeypatch.setitem(sys.modules, "pixeltable_pgserver.pgexec", fake_mod)

    assert embedded_pg._pre_initialize_cluster(pgdata) is True
    assert calls["command"] == "initdb"
    assert "--locale=C" in calls["args"]


@pytest.mark.asyncio
async def test_boot_sets_urls_connects_and_shuts_down(tmp_path, monkeypatch) -> None:
    # Preserve the URLs the session fixture set; boot() writes os.environ directly.
    saved_url = os.environ.get("DATABASE_URL")
    saved_sync = os.environ.get("DATABASE_SYNC_URL")
    monkeypatch.setenv("OE_USE_EMBEDDED_PG", "1")

    assert embedded_pg.is_requested() is True
    assert embedded_pg.is_running() is False

    booted = embedded_pg.boot(tmp_path)
    try:
        assert booted is True
        assert embedded_pg.is_running() is True

        async_url = os.environ["DATABASE_URL"]
        sync_url = os.environ["DATABASE_SYNC_URL"]
        assert async_url.startswith("postgresql+asyncpg://")
        assert sync_url.startswith("postgresql+psycopg2://")
        assert (tmp_path / "pgdata").is_dir()

        # The URL actually connects.
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        eng = create_async_engine(async_url, poolclass=NullPool)
        try:
            async with eng.connect() as conn:
                assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1
        finally:
            await eng.dispose()

        # boot() is idempotent.
        assert embedded_pg.boot(tmp_path) is True
    finally:
        embedded_pg.shutdown()
        assert embedded_pg.is_running() is False
        # Restore the session fixture's URLs (boot overwrote them in os.environ).
        if saved_url is not None:
            os.environ["DATABASE_URL"] = saved_url
        if saved_sync is not None:
            os.environ["DATABASE_SYNC_URL"] = saved_sync
