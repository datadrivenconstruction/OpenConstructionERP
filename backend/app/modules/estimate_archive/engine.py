# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure arithmetic of a sealed estimate: payload, fingerprint and carried rates.

Nothing here touches the database. The service builds a payload from a bill,
hands it to :func:`seal_digest`, and later hands the stored payload back to
:func:`derive_rate` to price a change from the sealed basis.

Payload (schema ``oe.estimate_seal/1``) holds everything needed to rebuild
every rate without the live bill: positions with their resource lines, every
markup row with its scope and override chain, dates, currency, rounding rule
and the hash of every attached file. Database ids are deliberately absent:
positions are keyed by ordinal and markups by a stable ``key`` built from
their order, so a re-export of the same content gives the same fingerprint
(rule S1).

Rounding follows the bill's own markup cascade
(:func:`app.modules.boq.service._calculate_markup_amounts`): each resource line
is rounded to cents, the markup stack runs at full precision on the net, and
the rate is rounded once, half up. The domain fixtures were written assuming
a rounding per markup step; on two of the three worked examples that gives a
cent less (36.15 vs 36.16, 188.01 vs 188.02). The bill is the authority, so
the carried rate agrees with the bill that produced the seal.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from app.core.evidence import content_digest

SCHEMA = "oe.estimate_seal/1"
ROUNDING_RULE = "line_2dp_half_up;cascade_full_precision;rate_2dp_half_up"

#: Basis methods a variation line may record. The engine computes, it never picks.
BASIS_METHODS = ("original_basis", "cost_plus_markup", "agreed", "daywork")

#: Markup categories that never belong in a unit rate: tax is levied on the
#: invoice, not built into what one cubic metre costs.
_EXCLUDED_CATEGORIES = frozenset({"tax", "vat"})

_CENT = Decimal("0.01")
_ZERO = Decimal("0")


def dec(value: Any) -> Decimal:
    """A finite Decimal out of a JSON-ish value; junk reads as zero."""
    if value is None or isinstance(value, bool):
        return _ZERO
    try:
        out = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError):
        return _ZERO
    return out if out.is_finite() else _ZERO


def canon(value: Any) -> str:
    """Canonical text of a number, so equal amounts hash equally ("52.80" == "52.8")."""
    d = dec(value)
    if d == 0:
        return "0"
    text = format(d.normalize(), "f")
    return text


def round2(value: Decimal) -> Decimal:
    """Cents, half up."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def money(value: Decimal) -> str:
    """A two-decimal string for responses."""
    return format(round2(value), "f")


# ── Payload ──────────────────────────────────────────────────────────────────


def resource_line(row: Mapping[str, Any]) -> dict[str, Any]:
    """One resource row of a bill position in sealed form."""
    return {
        "kind": str(row.get("type") or row.get("kind") or "other"),
        "code": str(row.get("code") or ""),
        "description": str(row.get("name") or row.get("description") or ""),
        "unit": str(row.get("unit") or ""),
        "consumption": canon(row.get("quantity", row.get("consumption"))),
        "unit_cost": canon(row.get("unit_rate", row.get("unit_cost"))),
        "price_date": str(row.get("price_date") or ""),
        "quote_ref": str(row.get("quote_ref") or row.get("supplier_quote_ref") or ""),
    }


def build_payload(
    *,
    estimate: Mapping[str, Any],
    positions: Iterable[Mapping[str, Any]],
    markups: Iterable[Mapping[str, Any]],
    attachments: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Assemble the sealed payload from plain dicts.

    Args:
        estimate: ``name``, ``currency``, ``base_date``, ``tax_date``,
            ``classification_standard``.
        positions: Each with ``ordinal``, ``parent_ordinal``, ``description``,
            ``unit``, ``quantity``, ``unit_rate``, ``classification`` and
            ``resources`` (bill resource rows).
        markups: Each with ``id`` (any hashable, used only to resolve
            ``overrides_id``), ``name``, ``category``, ``markup_type``,
            ``percentage``, ``fixed_amount``, ``apply_to``, ``sort_order``,
            ``is_active``, ``scope_ordinal`` and ``overrides_id``.
        attachments: Each with ``name`` and ``sha256``.

    Returns:
        The payload dict; ids are replaced by ordinals and stable keys.
    """
    ordered = sorted(markups, key=lambda m: (int(m.get("sort_order") or 0), str(m.get("name") or "")))
    key_of = {m.get("id"): f"m{i + 1:02d}" for i, m in enumerate(ordered)}
    sealed_markups = [
        {
            "key": key_of[m.get("id")],
            "name": str(m.get("name") or ""),
            "category": str(m.get("category") or "overhead"),
            "markup_type": str(m.get("markup_type") or "percentage"),
            "percentage": canon(m.get("percentage")),
            "fixed_amount": canon(m.get("fixed_amount")),
            "apply_to": str(m.get("apply_to") or "direct_cost"),
            "sort_order": int(m.get("sort_order") or 0),
            "is_active": bool(m.get("is_active", True)),
            "scope_ordinal": m.get("scope_ordinal") or None,
            "overrides_key": key_of.get(m.get("overrides_id")) if m.get("overrides_id") is not None else None,
        }
        for m in ordered
    ]
    sealed_positions = []
    for p in positions:
        quantity = dec(p.get("quantity"))
        rate = dec(p.get("unit_rate"))
        sealed_positions.append(
            {
                "ordinal": str(p.get("ordinal") or ""),
                "parent_ordinal": p.get("parent_ordinal") or None,
                "description": str(p.get("description") or ""),
                "unit": str(p.get("unit") or ""),
                "quantity": canon(quantity),
                "unit_rate": canon(rate),
                "total": canon(round2(quantity * rate)),
                "classification": dict(p.get("classification") or {}),
                "resources": [resource_line(r) for r in (p.get("resources") or []) if isinstance(r, Mapping)],
            }
        )
    return {
        "schema": SCHEMA,
        "estimate": {
            "name": str(estimate.get("name") or ""),
            "currency": str(estimate.get("currency") or ""),
            "base_date": str(estimate.get("base_date") or ""),
            "tax_date": str(estimate.get("tax_date") or ""),
            "classification_standard": str(estimate.get("classification_standard") or ""),
            "rounding": ROUNDING_RULE,
        },
        "positions": sealed_positions,
        "markups": sealed_markups,
        "attachments": sorted(
            ({"name": str(a.get("name") or ""), "sha256": str(a.get("sha256") or "")} for a in attachments),
            key=lambda a: (a["name"], a["sha256"]),
        ),
    }


def seal_digest(payload: Mapping[str, Any]) -> str:
    """SHA-256 fingerprint of the payload (rule S1)."""
    return content_digest(payload)


def is_priced(position: Mapping[str, Any]) -> bool:
    """A position that carries money (sections and headings do not)."""
    return str(position.get("unit") or "") not in ("", "section") and dec(position.get("quantity")) != 0


def payload_totals(payload: Mapping[str, Any]) -> dict[str, Decimal]:
    """Direct cost, markups and grand total of the sealed bill (rule S3)."""
    positions = [p for p in payload.get("positions") or [] if is_priced(p)]
    direct = sum((dec(p.get("total")) for p in positions), _ZERO)
    stack = [_ns(m) for m in payload.get("markups") or [] if not m.get("scope_ordinal")]
    from app.modules.boq.service import _calculate_markup_amounts

    amounts = _calculate_markup_amounts(direct, stack)  # type: ignore[arg-type]
    markup_total = sum((a for _m, a in amounts), _ZERO)
    return {
        "direct_cost": round2(direct),
        "markups": round2(markup_total),
        "grand_total": round2(direct + markup_total),
    }


def breakdown_stats(payload: Mapping[str, Any]) -> dict[str, int]:
    """Priced positions, those with a resource breakdown, and those without."""
    priced = [p for p in payload.get("positions") or [] if is_priced(p)]
    with_breakdown = sum(1 for p in priced if p.get("resources"))
    return {
        "positions": len(priced),
        "with_breakdown": with_breakdown,
        "without_breakdown": len(priced) - with_breakdown,
    }


# ── Markup stack of one position ──────────────────────────────────────────────


def _ns(m: Mapping[str, Any], *, for_rate: bool = False) -> SimpleNamespace:
    """A sealed markup row in the shape the bill cascade reads."""
    markup_type = str(m.get("markup_type") or "percentage")
    excluded = for_rate and (
        str(m.get("category") or "").lower() in _EXCLUDED_CATEGORIES or markup_type not in ("percentage",)
    )
    return SimpleNamespace(
        id=m.get("key"),
        name=str(m.get("name") or ""),
        category=str(m.get("category") or ""),
        # A lump-sum or tax line has no place in a unit rate; it stays in the
        # stack (so later cumulative steps keep their order) but adds nothing.
        markup_type="fixed" if excluded else markup_type,
        percentage=str(m.get("percentage") or "0"),
        fixed_amount="0" if excluded else str(m.get("fixed_amount") or "0"),
        apply_to=str(m.get("apply_to") or "direct_cost"),
        sort_order=int(m.get("sort_order") or 0),
        is_active=bool(m.get("is_active", True)),
        scope_position_id=m.get("scope_ordinal") or None,
        overrides_id=m.get("overrides_key") or None,
        metadata_={},
    )


def markup_stack_for(payload: Mapping[str, Any], ordinal: str) -> list[SimpleNamespace]:
    """The sealed markup stack that applied to one position, overrides resolved.

    Uses the bill's own scope resolution so the stack read here is the one the
    bill applied when it was priced.
    """
    from app.modules.boq.service import _effective_stack, _scope_chain

    rows = [_ns(m, for_rate=True) for m in payload.get("markups") or [] if m.get("is_active", True)]
    bill_wide = [m for m in rows if m.scope_position_id is None]
    by_scope: dict[str, list[SimpleNamespace]] = {}
    for m in rows:
        if m.scope_position_id is not None:
            by_scope.setdefault(m.scope_position_id, []).append(m)
    parent_of = {str(p.get("ordinal")): p.get("parent_ordinal") or None for p in payload.get("positions") or []}
    chain = _scope_chain(ordinal, parent_of, set(by_scope))  # type: ignore[arg-type]
    return list(_effective_stack(bill_wide, by_scope, chain))  # type: ignore[arg-type]


def apply_stack(net: Decimal, stack: list[SimpleNamespace]) -> tuple[Decimal, list[dict[str, str]]]:
    """Run the bill cascade on a net unit cost; returns the rate and each step."""
    from app.modules.boq.service import _calculate_markup_amounts

    amounts = _calculate_markup_amounts(net, stack)  # type: ignore[arg-type]
    steps = [
        {
            "key": str(m.id or ""),
            "name": m.name,
            "percentage": m.percentage if m.markup_type == "percentage" else "0",
            "apply_to": m.apply_to,
            "amount": format(a, "f"),
        }
        for m, a in amounts
    ]
    return round2(net + sum((a for _m, a in amounts), _ZERO)), steps


def stack_from_rows(rows: Iterable[Mapping[str, Any]]) -> list[SimpleNamespace]:
    """A markup stack given as plain rows (a pack's cost-plus profit line, say)."""
    return [_ns({"key": f"cp{i + 1}", **r}, for_rate=True) for i, r in enumerate(rows)]


# ── Deriving a rate from the seal (rules S4-S6) ───────────────────────────────


def find_position(payload: Mapping[str, Any], ordinal: str) -> Mapping[str, Any] | None:
    """The sealed position with this ordinal, or None."""
    for p in payload.get("positions") or []:
        if str(p.get("ordinal")) == ordinal:
            return p
    return None


def _line_amount(consumption: Decimal, unit_cost: Decimal) -> Decimal:
    return round2(consumption * unit_cost)


def derive_rate(
    payload: Mapping[str, Any],
    ordinal: str,
    *,
    changes: Iterable[Mapping[str, Any]] = (),
    additions: Iterable[Mapping[str, Any]] = (),
    removals: Iterable[str] = (),
    quantity: Any = None,
    current_unit_costs: Mapping[str, Any] | None = None,
    cost_plus_stack: Iterable[Mapping[str, Any]] | None = None,
    agreed_rate: Any = None,
) -> dict[str, Any]:
    """Price one position of a change from the sealed basis, with cost plus beside it.

    Args:
        payload: The sealed payload.
        ordinal: Sealed position to start from.
        changes: Per sealed resource (matched by ``code``): new ``consumption``
            and/or ``unit_cost`` and a ``note``.
        additions: New resources: ``kind``, ``code``, ``description``, ``unit``,
            ``consumption``, ``unit_cost``, ``price_date``, ``quote_ref``.
        removals: Codes of sealed resources the change no longer uses.
        quantity: Quantity of the change (defaults to the sealed quantity).
        current_unit_costs: ``{code: today's unit cost}`` for the cost-plus side.
        cost_plus_stack: Markup rows for cost plus; ``None`` uses the sealed stack.
        agreed_rate: A rate the parties agreed, shown as its own method.

    Returns:
        Sealed lines, changed lines, both nets and rates, the markup steps and
        a ``methods`` list; ``chosen`` is never set here.

    Raises:
        KeyError: The ordinal is not in the seal.
    """
    position = find_position(payload, ordinal)
    if position is None:
        raise KeyError(ordinal)
    change_by_code = {str(c.get("code") or ""): c for c in changes}
    removed = {str(r) for r in removals}
    today = {str(k): dec(v) for k, v in (current_unit_costs or {}).items()}

    sealed_lines: list[dict[str, Any]] = []
    changed_lines: list[dict[str, Any]] = []
    cost_plus_lines: list[dict[str, Any]] = []
    sealed_net = _ZERO
    changed_net = _ZERO
    cost_plus_net = _ZERO

    for res in position.get("resources") or []:
        code = str(res.get("code") or "")
        s_cons, s_cost = dec(res.get("consumption")), dec(res.get("unit_cost"))
        s_amount = _line_amount(s_cons, s_cost)
        sealed_net += s_amount
        sealed_lines.append({**res, "amount": money(s_amount)})
        if code in removed:
            continue
        change = change_by_code.get(code, {})
        c_cons = dec(change["consumption"]) if change.get("consumption") not in (None, "") else s_cons
        c_cost = dec(change["unit_cost"]) if change.get("unit_cost") not in (None, "") else s_cost
        note = str(change.get("note") or "")
        c_amount = _line_amount(c_cons, c_cost)
        changed_net += c_amount
        changed_lines.append(
            {
                **res,
                "consumption": canon(c_cons),
                "unit_cost": canon(c_cost),
                "amount": money(c_amount),
                "sealed_consumption": res.get("consumption"),
                "sealed_unit_cost": res.get("unit_cost"),
                "consumption_changed": c_cons != s_cons,
                "unit_cost_changed": c_cost != s_cost,
                "note": note,
                "origin": "sealed",
            }
        )
        cp_cost = today.get(code, c_cost)
        cp_amount = _line_amount(c_cons, cp_cost)
        cost_plus_net += cp_amount
        cost_plus_lines.append(
            {"code": code, "consumption": canon(c_cons), "unit_cost": canon(cp_cost), "amount": money(cp_amount)}
        )

    for add in additions:
        a_cons, a_cost = dec(add.get("consumption")), dec(add.get("unit_cost"))
        a_amount = _line_amount(a_cons, a_cost)
        changed_net += a_amount
        line = resource_line(add)
        changed_lines.append(
            {
                **line,
                "amount": money(a_amount),
                "sealed_consumption": None,
                "sealed_unit_cost": None,
                "consumption_changed": False,
                "unit_cost_changed": False,
                "note": str(add.get("note") or ""),
                "origin": "new",
            }
        )
        cp_cost = today.get(line["code"], a_cost)
        cp_amount = _line_amount(a_cons, cp_cost)
        cost_plus_net += cp_amount
        cost_plus_lines.append(
            {
                "code": line["code"],
                "consumption": canon(a_cons),
                "unit_cost": canon(cp_cost),
                "amount": money(cp_amount),
            }
        )

    stack = markup_stack_for(payload, ordinal)
    sealed_rate, sealed_steps = apply_stack(sealed_net, stack)
    original_rate, original_steps = apply_stack(changed_net, stack)
    cp_stack = stack if cost_plus_stack is None else stack_from_rows(cost_plus_stack)
    cost_plus_rate, cost_plus_steps = apply_stack(cost_plus_net, cp_stack)

    qty = dec(quantity) if quantity not in (None, "") else dec(position.get("quantity"))
    methods = [
        {"method": "original_basis", "rate": money(original_rate), "total": money(original_rate * qty)},
        {"method": "cost_plus_markup", "rate": money(cost_plus_rate), "total": money(cost_plus_rate * qty)},
    ]
    if agreed_rate not in (None, ""):
        agreed = round2(dec(agreed_rate))
        methods.append({"method": "agreed", "rate": money(agreed), "total": money(agreed * qty)})

    return {
        "ordinal": ordinal,
        "description": position.get("description"),
        "unit": position.get("unit"),
        "quantity": canon(qty),
        "sealed_unit_rate": position.get("unit_rate"),
        "sealed_lines": sealed_lines,
        "changed_lines": changed_lines,
        "cost_plus_lines": cost_plus_lines,
        "sealed_net": money(sealed_net),
        "sealed_rate": money(sealed_rate),
        "changed_net": money(changed_net),
        "original_basis_rate": money(original_rate),
        "cost_plus_net": money(cost_plus_net),
        "cost_plus_rate": money(cost_plus_rate),
        "markup_steps": original_steps,
        "sealed_markup_steps": sealed_steps,
        "cost_plus_markup_steps": cost_plus_steps,
        "methods": methods,
        # Escalation is a contract mechanism of its own (price index); a carried
        # rate is never escalated here (rule S5).
        "escalation": None,
    }


def deviations(result: Mapping[str, Any]) -> list[dict[str, str]]:
    """Changed sealed values without a note (rule S6), one row per field."""
    out: list[dict[str, str]] = []
    for line in result.get("changed_lines") or []:
        if line.get("origin") != "sealed" or str(line.get("note") or "").strip():
            continue
        if line.get("consumption_changed"):
            out.append(
                {
                    "code": line["code"],
                    "field": "consumption",
                    "old": line["sealed_consumption"],
                    "new": line["consumption"],
                }
            )
        if line.get("unit_cost_changed"):
            out.append(
                {"code": line["code"], "field": "unit_cost", "old": line["sealed_unit_cost"], "new": line["unit_cost"]}
            )
    return out


def unevidenced_additions(result: Mapping[str, Any]) -> list[str]:
    """Codes of new resources that carry neither a quote nor a price date (rule S6)."""
    return [
        str(line.get("code") or line.get("description") or "")
        for line in result.get("changed_lines") or []
        if line.get("origin") == "new" and not (line.get("quote_ref") or line.get("price_date"))
    ]
