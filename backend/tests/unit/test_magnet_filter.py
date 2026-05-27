# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the magnet-candidate suppressor.

Coverage:
    * Query classifier: confidence buckets from BIM vs sparse envelopes
    * Compatibility rules: MF / IFC / unit alignment + adjacency
    * Suppression policy: hard-drop / soft-penalty / no-op bands
    * End-to-end ``apply_to_hits`` with mocked hits
    * Env-var gating: filter is OFF unless ``OE_MATCH_MAGNET_FILTER=1``
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.match_service.boosts import magnet_filter as mf
from app.core.match_service.envelope import ElementEnvelope


def _envelope_concrete_wall() -> ElementEnvelope:
    """High-confidence BIM envelope: concrete wall, m², IfcWall."""
    return ElementEnvelope(
        source="bim",
        category="wall",
        description="Cast-in-place reinforced concrete wall, 240 mm thick, C30/37",
        properties={"material": "concrete C30/37", "thickness_mm": 240},
        quantities={"area_m2": 37.5},
        unit_hint="m2",
        ifc_class="IfcWall",
        material_class="concrete",
        nominal_size_mm=240,
        is_structural=True,
        is_loadbearing=True,
        source_lang="en",
    )


def _envelope_sparse() -> ElementEnvelope:
    """Low-confidence envelope: PDF source, no IFC, no quantities."""
    return ElementEnvelope(
        source="pdf",
        description="Wall finish",
        source_lang="en",
    )


def _hit(rate_code: str, score: float, **payload: Any) -> SimpleNamespace:
    """Build a lightweight QdrantHit-like SimpleNamespace for tests."""
    return SimpleNamespace(
        rate_code=rate_code,
        country="US",
        score=score,
        payload={"rate_code": rate_code, **payload},
    )


# ──────────────────────────────────────────────────────────────────────
#  classify_query — confidence derivation
# ──────────────────────────────────────────────────────────────────────


class TestClassifyQuery:
    def test_full_bim_envelope_is_high_confidence(self) -> None:
        c = mf.classify_query(_envelope_concrete_wall())
        # 0.30 IFC + 0.20 MF (via IFC→MF) + 0.20 unit + 0.15 material + 0.15 BIM = 1.0
        assert c.confidence == pytest.approx(1.0, abs=0.01)
        assert c.ifc_class == "IfcWall"
        assert "03" in c.mf_heads or "04" in c.mf_heads
        assert c.unit_family == "area"

    def test_sparse_pdf_envelope_is_low_confidence(self) -> None:
        c = mf.classify_query(_envelope_sparse())
        # No IFC, no MF, no unit family, no material, not BIM → 0.0
        assert c.confidence < mf._SOFT_PENALTY_FLOOR
        assert c.ifc_class is None
        assert c.mf_heads == ()
        assert c.unit_family is None

    def test_classifier_hint_drives_mf_head(self) -> None:
        env = _envelope_concrete_wall().model_copy(
            update={"classifier_hint": {"masterformat": "22 10 00"}},
        )
        c = mf.classify_query(env)
        # Explicit hint overrides IFC-derived MF
        assert "22" in c.mf_heads

    def test_quantity_implies_unit_when_no_hint(self) -> None:
        env = ElementEnvelope(
            source="bim",
            ifc_class="IfcPipeSegment",
            quantities={"length_m": 25.0},
            source_lang="en",
        )
        c = mf.classify_query(env)
        assert c.unit_family == "linear"


# ──────────────────────────────────────────────────────────────────────
#  Compatibility — _decide_compat
# ──────────────────────────────────────────────────────────────────────


class TestCompatibility:
    def test_aligned_concrete_wall_is_compatible(self) -> None:
        """High-conf concrete-wall query + concrete-wall candidate → keep."""
        c = mf.classify_query(_envelope_concrete_wall())
        payload = {
            "masterformat_division": "03 30 00",
            "ifc_class": "IfcWall",
            "unit_type": "Area",
        }
        compatible, reasons = mf._decide_compat(c, payload)
        assert compatible
        assert reasons == ()

    def test_magnet_electric_distribution_box_is_incompatible(self) -> None:
        """Concrete-wall query + IfcElectricDistributionBoard candidate → drop.

        This is the actual KAME_KAPU_KAMEDX_KAME magnet from the bench
        run. mf=26, IFC=ElectricDistributionBoard, unit=Count — 3-axis
        mismatch vs the IfcWall+Area+03 query.
        """
        c = mf.classify_query(_envelope_concrete_wall())
        payload = {
            "masterformat_division": "26 20 00",
            "ifc_class": "IfcElectricDistributionBoard",
            "unit_type": "Count",
        }
        compatible, reasons = mf._decide_compat(c, payload)
        assert not compatible
        # Must flag at least 2 axes
        assert len(reasons) >= 2
        assert "mf_mismatch" in reasons
        assert "unit_mismatch" in reasons

    def test_mf_adjacency_lets_masonry_pass_concrete_query(self) -> None:
        """Concrete query (mf=03) + masonry candidate (mf=04) → keep.

        The _MF_ADJACENCY map allows 03↔04 so the concrete vs masonry
        cross hit isn't suppressed — those are legitimate alternatives.
        """
        c = mf.classify_query(_envelope_concrete_wall())
        payload = {
            "masterformat_division": "04 20 00",  # masonry
            "ifc_class": "IfcWall",  # still a wall
            "unit_type": "Area",
        }
        compatible, _ = mf._decide_compat(c, payload)
        assert compatible

    def test_ifc_adjacency_covering_passes_roof_query(self) -> None:
        """IfcRoof query + IfcCovering candidate → keep (finish layer)."""
        env = ElementEnvelope(
            source="bim",
            description="Bituminous roof waterproofing",
            quantities={"area_m2": 320.0},
            unit_hint="m2",
            ifc_class="IfcRoof",
            material_class="bitumen",
            source_lang="en",
        )
        c = mf.classify_query(env)
        payload = {
            "masterformat_division": "07 00 00",
            "ifc_class": "IfcCovering",
            "unit_type": "Area",
        }
        compatible, _ = mf._decide_compat(c, payload)
        assert compatible

    def test_sparse_payload_with_mf_mismatch_drops_when_high_confidence(self) -> None:
        """High-conf query + candidate that has only MF (no IFC / unit) → drop on sparse.

        Catches the v3-payload-only magnets where the candidate ONLY
        has an MF division and the cross-encoder uses token-id noise
        to rank it.
        """
        c = mf.classify_query(_envelope_concrete_wall())
        payload = {
            "masterformat_division": "48 00 00",  # unrelated to 03
            # ifc_class missing, unit_type missing
        }
        compatible, reasons = mf._decide_compat(c, payload)
        assert not compatible
        assert "mf_mismatch" in reasons

    def test_unknown_candidate_classification_passes(self) -> None:
        """Candidate with no MF / IFC / unit info → keep (can't reject what we don't know)."""
        c = mf.classify_query(_envelope_concrete_wall())
        payload: dict[str, Any] = {}  # totally empty
        compatible, _ = mf._decide_compat(c, payload)
        assert compatible

    def test_pipe_query_vs_radiator_candidate_passes_via_adjacency(self) -> None:
        """IfcSpaceHeater query + IfcPipeSegment candidate → keep (radiator connects to pipe)."""
        env = ElementEnvelope(
            source="bim",
            ifc_class="IfcSpaceHeater",
            quantities={"count": 14.0},
            unit_hint="pcs",
            material_class="steel",
            source_lang="en",
        )
        c = mf.classify_query(env)
        payload = {
            "masterformat_division": "23 10 00",
            "ifc_class": "IfcPipeSegment",
            "unit_type": "Linear",
        }
        # MF and IFC adjacency both fire, only unit mismatches → 1 axis → keep
        compatible, _ = mf._decide_compat(c, payload)
        assert compatible


# ──────────────────────────────────────────────────────────────────────
#  Suppression policy — should_suppress
# ──────────────────────────────────────────────────────────────────────


class TestSuppressionPolicy:
    def test_high_confidence_query_hard_drops_incompatible(self) -> None:
        c = mf.classify_query(_envelope_concrete_wall())
        # Force confidence ≥ hard floor
        assert c.confidence >= mf._HARD_DROP_FLOOR
        payload = {
            "masterformat_division": "26 20 00",
            "ifc_class": "IfcElectricDistributionBoard",
            "unit_type": "Count",
        }
        d = mf.should_suppress(c, payload)
        assert d.action == "drop"
        assert d.score_delta == 0.0

    def test_low_confidence_query_never_suppresses(self) -> None:
        c = mf.classify_query(_envelope_sparse())
        payload = {
            "masterformat_division": "26 20 00",
            "ifc_class": "IfcElectricDistributionBoard",
            "unit_type": "Count",
        }
        d = mf.should_suppress(c, payload)
        assert d.action == "keep"

    def test_medium_confidence_query_applies_score_penalty(self) -> None:
        """A 0.5-0.8 confidence query should soft-penalise, not drop."""
        # Build an envelope landing in the 0.50–0.80 band:
        # IFC present (0.30) + MF derivable (0.20) + unit (0.20) = 0.70
        env = ElementEnvelope(
            source="pdf",
            ifc_class="IfcWall",
            unit_hint="m2",
            classifier_hint={"masterformat": "03 30 00"},
            source_lang="en",
        )
        c = mf.classify_query(env)
        assert mf._SOFT_PENALTY_FLOOR <= c.confidence < mf._HARD_DROP_FLOOR
        payload = {
            "masterformat_division": "26 20 00",
            "ifc_class": "IfcElectricDistributionBoard",
            "unit_type": "Count",
        }
        d = mf.should_suppress(c, payload)
        assert d.action == "penalise"
        assert d.score_delta == mf._SOFT_PENALTY

    def test_aligned_high_confidence_query_keeps_candidate(self) -> None:
        c = mf.classify_query(_envelope_concrete_wall())
        payload = {
            "masterformat_division": "03 30 00",
            "ifc_class": "IfcWall",
            "unit_type": "Area",
        }
        d = mf.should_suppress(c, payload)
        assert d.action == "keep"


# ──────────────────────────────────────────────────────────────────────
#  Pipeline integration — apply_to_hits
# ──────────────────────────────────────────────────────────────────────


class TestApplyToHits:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without OE_MATCH_MAGNET_FILTER=1 → input passes through unchanged."""
        monkeypatch.delenv("OE_MATCH_MAGNET_FILTER", raising=False)
        env = _envelope_concrete_wall()
        hits = [
            _hit(
                "KAME_KAPU_KAMEDX_KAME",
                0.50,
                masterformat_division="26 20 00",
                ifc_class="IfcElectricDistributionBoard",
                unit_type="Count",
            ),
            _hit("VALID_CONCRETE", 0.40, masterformat_division="03 30 00", ifc_class="IfcWall", unit_type="Area"),
        ]
        out = mf.apply_to_hits(env, hits)
        assert len(out) == 2
        assert [h.rate_code for h in out] == [h.rate_code for h in hits]

    def test_enabled_drops_real_magnets_on_concrete_wall(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With env var ON, the actual bench-observed magnets get dropped."""
        monkeypatch.setenv("OE_MATCH_MAGNET_FILTER", "1")
        env = _envelope_concrete_wall()
        hits = [
            # Real magnets from magnet_analysis.json:
            _hit(
                "KAME_KAPU_KAMEDX_KAME",
                0.50,
                masterformat_division="26 20 00",
                ifc_class="IfcElectricDistributionBoard",
                unit_type="Count",
            ),
            _hit(
                "KARI_KARI_KAKATO_KASA",
                0.45,
                masterformat_division="33 05 00",
                ifc_class="IfcReinforcingBar",
                unit_type="Count",
            ),
            _hit("KANE_KAME_KAKALI_KATOm", 0.40, masterformat_division="48 00 00", unit_type="Mass"),
            # The valid concrete wall candidate:
            _hit("VALID_CONCRETE_WALL", 0.30, masterformat_division="03 30 00", ifc_class="IfcWall", unit_type="Area"),
        ]
        out = mf.apply_to_hits(env, hits)
        codes = [h.rate_code for h in out]
        # The legitimate candidate survives
        assert "VALID_CONCRETE_WALL" in codes
        # At least one of the magnets was suppressed
        assert len(out) < len(hits)
        # All three problematic magnets specifically
        assert "KAME_KAPU_KAMEDX_KAME" not in codes
        assert "KANE_KAME_KAKALI_KATOm" not in codes

    def test_enabled_no_op_on_sparse_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sparse envelope (low confidence) → no candidates dropped even when ON."""
        monkeypatch.setenv("OE_MATCH_MAGNET_FILTER", "1")
        env = _envelope_sparse()
        hits = [
            _hit(
                "KAME_KAPU_KAMEDX_KAME",
                0.50,
                masterformat_division="26 20 00",
                ifc_class="IfcElectricDistributionBoard",
                unit_type="Count",
            ),
            _hit("VALID_CONCRETE", 0.40, masterformat_division="03 30 00", ifc_class="IfcWall", unit_type="Area"),
        ]
        out = mf.apply_to_hits(env, hits)
        assert len(out) == 2  # both pass through

    def test_empty_hits_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OE_MATCH_MAGNET_FILTER", "1")
        env = _envelope_concrete_wall()
        out = mf.apply_to_hits(env, [])
        assert out == []

    def test_penalise_mode_preserves_candidate_with_score_delta(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """In medium-confidence band: candidates stay, score is reduced."""
        monkeypatch.setenv("OE_MATCH_MAGNET_FILTER", "1")
        # Build a med-conf envelope (~0.70)
        env = ElementEnvelope(
            source="pdf",
            ifc_class="IfcWall",
            unit_hint="m2",
            classifier_hint={"masterformat": "03 30 00"},
            source_lang="en",
        )
        hits = [
            _hit(
                "MAGNET_BOX",
                0.50,
                masterformat_division="26 20 00",
                ifc_class="IfcElectricDistributionBoard",
                unit_type="Count",
            ),
        ]
        out = mf.apply_to_hits(env, hits)
        assert len(out) == 1  # not dropped, penalised
        assert out[0].score < 0.50  # score reduced by the penalty

    def test_parquet_fallback_lookup_when_payload_sparse(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If hit.payload lacks ifc_class but full_rows carries it → uses parquet."""
        monkeypatch.setenv("OE_MATCH_MAGNET_FILTER", "1")
        env = _envelope_concrete_wall()
        # Hit payload missing ifc_class; full_rows fills it in.
        hit = _hit("X", 0.50, masterformat_division="26 20 00", unit_type="Count")
        full_rows = {"X": {"ifc_class": "IfcElectricDistributionBoard"}}
        out = mf.apply_to_hits(env, [hit], full_rows=full_rows)
        # Three-axis incompatibility now visible → drop
        assert out == []


# ──────────────────────────────────────────────────────────────────────
#  Env-var gating — is_enabled
# ──────────────────────────────────────────────────────────────────────


class TestEnvGating:
    @pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE", "Yes"])
    def test_truthy_values_enable(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv("OE_MATCH_MAGNET_FILTER", val)
        assert mf.is_enabled() is True

    @pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "anything-else"])
    def test_falsy_values_disable(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv("OE_MATCH_MAGNET_FILTER", val)
        assert mf.is_enabled() is False

    def test_unset_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OE_MATCH_MAGNET_FILTER", raising=False)
        assert mf.is_enabled() is False
