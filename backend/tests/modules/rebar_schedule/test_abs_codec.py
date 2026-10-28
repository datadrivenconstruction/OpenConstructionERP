# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Reading and writing ABS records."""

from decimal import Decimal

import pytest

from app.modules.rebar_schedule.abs_format import (
    AbsSyntaxError,
    decode_bytes,
    parse_file,
    parse_record,
    read_coordinates,
    read_segments,
    read_turns,
    render_block,
    render_file,
)
from tests.modules.rebar_schedule import abs_fixtures

# ── Block structure ────────────────────────────────────────────────────────


@pytest.mark.parametrize(("label", "record"), sorted(abs_fixtures.RECORDS.items()))
def test_a_parsed_record_reassembles_into_the_text_it_came_from(label: str, record: str) -> None:
    """Every block's source text is kept, so the blocks re-join into the line.

    This is what lets an import be re-exported byte for byte, which matters
    because the checksum covers exact characters.
    """
    parsed = parse_record(record)
    assert f"{parsed.group}@" + "".join(block.raw for block in parsed.blocks) == record


def test_a_block_ends_where_an_at_sign_is_followed_by_an_uppercase_letter() -> None:
    """The rule the standard states, exercised on a record full of uppercase values."""
    parsed = parse_record(abs_fixtures.RECORDS["bar-with-a-coupler-and-a-thread"])
    assert [block.kind for block in parsed.blocks] == ["H", "G", "M", "C"]
    coupler = parsed.block("M")
    # 'SleeveA' ends on an uppercase letter, which must not end the block, and
    # 'nThreadB' is the next field rather than a new block.
    assert [(item.key, item.value) for item in coupler.fields] == [
        ("a", "SleeveA"),
        ("b", "S12"),
        ("c", "1"),
        ("n", "ThreadB"),
        ("o", "T13"),
        ("p", "2"),
    ]


def test_a_field_identifier_means_different_things_in_different_blocks() -> None:
    """'r' is the drawing number in the header and a radius in the geometry."""
    parsed = parse_record(abs_fixtures.RECORDS["bar-with-an-arc"])
    assert parsed.header_value("r") == "312"
    assert parsed.geometry.values("r") == ("300",)


def test_an_empty_field_still_carries_its_identifier() -> None:
    """The standard asks for the identifier even when there is no value."""
    parsed = parse_record(abs_fixtures.RECORDS["bar-with-one-bend"])
    assert parsed.header_value("v") == ""
    assert "v" in [item.key for item in parsed.header.fields]


def test_repeated_identifiers_are_kept_in_order() -> None:
    """A spatial geometry repeats x, y and z once per vertex."""
    parsed = parse_record(abs_fixtures.RECORDS["spatial-bar"])
    assert parsed.geometry.values("x") == ("250", "0", "0", "0", "250")


def test_a_mesh_geometry_block_carries_the_axis_whose_bars_are_bent() -> None:
    parsed = parse_record(abs_fixtures.RECORDS["bent-drawn-mesh"])
    assert parsed.geometry.axis == "y"
    assert parsed.geometry.first("l") == "150"


def test_a_spatial_geometry_reads_its_first_coordinate_as_a_field_not_an_axis() -> None:
    """``Gx250@`` in a BF3D record is the field x, not the axis marker Gx.

    The two look identical and are told apart by the super-group, so a codec
    that treats every ``Gx`` as an axis marker loses the first vertex of every
    spatial bar.
    """
    parsed = parse_record(abs_fixtures.RECORDS["spatial-bar"])
    assert parsed.geometry.axis is None
    assert parsed.geometry.first("x") == "250"


def test_the_private_block_is_kept_whole() -> None:
    """It is free-form, so its content is not forced into identified fields."""
    record = "BF2D@HjOCE-DEMO@r312@ib@p1@l1000@n10@e0.888@d12@gB500B@s48@v@Gl300@w90@l700@w0@Pcost-centre-4711@lot-12@"
    parsed = parse_record(record + "C" + str(96 - (sum(ord(c) for c in record + "C") % 32)) + "@")
    private = parsed.block("P")
    assert private.fields[0].value == "cost-centre-4711@lot-12"


# ── Geometry readers ───────────────────────────────────────────────────────


def test_straight_legs_sum_to_the_length_the_header_states() -> None:
    parsed = parse_record(abs_fixtures.RECORDS["cranked-bar"])
    segments = read_segments(parsed.geometry)
    assert [seg.length_mm for seg in segments] == [Decimal(n) for n in (150, 250, 354, 250, 150)]
    assert [seg.angle_deg for seg in segments] == [Decimal(n) for n in (90, 45, -45, -90, 0)]
    assert sum((seg.developed_length_mm for seg in segments), start=Decimal(0)) == parsed.header_number("l")


def test_an_arc_contributes_the_length_of_the_curve_it_draws() -> None:
    """300 mm radius through 90 degrees is 471.2 mm of steel, not 300."""
    parsed = parse_record(abs_fixtures.RECORDS["bar-with-an-arc"])
    segments = read_segments(parsed.geometry)
    assert [seg.radius_mm for seg in segments] == [None, Decimal(300), None]
    developed = sum((seg.developed_length_mm for seg in segments), start=Decimal(0))
    assert abs(developed - parsed.header_number("l")) < Decimal("0.5")


def test_a_second_angle_after_an_arc_is_read_as_the_bend_into_the_next_leg() -> None:
    """``r300@w90@w45@`` is an arc opening 90 degrees, then a 45 degree bend."""
    parsed = parse_record(abs_fixtures.RECORDS["bar-with-an-arc-and-a-bend-after-it"])
    arc = read_segments(parsed.geometry)[1]
    assert arc.radius_mm == Decimal(300)
    assert arc.angle_deg == Decimal(90)
    assert arc.trailing_angle_deg == Decimal(45)


def test_a_spatial_bar_reads_as_one_offset_per_vertex() -> None:
    parsed = parse_record(abs_fixtures.RECORDS["spatial-bar"])
    assert read_coordinates(parsed.geometry) == [
        (Decimal(250), Decimal(0), Decimal(0)),
        (Decimal(0), Decimal(300), Decimal(0)),
        (Decimal(0), Decimal(0), Decimal(300)),
        (Decimal(0), Decimal(-300), Decimal(0)),
        (Decimal(250), Decimal(0), Decimal(0)),
    ]


def test_a_helix_reads_as_a_planar_shape_and_its_turn_pitch_pairs() -> None:
    """A column helix tightens at the foot and the head and opens in between."""
    parsed = parse_record(abs_fixtures.RECORDS["square-helix"])
    assert [seg.length_mm for seg in read_segments(parsed.geometry)] == [Decimal(320)] * 4
    assert read_turns(parsed.geometry) == [
        (Decimal(5), Decimal(100)),
        (Decimal(10), Decimal(200)),
        (Decimal(5), Decimal(100)),
    ]


def test_a_round_helix_is_a_full_circle_with_no_straight_legs() -> None:
    parsed = parse_record(abs_fixtures.RECORDS["round-helix"])
    segments = read_segments(parsed.geometry)
    assert len(segments) == 1
    assert segments[0].radius_mm == Decimal(250)
    assert segments[0].angle_deg == Decimal(360)


def test_a_record_may_carry_no_geometry_at_all() -> None:
    """The standard asks that a shape it cannot describe still be exported."""
    parsed = parse_record(abs_fixtures.RECORDS["stock-mesh"])
    assert parsed.geometry is None
    assert [block.kind for block in parsed.blocks] == ["H", "C"]


def test_bar_blocks_carry_the_meshs_bars() -> None:
    parsed = parse_record(abs_fixtures.RECORDS["drawn-mesh"])
    bars = parsed.bar_blocks
    assert [block.kind for block in bars] == ["Y", "Y", "X", "X"]
    # A trailing 'd' on the diameter marks a double bar, and the two values of
    # a double bar are separated by a semicolon.
    assert bars[0].first("d") == "6d"
    assert bars[0].first("x") == "150;150"


# ── Files ──────────────────────────────────────────────────────────────────


def test_a_file_round_trips_byte_for_byte() -> None:
    data = abs_fixtures.fixture_file()
    parsed = parse_file(data)
    assert len(parsed) == len(abs_fixtures.RECORDS)
    assert render_file(parsed.records) == data


def test_a_trailing_newline_does_not_produce_an_empty_record() -> None:
    parsed = parse_file(abs_fixtures.RECORDS["bar-with-one-bend"] + "\r\n")
    assert len(parsed) == 1


def test_line_numbers_are_recorded_for_error_reporting() -> None:
    parsed = parse_file(abs_fixtures.fixture_file())
    assert [record.line_no for record in parsed.records] == list(range(1, len(abs_fixtures.RECORDS) + 1))


def test_ascii_bytes_are_decoded_as_ascii() -> None:
    text, encoding, offenders = decode_bytes(abs_fixtures.fixture_file())
    assert encoding == "ascii"
    assert offenders == []
    assert text.startswith("BF2D@")


def test_a_non_ascii_byte_is_decoded_and_reported_rather_than_refused() -> None:
    """German free text reaches us with accented bytes; refusing loses the file."""
    record = "BF2D@HjHalle S\xfcd@r312@ib@p1@l1000@n10@e0.888@d12@gB500B@s48@v@Gl300@w90@l700@w0@C77@"
    text, encoding, offenders = decode_bytes(record.encode("cp1252") + b"\r\n")
    assert encoding == "cp1252"
    assert offenders == [1]
    assert "\xfc" in text


# ── Syntax errors ──────────────────────────────────────────────────────────


def test_an_unknown_super_group_is_rejected_with_its_line() -> None:
    with pytest.raises(AbsSyntaxError, match="super-group") as caught:
        parse_file("BF2D@Hj@r@i@p@l@n@e@d@g@s@v@C69@\r\nXYZ@Hj@\r\n")
    assert caught.value.line_no == 2


def test_a_block_that_never_closes_is_rejected() -> None:
    with pytest.raises(AbsSyntaxError, match="not terminated"):
        parse_record("BF2D@HjOCE-DEMO@r312@ib@p1@l1000")


def test_a_field_with_no_identifier_is_rejected() -> None:
    with pytest.raises(AbsSyntaxError, match="no identifier"):
        parse_record("BF2D@HjOCE-DEMO@@r312@C70@")


def test_a_field_identifier_that_is_not_a_lowercase_letter_is_rejected() -> None:
    """Identifiers are lowercase a to z; an uppercase letter opens a block."""
    with pytest.raises(AbsSyntaxError, match="not a lowercase letter"):
        parse_record("BF2D@H1OCE-DEMO@r312@C70@")


# ── Writing ────────────────────────────────────────────────────────────────


def test_render_block_writes_an_identifier_even_for_an_empty_value() -> None:
    assert render_block("H", [("j", "OCE-DEMO"), ("r", "312"), ("v", "")]) == "HjOCE-DEMO@r312@v@"


def test_render_block_marks_the_bent_axis_of_a_mesh() -> None:
    assert render_block("G", [("l", "150"), ("w", "-90")], axis="y") == "Gyl150@w-90@"
