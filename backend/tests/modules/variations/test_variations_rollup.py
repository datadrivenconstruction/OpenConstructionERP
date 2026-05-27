"""R5 audit: Decimal-exact + currency-aware variations roll-up tests.

Patterned on tests/modules/clash_cost_impact/test_cost_rollup.py — pure
Decimal arithmetic in / Decimal out, currency drift surfaced as
warnings, bulk caps enforced.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.modules.variations.schemas import (
    DayworkSheetCreate,
    DayworkSheetLineCreate,
    FinalAccountCreate,
    VariationCostImpactCreate,
    VariationOrderCreate,
)
from app.modules.variations.service import (
    BULK_LINES_MAX,
    HIGH_VALUE_APPROVAL_THRESHOLD,
    VariationsService,
    apply_daywork_markup,
    compute_cost_impact_total,
    compute_daywork_sheet_total,
    is_high_value,
)

# ── In-memory stub repository (matches the production surface) ────────────


class _Repo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, row: Any) -> Any:
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        now = datetime.now(UTC)
        row.created_at = now
        row.updated_at = now
        self.rows[row.id] = row
        return row

    async def get_by_id(self, row_id: uuid.UUID) -> Any:
        return self.rows.get(row_id)

    async def update_fields(self, row_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(row_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        row.updated_at = datetime.now(UTC)

    async def delete(self, row_id: uuid.UUID) -> None:
        self.rows.pop(row_id, None)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if getattr(r, "project_id", None) == project_id]
        if status is not None:
            rows = [r for r in rows if getattr(r, "status", None) == status]
        return rows[offset : offset + limit], len(rows)

    async def next_code(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"X-{self._counter:04d}"

    async def next_sheet_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"DW-{self._counter:04d}"

    async def list_for_sheet(self, sheet_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "sheet_id", None) == sheet_id]

    async def list_for_order(self, vo_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "variation_order_id", None) == vo_id]

    async def list_valued_for_project(self, project_id: uuid.UUID) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if getattr(r, "project_id", None) == project_id and getattr(r, "status", None) != "voided"
        ]

    async def list_signed(self, project_id: uuid.UUID) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if getattr(r, "project_id", None) == project_id and getattr(r, "status", None) in {"signed", "billed"}
        ]

    async def for_project(self, project_id: uuid.UUID) -> Any:
        for r in self.rows.values():
            if getattr(r, "project_id", None) == project_id:
                return r
        return None


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        return None

    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: None)


def _make_service() -> VariationsService:
    svc = VariationsService.__new__(VariationsService)
    svc.session = _StubSession()
    svc.notice_repo = _Repo()
    svc.vr_repo = _Repo()
    svc.vo_repo = _Repo()
    svc.cost_impact_repo = _Repo()
    svc.schedule_impact_repo = _Repo()
    svc.site_measurement_repo = _Repo()
    svc.daywork_repo = _Repo()
    svc.daywork_line_repo = _Repo()
    svc.disruption_repo = _Repo()
    svc.eot_repo = _Repo()
    svc.final_account_repo = _Repo()
    return svc


# ── Decimal-exact rollup (no float drift) ─────────────────────────────────


def test_compute_cost_impact_total_decimal_exact_no_float_drift() -> None:
    """0.1 + 0.2 must equal exactly 0.3 (would be 0.30000...4 with float)."""
    lines = [
        SimpleNamespace(total=Decimal("0.1"), quantity=1, unit_rate=Decimal("0.1")),
        SimpleNamespace(total=Decimal("0.2"), quantity=1, unit_rate=Decimal("0.2")),
    ]
    total = compute_cost_impact_total(lines)
    assert total == Decimal("0.3")
    assert isinstance(total, Decimal)


def test_compute_cost_impact_total_long_chain_no_drift() -> None:
    """Sum 1000 lines of 0.01 each — must be exactly 10.00."""
    lines = [SimpleNamespace(total=Decimal("0.01"), quantity=1, unit_rate=Decimal("0.01")) for _ in range(1000)]
    assert compute_cost_impact_total(lines) == Decimal("10.00")


def test_apply_daywork_markup_decimal_exact() -> None:
    """100 + 15% markup must be exactly 115.00 (not 114.999... with float)."""
    assert apply_daywork_markup("100", "15") == Decimal("115.00")
    assert apply_daywork_markup("100", Decimal("15")) == Decimal("115.00")


def test_apply_daywork_markup_zero_markup_is_subtotal() -> None:
    assert apply_daywork_markup(Decimal("123.45"), 0) == Decimal("123.45")


def test_compute_daywork_sheet_total_falls_back_to_qty_rate() -> None:
    lines = [
        SimpleNamespace(total=None, quantity=Decimal("8"), unit_rate=Decimal("12.50")),
    ]
    assert compute_daywork_sheet_total(lines) == Decimal("100.00")


# ── High-value classification ─────────────────────────────────────────────


def test_is_high_value_at_threshold_is_false() -> None:
    assert is_high_value(HIGH_VALUE_APPROVAL_THRESHOLD) is False


def test_is_high_value_above_threshold() -> None:
    assert is_high_value(HIGH_VALUE_APPROVAL_THRESHOLD + Decimal("1")) is True


def test_is_high_value_negative_absolute() -> None:
    """Negative VOs (credit notes) of large magnitude also gate as high-value."""
    assert is_high_value(-HIGH_VALUE_APPROVAL_THRESHOLD - Decimal("1")) is True


def test_is_high_value_none_zero() -> None:
    assert is_high_value(None) is False
    assert is_high_value(0) is False


# ── Currency normalisation: line inherits VO currency when blank ──────────


@pytest.mark.asyncio
async def test_add_cost_impact_inherits_vo_currency_when_blank() -> None:
    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vo = await svc.create_order(
            VariationOrderCreate(
                project_id=project_id,
                title="vo",
                final_cost_impact=Decimal("1000"),
                currency="EUR",
            ),
            user_id="u1",
        )
    # Note: currency unset on the line.
    line = await svc.add_cost_impact(
        VariationCostImpactCreate(
            variation_order_id=vo.id,
            description="bolts",
            quantity=Decimal("10"),
            unit_rate=Decimal("5"),
        ),
    )
    assert line.currency == "EUR"
    assert line.total == Decimal("50")


@pytest.mark.asyncio
async def test_add_cost_impact_keeps_explicit_currency() -> None:
    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vo = await svc.create_order(
            VariationOrderCreate(
                project_id=project_id,
                title="vo",
                currency="EUR",
            ),
            user_id="u1",
        )
    line = await svc.add_cost_impact(
        VariationCostImpactCreate(
            variation_order_id=vo.id,
            description="usd line",
            quantity=Decimal("2"),
            unit_rate=Decimal("100"),
            currency="USD",
        ),
    )
    assert line.currency == "USD"


# ── Bulk cap (DoS guard) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_cost_impacts_rejects_oversized_payload() -> None:
    from fastapi import HTTPException

    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vo = await svc.create_order(
            VariationOrderCreate(project_id=project_id, title="vo"),
            user_id="u1",
        )
    too_many = [
        VariationCostImpactCreate(
            variation_order_id=vo.id,
            description=f"l{i}",
            quantity=Decimal("1"),
            unit_rate=Decimal("1"),
        )
        for i in range(BULK_LINES_MAX + 1)
    ]
    with pytest.raises(HTTPException) as exc:
        await svc.bulk_cost_impacts(vo.id, too_many)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_bulk_daywork_lines_rejects_oversized_payload() -> None:
    from fastapi import HTTPException

    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        sheet = await svc.create_daywork_sheet(
            DayworkSheetCreate(project_id=project_id, description="d", currency="EUR"),
            user_id="u1",
        )
    too_many = [
        DayworkSheetLineCreate(
            sheet_id=sheet.id,
            description=f"l{i}",
            quantity=Decimal("1"),
            unit_rate=Decimal("1"),
        )
        for i in range(BULK_LINES_MAX + 1)
    ]
    with pytest.raises(HTTPException) as exc:
        await svc.bulk_daywork_lines(sheet.id, too_many)
    assert exc.value.status_code == 413


# ── Currency-aware recompute (skips mismatched rows + warns) ─────────────


@pytest.mark.asyncio
async def test_recompute_final_account_skips_mismatched_currency(caplog) -> None:
    import logging

    svc = _make_service()
    project_id = uuid.uuid4()
    # FA in EUR.
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.create_final_account(
            FinalAccountCreate(
                project_id=project_id,
                original_contract_value=Decimal("1000000"),
                currency="EUR",
            ),
        )
    # Mix: one EUR VO (counts) + one USD VO (skipped).
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.create_order(
            VariationOrderCreate(
                project_id=project_id,
                title="eur",
                final_cost_impact=Decimal("50000"),
                currency="EUR",
            ),
            user_id="u1",
        )
        await svc.create_order(
            VariationOrderCreate(
                project_id=project_id,
                title="usd",
                final_cost_impact=Decimal("999999"),
                currency="USD",
            ),
            user_id="u1",
        )
    with caplog.at_level(logging.WARNING):
        fa = await svc.recompute_final_account(project_id)
    # Only the EUR VO should have contributed.
    assert fa is not None
    assert fa.variations_total == Decimal("50000")
    assert any("currency_skip" in rec.message or "currency_skip" in (rec.name or "") for rec in caplog.records)


@pytest.mark.asyncio
async def test_recompute_final_account_blank_fa_currency_accepts_all() -> None:
    """When FA currency is blank we accept rows regardless of their currency.

    A blank FA currency means "not yet decided" — the operator hasn't
    locked the unit and we shouldn't suppress data they may need to see.
    """
    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.create_final_account(
            FinalAccountCreate(
                project_id=project_id,
                original_contract_value=Decimal("0"),
                currency="",
            ),
        )
        await svc.create_order(
            VariationOrderCreate(
                project_id=project_id,
                title="usd",
                final_cost_impact=Decimal("100"),
                currency="USD",
            ),
            user_id="u1",
        )
    fa = await svc.recompute_final_account(project_id)
    assert fa is not None
    assert fa.variations_total == Decimal("100")
