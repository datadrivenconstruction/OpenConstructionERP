# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ABS checksum rule.

The checksum is the only self-verifying part of the format, which makes it the
oracle for everything else: a record that reproduces its own checksum has been
written correctly, and a codec that reproduces the checksum for a record it
built has laid the characters out the way the standard asks.
"""

from decimal import Decimal

import pytest

from app.modules.rebar_schedule.abs_format import (
    compute_checksum,
    parse_record,
    read_segments,
    render_record,
    split_checksum,
    verify_checksum,
)
from tests.modules.rebar_schedule import abs_fixtures


def test_the_worked_illustration_of_the_rule_arrives_at_its_stated_value() -> None:
    """One string carried through the rule by hand, spelled out in the fixture."""
    text, expected = abs_fixtures.CHECKSUM_ILLUSTRATION
    assert compute_checksum(text) == expected


@pytest.mark.parametrize(("label", "record"), sorted(abs_fixtures.RECORDS.items()))
def test_every_record_reproduces_its_own_checksum(label: str, record: str) -> None:
    assert verify_checksum(record), label


def test_a_lattice_girder_is_not_exempt_from_the_checksum_rule() -> None:
    """The one super-group the standard's checksum table leaves unmarked.

    That omission invites a reader to skip the check for BFGT rather than to
    read the rule, which would build a codec that accepts a damaged girder and
    rejects nothing. The fixture states a checksum its own characters do not
    produce, and the rule has to say so.
    """
    body, declared = split_checksum(abs_fixtures.BFGT_MISSTATED_CHECKSUM)
    assert declared == abs_fixtures.BFGT_STATED_CHECKSUM
    assert compute_checksum(body + "C") == abs_fixtures.BFGT_CORRECT_CHECKSUM
    assert not verify_checksum(abs_fixtures.BFGT_MISSTATED_CHECKSUM)


def test_an_overall_length_written_where_a_leg_belongs_is_caught_twice_over() -> None:
    """A plausible mistake, and two checks that refuse it without consulting
    each other.

    A hooked bar reads 150, 500, 150 against a header of 800 mm. Writing the
    800 where the middle leg belongs leaves a record that still parses. The
    checksum no longer holds, and the legs no longer add up to the header, so
    the arithmetic agrees with the checksum. That is what makes the checksum
    usable as an oracle for the rest of these tests.
    """
    record = abs_fixtures.RECORDS["bar-with-hooked-ends"]
    assert abs_fixtures.HOOKED_BAR_GEOMETRY in record
    swapped = record.replace(
        abs_fixtures.HOOKED_BAR_GEOMETRY,
        abs_fixtures.HOOKED_BAR_TOTAL_IN_THE_MIDDLE_LEG,
    )
    assert verify_checksum(record)
    assert not verify_checksum(swapped)

    legs = read_segments(parse_record(swapped).geometry)
    developed = sum((seg.developed_length_mm for seg in legs), start=Decimal(0))
    assert parse_record(record).header_number("l") == Decimal(800)
    assert developed == Decimal(1100)


def test_the_checksum_always_lands_in_the_range_the_rule_allows() -> None:
    """96 minus a value modulo 32 can only be 65 through 96."""
    for record in abs_fixtures.RECORDS.values():
        assert 65 <= parse_record(record).declared_checksum <= 96


def test_a_record_with_no_checksum_block_reports_no_declared_value() -> None:
    body, declared = split_checksum("BF2D@HjTest@r1@i@p1@l100@n1@e0.1@d12@gB500B@s48@v@Gl100@w0@")
    assert declared is None
    assert not verify_checksum(body)


def test_a_single_altered_character_is_caught() -> None:
    """A digit changed by one shifts the sum by one, which the rule sees."""
    record = abs_fixtures.RECORDS["bar-with-one-bend"]
    damaged = record.replace("@l1000@", "@l1001@")
    assert verify_checksum(record)
    assert not verify_checksum(damaged)


def test_separators_and_spaces_are_invisible_to_the_checksum() -> None:
    """A property of the rule, not of this implementation, and worth knowing.

    The sum is taken modulo 32, and both '@' (64) and the space (32) are exact
    multiples of 32. Dropping either leaves the checksum unchanged, so the rule
    catches transcription damage and is no defence against tampering.
    """
    record = abs_fixtures.RECORDS["bar-with-one-bend"]
    body, declared = split_checksum(record)
    assert compute_checksum(body + "C") == declared
    assert compute_checksum(body.replace("@v@", "@v@@") + "C") == declared
    assert compute_checksum(body + " " + "C") == declared


def test_rendering_a_record_arrives_at_the_same_characters_as_the_fixture() -> None:
    """Building the plainest record from its blocks reproduces it exactly."""
    rendered = render_record(
        "BF2D",
        ["HjOCE-DEMO@r312@ib@p1@l1000@n10@e0.888@d12@gB500B@s48@v@", "Gl300@w90@l700@w0@"],
    )
    assert rendered == abs_fixtures.RECORDS["bar-with-one-bend"]


def test_rendering_rejects_a_super_group_the_standard_does_not_define() -> None:
    with pytest.raises(ValueError, match="unknown super-group"):
        render_record("BF4D", ["Hj@r@i@p@l@n@e@d@g@s@v@"])
