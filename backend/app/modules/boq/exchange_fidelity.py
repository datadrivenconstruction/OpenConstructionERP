# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Exchange fidelity: what did not survive an import or an export.

Every exchange format holds less than the bill does, and each holds a
different less. GAEB cuts a quantity to three decimals and a unit to four
characters, BC3 has no place for a surcharge, a spreadsheet keeps the amount
of a markup and forgets its rule. A surveyor who sends a file needs to know
which of those happened to *this* bill before the recipient finds out.

This module answers that as a list of :class:`FidelityItem` rows, one per
thing that changed or went missing: its severity, the position it belongs
to, the field, the value the bill held and the value the file carries.

It is pure (no session, no FastAPI): the exporters hand it a *trace* of what
they actually wrote (``build_gaeb_xml(trace=...)``, ``build_bc3(trace=...)``)
and the importers record what they left behind on ``ImportedBOQ.fidelity``,
so the report describes the writer's real behaviour rather than a copy of
its rules that could drift. :func:`roundtrip_diff` is the independent check:
the exported bytes are read back by the matching importer and compared with
the bill, field by field.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from app.core.csv_safety import neutralise_formula
from app.modules.boq.units import is_registry_unit, normalise_unit, unit_identity_key

Severity = Literal["error", "warning", "info"]
Direction = Literal["import", "export"]

SEVERITIES: tuple[str, ...] = ("error", "warning", "info")

#: Every kind of loss the report names. The frontend words each one from
#: ``boq.fidelity.kind.<kind>`` and the downloads from the backend catalogue.
KINDS: tuple[str, ...] = (
    "unsupported_element",
    "truncated_text",
    "altered_text",
    "rounded_value",
    "value_out_of_range",
    "dropped_attribute",
    "unmapped_unit",
    "lost_hierarchy",
    "markup_not_representable",
    "attachment_skipped",
    "changed_identifier",
    "exceeds_limit",
    "rejected_row",
    "skipped_row",
    "parser_warning",
    "roundtrip_mismatch",
)

#: Formats an export can be checked for, and the importer that reads each back.
EXPORT_FORMATS: tuple[str, ...] = ("gaeb_xml", "bc3", "excel", "csv")
ROUNDTRIP_READER: dict[str, str] = {"gaeb_xml": "gaeb_xml", "bc3": "bc3", "excel": "excel", "csv": "excel"}

#: Items kept per report. Counts in the summary always cover every item; a
#: bill of tens of thousands of lines must not store a report the size of
#: the bill itself (principle 1, the 3 GB server).
MAX_STORED_ITEMS = 2000

#: Excel keeps at most this many characters in one cell.
EXCEL_CELL_MAX_CHARS = 32767
#: Excel stores numbers as IEEE doubles: 15 significant digits survive.
EXCEL_SIGNIFICANT_DIGITS = 15
#: Characters a spreadsheet exporter prefixes with an apostrophe.
_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")
#: GAEB DA XML ``tgDecimal_11_3``: eight integer digits.
GAEB_QTY_MAX = Decimal("99999999.999")
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_WS = re.compile(r"\s+")

#: Storage precision of quantity and unit rate on a position (4 dp).
_STORAGE_QUANTUM = Decimal("0.0001")


@dataclass(slots=True)
class FidelityItem:
    """One thing an exchange did not carry across unchanged."""

    severity: Severity
    kind: str
    field: str
    position_ref: str = ""
    position_id: str | None = None
    original: str | None = None
    written: str | None = None
    count: int = 1
    detail: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The item as stored and sent to the client."""
        return {
            "severity": self.severity,
            "kind": self.kind,
            "field": self.field,
            "position_ref": self.position_ref,
            "position_id": self.position_id,
            "original": self.original,
            "written": self.written,
            "count": self.count,
            "detail": self.detail,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> FidelityItem:
        """Build an item from an importer's note, tolerating missing keys."""
        severity = str(raw.get("severity") or "warning")
        if severity not in SEVERITIES:
            severity = "warning"
        kind = str(raw.get("kind") or "parser_warning")
        if kind not in KINDS:
            kind = "parser_warning"
        return cls(
            severity=severity,  # type: ignore[arg-type]
            kind=kind,
            field=str(raw.get("field") or ""),
            position_ref=str(raw.get("position_ref") or ""),
            position_id=(str(raw["position_id"]) if raw.get("position_id") else None),
            original=_s(raw.get("original")),
            written=_s(raw.get("written")),
            count=max(1, int(raw.get("count") or 1)),
            detail=str(raw.get("detail") or ""),
            params=dict(raw.get("params") or {}),
        )


@dataclass(slots=True)
class FidelityReport:
    """Every item of one import or export, with the counts the UI headlines."""

    direction: Direction
    format_id: str
    variant: str = ""
    roundtrip: bool = False
    items: list[FidelityItem] = field(default_factory=list)

    def add(self, severity: Severity, kind: str, fld: str, **kwargs: Any) -> None:
        """Append one item; ``kwargs`` are the remaining :class:`FidelityItem` fields."""
        self.items.append(FidelityItem(severity=severity, kind=kind, field=fld, **kwargs))

    def extend(self, items: Iterable[FidelityItem]) -> None:
        """Append items built elsewhere (an importer's notes, a round-trip diff)."""
        self.items.extend(items)

    def summary(self) -> dict[str, Any]:
        """Counts by severity and by kind, over every item (stored or not)."""
        by_severity = dict.fromkeys(SEVERITIES, 0)
        by_kind: dict[str, int] = {}
        for item in self.items:
            by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
            by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        return {
            "total": len(self.items),
            "by_severity": by_severity,
            "by_kind": dict(sorted(by_kind.items())),
            "critical": by_severity["error"],
            "lossless": not self.items,
        }

    def sorted_items(self) -> list[FidelityItem]:
        """Errors first, then warnings, then notes; stable within a severity."""
        rank = {s: i for i, s in enumerate(SEVERITIES)}
        return sorted(self.items, key=lambda it: rank.get(it.severity, 9))

    def to_dict(self) -> dict[str, Any]:
        """The report as stored and returned; items capped at :data:`MAX_STORED_ITEMS`."""
        ordered = self.sorted_items()
        return {
            "direction": self.direction,
            "format_id": self.format_id,
            "variant": self.variant,
            "roundtrip": self.roundtrip,
            "summary": self.summary(),
            "items": [it.to_dict() for it in ordered[:MAX_STORED_ITEMS]],
            "items_truncated": len(ordered) > MAX_STORED_ITEMS,
        }


# ── small helpers ──────────────────────────────────────────────────────────


def _s(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _plain(d: Decimal | None) -> str:
    if d is None:
        return ""
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _significant_digits(d: Decimal) -> int:
    digits = d.normalize().as_tuple().digits
    return len(digits)


def _meta(obj: Any) -> dict[str, Any]:
    meta = getattr(obj, "metadata", None)
    if not isinstance(meta, dict):
        meta = getattr(obj, "metadata_", None)
    return meta if isinstance(meta, dict) else {}


def _pid(obj: Any) -> str | None:
    value = getattr(obj, "id", None)
    return str(value) if value else None


def _ordinal(obj: Any) -> str:
    return str(getattr(obj, "ordinal", "") or "")


def iter_export_positions(structured: Any) -> Iterator[tuple[Any | None, Any]]:
    """Every exported leaf in writer order: section by section, then ungrouped."""
    for section in getattr(structured, "sections", None) or []:
        for pos in getattr(section, "positions", None) or []:
            yield section, pos
    for pos in getattr(structured, "positions", None) or []:
        yield None, pos


def _active_markups(structured: Any) -> list[Any]:
    return [m for m in getattr(structured, "markups", None) or [] if getattr(m, "is_active", True)]


def _markup_rule(markup: Any) -> str:
    pct = _dec(getattr(markup, "percentage", None))
    apply_to = str(getattr(markup, "apply_to", "") or "direct_cost")
    if pct:
        return f"{_plain(pct)}% on {apply_to}"
    return str(getattr(markup, "markup_type", "") or "fixed")


# ── hierarchy ──────────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class TreeRow:
    """The minimum of a stored position the hierarchy check needs."""

    id: str
    parent_id: str | None
    ordinal: str
    is_section: bool


def tree_rows(positions: Iterable[Any], is_section: Callable[[Any], bool]) -> list[TreeRow]:
    """Reduce stored positions to :class:`TreeRow` (``is_section`` is the service's own test)."""
    return [
        TreeRow(
            id=str(p.id),
            parent_id=str(p.parent_id) if getattr(p, "parent_id", None) else None,
            ordinal=_ordinal(p),
            is_section=bool(is_section(p)),
        )
        for p in positions
    ]


def flattened_levels(rows: Iterable[TreeRow]) -> list[tuple[TreeRow, str]]:
    """Rows whose place in the tree an export with one section level cannot keep.

    Returns ``(row, parent_ordinal)`` for every section nested under another
    section and every line filed under another line rather than a section:
    the structured export payload lists both at the top level.
    """
    by_id = {r.id: r for r in rows}
    lost: list[tuple[TreeRow, str]] = []
    for row in by_id.values():
        parent = by_id.get(row.parent_id or "")
        if parent is None:
            continue
        if row.is_section and parent.is_section or not row.is_section and not parent.is_section:
            lost.append((row, parent.ordinal))
    return lost


def _add_hierarchy(report: FidelityReport, tree: Iterable[TreeRow] | None, severity: Severity) -> None:
    for row, parent_ordinal in flattened_levels(tree or []):
        report.add(
            severity,
            "lost_hierarchy",
            "hierarchy",
            position_ref=row.ordinal,
            position_id=row.id,
            original=f"{parent_ordinal} > {row.ordinal}",
            written=row.ordinal,
        )


def _add_dropped_resources(report: FidelityReport, structured: Any, severity: Severity) -> None:
    for _section, pos in iter_export_positions(structured):
        resources = _meta(pos).get("resources")
        if isinstance(resources, list) and resources:
            report.add(
                severity,
                "dropped_attribute",
                "resources",
                position_ref=_ordinal(pos),
                position_id=_pid(pos),
                original=f"{len(resources)} resources",
                params={"count": len(resources)},
            )


def _add_dropped_classifications(report: FidelityReport, structured: Any, keep: frozenset[str]) -> None:
    counts: dict[str, int] = {}
    first: dict[str, Any] = {}
    for _section, pos in iter_export_positions(structured):
        classification = getattr(pos, "classification", None)
        if not isinstance(classification, dict):
            continue
        for system, code in classification.items():
            if system in keep or not str(code or "").strip():
                continue
            counts[system] = counts.get(system, 0) + 1
            first.setdefault(system, pos)
    for system, count in sorted(counts.items()):
        pos = first[system]
        report.add(
            "info",
            "dropped_attribute",
            "classification",
            position_ref=_ordinal(pos),
            position_id=_pid(pos),
            original=system,
            count=count,
            params={"system": system},
        )


# ── GAEB DA XML export ─────────────────────────────────────────────────────


def _oz_key(oz: str) -> tuple[str, ...]:
    """Compare OZ segments ignoring zero padding (``01.0010`` == ``1.10``)."""
    parts = []
    for seg in (oz or "").split("."):
        seg = seg.strip()
        if not seg:
            continue
        parts.append(str(int(seg)) if seg.isdigit() else seg.casefold())
    return tuple(parts)


def analyze_gaeb_export(
    structured: Any,
    trace: list[dict[str, Any]],
    *,
    variant: str,
    project_name: str = "",
    tree: Iterable[TreeRow] | None = None,
) -> FidelityReport:
    """What a GAEB DA XML export of ``structured`` lost, from the writer's trace."""
    report = FidelityReport(direction="export", format_id="gaeb_xml", variant=variant)
    priced = variant == "x84"
    written_items = {rec.get("id"): rec for rec in trace if rec.get("type") == "item"}
    boq_rec = next((rec for rec in trace if rec.get("type") == "boq"), {})

    name = str(getattr(structured, "name", "") or "")
    if boq_rec and boq_rec.get("name") != name:
        report.add(
            "warning",
            "truncated_text",
            "boq.name",
            original=name,
            written=boq_rec.get("name"),
            params={"limit": 20},
        )
    if boq_rec and project_name and boq_rec.get("project_name") != project_name:
        report.add(
            "warning",
            "truncated_text",
            "project.name",
            original=project_name,
            written=boq_rec.get("project_name"),
            params={"limit": 60},
        )

    leaves = list(iter_export_positions(structured))
    for _section, pos in leaves:
        pid = _pid(pos)
        rec = written_items.get(pid or "")
        if rec is None:
            continue
        ordinal = _ordinal(pos)
        ref = {"position_ref": ordinal, "position_id": pid}

        oz = str(rec.get("oz") or "")
        if ordinal and _oz_key(oz) != _oz_key(ordinal):
            report.add("warning", "changed_identifier", "ordinal", original=ordinal, written=oz, **ref)

        qty = _dec(getattr(pos, "quantity", None))
        qty_w = _dec(rec.get("qty"))
        if qty is not None and abs(qty) > GAEB_QTY_MAX:
            report.add(
                "error",
                "value_out_of_range",
                "quantity",
                original=_plain(qty),
                written=rec.get("qty"),
                params={"limit": str(GAEB_QTY_MAX)},
                **ref,
            )
        elif qty is not None and qty_w is not None and qty != qty_w:
            report.add(
                "info",
                "rounded_value",
                "quantity",
                original=_plain(qty),
                written=rec.get("qty"),
                params={"dp": 3},
                **ref,
            )

        if priced:
            rate = _dec(getattr(pos, "unit_rate", None))
            up_w = _dec(rec.get("up"))
            if rate is not None and up_w is not None and rate != up_w:
                report.add(
                    "info",
                    "rounded_value",
                    "unit_rate",
                    original=_plain(rate),
                    written=rec.get("up"),
                    params={"dp": 3},
                    **ref,
                )
            total = _dec(getattr(pos, "total", None))
            it_w = _dec(rec.get("it"))
            if total is not None and it_w is not None:
                delta = abs(total - it_w)
                if delta >= Decimal("0.01"):
                    severe = total != 0 and delta / abs(total) > Decimal("0.01")
                    report.add(
                        "error" if severe else "warning",
                        "rounded_value",
                        "total",
                        original=_plain(total),
                        written=rec.get("it"),
                        params={"delta": _plain(delta)},
                        **ref,
                    )
        else:
            unit = str(getattr(pos, "unit", "") or "")
            qu = rec.get("qu")
            if qu is not None:
                from app.modules.boq.units import to_gaeb_unit_code

                code = to_gaeb_unit_code(unit)
                if len(code) > len(qu):
                    report.add(
                        "warning", "truncated_text", "unit", original=code, written=qu, params={"limit": 4}, **ref
                    )
                elif unit and not is_registry_unit(unit):
                    report.add("info", "unmapped_unit", "unit", original=unit, written=qu, **ref)

        description = str(getattr(pos, "description", "") or "")
        if rec.get("text_written") and _XML_ILLEGAL.search(description):
            report.add(
                "info",
                "altered_text",
                "description",
                original=description[:200],
                written=_XML_ILLEGAL.sub("", description)[:200],
                **ref,
            )

    if priced and leaves:
        report.add(
            "info",
            "dropped_attribute",
            "description",
            count=len(leaves),
            detail="An X84 bid carries no long text; it travels in the paired X83.",
            params={"by_design": True},
        )
    if not priced:
        priced_leaves = [p for _s2, p in leaves if (_dec(getattr(p, "unit_rate", None)) or 0) != 0]
        if priced_leaves:
            report.add(
                "info",
                "dropped_attribute",
                "unit_rate",
                count=len(priced_leaves),
                detail="An X83 call for bids carries no prices.",
                params={"by_design": True},
            )
        for markup in _active_markups(structured):
            report.add(
                "info",
                "markup_not_representable",
                "markup",
                position_ref=str(getattr(markup, "name", "") or ""),
                original=_markup_rule(markup),
                params={"by_design": True},
            )
    else:
        written_markups = {rec.get("id"): rec for rec in trace if rec.get("type") == "markup"}
        for markup in _active_markups(structured):
            rec = written_markups.get(str(getattr(markup, "id", "") or ""))
            pct = _dec(getattr(markup, "percentage", None))
            if rec is not None and pct and _dec(rec.get("pct")) != pct:
                report.add(
                    "info",
                    "rounded_value",
                    "markup",
                    position_ref=str(getattr(markup, "name", "") or ""),
                    original=_plain(pct),
                    written=rec.get("pct"),
                )

    _add_dropped_resources(report, structured, "warning")
    _add_dropped_classifications(report, structured, keep=frozenset())
    _add_hierarchy(report, tree, "warning")
    return report


# ── BC3 export ─────────────────────────────────────────────────────────────


def analyze_bc3_export(
    structured: Any,
    trace: list[dict[str, Any]],
    *,
    tree: Iterable[TreeRow] | None = None,
) -> FidelityReport:
    """What a FIEBDC-3 (BC3) export of ``structured`` lost, from the writer's trace."""
    from app.modules.boq.exporters.bc3 import _UNIT_TO_BC3

    report = FidelityReport(direction="export", format_id="bc3")
    written_items = {rec.get("id"): rec for rec in trace if rec.get("type") == "item"}
    written_sections = {rec.get("id"): rec for rec in trace if rec.get("type") == "section"}

    for section in getattr(structured, "sections", None) or []:
        rec = written_sections.get(_pid(section) or "")
        if rec is None:
            continue
        ordinal = _ordinal(section)
        if ordinal and rec.get("code") != ordinal:
            report.add(
                "warning",
                "changed_identifier",
                "ordinal",
                position_ref=ordinal,
                position_id=_pid(section),
                original=ordinal,
                written=rec.get("code"),
            )

    for _section, pos in iter_export_positions(structured):
        pid = _pid(pos)
        rec = written_items.get(pid or "")
        if rec is None:
            continue
        ordinal = _ordinal(pos)
        meta = _meta(pos)
        ref = {"position_ref": ordinal, "position_id": pid}
        classification = getattr(pos, "classification", None) or {}
        code_source = (
            (str(classification.get("bc3_code") or "") if isinstance(classification, dict) else "")
            or str(getattr(pos, "reference_code", "") or "")
            or ordinal
        )
        if code_source and rec.get("code") != code_source:
            report.add("warning", "changed_identifier", "ordinal", original=code_source, written=rec.get("code"), **ref)
        description = str(getattr(pos, "description", "") or "")
        summary = str(rec.get("summary") or "")
        if summary != _norm_text(description):
            report.add(
                "warning", "altered_text", "description", original=description[:500], written=summary[:500], **ref
            )
        elif "\n" in description.strip():
            report.add(
                "info",
                "altered_text",
                "description",
                original=description[:500],
                written=summary[:500],
                params={"line_breaks": True},
                **ref,
            )
        unit = str(getattr(pos, "unit", "") or "").strip()
        if (
            unit
            and not str(meta.get("bc3_unit_original") or "").strip()
            and unit.lower() not in _UNIT_TO_BC3
            and not is_registry_unit(unit)
        ):
            report.add("info", "unmapped_unit", "unit", original=unit, written=rec.get("unit"), **ref)
        qty = _dec(getattr(pos, "quantity", None))
        if qty is not None and qty < 0:
            report.add("error", "value_out_of_range", "quantity", original=_plain(qty), written=rec.get("qty"), **ref)

    for markup in _active_markups(structured):
        report.add(
            "warning",
            "markup_not_representable",
            "markup",
            position_ref=str(getattr(markup, "name", "") or ""),
            original=f"{_markup_rule(markup)} = {_plain(_dec(getattr(markup, 'amount', None)))}",
            written=None,
        )

    _add_dropped_resources(report, structured, "warning")
    _add_dropped_classifications(report, structured, keep=frozenset({"bc3_code"}))
    _add_hierarchy(report, tree, "warning")
    return report


# ── spreadsheet export (Excel, CSV) ────────────────────────────────────────


def analyze_sheet_export(
    structured: Any,
    *,
    format_id: Literal["excel", "csv"],
    tree: Iterable[TreeRow] | None = None,
) -> FidelityReport:
    """What a spreadsheet export of ``structured`` lost.

    The writers keep full precision and every attribute (classification,
    resources and the rest of metadata travel as JSON columns), so the losses
    are the sheet's own: Excel's cell size and number precision, the
    apostrophe that defuses a formula, and a markup reduced to its amount.
    """
    report = FidelityReport(direction="export", format_id=format_id)
    excel = format_id == "excel"
    for _section, pos in iter_export_positions(structured):
        ordinal = _ordinal(pos)
        ref = {"position_ref": ordinal, "position_id": _pid(pos)}
        for fld in ("ordinal", "description", "unit"):
            text = str(getattr(pos, fld, "") or "")
            if text and neutralise_formula(text) != text:
                report.add("info", "altered_text", fld, original=text[:200], written=f"'{text[:199]}", **ref)
        if excel:
            texts = {
                "description": str(getattr(pos, "description", "") or ""),
                "metadata": json.dumps(_meta(pos), ensure_ascii=False) if _meta(pos) else "",
                "classification": json.dumps(getattr(pos, "classification", None) or {}, ensure_ascii=False),
            }
            for fld, text in texts.items():
                if len(text) > EXCEL_CELL_MAX_CHARS:
                    report.add(
                        "warning",
                        "truncated_text",
                        fld,
                        original=f"{len(text)} chars",
                        written=f"{EXCEL_CELL_MAX_CHARS} chars",
                        params={"limit": EXCEL_CELL_MAX_CHARS},
                        **ref,
                    )
            for fld in ("quantity", "unit_rate", "total"):
                value = _dec(getattr(pos, fld, None))
                if value is not None and value != 0 and _significant_digits(value) > EXCEL_SIGNIFICANT_DIGITS:
                    rounded = Decimal(repr(float(value)))
                    report.add(
                        "info",
                        "rounded_value",
                        fld,
                        original=_plain(value),
                        written=_plain(rounded),
                        params={"digits": EXCEL_SIGNIFICANT_DIGITS},
                        **ref,
                    )
    for markup in _active_markups(structured):
        report.add(
            "info",
            "markup_not_representable",
            "markup",
            position_ref=str(getattr(markup, "name", "") or ""),
            original=_markup_rule(markup),
            written=_plain(_dec(getattr(markup, "amount", None))),
        )
    _add_hierarchy(report, tree, "info")
    return report


# ── import ─────────────────────────────────────────────────────────────────


def _storage_limits() -> dict[str, int]:
    """Text limits of a stored position, read from the create schema itself."""
    from app.modules.boq.schemas import PositionCreate

    limits: dict[str, int] = {}
    for name in ("ordinal", "description", "unit"):
        info = PositionCreate.model_fields[name]
        for constraint in info.metadata:
            max_length = getattr(constraint, "max_length", None)
            if max_length:
                limits[name] = int(max_length)
    return limits


def _original_unit(meta: Mapping[str, Any]) -> tuple[bool, str]:
    """Whether the file recorded its own unit for this row, and what it was."""
    for key in ("gaeb_unit_original", "bc3_unit_original", "unit_original"):
        if key in meta:
            return True, str(meta.get(key) or "").strip()
    return False, ""


def _xlsx_media_count(raw: bytes) -> int:
    if raw[:4] != b"PK\x03\x04":
        return 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            return sum(1 for n in zf.namelist() if n.startswith("xl/media/") or n.startswith("xl/embeddings/"))
    except (zipfile.BadZipFile, OSError, ValueError):
        return 0


def analyze_import(format_id: str, imported: Any, raw: bytes | None = None) -> FidelityReport:
    """What an import of ``imported`` (an ``ImportedBOQ``) will not carry into the bill."""
    report = FidelityReport(direction="import", format_id=format_id)
    report.extend(FidelityItem.from_dict(note) for note in getattr(imported, "fidelity", None) or [])

    for err in getattr(imported, "errors", None) or []:
        report.add(
            "error",
            "rejected_row",
            "row",
            position_ref=str(err.get("ordinal") or ""),
            detail=str(err.get("error") or err.get("message") or ""),
        )
    for warn in getattr(imported, "warnings", None) or []:
        text = warn.get("warning") or warn.get("message") or warn.get("code") or ""
        report.add(
            "warning",
            "parser_warning",
            "row",
            position_ref=str(warn.get("ordinal") or ""),
            detail=str(text),
            params={k: v for k, v in warn.items() if k in ("code", "params") and v},
        )
    skipped = int(getattr(imported, "skipped", 0) or 0)
    if skipped:
        report.add("info", "skipped_row", "row", count=skipped)

    limits = _storage_limits()
    for row in getattr(imported, "positions", None) or []:
        ordinal = str(getattr(row, "ordinal", "") or "")
        meta = getattr(row, "metadata", None) or {}
        for fld, limit in limits.items():
            text = str(getattr(row, fld, "") or "")
            if len(text) > limit:
                report.add(
                    "error",
                    "exceeds_limit",
                    fld,
                    position_ref=ordinal,
                    original=text[:200],
                    written=None,
                    params={"limit": limit, "length": len(text)},
                )
        if getattr(row, "is_section", False):
            continue
        for fld in ("quantity", "unit_rate"):
            value = _dec(getattr(row, fld, None))
            if value is None:
                continue
            stored = value.quantize(_STORAGE_QUANTUM, rounding=ROUND_HALF_UP)
            if stored != value:
                report.add(
                    "info",
                    "rounded_value",
                    fld,
                    position_ref=ordinal,
                    original=_plain(value),
                    written=_plain(stored),
                    params={"dp": 4},
                )
        unit = str(getattr(row, "unit", "") or "")
        recorded, original_unit = _original_unit(meta)
        if recorded and not original_unit:
            report.add("warning", "unmapped_unit", "unit", position_ref=ordinal, original="", written=unit)
        elif unit and not is_registry_unit(unit) and normalise_unit(unit) is not None:
            report.add(
                "info", "unmapped_unit", "unit", position_ref=ordinal, original=original_unit or unit, written=unit
            )

    metadata = getattr(imported, "metadata", None) or {}
    for markup in metadata.get("markup_items") or []:
        if not isinstance(markup, dict):
            continue
        pct, amount = str(markup.get("percentage") or ""), str(markup.get("it") or "")
        report.add(
            "info",
            "markup_not_representable",
            "markup",
            position_ref=str(markup.get("ordinal") or ""),
            original=f"{pct}% = {amount}" if pct else amount,
            written=amount or (f"{pct}%" if pct else None),
            params={"as": "fixed" if amount else ("percentage" if pct else "skipped")},
        )

    columns = metadata.get("original_columns")
    mapping = metadata.get("column_mapping")
    if isinstance(columns, list) and isinstance(mapping, dict):
        for index, header in enumerate(columns):
            if str(index) in mapping or not str(header or "").strip():
                continue
            report.add("info", "dropped_attribute", "column", original=str(header), params={"column": index})

    if raw is not None and format_id == "excel":
        media = _xlsx_media_count(raw)
        if media:
            report.add("warning", "attachment_skipped", "attachment", count=media, original=f"{media} embedded files")
    return report


# ── round trip ─────────────────────────────────────────────────────────────


def _norm_text(text: Any) -> str:
    return _WS.sub(" ", str(text or "")).strip()


def _norm_unit(unit: Any) -> str:
    canonical = normalise_unit(str(unit or "")) or str(unit or "")
    return unit_identity_key(canonical) if canonical else ""


def _close(a: Decimal, b: Decimal, quantum: Decimal) -> bool:
    return abs(a - b) <= quantum


def roundtrip_diff(
    structured: Any,
    reimported: Any,
    *,
    compare_prices: bool = True,
    compare_text: bool = True,
    compare_units: bool = True,
    quantity_quantum: Decimal = Decimal("0.0005"),
    money_quantum: Decimal = Decimal("0.005"),
) -> list[FidelityItem]:
    """Compare the bill with what its export reads back as.

    Lines are paired in writer order, the order every writer and reader in
    this package keeps. When the counts differ the pairing falls back to the
    ordinal, and every line without a partner is reported on its own.
    Differences inside the rounding the format declares are not repeated
    here; the export analysis already names them.
    """
    items: list[FidelityItem] = []
    original = [pos for _s, pos in iter_export_positions(structured)]
    back = [p for p in getattr(reimported, "positions", None) or [] if not getattr(p, "is_section", False)]

    if len(original) != len(back):
        items.append(
            FidelityItem(
                severity="error",
                kind="roundtrip_mismatch",
                field="row",
                original=str(len(original)),
                written=str(len(back)),
                detail="The file reads back with a different number of lines.",
            )
        )
        by_ordinal = {_oz_key(str(getattr(p, "ordinal", "") or "")): p for p in back}
        pairs = [(pos, by_ordinal.get(_oz_key(_ordinal(pos)))) for pos in original]
    else:
        pairs = list(zip(original, back, strict=True))

    for pos, other in pairs:
        ordinal = _ordinal(pos)
        ref = {"position_ref": ordinal, "position_id": _pid(pos)}
        if other is None:
            items.append(
                FidelityItem(
                    severity="error", kind="roundtrip_mismatch", field="row", original=ordinal, written=None, **ref
                )
            )
            continue
        q_a, q_b = (
            _dec(getattr(pos, "quantity", None)) or Decimal(0),
            _dec(getattr(other, "quantity", None)) or Decimal(0),
        )
        if not _close(q_a, q_b, quantity_quantum):
            items.append(
                FidelityItem(
                    severity="error",
                    kind="roundtrip_mismatch",
                    field="quantity",
                    original=_plain(q_a),
                    written=_plain(q_b),
                    **ref,
                )
            )
        if compare_prices:
            r_a = _dec(getattr(pos, "unit_rate", None)) or Decimal(0)
            r_b = _dec(getattr(other, "unit_rate", None)) or Decimal(0)
            if not _close(r_a, r_b, money_quantum):
                items.append(
                    FidelityItem(
                        severity="error",
                        kind="roundtrip_mismatch",
                        field="unit_rate",
                        original=_plain(r_a),
                        written=_plain(r_b),
                        **ref,
                    )
                )
            t_a = _dec(getattr(pos, "total", None)) or Decimal(0)
            t_b = q_b * r_b
            if not _close(t_a, t_b, max(money_quantum, Decimal("0.01"))):
                items.append(
                    FidelityItem(
                        severity="error",
                        kind="roundtrip_mismatch",
                        field="total",
                        original=_plain(t_a),
                        written=_plain(t_b.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                        **ref,
                    )
                )
        if compare_text and _norm_text(getattr(pos, "description", "")) != _norm_text(
            getattr(other, "description", "")
        ):
            items.append(
                FidelityItem(
                    severity="warning",
                    kind="roundtrip_mismatch",
                    field="description",
                    original=_norm_text(getattr(pos, "description", ""))[:300],
                    written=_norm_text(getattr(other, "description", ""))[:300],
                    **ref,
                )
            )
        if compare_units and _norm_unit(getattr(pos, "unit", "")) != _norm_unit(getattr(other, "unit", "")):
            items.append(
                FidelityItem(
                    severity="warning",
                    kind="roundtrip_mismatch",
                    field="unit",
                    original=str(getattr(pos, "unit", "") or ""),
                    written=str(getattr(other, "unit", "") or ""),
                    **ref,
                )
            )
    return items


# ── downloads ──────────────────────────────────────────────────────────────

#: Download columns: (catalogue key, item field).
DOWNLOAD_COLUMNS: tuple[tuple[str, str], ...] = (
    ("severity", "severity"),
    ("kind", "kind"),
    ("position", "position_ref"),
    ("field", "field"),
    ("original", "original"),
    ("written", "written"),
    ("count", "count"),
    ("detail", "detail"),
)


def _download_rows(items: Iterable[Mapping[str, Any]], label: Callable[[str, str], str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for item in items:
        row: list[Any] = []
        for _key, attr in DOWNLOAD_COLUMNS:
            value = item.get(attr)
            if attr == "severity":
                value = label("severity", str(value or ""))
            elif attr == "kind":
                value = label("kind", str(value or ""))
            row.append("" if value is None else value)
        rows.append(row)
    return rows


def render_csv(items: Iterable[Mapping[str, Any]], headers: list[str], label: Callable[[str, str], str]) -> bytes:
    """The report as a UTF-8 CSV (with BOM, so a spreadsheet opens it in the right code page)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headers)
    for row in _download_rows(items, label):
        writer.writerow([neutralise_formula(v) if isinstance(v, str) else v for v in row])
    return ("﻿" + out.getvalue()).encode("utf-8")


def render_xlsx(
    items: Iterable[Mapping[str, Any]],
    headers: list[str],
    label: Callable[[str, str], str],
    *,
    title: str,
) -> bytes:
    """The report as one worksheet with a frozen, filterable header row."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = (title or "Report")[:31]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in _download_rows(items, label):
        ws.append([neutralise_formula(v[: EXCEL_CELL_MAX_CHARS - 1]) if isinstance(v, str) else v for v in row])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    widths = (10, 24, 14, 16, 40, 40, 8, 60)
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = [
    "DOWNLOAD_COLUMNS",
    "EXPORT_FORMATS",
    "KINDS",
    "MAX_STORED_ITEMS",
    "ROUNDTRIP_READER",
    "SEVERITIES",
    "FidelityItem",
    "FidelityReport",
    "TreeRow",
    "analyze_bc3_export",
    "analyze_gaeb_export",
    "analyze_import",
    "analyze_sheet_export",
    "flattened_levels",
    "iter_export_positions",
    "render_csv",
    "render_xlsx",
    "roundtrip_diff",
    "tree_rows",
]
