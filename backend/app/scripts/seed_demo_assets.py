# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Attach the full visible CAD/BIM file set (RVT + IFC + DWG + PDF) to demos.

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
import hashlib
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

# Procedural showcase spec for the Retail Market Heilbronn demo. Unlike the
# flagship (a real DDC-converted mesh shared by every demo), this project ships
# its own purpose-built procedural model: one IFC-format BIM model whose
# elements and ``.glb`` geometry are generated from the building's canonical
# geometry by ``app.scripts.gen_retail_heilbronn_assets``. Both files are
# committed next to this module.
RETAIL_HEILBRONN_DEMO_ID = "retail-market-heilbronn"
RETAIL_SPEC_PATH = ASSETS / "retail_heilbronn.json"
RETAIL_GLB_PATH = ASSETS / "retail_heilbronn.glb.gz"

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
# German demo projects get the purpose-built vector Grundriss (M 1:100, German
# room labels, dimension chains in metres) instead of the scanned US book
# plate, so a German file name never sits on top of English content. The file
# is generated deterministically by app/scripts/generate_grundriss_pdf.py.
_GRUNDRISS_PDF = {
    "kind": "asset",
    "src": "grundriss_erdgeschoss.pdf",
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
    "description": "Native DWG drawing",
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
                **_GRUNDRISS_PDF,
                "name": "Coordinated drawing set.pdf",
                "description": "Reference coordinated drawing set",
            },
            dict(_SPEC_PDF),
            *(dict(d) for d in _NATIVE_SOURCE_DOCS),
        ],
    },
    # Procedural showcase: the Retail Market Heilbronn demo ships its OWN
    # purpose-built model and geometry (see RETAIL_SPEC_PATH), not the shared
    # flagship mesh, so it is attached by a dedicated path
    # (``_attach_retail_heilbronn``). ``link_groups`` selects the structural and
    # facade element groups (KG 320/330/360/470) whose leaf BOQ positions get
    # ``cad_element_ids`` links. Documents reuse the committed reference PDFs.
    "retail_heilbronn": {
        "source_format": "ifc",
        "link_groups": [
            "retail_columns",
            "retail_foundations",
            "retail_binders",
            "retail_facade",
            "retail_tga",
        ],
        "documents": [
            {
                **_GRUNDRISS_PDF,
                "name": "Lageplan und Grundriss.pdf",
                "description": "Reference site plan and floor plan",
            },
            {
                **_SPEC_PDF,
                "name": "Baubeschreibung und Standards.pdf",
                "description": "Reference building description and standards",
            },
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
#
# Every demo_id that resolves to a DemoTemplate must appear here. A project
# absent from this map is never even offered to ``attach_demo_assets``, so it
# gets no BIMModel row, and a missing model silently empties everything that
# hangs off one: the BCF issue register skips a project with no model, and the
# coordination federation has nothing to group. That failure mode is invisible
# - both seeders log the skip at debug level - so the map is guarded by
# ``tests/unit/test_every_demo_project_is_offered_a_bim_model.py`` rather than
# by anyone noticing an empty screen.

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
    "infrastructure-capetown": "commercial_rvt",
    "it-park-bangalore": "commercial_rvt",
    "mixed-use-barcelona": "commercial_rvt",
    "mixed-use-istanbul": "commercial_rvt",
    "mixed-use-johannesburg": "commercial_rvt",
    "mixed-use-mexico-city": "commercial_rvt",
    "mixed-use-riyadh": "commercial_rvt",
    "mixed-use-sydney": "commercial_rvt",
    "modular-housing": "residential_ifc",
    "office-amsterdam": "commercial_rvt",
    "office-debrecen": "commercial_rvt",
    "office-frankfurt": "commercial_rvt",
    "office-montreal": "commercial_rvt",
    "office-rio": "commercial_rvt",
    "office-tokyo": "commercial_rvt",
    "rc-structure-formwork": "commercial_rvt",
    "residential-budapest": "residential_ifc",
    "residential-monterrey": "residential_ifc",
    "residential-moscow": "residential_ifc",
    "residential-rome": "residential_ifc",
    "residential-saopaulo": "residential_ifc",
    "residential-seoul": "residential_ifc",
    "residential-shenzhen": "residential_ifc",
    "residential-warsaw": "residential_ifc",
    "renovation-guangzhou": "commercial_rvt",
    "villa-suzhou": "residential_ifc",
    "office-milan": "commercial_rvt",
    # Heidelberg and Karlsruhe are Heilbronn's siblings, but they take the
    # shared RVT bundle rather than ``retail_heilbronn``. That bundle is not a
    # retail flavour of the generic set: it dispatches to
    # ``_attach_retail_heilbronn``, which attaches the procedural model built
    # from the Heilbronn building's own canonical geometry. Pointing a sibling
    # at it would hand Heidelberg a model of Heilbronn - a wrong building
    # presented as its own, which is worse than the empty screen this map is
    # here to fix. They keep the generic coordinated set until each one has
    # procedural assets of its own.
    "retail-market-heidelberg": "commercial_rvt",
    "retail-market-heilbronn": "retail_heilbronn",
    "retail-market-karlsruhe": "commercial_rvt",
    "school-christchurch": "commercial_rvt",
    "school-stpetersburg": "commercial_rvt",
    "solar-bess-epc": "commercial_rvt",
    "tower-abudhabi": "commercial_rvt",
    "office-toronto": "commercial_rvt",
    "residential-vancouver": "residential_ifc",
    "office-zurich": "commercial_rvt",
    "residential-lausanne": "residential_ifc",
    "office-vienna": "commercial_rvt",
    "residential-salzburg": "residential_ifc",
    # Tier 2 packs: Singapore, Ireland, Belgium, Czechia, Portugal,
    # Indonesia, Nigeria.
    "office-singapore": "commercial_rvt",
    "residential-singapore": "residential_ifc",
    "office-dublin": "commercial_rvt",
    "residential-cork": "residential_ifc",
    "office-brussels": "commercial_rvt",
    "residential-antwerp": "residential_ifc",
    "office-prague": "commercial_rvt",
    "residential-brno": "residential_ifc",
    "residential-zagreb": "residential_ifc",
    "office-split": "commercial_rvt",
    "office-lisbon": "commercial_rvt",
    "residential-porto": "residential_ifc",
    "commercial-jakarta": "commercial_rvt",
    "residential-surabaya": "residential_ifc",
    "commercial-lagos": "commercial_rvt",
    "residential-abuja": "residential_ifc",
    # Nordic packs: Sweden, Norway, Denmark.
    "office-stockholm": "commercial_rvt",
    "residential-gothenburg": "residential_ifc",
    "office-oslo": "commercial_rvt",
    "residential-bergen": "residential_ifc",
    "office-copenhagen": "commercial_rvt",
    "residential-aarhus": "residential_ifc",
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


async def _ensure_bim_artifacts(session: AsyncSession, pid: uuid.UUID, mid: uuid.UUID) -> None:
    """Best-effort bake of a seeded model's GLB + streaming tileset + Parquet.

    Delegates to :meth:`BIMHubService.ensure_artifacts`, which is idempotent
    and self-guards each step. Runs inside the seed transaction: the model and
    its elements are already flushed, so the same-session reads see them, and
    the GLB / tiles / Parquet are written straight to storage. A demo seed must
    never fail because artifact baking hit a problem, so everything is guarded.
    Called on both the fresh-attach path and the already-attached early return
    so an instance seeded before artifact baking was wired in still gets the
    sidecars backfilled on the next startup.
    """
    from app.modules.bim_hub.service import BIMHubService

    try:
        await BIMHubService(session).ensure_artifacts(pid, mid)
    except Exception as exc:  # noqa: BLE001 - seed artifacts are best-effort
        logger.warning("Seed artifact baking failed for model %s (non-fatal): %s", mid, exc)


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
        await _ensure_bim_artifacts(session, pid, mid)  # backfill on re-seed
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
    await _ensure_bim_artifacts(session, pid, mid)
    return mid, elem_uuid, bool(canonical_key)


async def _attach_dwg_drawing(
    session: AsyncSession,
    pid: uuid.UUID,
    owner: str,
    spec: dict,
) -> bool:
    """Attach the 2D drawing to the DWG Takeoff module as a ready DXF.

    DWG/DXF carries no 3D mesh, so (exactly like the flagship seed) it is
    routed to the dedicated ``DwgDrawing`` table, never the BIM 3D hub.

    The drawing is seeded as an already-converted DXF (status ``ready`` with
    parsed entities on disk) so a first-time user opens ``/dwg-takeoff`` and
    sees a working viewer immediately - no DDC converter needed and no
    perpetual "Converting..." spinner. DXF parses out of the box via ezdxf
    (a base dependency). When ezdxf is somehow unavailable the helper falls
    back to a metadata-only reference row, which the backend reports as
    ``needs_conversion`` (a clear convert CTA, still never a spinner).

    Idempotent on a deterministic id. Returns True when a drawing exists
    afterwards.

    The spec model is read for its presence only - it says the bundle carries a
    2D drawing at all. Nothing is copied off it: the seeded DXF is authored
    here, so the spec model's element count belongs to the converted CAD file
    behind the spec and not to the drawing this attaches.
    """
    if _source_model(spec, _DWG_MODEL["source_format"]) is None:
        return False

    did = _u(str(pid), "dwg", _DWG_MODEL["model_format"])

    from app.scripts.seed_dwg_drawing import seed_ready_dwg_drawing

    return await seed_ready_dwg_drawing(
        session,
        drawing_id=did,
        project_id=pid,
        owner=owner,
        name=_DWG_MODEL["model_name"],
        discipline=_DWG_MODEL.get("discipline"),
        source="demo_asset_seed",
    )


async def _link_positions_to_pool(
    session: AsyncSession,
    pid: uuid.UUID,
    pooled_elem_ids: list[uuid.UUID],
    bundle_key: str,
) -> int:
    """Link the first few leaf BOQ positions to a pool of BIM element ids.

    Writes ``cad_element_ids`` on each position plus a ``BOQElementLink`` row per
    element, so BIM<->BOQ navigation is demonstrable. Only runs on a first
    install: the pool is empty on an idempotent re-run (elements already
    attached), so this self-skips and never double-links. Returns the link count.
    """
    if not pooled_elem_ids:
        return 0
    from app.modules.bim_hub.models import BOQElementLink
    from app.modules.boq.models import BOQ, Position

    # Pick the project's detailed BOQ (the one with the most leaf positions).
    boqs = list((await session.execute(select(BOQ).where(BOQ.project_id == pid))).scalars().all())
    leaf_positions: list[Position] = []
    if boqs:
        best_boq = max(boqs, key=lambda b: len(b.positions))
        leaf_positions = [
            p for p in sorted(best_boq.positions, key=lambda x: x.sort_order or 0) if (p.unit or "") != ""
        ]

    n_links = 0
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
    return n_links


# Demo document bytes live in one content-addressed store per install rather
# than in a folder per project. Every demo project is handed the same native
# CAD sources, so a per-project copy stored the same multi-megabyte model once
# for each project. The blob is named after the digest of its own content,
# which keeps the store an ordinary directory: no symlinks, no hard links and
# no index, every path is a whole file any tool can open, and the whole store
# can be verified with sha256sum alone.
_SHARED_BLOB_DIRNAME = "_shared"


def _blob_present(file_path: str | None) -> bool:
    """True when a Document row's recorded file is really on disk."""
    if not file_path:
        return False
    try:
        return Path(file_path).is_file()
    except OSError:
        return False


def _materialize_blob(shared_dir: Path, data: bytes, name: str) -> Path:
    """Write ``data`` into the shared store and return the path it now lives at.

    Safe to run twice and safe to interrupt. The bytes go to a temporary name
    and are renamed into place, and because the final name is the digest of the
    content, a file that exists under that name is whole by construction: there
    is no state in which a half-written blob is mistaken for a finished one. A
    process killed mid-write leaves a ``.tmp`` that no Document row points at
    and that the next run ignores.
    """
    digest = hashlib.sha256(data).hexdigest()[:32]
    dest = shared_dir / f"{digest}{Path(name).suffix.lower()}"
    if dest.is_file():
        return dest
    shared_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    return dest


async def _adopt_into_shared_store(session: AsyncSession, document: Any, shared_dir: Path) -> bool:
    """Re-point an already seeded document at the shared store. True when moved.

    An install seeded before the store existed holds one copy of every native
    source per project, and its rows are perfectly healthy, so the idempotency
    check leaves them alone and the disk never shrinks. Without this, the saving
    only ever arrives on a data directory that starts empty.

    Ordered blob first, row second, unlink last, so an interruption leaves a file
    nobody points at rather than a row pointing at nothing. The per-project copy
    is removed only when it sits inside the upload tree and no other document
    still names it, which is the same question ``delete_document`` now asks.
    """
    from app.modules.documents.models import Document

    old = Path(document.file_path)
    if old.parent == shared_dir:
        return False

    data = old.read_bytes()
    dest = _materialize_blob(shared_dir, data, document.name)
    if dest == old:
        return False
    document.file_path = str(dest)
    document.file_size = len(data)
    await session.flush()

    # Never unlink outside the upload tree: a stored path can point at a sibling
    # root that another module owns, and this seeder does not get to delete it.
    try:
        old.relative_to(shared_dir.parent)
    except ValueError:
        return True
    survivor = (await session.execute(select(Document.id).where(Document.file_path == str(old)).limit(1))).first()
    if survivor is None:
        old.unlink(missing_ok=True)
    return True


async def _attach_documents(
    session: AsyncSession,
    pid: uuid.UUID,
    owner: str,
    documents: list[dict[str, Any]],
    bundle_key: str,
) -> int:
    """Materialize a bundle's ``documents`` list as real bytes + Document rows.

    Each entry is written to disk and a Document row points at the absolute
    path, so the Documents screen offers genuine HTTP-200 downloads (no
    byte-less stubs). Each entry is isolated: a missing or unreadable source
    skips THAT entry only and never aborts the rest of the install. Idempotent
    on a deterministic doc id. Returns the number of documents present afterwards.

    The bytes go to the install-wide content-addressed store rather than to a
    folder per project, because every demo project is handed the same native
    CAD sources and a per-project copy stored the same model once per project.
    Rows from different projects therefore share a file, which is why deleting
    a document keeps a blob another row still points at (see
    ``DocumentService.delete_document``).

    Idempotency is checked against the disk as well as the database: a row
    whose file has gone is repaired rather than skipped, so a run interrupted
    between the write and the commit heals on the next one instead of leaving
    a permanent 404 behind a row that looks finished. A row whose file is fine
    but still sits in a per-project folder is moved into the store, so an
    install that predates it reclaims the space on its next seed rather than
    only on a data directory that starts empty.
    """
    from app.modules.documents.models import Document
    from app.modules.documents.service import UPLOAD_BASE  # type: ignore

    samples_base = _samples_base()
    shared = Path(UPLOAD_BASE) / _SHARED_BLOB_DIRNAME
    docs_written = 0
    for entry in documents:
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
            if existing_doc is not None and _blob_present(existing_doc.file_path):
                await _adopt_into_shared_store(session, existing_doc, shared)
                docs_written += 1
                continue

            # The blob is written before the row is added or repaired, so an
            # interrupted install can leave a file nothing points at, never a
            # row pointing at a file that is not there.
            data = source_path.read_bytes()
            dest = _materialize_blob(shared, data, name)
            if existing_doc is not None:
                # The row outlived its bytes: an earlier run died between the
                # two, or the uploads folder was cleaned underneath it. Point
                # it back at real content instead of leaving a download that
                # answers 404 forever.
                existing_doc.file_path = str(dest)
                existing_doc.file_size = len(data)
            else:
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
    return docs_written


def _load_retail_spec() -> dict | None:
    """Read the procedural Retail Market Heilbronn canonical spec, or None."""
    if not RETAIL_SPEC_PATH.exists():
        return None
    try:
        return json.loads(RETAIL_SPEC_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt spec must not break installs
        logger.warning("seed_demo_assets: failed to read retail Heilbronn spec", exc_info=True)
        return None


async def _attach_retail_procedural_model(
    session: AsyncSession,
    pid: uuid.UUID,
    spec: dict,
) -> tuple[uuid.UUID | None, dict[str, uuid.UUID], bool]:
    """Attach the procedural Heilbronn BIM model (one IFC model + GLB geometry).

    Mirrors :func:`_attach_one_bim_model` but reads the model from the procedural
    spec and persists each element's canonical ``classification`` and
    ``geometry`` into ``properties``/``metadata`` so the BIM hub keeps the DIN
    276 mapping and the box geometry. Idempotent on a deterministic model id.
    Returns ``(model_id, {stable_id: element_uuid}, geometry_present)``.
    """
    from app.modules.bim_hub.file_storage import save_geometry
    from app.modules.bim_hub.models import BIMElement, BIMModel

    models = spec.get("models", [])
    if not models:
        return None, {}, False
    src = models[0]

    mid = _u(str(pid), "bim", "retail_procedural")
    if await session.get(BIMModel, mid) is not None:
        await _ensure_bim_artifacts(session, pid, mid)  # backfill on re-seed
        return mid, {}, True  # already attached on a previous run

    canonical_key: str | None = None
    if RETAIL_GLB_PATH.exists():
        content = gzip.decompress(RETAIL_GLB_PATH.read_bytes())
        canonical_key = await save_geometry(pid, mid, ".glb", content)

    session.add(
        BIMModel(
            id=mid,
            project_id=pid,
            name=src.get("name", "Procedural model"),
            discipline=src.get("discipline"),
            model_format=src.get("model_format", "ifc"),
            version="1",
            status="ready" if canonical_key else "needs_converter",
            element_count=src.get("element_count", len(src.get("elements", []))),
            storey_count=src.get("storey_count", 1),
            canonical_file_path=canonical_key,
            metadata_={
                "geometry_quality": src.get("geometry_quality", "procedural"),
                "geometry_type": "procedural" if canonical_key else "none",
                "converter_source": "procedural",
                "source": "retail_heilbronn_seed",
            },
        )
    )
    await session.flush()

    elem_uuid: dict[str, uuid.UUID] = {}
    for e in src.get("elements", []):
        sid = e["stable_id"]
        eu = _u(str(mid), "el", sid)
        elem_uuid[sid] = eu
        props = dict(e.get("props") or {})
        if e.get("classification"):
            props["classification"] = e["classification"]
        if e.get("geometry"):
            props["geometry"] = e["geometry"]
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
                properties=props,
                bounding_box=e.get("bounding_box"),
                metadata_={"source": "retail_heilbronn_seed"},
            )
        )
    await session.flush()
    await _ensure_bim_artifacts(session, pid, mid)
    return mid, elem_uuid, bool(canonical_key)


async def _attach_retail_heilbronn(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: str | uuid.UUID,
    bundle_key: str,
) -> dict:
    """Attach the procedural Retail Market Heilbronn model, links and documents.

    This showcase ships its OWN procedural model (not the shared flagship mesh):
    one IFC-format BIM model whose 232 canonical elements and ``.glb`` geometry
    are generated from the building's canonical geometry. A handful of leaf BOQ
    positions in the structural / facade / refrigeration groups (KG 320/330/360/
    470) are linked to real elements, and the reference PDFs are attached. Fully
    idempotent and resilient.
    """
    bundle = BUNDLES.get(bundle_key)
    if bundle is None:
        return {"status": "skipped", "reason": f"unknown bundle {bundle_key}"}
    spec = _load_retail_spec()
    if not spec:
        return {"status": "skipped", "reason": "no retail Heilbronn assets"}

    pid = project_id
    owner = str(owner_id)

    model_id, elem_uuid, geom = await _attach_retail_procedural_model(session, pid, spec)

    # Pool element ids from the bundle's link groups, in order.
    groups = spec.get("groups", {})
    src_model_id = str(spec["models"][0]["id"]) if spec.get("models") else None
    pooled_elem_ids: list[uuid.UUID] = []
    if model_id is not None and src_model_id is not None:
        for gk in bundle.get("link_groups", []):
            grp = groups.get(gk)
            if not grp or grp.get("model_id") != src_model_id:
                continue
            for sid in grp.get("stable_ids", []):
                eu = elem_uuid.get(sid)
                if eu is not None:
                    pooled_elem_ids.append(eu)

    n_links = await _link_positions_to_pool(session, pid, pooled_elem_ids, bundle_key)
    docs_written = await _attach_documents(session, pid, owner, bundle.get("documents", []), bundle_key)

    result = {
        "status": "ok",
        "project_id": str(pid),
        "bim_models": 1 if model_id else 0,
        "primary_model_id": str(model_id) if model_id else None,
        "dwg": False,
        "elements": len(elem_uuid),
        "links": n_links,
        "geometry": geom,
        "documents": docs_written,
        "bundle": bundle_key,
    }
    logger.info("Retail Heilbronn assets attached: %s", result)
    return result


async def _attach_demo_assets_inner(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: str | uuid.UUID,
    bundle_key: str,
) -> dict:
    # The Retail Market Heilbronn showcase ships its own procedural model.
    if bundle_key == "retail_heilbronn":
        return await _attach_retail_heilbronn(session, project_id, owner_id, bundle_key)

    bundle = BUNDLES.get(bundle_key)
    if bundle is None:
        return {"status": "skipped", "reason": f"unknown bundle {bundle_key}"}

    spec = _load_spec()
    if not spec:
        return {"status": "skipped", "reason": "no flagship assets"}

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

    n_links = await _link_positions_to_pool(session, pid, pooled_elem_ids, bundle_key)

    # ── 4. Real downloadable documents (best-effort, per entry) ──────────
    docs_written = await _attach_documents(session, pid, owner, bundle.get("documents", []), bundle_key)

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
