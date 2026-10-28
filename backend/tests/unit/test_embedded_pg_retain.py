"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A retained cluster survives an application shutdown.

The application stops the embedded cluster from its own shutdown handler. That
is right when the application booted it and wrong when something longer-lived
did. The test session boots one cluster for the whole run, so without the pin
the first test that exercises the app lifespan stopped the postmaster and every
test after it errored on connect with ConnectionRefusedError.

These tests drive the ownership rule directly with a stand-in server, so they
need no database and cannot themselves disturb the session's cluster.
"""

from __future__ import annotations

import pytest

from app.core import embedded_pg


class _FakeServer:
    """Stands in for the pgserver handle; records whether it was stopped."""

    def __init__(self) -> None:
        self.cleanup_calls = 0

    def cleanup(self) -> None:
        self.cleanup_calls += 1


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch) -> _FakeServer:
    """Install a stand-in server and restore the real module state afterwards.

    ``monkeypatch`` restores both globals, so a failure here cannot leave the
    session's own cluster pinned or detached for the tests that follow.
    """
    server = _FakeServer()
    monkeypatch.setattr(embedded_pg, "_server", server)
    monkeypatch.setattr(embedded_pg, "_retained", False)
    return server


def test_an_unretained_cluster_stops_normally(fake_server: _FakeServer) -> None:
    embedded_pg.shutdown()

    assert fake_server.cleanup_calls == 1
    assert embedded_pg._server is None


def test_a_retained_cluster_survives_an_application_shutdown(fake_server: _FakeServer) -> None:
    """The regression. This is the exact call app.main makes on lifespan exit."""
    embedded_pg.retain()

    embedded_pg.shutdown()

    assert fake_server.cleanup_calls == 0, "the app's shutdown handler stopped a cluster it does not own"
    assert embedded_pg.is_running(), "the cluster was detached, so later connections would be refused"


def test_a_retained_cluster_survives_repeated_application_shutdowns(fake_server: _FakeServer) -> None:
    """Many tests exercise the lifespan, not one, so the pin has to hold every time."""
    embedded_pg.retain()

    for _ in range(5):
        embedded_pg.shutdown()

    assert fake_server.cleanup_calls == 0
    assert embedded_pg.is_running()


def test_the_owner_can_still_stop_a_retained_cluster(fake_server: _FakeServer) -> None:
    """What the session's atexit hook does at the end of the run."""
    embedded_pg.retain()

    embedded_pg.shutdown(force=True)

    assert fake_server.cleanup_calls == 1
    assert embedded_pg._server is None


def test_stopping_a_retained_cluster_clears_the_pin(fake_server: _FakeServer) -> None:
    """Otherwise a later boot in the same process would come back pre-pinned."""
    embedded_pg.retain()
    embedded_pg.shutdown(force=True)

    assert embedded_pg._retained is False


def test_shutdown_is_safe_when_no_cluster_was_booted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedded_pg, "_server", None)
    monkeypatch.setattr(embedded_pg, "_retained", True)

    embedded_pg.shutdown()
    embedded_pg.shutdown(force=True)
