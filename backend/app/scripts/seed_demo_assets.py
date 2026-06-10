# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Attach the full visible CAD/BIM file set (RVT + IFC + DWG + PDF) to demos.

The flagship installer (:mod:`app.scripts.seed_flagship`) is the only working
ORM byte-attachment path; it restores a single reference project from committed
assets. This module *generalizes* that logic so every marketplace demo project
(residential, commercial, hospital, …) ships the same complete asset set the
flagship shows, instead of empty BIM / DWG / Documents screens.

Every demo project receives, consistently:

    * a Revit (RVT) 3D BIM model with real elements and ``.dae`` geometry,
    * an IFC 3D BIM model with real elements and ``.dae`` geometry,
    * a DWG drawing in the dedicated DWG Takeoff module (2D, metadata-only -
      a DWG carries no 3D mesh, so it never enters the BIM 3D hub),
    * real downloadable PDFs (a plan set + a spec) and native CAD source
      documents on the Documents screen (IFC always, via a committed in-repo
      fixture; RVT and DWG when the optional samples folder is present).

No CAD conversion ever runs here. We reuse the already-baked, committed assets:

    app/scripts/flagship_assets/flagship.json        spec (built by _bake_flagship.py)
    app/scripts/flagship_assets/geometry_ifc.dae.gz  real DDC IFC geometry
    app/scripts/flagship_assets/geometry_rvt.dae.gz  real DDC Revit geometry
    app/scripts/flagship_assets/house_plans.pdf      reference plan set
    app/scripts/flagship_assets/housing_standards.pdf  reference spec
    frontend/e2e/fixtures/dashboards/sample-project.ifc  committed native IFC

The :data:`_BIM_MODELS` / :data:`_DWG_MODEL` sets are attached to every project.
A *bundle* (:data:`BUNDLES`) only chooses which model is *primary* (the one a
handful of BOQ positions are linked to) and which plan-set PDF labels to use.
The public entry point :func:`attach_demo_assets` is fully idempotent
(deterministic ``uuid5`` ids per project) and dialect-agnostic (pure ORM), and
every step is wrapped so a missing asset never aborts a demo install.
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

# Monorepo root (backend/app/scripts/seed_demo_assets.py -> parents[3]). Used to
# resolve ``kind="repo"`` document sources - committed sample files that always
# ship with the package, unlike the optional ``kind="sample"`` CAD folder. When
# the app runs from an installed wheel (no monorepo tree) this path simply will
# not exist and the document entry is skipped, exactly like a missing sample.
_REPO_ROOT = Path(__file__).resolve().parents[3]


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
# Every project gets BOTH BIM models (:data:`_BIM_MODELS`) and the DWG drawing
# (:data:`_DWG_MODEL`). A bundle only selects the *primary* model used for the
# BOQ<->BIM link demo (``source_format`` + ``link_groups``, group keys from the
# flagship spec) and the per-project ``documents`` list.
#
# ``documents`` lists the real, downloadable files attached to every project
# that maps to the bundle. Each entry is a dict:
#
#     kind:        "asset"  -> read bytes from flagship_assets/<src>
#                  "repo"   -> read bytes from a committed in-repo file at
#                              <repo-root>/<src> (e.g. the native IFC fixture);
#                              present in the monorepo, absent in a wheel.
#                  "sample" -> read bytes from the CAD samples folder
#                              (resolved via OE_DEMO_CAD_SAMPLES); skipped when
#                              the file is absent, never fatal.
#     src:         source path. For "asset" it is a filename under
#                  flagship_assets/; for "repo" it is relative to the repo root;
#                  for "sample" it is a path relative to the samples base
#                  (e.g. "RVT_Revit/ARC_rac_basic_sample_2023.rvt").
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

# Native CAD source documents. These attach a real *native* file (RVT / IFC /
# DWG) to the Documents screen, on top of the converted 3D geometry that the
# BIM models already carry. The bytes come from the optional CAD samples folder
# (``OE_DEMO_CAD_SAMPLES``); when that folder is absent - the usual case for a
# shipped package, where multi-megabyte native CAD files are not committed - the
# entry is silently skipped and the project still shows the IFC source (see
# ``_IFC_SOURCE_DOC`` below, which falls back to a committed in-repo IFC).
_RVT_SOURCE_DOC = {
    "kind": "sample",
    "src": "RVT_Revit/ARC_rac_basic_sample_2023.rvt",
    "name": "Coordinated model source.rvt",
    "category": "model",
    "mime": "application/octet-stream",
    "tags": ["bim", "revit", "source-model", "rvt"],
    "description": "Native Revit source model",
}
_DWG_SOURCE_DOC = {
    "kind": "sample",
    "src": "DWG/ARC_house.dwg",
    "name": "Floor plan source.dwg",
    "category": "drawing",
    "mime": "image/vnd.dwg",
    "tags": ["drawings", "dwg", "source-drawing"],
    "description": "Native AutoCAD DWG drawing",
}
# IFC source document. Unlike RVT/DWG a real IFC sample is committed in the repo
# (``frontend/e2e/fixtures/dashboards/sample-project.ifc``, ~2.4 MB, a genuine
# ISO-10303-21 file), so this entry uses ``kind="repo"`` and always materializes
# even in a shipped package. It is the one native CAD source guaranteed visible
# on every demo project's Documents screen.
_IFC_SOURCE_DOC = {
    "kind": "repo",
    "src": "frontend/e2e/fixtures/dashboards/sample-project.ifc",
    "name": "Architectural model source.ifc",
    "category": "model",
    "mime": "application/x-step",
    "tags": ["bim", "ifc", "source-model"],
    "description": "Native IFC source model",
}

# Every demo project receives the same native-source document set so the
# Documents screen always lists an RVT, an IFC and a DWG entry (each materializes
# only when its bytes are available; IFC always does, via the committed repo
# fixture). The two plan-set PDFs are added per bundle below.
_NATIVE_SOURCE_DOCS = [dict(_IFC_SOURCE_DOC), dict(_RVT_SOURCE_DOC), dict(_DWG_SOURCE_DOC)]


# Every demo project receives BOTH 3D BIM models (RVT + IFC) and the 2D DWG
# drawing reference, so /bim shows a Revit AND an IFC model, /dwg-takeoff shows a
# DWG drawing, and /documents lists native RVT/IFC/DWG sources plus the PDFs. A
# bundle only chooses which model is the *primary* one used to link a handful of
# BOQ positions to real geometry (purely cosmetic for the BOQ<->BIM demo).
#
# ``bim_models`` is the fixed set of 3D models attached to every project, by
# source_format. ``dwg_model`` is the 2D drawing attached to every project.
_BIM_MODELS: list[dict[str, Any]] = [
    {
        "source_format": "rvt",
        "geometry_asset": "geometry_rvt.dae.gz",
        "model_name": "Coordinated model (Revit)",
        "discipline": "structural",
        "model_format": "rvt",
    },
    {
        "source_format": "ifc",
        "geometry_asset": "geometry_ifc.dae.gz",
        "model_name": "Architectural model (IFC)",
        "discipline": "architectural",
        "model_format": "ifc",
    },
]
# The 2D DWG drawing reference attached to every project (routed to the dedicated
# DWG Takeoff module, never the BIM 3D hub - a DWG carries no 3D mesh). It is a
# metadata-only row (status "uploaded", no parsed entities), exactly like the
# flagship seed's DWG handling.
_DWG_MODEL: dict[str, Any] = {
    "source_format": "dwg",
    "model_name": "Floor plans (DWG)",
    "discipline": "architecture",
    "model_format": "dwg",
}

BUNDLES: dict[str, dict[str, Any]] = {
    "residential_ifc": {
        # Primary model used for the BOQ<->BIM link demo.
        "source_format": "ifc",
        "link_groups": ["ifc_walls", "ifc_cover"],
        "documents": [
            {
                **_DRAWINGS_PDF,
                "name": "Architectural plan set.pdf",
                "description": "Reference architectural plan set",
            },
            dict(_SPEC_PDF),
            *(dict(d) for d in _NATIVE_SOURCE_DOCS),
        ],
    },
    "commercial_rvt": {
        # Primary model used for the BOQ<->BIM link demo.
        "source_format": "rvt",
        "link_groups": ["rvt_walls", "rvt_floors", "rvt_columns", "rvt_foundation"],
        "documents": [
            {
                **_DRAWINGS_PDF,
                "name": "Coordinated drawing set.pdf",
                "description": "Reference coordinated drawing set",
            },
            dict(_SPEC_PDF),
            *(dict(d) for d in _NATIVE_SOURCE_DOCS),
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
    """Attach the full, visible CAD/BIM file set to a demo project.

    Every demo project gets a consistent set so the BIM, DWG Takeoff and
    Documents screens are never blank and always show each major format:

      * a Revit (RVT) 3D BIM model with real elements and ``.dae`` geometry,
      * an IFC 3D BIM model with real elements and ``.dae`` geometry,
      * a DWG drawing reference in the dedicated DWG Takeoff module (2D, no
        mesh - metadata-only, exactly like the flagship seed),
      * real downloadable PDFs (a plan set + a spec) and native CAD source
        documents (IFC always, RVT/DWG when their bytes are available),
      * a few of the project's EXISTING BOQ positions linked to the primary
        model's real elements (``cad_element_ids`` + ``BOQElementLink`` rows).

    Idempotent (deterministic ids) and resilient (never raises). Returns a
    small status dict for logging.

    Args:
        session: Active async session (the caller owns commit).
        project_id: Project to attach assets to.
        owner_id: User id recorded as uploader / creator.
        bundle_key: Key into :data:`BUNDLES` (chooses the primary link model).
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


async def _attach_one_bim_model(
    session: AsyncSession,
    pid: uuid.UUID,
    spec: dict,
    model_def: dict[str, Any],
) -> tuple[uuid.UUID | None, dict[str, uuid.UUID], bool]:
    """Attach one 3D BIM model (RVT or IFC) with elements + geometry.

    Returns ``(model_id, {stable_id: element_uuid}, geometry_present)``. When
    the spec has no matching source model the model id is ``None`` and the maps
    are empty. Idempotent: an already-present model returns its id with an empty
    element map (the elements were attached on the first run).
    """
    from app.modules.bim_hub.file_storage import save_geometry
    from app.modules.bim_hub.models import BIMElement, BIMModel

    src = _source_model(spec, model_def["source_format"])
    if src is None:
        return None, {}, False

    mid = _u(str(pid), "bim", model_def["model_format"])
    if await session.get(BIMModel, mid) is not None:
        return mid, {}, True  # already attached on a previous run

    canonical_key: str | None = None
    geom_name = model_def.get("geometry_asset")
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
            name=model_def["model_name"],
            discipline=model_def.get("discipline"),
            model_format=model_def["model_format"],
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
            },
        )
    )
    await session.flush()  # model row must exist before its elements (FK)

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
    return mid, elem_uuid, bool(canonical_key)


async def _attach_dwg_drawing(
    session: AsyncSession,
    pid: uuid.UUID,
    owner: str,
    spec: dict,
) -> bool:
    """Attach the 2D DWG drawing reference to the DWG Takeoff module.

    DWG carries no 3D mesh, so (exactly like the flagship seed) it is routed to
    the dedicated ``DwgDrawing`` table, never the BIM 3D hub. This is a
    metadata-only row (status ``uploaded``, no parsed entities) so the DWG
    Takeoff module lists the drawing without pretending geometry was parsed.
    Idempotent on a deterministic id. Returns True when a row exists afterwards.
    """
    from app.modules.dwg_takeoff.models import DwgDrawing

    src = _source_model(spec, _DWG_MODEL["source_format"])
    if src is None:
        return False

    did = _u(str(pid), "dwg", _DWG_MODEL["model_format"])
    if await session.get(DwgDrawing, did) is not None:
        return True  # already attached on a previous run

    fmt = _DWG_MODEL["model_format"]
    session.add(
        DwgDrawing(
            id=did,
            project_id=pid,
            name=_DWG_MODEL["model_name"],
            filename=f"{_DWG_MODEL['model_name']}.{fmt}",
            file_format=fmt,
            # No source file ships in the package; a metadata-only reference row
            # lists the drawing in the DWG Takeoff module. Status "uploaded"
            # (not "ready") keeps the UI honest: no parsed entities to render.
            file_path="",
            size_bytes=0,
            status="uploaded",
            discipline=_DWG_MODEL.get("discipline"),
            created_by=owner,
            metadata_={
                "source": "demo_asset_seed",
                "seed_reference_only": True,
                "element_count": src.get("element_count", 0),
            },
        )
    )
    await session.flush()
    return True


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

    from app.modules.bim_hub.models import BOQElementLink
    from app.modules.boq.models import BOQ, Position
    from app.modules.documents.models import Document

    pid = project_id
    owner = str(owner_id)

    # ── 1+2. Both 3D BIM models (RVT + IFC) with elements + geometry ─────
    # Every project carries BOTH so /bim shows a Revit AND an IFC model. We
    # remember the primary model's element map (chosen by the bundle's
    # ``source_format``) for the BOQ<->BIM link demo below.
    primary_format = bundle["source_format"]
    primary_model_id: uuid.UUID | None = None
    primary_src_model_id: str | None = None
    primary_elem_uuid: dict[str, uuid.UUID] = {}
    bim_geometry = False
    bim_models_attached = 0
    for model_def in _BIM_MODELS:
        mid, elem_uuid, geom = await _attach_one_bim_model(session, pid, spec, model_def)
        if mid is not None:
            bim_models_attached += 1
            bim_geometry = bim_geometry or geom
        if model_def["source_format"] == primary_format and mid is not None:
            primary_model_id = mid
            primary_elem_uuid = elem_uuid
            src = _source_model(spec, primary_format)
            primary_src_model_id = str(src["id"]) if src else None

    # ── 2b. The 2D DWG drawing (DWG Takeoff module, never the BIM 3D hub) ─
    dwg_attached = await _attach_dwg_drawing(session, pid, owner, spec)

    # ── 3. Link a few EXISTING demo BOQ positions to the primary model ───
    # Build the candidate element-id pool from the bundle's link groups, in
    # order, so links are deterministic and concentrated on real groups. Only
    # runs on a first install (primary_elem_uuid is empty on an idempotent
    # re-run, so this block self-skips and never double-links).
    groups = spec.get("groups", {})
    pooled_elem_ids: list[uuid.UUID] = []
    if primary_src_model_id is not None:
        for gk in bundle.get("link_groups", []):
            grp = groups.get(gk)
            if not grp or grp.get("model_id") != primary_src_model_id:
                continue
            for sid in grp.get("stable_ids", []):
                eu = primary_elem_uuid.get(sid)
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
                # Optional native CAD samples folder (multi-MB RVT/DWG); usually
                # absent in a shipped package, so this entry is then skipped.
                source_path = samples_base / src
            elif kind == "repo":
                # Committed in-repo sample (e.g. the real IFC fixture); present
                # in the monorepo, absent in an installed wheel.
                source_path = _REPO_ROOT / src
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
        "bim_models": bim_models_attached,
        "primary_model_id": str(primary_model_id) if primary_model_id else None,
        "dwg": dwg_attached,
        "elements": len(primary_elem_uuid),
        "links": n_links,
        "geometry": bim_geometry,
        "documents": docs_written,
        "bundle": bundle_key,
    }
    logger.info("Demo assets attached: %s", result)
    return result
