# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost control exports: the cost report, the phase comparison, the invoice ledger, the forecast documentation.

Each is a printable register (landscape PDF) and a workbook built on
:mod:`app.core.register_export`, so they share the page furniture, the
fonts that draw every script, right-to-left text, the project's way of
writing numbers and dates, and amounts kept as numbers in the workbook.
Every word comes from the backend catalogue (``cost_control.export.*`` and
friends in ``backend/locales``) in the reader's language.

The invoice ledger is read from the payment release module and only read:
nothing here changes a release.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_all_translations, resolve_locale, t
from app.core.register_context import load_project_header
from app.core.register_export import (
    EMPTY,
    ProjectHeader,
    RegisterColumn,
    RegisterDocument,
    build_register_pdf,
    build_register_xlsx,
    country_date_format,
    export_filename,
    format_amount,
)
from app.modules.costmodel.cost_control import ZERO
from app.modules.costmodel.cost_control_schemas import PHASE_LAYERS

EXPORT_KINDS: tuple[str, ...] = ("cost_report", "phase_comparison", "invoice_ledger", "forecast_documentation")
EXPORT_FORMATS: tuple[str, ...] = ("pdf", "xlsx")

_MEDIA = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def media_type(fmt: str) -> str:
    return _MEDIA[fmt]


def rendered_language(locale: str) -> str:
    """The language the export's texts come out in for a reader who asked for ``locale``.

    ``t`` walks the requested code, then its base language, then English, key by key. A
    catalogue that resolves but lacks the cost control strings therefore writes English, and
    the response has to say so rather than echo what was asked for.
    """
    resolved = resolve_locale(locale)
    if resolved is not None and "cost_control.export.empty" in get_all_translations(resolved):
        return resolved
    return "en"


class _Words:
    """The catalogue in one language."""

    def __init__(self, locale: str) -> None:
        self.locale = locale

    def __call__(self, key: str, **params: Any) -> str:
        return t(f"cost_control.{key}", locale=self.locale, **params)

    def method(self, method: str) -> str:
        return self(f"method.{method or 'best_available'}")

    def source(self, source: str) -> str:
        return self(f"source.{source or 'none'}")


def _pct_text(value: object) -> str:
    if value in (None, ""):
        return EMPTY
    return f"{value} %"


def _document(
    words: _Words,
    project: ProjectHeader,
    *,
    document_key: str,
    columns: list[RegisterColumn],
    rows: list[list[Any]],
    details: list[tuple[str, str]],
    totals: bool = True,
) -> RegisterDocument:
    date_format = country_date_format(project.country) or "%Y-%m-%d"
    header = [
        (words("export.project"), project.label),
        (words("export.generated"), datetime.now(UTC).date().strftime(date_format)),
        (words("export.currency"), project.currency or EMPTY),
        *details,
    ]
    return RegisterDocument(
        title=words(f"export.{document_key}"),
        columns=columns,
        rows=rows,
        details=header,
        locale=words.locale,
        date_format=date_format,
        number_style=project.number_style,
        page_label=words("export.page"),
        generated_label=words("export.generated_at"),
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        empty_text=words("export.empty"),
        sheet_title=words(f"export.{document_key}"),
        totals_label=words("export.total") if totals else "",
        currency=project.currency,
    )


# ── Cost report ──────────────────────────────────────────────────────────


async def cost_report_document(session: AsyncSession, project_id: uuid.UUID, locale: str) -> RegisterDocument:
    """The cost report along cost lines: plan, commitment, progress, invoices, forecast and variance."""
    from app.modules.costmodel.cost_control_service import CostControlService

    words = _Words(locale)
    project = await load_project_header(session, project_id)
    report = await CostControlService(session).report(project_id)
    account_code = {a.id: a.code for a in report.accounts}
    rows: list[list[Any]] = []
    for r in report.rows:
        description = r.description
        if r.kind == "unassigned":
            description = words("export.row_unassigned")
        elif r.kind == "changes_without_contract":
            description = words("export.row_loose_changes")
        rows.append(
            [
                account_code.get(r.account_id or "", ""),
                r.code,
                description,
                words.source(r.forecast_source),
                words.method(r.forecast_method),
                r.planned,
                r.committed,
                r.pending_changes,
                r.measured,
                r.certified,
                r.invoiced,
                r.paid,
                r.forecast,
                r.variance,
                _pct_text(r.variance_pct),
            ]
        )
    columns = [
        RegisterColumn(words("export.col_account"), nobreak=True, xlsx_width=10),
        RegisterColumn(words("export.col_code"), nobreak=True, xlsx_width=12),
        RegisterColumn(words("export.col_description"), weight=2.5, wrap=True, xlsx_width=36),
        RegisterColumn(words("export.col_source"), xlsx_width=18),
        RegisterColumn(words("export.col_method"), xlsx_width=18),
        RegisterColumn(words("export.col_planned"), kind="money", total=True),
        RegisterColumn(words("export.col_committed"), kind="money", total=True),
        RegisterColumn(words("export.col_pending"), kind="money", total=True),
        RegisterColumn(words("export.col_measured"), kind="money", total=True),
        RegisterColumn(words("export.col_certified"), kind="money", total=True),
        RegisterColumn(words("export.col_invoiced"), kind="money", total=True),
        RegisterColumn(words("export.col_paid"), kind="money", total=True),
        RegisterColumn(words("export.col_forecast"), kind="money", total=True),
        RegisterColumn(words("export.col_variance"), kind="money", total=True),
        RegisterColumn(words("export.col_variance_pct"), nobreak=True, xlsx_width=10),
    ]
    details = [
        (words("export.as_of"), report.as_of),
        (words("export.forecast_method"), words.method(report.forecast_method)),
    ]
    return _document(words, project, document_key="cost_report", columns=columns, rows=rows, details=details)


# ── Phase comparison ─────────────────────────────────────────────────────


async def phase_document(session: AsyncSession, project_id: uuid.UUID, locale: str) -> RegisterDocument:
    """Every layer side by side on the account tree, with the percent columns."""
    from app.modules.costmodel.cost_control_phases import phase_comparison

    words = _Words(locale)
    project = await load_project_header(session, project_id)
    phases = await phase_comparison(session, project_id)
    rows: list[list[Any]] = []
    for r in [*phases.rows, phases.totals]:
        if r.key == "total":
            code, description = "", words("export.total")
        elif r.kind == "unassigned":
            code, description = "", words("export.row_unassigned")
        else:
            # Indentation shows the tree on paper and in the sheet alike.
            code = ("  " * max(r.level - 1, 0)) + r.code
            description = r.description
        rows.append(
            [
                code,
                description,
                *[r.values[layer] for layer in PHASE_LAYERS],
                _pct_text(r.pct.get("forecast")),
                _pct_text(r.progress_pct),
                _pct_text(r.invoiced_pct),
            ]
        )
    columns = [
        RegisterColumn(words("export.col_code"), nobreak=True, xlsx_width=14),
        RegisterColumn(words("export.col_description"), weight=2.0, wrap=True, xlsx_width=32),
        *[RegisterColumn(words(f"layer.{layer}"), kind="money") for layer in PHASE_LAYERS],
        RegisterColumn(words("export.col_forecast_of_plan"), nobreak=True, xlsx_width=10),
        RegisterColumn(words("export.col_measured_of_committed"), nobreak=True, xlsx_width=10),
        RegisterColumn(words("export.col_invoiced_of_committed"), nobreak=True, xlsx_width=10),
    ]
    details = [(words("export.as_of"), phases.as_of)]
    # Accounts already add up their lines, so the register's own totals would count money twice:
    # the last row is the project total instead.
    return _document(
        words, project, document_key="phase_comparison", columns=columns, rows=rows, details=details, totals=False
    )


# ── Invoice ledger ───────────────────────────────────────────────────────


async def ledger_document(session: AsyncSession, project_id: uuid.UUID, locale: str) -> RegisterDocument:
    """One row per supplier invoice: its contract, its release step by step, what is paid and open."""
    try:
        from app.modules.payment_release.service import PaymentReleaseService
    except ImportError as exc:  # pragma: no cover - module not installed
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("cost_control.errors.no_ledger")) from exc

    words = _Words(locale)
    project = await load_project_header(session, project_id)
    ledger = await PaymentReleaseService(session).ledger(project_id)

    def fig(figures: dict[str, Any], key: str) -> Decimal | None:
        raw = figures.get(key)
        return None if raw in (None, "") else Decimal(str(raw))

    rows: list[list[Any]] = []
    for block in ledger.get("contracts") or []:
        for inv in block.get("invoices") or []:
            figures = inv.get("figures") or {}
            rows.append(
                [
                    block.get("code") or "",
                    block.get("title") or "",
                    inv.get("number") or "",
                    inv.get("invoice_date"),
                    words(f"invoice_kind.{inv.get('kind') or 'interim'}"),
                    words(f"release_status.{inv.get('release_status') or 'open'}"),
                    fig(figures, "net_after"),
                    fig(figures, "vat_after"),
                    fig(figures, "gross_after"),
                    fig(figures, "retention"),
                    fig(figures, "release"),
                    fig(figures, "discount"),
                    fig(figures, "payable"),
                    Decimal(str(inv.get("paid") or "0")),
                    Decimal(str(inv.get("open_amount") or "0")),
                ]
            )
    for inv in ledger.get("other_invoices") or []:
        rows.append(
            [
                "",
                words("export.row_no_contract"),
                inv.get("number") or "",
                inv.get("invoice_date"),
                EMPTY,
                EMPTY,
                Decimal(str(inv.get("net") or "0")),
                None,
                Decimal(str(inv.get("gross") or "0")),
                None,
                None,
                None,
                None,
                Decimal(str(inv.get("paid") or "0")),
                Decimal(str(inv.get("gross") or "0")) - Decimal(str(inv.get("paid") or "0")),
            ]
        )
    columns = [
        RegisterColumn(words("export.col_contract"), nobreak=True, xlsx_width=12),
        RegisterColumn(words("export.col_contract_title"), weight=1.6, wrap=True, xlsx_width=28),
        RegisterColumn(words("export.col_invoice"), nobreak=True, xlsx_width=14),
        RegisterColumn(words("export.col_date"), kind="date", xlsx_width=12),
        RegisterColumn(words("export.col_kind"), xlsx_width=14),
        RegisterColumn(words("export.col_release_status"), xlsx_width=14),
        RegisterColumn(words("export.col_net"), kind="money", total=True),
        RegisterColumn(words("export.col_vat"), kind="money", total=True),
        RegisterColumn(words("export.col_gross"), kind="money", total=True),
        RegisterColumn(words("export.col_retention"), kind="money", total=True),
        RegisterColumn(words("export.col_release"), kind="money", total=True),
        RegisterColumn(words("export.col_discount"), kind="money", total=True),
        RegisterColumn(words("export.col_payable"), kind="money", total=True),
        RegisterColumn(words("export.col_paid"), kind="money", total=True),
        RegisterColumn(words("export.col_open"), kind="money", total=True),
    ]
    totals = ledger.get("totals") or {}
    details = [
        (
            words("export.contract_value"),
            format_amount(totals.get("contract_value") or "0", project.number_style, project.currency),
        ),
        (
            words("export.retention_held"),
            format_amount(totals.get("retention_held") or "0", project.number_style, project.currency),
        ),
    ]
    return _document(words, project, document_key="invoice_ledger", columns=columns, rows=rows, details=details)


# ── Forecast documentation ───────────────────────────────────────────────


async def forecast_document(
    session: AsyncSession, project_id: uuid.UUID, locale: str, snapshot_id: uuid.UUID | None
) -> RegisterDocument:
    """A snapshot's lines, largest move first, with method, source, move, comment and evidence.

    Without a snapshot named, the latest frozen one, else the open draft.
    """
    from app.modules.costmodel.cost_control_forecast import ForecastDocsService
    from app.modules.costmodel.cost_control_service import CostControlService

    words = _Words(locale)
    project = await load_project_header(session, project_id)
    docs = ForecastDocsService(session)
    control = CostControlService(session)
    if snapshot_id is not None:
        snap = await docs.snapshot(snapshot_id)
        if snap.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("cost_control.errors.snapshot_missing"))
    else:
        snap = await control.latest_frozen(project_id) or await control.open_draft(project_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("cost_control.errors.no_snapshot"))
    detail = await docs.snapshot_detail(snap, locale=locale)
    lines = sorted(detail.lines, key=lambda line: (-abs(line.delta), line.code))
    rows: list[list[Any]] = []
    for line in lines:
        evidence = "; ".join(
            f"{words(f'evidence_kind.{e.kind}')}: {e.ref or EMPTY}" for e in line.evidence if e.ref or e.document_id
        )
        description = line.description
        if line.kind == "unassigned":
            description = words("export.row_unassigned")
        elif line.kind == "changes_without_contract":
            description = words("export.row_loose_changes")
        rows.append(
            [
                line.code,
                description,
                words.method(line.method),
                words.source(line.source),
                line.previous,
                line.forecast,
                line.delta,
                _pct_text(line.delta_pct),
                words("export.yes") if line.needs_evidence else words("export.no"),
                line.comment or EMPTY,
                evidence or EMPTY,
            ]
        )
    columns = [
        RegisterColumn(words("export.col_code"), nobreak=True, xlsx_width=12),
        RegisterColumn(words("export.col_description"), weight=1.6, wrap=True, xlsx_width=30),
        RegisterColumn(words("export.col_method"), xlsx_width=18),
        RegisterColumn(words("export.col_source"), xlsx_width=18),
        RegisterColumn(words("export.col_previous"), kind="money", total=True),
        RegisterColumn(words("export.col_forecast"), kind="money", total=True),
        RegisterColumn(words("export.col_delta"), kind="money", total=True),
        RegisterColumn(words("export.col_delta_pct"), nobreak=True, xlsx_width=10),
        RegisterColumn(words("export.col_needs_evidence"), xlsx_width=10),
        RegisterColumn(words("export.col_comment"), weight=2.0, wrap=True, xlsx_width=40),
        RegisterColumn(words("export.col_evidence"), weight=1.6, wrap=True, xlsx_width=32),
    ]
    threshold_parts = []
    if detail.threshold_amount and detail.threshold_amount > ZERO:
        threshold_parts.append(format_amount(detail.threshold_amount, project.number_style, project.currency))
    if detail.threshold_pct is not None and detail.threshold_pct > ZERO:
        threshold_parts.append(f"{detail.threshold_pct} %")
    details = [
        (words("export.snapshot_date"), detail.taken_on),
        (words("export.snapshot_status"), words(f"snapshot_status.{detail.status}")),
        (words("export.previous_snapshot"), detail.previous.taken_on if detail.previous else EMPTY),
        (words("export.forecast_method"), words.method(detail.forecast_method)),
        (words("export.method_explained"), words(f"method_help.{detail.forecast_method}")),
        (
            words("export.evidence_threshold"),
            words("export.threshold_both", parts=" + ".join(threshold_parts))
            if threshold_parts
            else words("export.threshold_any"),
        ),
    ]
    if detail.frozen_at is not None:
        details.append((words("export.frozen_at"), detail.frozen_at.strftime("%Y-%m-%d %H:%M UTC")))
    return _document(words, project, document_key="forecast_documentation", columns=columns, rows=rows, details=details)


async def render_export(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: str,
    fmt: str,
    locale: str,
    *,
    snapshot_id: uuid.UUID | None = None,
) -> tuple[bytes, str]:
    """The export's bytes and its download name."""
    if kind == "cost_report":
        document = await cost_report_document(session, project_id, locale)
    elif kind == "phase_comparison":
        document = await phase_document(session, project_id, locale)
    elif kind == "invoice_ledger":
        document = await ledger_document(session, project_id, locale)
    else:
        document = await forecast_document(session, project_id, locale, snapshot_id)
    if fmt == "xlsx":
        buffer: io.BytesIO = build_register_xlsx(document)
        data = buffer.getvalue()
    else:
        data = build_register_pdf(document)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return data, export_filename(f"{kind}_{stamp}", kind, fmt)
