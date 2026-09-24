# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The AIA G702/G703 PDF is drawn in a worker thread, not on the event loop.

ReportLab lays the form out synchronously. Called straight from the async
route, a long continuation sheet held the event loop for as long as it took
to draw, and every other request on the worker waited behind it. The BOQ PDF
exports already hand the same kind of work to ``asyncio.to_thread``.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest

from app.modules.contracts import aia_pdf
from app.modules.contracts import router as contracts_router


async def test_the_aia_pdf_is_rendered_in_a_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    drawn_on: list[int] = []

    def _render(payload: dict[str, Any]) -> bytes:
        drawn_on.append(threading.get_ident())
        return b"%PDF-1.4 stub"

    async def _allowed(*_args: Any, **_kwargs: Any) -> None:
        return None

    class _Service:
        def __init__(self, _session: Any) -> None:
            pass

        async def build_aia_application(self, _claim_id: uuid.UUID, *, locale: str) -> dict[str, Any]:
            return {"application_number": "7"}

    monkeypatch.setattr(aia_pdf, "render_aia_application_pdf", _render)
    monkeypatch.setattr(contracts_router, "_verify_claim_access", _allowed)
    monkeypatch.setattr(contracts_router, "ContractsService", _Service)

    response = await contracts_router.export_aia_application_pdf(uuid.uuid4(), None, "user")  # type: ignore[arg-type]

    assert response.media_type == "application/pdf"
    assert drawn_on, "the renderer was never called"
    assert drawn_on[0] != loop_thread
