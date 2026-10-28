# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Bridge tests for the punchlist clash/inspection auto-creation (Lane A).

The punchlist module subscribes to two upstream signals and materialises
site-actionable punch items:

* ``clash.high_severity.detected`` -> one punch item per clash, idempotent
  on ``PunchItem.clash_result_id``.
* ``inspection.completed.failed`` -> one punch item per failed checklist
  item, idempotent on the (inspection_id, item-key) pair in ``metadata_``.

Both handlers open their own ``async_session_factory()`` session, so we
drive them with a DB-free fake session that records added rows and answers
the idempotency probe. This mirrors ``test_procurement_events.py`` and keeps
the suite runnable without booting PostgreSQL.

The tests are written as files only; per the parallel-run rules they are
not executed here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.events import Event
from app.modules.punchlist import events as punch_events
from app.modules.punchlist.models import PunchItem

# ── Fake session ────────────────────────────────────────────────────────────


class _Result:
    """Minimal mimic of a SQLAlchemy ``Result`` over an in-memory list."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Async-context session backed by an in-memory list of PunchItem rows."""

    def __init__(self, store: list[PunchItem]) -> None:
        self.store = store
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, stmt: Any) -> _Result:
        # The handlers issue two shapes of query:
        #   select(PunchItem.id).where(project_id == .., clash_result_id == ..)
        #   select(PunchItem.metadata_).where(project_id == ..)
        crit = _criteria(stmt)
        rows = list(self.store)
        for col, val in crit:
            rows = [r for r in rows if getattr(r, col, None) == val]

        first_desc = stmt.column_descriptions[0]
        expr = first_desc.get("expr")
        entity = first_desc.get("entity")
        expr_key = getattr(expr, "key", None) if expr is not None else None
        # Column projection (e.g. select(PunchItem.id) / select(PunchItem.metadata_)):
        # the selected expr is a column attribute, not the whole entity class.
        # (entity stays PunchItem for a column select, so test on expr identity.)
        if expr_key is not None and expr is not entity:
            return _Result([getattr(r, expr_key, None) for r in rows])
        return _Result(rows)

    def add(self, obj: PunchItem) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.store.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


def _criteria(stmt: Any) -> list[tuple[str, Any]]:
    """Flatten a statement's WHERE clause into ``(column_key, value)`` pairs."""
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


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> list[PunchItem]:
    """Wire the punchlist handlers to a fresh in-memory store."""
    rows: list[PunchItem] = []
    monkeypatch.setattr(punch_events, "async_session_factory", lambda: _FakeSession(rows))
    return rows


# ── clash.high_severity.detected -> punch item ─────────────────────────────


def _clash_event(
    *,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    severity: str = "high",
) -> Event:
    return Event(
        name="clash.high_severity.detected",
        data={
            "project_id": str(project_id),
            "run_id": str(uuid.uuid4()),
            "result_id": str(result_id),
            "severity": severity,
            "trigger": "created",
            "clash_type": "hard",
            "a_name": "Wall-12",
            "b_name": "Pipe-7",
            "assigned_to": "",
            "watchers": [],
            "actor": "",
        },
        source_module="clash",
    )


@pytest.mark.asyncio
async def test_clash_creates_punch_item(store: list[PunchItem]) -> None:
    project_id = uuid.uuid4()
    result_id = uuid.uuid4()
    await punch_events._on_clash_high_severity(_clash_event(project_id=project_id, result_id=result_id))

    assert len(store) == 1
    punch = store[0]
    assert punch.project_id == project_id
    assert punch.clash_result_id == str(result_id)
    assert punch.priority == "high"
    assert punch.status == "open"
    assert "Wall-12" in punch.title and "Pipe-7" in punch.title
    assert punch.metadata_["source"] == "clash"
    assert punch.metadata_["result_id"] == str(result_id)


@pytest.mark.asyncio
async def test_clash_critical_maps_to_critical_priority(store: list[PunchItem]) -> None:
    project_id = uuid.uuid4()
    await punch_events._on_clash_high_severity(
        _clash_event(project_id=project_id, result_id=uuid.uuid4(), severity="critical")
    )
    assert store[0].priority == "critical"


@pytest.mark.asyncio
async def test_clash_replay_is_idempotent(store: list[PunchItem]) -> None:
    project_id = uuid.uuid4()
    result_id = uuid.uuid4()
    event = _clash_event(project_id=project_id, result_id=result_id)

    await punch_events._on_clash_high_severity(event)
    await punch_events._on_clash_high_severity(event)

    assert len(store) == 1


@pytest.mark.asyncio
async def test_clash_missing_ids_is_noop(store: list[PunchItem]) -> None:
    await punch_events._on_clash_high_severity(
        Event(name="clash.high_severity.detected", data={"severity": "high"}, source_module="clash")
    )
    assert store == []


# ── inspection.completed.failed -> punch item(s) ───────────────────────────


def _inspection_event(
    *,
    project_id: uuid.UUID,
    inspection_id: uuid.UUID,
    failed_items: list[dict[str, Any]],
) -> Event:
    return Event(
        name="inspection.completed.failed",
        data={
            "project_id": str(project_id),
            "inspection_id": str(inspection_id),
            "inspection_number": "INS-007",
            "result": "fail",
            "failed_items": failed_items,
        },
        source_module="inspections",
    )


@pytest.mark.asyncio
async def test_inspection_creates_one_punch_per_failed_item(store: list[PunchItem]) -> None:
    project_id = uuid.uuid4()
    inspection_id = uuid.uuid4()
    failed = [
        {"id": "q1", "question": "Rebar spacing correct?", "response": "fail", "critical": True},
        {"id": "q2", "question": "Concrete cover adequate?", "response": "no", "notes": "20mm short"},
    ]
    await punch_events._on_inspection_completed_failed(
        _inspection_event(project_id=project_id, inspection_id=inspection_id, failed_items=failed)
    )

    assert len(store) == 2
    titles = {p.title for p in store}
    assert "Rebar spacing correct?" in titles
    assert "Concrete cover adequate?" in titles
    # Critical checklist item -> critical priority; others -> high.
    by_title = {p.title: p for p in store}
    assert by_title["Rebar spacing correct?"].priority == "critical"
    assert by_title["Concrete cover adequate?"].priority == "high"
    for p in store:
        assert p.metadata_["source"] == "inspection"
        assert p.metadata_["inspection_id"] == str(inspection_id)
        assert p.metadata_["item_key"]
    assert "20mm short" in by_title["Concrete cover adequate?"].description


@pytest.mark.asyncio
async def test_inspection_replay_is_idempotent(store: list[PunchItem]) -> None:
    project_id = uuid.uuid4()
    inspection_id = uuid.uuid4()
    failed = [
        {"id": "q1", "question": "Rebar spacing correct?", "response": "fail"},
        {"id": "q2", "question": "Concrete cover adequate?", "response": "fail"},
    ]
    event = _inspection_event(project_id=project_id, inspection_id=inspection_id, failed_items=failed)

    await punch_events._on_inspection_completed_failed(event)
    await punch_events._on_inspection_completed_failed(event)

    assert len(store) == 2


@pytest.mark.asyncio
async def test_inspection_empty_failed_items_is_noop(store: list[PunchItem]) -> None:
    await punch_events._on_inspection_completed_failed(
        _inspection_event(project_id=uuid.uuid4(), inspection_id=uuid.uuid4(), failed_items=[])
    )
    assert store == []
