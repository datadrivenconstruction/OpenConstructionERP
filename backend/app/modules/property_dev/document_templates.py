# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Property Development PDF document templates.

Production-grade PDF generators for every sales-pipeline transition:

  * Reservation receipt (issued on deposit)
  * Sales-Purchase Agreement / SPA (multi-page, multi-buyer, jurisdiction-aware)
  * Payment receipt (issued per paid instalment)
  * Handover certificate (signed on completion)
  * Warranty certificate (structural + finishing)
  * No Objection Certificate / NOC (for resale)

Each generator is a pure function: input dicts/entities, output ``bytes``
starting with ``%PDF``. Layout uses ``reportlab`` (already a hard dep -
see ``regulatory.py`` and ``boq/pdf_export.py`` for prior usage).

Design notes
------------

* **Locale**: strings come from ``data/document_locales/{locale}.json``.
  Unknown locales fall back to English. RTL languages (currently only
  ``ar``) get a paragraph style with ``wordWrap='RTL'`` and ``alignment``
  flipped to ``TA_RIGHT``.

* **Jurisdiction clauses**: the SPA injects regulator-specific clauses
  from ``data/jurisdiction_clauses/{regulator}_{locale}.json`` (falls
  back to ``_en`` then ``NONE_en``). Placeholders in the clause text
  (``{escrow_account_no}``, etc.) are filled from the contract metadata
  blob or sensibly defaulted so the PDF is always renderable.

* **Watermark**: a faint ``DRAFT`` diagonal is drawn on every page
  whenever ``SalesContract.status`` is not in ``{'signed', 'completed'}``.

* **Header/footer**: a custom page handler draws the developer logo (or
  name fallback), the unit code (Phase-Block-Plot when the hierarchy is
  set), and a page-X-of-Y footer with the doc reference + generation
  timestamp.

* **Money formatting**: ``Decimal`` values are formatted with
  thousands-separators per the locale's BCP-47 root (``de`` → ``1.234,56``,
  ``en`` → ``1,234.56``, ``ru`` → ``1 234,56``, ``fr`` → ``1 234,56``). How
  many decimal places follow the separator is a question about the currency,
  not about the locale, and is answered by ``app.core.money``.

The generators have no DB / I/O - they take SQLAlchemy ORM instances
(or anything duck-compatible) plus a few primitives, and return bytes.
The service layer ``generate_document`` wires the right entities in.
"""

from __future__ import annotations

import html
import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.money import minor_units, money_quantum
from app.core.pdf_fonts import (
    BODY_FONT,
    BOLD_FONT,
    pdf_font_for_text,
    pdf_style_for_text,
    register_pdf_fonts,
)
from app.core.storage import find_existing_upload, module_uploads_dir

# These property documents (contracts, receipts, certificates) ship in every
# locale, including Cyrillic (ru/bg/uk). reportlab's built-in Helvetica is
# Latin-1 only and would render those as empty boxes, so swap in the bundled
# DejaVu Sans Unicode faces. Registration is idempotent and runs once.
register_pdf_fonts()

# ── Constants ───────────────────────────────────────────────────────────

#: All locales offered in the document-templates UI picker. Locales
#: without a dedicated translation JSON in ``data/document_locales/``
#: fall back to ``en.json`` automatically (see ``_load_locale``); the
#: list below stays in sync with the frontend's ``app/locales/*.ts``
#: catalogue so every UI language has at least an English-content
#: template option available rather than being silently dropped from
#: the picker. Adding a new translation = drop a ``<code>.json`` file
#: into ``data/document_locales/`` - no code change required.
SUPPORTED_LOCALES: tuple[str, ...] = (
    "en",
    "de",
    "ru",
    "fr",
    "ar",
    "es",
    "it",
    "pt",
    "pl",
    "nl",
    "tr",
    "zh",
    "ja",
    "ko",
    "cs",
    "da",
    "fi",
    "no",
    "sv",
    "hi",
    "vi",
    "th",
    "id",
    "ro",
    "bg",
    "hr",
    "mn",
)

#: RTL locales - paragraph wordWrap set to ``RTL`` and alignment flipped.
RTL_LOCALES: frozenset[str] = frozenset({"ar", "he", "fa", "ur"})

#: Native + English display names for every supported locale. Used by
#: the locale picker on the document-templates settings page so the
#: dropdown shows "Deutsch (de)" instead of a bare "DE" - without this
#: the picker reads like an ISO code dump.
LOCALE_DISPLAY_NAMES: dict[str, tuple[str, str]] = {
    "en": ("English", "English"),
    "de": ("Deutsch", "German"),
    "ru": ("Русский", "Russian"),
    "fr": ("Français", "French"),
    "ar": ("العربية", "Arabic"),
    "es": ("Español", "Spanish"),
    "it": ("Italiano", "Italian"),
    "pt": ("Português", "Portuguese"),
    "pl": ("Polski", "Polish"),
    "nl": ("Nederlands", "Dutch"),
    "tr": ("Türkçe", "Turkish"),
    "zh": ("中文", "Chinese"),
    "ja": ("日本語", "Japanese"),
    "ko": ("한국어", "Korean"),
    "cs": ("Čeština", "Czech"),
    "da": ("Dansk", "Danish"),
    "fi": ("Suomi", "Finnish"),
    "no": ("Norsk", "Norwegian"),
    "sv": ("Svenska", "Swedish"),
    "hi": ("हिन्दी", "Hindi"),
    "vi": ("Tiếng Việt", "Vietnamese"),
    "th": ("ไทย", "Thai"),
    "id": ("Bahasa Indonesia", "Indonesian"),
    "ro": ("Română", "Romanian"),
    "bg": ("Български", "Bulgarian"),
    "hr": ("Hrvatski", "Croatian"),
    "mn": ("Монгол", "Mongolian"),
}


def list_locale_status() -> list[dict[str, Any]]:
    """Locale entries with translation status for the settings UI.

    Returns one entry per locale in ``SUPPORTED_LOCALES``:
        {code, native_name, english_name, rtl, is_translated, key_count}

    ``is_translated`` is the honest signal - true iff the locale has a
    dedicated JSON file in ``data/document_locales/``. Untranslated
    locales are still listed (the renderer falls back to English so the
    PDF still renders), but the UI can mark them clearly so users don't
    pick a locale and get an English PDF without knowing why.

    ``key_count`` is the number of top-level + nested string leaves in
    that locale's JSON - used by the UI to flag partial translations
    (e.g. de.json with 12 keys when en.json has 80).
    """
    en_keys = _count_leaf_keys(_load_locale("en"))
    out: list[dict[str, Any]] = []
    for code in SUPPORTED_LOCALES:
        native, english = LOCALE_DISPLAY_NAMES.get(code, (code.upper(), code.upper()))
        bundled_fp = _LOCALE_DIR / f"{code}.json"
        bundled_exists = bundled_fp.exists()
        override_exists = locale_override_exists(code)
        # Translation source priority: override > bundled > none (EN
        # fallback). The UI shows a distinct badge for each.
        if override_exists:
            source: str = "override"
            key_count = _count_leaf_keys(_load_locale(code))
        elif bundled_exists:
            source = "bundled"
            key_count = _count_leaf_keys(_load_locale(code))
        else:
            source = "none"
            key_count = 0
        out.append(
            {
                "code": code,
                "native_name": native,
                "english_name": english,
                "rtl": code in RTL_LOCALES,
                "is_translated": override_exists or bundled_exists,
                "source": source,
                "key_count": key_count,
                "en_key_count": en_keys,
            }
        )
    return out


def _count_leaf_keys(blob: Any) -> int:
    """Recursive leaf count for translation-coverage progress bars."""
    if isinstance(blob, dict):
        return sum(_count_leaf_keys(v) for v in blob.values())
    if isinstance(blob, list):
        return sum(_count_leaf_keys(v) for v in blob)
    return 1 if isinstance(blob, str) else 0


#: Regulators we ship clause-blocks for. Anything else uses ``NONE``.
SUPPORTED_REGULATORS: tuple[str, ...] = (
    "RERA",
    "MAHARERA",
    "214_FZ",
    "CMA",
    "NONE",
)

logger = logging.getLogger(__name__)

#: Page margins (all sides). 25 mm matches the spec, and is the default the
#: workspace setting falls back to - see :func:`_page_margin_pt`.
PAGE_MARGIN_MM: float = 25.0


def _appearance() -> dict[str, object]:
    """The workspace document appearance, or an empty dict, never raising.

    Guarded and lazily imported for the same reason
    :mod:`app.core.pdf_branding` guards its own read: a document a buyer is
    waiting for must not be lost because a settings file could not be parsed.
    The underlying read is cached by file mtime, so calling this per page (the
    page handler does) costs a ``stat``.
    """
    try:
        from app.core.pdf_appearance import read_appearance

        data = read_appearance()
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - degrade to the spec defaults, never break a PDF
        logger.debug("Could not read document appearance; using the spec defaults", exc_info=True)
        return {}


def _page_margin_pt() -> float:
    """The configured page margin in points, defaulting to the 25 mm spec."""
    value = _appearance().get("margin_mm")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value) * mm
    return PAGE_MARGIN_MM * mm


def _page_size_pt() -> tuple[float, float]:
    """The configured page size in points, defaulting to A4."""
    try:
        from app.core.pdf_appearance import resolve_page_size

        return resolve_page_size(_appearance())
    except Exception:  # noqa: BLE001 - A4 is the documented default
        logger.debug("Could not resolve page size; using A4", exc_info=True)
        return (float(A4[0]), float(A4[1]))


def _doc_page_size(target: Any) -> tuple[float, float]:
    """The page size of a live doc or canvas, falling back to the configured one.

    reportlab spells it ``pagesize`` on a ``BaseDocTemplate`` and ``_pagesize``
    on a ``Canvas``; both are read here so the header, the watermark and the
    page number all measure the same page.
    """
    for attr in ("pagesize", "_pagesize"):
        size = getattr(target, attr, None)
        if isinstance(size, tuple | list) and len(size) == 2:
            try:
                return (float(size[0]), float(size[1]))
            except (TypeError, ValueError):
                break
    return _page_size_pt()


def _base_font_size() -> float:
    """The configured body size in points, defaulting to the 10 pt spec.

    Every other size in :func:`_styles` is derived from this one by the ratio
    it already had, so raising the body size scales the document instead of
    leaving the headings and the small print where they were.
    """
    value = _appearance().get("base_font_size")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return 10.0


#: Default validity for an NOC, in days.
DEFAULT_NOC_VALIDITY_DAYS: int = 30

_DATA_DIR = Path(__file__).resolve().parent / "data"
_LOCALE_DIR = _DATA_DIR / "document_locales"
_CLAUSE_DIR = _DATA_DIR / "jurisdiction_clauses"

#: User-uploaded locale overrides live here so a tenant can ship a fully
#: translated ``de.json`` without re-deploying the codebase. The
#: directory is created on first write. Override JSON is preferred over
#: the bundled one (see ``_load_locale``); the bundled version is the
#: read-only fallback.
#:
#: Anchored on the platform data dir. A bare ``Path("uploads")`` pointed at
#: whatever directory the process was started in, so restarting the service
#: from elsewhere silently un-shadowed every override a tenant had uploaded.
#:
#: Spelled once, as the sub-path below the uploads root, because the
#: back-compat lookup needs the same segments relative to a different root.
_LOCALE_OVERRIDE_SUBPATH = ("property_dev", "document_locales")
_LOCALE_OVERRIDE_DIR = module_uploads_dir(*_LOCALE_OVERRIDE_SUBPATH)


def _override_locale_path(locale: str) -> Path:
    """Resolve the absolute path an override locale JSON is WRITTEN to.

    The directory is created lazily - calling this never auto-writes a
    file, only computes where one would live.

    Args:
        locale: The locale code, e.g. ``de``.

    Returns:
        The absolute path under the active data-dir root.
    """
    return (_LOCALE_OVERRIDE_DIR / f"{locale}.json").resolve()


def _existing_override_locale_path(locale: str) -> Path | None:
    """Return the override JSON that actually exists, or ``None``.

    Reads probe the active data-dir root first and then the
    working-directory-relative tree earlier releases wrote to, so an override a
    tenant uploaded before the roots were anchored keeps shadowing the bundled
    translation instead of silently reverting the documents to English.

    Args:
        locale: The locale code, e.g. ``de``.

    Returns:
        An existing file, or ``None`` when no root holds one.
    """
    return find_existing_upload(Path(*_LOCALE_OVERRIDE_SUBPATH) / f"{locale}.json")


def locale_override_exists(locale: str) -> bool:
    """True iff a writable override file shadows the bundled locale."""
    return _existing_override_locale_path(locale) is not None


# ── Locale loader ───────────────────────────────────────────────────────


@lru_cache(maxsize=32)
def _load_locale(locale: str) -> dict[str, Any]:
    """Load the locale JSON; user override > bundled > English fallback."""
    override = _existing_override_locale_path(locale)
    if override is not None:
        try:
            return json.loads(override.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass  # fall through to bundled
    fp = _LOCALE_DIR / f"{locale}.json"
    if not fp.exists():
        fp = _LOCALE_DIR / "en.json"
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Never crash a PDF render on a locale-load failure.
        return {}


def write_locale_override(locale: str, blob: dict[str, Any]) -> None:
    """Persist a user-uploaded override JSON for ``locale``.

    Creates the override directory if needed. Invalidates the
    ``_load_locale`` cache so the next PDF render picks up the new copy.
    """
    if locale not in SUPPORTED_LOCALES:
        msg = f"Unsupported locale: {locale}"
        raise ValueError(msg)
    _LOCALE_OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
    path = _override_locale_path(locale)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    _load_locale.cache_clear()


def delete_locale_override(locale: str) -> bool:
    """Remove the override and revert to the bundled translation.

    Deletes whichever root actually holds the file. Deleting only from the
    active root would leave a legacy override in place, and ``_load_locale``
    would keep reading it - "revert to bundled" that reverts nothing.

    Returns True if a file was removed.
    """
    path = _existing_override_locale_path(locale)
    if path is None:
        return False
    path.unlink()
    _load_locale.cache_clear()
    return True


def _t(locale: str, dotted_key: str, fallback: str = "") -> str:
    """Translation helper.

    ``dotted_key`` walks the JSON: ``"reservation_receipt.headings.buyer"``.
    Unknown keys (and unknown locales) fall back to English, and finally
    to ``fallback``.
    """
    data = _load_locale(locale)
    parts = dotted_key.split(".")

    def _walk(d: dict[str, Any]) -> Any:
        cur: Any = d
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur

    val = _walk(data)
    if val is None and locale != "en":
        val = _walk(_load_locale("en"))
    if not isinstance(val, str):
        return fallback
    return val


# ── Money / number formatting ───────────────────────────────────────────


def _format_money(amount: Decimal | int | float | None, locale: str, currency_code: str | None) -> str:
    """Locale-aware thousands-separated string in the currency's own units.

    The two arguments answer two different questions and neither can answer
    the other's. ``locale`` picks the separators, because that is a habit of
    whoever reads the document. ``currency_code`` decides how many digits
    follow the decimal separator, because that is a property of the money:
    a forint printed with the fillér that left circulation in 1999 reads as
    an amount no payment can settle, and a Kuwaiti dinar printed without its
    third digit has quietly lost a fils that one can.

    The count comes from :func:`app.core.money.minor_units`, the single table
    in the platform that records a currency's subdivision. This renderer used
    to quantise to a ``Decimal("0.01")`` literal instead, which is the shape
    of the bug: a literal cannot know its currency. A blank or unregistered
    code takes that function's own two-decimal default rather than a guess
    made here.

    Args:
        amount: value to render. ``None`` gives an empty string.
        locale: BCP-47 root; only the separators are taken from it.
        currency_code: ISO 4217 code the amount is denominated in. May be
            blank when the record carries no currency.

    Returns:
        The grouped amount on its own. Callers append the currency code.
    """
    if amount is None:
        return ""
    try:
        d = Decimal(str(amount))
    except (ValueError, TypeError):
        return ""
    # Quantize to the currency's own minor unit without introducing
    # scientific notation. ROUND_HALF_UP is what every other money path in
    # the platform rounds with, so a printed figure agrees with the stored one.
    decimals = minor_units(currency_code)
    q = d.quantize(money_quantum(currency_code), rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    abs_q = -q if q < 0 else q
    int_part, _, frac_part = format(abs_q, "f").partition(".")
    thou_sep, dec_sep = _separators_for_locale(locale)
    grouped = _group_digits(int_part, _base_language(locale), thou_sep)
    if decimals == 0:
        # No subunit, so no separator either - a trailing "," on a forint
        # would read as a truncated number rather than a whole one.
        return f"{sign}{grouped}"
    return f"{sign}{grouped}{dec_sep}{frac_part}"


def _base_language(locale: str) -> str:
    """The BCP-47 root of *locale*, lowercased. English when nothing says."""
    return (locale or "en").split("-")[0].lower()


#: Languages whose readers do not group the integer part in uniform threes.
#:
#: The Indian system groups the last three digits and then in twos, so
#: 47657972.78 is written ``4,76,57,972.78`` and not ``47,657,972.78``. That is
#: not a stylistic preference about where the commas fall: ``lakh`` names the
#: sixth digit and ``crore`` the eighth, so the grouping is what lets a figure
#: be read aloud at all, and one grouped by threes has to be counted digit by
#: digit first. This renderer chunked the reversed integer in threes for every
#: locale, which no argument could change, so ``hi`` - offered above, with a
#: bundled Devanagari face and HarfBuzz shaping behind it - issued contracts
#: written the way nobody in that market writes one.
#:
#: Only ``hi`` of the 27 offered locales reads this way. Bengali and Urdu do
#: too and are not offered as document locales; each joins this set with its
#: translation rather than ahead of it.
_INDIAN_GROUPING: frozenset[str] = frozenset({"hi"})


def _group_digits(digits: str, base: str, thou_sep: str) -> str:
    """Punctuate *digits* with *thou_sep* the way *base*'s readers group them."""
    if base in _INDIAN_GROUPING and len(digits) > 3:
        head, last_three = digits[:-3], digits[-3:]
        pairs = [head[max(i - 2, 0) : i] for i in range(len(head), 0, -2)]
        return thou_sep.join([*reversed(pairs), last_three])
    rev = digits[::-1]
    chunks = [rev[i : i + 3] for i in range(0, len(rev), 3)]
    return thou_sep.join([c[::-1] for c in chunks][::-1])  # readable order


#: (thousands separator, decimal separator) per BCP-47 root: one row for every
#: entry in ``SUPPORTED_LOCALES``, measured rather than recalled.
#:
#: Each row is what ``Intl.NumberFormat(<root>)`` puts between the digits of
#: 1234567.89 - the same CLDR data every browser and phone in that market
#: already formats numbers with. The table this replaced named nine languages
#: and let the other eighteen fall through to the English pair, and for ten of
#: them that was wrong. Five (cs, fi, no, sv, bg) write a space and a comma.
#: Five more (da, vi, id, ro, hr) write a dot and a comma, and for those the
#: fall-through did not merely look foreign: their readers take ``,`` as the
#: decimal separator, so a contract saying ``47,657,972.78`` opens with a
#: figure that reads as forty-seven point six five seven. Polish had a row and
#: the row said ``.``, where Poland writes a space.
#:
#: Measured across the 27 offered locales, 12 were written wrongly: those
#: eleven, plus Hindi, whose separators were right and whose grouping was not.
#:
#: Every space here is U+00A0 and not the U+202F CLDR gives French. Both are
#: non-breaking spaces, no reader can tell them apart on a printed page, and
#: holding the table to one character keeps its font requirement to a codepoint
#: every bundled face carries - NotoSansDevanagari has U+00A0 and no U+202F.
#:
#: Arabic keeps Western digits and the separators CLDR pairs with them.
#: Arabic-Indic digits in a generated contract are a larger decision than a
#: separator table and are not made here.
_SEPARATORS: dict[str, tuple[str, str]] = {
    "ar": (",", "."),
    "bg": (" ", ","),
    "cs": (" ", ","),
    "da": (".", ","),
    "de": (".", ","),
    "en": (",", "."),
    "es": (".", ","),
    "fi": (" ", ","),
    "fr": (" ", ","),
    "hi": (",", "."),
    "hr": (".", ","),
    "id": (".", ","),
    "it": (".", ","),
    "ja": (",", "."),
    "ko": (",", "."),
    "mn": (",", "."),
    "nl": (".", ","),
    "no": (" ", ","),
    "pl": (" ", ","),
    "pt": (".", ","),
    "ro": (".", ","),
    "ru": (" ", ","),
    "sv": (" ", ","),
    "th": (",", "."),
    "tr": (".", ","),
    "vi": (".", ","),
    "zh": (",", "."),
}


def _separators_for_locale(locale: str) -> tuple[str, str]:
    """Return (thousand_sep, decimal_sep) for a locale (BCP-47 root).

    A locale with no row keeps the English pair, which is the fallback the
    words already take: ``_load_locale`` answers an untranslated locale with
    ``en.json``, so the separators and the sentences around them stay in one
    convention instead of pairing Danish punctuation with English prose.
    """
    return _SEPARATORS.get(_base_language(locale), (",", "."))


def _format_date(value: str | date | datetime | None, _locale: str) -> str:
    """ISO date string (YYYY-MM-DD). Locale-format intentionally avoided so
    the values remain unambiguous in international contracts."""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value)
    return s[:10] if len(s) >= 10 else s


# ── Style factory ───────────────────────────────────────────────────────


def _styles(locale: str) -> dict[str, ParagraphStyle]:
    """Build the ParagraphStyle family for the given locale.

    Every point size below is the spec size multiplied by ``_scale``, the ratio
    between the workspace's configured body size and the 10 pt this document
    was designed at. Scaling the whole family rather than only the body keeps
    the hierarchy intact: a workspace that asks for larger print gets larger
    headings and larger small print too, instead of a title that no longer
    stands out from the paragraph under it.
    """
    _scale = _base_font_size() / 10.0
    rtl = locale in RTL_LOCALES
    base = getSampleStyleSheet()
    word_wrap = "RTL" if rtl else None
    align_body = TA_RIGHT if rtl else TA_LEFT

    title = ParagraphStyle(
        "OE_Title",
        parent=base["Title"],
        fontName=BOLD_FONT,
        fontSize=20 * _scale,
        leading=24 * _scale,
        alignment=TA_CENTER,
        wordWrap=word_wrap,
        spaceAfter=6,
    )
    subtitle = ParagraphStyle(
        "OE_Subtitle",
        parent=base["Heading2"],
        fontName=BODY_FONT,
        fontSize=12 * _scale,
        leading=16 * _scale,
        alignment=TA_CENTER,
        wordWrap=word_wrap,
        textColor=colors.HexColor("#4b5563"),
    )
    heading = ParagraphStyle(
        "OE_Heading",
        parent=base["Heading3"],
        fontName=BOLD_FONT,
        fontSize=12 * _scale,
        leading=15 * _scale,
        alignment=align_body,
        wordWrap=word_wrap,
        spaceBefore=10,
        spaceAfter=4,
        textColor=colors.HexColor("#1f2937"),
    )
    body = ParagraphStyle(
        "OE_Body",
        parent=base["Normal"],
        fontName=BODY_FONT,
        fontSize=10 * _scale,
        leading=14 * _scale,
        alignment=align_body,
        wordWrap=word_wrap,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "OE_Small",
        parent=body,
        fontSize=8.5 * _scale,
        leading=11 * _scale,
        textColor=colors.HexColor("#4b5563"),
    )
    label = ParagraphStyle(
        "OE_Label",
        parent=body,
        fontName=BOLD_FONT,
        textColor=colors.HexColor("#374151"),
    )
    # The header row of every table drawn with _grid_table_style. That style
    # fills the row #1f2937 and asks for white text, but a TableStyle TEXTCOLOR
    # cannot reach a cell holding a Paragraph, so the row took the label colour
    # instead and the headings of the parties table, the instalments table and
    # the move-in checklist were drawn #374151 on #1f2937.
    grid_header = ParagraphStyle(
        "OE_GridHeader",
        parent=body,
        fontName=BOLD_FONT,
        textColor=colors.white,
    )
    clause = ParagraphStyle(
        "OE_Clause",
        parent=body,
        fontSize=9.5 * _scale,
        leading=13 * _scale,
        spaceAfter=6,
    )
    clause_heading = ParagraphStyle(
        "OE_ClauseHeading",
        parent=heading,
        fontSize=10.5 * _scale,
        leading=13 * _scale,
        spaceBefore=6,
        spaceAfter=2,
    )
    return {
        "title": title,
        "subtitle": subtitle,
        "heading": heading,
        "body": body,
        "small": small,
        "label": label,
        "grid_header": grid_header,
        "clause": clause,
        "clause_heading": clause_heading,
    }


def _p(text: str, style: ParagraphStyle, *, markup: bool = False) -> Paragraph:
    """Build a paragraph faced for the script its own text is written in.

    Every paragraph in these documents goes through here. The template chrome
    follows the document locale, but the free text does not: buyer and
    developer names, plot labels, room and item names and clause overrides are
    whatever the parties are actually called, so a Chinese name turns up in an
    English or German contract as readily as in a Chinese one. The bundled
    DejaVu face has no Han glyph at all and draws those as empty boxes.

    The face is chosen per string rather than per document for that reason. A
    document-level switch keyed on ``locale`` would miss the Chinese buyer in
    an English contract and would also mis-face the whole of a Chinese-locale
    document, which falls back to English text when no translation ships.

    Text is escaped by default. A paragraph takes a small HTML-like markup, so
    an unescaped value is parsed rather than printed, and every way that goes
    wrong here is silent: nothing raises, the file still opens and still looks
    plausible. A name is truncated at an angle bracket, an ampersand followed
    by a letter has a semicolon injected after the next word ("R&D Tower"
    draws as "R&D; Tower"), and a literal "&amp;" in the data decodes to a
    bare ampersand. Only an ampersand followed by a space survives untouched,
    which is why the shipped clause headings ("Governing Law & Jurisdiction")
    have never shown the fault.

    Args:
        text: paragraph text. Escaped unless ``markup`` is set.
        style: base style, taken from :func:`_styles`. It is never mutated,
            only cloned when the text needs the other face.
        markup: the caller wrote reportlab inline markup and wants it parsed.
            Callers that set this are responsible for escaping any value they
            interpolate into that markup themselves, since the whole string is
            handed to the parser. Markup is ASCII, so it never triggers the
            face switch on its own.

    Returns:
        A paragraph bound to a style that can draw ``text``.
    """
    # The face is chosen from the text as written and the escaped form is what
    # gets drawn. Escaping only ever adds ASCII, so the two cannot disagree
    # about which face is needed, and asking the original keeps this the same
    # decision the direct Paragraph callers make.
    return Paragraph(text if markup else html.escape(text), pdf_style_for_text(style, text))


# ── Page layout (header / footer / watermark / page-numbers) ────────────


class _PageContext:
    """Per-render context used by the page-handler closure."""

    def __init__(
        self,
        *,
        developer_name: str,
        developer_logo_url: str | None,
        unit_code: str,
        doc_ref: str,
        locale: str,
        watermark: bool,
    ) -> None:
        self.developer_name = developer_name or ""
        self.developer_logo_url = developer_logo_url or None
        self.unit_code = unit_code or ""
        self.doc_ref = doc_ref or ""
        self.locale = locale
        self.watermark = watermark
        self.generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        # We always recount pages with a second pass via NumberedCanvas.


def _build_page_handler(ctx: _PageContext):
    """Return a (canvas, doc) -> None callable used by reportlab on each page."""

    def _draw(canvas: Canvas, doc: BaseDocTemplate) -> None:
        canvas.saveState()

        # Header - developer + unit code top-right. Geometry is read off the
        # live doc rather than from the module constants, so a workspace that
        # picked Letter or a wider margin gets a header that lines up with its
        # own body instead of one drawn at A4 coordinates.
        page_w, page_h = _doc_page_size(doc)
        left = float(getattr(doc, "leftMargin", PAGE_MARGIN_MM * mm))
        right_edge = page_w - float(getattr(doc, "rightMargin", PAGE_MARGIN_MM * mm))
        header_y = page_h - (left - 4 * mm)
        developer = (ctx.developer_name or "OpenConstructionERP")[:80]
        canvas.setFont(pdf_font_for_text(developer, bold=True), 14)
        canvas.setFillColor(colors.HexColor("#111827"))
        canvas.drawString(left, header_y, developer)

        if ctx.unit_code:
            canvas.setFont(pdf_font_for_text(ctx.unit_code), 10)
            canvas.setFillColor(colors.HexColor("#374151"))
            canvas.drawRightString(right_edge, header_y, ctx.unit_code)

        # Thin separator line under header.
        canvas.setStrokeColor(colors.HexColor("#d1d5db"))
        canvas.setLineWidth(0.4)
        rule_y = page_h - left + 1 * mm
        canvas.line(left, rule_y, right_edge, rule_y)

        # Watermark - drawn behind content.
        if ctx.watermark:
            canvas.saveState()
            canvas.translate(page_w / 2, page_h / 2)
            canvas.rotate(45)
            canvas.setFillColor(colors.Color(0.78, 0.27, 0.27, alpha=0.18))
            text = _t(ctx.locale, "common.watermark_draft", "DRAFT")
            canvas.setFont(pdf_font_for_text(text, bold=True), 96)
            canvas.drawCentredString(0, 0, text)
            canvas.restoreState()

        # Footer - doc ref + page X (real count appended by NumberedCanvas)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        gen_str = _t(ctx.locale, "common.generated_at", "Generated {timestamp} UTC").replace(
            "{timestamp}", ctx.generated_at
        )
        ref_label = _t(ctx.locale, "common.doc_ref", "Doc. Ref")
        ref_str = f"{ref_label}: {ctx.doc_ref}" if ctx.doc_ref else ""

        # Faced separately: an uploaded locale override can translate the
        # footer labels while the document reference stays ASCII, so the two
        # strings do not always want the same face.
        footer_y = left - 10 * mm
        canvas.setFont(pdf_font_for_text(ref_str), 8)
        canvas.drawString(left, footer_y, ref_str)
        canvas.setFont(pdf_font_for_text(gen_str), 8)
        canvas.drawCentredString(page_w / 2, footer_y, gen_str)
        # Right-side page label - final "X of Y" is injected on second pass.
        # We draw a placeholder that NumberedCanvas will overwrite.
        canvas.restoreState()

    return _draw


class _NumberedCanvas(Canvas):
    """Two-pass canvas that knows total page count when drawing."""

    def __init__(self, *args: Any, page_locale: str = "en", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_pages: list[dict[str, Any]] = []
        self._locale = page_locale

    def showPage(self) -> None:  # noqa: N802 - reportlab API
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        n_pages = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._draw_page_number(n_pages)
            super().showPage()
        super().save()

    def _draw_page_number(self, n_pages: int) -> None:
        if not _appearance().get("show_page_numbers", True):
            # The workspace files these inside a bundle that paginates itself.
            # Suppressed here as well as in the shared footer, so the setting
            # does not leave one of the two numbers behind.
            return
        self.saveState()
        self.setFillColor(colors.HexColor("#6b7280"))
        template = _t(self._locale, "common.page_of", "Page {page} of {total}")
        label = template.replace("{page}", str(self._pageNumber)).replace("{total}", str(n_pages))
        self.setFont(pdf_font_for_text(label), 8)
        page_w, _ = _doc_page_size(self)
        margin = _page_margin_pt()
        self.drawRightString(page_w - margin, margin - 10 * mm, label)
        self.restoreState()


# ── Common attribute extractors ────────────────────────────────────────


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Safe getattr for ORM rows OR dicts - both shapes show up in tests."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _development_name(development: Any) -> str:
    return str(_attr(development, "name", "") or "")


def _development_logo(development: Any) -> str | None:
    meta = _attr(development, "metadata_", None) or _attr(development, "metadata", None)
    if isinstance(meta, dict):
        url = meta.get("logo_url")
        if isinstance(url, str) and url.strip():
            return url
    # Direct attribute fallback.
    url = _attr(development, "logo_url", None)
    return url if isinstance(url, str) and url else None


def _regulator(development: Any) -> str:
    meta = _attr(development, "metadata_", None) or _attr(development, "metadata", None)
    reg = None
    if isinstance(meta, dict):
        reg = meta.get("regulator")
    reg = (reg or _attr(development, "regulator", None) or "NONE").upper()
    if reg not in SUPPORTED_REGULATORS:
        return "NONE"
    return reg


def _unit_code(plot: Any, development: Any = None) -> str:
    """Phase-Block-Plot if hierarchy set, else plot.plot_number."""
    parts: list[str] = []
    block_code = None
    phase_code = None
    meta = _attr(plot, "metadata_", None) or _attr(plot, "metadata", None) or {}
    if isinstance(meta, dict):
        phase_code = meta.get("phase_code")
        block_code = meta.get("block_code")
    if phase_code:
        parts.append(str(phase_code))
    if block_code:
        parts.append(str(block_code))
    plot_number = _attr(plot, "plot_number", None) or _attr(plot, "code", None)
    if plot_number:
        parts.append(str(plot_number))
    if not parts and development is not None:
        parts.append(_attr(development, "code", "") or "")
    return "-".join(p for p in parts if p)


def _is_draft(contract: Any) -> bool:
    status = (_attr(contract, "status", "") or "").lower()
    return status not in {"signed", "completed", "executed"}


def _doc_ref(prefix: str, *, entity: Any) -> str:
    """Stable, human-friendly reference based on entity ID."""
    ent_id = _attr(entity, "id", None)
    if isinstance(ent_id, uuid.UUID):
        short = ent_id.hex[:8].upper()
    elif isinstance(ent_id, str):
        short = ent_id.replace("-", "")[:8].upper()
    else:
        short = uuid.uuid4().hex[:8].upper()
    return f"{prefix}-{short}"


# ── Doc builder boilerplate ─────────────────────────────────────────────


def _build_doc(
    buf: BytesIO,
    *,
    title: str,
    author: str,
    subject: str,
    keywords: list[str],
) -> tuple[BaseDocTemplate, Frame]:
    margin = _page_margin_pt()
    doc = BaseDocTemplate(
        buf,
        pagesize=_page_size_pt(),
        leftMargin=margin,
        rightMargin=margin,
        # The extra top and bottom room is the band the page handler draws the
        # header and footer into, so it is added to whatever margin was chosen
        # rather than being folded into a fixed number.
        topMargin=margin + 5 * mm,
        bottomMargin=margin + 10 * mm,
        title=title,
        author=author,
        subject=subject,
        keywords=", ".join(keywords),
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="content",
        showBoundary=0,
    )
    return doc, frame


def _render(
    doc: BaseDocTemplate,
    frame: Frame,
    story: list[Any],
    ctx: _PageContext,
    buf: BytesIO,
) -> bytes:
    """Build the document with header/footer + numbered canvas and return bytes."""
    handler = _build_page_handler(ctx)
    template = PageTemplate(id="default", frames=[frame], onPage=handler)
    doc.addPageTemplates([template])

    locale = ctx.locale

    class _LocalisedCanvas(_NumberedCanvas):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, page_locale=locale, **kw)

    doc.build(story, canvasmaker=_LocalisedCanvas)
    return buf.getvalue()


# ── Table style helpers ────────────────────────────────────────────────


def _kv_table_style() -> TableStyle:
    return TableStyle(
        [
            ("FONTNAME", (0, 0), (0, -1), BOLD_FONT),
            ("FONTNAME", (1, 0), (1, -1), BODY_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#374151")),
            ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#111827")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ]
    )


def _grid_table_style() -> TableStyle:
    return TableStyle(
        [
            # Fills, rules and padding only. Every cell in these tables is a
            # Paragraph and carries its own face, size, colour and alignment,
            # so a TEXTCOLOR, FONTNAME, FONTSIZE or ALIGN command here would
            # describe a row that nothing draws. The header's white is on
            # styles["grid_header"] instead.
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f9fafb"), colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
    )


# ════════════════════════════════════════════════════════════════════════
#  Generator 1 - Reservation Receipt
# ════════════════════════════════════════════════════════════════════════


def render_reservation_receipt_pdf(
    reservation: Any,
    plot: Any,
    development: Any,
    buyers: list[Any],
    locale: str = "en",
) -> bytes:
    """Receipt issued when a buyer reserves a plot. Single A4 page."""
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("RES", entity=reservation)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "reservation_receipt.title", "Reservation Receipt"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"Reservation {_attr(reservation, 'reservation_number', '')}",
        keywords=["reservation", "property", "receipt", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=False,  # Receipt itself is final - issued on payment
    )

    story: list[Any] = [
        _p(_t(locale, "reservation_receipt.title", "Reservation Receipt"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(
            _t(
                locale,
                "reservation_receipt.intro",
                "This receipt confirms reservation of the property described below.",
            ),
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        _p(_t(locale, "reservation_receipt.headings.plot_details", "Plot Details"), styles["heading"]),
    ]

    # KV table - buyer / property / amounts.
    buyer_lines = "<br/>".join(
        f"{_attr(b, 'full_name', '')} ({_attr(b, 'email', '')})"
        for b in (buyers or [])
        if _attr(b, "full_name", "") or _attr(b, "email", "")
    )

    ccy = _attr(reservation, "currency", "") or _attr(plot, "currency", "") or ""
    deposit = _attr(reservation, "deposit_amount", Decimal("0"))
    expires_at = _attr(reservation, "expires_at", None)
    cooling_until = _attr(reservation, "cooling_off_until", None)
    cooling_days = _attr(reservation, "cooling_off_days", 0)

    rows = [
        [
            _p(_t(locale, "reservation_receipt.headings.reservation_number", "Reservation No."), styles["label"]),
            _p(str(_attr(reservation, "reservation_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "reservation_receipt.headings.buyer", "Buyer"), styles["label"]),
            _p(buyer_lines or "-", styles["body"]),
        ],
        [
            _p(_t(locale, "reservation_receipt.headings.property", "Property"), styles["label"]),
            _p(
                f"{_development_name(development)} - "
                f"{_attr(plot, 'plot_number', '')} "
                f"({_attr(plot, 'area_m2', '')} m²)",
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "reservation_receipt.headings.amount_paid", "Amount Paid"), styles["label"]),
            _p(f"{_format_money(deposit, locale, ccy)} {ccy}".strip(), styles["body"]),
        ],
        [
            _p(_t(locale, "reservation_receipt.headings.cooling_off", "Cooling-off Period"), styles["label"]),
            _p(
                _t(
                    locale, "reservation_receipt.cooling_off_text", "{days} days from receipt of this document."
                ).replace("{days}", str(int(cooling_days or 0))),
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "reservation_receipt.headings.valid_until", "Valid Until"), styles["label"]),
            _p(
                _format_date(expires_at or cooling_until, locale) or "-",
                styles["body"],
            ),
        ],
    ]
    tbl = Table(rows, colWidths=[55 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())
    story.append(tbl)

    story.extend(
        [
            Spacer(1, 6 * mm),
            _p(_t(locale, "reservation_receipt.headings.next_step", "Next Step"), styles["heading"]),
            _p(
                _t(
                    locale, "reservation_receipt.next_step_text", "Within {days} days the buyer must sign the SPA."
                ).replace("{days}", str(int(cooling_days or 0))),
                styles["body"],
            ),
            Spacer(1, 6 * mm),
            _p(_t(locale, "reservation_receipt.footer_note", ""), styles["small"]),
            Spacer(1, 10 * mm),
            _p(
                f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
                styles["body"],
            ),
        ]
    )

    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 2 - Sales-Purchase Agreement (SPA)
# ════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=64)
def _load_clauses(regulator: str, locale: str) -> dict[str, Any]:
    """Pull jurisdiction clauses with graceful fall-through.

    Tries both the underscore-bearing form (``214_FZ``) and the compact
    form (``214FZ``) because both spellings are commonly used in our
    metadata (the migration to fully-uppercase canonical regulator IDs
    is still in progress).
    """
    compact = regulator.replace("_", "")
    candidates = [
        f"{regulator}_{locale}",
        f"{compact}_{locale}",
        f"{regulator}_en",
        f"{compact}_en",
        "NONE_en",
    ]
    for cand in candidates:
        fp = _CLAUSE_DIR / f"{cand}.json"
        if fp.exists():
            try:
                return json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return {"regulator": "NONE", "title": "General Terms", "clauses": []}


def _resolve_clause_placeholders(text: str, contract: Any, development: Any) -> str:
    """Fill in {escrow_account_no}, {completion_date}, ... from metadata."""
    meta_c = _attr(contract, "metadata_", None) or _attr(contract, "metadata", None) or {}
    meta_d = _attr(development, "metadata_", None) or _attr(development, "metadata", None) or {}
    merged: dict[str, Any] = {}
    if isinstance(meta_d, dict):
        merged.update(meta_d)
    if isinstance(meta_c, dict):
        merged.update(meta_c)

    defaults = {
        "rera_registration_no": str(merged.get("rera_registration_no", "TBD")),
        "maharera_registration_no": str(merged.get("maharera_registration_no", "TBD")),
        "ddu_registration_no": str(merged.get("ddu_registration_no", "TBD")),
        "mof_approval_no": str(merged.get("mof_approval_no", "TBD")),
        "escrow_account_no": str(merged.get("escrow_account_no", "TBD")),
        "escrow_bank": str(merged.get("escrow_bank", "TBD")),
        "escrow_bank_inn": str(merged.get("escrow_bank_inn", "TBD")),
        "fund_contribution_amount": str(merged.get("fund_contribution_amount", "0")),
        "completion_date": str(merged.get("completion_date") or _attr(development, "completion_date", "") or "TBD"),
        "carpet_area_m2": str(merged.get("carpet_area_m2", "TBD")),
        "jurisdiction_seat": str(merged.get("jurisdiction_seat", "TBD")),
    }
    result = text
    for k, v in defaults.items():
        result = result.replace("{" + k + "}", v or "TBD")
    return result


def render_sales_contract_pdf(
    contract: Any,
    payment_schedule: Any,
    instalments: list[Any],
    parties: list[Any],
    plot: Any,
    development: Any,
    locale: str = "en",
    *,
    buyer_lookup: dict[Any, Any] | None = None,
) -> bytes:
    """Multi-page SPA. Multi-buyer aware. Jurisdiction-clause auto-inject.

    ``buyer_lookup`` (optional) maps buyer_id → Buyer ORM row so we can
    name parties without an N+1. When absent, parties show only the role
    and ownership percentage.
    """
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("SPA", entity=contract)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "sales_contract.title", "Sale-Purchase Agreement"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"SPA {_attr(contract, 'contract_number', '')}",
        keywords=[
            "spa",
            "sales",
            "contract",
            "property",
            doc_ref,
            str(_attr(contract, "contract_number", "")),
        ],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(contract),
    )

    contract_number = _attr(contract, "contract_number", "") or ""
    subtitle_tpl = _t(locale, "sales_contract.subtitle", "Agreement No. {number}")
    subtitle = subtitle_tpl.replace("{number}", str(contract_number))

    story: list[Any] = [
        _p(_t(locale, "sales_contract.title", "Sale-Purchase Agreement"), styles["title"]),
        _p(subtitle, styles["subtitle"]),
        Spacer(1, 6 * mm),
        _p(_t(locale, "sales_contract.preamble", ""), styles["body"]),
        Spacer(1, 4 * mm),
    ]

    # ── Parties section ──
    story.append(_p(_t(locale, "sales_contract.headings.parties", "Parties to the Agreement"), styles["heading"]))
    story.append(_p(_t(locale, "sales_contract.parties_intro", ""), styles["body"]))

    party_rows: list[list[Any]] = [
        [
            _p(_t(locale, "sales_contract.party_columns.name", "Name"), styles["grid_header"]),
            _p(_t(locale, "sales_contract.party_columns.role", "Role"), styles["grid_header"]),
            _p(_t(locale, "sales_contract.party_columns.ownership_pct", "Ownership %"), styles["grid_header"]),
            _p(_t(locale, "sales_contract.party_columns.email", "Email"), styles["grid_header"]),
        ]
    ]
    total_pct = Decimal("0")
    for p in parties or []:
        buyer_id = _attr(p, "buyer_id", None)
        buyer = (buyer_lookup or {}).get(buyer_id) if buyer_lookup else None
        name = _attr(buyer, "full_name", "") or _attr(p, "full_name", "") or "-"
        email = _attr(buyer, "email", "") or _attr(p, "email", "") or ""
        role = _attr(p, "party_role", "primary") or "primary"
        pct = _attr(p, "ownership_pct", Decimal("0")) or Decimal("0")
        try:
            total_pct += Decimal(str(pct))
        except (ValueError, TypeError):
            pass
        party_rows.append(
            [
                _p(str(name), styles["body"]),
                _p(str(role), styles["body"]),
                _p(f"{pct}%", styles["body"]),
                _p(str(email), styles["body"]),
            ]
        )

    if len(party_rows) > 1:
        tbl_parties = Table(
            party_rows,
            colWidths=[55 * mm, 30 * mm, 25 * mm, 50 * mm],
            repeatRows=1,
        )
        tbl_parties.setStyle(_grid_table_style())
        story.append(tbl_parties)
        if total_pct and total_pct != Decimal("100"):
            story.append(
                _p(
                    f"Total ownership: {total_pct}%",
                    styles["small"],
                )
            )

    # ── Property section ──
    story.extend(
        [
            Spacer(1, 4 * mm),
            _p(_t(locale, "sales_contract.headings.property", "The Property"), styles["heading"]),
        ]
    )
    prop_rows = [
        [
            _p(_t(locale, "sales_contract.property_columns.plot_number", "Plot Number"), styles["label"]),
            _p(str(_attr(plot, "plot_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "sales_contract.property_columns.development", "Development"), styles["label"]),
            _p(_development_name(development), styles["body"]),
        ],
        [
            _p(_t(locale, "sales_contract.property_columns.area_m2", "Area (m²)"), styles["label"]),
            _p(str(_attr(plot, "area_m2", "-")), styles["body"]),
        ],
    ]
    house_type_label = _attr(plot, "house_type_label", None)
    if house_type_label:
        prop_rows.append(
            [
                _p(_t(locale, "sales_contract.property_columns.house_type", "House Type"), styles["label"]),
                _p(str(house_type_label), styles["body"]),
            ]
        )
    tbl_prop = Table(prop_rows, colWidths=[55 * mm, 100 * mm])
    tbl_prop.setStyle(_kv_table_style())
    story.append(tbl_prop)

    # ── Price section ──
    story.extend(
        [
            Spacer(1, 4 * mm),
            _p(_t(locale, "sales_contract.headings.price", "Purchase Price"), styles["heading"]),
        ]
    )
    ccy = _attr(contract, "currency", "") or ""
    total_value = _attr(contract, "total_value", Decimal("0"))
    story.append(
        _p(
            f"<b>{html.escape(_t(locale, 'sales_contract.price_label', 'Total Purchase Price'))}</b>: "
            f"{_format_money(total_value, locale, ccy)} {html.escape(ccy)}".strip(),
            styles["body"],
            markup=True,
        )
    )

    breakdown = _attr(contract, "total_price_breakdown", None) or {}
    if isinstance(breakdown, dict) and breakdown:
        story.append(_p(_t(locale, "sales_contract.breakdown_label", "Price Breakdown"), styles["label"]))
        brk_rows: list[list[Any]] = []
        for key in ("base", "vat", "stamp_duty", "legal_fees", "options_value", "discounts"):
            if key in breakdown:
                brk_rows.append(
                    [
                        _p(key.replace("_", " ").title(), styles["body"]),
                        _p(
                            f"{_format_money(breakdown.get(key) or 0, locale, ccy)} {ccy}".strip(),
                            styles["body"],
                        ),
                    ]
                )
        if brk_rows:
            tbl_brk = Table(brk_rows, colWidths=[80 * mm, 75 * mm])
            tbl_brk.setStyle(_kv_table_style())
            story.append(tbl_brk)

    # ── Payment Schedule + Instalments ──
    if instalments:
        story.extend(
            [
                Spacer(1, 4 * mm),
                _p(_t(locale, "sales_contract.headings.instalments", "Instalments"), styles["heading"]),
            ]
        )
        inst_rows: list[list[Any]] = [
            [
                _p(_t(locale, "sales_contract.instalment_columns.sequence", "#"), styles["grid_header"]),
                _p(_t(locale, "sales_contract.instalment_columns.milestone", "Milestone"), styles["grid_header"]),
                _p(_t(locale, "sales_contract.instalment_columns.due_date", "Due Date"), styles["grid_header"]),
                _p(_t(locale, "sales_contract.instalment_columns.amount", "Amount"), styles["grid_header"]),
                _p(_t(locale, "sales_contract.instalment_columns.currency", "Currency"), styles["grid_header"]),
            ]
        ]
        sched_ccy = _attr(payment_schedule, "currency", "") or ccy
        for inst in instalments:
            inst_rows.append(
                [
                    _p(str(_attr(inst, "sequence", "")), styles["body"]),
                    _p(str(_attr(inst, "milestone_label", "") or _attr(inst, "milestone_event", "")), styles["body"]),
                    _p(_format_date(_attr(inst, "due_date", None), locale), styles["body"]),
                    _p(_format_money(_attr(inst, "amount", Decimal("0")), locale, sched_ccy), styles["body"]),
                    _p(str(sched_ccy), styles["body"]),
                ]
            )
        tbl_inst = Table(
            inst_rows,
            colWidths=[12 * mm, 60 * mm, 28 * mm, 35 * mm, 25 * mm],
            repeatRows=1,
        )
        tbl_inst.setStyle(_grid_table_style())
        story.append(tbl_inst)

    # ── Jurisdiction clauses ──
    regulator = _regulator(development)
    clause_data = _load_clauses(regulator, locale)
    story.extend(
        [
            PageBreak(),
            _p(_t(locale, "sales_contract.headings.regulatory", "Regulatory Disclosures"), styles["heading"]),
            _p(
                f"<b>{html.escape(str(clause_data.get('title', '') or ''))}</b>",
                styles["subtitle"],
                markup=True,
            ),
            _p(clause_data.get("intro", "") or "", styles["body"]),
            Spacer(1, 3 * mm),
        ]
    )
    for clause in clause_data.get("clauses", []) or []:
        story.append(
            KeepTogether(
                [
                    _p(str(clause.get("heading", "") or ""), styles["clause_heading"]),
                    _p(
                        _resolve_clause_placeholders(
                            str(clause.get("text", "") or ""),
                            contract,
                            development,
                        ),
                        styles["clause"],
                    ),
                ]
            )
        )

    # ── Signatures ──
    place = _attr(contract, "place", None) or "________________"
    signing_date = _format_date(_attr(contract, "signing_date", None), locale) or "________________"
    note_tpl = _t(locale, "sales_contract.signature_note", "Signed in {place} on {date}.")
    note = note_tpl.replace("{place}", place).replace("{date}", signing_date)
    story.extend(
        [
            PageBreak(),
            _p(_t(locale, "sales_contract.headings.signatures", "Signatures"), styles["heading"]),
            _p(note, styles["body"]),
            Spacer(1, 14 * mm),
            Table(
                [
                    [
                        _p(
                            f"{html.escape(_t(locale, 'common.buyer_signature', 'Buyer Signature'))}<br/>"
                            f"________________________________",
                            styles["body"],
                            markup=True,
                        ),
                        _p(
                            f"{html.escape(_t(locale, 'common.developer_signature', 'Developer Signature'))}<br/>"
                            f"________________________________",
                            styles["body"],
                            markup=True,
                        ),
                    ]
                ],
                colWidths=[75 * mm, 75 * mm],
            ),
        ]
    )

    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 3 - Payment Receipt
# ════════════════════════════════════════════════════════════════════════


def render_payment_receipt_pdf(
    instalment: Any,
    sales_contract: Any,
    payment_method: str,
    payment_ref: str | None,
    locale: str = "en",
    *,
    plot: Any = None,
    development: Any = None,
) -> bytes:
    """Receipt for a paid instalment. Single A4 page."""
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("PAY", entity=instalment)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "payment_receipt.title", "Payment Receipt"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"Payment for SPA {_attr(sales_contract, 'contract_number', '')}",
        keywords=["payment", "receipt", "instalment", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development) if plot is not None else "",
        doc_ref=doc_ref,
        locale=locale,
        watermark=False,
    )

    ccy = _attr(sales_contract, "currency", "") or ""
    amount_paid = _attr(instalment, "amount_paid", None) or _attr(instalment, "amount", Decimal("0"))
    outstanding = Decimal("0")
    try:
        outstanding = Decimal(str(_attr(instalment, "amount", "0"))) - Decimal(
            str(_attr(instalment, "amount_paid", "0") or "0")
        )
    except (ValueError, TypeError):
        outstanding = Decimal("0")

    rows = [
        [
            _p(_t(locale, "payment_receipt.headings.spa_ref", "Agreement No."), styles["label"]),
            _p(str(_attr(sales_contract, "contract_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "payment_receipt.headings.instalment", "Instalment"), styles["label"]),
            _p(f"#{_attr(instalment, 'sequence', '')}", styles["body"]),
        ],
        [
            _p(_t(locale, "payment_receipt.headings.milestone", "Milestone"), styles["label"]),
            _p(
                str(_attr(instalment, "milestone_label", "") or _attr(instalment, "milestone_event", "")),
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "payment_receipt.headings.amount_paid", "Amount Paid"), styles["label"]),
            _p(
                f"{_format_money(amount_paid, locale, ccy)} {ccy}".strip(),
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "payment_receipt.headings.payment_method", "Payment Method"), styles["label"]),
            _p(str(payment_method or "-"), styles["body"]),
        ],
        [
            _p(_t(locale, "payment_receipt.headings.payment_ref", "Payment Reference"), styles["label"]),
            _p(str(payment_ref or "-"), styles["body"]),
        ],
        [
            _p(_t(locale, "payment_receipt.headings.paid_at", "Paid On"), styles["label"]),
            _p(
                _format_date(_attr(instalment, "paid_at", None), locale) or "-",
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "payment_receipt.headings.outstanding", "Outstanding Balance"), styles["label"]),
            _p(
                f"{_format_money(outstanding, locale, ccy)} {ccy}".strip(),
                styles["body"],
            ),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        _p(_t(locale, "payment_receipt.title", "Payment Receipt"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "payment_receipt.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 8 * mm),
        _p(_t(locale, "payment_receipt.footer_note", ""), styles["small"]),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 4 - Handover Certificate
# ════════════════════════════════════════════════════════════════════════


def render_handover_certificate_pdf(
    handover: Any,
    sales_contract: Any,
    snag_count: int,
    plot: Any,
    development: Any,
    locale: str = "en",
) -> bytes:
    """Certificate of handover - buyer signs to accept the unit."""
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("HND", entity=handover)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "handover_certificate.title", "Certificate of Handover"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"Handover for SPA {_attr(sales_contract, 'contract_number', '')}",
        keywords=["handover", "certificate", "property", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(sales_contract),
    )

    rows = [
        [
            _p(_t(locale, "handover_certificate.headings.spa_ref", "Agreement No."), styles["label"]),
            _p(str(_attr(sales_contract, "contract_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "handover_certificate.headings.completed_at", "Handover Date"), styles["label"]),
            _p(
                _format_date(_attr(handover, "completed_at", None), locale)
                or _format_date(_attr(handover, "scheduled_at", None), locale)
                or "-",
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "handover_certificate.headings.snag_count", "Open Snags"), styles["label"]),
            _p(str(int(snag_count or 0)), styles["body"]),
        ],
        [
            _p(_t(locale, "handover_certificate.headings.keys_handed_over", "Keys Handed Over"), styles["label"]),
            _p(
                _format_date(_attr(handover, "keys_handed_over_at", None), locale) or "-",
                styles["body"],
            ),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        _p(_t(locale, "handover_certificate.title", "Certificate of Handover"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "handover_certificate.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        _p(
            _t(locale, "handover_certificate.headings.developer_declaration", "Developer's Declaration"),
            styles["heading"],
        ),
        _p(
            _t(locale, "handover_certificate.developer_declaration_text", ""),
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        _p(
            _t(locale, "handover_certificate.headings.buyer_acceptance", "Buyer's Acceptance"),
            styles["heading"],
        ),
        _p(
            _t(locale, "handover_certificate.buyer_acceptance_text", ""),
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        _p(
            _t(locale, "handover_certificate.snag_note", ""),
            styles["small"],
        ),
        Spacer(1, 14 * mm),
        Table(
            [
                [
                    _p(
                        f"{html.escape(_t(locale, 'common.buyer_signature', 'Buyer Signature'))}<br/>"
                        "________________________________",
                        styles["body"],
                        markup=True,
                    ),
                    _p(
                        f"{html.escape(_t(locale, 'common.developer_signature', 'Developer Signature'))}<br/>"
                        "________________________________",
                        styles["body"],
                        markup=True,
                    ),
                ]
            ],
            colWidths=[75 * mm, 75 * mm],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 5 - Warranty Certificate
# ════════════════════════════════════════════════════════════════════════


def render_warranty_certificate_pdf(
    sales_contract: Any,
    handover: Any,
    structural_warranty_years: int,
    finishing_warranty_years: int,
    locale: str = "en",
    *,
    plot: Any = None,
    development: Any = None,
) -> bytes:
    """Warranty certificate - typically structural 10y, finishing 1y."""
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("WAR", entity=handover)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "warranty_certificate.title", "Warranty Certificate"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"Warranty for SPA {_attr(sales_contract, 'contract_number', '')}",
        keywords=["warranty", "certificate", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development) if plot is not None else "",
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(sales_contract),
    )

    handover_iso = _format_date(_attr(handover, "completed_at", None), locale)
    expiry_iso = ""
    if handover_iso:
        try:
            hd = date.fromisoformat(handover_iso)
            expiry_iso = (hd.replace(year=hd.year + int(structural_warranty_years))).isoformat()
        except ValueError:
            expiry_iso = ""

    rows = [
        [
            _p(_t(locale, "warranty_certificate.headings.spa_ref", "Agreement No."), styles["label"]),
            _p(str(_attr(sales_contract, "contract_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "warranty_certificate.headings.handover_date", "Handover Date"), styles["label"]),
            _p(handover_iso or "-", styles["body"]),
        ],
        [
            _p(_t(locale, "warranty_certificate.headings.structural_period", "Structural Period"), styles["label"]),
            _p(f"{int(structural_warranty_years)}y", styles["body"]),
        ],
        [
            _p(_t(locale, "warranty_certificate.headings.finishing_period", "Finishing Period"), styles["label"]),
            _p(f"{int(finishing_warranty_years)}y", styles["body"]),
        ],
        [
            _p(_t(locale, "warranty_certificate.headings.warranty_expiry", "Warranty Expiry"), styles["label"]),
            _p(expiry_iso or "-", styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        _p(_t(locale, "warranty_certificate.title", "Warranty Certificate"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "warranty_certificate.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        _p(_t(locale, "warranty_certificate.headings.structural", "Structural Warranty"), styles["heading"]),
        _p(
            _t(locale, "warranty_certificate.structural_text", "").replace(
                "{years}",
                str(int(structural_warranty_years)),
            ),
            styles["body"],
        ),
        Spacer(1, 3 * mm),
        _p(_t(locale, "warranty_certificate.headings.finishing", "Finishing Warranty"), styles["heading"]),
        _p(
            _t(locale, "warranty_certificate.finishing_text", "").replace(
                "{years}",
                str(int(finishing_warranty_years)),
            ),
            styles["body"],
        ),
        Spacer(1, 3 * mm),
        _p(_t(locale, "warranty_certificate.headings.exclusions", "Exclusions"), styles["heading"]),
        _p(_t(locale, "warranty_certificate.exclusions_text", ""), styles["body"]),
        Spacer(1, 3 * mm),
        _p(_t(locale, "warranty_certificate.claim_procedure", ""), styles["small"]),
        Spacer(1, 14 * mm),
        _p(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 6 - NOC (No Objection Certificate)
# ════════════════════════════════════════════════════════════════════════


def render_no_objection_certificate_pdf(
    sales_contract: Any,
    plot: Any,
    development: Any,
    requested_by: str,
    locale: str = "en",
    *,
    validity_days: int = DEFAULT_NOC_VALIDITY_DAYS,
) -> bytes:
    """NOC - developer's permission for the buyer to resell."""
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("NOC", entity=sales_contract)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "noc.title", "No Objection Certificate"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"NOC for SPA {_attr(sales_contract, 'contract_number', '')}",
        keywords=["noc", "no objection", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(sales_contract),
    )

    issued_at = date.today().isoformat()
    valid_until = (date.today() + timedelta(days=int(validity_days))).isoformat()

    rows = [
        [
            _p(_t(locale, "noc.headings.spa_ref", "Agreement No."), styles["label"]),
            _p(str(_attr(sales_contract, "contract_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "noc.headings.requested_by", "Requested By"), styles["label"]),
            _p(str(requested_by or "-"), styles["body"]),
        ],
        [
            _p(_t(locale, "common.date", "Date"), styles["label"]),
            _p(issued_at, styles["body"]),
        ],
        [
            _p(_t(locale, "noc.headings.validity", "Validity"), styles["label"]),
            _p(
                _t(locale, "noc.validity_text", "Valid for {days} days from the date of issue.").replace(
                    "{days}",
                    str(int(validity_days)),
                )
                + f" ({valid_until})",
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "noc.headings.purpose", "Purpose"), styles["label"]),
            _p(_t(locale, "noc.purpose_text", ""), styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        _p(_t(locale, "noc.title", "No Objection Certificate"), styles["title"]),
        _p(_t(locale, "noc.subtitle", ""), styles["subtitle"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "noc.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        _p(_t(locale, "noc.no_outstanding", ""), styles["body"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "noc.developer_statement", ""), styles["body"]),
        Spacer(1, 14 * mm),
        _p(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 7 - Tenant Lease Agreement
# ════════════════════════════════════════════════════════════════════════


def render_tenant_lease_agreement_pdf(
    lease: Any,
    plot: Any,
    development: Any,
    tenants: list[Any],
    locale: str = "en",
) -> bytes:
    """Multi-page rental contract for a tenant occupying a developer unit.

    Useful for build-to-rent and post-handover developer-owned inventory.
    Pulls term length / rent / deposit from the ``lease`` blob (free
    duck-typed shape - works against ORM rows OR dicts) and emits a
    standard residential lease body with a signature block per tenant.
    """
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("LEA", entity=lease)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "tenant_lease_agreement.title", "Tenant Lease Agreement"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"Lease {_attr(lease, 'lease_number', '')}",
        keywords=["lease", "tenant", "rental", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(lease),
    )

    ccy = _attr(lease, "currency", "") or _attr(plot, "currency", "") or ""
    monthly_rent = _attr(lease, "monthly_rent", Decimal("0"))
    security_deposit = _attr(lease, "security_deposit", Decimal("0"))
    start_date = _format_date(_attr(lease, "start_date", None), locale) or "-"
    end_date = _format_date(_attr(lease, "end_date", None), locale) or "-"
    term_months = _attr(lease, "term_months", 12)

    tenant_lines = "<br/>".join(
        f"{_attr(t, 'full_name', '')} ({_attr(t, 'email', '')})"
        for t in (tenants or [])
        if _attr(t, "full_name", "") or _attr(t, "email", "")
    )

    rows = [
        [
            _p(_t(locale, "tenant_lease_agreement.headings.lease_number", "Lease No."), styles["label"]),
            _p(str(_attr(lease, "lease_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "tenant_lease_agreement.headings.tenant", "Tenant"), styles["label"]),
            _p(tenant_lines or "-", styles["body"]),
        ],
        [
            _p(_t(locale, "tenant_lease_agreement.headings.property", "Property"), styles["label"]),
            _p(
                f"{_development_name(development)} - "
                f"{_attr(plot, 'plot_number', '')} "
                f"({_attr(plot, 'area_m2', '')} m²)",
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "tenant_lease_agreement.headings.term", "Term"), styles["label"]),
            _p(
                f"{int(term_months or 0)} months - {start_date} → {end_date}",
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "tenant_lease_agreement.headings.monthly_rent", "Monthly Rent"), styles["label"]),
            _p(
                f"{_format_money(monthly_rent, locale, ccy)} {ccy}".strip(),
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "tenant_lease_agreement.headings.security_deposit", "Security Deposit"), styles["label"]),
            _p(
                f"{_format_money(security_deposit, locale, ccy)} {ccy}".strip(),
                styles["body"],
            ),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        _p(_t(locale, "tenant_lease_agreement.title", "Tenant Lease Agreement"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "tenant_lease_agreement.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        _p(_t(locale, "tenant_lease_agreement.headings.use_clause", "Use of the Property"), styles["heading"]),
        _p(_t(locale, "tenant_lease_agreement.use_clause_text", ""), styles["body"]),
        _p(_t(locale, "tenant_lease_agreement.headings.maintenance", "Maintenance"), styles["heading"]),
        _p(_t(locale, "tenant_lease_agreement.maintenance_text", ""), styles["body"]),
        _p(_t(locale, "tenant_lease_agreement.headings.termination", "Termination"), styles["heading"]),
        _p(_t(locale, "tenant_lease_agreement.termination_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        Table(
            [
                [
                    _p(
                        f"{html.escape(_t(locale, 'tenant_lease_agreement.tenant_signature', 'Tenant Signature'))}<br/>"
                        "________________________________",
                        styles["body"],
                        markup=True,
                    ),
                    _p(
                        f"{html.escape(_t(locale, 'common.developer_signature', 'Developer Signature'))}<br/>"
                        "________________________________",
                        styles["body"],
                        markup=True,
                    ),
                ]
            ],
            colWidths=[75 * mm, 75 * mm],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 8 - Move-in Checklist (room-by-room condition report)
# ════════════════════════════════════════════════════════════════════════


def render_move_in_checklist_pdf(
    handover: Any,
    sales_contract: Any,
    plot: Any,
    development: Any,
    rooms: list[Any] | None,
    locale: str = "en",
) -> bytes:
    """Itemised property-condition report at handover.

    Companion to the handover certificate - focuses on furnishings /
    appliance state per room. Each row in ``rooms`` is treated as a
    dict-like with ``name``, ``items`` (list of dict ``{label,
    condition, notes}``).
    """
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("MIC", entity=handover)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "move_in_checklist.title", "Move-in Checklist"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"Move-in for SPA {_attr(sales_contract, 'contract_number', '')}",
        keywords=["move-in", "checklist", "handover", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(sales_contract),
    )

    story: list[Any] = [
        _p(_t(locale, "move_in_checklist.title", "Move-in Checklist"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "move_in_checklist.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
    ]

    meta_rows = [
        [
            _p(_t(locale, "move_in_checklist.headings.spa_ref", "Agreement No."), styles["label"]),
            _p(str(_attr(sales_contract, "contract_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "move_in_checklist.headings.inspection_date", "Inspection Date"), styles["label"]),
            _p(
                _format_date(_attr(handover, "completed_at", None), locale)
                or _format_date(_attr(handover, "scheduled_at", None), locale)
                or "-",
                styles["body"],
            ),
        ],
    ]
    meta_tbl = Table(meta_rows, colWidths=[60 * mm, 100 * mm])
    meta_tbl.setStyle(_kv_table_style())
    story.append(meta_tbl)
    story.append(Spacer(1, 4 * mm))

    if rooms:
        for room in rooms:
            room_name = _attr(room, "name", "") or "-"
            items = _attr(room, "items", None) or []
            story.append(_p(str(room_name), styles["heading"]))
            room_rows: list[list[Any]] = [
                [
                    _p(_t(locale, "move_in_checklist.columns.item", "Item"), styles["grid_header"]),
                    _p(_t(locale, "move_in_checklist.columns.condition", "Condition"), styles["grid_header"]),
                    _p(_t(locale, "move_in_checklist.columns.notes", "Notes"), styles["grid_header"]),
                ]
            ]
            for it in items:
                room_rows.append(
                    [
                        _p(str(_attr(it, "label", "") or "-"), styles["body"]),
                        _p(str(_attr(it, "condition", "") or "-"), styles["body"]),
                        _p(str(_attr(it, "notes", "") or ""), styles["body"]),
                    ]
                )
            tbl = Table(
                room_rows,
                colWidths=[55 * mm, 30 * mm, 70 * mm],
                repeatRows=1,
            )
            tbl.setStyle(_grid_table_style())
            story.append(tbl)
            story.append(Spacer(1, 3 * mm))
    else:
        story.append(_p(_t(locale, "move_in_checklist.empty_rooms", "No room data supplied."), styles["small"]))

    story.extend(
        [
            Spacer(1, 6 * mm),
            _p(_t(locale, "move_in_checklist.acceptance_text", ""), styles["body"]),
            Spacer(1, 14 * mm),
            Table(
                [
                    [
                        _p(
                            f"{html.escape(_t(locale, 'common.buyer_signature', 'Buyer Signature'))}<br/>"
                            "________________________________",
                            styles["body"],
                            markup=True,
                        ),
                        _p(
                            f"{html.escape(_t(locale, 'common.developer_signature', 'Developer Signature'))}<br/>"
                            "________________________________",
                            styles["body"],
                            markup=True,
                        ),
                    ]
                ],
                colWidths=[75 * mm, 75 * mm],
            ),
        ]
    )
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 9 - Mortgage Clearance Letter
# ════════════════════════════════════════════════════════════════════════


def render_mortgage_clearance_letter_pdf(
    sales_contract: Any,
    plot: Any,
    development: Any,
    bank_name: str,
    locale: str = "en",
) -> bytes:
    """Bank-facing letter confirming the unit has no encumbrances.

    Required by most mortgage lenders before they release final draw-down.
    """
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("MCL", entity=sales_contract)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "mortgage_clearance_letter.title", "Mortgage Clearance Letter"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"Mortgage clearance for SPA {_attr(sales_contract, 'contract_number', '')}",
        keywords=["mortgage", "clearance", "letter", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(sales_contract),
    )

    issued_at = date.today().isoformat()
    rows = [
        [
            _p(_t(locale, "mortgage_clearance_letter.headings.bank", "Issued To (Bank)"), styles["label"]),
            _p(str(bank_name or "-"), styles["body"]),
        ],
        [
            _p(_t(locale, "mortgage_clearance_letter.headings.spa_ref", "Agreement No."), styles["label"]),
            _p(str(_attr(sales_contract, "contract_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "mortgage_clearance_letter.headings.unit", "Unit"), styles["label"]),
            _p(
                f"{_development_name(development)} - {_attr(plot, 'plot_number', '')}",
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "common.date", "Date"), styles["label"]),
            _p(issued_at, styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        _p(_t(locale, "mortgage_clearance_letter.title", "Mortgage Clearance Letter"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "mortgage_clearance_letter.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        _p(_t(locale, "mortgage_clearance_letter.no_encumbrance_text", ""), styles["body"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "mortgage_clearance_letter.purpose_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        _p(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 10 - Title Deed Transfer Request
# ════════════════════════════════════════════════════════════════════════


def render_title_deed_transfer_request_pdf(
    sales_contract: Any,
    plot: Any,
    development: Any,
    parties: list[Any],
    registry_name: str,
    locale: str = "en",
    *,
    buyer_lookup: dict[Any, Any] | None = None,
) -> bytes:
    """Request to the land registry to transfer title from developer to buyer.

    ``registry_name`` is free-text: ``"Grundbuchamt Berlin"`` /
    ``"Росреестр"`` / ``"Dubai Land Department"`` / ``"HM Land Registry"``.
    """
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("TDT", entity=sales_contract)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "title_deed_transfer_request.title", "Title Deed Transfer Request"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"Title deed transfer for SPA {_attr(sales_contract, 'contract_number', '')}",
        keywords=["title", "deed", "transfer", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(sales_contract),
    )

    party_names: list[str] = []
    for p in parties or []:
        buyer_id = _attr(p, "buyer_id", None)
        buyer = (buyer_lookup or {}).get(buyer_id) if buyer_lookup else None
        name = _attr(buyer, "full_name", "") or _attr(p, "full_name", "") or "-"
        pct = _attr(p, "ownership_pct", "") or ""
        party_names.append(f"{name} ({pct}%)" if pct else str(name))

    rows = [
        [
            _p(_t(locale, "title_deed_transfer_request.headings.registry", "Land Registry"), styles["label"]),
            _p(str(registry_name or "-"), styles["body"]),
        ],
        [
            _p(_t(locale, "title_deed_transfer_request.headings.spa_ref", "Agreement No."), styles["label"]),
            _p(str(_attr(sales_contract, "contract_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "title_deed_transfer_request.headings.unit", "Unit"), styles["label"]),
            _p(
                f"{_development_name(development)} - "
                f"{_attr(plot, 'plot_number', '')} "
                f"({_attr(plot, 'area_m2', '')} m²)",
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "title_deed_transfer_request.headings.new_owners", "New Owner(s)"), styles["label"]),
            _p(
                "<br/>".join(html.escape(str(name)) for name in party_names) if party_names else "-",
                styles["body"],
                markup=True,
            ),
        ],
        [
            _p(_t(locale, "common.date", "Date"), styles["label"]),
            _p(date.today().isoformat(), styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        _p(_t(locale, "title_deed_transfer_request.title", "Title Deed Transfer Request"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "title_deed_transfer_request.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        _p(_t(locale, "title_deed_transfer_request.headings.request_body", "Request"), styles["heading"]),
        _p(_t(locale, "title_deed_transfer_request.request_text", ""), styles["body"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "title_deed_transfer_request.headings.attachments", "Attachments"), styles["heading"]),
        _p(_t(locale, "title_deed_transfer_request.attachments_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        _p(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 11 - Escrow Release Authorization
# ════════════════════════════════════════════════════════════════════════


def render_escrow_release_authorization_pdf(
    sales_contract: Any,
    plot: Any,
    development: Any,
    escrow_account_no: str,
    amount: Decimal | int | float,
    release_reason: str,
    locale: str = "en",
) -> bytes:
    """Instruction to the escrow agent to release funds for a milestone."""
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    doc_ref = _doc_ref("ERA", entity=sales_contract)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "escrow_release_authorization.title", "Escrow Release Authorization"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=f"Escrow release for SPA {_attr(sales_contract, 'contract_number', '')}",
        keywords=["escrow", "release", "authorization", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(sales_contract),
    )

    ccy = _attr(sales_contract, "currency", "") or _attr(plot, "currency", "") or ""

    rows = [
        [
            _p(
                _t(locale, "escrow_release_authorization.headings.escrow_account", "Escrow Account No."),
                styles["label"],
            ),
            _p(str(escrow_account_no or "-"), styles["body"]),
        ],
        [
            _p(_t(locale, "escrow_release_authorization.headings.spa_ref", "Agreement No."), styles["label"]),
            _p(str(_attr(sales_contract, "contract_number", "-")), styles["body"]),
        ],
        [
            _p(_t(locale, "escrow_release_authorization.headings.unit", "Unit"), styles["label"]),
            _p(
                f"{_development_name(development)} - {_attr(plot, 'plot_number', '')}",
                styles["body"],
            ),
        ],
        [
            _p(
                _t(locale, "escrow_release_authorization.headings.amount_to_release", "Amount to Release"),
                styles["label"],
            ),
            _p(
                f"{_format_money(amount, locale, ccy)} {ccy}".strip(),
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "escrow_release_authorization.headings.release_reason", "Release Reason"), styles["label"]),
            _p(str(release_reason or "-"), styles["body"]),
        ],
        [
            _p(_t(locale, "common.date", "Date"), styles["label"]),
            _p(date.today().isoformat(), styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        _p(_t(locale, "escrow_release_authorization.title", "Escrow Release Authorization"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "escrow_release_authorization.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        _p(_t(locale, "escrow_release_authorization.instruction_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        _p(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 12 - Refund Authorization
# ════════════════════════════════════════════════════════════════════════


def render_refund_authorization_pdf(
    sales_contract: Any,
    plot: Any,
    development: Any,
    refund_amount: Decimal | int | float,
    refund_reason: str,
    payment_method: str,
    locale: str = "en",
    *,
    reservation: Any = None,
) -> bytes:
    """Formal refund instruction (reservation or contract cancelled).

    Either ``sales_contract`` OR ``reservation`` may be the source - the
    title bar shows whichever is non-empty.
    """
    if locale not in SUPPORTED_LOCALES:
        locale = "en"
    styles = _styles(locale)
    buf = BytesIO()
    source_entity = sales_contract if _attr(sales_contract, "id", None) else reservation
    doc_ref = _doc_ref("REF", entity=source_entity or sales_contract)

    doc, frame = _build_doc(
        buf,
        title=_t(locale, "refund_authorization.title", "Refund Authorization"),
        author=_development_name(development) or "OpenConstructionERP",
        subject=(
            f"Refund for SPA {_attr(sales_contract, 'contract_number', '')}"
            if _attr(sales_contract, "contract_number", None)
            else f"Refund for reservation {_attr(reservation, 'reservation_number', '')}"
        ),
        keywords=["refund", "authorization", doc_ref],
    )
    ctx = _PageContext(
        developer_name=_development_name(development),
        developer_logo_url=_development_logo(development),
        unit_code=_unit_code(plot, development),
        doc_ref=doc_ref,
        locale=locale,
        watermark=_is_draft(sales_contract),
    )

    ccy = (
        _attr(sales_contract, "currency", "") or _attr(reservation, "currency", "") or _attr(plot, "currency", "") or ""
    )

    ref_value = _attr(sales_contract, "contract_number", "") or _attr(reservation, "reservation_number", "") or "-"

    rows = [
        [
            _p(_t(locale, "refund_authorization.headings.reference", "Reference"), styles["label"]),
            _p(str(ref_value), styles["body"]),
        ],
        [
            _p(_t(locale, "refund_authorization.headings.unit", "Unit"), styles["label"]),
            _p(
                f"{_development_name(development)} - {_attr(plot, 'plot_number', '')}",
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "refund_authorization.headings.amount", "Refund Amount"), styles["label"]),
            _p(
                f"{_format_money(refund_amount, locale, ccy)} {ccy}".strip(),
                styles["body"],
            ),
        ],
        [
            _p(_t(locale, "refund_authorization.headings.reason", "Reason"), styles["label"]),
            _p(str(refund_reason or "-"), styles["body"]),
        ],
        [
            _p(_t(locale, "refund_authorization.headings.payment_method", "Payment Method"), styles["label"]),
            _p(str(payment_method or "-"), styles["body"]),
        ],
        [
            _p(_t(locale, "common.date", "Date"), styles["label"]),
            _p(date.today().isoformat(), styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        _p(_t(locale, "refund_authorization.title", "Refund Authorization"), styles["title"]),
        Spacer(1, 4 * mm),
        _p(_t(locale, "refund_authorization.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        _p(_t(locale, "refund_authorization.authorisation_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        _p(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ── Public exports ──────────────────────────────────────────────────────


__all__ = [
    "DEFAULT_NOC_VALIDITY_DAYS",
    "RTL_LOCALES",
    "SUPPORTED_LOCALES",
    "SUPPORTED_REGULATORS",
    "render_escrow_release_authorization_pdf",
    "render_handover_certificate_pdf",
    "render_mortgage_clearance_letter_pdf",
    "render_move_in_checklist_pdf",
    "render_no_objection_certificate_pdf",
    "render_payment_receipt_pdf",
    "render_refund_authorization_pdf",
    "render_reservation_receipt_pdf",
    "render_sales_contract_pdf",
    "render_tenant_lease_agreement_pdf",
    "render_title_deed_transfer_request_pdf",
    "render_warranty_certificate_pdf",
]
