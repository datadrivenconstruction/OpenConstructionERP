# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠AI Agents data-access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.ai_agents.models import AgentRun, AgentStep, CustomAgent


def _row_trigger_names(row: CustomAgent) -> set[str]:
    """Extract the set of event-trigger slugs from a custom agent's envelope."""
    auto = row.automation if isinstance(row.automation, dict) else {}
    triggers = auto.get("triggers")
    if not isinstance(triggers, list):
        return set()
    return {str(t) for t in triggers}


class AgentRunRepository:
    """CRUD-style helpers for :class:`AgentRun`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, run: AgentRun) -> AgentRun:
        """Insert a new run row and flush so it has an id."""
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> AgentRun | None:
        stmt = select(AgentRun).where(AgentRun.id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_runs(
        self,
        *,
        user_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        """Return runs ordered newest-first, scoped by user/project."""
        stmt = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
        if user_id is not None:
            stmt = stmt.where(AgentRun.user_id == user_id)
        if project_id is not None:
            stmt = stmt.where(AgentRun.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_automated(
        self,
        *,
        user_id: uuid.UUID,
        limit: int = 50,
    ) -> list[AgentRun]:
        """Return the caller's automated runs (scheduler/event), newest-first.

        A run is automated when its ``trigger_source`` is anything other than
        ``"manual"``. Powers the monitoring panel so the operator can see when
        their scheduled / event-fired agents ran and whether any failed.
        """
        stmt = (
            select(AgentRun)
            .where(AgentRun.user_id == user_id, AgentRun.trigger_source != "manual")
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def update_fields(self, run_id: uuid.UUID, **fields: object) -> None:
        """Patch arbitrary scalar fields on a run row."""
        stmt = update(AgentRun).where(AgentRun.id == run_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(AgentRun, run_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)


class AgentStepRepository:
    """CRUD-style helpers for :class:`AgentStep`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, step: AgentStep) -> AgentStep:
        self.session.add(step)
        await self.session.flush()
        return step

    async def list_for_run(self, run_id: uuid.UUID) -> list[AgentStep]:
        """Return every step for a run in chronological order."""
        stmt = select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.step_idx.asc())
        return list((await self.session.execute(stmt)).scalars().all())


class CustomAgentRepository:
    """CRUD helpers for user-authored :class:`CustomAgent` rows.

    Every read is scoped by ``user_id`` so a caller can only ever see, run,
    edit, or delete their own custom agents (per-user privacy model shared
    with agent runs).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, agent: CustomAgent) -> CustomAgent:
        self.session.add(agent)
        await self.session.flush()
        return agent

    async def get_for_user(self, agent_id: uuid.UUID, user_id: uuid.UUID) -> CustomAgent | None:
        """Return the custom agent if it exists AND belongs to ``user_id``."""
        stmt = select(CustomAgent).where(
            CustomAgent.id == agent_id,
            CustomAgent.user_id == user_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[CustomAgent]:
        """Return the caller's custom agents, newest first."""
        stmt = select(CustomAgent).where(CustomAgent.user_id == user_id).order_by(CustomAgent.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def update(self, agent: CustomAgent, **fields: object) -> CustomAgent:
        """Patch scalar fields on an owned custom agent and flush."""
        for key, value in fields.items():
            setattr(agent, key, value)
        await self.session.flush()
        return agent

    async def update_metadata(self, agent_id: uuid.UUID, automation: dict) -> None:  # type: ignore[type-arg]
        """Replace the whole ``automation`` JSON envelope on a custom agent.

        Used by the scheduler and the schedule/tools endpoints. The caller owns
        merge semantics (read-modify-write the dict, then pass the full value)
        so a partial knob update never clobbers a sibling key. Expires the
        identity map so a subsequent load re-reads the persisted value.
        """
        stmt = update(CustomAgent).where(CustomAgent.id == agent_id).values(automation=automation)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def list_subscribed_to_trigger(self, trigger_name: str) -> list[CustomAgent]:
        """Return every custom agent subscribed to a platform event ``trigger_name``.

        A row is subscribed when ``trigger_name`` appears in its ``automation``
        envelope's ``triggers`` JSON array. Scoped across all users by design:
        the event bus fires globally and each agent runs on behalf of its own
        creator (``agent.user_id``), so this must see every user's subscriptions
        (mirrors :meth:`list_due_scheduled`).

        Portable across SQLite (dev) and PostgreSQL (prod): we cannot rely on a
        JSON-array containment operator that both dialects share, so we fetch the
        candidate rows (those that have a non-empty ``triggers`` array) and do the
        membership check in Python. The custom-agent count per deployment is
        small (user-authored helpers), so this is cheap.
        """
        triggers_json = CustomAgent.automation["triggers"]
        stmt = select(CustomAgent).where(triggers_json.is_not(None))
        rows = list((await self.session.execute(stmt)).scalars().all())
        return [row for row in rows if trigger_name in _row_trigger_names(row)]

    async def list_due_scheduled(self, as_of: str) -> list[CustomAgent]:
        """Return custom agents whose schedule is due as of ``as_of`` (ISO UTC).

        A row is due when its ``automation`` envelope has a non-null ``cron``,
        is not paused (``schedule_enabled`` defaults true), and its stored
        ``next_run_at`` is at or before ``as_of``. ``next_run_at`` is an
        ISO-8601 string, so the lexical ``<=`` comparison is chronological.

        Scoped across all users by design - the scheduler fires on behalf of
        each agent's own creator (``agent.user_id``), so it must see every
        user's scheduled agents, unlike the per-user read paths.
        """
        next_run = CustomAgent.automation["next_run_at"].as_string()
        cron = CustomAgent.automation["cron"].as_string()
        enabled = CustomAgent.automation["schedule_enabled"].as_string()
        stmt = (
            select(CustomAgent)
            .where(
                cron.is_not(None),
                next_run.is_not(None),
                next_run <= as_of,
                # ``schedule_enabled`` defaults true; treat anything that is not
                # the literal JSON ``false`` as enabled so an absent key (older
                # rows / a cron set before the toggle existed) still fires.
                enabled != "false",
            )
            .order_by(next_run.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete(self, agent: CustomAgent) -> None:
        await self.session.delete(agent)
        await self.session.flush()
