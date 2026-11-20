"""Converter-imported BIM hub models as revisions (R16, contract §9a).

A wrapped model gets a revision row with a ``ddc-import/1`` record instead of a package; the BIM hub rows stay as
they are. Element keys are the stored ``stable_id`` (``contract_models.import_key`` for contract documents).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select

from .contract_models import import_key
from .models import DesignRevision
from .revisions import DESIGN_STATUS_KEY, chain_tip, next_number, storage_prefix

IMPORT_SCHEMA = "ddc-import/1"
WRAP_STATUSES = ("ready", "degraded")
# Model metadata keys a wrap sets; their prior values go to the record's ``restore`` so unwrapping puts them back.
WRAP_KEYS = (DESIGN_STATUS_KEY, "design_revision_id", "design_revision_number", "design_imported")
_NS = uuid.UUID("1f6c2b9e-5d3a-4e8f-9b07-6a4d2c1e8f30")


class NotWrappable(Exception):
    """The model cannot be wrapped; ``str(exc)`` says why."""


def revision_id_for(model_id: uuid.UUID) -> uuid.UUID:
    # One id per model: a second wrap of the same model collides on the primary key.
    return uuid.uuid5(_NS, f"ddc-import:{model_id}")


def is_import_record(manifest: dict | None) -> bool:
    return (manifest or {}).get("schema") == IMPORT_SCHEMA


def _is_design_model(model) -> bool:
    return (model.model_format or "").lower() == "ddc" or "design_revision_id" in (model.metadata_ or {})


async def candidates(session, project_id: uuid.UUID) -> list:
    """Converter models of the project that are ready and not wrapped yet, oldest first."""
    from app.modules.bim_hub.models import BIMModel

    wrapped = select(DesignRevision.bim_model_id).where(
        DesignRevision.project_id == project_id, DesignRevision.bim_model_id.is_not(None)
    )
    rows = (
        (
            await session.execute(
                select(BIMModel)
                .where(
                    BIMModel.project_id == project_id,
                    BIMModel.status.in_(WRAP_STATUSES),
                    BIMModel.element_count > 0,
                    BIMModel.id.not_in(wrapped),
                )
                .order_by(BIMModel.created_at, BIMModel.id)
            )
        )
        .scalars()
        .all()
    )
    return [m for m in rows if not _is_design_model(m)]


async def geometry_digest(project_id: uuid.UUID, model_id: uuid.UUID) -> tuple[str, int] | None:
    """SHA-256 and size of the geometry file the BIM hub serves for the model; None without one."""
    from app.modules.bim_hub import file_storage

    found = await file_storage.find_geometry_key(project_id, model_id)
    if found is None:
        return None
    digest, size = hashlib.sha256(), 0
    async for chunk in file_storage.open_geometry_stream(found[0]):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


async def element_stats(session, model_id: uuid.UUID) -> dict[str, int]:
    from app.modules.bim_hub.models import BIMElement

    verbatim = mapped = 0
    storeys: set[str] = set()
    result = await session.execute(
        select(BIMElement.stable_id, BIMElement.storey).where(BIMElement.model_id == model_id)
    )
    for sid, storey in result:
        if import_key(sid) == sid:
            verbatim += 1
        else:
            mapped += 1
        if storey:
            storeys.add(storey)
    return {"elements": verbatim + mapped, "storeys": len(storeys), "verbatim": verbatim, "mapped": mapped}


async def wrap(session, model, *, user_id: uuid.UUID, depth_level: str | None = None) -> DesignRevision:
    """Add ``model`` to its project's chain as a shared revision. Flushes; the caller commits (IntegrityError = race)."""
    if _is_design_model(model):
        raise NotWrappable("model is a design revision already")
    if model.status not in WRAP_STATUSES:
        raise NotWrappable(f"model is {model.status}, not ready")
    project_id = model.project_id
    if (
        await session.execute(select(DesignRevision.id).where(DesignRevision.bim_model_id == model.id))
    ).first() is not None:
        raise NotWrappable("model is wrapped already")
    stats = await element_stats(session, model.id)
    if stats["elements"] == 0:
        raise NotWrappable("model has no elements")
    geometry = await geometry_digest(project_id, model.id)
    if geometry is None:
        raise NotWrappable("model has no geometry file")
    revision_id = revision_id_for(model.id)
    parent = await chain_tip(session, project_id)
    number = await next_number(session, project_id)
    before = model.metadata_ or {}
    record: dict[str, Any] = {
        "schema": IMPORT_SCHEMA,
        "revision_id": str(revision_id),
        "bim_model_id": str(model.id),
        "source": {
            "kind": "imported",
            "imported_from": (model.name or str(model.id))[:255],
            "model_format": (model.model_format or "")[:20],
        },
        "counts": {"elements": stats["elements"], "storeys": stats["storeys"]},
        "keys": {"verbatim": stats["verbatim"], "mapped": stats["mapped"]},
        "restore": {
            "parent_model_id": str(model.parent_model_id) if model.parent_model_id else None,
            "metadata": {k: before[k] for k in WRAP_KEYS if k in before},
        },
        "files": [],
    }
    rev = DesignRevision(
        id=revision_id,
        project_id=project_id,
        number=number,
        parent_id=parent.id if parent else None,
        status="shared",
        source_kind="imported",
        depth_level=depth_level or "",
        message=model.name or "",
        manifest=record,
        storage_prefix=storage_prefix(project_id, revision_id),
        package_sha256=geometry[0],
        package_bytes=geometry[1],
        bim_model_id=model.id,
        author_user_id=user_id,
    )
    session.add(rev)
    model.metadata_ = {
        **before,
        DESIGN_STATUS_KEY: "shared",
        "design_revision_id": str(revision_id),
        "design_revision_number": number,
        "design_imported": True,
    }
    await session.flush()
    return rev


async def unwrap(session, rev: DesignRevision) -> None:
    """Remove a wrapper row and put the model's fields back as ``restore`` recorded them. Flushes."""
    from app.modules.bim_hub.models import BIMModel

    record = rev.manifest or {}
    if not is_import_record(record):
        raise NotWrappable("revision is not a wrapped import")
    restore = record.get("restore") or {}
    model = await session.get(BIMModel, rev.bim_model_id) if rev.bim_model_id else None
    if model is not None:
        meta = {k: v for k, v in (model.metadata_ or {}).items() if k not in WRAP_KEYS}
        meta.update(restore.get("metadata") or {})
        model.metadata_ = meta
        parent = restore.get("parent_model_id")
        model.parent_model_id = uuid.UUID(parent) if parent else None
    await session.delete(rev)
    await session.flush()
