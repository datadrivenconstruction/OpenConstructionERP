# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Seed an already-converted demo DXF drawing for the DWG Takeoff module.

Why this exists
---------------
Demo DWG drawings used to be seeded as metadata-only rows (``status="uploaded"``,
``file_path=""``, no parsed entities). On a fresh install the local DDC cad2data
DWG converter is absent, so nothing transitioned those rows and the
``/dwg-takeoff`` viewer span forever on a "Converting your drawing..." spinner.

DWG is an open format we open directly, and DXF parses out of the box via
``ezdxf`` (a base dependency). So instead of a stuck reference row, the demo now
seeds a small but real DXF floor-plan, parses it through the same code path an
upload uses, and persists a ``ready`` version with entities on disk. A first-time
user opens ``/dwg-takeoff`` and sees a working drawing immediately - no converter,
no spinner.

The helper is fully idempotent: it keys the drawing on a deterministic id and
skips when a ready version already exists, so re-running a seeder (every boot)
is a cheap no-op.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dwg_takeoff.models import DwgDrawing, DwgDrawingVersion

logger = logging.getLogger(__name__)


def _build_demo_dxf(path: str) -> bool:
    """Write the demo architectural drawing set DXF to ``path``.

    The set (site, plans, roof, section, elevations, schedule; eight A2 sheets in
    model space) is authored by :mod:`app.scripts.demo_drawing_set`, units mm.

    Returns ``True`` on success, ``False`` when ezdxf is unavailable (the
    caller then falls back to a metadata-only reference row).
    """
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        logger.info("seed_dwg_drawing: ezdxf not installed - skipping ready DXF seed")
        return False

    try:
        from app.scripts.demo_drawing_set import build_drawing_set

        os.makedirs(os.path.dirname(path), exist_ok=True)
        build_drawing_set(path)
        return True
    except Exception:  # noqa: BLE001 - seed is best-effort, never fatal
        logger.warning("seed_dwg_drawing: failed to build demo DXF", exc_info=True)
        return False


async def seed_ready_dwg_drawing(
    session: AsyncSession,
    *,
    drawing_id: uuid.UUID,
    project_id: uuid.UUID,
    owner: str,
    name: str,
    discipline: str | None = None,
    source: str = "demo_asset_seed",
) -> bool:
    """Seed (idempotently) a ready, viewer-renderable demo DXF drawing.

    Creates a ``DwgDrawing`` (format ``dxf``, status ``ready``) plus a parsed
    ``DwgDrawingVersion`` whose entities are written to the same on-disk store
    a real upload uses, so ``GET /drawings/{id}/entities`` serves them and the
    viewer renders immediately on a fresh install.

    The ``element_count`` written to the drawing's metadata is the count the
    parse returned for the DXF authored here, and nothing else. Callers used to
    pass a count in, and both passed the one belonging to the converted CAD
    model of the same format in the demo spec - a different, far larger file -
    so the drawing advertised thousands of elements and served eight. A count
    is only ever true of one file, so this one is taken from the file it
    describes and the parameter is gone.

    Idempotent: returns early if the drawing already has a ready version, and
    regenerates the DXF + entities only when missing (e.g. a half-seeded row
    from a previous failure, or a data-dir that was wiped).

    Returns ``True`` when a ready (or at least listed) drawing exists
    afterwards, ``False`` only when even the metadata row could not be created.
    Falls back to a metadata-only ``uploaded`` row when ezdxf or the parse is
    unavailable - the backend then reports ``needs_conversion`` so the UI shows
    the friendly convert state rather than a spinner.
    """
    # Lazy import: keep the dwg_takeoff parser dependency off the seeder's
    # import path so a seeder load never fails when the module is absent.
    from app.modules.dwg_takeoff.service import (
        _get_entities_dir,
        _get_upload_dir,
        _process_dxf_sync,
    )

    existing = await session.get(DwgDrawing, drawing_id)
    entities_key = f"{drawing_id}/entities.json"
    entities_path = os.path.join(_get_entities_dir(), entities_key)

    # Fast idempotency: a ready row whose entities are on disk is already good.
    from app.scripts.demo_drawing_set import SET_VERSION

    upload_dir = _get_upload_dir()
    file_path = os.path.join(upload_dir, f"{drawing_id}.dxf")
    stale = existing is not None and (existing.metadata_ or {}).get("seed_set_version") != SET_VERSION
    if existing is not None and existing.status == "ready" and os.path.exists(entities_path) and not stale:
        return True
    if stale and (existing.metadata_ or {}).get("seed_ready_dxf") and os.path.exists(file_path):
        # An older demo drawing: rebuild it so upgrades get the current set.
        os.remove(file_path)

    built = True
    if not os.path.exists(file_path):
        built = _build_demo_dxf(file_path)

    parsed: dict[str, Any] | None = None
    if built and os.path.exists(file_path):
        try:
            thumbnail_key = f"{drawing_id}/thumbnail.svg"
            parsed = await asyncio.to_thread(_process_dxf_sync, file_path, entities_key, thumbnail_key)
        except Exception:  # noqa: BLE001 - fall back to a reference row
            logger.warning(
                "seed_dwg_drawing: parse failed for %s - seeding reference row",
                drawing_id,
                exc_info=True,
            )
            parsed = None

    if existing is None:
        if parsed is not None and int(parsed.get("entity_count") or 0) > 0:
            size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            drawing = DwgDrawing(
                id=drawing_id,
                project_id=project_id,
                name=name,
                filename=f"{name}.dxf",
                file_format="dxf",
                file_path=file_path,
                size_bytes=size_bytes,
                status="ready",
                discipline=discipline,
                thumbnail_key=f"{drawing_id}/thumbnail.svg",
                created_by=owner,
                metadata_={
                    "source": source,
                    "seed_ready_dxf": True,
                    "seed_set_version": SET_VERSION,
                    "element_count": int(parsed.get("entity_count") or 0),
                },
            )
            session.add(drawing)
            await session.flush()
            await _create_ready_version(session, drawing_id, parsed, entities_key)
            return True

        # ezdxf/parse unavailable: metadata-only reference row. The backend
        # resolves this to ``needs_conversion`` on read so the UI shows the
        # convert CTA, not a perpetual spinner. It carries no ``element_count``
        # at all: nothing here has read a drawing, so any number would be a
        # claim about a file this install does not hold.
        drawing = DwgDrawing(
            id=drawing_id,
            project_id=project_id,
            name=name,
            filename=f"{name}.dxf",
            file_format="dxf",
            file_path="",
            size_bytes=0,
            status="uploaded",
            discipline=discipline,
            created_by=owner,
            metadata_={
                "source": source,
                "seed_reference_only": True,
            },
        )
        session.add(drawing)
        await session.flush()
        return True

    # Existing row missing its parsed entities (half-seeded / wiped data dir).
    # Promote it to ready in place when we just rebuilt + parsed the DXF.
    if parsed is not None and int(parsed.get("entity_count") or 0) > 0:
        existing.file_format = "dxf"
        existing.file_path = file_path
        existing.status = "ready"
        existing.thumbnail_key = f"{drawing_id}/thumbnail.svg"
        if os.path.exists(file_path):
            existing.size_bytes = os.path.getsize(file_path)
        meta = dict(existing.metadata_ or {})
        meta["seed_ready_dxf"] = True
        meta["seed_set_version"] = SET_VERSION
        # The row is being promoted off a parse we just ran, so its count is
        # restated from that parse. A row half-seeded by an older build can
        # carry a count that was never about this DXF; leaving it would keep
        # that number alive under a drawing that now reports its own.
        meta["element_count"] = int(parsed.get("entity_count") or 0)
        existing.metadata_ = meta
        session.add(existing)
        await session.flush()
        # Only create a version if none parsed yet.
        from app.modules.dwg_takeoff.repository import DwgDrawingVersionRepository

        version_repo = DwgDrawingVersionRepository(session)
        latest = await version_repo.get_latest_for_drawing(drawing_id)
        if stale or latest is None or (latest.entity_count or 0) == 0:
            await _create_ready_version(session, drawing_id, parsed, entities_key)
        return True

    return True


async def _create_ready_version(
    session: AsyncSession,
    drawing_id: uuid.UUID,
    parsed: dict[str, Any],
    entities_key: str,
) -> None:
    """Persist a ready DwgDrawingVersion from a parse result."""
    from app.modules.dwg_takeoff.repository import DwgDrawingVersionRepository

    version_repo = DwgDrawingVersionRepository(session)
    version_number = await version_repo.get_next_version_number(drawing_id)
    version = DwgDrawingVersion(
        drawing_id=drawing_id,
        version_number=version_number,
        layers=parsed["layers"],
        entities_key=entities_key,
        entity_count=int(parsed.get("entity_count") or 0),
        extents=parsed["extents"],
        units=parsed.get("units", "mm"),
        status="ready",
        metadata_={},
    )
    session.add(version)
    await session.flush()
    logger.info(
        "seed_dwg_drawing: seeded ready DXF drawing %s (%d entities)",
        drawing_id,
        version.entity_count,
    )
    # Ensure entities JSON is on disk (the parse wrote it, but double-check the
    # store survived a custom data dir).
    entities_path = os.path.join(_entities_dir(), entities_key)
    if not os.path.exists(entities_path):
        os.makedirs(os.path.dirname(entities_path), exist_ok=True)
        with open(entities_path, "w", encoding="utf-8") as f:
            json.dump(parsed["entities"], f)


def _entities_dir() -> str:
    from app.modules.dwg_takeoff.service import _get_entities_dir

    return _get_entities_dir()
