"""Unit tests for the daily-diary module.

Coverage:
    * Pure helpers: payload determinism, hashing, completeness,
      auto-populate mapping, photo timeline, before/after pairing,
      immutability validation, ``is_diary_signed``.
    * Service-level state transitions (close → sign → archive) plus
      invalid-direction guards.
    * Event emission on state transitions and asset attachments.
    * Repository CRUD basics through service stubs.
    * Permission registration.

Repositories and event_bus are stubbed; the real SQLAlchemy session
is not required for any of these tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.modules.daily_diary.schemas import (
    DailyDiaryCreate,
    DiaryEntryCreate,
    DiaryPhotoCreate,
    DroneSurveyCreate,
    RealityCaptureCreate,
    WeatherRecordCreate,
)
from app.modules.daily_diary.service import (
    DailyDiaryService,
    auto_populate_entries_from_module_events,
    compute_before_after,
    compute_content_sha256,
    compute_diary_completeness,
    compute_immutable_payload,
    compute_photo_timeline,
    is_diary_signed,
    validate_diary_immutability,
)

# ── Stubs ────────────────────────────────────────────────────────────────


PROJECT_ID = uuid.uuid4()


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalars=lambda: SimpleNamespace(all=lambda: []),
        )


class _BaseStubRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.deleted: list[uuid.UUID] = []

    async def create(self, obj: Any) -> Any:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = now
        obj.updated_at = now
        self.rows[obj.id] = obj
        return obj

    async def get_by_id(self, obj_id: uuid.UUID) -> Any:
        return self.rows.get(obj_id)

    async def update_fields(self, obj_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(obj_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)
        obj.updated_at = datetime.now(UTC)

    async def delete(self, obj_id: uuid.UUID) -> None:
        self.rows.pop(obj_id, None)
        self.deleted.append(obj_id)


class _StubDiaryRepo(_BaseStubRepo):
    async def get_by_date_and_project(
        self,
        project_id: uuid.UUID,
        diary_date: str,
    ) -> Any:
        for row in self.rows.values():
            if row.project_id == project_id and row.diary_date == diary_date:
                return row
        return None

    async def list_by_project_in_range(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id and (status is None or r.status == status)]
        return rows[offset : offset + limit], len(rows)


class _StubEntryRepo(_BaseStubRepo):
    async def list_for_diary(
        self,
        diary_id: uuid.UUID,
        *,
        entry_type: str | None = None,
    ) -> list[Any]:
        rows = [r for r in self.rows.values() if r.diary_id == diary_id]
        if entry_type is not None:
            rows = [r for r in rows if r.entry_type == entry_type]
        return rows

    async def entries_by_source_module(
        self,
        diary_id: uuid.UUID,
        source_module: str,
    ) -> list[Any]:
        return [r for r in self.rows.values() if r.diary_id == diary_id and r.source_module == source_module]

    async def bulk_create(self, entries: list[Any]) -> list[Any]:
        for e in entries:
            await self.create(e)
        return entries


class _StubPhotoRepo(_BaseStubRepo):
    async def photos_for_project_in_range(
        self,
        project_id: uuid.UUID,
        *,
        date_from: Any = None,
        date_to: Any = None,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        return rows[offset : offset + limit], len(rows)

    async def photos_for_diary(self, diary_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "diary_id", None) == diary_id]


class _StubSignatureRepo(_BaseStubRepo):
    async def signatures_for_diary(self, diary_id: uuid.UUID) -> list[Any]:
        return sorted(
            (r for r in self.rows.values() if r.diary_id == diary_id),
            key=lambda r: r.revision,
        )

    async def latest_for_diary(self, diary_id: uuid.UUID) -> Any:
        rows = [r for r in self.rows.values() if r.diary_id == diary_id]
        return max(rows, key=lambda r: r.revision) if rows else None


class _StubWeatherRepo(_BaseStubRepo):
    async def for_project_on_day(
        self,
        project_id: uuid.UUID,
        day_start: datetime,
        day_end: datetime,
    ) -> list[Any]:
        rows = [r for r in self.rows.values() if r.project_id == project_id and day_start <= r.captured_at < day_end]
        return sorted(rows, key=lambda r: r.captured_at, reverse=True)


class _StubGenericProjectRepo(_BaseStubRepo):
    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        return rows[offset : offset + limit], len(rows)


def _make_service() -> DailyDiaryService:
    svc = DailyDiaryService.__new__(DailyDiaryService)
    svc.session = _StubSession()
    svc.diary_repo = _StubDiaryRepo()
    svc.weather_repo = _StubWeatherRepo()
    svc.entry_repo = _StubEntryRepo()
    svc.photo_repo = _StubPhotoRepo()
    svc.video_repo = _StubGenericProjectRepo()
    svc.drone_repo = _StubGenericProjectRepo()
    svc.reality_repo = _StubGenericProjectRepo()
    svc.signature_repo = _StubSignatureRepo()
    return svc


def _diary_payload(**overrides: Any) -> DailyDiaryCreate:
    defaults: dict[str, Any] = {
        "project_id": PROJECT_ID,
        "diary_date": "2026-04-10",
        "labour_count": 12,
        "equipment_count": 4,
        "weather_summary": {"temp_c": 18.0, "conditions": "clear"},
        "notes": "All as planned",
        "metadata": {"weather_source": "open_meteo"},
    }
    defaults.update(overrides)
    return DailyDiaryCreate(**defaults)


# ── Pure helpers ─────────────────────────────────────────────────────────


def _fake_diary(**kw: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "project_id": PROJECT_ID,
        "diary_date": "2026-04-10",
        "site_supervisor_id": None,
        "weather_summary": {"temp": 18},
        "labour_count": 10,
        "equipment_count": 2,
        "notes": "ok",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _fake_entry(**kw: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "diary_id": uuid.uuid4(),
        "entry_type": "general",
        "entry_time": datetime(2026, 4, 10, 9, 0, tzinfo=UTC),
        "title": "T",
        "description": "D",
        "source_module": None,
        "source_ref": None,
        "author_id": None,
        "photo_ids": [],
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _fake_photo(**kw: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "taken_at": datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
        "lat": 52.52,
        "lng": 13.40,
        "file_url": "http://x/a.jpg",
        "mime_type": "image/jpeg",
        "is_360": False,
        "is_drone": False,
        "diary_id": uuid.uuid4(),
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_compute_immutable_payload_is_deterministic() -> None:
    diary = _fake_diary()
    e1 = _fake_entry(entry_time=datetime(2026, 4, 10, 8, tzinfo=UTC))
    e2 = _fake_entry(entry_time=datetime(2026, 4, 10, 12, tzinfo=UTC))
    p1 = _fake_photo()
    payload_a = compute_immutable_payload(diary, [e1, e2], [p1])
    payload_b = compute_immutable_payload(diary, [e2, e1], [p1])
    assert payload_a == payload_b
    assert payload_a["diary"]["diary_date"] == "2026-04-10"
    assert "schema_version" in payload_a
    assert payload_a["entries"][0]["entry_time"] < payload_a["entries"][1]["entry_time"]


def test_compute_content_sha256_changes_when_payload_changes() -> None:
    diary = _fake_diary()
    h1 = compute_content_sha256(compute_immutable_payload(diary, [], []))
    diary2 = _fake_diary(labour_count=99)
    h2 = compute_content_sha256(compute_immutable_payload(diary2, [], []))
    assert h1 != h2
    # Hex 64 chars
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_compute_content_sha256_is_deterministic_for_same_payload() -> None:
    diary = _fake_diary()
    payload = compute_immutable_payload(diary, [], [])
    assert compute_content_sha256(payload) == compute_content_sha256(payload)


def test_is_diary_signed_with_signature() -> None:
    diary_id = uuid.uuid4()
    sig = SimpleNamespace(diary_id=diary_id, revision=1, content_sha256="abc")
    assert is_diary_signed(diary_id, [sig]) is True


def test_is_diary_signed_without_signature() -> None:
    assert is_diary_signed(uuid.uuid4(), []) is False


def test_auto_populate_maps_hse_to_incident_summary() -> None:
    diary = _fake_diary()
    out = auto_populate_entries_from_module_events(
        diary,
        [
            {
                "source_module": "hse",
                "title": "Near-miss A",
                "occurred_at": datetime(2026, 4, 10, 9, tzinfo=UTC),
                "source_ref": uuid.uuid4(),
            }
        ],
    )
    assert len(out) == 1
    assert out[0]["entry_type"] == "incident_summary"
    assert out[0]["source_module"] == "hse"


def test_auto_populate_maps_procurement_to_delivery() -> None:
    out = auto_populate_entries_from_module_events(
        _fake_diary(),
        [{"source_module": "procurement", "title": "Concrete batch"}],
    )
    assert out[0]["entry_type"] == "delivery"


def test_auto_populate_maps_quality_to_inspection_summary() -> None:
    out = auto_populate_entries_from_module_events(
        _fake_diary(),
        [{"source_module": "quality", "summary": "QC OK"}],
    )
    assert out[0]["entry_type"] == "inspection_summary"


def test_auto_populate_maps_schedule_to_completion() -> None:
    out = auto_populate_entries_from_module_events(
        _fake_diary(),
        [{"source_module": "schedule", "title": "Foundation complete"}],
    )
    assert out[0]["entry_type"] == "completion"


def test_auto_populate_unknown_module_falls_back_to_general() -> None:
    out = auto_populate_entries_from_module_events(
        _fake_diary(),
        [{"source_module": "marketing", "title": "Site visit"}],
    )
    assert out[0]["entry_type"] == "general"


def test_compute_diary_completeness_zero_when_empty() -> None:
    diary = SimpleNamespace(
        diary_date="",
        site_supervisor_id=None,
        weather_summary={},
        labour_count=0,
        equipment_count=0,
        notes=None,
    )
    score = compute_diary_completeness(diary, [])
    assert score == Decimal("0")


def test_compute_diary_completeness_full_when_all_fields_present() -> None:
    diary = _fake_diary(site_supervisor_id=uuid.uuid4())
    entries = [_fake_entry()]
    score = compute_diary_completeness(diary, entries)
    assert score == Decimal("1.0000")


def test_compute_diary_completeness_partial() -> None:
    diary = SimpleNamespace(
        diary_date="2026-04-10",
        site_supervisor_id=None,
        weather_summary={"a": 1},
        labour_count=5,
        equipment_count=0,  # empty
        notes=None,
    )
    score = compute_diary_completeness(diary, [])
    # 3 of 7 fields filled (date, weather_summary, labour_count); no entries
    assert score > Decimal("0") and score < Decimal("0.6")


def test_compute_photo_timeline_groups_by_day() -> None:
    photos = [
        _fake_photo(taken_at=datetime(2026, 4, 10, 9, tzinfo=UTC)),
        _fake_photo(taken_at=datetime(2026, 4, 10, 15, tzinfo=UTC)),
        _fake_photo(taken_at=datetime(2026, 4, 11, 9, tzinfo=UTC)),
    ]
    buckets = compute_photo_timeline(PROJECT_ID, photos, None, None)
    assert len(buckets) == 2
    assert buckets[0]["date"] == "2026-04-10"
    assert buckets[0]["photo_count"] == 2
    assert buckets[1]["date"] == "2026-04-11"


def test_compute_before_after_pairs_by_proximity() -> None:
    p_before = _fake_photo(
        taken_at=datetime(2026, 4, 10, 9, tzinfo=UTC),
        lat=52.520,
        lng=13.400,
    )
    p_after = _fake_photo(
        taken_at=datetime(2026, 4, 20, 9, tzinfo=UTC),
        lat=52.520001,
        lng=13.400001,
    )
    p_far = _fake_photo(
        taken_at=datetime(2026, 4, 20, 9, tzinfo=UTC),
        lat=53.0,
        lng=14.0,
    )
    pairs = compute_before_after(
        [p_before, p_after, p_far],
        datetime(2026, 4, 10, tzinfo=UTC),
        datetime(2026, 4, 20, tzinfo=UTC),
        location_radius_m=15.0,
    )
    assert len(pairs) == 1
    assert pairs[0]["photo_a_id"] == p_before.id
    assert pairs[0]["photo_b_id"] == p_after.id


def test_compute_before_after_returns_empty_when_no_matches() -> None:
    p1 = _fake_photo(
        taken_at=datetime(2026, 4, 10, tzinfo=UTC),
        lat=52.5,
        lng=13.4,
    )
    p2 = _fake_photo(
        taken_at=datetime(2026, 4, 20, tzinfo=UTC),
        lat=53.0,
        lng=14.0,
    )
    pairs = compute_before_after(
        [p1, p2],
        datetime(2026, 4, 10, tzinfo=UTC),
        datetime(2026, 4, 20, tzinfo=UTC),
        location_radius_m=15.0,
    )
    assert pairs == []


def test_validate_diary_immutability_no_signatures() -> None:
    ok, reason = validate_diary_immutability(uuid.uuid4(), [], {"foo": "bar"})
    assert ok is True
    assert reason is None


def test_validate_diary_immutability_blocks_modified_payload() -> None:
    diary_id = uuid.uuid4()
    original_payload = {"diary": {"x": 1}}
    sig = SimpleNamespace(
        diary_id=diary_id,
        revision=1,
        content_sha256=compute_content_sha256(original_payload),
    )
    new_payload = {"diary": {"x": 2}}
    ok, reason = validate_diary_immutability(diary_id, [sig], new_payload)
    assert ok is False
    assert reason is not None and "signed" in reason


def test_validate_diary_immutability_allows_same_payload() -> None:
    diary_id = uuid.uuid4()
    payload = {"diary": {"x": 1}}
    sig = SimpleNamespace(
        diary_id=diary_id,
        revision=1,
        content_sha256=compute_content_sha256(payload),
    )
    ok, reason = validate_diary_immutability(diary_id, [sig], payload)
    assert ok is True
    assert reason is None


# ── Service: state transitions ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_diary_persists_and_returns_row() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="user-1")
    assert diary.id is not None
    assert diary.diary_date == "2026-04-10"
    assert diary.status == "open"


@pytest.mark.asyncio
async def test_create_diary_duplicate_date_raises_409() -> None:
    svc = _make_service()
    await svc.create_diary(_diary_payload(), user_id="u")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.create_diary(_diary_payload(), user_id="u")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_close_diary_transitions_status_and_emits_event() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    with patch(
        "app.modules.daily_diary.service.event_bus.publish_detached",
    ) as bus:
        closed = await svc.close_diary(diary.id, user_id="u")
    assert closed.status == "closed"
    # close emits both 'daily_diary.closed' AND 'daily_diary.workforce.summary'
    # so downstream resources/HSE modules pick up the day's utilisation.
    event_names = [call.args[0] for call in bus.call_args_list]
    assert "daily_diary.closed" in event_names
    assert "daily_diary.workforce.summary" in event_names


@pytest.mark.asyncio
async def test_close_diary_cannot_regress_from_signed() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    with patch("app.modules.daily_diary.service.event_bus.publish_detached"):
        await svc.close_diary(diary.id, user_id="u")
        await svc.sign_diary(
            diary.id,
            signer_role="supervisor",
            signer_name="A",
            user_id="u",
        )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.close_diary(diary.id, user_id="u")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_sign_diary_creates_signature_and_emits_event() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    with patch(
        "app.modules.daily_diary.service.event_bus.publish_detached",
    ) as bus:
        sig = await svc.sign_diary(
            diary.id,
            signer_role="supervisor",
            signer_name="Site Boss",
            user_id="u",
        )
    assert len(sig.content_sha256) == 64
    # close + sign events
    names = [c.args[0] for c in bus.call_args_list]
    assert "daily_diary.closed" in names
    assert "daily_diary.signed" in names


@pytest.mark.asyncio
async def test_sign_diary_idempotent_increments_revision() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    with patch("app.modules.daily_diary.service.event_bus.publish_detached"):
        sig1 = await svc.sign_diary(
            diary.id,
            signer_role="supervisor",
            signer_name="A",
            user_id="u",
        )
        sig2 = await svc.sign_diary(
            diary.id,
            signer_role="supervisor",
            signer_name="A",
            user_id="u",
        )
    assert sig2.revision == sig1.revision + 1


@pytest.mark.asyncio
async def test_archive_diary_emits_event() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    with patch(
        "app.modules.daily_diary.service.event_bus.publish_detached",
    ) as bus:
        await svc.close_diary(diary.id, user_id="u")
        await svc.sign_diary(
            diary.id,
            signer_role="owner",
            signer_name="O",
            user_id="u",
        )
        archived = await svc.archive_diary(diary.id, user_id="u")
    assert archived.status == "archived"
    archived_calls = [c for c in bus.call_args_list if c.args[0] == "daily_diary.archived"]
    assert len(archived_calls) == 1


@pytest.mark.asyncio
async def test_archive_diary_cannot_be_regressed() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    with patch("app.modules.daily_diary.service.event_bus.publish_detached"):
        await svc.close_diary(diary.id, user_id="u")
        await svc.sign_diary(
            diary.id,
            signer_role="owner",
            signer_name="O",
            user_id="u",
        )
        await svc.archive_diary(diary.id, user_id="u")
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.close_diary(diary.id, user_id="u")


@pytest.mark.asyncio
async def test_update_signed_diary_rejected() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    with patch("app.modules.daily_diary.service.event_bus.publish_detached"):
        await svc.close_diary(diary.id, user_id="u")
        await svc.sign_diary(
            diary.id,
            signer_role="owner",
            signer_name="O",
            user_id="u",
        )
    from fastapi import HTTPException

    from app.modules.daily_diary.schemas import DailyDiaryUpdate

    with pytest.raises(HTTPException) as exc:
        await svc.update_diary(diary.id, DailyDiaryUpdate(notes="cheating"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_future_dated_diary_rejected() -> None:
    """A contemporaneous record cannot be opened ahead of the site date."""
    svc = _make_service()
    from fastapi import HTTPException

    future = (datetime.now(UTC) + timedelta(days=10)).date().isoformat()
    with pytest.raises(HTTPException) as exc:
        await svc.create_diary(_diary_payload(diary_date=future), user_id="u")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_backdated_diary_allowed() -> None:
    """Retroactive (back-dated) entry is a legitimate site-diary flow."""
    svc = _make_service()
    past = (datetime.now(UTC) - timedelta(days=45)).date().isoformat()
    diary = await svc.create_diary(_diary_payload(diary_date=past), user_id="u")
    assert diary.diary_date == past


@pytest.mark.asyncio
async def test_create_today_diary_allowed() -> None:
    svc = _make_service()
    today = datetime.now(UTC).date().isoformat()
    diary = await svc.create_diary(_diary_payload(diary_date=today), user_id="u")
    assert diary.diary_date == today


@pytest.mark.asyncio
async def test_immutable_hash_scoped_to_diary_photos_only() -> None:
    """Photos belonging to a SIBLING diary in the same project must NOT
    influence the immutable hash of the diary under inspection.

    Regression: previously the service loaded every photo in the entire
    project and filtered by ``diary_id`` in Python — fine for correctness
    but expensive at scale. The new code path uses an indexed
    ``photos_for_diary`` repo method; this test confirms the scoping is
    preserved.
    """
    svc = _make_service()
    diary_a = await svc.create_diary(
        _diary_payload(diary_date="2026-04-09"),
        user_id="u",
    )
    diary_b = await svc.create_diary(
        _diary_payload(diary_date="2026-04-10"),
        user_id="u",
    )

    # Attach one photo to each diary; both share the same project.
    photo_a = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        diary_id=diary_a.id,
        taken_at=datetime(2026, 4, 9, 12, tzinfo=UTC),
        lat=52.0,
        lng=13.0,
        file_url="http://x/a.jpg",
        mime_type="image/jpeg",
        is_360=False,
        is_drone=False,
    )
    photo_b = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        diary_id=diary_b.id,
        taken_at=datetime(2026, 4, 10, 12, tzinfo=UTC),
        lat=52.0,
        lng=13.0,
        file_url="http://x/b.jpg",
        mime_type="image/jpeg",
        is_360=False,
        is_drone=False,
    )
    svc.photo_repo.rows[photo_a.id] = photo_a
    svc.photo_repo.rows[photo_b.id] = photo_b

    hash_b = await svc.immutable_payload_hash(diary_b.id)
    assert hash_b["payload_preview"]["photos_count"] == 1, "diary B's hash must include only its own photo, not photo A"


@pytest.mark.asyncio
async def test_archive_unsigned_diary_rejected() -> None:
    """Archiving must require a signed diary so the snapshot is sealed."""
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    from fastapi import HTTPException

    with patch("app.modules.daily_diary.service.event_bus.publish_detached"):
        await svc.close_diary(diary.id, user_id="u")
        with pytest.raises(HTTPException) as exc:
            await svc.archive_diary(diary.id, user_id="u")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_entry_blocked_when_diary_sealed() -> None:
    """Editing an entry of a signed diary invalidates the snapshot → 409."""
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    entry = await svc.create_entry(
        DiaryEntryCreate(
            diary_id=diary.id,
            entry_type="visitor",
            entry_time=datetime(2026, 4, 10, 9, tzinfo=UTC),
            title="Inspector",
        )
    )
    with patch("app.modules.daily_diary.service.event_bus.publish_detached"):
        await svc.close_diary(diary.id, user_id="u")
        await svc.sign_diary(
            diary.id,
            signer_role="owner",
            signer_name="O",
            user_id="u",
        )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.update_entry(entry.id, {"title": "tampered"})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_entry_allowed_when_diary_open() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    entry = await svc.create_entry(
        DiaryEntryCreate(
            diary_id=diary.id,
            entry_type="visitor",
            entry_time=datetime(2026, 4, 10, 9, tzinfo=UTC),
            title="Inspector",
        )
    )
    updated = await svc.update_entry(entry.id, {"title": "Revised"})
    assert updated.title == "Revised"


@pytest.mark.asyncio
async def test_delete_entry_blocked_when_diary_sealed() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    entry = await svc.create_entry(
        DiaryEntryCreate(
            diary_id=diary.id,
            entry_type="visitor",
            entry_time=datetime(2026, 4, 10, 9, tzinfo=UTC),
            title="Inspector",
        )
    )
    with patch("app.modules.daily_diary.service.event_bus.publish_detached"):
        await svc.close_diary(diary.id, user_id="u")
        await svc.sign_diary(
            diary.id,
            signer_role="owner",
            signer_name="O",
            user_id="u",
        )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.delete_entry(entry.id)
    assert exc.value.status_code == 409


# ── Service: photo / drone / reality capture emit events ────────────────


@pytest.mark.asyncio
async def test_register_photo_emits_event() -> None:
    svc = _make_service()
    payload = DiaryPhotoCreate(
        project_id=PROJECT_ID,
        taken_at=datetime(2026, 4, 10, 12, tzinfo=UTC),
        file_url="http://x/a.jpg",
        lat=52.5,
        lng=13.4,
    )
    with patch(
        "app.modules.daily_diary.service.event_bus.publish_detached",
    ) as bus:
        photo = await svc.register_photo(payload)
    assert photo.id is not None
    assert any(c.args[0] == "daily_diary.photo.registered" for c in bus.call_args_list)


@pytest.mark.asyncio
async def test_register_photo_auto_links_to_existing_diary_by_date() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(diary_date="2026-04-10"), user_id="u")
    payload = DiaryPhotoCreate(
        project_id=PROJECT_ID,
        taken_at=datetime(2026, 4, 10, 12, tzinfo=UTC),
        file_url="http://x/a.jpg",
    )
    with patch("app.modules.daily_diary.service.event_bus.publish_detached"):
        photo = await svc.register_photo(payload)
    assert photo.diary_id == diary.id


@pytest.mark.asyncio
async def test_attach_drone_survey_emits_event() -> None:
    svc = _make_service()
    payload = DroneSurveyCreate(
        project_id=PROJECT_ID,
        flown_at=datetime(2026, 4, 10, 11, tzinfo=UTC),
        pilot_name="Pilot",
        drone_model="DJI",
        area_m2=Decimal("123.45"),
    )
    with patch(
        "app.modules.daily_diary.service.event_bus.publish_detached",
    ) as bus:
        survey = await svc.attach_drone_survey(payload)
    assert survey.id is not None
    assert any(c.args[0] == "daily_diary.drone.attached" for c in bus.call_args_list)


@pytest.mark.asyncio
async def test_attach_reality_capture_emits_event() -> None:
    svc = _make_service()
    payload = RealityCaptureCreate(
        project_id=PROJECT_ID,
        captured_at=datetime(2026, 4, 10, 14, tzinfo=UTC),
        capture_type="laser_scan",
        file_url="http://x/scan.e57",
    )
    with patch(
        "app.modules.daily_diary.service.event_bus.publish_detached",
    ) as bus:
        ds = await svc.attach_reality_capture(payload)
    assert ds.id is not None
    assert any(c.args[0] == "daily_diary.reality_capture.attached" for c in bus.call_args_list)


# ── Service: weather + entries repository basics ─────────────────────────


@pytest.mark.asyncio
async def test_create_weather_record_persists() -> None:
    svc = _make_service()
    record = await svc.create_weather(
        WeatherRecordCreate(
            project_id=PROJECT_ID,
            captured_at=datetime(2026, 4, 10, 8, tzinfo=UTC),
            source="manual",
            temperature_c=Decimal("21.5"),
            humidity_pct=Decimal("55.0"),
        )
    )
    assert record.id is not None
    assert record.source == "manual"


@pytest.mark.asyncio
async def test_create_entry_then_bulk_create() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    single = await svc.create_entry(
        DiaryEntryCreate(
            diary_id=diary.id,
            entry_type="visitor",
            entry_time=datetime(2026, 4, 10, 9, tzinfo=UTC),
            title="Inspector",
        )
    )
    assert single.id is not None
    bulk = await svc.bulk_create_entries(
        diary.id,
        [
            {
                "entry_type": "delivery",
                "entry_time": datetime(2026, 4, 10, 10, tzinfo=UTC),
                "title": "Concrete",
            },
            {
                "entry_type": "event",
                "entry_time": datetime(2026, 4, 10, 11, tzinfo=UTC),
                "title": "Crane setup",
            },
        ],
    )
    assert len(bulk) == 2
    rows = await svc.entry_repo.list_for_diary(diary.id)
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_delete_diary() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    await svc.delete_diary(diary.id)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.get_diary(diary.id)


@pytest.mark.asyncio
async def test_get_diary_404_when_missing() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.get_diary(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_completeness_via_service() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    payload = await svc.completeness_for(diary.id)
    assert "completeness" in payload
    assert "missing" in payload


@pytest.mark.asyncio
async def test_immutable_payload_hash_returns_64_hex() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    result = await svc.immutable_payload_hash(diary.id)
    assert len(result["content_sha256"]) == 64


@pytest.mark.asyncio
async def test_pdf_stub_is_idempotent() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    a = await svc.generate_pdf_stub(diary.id)
    b = await svc.generate_pdf_stub(diary.id)
    assert a["pdf_export_ref"] == b["pdf_export_ref"]
    assert a["status"] == "stub"


# ── Permissions ──────────────────────────────────────────────────────────


def test_permissions_registered() -> None:
    from app.core.permissions import permission_registry
    from app.modules.daily_diary.permissions import register_daily_diary_permissions

    register_daily_diary_permissions()
    for perm in (
        "daily_diary.read",
        "daily_diary.create",
        "daily_diary.update",
        "daily_diary.delete",
        "daily_diary.close",
        "daily_diary.sign",
        "daily_diary.archive",
        "daily_diary.upload_photo",
        "daily_diary.attach_drone",
        "daily_diary.attach_reality_capture",
    ):
        assert perm in permission_registry._permissions  # noqa: SLF001


# ── Spec timing sanity check ─────────────────────────────────────────────


def test_status_machine_order() -> None:
    from app.modules.daily_diary.service import DIARY_STATUSES

    # The state machine is exactly open → closed → signed → archived.
    assert DIARY_STATUSES == ("open", "closed", "signed", "archived")


def test_compute_before_after_uses_radius_strictly() -> None:
    # Two photos exactly at the radius boundary (~15 m apart along lat).
    near = _fake_photo(
        taken_at=datetime(2026, 4, 10, tzinfo=UTC),
        lat=52.5,
        lng=13.4,
    )
    # Roughly 1.5km away
    far = _fake_photo(
        taken_at=datetime(2026, 4, 20, tzinfo=UTC),
        lat=52.51,
        lng=13.4,
    )
    pairs = compute_before_after(
        [near, far],
        datetime(2026, 4, 10, tzinfo=UTC),
        datetime(2026, 4, 20, tzinfo=UTC),
        location_radius_m=15.0,
    )
    assert pairs == []


# ── Productivity factor (trade-aware, real coefficients) ─────────────────


def test_productivity_concrete_stopped_in_heavy_rain() -> None:
    from app.modules.daily_diary.weather import compute_productivity_factor

    result = compute_productivity_factor(
        trade="concrete",
        rain_hours=6,
        precipitation_mm=40.0,  # 40mm over 6h → 6.7 mm/h, above 2 threshold
        temperature_c=12.0,
        working_hours=8,
    )
    assert result["stopped"] is True
    assert float(result["factor"]) == 0.0


def test_productivity_concrete_stopped_when_freezing() -> None:
    from app.modules.daily_diary.weather import compute_productivity_factor

    result = compute_productivity_factor(
        trade="concrete",
        temperature_c=1.0,
        working_hours=8,
    )
    assert result["stopped"] is True
    assert "temperature" in result["reason"]


def test_productivity_sitework_light_rain_partial_loss() -> None:
    from app.modules.daily_diary.weather import compute_productivity_factor

    result = compute_productivity_factor(
        trade="sitework",
        rain_hours=2,
        precipitation_mm=4.0,  # 2mm/h — below 15mm/h stop threshold
        temperature_c=12.0,
        working_hours=8,
    )
    assert result["stopped"] is False
    # 2h * 0.8 / 8h = 0.2 loss; factor = 0.8
    assert float(result["factor"]) == pytest.approx(0.8, abs=0.01)
    assert float(result["lost_hours"]) == pytest.approx(1.6, abs=0.05)


def test_productivity_interior_finishes_minimal_impact() -> None:
    from app.modules.daily_diary.weather import compute_productivity_factor

    result = compute_productivity_factor(
        trade="finishes_interior",
        rain_hours=8,
        precipitation_mm=80.0,
        temperature_c=18.0,
        working_hours=8,
    )
    # Interior finishes have rain_stop_mm_h = 999 (i.e. weather insensitive)
    assert result["stopped"] is False
    assert float(result["factor"]) >= 0.6


def test_productivity_steel_erection_stopped_by_wind() -> None:
    from app.modules.daily_diary.weather import compute_productivity_factor

    result = compute_productivity_factor(
        trade="steel_erection",
        wind_speed_kmh=55.0,
        working_hours=8,
    )
    assert result["stopped"] is True
    assert "wind" in result["reason"]


def test_productivity_unknown_trade_falls_back_to_sitework() -> None:
    from app.modules.daily_diary.weather import compute_productivity_factor

    a = compute_productivity_factor(trade="unknown_xyz", rain_hours=2)
    b = compute_productivity_factor(trade="sitework", rain_hours=2)
    assert float(a["factor"]) == float(b["factor"])


def test_list_supported_trades_includes_core_set() -> None:
    from app.modules.daily_diary.weather import list_supported_trades

    trades = list_supported_trades()
    for needed in (
        "concrete",
        "roofing",
        "steel_erection",
        "earthworks",
        "finishes_interior",
        "mep_roughin",
    ):
        assert needed in trades


# ── EXIF GPS extraction ──────────────────────────────────────────────────


def test_extract_exif_gps_empty_bytes_returns_none() -> None:
    from app.modules.daily_diary.weather import extract_exif_gps

    assert extract_exif_gps(b"") is None


def test_extract_exif_gps_non_image_returns_none() -> None:
    from app.modules.daily_diary.weather import extract_exif_gps

    # Random bytes should not parse as an image
    assert extract_exif_gps(b"not an image, just text") is None


# ── Photo / video MIME and size enforcement ──────────────────────────────


def test_photo_create_rejects_svg_mime() -> None:
    """SVG is renderable as inline HTML — must never reach diary photos."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DiaryPhotoCreate(
            project_id=PROJECT_ID,
            taken_at=datetime(2026, 4, 10, 12, tzinfo=UTC),
            file_url="http://x/a.svg",
            mime_type="image/svg+xml",
        )


def test_photo_create_rejects_text_html_mime() -> None:
    """Client-declared text/html MUST be rejected at the schema layer."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DiaryPhotoCreate(
            project_id=PROJECT_ID,
            taken_at=datetime(2026, 4, 10, 12, tzinfo=UTC),
            file_url="http://x/a.html",
            mime_type="text/html",
        )


def test_photo_create_rejects_oversize_file_bytes() -> None:
    """A 5 GB photo is nonsense — cap is 200 MB."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DiaryPhotoCreate(
            project_id=PROJECT_ID,
            taken_at=datetime(2026, 4, 10, 12, tzinfo=UTC),
            file_url="http://x/a.jpg",
            file_size_bytes=5 * 1024 * 1024 * 1024,  # 5 GB
        )


def test_video_create_rejects_non_video_mime() -> None:
    """A claimed ``text/html`` video MUST be rejected at the schema layer."""
    from pydantic import ValidationError

    from app.modules.daily_diary.schemas import DiaryVideoCreate

    with pytest.raises(ValidationError):
        DiaryVideoCreate(
            project_id=PROJECT_ID,
            recorded_at=datetime(2026, 4, 10, 12, tzinfo=UTC),
            file_url="http://x/a.mp4",
            mime_type="text/html",  # not a video MIME
        )


def test_video_create_accepts_mp4_mime() -> None:
    """Sanity-check the video allow-list."""
    from app.modules.daily_diary.schemas import DiaryVideoCreate

    obj = DiaryVideoCreate(
        project_id=PROJECT_ID,
        recorded_at=datetime(2026, 4, 10, 12, tzinfo=UTC),
        file_url="http://x/a.mp4",
        mime_type="video/mp4",
    )
    assert obj.mime_type == "video/mp4"


def test_video_create_rejects_implausible_duration() -> None:
    """30-day duration is almost certainly a unit-conversion mistake."""
    from pydantic import ValidationError

    from app.modules.daily_diary.schemas import DiaryVideoCreate

    with pytest.raises(ValidationError):
        DiaryVideoCreate(
            project_id=PROJECT_ID,
            recorded_at=datetime(2026, 4, 10, 12, tzinfo=UTC),
            file_url="http://x/a.mp4",
            duration_seconds=30 * 24 * 3600,
        )


def test_exif_gps_endpoint_magic_byte_rejects_svg() -> None:
    """``/photos/extract-gps`` is base64-only; verify the magic-byte gate
    rejects an SVG payload (raw text starting with ``<svg``).

    The endpoint MUST reject before passing bytes into Pillow / EXIF
    machinery — that's the whole point of the gate. This is a contract
    test on the underlying ``require`` helper that the router wires in.
    """
    from app.core.file_signature import (
        ALLOWED_PHOTO_TYPES,
        FileSignatureMismatch,
    )
    from app.core.file_signature import require as require_signature

    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'
    with pytest.raises(FileSignatureMismatch):
        require_signature(svg[:16], ALLOWED_PHOTO_TYPES)


def test_exif_gps_endpoint_magic_byte_accepts_jpeg_head() -> None:
    """A valid JPEG header passes the magic-byte gate."""
    from app.core.file_signature import ALLOWED_PHOTO_TYPES
    from app.core.file_signature import require as require_signature

    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00"
    detected = require_signature(jpeg[:16], ALLOWED_PHOTO_TYPES)
    assert detected == "jpeg"


# ── Labour count / equipment count bounds ────────────────────────────────


def test_diary_create_rejects_implausible_labour_count() -> None:
    """Labour count must be ≤ MAX_LABOUR_COUNT (10 000)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DailyDiaryCreate(
            project_id=PROJECT_ID,
            diary_date="2026-04-10",
            labour_count=999_999_999,
        )


def test_diary_create_rejects_negative_labour_count() -> None:
    """Labour count must be ≥ 0."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DailyDiaryCreate(
            project_id=PROJECT_ID,
            diary_date="2026-04-10",
            labour_count=-1,
        )


def test_diary_create_rejects_implausible_equipment_count() -> None:
    """Equipment count must be ≤ MAX_EQUIPMENT_COUNT (5 000)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DailyDiaryCreate(
            project_id=PROJECT_ID,
            diary_date="2026-04-10",
            equipment_count=10_000_000,
        )


# ── Drone elevation invariant ────────────────────────────────────────────


def test_drone_create_rejects_min_above_max_elevation() -> None:
    """``elevation_min_m`` must be ≤ ``elevation_max_m``."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DroneSurveyCreate(
            project_id=PROJECT_ID,
            flown_at=datetime(2026, 4, 10, 11, tzinfo=UTC),
            elevation_min_m=Decimal("500"),
            elevation_max_m=Decimal("200"),
        )


def test_drone_create_accepts_equal_min_max_elevation() -> None:
    """Flat-terrain edge case — min == max is valid."""
    obj = DroneSurveyCreate(
        project_id=PROJECT_ID,
        flown_at=datetime(2026, 4, 10, 11, tzinfo=UTC),
        elevation_min_m=Decimal("100"),
        elevation_max_m=Decimal("100"),
    )
    assert obj.elevation_min_m == obj.elevation_max_m


def test_drone_create_rejects_implausible_area() -> None:
    """100 km² (100 000 000 m²) is the cap — a stray "billion m²" is junk."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DroneSurveyCreate(
            project_id=PROJECT_ID,
            flown_at=datetime(2026, 4, 10, 11, tzinfo=UTC),
            area_m2=Decimal("1000000000"),  # 1 000 km²
        )


@pytest.mark.asyncio
async def test_update_drone_survey_rejects_partial_inversion() -> None:
    """PATCH that would create an inverted range against the stored row.

    Stored: elevation_min=100, elevation_max=200. PATCH bumps min to 300
    without touching max — the resulting row would have min(300) > max(200).
    """
    svc = _make_service()
    survey = await svc.attach_drone_survey(
        DroneSurveyCreate(
            project_id=PROJECT_ID,
            flown_at=datetime(2026, 4, 10, 11, tzinfo=UTC),
            elevation_min_m=Decimal("100"),
            elevation_max_m=Decimal("200"),
        ),
    )
    from fastapi import HTTPException

    from app.modules.daily_diary.schemas import DroneSurveyUpdate

    with pytest.raises(HTTPException) as exc:
        await svc.update_drone_survey(
            survey.id,
            DroneSurveyUpdate(elevation_min_m=Decimal("300")),
        )
    assert exc.value.status_code == 422


# ── Workforce summary cross-module event ─────────────────────────────────


@pytest.mark.asyncio
async def test_workforce_summary_aggregates_entries() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    # Add two entries each carrying labour/equipment counts in metadata.
    e1 = SimpleNamespace(
        id=uuid.uuid4(),
        diary_id=diary.id,
        entry_type="visitor",
        entry_time=datetime.now(UTC),
        title="A",
        description=None,
        source_module=None,
        source_ref=None,
        author_id=None,
        photo_ids=[],
        metadata_={"labour_count": 8, "company": "Alpha"},
    )
    e2 = SimpleNamespace(
        id=uuid.uuid4(),
        diary_id=diary.id,
        entry_type="visitor",
        entry_time=datetime.now(UTC),
        title="B",
        description=None,
        source_module=None,
        source_ref=None,
        author_id=None,
        photo_ids=[],
        metadata_={
            "labour_count": 5,
            "equipment_count": 2,
            "company": "Beta",
        },
    )
    svc.entry_repo.rows[e1.id] = e1
    svc.entry_repo.rows[e2.id] = e2

    summary = await svc.workforce_summary_for_diary(diary.id)
    assert summary["diary_id"] == diary.id
    # Diary base = 12 labour, entries add 8+5 = 13 → 25
    assert summary["labour_count"] == 25
    # Diary base = 4 equipment, entries add 2 → 6
    assert summary["equipment_count"] == 6
    assert summary["by_company"] == {"Alpha": 8, "Beta": 5}


@pytest.mark.asyncio
async def test_workforce_summary_stable_after_close() -> None:
    """Regression: `close_diary` used to mutate ``diary.labour_count`` by
    folding entries' metadata onto it. A later call to
    ``workforce_summary_for_diary`` then re-counted the same entries on
    top of the inflated base, double-counting them.

    The summary must be idempotent across the close transition.
    """
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    # Pre-existing entry that carries a labour count.
    entry = SimpleNamespace(
        id=uuid.uuid4(),
        diary_id=diary.id,
        entry_type="visitor",
        entry_time=datetime(2026, 4, 10, 9, tzinfo=UTC),
        title="Crew",
        description=None,
        source_module=None,
        source_ref=None,
        author_id=None,
        photo_ids=[],
        metadata_={"labour_count": 4, "company": "Alpha"},
    )
    svc.entry_repo.rows[entry.id] = entry

    before = await svc.workforce_summary_for_diary(diary.id)
    with patch("app.modules.daily_diary.service.event_bus.publish_detached"):
        await svc.close_diary(diary.id, user_id="u")
    after = await svc.workforce_summary_for_diary(diary.id)

    assert before["labour_count"] == after["labour_count"], (
        "workforce summary must not change just because the diary was closed"
    )
    assert before["equipment_count"] == after["equipment_count"]


@pytest.mark.asyncio
async def test_emit_workforce_summary_publishes_event() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    with patch(
        "app.modules.daily_diary.service.event_bus.publish_detached",
    ) as bus:
        result = await svc.emit_workforce_summary(diary.id)
    assert result["labour_count"] == 12
    assert bus.call_count == 1
    name, payload = bus.call_args.args[0], bus.call_args.args[1]
    assert name == "daily_diary.workforce.summary"
    assert payload["diary_id"] == str(diary.id)


# ── SCL Protocol bundle manifest ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_scl_bundle_manifest_validates_date_range() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.build_scl_bundle_manifest(
            PROJECT_ID,
            date_from="2026-04-20",
            date_to="2026-04-10",
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_scl_bundle_manifest_returns_deterministic_hash() -> None:
    svc = _make_service()
    # Manifest should produce a stable hash for an empty range
    a = await svc.build_scl_bundle_manifest(
        PROJECT_ID,
        date_from="2026-04-10",
        date_to="2026-04-12",
    )
    b = await svc.build_scl_bundle_manifest(
        PROJECT_ID,
        date_from="2026-04-10",
        date_to="2026-04-12",
    )
    assert a["bundle_sha256"] == b["bundle_sha256"]
    assert len(a["bundle_sha256"]) == 64


# ── Real weather fetcher (URL building only — no live HTTP) ───────────────


def test_open_meteo_url_uses_archive_for_historical_dates() -> None:
    from datetime import date as _date
    from datetime import timedelta as _td

    from app.modules.daily_diary.weather import (
        _build_forecast_url,
        _build_historical_url,
    )

    historical = _date.today() - _td(days=30)
    forecast_url = _build_forecast_url(52.5, 13.4, historical)
    archive_url = _build_historical_url(52.5, 13.4, historical)
    assert "api.open-meteo.com" in forecast_url
    assert "archive-api.open-meteo.com" in archive_url
    assert "latitude=52.500000" in forecast_url
    assert historical.isoformat() in archive_url


def test_summarise_open_meteo_handles_empty_payload() -> None:
    from datetime import date as _date

    from app.modules.daily_diary.weather import _summarise_open_meteo

    assert _summarise_open_meteo({}, _date(2026, 4, 10)) is None
    assert _summarise_open_meteo({"hourly": {}}, _date(2026, 4, 10)) is None


def test_summarise_open_meteo_with_realistic_payload() -> None:
    from datetime import date as _date

    from app.modules.daily_diary.weather import _summarise_open_meteo

    payload = {
        "hourly": {
            "time": ["2026-04-10T08:00", "2026-04-10T09:00", "2026-04-10T10:00"],
            "temperature_2m": [12.0, 13.5, 14.2],
            "relativehumidity_2m": [70, 65, 60],
            "precipitation": [0.0, 0.5, 0.0],
            "weathercode": [1, 2, 2],
            "windspeed_10m": [10.0, 12.0, 8.0],
        },
        "daily": {
            "sunrise": ["2026-04-10T05:30"],
            "sunset": ["2026-04-10T19:45"],
        },
    }
    out = _summarise_open_meteo(payload, _date(2026, 4, 10))
    assert out is not None
    assert out["source"] == "open_meteo"
    assert out["conditions_code"] == "partly_cloudy"  # code 2 dominates
    assert out["rain_hours"] == 1  # only 1 hour > 0.1mm
    assert float(out["temperature_c"]) == pytest.approx(13.23, abs=0.05)


# ── Wave M4: cross-module wiring ───────────────────────────────────────


@pytest.mark.asyncio
async def test_diary_closed_subscriber_fans_out_actuals_and_kpi() -> None:
    """``daily_diary.closed`` → schedule actuals + BI kpi recompute."""
    import asyncio
    import uuid as _uuid

    from app.core import events as _ev_module
    from app.core.events import Event
    from app.modules.daily_diary.events import _on_diary_closed

    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    event = Event(
        name="daily_diary.closed",
        data={
            "diary_id": str(_uuid.uuid4()),
            "project_id": str(_uuid.uuid4()),
            "diary_date": "2026-05-13",
            "closed_by": "user-x",
        },
        source_module="daily_diary",
    )
    real = _ev_module.event_bus.publish_detached
    _ev_module.event_bus.publish_detached = _spy  # type: ignore[assignment]
    try:
        await _on_diary_closed(event)
    finally:
        _ev_module.event_bus.publish_detached = real  # type: ignore[assignment]
    names = [n for n, _ in captured]
    assert "schedule_advanced.actuals_update" in names
    assert "bi_dashboards.kpi_recompute" in names
    actuals = next(d for n, d in captured if n == "schedule_advanced.actuals_update")
    assert actuals["diary_date"] == "2026-05-13"
    assert actuals["scope"] == "all_tasks_for_date"


@pytest.mark.asyncio
async def test_diary_signed_subscriber_emits_kpi_recompute() -> None:
    """``daily_diary.signed`` → BI kpi recompute (scl_protocol_compliance, diary_signed_rate)."""
    import asyncio
    import uuid as _uuid

    from app.core import events as _ev_module
    from app.core.events import Event
    from app.modules.daily_diary.events import _on_diary_signed

    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    event = Event(
        name="daily_diary.signed",
        data={"diary_id": str(_uuid.uuid4()), "project_id": str(_uuid.uuid4())},
        source_module="daily_diary",
    )
    real = _ev_module.event_bus.publish_detached
    _ev_module.event_bus.publish_detached = _spy  # type: ignore[assignment]
    try:
        await _on_diary_signed(event)
    finally:
        _ev_module.event_bus.publish_detached = real  # type: ignore[assignment]
    kpi = next(d for n, d in captured if n == "bi_dashboards.kpi_recompute")
    assert "diary_signed_rate" in kpi["kpi_codes"]
    assert "scl_protocol_compliance" in kpi["kpi_codes"]


@pytest.mark.asyncio
async def test_diary_register_subscribers_idempotent() -> None:
    """register_subscribers wiring is safe to call repeatedly."""
    from app.modules.daily_diary.events import register_subscribers

    register_subscribers()
    register_subscribers()


# ── list_entries service method ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_entries_returns_diary_entries() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    await svc.create_entry(
        DiaryEntryCreate(
            diary_id=diary.id,
            entry_type="visitor",
            entry_time=datetime(2026, 4, 10, 9, tzinfo=UTC),
            title="Inspector",
        )
    )
    await svc.create_entry(
        DiaryEntryCreate(
            diary_id=diary.id,
            entry_type="delivery",
            entry_time=datetime(2026, 4, 10, 11, tzinfo=UTC),
            title="Concrete",
        )
    )
    rows = await svc.list_entries(diary.id)
    assert len(rows) == 2
    assert {r.entry_type for r in rows} == {"visitor", "delivery"}


@pytest.mark.asyncio
async def test_list_entries_filters_by_entry_type() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    await svc.create_entry(
        DiaryEntryCreate(
            diary_id=diary.id,
            entry_type="visitor",
            entry_time=datetime(2026, 4, 10, 9, tzinfo=UTC),
            title="V",
        )
    )
    await svc.create_entry(
        DiaryEntryCreate(
            diary_id=diary.id,
            entry_type="delivery",
            entry_time=datetime(2026, 4, 10, 10, tzinfo=UTC),
            title="D",
        )
    )
    rows = await svc.list_entries(diary.id, entry_type="delivery")
    assert len(rows) == 1
    assert rows[0].entry_type == "delivery"


@pytest.mark.asyncio
async def test_list_entries_unknown_diary_raises_404() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.list_entries(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_entries_empty_when_no_entries() -> None:
    svc = _make_service()
    diary = await svc.create_diary(_diary_payload(), user_id="u")
    assert await svc.list_entries(diary.id) == []


# ── weather_for_day service method ───────────────────────────────────────


@pytest.mark.asyncio
async def test_weather_for_day_scopes_to_calendar_day() -> None:
    """A back-dated diary must see only its OWN day's readings."""
    svc = _make_service()
    on_day = await svc.create_weather(
        WeatherRecordCreate(
            project_id=PROJECT_ID,
            captured_at=datetime(2026, 4, 10, 8, tzinfo=UTC),
            source="manual",
            temperature_c=Decimal("12.0"),
        )
    )
    # A reading on a different day must NOT leak into 2026-04-10.
    await svc.create_weather(
        WeatherRecordCreate(
            project_id=PROJECT_ID,
            captured_at=datetime(2026, 4, 12, 8, tzinfo=UTC),
            source="manual",
            temperature_c=Decimal("20.0"),
        )
    )
    rows = await svc.weather_for_day(PROJECT_ID, "2026-04-10")
    assert [r.id for r in rows] == [on_day.id]


@pytest.mark.asyncio
async def test_weather_for_day_excludes_next_day_midnight() -> None:
    """Half-open interval — a midnight reading belongs to the next day only."""
    svc = _make_service()
    await svc.create_weather(
        WeatherRecordCreate(
            project_id=PROJECT_ID,
            captured_at=datetime(2026, 4, 11, 0, 0, tzinfo=UTC),
            source="manual",
            temperature_c=Decimal("9.0"),
        )
    )
    assert await svc.weather_for_day(PROJECT_ID, "2026-04-10") == []
    assert len(await svc.weather_for_day(PROJECT_ID, "2026-04-11")) == 1


@pytest.mark.asyncio
async def test_weather_for_day_defaults_to_today() -> None:
    svc = _make_service()
    today = datetime.now(UTC)
    rec = await svc.create_weather(
        WeatherRecordCreate(
            project_id=PROJECT_ID,
            captured_at=today,
            source="manual",
            temperature_c=Decimal("15.0"),
        )
    )
    rows = await svc.weather_for_day(PROJECT_ID, None)
    assert rec.id in [r.id for r in rows]


@pytest.mark.asyncio
async def test_weather_for_day_rejects_bad_date() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.weather_for_day(PROJECT_ID, "not-a-date")
    assert exc.value.status_code == 422
