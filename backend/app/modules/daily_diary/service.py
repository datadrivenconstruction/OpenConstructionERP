"""‌⁠‍Daily Site Diary business logic.

Pure helpers are exposed as module-level functions so they can be unit
tested without a database. The :class:`DailyDiaryService` orchestrates
state transitions, persistence, and event publication.

Events emitted:
    * ``daily_diary.closed``                 — diary transitioned open→closed
    * ``daily_diary.signed``                 — diary signed (snapshot frozen)
    * ``daily_diary.archived``               — diary archived (terminal state)
    * ``daily_diary.photo.registered``       — new photo recorded
    * ``daily_diary.drone.attached``         — drone survey attached
    * ``daily_diary.reality_capture.attached`` — reality-capture attached
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
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
from app.modules.daily_diary.repository import (
    DailyDiaryRepository,
    DiaryArchiveSignatureRepository,
    DiaryEntryRepository,
    DiaryPhotoRepository,
    DiaryVideoRepository,
    DroneSurveyRepository,
    RealityCaptureRepository,
    WeatherRecordRepository,
)
from app.modules.daily_diary.schemas import (
    DailyDiaryCreate,
    DailyDiaryUpdate,
    DiaryEntryCreate,
    DiaryPhotoCreate,
    DiaryPhotoUpdate,
    DiaryVideoCreate,
    DiaryVideoUpdate,
    DroneSurveyCreate,
    DroneSurveyUpdate,
    RealityCaptureCreate,
    RealityCaptureUpdate,
    WeatherRecordCreate,
    WeatherRecordUpdate,
)

logger = logging.getLogger(__name__)


# ── Status state machine ─────────────────────────────────────────────────


DIARY_STATUSES: tuple[str, ...] = ("open", "closed", "signed", "archived")


def _status_index(value: str) -> int:
    try:
        return DIARY_STATUSES.index(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unknown diary status: {value}") from exc


def _ensure_can_transition(current: str, target: str) -> None:
    """‌⁠‍Raise HTTPException(409) if the transition would regress."""
    if _status_index(target) <= _status_index(current):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot transition diary from '{current}' to '{target}' — "
                "status flow is open→closed→signed→archived and is one-way."
            ),
        )


def _diary_signed_immutable_detail(diary_id: uuid.UUID, status_str: str) -> dict[str, Any]:
    """‌⁠‍Return the structured 409 detail body for signed-immutable rejections.

    The ``code`` field is the i18n key the frontend renders against the
    user's locale. Inlining the english ``message`` keeps API consumers
    that don't speak the i18n dict happy.
    """
    return {
        "code": "diary_signed_immutable",
        "message": (
            f"Diary {diary_id} is {status_str}; the signed snapshot is "
            "immutable. Use POST /diaries/{diary_id}/unlock (manager+) "
            "to re-open before editing."
        ),
        "diary_id": str(diary_id),
        "status": status_str,
    }


def _entry_signed_immutable_detail(diary_id: uuid.UUID, status_str: str) -> dict[str, Any]:
    """‌⁠‍Structured 409 detail when a child entry/photo's parent diary is sealed."""
    return {
        "code": "entry_signed_immutable",
        "message": (
            f"Cannot modify entries of a {status_str} diary — the signed "
            "snapshot would be invalidated. Use POST /diaries/{diary_id}/"
            "unlock (manager+) first."
        ),
        "diary_id": str(diary_id),
        "status": status_str,
    }


# ── Pure helpers ─────────────────────────────────────────────────────────


def _json_default(value: Any) -> Any:
    """‌⁠‍JSON encoder fallback used by the canonical payload serialiser."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported type for canonical payload: {type(value)!r}")


def _coerce_scalar(value: Any) -> Any:
    """Coerce model values into JSON-friendly scalars (deterministically)."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_coerce_scalar(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _coerce_scalar(v) for k, v in value.items()}
    return value


def _diary_to_dict(diary: object) -> dict[str, Any]:
    """Extract the fields of a diary that participate in the content hash."""
    fields = (
        "id",
        "project_id",
        "diary_date",
        "site_supervisor_id",
        "weather_summary",
        "labour_count",
        "equipment_count",
        "notes",
    )
    out: dict[str, Any] = {}
    for fld in fields:
        out[fld] = _coerce_scalar(getattr(diary, fld, None))
    return out


def _entry_to_dict(entry: object) -> dict[str, Any]:
    fields = (
        "id",
        "entry_type",
        "entry_time",
        "title",
        "description",
        "source_module",
        "source_ref",
        "author_id",
        "photo_ids",
    )
    out: dict[str, Any] = {}
    for fld in fields:
        out[fld] = _coerce_scalar(getattr(entry, fld, None))
    return out


def _photo_to_dict(photo: object) -> dict[str, Any]:
    fields = (
        "id",
        "taken_at",
        "lat",
        "lng",
        "file_url",
        "mime_type",
        "is_360",
        "is_drone",
    )
    out: dict[str, Any] = {}
    for fld in fields:
        out[fld] = _coerce_scalar(getattr(photo, fld, None))
    return out


def compute_immutable_payload(
    diary: object,
    entries: list,
    photos: list,
) -> dict[str, Any]:
    """Build the deterministic, hash-stable representation of a diary.

    Order of entries and photos is enforced (by ``entry_time``/``taken_at``
    then ``id``) so the same logical content always hashes the same.
    """
    sorted_entries = sorted(
        entries,
        key=lambda e: (
            _coerce_scalar(getattr(e, "entry_time", "")),
            str(getattr(e, "id", "")),
        ),
    )
    sorted_photos = sorted(
        photos,
        key=lambda p: (
            _coerce_scalar(getattr(p, "taken_at", "")),
            str(getattr(p, "id", "")),
        ),
    )
    return {
        "schema_version": 1,
        "diary": _diary_to_dict(diary),
        "entries": [_entry_to_dict(e) for e in sorted_entries],
        "photos": [_photo_to_dict(p) for p in sorted_photos],
    }


def compute_content_sha256(payload: Mapping[str, Any]) -> str:
    """Stable SHA-256 of a JSON-serialisable payload."""
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_diary_signed(diary_id: uuid.UUID, signatures: list) -> bool:
    """Return True iff at least one signature row exists for ``diary_id``."""
    return any(getattr(sig, "diary_id", None) == diary_id for sig in signatures)


_MODULE_TO_ENTRY_TYPE: dict[str, str] = {
    "hse": "incident_summary",
    "safety": "incident_summary",
    "quality": "inspection_summary",
    "inspections": "inspection_summary",
    "procurement": "delivery",
    "schedule": "completion",
}


def auto_populate_entries_from_module_events(
    diary: object,
    module_payloads: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Map upstream-module event payloads to ``DiaryEntryCreate`` dicts.

    Each input payload must include ``source_module`` plus arbitrary
    fields. Recognised modules (HSE/Procurement/Quality/Schedule) map
    to a specific ``entry_type``; anything else lands as ``general``.
    """
    diary_id = getattr(diary, "id", None)
    out: list[dict[str, Any]] = []
    for raw in module_payloads:
        source_module = str(raw.get("source_module") or "").lower()
        entry_type = _MODULE_TO_ENTRY_TYPE.get(source_module, "general")
        entry_time = raw.get("entry_time") or raw.get("occurred_at") or datetime.now(UTC)
        if isinstance(entry_time, str):
            try:
                entry_time = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
            except ValueError:
                entry_time = datetime.now(UTC)
        out.append(
            {
                "diary_id": diary_id,
                "entry_type": entry_type,
                "entry_time": entry_time,
                "title": str(raw.get("title") or raw.get("summary") or "")[:500],
                "description": raw.get("description") or raw.get("body"),
                "source_module": source_module or None,
                "source_ref": raw.get("source_ref") or raw.get("entity_id"),
                "author_id": raw.get("author_id") or raw.get("user_id"),
                "photo_ids": list(raw.get("photo_ids") or []),
                "metadata": dict(raw.get("metadata") or {}),
            }
        )
    return out


_COMPLETENESS_FIELDS: tuple[str, ...] = (
    "diary_date",
    "site_supervisor_id",
    "weather_summary",
    "labour_count",
    "equipment_count",
    "notes",
)


def compute_diary_completeness(diary: object, entries: list) -> Decimal:
    """Return percent completeness (0.0 to 1.0) based on field + entry presence."""
    total = len(_COMPLETENESS_FIELDS) + 1  # +1 for "at least one entry"
    filled = 0
    for fld in _COMPLETENESS_FIELDS:
        value = getattr(diary, fld, None)
        if value in (None, "", 0, [], {}):
            continue
        filled += 1
    if entries:
        filled += 1
    if total == 0:
        return Decimal("0")
    return (Decimal(filled) / Decimal(total)).quantize(Decimal("0.0001"))


def compute_photo_timeline(
    project_id: uuid.UUID,
    photos: list,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[dict[str, Any]]:
    """Group photos by calendar date for a timeline view."""
    buckets: dict[str, dict[str, Any]] = {}
    for photo in photos:
        taken_at = getattr(photo, "taken_at", None)
        if taken_at is None:
            continue
        if isinstance(taken_at, str):
            try:
                taken_at = datetime.fromisoformat(taken_at.replace("Z", "+00:00"))
            except ValueError:
                continue
        if date_from is not None and taken_at < date_from:
            continue
        if date_to is not None and taken_at > date_to:
            continue
        day_key = taken_at.date().isoformat()
        bucket = buckets.setdefault(
            day_key,
            {"date": day_key, "photo_count": 0, "photo_ids": []},
        )
        bucket["photo_count"] += 1
        bucket["photo_ids"].append(photo.id)
    return sorted(buckets.values(), key=lambda b: b["date"])


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS-84 coordinates, in metres."""
    r = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _as_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str):
        return value[:10]
    return None


def compute_before_after(
    photos: list,
    date_a: datetime | str,
    date_b: datetime | str,
    location_radius_m: float = 15.0,
) -> list[dict[str, Any]]:
    """Pair photos taken near each other across two dates.

    Args:
        photos: All candidate photos.
        date_a: Earlier date (anchor for "before" photos).
        date_b: Later date (anchor for "after" photos).
        location_radius_m: Max great-circle distance to consider a pair.
    """
    da = _as_date(date_a)
    db = _as_date(date_b)
    if da is None or db is None:
        return []

    a_photos = [
        p
        for p in photos
        if _as_date(getattr(p, "taken_at", None)) == da
        and getattr(p, "lat", None) is not None
        and getattr(p, "lng", None) is not None
    ]
    b_photos = [
        p
        for p in photos
        if _as_date(getattr(p, "taken_at", None)) == db
        and getattr(p, "lat", None) is not None
        and getattr(p, "lng", None) is not None
    ]

    pairs: list[dict[str, Any]] = []
    used_b: set[Any] = set()
    for a in a_photos:
        best: tuple[float, Any] | None = None
        for b in b_photos:
            if b.id in used_b:
                continue
            distance = _haversine_m(
                float(a.lat),
                float(a.lng),
                float(b.lat),
                float(b.lng),
            )
            if distance <= location_radius_m and (best is None or distance < best[0]):
                best = (distance, b)
        if best is not None:
            distance, b = best
            used_b.add(b.id)
            pairs.append(
                {
                    "photo_a_id": a.id,
                    "photo_b_id": b.id,
                    "distance_m": round(distance, 4),
                    "date_a": a.taken_at,
                    "date_b": b.taken_at,
                }
            )
    return pairs


def validate_diary_immutability(
    diary_id: uuid.UUID,
    signatures: list,
    new_payload: Mapping[str, Any],
) -> tuple[bool, str | None]:
    """Check whether the new payload is allowed against signed history.

    Returns ``(True, None)`` if the diary has never been signed OR the
    new payload's hash matches the latest signed hash; otherwise
    ``(False, reason)``.
    """
    relevant = [s for s in signatures if getattr(s, "diary_id", None) == diary_id]
    if not relevant:
        return True, None
    latest = max(relevant, key=lambda s: getattr(s, "revision", 0))
    new_hash = compute_content_sha256(new_payload)
    if new_hash == getattr(latest, "content_sha256", None):
        return True, None
    return False, (
        f"Diary {diary_id} has been signed at revision "
        f"{getattr(latest, 'revision', '?')} with hash "
        f"{getattr(latest, 'content_sha256', '?')[:12]}…; "
        "the proposed payload diverges from the signed snapshot."
    )


# ── Service ──────────────────────────────────────────────────────────────


class DailyDiaryService:
    """Business logic for the daily-diary module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.diary_repo = DailyDiaryRepository(session)
        self.weather_repo = WeatherRecordRepository(session)
        self.entry_repo = DiaryEntryRepository(session)
        self.photo_repo = DiaryPhotoRepository(session)
        self.video_repo = DiaryVideoRepository(session)
        self.drone_repo = DroneSurveyRepository(session)
        self.reality_repo = RealityCaptureRepository(session)
        self.signature_repo = DiaryArchiveSignatureRepository(session)

    # ── Diary CRUD ───────────────────────────────────────────────────────

    async def create_diary(
        self,
        data: DailyDiaryCreate,
        user_id: str | None = None,
    ) -> DailyDiary:
        # A site diary is a contemporaneous record: back-dating (a
        # retroactive entry for a past day) is legitimate, but a
        # *future*-dated diary is not. Allow one day of slack so a site
        # ahead of UTC can still open "its" current day.
        try:
            entry_day = datetime.strptime(data.diary_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid diary_date: {exc}",
            ) from exc
        max_allowed = datetime.now(UTC).date() + timedelta(days=1)
        if entry_day > max_allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"diary_date {data.diary_date} is in the future; a daily "
                    "site diary is a contemporaneous record and cannot be "
                    "opened ahead of the site date."
                ),
            )
        existing = await self.diary_repo.get_by_date_and_project(data.project_id, data.diary_date)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Daily diary for project {data.project_id} on {data.diary_date} already exists"),
            )
        diary = DailyDiary(
            project_id=data.project_id,
            diary_date=data.diary_date,
            site_supervisor_id=data.site_supervisor_id,
            weather_summary=data.weather_summary,
            labour_count=data.labour_count,
            equipment_count=data.equipment_count,
            status="open",
            notes=data.notes,
            metadata_=data.metadata,
        )
        diary = await self.diary_repo.create(diary)
        logger.info(
            "Daily diary created: %s for project %s on %s by %s",
            diary.id,
            data.project_id,
            data.diary_date,
            user_id,
        )
        return diary

    async def get_diary(self, diary_id: uuid.UUID) -> DailyDiary:
        diary = await self.diary_repo.get_by_id(diary_id)
        if diary is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Daily diary not found",
            )
        return diary  # type: ignore[return-value]

    async def list_diaries(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        status_filter: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[DailyDiary], int]:
        return await self.diary_repo.list_by_project_in_range(
            project_id,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
            status=status_filter,
        )

    async def update_diary(self, diary_id: uuid.UUID, data: DailyDiaryUpdate) -> DailyDiary:
        diary = await self.get_diary(diary_id)
        if diary.status in ("signed", "archived"):
            # Enforce immutability for signed/archived diaries.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_diary_signed_immutable_detail(diary_id, diary.status),
            )
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return diary
        await self.diary_repo.update_fields(diary_id, **fields)
        await self.session.refresh(diary)
        return diary

    async def delete_diary(self, diary_id: uuid.UUID) -> None:
        diary = await self.get_diary(diary_id)
        if diary.status in ("signed", "archived"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_diary_signed_immutable_detail(diary_id, diary.status),
            )
        await self.diary_repo.delete(diary_id)

    async def unlock_diary(
        self,
        diary_id: uuid.UUID,
        *,
        user_id: str | None = None,
        reason: str | None = None,
    ) -> DailyDiary:
        """‌⁠‍Re-open a signed diary so manager-+ can amend it.

        The archive signature is preserved (with its hash) so the
        original sealed snapshot remains forensically traceable. After
        editing, a fresh ``sign_diary`` call produces a new revision —
        the integrity audit thus sees two signatures with two different
        hashes against the same diary_id.

        Archived diaries cannot be unlocked: an archived diary is the
        final legal record; re-opening it would invalidate the
        ``daily_diary.archived`` event already consumed downstream.
        """
        diary = await self.get_diary(diary_id)
        if diary.status == "open":
            return diary  # idempotent
        if diary.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "diary_archived_cannot_unlock",
                    "message": ("Cannot unlock an archived diary — archive is terminal. Open a new diary instead."),
                    "diary_id": str(diary_id),
                    "status": "archived",
                },
            )
        # signed → open. Stamp an audit row on the diary metadata.
        meta = dict(getattr(diary, "metadata_", {}) or {})
        history = list(meta.get("unlock_history") or [])
        history.append(
            {
                "unlocked_by": user_id,
                "unlocked_at": datetime.now(UTC).isoformat(),
                "previous_status": diary.status,
                "reason": reason,
            }
        )
        meta["unlock_history"] = history
        await self.diary_repo.update_fields(
            diary_id,
            status="open",
            metadata_=meta,
        )
        await self.session.refresh(diary)
        event_bus.publish_detached(
            "daily_diary.unlocked",
            {
                "diary_id": str(diary_id),
                "project_id": str(diary.project_id),
                "unlocked_by": user_id,
                "reason": reason,
            },
            source_module="daily_diary",
        )
        logger.warning(
            "Daily diary unlocked: %s by %s (broke signed snapshot, previous signatures retained for audit)",
            diary_id,
            user_id,
        )
        return diary

    # ── State transitions ────────────────────────────────────────────────

    async def close_diary(
        self,
        diary_id: uuid.UUID,
        *,
        user_id: str | None = None,
    ) -> DailyDiary:
        """Transition diary open→closed; emit ``daily_diary.closed``.

        ``labour_count`` / ``equipment_count`` on the diary row are the
        site-supervisor's HEADER counts and are intentionally NOT mutated
        here. The authoritative roll-up (header + entries) is computed
        on demand by :meth:`workforce_summary_for_diary` so that:

            * closing is idempotent — re-running it does not silently
              keep inflating the counts;
            * the workforce summary is internally consistent (header +
              entries) regardless of whether the diary is open or closed.

        Mutating the field here previously double-counted entries when
        :meth:`workforce_summary_for_diary` ran after close: the diary
        base was already inflated, and the summary then added the same
        entries on top of it again.
        """
        diary = await self.get_diary(diary_id)
        _ensure_can_transition(diary.status, "closed")

        now = datetime.now(UTC)
        closed_by_uuid: uuid.UUID | None = None
        if user_id:
            try:
                closed_by_uuid = uuid.UUID(user_id)
            except (ValueError, TypeError):
                closed_by_uuid = None

        await self.diary_repo.update_fields(
            diary_id,
            status="closed",
            closed_at=now,
            closed_by=closed_by_uuid,
        )
        await self.session.refresh(diary)
        event_bus.publish_detached(
            "daily_diary.closed",
            {
                "diary_id": str(diary_id),
                "project_id": str(diary.project_id),
                "diary_date": diary.diary_date,
                "closed_by": user_id,
            },
            source_module="daily_diary",
        )
        # Also emit the workforce summary so resource utilisation gets a tick.
        # Use a defensive try/except so a failure to compute does not undo
        # the close transition.
        try:
            await self.emit_workforce_summary(diary_id)
        except Exception:
            logger.debug("Failed to emit workforce summary on close", exc_info=True)
        return diary

    async def sign_diary(
        self,
        diary_id: uuid.UUID,
        *,
        signer_role: str,
        signer_name: str | None = None,
        signature_data: str | None = None,
        algorithm: str = "sha256",
        user_id: str | None = None,
    ) -> DiaryArchiveSignature:
        """Sign the diary — emit ``daily_diary.signed``. Idempotent on re-sign."""
        diary = await self.get_diary(diary_id)
        if diary.status == "open":
            # Auto-close on first sign so the transition stays one-way.
            await self.close_diary(diary_id, user_id=user_id)
            diary = await self.get_diary(diary_id)
        if diary.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot sign an archived diary",
            )

        entries = await self.entry_repo.list_for_diary(diary_id)
        # Single indexed query scoped to the diary — previously we fetched
        # every photo in the entire project (limit=10 000) and filtered in
        # Python, which scaled O(project size) per signature operation.
        photos = await self.photo_repo.photos_for_diary(diary_id)

        payload = compute_immutable_payload(diary, entries, photos)
        content_hash = compute_content_sha256(payload)

        existing = await self.signature_repo.latest_for_diary(diary_id)
        revision = (existing.revision + 1) if existing is not None else 1

        signed_by_uuid: uuid.UUID | None = None
        if user_id:
            try:
                signed_by_uuid = uuid.UUID(user_id)
            except (ValueError, TypeError):
                signed_by_uuid = None

        signature = DiaryArchiveSignature(
            diary_id=diary_id,
            content_sha256=content_hash,
            signed_at=datetime.now(UTC),
            signed_by=signed_by_uuid,
            signature_payload={
                "algorithm": algorithm,
                "signer_role": signer_role,
                "signer_name": signer_name,
                "signature_data": signature_data,
            },
            revision=revision,
        )
        # Unique on diary_id forces us to remove + recreate on re-sign.
        if existing is not None:
            await self.signature_repo.delete(existing.id)
        signature = await self.signature_repo.create(signature)  # type: ignore[assignment]

        sig_field = "owner_signature_ref" if signer_role == "owner" else "supervisor_signature_ref"
        await self.diary_repo.update_fields(
            diary_id,
            status="signed",
            **{sig_field: signer_name or content_hash[:32]},
        )
        await self.session.refresh(diary)

        event_bus.publish_detached(
            "daily_diary.signed",
            {
                "diary_id": str(diary_id),
                "project_id": str(diary.project_id),
                "content_sha256": content_hash,
                "revision": revision,
                "signer_role": signer_role,
            },
            source_module="daily_diary",
        )
        return signature  # type: ignore[return-value]

    async def archive_diary(
        self,
        diary_id: uuid.UUID,
        *,
        user_id: str | None = None,
    ) -> DailyDiary:
        """Transition diary signed→archived. Cannot transition back.

        Archiving is only meaningful for a *signed* diary — the archive's
        legal value is the sealed SHA-256 snapshot taken at sign time.
        Archiving an unsigned diary would produce a terminal record with
        no contemporaneous integrity proof, so it is rejected.
        """
        diary = await self.get_diary(diary_id)
        _ensure_can_transition(diary.status, "archived")
        if diary.status != "signed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot archive a '{diary.status}' diary — it must be "
                    "signed first so the archive carries a sealed snapshot."
                ),
            )

        await self.diary_repo.update_fields(diary_id, status="archived")
        await self.session.refresh(diary)
        event_bus.publish_detached(
            "daily_diary.archived",
            {
                "diary_id": str(diary_id),
                "project_id": str(diary.project_id),
                "archived_by": user_id,
            },
            source_module="daily_diary",
        )
        return diary

    # ── Weather ──────────────────────────────────────────────────────────

    async def create_weather(self, data: WeatherRecordCreate) -> WeatherRecord:
        record = WeatherRecord(
            project_id=data.project_id,
            captured_at=data.captured_at,
            source=data.source,
            temperature_c=data.temperature_c,
            humidity_pct=data.humidity_pct,
            wind_speed_kmh=data.wind_speed_kmh,
            precipitation_mm=data.precipitation_mm,
            conditions_code=data.conditions_code,
            conditions_text=data.conditions_text,
            sunrise=data.sunrise,
            sunset=data.sunset,
            location_lat=data.location_lat,
            location_lng=data.location_lng,
            metadata_=data.metadata,
        )
        return await self.weather_repo.create(record)  # type: ignore[return-value]

    async def weather_for_day(
        self,
        project_id: uuid.UUID,
        day: str | None = None,
    ) -> list[WeatherRecord]:
        """Weather records for one calendar day (UTC), newest first.

        ``day`` is ``YYYY-MM-DD``; ``None`` means the current UTC day.
        """
        if day is None:
            target = datetime.now(UTC).date()
        else:
            try:
                target = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError as exc:
                raise HTTPException(422, f"Invalid day: {exc}") from exc
        day_start = datetime(target.year, target.month, target.day, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        return await self.weather_repo.for_project_on_day(project_id, day_start, day_end)

    async def get_weather(self, weather_id: uuid.UUID) -> WeatherRecord:
        record = await self.weather_repo.get_by_id(weather_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Weather record not found")
        return record  # type: ignore[return-value]

    async def update_weather(self, weather_id: uuid.UUID, data: WeatherRecordUpdate) -> WeatherRecord:
        await self.get_weather(weather_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.weather_repo.update_fields(weather_id, **fields)
        return await self.get_weather(weather_id)

    async def delete_weather(self, weather_id: uuid.UUID) -> None:
        await self.get_weather(weather_id)
        await self.weather_repo.delete(weather_id)

    # ── Entries ──────────────────────────────────────────────────────────

    async def create_entry(self, data: DiaryEntryCreate) -> DiaryEntry:
        diary = await self.get_diary(data.diary_id)
        if diary.status in ("signed", "archived"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_entry_signed_immutable_detail(data.diary_id, diary.status),
            )
        entry = DiaryEntry(
            diary_id=data.diary_id,
            entry_type=data.entry_type,
            entry_time=data.entry_time,
            title=data.title,
            description=data.description,
            source_module=data.source_module,
            source_ref=data.source_ref,
            author_id=data.author_id,
            photo_ids=[str(pid) for pid in data.photo_ids],
            metadata_=data.metadata,
        )
        return await self.entry_repo.create(entry)  # type: ignore[return-value]

    async def bulk_create_entries(
        self,
        diary_id: uuid.UUID,
        payloads: list[Mapping[str, Any]],
    ) -> list[DiaryEntry]:
        diary = await self.get_diary(diary_id)
        if diary.status in ("signed", "archived"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_entry_signed_immutable_detail(diary_id, diary.status),
            )
        entries: list[DiaryEntry] = []
        for raw in payloads:
            entries.append(
                DiaryEntry(
                    diary_id=diary_id,
                    entry_type=str(raw["entry_type"]),
                    entry_time=raw["entry_time"],
                    title=str(raw.get("title") or ""),
                    description=raw.get("description"),
                    source_module=raw.get("source_module"),
                    source_ref=raw.get("source_ref"),
                    author_id=raw.get("author_id"),
                    photo_ids=[str(pid) for pid in (raw.get("photo_ids") or [])],
                    metadata_=dict(raw.get("metadata") or {}),
                )
            )
        return await self.entry_repo.bulk_create(entries)

    async def list_entries(
        self,
        diary_id: uuid.UUID,
        *,
        entry_type: str | None = None,
    ) -> list[DiaryEntry]:
        """List a diary's entries (chronological). Validates the diary exists."""
        await self.get_diary(diary_id)
        return await self.entry_repo.list_for_diary(diary_id, entry_type=entry_type)

    async def get_entry(self, entry_id: uuid.UUID) -> DiaryEntry:
        entry = await self.entry_repo.get_by_id(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Diary entry not found")
        return entry  # type: ignore[return-value]

    async def _assert_entry_diary_mutable(self, entry: DiaryEntry) -> DailyDiary:
        """Raise 409 if the entry's parent diary is sealed (signed/archived)."""
        diary = await self.get_diary(entry.diary_id)
        if diary.status in ("signed", "archived"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_entry_signed_immutable_detail(entry.diary_id, diary.status),
            )
        return diary

    async def update_entry(self, entry_id: uuid.UUID, fields: dict[str, Any]) -> DiaryEntry:
        entry = await self.get_entry(entry_id)
        await self._assert_entry_diary_mutable(entry)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.entry_repo.update_fields(entry_id, **fields)
        return await self.get_entry(entry_id)

    async def delete_entry(self, entry_id: uuid.UUID) -> None:
        entry = await self.get_entry(entry_id)
        await self._assert_entry_diary_mutable(entry)
        await self.entry_repo.delete(entry_id)

    # ── Photos ───────────────────────────────────────────────────────────

    async def register_photo(self, data: DiaryPhotoCreate) -> DiaryPhoto:
        diary_id = data.diary_id
        if diary_id is None:
            # Auto-link to the diary for the photo's date, if one exists.
            day = data.taken_at.date().isoformat()
            diary = await self.diary_repo.get_by_date_and_project(data.project_id, day)
            if diary is not None:
                diary_id = diary.id
        # R7 signed-immutable: a photo linked to a signed/archived diary
        # changes the immutable payload (photos participate in the hash),
        # which would break the archival signature. Refuse with the same
        # structured 409 used for entries.
        if diary_id is not None:
            parent = await self.diary_repo.get_by_id(diary_id)
            if parent is not None and getattr(parent, "status", "open") in ("signed", "archived"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=_entry_signed_immutable_detail(
                        diary_id,
                        parent.status,
                    ),
                )

        photo = DiaryPhoto(
            diary_id=diary_id,
            project_id=data.project_id,
            taken_at=data.taken_at,
            photographer_id=data.photographer_id,
            lat=data.lat,
            lng=data.lng,
            location_label=data.location_label,
            file_url=data.file_url,
            thumbnail_url=data.thumbnail_url,
            mime_type=data.mime_type,
            file_size_bytes=data.file_size_bytes,
            description=data.description,
            tags=list(data.tags),
            is_360=data.is_360,
            is_drone=data.is_drone,
        )
        photo = await self.photo_repo.create(photo)  # type: ignore[assignment]
        event_bus.publish_detached(
            "daily_diary.photo.registered",
            {
                "photo_id": str(photo.id),
                "project_id": str(data.project_id),
                "diary_id": str(diary_id) if diary_id else None,
                "taken_at": data.taken_at.isoformat(),
            },
            source_module="daily_diary",
        )
        return photo

    async def update_photo(self, photo_id: uuid.UUID, data: DiaryPhotoUpdate) -> DiaryPhoto:
        photo = await self.photo_repo.get_by_id(photo_id)
        if photo is None:
            raise HTTPException(
                status_code=404,
                detail=translate("errors.diary_photo_not_found", locale=get_locale()),
            )
        # R7 signed-immutable: mutating a photo on a sealed diary breaks the
        # archival hash.
        parent_diary_id = getattr(photo, "diary_id", None)
        if parent_diary_id is not None:
            parent = await self.diary_repo.get_by_id(parent_diary_id)
            if parent is not None and getattr(parent, "status", "open") in ("signed", "archived"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=_entry_signed_immutable_detail(
                        parent_diary_id,
                        parent.status,
                    ),
                )
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.photo_repo.update_fields(photo_id, **fields)
        return await self.photo_repo.get_by_id(photo_id)  # type: ignore[return-value]

    async def delete_photo(self, photo_id: uuid.UUID) -> None:
        photo = await self.photo_repo.get_by_id(photo_id)
        if photo is None:
            raise HTTPException(
                status_code=404,
                detail=translate("errors.diary_photo_not_found", locale=get_locale()),
            )
        # R7 signed-immutable: deleting a photo on a sealed diary is also
        # a hash-breaking change. Reject with the structured 409 so the
        # UI can prompt for unlock.
        parent_diary_id = getattr(photo, "diary_id", None)
        if parent_diary_id is not None:
            parent = await self.diary_repo.get_by_id(parent_diary_id)
            if parent is not None and getattr(parent, "status", "open") in ("signed", "archived"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=_entry_signed_immutable_detail(
                        parent_diary_id,
                        parent.status,
                    ),
                )
        await self.photo_repo.delete(photo_id)

    # ── Videos ───────────────────────────────────────────────────────────

    async def create_video(self, data: DiaryVideoCreate) -> DiaryVideo:
        video = DiaryVideo(
            diary_id=data.diary_id,
            project_id=data.project_id,
            recorded_at=data.recorded_at,
            file_url=data.file_url,
            thumbnail_url=data.thumbnail_url,
            duration_seconds=data.duration_seconds,
            file_size_bytes=data.file_size_bytes,
            description=data.description,
            tags=list(data.tags),
        )
        return await self.video_repo.create(video)  # type: ignore[return-value]

    async def update_video(self, video_id: uuid.UUID, data: DiaryVideoUpdate) -> DiaryVideo:
        video = await self.video_repo.get_by_id(video_id)
        if video is None:
            raise HTTPException(status_code=404, detail=translate("errors.diary_video_not_found", locale=get_locale()))
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.video_repo.update_fields(video_id, **fields)
        return await self.video_repo.get_by_id(video_id)  # type: ignore[return-value]

    async def delete_video(self, video_id: uuid.UUID) -> None:
        video = await self.video_repo.get_by_id(video_id)
        if video is None:
            raise HTTPException(status_code=404, detail=translate("errors.diary_video_not_found", locale=get_locale()))
        await self.video_repo.delete(video_id)

    # ── Drone surveys ────────────────────────────────────────────────────

    async def attach_drone_survey(self, data: DroneSurveyCreate) -> DroneSurvey:
        survey = DroneSurvey(
            project_id=data.project_id,
            flown_at=data.flown_at,
            pilot_name=data.pilot_name,
            drone_model=data.drone_model,
            area_m2=data.area_m2,
            ortho_file_url=data.ortho_file_url,
            dsm_file_url=data.dsm_file_url,
            point_cloud_url=data.point_cloud_url,
            elevation_min_m=data.elevation_min_m,
            elevation_max_m=data.elevation_max_m,
            notes=data.notes,
        )
        survey = await self.drone_repo.create(survey)  # type: ignore[assignment]
        event_bus.publish_detached(
            "daily_diary.drone.attached",
            {
                "drone_survey_id": str(survey.id),
                "project_id": str(data.project_id),
                "flown_at": data.flown_at.isoformat(),
            },
            source_module="daily_diary",
        )
        return survey

    async def update_drone_survey(self, survey_id: uuid.UUID, data: DroneSurveyUpdate) -> DroneSurvey:
        survey = await self.drone_repo.get_by_id(survey_id)
        if survey is None:
            raise HTTPException(status_code=404, detail=translate("errors.survey_not_found", locale=get_locale()))
        fields = data.model_dump(exclude_unset=True)
        # Cross-field invariant: elevation_min_m ≤ elevation_max_m. The
        # schema validator catches the case where BOTH come in the same
        # request; here we cover the partial PATCH that updates only one
        # side — the existing row supplies the missing end of the range.
        if "elevation_min_m" in fields or "elevation_max_m" in fields:
            new_lo = fields.get("elevation_min_m", survey.elevation_min_m)  # type: ignore[attr-defined]
            new_hi = fields.get("elevation_max_m", survey.elevation_max_m)  # type: ignore[attr-defined]
            if new_lo is not None and new_hi is not None and new_lo > new_hi:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "elevation_min_m must be less than or equal to "
                        "elevation_max_m (would conflict with stored value)"
                    ),
                )
        if fields:
            await self.drone_repo.update_fields(survey_id, **fields)
        return await self.drone_repo.get_by_id(survey_id)  # type: ignore[return-value]

    async def delete_drone_survey(self, survey_id: uuid.UUID) -> None:
        survey = await self.drone_repo.get_by_id(survey_id)
        if survey is None:
            raise HTTPException(status_code=404, detail=translate("errors.survey_not_found", locale=get_locale()))
        await self.drone_repo.delete(survey_id)

    # ── Reality capture ──────────────────────────────────────────────────

    async def attach_reality_capture(self, data: RealityCaptureCreate) -> RealityCaptureDataset:
        ds = RealityCaptureDataset(
            project_id=data.project_id,
            captured_at=data.captured_at,
            capture_type=data.capture_type,
            file_url=data.file_url,
            point_count_estimate=data.point_count_estimate,
            bbox_min=data.bbox_min,
            bbox_max=data.bbox_max,
            accuracy_mm=data.accuracy_mm,
            notes=data.notes,
            linked_bim_model_ref=data.linked_bim_model_ref,
        )
        ds = await self.reality_repo.create(ds)  # type: ignore[assignment]
        event_bus.publish_detached(
            "daily_diary.reality_capture.attached",
            {
                "reality_capture_id": str(ds.id),
                "project_id": str(data.project_id),
                "captured_at": data.captured_at.isoformat(),
                "capture_type": data.capture_type,
            },
            source_module="daily_diary",
        )
        return ds

    async def update_reality_capture(self, ds_id: uuid.UUID, data: RealityCaptureUpdate) -> RealityCaptureDataset:
        ds = await self.reality_repo.get_by_id(ds_id)
        if ds is None:
            raise HTTPException(
                status_code=404,
                detail="Reality capture dataset not found",
            )
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.reality_repo.update_fields(ds_id, **fields)
        return await self.reality_repo.get_by_id(ds_id)  # type: ignore[return-value]

    async def delete_reality_capture(self, ds_id: uuid.UUID) -> None:
        ds = await self.reality_repo.get_by_id(ds_id)
        if ds is None:
            raise HTTPException(
                status_code=404,
                detail="Reality capture dataset not found",
            )
        await self.reality_repo.delete(ds_id)

    # ── Completeness, hash, PDF stub ─────────────────────────────────────

    async def completeness_for(self, diary_id: uuid.UUID) -> dict[str, Any]:
        diary = await self.get_diary(diary_id)
        entries = await self.entry_repo.list_for_diary(diary_id)
        score = compute_diary_completeness(diary, entries)
        missing: list[str] = []
        for fld in _COMPLETENESS_FIELDS:
            v = getattr(diary, fld, None)
            if v in (None, "", 0, [], {}):
                missing.append(fld)
        if not entries:
            missing.append("entries")
        return {"diary_id": diary_id, "completeness": score, "missing": missing}

    async def immutable_payload_hash(self, diary_id: uuid.UUID) -> dict[str, Any]:
        diary = await self.get_diary(diary_id)
        entries = await self.entry_repo.list_for_diary(diary_id)
        # Single indexed query scoped to the diary (see ``sign_diary`` for
        # rationale). The previous project-wide fetch was an O(N) hit per
        # hash computation.
        photos = await self.photo_repo.photos_for_diary(diary_id)
        payload = compute_immutable_payload(diary, entries, photos)
        return {
            "diary_id": diary_id,
            "content_sha256": compute_content_sha256(payload),
            "payload_preview": {
                "schema_version": payload.get("schema_version"),
                "entries_count": len(payload.get("entries", [])),
                "photos_count": len(payload.get("photos", [])),
            },
        }

    async def generate_pdf_stub(self, diary_id: uuid.UUID) -> dict[str, Any]:
        """Hook for the future PDF renderer.

        Generates a deterministic placeholder UUID, stores it on the diary,
        and returns it. A future PDF service can pick the diary up by this
        reference.
        """
        diary = await self.get_diary(diary_id)
        if diary.pdf_export_ref is None:
            pdf_ref = uuid.uuid4()
            await self.diary_repo.update_fields(diary_id, pdf_export_ref=pdf_ref)
            await self.session.refresh(diary)
        else:
            pdf_ref = diary.pdf_export_ref
        return {
            "diary_id": diary_id,
            "pdf_export_ref": pdf_ref,
            "status": "stub",
        }

    # ── Real weather ingestion ───────────────────────────────────────────

    async def fetch_and_persist_weather(
        self,
        project_id: uuid.UUID,
        *,
        target_date: str,
        lat: float,
        lng: float,
        persist: bool = True,
    ) -> dict[str, Any]:
        """Fetch real weather from Open-Meteo and (optionally) persist it.

        Returns a dict describing what happened. If the upstream returned
        nothing, ``fetched=False`` and ``record_id`` is ``None``.
        """
        from app.modules.daily_diary.weather import fetch_weather_for_day

        try:
            target = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(422, f"Invalid target_date: {exc}") from exc

        summary = await fetch_weather_for_day(lat, lng, target)
        if not summary:
            return {
                "project_id": project_id,
                "target_date": target_date,
                "fetched": False,
                "record_id": None,
                "summary": {},
            }

        record_id: uuid.UUID | None = None
        if persist:
            record = WeatherRecord(
                project_id=project_id,
                captured_at=summary["captured_at"],
                source="open_meteo",
                temperature_c=summary.get("temperature_c"),
                humidity_pct=summary.get("humidity_pct"),
                wind_speed_kmh=summary.get("wind_speed_kmh"),
                precipitation_mm=summary.get("precipitation_mm"),
                conditions_code=summary.get("conditions_code"),
                conditions_text=summary.get("conditions_text"),
                sunrise=summary.get("sunrise"),
                sunset=summary.get("sunset"),
                location_lat=summary.get("location_lat"),
                location_lng=summary.get("location_lng"),
                metadata_={"rain_hours": summary.get("rain_hours", 0)},
            )
            record = await self.weather_repo.create(record)  # type: ignore[assignment]
            record_id = record.id

        return {
            "project_id": project_id,
            "target_date": target_date,
            "fetched": True,
            "record_id": record_id,
            "summary": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in summary.items()},
        }

    # ── Workforce summary event ──────────────────────────────────────────

    async def workforce_summary_for_diary(
        self,
        diary_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Aggregate the day's workforce/equipment counts from entries.

        Entry metadata is expected to carry ``labour_count`` /
        ``equipment_count`` integers and optionally a ``company`` label.
        """
        diary = await self.get_diary(diary_id)
        entries = await self.entry_repo.list_for_diary(diary_id)
        labour = int(diary.labour_count or 0)
        equipment = int(diary.equipment_count or 0)
        by_company: dict[str, int] = {}
        for e in entries:
            meta = e.metadata_ or {}
            if not isinstance(meta, dict):
                continue
            entry_labour = int(meta.get("labour_count", 0) or 0)
            entry_equipment = int(meta.get("equipment_count", 0) or 0)
            labour += entry_labour
            equipment += entry_equipment
            company = meta.get("company")
            if company and entry_labour:
                by_company[str(company)] = by_company.get(str(company), 0) + entry_labour
        return {
            "diary_id": diary_id,
            "project_id": diary.project_id,
            "diary_date": diary.diary_date,
            "labour_count": labour,
            "equipment_count": equipment,
            "by_company": by_company,
        }

    async def emit_workforce_summary(
        self,
        diary_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Compute the workforce summary AND publish to the event bus.

        Subscribers (e.g. the resources module) can fold this into a
        running utilisation metric.
        """
        summary = await self.workforce_summary_for_diary(diary_id)
        event_bus.publish_detached(
            "daily_diary.workforce.summary",
            {
                "diary_id": str(summary["diary_id"]),
                "project_id": str(summary["project_id"]),
                "diary_date": summary["diary_date"],
                "labour_count": summary["labour_count"],
                "equipment_count": summary["equipment_count"],
                "by_company": summary["by_company"],
            },
            source_module="daily_diary",
        )
        return summary

    # ── SCL Protocol contemporary-record bundle ──────────────────────────

    async def build_scl_bundle_manifest(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str,
        date_to: str,
    ) -> dict[str, Any]:
        """Build a deterministic manifest of a SCL Protocol bundle.

        The bundle itself (zip / PDF concatenation) is generated by the
        PDF renderer service in production. The manifest is the
        contractually meaningful artefact: a SHA-256 hash that pins the
        exact contents at extraction time.
        """
        if date_to < date_from:
            raise HTTPException(422, "date_to must be on or after date_from")
        diaries, _ = await self.diary_repo.list_by_project_in_range(
            project_id,
            date_from=date_from,
            date_to=date_to,
            limit=10_000,
        )
        from app.modules.daily_diary.service import (  # noqa: PLC0415 (self-import)
            compute_content_sha256,
        )

        # Photos in range
        try:
            df = datetime.fromisoformat(date_from)
        except ValueError:
            df = None
        try:
            dt = datetime.fromisoformat(date_to + "T23:59:59")
        except ValueError:
            dt = None
        photos, _ = await self.photo_repo.photos_for_project_in_range(
            project_id,
            date_from=df,
            date_to=dt,
            limit=10_000,
        )
        # Drones in range
        drones, _ = await self.drone_repo.list_for_project(
            project_id,
            limit=10_000,
        )
        if df is not None or dt is not None:
            kept: list = []
            for d in drones:
                fa = getattr(d, "flown_at", None)
                if isinstance(fa, str):
                    try:
                        fa_dt = datetime.fromisoformat(fa.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                else:
                    fa_dt = fa  # type: ignore[assignment]
                if fa_dt is None:
                    continue
                if df is not None and fa_dt < df:
                    continue
                if dt is not None and fa_dt > dt:
                    continue
                kept.append(d)
            drones = kept

        # Weather records in range — a single ranged query (no N+1, and no
        # fragile LIKE against a typed DateTime column which breaks on
        # PostgreSQL). The range mirrors the photo/drone window so the
        # sealed bundle is internally consistent.
        from sqlalchemy import select  # noqa: PLC0415 (local import)

        weather_stmt = select(WeatherRecord).where(WeatherRecord.project_id == project_id)
        if df is not None:
            weather_stmt = weather_stmt.where(WeatherRecord.captured_at >= df)
        if dt is not None:
            weather_stmt = weather_stmt.where(WeatherRecord.captured_at <= dt)
        weathers = list((await self.session.execute(weather_stmt)).scalars().all())

        # Build deterministic manifest contents
        contents: list[dict[str, Any]] = []
        for diary in sorted(diaries, key=lambda d: d.diary_date):
            contents.append(
                {
                    "kind": "diary",
                    "diary_id": str(diary.id),
                    "diary_date": diary.diary_date,
                    "status": diary.status,
                }
            )
        for w in sorted(weathers, key=lambda x: x.captured_at):
            contents.append(
                {
                    "kind": "weather",
                    "weather_id": str(w.id),
                    "captured_at": w.captured_at,
                    "source": w.source,
                }
            )
        for ph in sorted(photos, key=lambda x: str(x.taken_at)):
            contents.append(
                {
                    "kind": "photo",
                    "photo_id": str(ph.id),
                    "taken_at": str(ph.taken_at),
                    "file_url": ph.file_url,
                }
            )
        for dr in sorted(drones, key=lambda x: str(x.flown_at)):
            contents.append(
                {
                    "kind": "drone",
                    "survey_id": str(dr.id),
                    "flown_at": str(dr.flown_at),
                    "ortho_file_url": dr.ortho_file_url,
                }
            )

        manifest_payload = {
            "project_id": str(project_id),
            "date_from": date_from,
            "date_to": date_to,
            "schema_version": 1,
            "contents": contents,
        }
        bundle_hash = compute_content_sha256(manifest_payload)

        return {
            "project_id": project_id,
            "date_from": date_from,
            "date_to": date_to,
            "diary_count": len(diaries),
            "weather_record_count": len(weathers),
            # Counts MUST match what is actually sealed into ``contents``
            # (and therefore the hash). ``photo_total`` is the repository's
            # pre-truncation total and can exceed the number of rows
            # actually folded into the bundle.
            "photo_count": len(photos),
            "drone_survey_count": len(drones),
            "bundle_sha256": bundle_hash,
            "contents": contents,
        }
