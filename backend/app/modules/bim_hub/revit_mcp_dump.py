# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Convert a ``revit-mcp`` tool dump into BIM Hub bulk-import elements.

Why this exists
---------------
``revit-mcp`` / ``mcp-server-for-revit`` expose Revit through MCP tools
(``get_current_view_elements``, ``get_material_quantities``,
``analyze_model_statistics`` ...). Those servers are **stdio** processes
that must run on the workstation where Revit itself is open, so the ERP
backend can never call them directly. The practical bridge is a file: the
operator runs the MCP tools locally, saves the raw JSON responses, and
hands that dump to this module, which turns it into the same
``BIMElementCreate`` shape the CAD converter pipeline produces.

Three projections, three tiers
------------------------------
A dump does not necessarily contain per-instance records, so the
converter emits whatever tier the dump actually supports and says which
one each row came from via ``metadata["tier"]``:

``instance``
    From ``get_current_view_elements``. One row per real Revit element.
    Richest tier, but only present when the dump was taken from a *model*
    view - a ``DrawingSheet`` active view yields no model elements.
``type``
    From ``analyze_model_statistics.categories[].types[]``. One row per
    Revit family type, carrying its category, family and instance count.
    Always available and enough to drive category/trade level reporting.
``material``
    From ``get_material_quantities.materials[]``. One row per material
    with its aggregate area/volume and the element ids that consume it.

Units
-----
The Revit API reports areas in ft² and volumes in ft³ internally, and the
MCP servers forward those numbers without a unit field. Since the dump
carries no way to *verify* that, the default ``units="raw"`` stores the
values verbatim under ``area_raw`` / ``volume_raw`` and stamps
``metadata["units"] = "unverified"``. Pass ``units="imperial"`` to opt
into the ft²/ft³ reading and get converted ``area_m2`` / ``volume_m3``.
Never assume a dump is metric because the numbers look plausible.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.match_elements.revit_ifc_map import normalize_to_ifc_class

logger = logging.getLogger(__name__)

#: Marker written into every row's ``properties["source"]``.
SOURCE = "revit-mcp"

#: Accepted values for the ``units`` argument of :func:`convert_dump`.
UNITS_RAW = "raw"
UNITS_IMPERIAL = "imperial"

# Exact factors (international foot).
_SQFT_TO_SQM = 0.09290304
_CUFT_TO_CUM = 0.028316846592

# Column widths from app.modules.bim_hub.models.BIMElement / the matching
# BIMElementCreate validators. Over-long values are clipped here rather
# than rejected by Pydantic at import time.
_MAX_STABLE_ID = 255
_MAX_ELEMENT_TYPE = 100
_MAX_NAME = 500
_MAX_STOREY = 255
_MAX_DISCIPLINE = 50

# Discipline inference from a Revit category name. Ordered: the first
# keyword hit wins, so electrical/mechanical are probed before the
# architectural keywords ("Lighting Fixtures" must not become
# architectural just because a later rule matches "fixture").
#
# Deliberately conservative, mirroring revit_ifc_map: a category that
# matches nothing yields ``None`` instead of a guess, and the caller keeps
# the raw category in ``properties``.
_DISCIPLINE_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "electrical",
            "lighting",
            "cable tray",
            "conduit",
            "wire",
            "fire alarm",
            "security",
            "communication",
            "data device",
            "telephone",
            "nurse call",
            "panel schedule",
        ),
        "electrical",
    ),
    (
        (
            "duct",
            "hvac",
            "mechanical",
            "pipe",
            "plumbing",
            "sprinkler",
            "air terminal",
            "space",
        ),
        "mechanical",
    ),
    (
        ("structural", "rebar", "truss", "foundation"),
        "structural",
    ),
    (
        (
            "wall",
            "floor",
            "door",
            "window",
            "ceiling",
            "roof",
            "room",
            "stair",
            "railing",
            "curtain",
            "furniture",
            "casework",
        ),
        "architectural",
    ),
    (
        ("topography", "site", "pad", "road"),
        "civil",
    ),
)

# Tolerant key lookup for instance rows. The two MCP servers in the wild
# disagree on casing and on whether the id field is Id/ElementId, so every
# plausible spelling is probed instead of pinning one shape.
_INSTANCE_ID_KEYS = ("Id", "ElementId", "elementId", "id", "UniqueId", "uniqueId")
_INSTANCE_NAME_KEYS = ("Name", "name", "TypeName", "typeName", "FamilyName", "familyName")
_INSTANCE_CATEGORY_KEYS = ("Category", "category", "CategoryName", "categoryName")
_INSTANCE_FAMILY_KEYS = ("FamilyName", "familyName", "Family", "family")
_INSTANCE_TYPE_KEYS = ("TypeName", "typeName", "Type", "type")
_INSTANCE_LEVEL_KEYS = ("Level", "level", "LevelName", "levelName", "Storey", "storey")

# Revit categories that hold drafting/view bookkeeping rather than
# building elements. BIMElement doubles as the project asset register, so
# importing tags, title blocks and detail lines into it produces rows that
# can never carry geometry, quantity or cost - they are dropped unless the
# caller explicitly asks for them via ``include_annotation=True``.
#
# Matched as substrings against the lower-cased category name, so "Room
# Tags", "Lighting Fixture Tags" and "Cable Tray Tags" are all covered by
# the single "tag" token.
_ANNOTATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "tag",
        "annotation",
        "text note",
        "detail item",
        "detail group",
        "title block",
        "line",
        "dimension",
        "legend",
        "viewport",
        "sheet",
        "view",
        "schedule",
        "grid",
        "reference plane",
        "camera",
        "section box",
        "sun path",
        "color fill",
        "raster image",
        "sketch",
        "constraint",
        "revision",
        "phase",
        "material asset",
        "elevation",
        "level",
        "internal origin",
        "survey point",
        "base point",
        "shared site",
        "plan region",
        "contour",
        "load case",
        "project information",
    },
)


def is_annotation_category(category: str | None) -> bool:
    """Whether a Revit category is drafting/view bookkeeping, not an element.

    Args:
        category: Raw Revit category name, e.g. ``"Room Tags"``.

    Returns:
        ``True`` for annotation, view and project-bookkeeping categories
        that cannot carry geometry or cost. ``False`` for anything else,
        including unknown categories - an unrecognised category is treated
        as a real element so nothing physical is dropped by accident.
    """
    if not category:
        return False
    haystack = str(category).lower()
    return any(keyword in haystack for keyword in _ANNOTATION_KEYWORDS)


@dataclass
class ConversionResult:
    """Outcome of converting one dump.

    Attributes:
        elements: Rows shaped for ``BIMElementCreate`` - feed straight to
            ``POST /models/{model_id}/elements/`` as ``{"elements": [...]}``.
        model: Suggested ``BIMModel`` field values for the dump's project.
        warnings: Human-readable notes about anything skipped, empty or
            unrecognised. Never raised - a partial dump still converts.
    """

    elements: list[dict[str, Any]] = field(default_factory=list)
    model: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def tier_counts(self) -> dict[str, int]:
        """Row count per ``metadata["tier"]``, for logging and CLI output."""
        counts: dict[str, int] = {}
        for element in self.elements:
            tier = str(element.get("metadata", {}).get("tier", "unknown"))
            counts[tier] = counts.get(tier, 0) + 1
        return counts


def _clip(value: Any, limit: int) -> str | None:
    """Coerce ``value`` to a stripped string of at most ``limit`` chars."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _slug(raw: Any) -> str:
    """Lower-case, dash-separated token safe to embed in a stable id."""
    text = re.sub(r"[^a-z0-9]+", "-", str(raw).strip().lower())
    return text.strip("-") or "unknown"


def _stable_id(*parts: Any) -> str:
    """Build a deterministic ``stable_id`` that fits the column.

    Over-long ids keep a readable prefix and gain a content hash suffix,
    so two long-but-different ids never collide after truncation.
    """
    raw = ":".join(_slug(part) for part in parts)
    if len(raw) <= _MAX_STABLE_ID:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]  # noqa: S324  # not security
    keep = _MAX_STABLE_ID - len(digest) - 1
    return f"{raw[:keep]}-{digest}"


def _first(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        value = source.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def infer_discipline(category: str | None) -> str | None:
    """Map a Revit category name to an ERP discipline, or ``None``.

    Args:
        category: Raw Revit category name, e.g. ``"Lighting Fixtures"``.

    Returns:
        One of the discipline values already used across the backend
        (``electrical`` / ``mechanical`` / ``structural`` /
        ``architectural`` / ``civil``), or ``None`` when no keyword
        matches - callers must not substitute a default.
    """
    if not category:
        return None
    haystack = str(category).lower()
    for keywords, discipline in _DISCIPLINE_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return discipline
    return None


def _element_type_for(category: str | None) -> str | None:
    """Prefer the canonical IFC class, fall back to the raw category."""
    ifc_class = normalize_to_ifc_class(category)
    return _clip(ifc_class or category, _MAX_ELEMENT_TYPE)


def _quantities(area: Any, volume: Any, units: str) -> dict[str, Any]:
    """Build the ``quantities`` dict honouring the ``units`` contract."""
    quantities: dict[str, Any] = {}
    area_value = _as_float(area)
    volume_value = _as_float(volume)
    if units == UNITS_IMPERIAL:
        if area_value is not None:
            quantities["area_m2"] = area_value * _SQFT_TO_SQM
        if volume_value is not None:
            quantities["volume_m3"] = volume_value * _CUFT_TO_CUM
    else:
        if area_value is not None:
            quantities["area_raw"] = area_value
        if volume_value is not None:
            quantities["volume_raw"] = volume_value
    return quantities


def _as_float(value: Any) -> float | None:
    """Best-effort numeric coercion; ``None`` for anything non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _units_note(units: str) -> str:
    """Value stamped into ``metadata["units"]`` for quantity-bearing rows."""
    return "m2/m3 (assumed ft2/ft3 source)" if units == UNITS_IMPERIAL else "unverified"


def _instance_elements(
    payload: Any,
    units: str,
    warnings: list[str],
    *,
    include_annotation: bool,
) -> list[dict[str, Any]]:
    """Rows from ``get_current_view_elements`` (one per Revit element)."""
    if not isinstance(payload, dict):
        return []

    # The dump nests the tool result one level down when the operator
    # recorded the call arguments alongside it.
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    raw_elements = result.get("Elements") or result.get("elements") or []
    if not isinstance(raw_elements, list) or not raw_elements:
        view_name = result.get("ViewName") or result.get("viewName")
        warnings.append(
            "get_current_view_elements returned no elements"
            + (f" for view {view_name!r}" if view_name else "")
            + " - re-run the dump from a 3D or plan view (a DrawingSheet "
            "exposes only its viewports) and request categories the model "
            "actually contains.",
        )
        return []

    if result.get("Truncated") or result.get("truncated"):
        warnings.append(
            "get_current_view_elements reported Truncated=true - the dump "
            "holds only part of the view; raise the tool's limit and re-run.",
        )

    rows: list[dict[str, Any]] = []
    skipped = 0
    dropped_annotation = 0
    for raw in raw_elements:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        native_id = _first(raw, _INSTANCE_ID_KEYS)
        if native_id is None:
            skipped += 1
            continue
        category = _first(raw, _INSTANCE_CATEGORY_KEYS)
        if not include_annotation and is_annotation_category(category):
            dropped_annotation += 1
            continue
        family = _first(raw, _INSTANCE_FAMILY_KEYS)
        type_name = _first(raw, _INSTANCE_TYPE_KEYS)
        properties: dict[str, Any] = {"source": SOURCE, "revit_element_id": native_id}
        if category:
            properties["revit_category"] = category
        if family:
            properties["revit_family"] = family
        if type_name:
            properties["revit_type"] = type_name
        rows.append(
            {
                "stable_id": _stable_id("rvt", native_id),
                "element_type": _element_type_for(category),
                "name": _clip(_first(raw, _INSTANCE_NAME_KEYS) or type_name or native_id, _MAX_NAME),
                "storey": _clip(_first(raw, _INSTANCE_LEVEL_KEYS), _MAX_STOREY),
                "discipline": _clip(infer_discipline(category), _MAX_DISCIPLINE),
                "properties": properties,
                "quantities": _quantities(
                    _first(raw, ("Area", "area")),
                    _first(raw, ("Volume", "volume")),
                    units,
                ),
                "metadata": {"tier": "instance", "source": SOURCE, "units": _units_note(units)},
            },
        )

    if skipped:
        warnings.append(
            f"{skipped} instance record(s) skipped: no recognisable element id among {list(_INSTANCE_ID_KEYS)}.",
        )
    if dropped_annotation:
        warnings.append(
            f"{dropped_annotation} instance row(s) dropped as annotation/view "
            "categories - pass include_annotation=True to keep them.",
        )
    return rows


def _type_elements(
    stats: Any,
    warnings: list[str],
    *,
    include_annotation: bool,
) -> list[dict[str, Any]]:
    """Rows from ``analyze_model_statistics`` (one per Revit family type)."""
    if not isinstance(stats, dict):
        return []
    categories = stats.get("categories")
    if not isinstance(categories, list):
        return []

    rows: list[dict[str, Any]] = []
    categories_without_types = 0
    dropped_annotation = 0
    for category in categories:
        if not isinstance(category, dict):
            continue
        category_name = category.get("categoryName") or category.get("CategoryName")
        if not include_annotation and is_annotation_category(category_name):
            dropped_annotation += 1
            continue
        types = category.get("types")
        if not isinstance(types, list) or not types:
            # Annotation/system categories legitimately carry no family
            # types; counted for the summary, not warned about per row.
            categories_without_types += 1
            continue
        for type_entry in types:
            if not isinstance(type_entry, dict):
                continue
            type_name = type_entry.get("typeName") or type_entry.get("TypeName")
            family_name = type_entry.get("familyName") or type_entry.get("FamilyName")
            instance_count = type_entry.get("instanceCount", type_entry.get("InstanceCount"))
            rows.append(
                {
                    "stable_id": _stable_id("rvt-type", category_name, family_name, type_name),
                    "element_type": _element_type_for(category_name),
                    "name": _clip(type_name or family_name, _MAX_NAME),
                    "storey": None,
                    "discipline": _clip(infer_discipline(category_name), _MAX_DISCIPLINE),
                    "properties": {
                        "source": SOURCE,
                        "revit_category": category_name,
                        "revit_family": family_name,
                        "revit_type": type_name,
                    },
                    "quantities": (
                        {"instance_count": int(instance_count)}
                        if isinstance(instance_count, int | float) and not isinstance(instance_count, bool)
                        else {}
                    ),
                    "metadata": {"tier": "type", "source": SOURCE},
                },
            )

    if categories_without_types:
        warnings.append(
            f"{categories_without_types} of {len(categories)} categories exposed no "
            "family types (system/analytical categories) - no type rows for those.",
        )
    if dropped_annotation:
        warnings.append(
            f"{dropped_annotation} annotation/view category/categories skipped "
            "(tags, title blocks, sheets, dimensions ...) - pass "
            "include_annotation=True to keep them.",
        )
    return rows


def _material_elements(payload: Any, units: str, warnings: list[str]) -> list[dict[str, Any]]:
    """Rows from ``get_material_quantities`` (one per material)."""
    if not isinstance(payload, dict):
        return []
    materials = payload.get("materials")
    if not isinstance(materials, list) or not materials:
        return []

    if payload.get("truncated"):
        warnings.append(
            "get_material_quantities reported truncated=true - material rows are incomplete.",
        )

    rows: list[dict[str, Any]] = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        material_id = material.get("materialId", material.get("MaterialId"))
        material_name = material.get("materialName", material.get("MaterialName"))
        if material_id is None and not material_name:
            continue
        element_ids = material.get("elementIds")
        element_ids = element_ids if isinstance(element_ids, list) else []
        properties: dict[str, Any] = {
            "source": SOURCE,
            "revit_material_id": material_id,
            "revit_material_class": material.get("materialClass", material.get("MaterialClass")),
            # Kept verbatim: this is the only link from a material back to
            # the instances that consume it, and it is what lets a later
            # instance-tier import attach material composition per element.
            "revit_element_ids": element_ids,
        }
        quantities = _quantities(
            material.get("area", material.get("Area")),
            material.get("volume", material.get("Volume")),
            units,
        )
        element_count = material.get("elementCount", material.get("ElementCount"))
        if isinstance(element_count, int | float) and not isinstance(element_count, bool):
            quantities["element_count"] = int(element_count)
        rows.append(
            {
                "stable_id": _stable_id("rvt-material", material_id if material_id is not None else material_name),
                "element_type": "IfcMaterial",
                "name": _clip(material_name, _MAX_NAME),
                "storey": None,
                "discipline": None,
                "properties": properties,
                "quantities": quantities,
                "metadata": {"tier": "material", "source": SOURCE, "units": _units_note(units)},
            },
        )
    return rows


def _model_summary(dump: dict[str, Any], stats: Any, units: str) -> dict[str, Any]:
    """Suggested ``BIMModel`` field values for the dump's project."""
    stats = stats if isinstance(stats, dict) else {}
    view_info = dump.get("get_current_view_info")
    view_info = view_info if isinstance(view_info, dict) else {}
    levels = stats.get("levels") if isinstance(stats.get("levels"), list) else []

    disciplines = {
        infer_discipline(category.get("categoryName"))
        for category in (stats.get("categories") or [])
        if isinstance(category, dict) and not is_annotation_category(category.get("categoryName"))
    }
    disciplines.discard(None)

    return {
        "name": _clip(stats.get("projectName") or view_info.get("Name") or "Revit MCP dump", _MAX_NAME),
        # A single discipline column cannot describe a mixed model; only
        # claim one when the dump is unambiguous.
        "discipline": _clip(next(iter(disciplines)), _MAX_DISCIPLINE) if len(disciplines) == 1 else None,
        "model_format": "rvt",
        "storey_count": len(levels),
        "metadata": {
            "source": SOURCE,
            "units": _units_note(units),
            "revit_project_name": stats.get("projectName"),
            "revit_totals": {
                key: stats.get(key)
                for key in (
                    "totalElements",
                    "totalTypes",
                    "totalFamilies",
                    "totalViews",
                    "totalSheets",
                )
                if stats.get(key) is not None
            },
            "revit_active_view": (
                {
                    "id": view_info.get("Id"),
                    "name": view_info.get("Name"),
                    "view_type": view_info.get("ViewType"),
                    "scale": view_info.get("Scale"),
                }
                if view_info
                else None
            ),
            "revit_levels": [
                {
                    "name": level.get("levelName"),
                    "elevation_raw": level.get("elevation"),
                    "element_count": level.get("elementCount"),
                }
                for level in levels
                if isinstance(level, dict)
            ],
            "disciplines_detected": sorted(d for d in disciplines if d),
        },
    }


def convert_dump(
    dump: dict[str, Any],
    *,
    units: str = UNITS_RAW,
    include_annotation: bool = False,
) -> ConversionResult:
    """Convert a ``revit-mcp`` dump into bulk-import elements.

    Args:
        dump: Parsed dump JSON. Keys are MCP tool names
            (``get_current_view_info``, ``get_current_view_elements``,
            ``get_material_quantities``, ``analyze_model_statistics``);
            any subset is accepted and unknown keys are ignored.
        units: ``"raw"`` (default) keeps quantity numbers verbatim under
            ``area_raw`` / ``volume_raw``; ``"imperial"`` reads them as
            ft²/ft³ and emits ``area_m2`` / ``volume_m3``.
        include_annotation: Keep drafting/view categories (tags, title
            blocks, sheets, dimensions). Off by default because
            ``BIMElement`` doubles as the project asset register and those
            rows can never carry geometry, quantity or cost.

    Returns:
        A :class:`ConversionResult`. Never raises on a partial or
        unexpected dump - problems land in ``warnings`` so a bad dump
        degrades to fewer rows instead of an import failure.

    Raises:
        ValueError: If ``dump`` is not a dict or ``units`` is unknown.
    """
    if not isinstance(dump, dict):
        msg = f"dump must be a dict of MCP tool name → response, got {type(dump).__name__}"
        raise ValueError(msg)
    if units not in (UNITS_RAW, UNITS_IMPERIAL):
        msg = f"units must be {UNITS_RAW!r} or {UNITS_IMPERIAL!r}, got {units!r}"
        raise ValueError(msg)

    warnings: list[str] = []
    stats = dump.get("analyze_model_statistics")

    elements = [
        *_instance_elements(
            dump.get("get_current_view_elements"),
            units,
            warnings,
            include_annotation=include_annotation,
        ),
        *_type_elements(stats, warnings, include_annotation=include_annotation),
        *_material_elements(dump.get("get_material_quantities"), units, warnings),
    ]

    # stable_id is the model-scoped identity used by the diff engine, so a
    # duplicate would silently overwrite a sibling row. Keep first-seen.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for element in elements:
        stable_id = element["stable_id"]
        if stable_id in seen:
            warnings.append(f"duplicate stable_id {stable_id!r} dropped.")
            continue
        seen.add(stable_id)
        deduped.append(element)

    if not deduped:
        warnings.append(
            "no elements produced - the dump carries none of "
            "get_current_view_elements / analyze_model_statistics / "
            "get_material_quantities in a recognised shape.",
        )

    model = _model_summary(dump, stats, units)
    model["element_count"] = len(deduped)

    logger.info(
        "revit-mcp dump converted: %d element rows (%s) for project %r",
        len(deduped),
        ", ".join(f"{tier}={count}" for tier, count in sorted(ConversionResult(deduped).tier_counts.items())),
        model.get("name"),
    )

    return ConversionResult(elements=deduped, model=model, warnings=warnings)


def build_bulk_import_payload(
    dump: dict[str, Any],
    *,
    units: str = UNITS_RAW,
    include_annotation: bool = False,
) -> dict[str, Any]:
    """Return the request body for ``POST /models/{model_id}/elements/``.

    Convenience wrapper around :func:`convert_dump` for callers that only
    want the wire payload and not the model summary or warnings.
    """
    result = convert_dump(dump, units=units, include_annotation=include_annotation)
    return {"elements": result.elements}
