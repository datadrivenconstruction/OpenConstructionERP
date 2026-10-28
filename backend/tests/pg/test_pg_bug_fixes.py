"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PostgreSQL regression tests for the confirmed dialect-divergence bugs.

Each test reproduces a query that worked on SQLite but crashed (or silently
returned wrong results) on PostgreSQL before the corresponding fix. They run
only in the PG lane (``OE_TEST_DB=pg``); the SQLite suite skips the directory.

Covered fixes:
* ``numeric_value`` tolerant text→float coercion (catalog + costs rate filters)
* ``costs.category_tree`` GROUP BY by expression, not output alias
* ``costs.search_for_autocomplete`` jsonb_array_length on a JSONB column
* ``audit._parse_iso`` returns tz-aware datetimes for TIMESTAMPTZ comparison
* ``AwareDateTime`` coerces ISO strings / naive datetimes at bind time
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


# ── numeric_value: non-numeric money strings must not abort the query ────────
async def test_catalog_price_filter_tolerates_nonnumeric(pg_session) -> None:
    from app.modules.catalog.models import CatalogResource
    from app.modules.catalog.repository import CatalogResourceRepository

    pg_session.add(
        CatalogResource(
            resource_code="PG-CAT-1",
            name="Bad price row",
            resource_type="material",
            category="concrete",
            unit="m2",
            base_price="N/A",  # would crash CAST(text AS double precision) on PG
            currency="EUR",
        )
    )
    await pg_session.flush()

    repo = CatalogResourceRepository(pg_session)
    # A bare cast(.., Float) raised "invalid input syntax" here on PG.
    items, total = await repo.search(min_price=0.0)
    assert isinstance(items, list)
    assert total >= 0


async def test_costs_rate_filter_tolerates_nonnumeric(pg_session) -> None:
    from app.modules.costs.models import CostItem
    from app.modules.costs.repository import CostItemRepository

    pg_session.add(CostItem(code="PG-RATE-1", description="bad rate", unit="m2", rate="N/A", currency="USD"))
    await pg_session.flush()

    repo = CostItemRepository(pg_session)
    items, _total, _more = await repo.search(min_rate=0.0)
    assert isinstance(items, list)


# ── category_tree: GROUP BY must reference the JSONB expression, not the alias ─
async def test_costs_category_tree_groups_by_expression(pg_session) -> None:
    from app.modules.costs.models import CostItem
    from app.modules.costs.repository import CostItemRepository

    pg_session.add_all(
        [
            CostItem(
                code="PG-TREE-1",
                description="x",
                unit="m2",
                rate="10",
                is_active=True,
                classification={"collection": "Alpha", "department": "Beta"},
            ),
            CostItem(
                code="PG-TREE-2",
                description="y",
                unit="m2",
                rate="20",
                is_active=True,
                classification={"collection": "Alpha", "department": "Gamma"},
            ),
        ]
    )
    await pg_session.flush()

    repo = CostItemRepository(pg_session)
    # GROUP BY *active_keys (string aliases) raised "column collection does
    # not exist" on PG; GROUP BY *active_exprs is correct.
    tree = await repo.category_tree(depth=2)
    assert any(node["name"] == "Alpha" for node in tree)


# ── autocomplete: JSONB column needs jsonb_array_length, not json_array_length ─
async def test_costs_autocomplete_uses_jsonb_array_length(pg_session) -> None:
    from app.modules.costs.models import CostItem
    from app.modules.costs.repository import CostItemRepository

    pg_session.add_all(
        [
            CostItem(code="PG-AC-0", description="no comp", unit="m2", rate="10", components=[]),
            CostItem(
                code="PG-AC-1",
                description="has comp",
                unit="m2",
                rate="10",
                components=[{"cost_item_id": "x", "factor": "1.0"}],
            ),
        ]
    )
    await pg_session.flush()

    repo = CostItemRepository(pg_session)
    # json_array_length(jsonb) does not exist on PG; jsonb_array_length does.
    results = await repo.search_for_autocomplete(q="PG-AC", limit=10)
    assert results, "autocomplete returned nothing"
    assert results[0].components, "item WITH components must sort first"


# ── audit: naive ISO filter must not crash a TIMESTAMPTZ comparison ──────────
async def test_audit_naive_date_filter_no_crash(pg_session) -> None:
    from app.core.audit import audit_log, get_audit_entries

    await audit_log(pg_session, action="create", entity_type="pg_test", entity_id=str(uuid.uuid4()))
    await pg_session.flush()

    # date_from has no offset → _parse_iso must attach UTC, else asyncpg rejects
    # binding a naive datetime to the TIMESTAMPTZ created_at column.
    results = await get_audit_entries(pg_session, date_from="2000-01-01T00:00:00")
    assert isinstance(results, list)


# ── AwareDateTime: loose inputs become tz-aware datetimes at bind time ───────
async def test_aware_datetime_coerces_loose_inputs() -> None:
    from app.core.db_types import AwareDateTime

    t = AwareDateTime()
    iso_z = t.process_bind_param("2026-05-30T00:00:00Z", None)
    assert isinstance(iso_z, datetime) and iso_z.tzinfo is not None

    iso_offset = t.process_bind_param("2026-05-30T00:00:00+05:30", None)
    assert isinstance(iso_offset, datetime) and iso_offset.tzinfo is not None

    naive = t.process_bind_param(datetime(2026, 5, 30, 10, 0, 0), None)
    assert isinstance(naive, datetime) and naive.tzinfo is not None

    assert t.process_bind_param(None, None) is None


# ── Probe: does asyncpg accept a str bound to a uuid column in raw SQL? ───────
# project_intelligence/collector.py issues raw text() queries that bind a string
# project_id against uuid columns. This documents whether that pattern is safe
# on asyncpg (it is the WHERE-clause counterpart of the GROUP_CONCAT fix).
async def test_raw_text_uuid_param_accepts_string(pg_session) -> None:
    from app.modules.costs.models import CostItem

    item = CostItem(code="PG-UUIDPROBE", description="x", unit="m2", rate="1")
    pg_session.add(item)
    await pg_session.flush()

    count = (
        await pg_session.execute(
            text("SELECT count(*) FROM oe_costs_item WHERE id = :pid"),
            {"pid": str(item.id)},
        )
    ).scalar()
    assert count == 1
