"""Optional embedded PostgreSQL runtime - a real PG16 in-process, no Docker.

Boots a PostgreSQL 16 cluster from the ``pixeltable-pgserver`` wheel (bundled PG
binaries) and points the app's ``DATABASE_URL`` / ``DATABASE_SYNC_URL`` at it, so
the whole app runs on PostgreSQL with zero external setup. This is the default
runtime; the operator opts out only by supplying an external ``DATABASE_URL`` or
setting ``OE_USE_EMBEDDED_PG`` to a falsy value (see :func:`is_requested`).

The cluster's data directory is ``<data_dir>/pgdata`` so it survives restarts.
On first boot ``initdb`` runs once (a few seconds); subsequent boots attach to the
existing cluster.

Ordering contract
~~~~~~~~~~~~~~~~~
``app.database`` builds the SQLAlchemy engine from ``settings.database_url`` at
*import time*. :func:`boot` therefore MUST run before the first ``from app...``
import that pulls in ``app.database`` (and before ``get_settings()`` is cached).
The CLI calls it from ``_setup_env``, which every command runs before importing
any app module - so the contract holds for ``serve``/``init-db``/``seed``.

Single-process only: run ONE uvicorn worker with embedded PG (the default). For
multi-worker deployments use an external PostgreSQL and set ``DATABASE_URL``
directly.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: Module-level handle to the running server, kept so :func:`shutdown` can stop it.
_server = None

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def emit_stage(stage: str, status: str, detail: str = "") -> None:
    """Emit one machine-readable boot-progress marker on stdout (and the log).

    The desktop launcher (Tauri shell) pumps the sidecar's stdout into its own
    diagnostic log and parses these ``STAGE:`` lines to drive the visible boot
    checklist, so the user always sees which step is running and exactly where a
    startup failure happened. The format is deliberately simple and stable:

        ``STAGE:<stage>:<status>[:<detail>]``

    where ``stage`` is a short identifier (``pg``, ``migrate``, ``server`` ...),
    ``status`` is one of ``start`` / ``progress`` / ``done`` / ``fail``, and the
    optional ``detail`` is free human text (no newlines, no colons are required
    to be escaped because the consumer splits on the first three only).

    Best effort: never raises, so progress reporting can never break startup.
    """
    try:
        clean_detail = detail.replace("\n", " ").replace("\r", " ").strip()
        line = f"STAGE:{stage}:{status}"
        if clean_detail:
            line += f":{clean_detail}"
        # stdout is the transport the launcher watches; flush so the marker is
        # delivered immediately rather than sitting in a block buffer.
        print(line, flush=True)
        logger.info(line)
    except Exception:  # noqa: BLE001
        pass


def is_requested() -> bool:
    """True when the app should run on the embedded PostgreSQL cluster.

    Embedded PostgreSQL is the **default** runtime - a fresh
    ``openconstructionerp serve`` boots a real in-process PG16 (no Docker). The
    operator opts out in either of two ways, checked in order:

    * an explicit ``DATABASE_URL`` in the environment - "use my own database",
      so we never override it with an embedded cluster;
    * ``OE_USE_EMBEDDED_PG`` set to a falsy value (``0``/``false``/``no``/``off``)
      - explicit opt-out (typically paired with an external PG set via
      ``DATABASE_URL``, which is also covered by the rule above).

    Otherwise (the default, and any truthy ``OE_USE_EMBEDDED_PG``) it returns
    ``True``. An explicit truthy ``OE_USE_EMBEDDED_PG`` wins over an ambient
    ``DATABASE_URL`` (the two together are contradictory; the explicit flag is
    the clearer intent).
    """
    explicit = os.environ.get("OE_USE_EMBEDDED_PG", "").strip().lower()
    if explicit in _TRUTHY:
        return True
    if os.environ.get("DATABASE_URL", "").strip():
        return False
    if explicit in _FALSY:
        return False
    return True


def is_running() -> bool:
    """True once :func:`boot` has successfully started a cluster this process."""
    return _server is not None


def boot(data_dir: Path | str) -> bool:
    """Boot embedded PostgreSQL and point DATABASE_URL/DATABASE_SYNC_URL at it.

    Idempotent (a second call is a no-op once running). Never raises: on any
    failure it logs and returns ``False``. There is no SQLite fallback, so a
    ``False`` here is fatal at the CLI layer (``_setup_env`` exits with an
    actionable message). Returns ``True`` on success.
    """
    global _server
    if _server is not None:
        return True

    try:
        import pixeltable_pgserver as pgserver
        from sqlalchemy.engine import make_url
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "embedded PostgreSQL requested but pixeltable-pgserver is not installed "
            "(pip install 'openconstructionerp[server]' or pixeltable-pgserver): %r",
            exc,
        )
        return False

    pgdata = Path(data_dir).expanduser() / "pgdata"
    try:
        pgdata.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("embedded PostgreSQL data dir unavailable at %s: %r", pgdata, exc)
        return False

    # pixeltable-pgserver hard-codes a 10s ``pg_ctl start -w`` timeout
    # (postgres_server.py). After an unclean shutdown (force-kill, crash, power
    # loss) PostgreSQL replays its WAL on the next boot. On a large cluster that
    # replay also fsyncs every file in the data directory, which can take SEVERAL
    # MINUTES (observed ~140s on a 1.2 GB cluster on Windows). The 10s pg_ctl
    # wait therefore always times out, and pixeltable's pidfile parser then
    # raises AssertionError because, while recovery is in progress, PostgreSQL
    # writes only the first lines of postmaster.pid (the port/status lines are
    # added once it is ready) -- so the file does not yet have the 8 lines the
    # parser asserts on. Both failures mean a fixed-attempt retry gives up long
    # before recovery finishes, the sidecar exits, and the desktop window shows
    # nothing.
    #
    # The robust fix: launch the postmaster ourselves once, then WAIT for the
    # cluster to actually accept connections (probing the real port, not the
    # fragile pidfile) for a generous window, and only then hand off to
    # get_server(), which now simply attaches to the already-running, ready
    # postmaster (no pg_ctl, no timeout, complete pidfile).
    resolved_pgdata = pgdata.expanduser().resolve()

    try:
        from pixeltable_pgserver.postgres_server import PostgresServer as _PS
    except Exception:  # noqa: BLE001
        _PS = None

    # A leftover postmaster.pid whose process is gone (the usual aftermath of a
    # force-kill) makes pixeltable take its slower "found a pid file but server
    # not running" path; clearing it first keeps boot on the clean-start path.
    _clear_stale_pidfile(resolved_pgdata)

    # Embedded PG must initialise with an ASCII-safe locale. PostgreSQL's initdb
    # rejects a locale *name* that contains non-ASCII characters, and the bundled
    # initdb otherwise inherits the operating-system locale. On a Turkish Windows
    # box that locale is "Turkish_Türkiye.1254": initdb aborts with `locale name
    # ... contains non-ASCII characters`, then pixeltable crashes a second time
    # decoding that CP1254 error text as UTF-8, and the cluster is left stuck
    # "Recovering the local database" forever. Force the C locale for every PG
    # child process, and on Windows -- where env vars do NOT override the OS
    # locale that initdb reads -- pre-create the cluster ourselves with an
    # explicit --locale=C so pixeltable's own (locale-inheriting) initdb is
    # skipped. Both are no-ops once the cluster exists.
    _apply_ascii_locale_env()
    _pre_initialize_cluster(resolved_pgdata)

    emit_stage("pg", "start", "Starting embedded PostgreSQL")

    # Window for the whole bring-up, including a possibly slow crash recovery.
    # Override with OE_PG_BOOT_TIMEOUT (seconds) for very large clusters or slow
    # disks. 600s comfortably covers multi-minute fsync-based recovery.
    boot_timeout = _int_env("OE_PG_BOOT_TIMEOUT", 600)
    deadline = time.monotonic() + boot_timeout

    srv = None
    last_exc: Exception | None = None
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            srv = pgserver.get_server(str(pgdata))
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            # The first get_server() launches the postmaster, which keeps
            # recovering in the background even though pg_ctl/the parser raised.
            # Evict the half-built handle pixeltable cached (keyed by resolved
            # pgdata) so the next get_server() re-reads the now-progressing
            # cluster instead of returning the broken handle.
            if _PS is not None:
                try:
                    _PS._instances.pop(resolved_pgdata, None)
                except Exception:  # noqa: BLE001
                    pass

            remaining = int(deadline - time.monotonic())
            logger.warning(
                "embedded PostgreSQL not ready yet (attempt %d, %ds left); crash recovery "
                "may be replaying WAL -- waiting: %r",
                attempt,
                max(remaining, 0),
                exc,
            )
            emit_stage(
                "pg",
                "progress",
                f"Recovering the local database, this can take a few minutes ({max(remaining, 0)}s left)",
            )

            # Wait for the postmaster to actually accept connections (recovery
            # complete). When it does, loop straight back into get_server(),
            # which now attaches cleanly. If it never does within the window we
            # fall through to the failure path below.
            if not _wait_until_connectable(resolved_pgdata, deadline):
                break
            # A short floor between get_server() retries: if the port is already
            # open but get_server() still raised (a brief pidfile race), this
            # keeps the loop from spinning hot while the pidfile finishes.
            time.sleep(1.0)

    if srv is None:
        emit_stage("pg", "fail", _pg_failure_detail(resolved_pgdata, last_exc))
        logger.error(
            "embedded PostgreSQL failed to start at %s within %ds: %r",
            pgdata,
            boot_timeout,
            last_exc,
        )
        return False

    emit_stage("pg", "done", "Embedded PostgreSQL ready")

    try:
        # get_uri() is portable: TCP loopback on Windows, a unix socket on
        # Linux/macOS. Swap only the SQLAlchemy driver - never hand-parse it.
        base = make_url(srv.get_uri())
        async_url = base.set(drivername="postgresql+asyncpg")
        sync_url = base.set(drivername="postgresql+psycopg2")
        os.environ["DATABASE_URL"] = async_url.render_as_string(hide_password=False)
        os.environ["DATABASE_SYNC_URL"] = sync_url.render_as_string(hide_password=False)
    except Exception as exc:  # noqa: BLE001
        logger.error("embedded PostgreSQL booted but URL wiring failed: %r", exc)
        try:
            srv.cleanup()
        except Exception:  # noqa: BLE001
            pass
        return False

    _server = srv
    logger.info("embedded PostgreSQL ready (data dir: %s)", pgdata)
    return True


def _int_env(name: str, default: int) -> int:
    """Read a positive integer from the environment, falling back on parse errors."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _read_pidfile_pid(pgdata: Path) -> int | None:
    """Return the postmaster PID recorded in ``postmaster.pid``, or ``None``."""
    pidfile = pgdata / "postmaster.pid"
    try:
        first = pidfile.read_text(encoding="utf-8", errors="ignore").splitlines()[0].strip()
        return int(first)
    except (OSError, IndexError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    """Best-effort check whether a process with ``pid`` currently exists."""
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        # Without psutil, assume the process may be alive so we never delete a
        # pidfile for a live postmaster.
        return True


def _clear_stale_pidfile(pgdata: Path) -> None:
    """Delete ``postmaster.pid`` when it points at a process that is gone.

    A force-kill or crash leaves the pidfile behind. PostgreSQL itself refuses
    to start while a pidfile names a live process, but a pidfile for a dead PID
    only slows pixeltable's start path; removing it lets the clean-start path
    run. Never removes a pidfile whose process is still alive.
    """
    pidfile = pgdata / "postmaster.pid"
    if not pidfile.exists():
        return
    pid = _read_pidfile_pid(pgdata)
    if pid is None:
        return
    if _pid_alive(pid):
        return
    try:
        pidfile.unlink()
        logger.info("removed stale postmaster.pid (dead pid %d) in %s", pid, pgdata)
    except OSError as exc:
        logger.warning("could not remove stale postmaster.pid in %s: %r", pgdata, exc)


#: Locale overrides forced onto every embedded-PG child process. PostgreSQL's
#: initdb rejects locale *names* that contain non-ASCII characters; the C locale
#: is always ASCII and deterministic, which is exactly what an internal app
#: cluster wants (byte-order collation, no linguistic surprises).
_ASCII_LOCALE_ENV = {
    "LC_ALL": "C",
    "LANG": "C",
    "LC_CTYPE": "C",
    "LC_COLLATE": "C",
    "LC_MESSAGES": "C",
}


def _apply_ascii_locale_env() -> None:
    """Force a C locale for the embedded-PG subprocesses (initdb / postgres).

    Set in this process's environment so every child PG binary inherits it.
    Safe for the Python app itself: its locale was fixed at interpreter start and
    it does all file I/O as explicit UTF-8, so mutating ``os.environ`` now only
    affects the child processes we spawn, not Python's own text handling.
    """
    for key, value in _ASCII_LOCALE_ENV.items():
        os.environ[key] = value


def _initdb_args(pgdata: Path) -> tuple[str, ...]:
    """``initdb`` arguments matching pixeltable-pgserver, plus an explicit C locale.

    Kept identical to ``pixeltable_pgserver.postgres_server`` (auth=trust, utf8
    encoding, superuser ``postgres``) so a cluster we pre-create is exactly what
    pixeltable expects -- it then finds ``PG_VERSION`` and skips its own initdb.
    """
    return (
        "--auth=trust",
        "--auth-local=trust",
        "--encoding=utf8",
        "--locale=C",
        "-U",
        "postgres",
        "-D",
        str(pgdata),
    )


def _pre_initialize_cluster(pgdata: Path) -> bool:
    """On Windows, create the PG cluster with an ASCII-safe locale, once.

    Returns ``True`` if this call initialised the cluster, ``False`` if it was
    already initialised, not applicable (non-Windows), or the pre-init failed --
    in which case we leave it to pixeltable's own path, so we are never worse off
    than before.

    Windows-only on purpose: on POSIX, initdb honours the ``LC_*``/``LANG``
    environment, so :func:`_apply_ascii_locale_env` already steers it to C. On
    Windows the C runtime's locale comes from the OS regional settings, not env
    vars, so the only reliable way to dodge a non-ASCII OS locale is to pass
    ``--locale=C`` to initdb explicitly, which we do here before pixeltable's
    ``get_server()`` runs.
    """
    if os.name != "nt":
        return False
    if (pgdata / "PG_VERSION").exists():
        return False
    try:
        from pixeltable_pgserver.pgexec import pgexec
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not import pixeltable pgexec for pre-init: %r", exc)
        return False
    try:
        pgexec("initdb", _initdb_args(pgdata))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "pre-initialising embedded PostgreSQL with --locale=C failed; falling back to pixeltable's own initdb: %r",
            exc,
        )
        return False
    logger.info("pre-initialised embedded PostgreSQL cluster (locale=C) at %s", pgdata)
    return True


def _port_from_pidfile(pgdata: Path) -> int | None:
    """Return the TCP port the recovering postmaster is listening on, if known.

    During crash recovery PostgreSQL writes the port line (line 4) early, so we
    can learn the port even before the pidfile is "complete" enough for
    pixeltable's parser. Returns ``None`` if not yet present.
    """
    pidfile = pgdata / "postmaster.pid"
    try:
        lines = pidfile.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    if len(lines) < 4:
        return None
    try:
        port = int(lines[3].strip())
    except ValueError:
        return None
    return port if port > 0 else None


def _wait_until_connectable(pgdata: Path, deadline: float) -> bool:
    """Block until the embedded postmaster accepts TCP connections, or deadline.

    Probes ``127.0.0.1:<port>`` (port read from the recovering postmaster's
    pidfile) with a raw socket connect, which succeeds as soon as recovery
    finishes and the postmaster opens its listen socket. This is far more robust
    than parsing the pidfile, which is incomplete while recovery runs. Returns
    ``True`` if it became connectable before ``deadline``, else ``False``.
    """
    import socket

    while time.monotonic() < deadline:
        port = _port_from_pidfile(pgdata)
        if port is not None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2):
                    # Give PostgreSQL a breath after the socket opens so the
                    # very next get_server() attach finds status == 'ready'.
                    time.sleep(1.0)
                    return True
            except OSError:
                pass
        time.sleep(2.0)
    return False


def _pg_failure_detail(pgdata: Path, last_exc: Exception | None) -> str:
    """Build a short human-readable reason for an embedded-PG boot failure."""
    detail = "Could not start the local database"
    if last_exc is not None:
        detail += f": {type(last_exc).__name__}"
    log = pgdata / "log"
    try:
        if log.exists():
            tail = log.read_text(encoding="utf-8", errors="ignore").splitlines()[-3:]
            joined = " ".join(line.strip() for line in tail if line.strip())
            if joined:
                detail += f" (postgres log: {joined})"
    except OSError:
        pass
    return detail


def auto_migrate_legacy_sqlite(data_dir: Path | str) -> str:
    """One-time transparent SQLite -> embedded-PostgreSQL data migration.

    Runs only when ALL hold: embedded PG is running, a legacy
    ``<data_dir>/openestimate.db`` exists with content, the target is PostgreSQL,
    and the embedded cluster has no app rows yet (so an already-populated PG is
    never clobbered). On success the SQLite file is renamed to
    ``openestimate.db.migrated`` (with a numeric suffix if needed) so it never
    re-runs. Never raises -- returns a human-readable status string for the
    caller to log/print. A no-op (and safe) when the preconditions don't hold.
    """
    if _server is None:
        return "skip: embedded PostgreSQL not running"

    sqlite_file = Path(data_dir).expanduser() / "openestimate.db"
    try:
        if not sqlite_file.exists() or sqlite_file.stat().st_size == 0:
            return "skip: no legacy SQLite database to migrate"
    except OSError as exc:
        return f"skip: cannot stat {sqlite_file}: {exc!r}"

    sync_url = os.environ.get("DATABASE_SYNC_URL", "")
    if "postgresql" not in sync_url:
        return "skip: target is not PostgreSQL"

    try:
        from sqlalchemy import create_engine

        from app.scripts import migrate_sqlite_to_postgres as migrator
    except Exception as exc:  # noqa: BLE001
        logger.error("auto-migration unavailable: %r", exc)
        return f"error: migration module import failed: {exc!r}"

    dst = None
    src = None
    try:
        base = migrator._load_metadata()
        dst = create_engine(sync_url)
        base.metadata.create_all(dst)

        existing = migrator._target_has_rows(dst, base)
        if existing:
            return f"skip: embedded PostgreSQL already has data (e.g. '{existing}')"

        src = migrator._make_source_engine(f"sqlite:///{sqlite_file.as_posix()}")
        skipped = migrator._copy_all(src, dst, base, 1000)
        migrator._reset_sequences(dst, base)
    except Exception as exc:  # noqa: BLE001
        logger.exception("SQLite -> PostgreSQL auto-migration failed")
        return f"error: {exc!r}"
    finally:
        for eng in (src, dst):
            if eng is not None:
                try:
                    eng.dispose()
                except Exception:  # noqa: BLE001
                    pass

    # Rename the source so a later boot does not migrate again.
    backup = sqlite_file.with_name(sqlite_file.name + ".migrated")
    counter = 0
    while backup.exists():
        counter += 1
        backup = sqlite_file.with_name(f"{sqlite_file.name}.migrated.{counter}")
    try:
        sqlite_file.rename(backup)
        kept = backup.name
    except OSError:
        logger.warning("migrated but could not rename %s", sqlite_file)
        kept = sqlite_file.name + " (rename failed)"

    msg = f"migrated SQLite -> embedded PostgreSQL (skipped {skipped} unconvertible rows); legacy db kept as {kept}"
    logger.info(msg)
    return msg


def shutdown() -> None:
    """Stop the embedded cluster if this process booted one (safe to always call)."""
    global _server
    if _server is None:
        return
    try:
        _server.cleanup()
        logger.info("embedded PostgreSQL stopped")
    except Exception:  # noqa: BLE001
        logger.debug("embedded PostgreSQL cleanup failed", exc_info=True)
    finally:
        _server = None
