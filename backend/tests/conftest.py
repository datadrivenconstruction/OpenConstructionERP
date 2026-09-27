"""Shared test fixtures.

Test isolation
~~~~~~~~~~~~~~
Per ``feedback_test_isolation.md``: backend tests must NEVER touch the
production database. Several integration suites
(``test_api_smoke``, ``test_boq_regression``, ``test_boq_import_safety``,
``test_boq_cycle_detection``, ``test_boq_cost_item_link``) construct the
FastAPI app via ``create_app()`` which imports ``app.database`` and
binds ``async_session_factory`` to whatever ``DATABASE_URL`` is set at
that moment — so the env vars have to point at a throwaway PostgreSQL
cluster *before* any ``from app...`` import runs.

Doing it here in ``tests/conftest.py`` (which pytest loads before any
test module) guarantees the override beats every test-module import
order, regardless of which suite is collected first. Tests that already
self-redirect (``test_tenant_isolation``, ``test_register_bootstrap``,
etc.) are still fine — they overwrite this with their own connection.
"""

import inspect
import os

# ── Windows asyncpg event-loop policy ──────────────────────────────────────
# On Windows the default ProactorEventLoop leaves asyncpg socket transports to
# be finalized by the GC after the per-test loop has closed, surfacing as a
# noisy "RuntimeError: Event loop is closed" at teardown. The SelectorEventLoop
# policy (the default on Linux/macOS) closes them deterministically. Must run
# before any event loop is created.
import sys as _sys  # noqa: E402
import tempfile
from pathlib import Path

if _sys.platform == "win32":
    import asyncio as _asyncio

    from tests import _asyncio_write_send

    _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())
    # The selector transport on Windows drops a chunk send() refused, which
    # lost rows from asyncpg executemany; see tests/_asyncio_write_send.py.
    _asyncio_write_send.install()

# ── Per-session PostgreSQL isolation (must run before app imports) ──────────
# The app is PostgreSQL-only at runtime, so the test suite runs on PostgreSQL
# too. Two ways to provide it:
#   * CI sets ``DATABASE_URL`` (a postgres service container) — honour it as-is.
#   * Otherwise boot a throwaway embedded PostgreSQL 16 cluster (no Docker) into
#     a temp data dir for the session. ``embedded_pg.boot`` points
#     ``DATABASE_URL`` / ``DATABASE_SYNC_URL`` at the embedded cluster and is
#     registered for shutdown via ``atexit`` so the postmaster is stopped when
#     the run ends, and the data dir is removed with it.
# This must happen before any ``from app...`` import that pulls in
# ``app.database`` (which builds the engine from ``settings.database_url`` at
# import time).
#
# This used to say the temp dir was reclaimed by the OS regardless, and that
# belief is why nobody looked: shutdown stops the postmaster and never removed
# the directory, and nothing else does either, so every single run left its
# cluster on disk. One workstation had accumulated 712 of them, 59.5 GB, before
# anyone noticed the disk rather than the cause.

#: How recently a data dir may have been touched and still be considered a
#: candidate for reaping. Only a belt to the braces below: a session that has
#: just created its data dir but whose postmaster has not yet written its pid
#: file is indistinguishable from a dead one for a second or two.
_PG_REAP_MIN_AGE_SECONDS = 3600

#: Where a running cluster's pid file sits, relative to its data dir.
#:
#: ``embedded_pg.boot`` puts the cluster in ``<data_dir>/pgdata`` and the
#: postmaster writes its pid file inside that, so ``pgdata/postmaster.pid`` is
#: the path that exists. The guard below used to test the bare name, one level
#: too high, and therefore matched nothing on any machine: it counted zero
#: running clusters where every cluster was running, and the age check above
#: was left holding alone - which its own comment calls a belt to braces that
#: were not in fact fastened. Measured on this tree while writing this: of the
#: data dirs present, none carried a pid file at the bare name and every one
#: carried it under ``pgdata``.
#:
#: The bare name stays in the list. Erring towards leaving a directory alone
#: costs disk; erring the other way deletes a database somebody is serving out
#: of.
_PG_PIDFILE_RELPATHS = ("pgdata/postmaster.pid", "postmaster.pid")


def _pg_temp_root() -> Path:
    """Where this session's throwaway cluster lives.

    The system temp dir everywhere except a CI runner, which hands us a scratch
    directory of its own in ``RUNNER_TEMP`` and is the only place that has to be
    told apart. On GitHub's ``windows-latest`` the system temp dir is inside the
    elevated administrator's profile (``C:\\Users\\runneradmin\\AppData\\Local\\
    Temp``), and every Windows shard of the backend matrix died there before a
    single test ran: initdb reported ``could not create directory
    "<parent>": File exists`` for a parent that Python had just created and
    could still stat. ``RUNNER_TEMP`` on the same runner image works - the
    cross-OS e2e workflow boots this identical cluster from
    ``${{ runner.temp }}`` and its three windows-latest jobs are green - so the
    data dir moves there rather than the failure being chased through Win32.

    Set ``OE_TEST_PG_ROOT`` to override, which is the escape hatch if a machine
    ever has the same trouble with its own temp dir.
    """
    for candidate in (os.environ.get("OE_TEST_PG_ROOT"), os.environ.get("RUNNER_TEMP")):
        if candidate and candidate.strip():
            root = Path(candidate.strip())
            if root.is_dir():
                return root
    return Path(tempfile.gettempdir())


#: Resolved once, before the reaper runs, because both have to agree on it: a
#: reaper looking in the system temp dir while the session writes to
#: ``RUNNER_TEMP`` would silently stop collecting anything on CI.
_PG_TEMP_ROOT = _pg_temp_root()


def _reap_stale_pg_data_dirs() -> None:
    """Remove data dirs left by earlier runs that ended without cleaning up.

    Safe to run while other suites are in progress. A cluster writes
    ``pgdata/postmaster.pid`` when it starts and removes it on a clean stop, so
    a dir without one is a cluster that is definitively not running.

    A dir that still has a pid file used to be left alone on the reasoning that
    it belongs either to a live session or to a killed one whose postmaster is
    still up, and that this is not the place to decide which. Both of those
    cases have a live postmaster. The third does not: a postmaster that was
    force-killed leaves its pid file behind, and nothing ever comes back to
    remove it, so that dir was excluded from reaping permanently. Measured on
    this machine, that is where the leak the old docstring described was coming
    from, eleven dirs held out of reach by pid files naming processes that no
    longer existed.

    So the pid file is now read rather than merely counted, and the question is
    put to ``embedded_pg._pidfile_owner_is_live``, which is the same function
    the product's own boot and shutdown paths use. That matters more than
    reusing code: it answers yes when it cannot tell, and it treats a pid that
    is alive but belongs to something else as gone, which is the distinction a
    bare liveness check gets wrong on Windows often enough to matter. A dir is
    removed only on a definite no, and the minimum-age check still applies on
    top, so the bias the original comment asked for is intact: erring towards
    leaving a directory alone costs disk, erring the other way deletes a
    database somebody is serving out of.

    Dirs whose postmaster really is alive are still warned about rather than
    removed, because a growing count of those is a leak this function cannot
    fix. The two reasons for keeping a dir are counted apart and reported
    apart. They are not the same news: a live postmaster is a cluster this
    machine never shut down, while an unreadable pid file is a dir nothing can
    currently judge, and reporting the second as the first would describe a
    half-written file as a running database.

    The warning is a ``warnings.warn`` and not a print on purpose. pytest
    captures stdout and stderr from conftest import and shows them only when
    something fails, so a print here is swallowed on exactly the green runs
    that are quietly filling the disk. Warnings get their own summary whatever
    the outcome.
    """
    import shutil
    import time
    import warnings

    from app.core import embedded_pg

    root = _PG_TEMP_ROOT
    now = time.time()
    removed = 0
    unreadable = 0
    still_running = 0
    for entry in root.glob("oe-tests-pg-*"):
        if not entry.is_dir():
            continue
        try:
            holder = next((entry / rel for rel in _PG_PIDFILE_RELPATHS if (entry / rel).exists()), None)
            if holder is not None:
                pid = embedded_pg._read_pidfile_pid(holder.parent)
                # An unreadable pid file says nothing, so it keeps its dir.
                if pid is None:
                    unreadable += 1
                    continue
                if embedded_pg._pidfile_owner_is_live(holder.parent, pid):
                    still_running += 1
                    continue
            if now - entry.stat().st_mtime < _PG_REAP_MIN_AGE_SECONDS:
                continue
        except OSError:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            removed += 1
    if still_running or unreadable:
        parts = []
        if still_running:
            parts.append(
                f"{still_running} are still served by a live postmaster. Each of those is a "
                "cluster this machine never shut down; they hold their own disk until the "
                "process dies"
            )
        if unreadable:
            parts.append(
                f"{unreadable} carry a pid file this run could not read, so nothing is known "
                "about them and they were kept"
            )
        warnings.warn(
            f"embedded PostgreSQL: reaped {removed} abandoned data dir(s), but " + "; ".join(parts) + ".",
            stacklevel=2,
        )


if not os.environ.get("DATABASE_URL", "").strip():
    import atexit
    import secrets

    from app.core import embedded_pg

    _reap_stale_pg_data_dirs()
    # NAMED, NOT CREATED, and deliberately not ``mkdtemp``. ``boot()`` already
    # does ``mkdir(parents=True, exist_ok=True)`` on ``<dir>/pgdata``, so it
    # builds this whole chain itself - which is exactly the shape the green
    # windows-latest e2e jobs use, where OE_DATA_DIR names a directory nothing
    # has created yet. ``mkdtemp`` differs in creating the parent up front with
    # mode 0o700, and that parent is the one initdb named in the Windows CI
    # failure. Do not add a ``mkdir`` back here for safety: it would put the
    # pre-created parent back and undo half of this fix. The name is random for
    # the same reason mkdtemp's is - concurrent suites on one machine must not
    # share a cluster.
    _PG_DATA_DIR = _PG_TEMP_ROOT / f"oe-tests-pg-{secrets.token_hex(8)}"
    if not embedded_pg.boot(_PG_DATA_DIR):
        raise RuntimeError(
            "could not boot embedded PostgreSQL for the test session; set "
            "DATABASE_URL to point the suite at an external PostgreSQL instead"
        )
    # One cluster serves the whole session, so the application's shutdown handler
    # must leave it alone: without this pin the first test that exercises the app
    # lifespan stops the postmaster and every test after it errors on connect.
    embedded_pg.retain()

    def _stop_and_remove_cluster() -> None:
        """Stop the postmaster, then take its data dir with it.

        Stopping is not enough on its own. The dir is ours, this session named
        it, and nothing else will ever come for it. This does not run
        when the process is killed outright, which is what the reaper above is
        for: between them, a clean run leaves nothing and a killed run is
        cleared by whichever run comes next.
        """
        import shutil

        embedded_pg.shutdown(force=True)
        shutil.rmtree(_PG_DATA_DIR, ignore_errors=True)

    atexit.register(_stop_and_remove_cluster)

# ── Bound abandoned transactions on the test database ──────────────────────
# `lock_timeout` makes the VICTIM of a leaked transaction fail fast, which is
# what we want for readability, but it does nothing about the culprit: the
# abandoned transaction stays open and waits for the next victim. Only
# `idle_in_transaction_session_timeout` removes it, and it appeared nowhere in
# this tree.
#
# Set it on the DATABASE rather than in a fixture so it covers every connection
# the suite opens, including ones opened by application code rather than by a
# test, which is where the leak we chased actually came from.
#
# 300 seconds. It has to be far above any legitimate idle gap - a session sits
# "idle in transaction" for the whole time a test does Python work between
# queries, and that is normal - and far below the 900s per-test timeout that
# used to kill the nightly process, so a leak cannot outlive the test that made
# it by enough to matter. Nothing here should ever reach it; if something does,
# the kill is the report.
_IDLE_IN_TRANSACTION_TIMEOUT_S = 300


def _bound_idle_transactions() -> None:
    """Bound idle transactions on the MAINTENANCE database, and read it back.

    Which database this reaches is the whole of its scope, so it is named here
    rather than left to be inferred. The URL below is ``DATABASE_SYNC_URL`` (or
    ``DATABASE_URL``), which names the cluster's own database - ``postgres`` on
    the embedded cluster - and ``ALTER DATABASE ... SET`` binds to that one
    database alone. It does NOT reach ``oe_test_unit`` or the per-test clones
    that ``tests/_pg.py`` hands out: per-database settings live in
    ``pg_db_role_setting`` keyed by database OID, so they are neither inherited
    by a ``CREATE DATABASE ... TEMPLATE`` clone nor shared between databases.
    Measured: with this in force, ``oe_test_unit`` and a fresh clone both read
    ``0`` for it. Those databases carry their own bounds, set in
    ``tests/_pg.py`` by ``_bound_timeouts``.

    This is still worth doing, because ``app.database.engine`` is built from the
    same ``DATABASE_URL``, so the application's own sessions live on exactly the
    database this covers. It is one net of two, not the net for the suite.

    Set it, then READ IT BACK - an unverified guard is not a guard.

    ``ALTER DATABASE ... SET`` lands only for sessions opened afterwards, and a
    silent failure here would look exactly like success: nothing raises, nothing
    logs, and the leak we are bounding stays unbounded. So this reconnects and
    asks the server what the value actually is, and says so loudly when the two
    disagree. It warns rather than raises because a managed PostgreSQL may
    refuse ALTER DATABASE to a non-owner, and a suite that cannot set this
    should still run - just not while believing it did.
    """
    import warnings

    try:
        import psycopg2
        from sqlalchemy.engine.url import make_url

        # DATABASE_SYNC_URL is what the psycopg2 helpers in tests/_pg.py use,
        # but CI supplies only DATABASE_URL, so fall back to it.
        raw = os.environ.get("DATABASE_SYNC_URL") or os.environ["DATABASE_URL"]
        url = make_url(raw)
        database = url.database
        libpq = url.set(drivername="postgresql").render_as_string(hide_password=False)

        conn = psycopg2.connect(libpq)
        try:
            conn.autocommit = True
            conn.cursor().execute(
                f'ALTER DATABASE "{database}" SET idle_in_transaction_session_timeout = '
                f"'{_IDLE_IN_TRANSACTION_TIMEOUT_S}s'"
            )
        finally:
            conn.close()

        # A NEW session, because that is the only kind the setting reaches.
        check = psycopg2.connect(libpq)
        try:
            cur = check.cursor()
            cur.execute("SHOW idle_in_transaction_session_timeout")
            observed = cur.fetchone()[0]
        finally:
            check.close()
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        warnings.warn(
            f"could not bound idle transactions on the maintenance database: {exc!r}. "
            "A leaked transaction on the application engine will survive until the "
            "connection closes.",
            stacklevel=2,
        )
        return

    if observed in ("0", "0ms"):
        warnings.warn(
            "ALTER DATABASE reported success but idle_in_transaction_session_timeout "
            f"reads back as {observed!r}; the bound is NOT in force.",
            stacklevel=2,
        )


_bound_idle_transactions()


# ── Rate-limiter relaxation for tests ──────────────────────────────────────
# The integration suites repeatedly hit ``/auth/register`` and ``/auth/login``
# from the same in-process ``test`` client. The default 10/min login limit
# (and 100/min API limit) is fine for production but makes whole-suite
# runs flake with 429s long before the relevant assertion fires. Tests
# don't measure rate-limiter behaviour itself (those tests stand up their
# own ``RateLimiter(...)`` instance), so we lift the bucket here.
os.environ.setdefault("LOGIN_RATE_LIMIT", "10000")
os.environ.setdefault("API_RATE_LIMIT", "100000")
os.environ.setdefault("AI_RATE_LIMIT", "10000")
os.environ.setdefault("REGISTER_RATE_LIMIT_PER_HOUR", "100000")

# ── Debug on for the suite ─────────────────────────────────────────────────
# APP_DEBUG defaults to False so an installed server never echoes request
# input in 422 bodies. The suite was written against the verbose shape (and
# path-only validation errors answer 400 instead of 422 without debug), so it
# keeps running with debug on. Tests that pin the production shape set
# APP_DEBUG themselves.
os.environ.setdefault("APP_DEBUG", "true")
# The field-diary suites drive the magic-link flow from the plaintext token
# and PIN in the response. Settings are cached for the whole session, so the
# per-module env line in those files is not enough on its own once another
# module built the settings first; the flag is set here for the suite.
os.environ.setdefault("EXPOSE_DEV_AUTH_SECRETS", "true")

# ── Open registration for the suite ────────────────────────────────────────
# The default registration mode is "admin-approve" (every registrant after the
# first bootstrap admin is created inactive and cannot log in). The integration
# suites register a fresh user per module and immediately log in, so under the
# default they get a 401 and the auth fixture errors out. Open mode keeps every
# registrant active. The two mode-specific suites (test_register_modes,
# test_register_bootstrap) set the mode themselves and are unaffected.
os.environ.setdefault("REGISTRATION_MODE", "open")

# ── Skip demo account seeding for tests ───────────────────────────────────
# The startup lifespan creates demo@openconstructionerp.com (and two sibling
# accounts) every time create_app() boots. Although has_admin() is designed
# to exclude those demo emails from the bootstrap check, the seeding still
# costs time and writes rows that can interact with per-module auth fixtures.
# test_demo_login_endpoint.py sets SEED_DEMO=true inside its own fixture and
# is unaffected. All other suites work without the demo accounts.
os.environ.setdefault("SEED_DEMO", "false")

# ── Fast app startup for tests ─────────────────────────────────────────────
# Each integration module stands up its own FastAPI app via create_app() and
# runs the full lifespan. In production that lifespan connects to the vector
# backend, loads the embedding model (~35s) and installs the flagship showcase
# project (6640 elements + ~16MB of geometry). None of that is needed by the
# test suite, and paid per module it is the dominant cost of the whole run.
# This flag skips the vector init/warm-up and the flagship seed; vector
# endpoints still work because the embedder loads lazily on first use.
os.environ.setdefault("OE_TEST_FAST_STARTUP", "1")

# ── NullPool for the shared app engine under tests ─────────────────────────
# pytest-asyncio runs each test in its own event loop. asyncpg connections are
# loop-bound, so a connection pooled on one test's loop and reused on the next
# raises "Task ... attached to a different loop". The production engine uses a
# sized QueuePool; here we tell the engine factory to use NullPool so every
# checkout opens a fresh connection on the current loop. Must be set before the
# first ``import app...`` below builds the engine. The fast per-test isolation
# helpers in ``tests/_pg.py`` already use NullPool for the same reason.
os.environ.setdefault("OE_TEST_NULLPOOL", "1")

import pytest  # noqa: E402

import app.core.audit  # noqa: E402,F401

# Audit-log model needs to be registered with Base.metadata before
# create_all() so the FSM audit-log writes have somewhere to land.
import app.core.audit_log  # noqa: E402,F401
import app.modules.bim_hub.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.eac.models  # noqa: E402,F401

# ── Eagerly register all module ORM tables ─────────────────────────────────
# Without this, test-order pollution can leave Base.metadata holding a
# fragmentary view: e.g. a test that imports `schedule.models` but not
# `projects.models` registers `oe_schedule_schedule` with a dangling FK
# to the unloaded `oe_projects_project`. The next test that calls
# `Base.metadata.create_all()` then fails with NoReferencedTableError.
# Importing every module's models here once before any test runs
# guarantees a coherent metadata snapshot regardless of suite order.
import app.modules.projects.models  # noqa: E402,F401
import app.modules.schedule.models  # noqa: E402,F401
import app.modules.takeoff.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401

# ── Synchronous event publishing in tests ──────────────────────────────────
# Production wraps ``event_bus.publish`` in ``asyncio.create_task`` via
# :meth:`EventBus.publish_detached` so the database connection isn't
# held by the request session while subscribers open theirs. Tests, however,
# typically do ``await service.X()`` then immediately assert on a captured
# events fixture — the scheduled task hasn't yielded to the loop yet. To
# preserve pre-v2.6.47 sync semantics for tests we shim ``publish_detached``
# to use an immediate ``ensure_future`` + a ``run`` of pending callbacks
# before returning, so when control comes back to the test's next line the
# event has already fanned out to subscribers.
from app.core.events import event_bus as _event_bus  # noqa: E402


# Which subscribers must be driven by the event loop rather than stepped by hand
# ---------------------------------------------------------------------------
# This used to be a set of three handler names, kept by hand and documented with
# "keep this in sync with every event_bus.subscribe('*', ...) in app/". It went
# stale the way every such list does. It named only the three wildcard
# subscribers, so all 150-odd *per-event* subscribers under app/ - each of which
# opens its own database session, because that is the entire reason
# ``publish_detached`` exists - were classified as pure and hand-stepped. One
# leaked ``boq.position.created`` subscriber was enough to suspend a hand-stepped
# coroutine inside a live asyncpg read and corrupt the session-scoped loop, and
# every later test in that process then died in ``selectors.py`` without ever
# reaching application code.
#
# The classification is therefore structural now, and derived from something the
# author of a new subscriber cannot forget to update: the module the handler was
# defined in. Anything defined under ``app.`` may do real I/O and is never
# hand-stepped. A new ``event_bus.subscribe`` anywhere in the application is
# covered the day it lands, and no test needs to know it exists.
def _is_application_subscriber(handler: object) -> bool:
    """True when *handler* was defined inside the application package."""
    module = getattr(handler, "__module__", "") or ""
    return module == "app" or module.startswith("app.")


def _needs_event_loop(handler: object) -> bool:
    """True when stepping *handler* by hand would suspend the publish coroutine."""
    if _is_application_subscriber(handler):
        return True
    # A plain (non-async) subscriber is dispatched through ``asyncio.to_thread``
    # by :meth:`EventBus.publish`, which suspends the publish coroutine even
    # though the handler itself touches nothing. Ask the same question the bus
    # asks, so the two can never disagree.
    return not inspect.iscoroutinefunction(handler)


# Set per test by :func:`_isolate_unit_tests_from_leaked_subscribers` below.
_unit_test_scope = False

# Keep strong references to scheduled publish tasks so the loop can't garbage-
# collect them mid-flight (which would raise "Task was destroyed but it is
# pending"). The done-callback drops each task once it finishes.
_pending_event_tasks: set = set()


def _schedule_publish(coro):
    import asyncio as __asyncio

    task = __asyncio.ensure_future(coro)
    _pending_event_tasks.add(task)
    task.add_done_callback(_pending_event_tasks.discard)
    return task


def _drive_in_line(name, data, source_module, named, wildcard):
    """Fan *name* out synchronously to the vetted handler set, and only to it.

    Every handler passed here answered ``False`` to :func:`_needs_event_loop`, so
    :meth:`EventBus.publish` runs start to finish on a single ``send(None)`` and
    the synchronous contract unit tests are written against holds.

    The bus registries hold the vetted set for the duration of that one step, so
    ``publish`` fans out to exactly what we vetted rather than to whatever is on
    the bus. The window is invisible: the step is straight-line synchronous code
    with no suspension point, so nothing else in the process can observe it. The
    ``_handlers`` mapping itself is kept (only the one key is borrowed) so the
    bus never changes shape.
    """
    import asyncio as __asyncio

    fut: __asyncio.Future = __asyncio.Future()
    had_key = name in _event_bus._handlers
    saved_named = _event_bus._handlers.get(name)
    saved_wildcard = _event_bus._wildcard_handlers
    _event_bus._handlers[name] = named
    _event_bus._wildcard_handlers = wildcard
    try:
        coro = _event_bus.publish(name, data, source_module=source_module)
        try:
            coro.send(None)
        except StopIteration as stop:
            fut.set_result(stop.value)
            return fut
        except BaseException as exc:
            fut.set_exception(exc)
            return fut
    finally:
        if had_key:
            _event_bus._handlers[name] = saved_named
        else:
            _event_bus._handlers.pop(name, None)
        _event_bus._wildcard_handlers = saved_wildcard

    # Unreachable by construction, and loud rather than silent if construction
    # ever slips. The old code closed the half-stepped coroutine here and
    # re-published, which is unsound twice over: ``close()`` throws GeneratorExit
    # into a coroutine that may be suspended inside asyncpg, abandoning a socket
    # that is still registered on the session-scoped loop, and the re-publish
    # fires again every handler that already completed. Closing is safe *here*
    # because no application subscriber can be in this set - that is what
    # :func:`_needs_event_loop` guarantees - so what is left is a test-owned
    # handler that awaited something, and the test author is the one who can fix
    # it. Fail at the publish site rather than poisoning a later test.
    coro.close()
    raise RuntimeError(
        f"event {name!r} suspended while being published in line; handlers "
        f"{[getattr(h, '__qualname__', repr(h)) for h in named + wildcard]} were "
        "all classified as unable to suspend. A subscriber registered by a test "
        "awaited real I/O: subscribe it from the application package, or make it "
        "complete without awaiting."
    )


def _sync_publish_detached(name, data=None, source_module=None):
    """Test-time replacement for :meth:`EventBus.publish_detached`.

    Two regimes, chosen by :func:`_needs_event_loop` over the handlers actually
    registered for the event, in *both* bus registries:

    * **Unit tests** subscribe a pure-Python recorder to the bus, call a service
      that fires ``publish_detached`` and then immediately assert on the captured
      events. Nothing on that path does I/O, so the publish coroutine is driven
      to completion in line, preserving that synchronous contract exactly.

    * **Integration tests** run the full app, whose subscribers open their own DB
      session. Those do real asyncpg I/O; stepping them by hand corrupts the
      connection. So the publish is scheduled as a detached task, exactly as
      production does, and the loop drives the I/O correctly.

    Either way an awaitable is returned for callers/tests that use it.
    """
    named = list(_event_bus._handlers.get(name, ()))
    wildcard = list(_event_bus._wildcard_handlers)
    if _unit_test_scope:
        # A unit test never started the app, so every application subscriber on
        # the bus is leakage from some earlier test that imported a module and
        # did not put the bus back. Leave it registered - tests that assert on
        # the wiring need to see it - but keep it out of this publish, so it
        # neither runs nor decides the regime.
        named = [h for h in named if not _is_application_subscriber(h)]
        wildcard = [h for h in wildcard if not _is_application_subscriber(h)]

    if any(_needs_event_loop(h) for h in named + wildcard):
        try:
            # Deliberately the unfiltered publish: once the loop is driving it,
            # a leaked subscriber doing its own I/O is merely unwanted, never
            # corrupting, and re-deriving the fan-out here would duplicate
            # ``EventBus.publish`` in the harness.
            return _schedule_publish(_event_bus.publish(name, data, source_module=source_module))
        except RuntimeError:
            # No running loop (rare): ``publish_detached`` was called from plain
            # synchronous code. Nothing can drive a handler that suspends, and
            # hand-stepping one is the corruption this shim exists to prevent,
            # so deliver to the handlers that can complete in line and skip the
            # rest rather than half-running them.
            named = [h for h in named if not _needs_event_loop(h)]
            wildcard = [h for h in wildcard if not _needs_event_loop(h)]

    return _drive_in_line(name, data, source_module, named, wildcard)


_event_bus.publish_detached = _sync_publish_detached  # type: ignore[method-assign]


_LOCAL_HTTP_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1", "test", "testserver"})


@pytest.fixture(autouse=True)
def _no_outbound_http(request, monkeypatch):
    """Turn a real call to a third-party host into a named test failure.

    The suite is supposed to be hermetic, and mostly is - clients are mocked
    per test. But nothing enforced it, so a path that slipped past its mock
    just went out and left a line in the log that somebody had to notice. The
    nightly full run did exactly that: one ``POST https://api.anthropic.com``
    per night, answered 401 because the only key in play was the fixture's own
    ``sk-test-fake-key``. Harmless that time, and precisely the point - the
    same escape with a real key spends money, and either way it makes our runs
    depend on somebody else's availability.

    What counts as egress is the transport, not the hostname. A test that
    installs ``MockTransport`` or ``ASGITransport`` is hermetic no matter how
    real its base URL looks, and plenty of them point at the very vendor URLs
    the production client uses - judging by host would fail those for doing
    exactly the right thing. Resolving the transport the way httpx itself does
    also leaves PostgreSQL and any loopback service alone for free. Mark a test
    ``allow_network`` where reaching the network is the thing under test.
    """
    if request.node.get_closest_marker("allow_network"):
        return

    import httpx

    real_transports = (httpx.HTTPTransport, httpx.AsyncHTTPTransport)

    def _reject(url) -> None:
        raise RuntimeError(
            f"Outbound HTTP to {url.host} is blocked in tests: {url}. Mock the client, "
            "or mark the test `allow_network` if the call is the point."
        )

    def _check(client, url) -> None:
        resolve = getattr(client, "_transport_for_url", None)
        transport = resolve(url) if resolve is not None else getattr(client, "_transport", None)
        if isinstance(transport, real_transports):
            _reject(url)

    send = httpx.Client.send
    asend = httpx.AsyncClient.send

    # The first parameter has to keep httpx's own name. ``Client.stream`` and
    # ``AsyncClient.stream`` call ``self.send(request=request, ...)`` by
    # keyword, so a replacement that calls it anything else - ``request_``, to
    # leave this fixture's own ``request`` argument visible - takes the request
    # through ``**kwargs`` and raises "missing 1 required positional argument"
    # on every streaming call in the suite. That is what the 2026-09-22 nightly
    # reported four times in tests/integration/test_issue_138_openrouter_sse_e2e.py,
    # and it reads like a product bug rather than a guard that renamed an
    # argument. Shadowing the fixture's ``request`` inside these two functions
    # costs nothing: the marker it is needed for was read at the top.
    def _guarded_send(self, request, *args, **kwargs):
        _check(self, request.url)
        return send(self, request, *args, **kwargs)

    async def _guarded_asend(self, request, *args, **kwargs):
        _check(self, request.url)
        return await asend(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", _guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", _guarded_asend)

    # A handful of modules still reach for urllib rather than httpx, and they
    # reach for it three different ways. Patching only `urlopen` would leave
    # two of them open: `urlretrieve` never goes near it, and a custom opener
    # from `build_opener` calls `OpenerDirector.open` directly.
    import urllib.request

    def _check_url(target) -> None:
        # urllib exposes no transport to inspect, so host is all there is.
        url = httpx.URL(str(getattr(target, "full_url", target)))
        if (url.host or "").lower() not in _LOCAL_HTTP_HOSTS:
            _reject(url)

    opener_open = urllib.request.OpenerDirector.open
    urlretrieve = urllib.request.urlretrieve

    def _guarded_open(self, fullurl, *args, **kwargs):
        _check_url(fullurl)
        return opener_open(self, fullurl, *args, **kwargs)

    def _guarded_urlretrieve(url, *args, **kwargs):
        _check_url(url)
        return urlretrieve(url, *args, **kwargs)

    # `urlopen` delegates to the global opener, so guarding `OpenerDirector.open`
    # covers it and every custom opener along with it.
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _guarded_open)
    monkeypatch.setattr(urllib.request, "urlretrieve", _guarded_urlretrieve)


@pytest.fixture(autouse=True)
def _isolate_unit_tests_from_leaked_subscribers(request):
    """Keep a leaked application subscriber out of a unit test's publishes.

    ``_sync_publish_detached`` above picks its regime from what is on the bus:
    with a subscriber that does real I/O registered it schedules the publish on
    the loop, and every pure recorder goes with it. That is correct for an
    integration test, which starts the app and wants those handlers to run, and
    wrong for a unit test, which subscribes a recorder and asserts on it on the
    very next line with no await in between.

    Nothing removes those handlers once registered. So a single test that
    subscribed one and did not unsubscribe silently flipped every unit test that
    ran after it onto the loop regime, and they failed on an empty recorder in
    an unrelated module, hundreds of tests away from the cause and green again
    the moment that file was run on its own. ``test_dashboards_t01_service.py``
    was the one that surfaced it, on ``assert 'snapshot.created' in []``.

    Unit tests never start the app, so for them these handlers are always
    leakage. This fixture marks the scope; the exclusion itself happens in
    ``_sync_publish_detached`` and covers **both** registries, the per-event
    ``_handlers`` as well as the ``"*"`` ``_wildcard_handlers``. The predecessor
    of this fixture looked only at the wildcard list, which is how a leaked
    ``boq.position.created`` subscriber survived and got hand-stepped into a live
    asyncpg read, corrupting the session-scoped loop for the rest of the process.

    Excluding at the publish boundary rather than deleting from the bus is
    deliberate. Deleting would make every test that asserts on the wiring
    order-dependent: ``test_doc_assistant_wiring.py`` imports its events modules
    *inside* the test body, so run alone it re-registers after the deletion and
    passes, and run in a chunk the import is a no-op and it fails. Shipping a
    fresh instance of the bug class we are removing is not a fix. So the bus
    keeps its handlers and the publish simply does not fan out to them.
    """
    global _unit_test_scope

    path = str(getattr(request.node, "fspath", "")).replace("\\", "/")
    previous = _unit_test_scope
    _unit_test_scope = "/tests/unit/" in path
    try:
        yield
    finally:
        _unit_test_scope = previous


@pytest.fixture(autouse=True)
def _keep_validation_rules_registered():
    """Guard the process-global validation registry against cross-test pollution.

    A few suites swap the module-level ``validation_engine`` or replace/empty its
    registry to exercise edge cases; without a restore, a later test that runs a
    real rule set - inline BOQ-import validation, the pipeline graph gate - finds
    an empty registry and reports every requested set as ``unsupported``. After
    each test put the engine and its registry back, and re-register the built-ins
    if they went missing (``register_builtin_rules`` is idempotent).

    Registering on the way IN matters just as much, and used to be missing. The
    application calls ``register_builtin_rules`` from its lifespan, which no test
    process starts, so the registry began every run empty and was populated only
    as a side effect of this fixture's teardown. The first test in the process to
    ask for a rule set therefore got nothing: the engine marks an absent set as
    unsupported and returns a clean report, which is indistinguishable from the
    rules having run and found no problem. Whether a validation test was real then
    depended on where pytest happened to order it. Measured 2026-07-27 with
    ``tests/unit/test_validation_registry_populated.py``, which saw the registry
    holding ``[]`` at the first test and every built-in set present by the second.

    Both calls used to be guarded by ``"boq_quality" not in list_rule_sets()``,
    and that sentinel is not a property of the built-in pack alone. Modules
    register into the same shared set name as an import side effect:
    ``app.modules.esg.validators`` registers its rule into
    ``["esg_site", "boq_quality"]`` when the module is imported. In a process
    that imported it first, the sentinel reads as satisfied while ``din276``,
    ``gaeb`` and the rest of the built-ins are still absent, so the repair never
    runs and the engine answers a request for them with an empty ``skipped``
    report that is indistinguishable from a pass. That is the shape of the
    2026-08-21 shard failure in ``tests/unit/test_boq_import_validation.py``.
    Register unconditionally instead. The call is idempotent, it costs 0.1 ms,
    and it is what the product itself does at all three of its call sites.
    """
    import app.core.validation.engine as _eng
    from app.core.validation.rules import register_builtin_rules

    engine = _eng.validation_engine
    registry = engine.registry
    register_builtin_rules()
    try:
        yield
    finally:
        _eng.validation_engine = engine
        engine.registry = registry
        register_builtin_rules()


@pytest.fixture
def sample_boq_data():
    """Sample BOQ data for validation tests."""
    return {
        "positions": [
            {
                "id": "pos-001",
                "ordinal": "01.01.0010",
                "description": "Stahlbeton C30/37 für Fundamente",
                "unit": "m3",
                "quantity": 44.30,
                "unit_rate": 185.00,
                "classification": {"din276": "330", "masterformat": "03 30 00"},
            },
            {
                "id": "pos-002",
                "ordinal": "01.01.0020",
                "description": "Schalung für Fundamente",
                "unit": "m2",
                "quantity": 120.0,
                "unit_rate": 42.50,
                "classification": {"din276": "330"},
            },
            {
                "id": "pos-003",
                "ordinal": "01.02.0010",
                "description": "Betonstahl BSt 500 S",
                "unit": "kg",
                "quantity": 3200.0,
                "unit_rate": 1.85,
                "classification": {"din276": "330"},
            },
        ]
    }


@pytest.fixture
def sample_boq_data_with_issues():
    """BOQ data with validation issues."""
    return {
        "positions": [
            {
                "id": "pos-001",
                "ordinal": "01.01.0010",
                "description": "Good position",
                "unit": "m3",
                "quantity": 10.0,
                "unit_rate": 100.0,
                "classification": {"din276": "330"},
            },
            {
                "id": "pos-002",
                "ordinal": "01.01.0010",  # DUPLICATE ordinal
                "description": "",  # MISSING description
                "unit": "m2",
                "quantity": 0,  # ZERO quantity
                "unit_rate": 0,  # ZERO rate
                "classification": {},  # MISSING classification
            },
            {
                "id": "pos-003",
                "ordinal": "01.02.0010",
                "description": "Overpriced item",
                "unit": "pcs",
                "quantity": 5.0,
                "unit_rate": 999999.0,  # ANOMALY
                "classification": {"din276": "999"},  # INVALID code
            },
        ]
    }


@pytest.fixture
def sample_cad_elements():
    """Sample CAD canonical format elements."""
    return [
        {
            "id": "elem_001",
            "category": "wall",
            "classification": {"din276": "330"},
            "geometry": {
                "type": "extrusion",
                "length_m": 12.43,
                "height_m": 3.0,
                "thickness_m": 0.24,
                "area_m2": 37.29,
                "volume_m3": 8.95,
            },
            "properties": {"material": "concrete_c30_37"},
            "quantities": {"area": 37.29, "volume": 8.95},
        },
        {
            "id": "elem_002",
            "category": "floor",
            "classification": {"din276": "350"},
            "geometry": {
                "type": "slab",
                "area_m2": 85.0,
                "thickness_m": 0.20,
                "volume_m3": 17.0,
            },
            "properties": {"material": "concrete_c25_30"},
            "quantities": {"area": 85.0, "volume": 17.0},
        },
    ]
