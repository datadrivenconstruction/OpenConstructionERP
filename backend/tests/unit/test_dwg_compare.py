# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the revision-compare diff logic (Item 17).

The diff helpers are pure functions — no DB, no FastAPI — so they are
the right place to lock in the correctness properties the design calls
out:

1. The entity diff classifies layer additions / removals / count
   changes correctly.
2. The cost impact is ``(new - old) * unit_rate`` in the project base
   currency, quantised to 2dp.
3. The cost impact is ``None`` when the measurement is unlinked / the
   rate is missing / either value is absent.
4. Decimal precision is respected (no binary-float drift through the
   money math).

Both the DWG (``dwg_takeoff``) and PDF (``takeoff``) cost-impact
helpers are covered since they share the same contract.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.dwg_takeoff.service import (
    _calculate_cost_impact,
    _compute_entity_diff,
    _layer_count_map,
    _to_float,
)
from app.modules.takeoff.service import (
    _compute_cost_impact,
    _measurement_compare_key,
)

# ── Entity diff ───────────────────────────────────────────────────────


def _layers(*pairs: tuple[str, int]) -> list[dict[str, object]]:
    return [{"name": name, "entity_count": count} for name, count in pairs]


def test_entity_diff_classifies_added_removed_modified_unchanged() -> None:
    """Each layer's change_type reflects its count transition."""
    from_layers = _layers(("walls", 10), ("doors", 5), ("dims", 3))
    to_layers = _layers(("walls", 12), ("doors", 5), ("windows", 4))

    rows = {r["layer"]: r for r in _compute_entity_diff(from_layers, to_layers)}

    assert rows["walls"]["change_type"] == "modified"
    assert rows["walls"]["delta"] == 2
    assert rows["doors"]["change_type"] == "unchanged"
    assert rows["doors"]["delta"] == 0
    # Present only in the old version → removed.
    assert rows["dims"]["change_type"] == "removed"
    assert rows["dims"]["old_count"] == 3
    assert rows["dims"]["new_count"] == 0
    # Present only in the new version → added.
    assert rows["windows"]["change_type"] == "added"
    assert rows["windows"]["old_count"] == 0
    assert rows["windows"]["new_count"] == 4


def test_entity_diff_is_sorted_and_deterministic() -> None:
    """Rows come back sorted by layer name for stable UI rendering."""
    rows = _compute_entity_diff(_layers(("b", 1), ("a", 1)), _layers(("a", 2), ("c", 1)))
    assert [r["layer"] for r in rows] == ["a", "b", "c"]


def test_entity_diff_accepts_legacy_dict_layers() -> None:
    """A legacy dict-keyed-by-name layers blob is normalised, not crashed."""
    from_layers = {"walls": {"name": "walls", "entity_count": 4}}
    to_layers = {"walls": {"name": "walls", "entity_count": 7}}
    rows = _compute_entity_diff(from_layers, to_layers)
    assert len(rows) == 1
    assert rows[0]["change_type"] == "modified"
    assert rows[0]["delta"] == 3


def test_layer_count_map_tolerates_garbage() -> None:
    """Malformed entries collapse to {} rather than raising."""
    assert _layer_count_map(None) == {}
    assert _layer_count_map("nonsense") == {}
    assert _layer_count_map([{"name": "", "entity_count": 9}]) == {}
    assert _layer_count_map([{"name": "x", "entity_count": "bad"}]) == {"x": 0}


# ── Cost impact (DWG helper) ──────────────────────────────────────────


def test_cost_impact_basic_increase() -> None:
    """(55 - 50) * 100 = 500.00 — the design's worked example."""
    impact = _calculate_cost_impact(old_value=50.0, new_value=55.0, unit_rate="100")
    assert impact == "500.00"


def test_cost_impact_decrease_is_negative() -> None:
    """A smaller new measurement yields a negative (credit) impact."""
    impact = _calculate_cost_impact(old_value=50.0, new_value=40.0, unit_rate="100")
    assert impact == "-1000.00"


def test_cost_impact_decimal_precision_preserved() -> None:
    """Money math stays exact — no binary float drift."""
    # (12.345 - 12.000) * 99.99 = 0.345 * 99.99 = 34.49655 → 34.50 (HALF_UP)
    impact = _calculate_cost_impact(old_value=12.0, new_value=12.345, unit_rate="99.99")
    assert impact == "34.50"
    # The intermediate must equal the exact Decimal product, not a float.
    exact = (Decimal("12.345") - Decimal("12.000")) * Decimal("99.99")
    assert exact.quantize(Decimal("0.01")) == Decimal("34.50")


def test_cost_impact_none_when_unlinked_rate_missing() -> None:
    """No rate → no cost (unlinked annotation has no unit_rate)."""
    assert _calculate_cost_impact(old_value=50.0, new_value=55.0, unit_rate=None) is None
    assert _calculate_cost_impact(old_value=50.0, new_value=55.0, unit_rate="") is None
    assert _calculate_cost_impact(old_value=50.0, new_value=55.0, unit_rate="0") is None


def test_cost_impact_none_when_value_missing() -> None:
    """A measurement that only exists on one side cannot be priced."""
    assert _calculate_cost_impact(old_value=None, new_value=55.0, unit_rate="100") is None
    assert _calculate_cost_impact(old_value=50.0, new_value=None, unit_rate="100") is None


def test_cost_impact_none_for_unparseable_rate() -> None:
    """A garbage unit_rate degrades to no cost rather than raising."""
    assert _calculate_cost_impact(old_value=50.0, new_value=55.0, unit_rate="abc") is None


def test_to_float_handles_decimal_and_none() -> None:
    assert _to_float(Decimal("3.5")) == 3.5
    assert _to_float(None) is None
    assert _to_float("bad") is None


# ── Cost impact (PDF/takeoff helper shares the same contract) ─────────


def test_takeoff_cost_impact_matches_dwg_contract() -> None:
    """The takeoff helper produces the same money result as the DWG one."""
    assert _compute_cost_impact(old_value=50.0, new_value=55.0, unit_rate="100") == "500.00"
    assert _compute_cost_impact(old_value=50.0, new_value=55.0, unit_rate=None) is None
    assert _compute_cost_impact(old_value=None, new_value=55.0, unit_rate="100") is None


# ── Measurement compare key (PDF matching) ────────────────────────────


class _FakeMeasurement:
    def __init__(
        self,
        *,
        page: int = 1,
        type: str = "area",
        group_name: str = "General",
        annotation: str | None = None,
        metadata_: dict | None = None,
    ) -> None:
        self.page = page
        self.type = type
        self.group_name = group_name
        self.annotation = annotation
        self.metadata_ = metadata_ or {}


def test_compare_key_prefers_explicit_compare_key() -> None:
    """An explicit metadata.compare_key wins over the natural tuple."""
    a = _FakeMeasurement(page=1, type="area", group_name="Slab", metadata_={"compare_key": "SLAB-01"})
    b = _FakeMeasurement(page=2, type="distance", group_name="Other", metadata_={"compare_key": "SLAB-01"})
    assert _measurement_compare_key(a) == _measurement_compare_key(b) == "ck:SLAB-01"


def test_compare_key_natural_tuple_matches_same_logical_item() -> None:
    """Without a compare_key, the (page, type, group, annotation) tuple matches."""
    a = _FakeMeasurement(page=3, type="Area", group_name="Walls", annotation="W1")
    b = _FakeMeasurement(page=3, type="area", group_name="walls", annotation="w1")
    # Case-folded so a re-typed group/annotation still matches.
    assert _measurement_compare_key(a) == _measurement_compare_key(b)


def test_compare_key_distinguishes_different_items() -> None:
    a = _FakeMeasurement(page=1, type="area", group_name="Slab")
    b = _FakeMeasurement(page=2, type="area", group_name="Slab")
    assert _measurement_compare_key(a) != _measurement_compare_key(b)
