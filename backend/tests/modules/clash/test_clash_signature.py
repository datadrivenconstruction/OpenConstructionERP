# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the clash signature algorithm (v41).

The signature is the join key that lets a smart issue persist across
re-runs. These tests pin its mathematical contract:

* deterministic across multiple calls with the same inputs
* GUID-pair symmetric ((A, B) hash == (B, A) hash)
* invariant to sub-grid centroid drift (the spatial-grid bucketing)
* changes when ``tolerance`` changes (different signature → new issue)
* falls back to the weak ``ifc_class | material | qty_keys`` form when
  one or both GUIDs are missing
* unicode-safe canonicalisation (NFKC + lower + strip)

Pure-function tests — no DB session, no fixtures beyond pytest itself.
"""

from __future__ import annotations

import hashlib

import pytest

from app.modules.clash.service import (
    _ARCHIVE_AFTER_MISSING,
    _DEFAULT_SPATIAL_GRID_MM,
    _bucket,
    _canon_guid,
    _compute_signature_hash,
)

# ── Pure-helper tests ────────────────────────────────────────────────────


def test_canon_guid_strips_and_lowercases() -> None:
    assert _canon_guid(" ABC123 ") == "abc123"


def test_canon_guid_handles_none_and_empty() -> None:
    assert _canon_guid(None) == ""
    assert _canon_guid("") == ""
    assert _canon_guid("   ") == ""


def test_canon_guid_nfkc_normalises_unicode() -> None:
    # NFKC normalisation: full-width ASCII → ASCII, accents preserved.
    assert _canon_guid("ＡＢＣ") == "abc"
    # Combining-diacritic vs precomposed form: both lower-case identical.
    # (Both forms canonicalise to the same NFKC string.)
    a = _canon_guid("café")  # precomposed é
    b = _canon_guid("café")  # base + combining acute
    assert a == b


def test_bucket_basic_floor() -> None:
    # 0.3 m → 300 mm → floor(300/500) = 0
    assert _bucket(0.3, 500) == 0
    # 0.5 m → 500 mm → floor(500/500) = 1
    assert _bucket(0.5, 500) == 1
    # 1.3 m → 1300 mm → floor(1300/500) = 2
    assert _bucket(1.3, 500) == 2


def test_bucket_negative() -> None:
    # -0.3 m → -300 mm → floor(-300/500) = -1
    assert _bucket(-0.3, 500) == -1


def test_bucket_zero_grid_is_safe() -> None:
    # Defensive: zero / negative grid never raises.
    assert _bucket(1.5, 0) == 0
    assert _bucket(1.5, -10) == 0


def test_bucket_nan_inf_is_safe() -> None:
    assert _bucket(float("nan"), 500) == 0
    assert _bucket(float("inf"), 500) == 0


# ── Signature determinism ────────────────────────────────────────────────


def _sig(**kwargs) -> tuple[str, str]:
    """Helper — apply defaults so each test states only what it cares about."""
    return _compute_signature_hash(
        a_guid=kwargs.pop("a_guid", "GUID-A"),
        b_guid=kwargs.pop("b_guid", "GUID-B"),
        centroid=kwargs.pop("centroid", (1.234, 2.345, 3.456)),
        clash_type=kwargs.pop("clash_type", "hard"),
        grid_mm=kwargs.pop("grid_mm", _DEFAULT_SPATIAL_GRID_MM),
        weak_fallback=kwargs.pop("weak_fallback", None),
    )


def test_signature_is_deterministic() -> None:
    h1, q1 = _sig()
    h2, q2 = _sig()
    assert h1 == h2
    assert q1 == q2 == "strong"


def test_signature_is_40_hex_characters() -> None:
    h, _ = _sig()
    assert len(h) == 40
    int(h, 16)  # raises if not hex


def test_signature_pair_symmetric_a_b_vs_b_a() -> None:
    h_ab, _ = _sig(a_guid="A", b_guid="B")
    h_ba, _ = _sig(a_guid="B", b_guid="A")
    assert h_ab == h_ba


def test_signature_pair_symmetric_with_unicode() -> None:
    h_ab, _ = _sig(a_guid=" alpha ", b_guid="Beta")
    h_ba, _ = _sig(a_guid="BETA", b_guid="ALPHA")
    assert h_ab == h_ba


def test_signature_stable_across_many_runs() -> None:
    # 100 identical computations — all must hash the same.
    seen = {_sig()[0] for _ in range(100)}
    assert len(seen) == 1


# ── Bucket-grid invariance ───────────────────────────────────────────────


def test_signature_invariant_to_submm_drift() -> None:
    """0.5 mm drift on each axis stays in the same 500 mm bucket."""
    h1, _ = _sig(centroid=(1.0, 2.0, 3.0))
    h2, _ = _sig(centroid=(1.0005, 2.0005, 3.0005))
    assert h1 == h2


def test_signature_invariant_to_subgrid_drift() -> None:
    """Drift within one grid cell (< 500 mm) keeps the same hash."""
    # 1.234 m and 1.499 m: floor(1234/500)=2, floor(1499/500)=2 — same bucket.
    h1, _ = _sig(centroid=(1.234, 0, 0))
    h2, _ = _sig(centroid=(1.499, 0, 0))
    assert h1 == h2


def test_signature_changes_at_grid_boundary() -> None:
    """Crossing a bucket boundary yields a new signature."""
    # 0.499 m → bucket 0, 0.500 m → bucket 1.
    h1, _ = _sig(centroid=(0.499, 0, 0))
    h2, _ = _sig(centroid=(0.501, 0, 0))
    assert h1 != h2


def test_signature_grid_size_changes_hash() -> None:
    """Different grid_mm → generally different signature."""
    h_500, _ = _sig(centroid=(1.0, 0, 0), grid_mm=500)
    h_100, _ = _sig(centroid=(1.0, 0, 0), grid_mm=100)
    assert h_500 != h_100


def test_signature_finer_grid_more_discriminating() -> None:
    """A 100 mm grid distinguishes drifts the 500 mm grid absorbs."""
    h1_coarse, _ = _sig(centroid=(0.0, 0, 0), grid_mm=500)
    h2_coarse, _ = _sig(centroid=(0.2, 0, 0), grid_mm=500)
    assert h1_coarse == h2_coarse  # 0 and 200 mm — same 500-bucket

    h1_fine, _ = _sig(centroid=(0.0, 0, 0), grid_mm=100)
    h2_fine, _ = _sig(centroid=(0.2, 0, 0), grid_mm=100)
    assert h1_fine != h2_fine  # 0 and 200 mm — different 100-buckets


# ── Tolerance / clash_type semantics ─────────────────────────────────────


def test_signature_clash_type_segregates_hard_from_clearance() -> None:
    h_hard, _ = _sig(clash_type="hard")
    h_clr, _ = _sig(clash_type="clearance")
    assert h_hard != h_clr


def test_signature_changes_when_pair_changes() -> None:
    h1, _ = _sig(a_guid="A", b_guid="B")
    h2, _ = _sig(a_guid="A", b_guid="C")
    assert h1 != h2


# ── Weak / strong quality ────────────────────────────────────────────────


def test_strong_when_both_guids_present() -> None:
    _h, q = _sig(a_guid="GUID-A", b_guid="GUID-B")
    assert q == "strong"


def test_weak_when_a_guid_missing_and_fallback_provided() -> None:
    _h, q = _sig(
        a_guid=None,
        b_guid="GUID-B",
        weak_fallback=("IfcWall", "concrete", ["area", "volume"]),
    )
    assert q == "weak"


def test_weak_when_b_guid_missing_and_fallback_provided() -> None:
    _h, q = _sig(
        a_guid="GUID-A",
        b_guid="",
        weak_fallback=("IfcWall", "concrete", ["area"]),
    )
    assert q == "weak"


def test_weak_when_both_guids_missing_and_fallback_provided() -> None:
    _h, q = _sig(
        a_guid=None,
        b_guid=None,
        weak_fallback=("IfcWall", "concrete", ["area"]),
    )
    assert q == "weak"


def test_weak_fallback_uses_ifc_class_material_qty_keys() -> None:
    """Same fallback inputs → same hash; different inputs → different hash."""
    h1, _ = _sig(
        a_guid=None,
        b_guid=None,
        weak_fallback=("IfcWall", "concrete", ["area", "volume"]),
    )
    h2, _ = _sig(
        a_guid=None,
        b_guid=None,
        weak_fallback=("IfcWall", "concrete", ["area", "volume"]),
    )
    h3, _ = _sig(
        a_guid=None,
        b_guid=None,
        weak_fallback=("IfcWall", "steel", ["area", "volume"]),
    )
    assert h1 == h2
    assert h1 != h3


def test_weak_fallback_qty_keys_sorted_for_determinism() -> None:
    """Reordering quantity keys must not change the weak signature."""
    h_ordered, _ = _sig(
        a_guid=None,
        b_guid=None,
        weak_fallback=("IfcWall", "concrete", ["area", "volume", "length"]),
    )
    h_shuffled, _ = _sig(
        a_guid=None,
        b_guid=None,
        weak_fallback=("IfcWall", "concrete", ["volume", "length", "area"]),
    )
    assert h_ordered == h_shuffled


def test_strong_path_used_when_no_fallback_supplied() -> None:
    """No fallback + missing GUIDs → still strong (empty stable_ids hash)."""
    _h, q = _sig(a_guid=None, b_guid=None, weak_fallback=None)
    assert q == "strong"


# ── Tolerance-change semantics (caller responsibility) ───────────────────


def test_changing_tolerance_can_yield_new_signature_via_grid() -> None:
    """The spec calls out tolerance changes as new signatures. The
    signature itself doesn't read tolerance directly — the caller varies
    the grid (or stamps a different tolerance_at_signature_time_mm on the
    row) to express that. Here we pin the underlying contract: changing
    the grid produces a different hash, which is the mechanism we use.
    """
    h_coarse, _ = _sig(grid_mm=500)
    h_fine, _ = _sig(grid_mm=50)
    assert h_coarse != h_fine


# ── Unicode safety ───────────────────────────────────────────────────────


def test_signature_unicode_safe_guids() -> None:
    """Unicode GUIDs (e.g. NFC vs NFD) hash to the same value after canon."""
    # Precomposed é vs base + combining acute — NFKC normalisation
    # collapses both to the same string.
    h1, _ = _sig(a_guid="café-001", b_guid="object-β")
    h2, _ = _sig(a_guid="café-001", b_guid="OBJECT-β")
    assert h1 == h2


def test_signature_handles_emoji_and_cjk() -> None:
    """Random non-ASCII GUIDs hash deterministically + do not raise."""
    h1, _ = _sig(a_guid="🏗️-wall-1", b_guid="梁-001")
    h2, _ = _sig(a_guid="🏗️-wall-1", b_guid="梁-001")
    assert h1 == h2
    assert len(h1) == 40


# ── Spec-grade canonical form ────────────────────────────────────────────


def test_signature_matches_spec_form() -> None:
    """End-to-end check against the literal SHA-1 of the canonical string.

    Spec: ``SHA1(canon(min)|canon(max)|bx,by,bz|clash_type)``.
    """
    a = "GUID-X"
    b = "GUID-Y"
    centroid = (1.234, 2.345, 3.456)  # mm: 1234, 2345, 3456
    grid_mm = 500
    # canon: lower-case; pair sorted ⇒ "guid-x" < "guid-y"
    raw = "guid-x|guid-y|2,4,6|hard"
    expected = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    h, q = _compute_signature_hash(
        a_guid=a,
        b_guid=b,
        centroid=centroid,
        clash_type="hard",
        grid_mm=grid_mm,
    )
    assert h == expected
    assert q == "strong"


# ── Misc / safety rails ──────────────────────────────────────────────────


def test_archive_threshold_constant_is_three() -> None:
    """Pin the spec — issues missing for 3 runs → archived."""
    assert _ARCHIVE_AFTER_MISSING == 3


def test_default_spatial_grid_is_500_mm() -> None:
    assert _DEFAULT_SPATIAL_GRID_MM == 500


@pytest.mark.parametrize(
    "ct1,ct2",
    [
        ("hard", "HARD"),
        ("Hard", "hard"),
        ("Clearance", "clearance"),
    ],
)
def test_signature_clash_type_canonicalised(ct1: str, ct2: str) -> None:
    """Clash type is NFKC-lowered before hashing — case-insensitive."""
    h1, _ = _sig(clash_type=ct1)
    h2, _ = _sig(clash_type=ct2)
    assert h1 == h2
