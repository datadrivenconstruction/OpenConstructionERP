"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What ``clear_module_tables`` must do when somebody leaks a transaction.

The nightly cross-OS job used to die at 9% of the suite. The cause was not the
test that failed but the one after it: a fixture rebuilt the schema per test
with ``Base.metadata.drop_all``, DROP TABLE needs ACCESS EXCLUSIVE, and the
failing test had left a connection ``idle in transaction`` holding ACCESS SHARE
on one of those tables. No statement timeout covers a lock wait, so the drop
waited forever and the 900-second per-test timeout eventually killed the whole
process - taking the other 91% of the tree with it and printing no test name,
because pytest writes a node id without a trailing newline.

"The file passes now" would not prove that fixed: the file would also pass if
the failing assertion had simply stopped failing while the mechanism survived.
So these tests plant the leak deliberately and measure what the clear does
about it. Both hold a real lock from a second connection and assert on elapsed
time, which is the thing only the new mechanism can change.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from sqlalchemy import text

import app.modules.crm.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from tests import _pg
from tests._pg import clear_module_tables, create_module_tables

pytestmark = pytest.mark.asyncio

# Generous enough that a loaded CI machine cannot trip it by being slow, and
# far below the 30s budget a real lock wait would spend.
_FAST_S = 10.0


@pytest_asyncio.fixture(scope="module")
async def lead_table():
    from app.database import engine
    from app.modules.crm.models import Lead
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    if engine.dialect.name != "postgresql":
        pytest.skip("lock behaviour is PostgreSQL-specific")

    await create_module_tables(User, Project, Lead)
    return Lead


async def test_a_stray_reader_does_not_block_the_clear(lead_table) -> None:
    """The exact shape that wedged the nightly: ACCESS SHARE, held open."""
    from app.database import engine

    stray = await engine.connect()
    try:
        # A plain SELECT takes ACCESS SHARE and holds it for the life of the
        # transaction. Never committed, never rolled back - a leaked session.
        await stray.execute(text(f'SELECT 1 FROM "{lead_table.__table__.name}" LIMIT 1'))

        started = time.monotonic()
        await clear_module_tables((lead_table,))
        elapsed = time.monotonic() - started

        assert elapsed < _FAST_S, (
            f"clear waited {elapsed:.1f}s behind a stray reader; DELETE takes "
            "ROW EXCLUSIVE and must not queue behind ACCESS SHARE"
        )
    finally:
        await stray.rollback()
        await stray.close()


async def test_the_same_leak_would_have_blocked_a_truncate(lead_table) -> None:
    """Control: prove the stray reader really does hold a conflicting lock.

    Without this, the test above passes just as happily against a lock nobody
    is holding, and would go green on a leak it never reproduced. TRUNCATE
    takes the same ACCESS EXCLUSIVE that DROP TABLE does, so it is the old
    behaviour in miniature - bounded here only because we set a timeout the
    old fixture did not have.
    """
    from sqlalchemy.exc import DBAPIError

    from app.database import engine

    async def truncate_under_a_two_second_timeout() -> None:
        """The blocked statement, as one call so the raises block stays one.

        The timeout and the TRUNCATE have to share a transaction - SET LOCAL
        lasts only as long as the one it is issued in - so they cannot be
        split apart to satisfy the single-statement rule. Naming the pair is
        what satisfies it, and it also names what is being timed below.
        """
        async with engine.begin() as conn:
            await conn.exec_driver_sql("SET LOCAL lock_timeout = '2s'")
            await conn.exec_driver_sql(f'TRUNCATE TABLE "{lead_table.__table__.name}"')

    stray = await engine.connect()
    try:
        await stray.execute(text(f'SELECT 1 FROM "{lead_table.__table__.name}" LIMIT 1'))

        started = time.monotonic()
        with pytest.raises(DBAPIError) as exc:
            await truncate_under_a_two_second_timeout()
        elapsed = time.monotonic() - started

        assert "lock timeout" in str(exc.value).lower()
        # It has to actually WAIT - an instant failure would mean something
        # other than the lock refused it.
        assert 2.0 <= elapsed < _FAST_S, f"truncate resolved in {elapsed:.1f}s, expected a ~2s lock wait"
    finally:
        await stray.rollback()
        await stray.close()


async def test_a_conflicting_lock_fails_fast_instead_of_hanging(lead_table, monkeypatch) -> None:
    """When something genuinely does block a DELETE, it must end in seconds.

    SHARE conflicts with the ROW EXCLUSIVE a DELETE takes, so this is the
    residual case the timeout exists for. The point is not that it succeeds -
    it must not - but that it gives up with a named error rather than running
    out the job's clock.
    """
    from sqlalchemy.exc import DBAPIError

    from app.database import engine

    monkeypatch.setattr(_pg, "LOCK_TIMEOUT_S", 2)

    stray = await engine.connect()
    try:
        await stray.execute(text(f'LOCK TABLE "{lead_table.__table__.name}" IN SHARE MODE'))

        started = time.monotonic()
        with pytest.raises(DBAPIError) as exc:
            await clear_module_tables((lead_table,))
        elapsed = time.monotonic() - started

        assert "lock timeout" in str(exc.value).lower()
        assert elapsed < _FAST_S, f"clear took {elapsed:.1f}s to give up on a 2s budget"
    finally:
        await stray.rollback()
        await stray.close()


async def test_abandoned_transactions_are_bounded_on_this_database() -> None:
    """`lock_timeout` frees the victim; only this removes the culprit.

    conftest sets ``idle_in_transaction_session_timeout`` with ALTER DATABASE,
    which lands only for sessions opened afterwards and fails silently if the
    role may not set it. Asking the server is the only way to know it is in
    force, so ask - on a live session, which is the population that matters.
    """
    from app.database import engine

    async with engine.connect() as conn:
        observed = (await conn.exec_driver_sql("SHOW idle_in_transaction_session_timeout")).scalar()

    assert observed not in (None, "0", "0ms"), (
        "idle_in_transaction_session_timeout is not in force on the test database; "
        "a transaction abandoned by a failing test would live until its connection closes"
    )
