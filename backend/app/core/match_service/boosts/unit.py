# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit boost — rewards unit alignment, penalises type-mismatches.

CWICR position units stay in canonical short codes: ``m``, ``m2`` /
``m²``, ``m3`` / ``m³``, ``kg``, ``pcs``, ``lsum``. Element envelopes
either provide an explicit ``unit_hint`` or carry quantities the
matcher can use to infer one.

The penalty on type-mismatch (e.g. envelope is m³, candidate is m²) is
deliberately larger than the reward on match — a wrong unit means the
unit_rate is meaningless even if the description aligns, so we'd
rather drop the candidate than promote it.
"""

from __future__ import annotations

from typing import Any

from app.core.match_service.config import BOOST_WEIGHTS
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

# Canonical unit codes the matcher understands.
_VALID_UNITS = {"m", "m2", "m3", "kg", "pcs", "lsum", "lm", "h", "t"}

# Mapping ``quantities`` keys to the inferred unit. We hit this when no
# explicit ``unit_hint`` was supplied — helpful for BIM elements where
# the canonical-format geometry block already implies the unit.
_QUANTITY_TO_UNIT: dict[str, str] = {
    "length_m": "m",
    "perimeter_m": "m",
    "area_m2": "m2",
    "volume_m3": "m3",
    "mass_kg": "kg",
    "weight_kg": "kg",
    "count": "pcs",
    "quantity": "pcs",
}

# Units that disagree on dimensionality — m vs m2 vs m3. A wall extracted
# as area_m2 must NEVER be matched to an m3 cost item; the price would
# be off by a factor of thickness.
_DIMENSION_GROUP: dict[str, str] = {
    "m": "length",
    "lm": "length",
    "m2": "area",
    "m3": "volume",
    "kg": "mass",
    "t": "mass",
    "pcs": "count",
    "lsum": "lsum",
    "h": "time",
}


def _normalise_unit(unit: str) -> str:
    """Strip whitespace, lowercase, fold superscript m² / m³ → m2 / m3."""
    if not unit:
        return ""
    cleaned = unit.strip().lower()
    cleaned = cleaned.replace("²", "2").replace("³", "3")
    # Some catalogues store ``"m^2"`` or ``"m**2"`` — fold to ``m2``.
    cleaned = cleaned.replace("^", "").replace("**", "")
    if cleaned in _VALID_UNITS:
        return cleaned
    return cleaned  # Pass through unknown codes — the comparison still works


def _infer_from_quantities(quantities: dict[str, float]) -> str | None:
    """Pick the unit implied by the highest-precedence non-empty quantity.

    Precedence is dimensional: volume > area > length > mass > count.
    A wall element typically carries both ``area_m2`` and ``length_m``;
    we prefer the more specific dimension because that's what an
    estimator will price the position by.
    """
    precedence = ("volume_m3", "area_m2", "length_m", "perimeter_m", "mass_kg", "weight_kg", "count", "quantity")
    for key in precedence:
        value = quantities.get(key)
        if value is not None and float(value) > 0:
            return _QUANTITY_TO_UNIT.get(key)
    return None


def boost(
    envelope: ElementEnvelope,
    candidate: MatchCandidate,
    settings: Any,  # noqa: ARG001 — unused, kept for interface symmetry
) -> dict[str, float]:
    """Reward unit alignment, penalise dimensional mismatch.

    No-ops (returns ``{}``) when:
        * neither side has a unit, OR
        * one side is missing a unit and the dimensions can't be inferred.
    """
    cand_unit = _normalise_unit(candidate.unit)
    if not cand_unit:
        return {}

    env_unit = _normalise_unit(envelope.unit_hint or "")
    if not env_unit:
        env_unit = _normalise_unit(_infer_from_quantities(envelope.quantities) or "")
    if not env_unit:
        return {}

    if env_unit == cand_unit:
        return {"unit_match": BOOST_WEIGHTS.unit_match}

    # Different units — only penalise on a real dimensional mismatch.
    # ``m`` vs ``lm`` for example is the same dimension; treat as no-op.
    env_dim = _DIMENSION_GROUP.get(env_unit, env_unit)
    cand_dim = _DIMENSION_GROUP.get(cand_unit, cand_unit)
    if env_dim and cand_dim and env_dim != cand_dim:
        return {"unit_mismatch": BOOST_WEIGHTS.unit_mismatch_penalty}

    return {}
