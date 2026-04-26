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
from fastapi.responses import JSONResponse, Response

from app.dependencies import CurrentUserPayload, SessionDep
from app.modules.dashboards import messages
from app.modules.dashboards.cad2data_bridge import (
    UploadedFile,
    supported_extensions,
)
from app.modules.dashboards.duckdb_pool import get_duckdb_pool
from app.modules.dashboards.manifest import manifest
from app.modules.dashboards.presets_repository import DashboardPresetRepository
from app.modules.dashboards.presets_service import (
    CreatePresetArgs,
    DashboardPresetService,
    PresetError,
)
from app.modules.dashboards.repository import SnapshotRepository
from app.modules.dashboards.rows_io import (
    SUPPORTED_EXPORT_FORMATS,
    RowsIOError,
    commit_import,
    export_to_format,
    read_rows,
    stage_import,
)
from app.modules.dashboards.schemas import (
    CascadeRowCountOut,
    CascadeValueOut,
    CascadeValuesOut,
    CascadeValuesRequest,
    DashboardPresetCreate,
    DashboardPresetListResponse,
    DashboardPresetOut,
    DashboardPresetUpdate,
    QuickInsightChartOut,
    QuickInsightsOut,
    SmartValueOut,
    SmartValuesOut,
    SnapshotErrorOut,
    SnapshotImportCommitIn,
    SnapshotImportCommitOut,
    SnapshotImportPreviewOut,
    SnapshotListResponse,
    SnapshotOut,
    SnapshotRowsOut,
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


# ── Cascade Filter Engine (T04) ────────────────────────────────────────────


@router.post(
    "/snapshots/{snapshot_id}/cascade-values",
    response_model=CascadeValuesOut,
    summary="Distinct values of a column consistent with the active filter selection",
)
async def post_cascade_values(
    snapshot_id: uuid.UUID,
    body: CascadeValuesRequest,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: Annotated[str, Query()] = "en",
) -> CascadeValuesOut:
    """Cascade-aware value picker.

    Returns the distinct values of ``target_column`` whose row-set is
    consistent with every entry in ``selected`` AND fuzzy-matches ``q``
    (case-insensitive substring). Empty arrays in ``selected`` are
    silently dropped — they mean "no filter on that column".
    """
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))
    try:
        row = await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)

    from app.modules.dashboards.cascade import (
        InvalidSelectedColumnError,
        fetch_cascade_values,
    )
    from app.modules.dashboards.smart_values import ColumnNotFoundError

    pool = get_duckdb_pool()
    try:
        matches = await fetch_cascade_values(
            pool=pool,
            snapshot_id=str(snapshot_id),
            project_id=str(row.project_id),
            selected=body.selected,
            target_column=body.target_column,
            query=body.q,
            limit=body.limit,
        )
    except ColumnNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvalidSelectedColumnError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return CascadeValuesOut(
        snapshot_id=snapshot_id,
        target_column=body.target_column,
        q=body.q,
        values=[CascadeValueOut(**m.to_dict()) for m in matches],
    )


@router.get(
    "/snapshots/{snapshot_id}/row-count",
    response_model=CascadeRowCountOut,
    summary="Matched / total row counts under the active filter selection",
)
async def get_cascade_row_count(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    selected: Annotated[
        str,
        Query(
            description=(
                "JSON-encoded {column: [values]} map. Empty arrays mean "
                "'no filter on that column'."
            ),
            max_length=8000,
        ),
    ] = "{}",
    locale: Annotated[str, Query()] = "en",
) -> CascadeRowCountOut:
    """Return the matched / total row count for a selection.

    The selection arrives as a single URL-safe JSON blob to keep the
    GET query string flat — the cascade panel sends it on every chip
    add/remove for the live "X of Y rows match" counter.
    """
    import json

    try:
        parsed = json.loads(selected) if selected else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"selected is not valid JSON: {exc.msg}",
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="selected must decode to an object/dict.",
        )

    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))
    try:
        row = await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)

    from app.modules.dashboards.cascade import (
        InvalidSelectedColumnError,
        count_filtered_rows,
    )

    pool = get_duckdb_pool()
    try:
        matched, total = await count_filtered_rows(
            pool=pool,
            snapshot_id=str(snapshot_id),
            project_id=str(row.project_id),
            selected=parsed,
        )
    except InvalidSelectedColumnError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return CascadeRowCountOut(
        snapshot_id=snapshot_id, matched=matched, total=total,
    )


# ── Dashboard Presets & Collections (T05) ──────────────────────────────────


_PRESET_UPLOAD_MAX_BYTES = 16 * 1024 * 1024  # 16 MB cap on import payloads


@router.post(
    "/presets",
    response_model=DashboardPresetOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dashboard preset or shared collection",
)
async def create_preset(
    payload: CurrentUserPayload,
    session: SessionDep,
    body: DashboardPresetCreate,
    locale: Annotated[str, Query()] = "en",
) -> DashboardPresetOut:
    user_id = _user_id_from_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)
    service = DashboardPresetService(
        repo=DashboardPresetRepository(session),
    )
    try:
        row = await service.create(
            CreatePresetArgs(
                name=body.name,
                description=body.description,
                kind=body.kind,
                project_id=body.project_id,
                config_json=body.config_json,
                shared_with_project=body.shared_with_project,
                owner_id=user_id,
                tenant_id=tenant_id,
            )
        )
    except PresetError as exc:
        return _preset_error_response(exc, locale)

    await session.commit()
    return DashboardPresetOut.model_validate(row)


@router.get(
    "/presets",
    response_model=DashboardPresetListResponse,
    summary="List dashboards visible to the caller",
)
async def list_presets(
    payload: CurrentUserPayload,
    session: SessionDep,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    locale: Annotated[str, Query()] = "en",
) -> DashboardPresetListResponse:
    user_id = _user_id_from_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)
    service = DashboardPresetService(
        repo=DashboardPresetRepository(session),
    )
    try:
        rows, total = await service.list_visible(
            owner_id=user_id,
            tenant_id=tenant_id,
            project_id=project_id,
            kind=kind,
            limit=limit,
            offset=offset,
        )
    except PresetError as exc:
        _raise_preset_http(exc, locale)

    return DashboardPresetListResponse(
        total=total,
        items=[DashboardPresetOut.model_validate(r) for r in rows],
    )


@router.get(
    "/presets/{preset_id}",
    response_model=DashboardPresetOut,
    summary="Read a single dashboard preset",
)
async def get_preset(
    preset_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: Annotated[str, Query()] = "en",
) -> DashboardPresetOut:
    user_id = _user_id_from_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)
    service = DashboardPresetService(
        repo=DashboardPresetRepository(session),
    )
    try:
        row = await service.get(
            preset_id, owner_id=user_id, tenant_id=tenant_id,
        )
    except PresetError as exc:
        _raise_preset_http(exc, locale)
    return DashboardPresetOut.model_validate(row)


@router.patch(
    "/presets/{preset_id}",
    response_model=DashboardPresetOut,
    summary="Update a dashboard preset (owner only)",
)
async def update_preset(
    preset_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    body: DashboardPresetUpdate,
    locale: Annotated[str, Query()] = "en",
) -> DashboardPresetOut:
    user_id = _user_id_from_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)
    service = DashboardPresetService(
        repo=DashboardPresetRepository(session),
    )
    try:
        row = await service.update(
            preset_id,
            owner_id=user_id,
            tenant_id=tenant_id,
            name=body.name,
            description=body.description,
            kind=body.kind,
            config_json=body.config_json,
            shared_with_project=body.shared_with_project,
        )
    except PresetError as exc:
        _raise_preset_http(exc, locale)
    await session.commit()
    return DashboardPresetOut.model_validate(row)


@router.delete(
    "/presets/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dashboard preset (owner only)",
)
async def delete_preset(
    preset_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: Annotated[str, Query()] = "en",
) -> None:
    user_id = _user_id_from_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)
    service = DashboardPresetService(
        repo=DashboardPresetRepository(session),
    )
    try:
        await service.delete(
            preset_id, owner_id=user_id, tenant_id=tenant_id,
        )
    except PresetError as exc:
        _raise_preset_http(exc, locale)
    await session.commit()


@router.post(
    "/presets/{preset_id}/share",
    response_model=DashboardPresetOut,
    summary="Toggle 'shared with project' on a preset",
)
async def share_preset(
    preset_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: Annotated[str, Query()] = "en",
) -> DashboardPresetOut:
    user_id = _user_id_from_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)
    service = DashboardPresetService(
        repo=DashboardPresetRepository(session),
    )
    try:
        row = await service.toggle_share(
            preset_id, owner_id=user_id, tenant_id=tenant_id,
        )
    except PresetError as exc:
        _raise_preset_http(exc, locale)
    await session.commit()
    return DashboardPresetOut.model_validate(row)


# ── Tabular Data I/O (T06) ─────────────────────────────────────────────────


@router.get(
    "/snapshots/{snapshot_id}/rows",
    response_model=SnapshotRowsOut,
    summary="Paginated row reader for a snapshot",
)
async def get_snapshot_rows(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    columns: Annotated[str | None, Query(max_length=2000)] = None,
    filters: Annotated[str | None, Query(max_length=4000)] = None,
    order_by: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    locale: Annotated[str, Query()] = "en",
) -> SnapshotRowsOut:
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))
    try:
        row = await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)

    pool = get_duckdb_pool()
    try:
        result = await read_rows(
            pool=pool,
            snapshot_id=snapshot_id,
            project_id=row.project_id,
            columns=columns,
            filters=filters,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
    except RowsIOError as exc:
        _raise_rows_http(exc, locale)

    return SnapshotRowsOut(
        snapshot_id=snapshot_id,
        columns=result.columns,
        rows=result.rows,
        total=result.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/snapshots/{snapshot_id}/export",
    summary="Stream a snapshot as CSV / XLSX / Parquet",
)
async def export_snapshot(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    format: Annotated[str, Query(pattern=r"^(csv|xlsx|parquet)$")] = "csv",
    columns: Annotated[str | None, Query(max_length=2000)] = None,
    filters: Annotated[str | None, Query(max_length=4000)] = None,
    order_by: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100000)] = 10000,
    offset: Annotated[int, Query(ge=0)] = 0,
    locale: Annotated[str, Query()] = "en",
) -> Response:
    """Export the same rows the row reader returns, in a tabular format.

    Works in-memory today; for >100k rows the recommended path is to
    page through ``GET /rows`` client-side.
    """
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))
    try:
        row = await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)

    pool = get_duckdb_pool()
    try:
        result = await read_rows(
            pool=pool,
            snapshot_id=snapshot_id,
            project_id=row.project_id,
            columns=columns,
            filters=filters,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        payload_bytes, content_type, ext = export_to_format(
            columns=result.columns,
            rows=result.rows,
            format=format,
        )
    except RowsIOError as exc:
        _raise_rows_http(exc, locale)

    filename = f"snapshot_{snapshot_id}.{ext}"
    return Response(
        content=payload_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post(
    "/snapshots/{snapshot_id}/import",
    response_model=SnapshotImportPreviewOut,
    summary="Stage a CSV/XLSX upload for a future commit (preview only)",
)
async def import_preview(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    locale: Annotated[str, Query()] = "en",
) -> SnapshotImportPreviewOut:
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))
    try:
        row = await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)

    content = await file.read()
    if len(content) > _PRESET_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Upload exceeds {_PRESET_UPLOAD_MAX_BYTES // (1024 * 1024)} MB cap.",
        )

    pool = get_duckdb_pool()
    try:
        schema_rows = await pool.execute(
            snapshot_id, row.project_id, "DESCRIBE entities", parameters=[],
        )
    except Exception as exc:
        logger.warning(
            "dashboards.import.schema_lookup_failed snapshot_id=%s: %s",
            snapshot_id, type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not introspect snapshot schema.",
        ) from exc
    snapshot_columns = [str(r[0]) for r in schema_rows]

    try:
        result = stage_import(
            snapshot_id=snapshot_id,
            snapshot_columns=snapshot_columns,
            upload_filename=file.filename or "upload",
            upload_bytes=content,
        )
    except RowsIOError as exc:
        _raise_rows_http(exc, locale)

    return SnapshotImportPreviewOut(**result)


@router.post(
    "/snapshots/{snapshot_id}/import/commit",
    response_model=SnapshotImportCommitOut,
    summary="Finalise a previously staged import",
)
async def import_commit(
    snapshot_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    body: SnapshotImportCommitIn,
    locale: Annotated[str, Query()] = "en",
) -> SnapshotImportCommitOut:
    tenant_id = _tenant_id_from_payload(payload)
    service = SnapshotService(repo=SnapshotRepository(session))
    try:
        await service.get(snapshot_id, tenant_id=tenant_id)
    except SnapshotError as exc:
        _raise_http(exc, locale)

    try:
        result = commit_import(
            snapshot_id=snapshot_id,
            staging_id=body.staging_id,
        )
    except RowsIOError as exc:
        _raise_rows_http(exc, locale)

    return SnapshotImportCommitOut(**result)


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
    if key == "export.format.unsupported":
        return {"supported": ", ".join(SUPPORTED_EXPORT_FORMATS)}
    return {}


def _preset_error_response(exc: PresetError, locale: str) -> JSONResponse:
    body = SnapshotErrorOut(
        message_key=exc.message_key,
        message=messages.translate(exc.message_key, locale=locale),
        details=exc.details,
    )
    return JSONResponse(status_code=exc.http_status, content=body.model_dump())


def _raise_preset_http(exc: PresetError, locale: str) -> None:
    raise HTTPException(
        status_code=exc.http_status,
        detail=messages.translate(exc.message_key, locale=locale),
    )


def _raise_rows_http(exc: RowsIOError, locale: str) -> None:
    params = _params_for_message_key(exc.message_key)
    raise HTTPException(
        status_code=exc.http_status,
        detail=messages.translate(exc.message_key, locale=locale, **params),
    )


__all__ = ["router"]
