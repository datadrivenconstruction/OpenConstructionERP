"""Unit tests for the Bid Management module.

Covers:
    * Pure helpers (compute_submission_total, compute_completeness_score,
      validate_submission_pre_open, validate_late_submission,
      normalize_submission_for_leveling, rank_bids, recommend_bidder,
      compute_bid_summary).
    * State machine transition rules.
    * Service orchestration (publish_package, open_bids, disqualify_bidder,
      award_package — with auto-rejection).
    * Repository CRUD basics via stubs.
    * Permission constants are registered.

Repositories and event bus are stubbed so the tests don't touch the DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.bid_management.schemas import (
    BidAwardCreate,
    BidPackageCreate,
)
from app.modules.bid_management.service import (
    BidManagementService,
    allowed_invitation_transitions,
    allowed_package_transitions,
    compute_bid_summary,
    compute_completeness_score,
    compute_submission_total,
    normalize_submission_for_leveling,
    rank_bids,
    recommend_bidder,
    validate_late_submission,
    validate_submission_pre_open,
)

PROJECT_ID = uuid.uuid4()


# ── Stub plumbing ─────────────────────────────────────────────────────────


class _StubSession:
    """Minimal AsyncSession-shaped stub."""

    def __init__(self) -> None:
        self._pending_add: list[Any] = []

    def add(self, obj: Any) -> None:
        self._pending_add.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self._pending_add.extend(objs)

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        return None

    def expire_all(self) -> None:
        return None

    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalars=lambda: SimpleNamespace(all=lambda: []),
            scalar_one=lambda: 0,
        )

    async def get(self, _model: Any, _id: Any) -> Any:
        return None


class _StubRepo:
    """Generic in-memory repo stub keyed by uuid."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, obj: Any) -> Any:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        obj.created_at = now
        obj.updated_at = now
        self.rows[obj.id] = obj
        return obj

    async def get_by_id(self, entity_id: uuid.UUID) -> Any:
        return self.rows.get(entity_id)

    async def update_fields(self, entity_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(entity_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)
        obj.updated_at = datetime.now(UTC)

    async def delete(self, entity_id: uuid.UUID) -> None:
        self.rows.pop(entity_id, None)

    async def bulk_create(self, items: list[Any]) -> list[Any]:
        for item in items:
            await self.create(item)
        return items


class _StubPackageRepo(_StubRepo):
    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def get_by_code(self, code: str) -> Any:
        for row in self.rows.values():
            if getattr(row, "code", None) == code:
                return row
        return None


class _StubLineRepo(_StubRepo):
    async def list_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.package_id == package_id]


class _StubInvitationRepo(_StubRepo):
    async def list_for_package(self, package_id: uuid.UUID, *, status: str | None = None) -> list[Any]:
        rows = [r for r in self.rows.values() if r.package_id == package_id]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows

    async def invitations_pending(self, package_id: uuid.UUID) -> list[Any]:
        return [
            r for r in self.rows.values() if r.package_id == package_id and r.status in ("pending", "sent", "opened")
        ]


class _StubBidderRepo(_StubRepo):
    async def list_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.package_id == package_id]


class _StubSubmissionRepo(_StubRepo):
    async def submissions_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "_package_id", None) == package_id]

    async def get_by_invitation(self, invitation_id: uuid.UUID) -> Any:
        for row in self.rows.values():
            if getattr(row, "invitation_id", None) == invitation_id:
                return row
        return None


class _StubSubmissionLineRepo(_StubRepo):
    async def list_for_submission(self, submission_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.submission_id == submission_id]


class _StubQARepo(_StubRepo):
    async def q_and_a_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.package_id == package_id]


class _StubComparisonRepo(_StubRepo):
    async def get_for_package(self, package_id: uuid.UUID) -> Any:
        for row in self.rows.values():
            if row.package_id == package_id:
                return row
        return None


class _StubLevelingRepo(_StubRepo):
    async def levelings_for_comparison(self, comparison_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.comparison_id == comparison_id]

    async def delete_for_comparison(self, comparison_id: uuid.UUID) -> None:
        kill = [k for k, v in self.rows.items() if v.comparison_id == comparison_id]
        for k in kill:
            self.rows.pop(k, None)


class _StubAwardRepo(_StubRepo):
    async def get_for_package(self, package_id: uuid.UUID) -> Any:
        for row in self.rows.values():
            if row.package_id == package_id:
                return row
        return None


class _StubRejectionRepo(_StubRepo):
    async def list_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.package_id == package_id]


def _make_service() -> BidManagementService:
    svc = BidManagementService.__new__(BidManagementService)
    svc.session = _StubSession()
    svc.package_repo = _StubPackageRepo()
    svc.line_repo = _StubLineRepo()
    svc.invitation_repo = _StubInvitationRepo()
    svc.bidder_repo = _StubBidderRepo()
    svc.submission_repo = _StubSubmissionRepo()
    svc.submission_line_repo = _StubSubmissionLineRepo()
    svc.qa_repo = _StubQARepo()
    svc.comparison_repo = _StubComparisonRepo()
    svc.leveling_repo = _StubLevelingRepo()
    svc.award_repo = _StubAwardRepo()
    svc.rejection_repo = _StubRejectionRepo()
    return svc


def _line(line_id: uuid.UUID, code: str = "01", mandatory: bool = True) -> Any:
    return SimpleNamespace(id=line_id, code=code, is_mandatory=mandatory)


def _sub_line(line_item_id: uuid.UUID, unit_price: str, qty: str = "1") -> Any:
    return SimpleNamespace(
        line_item_id=line_item_id,
        unit_price=Decimal(unit_price),
        quantity_priced=Decimal(qty),
        total_price=Decimal(unit_price) * Decimal(qty),
    )


# ── Pure helpers: compute_submission_total ────────────────────────────────


def test_compute_submission_total_math() -> None:
    lines = [
        _sub_line(uuid.uuid4(), "100", "2"),  # 200
        _sub_line(uuid.uuid4(), "50.5", "4"),  # 202
    ]
    assert compute_submission_total(lines) == Decimal("402.00")


def test_compute_submission_total_empty() -> None:
    assert compute_submission_total([]) == Decimal("0.00")


def test_compute_submission_total_zero_priced() -> None:
    lines = [_sub_line(uuid.uuid4(), "0", "10")]
    assert compute_submission_total(lines) == Decimal("0.00")


# ── compute_completeness_score ────────────────────────────────────────────


def test_completeness_100_percent() -> None:
    l1, l2 = uuid.uuid4(), uuid.uuid4()
    pkg = [_line(l1), _line(l2)]
    sub = [_sub_line(l1, "10"), _sub_line(l2, "20")]
    assert compute_completeness_score(sub, pkg) == Decimal("100.00")


def test_completeness_partial() -> None:
    l1, l2, l3, l4 = (uuid.uuid4() for _ in range(4))
    pkg = [_line(l1), _line(l2), _line(l3), _line(l4)]
    sub = [_sub_line(l1, "10"), _sub_line(l2, "20")]  # 2 of 4
    assert compute_completeness_score(sub, pkg) == Decimal("50.00")


def test_completeness_zero() -> None:
    l1, l2 = uuid.uuid4(), uuid.uuid4()
    pkg = [_line(l1), _line(l2)]
    assert compute_completeness_score([], pkg) == Decimal("0.00")


def test_completeness_ignores_optional_lines() -> None:
    l1, l2 = uuid.uuid4(), uuid.uuid4()
    pkg = [_line(l1, mandatory=True), _line(l2, mandatory=False)]
    sub = [_sub_line(l1, "10")]
    assert compute_completeness_score(sub, pkg) == Decimal("100.00")


# ── validate_submission_pre_open ──────────────────────────────────────────


def _package(deadline: datetime | None = None, currency: str = "EUR") -> Any:
    return SimpleNamespace(
        submission_deadline=deadline.isoformat() if deadline else None,
        currency=currency,
    )


def _submission(submitted_at: datetime, currency: str = "EUR") -> Any:
    return SimpleNamespace(
        submitted_at=submitted_at.isoformat(),
        currency=currency,
        total_amount=Decimal("1000"),
    )


def test_validate_pre_open_ok() -> None:
    now = datetime.now(UTC)
    deadline = now + timedelta(hours=1)
    sub_time = now
    l1 = uuid.uuid4()
    pkg = _package(deadline=deadline)
    sub = _submission(sub_time)
    pkg_lines = [_line(l1)]
    sub_lines = [_sub_line(l1, "1000")]
    is_valid, errors = validate_submission_pre_open(sub, pkg, sub_lines, pkg_lines, now=now)
    assert is_valid is True
    assert errors == []


def test_validate_pre_open_after_deadline() -> None:
    now = datetime.now(UTC)
    deadline = now - timedelta(hours=2)
    sub_time = now
    l1 = uuid.uuid4()
    pkg = _package(deadline=deadline)
    sub = _submission(sub_time)
    pkg_lines = [_line(l1)]
    sub_lines = [_sub_line(l1, "1000")]
    is_valid, errors = validate_submission_pre_open(sub, pkg, sub_lines, pkg_lines, now=now)
    assert is_valid is False
    assert "submission_after_deadline" in errors


def test_validate_pre_open_missing_mandatory() -> None:
    now = datetime.now(UTC)
    deadline = now + timedelta(hours=2)
    l1, l2 = uuid.uuid4(), uuid.uuid4()
    pkg = _package(deadline=deadline)
    sub = _submission(now)
    pkg_lines = [_line(l1, "A"), _line(l2, "B")]
    sub_lines = [_sub_line(l1, "500")]  # missing l2
    is_valid, errors = validate_submission_pre_open(sub, pkg, sub_lines, pkg_lines, now=now)
    assert is_valid is False
    assert any("missing_mandatory_line:B" in e for e in errors)


def test_validate_pre_open_currency_mismatch() -> None:
    now = datetime.now(UTC)
    deadline = now + timedelta(hours=2)
    l1 = uuid.uuid4()
    pkg = _package(deadline=deadline, currency="EUR")
    sub = _submission(now, currency="USD")
    pkg_lines = [_line(l1)]
    sub_lines = [_sub_line(l1, "1000")]
    is_valid, errors = validate_submission_pre_open(sub, pkg, sub_lines, pkg_lines, now=now)
    assert is_valid is False
    assert "currency_mismatch" in errors


def test_validate_late_submission_true() -> None:
    now = datetime.now(UTC)
    pkg = _package(deadline=now - timedelta(hours=1))
    sub = _submission(now)
    assert validate_late_submission(sub, pkg) is True


def test_validate_late_submission_within_grace() -> None:
    now = datetime.now(UTC)
    pkg = _package(deadline=now - timedelta(minutes=5))
    sub = _submission(now)
    assert validate_late_submission(sub, pkg, grace_minutes=15) is False


# ── normalize_submission_for_leveling ─────────────────────────────────────


def test_normalize_no_exclusions() -> None:
    sub = SimpleNamespace(total_amount=Decimal("1000"), exclusions=[], qualifications=[])
    assert normalize_submission_for_leveling(sub, _package()) == Decimal("1000.00")


def test_normalize_with_exclusions() -> None:
    # 2 exclusions @ 5% each = +10% → 1100
    sub = SimpleNamespace(
        total_amount=Decimal("1000"),
        exclusions=["a", "b"],
        qualifications=[],
    )
    result = normalize_submission_for_leveling(sub, _package())
    assert result == Decimal("1100.00")


def test_normalize_with_mixed_penalties() -> None:
    # 1 exclusion (5%) + 2 qualifications (2% each = 4%) = +9% → 1090
    sub = SimpleNamespace(
        total_amount=Decimal("1000"),
        exclusions=["a"],
        qualifications=["q1", "q2"],
    )
    result = normalize_submission_for_leveling(sub, _package())
    assert result == Decimal("1090.00")


# ── rank_bids + recommend_bidder ──────────────────────────────────────────


def _lev(score: float, normalized: float, bidder_id: uuid.UUID) -> Any:
    return SimpleNamespace(
        total_score=Decimal(str(score)),
        normalized_total=Decimal(str(normalized)),
        bidder_id=bidder_id,
        rank=0,
    )


def test_rank_bids_sorts_desc() -> None:
    b1, b2, b3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    levelings = [
        _lev(80, 1000, b1),
        _lev(95, 900, b2),
        _lev(70, 1200, b3),
    ]
    ranked = rank_bids(levelings)
    assert ranked[0].rank == 1 and ranked[0].bidder_id == b2
    assert ranked[1].rank == 2 and ranked[1].bidder_id == b1
    assert ranked[2].rank == 3 and ranked[2].bidder_id == b3


def test_rank_bids_tie_break_by_normalized_total() -> None:
    b1, b2 = uuid.uuid4(), uuid.uuid4()
    # Equal scores → lower normalized_total wins.
    levelings = [_lev(90, 1100, b1), _lev(90, 1000, b2)]
    ranked = rank_bids(levelings)
    assert ranked[0].bidder_id == b2
    assert ranked[1].bidder_id == b1


def test_recommend_bidder_picks_rank_one() -> None:
    b1, b2 = uuid.uuid4(), uuid.uuid4()
    levelings = [_lev(80, 1000, b1), _lev(95, 900, b2)]
    rank_bids(levelings)
    bidders = [
        SimpleNamespace(id=b1, company_name="Alpha"),
        SimpleNamespace(id=b2, company_name="Beta"),
    ]
    comparison = SimpleNamespace()
    chosen = recommend_bidder(comparison, levelings, bidders)
    assert chosen is not None
    assert chosen.id == b2


def test_recommend_bidder_empty() -> None:
    bidders = [SimpleNamespace(id=uuid.uuid4(), company_name="X")]
    assert recommend_bidder(SimpleNamespace(), [], bidders) is None


# ── compute_bid_summary ───────────────────────────────────────────────────


def _full_sub(total: str, completeness: str = "100", valid: bool = True, late: bool = False) -> Any:
    return SimpleNamespace(
        total_amount=Decimal(total),
        completeness_score=Decimal(completeness),
        is_valid=valid,
        open_after_deadline=late,
    )


def test_compute_bid_summary_basic() -> None:
    subs = [
        _full_sub("1000"),
        _full_sub("1200"),
        _full_sub("1500"),
    ]
    summary = compute_bid_summary(subs)
    assert summary["count"] == 3
    assert summary["min"] == Decimal("1000.00")
    assert summary["max"] == Decimal("1500.00")
    assert summary["average"] == Decimal("1233.33")
    assert summary["valid_count"] == 3
    assert summary["late_count"] == 0


def test_compute_bid_summary_with_invalid_and_late() -> None:
    subs = [
        _full_sub("1000", valid=True, late=False),
        _full_sub("1500", valid=False, late=True),
    ]
    summary = compute_bid_summary(subs)
    assert summary["valid_count"] == 1
    assert summary["late_count"] == 1


def test_compute_bid_summary_empty() -> None:
    summary = compute_bid_summary([])
    assert summary["count"] == 0
    assert summary["min"] is None
    assert summary["max"] is None


# ── State machines ────────────────────────────────────────────────────────


def test_package_transitions_full_workflow() -> None:
    assert "published" in allowed_package_transitions("draft")
    assert "open" in allowed_package_transitions("published")
    assert "closed" in allowed_package_transitions("open")
    assert "awarded" in allowed_package_transitions("closed")
    # Terminal states
    assert allowed_package_transitions("awarded") == set()
    assert allowed_package_transitions("cancelled") == set()


def test_package_transitions_cancel_from_any_open_state() -> None:
    for state in ("draft", "published", "open", "closed"):
        assert "cancelled" in allowed_package_transitions(state)


def test_package_transitions_illegal_skip() -> None:
    # cannot go draft -> open directly
    assert "open" not in allowed_package_transitions("draft")
    # cannot go open -> awarded directly
    assert "awarded" not in allowed_package_transitions("open")


def test_invitation_transitions() -> None:
    assert "sent" in allowed_invitation_transitions("pending")
    assert "submitted" in allowed_invitation_transitions("sent")
    assert "declined" in allowed_invitation_transitions("opened")
    assert allowed_invitation_transitions("submitted") == set()


# ── Service: create_package + publish ─────────────────────────────────────


def _pkg_data(code: str = "BP-01", status: str = "draft") -> BidPackageCreate:
    return BidPackageCreate(
        project_id=PROJECT_ID,
        code=code,
        title="Test Package",
        currency="EUR",
        total_budget_estimate=Decimal("10000"),
        status=status,
    )


@pytest.mark.asyncio
async def test_create_package_stores_row() -> None:
    svc = _make_service()
    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(), user_id="u1")
    assert pkg.id is not None
    assert pkg.code == "BP-01"
    assert pkg.status == "draft"


@pytest.mark.asyncio
async def test_create_package_duplicate_code_raises() -> None:
    svc = _make_service()
    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        await svc.create_package(_pkg_data(), user_id="u1")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.create_package(_pkg_data(), user_id="u1")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_publish_package_transitions_and_emits() -> None:
    svc = _make_service()
    publish_mock = AsyncMock()
    with patch("app.modules.bid_management.service.event_bus.publish_detached", publish_mock):
        pkg = await svc.create_package(_pkg_data(), user_id="u1")
        published = await svc.publish_package(pkg.id, user_id="u1")
    assert published.status == "published"
    assert published.published_at is not None
    assert any(call.args[0] == "bid_management.package.published" for call in publish_mock.call_args_list)


@pytest.mark.asyncio
async def test_publish_package_illegal_transition() -> None:
    svc = _make_service()
    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(status="cancelled"), user_id="u1")
    # cancelled -> published is not legal
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.publish_package(pkg.id, user_id="u1")
    assert exc.value.status_code == 409


# ── Service: open_bids ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_bids_flips_invitations_and_emits() -> None:
    svc = _make_service()
    now = datetime.now(UTC)
    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(code="BP-OB"), user_id="u1")
        # Manually set deadline + status
        pkg.submission_deadline = (now - timedelta(hours=1)).isoformat()
        pkg.status = "published"

        # Add an invitation w/o submission (should expire)
        from app.modules.bid_management.models import BidInvitation

        inv = BidInvitation(package_id=pkg.id, invitee_email="late@x.com", status="sent")
        await svc.invitation_repo.create(inv)

    publish_mock = AsyncMock()
    with patch("app.modules.bid_management.service.event_bus.publish_detached", publish_mock):
        opened = await svc.open_bids(pkg.id, now=now)

    assert opened.status == "open"
    # Invitation with no submission and past-deadline -> expired
    assert inv.status == "expired"
    # Event emitted
    assert any(call.args[0] == "bid_management.bids.opened" for call in publish_mock.call_args_list)


# ── Service: disqualify_bidder ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disqualify_bidder_flips_status_and_emits() -> None:
    svc = _make_service()
    publish_mock = AsyncMock()
    with patch("app.modules.bid_management.service.event_bus.publish_detached", publish_mock):
        from app.modules.bid_management.models import Bidder

        bidder = Bidder(package_id=uuid.uuid4(), company_name="X Co", status="active")
        await svc.bidder_repo.create(bidder)
        disqualified = await svc.disqualify_bidder(bidder.id, reason="Doc missing")
    assert disqualified.status == "disqualified"
    assert disqualified.disqualification_reason == "Doc missing"
    assert any(call.args[0] == "bid_management.bidder.disqualified" for call in publish_mock.call_args_list)


# ── Service: award_package + auto-reject others ───────────────────────────


@pytest.mark.asyncio
async def test_award_package_emits_and_auto_rejects_others() -> None:
    svc = _make_service()
    publish_mock = AsyncMock()
    with patch("app.modules.bid_management.service.event_bus.publish_detached", publish_mock):
        pkg = await svc.create_package(_pkg_data(code="BP-AW"), user_id="u1")
        pkg.status = "closed"

        from app.modules.bid_management.models import Bidder

        winner = Bidder(package_id=pkg.id, company_name="Winner", status="active")
        loser1 = Bidder(package_id=pkg.id, company_name="Loser 1", status="active")
        loser2 = Bidder(package_id=pkg.id, company_name="Loser 2", status="active")
        # A disqualified bidder must NOT receive an auto-rejection.
        disq = Bidder(
            package_id=pkg.id,
            company_name="Disqualified Co",
            status="disqualified",
        )
        for b in (winner, loser1, loser2, disq):
            await svc.bidder_repo.create(b)

        award_data = BidAwardCreate(
            package_id=pkg.id,
            awarded_bidder_id=winner.id,
            awarded_amount=Decimal("9000"),
            currency="EUR",
            decision_summary="Best bid",
        )
        award = await svc.award_package(pkg.id, award_data, user_id="u1")

    assert award.awarded_bidder_id == winner.id
    assert pkg.status == "awarded"
    assert pkg.awarded_at is not None
    # Auto-rejections were created for the two active losers only — NOT
    # the winner and NOT the already-disqualified bidder.
    rejections = await svc.rejection_repo.list_for_package(pkg.id)
    assert len(rejections) == 2
    bidder_ids_rejected = {r.bidder_id for r in rejections}
    assert winner.id not in bidder_ids_rejected
    assert disq.id not in bidder_ids_rejected
    assert bidder_ids_rejected == {loser1.id, loser2.id}
    # Event emitted
    assert any(call.args[0] == "bid_management.package.awarded" for call in publish_mock.call_args_list)


@pytest.mark.asyncio
async def test_award_package_requires_closed_status() -> None:
    svc = _make_service()
    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(code="BP-DR"), user_id="u1")
        # status is still 'draft' — award must fail
        from app.modules.bid_management.models import Bidder

        bidder = Bidder(package_id=pkg.id, company_name="X")
        await svc.bidder_repo.create(bidder)

        award_data = BidAwardCreate(
            package_id=pkg.id,
            awarded_bidder_id=bidder.id,
            awarded_amount=Decimal("100"),
        )
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await svc.award_package(pkg.id, award_data, user_id="u1")
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_award_rejects_bidder_from_other_package() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    from app.modules.bid_management.models import Bidder

    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(code="BP-X1"), user_id="u1")
        pkg.status = "closed"
        # Bidder belongs to a *different* package.
        stray = Bidder(package_id=uuid.uuid4(), company_name="Stray", status="active")
        await svc.bidder_repo.create(stray)
        award_data = BidAwardCreate(
            package_id=pkg.id,
            awarded_bidder_id=stray.id,
            awarded_amount=Decimal("100"),
        )
        with pytest.raises(HTTPException) as exc:
            await svc.award_package(pkg.id, award_data, user_id="u1")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_award_rejects_disqualified_bidder() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    from app.modules.bid_management.models import Bidder

    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(code="BP-X2"), user_id="u1")
        pkg.status = "closed"
        b = Bidder(package_id=pkg.id, company_name="DQ", status="disqualified")
        await svc.bidder_repo.create(b)
        award_data = BidAwardCreate(
            package_id=pkg.id,
            awarded_bidder_id=b.id,
            awarded_amount=Decimal("100"),
        )
        with pytest.raises(HTTPException) as exc:
            await svc.award_package(pkg.id, award_data, user_id="u1")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_package_cannot_change_status() -> None:
    """A generic PATCH must not bypass the lifecycle state machine."""
    svc = _make_service()
    from fastapi import HTTPException

    from app.modules.bid_management.schemas import BidPackageUpdate

    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(code="BP-PS"), user_id="u1")
        with pytest.raises(HTTPException) as exc:
            await svc.update_package(pkg.id, BidPackageUpdate(status="awarded"))
    assert exc.value.status_code == 409
    # Non-status fields still update fine.
    updated = await svc.update_package(pkg.id, BidPackageUpdate(title="Renamed"))
    assert updated.title == "Renamed"
    assert updated.status == "draft"


@pytest.mark.asyncio
async def test_submission_locked_after_award() -> None:
    """Submission figures must not be editable once package is awarded."""
    svc = _make_service()
    from fastapi import HTTPException

    from app.modules.bid_management.models import BidInvitation
    from app.modules.bid_management.schemas import (
        BidSubmissionCreate,
        BidSubmissionUpdate,
    )

    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(code="BP-LK"), user_id="u1")
        inv = BidInvitation(package_id=pkg.id, invitee_email="a@b.com", status="opened")
        await svc.invitation_repo.create(inv)
        # R7 bidder-impersonation guard: bidder must belong to the same
        # package as the invitation, so seed an in-package bidder first.
        from app.modules.bid_management.models import Bidder

        bidder = Bidder(package_id=pkg.id, company_name="LK Co")
        await svc.bidder_repo.create(bidder)
        sub = await svc.record_submission(
            BidSubmissionCreate(
                invitation_id=inv.id,
                bidder_id=bidder.id,
                total_amount=Decimal("1000"),
                currency="EUR",
            )
        )
        # Editable while draft.
        await svc.update_submission(sub.id, BidSubmissionUpdate(total_amount=Decimal("1100")))
        # Lock once package is awarded.
        pkg.status = "awarded"
        with pytest.raises(HTTPException) as exc:
            await svc.update_submission(sub.id, BidSubmissionUpdate(total_amount=Decimal("9999")))
    assert exc.value.status_code == 409


# ── Service: cancel from various states ───────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_package_from_draft() -> None:
    svc = _make_service()
    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(code="BP-CD"), user_id="u1")
        cancelled = await svc.cancel_package(pkg.id, reason="No budget")
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_package_from_open() -> None:
    svc = _make_service()
    with patch("app.modules.bid_management.service.event_bus.publish_detached"):
        pkg = await svc.create_package(_pkg_data(code="BP-CO"), user_id="u1")
        pkg.status = "open"
        cancelled = await svc.cancel_package(pkg.id, reason="Scope change")
    assert cancelled.status == "cancelled"


# ── Service: send_invitations emits event ─────────────────────────────────


@pytest.mark.asyncio
async def test_send_invitations_emits_event() -> None:
    svc = _make_service()
    from app.modules.bid_management.models import BidInvitation

    pkg_id = uuid.uuid4()
    inv = BidInvitation(package_id=pkg_id, invitee_email="a@b.com", status="pending")
    await svc.invitation_repo.create(inv)

    publish_mock = AsyncMock()
    with patch("app.modules.bid_management.service.event_bus.publish_detached", publish_mock):
        count = await svc.send_invitations(pkg_id)

    assert count == 1
    assert inv.status == "sent"
    assert any(call.args[0] == "bid_management.invitation.sent" for call in publish_mock.call_args_list)


# ── Service: record_submission emits event ────────────────────────────────


@pytest.mark.asyncio
async def test_record_submission_emits_event() -> None:
    svc = _make_service()
    from app.modules.bid_management.models import BidInvitation
    from app.modules.bid_management.schemas import BidSubmissionCreate

    pkg_id = uuid.uuid4()
    inv = BidInvitation(package_id=pkg_id, invitee_email="x@y.com", status="opened")
    await svc.invitation_repo.create(inv)

    # R7 bidder-impersonation guard: bidder must belong to the same
    # package as the invitation; seed one explicitly.
    from app.modules.bid_management.models import Bidder

    bidder = Bidder(package_id=pkg_id, company_name="XY Co")
    await svc.bidder_repo.create(bidder)

    publish_mock = AsyncMock()
    data = BidSubmissionCreate(
        invitation_id=inv.id,
        bidder_id=bidder.id,
        total_amount=Decimal("5000"),
        currency="EUR",
    )
    with patch("app.modules.bid_management.service.event_bus.publish_detached", publish_mock):
        sub = await svc.record_submission(data)

    assert sub.invitation_id == inv.id
    assert any(call.args[0] == "bid_management.submission.received" for call in publish_mock.call_args_list)
    # Invitation status flipped to 'submitted'
    assert inv.status == "submitted"


# ── Repository CRUD basics ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_crud_roundtrip() -> None:
    svc = _make_service()
    from app.modules.bid_management.models import Bidder

    bidder = Bidder(package_id=uuid.uuid4(), company_name="Roundtrip Co")
    await svc.bidder_repo.create(bidder)
    assert await svc.bidder_repo.get_by_id(bidder.id) is bidder
    await svc.bidder_repo.update_fields(bidder.id, company_name="Updated Co")
    assert svc.bidder_repo.rows[bidder.id].company_name == "Updated Co"
    await svc.bidder_repo.delete(bidder.id)
    assert await svc.bidder_repo.get_by_id(bidder.id) is None


# ── Permission registry ───────────────────────────────────────────────────


def test_permissions_registered() -> None:
    from app.core.permissions import Role, permission_registry
    from app.modules.bid_management.permissions import (
        register_bid_management_permissions,
    )

    register_bid_management_permissions()
    # Spot-check a representative permission per role tier
    assert permission_registry.role_has_permission(Role.VIEWER, "bid_management.read")
    assert permission_registry.role_has_permission(Role.EDITOR, "bid_management.create")
    assert permission_registry.role_has_permission(Role.EDITOR, "bid_management.compute_leveling")
    assert permission_registry.role_has_permission(Role.MANAGER, "bid_management.publish")
    assert permission_registry.role_has_permission(Role.MANAGER, "bid_management.award")
    assert permission_registry.role_has_permission(Role.MANAGER, "bid_management.cancel")
    # Viewer cannot publish
    assert not permission_registry.role_has_permission(Role.VIEWER, "bid_management.publish")


# ── Outlier detection (±σ) ──────────────────────────────────────────────


def test_detect_bid_outliers_flags_low_and_high() -> None:
    """A clear low-baller and a clear high-baller should be flagged."""
    from app.modules.bid_management.service import detect_bid_outliers

    bids = [
        SimpleNamespace(id="b1", total_amount=Decimal("100000")),
        SimpleNamespace(id="b2", total_amount=Decimal("110000")),
        SimpleNamespace(id="b3", total_amount=Decimal("105000")),
        SimpleNamespace(id="b4", total_amount=Decimal("108000")),
        SimpleNamespace(id="b5", total_amount=Decimal("50000")),  # low
        SimpleNamespace(id="b6", total_amount=Decimal("180000")),  # high
    ]
    out = detect_bid_outliers(bids, sigma_threshold=Decimal("1"))
    low_ids = {row["id"] for row in out["low_outliers"]}
    high_ids = {row["id"] for row in out["high_outliers"]}
    assert "b5" in low_ids
    assert "b6" in high_ids
    assert out["mean"] > 0
    assert out["std_dev"] > 0


def test_detect_bid_outliers_single_bid_returns_empty() -> None:
    from app.modules.bid_management.service import detect_bid_outliers

    out = detect_bid_outliers(
        [SimpleNamespace(id="only", total_amount=Decimal("100000"))],
    )
    assert out["low_outliers"] == []
    assert out["high_outliers"] == []


def test_detect_bid_outliers_skips_zero_totals() -> None:
    from app.modules.bid_management.service import detect_bid_outliers

    bids = [
        SimpleNamespace(id="b1", total_amount=Decimal("100000")),
        SimpleNamespace(id="b2", total_amount=Decimal("0")),  # ignored
        SimpleNamespace(id="b3", total_amount=Decimal("105000")),
    ]
    out = detect_bid_outliers(bids, sigma_threshold=Decimal("2"))
    # All non-zero bids are within ±2σ of their mean.
    assert out["low_outliers"] == []
    assert out["high_outliers"] == []
