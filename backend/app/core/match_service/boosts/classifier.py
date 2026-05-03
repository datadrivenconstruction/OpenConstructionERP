# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Classifier boost — rewards candidates whose classification matches the hint."""

from __future__ import annotations

from typing import Any

from app.core.match_service.config import BOOST_WEIGHTS
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

# Map ``settings.classifier`` to the candidate field that carries that
# classification code. The vector adapter writes these payload keys.
_CLASSIFIER_FIELDS: dict[str, str] = {
    "din276": "classification_din276",
    "nrm": "classification_nrm",
    "masterformat": "classification_masterformat",
}


def _normalise_code(code: str) -> str:
    """Lowercase + strip a code so ``" 330.10 "`` matches ``"330.10"``."""
    return (code or "").strip().lower()


def _group_prefix(code: str) -> str:
    """Return the leading group segment of a hierarchical code.

    DIN 276 uses ``KG.LL.PPP`` form (``"330.10.020"``); MasterFormat uses
    ``"04 20 00"``. We extract the first dotted segment for DIN-style
    codes; for whitespace-separated codes we take the first space-token.
    Empty string when the code has no recognisable separator.
    """
    code = (code or "").strip()
    if not code:
        return ""
    for sep in (".", " "):
        if sep in code:
            return code.split(sep, 1)[0]
    # Bare 3-digit code like "330" — the candidate prefix == itself.
    return code


def boost(
    envelope: ElementEnvelope,
    candidate: MatchCandidate,
    settings: Any,
) -> dict[str, float]:
    """Add classifier match boost.

    Resolution:
        * exact code match → :data:`BoostWeights.classifier_full_match`
        * group-prefix match (e.g. ``"330"`` matches ``"330.10.020"``) →
          :data:`BoostWeights.classifier_group_match`
        * no match or no hint → ``{}`` (no contribution)
    """
    classifier = (getattr(settings, "classifier", "none") or "none").lower()
    if classifier == "none" or classifier not in _CLASSIFIER_FIELDS:
        return {}

    hint_map = envelope.classifier_hint or {}
    if not hint_map:
        return {}

    hint_code = _normalise_code(str(hint_map.get(classifier, "")))
    if not hint_code:
        return {}

    cand_code = _normalise_code(getattr(candidate, _CLASSIFIER_FIELDS[classifier], ""))
    if not cand_code:
        # Some candidates don't carry the chosen classifier — fall back to
        # the candidate's classification dict (for envelopes where we
        # already enriched the candidate model with that field).
        cand_code = _normalise_code(candidate.classification.get(classifier, ""))
    if not cand_code:
        return {}

    if cand_code == hint_code:
        return {"classifier_match": BOOST_WEIGHTS.classifier_full_match}

    hint_group = _group_prefix(hint_code)
    cand_group = _group_prefix(cand_code)
    if hint_group and hint_group == cand_group:
        return {"classifier_group_match": BOOST_WEIGHTS.classifier_group_match}

    # Last fallback: prefix containment so a hint like ``"330"`` matches
    # ``"330.10.020"``. We require ≥ 3 characters so a 2-digit operator
    # typo like ``"33"`` doesn't sweep up every code starting with 33.
    # Only the forward direction (cand starts with hint) is allowed —
    # the reverse direction would treat a candidate like ``"33"`` as a
    # match for a fully-qualified ``"330.10.020"`` hint, which is
    # over-broad. Document: forward containment only, min 3 chars.
    if hint_code and len(hint_code) >= 3 and cand_code.startswith(hint_code):
        return {"classifier_group_match": BOOST_WEIGHTS.classifier_group_match}

    return {}
