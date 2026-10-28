# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure schema contract tests for change-family ball-in-court / due-date.

The five change-management entities (change order, MoC entry, variation notice
/ request / order) all expose two additive fields - ``ball_in_court`` and
``response_due_date`` - on their Update and Response schemas. Their service
update methods persist via ``data.model_dump(exclude_unset=True)`` ->
``update_fields(**fields)``, so the behaviour that actually matters is:

* a supplied value survives ``model_dump(exclude_unset=True)`` (it will persist
  on PATCH), and
* an unsupplied value is absent from the dump (a PATCH that does not touch it
  leaves the stored value intact),
* the Response schema carries both fields (the read contract).

These schemas import cleanly without a database, so this runs on Python 3.11.
"""

from __future__ import annotations

import pytest

from app.modules.changeorders.schemas import ChangeOrderResponse, ChangeOrderUpdate
from app.modules.moc.schemas import MoCEntryResponse, MoCEntryUpdate
from app.modules.variations.schemas import (
    NoticeResponse,
    NoticeUpdate,
    VariationOrderResponse,
    VariationOrderUpdate,
    VariationRequestResponse,
    VariationRequestUpdate,
)

UPDATE_SCHEMAS = [
    ChangeOrderUpdate,
    MoCEntryUpdate,
    NoticeUpdate,
    VariationRequestUpdate,
    VariationOrderUpdate,
]
RESPONSE_SCHEMAS = [
    ChangeOrderResponse,
    MoCEntryResponse,
    NoticeResponse,
    VariationRequestResponse,
    VariationOrderResponse,
]


@pytest.mark.parametrize("schema", UPDATE_SCHEMAS)
def test_update_schema_carries_ball_in_court_fields(schema):
    obj = schema(ball_in_court="user-123", response_due_date="2026-07-01T00:00:00+00:00")
    assert obj.ball_in_court == "user-123"
    assert obj.response_due_date == "2026-07-01T00:00:00+00:00"
    dumped = obj.model_dump(exclude_unset=True)
    assert dumped["ball_in_court"] == "user-123"
    assert dumped["response_due_date"] == "2026-07-01T00:00:00+00:00"


@pytest.mark.parametrize("schema", UPDATE_SCHEMAS)
def test_update_schema_omits_unset_fields(schema):
    dumped = schema().model_dump(exclude_unset=True)
    assert "ball_in_court" not in dumped
    assert "response_due_date" not in dumped


@pytest.mark.parametrize("schema", RESPONSE_SCHEMAS)
def test_response_schema_exposes_ball_in_court_fields(schema):
    assert "ball_in_court" in schema.model_fields
    assert "response_due_date" in schema.model_fields
