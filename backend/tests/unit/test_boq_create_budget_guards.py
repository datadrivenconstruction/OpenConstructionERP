# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""create_budget_from_boq guards - audit findings (access check + idempotency).

The handler historically had two gaps:

* SECURITY - it was the only mutating BOQ handler without a
  ``_verify_boq_owner`` project-access check, so any authenticated user
  with the ``boq.update`` permission could materialise budgets from a
  foreign tenant's BOQ.
* M2 - it unconditionally ``session.add``-ed a finance ProjectBudget per
  group on every call, duplicating the budget on rerun while the
  docstring claimed idempotency.

These tests are AST-based (cheap and deterministic), mirroring
``test_boq_lock_cas.py``: they pin the shape of the implementation so a
refactor cannot silently drop either guard. The end-to-end behaviour is
covered by ``tests/integration/test_cross_module_flows.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _find_handler(name: str) -> ast.AsyncFunctionDef:
    here = Path(__file__).resolve()
    router = here.parents[2] / "app" / "modules" / "boq" / "router.py"
    tree = ast.parse(router.read_text(encoding="utf-8"), filename=str(router))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    pytest.fail(f"handler {name} not found in boq.router")


def test_create_budget_verifies_boq_owner() -> None:
    """The handler must run the same access check as every other mutator."""
    fn = _find_handler("create_budget_from_boq")
    calls = {node.func.id for node in ast.walk(fn) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "_verify_boq_owner" in calls, (
        "create_budget_from_boq no longer calls _verify_boq_owner - any "
        "authenticated user could build budgets from a foreign BOQ"
    )


def test_create_budget_declares_user_payload_dependency() -> None:
    """_verify_boq_owner needs the JWT payload for the admin bypass."""
    fn = _find_handler("create_budget_from_boq")
    annotations = {arg.annotation.id for arg in fn.args.args if isinstance(arg.annotation, ast.Name)}
    assert "CurrentUserPayload" in annotations, "create_budget_from_boq dropped its CurrentUserPayload dependency"


def test_create_budget_skips_existing_groups() -> None:
    """Rerunning the endpoint must not duplicate finance budgets (audit M2).

    Pin the idempotency guard: the group loop carries a continue branch
    keyed on the set of group keys already materialised from this BOQ.
    """
    fn = _find_handler("create_budget_from_boq")
    src = ast.unparse(fn)
    assert "existing_group_keys" in src, (
        "create_budget_from_boq no longer loads the groups already "
        "materialised from this BOQ - reruns will duplicate the budget"
    )
    assert "skipped_existing" in src, (
        "create_budget_from_boq no longer reports skipped groups - the "
        "response counts hide whether the call was a rerun"
    )
