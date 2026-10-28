# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every identifier a migration names must fit PostgreSQL's 63-character limit.

PostgreSQL truncates identifiers at ``NAMEDATALEN - 1`` = 63 characters, and
SQLAlchemy refuses to emit a name it knows would be silently cut, raising
``IdentifierError`` before any DDL is sent. Because PostgreSQL runs DDL inside a
transaction, that failure rolls back the entire ``alembic upgrade head``, so a
site upgrading across several releases receives *none* of the revisions rather
than stopping at the offending one.

That is how a 65-character foreign key name in ``v3280_contract_templates``
made an entire release unmigratable on PostgreSQL while passing every test we
had. SQLite has no such limit, so the revision applied cleanly wherever the
suite happened to run, and nothing in the tree compared a name against 63.

This guard is deliberately a string scan rather than a database round trip. The
point is to catch the name *before* release without requiring a PostgreSQL
service in the matrix, so it stays cheap enough to attach anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# PostgreSQL's NAMEDATALEN is 64, and the limit on a usable identifier is 63.
# MySQL is stricter still at 64 for most objects but 63 is the binding one for
# the databases this project supports.
MAX_IDENTIFIER_LENGTH = 63

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"

# A bare snake_case token. Anything containing a space, a dot, a percent sign or
# an upper-case letter is SQL text, a format template or a message rather than a
# name we are asking the database to store, and matching those would produce
# noise that trains people to ignore this test.
_IDENTIFIER_RE = re.compile(r"""["']([a-z_][a-z0-9_]*)["']""")


def _identifiers_in(path: Path) -> list[tuple[int, str]]:
    """Return every (line number, identifier-shaped literal) in one migration."""
    text = path.read_text(encoding="utf-8", errors="replace")
    found: list[tuple[int, str]] = []
    for match in _IDENTIFIER_RE.finditer(text):
        token = match.group(1)
        if len(token) > MAX_IDENTIFIER_LENGTH:
            found.append((text[: match.start()].count("\n") + 1, token))
    return found


def test_versions_directory_is_where_we_think_it_is() -> None:
    """A scan of nothing passes. Fail loudly instead if the path moves.

    The migrations live outside the test tree, so this suite is one directory
    rename away from silently scanning zero files and reporting success for the
    rest of the project's life.
    """
    assert VERSIONS_DIR.is_dir(), f"migration directory not found at {VERSIONS_DIR}"
    revisions = list(VERSIONS_DIR.glob("*.py"))
    assert len(revisions) > 50, (
        f"only {len(revisions)} revisions found under {VERSIONS_DIR}; this scan is meant to cover the whole history"
    )


def test_no_migration_names_an_identifier_postgres_would_truncate() -> None:
    offenders: list[str] = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        for line, token in _identifiers_in(path):
            offenders.append(f"{path.name}:{line} is {len(token)} chars: {token}")

    assert not offenders, (
        f"{len(offenders)} identifier(s) exceed PostgreSQL's "
        f"{MAX_IDENTIFIER_LENGTH}-character limit. PostgreSQL will reject the "
        "revision and roll back the whole upgrade, so a site gets none of the "
        "pending revisions. Shorten the name, scoping it to its own table "
        "without repeating the referenced table.\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    ("name", "should_flag"),
    [
        # The real one, from v3280. 65 characters.
        ("fk_oe_contracts_template_clause_template_id_oe_contracts_template", True),
        # Its replacement, and the two siblings it now reads consistently with.
        ("fk_oe_contracts_template_clause_template", False),
        ("pk_oe_contracts_template_clause", False),
        ("uq_oe_contracts_template_clause_number", False),
        # Boundary: 63 is allowed, 64 is not.
        ("a" * 63, False),
        ("a" * 64, True),
    ],
)
def test_the_detector_flags_what_it_is_meant_to(name: str, should_flag: bool, tmp_path: Path) -> None:
    """Drive the scanner over a synthetic revision.

    Without this, the suite above is a test that has only ever been observed
    passing, and a scanner that flags nothing is indistinguishable from one
    that was never written. This one has been seen to go red.
    """
    revision = tmp_path / "vXXXX_synthetic.py"
    revision.write_text(f'sa.ForeignKeyConstraint(["a"], ["b.id"], name="{name}")\n', encoding="utf-8")
    assert bool(_identifiers_in(revision)) is should_flag


def test_the_detector_ignores_prose_and_sql_text(tmp_path: Path) -> None:
    """Long strings that are not identifiers must not be reported.

    A guard that cries wolf on docstrings and raw SQL gets muted, and a muted
    guard is the same as no guard.
    """
    revision = tmp_path / "vYYYY_synthetic.py"
    revision.write_text(
        "op.execute(\"UPDATE oe_contracts_template SET status = 'draft' WHERE status IS NULL\")\n"
        '"""A module docstring that runs well past sixty-three characters without naming anything."""\n'
        'log.info("Backfilling the contract template lineage identifiers for existing rows")\n',
        encoding="utf-8",
    )
    assert _identifiers_in(revision) == []
