"""Unit tests for the resources module — service + pure helpers.

Scope:
    detect_conflicts, is_resource_available, validate_skill_requirements,
    derive_certification_status, compute_resource_utilization (pure),
    propose / confirm / complete / cancel state transitions,
    fulfill_request linkage, repository CRUD basics, permission registration.
Repositories and event bus are stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.modules.resources.schemas import (
    AssignmentProposeRequest,
    AvailabilityWindowCreate,
    CertificationCreate,
    ResourceCreate,
    ResourceRequestCreate,
    ResourceRequestFulfill,
    ResourceSkillCreate,
    SkillCreate,
)
from app.modules.resources.service import (
    ResourceConflictError,
    ResourcesService,
    SkillMismatchError,
    compute_resource_utilization,
    derive_certification_status,
    detect_conflicts,
    is_resource_available,
    validate_skill_requirements,
)

PROJECT_ID = uuid.uuid4()


# ── Stubs ─────────────────────────────────────────────────────────────────


class _StubSession:
    def __init__(self) -> None:
        self.flushed = False

    async def refresh(self, obj: Any) -> None:
        return None

    async def flush(self) -> None:
        self.flushed = True

    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: None, scalar_one=lambda: 0)

    def add(self, obj: Any) -> None:
        return None

    def expire_all(self) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        return None


class _StubResourceRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.by_code: dict[str, Any] = {}

    async def get_by_id(self, rid: uuid.UUID) -> Any:
        return self.rows.get(rid)

    async def get_by_code(self, code: str) -> Any:
        return self.by_code.get(code)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        resource_type: str | None = None,
        status: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if resource_type:
            rows = [r for r in rows if r.resource_type == resource_type]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def create(self, r: Any) -> Any:
        if getattr(r, "id", None) is None:
            r.id = uuid.uuid4()
        now = datetime.now(UTC)
        r.created_at = now
        r.updated_at = now
        self.rows[r.id] = r
        self.by_code[r.code] = r
        return r

    async def update_fields(self, rid: uuid.UUID, **fields: Any) -> None:
        r = self.rows.get(rid)
        if r:
            for k, v in fields.items():
                setattr(r, k, v)
            r.updated_at = datetime.now(UTC)

    async def delete(self, rid: uuid.UUID) -> None:
        r = self.rows.pop(rid, None)
        if r:
            self.by_code.pop(r.code, None)


class _StubSkillRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.by_code: dict[str, Any] = {}

    async def get_by_id(self, sid: uuid.UUID) -> Any:
        return self.rows.get(sid)

    async def get_by_code(self, code: str) -> Any:
        return self.by_code.get(code)

    async def list_all(
        self, *, offset: int = 0, limit: int = 200, category: str | None = None
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if category:
            rows = [r for r in rows if r.category == category]
        return rows[offset : offset + limit], len(rows)

    async def create(self, s: Any) -> Any:
        if getattr(s, "id", None) is None:
            s.id = uuid.uuid4()
        now = datetime.now(UTC)
        s.created_at = now
        s.updated_at = now
        self.rows[s.id] = s
        self.by_code[s.code] = s
        return s

    async def update_fields(self, sid: uuid.UUID, **fields: Any) -> None:
        s = self.rows.get(sid)
        if s:
            for k, v in fields.items():
                setattr(s, k, v)
            s.updated_at = datetime.now(UTC)

    async def delete(self, sid: uuid.UUID) -> None:
        s = self.rows.pop(sid, None)
        if s:
            self.by_code.pop(s.code, None)


class _StubResourceSkillRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, lid: uuid.UUID) -> Any:
        return self.rows.get(lid)

    async def list_for_resource(self, rid: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.resource_id == rid]

    async def find_pair(self, rid: uuid.UUID, sid: uuid.UUID) -> Any:
        for r in self.rows.values():
            if r.resource_id == rid and r.skill_id == sid:
                return r
        return None

    async def create(self, link: Any) -> Any:
        if getattr(link, "id", None) is None:
            link.id = uuid.uuid4()
        now = datetime.now(UTC)
        link.created_at = now
        link.updated_at = now
        self.rows[link.id] = link
        return link

    async def delete_pair(self, rid: uuid.UUID, sid: uuid.UUID) -> None:
        link = await self.find_pair(rid, sid)
        if link:
            self.rows.pop(link.id, None)


class _StubCertRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, cid: uuid.UUID) -> Any:
        return self.rows.get(cid)

    async def list_for_resource(self, rid: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.resource_id == rid]

    async def list_expiring(self, *, today_iso: str, cutoff_iso: str) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if r.status == "valid" and r.valid_until is not None and today_iso <= r.valid_until <= cutoff_iso
        ]

    async def create(self, c: Any) -> Any:
        if getattr(c, "id", None) is None:
            c.id = uuid.uuid4()
        now = datetime.now(UTC)
        c.created_at = now
        c.updated_at = now
        self.rows[c.id] = c
        return c

    async def update_fields(self, cid: uuid.UUID, **fields: Any) -> None:
        c = self.rows.get(cid)
        if c:
            for k, v in fields.items():
                setattr(c, k, v)
            c.updated_at = datetime.now(UTC)

    async def delete(self, cid: uuid.UUID) -> None:
        self.rows.pop(cid, None)


class _StubWindowRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, wid: uuid.UUID) -> Any:
        return self.rows.get(wid)

    async def list_for_resource(
        self,
        rid: uuid.UUID,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[Any]:
        out = [r for r in self.rows.values() if r.resource_id == rid]
        if start_at is not None:
            out = [r for r in out if r.end_at >= start_at]
        if end_at is not None:
            out = [r for r in out if r.start_at <= end_at]
        return out

    async def create(self, w: Any) -> Any:
        if getattr(w, "id", None) is None:
            w.id = uuid.uuid4()
        now = datetime.now(UTC)
        w.created_at = now
        w.updated_at = now
        self.rows[w.id] = w
        return w

    async def update_fields(self, wid: uuid.UUID, **fields: Any) -> None:
        w = self.rows.get(wid)
        if w:
            for k, v in fields.items():
                setattr(w, k, v)

    async def delete(self, wid: uuid.UUID) -> None:
        self.rows.pop(wid, None)


class _StubAssignmentRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, aid: uuid.UUID) -> Any:
        return self.rows.get(aid)

    async def list_for_resource(
        self,
        rid: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.resource_id == rid]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def list_for_project(
        self,
        pid: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 500,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == pid]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def assignments_for_resource_in_window(
        self,
        rid: uuid.UUID,
        start: datetime,
        end: datetime,
        *,
        exclude_id: uuid.UUID | None = None,
        active_only: bool = True,
    ) -> list[Any]:
        out: list[Any] = []
        for a in self.rows.values():
            if a.resource_id != rid:
                continue
            if exclude_id is not None and a.id == exclude_id:
                continue
            if active_only and a.status in ("cancelled", "completed"):
                continue
            if a.start_at < end and a.end_at > start:
                out.append(a)
        return out

    async def list_in_window(
        self,
        start: datetime,
        end: datetime,
        *,
        project_id: uuid.UUID | None = None,
        resource_ids: list[uuid.UUID] | None = None,
    ) -> list[Any]:
        out = [a for a in self.rows.values() if a.start_at < end and a.end_at > start]
        if project_id is not None:
            out = [a for a in out if a.project_id == project_id]
        if resource_ids is not None:
            out = [a for a in out if a.resource_id in resource_ids]
        return out

    async def create(self, a: Any) -> Any:
        if getattr(a, "id", None) is None:
            a.id = uuid.uuid4()
        now = datetime.now(UTC)
        a.created_at = now
        a.updated_at = now
        self.rows[a.id] = a
        return a

    async def update_fields(self, aid: uuid.UUID, **fields: Any) -> None:
        a = self.rows.get(aid)
        if a:
            for k, v in fields.items():
                setattr(a, k, v)
            a.updated_at = datetime.now(UTC)

    async def delete(self, aid: uuid.UUID) -> None:
        self.rows.pop(aid, None)

    async def find_available_resources(
        self,
        *,
        skill_ids: list[uuid.UUID],
        start: datetime,
        end: datetime,
        exclude_ids: list[uuid.UUID] | None = None,
        limit: int = 100,
    ) -> list[Any]:
        return []


class _StubRequestRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, rid: uuid.UUID) -> Any:
        return self.rows.get(rid)

    async def list_for_project(
        self,
        pid: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == pid]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def create(self, r: Any) -> Any:
        if getattr(r, "id", None) is None:
            r.id = uuid.uuid4()
        now = datetime.now(UTC)
        r.created_at = now
        r.updated_at = now
        self.rows[r.id] = r
        return r

    async def update_fields(self, rid: uuid.UUID, **fields: Any) -> None:
        r = self.rows.get(rid)
        if r:
            for k, v in fields.items():
                setattr(r, k, v)
            r.updated_at = datetime.now(UTC)

    async def delete(self, rid: uuid.UUID) -> None:
        self.rows.pop(rid, None)


class _StubLinkRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, lid: uuid.UUID) -> Any:
        return self.rows.get(lid)

    async def list_for_resource(self, rid: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.primary_resource_id == rid or r.secondary_resource_id == rid]

    async def create(self, link: Any) -> Any:
        if getattr(link, "id", None) is None:
            link.id = uuid.uuid4()
        now = datetime.now(UTC)
        link.created_at = now
        link.updated_at = now
        self.rows[link.id] = link
        return link

    async def update_fields(self, lid: uuid.UUID, **fields: Any) -> None:
        link = self.rows.get(lid)
        if link:
            for k, v in fields.items():
                setattr(link, k, v)

    async def delete(self, lid: uuid.UUID) -> None:
        self.rows.pop(lid, None)


def _make_service() -> ResourcesService:
    svc = ResourcesService.__new__(ResourcesService)
    svc.session = _StubSession()
    svc.resource_repo = _StubResourceRepo()
    svc.skill_repo = _StubSkillRepo()
    svc.resource_skill_repo = _StubResourceSkillRepo()
    svc.cert_repo = _StubCertRepo()
    svc.window_repo = _StubWindowRepo()
    svc.assignment_repo = _StubAssignmentRepo()
    svc.request_repo = _StubRequestRepo()
    svc.link_repo = _StubLinkRepo()
    return svc


def _make_resource(svc: ResourcesService, code: str = "P-001") -> Any:
    """Synchronously prime a resource into the stubbed repo and return it."""
    obj = SimpleNamespace(
        id=uuid.uuid4(),
        code=code,
        name="Test Person",
        resource_type="person",
        home_project_id=None,
        contact_id=None,
        default_cost_rate=Decimal("50"),
        currency="EUR",
        status="active",
        avatar_url=None,
        notes="",
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.resource_repo.rows[obj.id] = obj
    svc.resource_repo.by_code[code] = obj
    return obj


# ── Pure: detect_conflicts ────────────────────────────────────────────────


def test_detect_conflicts_no_overlap() -> None:
    rid = uuid.uuid4()
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
        allocation_percent=100,
        status="confirmed",
    )
    conflicts = detect_conflicts(
        rid,
        datetime(2026, 5, 10, 13, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        100,
        [a],
    )
    assert conflicts == []


def test_detect_conflicts_overlap_overallocation() -> None:
    rid = uuid.uuid4()
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 14, 0, tzinfo=UTC),
        allocation_percent=100,
        status="confirmed",
    )
    conflicts = detect_conflicts(
        rid,
        datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        50,
        [a],
    )
    assert len(conflicts) == 1
    assert conflicts[0].reason == "overallocation"
    assert conflicts[0].total_allocation_percent == 150


def test_detect_conflicts_edge_touch_is_not_overlap() -> None:
    rid = uuid.uuid4()
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
        allocation_percent=100,
        status="confirmed",
    )
    conflicts = detect_conflicts(
        rid,
        datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 16, 0, tzinfo=UTC),
        100,
        [a],
    )
    assert conflicts == []


def test_detect_conflicts_overlap_within_budget() -> None:
    """Two 50% overlapping assignments are fine."""
    rid = uuid.uuid4()
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=50,
        status="confirmed",
    )
    conflicts = detect_conflicts(
        rid,
        datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 15, 0, tzinfo=UTC),
        50,
        [a],
    )
    assert conflicts == []


def test_detect_conflicts_cancelled_ignored() -> None:
    rid = uuid.uuid4()
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="cancelled",
    )
    conflicts = detect_conflicts(
        rid,
        datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 15, 0, tzinfo=UTC),
        100,
        [a],
    )
    assert conflicts == []


def test_detect_conflicts_invalid_window() -> None:
    rid = uuid.uuid4()
    conflicts = detect_conflicts(
        rid,
        datetime(2026, 5, 10, 15, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
        100,
        [],
    )
    assert len(conflicts) == 1
    assert conflicts[0].reason == "invalid_window"


def test_detect_conflicts_cumulative_overallocation() -> None:
    """Two existing 40% bookings + a new 40% = 120% must be flagged even
    though no single existing/new pair on its own exceeds 100%."""
    rid = uuid.uuid4()
    a1 = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=40,
        status="confirmed",
    )
    a2 = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=40,
        status="confirmed",
    )
    conflicts = detect_conflicts(
        rid,
        datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
        40,
        [a1, a2],
    )
    # Both overlapping rows are reported, each carrying the cumulative total.
    assert len(conflicts) == 2
    assert all(c.reason == "overallocation" for c in conflicts)
    assert all(c.total_allocation_percent == 120 for c in conflicts)
    reported = {c.conflicting_assignment_id for c in conflicts}
    assert reported == {a1.id, a2.id}


def test_detect_conflicts_cumulative_within_budget_passes() -> None:
    """Two existing 30% + new 40% = 100% is exactly at budget — no conflict."""
    rid = uuid.uuid4()
    a1 = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=30,
        status="confirmed",
    )
    a2 = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=30,
        status="confirmed",
    )
    conflicts = detect_conflicts(
        rid,
        datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
        40,
        [a1, a2],
    )
    assert conflicts == []


# ── Pure: is_resource_available ──────────────────────────────────────────


def test_is_resource_available_clean() -> None:
    rid = uuid.uuid4()
    assert is_resource_available(
        rid,
        datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        [],
        [],
    )


def test_is_resource_available_blocked_by_holiday() -> None:
    rid = uuid.uuid4()
    win = SimpleNamespace(
        resource_id=rid,
        window_type="holiday",
        start_at=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
    )
    assert not is_resource_available(
        rid,
        datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        [],
        [win],
    )


def test_is_resource_available_partial_allocation_fits() -> None:
    rid = uuid.uuid4()
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=40,
        status="confirmed",
    )
    assert is_resource_available(
        rid,
        datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 15, 0, tzinfo=UTC),
        [a],
        [],
        allocation_percent=50,
    )


def test_is_resource_available_overallocation_blocks() -> None:
    rid = uuid.uuid4()
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=80,
        status="confirmed",
    )
    assert not is_resource_available(
        rid,
        datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 15, 0, tzinfo=UTC),
        [a],
        [],
        allocation_percent=50,
    )


# ── Pure: derive_certification_status ────────────────────────────────────


def test_cert_status_valid() -> None:
    today = date(2026, 5, 12)
    assert derive_certification_status("2027-01-01", False, today) == "valid"


def test_cert_status_expired() -> None:
    today = date(2026, 5, 12)
    assert derive_certification_status("2026-01-01", False, today) == "expired"


def test_cert_status_revoked_overrides_valid_date() -> None:
    today = date(2026, 5, 12)
    assert derive_certification_status("2027-01-01", True, today) == "revoked"


def test_cert_status_no_expiry_assumed_valid() -> None:
    today = date(2026, 5, 12)
    assert derive_certification_status(None, False, today) == "valid"


# ── Pure: validate_skill_requirements ────────────────────────────────────


def test_validate_skill_requirements_all_present() -> None:
    rid = uuid.uuid4()
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    rs = [
        SimpleNamespace(resource_id=rid, skill_id=s1, expires_at=None),
        SimpleNamespace(resource_id=rid, skill_id=s2, expires_at="2099-01-01"),
    ]
    passes, missing = validate_skill_requirements(rid, [s1, s2], rs, [], on_date=date(2026, 5, 12))
    assert passes
    assert missing == []


def test_validate_skill_requirements_missing_skill() -> None:
    rid = uuid.uuid4()
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    rs = [SimpleNamespace(resource_id=rid, skill_id=s1, expires_at=None)]
    passes, missing = validate_skill_requirements(rid, [s1, s2], rs, [], on_date=date(2026, 5, 12))
    assert not passes
    assert any(m.startswith("missing_skill:") for m in missing)


def test_validate_skill_requirements_expired_skill() -> None:
    rid = uuid.uuid4()
    s1 = uuid.uuid4()
    rs = [SimpleNamespace(resource_id=rid, skill_id=s1, expires_at="2025-01-01")]
    passes, missing = validate_skill_requirements(rid, [s1], rs, [], on_date=date(2026, 5, 12))
    assert not passes
    assert any(m.startswith("expired_skill:") for m in missing)


def test_validate_skill_requirements_expired_cert() -> None:
    rid = uuid.uuid4()
    s1 = uuid.uuid4()
    rs = [SimpleNamespace(resource_id=rid, skill_id=s1, expires_at=None)]
    certs = [
        SimpleNamespace(
            resource_id=rid,
            cert_type="Crane Operator",
            valid_until="2025-01-01",
            status="valid",
        )
    ]
    passes, missing = validate_skill_requirements(
        rid,
        [s1],
        rs,
        certs,
        on_date=date(2026, 5, 12),
        skill_to_cert_type={s1: "Crane Operator"},
    )
    assert not passes
    assert any("missing_or_expired_cert" in m for m in missing)


# ── Pure: compute_resource_utilization ───────────────────────────────────


def test_compute_resource_utilization_zero_period_returns_zero() -> None:
    rid = uuid.uuid4()
    now = datetime.now(UTC)
    util = compute_resource_utilization(rid, now, now, [])
    assert util["utilization_percent"] == 0.0
    assert util["hours_assigned"] == 0.0


def test_compute_resource_utilization_full_match() -> None:
    """One full-day, 100% assignment in a 1-day period = 100% utilization."""
    rid = uuid.uuid4()
    start = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=start,
        end_at=end,
        allocation_percent=100,
        status="confirmed",
    )
    util = compute_resource_utilization(rid, start, end, [a])
    assert util["utilization_percent"] == 100.0
    assert util["hours_available"] == 8.0
    assert util["hours_assigned"] == 8.0


def test_compute_resource_utilization_half_allocation() -> None:
    rid = uuid.uuid4()
    start = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=rid,
        start_at=start,
        end_at=end,
        allocation_percent=50,
        status="confirmed",
    )
    util = compute_resource_utilization(rid, start, end, [a])
    assert util["utilization_percent"] == 50.0
    assert util["hours_assigned"] == 4.0


# ── Service: resource CRUD ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_resource_returns_obj() -> None:
    svc = _make_service()
    resource = await svc.create_resource(ResourceCreate(code="P-1", name="Anna", resource_type="person"))
    assert resource.code == "P-1"
    assert resource.id is not None


@pytest.mark.asyncio
async def test_create_resource_duplicate_code() -> None:
    svc = _make_service()
    _make_resource(svc, code="P-1")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.create_resource(ResourceCreate(code="P-1", name="Bob", resource_type="person"))
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_get_resource_not_found() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_resource(uuid.uuid4())
    assert exc_info.value.status_code == 404


# ── Service: assignment workflow ────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_assignment_success() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    with patch("app.modules.resources.service.event_bus.publish_detached"):
        req = AssignmentProposeRequest(
            resource_id=r.id,
            project_id=PROJECT_ID,
            start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
            allocation_percent=100,
            required_skills=[],
        )
        assignment = await svc.propose_assignment(req, user_id="u1")
    assert assignment.status == "proposed"
    assert assignment.resource_id == r.id


@pytest.mark.asyncio
async def test_propose_assignment_conflict_raises() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    # Pre-existing assignment
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        project_id=PROJECT_ID,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="confirmed",
        cost_rate=Decimal("50"),
        currency="EUR",
        notes="",
        task_id=None,
        work_order_id=None,
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[existing.id] = existing
    req = AssignmentProposeRequest(
        resource_id=r.id,
        project_id=PROJECT_ID,
        start_at=datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 14, 0, tzinfo=UTC),
        allocation_percent=50,
        required_skills=[],
    )
    with pytest.raises(ResourceConflictError):
        await svc.propose_assignment(req, user_id="u1")


@pytest.mark.asyncio
async def test_propose_assignment_skill_mismatch_raises() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    missing_skill_id = uuid.uuid4()
    req = AssignmentProposeRequest(
        resource_id=r.id,
        project_id=PROJECT_ID,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        required_skills=[missing_skill_id],
    )
    with pytest.raises(SkillMismatchError):
        await svc.propose_assignment(req, user_id="u1")


@pytest.mark.asyncio
async def test_confirm_assignment_proposed_to_confirmed() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    with patch("app.modules.resources.service.event_bus.publish_detached"):
        req = AssignmentProposeRequest(
            resource_id=r.id,
            project_id=PROJECT_ID,
            start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
            allocation_percent=100,
            required_skills=[],
        )
        a = await svc.propose_assignment(req, user_id="u1")
        confirmed = await svc.confirm_assignment(a.id)
    assert confirmed.status == "confirmed"


@pytest.mark.asyncio
async def test_confirm_assignment_invalid_transition() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="completed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[a.id] = a
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.confirm_assignment(a.id)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_complete_assignment_confirmed_to_completed() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="confirmed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[a.id] = a
    completed = await svc.complete_assignment(a.id)
    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_complete_assignment_invalid_transition() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="proposed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[a.id] = a
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.complete_assignment(a.id)


@pytest.mark.asyncio
async def test_cancel_assignment_appends_reason_to_notes() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="confirmed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="initial",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[a.id] = a
    cancelled = await svc.cancel_assignment(a.id, reason="weather")
    assert cancelled.status == "cancelled"
    assert "weather" in cancelled.notes


@pytest.mark.asyncio
async def test_cancel_assignment_completed_rejected() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="completed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[a.id] = a
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.cancel_assignment(a.id)


@pytest.mark.asyncio
async def test_cancel_assignment_already_cancelled_is_idempotent() -> None:
    """Re-cancelling does not append a second CANCELLED line to notes."""
    svc = _make_service()
    r = _make_resource(svc)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="cancelled",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="initial\nCANCELLED: weather",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[a.id] = a
    out = await svc.cancel_assignment(a.id, reason="weather again")
    assert out.status == "cancelled"
    # Notes untouched — no second CANCELLED line appended.
    assert out.notes.count("CANCELLED:") == 1
    assert "weather again" not in out.notes


@pytest.mark.asyncio
async def test_complete_assignment_rejects_actual_end_before_start() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="confirmed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[a.id] = a
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.complete_assignment(a.id, actual_end=datetime(2026, 5, 10, 6, 0, tzinfo=UTC))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_assignment_to_cancelled_skips_conflict_check() -> None:
    """Cancelling via PATCH (status+dates sent together by the edit modal)
    must not be blocked by an over-allocation conflict against siblings."""
    svc = _make_service()
    r = _make_resource(svc)
    from app.modules.resources.schemas import AssignmentUpdate

    start = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
    end = datetime(2026, 5, 10, 17, 0, tzinfo=UTC)
    target = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=start,
        end_at=end,
        allocation_percent=100,
        status="confirmed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    sibling = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=start,
        end_at=end,
        allocation_percent=100,
        status="confirmed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[target.id] = target
    svc.assignment_repo.rows[sibling.id] = sibling
    updated = await svc.update_assignment(
        target.id,
        AssignmentUpdate(
            status="cancelled",
            start_at=start,
            end_at=end,
            allocation_percent=100,
        ),
    )
    assert updated.status == "cancelled"


@pytest.mark.asyncio
async def test_update_assignment_rejects_illegal_status_jump() -> None:
    """The generic PATCH must honour the same FSM as confirm/complete/cancel:
    a terminal 'completed' assignment cannot be PATCHed back to 'proposed'."""
    from fastapi import HTTPException

    svc = _make_service()
    r = _make_resource(svc)
    from app.modules.resources.schemas import AssignmentUpdate

    start = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
    end = datetime(2026, 5, 10, 17, 0, tzinfo=UTC)
    target = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=start,
        end_at=end,
        allocation_percent=100,
        status="completed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[target.id] = target
    with pytest.raises(HTTPException) as exc_info:
        await svc.update_assignment(target.id, AssignmentUpdate(status="proposed"))
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_assignment_allows_legal_status_transition() -> None:
    """A legal transition (confirmed -> in_progress) via PATCH is accepted."""
    svc = _make_service()
    r = _make_resource(svc)
    from app.modules.resources.schemas import AssignmentUpdate

    start = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
    end = datetime(2026, 5, 10, 17, 0, tzinfo=UTC)
    target = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=start,
        end_at=end,
        allocation_percent=100,
        status="confirmed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="EUR",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[target.id] = target
    updated = await svc.update_assignment(target.id, AssignmentUpdate(status="in_progress"))
    assert updated.status == "in_progress"


# ── Service: skill / cert attach ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_skill_and_attach() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    skill = await svc.create_skill(SkillCreate(code="trade.carpentry", name="Carpentry"))
    link = await svc.attach_skill(
        r.id,
        ResourceSkillCreate(skill_id=skill.id, level="expert"),
    )
    assert link.resource_id == r.id
    assert link.skill_id == skill.id
    assert link.level == "expert"


@pytest.mark.asyncio
async def test_attach_skill_idempotent_updates_level() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    skill = await svc.create_skill(SkillCreate(code="trade.x", name="X"))
    await svc.attach_skill(r.id, ResourceSkillCreate(skill_id=skill.id, level="basic"))
    second = await svc.attach_skill(r.id, ResourceSkillCreate(skill_id=skill.id, level="expert"))
    assert second.level == "expert"


@pytest.mark.asyncio
async def test_create_certification_derives_status() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    cert = await svc.create_certification(
        CertificationCreate(
            resource_id=r.id,
            cert_type="Crane Operator",
            valid_until="2099-01-01",
        )
    )
    assert cert.status == "valid"


@pytest.mark.asyncio
async def test_create_certification_expired_status() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    cert = await svc.create_certification(
        CertificationCreate(
            resource_id=r.id,
            cert_type="Crane Operator",
            valid_until="2000-01-01",
        )
    )
    assert cert.status == "expired"


@pytest.mark.asyncio
async def test_list_expiring_certifications_filters_window() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    soon = (datetime.now(UTC).date() + timedelta(days=10)).isoformat()
    far = (datetime.now(UTC).date() + timedelta(days=400)).isoformat()
    await svc.create_certification(CertificationCreate(resource_id=r.id, cert_type="A", valid_until=soon))
    await svc.create_certification(CertificationCreate(resource_id=r.id, cert_type="B", valid_until=far))
    expiring = await svc.list_expiring_certifications(days=60)
    assert len(expiring) == 1
    assert expiring[0].cert_type == "A"


# ── Service: availability windows ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_window_validates_end_after_start() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.create_window(
            AvailabilityWindowCreate(
                resource_id=r.id,
                start_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
                end_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            )
        )


@pytest.mark.asyncio
async def test_create_window_success() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    w = await svc.create_window(
        AvailabilityWindowCreate(
            resource_id=r.id,
            window_type="holiday",
            start_at=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
        )
    )
    assert w.window_type == "holiday"


# ── Service: request workflow ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_resource_emits_event() -> None:
    svc = _make_service()
    with patch("app.modules.resources.service.event_bus.publish_detached") as pub:
        req = await svc.request_resource(
            ResourceRequestCreate(
                project_id=PROJECT_ID,
                title="Need crane",
                start_at=datetime(2026, 5, 15, 8, 0, tzinfo=UTC),
                end_at=datetime(2026, 5, 16, 8, 0, tzinfo=UTC),
            ),
            user_id="u1",
        )
    assert req.status == "open"
    pub.assert_called_once()
    assert pub.call_args.args[0] == "resources.request.opened"


@pytest.mark.asyncio
async def test_fulfill_request_links_assignment() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    with patch("app.modules.resources.service.event_bus.publish_detached"):
        req = await svc.request_resource(
            ResourceRequestCreate(
                project_id=PROJECT_ID,
                title="Need carpenter",
                start_at=datetime(2026, 5, 15, 8, 0, tzinfo=UTC),
                end_at=datetime(2026, 5, 16, 8, 0, tzinfo=UTC),
            ),
            user_id="u1",
        )
        assignment = await svc.fulfill_request(
            req.id,
            ResourceRequestFulfill(resource_id=r.id),
            user_id="u1",
        )
    # Reload the request from the stub repo
    updated = await svc.get_request(req.id)
    assert updated.status == "fulfilled"
    assert updated.fulfilled_assignment_id == assignment.id
    assert assignment.status == "confirmed"


@pytest.mark.asyncio
async def test_fulfill_request_double_fulfill_rejected() -> None:
    svc = _make_service()
    r = _make_resource(svc)
    with patch("app.modules.resources.service.event_bus.publish_detached"):
        req = await svc.request_resource(
            ResourceRequestCreate(
                project_id=PROJECT_ID,
                title="Need carpenter",
                start_at=datetime(2026, 5, 15, 8, 0, tzinfo=UTC),
                end_at=datetime(2026, 5, 16, 8, 0, tzinfo=UTC),
            ),
            user_id="u1",
        )
        await svc.fulfill_request(
            req.id,
            ResourceRequestFulfill(resource_id=r.id),
            user_id="u1",
        )
        # Second fulfill should fail
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await svc.fulfill_request(
                req.id,
                ResourceRequestFulfill(resource_id=r.id),
                user_id="u1",
            )


# ── Permissions ──────────────────────────────────────────────────────────


def test_permissions_registered() -> None:
    """All eight resources.* permissions land in the registry on import."""
    from app.core.permissions import permission_registry
    from app.modules.resources.permissions import register_resources_permissions

    register_resources_permissions()
    modules = permission_registry.list_modules()
    perms = set(modules.get("resources", []))
    expected = {
        "resources.read",
        "resources.create",
        "resources.update",
        "resources.delete",
        "resources.assign",
        "resources.confirm_assignment",
        "resources.request",
        "resources.fulfill_request",
    }
    assert expected.issubset(perms)


# ── Repository CRUD basics (round-trip on stub) ──────────────────────────


@pytest.mark.asyncio
async def test_resource_repo_crud_roundtrip() -> None:
    svc = _make_service()
    r = await svc.create_resource(ResourceCreate(code="P-XYZ", name="Zed", resource_type="person"))
    fetched = await svc.get_resource(r.id)
    assert fetched.code == "P-XYZ"
    await svc.delete_resource(r.id)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.get_resource(r.id)


@pytest.mark.asyncio
async def test_skill_repo_crud_roundtrip() -> None:
    svc = _make_service()
    s = await svc.create_skill(SkillCreate(code="trade.q", name="Q"))
    fetched = await svc.get_skill(s.id)
    assert fetched.code == "trade.q"
    await svc.delete_skill(s.id)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.get_skill(s.id)


# ── New (Wave-5): skill-matrix ranked candidates ────────────────────────


@pytest.mark.asyncio
async def test_rank_candidates_excludes_no_skill_match() -> None:
    """A resource with zero of the required skills must not appear."""
    svc = _make_service()
    skill_a = uuid.uuid4()
    # Two resources, only first has the skill
    r1 = _make_resource(svc, "RA")
    r2 = _make_resource(svc, "RB")
    svc.resource_skill_repo.rows[uuid.uuid4()] = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r1.id,
        skill_id=skill_a,
        level="competent",
        expires_at=None,
    )
    start = datetime(2026, 5, 20, 8, 0, tzinfo=UTC)
    end = datetime(2026, 5, 20, 17, 0, tzinfo=UTC)
    out = await svc.rank_candidates([skill_a], start, end)
    ids = {row["resource_id"] for row in out}
    assert r1.id in ids
    assert r2.id not in ids
    # Skill match should yield score 1.0 on the skill component
    assert out[0]["skill_score"] == 1.0


@pytest.mark.asyncio
async def test_rank_candidates_penalises_overlapping_allocation() -> None:
    """Already-busy resource scores lower on availability."""
    svc = _make_service()
    skill = uuid.uuid4()
    r1 = _make_resource(svc, "FREE")
    r2 = _make_resource(svc, "BUSY")
    for r in (r1, r2):
        svc.resource_skill_repo.rows[uuid.uuid4()] = SimpleNamespace(
            id=uuid.uuid4(),
            resource_id=r.id,
            skill_id=skill,
            level="competent",
            expires_at=None,
        )
    # r2 already 100% allocated in the window
    start = datetime(2026, 5, 20, 8, 0, tzinfo=UTC)
    end = datetime(2026, 5, 20, 17, 0, tzinfo=UTC)
    svc.assignment_repo.rows[uuid.uuid4()] = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r2.id,
        project_id=None,
        start_at=start,
        end_at=end,
        allocation_percent=100,
        status="confirmed",
    )
    out = await svc.rank_candidates([skill], start, end)
    free_row = next(r for r in out if r["resource_id"] == r1.id)
    busy_row = next(r for r in out if r["resource_id"] == r2.id)
    assert free_row["availability_score"] == 1.0
    assert busy_row["availability_score"] == 0.0
    assert free_row["score"] > busy_row["score"]


# ── New (Wave-5): cert expiry buckets ───────────────────────────────────


@pytest.mark.asyncio
async def test_scan_expiring_buckets_smallest_window_first() -> None:
    """A cert expiring in 5 days lands only in the 7-day bucket."""
    svc = _make_service()
    today = datetime.now(UTC).date()
    cert = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        cert_type="WORKING_AT_HEIGHT",
        valid_until=(today + timedelta(days=5)).isoformat(),
        status="valid",
        cert_number=None,
        issued_by=None,
        issue_date=None,
        document_url=None,
        notes="",
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.cert_repo.rows[cert.id] = cert
    buckets = await svc.scan_expiring_certifications(windows_days=(60, 30, 14, 7))
    assert buckets[7] == [cert]
    assert buckets[14] == []
    assert buckets[30] == []
    assert buckets[60] == []


@pytest.mark.asyncio
async def test_emit_expiry_events_publishes_per_cert() -> None:
    svc = _make_service()
    today = datetime.now(UTC).date()
    cert = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        cert_type="CSCS",
        valid_until=(today + timedelta(days=14)).isoformat(),
        status="valid",
        cert_number=None,
        issued_by=None,
        issue_date=None,
        document_url=None,
        notes="",
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.cert_repo.rows[cert.id] = cert
    with patch("app.modules.resources.service.event_bus.publish_detached") as p:
        count = await svc.emit_expiry_events(windows_days=(60, 30, 14, 7))
    assert count == 1
    assert p.call_count == 1
    name, kwargs = p.call_args[0][0], p.call_args[1] if p.call_args[1] else p.call_args[0][1]
    assert "cert_expiring" in name


# ── New (Wave-5): time-card import ──────────────────────────────────────


@pytest.mark.asyncio
async def test_import_timecards_creates_assignments() -> None:
    svc = _make_service()
    r = _make_resource(svc, "T-001")
    rows = [
        {
            "resource_code": "T-001",
            "start_at": "2026-05-20T08:00:00+00:00",
            "end_at": "2026-05-20T17:00:00+00:00",
            "allocation_percent": 100,
            "notes": "Concrete pour",
        },
        {
            "resource_code": "T-001",
            "start_at": "2026-05-21T08:00:00+00:00",
            "end_at": "2026-05-21T17:00:00+00:00",
            "allocation_percent": 50,
        },
    ]
    result = await svc.import_timecards(rows, user_id="boss")
    assert result["created_count"] == 2
    assert result["error_count"] == 0
    # Both assignments tied to the resource, status=completed
    for aid_str in result["created"]:
        a = svc.assignment_repo.rows[uuid.UUID(aid_str)]
        assert a.resource_id == r.id
        assert a.status == "completed"
        assert a.metadata_["source"] == "timecard_import"


@pytest.mark.asyncio
async def test_import_timecards_reports_invalid_rows() -> None:
    svc = _make_service()
    _make_resource(svc, "T-002")
    rows = [
        # Valid
        {
            "resource_code": "T-002",
            "start_at": "2026-05-20T08:00:00+00:00",
            "end_at": "2026-05-20T17:00:00+00:00",
        },
        # Unknown resource
        {
            "resource_code": "T-MISSING",
            "start_at": "2026-05-20T08:00:00+00:00",
            "end_at": "2026-05-20T17:00:00+00:00",
        },
        # end_at <= start_at
        {
            "resource_code": "T-002",
            "start_at": "2026-05-21T08:00:00+00:00",
            "end_at": "2026-05-21T08:00:00+00:00",
        },
        # No resource identifier
        {
            "start_at": "2026-05-21T08:00:00+00:00",
            "end_at": "2026-05-21T17:00:00+00:00",
        },
    ]
    result = await svc.import_timecards(rows)
    assert result["created_count"] == 1
    assert result["error_count"] == 3
    # Error rows preserve the row index
    error_indexes = {e["row"] for e in result["errors"]}
    assert error_indexes == {1, 2, 3}


# ── Regression: dashboard surfaces a *running proposed* assignment ───────


@pytest.mark.asyncio
async def test_dashboard_includes_running_proposed_assignment() -> None:
    """A proposed assignment whose window is live right now used to fall
    into a dead zone — not "active" (status filter excluded proposed) and
    not "upcoming" (start_at is in the past) — so the drawer could never
    show its Confirm/Decline buttons. It must now appear under active.
    """
    svc = _make_service()
    r = _make_resource(svc)
    now = datetime.now(UTC)
    running_proposed = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        start_at=now - timedelta(hours=2),
        end_at=now + timedelta(hours=6),
        allocation_percent=100,
        status="proposed",
        cost_rate=Decimal("0"),
        currency="",
        notes="",
        created_by=None,
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    svc.assignment_repo.rows[running_proposed.id] = running_proposed
    payload = await svc.resource_dashboard(r.id)
    active_ids = {a.id for a in payload["active_assignments"]}
    upcoming_ids = {a.id for a in payload["upcoming_assignments"]}
    assert running_proposed.id in active_ids
    assert running_proposed.id not in upcoming_ids


@pytest.mark.asyncio
async def test_dashboard_future_proposed_still_upcoming() -> None:
    """A proposed assignment that has not started yet stays in upcoming."""
    svc = _make_service()
    r = _make_resource(svc)
    now = datetime.now(UTC)
    future = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        start_at=now + timedelta(days=3),
        end_at=now + timedelta(days=4),
        allocation_percent=100,
        status="proposed",
        cost_rate=Decimal("0"),
        currency="",
        notes="",
        created_by=None,
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    svc.assignment_repo.rows[future.id] = future
    payload = await svc.resource_dashboard(r.id)
    assert future.id in {a.id for a in payload["upcoming_assignments"]}
    assert future.id not in {a.id for a in payload["active_assignments"]}


# ── Regression: notes-only PATCH on an overlapping row is not 409'd ──────


@pytest.mark.asyncio
async def test_update_assignment_notes_only_skips_conflict_check() -> None:
    """Editing only the notes of an assignment that already overlaps a
    sibling at 100% must succeed. The edit modal always resends
    start/end/alloc, so the old "key present in payload" trigger
    spuriously blocked the save with a 409.
    """
    svc = _make_service()
    r = _make_resource(svc)
    from app.modules.resources.schemas import AssignmentUpdate

    start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    end = datetime(2026, 6, 1, 17, 0, tzinfo=UTC)
    common = {
        "resource_id": r.id,
        "start_at": start,
        "end_at": end,
        "allocation_percent": 100,
        "status": "confirmed",
        "project_id": PROJECT_ID,
        "task_id": None,
        "work_order_id": None,
        "cost_rate": Decimal("0"),
        "currency": "",
        "notes": "",
        "created_by": None,
        "metadata_": {},
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    target = SimpleNamespace(id=uuid.uuid4(), **common)
    sibling = SimpleNamespace(id=uuid.uuid4(), **common)
    svc.assignment_repo.rows[target.id] = target
    svc.assignment_repo.rows[sibling.id] = sibling

    updated = await svc.update_assignment(
        target.id,
        AssignmentUpdate(
            notes="just a note tweak",
            start_at=start,
            end_at=end,
            allocation_percent=100,
        ),
    )
    assert updated.notes == "just a note tweak"


@pytest.mark.asyncio
async def test_update_assignment_real_reschedule_still_conflict_checked() -> None:
    """Genuinely moving an assignment so it overlaps a 100% sibling must
    still raise — the fix must not weaken over-allocation protection.
    """
    svc = _make_service()
    r = _make_resource(svc)
    from app.modules.resources.schemas import AssignmentUpdate

    sibling = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 6, 2, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="confirmed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    target = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=r.id,
        start_at=datetime(2026, 6, 5, 8, 0, tzinfo=UTC),
        end_at=datetime(2026, 6, 5, 17, 0, tzinfo=UTC),
        allocation_percent=100,
        status="confirmed",
        project_id=PROJECT_ID,
        task_id=None,
        work_order_id=None,
        cost_rate=Decimal("0"),
        currency="",
        notes="",
        created_by=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.assignment_repo.rows[sibling.id] = sibling
    svc.assignment_repo.rows[target.id] = target

    with pytest.raises(ResourceConflictError):
        await svc.update_assignment(
            target.id,
            AssignmentUpdate(
                start_at=datetime(2026, 6, 2, 9, 0, tzinfo=UTC),
                end_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
            ),
        )


# ── Coverage: find_candidates delegates to the repo matcher ─────────────


@pytest.mark.asyncio
async def test_find_candidates_delegates_to_repository() -> None:
    """find_candidates was previously uncovered. It must forward its
    arguments to the repository's availability matcher and return its
    result verbatim.
    """
    svc = _make_service()
    skill = uuid.uuid4()
    sentinel = _make_resource(svc, "CAND-1")
    captured: dict[str, Any] = {}

    async def _fake(
        *,
        skill_ids: list[uuid.UUID],
        start: datetime,
        end: datetime,
        exclude_ids: list[uuid.UUID] | None = None,
        limit: int = 100,
    ) -> list[Any]:
        captured.update(
            skill_ids=skill_ids,
            start=start,
            end=end,
            exclude_ids=exclude_ids,
            limit=limit,
        )
        return [sentinel]

    svc.assignment_repo.find_available_resources = _fake  # type: ignore[assignment]
    start = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    out = await svc.find_candidates([skill], start, end, exclude_ids=[sentinel.id], limit=5)
    assert out == [sentinel]
    assert captured["skill_ids"] == [skill]
    assert captured["start"] == start
    assert captured["end"] == end
    assert captured["exclude_ids"] == [sentinel.id]
    assert captured["limit"] == 5


# ── propose_assignment cost_rate snapshot ─────────────────────────────────


@pytest.mark.asyncio
async def test_propose_assignment_explicit_zero_cost_rate_is_preserved() -> None:
    """An intentional ``cost_rate=0`` must NOT be silently overwritten by
    the resource's default. Pre-fix, ``data.cost_rate or default`` treated
    a real ``Decimal('0')`` as falsy and substituted the catalogue default,
    quietly inflating costed assignments for assets whose marginal cost is
    legitimately zero (donated equipment, internal staff loaned at no
    charge, etc.). This is a rate-history correctness bug — once frozen,
    the value should be exactly what the caller supplied.
    """
    svc = _make_service()
    # Resource has a non-zero catalogue rate that must NOT bleed through.
    r = _make_resource(svc)  # default_cost_rate=Decimal("50"), currency="EUR"
    with patch("app.modules.resources.service.event_bus.publish_detached"):
        req = AssignmentProposeRequest(
            resource_id=r.id,
            project_id=PROJECT_ID,
            start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
            allocation_percent=100,
            required_skills=[],
            cost_rate=Decimal("0"),
            currency="EUR",
        )
        assignment = await svc.propose_assignment(req, user_id="u1")
    assert assignment.cost_rate == Decimal("0"), (
        f"explicit zero cost_rate was overwritten with {assignment.cost_rate!r} — "
        f"the resource catalogue default leaked through `or`-coalesce"
    )


# ── board() surfaces project / task labels for clickable dispatcher rows ────


class _NamingSession(_StubSession):
    """Session stub whose execute() returns id->name rows for the label join."""

    def __init__(self, names: dict[uuid.UUID, str]) -> None:
        super().__init__()
        self._names = names

    async def execute(self, stmt: Any) -> Any:  # noqa: ARG002 - stmt not inspected
        rows = list(self._names.items())
        return SimpleNamespace(all=lambda: rows)


@pytest.mark.asyncio
async def test_board_annotates_project_and_task_labels() -> None:
    """The dispatcher board must attach human-readable project_name / task_name
    to each assignment so the UI renders clickable rows instead of bare UUIDs.
    """
    svc = _make_service()
    r = _make_resource(svc)
    pid = uuid.uuid4()
    tid = uuid.uuid4()
    await svc.assignment_repo.create(
        SimpleNamespace(
            id=uuid.uuid4(),
            resource_id=r.id,
            project_id=pid,
            task_id=tid,
            work_order_id=None,
            start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
            allocation_percent=100,
            status="confirmed",
            cost_rate=Decimal("0"),
            currency="EUR",
            notes="",
            created_by=None,
            metadata_={},
        )
    )
    svc.session = _NamingSession({pid: "Riverside Tower", tid: "Pour slab L3"})

    entries = await svc.board(
        datetime(2026, 5, 1, tzinfo=UTC),
        datetime(2026, 6, 1, tzinfo=UTC),
    )
    assignments = [a for e in entries for a in e["assignments"]]
    assert len(assignments) == 1
    a = assignments[0]
    assert a.project_name == "Riverside Tower"
    assert a.task_name == "Pour slab L3"


@pytest.mark.asyncio
async def test_board_labels_blank_when_unassigned() -> None:
    """Assignments with no project/task get empty labels (no DB round-trip),
    so the UI falls back to a non-linked 'Unassigned' cell rather than a UUID.
    """
    svc = _make_service()
    r = _make_resource(svc)
    await svc.assignment_repo.create(
        SimpleNamespace(
            id=uuid.uuid4(),
            resource_id=r.id,
            project_id=None,
            task_id=None,
            work_order_id=None,
            start_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 10, 17, 0, tzinfo=UTC),
            allocation_percent=100,
            status="confirmed",
            cost_rate=Decimal("0"),
            currency="EUR",
            notes="",
            created_by=None,
            metadata_={},
        )
    )
    entries = await svc.board(
        datetime(2026, 5, 1, tzinfo=UTC),
        datetime(2026, 6, 1, tzinfo=UTC),
    )
    a = next(a for e in entries for a in e["assignments"])
    assert a.project_name == ""
    assert a.task_name == ""
