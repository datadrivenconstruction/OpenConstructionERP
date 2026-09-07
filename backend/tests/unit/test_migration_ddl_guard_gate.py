# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The DDL guard gate, proved in both directions.

A gate that only ever refuses is as useless as one that only ever passes, and
both failure modes look identical from the outside: a green line in a log. So
every rule here is asserted twice, once on input the gate must refuse and once
on the guarded form of the same input that it must accept.

The regression that motivated the widening has its own test. The predecessor
gate matched ``op.create_table`` with a matcher that required the receiver to be
the name ``op``, so

    with op.batch_alter_table("oe_changeorders_order") as batch:
        batch.add_column(...)

was invisible to it: wrong verb and wrong receiver. That is the exact shape of
the revision whose replay was measured dying with DuplicateColumn on
``rejected_by``. ``test_a_batch_receiver_is_not_invisible`` is that shape.

Which path this gate protects, stated so nobody has to infer it. Nothing in
``backend/app`` runs ``alembic upgrade``: it reads ``ScriptDirectory`` to learn
the head and configures a ``MigrationContext`` to stamp, and that is all. The
schema moves at boot through the auto-migrator plus ``create_all``, which
``app/main.py`` calls a decision rather than an oversight. So the DuplicateColumn
is reachable by ``make migrate`` and by an operator typing ``alembic upgrade
head``, which ``postgres_migrator.py`` and ``main.py`` both name as the fallback
when the boot heal cannot do the work. It is the operator path, not the product
path, and a release note should say so.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).resolve().parents[3] / "scripts" / "check_migration_ddl_guarded.py"
_spec = importlib.util.spec_from_file_location("check_migration_ddl_guarded", _GATE)
assert _spec and _spec.loader, f"gate script not found at {_GATE}"
gate = importlib.util.module_from_spec(_spec)
sys.modules["check_migration_ddl_guarded"] = gate
_spec.loader.exec_module(gate)


_HEADER = '"""A revision."""\nimport sqlalchemy as sa\nfrom alembic import op\n\n'


def _refused(source: str) -> bool:
    """Would the gate report this revision as unguarded?"""
    result = gate.scan([("v_test.py", _HEADER + source)])
    return [name for name, _ in result.unguarded] == ["v_test.py"]


def _sees_ddl(source: str) -> bool:
    return gate.scan([("v_test.py", _HEADER + source)]).with_ddl == 1


# --------------------------------------------------------------------------
# Red and green, one pair per verb the tree actually uses.
# --------------------------------------------------------------------------

_UNGUARDED = {
    "add_column": 'def upgrade():\n    op.add_column("oe_t", sa.Column("c", sa.String()))\n',
    "create_table": 'def upgrade():\n    op.create_table("oe_t", sa.Column("id", sa.String()))\n',
    "create_index": 'def upgrade():\n    op.create_index("ix_t_c", "oe_t", ["c"])\n',
    "create_unique_constraint": 'def upgrade():\n    op.create_unique_constraint("uq_t", "oe_t", ["c"])\n',
    "create_foreign_key": 'def upgrade():\n    op.create_foreign_key("fk_t", "oe_t", "oe_o", ["c"], ["id"])\n',
    "create_check_constraint": 'def upgrade():\n    op.create_check_constraint("ck_t", "oe_t", "c > 0")\n',
    "create_primary_key": 'def upgrade():\n    op.create_primary_key("pk_t", "oe_t", ["id"])\n',
}

_PROBE = (
    "def upgrade():\n"
    "    inspector = sa.inspect(op.get_bind())\n"
    '    if "oe_t" not in inspector.get_table_names():\n'
    "        return\n"
)


@pytest.mark.parametrize("verb", sorted(_UNGUARDED))
def test_an_unguarded_verb_is_refused(verb: str) -> None:
    assert _refused(_UNGUARDED[verb]), f"{verb} without any database probe must be refused"


@pytest.mark.parametrize("verb", sorted(_UNGUARDED))
def test_the_guarded_form_of_the_same_verb_is_accepted(verb: str) -> None:
    """The other direction. Same statement, now behind a probe."""
    body = _UNGUARDED[verb].split("\n", 1)[1]
    guarded = _PROBE + body
    assert _sees_ddl(guarded), f"{verb} must still be recognised as additive DDL when guarded"
    assert not _refused(guarded), f"{verb} behind an inspector probe must be accepted"


# --------------------------------------------------------------------------
# The regression the widening exists for.
# --------------------------------------------------------------------------


def test_a_batch_receiver_is_not_invisible() -> None:
    """The literal shape of 24f9595e16d0, which the predecessor gate could not see.

    The old matcher required ``node.func.value.id == "op"``. Here the receiver is
    ``batch``, so that matcher returned False and the revision passed a gate
    whose whole purpose was to stop it.
    """
    source = (
        "def upgrade():\n"
        '    with op.batch_alter_table("oe_changeorders_order") as batch:\n'
        '        batch.add_column(sa.Column("rejected_by", sa.String(length=36), nullable=True))\n'
    )
    assert _sees_ddl(source), "a batch receiver still performs additive DDL"
    assert _refused(source)


def test_a_guarded_batch_receiver_is_accepted() -> None:
    source = (
        "def upgrade():\n"
        "    inspector = sa.inspect(op.get_bind())\n"
        '    have = {c["name"] for c in inspector.get_columns("oe_changeorders_order")}\n'
        '    with op.batch_alter_table("oe_changeorders_order") as batch:\n'
        '        if "rejected_by" not in have:\n'
        '            batch.add_column(sa.Column("rejected_by", sa.String(length=36)))\n'
    )
    assert _sees_ddl(source)
    assert not _refused(source)


# --------------------------------------------------------------------------
# Raw SQL, which fails the same way a verb does.
# --------------------------------------------------------------------------


def test_raw_sql_that_creates_an_index_is_refused() -> None:
    source = 'def upgrade():\n    op.execute("CREATE INDEX ix_t_c ON oe_t (c)")\n'
    assert _sees_ddl(source)
    assert _refused(source)


def test_raw_sql_saying_if_not_exists_is_accepted() -> None:
    source = 'def upgrade():\n    op.execute("CREATE INDEX IF NOT EXISTS ix_t_c ON oe_t (c)")\n'
    assert _sees_ddl(source)
    assert not _refused(source)


def test_raw_sql_that_adds_a_constraint_is_refused() -> None:
    source = 'def upgrade():\n    op.execute("ALTER TABLE oe_t ADD CONSTRAINT ck_t CHECK (c > 0)")\n'
    assert _refused(source)


# --------------------------------------------------------------------------
# What the gate must NOT flag.
# --------------------------------------------------------------------------


def test_a_revision_that_only_drops_is_not_this_gates_business() -> None:
    """Dropping does not collide with an already-current schema."""
    source = 'def upgrade():\n    op.drop_column("oe_t", "c")\n    op.drop_index("ix_t_c")\n'
    assert not _sees_ddl(source)
    assert not _refused(source)


def test_a_docstring_mentioning_create_table_is_not_a_call() -> None:
    """Why this is an AST and not a grep: grepping counted nine such revisions."""
    source = 'def upgrade():\n    """Superseded, this used to call op.create_table on oe_t."""\n    pass\n'
    assert not _sees_ddl(source)


# --------------------------------------------------------------------------
# The population, which is the part that cannot be allowed to shrink quietly.
# --------------------------------------------------------------------------


def test_every_examined_file_lands_in_exactly_one_bucket() -> None:
    entries = [
        ("a.py", _HEADER + _UNGUARDED["add_column"]),
        ("b.py", _HEADER + _PROBE + '    op.create_table("oe_t")\n'),
        ("c.py", _HEADER + "def upgrade():\n    pass\n"),
        ("d.py", "def upgrade(:\n"),
    ]
    result = gate.scan(entries)

    assert result.examined == 4
    assert result.with_ddl == 2
    assert result.without_ddl == 1
    assert len(result.unparseable) == 1
    assert result.accounted == result.examined


def test_an_unparseable_revision_is_a_failure_not_a_smaller_denominator() -> None:
    """It must not vanish. A file that cannot be parsed cannot be cleared."""
    result = gate.scan([("broken.py", "def upgrade(:\n")])

    assert result.examined == 1
    assert result.with_ddl == 0
    assert len(result.unparseable) == 1
    assert result.accounted == 1


def test_the_gate_examines_every_revision_file_on_disk() -> None:
    """The assertion the population line exists for, over the real tree."""
    entries = gate.read_versions()
    result = gate.scan(entries)
    on_disk = len(list(gate.VERSIONS.glob("*.py")))

    assert result.examined == on_disk, f"scanned {result.examined} of {on_disk} revision files"
    assert result.accounted == result.examined, (
        f"{result.with_ddl} + {result.without_ddl} + {len(result.unparseable)} "
        f"!= {result.examined}: a revision left the scan without a verdict"
    )
    assert result.unparseable == [], f"unparseable revisions: {result.unparseable}"
    assert on_disk >= gate.MIN_EXPECTED_REVISIONS, (
        f"only {on_disk} revisions found, so this assertion is not about the tree"
    )


def test_no_revision_in_the_tree_is_unguarded() -> None:
    """The whole point, over the tree that ships.

    Not pinned to a count and not written against the exemption list, so that a
    revision gaining a guard turns this greener rather than redder.
    """
    result = gate.scan(gate.read_versions())
    unguarded = [name for name, _ in result.unguarded]

    assert unguarded == [], f"unguarded revisions: {unguarded}"


def test_the_exemption_list_is_empty() -> None:
    """Green because the tree is clean, not because anything is excused.

    This is the assertion that keeps the allowlist from becoming the easy answer
    to a red gate. Adding a name here has to be a deliberate act that fails this
    test and makes someone justify it, rather than a quiet edit nobody sees.
    """
    assert gate.KNOWN_UNGUARDED == {}, f"revisions excused rather than guarded: {sorted(gate.KNOWN_UNGUARDED)}"


def test_the_exemption_list_cannot_rot() -> None:
    """An exemption that stopped describing the tree is itself a failure.

    Without this, a name left behind after its revision was fixed or deleted
    becomes a permanent hole that nothing ever reports.
    """
    entries = gate.read_versions()
    result = gate.scan(entries)

    assert gate.stale_exemptions(entries, result) == []


def test_a_stale_exemption_is_reported() -> None:
    """The other direction: prove the rot check can go red.

    Driven through an injected list rather than the real one, which is empty. A
    rot check exercised only when the list has entries stops being exercised the
    moment the list is cleaned out, which is when it starts to matter again.
    """
    known = {"v9002_was_fixed.py": "guarded since"}
    entries = [("v9002_was_fixed.py", _HEADER + _PROBE + '    op.add_column("oe_t", sa.Column("c", sa.String()))\n')]
    result = gate.scan(entries)

    stale = gate.stale_exemptions(entries, result, known)

    assert len(stale) == 1
    assert stale[0].startswith("v9002_was_fixed.py")
    assert "guarded now" in stale[0]


def test_a_missing_exemption_is_reported() -> None:
    known = {"v9003_deleted.py": "no longer present"}

    stale = gate.stale_exemptions([], gate.scan([]), known)

    assert len(stale) == 1
    assert "no such revision" in stale[0]


def test_an_exemption_that_still_describes_the_tree_is_not_reported() -> None:
    """The green direction for the rot check, so it is not a one-way alarm."""
    known = {"v9004_still_bad.py": "still unguarded"}
    entries = [("v9004_still_bad.py", _HEADER + _UNGUARDED["add_column"])]
    result = gate.scan(entries)

    assert gate.stale_exemptions(entries, result, known) == []
