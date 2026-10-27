# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Signature blocks for generated PDFs: who signs, in what role, and when.

One block, one look across documents: a column per signer with the role, the
printed name, a line to sign on and a date line. Which roles a document asks
for depends on its type (a bill is prepared and approved, minutes are chaired
and taken) and a workspace can override that list per document type in the PDF
appearance settings (``signature_roles``) or switch the block off
(``show_signatures: false``).
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_style_for_text, register_pdf_fonts

#: Roles each document type asks to sign, in reading order.
DEFAULT_ROLES: dict[str, tuple[str, ...]] = {
    "boq": ("prepared_by", "checked_by", "approved_by"),
    "offer": ("contractor", "client"),
    "award_letter": ("client",),
    "acceptance_certificate": ("contractor", "client", "engineer"),
    "handover_certificate": ("contractor", "client", "engineer"),
    "meeting_minutes": ("chair", "minute_taker"),
}

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "signatures": "Signatures",
        "name": "Name",
        "signature": "Signature",
        "date": "Date",
        "prepared_by": "Prepared by",
        "checked_by": "Checked by",
        "approved_by": "Approved by",
        "contractor": "Contractor",
        "client": "Client",
        "engineer": "Engineer",
        "chair": "Chair",
        "minute_taker": "Minutes taken by",
    },
    "de": {
        "signatures": "Unterschriften",
        "name": "Name",
        "signature": "Unterschrift",
        "date": "Datum",
        "prepared_by": "Erstellt von",
        "checked_by": "Geprüft von",
        "approved_by": "Freigegeben von",
        "contractor": "Auftragnehmer",
        "client": "Auftraggeber",
        "engineer": "Bauleitung",
        "chair": "Sitzungsleitung",
        "minute_taker": "Protokoll",
    },
    "fr": {
        "signatures": "Signatures",
        "name": "Nom",
        "signature": "Signature",
        "date": "Date",
        "prepared_by": "Établi par",
        "checked_by": "Vérifié par",
        "approved_by": "Approuvé par",
        "contractor": "Entreprise",
        "client": "Maître d'ouvrage",
        "engineer": "Maître d'œuvre",
        "chair": "Président de séance",
        "minute_taker": "Secrétaire de séance",
    },
    "es": {
        "signatures": "Firmas",
        "name": "Nombre",
        "signature": "Firma",
        "date": "Fecha",
        "prepared_by": "Elaborado por",
        "checked_by": "Revisado por",
        "approved_by": "Aprobado por",
        "contractor": "Contratista",
        "client": "Cliente",
        "engineer": "Dirección de obra",
        "chair": "Presidencia",
        "minute_taker": "Secretaría",
    },
    "ru": {
        "signatures": "Подписи",
        "name": "ФИО",
        "signature": "Подпись",
        "date": "Дата",
        "prepared_by": "Составил",
        "checked_by": "Проверил",
        "approved_by": "Утвердил",
        "contractor": "Подрядчик",
        "client": "Заказчик",
        "engineer": "Технический надзор",
        "chair": "Председатель",
        "minute_taker": "Секретарь",
    },
    "tr": {
        "signatures": "İmzalar",
        "name": "Adı Soyadı",
        "signature": "İmza",
        "date": "Tarih",
        "prepared_by": "Hazırlayan",
        "checked_by": "Kontrol eden",
        "approved_by": "Onaylayan",
        "contractor": "Yüklenici",
        "client": "İşveren",
        "engineer": "Kontrol mühendisi",
        "chair": "Toplantı başkanı",
        "minute_taker": "Tutanak yazmanı",
    },
}


@dataclass(frozen=True)
class Signer:
    """One signature slot; ``role`` is a key of :data:`LABELS` or free text."""

    role: str
    name: str = ""
    date: str = ""


def label(locale: str | None, key: str) -> str:
    """The label for ``key`` in ``locale``, English when the language has none."""
    lang = (locale or "en").split("-")[0].lower()
    return LABELS.get(lang, {}).get(key) or LABELS["en"].get(key) or key


def roles_for(
    doc_type: str, appearance: Mapping[str, Any] | None = None, defaults: Sequence[str] | None = None
) -> tuple[str, ...]:
    """The roles ``doc_type`` asks to sign, after the workspace's own choice.

    An empty tuple means no block: the workspace switched it off.
    """
    look = appearance or {}
    if look.get("show_signatures") is False:
        return ()
    custom = look.get("signature_roles")
    if isinstance(custom, (list, tuple)):
        chosen = tuple(str(r).strip() for r in custom if str(r).strip())
        if chosen:
            return chosen[:4]
    if defaults:
        return tuple(defaults)
    return DEFAULT_ROLES.get(doc_type, ("prepared_by", "approved_by"))


def signers_for(
    doc_type: str,
    appearance: Mapping[str, Any] | None = None,
    names: Mapping[str, str] | None = None,
    dates: Mapping[str, str] | None = None,
    defaults: Sequence[str] | None = None,
) -> list[Signer]:
    """Signature slots for ``doc_type``, with any names and dates already known."""
    names = names or {}
    dates = dates or {}
    return [
        Signer(role, names.get(role, ""), dates.get(role, "")) for role in roles_for(doc_type, appearance, defaults)
    ]


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(html.escape(text), pdf_style_for_text(style, text))


def signature_block(
    signers: Sequence[Signer],
    width: float,
    *,
    locale: str | None = "en",
    heading: bool = True,
    font_size: float = 8.5,
    hint: str | None = None,
    align: str = "LEFT",
    gap: float = 8 * mm,
    max_column: float = 70 * mm,
    space_before: float = 6 * mm,
    centre_text: bool = False,
) -> list[Any]:
    """Flowables for a signature block, one column per signer, kept on one page.

    Args:
        signers: The slots, in reading order; at most four fit a row.
        width: The frame width the block may use, in points.
        locale: Language of the printed labels.
        heading: Print the "Signatures" heading above the columns.
        font_size: Body size of the labels.
        hint: One caption under each line that already names the date (e.g.
            "Name / Signature / Date"); the separate date line is then left out.
        align: Horizontal placement of the block, "LEFT" or "CENTER".

    Returns:
        A list with one KeepTogether, or an empty list when there is no signer.
    """
    if not signers:
        return []
    register_pdf_fonts()
    signers = list(signers)[:4]
    text_align = 1 if centre_text else 0
    role_style = ParagraphStyle(
        "SigRole", alignment=text_align, fontName=BOLD_FONT, fontSize=font_size, leading=font_size * 1.3
    )
    text_style = ParagraphStyle(
        "SigText", alignment=text_align, fontName=BODY_FONT, fontSize=font_size, leading=font_size * 1.3
    )
    hint_style = ParagraphStyle(
        "SigHint",
        alignment=text_align,
        fontName=BODY_FONT,
        fontSize=font_size - 1.5,
        leading=(font_size - 1.5) * 1.3,
        textColor=colors.grey,
    )
    count = len(signers)
    column = min((width - gap * (count - 1)) / count, max_column)

    def row(cells: list[Any]) -> list[Any]:
        out: list[Any] = []
        for i, cell in enumerate(cells):
            if i:
                out.append("")
            out.append(cell)
        return out

    rows = [
        row([_para(label(locale, s.role), role_style) for s in signers]),
        row([_para(s.name, text_style) if s.name else "" for s in signers]),
        row(["" for _ in signers]),
        row([_para(hint or f"{label(locale, 'name')} / {label(locale, 'signature')}", hint_style) for _ in signers]),
    ]
    if hint is None:
        date_label = label(locale, "date")
        rows.append(
            row([_para(f"{date_label}: {s.date}" if s.date else f"{date_label}:", text_style) for s in signers])
        )
    widths: list[float] = []
    for i in range(count):
        if i:
            widths.append(gap)
        widths.append(column)
    heights: list[float | None] = [None, None, (10 if hint is None else 8) * mm, None] + (
        [7 * mm] if hint is None else []
    )
    table = Table(rows, colWidths=widths, rowHeights=heights, hAlign=align)
    rule = colors.HexColor("#999999")
    commands: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
    ]
    for i in range(count):
        col = i * 2
        commands.append(("LINEBELOW", (col, 2), (col, 2), 0.5, rule))
        if hint is None:
            commands.append(("LINEBELOW", (col, 4), (col, 4), 0.5, rule))
    table.setStyle(TableStyle(commands))
    parts: list[Any] = [Spacer(1, space_before)] if space_before else []
    if heading:
        title_style = ParagraphStyle(
            "SigTitle", fontName=BOLD_FONT, fontSize=font_size + 1.5, leading=(font_size + 1.5) * 1.3
        )
        parts += [_para(label(locale, "signatures"), title_style), Spacer(1, 2 * mm)]
    parts.append(table)
    return [KeepTogether(parts)]
