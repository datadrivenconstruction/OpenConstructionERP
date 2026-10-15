# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The demo logistics plan is really seeded, and tells the story of where the project stands.

The seed goes through the service, so one refused write used to leave a demo
project without its plan and a warning in a log nobody reads. Here it runs
against PostgreSQL for both stories and every plan screen must have rows:

* a project without a phase model keeps the running site;
* a project still before its gate into construction (the shipped neutral model,
  no gate decided) gets a plan and nothing that has already happened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.site_logistics import hosting
from app.modules.site_logistics import models as m
from app.modules.site_logistics.demo import DEMO_CONSTRUCTION_START_DAY
from app.modules.site_logistics.demo_plan import seed_logistics_plan_demo
from app.modules.site_logistics.permissions import register_site_logistics_permissions
from app.modules.site_logistics.plan_service import LogisticsPlanService
from tests._pg import isolated_engine
from tests.pg import governance_fixtures as gov

pytestmark = pytest.mark.asyncio

# Every table a plan screen lists from.
_SCREENS = (
    m.ExpansionStage,
    m.SiteArea,
    m.AreaAllocation,
    m.MediaConnection,
    m.MediaDemand,
    m.LogisticsConcept,
    m.Transport,
    m.TransportPermit,
    m.CustomsCase,
    m.CustomsLine,
    m.CustomsDocument,
    m.NeighbourhoodPlan,
    m.CoordinationEntry,
)


_CUSTOMS = (m.CustomsCase, m.CustomsLine, m.CustomsDocument)
START = DEMO_CONSTRUCTION_START_DAY


async def _rows(session: AsyncSession, model, project_id) -> list:
    return list((await session.execute(sa.select(model).where(model.project_id == project_id))).scalars())


async def test_the_plan_seed_fills_every_screen_for_both_stories() -> None:
    register_site_logistics_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        w = await gov.build_world(factory)  # the neutral phase model, no gate decided
        async with factory() as s:
            running = await gov.add_project(s, w.manager, [])  # no phase model at all
            await s.commit()

        async with factory() as s:
            assert await hosting.before_construction(s, w.project_id) is True
            assert await hosting.before_construction(s, running) is False
            totals = await seed_logistics_plan_demo(s, [running, w.project_id])
            assert totals["projects"] == 2
            await s.commit()
        async with factory() as s:
            # A second run adds nothing.
            assert (await seed_logistics_plan_demo(s, [running, w.project_id]))["projects"] == 0

        today = datetime.now(UTC).date()
        async with factory() as s:
            for pid in (running, w.project_id):
                for model in _SCREENS:
                    if model in _CUSTOMS and pid != running:
                        # Nothing is ordered before the gate: no shipment, no customs case.
                        assert await _rows(s, model, pid) == [], model.__tablename__
                        continue
                    assert await _rows(s, model, pid), (model.__tablename__, pid == running)
                svc = LogisticsPlanService(s)
                concept = await svc.concept(pid)
                assert concept.site_timezone and len(concept.strategy) == 3
                # The rules run on the seeded plan without raising.
                assert isinstance(await svc.findings(pid), list)
                assert (await svc.readiness(pid))["items"]

            # ── the running site ────────────────────────────────────────────
            stages = {x.code: x.state for x in await _rows(s, m.ExpansionStage, running)}
            assert stages == {"S1": "active", "S2": "planned"}
            media = {x.media_kind: x.state for x in await _rows(s, m.MediaConnection, running)}
            assert media == {"power": "connected", "water": "connected"}
            transports = await _rows(s, m.Transport, running)
            heavy = next(t for t in transports if t.transport_kind == "heavy_oversize")
            assert heavy.state == "scheduled"
            assert {p.state for p in await _rows(s, m.TransportPermit, running)} == {"granted"}
            assert len(await _rows(s, m.NeighbourIssue, running)) == 2

            # ── before the gate into construction: a plan, nothing that has happened ──
            pid = w.project_id
            assert {x.state for x in await _rows(s, m.ExpansionStage, pid)} == {"planned"}
            first_day = min(x.from_date for x in await _rows(s, m.ExpansionStage, pid))
            assert START == 190 and first_day == today + timedelta(days=START)
            media = {x.media_kind: x.state for x in await _rows(s, m.MediaConnection, pid)}
            assert media == {
                "power": "requested",
                "water": "requested",
                "sewage": "requested",
                "telecom": "identified",
            }
            connections = {x.id: x.media_kind for x in await _rows(s, m.MediaConnection, pid)}
            demanded = {connections[d.media_connection_id] for d in await _rows(s, m.MediaDemand, pid)}
            assert demanded == {"power", "water", "sewage", "telecom"}
            transports = await _rows(s, m.Transport, pid)
            heavy = [t for t in transports if t.transport_kind == "heavy_oversize"]
            assert len(heavy) == 1 and heavy[0].state == "permit_pending"
            assert heavy[0].planned_window_start.date() > today + timedelta(days=440)
            assert {t.state for t in transports} == {"permit_pending", "planned"}
            assert all(t.planned_window_start.date() > today + timedelta(days=START) for t in transports)
            assert all(t.arrived_on is None and t.in_transit_on is None for t in transports)
            permits = await _rows(s, m.TransportPermit, pid)
            assert [(p.permit_kind, p.state, p.transport_id) for p in permits] == [
                ("oversize_permit", "draft", heavy[0].id)
            ]
            assert await _rows(s, m.NeighbourIssue, pid) == []


async def test_the_seed_names_nobody_outside_the_project_and_logs_nothing_above_info(caplog) -> None:
    """A demo seeder runs on real installations, next to real accounts.

    The stranger here is a manager of the installation who is on neither project.
    After the whole logistics seed (the board and the plan) no row of the module
    carries that account, and the module's loggers said nothing above info: both
    stories are healthy states, a project with only its owner included.
    """
    import logging

    from app.database import Base
    from app.modules.site_logistics.demo import seed_site_logistics_demo

    register_site_logistics_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        w = await gov.build_world(factory)
        async with factory() as s:
            stranger = await gov.add_user(s, "manager")
            alone = await gov.add_project(s, w.manager, [])  # nobody but its owner
            await s.commit()

        with caplog.at_level(logging.DEBUG):
            async with factory() as s:
                totals = await seed_site_logistics_demo(s, [alone, w.project_id])
                await s.commit()
        assert totals["plan_projects"] == 2
        loud = [
            (r.name, r.levelname, r.getMessage())
            for r in caplog.records
            if r.name.startswith("app.modules.site_logistics") and r.levelno > logging.INFO
        ]
        assert not loud, loud

        scanned = 0
        async with factory() as s:
            for table in Base.metadata.sorted_tables:
                if not table.name.startswith("oe_site_logistics_"):
                    continue
                for row in (await s.execute(sa.select(table))).mappings():
                    scanned += 1
                    assert str(stranger) not in {str(v) for v in row.values()}, table.name
        # The scan read the seeded plan, not empty tables.
        assert scanned > 40
