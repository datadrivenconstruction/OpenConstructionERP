# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice lifecycle from pack data: the worked examples of the w1-einvoice spec.

Pure functions only (no database): deadlines, cancellation windows, hash chain,
QR, consolidation, the IRP writer, the inbound parser and the mandate loader.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.modules.einvoice_clearance import chain, consolidation, lifecycle, regimes
from app.modules.einvoice_clearance.consolidation import Receipt


def _regime(code: str) -> dict:
    return regimes.regime_as_dict(regimes.COUNTRY_REGIMES[code])


def _ids(findings: list[lifecycle.Finding]) -> list[str]:
    return [f.rule_id for f in findings]


# ── Mandate catalogue is pack data ──────────────────────────────────────────


class TestMandateCatalogue:
    def test_every_file_loads_and_matches_its_name(self) -> None:
        files = sorted(regimes.MANDATES_DIR.glob("*.json"))
        assert len(files) == len(regimes.COUNTRY_REGIMES) >= 27
        for path in files:
            doc = json.loads(path.read_text(encoding="utf-8"))
            assert doc["schema"] == regimes.MANDATE_SCHEMA
            assert path.stem == doc["country"]
            assert doc["markets"] == [doc["country"]]

    def test_malaysia_is_catalogued_from_the_irbm_guideline(self) -> None:
        my = regimes.COUNTRY_REGIMES["MY"]
        assert my.platform == "MyInvois"
        assert my.lifecycle["cancel"] == {**my.lifecycle["cancel"], "within_hours": 72, "from": "validated"}
        rule = my.lifecycle["consolidation"]
        assert rule["due_days_after_period"] == 7
        assert rule["single_transaction_cap"] == "10000"
        assert rule["cap_relief"]["until"] == "2027-12-31"
        assert "hasil.gov.my" in rule["source_url"]

    def test_poland_is_fa3_and_cannot_cancel(self) -> None:
        pl = regimes.COUNTRY_REGIMES["PL"]
        assert pl.document_format == "ksef_fa_3"
        assert pl.lifecycle["cancel"]["allowed"] is False
        assert pl.lifecycle["exemptions"][0]["until"] == "2026-12-31"

    def test_unread_values_are_flagged_for_review(self) -> None:
        india = regimes.COUNTRY_REGIMES["IN"].lifecycle
        assert india["cancel"]["needs_review"] is True
        assert india["deadlines"][0]["needs_review"] is True

    def test_bad_schema_is_refused(self) -> None:
        with pytest.raises(ValueError, match="schema"):
            regimes.regime_from_json({"schema": "x", "country": "ZZ", "regime": {}})


# ── Worked example 1: India late IRN ────────────────────────────────────────

_IN_DOC = {
    "invoice_number": "INV-24-0871",
    "invoice_date": "2025-05-02",
    "status": "validated",
    "total_amount": "2171200",
}
_IN_PROFILE = {"mode": "export", "settings": {"annual_turnover": "520000000"}}


class TestIndiaLateIrn:
    def test_32_days_raises_in_001(self) -> None:
        found = lifecycle.evaluate(
            _regime("IN"), _IN_DOC, profile=_IN_PROFILE, intent="submit", now=datetime(2025, 6, 3, tzinfo=UTC)
        )
        assert "EINV-IN-001" in _ids(found)
        assert lifecycle.blocking(found)[0].rule_id == "EINV-IN-001"

    def test_28_days_passes_without_a_soon_warning(self) -> None:
        found = lifecycle.evaluate(
            _regime("IN"), _IN_DOC, profile=_IN_PROFILE, intent="submit", now=datetime(2025, 5, 30, tzinfo=UTC)
        )
        assert "EINV-IN-001" not in _ids(found)
        assert "EINV-CORE-003" not in _ids(found)
        assert _ids(found) == ["EINV-CORE-006"]

    def test_small_taxpayer_is_not_bound(self) -> None:
        small = {"mode": "sandbox", "settings": {"annual_turnover": "90000000"}}
        found = lifecycle.evaluate(_regime("IN"), _IN_DOC, profile=small, now=datetime(2025, 6, 3, tzinfo=UTC))
        assert found == []

    def test_send_is_not_offered_in_export_mode(self) -> None:
        assert lifecycle.allowed_actions(_regime("IN"), _IN_DOC, _IN_PROFILE) == ["download"]


# ── Worked example 2: Saudi simplified reporting and hash chain ─────────────


class TestSaudiArabia:
    simplified = {
        "invoice_number": "SIM-0001",
        "invoice_date": "2026-03-10T09:00:00",
        "status": "validated",
        "document_kind": "simplified",
        "previous_hash": "abc",
        "total_amount": "5290",
    }

    def test_reporting_due_24_hours_after_issue(self) -> None:
        deadlines = lifecycle.resolve_deadlines(_regime("SA")["lifecycle"], self.simplified)
        assert deadlines[0].due_at == datetime(2026, 3, 11, 9, 0, tzinfo=UTC)

    def test_one_and_a_half_hours_left_warns(self) -> None:
        found = lifecycle.evaluate(_regime("SA"), self.simplified, now=datetime(2026, 3, 11, 7, 30, tzinfo=UTC))
        soon = [f for f in found if f.rule_id == "EINV-CORE-003"]
        assert soon and soon[0].params["n"] == "1.5"
        assert soon[0].severity == "warning"

    def test_standard_invoice_without_previous_hash_breaks_the_chain(self) -> None:
        standard = {
            "invoice_number": "STD-0042",
            "invoice_date": "2026-03-10",
            "status": "draft",
            "document_kind": "standard",
            "total_amount": "1437500",
        }
        found = lifecycle.evaluate(_regime("SA"), standard, now=datetime(2026, 3, 10, 10, tzinfo=UTC))
        assert "EINV-SA-001" in _ids(lifecycle.blocking(found))

    def test_genesis_hash_is_sha256_of_zero(self) -> None:
        genesis = regimes.COUNTRY_REGIMES["SA"].lifecycle["hash_chain"]["genesis"]
        assert base64.b64decode(genesis).decode() == (
            "5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9"
        )
        assert chain.previous_hash_or_genesis("", {"genesis": genesis}) == genesis

    def test_qr_is_tlv_in_tag_order(self) -> None:
        qr = regimes.COUNTRY_REGIMES["SA"].lifecycle["qr"]
        payload = chain.qr_payload(
            qr,
            {
                "seller_name": "Bobs Records",
                "vat_number": "310122393500003",
                "timestamp": "2026-03-10T09:00:00Z",
                "total_with_vat": "5290.00",
                "vat_total": "690.00",
                "invoice_hash": chain.invoice_hash(b"<Invoice/>"),
            },
        )
        records = chain.tlv_decode(base64.b64decode(payload))
        assert [tag for tag, _ in records] == [1, 2, 3, 4, 5, 6]
        assert records[3][1] == "5290.00"

    def test_vat_arithmetic_of_the_fixture(self) -> None:
        assert Decimal("4600") * Decimal("0.15") == Decimal("690.00")
        assert Decimal("1250000") * Decimal("0.15") == Decimal("187500.00")


# ── Worked example 3: Malaysia consolidated ─────────────────────────────────


def _october_receipts() -> list[Receipt]:
    out = [Receipt(f"T{i:03d}", date(2026, 10, 1 + i % 31), Decimal("613.00"), Decimal("49.04")) for i in range(100)]
    out += [Receipt(f"E{i:03d}", date(2026, 10, 1 + i % 31), Decimal("220.00")) for i in range(113)]
    out.append(Receipt("E113", date(2026, 10, 31), Decimal("260.00")))
    return out


_MY_RULE = regimes.COUNTRY_REGIMES["MY"].lifecycle["consolidation"]
_BIG_SELLER = {"annual_turnover": "40000000"}


class TestMalaysiaConsolidated:
    def test_october_totals_and_due_date(self) -> None:
        plan = consolidation.plan(_MY_RULE, _october_receipts(), "2026-10", _BIG_SELLER)
        assert len(plan.included) == 214
        assert plan.excluded == []
        assert plan.net == Decimal("86420.00")
        assert plan.tax == Decimal("4904.00")
        assert plan.total == Decimal("91324.00")
        assert plan.due_date == date(2026, 11, 7)

    def test_receipt_outside_period_raises_core_007(self) -> None:
        receipts = [*_october_receipts(), Receipt("N001", date(2026, 11, 1), Decimal("50.00"))]
        found = consolidation.check(_MY_RULE, receipts, "2026-10", settings=_BIG_SELLER)
        assert _ids(found) == ["EINV-CORE-007"]

    def test_receipt_over_rm_10000_raises_my_002(self) -> None:
        receipts = [*_october_receipts(), Receipt("BIG1", date(2026, 10, 15), Decimal("12400.00"))]
        found = consolidation.check(_MY_RULE, receipts, "2026-10", settings=_BIG_SELLER)
        assert _ids(found) == ["EINV-MY-002"]
        plan = consolidation.plan(_MY_RULE, receipts, "2026-10", _BIG_SELLER)
        assert [(r.number, why) for r, why in plan.excluded] == [("BIG1", consolidation.REASON_OVER_CAP)]

    def test_phase_four_seller_is_relieved_until_2027(self) -> None:
        receipts = [Receipt("BIG1", date(2026, 10, 15), Decimal("12400.00"))]
        small = {"annual_turnover": "4000000"}
        assert consolidation.check(_MY_RULE, receipts, "2026-10", settings=small) == []

    def test_late_consolidation_raises_my_001(self) -> None:
        found = consolidation.check(
            _MY_RULE, _october_receipts(), "2026-10", settings=_BIG_SELLER, today=date(2026, 11, 8)
        )
        assert _ids(found) == ["EINV-MY-001"]

    def test_cancel_80_hours_after_validation_is_closed(self) -> None:
        doc = {"status": "cleared", "cleared_at": "2026-11-03T10:00:00+00:00", "invoice_number": "C-2026-10"}
        found = lifecycle.evaluate(_regime("MY"), doc, intent="cancel", now=datetime(2026, 11, 6, 18, tzinfo=UTC))
        assert _ids(found) == ["EINV-CORE-005"]
        ok = lifecycle.evaluate(_regime("MY"), doc, intent="cancel", now=datetime(2026, 11, 5, 10, tzinfo=UTC))
        assert ok == []

    def test_receipts_round_trip_through_country_fields(self) -> None:
        receipts = _october_receipts()[:3]
        fields = {"receipts": consolidation.receipts_to_fields(receipts)}
        assert consolidation.receipts_from_fields(fields) == receipts


# ── Poland and Peppol ───────────────────────────────────────────────────────


def test_poland_offers_only_a_corrective_invoice() -> None:
    doc = {"status": "cleared", "authority_identifier": "123-KSEF"}
    assert lifecycle.allowed_actions(_regime("PL"), doc) == ["correct", "download"]
    found = lifecycle.evaluate(_regime("PL"), doc, intent="cancel")
    assert _ids(found) == ["EINV-CORE-005"]


def test_poland_missing_ksef_number_warns() -> None:
    found = lifecycle.evaluate(_regime("PL"), {"status": "cleared"})
    assert [(f.rule_id, f.severity) for f in found] == [("EINV-PL-001", "warning")]


def test_peppol_send_needs_buyer_participant_id() -> None:
    doc = {"status": "validated", "country_fields": {}}
    sandbox = {"mode": "sandbox"}
    assert _ids(lifecycle.evaluate(_regime("NL"), doc, profile=sandbox, intent="submit")) == ["EINV-PEP-001"]
    assert lifecycle.evaluate(_regime("NL"), doc, intent="submit") == []
    doc["country_fields"] = {"buyer_endpoint_id": "0106:12345678"}
    assert lifecycle.evaluate(_regime("NL"), doc, profile=sandbox, intent="submit") == []


# ── IRP writer ──────────────────────────────────────────────────────────────


def test_irp_document_for_the_india_fixture() -> None:
    from app.modules.einvoice.cii import EInvoice, EInvoiceLine, Party
    from app.modules.einvoice_clearance.irp import build_irp_document

    inv = EInvoice(
        profile="en16931",
        invoice_number="INV-24-0871",
        issue_date="2025-05-02",
        currency="INR",
        seller=Party(name="Seller Infra Pvt Ltd", country_code="IN"),
        buyer=Party(name="Buyer Realty Ltd", country_code="IN"),
        lines=[
            EInvoiceLine(
                line_id="1",
                name="RCC works",
                quantity=Decimal("1"),
                unit="LS",
                net_unit_price=Decimal("1840000"),
                line_net_amount=Decimal("1840000"),
                vat_rate=Decimal("18"),
            )
        ],
        tax_subtotals=[],
        line_total=Decimal("1840000"),
        tax_basis_total=Decimal("1840000"),
        tax_total=Decimal("331200"),
        grand_total=Decimal("2171200"),
        due_payable=Decimal("2171200"),
    )
    body = build_irp_document(
        inv, {"gstin_issuer": "27AAAAA0000A1Z5", "seller_state_code": "27", "place_of_supply": "29"}
    )
    assert body["Version"] == "1.1"
    assert body["DocDtls"] == {"Typ": "INV", "No": "INV-24-0871", "Dt": "02/05/2025"}
    assert body["ValDtls"]["IgstVal"] == 331200.0
    assert body["ValDtls"]["CgstVal"] == 0.0
    assert body["ValDtls"]["TotInvVal"] == 2171200.0


# ── Inbound parser ──────────────────────────────────────────────────────────

_UBL = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
 <cbc:ID>NL-2026-118</cbc:ID><cbc:IssueDate>2026-10-20</cbc:IssueDate>
 <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
 <cac:AccountingSupplierParty><cac:Party><cbc:EndpointID schemeID="0106">12345678</cbc:EndpointID>
  <cac:PartyTaxScheme><cbc:CompanyID>NL123456789B01</cbc:CompanyID></cac:PartyTaxScheme>
  <cac:PartyLegalEntity><cbc:RegistrationName>Steigerbouw BV</cbc:RegistrationName></cac:PartyLegalEntity>
 </cac:Party></cac:AccountingSupplierParty>
 <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">210.00</cbc:TaxAmount></cac:TaxTotal>
 <cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount currencyID="EUR">1000.00</cbc:TaxExclusiveAmount>
 <cbc:TaxInclusiveAmount currencyID="EUR">1210.00</cbc:TaxInclusiveAmount></cac:LegalMonetaryTotal>
</Invoice>"""


def test_inbound_ubl_parses_into_inbox_fields() -> None:
    from app.modules.einvoice.inbound import parse_inbound

    inv = parse_inbound(_UBL)
    assert inv.syntax == "ubl"
    assert inv.findings == []
    assert inv.capture_fields() == {
        "supplier_name": "Steigerbouw BV",
        "supplier_tax_id": "NL123456789B01",
        "invoice_number": "NL-2026-118",
        "invoice_date": "2026-10-20",
        "currency_code": "EUR",
        "amount_net": Decimal("1000.00"),
        "amount_tax": Decimal("210.00"),
        "amount_gross": Decimal("1210.00"),
    }
    assert inv.supplier_endpoint == "0106:12345678"


def test_inbound_flags_totals_that_do_not_reconcile() -> None:
    from app.modules.einvoice.inbound import parse_inbound

    inv = parse_inbound(_UBL.replace(b">1210.00<", b">1300.00<"))
    assert [f["code"] for f in inv.findings] == ["BR-CO-15"]


def test_inbound_refuses_entities_and_other_roots() -> None:
    from app.modules.einvoice.inbound import InboundParseError, parse_inbound

    with pytest.raises(InboundParseError):
        parse_inbound(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')
    with pytest.raises(InboundParseError):
        parse_inbound(b"<Order/>")
