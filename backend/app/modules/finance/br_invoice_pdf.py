"""Brazilian-styled invoice PDF (Tier-1 — pre-NF-e bridge).

Brazil's official electronic invoice is the NF-e (goods, federal SEFAZ XML
schema 4.00) or NFS-e (services, municipal). Full integration involves:

* an A1/A3 digital certificate signing pipeline,
* the SEFAZ contingency / autorização web-service round-trip,
* per-municipality NFS-e dialects (each big city has its own RPS layout),
* CRC parity-protected access keys (chave de acesso, 44 digits).

That work is Tier-2 (see ``__brazil_tier2_followups.md``). Until it lands,
the practical complaint from Brazilian users — "there is no invoice
support for BRL" (feedback 2026-05-27) — is that the existing Excel
export doesn't carry the fields a Brazilian estimator's accountant
expects: CNPJ, IE, Razão Social, endereço, código de serviço, retenções
(IRRF / INSS / ISS / PIS / COFINS / CSLL).

This module renders a one-page PDF that mirrors the layout of a typical
RPS (Recibo Provisório de Serviços), which is the *paper* receipt a
service provider hands the client before the municipal NFS-e is issued.
It is NOT a fiscal document and the PDF includes a clear disclaimer to
that effect. What it DOES give the user:

* a Brazilian-styled invoice (R$ formatting, DD/MM/YYYY dates, CNPJ
  field, IE / IM fields, código de serviço LC 116/03 field,
  retentions breakdown),
* immediate value while Tier-2 SEFAZ integration is built,
* a defined extension point (the ``br_fields`` dict on the invoice
  ``metadata``) that the future NF-e bridge will read.

The CNPJ / IE / endereço / código de serviço values are read from
``Invoice.metadata['br_fields']``. When absent we render the row with an
em-dash placeholder so the PDF still prints cleanly — accountants can
hand-write the missing values onto the paper copy.
"""

# Copyright 2024-2026 OpenEstimate Contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import html
import io
from decimal import Decimal, InvalidOperation
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 18 * mm
MARGIN_RIGHT = 18 * mm
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 18 * mm

EM_DASH = "—"


# ── BRL formatting (1.234.567,89) ──────────────────────────────────────


def _brl(value: Any) -> str:
    """Format ``value`` as Brazilian Real: ``R$ 1.234.567,89``.

    Brazil uses the comma as decimal separator and the period as
    thousands separator (ISO 4217 BRL, ABNT NBR 5891). Falls back to
    ``R$ 0,00`` on parse failure so the PDF never breaks rendering.
    """
    try:
        if value is None or value == "":
            d = Decimal("0")
        else:
            d = Decimal(str(value).strip())
        if not d.is_finite():
            d = Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        d = Decimal("0")

    quantised = d.quantize(Decimal("0.01"))
    raw = f"{quantised:,.2f}"
    # comma -> placeholder -> dot -> comma swap so we get 1.234,56
    swapped = raw.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"R$ {swapped}"


def _br_date(iso: str | None) -> str:
    """ISO ``YYYY-MM-DD`` → ``DD/MM/YYYY`` (Brazilian convention).

    Returns the em-dash placeholder for ``None`` or any value that doesn't
    parse as a 10-character ISO date.
    """
    if not iso or len(iso) < 10:
        return EM_DASH
    try:
        return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"
    except (IndexError, TypeError):
        return EM_DASH


def _val(v: Any) -> str:
    """Render an optional string field with em-dash fallback."""
    if v is None or v == "":
        return EM_DASH
    return str(v)


def _safe_para(text: Any, style: ParagraphStyle) -> Paragraph:
    """Escape user-controlled text before handing to ReportLab.

    Mirrors :func:`backend.app.modules.boq.pdf_export._safe_para`. Stops
    ``<font color="white">hidden</font>`` style attacks from the BR
    fields dict (which arrives via ``Invoice.metadata`` — a JSON column
    populated by the API caller, not pre-validated).
    """
    if text is None:
        rendered = ""
    elif isinstance(text, str):
        rendered = text
    else:
        rendered = str(text)
    return Paragraph(html.escape(rendered, quote=True), style)


# ── Styles ─────────────────────────────────────────────────────────────


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "BRTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1a1a2e"),
            spaceAfter=2 * mm,
        ),
        "subtitle": ParagraphStyle(
            "BRSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#666666"),
            spaceAfter=4 * mm,
        ),
        "section": ParagraphStyle(
            "BRSection",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=colors.HexColor("#1a1a2e"),
            spaceBefore=3 * mm,
            spaceAfter=1.5 * mm,
        ),
        "label": ParagraphStyle(
            "BRLabel",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=colors.HexColor("#666666"),
        ),
        "value": ParagraphStyle(
            "BRValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=colors.HexColor("#1a1a2e"),
        ),
        "cell": ParagraphStyle(
            "BRCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=colors.HexColor("#222222"),
            alignment=TA_LEFT,
        ),
        "cell_right": ParagraphStyle(
            "BRCellRight",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=colors.HexColor("#222222"),
            alignment=TA_RIGHT,
        ),
        "disclaimer": ParagraphStyle(
            "BRDisclaimer",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=7,
            textColor=colors.HexColor("#888888"),
            alignment=TA_CENTER,
            spaceBefore=5 * mm,
        ),
    }


# ── Render ─────────────────────────────────────────────────────────────


def _id_block(
    styles: dict[str, ParagraphStyle],
    title: str,
    fields: dict[str, str],
) -> Table:
    """Build a 2-column label/value block (used for prestador and tomador)."""
    rows: list[list[Paragraph]] = [[_safe_para(title, styles["section"]), _safe_para("", styles["section"])]]
    for label, value in fields.items():
        rows.append(
            [
                _safe_para(label, styles["label"]),
                _safe_para(value, styles["value"]),
            ]
        )
    col_widths = [
        (PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT) * 0.30,
        (PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT) * 0.70,
    ]
    tbl = Table(rows, colWidths=col_widths)
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("LINEBELOW", (0, 0), (-1, 0), 0.3, colors.HexColor("#1a1a2e")),
                ("SPAN", (0, 0), (1, 0)),
            ]
        )
    )
    return tbl


def render_br_invoice_pdf(
    *,
    invoice: dict[str, Any],
    line_items: list[dict[str, Any]],
    project: dict[str, Any] | None = None,
) -> bytes:
    """Render a Brazilian-styled invoice PDF and return the raw bytes.

    Args:
        invoice: dict with the standard ``InvoiceResponse`` shape plus
            an optional ``metadata.br_fields`` block carrying CNPJ / IE /
            endereço / código de serviço / retenções data.
        line_items: list of ``InvoiceLineItemResponse``-shaped dicts.
        project: optional project context (``name``, ``code``); used in
            the header line.

    Returns:
        PDF file content as bytes. Caller is responsible for streaming.
    """
    styles = _build_styles()
    br_fields = (invoice.get("metadata") or {}).get("br_fields") or {}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"Fatura {invoice.get('invoice_number', '')}".strip(),
    )

    story: list[Any] = []

    # Header
    project_name = (project or {}).get("name") or ""
    story.append(_safe_para("RECIBO PROVISÓRIO DE SERVIÇOS (RPS)", styles["title"]))
    if project_name:
        story.append(_safe_para(f"Projeto: {project_name}", styles["subtitle"]))

    # Top row: invoice number + dates
    header_rows: list[list[Paragraph]] = [
        [
            _safe_para("Número da fatura", styles["label"]),
            _safe_para(_val(invoice.get("invoice_number")), styles["value"]),
            _safe_para("Data de emissão", styles["label"]),
            _safe_para(_br_date(invoice.get("invoice_date")), styles["value"]),
        ],
        [
            _safe_para("Tipo", styles["label"]),
            _safe_para(
                "Receita" if invoice.get("invoice_direction") == "receivable" else "Despesa",
                styles["value"],
            ),
            _safe_para("Vencimento", styles["label"]),
            _safe_para(_br_date(invoice.get("due_date")), styles["value"]),
        ],
    ]
    col4 = (PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT) / 4
    header_tbl = Table(header_rows, colWidths=[col4] * 4)
    header_tbl.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
                ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#eeeeee")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(header_tbl)
    story.append(Spacer(1, 4 * mm))

    # Prestador (issuer) — pulled from br_fields.prestador_*
    prestador = br_fields.get("prestador") or {}
    story.append(
        _id_block(
            styles,
            "PRESTADOR DE SERVIÇOS (EMITENTE)",
            {
                "Razão Social": _val(prestador.get("razao_social")),
                "CNPJ": _val(prestador.get("cnpj")),
                "Inscrição Estadual": _val(prestador.get("ie")),
                "Inscrição Municipal": _val(prestador.get("im")),
                "Endereço": _val(prestador.get("endereco")),
                "Município / UF": _val(prestador.get("municipio_uf")),
                "CEP": _val(prestador.get("cep")),
            },
        )
    )
    story.append(Spacer(1, 3 * mm))

    # Tomador (recipient) — pulled from br_fields.tomador_*
    tomador = br_fields.get("tomador") or {}
    story.append(
        _id_block(
            styles,
            "TOMADOR DE SERVIÇOS (DESTINATÁRIO)",
            {
                "Razão Social / Nome": _val(tomador.get("razao_social")),
                "CNPJ / CPF": _val(tomador.get("cnpj_cpf")),
                "Inscrição Estadual": _val(tomador.get("ie")),
                "Endereço": _val(tomador.get("endereco")),
                "Município / UF": _val(tomador.get("municipio_uf")),
                "CEP": _val(tomador.get("cep")),
            },
        )
    )
    story.append(Spacer(1, 3 * mm))

    # Serviços / Items
    story.append(_safe_para("DISCRIMINAÇÃO DOS SERVIÇOS", styles["section"]))
    codigo_servico = _val(br_fields.get("codigo_servico"))  # LC 116/03 list code
    story.append(
        _safe_para(
            f"Código do Serviço (LC 116/03): {codigo_servico}",
            styles["label"],
        )
    )
    story.append(Spacer(1, 1.5 * mm))

    item_rows: list[list[Paragraph]] = [
        [
            _safe_para("<b>Descrição</b>", styles["cell"]),
            _safe_para("<b>Unid.</b>", styles["cell"]),
            _safe_para("<b>Qtd.</b>", styles["cell_right"]),
            _safe_para("<b>Valor unit.</b>", styles["cell_right"]),
            _safe_para("<b>Valor total</b>", styles["cell_right"]),
        ]
    ]
    for li in line_items:
        item_rows.append(
            [
                _safe_para(_val(li.get("description")), styles["cell"]),
                _safe_para(_val(li.get("unit") or ""), styles["cell"]),
                _safe_para(_val(li.get("quantity")), styles["cell_right"]),
                _safe_para(_brl(li.get("unit_rate")), styles["cell_right"]),
                _safe_para(_brl(li.get("amount")), styles["cell_right"]),
            ]
        )

    usable = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    item_widths = [
        usable * 0.46,
        usable * 0.08,
        usable * 0.12,
        usable * 0.17,
        usable * 0.17,
    ]
    item_tbl = Table(item_rows, colWidths=item_widths, repeatRows=1)
    item_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f6fa")),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
                ("INNERGRID", (0, 0), (-1, -1), 0.15, colors.HexColor("#eeeeee")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(item_tbl)
    story.append(Spacer(1, 3 * mm))

    # Totais e retenções
    story.append(_safe_para("APURAÇÃO", styles["section"]))
    retencoes = br_fields.get("retencoes") or {}
    subtotal = invoice.get("amount_subtotal", "0")
    tax = invoice.get("tax_amount", "0")
    retention = invoice.get("retention_amount", "0")
    total = invoice.get("amount_total", "0")

    totals_rows: list[list[Paragraph]] = [
        [
            _safe_para("Valor dos serviços (subtotal)", styles["cell"]),
            _safe_para(_brl(subtotal), styles["cell_right"]),
        ],
        [
            _safe_para("ISS (Imposto Sobre Serviços)", styles["cell"]),
            _safe_para(_brl(retencoes.get("iss", tax)), styles["cell_right"]),
        ],
        [
            _safe_para("PIS retido", styles["cell"]),
            _safe_para(_brl(retencoes.get("pis", "0")), styles["cell_right"]),
        ],
        [
            _safe_para("COFINS retido", styles["cell"]),
            _safe_para(_brl(retencoes.get("cofins", "0")), styles["cell_right"]),
        ],
        [
            _safe_para("CSLL retido", styles["cell"]),
            _safe_para(_brl(retencoes.get("csll", "0")), styles["cell_right"]),
        ],
        [
            _safe_para("INSS retido", styles["cell"]),
            _safe_para(_brl(retencoes.get("inss", "0")), styles["cell_right"]),
        ],
        [
            _safe_para("IRRF retido", styles["cell"]),
            _safe_para(_brl(retencoes.get("irrf", "0")), styles["cell_right"]),
        ],
        [
            _safe_para("Total de retenções", styles["cell"]),
            _safe_para(_brl(retention), styles["cell_right"]),
        ],
        [
            _safe_para("<b>Valor líquido a pagar</b>", styles["cell"]),
            _safe_para(f"<b>{_brl(total)}</b>", styles["cell_right"]),
        ],
    ]
    totals_widths = [usable * 0.70, usable * 0.30]
    totals_tbl = Table(totals_rows, colWidths=totals_widths)
    totals_tbl.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.HexColor("#1a1a2e")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f5f6fa")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ]
        )
    )
    story.append(totals_tbl)

    # Notes
    notes = invoice.get("notes")
    if notes:
        story.append(Spacer(1, 3 * mm))
        story.append(_safe_para("OBSERVAÇÕES", styles["section"]))
        story.append(_safe_para(str(notes), styles["cell"]))

    # Disclaimer — this is NOT a fiscal document
    story.append(
        _safe_para(
            "Este documento é um Recibo Provisório de Serviços (RPS) gerado pelo "
            "OpenConstructionERP. Não substitui Nota Fiscal Eletrônica (NF-e / NFS-e). "
            "A emissão fiscal definitiva deve ser realizada pelo sistema da prefeitura "
            "competente ou via integração SEFAZ.",
            styles["disclaimer"],
        )
    )

    doc.build(story)
    return buffer.getvalue()
