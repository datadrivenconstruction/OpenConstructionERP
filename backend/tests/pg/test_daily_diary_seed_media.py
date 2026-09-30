# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Demo diary media must point at files that exist.

The generic diary seeder used to write every photo as
``https://seed.local/photos/<uuid>.jpg``. That host does not exist, so on
every install each of the thousand demo diary photos rendered as a broken
image, and the report that reached the founder was "many images in the
platform do not show". Project photos themselves were fine; only the diary
pointed at nothing.

These tests hold both halves of the fix: a fresh seed references the
project's real site photos (and seeds no media it has no file for), and the
boot-time repair re-points the rows an earlier seed already wrote, because
the seeder guards per project and never runs twice on its own.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core import demo_enrichment
from app.modules.daily_diary.models import DailyDiary, DiaryPhoto, DiaryVideo, DroneSurvey
from app.modules.daily_diary.seed import repair_seeded_diary_media, seed_daily_diary_demo
from app.modules.documents.models import ProjectPhoto
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

_BASE = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)


async def _make_project(session, name: str) -> tuple[uuid.UUID, uuid.UUID]:
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{name.lower().replace(' ', '-')}-{owner_id.hex[:6]}@example.test",
            hashed_password="x",
            full_name=f"{name} Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Diary media fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await session.flush()
    return project_id, owner_id


async def _site_photos(session, project_id: uuid.UUID, owner_id: uuid.UUID, count: int = 3) -> set[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    for index in range(count):
        photo_id = uuid.uuid4()
        session.add(
            ProjectPhoto(
                id=photo_id,
                project_id=project_id,
                filename=f"site-{index}.jpg",
                file_path=f"/var/data/photos/site-{index}.jpg",
                thumbnail_path=f"/var/data/photos/site-{index}_thumb.jpg",
                caption=f"Slab pour bay {index + 1}",
                tags=["progress"],
                taken_at=datetime.now(UTC) - timedelta(days=index),
                category="site",
                metadata_={"seed": True},
                created_by=str(owner_id),
            )
        )
        ids.add(photo_id)
    await session.flush()
    return ids


def _source_id(url: str) -> uuid.UUID:
    # /api/v1/documents/photos/<id>/file/
    return uuid.UUID(url.rstrip("/").split("/")[-2])


async def _diary_photos(session, project_id: uuid.UUID) -> list[DiaryPhoto]:
    rows = await session.execute(select(DiaryPhoto).where(DiaryPhoto.project_id == project_id))
    return list(rows.scalars().all())


async def test_seeded_diary_photos_reference_the_projects_real_photos(pg_session) -> None:
    project_id, owner_id = await _make_project(pg_session, "Diary Media")
    real = await _site_photos(pg_session, project_id, owner_id)

    counts = await seed_daily_diary_demo(pg_session, [project_id], base_date=_BASE)

    photos = await _diary_photos(pg_session, project_id)
    assert photos, "a project with site photos got no diary photos"
    assert counts["photos"] == len(photos)
    for photo in photos:
        assert photo.file_url.startswith("/api/v1/documents/photos/"), photo.file_url
        assert photo.thumbnail_url and photo.thumbnail_url.endswith("/thumb/")
        assert _source_id(photo.file_url) in real, "a diary photo points at a photo the project does not have"
        assert photo.is_360 is False, "an ordinary photo was flagged as a 360 panorama"
    videos = (await pg_session.execute(select(DiaryVideo).where(DiaryVideo.project_id == project_id))).scalars()
    assert not list(videos), "videos were seeded with no footage behind them"
    surveys = (await pg_session.execute(select(DroneSurvey).where(DroneSurvey.project_id == project_id))).scalars()
    for survey in surveys:
        assert survey.ortho_file_url is None and survey.dsm_file_url is None


async def test_a_project_without_site_photos_gets_none_rather_than_broken_ones(pg_session) -> None:
    project_id, _owner = await _make_project(pg_session, "Diary No Photos")

    counts = await seed_daily_diary_demo(pg_session, [project_id], base_date=_BASE)

    assert counts.get("diaries", 0) > 0, "the register itself must still be seeded"
    assert await _diary_photos(pg_session, project_id) == []


async def test_the_repair_repoints_placeholders_and_leaves_real_uploads_alone(pg_session) -> None:
    project_id, owner_id = await _make_project(pg_session, "Diary Repair")
    real = await _site_photos(pg_session, project_id, owner_id, count=2)
    bare_id, _ = await _make_project(pg_session, "Diary Repair Bare")

    diary = DailyDiary(project_id=project_id, diary_date="2026-05-04", metadata_={"seed": True})
    bare_diary = DailyDiary(project_id=bare_id, diary_date="2026-05-04", metadata_={"seed": True})
    pg_session.add_all([diary, bare_diary])
    await pg_session.flush()

    def _photo(pid: uuid.UUID, diary_id: uuid.UUID, url: str) -> DiaryPhoto:
        return DiaryPhoto(
            diary_id=diary_id,
            project_id=pid,
            taken_at=_BASE,
            file_url=url,
            mime_type="image/jpeg",
            description="Seed photo",
            tags=[],
            is_360=True,
        )

    placeholders = [_photo(project_id, diary.id, f"https://seed.local/photos/{uuid.uuid4()}.jpg") for _ in range(3)]
    upload = _photo(project_id, diary.id, "/api/v1/documents/photos/00000000-0000-0000-0000-000000000001/file/")
    orphan = _photo(bare_id, bare_diary.id, f"https://seed.local/photos/{uuid.uuid4()}.jpg")
    video = DiaryVideo(
        diary_id=diary.id,
        project_id=project_id,
        recorded_at=_BASE,
        file_url=f"https://seed.local/videos/{uuid.uuid4()}.mp4",
        tags=[],
    )
    pg_session.add_all([*placeholders, upload, orphan, video])
    await pg_session.flush()

    counts = await repair_seeded_diary_media(pg_session, [project_id, bare_id])

    assert counts["photos_repointed"] == 3
    assert counts["photos_removed"] == 1
    assert counts["videos_removed"] == 1
    for photo in placeholders:
        await pg_session.refresh(photo)
        assert _source_id(photo.file_url) in real
        assert photo.is_360 is False
        assert photo.description != "Seed photo", "the caption of the real photo was not carried over"
    await pg_session.refresh(upload)
    assert upload.file_url.endswith("0001/file/"), "a row that was not a placeholder was rewritten"
    assert upload.is_360 is True
    assert await _diary_photos(pg_session, bare_id) == []

    again = await repair_seeded_diary_media(pg_session, [project_id, bare_id])
    assert sum(again.values()) == 0, "the repair is not idempotent, it would churn on every boot"


async def test_the_boot_backfill_seeds_photos_before_the_diary_and_repairs_after() -> None:
    source = inspect.getsource(demo_enrichment)
    photos = source.index('("photos", None')
    diary = source.index('("daily_diary", None')
    repair = source.index('("daily_diary_media", None')
    assert photos < diary < repair, (
        "diary photos reference the site photos, so the photo seeder must run first "
        "and the repair of older rows after both"
    )
