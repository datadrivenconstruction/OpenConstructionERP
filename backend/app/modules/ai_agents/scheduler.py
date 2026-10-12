# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scheduled custom-agent runs (Item 29).

A custom agent can carry a 5-field POSIX cron expression in its
``automation`` envelope. The platform polls once a minute for agents whose
``automation.next_run_at`` is due and fires a real :class:`AgentRun` for each,
then advances ``next_run_at`` to the next cron occurrence.

Design choices (architecture guide "LIGHTWEIGHT & SIMPLE"):

* **No new dependency.** Cron parsing reuses the hand-rolled parser the
  reporting module already ships (:func:`app.modules.reporting.cron.next_occurrence`),
  rather than pulling in ``croniter`` and its transitive deps.
* **In-process asyncio loop**, exactly like the existing KPI / reports
  schedulers in ``main.py`` - no Celery, single-process is acceptable for the
  single-tenant deploy. The central app lifespan wires :func:`start_scheduler`.
* **UTC everywhere.** ``next_run_at`` is an ISO-8601 UTC string. Cron fields
  are interpreted in UTC (the reporting parser's contract).
* **Determinism.** A scheduled run is a normal agent run: it spawns through the
  same loop, persists steps, and never auto-applies its output. If the operator
  has no LLM configured the run simply records ``failure_reason="no_llm"`` like
  any manual run - no silent action is ever taken.

Firing a scheduled run reuses the service's :meth:`AgentService.start_run`
path; ``tagged`` metadata (``automation_trigger="schedule"``) is left for a
future monitoring item - for now the run is identifiable by its ``agent_name``
(``custom:<id>``) and that it was not initiated by a user request.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import uuid

from app.database import async_session_factory
from app.modules.ai_agents.service import AgentService

logger = logging.getLogger(__name__)

# How often the poll loop wakes. One minute matches the finest cron resolution
# (a per-minute field) and the cadence of the existing reports scheduler.
POLL_INTERVAL_SECONDS = 60

# Default prompt fired for a scheduled run when the operator did not pin a
# specific instruction. Kept generic and deterministic.
DEFAULT_SCHEDULE_INPUT = "Run your scheduled task and report the result."


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def compute_next_run_at(cron_expr: str, *, after: _dt.datetime | None = None) -> str:
    """Return the next UTC ISO-8601 occurrence of ``cron_expr`` strictly after ``after``.

    Delegates to the reporting module's POSIX cron parser. Raises
    :class:`app.modules.reporting.cron.CronParseError` on a malformed
    expression so callers can surface a 422.
    """
    from app.modules.reporting.cron import next_occurrence

    base = after or _utc_now()
    nxt = next_occurrence(cron_expr, base)
    return nxt.isoformat(timespec="seconds")


async def _fire_due_agent(
    service: AgentService,
    agent_id: uuid.UUID,
    agent_user_id: uuid.UUID,
    agent_agent_name: str,
    auto: dict,
    now: _dt.datetime,
) -> None:
    """Fire one due agent (identified by pre-snapshotted plain values).

    The caller snapshots every field BEFORE the loop: the first agent's
    ``update_metadata()`` / ``start_run()`` calls ``session.expire_all()``,
    after which reading an attribute off a still-unprocessed sibling ORM
    instance would emit an illegal lazy SELECT on the async session
    (``MissingGreenlet``) and silently skip every agent after the first.
    Passing plain values dodges the reload entirely.

    The schedule clock is advanced FIRST (and committed by the caller) so a run
    that crashes mid-flight cannot wedge the agent into firing every tick - the
    next occurrence is already pinned regardless of run outcome.
    """
    cron_expr = auto.get("cron")
    if not isinstance(cron_expr, str) or not cron_expr.strip():
        return

    # Advance the clock before running so a failure can't busy-loop the tick.
    try:
        auto["next_run_at"] = compute_next_run_at(cron_expr, after=now)
    except Exception:
        # Unparseable cron (should not happen - validated at setup). Disable
        # the schedule rather than re-evaluate a broken expression every minute.
        logger.exception("Disabling schedule for agent %s: bad cron %r", agent_id, cron_expr)
        auto["schedule_enabled"] = False
        auto["next_run_at"] = None
    await service.custom_repo.update_metadata(agent_id, auto)

    schedule_input = auto.get("schedule_input")
    user_input = (
        schedule_input.strip() if isinstance(schedule_input, str) and schedule_input.strip() else DEFAULT_SCHEDULE_INPUT
    )

    from app.core import cost_scope

    try:
        # The scheduler has no request around it; the run it starts belongs
        # to the agent's owner and reads cost items as that user.
        with cost_scope.caller_scope(agent_user_id):
            await service.start_run(
                user_id=agent_user_id,
                agent_name=agent_agent_name,
                user_input=user_input,
                trigger_source="schedule",
            )
    except Exception:
        # A run failure is recorded on its own AgentRun row by start_run; an
        # unexpected exception here (e.g. agent vanished) is logged and skipped
        # so one bad agent never stalls the whole tick.
        logger.exception("Scheduled run for agent %s failed to start", agent_id)


async def fire_due_runs(now: _dt.datetime | None = None) -> int:
    """Poll once: fire every custom agent whose schedule is due. Returns count fired.

    Opens its own session (the request session is long gone for a background
    poll). Each due agent's run is awaited sequentially to bound LLM concurrency
    on the single-process deploy.
    """
    now = now or _utc_now()
    fired = 0
    async with async_session_factory() as session:
        service = AgentService(session)
        due = await service.custom_repo.list_due_scheduled(now.isoformat(timespec="seconds"))
        # Snapshot every field needed for ALL due agents BEFORE the loop, while
        # each instance is still fresh from the query. The first
        # _fire_due_agent() expires the whole identity map
        # (update_metadata()/start_run() -> session.expire_all()), after which
        # reading agent.automation on a sibling would emit a lazy SELECT
        # (MissingGreenlet) and silently skip every agent after the first.
        snapshots = [
            (
                a.id,
                a.user_id,
                a.agent_name,
                dict(a.automation) if isinstance(a.automation, dict) else {},
            )
            for a in due
        ]
        for agent_id, agent_user_id, agent_agent_name, auto in snapshots:
            await _fire_due_agent(service, agent_id, agent_user_id, agent_agent_name, auto, now)
            fired += 1
        await session.commit()
    return fired


async def _scheduler_loop() -> None:
    """Forever-loop: tick every :data:`POLL_INTERVAL_SECONDS`. Never raises out."""
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            count = await fire_due_runs()
            if count:
                logger.info("ai_agents scheduler fired %d scheduled run(s)", count)
        except Exception:
            logger.exception("ai_agents scheduler tick failed")


def start_scheduler() -> asyncio.Task[None]:
    """Spawn the background poll loop as an asyncio task.

    Called once from the app lifespan (wired centrally in ``main.py``). Returns
    the task handle so the caller can keep a reference / cancel on shutdown.
    """
    return asyncio.create_task(_scheduler_loop())
