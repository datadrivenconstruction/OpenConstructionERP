"""Property Development PDF document templates.

Production-grade PDF generators for every sales-pipeline transition:

  * Reservation receipt (issued on deposit)
  * Sales-Purchase Agreement / SPA (multi-page, multi-buyer, jurisdiction-aware)
  * Payment receipt (issued per paid instalment)
  * Handover certificate (signed on completion)
  * Warranty certificate (structural + finishing)
  * No Objection Certificate / NOC (for resale)

Each generator is a pure function: input dicts/entities, output ``bytes``
starting with ``%PDF``. Layout uses ``reportlab`` (already a hard dep —
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
  ``en`` → ``1,234.56``, ``ru`` → ``1 234,56``, ``fr`` → ``1 234,56``).

The generators have no DB / I/O — they take SQLAlchemy ORM instances
(or anything duck-compatible) plus a few primitives, and return bytes.
The service layer ``generate_document`` wires the right entities in.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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

# ── Constants ───────────────────────────────────────────────────────────

#: All locales offered in the document-templates UI picker. Locales
#: without a dedicated translation JSON in ``data/document_locales/``
#: fall back to ``en.json`` automatically (see ``_load_locale``); the
#: list below stays in sync with the frontend's ``app/locales/*.ts``
#: catalogue so every UI language has at least an English-content
#: template option available rather than being silently dropped from
#: the picker. Adding a new translation = drop a ``<code>.json`` file
#: into ``data/document_locales/`` — no code change required.
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

#: RTL locales — paragraph wordWrap set to ``RTL`` and alignment flipped.
RTL_LOCALES: frozenset[str] = frozenset({"ar", "he", "fa", "ur"})

#: Regulators we ship clause-blocks for. Anything else uses ``NONE``.
SUPPORTED_REGULATORS: tuple[str, ...] = (
    "RERA",
    "MAHARERA",
    "214_FZ",
    "CMA",
    "NONE",
)

#: Page margins (all sides). 25 mm matches the spec.
PAGE_MARGIN_MM: float = 25.0

#: Default validity for an NOC, in days.
DEFAULT_NOC_VALIDITY_DAYS: int = 30

_DATA_DIR = Path(__file__).resolve().parent / "data"
_LOCALE_DIR = _DATA_DIR / "document_locales"
_CLAUSE_DIR = _DATA_DIR / "jurisdiction_clauses"


# ── Locale loader ───────────────────────────────────────────────────────


@lru_cache(maxsize=32)
def _load_locale(locale: str) -> dict[str, Any]:
    """Load the locale JSON; falls back to ``en`` on missing files."""
    fp = _LOCALE_DIR / f"{locale}.json"
    if not fp.exists():
        fp = _LOCALE_DIR / "en.json"
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Never crash a PDF render on a locale-load failure.
        return {}


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


def _format_money(amount: Decimal | int | float | None, locale: str) -> str:
    """Locale-aware thousands-separated string. Falls back to en-US grouping."""
    if amount is None:
        return ""
    try:
        d = Decimal(str(amount))
    except (ValueError, TypeError):
        return ""
    # Quantize to 2 decimal places without introducing scientific notation.
    q = d.quantize(Decimal("0.01"))
    sign = "-" if q < 0 else ""
    abs_q = -q if q < 0 else q
    int_part, _, frac_part = format(abs_q, "f").partition(".")
    # Group by 3 from the right.
    rev = int_part[::-1]
    chunks = [rev[i : i + 3] for i in range(0, len(rev), 3)]
    grouped_rev = "".join(chunks)
    thou_sep, dec_sep = _separators_for_locale(locale)
    grouped = thou_sep.join([c[::-1] for c in chunks][::-1])  # readable order
    # NB: the join above already does grouping; ``grouped_rev`` was a sketch
    # we don't need. Keep the final value.
    _ = grouped_rev
    return f"{sign}{grouped}{dec_sep}{frac_part or '00'}"


def _separators_for_locale(locale: str) -> tuple[str, str]:
    """Return (thousand_sep, decimal_sep) for a locale (BCP-47 root)."""
    base = (locale or "en").split("-")[0].lower()
    # Continental Europe + Russia + Spanish + Arabic (using Arabic-Indic
    # digits is overkill for a generated PDF; stick to Western digits with
    # locale-conventional separators).
    if base in {"de", "ru", "es", "fr", "it", "nl", "pt", "tr", "pl"}:
        return (" " if base in {"fr", "ru"} else ".", ",")
    return (",", ".")


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
    """Build the ParagraphStyle family for the given locale."""
    rtl = locale in RTL_LOCALES
    base = getSampleStyleSheet()
    word_wrap = "RTL" if rtl else None
    align_body = TA_RIGHT if rtl else TA_LEFT

    title = ParagraphStyle(
        "OE_Title",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        alignment=TA_CENTER,
        wordWrap=word_wrap,
        spaceAfter=6,
    )
    subtitle = ParagraphStyle(
        "OE_Subtitle",
        parent=base["Heading2"],
        fontName="Helvetica",
        fontSize=12,
        leading=16,
        alignment=TA_CENTER,
        wordWrap=word_wrap,
        textColor=colors.HexColor("#4b5563"),
    )
    heading = ParagraphStyle(
        "OE_Heading",
        parent=base["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        alignment=align_body,
        wordWrap=word_wrap,
        spaceBefore=10,
        spaceAfter=4,
        textColor=colors.HexColor("#1f2937"),
    )
    body = ParagraphStyle(
        "OE_Body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        alignment=align_body,
        wordWrap=word_wrap,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "OE_Small",
        parent=body,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#4b5563"),
    )
    label = ParagraphStyle(
        "OE_Label",
        parent=body,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#374151"),
    )
    clause = ParagraphStyle(
        "OE_Clause",
        parent=body,
        fontSize=9.5,
        leading=13,
        spaceAfter=6,
    )
    clause_heading = ParagraphStyle(
        "OE_ClauseHeading",
        parent=heading,
        fontSize=10.5,
        leading=13,
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
        "clause": clause,
        "clause_heading": clause_heading,
    }


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

        # Header — developer + unit code top-right.
        canvas.setFont("Helvetica-Bold", 14)
        canvas.setFillColor(colors.HexColor("#111827"))
        canvas.drawString(
            PAGE_MARGIN_MM * mm,
            A4[1] - (PAGE_MARGIN_MM * mm - 4 * mm),
            (ctx.developer_name or "OpenConstructionERP")[:80],
        )

        if ctx.unit_code:
            canvas.setFont("Helvetica", 10)
            canvas.setFillColor(colors.HexColor("#374151"))
            canvas.drawRightString(
                A4[0] - PAGE_MARGIN_MM * mm,
                A4[1] - (PAGE_MARGIN_MM * mm - 4 * mm),
                ctx.unit_code,
            )

        # Thin separator line under header.
        canvas.setStrokeColor(colors.HexColor("#d1d5db"))
        canvas.setLineWidth(0.4)
        canvas.line(
            PAGE_MARGIN_MM * mm,
            A4[1] - PAGE_MARGIN_MM * mm + 1 * mm,
            A4[0] - PAGE_MARGIN_MM * mm,
            A4[1] - PAGE_MARGIN_MM * mm + 1 * mm,
        )

        # Watermark — drawn behind content.
        if ctx.watermark:
            canvas.saveState()
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(45)
            canvas.setFont("Helvetica-Bold", 96)
            canvas.setFillColor(colors.Color(0.78, 0.27, 0.27, alpha=0.18))
            text = _t(ctx.locale, "common.watermark_draft", "DRAFT")
            canvas.drawCentredString(0, 0, text)
            canvas.restoreState()

        # Footer — doc ref + page X (real count appended by NumberedCanvas)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        gen_str = _t(ctx.locale, "common.generated_at", "Generated {timestamp} UTC").replace(
            "{timestamp}", ctx.generated_at
        )
        ref_label = _t(ctx.locale, "common.doc_ref", "Doc. Ref")
        ref_str = f"{ref_label}: {ctx.doc_ref}" if ctx.doc_ref else ""

        canvas.drawString(
            PAGE_MARGIN_MM * mm,
            PAGE_MARGIN_MM * mm - 10 * mm,
            ref_str,
        )
        canvas.drawCentredString(
            A4[0] / 2,
            PAGE_MARGIN_MM * mm - 10 * mm,
            gen_str,
        )
        # Right-side page label — final "X of Y" is injected on second pass.
        # We draw a placeholder that NumberedCanvas will overwrite.
        canvas.restoreState()

    return _draw


class _NumberedCanvas(Canvas):
    """Two-pass canvas that knows total page count when drawing."""

    def __init__(self, *args: Any, page_locale: str = "en", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_pages: list[dict[str, Any]] = []
        self._locale = page_locale

    def showPage(self) -> None:  # noqa: N802 — reportlab API
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
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#6b7280"))
        template = _t(self._locale, "common.page_of", "Page {page} of {total}")
        label = template.replace("{page}", str(self._pageNumber)).replace("{total}", str(n_pages))
        self.drawRightString(
            A4[0] - PAGE_MARGIN_MM * mm,
            PAGE_MARGIN_MM * mm - 10 * mm,
            label,
        )
        self.restoreState()


# ── Common attribute extractors ────────────────────────────────────────


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Safe getattr for ORM rows OR dicts — both shapes show up in tests."""
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
) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=PAGE_MARGIN_MM * mm,
        rightMargin=PAGE_MARGIN_MM * mm,
        topMargin=PAGE_MARGIN_MM * mm + 5 * mm,
        bottomMargin=PAGE_MARGIN_MM * mm + 10 * mm,
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
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
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
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, 0), "LEFT"),
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
#  Generator 1 — Reservation Receipt
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
        watermark=False,  # Receipt itself is final — issued on payment
    )

    story: list[Any] = [
        Paragraph(_t(locale, "reservation_receipt.title", "Reservation Receipt"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(
            _t(
                locale,
                "reservation_receipt.intro",
                "This receipt confirms reservation of the property described below.",
            ),
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "reservation_receipt.headings.plot_details", "Plot Details"), styles["heading"]),
    ]

    # KV table — buyer / property / amounts.
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
            Paragraph(
                _t(locale, "reservation_receipt.headings.reservation_number", "Reservation No."), styles["label"]
            ),
            Paragraph(str(_attr(reservation, "reservation_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "reservation_receipt.headings.buyer", "Buyer"), styles["label"]),
            Paragraph(buyer_lines or "—", styles["body"]),
        ],
        [
            Paragraph(_t(locale, "reservation_receipt.headings.property", "Property"), styles["label"]),
            Paragraph(
                f"{_development_name(development)} — "
                f"{_attr(plot, 'plot_number', '')} "
                f"({_attr(plot, 'area_m2', '')} m²)",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "reservation_receipt.headings.amount_paid", "Amount Paid"), styles["label"]),
            Paragraph(f"{_format_money(deposit, locale)} {ccy}".strip(), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "reservation_receipt.headings.cooling_off", "Cooling-off Period"), styles["label"]),
            Paragraph(
                _t(
                    locale, "reservation_receipt.cooling_off_text", "{days} days from receipt of this document."
                ).replace("{days}", str(int(cooling_days or 0))),
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "reservation_receipt.headings.valid_until", "Valid Until"), styles["label"]),
            Paragraph(
                _format_date(expires_at or cooling_until, locale) or "—",
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
            Paragraph(_t(locale, "reservation_receipt.headings.next_step", "Next Step"), styles["heading"]),
            Paragraph(
                _t(
                    locale, "reservation_receipt.next_step_text", "Within {days} days the buyer must sign the SPA."
                ).replace("{days}", str(int(cooling_days or 0))),
                styles["body"],
            ),
            Spacer(1, 6 * mm),
            Paragraph(_t(locale, "reservation_receipt.footer_note", ""), styles["small"]),
            Spacer(1, 10 * mm),
            Paragraph(
                f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
                styles["body"],
            ),
        ]
    )

    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 2 — Sales-Purchase Agreement (SPA)
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
        Paragraph(_t(locale, "sales_contract.title", "Sale-Purchase Agreement"), styles["title"]),
        Paragraph(subtitle, styles["subtitle"]),
        Spacer(1, 6 * mm),
        Paragraph(_t(locale, "sales_contract.preamble", ""), styles["body"]),
        Spacer(1, 4 * mm),
    ]

    # ── Parties section ──
    story.append(
        Paragraph(_t(locale, "sales_contract.headings.parties", "Parties to the Agreement"), styles["heading"])
    )
    story.append(Paragraph(_t(locale, "sales_contract.parties_intro", ""), styles["body"]))

    party_rows: list[list[Any]] = [
        [
            Paragraph(_t(locale, "sales_contract.party_columns.name", "Name"), styles["label"]),
            Paragraph(_t(locale, "sales_contract.party_columns.role", "Role"), styles["label"]),
            Paragraph(_t(locale, "sales_contract.party_columns.ownership_pct", "Ownership %"), styles["label"]),
            Paragraph(_t(locale, "sales_contract.party_columns.email", "Email"), styles["label"]),
        ]
    ]
    total_pct = Decimal("0")
    for p in parties or []:
        buyer_id = _attr(p, "buyer_id", None)
        buyer = (buyer_lookup or {}).get(buyer_id) if buyer_lookup else None
        name = _attr(buyer, "full_name", "") or _attr(p, "full_name", "") or "—"
        email = _attr(buyer, "email", "") or _attr(p, "email", "") or ""
        role = _attr(p, "party_role", "primary") or "primary"
        pct = _attr(p, "ownership_pct", Decimal("0")) or Decimal("0")
        try:
            total_pct += Decimal(str(pct))
        except (ValueError, TypeError):
            pass
        party_rows.append(
            [
                Paragraph(str(name), styles["body"]),
                Paragraph(str(role), styles["body"]),
                Paragraph(f"{pct}%", styles["body"]),
                Paragraph(str(email), styles["body"]),
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
                Paragraph(
                    f"Total ownership: {total_pct}%",
                    styles["small"],
                )
            )

    # ── Property section ──
    story.extend(
        [
            Spacer(1, 4 * mm),
            Paragraph(_t(locale, "sales_contract.headings.property", "The Property"), styles["heading"]),
        ]
    )
    prop_rows = [
        [
            Paragraph(_t(locale, "sales_contract.property_columns.plot_number", "Plot Number"), styles["label"]),
            Paragraph(str(_attr(plot, "plot_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "sales_contract.property_columns.development", "Development"), styles["label"]),
            Paragraph(_development_name(development), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "sales_contract.property_columns.area_m2", "Area (m²)"), styles["label"]),
            Paragraph(str(_attr(plot, "area_m2", "—")), styles["body"]),
        ],
    ]
    house_type_label = _attr(plot, "house_type_label", None)
    if house_type_label:
        prop_rows.append(
            [
                Paragraph(_t(locale, "sales_contract.property_columns.house_type", "House Type"), styles["label"]),
                Paragraph(str(house_type_label), styles["body"]),
            ]
        )
    tbl_prop = Table(prop_rows, colWidths=[55 * mm, 100 * mm])
    tbl_prop.setStyle(_kv_table_style())
    story.append(tbl_prop)

    # ── Price section ──
    story.extend(
        [
            Spacer(1, 4 * mm),
            Paragraph(_t(locale, "sales_contract.headings.price", "Purchase Price"), styles["heading"]),
        ]
    )
    ccy = _attr(contract, "currency", "") or ""
    total_value = _attr(contract, "total_value", Decimal("0"))
    story.append(
        Paragraph(
            f"<b>{_t(locale, 'sales_contract.price_label', 'Total Purchase Price')}</b>: "
            f"{_format_money(total_value, locale)} {ccy}".strip(),
            styles["body"],
        )
    )

    breakdown = _attr(contract, "total_price_breakdown", None) or {}
    if isinstance(breakdown, dict) and breakdown:
        story.append(Paragraph(_t(locale, "sales_contract.breakdown_label", "Price Breakdown"), styles["label"]))
        brk_rows: list[list[Any]] = []
        for key in ("base", "vat", "stamp_duty", "legal_fees", "options_value", "discounts"):
            if key in breakdown:
                brk_rows.append(
                    [
                        Paragraph(key.replace("_", " ").title(), styles["body"]),
                        Paragraph(
                            f"{_format_money(breakdown.get(key) or 0, locale)} {ccy}".strip(),
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
                Paragraph(_t(locale, "sales_contract.headings.instalments", "Instalments"), styles["heading"]),
            ]
        )
        inst_rows: list[list[Any]] = [
            [
                Paragraph(_t(locale, "sales_contract.instalment_columns.sequence", "#"), styles["label"]),
                Paragraph(_t(locale, "sales_contract.instalment_columns.milestone", "Milestone"), styles["label"]),
                Paragraph(_t(locale, "sales_contract.instalment_columns.due_date", "Due Date"), styles["label"]),
                Paragraph(_t(locale, "sales_contract.instalment_columns.amount", "Amount"), styles["label"]),
                Paragraph(_t(locale, "sales_contract.instalment_columns.currency", "Currency"), styles["label"]),
            ]
        ]
        sched_ccy = _attr(payment_schedule, "currency", "") or ccy
        for inst in instalments:
            inst_rows.append(
                [
                    Paragraph(str(_attr(inst, "sequence", "")), styles["body"]),
                    Paragraph(
                        str(_attr(inst, "milestone_label", "") or _attr(inst, "milestone_event", "")), styles["body"]
                    ),
                    Paragraph(_format_date(_attr(inst, "due_date", None), locale), styles["body"]),
                    Paragraph(_format_money(_attr(inst, "amount", Decimal("0")), locale), styles["body"]),
                    Paragraph(str(sched_ccy), styles["body"]),
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
            Paragraph(_t(locale, "sales_contract.headings.regulatory", "Regulatory Disclosures"), styles["heading"]),
            Paragraph(
                f"<b>{clause_data.get('title', '')}</b>",
                styles["subtitle"],
            ),
            Paragraph(clause_data.get("intro", "") or "", styles["body"]),
            Spacer(1, 3 * mm),
        ]
    )
    for clause in clause_data.get("clauses", []) or []:
        story.append(
            KeepTogether(
                [
                    Paragraph(str(clause.get("heading", "") or ""), styles["clause_heading"]),
                    Paragraph(
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
            Paragraph(_t(locale, "sales_contract.headings.signatures", "Signatures"), styles["heading"]),
            Paragraph(note, styles["body"]),
            Spacer(1, 14 * mm),
            Table(
                [
                    [
                        Paragraph(
                            f"{_t(locale, 'common.buyer_signature', 'Buyer Signature')}<br/>"
                            f"________________________________",
                            styles["body"],
                        ),
                        Paragraph(
                            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}<br/>"
                            f"________________________________",
                            styles["body"],
                        ),
                    ]
                ],
                colWidths=[75 * mm, 75 * mm],
            ),
        ]
    )

    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 3 — Payment Receipt
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
            Paragraph(_t(locale, "payment_receipt.headings.spa_ref", "Agreement No."), styles["label"]),
            Paragraph(str(_attr(sales_contract, "contract_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "payment_receipt.headings.instalment", "Instalment"), styles["label"]),
            Paragraph(f"#{_attr(instalment, 'sequence', '')}", styles["body"]),
        ],
        [
            Paragraph(_t(locale, "payment_receipt.headings.milestone", "Milestone"), styles["label"]),
            Paragraph(
                str(_attr(instalment, "milestone_label", "") or _attr(instalment, "milestone_event", "")),
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "payment_receipt.headings.amount_paid", "Amount Paid"), styles["label"]),
            Paragraph(
                f"{_format_money(amount_paid, locale)} {ccy}".strip(),
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "payment_receipt.headings.payment_method", "Payment Method"), styles["label"]),
            Paragraph(str(payment_method or "—"), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "payment_receipt.headings.payment_ref", "Payment Reference"), styles["label"]),
            Paragraph(str(payment_ref or "—"), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "payment_receipt.headings.paid_at", "Paid On"), styles["label"]),
            Paragraph(
                _format_date(_attr(instalment, "paid_at", None), locale) or "—",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "payment_receipt.headings.outstanding", "Outstanding Balance"), styles["label"]),
            Paragraph(
                f"{_format_money(outstanding, locale)} {ccy}".strip(),
                styles["body"],
            ),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        Paragraph(_t(locale, "payment_receipt.title", "Payment Receipt"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "payment_receipt.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 8 * mm),
        Paragraph(_t(locale, "payment_receipt.footer_note", ""), styles["small"]),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 4 — Handover Certificate
# ════════════════════════════════════════════════════════════════════════


def render_handover_certificate_pdf(
    handover: Any,
    sales_contract: Any,
    snag_count: int,
    plot: Any,
    development: Any,
    locale: str = "en",
) -> bytes:
    """Certificate of handover — buyer signs to accept the unit."""
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
            Paragraph(_t(locale, "handover_certificate.headings.spa_ref", "Agreement No."), styles["label"]),
            Paragraph(str(_attr(sales_contract, "contract_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "handover_certificate.headings.completed_at", "Handover Date"), styles["label"]),
            Paragraph(
                _format_date(_attr(handover, "completed_at", None), locale)
                or _format_date(_attr(handover, "scheduled_at", None), locale)
                or "—",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "handover_certificate.headings.snag_count", "Open Snags"), styles["label"]),
            Paragraph(str(int(snag_count or 0)), styles["body"]),
        ],
        [
            Paragraph(
                _t(locale, "handover_certificate.headings.keys_handed_over", "Keys Handed Over"), styles["label"]
            ),
            Paragraph(
                _format_date(_attr(handover, "keys_handed_over_at", None), locale) or "—",
                styles["body"],
            ),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        Paragraph(_t(locale, "handover_certificate.title", "Certificate of Handover"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "handover_certificate.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        Paragraph(
            _t(locale, "handover_certificate.headings.developer_declaration", "Developer's Declaration"),
            styles["heading"],
        ),
        Paragraph(
            _t(locale, "handover_certificate.developer_declaration_text", ""),
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        Paragraph(
            _t(locale, "handover_certificate.headings.buyer_acceptance", "Buyer's Acceptance"),
            styles["heading"],
        ),
        Paragraph(
            _t(locale, "handover_certificate.buyer_acceptance_text", ""),
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        Paragraph(
            _t(locale, "handover_certificate.snag_note", ""),
            styles["small"],
        ),
        Spacer(1, 14 * mm),
        Table(
            [
                [
                    Paragraph(
                        f"{_t(locale, 'common.buyer_signature', 'Buyer Signature')}<br/>"
                        "________________________________",
                        styles["body"],
                    ),
                    Paragraph(
                        f"{_t(locale, 'common.developer_signature', 'Developer Signature')}<br/>"
                        "________________________________",
                        styles["body"],
                    ),
                ]
            ],
            colWidths=[75 * mm, 75 * mm],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 5 — Warranty Certificate
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
    """Warranty certificate — typically structural 10y, finishing 1y."""
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
            Paragraph(_t(locale, "warranty_certificate.headings.spa_ref", "Agreement No."), styles["label"]),
            Paragraph(str(_attr(sales_contract, "contract_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "warranty_certificate.headings.handover_date", "Handover Date"), styles["label"]),
            Paragraph(handover_iso or "—", styles["body"]),
        ],
        [
            Paragraph(
                _t(locale, "warranty_certificate.headings.structural_period", "Structural Period"), styles["label"]
            ),
            Paragraph(f"{int(structural_warranty_years)}y", styles["body"]),
        ],
        [
            Paragraph(
                _t(locale, "warranty_certificate.headings.finishing_period", "Finishing Period"), styles["label"]
            ),
            Paragraph(f"{int(finishing_warranty_years)}y", styles["body"]),
        ],
        [
            Paragraph(_t(locale, "warranty_certificate.headings.warranty_expiry", "Warranty Expiry"), styles["label"]),
            Paragraph(expiry_iso or "—", styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        Paragraph(_t(locale, "warranty_certificate.title", "Warranty Certificate"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "warranty_certificate.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        Paragraph(_t(locale, "warranty_certificate.headings.structural", "Structural Warranty"), styles["heading"]),
        Paragraph(
            _t(locale, "warranty_certificate.structural_text", "").replace(
                "{years}",
                str(int(structural_warranty_years)),
            ),
            styles["body"],
        ),
        Spacer(1, 3 * mm),
        Paragraph(_t(locale, "warranty_certificate.headings.finishing", "Finishing Warranty"), styles["heading"]),
        Paragraph(
            _t(locale, "warranty_certificate.finishing_text", "").replace(
                "{years}",
                str(int(finishing_warranty_years)),
            ),
            styles["body"],
        ),
        Spacer(1, 3 * mm),
        Paragraph(_t(locale, "warranty_certificate.headings.exclusions", "Exclusions"), styles["heading"]),
        Paragraph(_t(locale, "warranty_certificate.exclusions_text", ""), styles["body"]),
        Spacer(1, 3 * mm),
        Paragraph(_t(locale, "warranty_certificate.claim_procedure", ""), styles["small"]),
        Spacer(1, 14 * mm),
        Paragraph(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 6 — NOC (No Objection Certificate)
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
    """NOC — developer's permission for the buyer to resell."""
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
            Paragraph(_t(locale, "noc.headings.spa_ref", "Agreement No."), styles["label"]),
            Paragraph(str(_attr(sales_contract, "contract_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "noc.headings.requested_by", "Requested By"), styles["label"]),
            Paragraph(str(requested_by or "—"), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "common.date", "Date"), styles["label"]),
            Paragraph(issued_at, styles["body"]),
        ],
        [
            Paragraph(_t(locale, "noc.headings.validity", "Validity"), styles["label"]),
            Paragraph(
                _t(locale, "noc.validity_text", "Valid for {days} days from the date of issue.").replace(
                    "{days}",
                    str(int(validity_days)),
                )
                + f" ({valid_until})",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "noc.headings.purpose", "Purpose"), styles["label"]),
            Paragraph(_t(locale, "noc.purpose_text", ""), styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        Paragraph(_t(locale, "noc.title", "No Objection Certificate"), styles["title"]),
        Paragraph(_t(locale, "noc.subtitle", ""), styles["subtitle"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "noc.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        Paragraph(_t(locale, "noc.no_outstanding", ""), styles["body"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "noc.developer_statement", ""), styles["body"]),
        Spacer(1, 14 * mm),
        Paragraph(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 7 — Tenant Lease Agreement
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
    duck-typed shape — works against ORM rows OR dicts) and emits a
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
    start_date = _format_date(_attr(lease, "start_date", None), locale) or "—"
    end_date = _format_date(_attr(lease, "end_date", None), locale) or "—"
    term_months = _attr(lease, "term_months", 12)

    tenant_lines = "<br/>".join(
        f"{_attr(t, 'full_name', '')} ({_attr(t, 'email', '')})"
        for t in (tenants or [])
        if _attr(t, "full_name", "") or _attr(t, "email", "")
    )

    rows = [
        [
            Paragraph(_t(locale, "tenant_lease_agreement.headings.lease_number", "Lease No."), styles["label"]),
            Paragraph(str(_attr(lease, "lease_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "tenant_lease_agreement.headings.tenant", "Tenant"), styles["label"]),
            Paragraph(tenant_lines or "—", styles["body"]),
        ],
        [
            Paragraph(_t(locale, "tenant_lease_agreement.headings.property", "Property"), styles["label"]),
            Paragraph(
                f"{_development_name(development)} — "
                f"{_attr(plot, 'plot_number', '')} "
                f"({_attr(plot, 'area_m2', '')} m²)",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "tenant_lease_agreement.headings.term", "Term"), styles["label"]),
            Paragraph(
                f"{int(term_months or 0)} months — {start_date} → {end_date}",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "tenant_lease_agreement.headings.monthly_rent", "Monthly Rent"), styles["label"]),
            Paragraph(
                f"{_format_money(monthly_rent, locale)} {ccy}".strip(),
                styles["body"],
            ),
        ],
        [
            Paragraph(
                _t(locale, "tenant_lease_agreement.headings.security_deposit", "Security Deposit"), styles["label"]
            ),
            Paragraph(
                f"{_format_money(security_deposit, locale)} {ccy}".strip(),
                styles["body"],
            ),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        Paragraph(_t(locale, "tenant_lease_agreement.title", "Tenant Lease Agreement"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "tenant_lease_agreement.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        Paragraph(_t(locale, "tenant_lease_agreement.headings.use_clause", "Use of the Property"), styles["heading"]),
        Paragraph(_t(locale, "tenant_lease_agreement.use_clause_text", ""), styles["body"]),
        Paragraph(_t(locale, "tenant_lease_agreement.headings.maintenance", "Maintenance"), styles["heading"]),
        Paragraph(_t(locale, "tenant_lease_agreement.maintenance_text", ""), styles["body"]),
        Paragraph(_t(locale, "tenant_lease_agreement.headings.termination", "Termination"), styles["heading"]),
        Paragraph(_t(locale, "tenant_lease_agreement.termination_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        Table(
            [
                [
                    Paragraph(
                        f"{_t(locale, 'tenant_lease_agreement.tenant_signature', 'Tenant Signature')}<br/>"
                        "________________________________",
                        styles["body"],
                    ),
                    Paragraph(
                        f"{_t(locale, 'common.developer_signature', 'Developer Signature')}<br/>"
                        "________________________________",
                        styles["body"],
                    ),
                ]
            ],
            colWidths=[75 * mm, 75 * mm],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 8 — Move-in Checklist (room-by-room condition report)
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

    Companion to the handover certificate — focuses on furnishings /
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
        Paragraph(_t(locale, "move_in_checklist.title", "Move-in Checklist"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "move_in_checklist.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
    ]

    meta_rows = [
        [
            Paragraph(_t(locale, "move_in_checklist.headings.spa_ref", "Agreement No."), styles["label"]),
            Paragraph(str(_attr(sales_contract, "contract_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "move_in_checklist.headings.inspection_date", "Inspection Date"), styles["label"]),
            Paragraph(
                _format_date(_attr(handover, "completed_at", None), locale)
                or _format_date(_attr(handover, "scheduled_at", None), locale)
                or "—",
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
            room_name = _attr(room, "name", "") or "—"
            items = _attr(room, "items", None) or []
            story.append(Paragraph(str(room_name), styles["heading"]))
            room_rows: list[list[Any]] = [
                [
                    Paragraph(_t(locale, "move_in_checklist.columns.item", "Item"), styles["label"]),
                    Paragraph(_t(locale, "move_in_checklist.columns.condition", "Condition"), styles["label"]),
                    Paragraph(_t(locale, "move_in_checklist.columns.notes", "Notes"), styles["label"]),
                ]
            ]
            for it in items:
                room_rows.append(
                    [
                        Paragraph(str(_attr(it, "label", "") or "—"), styles["body"]),
                        Paragraph(str(_attr(it, "condition", "") or "—"), styles["body"]),
                        Paragraph(str(_attr(it, "notes", "") or ""), styles["body"]),
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
        story.append(Paragraph(_t(locale, "move_in_checklist.empty_rooms", "No room data supplied."), styles["small"]))

    story.extend(
        [
            Spacer(1, 6 * mm),
            Paragraph(_t(locale, "move_in_checklist.acceptance_text", ""), styles["body"]),
            Spacer(1, 14 * mm),
            Table(
                [
                    [
                        Paragraph(
                            f"{_t(locale, 'common.buyer_signature', 'Buyer Signature')}<br/>"
                            "________________________________",
                            styles["body"],
                        ),
                        Paragraph(
                            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}<br/>"
                            "________________________________",
                            styles["body"],
                        ),
                    ]
                ],
                colWidths=[75 * mm, 75 * mm],
            ),
        ]
    )
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 9 — Mortgage Clearance Letter
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
            Paragraph(_t(locale, "mortgage_clearance_letter.headings.bank", "Issued To (Bank)"), styles["label"]),
            Paragraph(str(bank_name or "—"), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "mortgage_clearance_letter.headings.spa_ref", "Agreement No."), styles["label"]),
            Paragraph(str(_attr(sales_contract, "contract_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "mortgage_clearance_letter.headings.unit", "Unit"), styles["label"]),
            Paragraph(
                f"{_development_name(development)} — {_attr(plot, 'plot_number', '')}",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "common.date", "Date"), styles["label"]),
            Paragraph(issued_at, styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        Paragraph(_t(locale, "mortgage_clearance_letter.title", "Mortgage Clearance Letter"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "mortgage_clearance_letter.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        Paragraph(_t(locale, "mortgage_clearance_letter.no_encumbrance_text", ""), styles["body"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "mortgage_clearance_letter.purpose_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        Paragraph(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 10 — Title Deed Transfer Request
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
        name = _attr(buyer, "full_name", "") or _attr(p, "full_name", "") or "—"
        pct = _attr(p, "ownership_pct", "") or ""
        party_names.append(f"{name} ({pct}%)" if pct else str(name))

    rows = [
        [
            Paragraph(_t(locale, "title_deed_transfer_request.headings.registry", "Land Registry"), styles["label"]),
            Paragraph(str(registry_name or "—"), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "title_deed_transfer_request.headings.spa_ref", "Agreement No."), styles["label"]),
            Paragraph(str(_attr(sales_contract, "contract_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "title_deed_transfer_request.headings.unit", "Unit"), styles["label"]),
            Paragraph(
                f"{_development_name(development)} — "
                f"{_attr(plot, 'plot_number', '')} "
                f"({_attr(plot, 'area_m2', '')} m²)",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "title_deed_transfer_request.headings.new_owners", "New Owner(s)"), styles["label"]),
            Paragraph(
                "<br/>".join(party_names) if party_names else "—",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "common.date", "Date"), styles["label"]),
            Paragraph(date.today().isoformat(), styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        Paragraph(_t(locale, "title_deed_transfer_request.title", "Title Deed Transfer Request"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "title_deed_transfer_request.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        Paragraph(_t(locale, "title_deed_transfer_request.headings.request_body", "Request"), styles["heading"]),
        Paragraph(_t(locale, "title_deed_transfer_request.request_text", ""), styles["body"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "title_deed_transfer_request.headings.attachments", "Attachments"), styles["heading"]),
        Paragraph(_t(locale, "title_deed_transfer_request.attachments_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        Paragraph(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 11 — Escrow Release Authorization
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
            Paragraph(
                _t(locale, "escrow_release_authorization.headings.escrow_account", "Escrow Account No."),
                styles["label"],
            ),
            Paragraph(str(escrow_account_no or "—"), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "escrow_release_authorization.headings.spa_ref", "Agreement No."), styles["label"]),
            Paragraph(str(_attr(sales_contract, "contract_number", "—")), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "escrow_release_authorization.headings.unit", "Unit"), styles["label"]),
            Paragraph(
                f"{_development_name(development)} — {_attr(plot, 'plot_number', '')}",
                styles["body"],
            ),
        ],
        [
            Paragraph(
                _t(locale, "escrow_release_authorization.headings.amount_to_release", "Amount to Release"),
                styles["label"],
            ),
            Paragraph(
                f"{_format_money(amount, locale)} {ccy}".strip(),
                styles["body"],
            ),
        ],
        [
            Paragraph(
                _t(locale, "escrow_release_authorization.headings.release_reason", "Release Reason"), styles["label"]
            ),
            Paragraph(str(release_reason or "—"), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "common.date", "Date"), styles["label"]),
            Paragraph(date.today().isoformat(), styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        Paragraph(_t(locale, "escrow_release_authorization.title", "Escrow Release Authorization"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "escrow_release_authorization.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        Paragraph(_t(locale, "escrow_release_authorization.instruction_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        Paragraph(
            f"{_t(locale, 'common.developer_signature', 'Developer Signature')}: ________________________________",
            styles["body"],
        ),
    ]
    return _render(doc, frame, story, ctx, buf)


# ════════════════════════════════════════════════════════════════════════
#  Generator 12 — Refund Authorization
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

    Either ``sales_contract`` OR ``reservation`` may be the source — the
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

    ref_value = _attr(sales_contract, "contract_number", "") or _attr(reservation, "reservation_number", "") or "—"

    rows = [
        [
            Paragraph(_t(locale, "refund_authorization.headings.reference", "Reference"), styles["label"]),
            Paragraph(str(ref_value), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "refund_authorization.headings.unit", "Unit"), styles["label"]),
            Paragraph(
                f"{_development_name(development)} — {_attr(plot, 'plot_number', '')}",
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "refund_authorization.headings.amount", "Refund Amount"), styles["label"]),
            Paragraph(
                f"{_format_money(refund_amount, locale)} {ccy}".strip(),
                styles["body"],
            ),
        ],
        [
            Paragraph(_t(locale, "refund_authorization.headings.reason", "Reason"), styles["label"]),
            Paragraph(str(refund_reason or "—"), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "refund_authorization.headings.payment_method", "Payment Method"), styles["label"]),
            Paragraph(str(payment_method or "—"), styles["body"]),
        ],
        [
            Paragraph(_t(locale, "common.date", "Date"), styles["label"]),
            Paragraph(date.today().isoformat(), styles["body"]),
        ],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 100 * mm])
    tbl.setStyle(_kv_table_style())

    story: list[Any] = [
        Paragraph(_t(locale, "refund_authorization.title", "Refund Authorization"), styles["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_t(locale, "refund_authorization.intro", ""), styles["body"]),
        Spacer(1, 4 * mm),
        tbl,
        Spacer(1, 6 * mm),
        Paragraph(_t(locale, "refund_authorization.authorisation_text", ""), styles["body"]),
        Spacer(1, 14 * mm),
        Paragraph(
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
