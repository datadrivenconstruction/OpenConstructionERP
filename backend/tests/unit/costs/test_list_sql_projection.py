"""The lite SQL projection preserves the public row and pagination contracts."""

import copy
import inspect
import json
import uuid

import pytest
from fastapi.params import Param
from pydantic import ValidationError
from sqlalchemy import event, text

from app.modules.costs.models import CostItem
from app.modules.costs.repository import reset_trgm_probe
from app.modules.costs.router import _localize_response_payload, _slim_list_row, search_cost_items
from app.modules.costs.schemas import CostItemResponse, CostSearchQuery
from app.modules.costs.service import CostItemService
from tests._pg import transactional_session
from tests.unit.costs.test_list_lite_row_shape import _pack_row


def _payload(row, locale="ro"):
    return _slim_list_row(_localize_response_payload(CostItemResponse.model_validate(row), locale))


async def _route(service, **overrides):
    # Apply HTTP parameter defaults for a direct route call; real service/PG.
    kwargs = {
        name: param.default.default
        for name, param in inspect.signature(search_cost_items).parameters.items()
        if isinstance(param.default, Param)
    }
    return await search_cost_items(service=service, **(kwargs | overrides))


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["catalogue", "plain", "empty", "top_slot", "component_slot", "bad_variants"])
async def test_lite_response_equals_full_trim_without_loading_bulk_or_mutating_identity_map(shape):
    async with transactional_session() as session:
        values = copy.deepcopy(vars(_pack_row(0)))
        values.update(id=uuid.uuid4(), source=f"projection-{uuid.uuid4().hex}")
        if shape != "catalogue":
            values["components"] = [
                {"quantity": "2.345", "unit_rate": "4.50", "cost": "0", "unit": "Std."},
                {"cost": "12.345", "quantity": None},
                {"quantity": "bad", "unit_rate": "NaN"},
                {"quantity": None, "unit_rate": "1.005"},
            ]
            values["metadata_"] = {"scope_of_work": ["Prepare"], "labor_cost": None}
        if shape == "empty":
            values["components"] = []
        if shape == "top_slot":
            values["metadata_"].update(variants=[1, 2], variant_stats={"count": 2, "unit": "Std."})
        if shape == "component_slot":
            values["components"][0].update(available_variants=[1, 2], available_variant_stats={"count": 2})
        if shape == "bad_variants":
            values["metadata_"].update(variants="invalid", variant_stats={})
            values["components"][0].update(available_variants=[1], available_variant_stats={"count": 1})
        item = CostItem(**values)
        session.add(item)
        await session.flush()
        service = CostItemService(session)
        expected = _payload(item)
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        engine = session.bind.sync_engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = await _route(service, source=item.source, lite=True, fuzzy=False, locale="ro")
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert result["items"] == [expected]
        assert result["total"] == 1
        assert result["has_more"] is False
        assert result["next_cursor"] is None
        assert len(statements) == 2  # count + page; no deferred-column/N+1 fetches
        assert "jsonb_array_elements" in statements[-1]
        assert "jsonb_each" in statements[-1]
        assert (await session.get(CostItem, item.id)) is item
        assert item.components == values["components"]
        assert item.metadata_ == values["metadata_"]
        full = await _route(service, source=item.source, lite=False, fuzzy=False, locale="ro")
        assert len(full["items"][0]["components"]) == len(item.components)
        assert _slim_list_row(full["items"][0]) == expected


@pytest.mark.asyncio
async def test_database_result_drops_heavy_catalogues_before_python_deserialization():
    async with transactional_session() as session:
        values = copy.deepcopy(vars(_pack_row(0)))
        values.update(id=uuid.uuid4(), source=f"projection-{uuid.uuid4().hex}")
        item = CostItem(**values)
        session.add(item)
        await session.flush()
        rows, *_ = await CostItemService(session).search_costs_paginated(
            CostSearchQuery(source=item.source, fuzzy=False), lite=True
        )
        projected = json.dumps(vars(rows[0]), default=str)
        assert "full_label" not in projected
        assert "Festigkeitsklasse" not in projected
        assert all(len(comp["available_variants"]) <= 2 for comp in rows[0].components)
        assert _payload(rows[0]) == _payload(item)


@pytest.mark.asyncio
@pytest.mark.parametrize("fuzzy", [False, True])
async def test_lite_projection_preserves_full_search_order_counts_and_cursors(fuzzy):
    async with transactional_session() as session:
        if fuzzy:
            available = await session.scalar(text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'"))
            if not available:
                pytest.skip("This PostgreSQL installation does not ship pg_trgm")
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        reset_trgm_probe()
        source = f"projection-{uuid.uuid4().hex}"
        for n in range(3):
            values = copy.deepcopy(vars(_pack_row(n)))
            values.update(id=uuid.uuid4(), source=source, description=f"Concrete slab {n}")
            session.add(CostItem(**values))
        await session.flush()
        service = CostItemService(session)
        try:
            cursor = None
            for _ in range(2):
                query = CostSearchQuery(source=source, q="concrete", fuzzy=fuzzy, limit=2, cursor=cursor)
                full = await service.search_costs_paginated(query)
                lite = await service.search_costs_paginated(query, lite=True)
                assert [_payload(row) for row in lite[0]] == [_payload(row) for row in full[0]]
                assert lite[1:] == full[1:]
                cursor = lite[3]
            assert len(lite[0]) == 1
            assert lite[1:] == (None, False, None)
        finally:
            reset_trgm_probe()


@pytest.mark.asyncio
@pytest.mark.parametrize("components,metadata", [(None, {}), ({}, {}), ([None], {}), ([], None), ([], [])])
async def test_invalid_outer_json_keeps_full_response_validation_contract(components, metadata):
    async with transactional_session() as session:
        values = copy.deepcopy(vars(_pack_row(0)))
        values.update(
            id=uuid.uuid4(), source=f"projection-{uuid.uuid4().hex}", components=components, metadata_=metadata
        )
        item = CostItem(**values)
        session.add(item)
        await session.flush()
        rows, *_ = await CostItemService(session).search_costs_paginated(
            CostSearchQuery(source=item.source, fuzzy=False), lite=True
        )
        errors = []
        for row in (item, rows[0]):
            with pytest.raises(ValidationError) as exc:
                CostItemResponse.model_validate(row)
            errors.append([(error["loc"], error["type"]) for error in exc.value.errors()])
        assert errors[0] == errors[1]


@pytest.mark.asyncio
async def test_legacy_json_columns_do_not_acquire_jsonb_input_restrictions():
    async with transactional_session() as session:
        # Modern installs use JSONB; upgraded JSON columns can contain escaped
        # NUL in discarded fields. Casting such valid JSON to JSONB would fail.
        await session.execute(
            text("ALTER TABLE oe_costs_item ALTER COLUMN components TYPE json USING components::json")
        )
        await session.execute(text("ALTER TABLE oe_costs_item ALTER COLUMN metadata TYPE json USING metadata::json"))
        values = copy.deepcopy(vars(_pack_row(0)))
        values.update(id=uuid.uuid4(), source=f"projection-{uuid.uuid4().hex}", components=[], metadata_={})
        item = CostItem(**values)
        session.add(item)
        await session.flush()
        await session.execute(
            text(
                "UPDATE oe_costs_item SET components = CAST(:components AS json), metadata = CAST(:metadata AS json) WHERE id = :id"
            ),
            {
                "id": str(item.id),
                "components": json.dumps([{"cost": "1", "description": "\u0000"}]),
                "metadata": json.dumps({"discarded_note": "\u0000"}),
            },
        )
        source = item.source
        session.expunge_all()
        service = CostItemService(session)
        query = CostSearchQuery(source=source, fuzzy=False)
        full, *_ = await service.search_costs_paginated(query)
        lite, *_ = await service.search_costs_paginated(query, lite=True)
        assert _payload(lite[0]) == _payload(full[0])
        assert _payload(lite[0])["buildup_rate"] == "1.00"
