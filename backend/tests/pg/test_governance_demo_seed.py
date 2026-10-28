# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo seed fills project governance through the service, once per project.

A demo project opens on the governance screen with a pinned phase model, an owner
on every area, a first gate decided with conditions, frame documents in several
states and one change request against a binding document. A second run of the
seeder must leave every count where the first run put it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.core import demo_enrichment
from app.modules.project_governance.models import (
    GovernanceArea,
    GovernanceChangeRequest,
    GovernanceCondition,
    GovernanceDecision,
    GovernanceDocument,
    GovernanceGate,
    GovernanceModel,
)
from app.modules.project_governance.seed import seed_project_governance_demo
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

DEMO = "demo@openconstructionerp.com"
MANAGER = "manager@openconstructionerp.com"
ESTIMATOR = "estimator@openconstructionerp.com"


@pytest_asyncio.fixture
async def factory(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        f = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", f)
        yield f


async def _user(s: AsyncSession, email: str, role: str) -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    s.add(
        User(
            id=uid,
            email=email,
            hashed_password="x",
            full_name=email.split("@")[0].title(),
            role=role,
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await s.flush()
    return uid


async def _project(s: AsyncSession, owner: uuid.UUID) -> uuid.UUID:
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    s.add(
        Project(
            id=pid,
            name="Demo governance",
            currency="EUR",
            status="active",
            owner_id=owner,
            # A demo project the seed does not place further on: it keeps the first-gate story.
            metadata_={"demo_id": "office-london"},
        )
    )
    await s.flush()
    return pid


async def _world(factory, *, with_manager: bool = True) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    async with factory() as s:
        users = {"demo": await _user(s, DEMO, "admin"), "estimator": await _user(s, ESTIMATOR, "estimator")}
        if with_manager:
            users["manager"] = await _user(s, MANAGER, "manager")
        pid = await _project(s, users["demo"])
        await s.commit()
    return pid, users


async def _seed(factory, pid: uuid.UUID) -> dict[str, int]:
    async with factory() as s:
        counts = await seed_project_governance_demo(s, [pid])
        await s.commit()
    return counts


async def _counts(factory, pid: uuid.UUID) -> dict[str, int]:
    from app.modules.approval_routes.models import Route
    from app.modules.cde.models import DocumentContainer, DocumentRevision
    from app.modules.teams.models import Team, TeamMembership

    tables = {
        "models": (GovernanceModel, GovernanceModel.project_id),
        "decisions": (GovernanceDecision, GovernanceDecision.project_id),
        "conditions": (GovernanceCondition, GovernanceCondition.project_id),
        "change_requests": (GovernanceChangeRequest, GovernanceChangeRequest.project_id),
        "documents": (GovernanceDocument, GovernanceDocument.project_id),
        "routes": (Route, Route.project_id),
        "containers": (DocumentContainer, DocumentContainer.project_id),
        "teams": (Team, Team.project_id),
    }
    out: dict[str, int] = {}
    async with factory() as s:
        for name, (model, col) in tables.items():
            out[name] = (await s.execute(select(func.count()).select_from(model).where(col == pid))).scalar_one()
        out["revisions"] = (
            await s.execute(
                select(func.count())
                .select_from(DocumentRevision)
                .join(DocumentContainer, DocumentContainer.id == DocumentRevision.container_id)
                .where(DocumentContainer.project_id == pid)
            )
        ).scalar_one()
        out["memberships"] = (
            await s.execute(
                select(func.count())
                .select_from(TeamMembership)
                .join(Team, Team.id == TeamMembership.team_id)
                .where(Team.project_id == pid)
            )
        ).scalar_one()
    return out


async def test_seed_fills_governance(factory) -> None:
    pid, users = await _world(factory)
    counts = await _seed(factory, pid)
    assert counts["projects"] == 1

    async with factory() as s:
        model = (await s.execute(select(GovernanceModel).where(GovernanceModel.project_id == pid))).scalar_one()
        assert (model.catalogue_source, model.catalogue_id) == ("shipped", "neutral")
        assert model.catalogue_version is not None
        assert model.four_eyes is True

        live_areas = (
            (
                await s.execute(
                    select(GovernanceArea).where(GovernanceArea.project_id == pid, GovernanceArea.retired.is_(False))
                )
            )
            .scalars()
            .all()
        )
        assert live_areas
        assert all(a.owner_user_id is not None for a in live_areas if a.applicable), "an area was left without an owner"
        assert len(live_areas) == 10
        owners = {a.owner_user_id for a in live_areas}
        assert users["estimator"] in owners, "the estimator owns no area, the ownership map lost its cost areas"
        assert owners <= {users["demo"], users["estimator"]}
        assert users["manager"] not in owners, "the decider owns an area, four-eyes would refuse the decision"

        gate = (
            await s.execute(
                select(GovernanceGate).where(
                    GovernanceGate.project_id == pid, GovernanceGate.code == "strategy_to_brief"
                )
            )
        ).scalar_one()
        assert gate.status == "decided"
        assert gate.last_outcome == "go_with_conditions"
        assert model.current_phase == gate.to_phase

        decision = (
            await s.execute(select(GovernanceDecision).where(GovernanceDecision.gate_id == gate.id))
        ).scalar_one()
        assert decision.decided_by == users["manager"]

        conds = (
            (await s.execute(select(GovernanceCondition).where(GovernanceCondition.decision_id == decision.id)))
            .scalars()
            .all()
        )
        by_status = {c.status: c for c in conds}
        assert len(conds) == 2 and set(by_status) == {"cleared", "open"}
        assert by_status["cleared"].evidence.strip()
        assert by_status["open"].due_date > datetime.now(UTC).date().isoformat()

        docs = {
            d.doc_type: d
            for d in (await s.execute(select(GovernanceDocument).where(GovernanceDocument.project_id == pid)))
            .scalars()
            .all()
        }
        statuses = {d.status for d in docs.values()}
        assert {"binding", "in_review", "draft"} <= statuses
        assert docs["business_case"].status == "binding"

        crs = (
            (await s.execute(select(GovernanceChangeRequest).where(GovernanceChangeRequest.project_id == pid)))
            .scalars()
            .all()
        )
        assert len(crs) == 1
        assert crs[0].status == "submitted"
        assert crs[0].document_id == docs["business_case"].id
        assert crs[0].approval_instance_id is not None


async def test_second_run_is_a_no_op(factory) -> None:
    pid, _ = await _world(factory)
    await _seed(factory, pid)
    first = await _counts(factory, pid)
    assert first["models"] == 1 and first["decisions"] == 1

    again = await _seed(factory, pid)

    assert again["projects"] == 0
    assert await _counts(factory, pid) == first


async def test_without_a_decider_the_project_gets_what_needs_no_second_person(factory) -> None:
    """Four-eyes would refuse an owner deciding their own areas, so nothing is decided; the rest is written."""
    pid, _ = await _world(factory, with_manager=False)
    result = await _seed(factory, pid)
    assert (result["projects"], result["ok"]) == (1, True)
    assert [(r["planned"], r["reached"], r["fallback_reason"], r["loud"]) for r in result["placements"]] == [
        ("first_gate", "owner_only", "no_decider", False)
    ]
    counts = await _counts(factory, pid)
    assert (counts["models"], counts["decisions"], counts["routes"], counts["conditions"]) == (1, 0, 0, 0)
    assert counts["documents"] > 0 and counts["containers"] >= 3 and counts["revisions"] >= 3
    # The estimator login of this world joined as the cost owner; nobody was created for the missing part.
    assert (counts["teams"], counts["memberships"]) == (1, 1)


async def test_the_enrichment_step_seeds_commits_and_hands_the_result_back(factory) -> None:
    """The step ``enrich_projects`` runs (its place in the order is tests/unit/test_governance_seed_order.py)."""
    pid, _ = await _world(factory)
    seeded = await demo_enrichment._seed_governance(factory, [pid])
    assert (seeded["ok"], seeded["projects"], seeded["fallbacks"]) == (True, 1, [])
    assert [(r["project_id"], r["planned"], r["reached"]) for r in seeded["placements"]] == [
        (str(pid), "first_gate", "first_gate")
    ]
    # Read in another session: the step committed what it seeded.
    assert (await _counts(factory, pid))["models"] == 1

    settled = await demo_enrichment._settle_governance(factory, [pid])
    assert set(settled) == {"cleared", "left_open"}
    assert all(isinstance(n, int) for n in settled.values())


async def test_a_governance_step_that_fails_is_reported_and_does_not_raise(
    factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.project_governance import seed as governance_seed

    async def _broken(session, project_ids):
        raise RuntimeError("the seed broke")

    monkeypatch.setattr(governance_seed, "seed_project_governance_demo", _broken)
    monkeypatch.setattr(governance_seed, "settle_demo_conditions", _broken)
    pid, _ = await _world(factory)
    assert await demo_enrichment._seed_governance(factory, [pid]) == {"ok": False, "error": "RuntimeError"}
    assert await demo_enrichment._settle_governance(factory, [pid]) == {"ok": False, "error": "RuntimeError"}
    assert (await _counts(factory, pid))["models"] == 0
