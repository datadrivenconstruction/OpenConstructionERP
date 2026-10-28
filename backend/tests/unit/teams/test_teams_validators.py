"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The six ``teams`` validation rules, each on a project that actually trips it.

Each rule gets a positive case (a clean project it stays quiet on) and a
negative case (a misconfiguration it names). The clean case is what stops a
rule that never fires from looking like a rule that passes.

The snapshot collector is exercised through the rules rather than separately:
if it read the wrong rows, the counts asserted below would not line up.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.teams.service import TeamService
from app.modules.teams.validators import (
    TEAMS_RULE_SET,
    collect_project_snapshot,
    evaluate_project_teams,
)
from tests.unit.teams.conftest import (
    make_membership,
    make_project,
    make_restriction,
    make_team,
    make_user,
)

pytestmark = pytest.mark.asyncio


def _rule_ids(report) -> set[str]:
    """The rule ids that reported a finding."""
    return {f.rule_id for f in report.findings}


async def _clean_project(session):
    """One default team with a member: the shape every rule should stay quiet on."""
    owner = await make_user(session)
    member = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Delivery", is_default=True)
    await make_membership(session, team.id, member.id)
    return owner, member, project, team


# ── The rule set runs at all ─────────────────────────────────────────────────


async def test_the_rule_set_is_registered_and_actually_runs(session) -> None:
    """Guard the guard.

    An unregistered rule set reports as ``unsupported``, which the UI would
    render as a clean project. If this ever fails, every other case in this
    file is passing for the wrong reason.
    """
    from app.core.validation.engine import rule_registry

    ids = {rule.rule_id for rule in rule_registry.get_rules_for_sets([TEAMS_RULE_SET])}
    # Named rather than counted: when a rule is added and forgotten here, the
    # failure should say which one is missing instead of "expected 6, got 7".
    assert ids == {
        "teams.default_team_present",
        "teams.restriction_has_viewer",
        "teams.restriction_scope",
        "teams.empty_team",
        "teams.duplicate_team_name",
        "teams.restriction_enforced",
        "teams.roster_ticket_valid",
        "teams.roster_window",
        "teams.roster_site_lead",
        "teams.roster_covers_access",
    }

    _owner, _member, project, _team = await _clean_project(session)
    report = await evaluate_project_teams(session, project.id)
    assert report.status not in {"unsupported", "skipped"}


async def test_a_clean_project_reports_no_findings(session) -> None:
    """The positive case for the whole set."""
    _owner, _member, project, _team = await _clean_project(session)
    report = await evaluate_project_teams(session, project.id)
    assert report.findings == []
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.status == "passed"


async def test_a_project_with_no_teams_is_not_reported_as_clean(session) -> None:
    """Nothing to check is not the same as checked and fine.

    The score stays ``None`` so the banner cannot render "100%" over a project
    whose access model does not exist yet.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    report = await evaluate_project_teams(session, project.id)
    assert report.findings == []
    assert report.score is None
    assert report.status == "skipped"


# ── teams.default_team_present ───────────────────────────────────────────────


async def test_two_default_teams_is_an_error(session) -> None:
    """Which team a new member lands on would be arbitrary."""
    owner = await make_user(session)
    member = await make_user(session)
    project = await make_project(session, owner.id)
    first = await make_team(session, project.id, name="One", is_default=True)
    second = await make_team(session, project.id, name="Two", is_default=True, sort_order=1)
    await make_membership(session, first.id, member.id)
    await make_membership(session, second.id, member.id)

    report = await evaluate_project_teams(session, project.id)
    assert "teams.default_team_present" in _rule_ids(report)
    assert report.error_count >= 1


async def test_no_default_team_is_an_error(session) -> None:
    """A project with teams but no default has nowhere to put a new member."""
    owner = await make_user(session)
    member = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Only", is_default=False)
    await make_membership(session, team.id, member.id)

    report = await evaluate_project_teams(session, project.id)
    assert "teams.default_team_present" in _rule_ids(report)


async def test_promoting_a_team_demotes_the_incumbent(session) -> None:
    """The service keeps the project valid rather than letting the rule scold.

    Two defaults are prevented at the write, so the rule above only ever fires
    on data that predates this or was written straight to the table.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    first = await make_team(session, project.id, name="One", is_default=True)

    from app.modules.teams.schemas import TeamCreate

    service = TeamService(session)
    second = await service.create_team(
        TeamCreate(project_id=project.id, name="Two", is_default=True),
        actor_id=owner.id,
    )
    snapshot = await collect_project_snapshot(session, project.id)
    defaults = [t for t in snapshot.teams if t.is_default]
    assert [t.id for t in defaults] == [str(second.id)]
    assert str(first.id) not in {t.id for t in defaults}


# ── teams.restriction_has_viewer ─────────────────────────────────────────────


async def test_a_record_restricted_to_an_empty_team_is_an_error(session) -> None:
    """The "we locked ourselves out" case.

    Nobody but the owner and system admins can open the record, and nothing
    else on the platform would say so.
    """
    owner = await make_user(session)
    member = await make_user(session)
    project = await make_project(session, owner.id)
    staffed = await make_team(session, project.id, name="Delivery", is_default=True)
    await make_membership(session, staffed.id, member.id)
    empty = await make_team(session, project.id, name="Nobody", sort_order=1)
    record = str(uuid.uuid4())
    await make_restriction(session, empty.id, entity_type="boq", entity_id=record)

    report = await evaluate_project_teams(session, project.id)
    ids = _rule_ids(report)
    assert "teams.restriction_has_viewer" in ids
    finding = next(f for f in report.findings if f.rule_id == "teams.restriction_has_viewer")
    assert finding.severity == "error"
    assert finding.element_ref == f"boq/{record}"


async def test_a_record_restricted_to_a_staffed_team_is_fine(session) -> None:
    """Somebody can still read it, so the rule stays quiet."""
    _owner, _member, project, team = await _clean_project(session)
    await make_restriction(session, team.id, entity_type="boq")

    report = await evaluate_project_teams(session, project.id)
    assert "teams.restriction_has_viewer" not in _rule_ids(report)


# ── teams.restriction_scope ──────────────────────────────────────────────────


async def test_a_restriction_naming_a_foreign_team_is_an_error(session) -> None:
    """The row is ignored on read, so it looks like protection and is not."""
    owner_a = await make_user(session)
    member = await make_user(session)
    owner_b = await make_user(session)
    project_a = await make_project(session, owner_a.id)
    project_b = await make_project(session, owner_b.id)
    team_a = await make_team(session, project_a.id, name="Ours", is_default=True)
    team_b = await make_team(session, project_b.id, name="Theirs", is_default=True)
    await make_membership(session, team_a.id, member.id)
    await make_membership(session, team_b.id, member.id)

    record = str(uuid.uuid4())
    await make_restriction(session, team_a.id, entity_type="document", entity_id=record)
    await make_restriction(session, team_b.id, entity_type="document", entity_id=record)

    report = await evaluate_project_teams(session, project_a.id)
    assert "teams.restriction_scope" in _rule_ids(report)


async def test_restrictions_inside_one_project_do_not_trip_the_scope_rule(session) -> None:
    """The clean case, so the rule is not simply always on."""
    _owner, _member, project, team = await _clean_project(session)
    await make_restriction(session, team.id, entity_type="document")
    report = await evaluate_project_teams(session, project.id)
    assert "teams.restriction_scope" not in _rule_ids(report)


# ── teams.empty_team ─────────────────────────────────────────────────────────


async def test_an_empty_active_team_is_a_warning(session) -> None:
    """Harmless on its own, which is why it is a warning and not an error."""
    _owner, _member, project, _team = await _clean_project(session)
    await make_team(session, project.id, name="Placeholder", sort_order=1)

    report = await evaluate_project_teams(session, project.id)
    assert "teams.empty_team" in _rule_ids(report)
    assert report.warning_count >= 1
    assert report.error_count == 0


async def test_an_empty_but_deactivated_team_is_not_reported(session) -> None:
    """Deactivating is the intended way to retire a team, not a finding."""
    _owner, _member, project, _team = await _clean_project(session)
    await make_team(session, project.id, name="Retired", is_active=False, sort_order=1)

    report = await evaluate_project_teams(session, project.id)
    assert "teams.empty_team" not in _rule_ids(report)


# ── teams.duplicate_team_name ────────────────────────────────────────────────


async def test_two_active_teams_with_the_same_name_is_a_warning(session) -> None:
    """A restriction can be pointed at the wrong one and still look right."""
    owner = await make_user(session)
    member = await make_user(session)
    other = await make_user(session)
    project = await make_project(session, owner.id)
    first = await make_team(session, project.id, name="Client", is_default=True)
    second = await make_team(session, project.id, name="client", sort_order=1)
    await make_membership(session, first.id, member.id)
    await make_membership(session, second.id, other.id)

    report = await evaluate_project_teams(session, project.id)
    assert "teams.duplicate_team_name" in _rule_ids(report)


async def test_distinct_names_do_not_trip_the_duplicate_rule(session) -> None:
    """The clean case."""
    owner = await make_user(session)
    member = await make_user(session)
    other = await make_user(session)
    project = await make_project(session, owner.id)
    first = await make_team(session, project.id, name="Client", is_default=True)
    second = await make_team(session, project.id, name="Site", sort_order=1)
    await make_membership(session, first.id, member.id)
    await make_membership(session, second.id, other.id)

    report = await evaluate_project_teams(session, project.id)
    assert "teams.duplicate_team_name" not in _rule_ids(report)


# ── teams.restriction_enforced ───────────────────────────────────────────────


async def test_a_restriction_on_an_unenforced_kind_is_a_warning(session) -> None:
    """Recorded, not enforced - and the report says so rather than implying a lock.

    Every kind in the catalogue is currently unenforced (no consumer subtracts
    yet), so any restriction trips this. When a module adopts the filter and
    flips ``enforced`` on its entry, the warning disappears for that kind on
    its own.
    """
    _owner, _member, project, team = await _clean_project(session)
    await make_restriction(session, team.id, entity_type="document")

    report = await evaluate_project_teams(session, project.id)
    finding = next(f for f in report.findings if f.rule_id == "teams.restriction_enforced")
    assert finding.severity == "warning"
    assert finding.context["entity_type"] == "document"
    assert finding.context["known"] is True


async def test_a_restriction_on_a_retired_kind_is_reported_as_dead_configuration(session) -> None:
    """A row written before a kind was retired hides nothing and should be cleared.

    Only reachable by writing straight to the table - the API refuses an
    unknown kind at the edge - which is exactly the data a sweep would find.
    """
    _owner, _member, project, team = await _clean_project(session)
    await make_restriction(session, team.id, entity_type="legacy_widget")

    report = await evaluate_project_teams(session, project.id)
    finding = next(
        f
        for f in report.findings
        if f.rule_id == "teams.restriction_enforced" and f.context.get("entity_type") == "legacy_widget"
    )
    assert finding.context["known"] is False


async def test_findings_carry_a_stable_i18n_key(session) -> None:
    """The UI localises on ``key``; the English message is the fallback."""
    _owner, _member, project, _team = await _clean_project(session)
    await make_team(session, project.id, name="Placeholder", sort_order=1)

    report = await evaluate_project_teams(session, project.id)
    finding = next(f for f in report.findings if f.rule_id == "teams.empty_team")
    # One "teams." segment, not two: the rule id is already namespaced, so the
    # key must not read "teams.validation.teams.empty_team".
    assert finding.key == "teams.validation.empty_team"
    assert finding.message
    assert finding.suggestion


async def test_validation_degrades_to_skipped_rather_than_500(session, monkeypatch) -> None:
    """Losing the banner must not take the teams screen down with it.

    And it degrades to ``skipped``, never to ``passed``: "we could not check"
    and "we checked and it is fine" must not read alike.
    """
    _owner, _member, project, _team = await _clean_project(session)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("engine down")

    monkeypatch.setattr("app.modules.teams.validators.collect_project_snapshot", _boom)
    report = await evaluate_project_teams(session, project.id)
    assert report.status == "skipped"
    assert report.score is None
    assert report.findings == []
