"""Tests for the ``scripts/build_enriched_snapshot.py`` synthesis layer.

The script lives outside the ``backend/app/`` package so we import it
via a path injection. We're testing the pure-function bits — payload-
to-passage synthesis — not the network/Qdrant code (those are covered
implicitly by the integration test against a real local server).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Inject the scripts/ directory so we can import build_enriched_snapshot.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from build_enriched_snapshot import (  # noqa: E402
    _build_description,
    _build_passage_text,
    _mf_label,
    _normalise_text,
    _split_camelcase,
)

# ── _split_camelcase ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("inp", "expected"),
    [
        ("ReinforcedConcrete", "Reinforced Concrete"),
        ("IfcSlab", "Ifc Slab"),
        ("IfcWall", "Ifc Wall"),
        ("IfcCovering", "Ifc Covering"),
        # Pure ALL-CAPS short tokens title-case rather than split letter-by-letter
        ("CLADDING", "Cladding"),
        ("USERDEFINED", "Userdefined"),
        ("MEP", "Mep"),
        # Already-spaced strings pass through unchanged
        ("plain text", "plain text"),
        # Empty → empty
        ("", ""),
    ],
)
def test_split_camelcase(inp: str, expected: str) -> None:
    assert _split_camelcase(inp) == expected


# ── _normalise_text ─────────────────────────────────────────────────────


def test_normalise_text_titlecases_all_caps() -> None:
    """ALL-CAPS noun phrases → Title Case for natural sentence reading."""
    assert _normalise_text("REPAIR AND CONSTRUCTION WORKS") == "Repair And Construction Works"
    assert _normalise_text("CONSTRUCTION WORK") == "Construction Work"


def test_normalise_text_preserves_mixed_case() -> None:
    """Non-ALL-CAPS text passes through (preserves "Stucco work" verbatim)."""
    assert _normalise_text("Stucco work") == "Stucco work"
    assert _normalise_text("Tunneling works") == "Tunneling works"


def test_normalise_text_handles_none_and_empty() -> None:
    assert _normalise_text(None) == ""
    assert _normalise_text("") == ""
    assert _normalise_text("   ") == ""


# ── _mf_label ───────────────────────────────────────────────────────────


def test_mf_label_known_divisions() -> None:
    """Known MasterFormat divisions get human labels."""
    assert _mf_label("03 30 00") == "MasterFormat 03 30 00 Concrete"
    assert _mf_label("09 21 00") == "MasterFormat 09 21 00 Finishes"
    assert _mf_label("22 11 00") == "MasterFormat 22 11 00 Plumbing"
    assert _mf_label("26 27 00") == "MasterFormat 26 27 00 Electrical"


def test_mf_label_unknown_division_falls_back_to_digits() -> None:
    """Unknown prefixes don't fabricate — just emit digits."""
    # 99 is not a standard division — still emit the digits without a label.
    out = _mf_label("99 99 99")
    assert "99 99 99" in out
    assert "MasterFormat" in out


def test_mf_label_empty_returns_empty() -> None:
    assert _mf_label("") == ""


# ── _build_passage_text ─────────────────────────────────────────────────


def test_passage_text_concrete_wall_full_payload() -> None:
    """Realistic IfcWall concrete payload — every meaningful field present."""
    payload = {
        "rate_code": "TEST_CONCRETE_WALL",
        "collection_name": "Monolithic concrete and reinforced concrete structures",
        "material_class": "ReinforcedConcrete",
        "ifc_class": "IfcWall",
        "ost_category": "OST_Walls",
        "category_type": "CONSTRUCTION WORK",
        "installation_method": "CastInPlace",
        "construction_stage": "03_Structure",
        "uniformat_group": "B_Shell",
        "unit_type": "Volume",
        "rate_unit": "m3",
        "masterformat_division": "03 30 00",
    }
    passage = _build_passage_text(payload)
    # Topical anchor
    assert "Monolithic concrete and reinforced concrete structures" in passage
    # CamelCase splits gave the encoder real tokens
    assert "Reinforced Concrete" in passage
    assert "Ifc Wall" in passage
    # OST_ prefix stripped
    assert "Walls" in passage and "OST_" not in passage
    # ALL-CAPS title-cased
    assert "Construction Work" in passage
    # Camelcase installation method
    assert "Cast In Place" in passage
    # Stage prefix stripped, underscored words spaced out
    assert "Structure" in passage and "03_" not in passage
    # Uniformat prefix stripped
    assert "Shell" in passage
    # Unit paired with rate_unit
    assert "Volume (m3)" in passage
    # MasterFormat with label
    assert "MasterFormat 03 30 00 Concrete" in passage


def test_passage_text_sparse_payload_only_what_is_present() -> None:
    """Snapshot rows often have many fields blank — empty/None must not pollute."""
    payload = {
        "rate_code": "SPARSE",
        "collection_name": "Stucco work",
        "masterformat_division": "09 24 00",
        # Everything else None/missing
    }
    passage = _build_passage_text(payload)
    assert "Stucco work" in passage
    assert "MasterFormat 09 24 00 Finishes" in passage
    # No em-dash spam, no None tokens
    assert "None" not in passage
    assert ". ." not in passage  # No empty segments


def test_passage_text_dedups_construction_stage_and_uniformat_overlap() -> None:
    """13_Sitework and G_Sitework collapse to one ``Sitework`` token.

    Pre-fix: ``"Sitework. Sitework."`` from two adjacent stage/uniformat
    fields. Post-fix: dedup pass collapses to one.
    """
    payload = {
        "rate_code": "DEDUP_TEST",
        "collection_name": "Motorways",
        "construction_stage": "13_Sitework",
        "uniformat_group": "G_Sitework",
        "masterformat_division": "32 10 00",
    }
    passage = _build_passage_text(payload)
    # Sitework appears exactly once
    assert passage.lower().count("sitework") == 1


def test_passage_text_userdefined_subtype_dropped() -> None:
    """USERDEFINED / NOTDEFINED IFC predefined types are noise — drop them."""
    payload = {
        "rate_code": "TEST",
        "collection_name": "Test collection",
        "ifc_class": "IfcWall",
        "ifc_predefined_type": "USERDEFINED",  # Should be skipped
    }
    passage = _build_passage_text(payload)
    assert "Ifc Wall" in passage
    assert "Userdefined" not in passage
    assert "USERDEFINED" not in passage


def test_passage_text_cladding_subtype_kept_and_titlecased() -> None:
    """Real IFC predefined types like CLADDING are kept and title-cased."""
    payload = {
        "rate_code": "TEST",
        "collection_name": "Stucco work",
        "ifc_class": "IfcCovering",
        "ifc_predefined_type": "CLADDING",
    }
    passage = _build_passage_text(payload)
    assert "Ifc Covering" in passage
    assert "Cladding" in passage
    # Not letter-spaced
    assert "C L A D D I N G" not in passage


def test_passage_text_empty_payload_returns_empty_string() -> None:
    """Truly empty payload returns empty (caller falls back to rate_code)."""
    assert _build_passage_text({}) == ""
    assert _build_passage_text({"rate_code": "X"}) == ""  # rate_code alone is not descriptive


def test_build_description_equals_passage_today() -> None:
    """description and passage_text are identical fields today.

    They're kept as separate payload keys so future work can diverge
    them (e.g., short UI label vs long encoder passage) without a
    re-ingest.
    """
    payload = {
        "rate_code": "T",
        "collection_name": "Internal piping",
        "masterformat_division": "22 10 00",
    }
    passage = _build_passage_text(payload)
    assert _build_description(passage) == passage


def test_passage_text_real_bench_fixture_drywall() -> None:
    """Verify against a real payload from the cwicr_en_v3 snapshot.

    From bench fixture q08 (drywall partition). The synthesised passage
    must be meaningfully comparable to the bench query
    "Drywall partition, double-side 12.5mm gypsum on metal stud" — i.e.,
    share salient nouns like "Partitions" and "Finishes".
    """
    payload = {
        "rate_code": "SASA_KAME_KAKADX_KAME",
        "collection_name": "Partitions",
        "category_type": "REPAIR AND CONSTRUCTION WORKS",
        "construction_stage": "02_Demolition",
        "uniformat_group": "F_Special_Demo",
        "unit_type": "Area",
        "rate_unit": "100 SF",
        "masterformat_division": "09 21 00",
    }
    passage = _build_passage_text(payload)
    assert "Partitions" in passage
    assert "Finishes" in passage  # From MasterFormat 09 label
    assert "Area (100 SF)" in passage
    # Multi-segment uniformat stripped & spaced
    assert "Special Demo" in passage
