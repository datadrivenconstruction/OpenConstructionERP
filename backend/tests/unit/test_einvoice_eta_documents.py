"""ETA documents: the SDK equations, the builder and the pre-submit rules.

The equations are those of the ETA SDK document reference
(https://sdk.invoicing.eta.gov.eg/documents/invoice-v1-0/ and the calculation
notes linked from it, read 2026-10-19). The SDK's own sample
(``tests/fixtures/eta/one-doc.json``, https://sdk.invoicing.eta.gov.eg/files/)
carries twenty tax types on each line, so every equation is exercised against
figures ETA itself published.
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.einvoice_clearance import validators as clearance_validators
from app.modules.einvoice_eta import builder, calculation, checks, codes, validators

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "eta"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
RIN = "100000001"

SETTINGS: dict[str, Any] = {
    "activity_code": "4100",
    "issuer": {
        "name": "Nile Build SAE",
        "address": {
            "branchID": "0",
            "country": "EG",
            "governate": "Cairo",
            "regionCity": "Nasr City",
            "street": "Abbas El Akkad",
            "buildingNumber": "12",
        },
    },
    "default_item": {"itemType": "EGS", "itemCode": "EG-100000001-1001", "unitType": "EA"},
}
# The buyer as finance.einvoice_parties resolves it for an invoice.
BUYER: dict[str, Any] = {
    "name": "Delta Developments",
    "country_code": "EG",
    "vat_id": "200000001",
    "line1": "Tahrir Street",
    "city": "Giza",
    "district": "Dokki",
    "building_number": "3",
}
INVOICE = {
    "invoice_number": "INV-1",
    "invoice_date": "2026-10-18",
    "currency_code": "EGP",
    "amount_subtotal": "1000.00",
    "tax_amount": "140.00",
}
LINES = [
    {"description": "Concrete C30", "quantity": "10", "unit": "m3", "unit_rate": "75.50", "vat_rate": "14"},
    {"description": "Formwork", "quantity": "2.5", "unit": "m2", "unit_rate": "98", "vat_rate": "14"},
]


def _build(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "invoice": INVOICE,
        "lines": LINES,
        "rin": RIN,
        "settings": SETTINGS,
        "eta_fields": {},
        "buyer": BUYER,
    }
    kwargs.update(overrides)
    return builder.build_document(builder.build_input_from_invoice(**kwargs))


def _text(doc: dict[str, Any]) -> str:
    return builder.to_json_text(doc)


def _codes(text: str) -> set[str]:
    return {issue.code for issue in checks.check_eta_document(text, profile_rin=RIN, now=NOW)}


# Until the shared Egyptian RIN check is installed, every document carries this
# one advisory note and nothing else may be expected of a clean document.
UNCHECKED = {"rin_format_unchecked"}


def _sdk_doc() -> dict[str, Any]:
    return json.loads((FIXTURES / "one-doc.json").read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)


# ── Equations ────────────────────────────────────────────────────────────────


class TestEquations:
    def test_the_sdk_sample_satisfies_every_equation(self):
        assert calculation.check_document(_sdk_doc()) == []

    def test_one_unit_in_the_last_place_is_tolerated(self):
        # Decision D9 in docs/design/egypt/eta.md: ETA publishes no tolerance
        # and its own sample is rounded to 2 places.
        doc = _sdk_doc()
        doc["invoiceLines"][0]["total"] += Decimal("0.01")
        assert calculation.check_document(doc) == []

    def test_a_line_total_off_by_two_cents_is_found_with_its_path(self):
        doc = _sdk_doc()
        doc["invoiceLines"][0]["total"] += Decimal("0.02")
        broken = calculation.check_document(doc)
        assert [(b.path, b.field) for b in broken][:1] == [("invoiceLines[0]", "total")]
        assert "invoiceLines[0]" in broken[0].message()

    def test_a_vat_amount_computed_on_the_wrong_base_is_found(self):
        doc = _sdk_doc()
        t1 = next(t for t in doc["invoiceLines"][0]["taxableItems"] if t["taxType"] == "T1")
        t1["amount"] = t1["rate"] * doc["invoiceLines"][0]["netTotal"] / 100  # VAT on net only
        fields = {(b.path, b.field) for b in calculation.check_document(doc)}
        assert any(field.startswith("taxableItems") or "T1" in field for _path, field in fields)

    def test_a_document_total_that_ignores_the_extra_discount_is_found(self):
        doc = _sdk_doc()
        doc["totalAmount"] += doc["extraDiscountAmount"] + Decimal("1")
        assert any(b.field == "totalAmount" for b in calculation.check_document(doc))

    def test_vat_is_charged_on_net_plus_taxable_fees_and_table_tax(self):
        line = calculation.compute_line(
            calculation.LineFigures(
                quantity=Decimal("2"),
                unit_amount_egp=Decimal("100"),
                discount_rate=Decimal("10"),
                taxes=(
                    calculation.TaxInput("T1", "V009", Decimal("14")),
                    calculation.TaxInput("T2", "Tbl01", Decimal("5")),
                    calculation.TaxInput("T5", "ST01", Decimal("1")),
                    calculation.TaxInput("T4", "W001", Decimal("1")),
                ),
            )
        )
        # sales 200, discount 20, net 180, T5 1% of net = 1.8
        # T2 = 5% x (180 + 1.8) = 9.09; T1 = 14% x (180 + 1.8 + 9.09) = 26.7246
        # T4 = 1% x (180 - 0) = 1.8; total = 180 + 26.7246 + 9.09 + 1.8 - 1.8
        assert line.net_total == Decimal("180.00000")
        assert line.total_taxable_fees == Decimal("1.80000")
        amounts = {t.tax_type: t.amount for t in line.taxes}
        assert amounts == {
            "T1": Decimal("26.72460"),
            "T2": Decimal("9.09000"),
            "T5": Decimal("1.80000"),
            "T4": Decimal("1.80000"),
        }
        assert line.total == Decimal("215.81460")

    def test_fixed_amount_types_take_the_amount_not_a_rate(self):
        line = calculation.compute_line(
            calculation.LineFigures(
                quantity=Decimal("1"),
                unit_amount_egp=Decimal("100"),
                taxes=(calculation.TaxInput("T3", "Tbl02", None, Decimal("7.5")),),
            )
        )
        assert line.taxes[0].amount == Decimal("7.50000")
        assert line.total == Decimal("107.50000")

    def test_amounts_round_half_up_to_five_places(self):
        assert calculation.round5(Decimal("0.000005")) == Decimal("0.00001")
        assert calculation.round5(Decimal("0.0000049")) == Decimal("0.00000")


# ── Codes ────────────────────────────────────────────────────────────────────


class TestCodeTables:
    def test_withholding_subtypes_w001_to_w016_belong_to_t4(self):
        parents = codes.tax_subtypes()
        assert all(parents[f"W{n:03d}"] == "T4" for n in range(1, 17))

    def test_every_tax_type_t1_to_t20_is_known(self):
        known = set(codes.tax_types())
        assert {f"T{n}" for n in range(1, 21)} <= known

    def test_reviewed_mappings_carry_the_expert_review_flag(self):
        assert codes.UNIT_MAP.needs_expert_review
        assert codes.VAT_CATEGORY_SUBTYPES.needs_expert_review

    def test_only_mapped_units_translate(self):
        assert codes.eta_unit_for("m3") == "MTQ"
        assert codes.eta_unit_for("no such unit") == ""


# ── Builder ──────────────────────────────────────────────────────────────────


class TestBuilder:
    def test_a_14_percent_invoice_builds_a_document_with_no_findings(self):
        doc = _build()
        assert doc["documentType"] == "i"
        assert doc["documentTypeVersion"] == "1.0"
        assert doc["totalAmount"] == Decimal("1140.00000")
        assert [t["amount"] for t in doc["taxTotals"]] == [Decimal("140.00000")]
        assert doc["invoiceLines"][0]["unitType"] == "MTQ"
        assert doc["invoiceLines"][0]["taxableItems"][0]["subType"] == "V009"
        text = _text(doc)
        assert _codes(text) <= UNCHECKED
        # What the builder writes, the equations accept at full precision.
        assert calculation.check_document(checks.parse_document(text)[0]) == []

    def test_numbers_are_written_as_plain_decimals(self):
        text = _text(_build())
        assert '"totalAmount": 1140.00000' in text
        assert '"totalTaxableFees": 0.00000' in text
        assert "E" not in text.split('"invoiceLines"')[1].split('"description"')[0]

    def test_member_order_follows_the_sdk_sample(self):
        keys = list(_build())
        assert keys[:3] == ["issuer", "receiver", "documentType"]
        assert keys.index("invoiceLines") < keys.index("totalSalesAmount")

    def test_a_credit_note_carries_its_references(self):
        doc = _build(eta_fields={"document_type": "c", "references": ["EKV0TCMYB5CMSC0AV38AR8YF10"]})
        assert doc["documentType"] == "c"
        assert doc["references"] == ["EKV0TCMYB5CMSC0AV38AR8YF10"]
        assert "no_references" not in _codes(_text(doc))

    def test_a_credit_note_without_references_is_refused_before_sending(self):
        doc = _build(eta_fields={"document_type": "c"})
        assert "no_references" in _codes(_text(doc))

    def test_a_usd_invoice_converts_with_the_exchange_rate(self):
        doc = _build(invoice={**INVOICE, "currency_code": "USD"}, eta_fields={"exchange_rate": "48.25"})
        unit = doc["invoiceLines"][0]["unitValue"]
        assert unit["currencySold"] == "USD"
        assert unit["amountSold"] == Decimal("75.50000")
        assert unit["currencyExchangeRate"] == Decimal("48.25000")
        assert unit["amountEGP"] == Decimal("3642.87500")
        assert _codes(_text(doc)) <= UNCHECKED

    def test_a_usd_invoice_without_a_rate_is_refused_by_name(self):
        with pytest.raises(builder.EtaBuildError, match="exchange rate"):
            _build(invoice={**INVOICE, "currency_code": "USD"})

    def test_a_zero_rated_line_needs_a_stated_reason(self):
        lines = [{**LINES[0], "vat_rate": "0", "vat_category": "Z"}]
        with pytest.raises(builder.EtaBuildError, match="vat_subtype"):
            _build(lines=lines, invoice={**INVOICE, "tax_amount": "0"})
        doc = _build(
            lines=lines,
            invoice={**INVOICE, "tax_amount": "0"},
            eta_fields={"lines": [{"vat_subtype": "V001"}]},
        )
        assert doc["invoiceLines"][0]["taxableItems"][0]["subType"] == "V001"

    def test_a_buyer_outside_egypt_is_a_foreign_receiver(self):
        party = builder.receiver_from_buyer({**BUYER, "country_code": "DE"})
        assert party.type == "F"
        person = builder.receiver_from_buyer({**BUYER, "first_name": "Mona", "vat_id": ""})
        assert person.type == "P"

    def test_line_overrides_replace_the_default_item_code(self):
        doc = _build(eta_fields={"lines": [{"itemType": "GS1", "itemCode": "10003752"}]})
        assert doc["invoiceLines"][0]["itemType"] == "GS1"
        assert doc["invoiceLines"][1]["itemType"] == "EGS"


# ── Checks ───────────────────────────────────────────────────────────────────


class TestChecks:
    def test_missing_rin_is_named(self):
        doc = _build(rin="")
        assert "issuer_rin_missing" in _codes(_text(doc))

    def test_an_issuer_other_than_the_registration_is_refused(self):
        doc = _build(rin="999999999")
        found = checks.check_eta_document(_text(doc), profile_rin=RIN, now=NOW)
        assert any(issue.path == "issuer.id" for issue in found)

    def test_a_business_receiver_without_tax_id_is_refused(self):
        doc = _build(buyer={**BUYER, "vat_id": ""})
        assert "receiver_id_missing" in _codes(_text(doc))

    def test_item_code_type_must_be_gs1_or_egs(self):
        doc = _build(eta_fields={"lines": [{"itemType": "GPC", "itemCode": "10003752"}]})
        assert "item_type" in _codes(_text(doc))

    def test_activity_code_must_be_in_etas_table(self):
        assert "activity_code_unknown" in _codes(_text(_build(settings={**SETTINGS, "activity_code": "0000"})))
        assert "activity_code_missing" in _codes(_text(_build(settings={**SETTINGS, "activity_code": ""})))

    def test_a_future_issue_time_is_refused(self):
        doc = _build(eta_fields={"date_time_issued": "2026-10-20T00:00:00Z"})
        assert any(issue.path == "dateTimeIssued" for issue in checks.check_eta_document(_text(doc), now=NOW))

    def test_a_totals_mismatch_is_reported_per_field(self):
        doc = _build()
        doc["totalAmount"] = Decimal("1141.00000")
        found = [i for i in checks.check_eta_document(_text(doc), profile_rin=RIN, now=NOW) if i.group == "totals"]
        assert [i.path for i in found] == ["document.totalAmount"] or found[0].path.endswith("totalAmount")

    def test_a_subtype_of_another_tax_type_is_named(self):
        doc = _build()
        doc["invoiceLines"][0]["taxableItems"][0]["subType"] = "W001"
        found = [i for i in checks.check_eta_document(_text(doc), now=NOW) if i.code == "tax_subtype_parent"]
        assert found and found[0].message.endswith("subtype W001 belongs to T4, not to T1.")

    def test_unreadable_text_is_one_finding(self):
        found = checks.check_eta_document("{not json", now=NOW)
        assert [(i.group, i.code) for i in found] == [("readable", "unreadable")]

    def test_the_v0_9_sdk_sample_is_told_it_is_not_v1_0(self):
        codes_found = _codes((FIXTURES / "one-doc.json").read_text(encoding="utf-8"))
        assert "document_version" in codes_found
        assert "equation" not in codes_found


# ── Rules in the clearance rule set ──────────────────────────────────────────


def _context(text: str, *, fmt: str = validators.ETA_DOCUMENT_FORMAT, intent: str = "submit") -> ValidationContext:
    return ValidationContext(
        data={
            "intent": intent,
            "reference_time": NOW.isoformat(),
            "regime": {"document_format": fmt},
            "payload": {"format": fmt, "text": text},
            "profile": {"tax_registration_id": RIN},
            "document": {"id": "doc-1"},
        }
    )


def _run(rule: Any, context: ValidationContext) -> list[Any]:
    return asyncio.run(rule.validate(context))


class TestRules:
    def test_every_rule_passes_on_a_built_document(self):
        context = _context(_text(_build()))
        for rule in validators.ETA_RULES:
            results = _run(rule, context)
            if rule.rule_id == "einvoice_clearance.eta_advisory":
                assert {r.details["code"] for r in results if not r.passed} <= UNCHECKED
            else:
                assert all(result.passed for result in results), rule.rule_id

    @pytest.mark.parametrize(
        ("mutate", "rule_id"),
        [
            (lambda d: d.update(issuer={**d["issuer"], "id": ""}), "einvoice_clearance.eta_parties"),
            (lambda d: d.update(taxpayerActivityCode=""), "einvoice_clearance.eta_header"),
            (lambda d: d["invoiceLines"][0].update(itemType="XYZ"), "einvoice_clearance.eta_lines"),
            (lambda d: d.update(totalAmount=Decimal("1")), "einvoice_clearance.eta_totals"),
        ],
    )
    def test_each_rule_fires_on_its_own_defect(self, mutate, rule_id):
        doc = copy.deepcopy(_build())
        mutate(doc)
        context = _context(_text(doc))
        fired = {rule.rule_id for rule in validators.ETA_RULES for result in _run(rule, context) if not result.passed}
        assert rule_id in fired
        rule = next(r for r in validators.ETA_RULES if r.rule_id == rule_id)
        failing = [r for r in _run(rule, context) if not r.passed]
        assert failing[0].details["path"]
        assert failing[0].element_ref == "doc-1"

    def test_an_unreadable_payload_fires_the_readable_rule(self):
        rule = next(r for r in validators.ETA_RULES if r.rule_id == "einvoice_clearance.eta_document_readable")
        assert not _run(rule, _context("[]"))[0].passed

    def test_rules_ignore_another_countrys_document(self):
        context = _context("<Invoice/>", fmt="ubl_2_1")
        for rule in validators.ETA_RULES:
            assert all(result.passed for result in _run(rule, context))

    def test_rules_do_not_judge_the_document_on_cancel(self):
        context = _context("{not json", intent="cancel")
        for rule in validators.ETA_RULES:
            if rule.rule_id != "einvoice_clearance.eta_profile":
                assert all(result.passed for result in _run(rule, context))

    def test_the_profile_rule_names_what_is_missing(self):
        rule = next(r for r in validators.ETA_RULES if r.rule_id == "einvoice_clearance.eta_profile")
        context = ValidationContext(
            data={"intent": "submit", "profile": {"adapter_key": "eta_eg", "sandbox": True, "settings": {"eta": {}}}}
        )
        result = _run(rule, context)[0]
        assert not result.passed
        assert "environment" in result.message and "client_id_env" in result.message

    def test_registered_error_rules_join_the_hard_gate(self):
        validators.register_eta_rules()
        gate = {rule.rule_id for rule in clearance_validators._gate_rules()}
        assert {rule.rule_id for rule in validators.ETA_RULES} <= gate

    def test_the_hard_gate_blocks_a_wrong_total(self):
        validators.register_eta_rules()
        doc = _build()
        doc["totalAmount"] = Decimal("1")
        blockers = asyncio.run(clearance_validators.hard_blockers(_context(_text(doc)).data))
        assert any(b.rule_id == "einvoice_clearance.eta_totals" for b in blockers)


class TestSharedRinCheck:
    """The RIN format is checked by app.core.party_identifiers, never here."""

    def _with(self, monkeypatch, verdict):
        calls = []

        def fake(country, scheme, value):
            calls.append((country, scheme, value))
            return verdict

        monkeypatch.setattr(checks, "_rin_checker", lambda: fake)
        return calls

    def test_an_invalid_rin_is_an_error_naming_the_party(self, monkeypatch):
        calls = self._with(monkeypatch, {"valid": False, "reason": "format", "details": {}})
        found = checks.check_eta_document(_text(_build()), profile_rin=RIN, now=NOW)
        assert {"issuer_rin_invalid", "receiver_rin_invalid"} <= {i.code for i in found}
        assert ("EG", "rin", RIN) in calls
        issuer = next(i for i in found if i.code == "issuer_rin_invalid")
        assert issuer.group == "parties"
        assert "9 digits" in issuer.message

    def test_a_rule_under_expert_review_only_warns(self, monkeypatch):
        # The shape of party_identifiers.IdentifierCheck: reason, details.
        verdict = type(
            "IdentifierCheck",
            (),
            {"valid": False, "reason": "format", "details": {"needs_expert_review": "yes"}},
        )()
        self._with(monkeypatch, verdict)
        found = [i for i in checks.check_eta_document(_text(_build()), profile_rin=RIN, now=NOW) if "rin" in i.code]
        assert {(i.group, i.code) for i in found} == {
            ("advisory", "issuer_rin_invalid"),
            ("advisory", "receiver_rin_invalid"),
        }

    def test_a_valid_rin_leaves_no_note(self, monkeypatch):
        self._with(monkeypatch, type("Result", (), {"valid": True, "reason": None, "details": {}})())
        assert _codes(_text(_build())) == set()

    def test_no_installed_check_is_a_warning_not_an_error(self, monkeypatch):
        self._with(monkeypatch, None)
        found = checks.check_eta_document(_text(_build()), profile_rin=RIN, now=NOW)
        assert [(i.group, i.code) for i in found] == [("advisory", "rin_format_unchecked")]
        assert found[0].path == "issuer.id, receiver.id"


class TestPersonThreshold:
    def _person_doc(self, total: str, issued: str) -> str:
        doc = _build(
            buyer={**BUYER, "first_name": "Mona", "vat_id": ""},
            eta_fields={"date_time_issued": issued},
        )
        doc["totalAmount"] = Decimal(total)
        return _text(doc)

    def test_the_threshold_follows_the_issue_date(self):
        assert codes.person_id_threshold("2024-07-31T10:00:00Z").amount == Decimal("50000")
        assert codes.person_id_threshold("2024-08-01T00:00:00Z").amount == Decimal("25000")
        assert all(row.needs_expert_review and row.source_url for row in codes.PERSON_ID_THRESHOLDS)

    def test_a_large_invoice_to_a_person_without_id_is_flagged(self):
        found = checks.check_eta_document(self._person_doc("30000", "2026-10-18T00:00:00Z"), now=NOW)
        flagged = [i for i in found if i.code == "person_without_id"]
        assert flagged
        assert flagged[0].group == "advisory"
        assert "25000" in flagged[0].message

    def test_below_the_threshold_of_its_date_nothing_is_said(self):
        found = checks.check_eta_document(self._person_doc("30000", "2024-07-01T00:00:00Z"), now=NOW)
        assert "person_without_id" not in {i.code for i in found}


class TestEgsCode:
    def test_only_the_documented_prefix_is_checked(self):
        doc = _build(eta_fields={"lines": [{"itemType": "EGS", "itemCode": "100000001-1001"}]})
        found = [i for i in checks.check_eta_document(_text(doc), now=NOW) if i.code == "egs_code_prefix"]
        assert [(i.group, i.path) for i in found] == [("advisory", "invoiceLines[0].itemCode")]
        assert "egs_code_prefix" not in _codes(_text(_build()))
