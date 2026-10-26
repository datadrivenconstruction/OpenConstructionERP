# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate branches against the database: fork, tree, compare, cherry-pick, merge.

The branch is an ordinary bill built by ``duplicate_boq``; what is pinned here
is what the branch layer adds on top:

* a fork stamps lineage on the source, writes a fork-point snapshot on the
  branch and keeps the branch out of the bill register and the "which bill"
  resolver;
* a fork from a snapshot starts from that snapshot's lines;
* cherry-pick writes only the chosen lines, snapshots the target first and
  refuses while a conflict has no decision; a decision either way is honoured;
* merge snapshots main, applies every change, then locks the branch as merged,
  and a merged branch takes no further changes;
* a locked main refuses a merge; the fork-point snapshot cannot be deleted;
* the drift block the validate endpoint feeds the boq.branch rules.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.boq_target import list_project_boqs
from app.core.validation.engine import ValidationContext
from app.modules.boq.branch_diff import LINEAGE_KEY
from app.modules.boq.branch_service import BranchService
from app.modules.boq.models import BOQ, BOQBranch, BOQSnapshot, Position
from app.modules.boq.repository import BOQRepository
from app.modules.boq.schemas import PositionCreate, PositionUpdate
from app.modules.boq.service import BOQService
from app.modules.boq.validators import BranchConflictsUnresolved, BranchDivergedFromMain
from app.modules.projects.models import Project
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A project with one bill of three priced lines under a section. Returns (project, bill)."""
    project = Project(name=f"Branch {uuid.uuid4().hex[:6]}", currency="EUR", region="DACH", owner_id=uuid.uuid4())
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Main estimate", status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    boq_id = boq.id
    service = BOQService(session)
    section = await service.add_position(
        PositionCreate(boq_id=boq_id, ordinal="1", description="Structure", unit="section", quantity=0, unit_rate=0)
    )
    for ordinal, desc, qty, rate in (
        ("1.1", "Cast in place slab", 100, 120),
        ("1.2", "Walls", 40, 200),
        ("1.3", "Columns", 10, 300),
    ):
        await service.add_position(
            PositionCreate(
                boq_id=boq_id,
                parent_id=section.id,
                ordinal=ordinal,
                description=desc,
                unit="m3",
                quantity=qty,
                unit_rate=rate,
            )
        )
    session.expunge_all()
    return project.id, boq_id


async def _by_ordinal(session: AsyncSession, boq_id: uuid.UUID) -> dict[str, Position]:
    rows = (await session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()
    return {p.ordinal: p for p in rows}


async def _set(session: AsyncSession, position: Position, **fields) -> None:
    await BOQService(session).update_position(position.id, PositionUpdate(**fields))


@pytest.mark.asyncio
async def test_fork_stamps_lineage_snapshots_and_hides_the_branch(session: AsyncSession) -> None:
    project_id, main_id = await _seed(session)
    branches = BranchService(session)

    branch = await branches.create_branch(main_id, name="Precast alternative", note="VE round 1")
    branch_id = branch.id

    main_lines = await _by_ordinal(session, main_id)
    branch_lines = await _by_ordinal(session, branch_id)
    assert set(main_lines) == set(branch_lines)
    for ordinal, line in main_lines.items():
        assert line.metadata_[LINEAGE_KEY] == str(line.id)
        assert branch_lines[ordinal].metadata_[LINEAGE_KEY] == str(line.id)

    header = (await session.execute(select(BOQ.branch_of_id, BOQ.parent_estimate_id).where(BOQ.id == branch_id))).one()
    assert header.branch_of_id == main_id and header.parent_estimate_id == main_id
    row = await branches.branch_row(branch_id)
    assert row is not None and row.status == "open" and row.note == "VE round 1"
    base = await session.get(BOQSnapshot, row.base_snapshot_id)
    assert base is not None and base.boq_id == branch_id and base.position_count == 4

    register, total = await BOQRepository(session).list_for_project(project_id)
    assert [b.id for b in register] == [main_id] and total == 1
    assert [b.id for b in await list_project_boqs(session, project_id)] == [main_id]


@pytest.mark.asyncio
async def test_fork_from_a_snapshot_starts_from_its_lines(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    service = BOQService(session)
    snap = await service.create_snapshot(main_id, name="Tender issue")
    walls = (await _by_ordinal(session, main_id))["1.2"]
    await _set(session, walls, quantity=55)

    branch = await BranchService(session).create_branch(main_id, name="From tender", snapshot_id=snap.id)
    lines = await _by_ordinal(session, branch.id)
    assert Decimal(lines["1.2"].quantity) == Decimal("40")
    assert lines["1.2"].metadata_[LINEAGE_KEY] == str(walls.id)
    row = await BranchService(session).branch_row(branch.id)
    assert row.source_snapshot_id == snap.id


@pytest.mark.asyncio
async def test_tree_reports_totals_and_delta_against_the_parent(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branches = BranchService(session)
    first = await branches.create_branch(main_id, name="A")
    nested = await branches.create_branch(first.id, name="A.1")
    slab = (await _by_ordinal(session, nested.id))["1.1"]
    await _set(session, slab, unit_rate=100)

    tree = await branches.tree(nested.id)
    assert tree["main_boq_id"] == main_id
    nodes = {n["boq_id"]: n for n in tree["nodes"]}
    assert nodes[main_id]["is_main"] and nodes[main_id]["position_count"] == 4
    assert nodes[nested.id]["parent_boq_id"] == first.id
    assert Decimal(nodes[nested.id]["delta_vs_parent"]) == Decimal("-2000.00")
    assert Decimal(nodes[first.id]["delta_vs_parent"]) == Decimal("0.00")


@pytest.mark.asyncio
async def test_compare_two_branches(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branches = BranchService(session)
    branch = await branches.create_branch(main_id, name="Precast")
    lines = await _by_ordinal(session, branch.id)
    await _set(session, lines["1.1"], description="Precast slab", unit_rate=110)
    await BOQService(session).delete_position(lines["1.3"].id)

    result = await branches.compare(main_id, branch.id)
    rows = {r["ordinal"]: r for r in result["rows"]}
    assert rows["1.1"]["change_type"] == "changed"
    assert set(rows["1.1"]["changed_fields"]) == {"description", "unit_rate"}
    assert rows["1.3"]["change_type"] == "removed"
    assert result["summary"]["changed"] == 1 and result["summary"]["removed"] == 1
    assert Decimal(result["summary"]["delta"]) == Decimal("-1000") - Decimal("3000")
    assert result["by_section"][0]["label"] == "1 Structure"


@pytest.mark.asyncio
async def test_cherry_pick_writes_only_chosen_lines_and_snapshots_the_target(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branches = BranchService(session)
    source = await branches.create_branch(main_id, name="Source")
    target = await branches.create_branch(main_id, name="Target")
    s_lines = await _by_ordinal(session, source.id)
    await _set(session, s_lines["1.1"], quantity=90)
    await _set(session, s_lines["1.2"], quantity=45)
    service = BOQService(session)
    await service.add_position(
        PositionCreate(
            boq_id=source.id,
            parent_id=s_lines["1"].id,
            ordinal="1.4",
            description="Precast beams",
            unit="m",
            quantity=30,
            unit_rate=80,
        )
    )
    plan = await branches.plan(source.id, target.id)
    keys = {i["ordinal"]: i["key"] for i in plan["items"]}
    assert set(keys) == {"1.1", "1.2", "1.4"}

    result = await branches.cherry_pick(source.id, target.id, keys=[keys["1.1"], keys["1.4"]], resolutions={})
    assert (result["added"], result["updated"], result["removed"]) == (1, 1, 0)
    t_lines = await _by_ordinal(session, target.id)
    assert Decimal(t_lines["1.1"].quantity) == Decimal("90")
    assert Decimal(t_lines["1.2"].quantity) == Decimal("40"), "a line not chosen stays as it was"
    assert t_lines["1.4"].parent_id == t_lines["1"].id
    snap = await session.get(BOQSnapshot, result["snapshot_id"])
    assert snap.boq_id == target.id
    beams = [p for p in snap.snapshot_data["positions"] if p["ordinal"] == "1.4"]
    assert beams == [], "the snapshot holds the target as it was before"


@pytest.mark.asyncio
async def test_conflicts_must_be_decided_and_each_decision_is_honoured(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branches = BranchService(session)
    branch = await branches.create_branch(main_id, name="VE")
    await _set(session, (await _by_ordinal(session, branch.id))["1.2"], unit_rate=180)
    await _set(session, (await _by_ordinal(session, main_id))["1.2"], unit_rate=210)
    await _set(session, (await _by_ordinal(session, branch.id))["1.3"], quantity=12)
    await _set(session, (await _by_ordinal(session, main_id))["1.3"], quantity=8)

    with pytest.raises(HTTPException) as refused:
        await branches.merge(branch.id, resolutions={})
    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "unresolved_conflicts"
    assert len(refused.value.detail["conflicts"]) == 2
    assert Decimal((await _by_ordinal(session, main_id))["1.2"].unit_rate) == Decimal("210")

    plan = await branches.plan(branch.id, main_id)
    keys = {i["ordinal"]: i["key"] for i in plan["items"] if i["conflict"]}
    result = await branches.merge(branch.id, resolutions={keys["1.2"]: "source", keys["1.3"]: "target"})
    assert result["kept_target"] == 1 and result["updated"] == 1
    main_lines = await _by_ordinal(session, main_id)
    assert Decimal(main_lines["1.2"].unit_rate) == Decimal("180")
    assert Decimal(main_lines["1.3"].quantity) == Decimal("8")


@pytest.mark.asyncio
async def test_merge_snapshots_main_locks_the_branch_and_closes_it(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branches = BranchService(session)
    branch = await branches.create_branch(main_id, name="Final")
    lines = await _by_ordinal(session, branch.id)
    await _set(session, lines["1.1"], quantity=80)
    await BOQService(session).delete_position(lines["1.3"].id)

    result = await branches.merge(branch.id, resolutions={})
    assert result["status"] == "merged" and result["removed"] == 1 and result["updated"] == 1
    main_lines = await _by_ordinal(session, main_id)
    assert "1.3" not in main_lines and Decimal(main_lines["1.1"].quantity) == Decimal("80")
    row = (await session.execute(select(BOQBranch).where(BOQBranch.boq_id == branch.id))).scalar_one()
    assert row.status == "merged" and row.merge_snapshot_id == result["snapshot_id"]
    snap = await session.get(BOQSnapshot, result["snapshot_id"])
    assert snap.boq_id == main_id and snap.position_count == 4
    locked = (await session.execute(select(BOQ.is_locked).where(BOQ.id == branch.id))).scalar_one()
    assert locked is True

    with pytest.raises(HTTPException) as again:
        await branches.merge(branch.id, resolutions={})
    assert again.value.status_code == 409
    with pytest.raises(HTTPException) as fork:
        await branches.create_branch(branch.id, name="From merged")
    assert fork.value.status_code == 409


@pytest.mark.asyncio
async def test_a_locked_main_refuses_the_merge(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branches = BranchService(session)
    branch = await branches.create_branch(main_id, name="Late")
    await _set(session, (await _by_ordinal(session, branch.id))["1.1"], quantity=1)
    await BOQRepository(session).update_fields(main_id, is_locked=True)
    with pytest.raises(HTTPException) as refused:
        await branches.merge(branch.id, resolutions={})
    assert refused.value.status_code == 409
    assert (await branches.branch_row(branch.id)).status == "open"


@pytest.mark.asyncio
async def test_the_fork_point_snapshot_cannot_be_deleted(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branches = BranchService(session)
    branch = await branches.create_branch(main_id, name="Keep base")
    row = await branches.branch_row(branch.id)
    with pytest.raises(HTTPException) as refused:
        await BOQService(session).delete_snapshot(branch.id, row.base_snapshot_id)
    assert refused.value.status_code == 409


@pytest.mark.asyncio
async def test_an_edit_that_replaces_metadata_keeps_the_lineage(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branch = await BranchService(session).create_branch(main_id, name="Meta")
    line = (await _by_ordinal(session, branch.id))["1.1"]
    lineage = line.metadata_[LINEAGE_KEY]
    await _set(session, line, metadata={"note": "client sent its own blob"})
    session.expunge_all()
    again = (await _by_ordinal(session, branch.id))["1.1"]
    assert again.metadata_[LINEAGE_KEY] == lineage and again.metadata_["note"] == "client sent its own blob"


@pytest.mark.asyncio
async def test_a_duplicated_line_is_a_new_lineage(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branch = await BranchService(session).create_branch(main_id, name="Dup")
    line = (await _by_ordinal(session, branch.id))["1.1"]
    copy = await BOQService(session).duplicate_position(line.id)
    assert LINEAGE_KEY not in (copy.metadata_ or {})


@pytest.mark.asyncio
async def test_drift_feeds_the_branch_rules(session: AsyncSession) -> None:
    _, main_id = await _seed(session)
    branches = BranchService(session)
    branch = await branches.create_branch(main_id, name="Drift")
    await _set(session, (await _by_ordinal(session, branch.id))["1.2"], unit_rate=180)
    await _set(session, (await _by_ordinal(session, main_id))["1.2"], unit_rate=210)

    block = await branches.divergence(branch.id)
    assert block["status"] == "open" and block["main_changes"] == 1
    assert [c["ordinal"] for c in block["conflicts"]] == ["1.2"]
    assert await branches.divergence(main_id) is None

    conflicts = await BranchConflictsUnresolved().validate(ValidationContext(data={"branch": block}))
    assert len(conflicts) == 1 and conflicts[0].element_ref == "1.2"
    fresh = await BranchDivergedFromMain().validate(ValidationContext(data={"branch": block}))
    assert fresh == [], "a branch opened today is not stale"
    stale = await BranchDivergedFromMain().validate(ValidationContext(data={"branch": {**block, "days_open": 45}}))
    assert len(stale) == 1 and stale[0].details["main_changes"] == 1
    merged = await BranchConflictsUnresolved().validate(
        ValidationContext(data={"branch": {**block, "status": "merged"}})
    )
    assert merged == []
