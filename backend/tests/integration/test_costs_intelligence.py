"""‌⁠‍Integration tests for the v3.12.0 Cost Intelligence endpoints.

Covers (end-to-end through the FastAPI router):
    - ``GET /v1/costs/regional-adjust`` math + the passthrough fallback
      when no index row exists.
    - ``GET /v1/costs/{id}/certainty`` thresholds at the boundaries:
      green / yellow / red rules per ``classify_certainty``.
    - ``POST /v1/costs/{id}/record-usage`` writes the ledger and the
      next certainty fetch reflects the increment.
    - ``GET /v1/costs/regional-indices`` lists every row for a region.
    - 404 paths for unknown cost item.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

# The engine is bound to PostgreSQL by conftest before this module imports.
# Skip the auto-seed so the test fixture controls every row.
os.environ.setdefault("SEED_SHOWCASE", "false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module and seed deterministic rows."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, async_session_factory, engine
        from app.modules.costs import models as _costs_models  # noqa: F401
        from app.modules.costs.models import CostItem, CostItemUsage, RegionalIndex

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with async_session_factory() as s:
            # Two cost items so we can pin certainty per-item.
            item_busy = CostItem(
                id=uuid.uuid4(),
                code="INTEL-BUSY",
                description="High-usage concrete C30/37 wall",
                unit="m3",
                rate="120.00",
                currency="EUR",
                source="cwicr",
                classification={"collection": "Concrete"},
                components=[],
                tags=[],
                region="DE_BERLIN",
                is_active=True,
                metadata_={},
            )
            item_idle = CostItem(
                id=uuid.uuid4(),
                code="INTEL-IDLE",
                description="Untouched rebar grade B500B",
                unit="kg",
                rate="1.50",
                currency="EUR",
                source="manual",
                classification={"collection": "Steel"},
                components=[],
                tags=[],
                region="DE_BERLIN",
                is_active=True,
                metadata_={},
            )
            s.add_all([item_busy, item_idle])

            # Regional matrix: use synthetic region codes the production
            # auto-seed (``seed_regional_indices.main``) does NOT touch
            # so the test is fully decoupled from the boot pipeline.
            # Real city codes are exercised by the e2e manual checks in
            # the release plan.
            seed_date = date(2026, 5, 1)
            for region, factor in (
                ("TEST_BERLIN", "1.0"),
                ("TEST_MUNICH", "1.12"),
                ("TEST_NYC", "1.45"),
            ):
                s.add(
                    RegionalIndex(
                        region_code=region,
                        category="concrete",
                        subcategory=None,
                        factor=Decimal(factor),
                        source="OE_v3.12_test",
                        effective_date=seed_date,
                    )
                )

            # 10 fresh usage rows for the BUSY item → green band.
            now = datetime.now(UTC)
            project_id = uuid.uuid4()
            for i in range(10):
                s.add(
                    CostItemUsage(
                        cost_item_id=item_busy.id,
                        project_id=project_id,
                        used_at=now - timedelta(days=i * 7),
                        unit_rate_at_use=Decimal("120.00"),
                        context="boq",
                    )
                )

            await s.commit()

            # Expose the seeded ids on the app for the test functions.
            app.state.test_item_busy_id = str(item_busy.id)
            app.state.test_item_idle_id = str(item_idle.id)
            app.state.test_project_id = str(project_id)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Regional adjust ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regional_adjust_applies_munich_factor(http_client):
    """TEST_MUNICH factor 1.12 — 100 € → 112 €.

    Round-7 (2026-05-24): money/factor fields surface as Decimal strings
    on the wire so JSON's float bridge never silently rounds a
    precision-critical value. Decoders cast via ``Decimal(str)`` for
    exact comparison.
    """
    resp = await http_client.get(
        "/api/v1/costs/regional-adjust/",
        params={"region": "TEST_MUNICH", "category": "concrete", "base_rate": "100.00"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["region"] == "TEST_MUNICH"
    assert body["category"] == "concrete"
    assert Decimal(body["factor_applied"]) == Decimal("1.12")
    assert Decimal(body["adjusted_rate"]) == Decimal("112.0000")
    assert body["source"] == "OE_v3.12_test"
    assert body["effective_date"] == "2026-05-01"


@pytest.mark.asyncio
async def test_regional_adjust_unknown_region_passthrough(http_client):
    """Unknown region → factor 1, source ``baseline``, no effective_date.

    Round-7 contract: factor/base_rate/adjusted_rate are Decimal
    strings.
    """
    resp = await http_client.get(
        "/api/v1/costs/regional-adjust/",
        params={"region": "ZZ_NOWHERE", "category": "concrete", "base_rate": "250.00"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["factor_applied"]) == Decimal("1")
    assert Decimal(body["adjusted_rate"]) == Decimal("250.00")
    assert body["source"] == "baseline"
    assert body["effective_date"] is None


@pytest.mark.asyncio
async def test_regional_indices_list_for_region(http_client):
    """``GET /regional-indices?region=TEST_BERLIN`` returns the Berlin rows."""
    resp = await http_client.get(
        "/api/v1/costs/regional-indices/",
        params={"region": "TEST_BERLIN"},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert isinstance(items, list)
    assert any(row["category"] == "concrete" for row in items)
    for row in items:
        assert row["region_code"] == "TEST_BERLIN"


# ── Certainty badge ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_certainty_green_for_busy_item(http_client, app_instance):
    """10 fresh uses → green band, frequency=10, low age."""
    item_id = app_instance.state.test_item_busy_id
    resp = await http_client.get(f"/api/v1/costs/{item_id}/certainty/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["frequency"] == 10
    assert body["age_days"] < 365
    assert body["confidence_badge"] == "green"
    assert body["last_used_at"] is not None
    assert body["source"] == "cwicr"


@pytest.mark.asyncio
async def test_certainty_red_for_unused_item(http_client, app_instance):
    """Zero recorded uses → red band, sentinel age."""
    item_id = app_instance.state.test_item_idle_id
    resp = await http_client.get(f"/api/v1/costs/{item_id}/certainty/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["frequency"] == 0
    assert body["confidence_badge"] == "red"
    assert body["last_used_at"] is None


@pytest.mark.asyncio
async def test_certainty_unknown_item_404(http_client):
    bogus = uuid.uuid4()
    resp = await http_client.get(f"/api/v1/costs/{bogus}/certainty/")
    assert resp.status_code == 404, resp.text


# ── Record usage ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_usage_increments_frequency(http_client, app_instance):
    """POST record-usage on the IDLE item must bump frequency to ≥ 1."""
    item_id = app_instance.state.test_item_idle_id
    project_id = app_instance.state.test_project_id

    resp = await http_client.post(
        f"/api/v1/costs/{item_id}/record-usage/",
        json={
            "project_id": project_id,
            "context": "boq",
            "unit_rate_at_use": 1.50,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["certainty"]["frequency"] >= 1
    # A single fresh use is "in use" - reassuring yellow, not alarming red -
    # and last_used_at is now populated.
    assert body["certainty"]["confidence_badge"] == "yellow"
    assert body["certainty"]["last_used_at"] is not None

    # Re-fetch via GET — must reflect the just-logged row.
    follow = await http_client.get(f"/api/v1/costs/{item_id}/certainty/")
    assert follow.status_code == 200
    follow_body = follow.json()
    assert follow_body["frequency"] >= 1


@pytest.mark.asyncio
async def test_record_usage_unknown_item_404(http_client):
    bogus = uuid.uuid4()
    resp = await http_client.post(
        f"/api/v1/costs/{bogus}/record-usage/",
        json={
            "project_id": str(uuid.uuid4()),
            "context": "boq",
            "unit_rate_at_use": 0.0,
        },
    )
    assert resp.status_code == 404, resp.text


# ── Classifier unit boundaries ─────────────────────────────────────────────


def test_classify_certainty_boundary_cases():
    """Pin the green / yellow / red rules at every boundary."""
    from app.modules.costs.intelligence import (
        NEVER_USED_AGE_DAYS,
        classify_certainty,
    )

    # Green floor: exactly 10 uses, just under 365 days old.
    assert classify_certainty(10, 364) == "green"
    # Just under green frequency threshold, recent → yellow.
    assert classify_certainty(9, 100) == "yellow"
    # Green frequency, but stale → yellow (age in [365, 1095]).
    assert classify_certainty(50, 365) == "yellow"
    assert classify_certainty(50, 1095) == "yellow"
    # A single fresh use must NOT be red - reassuring yellow instead.
    assert classify_certainty(1, 0) == "yellow"
    assert classify_certainty(1, 100) == "yellow"
    # A low, recent count is in use, so yellow (was red under the old rule).
    assert classify_certainty(2, 100) == "yellow"
    # Never used → red regardless of age input.
    assert classify_certainty(0, NEVER_USED_AGE_DAYS) == "red"
    assert classify_certainty(0, 0) == "red"
    # Used once but evidence gone stale (past the yellow max age) → red.
    assert classify_certainty(1, 1096) == "red"
    # Very stale even with high frequency → red.
    assert classify_certainty(100, 1500) == "red"
