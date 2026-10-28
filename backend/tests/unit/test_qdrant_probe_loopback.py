# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The Qdrant health probe does not send a loopback request to a proxy.

``urllib.request.urlopen`` uses the default opener, whose ``ProxyHandler`` is
seeded from the environment. Its bypass check is ``no_proxy`` alone on POSIX,
so loopback is not exempt unless the operator listed it. A machine with
``http_proxy`` set therefore had its probe of a Qdrant running on the same host
answered by the proxy, and the vector-database card told the user Qdrant was
not installed and offered to download it.

The visible cost of getting this wrong is not a slow page: it is a card that
states the opposite of the truth and sends the user to install software they
already have. These tests pin which opener each kind of URL gets, and that the
loopback one really carries no proxies, because an opener built with the
default handler set would pass the first check and fail the user.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

import pytest

from app.modules.match_elements import qdrant_supervisor as supervisor


class _Resp:
    """Minimal stand-in for the object ``urlopen`` yields."""

    status = 200

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


@pytest.fixture
def _record_opener(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record which opener each probe used, without touching the network."""
    used: list[str] = []

    def _direct(_req: Any, **_kw: Any) -> _Resp:
        used.append("direct")
        return _Resp()

    def _default(_req: Any, **_kw: Any) -> _Resp:
        used.append("default")
        return _Resp()

    monkeypatch.setattr(supervisor._DIRECT_OPENER, "open", _direct)
    monkeypatch.setattr(urllib.request, "urlopen", _default)
    return used


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:6333",
        "http://127.0.0.1:6333",
        # Anything in 127.0.0.0/8 is this machine, not just .0.1.
        "http://127.0.0.53:6333",
        "http://[::1]:6333",
        # The scheme's default port and a trailing slash must not change it.
        "http://localhost/",
    ],
)
def test_a_local_qdrant_is_probed_directly(url: str, _record_opener: list[str]) -> None:
    assert supervisor.probe_qdrant(url) is True
    assert _record_opener == ["direct"]


@pytest.mark.parametrize(
    "url",
    [
        "http://qdrant.internal:6333",
        "https://vector.example.com",
        "http://10.0.0.7:6333",
    ],
)
def test_a_remote_qdrant_still_honours_the_proxy(url: str, _record_opener: list[str]) -> None:
    """A deployment pointing at a Qdrant elsewhere may well need the proxy.

    Skipping it there would be the same defect in the other direction, so the
    exemption is scoped to addresses that name this machine.
    """
    assert supervisor.probe_qdrant(url) is True
    assert _record_opener == ["default"]


def test_the_fallback_probe_keeps_the_same_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/readyz`` failing must not quietly send the retry through the proxy.

    Older builds answer 4xx on ``/readyz`` until collections mount, which is
    exactly when the second request goes out - the common path on a cold
    start, not an edge case.
    """
    used: list[str] = []

    def _direct(req: Any, **_kw: Any) -> _Resp:
        used.append(req.full_url)
        if req.full_url.endswith("/readyz"):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return _Resp()

    def _default(*_a: Any, **_kw: Any) -> _Resp:
        pytest.fail("the retry must not fall back to the proxied opener")

    monkeypatch.setattr(supervisor._DIRECT_OPENER, "open", _direct)
    monkeypatch.setattr(urllib.request, "urlopen", _default)

    assert supervisor.probe_qdrant("http://localhost:6333") is True
    assert used == ["http://localhost:6333/readyz", "http://localhost:6333/"]


def test_the_direct_opener_carries_no_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exemption is only real if no handler on the opener holds a proxy.

    Passing an empty ``ProxyHandler`` to ``build_opener`` displaces the
    environment-seeded default, and the empty one is then dropped as well: it
    defines no ``<scheme>_open`` method, so ``add_handler`` never files it.
    The result is an opener with no proxy handling at all, which is the point,
    but it means "a ProxyHandler is present" is the wrong thing to assert.
    """
    proxied = [
        h for h in supervisor._DIRECT_OPENER.handlers if isinstance(h, urllib.request.ProxyHandler) and h.proxies
    ]
    assert proxied == []

    # The contrast is what makes the line above mean something: the opener
    # behind `urlopen` does read the environment, and that is the behaviour
    # the loopback probe had to be moved off.
    monkeypatch.setenv("http_proxy", "http://proxy.invalid:3128")
    env_seeded = urllib.request.build_opener()
    assert any(isinstance(h, urllib.request.ProxyHandler) and h.proxies for h in env_seeded.handlers), (
        "the default opener is supposed to pick environment proxies up"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:6333", True),
        ("http://LOCALHOST:6333", True),
        ("http://127.0.0.1", True),
        ("http://[::1]", True),
        ("http://qdrant.internal", False),
        ("http://192.168.1.10", False),
        # A host that merely starts with the name is a different machine.
        ("http://localhost.evil.example", False),
        ("", False),
    ],
)
def test_loopback_classification(url: str, expected: bool) -> None:
    assert supervisor._is_loopback(url) is expected


def test_an_empty_url_is_not_probed(_record_opener: list[str]) -> None:
    """No URL configured is not the same as a URL that failed."""
    assert supervisor.probe_qdrant("") is False
    assert _record_opener == []
