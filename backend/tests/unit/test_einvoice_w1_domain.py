# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""w1-einvoice: edge cases and DOMAIN rules around the worked examples (pure, no database).

Covers deadline boundaries, needs_review rules staying off by default, the
state machine (no illegal jumps), consolidation rounding and size, EN 16931
totals with Decimal in several currencies, the inbound parser on hostile
amounts, and the "no float for money" guard on the new modules.
"""

from __future__ import annotations

import ast
import itertools
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.einvoice import rules
from app.modules.einvoice.cii import EInvoice, EInvoiceLine, Party, TaxSubtotal
from app.modules.einvoice.inbound import InboundParseError, parse_inbound
from app.modules.einvoice_clearance import consolidation, lifecycle, regimes
from app.modules.einvoice_clearance.consolidation import Receipt
from app.modules.einvoice_clearance.models import (
    ALLOWED_TRANSITIONS,
    DOCUMENT_STATUSES,
    can_be_sent,
    can_transition,
)

_APP = Path(__file__).resolve().parents[2] / "app"


def _regime(code: str) -> dict:
    return regimes.regime_as_dict(regimes.COUNTRY_REGIMES[code])


def _ids(findings: list[lifecycle.Finding]) -> list[str]:
    return [f.rule_id for f in findings]


# ── Deadlines: boundaries ───────────────────────────────────────────────────

_IN_DOC = {"invoice_number": "INV-24-0871", "invoice_date": "2025-05-02", "status": "validated"}


def _in(turnover: str | None, now: datetime, doc: dict | None = None) -> list[str]:
    settings = {} if turnover is None else {"annual_turnover": turnover}
    profile = {"mode": "sandbox", "settings": settings}
    return _ids(lifecycle.evaluate(_regime("IN"), doc or _IN_DOC, profile=profile, now=now))


class TestIndiaThresholdAndDefaults:
    def test_rule_is_off_when_turnover_is_not_configured(self) -> None:
        """needs_review rule: a tenant that has not set its turnover is never blocked by it."""
        assert _in(None, datetime(2025, 9, 1, tzinfo=UTC)) == []

    @pytest.mark.parametrize("bad", ["", "abc", "-5", "0"])
    def test_unusable_turnover_does_not_apply_the_rule(self, bad: str) -> None:
        assert _in(bad, datetime(2025, 9, 1, tzinfo=UTC)) == []

    def test_nan_turnover_does_not_apply_the_rule(self) -> None:
        assert _in("NaN", datetime(2025, 9, 1, tzinfo=UTC)) == []

    def test_threshold_is_inclusive_at_ten_crore(self) -> None:
        late = datetime(2025, 6, 3, tzinfo=UTC)
        assert _in("100000000", late) == ["EINV-IN-001"]
        assert _in("99999999.99", late) == []

    def test_invoice_before_the_effective_date_is_not_bound(self) -> None:
        doc = {**_IN_DOC, "invoice_date": "2025-03-01"}
        assert _in("520000000", datetime(2025, 9, 1, tzinfo=UTC), doc) == []

    def test_exactly_30_days_after_midnight_is_still_open(self) -> None:
        assert _in("520000000", datetime(2025, 6, 1, 0, 0, tzinfo=UTC)) == []

    def test_the_in_rules_carry_needs_review_and_a_source(self) -> None:
        lc = regimes.COUNTRY_REGIMES["IN"].lifecycle
        assert lc["deadlines"][0]["needs_review"] is True
        assert lc["cancel"]["needs_review"] is True
        assert lc["deadlines"][0]["source_url"].startswith("https://")

    def test_a_submitted_invoice_no_longer_raises_the_age_error(self) -> None:
        doc = {**_IN_DOC, "status": "submitted"}
        assert _in("520000000", datetime(2025, 9, 1, tzinfo=UTC), doc) == []

    def test_day_30_is_reportable_all_day(self) -> None:
        assert _in("520000000", datetime(2025, 6, 1, 12, 0, tzinfo=UTC)) == []


class TestSaudiBoundaries:
    simplified = {
        "invoice_number": "SIM-9",
        "invoice_date": "2026-03-10T09:00:00",
        "status": "validated",
        "document_kind": "simplified",
        "previous_hash": "h",
    }

    def _state(self, now: datetime) -> str:
        deadline = lifecycle.resolve_deadlines(_regime("SA")["lifecycle"], self.simplified)[0]
        return deadline.state(now)

    def test_warning_starts_at_exactly_a_quarter_of_the_window_left(self) -> None:
        assert self._state(datetime(2026, 3, 11, 3, 0, tzinfo=UTC)) == "warning"  # 6 h left of 24
        assert self._state(datetime(2026, 3, 11, 2, 59, tzinfo=UTC)) == "ok"
        assert self._state(datetime(2026, 3, 10, 9, 0, tzinfo=UTC)) == "ok"

    def test_due_instant_is_not_overdue_one_second_later_is(self) -> None:
        assert self._state(datetime(2026, 3, 11, 9, 0, tzinfo=UTC)) == "warning"
        assert self._state(datetime(2026, 3, 11, 9, 0, 1, tzinfo=UTC)) == "overdue"

    def test_overdue_simplified_blocks_with_the_pack_rule(self) -> None:
        found = lifecycle.evaluate(_regime("SA"), self.simplified, now=datetime(2026, 3, 12, tzinfo=UTC))
        assert lifecycle.blocking(found)
        assert lifecycle.blocking(found)[0].severity == "error"

    def test_standard_invoice_has_no_24h_deadline(self) -> None:
        std = {**self.simplified, "document_kind": "standard"}
        assert lifecycle.resolve_deadlines(_regime("SA")["lifecycle"], std) == []

    def test_naive_and_aware_timestamps_agree(self) -> None:
        aware = {**self.simplified, "invoice_date": "2026-03-10T09:00:00Z"}
        a = lifecycle.resolve_deadlines(_regime("SA")["lifecycle"], aware)
        b = lifecycle.resolve_deadlines(_regime("SA")["lifecycle"], self.simplified)
        assert a[0].due_at == b[0].due_at

    def test_garbage_dates_yield_no_deadline_and_no_crash(self) -> None:
        for bad in ("", None, "not-a-date", "2026-13-45"):
            doc = {**self.simplified, "invoice_date": bad}
            assert lifecycle.resolve_deadlines(_regime("SA")["lifecycle"], doc) == []

    def test_warning_message_hours_use_decimal_not_float_noise(self) -> None:
        found = lifecycle.evaluate(_regime("SA"), self.simplified, now=datetime(2026, 3, 11, 7, 20, tzinfo=UTC))
        soon = next(f for f in found if f.rule_id == "EINV-CORE-003")
        assert soon.params["n"] == "1.7"


# ── State machine: no illegal jumps ─────────────────────────────────────────


class TestStateMachine:
    def test_every_status_has_a_row(self) -> None:
        assert set(ALLOWED_TRANSITIONS) == set(DOCUMENT_STATUSES)

    def test_cancelled_is_a_dead_end(self) -> None:
        assert all(not can_transition("cancelled", s) for s in DOCUMENT_STATUSES)

    @pytest.mark.parametrize(
        ("src", "dst"),
        [
            ("draft", "cleared"),
            ("draft", "cancelled"),
            ("draft", "rejected"),
            ("validated", "cleared"),
            ("submitted", "draft"),
            ("submitted", "queued"),
            ("submitted", "cancelled"),
            ("cleared", "draft"),
            ("cleared", "submitted"),
            ("cleared", "rejected"),
            ("reported", "cleared"),
            ("delivered", "rejected"),
        ],
    )
    def test_illegal_jumps_are_refused(self, src: str, dst: str) -> None:
        assert not can_transition(src, dst)

    def test_unknown_states_move_nowhere(self) -> None:
        assert not can_transition("bogus", "draft")
        assert not can_transition("draft", "bogus")
        assert not can_transition("", "")

    def test_no_state_transitions_to_itself(self) -> None:
        assert not any(can_transition(s, s) for s in DOCUMENT_STATUSES)

    def test_an_authority_decision_is_only_reachable_from_submitted(self) -> None:
        for src, dst in itertools.product(DOCUMENT_STATUSES, ("cleared", "reported", "delivered")):
            assert can_transition(src, dst) == (src == "submitted")

    def test_resubmitting_a_sent_document_is_not_allowed(self) -> None:
        for sent in ("submitted", "cleared", "reported", "delivered", "cancelled"):
            assert not can_be_sent(sent)
        for ok in ("draft", "validated", "queued", "rejected"):
            assert can_be_sent(ok)

    @pytest.mark.parametrize("status", sorted(DOCUMENT_STATUSES))
    def test_allowed_actions_always_end_with_download_and_never_double_primary(self, status: str) -> None:
        for country in ("SA", "PL", "IN", "MY", "DE"):
            profile = {"mode": "sandbox"}
            actions = lifecycle.allowed_actions(_regime(country), {"status": status}, profile)
            assert actions[-1] == "download"
            assert len([a for a in actions if a != "download"]) <= 1

    def test_cancelled_offers_neither_cancel_nor_correct(self) -> None:
        assert lifecycle.allowed_actions(_regime("SA"), {"status": "cancelled"}, {"mode": "live"}) == ["download"]

    def test_send_is_never_offered_in_export_mode(self) -> None:
        for status in DOCUMENT_STATUSES:
            assert "send" not in lifecycle.allowed_actions(_regime("SA"), {"status": status}, {"mode": "export"})

    def test_rejected_offers_revalidate_not_send(self) -> None:
        assert lifecycle.allowed_actions(_regime("SA"), {"status": "rejected"}, {"mode": "sandbox"}) == [
            "validate",
            "download",
        ]

    def test_cancel_with_unknown_start_is_not_closed(self) -> None:
        """No clearance timestamp yet: nothing to measure the window from, so no false refusal."""
        found = lifecycle.evaluate(
            _regime("MY"), {"status": "cleared"}, intent="cancel", now=datetime(2030, 1, 1, tzinfo=UTC)
        )
        assert found == []

    def test_cancel_window_is_exact_at_72_hours(self) -> None:
        doc = {"status": "cleared", "cleared_at": "2026-11-03T10:00:00+00:00"}
        at = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
        assert lifecycle.evaluate(_regime("MY"), doc, intent="cancel", now=at) == []
        assert _ids(lifecycle.evaluate(_regime("MY"), doc, intent="cancel", now=at + timedelta(seconds=1))) == [
            "EINV-CORE-005"
        ]


# ── Consolidation: rounding, zero, negative, large ──────────────────────────

_MY = regimes.COUNTRY_REGIMES["MY"].lifecycle["consolidation"]
_BIG = {"annual_turnover": "40000000"}


class TestConsolidationEdges:
    def test_empty_period_is_all_zero_and_not_an_error(self) -> None:
        p = consolidation.plan(_MY, [], "2026-10", _BIG)
        assert (p.net, p.tax, p.total, p.count if hasattr(p, "count") else 0) == (Decimal("0.00"),) * 3 + (0,)
        assert consolidation.check(_MY, [], "2026-10", settings=_BIG) == []

    def test_totals_round_half_up_on_the_sum_not_per_receipt(self) -> None:
        receipts = [Receipt(f"R{i}", date(2026, 10, 5), Decimal("0.005"), Decimal("0.004")) for i in range(3)]
        p = consolidation.plan(_MY, receipts, "2026-10", _BIG)
        assert p.net == Decimal("0.02")  # 0.015 -> 0.02 (half up)
        assert p.tax == Decimal("0.01")  # 0.012 -> 0.01
        assert p.total == p.net + p.tax

    def test_cap_is_strictly_greater_than(self) -> None:
        at_cap = Receipt("AT", date(2026, 10, 5), Decimal("10000.00"))
        over = Receipt("OV", date(2026, 10, 5), Decimal("10000.01"))
        p = consolidation.plan(_MY, [at_cap, over], "2026-10", _BIG)
        assert [r.number for r in p.included] == ["AT"]
        assert [(r.number, why) for r, why in p.excluded] == [("OV", consolidation.REASON_OVER_CAP)]

    def test_cap_compares_gross_not_net(self) -> None:
        r = Receipt("G", date(2026, 10, 5), Decimal("9500.00"), Decimal("760.00"))
        assert [x.number for x, _ in consolidation.plan(_MY, [r], "2026-10", _BIG).excluded] == ["G"]

    def test_cap_does_not_bind_before_it_took_effect(self) -> None:
        rule = {**_MY, "cap_effective_from": "2026-01-01"}
        r = Receipt("OLD", date(2025, 12, 31), Decimal("12400.00"))
        assert consolidation.plan(rule, [r], "2025-12", _BIG).excluded == []

    def test_relief_ends_after_its_until_date(self) -> None:
        small = {"annual_turnover": "4000000"}
        inside = Receipt("A", date(2027, 12, 31), Decimal("12400.00"))
        after = Receipt("B", date(2028, 1, 1), Decimal("12400.00"))
        assert consolidation.cap_applies(_MY, inside, small) is False
        assert consolidation.cap_applies(_MY, after, small) is True

    def test_negative_receipt_credit_reduces_totals_exactly(self) -> None:
        receipts = [
            Receipt("S1", date(2026, 10, 2), Decimal("100.10"), Decimal("8.00")),
            Receipt("CN1", date(2026, 10, 3), Decimal("-20.05"), Decimal("-1.60")),
        ]
        p = consolidation.plan(_MY, receipts, "2026-10", _BIG)
        assert (p.net, p.tax, p.total) == (Decimal("80.05"), Decimal("6.40"), Decimal("86.45"))

    def test_ten_thousand_receipts_sum_exactly(self) -> None:
        receipts = [
            Receipt(f"R{i}", date(2026, 10, 1 + i % 31), Decimal("0.10"), Decimal("0.01")) for i in range(10_000)
        ]
        p = consolidation.plan(_MY, receipts, "2026-10", _BIG)
        assert p.net == Decimal("1000.00")  # float would give 999.9999999...
        assert p.tax == Decimal("100.00")
        assert len(p.included) == 10_000

    def test_period_boundaries_first_and_last_day(self) -> None:
        r = [Receipt("F", date(2026, 10, 1), Decimal("1")), Receipt("L", date(2026, 10, 31), Decimal("1"))]
        assert len(consolidation.plan(_MY, r, "2026-10", _BIG).included) == 2

    def test_due_date_crosses_the_year_and_leap_february(self) -> None:
        assert consolidation.due_date("2026-12", _MY) == date(2027, 1, 7)
        assert consolidation.period_bounds("2028-02")[1] == date(2028, 2, 29)
        assert consolidation.period_bounds("2026-02")[1] == date(2026, 2, 28)

    @pytest.mark.parametrize("bad", ["2026-13", "2026-00", "abcd-ef", "2026", ""])
    def test_malformed_period_is_a_value_error(self, bad: str) -> None:
        with pytest.raises(ValueError):  # noqa: PT011
            consolidation.period_bounds(bad)

    def test_malformed_stored_receipts_are_skipped_not_fatal(self) -> None:
        fields = {"receipts": [{"number": "ok", "date": "2026-10-02", "net": "1.5"}, {"date": "x"}, {"net": "1"}, 7]}
        got = consolidation.receipts_from_fields(fields)
        assert [r.number for r in got] == ["ok"]

    def test_late_check_is_silent_once_submitted(self) -> None:
        found = consolidation.check(_MY, [], "2026-10", settings=_BIG, today=date(2026, 12, 1), submitted=True)
        assert found == []

    def test_due_day_itself_is_not_late(self) -> None:
        assert consolidation.check(_MY, [], "2026-10", settings=_BIG, today=date(2026, 11, 7)) == []

    def test_buyer_type_restriction_excludes_business_receipts(self) -> None:
        rule = {**_MY, "allowed_buyer_types": ["consumer"]}
        r = Receipt("B2B", date(2026, 10, 2), Decimal("5"), buyer_type="business")
        assert [why for _r, why in consolidation.plan(rule, [r], "2026-10", _BIG).excluded] == [
            consolidation.REASON_BUYER_TYPE
        ]


# ── Mandate packs: shape, sources, switched-off defaults ────────────────────


class TestMandatePacks:
    def _files(self) -> list[Path]:
        return sorted(regimes.MANDATES_DIR.glob("*.json"))

    def test_every_dated_rule_in_the_lifecycle_cites_a_source(self) -> None:
        missing: list[str] = []
        for path in self._files():
            lc = json.loads(path.read_text(encoding="utf-8")).get("lifecycle") or {}
            blocks = [*lc.get("deadlines", []), lc.get("cancel"), lc.get("consolidation")]
            for block in blocks:
                if block and block.get("allowed") is not False and not block.get("source_url"):
                    missing.append(f"{path.stem}:{block.get('id', 'block')}")
        assert missing == []

    def test_unread_values_are_never_silently_active(self) -> None:
        """A value with needs_review must also carry a reason in notes."""
        bad: list[str] = []
        for path in self._files():
            lc = json.loads(path.read_text(encoding="utf-8")).get("lifecycle") or {}
            for block in [*lc.get("deadlines", []), lc.get("cancel") or {}]:
                if block.get("needs_review") and not block.get("notes"):
                    bad.append(path.stem)
        assert bad == []

    def test_us_has_no_regime_so_a_us_only_tenant_gets_nothing(self) -> None:
        assert regimes.get_country_regime("US") is None
        assert "US" not in regimes.COUNTRY_REGIMES

    def test_de_and_sa_have_their_own_rows(self) -> None:
        assert regimes.get_country_regime("DE") is not None
        assert regimes.get_country_regime("SA") is not None

    def test_lowercase_country_code_still_resolves(self) -> None:
        assert regimes.get_country_regime("sa") is regimes.COUNTRY_REGIMES["SA"]

    def test_no_country_is_hardcoded_in_the_neutral_engine(self) -> None:
        for name in ("lifecycle.py", "consolidation.py"):
            src = (_APP / "modules" / "einvoice_clearance" / name).read_text(encoding="utf-8")
            tree = ast.parse(src)
            strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            for code in ("SA", "IN", "MY", "PL", "ZATCA", "MyInvois", "KSeF"):
                assert code not in strings, f"{name} names {code}"

    def test_regime_without_lifecycle_block_yields_no_findings(self) -> None:
        bare = {"platform": "X", "lifecycle": None}
        assert lifecycle.evaluate(bare, {"status": "draft"}) == []
        assert lifecycle.allowed_actions(bare, {"status": "cleared"}) == ["correct", "download"]


# ── EN 16931 totals with Decimal ────────────────────────────────────────────


def _party(**over: object) -> Party:
    base = {
        "name": "Bau GmbH",
        "country_code": "DE",
        "vat_id": "DE123456789",
        "line1": "Str 1",
        "postcode": "10115",
        "city": "Berlin",
    }
    base.update(over)
    return Party(**base)  # type: ignore[arg-type]


def _line(n: str, net: str, rate: str, cat: str = "S") -> EInvoiceLine:
    return EInvoiceLine(
        line_id=n,
        name=f"Item {n}",
        quantity=Decimal("1"),
        unit="C62",
        net_unit_price=Decimal(net),
        line_net_amount=Decimal(net),
        vat_rate=Decimal(rate),
        vat_category=cat,
    )


def _invoice(
    lines: list[EInvoiceLine], subtotals: list[TaxSubtotal], currency: str = "EUR", **over: object
) -> EInvoice:
    net = sum((ln.line_net_amount for ln in lines), Decimal("0"))
    tax = sum((g.tax_amount for g in subtotals), Decimal("0"))
    base: dict[str, object] = {
        "profile": "zugferd",
        "invoice_number": "RE-1",
        "issue_date": "2026-08-11",
        "currency": currency,
        "seller": _party(),
        "buyer": _party(name="Stadtwerke AG", vat_id=None),
        "lines": lines,
        "tax_subtotals": subtotals,
        "line_total": net,
        "tax_basis_total": net,
        "tax_total": tax,
        "grand_total": net + tax,
        "due_payable": net + tax,
    }
    base.update(over)
    return EInvoice(**base)  # type: ignore[arg-type]


def _fatal(inv: EInvoice) -> set[str]:
    return {v.rule_id for v in rules.check(inv) if v.severity == rules.FATAL}


class TestEn16931Totals:
    def test_mixed_vat_rates_reconcile(self) -> None:
        lines = [_line("1", "1000.00", "19"), _line("2", "500.00", "7")]
        subs = [
            TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("1000.00"), tax_amount=Decimal("190.00")),
            TaxSubtotal(category="S", rate=Decimal("7"), basis=Decimal("500.00"), tax_amount=Decimal("35.00")),
        ]
        inv = _invoice(lines, subs)
        assert inv.grand_total == Decimal("1725.00")
        assert _fatal(inv) == set()

    def test_mixed_vat_with_a_wrong_total_trips_br_co_15(self) -> None:
        lines = [_line("1", "1000.00", "19"), _line("2", "500.00", "7")]
        subs = [
            TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("1000.00"), tax_amount=Decimal("190.00")),
            TaxSubtotal(category="S", rate=Decimal("7"), basis=Decimal("500.00"), tax_amount=Decimal("35.00")),
        ]
        inv = _invoice(lines, subs, grand_total=Decimal("1724.99"), due_payable=Decimal("1724.99"))
        assert "BR-CO-15" in _fatal(inv)

    def test_line_sum_mismatch_trips_br_co_10(self) -> None:
        lines = [_line("1", "10.00", "19")]
        subs = [TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("10.00"), tax_amount=Decimal("1.90"))]
        inv = _invoice(lines, subs, line_total=Decimal("10.01"), tax_basis_total=Decimal("10.01"))
        assert "BR-CO-10" in _fatal(inv)

    def test_vat_breakdown_sum_mismatch_trips_br_co_14(self) -> None:
        lines = [_line("1", "10.00", "19")]
        subs = [TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("10.00"), tax_amount=Decimal("1.90"))]
        inv = _invoice(
            lines, subs, tax_total=Decimal("1.91"), grand_total=Decimal("11.91"), due_payable=Decimal("11.91")
        )
        assert "BR-CO-14" in _fatal(inv)

    def test_prepayment_must_be_deducted_br_co_16(self) -> None:
        lines = [_line("1", "100.00", "19")]
        subs = [TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("100.00"), tax_amount=Decimal("19.00"))]
        ok = _invoice(lines, subs, prepaid_amount=Decimal("50.00"), due_payable=Decimal("69.00"))
        bad = _invoice(lines, subs, prepaid_amount=Decimal("50.00"), due_payable=Decimal("119.00"))
        assert "BR-CO-16" not in _fatal(ok)
        assert "BR-CO-16" in _fatal(bad)

    def test_half_cent_difference_rounds_half_up_and_passes(self) -> None:
        lines = [_line("1", "0.125", "19")]
        subs = [TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("0.125"), tax_amount=Decimal("0.02375"))]
        inv = _invoice(
            lines,
            subs,
            line_total=Decimal("0.13"),
            tax_basis_total=Decimal("0.13"),
            tax_total=Decimal("0.02"),
            grand_total=Decimal("0.15"),
            due_payable=Decimal("0.15"),
        )
        assert {"BR-CO-13", "BR-CO-15"}.isdisjoint(_fatal(inv))

    def test_jpy_has_no_decimals_and_rounds_to_yen(self) -> None:
        assert rules.money_decimals("JPY") == 0
        lines = [_line("1", "1000", "10")]
        subs = [TaxSubtotal(category="S", rate=Decimal("10"), basis=Decimal("1000"), tax_amount=Decimal("100"))]
        assert _fatal(_invoice(lines, subs, currency="JPY")) == set()
        off = _invoice(lines, subs, currency="JPY", grand_total=Decimal("1101"), due_payable=Decimal("1101"))
        assert "BR-CO-15" in _fatal(off)

    def test_sar_vat_15_percent_fixture_reconciles(self) -> None:
        net, tax = Decimal("4600.00"), Decimal("690.00")
        assert net * Decimal("0.15") == tax
        lines = [_line("1", "4600.00", "15")]
        subs = [TaxSubtotal(category="S", rate=Decimal("15"), basis=net, tax_amount=tax)]
        inv = _invoice(lines, subs, currency="SAR", seller=_party(country_code="SA", vat_id="310122393500003"))
        assert inv.grand_total == Decimal("5290.00")
        assert "BR-CO-15" not in _fatal(inv)

    def test_kwd_three_decimals_is_capped_at_two_for_documents(self) -> None:
        assert rules.money_decimals("KWD") <= 2

    def test_credit_note_with_positive_amounts_reconciles(self) -> None:
        lines = [_line("1", "500.00", "21")]
        subs = [TaxSubtotal(category="S", rate=Decimal("21"), basis=Decimal("500.00"), tax_amount=Decimal("105.00"))]
        inv = _invoice(lines, subs, type_code="381")
        assert inv.type_code == "381"
        assert {"BR-CO-10", "BR-CO-13", "BR-CO-14", "BR-CO-15"}.isdisjoint(_fatal(inv))

    def test_zero_value_invoice_reconciles(self) -> None:
        lines = [_line("1", "0.00", "19")]
        subs = [TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("0.00"), tax_amount=Decimal("0.00"))]
        assert {"BR-CO-10", "BR-CO-13", "BR-CO-14", "BR-CO-15", "BR-CO-16"}.isdisjoint(_fatal(_invoice(lines, subs)))

    def test_hundred_lines_of_a_tenth_sum_exactly(self) -> None:
        lines = [_line(str(i), "0.10", "0", "Z") for i in range(1, 1001)]
        subs = [TaxSubtotal(category="Z", rate=Decimal("0"), basis=Decimal("100.00"), tax_amount=Decimal("0.00"))]
        inv = _invoice(lines, subs)
        assert inv.line_total == Decimal("100.00")
        assert {"BR-CO-10", "BR-CO-13", "BR-CO-15"}.isdisjoint(_fatal(inv))


# ── Inbound parser: hostile amounts ─────────────────────────────────────────

_CII = b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
 xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
 xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
 <rsm:ExchangedDocument><ram:ID>CN-7</ram:ID><ram:TypeCode>381</ram:TypeCode>
  <ram:IssueDateTime><udt:DateTimeString format="102">20261020</udt:DateTimeString></ram:IssueDateTime></rsm:ExchangedDocument>
 <rsm:SupplyChainTradeTransaction>
  <ram:ApplicableHeaderTradeAgreement>
   <ram:SellerTradeParty><ram:Name>Lieferant GmbH</ram:Name></ram:SellerTradeParty>
  </ram:ApplicableHeaderTradeAgreement>
  <ram:ApplicableHeaderTradeSettlement><ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
   <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    <ram:TaxBasisTotalAmount>100.00</ram:TaxBasisTotalAmount><ram:TaxTotalAmount>19.00</ram:TaxTotalAmount>
    <ram:GrandTotalAmount>119.00</ram:GrandTotalAmount>
   </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
  </ram:ApplicableHeaderTradeSettlement>
 </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""


class TestInbound:
    def test_cii_credit_note_is_recognised_and_clean(self) -> None:
        inv = parse_inbound(_CII)
        assert inv.syntax == "cii"
        assert inv.is_credit_note is True
        assert inv.invoice_date == "2026-10-20"
        assert inv.amount_gross == Decimal("119.00")
        assert inv.findings == []

    def test_amounts_stay_decimal(self) -> None:
        inv = parse_inbound(_CII)
        assert all(isinstance(v, Decimal) for v in (inv.amount_net, inv.amount_tax, inv.amount_gross))

    def test_missing_mandatory_fields_are_reported(self) -> None:
        inv = parse_inbound(b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"/>')
        codes = {f["code"] for f in inv.findings}
        assert {"BR-02", "BR-03", "BR-05", "BR-06"} <= codes

    @pytest.mark.parametrize("data", [b"", b"   ", b"not xml", b"<a><b></a>", b"\xff\xfe"])
    def test_garbage_is_a_parse_error_not_a_crash(self, data: bytes) -> None:
        with pytest.raises(InboundParseError):
            parse_inbound(data)

    def test_billion_laughs_is_refused(self) -> None:
        bomb = b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><x>&b;</x>'
        with pytest.raises(InboundParseError):
            parse_inbound(bomb)

    def test_large_invoice_number_does_not_break_parsing(self) -> None:
        big = _CII.replace(b"<ram:ID>CN-7</ram:ID>", b"<ram:ID>" + b"9" * 200_000 + b"</ram:ID>")
        assert len(parse_inbound(big).invoice_number) == 200_000

    def test_unparsable_amount_is_flagged_not_zero(self) -> None:
        inv = parse_inbound(_CII.replace(b">119.00<", b">1.000,50<"))
        assert inv.findings, "an unreadable gross amount must raise a finding"

    def test_signalling_nan_amount_is_a_parse_error(self) -> None:
        with pytest.raises(InboundParseError):
            parse_inbound(_CII.replace(b">119.00<", b">sNaN<"))


# ── No float for money ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "modules/einvoice_clearance/consolidation.py",
        "modules/einvoice_clearance/chain.py",
        "modules/einvoice/inbound.py",
    ],
)
def test_money_modules_never_call_float(path: str) -> None:
    tree = ast.parse((_APP / path).read_text(encoding="utf-8"))
    calls = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float"
    ]
    assert calls == []


def test_lifecycle_uses_float_only_for_durations() -> None:
    src = (_APP / "modules/einvoice_clearance/lifecycle.py").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(src, 1):
        if "float(" in line:
            assert "timedelta(hours=float(" in line, f"lifecycle.py:{i} uses float outside a duration"


def test_manifest_is_market_tagged() -> None:
    from app.core.market_scope import is_visible
    from app.modules.einvoice_clearance.manifest import manifest
    from app.modules.einvoice_clearance.regimes import SUPPORTED_COUNTRIES

    assert sorted(manifest.markets) == sorted(SUPPORTED_COUNTRIES)
    assert is_visible(manifest.markets, ["DE"])
    assert not is_visible(manifest.markets, ["US"])


_UBL_DISCOUNT = b"""<?xml version="1.0"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
 <cbc:ID>INV-9</cbc:ID><cbc:IssueDate>2026-10-20</cbc:IssueDate><cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
 <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>S GmbH</cbc:RegistrationName>
 </cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
 <cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount>90.00</cbc:TaxExclusiveAmount>
 <cbc:TaxInclusiveAmount>90.00</cbc:TaxInclusiveAmount></cac:LegalMonetaryTotal>
 <cac:InvoiceLine><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cbc:LineExtensionAmount>100.00</cbc:LineExtensionAmount>
  <cac:Item><cbc:Name>Work</cbc:Name></cac:Item><cac:Price><cbc:PriceAmount>100.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
 <cac:InvoiceLine><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cbc:LineExtensionAmount>-10.00</cbc:LineExtensionAmount>
  <cac:Item><cbc:Name>Discount</cbc:Name></cac:Item><cac:Price><cbc:PriceAmount>-10.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</Invoice>"""


def test_negative_inbound_line_is_kept_and_flagged() -> None:
    inv = parse_inbound(_UBL_DISCOUNT)
    amounts = [Decimal(ln["amount"]) for ln in inv.lines]
    assert amounts == [Decimal("100.00"), Decimal("-10.00")]
    assert sum(amounts) == inv.amount_net
    assert inv.lines[1]["unit_rate"] == "-10.00"
    flagged = [f for f in inv.findings if f["code"] == "LINE-NEGATIVE"]
    assert len(flagged) == 1 and flagged[0]["severity"] == "warning"
