# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The runner is wired into startup, in the right branch and in the right order.

``tests/pg/test_data_repairs.py`` proves the runner does the right thing when it
is called. Nothing there proves that anything calls it. That gap is not a
theoretical one: the defect the whole data-repair mechanism exists to answer is
code that does nothing while every signal reports success, and a call site
deleted from ``app/main.py`` would reproduce it exactly - the module would still
import, the health field would still answer ``false`` because
``data_repairs_failed`` is only set where the pass runs, and no test would move.

Read statically off ``app/main.py`` rather than by booting a lifespan. Booting
one needs a live PostgreSQL and belongs to the PG lane; what has to be held here
is a property of the source, and three of the four assertions below are about
ORDER, which a runtime test would find harder to see than the parser does.

The three orderings, and why each matters:

* the ledger model is imported before ``create_all``. It is declared in
  ``app.core``, which the dynamic ``app.modules.*`` model loop never reaches, so
  an import that lands after ``create_all`` leaves the table absent - the
  repairs then run correctly and the record of them is lost on every install.
* the repairs run after ``create_all``, because the ledger they write to is one
  of the tables ``create_all`` builds.
* both sit inside the ``"postgresql" in settings.database_url`` branch, which is
  what makes ``data_repairs_failed`` answer ``null`` rather than ``false`` on a
  deployment that never runs them.
"""

from __future__ import annotations

import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "app" / "main.py"


def _tree() -> ast.Module:
    return ast.parse(MAIN.read_text(encoding="utf-8"), filename=str(MAIN))


def _call_linenos(tree: ast.Module, func_name: str) -> list[int]:
    """Line numbers of every call to a plain ``name(...)`` in the file."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name
    ]


def _attribute_linenos(tree: ast.Module, dotted: str) -> list[int]:
    """Line numbers of every mention of ``a.b.c``, called or merely referenced.

    Matching only ``a.b.c(...)`` would have missed the one that matters. The
    boot path spells it ``await conn.run_sync(Base.metadata.create_all)`` - the
    attribute is handed over as a value and invoked by somebody else, so there
    is no Call node with it in the callee slot. A matcher that insisted on one
    came back empty and would have reported the ordering as unverifiable rather
    than as wrong, which is the same shape of silence as the defect above.
    """
    out: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        parts: list[str] = []
        cur: ast.expr = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        if ".".join(reversed(parts)) == dotted:
            out.append(node.lineno)
    return out


def _import_linenos(tree: ast.Module, module: str, name: str) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module and any(a.name == name for a in node.names)
    ]


def _postgresql_branch_ranges(tree: ast.Module) -> list[tuple[int, int]]:
    """Line spans of every ``if ... "postgresql" ... database_url`` block."""
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_src = ast.unparse(node.test)
        if "postgresql" in test_src and "database_url" in test_src:
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


def test_startup_calls_the_data_repair_runner() -> None:
    calls = _call_linenos(_tree(), "run_data_repairs")

    assert calls, "app/main.py never calls run_data_repairs - the repairs would never execute on boot"


def test_the_repairs_run_after_create_all_builds_the_ledger_table() -> None:
    tree = _tree()
    create_all = _attribute_linenos(tree, "Base.metadata.create_all")
    calls = _call_linenos(tree, "run_data_repairs")

    assert create_all, "could not find the create_all call this ordering is relative to"
    assert min(calls) > min(create_all), "the repairs run before create_all, so the ledger table is not there yet"


def test_the_ledger_model_is_imported_before_create_all() -> None:
    """Otherwise ``create_all`` never sees the table and the record is lost silently."""
    tree = _tree()
    imports = _import_linenos(tree, "app.core", "data_repairs")
    create_all = _attribute_linenos(tree, "Base.metadata.create_all")

    assert imports, "app/main.py does not import app.core.data_repairs, so create_all cannot build its table"
    assert min(imports) < min(create_all)


def test_the_repairs_run_inside_the_postgresql_branch() -> None:
    """Which is what lets the health field answer "never ran" instead of "went fine"."""
    tree = _tree()
    spans = _postgresql_branch_ranges(tree)
    calls = _call_linenos(tree, "run_data_repairs")

    assert spans, "could not find the PostgreSQL branch in the startup sequence"
    # Without this line the assertion below is vacuously true on zero calls, and
    # "passes because there was nothing to check" is the exact failure mode the
    # whole file exists to refuse.
    assert calls, "no run_data_repairs call to locate"
    assert all(any(start <= line <= end for start, end in spans) for line in calls), (
        "a run_data_repairs call sits outside the PostgreSQL branch"
    )


def test_the_verdict_is_published_and_defaulted() -> None:
    """``data_repairs_failed`` has to be set in both places or it cannot mean three things.

    Once where the application is built (so a deployment that never runs the
    pass keeps ``None``) and once where the pass finishes (so a run writes a
    real verdict). Either one alone collapses the field to two states.
    """
    source = MAIN.read_text(encoding="utf-8")

    assert "app.state.data_repairs_failed = None" in source, "no default, so 'never ran' is unrepresentable"
    assert 'result["data_repairs_failed"]' in source, "the verdict is computed and never published"
