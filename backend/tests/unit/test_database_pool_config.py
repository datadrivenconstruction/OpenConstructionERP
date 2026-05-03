"""Regression test: pool_size/max_overflow honoured for SQLite too.

Before v2.6.40, ``create_engine_from_settings`` skipped pool sizing on the
SQLite branch (``# SQLite doesn't support pool_size/max_overflow``).
That comment was wrong: ``aiosqlite`` does honour pool sizing, and the
default ``AsyncAdaptedQueuePool`` of size=5+overflow=10 was exhausting
under parallel load (parallel QA crawlers, multi-tab clients, scheduled
jobs running concurrently).

This test verifies — by source inspection, not by spinning up an engine —
that the new code path applies pool kwargs unconditionally for both
SQLite and Postgres URLs.
"""

from __future__ import annotations

import ast
from pathlib import Path

DATABASE_PY = (
    Path(__file__).resolve().parent.parent.parent
    / "app" / "database.py"
)


def _parse_create_engine() -> ast.FunctionDef:
    """Return the AST of ``create_engine_from_settings``."""
    tree = ast.parse(DATABASE_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "create_engine_from_settings":
            return node
    raise AssertionError("create_engine_from_settings not found in database.py")


def test_pool_size_assigned_outside_sqlite_branch() -> None:
    """``kwargs['pool_size']`` must be assigned at function scope, NOT
    inside an ``else`` branch of the ``if _is_sqlite(url):`` check.

    The pre-fix code looked like::

        if _is_sqlite(url):
            kwargs["connect_args"] = {...}
        else:
            kwargs["pool_size"] = ...
            kwargs["max_overflow"] = ...

    The fix moved both pool assignments out of the else branch so they
    run for both engines.
    """
    func = _parse_create_engine()

    # Find direct (top-level inside func) assignments to kwargs["pool_size"].
    pool_size_assigned_at_top_level = False
    max_overflow_assigned_at_top_level = False

    for stmt in func.body:
        if not isinstance(stmt, ast.Assign):
            continue
        for target in stmt.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "kwargs"
                and isinstance(target.slice, ast.Constant)
            ):
                if target.slice.value == "pool_size":
                    pool_size_assigned_at_top_level = True
                if target.slice.value == "max_overflow":
                    max_overflow_assigned_at_top_level = True

    assert pool_size_assigned_at_top_level, (
        "kwargs['pool_size'] must be assigned at the top level of "
        "create_engine_from_settings (not inside an else branch). "
        "Otherwise SQLite gets the SQLAlchemy default pool of size=5+10 "
        "which exhausts under parallel load."
    )
    assert max_overflow_assigned_at_top_level, (
        "kwargs['max_overflow'] must be assigned at the top level too."
    )


def test_no_else_branch_with_pool_kwargs() -> None:
    """The ``if _is_sqlite(url):`` block must NOT contain a sibling ``else``
    that exclusively owns ``pool_size``/``max_overflow``. That structure was
    the regression we're guarding against."""
    func = _parse_create_engine()

    for stmt in func.body:
        if not isinstance(stmt, ast.If):
            continue
        # Look for the _is_sqlite(url) test
        test = stmt.test
        if not (
            isinstance(test, ast.Call)
            and isinstance(test.func, ast.Name)
            and test.func.id == "_is_sqlite"
        ):
            continue

        # The else branch must NOT assign pool_size/max_overflow.
        for else_stmt in stmt.orelse:
            if not isinstance(else_stmt, ast.Assign):
                continue
            for target in else_stmt.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "kwargs"
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value in {"pool_size", "max_overflow"}
                ):
                    raise AssertionError(
                        f"kwargs['{target.slice.value}'] is assigned inside "
                        "the `else` of `if _is_sqlite(url):`. This is the "
                        "exact regression v2.6.40 fixed — SQLite would skip "
                        "pool sizing and exhaust the default pool under "
                        "parallel load. Move the assignment to the top "
                        "level of create_engine_from_settings."
                    )


def test_database_settings_have_pool_fields() -> None:
    """``Settings`` must expose ``database_pool_size`` and
    ``database_max_overflow`` attributes the engine factory reads from."""
    from app.config import Settings

    assert hasattr(Settings, "model_fields"), "Settings must be a Pydantic v2 model"
    fields = Settings.model_fields
    assert "database_pool_size" in fields, (
        "Settings.database_pool_size missing — required by "
        "create_engine_from_settings."
    )
    assert "database_max_overflow" in fields, (
        "Settings.database_max_overflow missing."
    )
