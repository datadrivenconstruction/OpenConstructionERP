# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-function tests for the clash service helpers (no DB, no GLB).

These pin the mathematical / heuristic contracts of the small pure
helpers that the clash engine, the cluster/rule subsystem, the KPI
dashboard and the BCF round-trip all build on. They construct tiny
in-memory stand-ins for ``ClashResult`` / ``ClashRun`` / ``BIMElement``
rows (only the attributes each helper reads are populated) and drive the
module-level functions directly, so the whole file runs without a live
PostgreSQL session or any GLB asset.

The functions under test were previously only exercised indirectly (via
the DB-backed engine path) or not at all; pinning them here turns a
silent regression in, e.g., the cluster tie-break, the DBSCAN labelling,
the FP rule miner, the MTTR window or the BCF status map into a fast,
deterministic test failure.

Per ``feedback_test_isolation.md`` the import-time env guard in
``tests/conftest.py`` already points ``DATABASE_URL`` at the per-session
embedded PostgreSQL cluster before this module is imported (importing
``app.modules.clash.service`` transitively touches ``app.database``);
the tests themselves never open a session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.clash.service import (
    _FP_SUGGESTION_THRESHOLD,
    _apply_rules,
    _bcf_status_to_clash_status,
    _coerce_rules,
    _collect_fp_pairs,
    _compute_kpi,
    _dbscan_cluster,
    _disc,
    _disc_system,
    _dominant_pair_and_storey,
    _existing_rule_pairs,
    _label_for_cluster,
    _norm_bbox,
    _resolved_mttr_hours,
    _severity_suggestion,
    _signature,
    _signature_from_description,
    _suggest_rule_from_fps,
)

# ── Tiny stand-ins ─────────────────────────────────────────────────────────


class _Row:
    """Minimal ClashResult stand-in for the pure aggregation helpers.

    Only the attributes the helper under test reads are populated; every
    helper accesses these defensively (``getattr`` / ``or``) so missing
    ones are fine.
    """

    def __init__(
        self,
        *,
        a_disc: str = "Mechanical",
        b_disc: str = "Structural",
        a_name: str = "Duct-1",
        b_name: str = "Beam-1",
        severity: str = "medium",
        status: str = "new",
        clash_type: str = "hard",
        a_storey: int | None = None,
        b_storey: int | None = None,
        penetration_m: float = 0.0,
        history: list[dict] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.a_discipline = a_disc
        self.b_discipline = b_disc
        self.a_name = a_name
        self.b_name = b_name
        self.severity = severity
        self.status = status
        self.clash_type = clash_type
        self.a_storey = a_storey
        self.b_storey = b_storey
        self.penetration_m = penetration_m
        self.history = history or []
        self.created_at = created_at


class _Run:
    """Minimal ClashRun stand-in carrying just a ``rules`` JSON list."""

    def __init__(self, rules: object) -> None:
        self.rules = rules


class _El:
    """Minimal BIMElement stand-in (only ``bounding_box`` matters here)."""

    def __init__(self, bounding_box: object) -> None:
        self.bounding_box = bounding_box


# ── _signature (run-independent pair identity) ─────────────────────────────


def test_signature_is_pair_symmetric_and_type_segregated() -> None:
    assert _signature("A", "B", "hard") == _signature("B", "A", "hard")
    # clash_type is part of the key: a hard hit and a clearance hit on the
    # same pair are distinct signatures.
    assert _signature("A", "B", "hard") != _signature("A", "B", "clearance")


def test_signature_is_16_hex_and_deterministic() -> None:
    sig = _signature("guid-x", "guid-y", "hard")
    assert len(sig) == 16
    int(sig, 16)  # raises if not hex
    assert sig == _signature("guid-x", "guid-y", "hard")


def test_signature_handles_missing_ids() -> None:
    # None-ish ids coerce to "" and never raise; still symmetric.
    assert _signature("", "", "hard") == _signature("", "", "hard")
    assert _signature("A", "", "hard") == _signature("", "A", "hard")


# ── _label_for_cluster / _dominant_pair_and_storey ─────────────────────────


def test_label_for_empty_members_is_generic() -> None:
    assert _label_for_cluster([], 7) == "Cluster 7"
    assert _dominant_pair_and_storey([]) == (("", ""), None)


def test_label_picks_dominant_pair_and_storey() -> None:
    members = [
        _Row(a_disc="Mechanical", b_disc="Structural", a_storey=3, b_storey=3),
        _Row(a_disc="Mechanical", b_disc="Structural", a_storey=3, b_storey=3),
        _Row(a_disc="Architectural", b_disc="Electrical", a_storey=1, b_storey=1),
    ]
    label = _label_for_cluster(members, 1)
    assert label == "Mechanical × Structural - Level 3"
    (a, b), storey = _dominant_pair_and_storey(members)
    assert (a, b) == ("Mechanical", "Structural")
    assert storey == 3


def test_label_pair_is_alphabetically_canonical() -> None:
    # a_disc > b_disc on input -> the pair is still stored (min, max).
    members = [_Row(a_disc="Structural", b_disc="Mechanical")]
    assert _label_for_cluster(members, 2).startswith("Mechanical × Structural")


def test_label_and_dominant_pair_agree_on_count_tie() -> None:
    """On a count tie the FULL (a, b) tuple breaks it - and the label and
    the structured helper MUST pick the SAME pair (Wave 6 fixed a weaker
    first-char-only tie-break that could disagree)."""
    members = [
        _Row(a_disc="Mechanical", b_disc="Plumbing"),
        _Row(a_disc="Mechanical", b_disc="Structural"),
    ]
    label = _label_for_cluster(members, 3)
    (a, b), _ = _dominant_pair_and_storey(members)
    # max() over (count, pair): both count 1, so the larger pair tuple
    # wins -> ("Mechanical", "Structural").
    assert (a, b) == ("Mechanical", "Structural")
    assert label == "Mechanical × Structural"


def test_label_unassigned_when_disciplines_blank() -> None:
    members = [_Row(a_disc="", b_disc="   ")]
    assert _label_for_cluster(members, 4) == "Unassigned × Unassigned"


def test_dominant_storey_ignores_unparseable_levels() -> None:
    members = [
        _Row(a_disc="Mechanical", b_disc="Structural", a_storey=2, b_storey=None),
        _Row(a_disc="Mechanical", b_disc="Structural", a_storey=2, b_storey=2),
    ]
    (_a, _b), storey = _dominant_pair_and_storey(members)
    assert storey == 2


# ── _dbscan_cluster ────────────────────────────────────────────────────────


def test_dbscan_empty_returns_empty() -> None:
    assert _dbscan_cluster([]) == []


def test_dbscan_two_close_points_form_one_cluster() -> None:
    pts = [(0.0, 0.0, 0.0), (0.1, 0.0, 0.0)]
    labels = _dbscan_cluster(pts, eps_m=0.6, min_samples=2)
    assert labels == [1, 1]


def test_dbscan_isolated_point_is_noise() -> None:
    pts = [(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (100.0, 0.0, 0.0)]
    labels = _dbscan_cluster(pts, eps_m=0.6, min_samples=2)
    assert labels[0] == labels[1] == 1
    assert labels[2] is None  # far away, below min_samples -> noise


def test_dbscan_two_separated_groups_get_distinct_ids() -> None:
    pts = [
        (0.0, 0.0, 0.0),
        (0.2, 0.0, 0.0),
        (50.0, 0.0, 0.0),
        (50.2, 0.0, 0.0),
    ]
    labels = _dbscan_cluster(pts, eps_m=0.6, min_samples=2)
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]
    # Numbered in iteration order -> first group is cluster 1.
    assert labels[0] == 1
    assert labels[2] == 2


def test_dbscan_is_deterministic() -> None:
    pts = [(0.0, 0.0, 0.0), (0.3, 0.0, 0.0), (0.6, 0.0, 0.0), (9.0, 9.0, 9.0)]
    first = _dbscan_cluster(pts)
    for _ in range(5):
        assert _dbscan_cluster(pts) == first


def test_dbscan_eps_is_inclusive_boundary() -> None:
    # Exactly eps apart -> distance**2 == eps**2 -> inside (inclusive).
    pts = [(0.0, 0.0, 0.0), (0.6, 0.0, 0.0)]
    assert _dbscan_cluster(pts, eps_m=0.6, min_samples=2) == [1, 1]
    # Just beyond eps -> separate -> both noise at min_samples=2.
    pts2 = [(0.0, 0.0, 0.0), (0.61, 0.0, 0.0)]
    assert _dbscan_cluster(pts2, eps_m=0.6, min_samples=2) == [None, None]


def test_dbscan_over_cap_noops_to_all_noise() -> None:
    from app.modules.clash.service import _MAX_CLUSTER_RESULTS

    n = _MAX_CLUSTER_RESULTS + 1
    pts = [(0.0, 0.0, 0.0)] * n  # identical points, but over the cap
    labels = _dbscan_cluster(pts)
    assert labels == [None] * n


# ── _apply_rules ───────────────────────────────────────────────────────────


def test_apply_rules_matches_symmetric_pair() -> None:
    run = _Run([{"discipline_a": "Mechanical", "discipline_b": "Structural", "tolerance_m": 0.05}])
    # Both orderings of the candidate pair match the single declared rule.
    assert _apply_rules(run, ("Mechanical", "Structural")) is not None
    assert _apply_rules(run, ("Structural", "Mechanical")) is not None


def test_apply_rules_is_case_insensitive() -> None:
    run = _Run([{"discipline_a": "mechanical", "discipline_b": "STRUCTURAL"}])
    assert _apply_rules(run, ("Mechanical", "Structural")) is not None


def test_apply_rules_skips_disabled_and_first_match_wins() -> None:
    run = _Run(
        [
            {"id": "r1", "discipline_a": "Mechanical", "discipline_b": "Structural", "enabled": False},
            {"id": "r2", "discipline_a": "Mechanical", "discipline_b": "Structural", "tolerance_m": 0.2},
        ]
    )
    rule = _apply_rules(run, ("Mechanical", "Structural"))
    assert rule is not None
    assert rule["id"] == "r2"  # disabled r1 skipped, first enabled wins


def test_apply_rules_no_match_returns_none() -> None:
    run = _Run([{"discipline_a": "Mechanical", "discipline_b": "Structural"}])
    assert _apply_rules(run, ("Mechanical", "Electrical")) is None


def test_apply_rules_is_defensive_against_junk() -> None:
    # Non-list rules, non-dict entries, blank disciplines -> never raises.
    assert _apply_rules(_Run("nonsense"), ("A", "B")) is None
    assert _apply_rules(_Run([None, 7, "x"]), ("A", "B")) is None
    assert _apply_rules(_Run(None), ("A", "B")) is None
    assert _apply_rules(_Run([{"discipline_a": "", "discipline_b": ""}]), ("", "")) is None


# ── _coerce_rules / _existing_rule_pairs ───────────────────────────────────


def test_coerce_rules_strips_non_dict_noise() -> None:
    assert _coerce_rules([{"a": 1}, None, 7, "x", {"b": 2}]) == [{"a": 1}, {"b": 2}]
    assert _coerce_rules("not a list") == []
    assert _coerce_rules(None) == []


def test_existing_rule_pairs_are_lowercased_and_symmetric() -> None:
    pairs = _existing_rule_pairs(
        [
            {"discipline_a": "Mechanical", "discipline_b": "Structural"},
            {"discipline_a": "  Electrical ", "discipline_b": "Plumbing"},
            {"discipline_a": "", "discipline_b": "Structural"},  # skipped (blank)
        ]
    )
    assert frozenset({"mechanical", "structural"}) in pairs
    assert frozenset({"electrical", "plumbing"}) in pairs
    assert len(pairs) == 2  # the blank-discipline rule is dropped


# ── _collect_fp_pairs ──────────────────────────────────────────────────────


def test_collect_fp_pairs_from_ignored_status() -> None:
    rows = [
        _Row(a_disc="Mechanical", b_disc="Structural", status="ignored", penetration_m=0.04),
        _Row(a_disc="Mechanical", b_disc="Structural", status="ignored", penetration_m=0.02),
        _Row(a_disc="Mechanical", b_disc="Structural", status="new", penetration_m=0.5),  # not FP
    ]
    pairs, max_pen = _collect_fp_pairs(rows)
    assert pairs == [("Mechanical", "Structural"), ("Mechanical", "Structural")]
    # max penetration tracked per pair, ignoring the non-FP row.
    assert max_pen[("Mechanical", "Structural")] == pytest.approx(0.04)


def test_collect_fp_pairs_from_history_flag() -> None:
    rows = [
        _Row(
            a_disc="Electrical",
            b_disc="Plumbing",
            status="reviewed",
            history=[{"field": "fp_flag", "after": "true"}],
            penetration_m=0.03,
        ),
    ]
    pairs, max_pen = _collect_fp_pairs(rows)
    assert pairs == [("Electrical", "Plumbing")]
    assert max_pen[("Electrical", "Plumbing")] == pytest.approx(0.03)


def test_collect_fp_pairs_canonicalises_and_defaults_unassigned() -> None:
    rows = [_Row(a_disc="", b_disc="Structural", status="ignored")]
    pairs, _max_pen = _collect_fp_pairs(rows)
    # Blank discipline -> "Unassigned"; pair sorted alphabetically.
    assert pairs == [("Structural", "Unassigned")]


# ── _suggest_rule_from_fps ─────────────────────────────────────────────────


def test_suggest_rule_none_below_threshold() -> None:
    pairs = [("Mechanical", "Structural")] * (_FP_SUGGESTION_THRESHOLD - 1)
    rule, reason, count = _suggest_rule_from_fps(pairs)
    assert rule is None
    assert reason == ""
    assert count == _FP_SUGGESTION_THRESHOLD - 1


def test_suggest_rule_empty_input() -> None:
    assert _suggest_rule_from_fps([]) == (None, "", 0)


def test_suggest_rule_at_threshold_proposes_pair() -> None:
    pairs = [("Mechanical", "Structural")] * _FP_SUGGESTION_THRESHOLD
    rule, reason, count = _suggest_rule_from_fps(pairs)
    assert count == _FP_SUGGESTION_THRESHOLD
    assert rule is not None
    assert rule["discipline_a"] == "Mechanical"
    assert rule["discipline_b"] == "Structural"
    assert rule["enabled"] is True
    assert rule["tolerance_m"] == 0.05  # safe default when no penetration data
    assert "false positives" in reason


def test_suggest_rule_widens_tolerance_past_max_penetration() -> None:
    pairs = [("Mechanical", "Structural")] * _FP_SUGGESTION_THRESHOLD
    rule, _reason, _count = _suggest_rule_from_fps(
        pairs,
        fp_max_penetration_by_pair={("Mechanical", "Structural"): 0.12},
    )
    assert rule is not None
    # round(0.12 + 0.01, 3) = 0.13, within [0.05, 0.50].
    assert rule["tolerance_m"] == pytest.approx(0.13)


def test_suggest_rule_caps_tolerance_at_half_metre() -> None:
    pairs = [("Mechanical", "Structural")] * _FP_SUGGESTION_THRESHOLD
    rule, _reason, _count = _suggest_rule_from_fps(
        pairs,
        fp_max_penetration_by_pair={("Mechanical", "Structural"): 5.0},
    )
    assert rule is not None
    assert rule["tolerance_m"] == 0.50  # ceiling, never catastrophic


def test_suggest_rule_tie_break_is_full_pair_deterministic() -> None:
    """Two pairs sharing a leading discipline, equal counts -> the FULL
    (a, b) tuple breaks the tie deterministically (Wave 6 fix)."""
    pairs = [("Mechanical", "Plumbing")] * _FP_SUGGESTION_THRESHOLD + [
        ("Mechanical", "Structural")
    ] * _FP_SUGGESTION_THRESHOLD
    rule, _reason, _count = _suggest_rule_from_fps(pairs)
    assert rule is not None
    # max() over (count, pair): equal counts, larger pair tuple wins.
    assert (rule["discipline_a"], rule["discipline_b"]) == ("Mechanical", "Structural")


# ── _severity_suggestion (advisory bump) ───────────────────────────────────


def test_severity_suggestion_only_for_deep_hard_clash() -> None:
    # Deep hard clash with headroom -> bump one band.
    assert _severity_suggestion("hard", 0.2, "medium") == "high"
    assert _severity_suggestion("hard", 0.11, "low") == "medium"
    # Shallow hard clash -> no suggestion.
    assert _severity_suggestion("hard", 0.10, "low") is None
    assert _severity_suggestion("hard", 0.05, "low") is None


def test_severity_suggestion_none_for_clearance() -> None:
    assert _severity_suggestion("clearance", 0.5, "low") is None


def test_severity_suggestion_none_at_ceiling() -> None:
    # Already critical -> no headroom -> None.
    assert _severity_suggestion("hard", 0.5, "critical") is None
    # Unknown base band -> None (never invents a bump).
    assert _severity_suggestion("hard", 0.5, "bogus") is None


# ── _norm_bbox (dual-dialect normaliser) ───────────────────────────────────


def test_norm_bbox_flat_form() -> None:
    bb = {"min_x": 0.0, "min_y": 0.0, "min_z": 0.0, "max_x": 1.0, "max_y": 2.0, "max_z": 3.0}
    assert _norm_bbox(bb) == (0.0, 0.0, 0.0, 1.0, 2.0, 3.0)


def test_norm_bbox_nested_form() -> None:
    bb = {"min": {"x": -1.0, "y": -2.0, "z": -3.0}, "max": {"x": 1.0, "y": 2.0, "z": 3.0}}
    assert _norm_bbox(bb) == (-1.0, -2.0, -3.0, 1.0, 2.0, 3.0)


def test_norm_bbox_rejects_degenerate_and_nan() -> None:
    # Zero-volume box (max == min on an axis) -> None.
    flat_degenerate = {"min_x": 0.0, "min_y": 0.0, "min_z": 0.0, "max_x": 0.0, "max_y": 1.0, "max_z": 1.0}
    assert _norm_bbox(flat_degenerate) is None
    # NaN -> None.
    nan_box = {"min_x": 0.0, "min_y": 0.0, "min_z": 0.0, "max_x": float("nan"), "max_y": 1.0, "max_z": 1.0}
    assert _norm_bbox(nan_box) is None


def test_norm_bbox_rejects_malformed_input() -> None:
    assert _norm_bbox(None) is None
    assert _norm_bbox("not a dict") is None
    assert _norm_bbox({}) is None  # neither dialect's keys present
    assert _norm_bbox({"min_x": "oops", "min_y": 0, "min_z": 0, "max_x": 1, "max_y": 1, "max_z": 1}) is None


# ── _disc / _disc_system ───────────────────────────────────────────────────


def test_disc_defaults_blank_to_unassigned() -> None:
    assert _disc("Mechanical") == "Mechanical"
    assert _disc("  ") == "Unassigned"
    assert _disc(None) == "Unassigned"


def test_disc_system_composes_with_middle_dot() -> None:
    # Composed "discipline · system" uses U+00B7, NOT an em dash.
    assert _disc_system("Mechanical", "HVAC") == "Mechanical · HVAC"
    # No system -> bare (defaulted) discipline.
    assert _disc_system("Mechanical", "") == "Mechanical"
    assert _disc_system("", None) == "Unassigned"


# ── _bcf_status_to_clash_status (BCF round-trip map) ───────────────────────


@pytest.mark.parametrize(
    ("topic_status", "expected"),
    [
        ("Open", "active"),
        ("IN PROGRESS", "active"),
        ("in-progress", "active"),
        ("Reviewed", "reviewed"),
        ("to be reviewed", "reviewed"),
        ("Closed", "resolved"),
        ("fixed", "resolved"),
        ("Approved", "approved"),
        ("accepted", "approved"),
        ("rejected", "ignored"),
        ("won't fix", "ignored"),
        ("  Resolved  ", "resolved"),  # case + whitespace insensitive
    ],
)
def test_bcf_status_maps_known_values(topic_status: str, expected: str) -> None:
    assert _bcf_status_to_clash_status(topic_status) == expected


def test_bcf_status_unknown_or_empty_returns_none() -> None:
    # Unmapped / empty -> None so the importer leaves the row untouched.
    assert _bcf_status_to_clash_status(None) is None
    assert _bcf_status_to_clash_status("") is None
    assert _bcf_status_to_clash_status("totally unknown state") is None


# ── _signature_from_description (BCF description -> signature) ──────────────


def test_signature_from_description_recovers_pair_signature() -> None:
    desc = "Hard clash · Mechanical ↔ Structural\nA: Duct 12 (GUID-A)\nB: Beam 7 (GUID-B)\nPenetration: 0.12 m"
    sig = _signature_from_description(desc)
    # Must equal the canonical signature for the same stable ids + type.
    assert sig == _signature("GUID-A", "GUID-B", "hard")


def test_signature_from_description_handles_clearance() -> None:
    desc = "Clearance clash\nA: Pipe (P-1)\nB: Wall (W-1)\n"
    assert _signature_from_description(desc) == _signature("P-1", "W-1", "clearance")


def test_signature_from_description_empty_when_unparseable() -> None:
    assert _signature_from_description("") == ""
    assert _signature_from_description("Some unrelated topic body") == ""
    # Header present but element lines missing -> "".
    assert _signature_from_description("Hard clash\n(no A/B lines)") == ""
    # Only one side present -> "".
    assert _signature_from_description("Hard clash\nA: Duct (GUID-A)\n") == ""


# ── _resolved_mttr_hours (resolution latency) ──────────────────────────────


def test_mttr_none_when_no_resolved_rows() -> None:
    rows = [_Row(status="new"), _Row(status="reviewed")]
    assert _resolved_mttr_hours(rows) is None


def test_mttr_averages_creation_to_first_resolved() -> None:
    created = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    resolved_ts = (created + timedelta(hours=4)).isoformat()
    row = _Row(
        created_at=created,
        history=[{"field": "status", "after": "resolved", "ts": resolved_ts}],
    )
    assert _resolved_mttr_hours([row]) == pytest.approx(4.0)


def test_mttr_uses_earliest_resolved_entry() -> None:
    created = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    first = (created + timedelta(hours=2)).isoformat()
    later = (created + timedelta(hours=10)).isoformat()
    row = _Row(
        created_at=created,
        history=[
            {"field": "status", "after": "resolved", "ts": later},
            {"field": "status", "after": "resolved", "ts": first},
        ],
    )
    # Earliest resolved transition (2 h) wins, not the later one.
    assert _resolved_mttr_hours([row]) == pytest.approx(2.0)


def test_mttr_coerces_naive_created_at_to_utc() -> None:
    # A legacy naive created_at must not raise on the tz-aware subtraction.
    created_naive = datetime(2026, 1, 1, 0, 0)  # noqa: DTZ001 - intentional naive row
    resolved_ts = "2026-01-01T03:00:00Z"
    row = _Row(
        created_at=created_naive,
        history=[{"field": "status", "after": "resolved", "ts": resolved_ts}],
    )
    assert _resolved_mttr_hours([row]) == pytest.approx(3.0)


def test_mttr_ignores_non_status_and_bad_timestamps() -> None:
    created = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    rows = [
        _Row(created_at=created, history=[{"field": "severity", "after": "resolved", "ts": "2026-01-01T05:00:00Z"}]),
        _Row(created_at=created, history=[{"field": "status", "after": "resolved", "ts": "not-a-timestamp"}]),
    ]
    assert _resolved_mttr_hours(rows) is None


# ── _compute_kpi (dashboard projection) ────────────────────────────────────


def test_compute_kpi_empty_rows() -> None:
    kpi = _compute_kpi([])
    assert kpi["total"] == 0
    assert kpi["by_status"] == {}
    assert kpi["by_type"] == {}
    # by_severity is always seeded from the four canonical bands.
    assert kpi["by_severity"] == {"critical": 0, "high": 0, "medium": 0, "low": 0}
    assert kpi["top_clashing_pairs"] == []
    assert kpi["mttr_hours"] is None


def test_compute_kpi_aggregates_counts_and_pairs() -> None:
    rows = [
        _Row(a_disc="Mechanical", b_disc="Structural", status="new", severity="high", clash_type="hard"),
        _Row(a_disc="Mechanical", b_disc="Structural", status="reviewed", severity="high", clash_type="hard"),
        _Row(a_disc="Architectural", b_disc="Electrical", status="resolved", severity="low", clash_type="clearance"),
    ]
    kpi = _compute_kpi(rows)
    assert kpi["total"] == 3
    assert kpi["by_status"] == {"new": 1, "reviewed": 1, "resolved": 1}
    assert kpi["by_type"] == {"hard": 2, "clearance": 1}
    assert kpi["by_severity"]["high"] == 2
    assert kpi["by_severity"]["low"] == 1
    # Top pair is the Mechanical/Structural pair (count 2).
    top = kpi["top_clashing_pairs"][0]
    assert (top["a"], top["b"]) == ("Mechanical", "Structural")
    assert top["count"] == 2


def test_compute_kpi_open_share_uses_open_statuses() -> None:
    # "new" and "reviewed" are open; "resolved" is not.
    rows = [
        _Row(a_disc="Mechanical", b_disc="Structural", status="new"),
        _Row(a_disc="Mechanical", b_disc="Structural", status="resolved"),
    ]
    cell = _compute_kpi(rows)["by_discipline_pair"][0]
    assert cell["count"] == 2
    assert cell["open_count"] == 1
    assert cell["open_share"] == pytest.approx(0.5)


def test_compute_kpi_top_pairs_capped_at_five_and_sorted() -> None:
    rows: list[_Row] = []
    # Six distinct pairs with descending counts 6..1 so the order is known.
    disciplines = ["Aaa", "Bbb", "Ccc", "Ddd", "Eee", "Fff"]
    for idx, d in enumerate(disciplines):
        count = 6 - idx
        rows.extend(_Row(a_disc="Zzz", b_disc=d) for _ in range(count))
    top = _compute_kpi(rows)["top_clashing_pairs"]
    assert len(top) == 5  # capped at five
    counts = [p["count"] for p in top]
    assert counts == sorted(counts, reverse=True)  # descending by count
    assert counts[0] == 6
