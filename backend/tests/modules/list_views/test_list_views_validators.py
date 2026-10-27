# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List-views rules: what blocks a save and what only warns."""

from __future__ import annotations

import pytest

from app.core.validation.engine import Severity, rule_registry
from app.modules.list_views.validators import LIST_VIEWS_RULE_SET, check_view


def _view(**over):
    base = {"name": "Open items", "scope_key": "tasks.list", "state": {}, "is_shared": False}
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_a_clean_view_raises_nothing():
    assert await check_view(_view(state={"columns": ["code", "qty"], "sort": {"key": "qty", "dir": "asc"}})) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("over", "rule_id"),
    [
        ({"name": "  "}, "list_views.name_present"),
        ({"scope_key": "bad key!"}, "list_views.scope_key_format"),
        ({"state": {"query": {"q": "x" * 40000}}}, "list_views.state_size"),
    ],
)
async def test_errors_block_a_save(over, rule_id):
    failing = await check_view(_view(**over))
    assert any(r.rule_id == rule_id and r.severity == Severity.ERROR for r in failing)


@pytest.mark.asyncio
async def test_hidden_sort_and_filter_columns_only_warn():
    failing = await check_view(
        _view(state={"columns": ["code"], "sort": {"key": "qty", "dir": "desc"}, "filters": {"unit": "m3"}})
    )
    ids = {r.rule_id: r.severity for r in failing}
    assert ids == {
        "list_views.sort_column_visible": Severity.WARNING,
        "list_views.filter_column_visible": Severity.WARNING,
    }


def test_rules_are_registered_in_their_rule_set():
    names = {r.rule_id for r in rule_registry.get_rules_for_sets([LIST_VIEWS_RULE_SET])}
    assert {"list_views.name_present", "list_views.state_size"} <= names
