# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The saved-views validation rules, without a database.

A saved view is a question written down once and asked for months afterwards.
These tests cover the case the module exists to survive: the register changed
underneath a stored spec. Every rule is driven through the real core engine so
a rule that is registered but unreachable by rule-set name would show up as a
missing finding rather than passing quietly.

The toy entity is built over ``SavedView`` itself - it is a mapped model with
an indexed ``project_id``, so it satisfies a queryable entity without dragging
another module in - and is never put in the global registry, so nothing here
leaks into another test module.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.saved_views.registry import FieldSpec, QueryableEntity
from app.modules.saved_views.scoper import project_member_scoper
from app.modules.saved_views.validators import (
    SAVED_VIEWS_RULE_SET,
    describe_staleness,
    evaluate_view,
    spec_problems,
)

ENTITY_TYPE = "saved_view_probe"


def _entity(**overrides: Any) -> QueryableEntity:
    """A toy queryable entity, optionally with fields swapped out."""
    from app.modules.saved_views.models import SavedView

    fields = {
        "name": FieldSpec(name="name", column="name", kind="string"),
        "entity_type": FieldSpec(name="entity_type", column="entity_type", kind="string", groupable=True),
        "share_scope": FieldSpec(
            name="share_scope",
            column="share_scope",
            kind="enum",
            enum_values=("private", "team", "project", "workspace"),
        ),
        "created_at": FieldSpec(name="created_at", column="created_at", kind="date"),
    }
    fields.update(overrides.pop("fields", {}))
    for name in overrides.pop("drop_fields", ()):
        fields.pop(name, None)
    return QueryableEntity(
        entity_type=ENTITY_TYPE,
        model=SavedView,
        fields=fields,
        scoper=project_member_scoper,
        default_sort=("created_at", "desc"),
        project_fk_column="project_id",
        default_columns=("name", "share_scope"),
        **overrides,
    )


def _spec(**parts: Any) -> dict[str, Any]:
    """A stored spec as it is persisted, filtering on ``name`` by default."""
    spec: dict[str, Any] = {
        "where": {"join": "and", "conditions": [{"field": "name", "op": "contains", "value": "roof"}]},
        "sort": [{"field": "created_at", "direction": "desc"}],
        "columns": ["name", "share_scope"],
        "page": 1,
        "page_size": 50,
    }
    spec.update(parts)
    return spec


def _view(**overrides: Any) -> dict[str, Any]:
    """The view-row half of a validation payload."""
    view = {
        "id": str(uuid.uuid4()),
        "name": "Roof packages",
        "description": "Everything on the roof package, by age",
        "entity_type": ENTITY_TYPE,
        "share_scope": "private",
        "shared_team_id": None,
        "project_id": str(uuid.uuid4()),
        "owner_id": str(uuid.uuid4()),
    }
    view.update(overrides)
    return view


def _payload(
    *,
    view: dict[str, Any] | None = None,
    spec: dict[str, Any] | None = None,
    entity: QueryableEntity | None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble what the service hands the engine."""
    view = view if view is not None else _view()
    spec = spec if spec is not None else _spec()
    return {
        "view": view,
        "problems": spec_problems(str(view["entity_type"]), spec, entity),
        "entity_facts": facts if facts is not None else {"spec_parsed": True, "complexity_ceiling": 12},
    }


def _rule_ids(report: Any) -> set[str]:
    """The rule ids that reported a finding."""
    return {f.rule_id for f in report.findings}


# ── The structural core ─────────────────────────────────────────────────────


def test_healthy_spec_reports_no_problems() -> None:
    """A spec that still binds produces no drift at all."""
    assert spec_problems(ENTITY_TYPE, _spec(), _entity()) == []
    assert describe_staleness(ENTITY_TYPE, _spec(), _entity()) == (False, [])


def test_unregistered_entity_is_the_only_problem_reported() -> None:
    """With no entity there is nothing to compare fields against, so stop there."""
    problems = spec_problems(ENTITY_TYPE, _spec(), None)
    assert [p.code for p in problems] == ["entity_unregistered"]
    is_stale, reasons = describe_staleness(ENTITY_TYPE, _spec(), None)
    assert is_stale is True
    assert ENTITY_TYPE in reasons[0]


def test_dropped_field_is_named_not_ignored() -> None:
    """The whole point: a field that left the whitelist must be visible."""
    problems = spec_problems(ENTITY_TYPE, _spec(), _entity(drop_fields=("name",)))
    codes = {p.code for p in problems}
    assert "field_missing" in codes
    assert {p.field for p in problems if p.code == "field_missing"} == {"name"}


def test_withdrawn_capability_is_reported_separately_from_a_missing_field() -> None:
    """A field can survive while the use the spec makes of it is withdrawn."""
    narrowed = _entity(
        fields={"name": FieldSpec(name="name", column="name", kind="string", filterable=False)},
    )
    problems = spec_problems(ENTITY_TYPE, _spec(), narrowed)
    assert [p.code for p in problems] == ["field_capability"]
    assert "filter" in problems[0].message


def test_retired_enum_value_is_reported() -> None:
    """A filter on a value that has left the vocabulary can only match nothing."""
    spec = _spec(
        where={
            "join": "and",
            "conditions": [{"field": "share_scope", "op": "eq", "value": "public"}],
        },
    )
    problems = spec_problems(ENTITY_TYPE, spec, _entity())
    assert [p.code for p in problems] == ["enum_value_gone"]
    assert "public" in problems[0].message


def test_enum_values_inside_an_in_list_are_each_checked() -> None:
    """``in`` carries a list, and every member has to be a current value."""
    spec = _spec(
        where={
            "join": "and",
            "conditions": [{"field": "share_scope", "op": "in", "value": ["project", "public"]}],
        },
    )
    problems = spec_problems(ENTITY_TYPE, spec, _entity())
    assert [p.code for p in problems] == ["enum_value_gone"]
    assert "public" in problems[0].message


def test_fields_nested_in_a_group_are_walked() -> None:
    """Drift hidden three groups deep is still drift."""
    spec = _spec(
        where={
            "join": "and",
            "conditions": [],
            "groups": [
                {
                    "join": "or",
                    "conditions": [],
                    "groups": [
                        {"join": "and", "conditions": [{"field": "gone", "op": "eq", "value": 1}]},
                    ],
                }
            ],
        },
    )
    problems = spec_problems(ENTITY_TYPE, spec, _entity())
    assert [p.field for p in problems] == ["gone"]


def test_unparsable_spec_stops_at_one_problem() -> None:
    """A spec that no longer parses cannot be compared field by field."""
    problems = spec_problems(ENTITY_TYPE, {"where": "not a group"}, _entity())
    assert [p.code for p in problems] == ["spec_unparsable"]


# ── The rules, through the core engine ──────────────────────────────────────


@pytest.mark.asyncio
async def test_healthy_view_produces_no_findings() -> None:
    """A current view passes every rule, so the report is clean."""
    report = await evaluate_view(_payload(entity=_entity()))
    assert report.findings == []
    assert report.error_count == 0
    assert report.passed_count > 0
    assert report.unsupported_rule_sets == []


@pytest.mark.asyncio
async def test_the_rule_set_is_reachable_by_name() -> None:
    """A rule registered under a name nobody requests never runs.

    ``unsupported_rule_sets`` is the engine's own report of a rule-set name it
    could not resolve, so this is the check that the registration and the
    request agree on the string.
    """
    report = await evaluate_view(_payload(entity=_entity()))
    assert SAVED_VIEWS_RULE_SET not in report.unsupported_rule_sets


@pytest.mark.asyncio
async def test_dropped_field_raises_an_error_finding() -> None:
    """The drift a saved view is most likely to suffer is an ERROR."""
    report = await evaluate_view(_payload(entity=_entity(drop_fields=("name",))))
    assert "saved_views.fields_whitelisted" in _rule_ids(report)
    assert report.error_count >= 1


@pytest.mark.asyncio
async def test_unregistered_entity_does_not_also_report_every_field() -> None:
    """One cause, one finding: the field rules stand down when the entity is gone."""
    report = await evaluate_view(_payload(entity=None))
    ids = _rule_ids(report)
    assert "saved_views.entity_registered" in ids
    assert "saved_views.fields_whitelisted" not in ids
    assert "saved_views.field_capability" not in ids


@pytest.mark.asyncio
async def test_team_share_without_a_team_is_an_error() -> None:
    """Deleting a team clears the pin, and the share must not pass unnoticed."""
    report = await evaluate_view(
        _payload(
            view=_view(share_scope="team", shared_team_id=None),
            entity=_entity(),
        )
    )
    assert "saved_views.team_share_has_team" in _rule_ids(report)


@pytest.mark.asyncio
async def test_team_share_with_a_team_passes() -> None:
    """The same view with its team intact reports nothing."""
    report = await evaluate_view(
        _payload(
            view=_view(share_scope="team", shared_team_id=str(uuid.uuid4())),
            entity=_entity(),
        )
    )
    assert "saved_views.team_share_has_team" not in _rule_ids(report)


@pytest.mark.asyncio
async def test_shared_view_without_a_project_pin_is_an_error() -> None:
    """Visibility is decided against the view's own project, so a share needs one."""
    report = await evaluate_view(_payload(view=_view(share_scope="project", project_id=None), entity=_entity()))
    assert "saved_views.shared_view_pinned" in _rule_ids(report)


@pytest.mark.asyncio
async def test_private_view_without_a_project_pin_is_not_flagged() -> None:
    """A private view answers only to its owner, so the pin rule stands down."""
    report = await evaluate_view(_payload(view=_view(share_scope="private", project_id=None), entity=_entity()))
    assert "saved_views.shared_view_pinned" not in _rule_ids(report)


@pytest.mark.asyncio
async def test_unknown_share_scope_is_an_error() -> None:
    """An unrecognised scope reads as private and hides a view its owner shared."""
    report = await evaluate_view(_payload(view=_view(share_scope="public"), entity=_entity()))
    assert "saved_views.share_scope_known" in _rule_ids(report)


@pytest.mark.asyncio
async def test_shared_view_without_a_description_is_only_an_info() -> None:
    """Worth saying, not worth blocking."""
    report = await evaluate_view(_payload(view=_view(share_scope="project", description=""), entity=_entity()))
    findings = {f.rule_id: f for f in report.findings}
    assert "saved_views.shared_view_described" in findings
    assert findings["saved_views.shared_view_described"].severity == "info"
    assert report.error_count == 0


@pytest.mark.asyncio
async def test_page_size_over_the_cap_warns_rather_than_silently_clamping() -> None:
    """The clamp is invisible in the response, so it is said out loud here."""
    report = await evaluate_view(
        _payload(
            entity=_entity(),
            facts={"spec_parsed": True, "complexity_ceiling": 12, "page_size": 900, "row_cap": 500},
        )
    )
    findings = {f.rule_id: f for f in report.findings}
    assert "saved_views.page_size_within_cap" in findings
    assert findings["saved_views.page_size_within_cap"].context == {"page_size": 900, "row_cap": 500}


@pytest.mark.asyncio
async def test_complexity_close_to_the_ceiling_warns_before_it_is_refused() -> None:
    """The ceiling is a hard refusal, so the warning has to arrive before it."""
    report = await evaluate_view(
        _payload(entity=_entity(), facts={"spec_parsed": True, "complexity": 10, "complexity_ceiling": 12})
    )
    assert "saved_views.within_complexity_budget" in _rule_ids(report)


@pytest.mark.asyncio
async def test_an_empty_spec_warns_that_nothing_was_saved() -> None:
    """A view with no filter, sort or columns is the register itself."""
    report = await evaluate_view(
        _payload(
            spec={"page": 1, "page_size": 50},
            entity=_entity(),
            facts={"spec_parsed": True, "complexity_ceiling": 12, "spec_is_empty": True},
        )
    )
    assert "saved_views.spec_is_not_empty" in _rule_ids(report)


@pytest.mark.asyncio
async def test_rules_that_could_not_compute_stand_down_rather_than_pass() -> None:
    """No facts means nothing was measured, and that must not read as healthy."""
    report = await evaluate_view(_payload(entity=_entity(), facts={"spec_parsed": False, "complexity_ceiling": 12}))
    ids = _rule_ids(report)
    assert "saved_views.spec_is_not_empty" not in ids
    assert "saved_views.within_complexity_budget" not in ids
    assert "saved_views.page_size_within_cap" not in ids
