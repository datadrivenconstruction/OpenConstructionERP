# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book quantities, cumulative summary and rule set, without a database."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.measurement_book.service import compute_quantity, summarize
from app.modules.measurement_book.validators import (
    CheckDeviationRule,
    CheckedBeforeCertificationRule,
    MeasuredWithinBoqRule,
)

D = Decimal


def test_quantity_is_number_times_dimensions() -> None:
    q = compute_quantity(length=D("10"), breadth=D("0.3"), height=D("0.45"), number=D("2"), direct_quantity=None)
    assert q == D("2.7000")


def test_missing_dimensions_count_as_one_and_direct_wins() -> None:
    running = compute_quantity(length=D("12.5"), breadth=None, height=None, number=None, direct_quantity=None)
    direct = compute_quantity(length=D("9"), breadth=None, height=None, number=None, direct_quantity=D("4"))
    assert running == D("12.5000")
    assert direct == D("4.0000")


def test_empty_line_is_refused() -> None:
    with pytest.raises(ValueError, match="dimension"):
        compute_quantity(length=None, breadth=None, height=None, number=None, direct_quantity=None)


def test_summary_counts_only_checked_quantities_towards_value() -> None:
    pid = uuid.uuid4()
    pos = SimpleNamespace(id=pid, ordinal="01.020", description="Brickwork", unit="m3", quantity="10", unit_rate="50")
    entries = [
        SimpleNamespace(boq_position_id=pid, quantity=D("4"), check_status="checked", check_quantity=D("3.8")),
        SimpleNamespace(boq_position_id=pid, quantity=D("3"), check_status="unchecked", check_quantity=None),
    ]
    [line] = summarize([pos], entries)
    assert line["measured_quantity"] == D("7")
    assert line["checked_quantity"] == D("3.8")
    assert line["value_to_date"] == D("190.00")
    assert line["unchecked_count"] == 1
    assert line["percent_measured"] == D("70.00")


@pytest.mark.asyncio
async def test_rules_flag_overmeasure_unchecked_and_deviation() -> None:
    position = {"ordinal": "1", "unit": "m", "entry_count": 1, "boq_quantity": D("5"), "measured_quantity": D("6")}
    data = {
        "positions": [position],
        "entries": [
            {
                "id": "a",
                "entry_date": "2026-10-01",
                "quantity": D("10"),
                "check_status": "checked",
                "check_quantity": D("9"),
            },
            {
                "id": "b",
                "entry_date": "2026-10-02",
                "quantity": D("2"),
                "check_status": "unchecked",
                "check_quantity": None,
            },
        ],
        "deviation_threshold_pct": D("5"),
    }
    ctx = ValidationContext(data=data)
    assert not (await MeasuredWithinBoqRule().validate(ctx))[0].passed
    unchecked = await CheckedBeforeCertificationRule().validate(ctx)
    assert [r.passed for r in unchecked] == [True, False]
    dev = await CheckDeviationRule().validate(ctx)
    assert len(dev) == 1
    assert not dev[0].passed
    data["deviation_threshold_pct"] = D("10")
    assert (await CheckDeviationRule().validate(ValidationContext(data=data)))[0].passed
