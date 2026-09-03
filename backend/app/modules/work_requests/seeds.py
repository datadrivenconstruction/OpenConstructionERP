# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The five departments a fresh install starts with.

Neutral names, every one of them editable afterwards (``PATCH
/departments/{key}``). The stage runs and request types are the ones the
intake spreadsheets carried: three intake logs (engineering + drafting,
manufacturing, automation) on one spine, plus the drafting and switchboard
trackers' own status columns.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests.models import WorkDepartment

logger = logging.getLogger(__name__)


def _stage(key: str, name: str, colour: str, order: int, closes: bool = False) -> dict:
    return {"key": key, "name": name, "colour": colour, "order": order, "closes": closes}


def _field(key: str, label: str, ftype: str, options: list[str] | None = None, required: bool = False) -> dict:
    out: dict = {"key": key, "label": label, "type": ftype, "required": required}
    if options is not None:
        out["options"] = list(options)
    return out


def _rtype(key: str, label: str, disciplines: list[str], fields: list[dict] | None = None) -> dict:
    return {
        "key": key,
        "label": label,
        "disciplines": list(disciplines),
        "fields": list(fields or []),
        "active": True,
        "position": 0,
    }


#: The colour ``hazardous_area`` was seeded with before it went red. The
#: startup reconcile repaints an install ONLY while it still reads this -
#: a colour the owner chose is theirs.
LEGACY_HAZARDOUS_AREA_COLOUR = "rose"

_ENGINEERING_FIELDS = [_field("request_form_url", "Request form / drawings link", "url")]
_DRAFTING_FIELDS = [
    _field("drawing_link", "Drawing link", "url"),
    _field("scope", "Scope", "select", ["Both", "Drafting only", "Board only"]),
]


DEFAULT_DEPARTMENTS: list[dict] = [
    {
        "key": "engineering",
        "name": "Engineering",
        "prefix": "ENG",
        "colour": "blue",
        "description": "Design, calculations and engineered solutions.",
        "stages": [
            _stage("received", "Received", "slate", 0),
            _stage("design", "Design", "blue", 1),
            _stage("review", "Review", "amber", 2),
            _stage("issued", "Issued", "green", 3, closes=True),
        ],
        "request_types": [
            _rtype("eng_only", "Engineering only", ["engineering"], _ENGINEERING_FIELDS),
            _rtype("eng_and_drafting", "Engineering and drafting", ["engineering", "drafting"], _ENGINEERING_FIELDS),
            _rtype("load_study", "Load study", ["engineering"], _ENGINEERING_FIELDS),
            _rtype("cable_schedule", "Cable schedule", ["engineering", "drafting"], _ENGINEERING_FIELDS),
            _rtype("arc_flash_study", "Arc flash study", ["engineering"], _ENGINEERING_FIELDS),
            _rtype("protection_settings", "Protection settings", ["engineering"], _ENGINEERING_FIELDS),
            _rtype("site_survey", "Site survey", ["engineering"], _ENGINEERING_FIELDS),
            _rtype("design_review", "Design review", ["engineering"], _ENGINEERING_FIELDS),
        ],
    },
    {
        "key": "drafting",
        "name": "Drafting",
        "prefix": "DRF",
        "colour": "violet",
        "description": "Drawings from ready-to-draft through IFC to site as-builts.",
        "stages": [
            _stage("ready_to_draft", "Ready to draft", "slate", 0),
            _stage("underway", "Underway", "blue", 1),
            _stage("for_review", "For review", "amber", 2),
            _stage("ifc", "IFC", "teal", 3),
            _stage("factory_as_built", "Factory as-built", "violet", 4),
            _stage("site_as_built", "Site as-built", "green", 5, closes=True),
        ],
        "request_types": [
            _rtype("drafting_only", "Drafting only", ["drafting"], _DRAFTING_FIELDS),
            _rtype("update_as_built", "Update as-built", ["drafting"], _DRAFTING_FIELDS),
            _rtype("ifc_issue", "IFC issue", ["drafting"], _DRAFTING_FIELDS),
            _rtype("schematics", "Schematics", ["drafting"], _DRAFTING_FIELDS),
            _rtype("panel_layout", "Panel layout", ["drafting"], _DRAFTING_FIELDS),
            _rtype("redlines_to_as_built", "Redlines to as-built", ["drafting"], _DRAFTING_FIELDS),
            _rtype("cable_schedule_drafting", "Cable schedule", ["drafting"], _DRAFTING_FIELDS),
        ],
    },
    {
        "key": "workshop",
        "name": "Workshop",
        "prefix": "WKS",
        "colour": "orange",
        "description": "Switchboards, control panels and fabrication.",
        "stages": [
            _stage("requested", "Requested", "slate", 0),
            _stage("drawings_received", "Drawings received", "blue", 1),
            _stage("materials_ordered", "Materials ordered", "teal", 2),
            _stage("build", "Build", "orange", 3),
            _stage("wiring", "Wiring", "amber", 4),
            _stage("testing", "Testing", "violet", 5),
            _stage("ready_for_fat", "Ready for FAT", "rose", 6),
            _stage("delivered", "Delivered", "green", 7, closes=True),
        ],
        "request_types": [
            _rtype("switchboard", "Switchboard", ["workshop"], None),
            _rtype("control_panel", "Control panel", ["workshop"], None),
            _rtype("fab_plinth_other", "Fabrication / plinth / other", ["workshop"], None),
            _rtype("modification_retrofit", "Modification / retrofit", ["workshop"], None),
            _rtype("gear_tray", "Gear tray", ["workshop"], None),
            _rtype("terminal_box", "Terminal box", ["workshop"], None),
            _rtype("repair", "Repair", ["workshop"], None),
            _rtype("testing_only", "Testing only", ["workshop"], None),
        ],
    },
    {
        "key": "automation",
        "name": "Automation",
        "prefix": "AUT",
        "colour": "teal",
        "description": "PLC, SCADA, functional design and commissioning.",
        "stages": [
            _stage("scoped", "Scoped", "slate", 0),
            _stage("fds", "FDS", "blue", 1),
            _stage("programming", "Programming", "teal", 2),
            _stage("scada", "SCADA", "violet", 3),
            _stage("fat", "FAT", "amber", 4),
            _stage("commissioning", "Commissioning", "orange", 5),
            _stage("complete", "Complete", "green", 6, closes=True),
        ],
        "request_types": [
            _rtype("plc_programming", "PLC programming", ["automation"], None),
            _rtype("scada", "SCADA", ["automation"], None),
            _rtype("fds", "FDS creation", ["automation"], None),
            _rtype("commissioning", "Commissioning", ["automation"], None),
            _rtype("hmi_screens", "HMI screens", ["automation"], None),
            _rtype("network_config", "Network configuration", ["automation"], None),
            _rtype("safety_plc", "Safety PLC", ["automation"], None),
            _rtype("software_fat", "Software FAT", ["automation"], None),
            _rtype("other", "Other", ["automation"], None),
        ],
    },
    {
        "key": "hazardous_area",
        "name": "Hazardous Area",
        "prefix": "HAZ",
        "colour": "red",
        "description": "Area classification, design review, inspection and dossiers.",
        "stages": [
            _stage("scope", "Scope", "slate", 0),
            _stage("classification", "Classification", "blue", 1),
            _stage("design_review", "Design review", "amber", 2),
            _stage("inspection", "Inspection", "violet", 3),
            _stage("dossier", "Dossier", "teal", 4),
            _stage("certified", "Certified", "green", 5, closes=True),
        ],
        "request_types": [
            _rtype("area_classification", "Area classification", ["hazardous_area"], None),
            _rtype("design_review", "Design review", ["hazardous_area"], None),
            _rtype("inspection_dossier", "Inspection dossier", ["hazardous_area"], None),
            _rtype("ex_inspection", "Ex inspection", ["hazardous_area"], None),
            _rtype("equipment_selection", "Equipment selection", ["hazardous_area"], None),
            _rtype("verification_dossier", "Verification dossier", ["hazardous_area"], None),
            _rtype("other", "Other", ["hazardous_area"], None),
        ],
    },
]

# The fields shared by every type in a department are attached once here
# rather than repeated per type above, so the seed reads as the intake
# sheet did: one column set per department.
_WORKSHOP_FIELDS = [
    _field("factory_cost_centre", "Factory cost centre", "text"),
    _field("drawings_to_factory_by", "Date the factory receives drawings", "date"),
    _field("custom_plinth", "Custom plinth required", "select", ["No", "Yes", "Yes - stand"]),
    _field("ifc_drawing_link", "IFC drawing link", "url"),
    _field("tested_by", "Tested by (date)", "date"),
]
_AUTOMATION_FIELDS = [
    _field("planner_uploaded", "Uploaded to planner", "bool"),
    _field("info_link", "Request / info link", "url"),
]
_HAZ_FIELDS = [
    _field("zone", "Zone", "text"),
    _field("standard", "Standard", "select", ["AS/NZS 60079", "IEC 60079", "Other"]),
]
for _dept in DEFAULT_DEPARTMENTS:
    _shared = {"workshop": _WORKSHOP_FIELDS, "automation": _AUTOMATION_FIELDS, "hazardous_area": _HAZ_FIELDS}.get(
        _dept["key"]
    )
    for _position, _rt in enumerate(_dept["request_types"]):
        _rt["position"] = _position
        if _shared:
            _rt["fields"] = [dict(f) for f in _shared]
        else:
            _rt["fields"] = [dict(f) for f in _rt["fields"]]


def seeded_request_type(department_key: str, type_key: str) -> dict | None:
    """The seeded spec for one type, or ``None`` - a deep copy, never the
    module-level dict, so a caller cannot edit the catalogue in place."""
    for spec in DEFAULT_DEPARTMENTS:
        if spec["key"] != department_key:
            continue
        for rt in spec["request_types"]:
            if rt["key"] == type_key:
                return {**rt, "fields": [dict(f) for f in rt["fields"]]}
    return None


async def seed_departments_if_empty(session: AsyncSession) -> int:
    """Plant the defaults when NO department exists. Never touches a
    configured install - a deleted or renamed seed stays deleted or
    renamed. Returns how many rows were added."""
    count = await session.scalar(select(func.count()).select_from(WorkDepartment))
    if count:
        return 0
    for position, spec in enumerate(DEFAULT_DEPARTMENTS):
        session.add(
            WorkDepartment(
                key=spec["key"],
                name=spec["name"],
                prefix=spec["prefix"],
                colour=spec["colour"],
                description=spec["description"],
                active=True,
                position=position,
                lead_user_id=None,
                member_ids=[],
                hourly_rate=None,
                stages=[dict(s) for s in spec["stages"]],
                request_types=[
                    {**rt, "fields": [dict(f) for f in rt.get("fields", [])]} for rt in spec["request_types"]
                ],
            )
        )
    await session.flush()
    logger.info("work_requests: seeded %d departments", len(DEFAULT_DEPARTMENTS))
    return len(DEFAULT_DEPARTMENTS)


async def reconcile_seeded_departments(session: AsyncSession) -> dict:
    """Top a LIVE install up with what a later release added, additively.

    ``seed_departments_if_empty`` only ever fires on a database with no
    department at all, so an install that started before this release
    would never see a newly seeded request type or the hazardous-area
    colour. This runs on every startup and is deliberately timid:

    * a seeded request type whose key is MISSING is appended at the end;
    * a type already there is left exactly as it is - label, fields,
      order, and ``active: false`` if the owner retired it;
    * a type the owner ADDED is never moved or renumbered;
    * a department key that is not one of the five seeds is never touched;
    * ``hazardous_area`` is repainted red only while it still carries the
      colour the old seed gave it.

    Returns ``{"added": {dept: [keys]}, "recoloured": [dept]}``.
    """
    by_key = {spec["key"]: spec for spec in DEFAULT_DEPARTMENTS}
    rows = (await session.execute(select(WorkDepartment).where(WorkDepartment.key.in_(list(by_key))))).scalars().all()
    added: dict[str, list[str]] = {}
    recoloured: list[str] = []
    for dept in rows:
        spec = by_key[dept.key]
        existing = list(dept.request_types or [])
        have = {str(rt.get("key") or "") for rt in existing}
        nextpos = max((int(rt.get("position") or 0) for rt in existing), default=-1) + 1
        new: list[dict] = []
        for rt in spec["request_types"]:
            if rt["key"] in have:
                continue
            new.append({**rt, "fields": [dict(f) for f in rt["fields"]], "position": nextpos})
            nextpos += 1
        if new:
            # A NEW list object, not an in-place append: a JSON column is
            # only marked dirty when the attribute itself is reassigned.
            dept.request_types = [*existing, *new]
            added[dept.key] = [rt["key"] for rt in new]
        if dept.key == "hazardous_area" and dept.colour == LEGACY_HAZARDOUS_AREA_COLOUR:
            dept.colour = spec["colour"]
            recoloured.append(dept.key)
    if added or recoloured:
        await session.flush()
        logger.info(
            "work_requests: reconciled seeds - added %s; recoloured %s",
            ", ".join(f"{k} +{len(v)}" for k, v in sorted(added.items())) or "nothing",
            ", ".join(recoloured) or "nothing",
        )
    return {"added": added, "recoloured": recoloured}
