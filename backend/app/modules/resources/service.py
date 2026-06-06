"""‌⁠‍Resources service - business logic for assignment, conflicts, skill matching."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.resources.models import (
    Assignment,
    AvailabilityWindow,
    Certification,
    Resource,
    ResourceLink,
    ResourceRequest,
    ResourceSkill,
    Skill,
)
from app.modules.resources.repository import (
    AssignmentRepository,
    AvailabilityWindowRepository,
    CertificationRepository,
    ResourceLinkRepository,
    ResourceRepository,
    ResourceRequestRepository,
    ResourceSkillRepository,
    SkillRepository,
)
from app.modules.resources.schemas import (
    AssignmentCreate,
    AssignmentProposeRequest,
    AssignmentUpdate,
    AvailabilityWindowCreate,
    AvailabilityWindowUpdate,
    CertificationCreate,
    CertificationUpdate,
    ConflictDetail,
    ResourceCreate,
    ResourceLinkCreate,
    ResourceLinkUpdate,
    ResourceRequestCreate,
    ResourceRequestFulfill,
    ResourceRequestUpdate,
    ResourceSkillCreate,
    ResourceUpdate,
    SkillCreate,
    SkillUpdate,
    UtilizationResponse,
)

logger = logging.getLogger(__name__)


# ── Exceptions ─────────────────────────────────────────────────────────────


class ResourceConflictError(ValueError):
    """‌⁠‍Raised when a proposed assignment conflicts with existing ones."""

    def __init__(self, message: str, conflicts: list[ConflictDetail]) -> None:
        super().__init__(message)
        self.conflicts = conflicts


class SkillMismatchError(ValueError):
    """‌⁠‍Raised when a resource does not satisfy required skills."""

    def __init__(self, message: str, missing: list[str]) -> None:
        super().__init__(message)
        self.missing = missing


# ── Assignment status FSM ──────────────────────────────────────────────────

# Allowed status transitions for an Assignment. A self-transition (target ==
# current) is always permitted and treated as a no-op. The dedicated
# confirm/complete/cancel endpoints enforce subsets of this table; the generic
# PATCH (update_assignment) must honour the SAME rules so the Edit Assignment
# modal cannot push a row through an illegal jump (e.g. completed -> proposed or
# cancelled -> confirmed), which would corrupt utilization/availability math.
ASSIGNMENT_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"confirmed", "cancelled"}),
    "confirmed": frozenset({"in_progress", "completed", "cancelled"}),
    "in_progress": frozenset({"completed", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


# ── Pure helpers ───────────────────────────────────────────────────────────


def _as_aware(dt: datetime) -> datetime:
    """Coerce a datetime to timezone-aware UTC.

    Columns are declared ``DateTime(timezone=True)`` (so Postgres returns aware
    values), but SQLite - used in dev and on the single-node VPS - ignores the
    timezone flag and hands back naive datetimes. Comparing such a naive value
    with ``datetime.now(UTC)`` raises ``TypeError: can't compare offset-naive and
    offset-aware datetimes`` (a 500 on every resource dashboard). Stored values
    are UTC by convention, so attaching UTC to a naive value is correct; aware
    values pass through unchanged.
    """
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _intervals_overlap(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> bool:
    """True if [a_start, a_end) and [b_start, b_end) overlap. Edge-touch ⇒ False."""
    return a_start < b_end and b_start < a_end


def _build_capacity_buckets(
    start: datetime,
    end: datetime,
    bucket: str,
    *,
    max_buckets: int = 60,
) -> list[tuple[int, datetime, datetime, str]]:
    """Slice [start, end) into fixed-width buckets for the capacity heatmap.

    ``week`` ⇒ 7-day columns, ``month`` ⇒ 30-day columns. The count is capped
    at ``max_buckets`` so a wide window never produces an unbounded payload;
    the last bucket is clamped to ``end``. Returns (index, start, end, label).
    """
    step = timedelta(days=30 if bucket == "month" else 7)
    out: list[tuple[int, datetime, datetime, str]] = []
    cursor = start
    idx = 0
    while cursor < end and idx < max_buckets:
        b_end = min(cursor + step, end)
        label = cursor.strftime("%b %d")
        out.append((idx, cursor, b_end, label))
        cursor = b_end
        idx += 1
    return out


# Assignment states that consume capacity for leveling purposes. Cancelled
# bookings never consumed the resource; completed bookings are in the past and
# cannot be re-levelled, so neither contributes to a forward-looking overload.
_LEVELING_ACTIVE_STATES: frozenset[str] = frozenset({"proposed", "confirmed", "in_progress"})


def build_leveling_suggestions(
    bucket_index: int,
    capacity_percent: int,
    bucket_bookings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pure: propose leveling actions for one over-allocated bucket.

    Given the bookings overlapping a single bucket and the resource's known
    ``capacity_percent``, return read-only suggestions that, if a human applied
    them, would bring the bucket back to (or below) capacity. No mutation is
    performed and no booking is auto-moved.

    Each ``bucket_bookings`` entry is a dict with at least:
        ``assignment_id`` (uuid), ``project_id`` (uuid | None),
        ``project_name`` (str), ``allocation_percent`` (int).

    Strategy (deterministic so the same input always yields the same advice):
        1. ``shift``  the smallest contributing booking out of the bucket if it
           alone is enough to clear the overflow.
        2. otherwise ``spread`` the largest contributing booking down to the
           allocation that just fits the remaining headroom.

    Returns an empty list when capacity is non-positive (caller must guard the
    "capacity unknown" path) or the bucket is within capacity.
    """
    if capacity_percent <= 0:
        return []
    total = sum(int(b.get("allocation_percent") or 0) for b in bucket_bookings)
    overflow = total - capacity_percent
    if overflow <= 0 or not bucket_bookings:
        return []

    suggestions: list[dict[str, Any]] = []
    # Sort smallest-first for the shift candidate, largest-first for spread.
    by_alloc_asc = sorted(bucket_bookings, key=lambda b: int(b.get("allocation_percent") or 0))
    smallest = by_alloc_asc[0]
    smallest_alloc = int(smallest.get("allocation_percent") or 0)

    if smallest_alloc >= overflow and smallest_alloc > 0:
        # Moving the smallest booking elsewhere clears the overload outright.
        suggestions.append(
            {
                "action": "shift",
                "bucket_index": bucket_index,
                "target_assignment_id": smallest["assignment_id"],
                "target_project_id": smallest.get("project_id"),
                "target_project_name": smallest.get("project_name", ""),
                "overflow_percent": overflow,
                "suggested_allocation_percent": 0,
                "rationale": (
                    f"Shift this {smallest_alloc}% booking to another period to "
                    f"clear the {overflow}% overload (capacity {capacity_percent}%)."
                ),
            }
        )
        return suggestions

    # Otherwise reduce the largest booking so the bucket just fits.
    largest = by_alloc_asc[-1]
    largest_alloc = int(largest.get("allocation_percent") or 0)
    suggested = max(0, largest_alloc - overflow)
    suggestions.append(
        {
            "action": "spread",
            "bucket_index": bucket_index,
            "target_assignment_id": largest["assignment_id"],
            "target_project_id": largest.get("project_id"),
            "target_project_name": largest.get("project_name", ""),
            "overflow_percent": overflow,
            "suggested_allocation_percent": suggested,
            "rationale": (
                f"Reduce this booking from {largest_alloc}% to {suggested}% (or "
                f"spread the work over more time) to fit the {capacity_percent}% "
                f"capacity; the bucket is {overflow}% over."
            ),
        }
    )
    return suggestions


def detect_conflicts(
    assignment_resource_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    allocation_percent: int,
    existing_for_resource: Iterable[Assignment],
    *,
    exclude_id: uuid.UUID | None = None,
) -> list[ConflictDetail]:
    """Pure: detect overlap conflicts between a candidate slot and existing assignments.

    A conflict is reported when the new allocation + sum of overlapping
    active allocations exceeds 100% during the overlap window. Cancelled /
    completed assignments are not considered conflicts.

    Args:
        assignment_resource_id: Resource being assigned.
        start_at: Candidate start.
        end_at: Candidate end.
        allocation_percent: Candidate allocation (0..100).
        existing_for_resource: All existing assignments for this resource.
        exclude_id: Skip this id when checking (used for update flow).
    """
    conflicts: list[ConflictDetail] = []
    if end_at <= start_at:
        conflicts.append(
            ConflictDetail(
                resource_id=assignment_resource_id,
                reason="invalid_window",
                overlap_start=start_at,
                overlap_end=end_at,
            )
        )
        return conflicts

    # Collect every active assignment that overlaps the candidate window.
    # Over-allocation is *cumulative*: three concurrent 40% bookings is
    # 120% and must be flagged even though no single pair exceeds 100%.
    # (The previous implementation summed the candidate with each existing
    # row independently, so N small overlaps that together blew the budget
    # slipped through silently - a real over-booking integrity hole.)
    overlapping: list[Assignment] = []
    for existing in existing_for_resource:
        if exclude_id is not None and existing.id == exclude_id:
            continue
        if existing.status in ("cancelled", "completed"):
            continue
        if not _intervals_overlap(start_at, end_at, existing.start_at, existing.end_at):
            continue
        overlapping.append(existing)

    existing_total = sum((e.allocation_percent or 0) for e in overlapping)
    cumulative = existing_total + (allocation_percent or 0)
    if cumulative > 100:
        for existing in overlapping:
            conflicts.append(
                ConflictDetail(
                    resource_id=assignment_resource_id,
                    conflicting_assignment_id=existing.id,
                    reason="overallocation",
                    overlap_start=max(start_at, existing.start_at),
                    overlap_end=min(end_at, existing.end_at),
                    total_allocation_percent=cumulative,
                )
            )
    return conflicts


def is_resource_available(
    resource_id: uuid.UUID,
    start: datetime,
    end: datetime,
    assignments: Iterable[Assignment],
    availability_windows: Iterable[AvailabilityWindow],
    *,
    allocation_percent: int = 100,
    exclude_assignment_id: uuid.UUID | None = None,
) -> bool:
    """Pure: True if resource has no blocking unavailability/holiday/sick window
    in [start, end) AND no overallocation from existing assignments.
    """
    if end <= start:
        return False

    # Blocking windows
    for w in availability_windows:
        if w.window_type in ("unavailable", "holiday", "sick"):
            if _intervals_overlap(start, end, w.start_at, w.end_at):
                return False

    # Allocation check
    used = 0
    for a in assignments:
        if exclude_assignment_id is not None and a.id == exclude_assignment_id:
            continue
        if a.resource_id != resource_id:
            continue
        if a.status in ("cancelled", "completed"):
            continue
        if _intervals_overlap(start, end, a.start_at, a.end_at):
            used += a.allocation_percent or 0
    return used + allocation_percent <= 100


def derive_certification_status(
    valid_until: str | None,
    revoked: bool,
    today: date,
) -> str:
    """Pure: derive certification status from valid_until and revoked flag.

    Returns one of: ``valid``, ``expired``, ``revoked``.
    """
    if revoked:
        return "revoked"
    if valid_until is None:
        return "valid"  # no expiry tracked ⇒ assume valid
    try:
        v = date.fromisoformat(valid_until[:10])
    except (ValueError, TypeError):
        return "valid"
    return "valid" if v >= today else "expired"


def validate_skill_requirements(
    resource_id: uuid.UUID,
    required_skills: Iterable[uuid.UUID],
    resource_skills: Iterable[ResourceSkill],
    certifications: Iterable[Certification],
    *,
    on_date: date,
    skill_to_cert_type: dict[uuid.UUID, str] | None = None,
) -> tuple[bool, list[str]]:
    """Pure: check if resource holds all required skills with non-expired certs.

    Args:
        resource_id: Resource being checked.
        required_skills: Set of skill IDs that must be present.
        resource_skills: All ResourceSkill rows for this resource.
        certifications: All certifications for this resource.
        on_date: Effective date (today usually) for expiry checks.
        skill_to_cert_type: Optional map skill_id → cert_type used to require
            a current cert for that skill.

    Returns:
        (passes, missing_reasons)
    """
    owned: dict[uuid.UUID, ResourceSkill] = {}
    for rs in resource_skills:
        if rs.resource_id == resource_id:
            owned[rs.skill_id] = rs

    missing: list[str] = []
    skill_to_cert = skill_to_cert_type or {}
    for sid in required_skills:
        if sid not in owned:
            missing.append(f"missing_skill:{sid}")
            continue
        rs = owned[sid]
        # If the resource-skill itself has an expires_at, honour it.
        if rs.expires_at:
            try:
                rs_until = date.fromisoformat(rs.expires_at[:10])
                if rs_until < on_date:
                    missing.append(f"expired_skill:{sid}")
                    continue
            except (ValueError, TypeError):
                pass
        # If a cert_type is required, look for a valid cert
        required_cert = skill_to_cert.get(sid)
        if required_cert is not None:
            has_valid = False
            for cert in certifications:
                if cert.resource_id != resource_id:
                    continue
                if cert.cert_type != required_cert:
                    continue
                status_derived = derive_certification_status(cert.valid_until, cert.status == "revoked", on_date)
                if status_derived == "valid":
                    has_valid = True
                    break
            if not has_valid:
                missing.append(f"missing_or_expired_cert:{required_cert}")
    return (len(missing) == 0, missing)


def compute_resource_utilization(
    resource_id: uuid.UUID,
    period_start: datetime,
    period_end: datetime,
    assignments: Iterable[Assignment],
    *,
    hours_per_day: float = 8.0,
) -> dict[str, float]:
    """Pure: compute utilization stats for a resource over a period.

    Counts overlap of each committed assignment with the period, weighted by
    allocation_percent. Tentative ('proposed') and 'cancelled' assignments are
    excluded. Returns dict with utilization_percent, hours_assigned,
    hours_available.
    """
    # Normalise to aware-UTC so naive (SQLite) and aware (Postgres) datetimes
    # can be compared regardless of which side the period bounds came from.
    period_start = _as_aware(period_start)
    period_end = _as_aware(period_end)
    if period_end <= period_start:
        return {"utilization_percent": 0.0, "hours_assigned": 0.0, "hours_available": 0.0}

    total_seconds = (period_end - period_start).total_seconds()
    # Calendar days in period × hours_per_day = nominal hours available
    days = total_seconds / 86400.0
    hours_available = days * hours_per_day

    hours_assigned = 0.0
    for a in assignments:
        if a.resource_id != resource_id:
            continue
        # Only committed work counts toward utilization. 'cancelled' never
        # consumed the resource, and 'proposed' is a tentative booking still
        # awaiting confirm/decline - counting either as assigned hours
        # inflates the figure and can push utilization past 100%.
        if a.status in ("cancelled", "proposed"):
            continue
        ov_start = max(period_start, _as_aware(a.start_at))
        ov_end = min(period_end, _as_aware(a.end_at))
        if ov_end <= ov_start:
            continue
        ov_sec = (ov_end - ov_start).total_seconds()
        ov_days = ov_sec / 86400.0
        ov_hours = ov_days * hours_per_day * ((a.allocation_percent or 0) / 100.0)
        hours_assigned += ov_hours

    util = (hours_assigned / hours_available * 100.0) if hours_available > 0 else 0.0
    return {
        "utilization_percent": round(util, 2),
        "hours_assigned": round(hours_assigned, 2),
        "hours_available": round(hours_available, 2),
    }


# ── ResourcesService ──────────────────────────────────────────────────────


class ResourcesService:
    """Business logic for resources, skills, certifications, assignments."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.resource_repo = ResourceRepository(session)
        self.skill_repo = SkillRepository(session)
        self.resource_skill_repo = ResourceSkillRepository(session)
        self.cert_repo = CertificationRepository(session)
        self.window_repo = AvailabilityWindowRepository(session)
        self.assignment_repo = AssignmentRepository(session)
        self.request_repo = ResourceRequestRepository(session)
        self.link_repo = ResourceLinkRepository(session)

    # ── Resource CRUD ──────────────────────────────────────────────────

    async def create_resource(self, data: ResourceCreate, user_id: str | None = None) -> Resource:
        existing = await self.resource_repo.get_by_code(data.code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Resource with code '{data.code}' already exists",
            )
        resource = Resource(
            code=data.code,
            name=data.name,
            resource_type=data.resource_type,
            home_project_id=data.home_project_id,
            contact_id=data.contact_id,
            default_cost_rate=data.default_cost_rate,
            currency=data.currency,
            capacity_percent=data.capacity_percent,
            status=data.status,
            avatar_url=data.avatar_url,
            notes=data.notes,
            metadata_=data.metadata,
        )
        resource = await self.resource_repo.create(resource)
        logger.info("Resource created: %s (%s)", data.code, data.resource_type)
        return resource

    async def get_resource(self, resource_id: uuid.UUID) -> Resource:
        resource = await self.resource_repo.get_by_id(resource_id)
        if resource is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.resource_not_found", locale=get_locale()),
            )
        return resource

    async def list_resources(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        resource_type: str | None = None,
        resource_status: str | None = None,
    ) -> tuple[list[Resource], int]:
        return await self.resource_repo.list_all(
            offset=offset,
            limit=limit,
            resource_type=resource_type,
            status=resource_status,
        )

    async def update_resource(self, resource_id: uuid.UUID, data: ResourceUpdate) -> Resource:
        resource = await self.get_resource(resource_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return resource
        await self.resource_repo.update_fields(resource_id, **fields)
        await self.session.refresh(resource)
        return resource

    async def delete_resource(self, resource_id: uuid.UUID) -> None:
        await self.get_resource(resource_id)
        await self.resource_repo.delete(resource_id)
        logger.info("Resource deleted: %s", resource_id)

    # ── Skill CRUD ─────────────────────────────────────────────────────

    async def create_skill(self, data: SkillCreate) -> Skill:
        existing = await self.skill_repo.get_by_code(data.code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Skill with code '{data.code}' already exists",
            )
        skill = Skill(
            code=data.code,
            name=data.name,
            category=data.category,
            description=data.description,
            metadata_=data.metadata,
        )
        return await self.skill_repo.create(skill)

    async def get_skill(self, skill_id: uuid.UUID) -> Skill:
        skill = await self.skill_repo.get_by_id(skill_id)
        if skill is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
        return skill

    async def list_skills(
        self, *, offset: int = 0, limit: int = 200, category: str | None = None
    ) -> tuple[list[Skill], int]:
        return await self.skill_repo.list_all(offset=offset, limit=limit, category=category)

    async def update_skill(self, skill_id: uuid.UUID, data: SkillUpdate) -> Skill:
        skill = await self.get_skill(skill_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return skill
        await self.skill_repo.update_fields(skill_id, **fields)
        await self.session.refresh(skill)
        return skill

    async def delete_skill(self, skill_id: uuid.UUID) -> None:
        await self.get_skill(skill_id)
        await self.skill_repo.delete(skill_id)

    # ── ResourceSkill management ──────────────────────────────────────

    async def attach_skill(self, resource_id: uuid.UUID, data: ResourceSkillCreate) -> ResourceSkill:
        await self.get_resource(resource_id)
        await self.get_skill(data.skill_id)
        existing = await self.resource_skill_repo.find_pair(resource_id, data.skill_id)
        if existing is not None:
            # Update level/dates in place
            existing.level = data.level
            existing.acquired_at = data.acquired_at
            existing.expires_at = data.expires_at
            existing.notes = data.notes
            await self.session.flush()
            return existing
        link = ResourceSkill(
            resource_id=resource_id,
            skill_id=data.skill_id,
            level=data.level,
            acquired_at=data.acquired_at,
            expires_at=data.expires_at,
            notes=data.notes,
        )
        return await self.resource_skill_repo.create(link)

    async def detach_skill(self, resource_id: uuid.UUID, skill_id: uuid.UUID) -> None:
        await self.resource_skill_repo.delete_pair(resource_id, skill_id)

    async def list_resource_skills(self, resource_id: uuid.UUID) -> list[ResourceSkill]:
        return await self.resource_skill_repo.list_for_resource(resource_id)

    # ── Certification CRUD ────────────────────────────────────────────

    async def create_certification(self, data: CertificationCreate) -> Certification:
        await self.get_resource(data.resource_id)
        # Auto-derive status if not provided as revoked
        revoked = data.status == "revoked"
        derived = derive_certification_status(data.valid_until, revoked, datetime.now(UTC).date())
        cert = Certification(
            resource_id=data.resource_id,
            cert_type=data.cert_type,
            cert_number=data.cert_number,
            issued_by=data.issued_by,
            issue_date=data.issue_date,
            valid_until=data.valid_until,
            document_url=data.document_url,
            status=derived,
            notes=data.notes,
            metadata_=data.metadata,
        )
        return await self.cert_repo.create(cert)

    async def get_certification(self, cert_id: uuid.UUID) -> Certification:
        cert = await self.cert_repo.get_by_id(cert_id)
        if cert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certification not found",
            )
        return cert

    async def list_certifications_for_resource(self, resource_id: uuid.UUID) -> list[Certification]:
        return await self.cert_repo.list_for_resource(resource_id)

    async def list_expiring_certifications(self, days: int = 60) -> list[Certification]:
        today = datetime.now(UTC).date()
        cutoff = today + timedelta(days=max(1, days))
        return await self.cert_repo.list_expiring(today_iso=today.isoformat(), cutoff_iso=cutoff.isoformat())

    async def update_certification(self, cert_id: uuid.UUID, data: CertificationUpdate) -> Certification:
        cert = await self.get_certification(cert_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        # Re-derive status if expiry changed
        new_valid_until = fields.get("valid_until", cert.valid_until)
        new_status_in = fields.get("status", cert.status)
        revoked = new_status_in == "revoked"
        fields["status"] = derive_certification_status(new_valid_until, revoked, datetime.now(UTC).date())
        if not fields:
            return cert
        await self.cert_repo.update_fields(cert_id, **fields)
        await self.session.refresh(cert)
        return cert

    async def delete_certification(self, cert_id: uuid.UUID) -> None:
        await self.get_certification(cert_id)
        await self.cert_repo.delete(cert_id)

    # ── AvailabilityWindow CRUD ───────────────────────────────────────

    async def create_window(self, data: AvailabilityWindowCreate) -> AvailabilityWindow:
        await self.get_resource(data.resource_id)
        if data.end_at <= data.start_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_at must be after start_at",
            )
        window = AvailabilityWindow(
            resource_id=data.resource_id,
            window_type=data.window_type,
            start_at=data.start_at,
            end_at=data.end_at,
            recurrence_rule=data.recurrence_rule,
            note=data.note,
            metadata_=data.metadata,
        )
        return await self.window_repo.create(window)

    async def get_window(self, window_id: uuid.UUID) -> AvailabilityWindow:
        window = await self.window_repo.get_by_id(window_id)
        if window is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Availability window not found",
            )
        return window

    async def list_windows(
        self,
        resource_id: uuid.UUID,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[AvailabilityWindow]:
        return await self.window_repo.list_for_resource(resource_id, start_at=start_at, end_at=end_at)

    async def update_window(self, window_id: uuid.UUID, data: AvailabilityWindowUpdate) -> AvailabilityWindow:
        window = await self.get_window(window_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return window
        await self.window_repo.update_fields(window_id, **fields)
        await self.session.refresh(window)
        return window

    async def delete_window(self, window_id: uuid.UUID) -> None:
        await self.get_window(window_id)
        await self.window_repo.delete(window_id)

    # ── Assignment CRUD + workflow ────────────────────────────────────

    async def create_assignment(self, data: AssignmentCreate, user_id: str | None = None) -> Assignment:
        await self.get_resource(data.resource_id)
        if data.end_at <= data.start_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_at must be after start_at",
            )
        assignment = Assignment(
            resource_id=data.resource_id,
            project_id=data.project_id,
            task_id=data.task_id,
            work_order_id=data.work_order_id,
            start_at=data.start_at,
            end_at=data.end_at,
            allocation_percent=data.allocation_percent,
            status=data.status,
            cost_rate=data.cost_rate,
            currency=data.currency,
            notes=data.notes,
            created_by=user_id,
            metadata_=data.metadata,
        )
        assignment = await self.assignment_repo.create(assignment)
        return assignment

    async def get_assignment(self, assignment_id: uuid.UUID) -> Assignment:
        assignment = await self.assignment_repo.get_by_id(assignment_id)
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
        return assignment

    async def list_assignments_for_resource(
        self,
        resource_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        assignment_status: str | None = None,
    ) -> tuple[list[Assignment], int]:
        return await self.assignment_repo.list_for_resource(
            resource_id,
            offset=offset,
            limit=limit,
            status=assignment_status,
        )

    async def update_assignment(self, assignment_id: uuid.UUID, data: AssignmentUpdate) -> Assignment:
        assignment = await self.get_assignment(assignment_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return assignment
        # Guard the status FSM: the dedicated confirm/complete/cancel endpoints
        # enforce strict transitions, but the generic PATCH used by the Edit
        # Assignment modal must not become a back door for illegal jumps
        # (e.g. completed -> proposed, cancelled -> confirmed). A self-transition
        # is a no-op and always allowed.
        if "status" in fields:
            target_status = fields["status"]
            if target_status != assignment.status:
                allowed = ASSIGNMENT_STATUS_TRANSITIONS.get(assignment.status, frozenset())
                if target_status not in allowed:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(f"Cannot change assignment status from '{assignment.status}' to '{target_status}'"),
                    )
        # If start_at/end_at change, run conflict check
        new_start = fields.get("start_at", assignment.start_at)
        new_end = fields.get("end_at", assignment.end_at)
        new_alloc = fields.get("allocation_percent", assignment.allocation_percent)
        if new_end <= new_start:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_at must be after start_at",
            )
        # A cancelled/completed assignment consumes no allocation, so a PATCH
        # that lands the row in one of those terminal states must NOT be
        # conflict-checked - otherwise cancelling an (already over-allocated)
        # assignment via the edit modal, which sends status+dates together,
        # is spuriously blocked with a 409.
        new_status = fields.get("status", assignment.status)
        skip_conflict_check = new_status in ("cancelled", "completed")
        # Only re-run the conflict check when the scheduling footprint
        # actually changes. The edit modal always sends start/end/alloc in
        # the payload even when the user only touched notes or status, so
        # keying off "present in fields" spuriously 409'd innocuous edits
        # on an assignment that already overlaps a sibling. Compare against
        # the stored values instead.
        footprint_changed = (
            new_start != assignment.start_at
            or new_end != assignment.end_at
            or new_alloc != assignment.allocation_percent
        )
        if not skip_conflict_check and footprint_changed:
            existing = await self.assignment_repo.assignments_for_resource_in_window(
                assignment.resource_id,
                new_start,
                new_end,
                exclude_id=assignment_id,
            )
            conflicts = detect_conflicts(
                assignment.resource_id,
                new_start,
                new_end,
                new_alloc,
                existing,
                exclude_id=assignment_id,
            )
            if conflicts:
                raise ResourceConflictError("Assignment update would overallocate", conflicts)

        await self.assignment_repo.update_fields(assignment_id, **fields)
        await self.session.refresh(assignment)
        return assignment

    async def delete_assignment(self, assignment_id: uuid.UUID) -> None:
        await self.get_assignment(assignment_id)
        await self.assignment_repo.delete(assignment_id)

    async def propose_assignment(
        self,
        data: AssignmentProposeRequest,
        user_id: str | None = None,
    ) -> Assignment:
        """Create an Assignment with status=proposed after conflict + skill checks.

        Raises:
            ResourceConflictError: if conflicts detected.
            SkillMismatchError: if skill requirements not met.
        """
        resource = await self.get_resource(data.resource_id)
        if data.end_at <= data.start_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_at must be after start_at",
            )
        # Conflict check
        existing = await self.assignment_repo.assignments_for_resource_in_window(
            data.resource_id, data.start_at, data.end_at
        )
        conflicts = detect_conflicts(
            data.resource_id,
            data.start_at,
            data.end_at,
            data.allocation_percent,
            existing,
        )
        if conflicts:
            raise ResourceConflictError(
                f"Resource {resource.code} has conflicting assignments",
                conflicts,
            )

        # Skill check
        if data.required_skills:
            res_skills = await self.resource_skill_repo.list_for_resource(data.resource_id)
            certs = await self.cert_repo.list_for_resource(data.resource_id)
            passes, missing = validate_skill_requirements(
                data.resource_id,
                data.required_skills,
                res_skills,
                certs,
                on_date=data.start_at.date(),
            )
            if not passes:
                raise SkillMismatchError(f"Resource {resource.code} missing required skills", missing)

        # Cost-rate snapshot policy: the assignment freezes whatever the
        # caller supplied AT THIS MOMENT. A *missing* cost_rate (None - only
        # possible when extra fields drift) falls back to the resource
        # default; a *zero* cost_rate (legit for donated kit / loaned staff
        # / pro-bono crews) is honoured exactly as sent. Pre-fix, the
        # ``data.cost_rate or default`` coalesce silently substituted the
        # catalogue default for an explicit Decimal('0'), corrupting the
        # rate-history audit trail.
        explicit_rate = data.cost_rate
        if explicit_rate is None:
            cost_rate_snapshot = resource.default_cost_rate or Decimal("0")
        else:
            cost_rate_snapshot = explicit_rate
        # Currency follows the same rule: empty string means "caller did not
        # specify; inherit from the resource"; a non-empty value (even when
        # exotic) is preserved verbatim.
        if data.currency:
            currency_snapshot = data.currency
        else:
            currency_snapshot = resource.currency or ""
        assignment = Assignment(
            resource_id=data.resource_id,
            project_id=data.project_id,
            task_id=data.task_id,
            work_order_id=data.work_order_id,
            start_at=data.start_at,
            end_at=data.end_at,
            allocation_percent=data.allocation_percent,
            status="proposed",
            cost_rate=cost_rate_snapshot,
            currency=currency_snapshot,
            notes=data.notes,
            created_by=user_id,
            metadata_=data.metadata,
        )
        assignment = await self.assignment_repo.create(assignment)
        logger.info(
            "Assignment proposed: resource=%s start=%s end=%s",
            resource.code,
            data.start_at,
            data.end_at,
        )
        event_bus.publish_detached(
            "resources.assignment.proposed",
            {
                "assignment_id": str(assignment.id),
                "resource_id": str(data.resource_id),
                "project_id": str(data.project_id) if data.project_id else None,
                "start_at": data.start_at.isoformat(),
                "end_at": data.end_at.isoformat(),
                "allocation_percent": data.allocation_percent,
            },
            source_module="resources",
        )
        return assignment

    async def confirm_assignment(self, assignment_id: uuid.UUID) -> Assignment:
        assignment = await self.get_assignment(assignment_id)
        if assignment.status not in ("proposed",):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot confirm assignment in status '{assignment.status}'; "
                    f"only 'proposed' assignments may be confirmed"
                ),
            )
        await self.assignment_repo.update_fields(assignment_id, status="confirmed")
        await self.session.refresh(assignment)
        event_bus.publish_detached(
            "resources.assignment.confirmed",
            {
                "assignment_id": str(assignment_id),
                "resource_id": str(assignment.resource_id),
                "project_id": str(assignment.project_id) if assignment.project_id else None,
            },
            source_module="resources",
        )
        return assignment

    async def complete_assignment(
        self,
        assignment_id: uuid.UUID,
        actual_end: datetime | None = None,
    ) -> Assignment:
        assignment = await self.get_assignment(assignment_id)
        if assignment.status not in ("confirmed", "in_progress"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot complete assignment in status '{assignment.status}'; must be 'confirmed' or 'in_progress'"
                ),
            )
        fields: dict[str, Any] = {"status": "completed"}
        if actual_end is not None:
            # A caller-supplied actual end before the assignment start would
            # produce a negative-length window that corrupts utilization and
            # availability math downstream - reject it at the boundary.
            if actual_end <= assignment.start_at:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="actual_end must be after the assignment start",
                )
            fields["end_at"] = actual_end
        await self.assignment_repo.update_fields(assignment_id, **fields)
        await self.session.refresh(assignment)
        return assignment

    async def cancel_assignment(
        self,
        assignment_id: uuid.UUID,
        reason: str = "",
    ) -> Assignment:
        assignment = await self.get_assignment(assignment_id)
        if assignment.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot cancel a completed assignment",
            )
        # Idempotent: re-cancelling an already-cancelled assignment is a
        # no-op rather than appending a second "CANCELLED:" line to notes
        # every time (which polluted the audit trail on retries).
        if assignment.status == "cancelled":
            return assignment
        notes = assignment.notes or ""
        if reason:
            notes = (notes + f"\nCANCELLED: {reason}").strip()
        await self.assignment_repo.update_fields(assignment_id, status="cancelled", notes=notes)
        await self.session.refresh(assignment)
        return assignment

    # ── ResourceRequest workflow ──────────────────────────────────────

    async def request_resource(
        self,
        data: ResourceRequestCreate,
        user_id: str | None = None,
    ) -> ResourceRequest:
        if data.end_at <= data.start_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_at must be after start_at",
            )
        req = ResourceRequest(
            project_id=data.project_id,
            requested_by=user_id,
            title=data.title,
            description=data.description,
            required_skills=[str(s) for s in data.required_skills],
            start_at=data.start_at,
            end_at=data.end_at,
            quantity=data.quantity,
            priority=data.priority,
            status="open",
            metadata_=data.metadata,
        )
        req = await self.request_repo.create(req)
        event_bus.publish_detached(
            "resources.request.opened",
            {
                "request_id": str(req.id),
                "project_id": str(data.project_id),
                "priority": data.priority,
                "title": data.title,
                "start_at": data.start_at.isoformat(),
                "end_at": data.end_at.isoformat(),
            },
            source_module="resources",
        )
        return req

    async def get_request(self, request_id: uuid.UUID) -> ResourceRequest:
        req = await self.request_repo.get_by_id(request_id)
        if req is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource request not found",
            )
        return req

    async def list_requests(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        request_status: str | None = None,
    ) -> tuple[list[ResourceRequest], int]:
        return await self.request_repo.list_for_project(project_id, offset=offset, limit=limit, status=request_status)

    async def update_request(self, request_id: uuid.UUID, data: ResourceRequestUpdate) -> ResourceRequest:
        req = await self.get_request(request_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if "required_skills" in fields and fields["required_skills"] is not None:
            fields["required_skills"] = [str(s) for s in fields["required_skills"]]
        if not fields:
            return req
        await self.request_repo.update_fields(request_id, **fields)
        await self.session.refresh(req)
        return req

    async def delete_request(self, request_id: uuid.UUID) -> None:
        await self.get_request(request_id)
        await self.request_repo.delete(request_id)

    async def fulfill_request(
        self,
        request_id: uuid.UUID,
        payload: ResourceRequestFulfill,
        user_id: str | None = None,
    ) -> Assignment:
        """Create an Assignment for the request's resource and link them."""
        req = await self.get_request(request_id)
        if req.status != "open":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot fulfill request in status '{req.status}'",
            )

        # Reuse propose_assignment for the validation flow
        propose = AssignmentProposeRequest(
            resource_id=payload.resource_id,
            project_id=req.project_id,
            start_at=req.start_at,
            end_at=req.end_at,
            allocation_percent=payload.allocation_percent,
            required_skills=[uuid.UUID(s) for s in req.required_skills],
            cost_rate=payload.cost_rate,
            currency=payload.currency,
            notes=payload.notes,
        )
        assignment = await self.propose_assignment(propose, user_id=user_id)
        # Auto-confirm fulfilled assignments
        await self.assignment_repo.update_fields(assignment.id, status="confirmed")
        await self.request_repo.update_fields(
            request_id,
            status="fulfilled",
            fulfilled_assignment_id=assignment.id,
        )
        await self.session.refresh(req)
        await self.session.refresh(assignment)
        event_bus.publish_detached(
            "resources.request.fulfilled",
            {
                "request_id": str(request_id),
                "assignment_id": str(assignment.id),
                "resource_id": str(payload.resource_id),
                "project_id": str(req.project_id),
            },
            source_module="resources",
        )
        return assignment

    # ── ResourceLink ───────────────────────────────────────────────────

    async def create_link(self, data: ResourceLinkCreate) -> ResourceLink:
        await self.get_resource(data.primary_resource_id)
        await self.get_resource(data.secondary_resource_id)
        if data.primary_resource_id == data.secondary_resource_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot link a resource to itself",
            )
        link = ResourceLink(
            primary_resource_id=data.primary_resource_id,
            secondary_resource_id=data.secondary_resource_id,
            link_type=data.link_type,
            notes=data.notes,
            metadata_=data.metadata,
        )
        return await self.link_repo.create(link)

    async def get_link(self, link_id: uuid.UUID) -> ResourceLink:
        link = await self.link_repo.get_by_id(link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource link not found",
            )
        return link

    async def list_links_for_resource(self, resource_id: uuid.UUID) -> list[ResourceLink]:
        return await self.link_repo.list_for_resource(resource_id)

    async def update_link(self, link_id: uuid.UUID, data: ResourceLinkUpdate) -> ResourceLink:
        link = await self.get_link(link_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return link
        await self.link_repo.update_fields(link_id, **fields)
        await self.session.refresh(link)
        return link

    async def delete_link(self, link_id: uuid.UUID) -> None:
        await self.get_link(link_id)
        await self.link_repo.delete(link_id)

    # ── Dashboard / Utilization ───────────────────────────────────────

    async def resource_dashboard(self, resource_id: uuid.UUID) -> dict[str, Any]:
        """Aggregate data for a resource dashboard view."""
        resource = await self.get_resource(resource_id)
        now = datetime.now(UTC)
        in_30d = now + timedelta(days=30)
        past_window = now - timedelta(days=30)

        all_assignments, _ = await self.assignment_repo.list_for_resource(resource_id, offset=0, limit=500)
        # "Active" = anything that is happening right now and still needs
        # attention. A *proposed* assignment whose window has already
        # started is the most important thing to show - it is awaiting a
        # confirm/decline decision - yet the old filter only matched
        # confirmed/in_progress, so a live-but-unconfirmed booking fell
        # into a dead zone (not "active", and not "upcoming" because its
        # start is in the past). Include running proposed rows here.
        active = [
            a
            for a in all_assignments
            if a.status in ("proposed", "confirmed", "in_progress")
            and _as_aware(a.start_at) <= now <= _as_aware(a.end_at)
        ]
        upcoming = [a for a in all_assignments if a.status in ("proposed", "confirmed") and _as_aware(a.start_at) > now]
        certs = await self.cert_repo.list_for_resource(resource_id)
        today = now.date()
        cutoff = today + timedelta(days=60)
        expiring = [
            c
            for c in certs
            if c.valid_until and c.status == "valid" and today.isoformat() <= c.valid_until <= cutoff.isoformat()
        ]
        skills = await self.resource_skill_repo.list_for_resource(resource_id)
        util = compute_resource_utilization(resource_id, past_window, now, all_assignments)
        return {
            "resource": resource,
            "active_assignments": active,
            "upcoming_assignments": upcoming[:50],
            "certifications": certs,
            "skills": skills,
            "expiring_certifications_count": len(expiring),
            "utilization_30d": UtilizationResponse(
                resource_id=resource_id,
                period_start=past_window,
                period_end=now,
                utilization_percent=util["utilization_percent"],
                hours_assigned=util["hours_assigned"],
                hours_available=util["hours_available"],
            ),
        }

    # ── Board (dispatcher) ────────────────────────────────────────────

    async def board(
        self,
        start: datetime,
        end: datetime,
        *,
        project_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Flat dispatcher-board: resources + their assignments in [start, end).

        Each assignment is annotated with the human-readable ``project_name`` and
        ``task_name`` so the board UI can render clickable rows instead of bare
        UUIDs. The labels are transient attributes (not persisted); the response
        schema reads them via ``from_attributes``.
        """
        resources, _ = await self.resource_repo.list_all(limit=500, project_id=project_id)
        assignments = await self.assignment_repo.list_in_window(start, end, project_id=project_id)
        await self._annotate_assignment_labels(assignments)
        by_resource: dict[uuid.UUID, list[Assignment]] = {}
        for a in assignments:
            by_resource.setdefault(a.resource_id, []).append(a)
        entries: list[dict[str, Any]] = []
        for r in resources:
            entries.append({"resource": r, "assignments": by_resource.get(r.id, [])})
        return entries

    async def _annotate_assignment_labels(self, assignments: list[Assignment]) -> None:
        """Resolve project/task names for assignments and attach them transiently.

        Two batched lookups (projects + tasks) keep this O(1) round-trips
        regardless of assignment count. Missing references resolve to an empty
        string so the UI falls back to a non-linked label rather than rendering
        a stale UUID.
        """
        project_ids = {a.project_id for a in assignments if a.project_id is not None}
        task_ids = {a.task_id for a in assignments if a.task_id is not None}

        name_by_project: dict[uuid.UUID, str] = {}
        if project_ids:
            from app.modules.projects.models import Project

            rows = (
                await self.session.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
            ).all()
            name_by_project = {pid: pname for (pid, pname) in rows}

        name_by_task: dict[uuid.UUID, str] = {}
        if task_ids:
            from app.modules.tasks.models import Task

            rows = (await self.session.execute(select(Task.id, Task.title).where(Task.id.in_(task_ids)))).all()
            name_by_task = {tid: ttitle for (tid, ttitle) in rows}

        for a in assignments:
            a.project_name = name_by_project.get(a.project_id, "") if a.project_id else ""  # type: ignore[attr-defined]
            a.task_name = name_by_task.get(a.task_id, "") if a.task_id else ""  # type: ignore[attr-defined]

    async def board_conflicts(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """List unresolved conflicts in [start, end)."""
        assignments = await self.assignment_repo.list_in_window(start, end)
        by_resource: dict[uuid.UUID, list[Assignment]] = {}
        for a in assignments:
            if a.status in ("cancelled", "completed"):
                continue
            by_resource.setdefault(a.resource_id, []).append(a)

        out: list[dict[str, Any]] = []
        for rid, asgns in by_resource.items():
            # For each pair, check overlap+over-allocation
            conflicts: list[ConflictDetail] = []
            for i, a in enumerate(asgns):
                others = [x for j, x in enumerate(asgns) if j != i]
                conflicts.extend(
                    detect_conflicts(
                        rid,
                        a.start_at,
                        a.end_at,
                        a.allocation_percent,
                        others,
                        exclude_id=a.id,
                    )
                )
            # De-duplicate by conflicting_assignment_id pair
            seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
            unique_conflicts: list[ConflictDetail] = []
            for c in conflicts:
                if c.conflicting_assignment_id is None:
                    unique_conflicts.append(c)
                    continue
                key = tuple(sorted([c.resource_id, c.conflicting_assignment_id]))  # type: ignore[arg-type]
                if key in seen:
                    continue
                seen.add(key)  # type: ignore[arg-type]
                unique_conflicts.append(c)
            if unique_conflicts:
                resource = await self.resource_repo.get_by_id(rid)
                out.append(
                    {
                        "resource_id": rid,
                        "resource_name": resource.name if resource else "?",
                        "conflicts": unique_conflicts,
                    }
                )
        return out

    async def portfolio_capacity(
        self,
        start: datetime,
        end: datetime,
        *,
        bucket: str = "week",
        max_resources: int = 200,
    ) -> dict[str, Any]:
        """Org-wide resource utilization heatmap across every project.

        Buckets the window into week/month columns. Per resource per bucket it
        sums the ``allocation_percent`` of active assignments overlapping that
        bucket, grouped by project. A bucket is *over-allocated* when the total
        exceeds 100% and *cross-project* when more than one distinct project
        competes for the resource in that bucket - the exact signal portfolio
        leveling exists to resolve. Only resources with at least one assignment
        in the window are returned, conflicts first.
        """
        start = _as_aware(start)
        end = _as_aware(end)
        bucket = bucket if bucket in ("week", "month") else "week"
        buckets = _build_capacity_buckets(start, end, bucket)
        bucket_dicts = [{"index": i, "start": bs, "end": be, "label": label} for (i, bs, be, label) in buckets]
        empty = {
            "start": start,
            "end": end,
            "bucket": bucket,
            "buckets": bucket_dicts,
            "resources": [],
            "total_resources": 0,
            "floating_resources": 0,
            "conflict_resources": 0,
        }
        if end <= start or not buckets:
            return empty

        assignments = await self.assignment_repo.list_in_window(start, end)
        active = [a for a in assignments if a.status not in ("cancelled", "completed")]
        if not active:
            return empty

        # Resolve project names once for the whole payload.
        project_ids = {a.project_id for a in active if a.project_id is not None}
        name_by_project: dict[uuid.UUID, str] = {}
        if project_ids:
            from app.modules.projects.models import Project

            rows = (
                await self.session.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
            ).all()
            name_by_project = {pid: pname for (pid, pname) in rows}

        by_resource: dict[uuid.UUID, list[Assignment]] = {}
        for a in active:
            by_resource.setdefault(a.resource_id, []).append(a)

        rows_out: list[dict[str, Any]] = []
        floating_count = 0
        conflict_count = 0
        for rid, asgns in by_resource.items():
            resource = await self.resource_repo.get_by_id(rid)
            if resource is None:
                continue
            is_floating = resource.home_project_id is None
            if is_floating:
                floating_count += 1

            cells: list[dict[str, Any]] = []
            peak = 0
            has_conflict = False
            for bi, b_start, b_end, _label in buckets:
                # Per-project tally inside this bucket.
                per_project: dict[uuid.UUID | None, int] = {}
                for a in asgns:
                    if _intervals_overlap(_as_aware(a.start_at), _as_aware(a.end_at), b_start, b_end):
                        per_project[a.project_id] = per_project.get(a.project_id, 0) + int(a.allocation_percent or 0)
                if not per_project:
                    continue
                total = sum(per_project.values())
                distinct_projects = {pid for pid in per_project if pid is not None}
                over = total > 100
                cross = len(distinct_projects) > 1
                if over:
                    has_conflict = True
                peak = max(peak, total)
                cells.append(
                    {
                        "bucket_index": bi,
                        "allocation_percent": total,
                        "over_allocated": over,
                        "cross_project": cross,
                        "projects": [
                            {
                                "project_id": pid,
                                "project_name": (
                                    name_by_project.get(pid, "Unknown project") if pid is not None else "Unassigned"
                                ),
                                "allocation_percent": pct,
                            }
                            for pid, pct in sorted(per_project.items(), key=lambda kv: kv[1], reverse=True)
                        ],
                    }
                )
            if not cells:
                continue
            if has_conflict:
                conflict_count += 1
            rows_out.append(
                {
                    "resource_id": rid,
                    "code": resource.code,
                    "name": resource.name,
                    "resource_type": resource.resource_type,
                    "is_floating": is_floating,
                    "peak_allocation_percent": peak,
                    "has_conflict": has_conflict,
                    "cells": cells,
                }
            )

        # Conflicts first, then highest peak, then name - the order a planner reads.
        rows_out.sort(key=lambda r: (not r["has_conflict"], -r["peak_allocation_percent"], r["name"]))
        total_resources = len(rows_out)
        rows_out = rows_out[:max_resources]

        return {
            "start": start,
            "end": end,
            "bucket": bucket,
            "buckets": bucket_dicts,
            "resources": rows_out,
            "total_resources": total_resources,
            "floating_resources": floating_count,
            "conflict_resources": conflict_count,
        }

    async def portfolio_leveling(
        self,
        start: datetime,
        end: datetime,
        *,
        bucket: str = "week",
        project_id: uuid.UUID | None = None,
        max_resources: int = 200,
    ) -> dict[str, Any]:
        """Read-only portfolio resource-leveling grid with overload + suggestions.

        Buckets ``[start, end)`` into week/month columns. Per resource per bucket
        it sums the ``allocation_percent`` of active assignments (proposed /
        confirmed / in_progress) overlapping that bucket. A bucket is
        *over-allocated* only when the resource has a declared
        ``capacity_percent`` AND the bucket total exceeds it; resources without a
        capacity are surfaced as ``capacity_unknown`` and are NEVER flagged
        over-allocated (we never fabricate a ceiling). For each overloaded bucket
        a deterministic leveling suggestion (shift / spread) is attached. No
        booking is moved - the planner confirms each action.

        When ``project_id`` is set the grid is scoped to that project's
        assignments only; otherwise it spans every project (portfolio view).
        """
        start = _as_aware(start)
        end = _as_aware(end)
        bucket = bucket if bucket in ("week", "month") else "week"
        buckets = _build_capacity_buckets(start, end, bucket)
        bucket_dicts = [{"index": i, "start": bs, "end": be, "label": label} for (i, bs, be, label) in buckets]
        empty = {
            "start": start,
            "end": end,
            "bucket": bucket,
            "project_id": project_id,
            "buckets": bucket_dicts,
            "resources": [],
            "total_resources": 0,
            "overloaded_resources": 0,
            "capacity_unknown_resources": 0,
            "total_suggestions": 0,
        }
        if end <= start or not buckets:
            return empty

        assignments = await self.assignment_repo.list_in_window(start, end, project_id=project_id)
        active = [a for a in assignments if a.status in _LEVELING_ACTIVE_STATES]
        if not active:
            return empty

        # Resolve project names once for the whole payload.
        project_ids = {a.project_id for a in active if a.project_id is not None}
        name_by_project: dict[uuid.UUID, str] = {}
        if project_ids:
            from app.modules.projects.models import Project

            rows = (
                await self.session.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
            ).all()
            name_by_project = {pid: pname for (pid, pname) in rows}

        by_resource: dict[uuid.UUID, list[Assignment]] = {}
        for a in active:
            by_resource.setdefault(a.resource_id, []).append(a)

        def _pname(pid: uuid.UUID | None) -> str:
            if pid is None:
                return "Unassigned"
            return name_by_project.get(pid, "Unknown project")

        rows_out: list[dict[str, Any]] = []
        overloaded_count = 0
        capacity_unknown_count = 0
        total_suggestions = 0
        for rid, asgns in by_resource.items():
            resource = await self.resource_repo.get_by_id(rid)
            if resource is None:
                continue
            capacity = resource.capacity_percent
            capacity_unknown = capacity is None
            is_floating = resource.home_project_id is None

            cells: list[dict[str, Any]] = []
            suggestions: list[dict[str, Any]] = []
            peak = 0
            overload_buckets = 0
            for bi, b_start, b_end, _label in buckets:
                bucket_bookings: list[dict[str, Any]] = []
                per_project_projects: set[uuid.UUID] = set()
                for a in asgns:
                    if _intervals_overlap(_as_aware(a.start_at), _as_aware(a.end_at), b_start, b_end):
                        bucket_bookings.append(
                            {
                                "assignment_id": a.id,
                                "project_id": a.project_id,
                                "project_name": _pname(a.project_id),
                                "allocation_percent": int(a.allocation_percent or 0),
                                "status": a.status,
                                "start_at": _as_aware(a.start_at),
                                "end_at": _as_aware(a.end_at),
                            }
                        )
                        if a.project_id is not None:
                            per_project_projects.add(a.project_id)
                if not bucket_bookings:
                    continue
                total = sum(int(b["allocation_percent"]) for b in bucket_bookings)
                peak = max(peak, total)
                # Over-allocation is ONLY meaningful against a known capacity.
                over = (not capacity_unknown) and capacity is not None and total > capacity
                if over:
                    overload_buckets += 1
                    cell_suggestions = build_leveling_suggestions(
                        bi,
                        int(capacity),
                        bucket_bookings,  # type: ignore[arg-type]
                    )
                    suggestions.extend(cell_suggestions)
                cells.append(
                    {
                        "bucket_index": bi,
                        "allocation_percent": total,
                        "capacity_percent": capacity,
                        "over_allocated": over,
                        "capacity_unknown": capacity_unknown,
                        "cross_project": len(per_project_projects) > 1,
                        "bookings": sorted(
                            bucket_bookings,
                            key=lambda b: int(b["allocation_percent"]),
                            reverse=True,
                        ),
                    }
                )
            if not cells:
                continue
            has_overload = overload_buckets > 0
            if has_overload:
                overloaded_count += 1
            if capacity_unknown:
                capacity_unknown_count += 1
            total_suggestions += len(suggestions)
            rows_out.append(
                {
                    "resource_id": rid,
                    "code": resource.code,
                    "name": resource.name,
                    "resource_type": resource.resource_type,
                    "is_floating": is_floating,
                    "capacity_percent": capacity,
                    "capacity_unknown": capacity_unknown,
                    "peak_allocation_percent": peak,
                    "overload_bucket_count": overload_buckets,
                    "has_overload": has_overload,
                    "cells": cells,
                    "suggestions": suggestions,
                }
            )

        # Overloaded first, then most overloaded buckets, then highest peak, then
        # name - the order a planner reads to triage the worst offenders first.
        rows_out.sort(
            key=lambda r: (
                not r["has_overload"],
                -r["overload_bucket_count"],
                -r["peak_allocation_percent"],
                r["name"],
            )
        )
        total_resources = len(rows_out)
        rows_out = rows_out[:max_resources]

        if overloaded_count > 0:
            event_bus.publish_detached(
                "resources.portfolio.overload_detected",
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "bucket": bucket,
                    "project_id": str(project_id) if project_id else None,
                    "overloaded_resources": overloaded_count,
                    "total_suggestions": total_suggestions,
                },
                source_module="resources",
            )

        return {
            "start": start,
            "end": end,
            "bucket": bucket,
            "project_id": project_id,
            "buckets": bucket_dicts,
            "resources": rows_out,
            "total_resources": total_resources,
            "overloaded_resources": overloaded_count,
            "capacity_unknown_resources": capacity_unknown_count,
            "total_suggestions": total_suggestions,
        }

    async def find_candidates(
        self,
        skill_ids: list[uuid.UUID],
        start: datetime,
        end: datetime,
        *,
        exclude_ids: list[uuid.UUID] | None = None,
        limit: int = 50,
    ) -> list[Resource]:
        """Find resources with required skills and no conflicts in [start, end)."""
        return await self.assignment_repo.find_available_resources(
            skill_ids=skill_ids,
            start=start,
            end=end,
            exclude_ids=exclude_ids,
            limit=limit,
        )

    # ── Skill-matrix ranked candidate scoring ─────────────────────────────

    async def rank_candidates(
        self,
        required_skill_ids: list[uuid.UUID],
        start: datetime,
        end: datetime,
        *,
        home_project_id: uuid.UUID | None = None,
        weight_skill: float = 0.6,
        weight_availability: float = 0.3,
        weight_proximity: float = 0.1,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return ranked candidate list scored on skills × availability × proximity.

        For each Resource holding at least one required skill (and not in a
        blocking unavailability window during ``[start, end)``), compute a
        composite score in ``[0.0, 1.0]``:

            score = w_skill   * fraction_of_required_skills_held
                  + w_avail   * (1 - existing_allocation_overlap / 100)
                  + w_prox    * (1 if home_project_id matches resource home, else 0)

        Resources that hold none of the required skills are excluded.
        Resources whose existing allocation already saturates the window are
        kept but scored low so the user can still see them.
        """
        all_resources, _ = await self.resource_repo.list_all(limit=2000)
        out: list[dict[str, Any]] = []
        required_set: set[uuid.UUID] = {uuid.UUID(str(s)) for s in required_skill_ids}

        # Bulk-fetch skills, in-window assignments, and availability windows for
        # the whole active candidate set in three round-trips, then join in
        # Python. The previous per-resource queries inside the loop produced an
        # N+1 explosion (~3 queries × up to 2000 resources).
        active_ids = [res.id for res in all_resources if res.status == "active"]
        skills_by_resource = await self.resource_skill_repo.list_for_resources(active_ids)
        assignments_by_resource = await self.assignment_repo.assignments_for_resources_in_window(active_ids, start, end)
        windows_by_resource = await self.window_repo.list_for_resources(active_ids, start_at=start, end_at=end)

        for res in all_resources:
            if res.status != "active":
                continue
            res_skills = skills_by_resource.get(res.id, [])
            owned_skill_ids = {rs.skill_id for rs in res_skills}
            matched = required_set & owned_skill_ids
            if not matched and required_set:
                continue  # zero overlap - not a candidate
            skill_score = len(matched) / len(required_set) if required_set else 1.0

            # Availability: sum allocation_percent of overlapping non-cancelled
            # assignments in [start, end). Convert to a 0..1 free-fraction.
            existing = assignments_by_resource.get(res.id, [])
            total_alloc = 0
            for a in existing:
                if a.status in ("cancelled", "completed"):
                    continue
                if not _intervals_overlap(start, end, a.start_at, a.end_at):
                    continue
                total_alloc += a.allocation_percent or 0
            free_fraction = max(0.0, min(1.0, (100 - total_alloc) / 100.0))

            # Blocking availability windows (holiday/sick/unavailable).
            # No defensive try/except here: a failing window query is a real
            # fault and must surface, not be silently downgraded to "fully
            # available" - that would rank an out-of-office resource top of
            # the list and let a dispatcher book someone who is on leave.
            blocking = False
            windows = windows_by_resource.get(res.id, [])
            for w in windows:
                if w.window_type in ("unavailable", "holiday", "sick"):
                    if _intervals_overlap(start, end, w.start_at, w.end_at):
                        blocking = True
                        break
            if blocking:
                free_fraction = 0.0

            # Proximity: same home project = 1, else 0.
            proximity = 0.0
            if home_project_id is not None and res.home_project_id == home_project_id:
                proximity = 1.0
            elif home_project_id is None:
                proximity = 1.0  # don't penalise when caller doesn't care

            score = weight_skill * skill_score + weight_availability * free_fraction + weight_proximity * proximity

            out.append(
                {
                    "resource_id": res.id,
                    "code": res.code,
                    "name": res.name,
                    "resource_type": res.resource_type,
                    "home_project_id": res.home_project_id,
                    "matched_skills": [str(s) for s in matched],
                    "missing_skills": [str(s) for s in required_set if s not in owned_skill_ids],
                    "skill_score": round(skill_score, 4),
                    "availability_score": round(free_fraction, 4),
                    "proximity_score": round(proximity, 4),
                    "score": round(score, 4),
                }
            )

        out.sort(key=lambda r: r["score"], reverse=True)
        return out[:limit]

    # ── Certification expiry watcher ──────────────────────────────────────

    async def scan_expiring_certifications(
        self,
        *,
        windows_days: tuple[int, ...] = (60, 30, 14, 7),
    ) -> dict[int, list[Certification]]:
        """Bucket expiring certifications into the requested look-ahead windows.

        For each window N in ``windows_days`` (descending), return certs whose
        ``valid_until`` falls between today and today+N, exclusive of any
        earlier (smaller) bucket - so a cert expiring in 6 days lands only
        in the 7-day bucket, not also in 14/30/60.
        """
        if not windows_days:
            return {}
        sorted_windows = sorted(set(int(w) for w in windows_days if w > 0))
        today = datetime.now(UTC).date()
        out: dict[int, list[Certification]] = {w: [] for w in sorted_windows}
        # Pull the largest window once, then bucket in Python.
        max_window = sorted_windows[-1]
        cutoff = today + timedelta(days=max_window)
        all_expiring = await self.cert_repo.list_expiring(today_iso=today.isoformat(), cutoff_iso=cutoff.isoformat())
        for cert in all_expiring:
            if not cert.valid_until:
                continue
            try:
                vu = date.fromisoformat(cert.valid_until[:10])
            except (ValueError, TypeError):
                continue
            days_left = (vu - today).days
            if days_left < 0:
                continue
            # Smallest matching window
            for w in sorted_windows:
                if days_left <= w:
                    out[w].append(cert)
                    break
        return out

    async def emit_expiry_events(
        self,
        *,
        windows_days: tuple[int, ...] = (60, 30, 14, 7),
    ) -> int:
        """Emit ``resources.cert_expiring`` events bucketed by ``windows_days``.

        Returns the total count of events emitted. Idempotency is the
        subscriber's responsibility - we publish a deterministic ``key`` so
        downstream notification stores can dedupe.
        """
        buckets = await self.scan_expiring_certifications(windows_days=windows_days)
        emitted = 0
        for window_days, certs in buckets.items():
            for cert in certs:
                event_bus.publish_detached(
                    "resources.cert_expiring",
                    {
                        "certification_id": str(cert.id),
                        "resource_id": str(cert.resource_id),
                        "cert_type": cert.cert_type,
                        "valid_until": cert.valid_until,
                        "window_days": window_days,
                        "dedupe_key": f"{cert.id}:{cert.valid_until}:{window_days}",
                    },
                    source_module="resources",
                )
                emitted += 1
        return emitted

    # ── Time-card import ──────────────────────────────────────────────────

    async def import_timecards(
        self,
        rows: list[dict[str, Any]],
        *,
        default_status: str = "completed",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Import time-card rows as completed assignments.

        Each row must contain:
            - resource_code OR resource_id
            - project_id (optional)
            - start_at (ISO string or datetime)
            - end_at (ISO string or datetime)
            - allocation_percent (optional, default 100)
            - cost_rate (optional)
            - currency (optional)
            - notes (optional)

        Rows lacking required fields are reported in ``errors`` with the
        row index. Successfully created assignments are returned in ``created``.
        """
        created: list[uuid.UUID] = []
        errors: list[dict[str, Any]] = []
        for i, row in enumerate(rows):
            try:
                resource = await self._resolve_resource_from_row(row)
            except ValueError as exc:
                errors.append({"row": i, "error": str(exc)})
                continue

            try:
                start_at = _coerce_dt(row.get("start_at"))
                end_at = _coerce_dt(row.get("end_at"))
            except ValueError as exc:
                errors.append({"row": i, "error": f"invalid_datetime:{exc}"})
                continue
            if end_at <= start_at:
                errors.append({"row": i, "error": "end_at_not_after_start_at"})
                continue
            try:
                allocation = int(row.get("allocation_percent") or 100)
                if allocation < 1 or allocation > 100:
                    raise ValueError("must be 1..100")
            except (TypeError, ValueError) as exc:
                errors.append({"row": i, "error": f"invalid_allocation:{exc}"})
                continue

            project_id = row.get("project_id")
            project_uuid: uuid.UUID | None = None
            if project_id:
                try:
                    project_uuid = uuid.UUID(str(project_id))
                except (ValueError, TypeError):
                    errors.append({"row": i, "error": "invalid_project_id"})
                    continue

            cost_rate = Decimal(str(row.get("cost_rate") or resource.default_cost_rate or 0))
            currency = str(row.get("currency") or resource.currency or "")
            assignment = Assignment(
                resource_id=resource.id,
                project_id=project_uuid,
                task_id=None,
                work_order_id=None,
                start_at=start_at,
                end_at=end_at,
                allocation_percent=allocation,
                status=default_status,
                cost_rate=cost_rate,
                currency=currency,
                notes=str(row.get("notes") or "[timecard_import]"),
                created_by=user_id,
                metadata_={"source": "timecard_import", "row_index": i},
            )
            assignment = await self.assignment_repo.create(assignment)
            created.append(assignment.id)

        event_bus.publish_detached(
            "resources.timecards.imported",
            {
                "created_count": len(created),
                "error_count": len(errors),
                "imported_by": user_id,
            },
            source_module="resources",
        )
        return {
            "created": [str(aid) for aid in created],
            "errors": errors,
            "created_count": len(created),
            "error_count": len(errors),
        }

    async def _resolve_resource_from_row(self, row: dict[str, Any]) -> Resource:
        """Resolve a Resource by row's resource_code or resource_id."""
        rid = row.get("resource_id")
        code = row.get("resource_code")
        if rid:
            try:
                res = await self.resource_repo.get_by_id(uuid.UUID(str(rid)))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"invalid_resource_id:{exc}") from exc
            if res is None:
                raise ValueError(f"resource_not_found:{rid}")
            return res
        if code:
            res = await self.resource_repo.get_by_code(str(code))
            if res is None:
                raise ValueError(f"resource_code_not_found:{code}")
            return res
        raise ValueError("missing_resource_identifier")


def _coerce_dt(value: Any) -> datetime:
    """Coerce ``value`` to a tz-aware datetime; raise ValueError on failure."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not_a_datetime")
    try:
        # Tolerate trailing 'Z'
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid_iso:{value}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
