# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Hold the timeline allowlist against the events ``app/`` actually publishes.

This is the check whose absence *was* the bug. The module shipped with sixteen
prefixes, nine of which matched no event in the codebase at all
(``changeorder.`` where the publisher says ``changeorders.``, ``schedule.``
where it says ``schedule_advanced.``, plus ``rfi.``, ``transmittal.``,
``submittal.``, ``delay.``, ``handover.``, ``clash.`` and ``budget.``), and it
captured 13 of 225 published event names. Fifteen unit tests covered that
mapping and all of them passed, because they only ever asked the mapping about
names the mapping itself had invented. Nothing compared the allowlist to
reality, so the allowlist could say anything.

Three directions are gated here, and all three are needed:

1. every prefix matches at least one published name - catches the typo;
2. every exact entry is published verbatim - catches the same typo in the
   other list, and entries that a publisher has since renamed;
3. everything either list captures is *routable* - catches an event that would
   be recorded and then be permanently unreachable.

Direction 3 is the one it is tempting to skip, because the allowlist was
generated under that rule in the first place. A generator that ran once is not
a gate: nothing stops the next entry being added by hand.

Scope of the measurement
------------------------
Event names are read statically with :mod:`ast`, so this sees only publishes
whose name is a string literal. At the time of writing ``app/`` also has 72
publish sites whose name is computed at runtime; those are invisible here and
are not part of any count this file makes. A "captures N of M" figure quoted
from this test is therefore about literal publishes only.

One blind spot is left on purpose, and it is large enough to name. Most modules
publish through their own ``_safe_publish`` wrapper - 326 call sites against
the 11 that call ``publish_after_commit`` directly - and this scan does not
follow them. Measured 2026-09-22: counting them too takes the scan from 227
literal names to 435 and the captured set from 91 to 126, and it lands 16 more
captured names that carry no ``project_id`` in a literal payload at the call
site, which would turn :func:`test_every_captured_event_is_routable` red. Some
of those 16 build their payload in a variable, where this scan cannot see the
keys at all, so a red there would be a mix of real gaps and scan blindness that
has to be read one by one rather than closed in a batch. Widening the scan is
worth doing; doing it means triaging those 16 in the same change, not now.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[3]
_APP = _BACKEND / "app"
_MAPPING_PATH = _APP / "modules" / "timeline" / "mapping.py"

# Load mapping.py by file path. Importing it as ``app.modules.timeline.mapping``
# would execute the package __init__, which imports the DB-bound router and
# fails without a configured DATABASE_URL - the module is deliberately pure, so
# the test keeps it that way.
_spec = importlib.util.spec_from_file_location("timeline_mapping_coverage", _MAPPING_PATH)
assert _spec is not None and _spec.loader is not None
mapping = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mapping)

_PROJECT_KEYS = {"project_id", "projectId"}

# Which calls publish, and WHERE each one carries the event name. The position
# matters: ``publish_after_commit`` takes the session first, so a scan that
# always reads ``args[0]`` finds a Name node there, skips the call, and reports
# the event as published nowhere. That is not hypothetical - it is what the
# 2026-09-22 nightly reported, three times, and every one of the three was
# wrong: ``bid_management.package.awarded``, ``qms.audit.finding_raised`` and
# ``validation.results.errors_found`` are all published, deferred to the
# commit, and so is the whole ``inspection.`` family that the same run called a
# dead prefix. An instrument that cannot see a call form reports absence, and
# absence here reads as "delete that allowlist entry".
_PUBLISH_NAME_ARG = {"publish": 0, "publish_detached": 0, "publish_after_commit": 1}


def _publish_sites() -> dict[str, list[dict]]:
    """Every literal-named publish call in ``app/``, keyed by event name.

    Each entry records whether that call site passed a literal dict payload and
    whether the payload names a project.
    """
    sites: dict[str, list[dict]] = {}
    for path in sorted(_APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            at = _PUBLISH_NAME_ARG.get(name)
            if at is None or len(node.args) <= at:
                continue
            first = node.args[at]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue

            payload = node.args[at + 1] if len(node.args) > at + 1 else None
            for kw in node.keywords:
                if kw.arg in ("data", "payload"):
                    payload = kw.value

            literal = isinstance(payload, ast.Dict)
            keys = {k.value for k in payload.keys if isinstance(k, ast.Constant)} if literal else set()
            sites.setdefault(first.value, []).append(
                {
                    "where": f"{path.relative_to(_BACKEND).as_posix()}:{first.lineno}",
                    "literal": literal,
                    "has_project": bool(keys & _PROJECT_KEYS),
                }
            )
    return sites


@pytest.fixture(scope="module")
def published() -> dict[str, list[dict]]:
    return _publish_sites()


def _captured(names) -> list[str]:
    """The published names the current allowlist would record."""
    return sorted(n for n in names if mapping.is_significant(n))


def test_the_scan_finds_the_publishers_at_all(published) -> None:
    """Guard the instrument before trusting anything it says.

    Every other test here reads as "the allowlist is fine" when the scan
    silently finds nothing, so assert the scan is working first.
    """
    assert len(published) > 150, f"only {len(published)} literal event names found"
    assert "ncr.created" in published
    assert "changeorders.candidate_from_moc" in published


def test_no_allowlist_prefix_is_dead(published) -> None:
    """Every prefix must match at least one published event name."""
    dead = [p for p in mapping.ALLOWLIST_PREFIXES if not any(n.startswith(p) for n in published)]
    assert not dead, (
        f"{len(dead)} allowlist prefix(es) match no event published anywhere in app/: "
        f"{dead}. A prefix that matches nothing reads as coverage and records nothing."
    )


def test_every_exact_allowlist_entry_is_published(published) -> None:
    """Every name in ALLOWLIST_EVENTS must exist verbatim in app/."""
    missing = sorted(n for n in mapping.ALLOWLIST_EVENTS if n not in published)
    assert not missing, f"{len(missing)} exact allowlist entr(ies) name an event nothing publishes: {missing}"


def test_every_captured_event_is_routable(published) -> None:
    """Nothing the allowlist captures may be unreachable once recorded.

    ``map_event`` can only reach a project through ``project_id`` /
    ``projectId``, and the project feed selects on ``parent_entity_id`` or
    ``entity_id``. An event with no project id in its payload therefore yields
    a row no timeline query can return - a write that costs money and reads as
    coverage. ``correspondence.outbound.requested`` was exactly that, and is
    why ``correspondence.`` is not in the allowlist.
    """
    offenders: list[str] = []
    for name in _captured(published):
        for site in published[name]:
            if not site["literal"]:
                # Payload built elsewhere; this scan cannot see its keys, so it
                # is not evidence either way and must not be reported as a fail.
                continue
            if not site["has_project"]:
                offenders.append(f"{name} at {site['where']}")
    assert not offenders, (
        "the allowlist captures events whose payload carries no project id, so every row "
        "they produce is unreachable:\n  " + "\n  ".join(offenders)
    )


def test_exact_entries_are_not_already_covered_by_a_prefix() -> None:
    """An exact entry shadowed by a prefix is dead weight.

    Same failure shape as a dead prefix: it reads like a deliberate decision
    and changes nothing.
    """
    redundant = sorted(n for n in mapping.ALLOWLIST_EVENTS if n.startswith(mapping.ALLOWLIST_PREFIXES))
    assert not redundant, f"exact entries already matched by a prefix: {redundant}"


def test_allowlist_shape_is_sane() -> None:
    """Prefixes end with a dot; exact names are dotted and unique."""
    assert all(p.endswith(".") for p in mapping.ALLOWLIST_PREFIXES)
    assert len(mapping.ALLOWLIST_PREFIXES) == len(set(mapping.ALLOWLIST_PREFIXES))
    assert all("." in n and not n.endswith(".") for n in mapping.ALLOWLIST_EVENTS)


def test_capture_has_not_collapsed(published) -> None:
    """A floor on how much of the platform reaches the timeline.

    Not an exact figure - that would fail on every unrelated event added
    elsewhere. The floor is here so that a future edit which quietly guts the
    allowlist (the state this module shipped in, at 13 of 225) cannot pass.
    """
    captured = _captured(published)
    assert len(captured) >= 80, (
        f"the timeline now captures only {len(captured)} of {len(published)} published "
        "event names; it shipped once at 13 and that is the state this floor exists to stop"
    )
