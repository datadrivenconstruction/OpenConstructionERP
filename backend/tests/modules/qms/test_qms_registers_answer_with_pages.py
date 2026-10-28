# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The quality registers have to say how much of themselves they returned.

Every one of these routes capped its result and answered with a bare array,
so a project past the cap was handed a full page with nothing to say it was
one. The NCR register is the sharp end: a project is closed out against its
list of nonconformities, and a list that stops at 200 and reads as complete
is how one survives handover.

Asserted against the registered ``response_model`` rather than the return
annotation. ``router.py`` imports annotations from ``__future__``, so the
annotation is the string "NCRListResponse" and an identity check against it
would pass for any module that spells a name the same way. ``response_model``
is also what FastAPI serialises through, so a route could declare the
envelope in one and rows in the other and only this half would reach a
reader.

No database and no HTTP: this is a claim about what the router declares, and
routing tables are built at import. Every route is looked up by its endpoint
function rather than by path, so renaming a path cannot quietly drop a case
here to zero matches and still pass.
"""

from __future__ import annotations

import pytest

from app.modules.qms import router as qms_router
from app.modules.qms import schemas as qms_schemas

# endpoint function name -> the envelope it must declare.
REGISTERS = {
    "list_itp_plans": "ITPPlanListResponse",
    "list_itp_items": "ITPItemListResponse",
    "list_inspections": "InspectionListResponse",
    "list_inspection_evidence": "InspectionAttachmentListResponse",
    "list_ncrs": "NCRListResponse",
    "list_ncr_actions": "NCRActionListResponse",
    "list_punch_items": "PunchItemListResponse",
    "list_audits": "AuditListResponse",
}


@pytest.mark.parametrize(("endpoint_name", "envelope_name"), sorted(REGISTERS.items()))
def test_the_register_answers_with_a_page_not_a_bare_array(endpoint_name: str, envelope_name: str) -> None:
    """Each register declares its envelope, and declares it exactly once."""
    endpoint = getattr(qms_router, endpoint_name)
    envelope = getattr(qms_schemas, envelope_name)

    routes = [r for r in qms_router.router.routes if getattr(r, "endpoint", None) is endpoint]
    assert len(routes) == 1, f"expected exactly one route for {endpoint_name}, found {len(routes)}"
    assert routes[0].response_model is envelope, (
        f"{endpoint_name} answers with {routes[0].response_model!r}, not {envelope_name}"
    )


@pytest.mark.parametrize("envelope_name", sorted(REGISTERS.values()))
def test_the_envelope_carries_the_count(envelope_name: str) -> None:
    """``total`` is named explicitly because it is the field doing the work.

    A model with ``items`` and nothing else satisfies a shape check and still
    tells the reader nothing, which is the state this whole change exists to
    leave behind.
    """
    fields = getattr(qms_schemas, envelope_name).model_fields
    assert set(fields) == {"items", "total", "offset", "limit"}, (
        f"{envelope_name} has drifted from {{items, total, offset, limit}}: {sorted(fields)}"
    )
