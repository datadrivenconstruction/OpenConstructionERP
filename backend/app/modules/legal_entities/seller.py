# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who sells: the one resolver every document asks for its seller block.

The chain, first answer wins:

1. the project names an entity and that entity has its own e-invoice settings
   (``EInvoiceSettings(scope="entity:<id>")``): those settings;
2. the project names an entity without its own settings: the entity's own
   identity (legal name, address, tax ids), with the group's default settings
   for everything that is not identity (bank account, payment terms, contact);
3. the project names no entity: the default settings (``scope="default"``),
   exactly as before entities existed;
4. nothing configured: the company profile (the letterhead), for display only.

A project that names no entity is never re-dressed in the default entity's
identity, so on an install that has not started using entities every invoice
and PDF stays what it was.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.legal_entities.models import LegalEntity
from app.modules.legal_entities.tax_ids import value_of
from app.modules.legal_entities.validators import missing_seller_fields

Source = Literal["entity_settings", "entity", "default", "company_profile", "none"]

#: Seller fields that say who the company is; an entity never inherits these from the group.
IDENTITY_FIELDS = (
    "name",
    "vat_id",
    "tax_number",
    "legal_id",
    "tax_office",
    "country_code",
    "line1",
    "postcode",
    "city",
    "electronic_address",
    "electronic_address_scheme",
)


def entity_scope(entity_id: uuid.UUID | str) -> str:
    """The e-invoice settings scope of one entity."""
    return f"entity:{entity_id}"


@dataclass
class SellerResolution:
    """The resolved seller for one project and where it came from."""

    source: Source
    defaults: dict[str, Any] = field(default_factory=dict)
    entity: LegalEntity | None = None
    assigned: bool = False

    @property
    def seller(self) -> dict[str, Any]:
        return dict(self.defaults.get("seller") or {})

    @property
    def country_code(self) -> str | None:
        if self.entity is not None:
            return self.entity.country_code
        return self.seller.get("country_code") or None

    @property
    def missing(self) -> list[str]:
        return missing_seller_fields(self.seller, self.country_code)


def entity_identity(entity: LegalEntity) -> dict[str, str]:
    """The seller identity an entity carries itself, blanks dropped."""
    address = entity.address or {}
    tax_ids = entity.tax_ids or []
    vat = value_of(tax_ids, "vat")
    if not vat and entity.tax_id and not tax_ids:
        vat = entity.tax_id
    line1 = ", ".join(p for p in (address.get("line1"), address.get("line2")) if p)
    fields = {
        "name": entity.legal_name or entity.name,
        "vat_id": vat,
        "tax_number": value_of(tax_ids, "tax_number") or value_of(tax_ids, "ein") or value_of(tax_ids, "bn"),
        "legal_id": entity.registration_number or value_of(tax_ids, "company_reg"),
        "country_code": entity.country_code,
        "line1": line1,
        "postcode": address.get("postcode") or "",
        "city": address.get("city") or "",
    }
    return {k: str(v).strip() for k, v in fields.items() if v and str(v).strip()}


async def _settings_defaults(session: AsyncSession, scope: str) -> dict[str, Any] | None:
    from app.modules.finance.einvoice_settings_models import EInvoiceSettings

    row = (await session.execute(select(EInvoiceSettings).where(EInvoiceSettings.scope == scope))).scalar_one_or_none()
    return row.as_defaults() if row is not None else None


def _company_profile_seller() -> dict[str, str]:
    try:
        from app.core.company_profile import read_company_profile

        profile = read_company_profile()
    except Exception:  # noqa: BLE001 - the letterhead is a display fallback, never a reason to fail
        return {}
    lines = [ln.strip() for ln in str(profile.get("address") or "").splitlines() if ln.strip()]
    seller = {"name": str(profile.get("legal_name") or "").strip(), "line1": lines[0] if lines else ""}
    if len(lines) > 1:
        seller["city"] = lines[1]
    return {k: v for k, v in seller.items() if v}


async def resolve_seller(
    session: AsyncSession, project_id: uuid.UUID | None, *, with_profile_fallback: bool = False
) -> SellerResolution:
    """Resolve the seller for a document of *project_id*.

    Args:
        session: An open session.
        project_id: The project the document belongs to, or None for a document of no project.
        with_profile_fallback: Fall back to the letterhead when nothing else answers. For the
            seller block shown on screen; e-invoice export leaves it off, as it always has.
    """
    entity: LegalEntity | None = None
    if project_id is not None:
        from app.modules.projects.models import Project

        project = await session.get(Project, project_id)
        if project is not None and project.legal_entity_id is not None:
            entity = await session.get(LegalEntity, project.legal_entity_id)

    if entity is not None:
        own = await _settings_defaults(session, entity_scope(entity.id))
        if own:
            return SellerResolution("entity_settings", own, entity, assigned=True)
        group = await _settings_defaults(session, "default") or {}
        seller = {k: v for k, v in (group.get("seller") or {}).items() if k not in IDENTITY_FIELDS}
        seller.update(entity_identity(entity))
        return SellerResolution("entity", {**group, "seller": seller}, entity, assigned=True)

    default = await _settings_defaults(session, "default")
    if default:
        return SellerResolution("default", default)
    if with_profile_fallback:
        seller = _company_profile_seller()
        if seller:
            return SellerResolution("company_profile", {"seller": seller})
    return SellerResolution("none", {})
