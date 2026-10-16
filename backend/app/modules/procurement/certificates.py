# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The catalogue of material certificate types, read from data.

A purchase order line may require the material to arrive with an inspection
document, for example an EN 10204 type 3.1 certificate for reinforcing steel.
Which documents exist differs by material, by client and by country, so the
types are data in ``catalogues/*.json`` and never a list in code. Every JSON
file in that folder is read; a later file (by name) replaces a type of the same
code, which is how a country or company pack adds or narrows types without a
schema change.

A delivered type *satisfies* a required one when both are of the same family and
the delivered rank is the same or higher. EN 10204 orders its types that way: a
3.1 certificate states everything a 2.2 test report does plus specific
inspection, so an order asking for 2.2 is covered by 3.1.

Standard library only, so the validation rules can use it without the ORM.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

CATALOGUE_DIR = Path(__file__).resolve().parent / "catalogues"


@dataclass(frozen=True)
class CertificateType:
    """One kind of inspection document a delivery can carry."""

    code: str
    family: str
    rank: int
    label: str
    standard: str = ""
    designation: str = ""
    specific_inspection: bool = False
    validated_by: str = ""

    def as_dict(self) -> dict[str, object]:
        """The type as the API returns it."""
        return {
            "code": self.code,
            "family": self.family,
            "rank": self.rank,
            "label": self.label,
            "standard": self.standard,
            "designation": self.designation,
            "specific_inspection": self.specific_inspection,
            "validated_by": self.validated_by,
        }


def _read_file(path: Path) -> list[CertificateType]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Certificate type catalogue %s could not be read", path.name, exc_info=True)
        return []
    out: list[CertificateType] = []
    for raw in data.get("types", []) if isinstance(data, dict) else []:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip()
        family = str(raw.get("family") or "").strip()
        if not code or not family or len(code) > 40:
            logger.warning("Certificate type without a usable code or family skipped in %s", path.name)
            continue
        try:
            rank = int(raw.get("rank", 1))
        except (TypeError, ValueError):
            rank = 1
        out.append(
            CertificateType(
                code=code,
                family=family,
                rank=rank,
                label=str(raw.get("label") or code),
                standard=str(raw.get("standard") or ""),
                designation=str(raw.get("designation") or ""),
                specific_inspection=bool(raw.get("specific_inspection", False)),
                validated_by=str(raw.get("validated_by") or ""),
            )
        )
    return out


@lru_cache(maxsize=1)
def _catalogue() -> dict[str, CertificateType]:
    types: dict[str, CertificateType] = {}
    for path in sorted(CATALOGUE_DIR.glob("*.json")):
        for ctype in _read_file(path):
            types[ctype.code] = ctype
    return types


def certificate_types() -> list[CertificateType]:
    """Every known certificate type, by family and rank."""
    return sorted(_catalogue().values(), key=lambda t: (t.family, t.rank, t.code))


def get_certificate_type(code: str | None) -> CertificateType | None:
    """The type with ``code``, or ``None`` when the catalogue does not know it."""
    if not code:
        return None
    return _catalogue().get(str(code).strip())


def is_known_type(code: str | None) -> bool:
    """True when ``code`` names a catalogue type."""
    return get_certificate_type(code) is not None


def satisfies(delivered: str | None, required: str | None) -> bool:
    """Whether a delivered certificate type covers a required one.

    Same code always satisfies. Otherwise both must be catalogue types of one
    family and the delivered rank must be the same or higher. An unknown
    required code is only satisfied by the identical code, so a requirement the
    catalogue lost is never waved through by a guess.
    """
    if not delivered or not required:
        return False
    if delivered == required:
        return True
    have = get_certificate_type(delivered)
    want = get_certificate_type(required)
    if have is None or want is None:
        return False
    return have.family == want.family and have.rank >= want.rank


def reload_catalogue() -> None:
    """Forget the cached catalogue so the next read sees files added since (tests, packs)."""
    _catalogue.cache_clear()


__all__ = [
    "CATALOGUE_DIR",
    "CertificateType",
    "certificate_types",
    "get_certificate_type",
    "is_known_type",
    "reload_catalogue",
    "satisfies",
]
