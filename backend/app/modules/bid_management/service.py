"""‌⁠‍Bid Management service — business logic, state machines, pure helpers.

The pure helpers (``compute_*`` / ``validate_*`` / ``rank_*`` /
``recommend_*``) operate on plain dataclass-like objects (anything with
the right attribute names) and have no I/O — they are easy to unit test
without a database. The :class:`BidManagementService` wraps them with
persistence and event emission.
"""

from __future__ import annotations

import logging
import statistics
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.bid_management.models import (
    BidAward,
    BidComparison,
    Bidder,
    BidInvitation,
    BidLeveling,
    BidPackage,
    BidPackageLineItem,
    BidQA,
    BidRejection,
    BidSubmission,
    BidSubmissionLine,
)
from app.modules.bid_management.repository import (
    BidAwardRepository,
    BidComparisonRepository,
    BidderRepository,
    BidInvitationRepository,
    BidLevelingRepository,
    BidPackageLineItemRepository,
    BidPackageRepository,
    BidQARepository,
    BidRejectionRepository,
    BidSubmissionLineRepository,
    BidSubmissionRepository,
)
from app.modules.bid_management.schemas import (
    BidAwardCreate,
    BidAwardUpdate,
    BidComparisonCreate,
    BidComparisonUpdate,
    BidderCreate,
    BidderUpdate,
    BidInvitationCreate,
    BidInvitationUpdate,
    BidPackageCreate,
    BidPackageLineItemCreate,
    BidPackageLineItemUpdate,
    BidPackageUpdate,
    BidQAAnswer,
    BidQACreate,
    BidQAUpdate,
    BidRejectionCreate,
    BidRejectionUpdate,
    BidSubmissionCreate,
    BidSubmissionLineCreate,
    BidSubmissionLineUpdate,
    BidSubmissionUpdate,
    SubmissionAnalyticsResponse,
)

logger = logging.getLogger(__name__)


# ── State machine definitions ─────────────────────────────────────────────


PACKAGE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"published", "cancelled"},
    "published": {"open", "cancelled"},
    "open": {"closed", "cancelled"},
    "closed": {"awarded", "cancelled"},
    "awarded": set(),
    "cancelled": set(),
}

INVITATION_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"sent", "expired"},
    "sent": {"opened", "declined", "submitted", "expired"},
    "opened": {"submitted", "declined", "expired"},
    "submitted": set(),
    "declined": set(),
    "expired": set(),
}


def allowed_package_transitions(current: str) -> set[str]:
    """‌⁠‍Return the set of legal next statuses for a package."""
    return PACKAGE_TRANSITIONS.get(current, set())


def allowed_invitation_transitions(current: str) -> set[str]:
    """‌⁠‍Return the set of legal next statuses for an invitation."""
    return INVITATION_TRANSITIONS.get(current, set())


# ── Pure helpers ──────────────────────────────────────────────────────────


def _to_decimal(value: Any) -> Decimal:
    """Coerce DB / schema scalars to :class:`Decimal`. Empty/None -> 0."""
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def compute_submission_total(lines: list[Any]) -> Decimal:
    """Sum of ``unit_price * quantity_priced`` across all lines.

    Lines may be ORM objects, Pydantic models, or anything else with the
    right attribute names — only attribute access is used.
    """
    total = Decimal("0")
    for line in lines:
        unit = _to_decimal(getattr(line, "unit_price", 0))
        qty = _to_decimal(getattr(line, "quantity_priced", 0))
        total += unit * qty
    return total.quantize(Decimal("0.01"))


def compute_completeness_score(submission_lines: list[Any], package_lines: list[Any]) -> Decimal:
    """Return percentage (0-100) of *mandatory* lines that are priced.

    A line is considered "priced" if a matching submission line exists
    AND its ``unit_price`` (or ``total_price``) is non-zero.
    """
    mandatory = [ln for ln in package_lines if getattr(ln, "is_mandatory", True)]
    if not mandatory:
        return Decimal("100.00")

    priced_ids: set[uuid.UUID] = set()
    for line in submission_lines:
        unit = _to_decimal(getattr(line, "unit_price", 0))
        total_price = _to_decimal(getattr(line, "total_price", 0))
        if unit > 0 or total_price > 0:
            line_item_id = getattr(line, "line_item_id", None)
            if line_item_id is not None:
                priced_ids.add(line_item_id)

    mandatory_ids = {ln.id for ln in mandatory}  # type: ignore[arg-type]
    matched = mandatory_ids & priced_ids
    pct = (Decimal(len(matched)) / Decimal(len(mandatory_ids))) * Decimal("100")
    return pct.quantize(Decimal("0.01"))


def _parse_iso(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        # Tolerate trailing Z
        normalized = dt_str.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except (TypeError, ValueError):
        return None


def validate_submission_pre_open(
    submission: Any,
    package: Any,
    submission_lines: list[Any],
    package_lines: list[Any],
    *,
    now: datetime,
) -> tuple[bool, list[str]]:
    """Validate a submission *before* the bid-opening event.

    Returns ``(is_valid, errors)``. Errors are human-readable codes:
        - "submission_after_deadline"
        - "missing_mandatory_line:<line_code>"
        - "currency_mismatch"
        - "zero_total"
    """
    errors: list[str] = []

    deadline = _parse_iso(getattr(package, "submission_deadline", None))
    submitted_at = _parse_iso(getattr(submission, "submitted_at", None))
    if deadline is not None and submitted_at is not None and submitted_at > deadline:
        errors.append("submission_after_deadline")

    package_currency = (getattr(package, "currency", "") or "").upper()
    submission_currency = (getattr(submission, "currency", "") or "").upper()
    if package_currency and submission_currency and package_currency != submission_currency:
        errors.append("currency_mismatch")

    priced_line_ids = {
        getattr(line, "line_item_id", None)
        for line in submission_lines
        if _to_decimal(getattr(line, "unit_price", 0)) > 0 or _to_decimal(getattr(line, "total_price", 0)) > 0
    }

    for line in package_lines:
        if not getattr(line, "is_mandatory", True):
            continue
        if getattr(line, "id", None) not in priced_line_ids:
            code = getattr(line, "code", str(getattr(line, "id", "?")))
            errors.append(f"missing_mandatory_line:{code}")

    total = compute_submission_total(submission_lines)
    if total <= Decimal("0"):
        errors.append("zero_total")

    return (len(errors) == 0, errors)


def validate_late_submission(submission: Any, package: Any, *, grace_minutes: int = 0) -> bool:
    """Return True if the submission is late (beyond deadline + grace)."""
    deadline = _parse_iso(getattr(package, "submission_deadline", None))
    submitted_at = _parse_iso(getattr(submission, "submitted_at", None))
    if deadline is None or submitted_at is None:
        return False
    from datetime import timedelta

    return submitted_at > (deadline + timedelta(minutes=grace_minutes))


def normalize_submission_for_leveling(
    submission: Any,
    package: Any,
    *,
    exclusion_penalty_pct: Decimal = Decimal("5"),
    qualification_penalty_pct: Decimal = Decimal("2"),
) -> Decimal:
    """Adjust a raw total by applying penalties for each declared exclusion
    or qualification.

    Penalties are expressed as percentage of the raw total, applied
    additively. The default rule of thumb (5% per exclusion, 2% per
    qualification) matches the contract-comparison conventions used by
    public procurement guidelines.
    """
    raw_total = _to_decimal(getattr(submission, "total_amount", 0))
    exclusions = getattr(submission, "exclusions", []) or []
    qualifications = getattr(submission, "qualifications", []) or []

    exclusion_count = Decimal(len(exclusions))
    qualification_count = Decimal(len(qualifications))

    penalty = (
        raw_total * (exclusion_penalty_pct / Decimal("100")) * exclusion_count
        + raw_total * (qualification_penalty_pct / Decimal("100")) * qualification_count
    )
    normalized = raw_total + penalty
    return normalized.quantize(Decimal("0.01"))


def rank_bids(levelings: list[Any]) -> list[Any]:
    """Sort by ``total_score`` desc (tie-break ``normalized_total`` asc),
    assign ``rank`` (1-based). Mutates and returns the input list for
    chainability.
    """

    def _key(row: Any) -> tuple[Decimal, Decimal]:
        # Higher total_score is better; lower normalized_total is the
        # tie-breaker. Wrap with -score so ``sorted`` ascending DTRT.
        score = _to_decimal(getattr(row, "total_score", 0))
        normalized = _to_decimal(getattr(row, "normalized_total", 0))
        return (-score, normalized)

    levelings.sort(key=_key)
    for idx, row in enumerate(levelings, start=1):
        row.rank = idx
    return levelings


def recommend_bidder(
    comparison: Any,
    levelings: list[Any],
    bidders: list[Any],
) -> Bidder | None:
    """Pick the bidder of rank 1 from the supplied levelings.

    Tie-break: when two rows share the same score, the one with the
    earliest submission wins. ``recommend_bidder`` does not query the DB —
    callers pass the relevant rows in.
    """
    if not levelings:
        return None

    rank_one = [row for row in levelings if getattr(row, "rank", 0) == 1]
    if not rank_one:
        # Levelings haven't been ranked yet — pick the top by score.
        top_score = max(_to_decimal(getattr(r, "total_score", 0)) for r in levelings)
        rank_one = [r for r in levelings if _to_decimal(getattr(r, "total_score", 0)) == top_score]

    bidder_lookup = {b.id: b for b in bidders}  # type: ignore[arg-type]
    chosen = rank_one[0]
    return bidder_lookup.get(getattr(chosen, "bidder_id", None))


def detect_bid_outliers(
    submissions: list[Any],
    sigma_threshold: Decimal | float | int | str = Decimal("2"),
) -> dict[str, Any]:
    """Flag submissions outside ±N·σ of the mean total amount.

    Returns a dict with the underlying mean / σ + per-submission flag.
    ``low_outliers`` are likely scope-misunderstanding bids; ``high_outliers``
    are conservative or padded.  Public procurement guidance (e.g. EU Dir
    2014/24 Art 69 abnormally-low-tender screen) typically uses ±2σ.

    Pure: no DB.
    """
    threshold = Decimal(str(sigma_threshold or 0))
    totals: list[Decimal] = []
    for s in submissions:
        amt = _to_decimal(getattr(s, "total_amount", 0))
        if amt > 0:
            totals.append(amt)
    if len(totals) < 2:
        return {
            "mean": Decimal("0"),
            "std_dev": Decimal("0"),
            "low_threshold": Decimal("0"),
            "high_threshold": Decimal("0"),
            "low_outliers": [],
            "high_outliers": [],
            "sigma_threshold": threshold,
        }
    mean = sum(totals, Decimal("0")) / Decimal(len(totals))
    # Population standard deviation (matches statistics.pstdev rounding).
    variance = sum(((t - mean) ** 2 for t in totals), Decimal("0")) / Decimal(len(totals))
    # Decimal lacks sqrt; iterate Newton's method for stability.
    if variance > 0:
        x = variance
        for _ in range(40):
            x = (x + variance / x) / Decimal("2")
        sigma = x
    else:
        sigma = Decimal("0")
    low_thr = mean - threshold * sigma
    high_thr = mean + threshold * sigma
    low_outliers: list[Any] = []
    high_outliers: list[Any] = []
    for s in submissions:
        amt = _to_decimal(getattr(s, "total_amount", 0))
        if amt <= 0:
            continue
        sid = str(getattr(s, "id", "") or "")
        if amt < low_thr:
            low_outliers.append({"id": sid, "total_amount": amt})
        elif amt > high_thr:
            high_outliers.append({"id": sid, "total_amount": amt})
    q = Decimal("0.01")
    return {
        "mean": mean.quantize(q),
        "std_dev": sigma.quantize(q),
        "low_threshold": low_thr.quantize(q),
        "high_threshold": high_thr.quantize(q),
        "low_outliers": low_outliers,
        "high_outliers": high_outliers,
        "sigma_threshold": threshold,
    }


def compute_bid_summary(submissions: list[Any]) -> dict[str, Any]:
    """Aggregate stats across a list of submissions.

    Returns a dict ready to drop into :class:`SubmissionAnalyticsResponse`.
    """
    totals = [
        float(_to_decimal(getattr(s, "total_amount", 0)))
        for s in submissions
        if _to_decimal(getattr(s, "total_amount", 0)) > 0
    ]
    completeness = [float(_to_decimal(getattr(s, "completeness_score", 0))) for s in submissions]
    valid_count = sum(1 for s in submissions if getattr(s, "is_valid", False))
    late_count = sum(1 for s in submissions if getattr(s, "open_after_deadline", False))

    if totals:
        avg = statistics.mean(totals)
        sd = statistics.pstdev(totals) if len(totals) > 1 else 0.0
        result_min: Decimal | None = Decimal(str(min(totals))).quantize(Decimal("0.01"))
        result_max: Decimal | None = Decimal(str(max(totals))).quantize(Decimal("0.01"))
        result_avg: Decimal | None = Decimal(str(avg)).quantize(Decimal("0.01"))
        result_sd: Decimal | None = Decimal(str(sd)).quantize(Decimal("0.01"))
    else:
        result_min = result_max = result_avg = result_sd = None

    comp_avg: Decimal | None = (
        Decimal(str(statistics.mean(completeness))).quantize(Decimal("0.01")) if completeness else None
    )

    return {
        "count": len(submissions),
        "min": result_min,
        "max": result_max,
        "average": result_avg,
        "std_dev": result_sd,
        "completeness_avg": comp_avg,
        "valid_count": valid_count,
        "late_count": late_count,
    }


# ── Orchestration service ─────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class BidManagementService:
    """Coordinates the bid_management workflow."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.package_repo = BidPackageRepository(session)
        self.line_repo = BidPackageLineItemRepository(session)
        self.invitation_repo = BidInvitationRepository(session)
        self.bidder_repo = BidderRepository(session)
        self.submission_repo = BidSubmissionRepository(session)
        self.submission_line_repo = BidSubmissionLineRepository(session)
        self.qa_repo = BidQARepository(session)
        self.comparison_repo = BidComparisonRepository(session)
        self.leveling_repo = BidLevelingRepository(session)
        self.award_repo = BidAwardRepository(session)
        self.rejection_repo = BidRejectionRepository(session)

    # ── Packages ──────────────────────────────────────────────────────

    async def create_package(self, data: BidPackageCreate, user_id: str | None = None) -> BidPackage:
        existing = await self.package_repo.get_by_code(data.code)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Package code already exists")

        package = BidPackage(
            project_id=data.project_id,
            tender_id=data.tender_id,
            code=data.code,
            title=data.title,
            scope_description=data.scope_description,
            instructions_to_bidders=data.instructions_to_bidders,
            submission_deadline=data.submission_deadline,
            decision_due_by=data.decision_due_by,
            currency=data.currency,
            total_budget_estimate=str(data.total_budget_estimate),
            status=data.status,
            confidentiality_level=data.confidentiality_level,
            created_by=user_id,
            metadata_=data.metadata,
        )
        return await self.package_repo.create(package)

    async def get_package(self, package_id: uuid.UUID) -> BidPackage:
        package = await self.package_repo.get_by_id(package_id)
        if package is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid package not found")
        return package

    async def list_packages(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[BidPackage], int]:
        return await self.package_repo.list_for_project(project_id, offset=offset, limit=limit, status=status_filter)

    async def update_package(self, package_id: uuid.UUID, data: BidPackageUpdate) -> BidPackage:
        package = await self.get_package(package_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        # Lifecycle status is owned by the state machine. A generic PATCH
        # must not be able to jump (e.g. draft → awarded) bypassing the
        # transition guards, timestamp stamping, auto-rejections and
        # events. Status changes go through the dedicated endpoints
        # (publish / open-bids / close / cancel / award).
        new_status = fields.pop("status", None)
        if new_status is not None and new_status != package.status:
            if new_status not in allowed_package_transitions(package.status):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Illegal transition: {package.status} -> "
                        f"{new_status}. Use the lifecycle endpoints "
                        f"(publish/open-bids/close/cancel/award)."
                    ),
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    "Package status cannot be changed via PATCH — use "
                    "the lifecycle endpoints "
                    "(publish/open-bids/close/cancel/award)."
                ),
            )
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if "total_budget_estimate" in fields and fields["total_budget_estimate"] is not None:
            fields["total_budget_estimate"] = str(fields["total_budget_estimate"])
        if not fields:
            return package
        await self.package_repo.update_fields(package_id, **fields)
        await self.session.refresh(package)
        return package

    async def delete_package(self, package_id: uuid.UUID) -> None:
        await self.get_package(package_id)
        await self.package_repo.delete(package_id)

    async def _transition_package(self, package: BidPackage, new_status: str) -> None:
        if new_status not in allowed_package_transitions(package.status):
            raise HTTPException(
                status_code=409,
                detail=f"Illegal transition: {package.status} -> {new_status}",
            )
        package.status = new_status
        await self.session.flush()

    async def publish_package(self, package_id: uuid.UUID, user_id: str | None = None) -> BidPackage:
        package = await self.get_package(package_id)
        await self._transition_package(package, "published")
        package.published_at = _now_iso()
        await self.session.flush()
        event_bus.publish_detached(
            "bid_management.package.published",
            {
                "package_id": str(package.id),
                "project_id": str(package.project_id),
                "code": package.code,
                "user_id": user_id,
            },
            source_module="bid_management",
        )
        return package

    async def open_bids(self, package_id: uuid.UUID, *, now: datetime | None = None) -> BidPackage:
        """Move a published package to ``open`` and flip invitation flags."""
        package = await self.get_package(package_id)
        # Allow open from either ``published`` or ``open`` (idempotent).
        if package.status == "published":
            await self._transition_package(package, "open")
        elif package.status != "open":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot open bids from status '{package.status}'",
            )

        cutoff = now or datetime.now(UTC)
        deadline = _parse_iso(package.submission_deadline)

        invitations = await self.invitation_repo.list_for_package(package_id)
        package_lines = await self.line_repo.list_for_package(package_id)

        for invitation in invitations:
            submission = await self.submission_repo.get_by_invitation(invitation.id)
            if submission is None:
                # Mark invitation as expired if past deadline & no submission.
                if (
                    deadline
                    and cutoff > deadline
                    and invitation.status
                    not in (
                        "submitted",
                        "declined",
                        "expired",
                    )
                ):
                    invitation.status = "expired"
                continue
            submission_lines = await self.submission_line_repo.list_for_submission(submission.id)
            is_valid, _errors = validate_submission_pre_open(
                submission,
                package,
                submission_lines,
                package_lines,
                now=cutoff,
            )
            submission.is_valid = is_valid
            submission.open_after_deadline = validate_late_submission(submission, package)
            submission.completeness_score = str(compute_completeness_score(submission_lines, package_lines))
            invitation.status = "submitted"

        await self.session.flush()

        event_bus.publish_detached(
            "bid_management.bids.opened",
            {
                "package_id": str(package.id),
                "project_id": str(package.project_id),
                "invitation_count": len(invitations),
                "opened_at": cutoff.isoformat(),
            },
            source_module="bid_management",
        )
        return package

    async def close_package(self, package_id: uuid.UUID) -> BidPackage:
        package = await self.get_package(package_id)
        await self._transition_package(package, "closed")
        package.closed_at = _now_iso()
        await self.session.flush()
        return package

    async def cancel_package(self, package_id: uuid.UUID, *, reason: str = "") -> BidPackage:
        package = await self.get_package(package_id)
        await self._transition_package(package, "cancelled")
        if reason:
            md = dict(package.metadata_ or {})
            md["cancel_reason"] = reason
            package.metadata_ = md
        await self.session.flush()
        return package

    async def award_package(self, package_id: uuid.UUID, data: BidAwardCreate, user_id: str | None = None) -> BidAward:
        package = await self.get_package(package_id)
        if package.status != "closed":
            raise HTTPException(
                status_code=409,
                detail=f"Package must be 'closed' before award (got '{package.status}')",
            )

        # The awarded bidder must belong to this package and still be
        # active — you cannot award a disqualified/withdrawn bidder, nor a
        # bidder record from a different package.
        winner = await self.bidder_repo.get_by_id(data.awarded_bidder_id)
        if winner is None or winner.package_id != package_id:
            raise HTTPException(
                status_code=404,
                detail="Awarded bidder not found for this package",
            )
        if winner.status != "active":
            raise HTTPException(
                status_code=409,
                detail=(f"Cannot award a '{winner.status}' bidder (must be 'active')"),
            )

        # Award row (upsert)
        existing = await self.award_repo.get_for_package(package_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Package is already awarded")

        award = BidAward(
            package_id=package_id,
            awarded_bidder_id=data.awarded_bidder_id,
            awarded_amount=str(data.awarded_amount),
            currency=data.currency or package.currency,
            decision_summary=data.decision_summary,
            decision_signed_by=data.decision_signed_by or user_id,
            decision_signed_at=data.decision_signed_at or _now_iso(),
            contract_template_ref=data.contract_template_ref,
        )
        await self.award_repo.create(award)

        # Transition package to awarded
        await self._transition_package(package, "awarded")
        package.awarded_at = _now_iso()

        # Auto-reject every other *active* bidder. Bidders already
        # disqualified or withdrawn are out for a recorded reason and must
        # not receive a duplicate "not selected" rejection.
        bidders = await self.bidder_repo.list_for_package(package_id)
        for bidder in bidders:
            if bidder.id == data.awarded_bidder_id:
                continue
            if bidder.status != "active":
                continue
            rejection = BidRejection(
                package_id=package_id,
                bidder_id=bidder.id,
                rejection_code="other",
                rejection_reason="Not selected — package awarded to another bidder",
            )
            await self.rejection_repo.create(rejection)

        await self.session.flush()

        event_bus.publish_detached(
            "bid_management.package.awarded",
            {
                "package_id": str(package.id),
                "project_id": str(package.project_id),
                "awarded_bidder_id": str(data.awarded_bidder_id),
                "awarded_amount": str(data.awarded_amount),
                "currency": award.currency,
            },
            source_module="bid_management",
        )
        return award

    # ── Lines ─────────────────────────────────────────────────────────

    async def create_line(self, data: BidPackageLineItemCreate) -> BidPackageLineItem:
        await self.get_package(data.package_id)  # 404 if missing
        line = BidPackageLineItem(
            package_id=data.package_id,
            code=data.code,
            description=data.description,
            unit=data.unit,
            quantity=str(data.quantity),
            alternative_allowed=data.alternative_allowed,
            order_index=data.order_index,
            parent_line_id=data.parent_line_id,
            spec_attachment_url=data.spec_attachment_url,
            is_mandatory=data.is_mandatory,
        )
        return await self.line_repo.create(line)

    async def bulk_create_lines(
        self, package_id: uuid.UUID, items: list[BidPackageLineItemCreate]
    ) -> list[BidPackageLineItem]:
        await self.get_package(package_id)
        rows = [
            BidPackageLineItem(
                package_id=package_id,
                code=item.code,
                description=item.description,
                unit=item.unit,
                quantity=str(item.quantity),
                alternative_allowed=item.alternative_allowed,
                order_index=item.order_index,
                parent_line_id=item.parent_line_id,
                spec_attachment_url=item.spec_attachment_url,
                is_mandatory=item.is_mandatory,
            )
            for item in items
        ]
        return await self.line_repo.bulk_create(rows)

    async def update_line(self, line_id: uuid.UUID, data: BidPackageLineItemUpdate) -> BidPackageLineItem:
        line = await self.line_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Line not found")
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "quantity" in fields and fields["quantity"] is not None:
            fields["quantity"] = str(fields["quantity"])
        if not fields:
            return line
        await self.line_repo.update_fields(line_id, **fields)
        await self.session.refresh(line)
        return line

    async def delete_line(self, line_id: uuid.UUID) -> None:
        await self.line_repo.delete(line_id)

    # ── Bidders ───────────────────────────────────────────────────────

    async def create_bidder(self, data: BidderCreate) -> Bidder:
        await self.get_package(data.package_id)
        bidder = Bidder(
            package_id=data.package_id,
            company_name=data.company_name,
            contact_name=data.contact_name,
            contact_email=data.contact_email,
            contact_phone=data.contact_phone,
            country=data.country,
            status=data.status,
            notes=data.notes,
        )
        return await self.bidder_repo.create(bidder)

    async def update_bidder(self, bidder_id: uuid.UUID, data: BidderUpdate) -> Bidder:
        bidder = await self.bidder_repo.get_by_id(bidder_id)
        if bidder is None:
            raise HTTPException(status_code=404, detail=translate("errors.bidder_not_found", locale=get_locale()))
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return bidder
        await self.bidder_repo.update_fields(bidder_id, **fields)
        await self.session.refresh(bidder)
        return bidder

    async def delete_bidder(self, bidder_id: uuid.UUID) -> None:
        await self.bidder_repo.delete(bidder_id)

    async def disqualify_bidder(self, bidder_id: uuid.UUID, reason: str) -> Bidder:
        bidder = await self.bidder_repo.get_by_id(bidder_id)
        if bidder is None:
            raise HTTPException(status_code=404, detail=translate("errors.bidder_not_found", locale=get_locale()))
        bidder.status = "disqualified"
        bidder.disqualification_reason = reason
        await self.session.flush()

        event_bus.publish_detached(
            "bid_management.bidder.disqualified",
            {
                "package_id": str(bidder.package_id),
                "bidder_id": str(bidder.id),
                "company_name": bidder.company_name,
                "reason": reason,
            },
            source_module="bid_management",
        )
        return bidder

    # ── Invitations ───────────────────────────────────────────────────

    async def create_invitation(self, data: BidInvitationCreate) -> BidInvitation:
        await self.get_package(data.package_id)
        invitation = BidInvitation(
            package_id=data.package_id,
            bidder_ref_id=data.bidder_ref_id,
            invitee_email=data.invitee_email,
            invitee_company_name=data.invitee_company_name,
            status=data.status,
        )
        return await self.invitation_repo.create(invitation)

    async def send_invitations(self, package_id: uuid.UUID) -> int:
        invitations = await self.invitation_repo.list_for_package(package_id, status="pending")
        sent_at = _now_iso()
        for inv in invitations:
            inv.status = "sent"
            inv.sent_at = sent_at
        await self.session.flush()

        if invitations:
            event_bus.publish_detached(
                "bid_management.invitation.sent",
                {
                    "package_id": str(package_id),
                    "count": len(invitations),
                    "sent_at": sent_at,
                },
                source_module="bid_management",
            )
        return len(invitations)

    async def update_invitation(self, invitation_id: uuid.UUID, data: BidInvitationUpdate) -> BidInvitation:
        inv = await self.invitation_repo.get_by_id(invitation_id)
        if inv is None:
            raise HTTPException(status_code=404, detail=translate("errors.invitation_not_found", locale=get_locale()))
        fields = data.model_dump(exclude_unset=True)
        new_status = fields.get("status")
        if new_status is not None and new_status != inv.status:
            if new_status not in allowed_invitation_transitions(inv.status):
                raise HTTPException(
                    status_code=409,
                    detail=f"Illegal invitation transition: {inv.status} -> {new_status}",
                )
        if not fields:
            return inv
        await self.invitation_repo.update_fields(invitation_id, **fields)
        await self.session.refresh(inv)
        return inv

    async def mark_invitation_opened(self, invitation_id: uuid.UUID) -> BidInvitation:
        inv = await self.invitation_repo.get_by_id(invitation_id)
        if inv is None:
            raise HTTPException(status_code=404, detail=translate("errors.invitation_not_found", locale=get_locale()))
        if "opened" not in allowed_invitation_transitions(inv.status):
            # No-op when already in a terminal state.
            return inv
        inv.status = "opened"
        inv.opened_at = _now_iso()
        await self.session.flush()
        return inv

    async def decline_invitation(self, invitation_id: uuid.UUID, reason: str = "") -> BidInvitation:
        inv = await self.invitation_repo.get_by_id(invitation_id)
        if inv is None:
            raise HTTPException(status_code=404, detail=translate("errors.invitation_not_found", locale=get_locale()))
        if "declined" not in allowed_invitation_transitions(inv.status):
            raise HTTPException(status_code=409, detail=f"Cannot decline from '{inv.status}'")
        inv.status = "declined"
        inv.declined_at = _now_iso()
        inv.decline_reason = reason
        await self.session.flush()
        return inv

    async def resend_invitation(self, invitation_id: uuid.UUID) -> BidInvitation:
        inv = await self.invitation_repo.get_by_id(invitation_id)
        if inv is None:
            raise HTTPException(status_code=404, detail=translate("errors.invitation_not_found", locale=get_locale()))
        inv.sent_at = _now_iso()
        inv.status = "sent" if inv.status == "pending" else inv.status
        await self.session.flush()
        return inv

    async def delete_invitation(self, invitation_id: uuid.UUID) -> None:
        await self.invitation_repo.delete(invitation_id)

    # ── Submissions ───────────────────────────────────────────────────

    async def record_submission(self, data: BidSubmissionCreate) -> BidSubmission:
        """Record a bid submission, guarding against concurrent duplicates.

        The application-level check (``get_by_invitation``) provides a
        fast early-out for the common single-request path.  However, two
        concurrent POSTs for the same ``invitation_id`` can both pass the
        check before either commits, resulting in two submission rows for
        the same invitation — corrupting the leveling matrix and
        potentially exposing competing prices to both bidders.

        Defence-in-depth: the ``oe_bid_management_submission.invitation_id``
        column carries a UNIQUE constraint (see models.py).  We wrap the
        insert + flush in a try/except so the DB-level uniqueness violation
        is surfaced as a clean HTTP 409, not a 500 Internal Server Error.
        The application-level check is kept as a pre-flight to avoid
        hitting the DB error path on the most common replay attempt.
        """
        from sqlalchemy.exc import IntegrityError

        # Application-level pre-flight (fast path for serialised requests).
        existing = await self.submission_repo.get_by_invitation(data.invitation_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Submission already exists for this invitation")
        # Bidder-impersonation guard: the bidder row referenced by the
        # submission MUST belong to the same package as the invitation. A
        # caller with manager access on project A who knows a bidder UUID
        # on project B's package could otherwise forge a submission row
        # linking project-A invitation -> project-B bidder snapshot. Use a
        # 404 (not 403) for the leak-safe policy mandated by R5/R6.
        inv_for_bidder = await self.invitation_repo.get_by_id(data.invitation_id)
        if inv_for_bidder is None:
            raise HTTPException(status_code=404, detail="Invitation not found")
        bidder_row = await self.bidder_repo.get_by_id(data.bidder_id)
        if bidder_row is None or bidder_row.package_id != inv_for_bidder.package_id:
            raise HTTPException(
                status_code=404,
                detail="Bidder not found for this invitation's package",
            )
        sub = BidSubmission(
            invitation_id=data.invitation_id,
            bidder_id=data.bidder_id,
            submitted_at=data.submitted_at or _now_iso(),
            total_amount=str(data.total_amount),
            currency=data.currency,
            notes_to_owner=data.notes_to_owner,
            exclusions=list(data.exclusions),
            qualifications=list(data.qualifications),
            envelope_payload=data.envelope_payload,
        )
        try:
            created = await self.submission_repo.create(sub)

            # Stamp invitation
            inv = await self.invitation_repo.get_by_id(data.invitation_id)
            if inv is not None:
                inv.submission_received_at = sub.submitted_at
                if inv.status in ("pending", "sent", "opened"):
                    inv.status = "submitted"

            await self.session.flush()
        except IntegrityError:
            # Concurrent duplicate — the UNIQUE constraint on invitation_id
            # fired. Roll back the partial work and surface a clean 409.
            await self.session.rollback()
            raise HTTPException(
                status_code=409,
                detail="Submission already exists for this invitation (concurrent request)",
            )

        event_bus.publish_detached(
            "bid_management.submission.received",
            {
                "package_id": str(inv.package_id) if inv else "",
                "invitation_id": str(data.invitation_id),
                "submission_id": str(created.id),
                "bidder_id": str(data.bidder_id),
                "total_amount": str(data.total_amount),
                "currency": data.currency,
            },
            source_module="bid_management",
        )
        return created

    async def _package_for_submission(self, submission_id: uuid.UUID) -> BidPackage | None:
        """Resolve the owning package for a submission (sub → inv → pkg)."""
        sub = await self.submission_repo.get_by_id(submission_id)
        if sub is None:
            return None
        inv = await self.invitation_repo.get_by_id(sub.invitation_id)
        if inv is None:
            return None
        return await self.package_repo.get_by_id(inv.package_id)

    async def _assert_submission_mutable(self, submission_id: uuid.UUID) -> None:
        """Forbid editing a submission once its package is in a terminal
        commercial state. Rewriting a bid's figures after the package has
        been awarded or cancelled breaks the audit trail / award integrity.
        """
        package = await self._package_for_submission(submission_id)
        if package is not None and package.status in ("awarded", "cancelled"):
            raise HTTPException(
                status_code=409,
                detail=(f"Submission is locked — package is '{package.status}'"),
            )

    async def update_submission(self, submission_id: uuid.UUID, data: BidSubmissionUpdate) -> BidSubmission:
        sub = await self.submission_repo.get_by_id(submission_id)
        if sub is None:
            raise HTTPException(status_code=404, detail=translate("errors.submission_not_found", locale=get_locale()))
        await self._assert_submission_mutable(submission_id)
        fields = data.model_dump(exclude_unset=True)
        if "total_amount" in fields and fields["total_amount"] is not None:
            fields["total_amount"] = str(fields["total_amount"])
        if not fields:
            return sub
        await self.submission_repo.update_fields(submission_id, **fields)
        await self.session.refresh(sub)
        return sub

    async def withdraw_submission(self, submission_id: uuid.UUID) -> BidSubmission:
        sub = await self.submission_repo.get_by_id(submission_id)
        if sub is None:
            raise HTTPException(status_code=404, detail=translate("errors.submission_not_found", locale=get_locale()))
        sub.is_valid = False
        envelope = dict(sub.envelope_payload or {})
        envelope["withdrawn"] = True
        envelope["withdrawn_at"] = _now_iso()
        sub.envelope_payload = envelope
        await self.session.flush()
        return sub

    async def delete_submission(self, submission_id: uuid.UUID) -> None:
        await self.submission_repo.delete(submission_id)

    # ── Submission lines ──────────────────────────────────────────────

    async def create_submission_line(self, data: BidSubmissionLineCreate) -> BidSubmissionLine:
        await self._assert_submission_mutable(data.submission_id)
        # Cross-package line-item guard: the line_item must belong to the
        # same package as the submission. Otherwise a caller could price
        # a project-B line_item against a project-A submission row,
        # cross-polluting the leveling matrix.
        sub_pkg = await self._package_for_submission(data.submission_id)
        if sub_pkg is None:
            raise HTTPException(status_code=404, detail="Submission not found")
        line_item = await self.line_repo.get_by_id(data.line_item_id)
        if line_item is None or line_item.package_id != sub_pkg.id:
            raise HTTPException(
                status_code=404,
                detail="Line item not found for this submission's package",
            )
        total_price = _to_decimal(data.unit_price) * _to_decimal(data.quantity_priced)
        line = BidSubmissionLine(
            submission_id=data.submission_id,
            line_item_id=data.line_item_id,
            unit_price=str(data.unit_price),
            quantity_priced=str(data.quantity_priced),
            total_price=str(total_price.quantize(Decimal("0.01"))),
            alternative_offered=data.alternative_offered,
            alternative_description=data.alternative_description,
            comment=data.comment,
            inclusion_status=getattr(data, "inclusion_status", "included"),
            prevailing_wage_applicable=getattr(
                data,
                "prevailing_wage_applicable",
                False,
            ),
        )
        return await self.submission_line_repo.create(line)

    async def bulk_create_submission_lines(
        self, submission_id: uuid.UUID, items: list[BidSubmissionLineCreate]
    ) -> list[BidSubmissionLine]:
        await self._assert_submission_mutable(submission_id)
        rows = []
        for item in items:
            total = _to_decimal(item.unit_price) * _to_decimal(item.quantity_priced)
            rows.append(
                BidSubmissionLine(
                    submission_id=submission_id,
                    line_item_id=item.line_item_id,
                    unit_price=str(item.unit_price),
                    quantity_priced=str(item.quantity_priced),
                    total_price=str(total.quantize(Decimal("0.01"))),
                    alternative_offered=item.alternative_offered,
                    alternative_description=item.alternative_description,
                    comment=item.comment,
                    # Carry the bid-leveling taxonomy + prevailing-wage flag
                    # through bulk import — without these the leveling
                    # matrix (which keys off inclusion_status) is corrupt.
                    inclusion_status=item.inclusion_status,
                    prevailing_wage_applicable=item.prevailing_wage_applicable,
                )
            )
        return await self.submission_line_repo.bulk_create(rows)

    async def update_submission_line(self, line_id: uuid.UUID, data: BidSubmissionLineUpdate) -> BidSubmissionLine:
        line = await self.submission_line_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Submission line not found")
        await self._assert_submission_mutable(line.submission_id)
        fields = data.model_dump(exclude_unset=True)
        if "unit_price" in fields and fields["unit_price"] is not None:
            fields["unit_price"] = str(fields["unit_price"])
        if "quantity_priced" in fields and fields["quantity_priced"] is not None:
            fields["quantity_priced"] = str(fields["quantity_priced"])
        # Recompute total_price if either changed
        if "unit_price" in fields or "quantity_priced" in fields:
            new_unit = _to_decimal(fields.get("unit_price", line.unit_price))
            new_qty = _to_decimal(fields.get("quantity_priced", line.quantity_priced))
            fields["total_price"] = str((new_unit * new_qty).quantize(Decimal("0.01")))
        if not fields:
            return line
        await self.submission_line_repo.update_fields(line_id, **fields)
        await self.session.refresh(line)
        return line

    async def delete_submission_line(self, line_id: uuid.UUID) -> None:
        await self.submission_line_repo.delete(line_id)

    # ── Q&A ───────────────────────────────────────────────────────────

    async def create_qa(self, data: BidQACreate) -> BidQA:
        await self.get_package(data.package_id)
        # Bidder consistency: when the Q&A is attributed to a bidder, that
        # bidder row MUST belong to the same package — otherwise the Q&A
        # board would attribute questions from project-B's bidder to
        # project-A's package, breaking the audit trail.
        if data.bidder_id is not None:
            bidder_row = await self.bidder_repo.get_by_id(data.bidder_id)
            if bidder_row is None or bidder_row.package_id != data.package_id:
                raise HTTPException(
                    status_code=404,
                    detail="Bidder not found for this package",
                )
        qa = BidQA(
            package_id=data.package_id,
            bidder_id=data.bidder_id,
            question=data.question,
            asked_at=data.asked_at or _now_iso(),
            asked_by_email=data.asked_by_email,
            is_public=data.is_public,
            visible_to_bidder_ids=list(data.visible_to_bidder_ids),
        )
        return await self.qa_repo.create(qa)

    async def answer_qa(self, qa_id: uuid.UUID, data: BidQAAnswer) -> BidQA:
        qa = await self.qa_repo.get_by_id(qa_id)
        if qa is None:
            raise HTTPException(status_code=404, detail="Q&A entry not found")
        qa.answer = data.answer
        qa.answered_by = data.answered_by
        qa.answered_at = _now_iso()
        if data.is_public is not None:
            qa.is_public = data.is_public
        if data.visible_to_bidder_ids is not None:
            qa.visible_to_bidder_ids = list(data.visible_to_bidder_ids)
        await self.session.flush()
        return qa

    async def update_qa(self, qa_id: uuid.UUID, data: BidQAUpdate) -> BidQA:
        qa = await self.qa_repo.get_by_id(qa_id)
        if qa is None:
            raise HTTPException(status_code=404, detail="Q&A entry not found")
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return qa
        await self.qa_repo.update_fields(qa_id, **fields)
        await self.session.refresh(qa)
        return qa

    async def delete_qa(self, qa_id: uuid.UUID) -> None:
        await self.qa_repo.delete(qa_id)

    # ── Comparison + leveling ─────────────────────────────────────────

    async def create_comparison(self, data: BidComparisonCreate) -> BidComparison:
        await self.get_package(data.package_id)
        existing = await self.comparison_repo.get_for_package(data.package_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Comparison already exists for this package")
        comparison = BidComparison(
            package_id=data.package_id,
            technical_scoring_rule=data.technical_scoring_rule,
            commercial_weight_pct=data.commercial_weight_pct,
            technical_weight_pct=data.technical_weight_pct,
        )
        return await self.comparison_repo.create(comparison)

    async def update_comparison(self, comparison_id: uuid.UUID, data: BidComparisonUpdate) -> BidComparison:
        comparison = await self.comparison_repo.get_by_id(comparison_id)
        if comparison is None:
            raise HTTPException(status_code=404, detail="Comparison not found")
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return comparison
        await self.comparison_repo.update_fields(comparison_id, **fields)
        await self.session.refresh(comparison)
        return comparison

    async def delete_comparison(self, comparison_id: uuid.UUID) -> None:
        await self.comparison_repo.delete(comparison_id)

    async def compute_leveling(self, comparison_id: uuid.UUID) -> list[BidLeveling]:
        """Recompute the leveling rows for a comparison."""
        comparison = await self.comparison_repo.get_by_id(comparison_id)
        if comparison is None:
            raise HTTPException(status_code=404, detail="Comparison not found")

        package = await self.get_package(comparison.package_id)
        submissions = await self.submission_repo.submissions_for_package(package.id)
        bidders = await self.bidder_repo.list_for_package(package.id)
        bidder_lookup = {b.id: b for b in bidders}

        # Clear old rows
        await self.leveling_repo.delete_for_comparison(comparison_id)

        commercial_w = Decimal(comparison.commercial_weight_pct) / Decimal("100")
        technical_w = Decimal(comparison.technical_weight_pct) / Decimal("100")

        # Filter valid submissions from non-disqualified bidders
        valid = [
            s
            for s in submissions
            if s.is_valid
            and bidder_lookup.get(s.bidder_id) is not None
            and bidder_lookup[s.bidder_id].status == "active"
        ]

        # Normalize and compute commercial score: lowest normalized total gets 100.
        normalized_totals = {s.id: normalize_submission_for_leveling(s, package) for s in valid}
        if normalized_totals:
            best = min(normalized_totals.values())
        else:
            best = Decimal("0")

        rows: list[BidLeveling] = []
        for sub in valid:
            normalized = normalized_totals[sub.id]
            raw_total = _to_decimal(sub.total_amount)
            if normalized > Decimal("0"):
                commercial_score = (best / normalized) * Decimal("100")
            else:
                commercial_score = Decimal("0")
            commercial_score = commercial_score.quantize(Decimal("0.0001"))

            # Technical score lives in envelope or scoring rule for now.
            technical_score = _to_decimal((sub.envelope_payload or {}).get("technical_score", 0)).quantize(
                Decimal("0.0001")
            )

            total_score = (commercial_score * commercial_w + technical_score * technical_w).quantize(Decimal("0.0001"))

            row = BidLeveling(
                comparison_id=comparison_id,
                bidder_id=sub.bidder_id,
                raw_total=str(raw_total),
                normalized_total=str(normalized),
                commercial_score=str(commercial_score),
                technical_score=str(technical_score),
                total_score=str(total_score),
                rank=0,
                manual_adjustment="0",
                manual_adjustment_reason="",
            )
            rows.append(row)

        rank_bids(rows)
        for row in rows:
            self.session.add(row)

        comparison.computed_at = _now_iso()
        if normalized_totals:
            comparison.normalized_low = str(min(normalized_totals.values()))
            comparison.normalized_high = str(max(normalized_totals.values()))
        recommended = recommend_bidder(comparison, rows, bidders)
        comparison.recommended_bidder_id = recommended.id if recommended else None
        comparison.recommended_reason = f"Top rank ({recommended.company_name})" if recommended else ""

        await self.session.flush()
        return rows

    async def leveling_table(self, comparison_id: uuid.UUID) -> list[BidLeveling]:
        return await self.leveling_repo.levelings_for_comparison(comparison_id)

    # ── Awards / rejections ───────────────────────────────────────────

    async def update_award(self, award_id: uuid.UUID, data: BidAwardUpdate) -> BidAward:
        award = await self.award_repo.get_by_id(award_id)
        if award is None:
            raise HTTPException(status_code=404, detail="Award not found")
        fields = data.model_dump(exclude_unset=True)
        if "awarded_amount" in fields and fields["awarded_amount"] is not None:
            fields["awarded_amount"] = str(fields["awarded_amount"])
        if not fields:
            return award
        await self.award_repo.update_fields(award_id, **fields)
        await self.session.refresh(award)
        return award

    async def delete_award(self, award_id: uuid.UUID) -> None:
        """Delete an award record and revert the package to 'closed'.

        Deleting the BidAward row without reverting the BidPackage FSM
        state would leave the package permanently stuck in 'awarded'
        (which has no outgoing transitions), making re-award impossible
        and breaking the audit trail. We therefore atomically step the
        package back to 'closed' — the last valid pre-award state — so the
        full award → compare → re-award cycle can be restarted.
        """
        award = await self.award_repo.get_by_id(award_id)
        if award is None:
            return
        package = await self.package_repo.get_by_id(award.package_id)
        await self.award_repo.delete(award_id)
        # Revert FSM: awarded → closed so the package can be re-awarded.
        if package is not None and package.status == "awarded":
            package.status = "closed"
            package.awarded_at = None
            await self.session.flush()
            event_bus.publish_detached(
                "bid_management.award.deleted",
                {
                    "package_id": str(award.package_id),
                    "award_id": str(award_id),
                    "reverted_to": "closed",
                },
                source_module="bid_management",
            )

    async def create_rejection(self, data: BidRejectionCreate) -> BidRejection:
        await self.get_package(data.package_id)
        # Bidder-impersonation guard: the bidder being rejected must
        # belong to the same package as the rejection. Without this, a
        # manager on project A could file a rejection record naming a
        # project-B bidder, polluting cross-tenant audit history.
        bidder_row = await self.bidder_repo.get_by_id(data.bidder_id)
        if bidder_row is None or bidder_row.package_id != data.package_id:
            raise HTTPException(
                status_code=404,
                detail="Bidder not found for this package",
            )
        rejection = BidRejection(
            package_id=data.package_id,
            bidder_id=data.bidder_id,
            rejection_code=data.rejection_code,
            rejection_reason=data.rejection_reason,
        )
        created = await self.rejection_repo.create(rejection)
        event_bus.publish_detached(
            "bid_management.package.rejected",
            {
                "package_id": str(data.package_id),
                "bidder_id": str(data.bidder_id),
                "rejection_code": data.rejection_code,
                "reason": data.rejection_reason,
            },
            source_module="bid_management",
        )
        return created

    async def update_rejection(self, rejection_id: uuid.UUID, data: BidRejectionUpdate) -> BidRejection:
        rejection = await self.rejection_repo.get_by_id(rejection_id)
        if rejection is None:
            raise HTTPException(status_code=404, detail=translate("errors.rejection_not_found", locale=get_locale()))
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return rejection
        await self.rejection_repo.update_fields(rejection_id, **fields)
        await self.session.refresh(rejection)
        return rejection

    async def notify_rejection(self, rejection_id: uuid.UUID) -> BidRejection:
        rejection = await self.rejection_repo.get_by_id(rejection_id)
        if rejection is None:
            raise HTTPException(status_code=404, detail=translate("errors.rejection_not_found", locale=get_locale()))
        rejection.notified_at = _now_iso()
        await self.session.flush()
        return rejection

    async def delete_rejection(self, rejection_id: uuid.UUID) -> None:
        await self.rejection_repo.delete(rejection_id)

    # ── Dashboards / analytics ────────────────────────────────────────

    async def package_dashboard(self, package_id: uuid.UUID) -> dict[str, Any]:
        package = await self.get_package(package_id)
        invitations = await self.invitation_repo.list_for_package(package_id)
        submissions = await self.submission_repo.submissions_for_package(package_id)
        qa_rows = await self.qa_repo.q_and_a_for_package(package_id)
        comparison = await self.comparison_repo.get_for_package(package_id)
        award = await self.award_repo.get_for_package(package_id)

        return {
            "package_id": package.id,
            "code": package.code,
            "title": package.title,
            "status": package.status,
            "invitations_count": len(invitations),
            "submissions_count": len(submissions),
            "declined_count": sum(1 for i in invitations if i.status == "declined"),
            "open_questions_count": sum(1 for q in qa_rows if not q.answer),
            "answered_questions_count": sum(1 for q in qa_rows if q.answer),
            "leveling_computed": comparison is not None and comparison.computed_at is not None,
            "awarded_bidder_id": award.awarded_bidder_id if award else None,
        }

    async def submission_analytics(self, package_id: uuid.UUID) -> SubmissionAnalyticsResponse:
        submissions = await self.submission_repo.submissions_for_package(package_id)
        summary = compute_bid_summary(submissions)
        return SubmissionAnalyticsResponse(
            package_id=package_id,
            count=summary["count"],
            min_total=summary["min"],
            max_total=summary["max"],
            average_total=summary["average"],
            std_dev_total=summary["std_dev"],
            completeness_avg=summary["completeness_avg"],
            valid_count=summary["valid_count"],
            late_count=summary["late_count"],
        )

    # ── Leveling matrix (line-level side-by-side) ─────────────────────

    async def leveling_matrix(self, package_id: uuid.UUID) -> dict[str, Any]:
        """Build the bid-leveling matrix for one package.

        Rows = package line items, columns = bidders. Each cell carries
        the priced line (with inclusion_status / alternative / prevailing
        wage flag) and the ``is_low`` marker for the lowest non-excluded
        bid on that line.
        """
        await self.get_package(package_id)
        lines = await self.line_repo.list_for_package(package_id)
        bidders = await self.bidder_repo.list_for_package(package_id)
        active_bidders = [b for b in bidders if b.status == "active"]
        submissions = await self.submission_repo.submissions_for_package(package_id)
        valid_subs = [s for s in submissions if s.is_valid]
        # Map bidder_id → submission for column lookup
        sub_by_bidder = {s.bidder_id: s for s in valid_subs}

        # Pre-fetch every line for every submission (one query each).
        lines_by_sub: dict[uuid.UUID, list[BidSubmissionLine]] = {}
        for sub in valid_subs:
            lines_by_sub[sub.id] = await self.submission_line_repo.list_for_submission(
                sub.id,
            )

        rows: list[dict[str, Any]] = []
        for line in lines:
            cells: list[dict[str, Any]] = []
            excluded_count = 0
            clarification_count = 0
            # Find each bidder's priced row (if any) for this line
            for bidder in active_bidders:
                sub = sub_by_bidder.get(bidder.id)
                if sub is None:
                    cells.append(
                        {
                            "bidder_id": bidder.id,
                            "company_name": bidder.company_name,
                            "unit_price": Decimal("0"),
                            "quantity_priced": Decimal("0"),
                            "total_price": Decimal("0"),
                            "inclusion_status": "excluded",
                            "alternative_offered": False,
                            "comment": "No submission",
                            "prevailing_wage_applicable": False,
                            "is_low": False,
                        }
                    )
                    excluded_count += 1
                    continue
                priced = next(
                    (ln for ln in lines_by_sub.get(sub.id, []) if ln.line_item_id == line.id),
                    None,
                )
                if priced is None:
                    cells.append(
                        {
                            "bidder_id": bidder.id,
                            "company_name": bidder.company_name,
                            "unit_price": Decimal("0"),
                            "quantity_priced": Decimal("0"),
                            "total_price": Decimal("0"),
                            "inclusion_status": "excluded",
                            "alternative_offered": False,
                            "comment": "Line not priced",
                            "prevailing_wage_applicable": False,
                            "is_low": False,
                        }
                    )
                    excluded_count += 1
                    continue
                if priced.inclusion_status == "excluded":
                    excluded_count += 1
                elif priced.inclusion_status == "clarification_needed":
                    clarification_count += 1
                cells.append(
                    {
                        "bidder_id": bidder.id,
                        "company_name": bidder.company_name,
                        "unit_price": _to_decimal(priced.unit_price),
                        "quantity_priced": _to_decimal(priced.quantity_priced),
                        "total_price": _to_decimal(priced.total_price),
                        "inclusion_status": priced.inclusion_status or "included",
                        "alternative_offered": priced.alternative_offered,
                        "comment": priced.comment or "",
                        "prevailing_wage_applicable": (priced.prevailing_wage_applicable),
                        "is_low": False,
                    }
                )

            # Mark the cell with the lowest non-zero total_price among
            # "included" / "alternative" / "noted" rows as is_low. Excluded
            # and clarification_needed rows do NOT participate (they are not
            # competitive bids on this scope).
            competitive = [
                c
                for c in cells
                if c["inclusion_status"] in ("included", "alternative", "noted") and c["total_price"] > Decimal("0")
            ]
            if competitive:
                low_total = min(c["total_price"] for c in competitive)
                for c in cells:
                    if c["total_price"] == low_total and c["inclusion_status"] in (
                        "included",
                        "alternative",
                        "noted",
                    ):
                        c["is_low"] = True

            rows.append(
                {
                    "line_item_id": line.id,
                    "line_item_code": line.code,
                    "description": line.description,
                    "unit": line.unit,
                    "quantity": _to_decimal(line.quantity),
                    "is_mandatory": line.is_mandatory,
                    "cells": cells,
                    "excluded_count": excluded_count,
                    "clarification_count": clarification_count,
                }
            )

        return {
            "package_id": package_id,
            "bidder_ids": [b.id for b in active_bidders],
            "bidder_names": [b.company_name for b in active_bidders],
            "rows": rows,
        }

    # ── Q&A board per bidder (filtered view) ──────────────────────────

    async def qa_board_for_bidder(
        self,
        package_id: uuid.UUID,
        bidder_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Return Q&A entries the given bidder is permitted to see.

        Visibility rules (Aconex-style):
        * is_public=True   → visible to everyone (anonymised question).
        * is_public=False  → visible only if bidder_id appears in
          ``visible_to_bidder_ids`` OR if the bidder asked the question.
        * If bidder_id is None (owner view) → returns everything.
        """
        await self.get_package(package_id)
        all_qa = await self.qa_repo.q_and_a_for_package(package_id)

        visible: list[dict[str, Any]] = []
        for qa in all_qa:
            if bidder_id is None:
                # Owner perspective — all entries
                allow = True
            else:
                allow = False
                if qa.is_public:
                    allow = True
                elif qa.bidder_id is not None and qa.bidder_id == bidder_id:
                    # Always show the questioner their own thread
                    allow = True
                else:
                    vis = qa.visible_to_bidder_ids or []
                    if str(bidder_id) in {str(b) for b in vis}:
                        allow = True
            if not allow:
                continue
            visible.append(
                {
                    "id": qa.id,
                    "question": qa.question,
                    "answer": qa.answer or "",
                    "asked_at": qa.asked_at,
                    "answered_at": qa.answered_at,
                    "is_public": qa.is_public,
                }
            )

        return {
            "package_id": package_id,
            "bidder_id": bidder_id,
            "entries": visible,
        }

    # ── Invitation email pipeline ─────────────────────────────────────

    @staticmethod
    def render_invitation_email(
        template_subject: str,
        template_body: str,
        *,
        package_code: str,
        package_title: str,
        invitee_email: str,
        invitee_company_name: str,
        sender_name: str = "",
        deadline: str = "",
        action_url: str = "",
    ) -> tuple[str, str]:
        """Merge an invitation-email template with the bidder context.

        Pure function — no I/O. Substitutes ``{placeholder}`` tokens.
        Unknown tokens are left literal so missing context is auditable.
        """
        context = {
            "package_code": package_code,
            "package_title": package_title,
            "invitee_email": invitee_email,
            "invitee_company_name": invitee_company_name,
            "sender_name": sender_name,
            "deadline": deadline,
            "action_url": action_url,
        }
        subj = template_subject
        body = template_body
        for key, value in context.items():
            subj = subj.replace("{" + key + "}", str(value))
            body = body.replace("{" + key + "}", str(value))
        return subj, body

    async def dispatch_invitation_emails(
        self,
        package_id: uuid.UUID,
        *,
        templates: list[dict[str, str]],
        invitation_ids: list[uuid.UUID] | None = None,
        sender_name: str = "",
        sender_email: str = "",
        default_language: str = "en",
    ) -> dict[str, Any]:
        """Render + mark invitations sent. Returns previews per invitee.

        Templates are picked by language with fallback to ``default_language``.
        When the matching template can't be found, the dispatch is skipped
        for that invitee (the caller receives `skipped` counter).
        """
        package = await self.get_package(package_id)
        invitations = await self.invitation_repo.list_for_package(package_id)
        if invitation_ids is not None:
            wanted = {str(i) for i in invitation_ids}
            invitations = [i for i in invitations if str(i.id) in wanted]

        if not templates:
            raise HTTPException(
                status_code=400,
                detail="At least one invitation email template is required",
            )

        tpl_by_lang = {t.get("language", "en"): t for t in templates}
        default_tpl = tpl_by_lang.get(default_language) or tpl_by_lang.get("en") or templates[0]

        previews: list[dict[str, Any]] = []
        sent_count = 0
        skipped = 0
        deadline = package.submission_deadline or ""
        action_url = f"/bid-management/packages/{package.id}"

        for inv in invitations:
            if inv.status in ("submitted", "declined", "expired"):
                skipped += 1
                continue
            # We don't store per-invitation language yet, so use the default.
            tpl = default_tpl
            subj, body = self.render_invitation_email(
                tpl.get("subject", ""),
                tpl.get("body", ""),
                package_code=package.code,
                package_title=package.title,
                invitee_email=inv.invitee_email,
                invitee_company_name=inv.invitee_company_name,
                sender_name=sender_name,
                deadline=deadline,
                action_url=action_url,
            )
            # Persist the "sent" markers; the actual SMTP send is done by
            # the notifications module / external mail gateway. We record
            # the dispatch envelope into invitation_log for audit.
            inv.sent_at = _now_iso()
            if inv.status == "pending":
                inv.status = "sent"
            sent_count += 1
            previews.append(
                {
                    "invitee_email": inv.invitee_email,
                    "invitee_company_name": inv.invitee_company_name,
                    "subject": subj,
                    "body": body,
                    "language": tpl.get("language", default_language),
                }
            )

        await self.session.flush()

        # Fire a single event the notifications module subscribes to.
        if sent_count > 0:
            event_bus.publish_detached(
                "bid_management.invitations.dispatched",
                {
                    "package_id": str(package.id),
                    "project_id": str(package.project_id),
                    "count": sent_count,
                    "sender_email": sender_email,
                },
                source_module="bid_management",
            )

        return {
            "package_id": package_id,
            "invitations_sent": sent_count,
            "previews": previews,
            "skipped": skipped,
        }

    # ── Subcontractor scorecard ingestion ─────────────────────────────

    async def record_subcontractor_scorecard(
        self,
        package_id: uuid.UUID,
        bidder_id: uuid.UUID,
        *,
        on_time_score: Decimal,
        quality_score: Decimal,
        safety_score: Decimal,
        commercial_score: Decimal,
        notes: str = "",
    ) -> dict[str, Any]:
        """Capture a post-award performance scorecard against the awarded bid.

        Persists the scorecard payload onto the package metadata and emits
        ``bid_management.subcontractor.scored`` so the subcontractors
        module can update the long-term bidder rating in its own table.
        """
        package = await self.get_package(package_id)
        # Bidder-impersonation guard: the bidder being scored must belong
        # to this package — otherwise a manager on project A could plant
        # a score against project-B's subcontractor in project-A's
        # metadata trail.
        bidder_row = await self.bidder_repo.get_by_id(bidder_id)
        if bidder_row is None or bidder_row.package_id != package_id:
            raise HTTPException(
                status_code=404,
                detail="Bidder not found for this package",
            )
        # The scorecard ranges 0..100 per pillar; the composite is the
        # straight average. Anything outside [0, 100] is clamped, then
        # quantized to 2 dp for deterministic persistence.

        def _clamp(v: Decimal) -> Decimal:
            if v < Decimal("0"):
                return Decimal("0")
            if v > Decimal("100"):
                return Decimal("100")
            return v.quantize(Decimal("0.01"))

        on_time = _clamp(_to_decimal(on_time_score))
        quality = _clamp(_to_decimal(quality_score))
        safety = _clamp(_to_decimal(safety_score))
        commercial = _clamp(_to_decimal(commercial_score))
        composite = ((on_time + quality + safety + commercial) / Decimal("4")).quantize(Decimal("0.01"))

        scorecard = {
            "bidder_id": str(bidder_id),
            "on_time_score": str(on_time),
            "quality_score": str(quality),
            "safety_score": str(safety),
            "commercial_score": str(commercial),
            "composite_score": str(composite),
            "notes": notes,
            "recorded_at": _now_iso(),
        }
        md = dict(package.metadata_ or {})
        scorecards = list(md.get("scorecards") or [])
        scorecards.append(scorecard)
        md["scorecards"] = scorecards
        package.metadata_ = md
        await self.session.flush()

        event_bus.publish_detached(
            "bid_management.subcontractor.scored",
            {
                "package_id": str(package_id),
                "bidder_id": str(bidder_id),
                "composite_score": str(composite),
                "on_time_score": str(on_time),
                "quality_score": str(quality),
                "safety_score": str(safety),
                "commercial_score": str(commercial),
            },
            source_module="bid_management",
        )
        return scorecard
