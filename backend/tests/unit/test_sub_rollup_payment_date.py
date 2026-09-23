# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A certificate the law asks for on the payment date is judged on that date.

The German pack declares the construction withholding tax exemption
(Freistellungsbescheinigung) with ``valid_at: payment_date``: it has to be
valid on the day the subcontractor is paid, not through the period end the
other certificates are judged at. Judged at the period end it was wrong both
ways. A certificate renewed after the period but before the payment was
reported lapsed, and a claim for March certified in April and paid in May on
a certificate that ran out on 30 April read as met, while the tax office
expects fifteen per cent to have been withheld.

The product warns and does not deduct. A pay application that is not paid
yet cannot be decided and says so rather than reading as met. One that was
paid on a day the certificate did not cover is a warning that says what the
law then requires, from the withholding scheme's own data, and leaves the
deduction to the person.

The United States pack declares ``period_end`` for everything, and what it
produces is held byte for byte against a snapshot taken from the code
before this reading existed.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.regional_packs import resolve_progress_billing
from app.core.validation.engine import RuleResult, Severity, ValidationContext
from app.modules.subcontractors.claim_rules import ROLLUP_KEY, SUB_ROLLUP_RULES, SubCertificateLapsedRule
from app.modules.subcontractors.rollup import (
    build_claim_rollup,
    requirements_from_pack,
    rule_context_from_rollup,
)

D = Decimal
SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "sub_rollup" / "us_claim_rollup_snapshot.json"


def _uid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def _plain_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_json(v) for v in value]
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, str | int | float | bool):
        return value.value
    return value


def _sov(n: int, code: str, total: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=_uid(n),
        code=code,
        description=f"Line {code}",
        total_value=D(total),
        quantity=D("1"),
        unit="LS",
        parent_line_id=None,
    )


def _agreement(n: int, sub: int, title: str, *, waiver: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=_uid(n),
        subcontractor_id=_uid(sub),
        title=title,
        currency="USD",
        requires_lien_waiver=waiver,
        prime_contract_id=None,
    )


def _pay_app(n: int, agreement: SimpleNamespace, number: str, **fields: Any) -> SimpleNamespace:
    base = {
        "id": _uid(n),
        "agreement_id": agreement.id,
        "application_number": number,
        "status": "finance_approved",
        "currency": "USD",
        "gross_amount": D("1000.00"),
        "net_amount": D("900.00"),
        "period_start": date(2026, 3, 1),
        "period_end": date(2026, 3, 31),
        "progress_claim_id": _uid(999),
        "paid_at": None,
    }
    base.update(fields)
    return SimpleNamespace(**base)


def _line(n: int, pay_app: SimpleNamespace, package: SimpleNamespace, claimed: str, certified: str, approved: str):
    return SimpleNamespace(
        id=_uid(n),
        payment_application_id=pay_app.id,
        work_package_id=package.id,
        contract_line_id=None,
        claimed_amount=D(claimed),
        certified_amount=D(certified),
        approved_amount=D(approved),
    )


def _cert(cert_type: str, valid_until: date | None, *, revoked: bool = False, valid_from: date | None = None):
    return SimpleNamespace(
        cert_type=cert_type,
        valid_until=valid_until,
        valid_from=valid_from or date(2025, 1, 1),
        revoked=revoked,
        subcontractor_id=None,
    )


def _waiver(waiver_type: str, amount: str, through: date) -> SimpleNamespace:
    return SimpleNamespace(waiver_type=waiver_type, amount=D(amount), signed_date=through, through_date=through)


def _context(rollup: dict[str, Any]) -> ValidationContext:
    data = {"claim": {"id": "claim-1"}, "lines": [], "currency": "USD", ROLLUP_KEY: rule_context_from_rollup(rollup)}
    return ValidationContext(data=data, metadata={"locale": "en"})


def _result_json(result: RuleResult) -> dict[str, Any]:
    return _plain_json(
        {
            "rule_id": result.rule_id,
            "severity": result.severity,
            "category": result.category,
            "passed": result.passed,
            "message": result.message,
            "element_ref": result.element_ref,
            "details": result.details,
            "suggestion": result.suggestion,
        }
    )


# ── United States: byte-identical ───────────────────────────────────────────


def _us_rollup() -> dict[str, Any]:
    requirements = requirements_from_pack(resolve_progress_billing(country_code="US"))
    line_a, line_b = _sov(1, "03.10", "100000"), _sov(2, "05.20", "50000")
    concrete = _agreement(11, 21, "Concrete subcontract", waiver=True)
    steel = _agreement(12, 22, "Steel subcontract", waiver=False)
    wp_a = SimpleNamespace(id=_uid(31), name="Concrete", contract_line_id=line_a.id)
    wp_b = SimpleNamespace(id=_uid(32), name="Steel", contract_line_id=line_b.id)
    approved = _pay_app(41, concrete, "PA-1", gross_amount=D("10000.00"), net_amount=D("9000.00"))
    paid = _pay_app(
        42,
        steel,
        "PA-7",
        status="paid",
        gross_amount=D("5000.00"),
        net_amount=D("4500.00"),
        paid_at=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
    )
    prior = _pay_app(
        43,
        concrete,
        "PA-0",
        status="paid",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        paid_at=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
        progress_claim_id=_uid(998),
    )
    candidate = _pay_app(44, steel, "PA-8", status="submitted", progress_claim_id=None)
    lines = [
        _line(51, approved, wp_a, "10000", "9500", "9000"),
        _line(52, paid, wp_b, "5000", "5000", "4000"),
        _line(53, prior, wp_a, "3000", "3000", "3000"),
    ]
    claim_line = SimpleNamespace(contract_line_id=line_a.id, period_completed_value=D("20000"))
    return build_claim_rollup(
        [line_a, line_b],
        [claim_line],
        [approved, paid],
        lines,
        {wp_a.id: wp_a, wp_b.id: wp_b},
        {
            approved.id: [_waiver("conditional_partial", "9000", date(2026, 3, 31))],
            prior.id: [_waiver("unconditional_partial", "2700", date(2026, 2, 28))],
        },
        {
            concrete.subcontractor_id: [_cert("insurance", date(2026, 3, 15)), _cert("license", None)],
            steel.subcontractor_id: [_cert("insurance", date(2026, 12, 31)), _cert("license", None, revoked=True)],
        },
        as_of=date(2026, 3, 31),
        requirements=requirements,
        currency="USD",
        agreements_by_id={concrete.id: concrete, steel.id: steel},
        subcontractor_names={concrete.subcontractor_id: "Example Concrete", steel.subcontractor_id: "Example Steel"},
        prior_pay_apps=[prior],
        candidates=[candidate],
        period=(date(2026, 3, 1), date(2026, 3, 31)),
    )


async def us_snapshot() -> dict[str, Any]:
    """The rollup, its rule context and every subcontract rule's results for a US claim."""
    rollup = _us_rollup()
    context = _context(rollup)
    results: list[dict[str, Any]] = []
    for rule_class in SUB_ROLLUP_RULES:
        results.extend(_result_json(result) for result in await rule_class().validate(context))
    return {
        "rollup": _plain_json(rollup),
        "rule_context": _plain_json(context.data[ROLLUP_KEY]),
        "rule_results": results,
    }


def us_snapshot_text() -> str:
    return json.dumps(asyncio.run(us_snapshot()), sort_keys=True, indent=1, ensure_ascii=False) + "\n"


@pytest.mark.asyncio
async def test_the_us_rollup_its_rule_context_and_its_findings_are_what_they_were() -> None:
    # The snapshot was written by the code before valid_at was read. Every
    # key, value and message of a US claim must come out the same.
    produced = json.dumps(await us_snapshot(), sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    assert produced == SNAPSHOT.read_text(encoding="utf-8")


# ── Germany: the exemption certificate on the payment date ──────────────────


def _de_requirements():
    return requirements_from_pack(resolve_progress_billing(country_code="DE"))


_PERIOD_END = date(2026, 3, 31)


def _de_rollup(pay_app_fields: dict[str, Any], certs: list[SimpleNamespace], *, as_of: date | None = _PERIOD_END):
    line = _sov(1, "300", "100000")
    agreement = _agreement(11, 21, "Rohbau", waiver=False)
    agreement.currency = "EUR"
    package = SimpleNamespace(id=_uid(31), name="Rohbau", contract_line_id=line.id)
    pay_app = _pay_app(41, agreement, "AR-3", currency="EUR", **pay_app_fields)
    return build_claim_rollup(
        [line],
        [],
        [pay_app],
        [_line(51, pay_app, package, "1000", "1000", "1000")],
        {package.id: package},
        {},
        {agreement.subcontractor_id: certs},
        as_of=as_of,
        requirements=_de_requirements(),
        currency="EUR",
        agreements_by_id={agreement.id: agreement},
        subcontractor_names={agreement.subcontractor_id: "Beispiel Bau GmbH"},
        period=(date(2026, 3, 1), _PERIOD_END),
    )


def _clearances() -> list[SimpleNamespace]:
    return [
        _cert("social_security_clearance", date(2026, 12, 31)),
        _cert("employers_liability_clearance", date(2026, 12, 31)),
    ]


def _paid(day: datetime) -> dict[str, Any]:
    return {"status": "paid", "paid_at": day}


def test_the_german_pack_names_the_exemption_as_judged_on_the_payment_date() -> None:
    de = _de_requirements()
    assert [(r.cert_type, r.withholding_scheme) for r in de.payment_date] == [
        ("construction_tax_exemption", "DE_BAUABZUGSTEUER")
    ]
    assert "construction_tax_exemption" in de.certificate_types
    us = requirements_from_pack(resolve_progress_billing(country_code="US"))
    assert us.payment_date == ()


def test_a_certificate_that_ran_out_before_the_payment_is_not_met_whatever_the_period_end_said() -> None:
    # March claim, certified in April, paid on 5 May on a certificate that
    # ran out on 30 April. At the period end it was valid, which is exactly
    # the reading that used to say "met".
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 4, 30))]
    row = _de_rollup(_paid(datetime(2026, 5, 5, 9, 0, tzinfo=UTC)), certs)["included"][0]
    assert row["certificate_findings"] == []
    assert row["paid_on"] == date(2026, 5, 5)
    assert row["certificates_ok"] is False
    assert row["certificates_pending_payment"] is False
    [finding] = row["payment_date_findings"]
    assert finding["document_type"] == "construction_tax_exemption"
    assert finding["state"] == "expired"
    assert finding["judged_on"] == date(2026, 5, 5)
    assert finding["lapsed_on"] == date(2026, 4, 30)
    assert finding["withholding"] == {
        "scheme": "DE_BAUABZUGSTEUER",
        "rate_pct": "15",
        "vat_included": True,
        "annual_limit": "5000.00",
        "currency": "EUR",
        "reference": "§ 48 Abs. 2 Satz 1 EStG; § 48b Abs. 1 EStG",
    }


def test_a_certificate_renewed_after_the_period_but_before_the_payment_is_met() -> None:
    certs = [
        *_clearances(),
        _cert("construction_tax_exemption", date(2026, 3, 15)),
        _cert("construction_tax_exemption", date(2026, 12, 31), valid_from=date(2026, 4, 1)),
    ]
    row = _de_rollup(_paid(datetime(2026, 4, 20, 9, 0, tzinfo=UTC)), certs)["included"][0]
    assert row["certificate_findings"] == []
    assert row["payment_date_findings"] == []
    assert row["certificates_ok"] is True
    assert row["certificates_pending_payment"] is False


def test_before_the_payment_the_answer_is_not_yet_rather_than_met() -> None:
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 12, 31))]
    rollup = _de_rollup({}, certs)
    row = rollup["included"][0]
    assert row["paid_on"] is None
    assert row["certificates_ok"] is None
    assert row["certificates_pending_payment"] is True
    [finding] = row["payment_date_findings"]
    assert (finding["state"], finding["judged_on"], finding["valid_until"]) == ("pending", None, date(2026, 12, 31))
    # The GC line row carries the same answer.
    assert rollup["lines"][0]["subs"][0]["certificates_ok"] is None
    assert rollup["lines"][0]["subs"][0]["certificates_pending_payment"] is True


def test_before_the_payment_without_a_usable_certificate_it_is_flagged_sooner() -> None:
    lapsed_before_period_end = [*_clearances(), _cert("construction_tax_exemption", date(2026, 2, 28))]
    [finding] = _de_rollup({}, lapsed_before_period_end)["included"][0]["payment_date_findings"]
    assert finding["state"] == "pending_invalid"
    [finding] = _de_rollup({}, _clearances())["included"][0]["payment_date_findings"]
    assert finding["state"] == "pending_invalid"
    revoked = [*_clearances(), _cert("construction_tax_exemption", date(2026, 12, 31), revoked=True)]
    [finding] = _de_rollup({}, revoked)["included"][0]["payment_date_findings"]
    assert finding["state"] == "pending_invalid"


def test_the_payment_day_is_the_utc_calendar_day_of_the_click() -> None:
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 4, 30))]
    late_evening = _de_rollup(_paid(datetime(2026, 4, 30, 23, 30, tzinfo=UTC)), certs)["included"][0]
    assert late_evening["paid_on"] == date(2026, 4, 30)
    assert late_evening["certificates_ok"] is True
    # 01:30 in Berlin summer time is still 30 April in UTC.
    berlin = timezone(timedelta(hours=2))
    after_midnight = _de_rollup(_paid(datetime(2026, 5, 1, 1, 30, tzinfo=berlin)), certs)["included"][0]
    assert after_midnight["paid_on"] == date(2026, 4, 30)
    next_day = _de_rollup(_paid(datetime(2026, 5, 1, 0, 30, tzinfo=UTC)), certs)["included"][0]
    assert next_day["paid_on"] == date(2026, 5, 1)
    assert next_day["certificates_ok"] is False


def test_the_period_end_certificates_are_still_judged_at_the_period_end() -> None:
    certs = [
        _cert("social_security_clearance", date(2026, 3, 20)),
        _cert("employers_liability_clearance", date(2026, 12, 31)),
        _cert("construction_tax_exemption", date(2026, 12, 31)),
    ]
    row = _de_rollup(_paid(datetime(2026, 4, 20, 9, 0, tzinfo=UTC)), certs)["included"][0]
    assert [(f["document_type"], f["state"]) for f in row["certificate_findings"]] == [
        ("social_security_clearance", "expired")
    ]
    assert row["payment_date_findings"] == []
    assert row["certificates_ok"] is False


def test_a_payment_without_a_recorded_day_is_not_met_either() -> None:
    # Marked paid, but no paid_at: there is no day to read the certificate on,
    # and "met" would be a verdict nobody reached.
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 12, 31))]
    row = _de_rollup({"status": "paid", "paid_at": None}, certs)["included"][0]
    assert row["paid_on"] is None
    assert row["certificates_ok"] is False
    assert [f["state"] for f in row["payment_date_findings"]] == ["undated"]


def test_an_open_ended_certificate_still_waits_for_the_payment() -> None:
    certs = [*_clearances(), _cert("construction_tax_exemption", None)]
    row = _de_rollup({}, certs)["included"][0]
    assert row["certificates_ok"] is None
    [finding] = row["payment_date_findings"]
    assert (finding["state"], finding["valid_until"]) == ("pending_open", None)


def test_a_claim_without_a_period_end_still_judges_the_payment_date() -> None:
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 4, 30))]
    row = _de_rollup(_paid(datetime(2026, 5, 5, 9, 0, tzinfo=UTC)), certs, as_of=None)["included"][0]
    assert row["certificate_findings"] == []
    assert row["certificates_ok"] is False
    assert row["payment_date_findings"][0]["state"] == "expired"


# ── The rule that words it ──────────────────────────────────────────────────


async def _run_all(rollup: dict[str, Any]) -> list[RuleResult]:
    context = _context(rollup)
    results: list[RuleResult] = []
    for rule_class in SUB_ROLLUP_RULES:
        results.extend(await rule_class().validate(context))
    return results


def _payment_date_results(results: list[RuleResult]) -> list[RuleResult]:
    return [r for r in results if r.rule_id == "pay_application.sub_certificate_payment_date"]


@pytest.mark.asyncio
async def test_a_payment_on_a_lapsed_certificate_warns_with_what_the_law_requires() -> None:
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 4, 30))]
    results = await _run_all(_de_rollup(_paid(datetime(2026, 5, 5, 9, 0, tzinfo=UTC)), certs))
    [warning] = _payment_date_results(results)
    assert warning.passed is False
    assert warning.severity == Severity.WARNING
    assert "Beispiel Bau GmbH" in warning.message
    assert "2026-05-05" in warning.message
    assert "AR-3" in warning.message
    assert "15%" in warning.message
    assert "VAT included" in warning.message
    assert "5,000.00 EUR" in warning.message
    assert "not deducted" in warning.suggestion
    # Warn, never block: nothing about the exemption is an error, and the
    # period-end rule does not judge it at all.
    assert not [r for r in results if r.severity == Severity.ERROR and not r.passed]
    lapsed = [r for r in results if r.rule_id == SubCertificateLapsedRule.rule_id]
    assert all(r.passed for r in lapsed)


@pytest.mark.asyncio
async def test_an_unpaid_pay_application_is_reported_as_undecided_not_as_met() -> None:
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 12, 31))]
    [info] = _payment_date_results(await _run_all(_de_rollup({}, certs)))
    assert info.passed is False
    assert info.severity == Severity.INFO
    assert "not paid yet" in info.message
    assert "15%" in info.message


@pytest.mark.asyncio
async def test_an_unpaid_pay_application_without_a_usable_certificate_is_a_warning() -> None:
    [warning] = _payment_date_results(await _run_all(_de_rollup({}, _clearances())))
    assert warning.passed is False
    assert warning.severity == Severity.WARNING
    assert "no valid" in warning.message


@pytest.mark.asyncio
async def test_a_payment_the_certificate_covered_passes() -> None:
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 12, 31))]
    [ok] = _payment_date_results(await _run_all(_de_rollup(_paid(datetime(2026, 4, 20, tzinfo=UTC)), certs)))
    assert ok.passed is True


@pytest.mark.asyncio
async def test_without_the_scheme_data_it_still_says_withholding_may_apply(monkeypatch) -> None:
    import app.modules.subcontractors.rollup as rollup_module

    monkeypatch.setattr(rollup_module, "withholding_terms", lambda *args, **kwargs: None)
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 4, 30))]
    [warning] = _payment_date_results(await _run_all(_de_rollup(_paid(datetime(2026, 5, 5, tzinfo=UTC)), certs)))
    assert warning.severity == Severity.WARNING
    assert "may be subject to tax withholding" in warning.message
    assert "%" not in warning.message


@pytest.mark.asyncio
async def test_the_german_wording_is_german() -> None:
    certs = [*_clearances(), _cert("construction_tax_exemption", date(2026, 4, 30))]
    context = _context(_de_rollup(_paid(datetime(2026, 5, 5, tzinfo=UTC)), certs))
    context.metadata["locale"] = "de"
    from app.modules.subcontractors.claim_rules import SubCertificatePaymentDateRule

    [warning] = await SubCertificatePaymentDateRule().validate(context)
    assert "Freistellungsbescheinigung" in warning.message
    assert "15 %" in warning.message or "15%" in warning.message


if __name__ == "__main__":  # pragma: no cover - writes the US snapshot from the code as it stands
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(us_snapshot_text(), encoding="utf-8")
