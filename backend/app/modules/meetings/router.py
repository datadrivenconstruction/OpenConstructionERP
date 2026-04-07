"""Meetings API routes.

Endpoints:
    GET    /                              - List meetings for a project
    POST   /                              - Create meeting (auto-generates meeting_number)
    GET    /{meeting_id}                  - Get single meeting
    PATCH  /{meeting_id}                  - Update meeting
    DELETE /{meeting_id}                  - Delete meeting
    POST   /{meeting_id}/complete         - Mark meeting as completed
    GET    /{meeting_id}/export/pdf       - Export meeting minutes as PDF
"""

import io
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.meetings.schemas import (
    MeetingCreate,
    MeetingResponse,
    MeetingUpdate,
)
from app.modules.meetings.service import MeetingService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> MeetingService:
    return MeetingService(session)


def _meeting_to_response(meeting: object) -> MeetingResponse:
    """Build a MeetingResponse from a Meeting ORM object."""
    return MeetingResponse(
        id=meeting.id,  # type: ignore[attr-defined]
        project_id=meeting.project_id,  # type: ignore[attr-defined]
        meeting_number=meeting.meeting_number,  # type: ignore[attr-defined]
        meeting_type=meeting.meeting_type,  # type: ignore[attr-defined]
        title=meeting.title,  # type: ignore[attr-defined]
        meeting_date=meeting.meeting_date,  # type: ignore[attr-defined]
        location=meeting.location,  # type: ignore[attr-defined]
        chairperson_id=(
            str(meeting.chairperson_id) if meeting.chairperson_id else None  # type: ignore[attr-defined]
        ),
        attendees=meeting.attendees or [],  # type: ignore[attr-defined]
        agenda_items=meeting.agenda_items or [],  # type: ignore[attr-defined]
        action_items=meeting.action_items or [],  # type: ignore[attr-defined]
        minutes=meeting.minutes,  # type: ignore[attr-defined]
        status=meeting.status,  # type: ignore[attr-defined]
        created_by=meeting.created_by,  # type: ignore[attr-defined]
        metadata=getattr(meeting, "metadata_", {}),
        created_at=meeting.created_at,  # type: ignore[attr-defined]
        updated_at=meeting.updated_at,  # type: ignore[attr-defined]
    )


# ── List ──────────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[MeetingResponse])
async def list_meetings(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    service: MeetingService = Depends(_get_service),
) -> list[MeetingResponse]:
    """List meetings for a project with optional filters."""
    meetings, _ = await service.list_meetings(
        project_id,
        offset=offset,
        limit=limit,
        meeting_type=type_filter,
        status_filter=status_filter,
    )
    return [_meeting_to_response(m) for m in meetings]


# ── Create ────────────────────────────────────────────────────────────────────


@router.post("/", response_model=MeetingResponse, status_code=201)
async def create_meeting(
    data: MeetingCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("meetings.create")),
    service: MeetingService = Depends(_get_service),
) -> MeetingResponse:
    """Create a new meeting with auto-generated meeting number."""
    meeting = await service.create_meeting(data, user_id=user_id)
    return _meeting_to_response(meeting)


# ── Get ───────────────────────────────────────────────────────────────────────


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MeetingService = Depends(_get_service),
) -> MeetingResponse:
    """Get a single meeting."""
    meeting = await service.get_meeting(meeting_id)
    return _meeting_to_response(meeting)


# ── Update ────────────────────────────────────────────────────────────────────


@router.patch("/{meeting_id}", response_model=MeetingResponse)
async def update_meeting(
    meeting_id: uuid.UUID,
    data: MeetingUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("meetings.update")),
    service: MeetingService = Depends(_get_service),
) -> MeetingResponse:
    """Update a meeting."""
    meeting = await service.update_meeting(meeting_id, data)
    return _meeting_to_response(meeting)


# ── Delete ────────────────────────────────────────────────────────────────────


@router.delete("/{meeting_id}", status_code=204)
async def delete_meeting(
    meeting_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("meetings.delete")),
    service: MeetingService = Depends(_get_service),
) -> None:
    """Delete a meeting."""
    await service.delete_meeting(meeting_id)


# ── Complete ──────────────────────────────────────────────────────────────────


@router.post("/{meeting_id}/complete", response_model=MeetingResponse)
async def complete_meeting(
    meeting_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("meetings.update")),
    service: MeetingService = Depends(_get_service),
) -> MeetingResponse:
    """Mark a meeting as completed."""
    meeting = await service.complete_meeting(meeting_id)
    return _meeting_to_response(meeting)


# ── PDF Export ───────────────────────────────────────────────────────────────


@router.get("/{meeting_id}/export/pdf")
async def export_meeting_pdf(
    meeting_id: uuid.UUID,
    session: SessionDep = None,  # type: ignore[assignment]
    _user: CurrentUserId = None,  # type: ignore[assignment]
) -> StreamingResponse:
    """Export meeting minutes as a PDF document."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )
    from sqlalchemy import select

    from app.modules.meetings.models import Meeting
    from app.modules.projects.models import Project

    result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
    meeting = result.scalar_one_or_none()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Fetch project name
    proj_result = await session.execute(
        select(Project.name).where(Project.id == meeting.project_id)
    )
    project_name = proj_result.scalar_one_or_none() or "Unknown Project"

    # ── Build PDF ────────────────────────────────────────────────────────
    PAGE_WIDTH, PAGE_HEIGHT = A4
    MARGIN = 20 * mm
    USABLE_WIDTH = PAGE_WIDTH - 2 * MARGIN

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "MeetingTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=4 * mm,
    )
    style_subtitle = ParagraphStyle(
        "MeetingSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
        spaceAfter=6 * mm,
    )
    style_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        spaceBefore=6 * mm,
        spaceAfter=3 * mm,
    )
    style_body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
    )
    style_small = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=colors.HexColor("#777777"),
    )

    elements: list = []

    # Header
    elements.append(Paragraph("Meeting Minutes", style_title))
    elements.append(Paragraph(project_name, style_subtitle))
    elements.append(Paragraph(meeting.title, style_heading))

    # Meeting info table
    info_data = [
        ["Date:", meeting.meeting_date or "N/A"],
        ["Location:", meeting.location or "N/A"],
        ["Type:", (meeting.meeting_type or "").replace("_", " ").title()],
        ["Meeting #:", meeting.meeting_number],
        ["Status:", (meeting.status or "").replace("_", " ").title()],
    ]
    info_table = Table(info_data, colWidths=[30 * mm, USABLE_WIDTH - 30 * mm])
    info_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    elements.append(info_table)
    elements.append(Spacer(1, 4 * mm))

    # Attendees
    attendees = meeting.attendees or []
    if attendees:
        elements.append(Paragraph("Attendees", style_heading))
        att_data = [["Name", "Company", "Status"]]
        for att in attendees:
            if isinstance(att, dict):
                att_data.append([
                    att.get("name", ""),
                    att.get("company", att.get("role", "")),
                    att.get("status", "").replace("_", " ").title(),
                ])
        att_table = Table(
            att_data,
            colWidths=[USABLE_WIDTH * 0.4, USABLE_WIDTH * 0.35, USABLE_WIDTH * 0.25],
        )
        att_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(att_table)

    # Agenda items
    agenda = meeting.agenda_items or []
    if agenda:
        elements.append(Paragraph("Agenda", style_heading))
        for idx, item in enumerate(agenda, 1):
            if isinstance(item, dict):
                topic = item.get("topic", item.get("title", ""))
                presenter = item.get("presenter", "")
                notes = item.get("notes", "")
                line = f"<b>{idx}.</b> {topic}"
                if presenter:
                    line += f"  <i>({presenter})</i>"
                elements.append(Paragraph(line, style_body))
                if notes:
                    elements.append(
                        Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{notes}", style_small)
                    )

    # Action items
    actions = meeting.action_items or []
    if actions:
        elements.append(Paragraph("Action Items", style_heading))
        act_data = [["#", "Description", "Owner", "Due Date", "Status"]]
        for idx, ai in enumerate(actions, 1):
            if isinstance(ai, dict):
                status_str = "Completed" if ai.get("completed") else (
                    ai.get("status", "Open").replace("_", " ").title()
                )
                act_data.append([
                    str(idx),
                    ai.get("description", ""),
                    ai.get("owner", ai.get("owner_id", "")),
                    ai.get("due_date", ""),
                    status_str,
                ])
        act_table = Table(
            act_data,
            colWidths=[
                USABLE_WIDTH * 0.06,
                USABLE_WIDTH * 0.40,
                USABLE_WIDTH * 0.20,
                USABLE_WIDTH * 0.17,
                USABLE_WIDTH * 0.17,
            ],
        )
        act_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(act_table)

    # Footer timestamp
    elements.append(Spacer(1, 10 * mm))
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    elements.append(
        Paragraph(f"Generated: {generated_at}", style_small)
    )

    # Build document
    buf = io.BytesIO()

    def _header_footer(canvas_obj, doc):  # type: ignore[no-untyped-def]
        canvas_obj.saveState()
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.setFillColor(colors.HexColor("#999999"))
        canvas_obj.drawString(
            MARGIN, PAGE_HEIGHT - 12 * mm, f"{project_name} — {meeting.title}"
        )
        canvas_obj.drawRightString(
            PAGE_WIDTH - MARGIN,
            10 * mm,
            f"Page {doc.page}",
        )
        canvas_obj.restoreState()

    frame = Frame(MARGIN, MARGIN, USABLE_WIDTH, PAGE_HEIGHT - 2 * MARGIN, id="main")
    doc = BaseDocTemplate(buf, pagesize=A4)
    doc.addPageTemplates(
        [PageTemplate(id="main", frames=[frame], onPage=_header_footer)]
    )
    doc.build(elements)

    buf.seek(0)
    safe_title = meeting.title.replace(" ", "_")[:50]
    filename = f"meeting_{meeting.meeting_number}_{safe_title}.pdf"

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
