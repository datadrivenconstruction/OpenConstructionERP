# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the bid probes on the fixture course's roofing package.

Figures are the fixture's ``seed.bid_package``. Built through
``BidManagementService`` in the order the engine probe proved: lines, bidders,
invitations, publish, bids recorded BEFORE opening, open, close.
Alderby leaves the mandatory F02 line blank, so its bid is invalid and it has
no levelling row: the probe says ``not_found``, never 0.

``bid.leveling`` is the one probe that can write. In ``check`` mode it
recomputes the levelling table, so the rows it reads are new rows with the
same figures. In ``read`` mode, the readback GET (decision 36), it reads the
rows that are there and writes nothing; with none it asks the learner to open
the levelling view.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.modules.bid_management.models import BidComparison, BidLeveling
from app.modules.bid_management.schemas import (
    BidAwardCreate,
    BidderCreate,
    BidInvitationCreate,
    BidPackageCreate,
    BidPackageLineItemCreate,
    BidSubmissionCreate,
    BidSubmissionLineCreate,
)
from app.modules.bid_management.service import BidManagementService
from app.modules.trainer.checker import run_task_probes
from app.modules.trainer.checker.matching import Expectation
from app.modules.trainer.checker.registry import OPEN_LEVELING_KEY, run_probe
from app.modules.trainer.spec import CourseSpec, normalise_course_dict
from app.modules.trainer.validators import build_ledger

COURSE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "trainer" / "course_fixture_v1.json"
MONEY = {"kind": "money", "tolerance": Decimal("0.01"), "currency": "GBP"}
LINES = {"F01": ("m2", Decimal(180)), "F02": ("m", Decimal(64))}
BIDS = {
    "Alderby Roofing": {"F01": Decimal("61.00")},  # F02 left blank
    "Brackenfold Roofs": {"F01": Decimal("58.50"), "F02": Decimal("11.25")},
    "Corrow and Sons": {"F01": Decimal("61.50"), "F02": Decimal("12.50")},
}


async def _package(world, project_id: uuid.UUID) -> tuple[Any, dict[str, Any]]:
    service = BidManagementService(world.session)
    user = str(world.user_id)
    package = await service.create_package(
        BidPackageCreate(
            project_id=project_id, code=f"FX-RF-{uuid.uuid4().hex[:6]}", title="Roof coverings", currency="GBP"
        ),
        user_id=user,
    )
    lines = {}
    for i, (code, (unit, qty)) in enumerate(LINES.items()):
        lines[code] = await service.create_line(
            BidPackageLineItemCreate(
                package_id=package.id, code=code, description=code, unit=unit, quantity=qty, order_index=i
            )
        )
    bidders, invitations = {}, {}
    for name in BIDS:
        bidder = await service.create_bidder(BidderCreate(package_id=package.id, company_name=name))
        bidders[name] = bidder
        invitations[name] = await service.create_invitation(
            BidInvitationCreate(
                package_id=package.id,
                bidder_ref_id=bidder.id,
                invitee_email=f"{uuid.uuid4().hex[:6]}@example.com",
                invitee_company_name=name,
            )
        )
    await service.publish_package(package.id, user_id=user)
    for name, rates in BIDS.items():
        total = sum(LINES[c][1] * r for c, r in rates.items())
        submission = await service.record_submission(
            BidSubmissionCreate(
                invitation_id=invitations[name].id, bidder_id=bidders[name].id, total_amount=total, currency="GBP"
            )
        )
        for code, rate in rates.items():
            await service.create_submission_line(
                BidSubmissionLineCreate(
                    submission_id=submission.id,
                    line_item_id=lines[code].id,
                    unit_price=rate,
                    quantity_priced=LINES[code][1],
                )
            )
    await service.open_bids(package.id)
    await service.close_package(package.id)
    return package, bidders


async def _probe(world, refs: dict, type_name: str, args: dict, expectation: Expectation, mode: str = "check"):
    return await run_probe(world.session, {"type": type_name, "args": args}, world.ctx(refs, mode=mode), expectation)


def _leveling_args(bidder: str, field: str = "normalized_total") -> dict:
    return {"package_ref": "bid_package.main", "bidder_name": bidder, "field": field}


async def _rows(world, package_id: uuid.UUID) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
    comparison = (
        await world.session.execute(select(BidComparison).where(BidComparison.package_id == package_id))
    ).scalar_one_or_none()
    if comparison is None:
        return {}
    rows = (
        (await world.session.execute(select(BidLeveling).where(BidLeveling.comparison_id == comparison.id)))
        .scalars()
        .all()
    )
    return {r.id: (r.bidder_id, r.normalized_total) for r in rows}


async def test_leveling_recomputes_its_rows_and_reads_the_normalised_total(world) -> None:
    package, bidders = await _package(world, world.project_id)
    refs = {"bid_package.main": package.id}
    expected = Expectation(value=Decimal("11250.00"), **MONEY)

    # No comparison exists yet: the probe creates it (documented side effect).
    first = await _probe(world, refs, "bid.leveling", _leveling_args("Brackenfold Roofs"), expected)
    assert (first.value, first.status) == (Decimal("11250.00"), "match")
    before = await _rows(world, package.id)
    assert {b for b, _t in before.values()} == {bidders["Brackenfold Roofs"].id, bidders["Corrow and Sons"].id}

    rank = await _probe(
        world, refs, "bid.leveling", _leveling_args("brackenfold roofs", "rank"), Expectation(value=1, kind="number")
    )
    assert (rank.value, rank.status) == (Decimal(1), "match")

    # compute_leveling deleted the rows the first read left and wrote new ones.
    after = await _rows(world, package.id)
    assert set(before).isdisjoint(after)
    assert sorted(before.values()) == sorted(after.values())


async def test_an_excluded_bidder_has_no_leveling_row_and_reads_as_missing(world) -> None:
    package, _bidders = await _package(world, world.project_id)
    result = await _probe(
        world,
        {"bid_package.main": package.id},
        "bid.leveling",
        _leveling_args("Alderby Roofing"),
        Expectation(value=Decimal("11780.00"), **MONEY),
    )
    assert (result.value, result.status, result.is_missing) == (None, "unknown", True)

    valid = await _probe(
        world,
        {"bid_package.main": package.id},
        "bid.submission",
        {"package_ref": "bid_package.main", "bidder_name": "Alderby Roofing", "field": "is_valid"},
        Expectation(value=False, kind="bool"),
    )
    assert (valid.value, valid.status) == (False, "match")
    total = await _probe(
        world,
        {"bid_package.main": package.id},
        "bid.submission",
        {"package_ref": "bid_package.main", "bidder_name": "Alderby Roofing", "field": "total_amount"},
        Expectation(value=Decimal("10980.00"), **MONEY),
    )
    assert (total.value, total.status) == (Decimal("10980.00"), "match")


async def test_the_award_is_read_by_amount_and_by_bidder_name(world) -> None:
    package, bidders = await _package(world, world.project_id)
    refs = {"bid_package.main": package.id}
    missing = await _probe(
        world,
        refs,
        "bid.award",
        {"package_ref": "bid_package.main", "field": "awarded_amount"},
        Expectation(value=Decimal("11250.00"), **MONEY),
    )
    assert missing.is_missing

    await BidManagementService(world.session).award_package(
        package.id,
        BidAwardCreate(
            package_id=package.id,
            awarded_bidder_id=bidders["Brackenfold Roofs"].id,
            awarded_amount=Decimal("11250.00"),
        ),
        user_id=str(world.user_id),
    )
    amount = await _probe(
        world,
        refs,
        "bid.award",
        {"package_ref": "bid_package.main", "field": "awarded_amount"},
        Expectation(value=Decimal("11250.00"), **MONEY),
    )
    assert (amount.value, amount.status) == (Decimal("11250.00"), "match")
    name = await _probe(
        world,
        refs,
        "bid.award",
        {"package_ref": "bid_package.main", "field": "awarded_bidder_name"},
        Expectation(value="Brackenfold Roofs", kind="text"),
    )
    assert (name.value, name.status) == ("Brackenfold Roofs", "match")


async def _comparisons(world, package_id: uuid.UUID) -> list[tuple[uuid.UUID, Any]]:
    rows = (
        (await world.session.execute(select(BidComparison).where(BidComparison.package_id == package_id)))
        .scalars()
        .all()
    )
    return [(c.id, c.computed_at) for c in rows]


async def test_a_readback_before_levelling_writes_nothing_and_asks_for_the_levelling_view(world) -> None:
    package, _bidders = await _package(world, world.project_id)
    result = await _probe(
        world,
        {"bid_package.main": package.id},
        "bid.leveling",
        _leveling_args("Brackenfold Roofs"),
        Expectation(value=Decimal("11250.00"), **MONEY),
        mode="read",
    )
    assert (result.value, result.status, result.is_missing) == (None, "unknown", True)
    assert result.detail == f"not_computed: {OPEN_LEVELING_KEY}"
    assert await _comparisons(world, package.id) == []


async def test_the_readback_get_reads_existing_rows_and_never_recomputes_them(world) -> None:
    raw = json.loads(COURSE_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    course_dict, problems = normalise_course_dict(raw)
    assert problems == []
    t3 = next(t for t in CourseSpec.model_validate(course_dict).tasks if t.id == "t3-tender")
    package, _bidders = await _package(world, world.project_id)
    ctx = world.ctx({"bid_package.main": package.id})

    checked = await run_task_probes(
        world.session, t3, ctx, currency="GBP", ledger=build_ledger(course_dict), mode="check"
    )
    leveling = next(i for i, r in enumerate(t3.readback) if r.probe is not None and r.probe.type == "bid.leveling")
    assert checked[leveling].value == Decimal("11250.00")
    rows, comparisons = await _rows(world, package.id), await _comparisons(world, package.id)
    assert rows

    for _ in range(2):
        read = await run_task_probes(
            world.session, t3, ctx, currency="GBP", ledger=build_ledger(course_dict), mode="read"
        )
        assert read[leveling].value == Decimal("11250.00")
        assert await _rows(world, package.id) == rows
        assert await _comparisons(world, package.id) == comparisons
