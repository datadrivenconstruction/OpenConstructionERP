"""Cost benchmarks against the database: tenant scope, demo cohort, outliers, rules, export."""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cost_benchmarks.demo import seed_cost_benchmarks_demo
from app.modules.cost_benchmarks.models import BenchmarkRecord
from app.modules.cost_benchmarks.service import CostBenchmarksService
from app.modules.cost_benchmarks.validators import evaluate
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _project(session: AsyncSession) -> tuple[uuid.UUID, str]:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"cb-{uuid.uuid4().hex[:10]}@bench.io",
        hashed_password="x",
        full_name="Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Quayside Depot", owner_id=owner.id, currency="EUR", fx_rates=[])
    session.add(project)
    await session.flush()
    return project.id, str(owner.id)


async def _fx(session: AsyncSession) -> None:
    from app.modules.fx.models import FxRateQuote, FxRateSet

    rs = FxRateSet(base_currency="EUR", rate_date=date(2026, 1, 2))
    rs.quotes = [FxRateQuote(currency="GBP", rate=Decimal("0.85")), FxRateQuote(currency="USD", rate=Decimal("1.10"))]
    session.add(rs)
    await session.flush()


async def _compare(service: CostBenchmarksService, estimate_id: uuid.UUID, **kw) -> dict:
    return await service.compare(
        estimate_id=estimate_id,
        filters={"project_type": "office"},
        base_date=date(2026, 6, 1),
        base_region=None,
        reporting_currency="EUR",
        **kw,
    )


async def test_demo_cohort_flags_two_outliers_and_stays_in_its_tenant(session: AsyncSession) -> None:
    pid, tenant = await _project(session)
    await _fx(session)
    counts = await seed_cost_benchmarks_demo(session, [pid])
    assert counts["synthetic"] == 6
    assert counts["estimates"] == 1
    again = await seed_cost_benchmarks_demo(session, [pid])
    assert again["synthetic"] == 0

    service = CostBenchmarksService(session, tenant)
    estimate = (await service.list_records(kind="estimate"))[0]
    result = await _compare(service, estimate.id)
    assert result["cohort"]["count"] == 6
    assert result["cohort"]["source"] == "own"
    outliers = {e["code"]: e["position"] for e in result["elements"] if e["position"] in ("above", "below")}
    assert outliers == {"330": "above", "420": "below"}
    findings = await evaluate(result)
    ids = {f.rule_id for f in findings}
    assert "cost_benchmarks.element_outside_band" in ids
    assert "cost_benchmarks.low_confidence_cohort" not in ids

    assert await CostBenchmarksService(session, "other-tenant").list_records() == []
    assert await CostBenchmarksService(session, None).list_records() == []


async def test_low_confidence_falls_back_to_the_reference_band(session: AsyncSession) -> None:
    _pid, tenant = await _project(session)
    service = CostBenchmarksService(session, tenant)
    est = await service.create(
        {
            "kind": "estimate",
            "name": "Lonely flat block",
            "project_type": "residential",
            "currency": "EUR",
            "cost_date": date(2026, 5, 1),
            "standard": "din276",
            "gfa_m2": Decimal("1000"),
            "elements": [{"code": "330", "amount": Decimal("900000")}],
        }
    )
    result = await _compare(service, est.id)
    assert result["cohort"]["low_confidence"] is True
    assert result["cohort"]["source"] == "reference"
    wall = next(e for e in result["elements"] if e["code"] == "330")
    assert wall["band_source"] == "reference"
    assert wall["position"] == "above"
    ids = {f.rule_id for f in await evaluate(result)}
    assert "cost_benchmarks.low_confidence_cohort" in ids


async def test_missing_gfa_rule_and_anonymised_export(session: AsyncSession) -> None:
    pid, tenant = await _project(session)
    await seed_cost_benchmarks_demo(session, [pid])
    service = CostBenchmarksService(session, tenant)
    est = await service.create(
        {
            "kind": "estimate",
            "name": "No area",
            "project_type": "office",
            "currency": "EUR",
            "cost_date": date(2026, 5, 1),
            "elements": [{"code": "330", "amount": Decimal("1")}],
        }
    )
    ids = {f.rule_id for f in await evaluate(await _compare(service, est.id))}
    assert "cost_benchmarks.missing_quantity" in ids

    basis, _ = await service.basis(base_date=date(2026, 6, 1), base_region=None, reporting_currency="EUR")
    content, media = await service.anonymised_export(basis=basis)
    data = json.loads(content)
    assert media == "application/json"
    assert data["records"]
    text = content.lower()
    assert "riverside" not in text
    assert "quayside" not in text
    names = (await session.execute(select(BenchmarkRecord.name).where(BenchmarkRecord.tenant_id == tenant))).scalars()
    assert all(n.lower() not in text for n in names)
