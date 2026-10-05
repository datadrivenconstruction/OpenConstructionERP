# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A client sees the payment plan of their contract, as far as a person marked it.

Surface (portal-session-gated):
    GET /api/v1/portal/projects/{project_id}/payment-plan

Tests:
* Only instalments marked ``client_visible`` of client contracts in force are
  listed; the totals add up those lines, money goes out as strings and no
  internal field (claims, findings, metadata, schedule links) is in the body.
* A draft or terminated client contract and a supplier contract are hidden.
* A due date that moved says by how much. Nothing reads overdue before it is
  invoiced; once it is, the invoice's due date counts.
* A ``contract`` rule shows that contract only; a rule on nothing in the
  project, or no rule at all, answers 404 like a project that does not exist.
* A ``project`` rule shows every plan to the client side only: a
  subcontractor let into the project sees just the contracts it holds a rule on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _no_detached_events(monkeypatch):
    from app.core import events

    monkeypatch.setattr(events.event_bus, "publish_detached", lambda *a, **k: None)


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.contracts import models as _contracts_models  # noqa: F401
        from app.modules.portal import models as _portal_models  # noqa: F401
        from app.modules.schedule import models as _schedule_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _iso(offset_days: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset_days)).isoformat()


async def _portal_user(s, now, rules: list[tuple[str, uuid.UUID]], *, role: str = "client") -> dict[str, str]:
    from app.modules.portal.models import PortalAccessRule, PortalSession, PortalUser
    from app.modules.portal.service import generate_token, hash_token

    user = PortalUser(
        id=uuid.uuid4(),
        email=f"client-{uuid.uuid4().hex[:6]}@plan.io",
        portal_role=role,
        full_name="Home Owner",
        status="active",
    )
    s.add(user)
    await s.flush()
    for resource_type, resource_id in rules:
        s.add(
            PortalAccessRule(
                portal_user_id=user.id, resource_type=resource_type, resource_id=resource_id, permission="view"
            )
        )
    token = generate_token()
    s.add(
        PortalSession(
            portal_user_id=user.id,
            session_token_hash=hash_token(token),
            ip_address="127.0.0.1",
            user_agent="pytest",
            started_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def seeded(http_client):
    from app.database import async_session_factory
    from app.modules.contracts.models import Contract, ContractMilestone, ProgressClaim
    from app.modules.finance.models import Invoice
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    now = datetime.now(UTC)
    async with async_session_factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:8]}@plan.io",
            full_name="Builder",
            hashed_password="x" * 60,
            role="admin",
            is_active=True,
        )
        s.add(owner)
        await s.flush()
        mine = Project(name=f"Plan-{uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="USD")
        other = Project(name=f"Plan-other-{uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="USD")
        s.add_all([mine, other])
        await s.flush()

        def contract(project, code, *, status="active", counterparty="client"):
            return Contract(
                id=uuid.uuid4(),
                code=code,
                title=f"Contract {code}",
                project_id=project.id,
                contract_type="lump_sum",
                counterparty_type=counterparty,
                currency="USD",
                total_value=Decimal("100000"),
                retention_percent=Decimal("0"),
                terms={"payment_terms": {"payment_period_days": 0}},
                status=status,
            )

        house = contract(mine, "A-HOUSE")
        annex = contract(mine, "B-ANNEX")
        draft = contract(mine, "C-DRAFT", status="draft")
        ended = contract(mine, "D-ENDED", status="terminated")
        supply = contract(mine, "E-SUPPLY", counterparty="supplier")
        theirs = contract(other, "F-THEIRS")
        s.add_all([house, annex, draft, ended, supply, theirs])
        await s.flush()

        def instalment(c, code, name, value, *, planned, status="pending", visible=True, reached=None):
            return ContractMilestone(
                contract_id=c.id,
                code=code,
                name=name,
                planned_date=planned,
                value=Decimal(value),
                trigger="date",
                status=status,
                reached_at=reached,
                client_visible=visible,
                metadata_={"note": "internal"},
            )

        s.add_all(
            [
                instalment(house, "1", "Deposit", "10000", planned=_iso(-40), status="paid"),
                # Reached five days later than the contract said, and unpaid.
                instalment(
                    house, "2", "Frame", "30000", planned=_iso(-10), status="reached", reached=_iso(-5) + "T09:00:00"
                ),
                instalment(house, "3", "Handover", "40000", planned=_iso(20)),
                instalment(house, "4", "Internal retention release", "20000", planned=_iso(30), visible=False),
                instalment(annex, "1", "Annex start", "5000", planned=_iso(3)),
                annex_billed := instalment(
                    annex, "2", "Annex frame", "5000", planned=_iso(-20), status="invoiced", reached=_iso(-20)
                ),
                instalment(draft, "1", "Draft deposit", "1000", planned=_iso(1)),
                instalment(ended, "1", "Ended deposit", "1000", planned=_iso(1)),
                instalment(supply, "1", "Supplier deposit", "1000", planned=_iso(1)),
                instalment(theirs, "1", "Their deposit", "1000", planned=_iso(1)),
            ]
        )
        await s.flush()
        # Billed: the invoice gave the client until three days ago.
        billed_claim = ProgressClaim(
            contract_id=annex.id,
            claim_number="PC-ANNEX",
            currency="USD",
            status="certified",
            gross_basis="milestone",
            gross_amount=Decimal("5000"),
            milestone_id=annex_billed.id,
        )
        s.add(billed_claim)
        await s.flush()
        s.add(
            Invoice(
                project_id=mine.id,
                invoice_direction="receivable",
                invoice_number="INV-ANNEX",
                invoice_date=_iso(-17),
                due_date=_iso(-3),
                currency_code="USD",
                status="sent",
                source_claim_id=billed_claim.id,
            )
        )
        await s.flush()

        headers = {
            "project": await _portal_user(s, now, [("project", mine.id)]),
            "annex": await _portal_user(s, now, [("contract", annex.id)]),
            "elsewhere": await _portal_user(s, now, [("contract", theirs.id)]),
            "nothing": await _portal_user(s, now, []),
            "sub_project": await _portal_user(s, now, [("project", mine.id)], role="subcontractor"),
            "sub_annex": await _portal_user(
                s, now, [("project", mine.id), ("contract", annex.id)], role="subcontractor"
            ),
            "investor": await _portal_user(s, now, [("project", mine.id)], role="investor"),
        }
        await s.commit()
    return {
        "project_id": str(mine.id),
        "other_id": str(other.id),
        "house_id": str(house.id),
        "annex_id": str(annex.id),
        "headers": headers,
    }


def _url(project_id: str) -> str:
    return f"/api/v1/portal/projects/{project_id}/payment-plan"


@pytest.mark.asyncio
async def test_the_client_sees_the_visible_lines_of_client_contracts_in_force(http_client, seeded):
    resp = await http_client.get(_url(seeded["project_id"]), headers=seeded["headers"]["project"])
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [i["contract_id"] for i in items] == [seeded["house_id"], seeded["annex_id"]]

    house = items[0]
    assert house["contract_title"] == "Contract A-HOUSE"
    assert house["currency"] == "USD"
    assert Decimal(house["contract_total"]) == Decimal("100000")
    # The visible lines only: the hidden twenty thousand is in neither total.
    assert Decimal(house["paid_total"]) == Decimal("10000")
    assert Decimal(house["outstanding_total"]) == Decimal("70000")
    assert isinstance(house["paid_total"], str)
    assert [ln["milestone_name"] for ln in house["lines"]] == ["Deposit", "Frame", "Handover"]
    assert [ln["sequence"] for ln in house["lines"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_each_line_says_when_it_falls_due_and_how_far_it_moved(http_client, seeded):
    resp = await http_client.get(_url(seeded["project_id"]), headers=seeded["headers"]["project"])
    deposit, frame, handover = resp.json()["items"][0]["lines"]

    assert deposit["status"] == "paid"
    assert deposit["days_until"] is None and deposit["days_overdue"] is None

    # Reached and past its forecast, but nobody has invoiced it yet.
    assert frame["status"] == "due"
    assert frame["original_due_date"] == _iso(-10)
    assert frame["forecast_due_date"] == _iso(-5)
    assert frame["days_moved"] == 5
    assert frame["days_overdue"] is None
    assert frame["days_until"] is None
    assert Decimal(frame["amount"]) == Decimal("30000")
    assert Decimal(frame["percent_of_contract"]) == Decimal("30")

    assert handover["status"] == "upcoming"
    assert handover["days_until"] == 20
    assert handover["days_moved"] == 0


@pytest.mark.asyncio
async def test_an_invoiced_line_falls_due_on_its_invoice(http_client, seeded):
    resp = await http_client.get(_url(seeded["project_id"]), headers=seeded["headers"]["annex"])
    billed = next(ln for ln in resp.json()["items"][0]["lines"] if ln["milestone_name"] == "Annex frame")
    assert billed["status"] == "overdue"
    assert billed["forecast_due_date"] == _iso(-3)
    assert billed["days_overdue"] == 3


@pytest.mark.asyncio
async def test_no_internal_field_reaches_the_client(http_client, seeded):
    resp = await http_client.get(_url(seeded["project_id"]), headers=seeded["headers"]["project"])
    body = resp.json()
    assert "findings" not in body
    contract = body["items"][0]
    assert set(contract) == {
        "contract_id",
        "contract_title",
        "currency",
        "contract_total",
        "paid_total",
        "outstanding_total",
        "lines",
    }
    assert set(contract["lines"][0]) == {
        "id",
        "sequence",
        "label",
        "amount",
        "percent_of_contract",
        "status",
        "milestone_name",
        "forecast_due_date",
        "original_due_date",
        "days_moved",
        "days_until",
        "days_overdue",
    }
    assert "internal" not in resp.text


@pytest.mark.asyncio
async def test_a_contract_rule_shows_that_contract_only(http_client, seeded):
    resp = await http_client.get(_url(seeded["project_id"]), headers=seeded["headers"]["annex"])
    assert resp.status_code == 200, resp.text
    assert [i["contract_id"] for i in resp.json()["items"]] == [seeded["annex_id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["elsewhere", "nothing"])
async def test_a_caller_without_a_rule_in_the_project_reads_it_as_missing(http_client, seeded, who):
    resp = await http_client.get(_url(seeded["project_id"]), headers=seeded["headers"][who])
    missing = await http_client.get(_url(str(uuid.uuid4())), headers=seeded["headers"][who])
    assert resp.status_code == 404
    assert missing.status_code == 404
    assert resp.json() == missing.json()


@pytest.mark.asyncio
async def test_an_investor_reads_the_project_like_the_client(http_client, seeded):
    resp = await http_client.get(_url(seeded["project_id"]), headers=seeded["headers"]["investor"])
    assert resp.status_code == 200, resp.text
    assert [i["contract_id"] for i in resp.json()["items"]] == [seeded["house_id"], seeded["annex_id"]]


@pytest.mark.asyncio
async def test_a_subcontractors_project_rule_shows_no_client_plan(http_client, seeded):
    resp = await http_client.get(_url(seeded["project_id"]), headers=seeded["headers"]["sub_project"])
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a_subcontractor_sees_only_the_contract_it_holds_a_rule_on(http_client, seeded):
    resp = await http_client.get(_url(seeded["project_id"]), headers=seeded["headers"]["sub_annex"])
    assert resp.status_code == 200, resp.text
    assert [i["contract_id"] for i in resp.json()["items"]] == [seeded["annex_id"]]


@pytest.mark.asyncio
async def test_another_tenants_project_reads_as_missing(http_client, seeded):
    resp = await http_client.get(_url(seeded["other_id"]), headers=seeded["headers"]["project"])
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_no_session_is_refused(http_client, seeded):
    resp = await http_client.get(_url(seeded["project_id"]))
    assert resp.status_code == 401
