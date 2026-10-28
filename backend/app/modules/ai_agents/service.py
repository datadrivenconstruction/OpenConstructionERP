# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠AI Agents service - business logic for starting and inspecting runs.

The service is what wires the in-process :class:`AgentRunner` to:
    1. The DB-backed :class:`AgentRun` / :class:`AgentStep` persistence.
    2. The production LLM bridge (or whichever bridge the caller injects).
    3. The user's AI settings (provider + api_key + model id).

Tests instantiate the service with a custom LLM bridge to avoid hitting
external providers; production passes ``None`` and the service resolves
the bridge via :mod:`app.modules.ai.ai_client`.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_agents.base import (
    Agent,
    AgentResult,
    AgentRunner,
    LLMBridge,
    StepRecord,
    ToolRegistry,
    get_agent,
    global_tool_registry,
    list_agents,
)
from app.modules.ai_agents.models import (
    CUSTOM_AGENT_PREFIX,
    AgentRun,
    AgentStep,
    CustomAgent,
)
from app.modules.ai_agents.repository import (
    AgentRunRepository,
    AgentStepRepository,
    CustomAgentRepository,
)
from app.modules.ai_agents.triggers import (
    normalise_triggers,
    required_permission_for_tool,
)

logger = logging.getLogger(__name__)


class ToolPermissionError(Exception):
    """Raised when an operator selects a tool they lack the permission for.

    Carries the offending tool + the permission required so the router can
    return a precise 403 the UI can render ("you lack ``boq.create``").
    """

    def __init__(self, tool_name: str, permission: str) -> None:
        self.tool_name = tool_name
        self.permission = permission
        super().__init__(f"Missing permission '{permission}' for tool '{tool_name}'")


# Conservative caps for user-authored agents. They are prompt-only (no tools),
# so a single LLM turn is the normal path; the small loop cap is just a guard.
CUSTOM_AGENT_MAX_ITERATIONS = 3


def compile_guided_prompt(guided: dict[str, Any]) -> str:
    """Build a well-formed system prompt from the friendly guided-builder fields.

    A non-technical user never writes a raw prompt: they answer a few plain
    questions (role, goal, audience, output format, extra guidance) and this
    function assembles a coherent, instruction-style system prompt from
    whatever they filled in. Only ``goal`` is required; empty fields are
    skipped so a sparse spec still yields a clean prompt.

    The compiled prompt always ends with the platform's "assistant, not
    autopilot" guardrail (state assumptions, never fabricate project specifics)
    so user agents behave as safely as the built-in advisors.
    """
    role = (guided.get("role") or "").strip()
    goal = (guided.get("goal") or "").strip()
    audience = (guided.get("audience") or "").strip()
    output_format = (guided.get("output_format") or "").strip()
    extra = (guided.get("extra_guidance") or "").strip()

    parts: list[str] = []
    if role:
        parts.append(f"You are {role}.")
    else:
        parts.append("You are a knowledgeable construction assistant.")
    if goal:
        parts.append(f"Your job is to help with the following: {goal}")
    if audience:
        parts.append(f"Your answer is for: {audience}. Pitch it accordingly.")
    if output_format:
        parts.append(f"Present your answer like this: {output_format}.")
    if extra:
        parts.append(f"Also keep this in mind: {extra}")

    parts.append(
        "Be concrete and practical. State any assumptions explicitly. Do not "
        "invent project-specific facts, quantities, prices, names, or dates "
        "you were not given; where a real figure or a professional judgement "
        "is needed, ask for it or leave a clearly marked placeholder. The "
        "person you are helping will review and confirm your output."
    )
    return " ".join(parts)


def _resolve_system_prompt(
    *,
    guided: dict[str, Any] | None,
    raw_prompt: str,
) -> str:
    """Pick the effective system prompt for a custom agent.

    Guided spec wins (compiled); otherwise the raw prompt is used as-is. Raises
    ``ValueError`` when neither yields any prompt text so the API can 422.
    """
    if guided:
        compiled = compile_guided_prompt(guided)
        if compiled.strip():
            return compiled
    raw = (raw_prompt or "").strip()
    if raw:
        return raw
    msg = "A custom agent needs either a guided spec with a goal, or a system prompt."
    raise ValueError(msg)


def _runtime_allowed_tools(row: CustomAgent) -> list[str]:
    """Resolve the custom agent's vetted tool slugs to ones the runner knows.

    The operator's saved selection is intersected with the live tool registry
    so a tool that has since been removed from the platform is silently dropped
    (the runner would reject it anyway). An agent with no tools selected stays
    prompt-only.
    """
    selected = row.allowed_tools
    if not selected:
        return []
    available = set(global_tool_registry.names())
    return [name for name in selected if name in available]


def custom_agent_to_runtime(row: CustomAgent) -> Agent:
    """Project a DB :class:`CustomAgent` row into a runnable :class:`Agent`.

    The runner only ever sees a declarative :class:`Agent`. Custom agents are
    prompt-only by default, but an operator may grant the agent a vetted set of
    tools (Item 29) stored in ``automation.allowed_tools``; those are surfaced
    here so the ReAct loop can dispatch to them. Granting a tool already
    required the operator to hold that tool's permission (enforced in
    :meth:`AgentService.set_tools`), and the runner still re-verifies the
    invoking user's permission inside each privileged tool - so an agent never
    widens its creator's reach. When no tools are granted the loop returns the
    model's first answer. The runtime ``name`` is the ``custom:<id>`` slug so
    the run path and persisted ``AgentRun.agent_name`` round-trip unambiguously.
    """
    tools = _runtime_allowed_tools(row)
    return Agent(
        name=row.agent_name,
        display_name=row.display_name,
        description=row.description or row.tagline or "",
        tagline=row.tagline or "",
        category=row.category or "general",
        icon=row.icon or "sparkles",
        example_prompts=list(row.example_prompts or []),
        system_prompt=row.system_prompt,
        allowed_tools=tools,
        # A tool-using custom agent needs room for a few ReAct turns; a
        # prompt-only one still returns on the first answer. Give tool-backed
        # agents the standard built-in budget, prompt-only ones the tight cap.
        max_iterations=8 if tools else CUSTOM_AGENT_MAX_ITERATIONS,
    )


def _iso_now() -> str:
    """Wall-clock UTC ISO string (kept short to fit String(40))."""
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


async def _resolve_production_llm(session: AsyncSession, user_id: uuid.UUID) -> LLMBridge | None:
    """Pull the user's AI settings and build a :class:`CallAILLM` bridge.

    Returns ``None`` when no API key is configured - the caller decides
    whether that's a hard error (it is, for ``run_agent``).
    """
    try:
        from app.modules.ai.ai_client import resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository
        from app.modules.ai_agents.llm import CallAILLM
    except Exception as exc:  # pragma: no cover - import safety
        logger.warning("AI module unavailable for agent runner: %s", exc)
        return None

    settings = await AISettingsRepository(session).get_by_user_id(user_id)
    try:
        provider, api_key, model = resolve_provider_key_model(settings)
    except ValueError:
        return None
    return CallAILLM(provider=provider, api_key=api_key, model=model)


def _humanize_agent(name: str) -> str:
    """Turn an agent slug (``boq_generator``) into a label (``Boq Generator``)."""
    return name.replace("_", " ").replace("-", " ").strip().title() or "AI agent"


def _coerce_confidence(value: Any) -> float | None:
    """Normalise a confidence to the 0.0-1.0 range the UI expects.

    Agents emit confidence on either a 0-1 or a 0-100 scale; anything above 1
    is treated as a percentage and divided down. Non-numeric input yields None.
    """
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return None
    if conf > 1.0:
        conf = conf / 100.0
    return max(0.0, min(conf, 1.0))


def _run_to_insight(run: AgentRun) -> dict[str, Any]:
    """Distill one completed :class:`AgentRun` into a project-insight card.

    Structured JSON output (``{"title", "summary", "confidence", "severity"}``)
    is used directly; plain-text output falls back to the agent's humanised name
    as the title and its first line as the summary. This is real run output, not
    a placeholder.
    """
    raw = (run.final_output or "").strip()
    title: str | None = None
    summary: str | None = None
    confidence: float | None = None
    severity: str | None = None

    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            title = payload.get("title") or payload.get("headline")
            summary = payload.get("summary") or payload.get("message") or payload.get("recommendation")
            confidence = _coerce_confidence(payload.get("confidence"))
            sev = payload.get("severity")
            severity = str(sev) if sev is not None else None

    if not title:
        title = _humanize_agent(run.agent_name)
    if not summary:
        first_line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
        summary = (first_line[:200] + "...") if len(first_line) > 200 else (first_line or None)
    if severity is None:
        severity = "info"

    return {
        "id": str(run.id),
        "title": str(title)[:200],
        "summary": summary,
        "confidence": confidence,
        "severity": severity,
    }


class AgentService:
    """High-level façade over the runner + persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.run_repo = AgentRunRepository(session)
        self.step_repo = AgentStepRepository(session)
        self.custom_repo = CustomAgentRepository(session)

    # ── Catalogue ────────────────────────────────────────────────────────

    def list_registered_agents(self) -> list[Agent]:
        return list_agents()

    async def list_custom_agents(self, user_id: uuid.UUID) -> list[CustomAgent]:
        """Return the caller's user-authored custom agent rows (newest first)."""
        return await self.custom_repo.list_for_user(user_id)

    async def list_catalogue_agents(self, user_id: uuid.UUID) -> list[tuple[Agent, CustomAgent | None]]:
        """Built-in + the caller's custom agents, as ``(Agent, row|None)`` pairs.

        Built-ins come from the in-memory registry (``row`` is ``None``); the
        caller's custom agents are projected to runnable :class:`Agent`\\s with
        their DB row attached so the router can flag them ``is_custom`` and
        surface the row id for edit/delete. Custom agents come first so a
        user's own helpers sit at the top of the catalogue.
        """
        custom_rows = await self.custom_repo.list_for_user(user_id)
        pairs: list[tuple[Agent, CustomAgent | None]] = [(custom_agent_to_runtime(row), row) for row in custom_rows]
        pairs.extend((a, None) for a in list_agents())
        return pairs

    async def resolve_agent(self, agent_name: str, user_id: uuid.UUID) -> Agent | None:
        """Resolve a runtime :class:`Agent` by name for a given caller.

        ``custom:<id>`` slugs resolve from the DB (and only if the agent
        belongs to ``user_id`` - a user cannot run another user's custom
        agent); everything else resolves from the built-in registry.
        """
        if agent_name.startswith(CUSTOM_AGENT_PREFIX):
            raw_id = agent_name[len(CUSTOM_AGENT_PREFIX) :]
            try:
                custom_id = uuid.UUID(raw_id)
            except (ValueError, TypeError):
                return None
            row = await self.custom_repo.get_for_user(custom_id, user_id)
            return custom_agent_to_runtime(row) if row is not None else None
        return get_agent(agent_name)

    # ── Custom-agent CRUD ─────────────────────────────────────────────────

    async def create_custom_agent(
        self,
        *,
        user_id: uuid.UUID,
        display_name: str,
        tagline: str,
        description: str,
        category: str,
        icon: str,
        example_prompts: list[str],
        guided: dict[str, Any] | None,
        system_prompt: str,
    ) -> CustomAgent:
        """Create a custom agent for ``user_id``. Raises ValueError on no prompt."""
        effective_prompt = _resolve_system_prompt(guided=guided, raw_prompt=system_prompt)
        row = CustomAgent(
            user_id=user_id,
            display_name=display_name,
            tagline=tagline,
            description=description,
            category=category or "general",
            icon=icon or "sparkles",
            example_prompts=[p for p in example_prompts if p and p.strip()],
            guided=guided,
            system_prompt=effective_prompt,
        )
        return await self.custom_repo.create(row)

    async def get_custom_agent(self, agent_id: uuid.UUID, user_id: uuid.UUID) -> CustomAgent | None:
        return await self.custom_repo.get_for_user(agent_id, user_id)

    async def update_custom_agent(
        self,
        *,
        agent_id: uuid.UUID,
        user_id: uuid.UUID,
        display_name: str,
        tagline: str,
        description: str,
        category: str,
        icon: str,
        example_prompts: list[str],
        guided: dict[str, Any] | None,
        system_prompt: str,
    ) -> CustomAgent | None:
        """Full-replace an owned custom agent. Returns None when not found/owned."""
        row = await self.custom_repo.get_for_user(agent_id, user_id)
        if row is None:
            return None
        effective_prompt = _resolve_system_prompt(guided=guided, raw_prompt=system_prompt)
        return await self.custom_repo.update(
            row,
            display_name=display_name,
            tagline=tagline,
            description=description,
            category=category or "general",
            icon=icon or "sparkles",
            example_prompts=[p for p in example_prompts if p and p.strip()],
            guided=guided,
            system_prompt=effective_prompt,
        )

    async def delete_custom_agent(self, agent_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Delete an owned custom agent. Returns False when not found/owned."""
        row = await self.custom_repo.get_for_user(agent_id, user_id)
        if row is None:
            return False
        await self.custom_repo.delete(row)
        return True

    # ── Automation: schedule + tools + triggers (Item 29) ────────────────────

    @staticmethod
    def validate_cron(expr: str) -> str:
        """Validate (and normalise whitespace in) a 5-field POSIX cron string.

        Returns the normalised expression. Raises :class:`ValueError` on a
        malformed expression (the router maps this to a 422). Reuses the
        reporting module's parser so the supported grammar is identical to the
        scheduled-reports feature - no new dependency.
        """
        from app.modules.reporting.cron import CronParseError, parse_cron

        normalised = " ".join((expr or "").split())
        if not normalised:
            msg = "Cron expression is required."
            raise ValueError(msg)
        try:
            parse_cron(normalised)
        except CronParseError as exc:
            raise ValueError(str(exc)) from exc
        return normalised

    @staticmethod
    def _automation_dict(row: CustomAgent) -> dict[str, Any]:
        """Return a mutable copy of the agent's automation envelope."""
        return dict(row.automation) if isinstance(row.automation, dict) else {}

    async def get_agent_metadata(self, agent_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any] | None:
        """Return the current schedule/tools/triggers for an owned agent, or None.

        The shape mirrors :class:`schemas.AgentMetadataResponse`. Returns
        ``None`` when the agent is not found / not owned by the caller.
        """
        row = await self.custom_repo.get_for_user(agent_id, user_id)
        if row is None:
            return None
        auto = self._automation_dict(row)
        return {
            "cron": row.cron_expr,
            "schedule_enabled": row.schedule_enabled,
            "next_run_at": auto.get("next_run_at") if isinstance(auto.get("next_run_at"), str) else None,
            "schedule_input": auto.get("schedule_input") if isinstance(auto.get("schedule_input"), str) else "",
            "triggers": [str(t) for t in auto.get("triggers", []) if isinstance(t, str)],
            "allowed_tools": row.allowed_tools,
        }

    async def set_schedule(
        self,
        *,
        agent_id: uuid.UUID,
        user_id: uuid.UUID,
        cron_expr: str,
        enabled: bool = True,
        schedule_input: str = "",
        triggers: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Create/replace the schedule on an owned agent. Returns metadata or None.

        Validates the cron, computes ``next_run_at`` from now, and persists the
        merged automation envelope. ``None`` when the agent is not owned/found;
        raises :class:`ValueError` on a bad cron.
        """
        row = await self.custom_repo.get_for_user(agent_id, user_id)
        if row is None:
            return None
        normalised = self.validate_cron(cron_expr)
        from app.modules.ai_agents.scheduler import compute_next_run_at

        auto = self._automation_dict(row)
        auto["cron"] = normalised
        auto["schedule_enabled"] = bool(enabled)
        auto["schedule_input"] = (schedule_input or "").strip()
        if triggers is not None:
            auto["triggers"] = normalise_triggers(triggers)
        # Only schedule a future fire when enabled; a paused schedule keeps its
        # cron but has no pending occurrence.
        auto["next_run_at"] = compute_next_run_at(normalised) if enabled else None
        await self.custom_repo.update_metadata(agent_id, auto)
        return await self.get_agent_metadata(agent_id, user_id)

    async def set_triggers(
        self,
        *,
        agent_id: uuid.UUID,
        user_id: uuid.UUID,
        triggers: list[str],
    ) -> dict[str, Any] | None:
        """Replace the event-trigger subscriptions on an owned agent.

        Triggers fire the agent on a platform event (RFI created, document
        uploaded) independently of any cron schedule, so they are set through
        their own path rather than requiring a cron. Unknown trigger slugs are
        dropped silently (a stale frontend can never persist an inert trigger).
        ``None`` when the agent is not owned/found.
        """
        row = await self.custom_repo.get_for_user(agent_id, user_id)
        if row is None:
            return None
        auto = self._automation_dict(row)
        auto["triggers"] = normalise_triggers(triggers)
        await self.custom_repo.update_metadata(agent_id, auto)
        return await self.get_agent_metadata(agent_id, user_id)

    async def delete_schedule(self, agent_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Remove the schedule (cron + next_run_at) from an owned agent.

        Leaves any tool grant intact. Returns False when not found/owned.
        """
        row = await self.custom_repo.get_for_user(agent_id, user_id)
        if row is None:
            return False
        auto = self._automation_dict(row)
        auto.pop("cron", None)
        auto.pop("next_run_at", None)
        auto.pop("schedule_enabled", None)
        auto.pop("schedule_input", None)
        await self.custom_repo.update_metadata(agent_id, auto)
        return True

    async def set_tools(
        self,
        *,
        agent_id: uuid.UUID,
        user_id: uuid.UUID,
        tool_names: list[str],
        user_role: str,
    ) -> dict[str, Any] | None:
        """Grant a vetted set of tools to an owned agent. Returns metadata or None.

        Each requested tool must (a) exist in the live tool registry and (b) be
        one the operator already has permission to use - otherwise a
        :class:`ToolPermissionError` is raised (router → 403). Unknown tools are
        dropped silently. ``None`` when the agent is not owned/found.

        Permission is checked against the live registry using the operator's
        role, mirroring ``RequirePermission``'s stale-JWT fallback - so the
        grant honours the operator's CURRENT role, not a cached token.
        """
        row = await self.custom_repo.get_for_user(agent_id, user_id)
        if row is None:
            return None

        from app.core.permissions import permission_registry

        available = set(global_tool_registry.names())
        vetted: list[str] = []
        seen: set[str] = set()
        for raw in tool_names:
            name = (raw or "").strip()
            if not name or name in seen or name not in available:
                continue
            seen.add(name)
            required = required_permission_for_tool(name)
            if not permission_registry.role_has_permission(user_role, required):
                raise ToolPermissionError(name, required)
            vetted.append(name)

        auto = self._automation_dict(row)
        auto["allowed_tools"] = vetted
        await self.custom_repo.update_metadata(agent_id, auto)
        return await self.get_agent_metadata(agent_id, user_id)

    def list_available_tools_with_permissions(self) -> list[dict[str, Any]]:
        """List every runner tool plus the permission needed to grant it.

        Powers the builder's tool picker: the frontend shows each tool with its
        required permission so it can grey out tools the operator cannot grant.
        """
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "required_permission": required_permission_for_tool(t.name),
            }
            for t in global_tool_registry.all()
        ]

    def list_registered_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in global_tool_registry.all()
        ]

    # ── Run lifecycle ────────────────────────────────────────────────────

    async def start_run(
        self,
        *,
        user_id: uuid.UUID,
        agent_name: str,
        user_input: str,
        project_id: uuid.UUID | None = None,
        llm: LLMBridge | None = None,
        tool_registry: ToolRegistry | None = None,
        trigger_source: str = "manual",
    ) -> AgentRun:
        """Create the run row, execute the loop synchronously, and persist steps.

        "Background task" wiring (``BackgroundTasks.add_task``) lives in
        the router - here we just run the loop. The router can choose to
        ``await`` us inline (tests do) or schedule us for later.

        Resolves built-ins from the in-memory registry AND the caller's own
        custom agents (``custom:<id>`` slugs) from the DB, so the scheduler can
        fire a scheduled custom agent through this same path. Ownership for
        custom slugs is enforced in :meth:`resolve_agent`.

        ``trigger_source`` records how the run was initiated ("manual",
        "schedule", or "event:<name>") so the monitoring panel and audit trail
        can tell automated runs apart from user-initiated ones.
        """
        agent = get_agent(agent_name)
        if agent is None:
            agent = await self.resolve_agent(agent_name, user_id)
        if agent is None:
            msg = f"Unknown agent: {agent_name}"
            raise ValueError(msg)

        run = AgentRun(
            agent_name=agent_name,
            project_id=project_id,
            user_id=user_id,
            status="running",
            user_input=user_input,
            iterations=0,
            total_tokens=0,
            started_at=_iso_now(),
            trigger_source=trigger_source,
        )
        run = await self.run_repo.create(run)
        run_id = run.id

        # Resolve LLM bridge (caller may inject one for tests).
        bridge = llm
        if bridge is None:
            bridge = await _resolve_production_llm(self.session, user_id)
        if bridge is None:
            await self.run_repo.update_fields(
                run_id,
                status="failed",
                failure_reason="no_llm",
                finished_at=_iso_now(),
            )
            refreshed = await self.run_repo.get_by_id(run_id)
            assert refreshed is not None  # noqa: S101
            return refreshed

        step_counter = {"i": 0}

        async def _persist(step: StepRecord) -> None:
            step_counter["i"] += 1
            await self.step_repo.create(
                AgentStep(
                    run_id=run_id,
                    step_idx=step_counter["i"],
                    role=step.role,
                    content=step.content,
                    token_count=step.token_count,
                )
            )

        runner = AgentRunner(bridge, on_step=_persist)
        # Always thread the invoking user into the trusted runner context so
        # data-reading tools can re-verify per-call project access (the LLM
        # cannot forge this - the runner strips any model-supplied
        # __agent_context__ and re-injects this dict). project_id is added only
        # when a project is in scope.
        context: dict[str, str] = {"user_id": str(user_id)}
        if project_id:
            context["project_id"] = str(project_id)

        try:
            result: AgentResult = await runner.run(
                agent,
                user_input,
                context=context,
                tool_registry=tool_registry,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Agent run %s crashed", run_id)
            await self.run_repo.update_fields(
                run_id,
                status="failed",
                failure_reason="exception",
                final_output=str(exc)[:500],
                finished_at=_iso_now(),
            )
            refreshed = await self.run_repo.get_by_id(run_id)
            assert refreshed is not None  # noqa: S101
            return refreshed

        await self.run_repo.update_fields(
            run_id,
            status=result.status,
            failure_reason=result.failure_reason,
            final_output=result.final_output,
            trust=result.trust,
            iterations=result.iterations,
            total_tokens=result.total_tokens,
            finished_at=_iso_now(),
        )
        # An automated run (scheduler/event) has no user watching the page, so
        # surface a failure through the notifications module - otherwise a
        # silently-failing schedule is invisible. Manual runs already show the
        # failure inline on the timeline, so they are not notified.
        if trigger_source != "manual" and result.status == "failed":
            await self._notify_automated_failure(
                user_id=user_id,
                run_id=run_id,
                agent_name=agent_name,
                trigger_source=trigger_source,
                failure_reason=result.failure_reason,
            )
        refreshed = await self.run_repo.get_by_id(run_id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    async def _notify_automated_failure(
        self,
        *,
        user_id: uuid.UUID,
        run_id: uuid.UUID,
        agent_name: str,
        trigger_source: str,
        failure_reason: str | None,
    ) -> None:
        """Best-effort in-app notification when an automated run fails.

        Reuses the existing notifications module (no new channel). Swallows all
        errors: a notification hiccup must never break the run-recording path or
        wedge the scheduler tick.
        """
        try:
            from app.modules.notifications.service import NotificationService

            await NotificationService(self.session).create(
                user_id=user_id,
                notification_type="ai_agent_run_failed",
                title_key="notifications.ai_agent.run_failed.title",
                body_key="notifications.ai_agent.run_failed.body",
                body_context={
                    "agent": _humanize_agent(agent_name),
                    "reason": failure_reason or "unknown",
                    "trigger": trigger_source,
                },
                entity_type="ai_agent_run",
                entity_id=str(run_id),
                action_url=f"/ai-agents?run={run_id}",
            )
        except Exception:  # noqa: BLE001 - notification is best-effort
            logger.warning("Failed to notify automated-run failure for run %s", run_id, exc_info=True)

    # ── Read ─────────────────────────────────────────────────────────────

    async def get_run(self, run_id: uuid.UUID) -> AgentRun | None:
        return await self.run_repo.get_by_id(run_id)

    async def get_run_steps(self, run_id: uuid.UUID) -> list[AgentStep]:
        return await self.step_repo.list_for_run(run_id)

    async def list_runs(
        self,
        *,
        user_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        return await self.run_repo.list_runs(
            user_id=user_id,
            project_id=project_id,
            limit=limit,
        )

    async def list_automated_runs(self, *, user_id: uuid.UUID, limit: int = 50) -> list[AgentRun]:
        """Return the caller's automated (scheduler/event) runs, newest-first.

        Powers the AI-agents monitoring panel: which scheduled / event-fired
        runs happened, with their status, so a silently-failing schedule is
        visible.
        """
        return await self.run_repo.list_automated(user_id=user_id, limit=limit)

    async def project_insights(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        """Return the user's most recent useful AI results for a project.

        Only completed runs that produced output become insights, so we
        over-fetch recent runs and stop once ``limit`` real insights are
        collected. Scoped to the caller's own runs, mirroring the privacy
        model of the run-detail endpoint.
        """
        runs = await self.run_repo.list_runs(
            user_id=user_id,
            project_id=project_id,
            limit=max(limit * 5, 10),
        )
        insights: list[dict[str, Any]] = []
        for run in runs:
            if run.status != "completed" or not (run.final_output or "").strip():
                continue
            insights.append(_run_to_insight(run))
            if len(insights) >= limit:
                break
        return insights

    # ── BOQ proposals: extract + apply (human-confirmed) ──────────────────────

    async def get_run_proposals(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Return the structured BOQ-position proposals a run produced.

        The BOQ-drafter emits each line as a ``create_position`` observation
        during the loop, but the run's final answer is markdown - so the
        proposals would otherwise be lost. This recovers them from the persisted
        steps (with a JSON-final-output fallback) so the UI can offer a real
        "apply to BOQ" action instead of asking the user to re-type every line.

        Returns ``None`` when the run does not exist or is not owned by the
        caller (the router maps that to 404/403). When the run has no proposals
        the ``proposals`` list is empty - a valid "nothing to apply" state.
        """
        from app.modules.ai_agents.proposals import extract_proposals, proposal_currencies

        run = await self.run_repo.get_by_id(run_id)
        if run is None or str(run.user_id) != str(user_id):
            return None
        steps = await self.step_repo.list_for_run(run_id)
        proposals = extract_proposals(steps, run.final_output)
        currencies = sorted(proposal_currencies(proposals))
        return {
            "run_id": str(run_id),
            "project_id": str(run.project_id) if run.project_id else None,
            "count": len(proposals),
            "currencies": currencies,
            "mixed_currency": len(currencies) > 1,
            "proposals": [p.to_dict() for p in proposals],
        }

    async def apply_run_proposals(
        self,
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        boq_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Apply a run's BOQ-position proposals to ``boq_id`` as real positions.

        The human-confirmed half of the drafter flow: the user reviewed the
        proposals and chose a BOQ, so we create real positions through the BOQ
        module's own ``add_position`` (every invariant honoured) and tag each
        line back to the run. Currencies are never blended - an off-currency or
        un-priced line is skipped with a reason.

        Returns ``None`` when the run is not found / not owned by the caller,
        or when the target BOQ belongs to a project other than the run's own
        (the run's ``project_id`` is the sole authority for the target - the
        caller's active project must never override it; the router maps the
        ``None`` to 404). Raises :class:`ValueError` when the run has no
        proposals to apply (the router maps that to 422). The caller (router)
        is responsible for verifying the user's access to the project and for
        the commit.
        """
        from app.modules.ai_agents.proposals import (
            apply_proposals_to_boq,
            extract_proposals,
        )
        from app.modules.boq.service import BOQService

        run = await self.run_repo.get_by_id(run_id)
        if run is None or str(run.user_id) != str(user_id):
            return None

        boq_service = BOQService(self.session)

        # Project binding (defence in depth - the router enforces this too):
        # a run bound to a project may only be applied into a BOQ that lives in
        # that SAME project. Anything else (e.g. a BOQ in the caller's active
        # project) is refused so a run's output can never land in a foreign
        # project. ``None`` here maps to 404 at the router.
        if run.project_id is not None:
            target_boq = await boq_service.boq_repo.get_by_id(boq_id)
            if target_boq is None or str(target_boq.project_id) != str(run.project_id):
                return None

        steps = await self.step_repo.list_for_run(run_id)
        proposals = extract_proposals(steps, run.final_output)
        if not proposals:
            msg = "This run produced no BOQ position proposals to apply."
            raise ValueError(msg)

        project_currency = (await boq_service._resolve_project_currency(boq_id)) or ""  # noqa: SLF001

        outcome = await apply_proposals_to_boq(
            session=self.session,
            proposals=proposals,
            boq_id=boq_id,
            run_id=run_id,
            project_currency=project_currency,
        )
        return {
            "run_id": str(run_id),
            "boq_id": str(boq_id),
            "created": outcome.created,
            "skipped": outcome.skipped,
            "currency": outcome.currency,
            "created_ordinals": outcome.created_ordinals,
            "skipped_reasons": outcome.skipped_reasons,
        }
