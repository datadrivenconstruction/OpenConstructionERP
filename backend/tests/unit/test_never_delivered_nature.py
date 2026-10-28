# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The third repair nature, and the checker that makes it mean something.

``never_delivered`` says a repair only ever adds rows. That claim is worth
having only if a repair which breaks it fails, so the controls here are repairs
that break it in the two ways that matter: one edits a row it found, and one
adds a second copy of a row already on file. The second is the realistic
failure. An additive repair does not usually damage anything - it duplicates,
and the reader that expected one tax rate for a province now gets two.
"""

from __future__ import annotations

import pytest

from app.core.data_repairs import (
    DataRepair,
    NeverDelivered,
    SupersededBy,
    verify_additive_shape,
)

_TABLE = "oe_i18n_tax_config"


async def _noop(_session) -> int:
    return 0


def _additive(repair_id: str, summary: str) -> DataRepair:
    return DataRepair(
        repair_id=repair_id,
        revision="",
        summary=summary,
        run=_noop,
        nature="never_delivered",
        never_delivered=NeverDelivered(table=_TABLE, identified_by=("country_code", "tax_code")),
    )


def test_a_never_delivered_repair_without_its_declaration_is_refused() -> None:
    """The nature is only worth having if a wrong declaration cannot be constructed."""
    with pytest.raises(ValueError, match="no NeverDelivered block"):
        DataRepair(
            repair_id="additive_without_block",
            revision="",
            summary="claims to add rows and says nothing about where",
            run=_noop,
            nature="never_delivered",
        )


def test_a_never_delivered_block_on_another_nature_is_refused() -> None:
    """A block that does not match the nature would be checked against nothing."""
    with pytest.raises(ValueError, match="only meaningful for 'never_delivered'"):
        DataRepair(
            repair_id="always_wrong_with_additive_block",
            revision="",
            summary="two declarations that cannot both be true",
            run=_noop,
            nature="always_wrong",
            never_delivered=NeverDelivered(table=_TABLE, identified_by=("country_code",)),
        )


def test_the_two_declarations_cannot_be_carried_at_once() -> None:
    """Close-and-add and add-only are opposite claims about the same repair."""
    with pytest.raises(ValueError):
        DataRepair(
            repair_id="both_blocks",
            revision="",
            summary="declares two natures' worth of promises",
            run=_noop,
            nature="never_delivered",
            never_delivered=NeverDelivered(table=_TABLE, identified_by=("country_code",)),
            superseded=SupersededBy(effective_from="2025-01-01", table=_TABLE, closes_column="effective_to"),
        )


def test_a_declaration_with_no_natural_key_is_refused() -> None:
    """Without a key the duplicate check has nothing to compare and passes everything."""
    with pytest.raises(ValueError, match="identified_by"):
        NeverDelivered(table=_TABLE, identified_by=())


def test_the_checker_passes_a_repair_that_only_added() -> None:
    """The positive control: without it the two below could pass by always failing."""
    repair = _additive("adds_a_missing_rate", "adds the rate this database never had")
    before = {"a": {"id": "a", "country_code": "CA", "tax_code": "GST", "rate_pct": "5.0"}}
    after = {
        "a": {"id": "a", "country_code": "CA", "tax_code": "GST", "rate_pct": "5.0"},
        "b": {"id": "b", "country_code": "CA", "tax_code": "QST_QC", "rate_pct": "9.975"},
    }
    assert verify_additive_shape(repair, before, after) == ()


def test_the_checker_catches_an_edited_row() -> None:
    """A rate rewritten under the cover of a repair that claims to only add."""
    repair = _additive("edits_a_row", "claims to add and quietly rewrites a rate")
    before = {"a": {"id": "a", "country_code": "CA", "tax_code": "GST", "rate_pct": "5.0"}}
    after = {"a": {"id": "a", "country_code": "CA", "tax_code": "GST", "rate_pct": "6.0"}}
    assert verify_additive_shape(repair, before, after), "the checker passed a repair that edited a rate"


def test_the_checker_catches_a_deleted_row() -> None:
    """Additive means additive; a row that left is not an addition."""
    repair = _additive("deletes_a_row", "drops a rate on its way past")
    before = {"a": {"id": "a", "country_code": "CA", "tax_code": "GST", "rate_pct": "5.0"}}
    assert verify_additive_shape(repair, before, {}), "the checker passed a repair that deleted a rate"


def test_the_checker_catches_a_duplicated_rate() -> None:
    """The failure an additive repair really has: not damage, duplication."""
    repair = _additive("doubles_a_row", "adds a second copy of a rate already on file")
    before = {"a": {"id": "a", "country_code": "CA", "tax_code": "QST_QC", "rate_pct": "9.975"}}
    after = {
        "a": {"id": "a", "country_code": "CA", "tax_code": "QST_QC", "rate_pct": "9.975"},
        # The customer's own copy edited to a different rate: still the same
        # rate line, so still a duplicate, and the rate not matching is exactly
        # why a value comparison would have missed it.
        "b": {"id": "b", "country_code": "CA", "tax_code": "QST_QC", "rate_pct": "9.5"},
    }
    assert verify_additive_shape(repair, before, after), "the checker passed a duplicate of an existing rate"


def test_a_moved_timestamp_alone_is_not_a_violation() -> None:
    """``updated_at`` moves whenever the ORM touches a row and says nothing to a customer."""
    repair = _additive("touches_nothing", "adds one rate")
    before = {"a": {"id": "a", "country_code": "CA", "tax_code": "GST", "rate_pct": "5.0", "updated_at": 1}}
    after = {"a": {"id": "a", "country_code": "CA", "tax_code": "GST", "rate_pct": "5.0", "updated_at": 2}}
    assert verify_additive_shape(repair, before, after) == ()
