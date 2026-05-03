"""Shared test fixtures.

Test isolation
~~~~~~~~~~~~~~
Per ``feedback_test_isolation.md``: backend tests must NEVER touch the
production ``backend/openestimate.db``. Several integration suites
(``test_api_smoke``, ``test_boq_regression``, ``test_boq_import_safety``,
``test_boq_cycle_detection``, ``test_boq_cost_item_link``) construct the
FastAPI app via ``create_app()`` which imports ``app.database`` and
binds ``async_session_factory`` to whatever ``DATABASE_URL`` is set at
that moment — so the env var has to be redirected to a per-session temp
SQLite file *before* any ``from app...`` import runs.

Doing it here in ``tests/conftest.py`` (which pytest loads before any
test module) guarantees the override beats every test-module import
order, regardless of which suite is collected first. Tests that already
self-redirect (``test_tenant_isolation``, ``test_register_bootstrap``,
etc.) are still fine — they overwrite this with their own temp file.
"""

import os
import tempfile
from pathlib import Path

# ── Per-session SQLite isolation (must run before app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-tests-"))
_TMP_DB = _TMP_DIR / "session.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}")
os.environ.setdefault("DATABASE_SYNC_URL", f"sqlite:///{_TMP_DB.as_posix()}")

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

import pytest  # noqa: E402

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
import app.modules.eac.models  # noqa: E402,F401
import app.modules.bim_hub.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.takeoff.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401


# ── Synchronous event publishing in tests ──────────────────────────────────
# Production wraps ``event_bus.publish`` in ``asyncio.create_task`` via
# :meth:`EventBus.publish_detached` so the SQLite single-writer lock isn't
# held by the request session while subscribers open theirs. Tests, however,
# typically do ``await service.X()`` then immediately assert on a captured
# events fixture — the scheduled task hasn't yielded to the loop yet. To
# preserve pre-v2.6.47 sync semantics for tests we shim ``publish_detached``
# to use an immediate ``ensure_future`` + a ``run`` of pending callbacks
# before returning, so when control comes back to the test's next line the
# event has already fanned out to subscribers.
from app.core.events import event_bus as _event_bus  # noqa: E402


def _sync_publish_detached(name, data=None, source_module=None):
    """Test-time replacement for :meth:`EventBus.publish_detached`.

    Drives the publish coroutine to completion synchronously by stepping
    the coroutine until it would yield to wait for a real I/O future.
    All current subscribers are pure-Python (notifications/webhooks open
    their own sessions but the test fixtures never wire those for unit
    tests), so the coroutine runs to ``return`` on first ``send(None)``.
    Returns a completed Future for callers that ignore the return value.
    """
    import asyncio as __asyncio

    coro = _event_bus.publish(name, data, source_module=source_module)
    fut: __asyncio.Future = __asyncio.Future()
    try:
        # Drive the coroutine. Pure subscribers (no real I/O) finish in one
        # send. Anything that does try to yield to the loop falls back to
        # ``ensure_future`` so we never hang the test.
        coro.send(None)
    except StopIteration as stop:
        fut.set_result(stop.value)
        return fut
    except BaseException as exc:
        fut.set_exception(exc)
        return fut
    # Coroutine yielded — fall back to scheduling so the loop can finish it.
    try:
        return __asyncio.ensure_future(coro)
    except RuntimeError:
        # No running loop in sync test context.
        fut.set_result(None)
        return fut


_event_bus.publish_detached = _sync_publish_detached  # type: ignore[method-assign]


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
