# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A national bill of quantities imports as the work it prices, and nothing else.

The sheet below is a trimmed Croatian troskovnik laid out the way the market
writes one: a letterhead, the header row "R.br. | Opis stavke | Jed. mj. |
Kolicina | Jed. cijena (EUR) | Ukupno (EUR)", roman-numbered sections, a total
line under every section, a recap page that repeats the section ordinals, and
the net total, the 25 % tax line and the grand total at the foot.

Before this change the importer read none of the header row and refused the
file with "No data rows found". Read with English headers instead, it turned
every total, the recap heading, every recap line and the tax line into an
empty section, the recap lines colliding with the real sections' ordinals,
and it warned that every lump sum's rate was ten times the file median.

What is pinned here is the result a Croatian estimator expects: the priced
lines and the section headings, the priced lines adding up to the net total
the file itself states, and the lines left out named in the warnings.

Run::

    cd backend
    python -m pytest tests/unit/test_boq_import_reads_a_national_bill_with_its_totals.py -v
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

import pytest
from openpyxl import Workbook

from app.modules.boq.importers._base import ImportedBOQ
from app.modules.boq.importers.excel import (
    _SUMMARY_KINDS,
    _SUMMARY_WORDS_BY_LANGUAGE,
    ExcelImporter,
    normalise_label,
    partition_summary_rows,
    summary_label_kind,
)
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.units import is_lump_sum_unit, normalise_unit

# ── The sheet ───────────────────────────────────────────────────────────────

_HEADER = ["R.br.", "Opis stavke", "Jed. mj.", "Količina", "Jed. cijena (EUR)", "Ukupno (EUR)"]

# (ordinal, description, unit, quantity, rate); a None unit marks a section.
_SECTIONS: list[tuple[str, str, list[tuple[str, str, str, float, float]]]] = [
    (
        "I.",
        "PRIPREMNI RADOVI",
        [
            ("1.1", "Organizacija i uređenje gradilišta. Obračun paušalno.", "pauš.", 1, 18500),
            ("1.2", "Iskolčenje građevine. Obračun paušalno.", "pauš.", 1, 1200),
        ],
    ),
    (
        "II.",
        "ZEMLJANI RADOVI",
        [
            ("2.1", "Strojni iskop građevne jame u tlu C kategorije.", "m³", 1450, 9.8),
            ("2.2", "Odvoz viška iskopanog materijala na deponij.", "m³", 1180, 12.5),
        ],
    ),
    (
        "III.",
        "LIMARSKI I STOLARSKI RADOVI",
        [
            ("3.1", "Opšav atike pocinčanim limom, r.š. 50 cm.", "m'", 180, 32),
            ("3.2", "Dobava i ugradnja PVC prozora 120 × 140 cm.", "kom", 96, 520),
            ("3.3", "Armatura B500B, sječenje, savijanje i postavljanje.", "kg", 9800, 1.35),
        ],
    ),
    (
        "IV.",
        "INSTALACIJE",
        [
            ("4.1", "Vodovod i kanalizacija, komplet. Obračun paušalno.", "pauš.", 1, 96000),
            ("4.2", "Elektroinstalacije, komplet. Obračun paušalno.", "pauš.", 1, 118000),
        ],
    ),
]


def _section_total(lines: list[tuple[str, str, str, float, float]]) -> float:
    return round(sum(quantity * rate for _, _, _, quantity, rate in lines), 2)


_NET_TOTAL = round(sum(_section_total(lines) for _, _, lines in _SECTIONS), 2)
_TAX = round(_NET_TOTAL * 0.25, 2)


def _troskovnik() -> bytes:
    """The trimmed troskovnik as an .xlsx, letterhead and all."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([None, "TROŠKOVNIK - Stambena zgrada, Zagreb"])
    sheet.append([None, "Sve cijene u EUR, bez PDV-a."])
    sheet.append([])
    sheet.append(_HEADER)
    for ordinal, title, lines in _SECTIONS:
        sheet.append([ordinal, title, None, None, None, None])
        for line_ordinal, description, unit, quantity, rate in lines:
            sheet.append([line_ordinal, description, unit, quantity, rate, round(quantity * rate, 2)])
        sheet.append([None, f"UKUPNO {ordinal} {title}", None, None, None, _section_total(lines)])
    sheet.append([None, "REKAPITULACIJA", None, None, None, None])
    for ordinal, title, lines in _SECTIONS:
        sheet.append([ordinal, title, None, None, None, _section_total(lines)])
    sheet.append([None, "UKUPNO (bez PDV-a)", None, None, None, _NET_TOTAL])
    sheet.append([None, "PDV 25 %", None, None, None, _TAX])
    sheet.append([None, "SVEUKUPNO", None, None, None, round(_NET_TOTAL + _TAX, 2)])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _parse(content: bytes) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content))


@pytest.fixture(scope="module")
def imported() -> ImportedBOQ:
    return _parse(_troskovnik())


# ── The bill ────────────────────────────────────────────────────────────────


def test_the_croatian_header_row_is_read(imported: ImportedBOQ) -> None:
    assert sorted(imported.metadata["column_mapping"].values()) == sorted(
        ["ordinal", "description", "unit", "quantity", "unit_rate", "total"]
    )
    assert imported.errors == []


def test_every_priced_line_and_every_section_heading_arrives(imported: ImportedBOQ) -> None:
    items = [p for p in imported.positions if not p.is_section]
    sections = [p for p in imported.positions if p.is_section]
    assert [p.ordinal for p in sections] == [ordinal for ordinal, _, _ in _SECTIONS]
    assert [p.ordinal for p in items] == [line[0] for _, _, lines in _SECTIONS for line in lines]


def test_the_priced_lines_add_up_to_the_net_total_the_file_states(imported: ImportedBOQ) -> None:
    # One number that catches both failures: a recap line imported as work
    # counts a section twice, a dropped line counts it short.
    items = [p for p in imported.positions if not p.is_section]
    assert round(sum(p.quantity * p.unit_rate for p in items), 2) == pytest.approx(_NET_TOTAL)


def test_no_ordinal_arrives_twice(imported: ImportedBOQ) -> None:
    ordinals = [p.ordinal for p in imported.positions]
    assert len(ordinals) == len(set(ordinals))


def test_every_line_left_out_is_named_with_its_kind_and_amount(imported: ImportedBOQ) -> None:
    left_out = [w for w in imported.warnings if w.get("code") == "summary_row_skipped"]
    kinds = [w["kind"] for w in left_out]
    section_count = len(_SECTIONS)
    # A total per section, the recap heading and a recap line per section,
    # then the net total, the tax line and the grand total.
    assert kinds == ["subtotal"] * section_count + ["recap"] * (1 + section_count) + ["subtotal", "tax", "grand_total"]
    assert left_out[-2]["amount"] == pytest.approx(_TAX)
    assert "PDV 25 %" in left_out[-2]["message"]
    assert imported.skipped == len(left_out)
    assert len(imported.metadata["summary_rows"]) == len(left_out)


def test_no_lump_sum_is_flagged_as_an_outlier(imported: ImportedBOQ) -> None:
    # Every lump sum in this file is priced far above the per-metre median,
    # which is what a lump sum is.
    outliers = [w for w in imported.warnings if "file median" in str(w.get("message", ""))]
    assert outliers == []


def test_a_per_unit_rate_far_above_the_median_is_still_flagged() -> None:
    # The exemption is for lump sums only; the check itself still works.
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Description", "Unit", "Quantity", "Unit Rate"])
    for index in range(5):
        sheet.append([f"Plaster, room {index}", "m2", 10, 12])
    sheet.append(["Plaster, typed with an extra zero", "m2", 10, 1200])
    sheet.append(["Site setup", "pauš.", 1, 1200])
    buffer = io.BytesIO()
    workbook.save(buffer)

    outliers = [w for w in _parse(buffer.getvalue()).warnings if "file median" in str(w.get("message", ""))]

    assert [w["ordinal"] for w in outliers] == ["6"]


# ── Summary rows in general ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("UKUPNO II. ZEMLJANI RADOVI", "subtotal"),
        ("Summe Titel 02 Erdarbeiten", "subtotal"),
        ("Total carried to collection", "subtotal"),
        ("Итого по разделу 2", "subtotal"),
        ("Razem dział 2", "subtotal"),
        ("PDV 25 %", "tax"),
        ("MwSt. 19 %", "tax"),
        ("TVA 20 %", "tax"),
        ("DPH 21 %", "tax"),
        ("SVEUKUPNO", "grand_total"),
        ("Grand total", "grand_total"),
        ("Total général TTC", "grand_total"),
        ("REKAPITULACIJA", "recap"),
        ("Zusammenstellung", "recap"),
        ("Récapitulatif", "recap"),
    ],
)
def test_a_summary_label_is_recognised_in_its_own_language(label: str, kind: str) -> None:
    matched = summary_label_kind(label)
    assert matched is not None
    assert matched[0] == kind


def test_a_recap_word_counts_only_as_the_whole_label() -> None:
    # "Summary of works" heads a section; "Summary" on its own heads a recap.
    assert summary_label_kind("Summary") == ("recap", True)
    assert summary_label_kind("Summary of works") is None


def test_no_summary_phrase_means_two_different_things() -> None:
    owners: dict[str, set[str]] = {}
    for words_by_kind in _SUMMARY_WORDS_BY_LANGUAGE.values():
        for kind, phrases in words_by_kind.items():
            assert kind in _SUMMARY_KINDS
            for phrase in phrases:
                owners.setdefault(normalise_label(phrase), set()).add(kind)
    assert {phrase: kinds for phrase, kinds in owners.items() if len(kinds) > 1} == {}


def _row(ordinal: str, description: str, unit: str = "", quantity: Any = None, rate: Any = None, total: Any = None):
    return {
        "ordinal": ordinal,
        "description": description,
        "unit": unit,
        "quantity": quantity,
        "unit_rate": rate,
        "total": total,
    }


def test_a_priced_line_is_work_whatever_its_label_says() -> None:
    kept, summary = partition_summary_rows([_row("1", "Total station survey, per day", "day", 3, 450, 1350)])
    assert len(kept) == 1
    assert summary == []


def test_a_heading_that_starts_with_a_summary_word_but_carries_no_amount_stays_a_section() -> None:
    kept, summary = partition_summary_rows([_row("A", "Total demolition of the east wing")])
    assert len(kept) == 1
    assert summary == []


def test_a_recap_page_without_a_heading_is_found_by_its_repeated_ordinals() -> None:
    rows = [
        _row("A", "Substructure"),
        _row("A.1", "Excavation", "m3", 10, 20, 200),
        _row("B", "Superstructure"),
        _row("B.1", "Columns", "m3", 5, 300, 1500),
        _row("A", "Substructure", total=200),
        _row("B", "Superstructure", total=1500),
    ]
    kept, summary = partition_summary_rows(rows)
    assert [row["ordinal"] for _, row in kept] == ["A", "A.1", "B", "B.1"]
    assert [(report["row"], report["kind"]) for report in summary] == [(6, "recap"), (7, "recap")]


def test_a_heading_after_a_recap_page_ends_the_recap() -> None:
    # A bill that puts the summary first and the detail after it.
    rows = [
        _row("", "Summary"),
        _row("A", "Substructure", total=200),
        _row("A", "Substructure"),
        _row("A.1", "Excavation", "m3", 10, 20, 200),
    ]
    kept, summary = partition_summary_rows(rows)
    assert [row["description"] for _, row in kept] == ["Substructure", "Excavation"]
    assert [report["kind"] for report in summary] == ["recap", "recap"]


# ── Running metre and lump sums ─────────────────────────────────────────────


@pytest.mark.parametrize("spelling", ["m'", "M'", "m’", "m′", "mʼ", "m´", " m' "])
def test_the_running_metre_written_with_a_prime_is_the_running_metre(spelling: str) -> None:
    assert normalise_unit(spelling) == "lm"
    created = PositionCreate(
        boq_id="00000000-0000-0000-0000-000000000001",
        ordinal="6.1",
        description="Opsav atike",
        unit=spelling,
        quantity=1,
    )
    assert created.unit == "lm"


@pytest.mark.parametrize("unsafe", ["m''", "'m", "m'; drop table", "x'", "m' or '1'='1"])
def test_an_apostrophe_anywhere_else_is_still_refused(unsafe: str) -> None:
    assert normalise_unit(unsafe) is None


@pytest.mark.parametrize(
    "unit", ["pauš.", "PAUS", "paušal", "psch", "Pauschal", "LS", "lsum", "forfait", "kpl.", "a corpo"]
)
def test_lump_sum_spellings_are_lump_sums(unit: str) -> None:
    assert is_lump_sum_unit(unit)


@pytest.mark.parametrize("unit", ["m2", "m'", "kom", "kg", "h", "", None])
def test_measured_units_are_not_lump_sums(unit: str | None) -> None:
    assert not is_lump_sum_unit(unit)
