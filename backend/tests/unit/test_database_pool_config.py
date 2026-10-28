"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression test: pool_size/max_overflow are applied unconditionally.

``create_engine_from_settings`` must size the connection pool from
``Settings.database_pool_size`` / ``database_max_overflow``. An earlier version
skipped pool sizing on a now-removed SQLite branch, so the engine fell back to
the SQLAlchemy default pool of size=5+overflow=10 and exhausted under parallel
load (QA crawlers, multi-tab clients, scheduled jobs running concurrently). The
app is PostgreSQL-only now and the assignments live at function scope; this test
guards by source inspection that they are not nested behind a dialect branch.
"""

from __future__ import annotations

import ast
from pathlib import Path

DATABASE_PY = Path(__file__).resolve().parent.parent.parent / "app" / "database.py"


def _parse_create_engine() -> ast.FunctionDef:
    """Return the AST of ``create_engine_from_settings``."""
    tree = ast.parse(DATABASE_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "create_engine_from_settings":
            return node
    raise AssertionError("create_engine_from_settings not found in database.py")


def test_pool_kwargs_assigned_at_function_scope() -> None:
    """``kwargs['pool_size']`` / ``['max_overflow']`` must be assigned at the
    top level of ``create_engine_from_settings`` so every engine gets them,
    never gated behind a dialect ``if``/``else``.
    """
    func = _parse_create_engine()

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
        "create_engine_from_settings, never inside a dialect branch, so the "
        "pool never falls back to the SQLAlchemy default of size=5+10."
    )
    assert max_overflow_assigned_at_top_level, "kwargs['max_overflow'] must be assigned at the top level too."


def test_database_settings_have_pool_fields() -> None:
    """``Settings`` must expose ``database_pool_size`` and
    ``database_max_overflow`` attributes the engine factory reads from."""
    from app.config import Settings

    assert hasattr(Settings, "model_fields"), "Settings must be a Pydantic v2 model"
    fields = Settings.model_fields
    assert "database_pool_size" in fields, (
        "Settings.database_pool_size missing - required by create_engine_from_settings."
    )
    assert "database_max_overflow" in fields, "Settings.database_max_overflow missing."
