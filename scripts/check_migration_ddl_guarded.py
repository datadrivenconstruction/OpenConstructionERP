#!/usr/bin/env python3
# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Refuse a migration that adds schema without first asking whether it is there.

Why this has to be a gate rather than a convention
--------------------------------------------------
The boot path builds the schema with ``Base.metadata.create_all`` before
anything reads ``alembic_version``. That is deliberate and documented in
``app/main.py``: the baseline revision is a no-op, the quickstart entrypoint
never runs ``alembic upgrade head``, and without ``create_all`` a fresh volume
comes up with no tables at all.

The consequence is that on every install this application has ever started, the
whole of the model metadata already exists by the time an operator runs
``alembic upgrade head`` by hand. Unguarded additive DDL then raises. PostgreSQL
runs DDL inside a transaction, so the failure rolls back the entire run rather
than one revision, ``alembic_version`` does not move, and every later revision is
skipped along with the data backfills inside them. An operator who is twenty-six
revisions behind can never catch up, and each attempt fails at the same object.

That is not hypothetical, in either of its two observed forms. It was reported
from an installation carried across four releases, stamped at ``v3258`` while
head was ``v3284``, failing on ``oe_eac_block_graph`` every time. And it was
reproduced directly against a database this application had booted: replaying
the chain over it died on

    (psycopg2.errors.DuplicateColumn) column "rejected_by" of relation
    "oe_changeorders_order" already exists

Why the verb list is what it is
-------------------------------
The predecessor of this gate checked ``op.create_table`` alone, and it checked it
with a matcher that required the receiver to be literally ``op``. Both halves of
that were too narrow, and the second one was what let the ``rejected_by`` failure
through: the revision that caused it writes

    with op.batch_alter_table("oe_changeorders_order") as batch:
        batch.add_column(...)

so the call is ``batch.add_column``, the receiver is not ``op``, and the gate saw
nothing at all. Sixty revisions in this tree use ``batch_alter_table``. The
matcher here is therefore receiver-blind: it asks what is being called, not what
it is being called on.

The verbs are the ones the tree actually uses, counted rather than imagined.
Every revision file was parsed and every attribute call collected:

    create_index               217 revisions
    create_table               173
    add_column                 151
    create_unique_constraint     9
    create_foreign_key           8
    execute(raw DDL)             7
    create_check_constraint      2

``create_primary_key`` is in the list with zero current users. That is on
purpose and is not a scan bug: a verb nobody uses yet is precisely the one that
ships unguarded the first time somebody reaches for it, and adding it costs
nothing today.

Raw SQL counts as DDL. Eleven ``op.execute`` sites in this tree issue CREATE
TABLE, CREATE INDEX, ADD COLUMN or ADD CONSTRAINT as text, and text fails the
same way a verb does. Most already write ``IF NOT EXISTS``, which is why that
string is one of the guard markers.

Deliberately absent: ``metadata.create_all`` (one revision), which defaults to
``checkfirst=True`` and is therefore guarded by construction, and every
``drop_*`` and ``alter_column``, which are not what collides with an
already-current schema.

What counts as guarded
----------------------
The revision must consult the database before it acts: any of the inspector
probes below, or ``IF NOT EXISTS`` in raw SQL. The check is deliberately
shallow. It asks whether the revision looks at the database at all, not whether
the guard is correctly placed around every statement, because a precise dataflow
answer would cost far more than it buys and the shallow question already catches
the whole observed failure mode. A per-object rule was measured against this
tree first and produced fifty reds, nearly all of them an index created
alongside the table it belongs to and already covered by that table's own guard.

Read with an AST rather than by grepping. ``op.create_table`` appears inside
docstrings in this tree, and a docstring is not a call: grepping for the text
counted nine revisions that create nothing.

The population is printed beside the verdict, and the count of files examined is
asserted against an independent count of the files on disk. A revision that
falls out of the scan has to become a failure rather than a smaller denominator,
because a shrinking denominator is invisible: the gate still says zero problems.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "backend" / "alembic" / "versions"

# A tree this size cannot shrink to nothing by accident. If it looks like it
# has, the glob is broken and the verdict is meaningless.
MIN_EXPECTED_REVISIONS = 300

# Verbs that add schema. Receiver-blind: op.add_column and batch_op.add_column
# are the same hazard and only one of them was ever visible to the old matcher.
ADDITIVE_VERBS = (
    "create_table",
    "add_column",
    "create_index",
    "create_unique_constraint",
    "create_foreign_key",
    "create_check_constraint",
    "create_primary_key",
)

# Raw DDL handed to op.execute as text.
RAW_DDL = re.compile(
    r"\b(?:CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)|ADD\s+(?:COLUMN|CONSTRAINT))\b",
    re.IGNORECASE,
)
RAW_LABEL = "execute(raw DDL)"

# Any one of these means the revision asked the database before it acted.
GUARD_MARKERS = (
    "get_table_names",
    "has_table",
    "get_columns",
    "get_indexes",
    "get_unique_constraints",
    "get_foreign_keys",
    "get_check_constraints",
    "get_pk_constraint",
    "IF NOT EXISTS",
)

# Revisions that are unguarded, are known to be unguarded, and have shipped.
#
# EMPTY, AND THAT IS THE POINT. The gate is green because the tree is clean, not
# because anything is excused. It briefly held the two revisions this gate was
# widened to catch, 24f9595e16d0 and 85f7cfa6eecf; both were then guarded and the
# replay that used to die on DuplicateColumn was measured completing, so they
# came off the list rather than living on it.
#
# The mechanism stays here so the next person who needs it finds it instead of
# inventing a second one. Add a filename mapped to a one-line reason, and only
# for a revision that has already shipped, because editing a shipped migration is
# a decision about the product rather than a cleanup. A revision that has not
# shipped gets a guard, not an entry.
#
# The list is self-policing: an entry whose file has gained a guard, has stopped
# doing additive DDL, or has disappeared is itself reported as a failure, so it
# cannot rot into a permanent hole. Prefer emptying it to growing it.
KNOWN_UNGUARDED: dict[str, str] = {}


@dataclass
class Scan:
    """What the gate saw, in disjoint parts that must add back up."""

    examined: int = 0
    with_ddl: int = 0
    without_ddl: int = 0
    unparseable: list[str] = field(default_factory=list)
    unguarded: list[tuple[str, list[str]]] = field(default_factory=list)
    verb_users: dict[str, int] = field(default_factory=dict)

    @property
    def accounted(self) -> int:
        """Every examined file lands in exactly one of three buckets."""
        return self.with_ddl + self.without_ddl + len(self.unparseable)


def additive_ddl(tree: ast.Module) -> set[str]:
    """Which additive DDL does this module perform, by any receiver?

    Returns the labels found. An empty set means the revision adds no schema and
    is not this gate's business.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr in ADDITIVE_VERBS:
            found.add(node.func.attr)
        elif node.func.attr == "execute":
            # Only string literals inside the call: a variable holding SQL is
            # out of reach of an AST and out of scope for a shallow check.
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Constant)
                    and isinstance(sub.value, str)
                    and RAW_DDL.search(sub.value)
                ):
                    found.add(RAW_LABEL)
    return found


def is_guarded(source: str) -> bool:
    """Does the revision consult the database anywhere at all?"""
    return any(marker in source for marker in GUARD_MARKERS)


def scan(entries: list[tuple[str, str]]) -> Scan:
    """Scan (filename, source) pairs. The caller decides where they came from."""
    result = Scan()
    for name, source in entries:
        result.examined += 1
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            result.unparseable.append(f"{name}: {exc}")
            continue
        verbs = additive_ddl(tree)
        if not verbs:
            result.without_ddl += 1
            continue
        result.with_ddl += 1
        for verb in verbs:
            result.verb_users[verb] = result.verb_users.get(verb, 0) + 1
        if not is_guarded(source):
            result.unguarded.append((name, sorted(verbs)))
    return result


def stale_exemptions(
    entries: list[tuple[str, str]],
    result: Scan,
    known: dict[str, str] | None = None,
) -> list[str]:
    """Entries in KNOWN_UNGUARDED that no longer describe the tree.

    ``known`` is injectable so this stays testable in both directions while the
    real list is empty. A rot check that can only be exercised when the list has
    entries stops being exercised the moment the list is cleaned out, which is
    exactly when it starts to matter again.
    """
    known = KNOWN_UNGUARDED if known is None else known
    present = {name for name, _ in entries}
    still_unguarded = {name for name, _ in result.unguarded}
    stale = []
    for name in sorted(known):
        if name not in present:
            stale.append(
                f"{name}: listed as known-unguarded but no such revision exists"
            )
        elif name not in still_unguarded:
            stale.append(
                f"{name}: listed as known-unguarded but it is guarded now, drop the entry"
            )
    return stale


def read_versions() -> list[tuple[str, str]]:
    return [
        (path.name, path.read_text(encoding="utf-8"))
        for path in sorted(VERSIONS.glob("*.py"))
    ]


def main() -> int:
    if not VERSIONS.is_dir():
        print(f"No migrations directory at {VERSIONS}", file=sys.stderr)
        return 0

    entries = read_versions()
    result = scan(entries)

    # Count the disk again, independently of the list that was scanned. This is
    # the assertion the whole population line exists for: a file that entered
    # the glob and left the scan without a verdict must be a failure, not a
    # quieter denominator.
    on_disk = len(list(VERSIONS.glob("*.py")))

    print(
        f"check_migration_ddl_guarded: {result.examined} revision files examined, "
        f"{result.with_ddl} perform additive DDL "
        f"({result.with_ddl - len(result.unguarded)} ask the database first), "
        f"{result.without_ddl} perform none, {len(result.unparseable)} unparseable"
    )
    for verb, count in sorted(
        result.verb_users.items(), key=lambda kv: (-kv[1], kv[0])
    ):
        print(f"    {count:4d}  {verb}")

    failed = False

    if result.accounted != result.examined:
        print(
            f"\nPopulation does not add up: {result.with_ddl} + {result.without_ddl} + "
            f"{len(result.unparseable)} = {result.accounted}, but {result.examined} files were "
            "examined. A revision left the scan without a verdict.",
            file=sys.stderr,
        )
        failed = True

    if result.examined != on_disk:
        print(
            f"\nScanned {result.examined} revision files but {on_disk} are on disk at "
            f"{VERSIONS}. A revision fell out of the scan, so the verdict above is over the "
            "wrong population.",
            file=sys.stderr,
        )
        failed = True

    if on_disk < MIN_EXPECTED_REVISIONS:
        print(
            f"\nOnly {on_disk} revision files found, below the floor of "
            f"{MIN_EXPECTED_REVISIONS}. This tree does not shrink, so the glob is broken.",
            file=sys.stderr,
        )
        failed = True

    for line in stale_exemptions(entries, result):
        print(f"\n  STALE EXEMPTION {line}", file=sys.stderr)
        failed = True

    for line in result.unparseable:
        print(f"  UNPARSEABLE {line}", file=sys.stderr)
        failed = True

    new_unguarded = [
        (name, verbs) for name, verbs in result.unguarded if name not in KNOWN_UNGUARDED
    ]
    if new_unguarded:
        print(
            "\nThese revisions add schema without asking whether it is already there.\n"
            "The boot heal runs create_all before any operator can run alembic, so on a\n"
            "real install these raise DuplicateTable, DuplicateColumn or DuplicateObject,\n"
            "roll back the whole upgrade, and silently skip every revision that follows.\n",
            file=sys.stderr,
        )
        for name, verbs in new_unguarded:
            print(f"  {name}: {', '.join(verbs)}", file=sys.stderr)
        print(
            "\nFollow the pattern the other revisions use:\n\n"
            "    def _has_column(inspector: sa.engine.reflection.Inspector, table: str, col: str) -> bool:\n"
            '        return col in {c["name"] for c in inspector.get_columns(table)}\n\n'
            "    def upgrade() -> None:\n"
            "        bind = op.get_bind()\n"
            "        inspector = sa.inspect(bind)\n"
            '        if not _has_column(inspector, "oe_your_table", "your_column"):\n'
            "            op.add_column(...)\n\n"
            "Raw SQL may write IF NOT EXISTS instead.\n\n"
            "If you do not recognise the revision named above, it is probably not yours.\n"
            "This gate reads the versions directory on DISK, not the git index, so in a\n"
            "tree several sessions write to at once it sees another session's untracked\n"
            "work in progress. That is deliberate: an unguarded revision breaks the same\n"
            "upgrade whether or not it has been committed yet, and a gate that only looked\n"
            "at committed files would go green until the moment it was too late to matter.\n"
            "Tell whoever owns the file rather than guarding it for them.\n",
            file=sys.stderr,
        )
        failed = True

    if result.unguarded and not new_unguarded and not failed:
        print(
            f"    {len(result.unguarded)} known-unguarded revision(s) held in KNOWN_UNGUARDED, "
            "shipped and owned elsewhere"
        )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
