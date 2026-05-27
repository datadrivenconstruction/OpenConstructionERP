"""Base agent framework — Tool protocol, registry, Agent + AgentRunner.

The runner implements a ReAct loop:

    user_input -> [LLM] -> tool_call -> [registry.run] -> observation
                        \\-> final answer (exit)

The LLM itself is abstracted behind :class:`LLMBridge` so tests can plug in
a scripted mock and production can use the existing ``ai`` module client.

Safety guards (cost runaway prevention) — all configurable per agent:

* ``max_iterations``      — hard ReAct-loop cap (failure_reason="iter_limit").
* ``max_total_tokens``    — sum tokens across all steps; halts when exceeded
                            (failure_reason="token_limit").
* ``max_wall_seconds``    — total wall-clock budget for the run
                            (failure_reason="wall_timeout").
* ``llm_step_timeout``    — per-LLM-call timeout (failure_reason="llm_timeout").
* ``max_observation_chars`` — truncate tool output so an oversized read
                              (10MB PDF, full DB dump) doesn't blow up the
                              next-step LLM prompt cost.

Structured per-step logging: every step emits one INFO record with
``agent``, ``step_idx``, ``role``, ``token_count``, ``tool``, ``tokens_total``
so prod log aggregators can sum cost per agent / per user / per day.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Default safety caps ─────────────────────────────────────────────────────
# Conservative defaults that catch obviously-runaway agents but leave headroom
# for legitimate multi-step BOQ drafts. Tune per-agent if needed.
DEFAULT_MAX_TOTAL_TOKENS = 20_000
DEFAULT_MAX_WALL_SECONDS = 120.0
DEFAULT_LLM_STEP_TIMEOUT = 45.0
DEFAULT_MAX_OBSERVATION_CHARS = 8_000


def _truncate_observation(value: Any, cap: int) -> Any:
    """Bound the size of a tool observation before it re-enters the LLM context.

    Tools may legitimately return large payloads (5MB document, multi-MB
    CAD JSON). Feeding that back into the LLM costs O(N) tokens per
    remaining step and is the most common cause of runaway agent cost.

    String values are clipped with a trailing ``...[truncated N chars]``
    marker; dict/list values are JSON-serialised then clipped the same
    way (preserving structure information up to the cap).
    """
    if cap <= 0:
        return value
    import json as _json

    if isinstance(value, str):
        if len(value) <= cap:
            return value
        return value[:cap] + f"...[truncated {len(value) - cap} chars]"
    try:
        encoded = _json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        encoded = str(value)
    if len(encoded) <= cap:
        return value
    return {
        "truncated": True,
        "original_chars": len(encoded),
        "preview": encoded[:cap],
    }


# ── Tool protocol ───────────────────────────────────────────────────────────


@runtime_checkable
class Tool(Protocol):
    """A side-effect-free helper an agent can dispatch to.

    Implementations may be either Tool *instances* (an object with the
    three attributes + an async ``run``) or any object that quacks the
    same shape — keeps the registry tolerant of duck typing.
    """

    name: str
    description: str
    input_schema: dict[str, Any]

    async def run(self, args: dict[str, Any]) -> Any: ...  # pragma: no cover


@dataclass
class FunctionTool:
    """Convenience adapter: wrap a plain async callable as a :class:`Tool`."""

    name: str
    description: str
    input_schema: dict[str, Any]
    func: Callable[..., Any]

    async def run(self, args: dict[str, Any]) -> Any:
        """Invoke the wrapped callable with ``**args`` (await if needed).

        The runner injects ``__agent_context__`` into every call so tools
        that need the invoking user / project can re-verify permission.
        Tools that ignore the context have it stripped transparently —
        we only forward keys the underlying callable actually accepts.
        """
        ctx = args.pop("__agent_context__", None)
        # Forward context only if the callable accepts it (or accepts **kwargs).
        sig_params: set[str] = set()
        accepts_var_kw = False
        try:
            sig = inspect.signature(self.func)
            for p in sig.parameters.values():
                if p.kind is inspect.Parameter.VAR_KEYWORD:
                    accepts_var_kw = True
                else:
                    sig_params.add(p.name)
        except (TypeError, ValueError):
            accepts_var_kw = True  # builtins / C-extensions — be permissive
        if ctx is not None and (accepts_var_kw or "__agent_context__" in sig_params):
            args["__agent_context__"] = ctx
        result = self.func(**args)
        if inspect.isawaitable(result):
            result = await result
        return result


# ── Tool registry ───────────────────────────────────────────────────────────


class ToolRegistry:
    """In-memory mapping name -> Tool.

    Module-level registries (e.g. the global registry the BOQ-drafter
    populates at import time) and per-run registries (a test may install
    a few mocks just for one ``AgentRunner.run`` call) both use the same
    class — there's nothing magical about the global instance.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add a tool (overwrites a previous registration with the same name)."""
        if not getattr(tool, "name", None):
            msg = "Tool must declare a non-empty 'name'"
            raise ValueError(msg)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Return the tool with this name, or None if not registered."""
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        """Return every tool currently registered."""
        return list(self._tools.values())

    def names(self) -> list[str]:
        return sorted(self._tools.keys())


# Module-level global. Agents and the API router import this to discover
# what tools are available. Tests should construct their own
# :class:`ToolRegistry` and pass it explicitly to keep state isolated.
global_tool_registry = ToolRegistry()


# ── Agent ───────────────────────────────────────────────────────────────────


@dataclass
class Agent:
    """Declarative agent metadata.

    The agent does NOT carry behaviour itself — :class:`AgentRunner` reads
    these attributes and drives the actual loop. Subclassing is therefore
    optional; most agents just instantiate :class:`Agent` with the right
    values.

    Safety caps (see module docstring for rationale):

    * ``max_iterations``  — ReAct-loop step cap.
    * ``max_total_tokens`` — aborts when total token usage exceeds this.
    * ``max_wall_seconds`` — total wall-clock budget for the whole run.
    * ``llm_step_timeout`` — per-LLM-call timeout (seconds).
    * ``max_observation_chars`` — clip oversized tool outputs.
    """

    name: str
    system_prompt: str = ""
    description: str = ""
    max_iterations: int = 8
    allowed_tools: list[str] = field(default_factory=list)
    max_total_tokens: int = DEFAULT_MAX_TOTAL_TOKENS
    max_wall_seconds: float = DEFAULT_MAX_WALL_SECONDS
    llm_step_timeout: float = DEFAULT_LLM_STEP_TIMEOUT
    max_observation_chars: int = DEFAULT_MAX_OBSERVATION_CHARS


# Agents registry (separate from tools) so the UI can list "available agents".
_agents: dict[str, Agent] = {}


def register_agent(agent: Agent) -> None:
    """Add an agent to the global registry (overwrites by name)."""
    if not agent.name:
        msg = "Agent must have a non-empty name"
        raise ValueError(msg)
    _agents[agent.name] = agent


def get_agent(name: str) -> Agent | None:
    return _agents.get(name)


def list_agents() -> list[Agent]:
    return list(_agents.values())


# ── LLM bridge (forward decl — concrete implementation in llm.py) ──────────


LLMItem = dict[str, Any]  # {"type": "tool_call", "name": str, "args": dict}
# or {"type": "final", "text": str}


@runtime_checkable
class LLMBridge(Protocol):
    """Uniform LLM interface the runner talks to.

    A bridge takes the conversation history (system + alternating
    user/assistant/tool messages) and returns either a tool-call request
    or a final answer. Token usage is reported as a side metric.
    """

    async def next_step(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[Tool],
    ) -> tuple[LLMItem, int]: ...  # pragma: no cover


# ── Runner result ──────────────────────────────────────────────────────────


@dataclass
class StepRecord:
    """One row of the run's timeline, ready for persistence."""

    role: str  # thought | tool_call | observation | answer | error
    content: Any
    token_count: int = 0


@dataclass
class AgentResult:
    """Final summary returned by :meth:`AgentRunner.run`."""

    status: str  # completed | failed
    final_output: str | None
    iterations: int
    total_tokens: int
    steps: list[StepRecord] = field(default_factory=list)
    failure_reason: str | None = None


# ── Runner ──────────────────────────────────────────────────────────────────


class AgentRunner:
    """Drives the ReAct loop for an :class:`Agent`.

    The runner is stateless — every call to :meth:`run` builds a fresh
    message history. Persistence is the caller's responsibility
    (``service.AgentService`` writes :class:`StepRecord`\\s to
    :class:`models.AgentStep` as the loop progresses, but the runner
    itself doesn't depend on the DB).
    """

    def __init__(
        self,
        llm: LLMBridge,
        *,
        on_step: Callable[[StepRecord], Awaitable[None] | None] | None = None,
    ) -> None:
        self.llm = llm
        self._on_step = on_step

    async def _emit(self, step: StepRecord) -> None:
        """Notify the optional persistence callback after a step is produced."""
        if self._on_step is None:
            return
        out = self._on_step(step)
        if inspect.isawaitable(out):
            await out

    async def run(
        self,
        agent: Agent,
        user_input: str,
        *,
        context: dict[str, Any] | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> AgentResult:
        """Execute the ReAct loop until a final answer or max_iterations.

        Args:
            agent: declarative agent metadata.
            user_input: the user's initial question / instruction.
            context: optional dict to expose to the system prompt (e.g.
                project_id). Rendered as ``[context] key=value`` lines.
            tool_registry: registry to dispatch tool_calls against.
                Defaults to the module-level :data:`global_tool_registry`.

        Returns:
            :class:`AgentResult` describing the outcome. ``status`` is
            ``completed`` on a final answer, ``failed`` otherwise.
            ``failure_reason`` is set on failure (``iter_limit``,
            ``llm_error``, ``unknown_tool`` ...).
        """
        registry = tool_registry or global_tool_registry
        allowed = set(agent.allowed_tools)
        available_tools: list[Tool] = [t for t in registry.all() if not allowed or t.name in allowed]

        messages: list[dict[str, Any]] = []
        if context:
            ctx_lines = "\n".join(f"{k}={v}" for k, v in context.items())
            messages.append({"role": "user", "content": f"[context]\n{ctx_lines}"})
        messages.append({"role": "user", "content": user_input})

        steps: list[StepRecord] = []
        total_tokens = 0
        iterations = 0
        run_started = time.monotonic()
        wall_budget = max(0.0, float(agent.max_wall_seconds or 0.0))
        token_budget = max(0, int(agent.max_total_tokens or 0))
        obs_cap = max(0, int(agent.max_observation_chars or 0))
        step_timeout = max(0.0, float(agent.llm_step_timeout or 0.0))

        def _wall_exceeded() -> bool:
            return wall_budget > 0 and (time.monotonic() - run_started) >= wall_budget

        def _tokens_exceeded() -> bool:
            return token_budget > 0 and total_tokens >= token_budget

        def _log_step(step: StepRecord, *, tool: str | None = None) -> None:
            """Emit structured per-step cost record for log aggregators."""
            logger.info(
                "ai_agent.step agent=%s iter=%s role=%s tokens=%s tokens_total=%s tool=%s",
                agent.name,
                iterations,
                step.role,
                step.token_count,
                total_tokens,
                tool or "",
            )

        for iterations in range(1, agent.max_iterations + 1):
            # Wall-clock guard BEFORE the LLM call (cheap to check).
            if _wall_exceeded():
                cap_step = StepRecord(
                    role="error",
                    content={"reason": "wall_timeout", "limit_s": wall_budget},
                )
                steps.append(cap_step)
                await self._emit(cap_step)
                _log_step(cap_step)
                return AgentResult(
                    status="failed",
                    final_output=None,
                    iterations=iterations,
                    total_tokens=total_tokens,
                    steps=steps,
                    failure_reason="wall_timeout",
                )

            try:
                if step_timeout > 0:
                    item, tokens = await asyncio.wait_for(
                        self.llm.next_step(
                            system_prompt=agent.system_prompt,
                            messages=messages,
                            tools=available_tools,
                        ),
                        timeout=step_timeout,
                    )
                else:
                    item, tokens = await self.llm.next_step(
                        system_prompt=agent.system_prompt,
                        messages=messages,
                        tools=available_tools,
                    )
            except TimeoutError:
                err_step = StepRecord(
                    role="error",
                    content={"reason": "llm_timeout", "timeout_s": step_timeout},
                )
                steps.append(err_step)
                await self._emit(err_step)
                _log_step(err_step)
                return AgentResult(
                    status="failed",
                    final_output=None,
                    iterations=iterations,
                    total_tokens=total_tokens,
                    steps=steps,
                    failure_reason="llm_timeout",
                )
            except Exception as exc:  # pragma: no cover - defensive
                err_step = StepRecord(
                    role="error",
                    content={"reason": "llm_error", "message": str(exc)[:300]},
                )
                steps.append(err_step)
                await self._emit(err_step)
                _log_step(err_step)
                return AgentResult(
                    status="failed",
                    final_output=None,
                    iterations=iterations,
                    total_tokens=total_tokens,
                    steps=steps,
                    failure_reason="llm_error",
                )

            total_tokens += int(tokens or 0)

            # Token-budget guard AFTER accumulating this step's spend.
            if _tokens_exceeded():
                cap_step = StepRecord(
                    role="error",
                    content={
                        "reason": "token_limit",
                        "limit": token_budget,
                        "used": total_tokens,
                    },
                    token_count=int(tokens or 0),
                )
                steps.append(cap_step)
                await self._emit(cap_step)
                _log_step(cap_step)
                return AgentResult(
                    status="failed",
                    final_output=None,
                    iterations=iterations,
                    total_tokens=total_tokens,
                    steps=steps,
                    failure_reason="token_limit",
                )

            item_type = item.get("type")
            if item_type == "final":
                text = str(item.get("text", "")).strip()
                ans_step = StepRecord(role="answer", content={"text": text}, token_count=tokens)
                steps.append(ans_step)
                await self._emit(ans_step)
                _log_step(ans_step)
                return AgentResult(
                    status="completed",
                    final_output=text,
                    iterations=iterations,
                    total_tokens=total_tokens,
                    steps=steps,
                )

            if item_type == "tool_call":
                tool_name = str(item.get("name", "")).strip()
                tool_args = item.get("args") or {}
                if not isinstance(tool_args, dict):
                    tool_args = {}

                # Optional 'thought' channel for richer UI rendering.
                thought = item.get("thought")
                if isinstance(thought, str) and thought.strip():
                    th_step = StepRecord(role="thought", content={"text": thought.strip()})
                    steps.append(th_step)
                    await self._emit(th_step)
                    _log_step(th_step)

                tc_step = StepRecord(
                    role="tool_call",
                    content={"name": tool_name, "args": tool_args},
                    token_count=tokens,
                )
                steps.append(tc_step)
                await self._emit(tc_step)
                _log_step(tc_step, tool=tool_name)

                tool = registry.get(tool_name) if tool_name else None
                if tool is None or (allowed and tool_name not in allowed):
                    err_payload = {
                        "name": tool_name,
                        "error": "unknown_tool",
                        "available": [t.name for t in available_tools],
                    }
                    obs_step = StepRecord(role="observation", content=err_payload)
                    steps.append(obs_step)
                    await self._emit(obs_step)
                    _log_step(obs_step, tool=tool_name)
                    messages.append(
                        {
                            "role": "tool",
                            "name": tool_name,
                            "content": err_payload,
                        }
                    )
                    continue

                # Forward the user/project context to tools that opt in.
                # Tools sniff ``__agent_context__`` and re-verify the user's
                # permission before performing privileged actions — we never
                # trust the LLM's elevated runner context implicitly.
                #
                # SECURITY: any ``__agent_context__`` the LLM tried to forge
                # in its tool_call args is STRIPPED before we re-inject the
                # trusted runtime context. A model that asks to run a tool
                # "as another user" must not be able to do so.
                call_args = {k: v for k, v in tool_args.items() if k != "__agent_context__"}
                if context:
                    call_args["__agent_context__"] = dict(context)

                try:
                    raw_observation = await tool.run(call_args)
                    observation = _truncate_observation(raw_observation, obs_cap)
                    obs_step = StepRecord(role="observation", content=observation)
                except Exception as exc:  # tool failure isn't fatal — feed it back to LLM
                    observation = {"error": str(exc)[:300]}
                    obs_step = StepRecord(role="observation", content=observation)
                steps.append(obs_step)
                await self._emit(obs_step)
                _log_step(obs_step, tool=tool_name)
                messages.append({"role": "tool", "name": tool_name, "content": observation})
                continue

            # Unknown LLM item shape — record and bail out gracefully.
            err_step = StepRecord(
                role="error",
                content={"reason": "bad_llm_item", "item": item},
            )
            steps.append(err_step)
            await self._emit(err_step)
            _log_step(err_step)
            return AgentResult(
                status="failed",
                final_output=None,
                iterations=iterations,
                total_tokens=total_tokens,
                steps=steps,
                failure_reason="bad_llm_item",
            )

        # Loop exhausted — cap hit, no final answer.
        cap_step = StepRecord(
            role="error",
            content={"reason": "iter_limit", "max_iterations": agent.max_iterations},
        )
        steps.append(cap_step)
        await self._emit(cap_step)
        _log_step(cap_step)
        return AgentResult(
            status="failed",
            final_output=None,
            iterations=iterations,
            total_tokens=total_tokens,
            steps=steps,
            failure_reason="iter_limit",
        )
