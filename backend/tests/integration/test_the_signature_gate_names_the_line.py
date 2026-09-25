# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The signature gate says what blocks the contract and which line it is.

Signing a subcontract with a blocking finding showed the generic "Compliance
gate failed" line and, next to each finding, the id of the schedule line it
was about. The refusal now names the findings, and each finding carries the
line's code and description as ``element_label``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.integration.test_contracts_compliance_enforcement import _draft_contract, _line, _make_service


@pytest.mark.asyncio
async def test_a_blocked_signature_names_the_line_and_the_finding() -> None:
    contract = _draft_contract()
    line = _line(code="01", quantity="0", unit_rate="100")
    project = SimpleNamespace(id=contract.project_id, region="DACH", compliance_rule_packs=["universal"])
    svc = _make_service(contract=contract, lines=[line], project=project)

    with pytest.raises(HTTPException) as exc:
        await svc.transition_contract(contract.id, "active", actor_id="u1")

    detail = exc.value.detail
    finding = next(e for e in detail["errors"] if e["rule_id"] == "boq_quality.position_has_quantity")
    assert finding["element_ref"] == str(line.id)
    assert finding["element_label"] == "01 Line 01"
    assert detail["message"].startswith("This contract cannot be signed until these are resolved:")
    assert finding["message"] in detail["message"]
    assert str(line.id) not in detail["message"]
