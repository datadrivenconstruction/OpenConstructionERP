"""Tests for ``app.modules.bim_requirements.yaml_loader``.

The loader is the security boundary of the rules-as-YAML feature: it
must refuse code-injection-shaped inputs (``!!python/object/apply``),
refuse pathological regex patterns, and produce errors that point at
the offending file and line so the operator can fix them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.bim_requirements.yaml_loader import (
    MAX_REGEX_LENGTH,
    PropertyAssertion,
    RulePack,
    RulePackParseError,
    SetVsSetAssertion,
    load_all_packs,
    load_rule_pack,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED_DIR = REPO_ROOT / "data" / "bim_rules"


# ── Helpers ────────────────────────────────────────────────────────────────


def _minimal_pack_yaml() -> str:
    return (
        "schema_version: '1.0'\n"
        "pack:\n"
        "  id: minimal\n"
        "  name: Minimal Pack\n"
        "rules:\n"
        "  - id: r1\n"
        "    name: First rule\n"
        "    selector:\n"
        "      ifc_class: IfcWall\n"
        "    assertion:\n"
        "      property:\n"
        "        key: FireRating\n"
        "        op: exists\n"
        "        value: true\n"
    )


# ── Happy path ─────────────────────────────────────────────────────────────


def test_loads_minimal_valid_pack() -> None:
    """A minimum-viable pack parses to a RulePack with one Rule."""
    pack = load_rule_pack("<inline>", text=_minimal_pack_yaml())
    assert isinstance(pack, RulePack)
    assert pack.pack.id == "minimal"
    assert len(pack.rules) == 1
    assert pack.rules[0].id == "r1"
    assert isinstance(pack.rules[0].assertion, PropertyAssertion)


def test_default_severity_is_warning() -> None:
    """Severity defaults to 'warning' when not specified."""
    pack = load_rule_pack("<inline>", text=_minimal_pack_yaml())
    assert pack.rules[0].severity == "warning"


def test_loads_all_seed_packs() -> None:
    """Every seed YAML in data/bim_rules/ parses successfully.

    The directory ships at least the original five DACH-focused packs plus
    the LOD 300 / LOD 400 / COBie handover packs; new packs may be added
    over time so the assertion is "every expected pack present" rather
    than "exactly N packs".
    """
    packs = load_all_packs(SEED_DIR)
    ids = {p.pack.id for p in packs}
    expected = {
        "din_276_kg_completeness",
        "clearance_corridor_door",
        "fire_compartment_property",
        "mep_clearance",
        "room_naming_convention",
        "lod300_design_development",
        "lod400_construction",
        "cobie_handover",
    }
    assert expected.issubset(ids), f"missing seed packs: {expected - ids}"
    assert len(packs) >= len(expected)


def test_mep_clearance_is_set_vs_set() -> None:
    """The MEP pack must round-trip as a set_vs_set rule."""
    pack = load_rule_pack(SEED_DIR / "mep_clearance.yaml")
    rule = pack.rules[0]
    assert rule.rule_type == "set_vs_set"
    assert isinstance(rule.assertion, SetVsSetAssertion)
    assert rule.assertion.set_vs_set.metric == "clearance"


# ── Safety: yaml tags ──────────────────────────────────────────────────────


def test_rejects_python_object_apply_tag() -> None:
    """Refuse the classic ``!!python/object/apply`` code-execution vector."""
    malicious = (
        "schema_version: '1.0'\npack:\n  id: bad\n  name: bad\nrules: !!python/object/apply:os.system ['echo pwned']\n"
    )
    with pytest.raises(RulePackParseError) as exc:
        load_rule_pack("<inline>", text=malicious)
    assert "python/" in str(exc.value).lower()


def test_rejects_python_name_tag() -> None:
    """Refuse the ``!!python/name`` variant as well."""
    malicious = "schema_version: '1.0'\npack:\n  id: bad\n  name: bad\nrules:\n  - !!python/name:os.system\n"
    with pytest.raises(RulePackParseError):
        load_rule_pack("<inline>", text=malicious)


# ── Safety: regex ──────────────────────────────────────────────────────────


def test_rejects_overlong_regex_pattern() -> None:
    """Patterns longer than the ReDoS cap must be rejected."""
    long_pattern = "a" * (MAX_REGEX_LENGTH + 1)
    yaml_text = (
        "schema_version: '1.0'\n"
        "pack: { id: redos, name: redos }\n"
        "rules:\n"
        "  - id: r1\n"
        "    name: long-regex\n"
        "    assertion:\n"
        "      property:\n"
        "        key: Name\n"
        "        op: regex\n"
        f"        value: '{long_pattern}'\n"
    )
    with pytest.raises(RulePackParseError) as exc:
        load_rule_pack("<inline>", text=yaml_text)
    assert "redos" in str(exc.value).lower() or "256" in str(exc.value)


def test_rejects_invalid_regex_syntax() -> None:
    """An unparseable regex must be rejected with a clear error."""
    yaml_text = (
        "schema_version: '1.0'\n"
        "pack: { id: bad_re, name: bad_re }\n"
        "rules:\n"
        "  - id: r1\n"
        "    name: bad\n"
        "    assertion:\n"
        "      property:\n"
        "        key: Name\n"
        "        op: regex\n"
        "        value: '['\n"
    )
    with pytest.raises(RulePackParseError):
        load_rule_pack("<inline>", text=yaml_text)


# ── Schema validation ─────────────────────────────────────────────────────


def test_schema_version_mismatch_raises_clean_error() -> None:
    """Unknown schema_version must fail with a useful message."""
    yaml_text = (
        "schema_version: '99.0'\n"
        "pack: { id: x, name: x }\n"
        "rules:\n"
        "  - { id: r, name: r, assertion: { property: { key: A, op: exists, value: true } } }\n"
    )
    with pytest.raises(RulePackParseError) as exc:
        load_rule_pack("<inline>", text=yaml_text)
    assert "schema_version" in str(exc.value).lower()


def test_unknown_operator_rejected() -> None:
    """Predicates with an unknown operator must be rejected at load time."""
    yaml_text = (
        "schema_version: '1.0'\n"
        "pack: { id: x, name: x }\n"
        "rules:\n"
        "  - id: r1\n"
        "    name: bad-op\n"
        "    assertion: { property: { key: A, op: not_a_real_op, value: 1 } }\n"
    )
    with pytest.raises(RulePackParseError) as exc:
        load_rule_pack("<inline>", text=yaml_text)
    assert "operator" in str(exc.value).lower()


def test_duplicate_rule_ids_rejected() -> None:
    """Two rules with the same id inside one pack is a load-time error."""
    yaml_text = (
        "schema_version: '1.0'\n"
        "pack: { id: dup, name: dup }\n"
        "rules:\n"
        "  - id: same\n"
        "    name: a\n"
        "    assertion: { property: { key: A, op: exists, value: true } }\n"
        "  - id: same\n"
        "    name: b\n"
        "    assertion: { property: { key: B, op: exists, value: true } }\n"
    )
    with pytest.raises(RulePackParseError) as exc:
        load_rule_pack("<inline>", text=yaml_text)
    assert "duplicate" in str(exc.value).lower()


def test_extra_fields_rejected() -> None:
    """Typo'd field names must surface, not silently disappear."""
    yaml_text = (
        "schema_version: '1.0'\n"
        "pack:\n"
        "  id: extras\n"
        "  name: extras\n"
        "  noSuchKey: oops\n"
        "rules:\n"
        "  - id: r1\n"
        "    name: r1\n"
        "    assertion: { property: { key: A, op: exists, value: true } }\n"
    )
    with pytest.raises(RulePackParseError):
        load_rule_pack("<inline>", text=yaml_text)


# ── Error reporting ───────────────────────────────────────────────────────


def test_yaml_syntax_error_reports_line_number() -> None:
    """Broken YAML must come back with a line number, not a bare exception."""
    broken = (
        "schema_version: '1.0'\n"
        "pack: { id: bad, name: bad,\n"  # unterminated mapping
        "rules: []\n"
    )
    with pytest.raises(RulePackParseError) as exc:
        load_rule_pack("<inline>", text=broken)
    err = exc.value
    assert err.line is not None
    assert err.line >= 2


def test_load_all_packs_rejects_missing_directory(tmp_path: Path) -> None:
    """A non-existent root must raise immediately, not silently return []."""
    missing = tmp_path / "does-not-exist"
    with pytest.raises(RulePackParseError):
        load_all_packs(missing)


def test_load_all_packs_skips_non_yaml(tmp_path: Path) -> None:
    """Files without a .yaml/.yml suffix must be ignored, not failed on."""
    (tmp_path / "README.md").write_text("not yaml at all")
    (tmp_path / "ok.yaml").write_text(_minimal_pack_yaml())
    packs = load_all_packs(tmp_path)
    assert len(packs) == 1
    assert packs[0].pack.id == "minimal"


def test_rule_id_pattern_enforced() -> None:
    """Rule ids must be safe for use as URL fragments and source refs."""
    yaml_text = (
        "schema_version: '1.0'\n"
        "pack: { id: x, name: x }\n"
        "rules:\n"
        "  - id: 'has spaces'\n"
        "    name: r\n"
        "    assertion: { property: { key: A, op: exists, value: true } }\n"
    )
    with pytest.raises(RulePackParseError):
        load_rule_pack("<inline>", text=yaml_text)


def test_between_requires_two_element_list() -> None:
    """The `between` op needs a [min, max] pair, not a scalar."""
    yaml_text = (
        "schema_version: '1.0'\n"
        "pack: { id: x, name: x }\n"
        "rules:\n"
        "  - id: r1\n"
        "    name: r1\n"
        "    assertion: { property: { key: Width, op: between, value: 1.5 } }\n"
    )
    with pytest.raises(RulePackParseError):
        load_rule_pack("<inline>", text=yaml_text)
