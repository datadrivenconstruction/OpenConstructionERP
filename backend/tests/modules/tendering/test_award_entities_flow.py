# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Issuing company, package header, award to controlling, rejections in bulk, filing.

Worked example 1 of the subcontractor award: the client entity "Bau GmbH Nord"
of a group that also runs "Bau GmbH Sued". Final offer of the drywall firm
412,380.00 EUR on cost line 300.345 (the discount lives on another branch, so
the contract sum here is the final offer). Two other firms lost; one gave an
email address, one did not.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.email import MemoryEmailBackend
from app.core.email import service as email_service_module
from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.costmodel.models import CostLine
from app.modules.documents.models import Document
from app.modules.legal_entities.models import LegalEntity
from app.modules.projects.models import Project
from app.modules.tendering import award_flow
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.tendering.pdf_documents import generate_rejection_letter_pdf
from app.modules.tendering.schemas import PackageHeaderUpdate
from app.modules.tendering.service import TenderingService
from app.modules.tendering.validators import ENTITY_AWARD_RULE_SET, register_tendering_award_rules
from app.modules.users.models import User
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def engine():
    # One database for the module: cloning the schema template per test costs minutes on Windows.
    async with isolated_engine() as eng:
        yield eng


@pytest_asyncio.fixture
async def session(engine):
    async with engine.connect() as conn:
        outer = await conn.begin()
        factory = async_sessionmaker(
            bind=conn, class_=AsyncSession, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with factory() as s:
            yield s
        await outer.rollback()


async def _entity(s: AsyncSession, code: str, name: str, **kw) -> LegalEntity:
    entity = LegalEntity(
        code=code,
        name=name,
        legal_name=name,
        country_code="DE",
        functional_currency="EUR",
        tax_ids=[{"scheme": "vat", "value": "DE123456789"}],
        address={"line1": "Hafenstrasse 1", "postcode": "20457", "city": "Hamburg"},
        default_signatory="Petra Nord",
        bank={"iban": "DE02120300000000202051", "bank_name": "Musterbank"},
        **kw,
    )
    s.add(entity)
    await s.flush()
    return entity


@pytest_asyncio.fixture
async def group(session: AsyncSession) -> dict:
    s = session
    owner = User(email=f"buyer-{uuid.uuid4().hex[:6]}@builder.de", hashed_password="x", full_name="Buyer", role="admin")
    s.add(owner)
    await s.flush()
    nord = await _entity(s, "NORD", "Bau GmbH Nord", is_default=True)
    sued = await _entity(s, "SUED", "Bau GmbH Sued")
    project = Project(name="Wohnquartier Hafen", owner_id=owner.id, currency="EUR")
    other = Project(name="Other job", owner_id=owner.id, currency="EUR")
    s.add_all([project, other])
    await s.flush()
    line = CostLine(project_id=project.id, code="300.345", description="Drywall", estimate_amount="430000.00")
    foreign = CostLine(project_id=other.id, code="999", description="Elsewhere")
    s.add_all([line, foreign])
    package = TenderPackage(project_id=project.id, name="Drywall", status="evaluating", metadata_={})
    s.add(package)
    await s.flush()
    return {
        "owner": owner,
        "nord": nord,
        "sued": sued,
        "project": project,
        "line": line,
        "foreign": foreign,
        "package": package,
    }


async def _award(s: AsyncSession, package: TenderPackage) -> dict[str, TenderBid]:
    bids = {
        "win": TenderBid(
            package_id=package.id,
            company_name="Trockenbau West",
            contact_email="bids@tb-west.de",
            total_amount="412380.00",
            currency="EUR",
            status="accepted",
        ),
        "lose": TenderBid(
            package_id=package.id,
            company_name="Ausbau Sued",
            contact_email="offers@ausbau-sued.de",
            total_amount="430110.00",
            currency="EUR",
            status="rejected",
        ),
        "silent": TenderBid(
            package_id=package.id,
            company_name="Innenausbau Ost",
            contact_email="",
            total_amount="441900.00",
            currency="EUR",
            status="rejected",
        ),
    }
    s.add_all(bids.values())
    await s.flush()
    package.status = "awarded"
    package.metadata_ = {"awarded_bid_id": str(bids["win"].id), "awarded_at": "2026-11-19T10:00:00+00:00"}
    await s.flush()
    return bids


async def _rules(s: AsyncSession, package: TenderPackage) -> dict[str, bool]:
    register_tendering_award_rules()
    context = ValidationContext(data=await award_flow.award_validation_payload(s, package))
    out = {}
    for rule in rule_registry.get_rules_for_sets([ENTITY_AWARD_RULE_SET]):
        for r in await rule.validate(context):
            out[r.rule_id] = r.passed
    return out


async def test_a_group_package_without_a_company_is_warned_and_one_named_passes(session, group) -> None:
    package = group["package"]
    assert (await _rules(session, package))["award.mandant_missing"] is False

    await award_flow.write_header(session, package, PackageHeaderUpdate(legal_entity_id=group["nord"].id))
    header = await award_flow.read_header(session, package)
    assert header.issuing_entity is not None
    assert (header.issuing_entity.name, header.issuing_entity.source) == ("Bau GmbH Nord", "package")
    assert header.active_entity_count == 2
    assert (await _rules(session, package))["award.mandant_missing"] is True


async def test_the_project_company_is_used_when_the_package_names_none(session, group) -> None:
    group["project"].legal_entity_id = group["sued"].id
    await session.flush()
    entity, source = await award_flow.issuing_entity(session, group["package"])
    assert (entity.code, source) == ("SUED", "project")


async def test_a_single_company_install_is_never_warned(session, group) -> None:
    group["sued"].is_active = False
    await session.flush()
    assert (await _rules(session, group["package"]))["award.mandant_missing"] is True


async def test_the_header_refuses_inactive_companies_and_foreign_cost_lines(session, group) -> None:
    package = group["package"]
    group["sued"].is_active = False
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await award_flow.write_header(session, package, PackageHeaderUpdate(legal_entity_id=group["sued"].id))
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await award_flow.write_header(session, package, PackageHeaderUpdate(cost_line_id=group["foreign"].id))
    assert exc.value.status_code == 422


async def test_the_header_keeps_trade_cost_line_dates_and_roles(session, group) -> None:
    package = group["package"]
    await award_flow.write_header(
        session,
        package,
        PackageHeaderUpdate(
            trade="  Drywall  ",
            cost_line_id=group["line"].id,
            issue_date=date(2026, 11, 2),
            questions_until=date(2026, 11, 20),
            bids_due=date(2026, 11, 16),
            award_planned=date(2026, 12, 1),
            buyer_id=str(group["owner"].id),
        ),
    )
    header = await award_flow.read_header(session, package)
    assert header.trade == "Drywall"
    assert header.cost_line is not None
    assert (header.cost_line.code, header.cost_line.budget) == ("300.345", "430000.00")
    assert header.buyer_id == str(group["owner"].id)
    assert header.warnings == ["questions_until_after_bids_due"]


async def test_after_the_award_the_company_is_fixed(session, group) -> None:
    package = group["package"]
    await award_flow.write_header(session, package, PackageHeaderUpdate(legal_entity_id=group["nord"].id))
    await _award(session, package)
    with pytest.raises(HTTPException) as exc:
        await award_flow.write_header(session, package, PackageHeaderUpdate(legal_entity_id=group["sued"].id))
    assert exc.value.status_code == 409
    await award_flow.write_header(session, package, PackageHeaderUpdate(trade="Drywall and ceilings"))


async def test_controlling_gets_project_cost_code_contract_sum_and_company(session, group) -> None:
    package = group["package"]
    await award_flow.write_header(
        session, package, PackageHeaderUpdate(legal_entity_id=group["nord"].id, cost_line_id=group["line"].id)
    )
    bids = await _award(session, package)
    fields = await award_flow.controlling_fields(session, package, bids["win"])
    assert fields["project_id"] == str(group["project"].id)
    assert fields["cost_code"] == "300.345"
    assert fields["cost_line_id"] == str(group["line"].id)
    assert (fields["contract_sum"], fields["currency"]) == ("412380.00", "EUR")
    assert (fields["legal_entity_code"], fields["legal_entity_name"]) == ("NORD", "Bau GmbH Nord")


async def test_letters_are_issued_in_the_company_name(session, group) -> None:
    issuer = award_flow.issuer_identity(group["nord"])
    assert issuer["name"] == "Bau GmbH Nord"
    assert issuer["address"] == "Hafenstrasse 1, 20457 Hamburg, DE"
    assert issuer["tax_id"] == "DE123456789"
    assert issuer["signatory"] == "Petra Nord"
    assert "DE02120300000000202051" in issuer["bank"]
    pdf = generate_rejection_letter_pdf(
        package_name="Drywall",
        package_ref="abc",
        project_name="Wohnquartier Hafen",
        company_name="Ausbau Sued",
        contact_email="",
        issuer=issuer,
    )
    assert pdf.startswith(b"%PDF")


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch, tmp_path) -> MemoryEmailBackend:
    box = MemoryEmailBackend()
    original = email_service_module.get_email_service
    monkeypatch.setattr("app.core.email.get_email_service", lambda backend=None: original(backend=box))
    monkeypatch.setattr(award_flow, "_award_dir", lambda project_id: tmp_path / str(project_id))
    return box


async def test_all_rejections_go_out_in_one_action_and_are_filed(session, group, outbox) -> None:
    package = group["package"]
    await award_flow.write_header(session, package, PackageHeaderUpdate(legal_entity_id=group["nord"].id))
    await _award(session, package)
    service = TenderingService(session)

    preview = await award_flow.rejection_preview(session, package)
    assert {r.company_name: r.state for r in preview.rows} == {"Ausbau Sued": "pending", "Innenausbau Ost": "no_email"}
    assert preview.pending == 1
    assert (await _rules(session, package))["award.losers_not_notified"] is False

    result = await award_flow.send_rejections(service, package, [], actor_id=str(group["owner"].id))
    assert (result.sent, result.failed, result.filed) == (1, 0, 1)
    (mail,) = outbox.sent
    assert mail.to == "offers@ausbau-sued.de"
    assert mail.attachments[0].content.startswith(b"%PDF")
    assert {r.company_name: r.state for r in result.rows}["Ausbau Sued"] == "sent"

    again = await award_flow.send_rejections(service, package, [], actor_id=None)
    assert again.sent == 0
    assert len(outbox.sent) == 1

    docs = (await session.execute(select(Document).where(Document.project_id == group["project"].id))).scalars().all()
    assert [d.category for d in docs] == ["correspondence"]


async def test_award_documents_are_filed_once(session, group, outbox) -> None:
    package = group["package"]
    await _award(session, package)
    service = TenderingService(session)
    first = await award_flow.file_award_documents(service, package, actor_id=None)
    states = {d.kind: d.state for d in first.documents}
    assert states == {"contract": "skipped", "award_record": "filed", "award_letter": "filed"}
    second = await award_flow.file_award_documents(service, package, actor_id=None)
    assert {d.kind: d.state for d in second.documents} == {
        "contract": "skipped",
        "award_record": "already_filed",
        "award_letter": "already_filed",
    }


async def test_rejections_wait_for_the_award(session, group, outbox) -> None:
    with pytest.raises(HTTPException) as exc:
        await award_flow.send_rejections(TenderingService(session), group["package"], [], actor_id=None)
    assert exc.value.status_code == 409


_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def _sued_without_ids() -> LegalEntity:
    return LegalEntity(
        code="SUED",
        name="Bau GmbH Sued",
        country_code="DE",
        functional_currency="EUR",
        tax_ids=[],
        address={"line1": "Isarweg 2", "postcode": "80331", "city": "Muenchen"},
        logo_data_url=_PNG,
    )


async def test_documents_print_the_issuing_company_and_its_logo() -> None:
    from app.core.company_profile import issuing_company, read_company_profile
    from app.core.doc_templates.seller import resolve_seller
    from app.modules.legal_entities.seller import entity_profile

    workspace = read_company_profile()
    with issuing_company(entity_profile(_sued_without_ids())):
        profile = read_company_profile()
        seller = resolve_seller()
    assert profile["legal_name"] == "Bau GmbH Sued"
    assert profile["address"] == "Isarweg 2\n80331 Muenchen"
    assert profile["document_logo_data_url"] == _PNG
    # A blank tax id stays blank: the workspace's VAT number never lands on another company.
    assert profile["vat_id"] == ""
    assert seller.legal_name == "Bau GmbH Sued"
    assert read_company_profile() == workspace


async def test_award_rule_messages_follow_the_language() -> None:
    from app.modules.tendering.validators import AwardLosersNotNotified, AwardMandantMissing

    data = {"package_id": "p", "active_entity_count": 2, "awarded": True, "losers_not_notified": ["A", "B"]}
    ctx = ValidationContext(data=data, metadata={"locale": "de"})
    (mandant,) = await AwardMandantMissing().validate(ctx)
    (losers,) = await AwardLosersNotNotified().validate(ctx)
    assert mandant.message.startswith("Das Paket hat keinen Mandanten")
    assert losers.message == "Absagen an 2 Bieter nicht versandt."
    (en,) = await AwardLosersNotNotified().validate(ValidationContext(data=data))
    assert en.message == "Rejection letters not sent to 2 bidders."


async def test_contract_names_the_package_company_not_the_project_one(session, group) -> None:
    from app.core.company_profile import issuing_company, read_company_profile
    from app.modules.legal_entities.seller import entity_for_contract, entity_profile

    package = group["package"]
    group["project"].legal_entity_id = group["nord"].id
    package.legal_entity_id = group["sued"].id
    await session.flush()
    entity, source = await award_flow.issuing_entity(session, package)
    assert (entity.code, source) == ("SUED", "package")

    class _Contract:
        project_id = group["project"].id
        metadata_ = {"legal_entity_id": str(group["sued"].id)}

    assert (await entity_for_contract(session, _Contract())).code == "SUED"
    _Contract.metadata_ = {}
    assert (await entity_for_contract(session, _Contract())).code == "NORD"
    with issuing_company(entity_profile(group["sued"])):
        assert read_company_profile()["legal_name"] == "Bau GmbH Sued"
