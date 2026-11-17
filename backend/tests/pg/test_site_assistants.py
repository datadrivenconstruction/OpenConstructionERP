# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site assistants on PostgreSQL: scope, degraded path, scripted LLM path, confirm writes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.ai_agents import site
from app.modules.ai_agents.llm import ScriptedLLM
from app.modules.ai_agents.models import AgentRun, AIFeedback
from tests.pg.governance_fixtures import add_project, add_user

pytestmark = pytest.mark.asyncio


def _llm(payload: Any) -> ScriptedLLM:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return ScriptedLLM([{"type": "final", "text": text}])


class RecordingLLM(ScriptedLLM):
    def __init__(self, payload: Any) -> None:
        super().__init__([{"type": "final", "text": json.dumps(payload)}])
        self.prompts: list[str] = []

    async def next_step(self, *, system_prompt, messages, tools):  # type: ignore[no-untyped-def]
        self.prompts.append(system_prompt + json.dumps(messages))
        return await super().next_step(system_prompt=system_prompt, messages=messages, tools=tools)


@pytest.fixture
def with_llm(monkeypatch):
    def _set(bridge: Any) -> None:
        async def _resolve(session, user_id):  # noqa: ARG001
            return bridge

        monkeypatch.setattr(site, "resolve_llm", _resolve)

    _set(None)
    return _set


async def _world(session) -> tuple[uuid.UUID, uuid.UUID]:
    user = await add_user(session, "editor")
    project = await add_project(session, user, [user])
    return user, project


async def _rfi(session, project, user, **kw):
    from app.modules.rfi.models import RFI

    row = RFI(
        project_id=project,
        rfi_number=kw.pop("rfi_number", "RFI-001"),
        subject=kw.pop("subject", "Slab edge"),
        question=kw.pop("question", "Please confirm the slab edge detail."),
        raised_by=user,
        status=kw.pop("status", "draft"),
        metadata_={},
        **kw,
    )
    session.add(row)
    await session.flush()
    return row


async def _meeting(session, project, minutes, attendees=None):
    from app.modules.meetings.models import Meeting

    row = Meeting(
        project_id=project,
        meeting_number="M-001",
        meeting_type="progress",
        title="Weekly",
        meeting_date="2026-11-16",
        attendees=attendees or [],
        agenda_items=[],
        action_items=[],
        minutes=minutes,
        status="draft",
        metadata_={},
    )
    session.add(row)
    await session.flush()
    return row


async def _roster(session, project, *names):
    from app.modules.teams.models import RosterMember

    for n in names:
        session.add(RosterMember(project_id=project, display_name=n))
    await session.flush()


# ── Briefing ──────────────────────────────────────────────────────────────


async def test_briefing_sees_only_its_own_project(pg_session, with_llm) -> None:
    user, a = await _world(pg_session)
    b = await add_project(pg_session, user, [user])
    past = (datetime.now(UTC) - timedelta(days=3)).date().isoformat()
    await _rfi(pg_session, a, user, rfi_number="RFI-A1", status="open", response_due_date=past)
    await _rfi(pg_session, b, user, rfi_number="RFI-B1", status="open", response_due_date=past)

    out = await site.run_briefing(pg_session, project_id=a, user_id=user)
    blob = json.dumps(out["items"])
    assert "RFI-A1" in blob and "RFI-B1" not in blob
    assert {i["id"] for i in out["items"]} == {"rfis_overdue"}


async def test_briefing_without_provider_is_facts_only(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    await _rfi(pg_session, project, user, status="open")
    out = await site.run_briefing(pg_session, project_id=project, user_id=user)
    assert out["provider_used"] is None and out["degraded"] is True
    assert out["narrative"] is None and out["items"]


async def test_briefing_with_provider_adds_narrative_and_once_per_day(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    await _rfi(pg_session, project, user, status="open")
    with_llm(_llm("Two things need you today."))
    first = await site.run_briefing(pg_session, project_id=project, user_id=user)
    assert first["narrative"] == "Two things need you today." and first["degraded"] is False
    again = await site.run_briefing(pg_session, project_id=project, user_id=user)
    assert again["proposal_id"] == first["proposal_id"]
    fresh = await site.run_briefing(pg_session, project_id=project, user_id=user, refresh=True)
    assert fresh["proposal_id"] != first["proposal_id"]


async def test_weather_only_when_location_is_configured(pg_session, with_llm, monkeypatch) -> None:
    from app.modules.daily_diary import weather
    from app.modules.projects.models import Project

    async def _fake(lat, lng, target):  # noqa: ARG001
        return {"conditions_text": "Clear", "temperature_c": 7.4, "wind_speed_kmh": 12, "precipitation_mm": 0}

    monkeypatch.setattr(weather, "fetch_weather_for_day", _fake)
    user, project = await _world(pg_session)
    first = await site.run_briefing(pg_session, project_id=project, user_id=user)
    assert not [i for i in first["items"] if i["id"] == "weather"]
    row = await pg_session.get(Project, project)
    row.address = {"lat": 48.1, "lng": 11.5}
    await pg_session.flush()
    out = await site.run_briefing(pg_session, project_id=project, user_id=user, refresh=True)
    assert [i for i in out["items"] if i["id"] == "weather"][0]["entries"][0]["conditions"] == "Clear"


async def test_rate_limit_is_twenty_runs_per_hour(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    for _ in range(site.RATE_LIMIT_PER_HOUR):
        pg_session.add(
            AgentRun(
                agent_name=site.AGENT_RFI,
                project_id=project,
                user_id=user,
                status="completed",
                started_at=site._iso(site._now()),
            )
        )
    await pg_session.flush()
    with pytest.raises(HTTPException) as err:
        await site.run_briefing(pg_session, project_id=project, user_id=user, refresh=True)
    assert err.value.status_code == 429


# ── Diary draft ───────────────────────────────────────────────────────────


async def _photo(session, project, taken, caption, lat=None, lng=None):
    from app.modules.daily_diary.models import DiaryPhoto

    session.add(
        DiaryPhoto(
            project_id=project,
            taken_at=taken,
            file_url="x.jpg",
            description=caption,
            lat=lat,
            lng=lng,
            tags=[],
            metadata_={},
        )
    )
    await session.flush()


async def test_diary_draft_template_then_confirm_writes_only_on_confirm(pg_session, with_llm) -> None:
    from app.modules.daily_diary.models import DailyDiary, DiaryEntry

    user, project = await _world(pg_session)
    day = datetime.now(UTC).date().isoformat()
    base = datetime.fromisoformat(f"{day}T08:00:00+00:00")
    await _photo(pg_session, project, base, "Rebar on level 2")
    await _photo(pg_session, project, base + timedelta(minutes=20), "Rebar on level 2 slab")
    await _photo(pg_session, project, base + timedelta(hours=4), "Formwork stripping")

    out = await site.run_diary_draft(
        pg_session, project_id=project, user_id=user, diary_date=day, transcripts=["Crew of eight on formwork"]
    )
    assert out["degraded"] is True and out["provider_used"] is None
    kinds = [(i["source"], i["photo_count"]) for i in out["items"]]
    assert kinds == [("photos", 2), ("photos", 1), ("transcript", 0)]
    assert out["items"][2]["raw"] == "Crew of eight on formwork"
    assert (await pg_session.execute(select(func.count()).select_from(DiaryEntry))).scalar_one() == 0
    assert (await pg_session.execute(select(func.count()).select_from(DailyDiary))).scalar_one() == 0

    res = await site.confirm_proposal(
        pg_session,
        proposal_id=uuid.UUID(out["proposal_id"]),
        user_id=user,
        selections=[
            {"id": "c0", "edits": {"activity": "Rebar fixing, level 2", "trade": "steelfixer", "crew_count": 6}}
        ],
    )
    assert [r["status"] for r in res["results"]] == ["accepted"]
    entries = (await pg_session.execute(select(DiaryEntry))).scalars().all()
    assert len(entries) == 1 and entries[0].title == "Rebar fixing, level 2"
    assert entries[0].metadata_["ai_proposed"] is True and entries[0].metadata_["crew_count"] == 6
    verdicts = (await pg_session.execute(select(AIFeedback.correct).order_by(AIFeedback.correct))).scalars().all()
    assert verdicts == [False, False, True]
    with pytest.raises(HTTPException) as again:
        await site.confirm_proposal(pg_session, proposal_id=uuid.UUID(out["proposal_id"]), user_id=user, selections=[])
    assert again.value.status_code == 409


async def test_diary_prompt_has_no_gps_and_llm_entries_are_used(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    day = datetime.now(UTC).date().isoformat()
    t = datetime.fromisoformat(f"{day}T09:00:00+00:00")
    await _photo(pg_session, project, t, "Crane pick at 48.137154, 11.576124 north side", lat=48.137154, lng=11.576124)
    bridge = RecordingLLM(
        {
            "entries": [
                {
                    "activity": "Crane pick",
                    "trade": "crane",
                    "crew_count": 4,
                    "confidence": 0.8,
                    "time": "09:00",
                    "sources": ["c0"],
                }
            ]
        }
    )
    with_llm(bridge)
    out = await site.run_diary_draft(
        pg_session, project_id=project, user_id=user, diary_date=day, transcripts=["at 48.137154, 11.576124 we lifted"]
    )
    assert out["degraded"] is False and out["items"][0]["activity"] == "Crane pick"
    prompt = bridge.prompts[0]
    assert "48.137" not in prompt and "11.576" not in prompt and "[removed]" in prompt


async def test_diary_date_in_future_is_refused(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    future = (datetime.now(UTC) + timedelta(days=5)).date().isoformat()
    with pytest.raises(HTTPException) as err:
        await site.run_diary_draft(pg_session, project_id=project, user_id=user, diary_date=future, transcripts=[])
    assert err.value.status_code == 422
    assert err.value.detail["rule_id"] == "ai_site_assistants.diary_date_not_future"


# ── RFI completeness ──────────────────────────────────────────────────────


async def test_rfi_check_rules_fail_and_ok(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    bad = await _rfi(pg_session, project, user, question="Fix it", discipline=None)
    out = await site.run_rfi_check(pg_session, rfi_id=bad.id, project_id=project, user_id=user)
    by_id = {c["id"]: c["status"] for c in out["checks"]}
    assert by_id["question"] == "fail" and by_id["discipline"] == "fail" and by_id["due_date"] == "fail"
    assert out["has_fail"] is True and out["score"] < 50 and out["degraded"] is True

    due = (datetime.now(UTC) + timedelta(days=14)).date().isoformat()
    good = await _rfi(
        pg_session,
        project,
        user,
        rfi_number="RFI-002",
        discipline="structural",
        response_due_date=due,
        question="Please confirm the slab edge detail on drawing S-201 level 2 is 250 mm and not 200 mm.",
        cost_impact=True,
        linked_drawing_ids=["d1"],
    )
    ok = await site.run_rfi_check(pg_session, rfi_id=good.id, project_id=project, user_id=user)
    assert {c["status"] for c in ok["checks"]} == {"ok"} and ok["score"] == 100


async def test_rfi_check_adds_ai_ambiguity_advice(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    rfi = await _rfi(pg_session, project, user)
    with_llm(_llm({"advice": [{"issue": "Which slab?", "suggestion": "Name the level", "confidence": 0.7}]}))
    out = await site.run_rfi_check(pg_session, rfi_id=rfi.id, project_id=project, user_id=user)
    ai = [c for c in out["checks"] if c["source"] == "ai"]
    assert out["degraded"] is False and ai and ai[0]["params"]["issue"] == "Which slab?"


async def test_rfi_check_needs_a_draft_in_the_project(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    other = await add_project(pg_session, user, [user])
    sent = await _rfi(pg_session, project, user, status="open")
    with pytest.raises(HTTPException) as err:
        await site.run_rfi_check(pg_session, rfi_id=sent.id, project_id=project, user_id=user)
    assert err.value.status_code == 422 and err.value.detail["rule_id"] == "ai_site_assistants.rfi_in_draft"
    with pytest.raises(HTTPException) as foreign:
        await site.run_rfi_check(pg_session, rfi_id=sent.id, project_id=other, user_id=user)
    assert foreign.value.status_code == 404


async def test_send_anyway_reason_is_recorded(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    rfi = await _rfi(pg_session, project, user, question="x")
    out = await site.run_rfi_check(pg_session, rfi_id=rfi.id, project_id=project, user_id=user)
    await site.record_rfi_override(
        pg_session,
        rfi_id=rfi.id,
        user_id=user,
        reason="Urgent, will clarify by phone",
        proposal_id=uuid.UUID(out["proposal_id"]),
    )
    fb = (await pg_session.execute(select(AIFeedback).where(AIFeedback.surface == "site_rfi_check"))).scalar_one()
    assert fb.correct is False and "Urgent" in (fb.note or "")


# ── Meeting actions ───────────────────────────────────────────────────────

MINUTES = (
    "Anna Keller: Please send the revised slab drawings by 2026-11-20.\n"
    "Bram Visser: I will do the crane permit follow-up by 2026-11-18.\n"
    "Everyone agreed the pour moves to Thursday.\n"
    "Zed Unknown: Needs to repaint the hoarding by 2026-11-25."
)


async def test_meeting_actions_need_fifty_characters(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    meeting = await _meeting(pg_session, project, "too short")
    with pytest.raises(HTTPException) as err:
        await site.run_meeting_actions(pg_session, meeting_id=meeting.id, project_id=project, user_id=user)
    assert err.value.detail["rule_id"] == "ai_site_assistants.minutes_min_length"


async def test_meeting_heuristic_fallback_and_roster_owners(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    await _roster(pg_session, project, "Anna Keller", "Bram Visser")
    meeting = await _meeting(pg_session, project, MINUTES)
    out = await site.run_meeting_actions(pg_session, meeting_id=meeting.id, project_id=project, user_id=user)
    assert out["degraded"] is True and out["provider_used"] is None and out["items"]
    assert {i["confidence"] for i in out["items"]} == {site.HEURISTIC_CONFIDENCE}
    owners = {i["owner_name"] for i in out["items"]}
    assert "Zed Unknown" not in owners and {"Anna Keller", "Bram Visser"} <= owners
    assert all(i["source_span"] for i in out["items"])


async def test_meeting_llm_actions_confirm_exactly_the_accepted(pg_session, with_llm) -> None:
    from app.modules.meetings.models import MeetingActionItem

    user, project = await _world(pg_session)
    await _roster(pg_session, project, "Anna Keller", "Bram Visser")
    meeting = await _meeting(pg_session, project, MINUTES)
    with_llm(
        _llm(
            {
                "actions": [
                    {
                        "text": "Send revised slab drawings",
                        "owner": "Anna Keller",
                        "due": "2026-11-20",
                        "confidence": 0.9,
                        "quote": "Please send the revised slab drawings",
                    },
                    {
                        "text": "Crane permit follow-up",
                        "owner": "Bram Visser",
                        "due": "2026-11-18",
                        "confidence": 0.8,
                        "quote": "crane permit follow-up",
                    },
                    {
                        "text": "Repaint hoarding",
                        "owner": "Zed Unknown",
                        "due": "2026-11-25",
                        "confidence": 0.5,
                        "quote": "repaint the hoarding",
                    },
                ]
            }
        )
    )
    out = await site.run_meeting_actions(pg_session, meeting_id=meeting.id, project_id=project, user_id=user)
    assert out["degraded"] is False and [i["owner_name"] for i in out["items"]] == ["Anna Keller", "Bram Visser", None]

    count = select(func.count()).select_from(MeetingActionItem)
    assert (await pg_session.execute(count)).scalar_one() == 0
    res = await site.confirm_proposal(
        pg_session,
        proposal_id=uuid.UUID(out["proposal_id"]),
        user_id=user,
        selections=[{"id": "a0"}, {"id": "a1", "edits": {"due": "2026-11-19"}}],
    )
    assert [r["status"] for r in res["results"]] == ["accepted", "accepted"]
    rows = (await pg_session.execute(select(MeetingActionItem).order_by(MeetingActionItem.due_date))).scalars().all()
    assert [(r.owner_name, r.due_date) for r in rows] == [("Bram Visser", "2026-11-19"), ("Anna Keller", "2026-11-20")]


async def test_meeting_item_failing_target_validation_is_not_written(pg_session, with_llm) -> None:
    from app.modules.meetings.models import MeetingActionItem

    user, project = await _world(pg_session)
    meeting = await _meeting(pg_session, project, MINUTES)
    out = await site.run_meeting_actions(pg_session, meeting_id=meeting.id, project_id=project, user_id=user)
    res = await site.confirm_proposal(
        pg_session, proposal_id=uuid.UUID(out["proposal_id"]), user_id=user, selections=[{"id": out["items"][0]["id"]}]
    )
    assert res["results"][0]["status"] == "error"  # empty roster: no owner, the target validator refuses
    assert (await pg_session.execute(select(func.count()).select_from(MeetingActionItem))).scalar_one() == 0


async def test_reject_writes_nothing_and_stores_verdicts(pg_session, with_llm) -> None:
    from app.modules.meetings.models import MeetingActionItem

    user, project = await _world(pg_session)
    meeting = await _meeting(pg_session, project, MINUTES)
    out = await site.run_meeting_actions(pg_session, meeting_id=meeting.id, project_id=project, user_id=user)
    res = await site.reject_proposal(pg_session, proposal_id=uuid.UUID(out["proposal_id"]), user_id=user, reason="noise")
    assert res["status"] == "rejected"
    assert (await pg_session.execute(select(func.count()).select_from(MeetingActionItem))).scalar_one() == 0
    assert (await pg_session.execute(select(AIFeedback.note))).scalar_one() == "noise"


async def test_proposal_is_private_to_its_user(pg_session, with_llm) -> None:
    user, project = await _world(pg_session)
    stranger = await add_user(pg_session, "editor")
    meeting = await _meeting(pg_session, project, MINUTES)
    out = await site.run_meeting_actions(pg_session, meeting_id=meeting.id, project_id=project, user_id=user)
    with pytest.raises(HTTPException) as err:
        await site.confirm_proposal(
            pg_session, proposal_id=uuid.UUID(out["proposal_id"]), user_id=stranger, selections=[]
        )
    assert err.value.status_code == 404
