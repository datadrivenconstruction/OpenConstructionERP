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
    # A live postmaster's pidfile must never be deleted. "Live" is two answers
    # since the deletion path asks _pidfile_owner_is_live: the pid runs AND it
    # is still the process that wrote the file. Pin both. With only the first
    # pinned, the second asked the real process table about pid 4321, and on a
    # runner where 4321 happened to be some other process the file read as
    # recycled and was removed (CI (PostgreSQL), 2026-10-04).
    monkeypatch.setattr(embedded_pg, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(embedded_pg, "_pid_was_recycled", lambda _pid, _start: False)
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


def test_pre_initialize_cluster_runs_on_posix_too(tmp_path, monkeypatch) -> None:
    """Pre-init is not a Windows-only step, despite starting life as one.

    It began as a locale workaround, which POSIX did not need because the env
    vars are enough there. It now also exists to write ``postgresql.conf``
    between initdb and the postmaster start, and ``max_locks_per_transaction``
    is a postmaster-level setting, so a cluster created by pixeltable's own
    one-shot path would not get it until the *next* boot. That reason applies to
    every platform, so skipping POSIX here would leave a first run on Linux
    hitting the lock ceiling the setting exists to raise.
    """
    monkeypatch.setattr(embedded_pg.os, "name", "posix")
    pgdata = tmp_path / "pgdata"

    assert embedded_pg._pre_initialize_cluster(pgdata) is True
    assert (pgdata / "PG_VERSION").exists(), "initdb should have created the cluster"


def test_pre_initialize_cluster_skips_when_already_inited(tmp_path, monkeypatch) -> None:
    """A cluster that already has PG_VERSION is never re-initialised."""
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "PG_VERSION").write_text("16\n")
    monkeypatch.setattr(embedded_pg.os, "name", "nt")
    assert embedded_pg._pre_initialize_cluster(pgdata) is False


def test_pre_initialize_cluster_passes_c_locale_on_windows(tmp_path, monkeypatch) -> None:
    """On Windows, a fresh cluster is pre-created via initdb --locale=C."""
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    monkeypatch.setattr(embedded_pg.os, "name", "nt")

    calls: dict[str, object] = {}

    def fake_pgexec(command, args, **_kwargs):
        calls["command"] = command
        calls["args"] = tuple(args)
        (pgdata / "PG_VERSION").write_text("16\n")  # simulate a real initdb
        return ""

    # The pre-init runs bundled programs through our own decoding runner, not
    # through pixeltable's pgexec, so the runner is what stands in for initdb.
    monkeypatch.setattr(embedded_pg, "_safe_pgexec", fake_pgexec)

    assert embedded_pg._pre_initialize_cluster(pgdata) is True
    assert calls["command"] == "initdb"
    assert "--locale=C" in calls["args"]


def test_clear_incomplete_cluster_wipes_debris_without_pg_version(tmp_path) -> None:
    """A pgdata with no PG_VERSION is leftover debris and gets cleared.

    Regression for the upgrade path: a build that aborted initdb (the Turkish
    locale bug, a power loss, an antivirus lock) leaves files behind, and initdb
    refuses to run in a non-empty directory. Clearing them lets the fixed build
    re-create the cluster cleanly instead of failing the same way forever.
    """
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "postmaster.opts").write_text("junk\n")
    (pgdata / "base").mkdir()
    (pgdata / "base" / "1").write_text("partial\n")
    assert list(pgdata.iterdir())  # non-empty before

    embedded_pg._clear_incomplete_cluster(pgdata)

    assert pgdata.is_dir()  # the directory itself is preserved (mounts/ACLs)
    assert list(pgdata.iterdir()) == []  # but emptied of debris


def test_clear_incomplete_cluster_keeps_a_real_cluster(tmp_path) -> None:
    """A directory that already has PG_VERSION is a real cluster, left untouched."""
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "PG_VERSION").write_text("16\n")
    (pgdata / "base").mkdir()
    embedded_pg._clear_incomplete_cluster(pgdata)
    assert (pgdata / "PG_VERSION").exists()
    assert (pgdata / "base").is_dir()


def test_pre_initialize_cluster_clears_debris_then_inits(tmp_path, monkeypatch) -> None:
    """On Windows, a non-empty pgdata without PG_VERSION is cleared, then inited."""
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    # Debris from a previous failed init: present, no PG_VERSION.
    (pgdata / "postmaster.opts").write_text("leftover\n")
    monkeypatch.setattr(embedded_pg.os, "name", "nt")

    seen: dict[str, object] = {}

    def fake_pgexec(command, args, **_kwargs):
        if args == ("--version",):
            # Pre-flight probe: just confirm the binary is reachable.
            return "initdb (PostgreSQL) 16.3"
        # initdb must find an EMPTY directory (debris already cleared).
        seen["dir_empty_at_initdb"] = list(pgdata.iterdir()) == []
        seen["command"] = command
        (pgdata / "PG_VERSION").write_text("16\n")
        return ""

    # The pre-init runs bundled programs through our own decoding runner, not
    # through pixeltable's pgexec, so the runner is what stands in for initdb.
    monkeypatch.setattr(embedded_pg, "_safe_pgexec", fake_pgexec)

    assert embedded_pg._pre_initialize_cluster(pgdata) is True
    assert seen["command"] == "initdb"
    assert seen["dir_empty_at_initdb"] is True  # debris cleared before initdb ran


@pytest.fixture
def detached_from_the_session_cluster():
    """Hide the suite's own cluster so a test can boot one of its own.

    ``tests/conftest.py`` boots a cluster for the whole run and pins it with
    ``retain()``. By the time any test executes, ``is_running()`` is therefore
    already True and ``shutdown()`` is a deliberate no-op. Both are correct for
    the suite, and both make the boot/shutdown cycle impossible to observe
    through the module's real state.

    Detaching the globals for the duration lets the test drive a genuine boot,
    and restoring them afterwards hands the session's cluster back untouched:
    the test never stops it, because for its lifetime it cannot see it.
    """
    saved_server = embedded_pg._server
    saved_retained = embedded_pg._retained
    embedded_pg._server = None
    embedded_pg._retained = False
    try:
        yield
    finally:
        embedded_pg._server = saved_server
        embedded_pg._retained = saved_retained


@pytest.mark.asyncio
async def test_boot_sets_urls_connects_and_shuts_down(tmp_path, monkeypatch, detached_from_the_session_cluster) -> None:
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
