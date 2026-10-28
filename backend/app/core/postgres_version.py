# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Refuse to start against a PostgreSQL the platform does not support.

The minimum is :data:`MIN_REQUIRED_PG_VERSION`, kept in step with the server
features the schema relies on (see ``backend/pyproject.toml``).

**How the version is read.** The authoritative source is ``server_version_num``,
the integer GUC every server since 8.2 exposes: ``160002`` for 16.2, ``90624``
for 9.6.24. It is a number, so there is nothing to misread - no locale, no
marketing banner, no release-candidate suffix. The major version is
``num // 10000`` in both the modern (``16.2`` -> ``160002``) and the pre-10
(``9.6.24`` -> ``90624``) numbering eras.

``SELECT version()`` is read too, but for two different jobs that must not be
confused:

* Always, as the human-readable string this returns and logs. It names the
  build, the platform and the vendor, which is what an operator needs in a
  failure message.
* Only when the ``server_version_num`` query itself could not be executed, as a
  documented *fallback* parse. Some poolers and wire-protocol proxies answer
  ``SELECT version()`` and nothing else.

The banner is a fallback for an *unavailable* number, never for an *unreadable*
one. A ``server_version_num`` that comes back and does not look like an integer
is a server we failed to identify, and this refuses to start rather than
guessing from a string that vendors are free to write however they like -
``"PostgreSQL 16.2 (Ubuntu 16.2-1.pgdg22.04+1)"``, ``"PostgreSQL 17beta1"``,
``"EnterpriseDB 16.2 (Advanced Server)"``, an Aurora banner, a fork that only
claims compatibility. Reading a number the server computed is the fix; a wider
regex only moves which strings get misread.

**Every failure raises.** Unreachable server, empty answer, unreadable number,
unparseable banner, version below the minimum - all of them raise
:class:`PostgreSQLVersionError`. Continuing past a version that was never
identified is the failure mode this module exists to prevent: the process would
come up, build a schema and take writes on a server whose capabilities nobody
checked, and the first symptom would arrive much later as a broken query. The
caller in ``app.main`` logs the cause and re-raises, so startup stops here.

**Two entry points, one rule.** :func:`validate_postgres_version` is the
application's, over the async engine it serves requests on.
:func:`validate_postgres_version_sync` is ``alembic/env.py``'s, over the sync
engine migrations run on - a database is reached that way too, by an operator
who has not booted the app, and that path builds the whole schema on a blank
server. Both are thin: they run the same two statements and hand the results to
:func:`_resolve_version`, which holds the entire rule. Nothing about the floor,
the authoritative source or the fallback is written down twice, because two
copies of a version floor drift apart.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

MIN_REQUIRED_PG_VERSION = 16

# The authoritative read: an integer GUC, not prose. ``current_setting`` is a
# plain SELECT, so it survives drivers and poolers that special-case ``SHOW``.
_VERSION_NUM_SQL = "SELECT current_setting('server_version_num')"

# Read for the human-readable string on every run, and parsed only when the
# query above could not be executed at all.
_VERSION_BANNER_SQL = "SELECT version()"

# From 10 onward the number is two components, major * 10000 + minor (16.2 ->
# 160002). Before 10 it was three, major * 10000 + minor * 100 + patch (9.6.24
# -> 90624). Either way the major is the leading group of 10000.
_VERSION_NUM_DIVISOR = 10000

_BANNER_MAJOR = re.compile(r"PostgreSQL\s+(\d+)", re.IGNORECASE)


class PostgreSQLVersionError(RuntimeError):
    """Raised when the connected PostgreSQL cannot be identified or is too old.

    Covers both halves deliberately. A server below the minimum and a server
    whose version could not be read are the same outcome for the caller: this
    process must not run against it.
    """


async def _scalar(engine: AsyncEngine, statement: str) -> object:
    """Run ``statement`` on its own connection and return the first column.

    Each probe gets a fresh connection on purpose. A statement that errors
    aborts its transaction on PostgreSQL, so sharing one connection would make
    the banner unreadable exactly when the fallback needs it.
    """
    from sqlalchemy import text

    async with engine.connect() as conn:
        result = await conn.execute(text(statement))
        return result.scalar()


def _scalar_sync(engine: Engine, statement: str) -> object:
    """:func:`_scalar` over a synchronous engine, for the alembic entry point.

    Same one connection per probe, for the same reason: an errored statement
    aborts its transaction, and the fallback needs the banner readable exactly
    when the number was not.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(text(statement))
        return result.scalar()


def _major_from_version_num(raw: object) -> int:
    """Major version from a ``server_version_num`` value.

    Args:
        raw: Whatever the server returned for ``server_version_num``.

    Returns:
        The major version, e.g. ``16`` for ``160002`` and ``9`` for ``90624``.

    Raises:
        PostgreSQLVersionError: If the value is missing, empty or not a
            positive integer. This does NOT fall back to the banner: a number
            that came back unreadable means the server answered something we do
            not understand, and guessing from prose is what this replaced.
    """
    text_value = "" if raw is None else str(raw).strip()
    if not text_value:
        raise PostgreSQLVersionError(
            "PostgreSQL returned an empty server_version_num. The server did not identify itself, "
            "so its version cannot be verified."
        )
    try:
        number = int(text_value)
    except ValueError as exc:
        raise PostgreSQLVersionError(
            f"PostgreSQL returned an unreadable server_version_num: {text_value!r}. "
            f"Expected an integer such as 160002 for 16.2."
        ) from exc
    if number <= 0:
        raise PostgreSQLVersionError(
            f"PostgreSQL returned an out-of-range server_version_num: {number}. "
            f"Expected a positive integer such as 160002 for 16.2."
        )
    return number // _VERSION_NUM_DIVISOR


def _major_from_banner(version_string: str) -> int:
    """Major version parsed out of a ``SELECT version()`` banner.

    The fallback path only. Matches the leading integer after the product name,
    so ``PostgreSQL 16.10 ...`` reads as 16 and ``PostgreSQL 17beta1 ...`` as
    17, while a vendor banner that never says "PostgreSQL" is refused instead of
    being guessed at.

    Raises:
        PostgreSQLVersionError: If no major version can be read from the string.
    """
    if not version_string:
        raise PostgreSQLVersionError(
            "PostgreSQL version query returned empty result, and server_version_num was unavailable."
        )
    match = _BANNER_MAJOR.search(version_string)
    if not match:
        raise PostgreSQLVersionError(
            f"Could not parse PostgreSQL version from: {version_string}. Expected format: 'PostgreSQL X.Y.Z ...'"
        )
    return int(match.group(1))


def _resolve_version(
    raw_number: object,
    number_error: Exception | None,
    banner: object,
    banner_error: Exception | None,
) -> tuple[int, str]:
    """Turn the two probe results into a verified major version, or refuse.

    The whole rule lives here: which source is authoritative, when the banner
    is allowed to stand in for the number, and what the floor is. The entry
    points differ only in how they run the two statements, so neither of them
    restates any part of this.

    Args:
        raw_number: What ``server_version_num`` returned, if it was queryable.
        number_error: The exception that statement raised, or ``None``.
        banner: What ``SELECT version()`` returned, if it was queryable.
        banner_error: The exception that statement raised, or ``None``.

    Returns:
        Tuple of ``(major_version, version_string)``.

    Raises:
        PostgreSQLVersionError: For every shape of failure. There is no path
            that returns normally without having read a version.
    """
    if banner_error is not None:
        if number_error is not None:
            # Neither probe ran: the server is unreachable, not merely unusual.
            raise PostgreSQLVersionError(
                "Could not query PostgreSQL version. Make sure the database is running and accessible. "
                f"Error: {banner_error}"
            ) from banner_error
        # The number is authoritative and it arrived; losing the banner costs
        # only the readable description.
        logger.warning("PostgreSQL banner query failed (%s); reporting the numeric version only", banner_error)
        banner = None

    version_string = str(banner).strip() if banner else ""

    if number_error is None:
        major_version = _major_from_version_num(raw_number)
        source = "server_version_num"
        if not version_string:
            version_string = f"PostgreSQL (server_version_num={raw_number})"
    else:
        logger.warning(
            "PostgreSQL server_version_num is unavailable (%s); falling back to parsing SELECT version()",
            number_error,
        )
        major_version = _major_from_banner(version_string)
        source = "version() banner (fallback)"

    if major_version < MIN_REQUIRED_PG_VERSION:
        raise PostgreSQLVersionError(
            f"PostgreSQL version {major_version} is not supported. "
            f"Minimum required version: {MIN_REQUIRED_PG_VERSION}. "
            f"Full version string: {version_string}"
        )

    logger.info(
        "PostgreSQL %d.x validated via %s (full version: %s)",
        major_version,
        source,
        version_string,
    )
    return major_version, version_string


async def validate_postgres_version(engine: AsyncEngine) -> tuple[int, str]:
    """Validate that the connected PostgreSQL meets the minimum version.

    Args:
        engine: SQLAlchemy AsyncEngine connected to PostgreSQL.

    Returns:
        Tuple of ``(major_version, version_string)``. The string is the
        ``SELECT version()`` banner when the server gave one, otherwise a
        synthesised description of the number that was read.

    Raises:
        PostgreSQLVersionError: If the server cannot be reached, cannot be
            identified, or reports a major version below
            :data:`MIN_REQUIRED_PG_VERSION`. There is no path that returns
            normally without having read a version.
    """
    try:
        raw_number = await _scalar(engine, _VERSION_NUM_SQL)
    except Exception as exc:  # noqa: BLE001 - any driver/server failure means "unavailable"
        number_error: Exception | None = exc
        raw_number = None
    else:
        number_error = None

    try:
        banner = await _scalar(engine, _VERSION_BANNER_SQL)
    except Exception as exc:  # noqa: BLE001 - the banner is optional; _resolve_version decides
        banner_error: Exception | None = exc
        banner = None
    else:
        banner_error = None

    return _resolve_version(raw_number, number_error, banner, banner_error)


def validate_postgres_version_sync(engine: Engine) -> tuple[int, str]:
    """Validate the minimum version over a synchronous engine.

    The alembic entry point. ``alembic upgrade head`` reaches a database
    without the application ever booting, and on a blank server it builds the
    entire schema, so it has to ask the same question the application asks -
    and ask it of the engine the migration itself runs on, rather than of a
    second one built from the async URL, which a deployment is free to point
    somewhere else.

    Args:
        engine: SQLAlchemy Engine connected to PostgreSQL.

    Returns:
        Tuple of ``(major_version, version_string)``, as
        :func:`validate_postgres_version`.

    Raises:
        PostgreSQLVersionError: On every failure shape the async entry point
            raises on, for the same reasons.
    """
    try:
        raw_number = _scalar_sync(engine, _VERSION_NUM_SQL)
    except Exception as exc:  # noqa: BLE001 - any driver/server failure means "unavailable"
        number_error: Exception | None = exc
        raw_number = None
    else:
        number_error = None

    try:
        banner = _scalar_sync(engine, _VERSION_BANNER_SQL)
    except Exception as exc:  # noqa: BLE001 - the banner is optional; _resolve_version decides
        banner_error: Exception | None = exc
        banner = None
    else:
        banner_error = None

    return _resolve_version(raw_number, number_error, banner, banner_error)


__all__ = [
    "MIN_REQUIRED_PG_VERSION",
    "PostgreSQLVersionError",
    "validate_postgres_version",
    "validate_postgres_version_sync",
]
