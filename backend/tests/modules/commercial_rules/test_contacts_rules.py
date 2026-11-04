"""The ``contacts`` rule set: each rule fires, a valid record passes, writes are gated."""

from __future__ import annotations

import io
import uuid

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.contacts.validators import (
    CONTACTS_RULE_SET,
    ContactIdentityRule,
    ContactPaymentTermsRule,
    ContactPrequalificationCurrentRule,
    ContactQualifiedUntilRule,
    ContactVatCountryRule,
    register_contacts_validation_rules,
)

TODAY = "2026-11-04"


def _c(**kw):
    base = {
        "id": "c1",
        "contact_type": "supplier",
        "company_name": "Acme Bau GmbH",
        "vat_number": "DE123456789",
        "country_code": "DE",
        "prequalification_status": "approved",
        "qualified_until": "2027-03-31",
        "payment_terms_days": "30",
    }
    base.update(kw)
    return base


async def _run(rule, contact, locale="en"):
    context = ValidationContext(data={"contact": contact}, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(context)


CASES = [
    (ContactIdentityRule, _c(company_name=None), "contacts.identity_present", Severity.ERROR),
    (ContactQualifiedUntilRule, _c(qualified_until="2027-02-31"), "contacts.qualified_until_valid", Severity.ERROR),
    (ContactPaymentTermsRule, _c(payment_terms_days="ninety"), "contacts.payment_terms_valid", Severity.ERROR),
    (ContactPaymentTermsRule, _c(payment_terms_days="400"), "contacts.payment_terms_valid", Severity.ERROR),
    (
        ContactPrequalificationCurrentRule,
        _c(qualified_until="2026-06-30"),
        "contacts.prequalification_current",
        Severity.WARNING,
    ),
    (ContactVatCountryRule, _c(vat_number="FR12345678901"), "contacts.vat_matches_country", Severity.WARNING),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "bad", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, bad, rule_id, severity):
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, _c()))


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(ContactPaymentTermsRule, _c(payment_terms_days="x"), "de") if not r.passed]
    assert "Zahlungsfrist" in failed[0].message


@pytest.mark.asyncio
async def test_greek_vat_prefix_and_blank_optional_fields_pass():
    assert all(r.passed for r in await _run(ContactVatCountryRule, _c(vat_number="EL123456789", country_code="GR")))
    blank = _c(vat_number=None, qualified_until="", payment_terms_days=None, prequalification_status=None)
    for rule in (
        ContactVatCountryRule,
        ContactQualifiedUntilRule,
        ContactPaymentTermsRule,
        ContactPrequalificationCurrentRule,
    ):
        assert all(r.passed for r in await _run(rule, blank))


def test_rule_set_is_registered():
    register_contacts_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([CONTACTS_RULE_SET])}) == 5


def _body(**over):
    body = {"contact_type": "supplier", "company_name": f"Acme {uuid.uuid4().hex[:6]}"}
    body.update(over)
    return body


def _codes(resp):
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


@pytest.mark.asyncio
async def test_blocking_rule_rejects_api_create_with_code(client, admin_auth):
    _, h = admin_auth
    r = await client.post("/api/v1/contacts/", json=_body(payment_terms_days="ninety"), headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "contact_rules_failed"
    assert _codes(r) == {"contacts.payment_terms_valid"}
    r = await client.post("/api/v1/contacts/", json={"contact_type": "supplier"}, headers=h)
    assert r.status_code == 422
    assert _codes(r) == {"contacts.identity_present"}


@pytest.mark.asyncio
async def test_valid_contact_is_created_clean_and_warnings_are_reported(client, admin_auth):
    _, h = admin_auth
    ok = await client.post("/api/v1/contacts/", json=_body(vat_number="DE123456789", country_code="DE"), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []
    warn = await client.post(
        "/api/v1/contacts/",
        json=_body(
            vat_number="FR12345678901",
            country_code="DE",
            prequalification_status="approved",
            qualified_until="2020-01-01",
        ),
        headers=h,
    )
    assert warn.status_code == 201, warn.text
    assert {w["rule_id"] for w in warn.json()["validation_warnings"]} == {
        "contacts.vat_matches_country",
        "contacts.prequalification_current",
    }


@pytest.mark.asyncio
async def test_update_blocks_an_introduced_error_and_keeps_the_stored_record(client, admin_auth):
    _, h = admin_auth
    made = (await client.post("/api/v1/contacts/", json=_body(payment_terms_days="30"), headers=h)).json()
    bad = await client.patch(f"/api/v1/contacts/{made['id']}", json={"payment_terms_days": "x"}, headers=h)
    assert bad.status_code == 422
    assert _codes(bad) == {"contacts.payment_terms_valid"}
    assert (await client.get(f"/api/v1/contacts/{made['id']}", headers=h)).json()["payment_terms_days"] == "30"
    good = await client.patch(f"/api/v1/contacts/{made['id']}", json={"payment_terms_days": "45"}, headers=h)
    assert good.status_code == 200 and good.json()["payment_terms_days"] == "45"


@pytest.mark.asyncio
async def test_legacy_record_with_a_violation_stays_editable(client, admin_auth):
    _, h = admin_auth
    made = (await client.post("/api/v1/contacts/", json=_body(), headers=h)).json()
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.contacts.models import Contact

    async with async_session_factory() as s:
        await s.execute(
            update(Contact).where(Contact.id == uuid.UUID(made["id"])).values(payment_terms_days="net thirty")
        )
        await s.commit()
    ok = await client.patch(f"/api/v1/contacts/{made['id']}", json={"notes": "called on site"}, headers=h)
    assert ok.status_code == 200, ok.text
    other = await client.patch(f"/api/v1/contacts/{made['id']}", json={"qualified_until": "2027-13-45"}, headers=h)
    assert other.status_code == 422 and _codes(other) == {"contacts.qualified_until_valid"}


@pytest.mark.asyncio
async def test_file_import_rejects_the_violating_row_and_names_the_rule(client, admin_auth):
    _, h = admin_auth
    tag = uuid.uuid4().hex[:6]
    csv = f"company,type,payment_terms\nBad {tag},supplier,abc\nGood {tag},supplier,30\n".encode()
    r = await client.post(
        "/api/v1/contacts/import/file/", files={"file": ("c.csv", io.BytesIO(csv), "text/csv")}, headers=h
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 1
    assert body["errors"][0]["rules"] == ["contacts.payment_terms_valid"]
