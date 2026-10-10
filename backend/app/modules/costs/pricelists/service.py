# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Detect a regional price list, preview it, and turn its rows into cost items.

One entry for every region: the user uploads what the region publishes (an
XML, a CSV or XLSX, or the ZIP they downloaded), the format is recognised from
the content, and the preview says what was found before anything is written:
how many priced voci, which chapters, sample rows, the edition, and the
licence and attribution the publisher states. Nothing is imported until the
user confirms, and the catalogue is named after the region and edition.

A ZIP that carries the same list twice (Lombardia's two layouts, Umbria's XLSX
and JSON) is read once, in the richest format, and the preview lists what was
left out and why.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import IO, Any

from app.modules.costs.pricelists import lombardia, six, tabular, toscana, veneto, xpwe
from app.modules.costs.pricelists.base import PriceListRow, PriceListSource, decimal_str
from app.modules.costs.pricelists.containers import MAX_UPLOAD_BYTES, ContainerRefused, Member, open_members

SOURCE_TAG = "prezzario_regionale"
CURRENCY = "EUR"
PREVIEW_SAMPLE_ROWS = 8
PREVIEW_CHAPTERS = 40
_MAX_CODE_LEN = 100

_SAFETY_RE = re.compile(r"sicurezza", re.IGNORECASE)


def _xml(reader: Callable[[IO[bytes], PriceListSource], Iterator[PriceListRow]]):  # type: ignore[no-untyped-def]
    def _read(member: Member, source: PriceListSource) -> Iterator[PriceListRow]:
        with member.open() as stream:
            yield from reader(stream, source)

    return _read


# XPWE is parsed from the member twice, as a stream each time (an index pass,
# then the rows), so it is never in memory whole. The cap is the upload limit:
# a member inflated out of a ZIP may not grow past it.
_MAX_XPWE_BYTES = MAX_UPLOAD_BYTES


def _read_xpwe(member: Member, source: PriceListSource) -> Iterator[PriceListRow]:
    if member.size > _MAX_XPWE_BYTES:
        raise ContainerRefused("file_too_large", limit_mb=_MAX_XPWE_BYTES // (1024 * 1024))
    yield from xpwe.read_member(member.open, source)


@dataclass(frozen=True)
class _Format:
    format_id: str
    priority: int
    sniff: Callable[[bytes, str], bool]
    read: Callable[[Member, PriceListSource], Iterator[PriceListRow]]
    extensions: tuple[str, ...]


_FORMATS: tuple[_Format, ...] = (
    # First: its sniff matches only the XPWE root element, so it can never
    # claim a regional XML.
    _Format(xpwe.FORMAT_ID, 0, xpwe.sniff, _read_xpwe, (".xpwe", ".pwe", ".xml")),
    _Format(toscana.FORMAT_ID, 1, toscana.sniff, _xml(toscana.read), (".xml",)),
    _Format(lombardia.FORMAT_ID, 2, lombardia.sniff, _xml(lombardia.read), (".xml",)),
    _Format(veneto.FORMAT_ID, 3, veneto.sniff, _xml(veneto.read), (".xml",)),
    _Format(six.FORMAT_ID, 4, six.sniff, _xml(six.read), (".xml",)),
    _Format("tabular_xlsx", 5, tabular.sniff, tabular.read, (".xlsx",)),
    _Format("tabular_csv", 6, tabular.sniff, tabular.read, (".csv", ".txt")),
    _Format("tabular_json", 7, tabular.sniff, tabular.read, (".json",)),
    _Format(lombardia.LEGACY_FORMAT_ID, 8, lombardia.sniff_legacy, _xml(lombardia.read_legacy), (".xml",)),
)


def _detect(member: Member) -> _Format | None:
    candidates = [f for f in _FORMATS if member.extension in f.extensions]
    if not candidates:
        return None
    head = member.head()
    for fmt in candidates:
        if fmt.sniff(head, member.name):
            return fmt
    return None


@dataclass
class UploadPlan:
    """What an upload holds and which of it will be read."""

    format: _Format
    members: list[Member]
    skipped: list[dict[str, str]]
    source: PriceListSource

    def rows(self) -> Iterator[PriceListRow]:
        for member in self.members:
            yield from self.format.read(member, self.source)


def plan_upload(stream: IO[bytes], filename: str) -> UploadPlan:
    """Open the upload, recognise its format and choose the members to read.

    Raises:
        ContainerRefused: When the upload cannot be opened or holds no price
            list in a recognised format (``no_price_list_found``, with the
            skipped members and their reasons).
    """
    members, skipped = open_members(stream, filename)
    detected: list[tuple[_Format, Member]] = []
    for member in members:
        if member.extension in {".csv", ".json", ".xlsx", ".txt"} and "analisi" in member.name.lower():
            # A table of price analyses, published beside the list itself.
            skipped.append({"name": member.name, "reason": "analysis_table"})
            continue
        fmt = _detect(member)
        if fmt is None:
            # A .pwe that is not XPWE inside is the estimating program's own
            # binary project file, which only that program can open.
            reason = "native_project_file" if member.extension == ".pwe" else "format_not_recognised"
            skipped.append({"name": member.name, "reason": reason})
            continue
        detected.append((fmt, member))
    if not detected and any(s["reason"] == "native_project_file" for s in skipped):
        raise ContainerRefused("xpwe_not_xml")
    if not detected:
        raise ContainerRefused("no_price_list_found", skipped=skipped)
    best = min(fmt.priority for fmt, _m in detected)
    chosen = [m for fmt, m in detected if fmt.priority == best]
    fmt = next(f for f, _m in detected if f.priority == best)
    for other_fmt, member in detected:
        if other_fmt.priority != best:
            skipped.append({"name": member.name, "reason": "same_list_other_format", "format": other_fmt.format_id})
    return UploadPlan(format=fmt, members=chosen, skipped=skipped, source=PriceListSource(format_id=fmt.format_id))


# ── Rows to cost items ───────────────────────────────────────────────────────


def skip_reason(row: PriceListRow) -> str | None:
    """Why a row is not imported, or ``None`` when it is."""
    if not row.code:
        return "no_code"
    if len(row.code) > _MAX_CODE_LEN:
        return "code_too_long"
    if row.rate is None:
        return "broken_rate" if "broken_number:rate" in row.flags else "no_rate"
    if row.rate < 0:
        return "negative_rate"
    if row.rate == 0:
        return "zero_rate"
    return None


def _is_safety(row: PriceListRow) -> bool:
    if row.safety:
        return True
    if any(_SAFETY_RE.search(title or "") for _code, title in row.chapters):
        return True
    return bool(_SAFETY_RE.search(str(row.extra.get("source_file") or "")))


def prezzario_metadata(row: PriceListRow, source: PriceListSource) -> dict[str, Any]:
    """The ``metadata["prezzario"]`` block a cost item carries, and its BOQ lines after it.

    Shares are stored as given (percent, or euro for amounts) and as strings, the
    way the module stores money. ``labor_cost`` and its siblings are deliberately
    not set at the top level: the add-to-BOQ flow builds resource lines from
    them when an item has no components, and a labour amount alone would then
    reprice the line to its labour cost.
    """
    block: dict[str, Any] = {
        "region": source.region_name,
        "region_code": source.region_code,
        "edition": source.edition,
        "area": source.area,
        "format": source.format_id,
        "licence": source.licence,
        "licence_stated_in": source.licence_stated_in,
        "attribution": source.attribution(),
        "source_unit": row.source_unit,
        "short_description": row.short_description[:300],
        "chapters": [{"code": c, "title": t} for c, t in row.chapters],
        "safety": _is_safety(row),
    }
    for key in (
        "labour_share_pct",
        "labour_amount",
        "safety_share_pct",
        "safety_amount",
        "overhead_pct",
        "profit_pct",
    ):
        value = decimal_str(getattr(row, key))
        if value is not None:
            block[key] = value
    for key in ("cam", "previous_code", "part", "source_file", "resource_type"):
        if row.extra.get(key) not in (None, ""):
            block[key] = row.extra[key]
    # The material and equipment shares an XPWE list states beside labour.
    for key in ("material_share_pct", "equipment_share_pct"):
        share = row.extra.get(key)
        if isinstance(share, Decimal):
            share = decimal_str(share)
        if share not in (None, ""):
            block[key] = str(share)
    if "analysis" in row.extra:
        block["analysis"] = row.extra["analysis"]
    flags = [f for f in row.flags if f != "broken_number:rate"]
    if flags:
        block["flags"] = flags
    return {key: value for key, value in block.items() if value is not None}


def cost_item_payload(row: PriceListRow, source: PriceListSource) -> dict[str, Any]:
    """The ``CostItemCreate`` fields for an importable row (catalog fields added by the caller)."""
    description = row.description or row.short_description
    tags = ["prezzario"]
    if source.region_code:
        tags.append(source.region_code.lower())
    if source.edition:
        tags.append(str(source.edition))
    return {
        "code": row.code,
        "description": description,
        "descriptions": {"it": description} if description else {},
        "unit": row.unit or "pcs",
        "rate": row.rate,
        "currency": CURRENCY,
        "source": SOURCE_TAG,
        "classification": {"voci": row.code},
        "components": row.components,
        "tags": tags,
        "metadata": {"prezzario": prezzario_metadata(row, source)},
    }


# ── Preview ──────────────────────────────────────────────────────────────────


@dataclass
class PreviewTally:
    """Everything the preview reports, gathered in one pass over the rows."""

    rows: int = 0
    importable: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    duplicates: int = 0
    duplicate_examples: list[str] = field(default_factory=list)
    broken_rows: int = 0
    broken_examples: list[dict[str, Any]] = field(default_factory=list)
    with_components: int = 0
    with_labour_share: int = 0
    safety_rows: int = 0
    chapters: Counter[tuple[str, str]] = field(default_factory=Counter)
    units: Counter[str] = field(default_factory=Counter)
    sample: list[dict[str, Any]] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)

    def add(self, row: PriceListRow) -> None:
        self.rows += 1
        broken = [f.partition(":")[2] for f in row.flags if f.startswith("broken_number:")]
        if broken:
            self.broken_rows += 1
            if len(self.broken_examples) < 10:
                self.broken_examples.append({"code": row.code, "fields": broken})
        reason = skip_reason(row)
        if reason:
            self.skipped[reason] += 1
            return
        if row.code in self.seen:
            self.duplicates += 1
            if len(self.duplicate_examples) < 10:
                self.duplicate_examples.append(row.code)
            return
        self.seen.add(row.code)
        self.importable += 1
        if row.components:
            self.with_components += 1
        if row.labour_share_pct is not None or row.labour_amount is not None:
            self.with_labour_share += 1
        if _is_safety(row):
            self.safety_rows += 1
        if row.chapters:
            self.chapters[row.chapters[0]] += 1
        self.units[row.unit] += 1
        if len(self.sample) < PREVIEW_SAMPLE_ROWS:
            self.sample.append(
                {
                    "code": row.code,
                    "description": (row.short_description or row.description)[:200],
                    "unit": row.unit,
                    "source_unit": row.source_unit,
                    "rate": decimal_str(row.rate),
                    "labour_share_pct": decimal_str(row.labour_share_pct),
                    "chapter": row.chapters[0][1] if row.chapters else "",
                }
            )


def source_payload(source: PriceListSource) -> dict[str, Any]:
    """The source half of a preview: whose list, which edition, under what licence."""
    source.resolve_licence()
    return {
        "format": source.format_id,
        "profile": source.profile or None,
        "title": source.title or None,
        "region_code": source.region_code,
        "region_name": source.region_name,
        "region_detected_from": source.detected_from,
        "edition": source.edition,
        "area": source.area,
        "publisher": source.publisher,
        "licence": source.licence,
        "licence_stated_in": source.licence_stated_in,
        "attribution": source.attribution(),
        "suggested_catalog_name": source.suggested_catalog_name(),
    }


def build_preview(plan: UploadPlan, on_row: Callable[[], None] | None = None) -> dict[str, Any]:
    """Read the whole list once and report it, without writing anything.

    Args:
        plan: The planned upload.
        on_row: Called once per row read, so a background job can report
            how far it got.
    """
    tally = PreviewTally()
    for row in plan.rows():
        tally.add(row)
        if on_row is not None:
            on_row()
    warnings: list[str] = []
    if not plan.source.region_code:
        warnings.append("region_not_detected")
    elif plan.source.detected_from in {"layout", "filename"}:
        warnings.append("region_inferred")
    if not plan.source.edition:
        warnings.append("edition_not_detected")
    if not plan.source.licence:
        plan.source.resolve_licence()
    if not plan.source.licence:
        warnings.append("licence_not_stated")
    if tally.broken_rows:
        warnings.append("broken_numbers")
    if tally.duplicates:
        warnings.append("duplicate_codes")
    if tally.importable == 0:
        warnings.append("nothing_to_import")
    return {
        "source": source_payload(plan.source),
        "files": [{"name": m.name, "size": m.size} for m in plan.members],
        "skipped_files": plan.skipped,
        "counts": {
            "rows": tally.rows,
            "importable": tally.importable,
            "duplicates": tally.duplicates,
            "broken_rows": tally.broken_rows,
            "with_analysis": tally.with_components,
            "with_labour_share": tally.with_labour_share,
            "safety_rows": tally.safety_rows,
            "skipped": dict(tally.skipped),
        },
        "chapters": [
            {"code": code, "title": title, "count": count}
            for (code, title), count in tally.chapters.most_common(PREVIEW_CHAPTERS)
        ],
        "chapter_count": len(tally.chapters),
        "units": dict(tally.units.most_common(12)),
        "sample_rows": tally.sample,
        "broken_examples": tally.broken_examples,
        "duplicate_examples": tally.duplicate_examples,
        "warnings": warnings,
        "currency": CURRENCY,
    }


def total_rate(rows: list[PriceListRow]) -> Decimal:
    """Sum of the rates of ``rows`` (tests and reports)."""
    return sum((r.rate or Decimal(0) for r in rows), Decimal(0))


__all__ = [
    "CURRENCY",
    "SOURCE_TAG",
    "ContainerRefused",
    "UploadPlan",
    "build_preview",
    "cost_item_payload",
    "plan_upload",
    "prezzario_metadata",
    "skip_reason",
    "source_payload",
]
