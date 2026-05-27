"""‌⁠‍Deterministic demo seed for the daily-diary module.

Usage::

    from app.modules.daily_diary.seed import seed_daily_diary_demo
    await seed_daily_diary_demo(session, project_ids=[uuid1, uuid2, uuid3])

Designed for the demo / QA dataset: produces 90 days of diaries per
project with realistic weather, entries, photos, videos, drone surveys
and reality-capture datasets.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

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
    compute_content_sha256,
    compute_immutable_payload,
)

_DAYS = 90
_WEATHER_PER_DIARY = 5
_ENTRIES_PER_DIARY = 8
_PHOTOS_TOTAL = 1000
_VIDEOS_TOTAL = 30
_DRONE_SURVEYS = 6
_REALITY_CAPTURES = 2

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
    "DJI Mavic 3 Enterprise",
    "DJI Matrice 350 RTK",
    "Parrot Anafi Ai",
    "Autel Evo II Pro RTK",
)

_CAPTURE_TYPES: tuple[str, ...] = ("laser_scan", "photogrammetry", "mobile_scan")


async def seed_daily_diary_demo(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
    *,
    base_date: datetime | None = None,
    deterministic_seed: int = 42,
) -> dict[str, int]:
    """‌⁠‍Populate the daily-diary tables with deterministic demo data.

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
    video_pool_remaining = _VIDEOS_TOTAL
    drone_pool_remaining = _DRONE_SURVEYS
    reality_pool_remaining = _REALITY_CAPTURES

    for project_idx, project_id in enumerate(project_ids):
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
                notes=f"Auto-seeded diary for {diary_date}",
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
                        sunrise="06:30:00",
                        sunset="20:15:00",
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
                        description=f"Seeded {entry_type} entry on {diary_date}",
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

    # Photos — distribute pool roughly evenly across all diaries.
    diary_list = list(diary_index.values())
    if diary_list:
        for _ in range(photo_pool_remaining):
            diary = rng.choice(diary_list)
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
                    file_url=f"https://seed.local/photos/{uuid.uuid4()}.jpg",
                    thumbnail_url=None,
                    mime_type="image/jpeg",
                    file_size_bytes=rng.randint(500_000, 8_000_000),
                    description="Seed photo",
                    tags=rng.sample(["progress", "safety", "quality", "drone", "concrete"], k=2),
                    is_360=rng.random() < 0.05,
                    is_drone=rng.random() < 0.10,
                )
            )

        for _ in range(video_pool_remaining):
            diary = rng.choice(diary_list)
            day_dt = datetime.fromisoformat(diary.diary_date + "T12:00:00").replace(tzinfo=UTC)
            videos.append(
                DiaryVideo(
                    id=uuid.uuid4(),
                    diary_id=diary.id,
                    project_id=diary.project_id,
                    recorded_at=day_dt,
                    file_url=f"https://seed.local/videos/{uuid.uuid4()}.mp4",
                    duration_seconds=rng.randint(15, 180),
                    file_size_bytes=rng.randint(5_000_000, 200_000_000),
                    description="Seed video",
                    tags=["progress"],
                )
            )

    for project_idx, project_id in enumerate(project_ids):
        for d in range(drone_pool_remaining // max(len(project_ids), 1)):
            drone_surveys.append(
                DroneSurvey(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    flown_at=base - timedelta(days=rng.randint(0, _DAYS - 1)),
                    pilot_name=f"Pilot {project_idx}.{d}",
                    drone_model=rng.choice(_DRONE_MODELS),
                    area_m2=Decimal(str(round(rng.uniform(500, 50_000), 2))),
                    ortho_file_url=f"https://seed.local/drone/{uuid.uuid4()}.tif",
                    dsm_file_url=f"https://seed.local/drone/{uuid.uuid4()}.tif",
                    point_cloud_url=None,
                    elevation_min_m=Decimal(str(round(rng.uniform(0, 50), 2))),
                    elevation_max_m=Decimal(str(round(rng.uniform(50, 150), 2))),
                    notes="Seed drone survey",
                )
            )
        for r in range(reality_pool_remaining // max(len(project_ids), 1) + 1):
            reality_captures.append(
                RealityCaptureDataset(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    captured_at=base - timedelta(days=rng.randint(0, _DAYS - 1)),
                    capture_type=rng.choice(_CAPTURE_TYPES),
                    file_url=f"https://seed.local/reality/{uuid.uuid4()}.e57",
                    point_count_estimate=rng.randint(1_000_000, 200_000_000),
                    bbox_min={"x": 0.0, "y": 0.0, "z": 0.0},
                    bbox_max={"x": 100.0, "y": 100.0, "z": 25.0},
                    accuracy_mm=Decimal(str(round(rng.uniform(1, 25), 2))),
                    notes="Seed reality capture",
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
