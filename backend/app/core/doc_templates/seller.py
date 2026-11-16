# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who a document is from: the one place generators read seller details.

Today the only source is the workspace company profile
(:mod:`app.core.company_profile`). When per-entity letterheads arrive, this is
the function that changes: callers already pass the optional ``entity_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["Seller", "resolve_seller"]


@dataclass(frozen=True)
class Seller:
    """Seller details printed on a document. Empty strings mean "not set"."""

    legal_name: str = ""
    address: str = ""
    registration_line: str = ""
    vat_id: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""
    logo_data_url: str = ""
    country: str = ""

    def as_fields(self) -> dict[str, str]:
        """Merge values under the ``entity.*`` paths."""
        return {
            "entity.legal_name": self.legal_name,
            "entity.address": self.address.replace("\n", ", "),
            "entity.registration_line": self.registration_line,
            "entity.vat_id": self.vat_id,
            "entity.email": self.email,
            "entity.phone": self.phone,
            "entity.website": self.website,
        }


def resolve_seller(entity_id: Any = None, *, country: str | None = None) -> Seller:
    """Seller details for a document. Never raises.

    Args:
        entity_id: Reserved for legal entities; ignored until they ship.
        country: The seller's country (ISO alpha-2) when the caller knows it,
            e.g. the market profile's primary market.
    """
    del entity_id
    try:
        from app.core.company_profile import read_company_profile

        profile: dict[str, Any] = read_company_profile()
    except Exception:  # noqa: BLE001 - a document never fails on a missing profile
        profile = {}

    def _get(key: str) -> str:
        value = profile.get(key)
        return value.strip() if isinstance(value, str) else ""

    return Seller(
        legal_name=_get("legal_name"),
        address=_get("address"),
        registration_line=_get("registration_line"),
        vat_id=_get("vat_id"),
        email=_get("email"),
        phone=_get("phone"),
        website=_get("website"),
        logo_data_url=_get("document_logo_png_data_url") or _get("document_logo_data_url"),
        country=(country or "").strip().upper()[:2],
    )
