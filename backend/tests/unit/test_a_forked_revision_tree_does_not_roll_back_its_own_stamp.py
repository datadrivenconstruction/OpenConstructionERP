"""A stamp that succeeded must not be undone by the call that reports it.

``stamp_head_if_unstamped`` writes a row per head and then names what it wrote.
Naming it with ``ScriptDirectory.get_current_head`` was wrong for a tree with
more than one head: that method raises ``CommandError`` by design, and it raises
after the rows are already written. The caller in ``app/main.py`` runs the whole
thing inside ``async with engine.begin()``, so the exception rolls the stamp
back and the boot logs "Alembic head stamp skipped (non-fatal)" over a stamp
that had in fact worked.

The cost is not the missing log line, and it takes two boots rather than one.
On the first boot of an install created while a fork is out, the database is
blank when ``app/main.py`` asks
:func:`database_is_populated_but_unstamped`, so the answer is False and the
stamp is attempted - and rolled back. On the SECOND boot the same database
holds the ``oe_*`` tables ``create_all`` built and still records no revision,
which is exactly that cohort, and the boot then refuses to stamp it for the
life of the install. So one forked release turns into databases the boot path
can never stamp again, and ``/api/health`` answers ``alembic_head_matches:
null`` on every one of them, which does not degrade.

The tree ships with one head and a gate keeps it that way
(``scripts/check_migration_heads.py``, Repo hygiene). These tests are about what
happens if one ever gets past it.
"""

from __future__ import annotations

import pathlib

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory

from app.core.alembic_version_table import stamp_head_if_unstamped

_REVISION = '''"""{rid}"""
revision = "{rid}"
down_revision = {down}
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
'''


def _script_dir(root: pathlib.Path, revisions: dict[str, str | None]) -> ScriptDirectory:
    """Build a real ScriptDirectory from ``{revision id: parent id}``.

    A real one rather than a stub: ``MigrationContext.stamp`` walks alembic's
    own revision map, and a hand-rolled object that satisfied today's call would
    stop resembling the thing under test the moment alembic changed.
    """
    from alembic.config import Config

    (root / "env.py").write_text("", encoding="utf-8")
    (root / "script.py.mako").write_text("", encoding="utf-8")
    versions = root / "versions"
    versions.mkdir()
    for rid, down in revisions.items():
        parent = "None" if down is None else f'"{down}"'
        (versions / f"{rid}.py").write_text(_REVISION.format(rid=rid, down=parent), encoding="utf-8")

    config = Config()
    config.set_main_option("script_location", str(root))
    return ScriptDirectory.from_config(config)


def _use(monkeypatch: pytest.MonkeyPatch, script: ScriptDirectory) -> None:
    """Make ``stamp_head_if_unstamped`` read this tree instead of the shipped one."""
    monkeypatch.setattr(ScriptDirectory, "from_config", classmethod(lambda cls, config: script))


def _blank() -> sa.Connection:
    return sa.create_engine("sqlite://").connect()


def _stamped_rows(conn: sa.Connection) -> list[str]:
    return sorted(conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all())


def test_alembic_still_refuses_to_name_a_single_head_on_a_forked_tree(tmp_path: pathlib.Path) -> None:
    """Pin the mechanism the fix exists for, so the guard cannot go quietly moot.

    Without this, an alembic release that stopped raising here would leave the
    two tests below passing for a reason unrelated to what they check, and the
    guard could be deleted on the evidence of a green suite.
    """
    script = _script_dir(tmp_path, {"r_root": None, "r_fork_a": "r_root", "r_fork_b": "r_root"})

    assert sorted(script.get_heads()) == ["r_fork_a", "r_fork_b"]
    with pytest.raises(Exception, match="multiple heads"):
        script.get_current_head()


def test_a_forked_tree_keeps_the_rows_it_stamped(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both heads are written, and the call returns rather than raising over them."""
    script = _script_dir(tmp_path, {"r_root": None, "r_fork_a": "r_root", "r_fork_b": "r_root"})
    _use(monkeypatch, script)

    with _blank() as conn:
        stamped = stamp_head_if_unstamped(conn)

        assert stamped is not None, "a stamp that wrote rows must not report None"
        # Named, not merely survived: the caller logs this string, and a boot
        # that says "stamped to head r_fork_a" on a forked tree is the half-truth
        # that hides the fork from whoever reads the log.
        assert "r_fork_a" in stamped
        assert "r_fork_b" in stamped
        assert _stamped_rows(conn) == ["r_fork_a", "r_fork_b"]


def test_the_ordinary_single_head_answer_is_unchanged(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The control. Every shipped install takes this path, and it must read identically.

    A fix for the forked case that also reworded the answer for the 99.9% case
    would be a regression wearing a repair's clothes: the return value reaches a
    log line operators read, and ``main.py`` tests it for truthiness.
    """
    script = _script_dir(tmp_path, {"r_root": None, "r_only_head": "r_root"})
    _use(monkeypatch, script)

    with _blank() as conn:
        stamped = stamp_head_if_unstamped(conn)

        assert stamped == "r_only_head"
        assert _stamped_rows(conn) == ["r_only_head"]


def test_a_tree_with_no_revisions_still_answers_none(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented contract for an empty tree, which ``", ".join`` would have made ``""``.

    ``main.py`` gates its log line on ``if stamped:``, so an empty string behaves
    the same there - but the annotation says ``str | None`` and a caller added
    later would be reading a value the docstring does not describe.
    """
    script = _script_dir(tmp_path, {})
    _use(monkeypatch, script)

    with _blank() as conn:
        assert stamp_head_if_unstamped(conn) is None
