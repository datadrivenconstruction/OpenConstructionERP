# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A payload of positions must reach the engine through the shared builder.

A validation rule reads its inputs from the mapping the caller hands the
engine, and a rule whose input is missing returns nothing rather than failing.
So a surface that assembles that mapping by hand is not caught by anything: the
report comes back, the rules that had what they needed ran, and the ones that
did not are absent from a list nobody counted. That is how
``boq_quality.unit_system_consistency`` came to fire on the demo seeder and the
estimate audit while staying silent behind the Validate button, on the same
bill, for the same project.

What is asserted here is the property, not a list of today's surfaces. A gate
that named the four call sites that were wrong in August would pass on the
fifth the day someone writes it, which makes it a check on the list rather than
on the thing. The statement is: anywhere in ``app`` that hands the engine a
payload carrying ``positions``, that payload passes through
:func:`app.core.validation.project_context.with_project_context`. A new surface
is covered without anyone remembering, and one that stops calling the builder
is named by file and line.

Two limits, stated rather than left to be discovered. The check reads source,
so a payload assembled inside a helper the call site merely invokes is opaque
to it - it sees ``data=_my_payload()`` and cannot say what is in there. And it
recognises the builder by name, so aliasing it past the check is possible for
anyone who wants to. Both are the ordinary limits of a source-level property;
neither is reachable by accident, which is what this guards against.

It lives in the PG lane because that lane is a merge gate and the default unit
lane is not. The check itself needs no database.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.validation.project_context import PROJECT_CONTEXT_KEYS

APP_DIR = Path(__file__).resolve().parents[2] / "app"

#: The one function allowed to add the project-derived half of a payload.
BUILDER = "with_project_context"

#: The key whose presence makes a payload a bill-shaped one. Rules that read
#: rows read this; anything carrying it is validating somebody's positions.
POSITIONS_KEY = "positions"


def _payload_arg(call: ast.Call) -> ast.expr | None:
    """Return the payload argument of an engine ``validate(...)`` call, if it is one.

    ``data`` is the engine's first positional parameter, not a keyword-only
    one, so reading ``call.keywords`` alone would let ``validate({"positions":
    rows}, ["boq_quality"])`` past the check. A call is taken as the engine's
    when it carries ``rule_sets``, by keyword or as a second positional; a
    single-argument ``rule.validate(context)`` is a rule being driven directly
    and is a different shape with a different meaning.
    """
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "validate":
        return None
    for keyword in call.keywords:
        if keyword.arg == "data":
            return keyword.value
    names = {keyword.arg for keyword in call.keywords}
    if call.args and ("rule_sets" in names or len(call.args) >= 2):
        return call.args[0]
    return None


def _assignments(scope: ast.AST) -> dict[str, ast.expr]:
    """Map each plain ``name = value`` in ``scope`` to its last assigned value."""
    found: dict[str, ast.expr] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            found[node.target.id] = node.value
    return found


def _resolved(expr: ast.expr, assigned: dict[str, ast.expr]) -> ast.expr:
    """Follow a bare name to the expression it was assigned.

    ``data=payload`` is the same offence as ``data={"positions": rows}`` and
    has to be read as one, or the gate only ever sees the form nobody writes.
    """
    seen: set[str] = set()
    while isinstance(expr, ast.Name) and expr.id in assigned and expr.id not in seen:
        seen.add(expr.id)
        expr = assigned[expr.id]
    return expr


def _expanded(expr: ast.expr, assigned: dict[str, ast.expr]) -> list[ast.expr]:
    """The payload expression plus whatever each ``**name`` in it stands for.

    ``{**base, "positions": rows}`` is how a payload legitimately grows after
    the builder has run, and reading it without following ``base`` would
    convict the compliant form.
    """
    root = _resolved(expr, assigned)
    out = [root]
    for node in ast.walk(root):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if key is None:
                    out.append(_resolved(value, assigned))
    return out


def _mentions(expr: ast.expr, needle: str) -> bool:
    """True when ``needle`` appears as a string constant or a called name."""
    for node in ast.walk(expr):
        if isinstance(node, ast.Constant) and node.value == needle:
            return True
        if isinstance(node, ast.Name) and node.id == needle:
            return True
        if isinstance(node, ast.Attribute) and node.attr == needle:
            return True
    return False


def _innermost_scope(tree: ast.Module, call: ast.Call) -> ast.AST:
    """The smallest function containing ``call``, or the module.

    Smallest rather than first: a local name has to be read against its own
    function, not against a same-named variable in an enclosing one.
    """
    best: ast.AST = tree
    best_size = len(list(ast.walk(tree)))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(ast.walk(node))
        if any(inner is call for inner in body) and len(body) <= best_size:
            best, best_size = node, len(body)
    return best


def hand_built_positions_payloads(source: str, label: str) -> list[str]:
    """Return ``"label:line"`` for each positions payload not built by ``BUILDER``.

    Args:
        source: Python source to read.
        label: What to call it in the returned findings (a path, usually).

    Returns:
        One entry per offending ``validate(data=...)`` call, empty when the
        module is clean.
    """
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        payload = _payload_arg(node)
        if payload is None:
            continue
        assigned = _assignments(_innermost_scope(tree, node))
        parts = _expanded(payload, assigned)
        if not any(_mentions(part, POSITIONS_KEY) for part in parts):
            continue
        if any(_mentions(part, BUILDER) for part in parts):
            continue
        offenders.append(f"{label}:{node.lineno}")
    return sorted(offenders)


def _returns_a_positions_mapping(expr: ast.expr, assigned: dict[str, ast.expr]) -> bool:
    """True when ``expr`` evaluates to a mapping literal carrying ``positions``.

    Deliberately narrower than :func:`_mentions`. A function that returns a
    plain list it happens to have called ``positions`` is not building a
    payload, and reading the name would convict every loader in the tree.
    A dict literal with that key is a payload and nothing else is.
    """
    for part in _expanded(expr, assigned):
        for node in ast.walk(part):
            if isinstance(node, ast.Dict) and any(
                isinstance(key, ast.Constant) and key.value == POSITIONS_KEY for key in node.keys
            ):
                return True
    return False


def helper_built_positions_payloads(source: str, label: str) -> list[str]:
    """Return ``"label:line"`` for each function that returns a positions payload without ``BUILDER``.

    The gate above reads the ``validate(data=...)`` call site, so a payload
    assembled one function earlier is invisible to it - the call site sees
    ``data=await self._engine_payload(...)`` and cannot say what is inside.
    That hop is the normal way this code is written, not an evasion, so the
    property is restated where the payload is actually built: a function whose
    return value is a mapping carrying ``positions`` calls the builder.

    Args:
        source: Python source to read.
        label: What to call it in the returned findings (a path, usually).

    Returns:
        One entry per offending function, empty when the module is clean.
    """
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        assigned = _assignments(node)
        returns = [inner.value for inner in ast.walk(node) if isinstance(inner, ast.Return) and inner.value is not None]
        if not any(_returns_a_positions_mapping(value, assigned) for value in returns):
            continue
        if any(_mentions(inner, BUILDER) for inner in ast.walk(node)):
            continue
        offenders.append(f"{label}:{node.lineno}")
    return sorted(offenders)


def test_every_positions_payload_in_app_is_built_by_the_shared_builder() -> None:
    """The positive side: no surface in ``app`` hand-builds one today."""
    offenders: list[str] = []
    scanned = 0
    for path in sorted(APP_DIR.rglob("*.py")):
        scanned += 1
        offenders.extend(
            hand_built_positions_payloads(path.read_text(encoding="utf-8"), path.relative_to(APP_DIR.parent).as_posix())
        )
    assert scanned > 100, f"the scan read {scanned} files, which is not the application"
    assert offenders == [], (
        "these validation runs hand-build a payload of positions, so every rule reading a "
        f"project-derived key is silent on them: {offenders}"
    )


#: What makes a module one that runs validation. A mapping with a ``positions``
#: key is not by itself a validation payload - the demo catalog, the cost-base
#: registry and the chat tool layer all return one and mean a page of rows -
#: so the helper property is asked only of modules that drive the engine. The
#: limit that leaves: a payload builder living in a module that never names the
#: engine is not read. That is a module boundary worth keeping anyway, and the
#: call-site gate above still covers wherever such a payload is handed over.
ENGINE = "validation_engine"


def test_every_helper_that_returns_a_positions_payload_calls_the_builder() -> None:
    """The same property one hop earlier: no helper in ``app`` builds one by hand."""
    offenders: list[str] = []
    scanned = 0
    for path in sorted(APP_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if ENGINE not in source:
            continue
        scanned += 1
        offenders.extend(helper_built_positions_payloads(source, path.relative_to(APP_DIR.parent).as_posix()))
    assert scanned > 5, f"the scan read {scanned} modules that drive the engine, which is too few to be the set"
    assert offenders == [], (
        "these helpers return a payload of positions the shared builder never saw, so a rule "
        f"reading a project-derived key is silent wherever they are used: {offenders}"
    )


def _reported_details(tree: ast.Module) -> set[int]:
    """Ids of the dict literals passed as a rule result's ``details=``.

    A rule naming the measurement system in its own findings is reporting what
    it was given, which is the opposite of overwriting it. Everything else that
    writes the key is writing a payload.
    """
    return {
        id(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "details" and isinstance(keyword.value, ast.Dict)
    }


def _payload_key_writes(tree: ast.Module) -> bool:
    """True when the module writes a project-derived key anywhere but a finding."""
    reported = _reported_details(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Subscript)
            and isinstance(target.slice, ast.Constant)
            and target.slice.value in PROJECT_CONTEXT_KEYS
            for target in node.targets
        ):
            return True
        if isinstance(node, ast.Dict) and id(node) not in reported:
            keys = {key.value for key in node.keys if isinstance(key, ast.Constant)}
            if keys & set(PROJECT_CONTEXT_KEYS):
                return True
    return False


def test_the_builder_is_the_only_thing_that_writes_the_project_keys() -> None:
    """The builder is the only place in ``app`` that writes those keys.

    Without this the gate above could be satisfied by a surface that calls the
    builder and then overwrites what it returned, which would put the key back
    in the payload while making it say whatever that surface preferred.
    """
    writers: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if not any(key in source for key in PROJECT_CONTEXT_KEYS):
            continue
        if _payload_key_writes(ast.parse(source)):
            writers.append(path.relative_to(APP_DIR.parent).as_posix())
    assert sorted(set(writers)) == ["app/core/validation/project_context.py"], (
        f"the project-derived validation keys are written outside the one builder: {sorted(set(writers))}"
    )


# ── the other polarity ────────────────────────────────────────────────────
#
# A gate is worth exactly what it catches, and this one is only worth
# something if it goes red when a surface stops calling the builder. Each
# snippet below is a form somebody actually writes.

_INLINE = """
async def run(session, project_id, rows):
    return await validation_engine.validate(data={"positions": rows}, rule_sets=["boq_quality"])
"""

_VIA_LOCAL = """
async def run(session, project_id, rows):
    payload = {"positions": rows}
    return await validation_engine.validate(data=payload, rule_sets=["boq_quality"])
"""

_POSITIONAL = """
async def run(session, project_id, rows):
    return await validation_engine.validate({"positions": rows}, ["boq_quality"])
"""

_A_RULE_DRIVEN_DIRECTLY = """
async def run(rows):
    context = ValidationContext(data={"positions": rows})
    return await BOQUnitSystemConsistencyRule().validate(context)
"""

_SPREAD_OVER_THE_BUILDER = """
async def run(session, project_id, rows):
    base = await with_project_context(session, project_id, {})
    payload = {**base, "positions": rows}
    return await validation_engine.validate(data=payload, rule_sets=["boq_quality"])
"""

_COMPLIANT = """
async def run(session, project_id, rows):
    return await validation_engine.validate(
        data=await with_project_context(session, project_id, {"positions": rows}),
        rule_sets=["boq_quality"],
    )
"""

_COMPLIANT_VIA_LOCAL = """
async def run(session, project_id, rows):
    payload = await with_project_context(session, project_id, {"positions": rows})
    return await validation_engine.validate(data=payload, rule_sets=["boq_quality"])
"""


_HELPER_HAND_BUILT = """
async def payload(session, project_id, rows):
    return {"positions": rows}
"""

_HELPER_COMPLIANT = """
async def payload(session, project_id, rows):
    return await with_project_context(session, project_id, {"positions": rows})
"""

_A_LOADER_RETURNING_A_LIST = """
async def load(session):
    positions = await fetch(session)
    return positions
"""


def test_a_helper_that_builds_a_payload_by_hand_is_named() -> None:
    """The new property goes red on the form it exists to catch."""
    assert helper_built_positions_payloads(_HELPER_HAND_BUILT, "helper") == ["helper:2"]


@pytest.mark.parametrize(
    ("label", "source"),
    [("compliant", _HELPER_COMPLIANT), ("a_loader", _A_LOADER_RETURNING_A_LIST)],
    ids=["compliant", "a_loader"],
)
def test_a_helper_that_is_not_hand_building_a_payload_is_not_named(label: str, source: str) -> None:
    """And its controls, including the loader whose list is merely called positions."""
    assert helper_built_positions_payloads(source, label) == []


@pytest.mark.parametrize(
    ("label", "source", "line"),
    [("inline", _INLINE, 3), ("via_local", _VIA_LOCAL, 4), ("positional", _POSITIONAL, 3)],
    ids=["inline", "via_local", "positional"],
)
def test_a_surface_that_stops_calling_the_builder_is_named(label: str, source: str, line: int) -> None:
    """Removing the shared construction makes the gate name that surface."""
    assert hand_built_positions_payloads(source, label) == [f"{label}:{line}"], (
        f"the gate did not name the {label} form, so it would not have caught it in app/"
    )


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("direct", _COMPLIANT),
        ("via_local", _COMPLIANT_VIA_LOCAL),
        ("spread", _SPREAD_OVER_THE_BUILDER),
        ("rule_driven_directly", _A_RULE_DRIVEN_DIRECTLY),
    ],
    ids=["direct", "via_local", "spread", "rule_driven_directly"],
)
def test_a_surface_that_calls_the_builder_is_not_named(label: str, source: str) -> None:
    """And the control: the compliant forms are not reported.

    ``rule_driven_directly`` is here for the other kind of false positive. A
    test that drives one rule with a context it built itself is not a product
    surface and must not be convicted by the widened positional reading.
    """
    assert hand_built_positions_payloads(source, label) == []
