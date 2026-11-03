# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project agent catalogue: four ready agents a project enables and configures.

* ``rfi_drafter``        - RFI draft from a question, a markup or a site photo,
  with the sheets and spec sections it refers to.
* ``daily_reporter``     - daily report draft from the day's timesheets,
  photos, voice notes, weather and deliveries.
* ``clause_reviewer``    - flags payment terms, liquidated damages,
  indemnity, retention and termination clauses against a configurable
  checklist, each finding cited.
* ``submittal_checker``  - checks a submittal against the requirements of
  its spec section.

Each agent is a regular :class:`~app.modules.ai_agents.base.Agent` in the
global registry (so it also appears in the gallery and can run through the
ReAct loop), and its tools are regular registry tools. All of them are
read-only: they gather, they never write. What an agent produces is an
:class:`~app.modules.ai_agents.models.AgentDraft`, which only a person turns
into a record.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from app.modules.ai_agents.agents._access import assert_user_can_access_project, coerce_user_id
from app.modules.ai_agents.base import Agent, FunctionTool, global_tool_registry, register_agent
from app.modules.ai_agents.catalogue_logic import DEFAULT_CLAUSE_CHECKLIST
from app.modules.doc_assistant.core import BM25Index, Hit, Passage

logger = logging.getLogger(__name__)

TOOL_SEARCH = "project_search_passages"
TOOL_DAY = "project_day_records"
TOOL_SUBMITTAL = "project_get_submittal"
TOOL_MARKUP = "project_get_markup"

DEFAULT_REVIEW_AFTER_DAYS = 7
DEFAULT_MAX_TOKENS_PER_RUN = 8_000


@dataclass(frozen=True)
class InputField:
    """One input the run form asks for."""

    key: str
    kind: str  # text | date | record
    required: bool = False
    record: str | None = None  # for kind=record: rfi | submittal | contract | markup | photo | document


@dataclass
class CatalogueSpec:
    """What the catalogue page shows and what a run needs."""

    name: str
    draft_kind: str
    display_name: str
    tagline: str
    icon: str
    entry_surface: str  # rfi | daily_report | contract | submittal
    inputs: list[InputField]
    tools: list[str]
    default_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable descriptor for the API."""
        return {
            "name": self.name,
            "draft_kind": self.draft_kind,
            "display_name": self.display_name,
            "tagline": self.tagline,
            "icon": self.icon,
            "entry_surface": self.entry_surface,
            "inputs": [vars(i) for i in self.inputs],
            "tools": self.tools,
            "default_config": self.default_config,
            "read_only_tools": True,
        }


CATALOGUE: dict[str, CatalogueSpec] = {
    spec.name: spec
    for spec in (
        CatalogueSpec(
            name="rfi_drafter",
            draft_kind="rfi",
            display_name="RFI drafter",
            tagline="Turns a question, markup or photo into an RFI draft with referenced sheets and spec sections",
            icon="message-square-plus",
            entry_surface="rfi",
            inputs=[
                InputField("question", "text", required=True),
                InputField("markup_id", "record", record="markup"),
                InputField("photo_id", "record", record="photo"),
            ],
            tools=[TOOL_SEARCH, TOOL_MARKUP],
            default_config={"review_after_days": DEFAULT_REVIEW_AFTER_DAYS},
        ),
        CatalogueSpec(
            name="daily_reporter",
            draft_kind="daily_report",
            display_name="Daily report drafter",
            tagline="Drafts the day's report from timesheets, photos, voice notes, weather and deliveries",
            icon="calendar-days",
            entry_surface="daily_report",
            inputs=[InputField("date", "date", required=True)],
            tools=[TOOL_DAY],
            default_config={"review_after_days": 2},
        ),
        CatalogueSpec(
            name="clause_reviewer",
            draft_kind="clause_review",
            display_name="Contract clause reviewer",
            tagline="Flags payment, liquidated damages, indemnity, retention and termination clauses with citations",
            icon="scale",
            entry_surface="contract",
            inputs=[
                InputField("document_id", "record", record="document"),
                InputField("contract_id", "record", record="contract"),
            ],
            tools=[TOOL_SEARCH],
            default_config={"review_after_days": DEFAULT_REVIEW_AFTER_DAYS, "checklist": DEFAULT_CLAUSE_CHECKLIST},
        ),
        CatalogueSpec(
            name="submittal_checker",
            draft_kind="submittal_check",
            display_name="Submittal checker",
            tagline="Checks a submittal against the requirements of its spec section",
            icon="clipboard-check",
            entry_surface="submittal",
            inputs=[InputField("submittal_id", "record", required=True, record="submittal")],
            tools=[TOOL_SUBMITTAL, TOOL_SEARCH],
            default_config={"review_after_days": DEFAULT_REVIEW_AFTER_DAYS},
        ),
    )
}


# ── Hits travel through tools as JSON ───────────────────────────────────────


def hit_to_json(hit: Hit) -> dict[str, Any]:
    """A ranked passage as a tool observation (text included, so the audit shows what was read)."""
    p = hit.passage
    return {
        **p.citation(0, hit.score),
        "text": p.text,
        "coverage": round(hit.coverage, 4),
        "is_current": p.is_current,
    }


def hits_from_json(items: list[dict[str, Any]]) -> list[Hit]:
    """Rebuild :class:`Hit` objects from a tool observation."""
    out: list[Hit] = []
    for it in items or []:
        passage = Passage(
            passage_id=str(it.get("passage_id")),
            source_kind=str(it.get("source_kind")),
            source_id=str(it.get("source_id")),
            title=str(it.get("title") or ""),
            text=str(it.get("text") or it.get("snippet") or ""),
            document_id=it.get("document_id"),
            revision=it.get("revision"),
            page=it.get("page"),
            sheet_number=it.get("sheet_number"),
            section=it.get("section"),
            is_current=bool(it.get("is_current", True)),
            deep_link=str(it.get("deep_link") or ""),
        )
        out.append(Hit(passage, float(it.get("score") or 0.0), float(it.get("coverage") or 0.0)))
    return out


# ── Tools (read-only) ───────────────────────────────────────────────────────


async def _scope(context: dict | None, session: Any) -> tuple[uuid.UUID, uuid.UUID, str] | None:
    user_id = coerce_user_id(context)
    try:
        project_id = uuid.UUID(str((context or {}).get("project_id")))
    except (TypeError, ValueError):
        return None
    if user_id is None or not await assert_user_can_access_project(session, project_id, user_id):
        return None
    return user_id, project_id, str((context or {}).get("role") or "viewer")


async def _tool_search(
    q: str,
    kinds: list[str] | None = None,
    document_id: str | None = None,
    k: int = 6,
    __agent_context__: dict | None = None,  # noqa: N803 - runner-injected key
) -> dict[str, Any]:
    from app.database import async_session_factory
    from app.modules.doc_assistant.sources import collect_passages

    async with async_session_factory() as session:
        scope = await _scope(__agent_context__, session)
        if scope is None:
            return {"error": "unavailable", "hits": []}
        user_id, project_id, role = scope
        passages = await collect_passages(
            session, project_id, role=role, user_id=str(user_id), kinds=set(kinds) if kinds else None
        )
    if document_id:
        passages = [p for p in passages if p.document_id == document_id or p.source_id == document_id]
    hits = BM25Index(passages).search(q, k=max(1, min(int(k or 6), 12)))
    return {"query": q, "searched": len(passages), "hits": [hit_to_json(h) for h in hits]}


def _day_bounds(day: str) -> tuple[datetime, datetime]:
    d = date.fromisoformat(day)
    start = datetime.combine(d, time.min).astimezone()
    return start, start + timedelta(days=1)


async def _tool_day_records(
    date: str,  # noqa: A002 - the tool's public argument name
    __agent_context__: dict | None = None,  # noqa: N803
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.database import async_session_factory

    try:
        start, end = _day_bounds(date)
    except ValueError:
        return {"error": "invalid_date", "records": {}}
    records: dict[str, list[dict[str, Any]]] = {
        k: [] for k in ("timesheets", "photos", "voice_notes", "weather", "deliveries")
    }
    async with async_session_factory() as session:
        scope = await _scope(__agent_context__, session)
        if scope is None:
            return {"error": "unavailable", "records": {}}
        _, project_id, _ = scope
        try:
            from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine

            stmt = (
                select(FieldTimesheetLine, FieldTimesheet)
                .join(FieldTimesheet, FieldTimesheet.id == FieldTimesheetLine.timesheet_id)
                .where(FieldTimesheet.project_id == project_id, FieldTimesheet.date == start.date())
            )
            for line, sheet in (await session.execute(stmt)).all():
                records["timesheets"].append(
                    {
                        "id": str(line.id),
                        "resource": str(line.resource_id or line.equipment_id or line.id),
                        "hours": float(line.hours or 0),
                        "label": sheet.reference or "timesheet",
                    }
                )
        except Exception:  # noqa: BLE001 - one missing source must not empty the report
            logger.info("Timesheets unavailable for daily report", exc_info=True)
        try:
            from app.modules.daily_diary.models import DailyDiary, DiaryEntry, DiaryPhoto, WeatherRecord

            for w in (
                await session.execute(
                    select(WeatherRecord).where(
                        WeatherRecord.project_id == project_id,
                        WeatherRecord.captured_at >= start,
                        WeatherRecord.captured_at < end,
                    )
                )
            ).scalars():
                records["weather"].append(
                    {
                        "id": str(w.id),
                        "captured_at": w.captured_at.isoformat() if w.captured_at else None,
                        "conditions": w.conditions_text or w.conditions_code,
                        "temperature_c": float(w.temperature_c) if w.temperature_c is not None else None,
                        "precipitation_mm": float(w.precipitation_mm) if w.precipitation_mm is not None else None,
                        "label": w.conditions_text or "weather",
                    }
                )
            for p in (
                await session.execute(
                    select(DiaryPhoto).where(
                        DiaryPhoto.project_id == project_id, DiaryPhoto.taken_at >= start, DiaryPhoto.taken_at < end
                    )
                )
            ).scalars():
                records["photos"].append({"id": str(p.id), "description": p.description, "label": p.location_label})
            stmt = (
                select(DiaryEntry)
                .join(DailyDiary, DailyDiary.id == DiaryEntry.diary_id)
                .where(DailyDiary.project_id == project_id, DiaryEntry.entry_time >= start, DiaryEntry.entry_time < end)
            )
            for e in (await session.execute(stmt)).scalars():
                row = {"id": str(e.id), "title": e.title, "description": e.description}
                if e.entry_type == "delivery":
                    records["deliveries"].append(row)
                elif (e.source_module or "") == "voice" or (e.metadata_ or {}).get("source") == "voice":
                    records["voice_notes"].append(row)
        except Exception:  # noqa: BLE001
            logger.info("Diary records unavailable for daily report", exc_info=True)
    return {"date": date, "records": records}


async def _tool_get_submittal(
    submittal_id: str,
    __agent_context__: dict | None = None,  # noqa: N803
) -> dict[str, Any]:
    from app.database import async_session_factory
    from app.modules.submittals.models import Submittal

    async with async_session_factory() as session:
        scope = await _scope(__agent_context__, session)
        if scope is None:
            return {"error": "unavailable"}
        try:
            row = await session.get(Submittal, uuid.UUID(str(submittal_id)))
        except (TypeError, ValueError):
            row = None
        if row is None or row.project_id != scope[1]:
            return {"error": "not_found"}
        history = " ".join(
            str(h.get("comment") or h.get("note") or "") for h in (row.review_history or []) if isinstance(h, dict)
        )
        return {
            "id": str(row.id),
            "number": row.submittal_number,
            "title": row.title,
            "spec_section": row.spec_section,
            "submittal_type": row.submittal_type,
            "manufacturer": row.manufacturer,
            "model_reference": row.model_reference,
            "text": history,
        }


async def _tool_get_markup(
    markup_id: str,
    __agent_context__: dict | None = None,  # noqa: N803
) -> dict[str, Any]:
    from app.database import async_session_factory
    from app.modules.markups.models import Markup

    async with async_session_factory() as session:
        scope = await _scope(__agent_context__, session)
        if scope is None:
            return {"error": "unavailable"}
        try:
            row = await session.get(Markup, uuid.UUID(str(markup_id)))
        except (TypeError, ValueError):
            row = None
        if row is None or getattr(row, "project_id", None) != scope[1]:
            return {"error": "not_found"}
        return {
            "id": str(row.id),
            "document_id": row.document_id,
            "page": row.page,
            "label": row.label,
            "text": row.text,
        }


_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "q": {"type": "string"},
        "kinds": {"type": "array", "items": {"type": "string"}},
        "document_id": {"type": "string"},
        "k": {"type": "integer"},
    },
    "required": ["q"],
}


def register_catalogue() -> None:
    """Register the catalogue tools and agents (idempotent)."""
    tools = [
        FunctionTool(
            TOOL_SEARCH,
            "Search the project's specifications, drawings, contracts, RFIs, submittals, letters and minutes "
            "the invoking user may read. Read-only. Returns ranked passages with document, revision, page, "
            "sheet and section.",
            _SEARCH_SCHEMA,
            _tool_search,
        ),
        FunctionTool(
            TOOL_DAY,
            "Read one day's timesheets, diary photos, voice notes, weather and deliveries. Read-only.",
            {"type": "object", "properties": {"date": {"type": "string", "format": "date"}}, "required": ["date"]},
            _tool_day_records,
        ),
        FunctionTool(
            TOOL_SUBMITTAL,
            "Read one submittal (title, spec section, manufacturer, model, review notes). Read-only.",
            {"type": "object", "properties": {"submittal_id": {"type": "string"}}, "required": ["submittal_id"]},
            _tool_get_submittal,
        ),
        FunctionTool(
            TOOL_MARKUP,
            "Read one drawing markup (document, page, label, text). Read-only.",
            {"type": "object", "properties": {"markup_id": {"type": "string"}}, "required": ["markup_id"]},
            _tool_get_markup,
        ),
    ]
    for tool in tools:
        global_tool_registry.register(tool)
    for spec in CATALOGUE.values():
        register_agent(
            Agent(
                name=spec.name,
                display_name=spec.display_name,
                category="project_catalogue",
                icon=spec.icon,
                tagline=spec.tagline,
                description=spec.tagline,
                system_prompt=(
                    "You are a construction project assistant. Use only the tool results. Cite the document, "
                    "revision, page or sheet for every statement. Produce a draft for a human to review; never "
                    "claim that a record was created."
                ),
                allowed_tools=list(spec.tools),
                max_total_tokens=DEFAULT_MAX_TOKENS_PER_RUN,
            )
        )
