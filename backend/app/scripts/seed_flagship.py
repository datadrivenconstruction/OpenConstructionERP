# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Install the flagship "Residential House" reference project.

Unlike the SQLite-only showcase snapshot, this installer is ORM-based and
therefore dialect-agnostic (works on the embedded-PostgreSQL default AND on
SQLite). It restores a real CAD-to-BOQ project from committed assets:

    app/scripts/flagship_assets/flagship.json        spec (built by _bake_flagship.py)
    app/scripts/flagship_assets/geometry_{ifc,rvt}.dae.gz   real DDC geometry
    app/scripts/flagship_assets/house_plans.pdf      reference plan set

It creates: the project (+ WGS84 geo anchor so it shows on the map), the IFC
and RVT BIM 3D models with their real converted elements and geometry, a DWG
drawing entry in the dedicated DWG Takeoff module (never the BIM 3D Hub, since
a 2D drawing has no mesh), a costed BOQ whose positions carry real CWICR rates +
material/labour/equipment resource breakdowns, BIM<->BOQ links for every
element in each priced group (bidirectional navigation), project resources,
and the PDF plan set.

All ids are derived deterministically so re-running is idempotent and a later
showcase export references the same rows.
"""

from __future__ import annotations

import gzip
import json
import logging
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent / "flagship_assets"
SPEC_PATH = ASSETS / "flagship.json"
_NS = uuid.UUID("f1a95eed-0000-4000-8000-000000000000")
FLAGSHIP_DEMO_ID = "flagship-house"


def _u(*parts: str) -> uuid.UUID:
    return uuid.uuid5(_NS, ":".join(parts))


def _money(x: Any) -> str:
    try:
        return str(Decimal(str(x)).quantize(Decimal("0.01")))
    except Exception:  # noqa: BLE001
        return "0.00"


def _dec(x: Any) -> Decimal:
    try:
        d = Decimal(str(x))
    except Exception:  # noqa: BLE001
        return Decimal("0")
    if not d.is_finite():
        return Decimal("0")
    return d


# Founder principle: "Все позиции мы делаем с ресурсами" - every BOQ position
# must carry a resource buildup. The flagship positions ship raw CWICR
# components in flagship.json, but those sum to whatever the source catalogue
# row cost, not to the position's converted unit_rate. The BOQ resource
# contract (boq/service.py) treats every leaf's ``unit_rate`` as a PER-UNIT
# norm and re-derives the position rate as Sum(leaf.quantity * leaf.unit_rate);
# for that to stay consistent the buildup must sum EXACTLY to the position
# unit_rate. So we keep the real component names/codes/types but scale every
# leaf by one deterministic factor so the buildup sums to the unit_rate, and
# we flag the scaling transparently (never silently authoritative).
_RES_TYPES = ("material", "labor", "equipment")


def _normalize_type(raw: Any) -> str:
    t = str(raw or "").strip().lower()
    if t in _RES_TYPES:
        return t
    if t in ("plant", "machine", "equip"):
        return "equipment"
    if t in ("worker", "crew", "operator"):
        return "labor"
    return "material"


def _build_resource_leaves(raw_resources: list[dict], unit_rate: Decimal) -> list[dict[str, Any]]:
    """Return per-unit resource leaves that sum EXACTLY to ``unit_rate``.

    Preserves the real CWICR component detail (name, code, type, unit) and its
    natural material/labour/equipment proportions, but rescales every leaf so
    Sum(quantity * unit_rate) == unit_rate, satisfying the BOQ resource
    contract. When the source carries no usable components, falls back to a
    transparent labour/material split that still sums to the rate so no
    flagship position is ever stored without a buildup.
    """
    rate = _dec(unit_rate)
    if rate <= 0:
        return []

    leaves: list[dict[str, Any]] = []
    src_subtotal = Decimal("0")
    for r in raw_resources or []:
        if not isinstance(r, dict):
            continue
        qty = _dec(r.get("quantity"))
        leaf_rate = _dec(r.get("unit_rate"))
        sub = qty * leaf_rate
        if sub <= 0:
            continue
        src_subtotal += sub
        leaves.append(
            {
                "name": str(r.get("name") or "Component"),
                "code": str(r.get("code") or ""),
                "type": _normalize_type(r.get("type")),
                "unit": str(r.get("unit") or ""),
                "quantity": float(qty),
                "unit_rate": leaf_rate,  # Decimal for now; scaled + stringified below
            }
        )

    if not leaves or src_subtotal <= 0:
        # Transparent fallback: labour 35% / material 65% of the unit rate,
        # one leaf each (quantity 1), summing exactly to the rate. Flagged
        # ``estimated`` so the split is never read as catalogue-grounded.
        out: list[dict[str, Any]] = []
        mat = (rate * Decimal("0.65")).quantize(Decimal("0.01"))
        lab = rate - mat  # remainder keeps the pair penny-exact
        for rtype, share_rate in (("labor", lab), ("material", mat)):
            out.append(
                {
                    "name": f"{rtype.capitalize()} allowance",
                    "code": "",
                    "type": rtype,
                    "unit": "ls",
                    "quantity": 1.0,
                    "unit_rate": _money(share_rate),
                    "estimated": True,
                }
            )
        return out

    # Scale every leaf rate by one factor so the buildup sums to the unit rate,
    # preserving each component's relative weight. ``quantity`` stays the real
    # component quantity; the scale folds into the per-unit ``unit_rate``. Round
    # each leaf's CONTRIBUTION (quantity * rate) to cents and absorb the residual
    # into the largest leaf's rate (un-rounded) so the buildup is penny-exact and
    # Sum(quantity * unit_rate) == unit_rate holds without float drift.
    factor = rate / src_subtotal
    booked = Decimal("0")
    biggest_idx = 0
    biggest_sub = Decimal("-1")
    for i, leaf in enumerate(leaves):
        q = _dec(leaf["quantity"])
        sub = (q * leaf["unit_rate"] * factor).quantize(Decimal("0.01"))
        leaf["_sub"] = sub
        leaf["scaled_to_rate"] = True
        booked += sub
        if sub > biggest_sub:
            biggest_sub = sub
            biggest_idx = i
    # Push the rounding residual onto the largest leaf's contribution.
    leaves[biggest_idx]["_sub"] += rate - booked
    # Derive each leaf's per-unit rate from its (now exact) contribution.
    for leaf in leaves:
        q = _dec(leaf["quantity"])
        if q > 0:
            leaf["unit_rate"] = format(leaf["_sub"] / q, "f")
        else:
            # Degenerate zero-quantity component: carry the money as a 1-unit
            # leaf so its contribution still counts toward the rate.
            leaf["quantity"] = 1.0
            leaf["unit_rate"] = _money(leaf["_sub"])
        leaf.pop("_sub", None)
    return leaves


def _resource_rollup(resources: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Roll resource leaves up to a per-type ``{total, pct}`` map for the
    material / labour / equipment badge on the BOQ, mirroring the assembly and
    ai-estimator apply paths so the flagship renders the same M/L/E split.
    """
    totals: dict[str, Decimal] = {}
    for r in resources:
        if not isinstance(r, dict):
            continue
        rtype = _normalize_type(r.get("type"))
        sub = _dec(r.get("quantity")) * _dec(r.get("unit_rate"))
        totals[rtype] = totals.get(rtype, Decimal("0")) + sub
    subtotal = sum(totals.values(), Decimal("0"))
    out: dict[str, dict[str, float]] = {}
    if subtotal > 0:
        for rtype, ttl in totals.items():
            out[rtype] = {"total": float(ttl), "pct": float((ttl / subtotal) * Decimal("100"))}
    return out


def _spec() -> dict | None:
    if not SPEC_PATH.exists():
        return None
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


async def _purge(session: AsyncSession, pid: uuid.UUID) -> None:
    """Remove a prior flagship install so a forced re-seed is clean.

    BIMModel/BIMElement and BOQElementLink carry bare FK columns with no DB
    ``ondelete`` cascade, so deleting the Project alone would orphan them and a
    deterministic-id re-insert would then PK-collide. Delete those rows
    explicitly (links -> elements -> models) before the cascading project delete.
    """
    from app.modules.bim_hub.models import BIMElement, BIMModel, BOQElementLink
    from app.modules.boq.models import BOQ, Position
    from app.modules.dwg_takeoff.models import DwgDrawing
    from app.modules.projects.models import Project
    from app.modules.resources.models import Resource

    model_ids = list((await session.execute(select(BIMModel.id).where(BIMModel.project_id == pid))).scalars().all())
    boq_ids = list((await session.execute(select(BOQ.id).where(BOQ.project_id == pid))).scalars().all())
    pos_ids: list[uuid.UUID] = []
    if boq_ids:
        pos_ids = list((await session.execute(select(Position.id).where(Position.boq_id.in_(boq_ids)))).scalars().all())
    if pos_ids:
        await session.execute(delete(BOQElementLink).where(BOQElementLink.boq_position_id.in_(pos_ids)))
    if model_ids:
        await session.execute(delete(BIMElement).where(BIMElement.model_id.in_(model_ids)))
        await session.execute(delete(BIMModel).where(BIMModel.id.in_(model_ids)))
    # DWG Takeoff drawings cascade on the project delete below, but a prior
    # install may have seeded the flagship DWG as a BIM model under the same
    # deterministic id; the BIMModel delete above already cleared that. Drop
    # any DWG drawing rows explicitly too so a forced re-seed never PK-collides.
    await session.execute(delete(DwgDrawing).where(DwgDrawing.project_id == pid))
    # Resources FK is ON DELETE SET NULL, so drop them explicitly.
    await session.execute(delete(Resource).where(Resource.home_project_id == pid))
    proj = await session.get(Project, pid)
    if proj is not None:
        await session.delete(proj)  # cascades BOQ (-> positions), GeoAnchor, Document
    await session.flush()


def _flagship_template(spec: dict) -> Any:
    """Build a minimal ``DemoTemplate`` for the flagship so the shared module
    seeders (``_seed_module_data`` -> ``_generate_module_data``) can populate
    its operational modules (RFIs, change orders, daily diary, safety, NCRs,
    compliance, procurement, risks, tendering, meetings, submittals, ...).

    The generators read only a handful of template fields: ``sections`` (to
    derive trades + representative item titles), ``tender_companies`` (firms),
    ``address`` (country code), ``project_name``, ``currency``,
    ``total_months`` and ``project_metadata``. We map those off the baked spec
    so the derived data cites the flagship's real trades and addresses.
    """
    from app.core.demo_projects import DemoTemplate  # local import: avoid cycle

    pj = spec["project"]
    addr = pj.get("address") or {}
    template_addr = {
        "street": addr.get("line1", ""),
        "city": addr.get("city", ""),
        "postcode": addr.get("postcode", ""),
        "country": addr.get("country", ""),
        "lat": addr.get("lat"),
        "lng": addr.get("lng"),
    }

    # Map BOQ sections -> SectionDef tuples
    # (code, title, classification, [ (ordinal, desc, unit, qty, rate, class) ]).
    sections: list[tuple] = []
    for sec in spec["boq"]["sections"]:
        items: list[tuple] = []
        for p in sec.get("positions", []):
            items.append(
                (
                    p.get("ordinal", ""),
                    p.get("description", ""),
                    p.get("unit", "ea"),
                    float(_dec(p.get("quantity", 0))),
                    float(_dec(p.get("unit_rate", 0))),
                    p.get("classification", {}),
                )
            )
        sections.append((sec.get("ordinal", ""), sec.get("title", ""), sec.get("classification", {}), items))

    # A couple of plausible bidders so the tendering module and the firm-derived
    # records (subcontract RFIs, NCRs, submittals) have companies to cite.
    tender_companies = [
        ("Summit Residential Builders", "estimating@summitresidential.example", 1.00),
        ("Front Range Construction", "bids@frontrangeconstruction.example", 1.04),
        ("Mile High General Contractors", "tenders@milehighgc.example", 0.97),
    ]

    return DemoTemplate(
        demo_id=FLAGSHIP_DEMO_ID,
        project_name=pj.get("name", "Residential House - Reference Build"),
        project_description=pj.get("description", ""),
        region="United States",
        classification_standard="masterformat",
        currency=pj.get("currency", "USD"),
        locale="en",
        validation_rule_sets=["masterformat", "boq_quality"],
        boq_name=spec["boq"].get("name", "Construction Estimate"),
        boq_description=spec["boq"].get("description", ""),
        boq_metadata={},
        sections=sections,
        markups=[],
        total_months=9,
        tender_name="Residential House - Main Works",
        tender_companies=tender_companies,
        project_metadata={
            "client": "Riverside Drive Holdings",
            "architect": "Denver Design Studio",
            "structural_engineer": "Rocky Mountain Structures",
            "main_contractor": "Summit Residential Builders",
        },
        address=template_addr,
    )


async def _seed_flagship_modules(
    session: AsyncSession,
    pid: uuid.UUID,
    owner: uuid.UUID,
    spec: dict,
) -> dict:
    """Populate the flagship's per-project operational modules.

    Reuses the shared demo seeders so the flagship hub (RFIs, change orders,
    daily diary, safety, NCRs, compliance, procurement, risks, tendering, ...)
    arrives populated like every showcase project. Fully resilient and
    idempotent: it skips when the flagship already has RFIs (a representative
    module) so a non-forced re-run never duplicates rows, and any failure is
    swallowed so a missing/disabled module never aborts the flagship install.
    """
    try:
        from app.core.demo_projects import _seed_module_data
        from app.modules.rfi.models import RFI
    except Exception:  # noqa: BLE001 - module set unavailable; skip decoration
        logger.debug("flagship: shared module seeders unavailable, skipping", exc_info=True)
        return {"status": "skipped", "reason": "seeders unavailable"}

    # Idempotency guard: if the flagship already carries RFIs, the modules were
    # seeded on a prior run. Re-seeding would duplicate (rows use random ids),
    # so skip. A forced re-seed (_purge) does not clear these decoration rows,
    # so this guard also prevents force-reseed duplication.
    try:
        existing = (
            await session.execute(select(RFI.id).where(RFI.project_id == pid).limit(1))
        ).scalar_one_or_none()
        if existing is not None:
            return {"status": "already", "reason": "modules present"}
    except Exception:  # noqa: BLE001 - table may not exist; fall through to seed
        logger.debug("flagship: RFI presence check failed, attempting seed", exc_info=True)

    try:
        template = _flagship_template(spec)
        result = await _seed_module_data(session, pid, owner, FLAGSHIP_DEMO_ID, template)
        await session.flush()
        return {"status": "ok", "modules": result}
    except Exception:  # noqa: BLE001 - never break the flagship install
        logger.warning("flagship: operational module seeding failed (non-fatal)", exc_info=True)
        return {"status": "error"}


async def install_flagship(
    session: AsyncSession,
    owner_id: str | uuid.UUID,
    *,
    force: bool = False,
) -> dict:
    """Create the flagship project from baked assets. Idempotent."""
    spec = _spec()
    if not spec:
        return {"status": "skipped", "reason": "no flagship assets"}

    from app.modules.bim_hub.file_storage import save_geometry
    from app.modules.bim_hub.models import BIMElement, BIMModel, BOQElementLink, is_non_3d_format
    from app.modules.boq.models import BOQ, Position
    from app.modules.documents.models import Document
    from app.modules.dwg_takeoff.models import DwgDrawing
    from app.modules.geo_hub.models import GeoAnchor
    from app.modules.projects.models import Project
    from app.modules.resources.models import Resource

    owner = uuid.UUID(str(owner_id))
    pj = spec["project"]
    pid = uuid.UUID(pj["id"])

    existing = await session.get(Project, pid)
    if existing is not None and not force:
        return {"status": "already", "project_id": str(pid)}
    if existing is not None and force:
        await _purge(session, pid)

    # ── project + geo anchor ────────────────────────────────────────────
    addr = pj.get("address") or {}
    session.add(
        Project(
            id=pid,
            name=pj["name"],
            description=pj["description"],
            region="US",
            classification_standard="masterformat",
            currency=pj.get("currency", "USD"),
            locale="en",
            status=pj.get("status", "active"),
            owner_id=owner,
            address=addr,
            metadata_=pj.get("metadata", {}),
        )
    )
    # Flush the project before any FK child (geo anchor, BIM models, …). The
    # children are linked by bare FK columns with no ORM relationship(), so
    # SQLAlchemy's unit-of-work cannot infer insert ordering by itself and
    # would otherwise try to insert a child before its parent row exists.
    await session.flush()
    if addr.get("lat") is not None and addr.get("lng") is not None:
        session.add(
            GeoAnchor(
                project_id=pid,
                lat=Decimal(str(addr["lat"])),
                lon=Decimal(str(addr["lng"])),
                epsg_code=4326,
                region_code=addr.get("country_code") and f"{addr['country_code']}-CO" or None,
                address=", ".join(str(addr[k]) for k in ("city", "region", "country") if addr.get(k)),
                metadata_={"source": "flagship_seed"},
            )
        )

    # ── BIM models + elements + geometry ────────────────────────────────
    # Only true 3D formats (IFC, RVT, ...) become BIM 3D models. 2D drawing
    # formats (DWG/DXF/DGN) belong to the dedicated DWG Takeoff module: they
    # carry no 3D mesh, so seeding them as ready BIM models made the 3D viewer
    # request geometry that can never exist and fire the "marked ready but its
    # 3D geometry file is no longer on the server" 404 on a fresh install.
    elem_uuid: dict[tuple[str, str], uuid.UUID] = {}
    model_count = 0
    elem_count = 0
    dwg_count = 0
    for m in spec["models"]:
        mid = uuid.UUID(m["id"])

        # Route 2D drawings to the DWG Takeoff module, never the BIM 3D Hub.
        if is_non_3d_format(m.get("model_format")):
            fmt = (m.get("model_format") or "dwg").lower().lstrip(".")
            session.add(
                DwgDrawing(
                    id=mid,
                    project_id=pid,
                    name=m["name"],
                    filename=f"{m['name']}.{fmt}",
                    file_format=fmt,
                    # No source file ships with the flagship assets - this is a
                    # metadata-only reference row so the DWG Takeoff module
                    # lists the drawing. Status "uploaded" (not "ready") keeps
                    # the UI honest: there are no parsed entities to render yet.
                    file_path="",
                    size_bytes=0,
                    status="uploaded",
                    discipline=m.get("discipline"),
                    created_by=str(owner),
                    metadata_={
                        "source": "flagship_seed",
                        "seed_reference_only": True,
                        "element_count": m.get("element_count", 0),
                    },
                )
            )
            dwg_count += 1
            await session.flush()
            continue

        canonical_key: str | None = None
        if m.get("geometry_asset"):
            gpath = ASSETS / m["geometry_asset"]
            if gpath.exists():
                content = gzip.decompress(gpath.read_bytes())
                canonical_key = await save_geometry(pid, mid, ".dae", content)
        # Status must match what is actually on storage. Only a model whose
        # geometry blob was written can be "ready" - the geometry endpoint
        # treats a "ready" model with no blob as a data-loss error and
        # returns the alarming `geometry_missing` 404 ("marked ready but its
        # 3D geometry file is no longer on the server"). A 3D model with no
        # bundled mesh is marked "needs_converter" so the same endpoint
        # returns the honest `geometry_absent` state ("no 3D geometry: the
        # converter for its format is not available") instead of pretending
        # geometry was lost. The BOQ "Linked Geometry" preview reads the same
        # endpoint and so becomes honest too.
        model_status = "ready" if canonical_key else "needs_converter"
        session.add(
            BIMModel(
                id=mid,
                project_id=pid,
                name=m["name"],
                discipline=m.get("discipline"),
                model_format=m["model_format"],
                version="1",
                status=model_status,
                element_count=m.get("element_count", 0),
                storey_count=m.get("storey_count", 0),
                canonical_file_path=canonical_key,
                metadata_={
                    "geometry_quality": m.get("geometry_quality", "real"),
                    "geometry_type": "real" if canonical_key else "none",
                    "converter_source": "ddc-community",
                    "source": "flagship_seed",
                },
            )
        )
        model_count += 1
        await session.flush()  # model row must exist before its elements (FK)
        for e in m["elements"]:
            eu = _u(m["id"], "el", e["stable_id"])
            elem_uuid[(m["id"], e["stable_id"])] = eu
            session.add(
                BIMElement(
                    id=eu,
                    model_id=mid,
                    stable_id=e["stable_id"],
                    element_type=e.get("element_type"),
                    name=e.get("name"),
                    storey=e.get("storey"),
                    discipline=e.get("discipline"),
                    quantities=e.get("quantities") or {},
                    properties=e.get("props") or {},
                    geometry_hash=e.get("geometry_hash"),
                    bounding_box=e.get("bounding_box"),
                    mesh_ref=e.get("mesh_ref"),
                    metadata_={"source": "flagship_seed"},
                )
            )
            elem_count += 1

    await session.flush()

    # ── BOQ + sections + positions ──────────────────────────────────────
    boq = spec["boq"]
    bid = uuid.UUID(boq["id"])
    session.add(BOQ(id=bid, project_id=pid, name=boq["name"], description=boq["description"], status="draft"))
    sort = 0
    pos_links: list[tuple[uuid.UUID, list[str]]] = []
    npos = 0
    npos_res = 0
    for sec in boq["sections"]:
        sec_id = _u(boq["id"], "sec", sec["ordinal"])
        session.add(
            Position(
                id=sec_id,
                boq_id=bid,
                parent_id=None,
                ordinal=sec["ordinal"],
                description=sec["title"],
                unit="",
                quantity="0",
                unit_rate="0",
                total="0",
                classification=sec.get("classification", {}),
                source="cad_import",
                cad_element_ids=[],
                validation_status="valid",
                sort_order=sort,
            )
        )
        sort += 1
        for p in sec["positions"]:
            pid_pos = _u(boq["id"], "pos", p["ordinal"])
            el_ids: list[str] = []
            for gk in p.get("link_groups", []):
                grp = spec["groups"].get(gk)
                if not grp:
                    continue
                for sid in grp["stable_ids"]:
                    eu = elem_uuid.get((grp["model_id"], sid))
                    if eu:
                        el_ids.append(str(eu))
            # Founder principle: every position carries a resource buildup.
            # Re-shape the raw CWICR components into per-unit leaves that sum
            # exactly to the unit_rate (the BOQ resource contract), and roll
            # them up to the M/L/E badge map - same shape the assembly and
            # ai-estimator apply paths write.
            unit_rate_dec = _dec(p.get("unit_rate", 0))
            res_leaves = _build_resource_leaves(p.get("resources", []), unit_rate_dec)
            res_breakdown = _resource_rollup(res_leaves)
            npos_res += 1 if res_leaves else 0
            session.add(
                Position(
                    id=pid_pos,
                    boq_id=bid,
                    parent_id=sec_id,
                    ordinal=p["ordinal"],
                    description=p["description"],
                    unit=p.get("unit", "ea"),
                    quantity=str(p.get("quantity", 0)),
                    unit_rate=_money(p.get("unit_rate", 0)),
                    total=_money(Decimal(str(p.get("quantity", 0))) * Decimal(str(p.get("unit_rate", 0)))),
                    classification=p.get("classification", {}),
                    source="cad_import",
                    # confidence stays NULL: CAD->BOQ linkage here is deterministic,
                    # not an AI prediction. The numeric confidence field would
                    # otherwise read back as 0.0 (a string label can't be parsed).
                    confidence=None,
                    cad_element_ids=el_ids,
                    validation_status="valid",
                    cost_code_id=str(p.get("cwicr_item_id") or "")[:36] or None,
                    reference_code=p.get("cwicr_code"),
                    metadata_={
                        "cost_item_id": p.get("cwicr_item_id"),
                        "cwicr_code": p.get("cwicr_code"),
                        "cwicr_description": p.get("cwicr_description"),
                        "resources": res_leaves,
                        "resource_breakdown": res_breakdown,
                        # Keep the unscaled source components for provenance so a
                        # reviewer can see the original CWICR cost driver detail.
                        "resources_source": p.get("resources", []),
                        "source": "cad_import",
                        "linked_groups": p.get("link_groups", []),
                    },
                    sort_order=sort,
                )
            )
            sort += 1
            npos += 1
            pos_links.append((pid_pos, p.get("link_groups", [])))
    await session.flush()

    # ── BIM <-> BOQ links (bidirectional navigation) ────────────────────
    nlinks = 0
    for pid_pos, groups in pos_links:
        for gk in groups:
            grp = spec["groups"].get(gk)
            if not grp:
                continue
            for sid in grp["stable_ids"]:
                eu = elem_uuid.get((grp["model_id"], sid))
                if not eu:
                    continue
                session.add(
                    BOQElementLink(
                        boq_position_id=pid_pos,
                        bim_element_id=eu,
                        link_type="auto_matched",
                        confidence="high",
                        rule_id="flagship_seed",
                        metadata_={"group": gk},
                    )
                )
                nlinks += 1

    # ── project resources (real Resource rows) ──────────────────────────
    for r in spec.get("resources", []):
        session.add(
            Resource(
                id=_u("res", r["code"]),
                code=r["code"],
                name=r["name"],
                resource_type=r.get("resource_type", "person"),
                home_project_id=pid,
                default_cost_rate=Decimal(str(r.get("default_cost_rate", "0"))),
                currency=r.get("currency", "USD"),
                status="active",
                metadata_={"demo_id": FLAGSHIP_DEMO_ID, "project_id": str(pid)},
            )
        )

    # ── PDF plan set (best-effort) ──────────────────────────────────────
    doc = spec.get("document")
    if doc:
        try:
            asset = ASSETS / doc["asset"]
            if asset.exists():
                from app.modules.documents.service import UPLOAD_BASE  # type: ignore

                up = Path(UPLOAD_BASE) / str(pid)
                up.mkdir(parents=True, exist_ok=True)
                fname = f"{uuid.uuid4().hex[:12]}_{doc['filename']}"
                dest = up / fname
                data = asset.read_bytes()
                dest.write_bytes(data)
                session.add(
                    Document(
                        id=_u("doc", doc["filename"]),
                        project_id=pid,
                        name=doc["filename"],
                        description=doc.get("title", ""),
                        category="drawing",
                        file_size=len(data),
                        mime_type="application/pdf",
                        file_path=str(dest),
                        uploaded_by=str(owner),
                        metadata_={"source": "flagship_seed"},
                    )
                )
        except Exception:  # noqa: BLE001 - PDF is non-critical
            logger.warning("flagship: PDF attach skipped", exc_info=True)

    # ── operational modules (RFIs, change orders, daily diary, safety, ...) ─
    # Make the flagship hub as rich as the showcase projects. Wrapped so a
    # failure never breaks the core install; flushed (not committed) so it
    # lands in the single transaction below.
    modules_result = await _seed_flagship_modules(session, pid, owner, spec)

    await session.commit()
    result = {
        "status": "ok",
        "project_id": str(pid),
        "models": model_count,
        "elements": elem_count,
        "dwg_drawings": dwg_count,
        "positions": npos,
        "positions_with_resources": npos_res,
        "links": nlinks,
        "resources": len(spec.get("resources", [])),
        "modules": modules_result,
    }
    logger.info("Flagship installed: %s", result)
    return result
