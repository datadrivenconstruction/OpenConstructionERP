# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Registry of record types an approval request may target.

An approval request stores its target as ``entity_type`` + ``entity_id``
strings. Without a registry nothing ties that pair to a real row, so a caller
could file a request on its own route against a record of a project it cannot
see and approve it, leaving "estimate X approved" in the trail.

Each entry maps an entity type to the model that owns it and, for child
records, the parent hop that carries ``project_id``. Types outside the
registry are rejected; adding one is a deliberate, reviewed change.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntityRef:
    """Where a record type lives and how to reach its project."""

    module: str
    model: str
    # For a child record: (parent model in the same module, FK column on the child).
    parent: tuple[str, str] | None = None


APPROVABLE_ENTITIES: dict[str, EntityRef] = {
    "boq": EntityRef("app.modules.boq.models", "BOQ"),
    "boq_position": EntityRef("app.modules.boq.models", "Position", parent=("BOQ", "boq_id")),
    "invoice": EntityRef("app.modules.finance.models", "Invoice"),
    "change_order": EntityRef("app.modules.changeorders.models", "ChangeOrder"),
    "purchase_order": EntityRef("app.modules.procurement.models", "PurchaseOrder"),
    "material_requisition": EntityRef("app.modules.procurement.models", "MaterialRequisition"),
    "contract": EntityRef("app.modules.contracts.models", "Contract"),
    "submittal": EntityRef("app.modules.submittals.models", "Submittal"),
    "rfi": EntityRef("app.modules.rfi.models", "RFI"),
    "ncr": EntityRef("app.modules.ncr.models", "NCR"),
    "document": EntityRef("app.modules.documents.models", "Document"),
    "task": EntityRef("app.modules.tasks.models", "Task"),
}


async def resolve_entity_project_id(session: AsyncSession, entity_type: str, entity_id: str) -> uuid.UUID | None:
    """Return the project that owns the record, or None when it cannot be found.

    None covers an unregistered type, a malformed id, a missing row and a
    module that is not installed; callers treat it as fail-closed.
    """
    ref = APPROVABLE_ENTITIES.get(entity_type)
    if ref is None:
        return None
    try:
        eid = uuid.UUID(str(entity_id))
    except (ValueError, TypeError):
        return None
    try:
        mod = importlib.import_module(ref.module)
    except ImportError:
        logger.debug("approval entity module not installed: %s", ref.module)
        return None
    model = getattr(mod, ref.model)
    if ref.parent is None:
        stmt = select(model.project_id).where(model.id == eid)
    else:
        parent_name, fk = ref.parent
        parent = getattr(mod, parent_name)
        stmt = select(parent.project_id).join(model, getattr(model, fk) == parent.id).where(model.id == eid)
    return (await session.execute(stmt)).scalar_one_or_none()
