# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The probe helpers that decide "which object" and "what value" (pure).

A probe that cannot tell which object it should read, or reads a value of the
wrong shape, answers ``unknown`` with a reason. It never picks the first match
and never turns an unreadable value into 0.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.modules.trainer.checker.probes import _einvoice_vat_rate, _one, _select
from app.modules.trainer.checker.registry import ProbeReading, ProbeResult


@dataclass
class _Claim:
    claim_number: str
    created_at: dt.datetime


def _claims(*numbers: str) -> list[_Claim]:
    base = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    return [_Claim(n, base + dt.timedelta(minutes=i)) for i, n in enumerate(numbers)]


def test_latest_is_the_last_in_creation_order() -> None:
    rows = _claims("PC-0001", "PC-0002")
    assert _select(rows, "latest", lambda c: c.claim_number, "claim") is rows[1]


def test_a_claim_selector_n_is_the_claim_numbered_pc_n() -> None:
    rows = _claims("PC-0001", "PC-0002", "PC-0003")
    assert _select(rows, 2, lambda c: c.claim_number, "claim") is rows[1]
    missing = _select(rows, 7, lambda c: c.claim_number, "claim")
    assert isinstance(missing, ProbeReading) and missing.reason == "not_found"


def test_two_claims_with_one_number_are_ambiguous_not_first_wins() -> None:
    # ``next_claim_number`` is count + 1, so a deleted claim can repeat a number.
    rows = _claims("PC-0002", "PC-0002")
    picked = _select(rows, 2, lambda c: c.claim_number, "claim")
    assert isinstance(picked, ProbeReading) and picked.reason == "ambiguous"


def test_a_variation_selector_n_is_the_nth_in_creation_order() -> None:
    rows = _claims("VR-0001", "VR-0002")
    assert _select(rows, 1, None, "request") is rows[0]
    beyond = _select(rows, 3, None, "request")
    assert isinstance(beyond, ProbeReading) and beyond.reason == "not_found"
    empty = _select([], "latest", None, "request")
    assert isinstance(empty, ProbeReading) and empty.reason == "not_found"


def test_two_rows_answering_one_name_are_ambiguous() -> None:
    assert _one(["a"], "x") == "a"
    none = _one([], "markup")
    assert isinstance(none, ProbeReading) and none.reason == "not_found"
    two = _one(["a", "b"], "markup")
    assert isinstance(two, ProbeReading) and two.reason == "ambiguous"


@pytest.mark.parametrize(
    ("metadata", "value"),
    [
        ({"einvoice": {"vat_rate": 20}}, Decimal(20)),
        ({"einvoice": {"vat_rate": "19"}}, Decimal(19)),
        ({"einvoice": {"vat_rate": 5.5}}, Decimal("5.5")),
        # Absent or null: finance charges 0, so that is the rate the ERP holds.
        ({}, Decimal(0)),
        ({"einvoice": {}}, Decimal(0)),
        ({"einvoice": {"vat_rate": None}}, Decimal(0)),
    ],
)
def test_the_einvoice_vat_rate_is_read_as_a_percent(metadata: dict, value: Decimal) -> None:
    reading = _einvoice_vat_rate(metadata)
    assert reading.found and reading.value == value


@pytest.mark.parametrize(
    "raw",
    [{"value": 20, "unit": "percent"}, [20], True, "twenty"],
)
def test_an_einvoice_vat_rate_that_is_not_a_number_is_unknown_never_zero(raw: object) -> None:
    reading = _einvoice_vat_rate({"einvoice": {"vat_rate": raw}})
    assert not reading.found
    assert reading.value is None and reading.reason == "unreadable"


def test_an_einvoice_block_that_is_not_an_object_is_unknown() -> None:
    reading = _einvoice_vat_rate({"einvoice": "19"})
    assert reading.reason == "unreadable"


def test_an_unread_value_is_marked_missing_or_error_by_its_reason() -> None:
    assert ProbeResult(None, "money", "unknown", "not_found: claim").is_missing
    assert ProbeResult(None, "money", "unknown", "ref_missing").is_missing
    assert not ProbeResult(None, "money", "unknown", "ref_outside_project: contract.main").is_missing
    assert not ProbeResult(None, "money", "unknown", "ambiguous: 2 x markup").is_missing
    assert ProbeReading.of(None).reason == "not_set"
