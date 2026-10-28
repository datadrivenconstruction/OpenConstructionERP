# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A socket that cannot judge your token must not say your token was bad.

Both WebSocket handlers used to answer every authentication problem with a
1008 policy close and the reason "unauthenticated". Measured against the real
handlers, every failure those clauses were written for - a malformed, expired
or wrong-type token, a subject that is not a UUID, a user who does not exist
or is inactive - already arrives as an ``HTTPException`` and is answered on
the narrow path. What was left reaching the broad clauses was never an
authentication failure at all: the database being unreachable, or a settings
object that cannot produce a secret. Those were reported to the client as
rejected credentials, which is the one answer that is certainly false.

Why it is worth a close code rather than a log line. Neither frontend client
reconnects, so in this product a socket that closes stays closed. A momentary
database fault did not degrade presence or notifications, it ended them, and
nothing came back when the database did. The user saw an empty roster and no
notifications, with nothing on screen suggesting anything had gone wrong.

Both directions, and that is not symmetry for its own sake. A test that only
asserts 1011 on an outage passes just as happily against a handler that has
been broken into answering 1011 for a genuinely rejected user, which is the
same defect with the polarity reversed and a worse one to debug: it tells a
person with a stale token that the server is broken.
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture(scope="module")
def ws_client() -> TestClient:
    app = create_app()
    with TestClient(app) as client:
        yield client


def _well_formed_token() -> str:
    """A token that passes every check up to the point of touching the database.

    It has to be genuinely valid, or the request never reaches re-hydration and
    the test would be asserting the outage path while exercising the decode one.
    """
    from jose import jwt

    settings = get_settings()
    return jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "exp": int(time.time()) + 3600},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _socket_path(which: str, token: str) -> str:
    """Both sockets, addressed the way a browser addresses them.

    The presence socket validates its entity arguments before it authenticates,
    so they have to be well formed here even though this file never gets far
    enough to touch a real entity.
    """
    if which == "presence":
        entity_id = uuid.uuid4()
        return f"/api/v1/collaboration_locks/presence/?entity_type=boq_position&entity_id={entity_id}&token={token}"
    return f"/api/v1/notifications/ws/?token={token}"


def _close_code(client: TestClient, path: str) -> int:
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(path):
            pass
    return excinfo.value.code


@pytest.mark.parametrize("which", ["presence", "notifications"])
def test_a_rejected_token_still_closes_with_a_policy_code(ws_client: TestClient, which: str) -> None:
    """A caller who was judged and refused gets 1008, exactly as before."""
    assert _close_code(ws_client, _socket_path(which, "not-a-jwt")) == 1008


@pytest.mark.parametrize("which", ["presence", "notifications"])
def test_an_unavailable_backend_closes_with_an_internal_code(
    ws_client: TestClient,
    which: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller who could not be judged gets 1011, not a slur on their token.

    The outage is simulated at the session factory rather than by stopping the
    cluster, because the cluster is shared with every other test in the run.
    """
    import app.dependencies as deps

    class _Unavailable:
        def __call__(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("simulated database outage")

    monkeypatch.setattr(deps, "async_session_factory", _Unavailable())

    assert _close_code(ws_client, _socket_path(which, _well_formed_token())) == 1011
