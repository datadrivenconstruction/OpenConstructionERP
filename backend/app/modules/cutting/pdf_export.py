# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed cutting list and its workbook, built on the shared register layout.

One row per stock piece: where it comes from, its size, the cuts taken from it
grouped by mark, the reusable offcut and the scrap. The builder is pure; the
layout and the PDF / XLSX rendering are :mod:`app.core.register_export`'s.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from app.core.register_export import ProjectHeader, RegisterColumn, RegisterDocument
from app.modules.cutting.pdf_translations import CATALOGUE, tr


def cuts_text(cuts: list[dict[str, Any]], *, sheet: bool) -> str:
    """Cuts grouped by mark and size, largest first: ``A 4000 x2, B 3000``."""
    groups: Counter[tuple[str, str, Decimal]] = Counter()
    for cut in cuts:
        length = Decimal(str(cut["length_mm"]))
        size = f"{cut['length_mm']} x {cut['width_mm']}" if sheet else str(cut["length_mm"])
        groups[(str(cut["ref"]), size, length)] += 1
    ordered = sorted(groups.items(), key=lambda kv: (-kv[0][2], kv[0][0]))
    return ", ".join(f"{ref} {size}" + (f" x{n}" if n > 1 else "") for (ref, size, _), n in ordered)


def _entry_row(entry: dict[str, Any], *, sheet: bool, locale: str, currency: str) -> list[Any]:
    if sheet:
        size = f"{entry['length_mm']} x {entry['width_mm']}"
        cuts = entry.get("placements", [])
        offcut = ", ".join(f"{o['length_mm']} x {o['width_mm']}" for o in entry.get("offcuts", []))
        scrap = "{} m2".format(entry.get("scrap_m2", "0"))
    else:
        size = str(entry["length_mm"])
        cuts = entry.get("cuts", [])
        offcut_mm = Decimal(str(entry.get("offcut_mm", "0")))
        offcut = "" if offcut_mm == 0 else str(entry["offcut_mm"])
        scrap = "{} mm".format(entry.get("scrap_mm", "0"))
    source = tr(locale, "source_inventory") if entry.get("is_offcut") else tr(locale, "source_purchase")
    return [
        entry["index"],
        entry.get("stock_label") or entry["stock_ref"],
        source,
        size,
        cuts_text(cuts, sheet=sheet),
        offcut,
        scrap,
        Decimal(str(entry.get("cost") or "0")),
        currency,
    ]


def cutting_list(job: Any, plan: Any, *, project: ProjectHeader, locale: str, generated: str = "") -> RegisterDocument:
    """Describe the printable cutting list of one plan."""
    sheet = plan.kind == "sheet"
    layout = plan.layout or {}
    entries = layout.get("sheets" if sheet else "bars", [])
    currency = plan.currency or project.currency
    columns = [
        RegisterColumn(tr(locale, "col_no"), kind="count", weight=0.4, xlsx_width=6),
        RegisterColumn(tr(locale, "col_stock"), weight=1.0, xlsx_width=18, nobreak=True),
        RegisterColumn(tr(locale, "col_source"), weight=0.9, xlsx_width=18),
        RegisterColumn(tr(locale, "col_size"), weight=0.9, xlsx_width=14, nobreak=True),
        RegisterColumn(tr(locale, "col_cuts"), weight=3.0, xlsx_width=60, wrap=True),
        RegisterColumn(tr(locale, "col_offcut"), weight=0.9, xlsx_width=16),
        RegisterColumn(tr(locale, "col_scrap"), weight=0.7, xlsx_width=12, nobreak=True),
        RegisterColumn(tr(locale, "col_cost"), kind="money", weight=0.8, xlsx_width=14, total=True),
        RegisterColumn(tr(locale, "currency"), kind="currency", xlsx_width=8, pdf=False),
    ]
    rows = [_entry_row(entry, sheet=sheet, locale=locale, currency=currency) for entry in entries]
    unit = "m2" if sheet else "m"
    details = [
        *CATALOGUE.register_details(locale, project, count=len(rows), with_currency=True),
        (tr(locale, "job"), job.name),
        (tr(locale, "material"), job.material or "-"),
        (tr(locale, "kerf"), str(job.kerf_mm)),
        (tr(locale, "stock_count"), str(plan.stock_count)),
        (tr(locale, "yield"), f"{plan.yield_pct} %"),
        (tr(locale, "waste"), f"{plan.waste_pct} % ({plan.scrap_total} {unit})"),
        (tr(locale, "cost"), f"{plan.cost} {currency}".strip()),
    ]
    if plan.unplaced:
        details.append((tr(locale, "unplaced"), ", ".join(f"{u['ref']} x{u['quantity']}" for u in plan.unplaced)))
    furniture = CATALOGUE.furniture(locale, project)
    furniture["currency"] = currency
    return RegisterDocument(
        title=tr(locale, "register_title"),
        columns=columns,
        rows=rows,
        details=details,
        locale=locale,
        number_style=project.number_style,
        generated=generated,
        empty_text=tr(locale, "empty"),
        sheet_title=tr(locale, "register_title"),
        currency_column=8,
        **furniture,
    )


__all__ = ["cuts_text", "cutting_list"]
