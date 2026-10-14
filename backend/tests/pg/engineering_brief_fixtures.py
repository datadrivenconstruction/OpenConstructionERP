# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared builders for the engineering brief PostgreSQL tests.

A world is a throwaway database with real users and a project, optionally running governance on the
shipped ``elf_module_framework`` model, and a brief pinned to the requested shipped catalogue. Everything
commits for real. ``complete_brief`` fills the brief with exactly what the pinned catalogue asks for, so a
test starts from a submittable brief and breaks one thing.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.engineering_brief.service import EngineeringBriefService
from app.modules.project_governance.service import GovernanceService
from tests.pg.governance_fixtures import World, add_container, add_project, add_route, add_user

OPERATION_PROOF = date.today() + timedelta(days=800)


async def build_world(
    factory: async_sessionmaker[AsyncSession],
    *,
    catalogue_id: str = "neutral",
    governance: bool = False,
    brief: bool = True,
) -> World:
    from app.modules.engineering_brief.catalogue import register_kinds

    register_kinds()
    async with factory() as s:
        manager = await add_user(s, "manager")
        decider = await add_user(s, "manager")
        owner = await add_user(s, "manager")
        editor = await add_user(s, "editor")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [decider, owner, editor])
        w = World(factory, pid, manager, decider, owner, editor, outsider)
        if governance:
            w.gate_route_id = await add_route(s, pid, "phase_gate", decider)
            w.change_route_id = await add_route(s, pid, "frame_change", decider)
            await GovernanceService(s).set_model(
                pid,
                source="shipped",
                catalogue_id="elf_module_framework",
                version=None,
                four_eyes=True,
                actor_id=manager,
                tenant_id=str(manager),
            )
            await GovernanceService(s).update_settings(
                pid,
                four_eyes=None,
                decision_route_id=w.gate_route_id,
                change_route_id=w.change_route_id,
                fields_set={"decision_route_id", "change_route_id"},
                actor_id=manager,
            )
            for d in await GovernanceService(s).repo.list_documents(pid):
                w.containers[d.doc_type] = await add_container(s, pid, d.doc_type)
        if brief:
            await EngineeringBriefService(s).set_brief(
                pid,
                actor_id=manager,
                tenant_id=str(manager),
                catalogue_id=catalogue_id,
                title="Brief",
                operation_proof_date=OPERATION_PROOF,
            )
        await s.commit()
    return w


async def call(w: World, fn: str, *args: Any, **kw: Any) -> Any:
    """Run one service method in its own committed session."""
    async with w.factory() as s:
        out = await getattr(EngineeringBriefService(s), fn)(w.project_id, *args, **kw)
        await s.commit()
        return out


async def complete_brief(w: World, *, with_gates: bool = False) -> None:
    """Everything the pinned catalogue requires: a verified requirement per required category, a decided
    concept item per required topic answering them, a programme line and the template chain."""
    async with w.factory() as s:
        svc = EngineeringBriefService(s)
        brief = await svc.require_brief(w.project_id)
        cat = await svc.catalogue_for(brief)
        ids = []
        for category in cat.requirement_categories:
            if not category.required:
                continue
            row = await svc.create_requirement(
                w.project_id,
                {
                    "category": category.code,
                    "entity": "Building",
                    "attribute": category.code,
                    "constraint_type": "exists",
                    "priority": "must",
                    "verification_method": "inspection",
                    "originator": "Owner",
                },
                w.manager,
            )
            ids.append(row.id)
        first = True
        for topic in cat.concept_topics:
            if topic.required:
                await svc.create_concept(
                    w.project_id,
                    {
                        "topic_code": topic.code,
                        "title": topic.code,
                        "decision": "Decided",
                        "requirement_ids": ids if first else [],
                    },
                    w.manager,
                )
                first = False
        await svc.create_programme(
            w.project_id,
            {"kind_code": cat.programme_kinds[0].code, "label": "Area", "unit": "m2", "quantity": "1000"},
            w.manager,
        )
        await svc.milestones_from_catalogue(w.project_id, None, w.manager)
        if with_gates:
            await svc.milestones_from_gates(w.project_id, w.manager)
            # The shipped model gives its gates no target date; a gate milestone is dated before publishing.
            day = OPERATION_PROOF - timedelta(days=700)
            for row in await svc.milestone_views(w.project_id):
                if row["gate_code"] and row["planned_date"] is None:
                    day += timedelta(days=60)
                    await svc.update_milestone(w.project_id, uuid.UUID(row["id"]), {"planned_date": day}, w.manager)
        await s.commit()
