# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every onboarding Country Pack preset must name a demo the backend can install.

The preset table lives in the frontend and the demo registry lives here, so
nothing in either language could see both halves at once. What filled the gap
was a comment, and the comment was wrong: it said the flagship demos under
``demo_packs/`` "only register when their partner pack is installed", so preset
after preset was written with ``demoId: null`` to stay on the safe side.

``demo_projects`` imports ``app.core.demo_packs`` unconditionally at the bottom
of the module and the loader merges every pack file into ``DEMO_TEMPLATES`` at
import time. There is no condition anywhere. Sixteen of the twenty-one markets
shipped without an example project because of a sentence, while the demo they
needed was in the registry the whole time.

So this reads the shipped preset table off disk and asks the real registry. It
fails in both directions on purpose: a preset naming a demo that does not exist
is the obvious defect, and a preset naming no demo at all is the one that
actually happened.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.demo_projects import DEMO_TEMPLATES


def _repo_root() -> Path:
    """Walk up until a directory holds both halves of the repository."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend").is_dir() and (parent / "frontend").is_dir():
            return parent
    raise RuntimeError(f"repository root not found from {__file__}")


COUNTRY_PACKS_TS = _repo_root() / "frontend" / "src" / "features" / "onboarding" / "countryPacks.ts"

# One preset object literal. Anchored on ``id`` and ``demoId`` together so a
# stray ``demoId`` in a doc comment cannot be mistaken for an entry.
_PRESET = re.compile(
    r"\{\s*\n\s*id:\s*'(?P<id>[a-z-]+)',.*?\n\s*demoId:\s*(?P<demo>'[a-z0-9-]+'|null),",
    re.S,
)


def _presets() -> list[tuple[str, str | None]]:
    """Parse ``(preset id, demo id)`` pairs out of the shipped preset table."""
    source = COUNTRY_PACKS_TS.read_text(encoding="utf-8")
    body = source.split("export const COUNTRY_PACKS", 1)[-1]
    found = [
        (m.group("id"), None if m.group("demo") == "null" else m.group("demo").strip("'"))
        for m in _PRESET.finditer(body)
    ]
    if not found:
        pytest.fail(f"parsed no presets out of {COUNTRY_PACKS_TS}; the table shape changed")
    return found


def test_the_preset_table_is_readable_and_not_empty() -> None:
    """Guard the parser itself, so a silent zero can never read as a pass."""
    presets = _presets()
    assert len(presets) >= 20, f"only {len(presets)} presets parsed, the regex has stopped matching the table"


def test_every_preset_names_a_demo() -> None:
    """The half that was actually broken: presets that promised a demo and had none."""
    presets = _presets()
    without = sorted(pack_id for pack_id, demo in presets if demo is None)
    assert not without, (
        f"{len(without)} of {len(presets)} presets carry no demo: {without}. "
        "The preset subtitle promises sample projects, so a null here ships a promise the install cannot keep."
    )


def test_every_named_demo_resolves_in_the_registry() -> None:
    """The other half: an id the backend cannot install is a dead one-click button."""
    presets = _presets()
    unresolved = sorted({demo for _, demo in presets if demo is not None and demo not in DEMO_TEMPLATES})
    assert not unresolved, (
        f"{len(unresolved)} preset demo id(s) are not in DEMO_TEMPLATES "
        f"({len(DEMO_TEMPLATES)} registered): {unresolved}"
    )


def test_pack_demos_register_without_any_pack_installed() -> None:
    """Pin the fact the old comment got wrong, so it cannot be re-asserted quietly.

    Nothing here installs or applies a partner pack. If these ids resolve anyway,
    the ``demo_packs`` loader is unconditional, which is the whole premise of
    wiring pack demos into the presets.
    """
    from_packs = ["residential-saopaulo", "office-shanghai", "school-stpetersburg", "condo-toronto"]
    missing = [demo for demo in from_packs if demo not in DEMO_TEMPLATES]
    assert not missing, (
        f"pack demos absent from a plain import: {missing}. If this is now true, the preset table "
        "cannot reference demo_packs templates and countryPacks.ts must say so again."
    )
