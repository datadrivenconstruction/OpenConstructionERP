# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Edge-case unit tests for the grouped band-tree stringifier + builder.

Pure-Python, no DB. Complements ``test_codes_grouped_tree.py`` by pinning the
corners of ``codes_bandtree.group_key`` and ``build_band_tree``:

* group_key: negative Decimals, exponent-form Decimals, very small fractions,
  negative zero, non-Decimal numerics (int / float / bool), and the guarantee
  that a Decimal repr never leaks into a band key,
* build_band_tree: band ordering is by display LABEL (case-insensitive) not raw
  key, ragged ``level_keys`` shorter than ``n_levels`` fall into ``(none)``
  sub-bands, duplicate combinations accumulate counts, deep (3-level) nesting
  stays pre-ordered with correct subtotals, partial meta (color-only) falls back
  to the key for the label, and band counts always sum to the leaf total.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.schedule.codes_bandtree import NONE_KEY, build_band_tree, group_key

# -- group_key: Decimal corners ------------------------------------------------


def test_group_key_negative_decimal_drops_padding() -> None:
    """A negative numeric UDF value keeps its sign and loses storage padding."""
    assert group_key(Decimal("-5.5000")) == "-5.5"
    assert group_key(Decimal("-5.0000")) == "-5"
    assert group_key(Decimal("-12.3400")) == "-12.34"


def test_group_key_exponent_form_decimal_is_plain() -> None:
    """Exponent-notation Decimals render as plain numbers, never as ``1E+2``."""
    assert group_key(Decimal("1E+2")) == "100"
    assert group_key(Decimal("0E-4")) == "0"
    assert "E" not in group_key(Decimal("1E+2"))


def test_group_key_very_small_fraction_preserved() -> None:
    """A small but significant fraction is not rounded away."""
    assert group_key(Decimal("0.0001")) == "0.0001"
    assert group_key(Decimal("0.2500")) == "0.25"


def test_group_key_negative_zero_is_documented() -> None:
    """Decimal negative zero stringifies to ``-0`` (documents actual behaviour).

    ``format(Decimal('-0.0000'), 'f')`` is ``'-0.0000'``; after stripping the
    fractional padding the key is ``'-0'``. This pins the current contract so a
    future change to normalise it to ``'0'`` is a conscious, tested decision.
    """
    assert group_key(Decimal("-0.0000")) == "-0"


def test_group_key_never_leaks_decimal_repr() -> None:
    """No band key ever contains the ``Decimal(..)`` repr."""
    for value in (Decimal("5"), Decimal("5.0000"), Decimal("-3.2"), Decimal("1E+2")):
        assert "Decimal" not in group_key(value)


def test_group_key_large_integer_decimal() -> None:
    """A large whole-number Decimal keeps every significant digit, no padding."""
    assert group_key(Decimal("1000000.0000")) == "1000000"


# -- group_key: non-Decimal numerics and other types ---------------------------


def test_group_key_plain_int_uses_str() -> None:
    """A plain int is not Decimal, so it goes through ``str`` unchanged."""
    assert group_key(5) == "5"
    assert group_key(-3) == "-3"
    assert group_key(0) == "0"


def test_group_key_float_uses_str() -> None:
    """A float is stringified by ``str`` (Decimal padding logic does not apply)."""
    assert group_key(5.5) == "5.5"


def test_group_key_bool_is_stringified() -> None:
    """A bool is not a Decimal; it stringifies to ``True`` / ``False``.

    Pins the actual behaviour: booleans are an unusual but possible group value
    and must not crash or be mistaken for an integer band.
    """
    assert group_key(True) == "True"
    assert group_key(False) == "False"


def test_group_key_empty_string_is_present_not_none() -> None:
    """An empty string is a present value (its own band), distinct from None."""
    assert group_key("") == ""
    assert group_key("") is not None


def test_group_key_none_is_none() -> None:
    """None stays None so it lands in the (none) band, never the string 'None'."""
    assert group_key(None) is None


# -- build_band_tree: ordering by display label --------------------------------


def test_bands_ordered_by_label_not_raw_key() -> None:
    """Sibling bands sort by their (case-insensitive) display label, not the key.

    The keys are A / b / c but the labels reorder them apple / b / zebra, so the
    emitted order follows the labels. This is what makes the grid read
    alphabetically by what the user actually sees.
    """
    rows = [(("b",), 1), (("A",), 1), (("c",), 1)]
    meta = {(0, "A"): {"label": "zebra"}, (0, "c"): {"label": "apple"}}
    bands, _ = build_band_tree(rows, 1, meta)
    assert [(b["key"], b["label"]) for b in bands] == [
        ("c", "apple"),
        ("b", "b"),
        ("A", "zebra"),
    ]


def test_label_sort_is_case_insensitive() -> None:
    """Mixed-case labels sort together regardless of case."""
    rows = [(("x",), 1), (("y",), 1)]
    meta = {(0, "x"): {"label": "Beta"}, (0, "y"): {"label": "alpha"}}
    bands, _ = build_band_tree(rows, 1, meta)
    assert [b["label"] for b in bands] == ["alpha", "Beta"]


def test_none_band_always_sorts_last_even_with_labels() -> None:
    """The (none) band is forced last no matter how the labels would sort it."""
    rows = [((None,), 1), (("a",), 1)]
    meta = {(0, "a"): {"label": "zzz"}}  # would sort after (none) alphabetically
    bands, _ = build_band_tree(rows, 1, meta)
    assert [b["key"] for b in bands] == ["a", NONE_KEY]


# -- build_band_tree: ragged level keys ----------------------------------------


def test_ragged_level_keys_fall_into_none_subband() -> None:
    """A row with fewer keys than levels gets a (none) band at the missing depth."""
    rows = [(("A1",), 5)]  # one key, but two levels requested
    bands, total = build_band_tree(rows, 2)
    assert total == 5
    assert [(b["depth"], b["key"], b["count"]) for b in bands] == [
        (0, "A1", 5),
        (1, NONE_KEY, 5),
    ]


def test_ragged_and_full_rows_mix() -> None:
    """Full and ragged rows under the same top band combine correctly."""
    rows = [(("A", "S1"), 2), (("A",), 1)]  # second row is missing its level-2 key
    bands, total = build_band_tree(rows, 2)
    assert total == 3
    top = next(b for b in bands if b["depth"] == 0)
    assert top["count"] == 3
    leaves = {b["key"]: b["count"] for b in bands if b["depth"] == 1}
    assert leaves == {"S1": 2, NONE_KEY: 1}


# -- build_band_tree: counts and deep nesting ----------------------------------


def test_duplicate_combinations_accumulate() -> None:
    """Two rows with the same key path sum into a single band."""
    rows = [(("A",), 2), (("A",), 3)]
    bands, total = build_band_tree(rows, 1)
    assert total == 5
    assert len(bands) == 1
    assert bands[0]["key"] == "A" and bands[0]["count"] == 5


def test_three_level_nesting_preordered_with_subtotals() -> None:
    """A 3-level tree stays depth-first with each band carrying its subtotal."""
    rows = [
        (("A", "x", "1"), 2),
        (("A", "x", "2"), 3),
        (("A", "y", "1"), 1),
    ]
    bands, total = build_band_tree(rows, 3)
    assert total == 6
    seq = [(b["depth"], b["key"], b["count"]) for b in bands]
    assert seq == [
        (0, "A", 6),
        (1, "x", 5),
        (2, "1", 2),
        (2, "2", 3),
        (1, "y", 1),
        (2, "1", 1),
    ]
    # Paths reflect full ancestry.
    deep = next(b for b in bands if b["depth"] == 2 and b["key"] == "2")
    assert deep["path"] == ["A", "x", "2"]
    # Leaf counts sum to the grand total.
    assert sum(b["count"] for b in bands if b["depth"] == 2) == total


def test_partial_meta_color_only_falls_back_to_key_label() -> None:
    """A meta entry with only a color leaves the label as the raw key."""
    rows = [(("v",), 1)]
    bands, _ = build_band_tree(rows, 1, {(0, "v"): {"color": "#abcdef"}})
    assert bands[0]["label"] == "v"
    assert bands[0]["color"] == "#abcdef"


def test_meta_for_wrong_depth_is_ignored() -> None:
    """Meta keyed at the wrong depth does not apply; the key is the label."""
    rows = [(("A", "B"), 1)]
    # Meta is keyed at depth 1 for "A", but "A" lives at depth 0 -> ignored.
    meta = {(1, "A"): {"label": "wrong"}}
    bands, _ = build_band_tree(rows, 2, meta)
    top = next(b for b in bands if b["depth"] == 0)
    assert top["label"] == "A"  # fell back to the key, not "wrong"


def test_band_counts_always_sum_to_total() -> None:
    """Across an arbitrary tree, the leaf-depth band counts equal the total."""
    rows = [
        (("P", "a"), 4),
        (("P", "b"), 2),
        (("P", None), 1),
        ((None, "a"), 3),
        ((None, None), 5),
    ]
    bands, total = build_band_tree(rows, 2)
    assert total == 15
    leaf_sum = sum(b["count"] for b in bands if b["depth"] == 1)
    assert leaf_sum == total
    # Each top band's count equals the sum of its own children.
    for top in (b for b in bands if b["depth"] == 0):
        children = [b for b in bands if b["depth"] == 1 and b["path"][0] == top["key"]]
        assert top["count"] == sum(c["count"] for c in children)
