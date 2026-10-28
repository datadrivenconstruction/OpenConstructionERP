# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The event-bus bridge: which events become rows, and what those rows carry.

``_record_event`` opens its own session through ``async_session_factory``,
which the rolled-back test session cannot intercept. These tests therefore
drive the mapping and the write decision directly and assert on the row the
bridge would build, rather than committing to the shared database from a
detached session and leaking rows into every later test.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.timeline import mapping

pytestmark = pytest.mark.asyncio


def _bridge_row(event_name: str, data: dict) -> dict | None:
    """What the bridge would write, or None when it would write nothing."""
    if not mapping.is_significant(event_name):
        return None
    mapped = mapping.map_event(event_name, data)
    if mapped is None or not mapping.is_routable(mapped):
        return None
    return mapped


async def test_a_significant_event_becomes_a_row() -> None:
    project = str(uuid.uuid4())
    ncr = str(uuid.uuid4())

    row = _bridge_row("ncr.created", {"project_id": project, "ncr_id": ncr})

    assert row is not None
    assert row["action"] == "ncr.created"
    assert row["module"] == "ncr"
    assert row["entity_type"] == "ncr"
    assert row["entity_id"] == ncr
    assert row["parent_entity_type"] == "project"
    assert row["parent_entity_id"] == project


async def test_an_insignificant_event_writes_nothing() -> None:
    assert _bridge_row("erp_chat.message.created", {"project_id": "p", "id": "m"}) is None
    assert _bridge_row("notifications.dispatch", {"project_id": "p"}) is None


async def test_an_event_with_no_project_and_no_entity_writes_nothing() -> None:
    """The bridge drops rows nothing could ever read.

    Recording them costs an insert and then reads as coverage forever: the row
    exists, so the register looks populated, but no project feed and no record
    history can select it.
    """
    assert _bridge_row("ncr.created", {"ncr_number": "N-1"}) is None


async def test_a_row_keeps_the_full_event_payload() -> None:
    row = _bridge_row(
        "safety.incident.created",
        {"project_id": "p", "incident_id": "i-1", "severity": "high", "injured": 2},
    )

    assert row is not None
    assert row["metadata"]["severity"] == "high"
    assert row["metadata"]["injured"] == 2


async def test_the_row_does_not_alias_the_publisher_payload() -> None:
    """Mutating the mapped metadata must not reach back into the event."""
    payload = {"project_id": "p", "incident_id": "i-1", "severity": "high"}

    row = _bridge_row("safety.incident.created", payload)
    row["metadata"]["severity"] = "tampered"

    assert payload["severity"] == "high"


async def test_the_row_records_the_actor_when_the_event_names_one() -> None:
    actor = uuid.uuid4()

    row = _bridge_row("ncr.created", {"project_id": "p", "ncr_id": "n", "created_by": str(actor)})

    assert row["actor_id"] == actor


async def test_families_the_publishers_actually_use_are_captured() -> None:
    """Spot-check the names that the old guessed allowlist missed entirely.

    Each of these is published in ``app/``; none of them matched the sixteen
    prefixes the module shipped with.
    """
    for name in (
        "changeorders.candidate_from_moc",
        "schedule_advanced.actuals_update",
        "qms.ncr.raised",
        "contracts.contract.signed",
        "safety.incident.created",
        "subcontractors.defect.recorded",
        "credentials.expiry.alert",
    ):
        assert mapping.is_significant(name), f"{name} is published but not captured"


async def test_the_names_the_old_allowlist_guessed_at_are_gone() -> None:
    """Nothing publishes these, so matching them was never coverage."""
    for name in (
        "changeorder.approved",
        "rfi.created",
        "schedule.baseline.set",
        "transmittal.issued",
        "submittal.approved",
        "delay.logged",
        "handover.completed",
        "clash.resolved",
        "budget.revised",
    ):
        assert not mapping.is_significant(name), f"{name} matches the allowlist but is never published"
