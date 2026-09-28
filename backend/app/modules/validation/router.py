# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation API routes.

Endpoints:
    POST  /validation/run                    - Run validation on a BOQ
    POST  /validation/import-ids             - Import IDS rules (multipart upload)
    GET   /validation/reports?project_id=X   - List validation reports
    GET   /validation/reports/{report_id}    - Get single report
    GET   /validation/reports/{id}/sarif     - Export report as SARIF v2.1.0 JSON
    GET   /validation/reports/{id}/export.csv  - Export findings as CSV
    GET   /validation/reports/{id}/export.xlsx - Export findings as XLSX
    DELETE /validation/reports/{report_id}   - Delete report
    GET   /validation/rule-sets              - List available rule sets
"""

import asyncio
import logging
import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content_disposition import attachment_disposition
from app.core.validation.engine import rule_registry
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.validation.bim_validation_service import BIMValidationService
from app.modules.validation.ids_importer import IDSImportError, parse_ids
from app.modules.validation.models import ValidationReport
from app.modules.validation.sarif_exporter import report_to_sarif
from app.modules.validation.schemas import (
    CheckBIMModelRequest,
    RunValidationRequest,
    RunValidationResponse,
    ValidationReportResponse,
    ValidationResultItem,
)
from app.modules.validation.service import ValidationModuleService
from app.modules.validation.tabular_exporter import report_to_csv, report_to_xlsx

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Validation"])


# ── Dependency ────────────────────────────────────────────────────────────


def _get_service(session: SessionDep) -> ValidationModuleService:
    return ValidationModuleService(session)


# ── IDOR protection helpers ───────────────────────────────────────────────


async def _require_project_access(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    user_id: str | None,
) -> None:
    """Verify the current user may access the referenced project.

    Central choke-point for project-scoped validation endpoints. Delegates
    to the canonical :func:`app.dependencies.verify_project_access`, which
    grants access to the owner, admins, and team members, and raises HTTP
    404 (not 403) on both "missing" and "denied" so the endpoint never
    leaks the existence of a project UUID the caller cannot see (IDOR
    defence). ``None`` project_id is a no-op - callers that accept global
    aggregates must scope at the service layer.
    """
    if project_id is None:
        return
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    from app.dependencies import verify_project_access

    await verify_project_access(project_id, user_id, session)


async def _require_report_access(
    session: AsyncSession,
    report_id: uuid.UUID,
    user_id: str | None,
) -> ValidationReport:
    """Load a report and verify the caller owns its parent project."""
    report = await session.get(ValidationReport, report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validation report {report_id} not found",
        )
    await _require_project_access(session, report.project_id, user_id)
    return report


# ── POST /run - Run validation on a BOQ ──────────────────────────────────


@router.post(
    "/run/",
    response_model=RunValidationResponse,
    dependencies=[Depends(RequirePermission("validation.create"))],
)
async def run_validation(
    data: RunValidationRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ValidationModuleService = Depends(_get_service),
) -> RunValidationResponse:
    """Run validation rules against a BOQ.

    Loads the BOQ positions, applies the requested rule sets, and returns
    a full validation report with per-rule results.

    The report is also persisted to the database for historical review.
    """
    await _require_project_access(session, data.project_id, user_id)
    try:
        result = await service.run_validation(
            project_id=data.project_id,
            boq_id=data.boq_id,
            rule_sets=data.rule_sets,
            user_id=uuid.UUID(user_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return RunValidationResponse(
        report_id=uuid.UUID(result["report_id"]),
        status=result["status"],
        score=result["score"],
        total_rules=result["total_rules"],
        passed_count=result["passed_count"],
        warning_count=result["warning_count"],
        error_count=result["error_count"],
        info_count=result["info_count"],
        rule_sets=result["rule_sets"],
        supported_rule_sets=result.get("supported_rule_sets", []),
        unsupported_rule_sets=result.get("unsupported_rule_sets", []),
        duration_ms=result["duration_ms"],
        results=[
            ValidationResultItem(
                rule_id=r["rule_id"],
                status=r["status"],
                message=r["message"],
                element_ref=r.get("element_ref"),
                details=r.get("details"),
                suggestion=r.get("suggestion"),
            )
            for r in result["results"]
        ],
    )


# ── POST /audit - One-click estimate audit on a BOQ ───────────────────────


class AuditEstimateRequest(BaseModel):
    """Request body for POST /validation/audit - audit a finished BOQ."""

    project_id: uuid.UUID = Field(description="Project owning the BOQ")
    boq_id: uuid.UUID = Field(description="BOQ to audit")


@router.post(
    "/audit/",
    dependencies=[Depends(RequirePermission("validation.create"))],
)
async def audit_estimate(
    data: AuditEstimateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ValidationModuleService = Depends(_get_service),
) -> dict[str, Any]:
    """Run the one-click estimate audit over a finished BOQ.

    Runs the universal quality checks, groups the failures into actionable
    findings (missing items, wrong units, duplicates, price outliers), attaches
    a concrete one-click fix to each, persists the report, and writes every
    finding back onto the BOQ positions so the estimate grid accents match. The
    response carries the grouped findings and the quality score so the caller
    can show a score delta after applying fixes and re-running.
    """
    await _require_project_access(session, data.project_id, user_id)
    try:
        return await service.run_estimate_audit(
            project_id=data.project_id,
            boq_id=data.boq_id,
            user_id=uuid.UUID(user_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


# ── POST /check-bim-model - Run per-element BIM rules ───────────────────


@router.post(
    "/check-bim-model",
    response_model=ValidationReportResponse,
    dependencies=[Depends(RequirePermission("validation.create"))],
)
async def check_bim_model(
    request: CheckBIMModelRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ValidationReportResponse:
    """Run per-element :class:`BIMElementRule` checks against a BIM model.

    Persists a :class:`ValidationReport` row with ``target_type='bim_model'``
    and ``results`` that carry ``element_id`` references so the UI can map
    each failure back to the offending element. Large models are capped at
    ``MAX_RESULTS_PER_REPORT`` failures with a ``_truncated`` sentinel.
    """
    # Ownership check - resolve the BIM model to its project first.
    from app.modules.bim_hub.repository import BIMModelRepository

    model_repo = BIMModelRepository(session)
    model = await model_repo.get(request.model_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"BIM model {request.model_id} not found",
        )
    await _require_project_access(session, model.project_id, user_id)

    service = BIMValidationService(session)
    try:
        report = await service.validate_bim_model(
            model_id=request.model_id,
            rule_ids=request.rule_ids,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return ValidationReportResponse.model_validate(report)


# ── GET /bim-scorecard/{model_id} - Maturity scorecard + version trend ────


async def _load_bim_model_for_read(
    session: AsyncSession,
    model_id: uuid.UUID,
    user_id: str | None,
) -> Any:
    """Resolve a BIM model to its project and verify read access (IDOR-safe).

    Mirrors the ownership resolution in ``check_bim_model``: load the model,
    404 when missing, then delegate to ``_require_project_access`` (which raises
    404 on both missing-and-forbidden so a model UUID the caller cannot see is
    never confirmed).
    """
    from app.modules.bim_hub.repository import BIMModelRepository

    model = await BIMModelRepository(session).get(model_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"BIM model {model_id} not found",
        )
    await _require_project_access(session, model.project_id, user_id)
    return model


@router.get(
    "/bim-scorecard/{model_id}",
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def get_bim_scorecard(
    model_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    expected_disciplines: list[str] | None = Query(
        None,
        description="Override the expected discipline set for the coverage facet.",
    ),
    rule_ids: list[str] | None = Query(
        None,
        description="Optional subset of universal rule ids for the property completeness facet.",
    ),
    include_trend: bool = Query(True, description="Include the version-over-version score trend."),
) -> dict[str, Any]:
    """Return the BIM maturity scorecard (facet sub-scores + grade) for a model.

    Read-only: it computes the facets live from the model's current elements and
    reads the version trend from the validation reports already persisted by
    prior ``/check-bim-model`` runs. No report is written. Gated on
    ``validation.read`` plus the standard project-access guard, identical to the
    other validation read endpoints.
    """
    from app.modules.validation.bim_scorecard_service import BIMScorecardService

    await _load_bim_model_for_read(session, model_id, user_id)
    service = BIMScorecardService(session)
    try:
        return await service.get_scorecard(
            model_id,
            expected_disciplines=expected_disciplines,
            rule_ids=rule_ids,
            include_trend=include_trend,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/bim-scorecard/{model_id}/trend",
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def get_bim_scorecard_trend(
    model_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict[str, Any]:
    """Return only the version-over-version validation score trend for a model.

    Same read access-control as ``get_bim_scorecard``; assembles the score
    series from the persisted ``ValidationReport`` history, no new storage.
    """
    from app.modules.validation.bim_scorecard_service import BIMScorecardService

    await _load_bim_model_for_read(session, model_id, user_id)
    service = BIMScorecardService(session)
    try:
        return await service.get_trend(model_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


# ── GET /reports - List validation reports ───────────────────────────────


@router.get(
    "/reports/",
    response_model=list[ValidationReportResponse],
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def list_reports(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Project ID to list reports for"),
    target_type: str | None = Query(None, description="Filter by target type (boq, document, etc.)"),
    limit: int = Query(50, ge=1, le=200),
    service: ValidationModuleService = Depends(_get_service),
) -> list[ValidationReportResponse]:
    """List validation reports for a project, newest first."""
    await _require_project_access(session, project_id, user_id)
    reports = await service.list_reports(project_id, target_type=target_type, limit=limit)
    return [ValidationReportResponse.model_validate(r) for r in reports]


# ── GET /reports/{report_id} - Get single report ─────────────────────────


@router.get(
    "/reports/{report_id}",
    response_model=ValidationReportResponse,
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def get_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ValidationModuleService = Depends(_get_service),
) -> ValidationReportResponse:
    """Get a single validation report by ID."""
    report = await _require_report_access(session, report_id, user_id)
    return ValidationReportResponse.model_validate(report)


# ── DELETE /reports/{report_id} - Delete report ──────────────────────────


@router.delete(
    "/reports/{report_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("validation.delete"))],
)
async def delete_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ValidationModuleService = Depends(_get_service),
) -> None:
    """Delete a validation report."""
    await _require_report_access(session, report_id, user_id)
    deleted = await service.delete_report(report_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validation report {report_id} not found",
        )


# ── POST /import-ids - Import buildingSMART IDS rules ─────────────────────


@router.post(
    "/import-ids",
    dependencies=[Depends(RequirePermission("validation.create"))],
)
async def import_ids(
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = File(..., description="An IDS XML file (.ids or .xml)"),
    project_id: uuid.UUID = Query(..., description="Project the imported rules belong to"),
    rule_set: str = Query(
        default="ids_custom",
        description="Rule set name to register the imported rules under.",
    ),
) -> dict[str, Any]:
    """Parse an IDS file and register one ValidationRule per <specification>.

    Requires ``project_id`` and verifies the caller owns the project before
    registering, mirroring every other validation endpoint. The rules are
    added to the in-process rule registry under a project-namespaced rule
    set (``{rule_set}:{project_id}``) so imported rules cannot leak across
    tenants or projects.  Returns the count and the list of generated rule
    ids.

    NOTE: the registry is process-global and in-memory, so namespacing gates
    which ``/validation/run`` calls can apply these rules but they are not yet
    persisted per project (lost on restart). Durable per-project storage needs
    a dedicated table - tracked as residual.
    """
    await _require_project_access(session, project_id, user_id)
    try:
        payload = await file.read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read upload: {exc}",
        ) from exc

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )

    try:
        rules = parse_ids(payload)
    except IDSImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    scoped_rule_set = f"{rule_set}:{project_id}"
    # Re-import replaces this project's scoped set atomically instead of
    # accumulating stale rules. Without this, importing a revised IDS for the
    # same project would leave the previous specs registered and still firing
    # (duplicate / outdated findings). Removal is keyed strictly to THIS
    # project's namespaced set, so built-in sets (boq_quality, din276, gaeb,
    # bim_compliance, ...) and other projects' scoped sets are untouched.
    rule_registry.unregister_rule_set(scoped_rule_set)
    rule_ids: list[str] = []
    for rule in rules:
        # Namespace the rule_id by project before registering. The registry
        # keys rules in a single process-global dict, so two projects that
        # import IDS files sharing a spec identifier would otherwise overwrite
        # each other's rule body. Registering ONLY into the project-scoped set
        # (never a shared global "IDS" set) keeps one tenant's imported rules
        # from being resolvable - or applied - by another.
        if not str(rule.rule_id).startswith(f"{project_id}:"):
            rule.rule_id = f"{project_id}:{rule.rule_id}"
        rule_registry.register(rule, rule_sets=[scoped_rule_set])
        rule_ids.append(rule.rule_id)

    return {
        "rules_created": len(rule_ids),
        "rule_ids": rule_ids,
        "rule_set": scoped_rule_set,
        "project_id": str(project_id),
        "filename": file.filename,
    }


# ── GET /reports/{id}/sarif - Export report as SARIF v2.1.0 ───────────────


@router.get(
    "/reports/{report_id}/sarif",
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def export_report_sarif(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> JSONResponse:
    """Export a validation report as SARIF v2.1.0 JSON.

    The response carries the ``application/sarif+json`` media type so
    downstream tooling (GitHub Code Scanning, Azure DevOps, VS Code SARIF
    Viewer) can ingest it directly.
    """
    report = await _require_report_access(session, report_id, user_id)
    sarif_doc = report_to_sarif(report)
    return JSONResponse(content=sarif_doc, media_type="application/sarif+json")


# ── GET /reports/{id}/export.csv|.xlsx - Export findings as CSV / XLSX ─────


def _export_filename(report: ValidationReport, ext: str) -> str:
    """Attachment filename for a report export.

    The name travels through :func:`attachment_disposition`, which emits the
    RFC 6266 pair (ASCII ``filename`` fallback plus UTF-8 ``filename*``), so
    non-ASCII target ids keep their real characters instead of becoming
    question marks. Only control characters are dropped here, keeping the
    value single-line (no CR/LF response-splitting). Falls back to the report
    id, then a constant.
    """
    raw = str(getattr(report, "target_id", "") or getattr(report, "id", "") or "report")
    base = "".join(ch for ch in raw if ch >= " " and ch != "\x7f").strip()
    base = base.replace("/", "-").replace("\\", "-")
    return f"validation_{base or 'report'}.{ext}"


def _report_snapshot(report: ValidationReport) -> SimpleNamespace:
    """Detached copy of the report fields the CSV / XLSX exporters read.

    The exporters run in a worker thread and duck-type the report, so they get
    this plain copy instead of the live ORM row.
    """
    return SimpleNamespace(
        id=getattr(report, "id", ""),
        target_type=getattr(report, "target_type", ""),
        target_id=getattr(report, "target_id", ""),
        rule_set=getattr(report, "rule_set", ""),
        created_at=getattr(report, "created_at", None),
        results=list(getattr(report, "results", []) or []),
    )


@router.get(
    "/reports/{report_id}/export.csv",
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def export_report_csv(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> Response:
    """Export a validation report's findings as a CSV file.

    Project access is verified the IDOR-safe way (``_require_report_access``
    returns 404 for a missing-or-forbidden report) before any bytes are
    produced. Every cell is neutralised against spreadsheet formula injection
    by the exporter.
    """
    report = await _require_report_access(session, report_id, user_id)
    # Writing the file walks every finding and is pure CPU, so it runs in a
    # worker thread instead of holding up every other request on the event loop.
    blob = await asyncio.to_thread(report_to_csv, _report_snapshot(report))
    filename = _export_filename(report, "csv")
    return Response(
        content=blob,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": attachment_disposition(filename),
            "Content-Length": str(len(blob)),
        },
    )


@router.get(
    "/reports/{report_id}/export.xlsx",
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def export_report_xlsx(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> Response:
    """Export a validation report's findings as an .xlsx workbook.

    Same IDOR guard and formula-injection neutralisation as the CSV export;
    only the serialisation differs.
    """
    report = await _require_report_access(session, report_id, user_id)
    # Writing the workbook walks every finding and is pure CPU, so it runs in a
    # worker thread instead of holding up every other request on the event loop.
    blob = await asyncio.to_thread(report_to_xlsx, _report_snapshot(report))
    filename = _export_filename(report, "xlsx")
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": attachment_disposition(filename),
            "Content-Length": str(len(blob)),
        },
    )


# ── GET /rule-sets - List available rule sets ─────────────────────────────


@router.get(
    "/rule-sets/",
)
async def list_rule_sets(
    service: ValidationModuleService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all available validation rule sets with descriptions.

    Returns each rule set's name, description, rule count, and individual rules.
    This endpoint does not require authentication so it can be used by
    public documentation pages.
    """
    return service.get_available_rule_sets()


# ── GET /rule-packs/coverage - Honest declared-vs-implemented coverage ────


@router.get(
    "/rule-packs/coverage/",
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def rule_pack_coverage() -> dict[str, Any]:
    """Report honest rule-pack coverage: declared vs actually implemented rules.

    Every shipped rule pack declares an ``enables_rule_ids`` list, but a declared
    rule id only executes when a real rule body is registered in the engine for
    that exact id. This resolves, per pack and repo-wide, which declared ids are
    implemented (will run) versus declared-only (will NOT run, and must never be
    reported as a silent pass), so a UI or report can show "N of M rules active"
    instead of over-claiming coverage from the raw declaration counts.

    Read-only accounting: it never registers rules or changes how validation
    runs. Gated on ``validation.read`` because it reveals which packs are
    installed on this deployment.
    """
    from app.core.validation.pack_coverage import get_pack_coverage

    return get_pack_coverage().to_dict()


# ── Vector / semantic memory endpoints ───────────────────────────────────
#
# ``/vector/status/`` + ``/vector/reindex/`` wired via the shared factory
# (see ``include_router`` at the bottom of the file).  The
# ``/{report_id}/similar/`` endpoint stays module-specific.


@router.get(
    "/{report_id}/similar/",
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def validation_report_similar(
    report_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    limit: int = Query(default=5, ge=1, le=20),
    cross_project: bool = Query(default=True),
) -> dict[str, Any]:
    """Return validation reports semantically similar to the given one."""
    from app.core.vector_index import find_similar
    from app.dependencies import allowed_project_ids_for_similar
    from app.modules.validation.vector_adapter import validation_report_adapter

    # Verify the caller owns the source report's project before running
    # cross-project similarity, mirroring get_report/export_report_sarif.
    row = await _require_report_access(session, report_id, user_id)
    project_id = str(row.project_id) if row.project_id else None
    # Restrict cross-project hits to projects the caller may access so a
    # cross-project search never leaks reports from inaccessible projects
    # (None == admin/unrestricted, mirroring verify_project_access).
    allowed = await allowed_project_ids_for_similar(session, str(user_id), project_id, cross_project)
    hits = await find_similar(
        validation_report_adapter,
        row,
        project_id=project_id,
        cross_project=cross_project,
        limit=limit,
        allowed_project_ids=allowed,
    )
    return {
        "source_id": str(report_id),
        "limit": limit,
        "cross_project": cross_project,
        "hits": [h.to_dict() for h in hits],
    }


# ── Mount vector status + reindex via the shared factory ────────────────
from app.core.vector_index import COLLECTION_VALIDATION  # noqa: E402
from app.core.vector_routes import create_vector_routes  # noqa: E402
from app.modules.validation.vector_adapter import (  # noqa: E402
    validation_report_adapter as _validation_report_adapter,
)

router.include_router(
    create_vector_routes(
        collection=COLLECTION_VALIDATION,
        adapter=_validation_report_adapter,
        model=ValidationReport,
        read_permission="validation.read",
        write_permission="validation.create",
        project_id_attr="project_id",
    )
)
