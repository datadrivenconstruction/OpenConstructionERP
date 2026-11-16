"""Booking batch export: the DOMAIN worked examples (sample customer config, not shipped data)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.active_markets import pack_active
from app.modules.dach_pack.datev import DatevWriter
from app.modules.finance.booking_export import InvoiceIn, Mapping, plan_batch
from app.modules.finance.connectors.registry import ConnectorRegistry

D = Decimal
MAPPING = Mapping(
    accounts={"mat": {"account": "3400", "tax_key": "9"}, "mat7": {"account": "3300", "tax_key": "8"}},
    creditors={"Baustoffe Nord GmbH": "70001"},
)
SETTINGS = {"advisor": "1001", "client": "20345", "fiscal_year_start": "20260101", "account_length": "4"}


def invoice(number: str, day: date, net: str, tax: str, gross: str, **kw) -> InvoiceIn:
    base = {
        "id": number,
        "number": number,
        "date": day,
        "currency": "EUR",
        "supplier": "Baustoffe Nord GmbH",
        "supplier_key": "",
        "net": D(net),
        "tax": D(tax),
        "gross": D(gross),
        "status": "approved",
        "expense_account": "mat",
        "project_code": "P-2026-014",
        "cost_code": "300.20",
    }
    return InvoiceIn(**{**base, **kw})


def body(content: bytes) -> list[str]:
    return content.decode("cp1252").split("\r\n")[2:-1]


def test_example_1_single_invoice_row() -> None:
    inv = invoice("RE-88412", date(2026, 10, 14), "1000.00", "190.00", "1190.00")
    plan = plan_batch([inv], MAPPING, date(2026, 10, 1), date(2026, 10, 31), prefix="datev")
    assert not plan.findings
    row = body(DatevWriter.render(plan.rows, SETTINGS, date(2026, 10, 1), date(2026, 10, 31)))[0]
    assert row.startswith('1190,00;"H";"EUR";70001;3400;"9";1410;"RE-88412";')
    assert row.endswith(';"P-2026-014";"300.20"')


def test_example_2_mixed_rates_make_two_rows_that_sum_to_gross() -> None:
    lines = (
        {"account": "mat", "amount": "500.00", "tax_rate": "19"},
        {"account": "mat7", "amount": "200.00", "tax_rate": "7"},
    )
    inv = invoice("RE-88430", date(2026, 10, 21), "700.00", "109.00", "809.00", lines=lines)
    plan = plan_batch([inv], MAPPING, date(2026, 10, 1), date(2026, 10, 31), prefix="datev")
    assert [(r.amount, r.counter_account, r.tax_key) for r in plan.rows] == [
        (D("595.00"), "3400", "9"),
        (D("214.00"), "3300", "8"),
    ]
    assert sum(r.amount for r in plan.rows) == D("809.00")
    assert {r.invoice_number for r in plan.rows} == {"RE-88430"}


def test_example_3_credit_note_flips_the_indicator_and_period_across_fiscal_year_is_blocked() -> None:
    inv = invoice("GS-1207", date(2026, 11, 3), "-200.00", "-38.00", "-238.00")
    plan = plan_batch([inv], MAPPING, date(2026, 11, 1), date(2026, 11, 30), prefix="datev")
    assert (plan.rows[0].amount, plan.rows[0].side) == (D("238.00"), "S")
    assert DatevWriter.check_settings(SETTINGS, date(2026, 12, 15), date(2027, 1, 15))[0]["rule_id"] == (
        "datev.period_crosses_fiscal_year"
    )
    assert DatevWriter.check_settings(SETTINGS, date(2026, 11, 1), date(2026, 11, 30)) == []


def test_header_is_complete_and_format_version_is_configurable() -> None:
    text = DatevWriter.render([], SETTINGS, date(2026, 10, 1), date(2026, 10, 31)).decode("cp1252")
    assert text.startswith('"EXTF";700;21;"Buchungsstapel";13;1001;20345;')
    v12 = DatevWriter.render([], {**SETTINGS, "format_version": 12}, date(2026, 10, 1), date(2026, 10, 31))
    assert v12.decode("cp1252").startswith('"EXTF";700;21;"Buchungsstapel";12;')
    assert DatevWriter.check_settings({"advisor": "1001"}, date(2026, 10, 1), date(2026, 10, 31))[0]["rule_id"] == (
        "datev.header_incomplete"
    )


def test_findings_unapproved_unmapped_exported_and_inconsistent() -> None:
    day = date(2026, 10, 14)
    invoices = [
        invoice("A", day, "100.00", "19.00", "119.00", status="captured"),
        invoice("B", day, "100.00", "19.00", "119.00", expense_account="unknown"),
        invoice("C", day, "100.00", "19.00", "119.00", exported_in="B-3"),
        invoice("D", day, "100.00", "19.00", "120.00"),
        invoice("E", day, "100.00", "19.00", "119.00", currency="CHF"),
    ]
    plan = plan_batch(invoices, MAPPING, day, day, prefix="datev", base_currency="EUR")
    assert {(f["rule_id"], f["invoice"]) for f in plan.findings} == {
        ("datev.not_approved", "A"),
        ("datev.account_unmapped", "B"),
        ("datev.already_exported", "C"),
        ("datev.amounts_inconsistent", "D"),
        ("datev.foreign_currency", "E"),
    }
    assert plan.blocked
    again = plan_batch([invoices[2]], MAPPING, day, day, reexport=True, prefix="datev")
    assert len(again.rows) == 1


def test_the_datev_type_is_listed_only_where_the_pack_is_active() -> None:
    from app.modules.finance.connectors.booking_connector import register_booking_connector

    registry = ConnectorRegistry()
    from app.modules.finance.connectors import booking_connector as bc

    original = bc.connector_registry
    bc.connector_registry = registry
    try:
        register_booking_connector(DatevWriter, "Export in DATEV format (EXTF)")
    finally:
        bc.connector_registry = original
    assert [t["connector_type"] for t in registry.list_types(["DE"])] == ["datev_extf"]
    assert registry.list_types(["US"]) == []
    assert registry.list_types(["*"]) == []
    assert pack_active(["CH"], DatevWriter.required_markets)
