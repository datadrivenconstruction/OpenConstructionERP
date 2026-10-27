# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks service: capture, normalise, compare, export.

Every query filters on the caller's tenant. A tenant of ``None`` reads nothing.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cost_benchmarks import bench_math as bm
from app.modules.cost_benchmarks import repository
from app.modules.cost_benchmarks.models import BenchmarkElement, BenchmarkRecord

logger = logging.getLogger(__name__)

_REFERENCE_PATH = Path(__file__).resolve().parents[2] / "core" / "country_data" / "cost_benchmark_reference.json"
_STANDARD_KEYS = {
    "din276": "din276",
    "nrm": "nrm1",
    "nrm1": "nrm1",
    "masterformat": "masterformat",
    "uniformat": "uniformat",
}


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


@lru_cache(maxsize=1)
def load_reference() -> dict[str, Any]:
    """The open reference bands (per m2 GFA, in their stated currency and base date)."""
    return json.loads(_REFERENCE_PATH.read_text(encoding="utf-8"))


class CostBenchmarksService:
    """Benchmark records, comparisons and the anonymised export."""

    def __init__(self, session: AsyncSession, tenant_id: str | None) -> None:
        self.session = session
        self.tenant = tenant_id or ""

    def _require_tenant(self) -> str:
        if not self.tenant:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Benchmarks need a signed-in company.")
        return self.tenant

    # -- records -------------------------------------------------------------

    async def list_records(self, kind: str | None = None, **filters: Any) -> list[BenchmarkRecord]:
        rows = await repository.records_for_tenant(self.session, self.tenant, kind)
        return [r for r in rows if self._matches(r, **filters)]

    @staticmethod
    def _matches(
        r: BenchmarkRecord,
        project_type: str | None = None,
        countries: list[str] | None = None,
        region: str | None = None,
        gfa_min: Decimal | None = None,
        gfa_max: Decimal | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        standard: str | None = None,
    ) -> bool:
        if project_type and r.project_type != project_type:
            return False
        if countries and r.country.upper() not in {c.upper() for c in countries}:
            return False
        if region and r.region != region:
            return False
        if gfa_min is not None and (r.gfa_m2 is None or r.gfa_m2 < gfa_min):
            return False
        if gfa_max is not None and (r.gfa_m2 is None or r.gfa_m2 > gfa_max):
            return False
        if year_from is not None and r.cost_date.year < year_from:
            return False
        if year_to is not None and r.cost_date.year > year_to:
            return False
        return not (standard and r.standard != standard)

    async def get(self, record_id: uuid.UUID) -> BenchmarkRecord:
        row = await self.session.get(BenchmarkRecord, record_id)
        if row is None or row.tenant_id != self.tenant or not self.tenant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benchmark record not found")
        return row

    async def create(self, data: dict[str, Any], user_id: str | None = None) -> BenchmarkRecord:
        tenant = self._require_tenant()
        elements = data.pop("elements", []) or []
        record = BenchmarkRecord(tenant_id=tenant, created_by=_uuid(user_id), **data)
        record.elements = [
            BenchmarkElement(code=e["code"], label=e.get("label", ""), amount=Decimal(str(e["amount"])))
            for e in elements
        ]
        if not data.get("total_cost") and elements:
            record.total_cost = sum((el.amount for el in record.elements), Decimal("0"))
        self.session.add(record)
        await self.session.flush()
        return record

    async def delete(self, record_id: uuid.UUID) -> None:
        row = await self.get(record_id)
        await self.session.delete(row)
        await self.session.flush()

    async def capture_project(
        self, project_id: uuid.UUID, *, kind: str = "completed", user_id: str | None = None
    ) -> BenchmarkRecord:
        """Turn a project's BOQ into a record: leaf position totals rolled up by element group."""
        tenant = self._require_tenant()
        from app.modules.boq.models import BOQ, Position
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        standard = _STANDARD_KEYS.get((project.classification_standard or "din276").lower(), "din276")
        boq_ids = [b for (b,) in (await self.session.execute(select(BOQ.id).where(BOQ.project_id == project_id))).all()]
        groups: dict[str, Decimal] = {}
        if boq_ids:
            positions = (
                (await self.session.execute(select(Position).where(Position.boq_id.in_(boq_ids)))).scalars().all()
            )
            parents = {p.parent_id for p in positions if p.parent_id is not None}
            key = "nrm" if standard == "nrm1" else standard
            for p in positions:
                if p.id in parents:
                    continue
                cls = p.classification if isinstance(p.classification, dict) else {}
                code = bm.element_group(standard, str(cls.get(standard) or cls.get(key) or ""))
                total = _dec(p.total) or Decimal("0")
                if total:
                    groups[code or "unclassified"] = groups.get(code or "unclassified", Decimal("0")) + total
        end = _parse_date(project.actual_end_date) or date.today()
        existing = (
            (
                await self.session.execute(
                    select(BenchmarkRecord).where(
                        BenchmarkRecord.tenant_id == tenant,
                        BenchmarkRecord.project_id == project_id,
                        BenchmarkRecord.kind == kind,
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            await self.session.delete(existing)
            await self.session.flush()
        meta = project.metadata_ if isinstance(project.metadata_, dict) else {}
        return await self.create(
            {
                "kind": kind,
                "project_id": project_id,
                "name": project.name,
                "project_type": project.project_type or "",
                "country": (project.country_code or "")[:2].upper(),
                "region": project.region or "",
                "currency": (project.currency or "")[:3].upper(),
                "cost_date": end,
                "standard": standard,
                "gfa_m2": _dec(project.gross_floor_area),
                "functional_unit": str(meta.get("functional_unit") or ""),
                "functional_units": _dec(meta.get("functional_units")),
                "total_cost": sum(groups.values(), Decimal("0")),
                "source": "project",
                "elements": [{"code": c, "amount": a} for c, a in sorted(groups.items())],
            },
            user_id,
        )

    # -- basis ---------------------------------------------------------------

    async def basis(
        self,
        *,
        base_date: date,
        base_region: str | None,
        reporting_currency: str,
        index_series_id: uuid.UUID | None = None,
        fx_date: date | None = None,
        stale_months: int = bm.DEFAULT_STALE_MONTHS,
    ) -> tuple[bm.Basis, dict[str, Any]]:
        from app.modules.fx.repository import latest_rate_set, quotes_as_map
        from app.modules.price_index.models import CostIndexPoint, CostIndexSeries, LocationFactor

        series = None
        if index_series_id is not None:
            series = await self.session.get(CostIndexSeries, index_series_id)
        if series is None:
            series = (
                (await self.session.execute(select(CostIndexSeries).order_by(CostIndexSeries.name))).scalars().first()
            )
        points: dict[str, Decimal] = {}
        if series is not None:
            rows = await self.session.execute(
                select(CostIndexPoint.period, CostIndexPoint.factor).where(CostIndexPoint.series_id == series.id)
            )
            points = {p: Decimal(str(v)) for p, v in rows.all() if p}
        regions = {
            r.region_code: Decimal(str(r.factor))
            for r in (await self.session.execute(select(LocationFactor))).scalars().all()
            if r.region_code
        }
        rate_set = await latest_rate_set(self.session, base_currency="EUR", on_date=fx_date or base_date)
        quotes = quotes_as_map(rate_set) if rate_set is not None else {}
        info = {
            "base_date": base_date.isoformat(),
            "base_region": base_region or "",
            "reporting_currency": reporting_currency.upper(),
            "index_series": series.name if series is not None else None,
            "index_series_id": str(series.id) if series is not None else None,
            "index_latest_period": max(points) if points else None,
            "fx_rate_date": rate_set.rate_date.isoformat() if rate_set is not None else None,
            "location_factors": len(regions),
        }
        return (
            bm.Basis(
                base_date=base_date,
                base_region=base_region,
                reporting_currency=reporting_currency.upper(),
                index_points=points,
                region_factors=regions,
                fx_quotes=quotes,
                stale_months=stale_months,
            ),
            info,
        )

    # -- comparison ----------------------------------------------------------

    @staticmethod
    def _normalised(r: BenchmarkRecord, basis: bm.Basis, measure: str) -> dict[str, Any]:
        f = bm.factors_for(basis, cost_date=r.cost_date, region=r.region or None, currency=r.currency)
        qty = r.gfa_m2 if measure == "gfa" else r.functional_units
        total = bm.normalise(r.total_cost, f)
        elements = {e.code: bm.normalise(e.amount, f) for e in r.elements}
        return {
            "record": r,
            "factors": f,
            "quantity": qty,
            "total": total,
            "total_per_unit": bm.per_unit(total, qty),
            "elements": elements,
            "elements_per_unit": {c: bm.per_unit(a, qty) for c, a in elements.items()},
        }

    def _reference(self, project_type: str, standard: str, basis: bm.Basis) -> dict[str, Any] | None:
        ref = load_reference()
        for row in ref.get("bands", []):
            if row.get("project_type") == project_type and row.get("standard") == standard:
                fx = bm.fx_factor(basis.fx_quotes, basis.fx_base, ref.get("currency", "EUR"), basis.reporting_currency)
                mult = fx if fx is not None else Decimal("1")

                def conv(b: dict[str, Any]) -> bm.Band:
                    return bm.Band(
                        int(b.get("n", 0)),
                        Decimal(str(b["p10"])) * mult,
                        Decimal(str(b["p50"])) * mult,
                        Decimal(str(b["p90"])) * mult,
                    )

                return {
                    "total": conv(row["total"]),
                    "elements": {c: conv(b) for c, b in row.get("elements", {}).items()},
                    "source": ref.get("source", ""),
                    "base_date": ref.get("base_date"),
                }
        return None

    async def compare(
        self,
        *,
        estimate_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        filters: dict[str, Any],
        base_date: date,
        base_region: str | None,
        reporting_currency: str,
        index_series_id: uuid.UUID | None = None,
        fx_date: date | None = None,
        measure: str = "gfa",
        min_projects: int = bm.DEFAULT_MIN_PROJECTS,
        stale_months: int = bm.DEFAULT_STALE_MONTHS,
    ) -> dict[str, Any]:
        """Benchmark an estimate (record or live project) against its cohort."""
        if estimate_id is not None:
            estimate = await self.get(estimate_id)
        elif project_id is not None:
            estimate = await self.capture_project(project_id, kind="estimate")
        else:
            raise HTTPException(status_code=422, detail="Name an estimate record or a project.")
        filters = {k: v for k, v in filters.items() if v not in (None, "", [])}
        filters.setdefault("standard", estimate.standard)
        cohort = [r for r in await self.list_records(kind="completed", **filters) if r.id != estimate.id]
        basis, info = await self.basis(
            base_date=base_date,
            base_region=base_region,
            reporting_currency=reporting_currency,
            index_series_id=index_series_id,
            fx_date=fx_date,
            stale_months=stale_months,
        )
        est = self._normalised(estimate, basis, measure)
        norm = [self._normalised(r, basis, measure) for r in cohort]
        usable = [n for n in norm if n["total_per_unit"] is not None]
        reference = None
        source = "own"
        if len(usable) < min_projects:
            reference = self._reference(estimate.project_type, estimate.standard, basis)
            if reference is not None and not usable:
                source = "reference"
        total_band = bm.band(n["total_per_unit"] for n in usable)
        codes = sorted({*est["elements"], *(c for n in usable for c in n["elements"])})
        elements = []
        for code in codes:
            vals = [v for n in usable if (v := n["elements_per_unit"].get(code)) is not None]
            b = bm.band(vals)
            el_source = "own"
            if b.count < min_projects and reference is not None and code in reference["elements"]:
                b, el_source = reference["elements"][code], "reference"
            value = est["elements_per_unit"].get(code)
            label = next((e.label for e in estimate.elements if e.code == code and e.label), "")
            elements.append(
                {
                    "code": code,
                    "label": label,
                    "estimate_per_unit": None if value is None else str(value),
                    "estimate_amount": str(est["elements"].get(code, Decimal("0"))),
                    "band": b.as_dict(),
                    "band_source": el_source,
                    "position": bm.position(value, b),
                }
            )
        if total_band.count < min_projects and reference is not None:
            total_band = reference["total"]
        stale = any(n["factors"].stale for n in norm) or est["factors"].stale
        return {
            "estimate": {
                "id": str(estimate.id),
                "name": estimate.name,
                "project_type": estimate.project_type,
                "country": estimate.country,
                "gfa_m2": None if estimate.gfa_m2 is None else str(estimate.gfa_m2),
                "functional_unit": estimate.functional_unit,
                "functional_units": None if estimate.functional_units is None else str(estimate.functional_units),
                "total": str(est["total"]),
                "total_per_unit": None if est["total_per_unit"] is None else str(est["total_per_unit"]),
                "total_position": bm.position(est["total_per_unit"], total_band),
            },
            "measure": measure,
            "basis": {**info, "stale": stale},
            "cohort": {
                "count": len(usable),
                "min_projects": min_projects,
                "low_confidence": len(usable) < min_projects,
                "source": source,
                "reference_source": reference["source"] if reference else None,
                "missing_quantity": [n["record"].name for n in norm if n["total_per_unit"] is None],
                "projects": [
                    {
                        "id": str(n["record"].id),
                        "name": n["record"].name,
                        "country": n["record"].country,
                        "year": n["record"].cost_date.year,
                        "gfa_m2": None if n["record"].gfa_m2 is None else str(n["record"].gfa_m2),
                        "total_per_unit": str(n["total_per_unit"]),
                        "factor": str(bm.quantize_factor(n["factors"].combined)),
                    }
                    for n in usable
                ],
            },
            "total_band": total_band.as_dict(),
            "elements": elements,
        }

    # -- export --------------------------------------------------------------

    async def anonymised_export(self, *, basis: bm.Basis, fmt: str = "json") -> tuple[str, str]:
        """Records without names, ids, regions or exact areas, per m2 on one basis."""
        rows = []
        for r in await self.list_records(kind="completed"):
            n = self._normalised(r, basis, "gfa")
            if n["total_per_unit"] is None:
                continue
            rows.append(
                {
                    "project_type": r.project_type,
                    "country": r.country,
                    "year": r.cost_date.year,
                    "standard": r.standard,
                    "gfa_class": bm.gfa_bucket(r.gfa_m2),
                    "total_per_m2": str(n["total_per_unit"]),
                    "elements_per_m2": {c: str(v) for c, v in n["elements_per_unit"].items() if v is not None},
                }
            )
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\r\n")
            w.writerow(
                ["project_type", "country", "year", "standard", "gfa_class", "total_per_m2", "element", "per_m2"]
            )
            for row in rows:
                for code, value in sorted(row["elements_per_m2"].items()):
                    w.writerow(
                        [
                            row["project_type"],
                            row["country"],
                            row["year"],
                            row["standard"],
                            row["gfa_class"],
                            row["total_per_m2"],
                            code,
                            value,
                        ]
                    )
            return buf.getvalue(), "text/csv"
        payload = {
            "schema": "openconstructionerp.cost_benchmarks.anonymised/1",
            "basis": {"base_date": basis.base_date.isoformat(), "reporting_currency": basis.reporting_currency},
            "records": rows,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2), "application/json"


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def validation_snapshot(comparison: dict[str, Any]) -> dict[str, Any]:
    """The comparison as the rule set reads it."""
    return comparison
