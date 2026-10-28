# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The health report says when nothing in the process can talk to the server.

A running vector database and a client library for it are two separate things,
and the shipped containers and the desktop build have neither. Both install the
base dependency set, so ``qdrant_client`` was never present, and every match
came back with no candidates because the adapter raised on the import long
before a URL was dialled.

The old report had no field for this, so the one case where it mattered most,
server up and no client, was reported as healthy: a green card above a matcher
that could not return anything. Worse, when the server was also down the card
offered to download it, and a user who took that offer got a running server and
the same empty results, because the missing piece was never the server.

These tests pin the field on all four report paths and pin that the offer to
download is withheld when it would not help.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from app.modules.match_elements import qdrant_supervisor as supervisor


@pytest.fixture(autouse=True)
def _forget_client_answer() -> None:
    """The import answer is cached for the process; tests must not inherit it."""
    supervisor._client_installed = None
    yield
    supervisor._client_installed = None


def _no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "qdrant_client" or name.startswith("qdrant_client."):
            raise ImportError("No module named 'qdrant_client'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    supervisor._client_installed = None


def test_reports_the_client_when_it_can_be_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "find_qdrant_binary", lambda: None)
    monkeypatch.setattr(supervisor, "probe_qdrant", lambda *_a, **_k: True)
    monkeypatch.setattr(supervisor, "qdrant_client_available", lambda: True)

    health = supervisor.ensure_qdrant_running("http://localhost:6333")

    assert health.reachable is True
    assert health.client_installed is True
    assert health.install_hint == ""


def test_a_reachable_server_is_not_healthy_without_a_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The state the old report called healthy, and the one #391 describes."""
    monkeypatch.setattr(supervisor, "find_qdrant_binary", lambda: None)
    monkeypatch.setattr(supervisor, "probe_qdrant", lambda *_a, **_k: True)
    monkeypatch.setattr(supervisor, "qdrant_client_available", lambda: False)

    health = supervisor.ensure_qdrant_running("http://localhost:6333")

    assert health.reachable is True
    assert health.client_installed is False
    assert "semantic" in health.install_hint
    # The card branches on client_installed before reachability, so the message
    # has to carry the reason rather than claim everything is answering.
    assert "no client library" in health.message


def test_a_missing_client_is_not_offered_a_server_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downloading the server changes nothing when nothing can speak to it."""
    monkeypatch.setattr(supervisor, "find_qdrant_binary", lambda: None)
    monkeypatch.setattr(supervisor, "probe_qdrant", lambda *_a, **_k: False)
    monkeypatch.setattr(supervisor, "qdrant_client_available", lambda: False)
    monkeypatch.setattr(
        supervisor,
        "_resolve_release_asset",
        lambda: (_ for _ in ()).throw(AssertionError("release asset must not be resolved")),
    )

    health = supervisor.ensure_qdrant_running("http://localhost:6333")

    assert health.reachable is False
    assert health.client_installed is False
    assert health.download_url is None
    assert "not available in this installation" in health.message


def test_a_missing_server_still_offers_the_download_when_a_client_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervisor, "find_qdrant_binary", lambda: None)
    monkeypatch.setattr(supervisor, "probe_qdrant", lambda *_a, **_k: False)
    monkeypatch.setattr(supervisor, "qdrant_client_available", lambda: True)
    monkeypatch.setattr(supervisor, "_resolve_release_asset", lambda: ("qdrant-x86_64.tar.gz", "https://example/x"))

    health = supervisor.ensure_qdrant_running("http://localhost:6333")

    assert health.reachable is False
    assert health.client_installed is True
    assert health.download_url == "https://example/x"


def test_a_binary_that_did_not_come_up_still_reports_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervisor, "find_qdrant_binary", lambda: Path("/tmp/qdrant"))
    monkeypatch.setattr(supervisor, "probe_qdrant", lambda *_a, **_k: False)
    monkeypatch.setattr(supervisor, "spawn_qdrant", lambda _b: None)
    monkeypatch.setattr(supervisor, "qdrant_client_available", lambda: True)

    health = supervisor.ensure_qdrant_running("http://localhost:6333", spawn_if_installed=False)

    assert health.reachable is False
    assert health.installed is True
    assert health.client_installed is True


def test_the_answer_is_an_import_not_a_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A package that resolves but raises on import is not a usable client.

    ``importlib.util.find_spec`` answers the first question and not the second,
    and the two differ exactly on a partial install or a missing native wheel,
    which is when this matters. So the check imports.
    """
    _no_client(monkeypatch)

    assert supervisor.qdrant_client_available() is False


def test_the_import_answer_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card polls; the answer cannot change without a restart."""
    calls: list[str] = []
    real_import = builtins.__import__

    def counting_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "qdrant_client":
            calls.append(name)
            raise ImportError("No module named 'qdrant_client'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", counting_import)
    supervisor._client_installed = None

    assert supervisor.qdrant_client_available() is False
    assert supervisor.qdrant_client_available() is False
    assert len(calls) == 1
