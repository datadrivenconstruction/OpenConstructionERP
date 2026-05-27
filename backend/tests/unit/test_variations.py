"""Unit tests for the Variations module.

Covers pure helpers, state machines, service transitions, repository
basics, conversion flow, and permission registration. Repositories and
the event bus are stubbed so tests don't touch a database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from datetime import date as dt_date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.modules.variations.schemas import (
    DayworkSheetCreate,
    DayworkSheetLineCreate,
    DisruptionClaimCreate,
    ExtensionOfTimeClaimCreate,
    FinalAccountCreate,
    NoticeCreate,
    SiteMeasurementCreate,
    VariationOrderCreate,
    VariationOrderUpdate,
    VariationRequestCreate,
    VariationRequestUpdate,
)
from app.modules.variations.service import (
    VariationsService,
    allowed_daywork_transitions,
    allowed_disruption_transitions,
    allowed_eot_transitions,
    allowed_final_account_transitions,
    allowed_notice_transitions,
    allowed_vo_transitions,
    allowed_vr_transitions,
    compute_cost_impact_total,
    compute_critical_path_extension,
    compute_daywork_sheet_total,
    is_within_response_window,
    validate_variation_request,
)

PROJECT_ID = uuid.uuid4()


# ── Generic in-memory stub repo ────────────────────────────────────────────


class _Repo:
    """A tiny in-memory CRUD stub mirroring the real repository surface."""

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

    async def list_open(self, project_id: uuid.UUID) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if getattr(r, "project_id", None) == project_id
            and getattr(r, "status", None) in {"draft", "submitted", "under_review"}
        ]

    async def list_open_variations(self, project_id: uuid.UUID) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if getattr(r, "project_id", None) == project_id and getattr(r, "status", None) in {"issued", "in_progress"}
        ]

    async def list_all_for_project(self, project_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "project_id", None) == project_id]

    async def list_valued_for_project(self, project_id: uuid.UUID) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if getattr(r, "project_id", None) == project_id and getattr(r, "status", None) != "voided"
        ]

    def _valued(self, project_id: uuid.UUID) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if getattr(r, "project_id", None) == project_id and getattr(r, "status", None) != "voided"
        ]

    async def status_counts(self, project_id: uuid.UUID) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows.values():
            if getattr(r, "project_id", None) != project_id:
                continue
            st = str(getattr(r, "status", "") or "")
            out[st] = out.get(st, 0) + 1
        return out

    async def cost_impact_sum(self, project_id: uuid.UUID) -> Decimal:
        return sum(
            (Decimal(str(getattr(r, "final_cost_impact", 0) or 0)) for r in self._valued(project_id)),
            Decimal("0"),
        )

    async def schedule_days_sum(self, project_id: uuid.UUID) -> int:
        return sum(int(getattr(r, "final_schedule_days", 0) or 0) for r in self._valued(project_id))

    async def signed_value(self, project_id: uuid.UUID) -> Decimal:
        return sum(
            (
                Decimal(str(getattr(r, "total_amount", 0) or 0))
                for r in self.rows.values()
                if getattr(r, "project_id", None) == project_id and getattr(r, "status", None) in {"signed", "billed"}
            ),
            Decimal("0"),
        )

    async def first_currency(self, project_id: uuid.UUID) -> str:
        for r in self.rows.values():
            if getattr(r, "project_id", None) == project_id and getattr(r, "currency", ""):
                return str(r.currency)
        return ""

    async def pending_claims(self, project_id: uuid.UUID) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if getattr(r, "project_id", None) == project_id
            and getattr(r, "status", None) in {"submitted", "under_review"}
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
        # Stub: in-memory rows already mutate via update_fields, no DB round-trip.
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


# ── Pure helpers ─────────────────────────────────────────────────────────


def test_compute_cost_impact_total_empty() -> None:
    assert compute_cost_impact_total([]) == Decimal("0")


def test_compute_cost_impact_total_sums_total_field() -> None:
    lines = [
        SimpleNamespace(total=Decimal("100"), quantity=2, unit_rate=50),
        SimpleNamespace(total=Decimal("200"), quantity=4, unit_rate=50),
    ]
    assert compute_cost_impact_total(lines) == Decimal("300")


def test_compute_cost_impact_total_falls_back_to_qty_x_rate() -> None:
    lines = [
        SimpleNamespace(total=None, quantity=3, unit_rate=Decimal("12.50")),
    ]
    assert compute_cost_impact_total(lines) == Decimal("37.50")


def test_compute_cost_impact_total_ignores_none_rows() -> None:
    assert compute_cost_impact_total([None, SimpleNamespace(total="50")]) == Decimal("50")


def test_compute_daywork_sheet_total_basic() -> None:
    lines = [
        SimpleNamespace(total=Decimal("80"), quantity=8, unit_rate=10),
        SimpleNamespace(total=Decimal("20"), quantity=2, unit_rate=10),
    ]
    assert compute_daywork_sheet_total(lines) == Decimal("100")


def test_compute_daywork_sheet_total_empty() -> None:
    assert compute_daywork_sheet_total([]) == Decimal("0")


def test_is_within_response_window_no_target_is_open() -> None:
    notice = SimpleNamespace(target_response_date=None)
    assert is_within_response_window(notice) is True


def test_is_within_response_window_future_open() -> None:
    notice = SimpleNamespace(target_response_date="2099-01-01")
    assert is_within_response_window(notice) is True


def test_is_within_response_window_past_closed() -> None:
    notice = SimpleNamespace(target_response_date="2000-01-01")
    assert is_within_response_window(notice) is False


def test_is_within_response_window_edge_today() -> None:
    today = dt_date(2026, 5, 12)
    notice = SimpleNamespace(target_response_date="2026-05-12")
    assert is_within_response_window(notice, today=today) is True


def test_compute_critical_path_extension_no_critical() -> None:
    impacts = [
        SimpleNamespace(days_added=5, is_critical_path=False),
        SimpleNamespace(days_added=10, is_critical_path=False),
    ]
    assert compute_critical_path_extension(impacts) == 0


def test_compute_critical_path_extension_picks_max_critical() -> None:
    impacts = [
        SimpleNamespace(days_added=3, is_critical_path=True),
        SimpleNamespace(days_added=20, is_critical_path=False),
        SimpleNamespace(days_added=7, is_critical_path=True),
    ]
    # Max of CRITICAL only -> 7, NOT 20.
    assert compute_critical_path_extension(impacts) == 7


def test_validate_variation_request_regulatory_requires_description() -> None:
    ok, errs = validate_variation_request(
        {"project_id": PROJECT_ID, "classification": "regulatory", "description": ""},
    )
    assert ok is False
    assert any("description is required" in e for e in errs)


def test_validate_variation_request_unforeseen_requires_description() -> None:
    ok, errs = validate_variation_request(
        {"project_id": PROJECT_ID, "classification": "unforeseen", "description": ""},
    )
    assert ok is False


def test_validate_variation_request_scope_change_requires_title_or_desc() -> None:
    ok, errs = validate_variation_request(
        {"project_id": PROJECT_ID, "classification": "scope_change", "title": "", "description": ""},
    )
    assert ok is False


def test_validate_variation_request_ok_with_title() -> None:
    ok, errs = validate_variation_request(
        {
            "project_id": PROJECT_ID,
            "classification": "scope_change",
            "title": "Replace window",
            "description": "",
        },
    )
    assert ok is True
    assert errs == []


def test_validate_variation_request_missing_project() -> None:
    ok, errs = validate_variation_request(
        {"classification": "scope_change", "title": "x"},
    )
    assert ok is False
    assert any("project_id" in e for e in errs)


def test_validate_variation_request_unknown_classification() -> None:
    ok, errs = validate_variation_request(
        {"project_id": PROJECT_ID, "classification": "weird_one", "title": "x"},
    )
    assert ok is False


# ── State-machine pure helpers ────────────────────────────────────────────


def test_allowed_notice_transitions() -> None:
    assert "acknowledged" in allowed_notice_transitions("issued")
    assert allowed_notice_transitions("closed") == []


def test_allowed_vr_transitions() -> None:
    assert allowed_vr_transitions("draft") == ["submitted"]
    assert set(allowed_vr_transitions("submitted")) == {"under_review", "approved", "rejected"}
    assert allowed_vr_transitions("converted_to_vo") == []


def test_allowed_vo_transitions() -> None:
    assert set(allowed_vo_transitions("issued")) == {"in_progress", "voided"}
    assert allowed_vo_transitions("completed") == []


def test_allowed_daywork_transitions() -> None:
    assert "signed" in allowed_daywork_transitions("draft")
    assert allowed_daywork_transitions("billed") == []


def test_allowed_disruption_transitions() -> None:
    assert allowed_disruption_transitions("draft") == ["submitted"]
    assert allowed_disruption_transitions("agreed") == []


def test_allowed_eot_transitions() -> None:
    assert allowed_eot_transitions("draft") == ["submitted"]
    assert allowed_eot_transitions("granted") == []


def test_allowed_final_account_transitions() -> None:
    assert "closed" in allowed_final_account_transitions("agreed")
    assert allowed_final_account_transitions("closed") == []


# ── Service: notices ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_notice_emits_event() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached") as pub:
        n = await svc.create_notice(
            NoticeCreate(project_id=PROJECT_ID, title="T", recipient_type="owner"),
            user_id="u1",
        )
    assert n.id is not None
    assert n.code.startswith("X-")
    event_names = [c.args[0] for c in pub.call_args_list]
    assert "variations.notice.issued" in event_names


@pytest.mark.asyncio
async def test_transition_notice_valid() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        n = await svc.create_notice(
            NoticeCreate(project_id=PROJECT_ID, title="T"),
            user_id="u1",
        )
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        n2 = await svc.transition_notice(n.id, "acknowledged")
    assert n2.status == "acknowledged"


@pytest.mark.asyncio
async def test_transition_notice_invalid_raises() -> None:
    from fastapi import HTTPException

    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        n = await svc.create_notice(
            NoticeCreate(project_id=PROJECT_ID, title="T"),
            user_id="u1",
        )
    # Force into closed first.
    n.status = "closed"
    with pytest.raises(HTTPException) as exc, patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.transition_notice(n.id, "acknowledged")
    assert exc.value.status_code == 409


# ── Service: variation requests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_request_invalid_payload_rejected() -> None:
    from fastapi import HTTPException

    svc = _make_service()
    # Regulatory with no description -> 422.
    bad = VariationRequestCreate(
        project_id=PROJECT_ID,
        classification="regulatory",
        description="",
    )
    with pytest.raises(HTTPException) as exc:
        await svc.create_request(bad, user_id="u1")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_transition_variation_request_happy_path() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=PROJECT_ID,
                title="Replace door",
                classification="scope_change",
            ),
            user_id="u1",
        )
    assert vr.status == "draft"
    with patch("app.modules.variations.service.event_bus.publish_detached") as pub:
        vr2 = await svc.transition_variation_request(vr.id, "submitted", user_id="u1")
    assert vr2.status == "submitted"
    assert vr2.submitted_at is not None
    names = [c.args[0] for c in pub.call_args_list]
    assert "variations.request.submitted" in names


@pytest.mark.asyncio
async def test_transition_variation_request_invalid_jump() -> None:
    from fastapi import HTTPException

    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=PROJECT_ID,
                title="Replace door",
                classification="scope_change",
            ),
            user_id="u1",
        )
    # draft -> approved is invalid.
    with pytest.raises(HTTPException) as exc, patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.transition_variation_request(vr.id, "approved")
    assert exc.value.status_code == 409


# ── Service: convert VR -> VO ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_convert_vr_to_vo_creates_vo_and_flips_status() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=PROJECT_ID,
                title="Foundations rework",
                classification="unforeseen",
                description="Site condition unforeseen",
            ),
            user_id="u1",
        )
        # Drive VR through submitted -> approved.
        await svc.transition_variation_request(vr.id, "submitted", user_id="u1")
        await svc.transition_variation_request(vr.id, "approved", user_id="u1")

    vo_payload = VariationOrderCreate(
        project_id=PROJECT_ID,
        title="Foundations rework",
        final_cost_impact=Decimal("12500"),
        final_schedule_days=5,
        currency="EUR",
    )

    # R7 audit: convert_vr_to_vo now atomically mirrors the VO into a
    # draft ChangeOrder via ChangeOrderService. The unit-test stub repo
    # set can't satisfy the CO repository contract (real SQLA execute
    # path), so patch the CO service to a no-op shim that returns a
    # plausible CO row. The R7-specific atomicity guarantee is pinned
    # in tests/modules/variations/test_r7_security.py.
    class _FakeCO:
        id = uuid.uuid4()

    class _FakeCOService:
        def __init__(self, _session: Any) -> None:
            pass

        async def create_order(self, _payload: Any) -> Any:
            return _FakeCO()

    with (
        patch(
            "app.modules.variations.service.event_bus.publish_detached",
        ) as pub,
        patch(
            "app.modules.changeorders.service.ChangeOrderService",
            _FakeCOService,
        ),
    ):
        vo = await svc.convert_vr_to_vo(vr.id, vo_payload, user_id="u1")

    assert vo.variation_request_id == vr.id
    refreshed_vr = await svc.vr_repo.get_by_id(vr.id)
    assert refreshed_vr.status == "converted_to_vo"
    names = [c.args[0] for c in pub.call_args_list]
    assert "variations.vo.issued" in names
    # R7 audit: event renamed from ``variations.change_order.requested``
    # (fire-and-forget) to ``variations.change_order.created`` because the
    # row now exists synchronously when this event fires.
    assert "variations.change_order.created" in names


@pytest.mark.asyncio
async def test_convert_vr_to_vo_blocks_when_not_approved() -> None:
    from fastapi import HTTPException

    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=PROJECT_ID,
                title="Whatever",
                classification="scope_change",
            ),
            user_id="u1",
        )
    payload = VariationOrderCreate(project_id=PROJECT_ID, title="x")
    with pytest.raises(HTTPException) as exc, patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.convert_vr_to_vo(vr.id, payload, user_id="u1")
    assert exc.value.status_code == 409


# ── Service: site measurement ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_site_measurement_emits_event() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached") as pub:
        sm = await svc.record_site_measurement(
            SiteMeasurementCreate(
                project_id=PROJECT_ID,
                location="Block A",
                unit="m2",
                measured_quantity=Decimal("12.5"),
            ),
            user_id="u1",
        )
    assert sm.measured_quantity == Decimal("12.5")
    assert any(c.args[0] == "variations.measurement.recorded" for c in pub.call_args_list)


# ── Service: daywork ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sign_daywork_sheet_computes_total_and_emits() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        sheet = await svc.create_daywork_sheet(
            DayworkSheetCreate(project_id=PROJECT_ID, description="Demo", currency="EUR"),
            user_id="u1",
        )
        await svc.add_daywork_line(
            DayworkSheetLineCreate(
                sheet_id=sheet.id,
                line_type="labor",
                description="2h labor",
                quantity=Decimal("2"),
                unit="h",
                unit_rate=Decimal("50"),
            ),
        )
        await svc.add_daywork_line(
            DayworkSheetLineCreate(
                sheet_id=sheet.id,
                line_type="material",
                description="cement",
                quantity=Decimal("4"),
                unit="bag",
                unit_rate=Decimal("12.5"),
            ),
        )

    with patch("app.modules.variations.service.event_bus.publish_detached") as pub:
        signed = await svc.sign_daywork_sheet(sheet.id, signer_id="u1")
    assert signed.status == "signed"
    assert signed.total_amount == Decimal("150")  # 100 + 50
    assert any(c.args[0] == "variations.daywork.signed" for c in pub.call_args_list)


@pytest.mark.asyncio
async def test_sign_daywork_sheet_rejects_when_billed() -> None:
    from fastapi import HTTPException

    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        sheet = await svc.create_daywork_sheet(
            DayworkSheetCreate(project_id=PROJECT_ID, currency="EUR"),
            user_id="u1",
        )
    sheet.status = "billed"
    with pytest.raises(HTTPException) as exc, patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.sign_daywork_sheet(sheet.id, signer_id="u1")
    assert exc.value.status_code == 409


# ── Service: disruption + EOT ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_disruption_claim_emits_event() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached") as pub:
        claim = await svc.submit_disruption_claim(
            DisruptionClaimCreate(
                project_id=PROJECT_ID,
                description="Productivity loss",
                cost_amount=Decimal("5000"),
                currency="EUR",
                status="submitted",
            ),
            user_id="u1",
        )
    assert claim.status == "submitted"
    names = [c.args[0] for c in pub.call_args_list]
    assert "variations.disruption.submitted" in names


@pytest.mark.asyncio
async def test_submit_eot_claim_emits_event() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached") as pub:
        claim = await svc.submit_eot_claim(
            ExtensionOfTimeClaimCreate(
                project_id=PROJECT_ID,
                description="Schedule delay",
                root_cause_category="employer_caused",
                requested_days=10,
                critical_path_impact=True,
                status="submitted",
            ),
            user_id="u1",
        )
    assert claim.status == "submitted"
    assert claim.requested_days == 10
    names = [c.args[0] for c in pub.call_args_list]
    assert "variations.eot.submitted" in names


@pytest.mark.asyncio
async def test_eot_grant_with_days() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        claim = await svc.submit_eot_claim(
            ExtensionOfTimeClaimCreate(
                project_id=PROJECT_ID,
                description="Schedule delay",
                requested_days=10,
                status="submitted",
            ),
        )
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        granted = await svc.transition_eot(claim.id, "granted", granted_days=7)
    assert granted.status == "granted"
    assert granted.granted_days == 7


# ── Service: final account recompute ─────────────────────────────────────


@pytest.mark.asyncio
async def test_recompute_final_account_aggregates_vos_and_daywork() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        # Create final account.
        await svc.create_final_account(
            FinalAccountCreate(
                project_id=PROJECT_ID,
                original_contract_value=Decimal("1000000"),
                currency="EUR",
                retention_held=Decimal("50000"),
                retention_released=Decimal("0"),
            ),
        )
        # Add 2 VOs.
        await svc.create_order(
            VariationOrderCreate(
                project_id=PROJECT_ID,
                title="VO 1",
                final_cost_impact=Decimal("20000"),
                currency="EUR",
            ),
        )
        await svc.create_order(
            VariationOrderCreate(
                project_id=PROJECT_ID,
                title="VO 2",
                final_cost_impact=Decimal("15000"),
                currency="EUR",
            ),
        )
        # Add 1 signed daywork sheet (manual status flip + total).
        sheet = await svc.create_daywork_sheet(
            DayworkSheetCreate(project_id=PROJECT_ID, currency="EUR"),
            user_id="u1",
        )
        sheet.status = "signed"
        sheet.total_amount = Decimal("3000")
        # Add 1 agreed disruption claim.
        claim = await svc.submit_disruption_claim(
            DisruptionClaimCreate(
                project_id=PROJECT_ID,
                description="x",
                cost_amount=Decimal("2000"),
                currency="EUR",
                status="agreed",
            ),
        )
        claim.decided_amount = Decimal("2000")

    fa = await svc.recompute_final_account(PROJECT_ID)
    assert fa is not None
    assert fa.variations_total == Decimal("35000")
    assert fa.daywork_total == Decimal("3000")
    assert fa.claims_total == Decimal("2000")
    # final = 1_000_000 + 35_000 + 3_000 + 2_000 - 50_000 + 0 = 990_000
    assert fa.final_value == Decimal("990000")


@pytest.mark.asyncio
async def test_recompute_final_account_excludes_voided_vos() -> None:
    """A voided VO must NOT inflate the revised contract sum."""
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.create_final_account(
            FinalAccountCreate(
                project_id=PROJECT_ID,
                original_contract_value=Decimal("100000"),
                currency="EUR",
            ),
        )
        live = await svc.create_order(
            VariationOrderCreate(
                project_id=PROJECT_ID,
                title="Live VO",
                final_cost_impact=Decimal("10000"),
                currency="EUR",
            ),
        )
        dead = await svc.create_order(
            VariationOrderCreate(
                project_id=PROJECT_ID,
                title="Voided VO",
                final_cost_impact=Decimal("99999"),
                currency="EUR",
            ),
        )
        # Drive the dead VO to voided through its real state machine.
        await svc.transition_variation_order(dead.id, "voided")

    fa = await svc.recompute_final_account(PROJECT_ID)
    assert fa is not None
    # Only the live VO counts — not the 99999 voided one.
    assert fa.variations_total == Decimal("10000")
    assert fa.final_value == Decimal("110000")
    assert live.status == "issued"


@pytest.mark.asyncio
async def test_update_order_blocked_after_completion() -> None:
    """A completed VO's money is frozen — editing it must 409."""
    from fastapi import HTTPException

    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vo = await svc.create_order(
            VariationOrderCreate(
                project_id=PROJECT_ID,
                title="VO",
                final_cost_impact=Decimal("5000"),
                currency="EUR",
            ),
        )
        await svc.transition_variation_order(vo.id, "in_progress")
        await svc.transition_variation_order(vo.id, "completed")
    with pytest.raises(HTTPException) as exc:
        await svc.update_order(
            vo.id,
            VariationOrderUpdate(final_cost_impact=Decimal("999999")),
        )
    assert exc.value.status_code == 409
    # Money unchanged.
    refreshed = await svc.vo_repo.get_by_id(vo.id)
    assert refreshed.final_cost_impact == Decimal("5000")


@pytest.mark.asyncio
async def test_update_request_blocked_after_approval() -> None:
    """An approved VR is a frozen commercial record — editing must 409."""
    from fastapi import HTTPException

    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=PROJECT_ID,
                title="Door swap",
                classification="scope_change",
            ),
            user_id="u1",
        )
        await svc.transition_variation_request(vr.id, "submitted", user_id="u1")
        await svc.transition_variation_request(vr.id, "approved", user_id="u1")
    with pytest.raises(HTTPException) as exc:
        await svc.update_request(
            vr.id,
            VariationRequestUpdate(estimated_cost_impact=Decimal("123456")),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_request_allowed_while_draft() -> None:
    """Pre-decision VRs remain freely editable (no over-restriction)."""
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=PROJECT_ID,
                title="Draft VR",
                classification="scope_change",
            ),
            user_id="u1",
        )
    updated = await svc.update_request(
        vr.id,
        VariationRequestUpdate(title="Edited while draft"),
    )
    assert updated.title == "Edited while draft"


@pytest.mark.asyncio
async def test_dashboard_excludes_voided_vo_cost() -> None:
    """Dashboard cost roll-up must skip voided VOs."""
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.create_order(
            VariationOrderCreate(
                project_id=PROJECT_ID,
                title="Live",
                final_cost_impact=Decimal("8000"),
                final_schedule_days=4,
                currency="EUR",
            ),
        )
        dead = await svc.create_order(
            VariationOrderCreate(
                project_id=PROJECT_ID,
                title="Dead",
                final_cost_impact=Decimal("50000"),
                final_schedule_days=30,
                currency="EUR",
            ),
        )
        await svc.transition_variation_order(dead.id, "voided")
    summary = await svc.get_dashboard(PROJECT_ID)
    assert summary["cost_impact_total"] == Decimal("8000")
    assert summary["schedule_impact_days"] == 4
    assert summary["variation_orders_total"] == 2
    assert summary["currency"] == "EUR"


@pytest.mark.asyncio
async def test_recompute_final_account_no_account_returns_none() -> None:
    svc = _make_service()
    result = await svc.recompute_final_account(PROJECT_ID)
    assert result is None


@pytest.mark.asyncio
async def test_close_final_account_emits_event() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        fa = await svc.create_final_account(
            FinalAccountCreate(
                project_id=PROJECT_ID,
                original_contract_value=Decimal("100000"),
                currency="EUR",
            ),
        )
    # Move to agreed first so we can close (closed only allowed from agreed/disputed).
    fa.status = "agreed"
    with patch("app.modules.variations.service.event_bus.publish_detached") as pub:
        closed = await svc.close_final_account(fa.id, signer_id="u1")
    assert closed.status == "closed"
    assert closed.closed_at is not None
    names = [c.args[0] for c in pub.call_args_list]
    assert "variations.final_account.closed" in names


# ── Repository CRUD basics (in-memory) ────────────────────────────────────


@pytest.mark.asyncio
async def test_notice_repo_crud_round_trip() -> None:
    repo = _Repo()
    row = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        status="issued",
        code="N-0001",
    )
    await repo.create(row)
    got = await repo.get_by_id(row.id)
    assert got is row
    await repo.update_fields(row.id, status="closed")
    assert (await repo.get_by_id(row.id)).status == "closed"
    await repo.delete(row.id)
    assert (await repo.get_by_id(row.id)) is None


@pytest.mark.asyncio
async def test_vo_repo_list_for_project_filter() -> None:
    repo = _Repo()
    other = uuid.uuid4()
    for st in ("issued", "completed", "voided"):
        await repo.create(SimpleNamespace(project_id=PROJECT_ID, status=st))
    await repo.create(SimpleNamespace(project_id=other, status="issued"))
    rows, total = await repo.list_for_project(PROJECT_ID)
    assert total == 3
    rows2, total2 = await repo.list_for_project(PROJECT_ID, status="completed")
    assert total2 == 1
    assert rows2[0].status == "completed"


# ── Permission registration ──────────────────────────────────────────────


def test_permission_constants_registered() -> None:
    from app.core.permissions import permission_registry
    from app.modules.variations.permissions import register_variations_permissions

    register_variations_permissions()
    expected = {
        "variations.read",
        "variations.create",
        "variations.update",
        "variations.delete",
        "variations.submit_request",
        "variations.approve_request",
        "variations.convert_to_vo",
        "variations.complete_vo",
        "variations.sign_daywork",
        "variations.decide_claim",
        "variations.close_final_account",
    }
    registered = (
        set(permission_registry.get_module_permissions("variations"))
        if hasattr(permission_registry, "get_module_permissions")
        else None
    )
    if registered is None:
        # Fall back to private dict if no accessor exists.
        registered = {p for p in getattr(permission_registry, "_permissions", {}).keys() if p.startswith("variations.")}
    assert expected.issubset(registered), f"missing: {expected - registered}"


# ── FIDIC 20.1 time-bar ─────────────────────────────────────────────────


def test_fidic_time_bar_notice_within_window() -> None:
    """Contractor notice issued 10 days after event — well within the 28d bar."""
    from app.modules.variations.service import check_fidic_time_bar

    out = check_fidic_time_bar(
        event_occurred_at="2026-01-01",
        notice_issued_at="2026-01-11",
    )
    assert out["within_time_bar"] is True
    assert out["days_elapsed"] == 10
    assert out["deadline_at"] == "2026-01-29"
    assert out["days_remaining"] is None


def test_fidic_time_bar_notice_beyond_window() -> None:
    """Notice issued 35 days after event — time-barred under Cl. 20.2.1."""
    from app.modules.variations.service import check_fidic_time_bar

    out = check_fidic_time_bar(
        event_occurred_at="2026-01-01",
        notice_issued_at="2026-02-05",
    )
    assert out["within_time_bar"] is False
    assert out["days_elapsed"] == 35


def test_fidic_time_bar_no_notice_yet_shows_remaining() -> None:
    from datetime import date as _d
    from datetime import timedelta as _td

    from app.modules.variations.service import check_fidic_time_bar

    # Event was 5 days ago — should show ~23 days remaining.
    event = (_d.today() - _td(days=5)).isoformat()
    out = check_fidic_time_bar(event_occurred_at=event, notice_issued_at=None)
    assert out["days_remaining"] is not None
    assert 22 <= int(out["days_remaining"]) <= 24


def test_fidic_time_bar_custom_window() -> None:
    from app.modules.variations.service import check_fidic_time_bar

    # NEC4 Cl 61.3 — 8 weeks (56d). Notice on day 60 is barred.
    out = check_fidic_time_bar(
        event_occurred_at="2026-01-01",
        notice_issued_at="2026-03-02",  # 60 days
        notice_window_days=56,
    )
    assert out["within_time_bar"] is False


# ── Schedule-of-rates re-rating ─────────────────────────────────────────


def test_rerate_within_threshold_keeps_contract_rate() -> None:
    from app.modules.variations.service import recommend_rerate

    out = recommend_rerate(boq_quantity=100, actual_quantity=110)
    assert out["rerate_required"] is False
    assert out["direction"] == "none"
    assert out["variance_pct"] == Decimal("10.00")


def test_rerate_increase_beyond_threshold() -> None:
    from app.modules.variations.service import recommend_rerate

    out = recommend_rerate(boq_quantity=100, actual_quantity=120)
    assert out["rerate_required"] is True
    assert out["direction"] == "increase"
    assert out["variance_pct"] == Decimal("20.00")


def test_rerate_decrease_beyond_threshold() -> None:
    from app.modules.variations.service import recommend_rerate

    out = recommend_rerate(boq_quantity=100, actual_quantity=80)
    assert out["rerate_required"] is True
    assert out["direction"] == "decrease"
    assert out["variance_pct"] == Decimal("-20.00")


def test_rerate_zero_boq_quantity_handled() -> None:
    from app.modules.variations.service import recommend_rerate

    out = recommend_rerate(boq_quantity=0, actual_quantity=50)
    assert out["rerate_required"] is True
    assert out["variance_pct"] == Decimal("100.00")
