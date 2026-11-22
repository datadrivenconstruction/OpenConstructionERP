# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo design for the demo estate, run by ``app.core.demo_enrichment`` (step ``design``).

Every demo project gets what a design lead writes in the first week: a brief cut from the
project's own record (use, storeys, basements, floor area, address, currency) and confirmed by
the demo owner, so the in-browser preview builds a model from it. Where the project holds a
converter-imported BIM model, that model joins the chain as revision 1 through the same
``imported.wrap`` the R16 endpoint uses, and where the country ships a starter rule set for the
brief's use the design estimate is installed and run on it.

Only projects carrying the demo marker are touched. Each part guards itself (a brief, a revision,
an estimate already there is left alone), so a re-run never duplicates and finishes a project a
failed run left half done. Re-run only this step on a database: ``python -m app.modules.design.seed``.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .model_params import APARTMENT_FRONTAGE, APARTMENTS_TOP, TYPOLOGY

logger = logging.getLogger(__name__)

DEPTH_LEVEL = "D2"
_RECORD_NOTE = "Taken from the project record"
_DERIVED_NOTE = "Derived from the floor area and storeys of the project record"

# use category -> generator template the in-browser engine builds (model_params.TYPOLOGY)
_TEMPLATE = {
    "residential_single": "house",
    "residential_multi": "apartment_section",
    "hotel": "apartment_section",
    "office": "office",
    "school": "school",
    "kindergarten": "school",
}
# storeys when the record names none, and a typical floor plate (m2) when it names no area
_DEFAULT_FLOORS = {
    "residential_single": 2,
    "residential_multi": 6,
    "hotel": 8,
    "office": 8,
    "mixed_use": 10,
    "school": 3,
    "kindergarten": 2,
    "healthcare": 5,
    "retail": 1,
    "warehouse": 1,
    "industrial": 1,
    "infrastructure": 1,
}
_DEFAULT_PLATE = {
    "residential_single": 140.0,
    "residential_multi": 750.0,
    "hotel": 900.0,
    "school": 1500.0,
    "kindergarten": 800.0,
    "retail": 2500.0,
    "warehouse": 10000.0,
    "industrial": 5000.0,
    "infrastructure": 300.0,
}
_FLOOR_HEIGHT = {"retail": 4.5, "warehouse": 6.0, "industrial": 6.0, "healthcare": 4.0}
# keyword -> use category, first hit wins; read over demo id, building type and name
_USE_WORDS = (
    (("kindergarten", "kita", "nursery"), "kindergarten"),
    (("school", "école", "ecole", "pupil", "classroom"), "school"),
    (("medical", "hospital", "clinic", "health"), "healthcare"),
    (("warehouse", "logistics", "distribution"), "warehouse"),
    (("factory", "plant", "industrial"), "industrial"),
    (("retail", "market", "supermarket", "mall", "shop"), "retail"),
    (("hotel",), "hotel"),
    (("mixed-use", "mixed_use", "mixed use", "uso mixto"), "mixed_use"),
    (("villa", "house", "reference build"), "residential_single"),
    (("residential", "condo", "apartment", "wohn", "dwelling", "housing"), "residential_multi"),
    (("office", "commercial", "govt", "government", "business", "tower"), "office"),
    (("park", "site-development", "landscape", "road", "bridge"), "infrastructure"),
)
_UNIT_WORDS = r"(?:apartments|flats|dwellings|serviced residences|residences|villas|units|homes)"


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and value > 0 else None
    if isinstance(value, str):
        m = re.fullmatch(r"\s*([0-9][0-9 ,]*(?:\.[0-9]+)?)\s*", value)
        if m:
            try:
                v = float(m.group(1).replace(",", "").replace(" ", ""))
            except ValueError:
                return None
            return v if v > 0 else None
    return None


def floors_above(value: Any) -> int | None:
    """Storeys above ground from a number or a phrase such as ``G+5`` or ``ground and 15 upper floors``."""
    n = _num(value)
    if n is not None:
        return int(n)
    if not isinstance(value, str):
        return None
    s = value.lower()
    if m := re.search(r"\bg\s*\+\s*(\d+)", s):
        return int(m.group(1)) + 1
    if m := re.search(r"(\d+)\s+(?:upper|residential|normal|typical)\s+(?:floors|storeys|stories|levels)", s):
        return int(m.group(1)) + (1 if "ground" in s else 0)
    if m := re.search(r"(\d+)\s+(?:(?:storeys|stories|floors|levels)\s+)?above", s):
        return int(m.group(1))
    if m := re.search(r"(\d+)\s*-?\s*(?:storeys|stories|storey|floors)", s):
        return int(m.group(1))
    return None


def floors_below(meta: dict, phrase: Any) -> int:
    for key in ("basement_levels", "basements", "parking_levels"):
        n = _num(meta.get(key))
        if n is not None:
            return min(10, int(n))
    if isinstance(phrase, str):
        s = phrase.lower()
        if m := re.search(r"(\d+)\s+basement", s):
            return min(10, int(m.group(1)))
        if re.search(r"\bone basement", s):
            return 1
    return 0


def use_category(meta: dict, name: str) -> str:
    if meta.get("use_mix"):
        return "mixed_use"
    text = " ".join(str(meta.get(k) or "") for k in ("demo_id", "building_type", "units")) + " " + (name or "")
    text = text.lower()
    if ("office" in text or "business" in text) and "residen" in text:
        return "mixed_use"
    for words, category in _USE_WORDS:
        if any(w in text for w in words):
            return category
    return "other"


def unit_count(meta: dict) -> int | None:
    for key in ("apartments", "flats", "dwellings", "units"):
        v = meta.get(key)
        n = _num(v)
        if n is not None:
            return int(n)
        if isinstance(v, str) and (m := re.search(rf"(\d+)\s+{_UNIT_WORDS}", v.lower())):
            return int(m.group(1))
    return None


def floor_area(meta: dict, project_gfa: Any) -> float | None:
    for key in ("gfa_m2", "gia_m2", "sdp_m2", "area_m2"):
        if (n := _num(meta.get(key))) is not None:
            return n
    if (n := _num(meta.get("gfa_sf"))) is not None:
        return round(n * 0.092903, 1)
    return _num(project_gfa)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _footprint(template: str, plate: float, floors: int, per_floor: int) -> tuple[float, float]:
    """Width and depth (m) of the block the generator builds, inside the ranges it accepts."""
    _, _, band, corridor = TYPOLOGY[template]
    if template == "house":
        depth = 10.0
        width = _clamp(plate / depth, 8.0, 24.0)
    elif template == "apartment_section":
        depth = round(2 * band + corridor, 1)
        # the cap the generator puts on flats per floor grows with the width (model_params.apartments_cap)
        need = APARTMENT_FRONTAGE * math.ceil(per_floor / 2)
        width = _clamp(plate / depth, max(12.0, need), max(120.0, need))
    elif template == "school":
        depth = round(2 * band + corridor, 1)
        width = _clamp(plate / depth, 20.0, 200.0)
    else:
        depth = _clamp(math.sqrt(plate), 12.0, 120.0 if floors == 1 else 60.0)
        width = _clamp(plate / depth, 12.0, 200.0)
    return round(width, 1), round(depth, 1)


def _plot(address: Any, width: float, depth: float) -> dict | None:
    """The block plus a 6 m margin, as a closed counter-clockwise lon/lat ring around the project's point."""
    if not isinstance(address, dict):
        return None
    lat, lng = address.get("lat"), address.get("lng")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lng)) or not -85 < lat < 85:
        return None
    half_w, half_d = (width + 12.0) / 2, (depth + 12.0) / 2
    dlat = half_d / 111_320.0
    dlng = half_w / (111_320.0 * math.cos(math.radians(lat)))
    x0, x1 = round(lng - dlng, 7), round(lng + dlng, 7)
    y0, y1 = round(lat - dlat, 7), round(lat + dlat, 7)
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def _address_line(address: Any) -> str | None:
    if not isinstance(address, dict):
        return None
    parts = [str(address.get(k)).strip() for k in ("street", "line1", "city") if address.get(k)]
    return ", ".join(parts)[:300] or None


def _budget(project: Any, meta: dict) -> float | None:
    for value in (getattr(project, "budget_estimate", None), getattr(project, "contract_value", None)):
        if (n := _num(value)) is not None:
            return n
    b = meta.get("budget")
    return _num(b.get("amount") if isinstance(b, dict) else b)


def _programme(category: str, template: str, count: int, gfa: float | None, meta: dict, plate: float) -> dict:
    out: dict[str, Any] = {}
    if template == "house":
        out["units"] = [
            {
                "name": "House",
                "count": count,
                "area_m2": round(_clamp((gfa or plate * 2) / max(1, count), 90.0, 400.0)),
                "rooms": [
                    {"kind": "living"},
                    {"kind": "kitchen"},
                    {"kind": "bedroom", "count": 3},
                    {"kind": "bath"},
                    {"kind": "hall"},
                ],
            }
        ]
    elif template == "apartment_section":
        out["units"] = [
            {
                "name": "2-bedroom apartment",
                "count": count,
                "area_m2": round(_clamp((gfa or 0) * 0.7 / count, 35.0, 160.0)) if gfa else 72,
                "rooms": [
                    {"kind": "living"},
                    {"kind": "bedroom", "count": 2},
                    {"kind": "kitchen"},
                    {"kind": "bath"},
                    {"kind": "hall"},
                ],
            }
        ]
    spaces: list[dict] = [{"kind": "lobby", "name": "Entrance lobby"}]
    if template == "school":
        pupils = _num(meta.get("pupil_places"))
        n = _num(meta.get("classrooms")) or (math.ceil(pupils / 25) if pupils else 12)
        spaces.append({"kind": "classroom", "count": int(n), "area_m2": 60})
    elif category in ("retail", "mixed_use"):
        spaces.append({"kind": "retail", "name": "Sales floor", "area_m2": round(plate * 0.8)})
    elif category in ("warehouse", "industrial"):
        spaces.append({"kind": "storage", "name": "Hall", "area_m2": round(plate * 0.9)})
    elif category == "healthcare":
        spaces.append({"kind": "ward", "name": "Wards", "count": 4})
    elif template == "office":
        spaces.append({"kind": "office", "name": "Open-plan office", "area_m2": round(plate * 0.75)})
    spaces.append({"kind": "technical", "name": "Plant room"})
    out["spaces"] = spaces
    parking = next((_num(meta.get(k)) for k in ("parking_spaces", "car_spaces") if _num(meta.get(k))), None)
    if parking:
        out["parking_spaces"] = int(parking)
    return out


def brief_for(project: Any) -> tuple[dict, dict[str, str]] | None:
    """The brief body (no ERP-owned keys) and, per value pointer, where it came from; None without a country.

    ``project`` is a ``Project`` row or anything with its attributes (name, country_code, locale,
    currency, address, gross_floor_area, budget_estimate, contract_value, metadata_).
    """
    country = (getattr(project, "country_code", None) or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        return None
    meta = dict(getattr(project, "metadata_", None) or {})
    name = (getattr(project, "name", None) or "").strip()
    locale = (getattr(project, "locale", None) or "en").strip()
    if not re.fullmatch(r"[a-z]{2,3}(-[A-Z]{2})?", locale):
        locale = "en"
    category = use_category(meta, name)
    count_hint = unit_count(meta)
    template = _TEMPLATE.get(category) or ("apartment_section" if category == "mixed_use" and count_hint else "office")
    storeys_raw = next((meta[k] for k in ("storeys", "stories", "storeys_tower") if meta.get(k) is not None), None)
    above_record = floors_above(storeys_raw)
    above = int(_clamp(above_record or _DEFAULT_FLOORS.get(category, 4), 1, TYPOLOGY[template][0]))
    below = floors_below(meta, storeys_raw)
    gfa = floor_area(meta, getattr(project, "gross_floor_area", None))
    count = 1  # a house brief is one house, also of a compound
    if template == "apartment_section":
        count = max(1, min(count_hint or above * 4, APARTMENTS_TOP * above))
    if gfa and template == "house" and count_hint:
        plate = gfa / count_hint / above  # one house of a compound
    elif gfa:
        plate = gfa / (above + below)
    else:
        plate = _DEFAULT_PLATE.get(category, 1200.0)
    per_floor = math.ceil(count / above) if template == "apartment_section" else 1
    width, depth = _footprint(template, plate, above, per_floor)
    _, height, _, _ = TYPOLOGY[template]
    height = _FLOOR_HEIGHT.get(category, height)

    source: dict[str, str] = {}
    doc: dict[str, Any] = {
        "name": name[:200] or "Design",
        "country": country,
        "locale": locale,
        "depth_level": DEPTH_LEVEL,
        "use": {"category": category},
        "massing": {
            "floors_above": above,
            "floors_below": below,
            "floor_height_m": height,
            "footprint": {"width_m": width, "depth_m": depth},
            "lift": template != "house" and above >= 3,
        },
        "programme": _programme(category, template, count, gfa, meta, plate),
        "structure": {
            "system": "masonry"
            if template == "house"
            else "steel"
            if category in ("warehouse", "industrial")
            else "concrete_frame",
            "foundation": "strip" if template == "house" or above == 1 else "raft",
        },
        "envelope": {"roof": "gable" if template == "house" else "flat"},
        "quality_level": "standard",
        "generator": {"template": template},
    }
    detail = next((str(meta[k]) for k in ("use_mix", "units", "building_type") if isinstance(meta.get(k), str)), None)
    if detail:
        doc["use"]["detail"] = detail[:500]
    source["/use/category"] = _RECORD_NOTE
    source["/massing/floors_above"] = _RECORD_NOTE if above_record else _DERIVED_NOTE
    source["/massing/floors_below"] = _RECORD_NOTE
    source["/massing/footprint/width_m"] = _DERIVED_NOTE
    source["/massing/footprint/depth_m"] = _DERIVED_NOTE
    if gfa:
        doc["massing"]["gross_floor_area_m2"] = round(gfa, 1)
        source["/massing/gross_floor_area_m2"] = _RECORD_NOTE
    if doc["programme"].get("units"):
        source["/programme/units/0/count"] = _RECORD_NOTE if count_hint else _DERIVED_NOTE
    energy = meta.get("energy_standard")
    if isinstance(energy, str) and energy.strip():
        doc["envelope"]["energy_standard"] = energy.strip()[:100]
    site: dict[str, Any] = {}
    if line := _address_line(getattr(project, "address", None)):
        site["address"] = line
    if plot := _plot(getattr(project, "address", None), width, depth):
        site["plot"] = plot
        source["/site/plot"] = _DERIVED_NOTE
    if site:
        doc["site"] = site
    currency = (getattr(project, "currency", None) or "").strip().upper()
    amount = _budget(project, meta)
    if amount and re.fullmatch(r"[A-Z]{3}", currency):
        doc["budget"] = {"amount": amount, "currency": currency, "includes_vat": False}
        source["/budget/amount"] = _RECORD_NOTE
    return doc, source


def _provenance(source: dict[str, str]) -> dict[str, dict]:
    return {p: {"status": "proposed", "sources": [{"kind": "text"}], "note": note} for p, note in source.items()}


async def _owner(session: AsyncSession, project: Any) -> uuid.UUID:
    from app.core.demo_accounts import SHOWCASE_OWNER_EMAIL
    from app.modules.users.models import User

    uid = (
        await session.execute(select(User.id).where(func.lower(User.email) == SHOWCASE_OWNER_EMAIL))
    ).scalar_one_or_none()
    return uid or project.owner_id


async def _seed_brief(session: AsyncSession, project: Any, user_id: uuid.UUID) -> dict | None:
    """Save the brief (version 1) and confirm every value in it (version 2), as a person does in the form."""
    from .brief import _head, _store
    from .brief_doc import apply_confirm, prepare_save

    if await _head(session, project.id) is not None:
        return None
    built = brief_for(project)
    if built is None:
        return None
    body, source = built
    body["provenance"] = _provenance(source)
    saved, _ = prepare_save(body, None, project_id=project.id, brief_id=uuid.uuid4(), version=1)
    await _store(
        session, None, project_id=project.id, expected=0, document=saved, user_id=user_id, action="save", commit=False
    )
    head = await _head(session, project.id)
    confirmed = apply_confirm(saved, sorted(source), user_id=user_id, at=datetime.now(UTC), version=2)
    await _store(
        session,
        head,
        project_id=project.id,
        expected=1,
        document=confirmed,
        user_id=user_id,
        action="confirm",
        commit=False,
    )
    return confirmed


async def _seed_revision(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID):
    """The project's richest converter model as revision 1, through ``imported.wrap``; None when there is none."""
    from . import imported
    from .imported_api import held_lock
    from .models import DesignRevision

    if (
        await session.execute(select(DesignRevision.id).where(DesignRevision.project_id == project_id).limit(1))
    ).first():
        return None
    if await held_lock(session, project_id) is not None:
        return None
    models = sorted(await imported.candidates(session, project_id), key=lambda m: -(m.element_count or 0))
    for model in models:
        try:
            async with session.begin_nested():
                return await imported.wrap(session, model, user_id=user_id, depth_level=DEPTH_LEVEL)
        except imported.NotWrappable as exc:
            logger.info("design demo seed: model %s of %s not wrapped (%s)", model.id, project_id, exc)
    return None


async def _seed_estimate(session: AsyncSession, project_id: uuid.UUID, brief: dict, rev, user_id: uuid.UUID) -> int:
    """Install the country's starter rules when they are written for the brief's use, and run them on ``rev``."""
    from . import estimate as est
    from . import links, rules
    from .models import DesignEstimate, DesignRevision

    if (await session.execute(select(DesignEstimate.id).where(DesignEstimate.project_id == project_id))).first():
        return 0
    if rev is None:  # a re-run: the imported revision an earlier run wrapped
        rev = (
            await session.execute(
                select(DesignRevision)
                .where(DesignRevision.project_id == project_id, DesignRevision.source_kind == "imported")
                .order_by(DesignRevision.number)
                .limit(1)
            )
        ).scalar_one_or_none()
    if rev is None or rev.bim_model_id is None or rev.status not in ("published", "shared"):
        return 0
    doc = rules.starter_set(brief["country"])
    if doc is None or doc.get("use") != brief["use"]["category"]:
        return 0
    async with session.begin_nested():
        await est.install_rules(session, project_id, doc, user_id)
        rows = await est.recompute(session, project_id, rev.id, rev.bim_model_id, user_id)
        await links.sync(session, project_id)
    return len(rows)


async def seed_design_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Brief, revision 1 and design estimate for every demo project in ``project_ids``. The caller commits."""
    from app.core.demo_marker import demo_id_of
    from app.modules.projects.models import Project

    from .brief import current_brief

    totals = {"briefs": 0, "revisions": 0, "estimate_positions": 0}
    ids = list(project_ids)
    if not ids:
        return totals
    projects = (await session.execute(select(Project).where(Project.id.in_(ids)))).scalars().all()
    for project in [p for p in projects if demo_id_of(p.metadata_)]:
        user_id = await _owner(session, project)
        if user_id is None:
            continue
        try:
            async with session.begin_nested():
                brief = await _seed_brief(session, project, user_id)
            totals["briefs"] += brief is not None
        except Exception:
            logger.warning("design demo seed: brief of %s skipped", project.id, exc_info=True)
        try:
            rev = await _seed_revision(session, project.id, user_id)
            totals["revisions"] += rev is not None
        except Exception:
            logger.warning("design demo seed: revision of %s skipped", project.id, exc_info=True)
            rev = None
        doc = await current_brief(session, project.id)
        if doc is None:
            continue
        try:
            totals["estimate_positions"] += await _seed_estimate(session, project.id, doc, rev, user_id)
        except Exception:
            logger.warning("design demo seed: estimate of %s skipped", project.id, exc_info=True)
    return totals


async def _main() -> dict[str, int]:
    from app.core.demo_marker import live_demo_projects
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as session:
        pids = list((await session.execute(select(Project.id).order_by(Project.created_at, Project.id))).scalars())
        live = [pid for pid, _ in await live_demo_projects(session, pids)]
        counts = await seed_design_demo(session, live)
        await session.commit()
    return counts


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(_main()))  # noqa: T201
