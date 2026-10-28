# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure per-role adoption-checklist engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. The only number
the engine produces is an integer percent in [0, 100], so the assertions are all
on integers, booleans, tuples and step keys - no Decimal, no money.
"""

from __future__ import annotations

import pytest

from app.modules.value.adoption_checklist import (
    ADOPTION_STEPS,
    DEFAULT_LAGGARD_THRESHOLD,
    DEFAULT_NEXT_ACTIONS,
    ROLE_ESTIMATOR,
    ROLE_FIELD,
    ROLE_MANAGER,
    ROLE_REVIEWER,
    AdoptionChecklist,
    ChecklistStep,
    ChecklistStepStatus,
    TeamAdoption,
    TeamMemberAdoption,
    evaluate,
    steps_for_role,
    team_adoption,
)

# --------------------------------------------------------------------------- #
# A small, explicit catalogue used by the scoring / ordering tests so the
# arithmetic is hand-checkable and independent of any later tuning of the
# built-in ADOPTION_STEPS. Weights chosen to make the percentages exact.
# --------------------------------------------------------------------------- #

_S_GLOBAL = ChecklistStep(
    key="s_global",
    label="Global step",
    module="m",
    action_keys=("g.one", "g.two"),  # two routes to the same outcome
    weight=1,
    role_scope=(),
)
_S_MANAGER = ChecklistStep(
    key="s_manager",
    label="Manager step",
    module="m",
    action_keys=("mgr.done",),
    weight=3,
    role_scope=(ROLE_MANAGER,),
)
_S_SHARED = ChecklistStep(
    key="s_shared",
    label="Shared step",
    module="m",
    action_keys=("shared.done",),
    weight=1,
    role_scope=(ROLE_MANAGER, ROLE_FIELD),
)

_MINI_CATALOGUE = (_S_GLOBAL, _S_MANAGER, _S_SHARED)


def _keys(steps) -> list:
    return [s.key for s in steps]


# --------------------------------------------------------------------------- #
# Built-in catalogue sanity
# --------------------------------------------------------------------------- #


def test_catalogue_non_empty_and_well_formed() -> None:
    assert ADOPTION_STEPS  # non-empty
    for step in ADOPTION_STEPS:
        assert isinstance(step, ChecklistStep)
        assert step.key
        assert step.label
        assert step.module
        # Every step must list at least one action key, or it can never be done.
        assert step.action_keys
        assert all(isinstance(k, str) and k for k in step.action_keys)
        assert step.weight >= 1


def test_catalogue_keys_are_unique() -> None:
    keys = [s.key for s in ADOPTION_STEPS]
    assert len(keys) == len(set(keys))


def test_catalogue_covers_the_documented_first_value_actions() -> None:
    # The build spec calls these out by name; each must be a step in the path.
    expected = {
        "create_project",
        "import_boq",
        "run_takeoff",
        "start_approval",
        "log_change_order",
        "run_ai_agent",
        "record_ai_verdict",
        "assemble_evidence_pack",
        "generate_value_report",
    }
    assert expected <= {s.key for s in ADOPTION_STEPS}


def test_catalogue_starts_with_create_project() -> None:
    # The onboarding sequence opens with standing up a project.
    assert ADOPTION_STEPS[0].key == "create_project"


def test_defaults_are_midpoint_and_three() -> None:
    assert DEFAULT_LAGGARD_THRESHOLD == 50
    assert DEFAULT_NEXT_ACTIONS == 3


# --------------------------------------------------------------------------- #
# steps_for_role - role-scope filtering (scoped vs global)
# --------------------------------------------------------------------------- #


def test_steps_for_role_includes_global_steps() -> None:
    # The global step appears for every role; the manager-only step only for it.
    assert _keys(steps_for_role(ROLE_FIELD, _MINI_CATALOGUE)) == ["s_global", "s_shared"]
    assert _keys(steps_for_role(ROLE_MANAGER, _MINI_CATALOGUE)) == ["s_global", "s_manager", "s_shared"]


def test_steps_for_role_unknown_role_sees_only_global() -> None:
    # An unrecognised role matches no explicit scope, so it sees only the
    # globally scoped step - the honest default, not an error.
    assert _keys(steps_for_role("stranger", _MINI_CATALOGUE)) == ["s_global"]


def test_steps_for_role_preserves_catalogue_order() -> None:
    # Order is the onboarding sequence, taken straight from the catalogue.
    got = steps_for_role(ROLE_MANAGER, _MINI_CATALOGUE)
    assert got == (_S_GLOBAL, _S_MANAGER, _S_SHARED)


@pytest.mark.parametrize(
    ("role", "expected_keys"),
    [
        (
            ROLE_MANAGER,
            [
                "create_project",
                "import_boq",
                "run_takeoff",
                "start_approval",
                "log_change_order",
                "run_ai_agent",
                "record_ai_verdict",
                "assemble_evidence_pack",
                "generate_value_report",
            ],
        ),
        (
            ROLE_ESTIMATOR,
            ["create_project", "import_boq", "run_takeoff", "log_change_order", "run_ai_agent", "record_ai_verdict"],
        ),
        (ROLE_FIELD, ["create_project", "run_takeoff", "log_change_order", "run_ai_agent"]),
        (
            ROLE_REVIEWER,
            [
                "create_project",
                "start_approval",
                "log_change_order",
                "run_ai_agent",
                "record_ai_verdict",
                "assemble_evidence_pack",
            ],
        ),
    ],
)
def test_steps_for_role_builtin_catalogue(role: str, expected_keys: list) -> None:
    # The built-in catalogue scopes office-heavy steps off the field path while
    # keeping the global ones (project / change order / AI agent) everywhere.
    assert _keys(steps_for_role(role)) == expected_keys


def test_field_role_excludes_office_only_steps() -> None:
    field_keys = {s.key for s in steps_for_role(ROLE_FIELD)}
    # Pricing, approvals, AI verdicts, evidence and the value report are not on
    # the field path, so the field score is not dragged down by office work.
    for office_only in (
        "import_boq",
        "start_approval",
        "record_ai_verdict",
        "assemble_evidence_pack",
        "generate_value_report",
    ):
        assert office_only not in field_keys


# --------------------------------------------------------------------------- #
# evaluate - done detection (any matching action key)
# --------------------------------------------------------------------------- #


def _status_map(checklist: AdoptionChecklist) -> dict:
    return {st.step.key: st.done for st in checklist.steps}


def test_done_when_any_action_key_matches() -> None:
    # The global step has two action keys; observing EITHER marks it done.
    via_first = evaluate(ROLE_FIELD, frozenset({"g.one"}), _MINI_CATALOGUE)
    via_second = evaluate(ROLE_FIELD, frozenset({"g.two"}), _MINI_CATALOGUE)
    assert _status_map(via_first)["s_global"] is True
    assert _status_map(via_second)["s_global"] is True


def test_not_done_when_no_action_key_matches() -> None:
    checklist = evaluate(ROLE_FIELD, frozenset({"unrelated.action"}), _MINI_CATALOGUE)
    statuses = _status_map(checklist)
    assert statuses["s_global"] is False
    assert statuses["s_shared"] is False


def test_done_detection_in_builtin_catalogue_alternate_route() -> None:
    # import_boq lists both "boq.imported" and "boq.created"; the alternate
    # route must also satisfy the step.
    checklist = evaluate(ROLE_ESTIMATOR, frozenset({"boq.created"}), ADOPTION_STEPS)
    assert _status_map(checklist)["import_boq"] is True


def test_unknown_action_key_never_marks_anything_done() -> None:
    # Activity unrelated to the catalogue cannot manufacture progress.
    checklist = evaluate(ROLE_MANAGER, frozenset({"random.thing", "another.thing"}))
    assert all(st.done is False for st in checklist.steps)
    assert checklist.adoption_score == 0


def test_one_status_per_applicable_step_in_order() -> None:
    checklist = evaluate(ROLE_MANAGER, frozenset(), _MINI_CATALOGUE)
    assert all(isinstance(st, ChecklistStepStatus) for st in checklist.steps)
    assert _keys([st.step for st in checklist.steps]) == ["s_global", "s_manager", "s_shared"]


# --------------------------------------------------------------------------- #
# evaluate - weighted scoring correctness
# --------------------------------------------------------------------------- #


def test_score_zero_when_nothing_observed() -> None:
    checklist = evaluate(ROLE_MANAGER, frozenset(), _MINI_CATALOGUE)
    assert checklist.adoption_score == 0


def test_score_full_when_all_applicable_done() -> None:
    # Manager applicable steps: g (1) + mgr (3) + shared (1) = total 5; all done.
    observed = frozenset({"g.one", "mgr.done", "shared.done"})
    checklist = evaluate(ROLE_MANAGER, observed, _MINI_CATALOGUE)
    assert checklist.adoption_score == 100
    assert checklist.next_actions == ()


def test_score_is_weighted_not_count_based() -> None:
    # Manager total weight = 5. Completing ONLY the heavy manager step (weight 3)
    # is 3/5 = 60, even though it is just one of three steps - weight, not count.
    checklist = evaluate(ROLE_MANAGER, frozenset({"mgr.done"}), _MINI_CATALOGUE)
    assert checklist.adoption_score == 60


def test_score_rounds_to_nearest_integer() -> None:
    # Field path on the built-in catalogue: weights 1 + 2 + 2 + 3 = 8.
    # Completing only create_project (weight 1) -> 100/8 = 12.5 -> 12 (round).
    checklist = evaluate(ROLE_FIELD, frozenset({"project.created"}), ADOPTION_STEPS)
    assert checklist.adoption_score == 12


def test_score_partial_weighted_sum() -> None:
    # Field path weight 8. create_project (1) + run_ai_agent (3) = 4 -> 50.
    observed = frozenset({"project.created", "ai_agents.run.created"})
    checklist = evaluate(ROLE_FIELD, observed, ADOPTION_STEPS)
    assert checklist.adoption_score == 50


def test_score_in_zero_hundred_interval() -> None:
    checklist = evaluate(ROLE_REVIEWER, frozenset({"approval.route.started"}))
    assert 0 <= checklist.adoption_score <= 100


def test_score_zero_weight_step_does_not_divide_by_zero() -> None:
    # A pathological all-zero-weight catalogue must score 0, never raise.
    zero = (
        ChecklistStep(key="z1", label="Z1", module="m", action_keys=("z.1",), weight=0),
        ChecklistStep(key="z2", label="Z2", module="m", action_keys=("z.2",), weight=0),
    )
    checklist = evaluate(ROLE_MANAGER, frozenset({"z.1", "z.2"}), zero)
    assert checklist.adoption_score == 0


def test_score_negative_weight_floored_to_zero() -> None:
    # A negative weight is a misconfiguration and must not subtract from the
    # score. With one weight=2 step done and one weight=-5 step, the negative is
    # floored to 0, so total weight = 2 and done weight = 2 -> 100.
    cat = (
        ChecklistStep(key="good", label="Good", module="m", action_keys=("good.done",), weight=2),
        ChecklistStep(key="bad", label="Bad", module="m", action_keys=("bad.done",), weight=-5),
    )
    checklist = evaluate(ROLE_MANAGER, frozenset({"good.done"}), cat)
    assert checklist.adoption_score == 100


# --------------------------------------------------------------------------- #
# evaluate - next-actions ordering and cap
# --------------------------------------------------------------------------- #


def test_next_actions_are_incomplete_steps_in_catalogue_order() -> None:
    # Nothing done -> the next actions are the leading steps in catalogue order.
    checklist = evaluate(ROLE_MANAGER, frozenset(), ADOPTION_STEPS)
    assert _keys(checklist.next_actions) == ["create_project", "import_boq", "run_takeoff"]


def test_next_actions_capped_at_default() -> None:
    checklist = evaluate(ROLE_MANAGER, frozenset(), ADOPTION_STEPS)
    assert len(checklist.next_actions) == DEFAULT_NEXT_ACTIONS


def test_next_actions_skip_completed_steps() -> None:
    # Completing the first two manager steps pushes the nudge to the next three
    # still-incomplete steps, preserving catalogue order.
    observed = frozenset({"project.created", "boq.imported"})
    checklist = evaluate(ROLE_MANAGER, observed, ADOPTION_STEPS)
    assert _keys(checklist.next_actions) == ["run_takeoff", "start_approval", "log_change_order"]


def test_next_actions_empty_when_complete() -> None:
    observed = frozenset({"g.one", "mgr.done", "shared.done"})
    checklist = evaluate(ROLE_MANAGER, observed, _MINI_CATALOGUE)
    assert checklist.next_actions == ()


def test_next_actions_custom_limit() -> None:
    two = evaluate(ROLE_MANAGER, frozenset(), ADOPTION_STEPS, next_actions_limit=2)
    assert _keys(two.next_actions) == ["create_project", "import_boq"]


def test_next_actions_limit_zero_yields_none() -> None:
    none = evaluate(ROLE_MANAGER, frozenset(), ADOPTION_STEPS, next_actions_limit=0)
    assert none.next_actions == ()


def test_next_actions_fewer_than_cap_when_few_remain() -> None:
    # Only the shared step is incomplete -> a single next action, under the cap.
    observed = frozenset({"g.one", "mgr.done"})
    checklist = evaluate(ROLE_MANAGER, observed, _MINI_CATALOGUE)
    assert _keys(checklist.next_actions) == ["s_shared"]


# --------------------------------------------------------------------------- #
# evaluate - empty / edge roles
# --------------------------------------------------------------------------- #


def test_evaluate_role_with_no_applicable_steps() -> None:
    # A catalogue whose every step is scoped away from the role yields an empty
    # checklist with score 0 and no next actions - not a divide-by-zero.
    scoped_away = (
        ChecklistStep(
            key="only_mgr", label="Mgr", module="m", action_keys=("a",), weight=2, role_scope=(ROLE_MANAGER,)
        ),
    )
    checklist = evaluate(ROLE_FIELD, frozenset({"a"}), scoped_away)
    assert checklist.role == ROLE_FIELD
    assert checklist.steps == ()
    assert checklist.adoption_score == 0
    assert checklist.next_actions == ()


def test_evaluate_returns_adoption_checklist_instance() -> None:
    checklist = evaluate(ROLE_MANAGER, frozenset())
    assert isinstance(checklist, AdoptionChecklist)
    assert checklist.role == ROLE_MANAGER


def test_evaluate_is_deterministic() -> None:
    observed = frozenset({"project.created", "ai_agents.run.created"})
    a = evaluate(ROLE_FIELD, observed, ADOPTION_STEPS)
    b = evaluate(ROLE_FIELD, observed, ADOPTION_STEPS)
    assert a == b


# --------------------------------------------------------------------------- #
# team_adoption - rollup mean, laggards, ordering, empties
# --------------------------------------------------------------------------- #


def _full_manager_keys() -> frozenset:
    return frozenset(s.action_keys[0] for s in steps_for_role(ROLE_MANAGER))


def test_team_rollup_mean_of_member_scores() -> None:
    # One fully-onboarded manager (100) and one untouched field user (0) -> 50.
    team = team_adoption(
        [
            ("u_full", ROLE_MANAGER, _full_manager_keys()),
            ("u_empty", ROLE_FIELD, frozenset()),
        ]
    )
    assert team.team_score == 50


def test_team_rollup_mean_rounds_to_nearest() -> None:
    # Three members at 100, 100, 0 -> mean 66.67 -> 67.
    team = team_adoption(
        [
            ("a", ROLE_MANAGER, _full_manager_keys()),
            ("b", ROLE_MANAGER, _full_manager_keys()),
            ("c", ROLE_FIELD, frozenset()),
        ]
    )
    assert team.team_score == 67


def test_team_members_scored_under_their_own_role() -> None:
    # The field user's empty observation is measured against the field path only,
    # and the manager's against the manager path - each gets its own denominator.
    team = team_adoption(
        [
            ("mgr", ROLE_MANAGER, _full_manager_keys()),
            ("fld", ROLE_FIELD, frozenset()),
        ]
    )
    by_id = {m.user_id: m for m in team.members}
    assert by_id["mgr"].adoption_score == 100
    assert by_id["mgr"].role == ROLE_MANAGER
    assert by_id["fld"].adoption_score == 0
    assert by_id["fld"].role == ROLE_FIELD


def test_team_laggards_below_or_at_threshold() -> None:
    # Default threshold 50: the 0-score member is a laggard, the 100 is not.
    team = team_adoption(
        [
            ("u_full", ROLE_MANAGER, _full_manager_keys()),
            ("u_empty", ROLE_FIELD, frozenset()),
        ]
    )
    assert team.laggards == ("u_empty",)


def test_team_laggard_threshold_is_inclusive() -> None:
    # A member sitting exactly ON the threshold counts as a laggard. Field path
    # weight 8; create_project (1) + run_ai_agent (3) = 4 -> 50 == threshold.
    observed = frozenset({"project.created", "ai_agents.run.created"})
    team = team_adoption([("edge", ROLE_FIELD, observed)])
    assert team.members[0].adoption_score == 50
    assert team.laggards == ("edge",)


def test_team_custom_laggard_threshold() -> None:
    # Tighten the threshold so even a 50-score member is no longer a laggard.
    observed = frozenset({"project.created", "ai_agents.run.created"})  # field -> 50
    team = team_adoption([("edge", ROLE_FIELD, observed)], laggard_threshold=40)
    assert team.laggards == ()


def test_team_members_sorted_by_score_then_id() -> None:
    # Ascending score puts laggards first; equal scores break by user_id.
    team = team_adoption(
        [
            ("zoe", ROLE_FIELD, frozenset()),  # 0
            ("amy", ROLE_FIELD, frozenset()),  # 0, ties with zoe -> id breaks
            ("max", ROLE_MANAGER, _full_manager_keys()),  # 100
        ]
    )
    assert [m.user_id for m in team.members] == ["amy", "zoe", "max"]
    # Laggards follow the same ascending order.
    assert team.laggards == ("amy", "zoe")


def test_team_empty_members() -> None:
    team = team_adoption([])
    assert isinstance(team, TeamAdoption)
    assert team.members == ()
    assert team.team_score == 0
    assert team.laggards == ()


def test_team_all_laggards() -> None:
    team = team_adoption(
        [
            ("a", ROLE_FIELD, frozenset()),
            ("b", ROLE_MANAGER, frozenset()),
        ]
    )
    assert team.team_score == 0
    assert set(team.laggards) == {"a", "b"}


def test_team_no_laggards_when_all_full() -> None:
    team = team_adoption(
        [
            ("a", ROLE_MANAGER, _full_manager_keys()),
            ("b", ROLE_MANAGER, _full_manager_keys()),
        ]
    )
    assert team.team_score == 100
    assert team.laggards == ()


def test_team_returns_member_instances() -> None:
    team = team_adoption([("a", ROLE_MANAGER, frozenset())])
    assert all(isinstance(m, TeamMemberAdoption) for m in team.members)


def test_team_is_deterministic_regardless_of_input_order() -> None:
    members = [
        ("a", ROLE_MANAGER, _full_manager_keys()),
        ("b", ROLE_FIELD, frozenset()),
        ("c", ROLE_ESTIMATOR, frozenset({"boq.imported"})),
    ]
    first = team_adoption(members)
    second = team_adoption(list(reversed(members)))
    assert first == second
