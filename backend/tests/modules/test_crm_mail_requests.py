"""CRM: deal currency, trade-show source, account contacts, lead conversion, reports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError

import app.modules.contacts.models  # noqa: F401
import app.modules.crm.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from app.modules.crm.models import Account, CrmActivity, Lead, PipelineStage
from app.modules.crm.schemas import (
    LeadConvertRequest,
    LeadCreate,
    OpportunityCreate,
    OpportunityUpdate,
)
from app.modules.crm.service import CrmService, compute_revenue_by_month, summarize_owner_activities
from app.modules.crm.validators import check_period, normalize_currency
from tests._pg import clear_module_tables, create_module_tables

_STAGE = "00000000-0000-0000-0000-000000000001"
_ACCOUNT = "00000000-0000-0000-0000-000000000002"


def _deal(**kw):
    base = {
        "account_id": _ACCOUNT,
        "title": "Deal",
        "stage_id": _STAGE,
        **kw,
    }
    return OpportunityCreate(**base)


# ── Currency: what the user picks is what is stored ───────────────────────


@pytest.mark.parametrize("picked", ["BRL", "usd", " gbp ", "JPY", "PLN"])
def test_picked_currency_is_kept_not_replaced_by_eur(picked):
    assert _deal(currency=picked).currency == picked.strip().upper()
    assert LeadConvertRequest(title="x", currency=picked).currency == picked.strip().upper()


def test_blank_currency_stays_blank():
    assert _deal().currency == ""
    assert normalize_currency(None) == ""
    assert OpportunityUpdate().currency is None


@pytest.mark.parametrize("bad", ["EURO", "E1", "12", "€"])
def test_currency_must_be_iso_shape(bad):
    with pytest.raises(ValidationError):
        _deal(currency=bad)
    with pytest.raises(ValidationError):
        OpportunityUpdate(currency=bad)


# ── Trade show source ─────────────────────────────────────────────────────


def test_trade_show_source_accepted_everywhere_and_unknown_rejected():
    assert LeadCreate(contact_name="A", source="trade_show").source == "trade_show"
    assert _deal(source="trade_show").source == "trade_show"
    assert OpportunityUpdate(source="trade_show").source == "trade_show"
    with pytest.raises(ValidationError):
        LeadCreate(contact_name="A", source="billboard")


# ── Worked examples: reports ──────────────────────────────────────────────


def test_revenue_by_month_worked_example():
    opps = [
        SimpleNamespace(
            status="open",
            estimated_value=Decimal("10000"),
            probability_percent=50,
            weighted_value=Decimal("5000"),
            currency="USD",
            expected_close_date="2026-03-15",
        ),
        SimpleNamespace(
            status="open",
            estimated_value=Decimal("2000"),
            probability_percent=25,
            weighted_value=Decimal("500"),
            currency="USD",
            expected_close_date="2026-03-01",
        ),
        SimpleNamespace(
            status="open",
            estimated_value=Decimal("4000"),
            probability_percent=100,
            weighted_value=Decimal("4000"),
            currency="EUR",
            expected_close_date="2026-04-10",
        ),
        SimpleNamespace(
            status="open",
            estimated_value=Decimal("1000"),
            probability_percent=10,
            weighted_value=Decimal("100"),
            currency="USD",
            expected_close_date=None,
        ),
        SimpleNamespace(
            status="won",
            estimated_value=Decimal("9999"),
            probability_percent=100,
            weighted_value=Decimal("9999"),
            currency="USD",
            expected_close_date="2026-03-20",
        ),
    ]
    out = compute_revenue_by_month(opps)
    assert [(r["month"], r["currency"], r["expected"], r["deals"]) for r in out["rows"]] == [
        ("2026-03", "USD", Decimal("5500.00"), 2),
        ("2026-04", "EUR", Decimal("4000.00"), 1),
        ("", "USD", Decimal("100.00"), 1),
    ]
    assert out["mixed_currency"] is True


def test_owner_activity_summary_worked_example():
    rows = summarize_owner_activities(
        [
            ("u1", "call", 3),
            ("u1", "meeting", 1),
            ("u1", "note", 5),
            ("u2", "email", 4),
            ("u2", "call", 1),
        ]
    )
    assert rows[0] == {
        "owner_user_id": "u1",
        "calls": 3,
        "meetings": 1,
        "emails": 0,
        "site_visits": 0,
        "total": 9,
    }
    assert rows[1]["owner_user_id"] == "u2"
    assert (rows[1]["calls"], rows[1]["emails"], rows[1]["total"]) == (1, 4, 5)


def test_period_must_be_ordered():
    check_period(date(2026, 1, 1), date(2026, 1, 1))
    check_period(None, date(2026, 1, 1))
    with pytest.raises(ValueError, match="crm.period_ordered"):
        check_period(date(2026, 2, 1), date(2026, 1, 1))


# ── Database flows ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def _schema():
    from app.modules.contacts.models import Contact
    from app.modules.crm.models import AccountContact, Opportunity, OpportunityStageHistory
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    tables = (Contact, AccountContact, CrmActivity, OpportunityStageHistory, Opportunity, Lead, PipelineStage, Account)
    await create_module_tables(User, Project, *tables)
    return tables


@pytest_asyncio.fixture
async def session(_schema):
    from app.database import async_session_factory

    await clear_module_tables(_schema)
    async with async_session_factory() as sess:
        yield sess
        await sess.rollback()


async def _contact(session, first="Ada", last="Lovelace", email=None):
    from app.modules.contacts.models import Contact

    c = Contact(contact_type="client", first_name=first, last_name=last, primary_email=email)
    session.add(c)
    await session.flush()
    return c


@pytest.mark.asyncio
async def test_account_lists_its_contacts_and_first_is_primary(session):
    svc = CrmService(session)
    acc = Account(name="Acme")
    session.add(acc)
    await session.flush()
    c1 = await _contact(session, "Ada", "Lovelace", "ada@example.com")
    c2 = await _contact(session, "Bob", "Builder")

    rows = await svc.link_account_contact(acc.id, c1.id, role="buyer")
    assert [r["display_name"] for r in rows] == ["Ada Lovelace"]
    assert rows[0]["is_primary"] is True
    assert (await svc.get_account(acc.id)).primary_contact_id == c1.id

    rows = await svc.link_account_contact(acc.id, c2.id, is_primary=True)
    assert [r["contact_id"] for r in rows] == [c2.id, c1.id]
    assert [r["is_primary"] for r in rows] == [True, False]

    rows = await svc.link_account_contact(acc.id, c1.id, is_primary=True)
    assert [r["contact_id"] for r in rows] == [c1.id, c2.id]
    assert (await svc.get_account(acc.id)).primary_contact_id == c1.id


@pytest.mark.asyncio
async def test_contact_links_once_and_must_exist(session):
    svc = CrmService(session)
    acc = Account(name="Acme")
    session.add(acc)
    await session.flush()
    c = await _contact(session)
    await svc.link_account_contact(acc.id, c.id)
    with pytest.raises(HTTPException) as dup:
        await svc.link_account_contact(acc.id, c.id)
    assert dup.value.status_code == 409
    import uuid

    with pytest.raises(HTTPException) as missing:
        await svc.link_account_contact(acc.id, uuid.uuid4())
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_unlinking_primary_clears_account_primary(session):
    svc = CrmService(session)
    acc = Account(name="Acme")
    session.add(acc)
    await session.flush()
    c = await _contact(session)
    await svc.link_account_contact(acc.id, c.id)
    await svc.unlink_account_contact(acc.id, c.id)
    assert await svc.list_account_contacts(acc.id) == []
    assert (await svc.get_account(acc.id)).primary_contact_id is None


@pytest.mark.asyncio
async def test_lead_converts_with_lead_account_first_open_stage_and_picked_currency(session):
    svc = CrmService(session)
    session.add(PipelineStage(code="lead_in", name="In", display_order=0))
    session.add(PipelineStage(code="won", name="Won", display_order=9, is_final=True, is_won=True))
    acc = Account(name="Acme")
    session.add(acc)
    await session.flush()
    lead = Lead(contact_name="Zed", account_id=acc.id, status="qualified", source="trade_show")
    session.add(lead)
    await session.flush()

    _, opp = await svc.convert_lead(lead.id, LeadConvertRequest(title="Zed deal", currency="brl"))
    assert opp.account_id == acc.id
    assert opp.currency == "BRL"
    assert opp.source == "trade_show"
    stage = await svc.stage_repo.get_by_id(opp.stage_id)
    assert stage.code == "lead_in"


@pytest.mark.asyncio
async def test_lead_without_any_account_is_refused(session):
    svc = CrmService(session)
    session.add(PipelineStage(code="lead_in", name="In", display_order=0))
    lead = Lead(contact_name="Zed", status="qualified")
    session.add(lead)
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await svc.convert_lead(lead.id, LeadConvertRequest(title="x"))
    assert exc.value.status_code == 400
    assert "crm.convert_needs_account" in exc.value.detail


@pytest.mark.asyncio
async def test_activity_summary_counts_only_the_period(session):
    from datetime import UTC, datetime

    svc = CrmService(session)
    import uuid

    owner = None
    inside = CrmActivity(owner_user_id=owner, kind="call", subject="a")
    inside.created_at = datetime(2026, 3, 10, 12, tzinfo=UTC)
    outside = CrmActivity(owner_user_id=owner, kind="call", subject="b")
    outside.created_at = datetime(2026, 5, 1, 12, tzinfo=UTC)
    email = CrmActivity(owner_user_id=owner, kind="email", subject="c")
    email.created_at = datetime(2026, 3, 31, 23, 30, tzinfo=UTC)
    session.add_all([inside, outside, email])
    await session.flush()
    del uuid

    rows = await svc.owner_activity_summary(date(2026, 3, 1), date(2026, 3, 31))
    assert len(rows) == 1
    assert (rows[0]["calls"], rows[0]["emails"], rows[0]["total"]) == (1, 1, 2)
    with pytest.raises(HTTPException) as exc:
        await svc.owner_activity_summary(date(2026, 4, 1), date(2026, 3, 1))
    assert exc.value.status_code == 400
