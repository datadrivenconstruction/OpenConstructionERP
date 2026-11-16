# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mandatory invoice content: the EN 16931 minimum in core, country notes from packs."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.doc_templates.legal import _parse, legal_blocks_for_editor, legal_notes, requirements_for
from app.core.doc_templates.registry import DocumentKind
from app.core.doc_templates.rules import LEGAL_DATA_MISSING, check_mandatory, has_errors
from app.core.doc_templates.standards import EN16931_INVOICE_MINIMUM

_DE_FILE = (
    Path(__file__).resolve().parents[3]
    / "packs"
    / "germany-de"
    / "src"
    / "openconstructionerp_germany_de"
    / "document_requirements.json"
)

INVOICE = DocumentKind(
    key="finance.invoice",
    channel="pdf",
    module="finance",
    label="Invoice",
    blocks=("title", "intro", "terms", "closing", "footer"),
    fields=(),
    defaults=lambda _lang: {"title": "Invoice"},
    mandatory=EN16931_INVOICE_MINIMUM,
)

COMPLETE = {
    "doc.number": "RE-2026-0042",
    "doc.date": "16.11.2026",
    "doc.currency": "EUR",
    "doc.supply_date": "30.10.2026",
    "entity.legal_name": "Muster Hochbau GmbH",
    "entity.address": "Hauptstr. 1, 10115 Berlin",
    "entity.vat_id": "DE123456789",
    "entity.tax_id": "DE123456789",
    "recipient.name": "Bau AG",
    "recipient.address": "Ring 5, 80331 München",
    "doc.total_net": "10.000,00 €",
    "doc.total_vat": "1.900,00 €",
    "doc.total_gross": "11.900,00 €",
}


def _de() -> list:
    return _parse(json.loads(_DE_FILE.read_text(encoding="utf-8")), "DE")


class TestEn16931Minimum:
    def test_complete_invoice_passes(self) -> None:
        assert check_mandatory(INVOICE, COMPLETE) == []

    def test_missing_seller_tax_id_blocks_issue(self) -> None:
        values = {k: v for k, v in COMPLETE.items() if not k.startswith("entity.vat") and k != "entity.tax_id"}
        issues = check_mandatory(INVOICE, values)
        assert [i.rule_id for i in issues] == [LEGAL_DATA_MISSING]
        assert issues[0].params["source"] == "EN 16931"
        assert has_errors(issues)

    def test_tax_number_alone_satisfies_seller_tax_id(self) -> None:
        values = {k: v for k, v in COMPLETE.items() if k != "entity.vat_id"} | {"entity.tax_number": "27/123/45678"}
        assert check_mandatory(INVOICE, values) == []

    def test_each_missing_total_is_reported(self) -> None:
        values = {k: v for k, v in COMPLETE.items() if not k.startswith("doc.total")}
        assert len(check_mandatory(INVOICE, values)) == 3

    def test_kind_without_mandatory_fields_never_complains(self) -> None:
        letter = DocumentKind("t.l", "pdf", "m", "Letter", ("title",), (), lambda _l: {"title": "x"})
        assert check_mandatory(letter, {}) == []


class TestGermanPack:
    def test_pack_file_parses_and_targets_invoices(self) -> None:
        reqs = _de()
        assert reqs and {r.kind for r in reqs} == {"finance.invoice"}
        assert all(r.country == "DE" and r.source for r in reqs)

    def test_supply_date_and_seller_tax_id_always_apply(self) -> None:
        notes, issues = legal_notes("finance.invoice", ["DE"], COMPLETE, "de", extra=_de())
        assert issues == []
        texts = " ".join(n.text for n in notes)
        assert "30.10.2026" in texts and "DE123456789" in texts
        assert "13b" not in texts

    def test_reverse_charge_note_only_when_flagged(self) -> None:
        notes, _ = legal_notes("finance.invoice", ["DE"], COMPLETE | {"doc.reverse_charge": "1"}, "de", extra=_de())
        assert any("§ 13b UStG" in n.text for n in notes)

    def test_missing_seller_tax_id_is_a_legal_error(self) -> None:
        values = {k: v for k, v in COMPLETE.items() if k not in ("entity.vat_id", "entity.tax_id")}
        _, issues = legal_notes("finance.invoice", ["DE"], values, "de", extra=_de())
        assert [i.rule_id for i in issues] == [LEGAL_DATA_MISSING]
        assert issues[0].params["country"] == "DE"

    def test_other_markets_get_no_german_blocks(self) -> None:
        assert requirements_for("finance.invoice", ["FR"], extra=_de()) == []
        assert requirements_for("finance.invoice", [], extra=_de()) == []

    def test_editor_shows_locked_blocks_with_their_source(self) -> None:
        blocks = legal_blocks_for_editor("finance.invoice", ["DE"], "de", extra=_de())
        assert blocks and all(b["source"].startswith("UStG") and b["text"] for b in blocks)
