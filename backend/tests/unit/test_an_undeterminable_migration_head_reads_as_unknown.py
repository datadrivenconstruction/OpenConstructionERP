"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A schema-version signal must be able to say "I could not tell".

``/api/health`` reports ``alembic_head_matches``, and it used to compute it as
``expected == actual`` on two values either of which can legitimately be absent.
Both absences came out as ``False``, which is not "unknown" but "known wrong",
and consumers act on it. The desktop launcher acted on it hardest: a backend
reporting ``false`` was refused, and refusing meant starting a SECOND backend
against the running one's data directory.

The two absences are ordinary, not exotic:

* ``expected`` is ``None`` wherever no migration tree shipped. That is every
  desktop build, deliberately - the frozen bundle carries neither ``alembic.ini``
  nor the script directory, for reasons ``test_desktop_spec_ships_wheel_data.py``
  sets out at length.
* ``actual`` is ``None`` on any database with no ``alembic_version`` row. That is
  every install created before the boot-time stamp existed, and every install
  where the stamp could not be written - an external PostgreSQL whose role has
  no DDL rights, for one. Those databases are physically at head. Nobody wrote
  it down.

So the helper is tested here rather than the endpoint: the comparison is the
whole defect, it is pure, and pinning it needs no database and no client.
"""

from __future__ import annotations

from app.main import alembic_head_state

HEAD = "v3299_latest"
BEHIND = "v3100_older"


def test_an_unstamped_database_is_unknown_and_not_a_mismatch() -> None:
    """The case that reported ``false`` forever on a healthy install."""
    assert alembic_head_state(HEAD, None) is None


def test_a_deployment_with_no_migration_tree_is_unknown() -> None:
    """The desktop build. It has nothing to compare against, so it says so."""
    assert alembic_head_state(None, HEAD) is None


def test_neither_side_known_is_still_unknown() -> None:
    assert alembic_head_state(None, None) is None


def test_a_real_mismatch_is_still_reported() -> None:
    """The other polarity, and the reason the signal exists at all.

    A check that answered "unknown" to everything would pass the tests above and
    tell an operator nothing about the deploy where somebody really did forget
    to migrate.
    """
    assert alembic_head_state(HEAD, BEHIND) is False


def test_a_database_at_head_is_reported_as_at_head() -> None:
    assert alembic_head_state(HEAD, HEAD) is True


def test_unknown_is_distinguishable_from_a_mismatch_by_a_caller() -> None:
    """``None`` and ``False`` must not be interchangeable to the consumer.

    Written against the way this is consumed rather than the way it is computed.
    Every reader of the flag branches on it, and a reader that treats a falsy
    answer as a mismatch reintroduces the whole defect while this module keeps
    returning the right values. ``is False`` is the test that survives that;
    ``not value`` is the one that does not.
    """
    unknown = alembic_head_state(HEAD, None)
    mismatch = alembic_head_state(HEAD, BEHIND)

    assert unknown is not mismatch
    assert unknown is not False, "unknown must not answer the mismatch question"
    assert mismatch is False
    # Both are falsy. A consumer written as ``if not matches:`` cannot tell them
    # apart, which is why the flag has to be read with ``is False``.
    assert not unknown and not mismatch


def test_the_naive_comparison_it_replaces_would_have_been_wrong() -> None:
    """Name the old behaviour so a revert cannot pass quietly.

    ``expected == actual`` is the expression this helper exists to stop being
    written inline again. On the two unknown inputs it is ``False``, which is
    the bug, so the helper has to differ from it there and agree with it
    everywhere else.
    """
    for expected, actual in ((HEAD, None), (None, HEAD), (None, None)):
        assert (expected == actual) is not alembic_head_state(expected, actual), (
            f"the helper still behaves like a bare == for ({expected!r}, {actual!r})"
        )

    for expected, actual in ((HEAD, HEAD), (HEAD, BEHIND)):
        assert (expected == actual) is alembic_head_state(expected, actual)
