# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠No seeded record may hold a value its own module would refuse.

Four modules have now been caught doing exactly that: contacts on
``contact_type``, variations on its status vocabulary, safety on four fields at
once, and contracts on ``counterparty_type``, where the seed wrote "contractor"
against a module that offers client and subcontractor and a picker that offers
the same two. Four instances is a class, so this checks every module rather than
waiting for the fifth to be reported.

The mechanism behind the class is that the seeder builds ORM rows directly. It
never passes the Pydantic layer that owns the vocabulary, and the columns behind
these fields are plain ``String`` with no enum, so the database accepts anything.
What reaches the screen is then a value the create endpoint would 422, the edit
form cannot re-select, and any filter built from the real vocabulary cannot find.

Three notes on the method, each of which cost a wrong answer to learn.

A regex over the seed source does not work. Auditing safety that way reported
"workmanship" and "supervision" as severities; both are NCR fields sitting a few
lines from the incident block. Values are read out of ``ast`` dict literals here,
never out of raw text.

A field name is not enough to identify a vocabulary. ``priority`` is a task field
and a punchlist field with different scales, and "critical" is legal in the
second and refused by the first; ``status`` belongs to nearly every module. Each
literal is therefore attributed to a schema by how much of its key set that
schema covers, and judged only against the vocabulary of the module it was
attributed to.

Constraints are read from ``model_fields`` rather than parsed from source,
because several are built from a module-level constant - contracts writes
``rf"^({COUNTERPARTY_TYPES})$"`` - and only the resolved pattern states the
actual vocabulary.

What this cannot see, measured rather than assumed. Reintroducing all four of the
defects above, it catches the contracts and tasks ones and misses the safety one,
because the safety values live in a tuple pool that a generator reads rather than
in a dict literal. That measurement predates both the table resolution below and
the shape and value split, either of which may have narrowed it, and it has not
been repeated, so read it as a floor on the blindness rather than a description
of it. Either way it is the division of labour with
``test_demo_safety_vocabulary.py``, which calls the generator and validates real
schema objects: this file is wide and shallow across every module, that one is
narrow and deep on the module where it mattered. A module whose seed is generated
rather than written needs the second kind.

The floors below exist so that a change which quietly drops the attribution rate
to zero fails instead of passing, because a comparison over nothing passes. Of
1642 dict literals in the seed sources, 895 are readable as records and 401
attribute to a schema that states a vocabulary; the rest are configuration and
nested fragments that are not records at all. Counted 18.08 by walking every
``ast.Dict`` in ``_seed_sources()`` and running ``_record_literals`` and
``_scan`` over them, not by reading the assertions. The first two rose from 752
and 352 when attribution moved onto the record's shape: a record whose other
fields are f-strings and calls used to fall under the floor and be dropped
whole, which is how a seeded submittal type outside its own vocabulary reached
every generated project with this file green.

A floor sitting far under the real number stops being a floor. These were set
when 143 records attributed and 143 was already the number after a defect that
silenced hundreds of them, which is how a scan reading a third of the seed went
on passing for months. They are now set close enough to bite.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from functools import cache
from pathlib import Path
from typing import Any

import app.modules as modules_pkg
from app.core import demo_projects

# A pattern states a vocabulary only when it is a plain alternation of literals.
# Anything else - a date shape, a length rule - says nothing about which words
# are allowed and is skipped rather than guessed at.
_VOCABULARY = re.compile(r"\^\(([a-z0-9_|\-]+)\)\$")

# Minimum keys a literal must share with a schema before it is attributed at
# all, and the share of its keys that must land. Below either, the match is a
# coincidence: three-key config dicts overlap almost everything.
_MIN_SHARED_KEYS = 3
_MIN_COVERAGE = 0.5

# Floors, so that a scan which stops finding anything fails rather than passes.
# Measured 18.08: 452 schemas carry a vocabulary, 662 fields across them, and
# 401 seeded records attribute. Set under those so ordinary drift and a module
# that fails to import do not trip them, but close enough that losing a quarter
# of the seed does. The previous pair sat at 250 and 90 against a real 143, wide
# enough that a scan reading no loop-built record at all still cleared them.
_MIN_SCHEMAS_WITH_VOCABULARY = 380
_MIN_ATTRIBUTED_RECORDS = 360

# Places the scan reached a constrained field and could not read its value: the
# record spells it, but it is built from a call or an f-string. Eight today.
# Held rather than only printed, because this number growing means the scan is
# judging less of the seed than it used to while still reporting clean.
_MAX_UNRESOLVED_FIELDS = 20


def _module_schemas() -> tuple[dict[str, set[str]], dict[str, dict[str, tuple[str, set[str]]]], list[str]]:
    """Every schema's field names and the ones that state a vocabulary.

    Returns ``({module.SchemaName: field names}, {module.SchemaName: {field:
    (module, allowed)}}, [modules that would not import])``. A module whose
    schemas do not import is skipped rather than failing the run: this test is
    about the seed, and an import break has its own tests. It is carried out in
    the third value all the same, because a lane short of an optional dependency
    loses vocabularies rather than seeds bad values, and a floor that goes red
    should say which of the two happened instead of leaving the seed accused.

    Keyed by module and class, not by class alone. A bare class name is not
    unique across 184 modules: 130 of 3145 schema names are declared by two
    modules or more, and in 21 of those the same field states a genuinely
    different vocabulary. ``PunchItemCreate.category`` is one, punchlist and
    qms, and it decided the answer for the punch list twice over. Keyed by name,
    whichever module ``pkgutil`` walked last silently replaced the other, so a
    snag row was judged against qms - which accepts "finishes" and has never
    heard of "hvac". The check would have excused a value the owning module
    refuses and accused one it requires, and both readings look identical from
    the outside. Other pairs in the same shape: LeadCreate.status across crm and
    property_dev, InspectionUpdate.status across three modules, WorkOrder across
    schedule and service.
    """
    fields: dict[str, set[str]] = {}
    constrained: dict[str, dict[str, tuple[str, set[str]]]] = {}
    unreadable: list[str] = []
    for info in pkgutil.iter_modules(modules_pkg.__path__):
        dotted = f"app.modules.{info.name}.schemas"
        try:
            schemas = importlib.import_module(dotted)
        except ModuleNotFoundError as exc:
            # 20 of the 191 modules ship no schemas file at all - the regional
            # packs, cad, match, admin - and that absence is the ordinary shape
            # rather than a fault. A ModuleNotFoundError naming anything else is
            # a dependency the lane does not have, and it takes that module's
            # vocabularies out of the count with it.
            if exc.name != dotted:
                unreadable.append(f"{dotted}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - see docstring
            unreadable.append(f"{dotted}: {type(exc).__name__}: {exc}")
            continue
        for attr in dir(schemas):
            model_fields = getattr(getattr(schemas, attr), "model_fields", None)
            if not isinstance(model_fields, dict) or not model_fields:
                continue
            qualified = f"{info.name}.{attr}"
            fields[qualified] = set(model_fields)
            for name, field in model_fields.items():
                for meta in getattr(field, "metadata", []) or []:
                    pattern = getattr(meta, "pattern", None)
                    if not isinstance(pattern, str):
                        continue
                    match = _VOCABULARY.fullmatch(pattern)
                    if match:
                        constrained.setdefault(qualified, {})[name] = (info.name, set(match.group(1).split("|")))
    return fields, constrained, unreadable


def _home_module(qualified: str) -> str:
    """The module half of a ``module.SchemaName`` key."""
    return qualified.split(".", 1)[0]


def _seed_sources() -> list[Path]:
    core = Path(demo_projects.__file__).parent
    backend_app = core.parent
    return sorted(core.glob("demo_*.py")) + sorted(backend_app.glob("modules/*/seed.py"))


def _where(path: Path) -> str:
    """A path a reader can act on. Several seed files share the basename seed.py."""
    parts = path.parts
    return "/".join(parts[parts.index("app") :]) if "app" in parts else path.name


# ── Values that live in a table rather than in the record ───────────────
#
# A seeded record does not have to spell its values inline, and a very common
# style in this file does not: the vocabulary sits in a table and the record is
# written from a loop over it.
#
#     punch_templates = [("Touch-up to finished surface", "low", "finishes"), ...]
#     for i, (title, prio, cat) in enumerate(punch_templates):
#         punchlist.append({"title": title, "priority": prio, "category": cat, ...})
#
# Read as constants only, that record is empty - every value is a name - so it
# falls under _MIN_SHARED_KEYS and is dropped. The scan never compared a single
# snag row against the punchlist vocabulary. It did not pass a bad value, it
# read no values at all, and the floors above cannot show that: one silent
# record among hundreds does not move a total. The gap was found from the
# outside, on a screen printing a raw category the module does not define.
#
# So a name is resolved to the column of the table it is bound to, and the field
# then carries the set of values that position can hold rather than a single
# value. The resolution is deliberately narrow: an enclosing ``for``, a target
# the name appears in, and an iterable that is a literal table or a name bound
# exactly once to one, in the same scope. Anything computed - a call, a
# comprehension, a name assigned in two places - resolves to nothing and the
# field is left out exactly as before. A guessed value would be reported against
# a module that never receives it, and a false accusation in a gate is worse
# than the blindness it replaces.
#
# One shape that looks covered and is not: a name assigned inside the loop body
# rather than bound by the loop. ``status = ("open", "in_progress",
# "resolved")[i % 3]`` sits two lines above the punch record, and the record
# reads the name, so the pool stays behind an assignment this does not follow
# and the field is dropped. Written inline in the record the same pool is read.
# Nothing hangs on it today, because punchlist states a status vocabulary only
# on its transition schema, but the limit is real and belongs written down next
# to the shape it resembles.


def _sequence_elements(node: ast.AST, bindings: dict[str, list[ast.expr]]) -> list[ast.expr] | None:
    """The elements of a literal list/tuple, following one level of name binding."""
    if isinstance(node, ast.List | ast.Tuple):
        return list(node.elts)
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    return None


def _target_path(target: ast.expr, name: str, prefix: tuple[int, ...] = ()) -> tuple[int, ...] | None:
    """Where ``name`` sits inside a loop target, as a path of tuple positions."""
    if isinstance(target, ast.Name):
        return prefix if target.id == name else None
    if isinstance(target, ast.Tuple | ast.List):
        for index, element in enumerate(target.elts):
            found = _target_path(element, name, (*prefix, index))
            if found is not None:
                return found
    return None


def _column(rows: list[ast.expr], path: tuple[int, ...]) -> frozenset[Any] | None:
    """Every constant a position of a literal table holds, or ``None``.

    All rows have to reach a constant at that position. A table with one
    computed row says nothing reliable about the column, and half a column is
    not a vocabulary.
    """
    values: set[Any] = set()
    for row in rows:
        node: ast.expr = row
        for index in path:
            elements = _sequence_elements(node, {})
            if elements is None or index >= len(elements):
                return None
            node = elements[index]
        if not isinstance(node, ast.Constant):
            return None
        values.add(node.value)
    return frozenset(values) or None


def _loop_binding(name: str, loops: list[ast.For], bindings: dict[str, list[ast.expr]]) -> frozenset[Any] | None:
    """The values ``name`` can hold, when an enclosing loop binds it to a table."""
    for loop in reversed(loops):
        path = _target_path(loop.target, name)
        if path is None:
            continue
        iterable: ast.expr = loop.iter
        # ``enumerate(table)`` binds (counter, row): drop the counter level. The
        # counter itself is an ordinal, not a seeded value, so a record reading
        # it resolves to nothing rather than to the row.
        if (
            isinstance(iterable, ast.Call)
            and isinstance(iterable.func, ast.Name)
            and iterable.func.id == "enumerate"
            and iterable.args
        ):
            if not path or path[0] != 1:
                return None
            path = path[1:]
            iterable = iterable.args[0]
        rows = _sequence_elements(iterable, bindings)
        return None if rows is None else _column(rows, path)
    return None


def _possible_values(
    node: ast.expr, loops: list[ast.For], bindings: dict[str, list[ast.expr]]
) -> tuple[Any] | frozenset[Any] | None:
    """What a record value can be: one constant, a set of them, or unknown.

    Returned wrapped so that ``None`` means "not readable" rather than "the
    literal None", which several seeded fields legitimately hold.
    """
    if isinstance(node, ast.Constant):
        return (node.value,)
    if isinstance(node, ast.Name):
        return _loop_binding(node.id, loops, bindings)
    # ``("open", "in_progress", "resolved")[i % 3]`` is the same pattern written
    # without a loop: a pool indexed by something derived. Which element is
    # taken does not matter, the field can hold any of them.
    if isinstance(node, ast.Subscript):
        elements = _sequence_elements(node.value, bindings)
        if not elements or not any(isinstance(element, ast.Constant) for element in elements):
            return None
        index = node.slice
        # A constant index takes one element and only that one. The pool is the
        # answer for a computed index, not for ``pool[0]``, and returning it
        # there would report values the seed never writes.
        if isinstance(index, ast.Constant) and isinstance(index.value, int):
            if not -len(elements) <= index.value < len(elements):
                return None
            picked = elements[index.value]
            return (picked.value,) if isinstance(picked, ast.Constant) else None
        if not all(isinstance(element, ast.Constant) for element in elements):
            return None
        return frozenset(element.value for element in elements)  # type: ignore[attr-defined]
    if isinstance(node, ast.IfExp):
        body = _possible_values(node.body, loops, bindings)
        orelse = _possible_values(node.orelse, loops, bindings)
        if body is None or orelse is None:
            return None
        return frozenset(body) | frozenset(orelse)
    return None


def _scope_bindings(scope: ast.AST) -> dict[str, list[ast.expr]]:
    """Names this scope binds exactly once, to a literal table.

    Scoped per function on purpose. Over a file this size the same short name is
    bound in a dozen functions, and a file-wide map would read one function's
    table through another function's name. A name stored more than once in the
    same scope is dropped whatever it was stored as, because which assignment
    reaches the record is a question about control flow that this cannot answer.
    """
    stored: dict[str, int] = {}
    literals: dict[str, list[ast.expr]] = {}
    for node in _scope_nodes(scope):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            stored[node.id] = stored.get(node.id, 0) + 1
        target, value = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if isinstance(target, ast.Name):
            elements = _sequence_elements(value, {}) if value is not None else None
            if elements is not None:
                literals[target.id] = elements
    return {name: elements for name, elements in literals.items() if stored.get(name) == 1}


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    """Every node in this scope, without descending into a nested scope."""
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


def _record_literals(path: Path) -> list[tuple[int, dict[str, Any], set[str]]]:
    """Every dict literal, as ``(line, readable values, every literal key)``.

    A value is a constant where the record spells one, and the set of constants
    a table column holds where the record reads one from a loop. Keys are always
    literal: a computed key is a shape this seeder does not use.

    The shape is returned separately because it answers a different question.
    Which schema a record belongs to is settled by the names it spells, while
    only the values that resolve can be judged. Attributing on the readable
    values alone discarded every record whose other fields are f-strings and
    calls, which is how a seeded submittal type outside the vocabulary reached
    every generated project with this gate green.
    """
    out: list[tuple[int, dict[str, Any], set[str]]] = []

    def visit(node: ast.AST, loops: list[ast.For], bindings: dict[str, list[ast.expr]]) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            bindings, loops = _scope_bindings(node), []
        elif isinstance(node, ast.Dict):
            record: dict[str, Any] = {}
            shape: set[str] = set()
            for key, value in zip(node.keys, node.values, strict=False):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                shape.add(key.value)
                resolved = _possible_values(value, loops, bindings)
                if resolved is not None:
                    record[key.value] = resolved[0] if isinstance(resolved, tuple) else resolved
            if len(shape) >= _MIN_SHARED_KEYS:
                out.append((node.lineno, record, shape))
        if isinstance(node, ast.For):
            # Only the body runs with the name bound. The iterable is evaluated
            # before the binding exists, so reading it through the loop would be
            # a name resolving to itself.
            visit(node.iter, loops, bindings)
            for child in [*node.body, *node.orelse]:
                visit(child, [*loops, node], bindings)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, loops, bindings)

    tree = ast.parse(path.read_text(encoding="utf-8"))
    visit(tree, [], _scope_bindings(tree))
    return out


def _attribute(
    keys: set[str],
    fields: dict[str, set[str]],
    constrained: dict[str, dict[str, tuple[str, set[str]]]],
) -> list[str]:
    """Every schema that covers this record's keys best, or an empty list.

    All of the tied schemas are returned rather than one of them. Ties are the
    normal case, not the exception: a module's Create, Update and Out schemas
    describe the same record and cover it equally well, and picking whichever
    sorted first would judge the record against a vocabulary chosen by
    alphabet. The caller only reports a value that every tied candidate
    refuses, which is an answer that does not depend on the tie being broken.

    Coverage picks a module; the vocabulary then comes from that module. Without
    the second step the winner can be a schema that states no vocabulary at all,
    and it shadows the siblings that do. That is not a tie, it is a strict win:
    a response model carries the stored fields, so it covers a seeded record
    more completely than the create model does, every time. The snag rows
    attributed to punchlist.PunchItemResponse at full coverage, that schema
    constrains nothing, and the record was dropped for having no constrained
    candidate - the same silence as never reading it. So when the best group
    states no vocabulary, the module's constrained schemas are admitted at their
    own coverage instead. Only that module's: a lower-covering schema from
    somewhere else is a different record, not a quieter reading of this one.
    """
    scored: list[tuple[float, str]] = []
    for name, schema_fields in fields.items():
        shared = len(keys & schema_fields)
        if shared < _MIN_SHARED_KEYS:
            continue
        score = shared / len(keys)
        if score >= _MIN_COVERAGE:
            scored.append((score, name))
    if not scored:
        return []
    best_score = max(score for score, _ in scored)
    best = [name for score, name in scored if score == best_score]
    if any(name in constrained for name in best):
        return best
    homes = {_home_module(name) for name in best}
    return [name for _, name in scored if name in constrained and _home_module(name) in homes]


@cache
def _scan() -> tuple[int, int, list[str]]:
    fields, constrained, unreadable = _module_schemas()
    broken = f"; {len(unreadable)} modules would not import: {' / '.join(unreadable)}" if unreadable else ""
    assert len(constrained) >= _MIN_SCHEMAS_WITH_VOCABULARY, (
        f"only {len(constrained)} schemas were found to state a vocabulary, "
        f"expected at least {_MIN_SCHEMAS_WITH_VOCABULARY}; the discovery has broken "
        f"and this check would pass without reading anything{broken}"
    )

    attributed = 0
    unresolved = 0
    problems: list[str] = []
    for source in _seed_sources():
        # A module's own seed.py seeds that module's records, so its schemas are
        # the only candidates. Without this, the forms starter templates matched
        # SkillCreate on name / category / description and were judged against a
        # document vocabulary they have nothing to do with. The core seeder is
        # not scoped, because it writes for every module at once.
        home = source.parent.name if source.name == "seed.py" else None
        visible = {n: f for n, f in fields.items() if home is None or _home_module(n) == home}
        for line, record, shape in _record_literals(source):
            candidates = [name for name in _attribute(shape, visible, constrained) if name in constrained]
            if not candidates:
                continue
            attributed += 1
            # Which fields any candidate constrains, and what each of them would
            # accept. A value is only reported when no candidate accepts it.
            vocabularies: dict[str, list[tuple[str, str, set[str]]]] = {}
            for name in candidates:
                for field, (module_name, allowed) in constrained[name].items():
                    vocabularies.setdefault(field, []).append((name, module_name, allowed))
            for field, claimants in vocabularies.items():
                if field not in record:
                    # The record spells this field and the value did not
                    # resolve. Counting it is the difference between a place
                    # that was checked and a place that was skipped, and a
                    # scan silent about the second reads as clean.
                    if field in shape:
                        unresolved += 1
                    continue
                held = record.get(field)
                # A field read out of a table holds every value that column can
                # hold, so each one is judged separately: a table is wrong the
                # moment one of its rows is, and reporting only the first would
                # send someone back for the rest one at a time.
                values = held if isinstance(held, frozenset) else {held}
                refused = sorted(
                    value
                    for value in values
                    if isinstance(value, str) and not any(value in allowed for _, _, allowed in claimants)
                )
                if not refused:
                    continue
                accepted = sorted({word for _, _, allowed in claimants for word in allowed})
                named = sorted({module_name for _, module_name, _ in claimants})
                problems.append(
                    f"{_where(source)}:{line} seeds {field}={'/'.join(refused)}, but {'/'.join(named)} "
                    f"accepts only {'|'.join(accepted)} (matched {', '.join(sorted(candidates))})"
                )
    return attributed, unresolved, problems


def test_no_seeded_record_holds_a_value_its_module_refuses() -> None:
    attributed, unresolved, problems = _scan()
    print(f"seed scan: {attributed} records attributed, {unresolved} vocabulary fields unresolved")
    assert attributed >= _MIN_ATTRIBUTED_RECORDS, (
        f"only {attributed} seeded records could be attributed to a schema, expected at "
        f"least {_MIN_ATTRIBUTED_RECORDS}; a scan that compares nothing reports clean"
    )
    assert not problems, (
        f"seeded values the owning module would refuse ({unresolved} more could not be read):\n  "
        + "\n  ".join(problems)
    )


def test_the_scan_says_how_much_it_could_not_read() -> None:
    """A scan silent about what it skipped reads as a scan that found nothing wrong.

    The seeded method statement sat behind exactly that silence: the record that
    held it was dropped for having too few readable values, and nothing said so.
    """
    _attributed, unresolved, _problems = _scan()
    assert unresolved <= _MAX_UNRESOLVED_FIELDS, (
        f"{unresolved} seeded vocabulary fields could not be read, over the {_MAX_UNRESOLVED_FIELDS} "
        f"this file records; the scan is judging less of the seed than it used to"
    )


def test_the_scan_would_notice_a_refused_value() -> None:
    """The green run above has to mean the seed is right, not that nothing is read.

    A synthetic record is pushed through the same attribution and comparison the
    scan uses. If this stops failing, the check above has stopped checking.
    """
    fields, constrained, _ = _module_schemas()
    record = {
        "code": "X",
        "title": "X",
        "contract_type": "lump_sum",
        "counterparty_type": "contractor",
        "project_id": "X",
    }
    candidates = [
        name
        for name in _attribute(set(record), fields, constrained)
        if "counterparty_type" in constrained.get(name, {})
    ]
    assert candidates, "the sample record no longer attributes to any schema that owns counterparty_type"
    for name in candidates:
        allowed = constrained[name]["counterparty_type"][1]
        assert "contractor" not in allowed, (
            f"{name} now accepts 'contractor', so this sample no longer demonstrates a refusal"
        )
