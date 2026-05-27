# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""R7 audit regressions — daily_diary module.

Pins down the security guarantees the R7 sweep enforces over the daily-
diary surface (53 endpoints, 7 upload-style paths, signed-immutable
contract):

1. **Signed-immutable invariant** — once a diary's status becomes
   ``signed`` (or ``archived``), every mutating operation on the diary,
   its entries, and its photos surfaces 409 with the structured
   ``code=diary_signed_immutable`` / ``entry_signed_immutable`` body.
   The frontend renders these via the i18n dictionary; the message is
   stable across releases.

2. **Unlock endpoint requires MANAGER+** — the new
   ``POST /diaries/{diary_id}/unlock`` route is gated to
   ``daily_diary.unlock`` (MANAGER+). An archived diary cannot be
   unlocked (terminal state); the 409 carries
   ``code=diary_archived_cannot_unlock``.

3. **Magic-byte gate on the EXIF GPS endpoint** — a base64 payload that
   is plainly NOT a real image (PE / ELF / SVG-with-script / random
   bytes) must 415 BEFORE Pillow ever sees it. This is the only daily-
   diary endpoint that accepts inline binary data; all other "uploads"
   are URL-references managed by object storage.

4. **Storage-URL schema validator** — photo / video / drone-ortho /
   point-cloud / reality-capture URLs reject ``javascript:`` and
   ``data:`` schemes at the 422 boundary. The diary UI renders these
   as ``<img>`` / ``<a href>`` links so XSS via a stored URL is the
   active vector.

5. **Geo-tag sanitisation** — lat / lon on photos and weather records
   reject |lat| > 90 / |lon| > 180 with 422. Same schema path that the
   EXIF extractor surfaces back.

6. **Cross-project IDOR** — every diary / entry / photo / video / drone
   / reality-capture GET / PATCH endpoint goes through
   ``verify_project_access(...)`` (which 404s on both missing and
   not-owned). The repository layer is project-scoped; nothing leaks
   diaries from another tenant.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.permissions import Role, permission_registry
from app.database import Base
from app.modules.daily_diary.models import (
    DailyDiary,
    DiaryArchiveSignature,
    DiaryEntry,
    DiaryPhoto,
    DiaryVideo,
    DroneSurvey,
    RealityCaptureDataset,
    WeatherRecord,
)
from app.modules.daily_diary.permissions import register_daily_diary_permissions
from app.modules.daily_diary.schemas import (
    DailyDiaryCreate,
    DailyDiaryUpdate,
    DiaryEntryCreate,
    DiaryPhotoCreate,
    DiaryPhotoUpdate,
    DroneSurveyCreate,
    RealityCaptureCreate,
    WeatherRecordCreate,
)
from app.modules.daily_diary.service import DailyDiaryService

# Import projects + users so the FK targets exist when create_all runs.
from app.modules.projects.models import Project  # noqa: F401
from app.modules.users.models import User  # noqa: F401

_DD_TABLES = [
    Project.__table__,  # FK target for project_id
    User.__table__,  # FK target for site_supervisor_id / signed_by / etc.
    DailyDiary.__table__,
    WeatherRecord.__table__,
    DiaryEntry.__table__,
    DiaryPhoto.__table__,
    DiaryVideo.__table__,
    DroneSurvey.__table__,
    RealityCaptureDataset.__table__,
    DiaryArchiveSignature.__table__,
]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """‌⁠‍Per-test in-memory SQLite session with daily_diary tables only.

    daily_diary models carry FK references to ``oe_projects_project``
    and ``oe_users_user``. We create those parent tables but leave
    SQLite's ``foreign_keys`` pragma OFF so we don't have to seed
    matching parent rows for every diary the test creates. The
    cross-module FK referential integrity is verified by the alembic
    migration tests against PostgreSQL, not here.
    """
    from sqlalchemy import text

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        # Explicit pragma OFF — some sqlite builds default to ON.
        await conn.execute(text("PRAGMA foreign_keys = OFF"))
        await conn.run_sync(Base.metadata.create_all, tables=_DD_TABLES)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        # Re-disable on the per-session connection (PRAGMA is per-conn).
        await sess.execute(text("PRAGMA foreign_keys = OFF"))
        yield sess
        await sess.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> DailyDiaryService:
    return DailyDiaryService(session)


def _today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def _yesterday_iso() -> str:
    return (datetime.now(UTC).date() - timedelta(days=1)).isoformat()


# ── 1. Permission registry (RBAC contract) ──────────────────────────────


def test_daily_diary_unlock_is_manager() -> None:
    """‌⁠‍The new unlock permission must be MANAGER+; EDITOR rejected."""
    register_daily_diary_permissions()
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "daily_diary.unlock",
    )
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "daily_diary.unlock",
    )
    assert not permission_registry.role_has_permission(
        Role.VIEWER,
        "daily_diary.unlock",
    )


def test_daily_diary_sign_is_manager() -> None:
    """‌⁠‍Sign-off remains MANAGER+ (per foreman-class roles)."""
    register_daily_diary_permissions()
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "daily_diary.sign",
    )
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "daily_diary.sign",
    )


# ── 2. Storage-URL schema validator (XSS at the boundary) ────────────────


def test_photo_url_rejects_javascript_scheme() -> None:
    """‌⁠‍``javascript:`` in file_url must 422 at schema parse."""
    with pytest.raises(ValidationError) as exc_info:
        DiaryPhotoCreate(
            project_id=uuid.uuid4(),
            taken_at=datetime.now(UTC),
            file_url="javascript:alert(1)",
        )
    assert "http(s)" in str(exc_info.value)


def test_photo_url_rejects_data_scheme() -> None:
    """‌⁠‍``data:`` URLs equally blocked."""
    with pytest.raises(ValidationError):
        DiaryPhotoCreate(
            project_id=uuid.uuid4(),
            taken_at=datetime.now(UTC),
            file_url="data:image/svg+xml,<svg onload=alert(1)/>",
        )


def test_photo_thumbnail_url_validator_active_on_update() -> None:
    """‌⁠‍PATCH path also runs the URL validator on thumbnail_url."""
    with pytest.raises(ValidationError):
        DiaryPhotoUpdate(thumbnail_url="javascript:bad()")


def test_photo_url_accepts_https() -> None:
    """‌⁠‍Sanity: a valid https URL passes through unchanged."""
    photo = DiaryPhotoCreate(
        project_id=uuid.uuid4(),
        taken_at=datetime.now(UTC),
        file_url="https://cdn.example.com/photo.jpg",
    )
    assert photo.file_url == "https://cdn.example.com/photo.jpg"


def test_photo_url_accepts_relative_minio_path() -> None:
    """‌⁠‍Relative ``/files/...`` paths are allowed (local MinIO mount)."""
    photo = DiaryPhotoCreate(
        project_id=uuid.uuid4(),
        taken_at=datetime.now(UTC),
        file_url="/files/photos/abc.jpg",
    )
    assert photo.file_url == "/files/photos/abc.jpg"


def test_drone_ortho_url_validator_active() -> None:
    """‌⁠‍Drone survey ortho_file_url also subject to XSS gate."""
    with pytest.raises(ValidationError):
        DroneSurveyCreate(
            project_id=uuid.uuid4(),
            flown_at=datetime.now(UTC),
            ortho_file_url="javascript:steal()",
        )


def test_reality_capture_file_url_validator_active() -> None:
    """‌⁠‍Reality-capture file_url cannot be a script URL."""
    with pytest.raises(ValidationError):
        RealityCaptureCreate(
            project_id=uuid.uuid4(),
            captured_at=datetime.now(UTC),
            capture_type="laser_scan",
            file_url="javascript:alert(1)",
        )


# ── 3. Geo-tag sanitisation ──────────────────────────────────────────────


def test_photo_lat_rejects_out_of_range() -> None:
    """‌⁠‍|lat| > 90 must 422 — schema-enforced."""
    with pytest.raises(ValidationError):
        DiaryPhotoCreate(
            project_id=uuid.uuid4(),
            taken_at=datetime.now(UTC),
            file_url="https://cdn.example.com/p.jpg",
            lat=91.0,
            lng=0.0,
        )


def test_photo_lng_rejects_out_of_range() -> None:
    """‌⁠‍|lng| > 180 must 422 — schema-enforced."""
    with pytest.raises(ValidationError):
        DiaryPhotoCreate(
            project_id=uuid.uuid4(),
            taken_at=datetime.now(UTC),
            file_url="https://cdn.example.com/p.jpg",
            lat=0.0,
            lng=200.0,
        )


def test_weather_lat_lng_clamped() -> None:
    """‌⁠‍Weather records also clamp lat/lng to WGS-84 bounds."""
    with pytest.raises(ValidationError):
        WeatherRecordCreate(
            project_id=uuid.uuid4(),
            captured_at=datetime.now(UTC),
            location_lat=-91.0,
            location_lng=0.0,
        )


# ── 4. Signed-immutable invariant ────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_diary_signed_returns_409_with_i18n_code(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Updating a signed diary -> 409 with structured ``code`` body."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    await svc.close_diary(diary.id)
    await svc.sign_diary(diary.id, signer_role="supervisor", signer_name="Bob")

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_diary(diary.id, DailyDiaryUpdate(notes="late edit"))
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "diary_signed_immutable"
    assert detail["status"] == "signed"
    assert detail["diary_id"] == str(diary.id)


@pytest.mark.asyncio
async def test_create_entry_on_signed_diary_returns_409(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Adding an entry to a signed diary -> 409 ``entry_signed_immutable``."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    await svc.close_diary(diary.id)
    await svc.sign_diary(diary.id, signer_role="supervisor")

    with pytest.raises(HTTPException) as exc_info:
        await svc.create_entry(
            DiaryEntryCreate(
                diary_id=diary.id,
                entry_type="visitor",
                entry_time=datetime.now(UTC),
                title="late visitor",
            ),
        )
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "entry_signed_immutable"


@pytest.mark.asyncio
async def test_register_photo_on_signed_diary_returns_409(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Attaching a photo to a signed diary breaks the hash → 409 immutable."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    await svc.close_diary(diary.id)
    await svc.sign_diary(diary.id, signer_role="supervisor")

    with pytest.raises(HTTPException) as exc_info:
        await svc.register_photo(
            DiaryPhotoCreate(
                project_id=project_id,
                diary_id=diary.id,
                taken_at=datetime.now(UTC),
                file_url="https://cdn.example.com/late.jpg",
            ),
        )
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "entry_signed_immutable"


@pytest.mark.asyncio
async def test_delete_photo_on_signed_diary_returns_409(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Deleting a photo from a signed diary is also a hash-breaking edit."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    # Attach a photo while still open.
    photo = await svc.register_photo(
        DiaryPhotoCreate(
            project_id=project_id,
            diary_id=diary.id,
            taken_at=datetime.now(UTC),
            file_url="https://cdn.example.com/early.jpg",
        ),
    )
    # Capture id eagerly — subsequent expire_all calls in close/sign would
    # turn ``photo.id`` into a lazy-load that breaks the sync-context.
    photo_id = photo.id
    await svc.close_diary(diary.id)
    await svc.sign_diary(diary.id, signer_role="supervisor")

    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_photo(photo_id)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "entry_signed_immutable"


@pytest.mark.asyncio
async def test_bulk_entries_on_signed_diary_returns_409(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Bulk insert is also gated by the signed-immutable invariant."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    await svc.close_diary(diary.id)
    await svc.sign_diary(diary.id, signer_role="supervisor")
    payloads = [
        {"entry_type": "visitor", "entry_time": datetime.now(UTC), "title": "B1"},
    ]
    with pytest.raises(HTTPException) as exc_info:
        await svc.bulk_create_entries(diary.id, payloads)
    assert exc_info.value.status_code == 409


# ── 5. Unlock — happy path and archived guard ────────────────────────────


@pytest.mark.asyncio
async def test_unlock_signed_diary_reopens_to_open(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Manager unlock returns the diary to ``open`` while preserving sig."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    await svc.close_diary(diary.id)
    await svc.sign_diary(diary.id, signer_role="supervisor")
    assert diary.status == "signed"

    user_id = str(uuid.uuid4())
    unlocked = await svc.unlock_diary(
        diary.id,
        user_id=user_id,
        reason="late equipment-count amendment",
    )
    assert unlocked.status == "open"

    # Signature row is preserved for forensic audit.
    signatures = await svc.signature_repo.signatures_for_diary(diary.id)
    assert len(signatures) == 1

    # Unlock history written into diary metadata.
    refreshed = await svc.get_diary(diary.id)
    history = (refreshed.metadata_ or {}).get("unlock_history", [])
    assert len(history) == 1
    assert history[0]["unlocked_by"] == user_id
    assert history[0]["previous_status"] == "signed"
    assert history[0]["reason"] == "late equipment-count amendment"


@pytest.mark.asyncio
async def test_unlock_archived_diary_returns_409(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Archived diaries cannot be unlocked — terminal state."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    await svc.close_diary(diary.id)
    await svc.sign_diary(diary.id, signer_role="supervisor")
    await svc.archive_diary(diary.id)

    with pytest.raises(HTTPException) as exc_info:
        await svc.unlock_diary(diary.id, user_id=str(uuid.uuid4()))
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "diary_archived_cannot_unlock"


@pytest.mark.asyncio
async def test_unlock_open_diary_is_idempotent(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Unlocking an already-open diary is a no-op (idempotent)."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    same = await svc.unlock_diary(diary.id, user_id="u-1")
    assert same.status == "open"


# ── 6. EXIF GPS endpoint — magic-byte gate ───────────────────────────────


@pytest.mark.asyncio
async def test_exif_gps_rejects_non_image_payload() -> None:
    """‌⁠‍Random bytes posing as base64 photo -> 415 from the magic-byte gate.

    This is the only daily_diary endpoint that takes inline binary
    data; the guard is essential because the downstream parser (Pillow)
    would otherwise be exercised by every random blob a caller stuffs
    in.
    """
    from app.modules.daily_diary import router as dd_router

    payload = dd_router.ExifGPSRequest(
        image_base64=base64.b64encode(b"this is plainly not an image").decode(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await dd_router.extract_photo_gps(payload, _perm=None)
    assert exc_info.value.status_code == 415


@pytest.mark.asyncio
async def test_exif_gps_rejects_pe_executable() -> None:
    """‌⁠‍A PE-header (Windows .exe) must NOT trick the EXIF endpoint."""
    from app.modules.daily_diary import router as dd_router

    # MZ header + filler.
    pe_bytes = b"MZ\x90\x00" + b"\x00" * 60 + b"PE\x00\x00" + b"\x00" * 256
    payload = dd_router.ExifGPSRequest(
        image_base64=base64.b64encode(pe_bytes).decode(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await dd_router.extract_photo_gps(payload, _perm=None)
    assert exc_info.value.status_code == 415


@pytest.mark.asyncio
async def test_exif_gps_accepts_minimal_png() -> None:
    """‌⁠‍Sanity: a real PNG header passes the magic-byte gate.

    The PNG is too small to actually have GPS EXIF; the endpoint
    returns ``found=False`` — but the important thing is that it gets
    PAST the magic-byte gate without 415.
    """
    from app.modules.daily_diary import router as dd_router

    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
    payload = dd_router.ExifGPSRequest(
        image_base64=base64.b64encode(png_header).decode(),
    )
    result = await dd_router.extract_photo_gps(payload, _perm=None)
    assert result.found is False  # no EXIF in this tiny stub


# ── 7. Cross-project IDOR at the repo layer ─────────────────────────────


@pytest.mark.asyncio
async def test_diary_repo_is_project_scoped(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Listing diaries for project A returns 0 of project B's diaries."""
    proj_a = uuid.uuid4()
    proj_b = uuid.uuid4()
    await svc.create_diary(
        DailyDiaryCreate(project_id=proj_a, diary_date=_yesterday_iso()),
    )
    await svc.create_diary(
        DailyDiaryCreate(project_id=proj_b, diary_date=_yesterday_iso()),
    )
    a_rows, _ = await svc.list_diaries(proj_a)
    b_rows, _ = await svc.list_diaries(proj_b)
    assert len(a_rows) == 1
    assert a_rows[0].project_id == proj_a
    assert len(b_rows) == 1
    assert b_rows[0].project_id == proj_b
    assert all(r.project_id == proj_a for r in a_rows)


@pytest.mark.asyncio
async def test_get_diary_missing_raises_404(svc: DailyDiaryService) -> None:
    """‌⁠‍Unknown diary id -> 404 (not 403, not 500)."""
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_diary(uuid.uuid4())
    assert exc_info.value.status_code == 404


# ── 8. Workforce header counts are bounded ──────────────────────────────


def test_diary_labour_count_clamped_at_10k() -> None:
    """‌⁠‍A single-site daily diary cannot record > 10 000 workers."""
    with pytest.raises(ValidationError):
        DailyDiaryCreate(
            project_id=uuid.uuid4(),
            diary_date=_today_iso(),
            labour_count=10_001,
        )


def test_diary_equipment_count_clamped_at_5k() -> None:
    """‌⁠‍Same clamp for equipment — protects analytics from unit-mistakes."""
    with pytest.raises(ValidationError):
        DailyDiaryCreate(
            project_id=uuid.uuid4(),
            diary_date=_today_iso(),
            equipment_count=5_001,
        )


# ── 9. Unlock restores mutability for entries ───────────────────────────


@pytest.mark.asyncio
async def test_unlock_restores_entry_mutability(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍After unlock, the diary is open again and entries can be added."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    diary_id = diary.id  # capture eagerly
    await svc.close_diary(diary_id)
    await svc.sign_diary(diary_id, signer_role="supervisor")

    # Before unlock: cannot add entry (signed-immutable invariant).
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_entry(
            DiaryEntryCreate(
                diary_id=diary_id,
                entry_type="visitor",
                entry_time=datetime.now(UTC),
                title="late visitor pre-unlock",
            ),
        )
    assert exc_info.value.status_code == 409

    # Unlock.
    await svc.unlock_diary(diary_id, user_id=str(uuid.uuid4()))

    # After unlock: entries CAN be added (open again).
    entry = await svc.create_entry(
        DiaryEntryCreate(
            diary_id=diary_id,
            entry_type="visitor",
            entry_time=datetime.now(UTC),
            title="late visitor post-unlock",
        ),
    )
    assert entry.title == "late visitor post-unlock"

    # The revision-1 signature row is still in the audit log.
    sigs = await svc.signature_repo.signatures_for_diary(diary_id)
    assert len(sigs) >= 1
    assert sigs[0].revision == 1
