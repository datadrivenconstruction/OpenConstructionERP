# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo group of companies: a German group and a US group, with their sites.

Runs only on a demo install that has no legal entity yet, so a group someone
set up by hand is never touched, and a re-run is a no-op. Every tax id here is
synthetic.

German showcase: Muster Hochbau GmbH (HB, the default) with sites Berlin and
Leipzig, and Muster Tiefbau GmbH (TB). US showcase: Ridgeline Builders Inc.
(RB) and Ridgeline Civil LLC (RC) with its Austin site. German demo projects
go to HB (the Frankfurt office to TB), the Texas project to RC at Austin, the
other US projects to RB. Projects of other countries name no company and fall
back to the default, as on any install.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.legal_entities.models import Branch, LegalEntity

_GROUP: list[dict[str, Any]] = [
    {
        "code": "HB",
        "name": "Muster Hochbau",
        "legal_name": "Muster Hochbau GmbH",
        "country_code": "DE",
        "functional_currency": "EUR",
        "address": {"line1": "Musterstraße 1", "postcode": "10115", "city": "Berlin"},
        "tax_ids": [{"scheme": "vat", "value": "DE123456789"}, {"scheme": "tax_number", "value": "30/123/45678"}],
        "invoice_prefix": "R-HB-",
        "is_default": True,
        "sites": [("HB-BER", "Berlin"), ("HB-LEI", "Leipzig")],
    },
    {
        "code": "TB",
        "name": "Muster Tiefbau",
        "legal_name": "Muster Tiefbau GmbH",
        "country_code": "DE",
        "functional_currency": "EUR",
        "address": {"line1": "Musterweg 7", "postcode": "04109", "city": "Leipzig"},
        "tax_ids": [{"scheme": "vat", "value": "DE987654321"}],
        "invoice_prefix": "R-TB-",
        "sites": [],
    },
    {
        "code": "RB",
        "name": "Ridgeline Builders",
        "legal_name": "Ridgeline Builders Inc.",
        "country_code": "US",
        "subdivision_code": "US-TX",
        "functional_currency": "USD",
        "address": {"line1": "100 Example Ave", "postcode": "75201", "city": "Dallas"},
        "tax_ids": [{"scheme": "ein", "value": "12-3456789"}],
        "invoice_prefix": "RB-",
        "sites": [],
    },
    {
        "code": "RC",
        "name": "Ridgeline Civil",
        "legal_name": "Ridgeline Civil LLC",
        "country_code": "US",
        "subdivision_code": "US-TX",
        "functional_currency": "USD",
        "address": {"line1": "200 Sample Rd", "postcode": "78701", "city": "Austin"},
        "tax_ids": [{"scheme": "ein", "value": "98-7654321"}],
        "invoice_prefix": "RC-",
        "sites": [("RC-AUS", "Austin TX")],
    },
]

#: demo_id -> (entity code, site code or None). Other projects go by country below.
_PLACED: dict[str, tuple[str, str | None]] = {
    "residential-berlin": ("HB", "HB-BER"),
    "office-frankfurt": ("TB", None),
    "medical-us": ("RC", "RC-AUS"),
}
_BY_COUNTRY = {"DE": "HB", "US": "RB"}


async def seed_legal_entities_demo(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[str, int]:
    """Create the demo group and place the demo projects in it. Idempotent."""
    from app.modules.projects.models import Project

    if not project_ids:
        return {}
    if (await session.scalar(select(func.count()).select_from(LegalEntity))) or 0:
        return {}

    entities: dict[str, LegalEntity] = {}
    sites: dict[str, Branch] = {}
    for row in _GROUP:
        entity = LegalEntity(
            code=row["code"],
            name=row["name"],
            legal_name=row["legal_name"],
            country_code=row["country_code"],
            subdivision_code=row.get("subdivision_code"),
            functional_currency=row["functional_currency"],
            address=row["address"],
            tax_ids=row["tax_ids"],
            invoice_prefix=row["invoice_prefix"],
            is_default=bool(row.get("is_default")),
            is_active=True,
            metadata_={"demo": True},
        )
        session.add(entity)
        await session.flush()
        entities[entity.code] = entity
        for code, name in row["sites"]:
            site = Branch(legal_entity_id=entity.id, code=code, name=name, country_code=row["country_code"])
            session.add(site)
            sites[code] = site
    await session.flush()

    placed = 0
    projects = (await session.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()
    for project in projects:
        demo_id = str((project.metadata_ or {}).get("demo_id") or "")
        entity_code, site_code = _PLACED.get(demo_id, (_BY_COUNTRY.get(project.country_code or ""), None))
        if entity_code is None:
            continue
        project.legal_entity_id = entities[entity_code].id
        project.legal_entity_branch_id = sites[site_code].id if site_code else None
        placed += 1
    await session.flush()
    return {"entities": len(entities), "sites": len(sites), "projects": placed}
