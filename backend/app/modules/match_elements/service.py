# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Match Elements orchestrator service — Phase A core wiring.

The service stitches together the source adapters and matchers behind
a single API surface the router calls. Stateless: every method takes
the AsyncSession explicitly so tests can pass a transactional session.

Implemented in this revision:
    create_session, get_session, update_session
    rebuild_groups, list_groups, get_group_detail
    run_match (single method, with auto-confirm above threshold)
    confirm, bulk_confirm
    list_templates, lookup_templates, delete_template

Stubbed — Phase A.5b / A.9 / A.10:
    split_group, merge_groups, skip_group
    apply_to_boq
    no_match
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.match_service.config import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    DEFAULT_AUTO_CONFIRM_THRESHOLD,
)
from app.core.match_service.envelope import (
    ElementEnvelope,
    MatchCandidate,
    confidence_band_for,
)
from app.core.validation.messages import translate
from app.modules.match_elements import ifc_labels, schemas, signature
from app.modules.match_elements.matchers.resources import ResourcesMatcher

# LexicalMatcher was removed in v3 — sparse matching is handled natively
# inside the Qdrant ranker (BAAI/bge-m3 sparse vector + RRF fusion). The
# "lexical" method literal is still accepted by the API for back-compat
# with stored MatchSession rows, but ``_matcher("lexical")`` now raises
# NotImplementedError so callers get a clean error instead of silently
# routing into dead code.
from app.modules.match_elements.matchers.vector import VectorMatcher
from app.modules.match_elements.models import (
    MatchGroup,
    MatchSearchLog,
    MatchSession,
    MatchTemplate,
)
from app.modules.match_elements.sources.base import SourceElement
from app.modules.match_elements.sources.bim_adapter import BIMSourceAdapter
from app.modules.match_elements.sources.boq_adapter import BoqAdapter
from app.modules.match_elements.sources.dwg_adapter import DwgAdapter
from app.modules.match_elements.sources.image_adapter import ImageSourceAdapter
from app.modules.match_elements.sources.text_adapter import TextAdapter

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────


def _to_session_read(row: MatchSession) -> schemas.SessionRead:
    # Catalogue id is either a legacy CostDatabase UUID (stored on the
    # ``catalogue_id`` column) or a CWICR v3 region string like
    # ``"DE_BERLIN"`` (stashed in ``metadata_["catalogue_region"]`` —
    # the column itself is typed UUID and rejects region strings).
    # Surface whichever is set so the wizard's "Catalogue" pill on
    # subsequent reads matches what the user picked.
    cat_id: str | None = None
    if row.catalogue_id is not None:
        cat_id = str(row.catalogue_id)
    else:
        region = (row.metadata_ or {}).get("catalogue_region")
        if isinstance(region, str) and region:
            cat_id = region
    return schemas.SessionRead(
        id=row.id,
        project_id=row.project_id,
        bim_model_id=row.bim_model_id,
        source=row.source,  # type: ignore[arg-type]
        name=row.name,
        group_by=list(row.group_by or []),
        filters=dict(row.filters or {}),
        excluded_categories=list(row.excluded_categories or []),
        auto_confirm_threshold=_to_decimal(row.auto_confirm_threshold, DEFAULT_AUTO_CONFIRM_THRESHOLD),
        use_net_quantities=row.use_net_quantities,
        catalogue_id=cat_id,
        is_archived=bool(getattr(row, "is_archived", False) or False),
        construction_stage=getattr(row, "construction_stage", None) or None,
        last_active_at=getattr(row, "last_active_at", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _ifc_class_from_group_key(group_key: str) -> str | None:
    """‌⁠‍Pull the ``ifc_class:`` segment out of a composite group key."""
    for chunk in (group_key or "").split("|"):
        if ":" in chunk:
            k, _, v = chunk.partition(":")
            if k.strip() == "ifc_class":
                return v.strip()
    return None


def _human_group_label(
    group_key: str,
    sample_attrs: dict[str, Any] | None,
) -> str:
    """‌⁠‍Render a group_key into a human-readable single-line label.

    ``"ifc_class:IfcWallStandardCase|material:Concrete C30/37|level:L01"``
    becomes ``"Wall · Concrete C30/37 · L01"``.

    The IFC class segment is replaced with its english label from
    :mod:`ifc_labels`; other segments pass their value through unchanged
    (catalogues already store these in the user's working language).
    """
    parts: list[str] = []
    seen: set[str] = set()
    for chunk in (group_key or "").split("|"):
        if ":" not in chunk:
            continue
        key, _, val = chunk.partition(":")
        key = key.strip()
        val = (val or "").strip()
        if not val or val.lower() in {"none", "null"}:
            continue
        if key in seen:
            continue
        seen.add(key)
        if key in ("ifc_class", "category", "element_type"):
            parts.append(ifc_labels.lookup(val).en_label)
        elif key in ("type_name", "name"):
            # Skip type_name when it duplicates the ifc_class label.
            if parts and parts[-1].lower() == val.lower():
                continue
            parts.append(val)
        else:
            parts.append(val)
    if not parts and isinstance(sample_attrs, dict):
        # Last-ditch: build from element name if the group_key was empty.
        nm = sample_attrs.get("name") or sample_attrs.get("type_name")
        if nm:
            parts.append(str(nm))
    return " · ".join(parts) if parts else (group_key or "Unnamed group")


# ─── Classification-standard registry, derived from CWICR catalogues ─────
#
# Drives section-path rendering when the operator hasn't explicitly set
# ``project.classification_standard``. For a Madrid or São Paulo or
# Boston project the right default leads with the standard the local
# estimator actually reads (UNTEC, VOCI, GB50500, …), not a static
# "din276" fallback.
#
# T1.1 + T2.1 (Match universalisation 2-day pass): both the standards
# tuple and the region→standard map are derived at module load from
# :mod:`app.modules.costs.cwicr_v3_catalogue.CWICR_V3_CATALOGUES`. A new
# catalogue automatically participates in section-path resolution
# without code edits here. If the catalogue module fails to import
# (circular dependency, packaging accident) the legacy hardcoded sets
# kick in so the matcher service stays loadable.
#
# Display labels stay in one place so we don't drift between section
# path rendering, BOQ exports, and the requirements/validation
# messages.

# Country ISO → preferred local classification standard. Drives the
# heuristic used by ``_derive_standards_from_catalogues``. The base set
# below is the task-spec heuristic (DE/AT/CH→din276, US→masterformat,
# UK/IE→nrm, FR→untec, IT→voci, CN→gb50500, RU→gesn, ES→bc3,
# JP→sekisan, KR→kbim, TR→birimfiyat). Anything not in this table
# falls back to MasterFormat (the most widely accepted CSI-aligned
# tender format for global exports).
_COUNTRY_TO_STANDARD: dict[str, str] = {
    # DACH — DIN-276 cost-group hierarchy
    "DE": "din276",
    "AT": "din276",
    "CH": "din276",
    "LI": "din276",
    # UK / Commonwealth NRM heritage (RICS-aligned local QS bodies)
    "GB": "nrm",
    "UK": "nrm",
    "IE": "nrm",
    "AU": "nrm",
    "NZ": "nrm",
    "ZA": "nrm",
    "IN": "nrm",
    "NG": "nrm",
    "KE": "nrm",
    "HK": "nrm",
    "SG": "nrm",
    "MY": "nrm",
    # US / North America (MasterFormat)
    "US": "masterformat",
    "USA": "masterformat",
    "CA": "masterformat",
    # Romance — native systems
    "FR": "untec",
    "IT": "voci",
    "ES": "bc3",
    # Asia — native systems
    "CN": "gb50500",
    "JP": "sekisan",
    "KR": "kbim",
    # Slavic / CIS — GESN family
    "RU": "gesn",
    # Türkiye — Birim Fiyat
    "TR": "birimfiyat",
}

# Macro-region & city-suffix bridges that the catalogue file doesn't
# encode but estimators routinely set as ``project.region``. We need
# these so a project keyed to ``DACH`` / ``LATAM`` / ``RU_MOSCOW``
# resolves to the same standard as its representative country. The
# entries here are NOT a duplicate of the heuristic — they only add
# macro-region keys that map to a country already in
# ``_COUNTRY_TO_STANDARD``.
_MACRO_REGION_TO_COUNTRY: dict[str, str] = {
    # DACH cluster
    "DACH": "DE",
    "EU": "DE",
    "BENELUX": "DE",
    "BE": "DE",
    "NL": "DE",
    "LU": "DE",
    "PL": "DE",
    "CZ": "DE",
    "SK": "DE",
    "HU": "DE",
    "RO": "DE",
    "BG": "DE",
    "HR": "DE",
    "SI": "DE",
    "RS": "DE",
    "LT": "DE",
    "LV": "DE",
    "EE": "DE",
    "MA": "DE",  # Morocco — French DTU-aligned, DIN-276 nearest export
    "TN": "DE",
    "DZ": "DE",
    # Nordic cluster (DIN-276 nearest hierarchy)
    "SCANDINAVIA": "DE",
    "NORDIC": "DE",
    "SE": "DE",
    "SV": "DE",
    "NO": "DE",
    "DK": "DE",
    "FI": "DE",
    "IS": "DE",
    # LATAM / Iberia cluster (MasterFormat / CSI-aligned exports)
    "LATAM": "US",
    "BR": "US",
    "MX": "US",
    "AR": "US",
    "CL": "US",
    "CO": "US",
    "PE": "US",
    "EC": "US",
    "UY": "US",
    "PY": "US",
    "BO": "US",
    "VE": "US",
    "PT": "US",
    # Gulf English-language tendering
    "GULF": "US",
    "AE": "US",
    "SA": "US",
    "QA": "US",
    "KW": "US",
    "BH": "US",
    "OM": "US",
    "EG": "US",
    # Asia-Pacific — CSI export defaults for non-native-mapped countries
    "ASIA_PAC": "US",
    "TW": "US",
    "ID": "US",
    "TH": "US",
    "VN": "US",
    "PH": "US",
    # India Hindi-region alias
    "HI": "IN",
    # CIS cluster (GESN family via Russia)
    "RU_STPETERSBURG": "RU",
    "RU_MOSCOW": "RU",
    "UA": "RU",
    "BY": "RU",
    "KZ": "RU",
}

# Legacy display labels — always present so the section-path renderer
# never KeyErrors on a brand-new standard introduced by a catalogue.
_CLASSIFICATION_STANDARD_LABELS: dict[str, str] = {
    "din276": "DIN276",
    "masterformat": "MasterFormat",
    "nrm": "NRM",
    "untec": "UNTEC",
    "voci": "VOCI",
    "bc3": "BC3",
    "gb50500": "GB50500",
    "sekisan": "SEKISAN",
    "kbim": "KBIM",
    "gesn": "GESN",
    "birimfiyat": "Birim Fiyat",
    "onorm": "ÖNORM",
    "uniclass": "Uniclass",
    "omniclass": "OmniClass",
    "uniformat": "UniFormat",
    "gaeb": "GAEB",
}

# Fallback sets used when the catalogue module can't be imported.
_FALLBACK_STANDARDS: tuple[str, ...] = ("din276", "masterformat", "nrm")
_FALLBACK_REGION_TO_STANDARD: dict[str, str] = {
    # Minimal map covering the three legacy standards. Used only if
    # CWICR_V3_CATALOGUES is unavailable; the normal path derives a
    # richer map from catalogue country_iso fields.
    "DE": "din276",
    "AT": "din276",
    "CH": "din276",
    "DACH": "din276",
    "EU": "din276",
    "US": "masterformat",
    "USA": "masterformat",
    "CA": "masterformat",
    "GB": "nrm",
    "UK": "nrm",
    "IE": "nrm",
}


def _derive_standards_from_catalogues() -> tuple[tuple[str, ...], dict[str, str]]:
    """Derive the standards tuple + region→standard map from CWICR.

    Reads :data:`CWICR_V3_CATALOGUES` once at module load and produces:

    * a tuple of unique classification-standard ids (``("din276",
      "masterformat", "nrm", "untec", "voci", "gb50500", "gesn",
      "bc3", "sekisan", "kbim", "birimfiyat")`` in catalogue order, with
      the three legacy standards always present so the section-path
      renderer can still fall through to them);
    * a dict mapping every catalogue ``region`` AND its ``country_iso``
      to the locally preferred standard (per :data:`_COUNTRY_TO_STANDARD`),
      plus the macro-region / city-suffix bridges from
      :data:`_MACRO_REGION_TO_COUNTRY`.

    On any import failure (circular dep, packaging mistake) returns the
    hardcoded :data:`_FALLBACK_STANDARDS` /
    :data:`_FALLBACK_REGION_TO_STANDARD` so the matcher service still
    loads.
    """
    try:
        from app.modules.costs.cwicr_v3_catalogue import (
            CWICR_V3_CATALOGUES,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "match_elements: CWICR catalogue import failed (%s); falling back to hardcoded standards",
            exc,
        )
        return _FALLBACK_STANDARDS, dict(_FALLBACK_REGION_TO_STANDARD)

    # Legacy three are always present so existing tests + BOQ exports
    # that hardcode ``{din276, masterformat, nrm}`` keep working.
    standards: list[str] = ["din276", "masterformat", "nrm"]
    seen: set[str] = set(standards)
    region_to_standard: dict[str, str] = {}

    # 1. Seed with the country-level heuristic table so every country
    # the task spec mentions has an entry even if no v3 catalogue
    # exists for it yet (e.g. UK / IE / NG / KE / HK / SG / MY / NZ
    # / LI lack standalone catalogues today but estimators still set
    # ``project.region`` to them).
    for country, std in _COUNTRY_TO_STANDARD.items():
        region_to_standard[country.upper()] = std
        if std not in seen:
            standards.append(std)
            seen.add(std)

    # 2. Layer in every published catalogue. Catalogue country_iso
    # wins over the seed (it shouldn't disagree, but if it does the
    # catalogue is the source of truth). The full catalogue region id
    # ("DE_BERLIN") always lands; the bare country ISO ("NL") only
    # lands when the country is explicitly in the heuristic table —
    # otherwise step 3's macro-region bridge gets a chance to map it
    # (e.g. NL → DACH cluster → din276 instead of falling to the
    # masterformat default that hides the cluster intent).
    for cat in CWICR_V3_CATALOGUES:
        country = (cat.country_iso or "").upper().strip()
        std = _COUNTRY_TO_STANDARD.get(country, "masterformat")
        if std not in seen:
            standards.append(std)
            seen.add(std)
        region_to_standard[cat.region.upper().strip()] = std
        if country in _COUNTRY_TO_STANDARD:
            region_to_standard.setdefault(country, std)

    # 3. Apply macro-region & city-suffix bridges. ``setdefault`` keeps
    # any seed / catalogue-derived entry so a real catalogue always
    # wins over an alias.
    for macro, anchor in _MACRO_REGION_TO_COUNTRY.items():
        anchor_std = region_to_standard.get(
            anchor.upper(),
            _COUNTRY_TO_STANDARD.get(anchor.upper(), "masterformat"),
        )
        region_to_standard.setdefault(macro.upper(), anchor_std)
        if anchor_std not in seen:
            standards.append(anchor_std)
            seen.add(anchor_std)

    return tuple(standards), region_to_standard


_KNOWN_CLASSIFICATION_STANDARDS, _REGION_PREFERRED_STANDARD = _derive_standards_from_catalogues()


def _resolve_classification_order(
    project_std: str | None,
    project_region: str | None,
) -> tuple[str, ...]:
    """Pick the classification-standard preference for a project.

    Resolution order:

    1. Explicit ``project.classification_standard`` if it names a
       standard we render.
    2. Region-derived default (``_REGION_PREFERRED_STANDARD``) — a US
       project gets MasterFormat first, UK gets NRM, DACH gets DIN-276,
       LATAM and Iberia get MasterFormat (their catalogues align with
       CSI more than DIN).
    3. Globally safe fallback ``("din276", "masterformat", "nrm")``.

    Returns a tuple ordered from most-preferred to least, listing the
    standards in ``_KNOWN_CLASSIFICATION_STANDARDS``. Standards not
    placed first are appended deterministically so the BOQ section path
    still falls through when the project's first-choice standard isn't
    populated on a given CostItem.
    """
    explicit = (project_std or "").lower().strip()
    region = (project_region or "").upper().strip()

    head: str | None = None
    if explicit in _KNOWN_CLASSIFICATION_STANDARDS:
        head = explicit
    elif region:
        head = _REGION_PREFERRED_STANDARD.get(region)
        # Strip city suffix (e.g. RU_STPETERSBURG → RU) for fallback
        if head is None and "_" in region:
            head = _REGION_PREFERRED_STANDARD.get(region.split("_", 1)[0])

    if head is None:
        head = "din276"  # global default — non-empty for any catalogue

    rest = tuple(s for s in _KNOWN_CLASSIFICATION_STANDARDS if s != head)
    return (head,) + rest


def _aggregate_quantities(elements: list[SourceElement]) -> dict[str, float]:
    """Sum element quantities into one rolled-up dict for the group."""
    out: dict[str, float] = defaultdict(float)
    for e in elements:
        for k, v in e.quantities.items():
            try:
                out[k] += float(v)
            except (TypeError, ValueError):
                continue
    return dict(out)


# Fallback unit per IFC class when explicit quantities are missing. Used
# when the BIM extractor could not derive volume/area/length (e.g. an IFC
# file without proper Qto_* property sets, or an early-design Revit model
# where the only quantity is the count). Without this fallback every
# such group defaults to "pcs" and the matcher then picks count-priced
# catalogue rows for elements that should be priced by area or volume.
#
# Values follow industry pricing convention:
#   m3  — bulk concrete / earthworks elements priced by volume
#   m2  — surface elements priced by area (slabs, roofs, coverings)
#   m   — linear elements priced by length (beams, columns, pipes)
#   pcs — discrete elements priced per unit (doors, windows, furniture)
#
# A class missing from the table returns None so the caller can keep its
# own default. Stem matching ("IfcWallStandardCase" → "IfcWall") keeps
# the table compact.
_IFC_NATURAL_UNIT: dict[str, str] = {
    "IfcWall": "m3",
    "IfcSlab": "m2",
    "IfcRoof": "m2",
    "IfcCovering": "m2",
    "IfcCeiling": "m2",
    "IfcCurtainWall": "m2",
    "IfcSpace": "m2",
    "IfcBeam": "m",
    "IfcColumn": "m",
    "IfcMember": "m",
    "IfcPlate": "m2",
    "IfcFooting": "m3",
    "IfcPile": "m",
    "IfcRamp": "m2",
    "IfcRailing": "m",
    "IfcStair": "pcs",
    "IfcStairFlight": "m2",
    "IfcDoor": "pcs",
    "IfcWindow": "pcs",
    "IfcOpeningElement": "pcs",
    "IfcFurniture": "pcs",
    "IfcFurnishingElement": "pcs",
    "IfcReinforcingBar": "kg",
    "IfcPipeSegment": "m",
    "IfcDuctSegment": "m",
    "IfcCableSegment": "m",
    "IfcCableCarrierSegment": "m",
    "IfcChimney": "pcs",
}


def _ifc_natural_unit(ifc_class: str | None) -> str | None:
    """Return the typical pricing unit for an IFC class, or None if unknown.

    Falls back to a stem match — ``IfcWallStandardCase`` → ``IfcWall`` —
    so subtype variants resolve without a table entry each.
    """
    if not ifc_class:
        return None
    cls = str(ifc_class)
    if cls in _IFC_NATURAL_UNIT:
        return _IFC_NATURAL_UNIT[cls]
    # Stem fallback: strip common suffixes once.
    for suffix in ("StandardCase", "ElementedCase", "BaseQuantities", "Type"):
        if cls.endswith(suffix):
            base = cls[: -len(suffix)]
            if base in _IFC_NATURAL_UNIT:
                return _IFC_NATURAL_UNIT[base]
    return None


def _pick_unit(quantities: dict[str, float], *, ifc_class: str | None = None) -> str:
    """Auto-pick the natural unit for a group by dimensional specificity.

    Construction estimating prices the most specific dimension first:
    a wall is volume (concrete), a slab is area (formwork+rebar), a pipe
    is length (LM), a door is count. Whichever dimension is non-zero
    wins in that order. Sorting by numeric value would always favour
    count (integers ≫ m³ values for multi-element groups) and route
    every wall group to a per-piece rate.

    When no dimension carries a positive value (a common case for IFC
    files exported without ``Qto_*`` property sets), falls back to the
    IFC class's natural pricing unit via :func:`_ifc_natural_unit`. This
    lets IfcWall groups land on m³-priced catalogue rows even when the
    file only carries element counts.
    """
    for unit, key in (
        ("m3", "volume_m3"),
        ("m2", "area_m2"),
        ("m", "length_m"),
        ("kg", "mass_kg"),
        ("pcs", "count"),
    ):
        v = quantities.get(key, 0.0) or 0.0
        try:
            if float(v) > 0:
                # Don't trust ``count`` when the class is normally priced
                # by surface or volume — the dimension-less default would
                # land on per-piece rates instead of per-m².
                if unit == "pcs":
                    fallback = _ifc_natural_unit(ifc_class)
                    if fallback and fallback != "pcs":
                        return fallback
                return unit
        except (TypeError, ValueError):
            continue
    return _ifc_natural_unit(ifc_class) or "pcs"


def _quantity_for_unit(quantities: dict[str, float], unit: str) -> float:
    return {
        "m3": quantities.get("volume_m3", 0.0),
        "m2": quantities.get("area_m2", 0.0),
        "m": quantities.get("length_m", 0.0),
        "kg": quantities.get("mass_kg", 0.0),
        "t": (quantities.get("mass_kg", 0.0) or 0.0) / 1000.0,
        "pcs": quantities.get("count", 0.0),
    }.get(unit, quantities.get("count", 0.0))


# Per-request safety caps. These protect the request thread on
# pathologically large sessions (10k+ groups). The frontend just
# repeats the action to progress through the full set; status counters
# update each call so the user sees forward motion.
_BULK_BATCH_LIMIT = 1000
_APPLY_BATCH_LIMIT = 1000


def _split_unit_multiplier(unit: str | None) -> tuple[float, str]:
    """Decompose a catalogue unit string into (multiplier, base_unit).

    Several CWICR locales encode a quantity multiplier in the unit
    column — ``"100 м3"``, ``"10 шт"``, ``"1000 кг"`` — meaning the
    rate is per N of the base unit. To compute a per-base-unit rate
    we peel off the leading numeric token. ``"m3"`` returns
    ``(1.0, "m3")`` so callers can treat both forms uniformly.
    """
    if not unit:
        return 1.0, ""
    s = unit.strip()
    if not s:
        return 1.0, s
    parts = s.split(None, 1)
    if len(parts) == 2:
        try:
            mult = float(parts[0].replace(",", "."))
            if mult > 0:
                return mult, parts[1].strip()
        except ValueError:
            pass
    return 1.0, s


# Cross-locale unit aliases. CWICR ships in 24 languages, so the unit
# column carries Cyrillic (м3, шт, т), Bulgarian (брой, бр), German
# (Stück, Stk), French (pcs, ml), Spanish (ud, m), etc. Without this
# map the dimensional gate in apply_to_boq mis-classifies cyrillic
# units as "no dimension" and lets pcs×volume mismatches through.
_UNIT_LOCALE_MAP: dict[str, str] = {
    # Russian / Bulgarian Cyrillic
    "м": "m",
    "м.": "m",
    "м2": "m2",
    "м²": "m2",
    "м3": "m3",
    "м³": "m3",
    "пог.м": "m",
    "пог. м": "m",
    "п.м": "m",
    "пм": "m",
    "т": "t",
    "кг": "kg",
    "г": "kg",
    "шт": "pcs",
    "шт.": "pcs",
    "штук": "pcs",
    "брой": "pcs",
    "броя": "pcs",
    "бр": "pcs",
    "бр.": "pcs",
    "стык": "pcs",
    "комплект": "lsum",
    "компл": "lsum",
    "компл.": "lsum",
    "комплектен": "lsum",
    "свързване": "pcs",  # connection
    # German
    "stk": "pcs",
    "stk.": "pcs",
    "stück": "pcs",
    "st": "pcs",
    "tn": "t",
    "tonne": "t",
    # French / Spanish / Italian
    "ud": "pcs",
    "ud.": "pcs",
    "u": "pcs",
    "uni": "pcs",
    "ml": "m",
    "lm": "m",
    # English variants
    "ea": "pcs",
    "each": "pcs",
    "no": "pcs",
    "no.": "pcs",
    "nr": "pcs",
    "lf": "m",  # linear foot — close enough for dim
    "sf": "m2",
    "sq.ft": "m2",
    "sqft": "m2",
    "cy": "m3",
    "cuyd": "m3",
    "lsum": "lsum",
    "ls": "lsum",
}


def _normalise_unit_cross_locale(unit: str | None) -> str:
    """Normalise a catalogue unit to the matcher's canonical code.

    Pre-folds Cyrillic / Bulgarian / German / Spanish / French short
    forms onto the same canonical set as the boost helper expects
    (``m``, ``m2``, ``m3``, ``kg``, ``pcs``, ``lsum``, ``t``).
    """
    if not unit:
        return ""
    cleaned = unit.strip().lower()
    cleaned = cleaned.replace("²", "2").replace("³", "3").replace("^", "")
    if cleaned in _UNIT_LOCALE_MAP:
        return _UNIT_LOCALE_MAP[cleaned]
    return cleaned


async def _record_pick_to_search_log(
    db: AsyncSession,
    *,
    project_id: uuid.UUID | str | None,
    session_id: uuid.UUID,
    group_id: uuid.UUID | None,
    picked_rate_code: str | None,
    picked_rank: int | None,
    picked_at: datetime,
) -> None:
    """Backfill ``picked_rank`` / ``picked_rate_code`` / ``picked_at``
    on the most recent ``oe_match_elements_search_log`` row for the
    given session+group pair.

    Implements the MAPPING_PROCESS.md §10 user-feedback loop. Without
    this hook the spec's classifier-quality alerts cannot fire because
    "user_picked_rank > 4 for >20% of requests" is unobservable.

    The match-search-log table is append-only by design, and matchers
    can run multiple times per group (re-run with different filters).
    The hook updates the latest row only — the historical ones stay
    immutable so the analytics audit trail of "what was suggested at
    the time of this confirmation" survives. If no log row exists
    (older sessions, unit-test fixtures, log INSERT failed) the hook
    is a no-op — match confirmation must never fail because of an
    analytics-only side effect.
    """
    if session_id is None:
        return

    stmt = select(MatchSearchLog).where(
        MatchSearchLog.session_id == session_id,
    )
    if group_id is not None:
        stmt = stmt.where(MatchSearchLog.group_id == group_id)
    stmt = stmt.order_by(MatchSearchLog.created_at.desc()).limit(1)

    try:
        log_row = (await db.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        logger.debug("search_log: pick lookup failed (%s)", exc)
        return

    if log_row is None:
        # Older sessions confirmed before v2934 landed have no log row.
        # Nothing to backfill — mute and move on.
        return

    log_row.picked_rate_code = picked_rate_code or None
    log_row.picked_rank = picked_rank
    log_row.picked_at = picked_at


def _derive_picked_rank_and_code(
    methods: dict[str, Any] | None,
    *,
    chosen_method: str | None,
    chosen_candidate_id: uuid.UUID | None,
) -> tuple[int | None, str | None]:
    """Find the 1-based rank of ``chosen_candidate_id`` within
    ``methods[chosen_method]``, plus the matching ``rate_code``.

    Returns ``(None, None)`` when the candidate isn't found in the
    stored method list — happens for manual overrides where the user
    typed a rate that wasn't suggested. The ``picked_rate_code`` field
    on the search_log stays NULL in that case so analytics can
    distinguish "picked from suggestions" vs "manual override".
    """
    if not methods or not chosen_method or chosen_candidate_id is None:
        return None, None

    cand_list = methods.get(chosen_method) or []
    if not isinstance(cand_list, list):
        return None, None

    target = str(chosen_candidate_id)
    for idx, raw in enumerate(cand_list, start=1):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("id") or "") == target:
            code = raw.get("code")
            return idx, (str(code) if code else None)
    return None, None


def _envelope_from_group(
    group_key: str,
    elements: list[SourceElement],
    quantities: dict[str, float],
    source: str = "bim",
    *,
    construction_stage: str | None = None,
    project_currency: str = "",
    project_region: str = "",
) -> ElementEnvelope:
    """Build an ElementEnvelope representative of the whole group.

    Composition order (mirrors the eval-harness BIM extractor at
    ``app.core.match_service.extractors.bim``):

        ``"<category>, <type_name>, <material>, thickness <x>m, fire <r>, U=<u>"``

    Each segment is included only when present, so a sparse group
    (just a name) still produces a useful envelope and a dense one
    (Revit family with full Pset) carries every dimensioning hint into
    the embedder. The previous implementation joined every attribute
    value into one string — that pollutes the embedding with GUIDs and
    layer names and caps recall. This composition is selective.
    """
    if not elements:
        raise ValueError("Cannot build envelope for empty group")
    sample = elements[0]
    attrs: dict[str, Any] = sample.attributes or {}

    def _attr(*keys: str) -> str | None:
        for k in keys:
            v = attrs.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s and s.lower() not in {"none", "null", "undefined", ""}:
                return s
        return None

    def _num(*keys: str) -> float | None:
        for k in keys:
            v = attrs.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    parts: list[str] = []
    # 1. Human category (translated IFC label) — anchors the embedding.
    ifc_meta = ifc_labels.lookup(sample.category)
    category_label = ifc_meta.en_label
    # For free-text / BoQ sources the category is a placeholder
    # ("Text" / generic IFC fallback) and carries no signal — skip it
    # so the embedding query is dominated by the actual ``raw_text`` /
    # description rather than a noise word.
    if source not in {"text", "boq"}:
        parts.append(category_label)
    # 2. Type / family name — usually the most discriminating signal.
    # For text / boq sources the ``raw_text`` / ``description`` IS the
    # user query — include it verbatim so vector search sees the line
    # the user actually wrote ("Concrete C30/37 wall, 240mm") instead
    # of a collapsed group label.
    raw_text = _attr("raw_text", "description")
    if source in {"text", "boq"} and raw_text:
        parts.append(raw_text)
    type_name = _attr("type_name", "Type", "Family", "name")
    if type_name and type_name != category_label:
        parts.append(type_name)
    # 3. Material.
    material = _attr("material", "Material", "primary_material")
    if material:
        parts.append(material)
    # 4. Geometry hints — thickness/diameter/etc.
    thickness_mm = _num("thickness_mm", "Thickness", "thickness")
    if thickness_mm:
        # Accept both raw mm (240) and m (0.24) — normalise to mm.
        if thickness_mm < 5:
            thickness_mm = thickness_mm * 1000.0
        parts.append(f"thickness {int(round(thickness_mm))}mm")
    diameter_mm = _num("diameter_mm", "Diameter", "diameter")
    if diameter_mm:
        if diameter_mm < 5:
            diameter_mm = diameter_mm * 1000.0
        parts.append(f"DN{int(round(diameter_mm))}")
    # 5. Performance hints.
    fire = _attr("fire_rating", "FireRating")
    if fire:
        parts.append(f"fire {fire}")
    u_val = _num("u_value", "U", "ThermalTransmittance")
    if u_val:
        parts.append(f"U={u_val:.2f}")
    is_external_raw = _attr("is_external", "IsExternal")
    if is_external_raw and is_external_raw.lower() in {"true", "1", "yes"}:
        parts.append("external")
    load_bearing_raw = _attr("load_bearing", "LoadBearing")
    if load_bearing_raw and load_bearing_raw.lower() in {"true", "1", "yes"}:
        parts.append("load-bearing")

    description = ", ".join(parts)[:1000]
    unit = _pick_unit(quantities, ifc_class=sample.category)
    unit_hint_map = {"m3": "m3", "m2": "m2", "m": "m", "kg": "kg", "pcs": "pcs"}

    # Only forward small primitive properties — the matcher uses these
    # for boost lookups, not for embedding text.
    ranking_props: dict[str, Any] = {
        k: v
        for k, v in attrs.items()
        if isinstance(v, (str, int, float, bool))
        and len(str(v)) < 80
        and k not in ("name", "guid", "global_id", "stable_id")
    }
    # Pre-classification hint for the trade-aware vector pre-filter.
    # The ranker reads any standard the project's catalogue is keyed by
    # (DIN 276 / MasterFormat / NRM) and uses it as a soft filter. Each
    # standard is emitted independently so a US project hitting a
    # MasterFormat-classified catalogue still narrows to the right
    # division even though the same envelope's DIN 276 hint is irrelevant
    # for that catalogue. Empty hints are not emitted, so the
    # ``classifier_hint`` dict is sparse.
    classifier_hint_parts: dict[str, str] = {}
    if ifc_meta.din276_hint:
        classifier_hint_parts["din276"] = ifc_meta.din276_hint
    if ifc_meta.masterformat_hint:
        classifier_hint_parts["masterformat"] = ifc_meta.masterformat_hint
    if ifc_meta.nrm_hint:
        classifier_hint_parts["nrm"] = ifc_meta.nrm_hint
    classifier_hint: dict[str, str] | None = classifier_hint_parts or None

    # ── v3 ProjectItem-equivalent structured fields ──────────────────
    # Populated when the upstream BIM/Revit extractor knows the value.
    # The query builder downstream routes these to either Qdrant
    # ``hard_filters`` or ``soft_boosts`` per MAPPING_PROCESS.md §4.2.1.
    nominal_size_mm: int | None = None
    if thickness_mm:
        nominal_size_mm = int(round(thickness_mm))
    elif diameter_mm:
        nominal_size_mm = int(round(diameter_mm))

    # Forward ``ifc_class`` only when it's an actual IFC class — BIM
    # extractors set ``sample.category="IfcWall"`` / ``IfcSlab``, but BoQ /
    # text / image adapters synthesise placeholders (``"BoQ"``, ``"Text"``)
    # that aren't valid IFC identifiers. Promoting those to the v3
    # SearchPlan's ``ifc_class`` hard filter eliminates every Qdrant hit
    # (CWICR rates carry empty / IfcCovering / etc. for non-BIM rows) and
    # collapses the search to the metadata-only fallback (score ≈ 0.0002).
    # An explicit ``Ifc`` prefix is the cheapest, most defensive check —
    # callers who know the IFC class for a BoQ row can put it in
    # ``attributes["ifc_class"]`` (the BoqAdapter forwards that key
    # verbatim).
    raw_cat = (sample.category or "").strip()
    attr_ifc_class = _attr("ifc_class", "IfcClass")
    forwarded_ifc_class: str | None = None
    if attr_ifc_class and attr_ifc_class.lower().startswith("ifc"):
        forwarded_ifc_class = attr_ifc_class
    elif raw_cat.lower().startswith("ifc"):
        forwarded_ifc_class = raw_cat

    return ElementEnvelope(
        source=source,
        category=category_label.lower(),
        description=description,
        properties=ranking_props,
        quantities=quantities,
        unit_hint=unit_hint_map.get(unit),
        classifier_hint=classifier_hint,
        ifc_class=forwarded_ifc_class,
        ifc_predefined_type=_attr("ifc_predefined_type", "PredefinedType"),
        ost_category=_attr("ost_category", "Category", "OST_Category"),
        material_class=_normalise_material_class(material),
        nominal_size_mm=nominal_size_mm,
        is_external=_parse_tri_bool(is_external_raw),
        is_loadbearing=_parse_tri_bool(load_bearing_raw),
        is_structural=_parse_tri_bool(_attr("is_structural", "StructuralUsage")),
        # v3-P10b: stage comes from the session (user-picked dropdown);
        # not derivable from BIM attributes alone. Forwarded as a hard
        # filter via SearchPlan when set.
        construction_stage_hint=construction_stage or None,
        # MAPPING_PROCESS.md §4.1.5 — when the upstream BoQ extractor
        # populated ``attributes["exact_code"]`` from the row's ``Code``
        # column, forward it so the ranker can short-circuit Qdrant.
        # Forwarded for any source (BoQ, manual override, future API
        # ingestors) — the BoQ adapter is the primary producer today.
        exact_code=_attr("exact_code", "rate_code", "code"),
        # Project-context pass-through for currency-aware candidate
        # filtering (lexical) and locale-aware Qdrant collection picking
        # (vector). Empty strings = no preference.
        project_currency=(project_currency or "").strip().upper(),
        project_region=(project_region or "").strip().upper(),
    )


# ── Helpers for v3 envelope fields ───────────────────────────────────────


def _parse_tri_bool(raw: str | None) -> bool | None:
    """Parse a free-form Pset boolean into ``True`` / ``False`` / ``None``.

    Returns ``None`` when the raw is missing or unrecognised so the
    caller can leave the envelope field unset rather than asserting a
    polarity that didn't come from the source.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in {"true", "1", "yes", "y", "on", "bearing"}:
        return True
    if s in {"false", "0", "no", "n", "off", "non-bearing", "nonbearing"}:
        return False
    return None


# Material bucket markers — coarse keywords across the languages we
# ship a CWICR catalogue for. Order: English, German/Dutch/Nordic,
# Romance (FR/ES/IT/PT), Slavic (RU/PL/CZ), MENA (Arabic/Turkish),
# CJK (Chinese/Japanese/Korean), Indian (Hindi). Keeping all 30
# language families covered means the soft material-class boost
# fires for any catalogue we can plausibly load.
#
# The matcher is a substring check on the lowercased input — adding
# a word here is non-destructive (won't shadow another bucket because
# the iteration is ordered: first match wins). When in doubt about
# whether a marker belongs to one bucket vs another, prefer leaving
# it out — a missed boost beats a wrong boost.
_MATERIAL_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "concrete",
        (
            # English / Latin
            "concrete",
            "c30/",
            "c25/",
            "c40/",
            "c20/",
            "c35/",
            # German / Dutch / Nordic
            "beton",
            "stahlbeton",
            "betong",
            # Romance
            "béton",
            "calcestruzzo",
            "hormigón",
            "concreto",
            "betón",
            # Slavic
            "бетон",
            "betonu",
            "betonová",
            # CJK
            "混凝土",
            "钢筋混凝土",
            "コンクリート",
            "鉄筋コンクリート",
            "콘크리트",
            # MENA / Indic
            "خرسانة",
            "خرسانه",
            "beton ",  # Turkish "beton" (intentional trailing space)
            "कंक्रीट",
            # Vietnamese / Indonesian / Thai
            "bê tông",
            "beton ",
            "คอนกรีต",
        ),
    ),
    (
        "steel",
        (
            "steel",
            "stahl",
            "acero",
            "aço",
            "acciaio",
            "acier",
            "сталь",
            "stal",
            "ocel",
            "rebar",
            "iron",
            "eisen",
            "fer ",
            # Steel grades — European, US, Indian, Brazilian, Japanese, Chinese
            "s235",
            "s355",
            "s275",
            "s420",
            "s460",
            "grade 40",
            "grade 60",
            "grade 75",
            "fe415",
            "fe500",
            "fe550",  # Indian
            "ca-50",
            "ca-25",  # Brazilian
            "sd295",
            "sd345",
            "sd390",
            "sd490",  # Japanese
            "hrb335",
            "hrb400",
            "hrb500",  # Chinese GB
            # CJK
            "钢",
            "钢筋",
            "鋼",
            "鉄筋",
            "강",
            "철근",
            # MENA
            "فولاذ",
            "حديد",
        ),
    ),
    (
        "wood",
        (
            "wood",
            "timber",
            "lumber",
            "plywood",
            "holz",
            "hout",
            "trä",
            "madera",
            "madeira",
            "legno",
            "bois",
            "дерев",
            "древ",
            "drewno",
            "dřevo",
            # CJK
            "木材",
            "木",
            "木造",
            "목재",
            "목조",
            # MENA / Indic
            "خشب",
            "लकड़ी",
        ),
    ),
    (
        "masonry",
        (
            "brick",
            "block",
            "masonry",
            "ziegel",
            "mauer",
            "mauerwerk",
            "ladrillo",
            "tijolo",
            "mattone",
            "brique",
            "кирпич",
            "блок",
            "cegła",
            # CJK
            "砖",
            "煉瓦",
            "벽돌",
            "조적",
            # MENA / Indic
            "طوب",
            "ईंट",
        ),
    ),
    (
        "glass",
        (
            "glass",
            "glazing",
            "glas",
            "verre",
            "vidrio",
            "vidro",
            "vetro",
            "стекл",
            "szkło",
            "sklo",
            # CJK
            "玻璃",
            "ガラス",
            "유리",
            # MENA / Indic
            "زجاج",
            "कांच",
        ),
    ),
    (
        "aluminum",
        (
            "aluminum",
            "aluminium",
            "alu",
            "aluminio",
            "alumínio",
            "alluminio",
            "алюмин",
            # CJK
            "铝",
            "アルミニウム",
            "アルミ",
            "알루미늄",
            # MENA / Indic
            "ألومنيوم",
            "एल्यूमीनियम",
        ),
    ),
    (
        "ceramic",
        (
            "ceramic",
            "tile",
            "porcelain",
            "fliese",
            "kachel",
            "tegel",
            "azulejo",
            "azulejos",
            "carrelage",
            "piastrella",
            "плитка",
            "керам",
            # CJK
            "瓷砖",
            "陶瓷",
            "タイル",
            "타일",
            "도자기",
            # MENA / Indic
            "بلاط",
            "टाइल",
        ),
    ),
    (
        "plaster",
        (
            "plaster",
            "drywall",
            "gypsum",
            "putz",
            "stuck",
            "gips",
            "yeso",
            "gesso",
            "plâtre",
            "штукат",
            "гипс",
            "tynk",
            "omítka",
            # CJK
            "石膏",
            "灰泥",
            "プラスター",
            "石膏ボード",
            # MENA / Indic
            "جص",
            "प्लास्टर",
        ),
    ),
    (
        "insulation",
        (
            "insulation",
            "foam",
            "wool",
            "dämm",
            "isolier",
            "isolatie",
            "aislamiento",
            "isolamento",
            "isolation",
            "теплоизол",
            "утепл",
            "izolac",
            "polystyr",
            "mineral",
            "minera",
            # CJK
            "保温",
            "断熱",
            "단열",
            # MENA / Indic
            "عزل",
            "इन्सुलेशन",
        ),
    ),
)


def _normalise_material_class(raw: str | None) -> str | None:
    """Collapse a free-form material string onto a coarse v3 bucket.

    Returns one of the keys in :data:`_MATERIAL_BUCKETS` or ``None``
    when no bucket fits. The buckets are intentionally narrow — when
    the source's text looks like ``"Concrete C30/37"`` we're confident
    enough to call it ``"concrete"`` and feed the soft boost; when it
    says ``"Generic 200mm"`` we'd rather not guess.
    """
    if not raw:
        return None
    needle = raw.strip().lower()
    if not needle:
        return None
    for bucket, markers in _MATERIAL_BUCKETS:
        for marker in markers:
            if marker in needle:
                return bucket
    return None


def _to_decimal(s: str | None, default: float = 0.0) -> float:
    if s is None:
        return default
    try:
        return float(Decimal(str(s)))
    except (InvalidOperation, TypeError, ValueError):
        return default


# ── Service ──────────────────────────────────────────────────────────────


class MatchElementsService:
    """Orchestrator. One singleton per process; statelessly forwards work
    to per-request adapter/matcher instances bound to the AsyncSession."""

    # ── Adapter / matcher factories ──────────────────────────────────

    def _adapter(
        self,
        source: str,
        db: AsyncSession,
        match_session: MatchSession | None = None,
    ):
        if source == "bim":
            return BIMSourceAdapter(db)
        if source == "dwg":
            return DwgAdapter(db)
        if source == "text":
            return TextAdapter(db, match_session)
        if source == "boq":
            return BoqAdapter(db, match_session)
        if source == "image":
            return ImageSourceAdapter(db, match_session)
        raise NotImplementedError(
            f"Source '{source}' not yet supported (BIM/DWG/Text/BoQ/Image live; PDF still pending)."
        )

    def _matcher(self, name: str, db: AsyncSession):
        if name == "vector":
            return VectorMatcher(db)
        if name == "lexical":
            raise NotImplementedError(
                "The standalone lexical matcher was removed in v3. Sparse "
                "matching is now fused into the vector matcher via the "
                "BAAI/bge-m3 sparse vector and RRF re-ranking — call with "
                'method="vector" instead.'
            )
        if name == "resources":
            return ResourcesMatcher(db)
        if name == "llm":
            raise NotImplementedError('LLM matcher deferred to Phase A.5+ — use method="vector".')
        raise ValueError(f"Unknown matcher: {name}")

    # ── Sessions ──────────────────────────────────────────────────────

    async def create_session(
        self,
        db: AsyncSession,
        spec: schemas.SessionCreate,
        created_by: uuid.UUID | None = None,
    ) -> schemas.SessionRead:
        # Auto-bind a CWICR catalogue to project match settings if none
        # is bound yet — without this the vector matcher short-circuits
        # with status="no_catalog_selected" and the user sees zero hits
        # despite having installed catalogue data.
        try:
            from app.modules.projects.service import (  # noqa: PLC0415
                auto_bind_dominant_catalogue,
            )

            await auto_bind_dominant_catalogue(db, spec.project_id)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.info(
                "match_elements: auto-bind catalogue skipped for %s: %s",
                spec.project_id,
                exc,
            )

        # Default group-by — source-aware:
        #
        # * BIM / DWG / image: ``["ifc_class", "type_name"]`` produces
        #   stable, estimable groups across BIM authors (rows that share
        #   IfcClass + family name nearly always carry the same rate).
        # * text / boq: each free-form line / row is semantically its
        #   own thing — collapsing them under one ``ifc_class:Text``
        #   bucket would discard every distinct query and run vector
        #   search on the meaningless rolled-up label, returning zero
        #   useful matches. Group by ``raw_text`` / ``description``
        #   instead so the matcher sees per-row signal.
        if spec.group_by:
            group_by = list(spec.group_by)
        elif spec.source == "text":
            group_by = ["raw_text"]
        elif spec.source == "boq":
            group_by = ["description"]
        else:
            group_by = ["ifc_class", "type_name"]
        # Sane subtractive default: voids/annotations/grids hidden by
        # default. Caller can pass [] to keep them visible (e.g. a QA
        # session debugging an opening deduction).
        if spec.excluded_categories is None:
            excluded = list(ifc_labels.DEFAULT_EXCLUDED_CATEGORIES)
        else:
            excluded = list(spec.excluded_categories)

        # MAPPING_PROCESS.md §4.1.5/§4.1.6 — text/BoQ sources persist
        # their input data into ``metadata_`` so the session-scoped
        # adapter (TextAdapter / BoqAdapter) can read it later. We
        # silently ignore the fields when ``source`` doesn't match so a
        # mistakenly-attached payload doesn't pollute a BIM session.
        metadata: dict[str, Any] = {}
        if spec.source == "text" and spec.text_inputs:
            metadata["text_inputs"] = list(spec.text_inputs)
        elif spec.source == "boq" and spec.boq_rows:
            metadata["boq_rows"] = list(spec.boq_rows)
        elif spec.source == "image" and spec.image:
            # MAPPING_PROCESS.md §3.1/§4.1.4 — single uploaded photo or
            # drawing snapshot. Persist as ``{"path"|"data_b64", "mime",
            # "filename"?, "image_id"?}``; the ImageSourceAdapter reads
            # this back on iter_elements.
            metadata["image"] = dict(spec.image)

        # ``catalogue_id`` can arrive as either a legacy CostDatabase UUID
        # (older callers / tests) or a CWICR v3 region string from the
        # wizard's catalogues-v3 picker (e.g. ``"DE_BERLIN"``). The DB
        # column is typed UUID, so route the region string into metadata
        # and leave the column null. ``_to_session_read`` reads both.
        catalogue_uuid: uuid.UUID | None = None
        if spec.catalogue_id:
            try:
                catalogue_uuid = uuid.UUID(spec.catalogue_id)
            except (ValueError, TypeError):
                metadata["catalogue_region"] = spec.catalogue_id

        now = datetime.now(UTC)
        row = MatchSession(
            project_id=spec.project_id,
            bim_model_id=spec.bim_model_id,
            source=spec.source,
            name=spec.name,
            group_by=group_by,
            filters=dict(spec.filters),
            excluded_categories=excluded,
            auto_confirm_threshold=str(spec.auto_confirm_threshold),
            use_net_quantities=spec.use_net_quantities,
            catalogue_id=catalogue_uuid,
            construction_stage=spec.construction_stage,
            created_by=created_by,
            last_active_at=now,
            metadata_=metadata,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return _to_session_read(row)

    async def get_session(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> schemas.SessionRead:
        row = await db.get(MatchSession, session_id)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.session_not_found", locale=get_locale()))
        return _to_session_read(row)

    async def update_session(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        patch: schemas.SessionUpdate,
    ) -> schemas.SessionRead:
        row = await db.get(MatchSession, session_id)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.session_not_found", locale=get_locale()))
        # Track whether the patch changed anything that affects grouping —
        # group_by, scope filters, excluded categories, BIM model binding,
        # or net/gross. If yes, regroup at the end so the chip-bar feels
        # interactive ("click → table re-groups") instead of "click → save
        # silently, refresh manually".
        regroup = False
        if patch.name is not None:
            row.name = patch.name
        if patch.bim_model_id is not None:
            row.bim_model_id = patch.bim_model_id
            regroup = True
        if patch.group_by is not None:
            row.group_by = list(patch.group_by)
            regroup = True
        if patch.filters is not None:
            row.filters = dict(patch.filters)
            regroup = True
        if patch.excluded_categories is not None:
            row.excluded_categories = list(patch.excluded_categories)
            regroup = True
        if patch.auto_confirm_threshold is not None:
            row.auto_confirm_threshold = str(patch.auto_confirm_threshold)
        if patch.use_net_quantities is not None:
            row.use_net_quantities = patch.use_net_quantities
            regroup = True
        if patch.catalogue_id is not None:
            # Same UUID-or-region routing as create_session — see comment
            # there. Empty string clears the binding (both UUID + region).
            md = dict(row.metadata_ or {})
            md.pop("catalogue_region", None)
            if not patch.catalogue_id:
                row.catalogue_id = None
            else:
                try:
                    row.catalogue_id = uuid.UUID(patch.catalogue_id)
                except (ValueError, TypeError):
                    row.catalogue_id = None
                    md["catalogue_region"] = patch.catalogue_id
            row.metadata_ = md
        if patch.is_archived is not None:
            row.is_archived = patch.is_archived
        # v3-P10b: stage flips don't trigger regroup — they only affect
        # the SearchPlan hard filter at run-match time, not the
        # element grouping itself. Use ``model_fields_set`` so the user
        # can explicitly clear the pin with ``{"construction_stage": null}``;
        # plain ``is not None`` would treat that as "unchanged".
        if "construction_stage" in patch.model_fields_set:
            row.construction_stage = patch.construction_stage
        row.last_active_at = datetime.now(UTC)
        await db.flush()
        if regroup:
            await self.rebuild_groups(db, session_id)
        await db.refresh(row)
        return _to_session_read(row)

    async def touch_session(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> None:
        """Bump ``last_active_at`` so the resume picker reflects activity."""
        row = await db.get(MatchSession, session_id)
        if row is None:
            return
        row.last_active_at = datetime.now(UTC)
        await db.flush()

    async def list_sessions(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        *,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[schemas.SessionSummary]:
        """Compact list for the resume picker.

        Returns sessions ordered by ``last_active_at`` desc with
        per-session aggregate stats (group_count, confirmed, applied,
        total_value) so the picker can show "Boylston Crossing — RVT
        — 24 confirmed · €312k applied" without N+1 round-trips.
        """
        stmt = select(MatchSession).where(
            MatchSession.project_id == project_id,
        )
        if not include_archived:
            stmt = stmt.where(MatchSession.is_archived.is_(False))
        stmt = stmt.order_by(
            MatchSession.last_active_at.desc().nullslast(),
            MatchSession.created_at.desc(),
        ).limit(limit)
        sessions = (await db.execute(stmt)).scalars().all()
        if not sessions:
            return []

        sids = [s.id for s in sessions]
        # Group counts by status for every session in one query.
        stat_stmt = (
            select(MatchGroup.session_id, MatchGroup.status, func.count(MatchGroup.id))
            .where(MatchGroup.session_id.in_(sids))
            .group_by(MatchGroup.session_id, MatchGroup.status)
        )
        per_session: dict[uuid.UUID, dict[str, int]] = {sid: {} for sid in sids}
        for sid, status, n in (await db.execute(stat_stmt)).all():
            per_session.setdefault(sid, {})[status] = int(n)

        # Applied total value — sum applied groups' chosen unit_rate × qty
        # across linked CostItems. We pull the CostItem rate once per
        # candidate id.
        from app.modules.boq.service import _project_fx_map
        from app.modules.costs.models import CostItem
        from app.modules.projects.models import Project

        applied_stmt = (
            select(MatchGroup.session_id, MatchGroup.chosen_candidate_id, MatchGroup.quantities, MatchGroup.chosen_unit)
            .where(MatchGroup.session_id.in_(sids))
            .where(MatchGroup.status == "applied")
        )
        applied_rows = (await db.execute(applied_stmt)).all()
        cost_ids = list({r[1] for r in applied_rows if r[1] is not None})
        cost_lookup: dict[uuid.UUID, tuple[float, str]] = {}
        if cost_ids:
            ci_stmt = select(CostItem.id, CostItem.rate, CostItem.currency).where(CostItem.id.in_(cost_ids))
            for cid, rate, ccy in (await db.execute(ci_stmt)).all():
                # Don't paper over a missing currency — leave it empty
                # so the rollup downstream can either pick the dominant
                # currency from siblings or surface the gap explicitly.
                # Hard-defaulting to EUR mis-stamps non-EUR rates (e.g.
                # a BRL rate row with NULL currency would become EUR).
                cost_lookup[cid] = (_to_decimal(rate, 0.0), (ccy or "").upper())

        # Universality: stamp the session_summary.currency with the
        # project's currency, NOT the first matched candidate's currency.
        # A USD project that happens to have an applied row pointing at
        # an EUR-stamped CostItem must NOT show "1.9 B EUR" in the
        # session picker — that's confusing and wrong. We fetch project
        # currency once and convert per-row via FX before summing so the
        # total shown to the user is in the currency the operator sees
        # everywhere else (BOQ totals, dashboards, exports).
        proj = await db.get(Project, project_id)
        project_ccy = ""
        fx_map: dict[str, float] = {}
        if proj is not None:
            project_ccy = (getattr(proj, "currency", "") or "").strip().upper()
            try:
                fx_map = _project_fx_map(proj) or {}
            except Exception:  # noqa: BLE001 — defensive, fx is optional
                fx_map = {}

        def _convert(amount: float, src_ccy: str) -> tuple[float, bool]:
            """Return (amount_in_project_ccy, ok). ``ok`` is False when FX
            is missing — caller drops the row rather than stamping a
            misleading project-currency label on a foreign amount."""
            if not amount:
                return 0.0, True
            if not project_ccy:
                # No project currency known — pass through raw amount;
                # caller stamps with row's own currency.
                return amount, True
            if not src_ccy or src_ccy == project_ccy:
                return amount, True
            factor = fx_map.get(src_ccy)
            if factor is None or factor <= 0:
                # No FX rate — refuse to silently mis-label.
                return 0.0, False
            return amount * float(factor), True

        totals: dict[uuid.UUID, tuple[float, str | None]] = dict.fromkeys(sids, (0.0, None))
        for sid, cid, qty_raw, unit in applied_rows:
            if cid is None or cid not in cost_lookup:
                continue
            rate, ccy = cost_lookup[cid]
            qty = _quantity_for_unit(qty_raw or {}, unit or "pcs")
            row_total, ok = _convert(rate * qty, ccy)
            if not ok:
                # Drop rows we can't FX-convert into the project
                # currency. The session is still shown — just with a
                # smaller (or zero) total — which is honest.
                continue
            cur, prev_ccy = totals.get(sid, (0.0, None))
            # When project currency is known, every row converts into
            # it, so the stamp is unambiguous. When it isn't, we fall
            # back to whichever currency the first applied row carried
            # (legacy behaviour for projects without project.currency).
            stamp = project_ccy or prev_ccy or ccy or None
            totals[sid] = (cur + row_total, stamp)

        out: list[schemas.SessionSummary] = []
        for s in sessions:
            counts = per_session.get(s.id, {})
            tot, ccy = totals.get(s.id, (0.0, None))
            out.append(
                schemas.SessionSummary(
                    id=s.id,
                    project_id=s.project_id,
                    bim_model_id=s.bim_model_id,
                    name=s.name,
                    source=s.source,  # type: ignore[arg-type]
                    last_active_at=s.last_active_at,
                    created_at=s.created_at,
                    is_archived=bool(s.is_archived or False),
                    group_count=sum(counts.values()),
                    confirmed_count=counts.get("confirmed", 0),
                    applied_count=counts.get("applied", 0),
                    total_value=round(tot, 2),
                    currency=ccy,
                )
            )
        return out

    # ── Group rebuild (reads source, groups, persists) ───────────────

    async def rebuild_groups(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> int:
        """Re-read source elements, recompute groups, replace existing
        unmatched/suggested groups. Confirmed and applied groups are kept
        and re-keyed to the latest membership where possible."""
        sess = await db.get(MatchSession, session_id)
        if sess is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.session_not_found", locale=get_locale()))

        adapter = self._adapter(sess.source, db, sess)
        elements = await adapter.iter_elements(
            project_id=sess.project_id,
            bim_model_id=sess.bim_model_id,
            filters=sess.filters or None,
            excluded_categories=sess.excluded_categories or None,
            use_net_quantities=sess.use_net_quantities,
        )

        group_by = list(sess.group_by or [])
        # Group elements by composite key.
        bucket: dict[str, list[SourceElement]] = defaultdict(list)
        for elem in elements:
            key = signature.derive_group_key(group_by, elem.attributes)
            bucket[key].append(elem)

        # Wipe current rows that aren't in confirmed/applied state.
        await db.execute(
            delete(MatchGroup).where(
                MatchGroup.session_id == session_id,
                MatchGroup.status.in_(["unmatched", "suggested", "skipped"]),
            )
        )

        # Existing confirmed/applied groups — preserve, only refresh
        # element_ids/quantities so they track BIM re-imports. The
        # unmatched/suggested rows were just deleted above, so this
        # query naturally scopes to the survivor set (typically a
        # small minority of total groups even on huge sessions).
        existing = (
            (
                await db.execute(
                    select(MatchGroup).where(
                        MatchGroup.session_id == session_id,
                        MatchGroup.status.in_(["confirmed", "overridden", "applied", "tbd"]),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_keys = {row.group_key: row for row in existing}

        for key, members in bucket.items():
            qty = _aggregate_quantities(members)
            sample_values = members[0].attributes if members else {}
            label, sig = signature.normalize_signature(group_by, sample_values)
            existing_row = existing_keys.get(key)
            if existing_row is not None:
                existing_row.element_ids = [m.id for m in members]
                existing_row.element_count = len(members)
                existing_row.quantities = qty
                existing_row.signature = sig
                # Refresh chosen_unit when geometry catches up. A group
                # first seen with only count (CV/photo source pre-OCR)
                # would otherwise stay locked on `pcs` even after a
                # later BIM enrichment populates volume/area — and that
                # routes the group through the wrong dimensional gate
                # in apply_to_boq.
                if not existing_row.chosen_unit:
                    existing_row.chosen_unit = _pick_unit(
                        qty,
                        ifc_class=_ifc_class_from_group_key(key),
                    )
                continue
            row = MatchGroup(
                session_id=session_id,
                group_key=key,
                signature=sig,
                element_ids=[m.id for m in members],
                element_count=len(members),
                quantities=qty,
                chosen_unit=_pick_unit(qty, ifc_class=_ifc_class_from_group_key(key)),
                methods={},
                status="unmatched",
            )
            db.add(row)
        await db.flush()
        return len(bucket)

    async def list_groups(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> schemas.GroupListResponse:
        # Auto-rebuild if no groups yet (first hit on a fresh session).
        n = (
            await db.execute(select(func.count(MatchGroup.id)).where(MatchGroup.session_id == session_id))
        ).scalar_one()
        if n == 0:
            await self.rebuild_groups(db, session_id)

        stmt = select(MatchGroup).where(MatchGroup.session_id == session_id)
        if status:
            stmt = stmt.where(MatchGroup.status == status)
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await db.execute(total_stmt)).scalar_one()

        stmt = stmt.order_by(MatchGroup.element_count.desc()).offset(offset).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

        # Status counter for the summary bar.
        summary_stmt = (
            select(MatchGroup.status, func.count(MatchGroup.id))
            .where(MatchGroup.session_id == session_id)
            .group_by(MatchGroup.status)
        )
        summary = {row[0]: int(row[1]) for row in (await db.execute(summary_stmt)).all()}

        # Bulk-load element names for the up-to-3 sample-name preview per
        # group. One IN-query for the whole page beats N queries; the
        # mapping below picks the first three available names per group.
        # BIM is the only source that has element rows; for boq/text/etc.
        # adapters the lookup yields no hits and ``sample_names`` falls
        # through as []. Any failure is swallowed — the count-table is
        # the load-bearing piece, not the names.
        names_by_id: dict[str, str] = {}
        try:
            sample_ids: list[str] = []
            for r in rows:
                for eid in (r.element_ids or [])[:3]:
                    if eid:
                        sample_ids.append(str(eid))
            if sample_ids:
                from app.modules.bim_hub.models import BIMElement

                name_stmt = select(BIMElement.id, BIMElement.name).where(
                    BIMElement.id.in_(sample_ids),
                )
                for elem_id, elem_name in (await db.execute(name_stmt)).all():
                    if elem_name:
                        names_by_id[str(elem_id)] = elem_name
        except Exception:  # noqa: BLE001
            names_by_id = {}

        groups: list[schemas.GroupSummary] = []
        for r in rows:
            ifc_class = _ifc_class_from_group_key(r.group_key)
            meta = ifc_labels.lookup(ifc_class) if ifc_class else ifc_labels.lookup(None)
            qty = dict(r.quantities or {})
            unit = r.chosen_unit or _pick_unit(qty, ifc_class=ifc_class)
            primary = _quantity_for_unit(qty, unit)

            # Gross/net pair — only meaningful for area/volume units.
            gross_q = net_q = None
            opening_warning = False
            if unit == "m3":
                gross_q = qty.get("gross_volume_m3")
                net_q = qty.get("net_volume_m3")
            elif unit == "m2":
                gross_q = qty.get("gross_area_m2")
                net_q = qty.get("net_area_m2")
            if gross_q is not None and net_q is not None and gross_q > 0:
                # Catch the Revit IFC export bug — host has openings but
                # gross == net suggests the deduction never happened.
                opening_warning = abs(gross_q - net_q) < 0.01

            # Top-1 suggestion for the row preview (vector preferred, then lexical).
            top: MatchCandidate | None = None
            methods = r.methods or {}
            for mname in ("vector", "lexical", "resources", "llm"):
                lst = methods.get(mname) or []
                if lst:
                    try:
                        top = MatchCandidate(**lst[0])
                        break
                    except Exception:  # noqa: BLE001
                        continue

            confidence_band: str = "none"
            if r.confidence:
                confidence_band = confidence_band_for(_to_decimal(r.confidence, 0.0))

            groups.append(
                schemas.GroupSummary(
                    id=r.id,
                    group_key=r.group_key,
                    display_label=_human_group_label(r.group_key, None),
                    trade=meta.trade,  # type: ignore[arg-type]
                    is_subtractive=meta.is_subtractive,
                    signature=r.signature,
                    element_count=r.element_count,
                    quantities=qty,
                    chosen_unit=unit,
                    primary_quantity=float(primary or 0.0),
                    gross_quantity=gross_q,
                    net_quantity=net_q,
                    opening_warning=opening_warning,
                    chosen_method=r.chosen_method,
                    confidence=r.confidence,
                    confidence_band=confidence_band,  # type: ignore[arg-type]
                    status=r.status,  # type: ignore[arg-type]
                    boq_position_id=r.boq_position_id,
                    suggested_code=top.code if top else None,
                    suggested_description=top.description if top else None,
                    suggested_unit_rate=top.unit_rate if top else None,
                    suggested_currency=top.currency if top else None,
                    sample_names=[
                        names_by_id[str(eid)] for eid in (r.element_ids or [])[:3] if str(eid) in names_by_id
                    ],
                )
            )
        return schemas.GroupListResponse(
            session_id=session_id,
            total=int(total),
            groups=groups,
            summary=summary,
            confidence_high_threshold=CONFIDENCE_HIGH_THRESHOLD,
            confidence_medium_threshold=CONFIDENCE_MEDIUM_THRESHOLD,
        )

    async def get_group_detail(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        group_key: str,
    ) -> schemas.GroupDetail:
        stmt = select(MatchGroup).where(
            MatchGroup.session_id == session_id,
            MatchGroup.group_key == group_key,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.group_not_found", locale=get_locale()))
        # Deserialize methods JSON into MatchCandidate lists.
        methods_typed: dict[str, list[MatchCandidate]] = {}
        for name, raw_list in (row.methods or {}).items():
            methods_typed[name] = [MatchCandidate(**item) for item in (raw_list or [])]
        ifc_class = _ifc_class_from_group_key(row.group_key)
        meta = ifc_labels.lookup(ifc_class) if ifc_class else ifc_labels.lookup(None)
        qty = dict(row.quantities or {})
        unit = row.chosen_unit or _pick_unit(qty, ifc_class=ifc_class)
        gross_q = net_q = None
        opening_warning = False
        if unit == "m3":
            gross_q = qty.get("gross_volume_m3")
            net_q = qty.get("net_volume_m3")
        elif unit == "m2":
            gross_q = qty.get("gross_area_m2")
            net_q = qty.get("net_area_m2")
        if gross_q is not None and net_q is not None and gross_q > 0:
            opening_warning = abs(gross_q - net_q) < 0.01

        confidence_band: str = "none"
        if row.confidence:
            confidence_band = confidence_band_for(_to_decimal(row.confidence, 0.0))

        return schemas.GroupDetail(
            id=row.id,
            session_id=row.session_id,
            group_key=row.group_key,
            display_label=_human_group_label(row.group_key, None),
            trade=meta.trade,  # type: ignore[arg-type]
            is_subtractive=meta.is_subtractive,
            signature=row.signature,
            element_ids=list(row.element_ids or []),
            element_count=row.element_count,
            quantities=qty,
            chosen_unit=unit,
            gross_quantity=gross_q,
            net_quantity=net_q,
            opening_warning=opening_warning,
            methods=methods_typed,
            chosen_candidate_id=row.chosen_candidate_id,
            chosen_method=row.chosen_method,
            confidence=row.confidence,
            confidence_band=confidence_band,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            boq_position_id=row.boq_position_id,
            confirmed_by=row.confirmed_by,
            confirmed_at=row.confirmed_at,
            notes=row.notes,
        )

    # ── Run match ─────────────────────────────────────────────────────

    # In-memory progress store, keyed by session_id. Deliberately NOT
    # a DB column: the run-match request holds an open transaction for
    # the full match duration (30s-3min on big BIM models), and on
    # SQLite (the dev / single-VPS backend) any concurrent write to
    # ``MatchSession`` would contend for the global write lock,
    # deadlocking the server against the collab-lock sweeper and
    # Qdrant writers. A module-level dict is process-local — same as
    # the existing rate-limit + tenant caches — which is fine for the
    # single-worker dev deploy and the typical 1-worker uvicorn prod
    # install. Multi-worker deploys would degrade to "no progress
    # poll" gracefully (FE falls back to its legacy spinner); a
    # follow-up could move this to Redis with the same key shape.
    _progress: dict[str, dict[str, Any]] = {}

    @classmethod
    def _write_progress(
        cls,
        session_id: uuid.UUID,
        *,
        stage: str,
        stage_idx: int,
        groups_done: int = 0,
        groups_total: int = 0,
        started_at: str | None = None,
        status: str = "running",
        error: str | None = None,
    ) -> None:
        """Update the in-memory progress snapshot for the session.

        Stages mirror the runner's loop boundaries:

        * ``init``      — session loaded, project context fetched
        * ``elements``  — source adapter iterating BIM/Excel/text rows
        * ``ranking``   — per-group vector search + boost + rerank
        * ``save``      — flushing results / auto-confirms to DB
        * ``done``      — finished cleanly
        * ``error``     — exception bubbled out of the runner

        ``groups_done`` / ``groups_total`` populate the per-stage
        counter rendered in the FE timeline.
        """
        key = str(session_id)
        progress = dict(cls._progress.get(key) or {})
        progress.update(
            {
                "stage": stage,
                "stage_idx": stage_idx,
                "total_stages": 5,  # init, elements, ranking, save, done
                "groups_done": groups_done,
                "groups_total": groups_total,
                "status": status,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        if started_at is not None:
            progress["started_at"] = started_at
        if error is not None:
            progress["error"] = error
        cls._progress[key] = progress

    async def get_progress(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Read the latest progress snapshot for a match session.

        Reads from the in-memory ``_progress`` dict — see
        :meth:`_write_progress` for the design rationale (SQLite
        write-lock contention vs. the long-running match transaction).
        Returns a stable shape even when no match has ever been
        kicked off so the FE can render a neutral "idle" state
        without an endpoint shape fork.

        Auth still flows through ``_assert_session_access`` in the
        router so a poll for someone else's session returns 404.
        ``db`` is kept on the signature for symmetry with the rest of
        the service even though the body doesn't touch it.
        """
        del db  # see docstring — kept for signature symmetry
        progress = dict(self._progress.get(str(session_id)) or {})
        return {
            "stage": progress.get("stage", "idle"),
            "stage_idx": int(progress.get("stage_idx") or 0),
            "total_stages": int(progress.get("total_stages") or 5),
            "groups_done": int(progress.get("groups_done") or 0),
            "groups_total": int(progress.get("groups_total") or 0),
            "status": progress.get("status", "idle"),
            "started_at": progress.get("started_at"),
            "updated_at": progress.get("updated_at"),
            "error": progress.get("error"),
        }

    async def run_match(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        spec: schemas.RunMatchRequest,
    ) -> list[schemas.GroupSummary]:
        sess = await db.get(MatchSession, session_id)
        if sess is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.session_not_found", locale=get_locale()))

        # Stamp the initial progress snapshot before any work begins —
        # the wizard's MatchProgressCard polls /progress every ~800ms and
        # needs an authoritative "stage 1 / 5 — Loading" row to render
        # the timeline even while we're still doing the project-context
        # fetch. Wrapped in a flush so the next poll sees the change.
        import time as _time  # noqa: PLC0415 — local import keeps top-of-file clean

        run_started = _time.perf_counter()
        started_iso = datetime.now(UTC).isoformat()
        self._write_progress(
            session_id,
            stage="init",
            stage_idx=1,
            started_at=started_iso,
            status="running",
        )

        # Load project context once so envelopes/matchers can scope
        # candidate search by the project's expected currency and region
        # without per-group lookups. Failure here is non-fatal — empty
        # strings mean "no preference" and matchers fall back to the
        # global oe_cost_items table.
        from app.modules.projects.models import Project  # noqa: PLC0415

        proj = await db.get(Project, sess.project_id)
        project_currency = ""
        project_region = ""
        if proj is not None:
            project_currency = (getattr(proj, "currency", "") or "").strip().upper()
            project_region = (getattr(proj, "region", "") or "").strip().upper()

        threshold = _to_decimal(sess.auto_confirm_threshold, DEFAULT_AUTO_CONFIRM_THRESHOLD)

        # Auto-bind catalogue late: existing sessions created before this
        # check landed don't trigger the create_session path again, so we
        # repeat the bind here. Idempotent — no-op when already bound.
        bound_catalogue_id: str | None = None
        if spec.method == "vector":
            try:
                from app.modules.projects.service import (  # noqa: PLC0415
                    auto_bind_dominant_catalogue,
                )

                bound_catalogue_id = await auto_bind_dominant_catalogue(
                    db,
                    sess.project_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "match_elements: late auto-bind skipped for %s: %s",
                    sess.project_id,
                    exc,
                )

            # Stale-binding short-circuit: when ``auto_bind`` returns
            # ``None`` (no catalogue has rows in the active DB) or the
            # bound catalogue has 0 active rows, ranking every group
            # against an empty catalogue burns ~6 s per group on Qdrant
            # round-trips before returning [] candidates. Surface the
            # state via progress + a structured log line and skip the
            # ranker loop entirely so the FE can show a clear CTA.
            from app.modules.costs.models import CostItem  # noqa: PLC0415

            rows_in_bound = 0
            if bound_catalogue_id:
                try:
                    rows_in_bound = (
                        await db.execute(
                            select(func.count(CostItem.id))
                            .where(CostItem.is_active.is_(True))
                            .where(CostItem.region == bound_catalogue_id)
                        )
                    ).scalar() or 0
                except Exception:
                    rows_in_bound = 0
            # Probe both SQL and Qdrant. The bound catalogue is usable
            # if EITHER has data: SQL-only is the legacy CWICR install
            # path; Qdrant-only is the new v3 snapshot path (language
            # fallback bindings like ``US`` for an ASIA_PAC project have
            # 0 SQL rows but populated Qdrant collections).
            from app.core.match_service.ranker_qdrant import (  # noqa: PLC0415
                _resolve_catalog_status,
            )

            try:
                _cat_status, _sql_cnt, _vec_cnt = await _resolve_catalog_status(
                    db,
                    bound_catalogue_id,
                )
            except Exception:  # noqa: BLE001
                _cat_status, _sql_cnt, _vec_cnt = "ok", rows_in_bound, 1
            if not bound_catalogue_id or (rows_in_bound == 0 and _vec_cnt == 0):
                logger.warning(
                    "match_elements.run_match: bound catalogue has no "
                    "data — session=%s project=%s catalogue=%r "
                    "sql=%d vec=%d",
                    session_id,
                    sess.project_id,
                    bound_catalogue_id,
                    rows_in_bound,
                    _vec_cnt,
                )
                self._write_progress(
                    session_id,
                    stage="done",
                    stage_idx=5,
                    groups_done=0,
                    groups_total=0,
                    started_at=started_iso,
                    status="done",
                    error=f"no_catalogue_rows:{bound_catalogue_id or 'none'}",
                )
                total_ms = int((_time.perf_counter() - run_started) * 1000)
                logger.info(
                    "match_elements.run_match: session=%s method=%s "
                    "elements=0 groups_total=0 groups_with_candidates=0 "
                    "candidates=0 catalogue=%r status=no_catalogue_rows "
                    "total_ms=%d",
                    session_id,
                    spec.method,
                    bound_catalogue_id,
                    total_ms,
                )
                return []

            if _vec_cnt == 0:
                logger.warning(
                    "match_elements.run_match: bound catalogue has no "
                    "vectors — session=%s project=%s catalogue=%r "
                    "sql=%d vec=0",
                    session_id,
                    sess.project_id,
                    bound_catalogue_id,
                    _sql_cnt,
                )
                self._write_progress(
                    session_id,
                    stage="done",
                    stage_idx=5,
                    groups_done=0,
                    groups_total=0,
                    started_at=started_iso,
                    status="done",
                    error=f"catalog_not_vectorized:{bound_catalogue_id}",
                )
                total_ms = int((_time.perf_counter() - run_started) * 1000)
                logger.info(
                    "match_elements.run_match: session=%s method=%s "
                    "elements=0 groups_total=0 groups_with_candidates=0 "
                    "candidates=0 catalogue=%r status=catalog_not_vectorized "
                    "total_ms=%d",
                    session_id,
                    spec.method,
                    bound_catalogue_id,
                    total_ms,
                )
                return []

        matcher = self._matcher(spec.method, db)

        # Stage 2: loading source elements (BIM / Excel rows / text /
        # photo). For BIM models this is the per-element fetch + join
        # that can run a few seconds on a 50k-element model.
        self._write_progress(
            session_id,
            stage="elements",
            stage_idx=2,
            started_at=started_iso,
        )

        # Re-read source so we can compose envelopes per group.
        adapter = self._adapter(sess.source, db, sess)
        all_elements = await adapter.iter_elements(
            project_id=sess.project_id,
            bim_model_id=sess.bim_model_id,
            filters=sess.filters or None,
            excluded_categories=sess.excluded_categories or None,
            use_net_quantities=sess.use_net_quantities,
        )
        by_id = {e.id: e for e in all_elements}

        # Auto-rebuild groups on first run for this session — same guard
        # ``list_groups`` uses. Without this, the wizard's "create →
        # immediately run match" path returns an empty result list
        # because ``create_session`` doesn't seed any :class:`MatchGroup`
        # rows: it persists the session metadata, then the FE fires
        # ``POST /sessions/{id}/match`` straight away, the SELECT below
        # finds zero rows, and the for-loop never executes. Symptom is
        # exactly what users report — "matching is fast but produces
        # nothing" / "matching does nothing on TOP / Any stage". Mirrors
        # ``list_groups``' behaviour at L1502-1508 so the two entry
        # points are now consistent. Idempotent on subsequent runs
        # because rebuild_groups preserves confirmed/applied rows and
        # only re-derives unmatched/suggested ones.
        existing_group_count = (
            await db.execute(select(func.count(MatchGroup.id)).where(MatchGroup.session_id == session_id))
        ).scalar_one()
        if existing_group_count == 0:
            await self.rebuild_groups(db, session_id)

        target_keys = spec.group_keys
        stmt = select(MatchGroup).where(MatchGroup.session_id == session_id)
        if target_keys:
            stmt = stmt.where(MatchGroup.group_key.in_(target_keys))
        else:
            stmt = (
                stmt.where(MatchGroup.status.in_(["unmatched", "suggested"]))
                .order_by(MatchGroup.element_count.desc())
                .limit(spec.max_groups)
            )
        rows = (await db.execute(stmt)).scalars().all()

        # Stage 3: per-group ranking. The for-loop below dominates wall
        # time on real matches — each iteration runs one Qdrant vector
        # search + sparse fusion + region/unit boost + (sometimes) BGE
        # cross-encoder rerank. Counter updates every group so the FE
        # bar advances visibly even on small (5-10 group) sessions.
        groups_total = len(rows)
        self._write_progress(
            session_id,
            stage="ranking",
            stage_idx=3,
            groups_done=0,
            groups_total=groups_total,
            started_at=started_iso,
        )

        out: list[schemas.GroupSummary] = []
        total_candidates = 0
        groups_with_candidates = 0
        # Throttle the per-group progress flush: at >50 groups, writing
        # JSON + flushing every iteration adds measurable overhead on
        # SQLite (the dev/VPS backend). The 4-group cadence keeps the FE
        # bar moving at ~25fps-equivalent while halving the write
        # amplification on big sessions.
        flush_every = 1 if groups_total <= 20 else 4
        for idx, grow in enumerate(rows):
            members = [by_id[eid] for eid in (grow.element_ids or []) if eid in by_id]
            if not members:
                continue
            try:
                envelope = _envelope_from_group(
                    grow.group_key,
                    members,
                    grow.quantities or {},
                    source=sess.source or "bim",
                    construction_stage=getattr(sess, "construction_stage", None),
                    project_currency=project_currency,
                    project_region=project_region,
                )
            except ValueError as exc:
                # ValueError from envelope construction means the source
                # type wasn't in :data:`SourceType` (Literal narrows to a
                # closed set), or a structured field violated its
                # constraint. Either way, skipping is safer than crashing
                # the whole match run — but log so we notice if it
                # regresses.
                logger.warning(
                    "run_match: skip group %s — envelope build failed: %s",
                    grow.group_key,
                    exc,
                )
                continue
            try:
                candidates = await matcher.rank(
                    envelope=envelope,
                    project_id=sess.project_id,
                    catalogue_id=sess.catalogue_id,
                    top_k=spec.top_k,
                )
            except Exception as exc:  # noqa: BLE001 — log + degrade per group
                logger.warning(
                    "Matcher %s failed for group %s: %s",
                    spec.method,
                    grow.group_key,
                    exc,
                )
                candidates = []

            total_candidates += len(candidates)
            if candidates:
                groups_with_candidates += 1

            # Persist per-method results.
            methods = dict(grow.methods or {})
            methods[spec.method] = [c.model_dump() for c in candidates]
            grow.methods = methods

            # Auto-confirm if top candidate >= threshold AND group not
            # already confirmed.
            if candidates and grow.status in ("unmatched", "suggested") and candidates[0].score >= threshold:
                top = candidates[0]
                # MatchCandidate now carries a real CostItem.id end-to-end,
                # so apply_to_boq can read the rate without a second lookup.
                grow.chosen_candidate_id = uuid.UUID(top.id) if top.id else None
                grow.chosen_method = "auto"
                grow.confidence = f"{top.score:.4f}"
                grow.status = "confirmed"
                grow.confirmed_at = datetime.now(UTC)
            elif candidates and grow.status == "unmatched":
                grow.status = "suggested"
                grow.confidence = f"{candidates[0].score:.4f}"

            ifc_class = _ifc_class_from_group_key(grow.group_key)
            meta = ifc_labels.lookup(ifc_class) if ifc_class else ifc_labels.lookup(None)
            unit = grow.chosen_unit or _pick_unit(grow.quantities or {}, ifc_class=ifc_class)
            primary = _quantity_for_unit(grow.quantities or {}, unit)
            top = candidates[0] if candidates else None
            confidence_band = "none"
            if grow.confidence:
                confidence_band = confidence_band_for(_to_decimal(grow.confidence, 0.0))
            out.append(
                schemas.GroupSummary(
                    id=grow.id,
                    group_key=grow.group_key,
                    display_label=_human_group_label(grow.group_key, None),
                    trade=meta.trade,  # type: ignore[arg-type]
                    is_subtractive=meta.is_subtractive,
                    signature=grow.signature,
                    element_count=grow.element_count,
                    quantities=dict(grow.quantities or {}),
                    chosen_unit=unit,
                    primary_quantity=float(primary or 0.0),
                    chosen_method=grow.chosen_method,
                    confidence=grow.confidence,
                    confidence_band=confidence_band,  # type: ignore[arg-type]
                    status=grow.status,  # type: ignore[arg-type]
                    boq_position_id=grow.boq_position_id,
                    suggested_code=top.code if top else None,
                    suggested_description=top.description if top else None,
                    suggested_unit_rate=top.unit_rate if top else None,
                    suggested_currency=top.currency if top else None,
                    sample_names=[m.name for m in members[:3] if m.name],
                )
            )

            # In-memory only counter update — we deliberately avoid
            # ``await db.flush()`` here. On SQLite, flushing per group
            # holds the write lock open across the next group's read
            # of MatchGroup, which deadlocks against the BIM hub's
            # Qdrant + DB writes happening concurrently. The progress
            # poll reads the session row via a separate transaction
            # so the in-memory mutation isn't visible until the final
            # flush below — but the per-stage transitions (init →
            # elements → ranking → save → done) already give the FE
            # enough signal at the boundaries that matter. The
            # counter inside ranking advances atomically with the
            # stage flip to ``save``.
            if (idx + 1) % flush_every == 0 or idx == groups_total - 1:
                self._write_progress(
                    session_id,
                    stage="ranking",
                    stage_idx=3,
                    groups_done=idx + 1,
                    groups_total=groups_total,
                    started_at=started_iso,
                )

        # Stage 4: persisting results (auto-confirms, signature
        # backfills, session activity bump). The bulk of the DB writes
        # already happened in the per-group iterations above; this
        # stage usually flashes by in < 200ms.
        self._write_progress(
            session_id,
            stage="save",
            stage_idx=4,
            groups_done=groups_total,
            groups_total=groups_total,
            started_at=started_iso,
        )
        # Bump session activity so the resume picker picks this run up.
        if rows:
            sess.last_active_at = datetime.now(UTC)
        await db.flush()

        # Stage 5: terminal — the FE polling card watches for this to
        # fade out and reveal the results pane.
        self._write_progress(
            session_id,
            stage="done",
            stage_idx=5,
            groups_done=groups_total,
            groups_total=groups_total,
            started_at=started_iso,
            status="done",
        )
        # One observable log line per match run — element_count is the
        # source-side fanout, candidate_count is what came back from the
        # ranker stack across all groups, hits_groups tracks how many of
        # those groups got *any* candidate (a 15-group run that returns
        # 0 for every group is the user's "матчинг никакой не происходит"
        # symptom). total_ms is wall-clock — slow runs jump out
        # immediately when grepping logs.
        total_ms = int((_time.perf_counter() - run_started) * 1000)
        logger.info(
            "match_elements.run_match: session=%s method=%s elements=%d "
            "groups_total=%d groups_with_candidates=%d candidates=%d "
            "stage=%s total_ms=%d",
            session_id,
            spec.method,
            len(all_elements),
            groups_total,
            groups_with_candidates,
            total_candidates,
            getattr(sess, "construction_stage", None) or "(none)",
            total_ms,
        )
        return out

    # ── Confirm ───────────────────────────────────────────────────────

    async def confirm(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        spec: schemas.ConfirmMatchRequest,
        confirmed_by: uuid.UUID | None,
    ) -> schemas.GroupDetail:
        stmt = select(MatchGroup).where(
            MatchGroup.session_id == session_id,
            MatchGroup.group_key == spec.group_key,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.group_not_found", locale=get_locale()))
        # candidate_id is now properly nullable both in the schema and the
        # FK column. None means "manual override / no library row" — the
        # group is still recorded as confirmed and the apply step writes
        # a custom Position with whatever description the user chose.
        cid = spec.candidate_id
        row.chosen_candidate_id = cid
        row.chosen_method = spec.method
        row.confidence = f"{spec.confidence:.4f}" if spec.confidence is not None else row.confidence
        row.status = "confirmed"
        row.confirmed_by = confirmed_by
        confirmed_at = datetime.now(UTC)
        row.confirmed_at = confirmed_at
        if spec.signature_fields_override is not None:
            row.signature_fields = list(spec.signature_fields_override)

        # MAPPING_PROCESS.md §10 — backfill the user-feedback columns on
        # the matching search_log row so the §10 alerts can fire
        # ("user_picked_rank > 4 for >20% of requests" → re-train).
        # Best-effort: never fail the confirm because of an analytics
        # side-effect.
        try:
            picked_rank, picked_code_from_methods = _derive_picked_rank_and_code(
                row.methods,
                chosen_method=spec.method,
                chosen_candidate_id=cid,
            )
            await _record_pick_to_search_log(
                db,
                project_id=None,  # session→project derivable via JOIN if needed
                session_id=session_id,
                group_id=row.id,
                picked_rate_code=picked_code_from_methods,
                picked_rank=picked_rank,
                picked_at=confirmed_at,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("confirm: search_log backfill skipped: %s", exc)

        # Cross-project library — write a template row when requested.
        # Only meaningful when we have a real cost-item id to link to.
        if spec.save_to_template_library and row.signature and cid is not None:
            existing = (
                await db.execute(
                    select(MatchTemplate).where(
                        MatchTemplate.signature == row.signature,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                sess = await db.get(MatchSession, session_id)
                tmpl = MatchTemplate(
                    tenant_id=None,  # Phase A.10 wires tenant resolution
                    signature=row.signature,
                    label=row.group_key,
                    cwicr_position_id=cid,
                    source_fields=list(row.signature_fields or (sess.group_by if sess else []) or []),
                    use_count=1,
                    last_used_at=datetime.now(UTC),
                    created_by=confirmed_by,
                )
                db.add(tmpl)
            else:
                existing.use_count = int(existing.use_count or 0) + 1
                existing.last_used_at = datetime.now(UTC)

        # Bump session activity so the resume picker reflects the work.
        sess = await db.get(MatchSession, session_id)
        if sess is not None:
            sess.last_active_at = datetime.now(UTC)

        await db.flush()
        return await self.get_group_detail(db, session_id, spec.group_key)

    async def bulk_confirm(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        spec: schemas.BulkConfirmRequest,
        confirmed_by: uuid.UUID | None,
    ) -> int:
        stmt = select(MatchGroup).where(
            MatchGroup.session_id == session_id,
            MatchGroup.status == "suggested",
        )
        if spec.group_keys:
            stmt = stmt.where(MatchGroup.group_key.in_(spec.group_keys))
        # Cap the per-call confirm batch so a 10k-group session doesn't
        # block the request thread. The frontend can repeat the call to
        # progress through the full set; status counters update live.
        stmt = stmt.order_by(MatchGroup.element_count.desc()).limit(_BULK_BATCH_LIMIT)
        rows = (await db.execute(stmt)).scalars().all()

        n = 0
        for r in rows:
            conf = _to_decimal(r.confidence, 0.0)
            if conf < spec.threshold:
                continue
            # Pick the top candidate from the best matcher run so the
            # apply step has a CostItem to read the rate from.
            if r.chosen_candidate_id is None and isinstance(r.methods, dict):
                best_id: uuid.UUID | None = None
                best_score = -1.0
                for cands in r.methods.values():
                    if not isinstance(cands, list) or not cands:
                        continue
                    top = cands[0]
                    if not isinstance(top, dict):
                        continue
                    score = float(top.get("score") or 0.0)
                    cid_raw = top.get("id")
                    if cid_raw and score > best_score:
                        try:
                            best_id = uuid.UUID(str(cid_raw))
                            best_score = score
                        except (TypeError, ValueError):
                            continue
                if best_id is not None:
                    r.chosen_candidate_id = best_id
            r.status = "confirmed"
            r.chosen_method = r.chosen_method or "auto"
            r.confirmed_by = confirmed_by
            r.confirmed_at = datetime.now(UTC)
            n += 1
        await db.flush()
        return n

    # ── Attributes / categories (drives the chip-bars) ────────────────

    async def list_attribute_keys(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> list[schemas.AttributeKey]:
        sess = await db.get(MatchSession, session_id)
        if sess is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.session_not_found", locale=get_locale()))
        adapter = self._adapter(sess.source, db, sess)
        keys = await adapter.list_attribute_keys(sess.project_id, sess.bim_model_id)
        return [schemas.AttributeKey(key=k, sample_values=[]) for k in keys]

    async def list_categories(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> list[schemas.CategoryCount]:
        sess = await db.get(MatchSession, session_id)
        if sess is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.session_not_found", locale=get_locale()))
        adapter = self._adapter(sess.source, db, sess)
        cats = await adapter.list_categories(sess.project_id, sess.bim_model_id)
        out: list[schemas.CategoryCount] = []
        for c, n in cats:
            meta = ifc_labels.lookup(c)
            out.append(
                schemas.CategoryCount(
                    category=c,
                    display_label=meta.en_label,
                    trade=meta.trade,  # type: ignore[arg-type]
                    is_subtractive=meta.is_subtractive,
                    count=n,
                )
            )
        return out

    # ── Templates ─────────────────────────────────────────────────────

    async def list_templates(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID | None,
    ) -> list[schemas.TemplateRead]:
        stmt = select(MatchTemplate)
        if tenant_id is not None:
            stmt = stmt.where(MatchTemplate.tenant_id == tenant_id)
        stmt = stmt.order_by(MatchTemplate.use_count.desc()).limit(500)
        rows = (await db.execute(stmt)).scalars().all()
        return [schemas.TemplateRead.model_validate(r) for r in rows]

    async def lookup_templates(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID | None,
        signatures: list[str],
    ) -> schemas.TemplateLookupResponse:
        if not signatures:
            return schemas.TemplateLookupResponse(matches={})
        stmt = select(MatchTemplate).where(
            MatchTemplate.signature.in_(signatures),
        )
        if tenant_id is not None:
            stmt = stmt.where(MatchTemplate.tenant_id == tenant_id)
        rows = (await db.execute(stmt)).scalars().all()
        return schemas.TemplateLookupResponse(
            matches={r.signature: schemas.TemplateRead.model_validate(r) for r in rows},
        )

    async def delete_template(
        self,
        db: AsyncSession,
        template_id: uuid.UUID,
    ) -> None:
        await db.execute(
            delete(MatchTemplate).where(MatchTemplate.id == template_id),
        )

    # ── Stubs (Phase A.5b/A.9/A.12) ───────────────────────────────────

    async def split_group(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        group_key: str,
        spec: schemas.GroupSplitRequest,
    ) -> schemas.GroupDetail:
        raise NotImplementedError("split_group — Phase A.5b")

    async def merge_groups(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        group_key: str,
        spec: schemas.GroupMergeRequest,
    ) -> schemas.GroupDetail:
        raise NotImplementedError("merge_groups — Phase A.5b")

    async def skip_group(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        group_key: str,
    ) -> schemas.GroupDetail:
        stmt = select(MatchGroup).where(
            MatchGroup.session_id == session_id,
            MatchGroup.group_key == group_key,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.group_not_found", locale=get_locale()))
        row.status = "skipped"
        await db.flush()
        return await self.get_group_detail(db, session_id, group_key)

    async def apply_to_boq(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        spec: schemas.ApplyToBoqRequest,
        applied_by: uuid.UUID | None,
    ) -> schemas.ApplyToBoqResponse:
        """Apply confirmed groups to a project's BOQ.

        Phase A.9 implementation. For each confirmed group:
            * Looks up the chosen CWICR position (or resources entry).
            * Creates one BOQ Position with description, unit, qty, rate.
            * Stores ``cad_element_ids`` so the BOQ row links back to BIM.
            * Auto-loads CWICR ``components`` as resource sub-rows when
              the CWICR position carries them, scaling each component
              quantity by ``factor × parent_quantity``. Components without
              a factor field default to factor=1.0.
        """
        from fastapi import HTTPException

        from app.modules.boq.models import BOQ, Position
        from app.modules.boq.service import _project_fx_map
        from app.modules.costs.models import CostItem
        from app.modules.projects.models import Project

        sess = await db.get(MatchSession, session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail=translate("errors.session_not_found", locale=get_locale()))
        project = await db.get(Project, sess.project_id)
        # Base currency selection (no EUR hardcode):
        #   1. project.currency if set (operator's choice).
        #   2. Currency stamped on the project's region row in
        #      `_REGION_CURRENCY` (e.g. RU_STPETERSBURG → RUB).
        #   3. Empty string — downstream knows to pick the dominant
        #      applied-rate currency rather than mis-stamping a default.
        # Defaulting to EUR for non-Eurozone projects (BR, RU, JP, …)
        # was the source of the BRL totals showing "€" headers in v2.8.x.
        base_currency = ""
        if project and getattr(project, "currency", None):
            base_currency = str(project.currency).upper()
        if not base_currency and project is not None:
            from app.modules.costs.router import _REGION_CURRENCY  # noqa: PLC0415

            project_region = (getattr(project, "region", "") or "").strip().upper()
            base_currency = _REGION_CURRENCY.get(project_region, "")
        fx_map = _project_fx_map(project)

        # ── 1. Resolve target BOQ ────────────────────────────────────
        boq_id = spec.target_boq_id
        if boq_id is None:
            stmt = select(BOQ).where(BOQ.project_id == sess.project_id).order_by(BOQ.created_at.asc())
            existing_boq = (await db.execute(stmt)).scalars().first()
            if existing_boq is None:
                if spec.dry_run:
                    boq_id = None
                else:
                    # Name the new BOQ after the project + source so a
                    # workspace with N projects doesn't end up with N
                    # rows literally named "BOQ from BIM matches".
                    project_label = getattr(project, "name", None) or f"Project {str(sess.project_id)[:8]}"
                    new_boq = BOQ(
                        project_id=sess.project_id,
                        name=f"{project_label} — {sess.source.upper()}",
                        description=(
                            f"Auto-created by Match Elements module (session {str(sess.id)[:8]}, source={sess.source})"
                        ),
                        status="draft",
                    )
                    db.add(new_boq)
                    await db.flush()
                    boq_id = new_boq.id
            else:
                boq_id = existing_boq.id

        # ── 2. Load confirmed groups + their candidates ──────────────
        stmt = select(MatchGroup).where(
            MatchGroup.session_id == session_id,
            MatchGroup.status == "confirmed",
        )
        if spec.group_keys:
            stmt = stmt.where(MatchGroup.group_key.in_(spec.group_keys))
        # Cap per-call apply size so a 10k-group session doesn't block.
        # Largest groups (by element_count) go first so the user sees
        # the highest-impact lines write to the BOQ first.
        stmt = stmt.order_by(MatchGroup.element_count.desc()).limit(_APPLY_BATCH_LIMIT)
        groups = (await db.execute(stmt)).scalars().all()

        # Pre-load all candidate CostItems in one shot.
        cost_ids = [g.chosen_candidate_id for g in groups if g.chosen_candidate_id]
        cost_items: dict[uuid.UUID, CostItem] = {}
        if cost_ids:
            ci_stmt = select(CostItem).where(CostItem.id.in_(cost_ids))
            for ci in (await db.execute(ci_stmt)).scalars().all():
                cost_items[ci.id] = ci

        positions_preview: list[schemas.ApplyPositionPreview] = []
        positions_created = 0

        # Track ordinal counter for new positions.
        max_ord = 0
        if boq_id is not None and not spec.dry_run:
            from sqlalchemy import func as sa_func

            existing_positions = (
                await db.execute(select(sa_func.count(Position.id)).where(Position.boq_id == boq_id))
            ).scalar_one()
            max_ord = int(existing_positions or 0)

        from app.core.match_service.boosts.unit import (
            _DIMENSION_GROUP,
            _normalise_unit,
        )

        for g in groups:
            unit = g.chosen_unit or "pcs"
            qty = _quantity_for_unit(g.quantities or {}, unit)
            ci = cost_items.get(g.chosen_candidate_id) if g.chosen_candidate_id else None

            description = ci.description if ci else g.group_key
            # CWICR catalogues sometimes encode a multiplier into the
            # unit string ("100 м3 @ 5,311,861.57 EUR" → 53,118.62
            # EUR/m3). Strip the leading numeric so qty × rate stays
            # dimensionally honest.
            raw_unit = (ci.unit if ci else unit) or unit
            mult, position_unit = _split_unit_multiplier(raw_unit)
            raw_rate = _to_decimal(ci.rate, 0.0) if ci else 0.0
            unit_rate = (raw_rate / mult) if mult > 0 else raw_rate

            # Dimensional gate: if the catalog row is priced in m³ but
            # the group quantity is `pcs`, the line total is meaningless.
            # Zero the rate rather than apply it — the row still appears
            # in the BOQ preview so the estimator can see the mismatch
            # and pick a different match manually. We fold cyrillic /
            # german / spanish units onto the canonical set first so the
            # gate fires for catalogues that don't use latin codes.
            env_unit_canon = _normalise_unit_cross_locale(unit) or _normalise_unit(unit)
            cand_unit_canon = _normalise_unit_cross_locale(position_unit) or _normalise_unit(position_unit)
            env_dim = _DIMENSION_GROUP.get(env_unit_canon, "")
            cand_dim = _DIMENSION_GROUP.get(cand_unit_canon, "")
            if env_dim and cand_dim and env_dim != cand_dim:
                unit_rate = 0.0

            currency = (ci.currency if ci else base_currency) or base_currency
            classification = ci.classification if ci else {}
            section_path = []
            if isinstance(classification, dict):
                # Pick classification-standard preference universally —
                # explicit project.classification_standard wins, else
                # fall back to the region-preferred standard so US/UK/
                # LATAM projects get the right taxonomy without per-
                # project setup. Helper covers all known regions.
                preferred_order = _resolve_classification_order(
                    getattr(project, "classification_standard", None),
                    getattr(project, "region", None),
                )
                for std in preferred_order:
                    code = classification.get(std)
                    if code:
                        section_path.append(f"{_CLASSIFICATION_STANDARD_LABELS[std]} {code}")
                        break

            # Build resource previews from CostItem.components when present.
            resource_previews: list[schemas.ApplyResourcePreview] = []
            if ci and isinstance(ci.components, list):
                for comp in ci.components:
                    if not isinstance(comp, dict):
                        continue
                    factor = float(comp.get("factor", 1.0) or 1.0)
                    resource_previews.append(
                        schemas.ApplyResourcePreview(
                            description=str(comp.get("description") or comp.get("name") or comp.get("code") or ""),
                            factor=factor,
                            quantity=factor * qty,
                            unit=str(comp.get("unit") or ""),
                            unit_rate=float(comp.get("unit_rate") or comp.get("rate") or 0),
                        )
                    )

            positions_preview.append(
                schemas.ApplyPositionPreview(
                    group_key=g.group_key,
                    section_path=section_path or ["Unclassified"],
                    description=description,
                    unit=position_unit,
                    quantity=qty,
                    unit_rate=unit_rate,
                    currency=currency,
                    resources=resource_previews,
                )
            )

            # ── 3. Commit (when not dry_run) ─────────────────────────
            if not spec.dry_run and boq_id is not None:
                max_ord += 1
                ordinal = f"{max_ord:04d}"
                metadata: dict[str, Any] = {
                    "match_session_id": str(session_id),
                    "match_group_key": g.group_key,
                    "match_signature": g.signature or "",
                    "match_method": g.chosen_method or "manual",
                    "match_confidence": g.confidence or "",
                }
                if ci:
                    metadata["cost_item_id"] = str(ci.id)
                if resource_previews:
                    metadata["match_components"] = [rp.model_dump(mode="json") for rp in resource_previews]

                pos = Position(
                    boq_id=boq_id,
                    parent_id=None,
                    ordinal=ordinal,
                    description=description,
                    unit=position_unit,
                    quantity=f"{qty:.4f}",
                    unit_rate=f"{unit_rate:.4f}",
                    total=f"{qty * unit_rate:.4f}",
                    classification=classification if isinstance(classification, dict) else {},
                    source="cad_import",
                    confidence=g.confidence or "",
                    cad_element_ids=list(g.element_ids or []),
                    validation_status="pending",
                    metadata_=metadata,
                    sort_order=max_ord,
                )
                db.add(pos)
                await db.flush()
                g.boq_position_id = pos.id
                g.status = "applied"
                positions_created += 1

        # Bump session activity so the resume picker reflects the apply.
        if not spec.dry_run and positions_created:
            sess.last_active_at = datetime.now(UTC)

        # Roll up grand total in the project's base currency, applying
        # Project.fx_rates to each line so a multi-currency project
        # (USD project that pulled CWICR rates priced in EUR) reports
        # a meaningful headline number rather than apples-and-oranges.
        # Lines whose CostItem.currency matches base_currency pass through
        # untouched. Resource sub-rows are likewise summed in base via
        # _resource_total_in_base so the position breakdown stays
        # consistent with the headline.
        # v3 §10 — money rollup uses Decimal end-to-end so cents never
        # drift through float intermediates. p.unit_rate / p.line_total
        # / grand_total are all Decimal on the schema; p.quantity stays
        # float (measurement, not money).
        grand_total: Decimal = Decimal("0")
        _Q2 = Decimal("0.01")
        for p in positions_preview:
            qty_dec = Decimal(str(p.quantity))
            line: Decimal = qty_dec * p.unit_rate
            line_currency = (p.currency or base_currency).upper()
            if line_currency != base_currency and fx_map:
                fx = fx_map.get(line_currency)
                if fx:
                    try:
                        line = line * Decimal(str(fx))
                    except (TypeError, ValueError, InvalidOperation):
                        pass
            p.line_total = line.quantize(_Q2, rounding=ROUND_HALF_UP)
            grand_total += line
        currency: str | None = base_currency

        await db.flush()
        # In dry_run mode positions_created stays at 0 (nothing was
        # written). Surface the would-be count so the UI can render
        # "47 positions will be created" accurately.
        reported_positions_created = positions_created if not spec.dry_run else len(positions_preview)
        return schemas.ApplyToBoqResponse(
            dry_run=spec.dry_run,
            boq_id=boq_id,
            positions_created=reported_positions_created,
            positions=positions_preview,
            grand_total=grand_total.quantize(_Q2, rounding=ROUND_HALF_UP),
            currency=currency,
        )

    async def no_match(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        spec: schemas.NoMatchRequest,
    ) -> schemas.GroupDetail:
        stmt = select(MatchGroup).where(
            MatchGroup.session_id == session_id,
            MatchGroup.group_key == spec.group_key,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=translate("errors.group_not_found", locale=get_locale()))
        if spec.action == "tbd":
            row.status = "tbd"
            row.notes = "Pending — no good catalogue match"
        elif spec.action == "custom":
            # Phase A.9 will write a Position with custom rate; for now
            # we just flag the group and stash the spec in metadata.
            row.status = "tbd"
            row.notes = (
                f"Custom: {spec.custom_description or '(no description)'} "
                f"@ {spec.custom_rate or 0} per {spec.custom_unit or 'pcs'}"
            )
            row.metadata_ = {
                **(row.metadata_ or {}),
                "custom_position": spec.model_dump(mode="json"),
            }
        elif spec.action == "rfq":
            # Phase A.12 — wire to procurement RFQ creation.
            row.status = "tbd"
            row.notes = "Sent to RFQ (procurement integration pending)"
        await db.flush()
        return await self.get_group_detail(db, session_id, spec.group_key)


_service_singleton: MatchElementsService | None = None


def get_service() -> MatchElementsService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = MatchElementsService()
    return _service_singleton
