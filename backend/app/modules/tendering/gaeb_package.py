# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The GAEB call for bids (X83) of one tender package rather than of its whole bill.

The BOQ module's GAEB writer, :func:`app.modules.boq.router.build_gaeb_xml`,
takes a structured bill. A package is usually raised over part of a bill, so
the bill is narrowed here to the package's lines before it is written: each
section keeps only the lines in scope, a section left with none is dropped, and
markups go, because the call for bids carries no prices and the writer writes
no markups in DP 83 anyway. The writer itself is reused unchanged, so the
document validates against the same schema as every other GAEB export.

The scope is the one the Excel bill for bidders uses (``_positions_in_scope``),
so both files a bidder receives list the same positions.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

__all__ = ["package_bill", "package_line_ids"]


def package_line_ids(positions: Iterable[Any], metadata: dict | None) -> set[str]:
    """Ids of the priceable lines a package was raised over.

    Args:
        positions: Every exportable position of the bill, headers included,
            the list the Excel bill for bidders narrows.
        metadata: The package's metadata.

    Returns:
        The ids of the lines in scope, section headers left out. A package
        that declares no scope, or one that matches nothing in the bill,
        covers the whole bill, as everywhere ``_positions_in_scope`` is read.
    """
    from app.modules.tendering.service import _positions_in_scope
    from app.modules.tendering.workbooks import _is_section

    return {
        str(p.id) for p in _positions_in_scope(list(positions), metadata) if not _is_section(getattr(p, "unit", ""))
    }


def _kept(positions: Iterable[Any], line_ids: set[str]) -> list[Any]:
    return [p for p in positions if str(getattr(p, "id", "")) in line_ids]


def package_bill(boq_data: Any, line_ids: set[str]) -> SimpleNamespace:
    """Narrow a structured bill to a package's lines for the GAEB writer.

    Args:
        boq_data: The structured bill (``BOQWithSections`` or anything with
            the same ``name``, ``sections`` and ``positions`` attributes).
        line_ids: Ids of the package's priceable lines.

    Returns:
        A bill with the attributes the writer reads: ``name``, the sections
        that still hold a line (each with only its lines in scope), the
        ungrouped lines in scope, no markups, and ``direct_cost`` over the
        kept lines.
    """
    sections = []
    kept_lines: list[Any] = []
    for section in getattr(boq_data, "sections", None) or []:
        lines = _kept(getattr(section, "positions", None) or [], line_ids)
        if not lines:
            continue
        kept_lines.extend(lines)
        sections.append(
            SimpleNamespace(
                id=getattr(section, "id", None),
                ordinal=getattr(section, "ordinal", ""),
                description=getattr(section, "description", ""),
                positions=lines,
                subtotal=sum((Decimal(str(getattr(p, "total", 0) or 0)) for p in lines), Decimal("0")),
            )
        )
    ungrouped = _kept(getattr(boq_data, "positions", None) or [], line_ids)
    kept_lines.extend(ungrouped)
    direct_cost = sum((Decimal(str(getattr(p, "total", 0) or 0)) for p in kept_lines), Decimal("0"))
    return SimpleNamespace(
        name=getattr(boq_data, "name", ""),
        sections=sections,
        positions=ungrouped,
        markups=[],
        direct_cost=direct_cost,
        net_total=direct_cost,
    )
