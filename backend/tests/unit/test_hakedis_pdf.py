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
from datetime import UTC, date, datetime
from decimal import Decimal

import pymupdf
import pytest

import app.modules.contracts.hakedis_pdf as hakedis_pdf
from app.modules.contracts.hakedis import (
    Certificate,
    CertificateParty,
    compute_certificate,
    expected_tax_bases,
    printed_works,
)
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
        "Yüklenici Örnek Mekanik ve Elektrik Taahhüt Ltd. Şti.",
        "Vergi Dairesi: Şişli - Vergi No: 9876543210",
        "Vergi Dairesi: Büyük Mükellefler - Vergi No: 1234567890",
        "Adres: Şişli, İstanbul",
        "Hakediş No",
        "1 (Geçici Hakediş)",
        "01.07.2026 - 31.07.2026",
        "Düzenleme Tarihi",
        "03.08.2026",
        "Tutar (TL)",
    ):
        assert text in summary, text
    # The lira is written the way a Turkish form writes it, and no cell is left empty-handed.
    assert "TRY" not in summary


def test_the_amounts_are_printed_the_turkish_way(first: Certificate, turkish: list[str]) -> None:
    summary = turkish[0]
    for letter, amount in EXPECTED[1].items():
        if amount is not None:
            assert f"{tr_number(amount)} TL" in summary, letter
    assert "12.187.793,96 TL" in summary
    assert "8.799.587,24 TL" in summary
    assert "12,187,793.96" not in " ".join(turkish)
    # A line that does not apply prints a dash, never a zero amount.
    assert summary.count("0,00 TL") == 2, "line D of a first certificate and the entered zero, nothing else"


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
        "Page 1 of ",
        "Amounts and dates are written in Turkish notation (1.234,56 - DD.MM.YYYY).",
    ):
        assert text in summary, text
    assert "Sözleşme Fiyatları" not in summary and "HAKEDİŞ RAPORU" not in summary
    assert "LIST OF WORKS DONE" in works and "Contract Unit Price" in works and "Subtotal" in works
    # The fixture's own data stays as it was written.
    assert "Sprinkler başlığı, sarkık tip, 68°C" in works


def test_bilingual_prints_the_turkish_label_with_the_english_beside_it(first: Certificate) -> None:
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
        "Page 1 of ",
    ):
        assert text in summary, text
    # The legal basis of a tax line is data, and is printed once, not once per language.
    assert summary.count("Kod: SYN-W1, Dayanak: Synthetic withholding table, row 1") == 1
    assert "Code: SYN-W1" not in summary
    # The captions of a party's registration are words too, and print in both languages.
    assert "Vergi Dairesi / Tax Office: Şişli - Vergi No / Tax No.: 9876543210" in summary
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
    # Four lines held for one reason print that reason once.
    assert (
        "(1) (2) (3) (4) F) KDV, a) Gelir / Kurumlar Vergisi, b) Damga Vergisi, c) KDV Tevkifatı: "
        "Vergi hesaplama modülü kurulu değil; vergi satırları hesaplanamadı."
    ) in summary
    assert summary.count("Vergi hesaplama modülü kurulu değil") == 1
    assert (
        "F) VAT, a) Income / Corporate Tax Withholding, b) Stamp Duty, c) VAT Withholding: "
        "The tax calculation module is not installed; the tax lines could not be computed."
    ) in summary
    # The watermark is on the page as well as the banner, so a photocopy of the middle still says draft.
    assert "TASLAK / DRAFT" in summary
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
    assert "243.755,88 TL (1)" in summary
    assert f"(1) a) Gelir / Kurumlar Vergisi: {note}" in summary
    assert "8.799.587,24 TL" in summary
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
        # Column A is the group's own share, and the page says so.
        "İş Grubu Sözleşme Bedeli",
        "A sütunu iş grubunun sözleşme bedelindeki payını",
        "Para Birimi: TL",
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
    assert "(!) 900,00" in works
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


# ── What the reader of the printed sheet sees ─────────────────────────────
#
# The figures above can all be right on a document nobody would sign: a page
# that holds nothing but signature lines, a number broken over two lines, a
# sheet that does not say which certificate it belongs to. These tests render
# the hard case (a letterhead, party names of 120 characters, five signature
# roles) and read the pages back.

GENERATED = datetime(2026, 8, 3, 9, 30, tzinfo=UTC)
STAMP = "03.08.2026 09:30 UTC"
FIVE_ROLES = ("subcontractor", "quantity_surveyor", "control_engineer", "project_manager", "employer")
LONG_NUMBER = "ALT-2026-014/İST-ÇĞL"
LONG_EMPLOYER = CertificateParty(
    name=(
        "Örnek IŞIK İNŞAAT Taahhüt Sanayi ve Ticaret Anonim Şirketi ile Örnek Çağlayan Yapı "
        "Mühendislik ve Müşavirlik Limited Şirketi Adi Ortaklığı"
    ),
    tax_number="1234567890",
    tax_office="Büyük Mükellefler Vergi Dairesi Başkanlığı",
    address="Çiğdem Mahallesi, Öğretmenler Caddesi No: 14/A, Kat 7, 06530 Çankaya / Ankara",
)
LONG_CONTRACTOR = CertificateParty(
    name=(
        "Örnek Işıl Mekanik ve Elektrik Tesisat Mühendislik Taahhüt Sanayi ve Dış Ticaret Limited Şirketi "
        "(İstanbul Avrupa Yakası Şubesi)"
    ),
    tax_number="9876543210",
    tax_office="Şişli",
    address="Büyükdere Caddesi No: 201, Ümraniye İş Merkezi B Blok, 34394 Şişli / İstanbul",
)
LETTERHEAD = {
    "legal_name": "Örnek Işıl Mekanik ve Elektrik Tesisat Mühendislik Taahhüt Ltd. Şti.",
    "address": "Büyükdere Caddesi No: 201, B Blok Kat 4\n34394 Şişli / İstanbul, Türkiye",
    "registration_line": "Şişli V.D. 9876543210 - Ticaret Sicil No: 123456-5 - MERSİS: 0987654321000015",
    "phone": "+90 212 555 01 42",
    "email": "info@ornek.example",
    "website": "www.ornek.example",
}


def _logo_data_url() -> str:
    import base64
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (480, 140), (15, 76, 129)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


@pytest.fixture
def letterhead(monkeypatch: pytest.MonkeyPatch) -> None:
    """A firm with a logo and a full letterhead, whatever this machine's data folder holds."""
    import app.core.company_profile as company_profile
    import app.core.pdf_branding as pdf_branding
    from app.core.pdf_appearance import DEFAULT_APPEARANCE

    profile = company_profile.sanitise(LETTERHEAD | {"document_logo_data_url": _logo_data_url()})
    monkeypatch.setattr(company_profile, "read_company_profile", lambda *args, **kwargs: dict(profile))
    monkeypatch.setattr(pdf_branding, "_read_branding", dict)
    monkeypatch.setattr(pdf_branding, "_read_appearance", lambda doc_type=None: dict(DEFAULT_APPEARANCE))


def realistic(flavour: str, roles: tuple[str, ...] | None):
    """A second certificate of a real-sized contract, with its settings."""
    hakedis = dict(CONTRACT_TERMS["hakedis"])
    if roles is not None:
        hakedis["signature_roles"] = list(roles)
    settings = resolve_settings("TR", {"hakedis": hakedis})
    changes: dict[str, object] = {
        "employer": LONG_EMPLOYER,
        "contractor": LONG_CONTRACTOR,
        "contract_number": LONG_NUMBER,
        "project_name": "IŞIK İNŞAAT - İstanbul Çağlayan Veri Merkezi ve Isıtma, Soğutma, Havalandırma Tesisleri İnşaatı",
        "layout": settings.layout,
        "signature_roles": settings.signature_roles,
    }
    if flavour == "lump_sum":
        inp = lump_sum_input(
            [D("400000.00"), D("350000.00"), D("250000.00")],
            [D("40"), D("35"), D("25")],
            D("25"),
            D("12.5"),
            manual_lines=certificate_input(1, D("0")).manual_lines,
            **changes,
        )
    else:
        inp = certificate_input(2, D("12187793.96"), **changes)
    bases = expected_tax_bases(inp)
    cert = compute_certificate(replace(inp, taxes=synthetic_taxes(bases["vat_computed"], bases["stamp_duty"])))
    assert cert.payable.amount is not None
    return cert, settings


SIGNED = re.compile(r"(İmza|Signature)( / Signature)?:")
PAGE_OF = {
    "tr": "Sayfa {n} / {total}",
    "en": "Page {n} of {total}",
    "tr-en": "Sayfa {n} / {total} - Page {n} of {total}",
}
STAMPED = {"tr": "Oluşturulma: ", "en": "Generated: ", "tr-en": "Oluşturulma: "}
PAYABLE = {"tr": "Ödenecek Tutar", "en": "Amount Payable", "tr-en": "Ödenecek Tutar"}

REALISTIC = [
    (locale, flavour, roles)
    for locale in ("tr", "en", "tr-en")
    for flavour in ("unit_price", "lump_sum")
    for roles in (None, FIVE_ROLES)
]


@pytest.mark.usefixtures("letterhead")
@pytest.mark.parametrize(("locale", "flavour", "roles"), REALISTIC)
def test_no_page_is_only_signatures_and_every_page_says_what_it_is(
    locale: str, flavour: str, roles: tuple[str, ...] | None
) -> None:
    assert len(LONG_EMPLOYER.name) >= 120 and len(LONG_CONTRACTOR.name) >= 120
    cert, settings = realistic(flavour, roles)
    pdf = render_hakedis_pdf(
        cert, locale=locale, settings=settings, issue_date=date(2026, 9, 3), generated_at=GENERATED
    )
    texts, sizes = pages_of(pdf), sizes_of(pdf)
    total = len(texts)
    payable = tr_number(cert.payable.amount)
    works_total = tr_number(cert.totals.cumulative_amount)

    signed_portrait = signed_landscape = 0
    for number, (text, (width, height)) in enumerate(zip(texts, sizes, strict=True), start=1):
        # The furniture: which document, which page of how many, generated when.
        assert PAGE_OF[locale].format(n=number, total=total) in text, number
        assert f"{STAMPED[locale]}{STAMP}" in text, number
        assert f": {cert.inp.certificate_number} - {LONG_NUMBER}" in text, "the running header keeps the number whole"
        if not SIGNED.search(text):
            continue
        # A page somebody signs carries the figure they sign for.
        if width < height:
            signed_portrait += 1
            assert PAYABLE[locale] in text and payable in text, number
        else:
            signed_landscape += 1
            assert works_total in text, number
    assert (signed_portrait, signed_landscape) == (1, 1), "each part is signed once, on the page of its total"

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        words = {word[4] for page in doc for word in page.get_text("words")}
        # The logo is on every sheet, the landscape ones included.
        assert all(page.get_images() for page in doc)
    # No number is broken: every figure of the works list is one word on the page.
    _, rows = printed_works(cert, locale, settings)
    figures = {cell for row in rows for cell, value in zip(row.cells, row.values, strict=True) if value is not None}
    assert len(figures) > 10
    assert figures <= words, sorted(figures - words)[:5]
    for line in cert.summary:
        if line.status == "value" and line.amount is not None:
            assert tr_number(line.amount) in words, line.key


def test_long_codes_and_large_unit_prices_stay_whole() -> None:
    inp = certificate_input(1, D("0"))
    lines = list(inp.lines)
    lines[0] = replace(lines[0], code="S-43.001/İZM-A-0001", unit_price=D("1234567890.12"), period_quantity=D("1"))
    lines[1] = replace(lines[1], unit_price=D("512.3456"), period_quantity=D("950.375"))
    cert = compute_certificate(replace(inp, lines=lines, taxes=None))
    pdf = render_hakedis_pdf(cert)
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        words = {word[4] for page in doc for word in page.get_text("words")}
    for figure in ("S-43.001/İZM-A-0001", "1.234.567.890,12", "512,3456", "950,375"):
        assert figure in words, figure


def test_the_footer_says_when_the_file_was_generated(first: Certificate) -> None:
    for page in pages_of(render_hakedis_pdf(first)):
        assert re.search(r"Oluşturulma: \d\d\.\d\d\.\d{4} \d\d:\d\d UTC", page)
    for page in pages_of(render_hakedis_pdf(first, locale="en", generated_at=GENERATED)):
        assert f"Generated: {STAMP}" in page


def test_the_standard_summary_names_the_official_form_and_a_contracts_own_does_not(turkish: list[str]) -> None:
    assert "M.Y.H.B.Y. Örnek No: 3/10" in turkish[0]
    # The works list is not the form's sheet line for line, and does not claim to be.
    assert all("Örnek No" not in page for page in turkish[1:])
    hakedis = dict(CONTRACT_TERMS["hakedis"]) | {"add": [{"key": "site_services", "op": "manual"}]}
    hakedis["labels"] = {
        "tr": {"line.site_services": "Şantiye Hizmetleri"},
        "en": {"line.site_services": "Site Services"},
    }
    settings = resolve_settings("TR", {"hakedis": hakedis})
    inp = certificate_input(1, D("0"), layout=settings.layout, taxes=None)
    own = pages_of(render_hakedis_pdf(compute_certificate(inp), settings=settings))
    assert all("Örnek No" not in page for page in own)


def test_the_party_is_named_the_same_in_the_header_and_the_signature_block() -> None:
    cert, settings = realistic("unit_price", FIVE_ROLES)
    summary, _ = parts_of(render_hakedis_pdf(cert, settings=settings))
    assert "Alt Yüklenici Örnek Işıl Mekanik" in summary
    assert "ALT YÜKLENİCİ" in summary
    # The form's own wording of the payable line is kept; no second name for the party in a heading.
    assert not re.search(r"(?<!Alt )Yüklenici Örnek Işıl", summary)
    assert "YÜKLENİCİ Örnek" not in summary.replace("ALT YÜKLENİCİ", "")


def test_a_certificate_in_a_foreign_currency_says_the_lira_equivalent_is_not_stated() -> None:
    cert = certify(1, D("0"), currency="EUR")
    summary, works = parts_of(render_hakedis_pdf(cert))
    for text in (
        "Para Birimi EUR",
        "TL karşılığı: döviz kuru girilmedi.",
        "Tutar (EUR)",
        "8.799.587,24 EUR",
        "Faturada TL karşılığı gösterilir (VUK md. 215).",
        "(KDV Kanunu md. 26)",
    ):
        assert text in summary, text
    assert "Para Birimi: EUR" in works
    # No rate is an input, so no converted figure is printed anywhere.
    assert " TL " not in summary.replace("TL Karşılığı", "").replace("TL karşılığı", "").replace("TL'ye", "")
    english, _ = parts_of(render_hakedis_pdf(cert, locale="en"))
    assert "TL equivalent: exchange rate not entered." in english
    assert "The invoice shows the TL equivalent (Tax Procedure Law art. 215)." in english


def test_a_lira_certificate_prints_no_exchange_rate_line(turkish: list[str]) -> None:
    text = " ".join(turkish)
    assert "döviz kuru" not in text and "TL Karşılığı" not in text and "Para Birimi: TL" in text


def test_a_correction_and_an_overrun_are_explained_under_the_works_list() -> None:
    final = certify(3, D("50024219.44"))
    _, works = parts_of(render_hakedis_pdf(final))
    assert "Eksi (-) işaretli değerler, önceki hakedişlere göre yapılan düzeltmeyi (azalışı) gösterir." in works
    _, first_works = parts_of(render_hakedis_pdf(certify(1, D("0"))))
    assert "Eksi (-)" not in first_works
    over = compute_certificate(lump_sum_input([D("250000.00")], [D("100")], D("90"), D("15"), taxes=None))
    _, lump = parts_of(render_hakedis_pdf(over))
    assert "(!) 105,00" in lump
    assert "(!) Gerçekleşen toplam imalat yüzdesi %100'ü aşmaktadır." in lump
    assert "sözleşme miktarını" not in lump


def test_a_party_with_no_tax_details_prints_dashes_not_empty_cells() -> None:
    cert = certify(1, D("0"), contractor=CertificateParty(name="Yüklenici Ltd. Şti."), contract_number="")
    summary = pages_of(render_hakedis_pdf(cert))[0]
    assert "Yüklenici Ltd. Şti. Vergi Dairesi: - - Vergi No: - Adres: -" in summary
    assert "Sözleşme No -" in summary
