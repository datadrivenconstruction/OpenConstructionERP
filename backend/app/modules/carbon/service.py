"""‌⁠‍Carbon & Sustainability service — pure carbon-math + orchestration.

Pure functions:
    * normalise_quantity_to_factor_unit
    * compute_embodied_entry_carbon
    * compute_scope1_co2e / compute_scope2_co2e
    * match_cost_item_to_epd
    * compute_inventory_totals
    * compare_alternatives
    * compute_carbon_intensity
    * is_target_met
    * validate_epd_file_magic       (R7 deep-improve: EPD upload gate)
    * ingest_epd_document            (R7 deep-improve: high-level wrapper)

Orchestration (DB-touching):
    * CarbonService — wraps repositories, emits events, generates reports
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.carbon.models import (
    CarbonInventory,
    CarbonTarget,
    EmbodiedCarbonEntry,
    EPDRecord,
    MaterialCarbonFactor,
    Scope1Entry,
    Scope2Entry,
    Scope3Entry,
    SustainabilityReport,
)
from app.modules.carbon.repository import (
    EmbodiedEntryRepository,
    EPDRecordRepository,
    InventoryRepository,
    MaterialFactorRepository,
    Scope1EntryRepository,
    Scope2EntryRepository,
    Scope3EntryRepository,
    SustainabilityReportRepository,
    TargetRepository,
)
from app.modules.carbon.schemas import (
    CarbonInventoryCreate,
    CarbonInventoryUpdate,
    CarbonTargetCreate,
    CarbonTargetUpdate,
    EmbodiedCarbonEntryCreate,
    EmbodiedCarbonEntryUpdate,
    EPDRecordCreate,
    EPDRecordUpdate,
    MaterialCarbonFactorCreate,
    MaterialCarbonFactorUpdate,
    Scope1EntryCreate,
    Scope1EntryUpdate,
    Scope2EntryCreate,
    Scope2EntryUpdate,
    Scope3EntryCreate,
    Scope3EntryUpdate,
    SustainabilityReportCreate,
    SustainabilityReportPayload,
    SustainabilityReportUpdate,
)

logger = logging.getLogger(__name__)


# ── EPD upload magic-byte gate (R7 deep-improve) ──────────────────────────
# EPD documents must be one of: PDF (binary), XML (ILCD+EPD / EN 15804),
# or JSON (EC3 / BuildingTransparency API). Any other binary content is
# rejected at the boundary with HTTP 415, never 500. This is a defence-
# in-depth gate alongside the MIME-type sniff in the router — the magic
# byte check is authoritative.
ALLOWED_EPD_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "text/xml",
        "application/xml",
        "application/json",
    },
)

# Maps detected format → tuple of byte signatures that begin a valid file
# of that format. Order does not matter; first match wins in the scan.
EPD_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    # XML may start with declaration (<?xml) or a bare root tag we know.
    # ILCD wrapper roots, EPD top-level tags, and ECO Platform variants.
    "xml": (
        b"<?xml",
        b"<EPD",
        b"<epd",
        b"<processDataSet",
        b"<ProcessDataSet",
    ),
    # JSON EPDs must be objects (EC3 / BuildingTransparency payloads).
    # Bare arrays / scalars are not valid EPD documents.
    "json": (b"{",),
}

# Minimum bytes required to even attempt magic-byte detection.
_EPD_MAGIC_MIN_BYTES: int = 4


def validate_epd_file_magic(payload: bytes) -> str:
    """Detect the EPD file format from its magic bytes.

    Returns the format name ("pdf" | "xml" | "json") on success.
    Raises ``ValueError`` whose message contains ``"415"`` when the payload
    is empty, too short, or does not match any allowed signature. The
    router wraps this in an HTTPException(415, ...).
    """
    if not payload:
        raise ValueError("415: empty upload")
    if len(payload) < _EPD_MAGIC_MIN_BYTES:
        raise ValueError("415: payload too short for magic-byte detection")
    # Strip a leading UTF-8 BOM so it doesn't shift the signature.
    head = payload.lstrip(b"\xef\xbb\xbf").lstrip()
    if not head:
        raise ValueError("415: payload empty after BOM/whitespace strip")
    for fmt, signatures in EPD_MAGIC_BYTES.items():
        for sig in signatures:
            if head.startswith(sig):
                # JSON: extra guard — must be parsable AND an object
                # (arrays / scalars are not valid EPD documents).
                if fmt == "json":
                    try:
                        decoded = json.loads(head.decode("utf-8", "strict"))
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        raise ValueError(
                            f"415: JSON payload is not parsable ({exc})",
                        ) from None
                    if not isinstance(decoded, dict):
                        raise ValueError(
                            "415: JSON payload must be an object (EPD record)",
                        )
                return fmt
    raise ValueError(
        "415: unsupported EPD file format (expected PDF, XML or JSON)",
    )


async def ingest_epd_document(
    *,
    service: Any,
    file_bytes: bytes,
    identifier: str,
    gwp_a1a3: Decimal,
    product_name: str,
    material_class: str,
) -> Any:
    """Service-level EPD ingest gate that validates magic bytes first.

    Raises ``HTTPException(415)`` if the payload is not a valid EPD file.
    On success delegates to ``service.ingest_epd_by_identifier`` and
    returns the created record.
    """
    try:
        validate_epd_file_magic(file_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from None
    return await service.ingest_epd_by_identifier(
        identifier=identifier,
        gwp_a1a3=gwp_a1a3,
        product_name=product_name,
        material_class=material_class,
    )


# ── Errors ────────────────────────────────────────────────────────────────


class UnitMismatchError(ValueError):
    """‌⁠‍Raised when two units cannot be converted without extra info."""


# ── Pure helpers ──────────────────────────────────────────────────────────


_LENGTH_ALIASES: dict[str, str] = {
    "m": "m",
    "metre": "m",
    "meter": "m",
}
_AREA_ALIASES: dict[str, str] = {
    "m2": "m2",
    "m^2": "m2",
    "sqm": "m2",
    "m²": "m2",
}
_VOLUME_ALIASES: dict[str, str] = {
    "m3": "m3",
    "m^3": "m3",
    "cbm": "m3",
    "m³": "m3",
}
_MASS_ALIASES: dict[str, str] = {
    "kg": "kg",
    "kilogram": "kg",
}
_TONNE_ALIASES: dict[str, str] = {
    "t": "t",
    "tonne": "t",
    "ton": "t",
    "tn": "t",
}
_PIECE_ALIASES: dict[str, str] = {
    "pcs": "pcs",
    "pc": "pcs",
    "piece": "pcs",
    "stk": "pcs",
}


def _canon_unit(unit: str | None) -> str:
    """‌⁠‍Lowercase a unit and resolve common aliases."""
    if not unit:
        return ""
    u = unit.strip().lower()
    for table in (
        _LENGTH_ALIASES,
        _AREA_ALIASES,
        _VOLUME_ALIASES,
        _MASS_ALIASES,
        _TONNE_ALIASES,
        _PIECE_ALIASES,
    ):
        if u in table:
            return table[u]
    return u


def normalise_quantity_to_factor_unit(
    qty: Decimal | float | int | str,
    qty_unit: str,
    factor_unit: str,
    density_kg_per_m3: Decimal | float | int | None = None,
) -> Decimal:
    """Convert ``qty`` from ``qty_unit`` into ``factor_unit``.

    Supported conversions:
        * Identity (same unit family).
        * m3 ↔ kg via ``density_kg_per_m3`` (must be supplied).
        * t ↔ kg (factor 1000).

    Raises:
        UnitMismatchError: incompatible units and no density supplied.
    """
    quantity = Decimal(str(qty))
    src = _canon_unit(qty_unit)
    dst = _canon_unit(factor_unit)

    if src == dst:
        return quantity

    # t ↔ kg
    if src == "t" and dst == "kg":
        return quantity * Decimal("1000")
    if src == "kg" and dst == "t":
        return quantity / Decimal("1000")

    # Volume <-> mass via density
    if src == "m3" and dst == "kg":
        if density_kg_per_m3 is None:
            raise UnitMismatchError(
                "Cannot convert m3 to kg without density_kg_per_m3",
            )
        return quantity * Decimal(str(density_kg_per_m3))
    if src == "kg" and dst == "m3":
        if density_kg_per_m3 is None or Decimal(str(density_kg_per_m3)) == 0:
            raise UnitMismatchError(
                "Cannot convert kg to m3 without non-zero density_kg_per_m3",
            )
        return quantity / Decimal(str(density_kg_per_m3))
    if src == "m3" and dst == "t":
        if density_kg_per_m3 is None:
            raise UnitMismatchError("Cannot convert m3 to t without density_kg_per_m3")
        return (quantity * Decimal(str(density_kg_per_m3))) / Decimal("1000")
    if src == "t" and dst == "m3":
        if density_kg_per_m3 is None or Decimal(str(density_kg_per_m3)) == 0:
            raise UnitMismatchError(
                "Cannot convert t to m3 without non-zero density_kg_per_m3",
            )
        return (quantity * Decimal("1000")) / Decimal(str(density_kg_per_m3))

    raise UnitMismatchError(
        f"Incompatible units: {qty_unit!r} -> {factor_unit!r}",
    )


def compute_embodied_entry_carbon(
    quantity: Decimal | float | int | str,
    quantity_unit: str,
    factor_value: Decimal | float | int | str,
    factor_unit: str,
    density: Decimal | float | int | None = None,
) -> Decimal:
    """Pure: compute embodied carbon kg = normalised_qty × factor_value."""
    normalised = normalise_quantity_to_factor_unit(
        quantity,
        quantity_unit,
        factor_unit,
        density,
    )
    return normalised * Decimal(str(factor_value))


def compute_scope1_co2e(
    litres: Decimal | float | int | str,
    fuel_type: str,
    factor: Decimal | float | int | str,
) -> Decimal:
    """Pure: scope-1 emissions = litres × factor.

    ``fuel_type`` is accepted but the emission factor is the source of
    truth — the caller is expected to supply the per-fuel factor.
    """
    _ = fuel_type  # accepted for API symmetry / future fuel-aware logic
    return Decimal(str(litres)) * Decimal(str(factor))


def compute_scope2_co2e(
    kwh: Decimal | float | int | str,
    factor: Decimal | float | int | str,
) -> Decimal:
    """Pure: scope-2 emissions = kWh × factor."""
    return Decimal(str(kwh)) * Decimal(str(factor))


def match_cost_item_to_epd(
    cost_item_payload: dict[str, Any],
    epds: Iterable[EPDRecord | dict[str, Any]],
    strategy: str = "exact",
) -> EPDRecord | dict[str, Any] | None:
    """Pure: pick the best EPD for a cost-item payload.

    Args:
        cost_item_payload: dict with at least ``material_class`` and
            optionally ``manufacturer`` / ``region``.
        epds: iterable of EPDRecord or dicts.
        strategy: ``'exact'`` -> require material_class + manufacturer
            match; ``'fuzzy'`` -> material_class match only.

    Returns:
        First match, or ``None``.
    """
    target_class = (cost_item_payload.get("material_class") or "").strip().lower()
    target_manufacturer = (cost_item_payload.get("manufacturer") or "").strip().lower()
    target_region = (cost_item_payload.get("region") or "").strip().lower()
    if not target_class:
        return None

    def _attr(epd: Any, key: str) -> str:
        if isinstance(epd, dict):
            return (epd.get(key) or "").strip().lower()
        return (getattr(epd, key, None) or "").strip().lower()

    candidates = [e for e in epds if _attr(e, "material_class") == target_class]
    if not candidates:
        return None

    if strategy == "exact":
        if not target_manufacturer:
            return None
        for epd in candidates:
            if _attr(epd, "manufacturer") == target_manufacturer:
                if not target_region or _attr(epd, "region") == target_region:
                    return epd
        return None

    if strategy == "fuzzy":
        # Prefer same region if specified, otherwise the first one.
        if target_region:
            for epd in candidates:
                if _attr(epd, "region") == target_region:
                    return epd
        return candidates[0]

    return None


def _stage_bucket(stage: str) -> str:
    """Map a (possibly granular) EN 15978 stage to a rollup bucket.

    The rollup keeps six buckets: ``a1a3 / a4 / a5 / b / c / d``. Granular
    codes are folded into their parent module so emissions are NEVER
    silently dropped from the inventory total:

        a1 / a2 / a3 / a1a3  -> a1a3   (product stage)
        a4                   -> a4     (transport to site)
        a5                   -> a5     (construction / installation)
        b, b1..b7            -> b      (use stage)
        c, c1..c4            -> c      (end of life)
        d                    -> d      (beyond system boundary)

    Unknown codes return the input unchanged so they fall through the
    ``if bucket in stage_totals`` guard (no accidental mis-bucketing).
    """
    s = (stage or "").strip().lower().replace(" ", "")
    if s in ("a1", "a2", "a3", "a1a3"):
        return "a1a3"
    if s == "a4":
        return "a4"
    if s == "a5":
        return "a5"
    if s == "b" or (len(s) == 2 and s[0] == "b" and s[1].isdigit()):
        return "b"
    if s == "c" or (len(s) == 2 and s[0] == "c" and s[1].isdigit()):
        return "c"
    if s == "d":
        return "d"
    return s


def compute_inventory_totals(
    inventory_id: uuid.UUID,
    embodied_entries: Iterable[Any],
    scope1_entries: Iterable[Any] = (),
    scope2_entries: Iterable[Any] = (),
    scope3_entries: Iterable[Any] = (),
) -> dict[str, Any]:
    """Pure: roll up A1-A5/B/C/D embodied + scope 1/2/3 operational.

    Returns a dict ready to be JSON-serialised into ``CarbonInventory.totals``.
    """
    stage_totals: dict[str, Decimal] = {
        "a1a3": Decimal("0"),
        "a4": Decimal("0"),
        "a5": Decimal("0"),
        "b": Decimal("0"),
        "c": Decimal("0"),
        "d": Decimal("0"),
    }
    for entry in embodied_entries:
        raw_stage = (getattr(entry, "stage", None) or "a1a3").strip().lower()
        carbon = Decimal(str(getattr(entry, "carbon_kg", 0) or 0))
        bucket = _stage_bucket(raw_stage)
        if bucket in stage_totals:
            stage_totals[bucket] += carbon

    a1a5 = stage_totals["a1a3"] + stage_totals["a4"] + stage_totals["a5"]

    s1 = sum(
        (Decimal(str(getattr(e, "total_co2e_kg", 0) or 0)) for e in scope1_entries),
        Decimal("0"),
    )
    s2 = sum(
        (Decimal(str(getattr(e, "total_co2e_kg", 0) or 0)) for e in scope2_entries),
        Decimal("0"),
    )
    s3 = sum(
        (Decimal(str(getattr(e, "total_co2e_kg", 0) or 0)) for e in scope3_entries),
        Decimal("0"),
    )

    operational = s1 + s2
    total = a1a5 + stage_totals["b"] + stage_totals["c"] + operational + s3
    return {
        "inventory_id": str(inventory_id),
        "embodied_a1a3": str(stage_totals["a1a3"]),
        "embodied_a4": str(stage_totals["a4"]),
        "embodied_a5": str(stage_totals["a5"]),
        "embodied_a1a5": str(a1a5),
        "embodied_b": str(stage_totals["b"]),
        "embodied_c": str(stage_totals["c"]),
        "embodied_d": str(stage_totals["d"]),
        "scope1": str(s1),
        "scope2": str(s2),
        "scope3": str(s3),
        "operational": str(operational),
        "end_of_life": str(stage_totals["c"]),
        "total": str(total),
    }


def compare_alternatives(
    current_entry: Any,
    alternative_factors: Iterable[Any],
) -> list[dict[str, Any]]:
    """Pure: rank alternatives by carbon savings (desc)."""
    current_factor_value = Decimal(str(getattr(current_entry, "factor_value_used", 0) or 0))
    current_carbon = Decimal(str(getattr(current_entry, "carbon_kg", 0) or 0))
    # Recover quantity from carbon / factor (avoid re-running unit-normalisation).
    if current_factor_value != 0:
        normalised_qty = current_carbon / current_factor_value
    else:
        normalised_qty = Decimal("0")

    out: list[dict[str, Any]] = []
    for alt in alternative_factors:
        alt_factor_value = Decimal(
            str(getattr(alt, "manual_override_factor", None) or getattr(alt, "factor_value", None) or 0)
        )
        alt_carbon = normalised_qty * alt_factor_value
        savings = current_carbon - alt_carbon
        if current_carbon != 0:
            savings_pct = float(savings / current_carbon) * 100.0
        else:
            savings_pct = 0.0
        out.append(
            {
                "factor_id": getattr(alt, "id", None) or getattr(alt, "factor_id", None),
                "factor_value": alt_factor_value,
                "carbon_kg": alt_carbon,
                "savings_kg": savings,
                "savings_pct": savings_pct,
                "confidence": getattr(alt, "confidence", "medium"),
            }
        )

    out.sort(key=lambda r: r["savings_kg"], reverse=True)
    return out


def compute_carbon_intensity(
    total_kg: Decimal | float | int | str,
    area_m2: Decimal | float | int | str,
) -> Decimal:
    """Pure: kgCO2e / m². Returns 0 if area is non-positive."""
    area = Decimal(str(area_m2))
    if area <= 0:
        return Decimal("0")
    return Decimal(str(total_kg)) / area


def is_target_met(
    target: Any,
    current_value: Decimal | float | int | str,
) -> bool:
    """Pure: target is met when ``current_value <= target_value``."""
    target_value = Decimal(str(getattr(target, "target_value", 0) or 0))
    return Decimal(str(current_value)) <= target_value


# ── EPD external sync hook ────────────────────────────────────────────────


def epd_database_sync_hook(
    source: str = "oekobaudat",
    region: str | None = None,
) -> list[dict[str, Any]]:
    """Hook stub for future external EPD-DB sync.

    Real implementations (Ökobaudat, ICE, EC3) plug in here and return a
    list of EPD payloads ready to be inserted via ``EPDRecordRepository``.
    The default no-op returns an empty list so callers can rely on the
    signature.
    """
    _ = source, region
    return []


# ── EN 15978 lifecycle stages ─────────────────────────────────────────────

EN_15978_STAGES: frozenset[str] = frozenset(
    {
        # Product stage
        "a1",
        "a2",
        "a3",
        "a1a3",
        # Construction process
        "a4",
        "a5",
        # Use stage
        "b1",
        "b2",
        "b3",
        "b4",
        "b5",
        "b6",
        "b7",
        "b",
        # End of life
        "c1",
        "c2",
        "c3",
        "c4",
        "c",
        # Benefits beyond system boundary
        "d",
    }
)


def validate_en15978_stage(stage: str) -> str:
    """Pure: normalise an EN 15978 stage code and raise on invalid input.

    Accepts case-insensitive input. Returns the canonical lowercase form.
    Raises ValueError on unknown stage.
    """
    if not stage or not isinstance(stage, str):
        raise ValueError("stage is required")
    norm = stage.strip().lower().replace(" ", "")
    if norm not in EN_15978_STAGES:
        raise ValueError(
            f"unknown EN 15978 stage {stage!r}; allowed: {sorted(EN_15978_STAGES)}",
        )
    return norm


# ── Grid emission factors (Scope 2 lookup) ────────────────────────────────

# Country-year grid factors (kg CO2e / kWh), location-based.
# Sources: IEA Emissions Factors 2024 (developed countries), DEFRA UK
# GHG Conversion Factors 2024, EPA eGRID 2022 (US average), Umweltbundesamt
# (DE 2023). Values rounded to 4 decimal places.
GRID_FACTORS_DEFAULT: dict[tuple[str, int], dict[str, Any]] = {
    # Germany — Umweltbundesamt
    ("DE", 2023): {"factor": "0.3800", "method": "location", "source": "UBA 2023"},
    ("DE", 2022): {"factor": "0.4340", "method": "location", "source": "UBA 2022"},
    ("DE", 2021): {"factor": "0.4200", "method": "location", "source": "UBA 2021"},
    # UK — DEFRA
    ("GB", 2024): {"factor": "0.2070", "method": "location", "source": "DEFRA 2024"},
    ("GB", 2023): {"factor": "0.2070", "method": "location", "source": "DEFRA 2023"},
    ("GB", 2022): {"factor": "0.1934", "method": "location", "source": "DEFRA 2022"},
    # USA — EPA eGRID national average
    ("US", 2022): {"factor": "0.3856", "method": "location", "source": "EPA eGRID 2022"},
    ("US", 2021): {"factor": "0.3924", "method": "location", "source": "EPA eGRID 2021"},
    # France — IEA
    ("FR", 2023): {"factor": "0.0560", "method": "location", "source": "IEA 2023"},
    # Spain — IEA
    ("ES", 2023): {"factor": "0.1740", "method": "location", "source": "IEA 2023"},
    # Italy — IEA
    ("IT", 2023): {"factor": "0.2700", "method": "location", "source": "IEA 2023"},
    # Netherlands — IEA
    ("NL", 2023): {"factor": "0.3240", "method": "location", "source": "IEA 2023"},
    # Poland — IEA
    ("PL", 2023): {"factor": "0.7100", "method": "location", "source": "IEA 2023"},
    # India — IEA
    ("IN", 2023): {"factor": "0.7080", "method": "location", "source": "IEA 2023"},
    # China — IEA
    ("CN", 2023): {"factor": "0.5810", "method": "location", "source": "IEA 2023"},
    # Brazil — IEA
    ("BR", 2023): {"factor": "0.0820", "method": "location", "source": "IEA 2023"},
    # Australia — IEA
    ("AU", 2023): {"factor": "0.5670", "method": "location", "source": "IEA 2023"},
    # Canada — IEA
    ("CA", 2023): {"factor": "0.1300", "method": "location", "source": "IEA 2023"},
    # UAE — IEA
    ("AE", 2023): {"factor": "0.4720", "method": "location", "source": "IEA 2023"},
    # Saudi Arabia — IEA
    ("SA", 2023): {"factor": "0.6720", "method": "location", "source": "IEA 2023"},
    # South Africa — IEA
    ("ZA", 2023): {"factor": "0.9410", "method": "location", "source": "IEA 2023"},
    # Norway — IEA (largely hydropower)
    ("NO", 2023): {"factor": "0.0190", "method": "location", "source": "IEA 2023"},
    # Sweden — IEA
    ("SE", 2023): {"factor": "0.0090", "method": "location", "source": "IEA 2023"},
    # Russia — IEA
    ("RU", 2023): {"factor": "0.3970", "method": "location", "source": "IEA 2023"},
    # Turkey — IEA
    ("TR", 2023): {"factor": "0.4380", "method": "location", "source": "IEA 2023"},
    # Japan — IEA
    ("JP", 2023): {"factor": "0.4360", "method": "location", "source": "IEA 2023"},
}


def lookup_grid_factor_default(
    country_code: str,
    year: int,
) -> dict[str, Any] | None:
    """Pure: return the built-in grid factor for (country_code, year).

    Falls back to the nearest year (older or same) for the same country if
    the exact year isn't catalogued. Returns ``None`` if the country is
    not in the static catalogue.
    """
    cc = (country_code or "").strip().upper()
    if not cc:
        return None
    # Exact match first
    if (cc, year) in GRID_FACTORS_DEFAULT:
        hit = GRID_FACTORS_DEFAULT[(cc, year)]
        return {
            "country_code": cc,
            "year": year,
            "factor_kg_co2e_per_kwh": Decimal(hit["factor"]),
            "method": hit["method"],
            "source": hit["source"],
            "fallback": False,
        }
    # Same-country fallback: nearest year ≤ requested
    same_country = [(yr, v) for (c, yr), v in GRID_FACTORS_DEFAULT.items() if c == cc and yr <= year]
    if not same_country:
        # Or any year for this country (newest available)
        same_country = [(yr, v) for (c, yr), v in GRID_FACTORS_DEFAULT.items() if c == cc]
    if not same_country:
        return None
    same_country.sort(key=lambda t: t[0], reverse=True)
    best_year, best = same_country[0]
    return {
        "country_code": cc,
        "year": best_year,
        "requested_year": year,
        "factor_kg_co2e_per_kwh": Decimal(best["factor"]),
        "method": best["method"],
        "source": best["source"],
        "fallback": True,
    }


# ── EPD identifier ingestion (parse only — no network IO in tests) ────────


def parse_epd_identifier(identifier: str) -> dict[str, Any]:
    """Pure: parse an EPD identifier or URL into a source + canonical id.

    Recognised forms:
        - "oekobaudat:1.4.01.04"          → {source: oekobaudat, id: 1.4.01.04}
        - "ice:concrete_c30_37"           → {source: ice, id: concrete_c30_37}
        - "ec3:abc123"                    → {source: ec3, id: abc123}
        - "epd_international:EPD-123-XYZ" → {source: epd_international, id: EPD-123-XYZ}
        - bare URL — extract the source from the host:
            https://www.oekobaudat.de/datensatz/.../ID
            https://www.environdec.com/library/epd-XYZ
            https://buildingtransparency.org/ec3/.../ID
    Returns ``{source, id, raw_identifier}``.

    Raises ValueError on unrecognised input.
    """
    if not identifier or not isinstance(identifier, str):
        raise ValueError("identifier is required")
    s = identifier.strip()
    # Prefix form
    if ":" in s and not s.startswith("http"):
        source, _, ident = s.partition(":")
        source = source.strip().lower()
        ident = ident.strip()
        if not ident:
            raise ValueError("identifier missing after ':'")
        if source in ("oekobaudat", "okobaudat", "obd"):
            source = "oekobaudat"
        elif source in ("ice", "ice_db"):
            source = "ice"
        elif source in ("ec3", "buildingtransparency"):
            source = "ec3"
        elif source in ("epd_international", "environdec", "epd-norge"):
            source = "epd_international"
        else:
            raise ValueError(f"unknown EPD source prefix {source!r}")
        return {"source": source, "id": ident, "raw_identifier": s}
    # URL form
    s_lower = s.lower()
    if s_lower.startswith("http"):
        if "oekobaudat" in s_lower:
            source = "oekobaudat"
        elif "environdec.com" in s_lower:
            source = "epd_international"
        elif "buildingtransparency.org" in s_lower or "ec3" in s_lower:
            source = "ec3"
        elif "ice" in s_lower:
            source = "ice"
        else:
            raise ValueError(f"cannot determine EPD source from URL: {s}")
        # Strip trailing slashes, take the final non-empty path component as the ID
        tail = [p for p in s.rstrip("/").split("/") if p]
        ident = tail[-1] if tail else s
        return {"source": source, "id": ident, "raw_identifier": s}
    raise ValueError(f"unrecognised EPD identifier format: {s}")


# ── TCFD / ISSB structured report body ────────────────────────────────────


TCFD_SECTIONS = (
    "governance",
    "strategy",
    "risk_management",
    "metrics_and_targets",
)


def build_tcfd_report_body(
    inventory_totals: dict[str, Any],
    *,
    project_name: str = "",
    period_start: str = "",
    period_end: str = "",
    targets: list[Any] = (),
    intensity_metrics: dict[str, Any] | None = None,
    narrative: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Pure: build a TCFD / ISSB S2-shaped report body.

    Sections returned:
        - governance: who oversees climate-related decisions
        - strategy: identified risks + transition plan summary
        - risk_management: process for identifying climate risks
        - metrics_and_targets: Scope 1/2/3 + intensity + targets

    Narrative override: callers pass per-section text; missing sections
    get a sensible default placeholder noting the data they should
    supply at finalisation.
    """
    narrative = narrative or {}
    totals = inventory_totals or {}
    intensity = intensity_metrics or {}

    def _section_narrative(sec: str, default: str) -> str:
        return narrative.get(sec, "").strip() or default

    return {
        "framework": "tcfd",
        "project_name": project_name,
        "period_start": period_start,
        "period_end": period_end,
        "sections": {
            "governance": {
                "narrative": _section_narrative(
                    "governance",
                    "Board oversight of climate-related risks is exercised through "
                    "the Audit & Risk Committee. Management responsibility sits "
                    "with the Sustainability Lead, reporting quarterly.",
                ),
            },
            "strategy": {
                "narrative": _section_narrative(
                    "strategy",
                    "Identified physical risks include heat / flood / wildfire "
                    "exposure on active sites; transition risks include carbon "
                    "pricing on cement & steel and stricter procurement criteria. "
                    "Transition plan: substitution of GGBS-blended cement, "
                    "electrified plant, low-carbon supplier preference.",
                ),
            },
            "risk_management": {
                "narrative": _section_narrative(
                    "risk_management",
                    "Climate risks are inventoried per project at tender phase, "
                    "scored on likelihood × impact, and tracked in the project "
                    "risk register alongside non-climate risks.",
                ),
            },
            "metrics_and_targets": {
                "scope_1_kg_co2e": str(totals.get("scope1", "0")),
                "scope_2_kg_co2e": str(totals.get("scope2", "0")),
                "scope_3_kg_co2e": str(totals.get("scope3", "0")),
                "embodied_a1a5_kg_co2e": str(totals.get("embodied_a1a5", "0")),
                "total_kg_co2e": str(totals.get("total", "0")),
                "intensity": intensity,
                "targets": [
                    {
                        "name": getattr(t, "name", ""),
                        "target_type": getattr(t, "target_type", ""),
                        "baseline_value": str(getattr(t, "baseline_value", "0")),
                        "target_value": str(getattr(t, "target_value", "0")),
                        "baseline_year": getattr(t, "baseline_year", None),
                        "target_year": getattr(t, "target_year", None),
                        "status": getattr(t, "status", "active"),
                    }
                    for t in targets
                ],
            },
        },
    }


# ── Intensity (per-m² / per-€1M revenue) ─────────────────────────────────


def compute_intensity_metrics(
    total_kg_co2e: Decimal | float | int | str,
    *,
    gross_floor_area_m2: Decimal | float | int | None = None,
    net_internal_area_m2: Decimal | float | int | None = None,
    revenue_million: Decimal | float | int | None = None,
) -> dict[str, Any]:
    """Pure: compute intensity in kgCO2e / m² GFA, m² NIA, per €1M revenue.

    Returns the available metrics only (skips ones whose denominator is
    None or zero).
    """
    out: dict[str, Any] = {}
    total = Decimal(str(total_kg_co2e or 0))
    if gross_floor_area_m2 is not None:
        gfa = Decimal(str(gross_floor_area_m2))
        if gfa > 0:
            out["per_m2_gfa"] = str((total / gfa).quantize(Decimal("0.0001")))
    if net_internal_area_m2 is not None:
        nia = Decimal(str(net_internal_area_m2))
        if nia > 0:
            out["per_m2_nia"] = str((total / nia).quantize(Decimal("0.0001")))
    if revenue_million is not None:
        rev = Decimal(str(revenue_million))
        if rev > 0:
            out["per_million_revenue"] = str((total / rev).quantize(Decimal("0.0001")))
    return out


# ── Service orchestrator ──────────────────────────────────────────────────


class CarbonService:
    """DB-touching orchestration. Permission checks happen in the router."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.epd_repo = EPDRecordRepository(session)
        self.factor_repo = MaterialFactorRepository(session)
        self.inventory_repo = InventoryRepository(session)
        self.embodied_repo = EmbodiedEntryRepository(session)
        self.scope1_repo = Scope1EntryRepository(session)
        self.scope2_repo = Scope2EntryRepository(session)
        self.scope3_repo = Scope3EntryRepository(session)
        self.target_repo = TargetRepository(session)
        self.report_repo = SustainabilityReportRepository(session)

    # ── EPD ──────────────────────────────────────────────────────────────
    async def create_epd(self, data: EPDRecordCreate) -> EPDRecord:
        # ``EPDRecord.epd_id`` is unique. Reject a duplicate with a clean 409
        # instead of letting the DB raise an uncaught IntegrityError that
        # surfaces to the client as an opaque 500. We do BOTH a pre-flight
        # lookup AND catch IntegrityError — the second guard closes a
        # race-condition window between two concurrent ingests of the same
        # external EPD id.
        existing = await self.epd_repo.get_by_epd_id(data.epd_id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An EPD record with id '{data.epd_id}' already exists",
            )
        epd = EPDRecord(**data.model_dump(exclude={"metadata"}))
        epd.metadata_ = data.metadata
        try:
            return await self.epd_repo.create(epd)
        except IntegrityError as exc:
            logger.info(
                "carbon.epd.create_race",
                extra={"epd_id": data.epd_id, "error": str(exc)},
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An EPD record with id '{data.epd_id}' already exists",
            ) from exc

    async def get_epd(self, epd_id: uuid.UUID) -> EPDRecord:
        epd = await self.epd_repo.get_by_id(epd_id)
        if epd is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="EPD not found")
        return epd

    async def list_epds(
        self,
        *,
        material_class: str | None = None,
        region: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[EPDRecord], int]:
        return await self.epd_repo.list_filtered(
            material_class=material_class,
            region=region,
            offset=offset,
            limit=limit,
        )

    async def update_epd(self, epd_id: uuid.UUID, data: EPDRecordUpdate) -> EPDRecord:
        await self.get_epd(epd_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.epd_repo.update_fields(epd_id, **fields)
        return await self.get_epd(epd_id)

    async def delete_epd(self, epd_id: uuid.UUID) -> None:
        await self.get_epd(epd_id)
        await self.epd_repo.delete(epd_id)

    async def sync_epds_from_external(
        self,
        source: str = "oekobaudat",
        region: str | None = None,
    ) -> int:
        """Run the external-sync hook stub and persist any returned payloads."""
        payloads = epd_database_sync_hook(source=source, region=region)
        count = 0
        for payload in payloads:
            try:
                model = EPDRecord(**{k: v for k, v in payload.items() if k != "metadata"})
                model.metadata_ = payload.get("metadata", {})
                await self.epd_repo.create(model)
                count += 1
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to ingest EPD payload from %s", source)
        return count

    # ── Material factors ─────────────────────────────────────────────────
    async def create_factor(
        self,
        data: MaterialCarbonFactorCreate,
    ) -> MaterialCarbonFactor:
        factor = MaterialCarbonFactor(**data.model_dump(exclude={"metadata"}))
        factor.metadata_ = data.metadata
        return await self.factor_repo.create(factor)

    async def get_factor(self, factor_id: uuid.UUID) -> MaterialCarbonFactor:
        factor = await self.factor_repo.get_by_id(factor_id)
        if factor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Material factor not found",
            )
        return factor

    async def list_factors(
        self,
        *,
        cost_item_id: uuid.UUID | None = None,
        region: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[MaterialCarbonFactor], int]:
        return await self.factor_repo.list_filtered(
            cost_item_id=cost_item_id,
            region=region,
            offset=offset,
            limit=limit,
        )

    async def update_factor(
        self,
        factor_id: uuid.UUID,
        data: MaterialCarbonFactorUpdate,
    ) -> MaterialCarbonFactor:
        await self.get_factor(factor_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.factor_repo.update_fields(factor_id, **fields)
        return await self.get_factor(factor_id)

    async def delete_factor(self, factor_id: uuid.UUID) -> None:
        await self.get_factor(factor_id)
        await self.factor_repo.delete(factor_id)

    # ── Inventory ───────────────────────────────────────────────────────
    async def create_inventory(
        self,
        data: CarbonInventoryCreate,
        user_id: str | None = None,
    ) -> CarbonInventory:
        inv = CarbonInventory(**data.model_dump(exclude={"metadata"}))
        inv.metadata_ = data.metadata
        inv.created_by = user_id
        return await self.inventory_repo.create(inv)

    async def get_inventory(self, inventory_id: uuid.UUID) -> CarbonInventory:
        inv = await self.inventory_repo.get_by_id(inventory_id)
        if inv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Inventory not found",
            )
        return inv

    # ── IDOR project-access helpers (Round-5) ────────────────────────────
    # These return the owning project_id for the entity addressed by the
    # router URL / body, so the router can call ``verify_project_access``
    # before touching cross-tenant rows. Raise HTTP 404 on missing rows so
    # callers don't leak the existence of UUIDs they don't own.
    async def get_inventory_project_id(self, inventory_id: uuid.UUID) -> uuid.UUID:
        inv = await self.get_inventory(inventory_id)
        return inv.project_id

    async def get_embodied_project_id(self, entry_id: uuid.UUID) -> uuid.UUID:
        entry = await self.get_embodied_entry(entry_id)
        inv = await self.get_inventory(entry.inventory_id)
        return inv.project_id

    async def get_scope1_project_id(self, entry_id: uuid.UUID) -> uuid.UUID:
        entry = await self.get_scope1(entry_id)
        inv = await self.get_inventory(entry.inventory_id)
        return inv.project_id

    async def get_scope2_project_id(self, entry_id: uuid.UUID) -> uuid.UUID:
        entry = await self.get_scope2(entry_id)
        inv = await self.get_inventory(entry.inventory_id)
        return inv.project_id

    async def get_scope3_project_id(self, entry_id: uuid.UUID) -> uuid.UUID:
        entry = await self.get_scope3(entry_id)
        inv = await self.get_inventory(entry.inventory_id)
        return inv.project_id

    async def get_target_project_id(self, target_id: uuid.UUID) -> uuid.UUID:
        target = await self.get_target(target_id)
        return target.project_id

    async def get_report_project_id(self, report_id: uuid.UUID) -> uuid.UUID:
        report = await self.get_report(report_id)
        return report.project_id

    async def list_inventories(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[CarbonInventory], int]:
        return await self.inventory_repo.list_for_project(project_id, offset=offset, limit=limit)

    async def update_inventory(
        self,
        inventory_id: uuid.UUID,
        data: CarbonInventoryUpdate,
    ) -> CarbonInventory:
        await self.get_inventory(inventory_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.inventory_repo.update_fields(inventory_id, **fields)
        return await self.get_inventory(inventory_id)

    async def delete_inventory(self, inventory_id: uuid.UUID) -> None:
        await self.get_inventory(inventory_id)
        await self.inventory_repo.delete(inventory_id)

    async def finalize_inventory(
        self,
        inventory_id: uuid.UUID,
        status_value: str = "baseline",
    ) -> CarbonInventory:
        """Mark inventory as baseline/current and freeze its totals."""
        if status_value not in {"baseline", "current"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="status must be 'baseline' or 'current'",
            )
        inv = await self.get_inventory(inventory_id)
        # 'archived' is a terminal state — refuse to silently resurrect an
        # archived inventory by re-finalising it. Callers must explicitly
        # PATCH it back to a non-archived status first.
        if inv.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot finalize an archived inventory",
            )
        # Capture project_id BEFORE update_fields() — that call runs
        # session.expire_all(), which expires every attribute on ``inv``;
        # reading inv.project_id afterwards would trigger a lazy DB reload
        # outside the async context (MissingGreenlet).
        project_id = inv.project_id
        totals = await self.compute_inventory_totals_fresh(inventory_id)
        await self.inventory_repo.update_fields(
            inventory_id,
            status=status_value,
            totals=totals,
        )
        # Structured audit log: carbon footprint freeze is a high-trust event
        # (changes downstream targets/met state and TCFD report inputs).
        logger.info(
            "carbon.inventory.finalized",
            extra={
                "project_id": str(project_id),
                "inventory_id": str(inventory_id),
                "status": status_value,
                "total_kg_co2e": str(totals.get("total", "0")),
                "embodied_a1a5_kg": str(totals.get("embodied_a1a5", "0")),
                "operational_kg": str(totals.get("operational", "0")),
            },
        )
        event_bus.publish_detached(
            "carbon.inventory.finalized",
            {
                "project_id": str(project_id),
                "inventory_id": str(inventory_id),
                "status": status_value,
                "totals": totals,
            },
            source_module="carbon",
        )
        return await self.get_inventory(inventory_id)

    async def compute_inventory_totals_fresh(
        self,
        inventory_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Recompute totals from current child rows. Pure-ish: reads DB only."""
        embodied = await self.embodied_repo.list_for_inventory(inventory_id)
        s1 = await self.scope1_repo.list_for_inventory(inventory_id)
        s2 = await self.scope2_repo.list_for_inventory(inventory_id)
        s3 = await self.scope3_repo.list_for_inventory(inventory_id)
        return compute_inventory_totals(inventory_id, embodied, s1, s2, s3)

    # ── Embodied entries ─────────────────────────────────────────────────
    async def create_embodied_entry(
        self,
        data: EmbodiedCarbonEntryCreate,
    ) -> EmbodiedCarbonEntry:
        entry = EmbodiedCarbonEntry(**data.model_dump(exclude={"metadata"}))
        entry.metadata_ = data.metadata
        # Validate the EN 15978 stage if present.
        if entry.stage:
            try:
                entry.stage = validate_en15978_stage(entry.stage)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
        # If carbon_kg is zero but quantity & factor are set, auto-fill.
        # ``factor_value_used`` is already normalised to the same unit as
        # ``quantity`` by the caller (or by assign_boq_position_carbon), so
        # we multiply directly rather than re-running the unit-conversion
        # machinery (which would mis-interpret m3×(kg/m3) as m3×(m3/…) if
        # both sides were naively set to entry.unit).
        if (entry.carbon_kg in (0, "0", Decimal("0"))) and entry.quantity and entry.factor_value_used:
            entry.carbon_kg = Decimal(str(entry.quantity)) * Decimal(str(entry.factor_value_used))
        return await self.embodied_repo.create(entry)

    async def list_embodied_entries(
        self,
        inventory_id: uuid.UUID,
        *,
        stage: str | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[EmbodiedCarbonEntry], int]:
        # Allowlist the stage filter — any value is parameterised so there
        # is no SQL injection, but accepting arbitrary garbage triggers a
        # needless full-table scan that always returns zero rows. Reject early.
        if stage is not None:
            try:
                stage = validate_en15978_stage(stage)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
        return await self.embodied_repo.list_for_inventory_paged(
            inventory_id,
            stage=stage,
            offset=offset,
            limit=limit,
        )

    async def get_embodied_entry(self, entry_id: uuid.UUID) -> EmbodiedCarbonEntry:
        entry = await self.embodied_repo.get_by_id(entry_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Embodied entry not found",
            )
        return entry

    async def update_embodied_entry(
        self,
        entry_id: uuid.UUID,
        data: EmbodiedCarbonEntryUpdate,
    ) -> EmbodiedCarbonEntry:
        await self.get_embodied_entry(entry_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.embodied_repo.update_fields(entry_id, **fields)
        return await self.get_embodied_entry(entry_id)

    async def delete_embodied_entry(self, entry_id: uuid.UUID) -> None:
        await self.get_embodied_entry(entry_id)
        await self.embodied_repo.delete(entry_id)

    async def bulk_create_embodied(
        self,
        inventory_id: uuid.UUID,
        entries: list[EmbodiedCarbonEntryCreate],
    ) -> int:
        """Bulk insert via session.add_all + single flush.

        Was: per-entry flush → 1 round-trip per row. Now: O(1) flushes for
        the whole batch. Stage codes are validated up-front so a single bad
        entry rejects the entire batch rather than half-committing.
        """
        models: list[EmbodiedCarbonEntry] = []
        for payload in entries:
            payload_dict = payload.model_dump()
            payload_dict["inventory_id"] = inventory_id
            raw_stage = payload_dict.get("stage") or "a1a3"
            try:
                payload_dict["stage"] = validate_en15978_stage(str(raw_stage))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            entry = EmbodiedCarbonEntry(
                **{k: v for k, v in payload_dict.items() if k != "metadata"},
            )
            entry.metadata_ = payload_dict.get("metadata", {})
            models.append(entry)
        if not models:
            return 0
        self.session.add_all(models)
        await self.session.flush()
        return len(models)

    # ── Scope 1 ──────────────────────────────────────────────────────────
    async def create_scope1(self, data: Scope1EntryCreate) -> Scope1Entry:
        payload = data.model_dump(exclude={"metadata"})
        if payload.get("total_co2e_kg") is None:
            payload["total_co2e_kg"] = compute_scope1_co2e(
                payload["litres_or_m3"],
                payload["fuel_type"],
                payload["emission_factor_kg_co2e_per_unit"],
            )
        entry = Scope1Entry(**payload)
        entry.metadata_ = data.metadata
        return await self.scope1_repo.create(entry)

    async def get_scope1(self, entry_id: uuid.UUID) -> Scope1Entry:
        entry = await self.scope1_repo.get_by_id(entry_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scope-1 entry not found",
            )
        return entry

    async def list_scope1(
        self,
        inventory_id: uuid.UUID,
    ) -> tuple[list[Scope1Entry], int]:
        rows = await self.scope1_repo.list_for_inventory(inventory_id)
        return rows, len(rows)

    async def update_scope1(
        self,
        entry_id: uuid.UUID,
        data: Scope1EntryUpdate,
    ) -> Scope1Entry:
        await self.get_scope1(entry_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.scope1_repo.update_fields(entry_id, **fields)
        return await self.get_scope1(entry_id)

    async def delete_scope1(self, entry_id: uuid.UUID) -> None:
        await self.get_scope1(entry_id)
        await self.scope1_repo.delete(entry_id)

    # ── Scope 2 ──────────────────────────────────────────────────────────
    async def create_scope2(self, data: Scope2EntryCreate) -> Scope2Entry:
        payload = data.model_dump(exclude={"metadata"})
        if payload.get("total_co2e_kg") is None:
            payload["total_co2e_kg"] = compute_scope2_co2e(
                payload["kwh"],
                payload["emission_factor_kg_co2e_per_kwh"],
            )
        entry = Scope2Entry(**payload)
        entry.metadata_ = data.metadata
        return await self.scope2_repo.create(entry)

    async def get_scope2(self, entry_id: uuid.UUID) -> Scope2Entry:
        entry = await self.scope2_repo.get_by_id(entry_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scope-2 entry not found",
            )
        return entry

    async def list_scope2(
        self,
        inventory_id: uuid.UUID,
    ) -> tuple[list[Scope2Entry], int]:
        rows = await self.scope2_repo.list_for_inventory(inventory_id)
        return rows, len(rows)

    async def update_scope2(
        self,
        entry_id: uuid.UUID,
        data: Scope2EntryUpdate,
    ) -> Scope2Entry:
        await self.get_scope2(entry_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.scope2_repo.update_fields(entry_id, **fields)
        return await self.get_scope2(entry_id)

    async def delete_scope2(self, entry_id: uuid.UUID) -> None:
        await self.get_scope2(entry_id)
        await self.scope2_repo.delete(entry_id)

    # ── Scope 3 ──────────────────────────────────────────────────────────
    async def create_scope3(self, data: Scope3EntryCreate) -> Scope3Entry:
        payload = data.model_dump(exclude={"metadata"})
        if payload.get("total_co2e_kg") is None:
            payload["total_co2e_kg"] = Decimal(str(payload["activity_data"])) * Decimal(str(payload["emission_factor"]))
        entry = Scope3Entry(**payload)
        entry.metadata_ = data.metadata
        return await self.scope3_repo.create(entry)

    async def get_scope3(self, entry_id: uuid.UUID) -> Scope3Entry:
        entry = await self.scope3_repo.get_by_id(entry_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scope-3 entry not found",
            )
        return entry

    async def list_scope3(
        self,
        inventory_id: uuid.UUID,
    ) -> tuple[list[Scope3Entry], int]:
        rows = await self.scope3_repo.list_for_inventory(inventory_id)
        return rows, len(rows)

    async def update_scope3(
        self,
        entry_id: uuid.UUID,
        data: Scope3EntryUpdate,
    ) -> Scope3Entry:
        await self.get_scope3(entry_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.scope3_repo.update_fields(entry_id, **fields)
        return await self.get_scope3(entry_id)

    async def delete_scope3(self, entry_id: uuid.UUID) -> None:
        await self.get_scope3(entry_id)
        await self.scope3_repo.delete(entry_id)

    # ── Targets ──────────────────────────────────────────────────────────
    async def create_target(
        self,
        data: CarbonTargetCreate,
        user_id: str | None = None,
    ) -> CarbonTarget:
        target = CarbonTarget(**data.model_dump(exclude={"metadata"}))
        target.metadata_ = data.metadata
        target.created_by = user_id
        return await self.target_repo.create(target)

    async def get_target(self, target_id: uuid.UUID) -> CarbonTarget:
        target = await self.target_repo.get_by_id(target_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target not found",
            )
        return target

    async def list_targets(
        self,
        project_id: uuid.UUID,
    ) -> tuple[list[CarbonTarget], int]:
        rows = await self.target_repo.targets_for_project(project_id)
        return rows, len(rows)

    async def update_target(
        self,
        target_id: uuid.UUID,
        data: CarbonTargetUpdate,
    ) -> CarbonTarget:
        target = await self.get_target(target_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.target_repo.update_fields(target_id, **fields)
        refreshed = await self.get_target(target_id)

        # Emit met/missed event when status transitions.
        old_status = target.status
        new_status = refreshed.status
        if new_status != old_status and new_status in {"met", "missed"}:
            event_bus.publish_detached(
                f"carbon.target.{new_status}",
                {
                    "project_id": str(refreshed.project_id),
                    "target_id": str(target_id),
                    "name": refreshed.name,
                },
                source_module="carbon",
            )
        return refreshed

    async def delete_target(self, target_id: uuid.UUID) -> None:
        await self.get_target(target_id)
        await self.target_repo.delete(target_id)

    async def target_progress(
        self,
        target_id: uuid.UUID,
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        """Compute progress of a target vs current inventory totals."""
        target = await self.get_target(target_id)
        # Sum all current/baseline inventories for the project.
        inventories, _ = await self.inventory_repo.list_for_project(target.project_id)
        latest = None
        for inv in inventories:
            if inv.status in {"baseline", "current"}:
                if latest is None or inv.updated_at > latest.updated_at:
                    latest = inv
        current_value = Decimal("0")
        if latest is not None:
            totals = latest.totals or {}
            current_value = Decimal(str(totals.get("total", 0) or 0))
        met = is_target_met(target, current_value)

        baseline = Decimal(str(target.baseline_value or 0))
        target_val = Decimal(str(target.target_value or 0))
        if baseline > target_val and baseline != 0:
            progress_pct = float(
                (baseline - current_value) / (baseline - target_val) * 100,
            )
        else:
            progress_pct = 0.0
        return {
            "target_id": target_id,
            "current_value": current_value,
            "baseline_value": baseline,
            "target_value": target_val,
            "progress_pct": progress_pct,
            "met": met,
            "as_of_date": as_of_date,
        }

    # ── Alternatives ────────────────────────────────────────────────────
    async def alternatives_for_entry(
        self,
        entry_id: uuid.UUID,
    ) -> dict[str, Any]:
        entry = await self.get_embodied_entry(entry_id)
        # Pull EPDs with the same material_class (via entry.factor_id → epd_id → class)
        candidate_factors: list[MaterialCarbonFactor] = []
        if entry.factor_id is not None:
            current_factor = await self.factor_repo.get_by_id(entry.factor_id)
            if current_factor is not None and current_factor.epd_id is not None:
                current_epd = await self.epd_repo.get_by_id(current_factor.epd_id)
                if current_epd is not None:
                    same_class, _ = await self.epd_repo.list_filtered(
                        material_class=current_epd.material_class,
                    )
                    for sibling in same_class:
                        if sibling.id == current_epd.id:
                            continue
                        # Wrap EPD into a "factor-shaped" object with id + factor_value.
                        candidate_factors.append(
                            type(
                                "EpdFactor",
                                (),
                                {
                                    "id": sibling.id,
                                    "factor_value": sibling.gwp_a1a3,
                                    "manual_override_factor": None,
                                    "confidence": "medium",
                                },
                            )(),
                        )
        options = compare_alternatives(entry, candidate_factors)
        return {
            "entry_id": entry.id,
            "current_factor_value": Decimal(str(entry.factor_value_used or 0)),
            "current_carbon_kg": Decimal(str(entry.carbon_kg or 0)),
            "options": options,
        }

    # ── Reports ─────────────────────────────────────────────────────────
    async def create_report_record(
        self,
        data: SustainabilityReportCreate,
        user_id: str | None = None,
    ) -> SustainabilityReport:
        report = SustainabilityReport(**data.model_dump(exclude={"metadata"}))
        report.metadata_ = data.metadata
        if user_id:
            try:
                report.generated_by = uuid.UUID(user_id)
            except (ValueError, TypeError):
                report.generated_by = None
        report.generated_at = datetime.now(UTC).date()
        return await self.report_repo.create(report)

    async def get_report(self, report_id: uuid.UUID) -> SustainabilityReport:
        report = await self.report_repo.get_by_id(report_id)
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found",
            )
        return report

    async def list_reports(
        self,
        project_id: uuid.UUID,
    ) -> tuple[list[SustainabilityReport], int]:
        rows = await self.report_repo.reports_for_project(project_id)
        return rows, len(rows)

    async def update_report(
        self,
        report_id: uuid.UUID,
        data: SustainabilityReportUpdate,
    ) -> SustainabilityReport:
        await self.get_report(report_id)
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if fields:
            await self.report_repo.update_fields(report_id, **fields)
        return await self.get_report(report_id)

    async def delete_report(self, report_id: uuid.UUID) -> None:
        await self.get_report(report_id)
        await self.report_repo.delete(report_id)

    async def generate_report(
        self,
        payload: SustainabilityReportPayload,
        user_id: str | None = None,
    ) -> SustainabilityReport:
        """Compose a SustainabilityReport with totals computed from inventory."""
        totals: dict[str, Any] = {}
        if payload.inventory_id is not None:
            totals = await self.compute_inventory_totals_fresh(payload.inventory_id)
        if payload.project_area_m2 and totals.get("total"):
            totals["intensity_per_m2"] = str(
                compute_carbon_intensity(
                    totals["total"],
                    payload.project_area_m2,
                )
            )
        report = SustainabilityReport(
            project_id=payload.project_id,
            inventory_id=payload.inventory_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            framework=payload.framework,
            totals=totals,
            narrative=payload.narrative,
            generated_at=datetime.now(UTC).date(),
        )
        if user_id:
            try:
                report.generated_by = uuid.UUID(user_id)
            except (ValueError, TypeError):
                report.generated_by = None
        report.metadata_ = {}
        report = await self.report_repo.create(report)
        event_bus.publish_detached(
            "carbon.report.generated",
            {
                "project_id": str(payload.project_id),
                "report_id": str(report.id),
                "framework": payload.framework,
                "totals": totals,
            },
            source_module="carbon",
        )
        return report

    # ── EPD ingestion by identifier ─────────────────────────────────────

    async def ingest_epd_by_identifier(
        self,
        identifier: str,
        *,
        gwp_a1a3: Decimal | float | int | str,
        product_name: str,
        material_class: str,
        manufacturer: str | None = None,
        region: str = "",
        declared_unit: str = "kg",
        validity_until: str | None = None,
        document_url: str | None = None,
    ) -> EPDRecord:
        """Ingest an EPD record from a public-database identifier.

        Parses the identifier (e.g. ``"oekobaudat:1.4.01.04"`` or a URL),
        derives ``source`` + canonical ID, and creates the EPDRecord
        atomically. The caller supplies the GWP because remote fetching is
        deliberately not done synchronously inside the request — the
        identifier is enough to dedupe and link to the public source.

        Conflict policy: duplicate (source, epd_id) is treated as an
        update, not an error — keeps subsequent imports idempotent.
        """
        parsed = parse_epd_identifier(identifier)
        # Compose a canonical epd_id by combining source + remote id, so it
        # de-dupes across re-imports and preserves the original raw URL.
        canonical_id = f"{parsed['source']}:{parsed['id']}"
        # Indexed lookup by canonical id (was: list-then-iterate, O(N) per call
        # and unbounded — could scan thousands of EPDs on every ingest).
        existing_match = await self.epd_repo.get_by_epd_id(canonical_id)
        gwp = Decimal(str(gwp_a1a3))
        if existing_match is not None:
            # Capture PK BEFORE update_fields() — that call runs
            # session.expire_all(), which expires every attribute on
            # ``existing_match``; reading ``.id`` afterwards would trigger a
            # lazy DB reload outside the async context (MissingGreenlet).
            existing_id = existing_match.id
            await self.epd_repo.update_fields(
                existing_id,
                gwp_a1a3=gwp,
                product_name=product_name,
                material_class=material_class,
                manufacturer=manufacturer,
                region=region,
                declared_unit=declared_unit,
                validity_until=validity_until,
                document_url=document_url,
            )
            refreshed = await self.epd_repo.get_by_id(existing_id)
            if refreshed is None:
                # Row deleted between update and re-fetch (extremely unlikely;
                # treat the same as a concurrent hard-delete).
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="EPD record removed concurrently during ingest",
                )
            return refreshed
        record = EPDRecord(
            epd_id=canonical_id,
            source=parsed["source"],
            material_class=material_class,
            product_name=product_name,
            manufacturer=manufacturer,
            region=region,
            declared_unit=declared_unit,
            gwp_a1a3=gwp,
            validity_until=validity_until,
            document_url=document_url,
        )
        record.metadata_ = {"raw_identifier": parsed["raw_identifier"]}
        created = await self.epd_repo.create(record)
        event_bus.publish_detached(
            "carbon.epd.ingested",
            {
                "epd_record_id": str(created.id),
                "source": parsed["source"],
                "canonical_id": canonical_id,
                "material_class": material_class,
                "gwp_a1a3": str(gwp),
            },
            source_module="carbon",
        )
        return created

    # ── BOQ-position → embodied carbon assignment ───────────────────────

    async def assign_boq_position_carbon(
        self,
        *,
        inventory_id: uuid.UUID,
        boq_position_id: uuid.UUID,
        material_factor_id: uuid.UUID,
        quantity: Decimal | float | int | str,
        quantity_unit: str,
        stage: str = "a1a3",
        density_kg_per_m3: Decimal | float | int | None = None,
    ) -> EmbodiedCarbonEntry:
        """Create an EmbodiedCarbonEntry tied to a BOQ position using a material factor.

        Computes kgCO2e = normalise(qty, unit, factor_unit, density) ×
        factor_value. Writes back to the inventory and emits
        ``carbon.boq_position.assigned``.
        """
        await self.get_inventory(inventory_id)
        factor = await self.get_factor(material_factor_id)

        # Get factor value: manual_override beats epd-derived
        factor_value: Decimal
        if factor.manual_override_factor is not None:
            factor_value = Decimal(str(factor.manual_override_factor))
        elif factor.epd_id is not None:
            epd = await self.epd_repo.get_by_id(factor.epd_id)
            if epd is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Material factor references missing EPD record",
                )
            factor_value = Decimal(str(epd.gwp_a1a3 or 0))
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Material factor has neither manual_override nor linked EPD",
            )

        try:
            stage_norm = validate_en15978_stage(stage)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        try:
            carbon_kg = compute_embodied_entry_carbon(
                quantity,
                quantity_unit,
                factor_value,
                factor.unit_for_factor,
                density_kg_per_m3,
            )
        except UnitMismatchError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unit_mismatch: {exc}",
            ) from exc

        entry = EmbodiedCarbonEntry(
            inventory_id=inventory_id,
            element_ref=f"boq:{boq_position_id}",
            description=f"BOQ position {boq_position_id}",
            quantity=Decimal(str(quantity)),
            unit=quantity_unit,
            factor_id=material_factor_id,
            factor_value_used=factor_value,
            carbon_kg=carbon_kg,
            stage=stage_norm,
        )
        entry.metadata_ = {
            "boq_position_id": str(boq_position_id),
            "density_kg_per_m3": (str(density_kg_per_m3) if density_kg_per_m3 is not None else None),
        }
        created = await self.embodied_repo.create(entry)
        event_bus.publish_detached(
            "carbon.boq_position.assigned",
            {
                "inventory_id": str(inventory_id),
                "boq_position_id": str(boq_position_id),
                "embodied_entry_id": str(created.id),
                "stage": stage_norm,
                "carbon_kg": str(carbon_kg),
            },
            source_module="carbon",
        )
        return created

    # ── Grid factor lookup ──────────────────────────────────────────────

    def lookup_grid_factor(
        self,
        country_code: str,
        year: int,
    ) -> dict[str, Any]:
        """Return the static grid emission factor for (country, year).

        Always returns a dict; raises HTTP 404 only when the country is
        not in the catalogue at all.
        """
        hit = lookup_grid_factor_default(country_code, year)
        if hit is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No grid factor found for country {country_code!r}",
            )
        return {
            "country_code": hit["country_code"],
            "year": hit["year"],
            "requested_year": hit.get("requested_year", year),
            "factor_kg_co2e_per_kwh": str(hit["factor_kg_co2e_per_kwh"]),
            "method": hit["method"],
            "source": hit["source"],
            "fallback": hit.get("fallback", False),
        }

    # ── TCFD / ISSB structured report ───────────────────────────────────

    async def generate_tcfd_report(
        self,
        project_id: uuid.UUID,
        *,
        inventory_id: uuid.UUID | None = None,
        period_start: str = "",
        period_end: str = "",
        gross_floor_area_m2: Decimal | float | int | None = None,
        net_internal_area_m2: Decimal | float | int | None = None,
        revenue_million: Decimal | float | int | None = None,
        narrative: dict[str, str] | None = None,
        project_name: str = "",
        user_id: str | None = None,
    ) -> SustainabilityReport:
        """Build and persist a TCFD-shaped sustainability report."""
        totals: dict[str, Any]
        if inventory_id is not None:
            totals = await self.compute_inventory_totals_fresh(inventory_id)
        else:
            inventories, _ = await self.inventory_repo.list_for_project(project_id)
            totals = {
                "scope1": "0",
                "scope2": "0",
                "scope3": "0",
                "embodied_a1a5": "0",
                "total": "0",
            }
            for inv in inventories:
                if inv.status in {"baseline", "current"}:
                    totals = inv.totals or totals
                    break
        targets, _ = await self.list_targets(project_id)
        intensity = compute_intensity_metrics(
            totals.get("total", 0),
            gross_floor_area_m2=gross_floor_area_m2,
            net_internal_area_m2=net_internal_area_m2,
            revenue_million=revenue_million,
        )
        body = build_tcfd_report_body(
            totals,
            project_name=project_name,
            period_start=period_start,
            period_end=period_end,
            targets=targets,
            intensity_metrics=intensity,
            narrative=narrative,
        )
        report = SustainabilityReport(
            project_id=project_id,
            inventory_id=inventory_id,
            period_start=period_start or datetime.now(UTC).date().isoformat(),
            period_end=period_end or datetime.now(UTC).date().isoformat(),
            framework="tcfd",
            totals={**totals, "intensity": intensity, "tcfd_body": body},
            narrative=(narrative or {}).get("metrics_and_targets", ""),
            generated_at=datetime.now(UTC).date(),
        )
        if user_id:
            try:
                report.generated_by = uuid.UUID(user_id)
            except (ValueError, TypeError):
                report.generated_by = None
        report.metadata_ = {"intensity": intensity}
        created = await self.report_repo.create(report)
        event_bus.publish_detached(
            "carbon.report.generated",
            {
                "project_id": str(project_id),
                "report_id": str(created.id),
                "framework": "tcfd",
                "totals": totals,
            },
            source_module="carbon",
        )
        return created

    # ── Dashboard ───────────────────────────────────────────────────────
    async def project_dashboard(
        self,
        project_id: uuid.UUID,
    ) -> dict[str, Any]:
        inventories, _ = await self.inventory_repo.list_for_project(project_id)
        targets, _ = await self.list_targets(project_id)
        reports, _ = await self.list_reports(project_id)

        embodied = Decimal("0")
        operational = Decimal("0")
        for inv in inventories:
            t = inv.totals or {}
            embodied += Decimal(str(t.get("embodied_a1a5", 0) or 0))
            operational += Decimal(str(t.get("operational", 0) or 0))

        targets_met = sum(1 for t in targets if t.status == "met")
        targets_missed = sum(1 for t in targets if t.status == "missed")
        latest_report_id = reports[0].id if reports else None
        return {
            "project_id": project_id,
            "total_embodied_kg": embodied,
            "total_operational_kg": operational,
            "total_kg": embodied + operational,
            "inventory_count": len(inventories),
            "target_count": len(targets),
            "targets_met": targets_met,
            "targets_missed": targets_missed,
            "intensity_per_m2": None,
            "latest_report_id": latest_report_id,
        }
