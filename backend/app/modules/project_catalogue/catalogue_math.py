# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure rules of a project catalogue rate against the source it was copied from.

Three numbers decide everything: the project's own ``rate``, the
``source_rate`` the project last took or acknowledged, and the source's
``current_source_rate`` read now. Nothing here touches the database.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

SOURCE_TYPES = ("manual", "cost_item", "catalog_resource")
SYNC_ACTIONS = ("take_source", "keep_local")
ITEM_TYPES = ("work", "labor", "material", "equipment", "other")


class ItemStatus(StrEnum):
    """Where a project rate stands against its source."""

    IN_SYNC = "in_sync"
    OVERRIDDEN = "overridden"
    SOURCE_CHANGED = "source_changed"
    SOURCE_MISSING = "source_missing"
    MANUAL = "manual"


def _same(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a.compare(b) == 0


def item_status(
    *,
    source_type: str,
    rate: Decimal,
    source_rate: Decimal | None,
    current_source_rate: Decimal | None,
    source_found: bool,
) -> ItemStatus:
    """Classify one project rate.

    A moved source outranks a local override: the estimator has to decide
    about the new price before the override means anything again.
    """
    if source_type == "manual":
        return ItemStatus.MANUAL
    if not source_found:
        return ItemStatus.SOURCE_MISSING
    if not _same(source_rate, current_source_rate):
        return ItemStatus.SOURCE_CHANGED
    if not _same(rate, source_rate):
        return ItemStatus.OVERRIDDEN
    return ItemStatus.IN_SYNC


def resolve_sync(action: str, *, rate: Decimal, current_source_rate: Decimal) -> tuple[Decimal, Decimal]:
    """Return ``(rate, source_rate)`` after the estimator's choice on a moved source."""
    if action == "take_source":
        return current_source_rate, current_source_rate
    if action == "keep_local":
        return rate, current_source_rate
    raise ValueError(f"unknown sync action {action!r}")


def deviation_percent(rate: Decimal | None, base: Decimal | None) -> Decimal | None:
    """Signed distance of ``rate`` from ``base`` in percent, one decimal; ``None`` without a base."""
    if rate is None or base is None or base == 0:
        return None
    return ((rate - base) / base * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
