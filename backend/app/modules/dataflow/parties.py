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
MAX_ROWS = 500

# Colour of a hex: the strongest role a party holds, in this order.
ROLE_CATEGORY_ORDER: tuple[str, ...] = ("client", "contractor", "subcontractor", "supplier", "bidder", "consultant")
_ROLE_CATEGORY: dict[str, str] = {
    "client": "client",
    "owner": "client",
    "contractor": "contractor",
    "subcontractor": "subcontractor",
    "supplier": "supplier",
    "bidder": "bidder",
    "engineer": "consultant",
    "architect": "consultant",
    "inspector": "consultant",
    "surveyor": "consultant",
    "consultant": "consultant",
    "authority": "consultant",
}
# Legal-form words that do not tell two companies apart.
_LEGAL_WORDS = frozenset(
    [
        "gmbh",
        "mbh",
        "co",
        "kg",
        "ag",
        "ug",
        "ltd",
        "llc",
        "inc",
        "sa",
        "sarl",
        "srl",
        "spa",
        "bv",
        "nv",
        "plc",
        "oy",
        "ab",
        "as",
        "kft",
        "sp",
        "zoo",
        "pty",
        "corp",
        "company",
        "und",
        "and",
    ]
)


def org_key(name: str) -> str:
    """Name a company is merged under: case, punctuation and legal form ignored."""
    cleaned = "".join(ch if ch.isalnum() else " " for ch in name.casefold())
    words = [w for w in cleaned.split() if w not in _LEGAL_WORDS]
    return " ".join(words) or cleaned.strip()


def monogram(name: str, letters: int) -> str:
    """Two or three letter monogram from the distinctive words of a name."""
    cleaned = "".join(ch if ch.isalnum() else " " for ch in name)
    words = [w for w in cleaned.split() if w.casefold() not in _LEGAL_WORDS] or cleaned.split()
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:letters].upper()
    if letters == 2:
        return (words[0][0] + words[1][0]).upper()
    if len(words) == 2:
        return (words[0][:2] + words[1][0]).upper()
    return "".join(w[0] for w in words[:3]).upper()


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
    touches: dict[str, int] = field(default_factory=dict)
    org: str | None = None
    initials: str = ""

    @property
    def primary_role(self) -> str:
        if self.kind == "person":
            return "person"
        cats = {_ROLE_CATEGORY.get(r, "") for r in self.roles}
        return next((c for c in ROLE_CATEGORY_ORDER if c in cats), "contractor")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "initials": self.initials or monogram(self.name, 2),
            "zone": self.zone,
            "roles": self.roles,
            "modules": sorted(set(self.modules)),
            "placeholder": self.placeholder,
            "primary_role": "" if self.placeholder else self.primary_role,
            "touches": dict(sorted(self.touches.items())),
            "org": self.org,
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
        # One hex per organisation: the same company reached through a contact,
        # a subcontract and a bid lands on the first key it was seen under.
        self.by_name: dict[str, str] = {}
        self.person_org: dict[str, str] = {}

    def add(
        self,
        key: str,
        kind: str,
        name: str | None,
        zone: str,
        role: str | None,
        module: str | None,
        org_name: str | None = None,
    ) -> None:
        name = (name or "").strip()
        if not name:
            return
        if kind != "person" and key not in self.parties:
            key = self.by_name.get(org_key(name), key)
        if len(self.parties) >= MAX_PARTIES and key not in self.parties:
            return
        party = self.parties.get(key)
        if party is None:
            party = self.parties[key] = Party(id=key, kind=kind, name=name[:80], zone=zone)
            if kind != "person":
                self.by_name.setdefault(org_key(name), key)
        if zone == CLIENT:
            party.zone = CLIENT
        if role and role not in party.roles:
            party.roles.append(role)
            party.modules.extend(self.by_role.get(role, []))
        if module:
            party.modules.append(module)
            party.touches[module] = party.touches.get(module, 0) + 1
        if kind == "person" and org_name and org_name.strip():
            self.person_org.setdefault(key, org_key(org_name))

    def finish(self) -> list[Party]:
        """Link people to their company and tell apart companies sharing initials."""
        for key, okey in self.person_org.items():
            org = self.by_name.get(okey)
            if org and key in self.parties:
                self.parties[key].org = org
        seen: dict[str, list[Party]] = {}
        for p in self.parties.values():
            p.initials = monogram(p.name, 2)
            if p.kind != "person":
                seen.setdefault(p.initials, []).append(p)
        for same in seen.values():
            if len(same) > 1:
                for p in same:
                    p.initials = monogram(p.name, 3)
        return list(self.parties.values())


async def _rows(session: AsyncSession, stmt: Any, limit: int = MAX_PARTIES) -> list[Any]:
    try:
        async with session.begin_nested():
            return list((await session.execute(stmt.limit(limit))).all())
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
            col.add(
                key,
                "person",
                member.display_name,
                zone,
                "site_manager" if zone == DELIVERY else None,
                "oe_teams",
                org_name=member.company_name,
            )

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
                select(Contact, PurchaseOrder.id)
                .join(PurchaseOrder, PurchaseOrder.vendor_contact_id == Contact.id)
                .where(PurchaseOrder.project_id == project_id)
            )
            for contact, _po in await _rows(session, stmt, MAX_ROWS):
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
        for party_id, display_name, party_role, party_type in await _rows(session, stmt, MAX_ROWS):
            zone = zone_for_text(party_role)
            role = "client" if zone == CLIENT else ("consultant" if zone == SPECIALIST else "contractor")
            kind = "person" if (party_type or "") in ("user", "person") else "company"
            key = f"contact:{party_id}" if party_id else f"party:{display_name}"
            col.add(key, kind, display_name, zone, role, "oe_contracts")

    if "oe_subcontractors" in loaded:
        from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor

        stmt = (
            select(
                Subcontractor.id,
                Subcontractor.contact_id,
                Subcontractor.legal_name,
                Subcontractor.trade_name,
                SubcontractAgreement.id,
            )
            .join(SubcontractAgreement, SubcontractAgreement.subcontractor_id == Subcontractor.id)
            .where(SubcontractAgreement.project_id == project_id)
        )
        for sid, contact_id, legal, trade, _agreement in await _rows(session, stmt, MAX_ROWS):
            key = f"contact:{contact_id}" if contact_id else f"sub:{sid}"
            col.add(key, "company", trade or legal, DELIVERY, "subcontractor", "oe_subcontractors")

    if "oe_tendering" in loaded:
        from app.modules.tendering.models import TenderBid, TenderPackage

        stmt = (
            select(TenderBid.contact_id, TenderBid.company_name, TenderBid.id)
            .join(TenderPackage, TenderPackage.id == TenderBid.package_id)
            .where(TenderPackage.project_id == project_id)
        )
        for contact_id, company, _bid in await _rows(session, stmt, MAX_ROWS):
            key = f"contact:{contact_id}" if contact_id else f"bidder:{(company or '').strip().lower()}"
            col.add(key, "company", company, DELIVERY, "bidder", "oe_tendering")

    parties = col.finish()
    if not parties:
        parties = placeholders(manifests)
    return [p.as_dict() for p in parties]
