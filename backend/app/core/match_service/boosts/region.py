# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Region boost — rewards candidates from the project's region.

CWICR ships one regional file per market (``DE_BERLIN``, ``GB_LONDON``,
``USA_NEWYORK``, ...). When the project says "DACH" the matcher should
prefer DACH-priced candidates even if a UK candidate has marginally
higher cosine similarity — the unit rate in the wrong region is a
useless number.

This boost is deliberately small (5 %) because regional preference
should bias ties, not override clear semantic mismatches.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.match_service.config import BOOST_WEIGHTS
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

_log = logging.getLogger(__name__)

# Project-region keyword → tuple of CWICR country prefixes the candidate's
# ``region_code`` should start with for a region match.
#
# Two layers, in lookup precedence order:
#
# 1. **Hand-curated multi-country aliases** (``_REGION_GROUP_ALIASES``).
#    These are macro-regions a human picks in the project picker
#    ("DACH" = DE+AT+CH, "UK" = GB+IE) that don't correspond to a single
#    ISO country. They have to be enumerated explicitly.
# 2. **Auto-derived single-country prefixes** from
#    :data:`region_language.REGION_LANGUAGE`. Every country with at
#    least one CWICR catalogue gets a `"<iso>": ("<ISO>_",)` row at
#    import time so a project pinned to ``HR_ZAGREB`` (the CWICR
#    region) or just ``HR`` (bare country code) automatically gets a
#    Croatian-rate boost — without anyone having to remember to add
#    Croatia to a hand-edited table here.
#
# Result: the boost stays consistent with whatever regions the catalogue
# layer knows about. Adding a new country to ``REGION_LANGUAGE`` (e.g. a
# future Vietnam catalogue) needs zero changes in this file.
#
# Two flavours of multi-country alias coexist:
#   - **Geographic** (DACH, UK, Iberia, LATAM, Benelux, Gulf, Scandinavia)
#     group countries by physical proximity. Picked when the operator's
#     supply chain is regionally clustered.
#   - **Language-family** (anglophone, hispanic, lusophone, francophone,
#     germanic, slavic, arabic, nordic) group countries by primary
#     working language. Picked when the operator wants the matcher to
#     consider semantically-equivalent rates from any country sharing
#     the language — e.g. an ES-Madrid project willing to accept MX or
#     AR rates as fallback when ES coverage is thin.
# The two are NOT auto-merged — picking "ES" stays single-country to
# avoid surprise. Operators opt into language coupling explicitly.
#
# Two-layer composition:
#   1. ``_HARDCODED_REGION_GROUPS`` — the baseline 17 groups inlined
#      below. Acts as the defensive fallback when the YAML file is
#      missing, malformed, or pyyaml is unavailable. Boot never breaks.
#   2. ``data/match/region_groups.yaml`` — operator-extendable mapping
#      loaded at import time. Merged into the baseline (YAML wins on
#      key conflicts) so post-Phase-A additions (ASEAN, MENA_AR,
#      ANGLO_AFRICA, ANDEAN, CAUCASUS, ...) ship without a Python edit.
_HARDCODED_REGION_GROUPS: dict[str, tuple[str, ...]] = {
    # ── Geographic ──────────────────────────────────────────────────
    "dach": ("DE_", "AT_", "CH_"),
    "uk": ("GB_", "IE_"),
    "us": ("USA_", "US_"),
    "usa": ("USA_", "US_"),
    "benelux": ("NL_", "BE_", "LU_"),
    "iberia": ("ES_", "PT_"),
    "scandinavia": ("SE_", "SV_", "NO_", "DK_", "FI_"),
    "gulf": ("AE_", "SA_", "QA_", "KW_", "BH_", "OM_"),
    "latam": ("MX_", "BR_", "AR_", "CL_", "CO_", "PE_"),
    # ── Language-family ─────────────────────────────────────────────
    "anglophone": (
        "USA_",
        "US_",
        "GB_",
        "IE_",
        "AU_",
        "NZ_",
        "CA_",
        "ZA_",
        "IN_",
        "NG_",
    ),
    "hispanic": (
        "ES_",
        "MX_",
        "AR_",
        "CL_",
        "CO_",
        "PE_",
        "EC_",
        "UY_",
        "PY_",
        "BO_",
        "DO_",
        "CR_",
        "VE_",
        "GT_",
        "PA_",
        "HN_",
        "SV_",
        "NI_",
    ),
    "lusophone": ("PT_", "BR_", "AO_", "MZ_", "CV_", "TL_"),
    "francophone": (
        "FR_",
        "BE_",
        "CH_",
        "CA_",
        "MA_",
        "TN_",
        "DZ_",
        "SN_",
        "CI_",
        "CM_",
        "MG_",
        "CD_",
        "BF_",
        "ML_",
        "GN_",
        "TG_",
        "BJ_",
        "NE_",
        "RW_",
        "BI_",
        "DJ_",
        "GA_",
        "LU_",
        "MC_",
    ),
    "germanic": ("DE_", "AT_", "CH_", "LI_"),
    "slavic": (
        "RU_",
        "UA_",
        "BY_",
        "PL_",
        "CZ_",
        "SK_",
        "BG_",
        "RS_",
        "HR_",
        "SI_",
        "MK_",
        "BA_",
        "ME_",
    ),
    "arabic": (
        "AE_",
        "SA_",
        "QA_",
        "KW_",
        "BH_",
        "OM_",
        "EG_",
        "MA_",
        "TN_",
        "DZ_",
        "JO_",
        "LB_",
        "SY_",
        "IQ_",
        "YE_",
        "PS_",
        "LY_",
        "SD_",
    ),
    "nordic": ("SE_", "SV_", "NO_", "DK_", "FI_", "IS_"),
    "turkic": ("TR_", "AZ_", "KZ_", "UZ_", "TM_", "KG_", "TJ_"),
    "sinic": ("CN_", "TW_", "HK_", "SG_"),
}


def _normalise_prefix(value: str) -> str:
    """Coerce a YAML entry to the trailing-underscore prefix form.

    YAML supports either bare country codes (``"DE"``) or full
    ``COUNTRY_CITY`` ids (``"DE_BERLIN"``). Both are normalised to the
    trailing-underscore prefix form (``"DE_"``, ``"DE_BERLIN_"``) so
    they slot into the same ``startswith()`` comparison the existing
    hardcoded baseline uses (every entry there already ends in ``_``).
    The unit invariant ``test_region_group_aliases_are_uppercase_prefixes``
    enforces the convention; merging non-suffixed city codes would
    silently break it.

    For city-level entries this means a project pinned to e.g. ``ID``
    matches catalogues like ``ID_JAKARTA`` / ``ID_SURABAYA`` via the
    bare-country prefix (``ID_``, also present in every group spec).
    The city-suffixed entry (``ID_JAKARTA_``) is a forward-compatible
    no-op today and only fires if the catalogue layer ships a sub-zone
    ``ID_JAKARTA_<area>`` row. We keep it for symmetry with the data
    spec and for future sub-city granularity.

    Empty / non-string values are dropped silently — bad YAML rows
    must never crash boot.
    """
    if not isinstance(value, str):
        return ""
    upper = value.strip().upper()
    if not upper:
        return ""
    if upper.endswith("_"):
        return upper
    return f"{upper}_"


def _load_region_groups_from_yaml() -> dict[str, tuple[str, ...]]:
    """Load ``data/match/region_groups.yaml`` into the alias dict shape.

    Returns an empty dict when:
      * pyyaml isn't importable in this environment,
      * the YAML file doesn't exist at the expected path,
      * the file is unreadable or contains malformed YAML,
      * the top-level structure isn't a mapping with a ``groups`` key.

    Each failure mode is logged at WARNING level (not ERROR) so the
    matcher continues to operate on the hardcoded fallback. The intent
    is "data-driven extension is best-effort, never load-bearing".
    """
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        _log.warning("pyyaml unavailable — region_groups.yaml extension disabled, matcher uses hardcoded baseline only")
        return {}

    # backend/app/core/match_service/boosts/region.py → repo root via 5x ``parents``.
    repo_root = Path(__file__).resolve().parents[5]
    yaml_path = repo_root / "data" / "match" / "region_groups.yaml"
    if not yaml_path.is_file():
        _log.debug(
            "region_groups.yaml not found at %s — using hardcoded baseline",
            yaml_path,
        )
        return {}

    try:
        with yaml_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:  # type: ignore[attr-defined]
        _log.warning(
            "region_groups.yaml at %s could not be parsed (%s) — using hardcoded baseline",
            yaml_path,
            exc,
        )
        return {}

    if not isinstance(raw, dict):
        _log.warning(
            "region_groups.yaml at %s top-level is not a mapping — using hardcoded baseline",
            yaml_path,
        )
        return {}

    groups = raw.get("groups")
    if not isinstance(groups, dict):
        _log.warning(
            "region_groups.yaml at %s has no ``groups`` mapping — using hardcoded baseline",
            yaml_path,
        )
        return {}

    parsed: dict[str, tuple[str, ...]] = {}
    for name, codes in groups.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(codes, (list, tuple)):
            _log.warning(
                "region_groups.yaml group %r value is not a list — skipped",
                name,
            )
            continue
        prefixes = tuple(p for p in (_normalise_prefix(c) for c in codes) if p)
        if not prefixes:
            continue
        parsed[name.strip().lower()] = prefixes
    return parsed


def _merge_region_groups() -> dict[str, tuple[str, ...]]:
    """Combine hardcoded baseline with YAML extension (YAML wins on key clash)."""
    merged: dict[str, tuple[str, ...]] = dict(_HARDCODED_REGION_GROUPS)
    overlay = _load_region_groups_from_yaml()
    if overlay:
        merged.update(overlay)
    return merged


_REGION_GROUP_ALIASES: dict[str, tuple[str, ...]] = _merge_region_groups()


def _build_country_prefix_table() -> dict[str, tuple[str, ...]]:
    """Auto-derive ``{iso_lower: (PREFIX_,)}`` from REGION_LANGUAGE keys.

    Every distinct head before the first underscore in REGION_LANGUAGE
    becomes its own one-prefix entry. Aliases in ``_BARE_COUNTRY_OVERRIDES``
    that don't appear in REGION_LANGUAGE (e.g. ``CZ`` whose key is
    ``CZ_PRAGUE``) still get covered because both heads route through
    the same iteration.
    """
    from app.core.match_service.region_language import (
        _BARE_COUNTRY_OVERRIDES,
        REGION_LANGUAGE,
    )

    out: dict[str, tuple[str, ...]] = {}
    for key in REGION_LANGUAGE:
        head = key.split("_", 1)[0]
        if head and head.lower() not in out:
            out[head.lower()] = (f"{head}_",)
    for head in _BARE_COUNTRY_OVERRIDES:
        if head.lower() not in out:
            out[head.lower()] = (f"{head}_",)
    return out


_AUTO_COUNTRY_PREFIXES: dict[str, tuple[str, ...]] = _build_country_prefix_table()


def _project_region_prefixes(settings: Any) -> tuple[str, ...]:
    """‌⁠‍Resolve the region-prefix tuple from project / match settings.

    The project's ``region`` field (``"DACH"`` / ``"UK"`` / ``"DE_BERLIN"``)
    is the primary signal; we fold it lowercase and look up the prefix
    table. If the region is already a CWICR ``COUNTRY_CITY`` code we
    return it as-is so a project pinned to ``DE_BERLIN`` only matches
    Berlin-priced rows (no Munich crossover).
    """
    project = getattr(settings, "project", None)
    region_raw: str = ""
    if project is not None:
        region_raw = str(getattr(project, "region", "") or "")
    if not region_raw:
        # ``settings`` itself sometimes carries the region (test stubs).
        region_raw = str(getattr(settings, "region", "") or "")
    if not region_raw:
        return ()

    region = region_raw.strip()
    if "_" in region:
        # Already a fully-qualified CWICR region code (e.g. "DE_BERLIN").
        # Return the *exact* code — a candidate with the same code will
        # match via ``startswith()``. Appending an extra underscore
        # would break the equality case (``"DE_BERLIN".startswith("DE_BERLIN_")``
        # is False). Tuple-form is mandatory — a bare string would be
        # iterated character-by-character downstream.
        upper = region.upper().rstrip("_")
        return (upper,)

    key = region.lower()
    # Group aliases (DACH, UK, Benelux, …) win over single-country
    # prefixes — operators picking "Iberia" expect ES+PT, not just one.
    if key in _REGION_GROUP_ALIASES:
        return _REGION_GROUP_ALIASES[key]
    return _AUTO_COUNTRY_PREFIXES.get(key, ())


def boost(
    envelope: ElementEnvelope,  # noqa: ARG001 — interface symmetry
    candidate: MatchCandidate,
    settings: Any,
) -> dict[str, float]:
    """‌⁠‍Add region-match boost when the candidate's region matches."""
    cand_region = (candidate.region_code or "").strip().upper()
    if not cand_region:
        return {}

    prefixes = _project_region_prefixes(settings)
    if not prefixes:
        return {}

    for prefix in prefixes:
        if cand_region.startswith(prefix.upper()):
            return {"region_match": BOOST_WEIGHTS.region_match}

    return {}
