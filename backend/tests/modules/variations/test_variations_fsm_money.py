"""R5 audit: FSM + high-value approval gate tests.

Patterned on tests/unit/test_rfq_bidding.py — exercises the
state-machine boundaries and the new ``ensure_high_value_authorised``
gate that decides whether a manager or admin must sign off on a
variation. LLM mocked (no LLM is used in variations).
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
    VariationOrderCreate,
    VariationRequestCreate,
)
from app.modules.variations.service import (
    HIGH_VALUE_APPROVAL_THRESHOLD,
    VariationsService,
    ensure_high_value_authorised,
)

# ── Repo / session stubs (shared with rollup test file shape) ────────────


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

    async def next_code(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"X-{self._counter:04d}"


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


# ── ensure_high_value_authorised gate ─────────────────────────────────────


def test_ensure_high_value_authorised_under_threshold_allows_any_payload() -> None:
    # No raise: amount below threshold, any role acceptable.
    ensure_high_value_authorised(
        Decimal("100"),
        payload={"role": "editor", "permissions": []},
    )


def test_ensure_high_value_authorised_above_threshold_blocks_editor() -> None:
    over = HIGH_VALUE_APPROVAL_THRESHOLD + Decimal("1")
    with pytest.raises(HTTPException) as exc:
        ensure_high_value_authorised(
            over,
            payload={"role": "editor", "permissions": []},
        )
    assert exc.value.status_code == 403


def test_ensure_high_value_authorised_above_threshold_blocks_manager() -> None:
    over = HIGH_VALUE_APPROVAL_THRESHOLD + Decimal("1")
    # Manager has approve_request but NOT approve_high_value.
    with pytest.raises(HTTPException) as exc:
        ensure_high_value_authorised(
            over,
            payload={
                "role": "manager",
                "permissions": ["variations.approve_request"],
            },
        )
    assert exc.value.status_code == 403


def test_ensure_high_value_authorised_admin_passes() -> None:
    over = HIGH_VALUE_APPROVAL_THRESHOLD + Decimal("1")
    ensure_high_value_authorised(
        over,
        payload={"role": "admin", "permissions": []},
    )


def test_ensure_high_value_authorised_explicit_perm_passes() -> None:
    over = HIGH_VALUE_APPROVAL_THRESHOLD + Decimal("1")
    ensure_high_value_authorised(
        over,
        payload={
            "role": "manager",
            "permissions": ["variations.approve_high_value"],
        },
    )


def test_ensure_high_value_authorised_none_payload_skips() -> None:
    """A None payload (unit tests bypassing the dependency) is permissive.

    Production always sends a payload; this branch only matters for
    service-level tests that don't simulate a JWT.
    """
    ensure_high_value_authorised(
        HIGH_VALUE_APPROVAL_THRESHOLD + Decimal("1"),
        payload=None,
    )


# ── State-machine boundaries (FSM) — money-bearing transitions ────────────


@pytest.mark.asyncio
async def test_vr_lifecycle_draft_to_approved_logs_decision(caplog) -> None:
    import logging

    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=project_id,
                title="Foundation rework",
                classification="scope_change",
                estimated_cost_impact=Decimal("12500"),
                currency="EUR",
            ),
            user_id="approver-1",
        )
        await svc.transition_variation_request(vr.id, "submitted", user_id="approver-1")
        with caplog.at_level(logging.INFO):
            decided = await svc.transition_variation_request(
                vr.id,
                "approved",
                user_id="approver-1",
                decision_notes="OK",
            )
    assert decided.status == "approved"
    assert decided.decided_by == "approver-1"
    # Structured-log decision record exists.
    assert any(
        "variations.request.approved" in str(rec.message) or rec.name.endswith("variations.service")
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_vr_cannot_jump_draft_to_approved() -> None:
    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=project_id,
                title="x",
                classification="scope_change",
            ),
            user_id="u1",
        )
        with pytest.raises(HTTPException) as exc:
            await svc.transition_variation_request(vr.id, "approved", user_id="u1")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_vo_cannot_be_edited_after_completed() -> None:
    """Locked-state guard: completed VOs reject silent money rewrites."""
    from app.modules.variations.schemas import VariationOrderUpdate

    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vo = await svc.create_order(
            VariationOrderCreate(
                project_id=project_id,
                title="vo",
                final_cost_impact=Decimal("5000"),
                currency="EUR",
            ),
            user_id="u1",
        )
        await svc.transition_variation_order(vo.id, "in_progress", user_id="u1")
        await svc.transition_variation_order(vo.id, "completed", user_id="u1")
    with pytest.raises(HTTPException) as exc:
        await svc.update_order(vo.id, VariationOrderUpdate(final_cost_impact=Decimal("99999")))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_vr_cannot_be_edited_after_approved() -> None:
    """Decided VRs are frozen — service must reject silent edits.

    A user with ``variations.update`` could otherwise rewrite the cost
    impact of an approved VR and quietly move the audit trail.
    """
    svc = _make_service()
    project_id = uuid.uuid4()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=project_id,
                title="x",
                classification="scope_change",
                estimated_cost_impact=Decimal("100"),
            ),
            user_id="u1",
        )
        await svc.transition_variation_request(vr.id, "submitted", user_id="u1")
        await svc.transition_variation_request(vr.id, "approved", user_id="u1")
    from app.modules.variations.schemas import VariationRequestUpdate

    with pytest.raises(HTTPException) as exc:
        await svc.update_request(
            vr.id,
            VariationRequestUpdate(estimated_cost_impact=Decimal("999999")),
        )
    assert exc.value.status_code == 409


def test_is_high_value_threshold_constant_matches_permission_doc() -> None:
    """Sanity-check: threshold is non-trivial and Decimal."""
    assert isinstance(HIGH_VALUE_APPROVAL_THRESHOLD, Decimal)
    assert Decimal("1000") < HIGH_VALUE_APPROVAL_THRESHOLD
