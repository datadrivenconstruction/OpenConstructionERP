# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The subcontract rollup of a GC progress claim, as pure functions.

``subcontractors.rollup`` lines up the pay applications included in one GC
claim against the GC's schedule of values. Everything here runs on plain
objects with no database, because each rule below is a decision about money
that has to hold whatever the storage does:

* a pay-application line's own SOV link beats its work package's default;
* a pay application in another currency is counted aside, never added;
* a line that lands on no billable SOV line is reported with why, never placed;
* lien waivers are summarised the way the payment gate reads them;
* certificates are judged as at the claim's period end, never today;
* the suggestion carries the GC's own lines forward, because committing the
  preview replaces every line on the claim.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.modules.subcontractors.rollup import (
    REQUIRED_CERT_TYPES_FOR_PAYMENT,
    SubPaymentRequirements,
    build_claim_rollup,
    claim_period,
    currencies_differ,
    earlier_claim_ids,
    in_period,
    requirements_from_pack,
    resolve_contract_line,
    resolve_prime_contract,
    rule_context_from_rollup,
    suggest_claim_lines,
    waiver_state,
)

D = Decimal


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _sov(code: str, total: str, *, parent: uuid.UUID | None = None, quantity: str = "0") -> SimpleNamespace:
    return SimpleNamespace(
        id=_id(),
        code=code,
        description=f"Line {code}",
        total_value=D(total),
        quantity=D(quantity),
        unit="LS",
        parent_line_id=parent,
    )


def _agreement(**overrides: Any) -> SimpleNamespace:
    fields = {
        "id": _id(),
        "subcontractor_id": _id(),
        "title": "Concrete subcontract",
        "currency": "USD",
        "requires_lien_waiver": False,
        "prime_contract_id": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _pay_app(agreement: SimpleNamespace, number: str, **overrides: Any) -> SimpleNamespace:
    fields = {
        "id": _id(),
        "agreement_id": agreement.id,
        "application_number": number,
        "status": "finance_approved",
        "currency": "USD",
        "gross_amount": D("1000.00"),
        "net_amount": D("900.00"),
        "period_start": date(2026, 4, 1),
        "period_end": date(2026, 4, 30),
        "progress_claim_id": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _pa_line(pay_app: SimpleNamespace, package: SimpleNamespace, approved: str, **overrides: Any) -> SimpleNamespace:
    fields = {
        "id": _id(),
        "payment_application_id": pay_app.id,
        "work_package_id": package.id,
        "contract_line_id": None,
        "claimed_amount": D(approved),
        "certified_amount": D(approved),
        "approved_amount": D(approved),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _package(name: str, contract_line_id: uuid.UUID | None) -> SimpleNamespace:
    return SimpleNamespace(id=_id(), name=name, contract_line_id=contract_line_id)


def _waiver(waiver_type: str, amount: str, *, signed: date | None = None, through: date | None = None) -> Any:
    return SimpleNamespace(waiver_type=waiver_type, amount=D(amount), signed_date=signed, through_date=through)


def _cert(cert_type: str, valid_until: date | None, *, revoked: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        cert_type=cert_type,
        valid_until=valid_until,
        valid_from=date(2025, 1, 1),
        revoked=revoked,
        subcontractor_id=None,
    )


def _rollup(**kwargs: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "sov_lines": [],
        "claim_lines": [],
        "pay_apps": [],
        "pay_app_lines": [],
        "wp_by_id": {},
        "waivers_by_pa": {},
        "certs_by_sub": {},
    }
    defaults.update({k: kwargs.pop(k) for k in list(kwargs) if k in defaults})
    kwargs.setdefault("as_of", date(2026, 4, 30))
    kwargs.setdefault("requirements", SubPaymentRequirements())
    kwargs.setdefault("currency", "USD")
    kwargs.setdefault("agreements_by_id", {})
    return build_claim_rollup(
        defaults["sov_lines"],
        defaults["claim_lines"],
        defaults["pay_apps"],
        defaults["pay_app_lines"],
        defaults["wp_by_id"],
        defaults["waivers_by_pa"],
        defaults["certs_by_sub"],
        **kwargs,
    )


# ── Line mapping ─────────────────────────────────────────────────────────────


def test_a_line_override_beats_the_work_package_default() -> None:
    default, override = _id(), _id()
    package = _package("Footings", default)
    assert (
        resolve_contract_line(SimpleNamespace(contract_line_id=None, work_package_id=package.id), {package.id: package})
        == default
    )
    assert (
        resolve_contract_line(
            SimpleNamespace(contract_line_id=override, work_package_id=package.id), {package.id: package}
        )
        == override
    )
    unlinked = _package("Cleanup", None)
    assert (
        resolve_contract_line(
            SimpleNamespace(contract_line_id=None, work_package_id=unlinked.id), {unlinked.id: unlinked}
        )
        is None
    )


def test_lines_land_on_their_resolved_sov_line_and_the_unresolvable_are_reported_with_why() -> None:
    parent = _sov("03", "0")
    footing = _sov("03.10", "5000", parent=parent.id)
    slab = _sov("03.20", "8000", parent=parent.id)
    agreement = _agreement()
    pay_app = _pay_app(agreement, "PA-1")
    footings = _package("Footings", footing.id)
    cleanup = _package("Cleanup", None)
    lines = [
        _pa_line(pay_app, footings, "1000.00"),  # work package default: footing
        _pa_line(pay_app, footings, "400.00", contract_line_id=slab.id),  # own override: slab
        _pa_line(pay_app, cleanup, "50.00"),  # nothing: unmapped, none
        _pa_line(pay_app, footings, "70.00", contract_line_id=_id()),  # another contract's line
        _pa_line(pay_app, footings, "30.00", contract_line_id=parent.id),  # a grouping line
    ]
    rollup = _rollup(
        sov_lines=[parent, footing, slab],
        pay_apps=[pay_app],
        pay_app_lines=lines,
        wp_by_id={footings.id: footings, cleanup.id: cleanup},
        agreements_by_id={agreement.id: agreement},
    )

    by_line = {row["contract_line_id"]: row for row in rollup["lines"]}
    assert by_line[footing.id]["sub_period_approved"] == D("1000.00")
    assert by_line[slab.id]["sub_period_approved"] == D("400.00")
    assert parent.id not in by_line
    assert sorted(row["reason"] for row in rollup["unmapped_lines"]) == ["foreign_line", "none", "parent_line"]
    assert rollup["sub_period_approved_total"] == D("1400.00")


# ── Currency ─────────────────────────────────────────────────────────────────


def test_a_pay_application_in_another_currency_is_counted_aside_never_added() -> None:
    line = _sov("01", "10000")
    package = _package("Works", line.id)
    usd = _agreement()
    eur = _agreement(currency="EUR")
    pa_usd = _pay_app(usd, "PA-USD")
    pa_eur = _pay_app(eur, "PA-EUR", currency="EUR")
    rollup = _rollup(
        sov_lines=[line],
        pay_apps=[pa_usd, pa_eur],
        pay_app_lines=[_pa_line(pa_usd, package, "300.00"), _pa_line(pa_eur, package, "999.00")],
        wp_by_id={package.id: package},
        agreements_by_id={usd.id: usd, eur.id: eur},
    )
    assert rollup["skipped_foreign_currency"] == 1
    assert rollup["lines"][0]["sub_period_approved"] == D("300.00")
    included = {row["application_number"]: row for row in rollup["included"]}
    assert included["PA-EUR"]["foreign_currency"] is True
    assert included["PA-USD"]["foreign_currency"] is False


def test_a_blank_currency_is_unknown_not_a_mismatch() -> None:
    assert currencies_differ("", "USD") is False
    assert currencies_differ(None, "USD") is False
    assert currencies_differ("usd", "USD") is False
    assert currencies_differ("EUR", "USD") is True

    line = _sov("01", "10000")
    package = _package("Works", line.id)
    agreement = _agreement(currency="")
    pay_app = _pay_app(agreement, "PA-1", currency="")
    rollup = _rollup(
        sov_lines=[line],
        pay_apps=[pay_app],
        pay_app_lines=[_pa_line(pay_app, package, "250.00")],
        wp_by_id={package.id: package},
        agreements_by_id={agreement.id: agreement},
    )
    assert rollup["skipped_foreign_currency"] == 0
    assert rollup["lines"][0]["sub_period_approved"] == D("250.00")


# ── Scheduled value ─────────────────────────────────────────────────────────


def test_approved_to_date_above_the_scheduled_value_is_flagged_outside_rounding_only() -> None:
    line = _sov("01", "1000.0000")
    package = _package("Works", line.id)
    agreement = _agreement()
    earlier = _pay_app(agreement, "PA-1", status="paid", period_end=date(2026, 3, 31))
    now = _pay_app(agreement, "PA-2")

    def run(now_amount: str) -> dict[str, Any]:
        return _rollup(
            sov_lines=[line],
            pay_apps=[now],
            pay_app_lines=[_pa_line(earlier, package, "600.00"), _pa_line(now, package, now_amount)],
            wp_by_id={package.id: package},
            agreements_by_id={agreement.id: agreement},
            prior_pay_apps=[earlier],
        )["lines"][0]

    inside = run("400.01")
    assert inside["sub_approved_to_date"] == D("1000.01")
    assert inside["exceeds_scheduled_value"] is False
    over = run("400.02")
    assert over["exceeds_scheduled_value"] is True


# ── Waivers ─────────────────────────────────────────────────────────────────


def test_waiver_state_reads_waivers_the_way_the_payment_gate_does() -> None:
    assert waiver_state([], D("900"))["state"] == "none"
    assert waiver_state([_waiver("w9", "900")], D("900"))["state"] == "none"

    conditional = waiver_state([_waiver("conditional_progress", "900", signed=date(2026, 4, 28))], D("900"))
    assert conditional["state"] == "conditional"
    assert conditional["covers_net"] is True
    # No through-date on file: the signing date is the honest upper bound.
    assert conditional["through_date"] == date(2026, 4, 28)
    assert conditional["through_date_basis"] == "signed_date"

    short = waiver_state([_waiver("conditional_progress", "899.99")], D("900"))
    assert short["covers_net"] is False

    both = waiver_state(
        [
            _waiver("conditional_progress", "900", through=date(2026, 4, 30)),
            _waiver("unconditional_progress", "900", signed=date(2026, 5, 20), through=date(2026, 3, 31)),
        ],
        D("900"),
    )
    assert both["state"] == "unconditional"
    # The through-date belongs to the reported state, not to the latest waiver.
    assert both["through_date"] == date(2026, 3, 31)
    assert both["through_date_basis"] == "through_date"


# ── Certificates ────────────────────────────────────────────────────────────


def test_certificates_are_judged_at_the_period_end_not_today() -> None:
    line = _sov("01", "10000")
    package = _package("Works", line.id)
    agreement = _agreement()
    pay_app = _pay_app(agreement, "PA-1")
    certs = {
        agreement.subcontractor_id: [_cert("insurance", date(2026, 4, 30)), _cert("license", None)],
    }

    def included(as_of: date | None) -> dict[str, Any]:
        return _rollup(
            sov_lines=[line],
            pay_apps=[pay_app],
            pay_app_lines=[_pa_line(pay_app, package, "100.00")],
            wp_by_id={package.id: package},
            certs_by_sub=certs,
            agreements_by_id={agreement.id: agreement},
            as_of=as_of,
        )["included"][0]

    # Valid on the last day of April, the claim's period end: fine, whatever
    # today's date happens to be when the test runs.
    assert included(date(2026, 4, 30))["certificates_ok"] is True
    lapsed = included(date(2026, 5, 31))
    assert lapsed["certificates_ok"] is False
    assert [(f["document_type"], f["state"]) for f in lapsed["certificate_findings"]] == [("insurance", "expired")]
    # No period end, no date to judge on: unknown, not "fine".
    unknown = included(None)
    assert unknown["certificates_ok"] is None
    assert unknown["certificate_findings"] == []


def test_pack_requirements_replace_the_built_in_list_and_say_where_they_came_from() -> None:
    pack = requirements_from_pack(
        {
            "sub_payment_requirements": {
                "certificate_types": ["insurance", "construction_tax_exemption"],
                "lien_waiver_required": True,
                "statute_reference": "Test statute 1",
            }
        }
    )
    assert pack.certificate_types == ("insurance", "construction_tax_exemption")
    assert pack.lien_waiver_required is True
    assert pack.source == "pack"
    assert pack.reference == "Test statute 1"

    for empty in (None, {}, {"sub_payment_requirements": {"certificate_types": []}}):
        fallback = requirements_from_pack(empty)
        assert fallback.certificate_types == REQUIRED_CERT_TYPES_FOR_PAYMENT
        assert fallback.source == "fallback"
    # A truthy string is not a yes: only a real boolean switches waivers on.
    assert (
        requirements_from_pack({"sub_payment_requirements": {"lien_waiver_required": "no"}}).lien_waiver_required
        is False
    )


# ── Prime contract, period and history ──────────────────────────────────────


def test_the_prime_contract_is_named_or_unambiguous_never_guessed() -> None:
    one, two = _id(), _id()
    assert resolve_prime_contract(_agreement(prime_contract_id=two), [one]) == (two, "explicit")
    assert resolve_prime_contract(_agreement(), [one]) == (one, "single_active_client")
    assert resolve_prime_contract(_agreement(), []) == (None, "none")
    assert resolve_prime_contract(_agreement(), [one, two]) == (None, "ambiguous")


def test_period_membership_is_unknown_rather_than_guessed() -> None:
    claim = SimpleNamespace(
        period_from=date(2026, 4, 1), period_to=date(2026, 4, 30), period_start=None, period_end=None
    )
    frm, to, how = claim_period(claim)
    assert (frm, to, how) == (date(2026, 4, 1), date(2026, 4, 30), "dates")
    assert in_period(SimpleNamespace(period_end=date(2026, 4, 15)), frm, to) is True
    assert in_period(SimpleNamespace(period_end=date(2026, 5, 1)), frm, to) is False
    assert in_period(SimpleNamespace(period_end=date(2026, 3, 31)), frm, to) is False
    assert in_period(SimpleNamespace(period_end=None), frm, to) is None
    assert in_period(SimpleNamespace(period_end=date(2026, 4, 15)), None, None) is None


def test_earlier_claims_skip_rejected_ones_and_stop_at_this_claim() -> None:
    def claim(number: str, period_to: date | None, status: str = "approved") -> SimpleNamespace:
        return SimpleNamespace(
            id=_id(), claim_number=number, status=status, period_from=None, period_to=period_to, created_at=None
        )

    jan = claim("PC-1", date(2026, 1, 31))
    feb = claim("PC-2", date(2026, 2, 28), status="rejected")
    mar = claim("PC-3", date(2026, 3, 31))
    apr = claim("PC-4", date(2026, 4, 30), status="draft")
    assert earlier_claim_ids([apr, mar, feb, jan], apr.id) == [jan.id, mar.id]
    assert earlier_claim_ids([apr, mar, feb, jan], jan.id) == []


# ── Suggestion ──────────────────────────────────────────────────────────────


def test_the_suggestion_carries_the_gcs_own_lines_forward() -> None:
    subbed = _sov("01", "10000", quantity="100")
    self_performed = _sov("02", "4000")
    package = _package("Works", subbed.id)
    agreement = _agreement()
    earlier = _pay_app(agreement, "PA-1", status="paid", period_end=date(2026, 3, 31))
    now = _pay_app(agreement, "PA-2")
    gc_line = SimpleNamespace(
        contract_line_id=self_performed.id,
        period_completed_value=D("1200"),
        period_completed_pct=D("30"),
        period_completed_qty=D("0"),
        cumulative_completed_value=D("1200"),
    )
    rollup = _rollup(
        sov_lines=[subbed, self_performed],
        claim_lines=[gc_line],
        pay_apps=[now],
        pay_app_lines=[_pa_line(earlier, package, "2000.00"), _pa_line(now, package, "2500.00")],
        wp_by_id={package.id: package},
        agreements_by_id={agreement.id: agreement},
        prior_pay_apps=[earlier],
    )
    items = {
        item["contract_line_id"]: item for item in suggest_claim_lines(rollup, [subbed, self_performed], [gc_line])
    }

    sub_item = items[subbed.id]
    assert sub_item["origin"] == "subcontract"
    assert sub_item["period_completed_value"] == D("2500.00")
    # Cumulative: 2000 earlier plus 2500 now, of 10000 scheduled.
    assert sub_item["observed_pct"] == D("45.0000")
    assert sub_item["period_completed_qty"] == D("25.0000")

    kept = items[self_performed.id]
    assert kept["origin"] == "existing"
    assert kept["period_completed_value"] == D("1200")
    assert kept["observed_pct"] == D("30")


def test_the_suggestion_never_bills_past_the_scheduled_value() -> None:
    line = _sov("01", "1000")
    package = _package("Works", line.id)
    agreement = _agreement()
    pay_app = _pay_app(agreement, "PA-1")
    rollup = _rollup(
        sov_lines=[line],
        pay_apps=[pay_app],
        pay_app_lines=[_pa_line(pay_app, package, "1500.00")],
        wp_by_id={package.id: package},
        agreements_by_id={agreement.id: agreement},
    )
    [item] = suggest_claim_lines(rollup, [line], [])
    assert item["period_completed_value"] == D("1000")
    assert item["observed_pct"] == D("100.0000")


# ── Rule context ────────────────────────────────────────────────────────────


def test_a_claim_with_no_subcontract_data_hands_the_rules_nothing() -> None:
    assert rule_context_from_rollup(None) == {}
    assert rule_context_from_rollup(_rollup(sov_lines=[_sov("01", "100")])) == {}


def test_the_rule_context_is_plain_data() -> None:
    line = _sov("01", "1000")
    package = _package("Works", line.id)
    agreement = _agreement()
    pay_app = _pay_app(agreement, "PA-1")
    context = rule_context_from_rollup(
        _rollup(
            sov_lines=[line],
            pay_apps=[pay_app],
            pay_app_lines=[_pa_line(pay_app, package, "100.00")],
            wp_by_id={package.id: package},
            agreements_by_id={agreement.id: agreement},
        )
    )
    assert context["as_of"] == "2026-04-30"
    row = context["included"][0]
    assert row["payment_application_id"] == str(pay_app.id)
    assert row["net_amount"] == "900.00"
    assert row["period_end"] == "2026-04-30"
