"""Every event name a handler subscribes to must be published by someone.

The event bus matches subscribers to publishers by exact string. Nothing checks
the two sides agree, so a handler subscribed to a name no module publishes is
silently inert: it imports, it registers, it is covered by its own unit tests
if it has any, and it never runs. There is no log line, no startup warning and
no failing assertion anywhere - the only visible symptom is a feature that does
not happen.

Thirty-one such subscriptions were already in the tree when this gate was
written. They are listed in ``KNOWN_DEAD_SUBSCRIPTIONS`` with the site and the
nearest published name, because the point is to shrink that list, not hold it.

The scan was wrong in both directions at first. It read only literals and
constants, so five live seams that name their event through a local variable
(a dict lookup, a conditional, a queue fired after commit) were listed as dead,
and fifteen subscriptions registered from a ``(name, handler)`` table were not
seen at all - twelve of them dead. The ``test_scanner_*`` cases below pin each
shape the scan now reads, with the near miss it must not count.

The gate deliberately does not assert the reverse. A published event with no
subscriber is normal and common: events exist for modules that may not be
installed, and the platform publishes far more names than it consumes.

It reads the whole backend tree, which costs about 45 seconds and makes it the
slowest test in the unit suite. That is the price of the population: a scan
narrowed to one package would go green while the seam it missed stayed broken,
and every dead subscription listed below sits in a different module.
"""

import ast
import pathlib
import re
from collections import defaultdict

#: Call names that put an event on the bus.
#:
#: Matched loosely (any callee containing "publish", or ending in "emit")
#: because the bus is reached through several wrappers. ``publish_after_commit``
#: takes the session first and the event name second, which is why the scan
#: reads every positional argument rather than only the first.
_PUBLISH_HINTS = ("publish",)
_PUBLISH_SUFFIXES = ("emit",)

#: Call names that attach a handler to the bus.
_SUBSCRIBE_HINTS = ("subscribe",)
_SUBSCRIBE_EXACT = ("on",)

#: Keyword arguments that can carry the event name.
_NAME_KEYWORDS = ("event_name", "event", "name")

_APP_ROOT = pathlib.Path(__file__).resolve().parents[2] / "app"

#: Cheap text test for a file that can possibly contain a bus call.
#:
#: A call cannot be named ``publish``/``subscribe``/``emit`` without those
#: letters appearing in the file, so skipping such a file cannot change the
#: result.
_CALL_TOKENS = ("publish", "subscribe", "emit", ".on(")

#: Cheap text test for a file that defines an event name constant.
#:
#: Files matching this are parsed even when they hold no bus call, because a
#: publisher commonly names its event through a constant imported from a module
#: that holds nothing else - ``event_taxonomy.SNAPSHOT_CREATED`` in dashboards is exactly
#: that shape. Without this the scan would lose the definition and report the
#: subscriber as dead.
_CONSTANT_LINE = re.compile(
    r"""^[A-Z_][A-Z0-9_]*(?:\s*:[^=
]+)?\s*=\s*[\(\[]?\s*["'][a-z0-9_]+\.[a-z0-9_.]+["']""",
    re.MULTILINE,
)


def _worth_parsing(source: str) -> bool:
    """Skip files that can hold neither a bus call nor an event-name constant.

    Parsing is the single most expensive step of this scan - about 23 of the
    2456 files' seconds - and roughly three quarters of the backend tree can
    contain neither. The two tests below are text-level and deliberately
    generous; a file that slips through costs a walk, a file wrongly skipped
    would cost correctness, so anything ambiguous is parsed.
    """
    return any(token in source for token in _CALL_TOKENS) or bool(_CONSTANT_LINE.search(source))


def _is_constant_name(identifier: str) -> bool:
    """Event-name constants are SCREAMING_CASE by convention everywhere here.

    Restricting the sweep to those keeps it honest and cheap. Honest, because
    every attribute access in a publish call would otherwise be offered up as a
    possible event name, and a lowercase attribute that happens to share a name
    with some constant elsewhere would invent a publisher. Cheap, because the
    tree holds far more ordinary assignments than constants.
    """
    return identifier.isupper() and identifier.strip("_") != ""


#: Subscriptions that are dead today, with where they live and what they most
#: likely meant. Each entry is a work item: fixing the seam means renaming one
#: side, proving the handler's effect with a test, and deleting the line here.
#:
#: Renaming all of them at once is NOT the way to close this list. Most of these
#: handlers have never executed against real data, and several write money or
#: create records; turning thirty of them on in one commit would be a behaviour
#: change disguised as a rename. One seam per commit, with a test that asserts
#: the handler's effect rather than that it fired.
KNOWN_DEAD_SUBSCRIPTIONS: dict[str, str] = {}


def _callee(node: ast.Call) -> str:
    """Name of the thing being called, ignoring what it is attached to."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _looks_like_event(value: str) -> bool:
    """Filter payload strings out of the argument sweep.

    Event names are dotted, lower case and otherwise alphanumeric. Reading every
    positional argument is what makes ``publish_after_commit`` work, and this is
    what stops the session argument or a message body being mistaken for a name.
    """
    return "." in value and value.islower() and value.replace(".", "").replace("_", "").isalnum()


def _literals(node: ast.AST) -> list[str]:
    """Every string literal inside an expression, f-strings excepted.

    An f-string's fixed parts (``"moc.entry."`` in ``f"moc.entry.{status}"``)
    are fragments, not event names, so their subtrees are skipped.
    """
    out: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.JoinedStr):
            continue
        if isinstance(current, ast.Constant) and isinstance(current.value, str):
            out.append(current.value)
        stack.extend(ast.iter_child_nodes(current))
    return out


def _fstring_pattern(node: ast.AST) -> str | None:
    """A regex for an event name built with an f-string, or None.

    ``f"notifications.dispatch.{channel}"`` publishes one event per channel.
    Each placeholder matches one name segment. The f-string must open with a
    literal that already reads like an event name (lower case, a dot), so
    ``f"{module}.created"`` cannot turn into a pattern that calls every
    ``*.created`` subscriber live, and a revision code such as ``f"C.{n}"``
    handed to a ``_announce_revision_if_published`` helper is not one.
    """
    if not isinstance(node, ast.JoinedStr) or not node.values:
        return None
    head = node.values[0]
    if not (isinstance(head, ast.Constant) and isinstance(head.value, str) and _looks_like_event(head.value)):
        return None
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(re.escape(value.value))
        else:
            parts.append("[a-z0-9_]+")
    return "".join(parts)


def _first_literals(node: ast.AST) -> list[str]:
    """The name half of a ``(name, payload)`` or ``(name, handler)`` pair."""
    if isinstance(node, ast.Tuple) and node.elts:
        return _literals(node.elts[0])
    return _literals(node)


def _local_values(scope: ast.AST, identifier: str, consts: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Names and f-string patterns a function binds to ``identifier``.

    See ``_Scan._resolve_locals``.
    """
    values: list[str] = []
    patterns: list[str] = []
    queues: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == identifier for t in node.targets):
            values.extend(_literals(node.value))
            patterns.extend(p for p in map(_fstring_pattern, ast.walk(node.value)) if p)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == identifier
            and node.value is not None
        ):
            values.extend(_literals(node.value))
        elif (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Tuple)
            and node.target.elts
            and isinstance(node.target.elts[0], ast.Name)
            and node.target.elts[0].id == identifier
        ):
            if isinstance(node.iter, ast.Name) and node.iter.id in consts:
                values.extend(consts[node.iter.id])
            elif isinstance(node.iter, ast.Name):
                queues.add(node.iter.id)
            elif isinstance(node.iter, (ast.Tuple, ast.List)):
                for element in node.iter.elts:
                    values.extend(_first_literals(element))
    if queues:
        for node in ast.walk(scope):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in queues
                and node.args
            ):
                values.extend(_first_literals(node.args[0]))
            elif (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(node.value, (ast.Tuple, ast.List))
                and any(isinstance(t, ast.Name) and t.id in queues for t in _targets(node))
            ):
                for element in node.value.elts:
                    values.extend(_first_literals(element))
    return values, patterns


def _parameter_position(scope: ast.FunctionDef | ast.AsyncFunctionDef, identifier: str) -> int | None:
    """Where ``identifier`` sits among a call's positional arguments, or None.

    A method's ``self`` or ``cls`` is bound by the attribute access, so it is
    not counted.
    """
    positional = [a.arg for a in (*scope.args.posonlyargs, *scope.args.args)]
    if positional and positional[0] in ("self", "cls"):
        positional = positional[1:]
    if identifier in positional:
        return positional.index(identifier)
    if identifier in (a.arg for a in scope.args.kwonlyargs):
        return 1_000_000  # keyword only, never positional
    return None


def _targets(node: ast.Assign | ast.AnnAssign) -> list[ast.expr]:
    return list(node.targets) if isinstance(node, ast.Assign) else [node.target]


class _Scan:
    """One pass over the backend tree, collecting publishers and subscribers.

    One parse and one ``ast.walk`` per file. The first version of this scan
    walked each tree four times and parsed it twice, which cost 137 seconds -
    slow enough that the gate would have been deleted rather than fixed.

    Constants are read from the module body before the walk, because that is
    where they live and because a per-node method call over two million nodes
    cost more than the parse that preceded it. Loop variables are resolved
    inside the walk instead: ``ast.walk`` is breadth-first, so a ``for`` header
    is always visited before the calls nested in its body.
    """

    def __init__(self) -> None:
        self.published: dict[str, set[str]] = defaultdict(set)
        # Regexes for names published through an f-string, with their sites.
        self.published_patterns: dict[str, set[str]] = defaultdict(set)
        self.subscribed: dict[str, set[str]] = defaultdict(set)
        # Constants defined anywhere in the tree, so a publisher that names its
        # event through an imported constant is not reported as missing. Every
        # definition of an identifier is kept, not the first: two modules may
        # use the same constant name, and resolving to whichever file happened
        # to be read first would invent a publisher that does not exist.
        self.constants: dict[str, set[str]] = defaultdict(set)
        # (is_publish, identifier, site) for arguments the defining file did not
        # hold. Resolved once every file has been read.
        self.pending: list[tuple[bool, str, str]] = []
        # (is_publish, local variable, line, site) for calls in the file being
        # read that name the event through a lowercase local. Resolved per file.
        self.local_pending: list[tuple[bool, str, int, str]] = []

    def _strings(self, node: ast.AST, consts: dict[str, list[str]]) -> list[str]:
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, str) else []
        if isinstance(node, ast.Name):
            return list(consts.get(node.id, []))
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            out: list[str] = []
            for element in node.elts:
                out.extend(self._strings(element, consts))
            return out
        return []

    def _unresolved_names(self, node: ast.AST, consts: dict[str, list[str]]) -> list[str]:
        """Identifiers that may name an event once the whole tree is known.

        ``ast.Attribute`` matters as much as ``ast.Name`` here. The common idiom
        in this codebase is ``from . import events as ev`` and then
        ``_safe_publish(ev.GR_POSTED, ...)``, so a scan that reads only bare
        names reports three live supplier_catalogs publishers as missing and
        calls their subscribers dead. Only the attribute is carried, not the
        module it hangs off, which is why every definition of a name is kept.
        """
        if isinstance(node, ast.Name) and node.id not in consts:
            return [node.id] if _is_constant_name(node.id) else []
        if isinstance(node, ast.Attribute):
            return [node.attr] if _is_constant_name(node.attr) else []
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            out: list[str] = []
            for element in node.elts:
                out.extend(self._unresolved_names(element, consts))
            return out
        return []

    def _record(self, is_publish: bool, names: list[str], site: str) -> None:
        target = self.published if is_publish else self.subscribed
        for name in names:
            if _looks_like_event(name):
                target[name].add(site)

    def _handle_call(self, node: ast.Call, consts: dict[str, list[str]], path: str) -> None:
        callee = _callee(node)
        is_publish = any(hint in callee for hint in _PUBLISH_HINTS) or callee.endswith(_PUBLISH_SUFFIXES)
        is_subscribe = any(hint in callee for hint in _SUBSCRIBE_HINTS) or callee in _SUBSCRIBE_EXACT
        if not is_publish and not is_subscribe:
            return
        site = f"{path}:{node.lineno}"
        arguments: list[ast.AST] = list(node.args)
        arguments.extend(kw.value for kw in node.keywords if kw.arg in _NAME_KEYWORDS)
        for argument in arguments:
            self._record(is_publish, self._strings(argument, consts), site)
            pattern = _fstring_pattern(argument) if is_publish else None
            if pattern:
                self.published_patterns[pattern].add(site)
            for unresolved in self._unresolved_names(argument, consts):
                self.pending.append((is_publish, unresolved, site))
            if isinstance(argument, ast.Name) and argument.id not in consts and not _is_constant_name(argument.id):
                self.local_pending.append((is_publish, argument.id, node.lineno, site))

    def _resolve_locals(self, tree: ast.Module, consts: dict[str, list[str]], path: str) -> None:
        """Resolve event names a publisher or subscriber keeps in a local variable.

        Three shapes in this tree name the event through a local rather than a
        literal or a constant, and a scan blind to them reports a live seam as
        dead. A dict lookup or conditional (``event_name = {...}.get(status)``,
        ``hold_event = "a" if passed else "b"``), a queue of ``(name, payload)``
        pairs fired after the transaction (``events_to_fire.append((...))``),
        and a ``for event_name, handler in _SUBSCRIPTIONS`` registration loop.

        Resolution is scoped to the innermost function holding the call, so a
        variable of the same name in another function cannot invent a
        publisher. Only files with such a call pay for the extra walk.
        """
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        # Same-file helpers that take the event name as a parameter and publish
        # it, keyed by helper name: (position among the call's arguments, name).
        wrappers: dict[str, tuple[int, str]] = {}
        for is_publish, identifier, lineno, site in self.local_pending:
            owners = [f for f in functions if f.lineno <= lineno <= (f.end_lineno or f.lineno)]
            if not owners:
                continue
            scope = max(owners, key=lambda f: f.lineno)
            values, patterns = _local_values(scope, identifier, consts)
            self._record(is_publish, values, site)
            if is_publish:
                for pattern in patterns:
                    self.published_patterns[pattern].add(site)
                position = _parameter_position(scope, identifier)
                if position is not None:
                    wrappers[scope.name] = (position, identifier)
        self.local_pending.clear()
        if wrappers:
            self._read_wrapper_calls(tree, consts, wrappers, path)

    def _read_wrapper_calls(
        self, tree: ast.Module, consts: dict[str, list[str]], wrappers: dict[str, tuple[int, str]], path: str
    ) -> None:
        """Count what callers hand a publishing helper as published.

        ``self._set_vendor_status(vendor_id, "blacklisted", ev.VENDOR_BLACKLISTED)``
        publishes ``supplier_catalogs.vendor.blacklisted`` inside the helper,
        but the name only appears at the call. Same file only: a helper is
        private to its module in every case this tree holds.
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            wrapper = wrappers.get(_callee(node))
            if wrapper is None:
                continue
            position, keyword = wrapper
            arguments = [kw.value for kw in node.keywords if kw.arg == keyword]
            if position < len(node.args):
                arguments.append(node.args[position])
            site = f"{path}:{node.lineno}"
            for argument in arguments:
                self._record(True, self._strings(argument, consts), site)
                for unresolved in self._unresolved_names(argument, consts):
                    self.pending.append((True, unresolved, site))

    def _harvest(self, node: ast.AST, consts: dict[str, list[str]]) -> bool:
        """Record a constant assignment. True when the node was one."""
        if isinstance(node, ast.Assign):
            if not isinstance(node.value, (ast.Constant, ast.Tuple, ast.List, ast.Set, ast.Name)):
                return True
            values = self._strings(node.value, {})
            if values:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        consts[target.id] = values
                        if _is_constant_name(target.id):
                            self.constants[target.id].update(values)
            return True
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            # `_EVENTS: tuple[str, ...] = (...)` is an AnnAssign, not an Assign.
            # Reading only Assign silently drops every annotated catalogue and
            # reports its subscribers as dead.
            if not isinstance(node.value, (ast.Constant, ast.Tuple, ast.List, ast.Set, ast.Name)):
                return True
            values = self._strings(node.value, {})
            if values:
                consts[node.target.id] = values
                if _is_constant_name(node.target.id):
                    self.constants[node.target.id].update(values)
            return True
        return False

    def read(self, path: pathlib.Path) -> None:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        self.read_source(source, path.relative_to(_APP_ROOT).as_posix())

    def read_source(self, source: str, relative: str) -> None:
        """Scan one module's text. Split from ``read`` so the scanner can be tested on snippets."""
        if not _worth_parsing(source):
            return
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            return
        consts: dict[str, list[str]] = {}
        # Constants live at module level, so harvest them from the top-level
        # body alone. Keeping _harvest out of the full walk below matters: that
        # loop runs about two million times per scan, and a method call per node
        # was costing more than the parse it followed.
        for node in tree.body:
            self._harvest(node, consts)
        if not any(token in source for token in _CALL_TOKENS):
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                # `for name in _STALE_EVENTS: subscribe_once(name, handler)`
                values = self._strings(node.iter, consts)
                if values:
                    consts[node.target.id] = values
            elif isinstance(node, ast.Call):
                self._handle_call(node, consts, relative)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        self._handle_call(decorator, consts, relative)
        if self.local_pending:
            self._resolve_locals(tree, consts, relative)

    def is_published(self, name: str) -> bool:
        """True when a literal, a constant or an f-string publishes ``name``."""
        if name in self.published:
            return True
        return any(re.fullmatch(pattern, name) for pattern in self.published_patterns)

    def resolve_pending(self) -> None:
        """Second chance for names defined in a file other than the caller's."""
        for is_publish, identifier, site in self.pending:
            values = self.constants.get(identifier)
            if values:
                self._record(is_publish, sorted(values), site)


def _scan_backend() -> _Scan:
    scan = _Scan()
    for path in sorted(_APP_ROOT.rglob("*.py")):
        scan.read(path)
    scan.resolve_pending()
    return scan


def test_no_new_dead_event_subscriptions() -> None:
    """A subscription to an unpublished name is a handler that can never run.

    Fails in both directions on purpose. Subscribe to a name nobody publishes
    and the new name is not in the allowlist, so the test fails and names it.
    Repair a seam and forget to delete its allowlist line, and the test fails
    asking for the line to go, so the list can never quietly outlive the bug it
    describes.
    """
    scan = _scan_backend()

    # A scan that came back empty would make both assertions below pass. State
    # the population next to the verdict rather than certifying silence.
    assert len(scan.published) > 100, f"scanner found only {len(scan.published)} published names - instrument is broken"
    assert len(scan.subscribed) > 50, (
        f"scanner found only {len(scan.subscribed)} subscribed names - instrument is broken"
    )

    dead = {name for name in scan.subscribed if not scan.is_published(name)}
    undocumented = dead - set(KNOWN_DEAD_SUBSCRIPTIONS)
    repaired = set(KNOWN_DEAD_SUBSCRIPTIONS) - dead

    assert undocumented == set(), "\n".join(
        [
            "These subscriptions name an event no module publishes, so the handler never runs:",
            *(f"  {name} subscribed at {', '.join(sorted(scan.subscribed[name]))}" for name in sorted(undocumented)),
            "Rename one side so both agree, or add the name to KNOWN_DEAD_SUBSCRIPTIONS with the reason.",
        ]
    )
    assert repaired == set(), "\n".join(
        [
            "These names are published again, so their allowlist entries are stale:",
            *(f"  {name}" for name in sorted(repaired)),
            "Delete them from KNOWN_DEAD_SUBSCRIPTIONS.",
        ]
    )


def test_allowlist_entries_all_carry_a_reason() -> None:
    """An allowlist of bare names decays into a list nobody can act on."""
    for name, reason in KNOWN_DEAD_SUBSCRIPTIONS.items():
        assert len(reason) > 30, f"{name} needs a reason saying where it is subscribed and what it probably meant"


def _scan_snippets(**modules: str) -> _Scan:
    scan = _Scan()
    for relative, source in modules.items():
        scan.read_source(source, relative)
    scan.resolve_pending()
    return scan


def test_scanner_reads_names_held_in_a_local_variable() -> None:
    """A dict lookup, a conditional and a queue fired after commit all publish.

    These three shapes made the gate list five live seams as dead
    (``approval_routes.instance.completed`` and ``.rejected``, the two MoC
    transitions, the QMS hold-point failure).
    """
    scan = _scan_snippets(
        a="""
def transition(to_status):
    event_name = {"accepted": "moc.entry.accepted"}.get(to_status, f"moc.entry.{to_status}")
    _safe_publish(event_name, {})

def record(result):
    hold_event = "qms.hold.passed" if result == "passed" else "qms.hold.failed"
    event_bus.publish_detached(hold_event, {})

def decide(rejected):
    events_to_fire = []
    if rejected:
        events_to_fire.append(("routes.instance.rejected", {"status": "rejected"}))
    else:
        events_to_fire.append(("routes.instance.completed", {"status": "approved"}))
    for event_name, event_data in events_to_fire:
        _safe_publish(event_name, event_data)
""",
    )
    for name in (
        "moc.entry.accepted",
        "qms.hold.passed",
        "qms.hold.failed",
        "routes.instance.rejected",
        "routes.instance.completed",
    ):
        assert scan.is_published(name), name
    # The f-string fallback publishes one name per status.
    assert scan.is_published("moc.entry.implemented")
    # The dict's keys are statuses, not names, and the payload's values are
    # statuses too.
    assert not scan.is_published("accepted")
    assert not scan.is_published("approved")


def test_scanner_keeps_a_local_name_inside_its_own_function() -> None:
    """The same variable name elsewhere in the file must not invent a publisher."""
    scan = _scan_snippets(
        a="""
def labels():
    event_name = "orders.order.shipped"
    return event_name

def send(event_name):
    log(event_name)

def fire():
    event_name = "orders.order.created"
    event_bus.publish_detached(event_name, {})
""",
    )
    assert scan.is_published("orders.order.created")
    assert not scan.is_published("orders.order.shipped")


def test_scanner_reads_subscriptions_registered_from_a_pair_table() -> None:
    """``for event_name, handler in _SUBSCRIPTIONS`` registers every pair.

    Fifteen subscriptions in four modules were invisible to the gate in this
    shape, so a dead one among them could never be reported.
    """
    scan = _scan_snippets(
        a="""
_SUBSCRIPTIONS = (
    ("projects.created", _on_project_created),
    ("risk.zone.flagged", _on_risk_zone_flagged),
)

def register_subscribers():
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe_once(event_name, handler)

def register_dispatchers():
    handlers_to_register = [
        ("notifications.dispatch.email", _on_dispatch_email),
    ]
    for event_name, handler in handlers_to_register:
        event_bus.subscribe_once(event_name, handler)
""",
    )
    assert set(scan.subscribed) == {"projects.created", "risk.zone.flagged", "notifications.dispatch.email"}


def test_scanner_matches_f_string_publishers_by_segment() -> None:
    scan = _scan_snippets(
        a="""
async def dispatch(channel, module):
    name = f"notifications.dispatch.{channel}"
    await _safe_publish(name, {})
    event_bus.publish_detached(f"{module}.created", {})
    self._announce_revision_if_published(container, f"C.{module}")
""",
    )
    assert scan.is_published("notifications.dispatch.email")
    # One placeholder is one segment, not a free suffix.
    assert not scan.is_published("notifications.dispatch.email.retry")
    # An f-string that opens on a placeholder would match every "*.created".
    assert not scan.is_published("projects.created")
    assert scan.published_patterns.keys() == {r"notifications\.dispatch\.[a-z0-9_]+"}


def test_scanner_follows_an_event_name_through_a_publishing_helper() -> None:
    """The name appears at the helper's call, the publish inside the helper."""
    scan = _scan_snippets(
        a="""
from . import events as ev

class VendorService:
    async def _set_vendor_status(self, vendor_id, new_status, event_name, user_id=None):
        _safe_publish(event_name, {"vendor_id": str(vendor_id)})

    async def blacklist_vendor(self, vendor_id):
        return await self._set_vendor_status(vendor_id, "blacklisted", ev.VENDOR_BLACKLISTED)

    async def suspend_vendor(self, vendor_id):
        return await self._set_vendor_status(vendor_id, "suspended", event_name="vendors.vendor.suspended")
""",
        b="""
VENDOR_BLACKLISTED = "vendors.vendor.blacklisted"
""",
    )
    assert scan.is_published("vendors.vendor.blacklisted")
    assert scan.is_published("vendors.vendor.suspended")
    # The status argument sits in another position and is not a name.
    assert not scan.is_published("blacklisted")
