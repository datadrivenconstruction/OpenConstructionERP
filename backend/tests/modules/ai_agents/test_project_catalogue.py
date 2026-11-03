# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project agent catalogue: drafting logic, run guards, audit, review, validation rule."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.ai_agents import catalogue_service as cs
from app.modules.ai_agents.base import FunctionTool, global_tool_registry
from app.modules.ai_agents.catalogue import (
    CATALOGUE,
    TOOL_DAY,
    TOOL_SEARCH,
    TOOL_SUBMITTAL,
    hit_to_json,
    hits_from_json,
    register_catalogue,
)
from app.modules.ai_agents.catalogue_logic import (
    DEFAULT_CLAUSE_CHECKLIST,
    check_submittal,
    compose_daily_report,
    draft_rfi,
    review_clauses,
)
from app.modules.ai_agents.models import AgentDraft, AgentRun, AgentStep, ProjectAgentGuard, ProjectAgentSetting
from app.modules.ai_agents.validators import DraftReviewOverdue
from app.modules.doc_assistant.core import BM25Index
from app.modules.doc_assistant.evaluation import load_corpus


@pytest.fixture(scope="module")
def index() -> BM25Index:
    passages, _ = load_corpus()
    return BM25Index(passages)


def _contract_hits(index: BM25Index) -> dict[str, list]:
    out = {}
    for item in DEFAULT_CLAUSE_CHECKLIST:
        hits = [h for h in index.search(item["label"], k=6) if h.passage.source_kind == "contract"]
        out[item["key"]] = hits
    return out


# ── Drafting logic ──────────────────────────────────────────────────────────


def test_clause_review_flags_risk_and_cites(index) -> None:
    out = review_clauses(_contract_hits(index))
    by_key = {f["key"]: f for f in out["findings"]}
    assert by_key["liquidated_damages"]["status"] == "ok"  # capped at 10 percent
    assert by_key["indemnity"]["status"] == "flagged" and "risk_wording" in by_key["indemnity"]["reasons"]
    assert by_key["retention"]["status"] == "ok"  # 5 percent, half released at completion
    assert by_key["payment_terms"]["status"] == "ok"  # 30 days
    assert by_key["termination"]["status"] == "missing" and by_key["termination"]["citations"] == []
    cited = by_key["indemnity"]["citations"][0]
    assert cited["source_id"] == "doc-contract" and cited["page"] == 2


def test_clause_checklist_is_configurable(index) -> None:
    checklist = [dict(i) for i in DEFAULT_CLAUSE_CHECKLIST]
    for item in checklist:
        if item["key"] == "payment_terms":
            item["max_payment_days"] = 14
        if item["key"] == "retention":
            item["max_retention_percent"] = 3
        if item["key"] == "termination":
            item["enabled"] = False
    by_key = {f["key"]: f for f in review_clauses(_contract_hits(index), checklist)["findings"]}
    assert "payment_period_exceeds_limit" in by_key["payment_terms"]["reasons"]
    assert "retention_exceeds_limit" in by_key["retention"]["reasons"]
    assert "termination" not in by_key


def test_uncapped_liquidated_damages_are_high_risk() -> None:
    from app.modules.doc_assistant.core import Hit, Passage

    p = Passage("x", "contract", "c", "C", "Liquidated damages of 5000 EUR per day apply.")
    out = review_clauses({"liquidated_damages": [Hit(p, 1.0, 1.0)]})
    ld = next(f for f in out["findings"] if f["key"] == "liquidated_damages")
    assert ld["risk"] == "high" and "no_cap" in ld["reasons"]


def test_submittal_check_lists_requirements_with_citations(index) -> None:
    hits = [h for h in index.search("03 30 00 curing compound", k=6) if h.passage.source_kind == "specification"]
    sub = {
        "title": "Curing compound product data",
        "spec_section": "03 30 00",
        "manufacturer": "Acme",
        "text": "membrane forming curing compound for exposed concrete surfaces, minimum 7 days",
    }
    out = check_submittal(sub, hits)
    assert out["requirements"] and all(r["citation"]["source_id"] == "doc-spec-03" for r in out["requirements"])
    assert out["addressed"] >= 1 and out["recommendation"] == "request_missing_information"
    assert 0 < out["confidence"] <= 1
    assert check_submittal(sub, [])["recommendation"] == "spec_section_not_found"


def test_daily_report_counts_inputs_and_keeps_sources() -> None:
    out = compose_daily_report(
        "2026-11-02",
        {
            "timesheets": [{"id": "t1", "resource": "r1", "hours": 8}, {"id": "t2", "resource": "r2", "hours": 7.5}],
            "weather": [{"id": "w1", "conditions": "Rain", "temperature_c": 6}],
            "deliveries": [{"id": "d1", "title": "Rebar 12 t"}],
        },
    )
    assert out["labour"] == {"workers": 2, "hours": 15.5}
    assert out["inputs_missing"] == ["photos", "voice_notes"] and out["confidence"] == 0.6
    assert {s["id"] for s in out["sources"]} == {"t1", "t2", "w1", "d1"}


def test_rfi_draft_references_sheets_only_above_the_gate(index) -> None:
    good = draft_rfi(
        "Which stair core wall thickness governs on level 1?", index.search("stair core walls level 1", k=5)
    )
    assert "A-201" in good["referenced_sheets"] and good["references"]
    weak = draft_rfi("Which elevator speed?", index.search("elevator speed", k=5))
    assert weak["references"] == [] and weak["confidence"] <= 0.3


def test_hits_round_trip_through_tool_json(index) -> None:
    hits = index.search("parapet upstand", k=2)
    back = hits_from_json([hit_to_json(h) for h in hits])
    assert [(h.passage.source_id, h.passage.page, h.passage.sheet_number) for h in back] == [
        (h.passage.source_id, h.passage.page, h.passage.sheet_number) for h in hits
    ]


def test_every_catalogue_agent_uses_only_read_only_registered_tools() -> None:
    register_catalogue()
    for spec in CATALOGUE.values():
        assert spec.tools and all(global_tool_registry.get(t) for t in spec.tools)
        assert spec.to_dict()["read_only_tools"] is True


# ── Service: guards, audit, review (fake session, fake tools) ──────────────


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, cls, key):
        return next((o for o in self.added if isinstance(o, cls) and o.id == key), None)


@pytest.fixture
def service(monkeypatch, index):
    register_catalogue()
    session = FakeSession()
    project_id = uuid.uuid4()
    state: dict[str, Any] = {"settings": {}, "guard": None, "contexts": []}

    async def settings(self, pid):
        return state["settings"]

    async def guard(self, pid):
        return state["guard"]

    monkeypatch.setattr(cs.CatalogueService, "settings", settings)
    monkeypatch.setattr(cs.CatalogueService, "guard", guard)

    async def fake_search(q, kinds=None, document_id=None, k=6, __agent_context__=None):
        state["contexts"].append(__agent_context__)
        hits = [h for h in index.search(q, k=12) if not kinds or h.passage.source_kind in kinds][:k]
        return {"hits": [hit_to_json(h) for h in hits]}

    async def fake_day(date, __agent_context__=None):
        return {"records": {"timesheets": [{"id": "t", "resource": "r", "hours": 8}]}}

    async def fake_sub(submittal_id, __agent_context__=None):
        return {
            "id": submittal_id,
            "number": "SUB-7",
            "title": "Curing compound",
            "spec_section": "03 30 00",
            "text": "",
        }

    originals = {n: global_tool_registry.get(n) for n in (TOOL_SEARCH, TOOL_DAY, TOOL_SUBMITTAL)}
    for name, fn in ((TOOL_SEARCH, fake_search), (TOOL_DAY, fake_day), (TOOL_SUBMITTAL, fake_sub)):
        global_tool_registry.register(FunctionTool(name, "fake", {"type": "object"}, fn))
    yield cs.CatalogueService(session), session, project_id, state  # type: ignore[arg-type]
    for tool in originals.values():
        if tool is not None:
            global_tool_registry.register(tool)


def _enable(state, name: str, **config) -> None:
    state["settings"][name] = ProjectAgentSetting(agent_name=name, enabled=True, config=config, max_tokens_per_run=4000)


async def test_disabled_agent_and_kill_switch_refuse_to_run(service) -> None:
    svc, _, pid, state = service
    with pytest.raises(cs.CatalogueError) as exc:
        await svc.run(
            project_id=pid,
            agent_name="daily_reporter",
            inputs={"date": "2026-11-02"},
            user_id=uuid.uuid4(),
            role="editor",
        )
    assert exc.value.code == "disabled"
    _enable(state, "daily_reporter")
    state["guard"] = ProjectAgentGuard(halted=True, reason="audit")
    with pytest.raises(cs.CatalogueError) as exc:
        await svc.run(
            project_id=pid,
            agent_name="daily_reporter",
            inputs={"date": "2026-11-02"},
            user_id=uuid.uuid4(),
            role="editor",
        )
    assert exc.value.code == "halted"


async def test_missing_inputs_are_refused(service) -> None:
    svc, _, pid, state = service
    _enable(state, "submittal_checker")
    with pytest.raises(cs.CatalogueError) as exc:
        await svc.run(project_id=pid, agent_name="submittal_checker", inputs={}, user_id=uuid.uuid4(), role="editor")
    assert exc.value.code == "missing_inputs"


async def test_run_records_audit_steps_and_a_pending_draft(service) -> None:
    svc, session, pid, state = service
    _enable(state, "clause_reviewer")
    user = uuid.uuid4()
    run, draft = await svc.run(
        project_id=pid, agent_name="clause_reviewer", inputs={}, user_id=user, role="viewer", use_ai=False
    )
    assert run.status == "completed" and run.trigger_source == "catalogue"
    assert draft is not None and draft.status == "pending" and draft.run_id == run.id
    assert draft.sources and all("text" not in s for s in draft.sources)
    steps = [o for o in session.added if isinstance(o, AgentStep)]
    assert [s.role for s in steps].count("tool_call") == len(DEFAULT_CLAUSE_CHECKLIST)
    assert steps[-1].role == "answer"
    assert all(c == {"user_id": str(user), "project_id": str(pid), "role": "viewer"} for c in state["contexts"])


async def test_token_limit_and_narrative_come_from_the_runner(service) -> None:
    svc, _, pid, state = service
    _enable(state, "daily_reporter")

    class Bridge:
        async def next_step(self, *, system_prompt, messages, tools):
            return {"type": "final", "text": "Two workers, 8 hours."}, 9000

    _, draft = await svc.run(
        project_id=pid,
        agent_name="daily_reporter",
        inputs={"date": "2026-11-02"},
        user_id=uuid.uuid4(),
        role="editor",
        llm=Bridge(),
    )
    assert "narrative" not in draft.payload and draft.payload["narrative_skipped"] == "token_limit"

    class Small(Bridge):
        async def next_step(self, *, system_prompt, messages, tools):
            return {"type": "final", "text": "Two workers, 8 hours."}, 50

    run, draft = await svc.run(
        project_id=pid,
        agent_name="daily_reporter",
        inputs={"date": "2026-11-02"},
        user_id=uuid.uuid4(),
        role="editor",
        llm=Small(),
    )
    assert draft.payload["narrative"] == "Two workers, 8 hours." and run.total_tokens == 50


async def test_review_is_a_one_time_human_decision(service, monkeypatch) -> None:
    svc, _, pid, state = service
    _enable(state, "rfi_drafter")
    _, draft = await svc.run(
        project_id=pid,
        agent_name="rfi_drafter",
        inputs={"question": "Which stair core wall thickness governs on level 1?"},
        user_id=uuid.uuid4(),
        role="editor",
        use_ai=False,
    )
    created: list[str] = []

    async def fake_apply(self, d, user_id):
        created.append(str(d.id))
        return "rfi-1"

    monkeypatch.setattr(cs.CatalogueService, "_apply_rfi", fake_apply)
    reviewer = uuid.uuid4()
    out = await svc.review(draft.id, project_id=pid, decision="accepted", user_id=reviewer, apply=True)
    assert out.status == "accepted" and out.applied_record_id == "rfi-1" and out.reviewed_by == reviewer
    with pytest.raises(cs.CatalogueError) as exc:
        await svc.review(draft.id, project_id=pid, decision="rejected", user_id=reviewer)
    assert exc.value.code == "already_reviewed"
    with pytest.raises(cs.CatalogueError):
        await svc.review(draft.id, project_id=uuid.uuid4(), decision="accepted", user_id=reviewer)


def test_models_are_distinct_tables() -> None:
    names = {m.__tablename__ for m in (AgentDraft, AgentRun, ProjectAgentGuard, ProjectAgentSetting)}
    assert len(names) == 4


# ── Validation rule ─────────────────────────────────────────────────────────


async def test_unreviewed_draft_after_n_days_is_info() -> None:
    from app.core.validation.engine import Severity, ValidationContext

    now = datetime(2026, 11, 3, tzinfo=UTC)
    drafts = [
        {"id": "a", "status": "pending", "title": "Old", "created_at": (now - timedelta(days=9)).isoformat()},
        {"id": "b", "status": "pending", "title": "New", "created_at": (now - timedelta(days=1)).isoformat()},
        {"id": "c", "status": "accepted", "title": "Done", "created_at": (now - timedelta(days=30)).isoformat()},
        {
            "id": "d",
            "status": "pending",
            "title": "Short",
            "created_at": (now - timedelta(days=2)).isoformat(),
            "review_after_days": 2,
        },
    ]
    res = await DraftReviewOverdue().validate(
        ValidationContext(data={"drafts": drafts, "as_of": now.isoformat()}, metadata={"locale": "ru"})
    )
    failed = {r.element_ref for r in res if not r.passed}
    assert failed == {"a", "d"}
    assert all(r.severity == Severity.INFO for r in res)
    assert "Черновик" in next(r.message for r in res if r.element_ref == "a")
