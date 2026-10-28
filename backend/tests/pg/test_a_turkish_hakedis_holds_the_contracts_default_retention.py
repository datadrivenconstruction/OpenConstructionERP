# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A Turkish contract starts at three percent retention and its hakediş holds it.

The certificate reads the retention from the contract unless its terms say
otherwise (``retention_source`` defaults to ``contract``). A contract on a
Turkish project that named no retention used to take the platform fallback,
so the hakediş held a figure no Turkish form sets. The standard public works
contract (Tip Sözleşme 30.2) holds three percent of each progress payment, and
that is now where a Turkish contract starts.

Every tax rate here is the SYNTHETIC set of the hakediş tests; only the
retention is Turkish.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.contracts.schemas import ContractCreate
from app.modules.contracts.service import ContractsService
from tests.pg.test_hakedis_progress_claims import (  # noqa: F401  (fixtures)
    BILL,
    CONTRACT_VALUE,
    _amounts,
    _bill,
    _claim,
    _enter_manual_lines,
    _measure,
    _period_value,
    _project,
    q,
    rates,
    session,
)

pytestmark = pytest.mark.asyncio


async def test_a_new_turkish_contract_holds_three_percent_and_its_hakedis_holds_it_too(session) -> None:
    project = await _project(session, country="TR")
    svc = ContractsService(session)
    created = await svc.create_contract(
        ContractCreate(
            code="TR-HKD-1",
            title="Mekanik ve elektrik tesisatı",
            contract_type="unit_price",
            project_id=project.id,
            total_value=CONTRACT_VALUE,
            currency="TRY",
        )
    )
    assert Decimal(str(created.retention_percent)) == Decimal("3")
    assert created.retention_release_event == "final_completion"

    lines = await _bill(session, created)
    claim = await _measure(svc, await _claim(session, created, 1), lines, 1)
    await _enter_manual_lines(svc, claim.id, advance="0")
    view = await svc.hakedis_view(claim.id, locale="tr")
    this = _period_value(1)
    retention = next(line for line in view["summary"] if line["key"] == "retention")
    assert _amounts(view)["retention"] == q(this * Decimal("3") / 100), retention
    assert len(BILL) == len(lines)
