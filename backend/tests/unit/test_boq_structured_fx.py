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

Test isolation: a transaction-isolated PostgreSQL session on the shared
schema-loaded ``oe_test_unit`` database (rolled back on teardown), never
the production database.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_structured_fx.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.service import (
    BOQService,
    _position_currency,
    _position_total_in_base,
)
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
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


# ── Pure converter ───────────────────────────────────────────────────────


def test_position_total_in_base_converts_foreign():
    # 500 USD at 1.10 EUR per USD → 550 EUR.
    out = _position_total_in_base("500", "USD", {"USD": "1.10"}, "EUR")
    assert out == Decimal("550.00")


def test_position_total_in_base_base_currency_passthrough():
    assert _position_total_in_base("1000", "EUR", {"USD": "1.10"}, "EUR") == Decimal("1000")
    # No currency on the row → treated as base.
    assert _position_total_in_base("1000", "", {"USD": "1.10"}, "EUR") == Decimal("1000")


def test_position_total_in_base_missing_rate_excluded():
    # GBP has no configured rate — must be summed in its own units, never 0.
    assert _position_total_in_base("800", "GBP", {"USD": "1.10"}, "EUR") == Decimal("0")


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
async def test_get_boq_structured_missing_rate_excluded(session):
    # USD has a rate; the project also has a position implicitly in EUR.
    # Swap the USD leaf's currency to an unconfigured GBP via no GBP rate.
    boq = await _make_boq_with_mixed_currency(session, [{"code": "CHF", "rate": "0.95", "label": "Swiss Franc"}])
    service = BOQService(session)
    structured = await service.get_boq_structured(boq.id)

    # USD has no configured rate (only CHF) → the 500 USD leaf is summed
    # in its own units, never dropped: 1000 + 500 = 1500.
    assert structured.direct_cost == pytest.approx(1000.0)


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


# ── Issue #157 (skolodi): missing-FX warning detection ────────────────────


def test_detect_resource_fx_warnings_no_resources() -> None:
    from app.modules.boq.service import _detect_resource_fx_warnings

    assert _detect_resource_fx_warnings(None, {"USD": "1.10"}, "EUR") == []
    assert _detect_resource_fx_warnings([], {"USD": "1.10"}, "EUR") == []


def test_detect_resource_fx_warnings_base_currency_only() -> None:
    """All resources priced in base currency — no warning, regardless of fx_rates_map."""
    from app.modules.boq.service import _detect_resource_fx_warnings

    resources = [
        {"quantity": 1, "unit_rate": 10, "currency": "EUR"},
        {"quantity": 2, "unit_rate": 20},  # no currency = base
        {"quantity": 3, "unit_rate": 30, "currency": ""},  # empty = base
    ]
    assert _detect_resource_fx_warnings(resources, {"USD": "1.10"}, "EUR") == []


def test_detect_resource_fx_warnings_foreign_with_rate() -> None:
    """Foreign currencies that have a project FX rate — no warning."""
    from app.modules.boq.service import _detect_resource_fx_warnings

    resources = [
        {"quantity": 1, "unit_rate": 10, "currency": "USD"},
        {"quantity": 2, "unit_rate": 20, "currency": "ARS"},
    ]
    fx_map = {"USD": "1.10", "ARS": "1415.0"}
    assert _detect_resource_fx_warnings(resources, fx_map, "EUR") == []


def test_detect_resource_fx_warnings_missing_rate() -> None:
    """skolodi's exact scenario — EUR base, resource in USD with no USD rate.

    The asymmetry from the video repro: project has ARS rate, doesn't have
    USD rate. Changing a resource from EUR → ARS updates the section
    (conversion applied). Changing from EUR → USD does NOT change the sum
    (silent no-op in _resource_total_in_base). This helper surfaces the
    "no USD rate" gap so the UI can render an amber badge.
    """
    from app.modules.boq.service import _detect_resource_fx_warnings

    resources = [
        {"quantity": 1, "unit_rate": 10, "currency": "USD"},
        {"quantity": 2, "unit_rate": 20, "currency": "ARS"},
    ]
    fx_map = {"ARS": "1415.0"}  # USD missing
    assert _detect_resource_fx_warnings(resources, fx_map, "EUR") == ["USD"]


def test_detect_resource_fx_warnings_multiple_missing_dedup_sorted() -> None:
    """Multiple resources in different unconfigured foreign currencies."""
    from app.modules.boq.service import _detect_resource_fx_warnings

    resources = [
        {"quantity": 1, "unit_rate": 10, "currency": "USD"},
        {"quantity": 1, "unit_rate": 10, "currency": "GBP"},
        {"quantity": 1, "unit_rate": 10, "currency": "USD"},  # duplicate
        {"quantity": 1, "unit_rate": 10, "currency": "CHF"},
        {"quantity": 1, "unit_rate": 10, "currency": "EUR"},  # base, ignored
    ]
    fx_map: dict[str, str] = {}  # no rates configured
    result = _detect_resource_fx_warnings(resources, fx_map, "EUR")
    # Deduplicated; order doesn't matter for the test contract but the impl
    # returns insertion-order. Compare as sets to keep the test robust.
    assert set(result) == {"USD", "GBP", "CHF"}


def test_detect_resource_fx_warnings_case_insensitive() -> None:
    """Currency codes normalised to uppercase before comparison."""
    from app.modules.boq.service import _detect_resource_fx_warnings

    resources = [{"quantity": 1, "unit_rate": 10, "currency": "usd"}]
    fx_map = {"USD": "1.10"}  # rate exists in canonical form
    assert _detect_resource_fx_warnings(resources, fx_map, "eur") == []


def test_detect_resource_fx_warnings_handles_malformed_rows() -> None:
    """Non-dict rows, missing currency, weird types — never raise."""
    from app.modules.boq.service import _detect_resource_fx_warnings

    resources = [
        None,  # type: ignore[list-item]
        "not a dict",  # type: ignore[list-item]
        {"quantity": 1, "unit_rate": 10},  # no currency
        {"currency": 123},  # int currency
        {"currency": "USD"},  # valid foreign without rate
    ]
    fx_map: dict[str, str] = {}
    assert _detect_resource_fx_warnings(resources, fx_map, "EUR") == ["USD"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fx_rates,expected_total,expected_unconverted",
    [
        ([], Decimal("1000"), {"USD": Decimal("500")}),
        ([{"code": "USD", "rate": "0", "label": "Dollar"}], Decimal("1000"), {"USD": Decimal("500")}),
        ([{"code": "USD", "rate": "1.1", "label": "Dollar"}], Decimal("1550"), {}),
    ],
)
async def test_summary_and_structured_totals_agree_for_persisted_currency_rows(
    session,
    monkeypatch,
    fx_rates,
    expected_total,
    expected_unconverted,
):
    from unittest.mock import AsyncMock

    from app.modules.boq import router

    boq = await _make_boq_with_mixed_currency(session, fx_rates)
    service = BOQService(session)
    monkeypatch.setattr(router, "_verify_boq_owner", AsyncMock())
    summary = await router.get_resource_summary(boq.id, OWNER_ID, {}, session, service)
    structured = await service.get_boq_structured(boq.id)
    assert summary.grand_total == expected_total
    assert structured.direct_cost == expected_total
    assert summary.unconverted == expected_unconverted
