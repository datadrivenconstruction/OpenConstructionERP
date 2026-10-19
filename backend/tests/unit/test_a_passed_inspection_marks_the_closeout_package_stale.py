"""A passed inspection is closure evidence, so it makes a built closeout package stale.

The closeout module clears a project's built package (and drops ``ready`` or
``issued`` back to ``in_progress``) whenever closure evidence changes, so the
handover bundle is never handed over without the latest records. It listened
for ``inspection.completed.passed`` next to the failed variant, but the
inspections service published only failures. A package built before the last
inspections passed stayed ``ready`` without them.

The test completes an inspection through the real service, captures what it
publishes, and replays it through a bus wired by closeout's own registrar.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

import app.modules.closeout.events as closeout_events
from app.core.events import EventBus, event_bus
from app.modules.inspections.schemas import InspectionCreate
from app.modules.inspections.service import InspectionService

PROJECT = uuid.uuid4()


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        return None


class _StubRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, row: Any) -> Any:
        row.id = uuid.uuid4()
        row.inspection_number = "INS-001"
        row.created_at = row.updated_at = datetime.now(UTC)
        self.rows[row.id] = row
        return row

    async def get_by_id(self, row_id: uuid.UUID) -> Any:
        return self.rows.get(row_id)

    async def update_fields(self, row_id: uuid.UUID, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.rows[row_id], key, value)


def _service() -> InspectionService:
    service = InspectionService.__new__(InspectionService)
    service.session = _StubSession()
    service.repo = _StubRepo()
    return service


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []

    def _capture(name: str, data: dict[str, Any] | None = None, source_module: str | None = None) -> None:
        seen.append((name, dict(data or {})))

    monkeypatch.setattr(event_bus, "publish_detached", _capture)
    return seen


@pytest.fixture
def package(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A built, ready closeout package for the project, held in memory."""
    built = SimpleNamespace(
        id=uuid.uuid4(),
        package_key="closeout/abc.zip",
        last_built_at=datetime.now(UTC),
        last_built_job_id=uuid.uuid4(),
        status="ready",
    )

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def add(self, obj: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    class _Repo:
        def __init__(self, session: Any) -> None:
            return None

        async def get_package_for_project(self, project_id: uuid.UUID) -> Any:
            return built if project_id == PROJECT else None

    monkeypatch.setattr(closeout_events, "async_session_factory", _Session)
    monkeypatch.setattr(closeout_events, "CloseoutRepository", _Repo)
    return built


@pytest.fixture
def closeout_bus(monkeypatch: pytest.MonkeyPatch) -> EventBus:
    bus = EventBus()
    monkeypatch.setattr(closeout_events, "event_bus", bus)
    closeout_events.register_closeout_subscribers()
    return bus


async def _complete(result: str) -> Any:
    service = _service()
    inspection = await service.create_inspection(
        InspectionCreate(project_id=PROJECT, inspection_type="handover", title="Final walk")
    )
    return await service.complete_inspection(inspection.id, result)


@pytest.mark.asyncio
async def test_a_passed_inspection_marks_the_built_package_stale(published, package, closeout_bus) -> None:
    inspection = await _complete("pass")

    passed = [data for name, data in published if name == "inspection.completed.passed"]
    assert passed == [
        {
            "project_id": str(PROJECT),
            "inspection_id": str(inspection.id),
            "inspection_number": "INS-001",
            "result": "pass",
        }
    ]
    for name, data in published:
        await closeout_bus.publish(name, data, source_module="test")

    assert (package.package_key, package.last_built_at, package.status) == (None, None, "in_progress")


@pytest.mark.asyncio
async def test_a_failed_inspection_does_not_also_claim_to_have_passed(published, package, closeout_bus) -> None:
    await _complete("fail")

    assert [name for name, _ in published] == ["inspection.completed.failed"]
