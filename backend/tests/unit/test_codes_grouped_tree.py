# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure grouped band-tree builder (T2.3, acceptance #5)."""

from __future__ import annotations

from decimal import Decimal

from app.modules.schedule.codes_bandtree import build_band_tree, group_key


def test_single_level_counts_sum_to_total() -> None:
    rows = [(("A1",), 3), (("A2",), 2), ((None,), 1)]
    bands, total = build_band_tree(rows, 1)
    assert total == 6
    assert sum(b["count"] for b in bands) == total
    by_key = {b["key"]: b for b in bands}
    assert by_key["A1"]["count"] == 3
    assert by_key["A2"]["count"] == 2
    # Unassigned activities fall into a (none) band.
    assert by_key["__none__"]["label"] == "(none)"
    assert by_key["__none__"]["count"] == 1


def test_none_band_sorts_last() -> None:
    rows = [((None,), 1), (("A2",), 1), (("A1",), 1)]
    bands, _ = build_band_tree(rows, 1)
    assert [b["key"] for b in bands] == ["A1", "A2", "__none__"]


def test_two_level_tree_is_preordered_with_subtotals() -> None:
    rows = [
        (("A1", "S1"), 2),
        (("A1", "S2"), 1),
        (("A1", None), 1),
        ((None, "S1"), 1),
    ]
    bands, total = build_band_tree(rows, 2)
    assert total == 5
    # Top-level bands carry the subtotal of their whole subtree.
    top = [b for b in bands if b["depth"] == 0]
    top_by_key = {b["key"]: b for b in top}
    assert top_by_key["A1"]["count"] == 4
    assert top_by_key["__none__"]["count"] == 1
    # Leaf counts under every band still sum to the grand total.
    leaves = [b for b in bands if b["depth"] == 1]
    assert sum(b["count"] for b in leaves) == total
    # Pre-order: a parent immediately precedes its own children.
    order = [(b["depth"], b["key"]) for b in bands]
    assert order[0] == (0, "A1")
    assert (1, "S1") in order
    assert order[-1] == (1, "S1")  # (none) > S1 is the final leaf


def test_meta_resolves_label_and_color() -> None:
    rows = [(("v1",), 4)]
    meta = {(0, "v1"): {"label": "A1 North wing", "color": "#ff0000"}}
    bands, _ = build_band_tree(rows, 1, meta)
    assert bands[0]["label"] == "A1 North wing"
    assert bands[0]["color"] == "#ff0000"
    assert bands[0]["path"] == ["v1"]


def test_empty_rows() -> None:
    bands, total = build_band_tree([], 1)
    assert bands == []
    assert total == 0


# ── group_key: the shared PHASE 1 / PHASE 2 band-key stringifier (UDF grouping) ──


def test_group_key_none_stays_none() -> None:
    # An unassigned value must stay None so it lands in the (none) band.
    assert group_key(None) is None


def test_group_key_text_passthrough() -> None:
    assert group_key("North wing") == "North wing"
    # An empty-but-present value keeps its own (empty) key, it is not (none).
    assert group_key("") == ""


def test_group_key_decimal_drops_storage_padding() -> None:
    # Numeric(18,4) reads back padded; the band key must not carry that padding,
    # and must never expose the Decimal(..) repr.
    assert group_key(Decimal("5.0000")) == "5"
    assert group_key(Decimal("5.5000")) == "5.5"
    assert group_key(Decimal("0.0000")) == "0"
    assert group_key(Decimal("12.3400")) == "12.34"
    assert "Decimal" not in group_key(Decimal("5"))


def test_group_key_decimal_keeps_significant_fraction() -> None:
    assert group_key(Decimal("0.2500")) == "0.25"
    assert group_key(Decimal("100")) == "100"


def test_udf_number_band_falls_back_to_raw_value_label() -> None:
    # A UDF level supplies no meta, so the band label falls back to the raw
    # value-string key. Mirrors how a number UDF appears in the grouped grid.
    keys = [group_key(Decimal("5.0000"))]
    rows = [((keys[0],), 4), ((None,), 1)]
    bands, total = build_band_tree(rows, 1)
    assert total == 5
    by_key = {b["key"]: b for b in bands}
    assert by_key["5"]["label"] == "5"
    assert by_key["5"]["count"] == 4
    assert by_key["__none__"]["label"] == "(none)"
