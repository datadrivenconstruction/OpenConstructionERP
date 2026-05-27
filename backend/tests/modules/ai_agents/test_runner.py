"""AI Agents — runner + registry + persistence tests.

Per ``feedback_test_isolation.md`` every test that touches the DB spins
up its own temp SQLite — never the shared session DB.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.ai_agents.agents.boq_drafter import register_boq_drafter
from app.modules.ai_agents.base import (
    Agent,
    AgentRunner,
    FunctionTool,
    StepRecord,
    ToolRegistry,
)
from app.modules.ai_agents.llm import ScriptedLLM, parse_llm_response


def _register_models() -> None:
    """Eagerly register ORM modules referenced by the per-test DB."""
    import app.modules.ai_agents.models  # noqa: F401


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Per-test SQLite session — never touches the production DB."""
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-ai-agents-")) / "agents.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


# ── Test fixtures ──────────────────────────────────────────────────────────


def _make_echo_tool(name: str = "echo") -> FunctionTool:
    """A tiny tool used by several tests."""

    async def _echo(message: str = "") -> dict[str, str]:
        return {"echoed": message}

    return FunctionTool(
        name=name,
        description="Echo the input message back.",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        func=_echo,
    )


# ── 1. Runner happy path with scripted LLM ────────────────────────────────


@pytest.mark.asyncio
async def test_runner_loop_with_scripted_mock_llm() -> None:
    """tool_call -> observation -> final_answer; runner exits after 1 tool call."""
    registry = ToolRegistry()
    registry.register(_make_echo_tool())

    llm = ScriptedLLM(
        script=[
            {
                "type": "tool_call",
                "name": "echo",
                "args": {"message": "hello"},
                "thought": "Calling echo to verify the loop.",
            },
            {"type": "final", "text": "Done. The echo tool returned: hello."},
        ],
        tokens_per_call=10,
    )
    agent = Agent(
        name="test_agent",
        system_prompt="Test",
        allowed_tools=["echo"],
        max_iterations=4,
    )
    runner = AgentRunner(llm)
    result = await runner.run(agent, "say hi", tool_registry=registry)

    assert result.status == "completed"
    assert result.final_output == "Done. The echo tool returned: hello."
    assert result.iterations == 2  # one tool_call iteration, one final iteration
    assert result.total_tokens == 20

    roles = [s.role for s in result.steps]
    # thought (from item.thought) + tool_call + observation + answer
    assert roles == ["thought", "tool_call", "observation", "answer"]
    assert result.steps[1].content == {"name": "echo", "args": {"message": "hello"}}
    assert result.steps[2].content == {"echoed": "hello"}


# ── 2. Max iterations enforced ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_iterations_hits_cap() -> None:
    """LLM always returns tool_calls; runner stops at max_iterations + fails."""
    registry = ToolRegistry()
    registry.register(_make_echo_tool())

    llm = ScriptedLLM(
        script=[{"type": "tool_call", "name": "echo", "args": {"message": "hi"}}],
        tokens_per_call=5,
    )
    agent = Agent(
        name="loop_agent",
        system_prompt="Loops forever",
        allowed_tools=["echo"],
        max_iterations=3,
    )
    runner = AgentRunner(llm)
    result = await runner.run(agent, "go", tool_registry=registry)

    assert result.status == "failed"
    assert result.failure_reason == "iter_limit"
    assert result.iterations == 3
    assert result.final_output is None
    # 3 iterations × (tool_call + observation) + 1 final iter_limit error step
    assert sum(1 for s in result.steps if s.role == "tool_call") == 3
    assert result.steps[-1].role == "error"
    assert result.steps[-1].content["reason"] == "iter_limit"


# ── 3. Tool registry dispatch ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_registry_dispatch() -> None:
    """register + get + all + dispatch via FunctionTool wrapper."""
    registry = ToolRegistry()
    assert registry.get("echo") is None
    assert registry.all() == []

    registry.register(_make_echo_tool("alpha"))
    registry.register(_make_echo_tool("beta"))
    assert sorted(t.name for t in registry.all()) == ["alpha", "beta"]
    assert registry.get("alpha") is not None
    assert registry.get("missing") is None

    out = await registry.get("alpha").run({"message": "x"})
    assert out == {"echoed": "x"}

    # Overwriting by same name is allowed.
    registry.register(_make_echo_tool("alpha"))
    assert len(registry.all()) == 2


# ── 4. Unknown tool recorded as error step ────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_tool_recorded_as_error_step() -> None:
    """A tool_call for an unregistered tool produces an observation with error."""
    registry = ToolRegistry()
    registry.register(_make_echo_tool())

    llm = ScriptedLLM(
        script=[
            {"type": "tool_call", "name": "ghost", "args": {}},
            {"type": "final", "text": "Couldn't find that tool — giving up."},
        ]
    )
    agent = Agent(name="explorer", allowed_tools=["echo", "ghost"], max_iterations=4)
    runner = AgentRunner(llm)
    result = await runner.run(agent, "try ghost", tool_registry=registry)

    assert result.status == "completed"
    obs = next(s for s in result.steps if s.role == "observation")
    assert obs.content["error"] == "unknown_tool"
    assert obs.content["name"] == "ghost"


# ── 5. BOQ drafter happy path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_boq_drafter_happy_path() -> None:
    """End-to-end with mock tools — verify a final BOQ proposal is returned."""
    # Use a fresh registry so test order doesn't bleed in real tool deps.
    registry = ToolRegistry()
    register_boq_drafter()  # writes to GLOBAL registry; we'll mirror needed tools

    # Mirror the three boq_drafter tools into our isolated registry.
    from app.modules.ai_agents.base import global_tool_registry

    for tool_name in ("search_costs", "suggest_assembly", "create_position"):
        tool = global_tool_registry.get(tool_name)
        assert tool is not None, f"{tool_name} must be registered by register_boq_drafter()"
        registry.register(tool)

    llm = ScriptedLLM(
        script=[
            {
                "type": "tool_call",
                "name": "search_costs",
                "args": {"q": "concrete wall", "region": "DE_BERLIN"},
            },
            {
                "type": "tool_call",
                "name": "create_position",
                "args": {
                    "description": "Reinforced concrete wall 24cm",
                    "unit": "m3",
                    "qty": 12,
                    "unit_rate": 280,
                },
            },
            {
                "type": "final",
                "text": "Proposal: 1 position\n- Reinforced concrete wall 24cm: 12 m3 @ 280",
            },
        ],
        tokens_per_call=3,
    )

    from app.modules.ai_agents.base import get_agent

    agent = get_agent("boq_drafter")
    assert agent is not None
    runner = AgentRunner(llm)
    result = await runner.run(
        agent,
        "Draft a BOQ for a 24cm reinforced concrete wall.",
        tool_registry=registry,
    )

    assert result.status == "completed"
    assert result.final_output is not None
    assert "Reinforced concrete wall" in result.final_output

    # Observation from create_position must be a proposal payload (not a DB write).
    create_obs = [s for s in result.steps if s.role == "observation" and isinstance(s.content, dict)]
    proposals = [c.content for c in create_obs if c.content.get("kind") == "boq_position_proposal"]
    assert proposals
    assert proposals[0]["confirmed"] is False  # human-confirmed principle
    assert proposals[0]["total"] == 12 * 280


# ── 6. Persistence: run + steps land in the DB ────────────────────────────


@pytest.mark.asyncio
async def test_agent_run_persisted_with_steps(session: AsyncSession) -> None:
    """AgentService.start_run writes a run row and one step per emit."""
    register_boq_drafter()

    from app.modules.ai_agents.base import get_agent
    from app.modules.ai_agents.service import AgentService

    service = AgentService(session)
    agent = get_agent("boq_drafter")
    assert agent is not None

    # Build an isolated tool registry holding the drafter tools.
    registry = ToolRegistry()
    from app.modules.ai_agents.base import global_tool_registry

    for tool_name in ("search_costs", "create_position"):
        tool = global_tool_registry.get(tool_name)
        assert tool is not None
        registry.register(tool)

    llm = ScriptedLLM(
        script=[
            {"type": "tool_call", "name": "search_costs", "args": {"q": "tiles"}},
            {"type": "final", "text": "Proposed 1 position."},
        ],
        tokens_per_call=4,
    )

    user_id = uuid.uuid4()
    run = await service.start_run(
        user_id=user_id,
        agent_name="boq_drafter",
        user_input="Tile a 50 m2 bathroom.",
        llm=llm,
        tool_registry=registry,
    )

    assert run.status == "completed"
    assert run.iterations == 2
    assert run.total_tokens == 8
    assert run.final_output == "Proposed 1 position."

    steps = await service.get_run_steps(run.id)
    roles = [s.role for s in steps]
    # tool_call + observation + answer (no thought channel for these items)
    assert roles == ["tool_call", "observation", "answer"]
    # All persisted steps are scoped to the same run.
    assert all(s.run_id == run.id for s in steps)
    # step_idx monotonically increasing
    assert [s.step_idx for s in steps] == [1, 2, 3]


# ── 7. Bonus — the text-protocol LLM parser ───────────────────────────────


def test_parse_llm_response_tool_call() -> None:
    """parse_llm_response extracts a <tool_call> block."""
    item = parse_llm_response(
        'I think I should call.\n<tool_call>{"name": "echo", "args": {"message": "hi"}}</tool_call>'
    )
    assert item["type"] == "tool_call"
    assert item["name"] == "echo"
    assert item["args"] == {"message": "hi"}
    assert "thought" in item


def test_parse_llm_response_final_when_no_tool_call() -> None:
    """parse_llm_response returns a final answer when no block is present."""
    item = parse_llm_response("Done — total 1234 EUR.")
    assert item == {"type": "final", "text": "Done — total 1234 EUR."}


# ── 8. on_step callback fires for every emitted step ─────────────────────


@pytest.mark.asyncio
async def test_on_step_callback_receives_every_step() -> None:
    registry = ToolRegistry()
    registry.register(_make_echo_tool())

    captured: list[StepRecord] = []

    async def _capture(step: StepRecord) -> None:
        captured.append(step)

    llm = ScriptedLLM(
        script=[
            {"type": "tool_call", "name": "echo", "args": {"message": "y"}},
            {"type": "final", "text": "ok"},
        ]
    )
    agent = Agent(name="cb_agent", allowed_tools=["echo"], max_iterations=4)
    runner = AgentRunner(llm, on_step=_capture)
    await runner.run(agent, "go", tool_registry=registry)

    assert [s.role for s in captured] == ["tool_call", "observation", "answer"]
