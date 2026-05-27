"""Regression tests for the IFC text-fallback parser bugfixes.

Each test pins one specific audit finding so a future refactor cannot
silently reintroduce the bug. The audit references are listed in the
test docstrings (Cnn = AUDIT_REPORT.md section C, Wave 1).

Setup is intentionally minimal: we build small synthetic IFC strings
in-memory and write them to a tempfile, then run the parser. No DDC
binary, no real model files. Each fixture isolates exactly one parser
quirk so a failure points at one fix.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

from app.modules.bim_hub.ifc_processor import (
    _STEP_DOUBLE_QUOTE_PLACEHOLDER,
    _decode_step_string,
    _extract_quantities_for_element,
    _ifc_units_are_non_si_metres,
    process_ifc_file,
)

# ── Helpers ─────────────────────────────────────────────────────────


@pytest.fixture
def workdir() -> Path:
    """A scratch dir for each test — parser writes its placeholder
    geometry into this directory, so we make a fresh one per test."""
    d = Path(tempfile.mkdtemp(prefix="ifc_regression_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _force_text_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """All tests in this module exercise the text-IFC fallback path
    (the regex tokenizer). Stub the converter lookup so the DDC binary
    is never invoked — guarantees we measure the parser, not the
    installed converter on the dev machine."""
    monkeypatch.setattr(
        "app.modules.boq.cad_import.find_converter",
        lambda _ext: None,
    )


def _write_ifc(content: str, workdir: Path) -> Path:
    """Write a STEP-21 IFC string into ``workdir`` and return the path."""
    p = workdir / "fixture.ifc"
    p.write_text(dedent(content).strip() + "\n", encoding="utf-8")
    return p


_IFC_HEADER = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('test.ifc','2026-05-13',('Test'),('OE'),'','OE','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1= IFCORGANIZATION($,'OE',$,$,$);
#2= IFCAPPLICATION(#1,'1.0','OE','OE');
#3= IFCPERSON($,'OE',$,$,$,$,$,$);
#4= IFCPERSONANDORGANIZATION(#3,#1,$);
#5= IFCOWNERHISTORY(#4,#2,$,.ADDED.,$,$,$,1234567890);
"""

_IFC_FOOTER = """\
ENDSEC;
END-ISO-10303-21;
"""


# ── _decode_step_string ───────────────────────────────────────────────


class TestDecodeStepString:
    """Direct unit coverage for the new STEP string decoder."""

    def test_unescapes_doubled_apostrophe_placeholder(self) -> None:
        """Audit C1 — placeholder restored to a single ASCII apostrophe."""
        encoded = f"O{_STEP_DOUBLE_QUOTE_PLACEHOLDER}Brien Tower"
        assert _decode_step_string(encoded) == "O'Brien Tower"

    def test_decodes_x_latin1_escape(self) -> None:
        """Audit C4 — ``\\X\\C4`` → U+00C4 (Latin-1 capital A-umlaut)."""
        # 0xC4 in Latin-1 maps to U+00C4; compare via codepoint to avoid
        # any source-encoding ambiguity in the test file itself.
        decoded = _decode_step_string(r"M\X\C4nchen")
        assert decoded[0] == "M"
        assert ord(decoded[1]) == 0xC4  # capital A-umlaut
        assert decoded[2:] == "nchen"

    def test_decodes_x2_utf16be_block(self) -> None:
        """Audit C4 — ``\\X2\\…\\X0\\`` block decoded as UTF-16BE."""
        # 0x0420 0x0443 0x0441 = three Cyrillic codepoints
        decoded = _decode_step_string(r"\X2\042004430441\X0\after")
        assert [ord(c) for c in decoded[:3]] == [0x0420, 0x0443, 0x0441]
        assert decoded[3:] == "after"

    def test_pass_through_when_no_escapes(self) -> None:
        """Plain ASCII strings round-trip untouched."""
        assert _decode_step_string("Wall-01") == "Wall-01"

    def test_empty_string(self) -> None:
        """Empty input returns empty output (no IndexError)."""
        assert _decode_step_string("") == ""


# ── C1: apostrophe in element name ───────────────────────────────────


def test_apostrophe_in_name_does_not_truncate_globalid(workdir: Path) -> None:
    """Audit C1 — ``O''Brien Tower`` must not split the preceding GUID.

    Before the fix the STEP tokenizer's greedy single-quote pairing
    parsed ``'22…' , #5, 'O''Brien Tower'`` as three strings:
      strings[0] = "22…GUID22"   ← truncated at the doubled '
      strings[1] = "O"
      strings[2] = "Brien Tower"
    After the fix the doubled apostrophe is replaced with a placeholder
    before regex tokenisation, so the GUID survives intact and the name
    contains a single ASCII apostrophe.
    """
    ifc = (
        _IFC_HEADER
        + (
            "#100= IFCBUILDINGSTOREY('2dEPbVfXn9bRTwS3l4kZ5G',#5,"
            "'O''Brien Tower',$,$,$,$,$,.ELEMENT.,0.0);\n"
            "#101= IFCWALL('1zZH5DqcvF7g5KkkN9mYTw',#5,'Wall',$,$,$,$,$,$);\n"
            "#102= IFCRELCONTAINEDINSPATIALSTRUCTURE("
            "'0relGUIDxxxxxxxxxxxxx',#5,$,$,(#101),#100);\n"
        )
        + _IFC_FOOTER
    )

    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    # The wall's storey should resolve to the apostrophised name —
    # this is the load-bearing post-condition because the storey list
    # in the result is built from element.storey, not raw
    # IFCBUILDINGSTOREY parsing.
    elements = result.get("elements", [])
    wall = next((e for e in elements if e["element_type"] == "Wall"), None)
    assert wall is not None, f"wall element missing — got {elements!r}"
    assert wall.get("storey") == "O'Brien Tower", (
        f"expected wall.storey to be the apostrophised name, got {wall.get('storey')!r}"
    )
    # And the wall's GUID must still be 22 chars (compressed IFC GUID).
    assert len(wall["stable_id"]) == 22, f"GUID truncated: {wall['stable_id']!r}"


# ── C5: multi-line entities must be picked up ────────────────────────


def test_multi_line_entity_is_parsed(workdir: Path) -> None:
    """Audit C5 — STEP statements are terminated by `;`, not `\\n`.

    Allplan/Revit/Tekla emit long IFCRELAGGREGATES / IFCPOLYLOOP rows on
    multiple physical lines. The old split-by-newline missed them.
    """
    # IFCRELCONTAINEDINSPATIALSTRUCTURE on three physical lines, valid
    # because STEP-21 only cares about ';' as a terminator.
    ifc = (
        _IFC_HEADER
        + (
            "#100= IFCBUILDINGSTOREY('2dEPbVfXn9bRTwS3l4kZ5G',#5,'L1',$,$,$,$,$,.ELEMENT.,0.0);\n"
            "#101= IFCWALL('1zZH5DqcvF7g5KkkN9mYTw',#5,'Wall1',$,$,$,$,$,$);\n"
            "#102= IFCWALL('1AAH5DqcvF7g5KkkN9mYAA',#5,'Wall2',$,$,$,$,$,$);\n"
            "#103= IFCRELCONTAINEDINSPATIALSTRUCTURE(\n"
            "  '0qABCDeFghijklmnoPqRs5',\n"
            "  #5,$,$,(#101,#102),#100);\n"
        )
        + _IFC_FOOTER
    )

    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    elements = result.get("elements", [])
    # Both walls should have been assigned the storey "L1".
    walls_with_storey = [e for e in elements if e["element_type"] == "Wall" and e.get("storey") == "L1"]
    assert len(walls_with_storey) == 2, f"expected 2 walls in L1, got {walls_with_storey!r}"


# ── C7: IfcQuantity regex no longer captures #N references ─────────


def test_quantity_value_not_confused_with_ref_id() -> None:
    """Audit C7 — IFCQUANTITYAREA('NetArea',$,$,#5,42.5) must give 42.5.

    Before the fix the regex `[\\d.]+(?:E[+-]?\\d+)?` matched the `5` in
    `#5` first, so we recorded NetArea=5 instead of 42.5.
    """
    # Hand-build a minimal entities dict that mirrors what the parser
    # produces, so we can unit-test the quantity extractor in isolation.
    entities = {
        100: {
            "id": 100,
            "type": "IFCWALL",
            "args_raw": "'1zZH5DqcvF7g5KkkN9mYTw',#5,'Wall',$,$,$,$,$,$",
            "strings": ["1zZH5DqcvF7g5KkkN9mYTw", "Wall"],
        },
        200: {
            "id": 200,
            "type": "IFCRELDEFINESBYPROPERTIES",
            # GUID, OwnerHistory, Name, Description, RelatedObjects=(#100),
            # RelatingPropertyDefinition=#300
            "args_raw": "'0relGUIDxxxxxxxxxxxxx',#5,$,$,(#100),#300",
            "strings": ["0relGUIDxxxxxxxxxxxxx"],
        },
        300: {
            "id": 300,
            "type": "IFCELEMENTQUANTITY",
            "args_raw": "'0eqGUIDxxxxxxxxxxxxxx',#5,'BaseQuantities',$,'OE',(#400)",
            "strings": ["0eqGUIDxxxxxxxxxxxxxx", "BaseQuantities", "OE"],
        },
        400: {
            "id": 400,
            "type": "IFCQUANTITYAREA",
            # Last positional arg is the area value (42.5 m²).
            "args_raw": "'NetArea',$,$,#5,42.5",
            "strings": ["NetArea"],
        },
    }
    quantities = _extract_quantities_for_element(100, entities)
    assert quantities.get("NetArea") == pytest.approx(42.5), f"expected NetArea=42.5, got {quantities!r}"


# ── C8: RelDefinesByProperties no longer matches via OwnerHistory ────


def test_rel_defines_by_properties_does_not_leak_through_owner_history() -> None:
    """Audit C8 — RelatedObjects must come from the parenthesised SET only.

    The old `refs[:-1]` membership test included OwnerHistory (and
    occasionally other framework refs), producing false-positive
    associations between property sets and elements that were never
    related to them in the IFC.
    """
    # Build an entities map where element #200's id (the wall) happens
    # to collide with the OwnerHistory id used by a RelDefinesByProperties
    # statement for a DIFFERENT element (the door, #100). Before the
    # fix the door's quantity would be wrongly attributed to the wall.
    entities = {
        100: {
            "id": 100,
            "type": "IFCDOOR",
            "args_raw": "'doorGUIDxxxxxxxxxxxxxx',#200,'Door',$,$,$,$,$,$",
            "strings": ["doorGUIDxxxxxxxxxxxxxx", "Door"],
        },
        200: {
            # This id is the OwnerHistory referenced by #300 below, NOT
            # an element. The previous parser would still mark #200 as
            # a "related object" through refs[:-1].
            "id": 200,
            "type": "IFCOWNERHISTORY",
            "args_raw": "$,#2,$,.ADDED.,$,$,$,1234567890",
            "strings": [],
        },
        300: {
            "id": 300,
            "type": "IFCRELDEFINESBYPROPERTIES",
            # GUID, OwnerHistory=#200, Name, Description,
            # RelatedObjects=(#100), RelatingPropertyDefinition=#400.
            "args_raw": "'relGUIDxxxxxxxxxxxxxx',#200,$,$,(#100),#400",
            "strings": ["relGUIDxxxxxxxxxxxxxx"],
        },
        400: {
            "id": 400,
            "type": "IFCELEMENTQUANTITY",
            "args_raw": "'eqGUIDxxxxxxxxxxxxxxx',#200,'BQ',$,'OE',(#500)",
            "strings": ["eqGUIDxxxxxxxxxxxxxxx", "BQ", "OE"],
        },
        500: {
            "id": 500,
            "type": "IFCQUANTITYAREA",
            "args_raw": "'NetArea',$,$,#200,2.0",
            "strings": ["NetArea"],
        },
    }
    # The OwnerHistory (#200) must NOT receive the door's quantities.
    qty_owner = _extract_quantities_for_element(200, entities)
    assert qty_owner == {}, f"OwnerHistory leaked door quantities: {qty_owner!r}"
    # The door (#100) must receive them.
    qty_door = _extract_quantities_for_element(100, entities)
    assert qty_door.get("NetArea") == pytest.approx(2.0)


# ── C6: STEP /* … */ comments are stripped ───────────────────────────


def test_step_comments_are_stripped(workdir: Path) -> None:
    """Audit C6 — `/* … */` blocks must not produce phantom entities.

    Tekla and Allplan emit comment blocks that contain `#N` references.
    Without stripping these comments the regex tokenizer would match
    them as entities, producing duplicate IDs and corrupted parse state.
    """
    ifc = (
        _IFC_HEADER
        + (
            "/* comment with #999= IFCWALL fake content */\n"
            "#100= IFCBUILDINGSTOREY('2dEPbVfXn9bRTwS3l4kZ5G',#5,'L1',$,$,$,$,$,.ELEMENT.,0.0);\n"
            "#101= IFCWALL('1zZH5DqcvF7g5KkkN9mYTw',#5,'Wall',$,$,$,$,$,$);\n"
        )
        + _IFC_FOOTER
    )

    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    elements = result.get("elements", [])
    # Exactly one wall must exist (the real #101), the comment must
    # not have produced a phantom #999 entity that shows up here.
    walls = [e for e in elements if e["element_type"] == "Wall"]
    assert len(walls) == 1, f"comment block leaked a phantom wall: {walls!r}"


# ── C2: IFC unit-assignment awareness ─────────────────────────────────


class TestIfcUnitAssignmentProbe:
    """Audit C2 — text-fallback must flag non-SI-metre files.

    We do NOT rescale quantities in the fallback (that's cad2data's
    job). The probe only sets ``unit_uncertain`` so the UI can refuse
    to roll them up.  See ``_ifc_units_are_non_si_metres`` doc.
    """

    def test_si_metre_is_certain(self) -> None:
        """Canonical SI-metre IFCUNITASSIGNMENT → unit_uncertain=False."""
        entities = {
            10: {
                "type": "IFCSIUNIT",
                "args_raw": "*,.LENGTHUNIT.,$,.METRE.",
                "strings": [],
            },
        }
        assert _ifc_units_are_non_si_metres(entities) is False

    def test_millimetre_is_uncertain(self) -> None:
        """mm prefix on IFCSIUNIT → flagged uncertain."""
        entities = {
            10: {
                "type": "IFCSIUNIT",
                "args_raw": "*,.LENGTHUNIT.,.MILLI.,.METRE.",
                "strings": [],
            },
        }
        assert _ifc_units_are_non_si_metres(entities) is True

    def test_imperial_inch_is_uncertain(self) -> None:
        """IFCCONVERSIONBASEDUNIT for INCH → flagged uncertain."""
        entities = {
            10: {
                "type": "IFCCONVERSIONBASEDUNIT",
                "args_raw": "*,.LENGTHUNIT.,'INCH',#11",
                "strings": ["INCH"],
            },
        }
        assert _ifc_units_are_non_si_metres(entities) is True

    def test_missing_length_unit_is_uncertain(self) -> None:
        """Conservative — no LENGTHUNIT row at all → uncertain."""
        entities = {
            10: {
                "type": "IFCWALL",
                "args_raw": "'guid',#5,'Wall',$",
                "strings": ["guid", "Wall"],
            },
        }
        assert _ifc_units_are_non_si_metres(entities) is True

    def test_si_metre_alongside_other_units_is_uncertain(self) -> None:
        """Mixed-unit project (SI metre for length + ft for some prop) is uncertain."""
        entities = {
            10: {
                "type": "IFCSIUNIT",
                "args_raw": "*,.LENGTHUNIT.,$,.METRE.",
                "strings": [],
            },
            11: {
                "type": "IFCCONVERSIONBASEDUNIT",
                "args_raw": "*,.LENGTHUNIT.,'FOOT',#12",
                "strings": ["FOOT"],
            },
        }
        # Both an SI metre row AND a conversion-based length unit →
        # safer to flag.  Real projects with consistent SI metres never
        # carry conversion-based length units.
        assert _ifc_units_are_non_si_metres(entities) is True


def test_full_parse_flags_unit_uncertain_when_units_missing(
    workdir: Path,
) -> None:
    """Audit C2 end-to-end — minimal IFC with no IFCUNITASSIGNMENT.

    Many real-world Allplan exports omit the unit assignment block
    entirely. The text-fallback parser must mark every element with
    ``unit_uncertain=True`` AND propagate the flag at the model root
    so the bim_hub router can show a "Install DDC converter" banner.
    """
    ifc = (
        _IFC_HEADER
        + (
            # IFCBUILDINGSTOREY + 1 wall, NO IFCSIUNIT / IFCUNITASSIGNMENT.
            "#100= IFCBUILDINGSTOREY('2dEPbVfXn9bRTwS3l4kZ5G',#5,'L1',$,$,$,$,$,.ELEMENT.,0.0);\n"
            "#101= IFCWALL('1zZH5DqcvF7g5KkkN9mYTw',#5,'Wall',$,$,$,$,$,$);\n"
            "#102= IFCRELCONTAINEDINSPATIALSTRUCTURE("
            "'0relGUIDxxxxxxxxxxxxx',#5,$,$,(#101),#100);\n"
        )
        + _IFC_FOOTER
    )

    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    assert result.get("unit_uncertain") is True
    for el in result.get("elements", []):
        assert el.get("unit_uncertain") is True
