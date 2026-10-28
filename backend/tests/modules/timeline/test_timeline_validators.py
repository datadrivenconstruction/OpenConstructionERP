# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Timeline validation rules.

Each rule is checked twice: once on data that should trip it, and once on data
that should not. A rule that only ever sees its own failure case cannot show
that it discriminates - it would pass just as well if it flagged everything.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.timeline.validators import (
    EntryWithoutEntityRule,
    UnattributedEntryRule,
    UnroutableEntryRule,
)
from tests.modules.timeline.conftest import make_entry, make_project, make_user

pytestmark = pytest.mark.asyncio


async def _run(rule, entries):
    """Run one rule over a list of rows and return the failing results."""
    results = await rule.validate(ValidationContext(data={"entries": entries}))
    return [r for r in results if not r.passed]


async def _project(session):
    user = await make_user(session)
    return await make_project(session, user.id)


# ── unroutable_entry ─────────────────────────────────────────────────────────


async def test_unroutable_entry_flags_a_row_nothing_can_select(session) -> None:
    entry = await make_entry(
        session,
        project_id=None,
        entity_id=None,
        entity_type="correspondence.outbound",
        action="correspondence.outbound.requested",
        module="correspondence",
    )
    entry.entity_id = None

    failures = await _run(UnroutableEntryRule(), [entry])

    assert len(failures) == 1
    assert failures[0].rule_id == "timeline.unroutable_entry"
    assert "never appear" in failures[0].message


async def test_unroutable_entry_passes_a_row_with_a_project(session) -> None:
    project = await _project(session)
    entry = await make_entry(session, project_id=project.id, action="ncr.created")

    assert await _run(UnroutableEntryRule(), [entry]) == []


async def test_unroutable_entry_passes_a_row_reachable_by_entity_alone(session) -> None:
    """A project-level row has no parent but is still selectable by entity."""
    project = await _project(session)
    entry = await make_entry(
        session,
        project_id=None,
        entity_type="project",
        entity_id=str(project.id),
        action="project.status_changed",
    )

    assert await _run(UnroutableEntryRule(), [entry]) == []


# ── entry_without_entity ─────────────────────────────────────────────────────


async def test_entry_without_entity_flags_a_row_that_names_no_record(session) -> None:
    project = await _project(session)
    entry = await make_entry(session, project_id=project.id, action="cost.back_charge.recorded")
    entry.entity_id = None

    failures = await _run(EntryWithoutEntityRule(), [entry])

    assert len(failures) == 1
    assert failures[0].rule_id == "timeline.entry_without_entity"


async def test_entry_without_entity_passes_when_the_record_is_named(session) -> None:
    project = await _project(session)
    entry = await make_entry(session, project_id=project.id, entity_id=str(uuid.uuid4()))

    assert await _run(EntryWithoutEntityRule(), [entry]) == []


async def test_the_two_reachability_rules_do_not_both_claim_one_row(session) -> None:
    """A row with neither parent nor entity is one finding, not two.

    Reporting it twice would double-count the same broken row and make a
    report of ten problems look like twenty.
    """
    entry = await make_entry(session, project_id=None, entity_id=None, action="x.y")
    entry.entity_id = None

    unroutable = await _run(UnroutableEntryRule(), [entry])
    unlinked = await _run(EntryWithoutEntityRule(), [entry])

    assert len(unroutable) == 1
    assert unlinked == []


# ── unattributed_entry ───────────────────────────────────────────────────────


async def test_unattributed_entry_flags_a_lost_actor(session) -> None:
    """The payload named who did it and the row does not carry them."""
    project = await _project(session)
    entry = await make_entry(
        session,
        project_id=project.id,
        action="ncr.created",
        actor_id=None,
        metadata={"created_by": "Alex Mason", "ncr_number": "N-1"},
    )

    failures = await _run(UnattributedEntryRule(), [entry])

    assert len(failures) == 1
    assert failures[0].rule_id == "timeline.unattributed_entry"
    assert "created_by" in failures[0].message


async def test_unattributed_entry_passes_when_the_actor_was_recorded(session) -> None:
    project = await _project(session)
    actor = uuid.uuid4()
    entry = await make_entry(
        session,
        project_id=project.id,
        actor_id=actor,
        metadata={"created_by": str(actor)},
    )

    assert await _run(UnattributedEntryRule(), [entry]) == []


async def test_unattributed_entry_ignores_genuine_system_events(session) -> None:
    """No actor named and none recorded is normal, not a finding.

    Most bridge rows come from automatic escalations and thresholds. Flagging
    those would bury the rows where information really was lost.
    """
    project = await _project(session)
    entry = await make_entry(
        session,
        project_id=project.id,
        action="approval.overdue",
        actor_id=None,
        metadata={"hours_overdue": 4, "sla_hours": 24},
    )

    assert await _run(UnattributedEntryRule(), [entry]) == []


# ── clean runs still count as checked ────────────────────────────────────────


@pytest.mark.parametrize("rule_cls", [UnroutableEntryRule, EntryWithoutEntityRule, UnattributedEntryRule])
async def test_a_clean_run_returns_a_passing_result_not_an_empty_list(rule_cls) -> None:
    """An empty result list is indistinguishable from a rule that never ran."""
    results = await rule_cls().validate(ValidationContext(data={"entries": []}))

    assert results, f"{rule_cls.__name__} returned nothing at all on a clean run"
    assert all(r.passed for r in results)
