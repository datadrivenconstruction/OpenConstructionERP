# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Source extractors for the AI Estimate Builder (stage-1 normalisation).

These turn a *reference to an artifact already in the system* (a BIM model,
takeoff measurements, existing BOQ positions, site photos) into the
source-agnostic serialised-``ElementEnvelope`` dicts the rest of the pipeline
consumes. They reuse the verified element-to-envelope code path rather than
reinventing it:

* BIM / CAD  -> ``app.core.match_service.extractors.bim.extract`` over the raw
  canonical block assembled from each ``BIMElement`` (the exact path
  ``/match-elements`` uses), so the v3 hard filters (``ifc_class``,
  ``material_class``, Pset booleans) survive into the matcher.
* Takeoff    -> measured items from ``oe_takeoff_measurement`` (PDF takeoff) and
  ``oe_dwg_takeoff_annotation`` (DWG takeoff); each measured item carries a
  description, a real measured quantity and a unit.
* BOQ-import -> existing ``oe_boq_position`` rows (the re-estimate flow); the
  description / unit / quantity / classification become the envelope.
* Photo      -> ``oe_documents_photo`` run through the ai module's
  ``heuristic_photo_suggestion`` (filename + caption + tags); a photo that
  yields nothing is reported honestly, never a silent empty.

Every extractor returns an :class:`ExtractionResult` so ``analyze`` can fail
the run with a clear ``failure_reason`` when a referenced artifact does not
exist or yields zero estimable elements - never a silent empty success.

The matcher never invents a measured quantity. Photo suggestions carry a
``count`` of 1 each (a presence signal the human confirms / edits) and are
explicitly flagged low-confidence; they never claim a measured dimension.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Hard cap so a pathological 100k-element model or photo gallery cannot
# materialise the whole table into one analyze pass. Mirrors the
# match-elements BIM adapter cap; the grouping pass collapses duplicates.
_MAX_ELEMENTS = 250_000

# Canonical quantity keys we keep on a serialised envelope. Mirrors the
# match_service envelope contract so the grouping / matching path is identical
# whatever the source.
_QUANTITY_KEYS = ("length_m", "area_m2", "volume_m3", "mass_kg", "count")


@dataclass
class ExtractionResult:
    """Outcome of one source extractor.

    Attributes:
        envelopes: Serialised ``ElementEnvelope`` dicts (the universal element).
        requested: How many artifacts the caller referenced (0 = "use all in
            project"). Lets ``analyze`` tell "you asked for a model that does
            not exist" apart from "the model is empty".
        found: How many referenced artifacts actually resolved.
        scanned: How many raw rows/items were inspected (for honest step logs).
        notes: Per-artifact honest notes (e.g. a photo that yielded nothing).
    """

    envelopes: list[dict[str, Any]] = field(default_factory=list)
    requested: int = 0
    found: int = 0
    scanned: int = 0
    notes: list[str] = field(default_factory=list)


def _coerce_uuids(values: list[str] | None) -> list[uuid.UUID]:
    """Best-effort parse a list of string ids to UUIDs, dropping junk."""
    out: list[uuid.UUID] = []
    for v in values or []:
        try:
            out.append(uuid.UUID(str(v)))
        except (ValueError, TypeError):
            continue
    return out


def _clean_quantities(raw: dict[str, Any]) -> dict[str, float]:
    """Keep only the canonical, finite, non-zero quantity keys."""
    out: dict[str, float] = {}
    for key in _QUANTITY_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        if f and f == f and f not in (float("inf"), float("-inf")):
            out[key] = f
    return out


# ── BIM / CAD source ─────────────────────────────────────────────────────────


async def extract_bim(
    session: AsyncSession,
    project_id: uuid.UUID,
    model_ids: list[str] | None,
) -> ExtractionResult:
    """Build envelopes from a project's converted BIM/CAD model(s).

    Reuses the verified ``bim.extract`` envelope builder over each element's
    canonical block (category + name + properties + quantities), so the same
    description synthesis and v3 hard filters the ``/match-elements`` BIM path
    relies on apply here unchanged.
    """
    from app.core.match_service.extractors import bim as bim_extractor
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.match_elements.revit_ifc_map import normalize_to_ifc_class

    wanted = _coerce_uuids(model_ids)
    result = ExtractionResult(requested=len(wanted))

    # Resolve which models in this project we are reading (scoped by project
    # so an id from another tenant resolves to nothing -> honest failure).
    model_stmt = select(BIMModel.id).where(BIMModel.project_id == project_id)
    if wanted:
        model_stmt = model_stmt.where(BIMModel.id.in_(wanted))
    found_models = [row[0] for row in (await session.execute(model_stmt)).all()]
    result.found = len(found_models)
    if not found_models:
        return result

    stmt = select(BIMElement).where(BIMElement.model_id.in_(found_models)).limit(_MAX_ELEMENTS)
    rows = (await session.execute(stmt)).scalars().all()

    for elem in rows:
        result.scanned += 1
        props = dict(elem.properties or {})
        category = elem.element_type or ""
        # Crosswalk a raw Revit OST category ("Walls") to its canonical IFC
        # class so the hard filter fires; genuine IFC inputs pass through.
        ifc_class = normalize_to_ifc_class(category) if category else None
        raw: dict[str, Any] = {
            "id": str(elem.id),
            "category": ifc_class or category,
            "name": elem.name or "",
            "properties": props,
            "quantities": dict(elem.quantities or {}),
            "language": props.get("language") or "",
        }
        if ifc_class:
            raw["ifc_class"] = ifc_class
        try:
            envelope = bim_extractor.extract(raw)
        except Exception as exc:  # noqa: BLE001 - skip a malformed element, never crash
            logger.debug("ai_estimator bim extract skipped element %s: %s", elem.id, exc)
            continue
        quantities = _clean_quantities(dict(envelope.quantities or {}))
        # An element with no description and no measurable quantity carries no
        # signal - skip it rather than emit a noise envelope.
        if not (envelope.description or "").strip() and not quantities:
            continue
        env_dict: dict[str, Any] = {
            "id": str(elem.id),
            "source": "bim",
            "description": (envelope.description or category or "BIM element")[:2000],
            "category": category,
            "unit_hint": envelope.unit_hint,
            "quantities": quantities,
            "exact_code": None,
            "properties": dict(envelope.properties or {}),
        }
        if envelope.ifc_class:
            env_dict["ifc_class"] = envelope.ifc_class
        if envelope.material_class:
            env_dict["material_class"] = envelope.material_class
        if envelope.classifier_hint:
            env_dict["classifier_hint"] = dict(envelope.classifier_hint)
        if elem.storey:
            env_dict["level"] = str(elem.storey)
        if elem.discipline:
            env_dict["discipline"] = str(elem.discipline)
        result.envelopes.append(env_dict)

    return result


# ── Takeoff source (PDF takeoff + DWG takeoff measured items) ──────────────────


# Canonical quantity key -> the catalogue unit hint it implies.
_QKEY_TO_UNIT = {
    "volume_m3": "m3",
    "area_m2": "m2",
    "length_m": "m",
    "mass_kg": "kg",
    "count": "pcs",
}


def _takeoff_quantities(unit: str, value: float) -> dict[str, float]:
    """Map a measured (unit, value) onto the canonical quantity dict."""
    if value <= 0:
        return {}
    u = (unit or "").strip().lower()
    key = {
        "m3": "volume_m3",
        "m³": "volume_m3",
        "m2": "area_m2",
        "m²": "area_m2",
        "sqm": "area_m2",
        "m": "length_m",
        "lm": "length_m",
        "mm": "length_m",
        "kg": "mass_kg",
    }.get(u, "count")
    return {key: value}


def _unit_hint_for(quantities: dict[str, float]) -> str:
    """The catalogue unit hint implied by a single-dimension quantity dict."""
    for qkey in quantities:
        hint = _QKEY_TO_UNIT.get(qkey)
        if hint:
            return hint
    return "pcs"


async def extract_takeoff(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> ExtractionResult:
    """Build envelopes from measured takeoff items (PDF + DWG takeoff).

    Each measurement is its own estimable element: the annotation text (or the
    group / type label) becomes the description, the measured value + unit the
    quantity. Measurements with no positive value carry no quantity and are
    skipped (we never fabricate a measurement).
    """
    from app.modules.dwg_takeoff.models import DwgAnnotation
    from app.modules.takeoff.models import TakeoffMeasurement

    result = ExtractionResult()

    # PDF takeoff measurements.
    pdf_rows = (
        (
            await session.execute(
                select(TakeoffMeasurement).where(TakeoffMeasurement.project_id == project_id).limit(_MAX_ELEMENTS)
            )
        )
        .scalars()
        .all()
    )
    for m in pdf_rows:
        result.scanned += 1
        value = float(m.volume if m.volume is not None else (m.measurement_value or 0) or 0)
        unit = "m3" if m.volume is not None else (m.measurement_unit or "")
        if m.count_value is not None and not value:
            value, unit = float(m.count_value), "pcs"
        quantities = _takeoff_quantities(unit, value)
        if not quantities:
            continue
        desc = (m.annotation or m.group_name or m.type or "Takeoff measurement").strip()
        result.envelopes.append(
            {
                "id": f"takeoff_pdf_{m.id}",
                "source": "pdf",
                "description": desc[:2000],
                "category": m.type or "",
                "unit_hint": _unit_hint_for(quantities),
                "quantities": quantities,
                "exact_code": None,
            }
        )

    # DWG takeoff annotations that carry a measured value.
    dwg_rows = (
        (
            await session.execute(
                select(DwgAnnotation)
                .where(DwgAnnotation.project_id == project_id)
                .where(DwgAnnotation.measurement_value.isnot(None))
                .limit(_MAX_ELEMENTS)
            )
        )
        .scalars()
        .all()
    )
    for a in dwg_rows:
        result.scanned += 1
        value = float(a.measurement_value or 0)
        unit = a.measurement_unit or ""
        quantities = _takeoff_quantities(unit, value)
        if not quantities:
            continue
        desc = (a.text or a.layer_name or a.annotation_type or "DWG takeoff").strip()
        result.envelopes.append(
            {
                "id": f"takeoff_dwg_{a.id}",
                "source": "dwg",
                "description": desc[:2000],
                "category": a.annotation_type or "",
                "unit_hint": _unit_hint_for(quantities),
                "quantities": quantities,
                "exact_code": None,
            }
        )

    result.found = len(pdf_rows) + len(dwg_rows)
    return result


# ── BOQ-import source (re-estimate existing positions) ─────────────────────────


async def extract_boq(
    session: AsyncSession,
    project_id: uuid.UUID,
    boq_ids: list[str] | None,
) -> ExtractionResult:
    """Build envelopes from existing BOQ positions (the re-estimate flow).

    Each position's description / unit / quantity / classification becomes an
    envelope. The classification block is carried through as a classifier hint
    and a populated code is promoted to ``exact_code`` so a re-estimate of a
    coded position can short-circuit to the same catalogue row.
    """
    from app.modules.boq.models import BOQ, Position

    wanted_boqs = _coerce_uuids(boq_ids)
    result = ExtractionResult(requested=len(wanted_boqs))

    boq_stmt = select(BOQ.id).where(BOQ.project_id == project_id)
    if wanted_boqs:
        boq_stmt = boq_stmt.where(BOQ.id.in_(wanted_boqs))
    found_boqs = [row[0] for row in (await session.execute(boq_stmt)).all()]
    result.found = len(found_boqs)
    if not found_boqs:
        return result

    rows = (
        (
            await session.execute(
                select(Position)
                .where(Position.boq_id.in_(found_boqs))
                .order_by(Position.sort_order)
                .limit(_MAX_ELEMENTS)
            )
        )
        .scalars()
        .all()
    )

    for pos in rows:
        result.scanned += 1
        desc = (pos.description or "").strip()
        if not desc:
            continue
        unit = (pos.unit or "").strip()
        try:
            qty = float(pos.quantity)
        except (TypeError, ValueError):
            qty = 0.0
        quantities: dict[str, float] = {}
        if qty > 0:
            u = unit.lower()
            key = {"m3": "volume_m3", "m2": "area_m2", "m": "length_m", "kg": "mass_kg"}.get(u, "count")
            quantities[key] = qty
        env: dict[str, Any] = {
            "id": f"boq_{pos.id}",
            "source": "boq",
            "description": desc[:2000],
            "category": "",
            "unit_hint": unit or None,
            "quantities": quantities,
            "exact_code": None,
        }
        classification = pos.classification if isinstance(pos.classification, dict) else {}
        hint = {k: str(v) for k, v in classification.items() if v and k in ("din276", "nrm", "masterformat")}
        if hint:
            env["classifier_hint"] = hint
        # A position's reference_code is a user-facing reuse code, NOT a
        # catalogue rate code, so it is never promoted to exact_code here.
        result.envelopes.append(env)

    return result


# ── Photo source (heuristic photo intelligence) ────────────────────────────────


async def extract_photos(
    session: AsyncSession,
    project_id: uuid.UUID,
    photo_ids: list[str] | None,
) -> ExtractionResult:
    """Build presence-signal envelopes from project photos.

    Runs each photo's filename + caption + tags through the ai module's
    ``heuristic_photo_suggestion``. A photo that produces a suggestion becomes
    a single ``count=1`` envelope (a presence the human confirms / quantifies),
    explicitly low-confidence - a photo never claims a measured dimension. A
    photo that yields nothing is recorded in ``notes`` so the run reports it
    honestly rather than silently dropping it.
    """
    from app.modules.ai.service import heuristic_photo_suggestion
    from app.modules.documents.models import ProjectPhoto

    # ``photo_ids`` may be ProjectPhoto ids; non-uuid refs (raw filenames the
    # wizard passed) are matched by filename instead so the user is not forced
    # to look up an internal id.
    wanted_uuids = _coerce_uuids(photo_ids)
    raw_refs = [str(r) for r in (photo_ids or [])]
    result = ExtractionResult(requested=len(raw_refs))

    stmt = select(ProjectPhoto).where(ProjectPhoto.project_id == project_id)
    if wanted_uuids:
        stmt = stmt.where(ProjectPhoto.id.in_(wanted_uuids))
    elif raw_refs:
        stmt = stmt.where(ProjectPhoto.filename.in_(raw_refs))
    photos = (await session.execute(stmt.limit(_MAX_ELEMENTS))).scalars().all()
    result.found = len(photos)

    for photo in photos:
        result.scanned += 1
        suggestion = heuristic_photo_suggestion(
            filename=photo.filename or "",
            caption=photo.caption or "",
            tags=[str(t) for t in (photo.tags or [])],
        )
        if not suggestion:
            result.notes.append(f"photo '{photo.filename}' yielded no element suggestion")
            continue
        category = str(suggestion.get("suggested_category") or "").strip()
        tags = [str(t) for t in (suggestion.get("suggested_tags") or [])]
        # Build the description from the strongest signal available.
        desc_parts = [category] if category else []
        if photo.caption:
            desc_parts.append(photo.caption.strip())
        desc_parts.extend(t for t in tags if t not in desc_parts)
        description = ", ".join(p for p in desc_parts if p) or (photo.filename or "Site photo")
        result.envelopes.append(
            {
                "id": f"photo_{photo.id}",
                "source": "photo",
                "description": description[:2000],
                "category": category,
                "unit_hint": "pcs",
                # Presence only: a count of 1 the human confirms / edits.
                # Photos never carry a measured dimension.
                "quantities": {"count": 1.0},
                "exact_code": None,
                "properties": {"photo_confidence": "low", "from_photo": True},
            }
        )
    return result


# ── Free-text scope source (deterministic line-item parser) ────────────────────

# The unit tokens we recognise at the head of a scope clause, mapped to the
# canonical quantity key + the catalogue unit hint. We reuse the matcher's
# canonical short codes (m / m2 / m3 / kg / pcs) and the common spoken
# spellings so "120 m2", "30 cubic metres" and "2 no." all resolve. Only
# numbers the user actually wrote are read - nothing is invented.
_TEXT_UNIT_MAP: dict[str, tuple[str, str]] = {
    # volume
    "m3": ("volume_m3", "m3"),
    "m³": ("volume_m3", "m3"),
    "cum": ("volume_m3", "m3"),
    "cbm": ("volume_m3", "m3"),
    "cubicmetre": ("volume_m3", "m3"),
    "cubicmeter": ("volume_m3", "m3"),
    "cubicmetres": ("volume_m3", "m3"),
    "cubicmeters": ("volume_m3", "m3"),
    # area
    "m2": ("area_m2", "m2"),
    "m²": ("area_m2", "m2"),
    "sqm": ("area_m2", "m2"),
    "sm": ("area_m2", "m2"),
    "squaremetre": ("area_m2", "m2"),
    "squaremeter": ("area_m2", "m2"),
    "squaremetres": ("area_m2", "m2"),
    "squaremeters": ("area_m2", "m2"),
    # length
    "m": ("length_m", "m"),
    "lm": ("length_m", "m"),
    "rm": ("length_m", "m"),
    "metre": ("length_m", "m"),
    "meter": ("length_m", "m"),
    "metres": ("length_m", "m"),
    "meters": ("length_m", "m"),
    "lfm": ("length_m", "m"),
    # mass
    "kg": ("mass_kg", "kg"),
    "kgs": ("mass_kg", "kg"),
    "t": ("mass_kg", "kg"),  # tonne folded into mass; magnitude preserved below
    # count
    "pcs": ("count", "pcs"),
    "pc": ("count", "pcs"),
    "no": ("count", "pcs"),
    "nr": ("count", "pcs"),
    "ea": ("count", "pcs"),
    "unit": ("count", "pcs"),
    "units": ("count", "pcs"),
    "off": ("count", "pcs"),
}

# Spoken multi-word unit spellings ("cubic metre", "square meters"). Folded to
# a single canonical key BEFORE building the alternation, and matched with a
# tolerant inner-space pattern so "30 cubic metres of concrete" resolves.
_SPACED_UNIT_PATTERNS: list[tuple[str, str]] = [
    (r"cubic\s*met(?:re|er)s?", "m3"),
    (r"square\s*met(?:re|er)s?", "m2"),
    (r"linear\s*met(?:re|er)s?", "m"),
    (r"running\s*met(?:re|er)s?", "m"),
]

# A leading "<number> <unit>" at the head of a clause. The single-token unit
# alternatives are sorted longest-first so "m2" wins over "m"; the multi-word
# spoken spellings come first so "cubic metre" is not eaten by "m". Allows an
# optional "x"/"of" filler ("2 x steel doors", "30 m3 of concrete").
_UNIT_ALTERNATION = "|".join(
    [pat for pat, _ in _SPACED_UNIT_PATTERNS] + [re.escape(u) for u in sorted(_TEXT_UNIT_MAP, key=len, reverse=True)]
)
_LEAD_QTY_RE = re.compile(
    r"^\s*(?P<qty>\d[\d.,]*\d|\d)\s*"
    r"(?P<unit>" + _UNIT_ALTERNATION + r")\b\.?\s*(?:x|of\b)?\s*",
    re.IGNORECASE,
)

# Fallback: a bare leading integer followed by a word that is not itself a
# unit and not a dimension (no trailing unit) is an explicit count the user
# wrote - "2 steel doors", "3 fire dampers". The number must be a small whole
# count (<= 9999) immediately followed by a letter-led word, so we never
# misread a dimension string ("11.5cm") or a measurement ("120 m2", already
# consumed by the unit regex above). The optional "x"/"no"/"nr"/"pcs" filler
# is tolerated.
_LEAD_COUNT_RE = re.compile(
    r"^\s*(?P<qty>\d{1,4})\s*(?:x|no\.?|nr\.?|pcs\.?|pieces?|units?\s+of)?\s+(?P<word>[A-Za-zÀ-ÿ])",
    re.IGNORECASE,
)

# Clause separators. We split on newlines, semicolons, bullets, the conjunction
# " and ", and commas - EXCEPT a comma sitting BETWEEN two digits with no space
# ("1,200") which is a thousands / decimal separator inside one number, not a
# clause break. "...2100, 45" still splits because the space after the comma
# means it is a real list separator, not part of a number.
_CLAUSE_SPLIT_RE = re.compile(
    r"[\n;]+|(?<![\d]),|,(?![\d])|(?:•)|(?:\s+\band\b\s+)",
    re.IGNORECASE,
)

# A spec-continuation comma is NOT a list separator: it joins a descriptive head
# to a trailing pure-dimension spec, e.g. "Brick wall, 24cm" (one line item, the
# 24cm is the wall thickness). The trailing token must be a bare dimension -
# a number followed by a length/thickness unit (cm / mm / m), optionally chained
# with "x" ("Slab, 200 x 50 mm") - and must NOT be followed by a descriptive
# word, because a real list separator is "..., 30 m3 concrete foundation" where
# the dimension is a quantity introducing a new item. So the run of dimension
# tokens must end the clause (end-of-string, another separator, or another such
# comma-continuation). The unit alternation is anchored to short length units
# only: a volumetric / area / count quantity ("30 m3", "2 pcs") after a comma is
# treated as a new list item, never a spec continuation.
_DIM_LENGTH_UNIT = r"(?:cm|mm|m)"
# A dimension run: one or more numbers chained with "x"/"×" ("200 x 50 mm",
# "24cm"), where at least one number carries an explicit length/thickness unit
# (cm / mm / m). A leading unitless number is allowed only inside an x-chain
# ("200 x 50 mm"); a lone bare "24" never absorbs a comma. Built as:
#   <num>(unit)?  ( x <num>(unit)? )*   -- with a lookahead asserting the run
#   contains at least one unit so a unitless "200 x 50" is not a dimension run.
_DIM_NUM = r"\d[\d.,]*\s*" + _DIM_LENGTH_UNIT + r"?\b"
# The leading lookahead asserts the run carries at least one length unit; it
# scans only number-ish characters (digits, dot, comma, space, the x chain
# link) up to that unit, so a thousands comma ("1,200 mm") is allowed inside the
# run but the scan never crosses into descriptive text.
_DIM_CHAIN = r"(?=[\d.,\sx×]*" + _DIM_LENGTH_UNIT + r"\b)" + _DIM_NUM + r"(?:\s*[x×]\s*" + _DIM_NUM + r")*"
# A comma that introduces a trailing dimension spec which then ENDS the clause
# (no descriptive word follows). Matched on the *original* text; the dimension
# run is followed only by whitespace, the end of the string, or a hard
# separator (newline / semicolon / bullet), never a letter-led descriptive word.
_DIM_CONTINUATION_RE = re.compile(
    r",\s*(?P<dim>" + _DIM_CHAIN + r")\s*(?=$|[\n;•])",
    re.IGNORECASE,
)
# Sentinel that cannot occur in real scope text; used to shield a
# spec-continuation comma from the clause splitter, restored afterwards.
_DIM_COMMA_SENTINEL = "\x00DIMCOMMA\x00"


def _shield_spec_commas(text: str) -> str:
    """Replace spec-continuation commas with a sentinel before clause splitting.

    "Brick wall, 24cm" -> "Brick wall<sentinel> 24cm" so the splitter keeps it
    as ONE clause, while "2 doors, 30 m3 concrete" is left untouched (the
    dimension is followed by a descriptive word, so the comma is a real list
    separator). The sentinel is converted back to a literal comma per clause
    after the split.
    """
    return _DIM_CONTINUATION_RE.sub(lambda m: _DIM_COMMA_SENTINEL + " " + m.group("dim"), text)


def _resolve_unit_token(token: str) -> tuple[str, str]:
    """Map a matched unit token to (canonical_quantity_key, catalogue_hint)."""
    norm = token.strip().lower().replace("²", "2").replace("³", "3")
    direct = _TEXT_UNIT_MAP.get(norm)
    if direct:
        return direct
    # Spoken multi-word spelling ("cubic metres"). Match against the spaced
    # patterns anchored to the whole token.
    for pat, hint in _SPACED_UNIT_PATTERNS:
        if re.fullmatch(pat, norm, re.IGNORECASE):
            return ({"m3": "volume_m3", "m2": "area_m2", "m": "length_m"}[hint], hint)
    return ("count", "pcs")


def _parse_qty(raw: str) -> float | None:
    """Parse a human-written quantity ("120", "1,200", "1 200", "3.5")."""
    cleaned = raw.strip().replace(" ", "")
    # A single comma with <=2 trailing digits is a decimal comma (EU); a comma
    # with exactly 3 trailing digits is a thousands separator.
    if "," in cleaned and "." not in cleaned:
        head, _, tail = cleaned.rpartition(",")
        cleaned = head.replace(",", "") + ("." + tail if len(tail) != 3 else tail)
    else:
        cleaned = cleaned.replace(",", "")
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return val if val > 0 else None


def parse_text_scope(text: str) -> list[dict[str, Any]]:
    """Turn a free-text scope into estimable line-item envelopes.

    Deterministic, no AI, no DB. Splits a scope into clauses on newlines and
    common list separators (";", ",", bullets, " and "), then reads a leading
    "<number> <unit>" off each clause. Only numbers the user explicitly wrote
    are read - a quantity is never invented. A clause with no recognisable
    leading quantity still becomes an envelope (description only) so the human
    can quantify it; the grouping pass collapses duplicates.

    A single-line scope like
    ``"120 m2 brick walls, 2 steel doors, 30 m3 C25/30 foundation"`` becomes
    three envelopes with real quantities (120 m2, 2 pcs, 30 m3), instead of one
    un-quantified blob.
    """
    envelopes: list[dict[str, Any]] = []
    if not text or not text.strip():
        return envelopes

    # Shield spec-continuation commas ("Brick wall, 24cm") so the splitter does
    # not break a single descriptive line item at its dimension comma, then
    # split into clauses across lines + inline separators, preserving order.
    shielded = _shield_spec_commas(text)
    fragments = [frag.replace(_DIM_COMMA_SENTINEL, ",").strip() for frag in _CLAUSE_SPLIT_RE.split(shielded)]
    idx = 0
    for frag in fragments:
        if len(frag) < 3:
            continue
        quantities: dict[str, float] = {}
        unit_hint: str | None = None
        match = _LEAD_QTY_RE.match(frag)
        if match:
            qty = _parse_qty(match.group("qty"))
            if qty is not None:
                unit_token = match.group("unit").strip().lower()
                qkey, hint = _resolve_unit_token(unit_token)
                # A tonne is mass in kg; keep the catalogue hint honest as kg.
                if unit_token.replace("²", "2").replace("³", "3") == "t":
                    qty *= 1000.0
                quantities = {qkey: qty}
                unit_hint = hint
        else:
            # No explicit unit - a bare leading count ("2 steel doors") is an
            # explicit piece count the user wrote. Read it as pcs.
            count_match = _LEAD_COUNT_RE.match(frag)
            if count_match:
                qty = _parse_qty(count_match.group("qty"))
                if qty is not None:
                    quantities = {"count": qty}
                    unit_hint = "pcs"
        # Classify the clause into a coarse trade from its own words
        # (deterministic keyword match, no AI). The trade is a real, honest
        # category signal for both the grouping key and the matcher; an
        # un-classifiable clause keeps an empty category.
        from app.modules.ai_estimator.taxonomy import classify_trade

        trade = classify_trade(frag)
        # Description: keep the full clause (it carries the material / spec the
        # matcher's dense query needs); never strip the quantity, only the
        # standalone numeric prefix would lose useful context.
        envelopes.append(
            {
                "id": f"text_{idx}",
                "source": "text",
                "description": frag[:2000],
                "category": trade if trade != "other" else "",
                # Each free-text clause is an independently authored line item:
                # carry a stable per-clause key so two clauses that share a unit
                # (and even a trade) are never silently collapsed into one group.
                "group_hint": f"line_{idx}",
                "unit_hint": unit_hint,
                "quantities": quantities,
            }
        )
        idx += 1
    return envelopes
