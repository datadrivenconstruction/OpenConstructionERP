# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Read-only directory hooks for contract packages and plant items.

Modules that need "which contract packages does this project have" or "is this
plant item delivered" must not import the module that owns those rows. The
owning module registers a reader here; a consumer asks and gets ``None`` when
nobody registered one, so it can tell "no data" from "no packages".

``list_contract_packages(session, project_id) -> list[{id, code, title, status}] | None``
``plant_item_facts(session, project_id, plant_item_id) -> {delivered: bool | None,
delivery_limit_agreed: bool | None} | None``
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

PackageLister = Callable[[Any, uuid.UUID], Awaitable[list[dict[str, Any]]]]
PlantReader = Callable[[Any, uuid.UUID, str], Awaitable[dict[str, Any] | None]]

_PACKAGES: list[PackageLister] = []
_PLANT: list[PlantReader] = []


def register_package_lister(fn: PackageLister) -> None:
    _PACKAGES.clear()
    _PACKAGES.append(fn)


def register_plant_reader(fn: PlantReader) -> None:
    _PLANT.clear()
    _PLANT.append(fn)


def unregister_all() -> None:
    """Tests."""
    _PACKAGES.clear()
    _PLANT.clear()


def plant_reader_registered() -> bool:
    """Whether a plant register answers :func:`plant_item_facts` in this installation."""
    return bool(_PLANT)


async def list_contract_packages(session: Any, project_id: uuid.UUID) -> list[dict[str, Any]] | None:
    """The project's contract packages, or ``None`` when no package module registered a reader."""
    if not _PACKAGES:
        return None
    return list(await _PACKAGES[0](session, project_id))


async def plant_item_facts(session: Any, project_id: uuid.UUID, plant_item_id: str | None) -> dict[str, Any] | None:
    """Delivery facts of one plant item, or ``None`` when unknown (no id, no reader)."""
    if not plant_item_id or not _PLANT:
        return None
    return await _PLANT[0](session, project_id, plant_item_id)
