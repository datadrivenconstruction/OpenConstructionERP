"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An Ontario holdback is not released before the lien period has run.

The Construction Act keeps the holdback until 60 days after the certificate of
substantial performance is published. The figure sat in the country defaults
and was shown on the contract, yet a release could be approved the day the
certificate was signed. This walks one Ontario contract through the release
gate on PostgreSQL: the preview names the period, a release without its start
date or inside the period is refused, and the same release goes through once
the period has run.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import Contract, ContractDocument, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
PERIOD_RULE = "retention_release.release_period_elapsed"


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"on-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


@pytest_asyncio.fixture
async def contract(session) -> SimpleNamespace:
    project = Project(
        id=uuid.uuid4(),
        name="Ontario holdback",
        owner_id=OWNER_ID,
        currency="CAD",
        country_code="CA",
        subdivision_code="CA-ON",
    )
    session.add(project)
    await session.flush()
    row = Contract(
        id=uuid.uuid4(),
        code=f"ON-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="CAD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(row)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=row.id,
        code="A",
        description="Works",
        quantity=Decimal("1"),
        unit_rate=Decimal("100000"),
        total_value=Decimal("100000"),
        order_index=0,
    )
    session.add(line)
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=row.id,
        claim_number="PC-1",
        period_start="2026-08-01",
        period_end="2026-08-28",
        period_from=date(2026, 8, 1),
        period_to=date(2026, 8, 28),
        currency="CAD",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    svc = ContractsService(session)
    await svc.auto_generate_claim_lines(claim.id, AutoGenerateClaimRequest(completion={str(line.id): Decimal("100")}))
    await svc.claim_repo.update_fields(claim.id, status="approved")
    return SimpleNamespace(row=row, svc=svc)


def _request(**extra):
    return SimpleNamespace(
        event="substantial_completion",
        amount=None,
        open_items_value=Decimal("0"),
        document_ids=[],
        released_on=None,
        notes=None,
        period_started_on=extra.get("period_started_on"),
    )


async def _evidence(session, contract, roles: list[str]) -> list[uuid.UUID]:
    ids = []
    for role in roles:
        doc = ContractDocument(contract_id=contract.row.id, doc_role=role, title=role)
        session.add(doc)
        await session.flush()
        ids.append(doc.id)
    return ids


async def _refused_by(svc: ContractsService, release_id, data) -> list[str]:
    with pytest.raises(HTTPException) as refused:
        await svc.approve_retention_release(release_id, data, "pm")
    assert refused.value.status_code == 422
    return [f["rule_id"] for f in refused.value.detail["errors"]]


async def test_the_holdback_waits_for_the_lien_period_after_publication(session, contract) -> None:
    svc = contract.svc
    preview = await svc.preview_retention_release(contract.row.id, _request())
    assert preview["release_period_days"] == 60
    assert "Construction Act" in (preview["release_period_reference"] or "")
    docs = await _evidence(session, contract, preview["required_documents"])

    release = await svc.create_retention_release(contract.row.id, _request(), "qs")
    assert release.metadata_["release_period_days"] == 60

    # No publication date: held, and only for that.
    assert await _refused_by(svc, release.id, SimpleNamespace(document_ids=docs)) == [PERIOD_RULE]

    # Published ten days ago: still inside the 60 days.
    recent = date.today() - timedelta(days=10)
    assert await _refused_by(svc, release.id, SimpleNamespace(document_ids=docs, period_started_on=recent)) == [
        PERIOD_RULE
    ]
    await session.refresh(release)
    assert release.metadata_["earliest_release_on"] == (recent + timedelta(days=60)).isoformat()

    # Published sixty days ago: the period has run on this day.
    published = date.today() - timedelta(days=60)
    approved = await svc.approve_retention_release(
        release.id, SimpleNamespace(document_ids=docs, period_started_on=published), "pm"
    )
    assert approved.status == "approved"
    assert approved.metadata_["period_started_on"] == published.isoformat()


async def test_a_release_proposed_with_its_publication_date_passes_once_it_has_run(session, contract) -> None:
    svc = contract.svc
    preview = await svc.preview_retention_release(contract.row.id, _request())
    docs = await _evidence(session, contract, preview["required_documents"])
    published = date.today() - timedelta(days=75)
    release = await svc.create_retention_release(contract.row.id, _request(period_started_on=published), "qs")
    assert release.metadata_["earliest_release_on"] == (published + timedelta(days=60)).isoformat()
    approved = await svc.approve_retention_release(release.id, SimpleNamespace(document_ids=docs), "pm")
    assert approved.status == "approved"
