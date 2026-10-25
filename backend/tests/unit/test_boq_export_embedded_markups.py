# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sale-rate export: markups folded into the unit rates, tax left visible.

Pins the arithmetic of :mod:`app.modules.boq.embedding`: an exact percentage,
a fixed line spread pro rata, a section-scoped line loading only its own
section, the cent rounding gap, and that the input payload is never mutated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.boq.embedding import (
    apply_embedding,
    embed_enabled,
    embed_tolerance,
    is_embedded,
    plan_embedding,
    preview_dict,
)
from app.modules.boq.models import BOQMarkup, Position
from app.modules.boq.schemas import BOQWithSections
from app.modules.boq.service import _calculate_markup_amounts_scoped
from app.modules.boq.validators import EmbeddedExportRoundingGap

BOQ_ID = uuid.uuid4()
NOW = datetime.now(UTC)


def _mk(
    name: str,
    category: str,
    *,
    pct: str = "0",
    fixed: str = "0",
    apply_to: str = "direct_cost",
    order: int = 0,
    scope: uuid.UUID | None = None,
    meta: dict | None = None,
) -> BOQMarkup:
    m = BOQMarkup(
        boq_id=BOQ_ID,
        name=name,
        category=category,
        markup_type="fixed" if fixed != "0" else "percentage",
        percentage=pct,
        fixed_amount=fixed,
        apply_to=apply_to,
        sort_order=order,
        is_active=True,
        scope_position_id=scope,
        overrides_id=None,
        metadata_=meta or {},
    )
    m.id = uuid.uuid4()
    return m


def _pos(qty: str, rate: str, parent: uuid.UUID | None = None, *, section: bool = False) -> Position:
    total = "0" if section else format(Decimal(qty) * Decimal(rate), "f")
    p = Position(
        boq_id=BOQ_ID,
        parent_id=parent,
        ordinal="1",
        description="S" if section else "Item",
        unit="" if section else "m2",
        quantity="0" if section else qty,
        unit_rate="0" if section else rate,
        total=total,
        classification={},
        metadata_={},
    )
    p.id = uuid.uuid4()
    return p


def _resp(p: Position, metadata: dict | None = None) -> dict:
    return {
        "id": p.id,
        "boq_id": BOQ_ID,
        "parent_id": p.parent_id,
        "ordinal": p.ordinal,
        "description": p.description,
        "unit": p.unit,
        "quantity": p.quantity,
        "unit_rate": p.unit_rate,
        "total": p.total,
        "classification": {},
        "source": "manual",
        "confidence": None,
        "cad_element_ids": [],
        "validation_status": "pending",
        "metadata_": metadata or {},
        "sort_order": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _structured(positions: list[Position], markups: list[BOQMarkup]) -> BOQWithSections:
    """The payload ``get_boq_structured`` would build for these rows."""
    leaf = lambda p: Decimal(p.total)  # noqa: E731
    sections = [p for p in positions if p.unit == ""]
    leaves = [p for p in positions if p.unit != ""]
    direct = sum((Decimal(p.total) for p in leaves), Decimal("0"))
    amounts = _calculate_markup_amounts_scoped(direct, markups, positions, leaf)
    return BOQWithSections.model_validate(
        {
            "id": BOQ_ID,
            "project_id": uuid.uuid4(),
            "name": "B",
            "description": "",
            "status": "draft",
            "metadata_": {},
            "created_at": NOW,
            "updated_at": NOW,
            "sections": [
                {
                    "id": s.id,
                    "ordinal": s.ordinal,
                    "description": s.description,
                    "positions": [_resp(p) for p in leaves if p.parent_id == s.id],
                    "subtotal": sum((Decimal(p.total) for p in leaves if p.parent_id == s.id), Decimal("0")),
                }
                for s in sections
            ],
            "positions": [_resp(p) for p in leaves if p.parent_id is None],
            "direct_cost": direct,
            "markups": [
                {
                    "id": m.id,
                    "boq_id": BOQ_ID,
                    "name": m.name,
                    "markup_type": m.markup_type,
                    "category": m.category,
                    "percentage": float(m.percentage),
                    "fixed_amount": float(m.fixed_amount),
                    "apply_to": m.apply_to,
                    "sort_order": m.sort_order,
                    "is_active": True,
                    "metadata_": m.metadata_,
                    "created_at": NOW,
                    "updated_at": NOW,
                    "amount": a,
                }
                for m, a in amounts
            ],
            "net_total": direct + sum((a for _, a in amounts), Decimal("0")),
            "grand_total": direct + sum((a for _, a in amounts), Decimal("0")),
        }
    )


def _run(positions: list[Position], markups: list[BOQMarkup]):
    structured = _structured(positions, markups)
    plan = plan_embedding(positions, markups, lambda p: Decimal(p.total))
    return structured, plan, apply_embedding(structured, plan)


def _leaves(payload: BOQWithSections) -> list:
    return [p for s in payload.sections for p in s.positions] + list(payload.positions)


def test_default_flag_embeds_everything_but_tax() -> None:
    assert is_embedded(_mk("OH", "overhead"))
    assert not is_embedded(_mk("VAT", "tax"))
    assert not is_embedded(_mk("VAT", "vat"))
    assert not is_embedded(_mk("OH", "overhead", meta={"include_in_unit_rates": False}))
    assert is_embedded(_mk("VAT", "tax", meta={"include_in_unit_rates": True}))
    assert embed_enabled({"export_embed_markups": True}) and not embed_enabled({})
    assert embed_tolerance({}) == Decimal("0.50")


def test_percentage_markup_is_exact_and_tax_is_recomputed_on_the_new_net() -> None:
    a, b = _pos("2", "100"), _pos("3", "50")
    markups = [_mk("OH", "overhead", pct="10", order=1), _mk("VAT", "tax", pct="20", apply_to="cumulative", order=2)]
    structured, plan, result = _run([a, b], markups)
    out = result.payload
    rates = {p.id: (p.unit_rate, p.total) for p in _leaves(out)}
    assert rates[a.id] == (Decimal("110.00"), Decimal("220.00"))
    assert rates[b.id] == (Decimal("55.00"), Decimal("165.00"))
    assert out.direct_cost == Decimal("385.00")
    assert [m.name for m in out.markups] == ["VAT"]
    assert out.markups[0].amount == Decimal("77.00")
    assert out.grand_total == structured.grand_total == Decimal("462.00")
    assert result.rounding_gap == 0
    # The input payload is a copy, never rewritten in place.
    assert {p.unit_rate for p in _leaves(structured)} == {Decimal("100"), Decimal("50")}


def test_fixed_line_is_spread_pro_rata() -> None:
    a, b = _pos("1", "300"), _pos("1", "100")
    _, plan, result = _run([a, b], [_mk("Site setup", "overhead", fixed="40")])
    assert plan.buckets[()].k == Decimal("1.1")
    assert {p.total for p in _leaves(result.payload)} == {Decimal("330.00"), Decimal("110.00")}
    assert result.payload.markups == []


def test_section_scoped_markup_only_loads_its_own_lines() -> None:
    s1, s2 = _pos("0", "0", section=True), _pos("0", "0", section=True)
    a, b = _pos("1", "100", s1.id), _pos("1", "100", s2.id)
    markups = [_mk("OH", "overhead", pct="10"), _mk("Risk", "contingency", pct="5", scope=s1.id)]
    _, plan, result = _run([s1, s2, a, b], markups)
    assert plan.k_of(a.id) == Decimal("1.15") and plan.k_of(b.id) == Decimal("1.1")
    subtotals = {s.id: s.subtotal for s in result.payload.sections}
    assert subtotals == {s1.id: Decimal("115.00"), s2.id: Decimal("110.00")}


def test_rounding_gap_is_reported_and_the_rule_warns_above_tolerance() -> None:
    lines = [_pos("1", "0.33") for _ in range(30)]
    _, plan, result = _run(lines, [_mk("OH", "overhead", pct="7")])
    # 0.33 * 1.07 = 0.3531 -> 0.35 per line: 10.50 against 10.59 in the editor.
    assert result.editor_net == Decimal("10.59")
    assert result.sale_net == Decimal("10.50")
    preview = preview_dict(result, plan, Decimal("0.05"))
    assert preview["rounding_gap"] == "-0.09" and preview["within_tolerance"] is False
    assert preview["buckets"][0]["k"] == "1.070000"

    rule = EmbeddedExportRoundingGap()
    import asyncio

    found = asyncio.run(rule.validate(ValidationContext(data={"export_embedding": preview})))
    assert len(found) == 1 and found[0].details["rounding_gap"] == "-0.09"
    quiet = {**preview, "tolerance": "0.10"}
    assert asyncio.run(rule.validate(ValidationContext(data={"export_embedding": quiet}))) == []


@pytest.mark.parametrize("rate", ["12.345", "0.01", "999999.99"])
def test_sale_rate_rounds_half_up_to_the_cent(rate: str) -> None:
    a = _pos("1", rate)
    _, _, result = _run([a], [_mk("OH", "overhead", pct="12.5")])
    expected = (Decimal(rate) * Decimal("1.125")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
    assert _leaves(result.payload)[0].unit_rate == expected
