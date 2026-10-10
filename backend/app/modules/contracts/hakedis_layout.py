# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The lines, columns and printed words of a hakediş (progress payment certificate).

A hakediş is the Turkish progress payment certificate: a summary page of
lettered lines (work done, price adjustment, VAT, deductions, amount payable)
on top of a works list. What the lines are, in which order and under which
letter is decided by the contract, so here it is data:

* :class:`SummaryLineDef` is one line of the summary and how it is obtained.
* :data:`DEFAULT_LAYOUTS` holds the standard order per country. A country that
  has an entry has the document; nothing else gates it.
* :func:`resolve_settings` applies what a contract wrote under
  ``Contract.terms["hakedis"]`` and refuses a configuration that cannot be
  evaluated, naming the key at fault.
* :data:`HAKEDIS_LABELS` is every word the PDF and the workbook print, in
  Turkish and in English. The renderers draw nothing that is not in it.

Standard library only, plus the :class:`~app.core.payment_taxes.Choice` value
object. This module does not import :mod:`app.modules.contracts.hakedis`,
which imports it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Literal

from app.core.payment_taxes import Choice

__all__ = [
    "DEFAULT_LAYOUTS",
    "DEFAULT_SIGNATURE_ROLES",
    "HAKEDIS_LABELS",
    "INPUT_SOURCES",
    "LAYOUT_PRESETS",
    "LOCALES",
    "TAX_KINDS",
    "WORKS_COLUMNS",
    "WORKS_DEFAULT_COLUMNS",
    "ColumnDef",
    "HakedisSettings",
    "SummaryLineDef",
    "contractor_label_key",
    "currency_label",
    "is_foreign_currency",
    "evaluation_order",
    "has_layout",
    "label",
    "label_filled",
    "label_parts",
    "tax_choice",
    "line_formula",
    "locale_languages",
    "resolve_layout",
    "resolve_settings",
    "tr_lower",
    "tr_upper",
    "upper_for",
    "validate_layout",
]

LineOp = Literal["input", "sum", "difference", "tax", "manual", "retention"]

_OPS: frozenset[str] = frozenset({"input", "sum", "difference", "tax", "manual", "retention"})

#: What an ``input`` line may read. These are sources, not other lines.
INPUT_SOURCES: frozenset[str] = frozenset({"work_cumulative", "previous_certified_total"})

#: The figures of a ``PaymentTaxResult`` a ``tax`` line may print.
TAX_KINDS: frozenset[str] = frozenset({"vat_computed", "vat_withheld", "vat_payable", "income_withheld", "stamp_duty"})

#: The taxes a contract may set a default choice for, as ``PaymentTaxInput`` names them.
_TAX_CHOICE_KINDS: frozenset[str] = frozenset({"vat_withholding", "income_withholding", "stamp_duty"})

#: Document locales. ``tr-en`` prints the Turkish label with the English one under it.
LOCALES: tuple[str, ...] = ("tr", "en", "tr-en")


@dataclass(frozen=True)
class SummaryLineDef:
    """One line of the certificate summary and how its amount is obtained.

    Attributes:
        key: Stable identifier, also the label key (``line.<key>``).
        letter: The letter printed in front of the line, empty for none.
        op: How the amount is obtained.

            * ``input``: read from the certificate input. ``operands`` holds
              one source name from :data:`INPUT_SOURCES`.
            * ``sum``: the operands added up.
            * ``difference``: the first operand less every other one.
            * ``tax``: the figure named by ``tax_kind`` of the shared payment
              tax calculation. ``operands`` states the base the figure must
              have been computed on (first less the others); an empty tuple
              switches the check off.
            * ``manual``: entered by a person. ``operands`` is the base used
              when the entry is a percent instead of an amount.
            * ``retention``: the retention percent of the base in ``operands``.
        operands: Keys of other lines, read as described under ``op``.
        sign: ``-1`` for a line that reduces the amount payable, ``1``
            otherwise. Amounts are stored positive either way; the sign tells
            a reader, and a validation rule, which way the line works.
        tax_kind: The figure a ``tax`` line prints.
        section: Printed block the line belongs to: ``work``, ``certificate``,
            ``deductions`` or ``result``.
    """

    key: str
    letter: str
    op: LineOp
    operands: tuple[str, ...]
    sign: int
    tax_kind: str = ""
    section: str = ""


def _line(
    key: str,
    letter: str,
    op: LineOp,
    operands: tuple[str, ...] = (),
    *,
    sign: int = 1,
    tax_kind: str = "",
    section: str,
) -> SummaryLineDef:
    return SummaryLineDef(key, letter, op, operands, sign, tax_kind, section)


_TR_DEDUCTIONS: tuple[str, ...] = (
    "income_tax",
    "stamp_duty",
    "vat_withholding",
    "social_security",
    "employer_plant_rent",
    "delay_penalty",
    "advance_recovery",
    "price_adjustment_guarantee",
    "retention",
    "other_deductions",
)

# The standard Turkish public works form, line for line and letter for letter:
# "Hakediş Raporu", M.Y.H.B.Y. Örnek No: 3/10, annexed to the Merkezî Yönetim
# Harcama Belgeleri Yönetmeliği and read from the Ministry of Treasury and
# Finance print on 2026-10-10:
# https://ms.hmb.gov.tr/uploads/2019/01/6.05-MERKEZ%C4%B0-Y%C3%96NET%C4%B0M-HARCAMA-BELGELER%C4%B0-Y%C3%96NETMEL%C4%B0%C4%9E%C4%B0.pdf
# Lines A to G, a) to h), H and the amount payable are the form's own. The form
# then leaves two blank rows for what a contract adds; they are filled here
# with the retention (teminat kesintisi) as i) and other deductions as j),
# after the form's letters and not between them, so a) to h) keep the meaning
# every cost control department knows them by. The stamp duty base is the
# form's "E - g": the advance was taxed when it was paid.
_TR_STANDARD: tuple[SummaryLineDef, ...] = (
    _line("work_done", "A", "input", ("work_cumulative",), section="work"),
    _line("price_adjustment", "B", "manual", section="work"),
    _line("total", "C", "sum", ("work_done", "price_adjustment"), section="work"),
    _line("previous_certificates", "D", "input", ("previous_certified_total",), section="certificate"),
    _line("this_certificate", "E", "difference", ("total", "previous_certificates"), section="certificate"),
    _line("vat", "F", "tax", ("this_certificate",), tax_kind="vat_computed", section="certificate"),
    _line("accrued", "G", "sum", ("this_certificate", "vat"), section="certificate"),
    _line("income_tax", "a", "tax", ("this_certificate",), sign=-1, tax_kind="income_withheld", section="deductions"),
    _line(
        "stamp_duty",
        "b",
        "tax",
        ("this_certificate", "advance_recovery"),
        sign=-1,
        tax_kind="stamp_duty",
        section="deductions",
    ),
    _line("vat_withholding", "c", "tax", ("vat",), sign=-1, tax_kind="vat_withheld", section="deductions"),
    _line("social_security", "d", "manual", sign=-1, section="deductions"),
    _line("employer_plant_rent", "e", "manual", sign=-1, section="deductions"),
    _line("delay_penalty", "f", "manual", sign=-1, section="deductions"),
    _line("advance_recovery", "g", "manual", ("this_certificate",), sign=-1, section="deductions"),
    _line("price_adjustment_guarantee", "h", "manual", sign=-1, section="deductions"),
    _line("retention", "i", "retention", ("this_certificate",), sign=-1, section="deductions"),
    _line("other_deductions", "j", "manual", sign=-1, section="deductions"),
    _line("deductions_total", "H", "sum", _TR_DEDUCTIONS, sign=-1, section="result"),
    _line("payable", "", "difference", ("accrued", "deductions_total"), section="result"),
)

_TR_PRIVATE_DEDUCTIONS: tuple[str, ...] = (
    "retention",
    "advance_recovery",
    "vat_withholding",
    "income_tax",
    "stamp_duty",
    "social_security",
    "delay_penalty",
    "back_charges",
    "other_deductions",
)

# A house arrangement for contracts between private parties, where the main
# contractor's own deductions lead and the statutory ones follow. No published
# private form was found, so this is not a transcription of one: it is the
# standard form's A to G over the deductions private contracts in Türkiye
# usually carry. A contract selects it with ``{"preset": "TR_PRIVATE"}`` and
# adjusts it like any other layout.
_TR_PRIVATE: tuple[SummaryLineDef, ...] = (
    *_TR_STANDARD[:7],
    _line("retention", "a", "retention", ("this_certificate",), sign=-1, section="deductions"),
    _line("advance_recovery", "b", "manual", ("this_certificate",), sign=-1, section="deductions"),
    _line("vat_withholding", "c", "tax", ("vat",), sign=-1, tax_kind="vat_withheld", section="deductions"),
    _line("income_tax", "d", "tax", ("this_certificate",), sign=-1, tax_kind="income_withheld", section="deductions"),
    _line(
        "stamp_duty",
        "e",
        "tax",
        ("this_certificate", "advance_recovery"),
        sign=-1,
        tax_kind="stamp_duty",
        section="deductions",
    ),
    _line("social_security", "f", "manual", sign=-1, section="deductions"),
    _line("delay_penalty", "g", "manual", sign=-1, section="deductions"),
    _line("back_charges", "h", "manual", sign=-1, section="deductions"),
    _line("other_deductions", "i", "manual", sign=-1, section="deductions"),
    _line("deductions_total", "H", "sum", _TR_PRIVATE_DEDUCTIONS, sign=-1, section="result"),
    _line("payable", "", "difference", ("accrued", "deductions_total"), section="result"),
)

#: The standard layout per ISO 3166-1 alpha-2 country code. Presence here is
#: what makes the certificate available for a project in that country.
DEFAULT_LAYOUTS: dict[str, tuple[SummaryLineDef, ...]] = {"TR": _TR_STANDARD}

#: Named layouts a contract may start from with ``{"preset": "<name>"}``.
LAYOUT_PRESETS: dict[str, tuple[SummaryLineDef, ...]] = {"TR": _TR_STANDARD, "TR_PRIVATE": _TR_PRIVATE}

#: Who signs, in printed order, per country: the standard form's three blocks.
DEFAULT_SIGNATURE_ROLES: dict[str, tuple[str, ...]] = {"TR": ("contractor", "prepared_by", "approved_by")}


# ── Works list columns ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ColumnDef:
    """One column of the works list.

    Attributes:
        key: The attribute of a work line result the column prints, also the
            label key (``col.<flavour>.<key>``).
        letter: The letter or formula printed over the column, empty for none.
        kind: How the value is formatted and aligned.
    """

    key: str
    letter: str
    kind: Literal["seq", "text", "unit", "quantity", "unit_price", "money", "percent"]


# Form 3/7-b (unit price) and 3/7-a (lump sum) of the same Örnek No: 3. The
# period amount is printed as cumulative less previous (G=E-F, G=C-E), the way
# filled certificates print it, where the blank form says G=AxD and G=AxF: the
# two agree before rounding and only the subtraction keeps a row adding up
# after it. ``contract_quantity``, ``code`` and ``unit`` on the lump-sum list
# are not on the form and are offered as optional columns.
WORKS_COLUMNS: dict[str, tuple[ColumnDef, ...]] = {
    "unit_price": (
        ColumnDef("seq", "", "seq"),
        ColumnDef("code", "", "text"),
        ColumnDef("description", "", "text"),
        ColumnDef("unit", "", "unit"),
        ColumnDef("contract_quantity", "", "quantity"),
        ColumnDef("unit_price", "A", "unit_price"),
        ColumnDef("cumulative_quantity", "B", "quantity"),
        ColumnDef("previous_quantity", "C", "quantity"),
        ColumnDef("period_quantity", "D=B-C", "quantity"),
        ColumnDef("cumulative_amount", "E=AxB", "money"),
        ColumnDef("previous_amount", "F=AxC", "money"),
        ColumnDef("period_amount", "G=E-F", "money"),
    ),
    "lump_sum": (
        ColumnDef("seq", "", "seq"),
        ColumnDef("weight_pct", "", "percent"),
        ColumnDef("code", "", "text"),
        ColumnDef("description", "", "text"),
        ColumnDef("unit", "", "unit"),
        ColumnDef("contract_amount", "A", "money"),
        ColumnDef("cumulative_pct", "B", "percent"),
        ColumnDef("cumulative_amount", "C=AxB", "money"),
        ColumnDef("previous_pct", "D", "percent"),
        ColumnDef("previous_amount", "E=AxD", "money"),
        ColumnDef("period_pct", "F=B-D", "percent"),
        ColumnDef("period_amount", "G=C-E", "money"),
    ),
}

#: The columns printed unless the contract chooses its own: the form's.
WORKS_DEFAULT_COLUMNS: dict[str, tuple[str, ...]] = {
    "unit_price": (
        "seq",
        "code",
        "description",
        "unit",
        "unit_price",
        "cumulative_quantity",
        "previous_quantity",
        "period_quantity",
        "cumulative_amount",
        "previous_amount",
        "period_amount",
    ),
    "lump_sum": (
        "seq",
        "weight_pct",
        "description",
        "contract_amount",
        "cumulative_pct",
        "cumulative_amount",
        "previous_pct",
        "previous_amount",
        "period_pct",
        "period_amount",
    ),
}


# ── Printed words ─────────────────────────────────────────────────────────

_TR: dict[str, str] = {
    # Titles and the header block
    "title.report": "Hakediş Raporu",
    "title.interim": "Geçici Hakediş",
    "title.final": "Kesin Hakediş",
    "title.works_list": "Yapılan İşler Listesi",
    "subtitle.unit_price": "(Teklif Birim Fiyatlı İş)",
    "subtitle.lump_sum": "(Anahtar Teslimi Götürü Bedel İş)",
    "header.project": "İşin Adı",
    "header.contract": "Sözleşme",
    "header.contract_number": "Sözleşme No",
    "header.employer": "İşveren",
    "header.contractor": "Yüklenici",
    "header.tax_number": "Vergi No",
    "header.tax_office": "Vergi Dairesi",
    "header.address": "Adres",
    "header.certificate_number": "Hakediş No",
    "header.period": "Hakediş Dönemi",
    "header.issue_date": "Düzenleme Tarihi",
    "header.currency": "Para Birimi",
    "header.work_to_date": "{date} tarihine kadar yapılan işin",
    "header.amount": "Tutar",
    "page.number": "Sayfa No",
    "page.of": "Sayfa {page} / {pages}",
    # Summary lines
    "line.work_done": "Sözleşme Fiyatları İle Yapılan İş",
    "line.price_adjustment": "Fiyat Farkı Tutarı",
    "line.total": "Toplam Tutar",
    "line.previous_certificates": "Bir Önceki Hakedişin Toplam Tutarı",
    "line.this_certificate": "Bu Hakedişin Tutarı",
    "line.vat": "KDV",
    "line.accrued": "Tahakkuk Tutarı",
    "line.income_tax": "Gelir / Kurumlar Vergisi",
    "line.stamp_duty": "Damga Vergisi",
    "line.vat_withholding": "KDV Tevkifatı",
    "line.social_security": "Sosyal Sigortalar Kurumu Kesintisi",
    "line.employer_plant_rent": "İdare Makinesi Kiraları",
    "line.delay_penalty": "Gecikme Cezası",
    "line.advance_recovery": "Avans Mahsubu",
    "line.price_adjustment_guarantee": "Bu Hakedişle Ödenen Fiyat Farkı Teminat Kesintisi",
    "line.retention": "Teminat Kesintisi",
    "line.other_deductions": "Diğer Kesintiler",
    "line.deductions_total": "Kesintiler ve Mahsuplar Toplamı",
    "line.payable": "Yükleniciye Ödenecek Tutar",
    # Lines a contract may add
    "line.provisional_acceptance_retention": "Geçici Kabul Kesintisi",
    "line.back_charges": "Yansıtma (Kontra Fatura) Kesintileri",
    "line.employer_supplied_materials": "İşveren Malzemesi Mahsubu",
    "line.hse_penalty": "İş Sağlığı ve Güvenliği Cezaları",
    "line.materials_on_site": "Malzeme İhzaratı",
    "section.deductions": "Kesintiler ve Mahsuplar",
    # Works list, unit price (form 3/7-b)
    "col.unit_price.seq": "Sıra No",
    "col.unit_price.code": "Poz No",
    "col.unit_price.description": "İşin Tanımı",
    "col.unit_price.unit": "Birimi",
    "col.unit_price.contract_quantity": "Sözleşme Miktarı",
    "col.unit_price.unit_price": "Teklif Birim Fiyat",
    "col.unit_price.cumulative_quantity": "Toplam İmalat, İhzarat Miktarı",
    "col.unit_price.previous_quantity": "Bir Önceki Hakediş İmalat, İhzarat Miktarı",
    "col.unit_price.period_quantity": "Bu Hakediş İmalat, İhzarat Miktarı",
    "col.unit_price.cumulative_amount": "Toplam İmalat, İhzarat Tutarı",
    "col.unit_price.previous_amount": "Bir Önceki Hakediş Tutarı",
    "col.unit_price.period_amount": "Bu Hakediş Tutarı",
    # Works list, lump sum (form 3/7-a)
    "col.lump_sum.seq": "Sıra No",
    "col.lump_sum.weight_pct": "İş Programı Grubu %si (*)",
    "col.lump_sum.code": "Poz No",
    "col.lump_sum.description": "Yapılan İş",
    "col.lump_sum.unit": "Birimi",
    "col.lump_sum.contract_amount": "İş Grubu Sözleşme Bedeli",
    "col.lump_sum.cumulative_pct": "Gerçekleşen Toplam İmalat %si",
    "col.lump_sum.cumulative_amount": "Toplam İmalat Tutarı",
    "col.lump_sum.previous_pct": "Önceki Hakediş Toplam İmalat %si",
    "col.lump_sum.previous_amount": "Önceki Hakediş Toplam İmalat Tutarı",
    "col.lump_sum.period_pct": "Bu Hakediş İmalat %si",
    "col.lump_sum.period_amount": "Bu Hakediş İmalat Tutarı",
    "works.total": "Toplam",
    "works.subtotal": "Ara Toplam",
    "works.weight_note": "(*) İş programında belirlenen iş grubu yüzdesi. A sütunu iş grubunun sözleşme bedelindeki payını, B, D ve F sütunları iş grubunun kendi gerçekleşme yüzdesini gösterir.",
    "works.over_measured_note": "(!) Toplam miktar sözleşme miktarını aşmaktadır.",
    # Signature block
    "role.contractor": "Yüklenici",
    "role.prepared_by": "Düzenleyenler (Yapı Denetim Elemanları)",
    "role.approved_by": "Onaylayan",
    "role.control_engineer": "Kontrol Mühendisi",
    "role.control_chief": "Kontrol Amiri",
    "role.control_organisation": "Kontrol Teşkilatı",
    "role.site_manager": "Şantiye Şefi",
    "role.project_manager": "Proje Müdürü",
    "role.employer": "İşveren",
    "role.subcontractor": "Alt Yüklenici",
    "role.cost_control": "Maliyet Kontrol",
    "role.quantity_surveyor": "Hakediş ve Metraj Sorumlusu",
    "sign.name": "Adı Soyadı",
    "sign.signature": "İmza",
    "sign.date": "Tarih",
    # Status words, the draft banner and its notes
    "status.held": "Beklemede",
    "status.draft": "Taslak",
    "draft.banner": "TASLAK - Tutarların tamamı kesinleşmemiştir",
    "draft.notes_title": "Açıklamalar",
    "reason.module_absent": "Vergi hesaplama modülü kurulu değil; vergi satırları hesaplanamadı.",
    "reason.provider_failed": "Vergi hesaplaması başarısız oldu; vergi satırları hesaplanamadı.",
    "reason.missing_figure": "Vergi hesaplaması bu satır için tutar döndürmedi.",
    "reason.not_chosen": "Henüz bir kategori seçilmedi.",
    "reason.no_rate_on_date": "{on} tarihinde {code} kodu için yürürlükte bir oran yok.",
    "reason.vat_rate_unknown": "KDV oranı bilinmiyor.",
    "reason.threshold_currency_mismatch": "Sınır {threshold_currency} cinsinden, belge ise {document_currency} cinsinden olduğu için karşılaştırılamıyor.",
    "reason.threshold_needs_year_total": "Sınır, alıcıya yıl içinde yapılan toplam ödemeye göre uygulanır; tek bir ödeme bunu göstermez.",
    "reason.rate_ambiguous": "{on} tarihinde {code} kodu için birden fazla oran satırı yürürlükte. Oran tablosunun düzeltilmesi gerekiyor.",
    "reason.rate_row_invalid": "{code} kodunun oran satırı eksik; bu satırdan hesaplama yapılamaz.",
    "reason.withholding_needs_vat": "Bu tutar, henüz belli olmayan KDV tutarına bağlıdır.",
    "reason.not_applicable_by_user": "Uygulanmaz olarak işaretlendi: {reason}",
    "reason.not_applicable_reason_missing": "Gerekçe belirtilmeden uygulanmaz olarak işaretlendi. Gerekçeyi girin.",
    "reason.buyer_class_unknown": "Alıcının belirlenmiş alıcı olup olmadığı belirtilmedi.",
    "reason.buyer_not_designated": "Uygulanmaz: alıcı belirlenmiş alıcı değil.",
    "reason.work_value_unknown": "İşin KDV dahil toplam bedeli girilmedi.",
    "reason.below_work_value": "Uygulanmaz: işin bedeli ({work_value} {currency}) {threshold} {currency} sınırının altında.",
    "reason.below_threshold": "Uygulanmaz: {measured} {currency}, {threshold} {currency} sınırının altında.",
    "reason.capped": "{cap} {currency} azami tutarıyla sınırlandı (hesaplanan {computed}).",
    "reason.cap_currency_mismatch": "Azami tutar {cap_currency} cinsinden, belge ise {document_currency} cinsinden olduğu için uygulanamıyor.",
    "reason.override_reason_missing": "Tutar, gerekçe belirtilmeden elle girildi. Gerekçeyi girin.",
    "reason.override_precision": "Elle girilen tutarın ({amount}) ondalık hanesi {currency} için izin verilenden fazla.",
    "reason.override_not_allowed": "Ödenecek KDV bir farktır ve elle girilemez. Bunun yerine tevkif edilen KDV'yi değiştirin.",
    "reason.currency_unknown": '"{currency}" para birimi tanınmıyor; tutarlar yuvarlanamıyor.',
    "reason.tax_base_mismatch": "Verginin matrahı ({base}) bu hakedişin matrahı ({expected}) ile uyuşmuyor.",
    "reason.taxes_stale": "Vergiler {stored} matrahı üzerinden hesaplanmıştı; bu hakedişin matrahı artık {expected}. Vergileri yeniden hesaplayın.",
    "reason.taxes_outdated": "Vergiler hesaplandıktan sonra hakedişin tarihi, KDV oranı veya damga vergisi matrahı değişti. Vergileri yeniden hesaplayın.",
    "reason.taxes_not_stored": "Bu hakediş için vergi seçimleri henüz kaydedilmedi.",
    "reason.taxes_not_confirmed": "Vergi tutarları henüz onaylanmadı.",
    "reason.stamp_duty_base_unknown": "Damga vergisinin matrahı belirtilmedi.",
    "reason.previous_not_certified": "Bir önceki hakediş ({number}) henüz onaylanmadığı için toplam tutarı kesinleşmedi.",
    "reason.base_held": "Matrahı oluşturan satır beklemede.",
    "reason.operand_held": "Beklemedeki satırlara bağlı: {operands}.",
    "reason.not_entered": "Tutar girilmedi.",
    "reason.manual_held": "Tutar beklemeye alındı.",
    "reason.retention_unknown": "Teminat kesintisi oranı bilinmiyor.",
    "reason.previous_unknown": "Bir önceki hakedişin toplam tutarı bilinmiyor.",
    "reason.work_line_incomplete": "Eksik veri içeren iş kalemleri: {lines}.",
    "reason.unconfirmed_rate": "Kullanılan oran birincil kaynaktan teyit edilmemiştir.",
    "reason.overridden": "Hesaplanan tutar elle değiştirilmiştir.",
    "reason.other": "Beklemede: {reason}.",
    "basis.legal_reference": "Dayanak",
    "basis.code": "Kod",
    "basis.note": "Not",
    "basis.conditions": "Koşul",
    # Presentation: the currency as printed, the page furniture, the notes
    # under the tables and the form references of the standard layout.
    "footer.generated": "Oluşturulma: {timestamp}",
    "works.over_complete_note": "(!) Gerçekleşen toplam imalat yüzdesi %100'ü aşmaktadır.",
    "works.negative_note": "Eksi (-) işaretli değerler, önceki hakedişlere göre yapılan düzeltmeyi (azalışı) gösterir.",
    "note.number_format": "Tutarlar ve tarihler Türkiye'de kullanılan biçimde yazılmıştır (1.234,56 - GG.AA.YYYY).",
    "form.reference.summary": "M.Y.H.B.Y. Örnek No: 3/10",
    # A certificate in a foreign currency. The certificate itself is not a
    # document of the Tax Procedure Law, so the lira equivalent is owed on the
    # invoice that follows it, and the certificate says so. Read 2026-10-10:
    # VUK (Law 213) md. 215/2-a, https://www.mevzuat.gov.tr/MevzuatMetin/1.4.213.pdf
    # KDV Kanunu (Law 3065) md. 26, https://www.mevzuat.gov.tr/MevzuatMetin/1.5.3065.pdf
    # KDV Genel Uygulama Tebliği III/A-1.1 (the Central Bank buying rate
    # published in the Resmî Gazete) and III/C-5.1 (the certificate is not a
    # VUK document), https://www.mevzuat.gov.tr/File/GeneratePdf?mevzuatNo=19631&mevzuatTur=Teblig&mevzuatTertip=5
    "fx.title": "TL Karşılığı",
    "fx.rate_missing": "TL karşılığı: döviz kuru girilmedi.",
    "fx.explanation": "Bu hakediş {currency} cinsinden düzenlenmiştir; döviz kuru girilmediği için TL karşılığı yazılmamıştır. Faturada TL karşılığı gösterilir (VUK md. 215). KDV, vergiyi doğuran olayın meydana geldiği günkü T.C. Merkez Bankası döviz alış kuru üzerinden TL'ye çevrilir (KDV Kanunu md. 26).",
}

_EN: dict[str, str] = {
    "title.report": "Progress Payment Certificate",
    "title.interim": "Interim Certificate",
    "title.final": "Final Certificate",
    "title.works_list": "List of Works Done",
    "subtitle.unit_price": "(Unit Price Work)",
    "subtitle.lump_sum": "(Turnkey Lump Sum Work)",
    "header.project": "Project",
    "header.contract": "Contract",
    "header.contract_number": "Contract No.",
    "header.employer": "Employer",
    "header.contractor": "Contractor",
    "header.tax_number": "Tax No.",
    "header.tax_office": "Tax Office",
    "header.address": "Address",
    "header.certificate_number": "Certificate No.",
    "header.period": "Certificate Period",
    "header.issue_date": "Date of Issue",
    "header.currency": "Currency",
    "header.work_to_date": "Work done up to {date}",
    "header.amount": "Amount",
    "page.number": "Page No.",
    "page.of": "Page {page} of {pages}",
    "line.work_done": "Work Done at Contract Prices",
    "line.price_adjustment": "Price Adjustment",
    "line.total": "Total Amount",
    "line.previous_certificates": "Total of the Previous Certificate",
    "line.this_certificate": "Amount of This Certificate",
    "line.vat": "VAT",
    "line.accrued": "Accrued Amount",
    "line.income_tax": "Income / Corporate Tax Withholding",
    "line.stamp_duty": "Stamp Duty",
    "line.vat_withholding": "VAT Withholding",
    "line.social_security": "Social Security Institution Deduction",
    "line.employer_plant_rent": "Rent of Employer's Plant",
    "line.delay_penalty": "Delay Penalty",
    "line.advance_recovery": "Advance Recovery",
    "line.price_adjustment_guarantee": "Guarantee Deduction on the Price Adjustment Paid with This Certificate",
    "line.retention": "Retention (Guarantee Deduction)",
    "line.other_deductions": "Other Deductions",
    "line.deductions_total": "Total Deductions and Set-offs",
    "line.payable": "Amount Payable to the Contractor",
    "line.provisional_acceptance_retention": "Provisional Acceptance Retention",
    "line.back_charges": "Back-charges",
    "line.employer_supplied_materials": "Set-off for Employer-supplied Materials",
    "line.hse_penalty": "Health and Safety Penalties",
    "line.materials_on_site": "Materials on Site",
    "section.deductions": "Deductions and Set-offs",
    "col.unit_price.seq": "No.",
    "col.unit_price.code": "Item Code",
    "col.unit_price.description": "Description of Work",
    "col.unit_price.unit": "Unit",
    "col.unit_price.contract_quantity": "Contract Quantity",
    "col.unit_price.unit_price": "Contract Unit Price",
    "col.unit_price.cumulative_quantity": "Total Quantity to Date",
    "col.unit_price.previous_quantity": "Previous Certificate Quantity",
    "col.unit_price.period_quantity": "This Certificate Quantity",
    "col.unit_price.cumulative_amount": "Total Amount to Date",
    "col.unit_price.previous_amount": "Previous Certificate Amount",
    "col.unit_price.period_amount": "This Certificate Amount",
    "col.lump_sum.seq": "No.",
    "col.lump_sum.weight_pct": "Work Group Weight % (*)",
    "col.lump_sum.code": "Item Code",
    "col.lump_sum.description": "Work Item",
    "col.lump_sum.unit": "Unit",
    "col.lump_sum.contract_amount": "Work Group Contract Amount",
    "col.lump_sum.cumulative_pct": "Total Completion %",
    "col.lump_sum.cumulative_amount": "Total Amount to Date",
    "col.lump_sum.previous_pct": "Previous Certificate Completion %",
    "col.lump_sum.previous_amount": "Previous Certificate Amount",
    "col.lump_sum.period_pct": "This Certificate %",
    "col.lump_sum.period_amount": "This Certificate Amount",
    "works.total": "Total",
    "works.subtotal": "Subtotal",
    "works.weight_note": "(*) Work group percentage set in the work programme. Column A is the group's share of the contract price; columns B, D and F are the group's own completion percentages.",
    "works.over_measured_note": "(!) The total quantity exceeds the contract quantity.",
    "role.contractor": "Contractor",
    "role.prepared_by": "Prepared by (Site Supervision Staff)",
    "role.approved_by": "Approved by",
    "role.control_engineer": "Supervising Engineer",
    "role.control_chief": "Chief Supervisor",
    "role.control_organisation": "Supervision Team",
    "role.site_manager": "Site Manager",
    "role.project_manager": "Project Manager",
    "role.employer": "Employer",
    "role.subcontractor": "Subcontractor",
    "role.cost_control": "Cost Control",
    "role.quantity_surveyor": "Quantity Surveyor",
    "sign.name": "Name",
    "sign.signature": "Signature",
    "sign.date": "Date",
    "status.held": "Held",
    "status.draft": "Draft",
    "draft.banner": "DRAFT - not all figures are final",
    "draft.notes_title": "Notes",
    "reason.module_absent": "The tax calculation module is not installed; the tax lines could not be computed.",
    "reason.provider_failed": "The tax calculation failed; the tax lines could not be computed.",
    "reason.missing_figure": "The tax calculation returned no figure for this line.",
    "reason.not_chosen": "No category has been chosen yet.",
    "reason.no_rate_on_date": "No rate is in force for code {code} on {on}.",
    "reason.vat_rate_unknown": "The VAT rate is not known.",
    "reason.threshold_currency_mismatch": "The limit is stated in {threshold_currency} and the document is in {document_currency}, so they cannot be compared.",
    "reason.threshold_needs_year_total": "The threshold applies to the payee's total for the year, which one payment cannot show.",
    "reason.rate_ambiguous": "More than one rate row is in force for code {code} on {on}. The rate table needs correcting.",
    "reason.rate_row_invalid": "The rate row for code {code} is incomplete and cannot be computed from.",
    "reason.withholding_needs_vat": "This figure depends on the VAT amount, which is not available yet.",
    "reason.not_applicable_by_user": "Marked as not applicable: {reason}",
    "reason.not_applicable_reason_missing": "Marked as not applicable without a reason. Enter the reason.",
    "reason.buyer_class_unknown": "It has not been stated whether the buyer is a designated buyer.",
    "reason.buyer_not_designated": "Does not apply: the buyer is not a designated buyer.",
    "reason.work_value_unknown": "The VAT-inclusive value of the whole work has not been entered.",
    "reason.below_work_value": "Does not apply: the value of the work ({work_value} {currency}) is below {threshold} {currency}.",
    "reason.below_threshold": "Does not apply: {measured} {currency} is below the threshold of {threshold} {currency}.",
    "reason.capped": "Limited to the ceiling of {cap} {currency} (computed {computed}).",
    "reason.cap_currency_mismatch": "The ceiling is stated in {cap_currency} and the document is in {document_currency}, so it cannot be applied.",
    "reason.override_reason_missing": "An amount was entered by hand without a reason. Enter the reason.",
    "reason.override_precision": "The amount entered by hand ({amount}) has more decimals than {currency} allows.",
    "reason.override_not_allowed": "Payable VAT is a difference and cannot be entered by hand. Change the withheld VAT instead.",
    "reason.currency_unknown": 'The currency "{currency}" is not known, so amounts cannot be rounded.',
    "reason.tax_base_mismatch": "The tax was computed on {base}, this certificate's base is {expected}.",
    "reason.taxes_stale": "The taxes were computed on a base of {stored}; this certificate's base is now {expected}. Recalculate the taxes.",
    "reason.taxes_outdated": "The date of the certificate, the VAT rate or the stamp duty base changed after the taxes were calculated. Recalculate the taxes.",
    "reason.taxes_not_stored": "No tax choices have been saved for this certificate yet.",
    "reason.taxes_not_confirmed": "The tax figures have not been confirmed yet.",
    "reason.stamp_duty_base_unknown": "The base of the stamp duty has not been stated.",
    "reason.previous_not_certified": "The previous certificate ({number}) has not been certified yet, so its total is not final.",
    "reason.base_held": "The line the base is taken from is held.",
    "reason.operand_held": "Depends on held lines: {operands}.",
    "reason.not_entered": "No amount has been entered.",
    "reason.manual_held": "The amount has been put on hold.",
    "reason.retention_unknown": "The retention percentage is not known.",
    "reason.previous_unknown": "The total of the previous certificate is not known.",
    "reason.work_line_incomplete": "Work items with missing data: {lines}.",
    "reason.unconfirmed_rate": "The rate used has not been confirmed against the primary source.",
    "reason.overridden": "The computed amount has been replaced by hand.",
    "reason.other": "Held: {reason}.",
    "basis.legal_reference": "Legal basis",
    "basis.code": "Code",
    "basis.note": "Note",
    "basis.conditions": "Condition",
    "footer.generated": "Generated: {timestamp}",
    "works.over_complete_note": "(!) The total completion exceeds 100%.",
    "works.negative_note": "Figures with a minus sign (-) are corrections (reductions) against earlier certificates.",
    "note.number_format": "Amounts and dates are written in Turkish notation (1.234,56 - DD.MM.YYYY).",
    "form.reference.summary": "M.Y.H.B.Y. Örnek No: 3/10",
    "fx.title": "Turkish Lira Equivalent",
    "fx.rate_missing": "TL equivalent: exchange rate not entered.",
    "fx.explanation": "This certificate is issued in {currency}; no exchange rate has been entered, so no TL equivalent is printed. The invoice shows the TL equivalent (Tax Procedure Law art. 215). VAT is converted to TL at the Central Bank buying rate of the day the taxable event occurs (VAT Law art. 26).",
}

#: locale -> key -> printed label. Both locales carry exactly the same keys.
HAKEDIS_LABELS: dict[str, dict[str, str]] = {"tr": _TR, "en": _EN}


def locale_languages(locale: str) -> tuple[str, ...]:
    """The languages a document locale prints, in order: ``tr-en`` is both.

    Raises:
        ValueError: The locale is not one of :data:`LOCALES`.
    """
    if locale not in LOCALES:
        raise ValueError(f"hakedis locale {locale!r} is not one of {', '.join(LOCALES)}")
    return tuple(locale.split("-"))


class _Params(dict[str, str]):
    """Label parameters; one that was not supplied prints as dots, not as a brace."""

    def __missing__(self, key: str) -> str:
        return "..."


def label(
    key: str,
    language: str,
    overrides: Mapping[str, Mapping[str, str]] | None = None,
    **params: str,
) -> str:
    """The printed label for ``key`` in one language.

    A contract's own label wins over the built-in one. A key with no label in
    either place prints as the key itself, so a missing word shows up on the
    page instead of disappearing from it; :func:`resolve_settings` refuses a
    layout whose lines have no label, so this is reached only by a custom
    signature role.
    """
    text = ((overrides or {}).get(language) or {}).get(key)
    if text is None:
        text = HAKEDIS_LABELS[language].get(key, key)
    if not params:
        # No parameters: the caller wants the template itself (the page
        # counter is filled in when the page count is known).
        return text
    try:
        return text.format_map(_Params(params))
    except (IndexError, ValueError):
        return text


def label_filled(
    key: str,
    language: str,
    overrides: Mapping[str, Mapping[str, str]] | None,
    params: Mapping[str, str],
) -> str:
    """The label for ``key`` with its placeholders always filled in.

    For a sentence that is printed as it stands: a parameter nobody supplied
    prints as dots, never as a brace.
    """
    text = label(key, language, overrides)
    try:
        return text.format_map(_Params(params))
    except (IndexError, ValueError):
        return text


def tax_choice(settings: HakedisSettings, tax: str) -> Choice:
    """The contract's choice for one tax, ``unset`` when the contract makes none.

    Nothing is inferred from the rate table: a tax with one shipped row is
    still not chosen until a person chooses it, because whether that row
    applies depends on who pays. An unset choice holds the line, visibly.
    """
    return settings.tax_choices.get(tax) or Choice("unset")


def label_parts(
    key: str,
    locale: str,
    overrides: Mapping[str, Mapping[str, str]] | None = None,
    **params: str,
) -> tuple[str, ...]:
    """The label once per language of the locale: two parts for ``tr-en``."""
    return tuple(label(key, language, overrides, **params) for language in locale_languages(locale))


def currency_label(
    currency: str,
    language: str,
    overrides: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """The currency as a document prints it beside an amount.

    A contract's own ``currency.<ISO>`` label wins. Otherwise the rule is the
    one every printed document of the set follows
    (:func:`app.core.register_export.printed_currency`): in Turkish the lira
    prints as "TL", the way every Turkish form and filled certificate writes
    it, and everything else keeps its ISO code. The stored currency stays the
    ISO code either way.
    """
    key = f"currency.{currency}"
    text = label(key, language, overrides)
    if text != key:
        return text
    # Imported here: this module is read by code that never draws a page.
    from app.core.register_export import printed_currency

    return printed_currency(currency, language)


def contractor_label_key(signature_roles: Sequence[str]) -> str:
    """The label key naming the paid party, the same in the header as in the signature block.

    A contract whose signature block is signed by the "subcontractor" names
    the party that way in the header too: one document, one name.
    """
    return "role.subcontractor" if "subcontractor" in signature_roles else "header.contractor"


#: The currency a country's certificates are expected in.
_HOME_CURRENCY: dict[str, str] = {"TR": "TRY"}


def is_foreign_currency(country_code: str | None, currency: str | None) -> bool:
    """Whether a certificate is in a currency other than its country's own.

    Such a certificate says that its lira equivalent is still to be stated;
    the exchange rate is not an input of the certificate, so none is printed.
    """
    home = _HOME_CURRENCY.get((country_code or "").strip().upper())
    return home is not None and (currency or "").strip().upper() != home


# ── Turkish-aware case ────────────────────────────────────────────────────


def tr_upper(text: str) -> str:
    """Upper-case Turkish text: ``i`` becomes ``İ`` and ``ı`` becomes ``I``.

    ``str.upper`` knows one alphabet and turns ``i`` into ``I``, which is a
    different Turkish letter: "işi" would print as "IŞI".
    """
    return text.replace("i", "İ").replace("ı", "I").upper()


def tr_lower(text: str) -> str:
    """Lower-case Turkish text: ``I`` becomes ``ı`` and ``İ`` becomes ``i``."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def upper_for(language: str, text: str) -> str:
    """Upper-case ``text`` by the rules of ``language``."""
    return tr_upper(text) if language == "tr" else text.upper()


# ── Layout checks ─────────────────────────────────────────────────────────


def validate_layout(layout: Sequence[SummaryLineDef]) -> None:
    """Refuse a layout that cannot be evaluated or printed.

    Raises:
        ValueError: A key or a letter appears twice, an operation is unknown,
            an operand names a line that does not exist, a tax line names no
            known figure, the lines depend on each other in a circle, or there
            is no ``payable`` line. The message names the key at fault.
    """
    keys: set[str] = set()
    letters: dict[str, str] = {}
    for line in layout:
        if not line.key:
            raise ValueError("hakedis layout has a line with an empty key")
        if line.key in keys:
            raise ValueError(f"hakedis layout defines line {line.key!r} twice")
        keys.add(line.key)
        if line.letter:
            if line.letter in letters:
                raise ValueError(
                    f"hakedis layout uses letter {line.letter!r} for both {letters[line.letter]!r} and {line.key!r}"
                )
            letters[line.letter] = line.key
        if line.op not in _OPS:
            raise ValueError(f"hakedis line {line.key!r} has unknown operation {line.op!r}")
        if line.sign not in (-1, 1):
            raise ValueError(f"hakedis line {line.key!r} has sign {line.sign!r}, expected 1 or -1")
    for line in layout:
        if line.op == "input":
            if len(line.operands) != 1 or line.operands[0] not in INPUT_SOURCES:
                raise ValueError(
                    f"hakedis line {line.key!r} must read exactly one of {', '.join(sorted(INPUT_SOURCES))}, "
                    f"got {list(line.operands)!r}"
                )
            continue
        if line.op in ("sum", "difference") and not line.operands:
            raise ValueError(f"hakedis line {line.key!r} is a {line.op} of nothing")
        if line.op == "tax" and line.tax_kind not in TAX_KINDS:
            raise ValueError(f"hakedis line {line.key!r} has unknown tax kind {line.tax_kind!r}")
        for operand in line.operands:
            if operand not in keys:
                raise ValueError(f"hakedis line {line.key!r} refers to line {operand!r}, which does not exist")
    if "payable" not in keys:
        raise ValueError("hakedis layout has no 'payable' line")
    evaluation_order(layout)


def evaluation_order(layout: Sequence[SummaryLineDef]) -> tuple[str, ...]:
    """The line keys in an order where every line follows what it depends on.

    Raises:
        ValueError: The lines depend on each other in a circle; the message
            names the keys on it.
    """
    by_key = {line.key: line for line in layout}
    done: list[str] = []
    state: dict[str, int] = {}

    def visit(key: str, trail: tuple[str, ...]) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            circle = " -> ".join((*trail[trail.index(key) :], key))
            raise ValueError(f"hakedis layout has a cycle through {key!r}: {circle}")
        state[key] = 1
        line = by_key[key]
        if line.op != "input":
            for operand in line.operands:
                if operand in by_key:
                    visit(operand, (*trail, key))
        state[key] = 2
        done.append(key)

    for line in layout:
        visit(line.key, ())
    return tuple(done)


# ── Formula text ──────────────────────────────────────────────────────────


def _operand_letters(line: SummaryLineDef, letters: Mapping[str, str]) -> list[str] | None:
    found = [letters.get(operand, "") for operand in line.operands]
    return found if found and all(found) else None


def line_formula(
    line: SummaryLineDef,
    layout: Sequence[SummaryLineDef],
    basis: Mapping[str, str],
    language: str,
    format_rate: Callable[[str], str],
) -> str:
    """The formula the form prints after a label, e.g. ``( C - D )`` or ``( E x %20 )``.

    Built from the letters of the layout in force, so a contract that
    re-letters its lines still prints formulas that point at the right ones.
    A total over more than three lines prints none, as on the form.

    Args:
        line: The line the formula belongs to.
        layout: The layout it sits in.
        basis: The computed line's basis; ``rate_pct``, ``numerator`` and
            ``denominator`` are read from it.
        language: ``tr`` writes the percent sign first (``%20``), ``en`` last.
        format_rate: Formats a decimal string the way the document prints numbers.
    """
    letters = {item.key: item.letter for item in layout}
    operands = _operand_letters(line, letters)
    if line.op == "sum":
        return f"( {' + '.join(operands)} )" if operands and 2 <= len(operands) <= 3 else ""
    if line.op == "difference":
        return f"( {' - '.join(operands)} )" if operands and len(operands) <= 3 else ""
    if line.op == "input" or operands is None:
        return ""
    numerator, denominator, rate = basis.get("numerator", ""), basis.get("denominator", ""), basis.get("rate_pct", "")
    if numerator and denominator:
        factor = f"{numerator}/{denominator}"
    elif rate:
        factor = f"%{format_rate(rate)}" if language == "tr" else f"{format_rate(rate)}%"
    elif line.op == "manual":
        return ""
    else:
        factor = "%.." if language == "tr" else "..%"
    return f"( {' - '.join(operands)} x {factor} )"


# ── Contract configuration ────────────────────────────────────────────────


@dataclass(frozen=True)
class HakedisSettings:
    """A contract's certificate configuration, resolved and checked.

    Attributes:
        layout: The summary lines in printed order.
        retention_source: Where the retention percent comes from:
            ``contract`` (the contract's own ``retention_percent``), ``fixed``
            (``retention_pct`` below) or ``none`` (no retention line).
        retention_pct: The percent when the source is ``fixed``.
        advance_recovery_pct: Percent of the base recovered against the
            advance on each certificate, or ``None`` when the amount is typed.
        advance_amount: The advance paid under the contract, or ``None`` when
            the contract does not state one. Nothing is computed from it; it
            is what the recoveries to date are checked against.
        tax_choices: The default choice per tax for a new certificate, keyed
            ``vat_withholding``, ``income_withholding``, ``stamp_duty``. A tax
            not listed is ``unset``: a person still has to decide it.
        not_applicable: Manual lines the contract rules out, with the reason.
        signature_roles: Role keys of the signature block, in printed order.
        columns: Works list column keys per flavour.
        labels: Label overrides, ``language -> key -> text``.
    """

    layout: tuple[SummaryLineDef, ...]
    retention_source: Literal["contract", "fixed", "none"] = "contract"
    retention_pct: Decimal | None = None
    advance_recovery_pct: Decimal | None = None
    advance_amount: Decimal | None = None
    tax_choices: Mapping[str, Choice] = field(default_factory=dict)
    not_applicable: Mapping[str, str] = field(default_factory=dict)
    signature_roles: tuple[str, ...] = ()
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    labels: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


_TERM_KEYS: frozenset[str] = frozenset(
    {
        "preset",
        "lines",
        "remove",
        "add",
        "letters",
        "operands",
        "reletter",
        "retention",
        "advance_recovery_pct",
        "advance_amount",
        "taxes",
        "not_applicable",
        "signature_roles",
        "columns",
        "labels",
    }
)
_LINE_KEYS: frozenset[str] = frozenset(
    {"key", "letter", "op", "operands", "sign", "tax_kind", "section", "after", "before", "total"}
)


def has_layout(country_code: str | None, contract_terms: Mapping[str, Any] | None = None) -> bool:
    """Whether the certificate exists for this project and contract.

    True when the country has a standard layout or the contract configures one
    itself (a preset or its own lines). Nothing else gates the document.
    """
    if (country_code or "").strip().upper() in DEFAULT_LAYOUTS:
        return True
    terms = (contract_terms or {}).get("hakedis") if isinstance(contract_terms, Mapping) else None
    return isinstance(terms, Mapping) and bool(terms.get("preset") or terms.get("lines"))


def _percent(value: Any, where: str) -> Decimal:
    try:
        pct = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"hakedis {where} must be a number, got {value!r}") from exc
    if not pct.is_finite() or pct < 0 or pct > 100:
        raise ValueError(f"hakedis {where} must be between 0 and 100, got {value!r}")
    return pct


def _line_from_mapping(raw: Any, where: str) -> SummaryLineDef:
    if not isinstance(raw, Mapping):
        raise ValueError(f"hakedis {where} must be an object, got {type(raw).__name__}")
    for name in raw:
        if name not in _LINE_KEYS:
            raise ValueError(f"hakedis {where} has unknown key {name!r}")
    key = str(raw.get("key") or "")
    if not key:
        raise ValueError(f"hakedis {where} has no 'key'")
    operands = raw.get("operands") or ()
    if isinstance(operands, str) or not isinstance(operands, Sequence):
        raise ValueError(f"hakedis line {key!r}: 'operands' must be a list of line keys")
    section = str(raw.get("section") or "deductions")
    sign = raw.get("sign", -1 if section == "deductions" else 1)
    if sign not in (-1, 1):
        raise ValueError(f"hakedis line {key!r} has sign {sign!r}, expected 1 or -1")
    return SummaryLineDef(
        key=key,
        letter=str(raw.get("letter") or ""),
        op=str(raw.get("op") or "manual"),  # type: ignore[arg-type]
        operands=tuple(str(operand) for operand in operands),
        sign=int(sign),
        tax_kind=str(raw.get("tax_kind") or ""),
        section=section,
    )


def _remove_line(lines: list[SummaryLineDef], key: str) -> list[SummaryLineDef]:
    """Drop a line.

    Totals stop adding it and a base stops subtracting it (the stamp duty base
    without an advance line is simply this certificate's amount). A line that
    reads it in any other way is left pointing at nothing, which the layout
    check then reports by name.
    """
    if key not in {line.key for line in lines}:
        raise ValueError(f"hakedis 'remove' names line {key!r}, which is not in the layout")
    kept: list[SummaryLineDef] = []
    for line in lines:
        if line.key == key:
            continue
        subtracted_from_base = line.op in ("tax", "manual", "retention") and key in line.operands[1:]
        if key in line.operands and (line.op == "sum" or subtracted_from_base):
            line = replace(line, operands=tuple(operand for operand in line.operands if operand != key))
        kept.append(line)
    return kept


def _reletter_deductions(lines: list[SummaryLineDef]) -> list[SummaryLineDef]:
    letters = iter("abcdefghijklmnopqrstuvwxyz")
    return [replace(line, letter=next(letters)) if line.section == "deductions" else line for line in lines]


def _layout_from_terms(base: tuple[SummaryLineDef, ...], terms: Mapping[str, Any]) -> list[SummaryLineDef]:
    lines = list(base)
    if terms.get("lines") is not None:
        raw_lines = terms["lines"]
        if isinstance(raw_lines, str) or not isinstance(raw_lines, Sequence):
            raise ValueError("hakedis 'lines' must be a list of line objects")
        lines = [_line_from_mapping(raw, f"lines[{index}]") for index, raw in enumerate(raw_lines)]
    for key in terms.get("remove") or ():
        lines = _remove_line(lines, str(key))
    for index, raw in enumerate(terms.get("add") or ()):
        new = _line_from_mapping(raw, f"add[{index}]")
        anchor_name = "after" if raw.get("after") else "before" if raw.get("before") else ""
        position = len(lines)
        if anchor_name:
            anchor = str(raw[anchor_name])
            positions = [i for i, line in enumerate(lines) if line.key == anchor]
            if not positions:
                raise ValueError(
                    f"hakedis line {new.key!r}: {anchor_name!r} names line {anchor!r}, which does not exist"
                )
            position = positions[0] + (1 if anchor_name == "after" else 0)
        else:
            # Without an anchor a new line joins the end of its own section.
            same = [i for i, line in enumerate(lines) if line.section == new.section]
            position = same[-1] + 1 if same else len(lines)
        lines.insert(position, new)
        total_key = str(raw.get("total") or ("deductions_total" if new.section == "deductions" else ""))
        if total_key:
            totals = [i for i, line in enumerate(lines) if line.key == total_key]
            if not totals:
                raise ValueError(f"hakedis line {new.key!r}: 'total' names line {total_key!r}, which does not exist")
            target = lines[totals[0]]
            if target.op != "sum":
                raise ValueError(f"hakedis line {new.key!r}: 'total' line {total_key!r} is not a sum")
            if new.key not in target.operands:
                lines[totals[0]] = replace(target, operands=(*target.operands, new.key))
    known = {line.key for line in lines}
    for key, operands in (terms.get("operands") or {}).items():
        if key not in known:
            raise ValueError(f"hakedis 'operands' names line {key!r}, which is not in the layout")
        if isinstance(operands, str) or not isinstance(operands, Sequence):
            raise ValueError(f"hakedis 'operands' for line {key!r} must be a list of line keys")
        lines = [
            replace(line, operands=tuple(str(operand) for operand in operands)) if line.key == key else line
            for line in lines
        ]
    # A total adds its lines in the order they are printed, whatever order
    # they were configured in.
    position_of = {line.key: index for index, line in enumerate(lines)}
    lines = [
        replace(line, operands=tuple(sorted(line.operands, key=lambda key: position_of.get(key, len(lines)))))
        if line.op == "sum"
        else line
        for line in lines
    ]
    if terms.get("reletter"):
        lines = _reletter_deductions(lines)
    for key, letter in (terms.get("letters") or {}).items():
        if key not in known:
            raise ValueError(f"hakedis 'letters' names line {key!r}, which is not in the layout")
        lines = [replace(line, letter=str(letter or "")) if line.key == key else line for line in lines]
    return lines


def _tax_choices(raw: Any) -> dict[str, Choice]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("hakedis 'taxes' must be an object keyed by tax")
    choices: dict[str, Choice] = {}
    for kind, value in raw.items():
        if kind not in _TAX_CHOICE_KINDS:
            raise ValueError(f"hakedis 'taxes' has unknown tax {kind!r}")
        if not isinstance(value, Mapping):
            raise ValueError(f"hakedis tax choice {kind!r} must be an object")
        state = str(value.get("state") or "")
        code = str(value.get("code") or "")
        reason = str(value.get("reason") or "")
        if state not in ("selected", "not_applicable", "unset"):
            raise ValueError(f"hakedis tax choice {kind!r} has unknown state {state!r}")
        if state == "selected" and not code:
            raise ValueError(f"hakedis tax choice {kind!r} is selected without a code")
        if state == "not_applicable" and not reason:
            raise ValueError(f"hakedis tax choice {kind!r} is not applicable without a reason")
        choices[kind] = Choice(state=state, code=code, reason=reason)  # type: ignore[arg-type]
    return choices


def resolve_settings(country_code: str | None, contract_terms: Mapping[str, Any] | None) -> HakedisSettings:
    """Resolve a contract's certificate configuration over its country's standard.

    ``contract_terms`` is ``Contract.terms``; only its ``"hakedis"`` entry is
    read. Keys of that entry, all optional:

    * ``preset``: a name from :data:`LAYOUT_PRESETS` to start from instead of
      the country's standard.
    * ``lines``: the whole line set, replacing the starting layout. Each line
      is ``{key, letter, op, operands, sign, tax_kind, section}``.
    * ``remove``: line keys to drop. Totals stop adding a removed line.
    * ``add``: lines to insert, each optionally with ``after`` or ``before``
      (a line key) and ``total`` (the sum line that adds it; deductions join
      ``deductions_total`` unless told otherwise).
    * ``operands``: ``{line key: [line keys]}``, e.g. a retention base that
      leaves the price adjustment out.
    * ``reletter``: true to letter the deductions a, b, c in printed order.
    * ``letters``: ``{line key: letter}``, applied last.
    * ``retention``: ``{"source": "contract" | "fixed" | "none", "pct": "5",
      "base": [line keys]}``.
    * ``advance_recovery_pct``: percent of the advance line's base.
    * ``advance_amount``: the advance paid, which recoveries are checked against.
    * ``taxes``: ``{tax: {"state", "code", "reason"}}`` default choices.
    * ``not_applicable``: ``{manual line key: reason}``.
    * ``signature_roles``: role keys in printed order.
    * ``columns``: ``{"unit_price" | "lump_sum": [column keys]}``.
    * ``labels``: ``{"tr" | "en": {label key: text}}`` for lines and roles the
      built-in table does not know.

    Raises:
        ValueError: The country has no standard layout and the contract names
            none, or the configuration is not usable. The message names the
            key at fault.
    """
    country = (country_code or "").strip().upper()
    raw = (contract_terms or {}).get("hakedis") if isinstance(contract_terms, Mapping) else None
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError("Contract.terms['hakedis'] must be an object")
    for name in raw:
        if name not in _TERM_KEYS:
            raise ValueError(f"Contract.terms['hakedis'] has unknown key {name!r}")

    preset = raw.get("preset")
    if preset is not None:
        if preset not in LAYOUT_PRESETS:
            raise ValueError(f"hakedis 'preset' names unknown layout {preset!r}")
        base = LAYOUT_PRESETS[str(preset)]
    elif country in DEFAULT_LAYOUTS:
        base = DEFAULT_LAYOUTS[country]
    elif raw.get("lines") is not None:
        base = ()
    else:
        raise ValueError(f"no hakedis layout for country {country!r} and the contract configures none")

    lines = _layout_from_terms(base, raw)

    retention_raw = raw.get("retention") or {}
    if not isinstance(retention_raw, Mapping):
        raise ValueError("hakedis 'retention' must be an object")
    for name in retention_raw:
        if name not in ("source", "pct", "base"):
            raise ValueError(f"hakedis 'retention' has unknown key {name!r}")
    retention_pct = _percent(retention_raw["pct"], "retention pct") if retention_raw.get("pct") is not None else None
    source = str(retention_raw.get("source") or ("fixed" if retention_pct is not None else "contract"))
    if source not in ("contract", "fixed", "none"):
        raise ValueError(f"hakedis 'retention' has unknown source {source!r}")
    if source == "fixed" and retention_pct is None:
        raise ValueError("hakedis 'retention' source is 'fixed' but no 'pct' is given")
    retention_keys = [line.key for line in lines if line.op == "retention"]
    if source == "none":
        for key in retention_keys:
            lines = _remove_line(lines, key)
    elif retention_raw.get("base") is not None:
        base_keys = retention_raw["base"]
        if isinstance(base_keys, str) or not isinstance(base_keys, Sequence):
            raise ValueError("hakedis 'retention' base must be a list of line keys")
        lines = [
            replace(line, operands=tuple(str(key) for key in base_keys)) if line.op == "retention" else line
            for line in lines
        ]

    layout = tuple(lines)
    validate_layout(layout)
    by_key = {line.key: line for line in layout}

    advance_pct = (
        _percent(raw["advance_recovery_pct"], "advance_recovery_pct")
        if raw.get("advance_recovery_pct") is not None
        else None
    )
    if advance_pct is not None:
        advance = by_key.get("advance_recovery")
        if advance is None or advance.op != "manual" or not advance.operands:
            raise ValueError("hakedis 'advance_recovery_pct' needs a manual 'advance_recovery' line with a base")

    advance_amount: Decimal | None = None
    if raw.get("advance_amount") is not None:
        try:
            advance_amount = Decimal(str(raw["advance_amount"]))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"hakedis 'advance_amount' must be a number, got {raw['advance_amount']!r}") from exc
        if not advance_amount.is_finite() or advance_amount < 0:
            raise ValueError(f"hakedis 'advance_amount' must not be negative, got {raw['advance_amount']!r}")

    not_applicable_raw = raw.get("not_applicable") or {}
    if not isinstance(not_applicable_raw, Mapping):
        raise ValueError("hakedis 'not_applicable' must be an object of line key to reason")
    not_applicable: dict[str, str] = {}
    for key, reason in not_applicable_raw.items():
        if key not in by_key or by_key[key].op != "manual":
            raise ValueError(f"hakedis 'not_applicable' names {key!r}, which is not a manual line of the layout")
        if not str(reason or "").strip():
            raise ValueError(f"hakedis 'not_applicable' gives no reason for line {key!r}")
        not_applicable[str(key)] = str(reason)

    labels_raw = raw.get("labels") or {}
    if not isinstance(labels_raw, Mapping):
        raise ValueError("hakedis 'labels' must be an object keyed by language")
    labels: dict[str, Mapping[str, str]] = {}
    for language, table in labels_raw.items():
        if language not in HAKEDIS_LABELS:
            raise ValueError(f"hakedis 'labels' has unknown language {language!r}")
        if not isinstance(table, Mapping):
            raise ValueError(f"hakedis 'labels' for {language!r} must be an object")
        labels[str(language)] = MappingProxyType({str(key): str(text) for key, text in table.items()})
    for line in layout:
        for language, table in HAKEDIS_LABELS.items():
            name = f"line.{line.key}"
            if name not in table and name not in labels.get(language, {}):
                raise ValueError(f"hakedis line {line.key!r} has no {language!r} label; add it under 'labels'")

    roles_raw = raw.get("signature_roles")
    if roles_raw is None:
        roles = DEFAULT_SIGNATURE_ROLES.get(country, DEFAULT_SIGNATURE_ROLES["TR"])
    else:
        if isinstance(roles_raw, str) or not isinstance(roles_raw, Sequence) or not roles_raw:
            raise ValueError("hakedis 'signature_roles' must be a non-empty list of role keys")
        roles = tuple(str(role) for role in roles_raw)
        for role in roles:
            for language, table in HAKEDIS_LABELS.items():
                name = f"role.{role}"
                if name not in table and name not in labels.get(language, {}):
                    raise ValueError(
                        f"hakedis signature role {role!r} has no {language!r} label; add it under 'labels'"
                    )

    columns_raw = raw.get("columns") or {}
    if not isinstance(columns_raw, Mapping):
        raise ValueError("hakedis 'columns' must be an object keyed by flavour")
    columns: dict[str, tuple[str, ...]] = dict(WORKS_DEFAULT_COLUMNS)
    for flavour, keys in columns_raw.items():
        if flavour not in WORKS_COLUMNS:
            raise ValueError(f"hakedis 'columns' has unknown flavour {flavour!r}")
        if isinstance(keys, str) or not isinstance(keys, Sequence) or not keys:
            raise ValueError(f"hakedis 'columns' for {flavour!r} must be a non-empty list of column keys")
        known_columns = {column.key for column in WORKS_COLUMNS[flavour]}
        for key in keys:
            if key not in known_columns:
                raise ValueError(f"hakedis 'columns' for {flavour!r} has unknown column {key!r}")
        columns[str(flavour)] = tuple(str(key) for key in keys)

    return HakedisSettings(
        layout=layout,
        retention_source=source,  # type: ignore[arg-type]
        retention_pct=retention_pct if source == "fixed" else None,
        advance_recovery_pct=advance_pct,
        advance_amount=advance_amount,
        tax_choices=MappingProxyType(_tax_choices(raw.get("taxes"))),
        not_applicable=MappingProxyType(not_applicable),
        signature_roles=roles,
        columns=MappingProxyType(columns),
        labels=MappingProxyType(labels),
    )


def resolve_layout(country_code: str, contract_terms: Mapping | None) -> tuple[SummaryLineDef, ...]:
    """The summary lines for a contract: the country's standard with the contract's changes.

    Raises:
        ValueError: As :func:`resolve_settings`.
    """
    return resolve_settings(country_code, contract_terms).layout
