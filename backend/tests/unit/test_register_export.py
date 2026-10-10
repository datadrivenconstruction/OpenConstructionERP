"""Tests for the shared register and record form renderer.

A register is a contractual record that gets attached to a letter, so these
tests pin what makes it one: the header says which project and when, the
footer says "page x of y" with the real total, the header row repeats, and
amounts and dates are written the way the project's market writes them.

They also pin the three rules the module exists to hold in one place:

* capitals follow the language (a Turkish "i" becomes "İ", never "I");
* an amount goes from ``Decimal`` to the page without passing through a
  float, and stays a number in a workbook;
* a catalogue that declares a language without a complete table does not
  import, so "listed as supported, printed in English" cannot happen.

Text assertions go through ``pypdf`` extraction, like the RFI PDF tests.
"""

from __future__ import annotations

import io
import unicodedata
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from app.core import register_export
from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, font_can_draw_all, register_pdf_fonts
from app.core.regional_format import ANGLO, CONTINENTAL
from app.core.register_export import (
    FURNITURE,
    DocumentCatalogue,
    ProjectHeader,
    RecordBlock,
    RecordDocument,
    RegisterColumn,
    RegisterDocument,
    TableLayout,
    build_record_pdf,
    build_register_pdf,
    build_register_xlsx,
    caps,
    export_filename,
    format_amount,
    format_count,
    format_stored_date,
    grid_rows,
    person_name,
    printed_currency,
    record_table_layout,
    record_text_lines,
    register_layout,
    register_text_rows,
    register_total_rows,
    short_digest,
    table_layout,
    xlsx_date_format,
)

TURKISH_LETTERS = "ç ğ ı İ ö ş ü Ç Ğ I i Ö Ş Ü"


@pytest.fixture(autouse=True)
def _no_company_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a company profile on the machine running the tests out of them."""
    monkeypatch.setattr("app.core.company_profile.read_company_profile", lambda: {})


def _text(pdf: bytes) -> str:
    raw = " ".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(pdf)).pages)
    return " ".join(unicodedata.normalize("NFC", raw).replace(" ", " ").split())


def _register(rows: list[list[Any]], **overrides: Any) -> RegisterDocument:
    params: dict[str, Any] = {
        "title": "Ölçüm Kayıt Listesi",
        "columns": [
            RegisterColumn("Kod"),
            RegisterColumn("Açıklama", weight=3.0, wrap=True),
            RegisterColumn("Tarih", kind="date"),
            RegisterColumn("Tutar", kind="money"),
            RegisterColumn("Gün", kind="count"),
        ],
        "rows": rows,
        "details": [("Proje", "Işıklı Veri Merkezi"), ("Proje no.", "TR-001")],
        "locale": "tr",
        "date_format": "%d.%m.%Y",
        "number_style": CONTINENTAL,
        "page_label": "Sayfa {page} / {total}",
        "generated_label": "Oluşturulma: {timestamp}",
        "generated": "10.10.2026 09:00 UTC",
        "empty_text": "Kayıt yok.",
    }
    params.update(overrides)
    return RegisterDocument(**params)


# ── Fonts ─────────────────────────────────────────────────────────────────


def test_the_bundled_faces_are_registered_and_draw_every_turkish_letter() -> None:
    """The fallback face is WinAnsi Helvetica, which has no ğ, ı, İ or ş.

    A silent fallback is the realistic way a Turkish document breaks, so the
    registration itself is asserted, not only the glyph coverage.
    """
    assert register_pdf_fonts() is True
    assert font_can_draw_all(BODY_FONT, TURKISH_LETTERS)
    assert font_can_draw_all(BOLD_FONT, TURKISH_LETTERS)


# ── Capitals ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Geçersiz", "GEÇERSİZ"),
        ("İncelemede", "İNCELEMEDE"),
        ("Arşivlendi", "ARŞİVLENDİ"),
        ("Açık", "AÇIK"),
        ("Kapatıldı", "KAPATILDI"),
        ("Revize edip yeniden sunun", "REVİZE EDİP YENİDEN SUNUN"),
    ],
)
def test_turkish_capitals_keep_the_dot_and_the_dotless_i(label: str, expected: str) -> None:
    assert caps(label, "tr") == expected
    assert caps(label, "tr-TR") == expected


def test_plain_upper_would_have_dropped_the_dot() -> None:
    """The defect ``caps`` exists for, stated as a fact about ``str.upper``."""
    assert "Geçersiz".upper() == "GEÇERSIZ"
    assert caps("Geçersiz", "tr") != "Geçersiz".upper()


def test_other_languages_use_plain_capitals() -> None:
    assert caps("Revise and resubmit", "en") == "REVISE AND RESUBMIT"
    assert caps("Ανοιχτό", "el") == "ΑΝΟΙΧΤΟ"


# ── Value formatting ──────────────────────────────────────────────────────


def test_an_amount_is_written_in_the_markets_separators_with_its_currency() -> None:
    assert format_amount(Decimal("1234.56"), CONTINENTAL, "try") == "1.234,56 TRY"
    assert format_amount(Decimal("1234.56"), ANGLO, "USD") == "1,234.56 USD"
    assert format_amount("1234567.5", CONTINENTAL) == "1.234.567,50"
    assert format_amount(Decimal("-0.004"), CONTINENTAL) == "0,00"


def test_an_amount_never_passes_through_a_float() -> None:
    """2.675 is 2.67499... as a float; a person rounding it writes 2,68."""
    assert format_amount(Decimal("2.675"), CONTINENTAL) == "2,68"
    assert format_amount(Decimal("123456789012.345"), CONTINENTAL) == "123.456.789.012,35"


@pytest.mark.parametrize("missing", [None, "", "  ", "abc", True, Decimal("NaN")])
def test_a_missing_amount_is_a_dash_not_a_zero(missing: Any) -> None:
    assert format_amount(missing, CONTINENTAL, "TRY") == "-"


def test_dates_read_every_stored_shape() -> None:
    assert format_stored_date("2026-10-10", "%d.%m.%Y") == "10.10.2026"
    assert format_stored_date("2026-10-10T08:30:00+00:00", "%d.%m.%Y") == "10.10.2026"
    assert format_stored_date(date(2026, 1, 5), "%d.%m.%Y") == "05.01.2026"
    assert format_stored_date(datetime(2026, 1, 5, 23, 0, tzinfo=UTC), "%d.%m.%Y") == "05.01.2026"
    assert format_stored_date(None, "%d.%m.%Y") == "-"
    assert format_stored_date("sonra", "%d.%m.%Y") == "sonra"
    assert xlsx_date_format("%d.%m.%Y") == "DD.MM.YYYY"
    assert xlsx_date_format("%Y-%m-%d") == "YYYY-MM-DD"


def test_counts_people_and_filenames() -> None:
    assert format_count(3) == "3"
    assert format_count(None) == "-"
    resolved = "8f6203d9-f81a-41f9-acb3-d67bc5d8187c"
    assert person_name(resolved, {resolved: "Çağrı Öztürk"}) == "Çağrı Öztürk"
    # An account that no longer resolves prints a dash: no part of a UUID
    # belongs on a document meant for people.
    assert person_name("0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d", {}) == "-"
    assert person_name("İsmail Şahin", {}) == "İsmail Şahin"
    assert person_name(None, {}) == "-"
    assert export_filename("SUB/012 a", "x", "pdf") == "SUB_012_a.pdf"
    assert export_filename("", "submittal", "pdf") == "submittal.pdf"


def test_a_project_header_labels_itself_and_picks_its_separators() -> None:
    turkish = ProjectHeader(name="Işıklı Veri Merkezi", code="TR-001", currency="TRY", country="TR")
    assert turkish.label == "Işıklı Veri Merkezi (TR-001)"
    assert turkish.number_style == CONTINENTAL
    assert ProjectHeader(name="Depot", currency="USD").number_style == ANGLO
    assert ProjectHeader().label == "-"


# ── Catalogue ─────────────────────────────────────────────────────────────


def test_the_page_furniture_is_complete_in_every_language() -> None:
    english = FURNITURE["en"]
    for locale, table in FURNITURE.items():
        assert set(table) == set(english), locale
        assert all(value.strip() for value in table.values()), locale
        assert "%" not in date(2026, 9, 10).strftime(table["date_format"]), locale


def test_a_language_declared_without_its_strings_does_not_import() -> None:
    with pytest.raises(ValueError, match="tr: strings missing"):
        DocumentCatalogue({"en": {"title": "Log", "col": "Code"}, "tr": {"title": "Liste"}})


def test_a_language_declared_without_its_labels_does_not_import() -> None:
    strings = {"en": {"title": "Log"}, "tr": {"title": "Liste"}}
    with pytest.raises(ValueError, match="label table 'status'"):
        DocumentCatalogue(strings, {"status": {"en": {"open": "Open"}}})
    with pytest.raises(ValueError, match="label table 'status' missing"):
        DocumentCatalogue(strings, {"status": {"en": {"open": "Open", "closed": "Closed"}, "tr": {"open": "Açık"}}})


def test_a_language_without_page_furniture_does_not_import() -> None:
    with pytest.raises(ValueError, match="zz: no page furniture"):
        DocumentCatalogue({"en": {"title": "Log"}, "zz": {"title": "Log"}})


def test_catalogue_lookups_fall_back_and_count_days() -> None:
    catalogue = DocumentCatalogue(
        {"en": {"title": "Log"}, "tr": {"title": "Liste"}},
        {"status": {"en": {"open": "Open"}, "tr": {"open": "Açık"}}},
    )
    assert catalogue.supported == ("en", "tr")
    assert catalogue.normalize("tr-TR") == "tr"
    assert catalogue.normalize("zz") == "en"
    assert catalogue.resolve(None, "zz-ZZ,tr;q=0.8") == "tr"
    assert catalogue.resolve("en", "tr") == "en"
    assert catalogue.tr("tr", "title") == "Liste"
    assert catalogue.tr("tr", "project") == "Proje"
    assert catalogue.label("status", "open", "tr") == "Açık"
    assert catalogue.label("status", "parked", "tr") == "parked"
    assert catalogue.label("status", None, "tr") == "-"
    assert catalogue.days(1, "en") == "1 day"
    assert catalogue.days(3, "en") == "3 days"
    assert catalogue.days(3, "tr") == "3 gün"
    assert catalogue.days(None, "tr") == "-"
    assert catalogue.yes_no(True, "tr") == "Evet"


# ── Register ──────────────────────────────────────────────────────────────


def test_register_cells_are_formatted_by_kind() -> None:
    document = _register([["İ-01", "Şantiye ölçümü", "2026-10-10", Decimal("1234.56"), 7]])
    assert register_text_rows(document) == [
        ["Kod", "Açıklama", "Tarih", "Tutar", "Gün"],
        ["İ-01", "Şantiye ölçümü", "10.10.2026", "1.234,56", "7"],
    ]


def test_a_row_with_the_wrong_number_of_cells_fails_loudly() -> None:
    with pytest.raises(ValueError, match="zip"):
        register_text_rows(_register([["İ-01", "eksik"]]))


def test_register_pdf_carries_header_rows_and_page_x_of_y() -> None:
    rows = [
        [f"K-{index:03d}", "Çığ düşmesi öncesi ölçüm", "2026-10-10", Decimal("1234.56"), index]
        for index in range(1, 120)
    ]
    pdf = build_register_pdf(_register(rows))
    assert pdf.startswith(b"%PDF")
    pages = [unicodedata.normalize("NFC", page.extract_text() or "") for page in PdfReader(io.BytesIO(pdf)).pages]
    total = len(pages)
    assert total >= 3
    for number, page in enumerate(pages, 1):
        flat = " ".join(page.replace(" ", " ").split())
        assert f"Sayfa {number} / {total}" in flat
        # The header row repeats on every sheet.
        assert "Açıklama" in flat
    text = _text(pdf)
    for expected in ("Ölçüm Kayıt Listesi", "Işıklı Veri Merkezi", "TR-001", "10.10.2026", "1.234,56", "K-119"):
        assert expected in text, expected
    assert "Oluşturulma: 10.10.2026 09:00 UTC" in text


def test_an_empty_register_says_so() -> None:
    assert "Kayıt yok." in _text(build_register_pdf(_register([])))


def test_user_text_is_printed_not_parsed_as_markup() -> None:
    text = _text(build_register_pdf(_register([["K-1", "<b>kalın</b> & <font color=red>x</font>", None, None, None]])))
    assert "<b>kalın</b> & <font color=red>x</font>" in text


def test_register_workbook_keeps_dates_and_amounts_as_values() -> None:
    document = _register(
        [
            ["İ-01", "Şantiye ölçümü", "2026-10-10", Decimal("1234.56"), 7],
            ["=cmd|'/c calc'!A0", "-", None, None, None],
        ],
        sheet_title="Çok uzun bir sayfa adı: otuz bir karakteri aşar",
    )
    ws = load_workbook(build_register_xlsx(document)).active
    assert len(ws.title) <= 31
    assert ":" not in ws.title
    cells = {cell.value: cell for row in ws.iter_rows() for cell in row if cell.value is not None}
    assert "Ölçüm Kayıt Listesi" in cells
    assert "Proje: Işıklı Veri Merkezi" in cells
    header_row = cells["Kod"].row
    assert [cell.value for cell in ws[header_row]] == ["Kod", "Açıklama", "Tarih", "Tutar", "Gün"]
    first = ws[header_row + 1]
    assert first[0].value == "İ-01"
    assert first[2].value.date() == date(2026, 10, 10)
    assert first[2].number_format == "DD.MM.YYYY"
    assert first[3].value == pytest.approx(1234.56)
    assert first[3].number_format == "#,##0.00"
    assert first[4].value == 7
    second = ws[header_row + 2]
    # A formula payload is neutralised, and a dash is an empty cell.
    assert second[0].value == "'=cmd|'/c calc'!A0"
    assert second[1].value is None
    assert ws.page_setup.orientation == "landscape"


# ── Record form ───────────────────────────────────────────────────────────


def _record(**overrides: Any) -> RecordDocument:
    params: dict[str, Any] = {
        "title": "Onay Belgesi",
        "number": "SUB-012",
        "project_label": "Işıklı Veri Merkezi (TR-001)",
        "status_text": caps("İncelemede", "tr"),
        "subject": "Soğutma grubu imalat çizimi",
        "grid": [["Proje", "Işıklı Veri Merkezi (TR-001)", "Tür", "İmalat çizimi"]],
        "blocks": [
            RecordBlock("İnceleyen yorumları", text="Kolon aksları ile çakışıyor.\nİkinci satır."),
            RecordBlock("Notlar", text="", empty_text="Not kaydedilmedi."),
            RecordBlock(
                "Kalemler",
                kind="table",
                rows=[["Açıklama", "Tutar"], ["Çelik boru", "1.234,56"]],
                weights=[3, 1],
                right_aligned=[False, True],
            ),
            RecordBlock("İmzalar", kind="signatures", rows=[["", "Ad soyad", "İmza", "Tarih"], ["Sunan", "", "", ""]]),
        ],
        "page_label": "Sayfa {page} / {total}",
        "generated_label": "Oluşturulma: {timestamp}",
        "generated": "10.10.2026 09:00 UTC",
    }
    params.update(overrides)
    return RecordDocument(**params)


def test_record_form_prints_every_section() -> None:
    document = _record()
    pdf = build_record_pdf(document)
    assert pdf.startswith(b"%PDF")
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1
    text = _text(pdf)
    for expected in (
        "Onay Belgesi",
        "SUB-012 · Işıklı Veri Merkezi (TR-001)",
        "İNCELEMEDE",
        "Soğutma grubu imalat çizimi",
        "İmalat çizimi",
        "Kolon aksları ile çakışıyor.",
        "İkinci satır.",
        "Not kaydedilmedi.",
        "Çelik boru",
        "1.234,56",
        "İmzalar",
        "Sayfa 1 / 1",
    ):
        assert expected in text, expected
    assert "İnceleyen yorumları" in record_text_lines(document)


def test_a_long_record_runs_on_and_counts_its_pages() -> None:
    pdf = build_record_pdf(_record(blocks=[RecordBlock("Açıklama", text="Uzun bir açıklama satırı. " * 900)]))
    pages = len(PdfReader(io.BytesIO(pdf)).pages)
    assert pages >= 3
    assert f"Sayfa {pages} / {pages}" in _text(pdf)


# ── Layout: nothing that must stay whole is ever cut ──────────────────────

_LONG_PERSON = "İsmail Çağrı Öztürk-Işıktaş (Örnek Mekanik Tesisat Taahhüt, Teknik Ofis Şefi)"
_LONG_TEXT = (
    "Soğutma grubu (chiller) imalat çizimi ve ölçüm föyü; iç tesisat şaftı ile ısıtma kolonları "
    "arasındaki çakışma, üçüncü kat döşeme geçişleri ve yangın damperi yerleşimi hakkında"
)
_RUNNING = "Değişiklik Emirleri Kayıt Listesi · TR-001"


def _wide_register(count: int = 64, **overrides: Any) -> RegisterDocument:
    """The reviewer's worst case: eleven columns, long names, amounts in the billions."""
    columns = [
        RegisterColumn("Belge no.", nobreak=True),
        RegisterColumn("Konu", weight=3.0, wrap=True),
        RegisterColumn("Durum"),
        RegisterColumn("Sorumlu", weight=1.5),
        RegisterColumn("Oluşturma tarihi", kind="date"),
        RegisterColumn("Yanıt son tarihi", kind="date"),
        RegisterColumn("Yüklenici talebi", kind="money", total=True),
        RegisterColumn("Mühendis değerlendirmesi", kind="money", total=True),
        RegisterColumn("Para birimi", kind="currency"),
        RegisterColumn("Süre etkisi (gün)", kind="count"),
        RegisterColumn("Kayıt kimliği", pdf=False),
    ]
    rows = [
        [
            f"DE-2026-{index:04d}",
            _LONG_TEXT,
            "Değerlendirmede",
            _LONG_PERSON,
            "2026-12-28",
            "2027-01-04",
            Decimal("1234567890.12"),
            Decimal("987654321.09"),
            "TRY",
            index,
            "8f6203d9-f81a-41f9-acb3-d67bc5d8187c",
        ]
        for index in range(1, count + 1)
    ]
    params: dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "totals_label": "Toplam",
        "currency_column": 8,
        "currency": "TRY",
        "title": "Değişiklik Emirleri Kayıt Listesi",
    }
    params.update(overrides)
    return _register(params.pop("rows"), **params)


def _page_texts(pdf: bytes) -> list[str]:
    return [
        " ".join(unicodedata.normalize("NFC", page.extract_text() or "").replace(" ", " ").split())
        for page in PdfReader(io.BytesIO(pdf)).pages
    ]


def _assert_keep_together_cells_fit(
    rows: list[list[str]], keep: list[bool], layout: TableLayout, bold_from: int
) -> None:
    """Every cell that must stay on one line, measured in its face and size, fits its column."""
    pad = 2 * register_export._TABLE_CELL_PAD
    for row_index, row in enumerate(rows):
        bold = row_index == 0 or row_index >= bold_from
        for column, text in enumerate(row):
            if row_index == 0:
                pieces = text.split()
            elif keep[column]:
                pieces = [text]
            else:
                continue
            for piece in pieces:
                width = register_export._unit_width(piece, bold=bold) * layout.font_size
                assert width + pad <= layout.widths[column] + 0.01, (row_index, column, piece)


def test_a_wide_register_keeps_every_number_date_and_amount_whole() -> None:
    document = _wide_register()
    layout = register_layout(document)
    assert layout.overflow == ()
    assert sum(layout.widths) == pytest.approx(841.89 - 2 * 15 * 72 / 25.4, abs=0.5)
    rows, columns, totals = register_export._register_print(document)
    _assert_keep_together_cells_fit(rows, [column.keeps_together for column in columns], layout, len(rows) - totals)

    text = " ".join(_page_texts(build_register_pdf(document)))
    # A cell the paragraph engine cut comes out of the extraction with a
    # space inside it, so finding the whole token is the proof it was not.
    for expected in ("DE-2026-0001", "DE-2026-0064", "28.12.2026", "04.01.2027", "1.234.567.890,12", "987.654.321,09"):
        assert expected in text, expected
    assert text.count("DE-2026-") == 64
    assert text.count("1.234.567.890,12") == 64
    assert "8f6203d9" not in text


def test_a_register_too_wide_for_eight_points_steps_the_font_down_first() -> None:
    amounts = [RegisterColumn(f"Tutar {number}", kind="money") for number in range(1, 11)]
    crowded = _register([[Decimal("1234567890.12")] * 10], columns=amounts)
    layout = register_layout(crowded)
    assert 6.5 <= layout.font_size < 8.0
    assert layout.overflow == ()
    assert "1.234.567.890,12" in " ".join(_page_texts(build_register_pdf(crowded)))
    assert register_layout(_wide_register()).font_size == 8.0
    roomy = register_layout(_register([["İ-01", "Şantiye ölçümü", "2026-10-10", Decimal("1234.56"), 7]]))
    assert roomy.font_size == 8.0
    assert roomy.overflow == ()


def test_a_table_that_cannot_keep_its_numbers_whole_says_so() -> None:
    rows = [["No.", "Tutar"], ["DE-2026-0001-REV-A-ÇOK-UZUN-BİR-BELGE-NUMARASI", "1.234.567.890,12"]]
    assert table_layout(rows, [1, 1], 120.0, keep_together=[True, True]).overflow != ()
    assert table_layout(rows, [1, 1], 600.0, keep_together=[True, True]).overflow == ()


def test_free_text_wraps_between_words_and_takes_the_slack() -> None:
    document = _wide_register(count=3)
    layout = register_layout(document)
    _rows, columns, _totals = register_export._register_print(document)
    subject = next(index for index, column in enumerate(columns) if column.wrap)
    assert layout.widths[subject] == max(layout.widths)
    text = " ".join(_page_texts(build_register_pdf(document)))
    for word in ("çakışma,", "yerleşimi", "Öztürk-Işıktaş", "Değerlendirmede", "Mühendis", "değerlendirmesi"):
        assert word in text, word


def test_totals_are_printed_per_currency_and_never_added_across() -> None:
    rows = [list(row) for row in _wide_register(count=4).rows]
    rows[1][8] = "EUR"
    rows[3][8] = "EUR"
    mixed = _wide_register(rows=rows)
    totals = register_total_rows(mixed)
    assert [row[0] for row in totals] == ["Toplam (TL)", "Toplam (EUR)"]
    assert totals[0][6] == totals[1][6] == "2.469.135.780,24"
    assert totals[0][7] == "1.975.308.642,18"
    text = " ".join(_page_texts(build_register_pdf(mixed)))
    assert "Toplam (TL)" in text
    assert "Toplam (EUR)" in text
    # Four rows of one amount: a sum across both currencies would be this.
    assert "4.938.271.560,48" not in text
    assert "Para birimi" in text

    single = _wide_register(count=4)
    assert [row[0] for row in register_total_rows(single)] == ["Toplam (TL)"]
    single_text = " ".join(_page_texts(build_register_pdf(single)))
    assert "4.938.271.560,48" in single_text
    # Every row is in the currency the register states, so the column is not printed.
    assert "Para birimi" not in single_text


def test_a_row_without_an_amount_adds_nothing_to_a_total() -> None:
    rows = [list(row) for row in _wide_register(count=2).rows]
    rows[1][6] = None
    rows[1][7] = None
    assert register_total_rows(_wide_register(rows=rows))[0][6] == "1.234.567.890,12"
    assert register_total_rows(_wide_register(rows=[])) == []


def test_an_empty_register_prints_its_header_row_and_no_totals() -> None:
    document = _wide_register(rows=[])
    assert register_layout(document).overflow == ()
    pages = _page_texts(build_register_pdf(document))
    assert len(pages) == 1
    assert "Kayıt yok." in pages[0]
    assert "Belge no." in pages[0]
    assert "Toplam" not in pages[0]
    assert "Sayfa 1 / 1" in pages[0]


def test_continuation_pages_say_which_register_they_belong_to() -> None:
    pages = _page_texts(build_register_pdf(_wide_register()))
    assert len(pages) >= 3
    for number, page in enumerate(pages, 1):
        assert f"Sayfa {number} / {len(pages)}" in page
        assert page.count("Belge no.") == 1, number
        assert (_RUNNING in page) == (number > 1), number


def test_the_table_header_is_never_repeated_in_the_middle_of_a_page() -> None:
    body = [[f"KLM-{index:03d}", f"{_LONG_TEXT} {_LONG_TEXT}", "1.234.567.890,12"] for index in range(1, 41)]
    block = RecordBlock(
        "Kalemler",
        kind="table",
        rows=[["Kalem no.", "Açıklama", "Maliyet farkı (TL)"], *body, ["Toplam (TL)", "", "49.382.715.604,80"]],
        weights=[1, 4, 1.4],
        right_aligned=[False, False, True],
        keep_together=[True, False, True],
        total_rows=1,
    )
    assert record_table_layout(block).overflow == ()
    pdf = build_record_pdf(_record(blocks=[RecordBlock("Açıklama", text="Kısa açıklama."), block]))
    pages = _page_texts(pdf)
    assert len(pages) >= 2
    for number, page in enumerate(pages, 1):
        # One header per sheet: a second one means a row was cut and the
        # header printed again under it.
        assert page.count("Kalem no.") <= 1, number
        if number > 1:
            assert "Onay Belgesi SUB-012 · Işıklı Veri Merkezi (TR-001)" in page, number
        assert f"Sayfa {number} / {len(pages)}" in page
    text = " ".join(pages)
    assert text.count("KLM-") == 40
    # Every row is whole on one sheet: its number and its amount share a page.
    for page in pages:
        assert page.count("KLM-") == page.count("1.234.567.890,12")
    assert "49.382.715.604,80" in text


def test_printed_currency_digest_and_grid_helpers() -> None:
    assert printed_currency("TRY", "tr") == "TL"
    assert printed_currency("try", "tr-TR") == "TL"
    assert printed_currency("TRY", "en") == "TRY"
    assert printed_currency("EUR", "tr") == "EUR"
    assert printed_currency(None, "tr") == ""
    assert format_amount(Decimal("1234.5"), CONTINENTAL, "TRY", locale="tr") == "1.234,50 TL"
    assert format_amount(Decimal("1234.5"), CONTINENTAL, "TRY") == "1.234,50 TRY"
    digest = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    assert short_digest(digest) == "9f86 d081 884c 7d65"
    assert short_digest("") == "-"
    assert grid_rows([("Tür", "Yazı"), None, ("Tarih", "10.10.2026"), ("Konu", "x")]) == [
        ["Tür", "Yazı", "Tarih", "10.10.2026"],
        ["Konu", "x", "", ""],
    ]


def test_a_workbook_keeps_iso_codes_ids_and_numeric_totals() -> None:
    ws = load_workbook(build_register_xlsx(_wide_register(count=3))).active
    # Cut between words: thirty-one characters would end in "Liste".
    assert ws.title == "Değişiklik Emirleri Kayıt"
    values = [[cell.value for cell in row] for row in ws.iter_rows()]
    total = next(row for row in values if str(row[0] or "").startswith("Toplam"))
    assert total[0] == "Toplam (TRY)"
    assert total[6] == pytest.approx(3703703670.36)
    header = next(row for row in values if row[0] == "Belge no.")
    assert "Para birimi" in header
    assert "Kayıt kimliği" in header


def test_signature_rows_carry_name_title_date_and_signature() -> None:
    catalogue = DocumentCatalogue({"en": {"title": "Form"}, "tr": {"title": "Form"}})
    rows = catalogue.signature_rows("tr", [("Hazırlayan", "İsmail Şahin"), ("Onaylayan", "-")])
    assert rows == [
        ["", "Adı Soyadı", "Görevi", "Tarih", "İmza"],
        ["Hazırlayan", "İsmail Şahin", "", "", ""],
        ["Onaylayan", "", "", "", ""],
    ]


def test_figures_follow_the_projects_country_and_words_the_language() -> None:
    catalogue = DocumentCatalogue({"en": {"title": "Log"}, "tr": {"title": "Liste"}})
    project = ProjectHeader(name="Işıklı Veri Merkezi", code="TR-001", currency="TRY", country="TR")
    assert catalogue.date_format("en", project) == "%d.%m.%Y"
    assert catalogue.date_format("tr", project) == "%d.%m.%Y"
    assert catalogue.furniture("tr", project)["currency"] == "TRY"
    assert catalogue.furniture("tr", project)["totals_label"] == "Toplam"
    assert catalogue.furniture("en")["page_label"] == "Page {page} of {total}"


@pytest.mark.parametrize("lines", [40, 52, 56, 58, 60, 62, 64, 70, 140])
def test_a_row_about_as_tall_as_a_page_still_prints(lines: int) -> None:
    """A row near the height of the frame must neither loop nor fail the export.

    The table sends a row to the next page when it does not fit what is left
    of this one. A row that would not fit a whole page either has to be cut
    instead, or the build never finishes.
    """
    tall = "\n".join(f"Satır {number}: şaft içi ölçüm" for number in range(1, lines + 1))
    block = RecordBlock(
        "Kalemler",
        kind="table",
        rows=[["Kalem no.", "Açıklama"], ["KLM-001", "Kısa"], ["KLM-002", tall], ["KLM-003", "Son"]],
        weights=[1, 5],
        keep_together=[True, False],
    )
    pages = _page_texts(build_record_pdf(_record(blocks=[block])))
    text = " ".join(pages)
    for expected in ("KLM-001", "KLM-002", "KLM-003", "Satır 1:", f"Satır {lines}:"):
        assert expected in text, expected


def test_workbook_details_are_grouped_to_the_width_of_the_table() -> None:
    details = [(f"Etiket {number}", "değer " * 4) for number in range(1, 8)]
    lines = register_export._xlsx_detail_lines(details, table_chars=120.0)
    assert len(lines) == 3
    assert all(len(line) <= 120 for line in lines)
    assert sum(line.count("Etiket") for line in lines) == 7
    # Too narrow a table for three lines: nothing is dropped, the lines run long.
    crowded = register_export._xlsx_detail_lines(details, table_chars=40.0)
    assert len(crowded) == 3
    assert sum(line.count("Etiket") for line in crowded) == 7
    assert register_export._xlsx_detail_lines(details[:2], table_chars=10.0) == [
        f"{label}: {value}" for label, value in details[:2]
    ]
