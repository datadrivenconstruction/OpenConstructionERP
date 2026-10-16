"""Reading a file of open invoices carried over from another system.

Amounts and dates must read one way only or be refused, the paid part must be
what the total, the retention and the open amount leave, a row that cannot be
right must say why, and a file repeating an invoice number must be caught
before anything reaches the database.

Run:
    cd backend
    python -m pytest tests/unit/test_finance_open_items.py -v
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modules.finance.open_items import (
    OpenItem,
    RowProblem,
    check_row,
    check_rows,
    normalise_tax_id,
    parse_amount,
    parse_date,
    read_table,
    template_csv,
)

CUTOVER = "2026-09-30"


def _row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "direction": "AR",
        "invoice_number": "INV-1",
        "counterparty": "Lakeview Homes",
        "invoice_date": "2026-08-15",
        "total": "11300.00",
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("1234.56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1234,56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1,234,567.89", "1234567.89"),
        ("(250.00)", "-250.00"),
        ("CAD 500", "500"),
        (1500, "1500"),
        (12.5, "12.5"),
        ("0.125", "0.125"),
    ],
)
def test_amounts_that_read_one_way(cell: object, expected: str) -> None:
    assert parse_amount(cell) == Decimal(expected)


@pytest.mark.parametrize("cell", ["1,234", "1.234", "12,34,5", "abc", "", None, True])
def test_amounts_that_could_be_read_two_ways_are_refused(cell: object) -> None:
    assert parse_amount(cell) is None


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("2026-08-15", "2026-08-15"),
        ("15.08.2026", "2026-08-15"),
        ("2026/08/15", "2026-08-15"),
        ("15/08/2026", "2026-08-15"),
        ("2026-08-15 00:00:00", "2026-08-15"),
        (datetime(2026, 8, 15, 9, 30), "2026-08-15"),
        (date(2026, 8, 15), "2026-08-15"),
    ],
)
def test_dates(cell: object, expected: str) -> None:
    assert parse_date(cell) == expected


def test_a_month_first_date_is_not_guessed() -> None:
    assert parse_date("08/15/2026") is None


def test_the_paid_part_is_what_total_retention_and_open_leave() -> None:
    item = check_row(2, _row(retention_held="1000", open="6300", tax="1300"), cutover_date=CUTOVER)
    assert isinstance(item, OpenItem)
    assert (item.direction, item.paid, item.tax) == ("receivable", Decimal("4000.00"), Decimal("1300.00"))


def test_an_empty_open_amount_is_the_total_less_retention() -> None:
    item = check_row(2, _row(direction="AP", retention_held="300"), cutover_date=CUTOVER)
    assert isinstance(item, OpenItem)
    assert (item.direction, item.open, item.paid) == ("payable", Decimal("11000.00"), Decimal("0.00"))


@pytest.mark.parametrize(
    ("over", "fragment"),
    [
        ({"direction": "both"}, "neither receivable"),
        ({"invoice_number": ""}, "invoice number is missing"),
        ({"counterparty": ""}, "counterparty is missing"),
        ({"invoice_date": "08/15/2026"}, "is not a date"),
        ({"invoice_date": "2026-10-01"}, "after the cut-over"),
        ({"due_date": "2026-08-01"}, "before the invoice date"),
        ({"currency": "C$"}, "three-letter"),
        ({"total": "1,234"}, "reads one way only"),
        ({"total": "0"}, "missing or zero"),
        ({"total": "-50"}, "negative"),
        ({"tax": "20000"}, "tax is larger"),
        ({"retention_held": "500", "open": "11000"}, "more than the total"),
        ({"open": "0"}, "Nothing is open"),
    ],
)
def test_a_row_that_cannot_be_right_says_why(over: dict[str, object], fragment: str) -> None:
    result = check_row(7, _row(**over), cutover_date=CUTOVER)
    assert isinstance(result, RowProblem)
    assert result.row == 7
    assert fragment in result.message
    assert result.code, "every problem carries a code the interface can translate"


def test_a_counterparty_given_only_by_tax_number_is_read() -> None:
    item = check_row(2, _row(counterparty="", tax_id="987654321RT0001"), cutover_date=CUTOVER)
    assert isinstance(item, OpenItem)


def test_a_repeated_number_is_caught_per_direction() -> None:
    rows = [
        (2, _row()),
        (3, _row(direction="AP")),
        (4, _row(invoice_number="inv-1")),
    ]
    results = check_rows(rows, cutover_date=CUTOVER)
    assert isinstance(results[0], OpenItem)
    assert isinstance(results[1], OpenItem)
    assert isinstance(results[2], RowProblem)
    assert "row 2" in results[2].message
    assert (results[2].code, results[2].params) == ("duplicate_in_file", {"number": "inv-1", "first_row": "2"})


def test_tax_numbers_match_without_spacing_or_case() -> None:
    assert normalise_tax_id("98765 4321-rt0001") == "987654321RT0001"
    assert normalise_tax_id(None) == ""


def test_a_csv_reads_with_its_aliases_and_row_numbers() -> None:
    content = (
        "Type;Invoice No;Customer;Date;Fällig am;Betrag;Offen\n"
        "AR;INV-9;Lakeview;15.08.2026;14.09.2026;1.130,00;630,00\n"
        ";;;;;;\n"
        "AP;LS-1;Steel;2026-09-02;;500;\n"
    ).encode()
    missing, rows = read_table(content, "open.csv")
    assert missing == []
    assert [n for n, _ in rows] == [2, 4]
    item = check_row(*rows[0], cutover_date=CUTOVER)
    assert isinstance(item, OpenItem)
    assert (item.total, item.open, item.due_date) == (Decimal("1130.00"), Decimal("630.00"), "2026-09-14")


def test_a_file_without_the_required_columns_names_them() -> None:
    missing, _ = read_table(b"invoice_number,total\nX,1\n", "open.csv")
    assert missing == ["direction", "counterparty", "invoice_date"]


def test_an_excel_file_under_a_letterhead_reads() -> None:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Lakeshore Developments Inc."])
    ws.append([])
    ws.append(["direction", "invoice_number", "counterparty", "invoice_date", "total"])
    ws.append(["AP", "LS-7", "Steel", datetime(2026, 9, 1), 1500])
    buf = io.BytesIO()
    wb.save(buf)
    missing, rows = read_table(buf.getvalue(), "open.xlsx")
    assert missing == []
    assert rows[0][0] == 4
    item = check_row(*rows[0], cutover_date=CUTOVER)
    assert isinstance(item, OpenItem)
    assert item.invoice_date == "2026-09-01"


def test_the_template_reads_back_cleanly() -> None:
    missing, rows = read_table(template_csv().encode(), "template.csv")
    assert missing == []
    results = check_rows(rows, cutover_date=CUTOVER)
    assert all(isinstance(r, OpenItem) for r in results)
