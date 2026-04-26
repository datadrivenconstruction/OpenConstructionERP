"""Dashboards module API router.

Endpoints land incrementally as each task in ``CLAUDE-DASHBOARDS.md``
ships. T01 adds the snapshot registry; T02–T11 will hang off the same
router but at different paths.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse

from app.dependencies import CurrentUserPayload, SessionDep
from app.modules.dashboards import messages
from app.modules.dashboards.cad2data_bridge import (
    UploadedFile,
    supported_extensions,
)
from app.modules.dashboards.duckdb_pool import get_duckdb_pool
from app.modules.dashboards.manifest import manifest
from app.modules.dashboards.repository import SnapshotRepository
from app.modules.dashboards.schemas import (
    QuickInsightChartOut,
    QuickInsightsOut,
    SmartValueOut,
    SmartValuesOut,
    SnapshotErrorOut,
    SnapshotListResponse,
    SnapshotOut,
    SnapshotSourceFileOut,
    SnapshotSummaryOut,
)
from app.modules.dashboards.service import (
    CreateSnapshotArgs,
    SnapshotError,
    SnapshotService,
)
from app.modules.dashboards.snapshot_storage import read_manifest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Dashboards"])


# ── Health ─────────────────────────────────────────────────────────────────


@router.get("/_health", include_in_schema=False)
async def module_health() -> dict[str, str]:
    """Module-scoped health probe — mirrors the `/api/health` shape."""
    return {
        "module": manifest.name,
        "version": manifest.version,
        "status": "healthy",
    }


# ── Snapshots (T01) ────────────────────────────────────────────────────────


_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB safety cap per file
_MAX_UPLOAD_COUNT = 16                 # per POST


@router.post(
    "/projects/{project_id}/snapshots",
    response_model=SnapshotOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a snapshot from uploaded CAD/BIM files",
)
async def create_snapshot(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    label: Annotated[str, Form(min_length=1, max_length=200)],
    files: Annotated[list[UploadFile], File()],
    locale: Annotated[str, Query(description="Locale for the response message")] = "en",
    disciplines: Annotated[list[str] | None, Form()] = None,
    parent_snapshot_id: Annotated[uuid.UUID | None, Form()] = None,
) -> SnapshotOut:
    """Create a new snapshot.

    Accepts a multipart upload of one or more CAD/BIM files plus a
    free-form label. The label must be unique within the project (409
    otherwise). Each uploaded file must be ≤ 200 MB; the total upload
    count is capped at 16 to protect the conversion process.
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="At least one file is required.")
    if len(files) > _MAX_UPLOAD_COUNT:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"At most {_MAX_UPLOAD_COUNT} files per snapshot.",
        )

    disciplines = disciplines or []
    uploaded: list[UploadedFile] = []
    for idx, f in enumerate(files):
        content = await f.read()
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File '{f.filename}' exceeds the 200 MB size cap.",
            )
        ext = (f.filename or "").rsplit(".", 1)[-1].lower() if f.filename else ""
        uploaded.append(
            UploadedFile(
                original_name=f.filename or f"unnamed_{idx}",
                extension=ext,
                content=content,
                discipline=disciplines[idx] if idx < len(disciplines) else None,
            )
        )

    user_id = _user_id_from_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)

    service = SnapshotService(
        repo=SnapshotRepository(session), pool=get_duckdb_pool(),
    )

    try:
        row = await service.create(
            CreateSnapshotArgs(
                project_id=project_id,
                label=label,
                files=uploaded,
                user_id=user_id,
                tenant_id=tenant_id,
                parent_snapshot_id=parent_snapshot_id,
            )
        )
    except SnapshotError as exc:
        return _error_response(exc, locale)

    await session.commit()

    source_files = [
        SnapshotSourceFileOut.model_validate(sf)
        for sf in await service.list_source_files(row.id)
    ]
    return _row_to_detail_out(row, source_files)


@router.get(
    "/projects/{project_id}/snapshots",
    response_model=SnapshotListResponse,
    summary="List snapshots for a project",
)
async def list_snapshots(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SnapshotListResponse:
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))
    rows, total = await service.list_for_project(
        project_id, tenant_id=tenant_id, limit=limit, offset=offset,
    )
    items = [SnapshotSummaryOut.model_validate(r) for r in rows]
    return SnapshotListResponse(total=total, items=items)


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=SnapshotOut,
    summary="Get a single snapshot with its source files",
)
async def get_snapshot(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: Annotated[str, Query()] = "en",
) -> SnapshotOut:
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))

    try:
        row = await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        return _error_response(exc, locale)

    source_files = [
        SnapshotSourceFileOut.model_validate(sf)
        for sf in await service.list_source_files(row.id)
    ]
    return _row_to_detail_out(row, source_files)


@router.delete(
    "/snapshots/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a snapshot and its Parquet files",
)
async def delete_snapshot(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: Annotated[str, Query()] = "en",
) -> None:
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(
        repo=SnapshotRepository(session), pool=get_duckdb_pool(),
    )
    try:
        await service.delete(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)
    await session.commit()


@router.get(
    "/snapshots/{snapshot_id}/manifest",
    summary="Return the snapshot's on-disk manifest.json",
)
async def get_snapshot_manifest(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: Annotated[str, Query()] = "en",
) -> dict:
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))

    try:
        row = await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)

    try:
        return await read_manifest(row.project_id, row.id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=messages.translate("snapshot.not_found", locale=locale),
        ) from exc


# ── Quick-Insight Panel (T02) ──────────────────────────────────────────────


@router.get(
    "/snapshots/{snapshot_id}/quick-insights",
    response_model=QuickInsightsOut,
    summary="Auto-generated charts surfacing patterns in the snapshot",
)
async def get_quick_insights(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=24)] = 6,
    locale: Annotated[str, Query()] = "en",
) -> QuickInsightsOut:
    """Return a small bundle of auto-generated charts for the snapshot.

    Inspired by Tableau's "Show Me" + Power BI's "Quick Insights": the
    user picks no columns; the heuristic engine surveys the data and
    surfaces histograms, bar charts, line charts, scatters and donuts
    ranked by an interestingness score (variance / spread / |r| /
    entropy depending on the chart type).
    """
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))
    try:
        row = await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)

    df = await _load_quick_insights_dataframe(row.project_id, snapshot_id)
    if df is None or df.empty:
        return QuickInsightsOut(
            snapshot_id=snapshot_id, charts=[], total_candidates=0,
        )

    from app.modules.dashboards.insights import generate_quick_insights

    insights = generate_quick_insights(df, limit=limit)
    return QuickInsightsOut(
        snapshot_id=snapshot_id,
        charts=[QuickInsightChartOut(**c.to_dict()) for c in insights],
        total_candidates=len(insights),
    )


async def _load_quick_insights_dataframe(
    project_id: uuid.UUID, snapshot_id: uuid.UUID,
):
    """Read the snapshot's entities Parquet into a wide-form DataFrame.

    The cad2data bridge stores per-entity attributes inside an
    ``attributes`` dict column; for the heuristics to "see" each
    attribute as a chart candidate we explode that dict into top-level
    columns. Using pandas + pyarrow keeps this dependency-free of
    DuckDB so the panel still works for offline scripts.
    """
    import pyarrow.parquet as pq

    from app.modules.dashboards.snapshot_storage import resolve_local_parquet_path

    try:
        path = await resolve_local_parquet_path(
            project_id, snapshot_id, "entities",
        )
    except FileNotFoundError:
        return None

    table = pq.read_table(path)
    df = table.to_pandas()
    if "attributes" in df.columns and len(df) > 0:
        first_non_null = next(
            (a for a in df["attributes"] if isinstance(a, dict)), None,
        )
        if first_non_null is not None:
            attr_keys = {
                k for row in df["attributes"] if isinstance(row, dict) for k in row
            }
            for k in attr_keys:
                df[k] = df["attributes"].apply(
                    lambda d, key=k: d.get(key) if isinstance(d, dict) else None,
                )
        df = df.drop(columns=["attributes"])
    return df


# ── Smart Value Autocomplete (T03) ─────────────────────────────────────────


@router.get(
    "/snapshots/{snapshot_id}/values",
    response_model=SmartValuesOut,
    summary="Distinct-value autocomplete for snapshot columns",
)
async def get_smart_values(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    column: Annotated[str, Query(min_length=1, max_length=200)],
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    locale: Annotated[str, Query()] = "en",
) -> SmartValuesOut:
    """Return the snapshot's distinct values for ``column`` matching ``q``.

    Empty ``q`` returns the top-N values by frequency (most-common
    first). DuckDB drives the LIKE filter against the Parquet zone
    maps; rapidfuzz reranks when the LIKE pattern overshoots the
    requested limit.
    """
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))
    try:
        row = await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)

    from app.modules.dashboards.smart_values import (
        ColumnNotFoundError,
        fetch_distinct_values,
    )

    pool = get_duckdb_pool()
    try:
        matches = await fetch_distinct_values(
            pool=pool,
            snapshot_id=str(snapshot_id),
            project_id=str(row.project_id),
            column=column,
            query=q,
            limit=limit,
        )
    except ColumnNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return SmartValuesOut(
        snapshot_id=snapshot_id,
        column=column,
        query=q,
        items=[SmartValueOut(**m.to_dict()) for m in matches],
    )


# ── Helpers ────────────────────────────────────────────────────────────────


def _user_id_from_payload(payload: dict) -> uuid.UUID:
    sub = payload.get("sub") or payload.get("user_id")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing user identity in token.",
        )
    try:
        return uuid.UUID(str(sub))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user id in token.",
        ) from exc


def _tenant_id_from_payload(payload: dict) -> str | None:
    """Extract the tenant id from the JWT payload.

    For the single-tenant shape we ship today, ``tenant_id`` equals the
    user id. A future multi-tenant deployment would populate an
    explicit ``tenant_id`` claim and we'd prefer that.
    """
    tenant = payload.get("tenant_id")
    if tenant:
        return str(tenant)
    sub = payload.get("sub") or payload.get("user_id")
    return str(sub) if sub else None


def _row_to_detail_out(row, source_files: list[SnapshotSourceFileOut]) -> SnapshotOut:
    base = SnapshotOut.model_validate(row)
    return base.model_copy(update={"source_files": source_files})


def _error_response(exc: SnapshotError, locale: str) -> JSONResponse:
    params = _params_for_message_key(exc.message_key)
    body = SnapshotErrorOut(
        message_key=exc.message_key,
        message=messages.translate(exc.message_key, locale=locale, **params),
        details=exc.details,
    )
    return JSONResponse(status_code=exc.http_status, content=body.model_dump())


def _raise_http(exc: SnapshotError, locale: str) -> None:
    params = _params_for_message_key(exc.message_key)
    raise HTTPException(
        status_code=exc.http_status,
        detail=messages.translate(exc.message_key, locale=locale, **params),
    )


def _params_for_message_key(key: str) -> dict:
    """Supply placeholder values for every parameterised message."""
    if key == "snapshot.format.unsupported":
        return {"supported": ", ".join(sorted(supported_extensions()))}
    return {}


__all__ = ["router"]
