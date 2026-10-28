# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A password change must end the session at every door, not just the front one.

``password_changed_at`` is the one session kill switch this product has. A
token whose ``iat`` predates it is refused, so changing a password ends a
stolen session on the next request. That is the whole mechanism, and it used
to be enforced in exactly one of the places a token is accepted.

Two doors let the killed session back in, and this test holds both shut.

The refresh endpoint was the wider one. ``UserService.refresh_tokens`` checked
the signature, the ``type`` claim and ``is_active``, and never looked at
``password_changed_at``. A refresh token minted before the change therefore
still minted a new access token, and that token's ``iat`` is the present
moment, so it sailed through the watermark that was supposed to stop it. The
kill switch was not weakened by this, it was cancelled: refresh tokens live
thirty days against the access token's hour, so whoever holds one keeps the
account for a month after the victim changes their password.

The sockets were the quieter one. Every token entry point that is not
``get_current_user_payload`` authenticates through
``verify_user_exists_and_active``, which loaded the user, checked ``is_active``
and stopped. The watermark went into the inline copy of that check inside
``get_current_user_payload`` and not into the shared helper, so a live socket
survived the password change that closed every HTTP call beside it. Passing
``issued_at`` into that helper is not itself the enforcement, which is the
trap this file exists to keep shut: the argument was accepted as required
before the body ever read it, and every caller looked correct.

Every assertion here is paired with a positive control, because both defects
look exactly like a refusal. A test that only asserts "the refresh 401s" and
"the socket closes" passes against a build where refresh is broken for
everyone and the socket never opens at all - the same green, none of the
meaning. So each door is first shown to be OPEN for the very token that is
about to be refused.

The refresh control deliberately uses a SECOND user rather than a first call
by the same one. A revocable-refresh design rotates the token on use, which
would make the second call fail as replay rather than as watermark - the
right verdict reached by the wrong mechanism, and the assertion message would
quietly become a lie. One user, one refresh, one meaning.
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.main import create_app

PASSWORD = "OriginalPassw0rd!"
NEW_PASSWORD = "RotatedPassw0rd!"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """One app, one lifespan, driven synchronously.

    Module-scoped and sync to match ``test_ws_auth_distinguishes_refusal_from
    _fault.py``: ``TestClient`` runs the app on its own portal thread, so
    building a second app inside an async test would cross event loops and
    re-run module discovery a second time in the same process.
    """
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _register_and_login(client: TestClient) -> dict[str, str]:
    """Register a fresh user and return its token pair.

    ``conftest`` pins ``REGISTRATION_MODE=open``, so the account lands active
    and can log in without an admin promotion.

    The domain is ``example.com`` and not ``.test`` because ``.test`` is a
    reserved TLD that our own email validation refuses: registration answers
    422 and the login below never happens. That failure lands on the positive
    control, so both tests in this file went red without reaching a single
    watermark assertion - red for a reason that has nothing to do with what
    they measure, which is the one way a controlled test can still mislead.
    """
    email = f"revoke-{uuid.uuid4().hex[:8]}@revocation.example.com"
    client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Revocation Tester"},
    )
    resp = client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert resp.status_code == 200, f"login failed for {email}: {resp.text}"
    body = resp.json()
    return {"email": email, "access": body["access_token"], "refresh": body["refresh_token"]}


def _change_password(client: TestClient, access_token: str) -> None:
    """Bump ``password_changed_at`` through the real endpoint.

    The response carries a fresh token pair, which is exactly why it is
    discarded here rather than bound to a name: a later edit that reached for
    it would silently start testing the new session instead of the old one.
    """
    resp = client.post(
        "/api/v1/users/me/change-password/",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200, f"change-password failed: {resp.text}"


def _wait_for_the_next_whole_second() -> None:
    """Put the login and the password change into different wall-clock seconds.

    The watermark compares a token's ``iat`` against ``password_changed_at``
    with both operands truncated to whole seconds, because ``iat`` is seconds
    since the epoch by RFC 7519. A token minted inside the same second as the
    change therefore compares equal to the watermark and survives it. That is
    a real, documented limit of second resolution, not an accident of this
    test - but without this wait the test inherits it as a race. Registering,
    logging in and changing a password take a few hundred milliseconds
    together, so whether the two calls straddle a second boundary is decided
    by when the run happens to start, and the same code goes green or red on
    consecutive runs.

    Sleeping to the next boundary is what makes the assertion mean the thing
    it claims. A green here says the door refuses a credential that is older
    than the change; it deliberately says nothing about a credential minted in
    the very same second, which only per-session revocation can reach.
    """
    now = time.time()
    time.sleep(1.0 - (now % 1.0) + 0.05)


def _open_notifications_socket(client: TestClient, access_token: str) -> str:
    """Open the notifications socket and return its first frame's event name.

    Reading a frame is the point. A handshake that is going to be refused
    still enters the context manager, so ``connect`` returning without raising
    proves nothing; the ``notifications.hello`` frame is only sent after the
    handler has accepted the caller.
    """
    with client.websocket_connect(f"/api/v1/notifications/ws/?token={access_token}") as socket:
        frame = socket.receive_json()
    return str(frame.get("event", ""))


def _socket_close_code(client: TestClient, access_token: str) -> int:
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/api/v1/notifications/ws/?token={access_token}") as socket:
            socket.receive_json()
    return int(excinfo.value.code)


def test_refresh_token_is_dead_after_a_password_change(client: TestClient) -> None:
    """A refresh token older than the password change must not mint anything."""
    # Positive control: a refresh token from an untouched account works. Without
    # it, the 401 below is equally consistent with refresh being broken outright.
    control = _register_and_login(client)
    control_resp = client.post(
        "/api/v1/users/auth/refresh",
        json={"refresh_token": control["refresh"]},
    )
    assert control_resp.status_code == 200, f"refresh must work on an untouched account: {control_resp.text}"
    assert control_resp.json().get("access_token"), "control refresh returned no access token"

    victim = _register_and_login(client)
    _wait_for_the_next_whole_second()
    _change_password(client, victim["access"])

    resp = client.post(
        "/api/v1/users/auth/refresh",
        json={"refresh_token": victim["refresh"]},
    )
    assert resp.status_code == 401, (
        "a refresh token issued before the password change still minted a new "
        f"access token (HTTP {resp.status_code}); the thirty-day refresh token "
        "cancels the one-hour access token's kill switch"
    )


def test_websocket_is_closed_after_a_password_change(client: TestClient) -> None:
    """The notifications socket must refuse a token the HTTP surface refuses."""
    victim = _register_and_login(client)

    # Positive control 1: this exact token opens the socket right now.
    assert _open_notifications_socket(client, victim["access"]) == "notifications.hello", (
        "the socket did not open for a valid token, so the close asserted below would mean nothing"
    )

    _wait_for_the_next_whole_second()
    _change_password(client, victim["access"])

    # Positive control 2: the HTTP surface now refuses that same token, which
    # is what proves the watermark actually landed.
    me_after = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {victim['access']}"})
    assert me_after.status_code == 401, (
        f"watermark did not take effect on the HTTP surface (HTTP {me_after.status_code}); "
        "the socket assertion below would be measuring nothing"
    )

    assert _socket_close_code(client, victim["access"]) == 1008, (
        "the notifications socket accepted an access token that the HTTP surface "
        "rejects: a password change closes every HTTP call and leaves the live socket open"
    )
