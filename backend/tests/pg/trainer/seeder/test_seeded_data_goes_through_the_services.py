# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the fixture course seeded through the real services, stage by stage.

Every stage runs through :func:`execute_stage` on a real PostgreSQL session, so
what is asserted here is what the services stored, not what the seeder meant:
the project the learner owns, the bill with its unpriced line, bids that stay
valid, a contract signed through the compliance gate with its value frozen,
readings stamped inside the claim period and picked up by the claim populate,
and a second run that creates nothing.

The fixture period (2026-10-01 to 2026-10-31) contains the day these tests were
written, so "populate at period_to finds the readings" alone would pass even if
the seeder never backdated. The discriminating checks are the exact stamp and a
claim that ends the day before it, which must find nothing.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.events import event_bus
from app.dependencies import verify_project_access
from app.modules.bid_management.models import Bidder, BidPackage, BidPackageLineItem, BidSubmission
from app.modules.bid_management.schemas import BidSubmissionCreate
from app.modules.bid_management.service import BidManagementService
from app.modules.boq.models import BOQ, Position
from app.modules.boq.service import BOQService
from app.modules.contracts.models import Contract, ContractLine
from app.modules.contracts.schemas import ProgressClaimCreate
from app.modules.contracts.service import BOQ_POSITION_META_KEY, ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.finance.service import _safe_decimal
from app.modules.progress.models import ProgressEntry
from app.modules.projects.models import Project
from app.modules.trainer.loader import parse_course_bytes
from app.modules.trainer.seeder import (
    SeedContext,
    SeedError,
    build_plan,
    execute_enrolment,
    execute_stage,
    seeding,
    seeding_enrolment,
)
from app.modules.trainer.seeder.plan import SeedPlan
from app.modules.trainer.spec import Stage
from app.modules.users.models import User
from app.modules.variations.models import VariationRequest
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

COURSE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "trainer" / "course_fixture_v1.json"

ON_ENROL = Stage("on_enrol")
T1, T3, T4, T5 = (Stage("on_unlock", n) for n in (1, 3, 4, 5))


def _raw() -> dict[str, Any]:
    return json.loads(COURSE_PATH.read_text(encoding="utf-8"))


def _plan(raw: dict[str, Any] | None = None) -> SeedPlan:
    parsed = parse_course_bytes(json.dumps(raw or _raw()).encode("utf-8"), "course_fixture_v1.json")
    assert parsed.errors == [], parsed.errors
    assert parsed.spec is not None
    return build_plan(parsed.spec)


async def _user(session, role: str) -> User:
    user = User(id=uuid.uuid4(), email=f"learner-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", role=role)
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def session():
    # The contracts rule set is registered by the module's startup hook, which
    # no test process runs; the signing gate needs it.
    register_contracts_validation_rules()
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def learner(session) -> User:
    # Provisioning (stream D) makes a learner a manager; the seeder never
    # touches the global role, it makes the learner the project owner.
    return await _user(session, "manager")


def _ctx(learner: User) -> SeedContext:
    return SeedContext(enrolment_id=uuid.uuid4(), learner_id=learner.id)


async def _run(session, plan: SeedPlan, ctx: SeedContext, upto: int) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    for stage in plan.stages:
        if stage.kind == "on_unlock" and (stage.task_n or 0) > upto:
            break
        refs = await execute_stage(session, plan, stage, ctx, refs)
    return refs


async def _count(session, stmt) -> int:
    return int((await session.execute(stmt)).scalar_one())


async def _project_rows(session, project_id: uuid.UUID) -> dict[str, int]:
    """Every row the seeder writes, counted inside the project."""
    return {
        "boq": await _count(session, select(func.count()).select_from(BOQ).where(BOQ.project_id == project_id)),
        "position": await _count(
            session,
            select(func.count())
            .select_from(Position)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id),
        ),
        "package": await _count(
            session, select(func.count()).select_from(BidPackage).where(BidPackage.project_id == project_id)
        ),
        "package_line": await _count(
            session,
            select(func.count())
            .select_from(BidPackageLineItem)
            .join(BidPackage, BidPackageLineItem.package_id == BidPackage.id)
            .where(BidPackage.project_id == project_id),
        ),
        "bidder": await _count(
            session,
            select(func.count())
            .select_from(Bidder)
            .join(BidPackage, Bidder.package_id == BidPackage.id)
            .where(BidPackage.project_id == project_id),
        ),
        "submission": await _count(
            session,
            select(func.count())
            .select_from(BidSubmission)
            .join(Bidder, BidSubmission.bidder_id == Bidder.id)
            .join(BidPackage, Bidder.package_id == BidPackage.id)
            .where(BidPackage.project_id == project_id),
        ),
        "contract": await _count(
            session, select(func.count()).select_from(Contract).where(Contract.project_id == project_id)
        ),
        "contract_line": await _count(
            session,
            select(func.count())
            .select_from(ContractLine)
            .join(Contract, ContractLine.contract_id == Contract.id)
            .where(Contract.project_id == project_id),
        ),
        "progress": await _count(
            session, select(func.count()).select_from(ProgressEntry).where(ProgressEntry.project_id == project_id)
        ),
        "variation_request": await _count(
            session,
            select(func.count()).select_from(VariationRequest).where(VariationRequest.project_id == project_id),
        ),
    }


# ── S0: enrolment ────────────────────────────────────────────────────────────


async def test_on_enrol_creates_the_learners_project_and_nothing_else(session, learner) -> None:
    refs = await execute_stage(session, _plan(), ON_ENROL, _ctx(learner), {})
    assert set(refs) == {"project"}
    project = await session.get(Project, uuid.UUID(refs["project"]))
    assert project is not None
    assert project.owner_id == learner.id
    assert project.country_code == "GB"
    assert project.currency == "GBP"
    assert project.address["subdivision"] == "GB-ENG"
    assert (await _project_rows(session, project.id))["boq"] == 0


async def test_the_enrolment_seed_creates_the_project_and_the_main_bill(session, learner) -> None:
    refs = await execute_enrolment(session, _plan(), _ctx(learner), {})
    project_id = uuid.UUID(refs["project"])
    boq = await session.get(BOQ, uuid.UUID(refs["boq.main"]))
    assert boq is not None
    assert boq.project_id == project_id
    assert boq.name == "Quillmere Depot main bill"
    assert set(refs["boq.main.positions"]) == {"01.001", "01.002", "01.003"}
    assert set(refs["boq.main.sections"]) == {"01"}

    unpriced = await session.get(Position, uuid.UUID(refs["boq.main.positions"]["01.002"]))
    assert unpriced is not None
    assert Decimal(str(unpriced.unit_rate)) == 0
    assert unpriced.parent_id == uuid.UUID(refs["boq.main.sections"]["01"])
    assert unpriced.classification == {"nrm": "2.5"}

    # The bill the learner opens totals what the course says before task 1.
    breakdown = await BOQService(session).get_cost_breakdown(boq.id)
    assert Decimal(str(breakdown.direct_cost)) == Decimal("16092.00")


async def test_boq_positions_have_events(session, learner) -> None:
    # Through the service, not the ORM: every seeded position publishes
    # ``boq.position.created``. The BOQ service defers it to the commit, so the
    # caller holds ``seeding`` across its commit, and the handler (a detached
    # task, which copies the context) sees which enrolment is seeding.
    ctx = _ctx(learner)
    seen: list[tuple[str, uuid.UUID | None]] = []

    async def record(event) -> None:
        seen.append((event.data["ordinal"], seeding_enrolment()))

    event_bus.subscribe("boq.position.created", record)
    try:
        with seeding(ctx.enrolment_id):
            await execute_enrolment(session, _plan(), ctx, {})
            await session.commit()
        for _ in range(100):
            if len(seen) >= 3:
                break
            await asyncio.sleep(0.02)
    finally:
        event_bus.unsubscribe("boq.position.created", record)
    assert sorted(seen) == [(o, ctx.enrolment_id) for o in ("01.001", "01.002", "01.003")]


async def test_the_learner_owns_the_project_and_nobody_else_reaches_it(session, learner) -> None:
    refs = await execute_enrolment(session, _plan(), _ctx(learner), {})
    project_id = uuid.UUID(refs["project"])
    await verify_project_access(project_id, str(learner.id), session)
    other = await _user(session, "manager")
    with pytest.raises(HTTPException) as info:
        await verify_project_access(project_id, str(other.id), session)
    assert info.value.status_code == 404


# ── S3: bid package ──────────────────────────────────────────────────────────


async def test_bids_recorded_before_open_are_valid(session, learner) -> None:
    refs = await _run(session, _plan(), _ctx(learner), upto=3)
    package = await session.get(BidPackage, uuid.UUID(refs["bid_package.main"]))
    assert package is not None
    assert package.status == "published"
    assert Decimal(str(package.total_budget_estimate)) == Decimal("11500.00")
    totals = {"Alderby Roofing": "10980.00", "Brackenfold Roofs": "11250.00", "Corrow and Sons": "11870.00"}
    assert set(refs["bid_package.main.submissions"]) == set(totals)
    for bidder, total in totals.items():
        submission = await session.get(BidSubmission, uuid.UUID(refs["bid_package.main.submissions"][bidder]))
        assert submission is not None
        assert Decimal(str(submission.total_amount)) == Decimal(total)
    # The learner opens the bids. Validity is decided at opening, so the seeded
    # bids are judged on their content: the two fully priced bids are valid, and
    # Alderby, who left the mandatory flashing line blank, is not.
    await BidManagementService(session).open_bids(package.id)
    validity = {}
    for bidder, submission_id in refs["bid_package.main.submissions"].items():
        submission = await session.get(BidSubmission, uuid.UUID(submission_id))
        await session.refresh(submission)
        validity[bidder] = submission.is_valid
    assert validity == {"Alderby Roofing": False, "Brackenfold Roofs": True, "Corrow and Sons": True}


async def test_a_bid_the_learner_records_is_left_open_for_the_learner(session, learner) -> None:
    raw = _raw()
    alderby = raw["seed"]["bid_package"]["bids"][0]
    alderby["recorded_by"] = "learner in T3 (Record bid)"
    raw["seed"]["bid_package"]["scope_lines"][0]["boq_position"] = "01.003"
    refs = await _run(session, _plan(raw), _ctx(learner), upto=3)
    assert set(refs["bid_package.main.submissions"]) == {"Brackenfold Roofs", "Corrow and Sons"}
    assert "Alderby Roofing" in refs["bid_package.main.bidders"]

    # The learner records it on the seeded invitation, before opening: no 409.
    svc = BidManagementService(session)
    learner_bid = await svc.record_submission(
        BidSubmissionCreate(
            invitation_id=uuid.UUID(refs["bid_package.main.invitations"]["Alderby Roofing"]),
            bidder_id=uuid.UUID(refs["bid_package.main.bidders"]["Alderby Roofing"]),
            total_amount=Decimal("10980.00"),
            currency="GBP",
        )
    )
    assert learner_bid.id is not None

    # The scope line links the bill position the course names, and nothing more.
    line = await session.get(BidPackageLineItem, uuid.UUID(refs["bid_package.main.lines"]["F01"]))
    assert line.boq_position_id == uuid.UUID(refs["boq.main.positions"]["01.003"])
    other = await session.get(BidPackageLineItem, uuid.UUID(refs["bid_package.main.lines"]["F02"]))
    assert other.boq_position_id is None


async def test_package_code_is_unique_per_learner(session, learner) -> None:
    plan = _plan()
    first = await _run(session, plan, _ctx(learner), upto=3)
    second_learner = await _user(session, "manager")
    second = await _run(session, plan, _ctx(second_learner), upto=3)
    codes = {(await session.get(BidPackage, uuid.UUID(refs["bid_package.main"]))).code for refs in (first, second)}
    assert len(codes) == 2


# ── S4: contract and readings ────────────────────────────────────────────────


async def test_contract_signs_through_the_compliance_gate(session, learner) -> None:
    refs = await _run(session, _plan(), _ctx(learner), upto=4)
    contract = await session.get(Contract, uuid.UUID(refs["contract.main"]))
    assert contract is not None
    await session.refresh(contract)
    assert contract.status == "active"
    assert contract.signed_at
    assert contract.original_contract_value == contract.total_value == Decimal("34502.82")
    assert "compliance_validation" in (contract.metadata_ or {})

    lines = {line.code: line for line in await ContractsService(session).line_repo.list_for_contract(contract.id)}
    assert set(lines) == {"C01", "C02", "C03", "C04"}
    for line in lines.values():
        assert line.unit == "item"
        assert line.metadata_["classification"]
    assert lines["C04"].metadata_["classification"] == {"nrm": "0.5"}
    # boq:<ordinal> links the main bill, csa the contract-sum-analysis bill, none nothing.
    assert lines["C01"].metadata_[BOQ_POSITION_META_KEY] == refs["boq.main.positions"]["01.001"]
    assert lines["C03"].metadata_[BOQ_POSITION_META_KEY] == refs["boq.csa.positions"]["C03"]
    assert BOQ_POSITION_META_KEY not in lines["C04"].metadata_
    csa_position = await session.get(Position, uuid.UUID(refs["boq.csa.positions"]["C03"]))
    assert Decimal(str(csa_position.total)) == Decimal("11250.00")


async def test_retention_is_stored_as_percent(session, learner) -> None:
    raw = _raw()
    # A fraction in the spec reaches the percent column as a percent.
    raw["seed"]["contract"]["retention_percent"] = {"value": 0.05, "unit": "fraction"}
    refs = await _run(session, _plan(raw), _ctx(learner), upto=4)
    contract = await session.get(Contract, uuid.UUID(refs["contract.main"]))
    assert contract.retention_percent == Decimal("5.00")


async def test_vat_rate_is_stored_as_percent(session, learner) -> None:
    refs = await _run(session, _plan(), _ctx(learner), upto=4)
    contract = await session.get(Contract, uuid.UUID(refs["contract.main"]))
    stored = contract.metadata_["einvoice"]["vat_rate"]
    assert stored == 20
    assert isinstance(stored, int)
    # What the receivable reads: a percent, not 0 from an object.
    assert _safe_decimal(stored, Decimal("0")) == Decimal("20")


async def test_no_vat_rate_writes_no_einvoice_key(session, learner) -> None:
    raw = _raw()
    raw["seed"]["contract"]["vat_rate_percent"] = None
    refs = await _run(session, _plan(raw), _ctx(learner), upto=4)
    contract = await session.get(Contract, uuid.UUID(refs["contract.main"]))
    assert "einvoice" not in (contract.metadata_ or {})


async def test_backdated_readings_are_stamped_inside_the_period(session, learner) -> None:
    refs = await _run(session, _plan(), _ctx(learner), upto=4)
    assert set(refs["progress.1"]) == {"C01", "C02", "C03"}
    stamp = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    seqs = []
    for line_code, entry_id in refs["progress.1"].items():
        entry = await session.get(ProgressEntry, uuid.UUID(entry_id))
        await session.refresh(entry)
        assert entry.recorded_at == stamp, line_code
        assert entry.period_label == "2026-10"
        assert entry.recorded_by == str(learner.id)
        assert entry.metadata_ == {"trainer_seed": True}
        assert uuid.UUID(refs["contract.main.position_links"][line_code]) == entry.boq_position_id
        seqs.append(entry.seq)
    assert seqs == sorted(seqs)


async def test_backdated_readings_are_picked_up_by_populate(session, learner) -> None:
    refs = await _run(session, _plan(), _ctx(learner), upto=4)
    svc = ContractsService(session)
    claim = await svc.create_progress_claim(
        ProgressClaimCreate(
            contract_id=uuid.UUID(refs["contract.main"]),
            period_start="2026-10-01",
            period_end="2026-10-31",
            claim_date="2026-10-31",
        )
    )
    preview = await svc.populate_claim_from_progress(claim.id)
    by_code = {item["contract_line_code"]: item for item in preview["items"]}
    assert set(by_code) == {"C01", "C02", "C03"}
    assert by_code["C01"]["period_completed_value"] == Decimal("4977.00")
    assert by_code["C02"]["period_completed_value"] == Decimal("7161.00")
    assert by_code["C03"]["period_completed_value"] == Decimal("0")
    assert preview["gross"] == Decimal("12138.00")
    assert preview["skipped_unlinked"] == 1  # C04, progress_link none
    assert preview["skipped_no_progress"] == 0


async def test_a_claim_cut_off_before_the_stamp_reads_no_reading(session, learner) -> None:
    # Discriminating: an unstamped reading carries today's date, which a claim
    # ending 2026-10-29 would read. The seeded stamp is 2026-10-30, so it must not.
    refs = await _run(session, _plan(), _ctx(learner), upto=4)
    svc = ContractsService(session)
    claim = await svc.create_progress_claim(
        ProgressClaimCreate(
            contract_id=uuid.UUID(refs["contract.main"]),
            period_start="2026-10-01",
            period_end="2026-10-29",
            claim_date="2026-10-29",
        )
    )
    preview = await svc.populate_claim_from_progress(claim.id)
    assert preview["items"] == []
    assert preview["skipped_no_progress"] == 3
    assert preview["gross"] == Decimal("0")


# ── S5: variation request ────────────────────────────────────────────────────


async def test_the_variation_request_is_a_draft_without_a_cost(session, learner) -> None:
    refs = await _run(session, _plan(), _ctx(learner), upto=5)
    request = await session.get(VariationRequest, uuid.UUID(refs["variation_request.1"]))
    assert request is not None
    assert request.status == "draft"
    assert request.estimated_cost_impact == Decimal("0")
    assert request.title == "Rooflights instead of part of the roof covering"


# ── Idempotency and failure ──────────────────────────────────────────────────


async def test_a_second_run_creates_nothing(session, learner) -> None:
    plan = _plan()
    ctx = _ctx(learner)
    refs = await _run(session, plan, ctx, upto=5)
    project_id = uuid.UUID(refs["project"])
    before = await _project_rows(session, project_id)
    assert before == {
        "boq": 2,  # main bill and contract sum analysis
        "position": 5,  # main bill: one section row and three positions; analysis: C03
        "package": 1,
        "package_line": 2,
        "bidder": 3,
        "submission": 3,
        "contract": 1,
        "contract_line": 4,
        "progress": 3,
        "variation_request": 1,
    }
    again = await execute_enrolment(session, plan, ctx, refs)
    for stage in plan.stages:
        again = await execute_stage(session, plan, stage, ctx, again)
    assert again == refs
    assert await _project_rows(session, project_id) == before


async def test_readings_are_written_once(session, learner) -> None:
    plan = _plan()
    ctx = _ctx(learner)
    refs = await _run(session, plan, ctx, upto=4)
    project_id = uuid.UUID(refs["project"])
    await execute_stage(session, plan, T4, ctx, refs)
    assert (await _project_rows(session, project_id))["progress"] == 3


async def test_a_failed_stage_keeps_neither_rows_nor_refs(session, learner) -> None:
    raw = _raw()
    # An NRM code the GB signing gate refuses: the contract stage fails at signing.
    raw["seed"]["contract"]["schedule_of_values"][0]["metadata"]["classification"] = {"nrm": "not-a-code"}
    plan = _plan(raw)
    ctx = _ctx(learner)
    refs = await _run(session, plan, ctx, upto=3)
    before = await _project_rows(session, uuid.UUID(refs["project"]))
    with pytest.raises(SeedError) as info:
        await execute_stage(session, plan, T4, ctx, refs)
    assert info.value.step == "contract.main"
    assert info.value.stage == "on_unlock(4)"
    assert "HTTP 422" in str(info.value)  # the compliance gate, not an earlier step
    assert "nrm" in str(info.value).lower()
    assert "contract.main" not in refs
    assert await _project_rows(session, uuid.UUID(refs["project"])) == before
