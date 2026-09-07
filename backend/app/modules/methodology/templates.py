# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Built-in estimating-methodology templates (pure data + a pure builder).

This module is the data-driven catalogue of methodology templates the platform
ships with: a neutral international default, flat templates for many popular
countries across every region, the Uzbekistan cascading methodology, the
Mexican APU cascading methodology, and a set of industry packs (railway, roads,
bridges, tunnelling, earthworks, water and wastewater, power, industrial plant,
residential and commercial buildings, and building services). The service layer
(:mod:`app.modules.methodology.service`) installs any of these into a project
idempotently.

Each template is a plain ``dict`` (see :data:`TEMPLATES`) describing everything
that distinguishes one estimating tradition from another:

* ``slug`` / ``name`` / ``description`` - identity and display text.
* ``country_code`` / ``industry`` - classification (either may be ``None``).
* ``currency`` / ``decimals`` - monetary presentation; the engine never blends
  or converts currencies.
* ``hierarchy_levels`` - the ordered typed levels a BOQ uses under this
  methodology (e.g. section/complex/object/work for railway).
* ``dimensions`` - the analytical dimensions activated, each a flat reference
  list or a value tree (e.g. the CBS "Chapters" / "Главы" tree).
* ``column_preset`` - a named BOQ column preset (GAEB / NRM2 / ...), or ``None``.
* ``base_mapping`` - maps each cascade leaf base token to the resource types
  that feed it (consumed by :func:`app.modules.methodology.bases.resolve_bases`).
* ``composites`` - named sums of leaf base tokens (e.g. SMR = labor + machinery
  + materials).
* ``cascade_steps`` - the ordered markup steps (see
  :func:`app.modules.methodology.cascade.compute_cascade`). Rates and fixed
  amounts are stored as STRINGS so no float ever touches money.
* ``vat_rate`` - convenience copy of the VAT percentage as a string, or ``None``
  when VAT is modelled purely as a cascade step.

Design constraints (mirror cascade.py / bases.py):

* Standard library only - ``decimal``, ``dataclasses`` (via the imported pure
  engine), ``typing``. Three ``app.*`` imports are allowed and no others: the
  two sibling PURE engine modules, imported lazily inside
  :func:`build_cascade_spec` and as re-exported types, and
  :mod:`app.modules.boq.markup_templates`, which is standard-library only for
  exactly this reason. The rule was never "nothing under ``app``", it was "no
  SQLAlchemy, Pydantic or FastAPI import is triggered", so that this file still
  loads standalone on Python 3.11 for its unit tests. It still does. Anything
  new imported here has to be checked against that, not against the package it
  happens to live in.
* English only in prose; no em-dashes in any string. Money as Decimal-safe
  strings. Step LABELS are the deliberate exception: a country template derived
  from the regional table carries that table's own national terms,
  Baustellengemeinkosten and Mehrwertsteuer rather than English renderings of
  them, because a term translated on the way through is a second copy of it and
  the point of the derivation is that there is one. The bundled DejaVu PDF
  faces cover Latin, Greek and Cyrillic but not CJK; that limitation already
  applies to the bill exporter printing the same names and is not introduced
  here.

The rates below are sensible, clearly documented defaults, not regulated
figures: a methodology is fully editable in-app once installed, so a user can
adjust every percentage to their jurisdiction and date.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from app.modules.boq.markup_templates import REGION_BY_COUNTRY, region_lines_for_country

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.modules.methodology.cascade import CascadeSpec

__all__ = [
    "TEMPLATES",
    "TEMPLATES_BY_SLUG",
    "INTERNATIONAL_SLUG",
    "NEUTRAL_METHOD_NOTE",
    "list_templates",
    "get_template",
    "build_cascade_spec",
    "build_cascade_spec_from_template",
    "TemplateError",
]

# Slug of the neutral default methodology a project gets when it opts into the
# engine without picking a country. The existing flat international BOQMarkup
# path remains the platform-wide default for projects that never opt in at all.
INTERNATIONAL_SLUG = "international"


class TemplateError(ValueError):
    """Raised when a template cannot be resolved or built into a cascade spec.

    Subclasses :class:`ValueError` so callers catching ``ValueError`` still
    handle it, consistent with ``cascade.CascadeError`` / ``bases``.
    """


# ---------------------------------------------------------------------------
# Reusable building blocks
# ---------------------------------------------------------------------------
#
# The "western flat" tradition: direct cost (labor + materials + equipment +
# subcontract) carries an overhead percentage, then a profit percentage on
# (direct + overhead), then VAT on everything. This is the existing
# international method expressed in the cascade vocabulary so it can coexist as
# a first-class, fully data-driven methodology too.

# Resource-type tokens here are the canonical ones the BOQ resource normaliser
# emits (labor / material / equipment); a country template that needs a finer
# split (e.g. machinery distinct from installed equipment) declares its own
# resource types in base_mapping and the data simply has to use them.
_FLAT_BASE_MAPPING: dict[str, list[str]] = {
    "labor": ["labor"],
    "materials": ["material"],
    "equipment": ["equipment"],
    "subcontract": ["subcontractor"],
}
_FLAT_COMPOSITES: dict[str, list[str]] = {
    "direct": ["labor", "materials", "equipment", "subcontract"],
}


def _flat_steps(*, overhead: str, profit: str, vat: str) -> list[dict[str, Any]]:
    """Build the canonical flat cascade: overhead, profit, then VAT.

    Args:
        overhead: Overhead-and-general-conditions rate, percent, as a string.
        profit: Profit / margin rate, percent, as a string.
        vat: VAT rate, percent, as a string.

    Returns:
        Ordered list of serialized markup-step dicts. Overhead applies to the
        direct-cost composite; profit applies to direct cost plus the overhead
        step; VAT applies to direct cost plus both prior steps.
    """
    return [
        {
            "key": "overhead",
            "label": "Overhead and general conditions",
            "category": "overhead",
            "kind": "percentage",
            "rate": overhead,
            "amount": "0",
            "base": ["direct"],
        },
        {
            "key": "profit",
            "label": "Profit",
            "category": "profit",
            "kind": "percentage",
            "rate": profit,
            "amount": "0",
            "base": ["direct", "overhead"],
        },
        {
            "key": "vat",
            "label": "VAT",
            "category": "tax",
            "kind": "percentage",
            "rate": vat,
            "amount": "0",
            "base": ["direct", "overhead", "profit"],
        },
    ]


# A neutral two-level work breakdown used by the flat templates: a section
# header level and the work line under it. Switchable per methodology.
_FLAT_HIERARCHY: list[dict[str, Any]] = [
    {"key": "section", "label": "Section", "order": 0},
    {"key": "work", "label": "Work", "order": 1},
]

# The customer's 12 standard construction chapters ("Главы строительства" /
# ССР / CBS), seeded as a flat reference list of (code, label) pairs. Modelled
# as a dimension, NOT a hierarchy level, per the locked design. Editable
# in-app, and a pack may replace or extend it.
_CBS_CHAPTERS: list[dict[str, str]] = [
    {"code": "1", "label": "Site preparation"},
    {"code": "2", "label": "Main buildings and structures"},
    {"code": "3", "label": "Auxiliary buildings and structures"},
    {"code": "4", "label": "Energy facilities"},
    {"code": "5", "label": "Transport and communications facilities"},
    {"code": "6", "label": "External networks and utilities"},
    {"code": "7", "label": "Site improvement and landscaping"},
    {"code": "8", "label": "Temporary buildings and structures"},
    {"code": "9", "label": "Other works and costs"},
    {"code": "10", "label": "Maintenance of the developer / client"},
    {"code": "11", "label": "Training of operating personnel"},
    {"code": "12", "label": "Design and survey works"},
]

# Railway typed hierarchy: Section (peregon / station) -> Structure complex ->
# Object -> Work. This is the customer's requested breakdown, switchable.
_RAILWAY_HIERARCHY: list[dict[str, Any]] = [
    {"key": "section", "label": "Section", "order": 0},
    {"key": "complex", "label": "Structure complex", "order": 1},
    {"key": "object", "label": "Object", "order": 2},
    {"key": "work", "label": "Work", "order": 3},
]

# Railway / UZ resource split: construction machinery is part of SMR works,
# while installed equipment is a separate base that carries only some markups.
_CASCADE_BASE_MAPPING: dict[str, list[str]] = {
    "labor": ["labor"],
    "machinery": ["machinery"],
    "materials": ["material"],
    "equipment": ["equipment"],
}
_SMR_COMPOSITE: dict[str, list[str]] = {
    "SMR": ["labor", "machinery", "materials"],
}

# Mexican APU (analisis de precios unitarios) resource split: the costo directo
# integrates mano de obra (labor), materiales (materials) and maquinaria /
# herramienta (construction machinery plus installed equipment).
_APU_BASE_MAPPING: dict[str, list[str]] = {
    "mano_de_obra": ["labor"],
    "materiales": ["material"],
    "maquinaria": ["machinery", "equipment"],
}
_APU_COMPOSITE: dict[str, list[str]] = {
    "costo_directo": ["mano_de_obra", "materiales", "maquinaria"],
}

# Chilean APU resource split. Same three buckets as the Mexican one and a
# separate constant anyway, because the middle bucket is called equipos in
# Chile and these keys are what an estimator reads on the sheet. Sharing the
# Mexican constant would put "maquinaria" on a Chilean tender to save three
# lines, and would also mean a later change for one country silently moved the
# other.
_APU_CL_BASE_MAPPING: dict[str, list[str]] = {
    "mano_de_obra": ["labor"],
    "materiales": ["material"],
    "equipos": ["machinery", "equipment"],
}
_APU_CO_BASE_MAPPING: dict[str, list[str]] = {
    "materiales": ["material"],
    "mano_de_obra": ["labor"],
    "equipo_y_herramienta": ["machinery", "equipment"],
    "transporte": ["transport"],
}
_APU_CO_COMPOSITE: dict[str, list[str]] = {
    "costo_directo": ["materiales", "mano_de_obra", "equipo_y_herramienta", "transporte"],
}

_BDI_BR_BASE_MAPPING: dict[str, list[str]] = {
    "mao_de_obra": ["labor"],
    "materiais": ["material"],
    "equipamentos": ["machinery", "equipment"],
}
_BDI_BR_COMPOSITE: dict[str, list[str]] = {
    "custo_direto": ["mao_de_obra", "materiais", "equipamentos"],
}

_APU_CL_COMPOSITE: dict[str, list[str]] = {
    "costo_directo": ["mano_de_obra", "materiales", "equipos"],
}


def _section_type_dimension() -> dict[str, Any]:
    """Flat section-type reference dimension (extensible per the design)."""
    return {
        "key": "section_type",
        "label": "Section type",
        "kind": "flat",
        "is_required": False,
        "values": [
            {"code": "span", "label": "Span (peregon)"},
            {"code": "station", "label": "Station"},
            {"code": "junction", "label": "Junction"},
            {"code": "other", "label": "Other"},
        ],
    }


def _stage_dimension() -> dict[str, Any]:
    """Flat stage reference dimension (design / construction phases)."""
    return {
        "key": "stage",
        "label": "Stage",
        "kind": "flat",
        "is_required": False,
        "values": [
            {"code": "design", "label": "Design"},
            {"code": "procurement", "label": "Procurement"},
            {"code": "construction", "label": "Construction"},
            {"code": "commissioning", "label": "Commissioning"},
        ],
    }


def _cbs_dimension() -> dict[str, Any]:
    """The CBS "Chapters" dimension seeded from the 12 standard chapters."""
    return {
        "key": "cbs_chapter",
        "label": "Construction chapter (CBS)",
        "kind": "tree",
        "is_required": False,
        "values": [dict(ch) for ch in _CBS_CHAPTERS],
    }


# ---------------------------------------------------------------------------
# Industry building blocks (typed hierarchies, dimensions and the shared
# heavy-civil cascade). Each industry template below composes these with the
# SMR-vs-equipment or flat cascade already defined above, so a specialist
# estimator gets the right breakdown regardless of country. Every figure is an
# editable, clearly-labelled starting point once installed.
# ---------------------------------------------------------------------------

# Road and highway typed hierarchy: Route section (a chainage stretch) ->
# Structure (a discrete asset within it) -> Work line.
_ROAD_HIERARCHY: list[dict[str, Any]] = [
    {"key": "route_section", "label": "Route section", "order": 0},
    {"key": "structure", "label": "Structure", "order": 1},
    {"key": "work", "label": "Work", "order": 2},
]

# Bridge and structures typed hierarchy: Structure -> Span or Element -> Work.
_BRIDGE_HIERARCHY: list[dict[str, Any]] = [
    {"key": "structure", "label": "Structure", "order": 0},
    {"key": "span", "label": "Span or element", "order": 1},
    {"key": "work", "label": "Work", "order": 2},
]

# Utility network typed hierarchy (water, wastewater, power): Network ->
# Section or Asset -> Work. Shared by the linear-network industries.
_NETWORK_HIERARCHY: list[dict[str, Any]] = [
    {"key": "network", "label": "Network", "order": 0},
    {"key": "section", "label": "Section or asset", "order": 1},
    {"key": "work", "label": "Work", "order": 2},
]

# Building typed hierarchy: Building -> Level -> Work.
_BUILDING_HIERARCHY: list[dict[str, Any]] = [
    {"key": "building", "label": "Building", "order": 0},
    {"key": "level", "label": "Level", "order": 1},
    {"key": "work", "label": "Work", "order": 2},
]

# Process and industrial plant typed hierarchy: Area -> System -> Work.
_PLANT_HIERARCHY: list[dict[str, Any]] = [
    {"key": "area", "label": "Area", "order": 0},
    {"key": "system", "label": "System", "order": 1},
    {"key": "work", "label": "Work", "order": 2},
]

# Building services (MEP) typed hierarchy: System -> Zone -> Work.
_MEP_HIERARCHY: list[dict[str, Any]] = [
    {"key": "system", "label": "System", "order": 0},
    {"key": "zone", "label": "Zone", "order": 1},
    {"key": "work", "label": "Work", "order": 2},
]

# Tunnelling and underground typed hierarchy: Drive or bore -> Structure ->
# Work.
_TUNNEL_HIERARCHY: list[dict[str, Any]] = [
    {"key": "drive", "label": "Drive or bore", "order": 0},
    {"key": "structure", "label": "Structure", "order": 1},
    {"key": "work", "label": "Work", "order": 2},
]

# Earthworks and site development typed hierarchy: Zone -> Area -> Work.
_EARTHWORKS_HIERARCHY: list[dict[str, Any]] = [
    {"key": "zone", "label": "Zone", "order": 0},
    {"key": "area", "label": "Area", "order": 1},
    {"key": "work", "label": "Work", "order": 2},
]


def _flat_dimension(key: str, label: str, values: list[tuple[str, str]]) -> dict[str, Any]:
    """Build a flat reference dimension from (code, label) pairs.

    A small helper so each industry can declare its characteristic analytical
    dimension as data. All industry dimensions are optional (``is_required``
    False) and fully editable once the methodology is installed.
    """
    return {
        "key": key,
        "label": label,
        "kind": "flat",
        "is_required": False,
        "values": [{"code": code, "label": text} for code, text in values],
    }


def _pavement_layer_dimension() -> dict[str, Any]:
    """Road pavement layers, subgrade up to running surface."""
    return _flat_dimension(
        "pavement_layer",
        "Pavement layer",
        [
            ("subgrade", "Subgrade"),
            ("subbase", "Subbase"),
            ("base", "Base course"),
            ("binder", "Binder course"),
            ("surface", "Surface course"),
        ],
    )


def _bridge_element_dimension() -> dict[str, Any]:
    """Bridge structural elements, foundation up to deck furniture."""
    return _flat_dimension(
        "bridge_element",
        "Structural element",
        [
            ("foundation", "Foundation"),
            ("substructure", "Substructure"),
            ("superstructure", "Superstructure"),
            ("deck", "Deck"),
            ("bearings", "Bearings and joints"),
            ("finishes", "Waterproofing and finishes"),
        ],
    )


def _asset_type_dimension() -> dict[str, Any]:
    """Water and wastewater asset types."""
    return _flat_dimension(
        "asset_type",
        "Asset type",
        [
            ("pipeline", "Pipeline"),
            ("treatment", "Treatment plant"),
            ("pumping", "Pumping station"),
            ("storage", "Storage or reservoir"),
            ("chamber", "Chamber or manhole"),
        ],
    )


def _voltage_level_dimension() -> dict[str, Any]:
    """Power transmission and distribution voltage levels."""
    return _flat_dimension(
        "voltage_level",
        "Voltage level",
        [
            ("lv", "Low voltage"),
            ("mv", "Medium voltage"),
            ("hv", "High voltage"),
            ("ehv", "Extra high voltage"),
        ],
    )


def _discipline_dimension() -> dict[str, Any]:
    """Engineering disciplines for a process or industrial plant."""
    return _flat_dimension(
        "discipline",
        "Discipline",
        [
            ("civil", "Civil"),
            ("structural", "Structural"),
            ("mechanical", "Mechanical"),
            ("piping", "Piping"),
            ("electrical", "Electrical"),
            ("instrumentation", "Instrumentation and control"),
        ],
    )


def _mep_discipline_dimension() -> dict[str, Any]:
    """Building services (MEP) disciplines."""
    return _flat_dimension(
        "mep_discipline",
        "Services discipline",
        [
            ("mechanical", "Mechanical and HVAC"),
            ("electrical", "Electrical"),
            ("plumbing", "Plumbing and drainage"),
            ("fire", "Fire protection"),
            ("controls", "Controls and building management"),
        ],
    )


def _building_trade_dimension() -> dict[str, Any]:
    """Building trade packages, substructure through external works."""
    return _flat_dimension(
        "trade",
        "Trade package",
        [
            ("substructure", "Substructure"),
            ("superstructure", "Superstructure"),
            ("envelope", "Facade and envelope"),
            ("finishes", "Internal finishes"),
            ("services", "Building services"),
            ("external", "External works"),
        ],
    )


def _tunnel_method_dimension() -> dict[str, Any]:
    """Tunnelling construction methods."""
    return _flat_dimension(
        "tunnel_method",
        "Construction method",
        [
            ("bored", "Bored (mechanised)"),
            ("drill_blast", "Drill and blast"),
            ("cut_cover", "Cut and cover"),
            ("mined", "Sequential mined"),
        ],
    )


def _earthworks_type_dimension() -> dict[str, Any]:
    """Earthworks and site development operation types."""
    return _flat_dimension(
        "earthworks_type",
        "Earthworks operation",
        [
            ("clearing", "Site clearing"),
            ("excavation", "Excavation"),
            ("fill", "Fill and embankment"),
            ("compaction", "Compaction"),
            ("stabilisation", "Slope and stabilisation"),
        ],
    )


def _infra_cascade_steps(*, vat: str = "0") -> list[dict[str, Any]]:
    """The heavy-civil SMR-and-equipment cascade shared by infra industries.

    Mirrors the railway cascade: temporary/winter works and other contractor
    costs apply to SMR (labor, machinery, materials); a contingency reserve and
    VAT then apply to SMR plus installed equipment plus the prior steps. All
    rates default to a clearly-labelled, editable starting point.

    Args:
        vat: VAT rate, percent, as a string. Defaults to ``"0"`` because an
            industry template is country-neutral until installed.
    """
    return [
        {
            "key": "other_temp_winter",
            "label": "Temporary buildings and winter works",
            "category": "temp_winter",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": ["SMR"],
        },
        {
            "key": "contractor_other",
            "label": "Other contractor costs",
            "category": "contractor_other",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": ["SMR", "other_temp_winter"],
        },
        {
            "key": "contingency",
            "label": "Contingency reserve",
            "category": "contingency",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": ["SMR", "equipment", "other_temp_winter", "contractor_other"],
        },
        {
            "key": "vat",
            "label": "VAT",
            "category": "tax",
            "kind": "percentage",
            "rate": vat,
            "amount": "0",
            "base": [
                "SMR",
                "equipment",
                "other_temp_winter",
                "contractor_other",
                "contingency",
            ],
        },
    ]


# ---------------------------------------------------------------------------
# The template catalogue
# ---------------------------------------------------------------------------
#
# Country VAT rates and typical overhead/profit are documented defaults. They
# are intentionally round, clearly-labelled starting points, fully editable
# once installed - never presented as official regulated figures.

_INTERNATIONAL_TEMPLATE: dict[str, Any] = {
    "slug": INTERNATIONAL_SLUG,
    "name": "International (neutral)",
    "description": (
        "Neutral flat methodology: direct cost, then overhead, profit and VAT. "
        "A sensible default for any country before a local template is chosen."
    ),
    "country_code": None,
    "industry": None,
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _FLAT_HIERARCHY,
    "dimensions": [_stage_dimension()],
    "column_preset": None,
    "base_mapping": _FLAT_BASE_MAPPING,
    "composites": _FLAT_COMPOSITES,
    "cascade_steps": _flat_steps(overhead="12", profit="8", vat="0"),
    "vat_rate": "0",
}


def _flat_country_template(
    *,
    slug: str,
    name: str,
    country_code: str,
    currency: str,
    vat: str,
    overhead: str,
    profit: str,
    tax_label: str,
    decimals: int = 2,
    column_preset: str | None = None,
) -> dict[str, Any]:
    """Build a flat-method country template with country-typical defaults.

    Every country in the flat tradition differs only by its currency, its local
    consumption-tax name and rate, and its typical overhead / profit starting
    points. This builder captures that so each additional market is one readable
    line of data rather than a repeated fifteen-line dict, while producing the
    exact same schema the hand-written templates use.

    Three steps is not a national cost plan and this builder does not claim to
    write one. Where the regional markup table states a national convention,
    :func:`_reconcile_with_region_table` replaces what is built here with it;
    where it does not, the template ships as built and its description carries
    :data:`NEUTRAL_METHOD_NOTE` so nobody reads three steps as a country's own
    method. Bringing a market from the second class into the first means adding
    its stack to ``DEFAULT_MARKUP_TEMPLATES`` and its country to
    ``REGION_BY_COUNTRY``, not enriching the arguments here.

    Args:
        slug: Unique catalogue slug (snake_case).
        name: Display name (a country name, plain ASCII).
        country_code: ISO 3166-1 alpha-2 code, upper case.
        currency: ISO 4217 currency code, upper case.
        vat: Standard consumption-tax rate, percent, as a string.
        overhead: Overhead-and-general-conditions rate, percent, as a string.
        profit: Profit / margin rate, percent, as a string.
        tax_label: Local name of the consumption tax (e.g. ``"IVA"``, ``"GST"``),
            used only in the human description.
        decimals: Monetary display precision (0 for whole-unit currencies, 3 for
            the Kuwaiti dinar, 2 otherwise).
        column_preset: Named BOQ column preset, or ``None``.

    Returns:
        A template dict matching the catalogue schema.
    """
    return {
        "slug": slug,
        "name": name,
        "description": f"{name} flat estimate with overhead, profit and {tax_label}.",
        "country_code": country_code,
        "industry": None,
        "currency": currency,
        "decimals": decimals,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": column_preset,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead=overhead, profit=profit, vat=vat),
        "vat_rate": vat,
    }


# Seven popular countries. What is written here is the flat method with
# country-typical defaults, and for most of these seven it is not what ships:
# :func:`_reconcile_with_region_table` replaces the steps of any country the
# regional markup table covers, so what a user installs for Germany is the DACH
# stack, not the three lines below. The literals stay because they carry the
# currency, the decimals, the column preset and the VAT rate, which the regional
# table has no opinion about, and because a country can lose its regional
# coverage and needs something to fall back to.
_COUNTRY_TEMPLATES: list[dict[str, Any]] = [
    {
        "slug": "germany",
        "name": "Germany",
        "description": "German flat estimate with BGK overhead, profit and VAT.",
        "country_code": "DE",
        "industry": None,
        "currency": "EUR",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": "GAEB",
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="13", profit="6", vat="19"),
        "vat_rate": "19",
    },
    {
        "slug": "united_kingdom",
        "name": "United Kingdom",
        "description": "UK flat estimate with preliminaries, OHP and VAT.",
        "country_code": "GB",
        "industry": None,
        "currency": "GBP",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": "NRM2",
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="6", vat="20"),
        "vat_rate": "20",
    },
    {
        "slug": "united_states",
        "name": "United States",
        "description": (
            "US flat estimate with general conditions, overhead and profit. "
            "Sales tax varies by state, so the tax step defaults to zero."
        ),
        "country_code": "US",
        "industry": None,
        "currency": "USD",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": "CSI",
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="10", profit="10", vat="0"),
        "vat_rate": "0",
    },
    {
        "slug": "france",
        "name": "France",
        "description": "French flat estimate with site overhead, profit and TVA.",
        "country_code": "FR",
        "industry": None,
        "currency": "EUR",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="7", vat="20"),
        "vat_rate": "20",
    },
    {
        "slug": "united_arab_emirates",
        "name": "United Arab Emirates",
        "description": "UAE flat estimate with preliminaries, profit and VAT.",
        "country_code": "AE",
        "industry": None,
        "currency": "AED",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="5"),
        "vat_rate": "5",
    },
    {
        "slug": "india",
        "name": "India",
        "description": "Indian flat estimate with overhead, profit and GST.",
        "country_code": "IN",
        "industry": None,
        "currency": "INR",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="10", profit="10", vat="18"),
        "vat_rate": "18",
    },
    {
        "slug": "australia",
        "name": "Australia",
        "description": "Australian flat estimate with preliminaries, margin and GST.",
        "country_code": "AU",
        "industry": None,
        "currency": "AUD",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="10"),
        "vat_rate": "10",
    },
    {
        "slug": "canada",
        "name": "Canada",
        "description": (
            "Canadian flat estimate with general conditions, overhead and profit. "
            "Sales tax (GST/HST) varies by province, so the tax step defaults low."
        ),
        "country_code": "CA",
        "industry": None,
        "currency": "CAD",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": "CSI",
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="10", profit="10", vat="5"),
        "vat_rate": "5",
    },
    {
        "slug": "spain",
        "name": "Spain",
        "description": "Spanish flat estimate with overhead (gastos generales), profit and IVA.",
        "country_code": "ES",
        "industry": None,
        "currency": "EUR",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="13", profit="6", vat="21"),
        "vat_rate": "21",
    },
    {
        "slug": "italy",
        "name": "Italy",
        "description": "Italian flat estimate with site overhead, profit and IVA.",
        "country_code": "IT",
        "industry": None,
        "currency": "EUR",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="15", profit="10", vat="22"),
        "vat_rate": "22",
    },
    {
        "slug": "netherlands",
        "name": "Netherlands",
        "description": "Dutch flat estimate with overhead (AK), profit and BTW.",
        "country_code": "NL",
        "industry": None,
        "currency": "EUR",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="8", profit="5", vat="21"),
        "vat_rate": "21",
    },
    {
        "slug": "poland",
        "name": "Poland",
        "description": "Polish flat estimate with overhead (koszty posrednie), profit and VAT.",
        "country_code": "PL",
        "industry": None,
        "currency": "PLN",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="23"),
        "vat_rate": "23",
    },
    {
        "slug": "austria",
        "name": "Austria",
        "description": "Austrian flat estimate with site overhead, profit and USt.",
        "country_code": "AT",
        "industry": None,
        "currency": "EUR",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": "ONORM",
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="20"),
        "vat_rate": "20",
    },
    {
        "slug": "switzerland",
        "name": "Switzerland",
        "description": "Swiss flat estimate with overhead, profit and MWST.",
        "country_code": "CH",
        "industry": None,
        "currency": "CHF",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="8.1"),
        "vat_rate": "8.1",
    },
    {
        "slug": "sweden",
        "name": "Sweden",
        "description": "Swedish flat estimate with overhead, profit and moms.",
        "country_code": "SE",
        "industry": None,
        "currency": "SEK",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="10", profit="7", vat="25"),
        "vat_rate": "25",
    },
    {
        "slug": "norway",
        "name": "Norway",
        "description": "Norwegian flat estimate with overhead, profit and MVA.",
        "country_code": "NO",
        "industry": None,
        "currency": "NOK",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="25"),
        "vat_rate": "25",
    },
    {
        "slug": "brazil",
        "name": "Brazil",
        "description": (
            "Brazilian flat estimate with indirect costs and profit (the BDI "
            "tradition). Taxes vary by municipality and regime, so the tax step "
            "defaults to zero."
        ),
        "country_code": "BR",
        "industry": None,
        "currency": "BRL",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="18", profit="8", vat="0"),
        "vat_rate": "0",
    },
    {
        "slug": "saudi_arabia",
        "name": "Saudi Arabia",
        "description": "Saudi flat estimate with preliminaries, profit and VAT.",
        "country_code": "SA",
        "industry": None,
        "currency": "SAR",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="15"),
        "vat_rate": "15",
    },
    {
        "slug": "south_africa",
        "name": "South Africa",
        "description": "South African flat estimate with preliminaries, profit and VAT.",
        "country_code": "ZA",
        "industry": None,
        "currency": "ZAR",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="15"),
        "vat_rate": "15",
    },
    {
        "slug": "china",
        "name": "China",
        "description": "Chinese flat estimate with overhead, profit and VAT.",
        "country_code": "CN",
        "industry": None,
        "currency": "CNY",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="10", profit="7", vat="9"),
        "vat_rate": "9",
    },
    {
        "slug": "japan",
        "name": "Japan",
        "description": "Japanese flat estimate with site overhead, profit and consumption tax.",
        "country_code": "JP",
        "industry": None,
        "currency": "JPY",
        "decimals": 0,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="10"),
        "vat_rate": "10",
    },
    {
        "slug": "south_korea",
        "name": "South Korea",
        "description": "Korean flat estimate with overhead, profit and VAT.",
        "country_code": "KR",
        "industry": None,
        "currency": "KRW",
        "decimals": 0,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="12", profit="8", vat="10"),
        "vat_rate": "10",
    },
    {
        "slug": "singapore",
        "name": "Singapore",
        "description": "Singapore flat estimate with preliminaries, profit and GST.",
        "country_code": "SG",
        "industry": None,
        "currency": "SGD",
        "decimals": 2,
        "hierarchy_levels": _FLAT_HIERARCHY,
        "dimensions": [_stage_dimension()],
        "column_preset": None,
        "base_mapping": _FLAT_BASE_MAPPING,
        "composites": _FLAT_COMPOSITES,
        "cascade_steps": _flat_steps(overhead="10", profit="8", vat="9"),
        "vat_rate": "9",
    },
]

# Broader international coverage: additional major construction markets across
# Europe, the Middle East, Africa, Asia-Pacific and Latin America. Each follows
# the same flat method with country-typical, editable starting points. Decimals
# reflect the currency's real minor unit (0 for whole-unit currencies such as
# the Indonesian rupiah and Chilean peso, 3 for the Kuwaiti dinar).
_MORE_COUNTRY_TEMPLATES: list[dict[str, Any]] = [
    # Europe (and the European-facing part of the Turkish market).
    _flat_country_template(
        slug="turkey",
        name="Turkey",
        country_code="TR",
        currency="TRY",
        vat="20",
        overhead="12",
        profit="8",
        tax_label="KDV",
    ),
    _flat_country_template(
        slug="portugal",
        name="Portugal",
        country_code="PT",
        currency="EUR",
        vat="23",
        overhead="13",
        profit="6",
        tax_label="IVA",
    ),
    _flat_country_template(
        slug="belgium",
        name="Belgium",
        country_code="BE",
        currency="EUR",
        vat="21",
        overhead="12",
        profit="7",
        tax_label="BTW",
    ),
    _flat_country_template(
        slug="ireland",
        name="Ireland",
        country_code="IE",
        currency="EUR",
        vat="23",
        overhead="12",
        profit="7",
        tax_label="VAT",
    ),
    _flat_country_template(
        slug="denmark",
        name="Denmark",
        country_code="DK",
        currency="DKK",
        vat="25",
        overhead="10",
        profit="7",
        tax_label="moms",
    ),
    _flat_country_template(
        slug="finland",
        name="Finland",
        country_code="FI",
        currency="EUR",
        vat="25.5",
        overhead="11",
        profit="7",
        tax_label="ALV",
    ),
    _flat_country_template(
        slug="greece",
        name="Greece",
        country_code="GR",
        currency="EUR",
        vat="24",
        overhead="13",
        profit="8",
        tax_label="VAT",
    ),
    _flat_country_template(
        slug="czechia",
        name="Czechia",
        country_code="CZ",
        currency="CZK",
        vat="21",
        overhead="12",
        profit="8",
        tax_label="DPH",
    ),
    _flat_country_template(
        slug="romania",
        name="Romania",
        country_code="RO",
        currency="RON",
        # 21 % since 1 August 2025; see ROMANIA_VAT_SOURCES in
        # app/modules/i18n_foundation/romania_vat.py. Editing this literal
        # changes what a *new* installation of the template carries. Project
        # methodologies already cloned from it keep their own ``vat_rate``
        # column and are not healed by this line.
        vat="21",
        overhead="12",
        profit="8",
        tax_label="TVA",
    ),
    _flat_country_template(
        slug="hungary",
        name="Hungary",
        country_code="HU",
        currency="HUF",
        vat="27",
        overhead="12",
        profit="8",
        tax_label="AFA",
        decimals=0,
    ),
    # Russia. The rates written here are the fallback and are not what ships:
    # the regional table states the national stack (НР, СП, unforeseen costs,
    # НДС) and :func:`_reconcile_with_region_table` replaces these three steps
    # with it. What this literal carries that the table has no opinion about is
    # the currency and the tax rate. Russia had no template at all until now,
    # which is why the national stack had nothing to be reconciled into.
    _flat_country_template(
        slug="russia",
        name="Russia",
        country_code="RU",
        currency="RUB",
        # 22 % since 1 January 2026, up from 20 %; the dated windows are in
        # seed_data/tax_configurations.json. As with Romania above, editing
        # this literal changes what a *new* installation of the template
        # carries. Project methodologies already cloned from it keep their own
        # ``vat_rate`` column and are not healed by this line.
        vat="22",
        overhead="16",
        profit="7",
        tax_label="NDS",
    ),
    # Middle East.
    _flat_country_template(
        slug="qatar",
        name="Qatar",
        country_code="QA",
        currency="QAR",
        vat="0",
        overhead="12",
        profit="8",
        tax_label="VAT",
    ),
    _flat_country_template(
        slug="kuwait",
        name="Kuwait",
        country_code="KW",
        currency="KWD",
        vat="0",
        overhead="12",
        profit="8",
        tax_label="VAT",
        decimals=3,
    ),
    _flat_country_template(
        slug="egypt",
        name="Egypt",
        country_code="EG",
        currency="EGP",
        vat="14",
        overhead="13",
        profit="10",
        tax_label="VAT",
    ),
    _flat_country_template(
        slug="israel",
        name="Israel",
        country_code="IL",
        currency="ILS",
        vat="18",
        overhead="12",
        profit="8",
        tax_label="VAT",
    ),
    # Africa.
    _flat_country_template(
        slug="nigeria",
        name="Nigeria",
        country_code="NG",
        currency="NGN",
        vat="7.5",
        overhead="12",
        profit="10",
        tax_label="VAT",
    ),
    _flat_country_template(
        slug="kenya",
        name="Kenya",
        country_code="KE",
        currency="KES",
        vat="16",
        overhead="12",
        profit="10",
        tax_label="VAT",
    ),
    _flat_country_template(
        slug="morocco",
        name="Morocco",
        country_code="MA",
        currency="MAD",
        vat="20",
        overhead="12",
        profit="8",
        tax_label="TVA",
    ),
    # Asia-Pacific.
    _flat_country_template(
        slug="indonesia",
        name="Indonesia",
        country_code="ID",
        currency="IDR",
        vat="11",
        overhead="12",
        profit="10",
        tax_label="PPN",
        decimals=0,
    ),
    _flat_country_template(
        slug="vietnam",
        name="Vietnam",
        country_code="VN",
        currency="VND",
        vat="10",
        overhead="10",
        profit="8",
        tax_label="VAT",
        decimals=0,
    ),
    _flat_country_template(
        slug="malaysia",
        name="Malaysia",
        country_code="MY",
        currency="MYR",
        vat="6",
        overhead="12",
        profit="8",
        tax_label="SST",
    ),
    _flat_country_template(
        slug="thailand",
        name="Thailand",
        country_code="TH",
        currency="THB",
        vat="7",
        overhead="12",
        profit="8",
        tax_label="VAT",
    ),
    _flat_country_template(
        slug="philippines",
        name="Philippines",
        country_code="PH",
        currency="PHP",
        vat="12",
        overhead="12",
        profit="10",
        tax_label="VAT",
    ),
    _flat_country_template(
        slug="new_zealand",
        name="New Zealand",
        country_code="NZ",
        currency="NZD",
        vat="15",
        overhead="12",
        profit="8",
        tax_label="GST",
    ),
    # Latin America.
    _flat_country_template(
        slug="argentina",
        name="Argentina",
        country_code="AR",
        currency="ARS",
        vat="21",
        overhead="15",
        profit="8",
        tax_label="IVA",
    ),
    _flat_country_template(
        slug="chile",
        name="Chile",
        country_code="CL",
        currency="CLP",
        vat="19",
        overhead="13",
        profit="8",
        tax_label="IVA",
        decimals=0,
    ),
    _flat_country_template(
        slug="colombia",
        name="Colombia",
        country_code="CO",
        currency="COP",
        vat="19",
        overhead="15",
        profit="8",
        tax_label="IVA",
        decimals=0,
    ),
    _flat_country_template(
        slug="peru",
        name="Peru",
        country_code="PE",
        currency="PEN",
        vat="18",
        overhead="14",
        profit="8",
        tax_label="IGV",
    ),
]

# The Uzbekistan cascading methodology - the canonical reference cascade from
# the design doc (section 5). SMR = labor + machinery + materials; installed
# equipment is a separate base that skips the SMR-only winter/contractor steps
# but still carries insurance, contingency and VAT.
#
# The first two steps default to zero rate so the cascade is correct out of the
# box (those rates are project-specific seasonal / contractual figures the user
# fills in); insurance (0.32 percent) and VAT (12 percent) are the stable,
# well-known figures.
_UZBEKISTAN_TEMPLATE: dict[str, Any] = {
    "slug": "uzbekistan",
    "name": "Uzbekistan (cascading)",
    "description": (
        "Uzbekistan cascading methodology. SMR (labor, machinery, materials) "
        "and installed equipment are distinct bases; markups cascade through "
        "temporary/winter, contractor, insurance, contingency and VAT."
    ),
    "country_code": "UZ",
    "industry": None,
    "currency": "UZS",
    "decimals": 2,
    "hierarchy_levels": _RAILWAY_HIERARCHY,
    "dimensions": [
        _cbs_dimension(),
        _section_type_dimension(),
        _stage_dimension(),
    ],
    "column_preset": None,
    "base_mapping": _CASCADE_BASE_MAPPING,
    "composites": _SMR_COMPOSITE,
    "cascade_steps": [
        {
            "key": "other_temp_winter",
            "label": "Temporary buildings and winter works",
            "category": "temp_winter",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": ["SMR"],
        },
        {
            "key": "contractor_other",
            "label": "Other contractor costs",
            "category": "contractor_other",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": ["SMR", "other_temp_winter"],
        },
        {
            "key": "insurance",
            "label": "Insurance",
            "category": "insurance",
            "kind": "percentage",
            "rate": "0.32",
            "amount": "0",
            "base": ["SMR", "equipment", "other_temp_winter", "contractor_other"],
        },
        {
            "key": "contingency",
            "label": "Contingency reserve",
            "category": "contingency",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": [
                "SMR",
                "equipment",
                "other_temp_winter",
                "contractor_other",
                "insurance",
            ],
        },
        {
            "key": "vat",
            "label": "VAT",
            "category": "tax",
            "kind": "percentage",
            "rate": "12",
            "amount": "0",
            "base": [
                "SMR",
                "equipment",
                "other_temp_winter",
                "contractor_other",
                "insurance",
                "contingency",
            ],
        },
    ],
    "vat_rate": "12",
}

# The Mexican APU (analisis de precios unitarios) cascading methodology. The
# costo directo (mano de obra, materiales, maquinaria) carries, in order,
# indirectos, financiamiento, utilidad and cargos adicionales, then IVA, exactly
# the integration order the LOPSRM reglamento prescribes for a precio unitario.
#
# Indirectos, financiamiento, utilidad and cargos adicionales default to clear,
# round, editable starting points (the cinco al millar inspection fee is the
# usual content of cargos adicionales, hence 0.5 percent); IVA is the stable
# 16 percent standard rate. Every figure is editable in-app once installed.
_MEXICO_TEMPLATE: dict[str, Any] = {
    "slug": "mexico",
    "name": "Mexico (APU)",
    "description": (
        "Mexican analisis de precios unitarios. Costo directo (mano de obra, "
        "materiales, maquinaria) carries indirectos, financiamiento, utilidad "
        "and cargos adicionales in turn, then IVA, per the LOPSRM reglamento."
    ),
    "country_code": "MX",
    "industry": None,
    "currency": "MXN",
    "decimals": 2,
    "hierarchy_levels": _FLAT_HIERARCHY,
    "dimensions": [_stage_dimension()],
    "column_preset": None,
    "base_mapping": _APU_BASE_MAPPING,
    "composites": _APU_COMPOSITE,
    "cascade_steps": [
        {
            "key": "indirectos",
            "label": "Indirectos",
            "category": "overhead",
            "kind": "percentage",
            "rate": "15",
            "amount": "0",
            "base": ["costo_directo"],
        },
        {
            "key": "financiamiento",
            "label": "Financiamiento",
            "category": "financing",
            "kind": "percentage",
            "rate": "1",
            "amount": "0",
            "base": ["costo_directo", "indirectos"],
        },
        {
            "key": "utilidad",
            "label": "Utilidad",
            "category": "profit",
            "kind": "percentage",
            "rate": "10",
            "amount": "0",
            "base": ["costo_directo", "indirectos", "financiamiento"],
        },
        {
            "key": "cargos_adicionales",
            "label": "Cargos adicionales",
            "category": "additional",
            "kind": "percentage",
            "rate": "0.5",
            "amount": "0",
            "base": ["costo_directo", "indirectos", "financiamiento", "utilidad"],
        },
        {
            "key": "iva",
            "label": "IVA",
            "category": "tax",
            "kind": "percentage",
            "rate": "16",
            "amount": "0",
            "base": [
                "costo_directo",
                "indirectos",
                "financiamiento",
                "utilidad",
                "cargos_adicionales",
            ],
        },
    ],
    "vat_rate": "16",
}

# Chilean APU. A Chilean public tender is submitted as an analisis de precio
# unitario, not as one marked-up rate: the itemised costo directo carries gastos
# generales and then utilidades, and the sum of those three is the precio
# unitario the bid is compared on. IVA sits outside it. The flat Chile template
# further up reaches the same total by a different road, which is fine for an
# internal budget and is not what a public client will accept as the analysis.
#
# The rates here are the same starting points the flat Chile template already
# shipped, deliberately: what a contractor needs from us is the cascade, its
# order and each step's base, because those are what the client dictates. The
# percentages are theirs and are meant to be edited on the first project.
#
# Imprevistos starts at zero. Tenders that carry a contingency put it on the
# costo directo before utilidades, and tenders that do not carry one would have
# to notice a line we invented and remove it, so the line exists and is empty
# rather than absent or guessed.
_CHILE_APU_TEMPLATE: dict[str, Any] = {
    "slug": "chile_apu",
    "name": "Chile (APU)",
    "description": (
        "Chilean analisis de precio unitario. Costo directo (mano de obra, "
        "materiales, equipos) carries imprevistos, gastos generales and "
        "utilidades in turn to the precio unitario, then IVA 19 percent per "
        "Ley sobre Impuesto a las Ventas y Servicios."
    ),
    "country_code": "CL",
    "industry": None,
    "currency": "CLP",
    # The peso has no minor unit. A cascade that displays cents on a tendered
    # rate is reporting precision the currency does not have.
    "decimals": 0,
    "hierarchy_levels": _FLAT_HIERARCHY,
    "dimensions": [_stage_dimension()],
    "column_preset": None,
    "base_mapping": _APU_CL_BASE_MAPPING,
    "composites": _APU_CL_COMPOSITE,
    "cascade_steps": [
        {
            "key": "imprevistos",
            "label": "Imprevistos",
            "category": "contingency",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": ["costo_directo"],
        },
        {
            "key": "gastos_generales",
            "label": "Gastos generales",
            "category": "overhead",
            "kind": "percentage",
            "rate": "13",
            "amount": "0",
            "base": ["costo_directo", "imprevistos"],
        },
        {
            "key": "utilidades",
            "label": "Utilidades",
            "category": "profit",
            "kind": "percentage",
            "rate": "8",
            "amount": "0",
            "base": ["costo_directo", "imprevistos", "gastos_generales"],
        },
        {
            "key": "iva",
            "label": "IVA",
            "category": "tax",
            "kind": "percentage",
            "rate": "19",
            "amount": "0",
            "base": [
                "costo_directo",
                "imprevistos",
                "gastos_generales",
                "utilidades",
            ],
        },
    ],
    "vat_rate": "19",
}

# Colombian AIU. Administracion, Imprevistos, Utilidad: the three letters a
# Colombian contract quotes its markup as, and the reason this cannot reuse the
# Chilean shape. Each of the three is a share OF THE COSTO DIRECTO, not of the
# running total, so nothing here compounds. "AIU 27% (A=20, I=2, U=5)" on a
# tender means exactly that, and a cascade that compounded them would quote a
# number the client did not ask for.
#
# IVA is the other half of the difference. For a construction contract on
# immovable property the base is the utilidad alone, not the contract value, per
# Decreto 1372 de 1992. On the figures below that is 19 percent of 5 percent
# rather than of 127 percent, and getting it wrong is not a rounding matter.
_COLOMBIA_AIU_TEMPLATE: dict[str, Any] = {
    "slug": "colombia_aiu",
    "name": "Colombia (AIU)",
    "description": (
        "Colombian analisis de precios unitarios with AIU. Administracion, "
        "imprevistos and utilidad are each taken on the costo directo, and IVA "
        "19 percent falls on the utilidad alone, as a construction contract on "
        "immovable property is taxed."
    ),
    "country_code": "CO",
    "industry": None,
    "currency": "COP",
    # Matches the flat Colombia template already shipped: the peso is quoted in
    # whole units on a bill of quantities.
    "decimals": 0,
    "hierarchy_levels": _FLAT_HIERARCHY,
    "dimensions": [_stage_dimension()],
    "column_preset": None,
    "base_mapping": _APU_CO_BASE_MAPPING,
    "composites": _APU_CO_COMPOSITE,
    "cascade_steps": [
        {
            "key": "administracion",
            "label": "Administracion",
            "category": "overhead",
            "kind": "percentage",
            "rate": "20",
            "amount": "0",
            "base": ["costo_directo"],
        },
        {
            "key": "imprevistos",
            "label": "Imprevistos",
            "category": "contingency",
            "kind": "percentage",
            "rate": "2",
            "amount": "0",
            "base": ["costo_directo"],
        },
        {
            "key": "utilidad",
            "label": "Utilidad",
            "category": "profit",
            "kind": "percentage",
            "rate": "5",
            "amount": "0",
            "base": ["costo_directo"],
        },
        {
            "key": "iva",
            "label": "IVA sobre la utilidad",
            "category": "tax",
            "kind": "percentage",
            "rate": "19",
            "amount": "0",
            "base": ["utilidad"],
        },
    ],
    "vat_rate": "19",
}

# Brazilian BDI, Beneficios e Despesas Indiretas, composed the way the federal
# audit court sets it out in Acordao 2622/2013:
#
#     BDI = [(1 + AC + S + R + G)(1 + DF)(1 + L) / (1 - I)] - 1
#
# Three shapes in one formula, and the steps below are that formula read left to
# right. Administracao central, seguros, garantias and riscos share a bracket,
# so each is a share of the custo direto and none of them sees the others.
# Despesas financeiras and lucro are their own factors, so each applies to
# everything before it. Tributos divide rather than multiply, which is what the
# gross_up kind exists for: PIS, COFINS and ISS are levied on the invoiced
# amount, so the amount they are levied on already contains them.
#
# The tax rate is one line and not three because all of them sit in the same
# denominator; three sequential steps would compound a thing that does not
# compound. ISS is municipal and runs 2 to 5 percent, so the 8.65 below (PIS
# 0.65, COFINS 3.00, ISS 5.00) is the common ceiling case and is meant to be
# set to the city the job is in.
_BRAZIL_BDI_TEMPLATE: dict[str, Any] = {
    "slug": "brazil_bdi",
    "name": "Brasil (BDI)",
    "description": (
        "Brazilian BDI composed per TCU Acordao 2622/2013. Administracao "
        "central, seguros, garantias and riscos on the custo direto, then "
        "despesas financeiras and lucro in turn, then PIS, COFINS and ISS "
        "grossed up because they are charged on the invoiced amount."
    ),
    "country_code": "BR",
    "industry": None,
    "currency": "BRL",
    "decimals": 2,
    "hierarchy_levels": _FLAT_HIERARCHY,
    "dimensions": [_stage_dimension()],
    "column_preset": None,
    "base_mapping": _BDI_BR_BASE_MAPPING,
    "composites": _BDI_BR_COMPOSITE,
    "cascade_steps": [
        {
            "key": "administracao_central",
            "label": "Administracao central",
            "category": "overhead",
            "kind": "percentage",
            "rate": "4",
            "amount": "0",
            "base": ["custo_direto"],
        },
        {
            "key": "seguros_e_garantias",
            "label": "Seguros e garantias",
            "category": "insurance",
            "kind": "percentage",
            "rate": "0.8",
            "amount": "0",
            "base": ["custo_direto"],
        },
        {
            "key": "riscos",
            "label": "Riscos",
            "category": "contingency",
            "kind": "percentage",
            "rate": "1.27",
            "amount": "0",
            "base": ["custo_direto"],
        },
        {
            "key": "despesas_financeiras",
            "label": "Despesas financeiras",
            "category": "other",
            "kind": "percentage",
            "rate": "1.23",
            "amount": "0",
            "base": ["custo_direto", "administracao_central", "seguros_e_garantias", "riscos"],
        },
        {
            "key": "lucro",
            "label": "Lucro",
            "category": "profit",
            "kind": "percentage",
            "rate": "7.4",
            "amount": "0",
            "base": [
                "custo_direto",
                "administracao_central",
                "seguros_e_garantias",
                "riscos",
                "despesas_financeiras",
            ],
        },
        {
            "key": "tributos",
            "label": "Tributos (PIS, COFINS, ISS)",
            "category": "tax",
            "kind": "gross_up",
            "rate": "8.65",
            "amount": "0",
            "base": [
                "custo_direto",
                "administracao_central",
                "seguros_e_garantias",
                "riscos",
                "despesas_financeiras",
                "lucro",
            ],
        },
    ],
    # Brazil has no VAT. Consumption tax on a construction service is ISS,
    # municipal, and it is already inside the tributos step above.
    "vat_rate": "0",
}

# Railway-infrastructure industry template. Country-neutral (currency blank,
# VAT a placeholder step) but ships the full railway typed hierarchy plus the
# CBS / section-type / stage dimensions and the SMR-vs-equipment cascade, so an
# infrastructure estimator gets the right structure regardless of country.
_RAILWAY_TEMPLATE: dict[str, Any] = {
    "slug": "railway_infrastructure",
    "name": "Railway infrastructure",
    "description": (
        "Railway-infrastructure industry methodology: Section, Structure "
        "complex, Object and Work levels; CBS chapters, section-type and "
        "stage dimensions; SMR and installed-equipment cascade."
    ),
    "country_code": None,
    "industry": "railway",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _RAILWAY_HIERARCHY,
    "dimensions": [
        _cbs_dimension(),
        _section_type_dimension(),
        _stage_dimension(),
    ],
    "column_preset": None,
    "base_mapping": _CASCADE_BASE_MAPPING,
    "composites": _SMR_COMPOSITE,
    "cascade_steps": [
        {
            "key": "other_temp_winter",
            "label": "Temporary buildings and winter works",
            "category": "temp_winter",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": ["SMR"],
        },
        {
            "key": "contractor_other",
            "label": "Other contractor costs",
            "category": "contractor_other",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": ["SMR", "other_temp_winter"],
        },
        {
            "key": "contingency",
            "label": "Contingency reserve",
            "category": "contingency",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": ["SMR", "equipment", "other_temp_winter", "contractor_other"],
        },
        {
            "key": "vat",
            "label": "VAT",
            "category": "tax",
            "kind": "percentage",
            "rate": "0",
            "amount": "0",
            "base": [
                "SMR",
                "equipment",
                "other_temp_winter",
                "contractor_other",
                "contingency",
            ],
        },
    ],
    "vat_rate": None,
}


# Industry-infrastructure templates. Each is country-neutral (currency blank,
# VAT a placeholder step) but ships a sector-specific typed hierarchy and the
# characteristic analytical dimension for that sector, so a specialist
# estimator gets the right structure regardless of country. The heavy-civil
# sectors use the SMR-and-installed-equipment cascade; buildings and services
# use the flat direct-cost cascade.
_ROAD_TEMPLATE: dict[str, Any] = {
    "slug": "road_highway",
    "name": "Roads and highways",
    "description": (
        "Road and highway methodology: Route section, Structure and Work "
        "levels; pavement-layer and stage dimensions; SMR and installed-"
        "equipment cascade for a machinery-intensive sector."
    ),
    "country_code": None,
    "industry": "road",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _ROAD_HIERARCHY,
    "dimensions": [_pavement_layer_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _CASCADE_BASE_MAPPING,
    "composites": _SMR_COMPOSITE,
    "cascade_steps": _infra_cascade_steps(),
    "vat_rate": None,
}

_BRIDGE_TEMPLATE: dict[str, Any] = {
    "slug": "bridge_structures",
    "name": "Bridges and structures",
    "description": (
        "Bridge and structures methodology: Structure, Span or element and "
        "Work levels; structural-element and stage dimensions; SMR and "
        "installed-equipment cascade."
    ),
    "country_code": None,
    "industry": "bridge",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _BRIDGE_HIERARCHY,
    "dimensions": [_bridge_element_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _CASCADE_BASE_MAPPING,
    "composites": _SMR_COMPOSITE,
    "cascade_steps": _infra_cascade_steps(),
    "vat_rate": None,
}

_WATER_TEMPLATE: dict[str, Any] = {
    "slug": "water_wastewater",
    "name": "Water and wastewater",
    "description": (
        "Water and wastewater networks methodology: Network, Section or asset "
        "and Work levels; asset-type and stage dimensions; SMR and installed-"
        "equipment cascade."
    ),
    "country_code": None,
    "industry": "water",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _NETWORK_HIERARCHY,
    "dimensions": [_asset_type_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _CASCADE_BASE_MAPPING,
    "composites": _SMR_COMPOSITE,
    "cascade_steps": _infra_cascade_steps(),
    "vat_rate": None,
}

_POWER_TEMPLATE: dict[str, Any] = {
    "slug": "power_transmission",
    "name": "Power transmission and distribution",
    "description": (
        "Power transmission and distribution methodology: Network, Section or "
        "asset and Work levels; voltage-level and stage dimensions; SMR plus a "
        "distinct installed-equipment base for transformers and switchgear."
    ),
    "country_code": None,
    "industry": "power",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _NETWORK_HIERARCHY,
    "dimensions": [_voltage_level_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _CASCADE_BASE_MAPPING,
    "composites": _SMR_COMPOSITE,
    "cascade_steps": _infra_cascade_steps(),
    "vat_rate": None,
}

_TUNNEL_TEMPLATE: dict[str, Any] = {
    "slug": "tunnel_underground",
    "name": "Tunnelling and underground",
    "description": (
        "Tunnelling and underground methodology: Drive or bore, Structure and "
        "Work levels; construction-method and stage dimensions; SMR and "
        "installed-equipment cascade."
    ),
    "country_code": None,
    "industry": "tunnel",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _TUNNEL_HIERARCHY,
    "dimensions": [_tunnel_method_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _CASCADE_BASE_MAPPING,
    "composites": _SMR_COMPOSITE,
    "cascade_steps": _infra_cascade_steps(),
    "vat_rate": None,
}

_EARTHWORKS_TEMPLATE: dict[str, Any] = {
    "slug": "earthworks_sitework",
    "name": "Earthworks and site development",
    "description": (
        "Earthworks and site development methodology: Zone, Area and Work "
        "levels; earthworks-operation and stage dimensions; SMR and installed-"
        "equipment cascade for a plant-intensive sector."
    ),
    "country_code": None,
    "industry": "earthworks",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _EARTHWORKS_HIERARCHY,
    "dimensions": [_earthworks_type_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _CASCADE_BASE_MAPPING,
    "composites": _SMR_COMPOSITE,
    "cascade_steps": _infra_cascade_steps(),
    "vat_rate": None,
}

_PLANT_TEMPLATE: dict[str, Any] = {
    "slug": "industrial_plant",
    "name": "Industrial and process plant",
    "description": (
        "Industrial and process plant methodology: Area, System and Work "
        "levels; discipline and stage dimensions; SMR plus a distinct "
        "installed-equipment base for process equipment."
    ),
    "country_code": None,
    "industry": "industrial",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _PLANT_HIERARCHY,
    "dimensions": [_discipline_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _CASCADE_BASE_MAPPING,
    "composites": _SMR_COMPOSITE,
    "cascade_steps": _infra_cascade_steps(),
    "vat_rate": None,
}

_RESIDENTIAL_TEMPLATE: dict[str, Any] = {
    "slug": "building_residential",
    "name": "Residential buildings",
    "description": (
        "Residential building methodology: Building, Level and Work levels; "
        "trade-package and stage dimensions; flat direct-cost cascade with "
        "overhead, profit and a placeholder VAT step."
    ),
    "country_code": None,
    "industry": "residential",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _BUILDING_HIERARCHY,
    "dimensions": [_building_trade_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _FLAT_BASE_MAPPING,
    "composites": _FLAT_COMPOSITES,
    "cascade_steps": _flat_steps(overhead="12", profit="8", vat="0"),
    "vat_rate": None,
}

_COMMERCIAL_TEMPLATE: dict[str, Any] = {
    "slug": "building_commercial",
    "name": "Commercial buildings",
    "description": (
        "Commercial and office building methodology: Building, Level and Work "
        "levels; trade-package and stage dimensions; flat direct-cost cascade "
        "with overhead, profit and a placeholder VAT step."
    ),
    "country_code": None,
    "industry": "commercial",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _BUILDING_HIERARCHY,
    "dimensions": [_building_trade_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _FLAT_BASE_MAPPING,
    "composites": _FLAT_COMPOSITES,
    "cascade_steps": _flat_steps(overhead="13", profit="8", vat="0"),
    "vat_rate": None,
}

_MEP_TEMPLATE: dict[str, Any] = {
    "slug": "mep_systems",
    "name": "Mechanical, electrical and plumbing",
    "description": (
        "Building services (MEP) methodology: System, Zone and Work levels; "
        "services-discipline and stage dimensions; flat direct-cost cascade "
        "that keeps installed equipment as a costed resource."
    ),
    "country_code": None,
    "industry": "mep",
    "currency": "",
    "decimals": 2,
    "hierarchy_levels": _MEP_HIERARCHY,
    "dimensions": [_mep_discipline_dimension(), _stage_dimension()],
    "column_preset": None,
    "base_mapping": _FLAT_BASE_MAPPING,
    "composites": _FLAT_COMPOSITES,
    "cascade_steps": _flat_steps(overhead="12", profit="10", vat="0"),
    "vat_rate": None,
}

# Industry packs, in catalogue order (railway first as the original pack).
_INDUSTRY_TEMPLATES: list[dict[str, Any]] = [
    _RAILWAY_TEMPLATE,
    _ROAD_TEMPLATE,
    _BRIDGE_TEMPLATE,
    _TUNNEL_TEMPLATE,
    _EARTHWORKS_TEMPLATE,
    _WATER_TEMPLATE,
    _POWER_TEMPLATE,
    _PLANT_TEMPLATE,
    _RESIDENTIAL_TEMPLATE,
    _COMMERCIAL_TEMPLATE,
    _MEP_TEMPLATE,
]


# ---------------------------------------------------------------------------
# Reconciliation with the regional markup table
# ---------------------------------------------------------------------------
#
# There are two markup engines and they used to answer the same country with
# two different numbers. A United States bill seeded from the regional table
# came to 1,308,150 on a million of direct cost; the "United States"
# methodology, three flat steps of overhead, profit and a zero tax, came to
# 1,210,000. Neither number was wrong for what it computed. What was wrong was
# that both were presented as the American way of pricing a job.
#
# ``app.modules.boq.markup_templates.DEFAULT_MARKUP_TEMPLATES`` is the
# canonical statement of what a national stack contains, so the country
# templates here derive from it instead of restating it. Nothing below is
# hand-copied: one pass rewrites the steps of every country the table covers,
# and the countries it does not cover keep the flat method and say so in the
# description rather than presenting three steps as a national convention.
#
# ``tests/unit/test_one_country_one_markup_stack.py`` computes each covered
# country through both engines and fails if the two disagree beyond the cents
# their different rounding costs, so the divergence cannot come back quietly.

#: Appended to the description of a country template the regional table does
#: not cover. It exists so the catalogue never implies a national method it
#: does not have, and the test asserts it is present on exactly that class.
NEUTRAL_METHOD_NOTE = (
    "This is the neutral international method carrying the local currency and "
    "consumption-tax rate, not a national cost-planning convention."
)

# The step keys :func:`_flat_steps` emits. A template whose steps are exactly
# these is running the neutral flat method and is a candidate for derivation; a
# template that states a real national cascade of its own (Brazilian BDI,
# Colombian AIU, Chilean APU, the Mexican and Uzbek methodologies) is not, and
# is left alone even when its country appears in the regional table.
_FLAT_STEP_KEYS = ("overhead", "profit", "vat")


def _derived_steps(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate regional markup lines into cascade steps.

    The two vocabularies differ in one place. A markup line says ``apply_to``:
    ``direct_cost`` for a rate on the direct cost alone, ``cumulative`` for a
    rate on the direct cost plus every line before it. A cascade step names its
    base explicitly. So ``direct_cost`` becomes the direct composite on its own,
    and ``cumulative`` becomes the direct composite plus the key of every
    preceding step, which is the same set written out. That is the whole
    translation, and it is the only thing between the two engines: with it the
    same country priced through either comes to the same money.

    Step keys are positional (``s5_bond``) rather than derived from the line
    name, because the names are national terms and several of them are CJK, so
    slugifying them would produce collisions or nothing at all. Labels keep the
    line name exactly as the table writes it.

    Args:
        lines: Markup lines from
            :func:`app.modules.boq.markup_templates.region_lines_for_country`,
            already in seeding order with the country VAT swapped in.

    Returns:
        Ordered cascade-step dicts for a template's ``cascade_steps``.
    """
    steps: list[dict[str, Any]] = []
    preceding: list[str] = []
    for index, line in enumerate(lines):
        key = f"s{index + 1}_{line['category']}"
        cumulative = str(line.get("apply_to", "direct_cost")).lower() in ("cumulative", "subtotal")
        steps.append(
            {
                "key": key,
                "label": str(line["name"]),
                "category": str(line["category"]),
                "kind": "percentage",
                "rate": str(line["percentage"]),
                "amount": "0",
                "base": ["direct", *preceding] if cumulative else ["direct"],
            }
        )
        preceding.append(key)
    return steps


def _reconcile_with_region_table(template: dict[str, Any]) -> dict[str, Any]:
    """Return the template as it should ship, given the regional markup table.

    Three outcomes, and which one applies is decided from the data rather than
    from a list somebody has to remember to update:

    * A flat country template whose country the regional table covers is
      rewritten from that table. It gains the national stack, the national line
      names, and ``derived_from_region``.
    * A flat country template whose country the table does not cover keeps its
      steps and gains :data:`NEUTRAL_METHOD_NOTE`, so a reader is told it is the
      neutral method rather than left to assume a national one.
    * Anything else, a template with a cascade of its own or with no country at
      all, is returned untouched.

    Args:
        template: A catalogue template dict.

    Returns:
        The same dict when nothing applies, otherwise a new dict. The catalogue
        literals above are never mutated, so a template's source keeps saying
        what was written by hand and what the table decided.
    """
    country = template.get("country_code")
    if not country:
        return template
    step_keys = tuple(str(step.get("key")) for step in template.get("cascade_steps") or ())
    if step_keys != _FLAT_STEP_KEYS:
        return {**template, "derived_from_region": None}

    lines = region_lines_for_country(str(country), vat_rate=template.get("vat_rate"))
    if lines is None:
        return {
            **template,
            "description": f"{template['description']} {NEUTRAL_METHOD_NOTE}",
            "derived_from_region": None,
        }

    region_key = REGION_BY_COUNTRY[str(country).upper()]
    return {
        **template,
        "description": (
            f"{template['name']} national markup stack, {len(lines)} lines, the same stack a bill "
            f"of quantities is seeded with in this market ({region_key} regional template)."
        ),
        "cascade_steps": _derived_steps(lines),
        "derived_from_region": region_key,
    }


# Ordered catalogue: international first, then countries, then UZ, MX, CL, then
# the industry packs (railway plus the sector methodologies). The two Latin
# American APU templates sit after the flat countries because a country can
# appear in both traditions: Chile is in the flat list as well, and which one a
# project wants depends on who is going to read the estimate.
TEMPLATES: tuple[dict[str, Any], ...] = tuple(
    _reconcile_with_region_table(tpl)
    for tpl in (
        _INTERNATIONAL_TEMPLATE,
        *_COUNTRY_TEMPLATES,
        *_MORE_COUNTRY_TEMPLATES,
        _UZBEKISTAN_TEMPLATE,
        _MEXICO_TEMPLATE,
        _CHILE_APU_TEMPLATE,
        _COLOMBIA_AIU_TEMPLATE,
        _BRAZIL_BDI_TEMPLATE,
        *_INDUSTRY_TEMPLATES,
    )
)

# Index by slug for O(1) lookup. Built once at import time.
TEMPLATES_BY_SLUG: dict[str, dict[str, Any]] = {t["slug"]: t for t in TEMPLATES}


def list_templates() -> list[dict[str, Any]]:
    """Return all built-in templates, in catalogue order.

    The returned dicts are the live catalogue objects; callers that mutate
    them would corrupt the catalogue, so the service layer copies before
    persisting. (They are not deep-copied here to keep this helper allocation
    free for the common read-only listing path.)
    """
    return list(TEMPLATES)


def get_template(slug: str) -> dict[str, Any]:
    """Return the template with ``slug`` or raise :class:`TemplateError`."""
    try:
        return TEMPLATES_BY_SLUG[slug]
    except KeyError as exc:
        raise TemplateError(f"unknown methodology template {slug!r}") from exc


def build_cascade_spec(
    *,
    slug: str,
    currency: str,
    decimals: int,
    composites: Mapping[str, Any],
    cascade_steps: Any,
) -> CascadeSpec:
    """Build a :class:`CascadeSpec` from serialized methodology fields.

    This is the single bridge from the persisted / template representation
    (composites as ``{name: [tokens]}`` and steps as a list of dicts with
    string rates/amounts) to the frozen-dataclass spec the pure cascade engine
    consumes. It is deliberately permissive about input numeric types (str /
    int / Decimal) because the same builder serves both the JSON-backed ORM row
    and the in-memory template dict; the engine itself does the strict Decimal
    coercion and all structural validation.

    Args:
        slug: Methodology slug (informational on the spec).
        currency: ISO currency code (informational; never used to convert).
        decimals: Rounding precision passed straight to the engine.
        composites: Mapping of composite name to a sequence of leaf base
            tokens, e.g. ``{"SMR": ["labor", "machinery", "materials"]}``.
        cascade_steps: Iterable of step dicts, each with ``key``, ``label``,
            ``category``, ``kind`` and either ``rate`` (percentage) or
            ``amount`` (fixed), plus a ``base`` list of tokens.

    Returns:
        A :class:`CascadeSpec` ready for ``compute_cascade``.

    Raises:
        TemplateError: If a step is not a mapping or is missing a required key,
            or if a composite member list is malformed.
    """
    # Imported lazily so a standalone (Python 3.11) import of this module for
    # the template-data unit tests does not pull the cascade module until a
    # spec is actually built (and even then cascade.py is itself stdlib-only).
    from decimal import Decimal

    from app.modules.methodology.cascade import CascadeSpec, MarkupStep

    if not isinstance(composites, Mapping):
        raise TemplateError(f"composites must be a mapping, got {type(composites).__name__}")

    composites_built: dict[str, tuple[str, ...]] = {}
    for name, members in composites.items():
        if isinstance(members, str) or not _is_sequence(members):
            raise TemplateError(f"composite {name!r} must map to a list of base tokens, got {type(members).__name__}")
        composites_built[str(name)] = tuple(str(m) for m in members)

    steps_built: list[MarkupStep] = []
    for raw in cascade_steps or ():
        if not isinstance(raw, Mapping):
            raise TemplateError(f"each cascade step must be a mapping, got {type(raw).__name__}")
        try:
            key = str(raw["key"])
            kind = str(raw["kind"])
        except KeyError as exc:
            raise TemplateError(f"cascade step is missing required field {exc.args[0]!r}") from exc

        base_raw = raw.get("base", ())
        if isinstance(base_raw, str) or not _is_sequence(base_raw):
            raise TemplateError(f"cascade step {key!r} base must be a list of tokens, got {type(base_raw).__name__}")

        steps_built.append(
            MarkupStep(
                key=key,
                label=str(raw.get("label", key)),
                category=str(raw.get("category", "other")),
                kind=kind,
                # Decimal() accepts str / int directly; the engine re-validates.
                rate=Decimal(str(raw.get("rate", "0") or "0")),
                amount=Decimal(str(raw.get("amount", "0") or "0")),
                base=tuple(str(token) for token in base_raw),
            )
        )

    return CascadeSpec(
        slug=slug,
        currency=currency,
        decimals=int(decimals),
        composites=composites_built,
        steps=tuple(steps_built),
    )


def build_cascade_spec_from_template(slug: str) -> CascadeSpec:
    """Resolve a built-in template by slug and build its cascade spec."""
    tpl = get_template(slug)
    return build_cascade_spec(
        slug=tpl["slug"],
        currency=tpl["currency"],
        decimals=tpl["decimals"],
        composites=tpl["composites"],
        cascade_steps=tpl["cascade_steps"],
    )


def _is_sequence(value: object) -> bool:
    """True for a list / tuple (the only sequence shapes templates use).

    A bare ``str`` is intentionally excluded by callers before this is reached;
    this helper just rejects non-iterables / mappings so a malformed template
    field fails loudly instead of iterating characters or dict keys.
    """
    return isinstance(value, (list, tuple))
