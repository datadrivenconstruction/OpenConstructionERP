"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fakes for the saved-views security tests.

Pure-unit fakes so the gate tests run WITHOUT a database: a stub session that
records the SQL it is asked to execute, a tiny seed-row store, and helpers to
build a registered entity against an in-memory toy model. The DB-backed
integration tests use ``tests._pg.transactional_session`` instead and are gated
on a bootable PostgreSQL cluster.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class RecordingSession:
    """A stub ``AsyncSession`` that records statements instead of running them.

    ``execute`` returns a canned result built from ``rows`` so the service can be
    driven without a real database. ``bind`` is a SimpleNamespace exposing a
    dialect name so the statement-timeout path is a no-op on the fake.
    """

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[Any] = []
        self.added: list[Any] = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def execute(self, stmt: Any) -> Any:  # noqa: ANN401
        self.executed.append(stmt)
        rows = self.rows

        class _Result:
            def all(self_inner) -> list[Any]:  # noqa: N805
                return list(rows)

            def scalar_one(self_inner) -> Any:  # noqa: N805
                return len(rows)

            def first(self_inner) -> Any:  # noqa: N805
                """The first row, or ``None`` - what an existence probe reads.

                ``rows`` defaults to empty, so a service asking "is this name
                already taken" gets "no" on a stub session that was not seeded
                to say otherwise.
                """
                return rows[0] if rows else None

        return _Result()

    def add(self, obj: Any) -> None:  # noqa: ANN401
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model: Any, ident: Any) -> Any:  # noqa: ANN401
        return None

    async def delete(self, obj: Any) -> None:  # noqa: ANN401
        return None


class SpySession(RecordingSession):
    """A session that fails loudly if ``execute`` is ever called.

    Used to prove a gate refused a spec BEFORE any database round-trip.
    """

    async def execute(self, stmt: Any) -> Any:  # noqa: ANN401
        raise AssertionError("execute() was called but the query should have been refused")
