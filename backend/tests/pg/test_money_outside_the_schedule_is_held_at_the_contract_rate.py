# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Money no schedule line carries is held at the contract's own rate, whatever a ladder says.

A retention ladder is a rate against percent complete on the schedule of
values: here 10% until the job is half done, then nothing. A month billed
with no schedule line behind it is not on that measure, so it is held at the
flat retention percent the contract states, even at a point where the ladder
has stopped retaining on the schedule, and the continuation sheet carries it
on a row of its own.

This pins that choice. A change that starts reading the ladder for such money
would hold nothing on it past half way, and has to change this test and say
why.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from tests.pg.test_retention_line5_counts_money_outside_the_schedule_once import (
    LADDER_ZERO_PAST_HALF,
    _job,
    _lineless_month,
    _schedule_month,
    _sheet,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _rules():
    register_contracts_validation_rules()


async def test_a_lineless_month_past_the_ladder_step_is_held_at_the_contract_rate(pg_session) -> None:
    svc = ContractsService(pg_session)
    job = await _job(pg_session, [("A", "100000"), ("B", "100000")], ladder=LADDER_ZERO_PAST_HALF)
    await _schedule_month(svc, pg_session, job, 1, {"A": "100000"})

    # Half the schedule is done, and from here the ladder retains nothing.
    policy = await svc.retention_policy(job.contract)
    assert policy.rate_at(Decimal("50")) == Decimal("0")
    assert Decimal(str(job.contract.retention_percent)) == Decimal("10")

    month2 = await _sheet(svc, await _lineless_month(svc, pg_session, job, 2, "20000"))
    # 10% of the 20,000, not the ladder's nothing.
    assert month2.retention_amount == Decimal("2000.00")
    assert month2.line5 == Decimal("12000.00")

    month3 = await _sheet(svc, await _schedule_month(svc, pg_session, job, 3, {"B": "40000"}))
    # The schedule accrues nothing past half way; the row keeps its 2,000.
    assert month3.retention_amount == Decimal("0.00")
    assert month3.row_i == Decimal("2000.00")
    assert month3.line5 == Decimal("12000.00")
