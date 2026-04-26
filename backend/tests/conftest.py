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
