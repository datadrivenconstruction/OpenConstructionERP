# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure helpers for editable estimate templates.

No database and no HTTP in here: the shape of a template, the rules a template
is checked against before it is saved, and the conversion of a finished
estimate into a template. ``template_service`` and the router call these.

A template is ``{"sections": [{"ordinal", "description", "classification",
"positions": [{"ordinal", "description", "unit", "quantity", "qty_factor",
"rate", "classification"}]}], "markups": [...]}``. ``quantity`` is a fixed
default, ``qty_factor`` is multiplied by the gross floor area when the template
is expanded, and either may be blank. ``rate`` is optional. Money and
quantities are strings, as everywhere else in the BOQ module.

Every rule is a warning. A template with gaps is still a useful start, so
nothing here rejects a save; the editor shows the list and the author decides.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

SECTION_UNITS: tuple[str, ...] = ("", "section")

# Markup fields that survive the trip into a template. Anything tied to a
# single position (scope, overrides) is project data and is dropped.
_MARKUP_FIELDS = ("name", "markup_type", "category", "percentage", "fixed_amount", "apply_to")

RULE_NO_SECTIONS = "boq.template.has_sections"
RULE_NAME = "boq.template.name_present"
RULE_EMPTY_SECTION = "boq.template.section_not_empty"
RULE_SECTION_DESCRIPTION = "boq.template.section_described"
RULE_POSITION_UNIT = "boq.template.position_has_unit"
RULE_POSITION_DESCRIPTION = "boq.template.position_described"
RULE_DUPLICATE_ORDINAL = "boq.template.ordinal_unique"
RULE_UNCLASSIFIED = "boq.template.position_classified"
RULE_MARKUP_BAND = "boq.template.markup_within_band"

ALL_RULES: tuple[str, ...] = (
    RULE_NO_SECTIONS,
    RULE_NAME,
    RULE_EMPTY_SECTION,
    RULE_SECTION_DESCRIPTION,
    RULE_POSITION_UNIT,
    RULE_POSITION_DESCRIPTION,
    RULE_DUPLICATE_ORDINAL,
    RULE_UNCLASSIFIED,
    RULE_MARKUP_BAND,
)


def to_decimal(value: object) -> Decimal | None:
    """Parse a quantity or rate; blank, non-numeric and non-finite values read as ``None``."""
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def money_text(value: object) -> str | None:
    """Canonical string for a quantity or rate, ``None`` for blank."""
    parsed = to_decimal(value)
    if parsed is None:
        return None
    text = format(parsed.normalize(), "f")
    return "0" if text in ("-0", "") else text


def builtin_to_detail(template_id: str, tpl: dict[str, Any]) -> dict[str, Any]:
    """A built-in template in the editable shape (read only until it is copied)."""
    sections = []
    for sec in tpl["sections"]:
        sections.append(
            {
                "ordinal": sec["ordinal"],
                "description": sec["description"],
                "classification": {},
                "positions": [
                    {
                        "ordinal": pos["ordinal"],
                        "description": pos["description"],
                        "unit": pos["unit"],
                        "quantity": None,
                        "qty_factor": money_text(pos.get("qty_factor")),
                        "rate": money_text(pos.get("rate")),
                        "classification": {},
                    }
                    for pos in sec["positions"]
                ],
            }
        )
    return {
        "id": template_id,
        "builtin": True,
        "name": tpl["name"],
        "description": tpl["description"],
        "icon": tpl.get("icon", "FileText"),
        "classification_standard": "",
        "origin": "builtin",
        "copied_from": None,
        "sections": sections,
        "markups": [],
    }


def count_positions(sections: Iterable[dict[str, Any]]) -> int:
    return sum(len(sec.get("positions") or []) for sec in sections)


def cost_per_area(sections: Iterable[dict[str, Any]]) -> float | None:
    """Benchmark cost per unit of floor area: sum of ``qty_factor * rate``; ``None`` when nothing is priced that way."""
    total = Decimal(0)
    priced = False
    for sec in sections:
        for pos in sec.get("positions") or []:
            factor, rate = to_decimal(pos.get("qty_factor")), to_decimal(pos.get("rate"))
            if factor is not None and rate is not None:
                total += factor * rate
                priced = True
    return float(total) if priced else None


def renumber(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give sections ``01``, ``02`` ... and positions ``01.0010``, ``01.0020`` ... in list order."""
    out: list[dict[str, Any]] = []
    for s_idx, sec in enumerate(sections, start=1):
        sec_no = f"{s_idx:02d}"
        positions = []
        for p_idx, pos in enumerate(sec.get("positions") or [], start=1):
            positions.append({**pos, "ordinal": f"{sec_no}.{p_idx * 10:04d}"})
        out.append({**sec, "ordinal": sec_no, "positions": positions})
    return out


def drop_empty_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [sec for sec in sections if sec.get("positions")]


def _is_blank_line(pos: dict[str, Any]) -> bool:
    return not (pos.get("description") or "").strip() and not (pos.get("unit") or "").strip()


def validate_template(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Check a template and return warnings, each ``{rule_id, severity, path, params}``.

    ``path`` points at the offending row as ``{"section": i, "position": j}``
    (zero based, ``position`` absent for section-level and template-level
    findings), so the editor can mark the row.
    """
    issues: list[dict[str, Any]] = []

    def add(rule: str, section: int | None = None, position: int | None = None, **params: Any) -> None:
        path: dict[str, int] = {}
        if section is not None:
            path["section"] = section
        if position is not None:
            path["position"] = position
        issues.append({"rule_id": rule, "severity": "warning", "path": path, "params": params})

    if not (detail.get("name") or "").strip():
        add(RULE_NAME)

    sections = detail.get("sections") or []
    if not sections:
        add(RULE_NO_SECTIONS)

    standard = (detail.get("classification_standard") or "").strip()
    seen: dict[str, tuple[int, int]] = {}
    dup_reported: set[str] = set()
    for s_idx, sec in enumerate(sections):
        positions = sec.get("positions") or []
        if not (sec.get("description") or "").strip():
            add(RULE_SECTION_DESCRIPTION, s_idx, ordinal=sec.get("ordinal", ""))
        if not positions:
            add(RULE_EMPTY_SECTION, s_idx, ordinal=sec.get("ordinal", ""), name=sec.get("description", ""))
        for p_idx, pos in enumerate(positions):
            ordinal = (pos.get("ordinal") or "").strip()
            if not (pos.get("description") or "").strip():
                add(RULE_POSITION_DESCRIPTION, s_idx, p_idx, ordinal=ordinal)
            if not (pos.get("unit") or "").strip():
                add(RULE_POSITION_UNIT, s_idx, p_idx, ordinal=ordinal)
            if standard and not any((pos.get("classification") or {}).values()):
                add(RULE_UNCLASSIFIED, s_idx, p_idx, ordinal=ordinal, standard=standard)
            if ordinal:
                if ordinal in seen:
                    if ordinal not in dup_reported:
                        dup_reported.add(ordinal)
                        first = seen[ordinal]
                        add(RULE_DUPLICATE_ORDINAL, first[0], first[1], ordinal=ordinal)
                    add(RULE_DUPLICATE_ORDINAL, s_idx, p_idx, ordinal=ordinal)
                else:
                    seen[ordinal] = (s_idx, p_idx)

    for m_idx, markup in enumerate(detail.get("markups") or []):
        pct = to_decimal(markup.get("percentage"))
        if pct is not None and not (Decimal(0) <= pct <= Decimal(100)):
            add(RULE_MARKUP_BAND, name=markup.get("name", ""), percentage=str(pct), index=m_idx)
    return issues


def _item_from_position(pos: Any, *, keep_quantities: bool, keep_rates: bool) -> dict[str, Any]:
    classification = {str(k): str(v) for k, v in (pos.classification or {}).items() if v not in (None, "")}
    return {
        "ordinal": (pos.ordinal or "").strip(),
        "description": (pos.description or "").strip(),
        "unit": (pos.unit or "").strip(),
        "quantity": money_text(pos.quantity) if keep_quantities else None,
        "qty_factor": None,
        "rate": money_text(pos.unit_rate) if keep_rates else None,
        "classification": classification,
    }


def sections_from_positions(
    positions: list[Any],
    *,
    keep_quantities: bool,
    keep_rates: bool,
    renumber_positions: bool = True,
    ungrouped_name: str = "General",
) -> list[dict[str, Any]]:
    """Turn the rows of an estimate into template sections.

    Only structure and defaults are copied: ordinal, description, unit,
    classification codes and, on request, quantity and rate. Everything that
    ties a row to its project (BIM links, cost-code and WBS links, actuals,
    notes, attachments, source and validation state) stays behind. Nested
    sections become sections of their own, in reading order. Empty sections
    are dropped and, by default, the ordinals are renumbered.
    """
    ordered = sorted(positions, key=lambda p: (p.sort_order or 0, p.ordinal or ""))
    by_id = {p.id: p for p in ordered}

    def is_section(p: Any) -> bool:
        unit = (p.unit or "").strip().lower()
        return unit in SECTION_UNITS and (to_decimal(p.quantity) or 0) == 0 and (to_decimal(p.unit_rate) or 0) == 0

    sections: list[dict[str, Any]] = []
    by_section: dict[Any, dict[str, Any]] = {}
    ungrouped: dict[str, Any] | None = None

    for pos in ordered:
        if is_section(pos):
            sec = {
                "ordinal": (pos.ordinal or "").strip(),
                "description": (pos.description or "").strip(),
                "classification": {str(k): str(v) for k, v in (pos.classification or {}).items() if v},
                "positions": [],
            }
            by_section[pos.id] = sec
            sections.append(sec)
            continue
        item = _item_from_position(pos, keep_quantities=keep_quantities, keep_rates=keep_rates)
        if _is_blank_line(item):
            continue
        parent = by_id.get(pos.parent_id) if pos.parent_id else None
        target = by_section.get(parent.id) if parent is not None else None
        if target is None:
            if ungrouped is None:
                ungrouped = {"ordinal": "", "description": ungrouped_name, "classification": {}, "positions": []}
                sections.append(ungrouped)
            target = ungrouped
        target["positions"].append(item)

    sections = drop_empty_sections(sections)
    return renumber(sections) if renumber_positions else sections


def markups_from_rows(markups: Iterable[Any]) -> list[dict[str, Any]]:
    """Active, bill-wide markup lines only; lines scoped to a position are project data."""
    out = []
    for m in sorted(markups, key=lambda x: x.sort_order or 0):
        if not m.is_active or getattr(m, "scope_position_id", None) or getattr(m, "overrides_id", None):
            continue
        out.append({f: getattr(m, f) for f in _MARKUP_FIELDS})
    return out


def expand_quantity(pos: dict[str, Any], area: Decimal | None) -> Decimal:
    """Quantity of a template line when a bill is made from it."""
    factor = to_decimal(pos.get("qty_factor"))
    if factor is not None and area is not None:
        return area * factor
    fixed = to_decimal(pos.get("quantity"))
    return fixed if fixed is not None else Decimal(0)
