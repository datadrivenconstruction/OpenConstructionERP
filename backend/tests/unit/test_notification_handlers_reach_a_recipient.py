# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every notification handler must reach a recipient from its publisher's payload.

A subscriber that reads ``event.data["winner_user_id"]`` when its publisher
never emits that key resolves nobody and sends nothing. Nothing fails, nothing
is logged, and the feature is simply absent. Reading the handler does not catch
it, because the handler is correct in isolation; only running it against the
payload its publisher actually emits does.

THE PROPERTY, asserted per handler rather than over a fixed set. Each handler
is executed twice:

    A  payload restricted to the keys this event's publisher emits
    B  payload containing every key the handler reads             (the control)

A handler is BROKEN when B produces a notification and A does not. The control
is what makes this evidence rather than a lint: without it a handler that
notifies nobody under any payload would be indistinguishable from one starved
by its publisher. Because the rule is a property of one handler, a new handler
added later is covered without anyone editing a list.

WHY NOT A CHEAPER RULE. Relaxing A to "keys any publisher anywhere emits"
removes the need to parse each event's payload and was measured rather than
assumed: it disagrees with A on 8 of 26 handlers, every time by calling a
broken handler fine. There are ~590 distinct published key names, so common
ones like ``created_by`` and ``actor_id`` are always emitted by something.

WHAT THIS TEST CANNOT SEE, stated because a green run must not be read as
coverage it does not claim. Publisher discovery is static and misses three
shapes, each found the hard way:

  1. the event name passed as a constant - ``_safe_publish(ev.STOCK_LOW, ...)``
     rather than a string literal;
  2. the payload built in a variable or with ``{**base, ...}`` rather than
     written as a literal dict at the call site;
  3. (fixed, kept as a warning) the publish call reached through a wrapper such
     as ``_safe_publish`` or ``_emit``. Wrappers are now discovered by checking
     that they forward their own event-name parameter to a bus primitive, but a
     wrapper taking the name any other way is still invisible.

A handler whose publisher is invisible for those reasons is NOT exempted and
NOT called a defect - the instrument simply has no verdict about it. Those are
counted and named by :data:`_OPAQUE_PUBLISHER` at run time. The number of
handlers this test can actually decide is therefore ratcheted too: extracting
an event name to a constant would otherwise drop a handler out of coverage and
make this test quietly greener.

WHAT A GREEN RUN CLAIMS, AND WHAT IT DOES NOT. The rule is that a handler
reaches at least ONE recipient. That is the right rule for a gate about
starved payloads, and it is exactly why a pass here must never be read as "this
feature works". A handler written to tell three people and now reaching two of
them passes, correctly, because the payload no longer starves it - and the
third person is still not told. ``_on_bid_awarded`` is the live example: it
reaches the buyer and the awarding user, and cannot reach the winning bidder,
because no user id for a bidder exists anywhere in the schema. That is not a
flaw in this test, it is the boundary of what it asserts, and boundaries that
are not written down get exceeded by the next reader.

THE DATABASE. The sweep hands every handler a throwaway database carrying the
full schema and no rows, so a handler that loads the row its event points at
finds nothing and returns, rather than dying on a missing relation. Both end in
"this handler sent nothing", which is exactly why it matters that only one of
them is a fact about the handler: against a database with no schema, whether a
handler read as database-bound or as working depended on whether an earlier test
in the same session had happened to build one.

THE BUS, checked so the payloads above are the payloads handlers really get.
There is one ``EventBus``, no serialization anywhere in the publish path, and
``publish_detached`` is ``asyncio.create_task`` on the same loop - so a value
arrives as the type it was published as, in dev and in production alike, with
no JSON round trip to turn a UUID into a string. Every handler also receives
the *same* ``Event`` object, with no per-handler copy, so a handler that
mutated ``event.data`` would change what later handlers see;
:func:`test_a_handler_does_not_mutate_the_shared_payload` pins that.
"""

from __future__ import annotations

import ast
import functools
import importlib
import inspect
import pathlib
import pkgutil
import textwrap
import unittest.mock as um
import uuid
from typing import Any

import pytest
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import event_bus
from tests._pg import isolated_engine

_APP = pathlib.Path(__file__).resolve().parents[2] / "app"
_PRIMITIVES = {"publish", "publish_after_commit", "publish_detached"}

# Names through which a subscriber sends a notification. A handler whose body
# calls none of these is silent by construction - it subscribes in order to do
# something else, such as create a contract - and is excluded structurally
# rather than by being named in a list. Deciding this from the code instead of
# by hand is what stops the exclusions from becoming a place to park handlers
# nobody wants to look at. The limit: a handler that notifies through a helper
# of its own would be excluded wrongly, so the count is printed on failure.
_NOTIFY_CALL_NAMES = {"_notify", "notify_users", "_notify_users", "_create_notification", "NotificationService"}

# Recipient keys a handler reads in a shape the static scan cannot see. Without
# an entry here the control payload is built short, the two runs stop differing,
# and the handler drops out of what this test can decide - so these entries buy
# a verdict, and they are as trustworthy as the reading behind them and no more.
# ``_on_bid_awarded`` resolves its recipients by iterating a literal tuple
# instead of naming each key in a ``data.get`` call, so the scan sees no reads
# at all. It is no longer starved, and the entry stays because the control still
# has to offer it winner_user_id, which its publisher cannot emit.
#
# An entry here is written by hand, which means it carries no more authority
# than the reading that produced it. Copy the names from the handler's source
# and record where from, so the next reader can re-check the transcription
# instead of trusting it: these three are the whole of the tuple looped at
# _wave23_subscribers.py:340, and that loop is the only place the handler
# resolves a recipient. If a handler picks recipients from somewhere an entry
# here does not name, the gate goes green on a fix that still notifies nobody.
_EXTRA_READ_KEYS: dict[str, set[str]] = {
    "_wave23_subscribers._on_bid_awarded": {"winner_user_id", "buyer_user_id", "actor_id"},
}

# Handlers that take their recipients from the database rather than from the
# payload: they open a session, load the row the event points at, and notify
# whoever that row names. The sweep runs them against an empty schema-loaded
# database, so the load finds no row and they return early and the control
# cannot fire - not because they are silent but because there is nothing here
# for them to read. Their equivalent of this test has to seed a database and
# live in ``tests/pg``.
#
# This list may only SHRINK, and it is checked: an entry whose handler starts
# resolving a recipient from the payload alone fails the test and must be
# removed. Each was confirmed session-dependent by reading the body, and
# reading is not enough on its own: ``_on_qms_ncr_mirrored_from_hse`` was listed
# here because the first recipient it resolves comes from a ``SafetyIncident``
# row, and the second, which it takes straight out of ``ncr_owner_user_id``,
# was read past. The membership check below is what caught that, and it could
# only catch it once the sweep stopped reporting a handler that died on a
# missing relation as one that resolved nobody.
_RESOLVES_RECIPIENTS_FROM_THE_DATABASE: dict[str, str] = {
    "_collaboration_subscribers._on_collaboration_comment_created": "loads the comment and its thread",
    "_wave4_subscribers._on_bi_alert_triggered": "loads the alert to find its watchers",
    "_wave4_subscribers._on_bi_report_generated": "loads the report to find its subscribers",
    "_wave5_cross_module_subscribers._on_boq_position_assigned": "loads the position and its assignee",
    "_wave5_cross_module_subscribers._on_cert_expiring": "loads the resource through ResourceRepository",
    "events._on_meeting_action_items_created": "loads the meeting to find action-item owners",
    "events._on_validation_report_created": "loads the ValidationReport by id",
}

# Handlers known to resolve no recipient from their publisher's payload.
# This list may only SHRINK: a handler here that starts working fails the test
# and must be removed. Each entry carries the key it waits for that nobody
# sends. Populated from a measured run, not by hand.
_KNOWN_STARVED: dict[str, str] = {
    "_wave1_subscribers._on_equipment_assigned": "wants notified_user_id/requested_by; publisher sends equipment_id/rental_id/project_id",
    "_wave1_subscribers._on_equipment_damage_reported": "wants fleet_manager_id/notified_user_id; publisher sends reported_by/equipment_id",
    "_wave1_subscribers._on_service_work_order_billed": "wants created_by/dispatcher_id; publisher sends contract_id/ticket_id",
    "_wave1_subscribers._on_subcontractor_payment_app_submitted": "wants assigned_to/foreman_id; publisher sends subcontractor_id/agreement_id",
    "_wave1_subscribers._on_subcontractor_prequalification_submitted": "wants assigned_to/reviewer_id; publisher sends prequalification_id/subcontractor_id",
    "_wave1_subscribers._on_subcontractor_retention_released": "wants created_by/notified_user_id; publisher sends agreement_id/amount/reason",
    "_wave23_subscribers._on_assignment_confirmed": "wants actor_id/planner_user_id; publisher sends assignment_id/resource_id/project_id",
    "_wave23_subscribers._on_assignment_proposed": "wants assignee_user_id/resource_owner_id; publisher sends assignment_id/resource_id",
    "_wave23_subscribers._on_constraint_cleared": "wants actor_id/commitment_owner_id; publisher sends user_id/constraint_id/task_ref",
    "_wave23_subscribers._on_diary_signed": "wants client_rep_user_id/project_owner_id; publisher sends diary_id/signer_role",
    "_wave23_subscribers._on_invitation_sent": "wants bidder_user_id; publisher sends count/package_id/sent_at",
    # These two starved before they were listed. transition_claim passed its
    # payload as ``data=``, a keyword this scan does not read, so both events
    # were undecidable and dropped out of the population. Moving the publish
    # to publish_after_commit made the payload positional and the verdict
    # visible; the keys sent did not change. A claim stores no submitter and
    # names no reviewer, so a real recipient needs a decision, not a key.
    "_wave23_subscribers._on_claim_paid": "wants submitted_by/actor_id; publisher sends actor/claim_id/contract_id",
    "_wave23_subscribers._on_claim_submitted": "wants reviewer_user_id/owner_user_id; publisher sends actor/claim_id",
    "events._on_boq_created": "wants created_by/user_id; publisher sends boq_id/project_id",
}

# Minimum number of handlers this test can decide. Ratchets coverage: if a
# publisher is rewritten so its payload stops being visible, coverage drops and
# this fails rather than the suite going quietly greener.
_DECIDABLE_FLOOR = 28


@functools.cache
def _trees() -> list[tuple[pathlib.Path, ast.AST]]:
    out = []
    for path in sorted(_APP.rglob("*.py")):
        try:
            out.append((path, ast.parse(path.read_text(encoding="utf-8"))))
        except (SyntaxError, UnicodeDecodeError):
            continue
    return out


def _publish_wrappers(trees) -> set[str]:
    """Functions that forward their own event-name parameter to a bus primitive.

    Requiring the forwarding is what separates ``_safe_publish(name, data)``
    from an ordinary service method that happens to publish a hardcoded event
    somewhere in its body. Without it, 258 names qualify and any call to a
    same-named function counts as a publish site.
    """
    out: set[str] = set()
    for _path, tree in trees:
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) or fn.name in _PRIMITIVES:
                continue
            params = {a.arg for a in [*fn.args.args, *fn.args.posonlyargs]}
            if fn.args.vararg:
                params.add(fn.args.vararg.arg)
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name not in _PRIMITIVES:
                    continue
                for arg in [*node.args, *[k.value for k in node.keywords]]:
                    if isinstance(arg, ast.Name) and arg.id in params:
                        out.add(fn.name)
                        break
    return out


def _scan_publishers(trees, wrappers: set[str]) -> tuple[dict[str, set[str]], set[str]]:
    """Map event name -> published keys, plus events with an unreadable payload."""
    published: dict[str, set[str]] = {}
    opaque: set[str] = set()
    for _path, tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if not (name in wrappers or name.startswith("publish")):
                continue
            args = list(node.args)
            for i, arg in enumerate(args):
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "." in arg.value):
                    continue
                payload = args[i + 1] if i + 1 < len(args) else None
                if isinstance(payload, ast.Dict) and not any(k is None for k in payload.keys):
                    keys = {k.value for k in payload.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                    published.setdefault(arg.value, set()).update(keys)
                else:
                    # A variable payload, or ``{**base, "x": 1}`` whose splat we
                    # cannot resolve. Marks the whole event undecidable.
                    opaque.add(arg.value)
                break
    return published, opaque


def _sends_notifications(handler) -> bool:
    """True when the handler's own body calls something that notifies.

    This and ``_payload_keys_read`` both parse the handler's source and both
    can fail to get it, and they answer that failure in opposite directions on
    purpose. Here an unreadable handler is kept in the measured population,
    because excluding it would be the one outcome that costs nothing and hides
    everything. There an unreadable handler yields no read keys, so the control
    payload cannot be enriched past the publisher's, both runs agree, and the
    handler ends up with no verdict - which this suite requires to be declared
    rather than treating as fine. Neither failure can turn into a quiet green;
    they turn into a handler that has to be looked at by a person.
    """
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    except (OSError, SyntaxError, TypeError):
        return True  # cannot tell: measure it rather than exclude it
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in _NOTIFY_CALL_NAMES:
                return True
    return False


def _payload_keys_read(handler) -> set[str]:
    """Keys the handler pulls out of the event payload."""
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    except (OSError, SyntaxError, TypeError):
        return set()
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
        ):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keys.add(arg.value)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                keys.add(node.slice.value)
    return keys


def _register_all_notification_subscribers() -> None:
    """Call every notifications registrar, then read the bus for the truth.

    Discovery is the live registry rather than a source scan: registration goes
    through module-level ``("event", handler)`` tables looped into
    ``event_bus.subscribe``, and reading the bus resolves the handler objects
    directly whatever shape the table takes.
    """
    import app.modules.notifications as pkg

    called: set[int] = set()
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        try:
            module = importlib.import_module(f"app.modules.notifications.{mod_info.name}")
        except Exception:  # noqa: BLE001, S112
            continue
        for attr in dir(module):
            if not attr.startswith("register_"):
                continue
            fn = getattr(module, attr)
            # Master registrars call the sub-registrars they group, so calling
            # both would register each handler several times.
            if callable(fn) and id(fn) not in called:
                called.add(id(fn))
                try:
                    fn()
                except Exception:  # noqa: BLE001, S110
                    pass


def _registered_notification_handlers() -> list[tuple[str, Any, str]]:
    _register_all_notification_subscribers()
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, Any, str]] = []
    for event_name, handlers in event_bus._handlers.items():
        for handler in handlers:
            module = getattr(handler, "__module__", "")
            if "modules.notifications" not in module:
                continue
            label = f"{module.rsplit('.', 1)[-1]}.{getattr(handler, '__qualname__', handler)}"
            if (event_name, label) in seen:
                continue
            seen.add((event_name, label))
            out.append((event_name, handler, label))
    return sorted(out, key=lambda r: (r[2], r[0]))


def _sample_value(key: str) -> Any:
    if key.endswith(("_id", "_by")) or key == "id":
        return str(uuid.uuid4())
    if key in {"count", "quantity", "days"}:
        return 3
    if any(t in key for t in ("amount", "value", "total")):
        return "1000.00"
    if key.endswith(("_at", "date")):
        return "2026-08-24T10:00:00Z"
    if key == "currency":
        return "EUR"
    return f"probe-{key}"


async def _recipients_resolved(
    module, handler, event_name: str, keys: set[str], session_factory
) -> tuple[int, BaseException | None]:
    """Run the handler against a payload of exactly *keys*.

    Returns the notifications sent and whatever the handler raised. The count
    alone is the verdict this test is after, because a handler that raises
    resolved no recipient and the bus isolates handlers the same way. The
    exception still has to come back: a handler that died reading the database
    also sent nothing, and that is a fact about the database it was handed
    rather than about the handler, which is why the two have to be told apart
    by :func:`test_the_sweep_runs_against_a_schema_loaded_database` instead of
    both counting as "notified nobody".
    """
    sent: list[Any] = []

    async def _record(*args, **kwargs):
        sent.append(kwargs or args)
        return

    patches = [
        um.patch.object(module, n, _record) for n in ("_notify", "notify_users", "_notify_users") if hasattr(module, n)
    ]
    if hasattr(module, "NotificationService"):

        class _StubService:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def __getattr__(self, _name):
                return _record

        patches.append(um.patch.object(module, "NotificationService", _StubService))
    if hasattr(module, "_can_open_isolated_session"):

        async def _always():
            return True

        patches.append(um.patch.object(module, "_can_open_isolated_session", _always))
    if hasattr(module, "async_session_factory"):
        patches.append(um.patch.object(module, "async_session_factory", session_factory))

    raised: BaseException | None = None
    for patch in patches:
        patch.start()
    try:
        event = module.Event(name=event_name, data={k: _sample_value(k) for k in keys}, source_module="contract-gate")
        try:
            await handler(event)
        except Exception as exc:  # noqa: BLE001
            raised = exc
    finally:
        for patch in patches:
            patch.stop()
    return len(sent), raised


_VERDICT_CACHE: tuple[dict[str, str], list[str], list[str], list[str]] | None = None


async def _verdicts() -> tuple[dict[str, str], list[str], list[str], list[str]]:
    """Return (verdict per handler, opaque-publisher labels, unobservable labels, schema errors).

    Memoised: the sweep executes every handler twice and the five assertions
    below all read the same run.

    Every handler is given a throwaway database holding the full schema and no
    rows, so a handler that looks its recipient up finds no row and returns,
    the same way on a machine that has run other tests first and on one that
    has not. The engine lives no longer than the sweep because asyncpg
    connections are bound to the event loop that opened them, and the memoised
    sweep runs on whichever test's loop got here first.
    """
    global _VERDICT_CACHE
    if _VERDICT_CACHE is not None:
        return _VERDICT_CACHE
    trees = _trees()
    published, opaque = _scan_publishers(trees, _publish_wrappers(trees))

    verdicts: dict[str, str] = {}
    opaque_labels: list[str] = []
    unobservable: list[str] = []
    schema_errors: list[str] = []

    silent_by_construction: list[str] = []
    async with isolated_engine() as engine:
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        for event_name, handler, label in _registered_notification_handlers():
            if not _sends_notifications(handler):
                silent_by_construction.append(label)
                continue
            reads = _payload_keys_read(handler) | _EXTRA_READ_KEYS.get(label, set())
            if not reads:
                opaque_labels.append(f"{label} ({event_name}): reads no payload key")
                continue
            if event_name not in published or event_name in opaque:
                why = "payload not a literal dict" if event_name in opaque else "no literal publish site found"
                opaque_labels.append(f"{label} ({event_name}): {why}")
                continue

            module = importlib.import_module(handler.__module__)
            control, control_error = await _recipients_resolved(module, handler, event_name, reads, session_factory)
            if isinstance(control_error, ProgrammingError):
                schema_errors.append(f"{label} ({event_name}): {control_error.orig}")
            if control == 0:
                unobservable.append(f"{label} ({event_name})")
                continue
            real, _real_error = await _recipients_resolved(
                module, handler, event_name, reads & published[event_name], session_factory
            )
            verdicts[label] = "WORKS" if real > 0 else "STARVED"
            if real == 0:
                verdicts[label] = (
                    f"STARVED (waits for {sorted(reads - published[event_name])}, "
                    f"publisher sends {sorted(published[event_name])})"
                )
    _VERDICT_CACHE = (verdicts, opaque_labels, unobservable, schema_errors)
    return _VERDICT_CACHE


@pytest.mark.asyncio
async def test_every_decidable_handler_resolves_a_recipient() -> None:
    """The ratchet. A handler not on the starved list must reach somebody."""
    verdicts, _opaque, _unobservable, _schema_errors = await _verdicts()

    newly_starved = [
        f"{label}: {verdict}"
        for label, verdict in sorted(verdicts.items())
        if verdict.startswith("STARVED") and label not in _KNOWN_STARVED
    ]
    assert not newly_starved, "handler(s) resolve no recipient from their publisher's payload:\n  " + "\n  ".join(
        newly_starved
    )


@pytest.mark.asyncio
async def test_the_starved_list_only_shrinks() -> None:
    """A handler that starts working must be taken off the list."""
    verdicts, _opaque, _unobservable, _schema_errors = await _verdicts()
    fixed = [label for label in _KNOWN_STARVED if verdicts.get(label) == "WORKS"]
    assert not fixed, (
        "these handlers now resolve a recipient and must be removed from _KNOWN_STARVED:\n  "
        + "\n  ".join(sorted(fixed))
    )
    stale = [label for label in _KNOWN_STARVED if label not in verdicts]
    assert not stale, (
        "these _KNOWN_STARVED entries no longer match any decidable handler (renamed, deleted, or dropped out of "
        "coverage) and must be removed:\n  " + "\n  ".join(sorted(stale))
    )
    now_measurable = [label for label in _RESOLVES_RECIPIENTS_FROM_THE_DATABASE if label in verdicts]
    assert not now_measurable, (
        "these handlers now resolve a recipient from the payload alone, so they are no longer database-bound and "
        "must be removed from _RESOLVES_RECIPIENTS_FROM_THE_DATABASE:\n  " + "\n  ".join(sorted(now_measurable))
    )


@pytest.mark.asyncio
async def test_a_handler_that_notifies_nobody_is_declared() -> None:
    """No verdict fails the gate, it does not pass it.

    Reaching here means the handler's body does call a notification function,
    so it is meant to notify, yet it resolved nobody even from a payload
    carrying every key it reads. That is a property of the handler rather than
    of the scan, so it counts as uncovered. Handlers that notify by way of a
    helper of their own land here too and are the reason the message asks which
    of the two it is instead of asserting a defect.
    """
    _verdicts_, _opaque, unobservable, _schema_errors = await _verdicts()
    undeclared = [u for u in unobservable if u.split(" (")[0] not in _RESOLVES_RECIPIENTS_FROM_THE_DATABASE]
    assert not undeclared, (
        "these handlers call a notification function but resolved no recipient even from a payload with every "
        "key they read. Either they notify nobody (a defect), or they reach their recipients in a shape this "
        "instrument cannot build a control for, which needs an entry in _EXTRA_READ_KEYS, or they look their "
        "recipients up in the database and belong in _RESOLVES_RECIPIENTS_FROM_THE_DATABASE with a reason:\n  "
        + "\n  ".join(sorted(undeclared))
    )


@pytest.mark.asyncio
async def test_the_sweep_runs_against_a_schema_loaded_database() -> None:
    """A handler that queries a table has to find no row, not no table.

    The instrument decides a handler resolved nobody by counting what it sent,
    and a handler that raises sends nothing. That is the right reading for a
    handler that gave up and the wrong one for a handler killed by the database
    it was handed: the verdict then says whether some earlier test in the
    session had built a schema, and the same tree answers differently run alone
    and run in a suite.

    Measured rather than supposed. ``_on_qms_ncr_mirrored_from_hse`` loads a
    ``SafetyIncident`` before it reads ``ncr_owner_user_id``, so with no schema
    present it died on ``relation "oe_safety_incident" does not exist``, counted
    as having notified nobody, and read as database-bound; with a schema present
    the same code on the same commit read as WORKS. Two lists in this file each
    demanded one of those answers, and neither of them was wrong about the run
    it saw.
    """
    _verdicts_, _opaque, _unobservable, schema_errors = await _verdicts()
    assert not schema_errors, (
        "the control run of these handlers failed on the schema rather than on the data, so what they resolved "
        "describes this instrument's database and not the handler:\n  " + "\n  ".join(sorted(schema_errors))
    )


@pytest.mark.asyncio
async def test_coverage_does_not_silently_shrink() -> None:
    """Ratchet the instrument, not only the handlers.

    Extracting an event name to a constant, or building a payload in a variable,
    removes a handler from what this test can decide. Without this the suite
    would go greener as visibility got worse.
    """
    verdicts, opaque_labels, _unobservable, _schema_errors = await _verdicts()
    decidable = len(verdicts)
    assert decidable >= _DECIDABLE_FLOOR, (
        f"this test can now decide only {decidable} handlers, down from {_DECIDABLE_FLOOR}. A publisher was "
        f"probably rewritten so its event name or payload is no longer a literal. The fix is to restore the "
        f"literal, or to teach the scan the new shape, or to add the handler's read keys to _EXTRA_READ_KEYS. "
        f"Lowering this number is not one of the fixes: it buys a green by giving up the coverage the green "
        f"is meant to stand for. Handlers with an unreadable "
        f"publisher ({len(opaque_labels)}):\n  " + "\n  ".join(sorted(opaque_labels))
    )


@pytest.mark.asyncio
async def test_a_handler_does_not_mutate_the_shared_payload() -> None:
    """``publish`` gives every handler the same ``Event``, with no per-handler copy.

    So a handler that wrote into ``event.data`` would change what the handlers
    after it receive. Nothing does today; this fails the day something starts,
    because it would silently invalidate every verdict above.
    """
    trees = _trees()
    published, opaque = _scan_publishers(trees, _publish_wrappers(trees))
    mutated: list[str] = []

    for event_name, handler, label in _registered_notification_handlers():
        reads = _payload_keys_read(handler)
        if not reads or event_name not in published or event_name in opaque:
            continue
        module = importlib.import_module(handler.__module__)
        payload = {k: _sample_value(k) for k in reads}
        before = dict(payload)
        event = module.Event(name=event_name, data=payload, source_module="contract-gate")
        try:
            await handler(event)
        except Exception:  # noqa: BLE001, S110
            pass
        if event.data != before:
            mutated.append(f"{label} ({event_name})")

    assert not mutated, "handler(s) mutated the event payload every other subscriber shares:\n  " + "\n  ".join(
        sorted(mutated)
    )
