# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ``bvbs_abs`` validation rules.

Every rule is exercised twice: once against the conforming corpus, where it
must pass, and once against a record built to break exactly that rule, where it
must fail. A rule tested only on conforming data cannot tell whether it looks
at anything at all.
"""

from decimal import Decimal

import pytest

from app.core.validation.engine import RuleResult, Severity, ValidationContext
from app.modules.rebar_schedule.abs_format import compute_checksum, parse_record
from app.modules.rebar_schedule.validators import (
    RULE_SET,
    RULES,
    AbsAsciiOnly,
    AbsBendRadiusOverRoller,
    AbsChecksumValid,
    AbsDevelopedLengthMatchesHeader,
    AbsGeometryAngleTerminated,
    AbsGeometryExcludesSpacer,
    AbsHeaderFieldOrder,
    AbsMeshCoordinatesNonNegative,
    AbsRecordLengthBudget,
)
from tests.modules.rebar_schedule import abs_fixtures


def _context(*records: str) -> ValidationContext:
    """A context over records given as text, parsed in file order."""
    return ValidationContext(
        data={"records": [parse_record(text, line_no=n) for n, text in enumerate(records, start=1)]},
        metadata={"locale": "en"},
    )


def _sealed(body: str) -> str:
    """Append the checksum block a body needs, so a fixture is well-formed.

    Computed here rather than written out, so a fixture aimed at one rule does
    not trip the checksum rule as a side effect.
    """
    return f"{body}C{compute_checksum(body + 'C')}@"


def _failures(results: list[RuleResult]) -> list[RuleResult]:
    return [item for item in results if not item.passed]


# ── Checksum ───────────────────────────────────────────────────────────────


async def test_checksum_rule_passes_every_record_in_the_corpus() -> None:
    results = await AbsChecksumValid().validate(_context(*abs_fixtures.RECORDS.values()))
    assert len(results) == len(abs_fixtures.RECORDS)
    assert _failures(results) == []


async def test_checksum_rule_catches_an_altered_length() -> None:
    damaged = abs_fixtures.RECORDS["bar-with-one-bend"].replace("@l1000@", "@l1001@")
    failures = _failures(await AbsChecksumValid().validate(_context(damaged)))
    assert len(failures) == 1
    assert failures[0].severity is Severity.ERROR
    assert "93" in failures[0].message


async def test_checksum_rule_catches_a_record_with_no_checksum_block() -> None:
    stripped = abs_fixtures.RECORDS["bar-with-one-bend"].rsplit("@C", 1)[0] + "@"
    assert _failures(await AbsChecksumValid().validate(_context(stripped)))


# ── Header ─────────────────────────────────────────────────────────────────


async def test_header_rule_passes_one_conforming_record_per_super_group() -> None:
    conforming = [
        abs_fixtures.RECORDS[label]
        for label in (
            "bar-with-one-bend",
            "spatial-bar",
            "square-helix",
            "stock-mesh",
            "lattice-girder",
            "spacer-strip",
        )
    ]
    assert _failures(await AbsHeaderFieldOrder().validate(_context(*conforming))) == []


async def test_header_rule_reports_a_missing_field() -> None:
    """Dropping the steel grade from a planar shape leaves the header short."""
    body = "BF2D@HjOCE-DEMO@r312@ib@p1@l1000@n10@e0.888@d12@s48@v@Gl300@w90@l700@w0@"
    failures = _failures(await AbsHeaderFieldOrder().validate(_context(_sealed(body))))
    assert len(failures) == 1
    assert "g" in failures[0].details["missing"]


async def test_header_rule_reports_fields_out_of_order() -> None:
    """Every field present, two of them swapped.

    This is the failure the rule exists for: a reader that walks the header
    positionally mis-assigns the diameter and the weight and reports nothing.
    """
    body = "BF2D@HjOCE-DEMO@r312@ib@p1@l1000@n10@d12@e0.888@gB500B@s48@v@Gl300@w90@l700@w0@"
    failures = _failures(await AbsHeaderFieldOrder().validate(_context(_sealed(body))))
    assert len(failures) == 1
    assert failures[0].details["out_of_order"] is True
    assert failures[0].details["missing"] == []


async def test_header_rule_reports_a_record_with_no_header_block() -> None:
    failures = _failures(await AbsHeaderFieldOrder().validate(_context(_sealed("BF2D@Gl300@w90@l700@w0@"))))
    assert len(failures) == 1
    assert "header block" in failures[0].message


# ── Block combinations ─────────────────────────────────────────────────────


async def test_spacer_rule_passes_a_record_that_carries_only_spacers() -> None:
    results = await AbsGeometryExcludesSpacer().validate(_context(abs_fixtures.RECORDS["spacer-positions"]))
    assert _failures(results) == []


async def test_spacer_rule_catches_geometry_and_spacers_on_one_line() -> None:
    body = "BF2D@HjOCE-DEMO@r312@ib@p9@l1200@n1@e1.066@d10@gB500B@s40@v@Gl1200@w0@At6@p150@p600@"
    failures = _failures(await AbsGeometryExcludesSpacer().validate(_context(_sealed(body))))
    assert len(failures) == 1
    assert failures[0].severity is Severity.ERROR


# ── ASCII and length ───────────────────────────────────────────────────────


async def test_ascii_rule_passes_the_whole_corpus() -> None:
    results = await AbsAsciiOnly().validate(_context(*abs_fixtures.RECORDS.values()))
    assert _failures(results) == []


async def test_ascii_rule_catches_an_umlaut_in_a_free_text_field() -> None:
    body = "BF2D@HjHalle S\xfcd@r312@ib@p1@l1000@n10@e0.888@d12@gB500B@s48@v@Gl300@w90@l700@w0@"
    failures = _failures(await AbsAsciiOnly().validate(_context(_sealed(body))))
    assert len(failures) == 1
    assert failures[0].details["characters"] == ["\xfc"]


async def test_length_rule_passes_records_inside_the_budget() -> None:
    results = await AbsRecordLengthBudget().validate(_context(*abs_fixtures.RECORDS.values()))
    assert _failures(results) == []


async def test_length_rule_reports_an_oversized_record_as_information_only() -> None:
    """Over budget is a quality note, not an error: the file still works."""
    padding = "@".join(f"l{n}@w0" for n in range(1, 200))
    body = f"BF2D@HjOCE-DEMO@r312@ib@p1@l1000@n10@e0.888@d12@gB500B@s48@v@G{padding}@"
    failures = _failures(await AbsRecordLengthBudget().validate(_context(_sealed(body))))
    assert len(failures) == 1
    assert failures[0].severity is Severity.INFO
    assert failures[0].details["length"] > 1000


# ── Geometry ───────────────────────────────────────────────────────────────


async def test_angle_rule_passes_the_corpus_planar_shapes() -> None:
    planar = [text for text in abs_fixtures.RECORDS.values() if text.startswith(("BF2D", "BFWE", "BFMA"))]
    assert _failures(await AbsGeometryAngleTerminated().validate(_context(*planar))) == []


async def test_angle_rule_catches_a_bar_that_ends_without_an_explicit_zero() -> None:
    """The standard asks for w0 on a bar that ends straight."""
    body = "BF2D@HjOCE-DEMO@r312@ib@p1@l1000@n10@e0.888@d12@gB500B@s48@v@Gl300@w90@l700@"
    failures = _failures(await AbsGeometryAngleTerminated().validate(_context(_sealed(body))))
    assert len(failures) == 1
    assert failures[0].details["legs"] == [2]


async def test_radius_rule_passes_the_corpus_arcs() -> None:
    arcs = [abs_fixtures.RECORDS[label] for label in ("bar-with-an-arc", "bar-with-an-arc-and-a-bend-after-it")]
    assert _failures(await AbsBendRadiusOverRoller().validate(_context(*arcs))) == []


async def test_radius_rule_catches_a_radius_the_stated_roller_cannot_produce() -> None:
    """A 48 mm roller cannot draw a 20 mm inner radius."""
    body = "BF2D@HjOCE-DEMO@r312@ib@p4@l1471@n10@e1.306@d12@gB500B@s48@v@Gl500@w0@r20@w90@w0@l500@w0@"
    failures = _failures(await AbsBendRadiusOverRoller().validate(_context(_sealed(body))))
    assert len(failures) == 1
    assert failures[0].details["legs"] == [2]
    assert failures[0].details["limit_mm"] == "24"


async def test_developed_length_rule_passes_the_corpus_planar_shapes() -> None:
    planar = [text for text in abs_fixtures.RECORDS.values() if text.startswith("BF2D")]
    assert _failures(await AbsDevelopedLengthMatchesHeader().validate(_context(*planar))) == []


async def test_developed_length_rule_catches_a_leg_that_does_not_add_up() -> None:
    """A header saying 1000 mm over legs of 300 and 400 is 300 mm of steel short."""
    body = "BF2D@HjOCE-DEMO@r312@ib@p1@l1000@n10@e0.888@d12@gB500B@s48@v@Gl300@w90@l400@w0@"
    failures = _failures(await AbsDevelopedLengthMatchesHeader().validate(_context(_sealed(body))))
    assert len(failures) == 1
    assert failures[0].severity is Severity.WARNING
    assert Decimal(failures[0].details["developed_mm"]) == Decimal(700)


async def test_developed_length_rule_tolerates_the_rounding_an_arc_introduces() -> None:
    """300 mm through 90 degrees develops to 471.239, and the header says 1471."""
    parsed = parse_record(abs_fixtures.RECORDS["bar-with-an-arc"])
    assert parsed.header_number("l") == Decimal(1471)
    assert _failures(await AbsDevelopedLengthMatchesHeader().validate(_context(parsed.raw))) == []


async def test_mesh_rule_passes_the_corpus_meshes() -> None:
    meshes = [text for text in abs_fixtures.RECORDS.values() if text.startswith("BFMA")]
    assert _failures(await AbsMeshCoordinatesNonNegative().validate(_context(*meshes))) == []


async def test_mesh_rule_catches_a_negative_bar_coordinate() -> None:
    body = "BFMA@HjOCE-DEMO@r312@ib@p2@l4200@n10@e24.240@gB500B@s48@mZM-01@b2600@v@Xd5@x-400@y200@l2200@e200,1@"
    failures = _failures(await AbsMeshCoordinatesNonNegative().validate(_context(_sealed(body))))
    assert len(failures) == 1
    assert failures[0].details["coordinates"] == ["Xx=-400"]


async def test_mesh_rule_reads_both_halves_of_a_double_bar() -> None:
    """A double bar carries two values separated by a semicolon; both count."""
    body = "BFMA@HjOCE-DEMO@r312@ib@p2@l4200@n10@e24.240@gB500B@s48@mZM-01@b2600@v@Yd6d@x150;-150@y500;500@l3800@"
    failures = _failures(await AbsMeshCoordinatesNonNegative().validate(_context(_sealed(body))))
    assert failures[0].details["coordinates"] == ["Yx=-150"]


async def test_mesh_rule_ignores_a_planar_shape() -> None:
    """The mesh coordinate rule says nothing about a bent bar."""
    results = await AbsMeshCoordinatesNonNegative().validate(_context(abs_fixtures.RECORDS["bar-with-one-bend"]))
    assert results == []


# ── The rule set as a whole ────────────────────────────────────────────────


def test_every_rule_belongs_to_the_rule_set_and_has_a_unique_id() -> None:
    ids = [rule.rule_id for rule in RULES]
    assert len(ids) == len(set(ids))
    assert all(rule.standard == RULE_SET for rule in RULES)
    assert all(rule.rule_id.startswith(f"{RULE_SET}.") for rule in RULES)


@pytest.mark.parametrize("rule_class", RULES)
async def test_no_rule_reports_a_finding_against_the_conforming_corpus(rule_class: type) -> None:
    """The corpus covers every super-group and every block the codec reads.

    A rule that fires on it is wrong about the format, not about the file -
    with one deliberate exception, the spacer record, whose header is short by
    design.
    """
    clean = [text for label, text in abs_fixtures.RECORDS.items() if label not in abs_fixtures.HEADER_INCOMPLETE]
    results = await rule_class().validate(_context(*clean))
    assert _failures(results) == [], rule_class.rule_id


async def test_the_spacer_record_is_the_one_record_any_rule_reports() -> None:
    """The header rule follows the standard's text, not a convenient record.

    Every identifier applicable to a super-group must be present, even when the
    value is empty. One record here omits two of them on purpose, and this test
    pins which record and which fields, so a later reader cannot loosen the rule
    to make the corpus go green.
    """
    findings = {}
    for label, text in abs_fixtures.RECORDS.items():
        for result in _failures(await AbsHeaderFieldOrder().validate(_context(text))):
            findings[label] = result.details["missing"]
    expected = dict.fromkeys(
        abs_fixtures.HEADER_INCOMPLETE,
        abs_fixtures.HEADER_INCOMPLETE_MISSING_FIELDS,
    )
    assert findings == expected


@pytest.mark.parametrize("rule_class", RULES)
async def test_every_rule_survives_an_empty_context(rule_class: type) -> None:
    assert await rule_class().validate(ValidationContext(data={"records": []})) == []


@pytest.mark.parametrize("rule_class", RULES)
async def test_every_rule_carries_a_translated_message_for_each_finding(rule_class: type) -> None:
    """A finding with a raw key in it has no message bundle behind it."""
    damaged = _sealed("BF2D@HjHalle S\xfcd@r312@ib@p1@l1000@n10@d12@gB500B@s48@v@Gl300@w90@l700@")
    broken = damaged.replace("C" + damaged.rsplit("@C", 1)[1].rstrip("@"), "C65")
    for result in await rule_class().validate(_context(broken)):
        assert not result.message.startswith(RULE_SET), result.message
        if not result.passed:
            assert result.suggestion
            assert not result.suggestion.startswith(RULE_SET)
