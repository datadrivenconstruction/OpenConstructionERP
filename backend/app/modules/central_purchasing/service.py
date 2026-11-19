# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Central purchasing service: bundles, shares, the live award split, the award and call-offs.

The award drafts documents and signs nothing (a person approves each one):

* ``per_project_contracts``: one contract (subcontract) or purchase order (supply) per project,
  each project being run by one legal entity, so one per (project, entity). Every document line
  carries the share quantity, the awarded rate and the share's cost line, so the document reaches
  exactly its own project's committed figure.
* ``framework_call_off``: one framework agreement per own legal entity (``contract_type`` framework,
  no cost lines, so it commits nothing), then call-offs from that entity's projects: a ``call_off``
  contract under the agreement, or a purchase order with ``po_type="call_off"``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.engine import validation_engine
from app.core.validation.messages import translate
from app.modules.central_purchasing import catalog
from app.modules.central_purchasing.models import AwardSplit, Bundle, BundleLine, BundleProject, LineShare
from app.modules.central_purchasing.repository import BundleRepository
from app.modules.central_purchasing.schemas import (
    AwardRequest,
    BundleCreate,
    BundleDetail,
    BundleSummary,
    BundleUpdate,
    CallOffRequest,
    CallOffResult,
    Catalogue,
    CostLineOption,
    DocumentRef,
    Finding,
    LineOut,
    LineUpdate,
    MyShare,
    MyShareLine,
    PreviewRequest,
    ProjectAdd,
    ProjectOut,
    ProjectUpdate,
    ShareIn,
    ShareOut,
    SplitOut,
    SplitRow,
)
from app.modules.central_purchasing.schemas import LineIn as LineInSchema
from app.modules.central_purchasing.split import (
    LineIn,
    SplitResult,
    budget_check,
    document_rate,
    round2,
    split_award,
)
from app.modules.central_purchasing.validators import RULE_SET

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
EDITABLE = ("draft", "published")
_PO_ISSUED = ("issued", "partially_received", "completed")
_CONTRACT_UNBOUND = ("draft", "cancelled", "void")
SOURCE = "central_purchasing.award"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _norm_code(value: str | None) -> str:
    return "".join(str(value or "").split()).upper().removeprefix("KG")


@dataclass
class _Ctx:
    """What one bundle reads from other modules, loaded once per request."""

    projects: dict[uuid.UUID, Any] = field(default_factory=dict)
    entities: dict[uuid.UUID, Any] = field(default_factory=dict)
    cost_codes: dict[uuid.UUID, str] = field(default_factory=dict)
    budgets: dict[uuid.UUID, Decimal | None] = field(default_factory=dict)
    entities_exist: bool = False

    def project_name(self, bp: BundleProject) -> str:
        p = self.projects.get(bp.project_id)
        return str(getattr(p, "name", "") or bp.project_id)

    def entity_name(self, bp: BundleProject) -> str | None:
        e = self.entities.get(bp.legal_entity_id) if bp.legal_entity_id else None
        return str(e.name) if e is not None else None


class CentralPurchasingService:
    """Stateless operations over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BundleRepository(session)

    # ── Bundles ─────────────────────────────────────────────────────────────

    async def get(self, bundle_id: uuid.UUID) -> Bundle:
        row = await self.repo.get(bundle_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bundle not found")
        return row

    async def create(self, data: BundleCreate, user_id: str) -> Bundle:
        row = Bundle(
            code=await self.repo.next_code(),
            title=data.title,
            description=data.description,
            kind=data.kind,
            mode=data.mode,
            currency=data.currency.upper()[:3],
            cost_code_standard=data.cost_code_standard,
            budget_tolerance_pct=data.budget_tolerance_pct,
            created_by=str(user_id),
            status="draft",
            projects=[],
            lines=[],
        )
        self.session.add(row)
        await self.session.flush()
        return row

    @staticmethod
    def _editable(row: Bundle) -> None:
        if row.status not in EDITABLE:
            raise HTTPException(status.HTTP_409_CONFLICT, "An awarded or cancelled bundle cannot be changed")

    async def update(self, row: Bundle, data: BundleUpdate) -> Bundle:
        self._editable(row)
        values = data.model_dump(exclude_unset=True, exclude={"clear_discount", "clear_lump_sum"})
        for key, value in values.items():
            if key == "currency" and value is not None:
                value = value.upper()[:3]
            setattr(row, key, value)
        if data.clear_discount:
            row.discount_pct = None
        if data.clear_lump_sum:
            row.lump_sum = None
        if row.discount_pct is not None and row.lump_sum is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a discount or a lump sum, not both")
        await self.session.flush()
        return row

    async def delete(self, row: Bundle) -> None:
        if row.status == "awarded":
            raise HTTPException(status.HTTP_409_CONFLICT, "An awarded bundle cannot be deleted")
        await self.session.delete(row)
        await self.session.flush()

    # ── Projects ────────────────────────────────────────────────────────────

    async def add_project(self, row: Bundle, data: ProjectAdd) -> BundleProject:
        self._editable(row)
        if any(bp.project_id == data.project_id for bp in row.projects):
            raise HTTPException(status.HTTP_409_CONFLICT, "The project is already in this bundle")
        project = (await self.repo.projects([data.project_id])).get(data.project_id)
        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
        bp = BundleProject(
            project_id=data.project_id,
            legal_entity_id=getattr(project, "legal_entity_id", None),
            budget_amount=data.budget_amount,
            order_index=len(row.projects),
        )
        row.projects.append(bp)
        if not row.currency:
            row.currency = str(getattr(project, "currency", "") or "").upper()[:3]
        await self.session.flush()
        return bp

    def _bundle_project(self, row: Bundle, bp_id: uuid.UUID) -> BundleProject:
        for bp in row.projects:
            if bp.id == bp_id:
                return bp
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project is not part of this bundle")

    async def update_project(self, row: Bundle, bp_id: uuid.UUID, data: ProjectUpdate) -> BundleProject:
        self._editable(row)
        bp = self._bundle_project(row, bp_id)
        if data.clear_budget:
            bp.budget_amount = None
        elif data.budget_amount is not None:
            bp.budget_amount = data.budget_amount
        await self.session.flush()
        return bp

    async def remove_project(self, row: Bundle, bp_id: uuid.UUID) -> None:
        self._editable(row)
        bp = self._bundle_project(row, bp_id)
        for line in row.lines:
            for share in [s for s in line.shares if s.bundle_project_id == bp.id]:
                line.shares.remove(share)
        row.projects.remove(bp)
        await self.session.flush()

    # ── Lines and shares ────────────────────────────────────────────────────

    async def add_line(self, row: Bundle, data: LineInSchema) -> BundleLine:
        self._editable(row)
        line = BundleLine(
            order_index=len(row.lines),
            code=data.code,
            description=data.description,
            unit=data.unit,
            quantity=data.quantity,
            unit_rate=data.unit_rate,
            cost_code=data.cost_code,
            shares=[],
        )
        row.lines.append(line)
        await self.session.flush()
        await self._apply_shares(row, line, data.shares or [])
        return line

    def _line(self, row: Bundle, line_id: uuid.UUID) -> BundleLine:
        for line in row.lines:
            if line.id == line_id:
                return line
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")

    async def update_line(self, row: Bundle, line_id: uuid.UUID, data: LineUpdate) -> BundleLine:
        self._editable(row)
        line = self._line(row, line_id)
        for key, value in data.model_dump(exclude_unset=True, exclude={"shares", "clear_rate"}).items():
            if value is not None:
                setattr(line, key, value)
        if data.clear_rate:
            line.unit_rate = None
        if data.shares is not None:
            await self._apply_shares(row, line, data.shares)
        await self.session.flush()
        return line

    async def delete_line(self, row: Bundle, line_id: uuid.UUID) -> None:
        self._editable(row)
        row.lines.remove(self._line(row, line_id))
        for i, line in enumerate(row.lines):
            line.order_index = i
        await self.session.flush()

    async def _apply_shares(self, row: Bundle, line: BundleLine, shares: list[ShareIn]) -> None:
        """Upsert shares; a share without a cost line takes the project's line whose code matches the line's."""
        by_project = {s.bundle_project_id: s for s in line.shares}
        for item in shares:
            bp = self._bundle_project(row, item.bundle_project_id)
            share = by_project.get(bp.id)
            if share is None:
                share = LineShare(bundle_project_id=bp.id)
                line.shares.append(share)
                by_project[bp.id] = share
            share.quantity = item.quantity
            cost_line_id = item.cost_line_id
            if cost_line_id is None and share.cost_line_id is None and line.cost_code:
                cost_line_id = await self._match_cost_line(bp.project_id, line.cost_code)
            if cost_line_id is not None or "cost_line_id" in item.model_fields_set:
                share.cost_line_id = cost_line_id
        await self.session.flush()

    async def _match_cost_line(self, project_id: uuid.UUID, cost_code: str) -> uuid.UUID | None:
        wanted = _norm_code(cost_code)
        if not wanted:
            return None
        matches = [c for c in await self.repo.cost_lines(project_id) if _norm_code(c.code) == wanted]
        return matches[0].id if len(matches) == 1 else None

    async def cost_line_options(self, project_id: uuid.UUID) -> list[CostLineOption]:
        return [
            CostLineOption(id=c.id, code=c.code, description=(c.description or "")[:200])
            for c in await self.repo.cost_lines(project_id)
        ]

    # ── Split and findings ──────────────────────────────────────────────────

    async def _context(self, row: Bundle) -> _Ctx:
        ctx = _Ctx()
        ctx.projects = await self.repo.projects([bp.project_id for bp in row.projects])
        ctx.entities = await self.repo.entities([bp.legal_entity_id for bp in row.projects if bp.legal_entity_id])
        ctx.entities_exist = await self.repo.entities_exist()
        ctx.cost_codes = await self.repo.cost_line_codes(
            [s.cost_line_id for ln in row.lines for s in ln.shares if s.cost_line_id]
        )
        for bp in row.projects:
            if bp.budget_amount is not None:
                ctx.budgets[bp.id] = bp.budget_amount
            else:
                ids = [s.cost_line_id for ln in row.lines for s in ln.shares if s.bundle_project_id == bp.id]
                ctx.budgets[bp.id] = await self.repo.planned_budget(bp.project_id, ids)
        return ctx

    @staticmethod
    def _split_lines(row: Bundle, rates: dict[uuid.UUID, Decimal] | None = None) -> list[LineIn]:
        out = []
        for i, line in enumerate(row.lines):
            shares: dict[Any, Decimal | None] = {s.bundle_project_id: s.quantity for s in line.shares}
            rate = (rates or {}).get(line.id, line.unit_rate)
            out.append(LineIn(line.id, line.code or f"#{i + 1}", line.unit, line.quantity, rate, shares))
        return out

    def _split(
        self,
        row: Bundle,
        *,
        discount: Decimal | None = None,
        lump: Decimal | None = None,
        rates: dict[uuid.UUID, Decimal] | None = None,
    ) -> SplitResult:
        return split_award(
            self._split_lines(row, rates),
            [bp.id for bp in row.projects],
            discount_pct=discount,
            lump_sum=lump,
        )

    def _payload(self, row: Bundle, ctx: _Ctx, split: SplitResult, *, awarded: bool) -> dict[str, Any]:
        names = {bp.id: ctx.project_name(bp) for bp in row.projects}
        priced = any(ln.unit_rate is not None for ln in row.lines)
        payload: dict[str, Any] = {
            "currency": row.currency,
            "entities_exist": ctx.entities_exist,
            "tolerance_pct": str(row.budget_tolerance_pct or ZERO),
            "lines": [
                {
                    "code": line.code or f"#{i + 1}",
                    "unit": line.unit,
                    "quantity": str(line.quantity),
                    "shares": [
                        {
                            "project": names[bp.id],
                            "quantity": None
                            if (s := self._share(line, bp.id)) is None or s.quantity is None
                            else str(s.quantity),
                            "cost_line_id": str(s.cost_line_id) if s is not None and s.cost_line_id else None,
                        }
                        for bp in row.projects
                    ],
                }
                for i, line in enumerate(row.lines)
            ],
            "projects": [
                {
                    "name": names[bp.id],
                    "legal_entity_id": str(bp.legal_entity_id) if bp.legal_entity_id else None,
                    "net": str(split.projects[bp.id].net) if priced else None,
                    "budget": str(ctx.budgets.get(bp.id)) if ctx.budgets.get(bp.id) is not None else None,
                }
                for bp in row.projects
            ],
        }
        if awarded and row.awarded_net is not None:
            payload["award"] = {"total": str(row.awarded_net), "split_sum": None}
        elif priced:
            payload["award"] = {"total": str(split.target), "split_sum": str(split.net)}
        return payload

    @staticmethod
    def _share(line: BundleLine, bp_id: uuid.UUID) -> LineShare | None:
        return next((s for s in line.shares if s.bundle_project_id == bp_id), None)

    async def _run_rules(self, payload: dict[str, Any], target_id: str) -> list[Finding]:
        report = await validation_engine.validate(
            data=payload,
            rule_sets=[RULE_SET],
            target_type="central_purchasing_bundle",
            target_id=target_id,
            metadata={"locale": get_locale()},
        )
        return [
            Finding(
                rule_id=r.rule_id,
                severity=r.severity.value,
                message=r.message,
                suggestion=r.suggestion,
                element_ref=r.element_ref,
            )
            for r in report.results
            if not r.passed and not r.is_engine_error
        ]

    async def _blocked_finding(self, subcontractor_id: uuid.UUID | None, vendor: str) -> Finding | None:
        sub = await self.repo.subcontractor(subcontractor_id)
        if sub is None or not getattr(sub, "is_blocked", False):
            return None
        locale = get_locale()
        name = vendor or str(getattr(sub, "company_name", "") or getattr(sub, "name", "") or "")
        return Finding(
            rule_id="award.bidder_blocked",
            severity="error",
            message=translate(f"{RULE_SET}.bidder_blocked.fail", locale=locale, vendor=name),
            suggestion=translate(f"{RULE_SET}.bidder_blocked.suggestion", locale=locale),
            element_ref=f"subcontractor:{subcontractor_id}",
        )

    async def findings(self, row: Bundle, ctx: _Ctx, split: SplitResult) -> list[Finding]:
        out = await self._run_rules(self._payload(row, ctx, split, awarded=row.status == "awarded"), str(row.id))
        if row.status == "awarded" and row.awarded_net is not None:
            stored = sum((s.net for s in await self.repo.splits(row.id)), ZERO)
            out = [f for f in out if f.rule_id != f"{RULE_SET}.award_split_unreconciled"]
            out += await self._run_rules(
                {"currency": row.currency, "award": {"total": str(row.awarded_net), "split_sum": str(stored)}},
                str(row.id),
            )
        blocked = await self._blocked_finding(row.subcontractor_id, row.vendor_name)
        if blocked is not None and row.status != "awarded":
            out.append(blocked)
        return out

    # ── Reads ───────────────────────────────────────────────────────────────

    async def _doc_ref(self, doc_type: str, doc_id: uuid.UUID | None) -> DocumentRef | None:
        if doc_id is None:
            return None
        if doc_type == "purchase_order":
            from app.modules.procurement.models import PurchaseOrder

            po = await self.session.get(PurchaseOrder, doc_id)
            if po is None:
                return DocumentRef(type=doc_type, id=doc_id)
            return DocumentRef(type=doc_type, id=po.id, code=po.po_number, status=po.status, project_id=po.project_id)
        from app.modules.contracts.models import Contract

        c = await self.session.get(Contract, doc_id)
        if c is None:
            return DocumentRef(type=doc_type, id=doc_id)
        return DocumentRef(type=doc_type, id=c.id, code=c.code, status=c.status, project_id=c.project_id)

    def _terms(self, row: Bundle, preview: PreviewRequest | None) -> tuple[Decimal | None, Decimal | None, dict]:
        if preview is None:
            return row.discount_pct, row.lump_sum, {}
        if preview.discount_pct is not None and preview.lump_sum is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a discount or a lump sum, not both")
        return preview.discount_pct, preview.lump_sum, dict(preview.rates)

    async def detail(self, row: Bundle, preview: PreviewRequest | None = None) -> BundleDetail:
        ctx = await self._context(row)
        discount, lump, rates = self._terms(row, preview)
        split = self._split(row, discount=discount, lump=lump, rates=rates)
        stored = {s.bundle_project_id: s for s in await self.repo.splits(row.id)} if row.status == "awarded" else {}
        tol = row.budget_tolerance_pct or ZERO
        rows: list[SplitRow] = []
        for bp in row.projects:
            ps = split.projects[bp.id]
            gross, net = ps.gross, ps.net
            saved = stored.get(bp.id)
            if saved is not None:
                gross, net = saved.gross, saved.net
            budget = ctx.budgets.get(bp.id)
            check = budget_check(net, budget, tol)
            rows.append(
                SplitRow(
                    bundle_project_id=bp.id,
                    project_name=ctx.project_name(bp),
                    legal_entity_name=ctx.entity_name(bp),
                    gross=gross,
                    discount=gross - net,
                    net=net,
                    budget=budget,
                    over_budget=check.over,
                    budget_delta=check.delta if budget is not None else None,
                    document=await self._doc_ref(saved.document_type, saved.document_id) if saved else None,
                )
            )
        agreements: list[DocumentRef] = []
        if row.mode == "framework_call_off":
            seen: set[uuid.UUID] = set()
            for saved in stored.values():
                if saved.document_id and saved.document_id not in seen:
                    seen.add(saved.document_id)
                    ref = await self._doc_ref("framework_agreement", saved.document_id)
                    if ref is not None:
                        agreements.append(ref)
        shares_out = {
            line.id: [
                ShareOut(
                    id=s.id,
                    bundle_project_id=s.bundle_project_id,
                    quantity=s.quantity,
                    cost_line_id=s.cost_line_id,
                    cost_line_code=ctx.cost_codes.get(s.cost_line_id) if s.cost_line_id else None,
                )
                for s in line.shares
            ]
            for line in row.lines
        }
        return BundleDetail(
            id=row.id,
            code=row.code,
            title=row.title,
            description=row.description,
            kind=row.kind,
            mode=row.mode,
            status=row.status,
            currency=row.currency,
            cost_code_standard=row.cost_code_standard,
            budget_tolerance_pct=tol,
            vendor_name=row.vendor_name,
            subcontractor_id=row.subcontractor_id,
            contact_id=row.contact_id,
            discount_pct=row.discount_pct,
            lump_sum=row.lump_sum,
            awarded_at=row.awarded_at,
            projects=[
                ProjectOut(
                    id=bp.id,
                    project_id=bp.project_id,
                    name=ctx.project_name(bp),
                    project_code=getattr(ctx.projects.get(bp.project_id), "project_code", None),
                    legal_entity_id=bp.legal_entity_id,
                    legal_entity_name=ctx.entity_name(bp),
                    budget_amount=bp.budget_amount,
                    budget_from_lines=ctx.budgets.get(bp.id) if bp.budget_amount is None else None,
                )
                for bp in row.projects
            ],
            lines=[
                LineOut(
                    id=line.id,
                    order_index=line.order_index,
                    code=line.code,
                    description=line.description,
                    unit=line.unit,
                    quantity=line.quantity,
                    unit_rate=rates.get(line.id, line.unit_rate),
                    cost_code=line.cost_code,
                    shares=shares_out[line.id],
                    share_sum=sum((s.quantity or ZERO for s in line.shares), ZERO),
                )
                for line in row.lines
            ],
            split=SplitOut(
                method="lump_sum" if lump is not None else "unit_rates",
                gross=split.gross,
                net=split.net,
                target=split.target,
                reconciles=split.reconciles,
                rows=rows,
                cells={f"{k[0]}:{k[1]}": {"gross": c.gross, "net": c.net} for k, c in split.cells.items()},
            ),
            findings=await self.findings(row, ctx, split),
            agreements=agreements,
        )

    async def summaries(self) -> list[BundleSummary]:
        out = []
        for row in await self.repo.list():
            ctx = await self._context(row)
            split = self._split(row, discount=row.discount_pct, lump=row.lump_sum)
            found = await self.findings(row, ctx, split)
            out.append(
                BundleSummary(
                    id=row.id,
                    code=row.code,
                    title=row.title,
                    kind=row.kind,
                    mode=row.mode,
                    status=row.status,
                    currency=row.currency,
                    vendor_name=row.vendor_name,
                    project_count=len(row.projects),
                    line_count=len(row.lines),
                    gross=row.awarded_gross if row.awarded_gross is not None else split.gross,
                    net=row.awarded_net if row.awarded_net is not None else split.net,
                    errors=sum(1 for f in found if f.severity == "error"),
                    warnings=sum(1 for f in found if f.severity == "warning"),
                    updated_at=row.updated_at,
                )
            )
        return out

    async def catalogues(self, row: Bundle | None) -> list[Catalogue]:
        countries: list[str | None] = list(await self.repo.entity_countries())
        if row is not None:
            projects = await self.repo.projects([bp.project_id for bp in row.projects])
            countries += [getattr(p, "country_code", None) for p in projects.values()]
        return [Catalogue(**c) for c in catalog.catalogues_for(countries)]

    # ── Publish and award ───────────────────────────────────────────────────

    @staticmethod
    def _raise_on_errors(found: list[Finding]) -> None:
        errors = [f for f in found if f.severity == "error"]
        if errors:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"error": "bundle_blocked", "findings": [f.model_dump() for f in errors]},
            )

    def _require_scope(self, row: Bundle) -> None:
        if not row.projects or not row.lines:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add at least one project and one line")

    async def publish(self, row: Bundle) -> Bundle:
        if row.status != "draft":
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft bundle can be published")
        self._require_scope(row)
        ctx = await self._context(row)
        split = self._split(row, discount=row.discount_pct, lump=row.lump_sum)
        found = await self._run_rules(self._payload(row, ctx, split, awarded=False), str(row.id))
        self._raise_on_errors([f for f in found if not f.rule_id.endswith("award_split_unreconciled")])
        row.status = "published"
        await self.session.flush()
        return row

    async def award(self, row: Bundle, req: AwardRequest, user_id: str) -> Bundle:
        self._editable(row)
        self._require_scope(row)
        if req.discount_pct is not None and req.lump_sum is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a discount or a lump sum, not both")
        if any(line.unit_rate is None for line in row.lines):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Every line needs its awarded rate")
        row.vendor_name = req.vendor_name
        row.subcontractor_id = req.subcontractor_id
        row.contact_id = req.contact_id
        row.discount_pct = req.discount_pct
        row.lump_sum = req.lump_sum

        blocked = await self._blocked_finding(row.subcontractor_id, row.vendor_name)
        if blocked is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, {"error": "bidder_blocked", "findings": [blocked.model_dump()]}
            )
        ctx = await self._context(row)
        split = self._split(row, discount=row.discount_pct, lump=row.lump_sum)
        found = await self._run_rules(self._payload(row, ctx, split, awarded=False), str(row.id))
        self._raise_on_errors(found)

        from app.modules.bid_management.award_contract import resolve_award_counterparty

        cp = await resolve_award_counterparty(
            self.session,
            subcontractor_id=row.subcontractor_id,
            contact_id=row.contact_id,
            company_name=row.vendor_name,
        )
        for bp in row.projects:
            if bp.budget_amount is None:
                bp.budget_amount = ctx.budgets.get(bp.id)

        if row.mode == "framework_call_off":
            docs = await self._draft_agreements(row, ctx, split, cp, user_id)
            doc_type = "call_off_ceiling"
        else:
            docs = {}
            for n, bp in enumerate(row.projects, start=1):
                if split.projects[bp.id].net == ZERO and split.projects[bp.id].gross == ZERO:
                    continue
                if row.kind == "supply":
                    docs[bp.id] = await self._draft_po(row, bp, ctx, split, cp, user_id)
                else:
                    docs[bp.id] = await self._draft_contract(row, bp, ctx, split, cp, n, user_id)
            doc_type = "purchase_order" if row.kind == "supply" else "contract"

        for bp in row.projects:
            ps = split.projects[bp.id]
            self.session.add(
                AwardSplit(
                    bundle_id=row.id,
                    bundle_project_id=bp.id,
                    gross=ps.gross,
                    discount=ps.discount,
                    net=ps.net,
                    document_type=doc_type,
                    document_id=docs.get(bp.id),
                )
            )
        row.awarded_gross = split.gross
        row.awarded_net = split.net
        row.awarded_at = _now()
        row.awarded_by = str(user_id)
        row.status = "awarded"
        await self.session.flush()
        logger.info(
            "Bundle %s awarded to %s: %s net over %d project(s)", row.code, row.vendor_name, split.net, len(docs)
        )
        return row

    def _meta(self, row: Bundle, bp: BundleProject) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "source": SOURCE,
            "bundle_id": str(row.id),
            "bundle_code": row.code,
            "bundle_share_id": str(bp.id),
            "legal_entity_id": str(bp.legal_entity_id) if bp.legal_entity_id else None,
            "awarded_vendor": row.vendor_name,
        }
        if row.bid_package_id:
            meta["bid_package_id"] = str(row.bid_package_id)
        return meta

    def _doc_lines(self, row: Bundle, bp: BundleProject, split: SplitResult) -> list[dict[str, Any]]:
        out = []
        for line in row.lines:
            share = self._share(line, bp.id)
            cell = split.cells.get((line.id, bp.id))
            if share is None or not share.quantity or cell is None:
                continue
            out.append(
                {
                    "line": line,
                    "quantity": share.quantity,
                    "rate": document_rate(line.unit_rate or ZERO, split.factor),
                    "total": cell.net,
                    "gross": cell.gross,
                    "cost_line_id": share.cost_line_id,
                }
            )
        return out

    async def _add_parties(self, contract_id: uuid.UUID, bp: BundleProject | None, ctx: _Ctx, cp: Any) -> None:
        from app.modules.bid_management.award_contract import add_award_party
        from app.modules.contracts.models import ContractParty

        add_award_party(self.session, contract_id, cp)
        entity = ctx.entities.get(bp.legal_entity_id) if bp is not None and bp.legal_entity_id else None
        if entity is not None:
            self.session.add(
                ContractParty(
                    contract_id=contract_id,
                    party_role="employer",
                    party_type="legal_entity",
                    party_id=entity.id,
                    display_name=str(entity.legal_name or entity.name)[:500],
                    is_primary=True,
                )
            )

    async def _draft_contract(
        self, row: Bundle, bp: BundleProject, ctx: _Ctx, split: SplitResult, cp: Any, n: int, user_id: str
    ) -> uuid.UUID:
        from app.modules.bid_management.award_contract import free_contract_code
        from app.modules.contracts.models import Contract, ContractLine

        code = await free_contract_code(self.session, f"{row.code}-{n:02d}")
        contract = Contract(
            code=code,
            title=row.title[:500],
            contract_type="lump_sum" if row.lump_sum is not None else "unit_price",
            counterparty_type="subcontractor",
            counterparty_id=cp.counterparty_id,
            project_id=bp.project_id,
            currency=row.currency,
            total_value=split.projects[bp.id].net,
            status="draft",
            created_by=str(user_id),
            metadata_=self._meta(row, bp),
        )
        self.session.add(contract)
        await self.session.flush()
        for i, item in enumerate(self._doc_lines(row, bp, split)):
            line: BundleLine = item["line"]
            self.session.add(
                ContractLine(
                    contract_id=contract.id,
                    code=line.code[:80],
                    description=line.description,
                    unit=line.unit[:20] or None,
                    quantity=item["quantity"],
                    unit_rate=item["rate"],
                    total_value=item["total"],
                    cost_line_id=item["cost_line_id"],
                    order_index=i,
                    metadata_={
                        "bundle_line_id": str(line.id),
                        "awarded_rate": str(line.unit_rate),
                        "gross": str(item["gross"]),
                    },
                )
            )
        await self._add_parties(contract.id, bp, ctx, cp)
        return contract.id

    async def _draft_po(
        self, row: Bundle, bp: BundleProject, ctx: _Ctx, split: SplitResult, cp: Any, user_id: str
    ) -> uuid.UUID:
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
        from app.modules.procurement.repository import PurchaseOrderRepository

        net = split.projects[bp.id].net
        po = PurchaseOrder(
            project_id=bp.project_id,
            vendor_contact_id=str(cp.contact_id) if cp.contact_id else None,
            po_number=await PurchaseOrderRepository(self.session).next_po_number(bp.project_id),
            po_type="standard",
            currency_code=row.currency,
            amount_subtotal=format(net, "f"),
            tax_amount="0",
            amount_total=format(net, "f"),
            status="draft",
            created_by=uuid.UUID(str(user_id)) if user_id else None,
            metadata_={**self._meta(row, bp), "supplier_name": row.vendor_name},
        )
        self.session.add(po)
        await self.session.flush()
        for i, item in enumerate(self._doc_lines(row, bp, split)):
            line: BundleLine = item["line"]
            self.session.add(
                PurchaseOrderItem(
                    po_id=po.id,
                    description=(f"{line.code} {line.description}".strip() or line.code)[:500],
                    quantity=format(item["quantity"], "f"),
                    unit=line.unit[:20] or None,
                    unit_rate=format(item["rate"], "f"),
                    amount=format(item["total"], "f"),
                    cost_line_id=item["cost_line_id"],
                    sort_order=i,
                )
            )
        return po.id

    async def _draft_agreements(
        self, row: Bundle, ctx: _Ctx, split: SplitResult, cp: Any, user_id: str
    ) -> dict[uuid.UUID, uuid.UUID]:
        """One framework agreement per own legal entity; cap = that entity's awarded net."""
        from app.modules.bid_management.award_contract import free_contract_code
        from app.modules.contracts.models import Contract

        groups: dict[uuid.UUID | None, list[BundleProject]] = {}
        for bp in row.projects:
            groups.setdefault(bp.legal_entity_id, []).append(bp)
        docs: dict[uuid.UUID, uuid.UUID] = {}
        for n, (entity_id, members) in enumerate(groups.items(), start=1):
            cap = sum((split.projects[bp.id].net for bp in members), ZERO)
            entity = ctx.entities.get(entity_id) if entity_id else None
            meta = {**self._meta(row, members[0]), "bundle_share_id": None, "bundle_role": "framework_agreement"}
            meta["legal_entity_id"] = str(entity_id) if entity_id else None
            agreement = Contract(
                code=await free_contract_code(self.session, f"{row.code}-FA{n:02d}"),
                title=row.title[:500],
                contract_type="framework",
                counterparty_type="subcontractor",
                counterparty_id=cp.counterparty_id,
                # A contract needs a project; the entity's first bundle project holds it. It has no
                # cost lines, so it commits nothing there.
                project_id=members[0].project_id,
                currency=row.currency,
                total_value=cap,
                retention_percent=ZERO,
                status="draft",
                created_by=str(user_id),
                terms={
                    "cap_value": format(cap, "f"),
                    "cap_basis": "committed",
                    "buyer_entity": str(getattr(entity, "name", "") or ""),
                    "projects": [str(bp.project_id) for bp in members],
                },
                metadata_=meta,
            )
            self.session.add(agreement)
            await self.session.flush()
            await self._add_parties(agreement.id, members[0], ctx, cp)
            await self._add_rate_items(row, agreement.id, members, split)
            for bp in members:
                docs[bp.id] = agreement.id
        return docs

    async def _add_rate_items(
        self, row: Bundle, agreement_id: uuid.UUID, members: list[BundleProject], split: SplitResult
    ) -> None:
        try:
            from app.modules.framework_agreements.models import FrameworkRateItem
        except ImportError:  # pragma: no cover - plugin not installed
            return
        ids = {bp.id for bp in members}
        for i, line in enumerate(row.lines):
            qty = sum((s.quantity or ZERO for s in line.shares if s.bundle_project_id in ids), ZERO)
            self.session.add(
                FrameworkRateItem(
                    agreement_id=agreement_id,
                    code=(line.code or f"#{i + 1}")[:80],
                    description=line.description,
                    unit=line.unit[:20],
                    base_rate=document_rate(line.unit_rate or ZERO, split.factor),
                    classification=line.cost_code,
                    max_qty=qty,
                    estimated_qty=qty,
                    source="manual",
                    sort_order=i,
                )
            )

    # ── Call-offs ───────────────────────────────────────────────────────────

    async def _called_off(self, row: Bundle, project_id: uuid.UUID) -> dict[str, Decimal]:
        """F5: quantities already called off per line, counting issued orders and active contracts."""
        from app.modules.contracts.models import Contract
        from app.modules.procurement.models import PurchaseOrder

        used: dict[str, Decimal] = {}
        docs: list[dict] = []
        if row.kind == "supply":
            q = select(PurchaseOrder.metadata_).where(
                PurchaseOrder.project_id == project_id,
                PurchaseOrder.po_type == "call_off",
                PurchaseOrder.status.in_(_PO_ISSUED),
            )
        else:
            q = select(Contract.metadata_).where(
                Contract.project_id == project_id,
                Contract.contract_type == "call_off",
                Contract.status.not_in(_CONTRACT_UNBOUND),
            )
        docs = [m for m in (await self.session.execute(q)).scalars().all() if isinstance(m, dict)]
        for meta in docs:
            if meta.get("bundle_id") != str(row.id):
                continue
            for line_id, qty in (meta.get("bundle_call_off") or {}).items():
                used[line_id] = used.get(line_id, ZERO) + Decimal(str(qty))
        return used

    async def call_off(self, row: Bundle, req: CallOffRequest, user_id: str) -> CallOffResult:
        if row.mode != "framework_call_off" or row.status != "awarded":
            raise HTTPException(status.HTTP_409_CONFLICT, "Call-offs need an awarded framework bundle")
        bp = next((b for b in row.projects if b.project_id == req.project_id), None)
        if bp is None:
            projects = await self.repo.projects([req.project_id])
            name = str(getattr(projects.get(req.project_id), "name", "") or req.project_id)
            found = await self._run_rules({"call_off": {"project": name, "in_bundle": False}}, str(row.id))
            self._raise_on_errors(found)
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Project is not part of this bundle")
        ctx = await self._context(row)
        split_row = next((s for s in await self.repo.splits(row.id) if s.bundle_project_id == bp.id), None)
        if split_row is None or split_row.document_id is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "The project has no framework agreement")
        factor = self._split(row, discount=row.discount_pct, lump=row.lump_sum).factor
        used = await self._called_off(row, bp.project_id)
        items, check_lines = [], []
        for req_line in req.lines:
            line = self._line(row, req_line.line_id)
            share = self._share(line, bp.id)
            rate = document_rate(line.unit_rate or ZERO, factor)
            items.append((line, req_line.quantity, rate, round2(req_line.quantity * rate), share))
            check_lines.append(
                {
                    "code": line.code,
                    "unit": line.unit,
                    "used": str(used.get(str(line.id), ZERO) + req_line.quantity),
                    "share": str(share.quantity if share and share.quantity is not None else ZERO),
                }
            )
        found = await self._run_rules(
            {"call_off": {"project": ctx.project_name(bp), "in_bundle": True, "lines": check_lines}}, str(row.id)
        )
        total = sum((i[3] for i in items), ZERO)
        meta = {
            **self._meta(row, bp),
            "framework_contract_id": str(split_row.document_id),
            "bundle_call_off": {str(i[0].id): format(i[1], "f") for i in items},
        }
        if row.kind == "supply":
            doc = await self._call_off_po(row, bp, items, total, meta, user_id)
        else:
            doc = await self._call_off_contract(row, bp, ctx, items, total, meta, split_row.document_id, user_id)
        return CallOffResult(document=doc, total=total, findings=found)

    async def _call_off_po(
        self, row: Bundle, bp: BundleProject, items: list, total: Decimal, meta: dict, user_id: str
    ) -> DocumentRef:
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
        from app.modules.procurement.repository import PurchaseOrderRepository

        po = PurchaseOrder(
            project_id=bp.project_id,
            vendor_contact_id=str(row.contact_id) if row.contact_id else None,
            po_number=await PurchaseOrderRepository(self.session).next_po_number(bp.project_id),
            po_type="call_off",
            currency_code=row.currency,
            amount_subtotal=format(total, "f"),
            tax_amount="0",
            amount_total=format(total, "f"),
            status="draft",
            created_by=uuid.UUID(str(user_id)) if user_id else None,
            metadata_={**meta, "supplier_name": row.vendor_name},
        )
        self.session.add(po)
        await self.session.flush()
        for i, (line, qty, rate, amount, share) in enumerate(items):
            self.session.add(
                PurchaseOrderItem(
                    po_id=po.id,
                    description=(f"{line.code} {line.description}".strip() or line.code)[:500],
                    quantity=format(qty, "f"),
                    unit=line.unit[:20] or None,
                    unit_rate=format(rate, "f"),
                    amount=format(amount, "f"),
                    cost_line_id=share.cost_line_id if share else None,
                    sort_order=i,
                )
            )
        await self.session.flush()
        return DocumentRef(
            type="purchase_order", id=po.id, code=po.po_number, status=po.status, project_id=po.project_id
        )

    async def _call_off_contract(
        self,
        row: Bundle,
        bp: BundleProject,
        ctx: _Ctx,
        items: list,
        total: Decimal,
        meta: dict,
        agreement_id: uuid.UUID,
        user_id: str,
    ) -> DocumentRef:
        from app.modules.bid_management.award_contract import free_contract_code, resolve_award_counterparty
        from app.modules.contracts.models import Contract, ContractLine

        agreement = await self.session.get(Contract, agreement_id)
        code = await free_contract_code(self.session, f"{getattr(agreement, 'code', row.code)}-CO")
        contract = Contract(
            code=code,
            title=row.title[:500],
            contract_type="call_off",
            counterparty_type="subcontractor",
            counterparty_id=getattr(agreement, "counterparty_id", None),
            project_id=bp.project_id,
            parent_contract_id=agreement_id,
            currency=row.currency,
            total_value=total,
            status="draft",
            created_by=str(user_id),
            metadata_=meta,
        )
        self.session.add(contract)
        await self.session.flush()
        for i, (line, qty, rate, amount, share) in enumerate(items):
            self.session.add(
                ContractLine(
                    contract_id=contract.id,
                    code=line.code[:80],
                    description=line.description,
                    unit=line.unit[:20] or None,
                    quantity=qty,
                    unit_rate=rate,
                    total_value=amount,
                    cost_line_id=share.cost_line_id if share else None,
                    order_index=i,
                    origin="framework_item",
                    metadata_={"bundle_line_id": str(line.id), "awarded_rate": str(line.unit_rate)},
                )
            )
        cp = await resolve_award_counterparty(
            self.session, subcontractor_id=row.subcontractor_id, contact_id=row.contact_id, company_name=row.vendor_name
        )
        await self._add_parties(contract.id, bp, ctx, cp)
        await self.session.flush()
        return DocumentRef(
            type="contract", id=contract.id, code=contract.code, status=contract.status, project_id=bp.project_id
        )

    # ── Project team view ───────────────────────────────────────────────────

    async def my_shares(self, project_id: uuid.UUID) -> list[MyShare]:
        """What one project's team may see: its share, its budget and its own document, nothing else."""
        out: list[MyShare] = []
        for membership in await self.repo.memberships(project_id):
            row = await self.repo.get(membership.bundle_id)
            if row is None or row.status not in ("published", "awarded"):
                continue
            ctx = await self._context(row)
            split = self._split(row, discount=row.discount_pct, lump=row.lump_sum)
            mine = split.projects[membership.id]
            saved = next((s for s in await self.repo.splits(row.id) if s.bundle_project_id == membership.id), None)
            gross, net = (saved.gross, saved.net) if saved else (mine.gross, mine.net)
            budget = ctx.budgets.get(membership.id)
            framework = row.mode == "framework_call_off" and saved is not None
            used = await self._called_off(row, project_id) if framework else {}
            lines = []
            for line in row.lines:
                share = self._share(line, membership.id)
                cell = split.cells.get((line.id, membership.id))
                lines.append(
                    MyShareLine(
                        code=line.code,
                        description=line.description,
                        unit=line.unit,
                        quantity=share.quantity if share else None,
                        rate=document_rate(line.unit_rate, split.factor) if line.unit_rate is not None else None,
                        net=cell.net if cell else None,
                        called_off=used.get(str(line.id), ZERO) if framework else None,
                    )
                )
            out.append(
                MyShare(
                    bundle_id=row.id,
                    code=row.code,
                    title=row.title,
                    status=row.status,
                    kind=row.kind,
                    mode=row.mode,
                    currency=row.currency,
                    vendor_name=row.vendor_name,
                    budget=budget,
                    gross=gross,
                    net=net,
                    over_budget=budget_check(net, budget, row.budget_tolerance_pct or ZERO).over,
                    lines=lines,
                    document=await self._doc_ref(saved.document_type, saved.document_id) if saved else None,
                )
            )
        return out


__all__ = ["CentralPurchasingService"]
