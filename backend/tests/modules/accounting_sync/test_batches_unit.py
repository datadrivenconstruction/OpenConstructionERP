# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export batches without a database: DATEV bytes, hashes, parsing, reconciliation, rules, registry."""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.modules.accounting_sync import providers, templates
from app.modules.accounting_sync.batches import ExportRecord
from app.modules.accounting_sync.export_validators import (
    evaluate_export,
    fiscal_year,
    register_export_rules,
)
from app.modules.accounting_sync.exports import datev
from app.modules.accounting_sync.ledger_import import parse_amount, parse_lines, reconcile
from app.modules.accounting_sync.postings import (
    Mapping,
    SyncContact,
    SyncDocument,
    SyncLine,
    personal_accounts,
)

GOLDEN = Path(__file__).parent / "golden" / "datev_buchungsstapel.csv"
CREATED = datetime(2026, 11, 16, 9, 30, 15, 123000, tzinfo=UTC)
PERIOD = (date(2026, 1, 1), date(2026, 12, 31))
SETTINGS = {"consultant_number": "1001", "client_number": "20002", "fiscal_year_start": "20260101", "account_length": 4}


@pytest.fixture(autouse=True)
def _rules():
    register_export_rules()


def _mapping() -> Mapping:
    tpl = templates.get_template("DE-SKR03")
    return Mapping(
        accounts={c: tuple(v[:2]) for c, v in tpl["accounts"].items()},
        tax_keys={(code, d): v for d, codes in tpl["tax_keys"].items() for code, v in codes.items()},
    )


def _bill(number: str = "SUB-17", net: str = "5000.10") -> SyncDocument:
    return SyncDocument(
        record_type="ap_bill",
        record_id=f"id-{number}",
        number=number,
        doc_date=date(2026, 4, 2),
        due_date=date(2026, 5, 2),
        contact=SyncContact(record_id="c2", name="Steelworks AG", kind="supplier", tax_id="DE811128135"),
        currency="EUR",
        lines=[SyncLine("Structural steel, level 2", Decimal(net), "subcontract_cost", "VAT", Decimal("19"))],
        source="subcontractor",
        project_code="P-100",
    )


def _datev(doc: SyncDocument) -> bytes:
    tpl = templates.get_template("DE-SKR03")
    accounts = personal_accounts([doc.contact], tuple(tpl["debtor_range"]), tuple(tpl["creditor_range"]))
    return datev.buchungsstapel(
        [doc], _mapping(), accounts, settings=SETTINGS, period=PERIOD, skr="03", created_at=CREATED
    )


def test_datev_file_matches_the_golden_bytes() -> None:
    content = _datev(_bill())
    if not GOLDEN.exists():  # pragma: no cover - first run writes the reviewed file
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_bytes(content)
    assert content == GOLDEN.read_bytes()
    assert content.startswith(b'"EXTF";')
    assert b"\r\n" in content


def test_datev_file_is_windows_1252() -> None:
    doc = _bill()
    doc.lines[0].description = "Stahlbau Grüße äöü"
    content = _datev(doc)
    assert "Grüße äöü".encode("cp1252") in content
    with pytest.raises(UnicodeDecodeError):
        content.decode("utf-8")


def test_batch_hash_is_stable_for_same_input_and_changes_with_amounts() -> None:
    first, second = _datev(_bill()), _datev(_bill())
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert hashlib.sha256(_datev(_bill(net="5000.11"))).hexdigest() != hashlib.sha256(first).hexdigest()


def test_record_payload_hash_ignores_nothing_that_is_exported() -> None:
    a = ExportRecord("budget", "b1", "Concrete", None, "EUR", net=Decimal("100"), payload={"actual": "1"})
    b = ExportRecord("budget", "b1", "Concrete", None, "EUR", net=Decimal("100"), payload={"actual": "1"})
    c = ExportRecord("budget", "b1", "Concrete", None, "EUR", net=Decimal("100"), payload={"actual": "2"})
    assert a.payload_hash() == b.payload_hash() != c.payload_hash()
    assert _bill().payload_hash() == _bill().payload_hash()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1234,5", "1234.50"),
        ("-12,00", "-12.00"),
        ("(100.00)", "-100.00"),
        ("1.234.567", "1234567.00"),
        ("", None),
        ("abc", None),
    ],
)
def test_amounts_parse_in_both_notations(raw: str, expected: str | None) -> None:
    got = parse_amount(raw)
    assert (None if got is None else f"{got:.2f}") == expected


def _rows(content: bytes, name: str = "books.csv") -> list[tuple[int, dict | None, str | None]]:
    return list(parse_lines(io.BytesIO(content), name))


def test_csv_import_reads_german_headers_and_cp1252() -> None:
    text = (
        "Belegfeld 1;Belegdatum;Konto;Umsatz (ohne Soll/Haben-Kz);Soll/Haben-Kennzeichen;Buchungstext;Status\r\n"
        "SUB-17;02.04.2026;4400;5.950,12;S;Stahlbau Grüße;bezahlt\r\n"
        ";02.04.2026;4400;1,00;S;no number;\r\n"
        "AR-001;31.03.2026;8400;11.900,00;H;Abschlag;\r\n"
    ).encode("cp1252")
    rows = _rows(text)
    assert [r[0] for r in rows] == [2, 3, 4]
    first = rows[0][1]
    assert first["document_number"] == "SUB-17" and first["debit"] == Decimal("5950.12") and first["credit"] == 0
    assert first["posting_date"] == date(2026, 4, 2) and first["payment_status"] == "paid"
    assert first["description"] == "Stahlbau Grüße"
    assert rows[1][1] is None and rows[1][2] == "document_number"
    assert rows[2][1]["credit"] == Decimal("11900.00")


def test_xlsx_import_streams_debit_and_credit_columns() -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["Document", "Date", "Account", "Debit", "Credit"])
    ws.append(["AR-001", date(2026, 3, 31), "1400", 11900, 0])
    ws.append(["AR-001", date(2026, 3, 31), "8400", 0, 10000])
    bio = io.BytesIO()
    wb.save(bio)
    rows = _rows(bio.getvalue(), "books.xlsx")
    assert len(rows) == 2 and rows[0][1]["debit"] == Decimal("11900.00") and rows[1][1]["credit"] == Decimal("10000.00")
    assert rows[0][1]["posting_date"] == date(2026, 3, 31)


def test_file_without_the_needed_columns_is_refused() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as err:
        _rows(b"foo;bar\r\n1;2\r\n")
    assert err.value.status_code == 422


def test_reconciliation_splits_matched_mismatched_and_one_sided_documents() -> None:
    platform = [
        {"number": "A-1", "amount": Decimal("100.00"), "record_id": "1"},
        {"number": "A-2", "amount": Decimal("200.00"), "record_id": "2"},
        {"number": "A-3", "amount": Decimal("300.00"), "record_id": "3"},
    ]
    books = {
        "A-1": {"amount": Decimal("100.00"), "date": None, "payment_status": "paid"},
        "A-2": {"amount": Decimal("190.00"), "date": None, "payment_status": ""},
        "B-9": {"amount": Decimal("50.00"), "date": date(2026, 2, 1), "payment_status": ""},
    }
    out = reconcile(platform, books)
    assert out["counts"] == {"matched": 1, "mismatches": 1, "platform_only": 1, "books_only": 1}
    assert out["mismatches"][0]["difference"] == "-10.00" and out["mismatches"][0]["number"] == "A-2"
    assert out["platform_only"][0]["number"] == "A-3" and out["books_only"][0]["number"] == "B-9"
    assert out["matched"][0]["payment_status"] == "paid"


def _snapshot(**over) -> dict:
    snap = {
        "format": "datev",
        "settings": dict(SETTINGS),
        "documents": [
            {
                "record_id": "r1",
                "number": "SUB-17",
                "doc_date": "2026-04-02",
                "debit": "5950.12",
                "credit": "5950.12",
                "accounts": ["3400", "1600"],
                "texts": ["ok"],
                "tax_keys": ["9"],
                "project_code": "P-100",
                "contact": {"name": "Steelworks AG", "tax_id": "DE811128135", "tax_id_valid": True},
            }
        ],
        "records": [
            {"record_type": "ap_bill", "record_id": "r1", "number": "SUB-17", "currency": "EUR", "batch_no": None}
        ],
    }
    snap.update(over)
    return snap


async def _ids(snap: dict) -> set[str]:
    return {r.rule_id.split(".")[1] for r in await evaluate_export(snap)}


@pytest.mark.asyncio
async def test_clean_snapshot_has_no_findings() -> None:
    assert await _ids(_snapshot()) == set()


@pytest.mark.asyncio
async def test_each_export_rule_fires_on_its_own_defect() -> None:
    snap = _snapshot()
    doc = snap["documents"][0]
    doc.update(credit="5000.00", accounts=["34000", "16"], texts=["x" * 61], tax_keys=["AB"], doc_date="2027-01-05")
    doc["contact"].update(tax_id_valid=False)
    snap["settings"] = {**SETTINGS, "consultant_number": ""}
    snap["records"] = [
        {"record_type": "ap_bill", "record_id": "r1", "number": "SUB-17", "currency": "EU", "batch_no": 1}
    ]
    assert await _ids(snap) == {
        "unbalanced",
        "datev_settings",
        "account_length",
        "booking_text_length",
        "posting_key",
        "date_in_fiscal_year",
        "currency_iso",
        "already_exported",
        "supplier_tax_id",
    }


@pytest.mark.asyncio
async def test_re_export_names_the_batch_and_cost_centre_needs_a_mapping() -> None:
    snap = _snapshot(has_cost_code_map=True, cost_codes_mapped=["P-200"])
    snap["records"][0]["batch_no"] = 1
    found = {r.rule_id: r for r in await evaluate_export(snap)}
    assert found["accounting_export.already_exported"].details["params"]["batch"] == 1
    assert "already in batch 1" in found["accounting_export.already_exported"].message
    assert "accounting_export.cost_centre_unmapped" in found


@pytest.mark.asyncio
async def test_datev_only_rules_stay_quiet_for_other_formats() -> None:
    snap = _snapshot(format="csv")
    snap["settings"] = {}
    assert await _ids(snap) == set()


def test_fiscal_year_handles_iso_and_leap_day() -> None:
    assert fiscal_year({"fiscal_year_start": "2026-04-01"}) == (date(2026, 4, 1), date(2027, 3, 31))
    assert fiscal_year({"fiscal_year_start": "20240229"}) == (date(2024, 2, 29), date(2025, 2, 27))
    assert fiscal_year({}) is None


def test_provider_registry_lets_a_pack_add_and_remove_an_adapter() -> None:
    class PackAdapter(providers.ProviderAdapter):  # type: ignore[misc]
        pass

    assert {"xero", "qbo"} <= set(providers.API_PROVIDERS)
    providers.register_provider("pack_x", PackAdapter)
    try:
        assert "pack_x" in providers.all_providers() and providers.API_PROVIDERS["pack_x"] is PackAdapter
        with pytest.raises(ValueError):
            providers.register_provider("pack_x", PackAdapter)
        with pytest.raises(ValueError):
            providers.register_provider("datev", PackAdapter)
    finally:
        providers.unregister_provider("pack_x")
    assert "pack_x" not in providers.all_providers()
