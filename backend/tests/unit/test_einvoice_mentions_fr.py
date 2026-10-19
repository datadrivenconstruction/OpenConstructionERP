"""French rows of the invoice mentions catalogue and the rules that read them."""

from __future__ import annotations

import asyncio

from app.core.validation.engine import ValidationContext
from app.modules.einvoice_clearance import mentions as m
from app.modules.einvoice_clearance.validators import InvoiceMentionsRequired, InvoiceMentionsUnconfirmed

GOOD = {"customer_siren": "552100554", "operation_category": "services"}


def _keys(**kw):
    base = {"country": "FR", "document_kind": "invoice", "issue_date": "2026-09-15", "facts": {"settings": {}}}
    base.update(kw)
    return {f.key for f in m.check_mentions(**base)}


def test_every_fr_row_is_sourced_and_dated():
    cat = m.load_catalogue()
    rows = [r for r in cat["mentions"] if r["country"] == "FR"]
    assert len(rows) == 5
    for r in rows:
        assert r["legal_basis"] and r["source_url"].startswith("https://")
        assert r["dated_by"] in m.DATED_BY
        if r["dated_by"] == m.DATED_BY_FIXED and not r.get("effective_date"):
            assert r["needs_expert_review"]
    sizes = cat["phase_by_size"]["FR"]["sizes"]
    assert sizes == {"ge": "2026-09-01", "eti": "2026-09-01", "pme": "2027-09-01", "micro": "2027-09-01"}


def test_large_issuer_bound_from_september_2026():
    assert _keys(company_size="eti") == {"fr_customer_siren", "fr_operation_category", "fr_professional_insurance"}
    assert _keys(company_size="eti", issue_date="2026-08-31") == {"fr_professional_insurance"}


def test_sme_bound_only_from_september_2027():
    assert "fr_customer_siren" not in _keys(company_size="pme")
    assert "fr_customer_siren" in _keys(company_size="pme", issue_date="2027-09-01")


def test_unknown_size_assumes_earliest_wave():
    (f,) = [
        x
        for x in m.check_mentions(
            country="FR", document_kind="invoice", issue_date="2026-10-01", facts={"settings": {}}
        )
        if x.key == "fr_customer_siren"
    ]
    assert f.size_assumed


def test_delivery_address_only_when_it_differs():
    facts = {**GOOD, "settings": {}}
    assert "fr_delivery_address" not in _keys(company_size="eti", facts=facts)
    facts["delivery_differs"] = True
    assert "fr_delivery_address" in _keys(company_size="eti", facts=facts)
    facts["delivery_address"] = "1 rue X, Lyon"
    assert "fr_delivery_address" not in _keys(company_size="eti", facts=facts)


def test_vat_on_debits_mention_follows_the_option():
    facts = {**GOOD, "settings": {"vat_on_debits_option": True}}
    assert "fr_vat_on_debits" in _keys(company_size="eti", facts=facts)
    facts["vat_on_debits_mention"] = "Option pour le paiement de la taxe d'apres les debits"
    assert "fr_vat_on_debits" not in _keys(company_size="eti", facts=facts)


def test_consumer_and_cross_border_sales_are_out_of_scope():
    for scope in ("b2c", "cross_border"):
        keys = _keys(company_size="eti", facts={"transaction_scope": scope, "settings": {}})
        assert not keys & {"fr_customer_siren", "fr_operation_category"}


def _ctx(document, settings=None):
    return ValidationContext(
        data={
            "document": {"invoice_date": "2026-10-01", **document},
            "profile": {"country": "FR", "settings": {"company_size": "eti", **(settings or {})}},
            "regime": {"country": "FR"},
        }
    )


def test_rules_split_blocking_from_advisory():
    ctx = _ctx({"country_fields": {}})
    blocking = asyncio.run(InvoiceMentionsRequired().validate(ctx))
    advisory = asyncio.run(InvoiceMentionsUnconfirmed().validate(ctx))
    assert {r.details["key"] for r in blocking if not r.passed} == {"fr_customer_siren", "fr_operation_category"}
    assert [r.details["key"] for r in advisory if not r.passed] == ["fr_professional_insurance"]
    ok = _ctx({"country_fields": {**GOOD, "insurance_mention": "Insurer X"}})
    assert all(r.passed for r in asyncio.run(InvoiceMentionsRequired().validate(ok)))
    assert all(r.passed for r in asyncio.run(InvoiceMentionsUnconfirmed().validate(ok)))


def test_other_country_is_untouched():
    ctx = ValidationContext(
        data={"document": {"invoice_date": "2026-10-01"}, "profile": {"country": "DE"}, "regime": {"country": "DE"}}
    )
    assert all(r.passed for r in asyncio.run(InvoiceMentionsRequired().validate(ctx)))
