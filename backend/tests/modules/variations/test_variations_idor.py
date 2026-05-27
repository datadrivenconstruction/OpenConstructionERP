"""R5 audit: object-level IDOR guards for variations.

Patterned on tests/unit/test_teams.py — every cross-table dereference
must verify the row lives in the caller's project before mutating
anything. Most router-level IDOR is already handled via
``verify_project_access`` on the *parent* row's project_id; this file
focuses on the service-layer guard ``apply_variation_to_final_account``
and the project-id resolvers used by line-level routes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.modules.variations.schemas import (
    FinalAccountCreate,
    VariationCostImpactCreate,
    VariationOrderCreate,
)
from app.modules.variations.service import VariationsService


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


# ── Cross-project IDOR on apply_variation_to_final_account ───────────────


@pytest.mark.asyncio
async def test_apply_variation_to_fa_rejects_cross_project() -> None:
    """A VO from project A must not be appliable to a FA from project B."""
    svc = _make_service()
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        # FA in project A.
        await svc.create_final_account(
            FinalAccountCreate(
                project_id=project_a,
                original_contract_value=Decimal("1000"),
                currency="EUR",
            ),
        )
        fa_a = await svc.final_account_repo.for_project(project_a)
        # VO in project B.
        vo_b = await svc.create_order(
            VariationOrderCreate(
                project_id=project_b,
                title="cross",
                final_cost_impact=Decimal("999"),
                currency="EUR",
            ),
            user_id="u1",
        )
    with pytest.raises(HTTPException) as exc:
        await svc.apply_variation_to_final_account(vo_b.id, fa_a.id)
    # 404 (not 403) — we deliberately do not leak the FA's existence.
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_apply_variation_to_fa_rejects_currency_mismatch() -> None:
    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.create_final_account(
            FinalAccountCreate(
                project_id=project_id,
                original_contract_value=Decimal("1000"),
                currency="EUR",
            ),
        )
        fa = await svc.final_account_repo.for_project(project_id)
        vo = await svc.create_order(
            VariationOrderCreate(
                project_id=project_id,
                title="usd vo",
                final_cost_impact=Decimal("100"),
                currency="USD",
            ),
            user_id="u1",
        )
    with pytest.raises(HTTPException) as exc:
        await svc.apply_variation_to_final_account(vo.id, fa.id)
    assert exc.value.status_code == 409
    assert "currency" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_apply_variation_to_fa_rejects_voided_vo() -> None:
    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.create_final_account(
            FinalAccountCreate(
                project_id=project_id,
                original_contract_value=Decimal("1000"),
                currency="EUR",
            ),
        )
        fa = await svc.final_account_repo.for_project(project_id)
        vo = await svc.create_order(
            VariationOrderCreate(
                project_id=project_id,
                title="vo",
                final_cost_impact=Decimal("100"),
                currency="EUR",
            ),
            user_id="u1",
        )
        await svc.transition_variation_order(vo.id, "voided", user_id="u1")
    with pytest.raises(HTTPException) as exc:
        await svc.apply_variation_to_final_account(vo.id, fa.id)
    assert exc.value.status_code == 409


# ── Project-id resolvers (line-level IDOR guards) ─────────────────────────


@pytest.mark.asyncio
async def test_cost_impact_project_id_returns_owning_project() -> None:
    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vo = await svc.create_order(
            VariationOrderCreate(project_id=project_id, title="vo", currency="EUR"),
            user_id="u1",
        )
    line = await svc.add_cost_impact(
        VariationCostImpactCreate(
            variation_order_id=vo.id,
            description="x",
            quantity=Decimal("1"),
            unit_rate=Decimal("1"),
        ),
    )
    resolved = await svc.cost_impact_project_id(line.id)
    assert resolved == project_id


@pytest.mark.asyncio
async def test_cost_impact_project_id_404_on_missing_line() -> None:
    svc = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.cost_impact_project_id(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_final_account_create_returns_409_not_500() -> None:
    """IntegrityError on duplicate FA per project must surface as 409."""
    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.create_final_account(
            FinalAccountCreate(
                project_id=project_id,
                original_contract_value=Decimal("1"),
                currency="EUR",
            ),
        )
        with pytest.raises(HTTPException) as exc:
            await svc.create_final_account(
                FinalAccountCreate(
                    project_id=project_id,
                    original_contract_value=Decimal("1"),
                    currency="EUR",
                ),
            )
    assert exc.value.status_code == 409
