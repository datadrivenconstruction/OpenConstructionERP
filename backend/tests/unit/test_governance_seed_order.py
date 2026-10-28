"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The governance demo seed pins the phase model before any module seeder runs.

The seed skips a project that already has a model. A module seeder that ran
first and pinned one would leave the demo project without area owners, gates
and decisions, so the order is part of the contract.
"""

from __future__ import annotations

import ast
import inspect

from app.core import demo_enrichment


def _line_of(tree: ast.AST, predicate) -> int:
    lines = [node.lineno for node in ast.walk(tree) if predicate(node)]
    assert len(lines) == 1, lines
    return lines[0]


def test_governance_is_seeded_before_the_module_seeders() -> None:
    tree = ast.parse(inspect.getsource(demo_enrichment))
    governance = _line_of(
        tree,
        lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_seed_governance",
    )
    module_loop = _line_of(
        tree,
        lambda n: isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "_module_seeders",
    )
    assert governance < module_loop


def test_conditions_are_settled_after_the_module_seeders() -> None:
    """Settling asks the module providers again, so it is worth nothing before they have rows."""
    tree = ast.parse(inspect.getsource(demo_enrichment))
    settle = _line_of(
        tree,
        lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_settle_governance",
    )
    module_loop = _line_of(
        tree,
        lambda n: isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "_module_seeders",
    )
    assert settle > module_loop


def test_the_enrichment_hands_back_what_both_governance_steps_reported() -> None:
    """Both results are stored on the report the enrichment returns, not dropped after a log line."""
    tree = ast.parse(inspect.getsource(demo_enrichment.enrich_projects))
    stored = {
        ast.unparse(node.targets[0]): node.value.value.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Await)
        and isinstance(node.value.value, ast.Call)
        and isinstance(node.value.value.func, ast.Name)
        and node.value.value.func.id == "_settle_governance"
    }
    assert stored == {"report['project_governance']['settle']": "_settle_governance"}
    source = inspect.getsource(demo_enrichment.enrich_projects)
    assert '{"seed": await _seed_governance(async_session_factory, _demo_pids)}' in source
    returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return)]
    assert returns and all(isinstance(r.value, ast.Name) and r.value.id == "report" for r in returns)


def test_the_cast_is_filled_before_governance_is_seeded() -> None:
    """Without a decider who owns no area the governance seed writes nothing at all."""
    tree = ast.parse(inspect.getsource(demo_enrichment))
    cast = _line_of(
        tree,
        lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_demo_cast",
    )
    governance = _line_of(
        tree,
        lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_seed_governance",
    )
    assert cast < governance
