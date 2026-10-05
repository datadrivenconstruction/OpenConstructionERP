"""The password-reset email links to the page that can use it.

The email has always pointed at ``{frontend_url}/auth/reset?token=...``, and
for as long as that was true the web app had no such page: the catch-all
route sent a signed-out visitor to a sign-in form, with the token parked in
``next=`` and no page anywhere that could spend it. The
email tests passed throughout, because they handed the template a URL of
their own and asserted it came back out. None of them asked which URL the
service builds.

This file asks. It runs ``UserService.forgot_password`` with small fakes,
captures the URL handed to the mailer, and pins its path to ``/auth/reset``,
the route ``frontend/src/app/App.tsx`` declares for ``ResetPasswordPage``.
The frontend half of the pin is
``frontend/src/app/__tests__/resetLinkLandsOnItsPage.test.ts``, which reads
this same f-string and fails if App.tsx stops routing it. It also checks the
token in the link is one ``reset_password`` will accept.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from jose import jwt

# The route App.tsx mounts ResetPasswordPage on.
FRONTEND_RESET_ROUTE = "/auth/reset"
SECRET = "s" * 40


def _service(monkeypatch: pytest.MonkeyPatch, frontend_url: str) -> tuple[Any, list[dict[str, Any]], Any]:
    from app.modules.users import service as users_service

    sent: list[dict[str, Any]] = []

    class _Email:
        async def send_password_reset(self, **kwargs: Any) -> SimpleNamespace:
            sent.append(kwargs)
            return SimpleNamespace(ok=True)

    monkeypatch.setattr(users_service, "get_email_service", lambda: _Email())

    user = SimpleNamespace(id=uuid.uuid4(), email="known@example.com", full_name="Known", is_active=True)

    class _Repo:
        async def get_by_email(self, email: str) -> SimpleNamespace | None:
            return user if email == user.email else None

    svc = users_service.UserService.__new__(users_service.UserService)
    svc.settings = SimpleNamespace(
        jwt_secret=SECRET,
        jwt_algorithm="HS256",
        resolved_frontend_url=frontend_url,
        app_debug=False,
    )
    svc.user_repo = _Repo()
    return svc, sent, user


@pytest.mark.asyncio
async def test_the_reset_email_links_to_the_frontend_reset_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.users.schemas import ForgotPasswordRequest

    svc, sent, user = _service(monkeypatch, "https://erp.example.com")
    await svc.forgot_password(ForgotPasswordRequest(email=user.email))

    assert len(sent) == 1
    link = urlsplit(sent[0]["reset_url"])
    assert (link.scheme, link.netloc) == ("https", "erp.example.com")
    assert link.path == FRONTEND_RESET_ROUTE
    assert link.fragment == ""

    tokens = parse_qs(link.query)["token"]
    assert len(tokens) == 1
    claims = jwt.decode(tokens[0], SECRET, algorithms=["HS256"])
    assert claims["type"] == "reset"
    assert claims["sub"] == str(user.id)


@pytest.mark.asyncio
async def test_the_reset_link_keeps_a_sub_path_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """An install served under a prefix gets the route under that prefix, not at the host root."""
    from app.modules.users.schemas import ForgotPasswordRequest

    svc, sent, user = _service(monkeypatch, "https://example.com/erp")
    await svc.forgot_password(ForgotPasswordRequest(email=user.email))

    assert urlsplit(sent[0]["reset_url"]).path == "/erp" + FRONTEND_RESET_ROUTE
