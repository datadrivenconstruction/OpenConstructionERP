# DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cash-flow forecast: project and portfolio views, rules, events and export."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.costmodel.cashflow_forecast import (
    ZERO,
    CurrencyForecast,
    Month,
    Scenario,
    aggregate,
    build_forecast,
)
from app.modules.costmodel.cashflow_forecast_data import ProjectInputs, collect_project
from app.modules.costmodel.cashflow_forecast_rules import PAYLOAD_KEY, RULE_SET
from app.modules.costmodel.cashflow_forecast_schemas import (
    CashFlowEvaluation,
    CashFlowFinding,
    CashFlowMonthOut,
    CashFlowScenario,
    CashFlowSourceOut,
    CashFlowTotals,
    CurrencyForecastOut,
    PeakFunding,
    PortfolioCashFlowForecast,
    PortfolioCurrencyOut,
    PortfolioProjectRow,
    ProjectCashFlowForecast,
    ProjectRef,
)

EVENT_EVALUATED = "costmodel.cashflow_forecast.evaluated"
EVENT_NEGATIVE_POSITION = "costmodel.cashflow_forecast.negative_position"
EVENT_RECEIPT_OVERDUE = "costmodel.cashflow_forecast.receipt_overdue"

_EVENT_FOR_RULE = {
    "cashflow_forecast.negative_position": EVENT_NEGATIVE_POSITION,
    "cashflow_forecast.receipt_overdue": EVENT_RECEIPT_OVERDUE,
}


def _s(value: Decimal) -> str:
    return format(value, "f")


def parse_pct(value: str | None) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except InvalidOperation:
        return ZERO


def _month_out(m: Month) -> CashFlowMonthOut:
    return CashFlowMonthOut(
        period=m.period,
        is_past=m.is_past,
        planned_in=_s(m.planned_in),
        planned_out=_s(m.planned_out),
        actual_in=_s(m.actual_in),
        actual_out=_s(m.actual_out),
        expected_in=_s(m.expected_in),
        expected_out=_s(m.expected_out),
        net=_s(m.net),
        cumulative=_s(m.cumulative),
        variance_in=_s(m.variance_in),
        variance_out=_s(m.variance_out),
    )


def _peak_out(f: CurrencyForecast) -> PeakFunding | None:
    return PeakFunding(amount=_s(f.peak.amount), period=f.peak.period) if f.peak else None


def currency_out(f: CurrencyForecast) -> CurrencyForecastOut:
    return CurrencyForecastOut(
        currency=f.currency,
        months=[_month_out(m) for m in f.months],
        totals=CashFlowTotals(
            **{
                k: _s(f.total(k))
                for k in ("planned_in", "planned_out", "actual_in", "actual_out", "expected_in", "expected_out")
            }
        ),
        sources=[CashFlowSourceOut(source=src, direction=d, amount=_s(v)) for (src, d), v in sorted(f.sources.items())],
        closing_position=_s(f.closing_position),
        peak_funding=_peak_out(f),
    )


def overdue_receipts(inp: ProjectInputs, today: date) -> list[dict[str, str]]:
    return [
        {
            "ref": line.ref,
            "label": line.label,
            "amount": _s(line.open),
            "currency": line.currency,
            "due": line.due.isoformat(),
            "days": str((today - line.due).days),
        }
        for line in inp.lines
        if line.direction == "in" and line.due is not None and line.due < today and line.open > ZERO
    ]


class CashFlowForecastService:
    def __init__(self, session: AsyncSession, *, today: date | None = None) -> None:
        self.session = session
        self.today = today or datetime.now(UTC).date()

    async def _inputs(self, project_id: uuid.UUID) -> ProjectInputs | None:
        return await collect_project(self.session, project_id, self.today)

    async def _findings(
        self,
        inp: ProjectInputs,
        currencies: list[CurrencyForecastOut],
        threshold: Decimal,
        locale: str,
    ) -> list[CashFlowFinding]:
        payload: dict[str, Any] = {
            "project_name": inp.name,
            "project_status": inp.status,
            "has_inputs": inp.has_inputs,
            "threshold": _s(threshold),
            "currencies": [c.model_dump() for c in currencies],
            "overdue": overdue_receipts(inp, self.today),
        }
        context = ValidationContext(
            data={PAYLOAD_KEY: payload}, project_id=str(inp.project_id), metadata={"locale": locale}
        )
        out: list[CashFlowFinding] = []
        for rule in rule_registry.get_rules_for_sets([RULE_SET]):
            if not rule.enabled:
                continue
            for r in await rule.validate(context):
                if r.passed:
                    continue
                out.append(
                    CashFlowFinding(
                        rule_id=r.rule_id,
                        severity=r.severity.value,
                        message=r.message,
                        suggestion=r.suggestion or "",
                        element_ref=r.element_ref,
                        details={k: str(v) for k, v in (r.details or {}).items()},
                    )
                )
        return out

    async def project(
        self,
        project_id: uuid.UUID,
        scenario: Scenario,
        *,
        threshold: Decimal | None = None,
        locale: str = "en",
    ) -> ProjectCashFlowForecast | None:
        inp = await self._inputs(project_id)
        if inp is None:
            return None
        return await self._project_from(inp, scenario, threshold=threshold, locale=locale)

    async def _project_from(
        self, inp: ProjectInputs, scenario: Scenario, *, threshold: Decimal | None, locale: str
    ) -> ProjectCashFlowForecast:
        tables = build_forecast(inp.lines, inp.actuals, today=self.today, scenario=scenario)
        currencies = [currency_out(t) for t in tables]
        limit = threshold if threshold is not None else inp.threshold
        return ProjectCashFlowForecast(
            project_id=str(inp.project_id),
            project_name=inp.name,
            as_of=self.today.isoformat(),
            scenario=CashFlowScenario(
                receipt_delay_days=scenario.receipt_delay_days, cost_overrun_pct=_s(scenario.cost_overrun_pct)
            ),
            threshold=_s(limit),
            has_inputs=inp.has_inputs,
            currencies=currencies,
            findings=await self._findings(inp, currencies, limit, locale),
        )

    async def portfolio(
        self, project_ids: list[uuid.UUID] | None, scenario: Scenario, *, locale: str = "en"
    ) -> PortfolioCashFlowForecast:
        """Every active project in scope, summed per currency and never across currencies."""
        from app.modules.projects.models import Project

        stmt = select(Project.id).where(Project.status.in_(("active", "in_progress", "construction", "planning")))
        if project_ids is not None:
            if not project_ids:
                return PortfolioCashFlowForecast(
                    as_of=self.today.isoformat(),
                    scenario=CashFlowScenario(
                        receipt_delay_days=scenario.receipt_delay_days, cost_overrun_pct=_s(scenario.cost_overrun_pct)
                    ),
                    currencies=[],
                    projects_without_forecast=[],
                    findings_count=0,
                )
            stmt = stmt.where(Project.id.in_(project_ids))
        ids = [pid for (pid,) in (await self.session.execute(stmt.order_by(Project.name))).all()]
        per_ccy: dict[str, list[tuple[ProjectInputs, CurrencyForecast]]] = {}
        missing: list[ProjectRef] = []
        findings = 0
        for pid in ids:
            inp = await self._inputs(pid)
            if inp is None:
                continue
            if not inp.has_inputs:
                missing.append(ProjectRef(project_id=str(pid), project_name=inp.name))
            tables = build_forecast(inp.lines, inp.actuals, today=self.today, scenario=scenario)
            for t in tables:
                per_ccy.setdefault(t.currency, []).append((inp, t))
            findings += len(await self._findings(inp, [currency_out(t) for t in tables], inp.threshold, locale))
        currencies = []
        for ccy in sorted(per_ccy):
            rows = per_ccy[ccy]
            total = aggregate([t for _, t in rows])
            currencies.append(
                PortfolioCurrencyOut(
                    currency=ccy,
                    months=[_month_out(m) for m in total.months],
                    closing_position=_s(total.closing_position),
                    peak_funding=_peak_out(total),
                    projects=[
                        PortfolioProjectRow(
                            project_id=str(inp.project_id),
                            project_name=inp.name,
                            closing_position=_s(t.closing_position),
                            peak_funding=_peak_out(t),
                            negative=t.peak is not None,
                        )
                        for inp, t in rows
                    ],
                )
            )
        return PortfolioCashFlowForecast(
            as_of=self.today.isoformat(),
            scenario=CashFlowScenario(
                receipt_delay_days=scenario.receipt_delay_days, cost_overrun_pct=_s(scenario.cost_overrun_pct)
            ),
            currencies=currencies,
            projects_without_forecast=missing,
            findings_count=findings,
        )

    async def evaluate(
        self, project_id: uuid.UUID, scenario: Scenario, *, threshold: Decimal | None, locale: str
    ) -> CashFlowEvaluation | None:
        """Run the rules and publish one event per finding plus a summary event."""
        forecast = await self.project(project_id, scenario, threshold=threshold, locale=locale)
        if forecast is None:
            return None
        published = 0
        for f in forecast.findings:
            name = _EVENT_FOR_RULE.get(f.rule_id)
            if name is None:
                continue
            event_bus.publish_detached(
                name,
                {"project_id": str(project_id), "rule_id": f.rule_id, "element_ref": f.element_ref, **f.details},
                source_module="costmodel",
            )
            published += 1
        event_bus.publish_detached(
            EVENT_EVALUATED,
            {
                "project_id": str(project_id),
                "findings": len(forecast.findings),
                "peak_funding": {
                    c.currency: (c.peak_funding.model_dump() if c.peak_funding else None) for c in forecast.currencies
                },
            },
            source_module="costmodel",
        )
        return CashFlowEvaluation(findings=forecast.findings, published=published + 1)


# ── Excel export ─────────────────────────────────────────────────────────────

_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("period", "text"),
    ("planned_in", "money"),
    ("actual_in", "money"),
    ("expected_in", "money"),
    ("planned_out", "money"),
    ("actual_out", "money"),
    ("expected_out", "money"),
    ("net", "money"),
    ("cumulative", "money"),
)


def _workbook(
    title: str, sheets: list[tuple[str, list[CashFlowMonthOut], list[tuple[str, str]]]], locale: str
) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from app.core.i18n import t

    def word(key: str) -> str:
        return t(f"cashflow_forecast.export.{key}", locale=locale)

    wb = Workbook()
    wb.remove(wb.active)
    if not sheets:
        ws = wb.create_sheet(word("title")[:31])
        ws.append([word("empty")])
    for name, months, details in sheets:
        ws = wb.create_sheet(name[:31] or "-")
        ws.append([title])
        ws["A1"].font = Font(bold=True)
        for label, value in details:
            ws.append([label, value])
        ws.append([])
        ws.append([word(f"col.{key}") for key, _ in _EXPORT_COLUMNS])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        for m in months:
            row: list[Any] = []
            for key, kind in _EXPORT_COLUMNS:
                value = getattr(m, key)
                row.append(Decimal(value) if kind == "money" else value)
            ws.append(row)
            for cell in ws[ws.max_row][1:]:
                cell.number_format = "#,##0.00"
        for col, width in zip("ABCDEFGHI", (10, 16, 16, 16, 16, 16, 16, 16, 18), strict=True):
            ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def project_workbook(forecast: ProjectCashFlowForecast, locale: str) -> bytes:
    from app.core.i18n import t

    def word(key: str) -> str:
        return t(f"cashflow_forecast.export.{key}", locale=locale)

    sheets = []
    for c in forecast.currencies:
        details = [
            (word("project"), forecast.project_name),
            (word("as_of"), forecast.as_of),
            (word("currency"), c.currency),
            (word("delay_days"), str(forecast.scenario.receipt_delay_days)),
            (word("overrun_pct"), forecast.scenario.cost_overrun_pct),
            (word("closing_position"), c.closing_position),
            (word("peak_funding"), c.peak_funding.amount if c.peak_funding else "0"),
            (word("peak_period"), c.peak_funding.period if c.peak_funding else ""),
        ]
        sheets.append((c.currency, c.months, details))
    return _workbook(word("title"), sheets, locale)


def portfolio_workbook(forecast: PortfolioCashFlowForecast, locale: str) -> bytes:
    from app.core.i18n import t

    def word(key: str) -> str:
        return t(f"cashflow_forecast.export.{key}", locale=locale)

    sheets = []
    for c in forecast.currencies:
        details = [
            (word("as_of"), forecast.as_of),
            (word("currency"), c.currency),
            (word("delay_days"), str(forecast.scenario.receipt_delay_days)),
            (word("overrun_pct"), forecast.scenario.cost_overrun_pct),
            (word("closing_position"), c.closing_position),
            (word("peak_funding"), c.peak_funding.amount if c.peak_funding else "0"),
            (word("peak_period"), c.peak_funding.period if c.peak_funding else ""),
        ]
        details += [
            (p.project_name, p.peak_funding.amount + " / " + p.peak_funding.period if p.peak_funding else "0")
            for p in c.projects
        ]
        sheets.append((c.currency, c.months, details))
    return _workbook(word("portfolio_title"), sheets, locale)
