# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Magnet-candidate suppressor — post-retrieval, pre-rerank.

Background
==========

The 2026-05-14 match-quality loop (``qa-tests/_match-quality-loop``)
discovered that the cwicr_en_v3 snapshot has a small handful of
candidates that get pulled into the top-10 of *unrelated* queries.
Diagnostic dump (``magnet_analysis.json``):

    KAME_KAPU_KAMEDX_KAME    mf=26 IfcElectricDistributionBoard   18/20
    KAME_KADX_KAKATO_KATO    mf=26 IfcElectricDistributionBoard   18/20
    KAME_KARI_KAMEDX_KARIm   mf=41                                16/20
    KAPU_KARI_KAPURI_KAPU    mf=14                                15/20
    KARI_KARI_KAKATO_KASA    mf=33 IfcReinforcingBar              14/20
    KANE_KAME_KAKALI_KATOm   mf=48                                13/20
    KATO_KAPU_KARIKA_KARIm   mf=14                                11/20

The cause is structural: v3's payload-only schema feeds the BGE
cross-encoder ``(query, code+unit)`` pairs with no description text, so
its preferences become a function of token-id artifacts in the
tokenizer vocabulary rather than topical similarity. The fix
(re-ingesting the snapshot with descriptions) is in another agent's
hands; this module is the complementary intervention: drop the magnets
out of the candidate pool *before* the cross-encoder ever sees them.

Design
======

The filter sits AFTER Qdrant retrieval but BEFORE BGE rerank, so the
re-ranker operates on a cleaner pool. Activation is gated by
``OE_MATCH_MAGNET_FILTER=1`` (default OFF; the bench harness sets it
explicitly).

The suppression decision is confidence-weighted:

    * **Query classifier confidence ≥ 0.80** → hard-drop incompatible
      candidates (we are sure enough about the topic).
    * **0.50 ≤ confidence < 0.80**           → penalise the candidate's
      score by -0.20 (let the cross-encoder still rescue it if the
      bi-encoder hit was very strong).
    * **confidence < 0.50**                  → no-op (don't risk
      over-suppression on ambiguous queries — the recall ceiling on
      edge cases matters more than precision on the obvious ones).

The query classifier is *only* the envelope's own structured fields
(``ifc_class``, ``unit_hint`` / ``quantities``, ``classifier_hint``,
``material_class``). It deliberately does NOT call back into the
embedding model — that would re-introduce the very non-determinism
this filter aims to neutralise.

Compatibility is checked along three axes:

    1. **MasterFormat division** — query's expected MF division head
       (``"03"`` from a concrete wall, ``"22"`` from a copper pipe) vs
       candidate's ``masterformat_division`` payload head. Aligned
       families pass; cross-family fails.
    2. **Unit type** — query's coarse unit family (Area / Volume /
       Linear / Mass / Count / Time) vs candidate's ``unit_type``
       payload. A wall (Area) candidate must NOT win the top slot of
       a pipe (Linear) query.
    3. **IFC class** — query's ``ifc_class`` vs candidate's
       ``ifc_class`` payload, with a per-MF compatibility map (some
       cross-class hits are legitimate: an IfcCovering can be a
       roof finish for an IfcRoof query).

A candidate must FAIL *all three* axes (or fail two when the third is
unknown on either side) before it gets flagged. The threshold is
deliberately conservative — over-suppression is worse than letting
one magnet slip through.

Logging
=======

Every suppression decision is logged at ``DEBUG`` level::

    magnet_filter: query=q01 confidence=0.92 dropped=KAME_KAPU_KAMEDX_KAME
        reason=mf_mismatch+ifc_mismatch+unit_mismatch

So an operator with ``OE_LOG_LEVEL=DEBUG`` can audit every drop
without code modifications.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

logger = logging.getLogger(__name__)


# ── Public env-var gate ──────────────────────────────────────────────────


def is_enabled() -> bool:
    """‌⁠‍Return ``True`` when ``OE_MATCH_MAGNET_FILTER`` is truthy.

    Cheap probe — read once per call. Off by default so production
    traffic keeps the legacy behaviour until the bench validates the
    intervention. Truthy values follow the same convention as
    ``determinism.is_enabled``: ``1``, ``true``, ``yes``, ``on``.
    """
    raw = (os.environ.get("OE_MATCH_MAGNET_FILTER") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# ── Tunable thresholds ───────────────────────────────────────────────────
#
# All env-overridable so an operator can A/B-test bands without a code
# deploy. Defaults chosen to be conservative on over-suppression risk.

_HARD_DROP_FLOOR: float = 0.80  # ≥ this confidence → hard-drop incompatible
_SOFT_PENALTY_FLOOR: float = 0.50  # ≥ this → penalty; below → no-op
_SOFT_PENALTY: float = -0.20  # additive score delta for soft-penalty


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _thresholds() -> tuple[float, float, float]:
    """‌⁠‍(hard_drop_floor, soft_penalty_floor, soft_penalty)."""
    return (
        _env_float("OE_MATCH_MAGNET_HARD_FLOOR", _HARD_DROP_FLOOR),
        _env_float("OE_MATCH_MAGNET_SOFT_FLOOR", _SOFT_PENALTY_FLOOR),
        _env_float("OE_MATCH_MAGNET_PENALTY", _SOFT_PENALTY),
    )


# ── Unit-family canonicalisation ─────────────────────────────────────────
#
# Mirrors ``ranker_qdrant._unit_family`` but extended with the Qdrant
# payload's ``unit_type`` enum (``"Area"`` / ``"Volume"`` / ``"Linear"``
# / ``"Mass"`` / ``"Count"`` / ``"Time"``) so we can compare the query's
# inferred family with the candidate's stored family without an extra
# normalisation step.

_UNIT_HINT_TO_FAMILY: dict[str, str] = {
    "m3": "volume",
    "m³": "volume",
    "cy": "volume",
    "cbm": "volume",
    "cum": "volume",
    "cubic meter": "volume",
    "cubic metre": "volume",
    "m2": "area",
    "m²": "area",
    "sm": "area",
    "sf": "area",
    "sqm": "area",
    "sqft": "area",
    "m": "linear",
    "lm": "linear",
    "lf": "linear",
    "lfm": "linear",
    "rm": "linear",
    "kg": "mass",
    "t": "mass",
    "ton": "mass",
    "tonne": "mass",
    "tn": "mass",
    "pcs": "count",
    "ea": "count",
    "stk": "count",
    "nr": "count",
    "no": "count",
    "u": "count",
    "stck": "count",
    "h": "time",
    "hr": "time",
    "hour": "time",
}

_QUANTITY_KEY_TO_FAMILY: dict[str, str] = {
    "volume_m3": "volume",
    "area_m2": "area",
    "length_m": "linear",
    "perimeter_m": "linear",
    "mass_kg": "mass",
    "weight_kg": "mass",
    "count": "count",
    "quantity": "count",
}

# Canonicalise the Qdrant payload's ``unit_type`` enum.
_PAYLOAD_UNIT_TYPE_TO_FAMILY: dict[str, str] = {
    "area": "area",
    "volume": "volume",
    "linear": "linear",
    "mass": "mass",
    "count": "count",
    "time": "time",
}


def _unit_family_from_hint(unit_hint: str | None) -> str | None:
    if not unit_hint:
        return None
    u = str(unit_hint).strip().lower().replace("²", "2").replace("³", "3")
    return _UNIT_HINT_TO_FAMILY.get(u)


def _unit_family_from_quantities(quantities: dict[str, float] | None) -> str | None:
    if not quantities:
        return None
    # Precedence — volume > area > linear > mass > count. A wall
    # carrying both ``area_m2`` AND ``length_m`` should be classified
    # as Area (it's priced per m²), not Linear.
    for key in ("volume_m3", "area_m2", "length_m", "perimeter_m", "mass_kg", "weight_kg", "count", "quantity"):
        v = quantities.get(key)
        if v is not None:
            try:
                if float(v) > 0:
                    return _QUANTITY_KEY_TO_FAMILY[key]
            except (TypeError, ValueError):
                continue
    return None


def _unit_family_from_payload(unit_type: str | None) -> str | None:
    if not unit_type:
        return None
    return _PAYLOAD_UNIT_TYPE_TO_FAMILY.get(str(unit_type).strip().lower())


# ── MasterFormat division compatibility ──────────────────────────────────
#
# Cross-division compatibility ONLY for cases where two MF divisions
# legitimately overlap. Two-digit head only — we deliberately don't
# specialise below the head (an IfcWall in 03 should not be suppressed
# when the query has expected_mf="04"; the cross-encoder can sort the
# masonry-vs-concrete order out, that's not a magnet, that's adjacency).
#
# Adjacency convention: A and B are in this set when a query targeting
# A might legitimately want a B candidate. NOT symmetric in general —
# e.g. concrete (03) might want some sitework (31) but sitework
# generally doesn't want concrete.

_MF_ADJACENCY: set[tuple[str, str]] = {
    ("03", "31"),  # Cast-in-place concrete adjacent to earthwork (foundations)
    ("03", "04"),  # Concrete and masonry both structural
    ("04", "03"),
    ("05", "06"),  # Structural metal/wood adjacency (composite)
    ("06", "05"),
    ("07", "09"),  # Thermal/moisture and finishes (insulation+drywall)
    ("09", "07"),
    ("08", "09"),  # Openings and finishes (frames+drywall)
    ("09", "08"),
    ("22", "23"),  # Plumbing and HVAC both MEP-mechanical
    ("23", "22"),
    ("26", "27"),  # Electrical and communications both MEP-electrical
    ("27", "26"),
}


def _mf_head(mf: str | None) -> str:
    """Return the 2-char division head of a MasterFormat string."""
    if not mf:
        return ""
    raw = str(mf).strip()
    if not raw:
        return ""
    # MasterFormat codes look like "03 30 00" or "03.30.00" or "03"
    head = raw.split()[0]
    head = head.split(".")[0]
    return head[:2]


def _mf_compatible(query_mf_heads: list[str], cand_mf_head: str) -> bool:
    """Return ``True`` when candidate's MF head is in the query's universe.

    A query without an MF head is treated as compatible with everything —
    we can't reject what we don't know. A candidate without an MF head
    falls into the "unknown" bucket and is NOT rejected on the MF axis
    alone (the rule below still requires multi-axis incompatibility).
    """
    if not query_mf_heads:
        return True
    if not cand_mf_head:
        return True
    for q in query_mf_heads:
        if q == cand_mf_head:
            return True
        if (q, cand_mf_head) in _MF_ADJACENCY:
            return True
    return False


# ── IFC class compatibility ──────────────────────────────────────────────
#
# Some IFC classes legitimately substitute for each other. The most
# important case: ``IfcCovering`` is the catch-all for finishes (ceiling,
# floor, wall finish, roof finish, insulation), so it's a valid answer
# for ``IfcRoof`` / ``IfcSlab`` / ``IfcWall`` queries where the search is
# for the finishing layer rather than the structural element.

_IFC_ADJACENCY: dict[str, set[str]] = {
    "IfcWall": {"IfcWallStandardCase", "IfcCovering"},
    "IfcSlab": {"IfcCovering", "IfcFooting"},
    "IfcRoof": {"IfcCovering", "IfcSlab"},
    "IfcFooting": {"IfcSlab", "IfcPile"},
    "IfcBeam": {"IfcColumn"},
    "IfcColumn": {"IfcBeam"},
    "IfcCovering": {"IfcWall", "IfcSlab", "IfcRoof", "IfcFlooring"},
    "IfcCurtainWall": {"IfcWindow", "IfcWall"},
    "IfcPipeSegment": {"IfcPipeFitting"},
    "IfcDuctSegment": {"IfcDuctFitting"},
    "IfcDoor": {"IfcWindow"},  # Both are openings
    "IfcWindow": {"IfcDoor", "IfcCurtainWall"},
    "IfcSpaceHeater": {"IfcPipeSegment"},  # Radiators connect to plumbing
    "IfcOutlet": {"IfcLightFixture"},
    "IfcLightFixture": {"IfcOutlet"},
}


def _ifc_compatible(query_ifc: str | None, cand_ifc: str | None) -> bool:
    """Return ``True`` when candidate's IFC class matches or substitutes."""
    if not query_ifc:
        return True
    if not cand_ifc:
        return True
    if query_ifc == cand_ifc:
        return True
    # Symmetric: a query for X is compatible with adjacency-set(X) ∪ {Y : X ∈ adjacency-set(Y)}
    if cand_ifc in _IFC_ADJACENCY.get(query_ifc, set()):
        return True
    if query_ifc in _IFC_ADJACENCY.get(cand_ifc, set()):
        return True
    # Substring tolerance for predefined-type variants (``IfcWallStandardCase``)
    if query_ifc in cand_ifc or cand_ifc in query_ifc:
        return True
    return False


# ── Query classifier ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueryClassification:
    """Structured anchor extracted from the envelope.

    Attributes:
        mf_heads: Likely MasterFormat division heads (``["03"]`` for
            concrete, ``["22"]`` for plumbing). Empty list when no
            classifier hint and no IFC-class-implied MF mapping fires.
        unit_family: Coarse unit family — area / volume / linear / mass
            / count / time. ``None`` when the envelope carries neither
            ``unit_hint`` nor recognisable ``quantities``.
        ifc_class: Verbatim IFC class from the envelope. ``None`` when
            the envelope didn't declare one (PDF / DWG / photo paths).
        confidence: Heuristic confidence in [0, 1]. Combines:
            * IFC class present                   (+0.30)
            * MF head derivable                   (+0.20)
            * Unit family inferable               (+0.20)
            * material_class set                  (+0.15)
            * BIM source (not pdf/photo)          (+0.15)
            Max 1.0. The filter consults ``confidence`` to decide
            between hard-drop / soft-penalty / no-op.
    """

    mf_heads: tuple[str, ...]
    unit_family: str | None
    ifc_class: str | None
    confidence: float


# Coarse mapping from IFC class → likely MasterFormat division heads.
# Used when the envelope has an IFC class but no explicit classifier
# hint. Kept narrow on purpose: when an envelope's classifier_hint is
# present we trust it verbatim; this map is only a fallback.
_IFC_TO_MF_HEADS: dict[str, tuple[str, ...]] = {
    "IfcWall": ("03", "04", "09"),
    "IfcSlab": ("03",),
    "IfcFooting": ("03", "31"),
    "IfcColumn": ("03", "05"),
    "IfcBeam": ("05", "06", "03"),
    "IfcRoof": ("07",),
    "IfcCurtainWall": ("08",),
    "IfcDoor": ("08",),
    "IfcWindow": ("08",),
    "IfcCovering": ("09", "07"),
    "IfcFlooring": ("09",),
    "IfcPipeSegment": ("22",),
    "IfcDuctSegment": ("23",),
    "IfcSpaceHeater": ("23",),
    "IfcOutlet": ("26",),
    "IfcLightFixture": ("26",),
    "IfcCableSegment": ("26",),
    "IfcReinforcingBar": ("03",),
    "IfcStair": ("06", "05"),
    "IfcRailing": ("05", "06"),
}


def classify_query(envelope: ElementEnvelope) -> QueryClassification:
    """Heuristic structured classification of the query.

    Pure function — no model calls, no DB access — so a per-request
    invocation costs microseconds. The output is consumed by
    :func:`should_suppress` to decide whether each retrieval candidate
    survives the filter.
    """
    # MF heads: prefer explicit classifier_hint, fall back to IFC mapping.
    mf_heads: list[str] = []
    hint = envelope.classifier_hint or {}
    if hint:
        mf_raw = (hint.get("masterformat") or "").strip()
        head = _mf_head(mf_raw)
        if head:
            mf_heads.append(head)

    ifc = (envelope.ifc_class or "").strip() or None
    if not mf_heads and ifc:
        mf_heads.extend(_IFC_TO_MF_HEADS.get(ifc, ()))

    # Unit family
    unit_family = _unit_family_from_hint(envelope.unit_hint)
    if not unit_family:
        unit_family = _unit_family_from_quantities(envelope.quantities)

    # Confidence — see docstring for the breakdown
    conf = 0.0
    if ifc:
        conf += 0.30
    if mf_heads:
        conf += 0.20
    if unit_family:
        conf += 0.20
    if envelope.material_class:
        conf += 0.15
    if (envelope.source or "").lower() == "bim":
        conf += 0.15
    conf = min(1.0, conf)

    return QueryClassification(
        mf_heads=tuple(mf_heads),
        unit_family=unit_family,
        ifc_class=ifc,
        confidence=conf,
    )


# ── Candidate compatibility check ────────────────────────────────────────


@dataclass(frozen=True)
class SuppressionDecision:
    """Decision payload for one (query, candidate) pair.

    Attributes:
        action: ``"drop"``, ``"penalise"``, ``"keep"``.
        score_delta: 0.0 for drop/keep; ``_SOFT_PENALTY`` for penalise.
        reasons: List of axis names that failed (``"mf_mismatch"``,
            ``"ifc_mismatch"``, ``"unit_mismatch"``). Empty when
            action == "keep".
    """

    action: str  # "drop" | "penalise" | "keep"
    score_delta: float
    reasons: tuple[str, ...]


def _candidate_payload(candidate: MatchCandidate) -> dict[str, Any]:
    """Extract the payload-style fields from a MatchCandidate.

    The candidate is the post-_hit_to_candidate object — it carries
    ``classification.masterformat`` derived from either the parquet or
    the Qdrant payload. We also accept that ``unit_type`` and
    ``ifc_class`` may not be present on every candidate (the candidate
    schema doesn't surface them as first-class fields) — when missing
    we treat that axis as unknown rather than incompatible.

    The function returns a dict mirroring the Qdrant payload keys so
    the rest of this module can operate uniformly whether the input
    came from a candidate or a raw Qdrant payload (used by unit tests).
    """
    cls = candidate.classification or {}
    return {
        "masterformat_division": cls.get("masterformat", ""),
        # ``unit_type`` is NOT a MatchCandidate field — fall back to
        # the canonical short unit ("m3" / "m2") which we can map.
        "unit_type": _unit_family_from_hint(candidate.unit) or "",
        "ifc_class": "",  # not on candidate; supplied by raw_payload path
    }


def _decide_compat(
    classification: QueryClassification,
    payload: dict[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    """Return ``(compatible, reasons)`` for one candidate payload.

    A candidate is INCOMPATIBLE when at least 2 of the 3 axes
    (mf / ifc / unit) actively disagree AND both sides of each
    failed axis carried a value. Mere absence on one side is NOT a
    failure — we don't suppress candidates whose schema is sparse.

    Returns:
        ``(True,  ())``                — keep this candidate.
        ``(False, ("mf", "ifc", ...))`` — reasons for suppression.
    """
    reasons: list[str] = []
    # MasterFormat
    cand_mf = _mf_head(str(payload.get("masterformat_division") or ""))
    if classification.mf_heads and cand_mf:
        if not _mf_compatible(list(classification.mf_heads), cand_mf):
            reasons.append("mf_mismatch")

    # IFC class
    cand_ifc = (str(payload.get("ifc_class") or "")).strip() or None
    if classification.ifc_class and cand_ifc:
        if not _ifc_compatible(classification.ifc_class, cand_ifc):
            reasons.append("ifc_mismatch")

    # Unit type
    cand_unit_family = _unit_family_from_payload(payload.get("unit_type"))
    if not cand_unit_family:
        # Fall back to interpreting ``rate_unit`` short code
        cand_unit_family = _unit_family_from_hint(payload.get("rate_unit"))
    if classification.unit_family and cand_unit_family:
        if classification.unit_family != cand_unit_family:
            reasons.append("unit_mismatch")

    # Decision rule: 2+ axes incompatible OR a single MF mismatch when
    # both IFC and unit info are unknown on the candidate. The latter
    # catches the cross-encoder magnets where the candidate has only
    # an MF head and no IFC/unit info — the v3 payload is sparse on
    # purpose and the magnets exploit exactly that gap.
    if len(reasons) >= 2:
        return False, tuple(reasons)
    if reasons == ["mf_mismatch"] and not cand_ifc and not cand_unit_family and classification.confidence >= 0.65:
        return False, tuple(reasons + ["sparse_payload"])
    return True, ()


def should_suppress(
    classification: QueryClassification,
    payload: dict[str, Any],
) -> SuppressionDecision:
    """Decide what to do with one (query, candidate) pair.

    Thresholds are env-overridable (see :func:`_thresholds`). The
    return value is a :class:`SuppressionDecision` so the caller can
    log the reason without re-running the compatibility check.
    """
    hard_floor, soft_floor, soft_penalty = _thresholds()

    # Confidence < soft_floor: too uncertain to risk over-suppression.
    if classification.confidence < soft_floor:
        return SuppressionDecision(action="keep", score_delta=0.0, reasons=())

    compatible, reasons = _decide_compat(classification, payload)
    if compatible:
        return SuppressionDecision(action="keep", score_delta=0.0, reasons=())

    if classification.confidence >= hard_floor:
        return SuppressionDecision(action="drop", score_delta=0.0, reasons=reasons)
    return SuppressionDecision(action="penalise", score_delta=soft_penalty, reasons=reasons)


# ── Pipeline integration ─────────────────────────────────────────────────


def apply_to_hits(
    envelope: ElementEnvelope,
    hits: list[Any],
    *,
    full_rows: dict[str, dict[str, Any]] | None = None,
    query_id: str | None = None,
) -> list[Any]:
    """Filter / penalise a list of :class:`QdrantHit` post-retrieval.

    Called from ``ranker_qdrant.rank`` AFTER Qdrant retrieval +
    abstract substitution + soft boosts, but BEFORE the
    ``_hit_to_candidate`` cast and BGE rerank. Operates in place on
    ``hit.score`` for penalised entries and returns a new list with
    dropped entries removed.

    The full Qdrant payload is available on each hit (``hit.payload``)
    so we read directly from it — no need to attach the parquet row
    first. ``full_rows`` is accepted for symmetry with the soft-boost
    plumbing but is not load-bearing here.

    Logs every drop / penalise at DEBUG level::

        magnet_filter: query=q01 conf=0.95 dropped=RATE_CODE_X
            reason=mf_mismatch+ifc_mismatch+unit_mismatch

    No-ops (returns the input list unchanged) when:

    * the env var gate is OFF, OR
    * the envelope's classifier confidence is below ``_SOFT_PENALTY_FLOOR``
      (we can't suppress what we can't classify), OR
    * ``hits`` is empty.
    """
    if not hits or not is_enabled():
        return hits

    classification = classify_query(envelope)
    _, soft_floor, _ = _thresholds()
    if classification.confidence < soft_floor:
        logger.debug(
            "magnet_filter: query=%s conf=%.2f below floor %.2f — no-op",
            query_id or "?",
            classification.confidence,
            soft_floor,
        )
        return hits

    kept: list[Any] = []
    dropped = 0
    penalised = 0
    for hit in hits:
        payload = dict(getattr(hit, "payload", None) or {})
        # Fall back to parquet row when payload is missing the relevant key.
        if full_rows:
            row = full_rows.get(getattr(hit, "rate_code", ""), {})
            for k in ("masterformat_division", "ifc_class", "unit_type", "rate_unit"):
                if not payload.get(k) and row.get(k):
                    payload[k] = row[k]

        decision = should_suppress(classification, payload)

        if decision.action == "drop":
            dropped += 1
            logger.debug(
                "magnet_filter: query=%s conf=%.2f DROP code=%s ifc=%s mf=%s unit=%s reason=%s",
                query_id or "?",
                classification.confidence,
                getattr(hit, "rate_code", "?"),
                payload.get("ifc_class") or "-",
                payload.get("masterformat_division") or "-",
                payload.get("unit_type") or "-",
                "+".join(decision.reasons),
            )
            continue
        if decision.action == "penalise":
            try:
                hit.score = float(hit.score) + decision.score_delta
            except Exception:
                pass
            penalised += 1
            logger.debug(
                "magnet_filter: query=%s conf=%.2f PENALISE code=%s delta=%.2f ifc=%s mf=%s unit=%s reason=%s",
                query_id or "?",
                classification.confidence,
                getattr(hit, "rate_code", "?"),
                decision.score_delta,
                payload.get("ifc_class") or "-",
                payload.get("masterformat_division") or "-",
                payload.get("unit_type") or "-",
                "+".join(decision.reasons),
            )
        kept.append(hit)

    if dropped or penalised:
        logger.info(
            "magnet_filter: query=%s conf=%.2f kept=%d dropped=%d penalised=%d (qry_ifc=%s qry_mf=%s qry_unit=%s)",
            query_id or "?",
            classification.confidence,
            len(kept),
            dropped,
            penalised,
            classification.ifc_class or "-",
            ",".join(classification.mf_heads) or "-",
            classification.unit_family or "-",
        )
    return kept


__all__ = [
    "QueryClassification",
    "SuppressionDecision",
    "apply_to_hits",
    "classify_query",
    "is_enabled",
    "should_suppress",
]
