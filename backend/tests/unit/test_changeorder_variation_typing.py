# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A change order says which instrument it is, not only why it exists.

``reason_category`` has always answered "why": a design changed, a condition
was unforeseen. ``variation_type`` answers a different question, "what document
is this", and the answer decides who signs, what evidence is required and which
clause governs. The two are independent: an unforeseen site condition can be
settled as an instructed change, as a signed site record, or as a claim.

Until now the column existed on the model and nothing could put a value in it.
It was absent from every schema, so the API had no way to set it and no way to
return it, and it held no data anywhere. That is why it can be given a closed
vocabulary without a migration to clean up behind it: there are no rows to
reject.

The vocabulary is neutral English rather than a transliteration, because the
same three instruments exist under the international contract standards and
under Chinese practice, where they are named 工程变更, 现场签证 and 索赔.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.changeorders.intl import (
    REASON_CATEGORIES,
    VARIATION_TYPE_LABELS,
    VARIATION_TYPE_PATTERN,
    VARIATION_TYPES,
    variation_type_label,
)
from app.modules.changeorders.schemas import ChangeOrderCreate, ChangeOrderUpdate


def _create(**overrides: object) -> ChangeOrderCreate:
    payload: dict[str, object] = {"project_id": uuid.uuid4(), "title": "Foundation rework"}
    payload.update(overrides)
    return ChangeOrderCreate(**payload)  # type: ignore[arg-type]


# ── The vocabulary has one source ───────────────────────────────────────────


def test_the_codes_and_the_pattern_both_come_from_the_labels() -> None:
    """One definition, three views of it.

    A pattern written out by hand beside a labels dict is the shape that once
    let two shipped reason codes be unacceptable to the schema that was meant
    to accept them, which is recorded in ``intl`` above the reason table. The
    derivation is what makes that impossible rather than unlikely.
    """
    assert tuple(VARIATION_TYPE_LABELS) == VARIATION_TYPES
    assert "^(" + "|".join(VARIATION_TYPE_LABELS) + ")$" == VARIATION_TYPE_PATTERN


def test_the_two_vocabularies_are_disjoint_and_are_not_the_same_axis() -> None:
    """Why and which-instrument are different questions with different answers.

    The equality check is the point of this test rather than a formality. Two
    sets that come back equal would mean the second axis does not exist, and a
    disjointness assertion alone passes just as happily on two empty sets.
    """
    types, reasons = set(VARIATION_TYPES), set(REASON_CATEGORIES)

    assert types and reasons
    assert types != reasons
    assert types & reasons == set()


# ── Labels ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("code", VARIATION_TYPES)
def test_every_code_has_a_label_that_is_not_the_code(code: str) -> None:
    label = variation_type_label(code)

    assert label == VARIATION_TYPE_LABELS[code]
    assert label != code


@pytest.mark.parametrize("absent", [None, "", "   "])
def test_an_untyped_order_reads_as_untyped_rather_than_blank(absent: str | None) -> None:
    """Null is a real state here: nobody has decided yet.

    A blank cell in a register is indistinguishable from a rendering fault, so
    the absence is given words.
    """
    assert variation_type_label(absent) == "Not yet typed"


def test_an_unknown_code_is_still_readable() -> None:
    """Data written before the vocabulary existed must not print as a gap."""
    assert variation_type_label("some_other_thing") == "Some other thing"


# ── The schema ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("code", VARIATION_TYPES)
def test_the_create_schema_accepts_each_instrument(code: str) -> None:
    assert _create(variation_type=code).variation_type == code


def test_the_create_schema_leaves_it_unset_by_default() -> None:
    """Not defaulted to the commonest instrument: an unmade decision is not a
    change to the works, and recording one would put a guess in the register."""
    assert _create().variation_type is None


@pytest.mark.parametrize(
    "rejected",
    [
        "variation",  # the module name, and what a caller would try first
        "works change",  # a space where the code has an underscore
        "WORKS_CHANGE",  # the pattern is anchored and lower case
        "工程变更",  # the Chinese term is a label, never a stored code
        "design_change",  # a reason_category, which is the other axis
        "claim; drop table",
    ],
)
def test_the_create_schema_refuses_anything_else(rejected: str) -> None:
    with pytest.raises(ValidationError):
        _create(variation_type=rejected)


@pytest.mark.parametrize("code", VARIATION_TYPES)
def test_the_update_schema_can_type_an_order_that_was_raised_untyped(code: str) -> None:
    """The ordinary path: an order is raised, then someone decides what it is."""
    update = ChangeOrderUpdate(variation_type=code)

    assert update.variation_type == code
    assert "variation_type" in update.model_dump(exclude_unset=True)


def test_an_update_that_says_nothing_does_not_clear_the_type() -> None:
    """``exclude_unset`` is what the service writes, so the omission has to be
    visible as an omission rather than as an explicit null."""
    assert "variation_type" not in ChangeOrderUpdate(title="Renamed").model_dump(exclude_unset=True)


def test_the_update_schema_refuses_an_unknown_instrument() -> None:
    with pytest.raises(ValidationError):
        ChangeOrderUpdate(variation_type="variation")
