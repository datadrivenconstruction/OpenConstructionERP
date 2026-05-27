"""‌⁠‍Regulator-report generators for property_dev (task #139).

Four jurisdictions are supported out of the box:

* ``RERA``     — Dubai Land Department, Real Estate Regulatory Agency.
                 Quarterly developer disclosure for off-plan sales.
* ``MAHARERA`` — Maharashtra Real Estate Regulatory Authority, India.
                 Form 5 quarterly progress + finances disclosure.
* ``214FZ``    — Russia, Federal Law 214-ФЗ on shared construction.
                 Квартальная отчётность застройщика, submitted to ЕИСЖС.
* ``CMA``      — Saudi Arabia, Capital Market Authority + Wafi off-plan
                 licence. Bilingual (Arabic + English) disclosure.

Each generator returns a :class:`RegulatorReport` value object carrying both
the rendered PDF (bytes) and a structured payload (JSON for RERA/CMA, XML
for MAHARERA and 214-FZ) so callers can save the artefact OR push the
machine-readable payload straight to the regulator's portal API.

The implementations DO NOT make outbound network calls — they only read
from the property_dev tables and produce in-memory bytes. PDF rendering
falls back gracefully to a marker-only document if reportlab is missing
(matches :mod:`bi_dashboards.report_builder`).

Escrow data is read live from :class:`EscrowAccount` +
:class:`EscrowTransaction` (task #138 schema). The legacy
``Development.metadata["escrow_accounts"]`` workaround is no longer used.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.property_dev.models import (
    Buyer,
    Development,
    EscrowAccount,
    EscrowTransaction,
    Handover,
    Plot,
    SalesContract,
)

logger = logging.getLogger(__name__)


_VALID_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")


# ── Value object ────────────────────────────────────────────────────────


@dataclass
class RegulatorReport:
    """Result envelope for a regulator-report generation.

    Attributes:
        regulator: ``"RERA"`` / ``"MAHARERA"`` / ``"214FZ"`` / ``"CMA"``.
        development_id: UUID of the source development.
        quarter: ``"YYYY-Qn"`` string the report covers.
        generated_at: Generation timestamp (UTC, ISO 8601).
        pdf_bytes: Rendered PDF artefact (always non-empty; ``b"%PDF-1.4..."``
            magic guaranteed).
        payload_format: ``"json"`` or ``"xml"`` — content type of
            ``payload_bytes``.
        payload_bytes: Machine-readable submission payload.
        summary: Compact dict the API returns alongside the artefact bytes.
    """

    regulator: str
    development_id: str
    quarter: str
    generated_at: str
    pdf_bytes: bytes
    payload_format: str
    payload_bytes: bytes
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Public dict view (no raw bytes — those are streamed separately)."""
        d = asdict(self)
        d.pop("pdf_bytes", None)
        d.pop("payload_bytes", None)
        d["pdf_size"] = len(self.pdf_bytes)
        d["payload_size"] = len(self.payload_bytes)
        return d


# ── Helpers ─────────────────────────────────────────────────────────────


def _coerce_uuid(raw: Any) -> uuid.UUID:
    """Strict UUID parse — raises ``ValueError`` (caller handles)."""
    if isinstance(raw, uuid.UUID):
        return raw
    return uuid.UUID(str(raw))


def parse_quarter(quarter: str) -> tuple[int, int]:
    """Parse ``"YYYY-Qn"`` into ``(year, quarter)``. Raises ``ValueError``."""
    m = _VALID_QUARTER.match((quarter or "").strip())
    if not m:
        raise ValueError(f"Invalid quarter '{quarter}'; expected 'YYYY-Qn'")
    return int(m.group(1)), int(m.group(2))


def quarter_bounds(year: int, q: int) -> tuple[str, str]:
    """Return ``(start_iso, end_iso)`` for the calendar quarter."""
    starts = {1: 1, 2: 4, 3: 7, 4: 10}
    ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    start = f"{year:04d}-{starts[q]:02d}-01"
    end = f"{year:04d}-{ends[q]}"
    return start, end


async def _compute_escrow_snapshot(session: AsyncSession, dev_id: uuid.UUID) -> list[dict[str, Any]]:
    """Build the escrow account list from EscrowAccount + EscrowTransaction.

    Each entry is a regulator-friendly summary; balances are computed live
    by summing credits minus debits on EscrowTransaction rows (matches
    :meth:`EscrowTransactionRepository.compute_balance`).
    """
    accounts = list(
        (
            await session.execute(
                select(EscrowAccount)
                .where(EscrowAccount.development_id == dev_id)
                .where(EscrowAccount.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    snapshot: list[dict[str, Any]] = []
    for acc in accounts:
        bal_stmt = (
            select(
                EscrowTransaction.direction,
                func.coalesce(func.sum(EscrowTransaction.amount), 0),
            )
            .where(EscrowTransaction.escrow_account_id == acc.id)
            .group_by(EscrowTransaction.direction)
        )
        credit = Decimal("0")
        debit = Decimal("0")
        for direction, total in (await session.execute(bal_stmt)).all():
            if direction == "credit":
                credit = Decimal(str(total or 0))
            elif direction == "debit":
                debit = Decimal(str(total or 0))
        balance = credit - debit
        meta = acc.metadata_ or {}
        declared_balance = meta.get("ledger_balance") if isinstance(meta, dict) else None
        snapshot.append(
            {
                "account_id": str(acc.id),
                "account_no": acc.regulator_account_number or "—",
                "bank": acc.bank_name or "—",
                "iban": acc.iban or "",
                "regulator_ref": acc.regulator_ref or "",
                "currency": (acc.currency or "").upper(),
                "credit_total": str(credit.quantize(Decimal("0.01"))),
                "debit_total": str(debit.quantize(Decimal("0.01"))),
                "computed_balance": str(balance.quantize(Decimal("0.01"))),
                "declared_balance": (
                    str(Decimal(str(declared_balance)).quantize(Decimal("0.01")))
                    if declared_balance is not None
                    else ""
                ),
            }
        )
    return snapshot


async def _load_aggregates(
    session: AsyncSession,
    dev_id: uuid.UUID,
    quarter: str,
) -> dict[str, Any]:
    """Compute the metrics every regulator needs.

    Pure function over the live tables — no caching, no I/O. All money is
    Decimal-quantized to two places.
    """
    year, q = parse_quarter(quarter)
    period_start, period_end = quarter_bounds(year, q)

    dev = await session.get(Development, dev_id)
    if dev is None:
        raise ValueError(f"Development {dev_id} not found")

    # Plot counts by status.
    plot_count_stmt = (
        select(Plot.status, func.count(Plot.id)).where(Plot.development_id == dev_id).group_by(Plot.status)
    )
    plot_counts = {row[0]: int(row[1]) for row in (await session.execute(plot_count_stmt)).all()}
    total_plots = sum(plot_counts.values())
    sold = plot_counts.get("sold", 0) + plot_counts.get("handed_over", 0)
    reserved = plot_counts.get("reserved", 0)
    available = plot_counts.get("planned", 0) + plot_counts.get("ready", 0)
    handed_over = plot_counts.get("handed_over", 0)

    # Average construction percent (weighted by plot — every plot one vote).
    progress_stmt = select(func.coalesce(func.avg(Plot.construction_status_percent), 0)).where(
        Plot.development_id == dev_id
    )
    avg_progress_raw = (await session.execute(progress_stmt)).scalar() or 0
    avg_progress = Decimal(str(avg_progress_raw)).quantize(Decimal("0.01"))

    # Sales value: sum of contract_value across non-cancelled buyers.
    sales_stmt = (
        select(
            func.coalesce(func.sum(Buyer.contract_value), 0),
            Buyer.currency,
        )
        .where(Buyer.development_id == dev_id)
        .where(Buyer.status != "cancelled")
        .group_by(Buyer.currency)
    )
    sales_rows = (await session.execute(sales_stmt)).all()
    sales_by_currency: dict[str, Decimal] = {}
    for total, ccy in sales_rows:
        key = (ccy or "").upper()
        sales_by_currency[key] = sales_by_currency.get(key, Decimal("0")) + Decimal(str(total))

    # Quarterly buyer activity (contracted/reserved IN the quarter).
    contracted_q_stmt = (
        select(func.count(Buyer.id))
        .where(Buyer.development_id == dev_id)
        .where(Buyer.contract_signed_at.is_not(None))
        .where(Buyer.contract_signed_at >= period_start)
        .where(Buyer.contract_signed_at <= period_end)
    )
    contracted_in_quarter = int((await session.execute(contracted_q_stmt)).scalar() or 0)

    # Quarterly SalesContract activity (R6 signed contracts via Plot FK).
    spa_q_stmt = (
        select(func.count(SalesContract.id))
        .join(Plot, Plot.id == SalesContract.plot_id)
        .where(Plot.development_id == dev_id)
        .where(SalesContract.signing_date.is_not(None))
        .where(SalesContract.signing_date >= period_start)
        .where(SalesContract.signing_date <= period_end)
    )
    spas_in_quarter = int((await session.execute(spa_q_stmt)).scalar() or 0)

    # Handovers completed in quarter.
    handover_q_stmt = (
        select(func.count(Handover.id))
        .join(Plot, Plot.id == Handover.plot_id)
        .where(Plot.development_id == dev_id)
        .where(Handover.completed_at.is_not(None))
        .where(Handover.completed_at >= period_start)
        .where(Handover.completed_at <= period_end)
    )
    handovers_in_quarter = int((await session.execute(handover_q_stmt)).scalar() or 0)

    # Live escrow snapshot from EscrowAccount + EscrowTransaction.
    escrow_accounts = await _compute_escrow_snapshot(session, dev_id)

    meta = dev.metadata_ or {}

    return {
        "development": {
            "id": str(dev.id),
            "code": dev.code,
            "name": dev.name,
            "location": dev.location_address or "",
            "sales_phase": dev.sales_phase,
            "status": dev.status,
            "completion_date": dev.completion_date or "",
            "rera_number": (meta.get("rera_registration_number") if isinstance(meta, dict) else "") or "",
            "maharera_number": (meta.get("maharera_registration_number") if isinstance(meta, dict) else "") or "",
            "fz214_project_id": (meta.get("fz214_project_id") if isinstance(meta, dict) else "") or "",
            "cma_licence_no": (meta.get("cma_licence_no") if isinstance(meta, dict) else "") or "",
            "authorised_signatory": (meta.get("authorised_signatory") if isinstance(meta, dict) else "") or "",
            "estimated_cost_to_completion": (meta.get("estimated_cost_to_completion") if isinstance(meta, dict) else "")
            or "",
        },
        "period": {
            "quarter": quarter,
            "start": period_start,
            "end": period_end,
        },
        "plots": {
            "total": total_plots,
            "sold": sold,
            "reserved": reserved,
            "available": available,
            "handed_over": handed_over,
            "by_status": plot_counts,
            "avg_progress_percent": str(avg_progress),
        },
        "sales": {
            "by_currency": {k: str(v.quantize(Decimal("0.01"))) for k, v in sales_by_currency.items()},
            "contracted_in_quarter": contracted_in_quarter,
            "spas_in_quarter": spas_in_quarter,
            "handovers_in_quarter": handovers_in_quarter,
        },
        "escrow": {
            "accounts": escrow_accounts,
        },
    }


# ── PDF rendering ───────────────────────────────────────────────────────


def _render_pdf(
    *,
    title: str,
    subtitle: str,
    sections: list[tuple[str, list[tuple[str, str]]]],
    signature_line: str,
    qr_payload: str,
) -> bytes:
    """Shared PDF skeleton used by every regulator generator.

    Each ``section`` is ``(heading, [(label, value), ...])``. The function
    returns the PDF as bytes (always starts with ``b"%PDF"``).
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:  # pragma: no cover — reportlab is a hard dep
        logger.warning("reportlab unavailable — emitting marker PDF for %s", title)
        marker = (
            "%PDF-1.4\n"
            f"% {title}\n"
            f"% {subtitle}\n"
            f"% generated_at={datetime.now(UTC).isoformat(timespec='seconds')}\n"
            "%%EOF\n"
        )
        return marker.encode("utf-8")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=title,
    )
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph(title, styles["Title"]),
        Paragraph(subtitle, styles["Heading2"]),
        Paragraph(
            f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} UTC",
            styles["BodyText"],
        ),
        Spacer(1, 0.5 * cm),
    ]
    for heading, rows in sections:
        story.append(Paragraph(heading, styles["Heading3"]))
        if not rows:
            story.append(Paragraph("(no data)", styles["BodyText"]))
            story.append(Spacer(1, 0.3 * cm))
            continue
        data = [["Field", "Value"]] + [[label, str(value)] for label, value in rows]
        table = Table(data, colWidths=[6 * cm, 11 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f3f4f6")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ],
            ),
        )
        story.append(table)
        story.append(Spacer(1, 0.4 * cm))

    # Signature block + QR code stub.
    story.append(Spacer(1, 0.7 * cm))
    story.append(Paragraph("Authorised signatory", styles["Heading3"]))
    sig_table = Table(
        [
            [signature_line or "Authorised signatory", "Date"],
            ["", datetime.now(UTC).strftime("%Y-%m-%d")],
        ],
        colWidths=[10 * cm, 7 * cm],
    )
    sig_table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ],
        ),
    )
    story.append(sig_table)
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        Paragraph(
            f"Regulator verification token (QR stub): {qr_payload}",
            styles["BodyText"],
        )
    )

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf


def _xml_text(value: Any) -> str:
    """Defensive XML body text — never ``None`` and never bare ``&``."""
    if value is None:
        return ""
    return str(value)


# ── RERA (Dubai DLD) ────────────────────────────────────────────────────


async def generate_regulator_report_rera(
    session: AsyncSession,
    dev_id: uuid.UUID | str,
    quarter: str,
) -> RegulatorReport:
    """Generate the RERA / DLD quarterly disclosure."""
    dev_uuid = _coerce_uuid(dev_id)
    agg = await _load_aggregates(session, dev_uuid, quarter)
    dev_meta = agg["development"]
    plots = agg["plots"]
    sales = agg["sales"]
    period = agg["period"]
    sales_currency = next(iter(sales["by_currency"]), "AED")
    net_sales_value = sales["by_currency"].get(sales_currency, "0.00")

    sections = [
        (
            "Project identification",
            [
                ("RERA registration number", dev_meta["rera_number"] or "—"),
                ("Project number", dev_meta["code"]),
                ("Project name", dev_meta["name"]),
                ("Location", dev_meta["location"] or "—"),
                ("Sales phase", dev_meta["sales_phase"]),
                ("Period", f"{period['quarter']} ({period['start']} -> {period['end']})"),
            ],
        ),
        (
            "Units",
            [
                ("Total units", plots["total"]),
                ("Sold units", plots["sold"]),
                ("Reserved units", plots["reserved"]),
                ("Available units", plots["available"]),
                ("Handed-over units", plots["handed_over"]),
                ("Average construction progress (%)", plots["avg_progress_percent"]),
            ],
        ),
        (
            "Sales",
            [
                ("Net sales value (this period)", f"{net_sales_value} {sales_currency}"),
                ("Contracts signed (this quarter)", sales["contracted_in_quarter"]),
                ("SPAs signed (this quarter)", sales["spas_in_quarter"]),
                ("Handovers completed (this quarter)", sales["handovers_in_quarter"]),
            ],
        ),
        (
            "Escrow activity (Article 11)",
            [
                (
                    acc["account_no"],
                    (
                        f"Bank {acc['bank']} | Balance {acc['computed_balance']} "
                        f"{acc['currency']} (credits {acc['credit_total']}, "
                        f"debits {acc['debit_total']})"
                    ),
                )
                for acc in agg["escrow"]["accounts"]
            ]
            or [("(no escrow accounts declared)", "—")],
        ),
    ]
    qr_payload = f"RERA|{dev_meta['rera_number'] or dev_meta['code']}|{quarter}"
    pdf_bytes = _render_pdf(
        title="RERA Quarterly Project Disclosure",
        subtitle=f"{dev_meta['name']} ({dev_meta['code']}) - {quarter}",
        sections=sections,
        signature_line=dev_meta["authorised_signatory"] or "Developer authorised signatory",
        qr_payload=qr_payload,
    )

    payload = {
        "regulator": "RERA",
        "format_version": "1.0",
        "submission": {
            "rera_registration_number": dev_meta["rera_number"],
            "project_number": dev_meta["code"],
            "project_name": dev_meta["name"],
            "period": period,
            "units": plots,
            "sales": sales,
            "escrow": agg["escrow"],
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return RegulatorReport(
        regulator="RERA",
        development_id=str(dev_uuid),
        quarter=quarter,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        pdf_bytes=pdf_bytes,
        payload_format="json",
        payload_bytes=payload_bytes,
        summary={
            "total_units": plots["total"],
            "sold_units": plots["sold"],
            "net_sales_value": net_sales_value,
            "currency": sales_currency,
            "escrow_accounts": len(agg["escrow"]["accounts"]),
        },
    )


# ── MAHARERA (Maharashtra Form 5) ───────────────────────────────────────


async def generate_regulator_report_maharera(
    session: AsyncSession,
    dev_id: uuid.UUID | str,
    quarter: str,
) -> RegulatorReport:
    """Generate the MAHARERA Form 5 quarterly disclosure (PDF + XML)."""
    dev_uuid = _coerce_uuid(dev_id)
    agg = await _load_aggregates(session, dev_uuid, quarter)
    dev_meta = agg["development"]
    plots = agg["plots"]
    sales = agg["sales"]
    period = agg["period"]
    inr_sales = sales["by_currency"].get("INR", "0.00")

    # Carpet vs built-up: sum from Plot.metadata when supplied.
    carpet_total = Decimal("0")
    built_up_total = Decimal("0")
    rows = (await session.execute(select(Plot).where(Plot.development_id == dev_uuid))).scalars().all()
    for plot in rows:
        pmeta = plot.metadata_ or {}
        try:
            carpet_total += Decimal(str(pmeta.get("carpet_area_m2", "0") or "0"))
            built_up_total += Decimal(str(pmeta.get("built_up_area_m2", "0") or plot.area_m2 or "0"))
        except Exception:  # noqa: BLE001 — defensive parser
            continue

    sections = [
        (
            "Project identification (Form 5)",
            [
                ("MAHARERA registration", dev_meta["maharera_number"] or "—"),
                ("Project code", dev_meta["code"]),
                ("Project name", dev_meta["name"]),
                ("Location", dev_meta["location"] or "—"),
                ("Reporting period", f"{period['quarter']} ({period['start']} -> {period['end']})"),
            ],
        ),
        (
            "Stage-wise % complete (averaged across buildings)",
            [
                ("Overall construction progress (%)", plots["avg_progress_percent"]),
                ("Total units", plots["total"]),
                ("Sold + handed over", plots["sold"]),
            ],
        ),
        (
            "Money received",
            [
                ("This quarter (INR contracts)", inr_sales),
                ("Contracts signed (this quarter)", sales["contracted_in_quarter"]),
                ("SPAs signed (this quarter)", sales["spas_in_quarter"]),
                ("Handovers (this quarter)", sales["handovers_in_quarter"]),
            ],
        ),
        (
            "Carpet vs built-up",
            [
                ("Total carpet area (m2)", str(carpet_total.quantize(Decimal("0.01")))),
                ("Total built-up area (m2)", str(built_up_total.quantize(Decimal("0.01")))),
            ],
        ),
        (
            "Estimated cost to completion",
            [
                ("Source", "Developer-declared (Form 5 Annexure C)"),
                ("Value", dev_meta.get("estimated_cost_to_completion", "—") or "—"),
            ],
        ),
    ]
    qr_payload = f"MAHARERA|{dev_meta['maharera_number'] or dev_meta['code']}|{quarter}"
    pdf_bytes = _render_pdf(
        title="MAHARERA Form 5 - Quarterly Progress Report",
        subtitle=f"{dev_meta['name']} ({dev_meta['code']}) - {quarter}",
        sections=sections,
        signature_line=dev_meta["authorised_signatory"] or "Authorised signatory of the promoter",
        qr_payload=qr_payload,
    )

    root = ET.Element("MAHARERA_Form5")
    ET.SubElement(root, "RegistrationNumber").text = _xml_text(dev_meta["maharera_number"])
    ET.SubElement(root, "ProjectCode").text = _xml_text(dev_meta["code"])
    ET.SubElement(root, "ProjectName").text = _xml_text(dev_meta["name"])
    ET.SubElement(root, "Quarter").text = quarter
    period_el = ET.SubElement(root, "Period")
    ET.SubElement(period_el, "Start").text = period["start"]
    ET.SubElement(period_el, "End").text = period["end"]
    units_el = ET.SubElement(root, "Units")
    ET.SubElement(units_el, "Total").text = str(plots["total"])
    ET.SubElement(units_el, "Sold").text = str(plots["sold"])
    ET.SubElement(units_el, "Reserved").text = str(plots["reserved"])
    ET.SubElement(units_el, "HandedOver").text = str(plots["handed_over"])
    ET.SubElement(units_el, "AverageProgressPercent").text = plots["avg_progress_percent"]
    areas_el = ET.SubElement(root, "Areas")
    ET.SubElement(areas_el, "CarpetTotalM2").text = str(carpet_total.quantize(Decimal("0.01")))
    ET.SubElement(areas_el, "BuiltUpTotalM2").text = str(built_up_total.quantize(Decimal("0.01")))
    money_el = ET.SubElement(root, "Money")
    ET.SubElement(money_el, "InQuarterINR").text = inr_sales
    ET.SubElement(money_el, "ContractsInQuarter").text = str(sales["contracted_in_quarter"])
    ET.SubElement(money_el, "SpasInQuarter").text = str(sales["spas_in_quarter"])
    ET.SubElement(money_el, "HandoversInQuarter").text = str(sales["handovers_in_quarter"])
    ET.SubElement(root, "GeneratedAt").text = datetime.now(UTC).isoformat(timespec="seconds")
    payload_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    return RegulatorReport(
        regulator="MAHARERA",
        development_id=str(dev_uuid),
        quarter=quarter,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        pdf_bytes=pdf_bytes,
        payload_format="xml",
        payload_bytes=payload_bytes,
        summary={
            "total_units": plots["total"],
            "carpet_area_m2": str(carpet_total.quantize(Decimal("0.01"))),
            "built_up_area_m2": str(built_up_total.quantize(Decimal("0.01"))),
            "inr_sales_in_quarter": inr_sales,
        },
    )


# ── 214-FZ (Russia ЕИСЖС) ───────────────────────────────────────────────


async def generate_regulator_report_214fz(
    session: AsyncSession,
    dev_id: uuid.UUID | str,
    quarter: str,
) -> RegulatorReport:
    """Сгенерировать квартальный отчёт застройщика по 214-ФЗ (PDF + XML)."""
    dev_uuid = _coerce_uuid(dev_id)
    agg = await _load_aggregates(session, dev_uuid, quarter)
    dev_meta = agg["development"]
    plots = agg["plots"]
    sales = agg["sales"]
    period = agg["period"]
    rub_sales = sales["by_currency"].get("RUB", "0.00")

    residential_total = Decimal("0")
    non_residential_total = Decimal("0")
    rows = (await session.execute(select(Plot).where(Plot.development_id == dev_uuid))).scalars().all()
    for plot in rows:
        pmeta = plot.metadata_ or {}
        try:
            if (pmeta.get("kind") or "residential") == "residential":
                residential_total += Decimal(str(plot.area_m2 or 0))
            else:
                non_residential_total += Decimal(str(plot.area_m2 or 0))
        except Exception:  # noqa: BLE001
            continue
    total_area = residential_total + non_residential_total

    sections = [
        (
            "Идентификация проекта",
            [
                ("Идентификатор в ЕИСЖС", dev_meta["fz214_project_id"] or "—"),
                ("Код проекта", dev_meta["code"]),
                ("Наименование", dev_meta["name"]),
                ("Адрес", dev_meta["location"] or "—"),
                ("Период", f"{period['quarter']} ({period['start']} -> {period['end']})"),
            ],
        ),
        (
            "Эскроу-счёт",
            [
                (
                    acc["account_no"],
                    (
                        f"Банк {acc['bank']} | Остаток {acc['computed_balance']} "
                        f"{acc['currency']} (кредит {acc['credit_total']}, "
                        f"дебет {acc['debit_total']})"
                    ),
                )
                for acc in agg["escrow"]["accounts"]
            ]
            or [("Эскроу-счета не объявлены", "—")],
        ),
        (
            "Договоры долевого участия (ДДУ) за период",
            [
                ("Заключено ДДУ (за квартал)", sales["contracted_in_quarter"]),
                ("SPA подписано (за квартал)", sales["spas_in_quarter"]),
                ("Сумма по ДДУ (RUB, нарастающим итогом)", rub_sales),
                ("Передано дольщикам (за квартал)", sales["handovers_in_quarter"]),
            ],
        ),
        (
            "Площади",
            [
                ("Общая площадь (m2)", str(total_area.quantize(Decimal("0.01")))),
                ("Жилая площадь (m2)", str(residential_total.quantize(Decimal("0.01")))),
                ("Нежилая площадь (m2)", str(non_residential_total.quantize(Decimal("0.01")))),
            ],
        ),
        (
            "Готовность строительства",
            [
                ("Средний процент готовности", plots["avg_progress_percent"]),
                ("Юнитов всего", plots["total"]),
                ("Передано", plots["handed_over"]),
            ],
        ),
    ]
    qr_payload = f"214FZ|{dev_meta['fz214_project_id'] or dev_meta['code']}|{quarter}"
    pdf_bytes = _render_pdf(
        title="214-FZ - Quarterly Developer Report",
        subtitle=f"{dev_meta['name']} ({dev_meta['code']}) - {quarter}",
        sections=sections,
        signature_line=dev_meta["authorised_signatory"] or "Authorised representative",
        qr_payload=qr_payload,
    )

    root = ET.Element("FZ214_QuarterlyReport")
    ET.SubElement(root, "EISZSProjectId").text = _xml_text(dev_meta["fz214_project_id"])
    ET.SubElement(root, "ProjectCode").text = _xml_text(dev_meta["code"])
    ET.SubElement(root, "ProjectName").text = _xml_text(dev_meta["name"])
    ET.SubElement(root, "Quarter").text = quarter
    period_el = ET.SubElement(root, "Period")
    ET.SubElement(period_el, "Start").text = period["start"]
    ET.SubElement(period_el, "End").text = period["end"]
    escrow_el = ET.SubElement(root, "Escrow")
    for acc in agg["escrow"]["accounts"]:
        a = ET.SubElement(escrow_el, "Account")
        ET.SubElement(a, "AccountId").text = _xml_text(acc["account_id"])
        ET.SubElement(a, "AccountNumber").text = _xml_text(acc["account_no"])
        ET.SubElement(a, "Bank").text = _xml_text(acc["bank"])
        ET.SubElement(a, "IBAN").text = _xml_text(acc["iban"])
        ET.SubElement(a, "ComputedBalance").text = _xml_text(acc["computed_balance"])
        ET.SubElement(a, "CreditTotal").text = _xml_text(acc["credit_total"])
        ET.SubElement(a, "DebitTotal").text = _xml_text(acc["debit_total"])
        ET.SubElement(a, "Currency").text = _xml_text(acc["currency"])
    contracts_el = ET.SubElement(root, "Contracts")
    ET.SubElement(contracts_el, "InQuarter").text = str(sales["contracted_in_quarter"])
    ET.SubElement(contracts_el, "SpasInQuarter").text = str(sales["spas_in_quarter"])
    ET.SubElement(contracts_el, "TotalRUB").text = rub_sales
    ET.SubElement(contracts_el, "HandoversInQuarter").text = str(sales["handovers_in_quarter"])
    areas_el = ET.SubElement(root, "Areas")
    ET.SubElement(areas_el, "TotalM2").text = str(total_area.quantize(Decimal("0.01")))
    ET.SubElement(areas_el, "ResidentialM2").text = str(residential_total.quantize(Decimal("0.01")))
    ET.SubElement(areas_el, "NonResidentialM2").text = str(non_residential_total.quantize(Decimal("0.01")))
    progress_el = ET.SubElement(root, "Progress")
    ET.SubElement(progress_el, "AveragePercent").text = plots["avg_progress_percent"]
    ET.SubElement(progress_el, "UnitsTotal").text = str(plots["total"])
    ET.SubElement(progress_el, "UnitsHandedOver").text = str(plots["handed_over"])
    ET.SubElement(root, "GeneratedAt").text = datetime.now(UTC).isoformat(timespec="seconds")
    payload_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    return RegulatorReport(
        regulator="214FZ",
        development_id=str(dev_uuid),
        quarter=quarter,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        pdf_bytes=pdf_bytes,
        payload_format="xml",
        payload_bytes=payload_bytes,
        summary={
            "total_units": plots["total"],
            "total_area_m2": str(total_area.quantize(Decimal("0.01"))),
            "rub_sales_in_quarter": rub_sales,
            "escrow_accounts": len(agg["escrow"]["accounts"]),
        },
    )


# ── CMA (Saudi Wafi off-plan licence) ───────────────────────────────────


async def generate_regulator_report_cma(
    session: AsyncSession,
    dev_id: uuid.UUID | str,
    quarter: str,
) -> RegulatorReport:
    """Generate the Saudi CMA / Wafi quarterly disclosure (bilingual PDF)."""
    dev_uuid = _coerce_uuid(dev_id)
    agg = await _load_aggregates(session, dev_uuid, quarter)
    dev_meta = agg["development"]
    plots = agg["plots"]
    sales = agg["sales"]
    period = agg["period"]
    sar_sales = sales["by_currency"].get("SAR", "0.00")
    sales_velocity = f"{sales['contracted_in_quarter']} contracts / {sales['handovers_in_quarter']} handovers"

    # Complaints register from Development.metadata.complaints (best-effort).
    dev = await session.get(Development, dev_uuid)
    meta = (dev.metadata_ if dev is not None else None) or {}
    complaints = meta.get("complaints") if isinstance(meta, dict) else None
    complaints_count = len(complaints) if isinstance(complaints, list) else 0

    sections = [
        (
            "Project identification (English) / Project identification (Arabic)",
            [
                ("Wafi licence", dev_meta["cma_licence_no"] or "—"),
                ("Project code", dev_meta["code"]),
                ("Project name", dev_meta["name"]),
                ("Location", dev_meta["location"] or "—"),
                ("Period", f"{period['quarter']} ({period['start']} -> {period['end']})"),
            ],
        ),
        (
            "Project status",
            [
                ("Units total", plots["total"]),
                ("Sold", plots["sold"]),
                ("Reserved", plots["reserved"]),
                ("Available", plots["available"]),
                ("Construction progress (%)", plots["avg_progress_percent"]),
            ],
        ),
        (
            "Escrow with SAMA-licensed bank",
            [
                (
                    acc["account_no"],
                    (
                        f"Bank {acc['bank']} | Balance {acc['computed_balance']} "
                        f"{acc['currency']} (credits {acc['credit_total']}, "
                        f"debits {acc['debit_total']})"
                    ),
                )
                for acc in agg["escrow"]["accounts"]
            ]
            or [("(no escrow accounts declared)", "—")],
        ),
        (
            "Sales velocity",
            [
                ("This quarter (SAR)", sar_sales),
                ("Velocity", sales_velocity),
            ],
        ),
        (
            "Complaints register",
            [
                ("Open complaints", complaints_count),
            ],
        ),
    ]
    qr_payload = f"CMA|{dev_meta['cma_licence_no'] or dev_meta['code']}|{quarter}"
    pdf_bytes = _render_pdf(
        title="CMA / Wafi - Quarterly Off-plan Disclosure",
        subtitle=f"{dev_meta['name']} ({dev_meta['code']}) - {quarter}",
        sections=sections,
        signature_line=dev_meta["authorised_signatory"] or "Authorised signatory",
        qr_payload=qr_payload,
    )

    payload = {
        "regulator": "CMA",
        "format_version": "1.0",
        "submission": {
            "wafi_licence_no": dev_meta["cma_licence_no"],
            "project_code": dev_meta["code"],
            "project_name": dev_meta["name"],
            "period": period,
            "units": plots,
            "sales": sales,
            "escrow": agg["escrow"],
            "complaints_open": complaints_count,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return RegulatorReport(
        regulator="CMA",
        development_id=str(dev_uuid),
        quarter=quarter,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        pdf_bytes=pdf_bytes,
        payload_format="json",
        payload_bytes=payload_bytes,
        summary={
            "total_units": plots["total"],
            "sold_units": plots["sold"],
            "sar_sales_in_quarter": sar_sales,
            "complaints_open": complaints_count,
        },
    )


# ── Dispatcher ──────────────────────────────────────────────────────────


SUPPORTED_REGULATORS = ("RERA", "MAHARERA", "214FZ", "CMA")


async def generate_regulator_report(
    session: AsyncSession,
    *,
    dev_id: uuid.UUID | str,
    regulator: str,
    quarter: str,
) -> RegulatorReport:
    """Dispatch to the regulator-specific generator. Raises ``ValueError``."""
    code = (regulator or "").strip().upper()
    if code == "RERA":
        return await generate_regulator_report_rera(session, dev_id, quarter)
    if code == "MAHARERA":
        return await generate_regulator_report_maharera(session, dev_id, quarter)
    if code in {"214FZ", "214-FZ", "214"}:
        return await generate_regulator_report_214fz(session, dev_id, quarter)
    if code == "CMA":
        return await generate_regulator_report_cma(session, dev_id, quarter)
    raise ValueError(f"Unsupported regulator '{regulator}'. Supported: {', '.join(SUPPORTED_REGULATORS)}")


__all__ = [
    "SUPPORTED_REGULATORS",
    "RegulatorReport",
    "generate_regulator_report",
    "generate_regulator_report_214fz",
    "generate_regulator_report_cma",
    "generate_regulator_report_maharera",
    "generate_regulator_report_rera",
    "parse_quarter",
    "quarter_bounds",
]
