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
#: that holds nothing else - ``event_taxonomy.SNAPSHOT_REFRESHED`` is exactly
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
KNOWN_DEAD_SUBSCRIPTIONS: dict[str, str] = {
    "approval_routes.instance.completed": (
        "rfi/approval_subscribers.py:93 and submittals/approval_subscribers.py:104; "
        "approval_routes/service.py:683 publishes 'approval_routes.instance.started'"
    ),
    "approval_routes.instance.rejected": (
        "rfi/approval_subscribers.py:94 and submittals/approval_subscribers.py:105; "
        "same publisher gap as the completed variant above"
    ),
    "bim_hub.element.updated": (
        "bim_hub/events.py:112; bim_hub/service.py:2228 publishes 'bim_hub.element.deleted' "
        "but nothing publishes the updated variant"
    ),
    "bim_model.new_version": "core/event_handlers.py:1839; the bim_hub module publishes under the 'bim_hub.' prefix",
    "bim_model.ready": "core/event_handlers.py:1838; the bim_hub module publishes under the 'bim_hub.' prefix",
    "catalog.resource.price_adjusted": "assemblies/events.py:406; no catalog publisher emits a price-adjusted event",
    "catalog.resource.updated": (
        "assemblies/events.py:405; catalog/router.py:747 publishes the plural "
        "'catalog.resources.updated' - a singular/plural mismatch, nothing more"
    ),
    "correspondence.outbound.delivered": (
        "property_dev/events.py:407; property_dev/service.py:4568 publishes "
        "'correspondence.outbound.requested' and nothing marks delivery"
    ),
    "document.revision.created": (
        "core/event_handlers.py:1833; documents and connectors publish 'documents.document.created' instead"
    ),
    "documents.uploaded": "core/event_handlers.py:1834; the documents module publishes 'documents.document.created'",
    "erp_chat.message.deleted": "erp_chat subscribes to its own delete event that no service publishes",
    "estimate.approved": "core/event_handlers.py:1831; no module publishes an estimate approval",
    "finance.invoice.created": (
        "property_dev/events.py:684; its only publisher was the duplicate claim-invoice "
        "subscriber removed from notifications/_wave5_cross_module_subscribers.py in "
        "8b71dec65, and that one never sent the metadata.instalment_buyer_id the handler "
        "keys on. Nothing writes that key, so publishing from finance would not wake it either"
    ),
    "inspection.completed.passed": "qms subscribes to a pass-specific name; inspections publish a single completion event",
    "inspection.scheduled": "nothing publishes when an inspection is scheduled",
    "meeting.action_item.created": (
        "core/event_handlers.py:1827; meetings/service.py:470 publishes the plural 'meeting.action_items_created'"
    ),
    "meeting.scheduled": "nothing publishes when a meeting is scheduled",
    "moc.entry.accepted": "moc subscribers wait on an acceptance event no service publishes",
    "moc.entry.implemented": "moc subscribers wait on an implementation event no service publishes",
    "ncr.cost_impact": "core/event_handlers.py:1832; ncr/service.py:333 publishes 'ncr.closed_with_cost_impact'",
    "po.issued": "core/event_handlers.py:1835; procurement/service.py:1588 publishes 'procurement.po.issued'",
    "portal.buyer_signup.completed": "nothing publishes a completed buyer signup",
    "qms.inspection.hold_point_failed": "qms subscribes to a hold-point failure no inspection service publishes",
    "rfi.response.design_change": "nothing publishes an RFI response that carries a design change",
    "schedule.milestone.reached": "nothing publishes when a schedule milestone is reached",
    "schedule_advanced.task.completed": (
        "bi_dashboards/events.py:104, inside the annotated _PROJECTION_INVALIDATING_EVENTS "
        "tuple; schedule_advanced publishes actuals updates but never a task completion, so "
        "the BI projection for it is never invalidated"
    ),
    "snapshot.refreshed": (
        "dashboards/__init__.py:94 via event_taxonomy.SNAPSHOT_REFRESHED, which is declared "
        "twice (dashboards/events.py:31 and dashboards/sync_protocol.py:58) and published "
        "nowhere. sync_protocol.py:18 documents the refresh cascade as if it runs"
    ),
    "schedule.progress_updated": (
        "core/event_handlers.py:1837; schedule/progress_service.py:230 publishes 'schedule.activity.progress_updated'"
    ),
    "submittal.status_changed": "nothing publishes a submittal status change",
    "validation.report.updated": "validation/events.py:72; validation publishes report creation, not update",
    "variations.completed": (
        "bi_dashboards/events.py:124, inside the annotated _PROJECTION_INVALIDATING_EVENTS "
        "tuple; the changeorders module publishes under the singular 'changeorder.' prefix"
    ),
    "variation.approved": (
        "core/event_handlers.py:1840; changeorders/service.py:1551 publishes "
        "'changeorder.approved'. Fix this seam LAST and on its own: the handler writes "
        "contract value, and a second, live subscriber already writes it from "
        "notifications/_wave5_cross_module_subscribers.py, so renaming without checking "
        "risks a double write"
    ),
}


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
            for unresolved in self._unresolved_names(argument, consts):
                self.pending.append((is_publish, unresolved, site))

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
        if not _worth_parsing(source):
            return
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            return
        relative = path.relative_to(_APP_ROOT).as_posix()
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

    dead = {name for name in scan.subscribed if name not in scan.published}
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
