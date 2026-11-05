# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan business logic.

Scenarios are copy-on-write: a what-if is a clone whose items can be edited without
touching the baseline. Funding suggestions are returned, never applied; applying them is
a separate call the user makes. Writes flush only; the request middleware commits.
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import accessible_project_ids
from app.modules.capital_plan import logic
from app.modules.capital_plan.models import (
    CapitalPlan,
    CapitalPlanEnvelope,
    CapitalPlanItem,
    CapitalPlanScenario,
)
from app.modules.capital_plan.repository import CapitalPlanRepository
from app.modules.capital_plan.schemas import (
    ApplyStatuses,
    EnvelopesReplace,
    ItemCreate,
    ItemPatch,
    PlanCreate,
    PlanPatch,
    ScenarioCreate,
    ScenarioPatch,
)
from app.modules.capital_plan.validators import run_rules
from app.modules.portfolio.models import PortfolioMembership, PortfolioNode


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _year_of(value: str | None) -> int | None:
    """Year of an ISO date string, or None when it does not start with four digits."""
    head = (value or "")[:4]
    return int(head) if head.isdigit() else None


def item_dict(row: CapitalPlanItem) -> dict[str, Any]:
    """The plain-dict shape the pure logic and the rules work on."""
    return {
        "id": str(row.id),
        "project_id": str(row.project_id) if row.project_id else None,
        "title": row.title,
        "priority": row.priority,
        "start_year": row.start_year,
        "duration_years": row.duration_years,
        "total_cost": row.total_cost,
        "phasing": list(row.phasing_json or []),
        "status": row.status,
        "score": row.score,
    }


def plan_dict(plan: CapitalPlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "currency": plan.currency,
        "start_year": plan.start_year,
        "horizon_years": plan.horizon_years,
    }


def envelope_dicts(rows: list[CapitalPlanEnvelope]) -> list[dict[str, Any]]:
    return [{"year": r.year, "amount": r.amount, "label": r.label} for r in rows]


class CapitalPlanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CapitalPlanRepository(session)

    # ── Lookups ────────────────────────────────────────────────────────────

    async def get_plan(self, plan_id: uuid.UUID) -> CapitalPlan:
        plan = await self.repo.get_plan(plan_id)
        if plan is None:
            raise _not_found("Capital plan")
        return plan

    async def get_scenario(self, scenario_id: uuid.UUID, plan_id: uuid.UUID | None = None) -> CapitalPlanScenario:
        scenario = await self.repo.get_scenario(scenario_id)
        if scenario is None or (plan_id is not None and scenario.plan_id != plan_id):
            raise _not_found("Scenario")
        return scenario

    async def get_item(self, item_id: uuid.UUID) -> CapitalPlanItem:
        item = await self.repo.get_item(item_id)
        if item is None:
            raise _not_found("Item")
        return item

    async def _node_subtree(self, node_id: uuid.UUID) -> list[uuid.UUID]:
        nodes = list((await self.session.execute(select(PortfolioNode))).scalars().all())
        children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
        for n in nodes:
            children.setdefault(n.parent_id, []).append(n.id)
        seen: list[uuid.UUID] = []
        stack = [node_id]
        while stack:
            cur = stack.pop()
            if cur not in seen:
                seen.append(cur)
                stack.extend(children.get(cur, []))
        return seen

    async def _require_node(self, node_id: uuid.UUID) -> None:
        if await self.session.get(PortfolioNode, node_id) is None:
            raise _not_found("Portfolio node")

    # ── Plans ──────────────────────────────────────────────────────────────

    async def list_plans(
        self, node_id: uuid.UUID | None = None, *, offset: int = 0, limit: int | None = None
    ) -> tuple[list[CapitalPlan], int]:
        """Plans (page, total), optionally narrowed to a portfolio node and everything under it."""
        if node_id is None:
            return await self.repo.list_plans(offset=offset, limit=limit)
        return await self.repo.list_plans(await self._node_subtree(node_id), offset=offset, limit=limit)

    async def create_plan(self, data: PlanCreate, user_id: str) -> CapitalPlan:
        if data.node_id is not None:
            await self._require_node(data.node_id)
        plan = CapitalPlan(
            node_id=data.node_id,
            name=data.name,
            currency=data.currency,
            start_year=data.start_year,
            horizon_years=data.horizon_years,
            created_by=uuid.UUID(str(user_id)) if user_id else None,
            metadata_=data.metadata,
        )
        await self.repo.add(plan)
        # A plan always has a baseline to hang items on.
        await self.repo.add(CapitalPlanScenario(plan_id=plan.id, name="Baseline", is_baseline=True))
        return plan

    async def patch_plan(self, plan_id: uuid.UUID, data: PlanPatch) -> CapitalPlan:
        plan = await self.get_plan(plan_id)
        fields = data.model_dump(exclude_unset=True)
        if fields.get("node_id") is not None:
            await self._require_node(fields["node_id"])
        for key, value in fields.items():
            if value is None and key != "node_id":
                continue
            setattr(plan, key, value)
        await self.session.flush()
        return plan

    async def delete_plan(self, plan_id: uuid.UUID) -> None:
        await self.repo.delete_row(await self.get_plan(plan_id))

    # ── Envelopes ──────────────────────────────────────────────────────────

    async def list_envelopes(
        self, plan_id: uuid.UUID, *, offset: int = 0, limit: int | None = None
    ) -> tuple[list[CapitalPlanEnvelope], int]:
        await self.get_plan(plan_id)
        rows = await self.repo.list_envelopes(plan_id, offset=offset, limit=limit)
        return rows, await self.repo.count_envelopes(plan_id)

    async def replace_envelopes(self, plan_id: uuid.UUID, data: EnvelopesReplace) -> list[CapitalPlanEnvelope]:
        await self.get_plan(plan_id)
        keys = [(e.year, e.label) for e in data.envelopes]
        if len(set(keys)) != len(keys):
            raise _unprocessable("Duplicate year and label in envelopes")
        await self.repo.clear_envelopes(plan_id)
        for e in data.envelopes:
            self.session.add(CapitalPlanEnvelope(plan_id=plan_id, year=e.year, amount=e.amount, label=e.label))
        await self.session.flush()
        return await self.repo.list_envelopes(plan_id)

    # ── Scenarios ──────────────────────────────────────────────────────────

    async def list_scenarios(
        self, plan_id: uuid.UUID, *, offset: int = 0, limit: int | None = None
    ) -> tuple[list[CapitalPlanScenario], int]:
        await self.get_plan(plan_id)
        rows = await self.repo.list_scenarios(plan_id, offset=offset, limit=limit)
        return rows, await self.repo.count_scenarios(plan_id)

    async def _assert_baseline_free(self, plan_id: uuid.UUID, except_id: uuid.UUID | None = None) -> None:
        for s in await self.repo.list_scenarios(plan_id):
            if s.is_baseline and s.id != except_id:
                raise _conflict("The plan already has a baseline scenario")

    async def create_scenario(self, plan_id: uuid.UUID, data: ScenarioCreate) -> CapitalPlanScenario:
        await self.get_plan(plan_id)
        if data.is_baseline:
            await self._assert_baseline_free(plan_id)
        scenario = CapitalPlanScenario(plan_id=plan_id, name=data.name, is_baseline=data.is_baseline, notes=data.notes)
        await self.repo.add(scenario)
        return scenario

    async def patch_scenario(
        self, plan_id: uuid.UUID, scenario_id: uuid.UUID, data: ScenarioPatch
    ) -> CapitalPlanScenario:
        scenario = await self.get_scenario(scenario_id, plan_id)
        fields = data.model_dump(exclude_unset=True)
        if fields.get("is_baseline"):
            await self._assert_baseline_free(plan_id, except_id=scenario.id)
        for key, value in fields.items():
            if value is not None:
                setattr(scenario, key, value)
        await self.session.flush()
        return scenario

    async def delete_scenario(self, plan_id: uuid.UUID, scenario_id: uuid.UUID) -> None:
        scenario = await self.get_scenario(scenario_id, plan_id)
        if scenario.is_baseline:
            raise _conflict("The baseline scenario cannot be deleted")
        await self.repo.delete_row(scenario)

    async def clone_scenario(self, plan_id: uuid.UUID, scenario_id: uuid.UUID, name: str | None) -> CapitalPlanScenario:
        """Copy a scenario and its items; the copy is never the baseline."""
        source = await self.get_scenario(scenario_id, plan_id)
        clone = CapitalPlanScenario(
            plan_id=plan_id, name=name or f"{source.name} (copy)", is_baseline=False, notes=source.notes
        )
        await self.repo.add(clone)
        for item in await self.repo.list_items(source.id):
            self.session.add(
                CapitalPlanItem(
                    scenario_id=clone.id,
                    project_id=item.project_id,
                    title=item.title,
                    priority=item.priority,
                    start_year=item.start_year,
                    duration_years=item.duration_years,
                    total_cost=item.total_cost,
                    phasing_json=list(item.phasing_json or []),
                    status=item.status,
                    score=item.score,
                )
            )
        await self.session.flush()
        return clone

    # ── Items ──────────────────────────────────────────────────────────────

    async def list_items(
        self, scenario_id: uuid.UUID, *, offset: int = 0, limit: int | None = None
    ) -> tuple[list[CapitalPlanItem], int]:
        await self.get_scenario(scenario_id)
        rows = await self.repo.list_items(scenario_id, offset=offset, limit=limit)
        return rows, await self.repo.count_items(scenario_id)

    async def _require_project(self, project_id: uuid.UUID | None, user_id: str | None) -> None:
        """A linked project must exist and be reachable by the caller."""
        if project_id is None or user_id is None:
            return
        reachable = await accessible_project_ids(self.session, user_id, live_only=True)
        if reachable is not None and project_id not in reachable:
            raise _not_found("Project")

    async def create_item(
        self, scenario_id: uuid.UUID, data: ItemCreate, user_id: str | None = None
    ) -> CapitalPlanItem:
        await self.get_scenario(scenario_id)
        await self._require_project(data.project_id, user_id)
        item = CapitalPlanItem(
            scenario_id=scenario_id,
            project_id=data.project_id,
            title=data.title,
            priority=data.priority,
            start_year=data.start_year,
            duration_years=data.duration_years,
            total_cost=data.total_cost,
            phasing_json=[str(x) for x in data.phasing or []],
            status=data.status,
            score=data.score,
        )
        await self.repo.add(item)
        return item

    async def patch_item(self, item_id: uuid.UUID, data: ItemPatch, user_id: str | None = None) -> CapitalPlanItem:
        item = await self.get_item(item_id)
        fields = data.model_dump(exclude_unset=True)
        await self._require_project(fields.get("project_id"), user_id)
        phasing = fields.pop("phasing", None)
        for key, value in fields.items():
            if value is not None or key in ("project_id", "score"):
                setattr(item, key, value)
        if phasing is not None:
            item.phasing_json = [str(x) for x in phasing]
        elif "duration_years" in fields and item.phasing_json:
            # A new duration invalidates the old fractions; fall back to the even split.
            item.phasing_json = []
        await self.session.flush()
        return item

    async def delete_item(self, item_id: uuid.UUID) -> None:
        await self.repo.delete_row(await self.get_item(item_id))

    async def apply_statuses(self, scenario_id: uuid.UUID, data: ApplyStatuses) -> list[CapitalPlanItem]:
        """Set item statuses in bulk (the user accepting a funding suggestion)."""
        await self.get_scenario(scenario_id)
        by_id = {i.id: i for i in await self.repo.list_items(scenario_id)}
        for change in data.items:
            if change.id not in by_id:
                raise _not_found("Item")
            by_id[change.id].status = change.status
        await self.session.flush()
        return await self.repo.list_items(scenario_id)

    # ── Import ─────────────────────────────────────────────────────────────

    async def _project_cost(self, project: Any) -> Decimal:
        """Latest approved BOQ total, else the project budget estimate, else the contract value."""
        from app.modules.boq.models import BOQ
        from app.modules.boq.service import BOQService

        stmt = (
            select(BOQ)
            .where(BOQ.project_id == project.id, BOQ.status == "approved")
            .order_by(BOQ.approved_at.desc().nulls_last(), BOQ.created_at.desc())
            .limit(1)
        )
        boq = (await self.session.execute(stmt)).scalars().first()
        if boq is not None:
            totals = await BOQService(self.session).compute_boq_totals([boq.id])
            grand = Decimal(str((totals.get(boq.id) or {}).get("grand_total") or 0))
            if grand > 0:
                return logic.money(grand)
        for raw in (project.budget_estimate, project.contract_value):
            amount = logic.money(raw)
            if amount > 0:
                return amount
        return Decimal("0.00")

    async def import_projects(
        self, plan_id: uuid.UUID, scenario_id: uuid.UUID, user_id: str
    ) -> tuple[list[CapitalPlanItem], int]:
        """Create items from the projects filed under the plan's node (or all the caller can reach)."""
        from app.modules.projects.models import Project

        plan = await self.get_plan(plan_id)
        await self.get_scenario(scenario_id, plan_id)
        if plan.node_id is not None:
            subtree = await self._node_subtree(plan.node_id)
            memberships = (
                (
                    await self.session.execute(
                        select(PortfolioMembership).where(PortfolioMembership.node_id.in_(subtree))
                    )
                )
                .scalars()
                .all()
            )
            wanted = {m.project_id for m in memberships}
        else:
            wanted = None
        reachable = await accessible_project_ids(self.session, user_id, live_only=True)
        stmt = select(Project).order_by(Project.name)
        if wanted is not None:
            stmt = stmt.where(Project.id.in_(wanted))
        if reachable is not None:
            stmt = stmt.where(Project.id.in_(reachable))
        projects = list((await self.session.execute(stmt)).scalars().all())

        present = {i.project_id for i in await self.repo.list_items(scenario_id) if i.project_id}
        created: list[CapitalPlanItem] = []
        skipped = 0
        for project in projects:
            if project.id in present:
                skipped += 1
                continue
            start = _year_of(project.planned_start_date) or plan.start_year
            end = _year_of(project.planned_end_date)
            duration = max((end - start + 1) if end else 1, 1)
            item = CapitalPlanItem(
                scenario_id=scenario_id,
                project_id=project.id,
                title=project.name,
                priority=3,
                start_year=start,
                duration_years=min(duration, 30),
                total_cost=await self._project_cost(project),
                phasing_json=[],
                status="proposed",
            )
            self.session.add(item)
            created.append(item)
        await self.session.flush()
        return created, skipped

    # ── Analysis ───────────────────────────────────────────────────────────

    async def _payload(self, plan: CapitalPlan, items: list[CapitalPlanItem]) -> dict[str, Any]:
        from app.modules.projects.models import Project

        ids = {i.project_id for i in items if i.project_id}
        currencies: dict[str, str] = {}
        if ids:
            rows = (await self.session.execute(select(Project.id, Project.currency).where(Project.id.in_(ids)))).all()
            currencies = {str(pid): cur or "" for pid, cur in rows}
        return {
            "plan": plan_dict(plan),
            "envelopes": envelope_dicts(await self.repo.list_envelopes(plan.id)),
            "items": [item_dict(i) for i in items],
            "baseline_count": await self.repo.count_baselines(plan.id),
            "project_currencies": currencies,
        }

    async def summary(self, scenario_id: uuid.UUID) -> dict[str, Any]:
        scenario = await self.get_scenario(scenario_id)
        plan = await self.get_plan(scenario.plan_id)
        items = await self.repo.list_items(scenario_id)
        payload = await self._payload(plan, items)
        result = logic.summarise(payload["plan"], payload["envelopes"], payload["items"])
        result["unfunded"] = [str(i.id) for i in items if i.status == "proposed"]
        result["findings"] = await run_rules(payload)
        return result

    async def autofund(self, scenario_id: uuid.UUID) -> dict[str, Any]:
        """A funding suggestion. Nothing is written; the user applies it separately."""
        scenario = await self.get_scenario(scenario_id)
        plan = await self.get_plan(scenario.plan_id)
        items = await self.repo.list_items(scenario_id)
        payload = await self._payload(plan, items)
        return {
            "items": logic.autofund(payload["envelopes"], payload["items"]),
            "findings": await run_rules(payload),
        }

    async def compare(self, plan_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID) -> dict[str, Any]:
        plan = await self.get_plan(plan_id)
        await self.get_scenario(a, plan_id)
        await self.get_scenario(b, plan_id)
        envelopes = envelope_dicts(await self.repo.list_envelopes(plan_id))
        items_a = [item_dict(i) for i in await self.repo.list_items(a)]
        items_b = [item_dict(i) for i in await self.repo.list_items(b)]
        return logic.compare(plan_dict(plan), envelopes, items_a, items_b)

    # ── Export ─────────────────────────────────────────────────────────────

    async def export_xlsx(self, scenario_id: uuid.UUID, locale: str) -> bytes:
        """The scenario as a workbook with the plan years as columns."""
        from openpyxl import Workbook
        from openpyxl.styles import Font

        from app.core.i18n import t

        def word(key: str) -> str:
            return t(f"capital_plan.export.{key}", locale=locale)

        scenario = await self.get_scenario(scenario_id)
        plan = await self.get_plan(scenario.plan_id)
        items = await self.repo.list_items(scenario_id)
        payload = await self._payload(plan, items)
        summary = logic.summarise(payload["plan"], payload["envelopes"], payload["items"])
        spend_by_id = {row["id"]: row["spend"] for row in summary["items"]}
        years = summary["years"]

        wb = Workbook()
        ws = wb.active
        ws.title = word("sheet")[:31]
        ws.append([f"{plan.name} - {scenario.name}", plan.currency])
        ws["A1"].font = Font(bold=True)
        ws.append([])
        ws.append([word("col.title"), word("col.priority"), word("col.status"), word("col.total"), *years])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        for item in items:
            spend = spend_by_id[str(item.id)]
            ws.append(
                [
                    item.title,
                    item.priority,
                    item.status,
                    item.total_cost,
                    *[Decimal(spend[str(y)]) for y in years],
                ]
            )
        ws.append([])
        for key, field in (("envelope", "envelope"), ("demand", "demand"), ("gap", "gap")):
            ws.append([word(f"row.{key}"), "", "", "", *[Decimal(r[field]) for r in summary["rows"]]])
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
        for row in ws.iter_rows(min_row=4, min_col=4):
            for cell in row:
                cell.number_format = "#,##0.00"
        ws.column_dimensions["A"].width = 38
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
