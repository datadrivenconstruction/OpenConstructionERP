"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The database URL is assembled from parts without breaking on punctuation.

Issue #404 was an installation that would not come up: the app container exited
on ``socket.gaierror: [Errno -2] Name or service not known`` while PostgreSQL
next to it stayed healthy on the same password. The cause was the URL, not the
network. A compose file interpolates the password straight into

    postgresql+asyncpg://oe:${POSTGRES_PASSWORD}@postgres:5432/openestimate

and a URL splits its user info at the *first* ``@``, so the password ``pa@ss``
makes the host ``ss@postgres``. PostgreSQL never noticed because it receives
the password as a plain environment variable, where ``@`` means nothing.

Compose has no urlencode, so the assembly moved into ``Settings``, which sees
the parts while they are still separate. These tests pin the behaviour that
matters: whatever the password contains, the host stays the host and the
password survives the round trip.
"""

import pytest
from sqlalchemy.engine import make_url

from app.config import Settings

# Passwords that a generator or a human plausibly produces. The first two are
# what the documented `openssl rand -base64 24` emits; the rest are the
# punctuation that a URL, a shell or a compose file each treat as special.
PASSWORDS = [
    pytest.param("s3cretpassword", id="plain"),
    pytest.param("Ab/cdEfGh+ijKlMn=", id="base64-with-slash"),
    pytest.param("pa@ss", id="at-sign-the-reported-break"),
    pytest.param("pa:ss", id="colon"),
    pytest.param("p@ss:w/rd#1", id="every-delimiter-at-once"),
    pytest.param("pa?ss/word", id="query-and-path"),
    pytest.param("па@роль", id="non-ascii-with-at-sign"),
    pytest.param("pa%40ss", id="already-looks-encoded"),
]


@pytest.fixture(autouse=True)
def _clear_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from no URL at all, so the parts are what is under test."""
    for name in ("DATABASE_URL", "DATABASE_SYNC_URL", "OE_DATABASE_URL", "OE_DATABASE_SYNC_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("password", PASSWORDS)
def test_parts_survive_any_password(password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The host is the host and the password round-trips, whatever is in it."""
    monkeypatch.setenv("OE_DB_HOST", "postgres")
    monkeypatch.setenv("OE_DB_PORT", "5432")
    monkeypatch.setenv("OE_DB_USER", "oe")
    monkeypatch.setenv("OE_DB_NAME", "openestimate")
    monkeypatch.setenv("OE_DB_PASSWORD", password)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    for url_text in (settings.database_url, settings.database_sync_url):
        url = make_url(url_text)
        assert url.host == "postgres", f"host mangled by password {password!r}: {url.host!r}"
        assert url.port == 5432
        assert url.database == "openestimate"
        assert url.username == "oe"
        assert url.password == password, f"password did not survive: {url.password!r}"


def test_interpolating_the_password_is_what_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard the guard: show the naive assembly really does mangle the host.

    Without this, every assertion above would pass just as well against a
    version that does nothing, because most passwords are harmless. This pins
    the one input that separates the two.
    """
    naive = make_url("postgresql+asyncpg://oe:pa@ss@postgres:5432/openestimate")
    assert naive.host == "ss@postgres"

    monkeypatch.setenv("OE_DB_PASSWORD", "pa@ss")
    assert make_url(Settings(_env_file=None).database_url).host == "postgres"  # type: ignore[call-arg]


def test_an_explicit_url_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """The parts only fill a blank; an operator's own URL is left alone."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@elsewhere:6543/other")
    monkeypatch.setenv("OE_DB_HOST", "postgres")
    monkeypatch.setenv("OE_DB_PASSWORD", "ignored")

    url = make_url(Settings(_env_file=None).database_url)  # type: ignore[call-arg]
    assert url.host == "elsewhere"
    assert url.port == 6543
    assert url.database == "other"


def test_a_mangled_url_loses_to_the_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A URL whose host swallowed the password is overruled by the parts.

    The quickstart image path has to pass both. The compose file cannot know
    how old the image it is about to run is, and an image published before the
    parts existed sees no ``DATABASE_URL`` and refuses to start. Passing both
    would otherwise undo the fix for anyone taking that route, because a URL
    normally wins. It does not win here: a host containing ``@`` is not a host,
    so the URL is unusable however it was meant.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://oe:pa@ss@postgres:5432/openestimate")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql://oe:pa@ss@postgres:5432/openestimate")
    monkeypatch.setenv("OE_DB_HOST", "postgres")
    monkeypatch.setenv("OE_DB_PORT", "5432")
    monkeypatch.setenv("OE_DB_USER", "oe")
    monkeypatch.setenv("OE_DB_NAME", "openestimate")
    monkeypatch.setenv("OE_DB_PASSWORD", "pa@ss")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    for url_text in (settings.database_url, settings.database_sync_url):
        url = make_url(url_text)
        assert url.host == "postgres", f"the mangled URL was used: host {url.host!r}"
        assert url.password == "pa@ss"


def test_a_mangled_url_alone_is_left_to_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the parts there is nothing to fall back to, so nothing is guessed.

    The container entrypoint refuses to start on this and names the reason.
    Quietly inventing a host here would take that message away and turn a
    diagnosed configuration error back into a resolver failure.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://oe:pa@ss@elsewhere:5432/other")
    for name in ("OE_DB_PASSWORD", "OE_DB_HOST", "OE_DB_PORT", "OE_DB_USER", "OE_DB_NAME"):
        monkeypatch.delenv(name, raising=False)

    assert make_url(Settings(_env_file=None).database_url).host == "ss@elsewhere"  # type: ignore[call-arg]


def test_no_parts_and_no_url_leaves_the_default_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a password there is nothing to assemble, and nothing is invented.

    The embedded-PostgreSQL path depends on this: a blank URL is how the app
    knows to start its own cluster rather than dial out to one.
    """
    for name in ("OE_DB_PASSWORD", "OE_DB_HOST", "OE_DB_PORT", "OE_DB_USER", "OE_DB_NAME"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.database_url == ""
