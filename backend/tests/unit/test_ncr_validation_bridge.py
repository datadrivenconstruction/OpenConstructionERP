# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Bridge tests for NCR auto-creation from validation errors (Wave 2).

The NCR module subscribes to ``validation.results.errors_found`` and raises a
single formal NCR per validation run that produced ERROR-severity results. A
blocking validation error is a data/documentation non-conformance that belongs
in the NCR workflow (root cause, corrective action, sign-off).

The handler opens its own ``async_session_factory()`` session, gates on
``_can_open_isolated_session`` (PostgreSQL only) and uses ``NCRRepository`` for
the running NCR number. We drive it with a DB-free fake session and a stub repo,
mirroring ``test_ncr_clash_bridge.py`` so the suite runs without booting
PostgreSQL. Idempotency is on ``metadata_['report_id']`` so a replay of the same
report never raises a duplicate, but a fresh run (new report id) does.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.events import Event
from app.modules.ncr import events as ncr_events
from app.modules.ncr.models import NCR


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


def _criteria(stmt: Any) -> list[tuple[str, Any]]:
    where = stmt.whereclause
    if where is None:
        return []
    clauses = list(where.clauses) if hasattr(where, "clauses") else [where]
    out: list[tuple[str, Any]] = []
    for crit in clauses:
        col = getattr(getattr(crit, "left", None), "key", None)
        val = getattr(getattr(crit, "right", None), "value", None)
        if col is not None:
            out.append((col, val))
    return out


class _FakeSession:
    def __init__(self, store: list[NCR]) -> None:
        self.store = store
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, stmt: Any) -> _Result:
        rows = list(self.store)
        for col, val in _criteria(stmt):
            rows = [r for r in rows if getattr(r, col, None) == val]
        return _Result(rows)

    def add(self, obj: NCR) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.store.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class _StubNCRRepo:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def next_ncr_number(self, _project_id: uuid.UUID) -> str:
        return f"NCR-{len(self.session.store) + 1:03d}"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> list[NCR]:
    """Wire the NCR handler to a fresh in-memory store + open the PG gate."""
    rows: list[NCR] = []

    async def _gate_open() -> bool:
        return True

    monkeypatch.setattr(ncr_events, "async_session_factory", lambda: _FakeSession(rows))
    monkeypatch.setattr(ncr_events, "_can_open_isolated_session", _gate_open)
    import app.modules.ncr.repository as ncr_repo

    monkeypatch.setattr(ncr_repo, "NCRRepository", _StubNCRRepo)
    monkeypatch.setattr(ncr_events.event_bus, "publish_detached", lambda *a, **k: None)
    return rows


def _validation_event(
    *,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    error_count: int = 2,
) -> Event:
    return Event(
        name="validation.results.errors_found",
        data={
            "project_id": str(project_id),
            "report_id": str(report_id),
            "target_type": "boq",
            "target_id": str(uuid.uuid4()),
            "rule_set": "boq_quality+din276",
            "error_count": error_count,
            "errors": [
                {
                    "rule_id": "boq_quality.zero_price",
                    "rule_name": "Zero unit price",
                    "message": "Position 01.02 has a zero unit price.",
                    "element_ref": "pos-01-02",
                },
                {
                    "rule_id": "din276.cost_group_required",
                    "rule_name": "Cost group required",
                    "message": "Position 02.01 has no DIN 276 cost group.",
                    "element_ref": "pos-02-01",
                },
            ][:error_count],
        },
        source_module="oe_validation",
    )


@pytest.mark.asyncio
async def test_validation_errors_raise_ncr(store: list[NCR]) -> None:
    project_id = uuid.uuid4()
    report_id = uuid.uuid4()
    await ncr_events._on_validation_errors_found(
        _validation_event(project_id=project_id, report_id=report_id, error_count=2)
    )

    assert len(store) == 1
    ncr = store[0]
    assert ncr.project_id == project_id
    assert ncr.ncr_type == "documentation"
    assert ncr.severity == "major"
    assert ncr.status == "identified"
    assert "2" in ncr.title
    assert ncr.metadata_["source"] == "validation"
    assert ncr.metadata_["report_id"] == str(report_id)
    assert ncr.metadata_["error_count"] == 2
    # The blocking error messages are carried for the corrective-action workflow.
    assert "zero unit price" in ncr.description.lower()


@pytest.mark.asyncio
async def test_validation_ncr_replay_is_idempotent(store: list[NCR]) -> None:
    project_id = uuid.uuid4()
    report_id = uuid.uuid4()
    event = _validation_event(project_id=project_id, report_id=report_id)

    await ncr_events._on_validation_errors_found(event)
    await ncr_events._on_validation_errors_found(event)

    assert len(store) == 1


@pytest.mark.asyncio
async def test_validation_new_report_raises_second_ncr(store: list[NCR]) -> None:
    """A fresh validation run (new report id) is a new non-conformance."""
    project_id = uuid.uuid4()
    await ncr_events._on_validation_errors_found(_validation_event(project_id=project_id, report_id=uuid.uuid4()))
    await ncr_events._on_validation_errors_found(_validation_event(project_id=project_id, report_id=uuid.uuid4()))
    assert len(store) == 2


@pytest.mark.asyncio
async def test_validation_no_errors_is_noop(store: list[NCR]) -> None:
    await ncr_events._on_validation_errors_found(
        _validation_event(project_id=uuid.uuid4(), report_id=uuid.uuid4(), error_count=0)
    )
    assert store == []


@pytest.mark.asyncio
async def test_validation_missing_ids_is_noop(store: list[NCR]) -> None:
    await ncr_events._on_validation_errors_found(
        Event(
            name="validation.results.errors_found",
            data={"error_count": 3},
            source_module="oe_validation",
        )
    )
    assert store == []
