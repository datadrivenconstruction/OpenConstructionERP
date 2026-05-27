"""Unit tests for the CRM module (:class:`CrmService` + pure helpers).

Scope:
    * Pure math helpers (compute_weighted_value, compute_win_rate, etc.)
    * Pure state-machine helpers (allowed_lead_transitions / allowed_opportunity_transitions)
    * Pipeline metrics + forecast aggregations
    * Lead lifecycle: qualify → convert
    * Opportunity lifecycle: stage transitions, win, lose
    * Permission registration

Repositories + event bus are stubbed; no real DB is touched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.crm.schemas import (
    AccountCreate,
    ActivityCreate,
    LeadConvertRequest,
    LeadCreate,
    OpportunityCreate,
    OpportunityUpdate,
    PipelineStageCreate,
    WinLossReasonCreate,
)
from app.modules.crm.service import (
    CrmService,
    allowed_lead_transitions,
    allowed_opportunity_transitions,
    compute_average_sales_cycle,
    compute_forecast,
    compute_lost_reasons_breakdown,
    compute_pipeline_metrics,
    compute_weighted_value,
    compute_win_rate,
    convert_opportunity_to_project_payload,
)

# ── Stubs ────────────────────────────────────────────────────────────────


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: None, scalars=lambda: _EmptyScalars())

    async def commit(self) -> None:
        pass


class _EmptyScalars:
    def all(self) -> list:
        return []


class _StubRepo:
    """Generic in-memory repository for any model."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, obj: Any) -> Any:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        obj.created_at = now
        obj.updated_at = now
        self.rows[obj.id] = obj
        return obj

    async def get_by_id(self, pk: uuid.UUID) -> Any:
        return self.rows.get(pk)

    async def list_all(self, **kwargs: Any) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        # Filter by simple equality kwargs (skip pagination keys)
        for key, val in kwargs.items():
            if key in ("offset", "limit", "due_before") or val is None:
                continue
            attr = "status" if key == "status" else key
            rows = [r for r in rows if getattr(r, attr, None) == val]
        return rows, len(rows)

    async def update_fields(self, pk: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(pk)
        if obj:
            for k, v in fields.items():
                setattr(obj, k, v)
            obj.updated_at = datetime.now(UTC)

    async def delete(self, pk: uuid.UUID) -> None:
        self.rows.pop(pk, None)


class _StubAccountRepo(_StubRepo):
    async def list_by_owner(self, owner_user_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.owner_user_id == owner_user_id]


class _StubLeadRepo(_StubRepo):
    async def find_by_email(self, email: str) -> Any:
        if not email:
            return None
        normalised = email.strip().lower()
        matches = [r for r in self.rows.values() if (getattr(r, "contact_email", None) or "").lower() == normalised]
        if not matches:
            return None
        matches.sort(key=lambda r: getattr(r, "created_at", None) or datetime.min, reverse=True)
        return matches[0]


class _StubOpportunityRepo(_StubRepo):
    async def list_by_owner(self, owner_user_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.owner_user_id == owner_user_id]

    async def list_by_stage(self, stage_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.stage_id == stage_id]

    async def list_open(self) -> list[Any]:
        return [r for r in self.rows.values() if r.status == "open"]

    async def list_won_between(self, start: str, end: str) -> list[Any]:
        return [r for r in self.rows.values() if r.status == "won" and r.won_at and start <= r.won_at <= end]

    async def list_lost_between(self, start: str, end: str) -> list[Any]:
        return [r for r in self.rows.values() if r.status == "lost" and r.lost_at and start <= r.lost_at <= end]


class _StubStageRepo(_StubRepo):
    def __init__(self) -> None:
        super().__init__()
        self.codes: dict[str, Any] = {}

    async def create(self, obj: Any) -> Any:
        obj = await super().create(obj)
        self.codes[obj.code] = obj
        return obj

    async def get_by_code(self, code: str) -> Any:
        return self.codes.get(code)

    async def list_all(self, **kwargs: Any) -> list[Any]:  # type: ignore[override]
        return sorted(self.rows.values(), key=lambda s: s.display_order)


class _StubHistoryRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, h: Any) -> Any:
        if getattr(h, "id", None) is None:
            h.id = uuid.uuid4()
        h.created_at = datetime.now(UTC)
        self.rows.append(h)
        return h

    async def list_for_opportunity(self, opportunity_id: uuid.UUID) -> list[Any]:
        return [h for h in self.rows if h.opportunity_id == opportunity_id]


class _StubActivityRepo(_StubRepo):
    pass


class _StubForecastRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def get_by_period(self, period: str, owner_user_id: uuid.UUID | None = None) -> Any:
        for r in self.rows:
            if r.period == period and r.owner_user_id == owner_user_id:
                return r
        return None

    async def create(self, f: Any) -> Any:
        if getattr(f, "id", None) is None:
            f.id = uuid.uuid4()
        f.created_at = datetime.now(UTC)
        f.updated_at = datetime.now(UTC)
        self.rows.append(f)
        return f

    async def upsert(self, f: Any) -> Any:
        existing = await self.get_by_period(f.period, f.owner_user_id)
        if existing is not None:
            existing.pipeline_value = f.pipeline_value
            existing.weighted_value = f.weighted_value
            existing.won_value = f.won_value
            existing.committed_value = f.committed_value
            existing.computed_at = f.computed_at
            return existing
        return await self.create(f)

    async def list_all(self) -> list[Any]:
        return list(self.rows)


class _StubReasonRepo(_StubRepo):
    def __init__(self) -> None:
        super().__init__()
        self.codes: dict[str, Any] = {}

    async def create(self, obj: Any) -> Any:
        obj = await super().create(obj)
        self.codes[obj.code] = obj
        return obj

    async def get_by_code(self, code: str) -> Any:
        return self.codes.get(code)


def _make_service() -> CrmService:
    svc = CrmService.__new__(CrmService)
    svc.session = _StubSession()
    svc.account_repo = _StubAccountRepo()
    svc.lead_repo = _StubLeadRepo()
    svc.opportunity_repo = _StubOpportunityRepo()
    svc.stage_repo = _StubStageRepo()
    svc.history_repo = _StubHistoryRepo()
    svc.activity_repo = _StubActivityRepo()
    svc.forecast_repo = _StubForecastRepo()
    svc.reason_repo = _StubReasonRepo()
    return svc


# ── Pure helper tests ────────────────────────────────────────────────────


def test_compute_weighted_value_basic() -> None:
    assert compute_weighted_value(1000, 50) == Decimal("500.00")
    assert compute_weighted_value(Decimal("1234.56"), 25) == Decimal("308.64")


def test_compute_weighted_value_clamping() -> None:
    assert compute_weighted_value(1000, -10) == Decimal("0.00")
    assert compute_weighted_value(1000, 250) == Decimal("1000.00")


def test_compute_weighted_value_zero_probability() -> None:
    assert compute_weighted_value(99999, 0) == Decimal("0.00")


def test_compute_weighted_value_rounding() -> None:
    # 333.33 * 33 / 100 = 109.9989 → 110.00 (round half-up)
    assert compute_weighted_value(Decimal("333.33"), 33) == Decimal("110.00")


def test_allowed_lead_transitions() -> None:
    assert allowed_lead_transitions("new") == {"qualifying", "disqualified"}
    assert allowed_lead_transitions("qualifying") == {"qualified", "disqualified"}
    assert allowed_lead_transitions("qualified") == {"converted", "disqualified"}
    assert allowed_lead_transitions("disqualified") == set()
    assert allowed_lead_transitions("converted") == set()
    assert allowed_lead_transitions("nonsense") == set()


def test_allowed_opportunity_transitions() -> None:
    assert allowed_opportunity_transitions("open") == {"won", "lost", "abandoned"}
    assert allowed_opportunity_transitions("won") == set()
    assert allowed_opportunity_transitions("lost") == set()
    assert allowed_opportunity_transitions("abandoned") == set()


def test_compute_pipeline_metrics_empty() -> None:
    out = compute_pipeline_metrics([])
    assert out["open_count"] == 0
    assert out["weighted_value"] == Decimal("0.00")
    assert out["total_value"] == Decimal("0.00")
    assert out["by_stage"] == {}
    assert out["win_rate_30d"] == Decimal("0.00")


def test_compute_pipeline_metrics_mixed_stages() -> None:
    stage_a = uuid.uuid4()
    stage_b = uuid.uuid4()
    opps = [
        SimpleNamespace(
            status="open",
            stage_id=stage_a,
            estimated_value=Decimal("1000"),
            weighted_value=Decimal("500"),
            probability_percent=50,
            won_at=None,
            lost_at=None,
        ),
        SimpleNamespace(
            status="open",
            stage_id=stage_a,
            estimated_value=Decimal("2000"),
            weighted_value=Decimal("1500"),
            probability_percent=75,
            won_at=None,
            lost_at=None,
        ),
        SimpleNamespace(
            status="open",
            stage_id=stage_b,
            estimated_value=Decimal("500"),
            weighted_value=Decimal("100"),
            probability_percent=20,
            won_at=None,
            lost_at=None,
        ),
        SimpleNamespace(
            status="won",
            stage_id=stage_a,
            estimated_value=Decimal("9999"),
            weighted_value=Decimal("9999"),
            probability_percent=100,
            won_at=datetime.now(UTC).date().isoformat(),
            lost_at=None,
        ),
    ]
    out = compute_pipeline_metrics(opps)
    assert out["open_count"] == 3
    assert out["total_value"] == Decimal("3500.00")
    assert out["weighted_value"] == Decimal("2100.00")
    assert str(stage_a) in out["by_stage"]
    assert out["by_stage"][str(stage_a)]["count"] == 2
    assert out["by_stage"][str(stage_b)]["count"] == 1


def test_compute_pipeline_metrics_win_rate_30d() -> None:
    today = datetime.now(UTC).date()
    recent_won = today.isoformat()
    recent_lost = (today - timedelta(days=10)).isoformat()
    old_won = (today - timedelta(days=200)).isoformat()
    opps = [
        SimpleNamespace(
            status="won",
            stage_id=uuid.uuid4(),
            estimated_value=Decimal("100"),
            weighted_value=Decimal("100"),
            probability_percent=100,
            won_at=recent_won,
            lost_at=None,
        ),
        SimpleNamespace(
            status="lost",
            stage_id=uuid.uuid4(),
            estimated_value=Decimal("100"),
            weighted_value=Decimal("0"),
            probability_percent=0,
            won_at=None,
            lost_at=recent_lost,
        ),
        SimpleNamespace(
            status="won",
            stage_id=uuid.uuid4(),
            estimated_value=Decimal("100"),
            weighted_value=Decimal("100"),
            probability_percent=100,
            won_at=old_won,
            lost_at=None,
        ),
    ]
    out = compute_pipeline_metrics(opps)
    # 1 recent won / (1 won + 1 lost) = 50%
    assert out["win_rate_30d"] == Decimal("50.00")


def test_compute_forecast_filtering_by_period() -> None:
    in_period = SimpleNamespace(
        status="open",
        estimated_value=Decimal("1000"),
        weighted_value=Decimal("500"),
        probability_percent=50,
        expected_close_date="2026-05-15",
        won_at=None,
        lost_at=None,
    )
    out_of_period = SimpleNamespace(
        status="open",
        estimated_value=Decimal("9999"),
        weighted_value=Decimal("9999"),
        probability_percent=100,
        expected_close_date="2025-12-01",
        won_at=None,
        lost_at=None,
    )
    won_in_period = SimpleNamespace(
        status="won",
        estimated_value=Decimal("2000"),
        weighted_value=Decimal("2000"),
        probability_percent=100,
        expected_close_date="2026-06-01",
        won_at="2026-06-01",
        lost_at=None,
    )
    result = compute_forecast([in_period, out_of_period, won_in_period], "2026-Q2")
    assert result["period"] == "2026-Q2"
    assert result["pipeline_value"] == Decimal("3000.00")  # 1000 + 2000 won
    assert result["weighted_value"] == Decimal("2500.00")  # 500 + 2000
    assert result["won_value"] == Decimal("2000.00")
    # in_period prob=50 < 80 → not committed; won always committed
    assert result["committed_value"] == Decimal("2000.00")


def test_compute_forecast_committed_threshold() -> None:
    committed = SimpleNamespace(
        status="open",
        estimated_value=Decimal("1000"),
        weighted_value=Decimal("800"),
        probability_percent=80,
        expected_close_date="2026-04-15",
        won_at=None,
        lost_at=None,
    )
    not_committed = SimpleNamespace(
        status="open",
        estimated_value=Decimal("1000"),
        weighted_value=Decimal("790"),
        probability_percent=79,
        expected_close_date="2026-04-15",
        won_at=None,
        lost_at=None,
    )
    result = compute_forecast([committed, not_committed], "2026-Q2")
    # Both close in May? 04-15 is in Q2 (Apr-Jun). Yes.
    assert result["pipeline_value"] == Decimal("2000.00")
    assert result["committed_value"] == Decimal("1000.00")


def test_compute_forecast_bad_period_format() -> None:
    with pytest.raises(ValueError, match="Invalid period format"):
        compute_forecast([], "2026/Q2")


def test_compute_forecast_bad_quarter() -> None:
    with pytest.raises(ValueError, match="Invalid quarter"):
        compute_forecast([], "2026-Q9")


def test_compute_win_rate_zero_division() -> None:
    assert compute_win_rate([], None, None) == Decimal("0.00")
    # Only open opportunities — denominator zero
    opps = [SimpleNamespace(status="open", won_at=None, lost_at=None)]
    assert compute_win_rate(opps, None, None) == Decimal("0.00")


def test_compute_win_rate_basic() -> None:
    opps = [
        SimpleNamespace(status="won", won_at="2026-04-01", lost_at=None),
        SimpleNamespace(status="won", won_at="2026-04-05", lost_at=None),
        SimpleNamespace(status="won", won_at="2026-04-10", lost_at=None),
        SimpleNamespace(status="lost", won_at=None, lost_at="2026-04-02"),
    ]
    assert compute_win_rate(opps, "2026-04-01", "2026-04-30") == Decimal("75.00")


def test_compute_win_rate_window_filter() -> None:
    opps = [
        SimpleNamespace(status="won", won_at="2026-04-01", lost_at=None),
        SimpleNamespace(status="lost", won_at=None, lost_at="2025-12-01"),  # filtered out
    ]
    assert compute_win_rate(opps, "2026-01-01", "2026-12-31") == Decimal("100.00")


def test_compute_average_sales_cycle_empty() -> None:
    assert compute_average_sales_cycle([]) == 0
    assert (
        compute_average_sales_cycle(
            [SimpleNamespace(status="open", created_at=datetime.now(UTC), won_at=None, lost_at=None)]
        )
        == 0
    )


def test_compute_average_sales_cycle_basic() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    opps = [
        SimpleNamespace(status="won", created_at=base, won_at="2026-01-11", lost_at=None),  # 10 days
        SimpleNamespace(status="lost", created_at=base, won_at=None, lost_at="2026-01-21"),  # 20 days
        SimpleNamespace(status="won", created_at=base, won_at="2026-01-31", lost_at=None),  # 30 days
    ]
    assert compute_average_sales_cycle(opps) == 20  # (10+20+30)/3


def test_compute_lost_reasons_breakdown_empty() -> None:
    assert compute_lost_reasons_breakdown([], None, None) == {}


def test_compute_lost_reasons_breakdown_basic() -> None:
    opps = [
        SimpleNamespace(status="lost", lost_at="2026-04-01", lost_reason_code="price_too_high"),
        SimpleNamespace(status="lost", lost_at="2026-04-15", lost_reason_code="price_too_high"),
        SimpleNamespace(status="lost", lost_at="2026-04-20", lost_reason_code="competitor_won"),
        SimpleNamespace(status="won", lost_at=None, lost_reason_code=None),
    ]
    breakdown = compute_lost_reasons_breakdown(opps, "2026-04-01", "2026-04-30")
    assert breakdown == {"price_too_high": 2, "competitor_won": 1}


def test_convert_opportunity_to_project_payload() -> None:
    opp = SimpleNamespace(
        id=uuid.uuid4(),
        title="ACME headquarters build",
        description="3-storey HQ",
        estimated_value=Decimal("1500000"),
        currency="EUR",
        owner_user_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
    )
    payload = convert_opportunity_to_project_payload(opp)
    assert payload["name"] == "ACME headquarters build"
    # v4.3.0 audit: estimated_value is now a Decimal-as-string to avoid the
    # binary-rounding hop into the Projects subscriber.
    assert payload["estimated_value"] == "1500000"
    assert payload["currency"] == "EUR"
    assert payload["source_module"] == "crm"
    assert payload["source_entity"] == "opportunity"
    assert payload["source_id"] == str(opp.id)


# ── Service: accounts ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_account() -> None:
    svc = _make_service()
    account = await svc.create_account(AccountCreate(name="ACME Construction", industry="Commercial"))
    assert account.id is not None
    assert account.name == "ACME Construction"
    assert account.status == "active"


@pytest.mark.asyncio
async def test_get_account_not_found() -> None:
    svc = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_account(uuid.uuid4())
    assert exc_info.value.status_code == 404


# ── Service: leads ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_lead() -> None:
    svc = _make_service()
    lead = await svc.create_lead(LeadCreate(contact_name="Jane Doe", contact_email="jane@example.com"))
    assert lead.id is not None
    assert lead.status == "new"


@pytest.mark.asyncio
async def test_qualify_lead_new_to_qualifying() -> None:
    svc = _make_service()
    lead = await svc.create_lead(LeadCreate(contact_name="Jane"))
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        out = await svc.qualify_lead(lead.id, "Sounds promising")
    assert out.status == "qualifying"


@pytest.mark.asyncio
async def test_qualify_lead_qualifying_to_qualified() -> None:
    svc = _make_service()
    lead = await svc.create_lead(LeadCreate(contact_name="Jane"))
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        await svc.qualify_lead(lead.id, "step 1")
        out = await svc.qualify_lead(lead.id, "step 2")
    assert out.status == "qualified"
    assert out.qualified_at is not None


@pytest.mark.asyncio
async def test_qualify_lead_invalid_state() -> None:
    svc = _make_service()
    lead = await svc.create_lead(LeadCreate(contact_name="Jane", status="disqualified"))
    with pytest.raises(HTTPException) as exc_info:
        await svc.qualify_lead(lead.id, "won't work")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_convert_lead_creates_opportunity() -> None:
    svc = _make_service()
    stage = await svc.create_stage(
        PipelineStageCreate(code="qualified", name="Qualified", default_probability_percent=25)
    )
    account = await svc.create_account(AccountCreate(name="Acme"))
    lead = await svc.create_lead(LeadCreate(contact_name="Jane"))
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        await svc.qualify_lead(lead.id, "step 1")
        await svc.qualify_lead(lead.id, "step 2")  # → qualified
        _, opp = await svc.convert_lead(
            lead.id,
            LeadConvertRequest(
                account_id=account.id,
                title="Big build",
                estimated_value=Decimal("100000"),
                stage_id=stage.id,
                probability_percent=25,
            ),
        )
    assert opp.id is not None
    refreshed_lead = svc.lead_repo.rows[lead.id]
    assert refreshed_lead.status == "converted"
    assert refreshed_lead.converted_opportunity_id == opp.id


@pytest.mark.asyncio
async def test_convert_lead_not_qualified_fails() -> None:
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="qualified", name="Qualified"))
    account = await svc.create_account(AccountCreate(name="Acme"))
    lead = await svc.create_lead(LeadCreate(contact_name="Jane"))  # status=new
    with pytest.raises(HTTPException) as exc_info:
        await svc.convert_lead(
            lead.id,
            LeadConvertRequest(account_id=account.id, title="No", stage_id=stage.id),
        )
    assert exc_info.value.status_code == 400


# ── Service: opportunities ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_opportunity_auto_weighted_value() -> None:
    svc = _make_service()
    stage = await svc.create_stage(
        PipelineStageCreate(code="proposal", name="Proposal", default_probability_percent=50)
    )
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(
        OpportunityCreate(
            account_id=account.id,
            title="Build a tower",
            estimated_value=Decimal("10000"),
            probability_percent=40,
            stage_id=stage.id,
        )
    )
    # weighted = 10000 * 40 / 100 = 4000
    assert opp.weighted_value == Decimal("4000.00")


@pytest.mark.asyncio
async def test_create_opportunity_invalid_stage_fails() -> None:
    svc = _make_service()
    account = await svc.create_account(AccountCreate(name="Acme"))
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_opportunity(
            OpportunityCreate(
                account_id=account.id,
                title="X",
                stage_id=uuid.uuid4(),  # bogus
            )
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_transition_opportunity_stage_valid() -> None:
    svc = _make_service()
    stage_a = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead", default_probability_percent=10))
    stage_b = await svc.create_stage(
        PipelineStageCreate(code="proposal", name="Proposal", default_probability_percent=60)
    )
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(
        OpportunityCreate(
            account_id=account.id,
            title="X",
            estimated_value=Decimal("1000"),
            probability_percent=10,
            stage_id=stage_a.id,
        )
    )
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        out = await svc.transition_opportunity_stage(opp.id, stage_b.id)

    assert out.stage_id == stage_b.id
    # Probability auto-updated to stage default
    assert out.probability_percent == 60
    # Weighted re-calculated
    assert out.weighted_value == Decimal("600.00")
    # History entry created (initial + new = 2 entries)
    hist = await svc.history_repo.list_for_opportunity(opp.id)
    assert len(hist) == 2


@pytest.mark.asyncio
async def test_transition_opportunity_stage_override_probability() -> None:
    svc = _make_service()
    stage_a = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead", default_probability_percent=10))
    stage_b = await svc.create_stage(
        PipelineStageCreate(code="proposal", name="Proposal", default_probability_percent=60)
    )
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(
        OpportunityCreate(account_id=account.id, title="X", estimated_value=Decimal("1000"), stage_id=stage_a.id)
    )
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        out = await svc.transition_opportunity_stage(opp.id, stage_b.id, override_probability_percent=33)
    assert out.probability_percent == 33
    assert out.weighted_value == Decimal("330.00")


@pytest.mark.asyncio
async def test_transition_opportunity_stage_to_final_won_blocked() -> None:
    """Moving directly to a won-final stage via move-stage must be blocked."""
    svc = _make_service()
    stage_open = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead"))
    stage_won = await svc.create_stage(
        PipelineStageCreate(
            code="won_stage",
            name="Won",
            is_final=True,
            is_won=True,
        )
    )
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(OpportunityCreate(account_id=account.id, title="X", stage_id=stage_open.id))
    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_opportunity_stage(opp.id, stage_won.id)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_transition_opportunity_non_open_fails() -> None:
    svc = _make_service()
    stage_a = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead"))
    stage_b = await svc.create_stage(PipelineStageCreate(code="proposal", name="Proposal"))
    reason = await svc.create_reason(WinLossReasonCreate(code="r", label="r", is_loss_reason=True))
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(OpportunityCreate(account_id=account.id, title="X", stage_id=stage_a.id))
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        await svc.lose_opportunity(opp.id, reason.code)

    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_opportunity_stage(opp.id, stage_b.id)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_win_opportunity() -> None:
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="proposal", name="Proposal"))
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(
        OpportunityCreate(
            account_id=account.id,
            title="X",
            estimated_value=Decimal("5000"),
            stage_id=stage.id,
        )
    )
    mock_publish = MagicMock()
    with patch("app.modules.crm.service.event_bus.publish_detached", mock_publish):
        out = await svc.win_opportunity(opp.id)
    assert out.status == "won"
    assert out.probability_percent == 100
    assert out.weighted_value == Decimal("5000.00")
    assert out.won_at is not None
    # Event emitted
    assert any(c.args[0] == "crm.opportunity.won" for c in mock_publish.call_args_list)


@pytest.mark.asyncio
async def test_win_opportunity_invalid_state() -> None:
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead"))
    reason = await svc.create_reason(WinLossReasonCreate(code="r", label="r", is_loss_reason=True))
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(OpportunityCreate(account_id=account.id, title="X", stage_id=stage.id))
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        await svc.lose_opportunity(opp.id, reason.code)

    with pytest.raises(HTTPException) as exc_info:
        await svc.win_opportunity(opp.id)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_lose_opportunity_with_reason() -> None:
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="proposal", name="Proposal"))
    reason = await svc.create_reason(
        WinLossReasonCreate(code="price_too_high", label="Too pricey", is_loss_reason=True)
    )
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(OpportunityCreate(account_id=account.id, title="X", stage_id=stage.id))
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        out = await svc.lose_opportunity(opp.id, reason.code)
    assert out.status == "lost"
    assert out.lost_reason_code == "price_too_high"
    assert out.probability_percent == 0
    assert out.weighted_value == Decimal("0")
    assert out.lost_at is not None


@pytest.mark.asyncio
async def test_lose_opportunity_unknown_reason_fails() -> None:
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="proposal", name="Proposal"))
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(OpportunityCreate(account_id=account.id, title="X", stage_id=stage.id))
    with pytest.raises(HTTPException) as exc_info:
        await svc.lose_opportunity(opp.id, "nonexistent")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_opportunity_invalid_status_transition() -> None:
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead"))
    reason = await svc.create_reason(WinLossReasonCreate(code="r", label="r", is_loss_reason=True))
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(OpportunityCreate(account_id=account.id, title="X", stage_id=stage.id))
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        await svc.lose_opportunity(opp.id, reason.code)

    # Try to flip a lost → won — must fail
    with pytest.raises(HTTPException) as exc_info:
        await svc.update_opportunity(opp.id, OpportunityUpdate(status="won"))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_opportunity_direct_won_blocked() -> None:
    """Generic PATCH must NOT flip an open opp to 'won' — the dedicated
    win endpoint stamps won_at + emits the project-creation event; a raw
    status change would silently skip all of that."""
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead"))
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(OpportunityCreate(account_id=account.id, title="X", stage_id=stage.id))
    for terminal in ("won", "lost"):
        with pytest.raises(HTTPException) as exc_info:
            await svc.update_opportunity(
                opp.id,
                OpportunityUpdate(status=terminal),  # type: ignore[arg-type]
            )
        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_opportunity_abandon_still_allowed() -> None:
    """``abandoned`` has no dedicated endpoint and no mandatory side
    effects — it must remain reachable via the generic update path."""
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead"))
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(OpportunityCreate(account_id=account.id, title="X", stage_id=stage.id))
    out = await svc.update_opportunity(opp.id, OpportunityUpdate(status="abandoned"))
    assert out.status == "abandoned"


@pytest.mark.asyncio
async def test_create_opportunity_invalid_account_fails() -> None:
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead"))
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_opportunity(
            OpportunityCreate(
                account_id=uuid.uuid4(),  # not created
                title="X",
                stage_id=stage.id,
            )
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_convert_lead_invalid_account_fails() -> None:
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="qualified", name="Qualified"))
    lead = await svc.create_lead(LeadCreate(contact_name="Jane"))
    with patch("app.modules.crm.service.event_bus.publish_detached"):
        await svc.qualify_lead(lead.id, "step 1")
        await svc.qualify_lead(lead.id, "step 2")  # → qualified
        with pytest.raises(HTTPException) as exc_info:
            await svc.convert_lead(
                lead.id,
                LeadConvertRequest(
                    account_id=uuid.uuid4(),  # not created
                    title="Big build",
                    stage_id=stage.id,
                ),
            )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_opportunity_recomputes_weighted_value() -> None:
    svc = _make_service()
    stage = await svc.create_stage(PipelineStageCreate(code="lead", name="Lead"))
    account = await svc.create_account(AccountCreate(name="Acme"))
    opp = await svc.create_opportunity(
        OpportunityCreate(
            account_id=account.id,
            title="X",
            estimated_value=Decimal("1000"),
            probability_percent=10,
            stage_id=stage.id,
        )
    )
    out = await svc.update_opportunity(opp.id, OpportunityUpdate(probability_percent=75))
    assert out.weighted_value == Decimal("750.00")


# ── Service: activities ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_activity() -> None:
    svc = _make_service()
    activity = await svc.create_activity(ActivityCreate(kind="call", subject="First contact"))
    assert activity.id is not None
    assert activity.kind == "call"


# ── Repository CRUD basics ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_repo_crud_roundtrip() -> None:
    svc = _make_service()
    account = await svc.create_account(AccountCreate(name="ACME"))
    fetched = await svc.account_repo.get_by_id(account.id)
    assert fetched is account
    await svc.account_repo.update_fields(account.id, name="ACME 2")
    fetched2 = await svc.account_repo.get_by_id(account.id)
    assert fetched2.name == "ACME 2"
    await svc.account_repo.delete(account.id)
    assert await svc.account_repo.get_by_id(account.id) is None


# ── Permission registration ──────────────────────────────────────────────


def test_crm_permissions_registered() -> None:
    """All 10 CRM permissions land in the registry at registration time."""
    from app.core.permissions import permission_registry
    from app.modules.crm.permissions import register_crm_permissions

    register_crm_permissions()
    expected = {
        "crm.read",
        "crm.create",
        "crm.update",
        "crm.delete",
        "crm.qualify_lead",
        "crm.convert_lead",
        "crm.move_stage",
        "crm.win_opportunity",
        "crm.lose_opportunity",
        "crm.compute_forecast",
    }
    registered = set(permission_registry._permissions.keys())  # type: ignore[attr-defined]
    missing = expected - registered
    assert not missing, f"Missing CRM permissions: {missing}"


# ── New (Wave-5): BANT scoring ──────────────────────────────────────────


def test_compute_opportunity_score_default_weights_hot() -> None:
    from app.modules.crm.service import compute_opportunity_score

    score = compute_opportunity_score(
        budget_score=100,
        authority_score=100,
        need_score=100,
        timeline_score=100,
    )
    assert score["total"] == 100.0
    assert score["band"] == "hot"
    assert score["budget"] == 100


def test_compute_opportunity_score_warm_band() -> None:
    from app.modules.crm.service import compute_opportunity_score

    score = compute_opportunity_score(
        budget_score=80,
        authority_score=80,
        need_score=70,
        timeline_score=60,
    )
    # 80*30 + 80*25 + 70*25 + 60*20 = 2400 + 2000 + 1750 + 1200 = 7350 / 100 = 73.5
    assert score["total"] == 73.5
    assert score["band"] == "warm"


def test_compute_opportunity_score_cold_band() -> None:
    from app.modules.crm.service import compute_opportunity_score

    score = compute_opportunity_score(
        budget_score=20,
        authority_score=20,
        need_score=20,
        timeline_score=20,
    )
    assert score["total"] == 20.0
    assert score["band"] == "cold"


def test_compute_opportunity_score_clamps_oversized_inputs() -> None:
    from app.modules.crm.service import compute_opportunity_score

    score = compute_opportunity_score(
        budget_score=999,
        authority_score=-5,
        need_score="abc",
        timeline_score=50,
    )
    assert score["budget"] == 100
    assert score["authority"] == 0
    assert score["need"] == 0
    assert score["timeline"] == 50


def test_compute_opportunity_score_custom_weights_normalise() -> None:
    from app.modules.crm.service import compute_opportunity_score

    score = compute_opportunity_score(
        budget_score=100,
        authority_score=0,
        need_score=0,
        timeline_score=0,
        weights={"budget": 50, "authority": 50, "need": 0, "timeline": 0},
    )
    # After normalisation weights should be {budget:50, authority:50, need:0, timeline:0}
    # so the total should be 50 (50% × 100).
    assert score["total"] == 50.0


# ── Account hierarchy tree ──────────────────────────────────────────────


def test_build_account_tree_two_levels() -> None:
    from app.modules.crm.service import build_account_tree

    parent_id = uuid.uuid4()
    child_a_id = uuid.uuid4()
    child_b_id = uuid.uuid4()
    accounts = [
        SimpleNamespace(
            id=parent_id,
            parent_account_id=None,
            name="Parent Owner",
            role="owner",
            status="active",
            industry=None,
            country="DE",
        ),
        SimpleNamespace(
            id=child_a_id,
            parent_account_id=parent_id,
            name="GC Alpha",
            role="general_contractor",
            status="active",
            industry=None,
            country="DE",
        ),
        SimpleNamespace(
            id=child_b_id,
            parent_account_id=parent_id,
            name="GC Beta",
            role="general_contractor",
            status="active",
            industry=None,
            country="DE",
        ),
    ]
    tree = build_account_tree(accounts)
    assert len(tree) == 1
    assert tree[0]["name"] == "Parent Owner"
    child_names = {c["name"] for c in tree[0]["children"]}
    assert child_names == {"GC Alpha", "GC Beta"}


def test_build_account_tree_handles_orphan_as_root() -> None:
    """Accounts whose parent is missing from the input become roots."""
    from app.modules.crm.service import build_account_tree

    missing_parent = uuid.uuid4()
    child_id = uuid.uuid4()
    accounts = [
        SimpleNamespace(
            id=child_id,
            parent_account_id=missing_parent,
            name="Orphan",
            role="subcontractor",
            status="active",
            industry=None,
            country=None,
        ),
    ]
    tree = build_account_tree(accounts)
    assert len(tree) == 1
    assert tree[0]["name"] == "Orphan"


# ── Stage-weighted forecast ─────────────────────────────────────────────


def test_compute_stage_weighted_forecast_groups_by_stage() -> None:
    from app.modules.crm.service import compute_stage_weighted_forecast

    stage1 = uuid.uuid4()
    stage2 = uuid.uuid4()
    stages = {
        stage1: SimpleNamespace(id=stage1, name="Qualification", code="qual", default_probability_percent=10),
        stage2: SimpleNamespace(id=stage2, name="Proposal", code="prop", default_probability_percent=50),
    }
    opps = [
        SimpleNamespace(
            stage_id=stage1,
            status="open",
            estimated_value=Decimal("100000"),
            probability_percent=10,
            weighted_value=Decimal("10000"),
        ),
        SimpleNamespace(
            stage_id=stage2,
            status="open",
            estimated_value=Decimal("200000"),
            probability_percent=50,
            weighted_value=Decimal("100000"),
        ),
        SimpleNamespace(
            stage_id=stage1,
            status="won",
            estimated_value=Decimal("50000"),
            probability_percent=100,
            weighted_value=Decimal("50000"),
        ),
    ]
    result = compute_stage_weighted_forecast(opps, stages)
    assert result["grand_total"] == Decimal("300000.00")  # excludes the won one
    assert result["grand_weighted"] == Decimal("110000.00")
    s1_bucket = result["by_stage"][str(stage1)]
    assert s1_bucket["count"] == 1
    assert s1_bucket["stage_name"] == "Qualification"
    s2_bucket = result["by_stage"][str(stage2)]
    assert s2_bucket["total"] == Decimal("200000.00")
