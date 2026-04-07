"""Meetings API routes.

Endpoints:
    GET    /                              - List meetings for a project
    POST   /                              - Create meeting (auto-generates meeting_number)
    POST   /import-summary                - Import meeting from transcript file (AI-powered)
    GET    /{meeting_id}                  - Get single meeting
    PATCH  /{meeting_id}                  - Update meeting
    DELETE /{meeting_id}                  - Delete meeting
    POST   /{meeting_id}/complete         - Mark meeting as completed
    GET    /{meeting_id}/export/pdf       - Export meeting minutes as PDF
"""

import io
import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.meetings.schemas import (
    ActionItemEntry,
    AgendaItemEntry,
    AttendeeEntry,
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


# ── Import Summary (AI-powered transcript parsing) ──────────────────────────


def _parse_vtt_transcript(content: str) -> list[dict[str, str]]:
    """Parse WebVTT (.vtt) transcript into structured segments.

    VTT format:
        WEBVTT

        00:00:00.000 --> 00:00:05.000
        Speaker Name: Hello everyone...

    Returns:
        List of dicts with 'speaker', 'text', and 'timestamp' keys.
    """
    segments: list[dict[str, str]] = []
    lines = content.strip().splitlines()
    current_speaker = ""
    current_text = ""
    current_ts = ""

    ts_pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3})"
    )

    for line in lines:
        line = line.strip()
        if not line or line.upper() == "WEBVTT" or line.startswith("NOTE"):
            continue

        ts_match = ts_pattern.match(line)
        if ts_match:
            # Save previous segment
            if current_text:
                segments.append(
                    {"speaker": current_speaker, "text": current_text.strip(), "timestamp": current_ts}
                )
                current_text = ""
            current_ts = ts_match.group(1)
            continue

        # Skip numeric cue identifiers
        if line.isdigit():
            continue

        # Check for speaker tag: "Speaker Name: text"
        speaker_match = re.match(r"^<v\s+([^>]+)>(.*)$", line)
        if speaker_match:
            current_speaker = speaker_match.group(1).strip()
            current_text += " " + speaker_match.group(2).strip()
        elif ": " in line and len(line.split(": ", 1)[0]) < 50:
            parts = line.split(": ", 1)
            current_speaker = parts[0].strip()
            current_text += " " + parts[1].strip()
        else:
            current_text += " " + line

    # Final segment
    if current_text:
        segments.append(
            {"speaker": current_speaker, "text": current_text.strip(), "timestamp": current_ts}
        )

    return segments


def _parse_srt_transcript(content: str) -> list[dict[str, str]]:
    """Parse SRT subtitle format into structured segments.

    SRT format:
        1
        00:00:00,000 --> 00:00:05,000
        Speaker Name: Hello everyone...

    Returns:
        List of dicts with 'speaker', 'text', and 'timestamp' keys.
    """
    segments: list[dict[str, str]] = []
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue

        # Skip numeric index and timestamp line
        text_lines = []
        timestamp = ""
        for line in lines:
            if line.strip().isdigit():
                continue
            ts_match = re.match(
                r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
                line.strip(),
            )
            if ts_match:
                timestamp = ts_match.group(1)
                continue
            text_lines.append(line.strip())

        text = " ".join(text_lines).strip()
        if not text:
            continue

        speaker = ""
        if ": " in text and len(text.split(": ", 1)[0]) < 50:
            parts = text.split(": ", 1)
            speaker = parts[0].strip()
            text = parts[1].strip()

        segments.append({"speaker": speaker, "text": text, "timestamp": timestamp})

    return segments


def _parse_plain_text(content: str) -> list[dict[str, str]]:
    """Parse plain text transcript (line by line).

    Attempts to detect speaker patterns like 'Name: text' or '[Name] text'.

    Returns:
        List of dicts with 'speaker', 'text', and 'timestamp' keys.
    """
    segments: list[dict[str, str]] = []
    for line in content.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        speaker = ""
        text = line

        # Pattern: [Speaker Name] text
        bracket_match = re.match(r"^\[([^\]]+)\]\s*(.*)$", line)
        if bracket_match:
            speaker = bracket_match.group(1).strip()
            text = bracket_match.group(2).strip()
        # Pattern: Speaker Name: text
        elif ": " in line and len(line.split(": ", 1)[0]) < 50:
            parts = line.split(": ", 1)
            # Avoid splitting on time-like patterns (e.g., "10:30")
            if not re.match(r"^\d{1,2}$", parts[0]):
                speaker = parts[0].strip()
                text = parts[1].strip()

        if text:
            segments.append({"speaker": speaker, "text": text, "timestamp": ""})

    return segments


def _extract_meeting_data_heuristic(
    segments: list[dict[str, str]],
    filename: str,
) -> dict:
    """Extract meeting structure from transcript segments using heuristics.

    Identifies:
    - Attendees from speaker tags
    - Action items from keywords (action, todo, will do, deadline, by Friday)
    - Key decisions from keywords (decided, agreed, approved, confirmed)
    - Meeting title from filename or first meaningful line

    Returns:
        Dict with title, attendees, agenda_items, action_items, and minutes.
    """
    attendees: dict[str, str] = {}  # name -> role
    action_items: list[dict] = []
    decisions: list[str] = []
    discussion_topics: list[str] = []
    all_text_parts: list[str] = []

    action_keywords = re.compile(
        r"\b(action\s*item|todo|to-do|will\s+do|deadline|assigned\s+to|"
        r"responsible|follow\s*up|by\s+(monday|tuesday|wednesday|thursday|friday|"
        r"saturday|sunday|next\s+week|end\s+of\s+week|eow|eod))\b",
        re.IGNORECASE,
    )
    decision_keywords = re.compile(
        r"\b(decided|agreed|approved|confirmed|resolved|conclusion|decision)\b",
        re.IGNORECASE,
    )
    topic_keywords = re.compile(
        r"\b(agenda|topic|item\s+\d|point\s+\d|discuss|discussion)\b",
        re.IGNORECASE,
    )

    for seg in segments:
        speaker = seg.get("speaker", "").strip()
        text = seg.get("text", "").strip()

        if speaker and speaker not in attendees:
            attendees[speaker] = ""

        if text:
            all_text_parts.append(text)

        # Check for action items
        if action_keywords.search(text):
            owner = speaker or "TBD"
            action_items.append(
                {
                    "description": text[:500],
                    "owner_id": None,
                    "owner_name": owner,
                    "due_date": None,
                    "status": "open",
                }
            )

        # Check for decisions
        if decision_keywords.search(text):
            decisions.append(text[:500])

        # Check for agenda/topic mentions
        if topic_keywords.search(text):
            discussion_topics.append(text[:300])

    # Derive title from filename
    title = "Imported Meeting"
    clean_name = re.sub(r"\.(txt|vtt|srt|docx|pdf)$", "", filename, flags=re.IGNORECASE)
    clean_name = clean_name.replace("_", " ").replace("-", " ").strip()
    if clean_name:
        title = clean_name

    # Build minutes from all text
    minutes_text = "\n".join(all_text_parts[:200])  # Cap at ~200 lines
    if decisions:
        minutes_text += "\n\n--- Key Decisions ---\n" + "\n".join(
            f"- {d}" for d in decisions[:20]
        )

    # Build attendee list
    attendee_list = [
        {"name": name, "company": "", "status": "present"}
        for name in attendees
    ]

    # Build agenda items from discussion topics
    agenda_list = [
        {"topic": topic, "presenter": None, "notes": None}
        for topic in discussion_topics[:20]
    ]

    # Detect source platform from content hints
    source = "other"
    full_text_lower = " ".join(all_text_parts[:50]).lower()
    if "teams" in full_text_lower or "microsoft teams" in filename.lower():
        source = "teams"
    elif "google meet" in full_text_lower or "meet" in filename.lower():
        source = "google_meet"
    elif "zoom" in full_text_lower or "zoom" in filename.lower():
        source = "zoom"

    return {
        "title": title,
        "attendees": attendee_list,
        "agenda_items": agenda_list,
        "action_items": action_items,
        "minutes": minutes_text[:10000],
        "source": source,
        "decisions": decisions[:20],
        "segments_count": len(segments),
    }


async def _extract_text_from_file(file_content: bytes, filename: str) -> str:
    """Extract text content from uploaded file based on extension.

    Supports: .txt, .vtt, .srt, .docx, .pdf
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in ("txt", "vtt", "srt"):
        # Try UTF-8 first, then latin-1 as fallback
        try:
            return file_content.decode("utf-8")
        except UnicodeDecodeError:
            return file_content.decode("latin-1", errors="replace")

    if ext == "docx":
        try:
            from docx import Document as DocxDocument

            doc = DocxDocument(io.BytesIO(file_content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            logger.warning("python-docx not installed, falling back to raw text extraction")
            # Fallback: extract text from docx XML
            import zipfile

            with zipfile.ZipFile(io.BytesIO(file_content)) as zf:
                if "word/document.xml" in zf.namelist():
                    xml_content = zf.read("word/document.xml").decode("utf-8", errors="replace")
                    # Strip XML tags to get plain text
                    return re.sub(r"<[^>]+>", " ", xml_content).strip()
            return ""

    if ext == "pdf":
        try:
            import pdfplumber

            text_parts = []
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                for page in pdf.pages[:50]:  # Cap at 50 pages
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n".join(text_parts)
        except ImportError:
            logger.warning("pdfplumber not installed, cannot extract PDF text")
            return ""
        except Exception as exc:
            logger.warning("Failed to extract text from PDF: %s", exc)
            return ""

    # Unknown format — try as plain text
    try:
        return file_content.decode("utf-8")
    except UnicodeDecodeError:
        return file_content.decode("latin-1", errors="replace")


@router.post("/import-summary", response_model=MeetingResponse, status_code=201)
async def import_meeting_summary(
    project_id: uuid.UUID = Query(...),
    file: UploadFile = File(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("meetings.create")),
    service: MeetingService = Depends(_get_service),
) -> MeetingResponse:
    """Import a meeting summary from a transcript file.

    Accepts: .txt, .vtt, .srt, .docx, .pdf files (transcripts/notes).

    AI-free heuristic parsing extracts:
    - Meeting title (from filename)
    - Attendees list (from speaker tags)
    - Discussion topics
    - Action items with owners
    - Key decisions
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Validate file extension
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    allowed_extensions = {"txt", "vtt", "srt", "docx", "pdf"}
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '.{ext}'. Accepted: {', '.join(sorted(allowed_extensions))}",
        )

    # Read file content (limit to 10MB)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10MB.")

    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    # Extract text
    text_content = await _extract_text_from_file(content, file.filename)
    if not text_content.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not extract any text from the file. Please check the file format.",
        )

    # Parse into segments based on format
    if ext == "vtt":
        segments = _parse_vtt_transcript(text_content)
    elif ext == "srt":
        segments = _parse_srt_transcript(text_content)
    else:
        segments = _parse_plain_text(text_content)

    if not segments:
        raise HTTPException(
            status_code=400,
            detail="Could not parse any content from the transcript.",
        )

    # Extract meeting data using heuristics
    extracted = _extract_meeting_data_heuristic(segments, file.filename)

    # Try AI-enhanced parsing if available
    ai_used = False
    try:
        from sqlalchemy import select

        from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_and_key
        from app.modules.ai.models import AISettings

        result = await service.session.execute(
            select(AISettings).where(AISettings.user_id == uuid.UUID(str(user_id)))
        )
        ai_settings = result.scalar_one_or_none()

        if ai_settings:
            provider, api_key = resolve_provider_and_key(ai_settings)

            # Truncate transcript for AI prompt
            transcript_preview = text_content[:8000]
            ai_prompt = (
                "Analyze this meeting transcript and extract structured data.\n"
                "Return a JSON object with these fields:\n"
                '- "title": string (meeting title)\n'
                '- "attendees": [{name, company, role}]\n'
                '- "agenda_items": [{topic, presenter, notes}]\n'
                '- "action_items": [{description, owner_name, due_date, status}]\n'
                '- "decisions": [string]\n'
                '- "summary": string (brief meeting summary)\n\n'
                f"Transcript:\n{transcript_preview}"
            )

            raw_response, _tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system="You are a meeting transcript analyzer. Extract structured meeting data from transcripts. Return valid JSON only.",
                prompt=ai_prompt,
                max_tokens=4096,
            )

            ai_data = extract_json(raw_response)
            if isinstance(ai_data, dict):
                ai_used = True
                # Merge AI results with heuristic results (AI takes priority)
                if ai_data.get("title"):
                    extracted["title"] = ai_data["title"]
                if ai_data.get("attendees") and isinstance(ai_data["attendees"], list):
                    extracted["attendees"] = [
                        {
                            "name": a.get("name", "Unknown"),
                            "company": a.get("company", a.get("role", "")),
                            "status": "present",
                        }
                        for a in ai_data["attendees"]
                        if isinstance(a, dict) and a.get("name")
                    ]
                if ai_data.get("agenda_items") and isinstance(ai_data["agenda_items"], list):
                    extracted["agenda_items"] = [
                        {
                            "topic": item.get("topic", ""),
                            "presenter": item.get("presenter"),
                            "notes": item.get("notes"),
                        }
                        for item in ai_data["agenda_items"]
                        if isinstance(item, dict) and item.get("topic")
                    ]
                if ai_data.get("action_items") and isinstance(ai_data["action_items"], list):
                    extracted["action_items"] = [
                        {
                            "description": item.get("description", ""),
                            "owner_id": None,
                            "owner_name": item.get("owner_name", item.get("owner", "TBD")),
                            "due_date": item.get("due_date"),
                            "status": item.get("status", "open"),
                        }
                        for item in ai_data["action_items"]
                        if isinstance(item, dict) and item.get("description")
                    ]
                if ai_data.get("summary"):
                    extracted["minutes"] = str(ai_data["summary"])[:10000]
                if ai_data.get("decisions") and isinstance(ai_data["decisions"], list):
                    extracted["decisions"] = ai_data["decisions"][:20]

    except Exception as exc:
        # AI is optional — log and continue with heuristic results
        logger.debug("AI-enhanced transcript parsing skipped: %s", exc)

    # Create meeting from extracted data
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    attendees_data = [
        {
            "name": att.get("name", "Unknown"),
            "company": att.get("company", ""),
            "status": att.get("status", "present"),
        }
        for att in extracted.get("attendees", [])
    ]

    agenda_data = [
        {
            "number": str(idx + 1),
            "topic": item.get("topic", "Discussion item"),
            "presenter": item.get("presenter"),
            "notes": item.get("notes"),
        }
        for idx, item in enumerate(extracted.get("agenda_items", []))
    ]

    action_data = [
        {
            "description": item.get("description", ""),
            "owner_id": item.get("owner_id"),
            "due_date": item.get("due_date"),
            "status": item.get("status", "open"),
        }
        for item in extracted.get("action_items", [])
        if item.get("description")
    ]

    meeting_create = MeetingCreate(
        project_id=project_id,
        meeting_type="progress",
        title=extracted.get("title", "Imported Meeting"),
        meeting_date=today,
        location=None,
        chairperson_id=None,
        attendees=[
            AttendeeEntry(
                name=att["name"],
                company=att.get("company"),
                status=att.get("status", "present"),
            )
            for att in attendees_data
        ],
        agenda_items=[
            AgendaItemEntry(
                number=item.get("number"),
                topic=item.get("topic", "Discussion item"),
                presenter=item.get("presenter"),
                notes=item.get("notes"),
            )
            for item in agenda_data
        ],
        action_items=[
            ActionItemEntry(
                description=item["description"],
                owner_id=item.get("owner_id"),
                due_date=item.get("due_date"),
                status=item.get("status", "open"),
            )
            for item in action_data
        ],
        minutes=extracted.get("minutes"),
        status="completed",
        metadata={
            "imported_from": file.filename,
            "import_source": extracted.get("source", "other"),
            "ai_enhanced": ai_used,
            "segments_parsed": extracted.get("segments_count", 0),
            "decisions": extracted.get("decisions", []),
        },
    )

    meeting = await service.create_meeting(meeting_create, user_id=user_id)

    logger.info(
        "Meeting imported from transcript: file=%s, attendees=%d, actions=%d, ai=%s",
        file.filename,
        len(attendees_data),
        len(action_data),
        ai_used,
    )

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
    """Mark a meeting as completed.

    Requires status to be 'scheduled' or 'in_progress'.
    Draft meetings must be scheduled first.
    Open action items are automatically converted to tasks.
    """
    meeting = await service.complete_meeting(meeting_id, user_id=user_id)
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
