# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A request a proxy forwarded is not a request from this machine.

The desktop bootstrap logs the caller in as the workspace owner without a
password, and it trusted any request whose peer address was loopback. A
reverse proxy on the same host connects from loopback too, so on a fresh
install put behind one, every remote visitor became the owner. The local
check now refuses a request that carries a forwarding header, or that arrived
on a socket not bound to loopback, and such a caller gets the normal login.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.loopback import is_loopback_request
from tests._pg import transactional_session


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """A peer address, headers and the address the server socket is bound to."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        headers: dict[str, str] | None = None,
        server: tuple[str, int] | None = ("127.0.0.1", 8080),
    ) -> None:
        self.client = _FakeClient(host)
        self.headers = headers or {}
        self.scope = {"server": server}


@pytest.mark.parametrize(
    "header",
    [
        {"x-forwarded-for": "198.51.100.23"},
        {"x-real-ip": "198.51.100.23"},
        {"forwarded": "for=198.51.100.23;proto=https"},
    ],
)
def test_a_forwarded_request_is_not_local(header: dict[str, str]) -> None:
    assert is_loopback_request(_FakeRequest(headers=header)) is False


def test_a_socket_bound_outside_loopback_is_not_local() -> None:
    assert is_loopback_request(_FakeRequest(server=("192.168.1.20", 8080))) is False


def test_a_direct_loopback_request_is_still_local() -> None:
    assert is_loopback_request(_FakeRequest()) is True
    assert is_loopback_request(_FakeRequest(host="::1", server=("::1", 8080))) is True


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated PostgreSQL session, empty at t=0: a fresh install."""
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_a_fresh_install_behind_a_proxy_does_not_hand_out_the_owner(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings
    from app.modules.users import router as users_router
    from app.modules.users.service import UserService

    monkeypatch.setenv("OE_DESKTOP", "1")
    service = UserService(session, get_settings())
    assert (await service.first_run_status(is_desktop=True)).fresh_install

    with pytest.raises(HTTPException) as exc:
        await users_router.desktop_bootstrap(
            request=_FakeRequest(headers={"x-forwarded-for": "198.51.100.23"}),
            service=service,
        )
    assert exc.value.status_code == 403
    assert "local machine" in str(exc.value.detail).lower()
