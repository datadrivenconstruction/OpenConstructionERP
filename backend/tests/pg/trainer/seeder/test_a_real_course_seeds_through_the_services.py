# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: one real course file, planned and seeded through the services.

Real course files never enter the repo (risk R13, decision 17). This test reads
one from ``OE_TRAINER_COURSES_DIR`` and is skipped when the variable is unset,
which is every CI run. The file goes through the loader's own parse; a file the
shape gate refuses fails the test with the loader's error list, and nothing
here maps an old key to a new one.

The brief asked for one course (the UK one, whose bill names every ordinal
itself); all four run, one case each. The discriminating checks: the seeded bill totals what the course says before task
1, the contract signs, and the claim populate at the period end bills exactly
the values the course states for its readings.
"""

from __future__ import annotations

import os
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from app.modules.boq.service import BOQService
from app.modules.contracts.models import Contract
from app.modules.contracts.schemas import ProgressClaimCreate
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.trainer.loader import parse_course_bytes
from app.modules.trainer.seeder import SeedContext, build_plan, execute_stage
from app.modules.trainer.seeder.plan import bid_recorded_by_seed
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

CENT = Decimal("0.01")

COURSE_FILES = (
    "course_tallowgate_v1.json",
    "course_erlengrund_de_v1.json",
    "course_landrevel_fr_v1.json",
    "course_corvennick_us_v1.json",
)


def _course_path(name: str) -> Path:
    directory = os.environ.get("OE_TRAINER_COURSES_DIR", "").strip()
    if not directory:
        pytest.skip("OE_TRAINER_COURSES_DIR is not set; real course files live outside the repo")
    path = Path(directory) / name
    if not path.is_file():
        pytest.skip(f"{name} is not in OE_TRAINER_COURSES_DIR")
    return path


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        yield s


@pytest.mark.parametrize("course_file", COURSE_FILES)
async def test_a_real_course_seeds_through_the_services(session, course_file: str) -> None:
    parsed = parse_course_bytes(_course_path(course_file).read_bytes(), course_file)
    if parsed.errors or parsed.spec is None:
        pytest.fail(f"{course_file} fails the course shape:\n" + "\n".join(parsed.errors))
    plan = build_plan(parsed.spec)
    course = plan.course

    learner = User(
        id=uuid.uuid4(), email=f"learner-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", role="manager"
    )
    session.add(learner)
    await session.flush()
    ctx = SeedContext(enrolment_id=uuid.uuid4(), learner_id=learner.id)

    # The checks below are the point of the test; a course without the blocks
    # they read would pass vacuously, so their presence is asserted first.
    seed = course.seed
    assert seed.boq is not None
    assert seed.boq.direct_cost_before_t1 is not None
    assert seed.boq.direct_cost_before_t1.value is not None
    assert seed.contract is not None
    assert seed.progress_readings
    assert seed.bid_package is not None

    refs: dict = {}
    direct_cost_checked = False
    for stage in plan.stages:
        refs = await execute_stage(session, plan, stage, ctx, refs)
        # The bill as seeded, before task 1 prices anything (FR seeds it on_enrol).
        if stage == seed.boq.parsed_stage:
            breakdown = await BOQService(session).get_cost_breakdown(uuid.UUID(refs["boq.main"]))
            assert Decimal(str(breakdown.direct_cost)) == seed.boq.direct_cost_before_t1.value
            direct_cost_checked = True
    assert direct_cost_checked

    # The bid a task asks the learner to record is left open on its invitation.
    learner_bids = {b.bidder for b in seed.bid_package.bids if not bid_recorded_by_seed(b)}
    assert learner_bids <= set(refs["bid_package.main.invitations"])
    assert not learner_bids & set(refs["bid_package.main.submissions"])

    contract = await session.get(Contract, uuid.UUID(refs["contract.main"]))
    await session.refresh(contract)
    assert contract.status == "active"
    assert contract.original_contract_value == seed.contract.value.value

    # The first valuation; a later one bills against the first once it is committed.
    entry = seed.progress_readings[0]
    svc = ContractsService(session)
    claim = await svc.create_progress_claim(
        ProgressClaimCreate(
            contract_id=contract.id,
            period_start=entry.period_from.isoformat(),
            period_end=entry.period_to.isoformat(),
            claim_date=entry.period_to.isoformat(),
        )
    )
    preview = await svc.populate_claim_from_progress(claim.id)
    # The preview carries the line column's four decimals (167435.73 x 30 % =
    # 50230.719); a course states money to the cent, so both meet at the cent.
    billed = {
        item["contract_line_code"]: Decimal(item["period_completed_value"]).quantize(CENT, ROUND_HALF_UP)
        for item in preview["items"]
    }
    stated = {r.line_code: r.value for r in entry.readings if r.value is not None}
    assert stated
    assert {code: billed.get(code) for code in stated} == stated
