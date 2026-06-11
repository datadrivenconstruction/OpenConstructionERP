"""AI Agents API routes.

Endpoints (mounted at ``/api/v1/ai-agents/`` by the module loader):

* ``GET    /agents/``            - registered agents (with allowed_tools)
* ``GET    /tools/``             - registered tools (debugging surface)
* ``POST   /runs/``              - start a new run (returns id immediately;
                                    loop runs in a background task)
* ``GET    /runs/``              - list runs (newest first; optional
                                    project_id filter)
* ``GET    /runs/{id}``          - full run snapshot incl. steps timeline
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
from app.modules.ai_agents.schemas import (
    CUSTOM_AGENT_CATEGORIES,
    AgentDescriptor,
    AgentHealthResponse,
    AgentInsightResponse,
    AgentMetadataResponse,
    AgentRunListItem,
    AgentRunResponse,
    AgentStepResponse,
    AgentToolsResponse,
    ApplyProposalsRequest,
    ApplyProposalsResponse,
    CreateAgentRunRequest,
    CustomAgentCreateRequest,
    CustomAgentResponse,
    CustomAgentUpdateRequest,
    EventTriggerDescriptor,
    GuidedAgentSpec,
    RunProposalsResponse,
    SetScheduleRequest,
    SetToolsRequest,
    SetTriggersRequest,
    ToolDescriptor,
    ToolWithPermission,
)
from app.modules.ai_agents.service import AgentService, ToolPermissionError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai_agents"])


# ── Idempotency cache ────────────────────────────────────────────────────
# In-memory map of ``(user_id, idempotency_key) -> (run_id, created_ts)``.
# Purpose: protect agent runs from frontend retry storms / duplicate
# submits - each agent run costs real LLM dollars, so re-running on a
# transient network blip would burn cash silently. Entries expire after
# IDEMPOTENCY_TTL_SECONDS.
#
# Single-process scope is acceptable for now (single-tenant VPS deploy);
# multi-instance prod needs Redis/DB backing so the dedupe holds across
# workers - see needs_shared_change. Until then the cache is bounded both
# by TTL and a hard entry cap so a key recorded-but-never-looked-up again
# can't accumulate for the process lifetime.
IDEMPOTENCY_TTL_SECONDS = 600  # 10 minutes
IDEMPOTENCY_MAX_ENTRIES = 10_000
# ``OrderedDict`` keeps insertion order so we can drop the oldest entries
# in O(1) when the hard cap is hit (FIFO eviction).
_IDEMPOTENCY_CACHE: OrderedDict[tuple[str, str], tuple[uuid.UUID, float]] = OrderedDict()


def _sweep_stale(now: float) -> None:
    """Drop every entry older than the TTL (cheap; cache is small)."""
    stale = [k for k, (_, ts) in _IDEMPOTENCY_CACHE.items() if now - ts > IDEMPOTENCY_TTL_SECONDS]
    for k in stale:
        _IDEMPOTENCY_CACHE.pop(k, None)


def _idempotency_lookup(user_id: str, key: str) -> uuid.UUID | None:
    """Return the cached run_id for this user+key, or None if absent/expired."""
    _sweep_stale(time.monotonic())
    entry = _IDEMPOTENCY_CACHE.get((user_id, key))
    if entry is None:
        return None
    return entry[0]


def _idempotency_record(user_id: str, key: str, run_id: uuid.UUID) -> None:
    """Record a key→run mapping, bounding growth by TTL sweep + size cap.

    Without an eviction path on *write*, keys that are recorded but never
    looked up again (the common case - a retry rarely arrives) would
    accumulate for the whole process lifetime. We sweep expired entries
    first, then enforce a hard FIFO cap so the cache can never grow
    unbounded even under a flood of unique keys.
    """
    now = time.monotonic()
    _sweep_stale(now)
    cache_key = (user_id, key)
    # Refresh ordering on overwrite so the most recently written key is
    # treated as newest for FIFO eviction.
    _IDEMPOTENCY_CACHE.pop(cache_key, None)
    _IDEMPOTENCY_CACHE[cache_key] = (run_id, now)
    while len(_IDEMPOTENCY_CACHE) > IDEMPOTENCY_MAX_ENTRIES:
        _IDEMPOTENCY_CACHE.popitem(last=False)  # drop oldest


def _get_service(session: SessionDep) -> AgentService:
    return AgentService(session)


async def _assert_project_access(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Raise 404/403 unless ``user_id`` owns or is a member of ``project_id``.

    Mirrors the BOQ module's guard: 404 when the project doesn't exist (so
    we never confirm/deny existence of a project the caller can't see), 403
    when it exists but the caller is neither owner nor a team member.
    """
    from app.modules.projects.repository import ProjectRepository
    from app.modules.teams.access import is_project_member

    project = await ProjectRepository(session).get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    if str(project.owner_id) == str(user_id):
        return
    if await is_project_member(session, project_id, user_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this project",
    )


# ── Agent / tool catalogues ──────────────────────────────────────────────


@router.get(
    "/agents/",
    response_model=list[AgentDescriptor],
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def list_agents_endpoint(
    user_id: CurrentUserId,
    service: AgentService = Depends(_get_service),
) -> list[AgentDescriptor]:
    """List every agent the caller can run - built-ins plus their own custom agents.

    Custom agents are flagged ``is_custom`` (with their ``custom_id``) so the UI
    can show edit/delete affordances only on the caller's own creations.
    """
    uid = uuid.UUID(user_id)
    pairs = await service.list_catalogue_agents(uid)
    return [
        AgentDescriptor(
            name=a.name,
            description=a.description,
            system_prompt=a.system_prompt,
            max_iterations=a.max_iterations,
            allowed_tools=a.allowed_tools,
            display_name=a.display_name,
            category=a.category,
            icon=a.icon,
            tagline=a.tagline,
            example_prompts=a.example_prompts,
            is_custom=row is not None,
            custom_id=row.id if row is not None else None,
        )
        for (a, row) in pairs
    ]


@router.get(
    "/tools/",
    response_model=list[ToolDescriptor],
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def list_tools_endpoint(
    service: AgentService = Depends(_get_service),
) -> list[ToolDescriptor]:
    """List every tool the runner can dispatch to."""
    return [ToolDescriptor(**t) for t in service.list_registered_tools()]


# ── Custom agents (user-authored) ─────────────────────────────────────────


def _validate_category(category: str) -> str:
    """Clamp a custom agent's category to a known catalogue group.

    An unknown category would render as a lone "General"-style section; folding
    it to ``general`` keeps the catalogue tidy without rejecting the request.
    """
    cat = (category or "general").strip().lower()
    return cat if cat in CUSTOM_AGENT_CATEGORIES else "general"


def _serialise_custom_agent(row: Any) -> CustomAgentResponse:
    """Convert a CustomAgent ORM row to its response schema."""
    guided = GuidedAgentSpec(**row.guided) if isinstance(row.guided, dict) and row.guided else None
    return CustomAgentResponse(
        id=row.id,
        user_id=row.user_id,
        display_name=row.display_name,
        tagline=row.tagline or "",
        description=row.description or "",
        category=row.category or "general",
        icon=row.icon or "sparkles",
        example_prompts=list(row.example_prompts or []),
        system_prompt=row.system_prompt or "",
        guided=guided,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/custom/",
    response_model=list[CustomAgentResponse],
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def list_custom_agents(
    user_id: CurrentUserId,
    service: AgentService = Depends(_get_service),
) -> list[CustomAgentResponse]:
    """List the caller's own custom agents (for the manage/edit surface)."""
    uid = uuid.UUID(user_id)
    rows = await service.list_custom_agents(uid)
    return [_serialise_custom_agent(r) for r in rows]


@router.post(
    "/custom/",
    response_model=CustomAgentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("ai_agents.run"))],
)
async def create_custom_agent(
    request: CustomAgentCreateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AgentService = Depends(_get_service),
) -> CustomAgentResponse:
    """Create a user-authored agent.

    The agent appears in the caller's catalogue alongside the built-ins and is
    runnable through the same ``POST /runs/`` path (its run name is
    ``custom:<id>``). Creating an agent needs the same ``ai_agents.run``
    permission as running one (an editor right), so a viewer cannot author
    agents.
    """
    uid = uuid.UUID(user_id)
    try:
        row = await service.create_custom_agent(
            user_id=uid,
            display_name=request.display_name,
            tagline=request.tagline,
            description=request.description,
            category=_validate_category(request.category),
            icon=request.icon or "sparkles",
            example_prompts=request.example_prompts,
            guided=request.guided.model_dump() if request.guided else None,
            system_prompt=request.system_prompt,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    await session.commit()
    return _serialise_custom_agent(row)


@router.get(
    "/custom/{agent_id}",
    response_model=CustomAgentResponse,
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def get_custom_agent(
    agent_id: uuid.UUID,
    user_id: CurrentUserId,
    service: AgentService = Depends(_get_service),
) -> CustomAgentResponse:
    """Fetch one of the caller's custom agents (to populate the edit form)."""
    uid = uuid.UUID(user_id)
    row = await service.get_custom_agent(agent_id, uid)
    if row is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    return _serialise_custom_agent(row)


@router.put(
    "/custom/{agent_id}",
    response_model=CustomAgentResponse,
    dependencies=[Depends(RequirePermission("ai_agents.run"))],
)
async def update_custom_agent(
    agent_id: uuid.UUID,
    request: CustomAgentUpdateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AgentService = Depends(_get_service),
) -> CustomAgentResponse:
    """Replace one of the caller's custom agents. 404 unless owned by caller."""
    uid = uuid.UUID(user_id)
    try:
        row = await service.update_custom_agent(
            agent_id=agent_id,
            user_id=uid,
            display_name=request.display_name,
            tagline=request.tagline,
            description=request.description,
            category=_validate_category(request.category),
            icon=request.icon or "sparkles",
            example_prompts=request.example_prompts,
            guided=request.guided.model_dump() if request.guided else None,
            system_prompt=request.system_prompt,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    await session.commit()
    return _serialise_custom_agent(row)


@router.delete(
    "/custom/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("ai_agents.run"))],
)
async def delete_custom_agent(
    agent_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AgentService = Depends(_get_service),
) -> None:
    """Delete one of the caller's custom agents. 404 unless owned by caller."""
    uid = uuid.UUID(user_id)
    deleted = await service.delete_custom_agent(agent_id, uid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    await session.commit()


# ── Automation: schedule + tools + triggers (Item 29) ──────────────────────


@router.get(
    "/triggers/",
    response_model=list[EventTriggerDescriptor],
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def list_event_triggers_endpoint() -> list[EventTriggerDescriptor]:
    """List the platform events a custom agent may subscribe to.

    The catalogue is static (no DB). ``available`` is ``False`` for events whose
    firing wiring is not yet live, so the builder can label them "coming soon".
    """
    from app.modules.ai_agents.triggers import list_event_triggers

    return [EventTriggerDescriptor(**t) for t in list_event_triggers()]


@router.get(
    "/grantable-tools/",
    response_model=list[ToolWithPermission],
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def list_grantable_tools_endpoint(
    service: AgentService = Depends(_get_service),
) -> list[ToolWithPermission]:
    """List every runner tool plus the permission needed to grant it.

    Powers the builder's tool picker before the agent has an id (the create
    flow), so it does not require an ``agent_id`` like ``GET /custom/{id}/tools``.
    """
    return [ToolWithPermission(**t) for t in service.list_available_tools_with_permissions()]


@router.get(
    "/custom/{agent_id}/schedule",
    response_model=AgentMetadataResponse,
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def get_schedule_endpoint(
    agent_id: uuid.UUID,
    user_id: CurrentUserId,
    service: AgentService = Depends(_get_service),
) -> AgentMetadataResponse:
    """Fetch the schedule + tools + triggers for one of the caller's agents."""
    uid = uuid.UUID(user_id)
    meta = await service.get_agent_metadata(agent_id, uid)
    if meta is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    return AgentMetadataResponse(**meta)


@router.post(
    "/custom/{agent_id}/schedule",
    response_model=AgentMetadataResponse,
    dependencies=[Depends(RequirePermission("ai_agents.run"))],
)
async def set_schedule_endpoint(
    agent_id: uuid.UUID,
    request: SetScheduleRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AgentService = Depends(_get_service),
) -> AgentMetadataResponse:
    """Create/replace the cron schedule on one of the caller's agents.

    The agent will then run automatically at the cron times (UTC). A scheduled
    run is a normal agent run: it never auto-applies its output. 422 on a
    malformed cron; 404 unless the agent is owned by the caller.
    """
    uid = uuid.UUID(user_id)
    try:
        meta = await service.set_schedule(
            agent_id=agent_id,
            user_id=uid,
            cron_expr=request.cron_expr,
            enabled=request.enabled,
            schedule_input=request.schedule_input,
            triggers=request.triggers,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if meta is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    await session.commit()
    return AgentMetadataResponse(**meta)


@router.delete(
    "/custom/{agent_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("ai_agents.run"))],
)
async def delete_schedule_endpoint(
    agent_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AgentService = Depends(_get_service),
) -> None:
    """Remove the schedule (the agent stops running automatically). Tools kept."""
    uid = uuid.UUID(user_id)
    removed = await service.delete_schedule(agent_id, uid)
    if not removed:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    await session.commit()


@router.post(
    "/custom/{agent_id}/triggers",
    response_model=AgentMetadataResponse,
    dependencies=[Depends(RequirePermission("ai_agents.run"))],
)
async def set_triggers_endpoint(
    agent_id: uuid.UUID,
    request: SetTriggersRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AgentService = Depends(_get_service),
) -> AgentMetadataResponse:
    """Subscribe one of the caller's agents to platform events.

    The agent then runs automatically when a subscribed event fires (e.g. an RFI
    is created). An event-fired run is a normal run and never auto-applies its
    output. 404 unless the agent is owned by the caller.
    """
    uid = uuid.UUID(user_id)
    meta = await service.set_triggers(agent_id=agent_id, user_id=uid, triggers=request.triggers)
    if meta is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    await session.commit()
    return AgentMetadataResponse(**meta)


@router.get(
    "/custom/{agent_id}/tools",
    response_model=AgentToolsResponse,
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def get_tools_endpoint(
    agent_id: uuid.UUID,
    user_id: CurrentUserId,
    service: AgentService = Depends(_get_service),
) -> AgentToolsResponse:
    """Return the full tool catalogue + the agent's current grant.

    The catalogue carries each tool's ``required_permission`` so the picker can
    grey out tools the operator cannot grant.
    """
    uid = uuid.UUID(user_id)
    meta = await service.get_agent_metadata(agent_id, uid)
    if meta is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    available = [ToolWithPermission(**t) for t in service.list_available_tools_with_permissions()]
    return AgentToolsResponse(available=available, selected=meta["allowed_tools"])


@router.post(
    "/custom/{agent_id}/tools",
    response_model=AgentMetadataResponse,
    dependencies=[Depends(RequirePermission("ai_agents.run"))],
)
async def set_tools_endpoint(
    agent_id: uuid.UUID,
    request: SetToolsRequest,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AgentService = Depends(_get_service),
) -> AgentMetadataResponse:
    """Grant a vetted set of tools to one of the caller's agents.

    Each tool the caller selects must be one they already have permission to
    use (the agent never widens its creator's reach). 403 with the offending
    tool + missing permission otherwise; 404 unless owned by the caller.
    """
    uid = uuid.UUID(str(payload.get("sub")))
    role = str(payload.get("role", ""))
    try:
        meta = await service.set_tools(
            agent_id=agent_id,
            user_id=uid,
            tool_names=request.allowed_tools,
            user_role=role,
        )
    except ToolPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": f"You do not have permission to grant the tool '{exc.tool_name}'.",
                "tool": exc.tool_name,
                "required_permission": exc.permission,
            },
        ) from exc
    if meta is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    await session.commit()
    return AgentMetadataResponse(**meta)


@router.get(
    "/health/",
    response_model=AgentHealthResponse,
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def agents_health(
    user_id: CurrentUserId,
    session: SessionDep,
) -> AgentHealthResponse:
    """Cheap pre-flight: does the caller have a usable LLM provider?

    The Agents page polls this on mount so it can warn before the user
    spends a turn writing a prompt only to get a cryptic ``no_llm`` row
    on the runs timeline. We resolve provider/key/model exactly the way
    ``_resolve_production_llm`` does, but never instantiate the bridge.
    """
    uid = uuid.UUID(user_id)
    try:
        from app.modules.ai.ai_client import resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository
    except Exception:  # pragma: no cover - import safety
        return AgentHealthResponse(llm_configured=False)

    settings = await AISettingsRepository(session).get_by_user_id(uid)
    try:
        provider, _api_key, model = resolve_provider_key_model(settings)
    except ValueError:
        return AgentHealthResponse(llm_configured=False)
    return AgentHealthResponse(
        llm_configured=True,
        provider=provider,
        model=model,
    )


# ── Run lifecycle ────────────────────────────────────────────────────────


async def _run_in_background(
    *,
    user_id: uuid.UUID,
    agent_name: str,
    user_input: str,
    project_id: uuid.UUID | None,
    run_id: uuid.UUID,
) -> None:
    """Background-task entry point - opens its own session.

    The FastAPI-supplied session is gone by the time the background
    task runs (the response has already been returned to the client),
    so we open a fresh session bound to the same async engine.
    """
    async with async_session_factory() as bg_session:
        try:
            service = AgentService(bg_session)
            # The run row already exists (created in the foreground); we
            # just resume the loop by calling start_run-equivalent logic.
            # Simplest path: reuse start_run but it would create a second
            # row. Instead we go a level deeper and drive the runner here.
            from app.modules.ai_agents.base import AgentRunner, StepRecord
            from app.modules.ai_agents.models import AgentStep
            from app.modules.ai_agents.service import _iso_now, _resolve_production_llm

            # Resolve built-in OR the caller's own custom agent. Ownership for
            # custom:<id> slugs is enforced in resolve_agent.
            target = await service.resolve_agent(agent_name, user_id)
            if target is None:
                await service.run_repo.update_fields(
                    run_id,
                    status="failed",
                    failure_reason="unknown_agent",
                    finished_at=_iso_now(),
                )
                await bg_session.commit()
                return

            bridge = await _resolve_production_llm(bg_session, user_id)
            if bridge is None:
                await service.run_repo.update_fields(
                    run_id,
                    status="failed",
                    failure_reason="no_llm",
                    finished_at=_iso_now(),
                )
                await bg_session.commit()
                return

            step_counter = {"i": 0}

            async def _persist(step: StepRecord) -> None:
                step_counter["i"] += 1
                await service.step_repo.create(
                    AgentStep(
                        run_id=run_id,
                        step_idx=step_counter["i"],
                        role=step.role,
                        content=step.content,
                        token_count=step.token_count,
                    )
                )
                await bg_session.commit()

            runner = AgentRunner(bridge, on_step=_persist)
            context = {"project_id": str(project_id)} if project_id else None
            result = await runner.run(target, user_input, context=context)

            await service.run_repo.update_fields(
                run_id,
                status=result.status,
                failure_reason=result.failure_reason,
                final_output=result.final_output,
                iterations=result.iterations,
                total_tokens=result.total_tokens,
                finished_at=_iso_now(),
            )
            await bg_session.commit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Background agent run %s crashed", run_id)
            try:
                from app.modules.ai_agents.repository import AgentRunRepository
                from app.modules.ai_agents.service import _iso_now

                await AgentRunRepository(bg_session).update_fields(
                    run_id,
                    status="failed",
                    failure_reason="exception",
                    final_output=str(exc)[:500],
                    finished_at=_iso_now(),
                )
                await bg_session.commit()
            except Exception:
                pass


@router.post(
    "/runs/",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("ai_agents.run"))],
)
async def create_run(
    request: CreateAgentRunRequest,
    background_tasks: BackgroundTasks,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AgentService = Depends(_get_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AgentRunResponse:
    """Start a new run.

    Returns immediately after persisting a ``running`` row; the agent
    loop continues in a FastAPI background task. Poll
    ``GET /runs/{id}`` for progress (the steps timeline updates as
    the loop emits each step).

    Idempotency: clients may pass ``Idempotency-Key`` header to make
    retries safe. Submitting the same key within 10 minutes returns the
    original run instead of spawning a duplicate (agent runs cost real
    LLM dollars - never let a retry storm double-spend).
    """
    uid = uuid.UUID(user_id)

    # Defense-in-depth: a run may be tagged to a project, so verify the
    # caller actually has access to it before persisting the row. Without
    # this a user could tag runs to projects they don't own. Owner OR team
    # member is allowed (same rule the BOQ module uses).
    if request.project_id is not None:
        await _assert_project_access(session, request.project_id, uid)

    # Idempotency replay: return existing run for the same key within TTL.
    if idempotency_key:
        existing_run_id = _idempotency_lookup(user_id, idempotency_key)
        if existing_run_id is not None:
            existing = await service.get_run(existing_run_id)
            if existing is not None and str(existing.user_id) == user_id:
                steps = await service.get_run_steps(existing_run_id)
                return _serialise_run(existing, steps=steps)

    # Validate that the agent exists (built-in OR the caller's own custom
    # agent) before creating the row. resolve_agent enforces ownership for
    # custom:<id> slugs, so a user can never start a run for another user's
    # custom agent.
    if (await service.resolve_agent(request.agent_name, uid)) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown agent: {request.agent_name}",
        )

    from app.modules.ai_agents.models import AgentRun
    from app.modules.ai_agents.service import _iso_now

    run = AgentRun(
        agent_name=request.agent_name,
        project_id=request.project_id,
        user_id=uid,
        status="running",
        user_input=request.user_input,
        started_at=_iso_now(),
    )
    run = await service.run_repo.create(run)
    await session.commit()

    if idempotency_key:
        _idempotency_record(user_id, idempotency_key, run.id)

    background_tasks.add_task(
        _run_in_background,
        user_id=uid,
        agent_name=request.agent_name,
        user_input=request.user_input,
        project_id=request.project_id,
        run_id=run.id,
    )

    return _serialise_run(run, steps=[])


@router.get(
    "/runs/",
    response_model=list[AgentRunListItem],
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def list_runs(
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    service: AgentService = Depends(_get_service),
) -> list[AgentRunListItem]:
    """List the caller's recent runs. ``project_id`` optionally narrows.

    ``limit`` is clamped to 1..200 so a caller can't request an unbounded
    result set (?limit=1000000) and blow up the payload.
    """
    uid = uuid.UUID(user_id)
    runs = await service.list_runs(user_id=uid, project_id=project_id, limit=limit)
    return [AgentRunListItem.model_validate(r) for r in runs]


@router.get(
    "/runs/automated",
    response_model=list[AgentRunListItem],
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def list_automated_runs(
    user_id: CurrentUserId,
    limit: int = Query(50, ge=1, le=200),
    service: AgentService = Depends(_get_service),
) -> list[AgentRunListItem]:
    """List the caller's automated runs (scheduler / event-fired), newest-first.

    Powers the monitoring panel so an operator can see when their scheduled or
    event-triggered agents ran and whether any failed - automated runs have no
    user watching the timeline live. Registered before ``/runs/{run_id}`` so the
    literal ``automated`` path is not captured by the UUID path parameter.
    """
    uid = uuid.UUID(user_id)
    runs = await service.list_automated_runs(user_id=uid, limit=limit)
    return [AgentRunListItem.model_validate(r) for r in runs]


@router.get(
    "/insights",
    response_model=list[AgentInsightResponse],
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def project_insights(
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(..., description="Project to surface insights for"),
    limit: int = Query(2, ge=1, le=50),
    service: AgentService = Depends(_get_service),
) -> list[AgentInsightResponse]:
    """Recent AI insights for a project, distilled from the caller's runs.

    Powers the project-dashboard "AI insights" widget. Returns an empty list
    (not an error) when the user has not run any agents against the project,
    so the widget shows its empty state rather than failing.
    """
    uid = uuid.UUID(user_id)
    items = await service.project_insights(user_id=uid, project_id=project_id, limit=limit)
    return [AgentInsightResponse.model_validate(i) for i in items]


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunResponse,
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def get_run(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    service: AgentService = Depends(_get_service),
) -> AgentRunResponse:
    """Return the full run incl. ordered steps timeline."""
    uid = uuid.UUID(user_id)
    run = await service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if str(run.user_id) != str(uid):
        raise HTTPException(status_code=403, detail="You can only view your own runs")
    steps = await service.get_run_steps(run_id)
    return _serialise_run(run, steps=steps)


# ── BOQ proposals: extract + apply (human-confirmed) ──────────────────────


@router.get(
    "/runs/{run_id}/proposals",
    response_model=RunProposalsResponse,
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def get_run_proposals(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    service: AgentService = Depends(_get_service),
) -> RunProposalsResponse:
    """Return the structured BOQ-position proposals a completed run produced.

    The drafter emits each line as a ``create_position`` observation during the
    loop, but the run's final answer is markdown - so the proposals would
    otherwise be lost. This recovers them so the UI can offer a real
    "apply to BOQ" action. An empty ``proposals`` list is a valid
    "nothing to apply" state (the run was advisory, not a draft).
    """
    uid = uuid.UUID(user_id)
    payload = await service.get_run_proposals(run_id=run_id, user_id=uid)
    if payload is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunProposalsResponse(**payload)


@router.post(
    "/runs/{run_id}/apply",
    response_model=ApplyProposalsResponse,
    dependencies=[
        Depends(RequirePermission("ai_agents.run")),
        Depends(RequirePermission("boq.create")),
    ],
)
async def apply_run_proposals(
    run_id: uuid.UUID,
    request: ApplyProposalsRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AgentService = Depends(_get_service),
) -> ApplyProposalsResponse:
    """Apply a completed run's BOQ proposals to a BOQ as real positions.

    The human-confirmed step: the user reviewed the proposals and chose the
    target BOQ. We create real positions through the BOQ module's own service
    (so locking, ordinal uniqueness, totals and provenance all behave exactly
    as a manual add) and tag each line back to the run. Currencies are never
    blended - off-currency or un-priced lines are skipped with a reason.

    403 unless the caller can access the BOQ's project; 404 when the run or BOQ
    does not exist; 422 when the run produced no proposals.
    """
    uid = uuid.UUID(user_id)

    # Resolve the BOQ and verify project access BEFORE doing any work, so a
    # caller can never apply proposals into a project they cannot see.
    from app.modules.boq.service import BOQService

    boq_service = BOQService(session)
    try:
        boq = await boq_service.get_boq(request.boq_id)
    except HTTPException:
        raise
    if boq is None:
        raise HTTPException(status_code=404, detail="BOQ not found")
    await _assert_project_access(session, boq.project_id, uid)

    try:
        result = await service.apply_run_proposals(
            run_id=run_id,
            user_id=uid,
            boq_id=request.boq_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await session.commit()
    return ApplyProposalsResponse(**result)


# ── Serialisation helper ─────────────────────────────────────────────────


def _serialise_run(run: Any, *, steps: list[Any]) -> AgentRunResponse:
    """Convert ORM models to the response schema."""
    return AgentRunResponse(
        id=run.id,
        agent_name=run.agent_name,
        project_id=run.project_id,
        user_id=run.user_id,
        status=run.status,
        trigger_source=getattr(run, "trigger_source", "manual") or "manual",
        failure_reason=run.failure_reason,
        user_input=run.user_input,
        final_output=run.final_output,
        iterations=run.iterations,
        total_tokens=run.total_tokens,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[AgentStepResponse.model_validate(s) for s in steps],
    )


# Silence "imported but unused" - kept for type imports used at runtime.
_ = AsyncSession
