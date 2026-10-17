# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The planner the v92 revision and the boot repair share, without a database."""

from __future__ import annotations

from app.modules.costmodel.structure_backfill import AccountRow, plan_structure_backfill


def _row(i: str, code: str, *, parent: str | None = None, title: str = "", level: int = 1, std: str = "din276"):
    return AccountRow(
        id=i, project_id="p", parent_id=parent, code=code, name=code, title=title, level=level, standard=std
    )


def test_an_untouched_flat_group_is_nested_and_the_plan_is_idempotent() -> None:
    rows = [_row("a", "300"), _row("b", "330"), _row("c", "331")]
    plan = plan_structure_backfill(rows)
    assert plan["b"]["parent_id"] == "a" and plan["b"]["level"] == 2
    assert plan["c"]["parent_id"] == "b" and plan["c"]["level"] == 3
    applied = [
        AccountRow(
            id=r.id,
            project_id=r.project_id,
            parent_id=plan.get(r.id, {}).get("parent_id", r.parent_id),
            code=r.code,
            name=r.name,
            title=str(plan.get(r.id, {}).get("title", r.title)),
            level=int(plan.get(r.id, {}).get("level", r.level)),
            standard=r.standard,
        )
        for r in rows
    ]
    assert plan_structure_backfill(applied) == {}


def test_a_group_with_a_title_or_a_parent_keeps_its_top_level_accounts() -> None:
    titled = [_row("a", "300", title="Building"), _row("b", "330")]
    assert "parent_id" not in plan_structure_backfill(titled).get("b", {})
    parented = [_row("a", "300"), _row("b", "310", parent="a"), _row("c", "330")]
    plan = plan_structure_backfill(parented)
    assert "parent_id" not in plan.get("c", {})
    assert plan["b"] == {"level": 2}


def test_a_custom_standard_is_never_nested_by_code() -> None:
    rows = [_row("a", "A1", std="company"), _row("b", "A1.1", std="company")]
    assert plan_structure_backfill(rows) == {}
