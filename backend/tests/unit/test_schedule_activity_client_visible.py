# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The flag that sends a milestone to the client portal.

``client_visible`` is NOT NULL in the table, so the update schema must keep
an omitted flag out of the update and refuse an explicit null, rather than
let either reach the database as a NULL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.schedule.models import Activity
from app.modules.schedule.schemas import ActivityUpdate


def test_an_omitted_flag_is_left_alone():
    assert "client_visible" not in ActivityUpdate(name="Roof on").model_dump(exclude_unset=True)


def test_the_flag_can_be_set_and_cleared():
    assert ActivityUpdate(client_visible=True).model_dump(exclude_unset=True) == {"client_visible": True}
    assert ActivityUpdate(client_visible=False).model_dump(exclude_unset=True) == {"client_visible": False}


def test_an_explicit_null_is_refused():
    with pytest.raises(ValidationError):
        ActivityUpdate(client_visible=None)


def test_a_new_milestone_starts_hidden_from_the_client():
    column = Activity.__table__.c.client_visible
    assert column.nullable is False
    assert column.default.arg is False


@pytest.mark.parametrize("stored", [True, False])
def test_the_api_answer_says_what_was_stored(stored):
    # The response is built field by field, so a column the helper forgets
    # comes back as its default: a PATCH that set the flag answered false.
    from app.modules.schedule.router import _activity_to_response

    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        schedule_id=uuid.uuid4(),
        parent_id=None,
        name="Roof on",
        description="",
        wbs_code="",
        start_date="2026-10-12",
        end_date="2026-10-12",
        duration_days=0,
        progress_pct="0",
        status="not_started",
        activity_type="milestone",
        dependencies=[],
        resources=[],
        boq_position_ids=[],
        color="",
        sort_order=0,
        metadata_={},
        created_at=now,
        updated_at=now,
        client_visible=stored,
    )
    assert _activity_to_response(row).client_visible is stored
