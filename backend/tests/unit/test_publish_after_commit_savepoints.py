# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``publish_after_commit`` must follow the fate of the transaction it was deferred in.

An event deferred inside a SAVEPOINT describes work done inside that savepoint.
When the savepoint is rolled back the work is gone, so the event must go with
it, even though the outer transaction goes on to commit. The reverse holds as
well: a savepoint that is released keeps its event, and a rollback of the outer
transaction drops everything deferred in it, including events whose savepoint
had already been released.

These tests drive the real SQLAlchemy session event machinery over an in-memory
SQLite database through a synchronous ``Session``. ``publish_after_commit`` only
touches ``in_transaction()`` and ``sync_session`` on the session it is given,
so a two-attribute adapter exercises exactly the listener code that runs under
an ``AsyncSession`` in production. The PostgreSQL lane repeats the core cases on
a real ``AsyncSession`` (tests/pg/test_publish_after_commit_savepoints_pg.py).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core import events as events_mod
from app.core.events import publish_after_commit


class _AsyncShape:
    """The two attributes of ``AsyncSession`` that ``publish_after_commit`` reads."""

    def __init__(self, sync_session: Session) -> None:
        self.sync_session = sync_session

    def in_transaction(self) -> bool:
        return self.sync_session.in_transaction()


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def _record(event_name: str, data: dict[str, Any] | None = None, *, source_module: str | None = None) -> None:
        seen.append(event_name)

    monkeypatch.setattr(events_mod.event_bus, "publish_detached", _record)
    return seen


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def _touch(sess: Session) -> None:
    """Start (or keep) a real transaction on the connection."""
    sess.execute(text("SELECT 1"))


def test_event_deferred_in_a_rolled_back_savepoint_is_dropped(session, published):
    _touch(session)
    nested = session.begin_nested()
    publish_after_commit(_AsyncShape(session), "x.in_rolled_back_savepoint")
    nested.rollback()
    session.commit()

    assert published == []


def test_event_deferred_in_a_released_savepoint_goes_out_on_the_outer_commit(session, published):
    _touch(session)
    with session.begin_nested():
        publish_after_commit(_AsyncShape(session), "x.in_released_savepoint")
    assert published == [], "a SAVEPOINT release is not the commit"
    session.commit()

    assert published == ["x.in_released_savepoint"]


def test_event_deferred_in_the_outer_transaction_survives_a_rolled_back_savepoint(session, published):
    _touch(session)
    publish_after_commit(_AsyncShape(session), "x.outer")
    nested = session.begin_nested()
    nested.rollback()
    session.commit()

    assert published == ["x.outer"]


def test_released_savepoint_inside_a_rolled_back_savepoint_drops_its_event(session, published):
    _touch(session)
    middle = session.begin_nested()
    with session.begin_nested():
        publish_after_commit(_AsyncShape(session), "x.inner")
    middle.rollback()
    session.commit()

    assert published == []


def test_outer_rollback_drops_everything_and_the_next_commit_stays_silent(session, published):
    _touch(session)
    publish_after_commit(_AsyncShape(session), "x.outer")
    with session.begin_nested():
        publish_after_commit(_AsyncShape(session), "x.released")
    session.rollback()

    # The same session goes on to commit an unrelated transaction. Nothing
    # deferred in the rolled-back one may ride along on it.
    _touch(session)
    session.commit()

    assert published == []


def test_close_without_commit_drops_the_event(session, published):
    _touch(session)
    publish_after_commit(_AsyncShape(session), "x.closed")
    session.close()

    _touch(session)
    session.commit()

    assert published == []


def test_only_the_rolled_back_savepoints_event_is_dropped(session, published):
    _touch(session)
    publish_after_commit(_AsyncShape(session), "x.outer")
    with session.begin_nested():
        publish_after_commit(_AsyncShape(session), "x.kept")
    doomed = session.begin_nested()
    publish_after_commit(_AsyncShape(session), "x.dropped")
    doomed.rollback()
    session.commit()

    assert sorted(published) == ["x.kept", "x.outer"]
