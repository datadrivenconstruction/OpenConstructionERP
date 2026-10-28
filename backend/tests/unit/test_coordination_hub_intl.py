# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the Coordination Hub international helpers.

These pin the pure functions in
:mod:`app.modules.coordination_hub.intl`: multilingual discipline
normalisation, plain-language explainers, empty-safe counting aggregates,
the zero-guarded resolution rate, and currency-safe Decimal money
aggregation. No session, no I/O, no fixtures.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.coordination_hub.intl import (
    CANONICAL_TRADES,
    counts_by_discipline,
    counts_by_status,
    describe_trade,
    discipline_pair_counts,
    explain_clash_status,
    explain_exposure,
    explain_matrix_cell,
    explain_resolution_rate,
    is_open_status,
    is_resolved_status,
    normalise_trade,
    resolution_rate,
    status_label,
    sum_amounts,
    sum_by_currency,
    total_in_currency,
)

# ── Multilingual discipline normalisation ───────────────────────────────────


def test_normalise_trade_english_aliases() -> None:
    assert normalise_trade("Architectural") == "arch"
    assert normalise_trade("STRUCTURAL") == "struct"
    assert normalise_trade("hvac") == "mep"
    assert normalise_trade("electrical") == "mep"
    assert normalise_trade("plumbing") == "mep"
    assert normalise_trade("landscape") == "landscape"
    assert normalise_trade("site") == "civil"


def test_normalise_trade_german_labels_resolve() -> None:
    assert normalise_trade("Tragwerk") == "struct"
    assert normalise_trade("Statik") == "struct"
    assert normalise_trade("Architektur") == "arch"
    assert normalise_trade("Elektro") == "mep"
    assert normalise_trade("Sanitär") == "mep"
    assert normalise_trade("Lüftung") == "mep"
    assert normalise_trade("Tiefbau") == "civil"
    assert normalise_trade("Freianlagen") == "landscape"


def test_normalise_trade_french_labels_resolve() -> None:
    assert normalise_trade("Structure") == "struct"
    assert normalise_trade("Électricité") == "mep"
    assert normalise_trade("Plomberie") == "mep"
    assert normalise_trade("CVC") == "mep"
    assert normalise_trade("Génie civil") == "civil"
    assert normalise_trade("Paysage") == "landscape"


def test_normalise_trade_spanish_labels_resolve() -> None:
    assert normalise_trade("Arquitectura") == "arch"
    assert normalise_trade("Estructura") == "struct"
    assert normalise_trade("Electricidad") == "mep"
    assert normalise_trade("Fontanería") == "mep"
    assert normalise_trade("Climatización") == "mep"
    assert normalise_trade("Obra civil") == "civil"


def test_normalise_trade_italian_labels_resolve() -> None:
    assert normalise_trade("Architettura") == "arch"
    assert normalise_trade("Struttura") == "struct"
    assert normalise_trade("Impianti") == "mep"
    assert normalise_trade("Idraulica") == "mep"
    assert normalise_trade("Genio civile") == "civil"
    assert normalise_trade("Paesaggio") == "landscape"


def test_normalise_trade_russian_labels_resolve() -> None:
    assert normalise_trade("Конструкции") == "struct"
    assert normalise_trade("Архитектура") == "arch"
    assert normalise_trade("Электрика") == "mep"
    assert normalise_trade("Сантехника") == "mep"
    assert normalise_trade("Вентиляция") == "mep"


def test_normalise_trade_accent_and_case_folding() -> None:
    # Accent-stripped and case-folded variants hit the same key.
    assert normalise_trade("sanitaer") == normalise_trade("Sanitär") == "mep"
    assert normalise_trade("electricite") == normalise_trade("Électricité") == "mep"
    assert normalise_trade("  genie  civil  ") == "civil"


def test_normalise_trade_unknown_and_empty_go_to_other() -> None:
    assert normalise_trade(None) == "other"
    assert normalise_trade("") == "other"
    assert normalise_trade("   ") == "other"
    assert normalise_trade("Zonktastic") == "other"


def test_normalise_trade_always_returns_canonical() -> None:
    for label in ["arch", "Tragwerk", "CVC", "Idraulica", "Дороги", "nonsense", None]:
        assert normalise_trade(label) in CANONICAL_TRADES


def test_describe_trade_is_plain_language() -> None:
    text = describe_trade("Tragwerk")
    assert "Structure" in text
    # Unknown falls back to the "other" description, never empty.
    assert describe_trade("nonsense") == describe_trade("other")
    assert describe_trade(None)


# ── Status vocabulary ───────────────────────────────────────────────────────


def test_status_label_known_and_unknown() -> None:
    assert status_label("new") == "New, not yet reviewed"
    assert status_label("resolved") == "Resolved"
    assert status_label("REVIEWED") == "Reviewed, awaiting resolution"
    assert status_label("nope") == "Unknown status"
    assert status_label(None) == "Unknown status"


def test_open_and_resolved_status_predicates() -> None:
    assert is_open_status("new")
    assert is_open_status("active")
    assert is_open_status("reviewed")
    assert not is_open_status("resolved")
    assert not is_open_status(None)
    assert is_resolved_status("approved")
    assert is_resolved_status("resolved")
    assert not is_resolved_status("new")


def test_explain_clash_status_buckets() -> None:
    assert "OPEN" in explain_clash_status("new")
    assert "RESOLVED" in explain_clash_status("resolved")
    assert "IGNORED" in explain_clash_status("ignored")
    assert "Unknown" in explain_clash_status("weird")


# ── Counting aggregates ─────────────────────────────────────────────────────


def test_counts_by_status_empty_safe() -> None:
    assert counts_by_status([]) == {}


def test_counts_by_status_folds_unknown() -> None:
    result = counts_by_status(["new", "New", "resolved", None, "  "])
    assert result["new"] == 2
    assert result["resolved"] == 1
    assert result["unknown"] == 2
    # Total preserved: nothing dropped.
    assert sum(result.values()) == 5


def test_counts_by_discipline_normalises_multilingual() -> None:
    labels = ["Tragwerk", "Structural", "Architektur", "hvac", "Idraulica", "nonsense"]
    result = counts_by_discipline(labels)
    assert result["struct"] == 2  # Tragwerk + Structural
    assert result["arch"] == 1
    assert result["mep"] == 2  # hvac + Idraulica
    assert result["other"] == 1
    assert sum(result.values()) == len(labels)


def test_counts_by_discipline_empty() -> None:
    assert counts_by_discipline([]) == {}


def test_discipline_pair_counts_symmetric() -> None:
    pairs = [
        ("Architectural", "Structural"),
        ("Structural", "Architectural"),  # same pair, reversed
        ("Mechanical", "Structural"),
        ("Electrical", "Structural"),  # folds to (mep, struct), same as above
    ]
    result = discipline_pair_counts(pairs)
    assert result[("arch", "struct")] == 2
    assert result[("mep", "struct")] == 2
    assert sum(result.values()) == len(pairs)


def test_discipline_pair_counts_same_discipline_kept() -> None:
    result = discipline_pair_counts([("arch", "arch")])
    assert result[("arch", "arch")] == 1


def test_discipline_pair_counts_empty() -> None:
    assert discipline_pair_counts([]) == {}


def test_explain_matrix_cell_language() -> None:
    assert "between arch and struct" in explain_matrix_cell("Architectural", "Tragwerk", 3)
    assert "1 clash" in explain_matrix_cell("arch", "struct", 1)
    assert "within arch" in explain_matrix_cell("arch", "arch", 2)


def test_explain_matrix_cell_rejects_negative() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        explain_matrix_cell("arch", "struct", -1)


# ── Resolution rate (zero-guarded) ──────────────────────────────────────────


def test_resolution_rate_basic() -> None:
    assert resolution_rate(0, 10) == 1.0
    assert resolution_rate(10, 0) == 0.0
    assert resolution_rate(1, 3) == 0.75


def test_resolution_rate_zero_guard() -> None:
    # No clashes at all: clean 0.0, never a ZeroDivisionError or NaN.
    assert resolution_rate(0, 0) == 0.0


def test_resolution_rate_rejects_negative() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        resolution_rate(-1, 5)
    with pytest.raises(ValueError, match="zero or positive"):
        resolution_rate(5, -1)


def test_resolution_rate_bounded() -> None:
    for open_c, res_c in [(3, 7), (100, 0), (0, 1), (5, 5)]:
        rate = resolution_rate(open_c, res_c)
        assert 0.0 <= rate <= 1.0


def test_explain_resolution_rate_language() -> None:
    assert "no resolution rate" in explain_resolution_rate(0, 0)
    text = explain_resolution_rate(1, 3)
    assert "75%" in text
    assert "3 resolved" in text
    assert "1 still open" in text


# ── Money aggregation (Decimal-exact, currency-safe) ────────────────────────


def test_sum_amounts_exact_decimal() -> None:
    # Classic float-drift case: 0.1 + 0.2 must be exactly 0.3.
    assert sum_amounts(["0.1", "0.2"]) == Decimal("0.3")
    assert sum_amounts([Decimal("1000.55"), Decimal("2000.45")]) == Decimal("3001.00")


def test_sum_amounts_empty_is_zero() -> None:
    assert sum_amounts([]) == Decimal("0")


def test_sum_amounts_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        sum_amounts(["NaN"])
    with pytest.raises(ValueError):
        sum_amounts(["Infinity"])
    with pytest.raises(ValueError):
        sum_amounts(["not-money"])


def test_sum_by_currency_never_mixes() -> None:
    items = [
        ("10", "EUR"),
        ("5", "eur"),  # case-insensitive same bucket
        ("10", "USD"),
        ("3", None),  # unknown currency, own bucket
    ]
    result = sum_by_currency(items)
    assert result["EUR"] == Decimal("15")
    assert result["USD"] == Decimal("10")
    assert result[""] == Decimal("3")
    # The two real currencies are never blended.
    assert "EUR" in result and "USD" in result


def test_sum_by_currency_empty() -> None:
    assert sum_by_currency([]) == {}


def test_total_in_currency_selects_one_code() -> None:
    items = [("10", "EUR"), ("20", "USD"), ("5", "eur")]
    assert total_in_currency(items, currency="EUR") == Decimal("15")
    assert total_in_currency(items, currency="usd") == Decimal("20")
    # A currency with no rows totals to a clean zero.
    assert total_in_currency(items, currency="GBP") == Decimal("0")


def test_total_in_currency_rejects_empty_code() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        total_in_currency([("10", "EUR")], currency="")


def test_explain_exposure_names_currency() -> None:
    text = explain_exposure(Decimal("1234.50"), "EUR")
    assert "1234.50" in text
    assert "EUR" in text
    # No currency set is stated, not silently dropped.
    assert "(no currency set)" in explain_exposure("100", None)
