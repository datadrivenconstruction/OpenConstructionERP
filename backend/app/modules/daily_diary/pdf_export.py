# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PDF report generation for a single daily site diary.

Renders one diary into a clean, single-document PDF using reportlab
(already a platform dependency - see ``boq/pdf_export.py`` for the same
conventions). The layout is:

- The firm's letterhead on page one, when the company profile has one.
- Header band: project name + diary date + status badge.
- Overview: site supervisor, labour / equipment counts, completeness.
- Weather: the day's weather readings (temperature, wind, precipitation,
  conditions), falling back to the diary's ``weather_summary`` snapshot
  when no granular records exist.
- Work performed / events: diary entries grouped by type (work,
  deliveries, inspections, incidents, visitors, general notes).
- Notes: the free-text diary notes block.
- Footer: author / supervisor line plus a generated-at timestamp and a
  page number on every page.

Localization: every fixed string comes from the module-local catalog in
:mod:`app.modules.daily_diary.pdf_translations` (English default plus
German), selected by the ``locale`` argument of
:func:`generate_diary_pdf`. Dates follow the locale's format and the
``weather_summary`` snapshot renders as a human sentence fragment
("20 °C, clear" / "20 °C, klar"), never as raw dictionary keys.

Security note (mirrors BUG-PDF01 / BUG-PDF02 in ``boq/pdf_export.py``):
    ReportLab's ``Paragraph`` parses a subset of HTML. Any string that
    originates outside the application (entry titles, descriptions,
    location labels, weather text, the project name, notes) is escaped
    with ``html.escape`` via :func:`_safe_para` before it reaches the
    parser, so a payload like ``<font color="white">x</font>`` renders
    inert and ``<img onerror=...>`` cannot crash paraparser.
"""

from __future__ import annotations

import html
import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

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
    pdf_room_beside,
    pdf_style_for_text,
    register_pdf_fonts,
)
from app.modules.daily_diary.pdf_translations import (
    DEFAULT_PDF_LOCALE,
    entry_type_label,
    format_iso_date,
    normalize_pdf_locale,
    status_caps,
    status_label,
    tr,
    weather_summary_text,
)
from app.modules.daily_diary.pdf_translations import (
    fmt_number as _fmt_number,
)

# Register the bundled Unicode (DejaVu) faces so Cyrillic / Greek / accented
# Latin text renders as glyphs rather than tofu boxes. Idempotent and safe.
register_pdf_fonts()

# Page geometry (A4, matching the BOQ export so both reports look related).
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 20 * mm
MARGIN_RIGHT = 20 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 18 * mm
USABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

# Display order for the entry sections (work first, housekeeping last).
# The per-locale section labels live in pdf_translations.entry_type_label.
_ENTRY_TYPE_ORDER: tuple[str, ...] = (
    "completion",
    "event",
    "delivery",
    "inspection_summary",
    "incident_summary",
    "visitor",
    "photo_note",
    "general",
)


def _safe_para(text: Any, style: ParagraphStyle) -> Paragraph:
    """Construct a ``Paragraph`` from possibly-untrusted user input.

    HTML metacharacters in ``text`` are escaped via ``html.escape`` so
    ReportLab's paraparser sees inert characters, not markup. ``None``
    becomes an empty string; other non-string values are coerced through
    ``str`` before escaping.

    The face is chosen here too, for the same reason the escaping is: this is
    the one place the diary's user-written strings pass through. A site diary
    kept on a Chinese job is written in Chinese.

    Args:
        text: The value to render. May be ``None`` or any type.
        style: The paragraph style to apply.

    Returns:
        A ``Paragraph`` with the escaped text.
    """
    if text is None:
        rendered = ""
    elif isinstance(text, str):
        rendered = text
    else:
        rendered = str(text)
    return Paragraph(html.escape(rendered, quote=True), pdf_style_for_text(style, rendered))


def _build_styles() -> dict[str, ParagraphStyle]:
    """Build the paragraph styles used throughout the diary PDF."""
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "Brand",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=16,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "header_date": ParagraphStyle(
            "HeaderDate",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=11,
            textColor=colors.HexColor("#e8e8ee"),
            alignment=TA_LEFT,
        ),
        "status": ParagraphStyle(
            "Status",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=11,
            textColor=colors.white,
            alignment=TA_RIGHT,
        ),
        "section": ParagraphStyle(
            "Section",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=11,
            textColor=colors.HexColor("#16213e"),
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "label": ParagraphStyle(
            "Label",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=9,
            textColor=colors.HexColor("#666666"),
        ),
        "value": ParagraphStyle(
            "Value",
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
            leading=11,
        ),
        "cell_head": ParagraphStyle(
            "CellHead",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=8,
            textColor=colors.white,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=9,
            textColor=colors.HexColor("#333333"),
            leading=13,
        ),
        "empty": ParagraphStyle(
            "Empty",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=9,
            textColor=colors.HexColor("#999999"),
        ),
    }


def _make_footer(
    author_line: str,
    generated_date: str,
    locale: str,
    *,
    letterhead_on_first_page: bool = False,
    appearance: dict[str, Any] | None = None,
) -> Any:
    """Return an ``onPage`` callback drawing the footer on every page.

    The footer follows the document appearance for the daily report, as the
    RFI's does: a saved footer line replaces the brand and timestamp line, the
    footer colour colours the footer, and page numbers can be switched off.

    Args:
        author_line: Pre-escaped, plain-text author / supervisor line.
        generated_date: The generated-at timestamp string.
        locale: PDF locale for the fixed footer strings.
        letterhead_on_first_page: Whether page one opens with the letterhead,
            decided once by the caller. The letterhead already carries the
            logo, so the small header logo is left off that page.
        appearance: The document appearance, read once for the whole document.

    Returns:
        A ``func(canvas, doc)`` callable for a reportlab PageTemplate.
    """
    look = appearance or {}
    footer_colour = look.get("footer_color") or "#999999"
    custom_footer = str(look.get("footer_text") or "").strip()
    show_page_numbers = look.get("show_page_numbers", True) is not False

    def _footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cccccc"))
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_LEFT, 13 * mm, PAGE_WIDTH - MARGIN_RIGHT, 13 * mm)
        # Footer carries the workspace brand (issue #284) plus the supervisor
        # line; the brand falls back to the default name when none is set.
        # All three footer strings come from tr(locale, ...) and may be in any
        # script (Thai, Devanagari, CJK). Paragraph is the only route through
        # which reportlab's shaper acts on complex scripts.
        brand = branded_cover_brand()
        footer_style = ParagraphStyle(
            "_diaryFooter",
            fontName=BODY_FONT,
            fontSize=7,
            leading=7,
            textColor=colors.HexColor(footer_colour),
        )
        # Both footer lines are anchored by the top of their box, so a wrapped
        # one grows downward: the author line would come down over the brand
        # line and the brand line off the bottom edge. Each is fitted onto a
        # single line instead, the author line into the room beside the page
        # number it shares a baseline with.
        page_line = tr(locale, "footer_page", page=doc.page) if show_page_numbers else ""
        full_width = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
        # Supervisor / author line (user data, could be non-Latin).
        left_text, _left_face, left_size = pdf_fit_line(
            (author_line or brand)[:120], pdf_room_beside(full_width, page_line), base=BODY_FONT
        )
        p1 = Paragraph(html.escape(left_text, quote=True), pdf_fitted_style(footer_style, left_text, left_size))
        pw1, ph1 = p1.wrapOn(canvas, full_width, 20)
        p1.drawOn(canvas, MARGIN_LEFT, 9 * mm - ph1 + 7 * 0.22)
        # Brand + generated timestamp line, or the workspace's own footer line,
        # printed as saved and untranslated.
        generated_line = tr(locale, "footer_generated", timestamp=generated_date)
        brand_line, _brand_face, brand_size = pdf_fit_line(
            custom_footer or brand,
            full_width,
            suffix="" if custom_footer else f"  |  {generated_line}",
            base=BODY_FONT,
        )
        p2 = Paragraph(html.escape(brand_line, quote=True), pdf_fitted_style(footer_style, brand_line, brand_size))
        pw2, ph2 = p2.wrapOn(canvas, full_width, 20)
        p2.drawOn(canvas, MARGIN_LEFT, 6 * mm - ph2 + 7 * 0.22)
        # Page number (locale-translated, could be Thai/Devanagari). Right
        # aligned inside the full width: a Paragraph wraps to the width it is
        # offered, not to its text, so offsetting by that width put the page
        # number at the left margin on top of the supervisor line.
        if page_line:
            page_style = ParagraphStyle("_diaryFooterPage", parent=footer_style, alignment=TA_RIGHT)
            p3 = Paragraph(html.escape(page_line, quote=True), pdf_style_for_text(page_style, page_line))
            pw3, ph3 = p3.wrapOn(canvas, PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT, 20)
            p3.drawOn(canvas, MARGIN_LEFT, 9 * mm - ph3 + 7 * 0.22)
        canvas.restoreState()
        # The uploaded white-label logo (if any) appears top-right in the header
        # margin on every page; the dark title band stays inside the content
        # frame, so they do not overlap. Issue #284 follow-up.
        if not (letterhead_on_first_page and doc.page == 1):
            branded_header_logo(canvas, doc)

    return _footer


def _build_header(
    project_name: str,
    diary_date: str,
    status: str,
    styles: dict[str, ParagraphStyle],
    locale: str,
) -> list[Any]:
    """Build the dark header band with project, date and status."""
    doc_title = tr(locale, "doc_title")
    status_text = status_caps(status_label(status, locale), locale)
    header = Table(
        [
            [
                _safe_para(project_name or doc_title, styles["brand"]),
                Paragraph(html.escape(status_text, quote=True), pdf_style_for_text(styles["status"], status_text)),
            ],
            [
                Paragraph(
                    f"{html.escape(doc_title)} &nbsp;&middot;&nbsp; {html.escape(diary_date)}",
                    pdf_style_for_text(styles["header_date"], doc_title),
                ),
                "",
            ],
        ],
        colWidths=[USABLE_WIDTH * 0.7, USABLE_WIDTH * 0.3],
    )
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#16213e")),
                ("SPAN", (1, 0), (1, 1)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (0, 0), 4 * mm),
                ("BOTTOMPADDING", (0, 1), (0, 1), 4 * mm),
            ]
        )
    )
    return [header, Spacer(1, 5 * mm)]


def _build_overview(
    diary: Any,
    supervisor_name: str | None,
    completeness: Decimal | float | None,
    styles: dict[str, ParagraphStyle],
    locale: str,
) -> list[Any]:
    """Build the overview block (supervisor, labour, equipment, score)."""
    completeness_text = "-"
    if completeness is not None:
        try:
            completeness_text = tr(locale, "percent", value=f"{float(completeness) * 100:.0f}")
        except (TypeError, ValueError):
            completeness_text = "-"

    rows = [
        [
            Paragraph(tr(locale, "site_supervisor"), styles["label"]),
            _safe_para(supervisor_name or tr(locale, "not_recorded"), styles["value"]),
            Paragraph(tr(locale, "labour_on_site"), styles["label"]),
            Paragraph(str(getattr(diary, "labour_count", 0) or 0), styles["value"]),
        ],
        [
            Paragraph(tr(locale, "completeness"), styles["label"]),
            Paragraph(completeness_text, styles["value"]),
            Paragraph(tr(locale, "equipment_on_site"), styles["label"]),
            Paragraph(str(getattr(diary, "equipment_count", 0) or 0), styles["value"]),
        ],
    ]
    table = Table(
        rows,
        colWidths=[USABLE_WIDTH * 0.22, USABLE_WIDTH * 0.28, USABLE_WIDTH * 0.22, USABLE_WIDTH * 0.28],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f6fa")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#eeeeee")),
            ]
        )
    )
    return [Paragraph(tr(locale, "overview"), styles["section"]), table]


def _build_weather(
    diary: Any,
    weather_records: list[Any],
    styles: dict[str, ParagraphStyle],
    locale: str,
) -> list[Any]:
    """Build the weather section.

    Prefers granular ``WeatherRecord`` rows. When none exist, falls back
    to the diary's ``weather_summary`` JSON snapshot rendered as a human
    sentence fragment (never raw dictionary keys), and finally to an
    empty-state line.
    """
    flow: list[Any] = [Paragraph(tr(locale, "weather"), styles["section"])]

    if weather_records:
        header = [
            Paragraph(tr(locale, "weather_time"), styles["cell_head"]),
            Paragraph(tr(locale, "weather_source"), styles["cell_head"]),
            Paragraph(tr(locale, "weather_temp"), styles["cell_head"]),
            Paragraph(tr(locale, "weather_wind"), styles["cell_head"]),
            Paragraph(tr(locale, "weather_precip"), styles["cell_head"]),
            Paragraph(tr(locale, "weather_conditions"), styles["cell_head"]),
        ]
        data: list[list[Any]] = [header]
        for rec in weather_records:
            captured = getattr(rec, "captured_at", None)
            time_text = captured.strftime("%H:%M") if isinstance(captured, datetime) else "-"
            data.append(
                [
                    Paragraph(time_text, styles["cell"]),
                    _safe_para(getattr(rec, "source", "") or "-", styles["cell"]),
                    Paragraph(_fmt_number(getattr(rec, "temperature_c", None), locale=locale), styles["cell"]),
                    Paragraph(_fmt_number(getattr(rec, "wind_speed_kmh", None), locale=locale), styles["cell"]),
                    Paragraph(_fmt_number(getattr(rec, "precipitation_mm", None), locale=locale), styles["cell"]),
                    _safe_para(getattr(rec, "conditions_text", None) or "-", styles["cell"]),
                ]
            )
        table = Table(
            data,
            colWidths=[
                USABLE_WIDTH * 0.12,
                USABLE_WIDTH * 0.16,
                USABLE_WIDTH * 0.14,
                USABLE_WIDTH * 0.16,
                USABLE_WIDTH * 0.16,
                USABLE_WIDTH * 0.26,
            ],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f6fa")]),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ]
            )
        )
        flow.append(table)
        return flow

    summary = getattr(diary, "weather_summary", None) or {}
    summary_line = weather_summary_text(summary, locale) if isinstance(summary, dict) else ""
    if summary_line:
        flow.append(Paragraph(html.escape(summary_line, quote=True), pdf_style_for_text(styles["body"], summary_line)))
    else:
        flow.append(Paragraph(tr(locale, "weather_empty"), styles["empty"]))
    return flow


def _build_entries(
    entries: list[Any],
    styles: dict[str, ParagraphStyle],
    locale: str,
) -> list[Any]:
    """Build the grouped diary-entry sections (work, deliveries, etc.)."""
    flow: list[Any] = [Paragraph(tr(locale, "site_record"), styles["section"])]

    if not entries:
        flow.append(Paragraph(tr(locale, "entries_empty"), styles["empty"]))
        return flow

    grouped: dict[str, list[Any]] = {}
    for entry in entries:
        grouped.setdefault(getattr(entry, "entry_type", "general") or "general", []).append(entry)

    # Stable ordering: known types first in display order, then any others.
    ordered_types = [t for t in _ENTRY_TYPE_ORDER if t in grouped]
    ordered_types += [t for t in grouped if t not in _ENTRY_TYPE_ORDER]

    for entry_type in ordered_types:
        bucket = sorted(
            grouped[entry_type],
            key=lambda e: getattr(e, "entry_time", None) or datetime.min.replace(tzinfo=UTC),
        )
        label = entry_type_label(entry_type, locale)
        block: list[Any] = [
            Paragraph(
                f"<b>{html.escape(label)}</b> ({len(bucket)})",
                styles["body"],
            )
        ]
        rows: list[list[Any]] = []
        for entry in bucket:
            etime = getattr(entry, "entry_time", None)
            time_text = etime.strftime("%H:%M") if isinstance(etime, datetime) else ""
            title = getattr(entry, "title", "") or ""
            description = getattr(entry, "description", "") or ""
            detail = title
            if description:
                detail = (
                    f"<b>{html.escape(title)}</b><br/>{html.escape(description)}" if title else html.escape(description)
                )
            else:
                detail = html.escape(title) if title else "-"
            rows.append(
                [
                    Paragraph(html.escape(time_text), styles["cell"]),
                    # The face comes from the unescaped source strings, which
                    # is what the entry was actually written in.
                    Paragraph(detail, pdf_style_for_text(styles["cell"], f"{title}{description}")),
                ]
            )
        table = Table(rows, colWidths=[USABLE_WIDTH * 0.12, USABLE_WIDTH * 0.88])
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#eeeeee")),
                ]
            )
        )
        block.append(table)
        block.append(Spacer(1, 3 * mm))
        flow.append(KeepTogether(block))

    return flow


def _build_notes(diary: Any, styles: dict[str, ParagraphStyle], locale: str) -> list[Any]:
    """Build the free-text notes block."""
    notes = (getattr(diary, "notes", None) or "").strip()
    flow: list[Any] = [Paragraph(tr(locale, "notes"), styles["section"])]
    if notes:
        # Preserve author line breaks as <br/> after escaping.
        escaped = html.escape(notes).replace("\n", "<br/>")
        flow.append(Paragraph(escaped, pdf_style_for_text(styles["body"], notes)))
    else:
        flow.append(Paragraph(tr(locale, "notes_empty"), styles["empty"]))
    return flow


def generate_diary_pdf(
    diary: Any,
    *,
    project_name: str,
    entries: list[Any] | None = None,
    weather_records: list[Any] | None = None,
    supervisor_name: str | None = None,
    completeness: Decimal | float | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
) -> bytes:
    """Render a single daily site diary into PDF bytes.

    Args:
        diary: The :class:`DailyDiary` ORM row (or any object exposing the
            same attributes: ``diary_date``, ``status``, ``labour_count``,
            ``equipment_count``, ``weather_summary``, ``notes``).
        project_name: Parent project name for the header.
        entries: Diary entries to render, grouped by type. Optional.
        weather_records: Granular weather readings for the day. Optional;
            falls back to ``diary.weather_summary`` when empty.
        supervisor_name: Display name of the site supervisor. Optional.
        completeness: Completeness score in the range ``0.0`` to ``1.0``.
        locale: Language for the document's fixed strings and date
            formats (``"en"`` / ``"de"``); region subtags are stripped
            and unsupported values fall back to English.

    Returns:
        The rendered PDF document as bytes (starts with ``b"%PDF"``).
    """
    entries = entries or []
    weather_records = weather_records or []
    styles = _build_styles()
    locale = normalize_pdf_locale(locale)

    diary_date = format_iso_date(str(getattr(diary, "diary_date", "") or ""), locale)
    status_text = str(getattr(diary, "status", "open") or "open")
    generated_date = datetime.now(tz=UTC).strftime(tr(locale, "datetime_format"))

    author_line = (
        tr(locale, "footer_supervisor", name=supervisor_name)
        if supervisor_name
        else tr(locale, "footer_supervisor_missing")
    )

    # The firm's letterhead, when the company profile has one. Decided once, so
    # the page callback can never put the logo on page one twice or not at all.
    # The frame pads 6pt on each side, so this is the width a flowable can use.
    letterhead = branded_letterhead(USABLE_WIDTH - 12, doc_type="daily_report")

    buffer = io.BytesIO()
    frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM,
        USABLE_WIDTH,
        PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM,
        id="body",
    )
    template = PageTemplate(
        id="body",
        frames=[frame],
        onPage=_make_footer(
            author_line,
            generated_date,
            locale,
            letterhead_on_first_page=letterhead is not None,
            appearance=branded_appearance(doc_type="daily_report"),
        ),
    )
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"{tr(locale, 'doc_title')} - {diary_date}",
        author=branded_doc_metadata()["author"],
        subject=tr(locale, "doc_title"),
        creator=branded_doc_metadata()["creator"],
        producer=branded_doc_metadata()["producer"],
        keywords=branded_doc_metadata()["keywords"],
    )
    doc.addPageTemplates([template])

    flowables: list[Any] = []
    if letterhead is not None:
        flowables.append(letterhead)
    flowables.extend(_build_header(project_name, diary_date, status_text, styles, locale))
    flowables.extend(_build_overview(diary, supervisor_name, completeness, styles, locale))
    flowables.extend(_build_weather(diary, weather_records, styles, locale))
    flowables.extend(_build_entries(entries, styles, locale))
    flowables.extend(_build_notes(diary, styles, locale))

    doc.build(flowables)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
