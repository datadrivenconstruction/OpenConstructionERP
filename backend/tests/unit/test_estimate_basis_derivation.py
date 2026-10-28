# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the basis-of-estimate derivation engine.

The engine (``app.modules.estimate_basis.derivation``) is pure - stdlib only, no
ORM or app imports - so it is loaded here directly from its file path. That keeps
the test independent of the FastAPI dependency graph (which does not import
cleanly on a bare interpreter) while still exercising the real module, and it
runs identically here and in CI.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

_DERIVATION_PATH = Path(__file__).resolve().parents[2] / "app" / "modules" / "estimate_basis" / "derivation.py"
_spec = importlib.util.spec_from_file_location("estimate_basis_derivation", _DERIVATION_PATH)
assert _spec and _spec.loader
derivation = importlib.util.module_from_spec(_spec)
# Register before exec: dataclasses under ``from __future__ import annotations``
# resolve field types via ``sys.modules[cls.__module__]``, which must exist.
sys.modules["estimate_basis_derivation"] = derivation
_spec.loader.exec_module(derivation)

to_decimal = derivation.to_decimal
fmt_decimal = derivation.fmt_decimal
fmt_pct = derivation.fmt_pct
normalize_din276_main_group = derivation.normalize_din276_main_group
normalize_masterformat_group = derivation.normalize_masterformat_group
normalize_nrm_group = derivation.normalize_nrm_group
resolve_trade_group = derivation.resolve_trade_group
derive_trades = derivation.derive_trades
draft_basis = derivation.draft_basis
derive_provenance = derivation.derive_provenance
source_family = derivation.source_family
parse_confidence = derivation.parse_confidence
parse_accuracy_pct = derivation.parse_accuracy_pct
accuracy_range = derivation.accuracy_range
summarise_markups = derivation.summarise_markups
suggest_estimate_class = derivation.suggest_estimate_class


def _pos(
    *,
    din276: str | None = None,
    masterformat: str | None = None,
    nrm: str | None = None,
    classification: dict | None = None,
    description: str = "",
    quantity: str = "1",
    unit_rate: str = "100",
    total: str = "100",
) -> dict:
    if classification is not None:
        cls = classification
    else:
        cls: dict[str, str] = {}
        if din276 is not None:
            cls["din276"] = din276
        if masterformat is not None:
            cls["masterformat"] = masterformat
        if nrm is not None:
            cls["nrm"] = nrm
    return {
        "classification": cls,
        "description": description,
        "quantity": quantity,
        "unit_rate": unit_rate,
        "total": total,
    }


# ── to_decimal: money parsing degrades, never raises ────────────────────────


def test_to_decimal_parses_and_degrades() -> None:
    assert to_decimal("1234.56") == Decimal("1234.56")
    assert to_decimal(10) == Decimal("10")
    assert to_decimal(None) == Decimal("0")
    assert to_decimal("") == Decimal("0")
    assert to_decimal("not-a-number") == Decimal("0")
    assert to_decimal("NaN") == Decimal("0")
    assert to_decimal("Infinity") == Decimal("0")


def test_fmt_decimal_is_two_places_plain() -> None:
    assert fmt_decimal(Decimal("1234.5")) == "1234.50"
    assert fmt_decimal(Decimal("0")) == "0.00"
    # Never scientific notation for a large rollup.
    assert "E" not in fmt_decimal(Decimal("100000000"))


# ── DIN 276 main-group normalisation ────────────────────────────────────────


def test_normalize_din276_main_group() -> None:
    assert normalize_din276_main_group("300") == "300"
    assert normalize_din276_main_group("331") == "300"
    assert normalize_din276_main_group("330.10") == "300"  # dotted CAD form
    assert normalize_din276_main_group("420") == "400"
    assert normalize_din276_main_group("") == ""
    assert normalize_din276_main_group("abc") == ""
    assert normalize_din276_main_group(None) == ""
    assert normalize_din276_main_group("030") == ""  # KG 0xx is not a main group


# ── MasterFormat normalisation ─────────────────────────────────────────────


def test_normalize_masterformat_group() -> None:
    # Standard spaced form.
    assert normalize_masterformat_group("03 30 00") == "300"  # Concrete -> building construction
    assert normalize_masterformat_group("23 00 00") == "400"  # HVAC -> technical systems
    assert normalize_masterformat_group("32 10 00") == "500"  # Exterior Improvements -> external
    assert normalize_masterformat_group("12 00 00") == "600"  # Furnishings -> FFE
    assert normalize_masterformat_group("02 40 00") == "200"  # Site prep
    # Dashed and compact forms.
    assert normalize_masterformat_group("03-30-00") == "300"
    assert normalize_masterformat_group("033000") == "300"
    # Division 01 (General Requirements) has no mapping -> empty.
    assert normalize_masterformat_group("01 00 00") == ""
    # Junk.
    assert normalize_masterformat_group("") == ""
    assert normalize_masterformat_group(None) == ""
    assert normalize_masterformat_group("abc") == ""


# ── NRM normalisation ─────────────────────────────────────────────────────


def test_normalize_nrm_group() -> None:
    assert normalize_nrm_group("2.5") == "300"  # Superstructure -> building construction
    assert normalize_nrm_group("2.5.1") == "300"
    assert normalize_nrm_group("5.8") == "400"  # Services -> technical systems
    assert normalize_nrm_group("8.1") == "500"  # External works
    assert normalize_nrm_group("0.1") == "200"  # Facilitating works -> site prep
    assert normalize_nrm_group("") == ""
    assert normalize_nrm_group(None) == ""


# ── resolve_trade_group (cross-standard) ──────────────────────────────────


def test_resolve_trade_group_prefers_din276_then_masterformat_then_nrm() -> None:
    # DIN 276 present -> use it.
    assert resolve_trade_group({"din276": "330"}) == "300"
    # MasterFormat only.
    assert resolve_trade_group({"masterformat": "03 30 00"}) == "300"
    # NRM only.
    assert resolve_trade_group({"nrm": "2.5"}) == "300"
    # Both present, DIN 276 wins (it is tried first).
    assert resolve_trade_group({"din276": "420", "masterformat": "03 30 00"}) == "400"
    # Empty dict or junk.
    assert resolve_trade_group({}) == ""
    assert resolve_trade_group(None) == ""


# ── derive_trades ────────────────────────────────────────────────────────────


def test_present_trades_from_classification_rollup_and_order() -> None:
    positions = [
        _pos(din276="330", total="500"),
        _pos(din276="331", total="1500"),  # same main group 300
        _pos(din276="420", total="800"),  # group 400
    ]
    coverage = derive_trades(positions)

    present = {p.code: p for p in coverage.present}
    assert set(present) == {"300", "400"}
    assert present["300"].position_count == 2
    assert present["300"].total == Decimal("2000")
    assert present["400"].total == Decimal("800")
    # Richest trade first.
    assert coverage.present[0].code == "300"
    assert coverage.classified_positions == 3
    assert coverage.unclassified_positions == 0


def test_absent_core_trade_becomes_available_for_exclusion() -> None:
    # Only building construction (300) present -> technical systems (400) absent.
    coverage = derive_trades([_pos(din276="330", total="100")])
    absent_codes = {t.code for t in coverage.absent_core}
    assert absent_codes == {"400"}

    # Both core trades present -> nothing expected-but-absent.
    both = derive_trades([_pos(din276="330"), _pos(din276="410")])
    assert both.absent_core == []


def test_masterformat_positions_are_classified() -> None:
    """A US project with MasterFormat codes must show classified positions."""
    positions = [
        _pos(masterformat="03 30 00", total="500"),  # Concrete -> 300
        _pos(masterformat="05 10 00", total="300"),  # Metals -> 300
        _pos(masterformat="23 00 00", total="800"),  # HVAC -> 400
        _pos(masterformat="26 00 00", total="400"),  # Electrical -> 400
    ]
    coverage = derive_trades(positions)

    present = {p.code: p for p in coverage.present}
    assert "300" in present
    assert "400" in present
    assert present["300"].position_count == 2
    assert present["400"].position_count == 2
    assert coverage.classified_positions == 4
    assert coverage.unclassified_positions == 0


def test_nrm_positions_are_classified() -> None:
    """A UK project with NRM codes must show classified positions."""
    positions = [
        _pos(nrm="2.5", total="600"),  # Superstructure -> 300
        _pos(nrm="5.8", total="400"),  # Services -> 400
    ]
    coverage = derive_trades(positions)

    present = {p.code: p for p in coverage.present}
    assert "300" in present
    assert "400" in present
    assert coverage.classified_positions == 2
    assert coverage.unclassified_positions == 0


def test_mixed_standards_all_count_as_classified() -> None:
    """Positions with different standards in the same BOQ all resolve."""
    positions = [
        _pos(din276="330", total="100"),
        _pos(masterformat="23 00 00", total="200"),
        _pos(nrm="2.5", total="300"),
    ]
    coverage = derive_trades(positions)

    assert coverage.classified_positions == 3
    assert coverage.unclassified_positions == 0


def test_keyword_fallback_classifies_unclassified_positions() -> None:
    positions = [
        _pos(description="Reinforced concrete slab to ground floor"),  # -> 300
        _pos(description="Supply and install HVAC ductwork"),  # -> 400
        _pos(description="Miscellaneous sundry line with no trade word"),  # -> none
    ]
    coverage = derive_trades(positions)
    present = {p.code for p in coverage.present}
    assert present == {"300", "400"}
    # None carried a DIN code, so none count as classified.
    assert coverage.classified_positions == 0
    assert coverage.unclassified_positions == 1


def test_quality_flags_are_counted() -> None:
    positions = [
        _pos(din276="330", unit_rate="0", total="0"),  # unpriced
        _pos(din276="330", quantity="0", total="0"),  # missing quantity
        _pos(din276="330", description="Provisional sum for signage"),  # provisional
        _pos(din276="330", description="Fire protection by others"),  # by others / excluded
    ]
    coverage = derive_trades(positions)
    assert coverage.total_positions == 4
    assert coverage.zero_rate_positions == 1
    assert coverage.missing_quantity_positions == 1
    assert coverage.provisional_positions == 1
    assert coverage.by_others_positions == 1


def test_empty_estimate_is_handled() -> None:
    coverage = derive_trades([])
    assert coverage.total_positions == 0
    assert coverage.present == []
    # Both core trades are missing from an empty estimate.
    assert {t.code for t in coverage.absent_core} == {"300", "400"}


# ── draft_basis ──────────────────────────────────────────────────────────────


def test_draft_produces_three_editable_lists() -> None:
    coverage = derive_trades(
        [
            _pos(din276="330", total="1000"),
            _pos(din276="330", unit_rate="0", total="0"),
        ]
    )
    draft = draft_basis(coverage, currency="EUR", base_date="2026-01-01")

    # One inclusion for the present trade.
    inc_codes = {q.trade_code for q in draft.inclusions}
    assert "300" in inc_codes
    assert all(q.category == "inclusion" for q in draft.inclusions)

    # Absent core trade (400) is offered as an exclusion, plus the standard set.
    exc_ids = {q.id for q in draft.exclusions}
    assert "exc-trade-400" in exc_ids
    assert "exc-vat" in exc_ids
    assert all(q.category == "exclusion" for q in draft.exclusions)

    # Flag-driven + context assumptions.
    asm_ids = {q.id for q in draft.assumptions}
    assert "asm-unpriced" in asm_ids  # one line had no rate
    assert "asm-base-date" in asm_ids
    assert "asm-currency" in asm_ids
    assert all(q.category == "assumption" for q in draft.assumptions)


def test_draft_is_deterministic() -> None:
    positions = [_pos(din276="330", total="10"), _pos(din276="410", total="20")]
    a = draft_basis(derive_trades(positions))
    b = draft_basis(derive_trades(positions))
    assert [q.id for q in a.inclusions] == [q.id for q in b.inclusions]
    assert [q.id for q in a.exclusions] == [q.id for q in b.exclusions]
    assert [q.id for q in a.assumptions] == [q.id for q in b.assumptions]


def test_qualification_to_dict_shape() -> None:
    coverage = derive_trades([_pos(din276="330", total="10")])
    item = draft_basis(coverage).inclusions[0]
    data = item.to_dict()
    assert set(data) == {
        "id",
        "category",
        "text",
        "trade_code",
        "trade_label",
        "basis",
        "source",
        "enabled",
    }
    assert data["source"] == "auto"
    assert data["enabled"] is True


def test_no_currency_or_base_date_omits_those_assumptions() -> None:
    coverage = derive_trades([_pos(din276="330", total="10")])
    draft = draft_basis(coverage)
    asm_ids = {q.id for q in draft.assumptions}
    assert "asm-currency" not in asm_ids
    assert "asm-base-date" not in asm_ids
    # Standard assumptions are always present.
    assert "asm-quantities" in asm_ids


# ── Sibling estimating-module assumptions (allowances / prelims / base date) ──


def _by_id(draft: object) -> dict:
    return {q.id: q for q in draft.assumptions}


def test_allowance_assumptions_one_line_each_plus_contingency_note() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    allowances = [
        {
            "id": "a1",
            "label": "Ground works PS",
            "allowance_type": "provisional_sum",
            "held_amount": "50000",
            "currency": "EUR",
        },
        {
            "id": "a2",
            "label": "Design reserve",
            "allowance_type": "contingency",
            "held_amount": "25000",
            "currency": "EUR",
        },
    ]
    draft = draft_basis(coverage, allowances=allowances)
    by_id = _by_id(draft)

    assert by_id["asm-allowance-a1"].text == ("Allowance included: Ground works PS - 50000.00 EUR (provisional sum).")
    assert by_id["asm-allowance-a2"].text == ("Allowance included: Design reserve - 25000.00 EUR (contingency).")
    # A contingency is present -> the note names its amount.
    assert by_id["asm-contingency"].text == ("Contingency of 25000.00 EUR is included in the estimate total.")
    assert by_id["asm-allowance-a1"].basis == "allowance"
    assert all(q.category == "assumption" for q in draft.assumptions)


def test_allowances_without_contingency_note_says_not_included() -> None:
    coverage = derive_trades([_pos(din276="330", total="10")])
    allowances = [
        {
            "id": "a1",
            "label": "Facade PC",
            "allowance_type": "pc_sum",
            "held_amount": "12000",
            "currency": "GBP",
        },
    ]
    draft = draft_basis(coverage, allowances=allowances)
    by_id = _by_id(draft)

    assert by_id["asm-allowance-a1"].text == ("Allowance included: Facade PC - 12000.00 GBP (prime cost sum).")
    assert by_id["asm-contingency"].text == "Contingency is not included in the estimate total."


def test_allowance_blank_label_and_currency_degrade() -> None:
    coverage = derive_trades([_pos(din276="330", total="10")])
    # No id, no label, no currency - the line still reads cleanly.
    allowances = [{"allowance_type": "contingency", "held_amount": "1000"}]
    draft = draft_basis(coverage, allowances=allowances)
    by_id = _by_id(draft)

    assert by_id["asm-allowance-0"].text == ("Allowance included: Contingency - 1000.00 (contingency).")
    assert by_id["asm-contingency"].text == ("Contingency of 1000.00 is included in the estimate total.")


def test_preliminaries_assumption_summarises_rollup() -> None:
    coverage = derive_trades([_pos(din276="330", total="10")])
    prelim = {
        "grand_total": "80000",
        "time_related_total": "60000",
        "fixed_total": "20000",
        "item_count": 4,
        "currency": "EUR",
    }
    draft = draft_basis(coverage, preliminaries=prelim)
    by_id = _by_id(draft)

    assert by_id["asm-preliminaries"].text == (
        "Preliminaries assumed: 80000.00 EUR (4 items, 60000.00 EUR time-related)."
    )
    assert by_id["asm-preliminaries"].basis == "preliminaries"


def test_preliminaries_singular_item_word_and_no_currency() -> None:
    coverage = derive_trades([_pos(din276="330", total="10")])
    prelim = {"grand_total": "5000", "time_related_total": "0", "item_count": 1}
    draft = draft_basis(coverage, preliminaries=prelim)
    by_id = _by_id(draft)

    assert by_id["asm-preliminaries"].text == ("Preliminaries assumed: 5000.00 (1 item, 0.00 time-related).")


def test_pricing_base_date_assumption() -> None:
    coverage = derive_trades([_pos(din276="330", total="10")])
    draft = draft_basis(coverage, pricing_base_date="2026-03-31")
    by_id = _by_id(draft)

    assert by_id["asm-pricing-date"].text == (
        "Prices are current as of 2026-03-31; escalation beyond this date is excluded unless stated."
    )
    assert by_id["asm-pricing-date"].basis == "pricing-date"


def test_sibling_module_assumptions_omitted_when_absent() -> None:
    coverage = derive_trades([_pos(din276="330", total="10")])
    draft = draft_basis(coverage)
    asm_ids = {q.id for q in draft.assumptions}

    assert not any(i.startswith("asm-allowance-") for i in asm_ids)
    assert "asm-contingency" not in asm_ids
    assert "asm-preliminaries" not in asm_ids
    assert "asm-pricing-date" not in asm_ids

    # An empty allowance list and a zero-item prelim summary also draft nothing.
    draft2 = draft_basis(coverage, allowances=[], preliminaries={"item_count": 0})
    ids2 = {q.id for q in draft2.assumptions}
    assert "asm-contingency" not in ids2
    assert "asm-preliminaries" not in ids2


# ── Line provenance: where the estimate's lines came from ───────────────────


def _prov(source: str, count: int, total: str, confidence: str | None = None) -> dict:
    return {"source": source, "confidence": confidence, "position_count": count, "total": total}


def test_source_family_folds_the_fifteen_values_into_four() -> None:
    assert source_family("cad_import") == "measured"
    assert source_family("ai_takeoff") == "measured"
    assert source_family("gaeb_import") == "imported"
    assert source_family("cost_database") == "catalogue"
    assert source_family("manual") == "manual"
    # Case and padding are folded; an unknown value reads as hand-entered, the
    # conservative answer - nothing about it evidences a measurement.
    assert source_family("  CAD_Import ") == "measured"
    assert source_family("something_new") == "manual"
    assert source_family(None) == "manual"
    assert source_family("") == "manual"


def test_parse_confidence_accepts_both_vocabularies() -> None:
    assert parse_confidence("0.85") == Decimal("0.85")
    assert parse_confidence(0.4) == Decimal("0.4")
    # Legacy word-shaped scores map to representative numbers.
    assert parse_confidence("high") == Decimal("0.9")
    assert parse_confidence("MEDIUM") == Decimal("0.6")
    assert parse_confidence("low") == Decimal("0.3")
    # Nothing readable yields None rather than a fabricated score, so an
    # unreadable value is reported as "no confidence" instead of as a good one.
    assert parse_confidence(None) is None
    assert parse_confidence("") is None
    assert parse_confidence("probably fine") is None
    assert parse_confidence("1.4") is None
    assert parse_confidence("-0.2") is None


def test_provenance_shares_are_by_value_and_roll_up_to_families() -> None:
    summary = derive_provenance(
        [
            _prov("cad_import", 40, "6000"),
            _prov("ai_takeoff", 10, "2000", confidence="0.9"),
            _prov("gaeb_import", 20, "1000"),
            _prov("manual", 5, "1000"),
        ]
    )

    assert summary.share_basis == "value"
    assert summary.total_positions == 75
    assert summary.priced_total == Decimal("10000")
    # measured = cad_import + ai_takeoff = 8000 of 10000.
    assert summary.family_share("measured") == Decimal("80.0")
    assert summary.family_share("imported") == Decimal("10.0")
    assert summary.family_share("manual") == Decimal("10.0")
    assert summary.family_positions("measured") == 50
    # Families come back in evidence order, strongest first.
    assert [f.family for f in summary.families] == ["measured", "imported", "manual"]


def test_provenance_falls_back_to_counts_when_the_bill_carries_no_money() -> None:
    summary = derive_provenance([_prov("cad_import", 3, "0"), _prov("manual", 1, "0")])

    # A value share over a zero total would read as "nothing is measured"
    # rather than "there is nothing to measure". The basis is named instead.
    assert summary.share_basis == "count"
    assert summary.family_share("measured") == Decimal("75.0")
    assert summary.family_share("manual") == Decimal("25.0")


def test_provenance_counts_ai_lines_and_low_confidence_separately() -> None:
    summary = derive_provenance(
        [
            _prov("ai_takeoff", 4, "400", confidence="0.95"),
            _prov("ai_takeoff", 3, "300", confidence="0.4"),
            _prov("cad_import_ai", 2, "200", confidence="low"),
            _prov("manual", 1, "100"),
        ]
    )

    assert summary.ai_position_count == 9
    assert summary.ai_total == Decimal("900")
    assert summary.scored_position_count == 9
    # 0.4 and "low" both sit under the 0.7 threshold; 0.95 does not.
    assert summary.low_confidence_count == 5
    assert summary.low_confidence_total == Decimal("500")


def test_provenance_reads_the_model_link_statuses() -> None:
    summary = derive_provenance(
        [_prov("cad_import", 10, "1000")],
        link_counts={"active": 7, "stale": 2, "broken": 1},
    )

    assert summary.model_linked_positions == 10
    assert summary.stale_links == 2
    assert summary.broken_links == 1


def test_empty_provenance_is_handled() -> None:
    summary = derive_provenance([])

    assert summary.total_positions == 0
    assert summary.families == []
    assert summary.buckets == []
    assert summary.share_basis == "value"
    assert summary.family_share("measured") == Decimal("0")
    assert summary.family_positions("measured") == 0


def test_provenance_ignores_groups_with_no_rows() -> None:
    summary = derive_provenance([_prov("cad_import", 0, "999"), _prov("manual", 2, "100")])

    # A zero-count group contributes neither lines nor money.
    assert summary.total_positions == 2
    assert summary.priced_total == Decimal("100")
    assert [b.source for b in summary.buckets] == ["manual"]


# ── Markups: the bill's own answer about tax, escalation and contingency ────


def test_summarise_markups_reads_the_three_flags() -> None:
    picture = summarise_markups(
        [
            {"name": "Overhead", "category": "overhead", "markup_type": "percentage", "percentage": "8"},
            {"name": "VAT", "category": "tax", "markup_type": "percentage", "percentage": "19"},
            {"name": "Risk", "category": "contingency", "markup_type": "percentage", "percentage": "5"},
            {"name": "Indexation", "category": "other", "markup_type": "escalation", "percentage": "2"},
        ]
    )

    assert picture.has_tax is True
    assert picture.has_contingency is True
    assert picture.has_escalation is True
    assert len(picture.lines) == 4


def test_summarise_markups_on_an_empty_bill_claims_nothing() -> None:
    picture = summarise_markups([])

    assert picture.lines == []
    assert picture.has_tax is False
    assert picture.has_contingency is False
    assert picture.has_escalation is False


def test_a_bill_that_prices_tax_does_not_also_exclude_it() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    picture = summarise_markups([{"name": "VAT", "category": "tax", "markup_type": "percentage", "percentage": "19"}])
    draft = draft_basis(coverage, markups=picture)

    exclusion_ids = {q.id for q in draft.exclusions}
    inclusion_ids = {q.id for q in draft.inclusions}
    assert "exc-vat" not in exclusion_ids
    assert "inc-tax" in inclusion_ids
    # The escalation exclusion is untouched - that markup is not on this bill.
    assert "exc-escalation" in exclusion_ids


def test_a_bill_that_prices_escalation_does_not_also_exclude_it() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    picture = summarise_markups(
        [{"name": "Indexation", "category": "other", "markup_type": "escalation", "percentage": "3"}]
    )
    draft = draft_basis(coverage, markups=picture)

    assert "exc-escalation" not in {q.id for q in draft.exclusions}
    assert "inc-escalation" in {q.id for q in draft.inclusions}
    assert "exc-vat" in {q.id for q in draft.exclusions}


def test_markup_contingency_stops_the_register_denying_it() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    picture = summarise_markups(
        [{"name": "Risk", "category": "contingency", "markup_type": "percentage", "percentage": "5"}]
    )
    allowances = [
        {
            "id": "a1",
            "label": "Ground PS",
            "allowance_type": "provisional_sum",
            "held_amount": "500",
            "currency": "EUR",
        }
    ]
    draft = draft_basis(coverage, allowances=allowances, markups=picture)

    # The register holds no contingency, but the bill does: the "not included"
    # note would contradict the inclusion the markup drafts.
    assert "asm-contingency" not in {q.id for q in draft.assumptions}
    assert "inc-contingency-markup" in {q.id for q in draft.inclusions}


def test_a_register_contingency_still_states_its_amount() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    allowances = [
        {
            "id": "c1",
            "label": "Design risk",
            "allowance_type": "contingency",
            "held_amount": "7500",
            "currency": "EUR",
        }
    ]
    draft = draft_basis(coverage, allowances=allowances)

    note = _by_id(draft)["asm-contingency"]
    assert note.text == "Contingency of 7500.00 EUR is included in the estimate total."


def test_markups_are_named_in_an_assumption() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    picture = summarise_markups(
        [
            {"name": "Overhead", "category": "overhead", "markup_type": "percentage", "percentage": "8"},
            {"name": "Bond", "category": "bond", "markup_type": "fixed", "fixed_amount": "12500"},
        ]
    )
    draft = draft_basis(coverage, markups=picture)

    assert _by_id(draft)["asm-markups"].text == "Markups applied to the direct cost: Overhead 8.00%, Bond 12500.00."


# ── Provenance in the drafted prose ─────────────────────────────────────────


def test_provenance_drafts_the_where_it_came_from_assumption() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    provenance = derive_provenance([_prov("cad_import", 8, "800"), _prov("manual", 2, "200")])
    draft = draft_basis(coverage, provenance=provenance)

    assert _by_id(draft)["asm-provenance"].text == (
        "Of the estimate's value: 80.0% measured from a drawing or model, 20.0% entered by hand."
    )


def test_low_confidence_and_stale_links_each_draft_their_own_line() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    provenance = derive_provenance(
        [_prov("ai_takeoff", 3, "300", confidence="0.4"), _prov("manual", 1, "700")],
        link_counts={"active": 5, "stale": 2},
    )
    draft = draft_basis(coverage, provenance=provenance)
    by_id = _by_id(draft)

    assert "3 machine-proposed lines carry a confidence below 0.7" in by_id["asm-low-confidence"].text
    assert "2 model-driven quantities are out of step" in by_id["asm-stale-links"].text


def test_a_clean_estimate_drafts_no_provenance_warnings() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    provenance = derive_provenance([_prov("cad_import", 10, "1000")])
    draft = draft_basis(coverage, provenance=provenance)
    asm_ids = {q.id for q in draft.assumptions}

    assert "asm-provenance" in asm_ids
    assert "asm-low-confidence" not in asm_ids
    assert "asm-stale-links" not in asm_ids


def test_provenance_over_no_lines_drafts_nothing() -> None:
    coverage = derive_trades([_pos(din276="330", total="1000")])
    draft = draft_basis(coverage, provenance=derive_provenance([]))

    assert "asm-provenance" not in {q.id for q in draft.assumptions}


# ── Estimate class: suggested from the evidence, never applied ──────────────


def test_a_well_measured_estimate_keeps_its_completeness_class() -> None:
    provenance = derive_provenance([_prov("cad_import", 90, "9000"), _prov("manual", 10, "1000")])
    suggestion = suggest_estimate_class(1, provenance)

    assert suggestion.suggested_class == 1
    assert suggestion.base_class == 1
    assert "capped_by_measurement" not in {r.code for r in suggestion.reasons}


def test_a_hand_typed_bill_cannot_be_suggested_as_definitive() -> None:
    # 100% filled in, so the completeness rule says class 1 - but not one
    # quantity was taken off anything.
    provenance = derive_provenance([_prov("manual", 200, "20000")])
    suggestion = suggest_estimate_class(1, provenance)

    assert suggestion.suggested_class == 3
    assert suggestion.base_class == 1
    codes = {r.code for r in suggestion.reasons}
    assert "capped_by_measurement" in codes
    assert "measured_share" in codes


def test_a_partly_measured_bill_is_capped_one_step_lower() -> None:
    # 30% of the value measured: firm enough for control, not for definitive.
    provenance = derive_provenance([_prov("cad_import", 30, "3000"), _prov("manual", 70, "7000")])
    suggestion = suggest_estimate_class(1, provenance)

    assert suggestion.suggested_class == 2


def test_poor_measurement_never_tightens_a_class() -> None:
    # The completeness rule already said class 5; good measurement must not
    # talk it up. The cap only ever widens.
    provenance = derive_provenance([_prov("cad_import", 100, "10000")])
    suggestion = suggest_estimate_class(5, provenance)

    assert suggestion.suggested_class == 5


def test_class_reasons_are_enum_keys_not_prose() -> None:
    provenance = derive_provenance(
        [_prov("ai_takeoff", 5, "500", confidence="0.3"), _prov("manual", 5, "500")],
        link_counts={"stale": 1},
    )
    coverage = derive_trades([_pos(din276="330", total="0", unit_rate="0")])
    suggestion = suggest_estimate_class(2, provenance, coverage)

    reasons = {r.code: r.value for r in suggestion.reasons}
    assert reasons["completeness_class"] == "2"
    assert reasons["measured_share"] == "50.0"
    assert reasons["manual_share"] == "50.0"
    assert reasons["low_confidence_lines"] == "5"
    assert reasons["stale_model_links"] == "1"
    assert reasons["unpriced_lines"] == "1"
    # Every value is a plain number - nothing here needs translating.
    for value in reasons.values():
        assert value.replace(".", "").replace("-", "").isdigit()


def test_class_suggestion_clamps_a_nonsense_base() -> None:
    provenance = derive_provenance([_prov("cad_import", 10, "1000")])

    assert suggest_estimate_class(0, provenance).base_class == 1
    assert suggest_estimate_class(9, provenance).base_class == 5


# ── Accuracy band ───────────────────────────────────────────────────────────


def test_parse_accuracy_pct_reads_the_published_forms() -> None:
    assert parse_accuracy_pct("-20%") == Decimal("-20")
    assert parse_accuracy_pct("+30%") == Decimal("30")
    assert parse_accuracy_pct("15") == Decimal("15")
    # Unreadable collapses the bound to zero rather than inventing one.
    assert parse_accuracy_pct("") == Decimal("0")
    assert parse_accuracy_pct(None) == Decimal("0")
    assert parse_accuracy_pct("wide") == Decimal("0")


def test_accuracy_range_applies_the_band_to_the_total() -> None:
    low, high = accuracy_range(Decimal("1000000"), Decimal("-20"), Decimal("30"))

    assert low == Decimal("800000.00")
    assert high == Decimal("1300000.00")


def test_accuracy_range_orders_the_bounds_whichever_way_they_arrive() -> None:
    low, high = accuracy_range(Decimal("1000"), Decimal("30"), Decimal("-20"))

    assert low == Decimal("800.00")
    assert high == Decimal("1300.00")


def test_fmt_pct_is_one_place_plain() -> None:
    assert fmt_pct(Decimal("33.333")) == "33.3"
    assert fmt_pct(Decimal("0")) == "0.0"
    assert fmt_pct(Decimal("-20")) == "-20.0"
