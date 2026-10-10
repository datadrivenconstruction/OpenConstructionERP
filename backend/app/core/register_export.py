# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable registers and record forms shared by the project-control modules.

A register (the RFI log, the submittal log, the correspondence log, the
variation log) is a contractual record: it is printed, attached to a letter
and filed. Every module that keeps one needs the same sheet: what the
register is, which project it belongs to, when it was produced, a table that
repeats its header row, and "page x of y" so a missing sheet is noticed.
A single record (one submittal, one letter, one change order) needs the same
form the RFI already prints: title, number, status, a label and value grid,
boxed text, an item table and signature lines.

A module's own words are not here. Each module keeps its catalogue next to
its renderer, the way :mod:`app.modules.rfi.pdf_translations` does, and hands
this module finished labels. The only strings held here are the page
furniture every one of these sheets carries ("Project", "Page 2 of 5",
"Generated ..."), in :data:`FURNITURE`, so six catalogues cannot drift into
six spellings of the same footer. :class:`DocumentCatalogue` joins the two
and refuses, at import, a language that is declared without a complete
table: a locale listed as supported with no dictionary behind it is how a
reader ends up holding an English document after asking for their own.

What is shared beyond that is the layout and the three rules that are easy
to get wrong one module at a time:

* **Capitals follow the language.** ``str.upper`` turns a Turkish "i" into
  "I", so "Geçersiz" would print as "GEÇERSIZ". :func:`caps` is the one place
  that knows.
* **Amounts are written the way the project's market writes them**, by
  :mod:`app.core.regional_format`, from the ``Decimal`` and never through a
  float. In a workbook an amount stays a number with a number format, so the
  column still sorts and sums.
* **Every cell is a Paragraph**, so text wraps instead of running over the
  next column, user text is escaped instead of parsed as markup, and each
  string gets a face that can draw it (:mod:`app.core.pdf_fonts`).

The page count is found by building the document twice: the first pass
counts, the second prints the total. A register is a few hundred rows, so
the second pass costs less than a wrong "page 1" on a three page log.
"""

from __future__ import annotations

import html
import io
import logging
import re
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.document_locale import normalize_document_locale, resolve_document_locale, translate
from app.core.pdf_branding import (
    branded_appearance,
    branded_cover_brand,
    branded_doc_metadata,
    branded_header_logo,
    branded_letterhead,
)
from app.core.pdf_fonts import (
    BODY_FONT,
    BOLD_FONT,
    pdf_fit_line,
    pdf_fitted_style,
    pdf_font_for_text,
    pdf_room_beside,
    pdf_style_for_text,
    pdf_table_paragraph_rows,
    register_pdf_fonts,
)
from app.core.regional_format import COUNTRY_DEFAULTS, NumberStyle, date_format_for_country, format_number, number_style

__all__ = [
    "EMPTY",
    "FURNITURE",
    "DocumentCatalogue",
    "ProjectHeader",
    "RecordBlock",
    "RecordDocument",
    "RegisterColumn",
    "RegisterDocument",
    "TableLayout",
    "build_record_pdf",
    "build_register_pdf",
    "build_register_xlsx",
    "caps",
    "country_date_format",
    "export_filename",
    "format_amount",
    "format_count",
    "format_stored_date",
    "grid_rows",
    "parse_stored_date",
    "person_name",
    "printed_currency",
    "record_table_layout",
    "record_text_lines",
    "register_layout",
    "register_text_rows",
    "register_total_rows",
    "short_digest",
    "table_layout",
    "xlsx_date_format",
]

register_pdf_fonts()

logger = logging.getLogger(__name__)

#: What an absent value prints as, on every register and form.
EMPTY = "-"

_INK = colors.HexColor("#16213e")
_MUTED = colors.HexColor("#666666")
_RULE = colors.HexColor("#cccccc")
_LABEL_FILL = colors.HexColor("#f4f5f7")
_ZEBRA = colors.HexColor("#f8f9fb")

_MARGIN_SIDE = 15 * mm
_MARGIN_TOP = 18 * mm
_MARGIN_BOTTOM = 18 * mm
_FORM_MARGIN_SIDE = 20 * mm
_BLANK_BOX_HEIGHT = 30 * mm
_SIGNATURE_ROW_HEIGHT = 10 * mm
_LONG_SECTION_MIN_ROOM = 30 * mm
#: The running title on continuation pages: how far below the top edge its
#: line starts, and the room left clear on the right for the header logo.
_RUNNING_TITLE_TOP = 9 * mm
_RUNNING_TITLE_LOGO_ROOM = 50 * mm

# Table layout. See :func:`table_layout`.
#: Body sizes tried in order. A wide register steps down before any column
#: is allowed to break a word; below 6.5 pt a printed table stops being read.
_TABLE_FONT_STEPS = (8.0, 7.5, 7.0, 6.5)
_TABLE_LEADING = 1.25
_TABLE_CELL_PAD = 1.6 * mm
#: A free-text column keeps at least this much, so it is not squeezed to one
#: word per line while the columns beside it sit on their natural width.
_TABLE_WRAP_FLOOR = 26 * mm
#: A single word wider than this in a free-text column (a file name, a URL)
#: may be cut: holding the column open for it would starve every other one.
_TABLE_LONG_WORD = 42 * mm
#: The last resort floor of a free-text column once words may be cut.
_TABLE_LAST_FLOOR = 14 * mm
_TOKEN_SPLIT = re.compile(r"[ \t\r\n]+")


# ── Project header ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectHeader:
    """The project facts a register or a record form is headed with.

    Attributes:
        name: The project's name; empty when the project is gone.
        code: The project number, when it has one.
        currency: ISO 4217 code, upper-cased; empty when none is set.
        country: ISO 3166-1 alpha-2 of the project's country, when recorded.
    """

    name: str = ""
    code: str | None = None
    currency: str = ""
    country: str | None = None

    @property
    def label(self) -> str:
        """``"Name (CODE)"``, the name alone without a code, or a dash."""
        name = self.name or EMPTY
        return f"{name} ({self.code})" if self.code else name

    @property
    def number_style(self) -> NumberStyle:
        """How this project's market writes a number: its country decides, then its currency."""
        return number_style(self.country, self.currency)


def person_name(value: Any, people: Mapping[str, str] | None) -> str:
    """The name to print for a stored person or company reference.

    The column holds one of three things: an id the lookup resolved, an id it
    could not (a deleted account), or a name somebody typed. A resolved id
    prints the name and typed text prints as typed. An unresolved id prints a
    dash: any part of a UUID is a machine identifier, and on a document meant
    for people eight hex characters read as a broken export, not as a person.
    """
    if value is None or str(value).strip() == "":
        return EMPTY
    key = str(value).strip()
    names = people or {}
    if key in names:
        return names[key]
    try:
        canonical = str(uuid.UUID(key))
    except ValueError:
        return key
    return names.get(canonical) or EMPTY


# ── Catalogue ────────────────────────────────────────────────────────────

#: Page furniture shared by every register and record form. English is the
#: source; a language is added here first and to the module catalogues after.
#: ``days_one`` and ``days_other`` exist because English counts "1 day" and
#: "3 days" while Turkish keeps the noun singular after a numeral.
FURNITURE: dict[str, dict[str, str]] = {
    "en": {
        "project": "Project",
        "project_no": "Project no.",
        "generated_on": "Date generated",
        "records": "Records",
        "currency": "Currency",
        "status": "Status",
        "name": "Name",
        "signature": "Signature",
        "date": "Date",
        "signatures": "Signatures",
        "yes": "Yes",
        "no": "No",
        "days_one": "{n} day",
        "days_other": "{n} days",
        "empty_register": "No records.",
        "total": "Total",
        "signer_title": "Title",
        "sig_prepared_by": "Prepared by",
        "sig_checked_by": "Checked by",
        "sig_approved_by": "Approved by",
        "footer_generated": "Generated {timestamp}",
        "footer_page": "Page {page} of {total}",
        "date_format": "%Y-%m-%d",
        "datetime_format": "%Y-%m-%d %H:%M UTC",
    },
    "tr": {
        "project": "Proje",
        "project_no": "Proje no.",
        "generated_on": "Oluşturulma tarihi",
        "records": "Kayıt sayısı",
        "currency": "Para birimi",
        "status": "Durum",
        "name": "Adı Soyadı",
        "signature": "İmza",
        "date": "Tarih",
        "signatures": "İmzalar",
        "yes": "Evet",
        "no": "Hayır",
        "days_one": "{n} gün",
        "days_other": "{n} gün",
        "empty_register": "Kayıt yok.",
        "total": "Toplam",
        "signer_title": "Görevi",
        "sig_prepared_by": "Hazırlayan",
        "sig_checked_by": "Kontrol eden",
        "sig_approved_by": "Onaylayan",
        "footer_generated": "Oluşturulma: {timestamp}",
        "footer_page": "Sayfa {page} / {total}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
}


class DocumentCatalogue:
    """One module's printed strings, joined with the shared page furniture.

    Args:
        strings: The module's own strings, keyed by language then by key.
        labels: Named code tables (statuses, types), each keyed by language
            then by stored code.
        default: The fallback language; it must be in every table.

    Raises:
        ValueError: At construction, when a language is declared in one table
            and missing from another, when a table lacks a key the default
            language has, or when the page furniture has no such language.
            A catalogue that imports is complete.
    """

    def __init__(
        self,
        strings: dict[str, dict[str, str]],
        labels: dict[str, dict[str, dict[str, str]]] | None = None,
        *,
        default: str = "en",
    ) -> None:
        self.default = default
        self.labels = labels or {}
        self.supported: tuple[str, ...] = tuple(strings)
        problems: list[str] = []
        for locale in self.supported:
            if locale not in FURNITURE:
                problems.append(f"{locale}: no page furniture")
            missing = set(strings[default]) - set(strings[locale])
            if missing:
                problems.append(f"{locale}: strings missing {sorted(missing)}")
        for name, table in self.labels.items():
            if set(table) != set(self.supported):
                problems.append(f"label table {name!r} covers {sorted(table)}, not {sorted(self.supported)}")
                continue
            for locale in self.supported:
                missing = set(table[default]) - set(table[locale])
                if missing:
                    problems.append(f"{locale}: label table {name!r} missing {sorted(missing)}")
        if problems:
            raise ValueError("incomplete document catalogue: " + "; ".join(problems))
        self.strings = {locale: {**FURNITURE[locale], **strings[locale]} for locale in self.supported}

    def normalize(self, value: str | None) -> str:
        """Reduce a locale-ish value to a language this catalogue has."""
        return normalize_document_locale(value, self.supported, self.default)

    def resolve(self, locale_param: str | None, accept_language: str | None) -> str:
        """Pick the language for a request: ``?locale=``, then ``Accept-Language``, then the default."""
        return resolve_document_locale(locale_param, accept_language, self.supported, self.default)

    def tr(self, locale: str | None, key: str, **params: Any) -> str:
        """Resolve ``key``, falling back to the default language, then the key."""
        return translate(self.strings, self.normalize(locale), key, self.default, **params)

    def label(self, table: str, code: Any, locale: str | None) -> str:
        """The word for a stored code; an unknown code prints as stored, an absent one as a dash."""
        text = "" if code is None else str(code).strip()
        if not text:
            return EMPTY
        by_locale = self.labels[table]
        key = text.lower()
        return by_locale[self.normalize(locale)].get(key) or by_locale[self.default].get(key) or text

    def days(self, count: Any, locale: str | None) -> str:
        """A number of days with the noun in the form the language needs, or a dash."""
        if count is None or isinstance(count, bool) or str(count).strip() == "":
            return EMPTY
        try:
            number = int(count)
        except (TypeError, ValueError):
            return str(count)
        return self.tr(locale, "days_one" if abs(number) == 1 else "days_other", n=number)

    def yes_no(self, flag: Any, locale: str | None) -> str:
        """ "Yes" or "No" in the document language."""
        return self.tr(locale, "yes" if flag else "no")

    def register_details(
        self, locale: str | None, project: ProjectHeader, *, count: int, with_currency: bool = False
    ) -> list[tuple[str, str]]:
        """The identifying block above a register: project, number, date, record count."""
        today = datetime.now(tz=UTC).date().strftime(self.date_format(locale, project))
        details = [
            (self.tr(locale, "project"), project.name or EMPTY),
            (self.tr(locale, "project_no"), project.code or EMPTY),
            (self.tr(locale, "generated_on"), today),
            (self.tr(locale, "records"), str(count)),
        ]
        if with_currency:
            details.append((self.tr(locale, "currency"), printed_currency(project.currency, locale) or EMPTY))
        return details

    def date_format(self, locale: str | None, project: ProjectHeader | None = None) -> str:
        """The ``strftime`` pattern dates are printed in.

        Words follow the document language, figures follow the project's
        market. A date is a figure: an English register of a project in
        Türkiye prints 30.12.2026 next to 1.234,56, the way the same
        project's Turkish register does, instead of an ISO date beside a
        Turkish number. Without a country on file the language decides.
        """
        return country_date_format(project.country if project is not None else None) or self.tr(locale, "date_format")

    def furniture(self, locale: str | None, project: ProjectHeader | None = None) -> dict[str, str]:
        """The footer templates, date format and totals label a register builder passes on.

        Args:
            locale: The document language.
            project: The project the register belongs to. With it, dates are
                written the way the project's country writes them (see
                :meth:`date_format`) and the register knows which currency a
                row without one of its own is in. Without it the language
                decides the date.
        """
        furniture = {
            "page_label": self.tr(locale, "footer_page"),
            "generated_label": self.tr(locale, "footer_generated"),
            "date_format": self.date_format(locale, project),
            "totals_label": self.tr(locale, "total"),
        }
        if project is not None:
            furniture["currency"] = project.currency
        return furniture

    def signature_rows(self, locale: str | None, signers: Sequence[tuple[str, str]]) -> list[list[str]]:
        """Rows of a signature block: role, name, title, date, signature.

        The one shape every form of the set signs in, so a correspondence
        record, a change order and the daily report do not each invent their
        own captions.

        Args:
            locale: The document language.
            signers: ``(role label, printed name)`` per signer; a dash or an
                empty name leaves the cell blank for a pen.
        """
        header = [
            "",
            self.tr(locale, "name"),
            self.tr(locale, "signer_title"),
            self.tr(locale, "date"),
            self.tr(locale, "signature"),
        ]
        return [header, *[[role, "" if name == EMPTY else name, "", "", ""] for role, name in signers]]


# ── Value formatting ─────────────────────────────────────────────────────


#: How a currency is written on a printed form in a language, where that is
#: not the ISO code. Turkish commercial and site documents write the lira as
#: "TL": the published progress payment forms, unit price lists and invoices
#: all do, and "TRY" is the banking code. Workbook cells and stored data keep
#: the ISO code.
_PRINTED_CURRENCY: dict[str, dict[str, str]] = {"tr": {"TRY": "TL"}}


def country_date_format(country: str | None) -> str | None:
    """The ``strftime`` pattern a country writes dates in, or ``None`` when it is not on file.

    ``None`` rather than a default: a project with no country, or one the
    regional table does not know, keeps the date format of the document
    language instead of being handed somebody else's.
    """
    code = (country or "").strip().upper()
    if code not in COUNTRY_DEFAULTS:
        return None
    return date_format_for_country(code).replace("DD", "%d").replace("MM", "%m").replace("YYYY", "%Y")


def printed_currency(code: str | None, locale: str | None) -> str:
    """The currency as a form in ``locale`` prints it: ``"TL"`` in Turkish, else the ISO code."""
    iso = (code or "").strip().upper()
    language = (locale or "").strip().lower().replace("_", "-").split("-", 1)[0]
    return _PRINTED_CURRENCY.get(language, {}).get(iso, iso)


def short_digest(digest: str | None, length: int = 16) -> str:
    """The first ``length`` hex characters of a digest, in groups of four, or a dash.

    A printed integrity code is compared by eye with the one on screen.
    Sixty-four characters cannot be compared that way and wrap over two
    lines; sixteen in groups of four can, and still identify the content.
    """
    text = "".join((digest or "").split()).lower()
    if not text:
        return EMPTY
    head = text[:length]
    return " ".join(head[index : index + 4] for index in range(0, len(head), 4))


def caps(label: str, locale: str | None) -> str:
    """Upper-case a label the way its language writes capitals.

    Turkish keeps the dot on a capital i ("Geçersiz" is "GEÇERSİZ") and its
    dotless ı becomes a plain I, which ``str.upper`` already does. Greek drops
    the stress accent in capitals. Everything else is ``str.upper``.

    Args:
        label: The localised word or phrase.
        locale: The document language; a regional tag reads its language.

    Returns:
        The label in capitals.
    """
    language = (locale or "").strip().lower().replace("_", "-").split("-", 1)[0]
    if language in ("tr", "az"):
        return label.replace("i", "İ").upper()
    upper = label.upper()
    if language == "el":
        stripped = "".join(ch for ch in unicodedata.normalize("NFD", upper) if ch != "́")
        return unicodedata.normalize("NFC", stripped)
    return upper


def parse_stored_date(value: Any) -> date | None:
    """Read a date out of the shapes the modules store one in.

    A ``date``, a ``datetime``, ``YYYY-MM-DD`` and a full ISO timestamp are
    all in use, sometimes in the same column. Anything else is ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def format_stored_date(value: Any, date_format: str) -> str:
    """A stored date in ``date_format``, as stored when unparseable, or a dash.

    Args:
        value: The stored value, in any shape :func:`parse_stored_date` reads.
        date_format: A ``strftime`` pattern from the module's catalogue.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return EMPTY
    parsed = parse_stored_date(value)
    if parsed is None:
        return str(value).strip()
    return parsed.strftime(date_format)


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    text = str(value).strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() else None


def format_amount(
    value: Any, style: NumberStyle, currency: str | None = None, *, decimals: int = 2, locale: str | None = None
) -> str:
    """A money amount in the market's separators, with its currency code.

    A code is printed rather than a symbol: a register travels between
    companies and countries, and a code cannot be misread the way a symbol
    can. With ``locale`` the code is the one that language's forms print
    (see :func:`printed_currency`), otherwise the ISO code.

    Args:
        value: A ``Decimal``, or anything ``Decimal`` reads. Never a float.
        style: The separators, from :func:`app.core.regional_format.number_style`.
        currency: ISO 4217 code appended after a no-break space, when given.
        decimals: Fraction digits.
        locale: The document language, to print the currency its way.

    Returns:
        ``"1.234,56 TRY"``, the bare number without a currency, or a dash when
        there is no amount.
    """
    amount = _as_decimal(value)
    if amount is None:
        return EMPTY
    text = format_number(amount, decimals, style)
    code = printed_currency(currency, locale) if locale else (currency or "").strip().upper()
    return f"{text} {code}" if code else text


def format_count(value: Any) -> str:
    """A whole number (days, revision, item count), or a dash when absent."""
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return EMPTY
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def xlsx_date_format(date_format: str) -> str:
    """The spreadsheet number format for a ``strftime`` date pattern."""
    return date_format.replace("%d", "DD").replace("%m", "MM").replace("%Y", "YYYY")


def export_filename(stem: str | None, fallback: str, extension: str) -> str:
    """A download filename every operating system accepts.

    Everything outside letters, digits, dot, dash and underscore becomes an
    underscore, so a number typed with a slash or a space still gives a name.
    """
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in (stem or "").strip())
    return f"{cleaned or fallback}.{extension}"


# ── Register (a log of many records) ─────────────────────────────────────


@dataclass(frozen=True)
class RegisterColumn:
    """One column of a register.

    Attributes:
        header: The translated column heading.
        kind: How the cell is written: ``"text"`` as it is, ``"date"`` from
            any stored date shape, ``"money"`` from a ``Decimal`` with two
            decimals, ``"count"`` as a whole number, ``"currency"`` as the
            code the document language prints (the workbook keeps ISO).
        weight: Relative share of the width the page has left once every
            column has what it needs. It no longer sets the width on its own:
            see :func:`table_layout`.
        xlsx_width: Column width in the workbook, in characters.
        wrap: Wrap the workbook cell (long free text). On paper it also marks
            the column that takes the slack and wraps at word boundaries.
        nobreak: The printed cell never wraps and is never cut: a document
            number, a date, an amount. ``None`` decides by ``kind``: dates,
            amounts, counts and currency codes do not break, text does (at
            spaces only). Set ``True`` on a text column that holds document
            numbers or codes.
        total: Sum this ``"money"`` column in a totals row, per currency.
        pdf: Print the column. ``False`` keeps it in the workbook only, for
            identifiers a person does not read but a spreadsheet joins on.
    """

    header: str
    kind: str = "text"
    weight: float = 1.0
    xlsx_width: float = 16.0
    wrap: bool = False
    nobreak: bool | None = None
    total: bool = False
    pdf: bool = True

    @property
    def keeps_together(self) -> bool:
        """Whether a cell of this column must stay on one line."""
        if self.nobreak is not None:
            return self.nobreak
        return self.kind in ("date", "money", "count", "currency")


@dataclass(frozen=True)
class RegisterDocument:
    """Everything a register prints, already translated.

    Attributes:
        title: The register's name, e.g. "Submittal Register".
        columns: The columns, left to right.
        rows: One list of raw values per record, in column order.
        details: Label and value pairs printed above the table: project,
            project number, generated date and whatever else identifies the
            sheet. Printed in the order given.
        locale: The document language, for capitals and metadata.
        date_format: ``strftime`` pattern for date cells.
        number_style: Separators for money cells.
        page_label: Footer template with ``{page}`` and ``{total}``.
        generated_label: Footer template with ``{timestamp}``.
        generated: The timestamp printed in the footer.
        empty_text: Printed instead of the table when there are no records.
        sheet_title: Workbook sheet name; cut to the 31 characters a sheet
            name may have.
        doc_type: Key in :data:`app.core.pdf_appearance.DOCUMENT_TYPES`, when
            the workspace styles this document type separately.
        totals_label: The word for "Total". Totals rows are printed when it
            is set and at least one column has ``total=True``.
        currency_column: Index of the column holding each row's currency.
            Totals are kept apart per currency, never added across them.
        currency: The register's own currency (the project's): the currency
            of a row that names none, and the one the header already states.
        running_title: Printed top left on every page after the first, so a
            loose sheet says which register it came from. Defaults to the
            title and the project number or name from ``details``.
    """

    title: str
    columns: Sequence[RegisterColumn]
    rows: Sequence[Sequence[Any]]
    details: Sequence[tuple[str, str]] = ()
    locale: str = "en"
    date_format: str = "%Y-%m-%d"
    number_style: NumberStyle = field(default_factory=number_style)
    page_label: str = "Page {page} of {total}"
    generated_label: str = "Generated {timestamp}"
    generated: str = ""
    empty_text: str = ""
    sheet_title: str = ""
    doc_type: str | None = None
    totals_label: str = ""
    currency_column: int | None = None
    currency: str = ""
    running_title: str = ""


def _cell_text(value: Any, kind: str, document: RegisterDocument) -> str:
    if kind == "date":
        return format_stored_date(value, document.date_format)
    if kind == "money":
        return format_amount(value, document.number_style)
    if kind == "count":
        return format_count(value)
    text = "" if value is None else str(value).strip()
    if kind == "currency":
        return printed_currency(text, document.locale) or EMPTY
    return text or EMPTY


def register_text_rows(document: RegisterDocument) -> list[list[str]]:
    """The register's cells as strings, header row first, every column included.

    This is the layer just before rendering: what a test reads to check a
    register without extracting text from a PDF. The PDF prints these rows
    minus the columns it leaves to the workbook, plus the totals rows of
    :func:`register_total_rows`.
    """
    rows = [[column.header for column in document.columns]]
    for row in document.rows:
        rows.append(
            [_cell_text(value, column.kind, document) for value, column in zip(row, document.columns, strict=True)]
        )
    return rows


def _row_currency(row: Sequence[Any], document: RegisterDocument) -> str:
    """The ISO currency of one row: its own, else the register's."""
    own = ""
    if document.currency_column is not None and document.currency_column < len(row):
        own = str(row[document.currency_column] or "").strip().upper()
    return own or (document.currency or "").strip().upper()


def _register_totals(document: RegisterDocument) -> list[tuple[str, dict[int, Decimal]]]:
    """Sums of the ``total`` columns, one entry per currency, in order of first appearance.

    Computed from the stored ``Decimal`` values, never from printed text. A
    row with no amount in any totalled column (a time-only claim) belongs to
    no currency and adds nothing. Amounts in different currencies are never
    added together: each currency gets its own row.
    """
    totalled = [index for index, column in enumerate(document.columns) if column.total and column.kind == "money"]
    if not totalled or not document.totals_label:
        return []
    sums: dict[str, dict[int, Decimal]] = {}
    for row in document.rows:
        amounts = {index: _as_decimal(row[index]) for index in totalled if index < len(row)}
        present = {index: amount for index, amount in amounts.items() if amount is not None}
        if not present:
            continue
        bucket = sums.setdefault(_row_currency(row, document), {})
        for index, amount in present.items():
            bucket[index] = bucket.get(index, Decimal(0)) + amount
    return list(sums.items())


def register_total_rows(document: RegisterDocument) -> list[list[str]]:
    """The totals rows as printed strings, one per currency, in column order.

    The label sits in the first column that is neither an amount nor the
    currency, and names the currency ("Toplam (TL)") so the row reads on its
    own when the currency column is not printed.
    """
    rows: list[list[str]] = []
    label_column = next(
        (
            index
            for index, column in enumerate(document.columns)
            if column.pdf and column.kind not in ("money", "currency") and index != document.currency_column
        ),
        0,
    )
    for currency, sums in _register_totals(document):
        printed = printed_currency(currency, document.locale)
        cells = ["" for _ in document.columns]
        cells[label_column] = f"{document.totals_label} ({printed})" if printed else document.totals_label
        for index, amount in sums.items():
            cells[index] = format_amount(amount, document.number_style)
        if document.currency_column is not None:
            cells[document.currency_column] = printed or EMPTY
        rows.append(cells)
    return rows


def _single_stated_currency(document: RegisterDocument) -> bool:
    """Whether every row is in the register's own currency, which the header already states."""
    stated = (document.currency or "").strip().upper()
    if document.currency_column is None or not stated:
        return False
    index = document.currency_column
    own = {str(row[index] or "").strip().upper() for row in document.rows if index < len(row)}
    return own <= {stated, ""}


def _printed_columns(document: RegisterDocument) -> list[int]:
    """Indexes of the columns the PDF prints.

    Workbook-only columns are left out, and so is the currency column when
    every row is in the currency the header block already names: the same
    three letters on sixty rows say nothing and cost the description column
    its width.
    """
    hide_currency = _single_stated_currency(document)
    return [
        index
        for index, column in enumerate(document.columns)
        if column.pdf and not (hide_currency and index == document.currency_column)
    ]


def _footer_callback(
    *,
    page_label: str,
    generated_label: str,
    generated: str,
    total_pages: int,
    page_width: float,
    margin_side: float,
    doc_type: str | None,
    letterhead_on_first_page: bool,
    running_title: str = "",
    page_height: float = 0.0,
) -> Callable[[Any, Any], None]:
    """``onPage`` callback: translated footer, workspace logo top right, running title.

    Follows the workspace's document appearance the way the RFI form does: a
    saved footer line replaces the brand and timestamp, the footer colour
    colours it, and page numbers can be switched off.

    Every page after the first carries ``running_title`` top left, in the
    header margin. Page one states what the document is in full; a
    continuation sheet that comes loose from it has to say so too, and a
    table header alone ("Code, Title, Status") does not.
    """
    look = branded_appearance(doc_type=doc_type) or {}
    style = ParagraphStyle(
        "RegisterFooter",
        fontName=BODY_FONT,
        fontSize=7,
        leading=8,
        textColor=colors.HexColor(look.get("footer_color") or "#999999"),
    )
    right_style = ParagraphStyle("RegisterFooterRight", parent=style, alignment=TA_RIGHT)
    running_style = ParagraphStyle("RegisterRunningTitle", fontName=BOLD_FONT, fontSize=8, leading=10, textColor=_MUTED)
    custom_footer = str(look.get("footer_text") or "").strip()
    show_page_numbers = look.get("show_page_numbers", True) is not False
    usable = page_width - 2 * margin_side

    def _draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.5)
        canvas.line(margin_side, 13 * mm, page_width - margin_side, 13 * mm)
        page_text = page_label.format(page=doc.page, total=max(total_pages, doc.page)) if show_page_numbers else ""
        # One line, fitted into the room beside the page number: the paragraph
        # is anchored by its top, so a wrapped line would fall off the sheet.
        left_text, _face, left_size = pdf_fit_line(
            custom_footer or branded_cover_brand(),
            pdf_room_beside(usable, page_text),
            suffix="" if custom_footer else f"  |  {generated_label.format(timestamp=generated)}",
            base=BODY_FONT,
        )
        left = Paragraph(html.escape(left_text, quote=True), pdf_fitted_style(style, left_text, left_size))
        _, left_h = left.wrapOn(canvas, usable, 20)
        left.drawOn(canvas, margin_side, 9 * mm - left_h + 2)
        if page_text:
            right = Paragraph(html.escape(page_text, quote=True), pdf_style_for_text(right_style, page_text))
            _, right_h = right.wrapOn(canvas, usable, 20)
            right.drawOn(canvas, margin_side, 9 * mm - right_h + 2)
        if running_title and doc.page > 1 and page_height:
            # One line, beside the logo's corner: fitted, never wrapped.
            head_text, _head_face, head_size = pdf_fit_line(
                running_title, usable - _RUNNING_TITLE_LOGO_ROOM, size=8.0, bold=True, base=BOLD_FONT
            )
            head = Paragraph(html.escape(head_text, quote=True), pdf_fitted_style(running_style, head_text, head_size))
            _, head_h = head.wrapOn(canvas, usable, 20)
            head.drawOn(canvas, margin_side, page_height - _RUNNING_TITLE_TOP - head_h)
        canvas.restoreState()
        if not (letterhead_on_first_page and doc.page == 1):
            branded_header_logo(canvas, doc)

    return _draw


def _build_twice(
    make_story: Callable[[], tuple[list[Any], bool]],
    *,
    pagesize: tuple[float, float],
    margin_side: float,
    title: str,
    subject: str,
    page_label: str,
    generated_label: str,
    generated: str,
    doc_type: str | None,
    running_title: str = "",
) -> bytes:
    """Build the document, then build it again knowing how many pages it has."""
    page_width, page_height = pagesize
    meta = branded_doc_metadata()
    total_pages = 0
    output = b""
    for _pass in range(2):
        story, has_letterhead = make_story()
        buffer = io.BytesIO()
        doc = BaseDocTemplate(
            buffer,
            pagesize=pagesize,
            leftMargin=margin_side,
            rightMargin=margin_side,
            topMargin=_MARGIN_TOP,
            bottomMargin=_MARGIN_BOTTOM,
            title=title,
            author=meta["author"],
            subject=subject,
            creator=meta["creator"],
            producer=meta["producer"],
            keywords=meta["keywords"],
        )
        frame = Frame(
            margin_side,
            _MARGIN_BOTTOM,
            page_width - 2 * margin_side,
            page_height - _MARGIN_TOP - _MARGIN_BOTTOM,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="body",
        )
        on_page = _footer_callback(
            page_label=page_label,
            generated_label=generated_label,
            generated=generated,
            total_pages=total_pages,
            page_width=page_width,
            margin_side=margin_side,
            doc_type=doc_type,
            letterhead_on_first_page=has_letterhead,
            running_title=running_title,
            page_height=page_height,
        )
        doc.addPageTemplates([PageTemplate(id="body", frames=[frame], onPage=on_page)])
        doc.build(story)
        total_pages = doc.page
        output = buffer.getvalue()
    return output


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("RegTitle", parent=base, fontName=BOLD_FONT, fontSize=16, leading=20, textColor=_INK),
        "sub": ParagraphStyle("RegSub", parent=base, fontName=BODY_FONT, fontSize=10, leading=13, textColor=_MUTED),
        "status": ParagraphStyle(
            "RegStatus", parent=base, fontName=BOLD_FONT, fontSize=10, leading=12, textColor=_INK, alignment=TA_CENTER
        ),
        "subject": ParagraphStyle(
            "RegSubject",
            parent=base,
            fontName=BOLD_FONT,
            fontSize=13,
            leading=17,
            textColor=_INK,
            spaceBefore=5 * mm,
            spaceAfter=4 * mm,
        ),
        "section": ParagraphStyle(
            "RegSection",
            parent=base,
            fontName=BOLD_FONT,
            fontSize=11,
            leading=14,
            textColor=_INK,
            spaceBefore=4 * mm,
            spaceAfter=1.8 * mm,
        ),
        "label": ParagraphStyle(
            "RegLabel", parent=base, fontName=BODY_FONT, fontSize=8.5, leading=11, textColor=_MUTED
        ),
        "value": ParagraphStyle("RegValue", parent=base, fontName=BODY_FONT, fontSize=9.5, leading=12, textColor=_INK),
        "body": ParagraphStyle(
            "RegBody", parent=base, fontName=BODY_FONT, fontSize=10, leading=14, textColor=colors.black
        ),
        "muted": ParagraphStyle("RegMuted", parent=base, fontName=BODY_FONT, fontSize=9, leading=12, textColor=_MUTED),
        "head": ParagraphStyle("RegHead", parent=base, fontName=BOLD_FONT, fontSize=8, leading=10, textColor=_INK),
        "cell": ParagraphStyle(
            "RegCell", parent=base, fontName=BODY_FONT, fontSize=8, leading=10, textColor=colors.black
        ),
        "cell_right": ParagraphStyle(
            "RegCellRight",
            parent=base,
            fontName=BODY_FONT,
            fontSize=8,
            leading=10,
            textColor=colors.black,
            alignment=TA_RIGHT,
        ),
        "head_right": ParagraphStyle(
            "RegHeadRight",
            parent=base,
            fontName=BOLD_FONT,
            fontSize=8,
            leading=10,
            textColor=_INK,
            alignment=TA_RIGHT,
        ),
    }


def _para(text: Any, style: ParagraphStyle) -> Paragraph:
    """A Paragraph for user-supplied text: escaped, newlines kept, face per script."""
    rendered = "" if text is None else str(text)
    markup = html.escape(rendered, quote=True).replace("\n", "<br/>")
    return Paragraph(markup, pdf_style_for_text(style, rendered))


def _label_value_table(rows: Sequence[Sequence[str]], styles: dict[str, ParagraphStyle], widths: list[float]) -> Table:
    """A grid whose even columns are labels and odd columns are values."""

    def _style_for(_row: int, col: int) -> ParagraphStyle:
        return styles["label"] if col % 2 == 0 else styles["value"]

    table = Table(pdf_table_paragraph_rows(rows, styles["value"], style_for=_style_for), colWidths=widths)
    commands: list[tuple[Any, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.5, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]
    for col in range(0, len(widths), 2):
        commands.append(("BACKGROUND", (col, 0), (col, -1), _LABEL_FILL))
    table.setStyle(TableStyle(commands))
    return table


@dataclass(frozen=True)
class TableLayout:
    """Where the columns of a printed table sit, and what had to give.

    Attributes:
        widths: One width per column, in points, summing to the frame width.
        font_size: The body size the table is set in. Smaller than the
            usual 8 pt when the register is too wide for it.
        overflow: Columns whose keep-together content (a number, a date, an
            amount, a header word) is still wider than the column. Empty for
            every sane register; a test asserts that, and a live export logs
            a warning and prints rather than refusing the document.
        cut_words: Free-text columns in which a single over-long word (a
            file name, a URL) is allowed to be cut. Nothing else is.
    """

    widths: tuple[float, ...]
    font_size: float
    overflow: tuple[int, ...] = ()
    cut_words: tuple[int, ...] = ()


def _unit_width(text: str, *, bold: bool) -> float:
    """The width of ``text`` at 1 pt, in the face that will draw it."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if not text:
        return 0.0
    face = pdf_font_for_text(text, bold=bold, base=BOLD_FONT if bold else BODY_FONT)
    return float(stringWidth(text, face, 1.0))


def table_layout(
    rows: Sequence[Sequence[str]],
    weights: Sequence[float],
    usable_width: float,
    *,
    keep_together: Sequence[bool] = (),
    flexible: Sequence[bool] = (),
    header_rows: int = 1,
    bold_rows: Sequence[int] = (),
    base_size: float = _TABLE_FONT_STEPS[0],
) -> TableLayout:
    """Size the columns of a table from what they hold.

    Dividing the page by fixed weights gives a date column nineteen
    millimetres whatever it holds, and the paragraph engine then cuts
    "28.12.2026" after the second digit of the year to make it fit. A
    register that prints "RFI-000" over "1" is not one a contract
    administrator files. So the widths start from the content:

    1. Every column gets at least its widest unbreakable piece, measured in
       the face and size it is drawn in. In a keep-together column (document
       numbers, dates, amounts) that is the whole cell; in a text column it
       is the widest word, and a header may wrap between words but not
       inside one. A free-text column also keeps a comfortable floor.
    2. If those minimums do not fit the frame, the body size steps down
       (8, 7.5, 7, 6.5 pt) before anything else gives.
    3. If they still do not fit, the free-text columns give up their floor
       and their long words, down to a last floor. Only then is a
       keep-together column reported in ``overflow``.
    4. The width left over goes to the columns that would otherwise wrap,
       by weight, each up to the width at which it no longer wraps, and
       what remains after that to the free-text columns.

    Args:
        rows: The table's cells as printed strings, header rows first.
        weights: Relative share of the slack per column.
        usable_width: The frame width, in points.
        keep_together: Per column, whether a cell must stay on one line.
        flexible: Per column, whether it is free text that takes the slack.
        header_rows: How many leading rows are headings (bold, may wrap
            between words).
        bold_rows: Indexes of body rows set in bold (totals).
        base_size: The body size to start from.

    Returns:
        The layout. ``overflow`` is empty unless the table cannot be printed
        without cutting a keep-together cell.
    """
    count = max((len(row) for row in rows), default=0)
    if not count:
        return TableLayout(widths=(), font_size=base_size)

    def _flag(flags: Sequence[bool], index: int) -> bool:
        return bool(flags[index]) if index < len(flags) else False

    share = [float(weights[index]) if index < len(weights) and weights[index] else 1.0 for index in range(count)]
    bold_body = set(bold_rows)
    head_word = [0.0] * count
    widest_line = [0.0] * count
    widest_word = [0.0] * count
    for row_index, row in enumerate(rows):
        is_header = row_index < header_rows
        bold = is_header or row_index in bold_body
        for index, cell in enumerate(row):
            if not isinstance(cell, str) or not cell:
                continue
            words = max((_unit_width(word, bold=bold) for word in _TOKEN_SPLIT.split(cell) if word), default=0.0)
            if is_header:
                head_word[index] = max(head_word[index], words)
                continue
            line = max((_unit_width(part.strip(), bold=bold) for part in cell.splitlines()), default=0.0)
            widest_line[index] = max(widest_line[index], line)
            widest_word[index] = max(widest_word[index], words)

    # Padding on both sides, and a hair for the difference between measuring
    # a string and the paragraph engine adding its words up one by one.
    pad = 2 * _TABLE_CELL_PAD + 0.8

    def _minimums(size: float, *, relaxed: bool) -> list[float]:
        minimums = []
        for index in range(count):
            header = head_word[index] * size
            if _flag(keep_together, index):
                need = max(header, widest_line[index] * size)
            elif relaxed:
                need = max(header, min(widest_word[index] * size, _TABLE_LAST_FLOOR))
            else:
                need = max(header, min(widest_word[index] * size, _TABLE_LONG_WORD))
                if _flag(flexible, index):
                    need = max(need, min(widest_line[index] * size, _TABLE_WRAP_FLOOR))
            minimums.append(need + pad)
        return minimums

    steps = [step for step in _TABLE_FONT_STEPS if step <= base_size] or [base_size]
    if steps[0] != base_size:
        steps.insert(0, base_size)
    size = steps[-1]
    minimums = _minimums(size, relaxed=True)
    for step in steps:
        candidate = _minimums(step, relaxed=False)
        if sum(candidate) <= usable_width:
            size, minimums = step, candidate
            break

    widths = list(minimums)
    overflow: list[int] = []
    total = sum(widths)
    if total > usable_width:
        # Nothing left to give: every column shrinks in proportion, and the
        # keep-together ones are named so the caller can say so.
        widths = [width * usable_width / total for width in widths]
        for index in range(count):
            hard = max(head_word[index], widest_line[index] if _flag(keep_together, index) else 0.0) * size + pad
            if hard > widths[index] + 0.01:
                overflow.append(index)
    else:
        room = usable_width - total
        natural = [max(head_word[index], widest_line[index]) * size + pad for index in range(count)]
        wanting = [index for index in range(count) if natural[index] > widths[index] + 0.01]
        while room > 0.01 and wanting:
            weight_sum = sum(share[index] for index in wanting)
            filled = [index for index in wanting if widths[index] + room * share[index] / weight_sum >= natural[index]]
            if not filled:
                for index in wanting:
                    widths[index] += room * share[index] / weight_sum
                room = 0.0
                break
            for index in filled:
                room -= natural[index] - widths[index]
                widths[index] = natural[index]
            wanting = [index for index in wanting if index not in filled]
        if room > 0.01:
            takers = [index for index in range(count) if _flag(flexible, index)] or list(range(count))
            weight_sum = sum(share[index] for index in takers)
            for index in takers:
                widths[index] += room * share[index] / weight_sum

    cut_words = [
        index
        for index in range(count)
        if not _flag(keep_together, index) and widest_word[index] * size + pad > widths[index] + 0.01
    ]
    return TableLayout(widths=tuple(widths), font_size=size, overflow=tuple(overflow), cut_words=tuple(cut_words))


class _PagedTable(Table):
    """A table that never starts a row it cannot finish on the page.

    reportlab splits a table between rows first and inside a row only when
    not even one row fits. With the in-row split switched on, that second
    rule fires in the wrong place: the first part fills most of the page,
    the remainder (which carries the repeated header) is offered the few
    lines left under it, no whole row fits there, and so the header is
    printed again in the middle of the page with the top of a row under it
    and the rest of that row on the next sheet.

    Here a row that does not fit what is left of the page, but does fit a
    whole page, goes to the next page. A row is cut only when it is taller
    than a page, which is the one case where cutting is the only way to
    print it.
    """

    _full_height: float = 0.0

    def split(self, availWidth: float, availHeight: float) -> list[Any]:  # noqa: N803 - reportlab's signature
        self._calc(availWidth, availHeight)
        heights = list(self._rowHeights or [])
        head = int(self.repeatRows or 0) if isinstance(self.repeatRows, int) else 0
        if self._full_height and len(heights) > head:
            first_row = sum(heights[: head + 1])
            if first_row > availHeight and first_row <= self._full_height:
                return []
        parts = super().split(availWidth, availHeight)
        for part in parts:
            if isinstance(part, _PagedTable):
                part._full_height = self._full_height
        return parts


def _default_flexible(weights: Sequence[float]) -> list[bool]:
    """Free-text columns of a table that does not say which they are: the heavy ones."""
    heaviest = max(weights, default=1.0)
    return [weight >= 2.0 or weight == heaviest for weight in weights]


def _data_table(
    rows: Sequence[Sequence[str]],
    weights: Sequence[float],
    right_aligned: Sequence[bool],
    usable_width: float,
    styles: dict[str, ParagraphStyle],
    *,
    keep_together: Sequence[bool] | None = None,
    flexible: Sequence[bool] | None = None,
    total_rows: int = 0,
    frame_height: float = 0.0,
    report: str = "table",
) -> Table:
    """A header row plus data rows, the header repeated on every page.

    Args:
        rows: Printed strings, header row first, totals rows last.
        weights: Relative share of the slack per column.
        right_aligned: Which columns are numbers.
        usable_width: The frame width.
        styles: The sheet's paragraph styles.
        keep_together: Which columns never wrap; the number columns when
            not given.
        flexible: Which columns are free text; the heavy ones when not given.
        total_rows: How many trailing rows are totals, set in bold under a rule.
        frame_height: The height of a full page's frame, so a row moves to
            the next page instead of being cut (see :class:`_PagedTable`).
        report: Named in the log line when a keep-together cell overflows.
    """
    keep = list(keep_together) if keep_together is not None else list(right_aligned)
    flex = list(flexible) if flexible is not None else _default_flexible(weights)
    first_total = len(rows) - total_rows if total_rows else len(rows)
    bold_rows = list(range(first_total, len(rows)))
    base_size = float(styles["cell"].fontSize)
    layout = table_layout(
        rows,
        weights,
        usable_width,
        keep_together=keep,
        flexible=flex,
        bold_rows=bold_rows,
        base_size=base_size,
    )
    if layout.overflow:
        logger.warning(
            "%s: %d column(s) hold content wider than the page allows at %.1f pt; those cells will be cut",
            report,
            len(layout.overflow),
            layout.font_size,
        )
    size = layout.font_size
    leading = round(size * _TABLE_LEADING, 2)
    breakable = set(layout.cut_words) | set(layout.overflow)
    cache: dict[tuple[str, bool, bool], ParagraphStyle] = {}

    def _styled(name: str, *, bold: bool, cut: bool) -> ParagraphStyle:
        key = (name, bold, cut)
        if key not in cache:
            cache[key] = styles[name].clone(
                f"{styles[name].name}-{size:g}-{int(bold)}{int(cut)}",
                fontName=BOLD_FONT if bold else styles[name].fontName,
                fontSize=size,
                leading=leading,
                # A word is never cut to make it fit, except in a column the
                # layout named: the page is sized so that it does fit.
                splitLongWords=1 if cut else 0,
            )
        return cache[key]

    def _style_for(row: int, col: int) -> ParagraphStyle:
        right = right_aligned[col] if col < len(right_aligned) else False
        cut = col in breakable
        if row == 0:
            return _styled("head_right" if right else "head", bold=False, cut=cut)
        return _styled("cell_right" if right else "cell", bold=row >= first_total, cut=cut)

    table = _PagedTable(
        pdf_table_paragraph_rows(rows, styles["cell"], style_for=_style_for),
        colWidths=list(layout.widths),
        repeatRows=1,
        splitInRow=1,
    )
    table._full_height = frame_height
    commands: list[tuple[Any, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("BACKGROUND", (0, 0), (-1, 0), _LABEL_FILL),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.3 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), _TABLE_CELL_PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), _TABLE_CELL_PAD),
    ]
    if total_rows and first_total > 0:
        commands.extend(
            [
                ("BACKGROUND", (0, first_total), (-1, -1), _LABEL_FILL),
                ("LINEABOVE", (0, first_total), (-1, first_total), 1.0, _INK),
            ]
        )
    table.setStyle(TableStyle(commands))
    return table


def _register_print(document: RegisterDocument) -> tuple[list[list[str]], list[RegisterColumn], int]:
    """The rows and columns the PDF prints, and how many of the rows are totals."""
    printed = _printed_columns(document)
    totals = register_total_rows(document)
    rows = [[row[index] for index in printed] for row in [*register_text_rows(document), *totals]]
    return rows, [document.columns[index] for index in printed], len(totals)


def register_layout(document: RegisterDocument) -> TableLayout:
    """The column layout :func:`build_register_pdf` prints ``document`` with.

    What a test asserts on: ``overflow`` empty means no document number,
    date or amount of this register is cut or wrapped.
    """
    rows, columns, total_rows = _register_print(document)
    return table_layout(
        rows,
        [column.weight for column in columns],
        landscape(A4)[0] - 2 * _MARGIN_SIDE,
        keep_together=[column.keeps_together for column in columns],
        flexible=[column.wrap for column in columns],
        bold_rows=list(range(len(rows) - total_rows, len(rows))),
    )


def build_register_pdf(document: RegisterDocument) -> bytes:
    """Render a register as a landscape A4 PDF.

    Args:
        document: The translated register.

    Returns:
        The PDF as bytes, starting with ``b"%PDF"``.
    """
    pagesize = landscape(A4)
    usable = pagesize[0] - 2 * _MARGIN_SIDE
    frame_height = pagesize[1] - _MARGIN_TOP - _MARGIN_BOTTOM
    text_rows, columns, total_rows = _register_print(document)
    right_aligned = [column.kind in ("money", "count") for column in columns]
    weights = [column.weight for column in columns]
    record_count = len(text_rows) - 1 - total_rows

    def _story() -> tuple[list[Any], bool]:
        styles = _styles()
        flow: list[Any] = []
        letterhead = branded_letterhead(usable, doc_type=document.doc_type)
        if letterhead is not None:
            flow.append(letterhead)
        flow.append(_para(document.title, styles["title"]))
        flow.append(Spacer(1, 2 * mm))
        if document.details:
            # Two label and value pairs per row, so six details take three
            # lines instead of six and the table starts higher on page one.
            pairs = list(document.details)
            grid_rows = []
            for index in range(0, len(pairs), 2):
                left = pairs[index]
                right = pairs[index + 1] if index + 1 < len(pairs) else ("", "")
                grid_rows.append([left[0], left[1], right[0], right[1]])
            label_w, value_w = 38 * mm, usable / 2 - 38 * mm
            flow.append(_label_value_table(grid_rows, styles, [label_w, value_w, label_w, value_w]))
            flow.append(Spacer(1, 4 * mm))
        flow.append(
            _data_table(
                text_rows,
                weights,
                right_aligned,
                usable,
                styles,
                keep_together=[column.keeps_together for column in columns],
                flexible=[column.wrap for column in columns],
                total_rows=total_rows,
                frame_height=frame_height,
                report=document.title,
            )
        )
        if record_count == 0:
            flow.append(Spacer(1, 3 * mm))
            flow.append(_para(document.empty_text, styles["muted"]))
        return flow, letterhead is not None

    return _build_twice(
        _story,
        pagesize=pagesize,
        margin_side=_MARGIN_SIDE,
        title=document.title,
        subject=document.title,
        page_label=document.page_label,
        generated_label=document.generated_label,
        generated=document.generated,
        doc_type=document.doc_type,
        running_title=document.running_title or _register_running_title(document),
    )


def _register_running_title(document: RegisterDocument) -> str:
    """The register's title with what identifies the project, for continuation pages.

    Every register is headed by :meth:`DocumentCatalogue.register_details`,
    whose first two entries are the project name and the project number; the
    number is the shorter and the one a filing clerk looks for, so it is
    preferred, and the name stands in when a project has none.
    """
    values = [value for _label, value in list(document.details)[:2] if value and value != EMPTY]
    project = values[1] if len(values) > 1 else (values[0] if values else "")
    return " · ".join(part for part in (document.title, project) if part)


def build_register_xlsx(document: RegisterDocument) -> io.BytesIO:
    """Render a register as a print-ready workbook.

    Dates are written as dates and amounts as numbers, each with a number
    format, so the sheet sorts, filters and sums. Text cells go through the
    formula neutraliser: a subject line is user text, and a cell that starts
    with ``=`` would run when a colleague opens the log.

    Args:
        document: The translated register.

    Returns:
        A buffer positioned at the start of the ``.xlsx`` file.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.properties import PageSetupProperties

    from app.core.csv_safety import neutralise_formula
    from app.core.xlsx_branding import apply_company_header
    from app.core.xlsx_text import store_strings_as_text

    wb = Workbook()
    ws = wb.active
    # A sheet name holds 31 characters and none of these seven.
    sheet_title = "".join(" " if ch in "[]:*?/\\" else ch for ch in (document.sheet_title or document.title))
    ws.title = _sheet_name(sheet_title) or "Register"

    # A heading longer than its column wraps inside it instead of running
    # under the next heading, where the reader sees half of each.
    header_alignment = Alignment(wrap_text=True, vertical="top")
    for col, column in enumerate(document.columns, 1):
        header_cell = ws.cell(row=1, column=col, value=column.header)
        header_cell.font = Font(bold=True)
        header_cell.alignment = header_alignment
        ws.column_dimensions[get_column_letter(col)].width = column.xlsx_width

    date_number_format = xlsx_date_format(document.date_format)
    wrap_top = Alignment(wrap_text=True, vertical="top")
    top = Alignment(vertical="top")
    for row_index, row in enumerate(document.rows, 2):
        for col, (value, column) in enumerate(zip(row, document.columns, strict=True), 1):
            cell = ws.cell(row=row_index, column=col)
            # Text longer than its column wraps whether or not the column was
            # declared free text: a name or a reason can be long too, and an
            # unwrapped cell is cut off by the next one on screen and on paper.
            overlong = column.kind == "text" and value is not None and len(str(value).strip()) > column.xlsx_width
            cell.alignment = wrap_top if column.wrap or overlong else top
            if column.kind == "date":
                parsed = parse_stored_date(value)
                if parsed is not None:
                    cell.value = parsed
                    cell.number_format = date_number_format
                elif value is not None and str(value).strip():
                    cell.value = neutralise_formula(str(value).strip())
            elif column.kind == "money":
                amount = _as_decimal(value)
                if amount is not None:
                    cell.value = amount
                    cell.number_format = "#,##0.00"
            elif column.kind == "count":
                if value is not None and not isinstance(value, bool) and str(value).strip() != "":
                    try:
                        cell.value = int(value)
                    except (TypeError, ValueError):
                        cell.value = neutralise_formula(str(value))
            elif value is not None and str(value).strip() not in ("", EMPTY):
                # A dash stands for "nobody" on paper; in a workbook the cell
                # is left empty so a filter on blanks finds it.
                cell.value = neutralise_formula(str(value).strip())

    # Totals, one row per currency, as values: the amounts above stay
    # sortable numbers, and the totals say what the printed register says.
    bold = Font(bold=True)
    label_column = next(
        (
            index
            for index, column in enumerate(document.columns)
            if column.kind not in ("money", "currency") and index != document.currency_column
        ),
        0,
    )
    for offset, (currency, sums) in enumerate(_register_totals(document)):
        total_row = len(document.rows) + 2 + offset
        label = f"{document.totals_label} ({currency})" if currency else document.totals_label
        ws.cell(row=total_row, column=label_column + 1, value=label).font = bold
        for index, amount in sums.items():
            total_cell = ws.cell(row=total_row, column=index + 1, value=amount)
            total_cell.number_format = "#,##0.00"
            total_cell.font = bold
        if document.currency_column is not None and currency:
            ws.cell(row=total_row, column=document.currency_column + 1, value=currency).font = bold

    ws.freeze_panes = "A2"
    ws.print_title_rows = "1:1"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    store_strings_as_text(ws)
    # The document block says which project and when, with or without a
    # company letterhead: a register detached from its letter must still say
    # what it is.
    table_chars = sum(float(column.xlsx_width or 0) for column in document.columns)
    apply_company_header(ws, title=document.title, details=_xlsx_detail_lines(document.details, table_chars))

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def _sheet_name(title: str) -> str:
    """A sheet name within the 31 characters a workbook allows, cut between words.

    Cutting at the limit left "Değişiklik Emirleri Kayıt Liste": a name that
    ends in half a word. The last whole word that fits is kept instead.
    """
    name = " ".join(title.split())
    if len(name) <= 31:
        return name
    head = name[:32]
    cut = head.rfind(" ")
    return (head[:cut] if cut >= 12 else name[:31]).rstrip(" -(,")


def _xlsx_detail_lines(details: Sequence[tuple[str, str]], table_chars: float = 0.0) -> list[str]:
    """The identifying block as at most three lines of a workbook header.

    The header block holds three detail lines
    (:data:`app.core.xlsx_branding.MAX_DETAIL_LINES`), so a register with
    more than three details used to lose the rest without a word. They are
    grouped instead. A header line is one text cell in column A that shows
    across the empty cells to its right, so a line is filled only up to the
    width of the table under it (``table_chars``, the sum of the column
    widths): the block then prints inside the sheet the table fits on.
    When three lines of that width cannot hold everything, the details are
    spread evenly and the last ones run past the table rather than vanish.
    """
    from app.core.xlsx_branding import MAX_DETAIL_LINES

    pairs = [f"{label}: {value}" for label, value in details if label]
    if len(pairs) <= MAX_DETAIL_LINES:
        return pairs
    separator = "  |  "
    if table_chars > 0:
        lines: list[str] = []
        for pair in pairs:
            if lines and len(lines[-1]) + len(separator) + len(pair) <= table_chars:
                lines[-1] = f"{lines[-1]}{separator}{pair}"
            else:
                lines.append(pair)
        if len(lines) <= MAX_DETAIL_LINES:
            return lines
    per_line = -(-len(pairs) // MAX_DETAIL_LINES)
    return [separator.join(pairs[index : index + per_line]) for index in range(0, len(pairs), per_line)]


# ── Record (one item, as a form) ─────────────────────────────────────────


@dataclass(frozen=True)
class RecordBlock:
    """One section of a record form.

    Attributes:
        title: The section heading.
        kind: ``"text"`` for boxed free text, ``"grid"`` for label and value
            pairs, ``"table"`` for a header row plus rows, ``"signatures"``
            for rows to sign in.
        text: The body of a ``"text"`` block.
        empty_text: Printed in a blank box when a ``"text"`` block has no
            body, so a printed copy can be filled in by hand.
        rows: Rows of a ``"grid"`` (label, value[, label, value]), a
            ``"table"`` (header row first) or ``"signatures"`` (header row
            first, then one row per signer).
        weights: Relative share of the slack per ``"table"`` column (see
            :func:`table_layout`; a weight no longer fixes a width).
        right_aligned: Which ``"table"`` columns are numbers.
        keep_together: Which ``"table"`` columns never wrap (numbers, dates,
            document numbers). The right-aligned ones when not given.
        total_rows: How many trailing ``"table"`` rows are totals, printed
            in bold under a rule.
    """

    title: str
    kind: str = "text"
    text: str = ""
    empty_text: str = ""
    rows: Sequence[Sequence[str]] = ()
    weights: Sequence[float] = ()
    right_aligned: Sequence[bool] = ()
    keep_together: Sequence[bool] = ()
    total_rows: int = 0


@dataclass(frozen=True)
class RecordDocument:
    """Everything a single-record form prints, already translated.

    Attributes:
        title: The document title, e.g. "Submittal".
        number: The record's own number.
        project_label: Project name, with its code when it has one.
        status_text: The status, already in capitals (see :func:`caps`).
        subject: The record's subject or title line.
        grid: Rows of ``[label, value, label, value]`` under the subject.
        blocks: The sections, top to bottom.
        page_label: Footer template with ``{page}`` and ``{total}``.
        generated_label: Footer template with ``{timestamp}``.
        generated: The timestamp printed in the footer.
        doc_type: Key in :data:`app.core.pdf_appearance.DOCUMENT_TYPES`.
    """

    title: str
    number: str
    project_label: str
    status_text: str
    subject: str
    grid: Sequence[Sequence[str]] = ()
    blocks: Sequence[RecordBlock] = ()
    page_label: str = "Page {page} of {total}"
    generated_label: str = "Generated {timestamp}"
    generated: str = ""
    doc_type: str | None = None


def grid_rows(pairs: Sequence[tuple[str, str] | None]) -> list[list[str]]:
    """Lay label and value pairs out two to a row, for :attr:`RecordDocument.grid`.

    A form drops a pair that does not apply (no attachments, so no
    "Attachments: 0" line) by passing ``None`` for it, and the rest close up
    instead of leaving a hole in the grid.
    """
    kept = [pair for pair in pairs if pair is not None]
    rows = []
    for index in range(0, len(kept), 2):
        left = kept[index]
        right = kept[index + 1] if index + 1 < len(kept) else ("", "")
        rows.append([left[0], left[1], right[0], right[1]])
    return rows


def record_text_lines(document: RecordDocument) -> list[str]:
    """Every string the record form prints, in reading order.

    The layer just before rendering, for tests that check a form without
    extracting text from the PDF.
    """
    lines = [document.title, f"{document.number} · {document.project_label}", document.status_text, document.subject]
    for row in document.grid:
        lines.extend(row)
    for block in document.blocks:
        lines.append(block.title)
        if block.kind == "text":
            lines.append(block.text if block.text.strip() else block.empty_text)
        for row in block.rows:
            lines.extend(row)
    return [line for line in lines if line]


def _boxed(flowables: list[Any], width: float, *, min_height: float | None = None) -> Table:
    """One bordered cell; long content splits across pages."""
    table = Table([[flowables]], colWidths=[width], rowHeights=[min_height] if min_height else None, splitInRow=1)
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, _RULE),
                # A box cut by a page break is closed at the cut and opened
                # again on the next page.
                ("LINEBELOW", (0, "splitlast"), (-1, "splitlast"), 0.6, _RULE),
                ("LINEABOVE", (0, "splitfirst"), (-1, "splitfirst"), 0.6, _RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    return table


def _block_table_args(block: RecordBlock) -> tuple[list[float], list[bool], list[bool]]:
    """The weights, number columns and keep-together columns of a ``"table"`` block."""
    count = len(block.rows[0]) if block.rows else 1
    weights = list(block.weights) or [1.0] * count
    right_aligned = list(block.right_aligned)
    keep = list(block.keep_together) if block.keep_together else list(right_aligned)
    return weights, right_aligned, keep


def record_table_layout(block: RecordBlock) -> TableLayout:
    """The column layout :func:`build_record_pdf` prints a ``"table"`` block with.

    The record counterpart of :func:`register_layout`, for the same test.
    """
    weights, _right_aligned, keep = _block_table_args(block)
    first_total = len(block.rows) - block.total_rows
    return table_layout(
        block.rows,
        weights,
        A4[0] - 2 * _FORM_MARGIN_SIDE,
        keep_together=keep,
        flexible=_default_flexible(weights),
        bold_rows=list(range(first_total, len(block.rows))),
    )


#: Column shares of a signature block, by its number of columns: the four
#: column form (role, name, signature, date) and the five column one of
#: :meth:`DocumentCatalogue.signature_rows` (role, name, title, date, signature).
_SIGNATURE_SHARES: dict[int, tuple[float, ...]] = {
    4: (0.2, 0.32, 0.3, 0.18),
    5: (0.2, 0.26, 0.2, 0.14, 0.2),
}


def _block_flowables(
    block: RecordBlock, usable: float, styles: dict[str, ParagraphStyle], frame_height: float = 0.0
) -> list[Any]:
    heading = Paragraph(html.escape(block.title), pdf_style_for_text(styles["section"], block.title))
    if block.kind == "grid":
        columns = max((len(row) for row in block.rows), default=2)
        if columns >= 4:
            widths = [32 * mm, usable / 2 - 32 * mm, 32 * mm, usable / 2 - 32 * mm]
        else:
            widths = [45 * mm, usable - 45 * mm]
        return [KeepTogether([heading, _label_value_table(block.rows, styles, widths)])]
    if block.kind == "table":
        weights, right_aligned, keep = _block_table_args(block)
        table = _data_table(
            block.rows,
            weights,
            right_aligned,
            usable,
            styles,
            keep_together=keep,
            total_rows=block.total_rows,
            frame_height=frame_height,
            report=block.title,
        )
        return [CondPageBreak(_LONG_SECTION_MIN_ROOM), heading, table]
    if block.kind == "signatures":

        def _sign_style(row: int, col: int) -> ParagraphStyle:
            if row == 0:
                return styles["head"]
            return styles["label"] if col == 0 else styles["value"]

        columns = max((len(row) for row in block.rows), default=4)
        shares = _SIGNATURE_SHARES.get(columns) or tuple(1 / columns for _ in range(columns))
        cells = pdf_table_paragraph_rows(block.rows, styles["value"], style_for=_sign_style)
        # A row is at least the height a signature needs and grows with its
        # content. A fixed height let a company name of three lines run over
        # the rules of its cell. The signature cell is blank on every form,
        # so a strut there holds the minimum (less the cell's own padding).
        for row in cells[1:]:
            if row:
                row[-1] = Spacer(1, _SIGNATURE_ROW_HEIGHT - 6)
        table = Table(cells, colWidths=[usable * share for share in shares])
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, _RULE),
                    ("BACKGROUND", (0, 0), (-1, 0), _LABEL_FILL),
                    ("BACKGROUND", (0, 1), (0, -1), _LABEL_FILL),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ]
            )
        )
        return [KeepTogether([heading, table])]
    if block.text.strip():
        box = _boxed([_para(block.text, styles["body"])], usable)
    else:
        box = _boxed([_para(block.empty_text, styles["muted"])], usable, min_height=_BLANK_BOX_HEIGHT)
    return [CondPageBreak(_LONG_SECTION_MIN_ROOM), heading, box]


def build_record_pdf(document: RecordDocument) -> bytes:
    """Render one record as a portrait A4 form.

    Args:
        document: The translated record.

    Returns:
        The PDF as bytes, starting with ``b"%PDF"``.
    """
    usable = A4[0] - 2 * _FORM_MARGIN_SIDE
    frame_height = A4[1] - _MARGIN_TOP - _MARGIN_BOTTOM

    def _story() -> tuple[list[Any], bool]:
        styles = _styles()
        flow: list[Any] = []
        letterhead = branded_letterhead(usable, doc_type=document.doc_type)
        if letterhead is not None:
            flow.append(letterhead)
        header = Table(
            [
                [
                    [
                        _para(document.title, styles["title"]),
                        _para(f"{document.number} · {document.project_label}", styles["sub"]),
                    ],
                    _para(document.status_text, styles["status"]),
                ]
            ],
            colWidths=[usable - 44 * mm, 44 * mm],
        )
        header.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (0, 0), 0),
                    ("BOX", (1, 0), (1, 0), 0.8, _INK),
                    ("TOPPADDING", (1, 0), (1, 0), 2 * mm),
                    ("BOTTOMPADDING", (1, 0), (1, 0), 2 * mm),
                    ("LINEBELOW", (0, 0), (-1, 0), 1.5, _INK),
                    ("BOTTOMPADDING", (0, 0), (0, 0), 3 * mm),
                ]
            )
        )
        flow.append(header)
        flow.append(_para(document.subject, styles["subject"]))
        if document.grid:
            half = usable / 2
            flow.append(_label_value_table(document.grid, styles, [32 * mm, half - 32 * mm, 32 * mm, half - 32 * mm]))
        for block in document.blocks:
            flow.extend(_block_flowables(block, usable, styles, frame_height))
        return flow, letterhead is not None

    return _build_twice(
        _story,
        pagesize=A4,
        margin_side=_FORM_MARGIN_SIDE,
        title=f"{document.title} {document.number}".strip(),
        subject=document.subject,
        page_label=document.page_label,
        generated_label=document.generated_label,
        generated=document.generated,
        doc_type=document.doc_type,
        # A continuation sheet names the document and its number, then the project.
        running_title=" · ".join(
            part for part in (f"{document.title} {document.number}".strip(), document.project_label) if part
        ),
    )
