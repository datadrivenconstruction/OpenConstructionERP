# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The cost structure on real PostgreSQL: tree, suspense, splits, copies, code lists.

Each test reads money back through the same paths the UI uses (the structure
tree, the bill's vectors, the cost control report), so a split that counted a
position twice, or a copied bill that added its money to the original's lines,
shows as a wrong total here.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio

D = Decimal


async def _project(pg_session, *, standard: str = "din276") -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"pg-structure-{uuid.uuid4().hex[:8]}@cost-structure.io",
        hashed_password="x",
        full_name="Structure Owner",
        role="admin",
    )
    pg_session.add(owner)
    await pg_session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Structure test",
        owner_id=owner.id,
        currency="EUR",
        fx_rates=[],
        classification_standard=standard,
    )
    pg_session.add(project)
    await pg_session.flush()
    return project.id


async def _bill(pg_session, project_id: uuid.UUID, specs: list[tuple]) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A bill with positions ``(ordinal, unit, qty, rate, total, classification)``."""
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name="Bill")
    pg_session.add(boq)
    await pg_session.flush()
    ids = []
    for n, (ordinal, unit, qty, rate, total, classification) in enumerate(specs):
        pos = Position(
            boq_id=boq.id,
            ordinal=ordinal,
            description=f"Item {ordinal}",
            unit=unit,
            quantity=qty,
            unit_rate=rate,
            total=total,
            classification=classification,
            sort_order=n,
        )
        pg_session.add(pos)
        await pg_session.flush()
        ids.append(pos.id)
    boq_id = boq.id
    pg_session.expunge_all()
    return boq_id, ids


async def _line_total(pg_session, project_id: uuid.UUID) -> Decimal:
    from sqlalchemy import select

    from app.modules.costmodel.models import CostLine

    rows = (
        await pg_session.execute(select(CostLine.estimate_amount).where(CostLine.project_id == project_id))
    ).scalars()
    return sum((D(str(r or "0")) for r in rows), D("0"))


async def _line_of(pg_session, position_id: uuid.UUID):
    from sqlalchemy import select

    from app.modules.costmodel.models import CostLine

    return (await pg_session.execute(select(CostLine).where(CostLine.boq_position_id == position_id))).scalar_one()


SPECS = [
    ("01", "m3", "10", "100", "1000.00", {"din276": "331"}),
    ("02", "m2", "5", "40", "200.00", {"din276": "331"}),
    ("03", "kg", "200", "1.5", "300.00", {"din276": "340"}),
    # MasterFormat only: under a DIN 276 structure it has no account.
    ("04", "m", "4", "25", "100.00", {"masterformat": "03 30 00"}),
]


async def test_generate_builds_the_tree_from_one_standard_and_parks_the_rest(pg_session) -> None:
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, ids = await _bill(pg_session, project_id, SPECS)

    result = await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    assert result.standard == "din276"
    assert result.cost_lines_created == 4
    # 331 needs 300 and 330 above it; 340 sits under 300.
    assert result.accounts_created == 4
    assert result.positions_in_suspense == 1
    assert result.suspense_amount == D("100.00")

    tree = await CostStructureService(pg_session).tree(project_id)
    assert [(n.code, n.level) for n in tree.nodes] == [("300", 1), ("330", 2), ("331", 3), ("340", 2)]
    by_code = {n.code: n for n in tree.nodes}
    assert by_code["331"].posted == D("1200.00")
    assert by_code["300"].total == D("1500.00")
    assert by_code["330"].title  # titled from the shipped code list
    assert {n.classification_standard for n in tree.nodes} == {"din276"}
    no_account = next(b for b in tree.suspense if b.kind == "no_account")
    assert (no_account.line_count, no_account.amount) == (1, D("100.00"))
    assert tree.total == D("1600.00") == await _line_total(pg_session, project_id)
    assert any(f.rule_id == "cost_structure.posted_to_postable" for f in tree.findings)
    assert not any(f.rule_id == "cost_structure.rollup" and f.severity == "error" for f in tree.findings)

    # A second run adds nothing.
    again = await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    assert (again.accounts_created, again.cost_lines_created) == (0, 0)


async def test_a_structure_is_never_a_mix_of_code_lists(pg_session) -> None:
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, _ = await _bill(pg_session, project_id, SPECS)
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)

    with pytest.raises(HTTPException) as err:
        await CostSpineService(pg_session).generate_from_boq(project_id, boq_id, "masterformat")
    assert err.value.status_code == 409
    assert err.value.detail["problem"] == "structure_standard_mismatch"
    with pytest.raises(HTTPException) as err:
        await CostStructureService(pg_session).apply_code_list(project_id, "nrm", None)
    assert err.value.status_code == 409


async def test_a_percent_split_moves_money_and_never_counts_it_twice(pg_session) -> None:
    from app.modules.costmodel.models import ControlAccount
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_schemas import AllocationRowIn, PositionAllocationRequest
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, ids = await _bill(pg_session, project_id, SPECS[:3])
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    before = await _line_total(pg_session, project_id)
    own = await _line_of(pg_session, ids[0])
    own_id, own_account = own.id, own.control_account_id
    acct_340 = (
        await pg_session.execute(
            ControlAccount.__table__.select().where(
                ControlAccount.project_id == project_id, ControlAccount.code == "340"
            )
        )
    ).one()

    service = CostStructureService(pg_session)
    out = await service.set_allocation(
        ids[0],
        PositionAllocationRequest(
            mode="percent",
            rows=[
                AllocationRowIn(control_account_id=own_account, share=D("60")),
                AllocationRowIn(control_account_id=acct_340.id, share=D("40")),
            ],
        ),
        "tester",
    )
    assert out.mode == "percent" and out.valid
    assert sorted(r.amount for r in out.rows) == [D("400.00"), D("600.00")]
    pg_session.expire_all()
    assert (await _line_of(pg_session, ids[0])).estimate_amount in ("600.00", "600")
    assert await _line_total(pg_session, project_id) == before

    tree = await service.tree(project_id)
    assert {n.code: n.posted for n in tree.nodes}["340"] == D("700.00")
    assert tree.total == before

    coverage = (await service.boq_allocations(boq_id)).coverage
    assert (coverage.positions_total, coverage.positions_split, coverage.share_pct) == (3, 1, D("100.00"))

    # Shares that miss the whole are refused and change nothing.
    with pytest.raises(HTTPException) as err:
        await service.set_allocation(
            ids[0],
            PositionAllocationRequest(
                mode="percent",
                rows=[
                    AllocationRowIn(cost_line_id=own_id, share=D("60")),
                    AllocationRowIn(control_account_id=acct_340.id, share=D("39")),
                ],
            ),
            "tester",
        )
    assert err.value.status_code == 422
    assert err.value.detail["problem"] == "shares_do_not_add_up"

    # Clearing takes the position off every line: the money leaves the totals.
    await service.clear_allocation(ids[0], "tester")
    assert await _line_total(pg_session, project_id) == before - D("1000.00")


async def test_a_quantity_split_follows_the_measured_parts(pg_session) -> None:
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_schemas import AllocationRowIn, PositionAllocationRequest
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, ids = await _bill(pg_session, project_id, SPECS[:3])
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    line_a = (await _line_of(pg_session, ids[0])).id
    line_c = (await _line_of(pg_session, ids[2])).id

    out = await CostStructureService(pg_session).set_allocation(
        ids[0],
        PositionAllocationRequest(
            mode="quantity",
            rows=[
                AllocationRowIn(cost_line_id=line_a, share=D("7")),
                AllocationRowIn(cost_line_id=line_c, share=D("3")),
            ],
        ),
        None,
    )
    assert {r.cost_line_id: r.amount for r in out.rows} == {line_a: D("700.00"), line_c: D("300.00")}

    with pytest.raises(HTTPException) as err:
        await CostStructureService(pg_session).set_allocation(
            ids[0],
            PositionAllocationRequest(
                mode="quantity",
                rows=[
                    AllocationRowIn(cost_line_id=line_a, share=D("7")),
                    AllocationRowIn(cost_line_id=line_c, share=D("2")),
                ],
            ),
            None,
        )
    assert err.value.detail["problem"] == "shares_do_not_add_up"


async def test_a_copied_bill_keeps_its_vectors_and_adds_no_money(pg_session) -> None:
    from sqlalchemy import select

    from app.modules.boq.models import Position
    from app.modules.boq.service import BOQService
    from app.modules.costmodel.models import ControlAccount, CostLine, PositionAllocation
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_schemas import AllocationRowIn, PositionAllocationRequest
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, ids = await _bill(pg_session, project_id, SPECS[:3])
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    line_a = (await _line_of(pg_session, ids[0])).id
    line_c = (await _line_of(pg_session, ids[2])).id
    await CostStructureService(pg_session).set_allocation(
        ids[0],
        PositionAllocationRequest(
            rows=[
                AllocationRowIn(cost_line_id=line_a, share=D("50")),
                AllocationRowIn(cost_line_id=line_c, share=D("50")),
            ]
        ),
        None,
    )
    before = await _line_total(pg_session, project_id)
    accounts_before = (
        (await pg_session.execute(select(ControlAccount.code).where(ControlAccount.project_id == project_id)))
        .scalars()
        .all()
    )

    copy = await BOQService(pg_session).duplicate_boq(boq_id)
    copy_id = copy.id
    pg_session.expire_all()
    copies = (
        await pg_session.execute(
            select(Position.ordinal, Position.cost_line_id, Position.id).where(Position.boq_id == copy_id)
        )
    ).all()
    by_ordinal = {o: (lid, pid) for o, lid, pid in copies}
    assert by_ordinal["01"][0] == line_a
    assert by_ordinal["03"][0] == line_c
    split = (
        (
            await pg_session.execute(
                select(PositionAllocation.cost_line_id).where(PositionAllocation.position_id == by_ordinal["01"][1])
            )
        )
        .scalars()
        .all()
    )
    assert sorted(map(str, split)) == sorted([str(line_a), str(line_c)])

    # Recomputing the original's lines after the copy changes nothing.
    await CostStructureService(pg_session).recompute_lines({line_a, line_c})
    assert await _line_total(pg_session, project_id) == before

    # Generating the copy's spine brings its vectors home onto lines of its own.
    result = await CostSpineService(pg_session).generate_from_boq(project_id, copy_id)
    assert result.accounts_created == 0
    pg_session.expire_all()
    copy_lines = set((await pg_session.execute(select(CostLine.id).where(CostLine.boq_id == copy_id))).scalars().all())
    split = (
        (
            await pg_session.execute(
                select(PositionAllocation.cost_line_id).where(PositionAllocation.position_id == by_ordinal["01"][1])
            )
        )
        .scalars()
        .all()
    )
    assert set(split) <= copy_lines and len(split) == 2
    # The original's lines still carry exactly the original's money.
    assert (await pg_session.get(CostLine, line_a)).estimate_amount in ("500.00", "500")
    accounts_after = (
        (await pg_session.execute(select(ControlAccount.code).where(ControlAccount.project_id == project_id)))
        .scalars()
        .all()
    )
    assert sorted(accounts_after) == sorted(accounts_before)
    # Both bills are now on the spine, each once.
    assert await _line_total(pg_session, project_id) == before * 2


async def test_own_amount_on_a_parent_counts_once_and_shows_in_cost_control(pg_session) -> None:
    from sqlalchemy import select

    from app.modules.costmodel.cost_control_service import CostControlService
    from app.modules.costmodel.models import ControlAccount
    from app.modules.costmodel.schemas import ControlAccountUpdate
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, _ = await _bill(pg_session, project_id, SPECS[:3])
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    parent_id = (
        await pg_session.execute(
            select(ControlAccount.id).where(ControlAccount.project_id == project_id, ControlAccount.code == "300")
        )
    ).scalar_one()
    await CostSpineService(pg_session).update_account(parent_id, ControlAccountUpdate(own_amount=D("250.00")))

    tree = await CostStructureService(pg_session).tree(project_id)
    root = next(n for n in tree.nodes if n.code == "300")
    assert root.own_amount == D("250.00")
    assert root.total == D("1750.00") == tree.total
    assert any(
        f.rule_id == "cost_structure.rollup" and f.details.get("problem") == "own_amount_on_parent"
        for f in tree.findings
    )

    report = await CostControlService(pg_session).report(project_id)
    allowance = [r for r in report.rows if r.kind == "allowance"]
    assert len(allowance) == 1 and allowance[0].budget == D("250.00")
    acct = next(a for a in report.accounts if a.code == "300")
    assert (acct.level, acct.own_amount) == (1, D("250.00"))


async def test_reparenting_relevels_the_subtree_and_refuses_a_loop(pg_session) -> None:
    from sqlalchemy import select

    from app.modules.costmodel.models import ControlAccount
    from app.modules.costmodel.schemas import ControlAccountUpdate
    from app.modules.costmodel.service import CostSpineService

    project_id = await _project(pg_session)
    boq_id, _ = await _bill(pg_session, project_id, SPECS[:3])
    service = CostSpineService(pg_session)
    await service.generate_from_boq(project_id, boq_id)
    ids = dict(
        (
            await pg_session.execute(
                select(ControlAccount.code, ControlAccount.id).where(ControlAccount.project_id == project_id)
            )
        ).all()
    )
    with pytest.raises(HTTPException) as err:
        await service.update_account(ids["300"], ControlAccountUpdate(parent_id=ids["331"]))
    assert err.value.status_code == 400

    await service.update_account(ids["330"], ControlAccountUpdate(parent_id=ids["340"]))
    pg_session.expire_all()
    levels = dict(
        (
            await pg_session.execute(
                select(ControlAccount.code, ControlAccount.level).where(ControlAccount.project_id == project_id)
            )
        ).all()
    )
    assert levels == {"300": 1, "340": 2, "330": 3, "331": 4}


async def test_a_company_code_list_is_validated_stored_and_applied(pg_session) -> None:
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session, standard="none")
    service = CostStructureService(pg_session)
    bad = b"code,title,parent\nA,Site,\nA,Again,\nB.1,Walls,Z\n"
    result = await service.import_code_list(
        project_id, filename="list.csv", content=bad, key="company", name="Company", dry_run=False, user_id=None
    )
    assert not result.ok
    assert {i.problem for i in result.issues} == {"duplicate_code", "parent_unknown"}
    assert [c.key for c in await service.list_code_lists(project_id) if c.source == "custom"] == []

    good = b"code,title,parent\nA,Site,\nA.1,Earthworks,A\nB,Building,\nB.1,Walls,B\n"
    result = await service.import_code_list(
        project_id, filename="list.csv", content=good, key="company", name="Company", dry_run=False, user_id=None
    )
    assert result.ok and result.code_list is not None and result.code_list.depth == 2

    applied = await service.apply_code_list(project_id, "company", 1)
    assert applied.accounts_created == 2
    applied = await service.apply_code_list(project_id, "company", None)
    assert applied.accounts_created == 2

    with pytest.raises(HTTPException) as err:
        await service.delete_code_list(project_id, "company")
    assert err.value.detail["problem"] == "code_list_in_use"
    with pytest.raises(HTTPException) as err:
        await service.import_code_list(
            project_id, filename="x.csv", content=good, key="din276", name="Mine", dry_run=True, user_id=None
        )
    assert err.value.status_code == 409


async def test_a_project_without_a_standard_parks_every_position(pg_session) -> None:
    from app.modules.costmodel.service import CostSpineService

    project_id = await _project(pg_session, standard="none")
    boq_id, _ = await _bill(pg_session, project_id, SPECS[:3])
    result = await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    assert (result.standard, result.accounts_created, result.positions_in_suspense) == ("", 0, 3)


async def test_the_bill_shows_each_share_the_cent_its_cost_line_carries(pg_session) -> None:
    """A remainder cent on a tie lands on the same line in the bill's view and in the line estimate."""
    from sqlalchemy import update

    from app.modules.costmodel.models import ControlAccount, CostLine
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_schemas import AllocationRowIn, PositionAllocationRequest
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, ids = await _bill(
        pg_session,
        project_id,
        [
            ("01", "m3", "1", "100.01", "100.01", {"din276": "331"}),
            ("02", "kg", "1", "5", "5.00", {"din276": "340"}),
        ],
    )
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    own = await _line_of(pg_session, ids[0])
    own_account = own.control_account_id
    acct_340 = (
        await pg_session.execute(
            ControlAccount.__table__.select().where(
                ControlAccount.project_id == project_id, ControlAccount.code == "340"
            )
        )
    ).one()
    service = CostStructureService(pg_session)
    out = await service.set_allocation(
        ids[0],
        PositionAllocationRequest(
            mode="percent",
            rows=[
                AllocationRowIn(control_account_id=own_account, share=D("50")),
                AllocationRowIn(control_account_id=acct_340.id, share=D("50")),
            ],
        ),
        "tester",
    )
    line_ids = sorted((r.cost_line_id for r in out.rows), key=str)
    # Make the code order the reverse of the id order, so the two orders a cut could follow disagree.
    for code, line_id in zip(("Z-LAST", "A-FIRST"), line_ids, strict=True):
        await pg_session.execute(update(CostLine).where(CostLine.id == line_id).values(code=code))
    await service.recompute_lines(set(line_ids))
    await pg_session.flush()
    pg_session.expire_all()

    shown = next(p for p in (await service.boq_allocations(boq_id)).positions if p.position_id == ids[0])
    assert sum((r.amount for r in shown.rows), D("0")) == D("100.01")
    estimates = {
        r.id: D(str(r.estimate_amount))
        for r in (await pg_session.execute(CostLine.__table__.select().where(CostLine.id.in_(line_ids)))).all()
    }
    assert {r.cost_line_id: r.amount for r in shown.rows} == estimates
    assert sorted(estimates.values()) == [D("50.00"), D("50.01")]


async def test_a_share_on_a_heading_or_closed_account_is_refused(pg_session) -> None:
    from sqlalchemy import update

    from app.modules.costmodel.models import ControlAccount
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_schemas import AllocationRowIn, PositionAllocationRequest
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, ids = await _bill(pg_session, project_id, SPECS[:3])
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    accounts = {
        r.code: r.id
        for r in (
            await pg_session.execute(ControlAccount.__table__.select().where(ControlAccount.project_id == project_id))
        ).all()
    }
    await pg_session.execute(
        update(ControlAccount).where(ControlAccount.id == accounts["300"]).values(is_leaf_postable=False)
    )
    await pg_session.execute(update(ControlAccount).where(ControlAccount.id == accounts["340"]).values(status="closed"))
    await pg_session.flush()
    pg_session.expire_all()

    service = CostStructureService(pg_session)
    for target in ("300", "340"):
        with pytest.raises(HTTPException) as err:
            await service.set_allocation(
                ids[0],
                PositionAllocationRequest(
                    mode="percent",
                    rows=[
                        AllocationRowIn(control_account_id=accounts["331"], share=D("50")),
                        AllocationRowIn(control_account_id=accounts[target], share=D("50")),
                    ],
                ),
                "tester",
            )
        assert err.value.status_code == 400
        assert err.value.detail["problem"] == "account_not_postable"


async def test_editing_or_deleting_a_position_refreshes_the_cost_lines_it_feeds(pg_session) -> None:
    from sqlalchemy import delete, update

    from app.modules.boq.models import Position
    from app.modules.costmodel.models import ControlAccount
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_schemas import AllocationRowIn, PositionAllocationRequest
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, ids = await _bill(pg_session, project_id, SPECS[:3])
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    service = CostStructureService(pg_session)
    acct_340 = (
        await pg_session.execute(
            ControlAccount.__table__.select().where(
                ControlAccount.project_id == project_id, ControlAccount.code == "340"
            )
        )
    ).one()
    own_account = (await _line_of(pg_session, ids[0])).control_account_id
    await service.set_allocation(
        ids[0],
        PositionAllocationRequest(
            mode="percent",
            rows=[
                AllocationRowIn(control_account_id=own_account, share=D("75")),
                AllocationRowIn(control_account_id=acct_340.id, share=D("25")),
            ],
        ),
        "tester",
    )

    # The bill is re-priced: position 01 goes from 1000.00 to 2000.00, position 02 from 200.00 to 300.00.
    await pg_session.execute(update(Position).where(Position.id == ids[0]).values(unit_rate="200", total="2000.00"))
    await pg_session.execute(update(Position).where(Position.id == ids[1]).values(quantity="7.5", total="300.00"))
    await pg_session.flush()
    assert await service.recompute_after_bill_change({ids[0], ids[1]}, set()) >= 3
    pg_session.expire_all()
    assert D((await _line_of(pg_session, ids[0])).estimate_amount) == D("1500.00")
    assert D((await _line_of(pg_session, ids[1])).estimate_amount) == D("300.00")
    assert await _line_total(pg_session, project_id) == D("2000.00") + D("300.00") + D("300.00")
    assert await service.recompute_after_bill_change({ids[0], ids[1]}, set()) == 0, "nothing left to refresh"

    # Position 02 is deleted: its line keeps nothing.
    line_02 = (await _line_of(pg_session, ids[1])).id
    await pg_session.execute(delete(Position).where(Position.id == ids[1]))
    await pg_session.flush()
    await service.recompute_after_bill_change(set(), {boq_id})
    pg_session.expire_all()
    from app.modules.costmodel.models import CostLine

    assert D((await pg_session.get(CostLine, line_02)).estimate_amount) == D("0")
    assert await _line_total(pg_session, project_id) == D("2000.00") + D("300.00")


async def test_money_on_a_line_without_an_account_is_not_counted_as_covered(pg_session) -> None:
    """A position parked in suspense sits on a cost line, yet it is not on the structure."""
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, ids = await _bill(pg_session, project_id, SPECS)
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)

    bill = await CostStructureService(pg_session).boq_allocations(boq_id)
    cov = bill.coverage
    assert cov.positions_allocated == 4
    assert (cov.positions_in_suspense, cov.value_in_suspense) == (1, D("100.00"))
    assert cov.value_allocated == D("1500.00")
    assert cov.value_unallocated == D("0")
    assert cov.value_allocated + cov.value_in_suspense + cov.value_unallocated == cov.value_total
    assert cov.share_pct == D("93.75"), "money in suspense never reads as covered"
    by_id = {p.position_id: p for p in bill.positions}
    assert by_id[ids[3]].in_suspense and not by_id[ids[3]].rows[0].account_postable
    assert not by_id[ids[0]].in_suspense and by_id[ids[0]].rows[0].account_postable


async def test_a_copied_bill_can_change_the_split_it_inherited(pg_session) -> None:
    """The copy may keep or reweigh the source lines it inherited, but not move onto new ones."""
    from sqlalchemy import select

    from app.modules.boq.models import Position
    from app.modules.boq.service import BOQService
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_schemas import AllocationRowIn, PositionAllocationRequest
    from app.modules.costmodel.structure_service import CostStructureService

    project_id = await _project(pg_session)
    boq_id, ids = await _bill(pg_session, project_id, SPECS[:3])
    await CostSpineService(pg_session).generate_from_boq(project_id, boq_id)
    line_a = (await _line_of(pg_session, ids[0])).id
    line_b = (await _line_of(pg_session, ids[1])).id
    line_c = (await _line_of(pg_session, ids[2])).id
    svc = CostStructureService(pg_session)
    await svc.set_allocation(
        ids[0],
        PositionAllocationRequest(
            rows=[
                AllocationRowIn(cost_line_id=line_a, share=D("50")),
                AllocationRowIn(cost_line_id=line_c, share=D("50")),
            ]
        ),
        None,
    )
    before = await _line_total(pg_session, project_id)

    copy_id = (await BOQService(pg_session).duplicate_boq(boq_id)).id
    pg_session.expire_all()
    copy_01 = (
        await pg_session.execute(select(Position.id).where(Position.boq_id == copy_id, Position.ordinal == "01"))
    ).scalar_one()

    out = await svc.set_allocation(
        copy_01,
        PositionAllocationRequest(
            rows=[
                AllocationRowIn(cost_line_id=line_a, share=D("70")),
                AllocationRowIn(cost_line_id=line_c, share=D("30")),
            ]
        ),
        None,
    )
    assert sorted(r.share for r in out.rows) == [D("30"), D("70")]
    assert await _line_total(pg_session, project_id) == before, "the copy still adds no money to the source lines"

    with pytest.raises(HTTPException) as err:
        await svc.set_allocation(
            copy_01,
            PositionAllocationRequest(
                rows=[
                    AllocationRowIn(cost_line_id=line_a, share=D("50")),
                    AllocationRowIn(cost_line_id=line_b, share=D("50")),
                ]
            ),
            None,
        )
    assert err.value.detail["problem"] == "line_of_other_bill"
