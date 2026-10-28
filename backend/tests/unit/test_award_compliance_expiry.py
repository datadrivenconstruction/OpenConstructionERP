"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The award gate reads the expiry dates the compliance register already holds.

Three registers on the platform carry expiry dates, but only one of them is
keyed to a counterparty: ``oe_subcontractors_certificate``, plus the
denormalised ``Subcontractor.insurance_expiry_date`` on the vendor row itself.
Until this gate read them, an expired insurance certificate was recorded,
displayed on the drawer, alerted on by the expiry cron - and did not stop the
award.

What is asserted here, in the order it matters:

* a lapsed blocking document refuses the award, and the refusal names the
  document and the day it lapsed;
* a document that lapsed and was then renewed does **not** refuse, which is the
  case a naive "latest row" or "maximum expiry" reading gets wrong;
* a lapsed document of a type nobody requires does not refuse, because a gate
  that bites on everything is a gate somebody switches off;
* missing and expired are told apart, and only expired blocks the award;
* the boundary on the expiry day itself, from both sides of midnight.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.subcontractors.service import (
    evaluate_required_certificates,
    subcontractor_award_block,
)

AS_AT = date(2026, 6, 15)


def _sub(*, blocked: bool = False, prequal: str = "approved", insurance_expiry: date | None = None):
    """A vendor row with a clean administrative record unless told otherwise."""
    return SimpleNamespace(
        is_blocked=blocked,
        prequalification_status=prequal,
        insurance_expiry_date=insurance_expiry,
    )


def _cert(cert_type: str, valid_until: date | None, *, revoked: bool = False):
    """A certificate row carrying only the fields the gate reads."""
    return SimpleNamespace(cert_type=cert_type, valid_until=valid_until, revoked=revoked)


def _clean_certs() -> list[SimpleNamespace]:
    """One live certificate of each required type."""
    return [
        _cert("insurance", date(2027, 1, 1)),
        _cert("license", date(2027, 1, 1)),
    ]


# ── Expired blocks, and says what and when ────────────────────────────────


def test_expired_blocking_certificate_refuses_the_award() -> None:
    certs = [_cert("insurance", date(2026, 5, 31)), _cert("license", date(2027, 1, 1))]

    result = subcontractor_award_block(_sub(), certificates=certs, as_at=AS_AT)

    assert result.blocked is True
    assert "expired_required_certificate:insurance:2026-05-31" in result.reasons


def test_refusal_names_the_document_and_the_date() -> None:
    """A refusal a person cannot read is a refusal somebody overrides."""
    certs = [_cert("insurance", date(2026, 5, 31)), _cert("license", date(2027, 1, 1))]

    result = subcontractor_award_block(_sub(), certificates=certs, as_at=AS_AT)

    detail = next(d for d in result.details if d.state == "expired")
    assert detail.document_type == "insurance"
    assert detail.lapsed_on == date(2026, 5, 31)
    assert detail.source == "certificate"
    # The flat reason list is what the eligibility banner prints verbatim, so
    # the date has to survive into the string as well as into the structure.
    assert any(str(date(2026, 5, 31)) in reason for reason in result.reasons)


def test_expired_insurance_on_the_vendor_row_refuses_the_award() -> None:
    """The denormalised date is a backstop, and it is attributed separately.

    It also has to be the *only* thing said about insurance. The register holds
    no insurance row here, so without care the evaluator's ``missing`` finding
    and the backstop's ``expired`` one would both land, and one document would
    carry two contradicting states.
    """
    certs = [_cert("license", date(2027, 1, 1))]

    result = subcontractor_award_block(
        _sub(insurance_expiry=date(2026, 4, 30)),
        certificates=certs,
        as_at=AS_AT,
    )

    assert result.blocked is True
    assert result.reasons == ["expired_insurance_on_record:2026-04-30"]
    insurance = [d for d in result.details if d.document_type == "insurance"]
    assert len(insurance) == 1
    assert insurance[0].state == "expired"
    assert insurance[0].source == "subcontractor_record"
    assert insurance[0].lapsed_on == date(2026, 4, 30)


def test_the_register_and_the_vendor_row_never_both_report_one_lapse() -> None:
    """Two sources, one document, one verdict - and the register is the one.

    A lapsed certificate on file *and* a stale date on the vendor row is the
    ordinary shape of this data, because the vendor row is a copy of what the
    register already holds. Reporting both would put two dates on one lapse,
    and a refusal a person cannot read is a refusal somebody overrides.
    """
    certs = [_cert("insurance", date(2026, 5, 31)), _cert("license", date(2027, 1, 1))]

    result = subcontractor_award_block(
        _sub(insurance_expiry=date(2026, 4, 30)),
        certificates=certs,
        as_at=AS_AT,
    )

    assert result.blocked is True
    # The register's date, once, and no second opinion from the copy.
    assert result.reasons == ["expired_required_certificate:insurance:2026-05-31"]
    assert [d.source for d in result.details] == ["certificate"]


def test_every_document_type_yields_exactly_one_finding() -> None:
    """The invariant behind the two tests above, asserted on its own.

    Held across the whole cross product of register state and vendor-row state,
    because it is the property that duplicate-blind assertions - a set of
    states, a dict keyed on the type - silently stop checking.
    """
    registers = {
        "no rows": [],
        "lapsed row": [_cert("insurance", date(2026, 5, 31))],
        "revoked row": [_cert("insurance", date(2027, 1, 1), revoked=True)],
        "live row": [_cert("insurance", date(2027, 1, 1))],
    }
    vendor_dates = [None, date(2026, 4, 30), date(2027, 4, 30)]

    for label, certs in registers.items():
        for vendor_date in vendor_dates:
            result = subcontractor_award_block(
                _sub(insurance_expiry=vendor_date),
                certificates=[*certs, _cert("license", date(2027, 1, 1))],
                as_at=AS_AT,
            )
            types = [d.document_type for d in result.details]
            assert len(types) == len(set(types)), f"duplicate finding for {label} / {vendor_date}"


def test_revoked_certificate_refuses_and_is_not_called_expired() -> None:
    certs = [_cert("insurance", date(2027, 1, 1), revoked=True), _cert("license", date(2027, 1, 1))]

    result = subcontractor_award_block(_sub(), certificates=certs, as_at=AS_AT)

    assert result.blocked is True
    assert "revoked_required_certificate:insurance" in result.reasons
    assert next(d for d in result.details if d.document_type == "insurance").state == "revoked"


# ── What must NOT refuse ──────────────────────────────────────────────────


def test_valid_certificates_do_not_refuse() -> None:
    result = subcontractor_award_block(_sub(), certificates=_clean_certs(), as_at=AS_AT)

    assert result.blocked is False
    assert result.reasons == []


def test_renewed_after_lapsing_does_not_refuse() -> None:
    """The case a maximum-over-rows reading gets wrong.

    The register holds last year's expired policy and this year's live one. The
    question is per document type, not per row, so the live one answers it.
    """
    certs = [
        _cert("insurance", date(2026, 5, 31)),
        _cert("insurance", date(2027, 5, 31)),
        _cert("license", date(2027, 1, 1)),
    ]

    result = subcontractor_award_block(_sub(), certificates=certs, as_at=AS_AT)

    assert result.blocked is False
    assert result.reasons == []


def test_stale_vendor_row_date_does_not_refuse_when_the_register_is_current() -> None:
    """Two sources, one fact: the register wins when it holds a live document.

    ``insurance_expiry_date`` is a copy, and copies go stale. Blocking on it
    while a current insurance certificate sits in the register would refuse a
    compliant vendor, which is worse than the miss this gate exists to fix.
    """
    result = subcontractor_award_block(
        _sub(insurance_expiry=date(2026, 1, 1)),
        certificates=_clean_certs(),
        as_at=AS_AT,
    )

    assert result.blocked is False
    assert result.reasons == []


def test_expired_non_blocking_document_does_not_refuse() -> None:
    """An expired ISO certificate is a note for the file, not a stop."""
    certs = [*_clean_certs(), _cert("iso", date(2020, 1, 1))]

    result = subcontractor_award_block(_sub(), certificates=certs, as_at=AS_AT)

    assert result.blocked is False
    assert result.reasons == []


def test_null_insurance_date_is_unknown_not_expired() -> None:
    """A legacy row with no date recorded must not be read as a lapse."""
    result = subcontractor_award_block(
        _sub(insurance_expiry=None),
        certificates=_clean_certs(),
        as_at=AS_AT,
    )

    assert result.blocked is False


def test_perpetual_certificate_never_expires() -> None:
    certs = [_cert("insurance", None), _cert("license", None)]

    result = subcontractor_award_block(_sub(), certificates=certs, as_at=date(2099, 1, 1))

    assert result.blocked is False


# ── Missing is not expired ────────────────────────────────────────────────


def test_missing_document_is_reported_but_does_not_refuse_the_award() -> None:
    """A vendor onboarded before their paperwork arrives is the ordinary case.

    Blocking it would stop every new supplier on day one, and a gate that stops
    everyone is a gate that gets switched off. The payment gate is the stricter
    one and still refuses a missing document.
    """
    result = subcontractor_award_block(_sub(), certificates=[], as_at=AS_AT)

    assert result.blocked is False
    assert result.reasons == []
    assert len(result.details) == 2
    assert {d.document_type for d in result.details} == {"insurance", "license"}
    assert {d.state for d in result.details} == {"missing"}
    assert all(d.lapsed_on is None for d in result.details)


def test_missing_and_expired_are_different_findings() -> None:
    certs = [_cert("insurance", date(2026, 5, 31))]

    result = subcontractor_award_block(_sub(), certificates=certs, as_at=AS_AT)

    assert len(result.details) == 2
    by_type = {d.document_type: d for d in result.details}
    assert by_type["insurance"].state == "expired"
    assert by_type["license"].state == "missing"
    # Only the lapse blocks; the gap is recorded.
    assert result.reasons == ["expired_required_certificate:insurance:2026-05-31"]


# ── The boundary, from both sides of midnight ─────────────────────────────


@pytest.mark.parametrize(
    ("as_at", "expect_blocked"),
    [
        (date(2026, 6, 29), False),  # the day before
        (date(2026, 6, 30), False),  # the expiry day itself - still valid
        (date(2026, 7, 1), True),  # the day after
    ],
)
def test_expiry_day_boundary(as_at: date, expect_blocked: bool) -> None:
    """Expires on the 30th means valid on the 30th, refused from the 1st.

    The inclusive reading is the one every other reader of
    ``Certificate.valid_until`` in this module already uses; two gates
    disagreeing about the same day on the same column would be a worse bug than
    either choice being wrong.
    """
    certs = [_cert("insurance", date(2026, 6, 30)), _cert("license", date(2027, 1, 1))]

    result = subcontractor_award_block(_sub(), certificates=certs, as_at=as_at)

    assert result.blocked is expect_blocked


def test_vendor_row_date_boundary_matches_the_certificate_boundary() -> None:
    """The backstop reads the same boundary as the register it backs up."""
    on_the_day = subcontractor_award_block(
        _sub(insurance_expiry=date(2026, 6, 30)),
        certificates=[_cert("license", date(2027, 1, 1))],
        as_at=date(2026, 6, 30),
    )
    day_after = subcontractor_award_block(
        _sub(insurance_expiry=date(2026, 6, 30)),
        certificates=[_cert("license", date(2027, 1, 1))],
        as_at=date(2026, 7, 1),
    )

    assert on_the_day.blocked is False
    assert day_after.blocked is True


# ── The gate is not the only axis, and the axes are reported together ─────


def test_administrative_block_and_expiry_are_both_reported() -> None:
    """Clearing the first reason must not simply reveal the second."""
    certs = [_cert("insurance", date(2026, 5, 31)), _cert("license", date(2027, 1, 1))]

    result = subcontractor_award_block(
        _sub(blocked=True, prequal="rejected"),
        certificates=certs,
        as_at=AS_AT,
    )

    assert result.reasons == [
        "subcontractor_blocked",
        "prequalification_rejected",
        "expired_required_certificate:insurance:2026-05-31",
    ]


# ── The shared evaluator the payment gate also uses ───────────────────────


def test_evaluator_reports_one_finding_per_type_not_per_row() -> None:
    """Three lapsed insurance policies are one problem, not three."""
    certs = [
        _cert("insurance", date(2024, 1, 1)),
        _cert("insurance", date(2025, 1, 1)),
        _cert("insurance", date(2026, 1, 1)),
        _cert("license", date(2027, 1, 1)),
    ]

    findings = evaluate_required_certificates(certs, as_at=AS_AT)

    assert len(findings) == 1
    # The most recent lapse is the one worth quoting back at the counterparty.
    assert findings[0].lapsed_on == date(2026, 1, 1)


def test_evaluator_prefers_expired_over_revoked_when_both_apply() -> None:
    """A lapse names an action the counterparty can take; a revocation does not."""
    certs = [
        _cert("insurance", date(2027, 1, 1), revoked=True),
        _cert("insurance", date(2026, 3, 31)),
        _cert("license", date(2027, 1, 1)),
    ]

    findings = evaluate_required_certificates(certs, as_at=AS_AT)

    assert [f.state for f in findings] == ["expired"]
    assert findings[0].lapsed_on == date(2026, 3, 31)


def test_evaluator_ignores_types_nobody_requires() -> None:
    findings = evaluate_required_certificates(
        [*_clean_certs(), _cert("bond", date(2001, 1, 1))],
        as_at=AS_AT,
    )

    assert findings == []
