# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The version floor, on the path an operator takes without booting the app.

``alembic upgrade head`` reaches a database on its own, and on a blank server
``alembic/env.py`` does not walk the revision chain at all - it builds the whole
current schema with ``Base.metadata.create_all`` and stamps head. So the one
command an operator is most likely to run against a freshly provisioned cluster
is also the one that creates every table on it. If it does not ask the server
what it is first, an unsupported or unidentifiable server gets a schema built on
it and the first symptom arrives much later as a broken query somewhere
unrelated, which is the exact failure ``app.core.postgres_version`` exists to
prevent on the application's own path.

What these tests drive is the real thing: ``alembic.command.upgrade`` executes
``env.py``, which builds its engine through ``sqlalchemy.create_engine``. That
one call is replaced with an engine that answers the two version statements
however the test wants, so the path is genuinely walked rather than the guard
being called directly. A test that only called the guard would prove it works
and prove nothing about whether migrations reach it, and a guard that is
imported but never executed produces exactly the clean result of one that
passed.

Nothing here asserts an absence. Every test asserts something that only
happened: a refusal, or - for the supported server - that ``env.py`` got past
the guard and opened a third connection to start schema work.

Before the fix these fail because ``env.py`` never consulted the version at all,
so the first connection it opens is the schema probe and the run dies in
``sa.inspect`` on a connection that is not a real one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy
from alembic import command
from alembic.config import Config

from app.core.postgres_version import MIN_REQUIRED_PG_VERSION, PostgreSQLVersionError

ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"

_PG16_BANNER = "PostgreSQL 16.2 on x86_64-pc-linux-gnu, compiled by gcc (GCC) 9.3.0, 64-bit"
_PG14_BANNER = "PostgreSQL 14.11 on x86_64-pc-linux-gnu, compiled by gcc, 64-bit"

# What a pooler or wire-protocol proxy in front of the database does: answers
# the statement, with something that is not the integer a server computes.
_POOLER_ANSWERS_WITH_PROSE = "sixteen"

_NUM_QUERY_FAILS = RuntimeError("ERROR:  unrecognized configuration parameter")


class _SchemaWorkStarted(RuntimeError):
    """Raised by the fake once ``env.py`` moves on from the version probes.

    Both version statements have been attempted by then, so the next connection
    ``env.py`` opens is the one it inspects the schema with. Catching it is how
    a test says "the guard ran and let this server through", positively, rather
    than by asserting that no error appeared.
    """


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value


class _FakeSyncConnection:
    def __init__(self, engine: _FakeSyncEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeSyncConnection:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, statement: object) -> _FakeResult:
        sql = str(statement)
        self._engine.executed.append(sql)
        answer = self._engine.version_num if "server_version_num" in sql else self._engine.banner
        if isinstance(answer, BaseException):
            raise answer
        return _FakeResult(answer)


class _FakeDialect:
    """Only the dialect name is read, and only to skip non-PostgreSQL URLs."""

    name = "postgresql"


class _FakeSyncEngine:
    """A sync engine whose two version probes are set independently.

    Stands in for what ``create_engine`` returns inside ``env.py``. The two
    probes take either the value the server answers with or an exception the
    statement raises, so a test can say "the number is unavailable but the
    banner is fine" - the only case in which the banner is allowed to decide.
    """

    dialect = _FakeDialect()

    def __init__(self, *, version_num: object = None, banner: object = None) -> None:
        self.version_num = version_num
        self.banner = banner
        self.executed: list[str] = []

    def _version_probes_done(self) -> bool:
        attempted_number = any("server_version_num" in sql for sql in self.executed)
        attempted_banner = any("version()" in sql for sql in self.executed)
        return attempted_number and attempted_banner

    def connect(self) -> _FakeSyncConnection:
        if self._version_probes_done():
            raise _SchemaWorkStarted("env.py opened a connection to inspect or build the schema")
        return _FakeSyncConnection(self)


def _alembic_config() -> Config:
    """A config with no ini file behind it.

    ``Config(alembic.ini)`` would make ``env.py`` run ``fileConfig``, which
    disables every existing logger for the rest of the pytest session and takes
    ``caplog`` with it. Nothing in the ini is read by ``env.py`` anyway - it
    takes its URL from the settings object - so the script location on its own
    is the whole configuration.
    """
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return cfg


def _upgrade_head_against(monkeypatch: pytest.MonkeyPatch, engine: _FakeSyncEngine) -> None:
    """Run ``alembic upgrade head``, with ``env.py`` handed ``engine``."""
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *_args, **_kwargs: engine)
    command.upgrade(_alembic_config(), "head")


def test_a_server_below_the_floor_stops_the_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    """PostgreSQL 14, reported as the server's own number. Nothing gets built."""
    engine = _FakeSyncEngine(version_num="140011", banner=_PG14_BANNER)

    with pytest.raises(PostgreSQLVersionError) as excinfo:
        _upgrade_head_against(monkeypatch, engine)

    assert "14" in str(excinfo.value)
    assert str(MIN_REQUIRED_PG_VERSION) in str(excinfo.value)
    # The refusal came before any schema work, and from the authoritative
    # source: the first thing this run asked the server was its version number.
    assert "server_version_num" in engine.executed[0]


def test_a_reassuring_banner_does_not_rescue_an_old_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """The number decides on this path too, not the string a vendor writes."""
    engine = _FakeSyncEngine(version_num="140011", banner=_PG16_BANNER)

    with pytest.raises(PostgreSQLVersionError, match="14"):
        _upgrade_head_against(monkeypatch, engine)


def test_a_server_that_will_not_answer_with_a_number_stops_the_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unidentifiable server, which is the pooler in front of a database.

    The banner it also serves is a perfectly parseable, perfectly supported
    PostgreSQL 16. It is not consulted: the GUC query answered with something we
    do not understand, so the server was never identified, and guessing from
    prose is what reading the number replaced.
    """
    engine = _FakeSyncEngine(version_num=_POOLER_ANSWERS_WITH_PROSE, banner=_PG16_BANNER)

    with pytest.raises(PostgreSQLVersionError, match="server_version_num"):
        _upgrade_head_against(monkeypatch, engine)


@pytest.mark.parametrize("version_num", ["", "   ", None, "0"])
def test_an_empty_or_impossible_number_stops_the_migration(
    monkeypatch: pytest.MonkeyPatch, version_num: object
) -> None:
    """Every shape of "the server did not identify itself" refuses here too."""
    engine = _FakeSyncEngine(version_num=version_num, banner=_PG16_BANNER)

    with pytest.raises(PostgreSQLVersionError, match="server_version_num"):
        _upgrade_head_against(monkeypatch, engine)


def test_an_unavailable_number_falls_back_and_still_refuses_an_old_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented fallback reaches this path with the floor intact.

    A server that cannot execute the GUC query at all is the one case where the
    banner decides. It widens where the version comes from, never what is
    accepted, and a 14 banner is refused here exactly as a 14 number is.
    """
    engine = _FakeSyncEngine(version_num=_NUM_QUERY_FAILS, banner=_PG14_BANNER)

    with pytest.raises(PostgreSQLVersionError, match="14"):
        _upgrade_head_against(monkeypatch, engine)


def test_a_supported_server_is_let_through_to_the_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard discriminates; it does not refuse everything it is shown.

    A blanket refusal would pass every test above and break every install. This
    one shows the supported server getting past: both probes ran, and ``env.py``
    then opened the connection it inspects the schema with.
    """
    engine = _FakeSyncEngine(version_num=f"{MIN_REQUIRED_PG_VERSION * 10000 + 2}", banner=_PG16_BANNER)

    with pytest.raises(_SchemaWorkStarted):
        _upgrade_head_against(monkeypatch, engine)

    assert "server_version_num" in engine.executed[0]
    assert any("version()" in sql for sql in engine.executed)
