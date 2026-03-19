"""BOQ API routes.

Endpoints:
    POST   /boqs/                              — Create a new BOQ
    GET    /boqs/?project_id=xxx               — List BOQs for a project
    GET    /boqs/templates                     — List available BOQ templates
    POST   /boqs/from-template                 — Create a BOQ from a template
    GET    /boqs/{boq_id}                      — Get BOQ with all positions
    PATCH  /boqs/{boq_id}                      — Update BOQ metadata
    DELETE /boqs/{boq_id}                      — Delete BOQ and all positions
    GET    /boqs/{boq_id}/structured           — Full BOQ with sections + markups
    GET    /boqs/{boq_id}/activity             — Activity log for a BOQ
    POST   /boqs/{boq_id}/positions            — Add a position to a BOQ
    PATCH  /positions/{position_id}            — Update a position
    DELETE /positions/{position_id}            — Delete a position
    POST   /boqs/{boq_id}/sections             — Create a section header
    POST   /boqs/{boq_id}/markups              — Add a markup line
    PATCH  /boqs/{boq_id}/markups/{markup_id}  — Update a markup
    DELETE /boqs/{boq_id}/markups/{markup_id}  — Delete a markup
    POST   /boqs/{boq_id}/markups/apply-defaults — Apply regional default markups
    POST   /boqs/{boq_id}/duplicate            — Duplicate a BOQ with all data
    POST   /positions/{position_id}/duplicate  — Duplicate a single position
    POST   /boqs/{boq_id}/validate             — Validate a BOQ against rule sets
    GET    /boqs/{boq_id}/export/csv           — Export BOQ as CSV
    GET    /boqs/{boq_id}/export/excel         — Export BOQ as Excel (xlsx)
    GET    /boqs/{boq_id}/export/pdf           — Export BOQ as PDF report
    POST   /boqs/{boq_id}/import/excel         — Import positions from Excel/CSV
    GET    /projects/{project_id}/activity     — Activity log for a project
"""

import csv
import io
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import StreamingResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.boq.schemas import (
    ActivityLogList,
    BOQCreate,
    BOQFromTemplateRequest,
    BOQResponse,
    BOQUpdate,
    BOQWithPositions,
    BOQWithSections,
    MarkupCreate,
    MarkupResponse,
    MarkupUpdate,
    PositionCreate,
    PositionResponse,
    PositionUpdate,
    SectionCreate,
    TemplateInfo,
)
from app.modules.boq.service import BOQService

router = APIRouter()


def _get_service(session: SessionDep) -> BOQService:
    return BOQService(session)


def _position_to_response(position: object) -> PositionResponse:
    """Build a PositionResponse from a Position ORM object."""
    return PositionResponse(
        id=position.id,  # type: ignore[attr-defined]
        boq_id=position.boq_id,  # type: ignore[attr-defined]
        parent_id=position.parent_id,  # type: ignore[attr-defined]
        ordinal=position.ordinal,  # type: ignore[attr-defined]
        description=position.description,  # type: ignore[attr-defined]
        unit=position.unit,  # type: ignore[attr-defined]
        quantity=float(position.quantity),  # type: ignore[attr-defined]
        unit_rate=float(position.unit_rate),  # type: ignore[attr-defined]
        total=float(position.total),  # type: ignore[attr-defined]
        classification=position.classification,  # type: ignore[attr-defined]
        source=position.source,  # type: ignore[attr-defined]
        confidence=(
            float(position.confidence) if position.confidence else None  # type: ignore[attr-defined]
        ),
        cad_element_ids=position.cad_element_ids,  # type: ignore[attr-defined]
        validation_status=position.validation_status,  # type: ignore[attr-defined]
        metadata_=position.metadata_,  # type: ignore[attr-defined]
        sort_order=position.sort_order,  # type: ignore[attr-defined]
        created_at=position.created_at,  # type: ignore[attr-defined]
        updated_at=position.updated_at,  # type: ignore[attr-defined]
    )


def _markup_to_response(markup: object) -> MarkupResponse:
    """Build a MarkupResponse from a BOQMarkup ORM object."""
    return MarkupResponse(
        id=markup.id,  # type: ignore[attr-defined]
        boq_id=markup.boq_id,  # type: ignore[attr-defined]
        name=markup.name,  # type: ignore[attr-defined]
        markup_type=markup.markup_type,  # type: ignore[attr-defined]
        category=markup.category,  # type: ignore[attr-defined]
        percentage=float(markup.percentage),  # type: ignore[attr-defined]
        fixed_amount=float(markup.fixed_amount),  # type: ignore[attr-defined]
        apply_to=markup.apply_to,  # type: ignore[attr-defined]
        sort_order=markup.sort_order,  # type: ignore[attr-defined]
        is_active=markup.is_active,  # type: ignore[attr-defined]
        metadata_=markup.metadata_,  # type: ignore[attr-defined]
        created_at=markup.created_at,  # type: ignore[attr-defined]
        updated_at=markup.updated_at,  # type: ignore[attr-defined]
    )


# ── BOQ CRUD ──────────────────────────────────────────────────────────────────


@router.post(
    "/boqs/",
    response_model=BOQResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.create"))],
)
async def create_boq(
    data: BOQCreate,
    _user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Create a new Bill of Quantities."""
    boq = await service.create_boq(data)
    return BOQResponse.model_validate(boq)


@router.get(
    "/boqs/",
    response_model=list[BOQResponse],
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_boqs(
    project_id: uuid.UUID = Query(..., description="Filter BOQs by project"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BOQService = Depends(_get_service),
) -> list[BOQResponse]:
    """List all BOQs for a given project."""
    boqs, _ = await service.list_boqs_for_project(
        project_id, offset=offset, limit=limit
    )
    return [BOQResponse.model_validate(b) for b in boqs]


# ── Templates ────────────────────────────────────────────────────────────────


@router.get(
    "/boqs/templates",
    response_model=list[TemplateInfo],
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_templates(
    service: BOQService = Depends(_get_service),
) -> list[TemplateInfo]:
    """List all available BOQ templates.

    Returns summary information for each built-in template: name, description,
    icon, section count, and total position count.

    Templates cover common building types:
    - **residential** — Multi-family apartments, 3-5 floors
    - **office** — Commercial office, 4-8 floors
    - **warehouse** — Logistics warehouse, single-story
    - **school** — Primary/secondary school, 2-3 floors
    - **hospital** — General hospital or clinic
    - **hotel** — 3-5 star hotel with conference
    - **retail** — Shopping mall, 1-3 floors
    - **infrastructure** — Bridge / overpass
    """
    return service.list_templates()


@router.post(
    "/boqs/from-template",
    response_model=BOQResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.create"))],
)
async def create_boq_from_template(
    data: BOQFromTemplateRequest,
    _user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Create a complete BOQ from a built-in template.

    Provide the template ID, gross floor area (m2), and optionally a custom
    name.  The endpoint creates:
    - A new BOQ
    - Section headers for each trade group
    - All positions with quantities derived from ``area_m2 * qty_factor``

    Use ``GET /boqs/templates`` to discover available template IDs.
    """
    boq = await service.create_boq_from_template(data)
    return BOQResponse.model_validate(boq)


@router.get(
    "/boqs/{boq_id}",
    response_model=BOQWithPositions,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_boq(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> BOQWithPositions:
    """Get a BOQ with all its positions and grand total."""
    return await service.get_boq_with_positions(boq_id)


@router.get(
    "/boqs/{boq_id}/structured",
    response_model=BOQWithSections,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_boq_structured(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> BOQWithSections:
    """Get a BOQ with hierarchical sections, subtotals, markups, and totals.

    Returns the full structured view that a professional estimator needs:
    - Sections with grouped positions and subtotals
    - Ungrouped positions (no parent section)
    - Direct cost (sum of all item totals)
    - Markup lines with computed amounts
    - Net total (direct cost + markups)
    - Grand total
    """
    return await service.get_boq_structured(boq_id)


@router.get(
    "/boqs/{boq_id}/activity",
    response_model=ActivityLogList,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_boq_activity(
    boq_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BOQService = Depends(_get_service),
) -> ActivityLogList:
    """Get the activity log for a BOQ (paginated, newest first).

    Returns a chronological audit trail of all mutations: position additions,
    updates, deletions, markup changes, exports, etc.
    """
    return await service.get_activity_for_boq(boq_id, offset=offset, limit=limit)


@router.get(
    "/projects/{project_id}/activity",
    response_model=ActivityLogList,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_project_activity(
    project_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BOQService = Depends(_get_service),
) -> ActivityLogList:
    """Get the activity log for a project (paginated, newest first).

    Returns all BOQ-related activity across all BOQs in the project.
    """
    return await service.get_activity_for_project(
        project_id, offset=offset, limit=limit
    )


@router.patch(
    "/boqs/{boq_id}",
    response_model=BOQResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def update_boq(
    boq_id: uuid.UUID,
    data: BOQUpdate,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Update BOQ metadata (name, description, status)."""
    boq = await service.update_boq(boq_id, data)
    return BOQResponse.model_validate(boq)


@router.delete(
    "/boqs/{boq_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.delete"))],
)
async def delete_boq(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> None:
    """Delete a BOQ and all its positions."""
    await service.delete_boq(boq_id)


# ── Duplicate ────────────────────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/duplicate",
    response_model=BOQResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.create"))],
)
async def duplicate_boq(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Duplicate an entire BOQ with all its positions and markups.

    Creates a new BOQ named "<original> (Copy)" in the same project.
    All positions (with hierarchy) and markups are deep-copied with new IDs.
    """
    new_boq = await service.duplicate_boq(boq_id)
    return BOQResponse.model_validate(new_boq)


@router.post(
    "/positions/{position_id}/duplicate",
    response_model=PositionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def duplicate_position(
    position_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Duplicate a single position within the same BOQ.

    Creates a copy with ordinal "<original>.1" placed after the original.
    """
    new_position = await service.duplicate_position(position_id)
    return _position_to_response(new_position)


# ── Position CRUD ─────────────────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/positions",
    response_model=PositionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def add_position(
    boq_id: uuid.UUID,
    data: PositionCreate,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Add a new position to a BOQ.

    The boq_id in the URL takes precedence over the body field.
    """
    # Override body boq_id with URL path parameter
    data.boq_id = boq_id
    position = await service.add_position(data)
    return _position_to_response(position)


@router.patch(
    "/positions/{position_id}",
    response_model=PositionResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def update_position(
    position_id: uuid.UUID,
    data: PositionUpdate,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Update a BOQ position. Recalculates total if quantity or unit_rate changed."""
    position = await service.update_position(position_id, data)
    return _position_to_response(position)


@router.delete(
    "/positions/{position_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.delete"))],
)
async def delete_position(
    position_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> None:
    """Delete a single position."""
    await service.delete_position(position_id)


# ── Section CRUD ──────────────────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/sections",
    response_model=PositionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def create_section(
    boq_id: uuid.UUID,
    data: SectionCreate,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Create a section header row in a BOQ.

    Sections are positions with unit="section", quantity=0, unit_rate=0.
    They serve as grouping headers for estimating line items.
    """
    section = await service.create_section(boq_id, data)
    return _position_to_response(section)


# ── Markup CRUD ───────────────────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/markups",
    response_model=MarkupResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def add_markup(
    boq_id: uuid.UUID,
    data: MarkupCreate,
    service: BOQService = Depends(_get_service),
) -> MarkupResponse:
    """Add a markup/overhead line to a BOQ."""
    markup = await service.add_markup(boq_id, data)
    return _markup_to_response(markup)


@router.patch(
    "/boqs/{boq_id}/markups/{markup_id}",
    response_model=MarkupResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def update_markup(
    boq_id: uuid.UUID,
    markup_id: uuid.UUID,
    data: MarkupUpdate,
    service: BOQService = Depends(_get_service),
) -> MarkupResponse:
    """Update a markup/overhead line on a BOQ."""
    markup = await service.update_markup(markup_id, data)
    return _markup_to_response(markup)


@router.delete(
    "/boqs/{boq_id}/markups/{markup_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.delete"))],
)
async def delete_markup(
    boq_id: uuid.UUID,
    markup_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> None:
    """Delete a markup/overhead line from a BOQ."""
    await service.delete_markup(markup_id)


@router.post(
    "/boqs/{boq_id}/markups/apply-defaults",
    response_model=list[MarkupResponse],
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def apply_default_markups(
    boq_id: uuid.UUID,
    region: str = Query(
        default="DEFAULT",
        description="Region code: DACH, UK, US, RU, GULF, or DEFAULT",
    ),
    service: BOQService = Depends(_get_service),
) -> list[MarkupResponse]:
    """Apply regional default markups to a BOQ.

    Replaces any existing markups with the standard template for the region.

    Supported regions:
    - **DACH**: BGK 8%, AGK 5%, W&G 3%
    - **UK**: Preliminaries 12%, OH&P 6%, Contingency 5%
    - **US**: General Conditions 10%, OH&P 8%, Contingency 5%, Escalation 3%
    - **RU**: Overhead 15%, Estimated Profit 8%, VAT 20%
    - **GULF**: OH&P 10%, Contingency 5%, VAT 5%
    - **DEFAULT**: Overhead 10%, Profit 5%, Contingency 5%
    """
    markups = await service.apply_default_markups(boq_id, region)
    return [_markup_to_response(m) for m in markups]


# ── Validation ────────────────────────────────────────────────────────────────


def _build_rule_sets(
    project_rule_sets: list[str],
    classification_standard: str,
    region: str,
) -> list[str]:
    """Determine which validation rule sets to apply based on project config.

    Always includes the project's configured rule sets (default: ["boq_quality"]).
    Adds standard-specific rules based on classification_standard and region.

    Args:
        project_rule_sets: Explicit rule sets from project config.
        classification_standard: e.g. "din276", "nrm", "masterformat".
        region: e.g. "DACH", "UK", "US".

    Returns:
        Deduplicated list of rule set names.
    """
    rule_sets = list(project_rule_sets)

    # Add classification-standard-specific rules
    if classification_standard == "din276" and "din276" not in rule_sets:
        rule_sets.append("din276")
    if classification_standard == "nrm" and "nrm" not in rule_sets:
        rule_sets.append("nrm")
    if classification_standard == "masterformat" and "masterformat" not in rule_sets:
        rule_sets.append("masterformat")

    # Add region-specific rules
    if region.upper() == "DACH" and "gaeb" not in rule_sets:
        rule_sets.append("gaeb")
    if region.upper() == "UK" and "nrm" not in rule_sets:
        rule_sets.append("nrm")
    if region.upper() == "US" and "masterformat" not in rule_sets:
        rule_sets.append("masterformat")

    return rule_sets


@router.post(
    "/boqs/{boq_id}/validate",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def validate_boq(
    boq_id: uuid.UUID,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> dict[str, Any]:
    """Validate a BOQ against configured rule sets.

    Loads the BOQ with all positions, determines which validation rule sets
    to apply based on the project configuration, runs the validation engine,
    and returns a full validation report.
    """
    from app.core.validation.engine import validation_engine
    from app.modules.projects.repository import ProjectRepository

    # Load BOQ with positions
    boq_data = await service.get_boq_with_positions(boq_id)

    # Load project to get classification config
    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(boq_data.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found for this BOQ",
        )

    # Convert positions to the format expected by validation rules
    positions_data = [
        {
            "id": str(pos.id),
            "ordinal": pos.ordinal,
            "description": pos.description,
            "quantity": pos.quantity,
            "unit_rate": pos.unit_rate,
            "classification": pos.classification,
        }
        for pos in boq_data.positions
    ]

    # Determine rule sets from project config
    rule_sets = _build_rule_sets(
        project_rule_sets=project.validation_rule_sets or ["boq_quality"],
        classification_standard=project.classification_standard or "din276",
        region=project.region or "DACH",
    )

    # Run validation
    report = await validation_engine.validate(
        data={"positions": positions_data},
        rule_sets=rule_sets,
        target_type="boq",
        target_id=str(boq_id),
        project_id=str(boq_data.project_id),
        region=project.region,
        standard=project.classification_standard,
    )

    # Build response: summary + full results
    summary = report.summary()
    summary["results"] = [
        {
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "severity": r.severity.value,
            "passed": r.passed,
            "message": r.message,
            "element_ref": r.element_ref,
            "suggestion": r.suggestion,
        }
        for r in report.results
    ]

    return summary


# ── Export (CSV / Excel) ──────────────────────────────────────────────────────


def _get_classification_code(classification: dict[str, Any]) -> str:
    """Extract the most relevant classification code for display.

    Checks din276, nrm, masterformat in order.
    """
    if not classification:
        return ""
    for key in ("din276", "nrm", "masterformat"):
        val = classification.get(key, "")
        if val:
            return str(val)
    # Fall back to the first available key
    for val in classification.values():
        if val:
            return str(val)
    return ""


@router.get(
    "/boqs/{boq_id}/export/csv",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def export_boq_csv(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> StreamingResponse:
    """Export BOQ positions as a CSV file."""
    boq_data = await service.get_boq_with_positions(boq_id)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "Pos.",
        "Description",
        "Unit",
        "Quantity",
        "Unit Rate",
        "Total",
        "Classification",
    ])

    # Position rows
    for pos in boq_data.positions:
        writer.writerow([
            pos.ordinal,
            pos.description,
            pos.unit,
            f"{pos.quantity:.2f}",
            f"{pos.unit_rate:.2f}",
            f"{pos.total:.2f}",
            _get_classification_code(pos.classification),
        ])

    # Grand total row
    writer.writerow([
        "",
        "Grand Total",
        "",
        "",
        "",
        f"{boq_data.grand_total:.2f}",
        "",
    ])

    content = output.getvalue()
    output.close()

    safe_name = boq_data.name.encode("ascii", errors="replace").decode("ascii").replace('"', "'")
    filename = f"{safe_name}.csv"

    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/boqs/{boq_id}/export/excel",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def export_boq_excel(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> StreamingResponse:
    """Export BOQ positions as an Excel (xlsx) file with formatting."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, numbers
    from openpyxl.utils import get_column_letter

    boq_data = await service.get_boq_with_positions(boq_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"

    # ── Header row ────────────────────────────────────────────────────────
    headers = [
        "Pos.",
        "Description",
        "Unit",
        "Quantity",
        "Unit Rate",
        "Total",
        "Classification",
    ]
    bold_font = Font(bold=True)

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = bold_font

    # ── Position rows ─────────────────────────────────────────────────────
    number_format = numbers.FORMAT_NUMBER_COMMA_SEPARATED1  # #,##0.00

    for row_idx, pos in enumerate(boq_data.positions, start=2):
        ws.cell(row=row_idx, column=1, value=pos.ordinal)
        ws.cell(row=row_idx, column=2, value=pos.description)
        ws.cell(row=row_idx, column=3, value=pos.unit)

        qty_cell = ws.cell(row=row_idx, column=4, value=pos.quantity)
        qty_cell.number_format = number_format

        rate_cell = ws.cell(row=row_idx, column=5, value=pos.unit_rate)
        rate_cell.number_format = number_format

        total_cell = ws.cell(row=row_idx, column=6, value=pos.total)
        total_cell.number_format = number_format

        ws.cell(
            row=row_idx,
            column=7,
            value=_get_classification_code(pos.classification),
        )

    # ── Grand total row ───────────────────────────────────────────────────
    total_row = len(boq_data.positions) + 2
    total_label = ws.cell(row=total_row, column=2, value="Grand Total")
    total_label.font = bold_font

    grand_total_cell = ws.cell(row=total_row, column=6, value=boq_data.grand_total)
    grand_total_cell.font = bold_font
    grand_total_cell.number_format = number_format

    # ── Auto-width columns ────────────────────────────────────────────────
    for col_idx in range(1, len(headers) + 1):
        max_length = len(str(headers[col_idx - 1]))
        for row in ws.iter_rows(
            min_row=2,
            max_row=total_row,
            min_col=col_idx,
            max_col=col_idx,
        ):
            for cell in row:
                val = cell.value
                if val is not None:
                    max_length = max(max_length, len(str(val)))
        # Add a small padding; cap at 60 to avoid excessively wide columns
        adjusted = min(max_length + 3, 60)
        ws.column_dimensions[get_column_letter(col_idx)].width = adjusted

    # Align numeric columns to the right
    for row in ws.iter_rows(min_row=2, max_row=total_row, min_col=4, max_col=6):
        for cell in row:
            cell.alignment = Alignment(horizontal="right")

    # ── Write to bytes buffer and return ──────────────────────────────────
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    safe_name = boq_data.name.encode("ascii", errors="replace").decode("ascii").replace('"', "'")
    filename = f"{safe_name}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/boqs/{boq_id}/export/pdf",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def export_boq_pdf(
    boq_id: uuid.UUID,
    session: SessionDep,
    service: BOQService = Depends(_get_service),
) -> StreamingResponse:
    """Export BOQ as a professional PDF cost estimate report.

    Generates a multi-page PDF document with:
    - Cover page: project name, BOQ title, cost summary, date, status
    - BOQ table pages: sections, positions, subtotals, markups, totals
    - Running headers/footers with page numbering
    """
    from app.modules.boq.pdf_export import generate_boq_pdf
    from app.modules.projects.repository import ProjectRepository
    from app.modules.users.models import User

    boq_data = await service.get_boq_structured(boq_id)

    # Load project for cover page info
    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(boq_data.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found for this BOQ",
        )

    # Try to get the owner name for "Prepared by"
    prepared_by = ""
    owner = await session.get(User, project.owner_id)
    if owner is not None:
        prepared_by = owner.full_name or owner.email

    pdf_bytes = generate_boq_pdf(
        boq_data=boq_data,
        project_name=project.name,
        currency=project.currency or "EUR",
        prepared_by=prepared_by,
    )

    safe_name = (
        boq_data.name.encode("ascii", errors="replace")
        .decode("ascii")
        .replace('"', "'")
    )
    filename = f"{safe_name}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ── Import (CSV / Excel) ──────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

# Column name aliases for flexible matching (all lowercased for comparison)
_COLUMN_ALIASES: dict[str, list[str]] = {
    "ordinal": ["pos", "pos.", "position", "ordinal", "nr.", "nr", "no.", "no", "#"],
    "description": [
        "description", "beschreibung", "desc", "text", "bezeichnung",
        "item", "item description",
    ],
    "unit": ["unit", "einheit", "me", "uom", "unit of measure"],
    "quantity": ["quantity", "qty", "menge", "amount", "qty.", "quantity (qty)"],
    "unit_rate": [
        "unit rate", "rate", "ep", "einheitspreis", "unit price",
        "unit cost", "price", "rate (ep)",
    ],
    "total": ["total", "amount", "gesamtpreis", "gp", "sum", "total price"],
    "classification": [
        "classification", "din 276", "din276", "kg", "nrm", "code",
        "masterformat", "cost code", "cost group", "class",
    ],
}


def _match_column(header: str) -> str | None:
    """Match a header string to a canonical column name using the alias map.

    Args:
        header: Raw column header text from the uploaded file.

    Returns:
        Canonical column key (e.g. "ordinal", "description") or None if unrecognised.
    """
    normalised = header.strip().lower()
    for canonical, aliases in _COLUMN_ALIASES.items():
        if normalised in aliases:
            return canonical
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a value to float, returning *default* on failure.

    Handles strings with comma decimal separators (e.g. "1.234,56" → 1234.56).
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    # Handle European-style numbers: "1.234,56" → "1234.56"
    if "," in text and "." in text:
        # Determine which is the decimal separator (last one wins)
        last_comma = text.rfind(",")
        last_dot = text.rfind(".")
        if last_comma > last_dot:
            # Comma is decimal separator: "1.234,56"
            text = text.replace(".", "").replace(",", ".")
        else:
            # Dot is decimal separator: "1,234.56"
            text = text.replace(",", "")
    elif "," in text:
        # Only commas — assume comma is decimal separator: "234,56"
        text = text.replace(",", ".")
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


def _parse_rows_from_csv(content_bytes: bytes) -> list[dict[str, Any]]:
    """Parse rows from a CSV file.

    Tries UTF-8 first, then Latin-1 as fallback (common for DACH region files).

    Returns:
        List of dicts mapping canonical column names to cell values.
    """
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Unable to decode CSV file — unsupported encoding")

    # Detect delimiter by sniffing first 4KB
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]

    reader = csv.reader(io.StringIO(text), dialect)
    raw_headers = next(reader, None)
    if not raw_headers:
        raise ValueError("CSV file is empty or has no header row")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        canonical = _match_column(hdr)
        if canonical:
            column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical:
                row[canonical] = val.strip() if isinstance(val, str) else val
        if row:
            rows.append(row)

    return rows


def _parse_rows_from_excel(content_bytes: bytes) -> list[dict[str, Any]]:
    """Parse rows from an Excel (.xlsx) file using openpyxl.

    Reads the first (active) worksheet. The first row is treated as headers.

    Returns:
        List of dicts mapping canonical column names to cell values.
    """
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content_bytes), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("Excel file has no worksheets")

    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = next(rows_iter, None)
    if not raw_headers:
        raise ValueError("Excel file is empty or has no header row")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        if hdr is not None:
            canonical = _match_column(str(hdr))
            if canonical:
                column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in rows_iter:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical and val is not None:
                row[canonical] = val
        if row:
            rows.append(row)

    wb.close()
    return rows


@router.post(
    "/boqs/{boq_id}/import/excel",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def import_boq_excel(
    boq_id: uuid.UUID,
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    service: BOQService = Depends(_get_service),
) -> dict[str, Any]:
    """Import BOQ positions from an Excel or CSV file.

    Accepts a multipart file upload. The file must be .xlsx or .csv.

    Expected columns (all optional except Description):
    - **Pos / Position / Ordinal / Nr.** — position ordinal number
    - **Description / Beschreibung / Text** — description (required)
    - **Unit / Einheit / ME** — unit of measurement
    - **Quantity / Qty / Menge** — quantity
    - **Unit Rate / Rate / EP / Einheitspreis** — unit rate
    - **Total** (ignored — auto-calculated from quantity x rate)
    - **Classification / DIN 276 / KG / NRM / Code** — classification code

    Returns:
        Summary with counts of imported, skipped, and error details per row.
    """
    # Verify BOQ exists (raises 404 if not found)
    await service.get_boq(boq_id)

    # Validate file type
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".csv")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Please upload an Excel (.xlsx) or CSV (.csv) file.",
        )

    # Read file content
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Limit file size (10 MB)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 10 MB.",
        )

    # Parse rows based on file type
    try:
        if filename.endswith(".xlsx"):
            rows = _parse_rows_from_excel(content)
        else:
            rows = _parse_rows_from_csv(content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse file: {exc}",
        )
    except Exception as exc:
        logger.exception("Unexpected error parsing import file: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse file. Please check the format and try again.",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data rows found in file. Check that the first row contains column headers.",
        )

    # Import each row as a Position
    imported = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    auto_ordinal = 1

    for row_idx, row in enumerate(rows, start=2):  # start=2 because row 1 is header
        try:
            description = str(row.get("description", "")).strip()

            # Skip rows without a description (likely empty or total rows)
            if not description:
                skipped += 1
                continue

            # Skip rows that look like summary/total rows
            desc_lower = description.lower()
            if desc_lower in (
                "grand total", "total", "summe", "gesamt", "gesamtsumme",
                "subtotal", "zwischensumme",
            ):
                skipped += 1
                continue

            # Build ordinal: use from file or auto-generate
            ordinal = str(row.get("ordinal", "")).strip()
            if not ordinal:
                ordinal = str(auto_ordinal)
            auto_ordinal += 1

            # Parse unit
            unit = str(row.get("unit", "pcs")).strip()
            if not unit:
                unit = "pcs"

            # Parse numeric fields
            quantity = _safe_float(row.get("quantity"), default=0.0)
            unit_rate = _safe_float(row.get("unit_rate"), default=0.0)

            # Build classification from the classification column
            classification: dict[str, Any] = {}
            class_value = str(row.get("classification", "")).strip()
            if class_value:
                classification["code"] = class_value

            # Create position via service
            position_data = PositionCreate(
                boq_id=boq_id,
                ordinal=ordinal,
                description=description,
                unit=unit,
                quantity=quantity,
                unit_rate=unit_rate,
                classification=classification,
                source="excel_import",
            )
            await service.add_position(position_data)
            imported += 1

        except Exception as exc:
            errors.append({
                "row": row_idx,
                "error": str(exc),
                "data": {k: str(v)[:100] for k, v in row.items()},
            })
            logger.warning(
                "Import error at row %d for BOQ %s: %s", row_idx, boq_id, exc
            )

    logger.info(
        "BOQ import complete for %s: imported=%d, skipped=%d, errors=%d",
        boq_id, imported, skipped, len(errors),
    )

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total_rows": len(rows),
    }
