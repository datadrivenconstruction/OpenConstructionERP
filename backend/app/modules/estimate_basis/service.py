# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate-basis business logic.

Reads the finished estimate contents (the BOQ positions of a project), runs the
pure :mod:`.derivation` engine over them, and persists the drafted
basis-of-estimate. Also serves the read / edit / export of a stored document.

The heavy reasoning lives in :mod:`.derivation` (stdlib-only, unit tested); this
layer only moves rows in and out and shapes the response.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.core.sql_numeric import numeric_value
from app.modules.allowances.models import Allowance
from app.modules.boq.base_date import latest_base_date
from app.modules.boq.models import BOQ, BOQMarkup, Position, QuantityLink
from app.modules.costs.models import CostItem, CostItemUsage
from app.modules.estimate_basis.derivation import (
    ClassSuggestion,
    MarkupPicture,
    ProvenanceSummary,
    TradeCoverage,
    accuracy_range,
    derive_provenance,
    derive_trades,
    draft_basis,
    fmt_decimal,
    fmt_pct,
    parse_accuracy_pct,
    suggest_estimate_class,
    summarise_markups,
    to_decimal,
)
from app.modules.estimate_basis.models import EstimateBasis
from app.modules.estimate_basis.schemas import (
    ClassReasonOut,
    ClassSuggestionOut,
    CoverageSummary,
    EstimateBasisResponse,
    EstimateBasisSummary,
    EstimateClassCatalog,
    EstimateClassOption,
    FinancialsSummary,
    ProvenanceBucketOut,
    ProvenanceFamilyOut,
    ProvenanceSummaryOut,
    QualificationItem,
    TradePresenceOut,
    TradeRefOut,
    UpdateRequest,
)
from app.modules.preliminaries.models import PrelimItem
from app.modules.preliminaries.prelim_math import rollup_by_category

# Bound the position scan so a runaway project can never OOM the worker; the same
# ceiling the BOQ Project Intelligence widgets use. A basis of estimate is a
# qualitative summary, so the first 20k lines already cover the trade picture.
#
# The cap applies to the TRADE scan only. The provenance and completeness
# figures are SQL aggregates over every position of the estimate: "62% of the
# value was measured from a model" computed off the first 20 000 lines of a
# longer bill would be a false statement about the whole, and a percentage is
# exactly the kind of number nobody re-checks.
_POSITION_CAP = 20_000

# A section header carries no unit (or the literal unit "section"); the
# derivation only wants priced line items. This is the SQL-expressible half of
# ``boq.service._is_section``, which additionally requires a zero quantity and
# rate - a condition that cannot be pushed into the same index-friendly filter
# and that no real section row fails.
_LINE_ITEM_FILTER = Position.unit.notin_(("", "section"))

# Money arrives from the BOQ roll-up as float (its long-standing contract, and
# the same figure the bill's own screens show). It is quantized on arrival and
# stored as a Decimal string; the basis never re-derives a total of its own.
_CENTS = Decimal("0.01")


def _money(value: object) -> Decimal:
    """Quantize a roll-up figure into a two-place Decimal.

    The BOQ roll-up's money keys are float by its own long-standing contract.
    Rounding once, here, at the boundary is what keeps the basis reporting the
    same figure the bill reports rather than a second opinion about it.
    """
    return to_decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


class EstimateBasisService:
    """Draft, store and serve the basis-of-estimate for a project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Reads over the estimate ──────────────────────────────────────────────

    async def _load_positions(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None,
    ) -> list[Position]:
        """Return the priced line items of a project (or one of its BOQs).

        Section headers (no unit) are dropped and the children/parent eager
        loads suppressed - the derivation reads only scalar columns.
        """
        stmt = (
            select(Position)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id)
            .where(_LINE_ITEM_FILTER)
            .order_by(Position.sort_order, Position.ordinal)
            .limit(_POSITION_CAP)
            .options(noload(Position.children), noload(Position.parent))
        )
        if boq_id is not None:
            stmt = stmt.where(Position.boq_id == boq_id)
        rows = await self.session.execute(stmt)
        return list(rows.scalars().all())

    @staticmethod
    def _position_to_dict(pos: Position) -> dict:
        """Project a Position ORM row into the plain dict the engine consumes."""
        return {
            "classification": pos.classification or {},
            "description": pos.description or "",
            "quantity": pos.quantity,
            "unit_rate": pos.unit_rate,
            "total": pos.total,
        }

    # ── Reads over the estimate as a whole (uncapped aggregates) ─────────────

    def _estimate_scope(self, stmt: object, project_id: uuid.UUID, boq_id: uuid.UUID | None) -> object:
        """Narrow a Position query to the estimate the document covers."""
        stmt = stmt.join(BOQ, Position.boq_id == BOQ.id).where(BOQ.project_id == project_id)  # type: ignore[attr-defined]
        stmt = stmt.where(_LINE_ITEM_FILTER)  # type: ignore[attr-defined]
        if boq_id is not None:
            stmt = stmt.where(Position.boq_id == boq_id)  # type: ignore[attr-defined]
        return stmt

    async def _load_provenance_rows(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None,
    ) -> list[dict]:
        """Group every line of the estimate by source and confidence.

        A ``GROUP BY`` rather than a scan on purpose: the shares this feeds are
        statements about the whole estimate, and the capped position load the
        trade coverage uses could not support one. The confidence column is
        grouped verbatim because it holds two vocabularies (a 0-1 number and the
        legacy ``high``/``medium``/``low`` words); the engine folds them.
        """
        stmt = select(
            Position.source,
            Position.confidence,
            func.count().label("position_count"),
            func.sum(numeric_value(Position.total)).label("total"),
        )
        stmt = self._estimate_scope(stmt, project_id, boq_id)
        stmt = stmt.group_by(Position.source, Position.confidence)  # type: ignore[attr-defined]
        rows = await self.session.execute(stmt)  # type: ignore[arg-type]
        return [
            {
                "source": row.source,
                "confidence": row.confidence,
                "position_count": int(row.position_count or 0),
                "total": row.total,
            }
            for row in rows
        ]

    async def _load_link_counts(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None,
    ) -> dict[str, int]:
        """Count the model-driven quantity bindings by status.

        A stale or broken binding is a basis-of-estimate fact in its own right:
        the quantity on the line was taken from a model that has since moved,
        and nobody has re-applied it.
        """
        stmt = (
            select(QuantityLink.status, func.count().label("n"))
            .join(BOQ, QuantityLink.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id)
            .group_by(QuantityLink.status)
        )
        if boq_id is not None:
            stmt = stmt.where(QuantityLink.boq_id == boq_id)
        rows = await self.session.execute(stmt)
        return {str(row.status or "").strip().lower(): int(row.n or 0) for row in rows}

    async def _load_completeness(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None,
    ) -> tuple[int, float, float]:
        """Return ``(line_items, rate_completeness_pct, resource_completeness_pct)``.

        The three inputs the BOQ module's AACE rule reads, computed here over the
        whole estimate (which may span several bills) instead of over one bill.
        """
        priced = numeric_value(Position.unit_rate) > 0
        measured = numeric_value(Position.quantity) > 0
        described = func.trim(Position.description) != ""
        stmt = select(
            func.count().label("total"),
            func.sum(case((priced, 1), else_=0)).label("with_rates"),
            func.sum(case((priced & measured & described, 1), else_=0)).label("with_resources"),
        )
        stmt = self._estimate_scope(stmt, project_id, boq_id)
        row = (await self.session.execute(stmt)).one()  # type: ignore[arg-type]
        total = int(row.total or 0)
        if total == 0:
            return 0, 0.0, 0.0
        rate_pct = float(row.with_rates or 0) / total * 100
        resource_pct = float(row.with_resources or 0) / total * 100
        return total, rate_pct, resource_pct

    async def _load_markups(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None,
    ) -> MarkupPicture:
        """Read the active markup lines the estimate applies.

        Only active lines: a deactivated markup charges nothing, so a document
        that named it would be describing money the client is not being asked
        for.
        """
        stmt = (
            select(BOQMarkup)
            .join(BOQ, BOQMarkup.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id)
            .where(BOQMarkup.is_active.is_(True))
            .order_by(BOQMarkup.sort_order, BOQMarkup.created_at)
            .limit(200)
        )
        if boq_id is not None:
            stmt = stmt.where(BOQMarkup.boq_id == boq_id)
        rows = await self.session.execute(stmt)
        return summarise_markups(
            [
                {
                    "name": m.name,
                    "category": m.category,
                    "markup_type": m.markup_type,
                    "percentage": m.percentage,
                    "fixed_amount": m.fixed_amount,
                }
                for m in rows.scalars().all()
            ]
        )

    async def _load_financials(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None,
        currency: str,
        markup_count: int,
    ) -> FinancialsSummary:
        """Snapshot the money the document qualifies.

        Delegates to ``BOQService.compute_boq_totals`` - the platform's single
        currency-aware roll-up, the same one the bill's list and detail screens
        report from. Nothing here re-implements the markup cascade: a second
        engine would eventually disagree with the first, and the number a client
        reads has to be the number the bill shows.
        """
        # Imported inside the call: ``boq.service`` pulls the whole FastAPI
        # dependency graph, and this module is imported by the demo seeder.
        from app.modules.boq.service import BOQService

        ids_stmt = select(BOQ.id).where(BOQ.project_id == project_id)
        if boq_id is not None:
            ids_stmt = ids_stmt.where(BOQ.id == boq_id)
        boq_ids = list((await self.session.execute(ids_stmt)).scalars().all())
        summary = FinancialsSummary(currency=currency, markup_count=markup_count, boq_count=len(boq_ids))
        if not boq_ids:
            return summary

        breakdown = await BOQService(self.session).compute_boq_totals(boq_ids)
        direct = Decimal("0")
        markups = Decimal("0")
        grand = Decimal("0")
        for entry in breakdown.values():
            direct += _money(entry.get("direct_cost"))
            markups += _money(entry.get("markups_total"))
            grand += _money(entry.get("grand_total"))
            summary.is_mixed_currency = summary.is_mixed_currency or bool(entry.get("is_mixed_currency"))
            summary.has_unresolved_escalation = summary.has_unresolved_escalation or bool(
                entry.get("has_unresolved_escalation")
            )
        summary.direct_cost = fmt_decimal(direct)
        summary.markups_total = fmt_decimal(markups)
        summary.grand_total = fmt_decimal(grand)
        return summary

    async def _resolve_currency(self, project_id: uuid.UUID, currency: str) -> str:
        """Return the stated currency, or the project's when none was stated.

        The standalone page has no currency to pass, so before this the document
        it generated carried no currency at all and its figures rendered with no
        symbol. Resolving it here fixes every caller at once rather than asking
        each one to remember.
        """
        stated = (currency or "").strip().upper()
        if stated:
            return stated
        from app.modules.projects.models import Project

        stmt = select(Project.currency).where(Project.id == project_id)
        found = (await self.session.execute(stmt)).scalar()
        return str(found or "").strip().upper()

    # ── Reads over the sibling estimating modules ────────────────────────────

    async def _load_allowances(self, project_id: uuid.UUID) -> list[dict]:
        """Return the project's allowances as plain dicts for the deriver.

        Only the held amount is read (not the drawdowns): the basis records the
        allowance that was set, not what has since been spent against it. Ordered
        by type then age so a regenerate is stable.
        """
        stmt = (
            select(Allowance)
            .where(Allowance.project_id == project_id)
            .order_by(Allowance.allowance_type, Allowance.created_at)
            .limit(500)
        )
        rows = await self.session.execute(stmt)
        return [
            {
                "id": str(a.id),
                "label": a.label or "",
                "allowance_type": a.allowance_type or "",
                "held_amount": a.held_amount,
                "currency": a.currency or "",
            }
            for a in rows.scalars().all()
        ]

    async def _load_preliminaries_summary(self, project_id: uuid.UUID, currency: str) -> dict:
        """Roll the project's preliminaries up via ``prelim_math`` into a summary.

        Returns the grand / time-related / fixed totals, the item count and the
        estimate currency, ready for the deriver. An empty project yields a
        zero-count summary that drafts no line.
        """
        stmt = select(PrelimItem).where(PrelimItem.project_id == project_id).limit(2000)
        rows = await self.session.execute(stmt)
        items = [
            {
                "item_type": p.item_type,
                "category": p.category,
                "rate_per_period": p.rate_per_period,
                "periods": p.periods,
                "fixed_amount": p.fixed_amount,
            }
            for p in rows.scalars().all()
        ]
        rollup = rollup_by_category(items)
        return {
            "grand_total": rollup.grand_total,
            "time_related_total": rollup.time_related_total,
            "fixed_total": rollup.fixed_total,
            "item_count": rollup.item_count,
            "currency": (currency or "").strip(),
        }

    async def _derive_pricing_base_date(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None,
    ) -> str | None:
        """Return the date the priced rates are current to, or ``None``.

        Prefers the freshest ``price_as_of`` across the cost items actually
        applied in the project (through the usage ledger); falls back to the
        estimate's stated base date (the BOQ ``base_date``, the escalation base).

        The bills are ranked by :func:`app.modules.boq.base_date.latest_base_date`
        rather than by ``max()`` in SQL. ``base_date`` is free text holding a
        day, a month, a quarter or a year, and those strings do not sort in the
        order their dates run: ``"2026-Q1"`` sorts above ``"2026-12-01"``. A
        project mixing shapes was quoting the wrong bill's price base in a
        document that goes to a client.
        """
        price_stmt = (
            select(func.max(CostItem.price_as_of))
            .select_from(CostItemUsage)
            .join(CostItem, CostItem.id == CostItemUsage.cost_item_id)
            .where(CostItemUsage.project_id == project_id)
        )
        price_as_of = (await self.session.execute(price_stmt)).scalar()
        if price_as_of is not None:
            return price_as_of.isoformat()

        base_stmt = select(BOQ.base_date).where(BOQ.project_id == project_id, BOQ.base_date.is_not(None))
        if boq_id is not None:
            base_stmt = base_stmt.where(BOQ.id == boq_id)
        return latest_base_date((await self.session.execute(base_stmt)).scalars().all())

    # ── Generate ─────────────────────────────────────────────────────────────

    async def generate(
        self,
        *,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None,
        title: str | None,
        currency: str,
        base_date: str | None,
        created_by: uuid.UUID | None,
    ) -> EstimateBasis:
        """Derive and persist a fresh basis-of-estimate for the project.

        Always inserts a new document (drafts are versioned, not overwritten), so
        a regenerate never silently discards a client's prior edits.
        """
        resolved_currency = await self._resolve_currency(project_id, currency)

        positions = await self._load_positions(project_id, boq_id)
        coverage = derive_trades([self._position_to_dict(p) for p in positions])
        allowances = await self._load_allowances(project_id)
        preliminaries = await self._load_preliminaries_summary(project_id, resolved_currency)
        pricing_base_date = await self._derive_pricing_base_date(project_id, boq_id)
        markups = await self._load_markups(project_id, boq_id)
        provenance = derive_provenance(
            await self._load_provenance_rows(project_id, boq_id),
            link_counts=await self._load_link_counts(project_id, boq_id),
        )
        suggestion = await self._suggest_class(project_id, boq_id, provenance, coverage)
        financials = await self._load_financials(
            project_id,
            boq_id,
            resolved_currency,
            markup_count=len(markups.lines),
        )

        draft = draft_basis(
            coverage,
            currency=resolved_currency,
            base_date=base_date,
            allowances=allowances,
            preliminaries=preliminaries,
            pricing_base_date=pricing_base_date,
            provenance=provenance,
            markups=markups,
        )

        doc = EstimateBasis(
            project_id=project_id,
            boq_id=boq_id,
            title=(title or "").strip() or "Basis of estimate",
            status="draft",
            inclusions=[q.to_dict() for q in draft.inclusions],
            exclusions=[q.to_dict() for q in draft.exclusions],
            assumptions=[q.to_dict() for q in draft.assumptions],
            coverage=self._coverage_summary(coverage).model_dump(),
            currency=resolved_currency,
            financials=financials.model_dump(),
            provenance=self._provenance_summary(provenance, suggestion).model_dump(),
            pricing_date=pricing_base_date,
            # ``estimate_class`` is deliberately left unset. The suggestion above
            # travels inside ``provenance`` and the UI presents it as a proposal;
            # storing it here would be the platform answering a question that is
            # the estimator's to answer.
            generated_at=datetime.now(UTC).isoformat(),
            created_by=created_by,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def _suggest_class(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID | None,
        provenance: ProvenanceSummary,
        coverage: TradeCoverage,
    ) -> ClassSuggestion:
        """Suggest an AACE class for the estimate.

        The completeness half of the judgement is the BOQ module's own rule -
        the one behind ``GET /boqs/{id}/classification/`` - so the two screens
        cannot disagree about the same bill. It is imported rather than copied:
        one standard, one table. What this layer adds is the part a completeness
        rule cannot see, that a fully filled-in bill of hand-typed quantities is
        not a definitive estimate.
        """
        # Imported inside the call for the same reason ``_load_financials``
        # does it: ``boq.service`` drags in the whole dependency graph.
        from app.modules.boq.service import _determine_aace_class

        total, rate_pct, resource_pct = await self._load_completeness(project_id, boq_id)
        base_class = _determine_aace_class(total, rate_pct, resource_pct)
        return suggest_estimate_class(base_class, provenance, coverage)

    @staticmethod
    def class_catalog() -> EstimateClassCatalog:
        """Publish the AACE 18R-97 class table the platform judges against.

        Served to the client so a UI never hardcodes a standard's accuracy
        ranges, and read back when an estimator picks a class so the band it
        seeds is the published one rather than a number somebody remembered.
        """
        from app.modules.boq.service import _AACE_CLASSES

        return EstimateClassCatalog(
            items=[
                EstimateClassOption(
                    estimate_class=key,
                    label=str(info.get("label", "")),
                    accuracy_low=str(info.get("accuracy_low", "")),
                    accuracy_high=str(info.get("accuracy_high", "")),
                    definition_level_low=int(info.get("definition_low", 0)),
                    definition_level_high=int(info.get("definition_high", 0)),
                    methodology=str(info.get("methodology", "")),
                )
                for key, info in sorted(_AACE_CLASSES.items())
            ]
        )

    @staticmethod
    def _default_band(estimate_class: int) -> tuple[str, str]:
        """Return the published accuracy band of a class as signed percentages."""
        from app.modules.boq.service import _AACE_CLASSES

        info = _AACE_CLASSES.get(estimate_class)
        if not info:
            return "", ""
        low = parse_accuracy_pct(info.get("accuracy_low"))
        high = parse_accuracy_pct(info.get("accuracy_high"))
        return fmt_pct(low), fmt_pct(high)

    @staticmethod
    def _provenance_summary(
        provenance: ProvenanceSummary,
        suggestion: ClassSuggestion,
    ) -> ProvenanceSummaryOut:
        """Shape a :class:`ProvenanceSummary` plus its suggestion for storage."""
        return ProvenanceSummaryOut(
            buckets=[
                ProvenanceBucketOut(
                    source=b.source,
                    family=b.family,
                    position_count=b.position_count,
                    total=fmt_decimal(b.total),
                    share_pct=fmt_pct(b.share_pct),
                )
                for b in provenance.buckets
            ],
            families=[
                ProvenanceFamilyOut(
                    family=f.family,
                    position_count=f.position_count,
                    total=fmt_decimal(f.total),
                    share_pct=fmt_pct(f.share_pct),
                )
                for f in provenance.families
            ],
            total_positions=provenance.total_positions,
            priced_total=fmt_decimal(provenance.priced_total),
            share_basis=provenance.share_basis,
            ai_position_count=provenance.ai_position_count,
            ai_total=fmt_decimal(provenance.ai_total),
            scored_position_count=provenance.scored_position_count,
            low_confidence_count=provenance.low_confidence_count,
            low_confidence_total=fmt_decimal(provenance.low_confidence_total),
            model_linked_positions=provenance.model_linked_positions,
            stale_links=provenance.stale_links,
            broken_links=provenance.broken_links,
            suggestion=ClassSuggestionOut(
                suggested_class=suggestion.suggested_class,
                base_class=suggestion.base_class,
                reasons=[ClassReasonOut(code=r.code, value=r.value) for r in suggestion.reasons],
            ),
        )

    @staticmethod
    def _coverage_summary(coverage: TradeCoverage) -> CoverageSummary:
        """Shape a :class:`TradeCoverage` into the serialisable summary."""
        return CoverageSummary(
            present_trades=[
                TradePresenceOut(
                    code=p.code,
                    label=p.label,
                    core=p.core,
                    position_count=p.position_count,
                    total=fmt_decimal(p.total),
                )
                for p in coverage.present
            ],
            absent_trades=[TradeRefOut(code=t.code, label=t.label) for t in coverage.absent_core],
            total_positions=coverage.total_positions,
            classified_positions=coverage.classified_positions,
            unclassified_positions=coverage.unclassified_positions,
            zero_rate_positions=coverage.zero_rate_positions,
            missing_quantity_positions=coverage.missing_quantity_positions,
            provisional_positions=coverage.provisional_positions,
            by_others_positions=coverage.by_others_positions,
        )

    # ── Read / list ──────────────────────────────────────────────────────────

    async def get_document(self, document_id: uuid.UUID) -> EstimateBasis | None:
        """Fetch one document by id, or ``None`` when it does not exist."""
        return await self.session.get(EstimateBasis, document_id)

    async def list_for_project(self, project_id: uuid.UUID) -> list[EstimateBasis]:
        """Every basis document for a project, newest first."""
        stmt = (
            select(EstimateBasis)
            .where(EstimateBasis.project_id == project_id)
            .order_by(EstimateBasis.created_at.desc())
            .limit(200)
        )
        rows = await self.session.execute(stmt)
        return list(rows.scalars().all())

    # ── Update ───────────────────────────────────────────────────────────────

    async def update_document(
        self,
        doc: EstimateBasis,
        payload: UpdateRequest,
    ) -> EstimateBasis:
        """Persist user edits. Only the provided fields are touched."""
        if payload.title is not None:
            doc.title = payload.title.strip() or doc.title
        if payload.status is not None:
            doc.status = payload.status
        if payload.notes is not None:
            doc.notes = payload.notes
        if payload.inclusions is not None:
            doc.inclusions = [self._normalize_item(i, "inclusion") for i in payload.inclusions]
        if payload.exclusions is not None:
            doc.exclusions = [self._normalize_item(i, "exclusion") for i in payload.exclusions]
        if payload.assumptions is not None:
            doc.assumptions = [self._normalize_item(i, "assumption") for i in payload.assumptions]
        if payload.market_conditions is not None:
            doc.market_conditions = payload.market_conditions
        if payload.contingency_rationale is not None:
            doc.contingency_rationale = payload.contingency_rationale
        self._apply_class(doc, payload)
        await self.session.flush()
        return doc

    @classmethod
    def _apply_class(cls, doc: EstimateBasis, payload: UpdateRequest) -> None:
        """Apply an estimate-class decision and the band that comes with it.

        Picking a class seeds the published accuracy band of that class, which
        is what an estimator expects and what makes the decision one click. An
        explicitly supplied band always wins, so a house that runs tighter than
        the standard keeps its own numbers on the next save. Sending ``0``
        unstates the class and clears the band with it - a band with no class
        behind it is a number nobody can defend.
        """
        if payload.estimate_class is not None:
            if payload.estimate_class == 0:
                doc.estimate_class = None
                doc.accuracy_low_pct = ""
                doc.accuracy_high_pct = ""
            elif payload.estimate_class != doc.estimate_class:
                doc.estimate_class = payload.estimate_class
                doc.accuracy_low_pct, doc.accuracy_high_pct = cls._default_band(payload.estimate_class)
        if payload.accuracy_low_pct is not None:
            doc.accuracy_low_pct = fmt_pct(parse_accuracy_pct(payload.accuracy_low_pct))
        if payload.accuracy_high_pct is not None:
            doc.accuracy_high_pct = fmt_pct(parse_accuracy_pct(payload.accuracy_high_pct))

    @staticmethod
    def _normalize_item(item: QualificationItem, category: str) -> dict:
        """Force an incoming item onto its list's category and serialise it."""
        data = item.model_dump()
        data["category"] = category
        return data

    # ── Response shaping ─────────────────────────────────────────────────────

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        """ISO-8601 for a timestamp column, or ``None``."""
        return value.isoformat() if value is not None else None

    @classmethod
    def accuracy_amounts(cls, doc: EstimateBasis) -> tuple[str, str]:
        """Return the money range the stated class implies, or two blanks.

        Blank rather than the point estimate twice when no class is stated: a
        range that equals the number would read as "this estimate is exact",
        which is the one thing an unanswered document does not say.
        """
        if doc.estimate_class is None:
            return "", ""
        low_pct = parse_accuracy_pct(doc.accuracy_low_pct)
        high_pct = parse_accuracy_pct(doc.accuracy_high_pct)
        if low_pct == 0 and high_pct == 0:
            return "", ""
        grand = to_decimal((doc.financials or {}).get("grand_total"))
        low, high = accuracy_range(grand, low_pct, high_pct)
        return fmt_decimal(low), fmt_decimal(high)

    @classmethod
    def to_response(cls, doc: EstimateBasis) -> EstimateBasisResponse:
        """Build the full-document response from a stored row."""
        low_amount, high_amount = cls.accuracy_amounts(doc)
        return EstimateBasisResponse(
            id=str(doc.id),
            project_id=str(doc.project_id),
            boq_id=str(doc.boq_id) if doc.boq_id else None,
            title=doc.title,
            status=doc.status,
            notes=doc.notes or "",
            inclusions=[QualificationItem.model_validate(i) for i in (doc.inclusions or [])],
            exclusions=[QualificationItem.model_validate(i) for i in (doc.exclusions or [])],
            assumptions=[QualificationItem.model_validate(i) for i in (doc.assumptions or [])],
            coverage=CoverageSummary.model_validate(doc.coverage or {}),
            financials=FinancialsSummary.model_validate(doc.financials or {}),
            provenance=ProvenanceSummaryOut.model_validate(doc.provenance or {}),
            currency=doc.currency or "",
            pricing_date=doc.pricing_date,
            estimate_class=doc.estimate_class,
            accuracy_low_pct=doc.accuracy_low_pct or "",
            accuracy_high_pct=doc.accuracy_high_pct or "",
            accuracy_low_amount=low_amount,
            accuracy_high_amount=high_amount,
            market_conditions=doc.market_conditions or "",
            contingency_rationale=doc.contingency_rationale or "",
            generated_at=doc.generated_at,
            created_at=cls._iso(doc.created_at),
            updated_at=cls._iso(doc.updated_at),
        )

    @classmethod
    def to_summary(cls, doc: EstimateBasis) -> EstimateBasisSummary:
        """Build the lightweight list row from a stored document."""
        return EstimateBasisSummary(
            id=str(doc.id),
            project_id=str(doc.project_id),
            boq_id=str(doc.boq_id) if doc.boq_id else None,
            title=doc.title,
            status=doc.status,
            inclusion_count=len(doc.inclusions or []),
            exclusion_count=len(doc.exclusions or []),
            assumption_count=len(doc.assumptions or []),
            estimate_class=doc.estimate_class,
            grand_total=str((doc.financials or {}).get("grand_total") or ""),
            currency=doc.currency or "",
            generated_at=doc.generated_at,
            created_at=cls._iso(doc.created_at),
            updated_at=cls._iso(doc.updated_at),
        )

    # ── Export ───────────────────────────────────────────────────────────────

    # Human labels for the provenance families in the exported document. The
    # UI labels the same keys from its own translated strings.
    _FAMILY_LABELS = {
        "measured": "Measured from a drawing or model",
        "imported": "Imported from a supplied bill",
        "catalogue": "From a cost database or assembly",
        "manual": "Entered by hand",
    }

    @classmethod
    def _render_headline(cls, doc: EstimateBasis) -> list[str]:
        """Render the estimate's own figure, class and accuracy band.

        A basis of estimate whose reader has to open a second document to learn
        what number is being qualified is not a deliverable. This block is what
        turns the export into one.
        """
        financials = doc.financials or {}
        currency = (doc.currency or financials.get("currency") or "").strip()
        grand = str(financials.get("grand_total") or "").strip()
        if not grand:
            return []

        suffix = f" {currency}" if currency else ""
        out: list[str] = ["## The estimate", "", f"- Estimate total: {grand}{suffix}"]
        direct = str(financials.get("direct_cost") or "").strip()
        markups = str(financials.get("markups_total") or "").strip()
        if direct:
            out.append(f"- Direct cost: {direct}{suffix}")
        if markups:
            out.append(f"- Markups: {markups}{suffix}")

        if doc.estimate_class is not None:
            low_amount, high_amount = cls.accuracy_amounts(doc)
            band = f"{doc.accuracy_low_pct}% to {doc.accuracy_high_pct}%"
            out.append(f"- Estimate class: AACE class {doc.estimate_class} ({band})")
            if low_amount and high_amount:
                out.append(f"- Expected range: {low_amount}{suffix} to {high_amount}{suffix}")
        else:
            out.append("- Estimate class: not stated.")
        if doc.pricing_date:
            out.append(f"- Prices current as of: {doc.pricing_date}")
        if financials.get("is_mixed_currency"):
            out.append("- Note: the bill blends more than one currency; the total above is not final.")
        if financials.get("has_unresolved_escalation"):
            out.append("- Note: an escalation line named an index that could not be resolved and was left unpriced.")
        out.append("")
        return out

    @classmethod
    def _render_provenance(cls, doc: EstimateBasis) -> list[str]:
        """Render where the estimate's lines came from."""
        provenance = doc.provenance or {}
        families = provenance.get("families") or []
        if not families:
            return []

        noun = "value" if provenance.get("share_basis") == "value" else "line items"
        out: list[str] = ["## Where the numbers came from", "", f"Share of {noun}:", ""]
        for entry in families:
            key = str(entry.get("family") or "")
            label = cls._FAMILY_LABELS.get(key, key)
            out.append(f"- {label}: {entry.get('share_pct', '0.0')}% ({entry.get('position_count', 0)} lines)")

        low = int(provenance.get("low_confidence_count") or 0)
        if low:
            out.append(f"- Machine-proposed lines awaiting review: {low}")
        stale = int(provenance.get("stale_links") or 0) + int(provenance.get("broken_links") or 0)
        if stale:
            out.append(f"- Model-driven quantities out of step with the model: {stale}")
        out.append("")
        return out

    @classmethod
    def render_markdown(cls, doc: EstimateBasis) -> str:
        """Render the document as Markdown for inclusion with a proposal.

        Only enabled lines are written - a line the estimator toggled off stays
        out of the client-facing export.
        """
        lines: list[str] = [f"# {doc.title}", ""]
        meta = f"Status: {doc.status}"
        if doc.generated_at:
            meta += f"  ·  Generated: {doc.generated_at}"
        lines.append(f"_{meta}_")
        lines.append("")
        lines.extend(cls._render_headline(doc))
        lines.extend(cls._render_provenance(doc))

        sections = (
            ("Inclusions", doc.inclusions),
            ("Exclusions", doc.exclusions),
            ("Assumptions", doc.assumptions),
        )
        for heading, items in sections:
            enabled = [it for it in (items or []) if it.get("enabled", True)]
            lines.append(f"## {heading}")
            if enabled:
                for it in enabled:
                    lines.append(f"- {str(it.get('text', '')).strip()}")
            else:
                lines.append("- None.")
            lines.append("")

        # The estimator's own two paragraphs, after the qualification lists and
        # before the free notes: they qualify the whole document, not one line.
        for heading, body in (
            ("Market conditions", doc.market_conditions),
            ("Contingency rationale", doc.contingency_rationale),
        ):
            if (body or "").strip():
                lines.append(f"## {heading}")
                lines.append(body.strip())
                lines.append("")

        if (doc.notes or "").strip():
            lines.append("## Notes")
            lines.append(doc.notes.strip())
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
