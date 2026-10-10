# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Ledger admission must preserve balance through PostgreSQL's amount scale."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text

from app.modules.finance.schemas import JournalEntryCreate, JournalLineInput
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as session:
        yield session


@pytest_asyncio.fixture
async def project(session):
    owner = User(
        id=uuid.uuid4(),
        email=f"journal-precision-{uuid.uuid4().hex}@test.invalid",
        hashed_password="x",
    )
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Journal precision",
        owner_id=owner.id,
        currency="KWD",
        country_code="KW",
    )
    session.add(project)
    await session.flush()
    return project


async def _stored_rows(session, reference):
    return (
        (
            await session.execute(
                text(
                    "SELECT id, debit_amount, credit_amount FROM oe_finance_ledger "
                    "WHERE transaction_ref=:reference ORDER BY id"
                ),
                {"reference": reference},
            )
        )
        .mappings()
        .all()
    )


async def test_kwd_milliunit_imbalance_is_rejected_without_persisting_rows(session, project):
    data = JournalEntryCreate(
        project_id=project.id,
        transaction_ref=f"QA-{uuid.uuid4().hex}",
        currency_code="KWD",
        lines=[
            JournalLineInput(account_code="1000", debit="1.001"),
            JournalLineInput(account_code="4000", credit="1.002"),
        ],
    )

    with pytest.raises(HTTPException) as error:
        await FinanceService(session).post_journal_entry(data)

    assert error.value.status_code == 400
    assert "Unbalanced" in error.value.detail
    assert await _stored_rows(session, data.transaction_ref) == []


async def test_balanced_split_milliunits_are_rejected_before_storage_rounding(session, project):
    # Exact input balance does not suffice: Numeric(18,2) would store two
    # debits of 0.01 against a single credit of 0.01.
    data = JournalEntryCreate(
        project_id=project.id,
        transaction_ref=f"QA-{uuid.uuid4().hex}",
        currency_code="KWD",
        lines=[
            JournalLineInput(account_code="1000", debit="0.005"),
            JournalLineInput(account_code="1010", debit="0.005"),
            JournalLineInput(account_code="4000", credit="0.010"),
        ],
    )

    with pytest.raises(HTTPException) as error:
        await FinanceService(session).post_journal_entry(data)

    assert error.value.status_code == 400
    assert "precision" in error.value.detail.lower()
    assert await _stored_rows(session, data.transaction_ref) == []


async def test_representable_kwd_trailing_zeros_roundtrip_and_replay_without_duplicates(session, project):
    data = JournalEntryCreate(
        project_id=project.id,
        transaction_ref=f"QA-{uuid.uuid4().hex}",
        currency_code="KWD",
        lines=[
            JournalLineInput(account_code="1000", debit="1.000"),
            JournalLineInput(account_code="4000", credit="1.0"),
        ],
    )
    service = FinanceService(session)
    rows, debit, credit = await service.post_journal_entry(data)
    original_ids = {str(row.id) for row in rows}
    assert len(original_ids) == 2
    assert debit == credit == Decimal("1")

    stored = await _stored_rows(session, data.transaction_ref)
    assert {str(row["id"]) for row in stored} == original_ids
    assert sum((row["debit_amount"] for row in stored), Decimal("0")) == Decimal("1")
    assert sum((row["credit_amount"] for row in stored), Decimal("0")) == Decimal("1")

    session.expunge_all()
    replay, replay_debit, replay_credit = await service.post_journal_entry(data)
    assert {str(row.id) for row in replay} == original_ids
    assert replay_debit == replay_credit == Decimal("1")
    assert list(await _stored_rows(session, data.transaction_ref)) == list(stored)
