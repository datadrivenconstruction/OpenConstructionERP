# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Project Controls service - the cross-module aggregation tissue.

The snapshot does NOT re-query each module directly. It calls the already
built :func:`app.modules.bi_dashboards.kpis.compute` for each code in the
executive spine, fanned out with :func:`asyncio.gather`, so every KPI keeps
its own graceful-degradation and currency-honest contract. The service then
bands each value green/amber/red against the active thresholds and stamps a
cross-module drill URL. Pure read-only.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards import kpis as kpi_registry
from app.modules.project_controls import thresholds as threshold_rules

logger = logging.getLogger(__name__)

# EVM ratio KPIs (CPI / SPI) are EV / AC and EV / PV respectively. When a
# project carries no earned-value basis yet (EV == 0 - no task progress /
# percent-complete recorded), these ratios collapse to exactly 0. A literal
# 0 is not a real "performance has cratered" reading: it just means there is
# no earned value to divide. We treat that case as "no data" so the tile shows
# a neutral dash instead of a misleading red 0, and we suppress the false
# alert. A genuinely computed CPI/SPI on real data is essentially never 0.
_EVM_RATIO_CODES = {"cpi", "spi"}


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


# The executive spine: ordered domains, each with its KPI codes + a label.
# Codes resolve against the shared bi_dashboards.kpis registry.
SPINE: list[dict[str, Any]] = [
    {
        "domain": "cost",
        "label": "Cost",
        "codes": ["cpi", "cv", "eac", "vac"],
    },
    {
        "domain": "schedule",
        "label": "Schedule",
        "codes": ["spi", "sv", "milestone_slippage_days"],
    },
    {
        "domain": "quality",
        "label": "Quality",
        "codes": ["first_pass_yield", "copq", "ncr_open_count", "rfi_close_avg_days"],
    },
    {
        "domain": "safety",
        "label": "Safety",
        "codes": ["safety_trir", "incident_count"],
    },
    {
        "domain": "risk",
        "label": "Risk",
        "codes": ["risk_open_exposure", "risk_high_unmitigated_count"],
    },
    {
        "domain": "changes",
        "label": "Changes",
        "codes": ["change_order_ratio", "pending_variation_value"],
    },
]

# Friendly labels for KPI codes (fall back to the registry metadata name).
_KPI_LABELS: dict[str, str] = {
    "cpi": "Cost Performance Index",
    "cv": "Cost Variance",
    "eac": "Estimate at Completion",
    "vac": "Variance at Completion",
    "spi": "Schedule Performance Index",
    "sv": "Schedule Variance",
    "milestone_slippage_days": "Milestone Slippage",
    "first_pass_yield": "First Pass Yield",
    "copq": "Cost of Poor Quality",
    "ncr_open_count": "Open NCRs",
    "rfi_close_avg_days": "RFI Turnaround",
    "safety_trir": "Recordable Incident Rate",
    "incident_count": "Safety Incidents",
    "risk_open_exposure": "Open Risk Exposure",
    "risk_high_unmitigated_count": "High Unmitigated Risks",
    "change_order_ratio": "Change Order Ratio",
    "pending_variation_value": "Pending Variation Value",
}

# Maps the ``kind`` carried on a drill record to an in-app deep-link template.
# ``{id}`` and ``{project_id}`` are substituted from the record. The owning
# module page reads the query string to focus the row.
_DEEP_LINK_TEMPLATES: dict[str, str] = {
    "risk": "/risks?id={id}",
    "ncr": "/ncr?id={id}",
    "incident": "/safety?id={id}",
    "variation_request": "/variations?id={id}",
    "activity": "/schedule?activity={id}",
    "task": "/tasks?id={id}",
    "payment": "/finance?id={id}",
    "purchase_order": "/procurement?id={id}",
    "project": "/projects/{id}",
    # CONN-77: the 4 previously dead spine tiles now drill to real rows.
    # ``inspection`` and ``change_order`` use the module page's ?id= focus
    # param; ``rfi`` jumps straight to its detail route. The inspections
    # page already reads ?id=; the RFI detail route exists; the change
    # orders page consumer lands with a sibling batch.
    "inspection": "/inspections?id={id}",
    "rfi": "/rfi/{id}",
    "change_order": "/changeorders?id={id}",
}


def _fmt_number(value: Any) -> str:
    """Plain numeric string for a KPI tile value, never scientific notation.

    ``str(Decimal("0E+2"))`` yields ``"0E+2"``; the dashboard tiles need a bare
    number (they render their own unit), so normalise the same way
    :func:`_fmt_value` does but without the unit/currency decoration.
    """
    dec = _to_decimal_or_none(value)
    if dec is None:
        return str(value)
    normalised = dec.quantize(Decimal(1)) if dec == dec.to_integral_value() else dec.normalize()
    return f"{normalised:f}"


def _fmt_value(value: Any, unit: str, breakdown: dict[str, Any] | None) -> str:
    """Render a KPI value for an alert message without scientific notation.

    Currency values carry their ISO code (never blended); ratios / counts /
    percents / days get a short suffix. Falls back to the raw value when it
    cannot be parsed as a number.
    """
    dec = _to_decimal_or_none(value)
    if dec is None:
        return f"{value} {unit}".strip()
    # Normalise so Decimal("0E+1") prints as "0", and trim trailing zeros.
    normalised = dec.quantize(Decimal(1)) if dec == dec.to_integral_value() else dec.normalize()
    num = f"{normalised:f}"
    if unit == "currency":
        code = str((breakdown or {}).get("currency") or "").strip().upper()
        return f"{code} {num}".strip() if code else num
    if unit == "percent":
        return f"{num}%"
    if unit == "days":
        return f"{num}d"
    return num


def _label_for(code: str) -> str:
    if code in _KPI_LABELS:
        return _KPI_LABELS[code]
    meta = kpi_registry.SYSTEM_KPI_META.get(code)
    if meta:
        return str(meta.get("name") or code)
    return code.replace("_", " ").title()


def _drill_url(code: str, project_id: uuid.UUID | None) -> str:
    base = f"/api/v1/project-controls/drill/{code}"
    if project_id is not None:
        return f"{base}?project_id={project_id}"
    return base


def _deep_link(record: dict[str, Any]) -> str | None:
    kind = str(record.get("kind") or "")
    template = _DEEP_LINK_TEMPLATES.get(kind)
    if not template:
        return None
    rid = str(record.get("id") or "")
    if not rid:
        return None
    return template.format(id=rid, project_id=record.get("project_id") or "")


class ProjectControlsService:
    """Read-only aggregation over the shared KPI registry."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def snapshot(
        self,
        *,
        project_id: uuid.UUID | None,
        period_start: _date | None = None,
        period_end: _date | None = None,
        thresholds: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Compute the whole controls spine in one round-trip.

        Each KPI is computed via ``kpis.compute`` (graceful-degradation built
        in). Money KPIs carry their own per-currency breakdown so the client
        groups by ISO code in portfolio mode; the snapshot surfaces an overall
        ``multi_currency`` flag and a headline ``currency``.
        """
        # Flatten the spine into (domain, code) pairs preserving order so the
        # gathered results map back cleanly.
        flat: list[tuple[str, str]] = []
        for group in SPINE:
            for code in group["codes"]:
                flat.append((group["domain"], code))

        async def _one(code: str) -> kpi_registry.KPIComputation:
            return await kpi_registry.compute(
                code,
                self.session,
                project_id=project_id,
                period_start=period_start,
                period_end=period_end,
            )

        results = await asyncio.gather(*[_one(code) for _, code in flat])
        by_code: dict[str, kpi_registry.KPIComputation] = {
            code: comp for (_, code), comp in zip(flat, results, strict=True)
        }

        multi_currency = False
        currency = ""
        alerts: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []

        for group in SPINE:
            kpi_tiles: list[dict[str, Any]] = []
            for code in group["codes"]:
                comp = by_code[code]
                breakdown = comp.breakdown or {}
                if breakdown.get("multi_currency"):
                    multi_currency = True
                if not currency and comp.unit == "currency":
                    currency = str(breakdown.get("currency") or "")

                # EVM ratio with no earned-value basis -> treat as no data so
                # the tile shows a neutral dash, not a misleading red 0.
                record_count = comp.source_record_count
                no_evm_basis = False
                if code in _EVM_RATIO_CODES:
                    ev = _to_decimal_or_none(breakdown.get("ev"))
                    if (ev is None or ev == 0) and (_to_decimal_or_none(comp.value) == 0):
                        no_evm_basis = True
                        record_count = 0

                if no_evm_basis:
                    status = "green"
                else:
                    status = threshold_rules.band_status(
                        code,
                        comp.value,
                        overrides=thresholds,
                    )
                if status != "green" and record_count > 0:
                    alerts.append(
                        {
                            "kpi_code": code,
                            "severity": "critical" if status == "red" else "warning",
                            "message": (
                                f"{_label_for(code)} is {status} ({_fmt_value(comp.value, comp.unit, breakdown)})."
                            ),
                        }
                    )
                kpi_tiles.append(
                    {
                        "code": code,
                        "label": _label_for(code),
                        "value": _fmt_number(comp.value),
                        "unit": comp.unit,
                        "status": status,
                        "source_record_count": record_count,
                        "breakdown": breakdown,
                        "drill_url": _drill_url(code, project_id),
                    }
                )
            groups.append(
                {
                    "domain": group["domain"],
                    "label": group["label"],
                    "kpis": kpi_tiles,
                }
            )

        return {
            "project_id": str(project_id) if project_id else None,
            "currency": currency,
            "multi_currency": multi_currency,
            "generated_at": datetime.now(UTC).isoformat(),
            "groups": groups,
            "alerts": alerts,
        }

    async def drill(
        self,
        code: str,
        *,
        project_id: uuid.UUID | None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return the underlying rows for a KPI, each enriched with a deep link.

        Delegates to the shared ``kpis.drilldown`` record providers, then maps
        each row's ``kind`` to an in-app cross-module deep link so a click on
        the dashboard jumps straight to the owning module's detail page.
        """
        rows = await kpi_registry.drilldown(
            code,
            self.session,
            project_id=project_id,
            limit=limit,
        )
        records = [{"fields": row, "deep_link": _deep_link(row)} for row in rows]
        return {
            "kpi_code": code,
            "project_id": str(project_id) if project_id else None,
            "record_count": len(records),
            "records": records,
        }
