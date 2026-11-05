"""The module wires up: imports resolve, routes exist, one migration head."""

from __future__ import annotations

import ast
import glob
from pathlib import Path


def test_router_service_and_manifest_import() -> None:
    from app.modules.offers import manifest
    from app.modules.offers.router import router

    paths = {r.path for r in router.routes}
    assert {"/context", "/{offer_id}/send", "/{offer_id}/accept", "/{offer_id}/preview"} <= paths
    assert manifest.name == "oe_offers"
    assert "oe_contacts" in manifest.depends


def test_migration_chain_has_one_head() -> None:
    versions = Path(__file__).resolve().parents[3] / "alembic" / "versions"
    revs: dict[str, str | None] = {}
    for f in glob.glob(str(versions / "*.py")):
        rev = down = None
        for node in ast.parse(Path(f).read_text(encoding="utf8")).body:
            target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
            if isinstance(target, ast.Name) and getattr(node, "value", None) is not None:
                if target.id == "revision":
                    rev = ast.literal_eval(node.value)
                if target.id == "down_revision":
                    down = ast.literal_eval(node.value)
        revs[rev] = down
    parents = {d for v in revs.values() for d in ([v] if isinstance(v, str) else (v or []))}
    assert [r for r in revs if r not in parents] == ["voff01_customer_offers"]


def test_accepting_needs_only_the_write_permission() -> None:
    """Accept is gated by boq.update; creating the contract is a separate, softer check."""
    source = (Path(__file__).resolve().parents[3] / "app/modules/offers/router.py").read_text(encoding="utf-8")
    start = source.index('"/{offer_id}/accept"')
    decorator = source[start : source.index("\n", start)]
    assert "_WRITE" in decorator
    assert "contracts.create" not in decorator
    assert "_AWARD" not in decorator
