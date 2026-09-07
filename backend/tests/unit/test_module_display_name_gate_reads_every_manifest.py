# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The module-name guard must read every manifest, however the file is written.

`scripts/check_module_display_names.py` decides which modules have to have a
`modules.catalog.<name>` key. Whatever it fails to read is not merely unchecked,
it is outside the population: no key is ever demanded of it, its name renders in
English in all 40 languages, and the verdict still looks ordinary because the
count is taken after the drop.

The reader used to be two line-anchored regexes over the manifest text, and the
comment above the skip said the loader would refuse a manifest they could not
match. It would not. `app/core/module_loader.py` imports the manifest and checks
`isinstance(manifest, ModuleManifest)`, so quoting and line layout never reach
it and the module loads normally.

The layout that defeats an anchor is one our own pinned formatter produces. A
`ModuleManifest(...)` call whose last keyword argument has no trailing comma is
collapsed onto a single line when it fits in 120 characters, and `display_name`
then sits mid-line where `^\\s*` cannot match. Single quotes did the same thing
from the other direction. Neither is exotic and neither would have gone red.

So the cases below are written as manifests, not as regex inputs, and they are
driven through `main()` rather than through the reader, because the failure that
mattered was not "the reader returned less" but "the verdict said nothing".
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).resolve().parents[3] / "scripts" / "check_module_display_names.py"
_spec = importlib.util.spec_from_file_location("check_module_display_names", _GATE)
assert _spec and _spec.loader, f"gate script not found at {_GATE}"
gate = importlib.util.module_from_spec(_spec)
sys.modules["check_module_display_names"] = gate
_spec.loader.exec_module(gate)


MULTILINE = """\
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_multiline",
    version="1.0.0",
    display_name="Multiline Module",
    category="core",
)
"""

#: What `ruff format` produces from the same call when its last argument has no
#: trailing comma and the whole thing fits inside the 120 character limit.
COLLAPSED = """\
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(name="oe_collapsed", version="1.0.0", display_name="Collapsed Module", category="core")
"""

SINGLE_QUOTED = """\
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name='oe_quoted',
    version='1.0.0',
    display_name='Quoted Module',
    category='core',
)
"""

#: A manifest the guard cannot read the name out of. It still loads, so it has
#: to be reported rather than skipped.
NON_LITERAL = """\
from app.core.module_loader import ModuleManifest

_SUFFIX = "built"

manifest = ModuleManifest(
    name="oe_" + _SUFFIX,
    version="1.0.0",
    display_name=f"Built {_SUFFIX}",
    category="core",
)
"""


def _write_tree(root: Path, manifests: dict[str, str], catalog: dict[str, str]) -> tuple[Path, Path]:
    """Write a module tree and an `en.ts` beside it, and return both paths."""
    modules_dir = root / "modules"
    for directory, source in manifests.items():
        module_dir = modules_dir / directory
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / "manifest.py").write_text(source, encoding="utf-8")

    pairs = "\n".join(f'  "{key}": "{value}",' for key, value in catalog.items())
    locale = root / "en.ts"
    locale.write_text(f"export const en = {{\n{pairs}\n}};\n", encoding="utf-8")
    return modules_dir, locale


@pytest.fixture
def gate_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point the guard at a tree written by the test."""

    def build(manifests: dict[str, str], catalog: dict[str, str]) -> None:
        modules_dir, locale = _write_tree(tmp_path, manifests, catalog)
        monkeypatch.setattr(gate, "MODULES", modules_dir)
        monkeypatch.setattr(gate, "EN_LOCALE", locale)
        monkeypatch.setattr(gate, "ROOT", tmp_path)

    return build


ALL_THREE = {"multiline": MULTILINE, "collapsed": COLLAPSED, "quoted": SINGLE_QUOTED}
ALL_THREE_KEYS = {
    "modules.catalog.multiline": "Multiline Module",
    "modules.catalog.collapsed": "Collapsed Module",
    "modules.catalog.quoted": "Quoted Module",
}


def test_every_manifest_layout_is_in_the_population(gate_tree, capsys: pytest.CaptureFixture[str]) -> None:
    """Three manifests on disk, three in the verdict.

    The collapsed one and the single-quoted one are the two the anchored
    regexes lost. Asserting the number in the verdict, and not just the exit
    code, is the point: a guard that drops a manifest passes this tree either
    way, and only the population says which one it checked.
    """
    gate_tree(ALL_THREE, ALL_THREE_KEYS)

    assert gate.main() == 0
    verdict = capsys.readouterr().out
    assert "3 of 3 manifests" in verdict, f"the verdict does not name the population it checked: {verdict!r}"


@pytest.mark.parametrize(
    ("directory", "source", "module_name"),
    [("collapsed", COLLAPSED, "oe_collapsed"), ("quoted", SINGLE_QUOTED, "oe_quoted")],
)
def test_a_manifest_the_reader_might_drop_is_still_held_to_the_locale(
    gate_tree,
    capsys: pytest.CaptureFixture[str],
    directory: str,
    source: str,
    module_name: str,
) -> None:
    """The consequence of a drop, stated as a test.

    A module outside the population is never asked for its key, so the guard
    that exists to demand one returns success while the module ships an
    untranslatable name. Both layouts are checked, because they were lost by
    two different halves of the same regex.
    """
    gate_tree(
        {"multiline": MULTILINE, directory: source},
        {"modules.catalog.multiline": "Multiline Module"},
    )

    assert gate.main() == 1, f"{module_name} has no catalog key and the guard reported success"
    assert module_name in capsys.readouterr().err


def test_a_manifest_whose_fields_are_not_literals_is_named_not_skipped(
    gate_tree,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The new reader must not rebuild the silent drop in a different shape.

    A manifest built at runtime is one the guard genuinely cannot judge. The
    loader still loads it, so the honest answer is to fail and say which file,
    rather than to leave it out of the count.
    """
    gate_tree({"multiline": MULTILINE, "built": NON_LITERAL}, {"modules.catalog.multiline": "Multiline Module"})

    assert gate.main() == 1
    stderr = capsys.readouterr().err
    assert "built/manifest.py" in stderr.replace("\\", "/")
    assert "display_name" in stderr


def test_a_drift_is_still_caught_in_a_collapsed_manifest(gate_tree, capsys: pytest.CaptureFixture[str]) -> None:
    """Widening the population must widen what the other two checks see too."""
    gate_tree(
        ALL_THREE,
        {**ALL_THREE_KEYS, "modules.catalog.collapsed": "Something Else Entirely"},
    )

    assert gate.main() == 1
    stderr = capsys.readouterr().err
    assert "Collapsed Module" in stderr
    assert "Something Else Entirely" in stderr


def test_the_reader_reaches_every_manifest_in_the_real_tree() -> None:
    """The live population, asserted where a change to the tree can move it.

    `main()` refuses to run on a short population, but only this says out loud
    what the number is, and it fails on the day a manifest is written in a way
    the parser cannot read instead of waiting for the gate to run in CI.
    """
    manifests = gate.read_manifests()
    on_disk = sorted(gate.MODULES.glob(gate.MANIFEST_GLOB))
    print(f"\nPOPULATION: {len(manifests)} manifests read, {len(on_disk)} manifest.py files under {gate.MODULES}")

    assert len(on_disk) >= 100, f"only {len(on_disk)} manifests found, so this test asserts almost nothing"
    assert len(manifests) == len(on_disk)

    unreadable = [m.path.name for m in manifests if not m.name or not m.display_name]
    assert not unreadable, f"the guard cannot read name and display_name out of: {unreadable}"
