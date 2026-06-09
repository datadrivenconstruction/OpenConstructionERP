# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Attach real, baked CAD/BIM geometry and a downloadable PDF to demo projects.

The flagship installer (:mod:`app.scripts.seed_flagship`) is the only working
ORM byte-attachment path; it restores a single reference project from committed
assets. This module *generalizes* that logic so every marketplace demo project
(residential, commercial, hospital, …) can ship a real BIM model with real
converted geometry plus a real downloadable plan-set PDF, instead of empty
BIM / Documents screens.

No CAD conversion ever runs here. We reuse the already-baked, committed assets:

    app/scripts/flagship_assets/flagship.json        spec (built by _bake_flagship.py)
    app/scripts/flagship_assets/geometry_ifc.dae.gz  real DDC IFC geometry
    app/scripts/flagship_assets/geometry_rvt.dae.gz  real DDC Revit geometry
    app/scripts/flagship_assets/house_plans.pdf      reference plan set

A *bundle* (:data:`BUNDLES`) picks which flagship model to clone into the demo
(by format), which element groups to link, and the PDF to attach. The public
entry point :func:`attach_demo_assets` is fully idempotent (deterministic
``uuid5`` ids per project) and dialect-agnostic (pure ORM), and every step is
wrapped so a missing asset never aborts a demo install.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent / "flagship_assets"
SPEC_PATH = ASSETS / "flagship.json"


def _samples_base() -> Path:
    """Folder holding the optional native CAD/BIM sample sources.

    Resolved from ``OE_DEMO_CAD_SAMPLES`` and falls back to the bundled
    sample folder under the user home. Sample sources are entirely optional:
    when a file is absent the document entry is skipped, never fatal.
    """
    env = os.environ.get("OE_DEMO_CAD_SAMPLES")
    if env:
        return Path(env)
    return Path.home() / "OpenConstructionERP_sample_data"

# Per-project namespace seed - distinct from seed_flagship's namespace so the
# generalized demo assets never collide with the dedicated flagship project.
_NS = uuid.UUID("d3705eed-0000-4000-8000-000000000000")

# Cap how many demo BOQ positions we wire to BIM elements. A handful is enough
# to make BIM<->BOQ navigation demonstrable without pretending the whole bill
# was modelled.
_MAX_LINKED_POSITIONS = 6
# How many real elements to attach to each linked position.
_ELEMS_PER_POSITION = 4


# ── Bundle specifications ─────────────────────────────────────────────────
#
# Each bundle reuses one flagship model (selected by ``source_format``) and a
# subset of its element groups for BOQ linking. ``geometry_asset`` is a
# filename under ``flagship_assets/``.
#
# ``documents`` lists the real, downloadable files attached to every project
# that maps to the bundle. Each entry is a dict:
#
#     kind:        "asset"  -> read bytes from flagship_assets/<src>
#                  "sample" -> read bytes from the CAD samples folder
#                              (resolved via OE_DEMO_CAD_SAMPLES); skipped when
#                              the file is absent, never fatal.
#     src:         source path. For "asset" it is a filename under
#                  flagship_assets/; for "sample" it is a path relative to the
#                  samples base (e.g. "PDF/Housing design standards2 LPG.pdf").
#     name:        display name written to the Document row.
#     category:    Document.category ("drawing" / "specification" / "model").
#     mime:        MIME type for the stored bytes.
#     tags:        list of tags for the Document row.
#     description: short Document.description.
#
# Every bundle ships at least two real PDFs (a plan set + a spec) so the
# Documents screen never shows byte-less stubs.

_DRAWINGS_PDF = {
    "kind": "asset",
    "src": "house_plans.pdf",
    "category": "drawing",
    "mime": "application/pdf",
    "tags": ["drawings", "plan-set"],
}
_SPEC_PDF = {
    "kind": "asset",
    "src": "housing_standards.pdf",
    "name": "Design standards and specification.pdf",
    "category": "specification",
    "mime": "application/pdf",
    "tags": ["specification", "standards"],
    "description": "Reference design standards and specification",
}

BUNDLES: dict[str, dict[str, Any]] = {
    "residential_ifc": {
        "source_format": "ifc",
        "geometry_asset": "geometry_ifc.dae.gz",
        "model_name": "Architectural model (IFC)",
        "discipline": "architectural",
        "model_format": "ifc",
        "link_groups": ["ifc_walls", "ifc_cover"],
        "documents": [
            {
                **_DRAWINGS_PDF,
                "name": "Architectural plan set.pdf",
                "description": "Reference architectural plan set",
            },
            dict(_SPEC_PDF),
            {
                "kind": "sample",
                "src": "IFC/ARC_SampleHouse_IFC4.ifc",
                "name": "Architectural model source.ifc",
                "category": "model",
                "mime": "application/x-step",
                "tags": ["bim", "ifc", "source-model"],
                "description": "Native IFC source model",
            },
        ],
    },
    "commercial_rvt": {
        "source_format": "rvt",
        "geometry_asset": "geometry_rvt.dae.gz",
        "model_name": "Coordinated model (Revit)",
        "discipline": "structural",
        "model_format": "rvt",
        "link_groups": ["rvt_walls", "rvt_floors", "rvt_columns", "rvt_foundation"],
        "documents": [
            {
                **_DRAWINGS_PDF,
                "name": "Coordinated drawing set.pdf",
                "description": "Reference coordinated drawing set",
            },
            dict(_SPEC_PDF),
            {
                "kind": "sample",
                "src": "RVT_Revit/ARC_rac_basic_sample_2023.rvt",
                "name": "Coordinated model source.rvt",
                "category": "model",
                "mime": "application/octet-stream",
                "tags": ["bim", "revit", "source-model"],
                "description": "Native Revit source model",
            },
        ],
    },
}


# ── Per-demo bundle map ───────────────────────────────────────────────────
#
# Maps each known demo_id to a bundle. Residential / housing / condo demos get
# the IFC architectural bundle; everything else (commercial, towers, hospitals,
# schools, mixed-use, structures, data centres, offices, …) gets the richer RVT
# coordinated bundle. ``flagship-house`` is intentionally absent - it owns its
# dedicated seed path (seed_flagship) and must not be double-seeded.

BUNDLE_MAP: dict[str, str] = {
    # Core built-ins
    "residential-berlin": "residential_ifc",
    "office-london": "commercial_rvt",
    "office-shanghai": "commercial_rvt",
    "medical-us": "commercial_rvt",
    "warehouse-dubai": "commercial_rvt",
    "school-paris": "commercial_rvt",
    # Partner packs
    "commercial-auckland": "commercial_rvt",
    "commercial-denver": "commercial_rvt",
    "commercial-london": "commercial_rvt",
    "condo-toronto": "residential_ifc",
    "data-center-melbourne": "commercial_rvt",
    "govt-building-delhi": "commercial_rvt",
    "hospital-jeddah": "commercial_rvt",
    "hospital-lyon": "commercial_rvt",
    "it-park-bangalore": "commercial_rvt",
    "mixed-use-riyadh": "commercial_rvt",
    "mixed-use-sydney": "commercial_rvt",
    "modular-housing": "residential_ifc",
    "office-frankfurt": "commercial_rvt",
    "office-montreal": "commercial_rvt",
    "office-rio": "commercial_rvt",
    "rc-structure-formwork": "commercial_rvt",
    "residential-saopaulo": "residential_ifc",
    "school-christchurch": "commercial_rvt",
    "solar-bess-epc": "commercial_rvt",
    "tower-abudhabi": "commercial_rvt",
}

# demo_ids that own a dedicated seed path and must never be attached here.
_SKIP_DEMOS = frozenset({"flagship-house"})


def _u(*parts: str) -> uuid.UUID:
    """Deterministic uuid5 in the demo-asset namespace (idempotent re-seed)."""
    return uuid.uuid5(_NS, ":".join(parts))


def bundle_key_for(demo_id: str) -> str | None:
    """Return the bundle key for a demo, or ``None`` when none is mapped."""
    if demo_id in _SKIP_DEMOS:
        return None
    return BUNDLE_MAP.get(demo_id)


def _load_spec() -> dict | None:
    if not SPEC_PATH.exists():
        return None
    try:
        return json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt spec must not break installs
        logger.warning("seed_demo_assets: failed to read flagship spec", exc_info=True)
        return None


def _source_model(spec: dict, source_format: str) -> dict | None:
    for m in spec.get("models", []):
        if m.get("model_format") == source_format:
            return m
    return None


async def attach_demo_assets(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: str | uuid.UUID,
    bundle_key: str,
) -> dict:
    """Attach a baked BIM model + geometry + plan-set PDF to a demo project.

    Creates a :class:`BIMModel` with its real :class:`BIMElement` rows and
    decompressed ``.dae`` geometry, links a few of the project's EXISTING BOQ
    positions to those elements (both the position ``cad_element_ids`` array
    and ``BOQElementLink`` rows), and writes the real PDF bytes to disk with a
    :class:`Document` row pointing at the on-disk file.

    Idempotent (deterministic ids) and resilient (never raises). Returns a
    small status dict for logging.

    Args:
        session: Active async session (the caller owns commit).
        project_id: Project to attach assets to.
        owner_id: User id recorded as uploader / creator.
        bundle_key: Key into :data:`BUNDLES`.
    """
    try:
        return await _attach_demo_assets_inner(session, project_id, owner_id, bundle_key)
    except Exception:  # pragma: no cover - never break a demo install
        logger.warning(
            "seed_demo_assets: attachment failed for project %s bundle %s",
            project_id,
            bundle_key,
            exc_info=True,
        )
        return {"status": "error", "bundle": bundle_key}


async def _attach_demo_assets_inner(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: str | uuid.UUID,
    bundle_key: str,
) -> dict:
    bundle = BUNDLES.get(bundle_key)
    if bundle is None:
        return {"status": "skipped", "reason": f"unknown bundle {bundle_key}"}

    spec = _load_spec()
    if not spec:
        return {"status": "skipped", "reason": "no flagship assets"}

    src = _source_model(spec, bundle["source_format"])
    if src is None:
        return {"status": "skipped", "reason": f"no source model for {bundle['source_format']}"}

    from app.modules.bim_hub.file_storage import save_geometry
    from app.modules.bim_hub.models import BIMElement, BIMModel, BOQElementLink
    from app.modules.boq.models import BOQ, Position
    from app.modules.documents.models import Document

    pid = project_id
    owner = str(owner_id)
    src_model_id = str(src["id"])

    # ── 1. BIM model (idempotent) ───────────────────────────────────────
    mid = _u(str(pid), "bim", bundle_key)
    existing_model = await session.get(BIMModel, mid)
    if existing_model is not None:
        return {"status": "already", "project_id": str(pid), "model_id": str(mid)}

    canonical_key: str | None = None
    geom_name = bundle.get("geometry_asset")
    if geom_name:
        gpath = ASSETS / geom_name
        if gpath.exists():
            content = gzip.decompress(gpath.read_bytes())
            canonical_key = await save_geometry(pid, mid, ".dae", content)

    model_status = "ready" if canonical_key else "needs_converter"
    session.add(
        BIMModel(
            id=mid,
            project_id=pid,
            name=bundle["model_name"],
            discipline=bundle.get("discipline"),
            model_format=bundle["model_format"],
            version="1",
            status=model_status,
            element_count=src.get("element_count", len(src.get("elements", []))),
            storey_count=src.get("storey_count", 0),
            canonical_file_path=canonical_key,
            metadata_={
                "geometry_quality": src.get("geometry_quality", "real"),
                "geometry_type": "real" if canonical_key else "none",
                "converter_source": "ddc-community",
                "source": "demo_asset_seed",
                "bundle": bundle_key,
            },
        )
    )
    await session.flush()  # model row must exist before its elements (FK)

    # ── 2. BIM elements ─────────────────────────────────────────────────
    elem_uuid: dict[str, uuid.UUID] = {}
    for e in src.get("elements", []):
        sid = e["stable_id"]
        eu = _u(str(mid), "el", sid)
        elem_uuid[sid] = eu
        session.add(
            BIMElement(
                id=eu,
                model_id=mid,
                stable_id=sid,
                element_type=e.get("element_type"),
                name=e.get("name"),
                storey=e.get("storey"),
                discipline=e.get("discipline"),
                quantities=e.get("quantities") or {},
                properties=e.get("props") or {},
                geometry_hash=e.get("geometry_hash"),
                bounding_box=e.get("bounding_box"),
                mesh_ref=e.get("mesh_ref"),
                metadata_={"source": "demo_asset_seed"},
            )
        )
    await session.flush()

    # ── 3. Link a few EXISTING demo BOQ positions to bundle elements ─────
    # Build the candidate element-id pool from the bundle's link groups, in
    # order, so links are deterministic and concentrated on real groups.
    groups = spec.get("groups", {})
    pooled_elem_ids: list[uuid.UUID] = []
    for gk in bundle.get("link_groups", []):
        grp = groups.get(gk)
        if not grp or grp.get("model_id") != src_model_id:
            continue
        for sid in grp.get("stable_ids", []):
            eu = elem_uuid.get(sid)
            if eu is not None:
                pooled_elem_ids.append(eu)

    n_links = 0
    if pooled_elem_ids:
        # Pick the project's detailed BOQ (the one with the most leaf
        # positions) and link its first few leaf positions.
        boqs = list((await session.execute(select(BOQ).where(BOQ.project_id == pid))).scalars().all())
        leaf_positions: list[Position] = []
        if boqs:
            best_boq = max(boqs, key=lambda b: len(b.positions))
            leaf_positions = [
                p for p in sorted(best_boq.positions, key=lambda x: x.sort_order or 0) if (p.unit or "") != ""
            ]

        cursor = 0
        for pos in leaf_positions[:_MAX_LINKED_POSITIONS]:
            chunk = pooled_elem_ids[cursor : cursor + _ELEMS_PER_POSITION]
            if not chunk:
                break
            cursor += _ELEMS_PER_POSITION
            existing_ids = list(pos.cad_element_ids or [])
            pos.cad_element_ids = existing_ids + [str(eu) for eu in chunk]
            for eu in chunk:
                session.add(
                    BOQElementLink(
                        boq_position_id=pos.id,
                        bim_element_id=eu,
                        link_type="auto_matched",
                        confidence="high",
                        rule_id="demo_asset_seed",
                        metadata_={"bundle": bundle_key},
                    )
                )
                n_links += 1
        await session.flush()

    # ── 4. Real downloadable documents (best-effort, per entry) ──────────
    # Every bundle declares a ``documents`` list. We materialize each one as
    # real bytes on disk plus a Document row pointing at the absolute path, so
    # the Documents screen offers genuine HTTP-200 downloads (no byte-less
    # stubs). Each entry is isolated: a missing or unreadable source skips
    # THAT entry only and never aborts the rest of the install.
    from app.modules.documents.service import UPLOAD_BASE  # type: ignore

    samples_base = _samples_base()
    up = Path(UPLOAD_BASE) / str(pid)
    docs_written = 0
    for entry in bundle.get("documents", []):
        try:
            kind = entry.get("kind", "asset")
            src = entry.get("src", "")
            name = entry.get("name") or Path(src).name
            if kind == "sample":
                source_path = samples_base / src
            else:
                source_path = ASSETS / src
            if not source_path.exists():
                # Optional source absent (common for native CAD samples) - skip.
                continue

            doc_id = _u(str(pid), "doc", name)
            existing_doc = await session.get(Document, doc_id)
            if existing_doc is not None:
                docs_written += 1
                continue

            up.mkdir(parents=True, exist_ok=True)
            fname = f"{uuid.uuid5(_NS, f'{pid}:doc:{name}').hex[:12]}_{name}"
            dest = up / fname
            data = source_path.read_bytes()
            dest.write_bytes(data)
            session.add(
                Document(
                    id=doc_id,
                    project_id=pid,
                    name=name,
                    description=entry.get("description", ""),
                    category=entry.get("category", "drawing"),
                    file_size=len(data),
                    mime_type=entry.get("mime", "application/octet-stream"),
                    file_path=str(dest),
                    uploaded_by=owner,
                    tags=list(entry.get("tags", [])),
                    metadata_={"source": "demo_asset_seed", "bundle": bundle_key},
                )
            )
            await session.flush()
            docs_written += 1
        except Exception:  # noqa: BLE001 - a single document is non-critical
            logger.warning(
                "seed_demo_assets: document attach skipped for %s (%s)",
                pid,
                entry.get("name") or entry.get("src"),
                exc_info=True,
            )

    result = {
        "status": "ok",
        "project_id": str(pid),
        "model_id": str(mid),
        "elements": len(elem_uuid),
        "links": n_links,
        "geometry": bool(canonical_key),
        "documents": docs_written,
        "bundle": bundle_key,
    }
    logger.info("Demo assets attached: %s", result)
    return result
