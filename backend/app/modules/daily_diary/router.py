# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Daily Site Diary API routes.

Mounted at ``/api/v1/daily-diary/``. Each endpoint is guarded by a
``RequirePermission(...)`` dependency. Project access checks are
performed through :func:`verify_project_access` for endpoints that
operate on a project context.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse

from app.core.content_disposition import attachment_disposition
from app.core.file_signature import (
    ALLOWED_PHOTO_TYPES,
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
)
from app.core.file_signature import (
    require as require_signature,
)
from app.core.i18n import get_locale
from app.core.offline_merge import (
    MergeAuditOut,
    MergeSpec,
    OfflineMergeRequest,
    OfflineMergeResponse,
    apply_merge,
    find_by_client_op_id,
    list_merge_audit,
    stamp_client_op_id,
)
from app.core.optimistic_lock import bump, check_version, resolve_expected_version
from app.core.validation.messages import translate
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.daily_diary.models import DailyDiary, DiaryEntry
from app.modules.daily_diary.pdf_translations import diary_pdf_filename, resolve_pdf_locale
from app.modules.daily_diary.schemas import (
    BeforeAfterResponse,
    DailyDiaryCreate,
    DailyDiaryListResponse,
    DailyDiaryResponse,
    DailyDiaryUpdate,
    DiaryArchiveSignatureResponse,
    DiaryCompletenessResponse,
    DiaryDashboardResponse,
    DiaryEntryBulkCreate,
    DiaryEntryCreate,
    DiaryEntryListResponse,
    DiaryEntryResponse,
    DiaryEntryUpdate,
    DiaryImmutablePayloadHashResponse,
    DiaryPhotoCreate,
    DiaryPhotoListResponse,
    DiaryPhotoResponse,
    DiaryPhotoUpdate,
    DiarySignRequest,
    DiaryVideoCreate,
    DiaryVideoResponse,
    DiaryVideoUpdate,
    DroneSurveyCreate,
    DroneSurveyResponse,
    DroneSurveyUpdate,
    ExifGPSRequest,
    ExifGPSResponse,
    PhotoPair,
    PhotoTimelineBucket,
    PhotoTimelineResponse,
    ProductivityFactorRequest,
    ProductivityFactorResponse,
    RealityCaptureCreate,
    RealityCaptureResponse,
    RealityCaptureUpdate,
    SCLBundleManifest,
    SCLBundleRequest,
    WeatherFetchRequest,
    WeatherFetchResponse,
    WeatherRecordCreate,
    WeatherRecordResponse,
    WeatherRecordUpdate,
    WorkforceSummary,
)
from app.modules.daily_diary.service import (
    DailyDiaryService,
    compute_before_after,
    compute_photo_timeline,
)
from app.modules.daily_diary.weather import (
    compute_productivity_factor,
    extract_exif_gps,
    list_supported_trades,
)

router = APIRouter(tags=["daily_diary"])


def _get_service(session: SessionDep) -> DailyDiaryService:
    return DailyDiaryService(session)


_DIARY_MERGE = MergeSpec(
    entity_type="daily_diary",
    module="daily_diary",
    fields={"notes": "text", "labour_count": "int", "equipment_count": "int", "weather_summary": "dict"},
    long_text_fields=frozenset({"notes"}),
)
_ENTRY_MERGE = MergeSpec(
    entity_type="daily_diary_entry",
    module="daily_diary",
    fields={"title": "str", "description": "text", "photo_ids": "list"},
    long_text_fields=frozenset({"description"}),
    list_fields=frozenset({"photo_ids"}),
)


# ── Diaries ──────────────────────────────────────────────────────────────


@router.get("/diaries/", response_model=DailyDiaryListResponse)
async def list_diaries(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DailyDiaryListResponse:
    """List daily diaries for a project, one page plus the matching total."""
    await verify_project_access(project_id, user_id, session)
    items, total = await service.list_diaries(
        project_id,
        date_from=date_from,
        date_to=date_to,
        status_filter=status_filter,
        offset=offset,
        limit=limit,
    )
    return DailyDiaryListResponse(
        items=[DailyDiaryResponse.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/diaries/", response_model=DailyDiaryResponse, status_code=201)
async def create_diary(
    data: DailyDiaryCreate,
    session: SessionDep,
    response: Response,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.create")),
    service: DailyDiaryService = Depends(_get_service),
) -> DailyDiaryResponse:
    """Create a new daily diary (one per project per date).

    A repeated ``client_op_id`` returns the diary created the first time (200).
    """
    await verify_project_access(data.project_id, user_id, session)
    earlier = await find_by_client_op_id(
        session, DailyDiary, data.client_op_id, DailyDiary.project_id == data.project_id
    )
    if earlier is not None:
        response.status_code = 200
        return DailyDiaryResponse.model_validate(earlier)
    diary = await service.create_diary(data, user_id=user_id)
    await stamp_client_op_id(session, diary, data.client_op_id)
    return DailyDiaryResponse.model_validate(diary)


@router.get("/diaries/{diary_id}", response_model=DailyDiaryResponse)
async def get_diary(
    diary_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DailyDiaryResponse:
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    return DailyDiaryResponse.model_validate(diary)


@router.patch("/diaries/{diary_id}", response_model=DailyDiaryResponse)
async def update_diary(
    diary_id: uuid.UUID,
    data: DailyDiaryUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    if_match: Annotated[str | None, Header()] = None,
    _perm: None = Depends(RequirePermission("daily_diary.update")),
    service: DailyDiaryService = Depends(_get_service),
) -> DailyDiaryResponse:
    """Update a diary. A stale ``If-Match`` (or body ``version``) answers 409 with the current row."""
    existing = await service.get_diary(diary_id)
    await verify_project_access(existing.project_id, user_id, session)
    check_version(
        existing.version,
        resolve_expected_version(if_match, data.version),
        DailyDiaryResponse.model_validate(existing).model_dump(mode="json"),
    )
    diary = await service.update_diary(diary_id, data)
    bump(diary)
    await session.flush()
    return DailyDiaryResponse.model_validate(diary)


@router.post("/diaries/{diary_id}/merge/", response_model=OfflineMergeResponse)
async def merge_diary(
    diary_id: uuid.UUID,
    data: OfflineMergeRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.update")),
    service: DailyDiaryService = Depends(_get_service),
) -> OfflineMergeResponse:
    """Apply a conflict resolution made on a device against the current version."""
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    if diary.status in ("signed", "archived"):
        await service.update_diary(diary_id, DailyDiaryUpdate())  # raises the signed-immutable 409
    version, merged = await apply_merge(
        session,
        diary,
        _DIARY_MERGE,
        data,
        actor_id=str(user_id) if user_id else None,
        project_id=diary.project_id,
        current_payload=DailyDiaryResponse.model_validate(diary).model_dump(mode="json"),
    )
    return OfflineMergeResponse(
        version=version,
        merged=merged,
        item=DailyDiaryResponse.model_validate(diary).model_dump(mode="json"),
    )


@router.get("/diaries/{diary_id}/merge-audit/", response_model=list[MergeAuditOut])
async def diary_merge_audit(
    diary_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> list[MergeAuditOut]:
    """What offline merges changed on this diary, field by field."""
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    return await list_merge_audit(session, _DIARY_MERGE.entity_type, diary_id)


@router.delete("/diaries/{diary_id}", status_code=204)
async def delete_diary(
    diary_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.delete")),
    service: DailyDiaryService = Depends(_get_service),
) -> None:
    existing = await service.get_diary(diary_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_diary(diary_id)


@router.post("/diaries/{diary_id}/close", response_model=DailyDiaryResponse)
async def close_diary(
    diary_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.close")),
    service: DailyDiaryService = Depends(_get_service),
) -> DailyDiaryResponse:
    existing = await service.get_diary(diary_id)
    await verify_project_access(existing.project_id, user_id, session)
    diary = await service.close_diary(diary_id, user_id=user_id)
    return DailyDiaryResponse.model_validate(diary)


@router.post(
    "/diaries/{diary_id}/sign",
    response_model=DiaryArchiveSignatureResponse,
)
async def sign_diary(
    diary_id: uuid.UUID,
    payload: DiarySignRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.sign")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryArchiveSignatureResponse:
    existing = await service.get_diary(diary_id)
    await verify_project_access(existing.project_id, user_id, session)
    signature = await service.sign_diary(
        diary_id,
        signer_role=payload.signer_role,
        signer_name=payload.signer_name,
        signature_data=payload.signature_data,
        algorithm=payload.algorithm,
        user_id=user_id,
    )
    return DiaryArchiveSignatureResponse.model_validate(signature)


@router.post("/diaries/{diary_id}/unlock", response_model=DailyDiaryResponse)
async def unlock_diary(
    diary_id: uuid.UUID,
    session: SessionDep,
    reason: str | None = Query(default=None, max_length=2000),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.unlock")),
    service: DailyDiaryService = Depends(_get_service),
) -> DailyDiaryResponse:
    """Re-open a signed diary so a manager can amend it.

    The original archive signature is preserved (its hash continues to
    point at the pre-edit snapshot) so the integrity break is forensic
    and traceable. An archived diary cannot be unlocked - see the 409
    body ``code=diary_archived_cannot_unlock`` for that case.
    """
    existing = await service.get_diary(diary_id)
    await verify_project_access(existing.project_id, user_id, session)
    diary = await service.unlock_diary(
        diary_id,
        user_id=user_id,
        reason=reason,
    )
    return DailyDiaryResponse.model_validate(diary)


@router.post("/diaries/{diary_id}/archive", response_model=DailyDiaryResponse)
async def archive_diary(
    diary_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.archive")),
    service: DailyDiaryService = Depends(_get_service),
) -> DailyDiaryResponse:
    existing = await service.get_diary(diary_id)
    await verify_project_access(existing.project_id, user_id, session)
    diary = await service.archive_diary(diary_id, user_id=user_id)
    return DailyDiaryResponse.model_validate(diary)


@router.get(
    "/diaries/{diary_id}/completeness",
    response_model=DiaryCompletenessResponse,
)
async def diary_completeness(
    diary_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryCompletenessResponse:
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    data = await service.completeness_for(diary_id)
    return DiaryCompletenessResponse(**data)


@router.get(
    "/diaries/{diary_id}/immutable-payload-hash",
    response_model=DiaryImmutablePayloadHashResponse,
)
async def immutable_payload_hash(
    diary_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryImmutablePayloadHashResponse:
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    data = await service.immutable_payload_hash(diary_id)
    return DiaryImmutablePayloadHashResponse(**data)


@router.get("/diaries/{diary_id}/pdf")
async def diary_pdf(
    diary_id: uuid.UUID,
    session: SessionDep,
    locale: Annotated[
        str | None,
        Query(max_length=10, description="Force the PDF language (e.g. 'de'). Overrides Accept-Language."),
    ] = None,
    accept_language: Annotated[str | None, Header(alias="accept-language")] = None,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> StreamingResponse:
    """Export a daily site diary as a PDF document.

    Renders the diary header, its entries, the day's weather, the
    project and supervisor names, and the notes into a single PDF and
    streams it back as an attachment named ``diary-<date>.pdf``
    (``bautagebuch-<date>.pdf`` for German).

    The document language follows the ``?locale=`` query parameter when
    given, otherwise the ``Accept-Language`` header (primary subtag
    match), otherwise English - the same resolution the cost endpoints
    use.
    """
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    pdf_locale = resolve_pdf_locale(locale, accept_language)
    pdf_bytes, diary_date = await service.generate_diary_pdf(diary_id, locale=pdf_locale)
    filename = diary_pdf_filename(str(diary_date or diary_id), pdf_locale)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": attachment_disposition(filename),
            # The language this document is written in, which is not always the
            # one the reader asked for: the diary catalogue is narrower than the
            # interface's locale list. Declaring it here overrides the
            # request-derived header the Accept-Language middleware would
            # otherwise apply, so a fallback to English is visible to the client.
            "Content-Language": pdf_locale,
        },
    )


# ── Weather ──────────────────────────────────────────────────────────────


@router.get("/weather/today", response_model=list[WeatherRecordResponse])
async def weather_today(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    day: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> list[WeatherRecordResponse]:
    """Weather records for a single calendar day (defaults to today, UTC).

    ``day`` must be a ``YYYY-MM-DD`` string; the diary UI passes the
    currently-viewed diary's date so a back-dated diary shows *its* weather
    rather than the most-recent reading of any date.
    """
    await verify_project_access(project_id, user_id, session)
    items = await service.weather_for_day(project_id, day)
    return [WeatherRecordResponse.model_validate(i) for i in items]


@router.post(
    "/weather-records/",
    response_model=WeatherRecordResponse,
    status_code=201,
)
async def create_weather_record(
    data: WeatherRecordCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.create")),
    service: DailyDiaryService = Depends(_get_service),
) -> WeatherRecordResponse:
    await verify_project_access(data.project_id, user_id, session)
    record = await service.create_weather(data)
    return WeatherRecordResponse.model_validate(record)


@router.get(
    "/weather-records/{weather_id}",
    response_model=WeatherRecordResponse,
)
async def get_weather_record(
    weather_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> WeatherRecordResponse:
    record = await service.get_weather(weather_id)
    await verify_project_access(record.project_id, user_id, session)
    return WeatherRecordResponse.model_validate(record)


@router.patch(
    "/weather-records/{weather_id}",
    response_model=WeatherRecordResponse,
)
async def update_weather_record(
    weather_id: uuid.UUID,
    data: WeatherRecordUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.update")),
    service: DailyDiaryService = Depends(_get_service),
) -> WeatherRecordResponse:
    existing = await service.get_weather(weather_id)
    await verify_project_access(existing.project_id, user_id, session)
    record = await service.update_weather(weather_id, data)
    return WeatherRecordResponse.model_validate(record)


@router.delete("/weather-records/{weather_id}", status_code=204)
async def delete_weather_record(
    weather_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.delete")),
    service: DailyDiaryService = Depends(_get_service),
) -> None:
    existing = await service.get_weather(weather_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_weather(weather_id)


# ── Entries ──────────────────────────────────────────────────────────────


@router.post(
    "/diary-entries/",
    response_model=DiaryEntryResponse,
    status_code=201,
)
async def create_entry(
    data: DiaryEntryCreate,
    session: SessionDep,
    response: Response,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.create")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryEntryResponse:
    """Create an entry. A repeated ``client_op_id`` returns the first entry (200)."""
    diary = await service.get_diary(data.diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    earlier = await find_by_client_op_id(session, DiaryEntry, data.client_op_id, DiaryEntry.diary_id == data.diary_id)
    if earlier is not None:
        response.status_code = 200
        return DiaryEntryResponse.model_validate(earlier)
    entry = await service.create_entry(data)
    await stamp_client_op_id(session, entry, data.client_op_id)
    return DiaryEntryResponse.model_validate(entry)


@router.get(
    "/diaries/{diary_id}/entries",
    response_model=DiaryEntryListResponse,
)
async def list_entries(
    diary_id: uuid.UUID,
    session: SessionDep,
    entry_type: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryEntryListResponse:
    """List a diary's entries, chronologically (entry_time asc), one page.

    ``offset`` and ``limit`` are new here: this route used to take neither and
    returned however many entries the diary held. A day's diary is small, but
    the bulk-create route below can write a whole month into one, and an
    endpoint whose response size is set by the data alone has no ceiling at
    all. The bound matches the photos route in this module; ``total`` says
    what it cut, so a client can tell a whole day from part of one.
    """
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    entries, total = await service.page_entries(
        diary_id,
        entry_type=entry_type,
        offset=offset,
        limit=limit,
    )
    return DiaryEntryListResponse(
        items=[DiaryEntryResponse.model_validate(e) for e in entries],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/diaries/{diary_id}/entries/bulk",
    response_model=list[DiaryEntryResponse],
    status_code=201,
)
async def bulk_create_entries(
    diary_id: uuid.UUID,
    payloads: list[DiaryEntryBulkCreate],
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.create")),
    service: DailyDiaryService = Depends(_get_service),
) -> list[DiaryEntryResponse]:
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    raw = [p.model_dump() for p in payloads]
    entries = await service.bulk_create_entries(diary_id, raw)
    return [DiaryEntryResponse.model_validate(e) for e in entries]


@router.get(
    "/diary-entries/{entry_id}",
    response_model=DiaryEntryResponse,
)
async def get_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryEntryResponse:
    entry = await service.get_entry(entry_id)
    diary = await service.get_diary(entry.diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    return DiaryEntryResponse.model_validate(entry)


@router.patch(
    "/diary-entries/{entry_id}",
    response_model=DiaryEntryResponse,
)
async def update_entry(
    entry_id: uuid.UUID,
    data: DiaryEntryUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    if_match: Annotated[str | None, Header()] = None,
    _perm: None = Depends(RequirePermission("daily_diary.update")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryEntryResponse:
    """Update an entry. A stale ``If-Match`` (or body ``version``) answers 409 with the current row."""
    existing = await service.get_entry(entry_id)
    diary = await service.get_diary(existing.diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    check_version(
        existing.version,
        resolve_expected_version(if_match, data.version),
        DiaryEntryResponse.model_validate(existing).model_dump(mode="json"),
    )
    entry = await service.update_entry(entry_id, data.model_dump(exclude_unset=True))
    bump(entry)
    await session.flush()
    return DiaryEntryResponse.model_validate(entry)


@router.post("/diary-entries/{entry_id}/merge/", response_model=OfflineMergeResponse)
async def merge_entry(
    entry_id: uuid.UUID,
    data: OfflineMergeRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.update")),
    service: DailyDiaryService = Depends(_get_service),
) -> OfflineMergeResponse:
    """Apply a conflict resolution made on a device against the current version."""
    entry = await service.get_entry(entry_id)
    diary = await service._assert_entry_diary_mutable(entry)  # noqa: SLF001
    await verify_project_access(diary.project_id, user_id, session)
    version, merged = await apply_merge(
        session,
        entry,
        _ENTRY_MERGE,
        data,
        actor_id=str(user_id) if user_id else None,
        project_id=diary.project_id,
        current_payload=DiaryEntryResponse.model_validate(entry).model_dump(mode="json"),
    )
    return OfflineMergeResponse(
        version=version,
        merged=merged,
        item=DiaryEntryResponse.model_validate(entry).model_dump(mode="json"),
    )


@router.get("/diary-entries/{entry_id}/merge-audit/", response_model=list[MergeAuditOut])
async def entry_merge_audit(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> list[MergeAuditOut]:
    """What offline merges changed on this entry, field by field."""
    entry = await service.get_entry(entry_id)
    diary = await service.get_diary(entry.diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    return await list_merge_audit(session, _ENTRY_MERGE.entity_type, entry_id)


@router.delete("/diary-entries/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.delete")),
    service: DailyDiaryService = Depends(_get_service),
) -> None:
    entry = await service.get_entry(entry_id)
    diary = await service.get_diary(entry.diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    await service.delete_entry(entry_id)


# ── Photos ───────────────────────────────────────────────────────────────


@router.get("/photos/", response_model=DiaryPhotoListResponse)
async def list_photos(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryPhotoListResponse:
    """List diary photos for a project, one page plus the matching total."""
    await verify_project_access(project_id, user_id, session)
    items, total = await service.photo_repo.photos_for_project_in_range(
        project_id,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )
    return DiaryPhotoListResponse(
        items=[DiaryPhotoResponse.model_validate(i) for i in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/photos/timeline", response_model=PhotoTimelineResponse)
async def photo_timeline(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> PhotoTimelineResponse:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.photo_repo.photos_for_project_in_range(
        project_id,
        date_from=date_from,
        date_to=date_to,
        limit=10_000,
    )
    buckets = compute_photo_timeline(project_id, items, date_from, date_to)
    return PhotoTimelineResponse(
        project_id=project_id,
        buckets=[PhotoTimelineBucket(**b) for b in buckets],
    )


@router.post(
    "/photos/before-after",
    response_model=BeforeAfterResponse,
)
async def photos_before_after(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    date_a: datetime = Query(...),
    date_b: datetime = Query(...),
    location_radius_m: float = Query(default=15.0, ge=0, le=10000),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> BeforeAfterResponse:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.photo_repo.photos_for_project_in_range(
        project_id,
        limit=10_000,
    )
    pairs = compute_before_after(items, date_a, date_b, location_radius_m)
    return BeforeAfterResponse(
        project_id=project_id,
        pairs=[PhotoPair(**p) for p in pairs],
    )


@router.post(
    "/diary-photos/",
    response_model=DiaryPhotoResponse,
    status_code=201,
)
async def upload_photo(
    data: DiaryPhotoCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.upload_photo")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryPhotoResponse:
    await verify_project_access(data.project_id, user_id, session)
    photo = await service.register_photo(data)
    return DiaryPhotoResponse.model_validate(photo)


@router.get(
    "/diary-photos/{photo_id}",
    response_model=DiaryPhotoResponse,
)
async def get_photo(
    photo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryPhotoResponse:
    photo = await service.photo_repo.get_by_id(photo_id)
    if photo is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=translate("errors.diary_photo_not_found", locale=get_locale()))
    await verify_project_access(photo.project_id, user_id, session)
    return DiaryPhotoResponse.model_validate(photo)


@router.patch(
    "/diary-photos/{photo_id}",
    response_model=DiaryPhotoResponse,
)
async def update_photo(
    photo_id: uuid.UUID,
    data: DiaryPhotoUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.update")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryPhotoResponse:
    existing = await service.photo_repo.get_by_id(photo_id)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=translate("errors.diary_photo_not_found", locale=get_locale()))
    await verify_project_access(existing.project_id, user_id, session)
    photo = await service.update_photo(photo_id, data)
    return DiaryPhotoResponse.model_validate(photo)


@router.delete("/diary-photos/{photo_id}", status_code=204)
async def delete_photo(
    photo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.delete")),
    service: DailyDiaryService = Depends(_get_service),
) -> None:
    existing = await service.photo_repo.get_by_id(photo_id)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=translate("errors.diary_photo_not_found", locale=get_locale()))
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_photo(photo_id)


# ── Videos ───────────────────────────────────────────────────────────────


@router.get("/diary-videos/", response_model=list[DiaryVideoResponse])
async def list_videos(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> list[DiaryVideoResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.video_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
    )
    return [DiaryVideoResponse.model_validate(i) for i in items]


@router.post(
    "/diary-videos/",
    response_model=DiaryVideoResponse,
    status_code=201,
)
async def create_video(
    data: DiaryVideoCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.create")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryVideoResponse:
    await verify_project_access(data.project_id, user_id, session)
    video = await service.create_video(data)
    return DiaryVideoResponse.model_validate(video)


@router.get(
    "/diary-videos/{video_id}",
    response_model=DiaryVideoResponse,
)
async def get_video(
    video_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryVideoResponse:
    video = await service.video_repo.get_by_id(video_id)
    if video is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=translate("errors.diary_video_not_found", locale=get_locale()))
    await verify_project_access(video.project_id, user_id, session)
    return DiaryVideoResponse.model_validate(video)


@router.patch(
    "/diary-videos/{video_id}",
    response_model=DiaryVideoResponse,
)
async def update_video(
    video_id: uuid.UUID,
    data: DiaryVideoUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.update")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryVideoResponse:
    existing = await service.video_repo.get_by_id(video_id)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=translate("errors.diary_video_not_found", locale=get_locale()))
    await verify_project_access(existing.project_id, user_id, session)
    video = await service.update_video(video_id, data)
    return DiaryVideoResponse.model_validate(video)


@router.delete("/diary-videos/{video_id}", status_code=204)
async def delete_video(
    video_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.delete")),
    service: DailyDiaryService = Depends(_get_service),
) -> None:
    existing = await service.video_repo.get_by_id(video_id)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=translate("errors.diary_video_not_found", locale=get_locale()))
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_video(video_id)


# ── Drone surveys ────────────────────────────────────────────────────────


@router.get("/drone-surveys/", response_model=list[DroneSurveyResponse])
async def list_drone_surveys(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> list[DroneSurveyResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.drone_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
    )
    return [DroneSurveyResponse.model_validate(i) for i in items]


@router.post(
    "/drone-surveys/",
    response_model=DroneSurveyResponse,
    status_code=201,
)
async def create_drone_survey(
    data: DroneSurveyCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.attach_drone")),
    service: DailyDiaryService = Depends(_get_service),
) -> DroneSurveyResponse:
    await verify_project_access(data.project_id, user_id, session)
    survey = await service.attach_drone_survey(data)
    return DroneSurveyResponse.model_validate(survey)


@router.get(
    "/drone-surveys/{survey_id}",
    response_model=DroneSurveyResponse,
)
async def get_drone_survey(
    survey_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DroneSurveyResponse:
    survey = await service.drone_repo.get_by_id(survey_id)
    if survey is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=translate("errors.survey_not_found", locale=get_locale()))
    await verify_project_access(survey.project_id, user_id, session)
    return DroneSurveyResponse.model_validate(survey)


@router.patch(
    "/drone-surveys/{survey_id}",
    response_model=DroneSurveyResponse,
)
async def update_drone_survey(
    survey_id: uuid.UUID,
    data: DroneSurveyUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.update")),
    service: DailyDiaryService = Depends(_get_service),
) -> DroneSurveyResponse:
    existing = await service.drone_repo.get_by_id(survey_id)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=translate("errors.survey_not_found", locale=get_locale()))
    await verify_project_access(existing.project_id, user_id, session)
    survey = await service.update_drone_survey(survey_id, data)
    return DroneSurveyResponse.model_validate(survey)


@router.delete("/drone-surveys/{survey_id}", status_code=204)
async def delete_drone_survey(
    survey_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.delete")),
    service: DailyDiaryService = Depends(_get_service),
) -> None:
    existing = await service.drone_repo.get_by_id(survey_id)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=translate("errors.survey_not_found", locale=get_locale()))
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_drone_survey(survey_id)


# ── Reality capture ──────────────────────────────────────────────────────


@router.get(
    "/reality-captures/",
    response_model=list[RealityCaptureResponse],
)
async def list_reality_captures(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> list[RealityCaptureResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.reality_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
    )
    return [RealityCaptureResponse.model_validate(i) for i in items]


@router.post(
    "/reality-captures/",
    response_model=RealityCaptureResponse,
    status_code=201,
)
async def create_reality_capture(
    data: RealityCaptureCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.attach_reality_capture")),
    service: DailyDiaryService = Depends(_get_service),
) -> RealityCaptureResponse:
    await verify_project_access(data.project_id, user_id, session)
    ds = await service.attach_reality_capture(data)
    return RealityCaptureResponse.model_validate(ds)


@router.get(
    "/reality-captures/{ds_id}",
    response_model=RealityCaptureResponse,
)
async def get_reality_capture(
    ds_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> RealityCaptureResponse:
    ds = await service.reality_repo.get_by_id(ds_id)
    if ds is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Reality capture not found")
    await verify_project_access(ds.project_id, user_id, session)
    return RealityCaptureResponse.model_validate(ds)


@router.patch(
    "/reality-captures/{ds_id}",
    response_model=RealityCaptureResponse,
)
async def update_reality_capture(
    ds_id: uuid.UUID,
    data: RealityCaptureUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.update")),
    service: DailyDiaryService = Depends(_get_service),
) -> RealityCaptureResponse:
    existing = await service.reality_repo.get_by_id(ds_id)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Reality capture not found")
    await verify_project_access(existing.project_id, user_id, session)
    ds = await service.update_reality_capture(ds_id, data)
    return RealityCaptureResponse.model_validate(ds)


@router.delete("/reality-captures/{ds_id}", status_code=204)
async def delete_reality_capture(
    ds_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.delete")),
    service: DailyDiaryService = Depends(_get_service),
) -> None:
    existing = await service.reality_repo.get_by_id(ds_id)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Reality capture not found")
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_reality_capture(ds_id)


# ── Archive signatures (read-only) ───────────────────────────────────────


@router.get(
    "/archive-signatures/",
    response_model=list[DiaryArchiveSignatureResponse],
)
async def list_archive_signatures(
    session: SessionDep,
    diary_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> list[DiaryArchiveSignatureResponse]:
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    items = await service.signature_repo.signatures_for_diary(diary_id)
    return [DiaryArchiveSignatureResponse.model_validate(i) for i in items]


@router.get(
    "/archive-signatures/{signature_id}",
    response_model=DiaryArchiveSignatureResponse,
)
async def get_archive_signature(
    signature_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryArchiveSignatureResponse:
    sig = await service.signature_repo.get_by_id(signature_id)
    if sig is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Archive signature not found")
    diary = await service.get_diary(sig.diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    return DiaryArchiveSignatureResponse.model_validate(sig)


# ── Dashboard ────────────────────────────────────────────────────────────


# ── Real weather fetch (Open-Meteo) ──────────────────────────────────────


@router.post("/weather/fetch", response_model=WeatherFetchResponse)
async def fetch_weather(
    payload: WeatherFetchRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.fetch_weather")),
    service: DailyDiaryService = Depends(_get_service),
) -> WeatherFetchResponse:
    """Fetch real weather from Open-Meteo for (project, date) and persist it."""
    await verify_project_access(payload.project_id, user_id, session)
    data = await service.fetch_and_persist_weather(
        payload.project_id,
        target_date=payload.target_date,
        lat=payload.lat,
        lng=payload.lng,
        persist=payload.persist,
    )
    return WeatherFetchResponse(**data)


# ── Productivity factor (trade-aware) ────────────────────────────────────


@router.get("/productivity/trades", response_model=list[str])
async def list_productivity_trades(
    _perm: None = Depends(RequirePermission("daily_diary.read")),
) -> list[str]:
    """List trades supported by the productivity-factor calculator."""
    return list_supported_trades()


@router.post(
    "/productivity/compute",
    response_model=ProductivityFactorResponse,
)
async def compute_productivity(
    payload: ProductivityFactorRequest,
    _perm: None = Depends(RequirePermission("daily_diary.read")),
) -> ProductivityFactorResponse:
    """Compute the productivity factor for a trade given weather inputs."""
    result = compute_productivity_factor(
        trade=payload.trade,
        rain_hours=payload.rain_hours,
        precipitation_mm=payload.precipitation_mm,
        temperature_c=payload.temperature_c,
        wind_speed_kmh=payload.wind_speed_kmh,
        working_hours=payload.working_hours,
    )
    return ProductivityFactorResponse(
        trade=result["trade"],
        factor=float(result["factor"]),
        stopped=result["stopped"],
        reason=result["reason"],
        lost_hours=float(result["lost_hours"]),
    )


# ── EXIF GPS extraction ───────────────────────────────────────────────────


@router.post("/photos/extract-gps", response_model=ExifGPSResponse)
async def extract_photo_gps(
    payload: ExifGPSRequest,
    _perm: None = Depends(RequirePermission("daily_diary.upload_photo")),
) -> ExifGPSResponse:
    """Extract GPS coordinates from an uploaded image's EXIF metadata.

    The base64 payload is gated by magic-byte detection against the photo
    allow-list (jpeg/png/gif/webp/heic/heif/tiff). SVG, scripts, PE / ELF
    binaries - anything that is not an actual raster image - is rejected
    with 415 BEFORE Pillow ever sees the bytes. This stops a caller from
    using the EXIF endpoint as a generic file-sniffer / parser-fuzz vector.
    """
    import base64

    try:
        raw = base64.b64decode(payload.image_base64, validate=True)
    except (ValueError, TypeError) as exc:
        from fastapi import HTTPException

        raise HTTPException(422, f"Invalid base64 image: {exc}") from exc
    # Magic-byte gate FIRST - Pillow is happy to attempt to decode all sorts
    # of formats and an attacker-shaped payload could exercise its parsers
    # in unexpected ways. The detector reads only the first 16 bytes.
    try:
        require_signature(
            raw[:SIGNATURE_BYTES_REQUIRED],
            ALLOWED_PHOTO_TYPES,
        )
    except FileSignatureMismatch as exc:
        from fastapi import HTTPException

        raise HTTPException(415, str(exc)) from exc
    gps = extract_exif_gps(raw)
    if gps is None:
        return ExifGPSResponse(found=False)
    return ExifGPSResponse(
        found=True,
        lat=gps.get("lat"),
        lng=gps.get("lng"),
        altitude_m=gps.get("altitude_m"),
        timestamp=gps.get("timestamp"),
    )


# ── Workforce summary (cross-module event) ────────────────────────────────


@router.get(
    "/diaries/{diary_id}/workforce-summary",
    response_model=WorkforceSummary,
)
async def diary_workforce_summary(
    diary_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> WorkforceSummary:
    """Aggregated labour + equipment counts for a single diary."""
    diary = await service.get_diary(diary_id)
    await verify_project_access(diary.project_id, user_id, session)
    data = await service.workforce_summary_for_diary(diary_id)
    return WorkforceSummary(**data)


# ── SCL Protocol bundle ───────────────────────────────────────────────────


@router.post("/exports/scl-bundle", response_model=SCLBundleManifest)
async def export_scl_bundle(
    payload: SCLBundleRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.export_scl_bundle")),
    service: DailyDiaryService = Depends(_get_service),
) -> SCLBundleManifest:
    """SCL Protocol contemporary-record bundle manifest (hash-sealed)."""
    await verify_project_access(payload.project_id, user_id, session)
    data = await service.build_scl_bundle_manifest(
        payload.project_id,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    return SCLBundleManifest(**data)


@router.get("/dashboard", response_model=DiaryDashboardResponse)
async def diary_dashboard(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("daily_diary.read")),
    service: DailyDiaryService = Depends(_get_service),
) -> DiaryDashboardResponse:
    await verify_project_access(project_id, user_id, session)
    diaries, total = await service.diary_repo.list_by_project_in_range(
        project_id,
        limit=10_000,
    )
    counts = {"open": 0, "closed": 0, "signed": 0, "archived": 0}
    by_date: dict[str, int] = {}
    for d in diaries:
        counts[d.status] = counts.get(d.status, 0) + 1
        by_date[d.diary_date] = by_date.get(d.diary_date, 0) + 1
    photos, photos_total = await service.photo_repo.photos_for_project_in_range(
        project_id,
        limit=1,
    )
    drone, drone_total = await service.drone_repo.list_for_project(
        project_id,
        limit=1,
    )
    reality, reality_total = await service.reality_repo.list_for_project(
        project_id,
        limit=1,
    )
    return DiaryDashboardResponse(
        total_diaries=total,
        open_count=counts["open"],
        closed_count=counts["closed"],
        signed_count=counts["signed"],
        archived_count=counts["archived"],
        photos_total=photos_total,
        drone_surveys_total=drone_total,
        reality_captures_total=reality_total,
        diaries_by_date=by_date,
    )
