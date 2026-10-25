# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export with markups embedded in the unit rates (sale rates).

A contractor often sends a client sale unit rates: overhead, profit and the
other margins folded into every rate, and only the tax shown as its own line.
This module rewrites the structured export payload into that shape. The stored
bill is never touched; every function here works on copies.

The leaves are bucketed exactly as :func:`_calculate_markup_amounts_scoped`
buckets them, so a section-scoped markup only loads its own lines. Each bucket
gets one factor ``k = 1 + embedded markup amount / bucket direct cost``. A
fixed or banded line is therefore spread pro rata over its bucket. Each sale
rate is ``rate x k`` rounded to the cent (ROUND_HALF_UP), each line total is
``quantity x sale rate``, and the difference between the new net and the
editor's net plus embedded markups is the rounding gap the preview reports.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.modules.boq.models import BOQMarkup, Position
from app.modules.boq.service import (
    _calculate_markup_amounts,
    _calculate_markup_amounts_scoped,
    _effective_stack,
    _is_section,
    _round_currency,
    _scope_chain,
)

#: BOQ metadata key that turns the mode on for every export of the bill.
EMBED_SETTING_KEY = "export_embed_markups"
#: BOQ metadata key holding the accepted rounding gap, in the bill currency.
EMBED_TOLERANCE_KEY = "export_embed_tolerance"
#: Markup metadata key: whether the line is folded into the unit rates.
INCLUDE_KEY = "include_in_unit_rates"
#: Categories that stay a visible line unless the estimator says otherwise.
NOT_EMBEDDED_BY_DEFAULT = frozenset({"tax", "vat"})
DEFAULT_TOLERANCE = Decimal("0.50")

_CENT = Decimal("0.01")
_K_PLACES = Decimal("0.000001")


def _dec(value: object) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _cents(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _meta(obj: object) -> dict[str, Any]:
    for attr in ("metadata_", "metadata"):
        value = getattr(obj, attr, None)
        if isinstance(value, dict):
            return value
    return {}


def is_embedded(markup: object) -> bool:
    """Whether a markup line is folded into the unit rates.

    The per-line flag wins; without it every category except tax/VAT is embedded.
    """
    flag = _meta(markup).get(INCLUDE_KEY)
    if isinstance(flag, bool):
        return flag
    return str(getattr(markup, "category", "") or "").lower() not in NOT_EMBEDDED_BY_DEFAULT


def embed_enabled(boq_metadata: object) -> bool:
    """Whether the bill opted into embedded-markup exports."""
    return isinstance(boq_metadata, dict) and boq_metadata.get(EMBED_SETTING_KEY) is True


def embed_tolerance(boq_metadata: object) -> Decimal:
    """The accepted rounding gap for the bill."""
    if isinstance(boq_metadata, dict) and boq_metadata.get(EMBED_TOLERANCE_KEY) is not None:
        value = _dec(boq_metadata.get(EMBED_TOLERANCE_KEY))
        if value >= 0:
            return value
    return DEFAULT_TOLERANCE


@dataclass
class Bucket:
    """Leaves that see the same markup stack."""

    key: tuple[uuid.UUID, ...]
    direct_cost: Decimal = Decimal("0")
    embedded_amount: Decimal = Decimal("0")
    sale_net: Decimal = Decimal("0")

    @property
    def k(self) -> Decimal:
        if self.direct_cost == 0:
            return Decimal("1")
        return Decimal("1") + self.embedded_amount / self.direct_cost


@dataclass
class EmbeddingPlan:
    """Per-leaf factors plus everything needed to re-roll the payload."""

    buckets: dict[tuple[uuid.UUID, ...], Bucket]
    bucket_of: dict[uuid.UUID, tuple[uuid.UUID, ...]]
    old_base: dict[uuid.UUID, Decimal]
    parent_of: dict[uuid.UUID, uuid.UUID | None]
    section_ids: set[uuid.UUID]
    positions: Sequence[Position]
    markups: Sequence[BOQMarkup]
    escalation_factors: Mapping[uuid.UUID, Decimal] | None
    new_base: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    rates: dict[uuid.UUID, tuple[Decimal, Decimal]] = field(default_factory=dict)

    def k_of(self, position_id: uuid.UUID) -> Decimal:
        key = self.bucket_of.get(position_id)
        return self.buckets[key].k if key is not None else Decimal("1")


def plan_embedding(
    positions: Sequence[Position],
    markups: Sequence[BOQMarkup],
    leaf_amount: Callable[[Position], Decimal],
    escalation_factors: Mapping[uuid.UUID, Decimal] | None = None,
) -> EmbeddingPlan:
    """Bucket the leaves and work out each bucket's embedded markup amount."""
    scope_ids = {m.scope_position_id for m in markups if m.scope_position_id is not None and m.is_active}
    bill_wide = [m for m in markups if m.scope_position_id is None]
    overrides_by_scope: dict[uuid.UUID, list[BOQMarkup]] = {}
    for m in markups:
        if m.scope_position_id is not None and m.is_active:
            overrides_by_scope.setdefault(m.scope_position_id, []).append(m)

    parent_of = {p.id: p.parent_id for p in positions}
    section_ids = {p.id for p in positions if _is_section(p)}
    buckets: dict[tuple[uuid.UUID, ...], Bucket] = {}
    bucket_of: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {}
    old_base: dict[uuid.UUID, Decimal] = {}
    for p in positions:
        if p.id in section_ids:
            continue
        key = _scope_chain(p.id, parent_of, scope_ids) if scope_ids else ()
        amount = leaf_amount(p)
        bucket = buckets.setdefault(key, Bucket(key=key))
        bucket.direct_cost += amount
        bucket_of[p.id] = key
        old_base[p.id] = amount

    for key, bucket in buckets.items():
        stack = _effective_stack(bill_wide, overrides_by_scope, key) if scope_ids else list(markups)
        for markup, amount in _calculate_markup_amounts(bucket.direct_cost, stack, escalation_factors):
            if markup.is_active and is_embedded(markup):
                bucket.embedded_amount += amount

    return EmbeddingPlan(
        buckets=buckets,
        bucket_of=bucket_of,
        old_base=old_base,
        parent_of=parent_of,
        section_ids=section_ids,
        positions=positions,
        markups=markups,
        escalation_factors=escalation_factors,
    )


def _scale_resources(meta: dict[str, Any], k: Decimal) -> dict[str, Any]:
    resources = meta.get("resources")
    if not isinstance(resources, list) or k == 1:
        return meta
    scaled: list[Any] = []
    for res in resources:
        if not isinstance(res, dict):
            scaled.append(res)
            continue
        row = dict(res)
        for key in ("unit_rate", "total"):
            if row.get(key) is not None:
                value = _cents(_dec(row[key]) * k)
                row[key] = format(value, "f") if isinstance(res[key], str) else float(value)
        scaled.append(row)
    return {**meta, "resources": scaled}


def embed_position(pos: Any, plan: EmbeddingPlan) -> Any:
    """A copy of one position response priced at its sale rate."""
    if pos.id in plan.section_ids or pos.id not in plan.bucket_of:
        return pos
    k = plan.k_of(pos.id)
    sale_rate = _cents(_dec(pos.unit_rate) * k)
    total = _cents(_dec(pos.quantity) * sale_rate)
    plan.rates[pos.id] = (sale_rate, total)
    meta = getattr(pos, "metadata", None)
    update: dict[str, Any] = {"unit_rate": sale_rate, "total": total}
    if isinstance(meta, dict):
        update["metadata"] = _scale_resources(copy.deepcopy(meta), k)
    return pos.model_copy(update=update)


def embed_positions(positions: Sequence[Any], plan: EmbeddingPlan) -> list[Any]:
    """Apply :func:`embed_position` to a flat list (the Excel row source)."""
    return [embed_position(p, plan) for p in positions]


def _new_leaf_base(plan: EmbeddingPlan, pos_id: uuid.UUID, old_total: Decimal, new_total: Decimal) -> Decimal:
    old_base = plan.old_base.get(pos_id, old_total)
    if old_base == old_total:
        return new_total
    if old_total == 0:
        return old_base * plan.k_of(pos_id)
    # A foreign-currency line: carry its base figure by the same ratio.
    return old_base * new_total / old_total


@dataclass
class EmbeddingResult:
    """The rewritten payload plus the figures the preview reports."""

    payload: Any
    editor_net: Decimal
    sale_net: Decimal

    @property
    def rounding_gap(self) -> Decimal:
        return self.sale_net - self.editor_net


def apply_embedding(structured: Any, plan: EmbeddingPlan) -> EmbeddingResult:
    """Rewrite a ``BOQWithSections`` payload into sale rates. The input is not mutated."""
    out = structured.model_copy(deep=True)
    editor_embedded = sum(
        (_dec(m.amount) for m in structured.markups if m.is_active and is_embedded(m)),
        Decimal("0"),
    )
    editor_net = _round_currency(_dec(structured.direct_cost) + editor_embedded)

    def _rewrite(rows: list[Any]) -> list[Any]:
        new_rows = []
        for row in rows:
            new_row = embed_position(row, plan)
            if new_row is not row:
                plan.new_base[row.id] = _new_leaf_base(plan, row.id, _dec(row.total), _dec(new_row.total))
            new_rows.append(new_row)
        return new_rows

    for section in out.sections:
        section.positions = _rewrite(section.positions)
    out.positions = _rewrite(out.positions)

    # Leaves the export dropped (blank placeholders) carry zero either way.
    for pos_id, key in plan.bucket_of.items():
        plan.buckets[key].sale_net += plan.new_base.get(pos_id, Decimal("0"))

    rolled: dict[uuid.UUID, Decimal] = {}
    for pos_id, amount in plan.new_base.items():
        parent = plan.parent_of.get(pos_id)
        seen: set[uuid.UUID] = set()
        while parent is not None and parent in plan.section_ids and parent not in seen:
            seen.add(parent)
            rolled[parent] = rolled.get(parent, Decimal("0")) + amount
            parent = plan.parent_of.get(parent)
    for section in out.sections:
        section.subtotal = _round_currency(rolled.get(section.id, Decimal("0")))

    sale_net = _round_currency(sum(plan.new_base.values(), Decimal("0")))
    kept = [m for m in plan.markups if not is_embedded(m)]
    amounts: dict[Any, Decimal] = {}
    if kept:
        for markup, amount in _calculate_markup_amounts_scoped(
            sale_net,
            kept,
            plan.positions,
            lambda p: plan.new_base.get(p.id, Decimal("0")),
            plan.escalation_factors,
        ):
            amounts[markup.id] = amount
    out.markups = [
        m.model_copy(update={"amount": _round_currency(amounts.get(m.id, Decimal("0")))})
        for m in out.markups
        if not is_embedded(m)
    ]
    total = sale_net + sum((m.amount for m in out.markups if m.is_active), Decimal("0"))
    out.direct_cost = sale_net
    out.net_total = _round_currency(total)
    out.grand_total = _round_currency(total)
    return EmbeddingResult(payload=out, editor_net=editor_net, sale_net=sale_net)


def preview_dict(result: EmbeddingResult, plan: EmbeddingPlan, tolerance: Decimal) -> dict[str, Any]:
    """The JSON body of the embedding preview endpoint. Money as decimal strings."""
    payload = result.payload
    return {
        "buckets": [
            {
                "scope_position_ids": [str(s) for s in key],
                "direct_cost": format(_round_currency(b.direct_cost), "f"),
                "embedded_amount": format(_round_currency(b.embedded_amount), "f"),
                "k": format(b.k.quantize(_K_PLACES, rounding=ROUND_HALF_UP), "f"),
                "sale_net": format(_round_currency(b.sale_net), "f"),
                "position_count": sum(1 for v in plan.bucket_of.values() if v == key),
            }
            for key, b in plan.buckets.items()
        ],
        "editor_net": format(result.editor_net, "f"),
        "sale_net": format(result.sale_net, "f"),
        "rounding_gap": format(_round_currency(result.rounding_gap), "f"),
        "tolerance": format(tolerance, "f"),
        "within_tolerance": abs(result.rounding_gap) <= tolerance,
        "visible_markups": [
            {"id": str(m.id), "name": m.name, "category": m.category, "amount": format(_round_currency(m.amount), "f")}
            for m in payload.markups
        ],
        "grand_total": format(_round_currency(payload.grand_total), "f"),
        "markups": [
            {"id": str(m.id), "name": m.name, "category": m.category, INCLUDE_KEY: is_embedded(m)}
            for m in plan.markups
            if m.is_active
        ],
    }
