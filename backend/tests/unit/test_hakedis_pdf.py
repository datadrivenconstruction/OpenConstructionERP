# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The hakediş PDF carries the Turkish form, in Turkish, with Turkish numbers.

A certificate that does not look like the document a cost control department
files is refused whatever its arithmetic, so these tests read the page back:
the labels with their diacritics, the amounts as ``1.234,56``, the dates as
``31.07.2026``, the fixture's own Turkish descriptions, the page furniture,
and the draft banner, which has to be there exactly when a figure is not final.

The text is read with PyMuPDF, a declared dependency. The fixture and its
SYNTHETIC rates are those of ``test_hakedis_math``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pymupdf
import pytest

import app.modules.contracts.hakedis_pdf as hakedis_pdf
from app.modules.contracts.hakedis import Certificate, compute_certificate, expected_tax_bases
from app.modules.contracts.hakedis_layout import resolve_settings
from app.modules.contracts.hakedis_pdf import render_hakedis_pdf
from tests.unit.test_hakedis_math import (
    CONTRACT_TERMS,
    EXPECTED,
    certificate_input,
    certify,
    lump_sum_input,
    synthetic_taxes,
)

# The suite must read the tree's copy of the renderer, not an installed one.
assert "site-packages" not in hakedis_pdf.__file__, hakedis_pdf.__file__

D = Decimal


def pages_of(pdf: bytes) -> list[str]:
    """The text of every page with its whitespace collapsed, so a wrapped label still reads."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pages = [re.sub(r"\s+", " ", page.get_text()) for page in doc]
    # No page of any test may show an unfilled placeholder.
    assert not any("{" in page or "}" in page for page in pages)
    return pages


def sizes_of(pdf: bytes) -> list[tuple[int, int]]:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return [(round(page.rect.width), round(page.rect.height)) for page in doc]


def parts_of(pdf: bytes) -> tuple[str, str]:
    """The summary (the portrait pages) and the works list (the landscape pages) as text."""
    texts, sizes = pages_of(pdf), sizes_of(pdf)
    summary = " ".join(text for text, (width, height) in zip(texts, sizes, strict=True) if width < height)
    works = " ".join(text for text, (width, height) in zip(texts, sizes, strict=True) if width > height)
    return summary, works


def tr_number(value: Decimal) -> str:
    whole, _, fraction = f"{value:.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    groups = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return f"{sign}{'.'.join(groups)},{fraction}"


@pytest.fixture(scope="module")
def first() -> Certificate:
    return certify(1, D("0"))


@pytest.fixture(scope="module")
def turkish(first: Certificate) -> list[str]:
    return pages_of(render_hakedis_pdf(first, locale="tr", issue_date=date(2026, 8, 3)))


def test_it_is_a_pdf_with_a_portrait_summary_and_a_landscape_works_list(first: Certificate) -> None:
    pdf = render_hakedis_pdf(first)
    assert pdf.startswith(b"%PDF")
    sizes = sizes_of(pdf)
    assert len(sizes) >= 2
    assert sizes[0] == (595, 842)
    assert all(size == (842, 595) for size in sizes[1:])


def test_the_summary_page_prints_the_form_in_turkish(turkish: list[str]) -> None:
    summary = turkish[0]
    for text in (
        "HAKEDİŞ RAPORU",
        "31.07.2026 TARİHİNE KADAR YAPILAN İŞİN",
        "Sözleşme Fiyatları İle Yapılan İş",
        "Fiyat Farkı Tutarı",
        "Toplam Tutar ( A + B )",
        "Bir Önceki Hakedişin Toplam Tutarı",
        "Bu Hakedişin Tutarı ( C - D )",
        "KDV ( E x %10 )",
        "Tahakkuk Tutarı",
        "KESİNTİLER VE MAHSUPLAR",
        "Gelir / Kurumlar Vergisi ( E x %2 )",
        "Damga Vergisi ( E - g x %1 )",
        "KDV Tevkifatı ( F x 1/2 )",
        "Sosyal Sigortalar Kurumu Kesintisi",
        "İdare Makinesi Kiraları",
        "Gecikme Cezası",
        "Avans Mahsubu ( E x %20 )",
        "Bu Hakedişle Ödenen Fiyat Farkı Teminat Kesintisi",
        "Teminat Kesintisi ( E x %10 )",
        "Kesintiler ve Mahsuplar Toplamı",
        "Yükleniciye Ödenecek Tutar ( G - H )",
        "YÜKLENİCİ",
        "DÜZENLEYENLER (YAPI DENETİM ELEMANLARI)",
        "ONAYLAYAN",
    ):
        assert text in summary, text
    # Never the ASCII upper-casing of a Turkish word.
    assert "HAKEDIŞ" not in summary and "IŞIN" not in summary and "KESINTILER" not in summary


def test_the_header_block_names_the_parties_with_their_tax_details(turkish: list[str]) -> None:
    summary = turkish[0]
    for text in (
        "İşin Adı",
        "Örnek Veri Merkezi İnşaatı",
        "Mekanik ve Elektrik Tesisat İşleri Alt Yüklenici Sözleşmesi",
        "ALT-2026-014",
        "İşveren",
        "Örnek Ana Yüklenici İnşaat A.Ş.",
        "Yüklenici - Vergi No",
        "9876543210",
        "Yüklenici - Vergi Dairesi",
        "Şişli",
        "Büyük Mükellefler",
        "Hakediş No",
        "1 (Geçici Hakediş)",
        "01.07.2026 - 31.07.2026",
        "Düzenleme Tarihi",
        "03.08.2026",
        "TRY",
    ):
        assert text in summary, text


def test_the_amounts_are_printed_the_turkish_way(first: Certificate, turkish: list[str]) -> None:
    summary = turkish[0]
    for letter, amount in EXPECTED[1].items():
        if amount is not None:
            assert f"{tr_number(amount)} TRY" in summary, letter
    assert "12.187.793,96 TRY" in summary
    assert "8.799.587,24 TRY" in summary
    assert "12,187,793.96" not in " ".join(turkish)
    # A line that does not apply prints a dash, never a zero amount.
    assert summary.count("0,00 TRY") == 2, "line D of a first certificate and the entered zero, nothing else"


def test_the_works_list_prints_every_row_with_its_turkish_description(first: Certificate, turkish: list[str]) -> None:
    works = " ".join(turkish[1:])
    for text in (
        "YAPILAN İŞLER LİSTESİ",
        "(Teklif Birim Fiyatlı İş)",
        "Sıra No",
        "Poz No",
        "İşin Tanımı",
        "Birimi",
        "Teklif Birim Fiyat",
        "D=B-C",
        "E=AxB",
        "G=E-F",
        "01 - MEKANİK TESİSAT",
        "02 - ELEKTRİK TESİSATI",
        "Ara Toplam",
        "Siyah çelik boru DN50, dişli, yangın tesisatı",
        "Sprinkler başlığı, sarkık tip, 68°C",
        "Klima santrali, 20.000 m³/h, ısı geri kazanımlı",
        "Topraklama iletkeni, örgülü bakır 50 mm²",
        "Acil aydınlatma armatürü, kesintide 3 saat yanan",
        "M-27.040",
        "E-39.400",
        "1.000,255",
        "742,18",
    ):
        assert text in works, text
    for row in first.work_lines:
        assert row.code in works
        assert tr_number(row.cumulative_amount) in works, row.code
    assert tr_number(first.totals.cumulative_amount) in works
    assert first.totals.cumulative_amount == first.line("work_done").amount


def test_the_summary_with_its_signatures_keeps_to_one_page(first: Certificate, turkish: list[str]) -> None:
    assert sizes_of(render_hakedis_pdf(first))[1] == (842, 595)
    assert "ONAYLAYAN" in turkish[0] and "Adı Soyadı:" in turkish[0] and "İmza:" in turkish[0]


def test_the_column_header_is_repeated_on_every_works_page() -> None:
    inp = certificate_input(1, D("0"))
    cert = compute_certificate(replace(inp, lines=list(inp.lines) * 4, taxes=None))
    pdf = render_hakedis_pdf(cert)
    texts, sizes = pages_of(pdf), sizes_of(pdf)
    with_rows = [
        text for text, size in zip(texts, sizes, strict=True) if size == (842, 595) and re.search(r"[ME]-\d\d\.", text)
    ]
    assert len(with_rows) >= 3, "a hundred rows run past two landscape pages"
    for page in with_rows:
        assert "Poz No" in page and "G=E-F" in page and "İşin Tanımı" in page


def test_every_page_says_which_page_of_how_many_it_is(turkish: list[str]) -> None:
    total = len(turkish)
    for number, page in enumerate(turkish, start=1):
        assert f"Sayfa {number} / {total}" in page
        assert "Hakediş No: 1 - ALT-2026-014" in page


def test_a_final_certificate_says_so() -> None:
    final = certify(3, D("50024219.44"))
    summary = pages_of(render_hakedis_pdf(final))[0]
    assert "3 (Kesin Hakediş)" in summary
    assert "-15.600,00" in " ".join(pages_of(render_hakedis_pdf(final))[1:])


def test_english_prints_english_labels_over_the_same_turkish_numbers(first: Certificate) -> None:
    pdf = render_hakedis_pdf(first, locale="en")
    assert sizes_of(pdf)[1] == (842, 595), "the English summary keeps to one page as well"
    summary, works = parts_of(pdf)
    for text in (
        "PROGRESS PAYMENT CERTIFICATE",
        "WORK DONE UP TO 31.07.2026",
        "Work Done at Contract Prices",
        "Amount of This Certificate ( C - D )",
        "VAT ( E x 10% )",
        "DEDUCTIONS AND SET-OFFS",
        "Stamp Duty ( E - g x 1% )",
        "Amount Payable to the Contractor ( G - H )",
        "8.799.587,24 TRY",
        "CONTRACTOR",
        "APPROVED BY",
        "Page 1 / ",
    ):
        assert text in summary, text
    assert "Sözleşme Fiyatları" not in summary and "HAKEDİŞ RAPORU" not in summary
    assert "LIST OF WORKS DONE" in works and "Contract Unit Price" in works and "Subtotal" in works
    # The fixture's own data stays as it was written.
    assert "Sprinkler başlığı, sarkık tip, 68°C" in works


def test_bilingual_prints_the_turkish_label_with_the_english_under_it(first: Certificate) -> None:
    pdf = render_hakedis_pdf(first, locale="tr-en")
    summary, works = parts_of(pdf)
    assert all(size in ((595, 842), (842, 595)) for size in sizes_of(pdf))
    for text in (
        "HAKEDİŞ RAPORU",
        "PROGRESS PAYMENT CERTIFICATE",
        "Bu Hakedişin Tutarı ( C - D )",
        "Amount of This Certificate",
        "KESİNTİLER VE MAHSUPLAR",
        "DEDUCTIONS AND SET-OFFS",
        "Yükleniciye Ödenecek Tutar ( G - H )",
        "Amount Payable to the Contractor",
        "YÜKLENİCİ",
        "CONTRACTOR",
        "Sayfa 1 / ",
        "Page 1 / ",
    ):
        assert text in summary, text
    assert summary.index("HAKEDİŞ RAPORU") < summary.index("PROGRESS PAYMENT CERTIFICATE")
    assert summary.index("Bu Hakedişin Tutarı") < summary.index("Amount of This Certificate")
    assert "Poz No" in works and "Item Code" in works


def test_an_unknown_locale_is_refused(first: Certificate) -> None:
    with pytest.raises(ValueError, match="'de'"):
        render_hakedis_pdf(first, locale="de")


# ── The draft banner ──────────────────────────────────────────────────────

BANNER_TR = "TASLAK - Tutarların tamamı kesinleşmemiştir"
BANNER_EN = "DRAFT - not all figures are final"


def test_a_final_set_of_figures_carries_no_banner_and_no_notes(first: Certificate, turkish: list[str]) -> None:
    assert not first.is_draft
    text = " ".join(turkish)
    assert "TASLAK" not in text and "Beklemede" not in text and "AÇIKLAMALAR" not in text


def test_without_the_tax_module_every_page_is_a_draft_and_says_why() -> None:
    cert = certify(1, D("0"), taxes=None)
    pdf = render_hakedis_pdf(cert, locale="tr-en")
    for page in pages_of(pdf):
        assert BANNER_TR in page and BANNER_EN in page
    summary, _ = parts_of(pdf)
    assert "Beklemede / Held (1)" in summary
    assert "AÇIKLAMALAR / NOTES" in summary
    assert "(1) F) KDV: Vergi hesaplama modülü kurulu değil; vergi satırları hesaplanamadı." in summary
    assert "F) VAT: The tax calculation module is not installed; the tax lines could not be computed." in summary
    # The amount payable has no number to print, and prints the marker instead.
    assert not re.search(r"Amount Payable to the Contractor[^A-Za-z]*\d", summary)
    assert summary.count("Beklemede / Held") == 7, "four tax lines, G, H and the amount payable"


@pytest.mark.parametrize(
    ("change", "note"),
    [
        ({"review_status": "unconfirmed"}, "Kullanılan oran birincil kaynaktan teyit edilmemiştir."),
        ({"overridden": True}, "Hesaplanan tutar elle değiştirilmiştir."),
    ],
)
def test_an_unconfirmed_or_overridden_figure_prints_its_amount_under_the_banner(
    change: dict[str, object], note: str
) -> None:
    inp = certificate_input(1, D("0"))
    bases = expected_tax_bases(inp)
    taxes = synthetic_taxes(bases["vat_computed"], bases["stamp_duty"])
    taxes = replace(taxes, income_withheld=replace(taxes.income_withheld, **change))
    cert = compute_certificate(replace(inp, taxes=taxes))
    summary = pages_of(render_hakedis_pdf(cert))[0]
    assert BANNER_TR in summary
    assert "243.755,88 TRY (1)" in summary
    assert f"(1) a) Gelir / Kurumlar Vergisi: {note}" in summary
    assert "8.799.587,24 TRY" in summary
    assert "Beklemede" not in summary


def test_a_tax_line_prints_its_code_and_legal_basis(turkish: list[str]) -> None:
    summary = turkish[0]
    assert "Kod: SYN-W1, Dayanak: Synthetic withholding table, row 1" in summary
    assert "Kod: SYN-I1, Dayanak: Synthetic income withholding, article 1" in summary


# ── Lump sum and a contract's own layout ──────────────────────────────────


def test_a_lump_sum_works_list_prints_percentages_and_the_forms_columns() -> None:
    cert = compute_certificate(
        lump_sum_input([D("400000.00"), D("600000.00")], [D("40"), D("60")], D("25"), D("12.5"), taxes=None)
    )
    pages = pages_of(render_hakedis_pdf(cert))
    works = " ".join(pages[1:])
    for text in (
        "(Anahtar Teslimi Götürü Bedel İş)",
        "İş Programı Grubu %si (*)",
        "Yapılan İş",
        "Sözleşme Bedeli",
        "Gerçekleşen Toplam İmalat %si",
        "C=AxB",
        "F=B-D",
        "G=C-E",
        "40,00",
        "37,50",
        "12,50",
        "400.000,00",
        "150.000,00",
        "1.000.000,00",
        "375.000,00",
        "(*) İş programında belirlenen iş grubu yüzdesi.",
    ):
        assert text in works, text


def test_a_contracts_own_lines_roles_and_columns_reach_the_page() -> None:
    hakedis = dict(CONTRACT_TERMS["hakedis"])
    hakedis |= {
        "add": [{"key": "site_services", "op": "manual"}],
        "labels": {
            "tr": {"line.site_services": "Şantiye Hizmetleri Kesintisi"},
            "en": {"line.site_services": "Site Services Charge"},
        },
        "signature_roles": ["subcontractor", "control_engineer", "project_manager", "employer"],
        "columns": {
            "unit_price": ["seq", "code", "description", "unit", "contract_quantity", "unit_price",
                           "cumulative_quantity", "cumulative_amount", "previous_amount", "period_amount"],
        },
    }  # fmt: skip
    settings = resolve_settings("TR", {"hakedis": hakedis})
    inp = certificate_input(2, D("12187793.96"), layout=settings.layout, signature_roles=settings.signature_roles)
    manual = dict(inp.manual_lines) | {"site_services": inp.manual_lines["social_security"]}
    cert = compute_certificate(replace(inp, manual_lines=manual, taxes=None))
    summary, works = parts_of(render_hakedis_pdf(cert, settings=settings))
    assert "Şantiye Hizmetleri Kesintisi" in summary
    for role in ("ALT YÜKLENİCİ", "KONTROL MÜHENDİSİ", "PROJE MÜDÜRÜ", "İŞVEREN"):
        assert role in summary, role
    assert "ONAYLAYAN" not in summary
    assert "Örnek Mekanik ve Elektrik Taahhüt Ltd. Şti." in summary
    assert "Sözleşme Miktarı" in works
    assert "Bir Önceki Hakediş İmalat, İhzarat Miktarı" not in works
    # The over-measured sprinkler row is marked once the contract quantity is on the page.
    assert "900,00 (!)" in works
    assert "(!) Toplam miktar sözleşme miktarını aşmaktadır." in works


def test_markup_in_a_description_is_printed_not_parsed() -> None:
    inp = certificate_input(1, D("0"))
    lines = list(inp.lines)
    lines[0] = replace(lines[0], description="Boru <b>DN50</b> & bağlantı parçaları")
    cert = compute_certificate(replace(inp, lines=lines, project_name="AR&GE Binası <Faz 2>"))
    pages = pages_of(render_hakedis_pdf(cert))
    assert "AR&GE Binası <Faz 2>" in pages[0]
    assert "Boru <b>DN50</b> & bağlantı parçaları" in " ".join(pages[1:])


def test_a_tax_that_does_not_apply_prints_why_under_its_line() -> None:
    inp = certificate_input(1, D("0"))
    bases = expected_tax_bases(inp)
    taxes = synthetic_taxes(bases["vat_computed"], bases["stamp_duty"])
    below = replace(
        taxes.income_withheld,
        status="not_applicable",
        amount=None,
        reason_key="below_threshold",
        reason_params={"measured": "1500.5", "threshold": "20000", "currency": "TRY"},
    )
    cert = compute_certificate(replace(inp, taxes=replace(taxes, income_withheld=below)))
    summary, _ = parts_of(render_hakedis_pdf(cert, locale="tr-en"))
    assert "Uygulanmaz: 1.500,50 TRY, 20.000,00 TRY sınırının altında." in summary
    assert "Does not apply: 1.500,50 TRY is below the threshold of 20.000,00 TRY." in summary
    assert not cert.is_draft


def test_a_reason_is_printed_as_a_sentence_with_dates_the_documents_way_and_no_braces() -> None:
    inp = certificate_input(1, D("0"))
    bases = expected_tax_bases(inp)
    taxes = synthetic_taxes(bases["vat_computed"], bases["stamp_duty"])
    no_rate = replace(
        taxes.income_withheld,
        status="held",
        amount=None,
        reason_key="no_rate_on_date",
        reason_params={"code": "SYN-I1", "on": "2026-07-31"},
    )
    # A reason that arrives without the parameter its sentence needs.
    bare = replace(taxes.stamp_duty, status="not_applicable", amount=None, reason_key="not_applicable_by_user")
    cert = compute_certificate(
        replace(
            inp,
            taxes=replace(taxes, income_withheld=no_rate, stamp_duty=bare),
            tax_conditions={"vat_withholding": "Yalnızca belirlenmiş alıcılar için (sentetik koşul)"},
        )
    )
    summary, _ = parts_of(render_hakedis_pdf(cert))
    assert "31.07.2026 tarihinde SYN-I1 kodu için yürürlükte bir oran yok." in summary
    assert "Uygulanmaz olarak işaretlendi: ..." in summary
    assert "Koşul: Yalnızca belirlenmiş alıcılar için (sentetik koşul)" in summary
