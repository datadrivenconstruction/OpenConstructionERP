# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Economics service: business case, cost frame and financing plan of one project.

The three parts are one record that is proposed and approved together, because
each is only meaningful next to the others: the investment of the business case
is the cost frame (a line can point at it instead of holding a number), and the
sources of finance must cover that investment.

Lifecycle of the plan::

    draft -> proposed -> approved -> reopened -> proposed -> ...
               |
               +-> draft (withdrawn)

* Edits are open in ``draft`` and ``reopened`` and closed while ``proposed`` and
  ``approved``. Drawing a tranche is an operational fact and stays open.
* A proposal needs no open error finding. A warning never blocks.
* With gates the governance gate approves: when the carrier document is
  binding and an approving act (a gate decision or an approved change request)
  is newer than the proposal, this module mirrors it. Without gates a manager
  approves by hand, never the person who proposed it under four-eyes.
* Approval freezes the figures it was judged on with a hash. The estimate and
  the commitments are not frozen: they stay live readings from the bill and the
  cost spine, and the frame is compared against them every time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import publish_after_commit
from app.modules.economics import calc, hosting, readings, rules
from app.modules.economics.calc import ZERO
from app.modules.economics.calc import FlowLine as FlowInput
from app.modules.economics.classification import normalise, overlaps, truncate
from app.modules.economics.errors import EconomicsError, conflict, not_found
from app.modules.economics.models import Approval, EconomicsPlan, FlowLine, FrameLine, FundingSource, Tranche
from app.modules.economics.registers import RegistersMixin
from app.modules.economics.repository import EconomicsRepository

logger = logging.getLogger(__name__)

MODULE = "economics"
EDITABLE = ("draft", "reopened")
_GO = ("go", "go_with_conditions")
BLOCKED_NOT_READY = "approval_not_ready"
BLOCKED_FOUR_EYES = "four_eyes_proposer_is_approver"
BLOCKED_NEEDS_CHANGE_REQUEST = "approval_needs_change_request"
BLOCKED_APPROVER_UNKNOWN = "approver_unknown"

_CENT = Decimal("0.01")


def _now() -> datetime:
    return datetime.now(UTC)


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def money(value: Decimal | None) -> str | None:
    """A decimal as a positional string: two places when that is exact, otherwise every place it has."""
    if value is None:
        return None
    if value == value.quantize(_CENT):
        return format(value.quantize(_CENT), "f")
    return format(value.normalize(), "f")


def ratio(value: Decimal | None, places: str = "0.01") -> str | None:
    return None if value is None else format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


class EconomicsService(RegistersMixin):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EconomicsRepository(session)

    # ── plumbing ───────────────────────────────────────────────────────────

    async def _audit(self, actor_id: Any, entity_type: str, entity_id: Any, action: str, **kw: Any) -> None:
        await log_activity(
            self.session,
            actor_id=_s(actor_id),
            entity_type=entity_type,
            entity_id=_s(entity_id),
            action=action,
            module=MODULE,
            **kw,
        )

    def _publish(self, name: str, data: dict[str, Any]) -> None:
        publish_after_commit(self.session, f"{MODULE}.{name}", data, source_module=MODULE)

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise not_found("project_not_found")
        return project

    async def get_plan(self, project_id: uuid.UUID) -> EconomicsPlan | None:
        return await self.repo.plan(project_id)

    async def require_plan(self, project_id: uuid.UUID, *, lock: bool = False) -> EconomicsPlan:
        plan = await self.repo.plan(project_id, lock=lock)
        if plan is None:
            raise not_found("plan_not_found")
        return plan

    async def start(self, project_id: uuid.UUID, actor_id: uuid.UUID | None) -> EconomicsPlan:
        """Create the plan with the project's currency and classification standard; idempotent."""
        plan = await self.repo.plan(project_id)
        if plan is not None:
            return plan
        project = await self._project(project_id)
        plan = await self.repo.add(
            EconomicsPlan(
                project_id=project_id,
                currency=(project.currency or "").upper()[:3],
                classification_standard=(project.classification_standard or "")[:50],
                created_by=actor_id,
            )
        )
        await self._audit(actor_id, "economics_plan", plan.id, "plan_started")
        return plan

    async def _editable(self, project_id: uuid.UUID) -> EconomicsPlan:
        plan = await self.require_plan(project_id, lock=True)
        if plan.status not in EDITABLE:
            raise conflict("plan_not_editable", detail=plan.status)
        return plan

    # ── plan settings ──────────────────────────────────────────────────────

    async def patch_plan(self, project_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID) -> EconomicsPlan:
        plan = await self._editable(project_id)
        if changes.pop("clear_boq", False):
            plan.boq_id = None
        if changes.get("boq_id") is not None:
            bill, _ = await readings.pick_bill(self.session, project_id, changes["boq_id"])
            if bill is None:
                raise not_found("bill_not_found")
        for key in ("discount_rate_pct", "horizon_years", "markup_allowance", "boq_id", "currency"):
            if key in changes and changes[key] is not None:
                value = changes[key]
                setattr(plan, key, value.upper() if key == "currency" else value)
        if changes.get("classification_standard"):
            plan.classification_standard = changes["classification_standard"].strip().lower()
        await self.session.flush()
        await self._audit(actor_id, "economics_plan", plan.id, "plan_changed")
        return plan

    # ── business case lines ────────────────────────────────────────────────

    async def add_flow_line(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: uuid.UUID) -> FlowLine:
        plan = await self._editable(project_id)
        kind = data["kind"]
        mode = data.get("mode") or ("per_year" if kind in ("revenue", "operating_cost") else "total")
        year_from = int(data.get("year_from") or 0)
        year_to = data.get("year_to")
        if year_to is None:
            year_to = plan.horizon_years if mode == "per_year" else year_from
        line = await self.repo.add(
            FlowLine(
                project_id=project_id,
                kind=kind,
                label=data.get("label", ""),
                mode=mode,
                source=data.get("source", "manual"),
                amount=data.get("amount", ZERO),
                year_from=year_from,
                year_to=int(year_to),
                escalation_pct=data.get("escalation_pct", ZERO),
                notes=data.get("notes", ""),
                sort_order=await self.repo.next_sort(FlowLine, project_id),
            )
        )
        await self._audit(actor_id, "economics_flow_line", line.id, "flow_line_added")
        return line

    async def patch_flow_line(
        self, project_id: uuid.UUID, line_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> FlowLine:
        await self._editable(project_id)
        line = await self.repo.flow_line(project_id, line_id)
        if line is None:
            raise not_found("flow_line_not_found")
        if changes.get("source") == "cost_frame" and line.kind != "investment":
            raise EconomicsError("cost_frame_source_needs_investment", 422)
        for key, value in changes.items():
            if value is not None:
                setattr(line, key, value)
        await self.session.flush()
        await self._audit(actor_id, "economics_flow_line", line.id, "flow_line_changed")
        return line

    async def delete_flow_line(self, project_id: uuid.UUID, line_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        await self._editable(project_id)
        line = await self.repo.flow_line(project_id, line_id)
        if line is None:
            raise not_found("flow_line_not_found")
        await self.session.delete(line)
        await self.session.flush()
        await self._audit(actor_id, "economics_flow_line", line_id, "flow_line_deleted")

    # ── cost frame lines ───────────────────────────────────────────────────

    async def add_frame_line(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: uuid.UUID) -> FrameLine:
        await self._editable(project_id)
        code = normalise(data["code"])
        if not code:
            raise EconomicsError("code_required", 422)
        existing = await self.repo.frame_lines(project_id)
        if any(normalise(f.code) == code for f in existing):
            raise conflict("frame_code_exists")
        clash = next((f.code for f in existing if overlaps(f.code, code)), None)
        if clash is not None:
            raise EconomicsError("frame_lines_overlap", 422, detail=clash)
        line = await self.repo.add(
            FrameLine(
                project_id=project_id,
                code=code,
                title=data.get("title", ""),
                amount=data.get("amount", ZERO),
                basis=data.get("basis", ""),
                sort_order=await self.repo.next_sort(FrameLine, project_id),
            )
        )
        await self._audit(actor_id, "economics_frame_line", line.id, "frame_line_added")
        return line

    async def patch_frame_line(
        self, project_id: uuid.UUID, line_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> FrameLine:
        await self._editable(project_id)
        line = await self.repo.frame_line(project_id, line_id)
        if line is None:
            raise not_found("frame_line_not_found")
        for key, value in changes.items():
            if value is not None:
                setattr(line, key, value)
        await self.session.flush()
        await self._audit(actor_id, "economics_frame_line", line.id, "frame_line_changed")
        return line

    async def delete_frame_line(self, project_id: uuid.UUID, line_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        await self._editable(project_id)
        line = await self.repo.frame_line(project_id, line_id)
        if line is None:
            raise not_found("frame_line_not_found")
        await self.session.delete(line)
        await self.session.flush()
        await self._audit(actor_id, "economics_frame_line", line_id, "frame_line_deleted")

    async def generate_frame(
        self, project_id: uuid.UUID, *, depth: int, amounts: str, replace: bool, actor_id: uuid.UUID
    ) -> list[FrameLine]:
        """Frame lines from the codes the bill uses, cut to ``depth``; the budget is the bill's own amount or zero.

        The classification standard is the plan's (taken from the project), so a DIN 276 project gets
        cost groups, an NRM project elements, and so on. Existing lines are kept unless ``replace``;
        a code that would overlap a kept line is skipped, never merged.
        """
        plan = await self._editable(project_id)
        bill = await readings.read_bill(self.session, project_id, plan.classification_standard, plan.boq_id)
        if bill is None:
            raise not_found("bill_not_found")
        if replace:
            for row in await self.repo.frame_lines(project_id):
                await self.session.delete(row)
            await self.session.flush()
        kept = [] if replace else await self.repo.frame_lines(project_id)
        totals: dict[str, Decimal] = {}
        for leaf in bill.leaves:
            if leaf.code:
                key = truncate(leaf.code, depth)
                totals[key] = totals.get(key, ZERO) + leaf.amount
        titles = await self._code_titles(project_id, plan.classification_standard)
        created: list[FrameLine] = []
        for code in sorted(totals):
            if any(overlaps(k.code, code) for k in kept + created):
                continue
            created.append(
                await self.repo.add(
                    FrameLine(
                        project_id=project_id,
                        code=code,
                        title=titles.get(code, ""),
                        amount=totals[code] if amounts == "estimate" else ZERO,
                        basis="",
                        sort_order=await self.repo.next_sort(FrameLine, project_id),
                    )
                )
            )
        await self._audit(actor_id, "economics_plan", plan.id, "frame_generated", metadata={"lines": len(created)})
        return created

    async def _code_titles(self, project_id: uuid.UUID, standard: str) -> dict[str, str]:
        """Titles of the control accounts of the cost spine, keyed by their classification code."""
        from sqlalchemy import select

        from app.modules.costmodel.models import ControlAccount

        rows = (
            await self.session.execute(
                select(ControlAccount.code, ControlAccount.name).where(ControlAccount.project_id == project_id)
            )
        ).all()
        return {normalise(code): name for code, name in rows if name and name != code}

    # ── financing ──────────────────────────────────────────────────────────

    async def _application(self, project_id: uuid.UUID, application_id: uuid.UUID) -> Any:
        from app.modules.funding.models import FundingApplication

        row = await self.session.get(FundingApplication, application_id)
        if row is None or row.project_id != project_id:
            raise not_found("funding_application_not_found")
        return row

    async def add_source(self, project_id: uuid.UUID, data: dict[str, Any], actor_id: uuid.UUID) -> FundingSource:
        await self._editable(project_id)
        if data.get("funding_application_id") is not None:
            await self._application(project_id, data["funding_application_id"])
        source = await self.repo.add(
            FundingSource(
                project_id=project_id,
                kind=data["kind"],
                name=data.get("name", ""),
                amount=data.get("amount", ZERO),
                interest_rate_pct=data.get("interest_rate_pct"),
                funding_application_id=data.get("funding_application_id"),
                notes=data.get("notes", ""),
                sort_order=await self.repo.next_sort(FundingSource, project_id),
            )
        )
        await self._audit(actor_id, "economics_source", source.id, "source_added")
        return source

    async def patch_source(
        self, project_id: uuid.UUID, source_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> FundingSource:
        await self._editable(project_id)
        source = await self.repo.source(project_id, source_id)
        if source is None:
            raise not_found("source_not_found")
        if changes.pop("clear_funding_application", False):
            source.funding_application_id = None
        if changes.get("funding_application_id") is not None:
            await self._application(project_id, changes["funding_application_id"])
        for key, value in changes.items():
            if value is not None:
                setattr(source, key, value)
        await self.session.flush()
        await self._audit(actor_id, "economics_source", source.id, "source_changed")
        return source

    async def delete_source(self, project_id: uuid.UUID, source_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        await self._editable(project_id)
        source = await self.repo.source(project_id, source_id)
        if source is None:
            raise not_found("source_not_found")
        if any(t.status == "drawn" for t in await self.repo.tranches(project_id) if t.source_id == source_id):
            raise conflict("source_has_drawn_tranches")
        await self.session.delete(source)
        await self.session.flush()
        await self._audit(actor_id, "economics_source", source_id, "source_deleted")

    async def add_tranche(
        self, project_id: uuid.UUID, source_id: uuid.UUID, data: dict[str, Any], actor_id: uuid.UUID
    ) -> Tranche:
        await self._editable(project_id)
        if await self.repo.source(project_id, source_id) is None:
            raise not_found("source_not_found")
        tranche = await self.repo.add(
            Tranche(
                project_id=project_id,
                source_id=source_id,
                due_on=data["due_on"],
                amount=data["amount"],
                condition=data.get("condition", ""),
            )
        )
        await self._audit(actor_id, "economics_tranche", tranche.id, "tranche_added")
        return tranche

    async def patch_tranche(
        self, project_id: uuid.UUID, tranche_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> Tranche:
        plan = await self.require_plan(project_id, lock=True)
        tranche = await self.repo.tranche(project_id, tranche_id)
        if tranche is None:
            raise not_found("tranche_not_found")
        # Drawing a tranche is a fact of the project and stays open while the plan is approved; moving
        # or resizing one is a change of the plan and is not.
        if plan.status not in EDITABLE and set(changes) - {"status", "drawn_on", "condition"}:
            raise conflict("plan_not_editable", detail=plan.status)
        if changes.get("status") == "drawn" and not (changes.get("drawn_on") or tranche.drawn_on):
            changes["drawn_on"] = datetime.now(UTC).date().isoformat()
        for key, value in changes.items():
            if value is not None:
                setattr(tranche, key, value)
        await self.session.flush()
        await self._audit(actor_id, "economics_tranche", tranche.id, "tranche_changed")
        return tranche

    async def delete_tranche(self, project_id: uuid.UUID, tranche_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        await self._editable(project_id)
        tranche = await self.repo.tranche(project_id, tranche_id)
        if tranche is None:
            raise not_found("tranche_not_found")
        if tranche.status == "drawn":
            raise conflict("tranche_drawn")
        await self.session.delete(tranche)
        await self.session.flush()
        await self._audit(actor_id, "economics_tranche", tranche_id, "tranche_deleted")

    # ── views: the three parts ─────────────────────────────────────────────

    async def _frame_numbers(self, plan: EconomicsPlan) -> dict[str, Any]:
        """The cost frame compared with the bill and the commitments, all as Decimals."""
        project_id = plan.project_id
        lines = await self.repo.frame_lines(project_id)
        codes = [normalise(f.code) for f in lines]
        bill = await readings.read_bill(self.session, project_id, plan.classification_standard, plan.boq_id)
        commit = await readings.read_commitments(self.session, project_id)
        est, est_loose, est_count = calc.assign(codes, bill.leaves if bill else [])
        com, com_loose, _ = calc.assign(codes, commit.readings)
        rows = []
        for f in lines:
            code = normalise(f.code)
            estimate = est.get(code, ZERO)
            committed = com.get(code, ZERO) if commit.available else None
            rows.append(
                {
                    "id": str(f.id),
                    "code": f.code,
                    "title": f.title,
                    "basis": f.basis,
                    "amount": f.amount,
                    "estimate": estimate,
                    "committed": committed,
                    "variance": estimate - f.amount,
                    "variance_pct": calc.pct_of(estimate - f.amount, f.amount),
                    "headroom": f.amount - max(estimate, committed or ZERO),
                }
            )
        lines_total = sum((f.amount for f in lines), ZERO)
        markups_total = bill.markups_total if bill else ZERO
        frame_total = lines_total + plan.markup_allowance
        estimate_total = bill.grand_total if bill else ZERO
        return {
            "rows": rows,
            "lines_total": lines_total,
            "markup_allowance": plan.markup_allowance,
            "frame_total": frame_total,
            "bill": bill,
            "estimate_assigned": sum(est.values(), ZERO),
            "estimate_unassigned": est_loose,
            "unassigned_count": est_count,
            "markups_total": markups_total,
            "estimate_total": estimate_total,
            "variance_total": estimate_total - frame_total,
            "variance_total_pct": calc.pct_of(estimate_total - frame_total, frame_total),
            "committed_available": commit.available,
            "committed_reason": commit.reason,
            "committed_total": commit.total if commit.available else None,
            "committed_unassigned": com_loose if commit.available else None,
        }

    async def cost_frame(self, project_id: uuid.UUID) -> dict[str, Any]:
        plan = await self.require_plan(project_id)
        n = await self._frame_numbers(plan)
        bill = n["bill"]
        return {
            "classification_standard": plan.classification_standard,
            "currency": plan.currency,
            "bill": None
            if bill is None
            else {
                "id": str(bill.boq_id),
                "name": bill.boq_name,
                "currency": bill.currency,
                "bill_count": bill.bill_count,
            },
            "lines": [
                {
                    **{
                        k: v
                        for k, v in r.items()
                        if k not in ("amount", "estimate", "committed", "variance", "variance_pct", "headroom")
                    },
                    "amount": money(r["amount"]),
                    "estimate": money(r["estimate"]),
                    "committed": money(r["committed"]),
                    "variance": money(r["variance"]),
                    "variance_pct": ratio(r["variance_pct"]),
                    "headroom": money(r["headroom"]),
                }
                for r in n["rows"]
            ],
            "markups": [
                {"name": m.name, "category": m.category, "amount": money(m.amount)}
                for m in (bill.markups if bill else [])
            ],
            "totals": {
                "lines": money(n["lines_total"]),
                "markup_allowance": money(n["markup_allowance"]),
                "frame": money(n["frame_total"]),
                "estimate_direct": money(bill.direct_cost if bill else ZERO),
                "estimate_assigned": money(n["estimate_assigned"]),
                "estimate_unassigned": money(n["estimate_unassigned"]),
                "unassigned_count": n["unassigned_count"],
                "markups": money(n["markups_total"]),
                "estimate": money(n["estimate_total"]),
                "reserve": money(n["frame_total"] - n["estimate_total"]),
                "variance": money(n["variance_total"]),
                "variance_pct": ratio(n["variance_total_pct"]),
                "committed": money(n["committed_total"]),
                "committed_unassigned": money(n["committed_unassigned"]),
                "committed_available": n["committed_available"],
                "committed_reason": n["committed_reason"],
            },
        }

    async def _flow_inputs(self, plan: EconomicsPlan, frame_total: Decimal) -> list[tuple[FlowLine, FlowInput]]:
        out = []
        for line in await self.repo.flow_lines(plan.project_id):
            amount = frame_total if line.source == "cost_frame" else line.amount
            out.append(
                (
                    line,
                    FlowInput(
                        kind=line.kind,
                        mode=line.mode,
                        amount=amount,
                        year_from=line.year_from,
                        year_to=line.year_to,
                        escalation_pct=line.escalation_pct,
                    ),
                )
            )
        return out

    async def _frame_total(self, plan: EconomicsPlan) -> Decimal:
        lines = await self.repo.frame_lines(plan.project_id)
        return sum((f.amount for f in lines), ZERO) + plan.markup_allowance

    def _key_figure_view(self, figures: dict[str, Any]) -> dict[str, Any]:
        return {
            "total_investment": money(figures["total_investment"]),
            "total_revenue": money(figures["total_revenue"]),
            "total_operating_cost": money(figures["total_operating_cost"]),
            "residual_value": money(figures["residual_value"]),
            "net_cash_flow": money(figures["net_cash_flow"]),
            "npv": money(figures["npv"].quantize(_CENT, rounding=ROUND_HALF_UP))
            if figures["npv"] is not None
            else None,
            "irr_pct": ratio(figures["irr_pct"]),
            "payback_year": figures["payback_year"],
            "benefit_cost_ratio": ratio(figures["benefit_cost_ratio"], "0.0001"),
            "yield_on_cost_pct": ratio(figures["yield_on_cost_pct"]),
        }

    async def business_case(self, project_id: uuid.UUID) -> dict[str, Any]:
        plan = await self.require_plan(project_id)
        frame_total = await self._frame_total(plan)
        pairs = await self._flow_inputs(plan, frame_total)
        inputs = [p[1] for p in pairs]
        figures = calc.key_figures(inputs, plan.horizon_years, plan.discount_rate_pct)
        flows = calc.cash_flows(inputs, plan.horizon_years)
        cumulative, running = [], ZERO
        for flow in flows:
            running += flow
            cumulative.append(running)
        return {
            "currency": plan.currency,
            "discount_rate_pct": ratio(plan.discount_rate_pct, "0.0001")
            if plan.discount_rate_pct is not None
            else None,
            "horizon_years": plan.horizon_years,
            "frame_total": money(frame_total),
            "lines": [
                {
                    "id": str(line.id),
                    "kind": line.kind,
                    "label": line.label,
                    "mode": line.mode,
                    "source": line.source,
                    "amount": money(inp.amount),
                    "year_from": line.year_from,
                    "year_to": line.year_to,
                    "escalation_pct": ratio(line.escalation_pct, "0.0001"),
                    "notes": line.notes,
                }
                for line, inp in pairs
            ],
            "cash_flow": [
                {"year": year, "net": money(flow), "cumulative": money(cumulative[year])}
                for year, flow in enumerate(flows)
            ],
            "key_figures": self._key_figure_view(figures),
        }

    async def _financing_numbers(self, plan: EconomicsPlan, frame_total: Decimal) -> dict[str, Any]:
        from app.modules.funding.models import FundingApplication

        project_id = plan.project_id
        sources = await self.repo.sources(project_id)
        tranches = await self.repo.tranches(project_id)
        inputs = [inp for _line, inp in await self._flow_inputs(plan, frame_total)]
        invested = sum((sum(calc.yearly(i).values(), ZERO) for i in inputs if i.kind == "investment"), ZERO)
        # With no investment line the requirement is the cost frame itself: the money the project must find.
        requirement = invested if invested > 0 else frame_total
        cov = calc.coverage(requirement, [s.amount for s in sources])
        rows = []
        for s in sources:
            mine = [t for t in tranches if t.source_id == s.id and t.status != "cancelled"]
            award = None
            if s.funding_application_id is not None:
                app = await self.session.get(FundingApplication, s.funding_application_id)
                if app is not None and app.project_id == project_id:
                    awarded = app.status in ("approved", "closed")
                    award = {
                        "code": app.code,
                        "title": app.title,
                        "status": app.status,
                        "amount": app.approved_amount if awarded else app.requested_amount,
                        "basis": "approved" if awarded else "requested",
                    }
            rows.append((s, mine, award))
        return {"requirement": requirement, "coverage": cov, "rows": rows, "tranches": tranches}

    async def financing(self, project_id: uuid.UUID) -> dict[str, Any]:
        plan = await self.require_plan(project_id)
        n = await self._financing_numbers(plan, await self._frame_total(plan))
        cov = n["coverage"]
        total = cov["sources_total"]
        return {
            "currency": plan.currency,
            "requirement": money(n["requirement"]),
            "coverage": {
                "sources_total": money(total),
                "shortfall": money(cov["shortfall"]),
                "surplus": money(cov["surplus"]),
                "covered": cov["covered"],
                "coverage_pct": ratio(cov["coverage_pct"]),
            },
            "sources": [
                {
                    "id": str(s.id),
                    "kind": s.kind,
                    "name": s.name,
                    "amount": money(s.amount),
                    "share_pct": ratio(calc.pct_of(s.amount, total)),
                    "interest_rate_pct": ratio(s.interest_rate_pct, "0.0001")
                    if s.interest_rate_pct is not None
                    else None,
                    "funding_application_id": _s(s.funding_application_id),
                    "award": None if award is None else {**award, "amount": money(award["amount"])},
                    "notes": s.notes,
                    "tranche_total": money(sum((t.amount for t in mine), ZERO)),
                    "tranches": [
                        {
                            "id": str(t.id),
                            "due_on": t.due_on,
                            "amount": money(t.amount),
                            "status": t.status,
                            "condition": t.condition,
                            "drawn_on": t.drawn_on,
                        }
                        for t in n["tranches"]
                        if t.source_id == s.id
                    ],
                }
                for s, mine, award in n["rows"]
            ],
        }

    # ── findings and readiness ─────────────────────────────────────────────

    async def validation_payload(self, project_id: uuid.UUID) -> dict[str, Any]:
        plan = await self.require_plan(project_id)
        n = await self._frame_numbers(plan)
        frame_total = n["frame_total"]
        pairs = await self._flow_inputs(plan, frame_total)
        fin = await self._financing_numbers(plan, frame_total)
        bill = n["bill"]
        return {
            "plan": {
                "status": plan.status,
                "currency": plan.currency,
                "bill_currency": bill.currency if bill else "",
                "bill_count": bill.bill_count if bill else 0,
                "bill_chosen": plan.boq_id is not None,
                "discount_rate_pct": _s(plan.discount_rate_pct),
                "horizon_years": plan.horizon_years,
            },
            "flow_lines": [
                {
                    "id": str(line.id),
                    "kind": line.kind,
                    "label": line.label,
                    "source": line.source,
                    "amount": str(inp.amount),
                    "year_from": line.year_from,
                    "year_to": line.year_to,
                }
                for line, inp in pairs
            ],
            "frame": {
                "total": str(frame_total),
                "lines": [
                    {
                        "id": r["id"],
                        "code": r["code"],
                        "amount": str(r["amount"]),
                        "estimate": str(r["estimate"]),
                        "committed": None if r["committed"] is None else str(r["committed"]),
                    }
                    for r in n["rows"]
                ],
                "markup_allowance": str(n["markup_allowance"]),
                "markups_total": str(n["markups_total"]),
                "unassigned_estimate": str(n["estimate_unassigned"]),
                "unassigned_count": n["unassigned_count"],
                "committed_available": n["committed_available"],
                "committed_unassigned": str(n["committed_unassigned"] or ZERO),
            },
            "financing": {
                "requirement": str(fin["requirement"]),
                "coverage": {k: _s(v) for k, v in fin["coverage"].items()},
                "sources": [
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "kind": s.kind,
                        "amount": str(s.amount),
                        "tranche_total": str(sum((t.amount for t in mine), ZERO)),
                        "tranche_count": len(mine),
                        "award": None if award is None else {**award, "amount": str(award["amount"])},
                    }
                    for s, mine, award in fin["rows"]
                ],
            },
            "registers": await self.register_payload(project_id),
        }

    async def findings(self, project_id: uuid.UUID) -> list[rules.Finding]:
        return rules.all_findings(await self.validation_payload(project_id))

    async def readiness(self, project_id: uuid.UUID) -> dict[str, Any]:
        """What stands between the plan and a proposal: the open findings and whether it is proposed."""
        plan = await self.require_plan(project_id)
        found = await self.findings(project_id)
        blocking = [f.as_dict() for f in rules.errors(found)]
        return {
            "met": not blocking,
            "status": plan.status,
            "proposed": plan.status in ("proposed", "approved"),
            "errors": blocking,
            "warnings": [f.as_dict() for f in found if f.severity == rules.WARNING],
        }

    # ── snapshot and restore ───────────────────────────────────────────────

    async def _snapshot(self, plan: EconomicsPlan) -> dict[str, Any]:
        """Everything the approval is judged on, as plain JSON; enough to restore the plan from it."""
        project_id = plan.project_id
        frame_total = await self._frame_total(plan)
        pairs = await self._flow_inputs(plan, frame_total)
        figures = calc.key_figures([p[1] for p in pairs], plan.horizon_years, plan.discount_rate_pct)
        fin = await self.financing(project_id)
        return {
            "plan": {
                "discount_rate_pct": _s(plan.discount_rate_pct),
                "horizon_years": plan.horizon_years,
                "markup_allowance": str(plan.markup_allowance),
                "boq_id": _s(plan.boq_id),
                "currency": plan.currency,
                "classification_standard": plan.classification_standard,
            },
            "flow_lines": [
                {
                    "id": str(ln.id),
                    "kind": ln.kind,
                    "label": ln.label,
                    "mode": ln.mode,
                    "source": ln.source,
                    "amount": str(ln.amount),
                    "year_from": ln.year_from,
                    "year_to": ln.year_to,
                    "escalation_pct": str(ln.escalation_pct),
                    "notes": ln.notes,
                    "sort_order": ln.sort_order,
                }
                for ln, _ in pairs
            ],
            "frame_lines": [
                {
                    "id": str(f.id),
                    "code": f.code,
                    "title": f.title,
                    "amount": str(f.amount),
                    "basis": f.basis,
                    "sort_order": f.sort_order,
                }
                for f in await self.repo.frame_lines(project_id)
            ],
            "sources": [
                {
                    "id": str(s.id),
                    "kind": s.kind,
                    "name": s.name,
                    "amount": str(s.amount),
                    "interest_rate_pct": _s(s.interest_rate_pct),
                    "funding_application_id": _s(s.funding_application_id),
                    "notes": s.notes,
                    "sort_order": s.sort_order,
                }
                for s in await self.repo.sources(project_id)
            ],
            "tranches": [
                {
                    "id": str(t.id),
                    "source_id": str(t.source_id),
                    "due_on": t.due_on,
                    "amount": str(t.amount),
                    "status": t.status,
                    "condition": t.condition,
                    "drawn_on": t.drawn_on,
                }
                for t in await self.repo.tranches(project_id)
            ],
            "key_figures": self._key_figure_view(figures),
            "frame_total": str(frame_total),
            "financing_coverage": fin["coverage"],
        }

    async def _restore(self, plan: EconomicsPlan, snap: dict[str, Any]) -> None:
        """Put the plan's rows back to the approved snapshot; the edits of a reopening are dropped."""
        project_id = plan.project_id
        for tranche in await self.repo.tranches(project_id):
            await self.session.delete(tranche)
        for source in await self.repo.sources(project_id):
            await self.session.delete(source)
        for fl in await self.repo.flow_lines(project_id):
            await self.session.delete(fl)
        for fr in await self.repo.frame_lines(project_id):
            await self.session.delete(fr)
        await self.session.flush()
        p = snap["plan"]
        plan.discount_rate_pct = Decimal(p["discount_rate_pct"]) if p["discount_rate_pct"] is not None else None
        plan.horizon_years, plan.markup_allowance = p["horizon_years"], Decimal(p["markup_allowance"])
        plan.boq_id = uuid.UUID(p["boq_id"]) if p["boq_id"] else None
        for r in snap["flow_lines"]:
            self.session.add(
                FlowLine(
                    id=uuid.UUID(r["id"]),
                    project_id=project_id,
                    kind=r["kind"],
                    label=r["label"],
                    mode=r["mode"],
                    source=r["source"],
                    amount=Decimal(r["amount"]),
                    year_from=r["year_from"],
                    year_to=r["year_to"],
                    escalation_pct=Decimal(r["escalation_pct"]),
                    notes=r["notes"],
                    sort_order=r["sort_order"],
                )
            )
        for r in snap["frame_lines"]:
            self.session.add(
                FrameLine(
                    id=uuid.UUID(r["id"]),
                    project_id=project_id,
                    code=r["code"],
                    title=r["title"],
                    amount=Decimal(r["amount"]),
                    basis=r["basis"],
                    sort_order=r["sort_order"],
                )
            )
        for r in snap["sources"]:
            self.session.add(
                FundingSource(
                    id=uuid.UUID(r["id"]),
                    project_id=project_id,
                    kind=r["kind"],
                    name=r["name"],
                    amount=Decimal(r["amount"]),
                    interest_rate_pct=Decimal(r["interest_rate_pct"]) if r["interest_rate_pct"] is not None else None,
                    funding_application_id=uuid.UUID(r["funding_application_id"])
                    if r["funding_application_id"]
                    else None,
                    notes=r["notes"],
                    sort_order=r["sort_order"],
                )
            )
        await self.session.flush()
        for r in snap["tranches"]:
            self.session.add(
                Tranche(
                    id=uuid.UUID(r["id"]),
                    project_id=project_id,
                    source_id=uuid.UUID(r["source_id"]),
                    due_on=r["due_on"],
                    amount=Decimal(r["amount"]),
                    status=r["status"],
                    condition=r["condition"],
                    drawn_on=r["drawn_on"],
                )
            )
        await self.session.flush()

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def _approved(self, project_id: uuid.UUID) -> Approval | None:
        return next((a for a in await self.repo.approvals(project_id) if a.status == "approved"), None)

    async def action_blocks(self, plan: EconomicsPlan, actor_id: uuid.UUID | None = None) -> dict[str, str | None]:
        """Why each action is refused now, ``None`` when it is open. The view and the write both ask here."""
        gates = await hosting.gates_in_use(self.session, plan.project_id)
        carrier = None
        if gates:
            carrier, why = await hosting.carrier_document(self.session, plan.project_id)
        blocks: dict[str, str | None] = {
            "propose": None if plan.status in EDITABLE else "invalid_transition",
            "withdraw": None if plan.status == "proposed" else "invalid_transition",
            "approve": None,
            "reopen": None if plan.status == "approved" else "invalid_transition",
            "close_reopening": None if plan.status == "reopened" and plan.current_approval_id else "invalid_transition",
        }
        if gates and blocks["propose"] is None and carrier is None:
            blocks["propose"] = why
        blocks["approve"] = await self.hand_approval_refusal(plan, actor_id)
        return blocks

    async def propose(self, project_id: uuid.UUID, rationale: str, actor_id: uuid.UUID) -> Approval:
        plan = await self.require_plan(project_id, lock=True)
        blocked = (await self.action_blocks(plan))["propose"]
        if blocked:
            raise conflict(blocked)
        found = await self.findings(project_id)
        blocking = rules.errors(found)
        if blocking:
            raise EconomicsError("plan_has_errors", 422, violations=[f.as_dict() for f in blocking])
        snapshot = await self._snapshot(plan)
        for old in await self.repo.approvals(project_id):
            if old.status == "proposed":
                old.status = "withdrawn"
        approval = await self.repo.add(
            Approval(
                project_id=project_id,
                number=await self.repo.next_approval_number(project_id),
                status="proposed",
                rationale=rationale,
                snapshot=snapshot,
                snapshot_hash=snapshot_hash(snapshot),
                proposed_by=actor_id,
                proposed_at=_now(),
            )
        )
        plan.status, plan.current_approval_id = "proposed", approval.id
        await self.session.flush()
        await self._audit(actor_id, "economics_approval", approval.id, "plan_proposed")
        self._publish("plan.proposed", {"project_id": str(project_id), "approval_id": str(approval.id)})
        await self._approve_if_bound(plan)
        return approval

    async def withdraw(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> EconomicsPlan:
        plan = await self.require_plan(project_id, lock=True)
        blocked = (await self.action_blocks(plan))["withdraw"]
        if blocked:
            raise conflict(blocked)
        current = await self.repo.approval(project_id, plan.current_approval_id) if plan.current_approval_id else None
        if current is not None and current.status == "proposed":
            current.status, current.approval_blocked_reason = "withdrawn", ""
        approved = await self._approved(project_id)
        # A withdrawn proposal made during a reopening returns to the reopening: the approved version is
        # still in force and the edits stay open until they are proposed again.
        plan.status = "reopened" if approved is not None else "draft"
        plan.current_approval_id = approved.id if approved is not None else None
        await self.session.flush()
        await self._audit(actor_id, "economics_plan", plan.id, "plan_withdrawn")
        return plan

    async def reopen(self, project_id: uuid.UUID, actor_id: uuid.UUID, reason: str | None = None) -> EconomicsPlan:
        """Approved to reopened. With gates only while governance has an open change request on the carrier."""
        plan = await self.require_plan(project_id, lock=True)
        blocked = (await self.action_blocks(plan))["reopen"]
        if blocked:
            raise conflict(blocked)
        if not await hosting.gates_in_use(self.session, project_id):
            why = (reason or "").strip()
            if not why:
                raise EconomicsError("reopen_reason_required", 422)
            plan.status = "reopened"
            await self._audit(actor_id, "economics_plan", plan.id, "plan_reopened", metadata={"reason": why})
            await self.session.flush()
            return plan
        doc, _ = await hosting.carrier_document(self.session, project_id)
        open_cr = await hosting.open_change_request(self.session, project_id, doc.id) if doc is not None else None
        if open_cr is None:
            raise conflict("change_request_required")
        plan.change_request_id, plan.status = open_cr, "reopened"
        await self.session.flush()
        await self._audit(actor_id, "economics_plan", plan.id, "plan_reopened")
        return plan

    async def close_reopening(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> EconomicsPlan:
        """Give up a reopening: the rows return to the approved snapshot and the approved version stays in force."""
        plan = await self.require_plan(project_id, lock=True)
        blocked = (await self.action_blocks(plan))["close_reopening"]
        if blocked:
            raise conflict(blocked)
        await self._return_to_approved(plan, actor_id, "reopening_closed")
        return plan

    async def _return_to_approved(self, plan: EconomicsPlan, actor_id: Any, reason: str) -> None:
        approved = await self._approved(plan.project_id)
        if approved is None:
            raise conflict("reopening_not_open")
        await self._restore(plan, approved.snapshot)
        plan.status, plan.current_approval_id, plan.change_request_id = "approved", approved.id, None
        await self.session.flush()
        await self._audit(actor_id, "economics_plan", plan.id, reason)

    # approval mirror ------------------------------------------------------

    async def sync_with_governance(self, project_id: uuid.UUID) -> bool:
        """Bring the plan in line with what governance decided since; idempotent, returns whether it changed."""
        plan = await self.repo.plan(project_id)
        if plan is None or plan.status not in ("proposed", "reopened"):
            return False
        if plan.status != "proposed" and plan.change_request_id is None:
            return False
        await self.session.refresh(plan, with_for_update=True)
        if await self._settle_change_request(plan):
            return True
        if plan.status == "proposed":
            return await self._approve_if_bound(plan)
        return False

    async def mirror_binding(self, project_id: uuid.UUID | None) -> bool:
        """Subscriber entry point: a frame document of the project changed state."""
        return False if project_id is None else await self.sync_with_governance(project_id)

    async def _settle_change_request(self, plan: EconomicsPlan) -> bool:
        if plan.change_request_id is None:
            return False
        doc, _ = await hosting.carrier_document(self.session, plan.project_id)
        if doc is None:
            return False
        requests = await hosting.change_requests(self.session, plan.project_id, doc.id)
        cr = next((r for r in requests if r.id == plan.change_request_id), None)
        if cr is not None and cr.status in ("submitted", "approved"):
            return False
        await self._return_to_approved(plan, cr.decided_by if cr is not None else None, "change_request_rejected")
        return True

    async def _approving_act(
        self, plan: EconomicsPlan, approval: Approval, doc: Any
    ) -> tuple[Any, Any, str, Any] | None:
        """The governance act that bound the carrier for THIS proposal: ``(approver, at, source, ref)``."""
        proposed_at = approval.proposed_at
        approved = [
            r
            for r in await hosting.change_requests(self.session, plan.project_id, doc.id)
            if r.status == "approved" and r.decided_at
        ]
        for cr in sorted(approved, key=lambda r: r.decided_at, reverse=True):
            after = bool(proposed_at and cr.decided_at >= proposed_at)
            if after or cr.id == plan.change_request_id:
                return cr.decided_by, cr.decided_at if after else None, "change_request", cr.id
        if doc.approved_gate_id is not None:
            gd = await hosting.latest_gate_decision(self.session, plan.project_id, doc.approved_gate_id, _GO)
            if gd is not None and gd.decided_at and proposed_at and gd.decided_at >= proposed_at:
                return gd.decided_by, gd.decided_at, "gate", gd.id
        return None

    async def _blocked(self, approval: Approval, reason: str) -> bool:
        if (approval.approval_blocked_reason or "") == reason:
            return False
        approval.approval_blocked_reason = reason
        await self.session.flush()
        if reason:
            await self._audit(None, "economics_approval", approval.id, "approval_blocked", metadata={"reason": reason})
        return True

    async def _approve_if_bound(self, plan: EconomicsPlan) -> bool:
        if plan.status != "proposed" or plan.current_approval_id is None:
            return False
        approval = await self.repo.approval(plan.project_id, plan.current_approval_id)
        if approval is None or approval.status != "proposed":
            return False
        doc, _ = await hosting.carrier_document(self.session, plan.project_id)
        if doc is None or doc.status != "binding":
            return await self._blocked(approval, "")
        act = await self._approving_act(plan, approval, doc)
        if act is None:
            return await self._blocked(approval, BLOCKED_NEEDS_CHANGE_REQUEST)
        approver, at, source, ref = act
        if not (await self.readiness(plan.project_id))["met"]:
            return await self._blocked(approval, BLOCKED_NOT_READY)
        four_eyes = await hosting.four_eyes(self.session, plan.project_id)
        if four_eyes and approver is None:
            return await self._blocked(approval, BLOCKED_APPROVER_UNKNOWN)
        if four_eyes and approver == approval.proposed_by:
            return await self._blocked(approval, BLOCKED_FOUR_EYES)
        await self._approve(plan, approval, approver=approver, at=at, source=source, ref=ref, doc=doc)
        return True

    async def hand_approval_refusal(self, plan: EconomicsPlan, actor_id: uuid.UUID | None) -> str | None:
        """Why this person cannot approve the proposal by hand now (``None`` = they can)."""
        if await hosting.gates_in_use(self.session, plan.project_id):
            return "approved_by_gate_decision"
        approval = (
            await self.repo.approval(plan.project_id, plan.current_approval_id) if plan.current_approval_id else None
        )
        if plan.status != "proposed" or approval is None or approval.status != "proposed":
            return "plan_not_proposed"
        if (
            await hosting.four_eyes(self.session, plan.project_id)
            and actor_id is not None
            and approval.proposed_by == actor_id
        ):
            return BLOCKED_FOUR_EYES
        if not (await self.readiness(plan.project_id))["met"]:
            return BLOCKED_NOT_READY
        return None

    async def approve_by_hand(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> EconomicsPlan:
        plan = await self.require_plan(project_id, lock=True)
        refusal = await self.hand_approval_refusal(plan, actor_id)
        if refusal:
            raise conflict(refusal)
        approval = await self.repo.approval(project_id, plan.current_approval_id)
        await self._approve(plan, approval, approver=actor_id, at=None, source="hand", ref=None, doc=None)
        return plan

    async def _approve(
        self,
        plan: EconomicsPlan,
        approval: Approval,
        *,
        approver: Any,
        at: datetime | None,
        source: str,
        ref: Any,
        doc: Any | None,
    ) -> None:
        for old in await self.repo.approvals(plan.project_id):
            if old.status == "approved" and old.id != approval.id:
                old.status = "superseded"
        # Completed at approval from the rows as they stand, then frozen: the proposal may have been edited by
        # nobody (edits are closed), but the hash must describe what was approved.
        snapshot = await self._snapshot(plan)
        approval.snapshot, approval.snapshot_hash = snapshot, snapshot_hash(snapshot)
        approval.status, approval.approved_by, approval.approved_at = "approved", approver, at or _now()
        approval.approval_source, approval.governance_ref_id = source, ref
        if doc is not None:
            approval.governance_document_id = doc.id
        approval.four_eyes = await hosting.four_eyes(self.session, plan.project_id)
        approval.approval_blocked_reason = ""
        plan.status, plan.change_request_id = "approved", None
        await self.session.flush()
        await self._audit(approver, "economics_approval", approval.id, "plan_approved", metadata={"source": source})
        self._publish("plan.approved", {"project_id": str(plan.project_id), "approval_id": str(approval.id)})

    # ── plan view ──────────────────────────────────────────────────────────

    def _approval_view(self, a: Approval, names: dict[str, str]) -> dict[str, Any]:
        return {
            "id": str(a.id),
            "number": a.number,
            "status": a.status,
            "rationale": a.rationale,
            "proposed_by": _s(a.proposed_by),
            "proposed_by_name": names.get(_s(a.proposed_by) or "", ""),
            "proposed_at": a.proposed_at.isoformat() if a.proposed_at else None,
            "approved_by": _s(a.approved_by),
            "approved_by_name": names.get(_s(a.approved_by) or "", ""),
            "approved_at": a.approved_at.isoformat() if a.approved_at else None,
            "approval_source": a.approval_source,
            "four_eyes": a.four_eyes,
            "blocked_reason": a.approval_blocked_reason or None,
            "snapshot_hash": a.snapshot_hash,
            "key_figures": (a.snapshot or {}).get("key_figures"),
            "frame_total": (a.snapshot or {}).get("frame_total"),
        }

    async def plan_view(
        self, project_id: uuid.UUID, *, actor_id: uuid.UUID | None, can_edit: bool, can_manage: bool
    ) -> dict[str, Any]:
        await self.sync_with_governance(project_id)
        plan = await self.repo.plan(project_id)
        if plan is None:
            return {"exists": False, "can": {"edit": can_edit, "manage": can_manage}}
        gates = await hosting.gates_in_use(self.session, project_id)
        blocks = await self.action_blocks(plan, actor_id)
        ready = await self.readiness(project_id)
        carrier_reason = None
        if gates:
            doc, carrier_reason = await hosting.carrier_document(self.session, project_id)
            carrier_reason = None if doc is not None else carrier_reason
        approvals = await self.repo.approvals(project_id)
        names = await self._names({u for a in approvals for u in (a.proposed_by, a.approved_by) if u})
        return {
            "exists": True,
            "id": str(plan.id),
            "status": plan.status,
            "currency": plan.currency,
            "classification_standard": plan.classification_standard,
            "discount_rate_pct": ratio(plan.discount_rate_pct, "0.0001")
            if plan.discount_rate_pct is not None
            else None,
            "horizon_years": plan.horizon_years,
            "markup_allowance": money(plan.markup_allowance),
            "boq_id": _s(plan.boq_id),
            "gates_in_use": gates,
            "carrier_reason": carrier_reason,
            "editable": plan.status in EDITABLE,
            "blocks": blocks,
            "readiness": ready,
            "approvals": [self._approval_view(a, names) for a in approvals],
            "can": {"edit": can_edit and plan.status in EDITABLE, "manage": can_manage, "records": can_edit},
        }
