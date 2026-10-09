"""Print the alembic heads of an installed site-packages tree by AST, not regex.

Usage: heads.py <site-packages>  -> prints "<n_revisions> <head> [<head>...]", exit 1 unless one head.
"""

import ast
import pathlib
import sys

root = pathlib.Path(sys.argv[1]) / "alembic" / "versions"
revs, parents = {}, set()
for f in root.glob("*.py"):
    tree = ast.parse(f.read_text(encoding="utf-8"))
    rev = down = None
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if not targets or node.value is None:
            continue
        if "revision" in targets and isinstance(node.value, ast.Constant):
            rev = node.value.value
        if "down_revision" in targets:
            v = node.value
            if isinstance(v, ast.Constant):
                down = [v.value] if v.value else []
            elif isinstance(v, (ast.Tuple, ast.List)):
                down = [e.value for e in v.elts if isinstance(e, ast.Constant)]
    if rev:
        revs[rev] = f.name
        parents.update(down or [])
assert len(revs) > 100, f"only {len(revs)} revisions found under {root}"
heads = sorted(set(revs) - parents)
print(len(revs), *heads)
sys.exit(0 if len(heads) == 1 else 1)
