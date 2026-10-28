# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every branch of the startup version check that must not end in a return.

``validate_postgres_version`` only needs an object that answers two statements,
so a stub engine reaches every rejection, every acceptance and - the part a
real server cannot show - every *disagreement* between the two sources.

That disagreement is the point. The authoritative source is the integer
``server_version_num``; ``SELECT version()`` is prose that vendors write as they
please. The tests below drive the two apart deliberately, so an implementation
that reads the banner instead of the number fails here rather than in
production against an Aurora, EnterpriseDB or ``rc`` build.

The second property under test is that no failure is survivable. A version that
was never identified must stop the process, because the alternative is a server
whose capabilities nobody checked building a schema and taking writes. Every
test in this file therefore asserts a raise, and
``test_no_failing_engine_ever_returns_normally`` asserts it as a sweep, so a
future shortcut that returns a default cannot pass quietly.

The live-cluster half lives in ``test_postgres_version``.
"""

from __future__ import annotations

import logging

import pytest

from app.core.postgres_version import (
    MIN_REQUIRED_PG_VERSION,
    PostgreSQLVersionError,
    validate_postgres_version,
)

_LOGGER_NAME = "app.core.postgres_version"

# A server that answers neither probe with anything usable.
_NUM_QUERY_FAILS = RuntimeError("ERROR:  unrecognized configuration parameter")
_BANNER_QUERY_FAILS = RuntimeError("ERROR:  function version() does not exist")


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value


class _FakeConnection:
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    async def __aenter__(self) -> _FakeConnection:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def execute(self, statement: object) -> _FakeResult:
        sql = str(statement)
        self._engine.executed.append(sql)
        if "server_version_num" in sql:
            answer = self._engine.version_num
        else:
            answer = self._engine.banner
        if isinstance(answer, BaseException):
            raise answer
        return _FakeResult(answer)


class _FakeEngine:
    """An engine whose two probes can be set - or failed - independently.

    ``version_num`` and ``banner`` each take either the value the server
    returns or an exception instance the statement raises with. Keeping them
    separate is what lets a test say "the number is unavailable but the banner
    is fine", which is the only situation in which the string path is allowed
    to decide anything.
    """

    def __init__(self, *, version_num: object = None, banner: object = None) -> None:
        self.version_num = version_num
        self.banner = banner
        self.executed: list[str] = []

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


class _UnreachableEngine:
    def connect(self) -> _FakeConnection:
        raise OSError("connection refused")


_PG16_BANNER = "PostgreSQL 16.2 on x86_64-pc-linux-gnu, compiled by gcc (GCC) 9.3.0, 64-bit"
_PG14_BANNER = "PostgreSQL 14.11 on x86_64-pc-linux-gnu, compiled by gcc, 64-bit"


# ---------------------------------------------------------------------------
# The number is the source of truth
# ---------------------------------------------------------------------------


async def test_the_numeric_guc_is_what_gets_queried() -> None:
    """A stated intention is not an implementation; read what was executed."""
    engine = _FakeEngine(version_num="160002", banner=_PG16_BANNER)

    await validate_postgres_version(engine)

    assert any("server_version_num" in sql for sql in engine.executed)


async def test_the_number_decides_when_the_banner_disagrees_upward() -> None:
    """A supported server behind an ancient-looking banner is accepted.

    The banner is the half a vendor rewrites. This is the shape that a
    string-parsing implementation gets wrong in the expensive direction: it
    refuses to start against a perfectly supported server.
    """
    engine = _FakeEngine(version_num="160002", banner="PostgreSQL 9.6.24 compatible (Vendor Fork 3.1)")

    major_version, version_string = await validate_postgres_version(engine)

    assert major_version == 16
    assert version_string == "PostgreSQL 9.6.24 compatible (Vendor Fork 3.1)"


async def test_the_number_decides_when_the_banner_disagrees_downward() -> None:
    """An unsupported server behind a reassuring banner is still refused."""
    engine = _FakeEngine(version_num="140011", banner=_PG16_BANNER)

    with pytest.raises(PostgreSQLVersionError) as excinfo:
        await validate_postgres_version(engine)

    assert "14" in str(excinfo.value)
    assert str(MIN_REQUIRED_PG_VERSION) in str(excinfo.value)


async def test_a_vendor_banner_is_accepted_when_the_number_is_sound() -> None:
    """EnterpriseDB, Aurora and friends are PostgreSQL and report the GUC.

    Refusing these was a symptom of parsing the banner, not a safety property.
    """
    engine = _FakeEngine(
        version_num="160002",
        banner="EnterpriseDB 16.2 (Advanced Server) on x86_64-pc-linux-gnu, 64-bit",
    )

    major_version, _ = await validate_postgres_version(engine)

    assert major_version == 16


@pytest.mark.parametrize(
    ("version_num", "expected_major"),
    [
        ("160002", 16),
        ("160000", 16),
        ("170004", 17),
        ("180000", 18),
        ("1600002", 160),  # A future three-digit major must not truncate to 16.
    ],
)
async def test_supported_numbers_resolve_to_their_major(version_num: str, expected_major: int) -> None:
    engine = _FakeEngine(version_num=version_num, banner=_PG16_BANNER)

    major_version, _ = await validate_postgres_version(engine)

    assert major_version == expected_major


async def test_the_pre_ten_numbering_era_is_read_as_nine_not_ninety() -> None:
    """``9.6.24`` is ``90624``; a naive ``num // 100`` would read 906 and pass."""
    engine = _FakeEngine(version_num="90624", banner="PostgreSQL 9.6.24 on x86_64-pc-linux-gnu, 64-bit")

    with pytest.raises(PostgreSQLVersionError) as excinfo:
        await validate_postgres_version(engine)

    assert "version 9 is not supported" in str(excinfo.value)


async def test_the_minimum_itself_is_accepted() -> None:
    """The boundary: exactly the minimum passes, one major below does not."""
    at_minimum = _FakeEngine(version_num=f"{MIN_REQUIRED_PG_VERSION * 10000}", banner=_PG16_BANNER)
    below = _FakeEngine(version_num=f"{(MIN_REQUIRED_PG_VERSION - 1) * 10000}", banner=_PG16_BANNER)

    major_version, _ = await validate_postgres_version(at_minimum)
    assert major_version == MIN_REQUIRED_PG_VERSION

    with pytest.raises(PostgreSQLVersionError):
        await validate_postgres_version(below)


# ---------------------------------------------------------------------------
# An unreadable number is not a reason to consult the banner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version_num",
    [
        "sixteen",
        "16.2",
        "",
        "   ",
        None,
        "0",
        "-1",
    ],
)
async def test_an_unreadable_number_raises_and_does_not_fall_back(version_num: object) -> None:
    """The defect this file exists to pin.

    The banner handed to the engine is a perfectly parseable, perfectly
    supported ``PostgreSQL 16.2``. An implementation that treats "could not read
    the number" as "try the string instead" therefore returns 16 here and looks
    correct. It is not correct: the server answered the GUC query with
    something we do not understand, which means it was never identified, and
    the string it also serves is written by whoever built it.
    """
    engine = _FakeEngine(version_num=version_num, banner=_PG16_BANNER)

    with pytest.raises(PostgreSQLVersionError) as excinfo:
        await validate_postgres_version(engine)

    assert "server_version_num" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The documented fallback: the number could not be QUERIED
# ---------------------------------------------------------------------------


async def test_an_unavailable_number_falls_back_to_the_banner() -> None:
    engine = _FakeEngine(version_num=_NUM_QUERY_FAILS, banner=_PG16_BANNER)

    major_version, version_string = await validate_postgres_version(engine)

    assert major_version == 16
    assert version_string == _PG16_BANNER


async def test_the_fallback_says_so_in_the_log(caplog) -> None:
    """A degraded read that nobody can see is a degraded read nobody fixes."""
    engine = _FakeEngine(version_num=_NUM_QUERY_FAILS, banner=_PG16_BANNER)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        await validate_postgres_version(engine)

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("server_version_num" in message for message in warnings)


@pytest.mark.parametrize(
    "banner",
    [
        "PostgreSQL 16.2 on x86_64-pc-linux-gnu, compiled by gcc (GCC) 9.3.0, 64-bit",
        # Two-digit minor: the major must not be misread as 1.
        "PostgreSQL 16.10 on x86_64-pc-linux-gnu, compiled by gcc (GCC) 9.3.0, 64-bit",
        # Pre-release builds carry no dot between major and suffix.
        "PostgreSQL 17beta1 on x86_64-pc-linux-gnu, compiled by gcc, 64-bit",
        "PostgreSQL 18rc1 on aarch64-apple-darwin, compiled by clang, 64-bit",
        # Distribution builds wrap the number in their own packaging string.
        "PostgreSQL 16.2 (Ubuntu 16.2-1.pgdg22.04+1) on x86_64-pc-linux-gnu, 64-bit",
    ],
)
async def test_fallback_banner_shapes_that_must_still_resolve(banner: str) -> None:
    engine = _FakeEngine(version_num=_NUM_QUERY_FAILS, banner=banner)

    major_version, returned = await validate_postgres_version(engine)

    assert major_version >= MIN_REQUIRED_PG_VERSION
    assert returned == banner


async def test_fallback_onto_an_unparseable_banner_raises() -> None:
    """Both sources unusable is the one case with nothing left to check."""
    engine = _FakeEngine(
        version_num=_NUM_QUERY_FAILS,
        banner="EnterpriseDB 16.2 (Advanced Server) on x86_64, 64-bit",
    )

    with pytest.raises(PostgreSQLVersionError, match="Could not parse"):
        await validate_postgres_version(engine)


async def test_fallback_onto_an_empty_banner_raises() -> None:
    engine = _FakeEngine(version_num=_NUM_QUERY_FAILS, banner="")

    with pytest.raises(PostgreSQLVersionError, match="empty"):
        await validate_postgres_version(engine)


async def test_fallback_onto_an_old_banner_still_enforces_the_minimum() -> None:
    """The fallback widens where the number comes from, not what is accepted."""
    engine = _FakeEngine(version_num=_NUM_QUERY_FAILS, banner=_PG14_BANNER)

    with pytest.raises(PostgreSQLVersionError) as excinfo:
        await validate_postgres_version(engine)

    assert "14" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Connection-level failures
# ---------------------------------------------------------------------------


async def test_a_lost_banner_does_not_discard_a_sound_number() -> None:
    """Only the description is lost, and the caller is told what was read."""
    engine = _FakeEngine(version_num="160002", banner=_BANNER_QUERY_FAILS)

    major_version, version_string = await validate_postgres_version(engine)

    assert major_version == 16
    assert "160002" in version_string


async def test_both_probes_failing_is_reported_as_an_unreachable_database() -> None:
    engine = _FakeEngine(version_num=_NUM_QUERY_FAILS, banner=_BANNER_QUERY_FAILS)

    with pytest.raises(PostgreSQLVersionError, match="Could not query PostgreSQL version"):
        await validate_postgres_version(engine)


async def test_an_unreachable_engine_is_wrapped() -> None:
    with pytest.raises(PostgreSQLVersionError, match="Could not query PostgreSQL version"):
        await validate_postgres_version(_UnreachableEngine())


async def test_the_error_is_a_runtime_error() -> None:
    """``app.main`` catches ``Exception`` around the call and re-raises.

    The startup guard only works while this stays inside that hierarchy.
    """
    assert issubclass(PostgreSQLVersionError, RuntimeError)


# ---------------------------------------------------------------------------
# The sweep: no failure shape may return
# ---------------------------------------------------------------------------


def _failing_engines() -> list[object]:
    """Every shape in which the server fails to identify itself."""
    return [
        pytest.param(_UnreachableEngine(), id="unreachable"),
        pytest.param(
            _FakeEngine(version_num=_NUM_QUERY_FAILS, banner=_BANNER_QUERY_FAILS),
            id="both-probes-fail",
        ),
        pytest.param(_FakeEngine(version_num="sixteen", banner=_PG16_BANNER), id="unreadable-number"),
        pytest.param(_FakeEngine(version_num="", banner=_PG16_BANNER), id="empty-number"),
        pytest.param(_FakeEngine(version_num=None, banner=_PG16_BANNER), id="missing-number"),
        pytest.param(_FakeEngine(version_num="0", banner=_PG16_BANNER), id="zero-number"),
        pytest.param(_FakeEngine(version_num="140011", banner=_PG16_BANNER), id="old-number"),
        pytest.param(
            _FakeEngine(version_num=_NUM_QUERY_FAILS, banner=_PG14_BANNER),
            id="old-fallback-banner",
        ),
        pytest.param(
            _FakeEngine(version_num=_NUM_QUERY_FAILS, banner="Vendor DB 3.1"),
            id="unparseable-fallback-banner",
        ),
        pytest.param(_FakeEngine(version_num=_NUM_QUERY_FAILS, banner=""), id="empty-fallback-banner"),
    ]


@pytest.mark.parametrize("engine", _failing_engines())
async def test_no_failing_engine_ever_returns_normally(engine: object) -> None:
    """Silently continuing past an unverified version is the defect.

    Asserted as a sweep rather than one branch at a time so that a future
    "return a sensible default instead of raising" edit cannot pass by fixing
    up a single test.
    """
    with pytest.raises(PostgreSQLVersionError):
        await validate_postgres_version(engine)
