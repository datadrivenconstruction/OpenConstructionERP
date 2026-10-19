"""The invoice mentions mechanism is country-neutral: rows are data, one validator serves all."""

from __future__ import annotations

import pytest

from app.modules.einvoice_clearance import mentions as m

CAT = {
    "phase_by_size": {"XX": {"sizes": {"large": "2026-09-01", "small": "2027-09-01"}}},
    "mentions": [
        {
            "key": "xx_tax_id",
            "country": "XX",
            "label": "Issuer tax id",
            "document_kinds": ["invoice"],
            "dated_by": "issuer_phase",
            "when": [],
            "satisfied_by": [[{"path": "seller.tax_id", "present": True}]],
            "legal_basis": "Test Act s.1",
            "source_url": "https://example.test/act",
            "needs_expert_review": False,
        },
        {
            "key": "xx_category",
            "country": "XX",
            "label": "Operation category",
            "document_kinds": ["invoice", "credit_note"],
            "dated_by": "fixed",
            "effective_date": "2026-01-01",
            "when": [{"path": "settings.regime", "equals": "standard"}],
            "satisfied_by": [
                [{"path": "category", "in": ["goods", "services", "both"]}],
                [{"path": "exempt", "truthy": True}],
            ],
            "legal_basis": "Test Act s.2",
            "source_url": "https://example.test/act2",
            "needs_expert_review": True,
        },
    ],
}


def _run(**kw):
    base = {"country": "xx", "document_kind": "invoice", "issue_date": "2026-10-01", "facts": {}, "catalogue": CAT}
    base.update(kw)
    return m.check_mentions(**base)


def test_shipped_catalogue_loads_and_rows_are_complete():
    cat = m.load_catalogue()
    needed = {
        "key",
        "country",
        "label",
        "document_kinds",
        "dated_by",
        "when",
        "satisfied_by",
        "legal_basis",
        "source_url",
    }
    for row in cat["mentions"]:
        assert needed <= set(row)
        assert row["dated_by"] in m.DATED_BY
    assert _run(catalogue={"mentions": []}) == []


def test_issuer_phase_date_by_size_and_assumption():
    assert m.issuer_phase_date("XX", "Small", catalogue=CAT) == ("2027-09-01", False)
    assert m.issuer_phase_date("xx", None, catalogue=CAT) == ("2026-09-01", True)
    assert m.issuer_phase_date("YY", "large", catalogue=CAT) == (None, False)


def test_row_silent_before_its_date():
    assert _run(issue_date="2026-08-31", company_size="large") == []


def test_unknown_size_warns_and_asks_for_the_size():
    row, ask = _run()
    assert row.key == "xx_tax_id" and row.size_assumed and row.severity == m.SEVERITY_WARNING
    assert ask.key == m.KEY_COMPANY_SIZE and ask.severity == m.SEVERITY_WARNING
    assert ask.params == {"waves": {"large": "2026-09-01", "small": "2027-09-01"}}
    assert _run(company_size="large")[0].severity == m.SEVERITY_ERROR


def test_small_issuer_not_yet_bound():
    assert _run(company_size="small") == []


def test_present_mention_satisfies():
    assert _run(facts={"seller": {"tax_id": "123"}}, company_size="large") == []


def test_review_row_is_warning_and_when_clause_gates():
    facts = {"seller": {"tax_id": "1"}, "settings": {"regime": "standard"}}
    (f,) = _run(facts=facts, company_size="large")
    assert f.key == "xx_category" and f.severity == m.SEVERITY_WARNING and f.needs_expert_review
    assert f.missing == ("category",)
    assert _run(facts={"seller": {"tax_id": "1"}, "settings": {"regime": "other"}}, company_size="large") == []


def test_any_alternative_satisfies():
    base = {"seller": {"tax_id": "1"}, "settings": {"regime": "standard"}}
    assert _run(facts={**base, "category": "goods"}, company_size="large") == []
    assert _run(facts={**base, "exempt": "yes"}, company_size="large") == []
    assert _run(facts={**base, "exempt": "false"}, company_size="large") != []


def test_document_kind_and_country_filter():
    assert _run(document_kind="quote", company_size="large") == []
    assert _run(country="YY", company_size="large") == []


def test_clause_without_a_test_is_rejected():
    with pytest.raises(ValueError):
        m._clause_holds({"path": "a"}, {})


def test_facts_from_context():
    facts = m.facts_from_context({"country_fields": {"a": 1}}, {"settings": {"k": "v"}})
    assert facts == {"a": 1, "settings": {"k": "v"}}
    assert m.facts_from_context({}, {}) == {"settings": {}}
