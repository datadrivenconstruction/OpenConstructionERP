"""Store a verified revision and register it as a BIM hub model version (contract §9).

The GLB and Parquet in the package are used as they are: no converter runs. Element
identity is ``element_key`` everywhere (node name = ``mesh_ref`` = ``stable_id`` = Parquet ``id``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from .intake import VerifiedPackage
from .models import DesignRevision

logger = logging.getLogger(__name__)

UPLOADING = "uploading"
VISIBLE = ("shared", "published", "rejected", "archived")

# ERP canonical quantity keys (bim_hub) plus the gross values of contract §4.
QUANTITY_KEYS = ("length_m", "area_m2", "volume_m3", "weight_kg", "count", "area_gross_m2", "volume_gross_m3")
_IDENTITY = ("id", "stable_id", "element_key", "element_type", "name", "storey", "discipline", "geometry_hash")
_BBOX = ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z")


def storage_prefix(project_id: uuid.UUID, revision_id: uuid.UUID) -> str:
    return f"design/{project_id}/{revision_id}"


def file_key(prefix: str, path: str) -> str:
    return f"{prefix}/{path}"


def _props(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("props")
    return json.loads(raw) if raw else {}


def element_properties(row: dict[str, Any]) -> dict[str, Any]:
    """Everything that is neither identity, a quantity nor bbox; contract fields win over props."""
    out: dict[str, Any] = {"element_key": row["element_key"]}
    for col in ("ifc_class", "type_key", "space", "material", "phase"):
        if row.get(col) is not None:
            out[col] = row[col]
    for k, v in _props(row).items():
        out.setdefault(str(k), v)
    return out


def element_quantities(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row[k] for k in QUANTITY_KEYS if row.get(k) is not None}


def dataframe_row(row: dict[str, Any]) -> dict[str, Any]:
    """The ERP's string copy: contract columns minus ``props``, with props flattened beside them."""
    out = {k: v for k, v in row.items() if k != "props"}
    for k, v in _props(row).items():
        out.setdefault(str(k), v)
    return out


async def latest_published(session, project_id: uuid.UUID) -> DesignRevision | None:
    return (
        await session.execute(
            select(DesignRevision)
            .where(DesignRevision.project_id == project_id, DesignRevision.status == "published")
            .order_by(DesignRevision.number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def chain_tip(session, project_id: uuid.UUID) -> DesignRevision | None:
    """Newest revision still in play (waiting or published): the parent of the next upload."""
    return (
        await session.execute(
            select(DesignRevision)
            .where(DesignRevision.project_id == project_id, DesignRevision.status.in_(("shared", "published")))
            .order_by(DesignRevision.number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def design_tip(session, project_id: uuid.UUID) -> DesignRevision | None:
    """The parent of the next design revision (contract §8): the newest revision in play that is not a
    ``ddc-import/1`` record (no element table to diff against) and can still be accepted, i.e. its waiting
    parents lead to the published one, or to nothing while the published one is an import or missing.
    """
    rows = (
        (
            await session.execute(
                select(DesignRevision)
                .where(DesignRevision.project_id == project_id, DesignRevision.status.in_(("shared", "published")))
                .order_by(DesignRevision.number.desc())
            )
        )
        .scalars()
        .all()
    )
    by_id = {r.id: r for r in rows}
    published = next((r for r in rows if r.status == "published"), None)

    def imported(r) -> bool:
        return (r.manifest or {}).get("schema") == "ddc-import/1"

    def viable(r) -> bool:
        while r.status == "shared":
            if r.parent_id is None:
                return published is None or imported(published)
            if r.parent_id not in by_id:
                return False  # built on a rejected or archived revision
            r = by_id[r.parent_id]
        return True

    return next((r for r in rows if not imported(r) and viable(r)), None)


async def next_number(session, project_id: uuid.UUID) -> int:
    current = (
        await session.execute(select(func.max(DesignRevision.number)).where(DesignRevision.project_id == project_id))
    ).scalar_one()
    return int(current or 0) + 1


async def store_files(pkg: VerifiedPackage, prefix: str, work_dir: Path) -> Path:
    """Put every package file under ``prefix``; returns a private copy of the GLB for the BIM hub."""
    from app.core.storage import get_storage_backend

    backend = get_storage_backend()
    glb_copy = work_dir / "_bim" / "geometry.glb"
    glb_copy.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.copyfile, pkg.files[pkg.roles["geometry"]], glb_copy)
    await backend.put(file_key(prefix, "manifest.json"), json.dumps(pkg.manifest_json, indent=1).encode("utf-8"))
    keep = pkg.files[pkg.roles["elements"]]  # read again for the BIM rows; put_stream may consume its source
    for path, local in pkg.files.items():
        if local == keep:
            local = work_dir / "_put" / "elements.parquet"
            local.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copyfile, keep, local)
        await backend.put_stream(file_key(prefix, path), local)
    return glb_copy


def _rows_for_bim(pkg: VerifiedPackage) -> tuple[list[dict[str, Any]], list]:
    """One batched pass over the Parquet: the ERP's dataframe rows and its element records."""
    from app.modules.bim_hub.schemas import BIMElementCreate

    frame: list[dict[str, Any]] = []
    elements: list = []
    for r in pkg.rows():
        frame.append(dataframe_row(r))
        elements.append(
            BIMElementCreate(
                stable_id=r["element_key"],
                mesh_ref=r["element_key"],
                element_type=r["element_type"],
                name=r["name"],
                storey=r["storey"],
                discipline=r["discipline"],
                geometry_hash=r["geometry_hash"],
                quantities=element_quantities(r),
                properties=element_properties(r),
                bounding_box={k: r[f"bbox_{k}"] for k in _BBOX},
            )
        )
    return frame, elements


async def register_bim_model(
    session,
    *,
    pkg: VerifiedPackage,
    project_id: uuid.UUID,
    model_name: str,
    number: int,
    parent: DesignRevision | None,
    user_id: uuid.UUID,
    glb_path: Path,
    on_created,
) -> uuid.UUID:
    """``on_created(model_id)`` is called as soon as the model exists, so the caller can clean up."""
    from app.modules.bim_hub import dataframe_store
    from app.modules.bim_hub import file_storage as bim_file_storage
    from app.modules.bim_hub.schemas import BIMModelCreate
    from app.modules.bim_hub.service import BIMHubService

    service = BIMHubService(session)
    manifest = pkg.manifest
    model = await service.create_model(
        BIMModelCreate(
            project_id=project_id,
            name=model_name,
            model_format="ddc",
            version=str(number),
            status="processing",
            # Unchained until accepted: the BOQ treats any child model as the newest version.
            parent_model_id=None,
            metadata={
                DESIGN_STATUS_KEY: "shared",
                "design_revision_id": manifest.revision_id,
                "design_revision_number": number,
                "depth_level": manifest.depth_level,
                "base_point": manifest.base_point.model_dump(exclude_none=True),
                "design_parent_model_id": str(parent.bim_model_id) if parent and parent.bim_model_id else None,
            },
        ),
        user_id=str(user_id),
    )
    model_id = model.id
    on_created(model_id)
    await bim_file_storage.save_geometry_from_path(project_id, model_id, ".glb", glb_path)
    frame, elements = await asyncio.to_thread(_rows_for_bim, pkg)
    await asyncio.to_thread(dataframe_store.write_dataframe, str(project_id), str(model_id), frame)
    del frame
    await service.bulk_import_elements(model_id, elements)
    # Geometry, elements and table are all in place; the viewer renders only "ready" or "degraded".
    from app.modules.bim_hub.models import BIMModel

    stored = await session.get(BIMModel, model_id)
    if stored is not None:
        stored.status = "ready"
    return model_id


# The BIM hub status vocabulary has no hidden or archived state; the revision's
# state is mirrored into the model metadata so lists can tell pending and rejected apart.
DESIGN_STATUS_KEY = "design_status"


async def mark_model(session, model_id: uuid.UUID | None, design_status: str) -> None:
    from app.modules.bim_hub.models import BIMModel

    if model_id is None:
        return
    model = await session.get(BIMModel, model_id)
    if model is not None:
        model.metadata_ = {**(model.metadata_ or {}), DESIGN_STATUS_KEY: design_status}


async def ensure_model_artifacts(project_id: str, model_id: str) -> None:
    """Tiles for the viewer, after the request committed (GLB and Parquet already exist)."""
    from app.database import async_session_factory
    from app.modules.bim_hub.service import BIMHubService

    try:
        async with async_session_factory() as session:
            await BIMHubService(session).ensure_artifacts(project_id, model_id)
            await session.commit()
    except Exception:  # noqa: BLE001 - artifacts are best-effort, as in the BIM hub upload
        logger.exception("design: artifact bake failed for model %s", model_id)


async def discard_files(prefix: str) -> None:
    """Undo the storage side of a failed intake (only for a prefix this intake claimed)."""
    from app.core.storage import get_storage_backend

    try:
        await get_storage_backend().delete_prefix(prefix)
    except Exception:  # noqa: BLE001 - cleanup must not hide the original error
        logger.exception("design: cleanup of %s failed", prefix)


async def discard_model_files(project_id: uuid.UUID, model_id: uuid.UUID) -> None:
    """Blobs and the dataframe sidecar of a BIM model whose rows were rolled back."""
    from app.modules.bim_hub import dataframe_store
    from app.modules.bim_hub import file_storage as bim_file_storage

    await bim_file_storage.delete_model_blobs(project_id, model_id)
    # write_dataframe's root (the module has no public delete); our own fresh output only.
    sidecar = dataframe_store._data_root() / str(project_id) / str(model_id)
    await asyncio.to_thread(shutil.rmtree, sidecar, True)


async def sweep_stale_uploads(session, project_id: uuid.UUID, older_than_s: int) -> None:
    """Intakes that died mid-way leave an ``uploading`` row and maybe files; drop them."""
    from sqlalchemy import delete

    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_s)
    stale = (
        await session.execute(
            select(DesignRevision.id, DesignRevision.storage_prefix).where(
                DesignRevision.project_id == project_id,
                DesignRevision.status == UPLOADING,
                DesignRevision.created_at < cutoff,
            )
        )
    ).all()
    for rev_id, prefix in stale:
        gone = await session.execute(
            delete(DesignRevision).where(DesignRevision.id == rev_id, DesignRevision.status == UPLOADING)
        )
        await session.commit()
        if gone.rowcount == 1:
            await discard_files(prefix)
