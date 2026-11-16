"""Sign-up in ``email-verify`` mode ends in a working account, mail or no mail.

The mode created a dormant account and sent nothing, so a self-registered
user waited for a message that never came and had no way in. Registration
now mails a confirmation link; following it activates the account once. When
the mail does not arrive, an administrator copies the same link for the
pending user and passes it on by any other channel.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.email import MemoryEmailBackend, get_email_service
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> MemoryEmailBackend:
    backend = MemoryEmailBackend()
    monkeypatch.setattr("app.modules.users.service.get_email_service", lambda: get_email_service(backend=backend))
    monkeypatch.setattr("app.config.effective_registration_mode", lambda _s: "email-verify")
    return backend


def _service(session):
    from app.config import get_settings
    from app.modules.users.service import UserService

    return UserService(session, get_settings())


async def _pending_user(session):
    from app.modules.users.schemas import UserCreate

    svc = _service(session)
    # The first registrant bootstraps the admin; the second one is the pending user.
    await svc.register(
        UserCreate(email=f"admin-{uuid.uuid4().hex[:6]}@verify.io", password="VerifyAdm99!", full_name="Admin")
    )
    user = await svc.register(
        UserCreate(email=f"site-{uuid.uuid4().hex[:6]}@verify.io", password="VerifySite99!", full_name="Site Lead")
    )
    await session.flush()
    return svc, user


def _token(url: str) -> str:
    return url.split("token=", 1)[1]


@pytest.mark.asyncio
async def test_registration_mails_a_link_that_activates_the_account(session, outbox):
    svc, user = await _pending_user(session)
    assert user.is_active is False
    (mail,) = [m for m in outbox.sent if m.to == user.email]
    assert "verify_email" in mail.tags
    url = mail.html_body.split('href="', 1)[1].split('"', 1)[0].replace("&amp;", "&")
    assert "/auth/verify-email?token=" in url

    await svc.verify_email(_token(url))
    assert (await svc.get_user(user.id)).is_active is True
    # Following the link a second time is harmless.
    await svc.verify_email(_token(url))


@pytest.mark.asyncio
async def test_an_admin_can_copy_the_link_for_a_pending_user(session, outbox):
    svc, user = await _pending_user(session)
    outbox.clear()
    link = await svc.verification_link(user.id)
    assert link["url"].startswith(svc.settings.resolved_frontend_url)
    assert outbox.sent == []
    await svc.verify_email(_token(link["url"]))
    assert (await svc.get_user(user.id)).is_active is True
    with pytest.raises(HTTPException) as exc:
        await svc.verification_link(user.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_link_does_not_reactivate_an_account_an_admin_switched_off(session, outbox):
    from datetime import UTC, datetime

    svc, user = await _pending_user(session)
    token = _token((await svc.verification_link(user.id))["url"])
    user.last_login_at = datetime.now(UTC)
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await svc.verify_email(token)
    assert exc.value.status_code == 400
    assert (await svc.get_user(user.id)).is_active is False


@pytest.mark.asyncio
async def test_a_reset_token_is_not_a_verification_link(session, outbox):
    from app.modules.users.service import create_reset_token

    svc, user = await _pending_user(session)
    with pytest.raises(HTTPException):
        await svc.verify_email(create_reset_token(user, svc.settings))
    assert (await svc.get_user(user.id)).is_active is False
