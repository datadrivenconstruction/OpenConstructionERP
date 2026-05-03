# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Region boost — rewards candidates from the project's region.

CWICR ships one regional file per market (``DE_BERLIN``, ``GB_LONDON``,
``USA_NEWYORK``, ...). When the project says "DACH" the matcher should
prefer DACH-priced candidates even if a UK candidate has marginally
higher cosine similarity — the unit rate in the wrong region is a
useless number.

This boost is deliberately small (5 %) because regional preference
should bias ties, not override clear semantic mismatches.
"""

from __future__ import annotations

from typing import Any

from app.core.match_service.config import BOOST_WEIGHTS
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

# Map project region keywords to the country-prefix glob the candidate's
# ``region_code`` should start with. Permits matching at the broadest
# useful granularity — "DACH" matches DE/AT/CH, "UK" matches GB/IE.
_REGION_PREFIXES: dict[str, tuple[str, ...]] = {
    "dach": ("DE_", "AT_", "CH_"),
    "de": ("DE_",),
    "at": ("AT_",),
    "ch": ("CH_",),
    "uk": ("GB_", "IE_"),
    "gb": ("GB_",),
    "us": ("USA_", "US_"),
    "usa": ("USA_", "US_"),
    "fr": ("FR_",),
    "es": ("ES_",),
    "it": ("IT_",),
    "pt": ("PT_", "BR_"),
    "ru": ("RU_",),
    "pl": ("PL_",),
    "cz": ("CZ_",),
    "ro": ("RO_",),
    "bg": ("BG_",),
    "lt": ("LT_",),
    "nl": ("NL_", "BE_"),
    "be": ("BE_", "NL_"),
    "tr": ("TR_",),
    "ae": ("AE_", "SA_"),
    "cn": ("CN_",),
    "jp": ("JP_",),
    "in": ("IN_",),
    "mx": ("MX_",),
    "ar": ("AR_",),
    "br": ("BR_",),
    "au": ("AU_",),
    "nz": ("NZ_",),
    "za": ("ZA_",),
    "ca": ("CA_",),
}


def _project_region_prefixes(settings: Any) -> tuple[str, ...]:
    """Resolve the region-prefix tuple from project / match settings.

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

    return _REGION_PREFIXES.get(region.lower(), ())


def boost(
    envelope: ElementEnvelope,  # noqa: ARG001 — interface symmetry
    candidate: MatchCandidate,
    settings: Any,
) -> dict[str, float]:
    """Add region-match boost when the candidate's region matches."""
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
