# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Bridge tests for the NCR clash auto-creation (Lane A).

The NCR module subscribes to ``clash.high_severity.detected`` and raises a
formal NCR for CRITICAL clashes (or reviewer-confirmed ones). High clashes
that are merely detected stay on the clash board (and become a punch item
via the punchlist bridge) so the NCR dashboard is not flooded.

The handler opens its own ``async_session_factory()`` session, gates on
``_can_open_isolated_session`` (PostgreSQL only), and uses ``NCRRepository``
for the running NCR number. We drive it with a DB-free fake session and a
stub repo, mirroring ``test_procurement_events.py`` so the suite runs
without booting PostgreSQL.

The tests are written as files only; per the parallel-run rules they are
not executed here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.events import Event
from app.modules.ncr import events as ncr_events
from app.modules.ncr.models import NCR

# ── Fake session + stub repo ────────────────────────────────────────────────


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
        first_desc = stmt.column_descriptions[0]
        expr = first_desc.get("expr")
        expr_key = getattr(expr, "key", None) if expr is not None else None
        if first_desc.get("entity") is None and expr_key is not None:
            return _Result([getattr(r, expr_key, None) for r in rows])
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
    # The handler imports NCRRepository lazily from the repository module.
    import app.modules.ncr.repository as ncr_repo

    monkeypatch.setattr(ncr_repo, "NCRRepository", _StubNCRRepo)
    # No-op the detached fan-out so the test does not schedule a real task.
    monkeypatch.setattr(ncr_events.event_bus, "publish_detached", lambda *a, **k: None)
    return rows


def _clash_event(
    *,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    severity: str = "critical",
    trigger: str = "created",
) -> Event:
    return Event(
        name="clash.high_severity.detected",
        data={
            "project_id": str(project_id),
            "run_id": str(uuid.uuid4()),
            "result_id": str(result_id),
            "severity": severity,
            "trigger": trigger,
            "clash_type": "hard",
            "a_name": "Duct-3",
            "b_name": "Beam-9",
        },
        source_module="clash",
    )


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_critical_clash_raises_ncr(store: list[NCR]) -> None:
    project_id = uuid.uuid4()
    result_id = uuid.uuid4()
    await ncr_events._on_clash_high_severity(
        _clash_event(project_id=project_id, result_id=result_id, severity="critical")
    )

    assert len(store) == 1
    ncr = store[0]
    assert ncr.project_id == project_id
    assert ncr.clash_result_id == str(result_id)
    assert ncr.severity == "critical"
    assert ncr.ncr_type == "design"
    assert ncr.status == "identified"
    assert "Duct-3" in ncr.title and "Beam-9" in ncr.title
    assert ncr.metadata_["source"] == "clash"
    assert ncr.metadata_["result_id"] == str(result_id)


@pytest.mark.asyncio
async def test_confirmed_high_clash_raises_ncr(store: list[NCR]) -> None:
    """A reviewer-confirmed high clash also warrants an NCR (severity major)."""
    project_id = uuid.uuid4()
    await ncr_events._on_clash_high_severity(
        _clash_event(project_id=project_id, result_id=uuid.uuid4(), severity="high", trigger="confirmed")
    )
    assert len(store) == 1
    assert store[0].severity == "major"


@pytest.mark.asyncio
async def test_high_detected_clash_does_not_raise_ncr(store: list[NCR]) -> None:
    """A merely-detected high clash stays off the NCR dashboard."""
    await ncr_events._on_clash_high_severity(
        _clash_event(project_id=uuid.uuid4(), result_id=uuid.uuid4(), severity="high", trigger="created")
    )
    assert store == []


@pytest.mark.asyncio
async def test_clash_ncr_replay_is_idempotent(store: list[NCR]) -> None:
    project_id = uuid.uuid4()
    result_id = uuid.uuid4()
    event = _clash_event(project_id=project_id, result_id=result_id, severity="critical")

    await ncr_events._on_clash_high_severity(event)
    await ncr_events._on_clash_high_severity(event)

    assert len(store) == 1


@pytest.mark.asyncio
async def test_clash_ncr_missing_ids_is_noop(store: list[NCR]) -> None:
    await ncr_events._on_clash_high_severity(
        Event(name="clash.high_severity.detected", data={"severity": "critical"}, source_module="clash")
    )
    assert store == []
