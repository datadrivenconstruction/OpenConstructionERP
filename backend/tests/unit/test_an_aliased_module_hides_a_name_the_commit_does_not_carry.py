# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The head-import guard follows a module reached through a local name.

On 2026-08-29 the three supplier-catalog delete endpoints published event topics
that ``app/modules/supplier_catalogs/events.py`` did not define. The module was
imported as a module and the topics were read off it as attributes, so nothing
failed on load, nothing dropped out of the registry, and the guard that exists
to prove a commit can import itself said the commit was fine. The name was read
at call time, on the line announcing the deletion, which is after the guard and
after the delete: a refused delete returned its 409 and an allowed one returned
500. That is the shape this test pins, and it is the shape a checker reading
import statements alone cannot see, because the import statement says nothing
about which names the module carries.

Two things are worth proving and they pull in opposite directions. The guard has
to report the alias shape, and it has to stay silent on the code it walks past
every run, because a gate that is wrong in the other direction is worse than no
gate - it gets switched off and then catches nothing at all. So every red case
here comes with the same source one word away from it in green.

The script carries its own self-test and runs it on every invocation. This is
not a copy of it. The self-test fails the script; these fail the suite, which is
what anyone changing the script will actually run, and the fixtures below are
the incident rather than a minimal shape chosen to exercise a branch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "check_head_imports.py"

_MODULE = "app.modules.supplier_catalogs"
_SERVICE = f"{_MODULE}.service"
_EVENTS_SOURCE = '"""Event topics this module publishes."""\n\nVENDOR_UPDATED = "supplier_catalogs.vendor.updated"\n'


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_head_imports", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def _blobs(service_source: str) -> dict[str, str]:
    """The incident's file set, keyed by the paths git keys the blobs by.

    Every package on the way down is present. A guard handed a from-import of a
    package it holds no ``__init__.py`` for reports the package missing, which
    would make these fixtures red for a reason that is not the one under test.
    """
    packages = ["app", "app.modules", _MODULE]
    blobs = {guard.module_path(pkg)[0]: '"""fixture package."""\n' for pkg in packages}
    blobs[guard.module_path(f"{_MODULE}.events")[1]] = _EVENTS_SOURCE
    blobs[guard.module_path(_SERVICE)[1]] = service_source
    return blobs


# The two ways a file ends up holding a module under a local name. Both were
# invisible to the guard until it followed them, and the second is by far the
# commoner spelling in this tree.
_BINDINGS = {
    "aliased": f"import {_MODULE}.events as ev",
    "from the package": "from app.modules.supplier_catalogs import events as ev",
}


def _service(binding: str, topic: str) -> str:
    return (
        f"{binding}\n\n\nasync def delete_vendor(vendor_id: str) -> None:\n    await publish(ev.{topic}, vendor_id)\n"
    )


@pytest.mark.parametrize("binding", _BINDINGS.values(), ids=list(_BINDINGS))
def test_a_topic_the_module_does_not_define_is_reported(binding: str) -> None:
    """The incident. The import resolves; the attribute read off it does not."""
    found = guard.scan(_blobs(_service(binding, "VENDOR_DELETED")))

    assert len(found.broken) == 1, f"expected the missing topic and nothing else, got {found.broken}"
    assert "VENDOR_DELETED" in found.broken[0]
    # The finding has to name the file that reads the attribute as well as the
    # one that should define it, because the fix belongs in one of the two and
    # the reader cannot tell which from the name alone.
    assert "service.py" in found.broken[0]
    assert "events.py" in found.broken[0]


@pytest.mark.parametrize("binding", _BINDINGS.values(), ids=list(_BINDINGS))
def test_the_control_a_topic_the_module_does_define_is_silent(binding: str) -> None:
    """One word apart from the case above. Without this a guard that reports
    every attribute would pass every assertion in this file."""
    found = guard.scan(_blobs(_service(binding, "VENDOR_UPDATED")))

    assert not found.broken, f"a topic the module carries was reported: {found.broken}"
    assert found.attributes == 1, f"the attribute was not examined at all, count says {found.attributes}"


def test_an_attribute_is_not_counted_as_an_imported_name() -> None:
    """Why the guard could pass the incident: the name half never saw it.

    The import binds a module, so there is no imported name for the name half to
    resolve. It had nothing to look at and reported that everything it looked at
    was fine, which is a true sentence about an empty set.
    """
    found = guard.scan(_blobs(_service(_BINDINGS["aliased"], "VENDOR_DELETED")))

    assert found.names == 0
    assert found.modules == 1


def test_a_from_import_of_a_missing_name_is_still_reported() -> None:
    """The half that existed first, kept honest against a rewrite of the other."""
    found = guard.scan(_blobs(f"from {_MODULE}.events import VENDOR_DELETED\n"))

    assert len(found.broken) == 1, f"expected the unresolved import and nothing else, got {found.broken}"
    assert "VENDOR_DELETED" in found.broken[0]


def test_a_name_a_parameter_also_binds_is_left_alone() -> None:
    """From the text alone there is no telling which binding a use meant, and a
    guard that guesses reports the tree it guards."""
    source = f"import {_MODULE}.events as ev\n\n\ndef render(ev: object) -> str:\n    return ev.VENDOR_DELETED\n"

    assert not guard.scan(_blobs(source)).broken


def test_an_import_that_is_allowed_to_fail_is_left_alone() -> None:
    """This tree probes for optional modules that way; a name it may never bind
    is not a name the commit is missing."""
    source = (
        f"try:\n    import {_MODULE}.events as ev\nexcept ImportError:\n    ev = None\n"
        "\n\ndef render() -> str:\n    return ev.VENDOR_DELETED\n"
    )

    assert not guard.scan(_blobs(source)).broken


def test_the_scripts_own_self_test_holds() -> None:
    """It runs on every invocation of the script and raises SystemExit(2) on a
    regression, so a break in it should fail the suite too rather than waiting
    for the next commit to be checked."""
    guard.self_test()
