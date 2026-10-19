# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The VAT regimes a contract on an Egyptian project is offered, priced from the stored tax table.

The rate of each regime is read from the tax table the install holds, not
from the regime data, so a tenant who corrects a row sees the regime follow.
The dates either side of 2025-07-18 decide which regimes are offered at all.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.contracts.service import ContractsService
from app.modules.i18n_foundation.seed import load_tax_seed_rows, tax_configuration_from_seed_row
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _project(session, country: str | None, *, seed: bool = True) -> uuid.UUID:
    if seed:
        for row in load_tax_seed_rows():
            if row["country_code"] == "EG":
                session.add(tax_configuration_from_seed_row(row))
    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"regime-{tag}@example.test", hashed_password="x", full_name="Regime")
    session.add(owner)
    await session.flush()
    project = Project(name=f"Regimes {tag}", owner_id=owner.id, currency="EGP", country_code=country)
    session.add(project)
    await session.flush()
    return project.id


async def _offered(session, project_id: uuid.UUID, on: date) -> dict[str, tuple[Decimal | None, Decimal | None, bool]]:
    answer = await ContractsService(session).vat_regimes_for_project(project_id, on)
    return {
        regime["code"]: (regime["nominal_rate_pct"], regime["effective_rate_pct"], regime["input_credit"])
        for regime in answer["regimes"]
    }


async def test_after_the_cutoff_the_standard_and_the_transitional_regime_are_offered(pg_session) -> None:
    project_id = await _project(pg_session, "EG")
    offered = await _offered(pg_session, project_id, date(2026, 10, 19))
    assert offered == {
        "EG_CONSTR_STANDARD": (Decimal("14.0"), Decimal("14.0"), True),
        "EG_CONSTR_TRANSITIONAL_36": (Decimal("14.0"), Decimal("5.040"), False),
    }


async def test_before_the_cutoff_only_the_schedule_tax_is_offered(pg_session) -> None:
    project_id = await _project(pg_session, "EG")
    offered = await _offered(pg_session, project_id, date(2025, 7, 17))
    assert offered == {"EG_CONSTR_SCHEDULE_5": (Decimal("5.0"), Decimal("5.0"), False)}


async def test_the_transitional_conditions_travel_as_data(pg_session) -> None:
    project_id = await _project(pg_session, "EG")
    answer = await ContractsService(pg_session).vat_regimes_for_project(project_id, date(2026, 10, 19))
    transitional = next(r for r in answer["regimes"] if r["code"] == "EG_CONSTR_TRANSITIONAL_36")
    assert transitional["contract_signed_before"] == date(2025, 7, 18)
    assert transitional["required_evidence"] == ["approved_certificate", "einvoice"]
    assert transitional["subcontract_evidence"] == ["main_contractor_certificate"]
    assert transitional["scope_increase_ends_regime"] is True


async def test_an_install_without_the_tax_rows_offers_the_regimes_without_a_rate(pg_session) -> None:
    project_id = await _project(pg_session, "EG", seed=False)
    offered = await _offered(pg_session, project_id, date(2026, 10, 19))
    assert offered["EG_CONSTR_TRANSITIONAL_36"] == (None, None, False)


async def test_a_country_without_regimes_and_a_project_without_a_country_offer_none(pg_session) -> None:
    for country in ("DE", None):
        project_id = await _project(pg_session, country, seed=False)
        assert await _offered(pg_session, project_id, date(2026, 10, 19)) == {}
