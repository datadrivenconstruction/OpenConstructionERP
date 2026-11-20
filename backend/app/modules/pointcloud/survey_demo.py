# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Riverside Yard: an as-built scan of the pad, generated at seed time, compared against the design.

The cloud is a LAS 1.4 file written by :func:`build_pad_scan`, about 0.7 MB:

* ground points (class 2) on a 0.5 m grid over the 100 x 60 m pad at the design
  level 34.300 m, with a repeating -2..+2 mm pattern as instrument noise;
* one high spot: the 20 x 20 m block E 389060-389080, N 5819020-5819040 stands
  45 mm above the design (spoil not yet taken off), so the heatmap shows it red;
* an excavator parked at E 389020, N 5819010 (class 1, 2.5 m up), which the
  ground-only option leaves out of the statistics.

The seed stores the scan, runs the comparison against the "Pad" surface with
the demo tolerance profile (10 mm, labelled as demo values) and leaves the cut
and fill to the learner. The numbers it produces are pinned in
``demo/riverside/expected.json``.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

EXPECTED = Path(__file__).resolve().parent / "demo" / "riverside" / "expected.json"
DESIGN_SURFACE = "Pad"
SCAN_NAME = "riverside_pad_asbuilt.las"
DESIGN_Z = 34.3
PAD = (389000.0, 5819000.0, 389100.0, 5819060.0)
PATCH = (389060.0, 5819020.0, 389080.0, 5819040.0)
PATCH_DZ = 0.045
SPACING = 0.5
MACHINE = (389020.0, 5819010.0, 389024.0, 5819013.0)


def pad_points() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """x, y, z and LAS class of the demo scan."""
    i = np.arange(int(round((PAD[2] - PAD[0]) / SPACING)) + 1)
    j = np.arange(int(round((PAD[3] - PAD[1]) / SPACING)) + 1)
    ii, jj = np.meshgrid(i, j)
    x = PAD[0] + ii.ravel() * SPACING
    y = PAD[1] + jj.ravel() * SPACING
    noise = ((ii.ravel() * 7 + jj.ravel() * 13) % 5 - 2) * 0.001
    z = DESIGN_Z + noise
    patch = (x >= PATCH[0]) & (x <= PATCH[2]) & (y >= PATCH[1]) & (y <= PATCH[3])
    z = z + np.where(patch, PATCH_DZ, 0.0)
    cls = np.full(len(x), 2, dtype=np.uint8)
    mx, my = np.meshgrid(np.arange(MACHINE[0], MACHINE[2] + 1e-9, 0.25), np.arange(MACHINE[1], MACHINE[3] + 1e-9, 0.25))
    x = np.concatenate([x, mx.ravel()])
    y = np.concatenate([y, my.ravel()])
    z = np.concatenate([z, np.full(mx.size, DESIGN_Z + 2.5)])
    cls = np.concatenate([cls, np.full(mx.size, 1, dtype=np.uint8)])
    return x, y, z, cls


def build_pad_scan() -> bytes:
    """The demo cloud as LAS 1.4 bytes (millimetre scale)."""
    import laspy  # noqa: PLC0415

    x, y, z, cls = pad_points()
    header = laspy.LasHeader(point_format=1, version="1.4")
    header.offsets = [PAD[0], PAD[1], 0.0]
    header.scales = [0.001, 0.001, 0.001]
    las = laspy.LasData(header)
    las.x, las.y, las.z = x, y, z
    las.classification = cls
    las.intensity = np.where(cls == 2, 900, 2500).astype(np.uint16)
    buf = io.BytesIO()
    las.write(buf)
    return buf.getvalue()


def expected() -> dict[str, Any]:
    """The pinned demo numbers."""
    return json.loads(EXPECTED.read_text(encoding="utf-8"))


async def seed_riverside_scan(session: AsyncSession, project_id: uuid.UUID, owner_id: uuid.UUID) -> dict[str, Any]:
    """Store the pad scan and its comparison against the design; idempotent per project."""
    from app.modules.pointcloud.models import ScanDataset  # noqa: PLC0415
    from app.modules.pointcloud.scan_design_schemas import DeviationRequest  # noqa: PLC0415
    from app.modules.pointcloud.scan_design_service import ScanDesignService  # noqa: PLC0415
    from app.modules.pointcloud.service import PointCloudService  # noqa: PLC0415
    from app.modules.surfaces_volumes.service import VolumesService  # noqa: PLC0415

    surfaces = await VolumesService(session).list_surfaces(project_id)
    design = next((s for s in surfaces if s.name == DESIGN_SURFACE), None)
    if design is None:
        return {}
    taken = (
        (await session.execute(select(ScanDataset.id).where(ScanDataset.project_id == project_id).limit(1)))
        .scalars()
        .first()
    )
    if taken is not None:
        return {}
    pc = PointCloudService(session)
    scan_id = uuid.uuid5(uuid.NAMESPACE_URL, f"oe:riverside-scan:{project_id}")
    key = PointCloudService._upload_key(owner_id, project_id, scan_id, "las")  # noqa: SLF001 - same module
    content = await asyncio.to_thread(build_pad_scan)
    await pc.storage.put(key, content)
    session.add(
        ScanDataset(
            id=scan_id,
            project_id=project_id,
            tenant_id=owner_id,
            source_type="lidar",
            original_format="las",
            accuracy_tier="standard",
            registration_status="registered",
            upload_key=key,
            status="ready",
            retention_policy="keep_raw",
            created_by=owner_id,
            scan_metadata={"demo": "riverside_pad_asbuilt", "name": SCAN_NAME},
        )
    )
    await session.flush()
    fields = await pc._sniff_header_fields(key, "las", had_crs=True)  # noqa: SLF001 - same module
    if fields:
        meta = dict(fields.get("scan_metadata") or {})
        meta.update({"demo": "riverside_pad_asbuilt", "name": SCAN_NAME})
        fields["scan_metadata"] = meta
        await pc.scans.update_fields(scan_id, **fields)
    report = await ScanDesignService(session).compare(
        scan_id,
        DeviationRequest(surface_id=design.id, tolerance_key="demo", ground_only=True),
        {"sub": str(owner_id), "role": "admin"},
        str(owner_id),
        [],
    )
    return {"pointcloud_scans": 1, "pointcloud_bytes": len(content), "scan_within_pct": report.stats.within_pct}


__all__ = ["build_pad_scan", "expected", "pad_points", "seed_riverside_scan"]
