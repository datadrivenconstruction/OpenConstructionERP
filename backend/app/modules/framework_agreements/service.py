# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Framework agreement service: agreements, price list, rate periods, call-off orders, cap use.

An agreement is a ``Contract`` (``contract_type="framework"``) and an order is a ``Contract``
(``contract_type="call_off"``, ``parent_contract_id`` = agreement). Prices on an order come only
from the agreement (R5), are frozen when written (R6) and carry their build in
``ContractLine.metadata["rate_build"]``. Consumption is computed, never stored.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.engine import validation_engine
from app.dependencies import accessible_project_ids, verify_project_access
from app.modules.contracts.models import Contract, ContractLine
from app.modules.framework_agreements import pricing
from app.modules.framework_agreements.models import FrameworkAdjustment, FrameworkRateItem, FrameworkRatePeriod
from app.modules.framework_agreements.packs import pack_profile
from app.modules.framework_agreements.repository import (
    AGREEMENT,
    CALL_OFF,
    COMMITTED_STATUSES,
    FrameworkRepository,
)
from app.modules.framework_agreements.schemas import (
    AdjustmentIn,
    AgreementCreate,
    AgreementUpdate,
    Finding,
    OrderCreate,
    OrderQuoteRequest,
    RateItemIn,
    RateItemUpdate,
    RatePeriodIn,
)
from app.modules.framework_agreements.validators import RULE_SET

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
#: Minimum length of the reason that justifies issuing an order past the cap.
OVERRIDE_REASON_MIN = 20
_ORDER_TO_CONTRACT_STATUS = {
    "draft": "draft",
    "issued": "active",
    "in_progress": "active",
    "closed": "completed",
    "cancelled": "terminated",
}


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else ZERO
    except ArithmeticError:
        return ZERO


def _opt_d(value: Any) -> Decimal | None:
    return None if value in (None, "") else _d(value)


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _period_label(period: FrameworkRatePeriod | None) -> str:
    if period is None:
        return ""
    return period.label or period.effective_from.isoformat()


class FrameworkService:
    """Stateless operations over one session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FrameworkRepository(session)

    # ── Access ──────────────────────────────────────────────────────────────

    async def agreement(self, agreement_id: uuid.UUID, user_id: str) -> Contract:
        row = await self.session.get(Contract, agreement_id)
        if row is None or row.contract_type != AGREEMENT:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Framework agreement not found")
        await verify_project_access(row.project_id, user_id, self.session)
        return row

    async def order(self, order_id: uuid.UUID, user_id: str) -> tuple[Contract, Contract]:
        row = await self.session.get(Contract, order_id)
        if row is None or row.contract_type != CALL_OFF or row.parent_contract_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        return row, await self.agreement(row.parent_contract_id, user_id)

    # ── Agreements ──────────────────────────────────────────────────────────

    async def list_agreements(self, user_id: str, project_id: uuid.UUID | None) -> list[dict[str, Any]]:
        if project_id is not None:
            await verify_project_access(project_id, user_id, self.session)
            ids = None
        else:
            ids = await accessible_project_ids(self.session, user_id, live_only=True)
        rows = await self.repo.list_agreements(ids, project_id)
        use = await self.repo.consumption([r.id for r in rows])
        month = date.today().strftime("%Y-%m")
        this_month = await self.repo.orders_in_month([r.id for r in rows], month)
        out = [self._summary(r, use[r.id], this_month.get(r.id, 0)) for r in rows]
        out.sort(key=lambda s: -(s["consumption"]["pct"] or ZERO))
        return out

    def _summary(self, row: Contract, use: dict[str, Any], orders_this_month: int = 0) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "code": row.code,
            "title": row.title,
            "client_name": str((row.terms or {}).get("client_name") or ""),
            "status": self._agreement_status(row, use),
            "currency": row.currency,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "consumption": self._consumption(row, use),
            "orders_this_month": orders_this_month,
        }

    def _consumption(self, row: Contract, use: dict[str, Any]) -> dict[str, Any]:
        terms = row.terms or {}
        basis = str(terms.get("cap_basis") or "committed")
        cap = _opt_d(terms.get("cap_value"))
        tested = _d(use.get(basis))
        pct = headroom = None
        if cap and cap > 0:
            pct = (tested / cap * 100).quantize(Decimal("0.01"))
            headroom = pricing.round2(cap - tested)
        elapsed = None
        start, end = _date(row.start_date), _date(row.end_date)
        if start and end and end > start:
            days = (min(max(date.today(), start), end) - start).days
            elapsed = (Decimal(days * 100) / Decimal((end - start).days)).quantize(Decimal("0.1"))
        return {
            "cap": cap,
            "min_value": _opt_d(terms.get("min_value")),
            "committed": pricing.round2(_d(use.get("committed"))),
            "certified": pricing.round2(_d(use.get("certified"))),
            "invoiced": pricing.round2(_d(use.get("invoiced"))),
            "tested": pricing.round2(tested),
            "headroom": headroom,
            "pct": pct,
            "threshold_pct": _d(terms.get("threshold_pct") or 80),
            "cap_basis": basis,
            "term_elapsed_pct": elapsed,
            "orders": int(use.get("orders") or 0),
        }

    @staticmethod
    def _agreement_status(row: Contract, use: dict[str, Any]) -> str:
        """draft, signed, active, exhausted, expired or closed: one word for the pipeline."""
        if row.status in ("completed", "terminated"):
            return "closed"
        if row.status == "draft":
            return "signed" if row.signed_at else "draft"
        terms = row.terms or {}
        cap = _opt_d(terms.get("cap_value"))
        basis = str(terms.get("cap_basis") or "committed")
        if cap and _d(use.get(basis)) >= cap:
            return "exhausted"
        end = _date(row.end_date)
        if end and end < date.today():
            return "expired"
        return "active"

    async def create_agreement(self, data: AgreementCreate, user_id: str) -> Contract:
        await verify_project_access(data.project_id, user_id, self.session)
        if data.end_date < data.start_date:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end_date before start_date")
        project = await self._project(data.project_id)
        currency = (data.currency or str(getattr(project, "currency", "") or "")).upper()[:3]
        code = data.code or await self._next_agreement_code()
        if await self.repo.code_taken(code):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Contract code {code} already exists")
        self._raise_on_duplicates(data.items)
        row = Contract(
            code=code,
            title=data.title,
            contract_type=AGREEMENT,
            counterparty_type="client",
            counterparty_id=data.client_id,
            project_id=data.project_id,
            start_date=data.start_date.isoformat(),
            end_date=data.end_date.isoformat(),
            currency=currency,
            # Retention is held per order, never on the agreement itself.
            retention_percent=Decimal("0"),
            status="draft",
            created_by=str(user_id),
            terms={
                "client_name": data.client_name,
                "cap_value": str(data.cap_value) if data.cap_value is not None else None,
                "min_value": str(data.min_value) if data.min_value is not None else None,
                "estimated_value": str(data.estimated_value) if data.estimated_value is not None else None,
                "cap_basis": data.cap_basis,
                "threshold_pct": str(data.threshold_pct),
                "rounding": data.rounding,
                "override_policy": data.override_policy,
                "numbering_pattern": data.numbering_pattern,
                "client_kind": data.client_kind,
                "pack_values": data.pack_values,
            },
            total_value=data.cap_value or ZERO,
        )
        self.session.add(row)
        await self.session.flush()
        self.session.add(
            FrameworkRatePeriod(
                agreement_id=row.id,
                label=data.start_date.strftime("%Y-%m"),
                effective_from=data.start_date,
                effective_to=data.end_date,
                method=data.escalation_method,
                base_period=data.start_date.strftime("%Y-%m") if data.escalation_method != "none" else None,
            )
        )
        await self._add_items(row.id, data.items, start=0)
        await self.session.flush()
        return row

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        return await self.session.get(Project, project_id)

    async def _next_agreement_code(self) -> str:
        from sqlalchemy import func

        n = (
            await self.session.execute(select(func.count(Contract.id)).where(Contract.contract_type == AGREEMENT))
        ).scalar()
        seq = int(n or 0) + 1
        while await self.repo.code_taken(f"FA-{seq:03d}"):
            seq += 1
        return f"FA-{seq:03d}"

    async def update_agreement(self, row: Contract, data: AgreementUpdate) -> Contract:
        terms = dict(row.terms or {})
        fields = data.model_dump(exclude_unset=True)
        for key in ("title",):
            if key in fields:
                setattr(row, key, fields.pop(key))
        for key in ("start_date", "end_date"):
            if key in fields and fields[key] is not None:
                setattr(row, key, fields.pop(key).isoformat())
        for key, value in fields.items():
            terms[key] = str(value) if isinstance(value, Decimal) else value
        row.terms = terms
        if "cap_value" in fields and fields["cap_value"] is not None:
            row.total_value = Decimal(str(fields["cap_value"]))
        await self.session.flush()
        return row

    async def set_agreement_status(self, row: Contract, target: str) -> Contract:
        """``active`` (after signing), ``closed`` or back to ``draft`` while nothing was ordered."""
        if target == "active":
            if row.status != "draft":
                raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft agreement can be activated")
            row.status = "active"
            row.signed_at = row.signed_at or _now()
            row.original_contract_value = row.original_contract_value or row.total_value
        elif target == "closed":
            row.status = "completed"
        else:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown status")
        await self.session.flush()
        return row

    async def detail(self, row: Contract) -> dict[str, Any]:
        use = (await self.repo.consumption([row.id]))[row.id]
        summary = self._summary(row, use)
        project = await self._project(row.project_id)
        terms = row.terms or {}
        pack = pack_profile(getattr(project, "country_code", None), str(terms.get("client_kind") or "classic"))
        period = self._period_for(await self.repo.periods(row.id), date.today())
        summary.update(
            terms={**terms, "cap_overrides": list((row.metadata_ or {}).get("cap_overrides") or [])},
            pack=pack,
            findings=await self.agreement_findings(row, use, pack),
            current_period=self._period_out(period, {}) if period else None,
        )
        return summary

    async def agreement_findings(
        self, row: Contract, use: dict[str, Any], pack: dict[str, Any] | None = None
    ) -> list[Finding]:
        """Standing findings of an agreement: threshold, minimum, item maxima, term limit."""
        terms = row.terms or {}
        if pack is None:
            project = await self._project(row.project_id)
            pack = pack_profile(getattr(project, "country_code", None), str(terms.get("client_kind") or "classic"))
        basis = str(terms.get("cap_basis") or "committed")
        cap = pricing.cap_status(
            _opt_d(terms.get("cap_value")), _d(use.get(basis)), ZERO, _d(terms.get("threshold_pct") or 80)
        )
        start, end = _date(row.start_date), _date(row.end_date)
        payload: dict[str, Any] = {
            "agreement": self._agreement_payload(row, pack),
            "cap": self._cap_payload(cap),
            "items_over_max": await self._items_over_max(row.id),
        }
        if start and end:
            risk, days, pct = pricing.min_at_risk(
                _opt_d(terms.get("min_value")), _d(use.get("committed")), start, end, date.today()
            )
            payload["min_risk"] = {"at_risk": risk, "days": days, "pct": str(pct)}
        return await self._run_rules(payload, str(row.id))

    def _agreement_payload(self, row: Contract, pack: dict[str, Any]) -> dict[str, Any]:
        start, end = _date(row.start_date), _date(row.end_date)
        years = None
        if start and end:
            months = pricing.term_months(start, end)
            years = str((Decimal(months) / 12).quantize(Decimal("0.1")).normalize())
        return {
            "code": row.code,
            "currency": row.currency,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "term_limit": pack.get("term_limit"),
            "term_years": years,
        }

    @staticmethod
    def _cap_payload(cap: pricing.CapStatus) -> dict[str, Any]:
        return {
            "cap": str(cap.cap) if cap.cap is not None else None,
            "total_after": str(cap.total_after),
            "headroom_before": str(cap.headroom_before) if cap.headroom_before is not None else None,
            "headroom_after": str(cap.headroom_after) if cap.headroom_after is not None else None,
            "pct_after": str(cap.pct_after) if cap.pct_after is not None else None,
            "exceeded": cap.exceeded,
            "threshold_reached": cap.threshold_reached,
        }

    async def _items_over_max(self, agreement_id: uuid.UUID) -> list[dict[str, str]]:
        ordered = await self.repo.ordered_qty_by_item(agreement_id)
        out = []
        for item in await self.repo.items(agreement_id):
            qty = ordered.get(f"framework_item:{item.id}", (ZERO, 0))[0]
            if item.max_qty is not None and qty > item.max_qty:
                out.append(
                    {
                        "code": item.code,
                        "qty": format(qty.normalize(), "f"),
                        "max": format(item.max_qty.normalize(), "f"),
                    }
                )
        return out

    async def _run_rules(self, payload: dict[str, Any], target_id: str) -> list[Finding]:
        report = await validation_engine.validate(
            data=payload,
            rule_sets=[RULE_SET],
            target_type="framework_agreement",
            target_id=target_id,
            metadata={"locale": get_locale()},
        )
        return [
            Finding(
                rule_id=r.rule_id,
                code=str((r.details or {}).get("code") or ""),
                severity=r.severity.value,
                message=r.message,
                suggestion=r.suggestion,
                element_ref=r.element_ref,
            )
            for r in report.results
            if not r.passed and not r.is_engine_error
        ]

    # ── Price list ──────────────────────────────────────────────────────────

    @staticmethod
    def _duplicates(items: list[RateItemIn] | list[FrameworkRateItem]) -> list[str]:
        seen: set[str] = set()
        dupes: list[str] = []
        for item in items:
            code = item.code.strip()
            if code in seen and code not in dupes:
                dupes.append(code)
            seen.add(code)
        return dupes

    def _raise_on_duplicates(self, items: list[RateItemIn]) -> None:
        dupes = self._duplicates(items)
        if dupes:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"error": "FWK_DUPLICATE_ITEM", "codes": dupes},
            )

    async def _add_items(self, agreement_id: uuid.UUID, items: list[RateItemIn], start: int) -> None:
        for i, item in enumerate(items):
            self.session.add(
                FrameworkRateItem(
                    agreement_id=agreement_id,
                    sort_order=start + i,
                    **{**item.model_dump(), "code": item.code.strip()},
                )
            )

    async def list_items(self, row: Contract) -> list[dict[str, Any]]:
        items = await self.repo.items(row.id)
        ordered = await self.repo.ordered_qty_by_item(row.id)
        period = self._period_for(await self.repo.periods(row.id), date.today())
        factor = None
        if period is not None:
            try:
                factor = (await self._factor(period, date.today())).factor
            except (pricing.EscalationUnresolvedError, ValueError):
                factor = None
        out = []
        for item in items:
            qty, cites = ordered.get(f"framework_item:{item.id}", (ZERO, 0))
            base = self._base_rate(item, period)
            out.append(
                {
                    **{
                        c: getattr(item, c)
                        for c in (
                            "id",
                            "code",
                            "description",
                            "unit",
                            "classification",
                            "max_qty",
                            "estimated_qty",
                            "surcharge_flags",
                            "escalation_group",
                            "is_active",
                            "source",
                        )
                    },
                    "base_rate": base,
                    "effective_rate": pricing.round2(base * factor) if factor is not None else None,
                    "ordered_qty": qty,
                    "cited": cites > 0,
                }
            )
        return out

    async def import_items(self, row: Contract, items: list[RateItemIn], replace: bool) -> int:
        self._raise_on_duplicates(items)
        existing = await self.repo.items(row.id)
        ordered = await self.repo.ordered_qty_by_item(row.id)
        if replace:
            cited = [i.code for i in existing if f"framework_item:{i.id}" in ordered]
            if cited:
                # Rates cited by an order are never deleted; they go inactive and stay readable.
                for item in existing:
                    item.is_active = False
            else:
                for item in existing:
                    await self.session.delete(item)
            await self.session.flush()
            start = len(existing) if cited else 0
        else:
            clash = {i.code for i in existing} & {i.code.strip() for i in items}
            if clash:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    {"error": "FWK_DUPLICATE_ITEM", "codes": sorted(clash)},
                )
            start = len(existing)
        await self._add_items(row.id, items, start=start)
        await self.session.flush()
        return len(items)

    async def update_item(self, row: Contract, item_id: uuid.UUID, data: RateItemUpdate) -> dict[str, Any]:
        """Edit an item; a new rate for an item an order cites goes to a new draft rate period."""
        item = await self.session.get(FrameworkRateItem, item_id)
        if item is None or item.agreement_id != row.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        fields = data.model_dump(exclude_unset=True)
        ordered = await self.repo.ordered_qty_by_item(row.id)
        new_period = None
        if "base_rate" in fields and f"framework_item:{item.id}" in ordered and fields["base_rate"] != item.base_rate:
            new_period = FrameworkRatePeriod(
                agreement_id=row.id,
                label=f"{date.today():%Y-%m} draft",
                effective_from=date.today(),
                effective_to=_date(row.end_date),
                method="none",
                status="draft",
                rate_overrides={item.code: str(fields.pop("base_rate"))},
            )
            self.session.add(new_period)
        for key, value in fields.items():
            setattr(item, key, value)
        await self.session.flush()
        return {"item_id": item.id, "new_period_id": new_period.id if new_period else None}

    # ── Rate periods and adjustments ────────────────────────────────────────

    @staticmethod
    def _period_for(periods: list[FrameworkRatePeriod], day: date) -> FrameworkRatePeriod | None:
        """The active period whose window contains ``day``; the latest start wins (R5)."""
        live = [
            p
            for p in periods
            if p.status == "active" and p.effective_from <= day and (p.effective_to is None or day <= p.effective_to)
        ]
        return max(live, key=lambda p: p.effective_from) if live else None

    @staticmethod
    def _base_rate(item: FrameworkRateItem, period: FrameworkRatePeriod | None) -> Decimal:
        overrides = (period.rate_overrides or {}) if period else {}
        return _d(overrides[item.code]) if item.code in overrides else Decimal(item.base_rate)

    async def _index_points(self, names: list[str]) -> dict[str, dict[str, Decimal]]:
        from app.modules.price_index.models import CostIndexSeries

        names = [n for n in names if n]
        if not names:
            return {}
        rows = (
            (await self.session.execute(select(CostIndexSeries).where(CostIndexSeries.name.in_(names)))).scalars().all()
        )
        return {s.name: {p.period: Decimal(p.factor) for p in s.points} for s in rows}

    async def _factor(self, period: FrameworkRatePeriod, day: date) -> pricing.FactorResult:
        refs = list(period.series_refs or [])
        points = await self._index_points([str(r.get("series") or "") for r in refs])
        return pricing.period_factor(
            method=period.method,
            ordered_at=day,
            base_period=period.base_period,
            fixed_price_until=period.fixed_price_until,
            series_refs=refs,
            fixed_part=period.fixed_part,
            index_points=points,
            fixed_factor=period.fixed_factor,
        )

    def _period_out(self, period: FrameworkRatePeriod, extra: dict[str, Any]) -> dict[str, Any]:
        return {
            **{
                c: getattr(period, c)
                for c in (
                    "id",
                    "label",
                    "effective_from",
                    "effective_to",
                    "method",
                    "template_code",
                    "base_period",
                    "fixed_price_until",
                    "fixed_part",
                    "fixed_factor",
                    "series_refs",
                    "rate_overrides",
                    "status",
                )
            },
            **extra,
        }

    async def list_periods(self, row: Contract) -> list[dict[str, Any]]:
        out = []
        for period in await self.repo.periods(row.id):
            extra: dict[str, Any] = {}
            day = min(max(date.today(), period.effective_from), period.effective_to or date.today())
            try:
                extra["factor_today"] = (await self._factor(period, day)).factor
            except pricing.EscalationUnresolvedError as exc:
                extra["factor_error"] = f"{exc.series}@{exc.period}"
            except ValueError as exc:
                extra["factor_error"] = str(exc)
            out.append(self._period_out(period, extra))
        return out

    async def add_period(self, row: Contract, data: RatePeriodIn) -> FrameworkRatePeriod:
        period = FrameworkRatePeriod(agreement_id=row.id, **data.model_dump(mode="python"))
        period.rate_overrides = {k: str(v) for k, v in data.rate_overrides.items()}
        if not period.label:
            period.label = data.effective_from.strftime("%Y-%m")
        self.session.add(period)
        await self.session.flush()
        return period

    async def update_period(
        self, row: Contract, period_id: uuid.UUID, data: RatePeriodIn, activate: bool
    ) -> FrameworkRatePeriod:
        period = await self.session.get(FrameworkRatePeriod, period_id)
        if period is None or period.agreement_id != row.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Rate period not found")
        for key, value in data.model_dump(mode="python").items():
            setattr(period, key, value)
        period.rate_overrides = {k: str(v) for k, v in data.rate_overrides.items()}
        if activate:
            period.status = "active"
        await self.session.flush()
        return period

    async def list_adjustments(self, row: Contract) -> list[FrameworkAdjustment]:
        return await self.repo.adjustments(row.id)

    async def add_adjustment(self, row: Contract, data: AdjustmentIn) -> FrameworkAdjustment:
        adj = FrameworkAdjustment(agreement_id=row.id, **data.model_dump())
        self.session.add(adj)
        await self.session.flush()
        return adj

    async def delete_adjustment(self, row: Contract, adj_id: uuid.UUID) -> None:
        adj = await self.session.get(FrameworkAdjustment, adj_id)
        if adj is None or adj.agreement_id != row.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Adjustment not found")
        await self.session.delete(adj)
        await self.session.flush()

    # ── Pricing an order ────────────────────────────────────────────────────

    async def quote(self, row: Contract, req: OrderQuoteRequest) -> dict[str, Any]:
        """Price lines from the agreement and check the order; nothing is written."""
        items = await self.repo.items(row.id)
        by_id = {i.id: i for i in items}
        by_code = {i.code: i for i in items}
        adjustments = await self.repo.adjustments(row.id)
        period = self._period_for(await self.repo.periods(row.id), req.ordered_at)
        payload: dict[str, Any] = {
            "agreement": self._agreement_payload(row, {}),
            "order": {
                "ordered_at": req.ordered_at.isoformat(),
                "currency": (req.currency or row.currency).upper(),
                "lines": [],
            },
            "rate_period": {"covered": period is not None, "date": req.ordered_at.isoformat()},
        }
        factor_result = None
        if period is not None:
            try:
                factor_result = await self._factor(period, req.ordered_at)
            except pricing.EscalationUnresolvedError as exc:
                payload["escalation_unresolved"] = [{"series": exc.series, "period": exc.period}]
        priceable: list[tuple[pricing.ItemSpec, Decimal]] = []
        meta: list[FrameworkRateItem] = []
        for line in req.lines:
            item = by_id.get(line.item_id) if line.item_id else by_code.get(str(line.code or "").strip())
            if item is None or not item.is_active:
                payload["order"]["lines"].append({"code": line.code or str(line.item_id), "in_agreement": False})
                continue
            meta.append(item)
            priceable.append(
                (
                    pricing.ItemSpec(
                        item.code,
                        self._base_rate(item, period),
                        tuple(item.surcharge_flags or ()),
                        item.escalation_group,
                    ),
                    line.quantity,
                )
            )
        specs = [
            pricing.AdjustmentSpec(
                a.code, a.kind, Decimal(a.value), a.scope, tuple(a.scope_items or ()), a.scope_group, a.condition
            )
            for a in adjustments
        ]
        rounding = str((row.terms or {}).get("rounding") or "per_rate")
        lines_out: list[dict[str, Any]] = []
        net = ZERO
        alt: dict[str, Decimal] = {}
        if factor_result is not None:
            order = pricing.price_order(
                priceable, factor=factor_result.factor, adjustments=specs, tags=req.tags, rounding=rounding
            )
            net = order.net
            for item, priced in zip(meta, order.lines, strict=True):
                priced.rate_build["period"] = _period_label(period)
                priced.rate_build["period_id"] = str(period.id) if period else ""
                priced.rate_build["fixed_price"] = factor_result.fixed
                lines_out.append(
                    {
                        "item_id": item.id,
                        "code": item.code,
                        "description": item.description,
                        "unit": item.unit,
                        "quantity": priced.quantity,
                        "unit_rate": priced.unit_rate,
                        "total": priced.total,
                        "rate_build": priced.rate_build,
                    }
                )
            for mode in pricing.ROUNDING_MODES:
                alt[mode] = pricing.price_order(
                    priceable, factor=factor_result.factor, adjustments=specs, tags=req.tags, rounding=mode
                ).net
        payload["unknown_tags"] = pricing.unknown_condition_tags(req.tags, specs)
        terms = row.terms or {}
        use = (await self.repo.consumption([row.id]))[row.id]
        prior = _d(use.get("committed"))
        if req.exclude_order_id is not None:
            existing = await self.session.get(Contract, req.exclude_order_id)
            if existing is not None and existing.status in COMMITTED_STATUSES:
                prior -= Decimal(existing.total_value or 0)
        cap = pricing.cap_status(_opt_d(terms.get("cap_value")), prior, net, _d(terms.get("threshold_pct") or 80))
        payload["cap"] = self._cap_payload(cap)
        findings = await self._run_rules(payload, str(row.id))
        blocking = any(f.severity == "error" and f.code != "FWK_CAP_EXCEEDED" for f in findings)
        return {
            "lines": lines_out,
            "net": net,
            "factor": factor_result.factor if factor_result else None,
            "period_label": _period_label(period) or None,
            "rounding": rounding,
            "cap": self._cap_payload(cap),
            "findings": findings,
            "blocking": blocking,
            "over_cap": cap.exceeded,
            "per_rate_net": alt.get("per_rate"),
            "per_total_net": alt.get("per_total"),
        }

    async def _next_order_no(self, row: Contract, day: date) -> str:
        pattern = str((row.terms or {}).get("numbering_pattern") or "{agreement}-{yyyy}-{seq4}")
        # The next number follows the highest one in use for that year, so numbering carried
        # over from an earlier system continues instead of restarting at the count.
        prefix = pattern.replace("{agreement}", row.code).replace("{yyyy}", f"{day.year:04d}").split("{seq")[0]
        used = [c[len(prefix) :] for c in await self.repo.order_codes(row.id) if c.startswith(prefix)]
        seq = max((int(u) for u in used if u.isdigit()), default=0) + 1
        while True:
            code = (
                pattern.replace("{agreement}", row.code)
                .replace("{yyyy}", f"{day.year:04d}")
                .replace("{seq4}", f"{seq:04d}")
                .replace("{seq}", str(seq))
            )
            if not await self.repo.code_taken(code):
                return code
            seq += 1

    def _check_issue(
        self, row: Contract, quote: dict[str, Any], reason: str | None, can_override: bool
    ) -> dict[str, Any] | None:
        """Refuse an order that cannot be issued; return the override record when the cap is passed."""
        if quote["blocking"]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {
                    "error": "framework_order_invalid",
                    "findings": [f.model_dump() for f in quote["findings"] if f.severity == "error"],
                },
            )
        if not quote["over_cap"]:
            return None
        policy = str((row.terms or {}).get("override_policy") or "block")
        if policy == "block" and not can_override:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {"error": "FWK_CAP_EXCEEDED", "cap": quote["cap"]},
            )
        if len((reason or "").strip()) < OVERRIDE_REASON_MIN:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"error": "override_reason_required", "min_length": OVERRIDE_REASON_MIN, "cap": quote["cap"]},
            )
        cap = quote["cap"]
        overrun = pricing.round2(_d(cap["total_after"]) - _d(cap["cap"]))
        return {
            "reason": reason.strip() if reason else "",
            "overrun": str(overrun),
            "pct": cap["pct_after"],
            "policy": policy,
        }

    async def create_order(self, row: Contract, data: OrderCreate, user_id: str, can_override: bool) -> Contract:
        if row.status != "active" and data.issue:
            raise HTTPException(status.HTTP_409_CONFLICT, "Orders are issued under an active agreement")
        if not data.lines:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An order needs at least one line")
        quote = await self.quote(row, data)
        override = self._check_issue(row, quote, data.override_reason, can_override) if data.issue else None
        project_id = row.project_id
        if data.site_project_id is not None:
            await verify_project_access(data.site_project_id, user_id, self.session)
            project_id = data.site_project_id
        elif data.own_site_project:
            project_id = await self._create_site_project(row, data.site_label or data.ordered_at.isoformat(), user_id)
        order_no = await self._next_order_no(row, data.ordered_at)
        order = Contract(
            code=order_no,
            title=f"{order_no} {data.site_label}".strip(),
            contract_type=CALL_OFF,
            counterparty_type="client",
            counterparty_id=row.counterparty_id,
            project_id=project_id,
            parent_contract_id=row.id,
            start_date=data.ordered_at.isoformat(),
            end_date=data.requested_finish.isoformat() if data.requested_finish else None,
            currency=row.currency,
            retention_percent=row.retention_percent,
            status="draft",
            created_by=str(user_id),
            total_value=quote["net"],
            terms={
                "order_no": order_no,
                "ordered_at": data.ordered_at.isoformat(),
                "site_label": data.site_label,
                "tags": list(data.tags),
                "requested_start": data.requested_start.isoformat() if data.requested_start else None,
                "requested_finish": data.requested_finish.isoformat() if data.requested_finish else None,
                "order_status": "draft",
                "rounding": quote["rounding"],
                "factor": str(quote["factor"]) if quote["factor"] is not None else None,
                "period_label": quote["period_label"],
                "pack_values": data.pack_values,
            },
        )
        self.session.add(order)
        await self.session.flush()
        for i, line in enumerate(quote["lines"]):
            build = line["rate_build"]
            self.session.add(
                ContractLine(
                    contract_id=order.id,
                    code=line["code"],
                    description=line["description"],
                    unit=line["unit"],
                    quantity=line["quantity"],
                    unit_rate=line["unit_rate"],
                    total_value=line["total"],
                    order_index=i,
                    origin="framework_item",
                    source_key=f"framework_item:{line['item_id']}@{build.get('period_id') or ''}",
                    metadata_={"rate_build": build},
                )
            )
        await self.session.flush()
        if data.issue:
            await self._mark_issued(row, order, user_id, override)
        return order

    async def _create_site_project(self, row: Contract, site_label: str, user_id: str) -> uuid.UUID:
        """Q1: a large order gets its own site project, a child of the agreement's project."""
        from app.modules.projects.models import Project

        parent = await self._project(row.project_id)
        child = Project(
            name=f"{row.title} - {site_label}"[:255],
            description="",
            owner_id=uuid.UUID(str(user_id)),
            currency=getattr(parent, "currency", "") or row.currency,
            region=getattr(parent, "region", "") or "",
            locale=getattr(parent, "locale", "") or "en",
            classification_standard=getattr(parent, "classification_standard", "") or "",
            country_code=getattr(parent, "country_code", None),
            parent_project_id=row.project_id,
            project_type="framework_site",
        )
        self.session.add(child)
        await self.session.flush()
        return child.id

    async def _mark_issued(self, row: Contract, order: Contract, user_id: str, override: dict[str, Any] | None) -> None:
        terms = dict(order.terms or {})
        terms["order_status"] = "issued"
        terms["issued_at"] = _now()
        terms["issued_by"] = str(user_id)
        if override:
            override.update(by=str(user_id), at=_now())
            terms["cap_override"] = override
            meta = dict(row.metadata_ or {})
            meta["cap_overrides"] = [*(meta.get("cap_overrides") or []), {**override, "order_no": order.code}]
            row.metadata_ = meta
            logger.info(
                "framework cap override: agreement=%s order=%s overrun=%s", row.code, order.code, override["overrun"]
            )
        order.terms = terms
        order.status = "active"
        order.signed_at = order.signed_at or _now()
        order.original_contract_value = order.total_value
        for line in await self.repo.lines(order.id):
            line.original_value = line.total_value
        await self.session.flush()

    async def issue_order(
        self, order: Contract, row: Contract, reason: str | None, user_id: str, can_override: bool
    ) -> Contract:
        if (order.terms or {}).get("order_status") != "draft":
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft order can be issued")
        if row.status != "active":
            raise HTTPException(status.HTTP_409_CONFLICT, "Orders are issued under an active agreement")
        lines = [ln for ln in await self.repo.lines(order.id) if ln.origin == "framework_item"]
        req = OrderQuoteRequest(
            ordered_at=_date((order.terms or {}).get("ordered_at")) or date.today(),
            tags=list((order.terms or {}).get("tags") or []),
            lines=[{"code": ln.code, "quantity": ln.quantity} for ln in lines],
            exclude_order_id=order.id,
        )
        quote = await self.quote(row, req)
        # R6: an issued order freezes the rates it is issued at, so a draft is repriced right before.
        priced_by_code = {p["code"]: p for p in quote["lines"]}
        for line in lines:
            priced = priced_by_code.get(line.code)
            if priced is None:
                continue
            line.unit_rate = priced["unit_rate"]
            line.total_value = priced["total"]
            line.metadata_ = {**(line.metadata_ or {}), "rate_build": priced["rate_build"]}
        extras = sum(
            (Decimal(ln.total_value or 0) for ln in await self.repo.lines(order.id) if ln.origin != "framework_item"),
            ZERO,
        )
        order.total_value = quote["net"] + extras
        override = self._check_issue(row, quote, reason, can_override)
        await self._mark_issued(row, order, user_id, override)
        return order

    async def set_order_status(self, order: Contract, target: str) -> Contract:
        current = str((order.terms or {}).get("order_status") or "draft")
        allowed = {
            "draft": {"cancelled"},
            "issued": {"in_progress", "closed", "cancelled"},
            "in_progress": {"closed"},
        }
        if target not in allowed.get(current, set()):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot move an order from {current} to {target}")
        order.terms = {**(order.terms or {}), "order_status": target}
        order.status = _ORDER_TO_CONTRACT_STATUS[target]
        await self.session.flush()
        return order

    async def record_measurements(self, order: Contract, measurements: dict[str, Decimal]) -> list[ContractLine]:
        """R7: measured quantity to date per line; above ordered is allowed and flagged."""
        lines = await self.repo.lines(order.id)
        by_id = {str(ln.id): ln for ln in lines}
        for line_id, qty in measurements.items():
            line = by_id.get(line_id)
            if line is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Line {line_id} not on this order")
            if qty < 0:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Measured quantity cannot be negative")
            line.metadata_ = {**(line.metadata_ or {}), "measured_qty": format(qty, "f")}
        await self.session.flush()
        return lines

    # ── Reading orders ──────────────────────────────────────────────────────

    @staticmethod
    def _order_status(order: Contract, roll: dict[str, Any]) -> str:
        base = str((order.terms or {}).get("order_status") or "draft")
        if base in ("issued", "in_progress"):
            if roll.get("claims"):
                return "claimed"
            if roll.get("measured_value"):
                return "measured"
        return base

    def _order_summary(self, order: Contract, roll: dict[str, Any]) -> dict[str, Any]:
        terms = order.terms or {}
        ordered_value = _d(roll.get("ordered_value"))
        measured_pct = None
        if ordered_value > 0 and roll.get("measured_value"):
            measured_pct = (_d(roll["measured_value"]) / ordered_value * 100).quantize(Decimal("0.1"))
        return {
            "id": order.id,
            "code": order.code,
            "order_no": str(terms.get("order_no") or order.code),
            "site_label": str(terms.get("site_label") or ""),
            "project_id": order.project_id,
            "ordered_at": terms.get("ordered_at") or order.start_date,
            "tags": list(terms.get("tags") or []),
            "order_status": self._order_status(order, roll),
            "line_count": int(roll.get("lines") or 0),
            "net": Decimal(order.total_value or 0),
            "extras": _d(roll.get("extras")),
            "measured_pct": measured_pct,
            "claimed": _d(roll.get("claimed")),
            "has_extras": _d(roll.get("extras")) != 0,
            "measured_over_ordered": bool(roll.get("over")),
        }

    async def list_orders(self, row: Contract) -> list[dict[str, Any]]:
        orders = await self.repo.call_offs(row.id)
        rolls = await self.repo.order_rollups([o.id for o in orders])
        return [self._order_summary(o, rolls[o.id]) for o in orders]

    async def order_detail(self, order: Contract, row: Contract) -> dict[str, Any]:
        roll = (await self.repo.order_rollups([order.id]))[order.id]
        out = self._order_summary(order, roll)
        lines = await self.repo.lines(order.id)
        out["lines"] = [
            {
                "id": ln.id,
                "code": ln.code,
                "description": ln.description,
                "unit": ln.unit,
                "quantity": ln.quantity,
                "unit_rate": ln.unit_rate,
                "total_value": ln.total_value,
                "origin": ln.origin,
                "measured_qty": _opt_d((ln.metadata_ or {}).get("measured_qty")),
                "rate_build": dict((ln.metadata_ or {}).get("rate_build") or {}),
            }
            for ln in lines
        ]
        out["terms"] = order.terms or {}
        payload = {
            "agreement": self._agreement_payload(row, {}),
            "order": {
                "order_no": out["order_no"],
                "currency": order.currency,
                "lines": [
                    {"code": ln["code"], "quantity": str(ln["quantity"]), "measured_qty": ln["measured_qty"]}
                    for ln in out["lines"]
                    if ln["origin"] == "framework_item"
                ],
            },
        }
        out["findings"] = await self._run_rules(payload, str(order.id))
        return out

    async def breakdown(self, row: Contract, by: str) -> list[dict[str, Any]]:
        rows = await self.repo.breakdown(row.id, by)
        items = {f"framework_item:{i.id}": i for i in await self.repo.items(row.id)} if by == "item" else {}
        out = []
        for key, label, n, committed, qty in rows:
            item = items.get(key)
            out.append(
                {
                    "key": key,
                    "label": f"{item.code} {item.description}".strip() if item else label,
                    "orders": n,
                    "committed": pricing.round2(committed),
                    "quantity": qty if by == "item" else None,
                    "max_qty": item.max_qty if item else None,
                }
            )
        return out

    # ── Extras ──────────────────────────────────────────────────────────────

    async def list_extras(self, order: Contract) -> list[dict[str, Any]]:
        from app.modules.variations.models import VariationRequest

        rows = (
            (
                await self.session.execute(
                    select(VariationRequest).where(VariationRequest.project_id == order.project_id)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": vr.id,
                "code": vr.code,
                "title": vr.title,
                "status": vr.status,
                "amount": vr.agreed_cost_impact if vr.agreed_cost_impact is not None else vr.estimated_cost_impact,
                "currency": vr.currency,
            }
            for vr in rows
            if str((vr.metadata_ or {}).get("contract_id") or "") == str(order.id)
        ]

    async def raise_extra(self, order: Contract, title: str, description: str, amount: Decimal, user_id: str) -> Any:
        """An extra is a variation request on the order, never a free-text order line."""
        from sqlalchemy import func

        from app.modules.variations.models import VariationRequest

        n = (
            await self.session.execute(
                select(func.count(VariationRequest.id)).where(VariationRequest.project_id == order.project_id)
            )
        ).scalar()
        vr = VariationRequest(
            project_id=order.project_id,
            code=f"VR-{order.code}-{int(n or 0) + 1:02d}"[:50],
            title=title,
            description=description,
            requested_by=str(user_id),
            requested_at=_now(),
            classification="extra_item",
            estimated_cost_impact=amount,
            currency=order.currency,
            status="draft",
            metadata_={"contract_id": str(order.id), "framework_order": order.code},
        )
        self.session.add(vr)
        await self.session.flush()
        return vr
