"""Baseline tests for the AI Agents framework — cost-runaway guards + safety.

Focuses on the safety contract added during the v4.2.2 audit pass:

* ``test_max_iterations_hits_cap``  — runaway tool-call loop is bounded by
  ``Agent.max_iterations`` (failure_reason="iter_limit"); the agent does
  NOT recurse indefinitely.
* ``test_token_budget_halts_run``   — once aggregate LLM token spend
  crosses ``Agent.max_total_tokens`` the loop aborts with
  failure_reason="token_limit" (protects the LLM bill).
* ``test_llm_step_timeout``         — a slow LLM call is cancelled after
  ``Agent.llm_step_timeout`` seconds with failure_reason="llm_timeout".
* ``test_observation_truncated``    — a 10MB tool response is clipped
  before re-entering the LLM context (next-step cost stays bounded).
* ``test_tool_receives_user_context_for_permission_recheck`` — tools
  are passed ``__agent_context__`` so they can re-verify the invoking
  user's permission instead of trusting the agent's elevated runner
  context blindly.
* ``test_happy_path_returns_expected_structure`` — a single-step "final"
  reply produces a completed AgentResult with the expected fields.

Per project convention these are pure unit tests — no DB, no FastAPI
client, no network. The ``ScriptedLLM`` mock + ``FunctionTool`` shim give
us full control over the loop.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.modules.ai_agents.base import (
    Agent,
    AgentRunner,
    FunctionTool,
    LLMBridge,
    ToolRegistry,
)
from app.modules.ai_agents.llm import ScriptedLLM

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_registry(tools: list[FunctionTool]) -> ToolRegistry:
    """Build an isolated registry — never touch the module-level global."""
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_iterations_hits_cap():
    """A misbehaving LLM that only ever returns tool_calls must halt at the cap."""

    async def _echo(x: str = "") -> dict[str, Any]:
        return {"echoed": x}

    registry = _make_registry(
        [
            FunctionTool(
                name="echo",
                description="echo back",
                input_schema={"type": "object"},
                func=_echo,
            )
        ]
    )

    # The scripted LLM repeats its last item forever — perfect runaway sim.
    llm = ScriptedLLM(
        script=[{"type": "tool_call", "name": "echo", "args": {"x": "hi"}}],
        tokens_per_call=10,
    )
    agent = Agent(
        name="loopbot",
        max_iterations=3,
        allowed_tools=["echo"],
        # Disable other caps so we isolate the iteration guard.
        max_total_tokens=0,
        max_wall_seconds=0.0,
        llm_step_timeout=0.0,
    )

    result = await AgentRunner(llm).run(agent, "go", tool_registry=registry)

    assert result.status == "failed"
    assert result.failure_reason == "iter_limit"
    assert result.iterations == 3
    # 3 LLM calls × 10 tokens.
    assert result.total_tokens == 30


@pytest.mark.asyncio
async def test_token_budget_halts_run():
    """When cumulative tokens exceed ``max_total_tokens`` the run aborts cleanly."""

    async def _noop() -> dict[str, Any]:
        return {"ok": True}

    registry = _make_registry(
        [
            FunctionTool(
                name="noop",
                description="noop",
                input_schema={"type": "object"},
                func=_noop,
            )
        ]
    )

    llm = ScriptedLLM(
        script=[{"type": "tool_call", "name": "noop", "args": {}}],
        tokens_per_call=200,
    )
    agent = Agent(
        name="costly",
        max_iterations=50,  # plenty of room — token guard fires first
        allowed_tools=["noop"],
        max_total_tokens=300,  # 2nd call (400 cumulative) trips this
        max_wall_seconds=0.0,
        llm_step_timeout=0.0,
    )

    result = await AgentRunner(llm).run(agent, "go", tool_registry=registry)

    assert result.status == "failed"
    assert result.failure_reason == "token_limit"
    assert result.total_tokens >= 300


@pytest.mark.asyncio
async def test_llm_step_timeout():
    """A hung LLM call is cancelled at the per-step timeout boundary."""

    class _HangingLLM(LLMBridge):
        async def next_step(self, *, system_prompt, messages, tools):  # type: ignore[override]
            await asyncio.sleep(5.0)  # well past the 0.05s budget
            return {"type": "final", "text": "never reached"}, 0

    agent = Agent(
        name="slowllm",
        max_iterations=2,
        allowed_tools=[],
        llm_step_timeout=0.05,
        max_total_tokens=0,
        max_wall_seconds=0.0,
    )

    result = await AgentRunner(_HangingLLM()).run(agent, "go", tool_registry=ToolRegistry())

    assert result.status == "failed"
    assert result.failure_reason == "llm_timeout"


@pytest.mark.asyncio
async def test_observation_truncated():
    """A 1MB tool observation must be clipped before re-entering the loop."""

    huge_payload = "X" * 1_000_000  # 1 MB string

    async def _huge() -> str:
        return huge_payload

    registry = _make_registry(
        [
            FunctionTool(
                name="huge",
                description="returns a huge string",
                input_schema={"type": "object"},
                func=_huge,
            )
        ]
    )

    # Two-step script: call tool, then emit final.
    llm = ScriptedLLM(
        script=[
            {"type": "tool_call", "name": "huge", "args": {}},
            {"type": "final", "text": "done"},
        ],
        tokens_per_call=0,
    )
    agent = Agent(
        name="bigreader",
        max_iterations=4,
        allowed_tools=["huge"],
        max_observation_chars=500,
        max_total_tokens=0,
        max_wall_seconds=0.0,
        llm_step_timeout=0.0,
    )

    result = await AgentRunner(llm).run(agent, "go", tool_registry=registry)

    assert result.status == "completed"
    obs_steps = [s for s in result.steps if s.role == "observation"]
    assert obs_steps, "observation step should be recorded"
    obs = obs_steps[0].content
    # Truncation produces either a clipped string with marker, or a wrapped
    # {"truncated": True, ...} envelope — both are acceptable bounded shapes.
    if isinstance(obs, str):
        assert len(obs) < 1000  # well below the 1MB original
        assert "truncated" in obs
    else:
        assert isinstance(obs, dict)
        assert obs.get("truncated") is True
        assert len(obs.get("preview", "")) <= 500


@pytest.mark.asyncio
async def test_tool_receives_user_context_for_permission_recheck():
    """Tools can read ``__agent_context__`` to re-verify the calling user.

    The runner must NOT let the LLM forge a different user_id — the
    context dict comes from the trusted service layer, not the model.
    """
    seen: dict[str, Any] = {}

    async def _privileged(target: str, **kwargs: Any) -> dict[str, Any]:
        # A real tool would call permission_registry.check(...) here.
        ctx = kwargs.get("__agent_context__") or {}
        seen["ctx"] = ctx
        seen["target"] = target
        # Pretend permission check: only the original user may proceed.
        if ctx.get("user_id") != "user-123":
            return {"error": "forbidden"}
        return {"ok": True, "target": target}

    registry = _make_registry(
        [
            FunctionTool(
                name="privileged",
                description="a permissioned tool",
                input_schema={"type": "object"},
                func=_privileged,
            )
        ]
    )

    # LLM tries to spoof a different user_id in the args.
    llm = ScriptedLLM(
        script=[
            {
                "type": "tool_call",
                "name": "privileged",
                "args": {"target": "secret", "__agent_context__": {"user_id": "attacker"}},
            },
            {"type": "final", "text": "done"},
        ],
        tokens_per_call=0,
    )
    agent = Agent(
        name="permbot",
        max_iterations=3,
        allowed_tools=["privileged"],
        max_total_tokens=0,
        max_wall_seconds=0.0,
        llm_step_timeout=0.0,
    )

    # Trusted context supplied by the service layer (NOT the LLM).
    result = await AgentRunner(llm).run(
        agent,
        "go",
        context={"user_id": "user-123", "project_id": "proj-1"},
        tool_registry=registry,
    )

    assert result.status == "completed"
    # The trusted context wins — args injected by the LLM are overwritten.
    assert seen["ctx"].get("user_id") == "user-123"
    assert seen["target"] == "secret"


@pytest.mark.asyncio
async def test_happy_path_returns_expected_structure():
    """Single-step ``final`` reply produces a clean AgentResult."""
    llm = ScriptedLLM(
        script=[{"type": "final", "text": "all done"}],
        tokens_per_call=42,
    )
    agent = Agent(name="finalbot", max_iterations=4)

    result = await AgentRunner(llm).run(agent, "go", tool_registry=ToolRegistry())

    assert result.status == "completed"
    assert result.failure_reason is None
    assert result.final_output == "all done"
    assert result.iterations == 1
    assert result.total_tokens == 42
    assert any(s.role == "answer" for s in result.steps)
