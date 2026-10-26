# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Index PDF of a handover dossier.

The index is the first thing a recipient opens: what the dossier covers (scope),
whether it passed its completeness checklist, which file in the ZIP is what
(with each file's SHA-256 so a copy can be checked against it), and the
resolved punch register with each photo's capture evidence.

Every label arrives in ``summary["labels"]`` already translated by the caller,
so the PDF reads in the requester's language. Free text from users goes through
the cover sheet's escaping paragraph helper.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_branding import branded_doc_metadata, branded_header_logo, branded_letterhead
from app.modules.closeout.cover_pdf import (
    _AMBER,
    _GREEN,
    _HEADER_BG,
    _RED,
    _ROW_ALT,
    USABLE_WIDTH,
    _safe_para,
    _styles,
)

_STATUS_COLOUR = {"passed": _GREEN, "warnings": _AMBER, "errors": _RED}


def _human_size(n: Any) -> str:
    try:
        size = float(n)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _table(rows: list[list[Any]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def render_dossier_index_pdf(summary: dict[str, Any]) -> bytes:
    """Render the dossier index.

    Args:
        summary: Plain dict with ``labels`` (translated strings), ``title``,
            ``project_name``, ``scope_label``, ``built_at``, ``check_status``
            (passed | warnings | errors), ``findings`` (list of
            ``{severity, message}``), ``files`` (list of ``{path, size_bytes,
            sha256}``) and ``punch`` (list of ``{title, status, photos,
            evidence}`` where ``evidence`` is a printable line or ``""``).

    Returns:
        PDF bytes.
    """
    labels: dict[str, str] = summary.get("labels") or {}

    def lab(key: str, fallback: str) -> str:
        return labels.get(key) or fallback

    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=lab("title", "Handover dossier"),
        **branded_doc_metadata(),
    )
    story: list[Any] = []
    story.append(_safe_para(summary.get("title") or lab("title", "Handover dossier"), styles["title"]))
    story.append(_safe_para(summary.get("project_name") or "", styles["subtitle"]))
    story.append(
        _safe_para(
            f"{lab('scope', 'Scope')}: {summary.get('scope_label') or '-'}   |   "
            f"{lab('built', 'Assembled')}: {summary.get('built_at') or '-'}",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 6 * mm))

    status = str(summary.get("check_status") or "passed")
    band_text = lab(f"status_{status}", status.upper())
    band = Table([[_safe_para(band_text, styles["banner"])]], colWidths=[USABLE_WIDTH])
    band.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _STATUS_COLOUR.get(status, _AMBER)),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    story.append(band)

    findings = [f for f in summary.get("findings") or [] if isinstance(f, dict)]
    if findings:
        story.append(_safe_para(lab("findings", "Open checklist findings"), styles["section"]))
        rows: list[list[Any]] = [
            [
                _safe_para(lab("severity", "Severity"), styles["cell_head"]),
                _safe_para(lab("finding", "Finding"), styles["cell_head"]),
            ]
        ]
        for f in findings:
            rows.append(
                [
                    _safe_para(lab(f"severity_{f.get('severity')}", str(f.get("severity") or "")), styles["cell"]),
                    _safe_para(f.get("message") or "", styles["cell"]),
                ]
            )
        story.append(_table(rows, [USABLE_WIDTH * 0.18, USABLE_WIDTH * 0.82]))

    story.append(_safe_para(lab("contents", "Contents"), styles["section"]))
    rows = [
        [
            _safe_para(lab("file", "File"), styles["cell_head"]),
            _safe_para(lab("size", "Size"), styles["cell_head"]),
            _safe_para("SHA-256", styles["cell_head"]),
        ]
    ]
    for entry in summary.get("files") or []:
        rows.append(
            [
                _safe_para(entry.get("path") or "", styles["cell"]),
                _safe_para(_human_size(entry.get("size_bytes")), styles["cell"]),
                _safe_para(str(entry.get("sha256") or "")[:16], styles["cell"]),
            ]
        )
    story.append(_table(rows, [USABLE_WIDTH * 0.58, USABLE_WIDTH * 0.14, USABLE_WIDTH * 0.28]))

    punch = [p for p in summary.get("punch") or [] if isinstance(p, dict)]
    if punch:
        story.append(_safe_para(lab("punch", "Resolved punch list"), styles["section"]))
        rows = [
            [
                _safe_para(lab("item", "Item"), styles["cell_head"]),
                _safe_para(lab("status", "Status"), styles["cell_head"]),
                _safe_para(lab("photos", "Photos"), styles["cell_head"]),
                _safe_para(lab("evidence", "Evidence"), styles["cell_head"]),
            ]
        ]
        for p in punch:
            rows.append(
                [
                    _safe_para(p.get("title") or "", styles["cell"]),
                    _safe_para(p.get("status") or "", styles["cell"]),
                    _safe_para(str(p.get("photos") or 0), styles["cell"]),
                    _safe_para(p.get("evidence") or "-", styles["cell"]),
                ]
            )
        story.append(_table(rows, [USABLE_WIDTH * 0.30, USABLE_WIDTH * 0.14, USABLE_WIDTH * 0.10, USABLE_WIDTH * 0.46]))

    letterhead = branded_letterhead(doc.width - 12, doc_type="closeout_cover")
    if letterhead is not None:
        story.insert(0, letterhead)

    def _first_page(canvas: Any, page_doc: Any) -> None:
        if letterhead is None:
            branded_header_logo(canvas, page_doc)

    doc.build(story, onFirstPage=_first_page, onLaterPages=branded_header_logo)
    return buf.getvalue()
