# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site assistants: morning briefing, diary draft, RFI completeness, meeting actions.

Every assistant has two paths. With an AI provider the LLM adds a narrative or proposals;
without one (or when the call fails) the same facts come back from rules and templates and the
result is flagged ``degraded``. Output is a proposal stored on an :class:`AgentRun`
(``final_output`` holds the JSON envelope); nothing reaches the diary, an RFI or a meeting until
:func:`confirm_proposal` is called with the items the person accepted.

Server text stays language-neutral: items carry codes and facts, the client renders them with
its own locale. Only the LLM narrative and extracted text are free prose.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
import weakref
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.validation.engine import validation_engine
from app.modules.ai_agents.accuracy_service import record_ai_feedback
from app.modules.ai_agents.models import AgentRun, AgentStep, SiteAssistantPref
from app.modules.ai_agents.site_rules import AI_SITE_RULE_SET

logger = logging.getLogger(__name__)

AGENT_BRIEFING = "site_briefing"
AGENT_DIARY = "diary_draft"
AGENT_RFI = "rfi_completeness"
AGENT_MEETING = "meeting_actions"
SITE_AGENTS = (AGENT_BRIEFING, AGENT_DIARY, AGENT_RFI, AGENT_MEETING)

BRIEFING_SECTIONS = ("weather", "rfis", "inspections", "deliveries", "diary")
RATE_LIMIT_PER_HOUR = 20
PROMPT_CAP_TOKENS = 24_000
PROMPT_CAP_CHARS = PROMPT_CAP_TOKENS * 4
LLM_TIMEOUT_SECONDS = 90
HELPFUL_MIN_WORKING_DAYS = 3
HEURISTIC_CONFIDENCE = 0.4
PHOTO_CLUSTER_GAP = timedelta(minutes=60)
MAX_ACTIONS = 30

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GPS_DECIMAL = re.compile(r"-?\d{1,3}\.\d{3,}\s*[,;/]\s*-?\d{1,3}\.\d{3,}")
_GPS_DMS = re.compile(r"\d{1,3}\s*°\s*\d{1,2}\s*[′']\s*[\d.]*\s*[″\"]?\s*[NSEWnsew]?")
_DRAWING_REF = re.compile(
    r"\b(drawing|dwg|sheet|spec(?:ification)?|section|detail|clause|gridline|grid)\b\s*[\w.\-/]*\d"
    r"|\b[A-Z]{1,3}[-_ ]?\d{2,}[A-Za-z0-9.\-_/]*\b",
    re.IGNORECASE,
)
_LOCATION_WORDS = re.compile(
    r"\b(level|floor|room|zone|block|wing|stair|core|basement|roof|grid|axis)\b", re.IGNORECASE
)

_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _llm_lock() -> asyncio.Semaphore:
    """One LLM-backed run at a time per process (the 3 GB server budget)."""
    loop = asyncio.get_running_loop()
    lock = _locks.get(loop)
    if lock is None:
        lock = asyncio.Semaphore(1)
        _locks[loop] = lock
    return lock


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ── Provider ──────────────────────────────────────────────────────────────


async def resolve_llm(session: AsyncSession, user_id: uuid.UUID) -> Any | None:
    """The caller's LLM bridge, or ``None`` when no provider is configured."""
    from app.modules.ai_agents.service import _resolve_production_llm

    try:
        return await _resolve_production_llm(session, user_id)
    except Exception:  # noqa: BLE001 - a broken settings row means "no provider"
        logger.warning("site assistants: provider resolution failed", exc_info=True)
        return None


def provider_name(bridge: Any) -> str:
    return str(getattr(bridge, "provider", None) or type(bridge).__name__)


def scrub_text(text: str | None) -> str:
    """Remove GPS coordinates from free text before it can reach a prompt."""
    if not text:
        return ""
    return _GPS_DMS.sub("[removed]", _GPS_DECIMAL.sub("[removed]", str(text)))


def _fit_prompt(payload: dict[str, Any], trim_keys: tuple[str, ...]) -> str:
    """Serialise ``payload`` under the prompt cap by dropping trailing list entries."""
    text = json.dumps(payload, ensure_ascii=False, default=str)
    while len(text) > PROMPT_CAP_CHARS:
        key = max(
            (k for k in trim_keys if isinstance(payload.get(k), list) and payload[k]),
            key=lambda k: len(json.dumps(payload[k], default=str)),
            default=None,
        )
        if key is None:
            return text[:PROMPT_CAP_CHARS]
        payload[key] = payload[key][:-1]
        text = json.dumps(payload, ensure_ascii=False, default=str)
    return text


def _parse_json_object(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def ask_json(
    bridge: Any, system: str, payload: dict[str, Any], *, trim_keys: tuple[str, ...] = ()
) -> tuple[dict[str, Any] | None, int]:
    """One prompt to the bridge; the reply parsed as a JSON object, ``None`` on any failure."""
    prompt = _fit_prompt(payload, trim_keys)
    try:
        async with _llm_lock():
            item, tokens = await asyncio.wait_for(
                bridge.next_step(system_prompt=system, messages=[{"role": "user", "content": prompt}], tools=[]),
                timeout=LLM_TIMEOUT_SECONDS,
            )
    except Exception:  # noqa: BLE001 - any provider failure degrades to the rule-based result
        logger.warning("site assistant LLM call failed", exc_info=True)
        return None, 0
    if not isinstance(item, dict) or item.get("type") != "final":
        return None, int(tokens or 0)
    return _parse_json_object(str(item.get("text") or "")), int(tokens or 0)


async def ask_text(bridge: Any, system: str, payload: dict[str, Any]) -> tuple[str | None, int]:
    prompt = _fit_prompt(payload, ())
    try:
        async with _llm_lock():
            item, tokens = await asyncio.wait_for(
                bridge.next_step(system_prompt=system, messages=[{"role": "user", "content": prompt}], tools=[]),
                timeout=LLM_TIMEOUT_SECONDS,
            )
    except Exception:  # noqa: BLE001
        logger.warning("site assistant LLM call failed", exc_info=True)
        return None, 0
    text = str(item.get("text") or "").strip() if isinstance(item, dict) and item.get("type") == "final" else ""
    return (text or None), int(tokens or 0)


# ── Rules, rate limit, runs ───────────────────────────────────────────────


async def validate_request(data: dict[str, Any], *, locale: str = "en") -> None:
    """Run the ``ai_site_assistants`` rule set; 422 on the first failing error."""
    report = await validation_engine.validate(
        data=data,
        rule_sets=[AI_SITE_RULE_SET],
        target_type="ai_site_request",
        target_id=str(data.get("project_id") or ""),
        project_id=str(data.get("project_id") or "") or None,
        metadata={"locale": locale},
    )
    failed = [r for r in report.results if not r.passed and not r.is_engine_error]
    if failed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"rule_id": failed[0].rule_id, "message": failed[0].message, "suggestion": failed[0].suggestion},
        )


async def enforce_rate_limit(session: AsyncSession, user_id: uuid.UUID) -> None:
    since = _iso(_now() - timedelta(hours=1))
    count = (
        await session.execute(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.user_id == user_id, AgentRun.agent_name.in_(SITE_AGENTS), AgentRun.started_at >= since)
        )
    ).scalar_one()
    if count >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"rule_id": "ai_site_assistants.rate_limit", "limit": RATE_LIMIT_PER_HOUR, "window": "hour"},
            headers={"Retry-After": "600"},
        )


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 1.0


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


async def _save_run(
    session: AsyncSession,
    *,
    agent: str,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    user_input: str,
    envelope: dict[str, Any],
    tokens: int = 0,
) -> dict[str, Any]:
    run = AgentRun(
        agent_name=agent,
        project_id=project_id,
        user_id=user_id,
        status="completed",
        trigger_source=envelope.pop("_trigger", "manual"),
        user_input=user_input[:500],
        total_tokens=tokens,
        started_at=_iso(_now()),
        finished_at=_iso(_now()),
        trust={
            "site": True,
            "provider_used": envelope["provider_used"],
            "degraded": envelope["degraded"],
            "confidence": envelope["confidence"],
        },
    )
    session.add(run)
    await session.flush()
    envelope["proposal_id"] = str(run.id)
    envelope["agent"] = agent
    envelope["status"] = "pending"
    envelope["created_at"] = run.started_at
    run.final_output = json.dumps(envelope, ensure_ascii=False, default=str)
    await session.flush()
    return envelope


async def load_proposal(session: AsyncSession, proposal_id: uuid.UUID) -> tuple[AgentRun, dict[str, Any]]:
    run = await session.get(AgentRun, proposal_id)
    if run is None or run.agent_name not in SITE_AGENTS or not run.final_output:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    try:
        envelope = json.loads(run.final_output)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found") from exc
    return run, envelope


def _store_envelope(run: AgentRun, envelope: dict[str, Any]) -> None:
    run.final_output = json.dumps(envelope, ensure_ascii=False, default=str)


# ── 1. Morning briefing ───────────────────────────────────────────────────


def _location(address: Any) -> tuple[float, float] | None:
    if not isinstance(address, dict):
        return None
    lat = next((address.get(k) for k in ("lat", "latitude") if address.get(k) not in (None, "")), None)
    lng = next((address.get(k) for k in ("lng", "lon", "longitude") if address.get(k) not in (None, "")), None)
    try:
        return (float(lat), float(lng)) if lat is not None and lng is not None else None
    except (TypeError, ValueError):
        return None


async def get_pref(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> SiteAssistantPref | None:
    return (
        await session.execute(
            select(SiteAssistantPref).where(
                SiteAssistantPref.project_id == project_id, SiteAssistantPref.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def gather_briefing_facts(
    session: AsyncSession, project_id: uuid.UUID, today: date, sections: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Facts for one project only; every query filters on ``project_id``."""
    from app.modules.daily_diary.models import DailyDiary, DiaryEntry
    from app.modules.inspections.models import QualityInspection
    from app.modules.projects.models import Project
    from app.modules.rfi.models import RFI
    from app.modules.site_logistics.models import DeliveryBooking

    items: list[dict[str, Any]] = []
    iso_today = today.isoformat()

    if "weather" in sections:
        project = await session.get(Project, project_id)
        loc = _location(project.address if project else None)
        if loc is not None:
            from app.modules.daily_diary.weather import fetch_weather_for_day

            try:
                summary = await fetch_weather_for_day(loc[0], loc[1], today)
            except Exception:  # noqa: BLE001 - weather is best effort
                summary = None
            if summary:
                items.append(
                    {
                        "id": "weather",
                        "section": "weather",
                        "count": 1,
                        "entries": [
                            {
                                "conditions": summary.get("conditions_text"),
                                "temperature_c": _num(summary.get("temperature_c")),
                                "wind_kmh": _num(summary.get("wind_speed_kmh")),
                                "precipitation_mm": _num(summary.get("precipitation_mm")),
                            }
                        ],
                        "confidence": 1.0,
                    }
                )

    if "rfis" in sections:
        rows = (
            (await session.execute(select(RFI).where(RFI.project_id == project_id, RFI.status == "open")))
            .scalars()
            .all()
        )
        overdue = [r for r in rows if r.response_due_date and str(r.response_due_date)[:10] < iso_today]
        rest = [r for r in rows if r not in overdue]
        for sid, group in (("rfis_overdue", overdue), ("rfis_open", rest)):
            if group:
                group.sort(key=lambda r: str(r.response_due_date or "9999"))
                items.append(
                    {
                        "id": sid,
                        "section": "rfis",
                        "count": len(group),
                        "entries": [
                            {
                                "ref": r.rfi_number,
                                "title": r.subject,
                                "due": str(r.response_due_date or "")[:10] or None,
                            }
                            for r in group[:5]
                        ],
                        "confidence": 1.0,
                    }
                )

    if "inspections" in sections:
        horizon = (today + timedelta(days=2)).isoformat()
        rows = (
            (
                await session.execute(
                    select(QualityInspection).where(
                        QualityInspection.project_id == project_id, QualityInspection.status == "scheduled"
                    )
                )
            )
            .scalars()
            .all()
        )
        due = sorted(
            (r for r in rows if r.inspection_date and iso_today <= str(r.inspection_date)[:10] <= horizon),
            key=lambda r: str(r.inspection_date),
        )
        if due:
            items.append(
                {
                    "id": "inspections_due",
                    "section": "inspections",
                    "count": len(due),
                    "entries": [
                        {"ref": r.inspection_number, "title": r.title, "due": str(r.inspection_date)[:16]}
                        for r in due[:5]
                    ],
                    "confidence": 1.0,
                }
            )

    if "deliveries" in sections:
        start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
        rows = (
            (
                await session.execute(
                    select(DeliveryBooking)
                    .where(
                        DeliveryBooking.project_id == project_id,
                        DeliveryBooking.window_start >= start,
                        DeliveryBooking.window_start < start + timedelta(days=1),
                        DeliveryBooking.status.notin_(("cancelled", "rejected")),
                    )
                    .order_by(DeliveryBooking.window_start)
                )
            )
            .scalars()
            .all()
        )
        if rows:
            items.append(
                {
                    "id": "deliveries_today",
                    "section": "deliveries",
                    "count": len(rows),
                    "entries": [
                        {
                            "ref": r.po_ref,
                            "title": r.supplier_name,
                            "materials": (r.materials_desc or "")[:120] or None,
                            "due": r.window_start.astimezone(UTC).strftime("%H:%M"),
                        }
                        for r in rows[:5]
                    ],
                    "confidence": 1.0,
                }
            )

    if "diary" in sections:
        yesterday = (today - timedelta(days=1)).isoformat()
        diary = (
            await session.execute(
                select(DailyDiary).where(DailyDiary.project_id == project_id, DailyDiary.diary_date == yesterday)
            )
        ).scalar_one_or_none()
        if diary is not None:
            entries = (
                await session.execute(
                    select(func.count()).select_from(DiaryEntry).where(DiaryEntry.diary_id == diary.id)
                )
            ).scalar_one()
            items.append(
                {
                    "id": "diary_yesterday",
                    "section": "diary",
                    "count": int(entries),
                    "entries": [
                        {
                            "date": yesterday,
                            "labour": diary.labour_count,
                            "equipment": diary.equipment_count,
                            "notes": (diary.notes or "")[:300] or None,
                        }
                    ],
                    "confidence": 1.0,
                }
            )
    return items


def _num(value: Any) -> float | None:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


async def run_briefing(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    locale: str = "en",
    refresh: bool = False,
    trigger: str = "manual",
) -> dict[str, Any]:
    today = _now().date()
    if not refresh:
        existing = await latest_briefing(session, project_id, user_id)
        if existing is not None and existing.get("day") == today.isoformat():
            return existing
    await enforce_rate_limit(session, user_id)

    pref = await get_pref(session, project_id, user_id)
    chosen = tuple(s for s in (pref.enabled_sections if pref else []) if s in BRIEFING_SECTIONS) or BRIEFING_SECTIONS
    items = await gather_briefing_facts(session, project_id, today, chosen)

    bridge = await resolve_llm(session, user_id)
    narrative, tokens, used = None, 0, None
    if bridge is not None and items:
        narrative, tokens = await ask_text(
            bridge,
            "You brief a construction site manager before the working day. Write 3 to 5 plain sentences from the "
            f"facts only, no invention, no markdown. Answer in the language with code '{locale}'.",
            {"date": today.isoformat(), "facts": items},
        )
        used = provider_name(bridge) if narrative else None
    envelope = {
        "kind": AGENT_BRIEFING,
        "day": today.isoformat(),
        "provider_used": used,
        "degraded": used is None,
        "items": items,
        "confidence": _mean([i["confidence"] for i in items]),
        "narrative": narrative,
        "sections": list(chosen),
        "_trigger": trigger,
    }
    saved = await _save_run(
        session,
        agent=AGENT_BRIEFING,
        project_id=project_id,
        user_id=user_id,
        user_input=today.isoformat(),
        envelope=envelope,
        tokens=tokens,
    )
    saved["status"] = "ready"
    run = await session.get(AgentRun, uuid.UUID(saved["proposal_id"]))
    _store_envelope(run, saved)  # type: ignore[arg-type]
    await event_bus.publish(
        "ai_agents.site.briefing.ready",
        {
            "project_id": str(project_id),
            "user_id": str(user_id),
            "proposal_id": saved["proposal_id"],
            "trigger": trigger,
        },
        source_module="ai_agents",
    )
    return saved


async def latest_briefing(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any] | None:
    run = (
        await session.execute(
            select(AgentRun)
            .where(
                AgentRun.project_id == project_id, AgentRun.user_id == user_id, AgentRun.agent_name == AGENT_BRIEFING
            )
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None or not run.final_output:
        return None
    try:
        return json.loads(run.final_output)
    except ValueError:
        return None


async def fire_due_briefings(now: datetime | None = None) -> int:
    """Scheduler tick: run the briefing for every enabled preference whose time has come, one at a time."""
    from app.database import async_session_factory

    moment = now or _now()
    hhmm = moment.strftime("%H:%M")
    fired = 0
    async with async_session_factory() as session:
        prefs = (
            (await session.execute(select(SiteAssistantPref).where(SiteAssistantPref.enabled.is_(True))))
            .scalars()
            .all()
        )
        due = [(p.project_id, p.user_id) for p in prefs if (p.briefing_time or "06:30") <= hhmm]
    for project_id, user_id in due:
        async with async_session_factory() as session:
            try:
                if await latest_today(session, project_id, user_id, moment.date()):
                    continue
                from app.core import cost_scope

                with cost_scope.caller_scope(user_id):
                    await run_briefing(session, project_id=project_id, user_id=user_id, trigger="schedule")
                await session.commit()
                fired += 1
            except Exception:  # noqa: BLE001 - one user's failure never stops the tick
                await session.rollback()
                logger.exception("scheduled site briefing failed for %s/%s", project_id, user_id)
    return fired


async def latest_today(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID, day: date) -> bool:
    existing = await latest_briefing(session, project_id, user_id)
    return existing is not None and existing.get("day") == day.isoformat()


# ── 2. Diary draft ────────────────────────────────────────────────────────


def cluster_photos(photos: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group photos taken within an hour of each other; GPS never enters ``photos``."""
    clusters: list[list[dict[str, Any]]] = []
    for photo in sorted(photos, key=lambda p: p["taken_at"]):
        if clusters and photo["taken_at"] - clusters[-1][-1]["taken_at"] <= PHOTO_CLUSTER_GAP:
            clusters[-1].append(photo)
        else:
            clusters.append([photo])
    return clusters


def _template_diary_items(
    clusters: list[list[dict[str, Any]]], transcripts: list[str], weather: str | None
) -> list[dict]:
    items: list[dict[str, Any]] = []
    for idx, cluster in enumerate(clusters):
        captions = list(dict.fromkeys(p["caption"] for p in cluster if p["caption"]))
        items.append(
            {
                "id": f"c{idx}",
                "source": "photos",
                "time": cluster[0]["taken_at"].strftime("%H:%M"),
                "time_to": cluster[-1]["taken_at"].strftime("%H:%M"),
                "photo_count": len(cluster),
                "activity": "; ".join(captions)[:300],
                "trade": None,
                "crew_count": None,
                "weather_notes": weather,
                "confidence": 0.3 if captions else 0.15,
            }
        )
    for idx, text in enumerate(transcripts):
        items.append(
            {
                "id": f"t{idx}",
                "source": "transcript",
                "time": None,
                "time_to": None,
                "photo_count": 0,
                "activity": text[:300],
                "raw": text[:4000],
                "trade": None,
                "crew_count": None,
                "weather_notes": weather,
                "confidence": 0.2,
            }
        )
    return items


async def run_diary_draft(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    diary_date: str,
    transcripts: list[str],
    locale: str = "en",
) -> dict[str, Any]:
    from app.modules.daily_diary.models import DailyDiary, DiaryPhoto

    await validate_request({"project_id": str(project_id), "diary_date": diary_date}, locale=locale)
    await enforce_rate_limit(session, user_id)
    day = date.fromisoformat(diary_date)
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    # Only time and caption are read: latitude and longitude never leave the database row.
    rows = (
        await session.execute(
            select(DiaryPhoto.taken_at, DiaryPhoto.description)
            .where(
                DiaryPhoto.project_id == project_id,
                DiaryPhoto.taken_at >= start,
                DiaryPhoto.taken_at < start + timedelta(days=1),
                DiaryPhoto.is_archived.is_(False),
            )
            .order_by(DiaryPhoto.taken_at)
            .limit(300)
        )
    ).all()
    photos = [{"taken_at": t if t.tzinfo else t.replace(tzinfo=UTC), "caption": scrub_text(d).strip()} for t, d in rows]
    clean = [scrub_text(t).strip() for t in transcripts if t and t.strip()][:20]
    diary = (
        await session.execute(
            select(DailyDiary).where(DailyDiary.project_id == project_id, DailyDiary.diary_date == diary_date)
        )
    ).scalar_one_or_none()
    weather = None
    if diary is not None and isinstance(diary.weather_summary, dict):
        weather = diary.weather_summary.get("conditions_text") or None

    clusters = cluster_photos(photos)
    items = _template_diary_items(clusters, clean, weather)
    used, tokens = None, 0
    bridge = await resolve_llm(session, user_id) if items else None
    if bridge is not None:
        payload = {
            "date": diary_date,
            "photo_clusters": [
                {
                    "id": f"c{i}",
                    "from": c[0]["taken_at"].strftime("%H:%M"),
                    "to": c[-1]["taken_at"].strftime("%H:%M"),
                    "photos": len(c),
                    "captions": [p["caption"] for p in c if p["caption"]][:20],
                }
                for i, c in enumerate(clusters)
            ],
            "transcripts": [{"id": f"t{i}", "text": t} for i, t in enumerate(clean)],
            "known_weather": weather,
        }
        data, tokens = await ask_json(
            bridge,
            "You draft site diary entries for a construction site from photo captions with times and voice "
            "transcripts. Propose one entry per distinct activity. Never invent facts; use null when unknown. "
            'Reply with JSON only: {"entries":[{"activity":str,"trade":str|null,"crew_count":int|null,'
            '"weather_notes":str|null,"time":"HH:MM"|null,"confidence":0..1,"sources":[ids]}]}. '
            f"Write text in the language with code '{locale}' unless the source text is in another language.",
            payload,
            trim_keys=("transcripts", "photo_clusters"),
        )
        proposed = _sanitize_diary_entries(data)
        if proposed:
            items, used = proposed, provider_name(bridge)
    envelope = {
        "kind": AGENT_DIARY,
        "diary_date": diary_date,
        "provider_used": used,
        "degraded": used is None,
        "items": items,
        "confidence": _mean([i["confidence"] for i in items]),
    }
    return await _save_run(
        session,
        agent=AGENT_DIARY,
        project_id=project_id,
        user_id=user_id,
        user_input=diary_date,
        envelope=envelope,
        tokens=tokens,
    )


def _sanitize_diary_entries(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, raw in enumerate((data or {}).get("entries") or []):
        if not isinstance(raw, dict) or not str(raw.get("activity") or "").strip():
            continue
        crew = raw.get("crew_count")
        time_s = str(raw.get("time") or "")
        out.append(
            {
                "id": f"e{idx}",
                "source": "ai",
                "time": time_s if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time_s) else None,
                "time_to": None,
                "photo_count": 0,
                "activity": str(raw["activity"]).strip()[:300],
                "trade": (str(raw.get("trade")).strip()[:60] or None) if raw.get("trade") else None,
                "crew_count": int(crew) if isinstance(crew, (int, float)) and 0 <= crew <= 5000 else None,
                "weather_notes": (str(raw.get("weather_notes"))[:200] or None) if raw.get("weather_notes") else None,
                "confidence": _clamp(raw.get("confidence")),
                "sources": [str(s) for s in (raw.get("sources") or []) if isinstance(s, (str, int))][:10],
            }
        )
        if len(out) >= 30:
            break
    return out


# ── 3. RFI completeness ───────────────────────────────────────────────────


def working_days_between(start: date, end: date) -> int:
    """Working days (Mon-Fri) after ``start`` up to and including ``end``; negative when ``end`` is earlier."""
    if end < start:
        return -working_days_between(end, start)
    return sum(1 for i in range(1, (end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5)


def rfi_rule_checks(rfi: Any, today: date) -> list[dict[str, Any]]:
    """Deterministic completeness checks; ``params`` feed the client's localized message."""
    question = (getattr(rfi, "question", "") or "").strip()
    subject = (getattr(rfi, "subject", "") or "").strip()
    text = f"{subject} {question}"
    linked = list(getattr(rfi, "linked_drawing_ids", None) or [])
    attachments = list(getattr(rfi, "attachments", None) or [])
    checks: list[dict[str, Any]] = []

    q_len = len(question)
    checks.append(
        {
            "id": "question",
            "status": "fail" if q_len < 10 else "warn" if q_len < 40 else "ok",
            "params": {"length": q_len},
        }
    )
    has_ref = bool(linked) or bool(_DRAWING_REF.search(text))
    checks.append({"id": "reference", "status": "ok" if has_ref else "warn", "params": {}})
    has_where = bool(attachments) or bool(linked) or bool(_LOCATION_WORDS.search(text))
    checks.append({"id": "attachment_or_location", "status": "ok" if has_where else "warn", "params": {}})
    checks.append(
        {
            "id": "discipline",
            "status": "ok" if (getattr(rfi, "discipline", None) or "").strip() else "fail",
            "params": {},
        }
    )

    raw_due = str(getattr(rfi, "response_due_date", None) or getattr(rfi, "date_required", None) or "")[:10]
    if not _ISO_DATE.match(raw_due):
        checks.append({"id": "due_date", "status": "fail", "params": {"minimum_days": HELPFUL_MIN_WORKING_DAYS}})
    else:
        days = working_days_between(today, date.fromisoformat(raw_due))
        checks.append(
            {
                "id": "due_date",
                "status": "ok" if days >= HELPFUL_MIN_WORKING_DAYS else "warn",
                "params": {"working_days": days, "minimum_days": HELPFUL_MIN_WORKING_DAYS},
            }
        )
    impact_set = bool(
        getattr(rfi, "cost_impact", False)
        or getattr(rfi, "schedule_impact", False)
        or getattr(rfi, "cost_impact_value", None)
        or getattr(rfi, "schedule_impact_days", None)
    )
    checks.append({"id": "impact", "status": "ok" if impact_set else "warn", "params": {}})
    return checks


def rfi_score(checks: list[dict[str, Any]]) -> int:
    points = {"ok": 1.0, "warn": 0.5, "fail": 0.0}
    rule_checks = [c for c in checks if c.get("source") != "ai"]
    return round(100 * sum(points[c["status"]] for c in rule_checks) / max(len(rule_checks), 1))


async def run_rfi_check(
    session: AsyncSession, *, rfi_id: uuid.UUID, project_id: uuid.UUID | None, user_id: uuid.UUID, locale: str = "en"
) -> dict[str, Any]:
    from app.modules.rfi.models import RFI

    rfi = await session.get(RFI, rfi_id)
    if rfi is None or (project_id is not None and rfi.project_id != project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFI not found")
    await validate_request(
        {"project_id": str(rfi.project_id), "record_project_id": str(rfi.project_id), "rfi_status": rfi.status},
        locale=locale,
    )
    await enforce_rate_limit(session, user_id)

    checks = rfi_rule_checks(rfi, _now().date())
    used, tokens = None, 0
    bridge = await resolve_llm(session, user_id)
    if bridge is not None:
        data, tokens = await ask_json(
            bridge,
            "You review a draft RFI (request for information) on a construction project for ambiguity. "
            "List up to 3 concrete ambiguities a recipient could misread, each with a short fix. "
            'Reply with JSON only: {"advice":[{"issue":str,"suggestion":str,"confidence":0..1}]}. '
            f"Write in the language with code '{locale}'.",
            {"subject": rfi.subject, "question": (rfi.question or "")[:6000], "discipline": rfi.discipline},
        )
        advice = [a for a in ((data or {}).get("advice") or []) if isinstance(a, dict) and a.get("issue")]
        for idx, a in enumerate(advice[:3]):
            checks.append(
                {
                    "id": f"ambiguity_{idx}",
                    "status": "warn",
                    "source": "ai",
                    "params": {"issue": str(a["issue"])[:300], "suggestion": str(a.get("suggestion") or "")[:300]},
                    "confidence": _clamp(a.get("confidence")),
                }
            )
        used = provider_name(bridge) if data is not None else None
    for c in checks:
        c.setdefault("source", "rule")
        c.setdefault("confidence", 1.0)
    envelope = {
        "kind": AGENT_RFI,
        "rfi_id": str(rfi_id),
        "provider_used": used,
        "degraded": used is None,
        "items": checks,
        "checks": checks,
        "score": rfi_score(checks),
        "has_fail": any(c["status"] == "fail" for c in checks),
        "confidence": _mean([c["confidence"] for c in checks]),
    }
    return await _save_run(
        session,
        agent=AGENT_RFI,
        project_id=rfi.project_id,
        user_id=user_id,
        user_input=str(rfi_id),
        envelope=envelope,
        tokens=tokens,
    )


async def record_rfi_override(
    session: AsyncSession, *, rfi_id: uuid.UUID, user_id: uuid.UUID, reason: str, proposal_id: uuid.UUID | None
) -> dict[str, Any]:
    """Store why a person sent an RFI that failed the check (step on the run plus feedback)."""
    from app.modules.rfi.models import RFI

    rfi = await session.get(RFI, rfi_id)
    if rfi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFI not found")
    if proposal_id is not None:
        run, envelope = await load_proposal(session, proposal_id)
        if run.agent_name != AGENT_RFI or envelope.get("rfi_id") != str(rfi_id) or run.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
        steps = (
            await session.execute(select(func.count()).select_from(AgentStep).where(AgentStep.run_id == run.id))
        ).scalar_one()
        session.add(
            AgentStep(
                run_id=run.id,
                step_idx=int(steps) + 1,
                role="override",
                content={"reason": reason, "rfi_id": str(rfi_id)},
            )
        )
    await record_ai_feedback(
        session,
        user_id=user_id,
        surface="site_rfi_check",
        correct=False,
        project_id=rfi.project_id,
        ref=str(proposal_id or rfi_id),
        note=f"sent anyway: {reason}"[:1000],
    )
    return {"recorded": True, "rfi_id": str(rfi_id)}


# ── 4. Meeting actions ────────────────────────────────────────────────────


async def project_owner_names(
    session: AsyncSession, project_id: uuid.UUID, attendees: list[Any]
) -> dict[str, str | None]:
    """Allowed action owners: the project roster plus the meeting's own attendees. name(lower) -> user id."""
    from app.modules.teams.models import RosterMember

    owners: dict[str, str | None] = {}
    rows = (
        await session.execute(
            select(RosterMember.display_name, RosterMember.user_id).where(RosterMember.project_id == project_id)
        )
    ).all()
    for name, uid in rows:
        if name and name.strip():
            owners[name.strip()] = str(uid) if uid else None
    for att in attendees or []:
        if isinstance(att, dict) and str(att.get("name") or "").strip():
            owners.setdefault(str(att["name"]).strip(), str(att["user_id"]) if att.get("user_id") else None)
    return owners


def match_owner(candidate: str | None, owners: dict[str, str | None]) -> tuple[str | None, str | None]:
    """Case-insensitive exact, then unique surname/first-name token match. Returns (name, user_id)."""
    cand = (candidate or "").strip().lower()
    if not cand or cand in ("tbd", "unknown", "n/a"):
        return None, None
    for name, uid in owners.items():
        if name.lower() == cand:
            return name, uid
    hits = [n for n in owners if cand in n.lower().split() or n.lower() in cand.split()]
    if len(hits) == 1:
        return hits[0], owners[hits[0]]
    return None, None


def _span(minutes: str, quote: str) -> dict[str, int] | None:
    if not quote:
        return None
    idx = minutes.find(quote.strip()[:200])
    return {"start": idx, "end": idx + len(quote.strip()[:200])} if idx >= 0 else None


def heuristic_actions(minutes: str, owners: dict[str, str | None]) -> list[dict[str, Any]]:
    from app.modules.meetings.router import _coerce_iso_due_date, _extract_meeting_data_heuristic

    segments: list[dict[str, str]] = []
    for line in minutes.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([^:\n]{2,40}):\s+(.+)$", line)
        segments.append({"speaker": m.group(1).strip(), "text": m.group(2)} if m else {"speaker": "", "text": line})
    extracted = _extract_meeting_data_heuristic(segments, "minutes", minutes)
    out: list[dict[str, Any]] = []
    for raw in extracted.get("action_items", [])[:MAX_ACTIONS]:
        text = str(raw.get("description") or "").strip()
        if not text:
            continue
        owner_name, owner_id = match_owner(raw.get("owner_name"), owners)
        out.append(
            {
                "id": f"a{len(out)}",
                "text": text,
                "owner_name": owner_name,
                "owner_id": owner_id,
                "due": _coerce_iso_due_date(raw.get("due_date")),
                "confidence": HEURISTIC_CONFIDENCE,
                "source_span": _span(minutes, text),
            }
        )
    return out


async def run_meeting_actions(
    session: AsyncSession,
    *,
    meeting_id: uuid.UUID,
    project_id: uuid.UUID | None,
    user_id: uuid.UUID,
    locale: str = "en",
) -> dict[str, Any]:
    from app.modules.meetings.models import Meeting
    from app.modules.meetings.router import _coerce_iso_due_date

    meeting = await session.get(Meeting, meeting_id)
    if meeting is None or (project_id is not None and meeting.project_id != project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    minutes = meeting.minutes or ""
    await validate_request(
        {"project_id": str(meeting.project_id), "record_project_id": str(meeting.project_id), "minutes": minutes},
        locale=locale,
    )
    await enforce_rate_limit(session, user_id)
    owners = await project_owner_names(session, meeting.project_id, meeting.attendees)

    items: list[dict[str, Any]] = []
    used, tokens = None, 0
    bridge = await resolve_llm(session, user_id)
    if bridge is not None:
        data, tokens = await ask_json(
            bridge,
            "Extract action items from construction meeting minutes. An action has a task, an owner and a due date. "
            "Use only owners from the allowed list (exact spelling) or null. due is YYYY-MM-DD or null. "
            "quote is the minutes sentence the action comes from, copied verbatim. "
            'Reply with JSON only: {"actions":[{"text":str,"owner":str|null,"due":str|null,'
            '"confidence":0..1,"quote":str}]}. Keep the language of the minutes.',
            {
                "minutes": minutes[: PROMPT_CAP_CHARS - 4000],
                "allowed_owners": list(owners),
                "today": _now().date().isoformat(),
            },
        )
        for raw in ((data or {}).get("actions") or [])[:MAX_ACTIONS]:
            if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
                continue
            owner_name, owner_id = match_owner(raw.get("owner"), owners)
            items.append(
                {
                    "id": f"a{len(items)}",
                    "text": str(raw["text"]).strip()[:1000],
                    "owner_name": owner_name,
                    "owner_id": owner_id,
                    "due": _coerce_iso_due_date(raw.get("due")),
                    "confidence": _clamp(raw.get("confidence")),
                    "source_span": _span(minutes, str(raw.get("quote") or "")),
                }
            )
        if data is not None:
            used = provider_name(bridge)
    if used is None:
        items = heuristic_actions(minutes, owners)
    envelope = {
        "kind": AGENT_MEETING,
        "meeting_id": str(meeting_id),
        "provider_used": used,
        "degraded": used is None,
        "items": items,
        "confidence": _mean([i["confidence"] for i in items]),
        "allowed_owners": sorted(owners),
    }
    return await _save_run(
        session,
        agent=AGENT_MEETING,
        project_id=meeting.project_id,
        user_id=user_id,
        user_input=str(meeting_id),
        envelope=envelope,
        tokens=tokens,
    )


# ── Confirm / reject ──────────────────────────────────────────────────────

CONFIRM_PERMISSION = {AGENT_DIARY: "daily_diary.create", AGENT_MEETING: "meetings.update"}
_EDITABLE = {
    AGENT_DIARY: {"activity", "trade", "crew_count", "weather_notes", "time", "title"},
    AGENT_MEETING: {"text", "owner_name", "owner_id", "due"},
}


def _merge_edits(kind: str, item: dict[str, Any], edits: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    merged = dict(item)
    changed = False
    for key, value in (edits or {}).items():
        if key in _EDITABLE.get(kind, set()) and merged.get(key) != value:
            merged[key] = value
            changed = True
    return merged, changed


async def _write_diary_item(
    session: AsyncSession, envelope: dict, item: dict, project_id: uuid.UUID, user_id: uuid.UUID, run_id: str
) -> str:
    from app.modules.daily_diary.schemas import DailyDiaryCreate, DiaryEntryCreate
    from app.modules.daily_diary.service import DailyDiaryService

    service = DailyDiaryService(session)
    diary_date = envelope["diary_date"]
    diary = await service.diary_repo.get_by_date_and_project(project_id, diary_date)
    if diary is None:
        diary = await service.create_diary(
            DailyDiaryCreate(project_id=project_id, diary_date=diary_date, site_supervisor_id=user_id),
            user_id=str(user_id),
        )
    hhmm = item.get("time") or "08:00"
    entry_time = datetime.fromisoformat(f"{diary_date}T{hhmm}:00+00:00")
    activity = str(item.get("title") or item.get("activity") or "").strip()
    details = [
        f"{label}: {val}"
        for label, val in (
            ("trade", item.get("trade")),
            ("crew", item.get("crew_count")),
            ("weather", item.get("weather_notes")),
        )
        if val not in (None, "")
    ]
    entry = await service.create_entry(
        DiaryEntryCreate(
            diary_id=diary.id,
            entry_type="general",
            entry_time=entry_time,
            title=activity[:500],
            description="\n".join(details) or None,
            source_module="ai_agents",
            author_id=user_id,
            metadata={
                "ai_proposed": True,
                "ai_run_id": run_id,
                "confidence": item.get("confidence"),
                "trade": item.get("trade"),
                "crew_count": item.get("crew_count"),
                "weather_notes": item.get("weather_notes"),
            },
        )
    )
    return str(entry.id)


async def _write_meeting_item(
    session: AsyncSession, envelope: dict, item: dict, user_id: uuid.UUID, run_id: str
) -> str:
    from app.modules.meetings.models import Meeting
    from app.modules.meetings.schemas import ActionRegisterItemCreate
    from app.modules.meetings.service import MeetingService

    meeting = await session.get(Meeting, uuid.UUID(envelope["meeting_id"]))
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    created = await MeetingService(session).add_action(
        meeting,
        ActionRegisterItemCreate(
            description=str(item.get("text") or ""),
            owner_id=item.get("owner_id"),
            owner_name=item.get("owner_name"),
            due_date=item.get("due"),
        ),
        user_id=str(user_id),
    )
    return str(created.get("id") or "")


async def confirm_proposal(
    session: AsyncSession,
    *,
    proposal_id: uuid.UUID,
    user_id: uuid.UUID,
    selections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write the selected (and possibly edited) items through the target module's own service."""
    run, envelope = await load_proposal(session, proposal_id)
    if run.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    kind = envelope.get("kind")
    if kind not in CONFIRM_PERMISSION:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This result has nothing to confirm")
    if envelope.get("status") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal already decided")
    project_id = run.project_id
    by_id = {i["id"]: i for i in envelope.get("items", [])}
    chosen = {s["id"]: s.get("edits") for s in selections if s.get("id") in by_id}
    results: list[dict[str, Any]] = []
    for item_id, item in by_id.items():
        if item_id not in chosen:
            item["status"] = "rejected"
            await record_ai_feedback(
                session,
                user_id=user_id,
                surface=f"site_{kind}",
                correct=False,
                project_id=project_id,
                ref=f"{run.id}:{item_id}",
                note="rejected",
            )
            continue
        merged, edited = _merge_edits(kind, item, chosen[item_id])
        try:
            async with session.begin_nested():
                if kind == AGENT_DIARY:
                    record_id = await _write_diary_item(session, envelope, merged, project_id, user_id, str(run.id))
                else:
                    record_id = await _write_meeting_item(session, envelope, merged, user_id, str(run.id))
        except HTTPException as exc:
            item["status"] = "error"
            results.append({"id": item_id, "status": "error", "detail": exc.detail})
            continue
        item.update({k: merged[k] for k in _EDITABLE[kind] if k in merged})
        item["status"] = "accepted"
        item["record_id"] = record_id
        results.append({"id": item_id, "status": "accepted", "edited": edited, "record_id": record_id})
        await record_ai_feedback(
            session,
            user_id=user_id,
            surface=f"site_{kind}",
            correct=True,
            project_id=project_id,
            ref=f"{run.id}:{item_id}",
            note="edited" if edited else None,
        )
    accepted = [r for r in results if r["status"] == "accepted"]
    errors = [r for r in results if r["status"] == "error"]
    if not errors:
        envelope["status"] = "confirmed"
    else:
        for item in by_id.values():
            if item.get("status") == "error":
                item.pop("status")
    _store_envelope(run, envelope)
    if not errors:
        await event_bus.publish(
            "ai_agents.proposal.confirmed",
            {"proposal_id": str(run.id), "kind": kind, "project_id": str(project_id), "accepted": len(accepted)},
            source_module="ai_agents",
        )
    return {"proposal_id": str(run.id), "status": envelope["status"], "results": results}


async def reject_proposal(
    session: AsyncSession, *, proposal_id: uuid.UUID, user_id: uuid.UUID, reason: str | None
) -> dict[str, Any]:
    run, envelope = await load_proposal(session, proposal_id)
    if run.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    if envelope.get("status") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal already decided")
    envelope["status"] = "rejected"
    for item in envelope.get("items", []):
        item["status"] = "rejected"
    _store_envelope(run, envelope)
    await record_ai_feedback(
        session,
        user_id=user_id,
        surface=f"site_{envelope.get('kind')}",
        correct=False,
        project_id=run.project_id,
        ref=str(run.id),
        note=(reason or "rejected")[:500],
    )
    await event_bus.publish(
        "ai_agents.proposal.rejected",
        {"proposal_id": str(run.id), "kind": envelope.get("kind"), "project_id": str(run.project_id)},
        source_module="ai_agents",
    )
    return {"proposal_id": str(run.id), "status": "rejected", "results": []}


def public_view(envelope: dict[str, Any]) -> dict[str, Any]:
    """The API shape: the stored envelope as is (it holds no secrets, GPS or raw prompts)."""
    return envelope
