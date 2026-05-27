"""Issue #111 — FX-aware structured rollup + frozen FX export appendix.

#131 fixed the grid path (``groupPositionsIntoSections``): a position
priced in a non-base currency is converted into the project base before
it lands in a section subtotal. The *same* defect lived in
``BOQService.get_boq_structured`` — the function that powers the CSV /
Excel / PDF / GAEB exporters — which summed foreign ``total`` strings
straight into the base-currency Direct Cost / Grand Total. These tests
pin the export-side fix:

* the pure converter ``_position_total_in_base`` / ``_position_currency``
* ``get_boq_structured`` converts section subtotal + direct cost +
  grand total via the project FX table
* a foreign currency with NO configured rate is summed in its own units
  (never zeroed) so a forgotten rate degrades visibly, not silently
* ``get_export_fx`` returns the frozen ``(base, {code: rate})`` the
  exporters embed as an audit appendix

Test isolation (``feedback_test_isolation.md``): a per-test temp SQLite
file, never the production ``openestimate.db``.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_structured_fx.py -v --tb=short
"""

from __future__ import annotations

import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.boq.service import (
    BOQService,
    _position_currency,
    _position_total_in_base,
)

OWNER_ID = uuid.uuid4()


def _register_models() -> None:
    import app.modules.boq.models  # noqa: F401
    import app.modules.catalog.models  # noqa: F401
    import app.modules.costs.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    tmp_db = Path(tempfile.mkdtemp()) / "structured_fx.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"o-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="O",
            )
        )
        await s.flush()
        await s.commit()
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


# ── Pure converter ───────────────────────────────────────────────────────


def test_position_total_in_base_converts_foreign():
    # 500 USD at 1.10 EUR per USD → 550 EUR.
    out = _position_total_in_base("500", "USD", {"USD": "1.10"}, "EUR")
    assert out == Decimal("550.00")


def test_position_total_in_base_base_currency_passthrough():
    assert _position_total_in_base("1000", "EUR", {"USD": "1.10"}, "EUR") == Decimal("1000")
    # No currency on the row → treated as base.
    assert _position_total_in_base("1000", "", {"USD": "1.10"}, "EUR") == Decimal("1000")


def test_position_total_in_base_missing_rate_not_zeroed():
    # GBP has no configured rate — must be summed in its own units, never 0.
    assert _position_total_in_base("800", "GBP", {"USD": "1.10"}, "EUR") == Decimal("800")


def test_position_total_in_base_garbage_total_is_zero():
    assert _position_total_in_base("not-a-number", "USD", {"USD": "1.1"}, "EUR") == (Decimal("0"))


def test_position_currency_priority():
    class _P:
        metadata_ = {"position_currency": "JPY"}

    assert _position_currency(_P()) == "JPY"

    class _Q:
        metadata_ = {"currency": "usd", "position_currency": "JPY"}

    # explicit ``currency`` wins, normalised upper-case
    assert _position_currency(_Q()) == "USD"

    class _R:
        metadata_ = {}

    assert _position_currency(_R()) == ""


# ── Service-level rollup ─────────────────────────────────────────────────


async def _make_boq_with_mixed_currency(session, fx_rates):
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name="FX Rollup",
            owner_id=OWNER_ID,
            currency="EUR",
            fx_rates=fx_rates,
        )
    )
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="FX BOQ")
    session.add(boq)
    await session.flush()

    section = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="01",
        description="Section A",
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
        sort_order=0,
    )
    session.add(section)
    await session.flush()

    # EUR leaf (base currency, no metadata currency).
    session.add(
        Position(
            id=uuid.uuid4(),
            boq_id=boq.id,
            parent_id=section.id,
            ordinal="01.001",
            description="EUR work",
            unit="m2",
            quantity="100",
            unit_rate="10",
            total="1000",
            sort_order=1,
        )
    )
    # USD leaf — priced in USD via metadata.currency.
    session.add(
        Position(
            id=uuid.uuid4(),
            boq_id=boq.id,
            parent_id=section.id,
            ordinal="01.002",
            description="USD work",
            unit="m2",
            quantity="50",
            unit_rate="10",
            total="500",
            metadata_={"currency": "USD"},
            sort_order=2,
        )
    )
    await session.commit()
    return boq


@pytest.mark.asyncio
async def test_get_boq_structured_converts_foreign_currency(session):
    boq = await _make_boq_with_mixed_currency(session, [{"code": "USD", "rate": "1.10", "label": "US Dollar"}])
    service = BOQService(session)
    structured = await service.get_boq_structured(boq.id)

    # 1000 EUR + (500 USD × 1.10) = 1550 EUR — NOT a raw 1500.
    assert len(structured.sections) == 1
    assert structured.sections[0].subtotal == pytest.approx(1550.0)
    assert structured.direct_cost == pytest.approx(1550.0)
    assert structured.grand_total == pytest.approx(1550.0)


@pytest.mark.asyncio
async def test_get_boq_structured_missing_rate_not_zeroed(session):
    # USD has a rate; the project also has a position implicitly in EUR.
    # Swap the USD leaf's currency to an unconfigured GBP via no GBP rate.
    boq = await _make_boq_with_mixed_currency(session, [{"code": "CHF", "rate": "0.95", "label": "Swiss Franc"}])
    service = BOQService(session)
    structured = await service.get_boq_structured(boq.id)

    # USD has no configured rate (only CHF) → the 500 USD leaf is summed
    # in its own units, never dropped: 1000 + 500 = 1500.
    assert structured.direct_cost == pytest.approx(1500.0)


@pytest.mark.asyncio
async def test_get_export_fx_returns_frozen_table(session):
    boq = await _make_boq_with_mixed_currency(
        session,
        [
            {"code": "USD", "rate": "1.10", "label": "US Dollar"},
            {"code": "gbp", "rate": "1.18", "label": "Pound"},
        ],
    )
    service = BOQService(session)
    base, fx_map = await service.get_export_fx(boq.id)
    assert base == "EUR"
    assert fx_map == {"USD": "1.10", "GBP": "1.18"}
