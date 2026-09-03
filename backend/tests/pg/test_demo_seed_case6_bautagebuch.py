# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The seeded German Bautagebuch must read as a document, not as filler.

The showcase register is filmed as evidence that holds up in a dispute, so
the properties gated here are the ones a Bauleiter checks first: the days
are days the site was actually open, the text is the site's own language,
"geschlossen" names who closed it and when, and the archived chain carries
a seal that still verifies after the dates were moved back to the site's
own chronology.

Against a real PostgreSQL schema, because the diary carries a unique
constraint on (project_id, diary_date) and the whole point of the seeding
order this gates is that two seeders no longer both write that column.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

#: The showcase project this test impersonates. Frankfurt is the case-6 hero
#: and sits in Hesse, so it also exercises the Land holiday set.
_DEMO_ID = "office-frankfurt"


async def _make_frankfurt(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Create the anchors the showcase seeder keys on, the way the installer does.

    Returns ``(project_id, owner_id)``. The owner is the site supervisor the
    register must name as the closer and signer.
    """
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "bauleitung-tagebuch@reference.example"
    owner = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Reference site lead")
        session.add(owner)
        await session.flush()

    name = "Buerogebaeude Mainufer Bautagebuch"
    project = (await session.execute(select(Project).where(Project.name == name))).scalars().first()
    if project is None:
        project = Project(
            name=name,
            owner_id=owner.id,
            country_code="DE",
            currency="EUR",
            metadata_={"demo_id": _DEMO_ID},
        )
        session.add(project)
        await session.flush()
    await session.flush()
    return uuid.UUID(str(project.id)), uuid.UUID(str(owner.id))


async def _site_photos(session, project_id: uuid.UUID, owner_id: uuid.UUID, count: int = 3) -> list[uuid.UUID]:
    """Commit the project's site photography the diary is meant to reference.

    The Bautagebuch does not copy image files; it points at the ones the photo
    seeder already stored. Without any, the register carries no photos, so the
    photo path would never execute and the case's first blocker (FOTOS 0)
    would go untested.
    """
    from app.modules.documents.models import ProjectPhoto

    ids: list[uuid.UUID] = []
    for index in range(count):
        photo_id = uuid.uuid4()
        session.add(
            ProjectPhoto(
                id=photo_id,
                project_id=project_id,
                filename=f"bautagebuch-{index}.jpg",
                file_path=f"/var/data/photos/bautagebuch-{index}.jpg",
                thumbnail_path=f"/var/data/photos/bautagebuch-{index}_thumb.jpg",
                caption=f"Bewehrung Achse {index + 1}",
                tags=["progress"],
                taken_at=datetime.now(UTC) - timedelta(days=index),
                category="site",
                metadata_={"seed": True},
                created_by=str(owner_id),
            )
        )
        ids.append(photo_id)
    await session.flush()
    return ids


async def _diaries(session, project_id: uuid.UUID):
    from app.modules.daily_diary.models import DailyDiary

    rows = await session.execute(
        select(DailyDiary).where(DailyDiary.project_id == project_id).order_by(DailyDiary.diary_date)
    )
    return list(rows.scalars().all())


async def test_the_register_is_german_working_days_only(pg_session) -> None:
    """No crew is booked on a weekend, a federal holiday or a Hessen holiday.

    The audit found five of ten seeded diaries on days the German site is
    shut, Karfreitag among them. A diary that records seventeen operatives
    on a Sunday argues against the document it is supposed to prove, so the
    calendar is asserted before anything else.
    """
    from app.core.calendar import is_working_day
    from app.modules.daily_diary.seed import _extra_closed_days, seed_daily_diary_showcase_de

    pid, _owner = await _make_frankfurt(pg_session)
    report = await seed_daily_diary_showcase_de(pg_session, [pid])
    assert report["projects"] == 1, f"the showcase seeder skipped its own project: {report}"

    diaries = await _diaries(pg_session, pid)
    assert len(diaries) == report["diaries"] > 0

    days = [date.fromisoformat(d.diary_date) for d in diaries]
    closed_days = _extra_closed_days("HE", {d.year for d in days})
    offenders = [d.isoformat() for d in days if not is_working_day(d, "DE") or d in closed_days]
    assert not offenders, f"the register books a crew on days the site is shut: {offenders}"

    # The module is called "daily", so the window has to be dense and recent:
    # opening it today must not land on an empty calendar.
    today = datetime.now(UTC).date()
    assert (today - days[-1]).days <= 4, f"the newest diary is {days[-1]}, the calendar opens empty on {today}"
    assert (days[-1] - days[0]).days <= 70, "thirty working days should not span more than a quarter"


async def test_the_register_speaks_german_and_carries_entries(pg_session) -> None:
    """German text and real content, not English headers over an empty day.

    The dashboard reported zero entries and zero photos on every project,
    and the largest text in frame was an English sentence with a German
    trade name glued into it.
    """
    from app.modules.daily_diary.models import DiaryEntry
    from app.modules.daily_diary.seed import seed_daily_diary_showcase_de

    pid, owner_id = await _make_frankfurt(pg_session)
    sources = await _site_photos(pg_session, pid, owner_id)
    report = await seed_daily_diary_showcase_de(pg_session, [pid])

    diaries = await _diaries(pg_session, pid)
    notes = " ".join(d.notes or "" for d in diaries)
    assert "Mann auf der Baustelle" in notes, "the header line is not the site's own wording"
    for english in ("operatives", "items of plant", "Day shift record"):
        assert english not in notes, f"English seed wording survived on a German project: {english!r}"

    ids = [d.id for d in diaries]
    entries = list((await pg_session.execute(select(DiaryEntry).where(DiaryEntry.diary_id.in_(ids)))).scalars().all())
    assert len(entries) >= len(diaries), "every diary must carry entries, that is what the module records"
    assert all(e.author_id == owner_id for e in entries), "an entry nobody wrote is not evidence"
    assert any("Behinderung" in (e.description or "") for e in entries), "no disruption is ever recorded"

    # FOTOS 0 was the first line of the audit. The register does not copy
    # image bytes, it points at the project's committed site photography, so
    # what is gated here is that a project which has photos gets them into
    # the diary and that every URL is one the client can actually render.
    from app.modules.daily_diary.models import DiaryPhoto

    photos = list((await pg_session.execute(select(DiaryPhoto).where(DiaryPhoto.diary_id.in_(ids)))).scalars().all())
    assert len(photos) == report["photos"] > 0, "the project has site photography and the register shows none of it"
    served = {f"/api/v1/documents/photos/{sid}/file/" for sid in sources}
    for photo in photos:
        assert photo.file_url in served, f"a diary photo points somewhere the client cannot render: {photo.file_url}"
        assert photo.photographer_id == owner_id
        assert photo.description, "a photo with no caption says nothing in the register"
    # Every source is used, so the pool is cycled rather than sampled from
    # its first row over and over.
    assert {p.file_url for p in photos} == served


async def test_closed_means_somebody_closed_it_and_the_seal_verifies(pg_session) -> None:
    """``closed_by`` names the supervisor, and the archive's hash still checks out.

    Closed diaries used to carry a badge over ``closed_at: null`` and
    ``closed_by: null``. They now go through the service, and the timestamps
    are moved back to the evening of the day itself afterwards. That move is
    only safe because neither field feeds the content hash, so the seal is
    recomputed here from the stored rows rather than trusted.
    """
    from app.modules.daily_diary.models import DiaryArchiveSignature, DiaryEntry, DiaryPhoto
    from app.modules.daily_diary.seed import seed_daily_diary_showcase_de
    from app.modules.daily_diary.service import compute_content_sha256, compute_immutable_payload

    pid, owner_id = await _make_frankfurt(pg_session)
    report = await seed_daily_diary_showcase_de(pg_session, [pid])

    diaries = await _diaries(pg_session, pid)
    closed = [d for d in diaries if d.status in ("closed", "signed", "archived")]
    assert len(closed) == report["closed"] > 0
    for diary in closed:
        assert diary.closed_by == owner_id, f"{diary.diary_date} is closed but nobody closed it"
        assert diary.closed_at is not None
        assert diary.closed_at.date() == date.fromisoformat(diary.diary_date), (
            f"{diary.diary_date} was closed on {diary.closed_at.date()}, which is the seeding day, not the site's"
        )

    assert [d for d in diaries if d.status == "open"], "a live site always has days still open"

    archived = [d for d in diaries if d.status == "archived"]
    assert len(archived) == report["signed"] > 0, "the Archiv tab has to hold something"
    for diary in archived:
        signature = (
            await pg_session.execute(select(DiaryArchiveSignature).where(DiaryArchiveSignature.diary_id == diary.id))
        ).scalar_one()
        assert signature.signed_by == owner_id
        assert signature.signed_at is not None
        assert signature.signed_at.date() == date.fromisoformat(diary.diary_date)
        entries = list(
            (await pg_session.execute(select(DiaryEntry).where(DiaryEntry.diary_id == diary.id))).scalars().all()
        )
        photos = list(
            (await pg_session.execute(select(DiaryPhoto).where(DiaryPhoto.diary_id == diary.id))).scalars().all()
        )
        recomputed = compute_content_sha256(compute_immutable_payload(diary, entries, photos))
        assert recomputed == signature.content_sha256, (
            f"the archived diary {diary.diary_date} no longer matches its own seal"
        )


async def test_the_generic_english_seeder_leaves_the_showcase_alone(pg_session) -> None:
    """The two seeders must not both write ``(project_id, diary_date)``.

    That column pair is unique. The generic seeder used to be blocked by the
    installer's own thin headers and so never ran anywhere; now that it is
    unblocked, the only thing keeping it off the German projects is the
    filter it applies before its own already-seeded guard.
    """
    from app.modules.daily_diary.seed import seed_daily_diary_demo, seed_daily_diary_showcase_de

    pid, _owner = await _make_frankfurt(pg_session)
    generic = await seed_daily_diary_demo(pg_session, [pid])
    assert not generic.get("diaries"), f"the English sprinkle reached a German showcase project: {generic}"

    await seed_daily_diary_showcase_de(pg_session, [pid])
    before = len(await _diaries(pg_session, pid))
    assert before > 0

    # Both seeders re-run on every boot, every pack apply and every forced
    # reinstall. Neither may add a row the second time.
    again = await seed_daily_diary_showcase_de(pg_session, [pid])
    await seed_daily_diary_demo(pg_session, [pid])
    assert again["projects"] == 0, "the showcase seeder does not recognise its own register"
    assert len(await _diaries(pg_session, pid)) == before


async def test_a_project_outside_the_showcase_is_untouched(pg_session) -> None:
    """The German register is scoped by demo id, not by anything ambient."""
    from app.modules.daily_diary.seed import seed_daily_diary_showcase_de
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "site-lead-generic@reference.example"
    owner = (await pg_session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Generic site lead")
        pg_session.add(owner)
        await pg_session.flush()
    project = Project(
        name=f"Ordinary project {uuid.uuid4().hex[:8]}",
        owner_id=owner.id,
        country_code="DE",
        currency="EUR",
        metadata_={"demo_id": "residential-berlin"},
    )
    pg_session.add(project)
    await pg_session.flush()

    report = await seed_daily_diary_showcase_de(pg_session, [uuid.UUID(str(project.id))])
    assert report["projects"] == 0
    assert not await _diaries(pg_session, uuid.UUID(str(project.id)))


async def test_the_showcase_seeder_is_wired_into_the_boot_backfill() -> None:
    """An unreferenced seeder is the bug this module already shipped once.

    Read from the source of the function that owns the list, because the list
    is built inside it from local imports and cannot be inspected as a value.
    """
    import inspect

    from app.core import demo_enrichment

    source = inspect.getsource(demo_enrichment.enrich_projects)
    assert "seed_daily_diary_showcase_de" in source, "the German Bautagebuch seeder is never called"
    assert '"daily_diary_showcase_de"' in source, "the seeder runs but logs its counters as an unknown module"
    # Order matters: the register points at the photo files the photos seeder
    # commits, so a run that signs the archive before those exist seals a
    # diary with no photographic evidence in it.
    assert source.index('("photos"') < source.index('("daily_diary_showcase_de"'), (
        "the Bautagebuch is seeded before the site photography it references"
    )


async def test_the_window_walks_back_over_a_holiday_run() -> None:
    """Thirty working days ending in a holiday week still yields thirty days.

    Guards the bounded walk in ``_german_working_days``: a fixed number of
    calendar steps that runs out mid-window would silently return a short
    register, and a short register reads as a site that stopped working.
    """
    from app.core.calendar import is_working_day
    from app.modules.daily_diary.seed import _extra_closed_days, _german_working_days

    for land in ("HE", "BW"):
        days = _german_working_days(date(2026, 12, 30), 30, land=land)
        assert len(days) == 30, f"{land}: the walk ran out over the Christmas break, got {len(days)}"
        closed = _extra_closed_days(land, {d.year for d in days})
        assert all(is_working_day(d, "DE") and d not in closed for d in days)
        assert days == sorted(days), "the window must read oldest first"
        assert days[-1] <= date(2026, 12, 30)
        assert date(2026, 12, 24) not in days, "Heiligabend is not a site day"
        assert (days[-1] - days[0]) < timedelta(days=90)
