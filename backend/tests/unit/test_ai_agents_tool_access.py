# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Per-call IDOR guard on the AI-agent data-reading tools (Findings #4 / #6).

The data-reading agent tools (``search_documents``, ``project_cost_summary``,
``read_boq``, ``check_boq_quality``) run OUTSIDE the request cycle, so they
cannot raise ``HTTPException`` the way a route guard does. Instead each one
must, BEFORE touching any data, verify that the run's *trusted* invoking user
(threaded in via ``__agent_context__``) owns or belongs to the target
project/BOQ and, when it does not, return its own "cannot read" observation
WITHOUT reading a single row - so the LLM reasons "I have no access" and a
cross-tenant resource's existence is never revealed.

These are pure unit tests (no DB, no FastAPI, no network), matching the
convention in ``test_ai_agents.py``: the access primitive and the underlying
data fetch are monkeypatched so we can assert two things precisely -

* a context user who does NOT own/belong to the target gets the no-access
  observation AND the data layer is never called (no leak); and
* the owner (access granted) still flows through to the real data fetch.

Each tool reads the access helper by the name it imported, so we patch that
module-local name (``<module>.assert_user_can_access_project``).
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

import pytest

from app.modules.ai_agents.agents import (
    document_analyst,
    estimate_reviewer,
    project_analyst,
)

# ── Shared fakes ───────────────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def _fake_session_factory():
    """Stand-in for ``async_session_factory()`` - yields a sentinel session.

    The tools only pass the session through to the (monkeypatched) access
    helper and data fetch, so the object itself is never used directly.
    """
    yield object()


class _Tripwire:
    """Records whether it was awaited - proves the data layer was NOT reached.

    Used to assert that a denied access check short-circuits BEFORE any real
    data read (positions, dashboard, document index) happens.
    """

    def __init__(self, result: Any = None) -> None:
        self.called = False
        self._result = result

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.called = True
        return self._result


def _ctx(user_id: uuid.UUID | str) -> dict[str, str]:
    """A trusted runner context carrying the invoking user id."""
    return {"user_id": str(user_id)}


async def _grant(*_a: Any, **_k: Any) -> bool:
    """Patched access helper that GRANTS access (owner / member)."""
    return True


async def _deny(*_a: Any, **_k: Any) -> bool:
    """Patched access helper that DENIES access (cross-tenant / not a member)."""
    return False


# ── search_documents (document_analyst) ────────────────────────────────────


@pytest.mark.asyncio
async def test_search_documents_denied_for_foreign_user(monkeypatch):
    """A user with no access gets 'unavailable' and the index is never queried."""
    project_id = uuid.uuid4()
    foreign_user = uuid.uuid4()

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr(document_analyst, "assert_user_can_access_project", _deny)
    # Tripwire on the real content search: it must NOT be reached on denial.
    tripwire = _Tripwire(result=[])
    monkeypatch.setattr("app.modules.file_search.service.search_content", tripwire, raising=False)

    out = await document_analyst._tool_search_documents(
        q="fire rating",
        project_id=str(project_id),
        __agent_context__=_ctx(foreign_user),
    )

    assert out["error"] == "unavailable"
    assert out["matches"] == []
    assert "No access" in out["detail"]
    assert tripwire.called is False  # no data was read


@pytest.mark.asyncio
async def test_search_documents_missing_user_fails_closed(monkeypatch):
    """No user_id in context => fail closed (denied) without any DB access."""
    # If the guard ran, this would explode - prove we never get there.
    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    tripwire_access = _Tripwire(result=True)
    monkeypatch.setattr(document_analyst, "assert_user_can_access_project", tripwire_access)

    out = await document_analyst._tool_search_documents(
        q="anything",
        project_id=str(uuid.uuid4()),
        __agent_context__={},  # no user_id
    )

    assert out["error"] == "unavailable"
    assert tripwire_access.called is False


@pytest.mark.asyncio
async def test_search_documents_owner_reaches_index(monkeypatch):
    """With access granted the tool flows through to the real content search."""
    project_id = uuid.uuid4()
    owner = uuid.uuid4()

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr(document_analyst, "assert_user_can_access_project", _grant)

    # Pretend the project IS indexed (count > 0) so we get past the empty-index
    # branch and into the real search, which we stub to return one hit.
    class _ScalarResult:
        def scalar_one(self) -> int:
            return 1

    class _Session:
        async def execute(self, *_a: Any, **_k: Any) -> _ScalarResult:
            return _ScalarResult()

    @contextlib.asynccontextmanager
    async def _indexed_session_factory():
        yield _Session()

    monkeypatch.setattr("app.database.async_session_factory", _indexed_session_factory, raising=False)

    class _Hit:
        file_id = str(uuid.uuid4())
        canonical_name = "Spec-03.pdf"
        snippet = "concrete cover 40mm"
        score = 0.9

    search = _Tripwire(result=[_Hit()])
    monkeypatch.setattr("app.modules.file_search.service.search_content", search, raising=False)

    out = await document_analyst._tool_search_documents(
        q="cover",
        project_id=str(project_id),
        __agent_context__=_ctx(owner),
    )

    assert search.called is True
    assert out.get("matches")
    assert out["matches"][0]["title_or_filename"] == "Spec-03.pdf"


# ── project_cost_summary (project_analyst) ─────────────────────────────────


@pytest.mark.asyncio
async def test_project_cost_summary_denied_for_foreign_user(monkeypatch):
    """A foreign user gets 'not_found' and the dashboard is never aggregated."""
    project_id = uuid.uuid4()
    foreign_user = uuid.uuid4()

    # A project row that DOES exist (owned by someone else) - proving the guard,
    # not mere absence, is what blocks the read.
    class _Project:
        owner_id = uuid.uuid4()
        name = "Someone Else's Tower"

    class _Repo:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_by_id(self, *_a: Any, **_k: Any) -> _Project:
            return _Project()

    dashboard_tripwire = _Tripwire()

    class _CostService:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_dashboard(self, *a: Any, **k: Any) -> Any:
            return await dashboard_tripwire(*a, **k)

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr(project_analyst, "assert_user_can_access_project", _deny)
    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _Repo, raising=False)
    monkeypatch.setattr("app.modules.costmodel.service.CostModelService", _CostService, raising=False)

    out = await project_analyst._tool_project_cost_summary(
        project_id=str(project_id),
        __agent_context__=_ctx(foreign_user),
    )

    assert out["error"] == "not_found"
    assert dashboard_tripwire.called is False  # no figures were read


@pytest.mark.asyncio
async def test_project_cost_summary_missing_user_fails_closed(monkeypatch):
    """No user_id in context => unavailable, before any project lookup."""
    repo_tripwire = _Tripwire()

    class _Repo:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_by_id(self, *a: Any, **k: Any) -> Any:
            return await repo_tripwire(*a, **k)

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _Repo, raising=False)

    out = await project_analyst._tool_project_cost_summary(
        project_id=str(uuid.uuid4()),
        __agent_context__={"project_id": str(uuid.uuid4())},  # no user_id
    )

    assert out["error"] == "unavailable"
    assert repo_tripwire.called is False


@pytest.mark.asyncio
async def test_project_cost_summary_owner_reaches_dashboard(monkeypatch):
    """With access granted the tool aggregates the real dashboard."""
    project_id = uuid.uuid4()
    owner = uuid.uuid4()

    class _Project:
        owner_id = owner
        name = "My Project"

    class _Repo:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_by_id(self, *_a: Any, **_k: Any) -> _Project:
            return _Project()

    class _Dashboard:
        currency = "EUR"
        mixed_currency = False
        total_budget = "1000"
        total_committed = "400"
        total_actual = "250"
        status = "on_track"

    dashboard = _Tripwire(result=_Dashboard())

    class _CostService:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_dashboard(self, *a: Any, **k: Any) -> Any:
            return await dashboard(*a, **k)

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr(project_analyst, "assert_user_can_access_project", _grant)
    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _Repo, raising=False)
    monkeypatch.setattr("app.modules.costmodel.service.CostModelService", _CostService, raising=False)

    out = await project_analyst._tool_project_cost_summary(
        project_id=str(project_id),
        __agent_context__=_ctx(owner),
    )

    assert dashboard.called is True
    assert out.get("error") is None
    assert out["currency"] == "EUR"
    assert out["total_budget"] == "1000"


# ── read_boq / check_boq_quality (estimate_reviewer) ───────────────────────


class _Position:
    """Minimal stand-in for a ``PositionResponse``."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.parent_id = None
        self.ordinal = "1"
        self.description = "Excavation"
        self.unit = "m3"
        self.quantity = 10
        self.unit_rate = 5
        self.total = 50
        self.classification = None
        self.source = None
        self.metadata = {}


class _Boq:
    """Minimal stand-in for ``BOQWithPositions`` with a known owning project."""

    def __init__(self, project_id: uuid.UUID) -> None:
        self.project_id = project_id
        self.name = "BOQ A"
        self.status = "draft"
        self.position_count = 1
        self.grand_total = 50
        self.direct_cost_total = 50
        self.positions = [_Position()]


def _patch_boq_service(monkeypatch, boq: _Boq, *, currency: str = "EUR") -> _Tripwire:
    """Patch BOQService so get_boq_with_positions returns *boq*.

    Returns a tripwire wrapping ``_resolve_project_currency`` so a test can
    assert whether the post-access read path was reached.
    """
    currency_tripwire = _Tripwire(result=currency)

    class _BOQService:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_boq_with_positions(self, *_a: Any, **_k: Any) -> _Boq:
            return boq

        async def _resolve_project_currency(self, *a: Any, **k: Any) -> str:
            return await currency_tripwire(*a, **k)

    monkeypatch.setattr("app.modules.boq.service.BOQService", _BOQService, raising=False)
    return currency_tripwire


@pytest.mark.asyncio
async def test_read_boq_denied_for_foreign_user(monkeypatch):
    """A foreign user gets 'not_found' and no positions/currency are read."""
    boq = _Boq(project_id=uuid.uuid4())
    foreign_user = uuid.uuid4()

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr(estimate_reviewer, "assert_user_can_access_project", _deny)
    currency_tripwire = _patch_boq_service(monkeypatch, boq)

    out = await estimate_reviewer._tool_read_boq(
        boq_id=str(uuid.uuid4()),
        __agent_context__=_ctx(foreign_user),
    )

    assert out["error"] == "not_found"
    # The currency/positions read happens only AFTER the access check passes.
    assert currency_tripwire.called is False


@pytest.mark.asyncio
async def test_read_boq_missing_user_fails_closed(monkeypatch):
    """No user_id in context => unavailable, before the BOQ is even loaded."""
    load_tripwire = _Tripwire(result=_Boq(project_id=uuid.uuid4()))

    class _BOQService:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_boq_with_positions(self, *a: Any, **k: Any) -> Any:
            return await load_tripwire(*a, **k)

        async def _resolve_project_currency(self, *_a: Any, **_k: Any) -> str:
            return "EUR"

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr("app.modules.boq.service.BOQService", _BOQService, raising=False)

    out = await estimate_reviewer._tool_read_boq(
        boq_id=str(uuid.uuid4()),
        __agent_context__={},  # no user_id
    )

    assert out["error"] == "unavailable"
    assert load_tripwire.called is False


@pytest.mark.asyncio
async def test_read_boq_owner_reaches_positions(monkeypatch):
    """With access granted the tool reads positions and returns the summary."""
    owner = uuid.uuid4()
    boq = _Boq(project_id=uuid.uuid4())

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr(estimate_reviewer, "assert_user_can_access_project", _grant)
    currency_tripwire = _patch_boq_service(monkeypatch, boq)

    out = await estimate_reviewer._tool_read_boq(
        boq_id=str(uuid.uuid4()),
        __agent_context__=_ctx(owner),
    )

    assert out.get("error") is None
    assert currency_tripwire.called is True
    assert out["position_count"] == 1
    assert out["line_items"][0]["currency"] == "EUR"


@pytest.mark.asyncio
async def test_check_boq_quality_denied_for_foreign_user(monkeypatch):
    """A foreign user gets 'not_found' and the validation engine never runs."""
    boq = _Boq(project_id=uuid.uuid4())
    foreign_user = uuid.uuid4()

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr(estimate_reviewer, "assert_user_can_access_project", _deny)
    _patch_boq_service(monkeypatch, boq)

    validate_tripwire = _Tripwire()

    class _Engine:
        async def validate(self, *a: Any, **k: Any) -> Any:
            return await validate_tripwire(*a, **k)

    monkeypatch.setattr("app.core.validation.engine.validation_engine", _Engine(), raising=False)

    out = await estimate_reviewer._tool_check_boq_quality(
        boq_id=str(uuid.uuid4()),
        __agent_context__=_ctx(foreign_user),
    )

    assert out["error"] == "not_found"
    assert validate_tripwire.called is False  # no analysis ran


@pytest.mark.asyncio
async def test_check_boq_quality_missing_user_fails_closed(monkeypatch):
    """No user_id in context => unavailable, before the BOQ is loaded."""
    load_tripwire = _Tripwire(result=_Boq(project_id=uuid.uuid4()))

    class _BOQService:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_boq_with_positions(self, *a: Any, **k: Any) -> Any:
            return await load_tripwire(*a, **k)

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr("app.modules.boq.service.BOQService", _BOQService, raising=False)

    out = await estimate_reviewer._tool_check_boq_quality(
        boq_id=str(uuid.uuid4()),
        __agent_context__={},  # no user_id
    )

    assert out["error"] == "unavailable"
    assert load_tripwire.called is False


@pytest.mark.asyncio
async def test_check_boq_quality_owner_runs_engine(monkeypatch):
    """With access granted the tool runs the validation engine over the BOQ."""
    owner = uuid.uuid4()
    boq = _Boq(project_id=uuid.uuid4())

    monkeypatch.setattr("app.database.async_session_factory", _fake_session_factory, raising=False)
    monkeypatch.setattr(estimate_reviewer, "assert_user_can_access_project", _grant)
    _patch_boq_service(monkeypatch, boq)

    class _Report:
        results: list[Any] = []
        engine_errors: list[Any] = []
        errors: list[Any] = []
        warnings: list[Any] = []
        infos: list[Any] = []

        class status:  # noqa: N801 - mimic enum-with-.value shape
            value = "passed"

        score = 100

    validate = _Tripwire(result=_Report())

    class _Engine:
        async def validate(self, *a: Any, **k: Any) -> Any:
            return await validate(*a, **k)

    monkeypatch.setattr("app.core.validation.engine.validation_engine", _Engine(), raising=False)

    out = await estimate_reviewer._tool_check_boq_quality(
        boq_id=str(uuid.uuid4()),
        __agent_context__=_ctx(owner),
    )

    assert validate.called is True
    assert out.get("error") is None
    assert out["summary"]["positions_checked"] == 1
