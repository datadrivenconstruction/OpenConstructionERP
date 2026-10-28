# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Guard: no bare numeric literal may act as money inside the COPQ maths.

The cost of poor quality used to be part guess. ``compute_copq`` multiplied
the open punch count by a module constant of ``Decimal("250.00")`` in no
declared currency, so the headline figure was a number nobody had recorded
and nobody could denominate. The rework term now comes from
``punchlist.PunchItem.rework_cost``, which is money a human actually entered
alongside the currency they entered it in.

This file is the ratchet that keeps it that way. It reads the source with
``ast`` and never imports the application, so it holds no database opinion
and cannot be skipped out from under a green summary by a missing
``OE_TEST_DB``. It prints its census: which functions it found, how many
nodes it walked, and every literal it saw with the verdict on each.

Two failure modes are covered, because the original defect used the second:

* a numeric literal written directly into the computation, and
* a module-level constant holding one, referenced by name from inside it -
  which a scan of the function bodies alone would walk straight past.
"""

from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_QMS_SERVICE = _BACKEND / "app" / "modules" / "qms" / "service.py"
_QMS_ROUTER = _BACKEND / "app" / "modules" / "qms" / "router.py"
_PUNCHLIST_SERVICE = _BACKEND / "app" / "modules" / "punchlist" / "service.py"

# Every function that contributes to a COPQ money figure. The scan asserts it
# found all of them: a rename must break this test loudly rather than empty
# the target set and report success having examined nothing.
_TARGETS = (
    "compute_copq",
    "compute_copq_detailed",
    "compute_copq_breakdown",
    "_recorded_rework_cost",
    "_rework_component",
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _numeric_value(node: ast.AST) -> Decimal | None:
    """Return the numeric value of a literal node, or None if it is not one.

    Recognises a bare ``int``/``float`` constant and the ``Decimal("...")``
    form the money code uses. ``Decimal(some_name)`` is not a literal and is
    deliberately not matched.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return None
        if isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Decimal":
        if len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
            arg = node.args[0].value
            if isinstance(arg, (int, float, str)):
                try:
                    return Decimal(str(arg))
                except InvalidOperation:
                    return None
    return None


def _describe(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - unparse is total on real sources
        return f"<{type(node).__name__}>"


def _parents(root: ast.AST) -> dict[int, ast.AST]:
    table: dict[int, ast.AST] = {}
    for parent in ast.walk(root):
        for child in ast.iter_child_nodes(parent):
            table[id(child)] = parent
    return table


def _decimal_bound_names(func: ast.AST) -> set[str]:
    """Local names that hold Decimal money somewhere in this function.

    A name assigned from an expression that constructs a ``Decimal``, or
    annotated as one, is carrying money. Row counters are plain ints and never
    appear here, which is what lets the scan tell ``priced += 1`` (counting
    punch items) apart from ``rework_total += 250`` (inventing money).
    """
    names: set[str] = set()
    for node in ast.walk(func):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
            annotation = getattr(node, "annotation", None)
            if isinstance(annotation, ast.Name) and annotation.id == "Decimal":
                names.update(t.id for t in targets if isinstance(t, ast.Name))
        if value is None:
            continue
        mentions_decimal = any(isinstance(sub, ast.Name) and sub.id == "Decimal" for sub in ast.walk(value))
        if mentions_decimal:
            names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _money_verdict(
    node: ast.AST,
    parents: dict[int, ast.AST],
    decimal_names: set[str],
) -> str | None:
    """Say why a nonzero literal is money here, or None if it is not.

    Money in this codebase is always ``Decimal``. Three shapes can turn a
    literal into a money term and each is reported:

    * ``Decimal("250.00")`` - the money constructor taking a literal. This is
      the exact shape the old hardcoded cost-per-punch had.
    * a bare literal inside arithmetic (``250 * count``, ``total + 250``),
      because ``int`` and ``Decimal`` mix silently in Python.
    * a bare literal augmenting a name already known to hold Decimal money.

    A literal inside a comparison, a subscript, or augmenting a plain int
    counter is counting rows, not currency.
    """
    if isinstance(node, ast.Call):
        return "Decimal() built from a literal"
    parent = parents.get(id(node))
    if isinstance(parent, (ast.Compare, ast.Subscript, ast.Slice)):
        return None
    if isinstance(parent, ast.BinOp):
        return "literal in arithmetic"
    if isinstance(parent, ast.AugAssign):
        target = parent.target
        if isinstance(target, ast.Name) and target.id in decimal_names:
            return f"literal augmenting Decimal name {target.id!r}"
        return None
    return None


def _module_numeric_constants(tree: ast.Module) -> dict[str, Decimal]:
    """Module-level names bound to a numeric literal, with their values."""
    found: dict[str, Decimal] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            value = _numeric_value(node.value)
            if value is not None:
                found[node.target.id] = value
        elif isinstance(node, ast.Assign) and node.value is not None:
            value = _numeric_value(node.value)
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = value
    return found


def _collect_targets(tree: ast.Module) -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _TARGETS:
            found[node.name] = node
    return found


def _scan(tree: ast.Module, label: str) -> tuple[list[str], dict[str, ast.AST], int]:
    """Scan every target function for money literals; print the whole census.

    Returns ``(offences, targets_found, nodes_walked)``. The caller decides
    what to do about a miss, so the same scanner serves both the ratchet over
    the real source and the negative test that proves it can still bite.
    """
    targets = _collect_targets(tree)
    module_constants = _module_numeric_constants(tree)
    offences: list[str] = []
    total_nodes = 0

    print(f"\n[{label}] targets expected: {len(_TARGETS)} -> {', '.join(_TARGETS)}")
    print(f"[{label}] targets found:    {len(targets)} -> {', '.join(sorted(targets)) or '(none)'}")
    print(
        f"[{label}] module-level numeric constants: "
        + (", ".join(f"{k}={v}" for k, v in sorted(module_constants.items())) or "(none)")
    )

    for name in sorted(targets):
        node = targets[name]
        parents = _parents(node)
        decimal_names = _decimal_bound_names(node)
        walked = list(ast.walk(node))
        total_nodes += len(walked)
        literals: list[str] = []
        referenced: set[str] = set()

        for sub in walked:
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                referenced.add(sub.id)
            value = _numeric_value(sub)
            if value is None:
                continue
            source = _describe(sub)
            if value == 0:
                literals.append(f"{source} (zero, allowed)")
                continue
            verdict = _money_verdict(sub, parents, decimal_names)
            if verdict is None:
                literals.append(f"{source} (counting, allowed)")
            else:
                literals.append(f"{source} (MONEY LITERAL: {verdict})")
                offences.append(f"{name}: {source} on line {getattr(sub, 'lineno', '?')} - {verdict}")

        for ref in sorted(referenced):
            if ref in module_constants and module_constants[ref] != 0:
                literals.append(f"{ref} -> {module_constants[ref]} (MONEY CONSTANT)")
                offences.append(f"{name}: references module constant {ref} = {module_constants[ref]}")

        print(
            f"[{label}] {name}: {len(walked)} nodes, "
            f"Decimal-bound names {sorted(decimal_names) or '(none)'}, "
            f"literals: {literals or ['(none)']}"
        )

    print(f"[{label}] nodes walked: {total_nodes}; offences: {len(offences)}")
    return offences, targets, total_nodes


def test_copq_maths_holds_no_hardcoded_money() -> None:
    """No numeric literal may act as money in the COPQ computation."""
    print(f"\n[copq-money-scan] source: {_QMS_SERVICE}")
    offences, targets, walked = _scan(_parse(_QMS_SERVICE), "copq-money-scan")

    missing = [name for name in _TARGETS if name not in targets]
    assert not missing, (
        f"COPQ money scan examined nothing for {missing}. These functions were renamed or removed; "
        f"update _TARGETS in this file so the ratchet keeps measuring something. "
        f"Found instead: {sorted(targets)}"
    )
    assert walked > 0, "the scan walked zero nodes and would pass having checked nothing"

    assert not offences, (
        "A numeric literal is acting as money in the COPQ computation:\n  "
        + "\n  ".join(offences)
        + "\nCost of poor quality must be summed from recorded amounts "
        "(punchlist.PunchItem.rework_cost, QMSNCR.cost_impact_amount), never from a constant. "
        "A constant carries no currency, so it cannot be added to anything."
    )


# The defect as it was actually written, plus the two other shapes it could
# come back as. If the scanner ever stops flagging these it has gone blind and
# the test above would pass by examining nothing meaningful.
_REGRESSION_SOURCE = """
from decimal import Decimal

_DEFAULT_REWORK_COST_PER_PUNCH: Decimal = Decimal("250.00")


async def compute_copq(self, project_id, rework_cost_per_punch=None):
    per_punch = rework_cost_per_punch or _DEFAULT_REWORK_COST_PER_PUNCH
    open_punch = await self.repo.count_open_punch(project_id)
    return per_punch * Decimal(open_punch)


async def compute_copq_detailed(self, project_id):
    return Decimal("250.00") * Decimal(1)


def compute_copq_breakdown(*, ncr_cost):
    return ncr_cost + 250


async def _recorded_rework_cost(self, project_id, base_currency):
    total = Decimal("0")
    total += 250
    return total


async def _rework_component(self, project_id):
    seen = 0
    seen += 1
    return seen
"""


def test_the_scanner_still_catches_the_original_defect() -> None:
    """Negative control: the scan must fail on the code it was written for."""
    print("\n[copq-money-scan] negative control over the pre-fix shape")
    offences, targets, _ = _scan(ast.parse(_REGRESSION_SOURCE), "copq-money-negative")

    assert len(targets) == len(_TARGETS), f"the control source no longer covers every target: {sorted(targets)}"
    flagged = " ".join(offences)
    assert "_DEFAULT_REWORK_COST_PER_PUNCH" in flagged, (
        "the scan missed a money constant referenced by name from inside the computation, "
        "which is exactly how the original 250 hid from a body-only scan"
    )
    assert "compute_copq_detailed" in flagged, "missed an inline Decimal money literal"
    assert "compute_copq_breakdown" in flagged, "missed a bare literal in money arithmetic"
    assert "_recorded_rework_cost" in flagged, "missed a bare literal augmenting a Decimal name"
    assert all("_rework_component" not in entry for entry in offences), (
        f"a plain row counter was misread as money: {offences}"
    )


def test_router_does_not_reintroduce_a_default_per_punch_rate() -> None:
    """The scan covers the service; this covers the one gap it leaves.

    ``compute_copq`` honours an explicit ``rework_cost_per_punch``, so giving
    that query parameter a nonzero default in the router would restore the old
    guessed figure through the front door while the service stayed literal
    free. The router is not scanned wholesale because its money bounds
    (``le=Decimal("1e15")``) are legitimate literals, so this asserts the one
    default that matters.
    """
    tree = _parse(_QMS_ROUTER)
    checked: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        names = [a.arg for a in (*args.args, *args.kwonlyargs)]
        if "rework_cost_per_punch" not in names:
            continue
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=False):
            if arg.arg == "rework_cost_per_punch" and default is not None:
                checked.append(f"{node.name}: {_describe(default)}")
        for arg, default in zip(args.args[-len(args.defaults) :], args.defaults, strict=False):
            if arg.arg == "rework_cost_per_punch":
                checked.append(f"{node.name}: {_describe(default)}")

    print(f"\n[copq-router-scan] source: {_QMS_ROUTER}")
    print(f"[copq-router-scan] rework_cost_per_punch defaults found: {checked or ['(none)']}")

    assert checked, (
        f"no rework_cost_per_punch parameter found in {_QMS_ROUTER}; this test checked nothing. "
        "If the endpoint moved, point this scan at its new home."
    )
    for entry in checked:
        assert "default=None" in entry, (
            f"the COPQ endpoint ships a default per-punch rework rate: {entry}. "
            "A default rate is the hardcoded 250 in another costume - it re-enters the total as "
            "money nobody recorded, in no stated currency. Leave it None so an absent rate stays absent."
        )


def _terminal_statuses(path: Path, name: str) -> set[str]:
    """Read a frozenset-of-strings module constant out of a source file."""
    for node in ast.walk(_parse(path)):
        target: ast.AST | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target if node.target.id == name else None
        elif isinstance(node, ast.Assign):
            target = next((t for t in node.targets if isinstance(t, ast.Name) and t.id == name), None)
        if target is None or getattr(node, "value", None) is None:
            continue
        return {
            elt.value
            for elt in ast.walk(node.value)  # type: ignore[attr-defined]
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        }
    return set()


def test_punch_terminal_status_vocabulary_has_not_drifted() -> None:
    """QMS mirrors the punchlist terminal statuses; they must stay identical.

    QMS cannot import the punchlist module at load time, so it holds a copy of
    the status vocabulary that decides which punch items still owe rework
    money. A copy is only safe while something checks it, or the COPQ figure
    quietly starts counting items the punchlist considers finished.
    """
    qms_set = _terminal_statuses(_QMS_SERVICE, "_PUNCH_TERMINAL_STATUSES")
    punch_set = _terminal_statuses(_PUNCHLIST_SERVICE, "_TERMINAL_STATUSES")

    print(f"\n[copq-vocab-scan] qms._PUNCH_TERMINAL_STATUSES = {sorted(qms_set)}")
    print(f"[copq-vocab-scan] punchlist._TERMINAL_STATUSES  = {sorted(punch_set)}")

    assert qms_set, f"read no statuses from {_QMS_SERVICE}; the scan checked nothing"
    assert punch_set, f"read no statuses from {_PUNCHLIST_SERVICE}; the scan checked nothing"
    assert qms_set == punch_set, (
        f"punch terminal-status vocabularies drifted: QMS has {sorted(qms_set)}, "
        f"punchlist has {sorted(punch_set)}. COPQ would price the difference."
    )
