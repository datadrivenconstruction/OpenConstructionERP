"""Money inputs beyond the column range are refused with a 422, not a database overflow."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.contracts import schemas as c
from app.modules.variations import schemas as v

HUGE = "1e30"


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (c.ContractCreate, {"code": "A", "contract_type": "lump_sum", "project_id": uuid4(), "total_value": HUGE}),
        (c.ContractUpdate, {"total_value": HUGE}),
        (c.ContractLineUpdate, {"quantity": HUGE}),
        (c.ContractLineUpdate, {"unit_rate": "-" + HUGE}),
        (c.RetentionReleaseCreate, {"event": "practical_completion", "amount": HUGE}),
        (c.ContractSecurityCreate, {"contract_id": uuid4(), "amount": HUGE}),
        (c.FeeStructureCreate, {"contract_id": uuid4(), "fee_percent": "101"}),
        (c.LDClauseCreate, {"contract_id": uuid4(), "per_day_amount": HUGE}),
        (c.ProgressClaimLineUpdate, {"period_completed_value": HUGE}),
        (c.ProgressClaimLineCreate, {"progress_claim_id": uuid4(), "contract_line_id": uuid4(), "certified_qty": HUGE}),
        (v.VariationRequestUpdate, {"estimated_cost_impact": HUGE}),
        (v.VariationOrderUpdate, {"final_cost_impact": "-" + HUGE}),
        (v.DisruptionClaimCreate, {"cost_amount": HUGE}),
        (v.DisruptionClaimCreate, {"measured_quantity": HUGE}),
    ],
)
def test_oversized_money_is_a_validation_error(model, kwargs):
    with pytest.raises(ValidationError):
        model(**kwargs)


def test_ordinary_amounts_still_pass():
    assert v.VariationRequestUpdate(estimated_cost_impact="-250000.50").estimated_cost_impact
    assert c.ContractUpdate(total_value="5000000000000").total_value
