"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Run the shipped container entrypoint and check the DATABASE_URL guard.

`test_config_db_url_from_parts.py` says in a docstring that "the container
entrypoint refuses to start on this and names the reason". Nothing executed
that claim, and the guard it describes was wrong for four months: it truncated
the authority at the first "/" before counting "@", so a password holding both
characters slipped past the very check that exists to catch it.

The entrypoint is a shell script whose last act is `exec python -m uvicorn`,
so putting a stub `python` on PATH is enough to run the real file, guard and
all, without Docker and without a database. That is the point of this module:
the guard now has a reader that fails when it regresses.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[2] / "deploy" / "docker" / "entrypoint.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("sh") is None,
    reason="POSIX sh is needed to run the container entrypoint",
)


@pytest.fixture
def run_entrypoint(tmp_path: Path):
    """Return a callable that runs the entrypoint with a harmless `python`."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "python"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)

    def run(**env_overrides: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        # Nothing inherited may decide the outcome: the cases below set what
        # they mean to set and clear the rest.
        for key in ("DATABASE_URL", "DATABASE_SYNC_URL", "OE_DB_PASSWORD", "OE_DB_HOST"):
            env.pop(key, None)
        env.update(env_overrides)
        env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
        return subprocess.run(
            ["sh", str(ENTRYPOINT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )

    return run


def test_a_missing_url_is_refused_by_name(run_entrypoint) -> None:
    result = run_entrypoint()
    assert result.returncode == 1
    assert "DATABASE_URL is not set" in result.stderr


def test_a_literal_at_sign_in_the_password_is_refused(run_entrypoint) -> None:
    url = "postgresql+asyncpg://oe:pa@ss@postgres:5432/openestimate"
    result = run_entrypoint(DATABASE_URL=url)
    assert result.returncode == 1
    assert "contains an '@'" in result.stderr


def test_a_slash_before_the_at_sign_does_not_hide_it(run_entrypoint) -> None:
    """The regression this guard was blind to.

    SQLAlchemy reads this URL with host "ss@postgres", so it is exactly the
    damage the guard describes. While the count stopped at the first "/" the
    truncated text was "oe:pa", the count was zero, and the URL was waved
    through to fail later as a DNS error for a host nobody typed.
    """
    url = "postgresql+asyncpg://oe:pa/b@ss@postgres:5432/openestimate"
    result = run_entrypoint(DATABASE_URL=url)
    assert result.returncode == 1
    assert "contains an '@'" in result.stderr


def test_a_question_mark_before_the_at_sign_does_not_hide_it_either(run_entrypoint) -> None:
    """The same hole one character over.

    A guard that isolates the host by cutting the URL at some character is
    blind to a password containing that character, whichever character is
    chosen. Asking for the host the way the parser downstream asks for it is
    what closes the whole class, so this URL is caught for the same reason the
    one above is: make_url reads both with host "ss@postgres".
    """
    url = "postgresql+asyncpg://oe:pa?b@ss@postgres:5432/openestimate"
    result = run_entrypoint(DATABASE_URL=url)
    assert result.returncode == 1
    assert "contains an '@'" in result.stderr


@pytest.mark.parametrize(
    "url",
    [
        # Past the host, so neither is the damage. make_url reads both of these
        # with host "postgres", and a guard that counted "@" over the whole URL
        # would have refused to start on either.
        "postgresql+asyncpg://oe:pw@postgres:5432/db?options=-c%20x@y",
        "postgresql+asyncpg://oe:pw@postgres:5432/db@name",
    ],
)
def test_an_at_sign_past_the_host_is_not_the_damage(run_entrypoint, url: str) -> None:
    result = run_entrypoint(DATABASE_URL=url)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "password",
    [
        "ordinary",
        # What `openssl rand -base64 24` emits about four times in ten. The
        # base64 alphabet cannot produce "@", so a slash here is harmless and
        # must not be mistaken for the damage above.
        "ab/cd+ef==",
        "pa%40ss",
    ],
)
def test_a_password_without_a_literal_at_sign_starts(run_entrypoint, password: str) -> None:
    url = f"postgresql+asyncpg://oe:{password}@postgres:5432/openestimate"
    result = run_entrypoint(DATABASE_URL=url)
    assert result.returncode == 0, result.stderr
    assert "more than one '@'" not in result.stderr


def test_a_mangled_url_is_survivable_when_the_parts_are_there(run_entrypoint) -> None:
    """Compose passes both so one file works with an image older than itself."""
    url = "postgresql+asyncpg://oe:pa@ss@postgres:5432/openestimate"
    result = run_entrypoint(DATABASE_URL=url, OE_DB_PASSWORD="pa@ss", OE_DB_HOST="postgres")
    assert result.returncode == 0, result.stderr
    assert "NOTE:" in result.stderr
    assert "Using OE_DB_HOST" in result.stderr


def test_a_non_postgres_url_is_refused_without_echoing_it(run_entrypoint) -> None:
    result = run_entrypoint(DATABASE_URL="mysql://oe:secretpassword@db:3306/openestimate")
    assert result.returncode == 1
    assert "must be a PostgreSQL URL" in result.stderr
    assert "secretpassword" not in result.stderr
