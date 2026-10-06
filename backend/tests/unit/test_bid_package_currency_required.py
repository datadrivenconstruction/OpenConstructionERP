"""An unlabelled tender must never become a valid monetary competition."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.modules.bid_management.models import BidAward, BidPackage
from app.modules.bid_management.schemas import BidAwardCreate, BidPackageCreate, BidPackageUpdate
from app.modules.bid_management.service import BidManagementService, validate_submission_pre_open
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest.mark.parametrize("currency", [None, "", " ", "\t\n"])
def test_create_and_explicit_update_refuse_blank_currency(currency):
    with pytest.raises(ValidationError):
        BidPackageCreate(project_id=uuid.uuid4(), code="CURRENCY", currency=currency)
    with pytest.raises(ValidationError):
        BidPackageUpdate(currency=currency)


def test_create_requires_currency_but_an_unrelated_patch_does_not():
    with pytest.raises(ValidationError):
        BidPackageCreate(project_id=uuid.uuid4(), code="CURRENCY")
    assert "currency" not in BidPackageUpdate(title="New title").model_dump(exclude_unset=True)


def test_currency_labels_are_normalized_before_storage():
    assert BidPackageCreate(project_id=uuid.uuid4(), code="CURRENCY", currency=" eur ").currency == "EUR"
    assert BidPackageUpdate(currency=" jpy ").currency == "JPY"


@pytest.mark.parametrize(
    "package_currency,submission_currency",
    [
        ("", "EUR"),
        ("EUR", ""),
        ("", ""),
        (" \t", "EUR"),
        (None, "EUR"),
        ("EUR", None),
    ],
)
def test_missing_currency_never_passes_opening(package_currency, submission_currency):
    valid, errors = validate_submission_pre_open(
        SimpleNamespace(currency=submission_currency),
        SimpleNamespace(currency=package_currency),
        [SimpleNamespace(line_item_id=uuid.uuid4(), total_price="100", unit_price="100", quantity_priced="1")],
        [],
        now=datetime.now(UTC),
    )
    assert valid is False
    assert errors == ["currency_mismatch"]


def test_opening_accepts_equivalent_trimmed_currency_labels():
    valid, errors = validate_submission_pre_open(
        SimpleNamespace(currency=" eur "),
        SimpleNamespace(currency="EUR"),
        [SimpleNamespace(line_item_id=uuid.uuid4(), total_price="100", unit_price="100", quantity_priced="1")],
        [],
        now=datetime.now(UTC),
    )
    assert valid is True
    assert errors == []


@pytest_asyncio.fixture
async def legacy_package():
    from tests._pg import transactional_session

    async with transactional_session() as session:
        owner = User(email=f"currency-{uuid.uuid4().hex}@example.test", hashed_password="x", full_name="Owner")
        session.add(owner)
        await session.flush()
        project = Project(name="Currency", owner_id=owner.id)
        session.add(project)
        await session.flush()
        package = BidPackage(project_id=project.id, code=uuid.uuid4().hex, currency="", status="draft")
        session.add(package)
        await session.flush()
        yield session, package


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,state", [("publish", "draft"), ("open", "published"), ("open", "open"), ("award", "closed")]
)
async def test_legacy_unlabelled_package_cannot_progress(legacy_package, operation, state):
    session, package = legacy_package
    package.status = state
    await session.flush()
    service = BidManagementService(session)
    if operation == "publish":
        action = service.publish_package(package.id)
    elif operation == "open":
        action = service.open_bids(package.id)
    else:
        action = service.award_package(
            package.id,
            BidAwardCreate(package_id=package.id, awarded_bidder_id=uuid.uuid4(), awarded_amount="100"),
        )
    with pytest.raises(HTTPException) as exc:
        await action
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "bid_package_currency_required"
    await session.refresh(package)
    assert package.status == state
    assert package.currency == ""
    assert await session.scalar(select(func.count()).select_from(BidAward)) == 0


@pytest.mark.asyncio
async def test_legacy_currency_can_be_repaired_before_publish(legacy_package, monkeypatch):
    from app.modules.bid_management import service as module

    session, package = legacy_package
    monkeypatch.setattr(module.event_bus, "publish_detached", lambda *a, **kw: None)
    service = BidManagementService(session)
    repaired = await service.update_package(package.id, BidPackageUpdate(currency=" eur "))
    assert repaired.currency == "EUR"
    published = await service.publish_package(package.id)
    await session.refresh(published)
    assert (published.status, published.currency) == ("published", "EUR")


@pytest.mark.asyncio
async def test_internal_create_cannot_bypass_currency_validation(legacy_package):
    session, package = legacy_package
    data = BidPackageCreate.model_construct(project_id=package.project_id, code="UNLABELLED", currency=" ")
    service = BidManagementService(session)
    with pytest.raises(HTTPException) as exc:
        await service.create_package(data)
    assert exc.value.detail["code"] == "bid_package_currency_required"
    assert await session.scalar(select(func.count()).select_from(BidPackage)) == 1


@pytest.mark.asyncio
async def test_internal_patch_cannot_erase_the_currency(legacy_package):
    session, package = legacy_package
    package.currency = "EUR"
    await session.flush()
    data = BidPackageUpdate.model_construct(currency=" ")
    with pytest.raises(HTTPException) as exc:
        await BidManagementService(session).update_package(package.id, data)
    assert exc.value.detail["code"] == "bid_package_currency_required"
    await session.refresh(package)
    assert package.currency == "EUR"
