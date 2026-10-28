"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Baseline tests for project_intelligence advisor and cross-project ACL.

Covers two correctness properties the module must hold:

1. ``generate_recommendations`` returns a structured insight derived from the
   project state and score, sourced from the LLM when one is configured. The
   LLM call must surface ``provider_intelligence.llm_call`` structured log
   records (tokens + duration + outcome) so cost is observable.

2. ``_verify_project_access`` blocks cross-project data leakage: a non-admin
   user requesting a project they do not own gets a 403, *before* any
   advisor / collector / scorer code runs. This guards every advisor entry
   point (recommendations, chat, explain-gap, actions).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

# ── Test fixtures ─────────────────────────────────────────────────────────


def _make_state() -> Any:
    """Build a minimal but realistic ProjectState for advisor input."""
    from app.modules.project_intelligence.collector import BOQState, ProjectState

    state = ProjectState()
    state.project_id = str(uuid.uuid4())
    state.project_name = "Acme Tower"
    state.project_type = "high_rise"
    state.region = "DACH"
    state.standard = "DIN276"
    state.currency = "EUR"
    state.boq = BOQState(
        exists=True,
        total_items=120,
        items_with_zero_price=8,
        items_with_zero_quantity=2,
        sections_count=14,
        completion_pct=70.0,
    )
    return state


def _make_score() -> Any:
    from app.modules.project_intelligence.scorer import CriticalGap, ProjectScore

    return ProjectScore(
        overall=58.0,
        overall_grade="D",
        domain_scores={"boq": 70.0, "schedule": 40.0},
        critical_gaps=[
            CriticalGap(
                id="boq.zero_price",
                domain="boq",
                severity="high",
                title="8 zero-price items",
                description="Some BOQ items have no rate.",
                impact="Budget is understated.",
                action_id="action_run_validation",
                affected_count=8,
            )
        ],
        achievements=[],
    )


# ── 1. generate_recommendations returns a structured LLM insight ──────────


@pytest.mark.asyncio
async def test_generate_recommendations_uses_mocked_llm(caplog) -> None:
    """LLM is mocked → advisor returns the LLM text and logs a cost record."""
    from app.modules.project_intelligence import advisor

    state = _make_state()
    score = _make_score()
    session = SimpleNamespace()  # _resolve_provider is patched, so unused

    # Force the cache to be empty for this test so the LLM is actually called.
    advisor._llm_cache.clear()

    fake_response = "1. Fill the 8 zero-price items.\n2. Validate against DIN276."

    with (
        patch.object(
            advisor,
            "_resolve_provider",
            new=AsyncMock(return_value=("anthropic", "fake-key", "claude-test")),
        ),
        patch(
            "app.modules.ai.ai_client.call_ai",
            new=AsyncMock(return_value=(fake_response, 1234)),
        ) as mock_call,
    ):
        with caplog.at_level(logging.INFO, logger="app.modules.project_intelligence.advisor"):
            text = await advisor.generate_recommendations(
                session=session,  # type: ignore[arg-type]
                state=state,
                score=score,
                role="estimator",
                language="en",
            )

    # Structured insight returned verbatim from the (mocked) LLM
    assert text == fake_response
    mock_call.assert_awaited_once()

    # Cost / outcome observability — exactly one llm_call record, ok outcome,
    # tokens echoed through, provider/model present.
    cost_records = [r for r in caplog.records if r.getMessage() == "project_intelligence.llm_call"]
    assert len(cost_records) == 1, "expected exactly one structured cost log"
    rec = cost_records[0]
    assert rec.operation == "recommendations"
    assert rec.provider == "anthropic"
    assert rec.model == "claude-test"
    assert rec.tokens == 1234
    assert rec.outcome == "ok"
    assert rec.cache_hit is False


@pytest.mark.asyncio
async def test_generate_recommendations_cache_debounces_llm() -> None:
    """Identical prompts within TTL must NOT re-hit the LLM (cost guard)."""
    from app.modules.project_intelligence import advisor

    state = _make_state()
    score = _make_score()
    session = SimpleNamespace()

    advisor._llm_cache.clear()

    with (
        patch.object(
            advisor,
            "_resolve_provider",
            new=AsyncMock(return_value=("anthropic", "fake-key", "claude-test")),
        ),
        patch(
            "app.modules.ai.ai_client.call_ai",
            new=AsyncMock(return_value=("cached body", 100)),
        ) as mock_call,
    ):
        first = await advisor.generate_recommendations(
            session=session,
            state=state,
            score=score,  # type: ignore[arg-type]
        )
        second = await advisor.generate_recommendations(
            session=session,
            state=state,
            score=score,  # type: ignore[arg-type]
        )

    assert first == second == "cached body"
    assert mock_call.await_count == 1, "second call must be served from cache"


@pytest.mark.asyncio
async def test_generate_recommendations_no_provider_falls_back() -> None:
    """No LLM configured → rule-based fallback, no LLM call attempted."""
    from app.modules.project_intelligence import advisor

    state = _make_state()
    score = _make_score()
    session = SimpleNamespace()

    with (
        patch.object(
            advisor,
            "_resolve_provider",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.modules.ai.ai_client.call_ai",
            new=AsyncMock(side_effect=AssertionError("must not be called")),
        ),
    ):
        text = await advisor.generate_recommendations(
            session=session,
            state=state,
            score=score,  # type: ignore[arg-type]
        )

    assert "Acme Tower" in text
    assert "58/100" in text  # score is rendered
    assert "8 zero-price items" in text  # gap title surfaced


# ── 2. Cross-project ACL prevents data leak ───────────────────────────────


class _StubProject:
    def __init__(self, owner_id: str) -> None:
        self.owner_id = owner_id


class _StubUser:
    def __init__(self, role: str = "user") -> None:
        self.role = role


class _StubRepo:
    """Stand-in for ProjectRepository / UserRepository."""

    def __init__(self, result: Any) -> None:
        self._result = result

    async def get_by_id(self, _id: Any) -> Any:
        return self._result


@pytest.mark.asyncio
async def test_verify_project_access_blocks_cross_project() -> None:
    """A non-admin user requesting another user's project gets 404.

    The shared ``verify_project_access`` returns 404 (not 403) on denial so the
    status code cannot be used to probe which project UUIDs exist (IDOR oracle
    defence). User IDs are real UUIDs - the helper coerces them with
    ``uuid.UUID(str(user_id))`` for the admin / team-member lookups.
    """
    from app.modules.project_intelligence import router as pi_router

    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    project_id = uuid.uuid4()

    with (
        patch(
            "app.modules.projects.repository.ProjectRepository",
            new=lambda _s: _StubRepo(_StubProject(owner_id=owner_id)),
        ),
        patch(
            "app.modules.users.repository.UserRepository",
            new=lambda _s: _StubRepo(_StubUser(role="user")),
        ),
        patch(
            "app.modules.teams.access.is_project_member",
            new=AsyncMock(return_value=False),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await pi_router._verify_project_access(
                session=SimpleNamespace(),  # type: ignore[arg-type]
                project_id=project_id,
                user_id=other_id,
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_verify_project_access_allows_owner() -> None:
    """Owner of the project is permitted (sanity check on the same path)."""
    from app.modules.project_intelligence import router as pi_router

    owner_id = str(uuid.uuid4())
    project_id = uuid.uuid4()

    with (
        patch(
            "app.modules.projects.repository.ProjectRepository",
            new=lambda _s: _StubRepo(_StubProject(owner_id=owner_id)),
        ),
        patch(
            "app.modules.users.repository.UserRepository",
            new=lambda _s: _StubRepo(_StubUser(role="user")),
        ),
    ):
        # Should NOT raise - owner has full access.
        await pi_router._verify_project_access(
            session=SimpleNamespace(),  # type: ignore[arg-type]
            project_id=project_id,
            user_id=owner_id,
        )


@pytest.mark.asyncio
async def test_verify_project_access_requires_authentication() -> None:
    """Anonymous caller (user_id=None) is rejected with 401, no DB touched."""
    from app.modules.project_intelligence import router as pi_router

    with pytest.raises(HTTPException) as exc_info:
        await pi_router._verify_project_access(
            session=SimpleNamespace(),  # type: ignore[arg-type]
            project_id=uuid.uuid4(),
            user_id=None,
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_project_access_admin_bypass() -> None:
    """Admins can read any project - used by support/debug flows.

    The admin check coerces ``user_id`` via ``uuid.UUID(str(user_id))`` before
    reading the role, so the test uses a real UUID admin id (a non-UUID id
    would make the coercion raise and silently skip the bypass).
    """
    from app.modules.project_intelligence import router as pi_router

    admin_id = str(uuid.uuid4())
    project_id = uuid.uuid4()

    with (
        patch(
            "app.modules.projects.repository.ProjectRepository",
            new=lambda _s: _StubRepo(_StubProject(owner_id=str(uuid.uuid4()))),
        ),
        patch(
            "app.modules.users.repository.UserRepository",
            new=lambda _s: _StubRepo(_StubUser(role="admin")),
        ),
    ):
        # Should NOT raise - admin bypasses ownership.
        await pi_router._verify_project_access(
            session=SimpleNamespace(),  # type: ignore[arg-type]
            project_id=project_id,
            user_id=admin_id,
        )


# ── 3. collect_project_state distinguishes cancellation from failure ──────


@pytest.mark.asyncio
async def test_collect_project_state_does_not_let_a_cancelled_collector_reach_the_merge() -> None:
    """A cancelled collector must not be mistaken for one that answered.

    ``collect_project_state`` fans its 14 ``_collect_*`` domain collectors
    out through one ``asyncio.gather(..., return_exceptions=True)`` and then
    unpacks the result tuple, substituting a domain default wherever a slot
    holds an exception. ``asyncio.CancelledError`` has been a
    ``BaseException`` rather than an ``Exception`` since Python 3.8, so a
    check written as ``isinstance(x, Exception)`` does not catch it: a
    cancelled collector's ``CancelledError`` instance would be handed to
    ``ProjectState`` in place of the domain object every downstream reader
    expects, and the crash would surface wherever that object's attributes
    are first read - nowhere near the cancellation that produced it.

    ``_collect_boq`` is replaced with a coroutine that raises
    ``CancelledError`` directly, which is exactly the object
    ``asyncio.gather`` places in the results tuple for a genuinely
    cancelled task - the unpacking code this test exercises cannot tell the
    two apart. Every other collector is replaced with a fast stub, and
    ``_with_own_session`` is bypassed entirely, so the test needs no
    database.
    """
    from app.modules.project_intelligence import collector

    async def _cancelled(_session: Any, _project_id: str) -> Any:
        raise asyncio.CancelledError()

    async def _ok_dict(_session: Any, _project_id: str) -> dict[str, Any]:
        return {}

    def _ok_state(cls: type) -> Any:
        async def _inner(_session: Any, _project_id: str) -> Any:
            return cls()

        return _inner

    async def _fake_with_own_session(fn: Any, project_id: str) -> Any:
        return await fn(None, project_id)

    patches = [
        patch.object(collector, "_collect_project_info", _ok_dict),
        patch.object(collector, "_collect_boq", _cancelled),
        patch.object(collector, "_collect_schedule", _ok_state(collector.ScheduleState)),
        patch.object(collector, "_collect_takeoff", _ok_state(collector.TakeoffState)),
        patch.object(collector, "_collect_validation", _ok_state(collector.ValidationState)),
        patch.object(collector, "_collect_risk", _ok_state(collector.RiskState)),
        patch.object(collector, "_collect_tendering", _ok_state(collector.TenderingState)),
        patch.object(collector, "_collect_documents", _ok_state(collector.DocumentsState)),
        patch.object(collector, "_collect_reports", _ok_state(collector.ReportsState)),
        patch.object(collector, "_collect_cost_model", _ok_state(collector.CostModelState)),
        patch.object(collector, "_collect_requirements", _ok_state(collector.RequirementsState)),
        patch.object(collector, "_collect_bim", _ok_state(collector.BIMState)),
        patch.object(collector, "_collect_tasks", _ok_state(collector.TasksState)),
        patch.object(collector, "_collect_assemblies", _ok_state(collector.AssembliesState)),
        patch.object(collector, "_with_own_session", _fake_with_own_session),
    ]

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        state = await collector.collect_project_state(
            SimpleNamespace(),  # type: ignore[arg-type]
            str(uuid.uuid4()),
        )

    assert state.boq == collector.BOQState()
    assert not isinstance(state.boq, BaseException)
