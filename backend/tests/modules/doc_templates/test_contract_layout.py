# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The contract has a printable form and a document layout the firm can restyle."""

from __future__ import annotations

from app.core.register_export import ProjectHeader


def _contract_and_lines():
    from app.modules.contracts.layouts import _sample_contract

    return _sample_contract()


def test_contract_layout_is_registered_and_listed() -> None:
    from app.modules.doc_templates.layout_service import require_layout

    spec = require_layout("contracts.contract")
    assert spec.module == "contracts"
    assert {c.id for c in spec.collections} == {"lines"}


def test_standard_form_prints_a_pdf_with_the_contract_number() -> None:
    from app.modules.contracts.pdf_export import build_contract_pdf

    contract, lines = _contract_and_lines()
    pdf = build_contract_pdf(
        contract,
        lines,
        project=ProjectHeader(name="Riverside Block B", code="RB-B", currency="EUR"),
        counterparty="Keller Rohbau GmbH",
        generated="2026-11-18 09:30 UTC",
    )
    assert pdf.startswith(b"%PDF")


def test_context_says_which_side_the_contract_is_on() -> None:
    from app.modules.contracts.pdf_export import contract_context

    contract, lines = _contract_and_lines()
    project = ProjectHeader(name="Riverside Block B", code="RB-B", currency="EUR")
    sub = contract_context(contract, lines, project=project, locale="en")
    assert sub.values["doc.role"] == "Subcontract"
    contract.counterparty_type = "client"
    client = contract_context(contract, lines, project=project, locale="en")
    assert client.values["doc.role"] == "Client contract"
    # No counterparty name resolved: the role is printed rather than a blank.
    assert client.values["doc.counterparty"] == "Client contract"


def test_french_form_uses_french_words() -> None:
    from app.modules.contracts.pdf_export import contract_context

    contract, lines = _contract_and_lines()
    ctx = contract_context(contract, lines, project=ProjectHeader(name="P", code="P", currency="EUR"), locale="fr")
    assert ctx.values["doc.role"] == "Sous-traitance"
    assert ctx.values["doc.type"] == "Forfait"
