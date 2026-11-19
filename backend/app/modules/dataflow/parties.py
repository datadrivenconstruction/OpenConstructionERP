# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The people, companies and organisations working on one project's data.

Read from records the project already has: the owner and team members, the
site roster, the client contact, contract parties, subcontract agreements,
tender bidders and purchase-order suppliers. Each party lands in one of three
zones and carries the modules it creates or consumes, so hovering a party can
light up its paths. No photos: initials and monograms only.

Every source is optional: a module that is not installed contributes nothing,
and one failing query never fails the response.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CLIENT, DELIVERY, SPECIALIST = "client", "delivery", "specialist"

# Role vocabulary used by DataPaths.roles; each role belongs to one zone.
ROLE_ZONES: dict[str, str] = {
    "client": CLIENT,
    "owner": CLIENT,
    "project_manager": DELIVERY,
    "estimator": DELIVERY,
    "buyer": DELIVERY,
    "site_manager": DELIVERY,
    "planner": DELIVERY,
    "quantity_surveyor": DELIVERY,
    "accountant": DELIVERY,
    "contractor": DELIVERY,
    "subcontractor": DELIVERY,
    "supplier": DELIVERY,
    "bidder": DELIVERY,
    "engineer": SPECIALIST,
    "architect": SPECIALIST,
    "inspector": SPECIALIST,
    "surveyor": SPECIALIST,
    "consultant": SPECIALIST,
    "authority": SPECIALIST,
}

# Shown when the project has no parties yet: the picture still teaches who does what.
PLACEHOLDER_ROLES: tuple[str, ...] = (
    "client",
    "estimator",
    "buyer",
    "site_manager",
    "subcontractor",
    "supplier",
    "engineer",
    "inspector",
)

_SPECIALIST_WORDS = ("engineer", "architect", "consult", "surveyor", "inspector", "authority", "designer")
_CLIENT_WORDS = ("client", "employer", "owner", "customer", "buyer_party")

MAX_PARTIES = 60


@dataclass
class Party:
    """One hex: a person, a company or an organisation."""

    id: str
    kind: str  # person | company | organisation | role
    name: str
    zone: str
    roles: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    placeholder: bool = False

    @property
    def initials(self) -> str:
        words = [w for w in self.name.replace("-", " ").split() if w[:1].isalnum()]
        if not words:
            return "?"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[1][0]).upper()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "initials": self.initials,
            "zone": self.zone,
            "roles": self.roles,
            "modules": sorted(set(self.modules)),
            "placeholder": self.placeholder,
        }


def zone_for_text(text: str | None, default: str = DELIVERY) -> str:
    """Zone from a free-text role such as ``ContractParty.party_role``."""
    low = (text or "").lower()
    if any(w in low for w in _CLIENT_WORDS):
        return CLIENT
    if any(w in low for w in _SPECIALIST_WORDS):
        return SPECIALIST
    return default


def role_modules(manifests: dict[str, Any]) -> dict[str, list[str]]:
    """Role -> modules whose declaration names that role."""
    out: dict[str, list[str]] = {}
    for name, manifest in manifests.items():
        decl = getattr(manifest, "data_paths", None)
        for role in getattr(decl, "roles", ()) or ():
            out.setdefault(role, []).append(name)
    return out


def placeholders(manifests: dict[str, Any]) -> list[Party]:
    by_role = role_modules(manifests)
    return [
        Party(
            id=f"role:{r}",
            kind="role",
            name=r,
            zone=ROLE_ZONES[r],
            roles=[r],
            modules=by_role.get(r, []),
            placeholder=True,
        )
        for r in PLACEHOLDER_ROLES
    ]


class _Collector:
    def __init__(self, manifests: dict[str, Any]) -> None:
        self.by_role = role_modules(manifests)
        self.parties: dict[str, Party] = {}

    def add(self, key: str, kind: str, name: str | None, zone: str, role: str | None, module: str | None) -> None:
        name = (name or "").strip()
        if not name or len(self.parties) >= MAX_PARTIES and key not in self.parties:
            return
        party = self.parties.setdefault(key, Party(id=key, kind=kind, name=name[:80], zone=zone))
        if role and role not in party.roles:
            party.roles.append(role)
            party.modules.extend(self.by_role.get(role, []))
        if module:
            party.modules.append(module)


async def _rows(session: AsyncSession, stmt: Any) -> list[Any]:
    try:
        async with session.begin_nested():
            return list((await session.execute(stmt.limit(MAX_PARTIES))).all())
    except Exception as exc:
        logger.info("dataflow: party source unavailable: %s", type(exc).__name__)
        return []


def _contact_name(contact: Any) -> str:
    company = getattr(contact, "company_name", None) or getattr(contact, "legal_name", None)
    if company:
        return company
    return " ".join(x for x in (getattr(contact, "first_name", None), getattr(contact, "last_name", None)) if x)


async def collect_parties(
    session: AsyncSession, project_id: uuid.UUID, manifests: dict[str, Any], loaded: frozenset[str]
) -> list[dict[str, Any]]:
    """Real parties of one project; placeholders when there are none. Caller checks access first."""
    col = _Collector(manifests)
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    project = await session.get(Project, project_id)
    if project is None:
        return []
    owner = await session.get(User, project.owner_id) if project.owner_id else None
    if owner is not None:
        col.add(
            f"user:{owner.id}", "person", owner.full_name or owner.email, DELIVERY, "project_manager", "oe_projects"
        )

    if "oe_teams" in loaded:
        from app.modules.teams.models import RosterMember, Team, TeamMembership

        stmt = (
            select(User.id, User.full_name, User.email, TeamMembership.role)
            .join(TeamMembership, TeamMembership.user_id == User.id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(Team.project_id == project_id)
        )
        for uid, full_name, email, role in await _rows(session, stmt):
            mapped = role if role in ROLE_ZONES else None
            col.add(f"user:{uid}", "person", full_name or email, ROLE_ZONES.get(role, DELIVERY), mapped, "oe_teams")
        stmt = select(RosterMember).where(RosterMember.project_id == project_id, RosterMember.is_active.is_(True))
        for (member,) in await _rows(session, stmt):
            key = f"user:{member.user_id}" if member.user_id else f"roster:{member.id}"
            zone = zone_for_text(member.site_role)
            col.add(key, "person", member.display_name, zone, "site_manager" if zone == DELIVERY else None, "oe_teams")

    if "oe_contacts" in loaded:
        from app.modules.contacts.models import Contact

        if getattr(project, "client_id", None):
            try:
                client = await session.get(Contact, uuid.UUID(str(project.client_id)))
            except (ValueError, TypeError):
                client = None
            if client is not None:
                kind = "organisation" if (client.party_kind or "") in ("authority", "public_body") else "company"
                col.add(f"contact:{client.id}", kind, _contact_name(client), CLIENT, "client", "oe_projects")
        if "oe_procurement" in loaded:
            from app.modules.procurement.models import PurchaseOrder

            stmt = (
                select(Contact)
                .join(PurchaseOrder, PurchaseOrder.vendor_contact_id == Contact.id)
                .where(PurchaseOrder.project_id == project_id)
                .distinct()
            )
            for (contact,) in await _rows(session, stmt):
                col.add(
                    f"contact:{contact.id}", "company", _contact_name(contact), DELIVERY, "supplier", "oe_procurement"
                )

    if "oe_contracts" in loaded:
        from app.modules.contracts.models import Contract, ContractParty

        stmt = (
            select(
                ContractParty.party_id, ContractParty.display_name, ContractParty.party_role, ContractParty.party_type
            )
            .join(Contract, Contract.id == ContractParty.contract_id)
            .where(Contract.project_id == project_id)
        )
        for party_id, display_name, party_role, party_type in await _rows(session, stmt):
            zone = zone_for_text(party_role)
            role = "client" if zone == CLIENT else ("consultant" if zone == SPECIALIST else "contractor")
            kind = "person" if (party_type or "") in ("user", "person") else "company"
            key = f"contact:{party_id}" if party_id else f"party:{display_name}"
            col.add(key, kind, display_name, zone, role, "oe_contracts")

    if "oe_subcontractors" in loaded:
        from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor

        stmt = (
            select(Subcontractor.id, Subcontractor.contact_id, Subcontractor.legal_name, Subcontractor.trade_name)
            .join(SubcontractAgreement, SubcontractAgreement.subcontractor_id == Subcontractor.id)
            .where(SubcontractAgreement.project_id == project_id)
            .distinct()
        )
        for sid, contact_id, legal, trade in await _rows(session, stmt):
            key = f"contact:{contact_id}" if contact_id else f"sub:{sid}"
            col.add(key, "company", trade or legal, DELIVERY, "subcontractor", "oe_subcontractors")

    if "oe_tendering" in loaded:
        from app.modules.tendering.models import TenderBid, TenderPackage

        stmt = (
            select(TenderBid.contact_id, TenderBid.company_name)
            .join(TenderPackage, TenderPackage.id == TenderBid.package_id)
            .where(TenderPackage.project_id == project_id)
            .distinct()
        )
        for contact_id, company in await _rows(session, stmt):
            key = f"contact:{contact_id}" if contact_id else f"bidder:{(company or '').strip().lower()}"
            col.add(key, "company", company, DELIVERY, "bidder", "oe_tendering")

    parties = list(col.parties.values())
    if not parties:
        parties = placeholders(manifests)
    return [p.as_dict() for p in parties]
