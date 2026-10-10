#!/usr/bin/env python3
"""Report migrations whose upgrade() rewrites rows in a table it did not create.

Grew out of #126: a migration that filled a pre-existing 1724 MB table inside
the single transaction Alembic wraps a whole upgrade() run in died with
DiskFull on a real box, because Postgres keeps every superseded row version
until the transaction commits, so peak disk was roughly twice the table no
matter how the writes were batched. That class of migration - one whose
upgrade() issues INSERT/UPDATE/DELETE against a table that already held rows
before this revision ran - has a disk profile worth a human look before it
ships, whether or not the specific revision turns out to be safe. Creating a
table and filling it in the same revision is a different case: the table is
empty until this revision runs, so there is no pre-existing data to make a
transaction-sized copy of, and that shape is not flagged.

Blocking, in Repo hygiene (a static check over source text, not a database
test - see .github/workflows/repo-hygiene.yml). A flagged revision ships
only if its own file carries a ``# data-rewrite-ack:`` comment for every
table it touches; see "Acknowledging a flagged revision" below. The 24
revisions flagged on the tree the day this went blocking (2026-08-12)
already carry one each. See the summary line for scale: N revisions
scanned, M flagged into how many statements, and how many statements this
could not classify at all (printed separately; a new one not already in
_UNRESOLVED_BASELINE blocks on its own terms, and neither bucket is ever
silently treated as clean). The scan running at all gets the same
treatment: a versions/ directory that resolves but comes back near-empty
reports "clean" for the same reason a passing test suite with zero tests
does, so paths below _MIN_EXPECTED_REVISIONS fails loud in main() instead.
That check exists because of a sibling instrument making the opposite
mistake: .github/workflows/desktop-release.yml's Windows signing job
exits 0 and writes a $GITHUB_STEP_SUMMARY line plus a ::warning when
its signing secrets are unset, so every release so far has shipped
unsigned installers under a job the run's conclusion field reports as
success, indistinguishable there from a job that signed anything. This
script's own summary line is read by whatever reads a conclusion field,
so it does not get to make that same substitution about its own input.

Known gap in that floor: it catches zero and near-zero, not a
proportional shrink. A reorganisation that splits versions/ into
subfolders and moves, say, half the files would leave the flat glob
below counting only the half left behind - comfortably above 100,
reporting clean over a scan that covered less than the whole tree. A
fixed floor also decays by construction: 100 was chosen against a tree
of 320 files, so it currently requires seeing at least 31% of them, and
against 600 files next year the same constant requires seeing only 17%.
Cross-checking the glob's count against a second, independent
enumeration of the same directory was considered and rejected - Alembic's
own ScriptDirectory discovers revisions by walking that same versions/
path under the same single-directory assumption, so a subfolder split
that fools the glob below would fool Alembic's own view of its
migration tree the same way, and by then CI would presumably be red on
far more than this one script. Naming the gap here is the honest
alternative to a cross-check that could not actually be independent of
the failure mode it exists to catch.

Why AST, not grep or ScriptDirectory.walk_revisions()
------------------------------------------------------
Grep looks for a literal table name next to a literal verb and this codebase
does not write SQL that way: every migration builds its raw SQL as an
f-string over a module-level constant (UPDATE {_ITEM} SET ... with
_ITEM = "oe_costs_item" twenty lines above). A sweep for UPDATE followed by
oe_ misses every one of them and returns a confident, wrong zero.

ScriptDirectory.walk_revisions() imports every migration module to build the
chain, and importing v3121 demands a live DATABASE_URL at collection time.
That would make invoking this script depend on a database being up, so
revisions are read as source text and parsed with ast instead - the same
approach backend/tests/integration/test_migrations_roundtrip.py uses for the
same reason, kept independent here rather than imported so this script
carries no pytest or psycopg2 dependency.

Resolution and confidence tiers
--------------------------------
A table name reaches a SQL string several ways in this codebase, in
increasing order of how much has to be inferred to name it:

* literal - a plain string, or a chain of simple NAME = "value" indirections
  (including through sa.text(...), sa.table(...) / sa.Table(...), and
  .bindparams(...), all transparent wrappers for this purpose), with no
  loop or function call standing between the constant and its use.
* derived - the name came from unpacking a module-level literal collection
  in a for loop (e.g. a table name that is the first element of each tuple
  in a list this revision iterates), or passed through a single-argument
  helper call this script cannot inspect the body of and therefore assumes
  is a pass-through (e.g. an identifier-validation helper that returns its
  argument unchanged or raises). Both are real answers, not guesses about
  intent, but resting on an assumption this script did not verify by
  reading the helper.
* unresolved - this script could not determine the SQL text, or could not
  determine the table a resolved statement targets, at all. Listed
  separately from confirmed findings rather than dropped, because a
  statement this script cannot read is not evidence of anything either way.
  In the corpus this scan was built against, most of these are DDL - a
  dialect-conditional CREATE INDEX CONCURRENTLY or an ALTER TABLE ADD
  CONSTRAINT whose index or constraint name comes from a value this script
  cannot pin down - where the verb itself is plainly not UPDATE/INSERT/
  DELETE/MERGE but the rest of the statement never resolves far enough to
  say so on the record; the remainder is a Core select(...).where(...) read
  built from more than one comparison and a bare SELECT setval(...) that
  advances a sequence rather than writing a table row, neither a
  data-modifying statement to begin with. None of these found a write; they
  show up here because this script does not model boolean expressions or
  chase every non-DML verb, not because a write went unseen. A statement
  landing here is never required to carry an acknowledgement - there is no
  table to name growth for until this script can name the table - but its
  identity, (filename, ast.unparse() of the call), is checked against
  _UNRESOLVED_BASELINE and a statement whose identity is new blocks the
  run; see that constant for the current eight and what to do about a
  ninth.

Known blind spots, deliberately not covered
---------------------------------------------
An ALTER COLUMN ... TYPE change (batch or plain) can rewrite every row of a
pre-existing table on PostgreSQL to re-encode the column, which is the same
disk-profile class this script exists to flag - but it is a schema
statement, not a data-modifying one, and the rule as specified is about
statements that modify data. 7f3ab0f2d4e1_phase2e_money_numeric.py is a real
example on the current tree. Naming it here rather than folding it into this
rule, which would require a different detector (schema-op scan, not DML-op
scan) and a different, harder to state safety condition.

A table name arriving as a function parameter, rather than a module-level
constant, a for-loop target, or a locally reassigned literal, is invisible
to this script's scope model and so cannot reach ``created``. Five files on
the current tree share an ``_create_if_not_exists(table_name, *columns,
**kw)`` helper with exactly this shape (a1b2c3d4e5f6_add_collab_lock_table.py,
f22fa2934807_add_bim_element_group_table.py,
ffe3f561e2c1_add_documents_bim_link_table.py, v090_add_all_new_modules.py,
v191_dwg_entity_groups.py) - none of them issue any DML at all, so this is
a latent gap rather than a live false positive today, but a future revision
that both creates a table this way and writes to it in the same upgrade()
would be flagged as touching pre-existing data when it does not. Extending
the scope model to bind a called function's parameters from the literal
arguments a call site passes would close this without weakening anything
else, and is future work rather than something this revision of the script
attempts.

Acknowledging a flagged revision
---------------------------------
A flagged revision ships only if its own source carries one line per table
it touches, in this exact shape::

    # data-rewrite-ack: table=oe_costs_item growth=tenure rows=core cost-estimation line items across every project; already 1724 MB in the field, see #126

Three fields, all required. ``table=`` is the table this acknowledges - a
finding whose table has no matching line still blocks. ``growth=`` is
``tenure`` if the row count tracks operational history (a row per
transaction, per day, per measurement, per entry - the table keeps growing
for as long as a customer keeps using the product), ``bounded`` if it
tracks a catalogue or configuration instead (it is what it is, regardless
of how long the install has run), or ``dead-code`` for the one shape that
is neither: a statement this script found that provably cannot execute,
e.g. guarded by a check against a table name that has never existed - see
v3145_demo_project_addresses.py, the only case on this tree today, and read
its comment above ``upgrade()`` before assuming a second one is the same
shape. ``dead-code`` is the one value that asserts something about the
code rather than about the data, and code changes under a repair in a way
a table's growth class does not: the day someone fixes the guard, the
statement goes live, and an ack that still reads dead-code would be a
live rewrite wearing a never-runs label - the worst object this gate
could produce. So a dead-code ``rows=`` must also carry an issue
reference (``#NNN``) naming the guard - see v3145's line - putting the
repair and the stale claim in the same diff a future reviewer reads.
``rows=`` is otherwise a free-text estimate of row count on a mature
install.

Keyed on (revision, table), not on revision alone: one revision touching
several tables needs one line per table (v3033_audit_log.py touches four -
oe_finance_invoice, oe_ncr_ncr, oe_rfq_rfq, oe_submittals_submittal), because
growth class is a property of the table, not of the migration, and a single
label across all of them would hide exactly the distinction that matters.
The comment can sit anywhere in the file - this is a plain text scan, not
part of the ast walk above, because the requirement is that the revision
carries an acknowledgement for each table, not that one specific line does,
and this codebase's flagged statements are sometimes reached through a
helper several lines from anything a line-anchored scan could find.

This grew out of #126: v3273_backfill_cost_item_currency.py rewrote
oe_costs_item, 1724 MB in the field, inside the single transaction Alembic
wraps a whole upgrade() in, and died with DiskFull on a real box. The
danger was never the UPDATE by itself - it was writing to a table whose
size nobody had checked first. A megabyte figure measured on a demo
database cannot answer whether a table will be large on a customer box
three years in, because oe_costs_item was small on a fresh demo too, before
years of real projects filled it; only a table's growth class can answer
that, which is why the acknowledgement asks for growth class rather than
for a size measured somewhere that cannot see a mature install. Five tables
on this tree are the worked example of the shape that bites hardest:
oe_field_diary_entry, oe_progress_entry, oe_payroll_entry /
oe_payroll_batch, oe_takeoff_measurement (with oe_ai_takeoff_run and
oe_takeoff_document), and oe_boq_position - each small wherever it has only
been measured on a fresh install, and each the kind of table that
accumulates one row per real-world event for as long as a customer keeps
using the product, exactly the way oe_costs_item did.

An acknowledgement is deliberately not a size and not a bare marker: a
number pulled from nowhere - or measured on a demo box that cannot have
lived through the tenure that matters - is worse than useless, and a token
with no content is a rubber stamp within a month. Writing the three fields
honestly is the actual review a flagged revision has to pass: a human who
has never seen a customer's database can still say whether a table is a
log of something that keeps happening, or a catalogue that is what it is,
without needing to know a row count nobody watching a demo box could give
them.

Usage:

    python scripts/check_migration_data_rewrites.py
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = REPO_ROOT / "backend" / "alembic" / "versions"

_DML_RE = re.compile(
    r'^\s*(UPDATE|INSERT\s+INTO|DELETE\s+FROM|MERGE\s+INTO)\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
    re.IGNORECASE,
)
_VERB_TO_KIND = {
    "UPDATE": "UPDATE",
    "INSERT INTO": "INSERT",
    "DELETE FROM": "DELETE",
    "MERGE INTO": "MERGE",
}

_TRANSPARENT_CALL_NAMES = {"text", "table", "Table"}
_TRANSPARENT_METHODS = {"bindparams"}
_DML_METHODS = {"insert", "update", "delete"}

_CONFIDENCE_ORDER = {"literal": 0, "derived": 1, "unresolved": 2}

# See "Acknowledging a flagged revision" in the module docstring for the
# full shape and worked example.
_ACK_RE = re.compile(
    r"#\s*data-rewrite-ack:\s*table=(\S+)\s+growth=(tenure|bounded|dead-code)\s+rows=(.+?)\s*$",
    re.IGNORECASE,
)

# The unresolved bucket the day this gate went blocking (2026-08-12), keyed
# by identity - (filename, ast.unparse() of the call) - not by a bare
# count. A count is a one-bit hash of a set already in hand: it catches
# growth in the total but not a same-day swap (one of these resolved by a
# parser fix, replaced by one new unsafe statement, count unchanged).
# Line numbers are deliberately not part of the identity - they churn on
# any reformat that does not touch the statement itself, and
# ast.unparse() already does not.
#
# Every entry below was read by hand and confirmed non-DML: a dialect-
# conditional CREATE INDEX CONCURRENTLY or ALTER TABLE ADD CONSTRAINT
# whose name does not resolve, a Core select().where() read, a SELECT
# setval() sequence bump, and the ALTER COLUMN ... TYPE change named in
# "Known blind spots" above. 9 statements resolve to 8 identities -
# v3123_boq_fk_indexes.py has two CREATE INDEX IF NOT EXISTS statements
# whose table/column names are loop-derived, not literal, so ast.unparse()
# sees the same template text for both; the set collapses them to one
# identity, and a third, unrelated statement sharing that exact text
# would be exactly as safe as the two already here, by the same reasoning.
#
# Finding a ninth: read it by hand. If it is non-DML like every entry
# here, add its (filename, ast.unparse(node)) identity below with a
# one-line reason. If it touches a pre-existing table, that is the
# finding this whole script exists to surface - improve resolution above
# so it becomes a real Finding with a table name, or escalate for manual
# review before this ships; do not add it here just to make the run pass.
_UNRESOLVED_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        (
            "7f3ab0f2d4e1_phase2e_money_numeric.py",
            "op.execute(f\"ALTER TABLE {table} ALTER COLUMN {column} TYPE NUMERIC({precision}, {scale}) USING NULLIF({column}, '')::NUMERIC({precision}, {scale})\")",
        ),
        (
            "v261_eac_alias_catalog_seed.py",
            "bind.execute(sa.select(alias_meta.c.id).where(alias_meta.c.scope == 'org', alias_meta.c.scope_id.is_(None), alias_meta.c.name == name))",
        ),
        (
            "v3123_boq_fk_indexes.py",
            "op.execute(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table} ({col_list})')",
        ),
        (
            "v3123_boq_fk_indexes.py",
            "op.execute(f'CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({col_list})')",
        ),
        (
            "v3124_propdev_analytics_indexes.py",
            "op.execute(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table} ({col_list})')",
        ),
        (
            "v3124_propdev_analytics_indexes.py",
            "op.execute(f'CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({col_list})')",
        ),
        (
            "v3258_progress_entry_seq.py",
            "op.execute(sa.text(f\"SELECT setval('{_SEQUENCE}', {int(next_value)}, false)\"))",
        ),
        (
            "v3267_saved_views_team_share.py",
            "op.execute(sa.text(f'ALTER TABLE {table} ADD CONSTRAINT \"{name}\" CHECK ({condition})'))",
        ),
    }
)

# 320 revisions exist on the tree the day this was written (2026-08-12).
# This floor is well under that so ordinary growth of the migration tree
# never trips it, and well over what a shallow checkout, a moved
# directory, or a future refactor into subfolders the glob below stops
# matching would leave behind - see the module docstring for why that
# failure mode gets its own check rather than being left to read as
# "nothing to flag".
_MIN_EXPECTED_REVISIONS = 100


@dataclass(frozen=True)
class Resolved:
    """A resolved SQL/table name expression: the set of strings it could be.

    ``values is None`` means "could not resolve at all". A non-None,
    possibly multi-element set covers loop-derived values that vary per
    iteration (e.g. a table name that differs by which tuple in a constant
    list produced it).
    """

    values: frozenset[str] | None
    confidence: str  # "literal" | "derived" | "unresolved"
    #: Set only when full resolution failed but the value's own source
    #: expression had a leading segment - literal text, optionally followed
    #: by a placeholder that itself resolves to exactly one string, e.g. the
    #: table name in ``f"UPDATE {_TABLE} SET {expr}"`` - that alone
    #: completed a DML verb + table (see ``_classify_prefix``). Lets a later
    #: ``Name`` lookup (``sql = sa.text(f"...")`` then
    #: ``conn.execute(sql, ...)``) recover a finding that a bare scope
    #: lookup on the Name would otherwise lose.
    prefix: tuple[str, str, str] | None = None


UNRESOLVED = Resolved(None, "unresolved")


def _literal(value: str) -> Resolved:
    return Resolved(frozenset({value}), "literal")


def _combine_confidence(a: str, b: str) -> str:
    return a if _CONFIDENCE_ORDER[a] >= _CONFIDENCE_ORDER[b] else b


def _parse_acknowledgements(source: str) -> dict[str, tuple[str, str]]:
    """table -> (growth_class, rows_estimate) for every data-rewrite-ack
    comment in this revision's own source text.

    A plain text scan, not part of the ast walk the rest of this script
    does - comments are invisible to ast by design, and the requirement is
    that the revision carries an acknowledgement for each table it touches,
    not that one specific line does."""
    acks: dict[str, tuple[str, str]] = {}
    for line in source.splitlines():
        m = _ACK_RE.search(line)
        if m:
            table, growth, rows = m.group(1), m.group(2).lower(), m.group(3).strip()
            acks[table] = (growth, rows)
    return acks


_ISSUE_REF_RE = re.compile(r"#\d+")


def _ack_problem(growth: str, rows: str) -> str | None:
    """None if this acknowledgement is well-formed, else a short reason
    why it is not. The one rule so far: growth=dead-code must name an
    issue in rows=. See "Acknowledging a flagged revision" above for why -
    in short, dead-code claims something about the code, not the data,
    and code changes under a repair in a way a table's growth class does
    not."""
    if growth == "dead-code" and not _ISSUE_REF_RE.search(rows):
        return "growth=dead-code carries no issue reference (e.g. #144) in rows="
    return None


def _call_func_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def resolve_expr(node: ast.expr, scope: dict[str, Resolved]) -> Resolved:
    """Best-effort static resolution of ``node`` to the string(s) it can be.

    Handles the shapes this codebase's migrations actually use: literal
    strings, f-strings over names already in ``scope``, bare names, and the
    handful of call shapes covered by ``_resolve_call``. Anything else comes
    back UNRESOLVED rather than guessed at.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _literal(node.value)
    if isinstance(node, ast.Name):
        return scope.get(node.id, UNRESOLVED)
    if isinstance(node, ast.JoinedStr):
        return _resolve_joined(node, scope)
    if isinstance(node, ast.Call):
        return _resolve_call(node, scope)
    return UNRESOLVED


def _resolve_joined(node: ast.JoinedStr, scope: dict[str, Resolved]) -> Resolved:
    parts: frozenset[str] = frozenset({""})
    confidence = "literal"
    for value_node in node.values:
        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
            seg = frozenset({value_node.value})
        elif isinstance(value_node, ast.FormattedValue):
            resolved = resolve_expr(value_node.value, scope)
            if resolved.values is None:
                return UNRESOLVED
            seg = resolved.values
            confidence = _combine_confidence(confidence, resolved.confidence)
        else:
            return UNRESOLVED
        if len(parts) * len(seg) > 200:
            # A blow-up here means this f-string combines several
            # loop-derived placeholders at once. Nothing in the corpus this
            # was built against does that; bail to unresolved rather than
            # build a combinatorial table set nobody asked for.
            return UNRESOLVED
        parts = frozenset(p + s for p in parts for s in seg)
    return Resolved(parts, confidence)


def _resolve_call(node: ast.Call, scope: dict[str, Resolved]) -> Resolved:
    name = _call_func_name(node.func)
    if name in _TRANSPARENT_CALL_NAMES and node.args:
        return resolve_expr(node.args[0], scope)
    # Heuristic: a call with exactly one positional argument and no keyword
    # arguments is assumed to be a pass-through (e.g. an identifier
    # validator that returns its argument unchanged or raises). This is an
    # assumption, not a fact this script verified - callers get "derived",
    # never "literal", from it.
    if len(node.args) == 1 and not node.keywords and not isinstance(node.args[0], ast.Starred):
        inner = resolve_expr(node.args[0], scope)
        if inner.values is None:
            return UNRESOLVED
        return Resolved(inner.values, "derived")
    return UNRESOLVED


def _merge(scope: dict[str, Resolved], name: str, resolved: Resolved) -> None:
    """Rebind ``name``, replacing any previous binding.

    Matches ordinary Python assignment semantics (last write wins): a
    second ``for`` loop reusing an earlier loop's target name replaces
    that binding rather than merging with it, and a name bound inside one
    branch of an if/elif/else is visible to code after the whole
    statement, because nothing in this codebase's compound statements
    gets its own block scope - matching Python, which does not have one
    either. An earlier version of this script instead unioned every
    rebinding of the same name together, which produced a concrete false
    positive on v3033_audit_log.py: two unrelated for loops both used
    ``table`` as their loop variable, and the union made the first
    loop's UPDATE look like it also touched the second loop's tables.
    """
    scope[name] = resolved


def _module_scope(tree: ast.Module) -> tuple[dict[str, Resolved], dict[str, object]]:
    """Two views of every module-level assignment.

    ``str_scope`` resolves names the same way ``resolve_expr`` would resolve
    a use of them. ``literal_values`` is the actual Python value via
    ``ast.literal_eval`` where that succeeds (lists of tuples, mostly),
    needed to unpack ``for x, y in SOME_CONSTANT:`` loops later - a string
    resolution alone cannot say what the second element of each tuple was.
    """
    str_scope: dict[str, Resolved] = {}
    literal_values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        else:
            continue
        if value is None:
            continue
        _merge(str_scope, target, resolve_expr(value, str_scope))
        try:
            literal_values[target] = ast.literal_eval(value)
        except (ValueError, TypeError):
            pass
    return str_scope, literal_values


def _bind_for_target(stmt: ast.For, scope: dict[str, Resolved], module_literals: dict[str, object]) -> None:
    """Extend ``scope`` with what a ``for`` loop's target(s) can be.

    Only handles iterating a module-level literal list/tuple (by far the
    common case here: a frozen table of (table, column, ...) rows). Anything
    else - iterating a runtime query result, a dict's .items(), a
    dynamically built list - is left unbound, which is correct: a later use
    of that name simply falls through to "not in scope" and is reported as
    unresolved rather than guessed at.
    """
    iterable: object = None
    if isinstance(stmt.iter, ast.Name) and stmt.iter.id in module_literals:
        iterable = module_literals[stmt.iter.id]
    else:
        try:
            iterable = ast.literal_eval(stmt.iter)
        except (ValueError, TypeError):
            iterable = None
    if not isinstance(iterable, (list, tuple)):
        return

    target = stmt.target
    if isinstance(target, ast.Name):
        values = {item for item in iterable if isinstance(item, str)}
        if values:
            _merge(scope, target.id, Resolved(frozenset(values), "derived"))
    elif isinstance(target, ast.Tuple):
        for idx, elt in enumerate(target.elts):
            if not isinstance(elt, ast.Name):
                continue
            values = {
                item[idx]
                for item in iterable
                if isinstance(item, (tuple, list)) and idx < len(item) and isinstance(item[idx], str)
            }
            if values:
                _merge(scope, elt.id, Resolved(frozenset(values), "derived"))


def _local_function_defs(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _called_local_names(func: ast.FunctionDef) -> set[str]:
    return {node.func.id for node in ast.walk(func) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def _reachable_from_upgrade(tree: ast.Module) -> list[ast.FunctionDef]:
    """``upgrade()`` plus every module-level helper it calls, transitively.

    The rule is about what upgrade() does, but what it does is often written
    one call away: v3273_backfill_cost_item_currency's actual UPDATE
    statements live in _fill_chunked / _fill_in_transaction, called from
    upgrade() rather than inlined in it. Scanning only upgrade()'s own AST
    body would miss every one of them. Starting a reachability walk from
    upgrade and stopping at module-level, bare-name calls keeps this from
    also pulling in downgrade()'s own helpers, per the rule as specified
    ("its upgrade()").
    """
    defs = _local_function_defs(tree)
    if "upgrade" not in defs:
        return []
    seen: set[str] = set()
    order: list[ast.FunctionDef] = []
    stack = ["upgrade"]
    while stack:
        name = stack.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        func = defs[name]
        order.append(func)
        stack.extend(_called_local_names(func) - seen)
    return order


@dataclass(frozen=True)
class Statement:
    lineno: int
    kind: str
    tables: frozenset[str]
    confidence: str
    #: ast.unparse() of the statement's own call node. A fingerprint, not
    #: source: it renormalises whitespace and quoting, so it is identical
    #: before and after a reformat that does not touch this statement, and
    #: it changes when the statement itself changes, unlike lineno.
    text: str


def _find_dml_chain_table(node: ast.expr, scope: dict[str, Resolved]) -> tuple[str, Resolved] | None:
    """If ``node`` contains a Core .insert()/.update()/.delete() call
    anywhere in it, resolve the table it was called on."""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr in _DML_METHODS:
            return inner.func.attr.upper(), resolve_expr(inner.func.value, scope)
    return None


def _unwrap_transparent_methods(node: ast.expr) -> ast.expr:
    while (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _TRANSPARENT_METHODS
    ):
        node = node.func.value
    return node


def _classify_sql_text(resolved: Resolved) -> tuple[str, frozenset[str]] | None:
    """``(kind, {table, ...})`` if every resolvable string is a DML statement.

    ``None`` if the resolved text plainly is not DML (a SELECT, a SET, a
    VACUUM, DDL) - which is a real answer, not a failure to resolve.
    """
    if resolved.values is None:
        return None
    kinds: set[str] = set()
    tables: set[str] = set()
    for text in resolved.values:
        m = _DML_RE.match(text)
        if not m:
            continue
        verb = re.sub(r"\s+", " ", m.group(1).upper())
        kinds.add(_VERB_TO_KIND[verb])
        tables.add(m.group(2))
    if not tables:
        return None
    return "/".join(sorted(kinds)), frozenset(tables)


def _unwrap_to_string_node(node: ast.expr) -> ast.expr:
    """Peel .bindparams(...) and sa.text(...)/text(...)/sa.table(...) call
    wrappers down to whatever string-shaped node they wrap, for the prefix
    fallback below. Not a full resolve - just enough to reach a literal or
    f-string sitting directly under a couple of known-transparent calls."""
    node = _unwrap_transparent_methods(node)
    while isinstance(node, ast.Call):
        name = _call_func_name(node.func)
        if name in _TRANSPARENT_CALL_NAMES and node.args:
            node = _unwrap_transparent_methods(node.args[0])
        else:
            break
    return node


def _classify_prefix(node: ast.expr, scope: dict[str, Resolved]) -> tuple[str, str, str] | None:
    """Classify using a SQL string's leading, fully-pinned-down segment.

    Fallback for when full resolution fails because some placeholder later
    in a long f-string cannot be resolved - typically an INSERT ... SELECT
    whose SELECT list builds derived column expressions this script does
    not model, or a WHERE clause built from a module constant this script
    does not evaluate (e.g. ``_quoted(SOME_TUPLE)`` for an IN-list). Builds
    up a prefix by concatenating literal text and any placeholder that
    itself resolves to exactly one string - covering both the table name
    sitting directly in the literal text (``f"UPDATE {table} SET ..."``
    where ``table`` fails to resolve later) and the table name arriving as
    its own placeholder right after the verb (``f"UPDATE {_TABLE} SET
    {expr}"`` where ``_TABLE`` is a resolvable module constant and ``expr``
    is not) - and stops at the first segment it cannot pin down to exactly
    one value. SQL syntax puts the verb and the table right after it, so
    whatever prefix this accumulates either contains a complete verb+table
    pair or does not contain a full identifier at all; there is no way for
    this to see a verb+table pair that is not really there.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        leading = node.value
        confidence = "literal"
    elif isinstance(node, ast.JoinedStr):
        leading = ""
        confidence = "literal"
        for value_node in node.values:
            if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                leading += value_node.value
                continue
            if isinstance(value_node, ast.FormattedValue):
                resolved = resolve_expr(value_node.value, scope)
                if resolved.values is not None and len(resolved.values) == 1:
                    leading += next(iter(resolved.values))
                    confidence = _combine_confidence(confidence, resolved.confidence)
                    continue
            break
        if not leading:
            return None
    else:
        return None
    m = _DML_RE.match(leading)
    if not m:
        return None
    verb = re.sub(r"\s+", " ", m.group(1).upper())
    return _VERB_TO_KIND[verb], m.group(2), confidence


def _statement_own_exprs(stmt: ast.stmt) -> list[ast.expr]:
    """Expressions belonging to ``stmt`` itself, not to a nested block.

    Used to scan a statement for create_table / execute / bulk_insert calls
    without also re-walking a nested for/if/with/try body - that body is
    scanned separately, with its own (possibly extended) scope.
    """
    if isinstance(stmt, (ast.Assign, ast.AugAssign)):
        return [stmt.value]
    if isinstance(stmt, ast.AnnAssign):
        return [stmt.value] if stmt.value is not None else []
    if isinstance(stmt, ast.Expr):
        return [stmt.value]
    if isinstance(stmt, ast.Return):
        return [stmt.value] if stmt.value is not None else []
    if isinstance(stmt, ast.For):
        return [stmt.iter]
    if isinstance(stmt, (ast.If, ast.While)):
        return [stmt.test]
    if isinstance(stmt, ast.With):
        return [item.context_expr for item in stmt.items]
    return []


def _handle_call(
    node: ast.Call,
    scope: dict[str, Resolved],
    created: set[str],
    statements: list[Statement],
) -> None:
    name = _call_func_name(node.func)

    if name == "create_table" and node.args:
        resolved = resolve_expr(node.args[0], scope)
        if resolved.values:
            created.update(resolved.values)
        return

    if name == "bulk_insert" and node.args:
        resolved = resolve_expr(node.args[0], scope)
        if resolved.values:
            statements.append(
                Statement(
                    node.lineno,
                    "INSERT(bulk)",
                    resolved.values,
                    resolved.confidence,
                    ast.unparse(node),
                )
            )
        else:
            statements.append(
                Statement(
                    node.lineno,
                    "INSERT(bulk)",
                    frozenset(),
                    "unresolved",
                    ast.unparse(node),
                )
            )
        return

    if name != "execute":
        return
    arg = node.args[0] if node.args else None
    if arg is None:
        for kw in node.keywords:
            if kw.arg == "statement":
                arg = kw.value
        if arg is None:
            return

    chain = _find_dml_chain_table(arg, scope)
    if chain is not None:
        kind, receiver = chain
        statements.append(
            Statement(
                node.lineno,
                kind,
                receiver.values or frozenset(),
                receiver.confidence,
                ast.unparse(node),
            )
        )
        return

    text_resolved = resolve_expr(_unwrap_transparent_methods(arg), scope)
    classified = _classify_sql_text(text_resolved)
    if classified is not None:
        kind, tables = classified
        statements.append(Statement(node.lineno, kind, tables, text_resolved.confidence, ast.unparse(node)))
        return
    if text_resolved.values is not None:
        # Resolved text, just not a DML verb (SELECT/SET/VACUUM/...) - nothing to record.
        return

    # Full resolution failed - a placeholder somewhere in the string could
    # not be pinned down, often a derived column expression later in an
    # INSERT ... SELECT. Try the leading prefix alone: SQL syntax puts the
    # verb and table right after it, so if that much is already pinned
    # down - literal text, or literal text plus one placeholder that
    # resolves to a single value - this is still a real finding.
    prefix = _classify_prefix(_unwrap_to_string_node(arg), scope) or text_resolved.prefix
    if prefix is not None:
        kind, table, confidence = prefix
        statements.append(Statement(node.lineno, kind, frozenset({table}), confidence, ast.unparse(node)))
    else:
        statements.append(
            Statement(
                node.lineno,
                "execute(...)",
                frozenset(),
                "unresolved",
                ast.unparse(node),
            )
        )


def _scan_calls_in(
    expr: ast.expr,
    scope: dict[str, Resolved],
    created: set[str],
    statements: list[Statement],
) -> None:
    for node in ast.walk(expr):
        if isinstance(node, ast.Call):
            _handle_call(node, scope, created, statements)


def _scan_body(
    stmts: list[ast.stmt],
    scope: dict[str, Resolved],
    module_literals: dict[str, object],
    created: set[str],
    statements: list[Statement],
) -> None:
    """Walk a statement list in source order, threading name bindings and
    finding create_table / execute / bulk_insert calls in the same pass.

    One mutable scope dict flows through the whole function, mutated in
    place as each binding statement is reached - matching Python, which has
    no per-if/per-for/per-with block scoping: a name bound inside one
    branch of an if/elif/else, or inside a for loop's body, stays bound for
    whatever comes after that statement. ``_merge`` (really a rebind: last
    write wins) is what makes this correct rather than an over-union - see
    its docstring for the v3033_audit_log.py case that motivated it: two
    unrelated for loops there reuse ``table`` as their loop variable, and a
    second loop's ``for ... table in ...:`` must replace the first loop's
    binding, not add to it, for the first loop's own call site to keep
    reporting only its own tables.
    """
    for stmt in stmts:
        for expr in _statement_own_exprs(stmt):
            _scan_calls_in(expr, scope, created, statements)

        if isinstance(stmt, ast.For):
            _bind_for_target(stmt, scope, module_literals)
            _scan_body(stmt.body, scope, module_literals, created, statements)
            _scan_body(stmt.orelse, scope, module_literals, created, statements)
        elif isinstance(stmt, (ast.If, ast.While)):
            _scan_body(stmt.body, scope, module_literals, created, statements)
            _scan_body(stmt.orelse, scope, module_literals, created, statements)
        elif isinstance(stmt, ast.With):
            _scan_body(stmt.body, scope, module_literals, created, statements)
        elif isinstance(stmt, ast.Try):
            _scan_body(stmt.body, scope, module_literals, created, statements)
            for handler in stmt.handlers:
                _scan_body(handler.body, scope, module_literals, created, statements)
            _scan_body(stmt.orelse, scope, module_literals, created, statements)
            _scan_body(stmt.finalbody, scope, module_literals, created, statements)
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            resolved = resolve_expr(stmt.value, scope)
            if resolved.values is None:
                prefix = _classify_prefix(_unwrap_to_string_node(stmt.value), scope)
                if prefix is not None:
                    resolved = Resolved(None, "unresolved", prefix=prefix)
            _merge(scope, stmt.targets[0].id, resolved)
        # Other statement kinds neither bind names this script tracks nor
        # need recursion beyond the _statement_own_exprs scan above.


def _scan_revision(tree: ast.Module) -> tuple[frozenset[str], list[Statement]]:
    module_scope, module_literals = _module_scope(tree)
    created: set[str] = set()
    statements: list[Statement] = []
    for func in _reachable_from_upgrade(tree):
        _scan_body(func.body, dict(module_scope), module_literals, created, statements)
    return frozenset(created), statements


@dataclass(frozen=True)
class Finding:
    lineno: int
    kind: str
    table: str
    confidence: str


def scan_file(path: Path) -> tuple[list[Finding], list[Statement], str]:
    """Findings (touches a table this revision did not create), statements
    this script could not classify at all, and the file's own source text
    (for the acknowledgement scan below), for one revision file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    created, statements = _scan_revision(tree)

    findings: list[Finding] = []
    unresolved: list[Statement] = []
    for stmt in statements:
        if not stmt.tables:
            unresolved.append(stmt)
            continue
        for table in sorted(stmt.tables):
            if table not in created:
                findings.append(Finding(stmt.lineno, stmt.kind, table, stmt.confidence))
    return findings, unresolved, source


def main(argv: list[str]) -> int:
    if not VERSIONS_DIR.is_dir():
        print(f"[FAIL] versions directory not found: {VERSIONS_DIR}")
        return 1

    paths = sorted(VERSIONS_DIR.glob("*.py"))
    if len(paths) < _MIN_EXPECTED_REVISIONS:
        print(
            f"[FAIL] only {len(paths)} revision(s) found under {VERSIONS_DIR}, "
            f"expected at least {_MIN_EXPECTED_REVISIONS}. Either the migration "
            "tree really did shrink, or this scan is not seeing the real "
            "directory (shallow checkout, moved path, a future layout change) "
            "- either way, a clean summary over this few files would be a "
            "false clean, so this fails instead of reporting one."
        )
        return 1

    parse_errors: list[tuple[str, str]] = []
    flagged_files = 0
    unresolved_files = 0
    total_findings = 0
    total_unresolved = 0
    by_confidence = {"literal": 0, "derived": 0}

    missing_acks: list[tuple[str, list[str]]] = []
    new_unresolved: list[tuple[str, Statement]] = []

    for path in paths:
        try:
            findings, unresolved, source = scan_file(path)
        except SyntaxError as exc:
            parse_errors.append((path.name, str(exc)))
            continue
        if not findings and not unresolved:
            continue

        acks = _parse_acknowledgements(source)
        flagged_tables = sorted({f.table for f in findings})
        bad_acks: list[str] = []
        for t in flagged_tables:
            ack = acks.get(t)
            if ack is None:
                bad_acks.append(f"{t}: no data-rewrite-ack comment")
                continue
            growth, rows_text = ack
            problem = _ack_problem(growth, rows_text)
            if problem:
                bad_acks.append(f"{t}: {problem}")
        if bad_acks:
            missing_acks.append((path.name, bad_acks))

        rows: list[tuple[int, str]] = []
        for f in findings:
            ack = acks.get(f.table)
            if ack is None:
                ack_note = " ack=MISSING"
            else:
                growth, rows_text = ack
                problem = _ack_problem(growth, rows_text)
                ack_note = f" ack={growth}(INVALID)" if problem else f" ack={growth}"
            rows.append(
                (
                    f.lineno,
                    f"  {f.kind:<12} {f.table:<42} line {f.lineno:<5} confidence={f.confidence}{ack_note}",
                )
            )
            by_confidence[f.confidence] = by_confidence.get(f.confidence, 0) + 1
            total_findings += 1
        for u in unresolved:
            rows.append(
                (
                    u.lineno,
                    f"  UNRESOLVED   {u.kind:<42} line {u.lineno:<5} (could not determine target table)",
                )
            )
            total_unresolved += 1
            if (path.name, u.text) not in _UNRESOLVED_BASELINE:
                new_unresolved.append((path.name, u))
        rows.sort(key=lambda r: r[0])

        print(path.name)
        for _, line_text in rows:
            print(line_text)

        if findings:
            flagged_files += 1
        if unresolved:
            unresolved_files += 1

    print()
    print(
        f"SUMMARY: {len(paths)} revisions scanned, {flagged_files} flagged "
        f"({total_findings} statement(s): {by_confidence.get('literal', 0)} literal, "
        f"{by_confidence.get('derived', 0)} derived), "
        f"{unresolved_files} revision(s) carry {total_unresolved} statement(s) this script "
        f"could not classify at all"
    )

    blocking = False

    if missing_acks:
        blocking = True
        print()
        print(
            f"[FAIL] {len(missing_acks)} revision(s) flag a table with no "
            "data-rewrite-ack, or one that is not well-formed:"
        )
        for name, reasons in missing_acks:
            print(f"  {name}: {'; '.join(reasons)}")
        print(
            "  Add one comment per table, shaped like: "
            "# data-rewrite-ack: table=... growth=tenure|bounded|dead-code rows=... "
            "- see Acknowledging a flagged revision in this script's module docstring. "
            "growth=dead-code additionally needs an issue reference (e.g. #144) in rows=."
        )

    if new_unresolved:
        blocking = True
        print()
        print(f"[FAIL] {len(new_unresolved)} unresolved statement(s) not in _UNRESOLVED_BASELINE:")
        for name, stmt in new_unresolved:
            print(f"  {name} line {stmt.lineno}: {stmt.text}")
        print(
            "  Read each by hand. If it is non-DML, like every entry already in "
            "the baseline (a read, an index/constraint/sequence statement), add "
            "its (filename, ast.unparse(node)) identity to _UNRESOLVED_BASELINE "
            "in this script with a one-line reason. If it touches a pre-existing "
            "table, that is the finding this whole script exists to surface - "
            "improve resolution above so it becomes a real Finding with a table "
            "name, or escalate for manual review; do not add it to the baseline "
            "just to make this run pass."
        )

    if parse_errors:
        print()
        print(f"[WARN] {len(parse_errors)} file(s) could not be parsed:")
        for name, msg in parse_errors:
            print(f"  {name}: {msg}")

    print()
    if blocking or parse_errors:
        print(
            "Blocking: Repo hygiene fails this run. See this script's module docstring for the acknowledgement format."
        )
    else:
        print("Blocking: every flagged table carries an acknowledgement. Run is clean.")
    return 1 if (blocking or parse_errors) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
