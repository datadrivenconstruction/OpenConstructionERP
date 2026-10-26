# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Life-cycle​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ stages, carbon budget, checks and company E1 reporting.

Extends ``CarbonService`` with A4 transport, A5 site energy and waste, EPD file
import (ILCD+EPD XML and CSV) attached to supplier catalogue products, project
hotspots, budget, material swap, bid carbon, the carbon checks behind the
validation rules, and company-level ESRS E1 aggregation with an audit trail.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.carbon import csrd, lifecycle
from app.modules.carbon.models import (
    CarbonCompanyActivity,
    CarbonCompanyReport,
    CarbonInventory,
    CarbonTarget,
    EmbodiedCarbonEntry,
    EPDRecord,
    MaterialCarbonFactor,
    Scope1Entry,
    Scope2Entry,
    Scope3Entry,
)
from app.modules.carbon.service import (
    CarbonService,
    UnitMismatchError,
    compute_embodied_entry_carbon,
    lookup_grid_factor_default,
)

BUDGET_TARGET_TYPE = "budget"


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class CarbonLifecycleService:
    """Life-cycle and company reporting operations on top of ``CarbonService``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.base = CarbonService(session)

    # ── EPD import ───────────────────────────────────────────────────────

    async def import_epd_file(
        self,
        payload: bytes,
        filename: str,
        *,
        material_class: str = "other",
        supplier_catalog_item_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Import ILCD+EPD XML (one dataset) or a CSV of EPDs; upsert by epd_id."""
        name = (filename or "").lower()
        head = payload.lstrip(b"\xef\xbb\xbf").lstrip()[:1]
        errors: list[str] = []
        if name.endswith(".xml") or head == b"<":
            try:
                rows = [lifecycle.parse_ilcd_epd_xml(payload)]
            except ValueError as exc:
                raise _bad(f"epd_parse_failed: {exc}") from None
            fmt = "ilcd_xml"
        elif name.endswith(".csv"):
            try:
                text = payload.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise _bad("epd_parse_failed: CSV must be UTF-8") from None
            rows, errors = lifecycle.parse_epd_csv(text)
            fmt = "csv"
        else:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="expected .xml or .csv")

        created: list[EPDRecord] = []
        for row in rows:
            existing = (
                await self.session.execute(select(EPDRecord).where(EPDRecord.epd_id == row["epd_id"]))
            ).scalar_one_or_none()
            rec = existing or EPDRecord(epd_id=row["epd_id"], source="custom")
            rec.product_name = row.get("product_name") or row["epd_id"]
            rec.material_class = row.get("material_class") or material_class
            rec.manufacturer = row.get("manufacturer")
            rec.region = row.get("region") or rec.region or ""
            rec.declared_unit = row.get("declared_unit") or "kg"
            for key in ("gwp_a1a3", "gwp_a4", "gwp_a5", "gwp_b_total", "gwp_c_total", "gwp_d_credits"):
                if key in row:
                    setattr(rec, key, row[key] if row[key] is not None or key != "gwp_a1a3" else Decimal("0"))
            vu = row.get("validity_until")
            rec.validity_until = date.fromisoformat(vu) if isinstance(vu, str) and vu else None
            rec.epd_format = fmt
            if supplier_catalog_item_id is not None:
                rec.supplier_catalog_item_id = supplier_catalog_item_id
            meta = dict(rec.metadata_ or {})
            if row.get("reference_year"):
                meta["reference_year"] = row["reference_year"]
            rec.metadata_ = meta
            if existing is None:
                self.session.add(rec)
            created.append(rec)
        await self.session.flush()
        event_bus.publish_detached(
            "carbon.epd.imported",
            {"count": len(created), "format": fmt, "epd_ids": [r.epd_id for r in created]},
            source_module="carbon",
        )
        return {"format": fmt, "imported": [str(r.id) for r in created], "errors": errors}

    async def epds_for_catalog_item(self, item_id: uuid.UUID) -> list[EPDRecord]:
        stmt = select(EPDRecord).where(EPDRecord.supplier_catalog_item_id == item_id)
        return list((await self.session.execute(stmt)).scalars())

    # ── Stage lines ──────────────────────────────────────────────────────

    async def _add_entry(
        self,
        inventory_id: uuid.UUID,
        *,
        stage: str,
        description: str,
        quantity: Decimal,
        unit: str,
        factor_value: Decimal,
        carbon_kg: Decimal,
        data_quality: str,
        meta: dict[str, Any],
    ) -> EmbodiedCarbonEntry:
        if data_quality not in lifecycle.DATA_QUALITY:
            raise _bad("data_quality must be measured, calculated or estimated")
        await self.base.get_inventory(inventory_id)
        entry = EmbodiedCarbonEntry(
            inventory_id=inventory_id,
            description=description,
            quantity=quantity,
            unit=unit,
            factor_value_used=factor_value,
            carbon_kg=carbon_kg,
            stage=stage,
            source="manual",
            data_quality=data_quality,
        )
        entry.metadata_ = meta
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def add_transport_a4(
        self,
        inventory_id: uuid.UUID,
        *,
        mass_kg: Decimal,
        distance_km: Decimal,
        mode: str,
        description: str = "",
        factor_per_tkm: Decimal | None = None,
        supplier: str | None = None,
        data_quality: str = "calculated",
    ) -> EmbodiedCarbonEntry:
        try:
            kg = lifecycle.compute_a4_transport(mass_kg, distance_km, mode, factor_per_tkm)
        except ValueError as exc:
            raise _bad(str(exc)) from None
        factor = factor_per_tkm if factor_per_tkm is not None else lifecycle.TRANSPORT_MODE_FACTORS[mode]
        tkm = Decimal(str(mass_kg)) / Decimal("1000") * Decimal(str(distance_km))
        return await self._add_entry(
            inventory_id,
            stage="a4",
            description=description or f"Transport {mode} {distance_km} km",
            quantity=tkm,
            unit="tkm",
            factor_value=Decimal(str(factor)),
            carbon_kg=kg,
            data_quality=data_quality,
            meta={
                "kind": "transport",
                "mode": mode,
                "mass_kg": str(mass_kg),
                "distance_km": str(distance_km),
                "supplier": supplier,
                "factor_source": "user" if factor_per_tkm is not None else lifecycle.TRANSPORT_FACTOR_SOURCE,
            },
        )

    async def add_site_energy_a5(
        self,
        inventory_id: uuid.UUID,
        *,
        fuel_litres: dict[str, Decimal] | None = None,
        electricity_kwh: Decimal = Decimal("0"),
        grid_factor: Decimal | None = None,
        description: str = "",
        data_quality: str = "measured",
    ) -> EmbodiedCarbonEntry:
        inv = await self.base.get_inventory(inventory_id)
        grid_source = "user"
        if grid_factor is None:
            country = await self._project_country(inv.project_id)
            hit = lookup_grid_factor_default(country, date.today().year) if country else None
            grid_factor = Decimal(str(hit["factor_kg_co2e_per_kwh"])) if hit else Decimal("0.48")
            grid_source = hit["source"] if hit else "World average default"
        try:
            parts = lifecycle.compute_a5_site_energy(fuel_litres, electricity_kwh, grid_factor)
        except ValueError as exc:
            raise _bad(str(exc)) from None
        return await self._add_entry(
            inventory_id,
            stage="a5",
            description=description or "Site energy and fuel",
            quantity=Decimal(str(electricity_kwh)),
            unit="kWh",
            factor_value=Decimal(str(grid_factor)),
            carbon_kg=parts["total_kg"],
            data_quality=data_quality,
            meta={
                "kind": "site_energy",
                "fuel_litres": {k: str(v) for k, v in (fuel_litres or {}).items()},
                "fuel_kg": str(parts["fuel_kg"]),
                "electricity_kg": str(parts["electricity_kg"]),
                "grid_factor_source": grid_source,
                "fuel_factor_source": lifecycle.FUEL_FACTOR_SOURCE,
            },
        )

    async def import_equipment_fuel_a5(
        self, inventory_id: uuid.UUID, *, period_start: date, period_end: date
    ) -> EmbodiedCarbonEntry | None:
        """Sum fuel logs of equipment rented to the project in the period into one A5 line."""
        from app.modules.equipment.models import EquipmentRental, FuelLog

        inv = await self.base.get_inventory(inventory_id)
        stmt = (
            select(FuelLog.fuel_type, FuelLog.fuel_liters, FuelLog.id)
            .join(EquipmentRental, EquipmentRental.equipment_id == FuelLog.equipment_id)
            .where(EquipmentRental.project_id == inv.project_id)
            .where(FuelLog.logged_at >= period_start.isoformat())
            .where(FuelLog.logged_at <= f"{period_end.isoformat()}T23:59:59")
        )
        litres: dict[str, Decimal] = {}
        refs: set[str] = set()
        for fuel_type, qty, log_id in (await self.session.execute(stmt)).all():
            if str(log_id) in refs:
                continue
            refs.add(str(log_id))
            key = (fuel_type or "diesel").lower()
            key = key if key in lifecycle.FUEL_FACTORS else "diesel"
            litres[key] = litres.get(key, Decimal("0")) + Decimal(str(qty or 0))
        if not litres:
            return None
        entry = await self.add_site_energy_a5(
            inventory_id,
            fuel_litres=litres,
            grid_factor=Decimal("0"),
            description=f"Equipment fuel {period_start} to {period_end}",
            data_quality="measured",
        )
        entry.metadata_ = {**entry.metadata_, "source": "equipment_fuel_log", "fuel_log_ids": sorted(refs)}
        await self.session.flush()
        return entry

    async def add_waste_a5(
        self,
        inventory_id: uuid.UUID,
        *,
        material_carbon_kg: Decimal,
        material_mass_kg: Decimal,
        waste_rate_pct: Decimal,
        treatment: str,
        description: str = "",
        data_quality: str = "estimated",
    ) -> EmbodiedCarbonEntry:
        try:
            kg = lifecycle.compute_a5_waste(material_carbon_kg, material_mass_kg, waste_rate_pct, treatment)
        except ValueError as exc:
            raise _bad(str(exc)) from None
        mass = Decimal(str(material_mass_kg)) * Decimal(str(waste_rate_pct)) / Decimal("100")
        return await self._add_entry(
            inventory_id,
            stage="a5",
            description=description or f"Construction waste ({treatment})",
            quantity=mass,
            unit="kg",
            factor_value=lifecycle.WASTE_TREATMENT_FACTORS[treatment],
            carbon_kg=kg,
            data_quality=data_quality,
            meta={"kind": "waste", "treatment": treatment, "waste_rate_pct": str(waste_rate_pct)},
        )

    # ── Analysis ─────────────────────────────────────────────────────────

    async def _project_country(self, project_id: uuid.UUID) -> str:
        from app.modules.projects.models import Project

        proj = await self.session.get(Project, project_id)
        return (getattr(proj, "country_code", None) or "").upper()

    async def hotspots(self, inventory_id: uuid.UUID, system: str = "din276") -> list[dict[str, Any]]:
        from app.modules.boq.models import Position

        entries = await self.base.embodied_repo.list_for_inventory(inventory_id)
        ids = []
        for e in entries:
            pid = (e.metadata_ or {}).get("boq_position_id")
            try:
                ids.append(uuid.UUID(str(pid)))
            except (TypeError, ValueError):
                continue
        classification: dict[str, dict[str, Any]] = {}
        if ids:
            rows = await self.session.execute(select(Position.id, Position.classification).where(Position.id.in_(ids)))
            classification = {str(pid): (cls or {}) for pid, cls in rows.all()}
        try:
            return lifecycle.hotspots_by_group(entries, classification, system)
        except ValueError as exc:
            raise _bad(str(exc)) from None

    async def _latest_inventory(self, project_id: uuid.UUID) -> CarbonInventory | None:
        stmt = (
            select(CarbonInventory)
            .where(CarbonInventory.project_id == project_id)
            .order_by(CarbonInventory.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def budget(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Project carbon budget (a target with ``target_type='budget'``) vs the latest inventory."""
        stmt = select(CarbonTarget).where(
            CarbonTarget.project_id == project_id, CarbonTarget.target_type == BUDGET_TARGET_TYPE
        )
        target = (await self.session.execute(stmt.order_by(CarbonTarget.created_at.desc()).limit(1))).scalar()
        inv = await self._latest_inventory(project_id)
        actual = Decimal("0")
        if inv is not None:
            totals = await self.base.compute_inventory_totals_fresh(inv.id)
            actual = sum(
                (Decimal(str(totals.get(k, 0))) for k in ("embodied_a1a5", "embodied_b", "embodied_c")), Decimal("0")
            )
        result = lifecycle.budget_status(actual, target.target_value if target else 0)
        result.update(
            {
                "project_id": str(project_id),
                "target_id": str(target.id) if target else None,
                "inventory_id": str(inv.id) if inv else None,
            }
        )
        if result["over_budget"]:
            event_bus.publish_detached("carbon.budget.exceeded", result, source_module="carbon")
        return result

    async def swap(
        self,
        entry_id: uuid.UUID,
        *,
        alternative_factor_id: uuid.UUID,
        current_unit_rate: Decimal,
        alternative_unit_rate: Decimal,
    ) -> dict[str, Any]:
        entry = await self.base.get_embodied_entry(entry_id)
        alt = await self.base.get_factor(alternative_factor_id)
        alt_value = await self._factor_value(alt)
        current = Decimal(str(entry.factor_value_used or 0))
        qty = Decimal(str(entry.carbon_kg or 0)) / current if current else Decimal(str(entry.quantity or 0))
        out = lifecycle.compare_swap(qty, current, current_unit_rate, alt_value, alternative_unit_rate)
        out.update({"entry_id": str(entry_id), "alternative_factor_id": str(alternative_factor_id)})
        return out

    async def _factor_value(self, factor: MaterialCarbonFactor) -> Decimal:
        if factor.manual_override_factor is not None:
            return Decimal(str(factor.manual_override_factor))
        if factor.epd_id is not None:
            epd = await self.session.get(EPDRecord, factor.epd_id)
            if epd is not None:
                return Decimal(str(epd.gwp_a1a3 or 0))
        return Decimal("0")

    async def bid_carbon(self, lines: list[dict[str, Any]]) -> dict[str, Any]:
        """Carbon per bid line via the factor linked to its cost item (tender comparison column)."""
        cost_ids = {str(line.get("cost_item_id")) for line in lines if line.get("cost_item_id")}
        factors: dict[str, MaterialCarbonFactor] = {}
        if cost_ids:
            uuids = [uuid.UUID(c) for c in cost_ids]
            rows = await self.session.execute(
                select(MaterialCarbonFactor).where(MaterialCarbonFactor.cost_item_id.in_(uuids))
            )
            for f in rows.scalars():
                factors.setdefault(str(f.cost_item_id), f)
        out: list[dict[str, Any]] = []
        total = Decimal("0")
        for line in lines:
            f = factors.get(str(line.get("cost_item_id")))
            row: dict[str, Any] = {"ref": line.get("ref"), "carbon_kg": None, "status": "no_factor"}
            if f is not None:
                try:
                    kg = compute_embodied_entry_carbon(
                        line.get("quantity", 0),
                        line.get("unit") or f.unit_for_factor,
                        await self._factor_value(f),
                        f.unit_for_factor,
                    )
                    row.update({"carbon_kg": str(kg), "status": "ok"})
                    total += kg
                except (UnitMismatchError, ValueError):
                    row["status"] = "unit_mismatch"
            out.append(row)
        return {"lines": out, "total_kg": str(total)}

    async def checks(self, project_id: uuid.UUID, today: date | None = None) -> dict[str, Any]:
        """Facts the carbon validation rule judges: missing factors, outdated sets, budget, EPDs, units."""
        inv = await self._latest_inventory(project_id)
        issues: dict[str, list[str]] = {
            "no_factor": [],
            "outdated_factor_set": [],
            "expired_epd": [],
            "unit_mismatch": [],
        }
        if inv is not None:
            for e in await self.base.embodied_repo.list_for_inventory(inv.id):
                if e.stage == "a1a3" and e.factor_id is None and not Decimal(str(e.factor_value_used or 0)):
                    issues["no_factor"].append(str(e.id))
                    continue
                if e.factor_id is None:
                    continue
                f = await self.session.get(MaterialCarbonFactor, e.factor_id)
                if f is None:
                    continue
                if lifecycle.is_factor_set_outdated(f.factor_set_year, today):
                    issues["outdated_factor_set"].append(str(e.id))
                try:
                    compute_embodied_entry_carbon(e.quantity, e.unit, Decimal("1"), f.unit_for_factor)
                except UnitMismatchError:
                    issues["unit_mismatch"].append(str(e.id))
                except ValueError:
                    pass
                if f.epd_id is not None:
                    epd = await self.session.get(EPDRecord, f.epd_id)
                    if epd is not None and lifecycle.is_epd_expired(epd.validity_until, today):
                        issues["expired_epd"].append(str(e.id))
        budget = await self.budget(project_id)
        return {"project_id": str(project_id), "inventory_id": str(inv.id) if inv else None, **issues, "budget": budget}

    # ── Company reporting ────────────────────────────────────────────────

    async def create_activity(self, data: dict[str, Any], user_id: str | None) -> CarbonCompanyActivity:
        if data.get("data_quality", "calculated") not in lifecycle.DATA_QUALITY:
            raise _bad("data_quality must be measured, calculated or estimated")
        if int(data.get("scope", 0)) not in (1, 2, 3):
            raise _bad("scope must be 1, 2 or 3")
        amount = Decimal(str(data.get("activity_amount") or 0))
        factor = Decimal(str(data.get("emission_factor") or 0))
        if amount < 0 or factor < 0:
            raise _bad("activity and factor must not be negative")
        row = CarbonCompanyActivity(**{**data, "co2e_kg": amount * factor, "created_by": user_id})
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_activities(self, year: int, user_id: str | None, admin: bool) -> list[CarbonCompanyActivity]:
        stmt = select(CarbonCompanyActivity).where(CarbonCompanyActivity.reporting_year == year)
        if not admin:
            stmt = stmt.where(CarbonCompanyActivity.created_by == user_id)
        return list((await self.session.execute(stmt.order_by(CarbonCompanyActivity.created_at))).scalars())

    async def delete_activity(self, activity_id: uuid.UUID, user_id: str | None, admin: bool) -> None:
        row = await self.session.get(CarbonCompanyActivity, activity_id)
        if row is None or (not admin and row.created_by != user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
        await self.session.delete(row)
        await self.session.flush()

    async def import_fleet_fuel(self, year: int, user_id: str | None) -> list[CarbonCompanyActivity]:
        """Company fleet fuel (all fuel logs of the year) as measured scope 1 activities."""
        from app.modules.equipment.models import FuelLog

        stmt = select(FuelLog.fuel_type, FuelLog.fuel_liters).where(FuelLog.logged_at.like(f"{year}-%"))
        litres: dict[str, Decimal] = {}
        for fuel_type, qty in (await self.session.execute(stmt)).all():
            key = (fuel_type or "diesel").lower()
            key = key if key in lifecycle.FUEL_FACTORS else "diesel"
            litres[key] = litres.get(key, Decimal("0")) + Decimal(str(qty or 0))
        out = []
        for fuel, qty in litres.items():
            out.append(
                await self.create_activity(
                    {
                        "reporting_year": year,
                        "scope": 1,
                        "category": "fleet_fuel",
                        "description": f"Fleet {fuel}",
                        "activity_amount": qty,
                        "activity_unit": "L",
                        "emission_factor": lifecycle.FUEL_FACTORS[fuel],
                        "factor_source": lifecycle.FUEL_FACTOR_SOURCE,
                        "energy_kwh": qty * csrd.FUEL_KWH_PER_UNIT.get(fuel, Decimal("10")),
                        "data_quality": "measured",
                        "source_module": "equipment",
                    },
                    user_id,
                )
            )
        return out

    async def collect_rows(
        self, year: int, project_ids: set[uuid.UUID] | None, user_id: str | None, admin: bool
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Flat source rows for the E1 aggregate, plus the targets."""
        rows: list[dict[str, Any]] = []

        def scoped(stmt: Any, model: Any) -> Any:
            stmt = stmt.join(CarbonInventory, CarbonInventory.id == model.inventory_id)
            if project_ids is not None:
                stmt = stmt.where(CarbonInventory.project_id.in_(project_ids))
            return stmt

        for scope, model, energy in ((1, Scope1Entry, None), (2, Scope2Entry, "kwh"), (3, Scope3Entry, None)):
            stmt = scoped(select(model, CarbonInventory.project_id), model).where(
                extract("year", model.period_start) == year
            )
            for rec, pid in (await self.session.execute(stmt)).all():
                row = {
                    "scope": scope,
                    "co2e_kg": rec.total_co2e_kg,
                    "data_quality": rec.data_quality,
                    "source": model.__tablename__,
                    "source_id": rec.id,
                    "project_id": pid,
                }
                if energy:
                    row["energy_kwh"] = rec.kwh
                    row["renewable_share_pct"] = (rec.metadata_ or {}).get("renewable_share_pct", 0)
                    if rec.market_or_location == "market":
                        row["market_co2e_kg"] = rec.total_co2e_kg
                if scope == 1:
                    kwh = csrd.FUEL_KWH_PER_UNIT.get(rec.fuel_type)
                    if kwh:
                        row["energy_kwh"] = Decimal(str(rec.litres_or_m3)) * kwh
                rows.append(row)

        # Purchased materials (scope 3 category 1) from A1-A3 lines of inventories dated in the year.
        stmt = scoped(select(EmbodiedCarbonEntry, CarbonInventory.project_id), EmbodiedCarbonEntry).where(
            EmbodiedCarbonEntry.stage == "a1a3", extract("year", CarbonInventory.as_of_date) == year
        )
        for rec, pid in (await self.session.execute(stmt)).all():
            rows.append(
                {
                    "scope": 3,
                    "co2e_kg": rec.carbon_kg,
                    "data_quality": rec.data_quality,
                    "source": "oe_carbon_embodied_entry",
                    "source_id": rec.id,
                    "project_id": pid,
                }
            )

        for act in await self.list_activities(year, user_id, admin):
            rows.append(
                {
                    "scope": act.scope,
                    "co2e_kg": act.co2e_kg,
                    "market_co2e_kg": act.market_based_co2e_kg,
                    "energy_kwh": act.energy_kwh,
                    "renewable_share_pct": act.renewable_share_pct,
                    "data_quality": act.data_quality,
                    "source": "oe_carbon_company_activity",
                    "source_id": act.id,
                    "project_id": None,
                }
            )

        tstmt = select(CarbonTarget).where(CarbonTarget.target_type != BUDGET_TARGET_TYPE)
        if project_ids is not None:
            tstmt = tstmt.where(CarbonTarget.project_id.in_(project_ids))
        targets = [
            {
                "id": str(t.id),
                "name": t.name,
                "baseline_year": t.baseline_year,
                "target_year": t.target_year,
                "baseline_value": str(t.baseline_value),
                "target_value": str(t.target_value),
            }
            for t in (await self.session.execute(tstmt)).scalars()
        ]
        return rows, targets

    async def generate_company_report(
        self,
        *,
        year: int,
        template: str,
        net_revenue: Decimal,
        currency: str,
        company_name: str,
        project_ids: set[uuid.UUID] | None,
        user_id: str | None,
        admin: bool,
    ) -> CarbonCompanyReport:
        if template not in csrd.report_templates():
            raise _bad(f"unknown template: {template}")
        rows, targets = await self.collect_rows(year, project_ids, user_id, admin)
        datapoints, audit = csrd.build_e1_datapoints(rows, net_revenue=net_revenue, targets=targets, template=template)
        report = CarbonCompanyReport(
            reporting_year=year,
            template=template,
            company_name=company_name,
            net_revenue=net_revenue,
            currency=currency,
            datapoints=datapoints,
            audit=audit,
            created_by=user_id,
        )
        self.session.add(report)
        await self.session.flush()
        event_bus.publish_detached(
            "carbon.company_report.generated",
            {"report_id": str(report.id), "year": year, "template": template},
            source_module="carbon",
        )
        return report

    async def get_company_report(self, report_id: uuid.UUID, user_id: str | None, admin: bool) -> CarbonCompanyReport:
        rep = await self.session.get(CarbonCompanyReport, report_id)
        if rep is None or (not admin and rep.created_by != user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
        return rep

    async def list_company_reports(self, user_id: str | None, admin: bool) -> list[CarbonCompanyReport]:
        stmt = select(CarbonCompanyReport).order_by(CarbonCompanyReport.reporting_year.desc())
        if not admin:
            stmt = stmt.where(CarbonCompanyReport.created_by == user_id)
        return list((await self.session.execute(stmt)).scalars())


__all__ = ["BUDGET_TARGET_TYPE", "CarbonLifecycleService"]
