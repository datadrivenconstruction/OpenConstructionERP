# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A missing event project is not permission to reach every scoped endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.integrations.service import WebhookService

PROJECT = UUID("442de1ad-26f6-4c53-888b-e09b48dd294b")
OTHER = UUID("f9b90b91-a0b3-41ed-be69-1a7d28c4e7c6")


@pytest.mark.parametrize("project_id", [None, "", "not-a-uuid", [], {}, str(OTHER)])
async def test_unknown_or_different_project_reaches_global_hooks_only(project_id):
    scoped = SimpleNamespace(project_id=PROJECT, events=["*"])
    global_hook = SimpleNamespace(project_id=None, events=["*"])
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [scoped, global_hook]))
    service = WebhookService(SimpleNamespace(execute=AsyncMock(return_value=result)))
    service._deliver = AsyncMock()  # No HTTP/DNS, even when the old filter leaks.

    count = await service.dispatch_event("ncr.created", {"test": True}, project_id=project_id)

    assert count == 1
    service._deliver.assert_awaited_once_with(global_hook, "ncr.created", {"test": True})


@pytest.mark.parametrize("project_id", [PROJECT, str(PROJECT)])
async def test_matching_project_reaches_its_scoped_and_global_hooks(project_id):
    scoped = SimpleNamespace(project_id=PROJECT, events=["ncr.created"])
    global_hook = SimpleNamespace(project_id=None, events=["*"])
    other = SimpleNamespace(project_id=OTHER, events=["*"])
    wrong_event = SimpleNamespace(project_id=PROJECT, events=["invoice.paid"])
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [scoped, global_hook, other, wrong_event]))
    service = WebhookService(SimpleNamespace(execute=AsyncMock(return_value=result)))
    service._deliver = AsyncMock()

    count = await service.dispatch_event("ncr.created", {"test": True}, project_id=project_id)

    assert count == 2
    assert [call.args[0] for call in service._deliver.await_args_list] == [scoped, global_hook]
