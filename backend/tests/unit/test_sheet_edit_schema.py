"""Unit: ​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠the sheet edit payload refuses fields and shapes it cannot write safely."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.boq.schemas import SheetEditRequest


def test_accepts_the_cells_the_sheet_edits() -> None:
    req = SheetEditRequest(
        edits=[{"id": uuid.uuid4(), "version": 3, "fields": {"quantity": "1.5", "unit": "m2", "ordinal": "01.010"}}]
    )
    assert req.edits[0].version == 3


def test_refuses_fields_outside_the_sheet() -> None:
    with pytest.raises(ValidationError):
        SheetEditRequest(edits=[{"id": uuid.uuid4(), "version": 0, "fields": {"total": "5"}}])


def test_refuses_the_same_row_twice() -> None:
    pid = uuid.uuid4()
    with pytest.raises(ValidationError):
        SheetEditRequest(
            edits=[
                {"id": pid, "version": 0, "fields": {"unit": "m"}},
                {"id": pid, "version": 0, "fields": {"unit": "m2"}},
            ]
        )


def test_refuses_an_empty_edit() -> None:
    with pytest.raises(ValidationError):
        SheetEditRequest(edits=[{"id": uuid.uuid4(), "version": 0, "fields": {}}])
