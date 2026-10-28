"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Custom (user-authored) AI agents — service + run-path lifecycle.

Exercises the custom-agent feature end to end against a transaction-isolated
PostgreSQL session (rolled back on teardown), never the production DB and
without the slow full-app lifespan:

* the guided builder spec compiles into a coherent system prompt;
* AgentService creates / lists / resolves / updates / deletes custom agents;
* per-user ownership: another user cannot resolve/get/update/delete them;
* a custom agent runs through the SAME AgentRunner loop as the built-ins
  (via AgentService.start_run with an injected ScriptedLLM) and the run row
  reaches status=completed with the scripted answer;
* a custom agent's run name is the ``custom:<id>`` slug round-tripped on the
  persisted AgentRun.

The LLM is a ScriptedLLM, so no external provider is contacted.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_agents.llm import ScriptedLLM
from app.modules.ai_agents.service import (
    AgentService,
    compile_guided_prompt,
)
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


# ── 1. Guided-prompt compilation ──────────────────────────────────────────


def test_compile_guided_prompt_is_coherent() -> None:
    prompt = compile_guided_prompt(
        {
            "role": "a senior quantity surveyor",
            "goal": "draft clear variation cover letters",
            "audience": "the client",
            "output_format": "a short formal letter",
            "extra_guidance": "always reference the contract clause",
        }
    )
    assert "You are a senior quantity surveyor." in prompt
    assert "draft clear variation cover letters" in prompt
    assert "the client" in prompt
    assert "short formal letter" in prompt
    assert "contract clause" in prompt
    # Always ends with the safety guardrail.
    assert "review and confirm" in prompt


def test_compile_guided_prompt_sparse_goal_only() -> None:
    prompt = compile_guided_prompt({"goal": "summarise daily site diaries"})
    assert "knowledgeable construction assistant" in prompt
    assert "summarise daily site diaries" in prompt


# ── 2. Service CRUD + ownership ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_agent_crud_and_ownership(session: AsyncSession) -> None:
    owner = uuid.uuid4()
    other = uuid.uuid4()
    svc = AgentService(session)

    row = await svc.create_custom_agent(
        user_id=owner,
        display_name="Variation Letter Helper",
        tagline="Draft variation cover letters",
        description="",
        category="documents",
        icon="filetext",
        example_prompts=["Draft a delay letter", ""],
        guided={"role": "a senior QS", "goal": "draft variation cover letters"},
        system_prompt="",
    )
    await session.flush()

    # Guided spec compiled; empty example dropped.
    assert "senior QS" in row.system_prompt
    assert row.example_prompts == ["Draft a delay letter"]
    run_name = row.agent_name
    assert run_name == f"custom:{row.id}"

    # Listing returns it for the owner, not for another user.
    assert [r.id for r in await svc.list_custom_agents(owner)] == [row.id]
    assert await svc.list_custom_agents(other) == []

    # resolve_agent: owner resolves a runnable Agent (prompt-only, no tools).
    resolved = await svc.resolve_agent(run_name, owner)
    assert resolved is not None
    assert resolved.name == run_name
    assert resolved.allowed_tools == []
    # Another user cannot resolve it.
    assert await svc.resolve_agent(run_name, other) is None

    # get scoped by owner.
    assert await svc.get_custom_agent(row.id, owner) is not None
    assert await svc.get_custom_agent(row.id, other) is None

    # Update (full replace) by owner.
    updated = await svc.update_custom_agent(
        agent_id=row.id,
        user_id=owner,
        display_name="Variation Letter Helper v2",
        tagline="",
        description="",
        category="estimating",
        icon="filetext",
        example_prompts=[],
        guided={"role": "a senior QS", "goal": "draft variation letters and summarise cost impact"},
        system_prompt="",
    )
    assert updated is not None
    assert updated.display_name == "Variation Letter Helper v2"
    assert updated.category == "estimating"
    assert "cost impact" in updated.system_prompt
    # A non-owner update is a no-op (returns None).
    assert (
        await svc.update_custom_agent(
            agent_id=row.id,
            user_id=other,
            display_name="hijack",
            tagline="",
            description="",
            category="general",
            icon="bot",
            example_prompts=[],
            guided={"goal": "hijack"},
            system_prompt="",
        )
        is None
    )

    # Delete: non-owner cannot, owner can.
    assert await svc.delete_custom_agent(row.id, other) is False
    assert await svc.delete_custom_agent(row.id, owner) is True
    assert await svc.get_custom_agent(row.id, owner) is None


@pytest.mark.asyncio
async def test_create_custom_agent_requires_prompt(session: AsyncSession) -> None:
    svc = AgentService(session)
    with pytest.raises(ValueError, match="guided spec"):
        await svc.create_custom_agent(
            user_id=uuid.uuid4(),
            display_name="Empty",
            tagline="",
            description="",
            category="general",
            icon="sparkles",
            example_prompts=[],
            guided=None,
            system_prompt="",
        )


# ── 3. Custom agent runs through the shared runner loop ─────────────────────


@pytest.mark.asyncio
async def test_custom_agent_runs_to_completion(session: AsyncSession) -> None:
    owner = uuid.uuid4()
    svc = AgentService(session)

    row = await svc.create_custom_agent(
        user_id=owner,
        display_name="Raw Prompt Agent",
        tagline="",
        description="",
        category="general",
        icon="bot",
        example_prompts=[],
        guided=None,
        system_prompt="You are a helpful estimator. Answer the question.",
    )

    # Resolve the runnable Agent exactly as the router does (custom:<id> slug),
    # confirming ownership-scoped resolution returns a prompt-only agent.
    resolved = await svc.resolve_agent(row.agent_name, owner)
    assert resolved is not None
    assert resolved.allowed_tools == []
    # Capture the slug now: start_run calls expire_all() on the shared session,
    # which would expire `row` and turn a later `row.agent_name` access into a
    # lazy reload outside the test's greenlet.
    run_name = resolved.name
    # A different user cannot resolve it.
    assert await svc.resolve_agent(run_name, uuid.uuid4()) is None

    # Inject a one-shot scripted final answer so no provider is contacted.
    llm = ScriptedLLM(
        script=[{"type": "final", "text": "Here is the variation cover letter you asked for."}],
        tokens_per_call=12,
    )

    # Run through the shared AgentService.start_run path (same loop the built-ins
    # use). The resolved custom Agent is registered transiently so start_run's
    # get_agent() finds it, mirroring how the router resolves and runs it.
    run = await _run_custom(svc, owner, resolved, "3-day delay, +1200 EUR", llm)
    assert run.agent_name == run_name
    assert run.status == "completed", run.failure_reason
    assert "variation cover letter" in (run.final_output or "")
    assert run.iterations == 1

    # Steps were persisted (the answer step at minimum).
    steps = await svc.get_run_steps(run.id)
    assert any(s.role == "answer" for s in steps)


async def _run_custom(svc, user_id, agent, user_input, llm):
    """Drive a resolved custom agent through the service run path.

    AgentService.start_run resolves built-ins via get_agent(); custom agents are
    resolved by the router and run through the same runner. Here we replicate
    that by registering the resolved Agent transiently so start_run can find it,
    then running with the injected scripted LLM (no provider contacted).
    """
    from app.modules.ai_agents.base import _agents

    _agents[agent.name] = agent
    try:
        return await svc.start_run(
            user_id=user_id,
            agent_name=agent.name,
            user_input=user_input,
            llm=llm,
        )
    finally:
        _agents.pop(agent.name, None)
