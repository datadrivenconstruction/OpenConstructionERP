# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a property document is emailed only to the sender.

``POST /property-dev/documents/email`` renders a receipt, contract or
certificate and mails it to whatever address the body names. On an academy
install that is an open relay for any learner with editor rights: the
platform's own mail server sends a message with an attachment and a free-text
note to any inbox. In academy mode a learner may send it only to their own
address (422 ``academy_email_not_own`` otherwise); an admin is not limited.
Nothing changes with the flag off.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.core.academy_isolation import EMAIL_NOT_OWN
from app.core.email import MemoryEmailBackend, get_email_service
from app.modules.property_dev import router as propdev_router
from app.modules.property_dev.service import PropertyDevService
from tests.pg.academy_isolation.rows import make_user, payload_of

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


@pytest.fixture
def mailbox(monkeypatch) -> MemoryEmailBackend:
    """Capture the mail and skip the document lookup, which is not under test."""
    backend = MemoryEmailBackend()
    monkeypatch.setattr(propdev_router, "get_email_service", lambda: get_email_service(backend=backend))

    async def _owner_ok(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _pdf(*_args: Any, **_kwargs: Any) -> bytes:
        return b"%PDF-1.4 test"

    monkeypatch.setattr(propdev_router, "_enforce_propdev_doc_owner", _owner_ok)
    monkeypatch.setattr(PropertyDevService, "generate_document", _pdf)
    return backend


async def _send(session, user, recipient: str) -> dict[str, Any]:
    return await propdev_router.email_propdev_document(
        body={"doc_type": "sales_contract", "recipient_email": recipient, "note": "Please sign"},
        payload=payload_of(user),
        service=PropertyDevService(session),
        _perm=None,
    )


async def test_academy_on_a_learner_cannot_mail_someone_else(pg_session, academy, mailbox) -> None:
    academy(True)
    alice = await make_user(pg_session)
    bob = await make_user(pg_session)

    for recipient in (bob.email, "anyone@elsewhere.example"):
        with pytest.raises(HTTPException) as caught:
            await _send(pg_session, alice, recipient)
        assert caught.value.status_code == 422
        assert caught.value.detail["error"] == EMAIL_NOT_OWN
    assert mailbox.sent == []


async def test_academy_on_a_learner_mails_themselves(pg_session, academy, mailbox) -> None:
    academy(True)
    alice = await make_user(pg_session)

    result = await _send(pg_session, alice, f"  {alice.email.upper()} ")

    assert result["ok"] is True
    assert [m.to for m in mailbox.sent] == [alice.email.upper()]


async def test_academy_on_an_admin_is_not_limited(pg_session, academy, mailbox) -> None:
    academy(True)
    admin = await make_user(pg_session, role="admin")

    await _send(pg_session, admin, "buyer@elsewhere.example")

    assert [m.to for m in mailbox.sent] == ["buyer@elsewhere.example"]


async def test_academy_off_unchanged(pg_session, academy, mailbox) -> None:
    academy(False)
    alice = await make_user(pg_session)

    await _send(pg_session, alice, "buyer@elsewhere.example")

    assert [m.to for m in mailbox.sent] == ["buyer@elsewhere.example"]
