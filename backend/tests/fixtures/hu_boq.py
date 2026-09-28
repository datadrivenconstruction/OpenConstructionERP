# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Synthetic Hungarian bills (költségvetés) in the shapes estimators exchange.

Written from what Hungarian bills look like, not copied from any one: a title
block above the table, "Ssz." for the running number and "Tételszám" for the
norm or catalogue code, "Menny." for the quantity, every line priced as
material (anyag) plus fee (díj), chapter headings with the trade number in
front, chapter totals with "összesen" at the END of the line, then the net
total, the VAT line and the gross total. Numbers are typed the Hungarian way,
with a space between thousands and a decimal comma.

Each builder returns the bytes of one upload. The variants are the ones a
tester can plausibly hold: a flat table, the same table with the money
columns headed over two rows, a workbook that opens on its cover sheet, a
semicolon CSV saved from Hungarian Excel (Windows-1250) and one saved as
UTF-8, and the simpler single-rate layout.
"""

from __future__ import annotations

import io

from openpyxl import Workbook

TITLE_ROWS: list[list[str]] = [
    ["Költségvetés"],
    ["Építtető: Minta Kft."],
    ["Munka: Családi ház, Budapest"],
    [],
]

HEADER: list[str] = [
    "Ssz.",
    "Tételszám",
    "Tétel szövege",
    "Menny.",
    "Egység",
    "Anyag egységár",
    "Díj egységár",
    "Anyag összesen",
    "Díj összesen",
]

# The same money columns headed over two rows, "Egységár" and "Összesen"
# merged across the pair beneath them.
TWO_ROW_HEADER: list[list[str | None]] = [
    ["Ssz.", "Tételszám", "Tétel szövege", "Menny.", "Egység", "Egységár", None, "Összesen", None],
    [None, None, None, None, None, "Anyag", "Díj", "Anyag", "Díj"],
]

SINGLE_RATE_HEADER: list[str] = [
    "Ssz.",
    "Tételszám",
    "Tétel szövege",
    "Mennyiség",
    "Mértékegység",
    "Egységár (Ft)",
    "Összesen (Ft)",
]

PANEL = "Előregyártott vasbeton födémpanel elhelyezése, hőszigeteléssel"

ROWS: list[list[str]] = [
    ["", "", "21 Irtás, föld- és sziklamunka", "", "", "", "", "", ""],
    ["1", "21-003-5.1.1", "Munkagödör földkiemelése gépi erővel", "125,5", "m3", "0", "1 850", "0", "232 175"],
    ["2", "21-011-11.2", "Tükörkészítés, tömörítéssel", "340", "m2", "", "420,50", "", "142 970"],
    ["", "", "Irtás, föld- és sziklamunka összesen:", "", "", "", "", "0", "375 145"],
    ["", "", "31 Helyszíni beton és vasbeton munkák", "", "", "", "", "", ""],
    ["3", "31-011-1.1.1", PANEL, "48", "db", "85 400", "12 300", "4 099 200", "590 400"],
    ["4", "31-021-2.3", "Zsaluzás, 30 cm vastag falhoz", "96,4", "m2", "3 200", "4 150", "308 480", "400 060"],
    ["5", "", "Felvonulási létesítmények", "1", "klt", "150 000", "250 000", "150 000", "250 000"],
    ["6", "", "Vasszerelés", "2,35", "t", "420 000", "95 000", "987 000", "223 250"],
    ["7", "", "Betonszivattyú", "8", "óra", "", "18 500", "", "148 000"],
    ["8", "", "Lábazati szegély", "42,6", "fm", "1 250", "980", "53 250", "41 748"],
    ["", "", "Helyszíni beton és vasbeton munkák összesen:", "", "", "", "", "5 544 680", "1 255 458"],
    ["", "", "Mindösszesen", "", "", "", "", "5 544 680", "1 630 603"],
    ["", "", "ÁFA 27%", "", "", "", "", "", "1 937 426"],
    ["", "", "Bruttó összesen", "", "", "", "", "", "9 112 709"],
]

# (ssz, unit, quantity, material rate, fee rate) of every priced line above.
EXPECTED_LINES: list[tuple[str, str, float, float, float]] = [
    ("1", "m3", 125.5, 0.0, 1850.0),
    ("2", "m2", 340.0, 0.0, 420.5),
    ("3", "db", 48.0, 85400.0, 12300.0),
    ("4", "m2", 96.4, 3200.0, 4150.0),
    ("5", "klt", 1.0, 150000.0, 250000.0),
    ("6", "t", 2.35, 420000.0, 95000.0),
    ("7", "óra", 8.0, 0.0, 18500.0),
    ("8", "fm", 42.6, 1250.0, 980.0),
]

# (label, kind) of every total, tax and recap line, in sheet order.
EXPECTED_SUMMARY: list[tuple[str, str]] = [
    ("Irtás, föld- és sziklamunka összesen:", "subtotal"),
    ("Helyszíni beton és vasbeton munkák összesen:", "subtotal"),
    ("Mindösszesen", "grand_total"),
    ("ÁFA 27%", "tax"),
    ("Bruttó összesen", "grand_total"),
]


def _xlsx(sheets: list[tuple[str, list[list[object]]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets:
        worksheet = workbook.create_sheet(name)
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _csv(rows: list[list[str]], encoding: str) -> bytes:
    return "".join(";".join(row) + "\r\n" for row in rows).encode(encoding)


def _single_rate_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for row in ROWS:
        material = row[5].replace(" ", "").replace(",", ".")
        fee = row[6].replace(" ", "").replace(",", ".")
        rate = ""
        if material or fee:
            rate = f"{float(material or 0) + float(fee or 0):g}".replace(".", ",")
        rows.append([*row[:5], rate, row[8]])
    return rows


def flat_xlsx() -> bytes:
    """One sheet: title block, one header row, the bill."""
    return _xlsx([("Költségvetés", [*TITLE_ROWS, HEADER, *ROWS])])


def two_row_header_xlsx() -> bytes:
    """The money columns headed over two rows."""
    return _xlsx([("Költségvetés", [*TITLE_ROWS, *TWO_ROW_HEADER, *ROWS])])


def cover_first_xlsx() -> bytes:
    """A workbook that opens on its cover and summary sheets."""
    return _xlsx(
        [
            ("Záradék", [["Záradék"], ["A költségvetés a kiviteli terv alapján készült."]]),
            ("Összesítő", [["Munkanem", "Anyag", "Díj"], ["Földmunka", 0, 375145]]),
            ("Költségvetés", [HEADER, *ROWS]),
        ]
    )


def cp1250_csv() -> bytes:
    """Semicolon CSV as Hungarian Excel saves it: Windows-1250, title block on top."""
    return _csv([*[row or [""] for row in TITLE_ROWS], HEADER, *ROWS], "cp1250")


def utf8_csv() -> bytes:
    """The same CSV saved as UTF-8 with a byte order mark."""
    return _csv([HEADER, *ROWS], "utf-8-sig")


def single_rate_xlsx() -> bytes:
    """The simpler layout: one rate and one total per line, "Mértékegység" for the unit."""
    return _xlsx([("Költségvetés", [SINGLE_RATE_HEADER, *_single_rate_rows()])])
