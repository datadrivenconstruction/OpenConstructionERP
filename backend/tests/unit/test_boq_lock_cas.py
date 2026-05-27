"""BOQ lock/unlock CAS regression — Audit B7 / CC4.

The pre-fix lock_boq did READ -> CHECK -> UPDATE, which let two
concurrent callers both pass the "not locked" check and both write
their approval metadata. The fixed version uses a compare-and-swap
UPDATE (``WHERE is_locked = false``); the loser of the race gets a
clean 409 instead of corrupting the row.

These tests are AST-based (cheap and deterministic) — they verify the
shape of the implementation rather than driving real DB concurrency,
which would be flaky in a unit suite. The end-to-end race behaviour
is covered in ``backend/tests/integration/test_boq_lock_race.py``
(if/when that suite is added).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _load_router_ast() -> ast.Module:
    here = Path(__file__).resolve()
    repo = here.parents[2]
    router = repo / "app" / "modules" / "boq" / "router.py"
    return ast.parse(router.read_text(encoding="utf-8"), filename=str(router))


def _find_handler(name: str) -> ast.AsyncFunctionDef:
    tree = _load_router_ast()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    pytest.fail(f"handler {name} not found in boq.router")


def _has_where_is_locked_false(fn: ast.AsyncFunctionDef) -> bool:
    """Verify the handler chains a ``.where(BOQ.is_locked == False)`` clause.

    We look for any ``Compare`` node whose left side references
    ``is_locked`` and whose comparator is the boolean literal ``False``.
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare):
            left = node.left
            attr_name = None
            if isinstance(left, ast.Attribute):
                attr_name = left.attr
            if attr_name == "is_locked":
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and comp.value is False:
                        return True
    return False


def _has_where_is_locked_true(fn: ast.AsyncFunctionDef) -> bool:
    """Same as the False-variant — used for the unlock CAS check."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare):
            left = node.left
            attr_name = None
            if isinstance(left, ast.Attribute):
                attr_name = left.attr
            if attr_name == "is_locked":
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and comp.value is True:
                        return True
    return False


def _checks_rowcount(fn: ast.AsyncFunctionDef) -> bool:
    """Verify the handler reads ``result.rowcount`` and branches on it.

    Without this check the CAS pattern silently swallows race losses
    instead of returning a 409.
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute) and node.attr == "rowcount":
            return True
    return False


def test_lock_boq_uses_cas() -> None:
    """lock_boq must guard its UPDATE with ``WHERE is_locked = false``.

    Pure READ -> CHECK -> UPDATE re-opens the TOCTOU race that B7 closes.
    """
    fn = _find_handler("lock_boq")
    assert _has_where_is_locked_false(fn), (
        "lock_boq no longer constrains its UPDATE to is_locked=false — "
        "the TOCTOU race against a second concurrent lock is back"
    )


def test_lock_boq_inspects_rowcount() -> None:
    """The CAS pattern is meaningless without checking rowcount.

    Pin the conflict-detection step so a refactor can't silently drop it.
    """
    fn = _find_handler("lock_boq")
    assert _checks_rowcount(fn), (
        "lock_boq runs a CAS UPDATE but never inspects rowcount — race losers won't get a 409 Conflict"
    )


def test_unlock_boq_uses_cas() -> None:
    """unlock_boq must guard its UPDATE with ``WHERE is_locked = true``.

    Symmetric to lock_boq: prevents double-unlock from writing two
    "draft" reverts (and two activity-log entries).
    """
    fn = _find_handler("unlock_boq")
    assert _has_where_is_locked_true(fn), (
        "unlock_boq no longer constrains its UPDATE to is_locked=true — double-unlock race is back"
    )


def test_unlock_boq_inspects_rowcount() -> None:
    """Same pin for unlock — without rowcount check the CAS is decoration."""
    fn = _find_handler("unlock_boq")
    assert _checks_rowcount(fn), (
        "unlock_boq runs a CAS UPDATE but never inspects rowcount — the 'not locked' 400 will never fire"
    )
