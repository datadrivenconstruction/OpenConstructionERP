# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Component input tax inside :class:`AssemblyService` (issue #559).

Everything here is behind ``Project.component_tax_enabled``. An assembly with no
project, or whose project has the switch off, gets no context from
:meth:`AssemblyTaxMixin.tax_context` and every caller falls through to the
pre-existing arithmetic untouched.

A component's ``total`` is its cost (net, plus the tax the project folds into
cost), so apply-to-bill, the assembly total and the exports keep reading one
number. The split lives in ``metadata["tax"]`` on the component and in
``metadata["tax_totals"]`` on the assembly. Prices move only through the explicit
:meth:`AssemblyTaxMixin.recalculate_tax` action, and an approved assembly is never
changed by it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from app.modules.assemblies import component_tax as ct
from app.modules.assemblies.models import Assembly, Component
from app.modules.assemblies.schemas import ProjectTaxRecalcResponse, TaxFinding, TaxRecalcResponse
from app.modules.i18n_foundation.tax_rules import TaxRateRow, row_from_orm

logger = logging.getLogger(__name__)

_TAX_FIELDS = ("tax_code", "tax_rate", "tax_status", "price_includes_tax", "input_tax_treatment")
_APPROVED_STATES = ("approved", "released", "frozen")


def is_approved(assembly: Assembly) -> bool:
    """Whether the assembly has been approved: ``metadata.status`` (or ``approved: true``)."""
    meta = assembly.metadata_ if isinstance(assembly.metadata_, dict) else {}
    return bool(meta.get("approved")) or str(meta.get("status") or "").lower() in _APPROVED_STATES


@dataclass(frozen=True)
class TaxContext:
    """What pricing a project's components needs: its default treatment, place, date and the registry."""

    treatment: str
    country: str | None
    subdivision: str | None
    rows: list[TaxRateRow]
    on_date: str
    currency: str


@dataclass
class LineOutcome:
    """The tax result of one component."""

    total: Decimal
    breakdown: ct.LineTax | None
    rate: ct.RateResult | None
    effective: ct.EffectiveTax
    entered: Decimal


async def tax_managed_assembly_ids(session: Any, assembly_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The assemblies, among ``assembly_ids``, whose project has component tax switched on."""
    if not assembly_ids:
        return set()
    from app.modules.projects.models import Project  # noqa: PLC0415

    stmt = (
        select(Assembly.id)
        .join(Project, Project.id == Assembly.project_id)
        .where(Assembly.id.in_(assembly_ids), Project.component_tax_enabled.is_(True))
    )
    return set((await session.execute(stmt)).scalars().all())


def _entered_price(comp: Any) -> Decimal:
    """The component's line price as entered (factor x quantity x unit cost, typed adjustments)."""
    from app.modules.assemblies.service import _compute_typed_total, _str_to_float  # noqa: PLC0415

    meta = comp.metadata_ if isinstance(comp.metadata_, dict) else {}
    raw = _compute_typed_total(
        resource_type=comp.resource_type,
        factor=_str_to_float(comp.factor),
        quantity=_str_to_float(comp.quantity),
        unit_cost=_str_to_float(comp.unit_cost),
        metadata=meta,
    )
    return ct.to_decimal(raw) or Decimal("0")


def component_cost_with_tax(comp: Any, entered: Decimal, currency: str | None) -> Decimal:
    """``entered`` re-priced with the tax profile stored on the component; ``entered`` itself without one."""
    stored = comp.metadata_.get("tax") if isinstance(comp.metadata_, dict) else None
    if not isinstance(stored, dict):
        return entered
    rate = ct.to_decimal(stored.get("rate_pct"))
    if rate is None or stored.get("status") not in ct.TAX_STATUSES or stored.get("treatment") not in ct.TAX_TREATMENTS:
        return entered
    return ct.compute_line_tax(
        entered,
        status=stored["status"],
        rate_pct=rate,
        includes_tax=bool(stored.get("price_includes_tax")),
        treatment=stored["treatment"],
        currency=currency,
    ).cost


def _outcome(ctx: TaxContext, comp: Any, resource: Any | None) -> LineOutcome:
    entered = _entered_price(comp)
    eff = ct.effective_tax(comp, resource, ctx.treatment)
    if eff.status is None and not any(getattr(comp, f, None) not in (None, "") for f in ("tax_code", "tax_rate")):
        return LineOutcome(entered, None, None, eff, entered)
    rate = ct.resolve_rate(
        comp, resource, rows=ctx.rows, country=ctx.country, subdivision=ctx.subdivision, on_date=ctx.on_date
    )
    status_ = eff.status or ("taxable" if rate.rate_pct is not None else None)
    if status_ is None or (status_ == "taxable" and rate.rate_pct is None):
        return LineOutcome(entered, None, rate, eff, entered)
    line = ct.compute_line_tax(
        entered,
        status=status_,
        rate_pct=rate.rate_pct,
        includes_tax=eff.includes_tax,
        treatment=eff.treatment or ct.DEFAULT_TREATMENT,
        currency=ctx.currency,
    )
    return LineOutcome(line.cost, line, rate, eff, entered)


def _meta_with_tax(meta: Any, outcome: LineOutcome) -> dict[str, Any]:
    out = dict(meta) if isinstance(meta, dict) else {}
    if outcome.breakdown is None:
        out.pop("tax", None)
    else:
        out["tax"] = {**outcome.breakdown.as_dict(), "rate_source": outcome.rate.source if outcome.rate else None}
    return out


class AssemblyTaxMixin:
    """Tax-aware pricing and the explicit recalculation, mixed into ``AssemblyService``."""

    session: Any
    assembly_repo: Any
    component_repo: Any

    async def tax_context(self, assembly: Assembly, as_of: str | None = None) -> TaxContext | None:
        """The pricing context, or ``None`` when the assembly's project does not use component tax."""
        if assembly.project_id is None:
            return None
        from app.modules.i18n_foundation.models import TaxConfiguration  # noqa: PLC0415
        from app.modules.projects.models import Project  # noqa: PLC0415

        project = await self.session.get(Project, assembly.project_id)
        if project is None or not getattr(project, "component_tax_enabled", False):
            return None
        country = (project.country_code or "").strip().upper() or None
        rows: list[TaxRateRow] = []
        if country:
            found = await self.session.execute(select(TaxConfiguration).where(TaxConfiguration.country_code == country))
            rows = [row_from_orm(c) for c in found.scalars().all()]
        return TaxContext(
            treatment=project.component_tax_treatment or ct.DEFAULT_TREATMENT,
            country=country,
            subdivision=(project.subdivision_code or "").strip().upper() or None,
            rows=rows,
            on_date=as_of or datetime.now(tz=UTC).date().isoformat(),
            currency=assembly.currency or project.currency or "",
        )

    async def _resource(self, resource_id: uuid.UUID | None) -> Any | None:
        if resource_id is None:
            return None
        from app.modules.catalog.models import CatalogResource  # noqa: PLC0415

        return await self.session.get(CatalogResource, resource_id)

    async def tax_price_new_component(self, assembly: Assembly, component: Component) -> None:
        """Set ``total`` and ``metadata["tax"]`` on a component about to be stored; no-op with the switch off."""
        ctx = await self.tax_context(assembly)
        if ctx is None:
            return
        outcome = _outcome(ctx, component, await self._resource(component.catalog_resource_id))
        component.total = str(outcome.total)
        component.metadata_ = _meta_with_tax(component.metadata_, outcome)

    async def tax_price_update(self, assembly: Assembly, component: Component, fields: dict[str, Any]) -> None:
        """Fold a component edit into ``fields`` (``total``, ``metadata_``); no-op with the switch off."""
        ctx = await self.tax_context(assembly)
        if ctx is None:
            return
        merged = SimpleNamespace(
            **{
                name: fields.get(name, getattr(component, name, None))
                for name in (
                    *_TAX_FIELDS,
                    "factor",
                    "quantity",
                    "unit_cost",
                    "resource_type",
                    "catalog_resource_id",
                )
            },
            metadata_=fields.get("metadata_", component.metadata_),
        )
        outcome = _outcome(ctx, merged, await self._resource(merged.catalog_resource_id))
        fields["total"] = str(outcome.total)
        fields["metadata_"] = _meta_with_tax(merged.metadata_, outcome)

    async def _master_price(self, comp: Component, resource: Any | None) -> Decimal | None:
        if resource is not None:
            return ct.to_decimal(resource.base_price)
        if comp.cost_item_id is not None:
            from app.modules.costs.models import CostItem  # noqa: PLC0415

            item = await self.session.get(CostItem, comp.cost_item_id)
            return ct.to_decimal(getattr(item, "rate", None)) if item is not None else None
        return None

    async def tax_rule_context(self, assembly: Assembly, ctx: TaxContext) -> dict[str, Any]:
        """The payload the TAX-001..006 rules run over."""
        components = await self.component_repo.list_for_assembly(assembly.id)
        rows_out: list[dict[str, Any]] = []
        for comp in components:
            resource = await self._resource(comp.catalog_resource_id)
            outcome = _outcome(ctx, comp, resource)
            eff, rate = outcome.effective, outcome.rate
            explicit = next(
                (
                    o.tax_rate
                    for o in (comp, resource)
                    if o is not None and ct.to_decimal(getattr(o, "tax_rate", None)) is not None
                ),
                None,
            )
            classified = bool(
                eff.status
                or eff.code
                or explicit is not None
                or eff.includes_tax
                or getattr(comp, "input_tax_treatment", None)
            )
            rows_out.append(
                {
                    "id": str(comp.id),
                    "description": comp.description,
                    "tax": {
                        "classified": classified,
                        "status": eff.status,
                        "explicit_rate": explicit,
                        "code": eff.code,
                        "includes_tax": eff.includes_tax,
                        "reason": rate.reason if rate else ("no_rate" if classified else None),
                        "in_force": rate.in_force if rate else True,
                        "on_date": ctx.on_date,
                        "master_price": str(mp)
                        if (mp := await self._master_price(comp, resource)) is not None
                        else None,
                        "unit_cost": comp.unit_cost,
                    },
                }
            )
        return {
            "assembly": {"id": str(assembly.id), "code": assembly.code, "approved": is_approved(assembly)},
            "components": rows_out,
        }

    async def tax_findings(self, assembly: Assembly, ctx: TaxContext) -> list[TaxFinding]:
        """Run the component-tax rule set; every non-passing result, errors first."""
        from app.core.validation.cost_gate import run_rule_set  # noqa: PLC0415
        from app.modules.assemblies.validators import ASSEMBLIES_TAX_RULE_SET  # noqa: PLC0415

        report = await run_rule_set(
            ASSEMBLIES_TAX_RULE_SET,
            await self.tax_rule_context(assembly, ctx),
            target_type="assembly",
            target_id=str(assembly.id),
            project_id=str(assembly.project_id) if assembly.project_id else None,
        )
        order = {"error": 0, "warning": 1, "info": 2}
        failed = [r for r in report.results if not r.passed and not r.is_engine_error]
        failed.sort(key=lambda r: order.get(str(r.severity.value), 3))
        return [
            TaxFinding(
                rule_id=r.rule_id, severity=str(r.severity.value), message=r.message, component_id=r.element_ref or ""
            )
            for r in failed
        ]

    async def recalculate_tax(self, assembly_id: uuid.UUID, as_of: str | None = None) -> TaxRecalcResponse:
        """Re-price one assembly: take master prices, apply component tax, refresh the totals.

        Raises 409 for an approved assembly, which keeps its historical amounts.
        """
        assembly = await self.get_assembly(assembly_id)  # type: ignore[attr-defined]
        if is_approved(assembly):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Assembly is approved; its prices are frozen",
            )
        ctx = await self.tax_context(assembly, as_of)
        if ctx is None:
            return TaxRecalcResponse(assembly_id=assembly_id, updated=False, skipped_reason="component_tax_disabled")
        for comp in await self.component_repo.list_for_assembly(assembly_id):
            resource = await self._resource(comp.catalog_resource_id)
            master = await self._master_price(comp, resource)
            if master is not None and ct.to_decimal(comp.unit_cost) != master:
                comp.unit_cost = str(master)
            outcome = _outcome(ctx, comp, resource)
            comp.total = str(outcome.total)
            comp.metadata_ = _meta_with_tax(comp.metadata_, outcome)
        await self.session.flush()
        await self._recalculate_total(assembly_id)  # type: ignore[attr-defined]
        stamped = await self.assembly_repo.get_by_id(assembly_id)
        if stamped is not None and isinstance(stamped.metadata_, dict) and "tax_totals" in stamped.metadata_:
            meta = dict(stamped.metadata_)
            meta["tax_totals"] = {**meta["tax_totals"], "as_of": ctx.on_date}
            await self.assembly_repo.update_fields(assembly_id, metadata_=meta)
        refreshed = await self.get_assembly(assembly_id)  # type: ignore[attr-defined]
        return TaxRecalcResponse(
            assembly_id=assembly_id,
            updated=True,
            tax_totals=(refreshed.metadata_ or {}).get("tax_totals", {}),
            total_rate=float(ct.to_decimal(refreshed.total_rate) or 0),
            findings=await self.tax_findings(refreshed, ctx),
        )

    async def refresh_tax_totals(self, assembly_id: uuid.UUID) -> None:
        """Rewrite ``metadata["tax_totals"]`` from the stored component breakdowns; no-op with the switch off."""
        assembly = await self.assembly_repo.get_by_id(assembly_id)
        if assembly is None or assembly.project_id is None:
            return
        from app.modules.projects.models import Project  # noqa: PLC0415

        project = await self.session.get(Project, assembly.project_id)
        if project is None or not getattr(project, "component_tax_enabled", False):
            return
        lines: list[dict[str, Any]] = []
        for comp in await self.component_repo.list_for_assembly(assembly_id):
            stored = (comp.metadata_ or {}).get("tax") if isinstance(comp.metadata_, dict) else None
            total = str(ct.to_decimal(comp.total) or 0)
            lines.append(
                stored
                if isinstance(stored, dict)
                else {
                    "net": total,
                    "cost": total,
                    "gross_outlay": total,
                    "tax": "0",
                    "tax_in_cost": "0",
                    "tax_recoverable": "0",
                }
            )
        totals = ct.sum_lines(lines, ct.to_decimal(assembly.bid_factor) or Decimal("1"))
        meta = dict(assembly.metadata_) if isinstance(assembly.metadata_, dict) else {}
        prior = meta.get("tax_totals") if isinstance(meta.get("tax_totals"), dict) else {}
        meta["tax_totals"] = {
            **totals,
            "currency": assembly.currency or project.currency or "",
            "as_of": prior.get("as_of") or datetime.now(tz=UTC).date().isoformat(),
        }
        await self.assembly_repo.update_fields(assembly_id, metadata_=meta)

    async def recalculate_project_tax(
        self, project_id: uuid.UUID, as_of: str | None = None
    ) -> ProjectTaxRecalcResponse:
        """Re-price every assembly of a project; approved ones are listed and left alone."""
        found = await self.session.execute(select(Assembly.id).where(Assembly.project_id == project_id))
        result = ProjectTaxRecalcResponse()
        for assembly_id in found.scalars().all():
            assembly = await self.assembly_repo.get_by_id(assembly_id)
            if assembly is None:
                continue
            if is_approved(assembly):
                result.skipped_approved.append(assembly_id)
                continue
            done = await self.recalculate_tax(assembly_id, as_of)
            (result.updated if done.updated else result.skipped_other).append(assembly_id)
        return result
