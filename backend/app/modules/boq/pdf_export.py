# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PDF report generation for BOQ cost estimates.

Produces a professional multi-page PDF document with:
- Cover page: project name, BOQ title, cost summary, date, status
- Table of contents with page numbers, for a bill of more than one section
- BOQ table pages: sections, positions, subtotals, markups, totals
- Cost summary page: each section's subtotal, then the totals
- Running headers/footers with page numbering

Security note (BUG-PDF01 / BUG-PDF02):
    ReportLab's ``Paragraph`` parses a subset of HTML (``<b>``, ``<i>``,
    ``<font color>``, ``<para>``, etc.). Passing a user-supplied string
    that contains unknown HTML attributes (``onerror``, ``onclick``)
    crashes ``paraparser`` with a ``ValueError``, which propagated as a
    500 from the ``/export/pdf`` endpoint and made the entire reporting
    feature DoSable by anyone with ``boq.update`` rights. Worse, valid
    markup like ``<font color="white">hidden</font>`` rendered in the
    output, allowing a malicious description to hide content in print.

    The fix is to escape every user-controlled string with ``html.escape``
    before handing it to ``Paragraph``. The helper below ``_safe_para``
    does both: coerces non-strings, escapes, then constructs the
    paragraph. Internal labels that legitimately use ReportLab markup
    (``<b>Pos.</b>``) bypass it and continue to use ``Paragraph`` directly.
"""

import html
import io
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, NamedTuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.pdf_branding import (
    branded_cover_brand,
    branded_doc_metadata,
    branded_header_logo,
    branded_letterhead,
)

# Locale-aware PDF labels. Keyed by locale prefix (first 2 chars of the project
# locale). Falls back to English when the locale is unknown, and key by key to
# English when a locale lacks one, so a label added later never raises.
#
# Written in each language's own script and with its own diacritics. The table
# used to carry Russian in Latin transliteration ("SMETNYJ RASCHET") and drop
# the accents from French, Spanish, Portuguese and Turkish, from the days the
# generator printed in a Latin-1 base font. Every label here reaches the page
# through the bundled Unicode face (``app.core.pdf_fonts``), so that reason is
# gone. Chinese stays in English: a label is drawn in the style's own face
# without the per-string Chinese route that user text takes.
#
# ``positions_omitted`` carries a ``{count}`` placeholder and is phrased so the
# number never has to agree with a noun, which Russian and Ukrainian would
# otherwise need three plural forms for.
_PDF_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "cost_estimate": "COST ESTIMATE",
        "summary": "SUMMARY",
        "project": "Project:",
        "boq": "BOQ:",
        "date": "Date:",
        "status": "Status:",
        "prepared_by": "Prepared by:",
        "approved_by": "Approved by:",
        "signature_hint": "Name / Signature / Date",
        "contents": "Sections / Positions:",
        "pos": "Pos.",
        "description": "Description",
        "unit": "Unit",
        "qty": "Qty",
        "rate": "Rate",
        "total": "Total",
        "subtotal": "Subtotal:",
        "other_positions": "Other Positions",
        "direct_cost": "Direct Cost:",
        "markups": "Markups (excl. tax):",
        "net_total": "Net Total (excl. tax):",
        "gross_total": "Gross Total",
        "page": "Page",
        "of": "of",
        "generated": "Generated:",
        "summary_report": "Summary Report",
        "positions_omitted": "{count} positions (full detail omitted for performance)",
        "section": "Section",
        "items": "Items",
        "cost_summary": "Cost Summary",
        "table_of_contents": "Table of Contents",
        "status_draft": "Draft",
        "status_final": "Final",
        "status_archived": "Archived",
        "subject": "Bill of Quantities",
        "tax_vat": "VAT",
    },
    "de": {
        "cost_estimate": "KOSTENSCHÄTZUNG",
        "summary": "ZUSAMMENFASSUNG",
        "project": "Projekt:",
        "boq": "LV:",
        "date": "Datum:",
        "status": "Status:",
        "prepared_by": "Erstellt von:",
        "approved_by": "Freigegeben von:",
        "signature_hint": "Name / Unterschrift / Datum",
        "contents": "Abschnitte / Positionen:",
        "pos": "Pos.",
        "description": "Beschreibung",
        "unit": "Einheit",
        "qty": "Menge",
        "rate": "EP",
        "total": "Gesamt",
        "subtotal": "Zwischensumme:",
        "other_positions": "Sonstige Positionen",
        "direct_cost": "Direktkosten:",
        "markups": "Zuschläge (ohne MwSt.):",
        "net_total": "Netto (ohne MwSt.):",
        "gross_total": "Brutto",
        "page": "Seite",
        "of": "von",
        "generated": "Erstellt:",
        "summary_report": "Kurzbericht",
        "positions_omitted": "{count} Positionen (Einzelaufstellung aus Leistungsgründen ausgelassen)",
        "section": "Abschnitt",
        "items": "Positionen",
        "cost_summary": "Kostenübersicht",
        "table_of_contents": "Inhaltsverzeichnis",
        "status_draft": "Entwurf",
        "status_final": "Freigegeben",
        "status_archived": "Archiviert",
        "subject": "Leistungsverzeichnis",
        "tax_vat": "MwSt.",
    },
    "fr": {
        "cost_estimate": "ESTIMATION DES COÛTS",
        "summary": "RÉSUMÉ",
        "project": "Projet :",
        "boq": "DQE :",
        "date": "Date :",
        "status": "Statut :",
        "prepared_by": "Préparé par :",
        "approved_by": "Approuvé par :",
        "signature_hint": "Nom / Signature / Date",
        "contents": "Lots / Postes :",
        "pos": "Pos.",
        "description": "Description",
        "unit": "Unité",
        "qty": "Qté",
        "rate": "PU",
        "total": "Total",
        "subtotal": "Sous-total :",
        "other_positions": "Autres postes",
        "direct_cost": "Coût direct :",
        "markups": "Majorations (HT) :",
        "net_total": "Total HT :",
        "gross_total": "Total TTC",
        "page": "Page",
        "of": "sur",
        "generated": "Généré le :",
        "summary_report": "Rapport de synthèse",
        "positions_omitted": "{count} postes (détail omis pour des raisons de performance)",
        "section": "Lot",
        "items": "Postes",
        "cost_summary": "Récapitulatif des coûts",
        "table_of_contents": "Table des matières",
        "status_draft": "Brouillon",
        "status_final": "Validé",
        "status_archived": "Archivé",
        "subject": "Détail quantitatif estimatif",
        "tax_vat": "TVA",
    },
    "es": {
        "cost_estimate": "PRESUPUESTO",
        "summary": "RESUMEN",
        "project": "Proyecto:",
        "boq": "Presupuesto:",
        "date": "Fecha:",
        "status": "Estado:",
        "prepared_by": "Preparado por:",
        "approved_by": "Aprobado por:",
        "signature_hint": "Nombre / Firma / Fecha",
        "contents": "Capítulos / Partidas:",
        "pos": "Pos.",
        "description": "Descripción",
        "unit": "Unidad",
        "qty": "Cant.",
        "rate": "PU",
        "total": "Total",
        "subtotal": "Subtotal:",
        "other_positions": "Otras partidas",
        "direct_cost": "Coste directo:",
        "markups": "Recargos (sin IVA):",
        "net_total": "Total neto (sin IVA):",
        "gross_total": "Total bruto",
        "page": "Página",
        "of": "de",
        "generated": "Generado:",
        "summary_report": "Informe resumido",
        "positions_omitted": "{count} partidas (detalle omitido por rendimiento)",
        "section": "Capítulo",
        "items": "Partidas",
        "cost_summary": "Resumen de costes",
        "table_of_contents": "Índice",
        "status_draft": "Borrador",
        "status_final": "Aprobado",
        "status_archived": "Archivado",
        "subject": "Presupuesto y mediciones",
        "tax_vat": "IVA",
    },
    "ru": {
        "cost_estimate": "СМЕТНЫЙ РАСЧЁТ",
        "summary": "ИТОГИ",
        "project": "Проект:",
        "boq": "Смета:",
        "date": "Дата:",
        "status": "Статус:",
        "prepared_by": "Составил:",
        "approved_by": "Утвердил:",
        "signature_hint": "ФИО / Подпись / Дата",
        "contents": "Разделы / Позиции:",
        "pos": "№ п/п",
        "description": "Наименование",
        "unit": "Ед. изм.",
        "qty": "Кол-во",
        "rate": "Цена",
        "total": "Сумма",
        "subtotal": "Итого по разделу:",
        "other_positions": "Прочие позиции",
        "direct_cost": "Прямые затраты:",
        "markups": "Начисления (без НДС):",
        "net_total": "Итого без НДС:",
        "gross_total": "Всего с НДС",
        "page": "Стр.",
        "of": "из",
        "generated": "Составлено:",
        "summary_report": "Сводный отчёт",
        "positions_omitted": "Позиций: {count} (детализация опущена для быстродействия)",
        "section": "Раздел",
        "items": "Позиций",
        "cost_summary": "Сводка затрат",
        "table_of_contents": "Содержание",
        "status_draft": "Черновик",
        "status_final": "Утверждена",
        "status_archived": "В архиве",
        "subject": "Смета",
        "tax_vat": "НДС",
    },
    "uk": {
        "cost_estimate": "КОШТОРИСНИЙ РОЗРАХУНОК",
        "summary": "ПІДСУМКИ",
        "project": "Проєкт:",
        "boq": "Кошторис:",
        "date": "Дата:",
        "status": "Статус:",
        "prepared_by": "Склав:",
        "approved_by": "Затвердив:",
        "signature_hint": "ПІБ / Підпис / Дата",
        "contents": "Розділи / Позиції:",
        "pos": "№ з/п",
        "description": "Найменування",
        "unit": "Од. вим.",
        "qty": "Кількість",
        "rate": "Ціна",
        "total": "Сума",
        "subtotal": "Разом за розділом:",
        "other_positions": "Інші позиції",
        "direct_cost": "Прямі витрати:",
        "markups": "Нарахування (без ПДВ):",
        "net_total": "Разом без ПДВ:",
        "gross_total": "Усього з ПДВ",
        "page": "Стор.",
        "of": "з",
        "generated": "Складено:",
        "summary_report": "Зведений звіт",
        "positions_omitted": "Позицій: {count} (деталізацію пропущено для швидкодії)",
        "section": "Розділ",
        "items": "Позицій",
        "cost_summary": "Зведення витрат",
        "table_of_contents": "Зміст",
        "status_draft": "Чернетка",
        "status_final": "Затверджено",
        "status_archived": "В архіві",
        "subject": "Кошторис",
        "tax_vat": "ПДВ",
    },
    "hu": {
        "cost_estimate": "KÖLTSÉGBECSLÉS",
        "summary": "ÖSSZESÍTÉS",
        "project": "Projekt:",
        "boq": "Költségvetés:",
        "date": "Dátum:",
        "status": "Állapot:",
        "prepared_by": "Készítette:",
        "approved_by": "Jóváhagyta:",
        "signature_hint": "Név / Aláírás / Dátum",
        "contents": "Fejezetek / Tételek:",
        "pos": "Tétel",
        "description": "Megnevezés",
        "unit": "Egység",
        "qty": "Mennyiség",
        "rate": "Egységár",
        "total": "Összeg",
        "subtotal": "Részösszeg:",
        "other_positions": "Egyéb tételek",
        "direct_cost": "Közvetlen költség:",
        "markups": "Pótlékok (ÁFA nélkül):",
        "net_total": "Nettó összesen (ÁFA nélkül):",
        "gross_total": "Bruttó összesen",
        "page": "Oldal",
        "of": "/",
        "generated": "Készült:",
        "summary_report": "Összesítő jelentés",
        "positions_omitted": "Tételek száma: {count} (a részletezés teljesítményokokból elmarad)",
        "section": "Fejezet",
        "items": "Tételek",
        "cost_summary": "Költségösszesítő",
        "table_of_contents": "Tartalomjegyzék",
        "status_draft": "Piszkozat",
        "status_final": "Jóváhagyva",
        "status_archived": "Archiválva",
        "subject": "Költségvetés",
        "tax_vat": "ÁFA",
    },
    "zh": {
        "cost_estimate": "COST ESTIMATE",
        "summary": "SUMMARY",
        "project": "Project:",
        "boq": "BOQ:",
        "date": "Date:",
        "status": "Status:",
        "prepared_by": "Prepared by:",
        "pos": "Pos.",
        "description": "Description",
        "unit": "Unit",
        "qty": "Qty",
        "rate": "Rate",
        "total": "Total",
        "subtotal": "Subtotal:",
        "other_positions": "Other",
        "direct_cost": "Direct Cost:",
        "net_total": "Net Total:",
        "gross_total": "Gross Total",
        "page": "Page",
        "of": "of",
        "generated": "Generated:",
    },
    "pt": {
        "cost_estimate": "ORÇAMENTO",
        "summary": "RESUMO",
        "project": "Projeto:",
        "boq": "Orçamento:",
        "date": "Data:",
        "status": "Estado:",
        "prepared_by": "Preparado por:",
        "approved_by": "Aprovado por:",
        "signature_hint": "Nome / Assinatura / Data",
        "contents": "Capítulos / Itens:",
        "pos": "Pos.",
        "description": "Descrição",
        "unit": "Unid.",
        "qty": "Qtd.",
        "rate": "PU",
        "total": "Total",
        "subtotal": "Subtotal:",
        "other_positions": "Outros itens",
        "direct_cost": "Custo direto:",
        "markups": "Encargos (s/ impostos):",
        "net_total": "Total s/ impostos:",
        "gross_total": "Total c/ impostos",
        "page": "Página",
        "of": "de",
        "generated": "Gerado:",
        "summary_report": "Relatório resumido",
        "positions_omitted": "{count} itens (detalhe omitido por desempenho)",
        "section": "Capítulo",
        "items": "Itens",
        "cost_summary": "Resumo de custos",
        "table_of_contents": "Índice",
        "status_draft": "Rascunho",
        "status_final": "Aprovado",
        "status_archived": "Arquivado",
        "subject": "Orçamento",
        "tax_vat": "IVA",
    },
    "tr": {
        "cost_estimate": "MALİYET TAHMİNİ",
        "summary": "ÖZET",
        "project": "Proje:",
        "boq": "Metraj:",
        "date": "Tarih:",
        "status": "Durum:",
        "prepared_by": "Hazırlayan:",
        "approved_by": "Onaylayan:",
        "signature_hint": "Ad Soyad / İmza / Tarih",
        "contents": "Bölümler / Kalemler:",
        "pos": "Poz.",
        "description": "Tanım",
        "unit": "Birim",
        "qty": "Miktar",
        "rate": "BF",
        "total": "Toplam",
        "subtotal": "Ara toplam:",
        "other_positions": "Diğer kalemler",
        "direct_cost": "Doğrudan maliyet:",
        "markups": "Ek giderler (KDV hariç):",
        "net_total": "Net toplam (KDV hariç):",
        "gross_total": "Genel toplam",
        "page": "Sayfa",
        "of": "/",
        "generated": "Oluşturulma:",
        "summary_report": "Özet rapor",
        "positions_omitted": "{count} kalem (performans için ayrıntı gösterilmedi)",
        "section": "Bölüm",
        "items": "Kalem",
        "cost_summary": "Maliyet özeti",
        "table_of_contents": "İçindekiler",
        "status_draft": "Taslak",
        "status_final": "Onaylandı",
        "status_archived": "Arşivlendi",
        "subject": "Keşif ve metraj",
        "tax_vat": "KDV",
    },
}


def _get_pdf_labels(locale: str) -> dict[str, str]:
    """Resolve PDF labels for the given locale, English filling any key it lacks."""
    prefix = (locale or "en")[:2].lower()
    return {**_PDF_LABELS["en"], **_PDF_LABELS.get(prefix, {})}


def pdf_language(locale: str) -> str:
    """The language the PDF's own labels are printed in, for ``Content-Language``.

    The project locale's table when there is one, English otherwise. Chinese
    has a table that is English on purpose (see the note above
    ``_PDF_LABELS``), so a Chinese bill's labels are English and say so.
    """
    prefix = (locale or "en")[:2].lower()
    return prefix if prefix in _PDF_LABELS and prefix != "zh" else "en"


def _status_label(status: str | None, labels: dict[str, str]) -> str:
    """The bill's lifecycle state in the document's language.

    ``draft``, ``final`` and ``archived`` are the whole state set a bill has.
    Anything else is shown as stored, capitalised, rather than guessed at.
    """
    value = (status or "draft").strip().lower()
    return labels.get(f"status_{value}") or value.capitalize()


from app.core.pdf_fonts import (
    BODY_FONT,
    BOLD_FONT,
    pdf_fit_line,
    pdf_fitted_style,
    pdf_room_beside,
    pdf_style_for_text,
    register_pdf_fonts,
)
from app.core.regional_format import format_date, format_number, number_style
from app.core.unit_conversion import convert as convert_units
from app.core.unit_conversion import display_rate

# Register the bundled Unicode (DejaVu) faces with reportlab. Idempotent and
# safe at import time because reportlab is imported at module level here.
register_pdf_fonts()

# Page dimensions
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 20 * mm
MARGIN_RIGHT = 20 * mm
MARGIN_TOP = 25 * mm
MARGIN_BOTTOM = 20 * mm
USABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

# Column widths for the BOQ table (Pos | Description | Unit | Qty | Rate | Total)
COL_POS = 35 * mm
COL_DESC = USABLE_WIDTH - 35 * mm - 20 * mm - 25 * mm - 30 * mm - 30 * mm
COL_UNIT = 20 * mm
COL_QTY = 25 * mm
COL_RATE = 30 * mm
COL_TOTAL = 30 * mm
TABLE_COL_WIDTHS = [COL_POS, COL_DESC, COL_UNIT, COL_QTY, COL_RATE, COL_TOTAL]


# Currencies with zero decimals (no cents).
_ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
    {
        "JPY",
        "KRW",
        "VND",
        "CLP",
        "HUF",
        "ISK",
    }
)


def _fmt(value: float, decimals: int = 2, currency: str = "", country: str = "") -> str:
    """Format a number the way the project's country writes it.

    The country decides the separators, read from ``COUNTRY_DEFAULTS`` through
    :mod:`app.core.regional_format`: an Irish euro bill is ``1,234.56``, a
    German one ``1.234,56``, a French or Ukrainian one ``1 234,56`` with a
    no-break space, a Swiss one ``1'234.56``. With no country the currency
    decides, exactly as it did before the country was consulted, so a call
    without one prints what it always printed (EUR ``1.234,56``, USD
    ``1,234.56``, INR ``12,34,567.89``, CHF ``1'234.56``), with one
    correction: a hryvnia, tenge or Belarusian rouble is spaced rather than
    American.

    A zero-decimal currency (JPY, KRW, HUF ...) prints whole units whatever
    ``decimals`` asks for. Use :func:`_fmt_rate` for a percentage, which is
    not an amount of that currency and keeps its fraction.
    """
    ccy = (currency or "").upper()
    if ccy in _ZERO_DECIMAL_CURRENCIES:
        decimals = 0
    return format_number(value, decimals, number_style(country, ccy))


def _fmt_rate(value: float, decimals: int, currency: str = "", country: str = "") -> str:
    """A percentage in the market's separators, never rounded to a currency's units.

    Routing a rate through :func:`_fmt` printed a Japanese 10.5 per cent
    markup as ``10%`` and a Hungarian 13.5 per cent one as ``14%``, because
    the yen and the forint have no subunit and the rate inherited that.
    """
    return format_number(value, decimals, number_style(country, currency))


def _safe_para(text: Any, style: ParagraphStyle) -> "Paragraph":
    """Construct a ``Paragraph`` from possibly-untrusted user input.

    HTML metacharacters in ``text`` are escaped via ``html.escape`` so
    ReportLab's paraparser sees inert characters, not markup. ``None``
    becomes empty; other non-string values are rendered through ``str``
    before escaping. Use this anywhere a value originated outside the
    application's control (BOQ position descriptions, ordinals, units,
    section titles, the ``prepared_by`` field, project names, etc.).

    Internal labels that need ReportLab inline markup such as ``<b>...</b>``
    construct ``Paragraph`` directly - that text is checked into source and
    trusted.

    This is also where the Chinese face is chosen. Every string a Chinese bill
    of quantities carries - the section titles, the item descriptions, the unit
    labels, the markup names - reaches the document through here, so asking
    ``pdf_style_for_text`` for the face once, at the funnel, wires the whole
    generator rather than each call site. The style handed in is returned
    unchanged for anything that is not Chinese.
    """
    if text is None:
        rendered = ""
    elif isinstance(text, str):
        rendered = text
    else:
        rendered = str(text)
    return Paragraph(html.escape(rendered, quote=True), pdf_style_for_text(style, rendered))


def _fmt_currency(value: float, currency: str, decimals: int = 2, country: str = "") -> str:
    """Format a monetary amount with currency code appended.

    Examples:
        _fmt_currency(1234.56, "EUR") -> "1.234,56 EUR"
        _fmt_currency(1234.56, "EUR", country="IE") -> "1,234.56 EUR"
        _fmt_currency(1234.56, "USD") -> "1,234.56 USD"
        _fmt_currency(1234.56, "UAH") -> "1 234,56 UAH" (no-break space)
    """
    formatted = _fmt(value, decimals, currency, country)
    return f"{formatted} {currency}"


def _tax_label(markup: Any, currency: str, country: str = "") -> str:
    """A tax line's own name and rate, so a stack of several stays readable.

    Two decimals rather than the one the other markup rows use, because a rate
    like Brazil's 3.65 loses its meaning when rounded to 3.7.
    """
    if getattr(markup, "markup_type", "") == "percentage":
        return f"{markup.name} ({_fmt_rate(markup.percentage, 2, currency, country)}%)"
    return str(markup.name)


# Countries whose consumption levy is NOT a value-added tax, by the name the
# levy goes by. Printing "VAT" on a US or Indian bill names a tax that does not
# exist there, and these names are proper names, so they are written the same
# in every document language.
#
# A country whose levy IS a VAT is deliberately absent. Its word is the
# document language's own word for VAT, the ``tax_vat`` label: a Ukrainian
# bill written in Ukrainian says ПДВ, the same bill written in English says
# VAT and in Russian НДС. The table used to carry those words keyed by country
# and in Latin transliteration ("PDV", "NDS"), so a Ukrainian-language PDF
# printed Cyrillic everywhere and then "PDV 0%:", and an English one for the
# same project printed a word its reader could not place.
_TAX_LABEL_BY_COUNTRY: dict[str, str] = {
    "US": "Sales Tax",
    "CA": "GST/HST",
    "AU": "GST",
    "NZ": "GST",
    "SG": "GST",
    "IN": "GST",
    "JP": "Consumption Tax",
    "BR": "ICMS",
}


def _zero_tax_fallback_label(country_code: str, labels: dict[str, str] | None = None) -> str:
    """Return the fallback label for a bill that carries no tax markup at all.

    A levy that is not a VAT keeps its own name ("Sales Tax 0%:" for the
    United States, "GST 0%:" for India). Every other country is written with
    the document language's word for VAT, from the ``tax_vat`` label, so the
    word is in the same language and script as the rest of the page.

    Args:
        country_code: The project's country, ISO 3166-1 alpha-2, may be empty.
        labels: The document's labels from :func:`_get_pdf_labels`; English
            when omitted.
    """
    cc = (country_code or "").upper()
    lb = labels or _PDF_LABELS["en"]
    label = _TAX_LABEL_BY_COUNTRY.get(cc) or lb.get("tax_vat") or "VAT"
    return f"{label} 0%:"


def _tax_split(boq_data: Any) -> tuple[list[Any], Decimal, Decimal, Decimal]:
    """Split a priced bill into its pre-tax subtotal, its tax lines and its total.

    The tax is already inside ``net_total``. ``get_boq_structured`` computes
    ``net_total = direct_cost + sum(every active markup)`` and sets
    ``grand_total`` to exactly that, and the markup calculator has no notion of
    a tax category, so a VAT line is one markup among the others. The exports
    here used to read that figure as if it were net OF tax and add a tax on top
    of it, which overstated a German bill by the whole nineteen per cent and
    printed a Gross Total the application itself never agreed with.

    Two things follow and both are the caller's to honour: the pre-tax subtotal
    is ``net_total`` MINUS the tax rather than plus, and the total of everything
    is ``net_total`` unchanged.

    ``tax_lines`` is every active tax markup rather than the first one found.
    Brazil's stack carries two, PIS + COFINS and ISS, and stopping at the first
    dropped the second from the tax section while its money stayed inside the
    total, so the printed figures did not add up down the column.

    Returns ``(tax_lines, tax_amount, subtotal_excluding_tax, gross_total)``.
    """
    markups = getattr(boq_data, "markups", None) or []
    tax_lines = [m for m in markups if getattr(m, "category", "") == "tax" and m.is_active]
    tax_amount = sum((Decimal(str(m.amount)) for m in tax_lines), Decimal("0"))
    gross_total = Decimal(str(boq_data.net_total))
    return tax_lines, tax_amount, gross_total - tax_amount, gross_total


def _position_meta(pos: Any) -> dict[str, Any]:
    """A position's metadata, whichever name the object carries it under."""
    meta = getattr(pos, "metadata", None)
    if not isinstance(meta, dict):
        meta = getattr(pos, "metadata_", None)
    return meta if isinstance(meta, dict) else {}


def _line_money(pos: Any, base_currency: str, fx_rates: Mapping[str, str] | None) -> tuple[Decimal, Decimal]:
    """A line's total and unit rate in the project's base currency.

    The section subtotals, the direct cost and every total below them are
    already in the base currency: :meth:`BOQService.get_boq_structured` rolls
    each leaf up through ``_leaf_total_base_with_resources``. The lines have to
    be read through the same function, or a line priced in dollars on a euro
    bill prints its dollar figure under a "Total (EUR)" heading and the lines
    of a section stop adding up to the subtotal printed under them.

    The rate goes through the same function with a quantity of one, so it is
    converted the same way the total is (from the position's own currency, or
    resource by resource) and ``quantity x rate`` still makes the line. A line
    already in the base currency comes back exactly as stored.

    The helper reads ``metadata_``, the ORM name; the export payload carries
    ``metadata``, so it is handed a stand-in with the name it reads.
    """
    from app.modules.boq.service import _leaf_total_base_with_resources

    meta = _position_meta(pos)
    fx = dict(fx_rates or {})
    quantity = getattr(pos, "quantity", 0) or 0
    unit_rate = getattr(pos, "unit_rate", 0) or 0
    total = getattr(pos, "total", 0) or 0
    line = SimpleNamespace(metadata_=meta, total=total, quantity=quantity)
    per_unit = SimpleNamespace(metadata_=meta, total=unit_rate, quantity=1)
    return (
        _leaf_total_base_with_resources(line, fx, base_currency),
        _leaf_total_base_with_resources(per_unit, fx, base_currency),
    )


class _ResourceLine(NamedTuple):
    """One resource of a position, scaled to the position's quantity."""

    name: str
    unit: str
    quantity: Decimal
    unit_rate: Decimal
    total: Decimal


def _resource_lines(pos: Any, base_currency: str, fx_rates: Mapping[str, str] | None) -> list[_ResourceLine]:
    """The resources a position is built from, as lines of the bill.

    A resource is stored per unit of its position (0.25 h of labour per m3),
    which is how the position's unit rate is built from them. Printed under a
    line whose quantity is 120 m3, a per-unit figure in the Total column reads
    as the resource's share of the line and is off by a factor of 120, so each
    one is scaled to the line here: its quantity times the position's, and a
    total that is that quantity times its rate.

    The rate is converted into the base currency by the branch the rollup
    (``_leaf_total_base_with_resources``) takes for the same line, through the
    rollup's own helpers, so the rows printed under a line are converted the
    way the line above them was:

    * When some resource names a foreign currency, the rollup converts
      resource by resource, and so does this.
    * When none does, the rollup converts the stored line total by the
      POSITION's currency. That is the shape an assembly applied without an
      FX rate leaves: ``metadata.currency`` is the assembly's, and its
      resources carry no currency of their own because they inherit the
      line's. Each rate is then scaled by that same position factor. A
      resource tagged with the base currency counts as not foreign there, so
      under a dollar line it is scaled by the dollar rate too, exactly as the
      line's total is.

    A currency with no usable rate stays in its own units, as in the rollup.
    """
    from app.modules.boq.service import (
        _position_currency,
        _position_total_in_base,
        _resource_total_in_base,
        _to_decimal,
    )

    meta = _position_meta(pos)
    resources = meta.get("resources")
    if not isinstance(resources, list):
        return []
    base = (base_currency or "").strip().upper()
    fx = dict(fx_rates or {})
    position_qty = _to_decimal(getattr(pos, "quantity", 0))
    any_foreign = any(
        isinstance(r, dict) and str(r.get("currency") or "").strip().upper() not in ("", base) for r in resources
    )
    # The factor the rollup applies to the whole line when no resource is
    # foreign: the position's currency through ``_position_total_in_base``.
    position_factor = _position_total_in_base(
        "1", _position_currency(SimpleNamespace(metadata_=meta)), fx, base_currency
    )
    lines: list[_ResourceLine] = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        rate = _to_decimal(resource.get("unit_rate"))
        if any_foreign:
            rate = _resource_total_in_base(
                [{"quantity": 1, "unit_rate": rate, "currency": resource.get("currency")}], fx, base_currency
            )
        else:
            rate *= position_factor
        quantity = _to_decimal(resource.get("quantity")) * position_qty
        lines.append(
            _ResourceLine(
                name=str(resource.get("name") or resource.get("code") or "").strip(),
                unit=str(resource.get("unit") or "").strip(),
                quantity=quantity,
                unit_rate=rate,
                total=quantity * rate,
            )
        )
    return lines


def _build_styles() -> dict[str, ParagraphStyle]:
    """Build the set of paragraph styles used throughout the PDF."""
    base = getSampleStyleSheet()

    return {
        "brand": ParagraphStyle(
            "Brand",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1a1a2e"),
            spaceAfter=6 * mm,
        ),
        "title": ParagraphStyle(
            "CoverTitle",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=18,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#16213e"),
            spaceAfter=4 * mm,
        ),
        "subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#333333"),
            spaceAfter=2 * mm,
        ),
        "info_label": ParagraphStyle(
            "InfoLabel",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=10,
            textColor=colors.HexColor("#666666"),
            alignment=TA_LEFT,
        ),
        "info_value": ParagraphStyle(
            "InfoValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=10,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_LEFT,
        ),
        "summary_label": ParagraphStyle(
            "SummaryLabel",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=11,
            textColor=colors.HexColor("#333333"),
            alignment=TA_LEFT,
        ),
        "summary_value": ParagraphStyle(
            "SummaryValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=11,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_RIGHT,
        ),
        "summary_total_label": ParagraphStyle(
            "SummaryTotalLabel",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=12,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_LEFT,
        ),
        "summary_total_value": ParagraphStyle(
            "SummaryTotalValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=12,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_RIGHT,
        ),
        "section_header": ParagraphStyle(
            "SectionHeader",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=9,
            textColor=colors.HexColor("#1a1a2e"),
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            leading=10,
        ),
        "cell_right": ParagraphStyle(
            "CellRight",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        "cell_bold_right": ParagraphStyle(
            "CellBoldRight",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        # The header row of the position table and of the section summary. A
        # TableStyle TEXTCOLOR cannot reach a cell that holds a Paragraph, so
        # the colour of a header has to live on the header's own style. It did
        # not, and the row was drawn in the colour of the text below it: on the
        # #1a1a2e header fill, "Pos.", "Description" and "Unit" came out
        # #1a1a2e, the same colour they were standing on.
        #
        # Sizes are the ones these two rows already rendered at, 9pt on the
        # left and 8pt on the right to match their columns. The table style
        # also carried a FONTSIZE of 9 for the whole row, equally unable to
        # act; honouring that as well would resize the right hand headings and
        # move the table without making anything more readable.
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=9,
            textColor=colors.white,
        ),
        "table_header_right": ParagraphStyle(
            "TableHeaderRight",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=8,
            textColor=colors.white,
            alignment=TA_RIGHT,
            leading=10,
        ),
        "subtotal_label": ParagraphStyle(
            "SubtotalLabel",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=8,
            textColor=colors.HexColor("#444444"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        "subtotal_value": ParagraphStyle(
            "SubtotalValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=7,
            textColor=colors.HexColor("#999999"),
        ),
        # A resource under its position: the cost build-up, one size down and
        # greyed so the priced line above it stays the thing a reader scans.
        "resource_cell": ParagraphStyle(
            "ResourceCell",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=7,
            textColor=colors.HexColor("#666666"),
            leading=9,
            leftIndent=3 * mm,
        ),
        "resource_cell_right": ParagraphStyle(
            "ResourceCellRight",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=7,
            textColor=colors.HexColor("#666666"),
            alignment=TA_RIGHT,
            leading=9,
        ),
        # The sign-off block at the foot of the cover. Each column is centred
        # over its signing line, so the pair sits on the page's axis like the
        # title and the summary above it.
        "sign_label": ParagraphStyle(
            "SignLabel",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=9,
            textColor=colors.HexColor("#666666"),
            alignment=TA_CENTER,
            leading=11,
        ),
        "sign_name": ParagraphStyle(
            "SignName",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=10,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_CENTER,
            leading=12,
        ),
        "sign_hint": ParagraphStyle(
            "SignHint",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=7,
            textColor=colors.HexColor("#999999"),
            alignment=TA_CENTER,
            leading=9,
        ),
    }


def _make_header_footer(
    project_name: str,
    boq_name: str,
    generated_date: str,
    *,
    page_width: float = 0,
    page_height: float = 0,
    margin_left: float = 0,
    margin_right: float = 0,
    labels: dict[str, str] | None = None,
) -> tuple[Any, Any]:
    """Return (header_func, footer_func) for table pages."""
    pw = page_width or PAGE_WIDTH
    ph = page_height or PAGE_HEIGHT
    ml = margin_left or MARGIN_LEFT
    mr = margin_right or MARGIN_RIGHT
    lb = labels or _PDF_LABELS["en"]

    def _header(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#666666"))
        text = f"{project_name}  -  {boq_name}"
        hdr_style = ParagraphStyle(
            "_boqHeader",
            fontName=BODY_FONT,
            fontSize=8,
            leading=8,
            textColor=colors.HexColor("#666666"),
        )
        p = Paragraph(html.escape(text, quote=True), pdf_style_for_text(hdr_style, text))
        _pw, _ph = p.wrapOn(canvas, pw - ml - mr, 20)
        p.drawOn(canvas, ml, ph - 15 * mm - _ph + 8 * 0.22)
        canvas.setStrokeColor(colors.HexColor("#cccccc"))
        canvas.setLineWidth(0.5)
        line_y = ph - 17 * mm
        canvas.line(ml, line_y, pw - mr, line_y)
        canvas.restoreState()
        branded_header_logo(canvas, doc)

    def _footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#999999"))
        ftr_style = ParagraphStyle(
            "_boqFooter",
            fontName=BODY_FONT,
            fontSize=7,
            leading=7,
            textColor=colors.HexColor("#999999"),
        )
        if getattr(doc, "page_count", 0) > 0:
            page_text = f"{lb.get('page', 'Page')} {doc.page} {lb.get('of', 'of')} {doc.page_count}"
        else:
            page_text = f"{lb.get('page', 'Page')} {doc.page}"
        # Fitted onto one line in the room beside the page number: the brand is
        # the firm's legal name, which is long enough to reach the number, and
        # this paragraph is anchored by its top, so a wrapped one would come
        # down over the bottom edge of the page instead.
        brand_text, _brand_face, brand_size = pdf_fit_line(
            branded_cover_brand(),
            pdf_room_beside(pw - ml - mr, page_text),
            suffix=f"  |  {lb.get('generated', 'Generated:')} {generated_date}",
            base=BODY_FONT,
        )
        p = Paragraph(html.escape(brand_text, quote=True), pdf_fitted_style(ftr_style, brand_text, brand_size))
        _pw, _ph = p.wrapOn(canvas, pw - ml - mr, 20)
        p.drawOn(canvas, ml, 10 * mm - _ph + 7 * 0.22)
        canvas.setFont(BODY_FONT, 7)
        canvas.drawRightString(pw - mr, 10 * mm, page_text)
        canvas.restoreState()

    return _header, _footer


class _NumberedDocTemplate(BaseDocTemplate):
    """DocTemplate that tracks total page count for 'Page X of Y' footers.

    Uses a two-pass approach: the first build counts pages, then we store
    the total so the footer can reference it.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.page_count = 0

    def afterFlowable(self, flowable: Any) -> None:  # noqa: N802
        """Track page count after each flowable is placed."""
        # page_count is updated after the full build via handle_documentEnd

    def afterPage(self) -> None:  # noqa: N802
        """Called after each page is completed."""
        self.page_count = max(self.page_count, self.page)


def _build_cover_page(
    boq_data: Any,
    project_name: str,
    currency: str,
    prepared_by: str,
    styles: dict[str, ParagraphStyle],
    country_code: str = "",
    labels: dict[str, str] | None = None,
    usable_width: float = 0,
    letterhead: Any | None = None,
) -> list[Any]:
    """Build the list of flowables for the cover page.

    With a letterhead, the letterhead heads the cover in place of the top
    spacing and the large brand name: it already names the firm, and the
    name printed again right under it reads as a mistake.
    """
    lb = labels or _PDF_LABELS["en"]
    uw = usable_width or USABLE_WIDTH
    elements: list[Any] = []

    if letterhead is not None:
        elements.append(letterhead)
    else:
        # Top spacing
        elements.append(Spacer(1, 30 * mm))

        # Brand (workspace white-label name, falls back to the default; issue #284)
        elements.append(_safe_para(branded_cover_brand(), styles["brand"]))
    elements.append(Spacer(1, 10 * mm))

    # Decorative line
    line_table = Table(
        [[""]],
        colWidths=[120 * mm],
        rowHeights=[0.8 * mm],
    )
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1a1a2e")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    line_wrapper = Table([[line_table]], colWidths=[uw])
    line_wrapper.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    elements.append(line_wrapper)
    elements.append(Spacer(1, 4 * mm))

    # Title
    elements.append(Paragraph(lb["cost_estimate"], styles["title"]))

    elements.append(Spacer(1, 2 * mm))
    elements.append(line_wrapper)
    elements.append(Spacer(1, 8 * mm))

    # Project info
    # How big the bill is, as two plain numbers: "3 / 42" needs no plural
    # form in any language, where "3 sections" would need three in Russian.
    contents = f"{len(boq_data.sections)} / {count_boq_positions(boq_data)}"
    info_rows = [
        (lb["project"], project_name),
        (lb["boq"], boq_data.name),
        (lb["date"], format_date(datetime.now(tz=UTC), country_code)),
        (lb["status"], _status_label(boq_data.status, lb)),
        (lb["contents"], contents),
    ]

    info_table_data = []
    for label, value in info_rows:
        info_table_data.append(
            [
                # Labels are first-party constants, values come from the
                # project / BOQ records and may contain HTML - escape only
                # the dynamic side.
                Paragraph(label, styles["info_label"]),
                _safe_para(value, styles["info_value"]),
            ]
        )

    # The label column fits "Abschnitte / Positionen:" on one line; a label
    # that wraps makes its row two lines tall, and the cover has no height to
    # spare once the sign-off block is under the summary.
    info_table = Table(
        info_table_data,
        colWidths=[48 * mm, 82 * mm],
        hAlign="CENTER",
    )
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
            ]
        )
    )
    elements.append(info_table)
    elements.append(Spacer(1, 8 * mm))

    # Separator
    sep_table = Table([[""]], colWidths=[130 * mm], rowHeights=[0.3 * mm])
    sep_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#cccccc")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    sep_wrapper = Table([[sep_table]], colWidths=[uw])
    sep_wrapper.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    elements.append(sep_wrapper)
    elements.append(Spacer(1, 6 * mm))

    # Summary heading, centred by its style like the title above it. It used to
    # be pushed right with a run of non-breaking spaces, which put it off the
    # axis of the centred summary table under it.
    elements.append(Paragraph(lb["summary"], styles["title"]))
    elements.append(Spacer(1, 4 * mm))

    # Cost summary. The tax is already inside ``net_total``, so the pre-tax
    # subtotal is that figure minus the tax and the total of everything is that
    # figure itself. See :func:`_tax_split`.
    direct_cost = boq_data.direct_cost
    tax_lines, tax_amount, subtotal_ex_tax, gross_total = _tax_split(boq_data)
    markup_total = subtotal_ex_tax - Decimal(str(direct_cost))

    def _fc(value: Any) -> str:
        return _fmt_currency(value, currency, country=country_code)

    summary_rows: list[tuple[str, str, bool]] = [
        (lb["direct_cost"], _fc(direct_cost), False),
        (lb["markups"], _fc(markup_total), False),
        (lb["net_total"], _fc(subtotal_ex_tax), False),
    ]
    # One row per tax line, named and rated as the bill carries it. A stack with
    # no tax at all still prints a zero row, so the summary keeps its shape and
    # an untaxed bill is visibly untaxed rather than silently missing a row.
    tax_rows = [(f"{_tax_label(m, currency, country_code)}:", Decimal(str(m.amount))) for m in tax_lines]
    if not tax_rows:
        tax_rows = [(_zero_tax_fallback_label(country_code, lb), Decimal("0"))]
    summary_rows.extend((label, _fc(amount), False) for label, amount in tax_rows)
    summary_rows.append((f"{lb['gross_total']}:", _fc(gross_total), True))

    summary_table_data = []
    for label, value, is_total in summary_rows:
        lbl_style = styles["summary_total_label"] if is_total else styles["summary_label"]
        val_style = styles["summary_total_value"] if is_total else styles["summary_value"]
        summary_table_data.append(
            [
                Paragraph(label, lbl_style),
                Paragraph(value, val_style),
            ]
        )

    summary_table = Table(
        summary_table_data,
        colWidths=[50 * mm, 80 * mm],
        hAlign="CENTER",
    )

    # Style the summary table with a line above the Gross Total
    summary_style_commands: list[Any] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]
    # Add top border on the Gross Total row (last row)
    last_row = len(summary_rows) - 1
    summary_style_commands.append(("LINEABOVE", (0, last_row), (-1, last_row), 1, colors.HexColor("#1a1a2e")))
    summary_table.setStyle(TableStyle(summary_style_commands))
    elements.append(summary_table)

    elements.append(Spacer(1, 6 * mm))
    elements.append(_sign_off_block(prepared_by, styles, lb, uw))

    return elements


def _sign_off_block(prepared_by: str, styles: dict[str, ParagraphStyle], lb: dict[str, str], width: float) -> Any:
    """Who prepared the estimate and who approved it, each with a line to sign on.

    A cost estimate that leaves the office is signed off, and the person who
    prints it needs somewhere to do that. The preparer is named when the
    project's owner is known; the approver's name is left for the hand that
    signs.

    ``prepared_by`` is user-supplied and goes through :func:`_safe_para`, which
    escapes it (a payload like ``<font color="white">x</font>`` would otherwise
    render as styled text, BUG-PDF01) and picks the Chinese face when the name
    needs it.
    """
    column = min((width - 16 * mm) / 2, 65 * mm)
    rule = colors.HexColor("#999999")
    table = Table(
        [
            [
                Paragraph(lb["prepared_by"], styles["sign_label"]),
                "",
                Paragraph(lb["approved_by"], styles["sign_label"]),
            ],
            [_safe_para(prepared_by, styles["sign_name"]), "", ""],
            ["", "", ""],
            [
                Paragraph(lb["signature_hint"], styles["sign_hint"]),
                "",
                Paragraph(lb["signature_hint"], styles["sign_hint"]),
            ],
        ],
        colWidths=[column, 16 * mm, column],
        rowHeights=[None, None, 8 * mm, None],
        hAlign="CENTER",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
                # The two lines to sign on, one under each column.
                ("LINEBELOW", (0, 2), (0, 2), 0.5, rule),
                ("LINEBELOW", (2, 2), (2, 2), 0.5, rule),
            ]
        )
    )
    return table


def _build_boq_table(
    boq_data: Any,
    currency: str,
    styles: dict[str, ParagraphStyle],
    measurement_system: str = "metric",
    country_code: str = "",
    labels: dict[str, str] | None = None,
    col_widths: list[float] | None = None,
    *,
    base_currency: str = "",
    fx_rates: Mapping[str, str] | None = None,
    include_resources: bool = False,
    page_marks: dict[str, int] | None = None,
) -> list[Any]:
    """Build the BOQ table flowables (sections, positions, totals).

    Improvements:
    - Locale-aware currency formatting for all monetary values
    - Conditional page break before each major section (60mm threshold)
    - Grand total block wrapped in KeepTogether

    ``measurement_system`` controls the physical quantity column: when
    ``"imperial"`` each ``pos.quantity`` is scaled and its unit relabelled
    (m -> ft, m² -> ft² ...). The paired per-unit RATE is then restated
    reciprocally against the same displayed unit (50 / m -> 15.24 / ft) so a
    converted line still reconciles (qty_shown * rate_shown == line total).
    Line / project totals (total / subtotals / markups / VAT) are NEVER
    converted or recomputed - they are invariant amounts in the project
    currency, not measurements.

    ``base_currency`` and ``fx_rates`` are the project's, as the structured
    payload's subtotals were rolled up with them: each line's total and rate
    are read in the base currency through :func:`_line_money`, so the lines
    of a section add up to its subtotal on a mixed-currency bill too.

    ``include_resources`` prints each position's resources under it, scaled
    to the line (see :func:`_resource_lines`). Off by default: the build-up is
    the estimator's own cost, not every recipient's business.

    ``page_marks``, when given, receives the page each section's header row
    is drawn on (see :class:`_PageMark`), for the table of contents.
    """
    lb = labels or _PDF_LABELS["en"]
    table_widths = col_widths or TABLE_COL_WIDTHS
    elements: list[Any] = []

    def _mark(key: str) -> Any:
        """An empty cell of a section's header row, holding its page mark when asked for."""
        return _PageMark(key, page_marks) if page_marks is not None else ""

    # Locale-aware formatting shortcuts
    def _fv(value: Any, decimals: int = 2) -> str:
        return _fmt(value, decimals, currency, country_code)

    def _fc(value: Any) -> str:
        return _fmt_currency(value, currency, country=country_code)

    def _qty_cell(quantity: Any, unit: str) -> tuple[str, str]:
        """Return (quantity_text, unit_label) for a row.

        Honours ``measurement_system``: the quantity is converted and the unit
        relabelled for imperial; metric tidies the label only. The numeric
        value is formatted with the same locale-aware helper as before so
        thousands / decimal separators stay consistent.
        """
        result = convert_units(quantity, unit, measurement_system)
        return _fv(result.value), result.display_unit

    def _rate_cell(rate: Any, unit: str) -> str:
        """Return the per-unit rate text for a row.

        The rate is money per ONE metric unit. When ``_qty_cell`` shows the
        quantity converted (m -> ft ...) the rate is restated reciprocally
        against the SAME displayed unit (50 / m -> 15.24 / ft) via
        :func:`display_rate`, so ``qty_shown * rate_shown`` reconciles to the
        invariant line total. Metric and unmapped units return the rate
        unchanged. The line total is never recomputed from this - only the
        printed per-unit basis is restated.
        """
        return _fv(display_rate(rate, unit, measurement_system))

    def _position_rows(pos: Any) -> tuple[list[list[Any]], Decimal]:
        """The position's row, its resource rows when asked for, and its total."""
        total, rate = _line_money(pos, base_currency, fx_rates)
        qty_text, unit_label = _qty_cell(pos.quantity, pos.unit)
        rows: list[list[Any]] = [
            [
                _safe_para(pos.ordinal, styles["cell"]),
                _safe_para(pos.description, styles["cell"]),
                _safe_para(unit_label, styles["cell"]),
                Paragraph(qty_text, styles["cell_right"]),
                Paragraph(_rate_cell(rate, pos.unit), styles["cell_right"]),
                Paragraph(_fv(total), styles["cell_right"]),
            ]
        ]
        if include_resources:
            for resource in _resource_lines(pos, base_currency, fx_rates):
                r_qty, r_unit = _qty_cell(resource.quantity, resource.unit)
                rows.append(
                    [
                        "",
                        _safe_para(resource.name, styles["resource_cell"]),
                        _safe_para(r_unit, styles["resource_cell"]),
                        Paragraph(r_qty, styles["resource_cell_right"]),
                        Paragraph(_rate_cell(resource.unit_rate, resource.unit), styles["resource_cell_right"]),
                        Paragraph(_fv(resource.total), styles["resource_cell_right"]),
                    ]
                )
        return rows, total

    # Table header row (locale-aware)
    header_row = [
        Paragraph(f"<b>{lb['pos']}</b>", styles["table_header"]),
        Paragraph(f"<b>{lb['description']}</b>", styles["table_header"]),
        Paragraph(f"<b>{lb['unit']}</b>", styles["table_header"]),
        Paragraph(f"<b>{lb['qty']}</b>", styles["table_header_right"]),
        Paragraph(f"<b>{lb['rate']} ({currency})</b>", styles["table_header_right"]),
        Paragraph(f"<b>{lb['total']} ({currency})</b>", styles["table_header_right"]),
    ]

    table_data: list[list[Any]] = [header_row]
    row_styles: list[tuple[int, str]] = []  # (row_index, type) for custom styling

    row_idx = 1  # 0 = header

    # Sections with positions
    for section_index, section in enumerate(boq_data.sections):
        # Section header row
        table_data.append(
            [
                _safe_para(section.ordinal, styles["section_header"]),
                _safe_para(section.description, styles["section_header"]),
                _mark(_toc_section_key(section_index)),
                "",
                "",
                "",
            ]
        )
        row_styles.append((row_idx, "section"))
        row_idx += 1

        # Position rows within section
        for pos in section.positions:
            rows, _total = _position_rows(pos)
            for kind, row in zip(["item"] + ["resource"] * (len(rows) - 1), rows, strict=True):
                table_data.append(row)
                row_styles.append((row_idx, kind))
                row_idx += 1

        # Section subtotal
        table_data.append(
            [
                "",
                "",
                Paragraph(lb["subtotal"], styles["subtotal_label"]),
                "",
                "",
                Paragraph(_fv(section.subtotal), styles["subtotal_value"]),
            ]
        )
        row_styles.append((row_idx, "subtotal"))
        row_idx += 1

    # Ungrouped positions
    if boq_data.positions:
        table_data.append(
            [
                Paragraph("", styles["section_header"]),
                Paragraph(lb["other_positions"], styles["section_header"]),
                _mark(_TOC_UNGROUPED),
                "",
                "",
                "",
            ]
        )
        row_styles.append((row_idx, "section"))
        row_idx += 1

        # Summed in the base currency, line by line, as the direct cost is.
        ungrouped_total = Decimal("0")
        for pos in boq_data.positions:
            rows, total = _position_rows(pos)
            for kind, row in zip(["item"] + ["resource"] * (len(rows) - 1), rows, strict=True):
                table_data.append(row)
                row_styles.append((row_idx, kind))
                row_idx += 1
            ungrouped_total += total

        table_data.append(
            [
                "",
                "",
                Paragraph(lb["subtotal"], styles["subtotal_label"]),
                "",
                "",
                Paragraph(_fv(ungrouped_total), styles["subtotal_value"]),
            ]
        )
        row_styles.append((row_idx, "subtotal"))
        row_idx += 1

    # Blank spacer row
    table_data.append(["", "", "", "", "", ""])
    row_styles.append((row_idx, "spacer"))
    row_idx += 1

    # Direct cost
    table_data.append(
        [
            "",
            "",
            Paragraph(f"<b>{lb['direct_cost']}</b>", styles["cell_bold_right"]),
            "",
            "",
            Paragraph(f"<b>{_fc(boq_data.direct_cost)}</b>", styles["cell_bold_right"]),
        ]
    )
    row_styles.append((row_idx, "total_line"))
    row_idx += 1

    # Markup lines. Tax is not one of them here: it is printed below the pre-tax
    # subtotal, which is where the reader of a bill looks for it, and printing it
    # in both places counted its money twice.
    for markup in boq_data.markups:
        if not markup.is_active or markup.category == "tax":
            continue
        label = markup.name
        if markup.markup_type == "percentage":
            label = f"{markup.name} ({_fmt_rate(markup.percentage, 1, currency, country_code)}%)"
        table_data.append(
            [
                "",
                "",
                _safe_para(label, styles["cell_right"]),
                "",
                "",
                Paragraph(_fc(markup.amount), styles["cell_right"]),
            ]
        )
        row_styles.append((row_idx, "markup"))
        row_idx += 1

    # Net total, before tax, then the tax lines, then the total of everything.
    # See :func:`_tax_split` for why the tax is subtracted and not added.
    tax_lines, tax_amount, subtotal_ex_tax, gross_total = _tax_split(boq_data)
    table_data.append(
        [
            "",
            "",
            Paragraph(f"<b>{lb['net_total']}</b>", styles["cell_bold_right"]),
            "",
            "",
            Paragraph(f"<b>{_fc(subtotal_ex_tax)}</b>", styles["cell_bold_right"]),
        ]
    )
    row_styles.append((row_idx, "grand_total"))
    row_idx += 1

    tax_rows = [(f"{_tax_label(m, currency, country_code)}:", Decimal(str(m.amount))) for m in tax_lines]
    if not tax_rows:
        tax_rows = [(_zero_tax_fallback_label(country_code, lb), Decimal("0"))]
    for tax_label, tax_line_amount in tax_rows:
        table_data.append(
            [
                "",
                "",
                Paragraph(tax_label, styles["cell_right"]),
                "",
                "",
                Paragraph(_fc(tax_line_amount), styles["cell_right"]),
            ]
        )
        row_styles.append((row_idx, "vat"))
        row_idx += 1

    table_data.append(
        [
            "",
            "",
            Paragraph(f"<b>{lb['gross_total']} ({currency}):</b>", styles["cell_bold_right"]),
            "",
            "",
            Paragraph(f"<b>{_fc(gross_total)}</b>", styles["cell_bold_right"]),
        ]
    )
    row_styles.append((row_idx, "grand_total"))
    row_idx += 1

    # Build the table
    table = Table(table_data, colWidths=table_widths, repeatRows=1)

    # Base table style
    style_commands: list[Any] = [
        # Header row. The fill only: every cell in this table is a Paragraph
        # and carries its own face, size and colour, so a TEXTCOLOR, FONTNAME
        # or FONTSIZE command here would read as authoritative and change
        # nothing on the page.
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        # Global
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        # Grid lines
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a1a2e")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
    ]

    # Per-row styling
    for ri, row_type in row_styles:
        if row_type == "section":
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#e8e8ee")))
            style_commands.append(("LINEBELOW", (0, ri), (-1, ri), 0.5, colors.HexColor("#cccccc")))
        elif row_type == "subtotal":
            style_commands.append(("LINEABOVE", (0, ri), (-1, ri), 0.5, colors.HexColor("#cccccc")))
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#f0f0f5")))
        elif row_type == "total_line":
            style_commands.append(("LINEABOVE", (0, ri), (-1, ri), 1, colors.HexColor("#1a1a2e")))
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.white))
        elif row_type == "grand_total":
            style_commands.append(("LINEABOVE", (0, ri), (-1, ri), 1.5, colors.HexColor("#1a1a2e")))
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#e8e8ee")))
        elif row_type == "spacer":
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.white))
        elif row_type == "resource":
            # Tight and on white, so a build-up reads as part of the line above.
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.white))
            style_commands.append(("TOPPADDING", (0, ri), (-1, ri), 0.5 * mm))
            style_commands.append(("BOTTOMPADDING", (0, ri), (-1, ri), 0.5 * mm))

    table.setStyle(TableStyle(style_commands))
    elements.append(table)

    return elements


class _PageMark(Flowable):
    """A flowable of no size that writes down the page it is drawn on.

    The bill is one long table that reportlab splits across pages, so the page
    a section starts on is known only once that table has been laid out. A
    mark in an empty cell of the section's header row is drawn with the row,
    on whichever page the row lands, and records that page's number in
    ``sink`` under ``key``. The first build fills the sink; the second prints
    the table of contents from it. The number is the canvas page, the same
    one the footer prints as ``doc.page``.
    """

    def __init__(self, key: str, sink: dict[str, int]) -> None:
        super().__init__()
        self._key = key
        self._sink = sink
        self.width = 0
        self.height = 0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        return 0, 0

    def draw(self) -> None:
        self._sink.setdefault(self._key, self.canv.getPageNumber())


#: Keys under which the page marks record where each part of the bill starts.
_TOC_UNGROUPED = "__ungrouped__"
_TOC_SUMMARY = "__summary__"


def _toc_section_key(index: int) -> str:
    """The page mark key of the section at ``index`` in ``boq_data.sections``."""
    return f"section:{index}"


def _toc_entries(boq_data: Any, lb: dict[str, str]) -> list[tuple[str, str, str]]:
    """``(ordinal, title, page mark key)`` for each line of the table of contents.

    Every section in bill order, then the positions outside any section when
    there are some, then the cost summary page.
    """
    entries = [
        (str(section.ordinal or ""), str(section.description or ""), _toc_section_key(index))
        for index, section in enumerate(boq_data.sections)
    ]
    if boq_data.positions:
        entries.append(("", lb["other_positions"], _TOC_UNGROUPED))
    entries.append(("", lb["cost_summary"], _TOC_SUMMARY))
    return entries


def _table_of_contents(
    boq_data: Any,
    styles: dict[str, ParagraphStyle],
    lb: dict[str, str],
    width: float,
    page_refs: Mapping[str, int] | None,
) -> list[Any]:
    """The table of contents page: each section and the page it starts on.

    ``page_refs`` is what the page marks recorded in the first build. That
    build lays this page out too, with every number still unknown, so the
    page takes the same room in both builds and no number it prints is
    pushed onto a later page by the numbers themselves. The page column is
    fixed and wide enough for any page count a PDF of this size reaches.
    """
    refs = page_refs or {}
    page_heading = lb["page"]
    rows: list[list[Any]] = [
        [
            Paragraph(f"<b>{lb['section']}</b>", styles["table_header"]),
            Paragraph(f"<b>{lb['description']}</b>", styles["table_header"]),
            Paragraph(f"<b>{page_heading}</b>", styles["table_header_right"]),
        ]
    ]
    for ordinal, title, key in _toc_entries(boq_data, lb):
        page = refs.get(key)
        rows.append(
            [
                _safe_para(ordinal, styles["cell"]),
                _safe_para(title, styles["cell"]),
                Paragraph(str(page) if page else "-", styles["cell_right"]),
            ]
        )
    table = Table(rows, colWidths=[35 * mm, width - 35 * mm - 20 * mm, 20 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a1a2e")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
            ]
        )
    )
    return [
        Paragraph(f"<b>{lb['table_of_contents']}</b>", styles["section_header"]),
        Spacer(1, 4 * mm),
        table,
    ]


def _section_summary_table(
    boq_data: Any,
    currency: str,
    styles: dict[str, ParagraphStyle],
    lb: dict[str, str],
    width: float,
    *,
    country_code: str = "",
    base_currency: str = "",
    fx_rates: Mapping[str, str] | None = None,
) -> Any:
    """Each section with its number of positions and its subtotal, one row each.

    The positions outside any section get a row of their own, summed line by
    line in the base currency the section subtotals are already in (see
    :func:`_line_money`), so the rows add up to the direct cost.
    """
    # ``subtotal`` carries the colon the section rows print it with.
    subtotal_heading = lb["subtotal"].rstrip(" :")
    header_row = [
        Paragraph(f"<b>{lb['section']}</b>", styles["table_header"]),
        Paragraph(f"<b>{lb['description']}</b>", styles["table_header"]),
        Paragraph(f"<b>{lb['items']}</b>", styles["table_header_right"]),
        Paragraph(f"<b>{subtotal_heading}</b>", styles["table_header_right"]),
    ]
    col_widths = [35 * mm, width - 35 * mm - 25 * mm - 35 * mm, 25 * mm, 35 * mm]

    def _fc(value: Any) -> str:
        return _fmt_currency(value, currency, country=country_code)

    table_data: list[list[Any]] = [header_row]

    for section in boq_data.sections:
        table_data.append(
            [
                _safe_para(section.ordinal, styles["cell"]),
                _safe_para(section.description, styles["cell"]),
                Paragraph(str(len(section.positions)), styles["cell_right"]),
                Paragraph(_fc(section.subtotal), styles["cell_right"]),
            ]
        )

    if boq_data.positions:
        ungrouped_total = sum(
            (_line_money(p, base_currency, fx_rates)[0] for p in boq_data.positions),
            Decimal("0"),
        )
        table_data.append(
            [
                Paragraph("", styles["cell"]),
                Paragraph(lb["other_positions"], styles["cell"]),
                Paragraph(str(len(boq_data.positions)), styles["cell_right"]),
                Paragraph(_fc(ungrouped_total), styles["cell_right"]),
            ]
        )

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                # The fill only, for the same reason as the position table.
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a1a2e")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
            ]
        )
    )
    return table


def _cost_totals_table(
    boq_data: Any,
    currency: str,
    styles: dict[str, ParagraphStyle],
    lb: dict[str, str],
    width: float,
    *,
    country_code: str = "",
) -> Any:
    """Direct cost, each markup, the pre-tax total, each tax line and the gross total."""

    def _fc(value: Any) -> str:
        return _fmt_currency(value, currency, country=country_code)

    cost_rows: list[list[Any]] = []
    cost_rows.append(
        [
            Paragraph(f"<b>{lb['direct_cost']}</b>", styles["cell_bold_right"]),
            Paragraph(f"<b>{_fc(boq_data.direct_cost)}</b>", styles["cell_bold_right"]),
        ]
    )

    # Tax is excluded here and printed under the pre-tax subtotal instead, so
    # its money is stated once. See :func:`_tax_split`.
    for markup in boq_data.markups:
        if not markup.is_active or markup.category == "tax":
            continue
        label = markup.name
        if markup.markup_type == "percentage":
            label = f"{markup.name} ({_fmt_rate(markup.percentage, 1, currency, country_code)}%)"
        cost_rows.append(
            [
                _safe_para(label, styles["cell_right"]),
                Paragraph(_fc(markup.amount), styles["cell_right"]),
            ]
        )

    tax_lines, _tax_amount, subtotal_ex_tax, gross_total = _tax_split(boq_data)
    cost_rows.append(
        [
            Paragraph(f"<b>{lb['net_total']}</b>", styles["cell_bold_right"]),
            Paragraph(f"<b>{_fc(subtotal_ex_tax)}</b>", styles["cell_bold_right"]),
        ]
    )

    tax_rows = [(f"{_tax_label(m, currency, country_code)}:", Decimal(str(m.amount))) for m in tax_lines]
    if not tax_rows:
        tax_rows = [(_zero_tax_fallback_label(country_code, lb), Decimal("0"))]
    for tax_label, tax_line_amount in tax_rows:
        cost_rows.append(
            [
                Paragraph(tax_label, styles["cell_right"]),
                Paragraph(_fc(tax_line_amount), styles["cell_right"]),
            ]
        )
    cost_rows.append(
        [
            Paragraph(f"<b>{lb['gross_total']} ({currency}):</b>", styles["cell_bold_right"]),
            Paragraph(f"<b>{_fc(gross_total)}</b>", styles["cell_bold_right"]),
        ]
    )

    cost_table = Table(cost_rows, colWidths=[width * 0.6, width * 0.4])
    cost_style: list[Any] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]
    # Gross total row styling
    last_row = len(cost_rows) - 1
    cost_style.append(("LINEABOVE", (0, last_row), (-1, last_row), 1.5, colors.HexColor("#1a1a2e")))
    cost_style.append(("BACKGROUND", (0, last_row), (-1, last_row), colors.HexColor("#e8e8ee")))
    cost_table.setStyle(TableStyle(cost_style))
    return cost_table


def generate_boq_pdf(
    boq_data: Any,
    project_name: str,
    currency: str = "",
    prepared_by: str = "",
    measurement_system: str = "metric",
    country_code: str = "",
    locale: str = "en",
    page_format: str = "A4",
    *,
    base_currency: str = "",
    fx_rates: Mapping[str, str] | None = None,
    include_resources: bool = False,
) -> bytes:
    """Generate a professional PDF cost estimate report.

    Args:
        boq_data: BOQWithSections schema instance with sections, positions,
                  markups, direct_cost, net_total, grand_total.
        project_name: Name of the parent project (for the cover page).
        currency: Currency code (e.g. "EUR", "GBP", "USD").
        prepared_by: Full name of the person who prepared the estimate.
        measurement_system: ``"metric"`` (default) renders quantities
            canonical; ``"imperial"`` converts the physical quantity column +
            its unit label (m -> ft, m² -> ft² ...) and restates the paired
            per-unit rate reciprocally so each converted line still reconciles.
            Line / project totals are never converted or recomputed.
        locale: Project locale for translating PDF labels (e.g. "de", "fr",
            "ru", "es"). Falls back to English for unknown locales.
        page_format: ``"A4"`` (default, 210x297mm) or ``"LETTER"``
            (8.5x11in, US/CA standard).
        base_currency: The project's base currency the payload's subtotals
            were rolled up in (``BOQService.get_export_fx``).
        fx_rates: The project's FX table, ``{code: rate}``, used to print each
            line in that base currency so the lines add up to the subtotals.
        include_resources: Print each position's resources under it.

    Returns:
        PDF file contents as bytes.
    """
    buffer = io.BytesIO()
    styles = _build_styles()

    # Page size selection (US/CA use Letter, rest of world A4)
    if page_format.upper() == "LETTER":
        page_size = LETTER
    else:
        page_size = A4
    labels = _get_pdf_labels(locale)
    generated_date = format_date(datetime.now(tz=UTC), country_code)

    # Page dimensions computed from chosen paper size
    pw, ph = page_size
    ml, mr, mt, mb = MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM
    uw = pw - ml - mr

    # Recalculate column widths proportionally for the chosen page size
    col_pos = 35 * mm
    col_unit = 20 * mm
    col_qty = 25 * mm
    col_rate = 30 * mm
    col_total = 30 * mm
    col_desc = uw - col_pos - col_unit - col_qty - col_rate - col_total
    table_col_widths = [col_pos, col_desc, col_unit, col_qty, col_rate, col_total]

    header_func, footer_func = _make_header_footer(
        project_name,
        boq_data.name,
        generated_date,
        page_width=pw,
        page_height=ph,
        margin_left=ml,
        margin_right=mr,
        labels=labels,
    )

    # -- Page templates --
    cover_frame = Frame(ml, mb, uw, ph - mt - mb, id="cover")
    table_frame = Frame(ml, mb + 5 * mm, uw, ph - mt - mb - 12 * mm, id="table")

    def _table_page_handler(canvas: Any, doc: Any) -> None:
        header_func(canvas, doc)
        footer_func(canvas, doc)

    cover_template = PageTemplate(id="cover", frames=[cover_frame])
    table_template = PageTemplate(id="table", frames=[table_frame], onPage=_table_page_handler)

    doc_meta = branded_doc_metadata()
    doc_kwargs: dict[str, Any] = {
        "pagesize": page_size,
        "leftMargin": ml,
        "rightMargin": mr,
        "topMargin": mt,
        "bottomMargin": mb,
        "title": f"{labels['cost_estimate']} - {boq_data.name}",
        "author": doc_meta["author"],
        "subject": labels["subject"],
        "creator": doc_meta["creator"],
        "producer": doc_meta["producer"],
        "keywords": doc_meta["keywords"],
    }

    doc = _NumberedDocTemplate(buffer, **doc_kwargs)
    doc.addPageTemplates([cover_template, table_template])

    # The firm's letterhead heads the cover when the company profile has one.
    # Each pass gets its own copy, since a flowable is laid out by the build
    # that draws it. The cover frame pads 6pt on each side.
    with_letterhead = branded_letterhead(uw - 12) is not None

    def _letterhead() -> Any | None:
        return branded_letterhead(uw - 12) if with_letterhead else None

    # A bill of more than one section opens with a table of contents, as the
    # editor's browser PDF did. Its page numbers come from the first build:
    # the page marks in the bill record where each section starts, and the
    # second build prints them.
    with_toc = len(boq_data.sections) > 1

    def _flowables(page_refs: Mapping[str, int] | None, page_marks: dict[str, int] | None) -> list[Any]:
        """Everything the document holds, in order, for one build."""
        flowables: list[Any] = []
        flowables.extend(
            _build_cover_page(
                boq_data,
                project_name,
                currency,
                prepared_by,
                styles,
                country_code,
                labels=labels,
                usable_width=uw,
                letterhead=_letterhead(),
            )
        )
        flowables.append(NextPageTemplate("table"))
        flowables.append(PageBreak())
        if with_toc:
            flowables.extend(_table_of_contents(boq_data, styles, labels, uw, page_refs))
            flowables.append(PageBreak())
        flowables.extend(
            _build_boq_table(
                boq_data,
                currency,
                styles,
                measurement_system,
                country_code,
                labels=labels,
                col_widths=table_col_widths,
                base_currency=base_currency,
                fx_rates=fx_rates,
                include_resources=include_resources,
                page_marks=page_marks,
            )
        )
        # The cost summary page: each section's subtotal on one page, then the
        # totals, so a reviewer reads the bill's shape without paging through
        # every subtotal row of the table.
        flowables.append(PageBreak())
        if page_marks is not None:
            flowables.append(_PageMark(_TOC_SUMMARY, page_marks))
        flowables.append(Paragraph(f"<b>{labels['cost_summary']}</b>", styles["section_header"]))
        flowables.append(Spacer(1, 4 * mm))
        flowables.append(
            _section_summary_table(
                boq_data,
                currency,
                styles,
                labels,
                uw,
                country_code=country_code,
                base_currency=base_currency,
                fx_rates=fx_rates,
            )
        )
        flowables.append(Spacer(1, 6 * mm))
        flowables.append(_cost_totals_table(boq_data, currency, styles, labels, uw, country_code=country_code))
        return flowables

    # Two-pass build: the first counts the pages and records where each part of
    # the bill starts, the second renders with both.
    page_marks: dict[str, int] = {}
    doc.build(_flowables(None, page_marks if with_toc else None))
    total_pages = doc.page_count

    # Second pass with correct page count
    buffer.seek(0)
    buffer.truncate()

    doc2 = _NumberedDocTemplate(buffer, **doc_kwargs)
    doc2.page_count = total_pages
    doc2.addPageTemplates([cover_template, table_template])
    doc2.build(_flowables(page_marks, None))

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def count_boq_positions(boq_data: Any) -> int:
    """Count the total number of line-item positions in a BOQWithSections.

    Counts positions inside sections plus ungrouped positions.
    Section headers themselves are not counted.

    Args:
        boq_data: BOQWithSections schema instance.

    Returns:
        Total number of line-item positions.
    """
    total = 0
    for section in boq_data.sections:
        total += len(section.positions)
    total += len(boq_data.positions)
    return total


# ── Large BOQ threshold ──────────────────────────────────────────────────────

LARGE_BOQ_THRESHOLD = 500


def generate_boq_pdf_simple(
    boq_data: Any,
    project_name: str,
    currency: str = "",
    prepared_by: str = "",
    measurement_system: str = "metric",
    country_code: str = "",
    locale: str = "en",
    page_format: str = "A4",
    *,
    base_currency: str = "",
    fx_rates: Mapping[str, str] | None = None,
) -> bytes:
    """Generate a simplified PDF for large BOQs (> 500 positions).

    ``base_currency`` and ``fx_rates`` are the project's, as for
    :func:`generate_boq_pdf`: the ungrouped positions are summed in the base
    currency the section subtotals are already in.

    Uses a single-pass build (no two-pass page counting) and a compact
    table layout to reduce memory usage and generation time on Windows.

    The simplified report includes:
    - Cover page with summary
    - Section-level summary table (no individual positions)
    - Cost summary with markups

    Args:
        boq_data: BOQWithSections schema instance.
        project_name: Name of the parent project.
        currency: Currency code (e.g. "EUR").
        prepared_by: Full name of the person who prepared the estimate.
        measurement_system: Accepted for signature parity with
            :func:`generate_boq_pdf` so the router can call either uniformly.
            The summary report carries no physical-quantity column (only item
            counts and money subtotals), so there is nothing to convert and
            the value is otherwise unused.

    Returns:
        PDF file contents as bytes.
    """
    lb = _get_pdf_labels(locale)
    # The paper the router chose (Letter for the United States and Canada) is
    # the page, its frames and its table widths alike. This used to pick the
    # size and then lay every frame out for A4 regardless, so a Letter summary
    # came out on A4 paper.
    ps = LETTER if page_format.upper() == "LETTER" else A4
    pw, ph = ps
    uw = pw - MARGIN_LEFT - MARGIN_RIGHT
    buffer = io.BytesIO()
    styles = _build_styles()
    generated_date = format_date(datetime.now(tz=UTC), country_code)

    header_func, footer_func = _make_header_footer(
        project_name,
        boq_data.name,
        generated_date,
        page_width=pw,
        page_height=ph,
        margin_left=MARGIN_LEFT,
        margin_right=MARGIN_RIGHT,
        labels=lb,
    )

    cover_frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM,
        uw,
        ph - MARGIN_TOP - MARGIN_BOTTOM,
        id="cover",
    )
    table_frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM + 5 * mm,
        uw,
        ph - MARGIN_TOP - MARGIN_BOTTOM - 12 * mm,
        id="table",
    )

    def _table_page_handler(canvas: Any, doc: Any) -> None:
        header_func(canvas, doc)
        footer_func(canvas, doc)

    cover_template = PageTemplate(id="cover", frames=[cover_frame])
    table_template = PageTemplate(
        id="table",
        frames=[table_frame],
        onPage=_table_page_handler,
    )

    doc = _NumberedDocTemplate(
        buffer,
        pagesize=ps,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"{lb['cost_estimate']} - {boq_data.name} ({lb['summary_report']})",
        author=branded_doc_metadata()["author"],
        subject=lb["subject"],
        creator=branded_doc_metadata()["creator"],
        producer=branded_doc_metadata()["producer"],
        keywords=branded_doc_metadata()["keywords"],
    )
    doc.addPageTemplates([cover_template, table_template])

    flowables: list[Any] = []

    # Cover page, headed by the firm's letterhead when the company profile has
    # one. The cover frame pads 6pt on each side.
    flowables.extend(
        _build_cover_page(
            boq_data,
            project_name,
            currency,
            prepared_by,
            styles,
            country_code,
            labels=lb,
            usable_width=uw,
            letterhead=branded_letterhead(uw - 12),
        )
    )

    # Switch to table template
    flowables.append(NextPageTemplate("table"))
    flowables.append(PageBreak())

    # Section-level summary table instead of full position listing
    total_positions = count_boq_positions(boq_data)
    omitted = lb["positions_omitted"].format(count=total_positions)
    flowables.append(
        Paragraph(
            f"<b>{lb['summary_report']}</b> &mdash; {html.escape(omitted)}",
            styles["section_header"],
        )
    )
    flowables.append(Spacer(1, 4 * mm))

    flowables.append(
        _section_summary_table(
            boq_data,
            currency,
            styles,
            lb,
            uw,
            country_code=country_code,
            base_currency=base_currency,
            fx_rates=fx_rates,
        )
    )
    flowables.append(Spacer(1, 6 * mm))

    # Direct cost, markups, net total, VAT, gross total
    flowables.append(Paragraph(f"<b>{lb['cost_summary']}</b>", styles["section_header"]))
    flowables.append(Spacer(1, 3 * mm))
    flowables.append(_cost_totals_table(boq_data, currency, styles, lb, uw, country_code=country_code))

    # Single-pass build (no two-pass for page count - acceptable trade-off
    # for large BOQs; footer shows "Page X" without " of Y")
    doc.page_count = 0  # Will not display " of 0" - see footer_func logic
    doc.build(flowables)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
