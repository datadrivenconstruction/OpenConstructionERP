# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The contracts API hands out the cost line of a contract and of each schedule line.

The router builds its responses field by field, so a column the schema
declares but the builder does not pass reaches the screen as null: the
account chips of cost control then read "no cost line" for rows that have one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.contracts.models import Contract, ContractLine
from app.modules.contracts.router import _contract_to_response, _line_to_response


def test_a_schedule_line_response_names_its_cost_line() -> None:
    cost_line = uuid.uuid4()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=uuid.uuid4(),
        code="02.001",
        description="Walls",
        line_type="work",
        unit="m3",
        quantity=Decimal("10"),
        unit_rate=Decimal("5"),
        total_value=Decimal("50"),
        order_index=0,
        cost_line_id=cost_line,
        metadata_={"cost_line_source": "bid_line"},
    )
    line.created_at = line.updated_at = datetime.now(UTC)
    assert _line_to_response(line).cost_line_id == cost_line


def test_a_contract_response_names_its_own_account() -> None:
    cost_line = uuid.uuid4()
    contract = Contract(
        id=uuid.uuid4(),
        code="SC-01",
        title="Shell",
        contract_type="lump_sum",
        counterparty_type="subcontractor",
        project_id=uuid.uuid4(),
        total_value=Decimal("100"),
        currency="EUR",
        retention_percent=Decimal("0"),
        retention_release_event="practical_completion",
        status="active",
        terms={},
        cost_line_id=cost_line,
        metadata_={},
    )
    contract.created_at = contract.updated_at = datetime.now(UTC)
    assert _contract_to_response(contract).cost_line_id == cost_line
