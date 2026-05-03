# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests — auto-classifier-hint flow through extractors.

Phase 1 of the v2.8.0 vector match feature wires the
:func:`enrich_classification` helper into the BIM/PDF/DWG extractors so
that elements imported without a pre-baked ``classification`` block
still emit a ``classifier_hint`` for the matcher's classifier-boost.

These tests exercise the full path:

* BIM extractor with raw category + material → auto-derived hint
  populates :attr:`ElementEnvelope.classifier_hint`.
* BIM extractor with explicit ``classification`` block → existing block
  wins (no overwrite).
* The downstream classifier boost rewards candidates whose code matches
  the auto-derived hint.
* PDF / DWG extractors emit a coarse hint when only a category is known.
"""

from __future__ import annotations

from app.core.match_service.boosts import classifier as classifier_boost
from app.core.match_service.config import BOOST_WEIGHTS
from app.core.match_service.envelope import MatchCandidate
from app.core.match_service.extractors import build_envelope

# ── BIM extractor — auto-hint when classification missing ─────────────────


class TestBimAutoClassifierHint:
    """BIM extractor populates classifier_hint via classification_mapper
    when the upstream raw dict lacks a ``classification`` block."""

    def test_bim_auto_hint_for_concrete_wall(self) -> None:
        raw = {
            "category": "wall",
            "name": "Stahlbetonwand",
            "properties": {"material": "Concrete C30/37", "fire_rating": "F90"},
            "geometry": {"thickness_m": 0.24, "area_m2": 37.5},
            # No "classification" block.
            "language": "de",
        }
        envelope = build_envelope("bim", raw)
        assert envelope.classifier_hint is not None
        # Concrete wall → DIN 330.10 (Stahlbeton-Außenwand).
        assert envelope.classifier_hint["din276"] == "330.10"
        # All three standards populated so the matcher can pick by
        # settings.classifier without re-extracting.
        assert envelope.classifier_hint["nrm"] == "2.5.1"
        assert envelope.classifier_hint["masterformat"] == "03 30 00"

    def test_bim_auto_hint_for_brick_wall(self) -> None:
        raw = {
            "category": "wall",
            "properties": {"material": "Brick masonry, clay brick NF"},
            "geometry": {"area_m2": 67.2},
            "language": "en",
        }
        envelope = build_envelope("bim", raw)
        assert envelope.classifier_hint is not None
        assert envelope.classifier_hint["din276"] == "331.10"

    def test_bim_auto_hint_for_steel_column(self) -> None:
        raw = {
            "category": "column",
            "properties": {"material": "Structural steel S235JR"},
            "geometry": {"height_m": 3.5},
            "language": "en",
        }
        envelope = build_envelope("bim", raw)
        assert envelope.classifier_hint is not None
        assert envelope.classifier_hint["din276"] == "340.20"
        assert envelope.classifier_hint["masterformat"] == "05 12 00"

    def test_bim_explicit_classification_wins_over_auto(self) -> None:
        """Pre-baked classification is honoured; auto-hint never overwrites."""
        raw = {
            "category": "wall",
            "properties": {"material": "Concrete C30/37"},
            # An upstream pipeline already classified this — must not be
            # clobbered by the auto-derived deeper code.
            "classification": {"din276": "330.10.020"},
            "language": "en",
        }
        envelope = build_envelope("bim", raw)
        assert envelope.classifier_hint == {"din276": "330.10.020"}

    def test_bim_no_category_no_material_no_hint(self) -> None:
        """Empty raw dict → no classifier_hint."""
        envelope = build_envelope("bim", {"description": "something generic"})
        assert envelope.classifier_hint is None

    def test_bim_unknown_category_no_hint(self) -> None:
        """Category outside coarse map → no hint at all (None, not empty)."""
        envelope = build_envelope("bim", {
            "category": "Unobtanium",
            "properties": {"material": "concrete"},
        })
        assert envelope.classifier_hint is None

    def test_bim_fire_rated_door_routes_to_steel_variant(self) -> None:
        raw = {
            "category": "door",
            "properties": {
                "material": "Solid wood interior door",
                "fire_rating": "F90",
            },
        }
        envelope = build_envelope("bim", raw)
        assert envelope.classifier_hint is not None
        # F90 fire rating prefers the steel variant.
        assert envelope.classifier_hint["din276"] == "344.20"


# ── Classifier boost rewards auto-derived hint ────────────────────────────


class TestClassifierBoostHonoursAutoHint:
    """End-to-end seam: BIM extractor → envelope → classifier boost."""

    def test_classifier_boost_full_match_on_auto_hint(self) -> None:
        # Build envelope through the extractor (auto-hint path).
        envelope = build_envelope("bim", {
            "category": "wall",
            "properties": {"material": "Concrete C30/37"},
        })
        assert envelope.classifier_hint is not None
        hint_code = envelope.classifier_hint["din276"]

        # Candidate carries the same code in its classification field.
        candidate = MatchCandidate(
            code="X-001",
            classification={"din276": hint_code},
        )

        class _Settings:
            classifier = "din276"

        deltas = classifier_boost.boost(envelope, candidate, _Settings())
        assert deltas == {"classifier_match": BOOST_WEIGHTS.classifier_full_match}

    def test_classifier_boost_group_match_on_auto_hint(self) -> None:
        """Auto-hint ``330.10`` rewards a candidate with ``330.10.020``."""
        envelope = build_envelope("bim", {
            "category": "wall",
            "properties": {"material": "Concrete C30/37"},
        })
        # Auto-hint resolves to ``330.10`` — a CWICR-style 3-level code
        # ``330.10.020`` shares the group.
        candidate = MatchCandidate(
            code="X-002",
            classification={"din276": "330.10.020"},
        )

        class _Settings:
            classifier = "din276"

        deltas = classifier_boost.boost(envelope, candidate, _Settings())
        # Forward containment ("330.10".startswith ⊂ "330.10.020") fires
        # the group-match boost.
        assert "classifier_group_match" in deltas
        assert deltas["classifier_group_match"] == BOOST_WEIGHTS.classifier_group_match

    def test_classifier_boost_no_match_when_codes_diverge(self) -> None:
        """Auto-hint for masonry must NOT reward a concrete candidate."""
        envelope = build_envelope("bim", {
            "category": "wall",
            "properties": {"material": "Brick masonry"},
        })
        candidate = MatchCandidate(
            code="X-003",
            classification={"din276": "330.10.020"},  # concrete
        )

        class _Settings:
            classifier = "din276"

        deltas = classifier_boost.boost(envelope, candidate, _Settings())
        assert deltas == {}

    def test_classifier_boost_other_classifier_setting_no_op(self) -> None:
        """Settings.classifier='masterformat' uses MF hint, not DIN."""
        envelope = build_envelope("bim", {
            "category": "wall",
            "properties": {"material": "Concrete C30/37"},
        })
        # Auto-hint includes all three standards.
        assert envelope.classifier_hint["masterformat"] == "03 30 00"

        candidate = MatchCandidate(
            code="X-004",
            classification={"masterformat": "03 30 00"},
        )

        class _Settings:
            classifier = "masterformat"

        deltas = classifier_boost.boost(envelope, candidate, _Settings())
        assert deltas == {"classifier_match": BOOST_WEIGHTS.classifier_full_match}


# ── PDF / DWG extractors emit coarse hint ─────────────────────────────────


class TestPdfDwgCoarseHint:
    """PDF/DWG rarely have material info — coarse category-only hint."""

    def test_pdf_extractor_coarse_hint_from_category(self) -> None:
        envelope = build_envelope("pdf", {
            "description": "Wandanstrich Dispersionsfarbe weiss",
            "category": "wall",
            "unit": "m2",
            "quantity": 220.0,
            "language": "de",
        })
        # No material → coarse "330" only (not 330.10).
        assert envelope.classifier_hint is not None
        assert envelope.classifier_hint["din276"] == "330"

    def test_pdf_extractor_no_category_no_hint(self) -> None:
        envelope = build_envelope("pdf", {
            "description": "Dispersionsfarbe weiss",
            "unit": "m2",
            "language": "de",
        })
        assert envelope.classifier_hint is None

    def test_pdf_explicit_classification_preserved(self) -> None:
        """PDF extractor honours upstream classification (legacy behaviour)."""
        envelope = build_envelope("pdf", {
            "description": "Wandanstrich",
            "category": "wall",
            "classification": {"din276": "363.10.010"},  # specific paint code
            "language": "de",
        })
        assert envelope.classifier_hint == {"din276": "363.10.010"}

    def test_dwg_extractor_coarse_hint_from_layer_category(self) -> None:
        # DWG extractor derives category from the AIA layer code.
        envelope = build_envelope("dwg", {
            "description": "Drywall partition, double-sided 12.5 mm gypsum",
            "layer": "A-WALL-PRTN",
            "language": "en",
        })
        assert envelope.category == "wall"  # derived from layer
        # Coarse hint emitted (no material to refine on).
        assert envelope.classifier_hint is not None
        assert envelope.classifier_hint["din276"] == "330"

    def test_dwg_unknown_layer_unknown_category_no_hint(self) -> None:
        envelope = build_envelope("dwg", {
            "description": "x",
            "layer": "S-EXOTIC-XXX",
        })
        # Category resolves to "exotic" — not in coarse map, no hint.
        assert envelope.classifier_hint is None
