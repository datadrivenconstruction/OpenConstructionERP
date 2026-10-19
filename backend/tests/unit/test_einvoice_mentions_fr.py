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


def test_unset_size_warns_instead_of_blocking():
    found = {
        f.key: f
        for f in m.check_mentions(
            country="FR", document_kind="invoice", issue_date="2026-10-01", facts={"settings": {}}
        )
    }
    assert found["fr_customer_siren"].severity == m.SEVERITY_WARNING and found["fr_customer_siren"].size_assumed
    assert found[m.KEY_COMPANY_SIZE].params["waves"]["pme"] == "2027-09-01"
    assert not [f for f in found.values() if f.severity == m.SEVERITY_ERROR]


def test_unset_size_before_any_wave_is_silent():
    assert "company_size" not in _keys(issue_date="2026-08-31")


def test_rule_does_not_block_without_a_size():
    ctx = _ctx({"country_fields": {}}, settings={"company_size": ""})
    assert all(r.passed for r in asyncio.run(InvoiceMentionsRequired().validate(ctx)))
    advisory = [r for r in asyncio.run(InvoiceMentionsUnconfirmed().validate(ctx)) if not r.passed]
    assert "company_size" in {r.details["key"] for r in advisory}


def test_set_size_blocks_ge_and_spares_pme():
    ge = _ctx({"country_fields": {}}, settings={"company_size": "ge"})
    assert any(not r.passed for r in asyncio.run(InvoiceMentionsRequired().validate(ge)))
    pme = _ctx({"country_fields": {}}, settings={"company_size": "pme"})
    assert all(r.passed for r in asyncio.run(InvoiceMentionsRequired().validate(pme)))
    keys = {r.details["key"] for r in asyncio.run(InvoiceMentionsUnconfirmed().validate(pme)) if not r.passed}
    assert keys == {"fr_professional_insurance"}


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


def test_meta_offers_the_mention_inputs_without_making_them_mandatory():
    from app.modules.einvoice_clearance import regimes

    flat = regimes.regime_as_dict(regimes.COUNTRY_REGIMES["FR"])
    assert {"customer_siren", "delivery_differs", "insurance_mention"} <= set(flat["optional_document_fields"])
    assert not set(flat["optional_document_fields"]) & set(flat["document_fields"])
    assert flat["profile_setting_fields"] == ["company_size", "vat_on_debits_option"]
    assert flat["company_sizes"] == ["ge", "eti", "pme", "micro"]
    assert regimes.regime_as_dict(regimes.COUNTRY_REGIMES["DE"])["optional_document_fields"] == []
