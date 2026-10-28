# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The wave-eight registers describe how much of themselves they return.

Eleven routes across seven modules moved from a bare ``list[XResponse]`` to
``{items, total, offset, limit}``: the ten this wave ranked by user impact, plus
``equipment/fuel-logs``, which was finished because it already carried a total
but which no screen reads. Every one of them already received a total
from its repository and threw it away with ``items, _ = ...``, so a site past
its fiftieth timesheet, ticket or incident was served fifty rows and no way to
tell that was not all of them.

Two tests, because there are two different ways to regress this:

#. :func:`test_every_migrated_route_answers_with_an_envelope` walks each
   router's registered routes. It covers ``equipment/fuel-logs``, which no
   frontend reads and which the envelope-consumer guard therefore cannot watch
   at all. A route quietly reverted to ``list[...]`` fails here.

#. :func:`test_the_total_is_the_registers_size_not_the_pages` drives one route
   with a stub repository that returns two rows and a total of 137. That is the
   assertion the shape test cannot make: a route could carry an envelope and
   still fill ``total`` with ``len(items)``, which reads as an honest page and
   is the exact lie this programme exists to remove.

No database: the repository, the service and the project-scope guard are all
stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.modules.equipment import router as equipment_router
from app.modules.field_time import router as field_time_router
from app.modules.safety import router as safety_router
from app.modules.service import router as service_router
from app.modules.subcontractors import router as subcontractors_router
from app.modules.supplier_catalogs import router as supplier_catalogs_router
from app.modules.tasks import router as tasks_router

ENVELOPE_FIELDS = {"items", "total", "offset", "limit"}

# (module under test, path as the router registers it). The path, not the
# function name: the function could be renamed and still answer on the route,
# and it is the route a caller holds.
MIGRATED_ROUTES = [
    (subcontractors_router, "/subcontractors/"),
    (supplier_catalogs_router, "/catalog-items"),
    (supplier_catalogs_router, "/vendors"),
    (field_time_router, "/timesheets/"),
    (safety_router, "/incidents/"),
    (service_router, "/tickets/"),
    (service_router, "/work-orders/"),
    (equipment_router, "/maintenance-work-orders/"),
    (equipment_router, "/fuel-logs/"),
    (tasks_router, "/"),
    (tasks_router, "/my-tasks/"),
]


def _get_route(module: Any, path: str) -> Any:
    """The registered GET route for ``path``, or fail naming what was found."""
    for route in module.router.routes:
        if getattr(route, "path", None) == path and "GET" in getattr(route, "methods", set()):
            return route
    available = sorted(str(getattr(r, "path", "")) for r in module.router.routes)
    raise AssertionError(f"no GET route registered at {path} in {module.__name__}; router has {available}")


@pytest.mark.parametrize(
    ("module", "path"),
    MIGRATED_ROUTES,
    ids=[f"{m.__name__.split('.')[-2]}{p}" for m, p in MIGRATED_ROUTES],
)
def test_every_migrated_route_answers_with_an_envelope(module: Any, path: str) -> None:
    """A page envelope, not a bare array, on every register moved in this wave."""
    model = _get_route(module, path).response_model

    assert model is not None, f"{path} declares no response_model"
    # A bare ``list[XResponse]`` is not a class, so this is the check that
    # actually distinguishes the two shapes.
    assert isinstance(model, type) and issubclass(model, BaseModel), (
        f"{path} answers with {model!r}, which cannot carry a total"
    )
    assert set(model.model_fields) >= ENVELOPE_FIELDS, (
        f"{path} answers with {model.__name__}, missing {sorted(ENVELOPE_FIELDS - set(model.model_fields))}"
    )


def _subcontractor_row() -> SimpleNamespace:
    """The attributes ``SubcontractorResponse.model_validate`` requires, and no more."""
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        contact_id=None,
        legal_name="Meridian Groundworks",
        trade_name=None,
        tax_id=None,
        trade_categories=[],
        prequalification_status="approved",
        rating_score=0,
        country=None,
        address=None,
        website=None,
        notes=None,
        is_active=True,
        prequal_score=None,
        insurance_expiry_date=None,
        insurance_doc_id=None,
        prequal_questionnaire=None,
        prequal_completed_at=None,
        blocked_reason=None,
        is_blocked=False,
        created_by=None,
        metadata_={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_the_total_is_the_registers_size_not_the_pages(monkeypatch) -> None:
    """``total`` is what the repository counted, never the length of the page."""
    captured: dict[str, Any] = {}

    class _StubRepo:
        async def list_all(
            self,
            *,
            offset: int,
            limit: int,
            prequalification_status: str | None = None,
            trade_category: str | None = None,
            active_only: bool = True,
        ) -> tuple[list[Any], int]:
            captured["offset"] = offset
            captured["limit"] = limit
            captured["prequalification_status"] = prequalification_status
            captured["active_only"] = active_only
            # Two rows out of a yard of 137: the case the whole programme is
            # about. A route filling `total` from `len(items)` returns 2.
            return [_subcontractor_row(), _subcontractor_row()], 137

    monkeypatch.setattr(
        subcontractors_router,
        "SubcontractorService",
        lambda _session: SimpleNamespace(subs=_StubRepo()),
    )

    result = await subcontractors_router.list_subcontractors(
        # Never touched: the service is stubbed above and nothing else in the
        # handler reads the session.
        session=object(),  # type: ignore[arg-type]
        _user=str(uuid.uuid4()),
        offset=0,
        limit=50,
        prequalification_status="approved",
        trade_category=None,
        active_only=True,
        _perm=None,
    )

    # The page is echoed back as asked for, so a client can tell where it is.
    assert result.offset == 0
    assert result.limit == 50
    assert len(result.items) == 2

    # The point of the wave.
    assert result.total == 137
    assert result.total != len(result.items)

    # The count is taken over the SAME filters as the page. A total counted
    # without them would describe a different register than the one on screen,
    # which is worse than no total at all.
    assert captured["prequalification_status"] == "approved"
    assert captured["active_only"] is True


@pytest.mark.asyncio
async def test_a_route_that_filters_in_memory_counts_what_it_filtered(monkeypatch) -> None:
    """The tasks BIM branch narrows in Python, so its total is the narrowed set.

    This branch never reaches the repository's count. It loads every task
    carrying the element id, applies the remaining filters in memory and slices
    a page out of the result, so the honest denominator is the length of that
    result rather than anything the database counted. Left as ``len(items)`` it
    would have claimed a five-task element had five tasks when the page held
    two of nine.
    """
    project_id = uuid.uuid4()
    caller = str(uuid.uuid4())

    def _task(status: str) -> SimpleNamespace:
        now = datetime.now(UTC)
        return SimpleNamespace(
            id=uuid.uuid4(),
            project_id=project_id,
            title="Seal the penetration",
            description="",
            result=None,
            task_type="defect",
            status=status,
            priority="normal",
            responsible_id=None,
            meeting_id=None,
            milestone_id=None,
            due_date=None,
            checklist=[],
            persons_involved=[],
            is_private=False,
            bim_element_ids=["e-1"],
            metadata_={},
            created_by=caller,
            created_at=now,
            updated_at=now,
        )

    # Nine carry the element, four of them open. The route asks for two.
    rows = [_task("open") for _ in range(4)] + [_task("done") for _ in range(5)]

    async def _fake_verify(project: Any, user: Any, session: Any) -> None:
        return None

    class _StubService:
        async def get_tasks_for_bim_element(
            self,
            element_id: str,
            *,
            project_id: uuid.UUID,
            current_user_id: str,
        ) -> list[Any]:
            return rows

        async def resolve_assignee_names(self, tasks: list[Any]) -> dict[str, str]:
            return {}

    monkeypatch.setattr(tasks_router, "verify_project_access", _fake_verify)

    result = await tasks_router.list_tasks(
        session=object(),  # type: ignore[arg-type]
        project_id=project_id,
        user_id=caller,
        offset=0,
        limit=2,
        type_filter=None,
        status_filter="open",
        priority=None,
        responsible_id=None,
        meeting_id=None,
        bim_element_id="e-1",
        search=None,
        service=_StubService(),  # type: ignore[arg-type]
    )

    assert len(result.items) == 2
    # Four matched the status filter, not nine and not two.
    assert result.total == 4
