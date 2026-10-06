"""Stamping a populated, unstamped database destroys the only evidence it is odd.

Releases before 15.4.0 shipped no ``alembic.ini``, so their databases record no
revision at all. On boot ``create_all`` creates whatever tables are wholly
absent and cannot alter the ones already there, which leaves such a database
part-migrated. Stamping head over the top then claims a schema state nothing
verified, and the absent revision was the only durable record that the database
was not at head.

Refusing to stamp is reversible; the database can always be stamped later once
the repair for this cohort is verified. Stamping is not. MISC-14 (6 October
2026) confirms refusal rather than automatic revision inference; these tests
pin that branch independently of the health endpoint's degraded signal.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.core.alembic_version_table import database_is_populated_but_unstamped, stamp_head_if_unstamped


def _connect() -> sa.Connection:
    return sa.create_engine("sqlite://").connect()


def test_a_blank_database_is_not_the_populated_cohort() -> None:
    """A fresh install has no application tables, so it is stampable as before."""
    with _connect() as conn:
        assert database_is_populated_but_unstamped(conn) is False


def test_application_tables_with_no_revision_are_the_cohort() -> None:
    """Tables but no revision is exactly the pre-15.4.0 shape."""
    with _connect() as conn:
        conn.execute(sa.text("CREATE TABLE oe_projects (id INTEGER PRIMARY KEY)"))
        assert database_is_populated_but_unstamped(conn) is True


def test_a_database_that_names_its_revision_is_not_the_cohort() -> None:
    """15.4.0 and later arrive stamped, and those have an ordinary repair."""
    with _connect() as conn:
        conn.execute(sa.text("CREATE TABLE oe_projects (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(128) NOT NULL)"))
        conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('v3302')"))
        assert database_is_populated_but_unstamped(conn) is False


def test_tables_that_are_not_ours_do_not_make_a_database_populated() -> None:
    """The negative control. Only ``oe_*`` tables count as our schema.

    Without this, any database carrying an unrelated table would be read as the
    cohort and would never be stamped, which is a far wider refusal than the one
    intended.
    """
    with _connect() as conn:
        conn.execute(sa.text("CREATE TABLE some_other_apps_table (id INTEGER PRIMARY KEY)"))
        assert database_is_populated_but_unstamped(conn) is False


def test_the_stamp_is_refused_when_the_caller_says_populated() -> None:
    """The refusal returns None and writes nothing."""
    with _connect() as conn:
        conn.execute(sa.text("CREATE TABLE oe_projects (id INTEGER PRIMARY KEY)"))

        assert stamp_head_if_unstamped(conn, refuse_when_populated=True) is None

        # Nothing was written: no version table came into existence.
        assert not sa.inspect(conn).has_table("alembic_version")


def test_without_the_refusal_the_same_database_does_get_stamped() -> None:
    """The control that has to come out the other way, or the refusal proves nothing.

    A guard that returns None on a path which would have returned None anyway is
    indistinguishable from no guard at all. This runs the identical database
    through the identical call with the flag off and shows head being written,
    which is what makes the refusal above a measurement rather than an assertion
    about a value.
    """
    with _connect() as conn:
        conn.execute(sa.text("CREATE TABLE oe_projects (id INTEGER PRIMARY KEY)"))

        stamped = stamp_head_if_unstamped(conn, refuse_when_populated=False)

        assert stamped is not None, "expected the unguarded call to stamp this database"
        assert sa.inspect(conn).has_table("alembic_version")


def test_the_default_leaves_the_previous_behaviour_alone() -> None:
    """A caller that does not pass the flag behaves exactly as before.

    The guard has to be opt-in at the call site, because the question it answers
    can only be asked before ``create_all`` runs and this function is in no
    position to ask it.
    """
    import inspect as _inspect

    sig = _inspect.signature(stamp_head_if_unstamped)
    assert sig.parameters["refuse_when_populated"].default is False
