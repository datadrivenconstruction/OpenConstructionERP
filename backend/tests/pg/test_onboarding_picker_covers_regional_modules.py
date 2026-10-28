# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A shipped regional module has to be selectable at the one moment it is offered.

The onboarding wizard's module list is a hand-written mirror of the backend
module manifests. Nothing joined the two, so a module could ship, register its
routes, seed its data and never appear on the screen where a new workspace is
asked what it works on. That is what happened to ``china_pack``: it shipped
long before the list was written and was the only one of the thirteen country
packs with no line in it, so a Chinese user could not switch China on. The
fourteenth regional module, ``payment_clock``, was missing for the same reason
and for longer, and it was missed twice over because it does not carry the
``_pack`` suffix a search for the country packs would look for.

Hence the shape of this check. It keys on the backend manifest's own
``category`` rather than on a naming convention, because a convention is a
second thing to keep in step and this defect is exactly what happens when two
hand-kept lists drift. It does not require the reverse - that every picker key
name a backend module - because the picker's key space is deliberately wider:
``cost-benchmark`` and ``sustainability`` are frontend-only modules with routes
in ``navCatalog.ts`` and no Python package, and a check that called them dead
would invite someone to delete two working toggles.

The label mirror is checked in the same pass. An entry names two i18n keys, and
neither carries a ``defaultValue``, so a key that is missing from the base
locale reaches the screen as its own raw name.

These tests live in the PG lane because that lane is a merge gate and the
default unit lane is not, the same reason ``test_rule_set_reachability.py``
gives. Neither of them touches a database.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES_DIR = REPO_ROOT / "backend" / "app" / "modules"
PICKER = REPO_ROOT / "frontend" / "src" / "features" / "onboarding" / "modules.ts"
BASE_LOCALE = REPO_ROOT / "frontend" / "src" / "app" / "locales" / "en.ts"

#: The manifest fields are read anchored to the start of a line so that
#: ``display_name=`` cannot be mistaken for ``name=``.
_MANIFEST_NAME = re.compile(r"^\s{4}name\s*=\s*\"([^\"]+)\"", re.M)
_MANIFEST_CATEGORY = re.compile(r"^\s{4}category\s*=\s*\"([^\"]+)\"", re.M)

#: One entry of ``ALL_MODULES``. Written on a single line throughout the file.
_PICKER_ENTRY = re.compile(
    r"\{\s*key:\s*'([^']+)',\s*labelKey:\s*'([^']+)',\s*descriptionKey:\s*'([^']+)',\s*group:\s*'([^']+)'",
)

#: Every ``key:`` in the picker source, used only to check the entry reader
#: above against a second, cruder count of the same thing.
_PICKER_KEY = re.compile(r"(?<![A-Za-z])key:\s*'")

#: A flat locale key. The base locale is one object of ``"key": "value"``.
_LOCALE_KEY = re.compile(r"^\s*\"([^\"]+)\":", re.M)


def _backend_modules() -> dict[str, str]:
    """Module key -> the ``category`` its backend manifest declares.

    The key is the manifest ``name`` minus the ``oe_`` prefix, which is the
    convention the picker's own docstring states.

    Returns:
        Every backend module that declares both a name and a category.
    """
    out: dict[str, str] = {}
    for path in sorted(MODULES_DIR.glob("*/manifest.py")):
        source = path.read_text(encoding="utf-8")
        name = _MANIFEST_NAME.search(source)
        category = _MANIFEST_CATEGORY.search(source)
        if not name or not category:
            continue
        out[name.group(1).removeprefix("oe_")] = category.group(1)
    return out


def _picker_entries() -> list[tuple[str, str, str, str]]:
    """Every ``ALL_MODULES`` entry as (key, labelKey, descriptionKey, group)."""
    return _PICKER_ENTRY.findall(PICKER.read_text(encoding="utf-8"))


def _locale_keys() -> set[str]:
    """Every key defined in the base English locale."""
    return set(_LOCALE_KEY.findall(BASE_LOCALE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def entries() -> list[tuple[str, str, str, str]]:
    """Read the picker once for the whole file."""
    return _picker_entries()


def test_the_discovery_read_the_modules_the_picker_and_the_locale(
    entries: list[tuple[str, str, str, str]],
) -> None:
    """The control on the two assertions below.

    All three inputs are read with regular expressions over source files that
    this test does not own. Reformat any of them and a reader can quietly
    return nothing, at which point "every regional module is in the picker" is
    true because no regional module was found. The counts are asserted before
    anything is concluded from the contents, and the entry reader is checked
    against a second count of the same file so that a differently written
    entry fails rather than disappearing.

    Floors, not equalities, so that adding a module does not turn a passing
    gate red and invite an edit to the number.
    """
    modules = _backend_modules()
    assert len(modules) >= 150, f"only {len(modules)} backend module manifests were read from {MODULES_DIR}"

    regional = sorted(key for key, category in modules.items() if category == "regional")
    assert len(regional) >= 10, f"only {len(regional)} regional modules were found, which is too few to be right"

    assert len(entries) >= 150, f"only {len(entries)} entries were read from {PICKER}"
    crude = len(_PICKER_KEY.findall(PICKER.read_text(encoding="utf-8")))
    assert len(entries) == crude, (
        f"the entry reader saw {len(entries)} entries and there are {crude} keys in {PICKER.name}. "
        "An entry written in a shape the reader does not describe is an entry it silently exempts."
    )

    assert len(_locale_keys()) >= 10000, "the base locale reader did not find a plausible number of keys"


def test_every_regional_module_can_be_chosen_in_the_onboarding_picker(
    entries: list[tuple[str, str, str, str]],
) -> None:
    """A regional module absent from the list cannot be switched on by a new user."""
    regional = {key for key, category in _backend_modules().items() if category == "regional"}
    offered = {entry[0] for entry in entries}
    missing = sorted(regional - offered)
    assert not missing, (
        f"these regional modules ship in the backend and are not offered by the onboarding "
        f"picker: {missing}. A user setting up a workspace for that market is not shown the "
        f"module that serves it. Add a line to ALL_MODULES in {PICKER.name} with group "
        "'regional', and its two i18n keys to the base locale."
    )


def test_every_picker_entry_names_a_label_and_a_description_the_locale_defines(
    entries: list[tuple[str, str, str, str]],
) -> None:
    """The second mirror. A key with no translation reaches the screen raw."""
    keys = _locale_keys()
    undefined = {
        key: [name for name in (label, description) if name not in keys] for key, label, description, _ in entries
    }
    undefined = {key: names for key, names in undefined.items() if names}
    assert not undefined, (
        f"these picker entries name i18n keys the base locale does not define: {undefined}. "
        "The entries carry no defaultValue, so the wizard would render the key itself."
    )
