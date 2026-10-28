"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Fail if the weak-JWT-secret denylist or its length threshold is restated.

Why this exists. The denylist of known-weak JWT secrets and the 32-unit
minimum length lived in two files at once, ``app/config.py`` and
``app/main.py``, each maintained by hand. That shape is invisible while the
copies agree and silent when they stop agreeing, and these two had already
stopped: the copy in ``main.py`` was missing three of the strings the other
rejected, and it counted UTF-8 bytes where the other counted characters, so
they disagreed on any non-ASCII secret. Nobody noticed, because nothing was
comparing them.

Collapsing them fixes today. This script is what keeps them collapsed: it
fails the moment a second copy appears, rather than the moment the second
copy starts to matter.

Two independent checks, both over the AST rather than the text, so a
reformat or a different quote style cannot slip past:

1. A collection literal (set, frozenset, list, tuple) holding two or more
   known-weak secret strings, anywhere outside the canonical module.
2. A length comparison of the form ``len(<... jwt_secret ...>) < <number>``,
   anywhere outside the canonical module.

Usage:
    python scripts/check_secret_denylist_single_source.py

Exit codes: 0 clean, 1 a second copy was found, 2 the canonical module no
longer looks the way this script expects.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The one module allowed to state these constants. Named here rather than
# hidden in a path test below, so that moving the source of truth is a
# deliberate one-line edit to this list.
CANONICAL = {Path("backend/app/config.py")}

# Trees to scan. Tests are deliberately excluded: a test asserting on the
# canonical list has to spell the strings out, and that is the test doing its
# job, not a second source of truth.
SCAN_ROOTS = [Path("backend/app")]

# Enough of the denylist to recognise a copy of it. A file naming two or more
# of these in one literal is keeping its own list, whatever it calls it.
KNOWN_WEAK_MARKERS = frozenset(
    {
        "openestimate-local-dev-key",
        "change-me",
        "change-me-in-production",
        "secret",
        "jwt-secret",
    }
)

COLLECTION_NODES = (ast.Set, ast.List, ast.Tuple)


def _string_items(node: ast.AST) -> set[str]:
    """The string constants directly inside a collection literal."""
    elts: list[ast.expr] = []
    if isinstance(node, COLLECTION_NODES):
        elts = list(node.elts)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset":
        for arg in node.args:
            if isinstance(arg, COLLECTION_NODES):
                elts.extend(arg.elts)
    return {e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}


def _mentions_jwt_secret(node: ast.AST) -> bool:
    """Whether any name or attribute under ``node`` is called jwt_secret."""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and "jwt_secret" in child.id:
            return True
        if isinstance(child, ast.Attribute) and "jwt_secret" in child.attr:
            return True
    return False


def _scan(path: Path, source: str) -> list[str]:
    findings: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: could not parse ({exc.msg})"]

    for node in ast.walk(tree):
        # 1. A second denylist.
        overlap = _string_items(node) & KNOWN_WEAK_MARKERS
        if len(overlap) >= 2:
            findings.append(
                f"{path}:{node.lineno}: a second denylist of weak JWT secrets "
                f"({sorted(overlap)}). Import jwt_secret_is_known_weak from "
                f"app.config instead of restating the strings."
            )

        # 2. A second length threshold.
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Call):
            func = node.left.func
            is_len_call = isinstance(func, ast.Name) and func.id == "len"
            compared_to_number = any(
                isinstance(c, ast.Constant) and isinstance(c.value, int) and not isinstance(c.value, bool)
                for c in node.comparators
            )
            if is_len_call and compared_to_number and _mentions_jwt_secret(node.left):
                findings.append(
                    f"{path}:{node.lineno}: a second minimum-length rule for the "
                    f"JWT secret. Import jwt_secret_is_too_short from app.config "
                    f"instead of comparing a length here."
                )

    return findings


def main() -> int:
    canonical_path = ROOT / "backend/app/config.py"
    canonical_source = canonical_path.read_text(encoding="utf-8")
    # Guard against the source of truth being renamed or gutted while this
    # script keeps reporting a clean tree over the remaining copies.
    for expected in (
        "_JWT_KNOWN_WEAK_SECRETS",
        "jwt_secret_is_known_weak",
        "jwt_secret_is_too_short",
    ):
        if expected not in canonical_source:
            print(f"ERROR: {canonical_path} no longer defines {expected}.")
            print("The source of truth moved; update CANONICAL in this script.")
            return 2

    findings: list[str] = []
    scanned = 0
    for scan_root in SCAN_ROOTS:
        for path in sorted((ROOT / scan_root).rglob("*.py")):
            relative = path.relative_to(ROOT)
            if Path(*relative.parts) in CANONICAL:
                continue
            scanned += 1
            findings.extend(_scan(relative, path.read_text(encoding="utf-8")))

    if findings:
        print("The weak-secret denylist must have exactly one source of truth.")
        print(f"Found {len(findings)} restatement(s) across {scanned} scanned file(s):\n")
        for finding in findings:
            print(f"  - {finding}")
        print(f"\nThe source of truth is {canonical_path.relative_to(ROOT)}.")
        return 1

    print(f"OK: no second copy of the weak-secret denylist or its length rule ({scanned} files scanned).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
