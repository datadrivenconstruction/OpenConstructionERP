# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Point Cloud validation helpers.

Phase 0 ships the accuracy-tier helpers used at register time: the USIBD Level
of Accuracy (LOA) tolerance table, the tier-allow-list check, and the upload
format gate that rejects proprietary ReCap containers with an explanatory
reason.

The full point-cloud validation RULE SET (BLOCKING coverage / registration-RMS
/ tier / occlusion checks registered with ``core/validation/rules``) lands in a
later phase together with its 26-locale i18n keys. Keeping the deterministic
helpers here now lets the service give honest, explanatory errors at register
time without pulling in the rule engine before its rules exist.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.pointcloud.models import (
    ACCEPTED_SCAN_FORMATS,
    REJECTED_SCAN_FORMATS,
)

# USIBD Level of Accuracy - upper tolerance bound per tier, in millimetres.
# A registration RMS at or below this bound is within tier; above it, the
# later-phase validation rule blocks dimensional QA and cut/fill price feed.
LOA_TOLERANCE_MM: dict[str, Decimal] = {
    "survey": Decimal("6"),  # LOA30-40, plus/minus 3-6 mm (TLS)
    "standard": Decimal("15"),  # LOA20, plus/minus 15 mm (MLS / SLAM / drone)
    "coarse": Decimal("50"),  # LOA10, plus/minus 50 mm (iPhone / iPad LiDAR)
}

# Tiers forbidden from feeding cut/fill into BOQ price or dimensional QA without
# an explicit human override (plan decision #2).
DIMENSIONAL_QA_FORBIDDEN_TIERS: frozenset[str] = frozenset({"coarse"})


def normalize_format(raw: str | None) -> str:
    """Lower-case, strip a leading dot and surrounding whitespace from a format.

    ``".LAS"`` -> ``"las"``; ``" E57 "`` -> ``"e57"``; ``None`` -> ``""``.
    """
    if not raw:
        return ""
    return raw.strip().lower().lstrip(".")


def is_accepted_format(raw: str | None) -> bool:
    """Return True when ``raw`` is an accepted point-cloud upload format."""
    return normalize_format(raw) in ACCEPTED_SCAN_FORMATS


def format_rejection_reason(raw: str | None) -> str | None:
    """Return a machine-readable rejection reason code, or ``None`` if accepted.

    The reason is a stable code the API / UI can translate (i18n), not prose:

    * ``"format_proprietary_recap"`` - ReCap RCP/RCS, never accepted.
    * ``"format_unsupported"``        - anything else not in the allow-list.
    """
    fmt = normalize_format(raw)
    if fmt in ACCEPTED_SCAN_FORMATS:
        return None
    if fmt in REJECTED_SCAN_FORMATS:
        return "format_proprietary_recap"
    return "format_unsupported"


def is_valid_tier(tier: str | None) -> bool:
    """Return True when ``tier`` is a known USIBD LOA tier."""
    return tier in LOA_TOLERANCE_MM


def tier_tolerance_mm(tier: str | None) -> Decimal | None:
    """Return the LOA tolerance bound in millimetres for ``tier``, or ``None``."""
    if tier is None:
        return None
    return LOA_TOLERANCE_MM.get(tier)


def rms_within_tier(rms_mm: Decimal | float | None, tier: str | None) -> bool | None:
    """Return whether a registration RMS is within its tier's LOA tolerance.

    Returns ``None`` when the RMS or the tier is unknown (not yet measured), so
    a caller can distinguish "not measured" from "measured and failing" instead
    of treating a missing value as a pass.
    """
    bound = tier_tolerance_mm(tier)
    if bound is None or rms_mm is None:
        return None
    value = rms_mm if isinstance(rms_mm, Decimal) else Decimal(str(rms_mm))
    return value <= bound


def tier_allows_dimensional_qa(tier: str | None) -> bool:
    """Return whether ``tier`` may drive dimensional QA / cut-fill price feed."""
    return tier not in DIMENSIONAL_QA_FORBIDDEN_TIERS


__all__ = [
    "DIMENSIONAL_QA_FORBIDDEN_TIERS",
    "LOA_TOLERANCE_MM",
    "format_rejection_reason",
    "is_accepted_format",
    "is_valid_tier",
    "normalize_format",
    "rms_within_tier",
    "tier_allows_dimensional_qa",
    "tier_tolerance_mm",
]
