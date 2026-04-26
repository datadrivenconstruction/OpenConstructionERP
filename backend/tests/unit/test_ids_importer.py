"""Unit tests for the IDS → ValidationRule importer.

Covers task tracker #224 mandates:
    1. parse a known-good IDS file and assert rule count + ids
    2. multi-spec parse + check ``validate()`` produces the expected pass/fail
    3. malformed IDS → IDSImportError, no stack trace
    4. attribute-required predicate fires when the element is missing it
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.validation.engine import (
    RuleCategory,
    Severity,
    ValidationContext,
)
from app.modules.validation.ids_importer import (
    IDSImportError,
    IDSValidationRule,
    parse_ids,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ids"


# ── 1. Round-trip: known-good IDS file ──────────────────────────────────────


def test_parse_multi_spec_fixture_count_and_ids() -> None:
    """``ids_10_multi_specification.xml`` has three specs → three rules."""
    rules = parse_ids(FIXTURES / "ids_10_multi_specification.xml")

    assert len(rules) == 3
    # All three must be IDSValidationRule instances with the IDS standard.
    for rule in rules:
        assert isinstance(rule, IDSValidationRule)
        assert rule.standard == "IDS"
        assert rule.category == RuleCategory.COMPLIANCE
        assert rule.severity == Severity.ERROR
        assert rule.enabled

    rule_ids = {r.rule_id for r in rules}
    # The ``identifier`` attributes in the fixture become slugs.
    assert "ids.ids_10_walls" in rule_ids
    assert "ids.ids_10_slabs" in rule_ids
    assert "ids.ids_10_doors" in rule_ids


# ── 2. Multi-spec validate() produces expected pass/fail ───────────────────


@pytest.mark.asyncio
async def test_validate_multi_spec_pass_and_fail() -> None:
    """Walls/slabs/doors fixture exercised against synthetic canonical elements.

    Element fixtures:
        * wall_ok        — IFCWALL with Pset_WallCommon.IsExternal      → PASS for spec 1
        * wall_missing   — IFCWALL with no IsExternal                   → FAIL for spec 1
        * slab_ok        — IFCSLAB with Pset_SlabCommon.LoadBearing     → PASS for spec 2
        * door_no_rating — IFCDOOR with no FireRating                   → FAIL for spec 3
    """
    rules = parse_ids(FIXTURES / "ids_10_multi_specification.xml")
    rule_by_id = {r.rule_id: r for r in rules}

    elements = [
        {
            "id": "wall_ok",
            "ifc_class": "IfcWall",
            "category": "Walls",
            "properties": {"Pset_WallCommon": {"IsExternal": True}},
        },
        {
            "id": "wall_missing",
            "ifc_class": "IfcWall",
            "category": "Walls",
            "properties": {},
        },
        {
            "id": "slab_ok",
            "ifc_class": "IfcSlab",
            "category": "Slabs",
            "properties": {"LoadBearing": True},
        },
        {
            "id": "door_no_rating",
            "ifc_class": "IfcDoor",
            "category": "Doors",
            "properties": {},
        },
    ]
    ctx = ValidationContext(data={"elements": elements})

    walls_rule = rule_by_id["ids.ids_10_walls"]
    wall_results = await walls_rule.validate(ctx)
    by_ref = {r.element_ref: r for r in wall_results}
    # Only wall elements are applicable.
    assert set(by_ref) == {"wall_ok", "wall_missing"}
    assert by_ref["wall_ok"].passed is True
    assert by_ref["wall_missing"].passed is False
    assert "IsExternal" in by_ref["wall_missing"].message

    slabs_rule = rule_by_id["ids.ids_10_slabs"]
    slab_results = await slabs_rule.validate(ctx)
    by_ref = {r.element_ref: r for r in slab_results}
    assert set(by_ref) == {"slab_ok"}
    assert by_ref["slab_ok"].passed is True

    doors_rule = rule_by_id["ids.ids_10_doors"]
    door_results = await doors_rule.validate(ctx)
    by_ref = {r.element_ref: r for r in door_results}
    assert set(by_ref) == {"door_no_rating"}
    assert by_ref["door_no_rating"].passed is False
    assert "FireRating" in by_ref["door_no_rating"].message


# ── 3. Malformed IDS → IDSImportError ──────────────────────────────────────


def test_malformed_xml_raises_clear_error() -> None:
    """Garbage input → IDSImportError with a useful message, not a stack trace."""
    with pytest.raises(IDSImportError) as excinfo:
        parse_ids(b"this is not XML at all <<>><><><")
    assert "Invalid IDS XML" in str(excinfo.value) or "Failed to parse" in str(excinfo.value)


def test_wrong_root_element_raises() -> None:
    """A well-formed XML doc that isn't IDS → IDSImportError."""
    bad = b"""<?xml version='1.0'?><root><child/></root>"""
    with pytest.raises(IDSImportError) as excinfo:
        parse_ids(bad)
    assert "ids" in str(excinfo.value).lower()


def test_missing_specifications_raises() -> None:
    """An IDS doc with no <specifications> element raises IDSImportError."""
    bad = (
        b"<?xml version='1.0'?>"
        b'<ids xmlns="http://standards.buildingsmart.org/IDS"></ids>'
    )
    with pytest.raises(IDSImportError) as excinfo:
        parse_ids(bad)
    assert "specifications" in str(excinfo.value).lower()


# ── 4. Attribute-required predicate fires when missing ─────────────────────


@pytest.mark.asyncio
async def test_attribute_required_fires_when_missing() -> None:
    """``ids_03_entity_with_attribute.xml`` requires Name=EXT.* on IfcDoor."""
    rules = parse_ids(FIXTURES / "ids_03_entity_with_attribute.xml")
    assert len(rules) == 1
    rule = rules[0]

    elements = [
        # Door with proper EXT-prefixed name → PASS.
        {"id": "door_a", "ifc_class": "IfcDoor", "Name": "EXT-1234"},
        # Door without Name attribute at all → FAIL (attribute required).
        {"id": "door_b", "ifc_class": "IfcDoor"},
        # Door with non-matching name → FAIL (regex restriction).
        {"id": "door_c", "ifc_class": "IfcDoor", "Name": "INT-Office"},
        # Wall — out of scope, must NOT generate a result for this rule.
        {"id": "wall_x", "ifc_class": "IfcWall", "Name": "EXT-irrelevant"},
    ]
    ctx = ValidationContext(data={"elements": elements})
    results = await rule.validate(ctx)
    by_ref = {r.element_ref: r for r in results}

    # Only doors are in scope.
    assert "wall_x" not in by_ref
    assert set(by_ref) == {"door_a", "door_b", "door_c"}
    assert by_ref["door_a"].passed is True
    assert by_ref["door_b"].passed is False
    assert "Name" in by_ref["door_b"].message
    assert by_ref["door_c"].passed is False  # regex EXT.* doesn't match INT-*


# ── Bonus: parse-from-string + parse-from-bytes paths ──────────────────────


def test_parse_from_string_and_bytes() -> None:
    """parse_ids accepts both str and bytes payloads (not just paths)."""
    text = (FIXTURES / "ids_02_entity_with_property.xml").read_text(encoding="utf-8")
    from_str = parse_ids(text)
    from_bytes = parse_ids(text.encode("utf-8"))
    assert len(from_str) == 1
    assert len(from_bytes) == 1
    assert from_str[0].rule_id == from_bytes[0].rule_id


@pytest.mark.asyncio
async def test_no_applicable_elements_passes_vacuously() -> None:
    """A spec with no in-scope elements should still emit one passed result."""
    rules = parse_ids(FIXTURES / "ids_02_entity_with_property.xml")
    assert len(rules) == 1
    rule = rules[0]
    ctx = ValidationContext(data={"elements": []})
    results = await rule.validate(ctx)
    assert len(results) == 1
    assert results[0].passed is True
    assert "vacuously" in results[0].message.lower() or "no applicable" in results[0].message.lower()
