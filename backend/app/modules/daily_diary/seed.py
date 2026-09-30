# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deterministic demo seed for the daily-diary module.

Usage::

    from app.modules.daily_diary.seed import seed_daily_diary_demo
    await seed_daily_diary_demo(session, project_ids=[uuid1, uuid2, uuid3])

Designed for the demo / QA dataset: produces 90 days of diaries per
project with realistic weather, entries, photos (drawn from the project's
real site photos), drone surveys and reality-capture datasets. No videos:
there is no bundled footage to point them at.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from dateutil.easter import easter  # type: ignore[import]
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.calendar import is_working_day
from app.core.demo_showcase import GERMAN_SHOWCASE_DEMO_IDS
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
from app.modules.daily_diary.service import (
    DailyDiaryService,
    compute_content_sha256,
    compute_immutable_payload,
)
from app.modules.projects.models import Project
from app.modules.users.models import User

logger = logging.getLogger(__name__)

_DAYS = 90
_WEATHER_PER_DIARY = 5
_ENTRIES_PER_DIARY = 8
_PHOTOS_TOTAL = 1000
_DRONE_SURVEYS = 6
_REALITY_CAPTURES = 2

# What the seed writes on rows that carry no seed mark of their own. The
# cleanup of real projects (``seeded_child_ids``) recognises the rows by these,
# so they are read from here by both sides rather than written twice.
_SUNRISE = "06:30:00"
_SUNSET = "20:15:00"
_DRONE_NOTE = "Seed drone survey"
_DRONE_URL = "https://seed.local/drone/"
_REALITY_NOTE = "Seed reality capture"
_REALITY_URL = "https://seed.local/reality/"

# Realistic-ish lat/lng centres (Berlin, Frankfurt, Munich)
_DEFAULT_CENTRES: tuple[tuple[float, float], ...] = (
    (52.5200, 13.4050),
    (50.1109, 8.6821),
    (48.1351, 11.5820),
)

_WEATHER_CONDITIONS: tuple[tuple[str, str], ...] = (
    ("clear", "Clear sky"),
    ("cloudy", "Partly cloudy"),
    ("rain", "Light rain"),
    ("overcast", "Overcast"),
    ("snow", "Light snow"),
)

_ENTRY_TYPES: tuple[str, ...] = (
    "visitor",
    "event",
    "delivery",
    "completion",
    "incident_summary",
    "inspection_summary",
    "photo_note",
    "general",
)

_DRONE_MODELS: tuple[str, ...] = (
    "Compact survey quadcopter (RTK)",
    "Heavy-lift survey drone (RTK)",
    "Foldable inspection drone (4G)",
    "Wide-sensor mapping drone (RTK)",
)

_CAPTURE_TYPES: tuple[str, ...] = ("laser_scan", "photogrammetry", "mobile_scan")


async def seed_daily_diary_demo(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
    *,
    base_date: datetime | None = None,
    deterministic_seed: int = 42,
) -> dict[str, int]:
    """Populate the daily-diary tables with deterministic demo data.

    Args:
        session: Async SQLAlchemy session, will be flushed but **not** committed.
        project_ids: Projects to seed against (≥1).
        base_date: Anchor date for the synthetic 90-day window. Defaults to "now".
        deterministic_seed: Random seed for reproducibility.

    Returns:
        Counters per entity inserted.
    """
    if not project_ids:
        return {}

    # The German showcase projects carry a hand-authored German Bautagebuch
    # (seed_daily_diary_showcase_de) instead of this generic English one.
    # Filtered before the already-seeded guard on purpose, the same way the
    # variations sprinkle does it: German diaries on those projects must not
    # read as "the sprinkle already ran" for the rest of the estate.
    project_ids = await _without_german_showcase(session, list(project_ids))
    if not project_ids:
        return {}

    # Ninety days of diaries per project is not something to add twice. The
    # boot backfill re-runs this on every start, so the guard is per project
    # rather than a table-wide count: users write diaries too, and one real
    # entry would otherwise stop the demo seed reaching the projects that are
    # still empty.
    #
    # What the guard asks matters more than that it exists. "Does this project
    # hold a diary" was the wrong question. The demo installer writes a handful
    # of empty English headers of its own before this runs, so every project
    # answered yes and this seeder reached none of them - the rich diary was
    # written, tested and never once inserted. The question is "did I write
    # it", and the writers are told apart by the marks they leave:
    # ``metadata_["seed"]`` is this seeder and its showcase sibling,
    # ``metadata_["demo_id"]`` is the installer. A row carrying neither is a
    # real diary and still stops the project cold, which is the whole point of
    # having a guard.
    #
    # Compared as strings on both sides. The id column is a text-backed GUID
    # that reads back as a uuid.UUID, and callers hand this function whichever
    # of the two they happen to hold, so comparing the raw values would let the
    # guard silently never match and duplicate the whole seed on every boot.
    _rows = (
        await session.execute(
            select(DailyDiary.id, DailyDiary.project_id, DailyDiary.metadata_).where(
                DailyDiary.project_id.in_(list(project_ids))
            )
        )
    ).all()
    seeded: set[str] = set()
    installer_headers: dict[str, list] = {}
    for _row_id, _pid, _marks in _rows:
        _key = str(_pid)
        _mark = _marks or {}
        if _mark.get("demo_id") and not _mark.get("seed"):
            installer_headers.setdefault(_key, []).append(_row_id)
        else:
            seeded.add(_key)

    # Drop the installer's placeholders on the projects that are about to get
    # the real thing. They are this install's own rows rather than anybody's
    # work, and (project_id, diary_date) is unique, so a header left standing
    # inside the ninety-day window would collide with the day being written.
    # Projects that are being skipped keep theirs: a project this seeder does
    # not fill must not come out emptier than it went in.
    _doomed = [row_id for pid, rows in installer_headers.items() if pid not in seeded for row_id in rows]
    if _doomed:
        await session.execute(delete(DailyDiary).where(DailyDiary.id.in_(_doomed)))
        await session.flush()

    rng = random.Random(deterministic_seed)
    base = base_date or datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)

    diaries: list[DailyDiary] = []
    weather_records: list[WeatherRecord] = []
    entries: list[DiaryEntry] = []
    photos: list[DiaryPhoto] = []
    videos: list[DiaryVideo] = []
    drone_surveys: list[DroneSurvey] = []
    reality_captures: list[RealityCaptureDataset] = []
    signatures: list[DiaryArchiveSignature] = []

    diary_index: dict[tuple[uuid.UUID, str], DailyDiary] = {}

    photo_pool_remaining = _PHOTOS_TOTAL
    drone_pool_remaining = _DRONE_SURVEYS
    reality_pool_remaining = _REALITY_CAPTURES

    for project_idx, project_id in enumerate(project_ids):
        if str(project_id) in seeded:
            continue
        centre = _DEFAULT_CENTRES[project_idx % len(_DEFAULT_CENTRES)]
        lat0, lng0 = centre

        for day_offset in range(_DAYS):
            day = base - timedelta(days=_DAYS - day_offset - 1)
            diary_date = day.date().isoformat()

            # Status mix: oldest 60 days archived/signed, middle 20 closed, latest 10 open.
            if day_offset < _DAYS - 30:
                status = rng.choice(["archived", "signed"])
            elif day_offset < _DAYS - 10:
                status = "closed"
            else:
                status = "open"

            diary = DailyDiary(
                id=uuid.uuid4(),
                project_id=project_id,
                diary_date=diary_date,
                site_supervisor_id=None,
                weather_summary={
                    "conditions": rng.choice(_WEATHER_CONDITIONS)[0],
                    "temp_c": round(rng.uniform(-5, 35), 1),
                },
                labour_count=rng.randint(8, 80),
                equipment_count=rng.randint(2, 25),
                status=status,
                notes=f"Day shift record for {diary_date}.",
                closed_at=day if status != "open" else None,
                metadata_={"seed": True, "seed_revision": 1},
            )
            diaries.append(diary)
            diary_index[(project_id, diary_date)] = diary

            for w in range(_WEATHER_PER_DIARY):
                conditions = rng.choice(_WEATHER_CONDITIONS)
                weather_records.append(
                    WeatherRecord(
                        id=uuid.uuid4(),
                        project_id=project_id,
                        captured_at=day + timedelta(hours=w * 4),
                        source=rng.choice(["open_meteo", "manual", "sensor"]),
                        temperature_c=Decimal(str(round(rng.uniform(-10, 38), 2))),
                        humidity_pct=Decimal(str(round(rng.uniform(20, 99), 2))),
                        wind_speed_kmh=Decimal(str(round(rng.uniform(0, 60), 2))),
                        precipitation_mm=Decimal(str(round(rng.uniform(0, 25), 2))),
                        conditions_code=conditions[0],
                        conditions_text=conditions[1],
                        sunrise=_SUNRISE,
                        sunset=_SUNSET,
                        location_lat=lat0,
                        location_lng=lng0,
                    )
                )

            for e in range(_ENTRIES_PER_DIARY):
                entry_type = _ENTRY_TYPES[e % len(_ENTRY_TYPES)]
                entries.append(
                    DiaryEntry(
                        id=uuid.uuid4(),
                        diary_id=diary.id,
                        entry_type=entry_type,
                        entry_time=day + timedelta(hours=8 + e),
                        title=f"{entry_type.replace('_', ' ').title()} #{e + 1}",
                        description=f"{entry_type.replace('_', ' ').capitalize()} recorded on {diary_date}.",
                        source_module=rng.choice([None, "hse", "procurement", "quality", "schedule"]),
                        source_ref=None,
                        author_id=None,
                        photo_ids=[],
                        metadata_={"labour_count": rng.randint(0, 5)},
                    )
                )

        if status_in_archived := True:  # noqa: E712
            # Add archive signatures for archived/signed diaries
            for (pid, d_date), diary in diary_index.items():
                if pid != project_id:
                    continue
                if diary.status in ("signed", "archived"):
                    diary_entries = [e for e in entries if e.diary_id == diary.id]
                    payload = compute_immutable_payload(diary, diary_entries, [])
                    signatures.append(
                        DiaryArchiveSignature(
                            id=uuid.uuid4(),
                            diary_id=diary.id,
                            content_sha256=compute_content_sha256(payload),
                            signed_at=base,
                            signed_by=None,
                            signature_payload={
                                "algorithm": "sha256",
                                "signer_role": "supervisor",
                                "signer_name": "Seed Bot",
                                "signature_data": None,
                            },
                            revision=1,
                        )
                    )

    # Photos - distribute pool roughly evenly across all diaries.
    #
    # Every photo points at a real site photo already on the project, served
    # by the documents photo routes, exactly as the German showcase diary
    # does. This used to write ``https://seed.local/photos/<uuid>.jpg``: a
    # host that does not exist, so each of the thousand demo diary photos
    # rendered as a broken image and the founder reported the platform's
    # images as missing. A project with no site photos gets no diary photos,
    # a thinner frame but never a broken one. The photo seeder therefore runs
    # before this one (see ``app.core.demo_enrichment``).
    diary_list = list(diary_index.values())
    photo_pools: dict[uuid.UUID, list[tuple[uuid.UUID, str | None]]] = {}
    for diary in diary_list:
        if diary.project_id not in photo_pools:
            photo_pools[diary.project_id] = await _showcase_photo_pool(session, diary.project_id)
    photo_diaries = [diary for diary in diary_list if photo_pools.get(diary.project_id)]
    if photo_diaries:
        for n in range(photo_pool_remaining):
            diary = rng.choice(photo_diaries)
            pool = photo_pools[diary.project_id]
            source_id, caption = pool[n % len(pool)]
            lat_centre, lng_centre = _DEFAULT_CENTRES[list(project_ids).index(diary.project_id) % len(_DEFAULT_CENTRES)]
            jitter_lat = rng.uniform(-0.001, 0.001)
            jitter_lng = rng.uniform(-0.001, 0.001)
            day_dt = datetime.fromisoformat(diary.diary_date + "T12:00:00").replace(tzinfo=UTC)
            photos.append(
                DiaryPhoto(
                    id=uuid.uuid4(),
                    diary_id=diary.id,
                    project_id=diary.project_id,
                    taken_at=day_dt + timedelta(minutes=rng.randint(-600, 600)),
                    photographer_id=None,
                    lat=lat_centre + jitter_lat,
                    lng=lng_centre + jitter_lng,
                    location_label=rng.choice(["Block A", "Block B", "Crane Pad", "Site Office"]),
                    file_url=f"/api/v1/documents/photos/{source_id}/file/",
                    thumbnail_url=f"/api/v1/documents/photos/{source_id}/thumb/",
                    mime_type="image/jpeg",
                    description=caption or "Site photo",
                    tags=rng.sample(["progress", "safety", "quality", "concrete"], k=2),
                    # Ordinary flat photos: flagging one as 360 would open it
                    # in the spherical viewer as a smeared panorama, and
                    # flagging it as drone would claim an aerial it is not.
                    is_360=False,
                    is_drone=False,
                )
            )

    # No demo videos. There is no bundled footage to point them at, and a
    # player aimed at an invented URL is a broken control, not a demo.

    for project_idx, project_id in enumerate(project_ids):
        if str(project_id) in seeded:
            continue
        for d in range(drone_pool_remaining // max(len(project_ids), 1)):
            drone_surveys.append(
                DroneSurvey(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    flown_at=base - timedelta(days=rng.randint(0, _DAYS - 1)),
                    pilot_name=f"Pilot {project_idx}.{d}",
                    drone_model=rng.choice(_DRONE_MODELS),
                    area_m2=Decimal(str(round(rng.uniform(500, 50_000), 2))),
                    # No bundled orthophoto or elevation model to link, so
                    # none is claimed; the survey record itself stays.
                    ortho_file_url=None,
                    dsm_file_url=None,
                    point_cloud_url=None,
                    elevation_min_m=Decimal(str(round(rng.uniform(0, 50), 2))),
                    elevation_max_m=Decimal(str(round(rng.uniform(50, 150), 2))),
                    notes=_DRONE_NOTE,
                )
            )
        for r in range(reality_pool_remaining // max(len(project_ids), 1) + 1):
            reality_captures.append(
                RealityCaptureDataset(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    captured_at=base - timedelta(days=rng.randint(0, _DAYS - 1)),
                    capture_type=rng.choice(_CAPTURE_TYPES),
                    file_url=f"{_REALITY_URL}{uuid.uuid4()}.e57",
                    point_count_estimate=rng.randint(1_000_000, 200_000_000),
                    bbox_min={"x": 0.0, "y": 0.0, "z": 0.0},
                    bbox_max={"x": 100.0, "y": 100.0, "z": 25.0},
                    accuracy_mm=Decimal(str(round(rng.uniform(1, 25), 2))),
                    notes=_REALITY_NOTE,
                )
            )

    session.add_all(diaries)
    session.add_all(weather_records)
    session.add_all(entries)
    session.add_all(photos)
    session.add_all(videos)
    session.add_all(drone_surveys)
    session.add_all(reality_captures)
    session.add_all(signatures)
    await session.flush()

    return {
        "diaries": len(diaries),
        "weather_records": len(weather_records),
        "entries": len(entries),
        "photos": len(photos),
        "videos": len(videos),
        "drone_surveys": len(drone_surveys),
        "reality_captures": len(reality_captures),
        "signatures": len(signatures),
    }


# ── Repair of media written by earlier versions of the seeder ────────────────

#: The host earlier versions of ``seed_daily_diary_demo`` invented for its
#: media. Nothing but that seeder ever wrote it, so a row carrying it is a
#: seeded placeholder and never a user's upload.
_PLACEHOLDER_MEDIA_PREFIX = "https://seed.local/"


async def repair_seeded_diary_media(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
) -> dict[str, int]:
    """Point earlier demo diary media at real files, or remove what has none.

    Fixing the seeder alone changes nothing on an install that already ran
    it: the seeder guards per project and never runs twice, so those diaries
    keep a thousand photos aimed at a host that does not exist. This runs on
    every boot and touches only rows whose URL starts with
    ``_PLACEHOLDER_MEDIA_PREFIX``, so once they are repaired it finds nothing
    and changes nothing; the cost is one project-scoped scan per table.

    Photos are re-pointed at the project's real site photos, the same pool the
    seeder now draws from; a project without site photos loses the
    placeholder rows instead. Videos have no real footage to point at and are
    removed. Drone surveys keep their record and lose the invented file links.

    Args:
        session: Async SQLAlchemy session, flushed but not committed.
        project_ids: Projects to repair.

    Returns:
        Counters for what was re-pointed, removed and cleared.
    """
    counts = {"photos_repointed": 0, "photos_removed": 0, "videos_removed": 0, "drone_links_cleared": 0}
    if not project_ids:
        return counts
    pids = list(project_ids)
    like = f"{_PLACEHOLDER_MEDIA_PREFIX}%"

    placeholder_photos = (
        (
            await session.execute(
                select(DiaryPhoto)
                .where(DiaryPhoto.project_id.in_(pids), DiaryPhoto.file_url.like(like))
                .order_by(DiaryPhoto.taken_at, DiaryPhoto.id)
            )
        )
        .scalars()
        .all()
    )
    pools: dict[uuid.UUID, list[tuple[uuid.UUID, str | None]]] = {}
    doomed_photos: list[uuid.UUID] = []
    for n, photo in enumerate(placeholder_photos):
        if photo.project_id not in pools:
            pools[photo.project_id] = await _showcase_photo_pool(session, photo.project_id)
        pool = pools[photo.project_id]
        if not pool:
            doomed_photos.append(photo.id)
            continue
        source_id, caption = pool[n % len(pool)]
        photo.file_url = f"/api/v1/documents/photos/{source_id}/file/"
        photo.thumbnail_url = f"/api/v1/documents/photos/{source_id}/thumb/"
        photo.mime_type = "image/jpeg"
        photo.is_360 = False
        photo.is_drone = False
        if photo.description == "Seed photo" and caption:
            photo.description = caption
        counts["photos_repointed"] += 1
    if doomed_photos:
        await session.execute(delete(DiaryPhoto).where(DiaryPhoto.id.in_(doomed_photos)))
        counts["photos_removed"] = len(doomed_photos)

    videos = await session.execute(
        delete(DiaryVideo).where(DiaryVideo.project_id.in_(pids), DiaryVideo.file_url.like(like))
    )
    counts["videos_removed"] = videos.rowcount or 0

    surveys = (
        (
            await session.execute(
                select(DroneSurvey).where(
                    DroneSurvey.project_id.in_(pids),
                    (DroneSurvey.ortho_file_url.like(like)) | (DroneSurvey.dsm_file_url.like(like)),
                )
            )
        )
        .scalars()
        .all()
    )
    for survey in surveys:
        if (survey.ortho_file_url or "").startswith(_PLACEHOLDER_MEDIA_PREFIX):
            survey.ortho_file_url = None
        if (survey.dsm_file_url or "").startswith(_PLACEHOLDER_MEDIA_PREFIX):
            survey.dsm_file_url = None
        counts["drone_links_cleared"] += 1

    await session.flush()
    return counts


# ── German showcase Bautagebuch ──────────────────────────────────────────────

_SHOWCASE_WORKING_DAYS = 30
_SHOWCASE_ARCHIVED = 10  # oldest, carried through close -> sign -> archive
_SHOWCASE_CLOSED = 12  # middle, closed by the named Bauleiter
_SHOWCASE_ENTRIES = 4
_SHOWCASE_WEATHER = 3
_SHOWCASE_PHOTOS = 2
_SHOWCASE_MARKER = "daily_diary_showcase_de"

#: Land the project sits in. Germany's public holidays are federal plus
#: per-Land, and a diary that books a full crew on a day the Land is closed
#: is the document arguing against itself.
_SHOWCASE_LAND: dict[str, str] = {
    "office-frankfurt": "HE",
    "retail-market-heidelberg": "BW",
    "retail-market-karlsruhe": "BW",
    "retail-market-heilbronn": "BW",
}

#: ``(code, German label, the header sentence the site writes)``. The code is
#: what the UI translates; the German text is the site's own wording, which is
#: the thing the diary is evidence of.
_DE_WEATHER: tuple[tuple[str, str, str], ...] = (
    ("clear", "Klar", "Trocken und klar, voller Arbeitstag."),
    ("cloudy", "Teilweise bewölkt", "Teilweise bewölkt, kein Einfluss auf die Leistung."),
    ("overcast", "Bedeckt", "Bedeckt, Arbeiten planmäßig fortgeführt."),
    ("rain", "Leichter Regen", "Zeitweise Regen, Außenarbeiten am Nachmittag unterbrochen."),
)

#: Long-run monthly means for southern and central Germany, in °C, January
#: first. The window walks backwards from today, so a diary seeded in
#: February must not read 21 °C.
_DE_MONTHLY_TEMP_C: tuple[int, ...] = (2, 3, 7, 11, 15, 19, 21, 20, 16, 11, 6, 3)

_DE_TRADES: tuple[str, ...] = (
    "Rohbau",
    "Bewehrung",
    "Betonarbeiten",
    "Schalung",
    "Dachabdichtung",
    "Trockenbau",
    "Elektroinstallation",
    "Heizung und Sanitär",
    "Fassade",
    "Estrich",
)

_DE_ACTIVITIES: tuple[str, ...] = (
    "Achse C bis E ausgeführt und aufgemessen",
    "Abschnitt planmäßig fertiggestellt",
    "Vorleistung des Vorgewerks abgenommen",
    "Anlieferung geprüft und eingelagert",
    "Folgegewerk hinter der führenden Kolonne aufgenommen",
)

#: ``(entry_type, Titel, Beschreibung)``. ``entry_type`` must stay inside the
#: module's own vocabulary (``_ENTRY_TYPE_RE`` in schemas.py) or the register
#: holds values its own editor cannot offer back.
_DE_ENTRIES: tuple[tuple[str, str, str], ...] = (
    (
        "delivery",
        "Materiallieferung",
        "Anlieferung {trade}, Lieferschein {ref} geprüft und gegengezeichnet.",
    ),
    (
        "inspection_summary",
        "Zwischenabnahme",
        "{trade}: Zwischenabnahme durch die Bauleitung, Ausführung freigegeben.",
    ),
    (
        "completion",
        "Teilfertigstellung",
        "{trade}: {activity}.",
    ),
    (
        "visitor",
        "Besuch auf der Baustelle",
        "Vertreter des Auftraggebers zur Begehung auf der Baustelle, Rundgang protokolliert.",
    ),
    (
        "event",
        "Baubesprechung",
        "Wöchentliche Baubesprechung, Protokoll {ref} an alle Beteiligten versandt.",
    ),
    (
        "incident_summary",
        "Behinderungsanzeige",
        "Witterungsbedingter Ausfall, Außenarbeiten unterbrochen, Behinderung schriftlich angezeigt.",
    ),
    (
        "photo_note",
        "Fotodokumentation",
        "{trade}: Bauzustand vor dem Schließen der Schalung fotografisch dokumentiert.",
    ),
    (
        "general",
        "Tagesleistung",
        "{trade}: Tagesleistung aufgemessen und in den Aufmaßblättern erfasst.",
    ),
)

_DE_PHOTO_PLACES: tuple[str, ...] = (
    "Bauabschnitt A",
    "Bauabschnitt B",
    "Kranstellfläche",
    "Baustelleneinrichtung",
)


def _extra_closed_days(land: str, years: Iterable[int]) -> frozenset[date]:
    """Days a German site is closed beyond the federal calendar.

    ``app.core.calendar`` carries the holidays common to all sixteen Länder.
    Two things sit on top of it. The Land adds its own statutory holidays,
    and the showcase spans Hesse and Baden-Württemberg. Heiligabend and
    Silvester are not statutory anywhere, but a site that books a full crew
    on 24 December is a document nobody believes, so they are treated as
    closed here as well.
    """
    out: set[date] = set()
    for year in years:
        fronleichnam = easter(year) + timedelta(days=60)
        if land == "HE":
            out.add(fronleichnam)
        elif land == "BW":
            out.add(date(year, 1, 6))  # Heilige Drei Könige
            out.add(fronleichnam)
            out.add(date(year, 11, 1))  # Allerheiligen
        out.add(date(year, 12, 24))  # Heiligabend
        out.add(date(year, 12, 31))  # Silvester
    return frozenset(out)


def _german_working_days(end: date, count: int, *, land: str) -> list[date]:
    """The last ``count`` German working days ending at or before ``end``.

    Weekends and public holidays are skipped, so the register never books a
    crew on a Sunday or on Karfreitag. Returned oldest first.
    """
    extra = _extra_closed_days(land, {end.year, (end - timedelta(days=365)).year})
    days: list[date] = []
    cursor = end
    # A worst case of a fortnight of holidays either side of the window still
    # fits inside three times the working days asked for.
    for _ in range(count * 3 + 30):
        if len(days) == count:
            break
        if is_working_day(cursor, "DE") and cursor not in extra:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


async def _without_german_showcase(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """Drop the projects whose Bautagebuch is hand-authored in German."""
    if not project_ids:
        return []
    rows = await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(project_ids)))
    showcase: set[uuid.UUID] = set()
    for pid, meta in rows.all():
        demo_id = str(meta.get("demo_id") or "").strip() if isinstance(meta, dict) else ""
        if demo_id in GERMAN_SHOWCASE_DEMO_IDS:
            showcase.add(pid)
    return [pid for pid in project_ids if pid not in showcase]


async def _showcase_photo_pool(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[tuple[uuid.UUID, str | None]]:
    """Site photos already on the project, as ``(id, caption)``.

    The diary references the bytes the photo seeder committed rather than
    copying them again: ``DiaryPhoto.file_url`` is a URL the client renders
    through ``AuthImage``, and ``/api/v1/documents/photos/{id}/file/`` is the
    route that already serves those files. An install without the bundled
    assets returns nothing here and the diaries carry no photos, which is a
    thinner frame but never a broken image.
    """
    try:
        from app.modules.documents.models import ProjectPhoto
    except Exception:  # pragma: no cover - documents module not installed
        return []
    rows = await session.execute(
        select(ProjectPhoto.id, ProjectPhoto.caption)
        .where(ProjectPhoto.project_id == project_id)
        .order_by(ProjectPhoto.taken_at)
        .limit(60)
    )
    return [(pid, caption) for pid, caption in rows.all()]


async def seed_daily_diary_showcase_de(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
) -> dict[str, int]:
    """Hand-authored German Bautagebuch for the German showcase projects.

    For every demo project whose ``demo_id`` is in
    :data:`~app.core.demo_showcase.GERMAN_SHOWCASE_DEMO_IDS`, writes thirty
    consecutive German working days ending today: German entry text, weather
    the site would have had for the month, four entries a day, photos taken
    from the project's own committed site photography, and a status ladder
    that ends in a signed and archived chain.

    Three properties matter more than volume, because this register is the
    one filmed as a document that holds up in a dispute:

    * Only working days. Weekends, federal holidays and the Land's own
      holidays are skipped, so no crew is booked on Karfreitag or a Sunday.
    * Closed means somebody closed it. The transitions run through
      :class:`DailyDiaryService`, so ``closed_by`` and ``signed_by`` name the
      site supervisor and the archive carries the sealed SHA-256 snapshot
      production code computes.
    * The chronology is the site's, not the seeding minute's. ``closed_at``
      and ``signed_at`` are moved back to the evening of the day in question
      after the transition, which is safe because neither participates in the
      content hash (see ``_diary_to_dict``).

    Self-guards per project on its own diaries, so a re-run (boot, pack
    apply, force reinstall backfill) never duplicates. Callers pass demo
    projects only.

    Args:
        session: Open async DB session (the caller commits).
        project_ids: Candidate projects; non-German or non-demo ids are
            ignored.

    Returns:
        Counts dict (projects, diaries, entries, photos, weather_records,
        closed, signed).
    """
    candidates = list(project_ids)
    counts = {
        "projects": 0,
        "diaries": 0,
        "entries": 0,
        "photos": 0,
        "weather_records": 0,
        "closed": 0,
        "signed": 0,
    }
    if not candidates:
        return counts

    rows = await session.execute(
        select(Project.id, Project.metadata_, Project.owner_id).where(Project.id.in_(candidates))
    )
    targets: list[tuple[uuid.UUID, str, uuid.UUID | None]] = []
    for pid, meta, owner_id in rows.all():
        demo_id = str(meta.get("demo_id") or "").strip() if isinstance(meta, dict) else ""
        if demo_id in GERMAN_SHOWCASE_DEMO_IDS:
            targets.append((pid, demo_id, owner_id))
    if not targets:
        return counts

    # Per-project self-guard. Any diary at all means this project has been
    # through a seeder already, which is the same guard the generic seed
    # uses; the difference is that the generic seed no longer reaches these
    # projects, so the only diary that can be here is this one or a user's.
    existing_rows = await session.execute(
        select(DailyDiary.project_id).where(DailyDiary.project_id.in_([t[0] for t in targets]))
    )
    already = {pid for pid in existing_rows.scalars().all()}

    service = DailyDiaryService(session)
    today = datetime.now(UTC).date()

    for project_id, demo_id, owner_id in targets:
        if project_id in already:
            continue
        land = _SHOWCASE_LAND.get(demo_id, "HE")
        days = _german_working_days(today, _SHOWCASE_WORKING_DAYS, land=land)
        if not days:
            continue

        supervisor_name = ""
        if owner_id is not None:
            supervisor_name = str(
                (await session.execute(select(User.full_name).where(User.id == owner_id))).scalar_one_or_none() or ""
            ).strip()
        photo_pool = await _showcase_photo_pool(session, project_id)

        made: list[tuple[DailyDiary, date]] = []
        for index, day in enumerate(days):
            code, weather_label, weather_sentence = _DE_WEATHER[index % len(_DE_WEATHER)]
            trade = _DE_TRADES[index % len(_DE_TRADES)]
            activity = _DE_ACTIVITIES[index % len(_DE_ACTIVITIES)]
            labour = 14 + (index % 9)
            equipment = 3 + (index % 5)
            temp_c = _DE_MONTHLY_TEMP_C[day.month - 1] + (index % 5) - 2
            midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)

            diary = DailyDiary(
                id=uuid.uuid4(),
                project_id=project_id,
                diary_date=day.isoformat(),
                site_supervisor_id=owner_id,
                weather_summary={"conditions": code, "temp_c": temp_c},
                labour_count=labour,
                equipment_count=equipment,
                status="open",
                notes=(
                    f"{weather_sentence} {labour} Mann auf der Baustelle, "
                    f"{equipment} Geräte im Einsatz. {trade}: {activity}."
                ),
                closed_at=None,
                metadata_={"seed": _SHOWCASE_MARKER, "seed_revision": 1},
            )
            session.add(diary)
            made.append((diary, day))
            counts["diaries"] += 1

            for w in range(_SHOWCASE_WEATHER):
                session.add(
                    WeatherRecord(
                        id=uuid.uuid4(),
                        project_id=project_id,
                        captured_at=midnight + timedelta(hours=7 + w * 4),
                        source="open_meteo",
                        temperature_c=Decimal(str(temp_c + w - 1)),
                        humidity_pct=Decimal(str(55 + (index + w) % 30)),
                        wind_speed_kmh=Decimal(str(6 + (index + w) % 18)),
                        precipitation_mm=Decimal("4.2" if code == "rain" else "0.0"),
                        conditions_code=code,
                        conditions_text=weather_label,
                        sunrise=_SUNRISE,
                        sunset=_SUNSET,
                        location_lat=None,
                        location_lng=None,
                    )
                )
                counts["weather_records"] += 1

            for slot in range(_SHOWCASE_ENTRIES):
                entry_type, title, body = _DE_ENTRIES[(index + slot) % len(_DE_ENTRIES)]
                session.add(
                    DiaryEntry(
                        id=uuid.uuid4(),
                        diary_id=diary.id,
                        entry_type=entry_type,
                        entry_time=midnight + timedelta(hours=7, minutes=30 + slot * 170),
                        title=title,
                        description=body.format(
                            trade=trade,
                            activity=activity,
                            ref=f"BT-{index + 1:03d}",
                        ),
                        source_module=None,
                        source_ref=None,
                        author_id=owner_id,
                        photo_ids=[],
                        metadata_={"labour_count": labour // _SHOWCASE_ENTRIES},
                    )
                )
                counts["entries"] += 1

            for slot in range(_SHOWCASE_PHOTOS):
                if not photo_pool:
                    break
                source_id, caption = photo_pool[(index * _SHOWCASE_PHOTOS + slot) % len(photo_pool)]
                session.add(
                    DiaryPhoto(
                        id=uuid.uuid4(),
                        diary_id=diary.id,
                        project_id=project_id,
                        taken_at=midnight + timedelta(hours=9 + slot * 5),
                        photographer_id=owner_id,
                        lat=None,
                        lng=None,
                        location_label=_DE_PHOTO_PLACES[(index + slot) % len(_DE_PHOTO_PLACES)],
                        file_url=f"/api/v1/documents/photos/{source_id}/file/",
                        thumbnail_url=f"/api/v1/documents/photos/{source_id}/thumb/",
                        mime_type="image/jpeg",
                        # Left to the column default: the bytes live with the
                        # photo the URL points at, and inventing a size here
                        # would print a number the file does not have.
                        description=caption or f"{trade}: Bauzustand am {day.strftime('%d.%m.%Y')}",
                        tags=["bautagebuch", "baufortschritt"],
                        is_360=False,
                        is_drone=False,
                    )
                )
                counts["photos"] += 1

        await session.flush()

        if owner_id is None:
            # Nobody to name as the closer. Leaving the register open is
            # honest; a "Geschlossen" badge over a null closed_by is the
            # defect this seeder exists to remove.
            logger.info("daily diary showcase seed: %s has no owner, diaries left open", demo_id)
            counts["projects"] += 1
            continue

        actor = str(owner_id)
        signer_name = supervisor_name or "Bauleitung"
        for index, (diary, day) in enumerate(made):
            if index >= _SHOWCASE_ARCHIVED + _SHOWCASE_CLOSED:
                break  # the newest days stay open, as a live site's would
            await service.close_diary(diary.id, user_id=actor)
            # Back to the evening of the day itself. Neither closed_at nor
            # status feeds the content hash, so this can follow the
            # transition without breaking the archive's seal.
            closed_at = datetime(day.year, day.month, day.day, 17, 30, tzinfo=UTC)
            await service.diary_repo.update_fields(diary.id, closed_at=closed_at)
            counts["closed"] += 1
            if index >= _SHOWCASE_ARCHIVED:
                continue
            signature = await service.sign_diary(
                diary.id,
                signer_role="supervisor",
                signer_name=signer_name,
                user_id=actor,
            )
            signature.signed_at = closed_at + timedelta(minutes=20)
            await service.archive_diary(diary.id, user_id=actor)
            counts["signed"] += 1

        await session.flush()
        counts["projects"] += 1

    logger.info("seed_daily_diary_showcase_de: %s", counts)
    return counts


async def seeded_child_ids(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    diary_ids: list[uuid.UUID],
) -> list[tuple[type, list, str]]:
    """Diary-side rows the seed wrote next to the diaries ``diary_ids`` in ``project_ids``.

    Weather records, drone surveys and reality captures hang off the project,
    not the diary, so removing a seeded diary leaves them behind. A weather
    record matches when it sits in the same project on the day of a seeded
    diary (or the morning after, where the four-hourly readings run past
    midnight) and carries the seed's fixed sunrise and sunset. A drone survey
    and a reality capture match on the seed's note and its placeholder file
    address together.

    Returns:
        ``(model, ids, label)`` groups; ``label`` names the group in reports.
    """
    if not project_ids:
        return []
    days: set[tuple[uuid.UUID, str]] = set()
    if diary_ids:
        for pid, diary_date in (
            await session.execute(
                select(DailyDiary.project_id, DailyDiary.diary_date).where(DailyDiary.id.in_(diary_ids))
            )
        ).all():
            start = date.fromisoformat(str(diary_date)[:10])
            days.add((pid, start.isoformat()))
            days.add((pid, (start + timedelta(days=1)).isoformat()))
    weather = [
        r.id
        for r in (
            await session.execute(
                select(WeatherRecord.id, WeatherRecord.project_id, WeatherRecord.captured_at).where(
                    WeatherRecord.project_id.in_(project_ids),
                    WeatherRecord.sunrise == _SUNRISE,
                    WeatherRecord.sunset == _SUNSET,
                )
            )
        ).all()
        if (r.project_id, r.captured_at.date().isoformat()) in days
    ]
    drones = [
        r.id
        for r in (
            await session.execute(
                select(DroneSurvey.id, DroneSurvey.ortho_file_url).where(
                    DroneSurvey.project_id.in_(project_ids), DroneSurvey.notes == _DRONE_NOTE
                )
            )
        ).all()
        if str(r.ortho_file_url or "").startswith(_DRONE_URL)
    ]
    captures = [
        r.id
        for r in (
            await session.execute(
                select(RealityCaptureDataset.id, RealityCaptureDataset.file_url).where(
                    RealityCaptureDataset.project_id.in_(project_ids),
                    RealityCaptureDataset.notes == _REALITY_NOTE,
                )
            )
        ).all()
        if str(r.file_url or "").startswith(_REALITY_URL)
    ]
    return [
        (WeatherRecord, weather, "daily_diary_weather"),
        (DroneSurvey, drones, "daily_diary_drone_surveys"),
        (RealityCaptureDataset, captures, "daily_diary_reality_captures"),
    ]
