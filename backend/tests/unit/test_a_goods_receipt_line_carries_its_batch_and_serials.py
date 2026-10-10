# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A procurement goods receipt line carries its batch or lot and serial numbers.

Procurement is the canonical purchasing flow. The supplier catalogue receipt
line had batch/lot and serial tracking that procurement lacked; the fields now
live on the canonical line, with serials unique and no more than the units
received.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.procurement.models import GoodsReceiptItem
from app.modules.procurement.schemas import GRItemCreate, GRItemResponse


def test_batch_and_serials_are_accepted_and_trimmed() -> None:
    item = GRItemCreate(quantity_received="3", batch_lot="LOT-42", serial_numbers=[" SN1", "SN2 "])

    assert item.batch_lot == "LOT-42"
    assert item.serial_numbers == ["SN1", "SN2"]


def test_more_serials_than_units_received_is_refused() -> None:
    with pytest.raises(ValidationError, match="more serial numbers"):
        GRItemCreate(quantity_received="1", serial_numbers=["SN1", "SN2"])


def test_a_repeated_serial_is_refused() -> None:
    with pytest.raises(ValidationError, match="unique"):
        GRItemCreate(quantity_received="5", serial_numbers=["SN1", "SN1"])


def test_a_blank_serial_is_refused() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        GRItemCreate(quantity_received="5", serial_numbers=["  "])


def test_the_line_model_and_response_carry_both_fields() -> None:
    columns = GoodsReceiptItem.__table__.columns
    assert "batch_lot" in columns and "serial_numbers" in columns
    assert {"batch_lot", "serial_numbers"} <= set(GRItemResponse.model_fields)
