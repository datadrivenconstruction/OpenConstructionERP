# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The migration chain must have exactly one head.

A second head makes ``alembic upgrade head`` refuse to run at all, for
everyone, with "Multiple head revisions are present". It is not a degraded
mode: nobody can upgrade until it is repaired. It happened on main when a
module migration named a parent that a merge revision had already folded into
the mainline hundreds of revisions earlier, and it went unnoticed because our
own production deploy is ``create_all`` plus ``alembic stamp head`` and never
walks the chain. Only self-hosters upgrading in place would have hit it.

The revisions are read with ``ast`` rather than imported. Importing them means
importing ``app.database``, which requires a PostgreSQL URL and would make
this a slow test that needs a database to answer a question that is purely
about text on disk. It would also mean an unrelated import error anywhere in
the 300-plus revision files silently disables the check, which is exactly the
failure mode a guard must not have.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _literal(node: ast.AST) -> object | None:
    """Best-effort constant value, or None when it is not a literal."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


def _parents(value: object) -> tuple[str, ...]:
    """Normalise a ``down_revision`` into the revisions it depends on.

    It is a string for an ordinary revision, a tuple or list for a merge, and
    None for a base. Anything else is a revision we cannot reason about, and
    we would rather see that as a parse failure than pretend it has no parent.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)) and all(isinstance(v, str) for v in value):
        return tuple(value)
    msg = f"unreadable down_revision: {value!r}"
    raise TypeError(msg)


def _read_chain() -> tuple[dict[str, tuple[str, ...]], list[Path]]:
    """Map every revision id to its parents, without executing any of them."""
    chain: dict[str, tuple[str, ...]] = {}
    unreadable: list[Path] = []
    for path in sorted(VERSIONS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found: dict[str, object] = {}
        for node in tree.body:
            targets = [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    if node.value is not None:
                        found[target.id] = _literal(node.value)
        rev = found.get("revision")
        if not isinstance(rev, str):
            unreadable.append(path)
            continue
        chain[rev] = _parents(found.get("down_revision"))
    return chain, unreadable


@pytest.fixture(scope="module")
def chain() -> dict[str, tuple[str, ...]]:
    parsed, unreadable = _read_chain()
    assert not unreadable, "revisions whose id could not be read:\n  " + "\n  ".join(str(p) for p in unreadable)
    return parsed


def test_the_versions_directory_was_actually_found(chain: dict[str, tuple[str, ...]]) -> None:
    """A wrong path would make every assertion below vacuously true."""
    assert len(chain) > 250, f"only {len(chain)} revisions parsed from {VERSIONS}"


def test_exactly_one_head(chain: dict[str, tuple[str, ...]]) -> None:
    """A head is a revision nobody names as a parent."""
    claimed = {parent for parents in chain.values() for parent in parents}
    heads = sorted(set(chain) - claimed)
    assert len(heads) == 1, (
        "alembic upgrade head is broken for every self-hosted upgrade. "
        f"Heads: {heads}. Add a merge revision naming all of them as parents. "
        "Do not repoint an existing revision's down_revision: a database already "
        "stamped at it would then treat everything between the old parent and the "
        "new one as applied, and skip those migrations in silence."
    )


def test_every_named_parent_exists(chain: dict[str, tuple[str, ...]]) -> None:
    """A parent nobody defines breaks the walk just as badly as a second head."""
    missing = sorted(
        f"{rev} -> {parent}" for rev, parents in chain.items() for parent in parents if parent not in chain
    )
    assert not missing, "revisions naming a parent that does not exist:\n  " + "\n  ".join(missing)


def test_exactly_one_base(chain: dict[str, tuple[str, ...]]) -> None:
    """More than one base means a whole subtree hangs off nothing."""
    bases = sorted(rev for rev, parents in chain.items() if not parents)
    assert len(bases) == 1, f"expected a single base revision, found: {bases}"
