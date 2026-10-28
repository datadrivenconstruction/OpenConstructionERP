# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Several modules fill one tool registry, and a name collision leaves no trace.

``global_tool_registry`` is a single process-wide dict of name -> tool, filled
by ``register()`` calls that run inside module ``on_startup`` hooks rather than
at import. ``ToolRegistry.register`` overwrites by name and returns ``None``, so
two modules registering the same name is not an error, not a warning, and not
visible in the registry afterwards. The only difference it makes is that every
agent listing that name in ``allowed_tools`` calls whichever copy the startup
order happened to run last, while both files go on reading as if each owned its
own tool.

That is live today. ``search_costs`` is registered by ``boq_drafter`` and again
by ``rate_benchmarker``; ``on_startup`` runs the drafter first, so the
benchmarker's copy is the one every agent gets, the BOQ drafter included. The
two implementations agree apart from the observation each hands back to the LLM
when the cost database is unreachable, so the live effect is that a drafter run
is told the rate could not be benchmarked while it is drafting a BOQ. It stays
that small only until somebody edits one of the two copies, which nothing here
or anywhere else would notice.

The collision is pinned rather than repaired because repairing it means either
deleting one of two live implementations or merging them behind one message,
and both are calls for the module's owner rather than for a test.

The other check here is that ``TOOL_PERMISSIONS`` in ``ai_agents/triggers.py``
never prices a tool nothing registers. Its scope is narrow on purpose. That map
is documented as listing the tools that perform or propose a privileged action,
while read-only tools are meant to ride ``DEFAULT_TOOL_PERMISSION`` with no
entry at all, so the absence of a name proves nothing and is not asserted on.
The presence of a name that resolves to no tool does prove something: the entry
was written to keep a specific permission attached to a specific tool, a rename
in the agent module detaches it silently, and the comment explaining the
arrangement goes on describing something that has stopped happening.

Two mechanics have to be respected or the file measures nothing. Registration
happens in function calls, so a probe that merely imports the agent packages
reports an empty registry and would report that as a finding. And an overwrite
is observable only while it happens, which is why the fixture records
registrations as they are made instead of inspecting the result.
"""

from __future__ import annotations

import asyncio
import importlib
import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from app.modules.ai_agents.base import global_tool_registry
from app.modules.ai_agents.triggers import DEFAULT_TOOL_PERMISSION, TOOL_PERMISSIONS

_REGISTERS_A_TOOL = re.compile(r"\bglobal_tool_registry\.register\s*\(")

#: Tool names registered from more than one module, as measured today, against
#: the modules that define the colliding implementations. Startup order decides
#: the winner, so this doubles as the record of which copy is live.
_KNOWN_COLLISIONS = {
    "search_costs": (
        "app.modules.ai_agents.agents.boq_drafter",
        "app.modules.ai_agents.agents.rate_benchmarker",
    ),
}


class Startup(NamedTuple):
    """What a boot of every tool-registering module produced.

    ``registered`` is the registry afterwards, which is what ``set_tools``
    reads. ``calls`` is every registration in the order it was made, which is
    the only place an overwritten tool is still visible.
    """

    registered: set[str]
    calls: list[tuple[str, str]]


def _modules_that_register_tools() -> list[str]:
    """Every module package whose source registers a runner tool.

    Read out of the source rather than listed, so a third module that starts
    registering into the same global registry is measured from the day it does.
    Naming the two we have today would be the same defect this file is about.
    """
    import app.modules as modules_pkg

    root = Path(modules_pkg.__file__).parent
    found = set()
    for path in root.rglob("*.py"):
        if _REGISTERS_A_TOOL.search(path.read_text(encoding="utf-8", errors="replace")):
            found.add(path.relative_to(root).parts[0])
    return sorted(found)


@pytest.fixture
def startup() -> Iterator[Startup]:
    """Boot every registering module, recording each registration, then undo it.

    The registry is global and these are the real production registrations, so
    leaving them behind would change what every later test in the session sees.
    Both the dict and the patched method are put back for that reason.
    """
    before = dict(global_tool_registry._tools)
    original = global_tool_registry.register
    calls: list[tuple[str, str]] = []

    def recording(tool: Any) -> None:
        # ``func`` is the implementation the name resolves to, and its defining
        # module is what tells two same-named tools apart. A tool without one is
        # recorded as unknown rather than skipped, so it cannot drop out of the
        # comparison unnoticed.
        defining = getattr(getattr(tool, "func", None), "__module__", None) or "<unknown>"
        calls.append((tool.name, defining))
        original(tool)

    global_tool_registry.register = recording  # type: ignore[method-assign]
    try:
        for name in _modules_that_register_tools():
            module = importlib.import_module(f"app.modules.{name}")
            hook = getattr(module, "on_startup", None)
            if hook is not None:
                asyncio.run(hook())
        yield Startup(registered=set(global_tool_registry.names()), calls=calls)
    finally:
        del global_tool_registry.register  # drop the instance attribute, restore the class method
        global_tool_registry._tools = before


def test_the_boot_this_file_measures_actually_happened(startup: Startup) -> None:
    """The vacuity guard, and the reason the rest of the file can be trusted.

    Every assertion below is over a registry somebody has to have filled, and
    all of them pass trivially against an empty one. A silent zero here reads
    exactly like a clean result, so it is asserted rather than printed.
    """
    registrars = _modules_that_register_tools()

    assert len(registrars) >= 2, (
        f"only {registrars} register runner tools. Either the registration call was renamed, in "
        "which case this scan reads nothing, or a module stopped registering. Both make the "
        "assertions below vacuous."
    )
    assert startup.registered, "the startup hooks registered no tools at all, so nothing here is compared"
    assert len(startup.calls) >= len(startup.registered), (
        f"{len(startup.calls)} recorded registrations produced {len(startup.registered)} tools, "
        "which is impossible unless the recording wrapper was bypassed. The collision check reads "
        "those recorded calls and would see nothing."
    )


def test_the_permission_map_never_prices_a_tool_that_is_not_registered(startup: Startup) -> None:
    """An entry that resolves to nothing detaches a permission without saying so.

    ``required_permission_for_tool`` is a ``dict.get`` with a default, so an
    entry whose tool was renamed in its agent module is not an error. The tool
    silently returns to ``DEFAULT_TOOL_PERMISSION`` and the entry prices
    nothing, while the comment above the map goes on explaining a deliberate
    choice, ``create_position`` gated on ``boq.create`` being the one written
    out at length, that has quietly stopped applying to anything.

    This asserts in one direction only. A registered tool with no entry is the
    documented arrangement for read-only tools, not a gap, so it is not checked.
    """
    orphans = sorted(set(TOOL_PERMISSIONS) - startup.registered)

    assert not orphans, (
        f"{orphans} are priced in TOOL_PERMISSIONS and registered by nothing, so each names a "
        f"permission that is now attached to no tool and falls back to {DEFAULT_TOOL_PERMISSION!r}. "
        "Rename the entry along with its tool, or drop the entry and the comment that explains it."
    )


def test_one_tool_name_never_means_two_implementations(startup: Startup) -> None:
    """A second registration of a live name discards the first one in silence.

    The registry ends one entry shorter than the number of registrations, no
    call reports anything, and the losing module keeps its now-unreachable
    implementation and its docstring. Which copy survives is decided by the
    order of ``register_*`` calls in ``on_startup``, which is not written
    anywhere as an interface and reorders freely.

    Pinned rather than repaired: see the module docstring for the live pair and
    for why the repair is the module owner's call.
    """
    by_name: dict[str, set[str]] = defaultdict(set)
    for name, defining_module in startup.calls:
        by_name[name].add(defining_module)
    collided = {name: tuple(sorted(modules)) for name, modules in by_name.items() if len(modules) > 1}

    new = {name: modules for name, modules in collided.items() if name not in _KNOWN_COLLISIONS}
    assert not new, (
        f"{new} is registered from more than one module. register() overwrites by name, so one of "
        "those implementations is discarded at boot and every agent naming the tool calls the "
        "other one, whichever that turns out to be. Give the copies distinct names, or register a "
        "single shared implementation once."
    )
    resolved = sorted(set(_KNOWN_COLLISIONS) - set(collided))
    assert not resolved, (
        f"{resolved} no longer collides. Remove it from _KNOWN_COLLISIONS and from the module "
        "docstring, so the record matches what the code does."
    )
    for name, modules in _KNOWN_COLLISIONS.items():
        assert collided[name] == modules, (
            f"{name} still collides, but between {collided[name]} rather than the recorded "
            f"{modules}. A third copy, or a copy that moved, is a different defect from the one "
            "pinned here and needs deciding on its own."
        )


# ── The checks above, checked ───────────────────────────────────────────────
#
# Both assertions pass on the tree as it stands, and an assertion that has only
# ever been seen passing is not known to be able to fail. Each one is handed a
# planted input here and has to reject it. The inputs are built rather than
# perturbed into the source, because this repository is written by many agents
# at once and a probe that edits a shared file has to survive its own process
# being killed to put the file back, which is not a bet worth taking.


def test_the_orphan_check_rejects_a_planted_orphan(startup: Startup) -> None:
    """Drop a mapped tool out of the registry and the check has to notice."""
    priced = next(iter(TOOL_PERMISSIONS))
    planted = Startup(registered=startup.registered - {priced}, calls=startup.calls)

    with pytest.raises(AssertionError, match=priced):
        test_the_permission_map_never_prices_a_tool_that_is_not_registered(planted)


def test_the_collision_check_rejects_a_planted_collision(startup: Startup) -> None:
    """Register one name from two modules and the check has to notice."""
    planted = Startup(
        registered=startup.registered,
        calls=[*startup.calls, ("read_boq", "app.modules.somewhere_else")],
    )

    with pytest.raises(AssertionError, match="read_boq"):
        test_one_tool_name_never_means_two_implementations(planted)


def test_the_pin_rejects_a_collision_that_quietly_went_away(startup: Startup) -> None:
    """The pin has to fail on repair too, not only on a new collision.

    A pin that only notices growth lets the record rot: the collision gets
    fixed, this file goes on naming it, and the next reader is told about a
    defect that is no longer there.
    """
    planted = Startup(
        registered=startup.registered,
        calls=[(name, module) for name, module in startup.calls if name not in _KNOWN_COLLISIONS],
    )

    with pytest.raises(AssertionError, match="no longer collides"):
        test_one_tool_name_never_means_two_implementations(planted)
