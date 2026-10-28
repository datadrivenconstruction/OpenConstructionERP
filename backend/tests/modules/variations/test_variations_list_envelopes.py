# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The variations list routes describe how much of themselves they return.

All seven registers in this module used to answer with a bare
``list[XResponse]``. Each one already received a total from
``<repo>.list_for_project`` and threw it away with ``rows, _ = ...``, so a
project past its fiftieth notice served fifty rows and no way to tell.

Two tests, because there are two different ways to regress this:

#. :func:`test_every_list_route_answers_with_an_envelope` walks the router's
   registered routes. It covers all seven paths including
   ``site-measurements`` and ``disruption-claims``, which no frontend reads
   yet and which the envelope-consumer guard therefore cannot watch. A route
   quietly reverted to ``list[...]`` fails here.

#. :func:`test_the_total_is_the_registers_size_not_the_pages` drives one route
   with a stub repository that returns two rows and a total of 137. That is
   the assertion the shape test cannot make: a route could carry an envelope
   and still fill ``total`` with ``len(rows)``, which reads as an honest page
   and is the exact lie this programme exists to remove.

No database: the repository and the project-scope guard are both stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.modules.variations import router as variations_router

ENVELOPE_FIELDS = {"items", "total", "offset", "limit"}

LIST_ROUTES = [
    "/notices/",
    "/variation-requests/",
    "/variation-orders/",
    "/site-measurements/",
    "/daywork-sheets/",
    "/disruption-claims/",
    "/eot-claims/",
]


def _get_route(path: str) -> Any:
    """The registered GET route for ``path``, or fail naming what was found."""
    for route in variations_router.router.routes:
        if getattr(route, "path", None) == path and "GET" in getattr(route, "methods", set()):
            return route
    available = sorted(str(getattr(r, "path", "")) for r in variations_router.router.routes)
    raise AssertionError(f"no GET route registered at {path}; router has {available}")


@pytest.mark.parametrize("path", LIST_ROUTES)
def test_every_list_route_answers_with_an_envelope(path: str) -> None:
    """A page envelope, not a bare array, on every register in the module."""
    model = _get_route(path).response_model

    assert model is not None, f"{path} declares no response_model"
    # A bare ``list[XResponse]`` is not a class, so this is the check that
    # actually distinguishes the two shapes.
    assert isinstance(model, type) and issubclass(model, BaseModel), (
        f"{path} still answers with {model!r}, which cannot carry a total"
    )
    assert set(model.model_fields) >= ENVELOPE_FIELDS, (
        f"{path} answers with {model.__name__}, missing {sorted(ENVELOPE_FIELDS - set(model.model_fields))}"
    )


def _notice_row() -> SimpleNamespace:
    """The attributes ``NoticeResponse.model_validate`` requires, and no more."""
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        code="VN-001",
        title="Ground conditions differ from the survey",
        description="",
        raised_at=None,
        raised_by=None,
        recipient_type="owner",
        recipient_name="",
        target_response_date=None,
        response_received_at=None,
        response_summary="",
        status="issued",
        reference_change_order_id=None,
        ball_in_court=None,
        response_due_date=None,
        metadata_={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_the_total_is_the_registers_size_not_the_pages(monkeypatch) -> None:
    """``total`` is what the repository counted, never the length of the page."""
    project_id = uuid.uuid4()
    caller = str(uuid.uuid4())
    captured: dict[str, Any] = {}

    async def _fake_verify(project: Any, user: Any, session: Any) -> None:
        captured["project"] = project
        captured["user"] = user

    class _StubRepo:
        async def list_for_project(
            self,
            pid: uuid.UUID,
            *,
            offset: int,
            limit: int,
            status: str | None = None,
        ) -> tuple[list[Any], int]:
            captured["offset"] = offset
            captured["limit"] = limit
            captured["status"] = status
            # Two rows out of a register of 137: the case the whole programme
            # is about. A route filling `total` from `len(rows)` returns 2.
            return [_notice_row(), _notice_row()], 137

    monkeypatch.setattr(variations_router, "verify_project_access", _fake_verify)

    result = await variations_router.list_notices(
        # Never touched: the only thing that would use the session is
        # ``verify_project_access``, and that is stubbed above.
        session=object(),  # type: ignore[arg-type]
        project_id=project_id,
        user_id=caller,
        offset=0,
        limit=50,
        status="issued",
        _perm=None,
        service=SimpleNamespace(notice_repo=_StubRepo()),  # type: ignore[arg-type]
    )

    # The project-scope guard runs against the caller's project.
    assert captured["project"] == project_id
    assert captured["user"] == caller

    # The page is echoed back as asked for, so a client can tell where it is.
    assert result.offset == 0
    assert result.limit == 50
    assert len(result.items) == 2

    # The point of the wave.
    assert result.total == 137
    assert result.total != len(result.items)

    # The count is taken over the SAME filter as the page. A total counted
    # without the status filter would describe a different register than the
    # one on screen, which is worse than no total at all.
    assert captured["status"] == "issued"
