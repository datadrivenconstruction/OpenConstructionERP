# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who sees which project, and who sells on its invoices, on the worked examples.

DE group: HB Muster Hochbau GmbH (sites HB-BER, HB-LEI) and TB Muster Tiefbau
GmbH; project P-2026-014 on HB / HB-LEI. A person who works for TB only does
not see it; a person of HB does; a TB person on its team does. The seller
block names Muster Hochbau GmbH and DE123456789, not the group.

US group: project TX-118 on RC Ridgeline Civil LLC; the seller carries its EIN
and is complete without any VAT id.

Single-company install: a project that names no company sells exactly as
before, byte for byte.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.dependencies import accessible_project_ids, verify_project_access
from app.modules.finance.einvoice_settings_models import EInvoiceSettings
from app.modules.finance.einvoice_settings_service import einvoice_defaults
from app.modules.legal_entities.models import Branch, LegalEntity, LegalEntityMember
from app.modules.legal_entities.seller import resolve_seller
from app.modules.legal_entities.service import LegalEntityService
from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            yield s


async def _user(s: AsyncSession, name: str, role: str = "editor") -> User:
    user = User(email=f"{name}-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name=name, role=role)
    s.add(user)
    await s.flush()
    return user


async def _project(s: AsyncSession, name: str, owner: User, **kw) -> Project:
    project = Project(name=name, owner_id=owner.id, currency=kw.pop("currency", "EUR"), **kw)
    s.add(project)
    await s.flush()
    return project


async def _entity(s: AsyncSession, code: str, legal_name: str, country: str, tax: dict, **kw) -> LegalEntity:
    entity = LegalEntity(
        code=code,
        name=legal_name,
        legal_name=legal_name,
        country_code=country,
        functional_currency="EUR" if country == "DE" else "USD",
        tax_ids=[tax],
        address=kw.pop("address", {"line1": "Street 1", "postcode": "10115", "city": "Berlin"}),
        **kw,
    )
    s.add(entity)
    await s.flush()
    return entity


async def _on_team(s: AsyncSession, project: Project, user: User) -> None:
    team = Team(project_id=project.id, name="Site team")
    s.add(team)
    await s.flush()
    s.add(TeamMembership(team_id=team.id, user_id=user.id))
    await s.flush()


@pytest_asyncio.fixture
async def de_group(session: AsyncSession) -> dict:
    s = session
    owner = await _user(s, "estimator")
    hb = await _entity(s, "HB", "Muster Hochbau GmbH", "DE", {"scheme": "vat", "value": "DE123456789"}, is_default=True)
    tb = await _entity(s, "TB", "Muster Tiefbau GmbH", "DE", {"scheme": "vat", "value": "DE987654321"})
    ber = Branch(legal_entity_id=hb.id, code="HB-BER", name="Berlin", country_code="DE")
    lei = Branch(legal_entity_id=hb.id, code="HB-LEI", name="Leipzig", country_code="DE")
    s.add_all([ber, lei])
    await s.flush()
    p014 = await _project(s, "P-2026-014", owner, country_code="DE")
    await LegalEntityService(s).assign_project(p014.id, hb.id, lei.id)
    tb_project = await _project(s, "TB road", owner, country_code="DE", legal_entity_id=tb.id)
    unassigned = await _project(s, "Old project", owner, country_code="DE")
    return {"owner": owner, "hb": hb, "tb": tb, "lei": lei, "p014": p014, "tb_project": tb_project, "old": unassigned}


async def test_a_person_of_tb_only_does_not_see_p014(session: AsyncSession, de_group: dict) -> None:
    s, g = session, de_group
    jonas = await _user(s, "jonas")
    s.add(LegalEntityMember(legal_entity_id=g["tb"].id, user_id=jonas.id, role="member"))
    await s.flush()

    seen = await accessible_project_ids(s, str(jonas.id))
    assert g["p014"].id not in seen
    assert g["tb_project"].id in seen
    with pytest.raises(HTTPException):
        await verify_project_access(g["p014"].id, str(jonas.id), s)


async def test_a_person_of_hb_sees_p014_and_the_projects_that_name_no_company(
    session: AsyncSession, de_group: dict
) -> None:
    s, g = session, de_group
    anna = await _user(s, "anna")
    s.add(LegalEntityMember(legal_entity_id=g["hb"].id, user_id=anna.id, role="admin"))
    await s.flush()

    seen = await accessible_project_ids(s, str(anna.id))
    # HB is the default company, so the project naming none belongs to it.
    assert {g["p014"].id, g["old"].id} <= seen
    assert g["tb_project"].id not in seen
    await verify_project_access(g["p014"].id, str(anna.id), s)


async def test_a_tb_person_on_the_team_of_p014_sees_it(session: AsyncSession, de_group: dict) -> None:
    s, g = session, de_group
    mia = await _user(s, "mia")
    s.add(LegalEntityMember(legal_entity_id=g["tb"].id, user_id=mia.id))
    await _on_team(s, g["p014"], mia)
    assert g["p014"].id in await accessible_project_ids(s, str(mia.id))


async def test_admins_and_owners_are_untouched_by_memberships(session: AsyncSession, de_group: dict) -> None:
    s, g = session, de_group
    admin = await _user(s, "admin", role="admin")
    s.add(LegalEntityMember(legal_entity_id=g["tb"].id, user_id=admin.id))
    s.add(LegalEntityMember(legal_entity_id=g["tb"].id, user_id=g["owner"].id))
    await s.flush()
    assert await accessible_project_ids(s, str(admin.id)) is None
    owned = {g["p014"].id, g["tb_project"].id, g["old"].id}
    assert owned <= await accessible_project_ids(s, str(g["owner"].id))


async def test_the_p014_invoice_sells_as_muster_hochbau_not_the_group(session: AsyncSession, de_group: dict) -> None:
    s, g = session, de_group
    s.add(
        EInvoiceSettings(
            scope="default",
            seller_name="Muster Gruppe Holding",
            seller_vat_id="DE111111111",
            seller_country_code="DE",
            seller_line1="Konzernplatz 1",
            seller_city="Berlin",
            payee_iban="DE02120300000000202051",
        )
    )
    await s.flush()

    resolution = await resolve_seller(s, g["p014"].id)
    assert resolution.source == "entity"
    assert resolution.seller["name"] == "Muster Hochbau GmbH"
    assert resolution.seller["vat_id"] == "DE123456789"
    assert resolution.missing == []
    # Not identity: the group's bank account still applies until HB has its own settings.
    assert resolution.defaults["payee_iban"] == "DE02120300000000202051"

    defaults = await einvoice_defaults(s, project_id=g["p014"].id)
    assert defaults["seller"]["name"] == "Muster Hochbau GmbH"
    # The project naming no company keeps the group settings, unchanged.
    assert await einvoice_defaults(s, project_id=g["old"].id) == await einvoice_defaults(s)

    s.add(EInvoiceSettings(scope=f"entity:{g['hb'].id}", seller_name="Muster Hochbau GmbH (eigene)"))
    await s.flush()
    assert (await resolve_seller(s, g["p014"].id)).source == "entity_settings"


async def test_tx118_pay_application_carries_ridgeline_civil_and_its_ein(session: AsyncSession) -> None:
    s = session
    owner = await _user(s, "pm")
    rc = await _entity(
        s,
        "RC",
        "Ridgeline Civil LLC",
        "US",
        {"scheme": "ein", "value": "98-7654321"},
        address={"line1": "200 Sample Rd", "postcode": "78701", "city": "Austin"},
    )
    aus = Branch(legal_entity_id=rc.id, code="RC-AUS", name="Austin TX", country_code="US")
    s.add(aus)
    await s.flush()
    tx118 = await _project(s, "TX-118", owner, currency="USD", country_code="US")
    await LegalEntityService(s).assign_project(tx118.id, rc.id, aus.id)

    resolution = await resolve_seller(s, tx118.id)
    assert resolution.seller["name"] == "Ridgeline Civil LLC"
    assert resolution.seller["tax_number"] == "98-7654321"
    assert "vat_id" not in resolution.seller
    assert resolution.missing == []


async def test_a_site_of_another_company_cannot_be_given_to_a_project(session: AsyncSession, de_group: dict) -> None:
    s, g = session, de_group
    with pytest.raises(HTTPException) as exc:
        await LegalEntityService(s).assign_project(g["tb_project"].id, g["tb"].id, g["lei"].id)
    assert exc.value.status_code == 422
    assert exc.value.detail[0]["rule_id"] == "entity.site_wrong_entity"


async def test_an_inactive_company_cannot_take_a_project(session: AsyncSession, de_group: dict) -> None:
    s, g = session, de_group
    g["tb"].is_active = False
    await s.flush()
    with pytest.raises(HTTPException) as exc:
        await LegalEntityService(s).assign_project(g["old"].id, g["tb"].id)
    assert exc.value.detail[0]["rule_id"] == "entity.inactive_on_new_project"


async def test_a_single_company_install_sells_exactly_as_before(session: AsyncSession) -> None:
    s = session
    owner = await _user(s, "solo")
    projects = [await _project(s, f"Job {i}", owner) for i in range(3)]
    s.add(EInvoiceSettings(scope="default", seller_name="Example Construction Ltd", seller_vat_id="GB123456789"))
    await s.flush()
    before = await einvoice_defaults(s)
    for project in projects:
        assert await einvoice_defaults(s, project_id=project.id) == before
    resolution = await resolve_seller(s, projects[0].id)
    assert resolution.source == "default" and not resolution.assigned


async def test_the_first_company_becomes_the_default(session: AsyncSession) -> None:
    service = LegalEntityService(session)
    first = await service.create_entity(
        {"code": "MAIN", "name": "Example Construction", "country_code": "GB", "functional_currency": "GBP"}
    )
    second = await service.create_entity(
        {"code": "SUB", "name": "Example Civil", "country_code": "GB", "functional_currency": "GBP"}
    )
    assert first.is_default and not second.is_default
