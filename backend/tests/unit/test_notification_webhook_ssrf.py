# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A notification webhook target cannot point the server at an internal address.

The integrations module's webhooks pass every URL through ``url_safety`` when
it is saved and again right before it is sent. The notification module keeps a
second, separate list of webhook targets, and its URL was checked only for an
``http(s)://`` prefix, so a target could name the loopback interface, a LAN
host or the cloud metadata address and the dispatcher would POST every event
there. Both halves are closed here: the schema refuses such a URL, and the
dispatcher re-resolves the stored URL before each delivery, which also covers
targets saved before the schema check existed and names that resolve inward.
"""

from __future__ import annotations

import unittest.mock
import uuid

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import WebhookTarget
from app.modules.notifications.schemas import WebhookTargetCreate, WebhookTargetUpdate
from tests._pg import transactional_session

INTERNAL = [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:5432/",
    "http://localhost:8080/admin",
    "http://10.0.0.7/hook",
    "http://100.100.100.200/",
]


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.mark.parametrize("url", INTERNAL)
def test_the_schema_refuses_an_internal_target(url: str) -> None:
    with pytest.raises(ValidationError):
        WebhookTargetCreate(name="t", url=url)
    with pytest.raises(ValidationError):
        WebhookTargetUpdate(url=url)


def test_the_schema_accepts_a_public_target() -> None:
    assert WebhookTargetCreate(name="t", url="https://hooks.example.com/x").url == "https://hooks.example.com/x"


@pytest.mark.asyncio
async def test_the_dispatcher_does_not_post_to_a_stored_internal_target(session: AsyncSession) -> None:
    import app.modules.notifications.dispatcher as disp_mod
    from app.core.events import Event

    # Written straight to the table, the way a target saved before the schema
    # check (or by a direct import) would sit there.
    target = WebhookTarget(name="legacy", url="http://169.254.169.254/latest/meta-data/", event_filter="*", active=True)
    session.add(target)
    await session.commit()

    posted_to: list[str] = []

    class _CM:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *_: object) -> None:
            return None

    class _FakeClient:
        async def post(self, url: str, **_: object) -> object:
            posted_to.append(url)

            class _Resp:
                status_code = 200

            return _Resp()

    with (
        unittest.mock.patch.object(disp_mod, "async_session_factory", return_value=_CM()),
        unittest.mock.patch.object(disp_mod, "_get_http_client", return_value=_FakeClient()),
    ):
        await disp_mod._on_dispatch_webhook(
            Event(
                name="notifications.dispatch.webhook",
                data={"event_type": "boq.position.created", "user_id": str(uuid.uuid4()), "payload": {}},
            )
        )

    assert posted_to == []
    assert (target.failure_count or 0) >= 1
