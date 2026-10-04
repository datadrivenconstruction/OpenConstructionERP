# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which market and language a loaded cost base is in, kept in the database.

A national base (China, Turkiye, ...) can be priced into any of 48 markets and
its work-item text switched to another language. Both rewrite the shared
``oe_costs_item`` rows of the base's region for everyone on the deployment, so
the answer to "which market is this base in" is a property of the region, not
of a user or a browser. It used to live in a process-local dict and in the
browser's storage: a restart forgot it, a second worker never knew it, and two
browsers could each show a different "active market" over the same rows.

This module is the one way in and out of that state (``oe_costs_base_state``)
and the one lock that serialises the operations that change it:

* :func:`read_base_state` / :func:`read_all_base_states` read it.
* :func:`write_base_state` upserts it and commits, so every marker written
  before a long step is durable before the step starts.
* :func:`forget_base_state` drops it when the region is wiped or reloaded.
* :func:`base_market_lock` lets one market switch, return home or language
  switch run per base at a time, across workers: an in-process
  :class:`asyncio.Lock` orders the requests of one worker, and a PostgreSQL
  session-level advisory lock, held on a connection of its own, orders the
  workers. A row lock would not do: the switch commits several times, one of
  them from a worker thread on its own connection, and a row lock ends with
  the first commit.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.modules.costs.models import CostBaseState

logger = logging.getLogger(__name__)

#: ``switching_to`` while a base is being brought back to its own home market.
RESTORING_HOME = "__home__"

#: First half of the two-int advisory lock key. The two-int key space does not
#: overlap the single-bigint one the migrator, RLS setup and cost explorer use,
#: and this namespace keeps it apart from any other two-int user.
_LOCK_NAMESPACE = 20_261_004

#: How long a second switch of the same base waits for the first to finish
#: before it gives up. A large base takes minutes to reprice, so this is long on
#: purpose: the old in-process lock waited without any bound at all.
LOCK_WAIT_S = 30 * 60.0

#: Seconds between two attempts at the advisory lock while waiting.
_LOCK_POLL_S = 0.5

_UNSET: Any = object()

_PROCESS_LOCKS: dict[str, asyncio.Lock] = {}


class BaseBusyError(RuntimeError):
    """Another switch of the same base held the lock for longer than the wait."""


@dataclass(frozen=True)
class BaseState:
    """A read of one base's stored state, detached from the session."""

    region: str
    text_language: str | None
    active_market: str | None
    switching_to: str | None
    updated_at: datetime | None

    @property
    def market_state(self) -> str:
        """``switching`` while a change runs or after one was cut off, else ``market`` or ``home``."""
        if self.switching_to:
            return "switching"
        return "market" if self.active_market else "home"

    def public(self) -> dict[str, Any]:
        """The JSON shape ``/base-catalog`` and the switch endpoints return."""
        return {
            "market_state": self.market_state,
            "active_market": self.active_market,
            "switching_to": self.switching_to,
            "text_language": self.text_language,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def _snapshot(row: CostBaseState) -> BaseState:
    return BaseState(
        region=row.region,
        text_language=row.text_language,
        active_market=row.active_market,
        switching_to=row.switching_to,
        updated_at=row.updated_at,
    )


async def read_base_state(session: AsyncSession, region: str) -> BaseState | None:
    """Return the stored state of one base region, or ``None`` when nothing is stored.

    ``None`` means "not known", never "home market": a base loaded before this
    record existed has no row, and its rows may well be priced into a market.
    """
    row = (await session.execute(select(CostBaseState).where(CostBaseState.region == region))).scalar_one_or_none()
    return _snapshot(row) if row is not None else None


async def read_all_base_states(session: AsyncSession) -> dict[str, BaseState]:
    """Return every stored base state, keyed by region."""
    rows = (await session.execute(select(CostBaseState))).scalars().all()
    return {row.region: _snapshot(row) for row in rows}


async def write_base_state(
    session: AsyncSession,
    region: str,
    *,
    text_language: str | None = _UNSET,
    active_market: str | None = _UNSET,
    switching_to: str | None = _UNSET,
    updated_by: uuid.UUID | None = None,
    commit: bool = True,
) -> None:
    """Upsert the fields given for ``region`` and commit.

    Only the keyword arguments actually passed are written, so a caller that
    records the language leaves the market alone and the other way round.
    Committed by default because every caller writes a marker that must be
    durable before the long step that follows it starts.
    """
    values: dict[str, Any] = {}
    if text_language is not _UNSET:
        values["text_language"] = text_language
    if active_market is not _UNSET:
        values["active_market"] = active_market
    if switching_to is not _UNSET:
        values["switching_to"] = switching_to
    if updated_by is not None:
        values["updated_by"] = updated_by
    stmt = pg_insert(CostBaseState).values(id=uuid.uuid4(), region=region, **values)
    # ``onupdate`` does not reach an ON CONFLICT branch, so the time is set here.
    stmt = stmt.on_conflict_do_update(
        index_elements=[CostBaseState.region],
        set_={**values, "updated_at": func.now()},
    )
    await session.execute(stmt)
    if commit:
        await session.commit()


async def forget_base_state(session: AsyncSession, region: str, *, commit: bool = True) -> None:
    """Drop what is stored for ``region``: its rows were wiped or are being reloaded."""
    await session.execute(delete(CostBaseState).where(CostBaseState.region == region))
    if commit:
        await session.commit()


def _process_lock(region: str) -> asyncio.Lock:
    lock = _PROCESS_LOCKS.get(region)
    if lock is None:
        lock = _PROCESS_LOCKS[region] = asyncio.Lock()
    return lock


def _engine_of(session: AsyncSession | None) -> AsyncEngine | None:
    """The engine behind ``session``, so the lock lands in the same database.

    Taken from the session and never from the application's global engine: in
    the test suite those point at different databases, and an advisory lock only
    excludes holders in the same database.
    """
    bind = getattr(session, "bind", None)
    if isinstance(bind, AsyncConnection):
        return bind.engine
    if isinstance(bind, AsyncEngine):
        return bind
    return None


@contextlib.asynccontextmanager
async def _advisory_lock(engine: AsyncEngine, region: str, wait_s: float) -> AsyncIterator[None]:
    params = {"ns": _LOCK_NAMESPACE, "region": region}
    conn = await engine.connect()
    try:
        deadline = time.monotonic() + wait_s
        while True:
            got = (await conn.execute(text("SELECT pg_try_advisory_lock(:ns, hashtext(:region))"), params)).scalar()
            # A session-level lock outlives the transaction that took it. Ending
            # the transaction keeps this connection from sitting idle inside one,
            # which the server's idle-in-transaction timeout would end by
            # closing the connection and so silently dropping the lock.
            await conn.commit()
            if got:
                break
            if time.monotonic() >= deadline:
                raise BaseBusyError(f"Another market switch of '{region}' is still running.")
            await asyncio.sleep(_LOCK_POLL_S)
        try:
            yield
        finally:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(:ns, hashtext(:region))"), params)
                await conn.commit()
            except Exception:  # noqa: BLE001 - closing the connection below releases it anyway
                logger.warning("Could not release the market lock of %s; dropping the connection", region)
                await conn.invalidate()
    finally:
        await conn.close()


@contextlib.asynccontextmanager
async def base_market_lock(
    session: AsyncSession | None,
    region: str,
    *,
    wait_s: float = LOCK_WAIT_S,
) -> AsyncIterator[None]:
    """Hold the one lock that orders every change to ``region``'s market and language.

    Raises :class:`BaseBusyError` when another worker held it for longer than
    ``wait_s``. Without a PostgreSQL session (a unit test that passes none) only
    the in-process lock is taken.
    """
    async with _process_lock(region):
        engine = _engine_of(session)
        if engine is None or engine.dialect.name != "postgresql":
            yield
        else:
            async with _advisory_lock(engine, region, wait_s):
                yield
