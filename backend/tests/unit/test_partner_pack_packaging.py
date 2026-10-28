# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The documents a pack ships in the repository, and the ones it ships to a user.

Thirteen packs carried rule-pack documents in the tree that no installed copy
ever received, because a wheel only carries a non-Python file when a
``package-data`` glob names it. The defect is invisible from inside the tree:
every document is there, every test that reads the tree finds it, and the only
people affected are the ones who installed from a package. That is the worst
shape a defect can have, so it gets a gate rather than a repair.

The property is stated over every pack: each non-Python file under a pack's
package directory has to be matched by one of that package's ``package-data``
globs. A pack that starts shipping a new data directory without declaring it
goes red on the day it lands, not on the day somebody installs it.

The inverse, a glob that matches nothing, is deliberately not asserted here.
Twelve packs carry one today and it costs nothing: setuptools ignores a glob
with no files, so the wheel is correct either way. Folding it in would make
this gate red for a cosmetic reason and train people to ignore it, which is how
a gate stops working.

``test_the_gate_reports_a_pack_whose_glob_is_missing`` is the part that keeps
this honest. A gate built from first principles can pass because its own
predicate is wrong, so the predicate is run against a pack built to fail and
against the same pack built to pass, and has to tell them apart.
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKS = REPO_ROOT / "packs"

#: Directories that hold build output rather than anything a wheel should carry.
_IGNORED_DIRS = {"__pycache__", ".pytest_cache"}

#: Suffixes setuptools ships as modules, not as package data.
_MODULE_SUFFIXES = {".py", ".pyc", ".pyo"}


def _package_data(pyproject: Path) -> dict[str, list[str]]:
    """The ``[tool.setuptools.package-data]`` table, or an empty one."""
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    table = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    return {str(k): [str(g) for g in v] for k, v in table.items()}


def _data_files(package_dir: Path) -> list[str]:
    """Every non-Python file under ``package_dir``, relative and slash-separated."""
    found: list[str] = []
    for path in package_dir.rglob("*"):
        if not path.is_file() or path.suffix in _MODULE_SUFFIXES:
            continue
        if any(part in _IGNORED_DIRS for part in path.relative_to(package_dir).parts):
            continue
        found.append(path.relative_to(package_dir).as_posix())
    return sorted(found)


def uncovered_data_files(pack_dir: Path) -> dict[str, list[str]]:
    """Data files a pack holds on disk that its ``package-data`` does not name.

    Args:
        pack_dir: A directory holding ``pyproject.toml`` and ``src/<package>/``.

    Returns:
        Package name mapped to the files that would be left out of a wheel.
        Empty when everything on disk is declared.
    """
    pyproject = pack_dir / "pyproject.toml"
    if not pyproject.is_file():
        return {}
    globs = _package_data(pyproject)
    src = pack_dir / "src"
    if not src.is_dir():
        return {}

    missing: dict[str, list[str]] = {}
    for package_dir in sorted(p for p in src.iterdir() if p.is_dir()):
        declared = globs.get(package_dir.name, [])
        left_out = [f for f in _data_files(package_dir) if not any(fnmatch.fnmatch(f, g) for g in declared)]
        if left_out:
            missing[package_dir.name] = left_out
    return missing


def _pack_dirs() -> list[Path]:
    """Every pack that builds a distribution."""
    return sorted(p.parent for p in PACKS.glob("*/pyproject.toml"))


def test_no_subpackage_holds_data_this_gate_cannot_see() -> None:
    """The gate matches a package's globs against the files under that package.

    setuptools assigns a data file to the package that owns it, so a nested
    package with an ``__init__.py`` would need its own ``package-data`` key and
    this gate's model would quietly be wrong about it. No pack has one today.
    If one appears, this fails and says to extend the gate rather than letting
    it return a confident wrong answer.
    """
    nested: dict[str, list[str]] = {}
    for pack_dir in _pack_dirs():
        src = pack_dir / "src"
        if not src.is_dir():
            continue
        for package_dir in sorted(p for p in src.iterdir() if p.is_dir()):
            found = [
                str(init.parent.relative_to(package_dir).as_posix())
                for init in package_dir.rglob("__init__.py")
                if init.parent != package_dir and "__pycache__" not in init.parts
            ]
            if found:
                nested[pack_dir.name] = sorted(found)
    assert not nested, (
        "these packs hold a nested package, so package-data is resolved per subpackage and this "
        f"gate's one-package-per-pack model no longer holds: {nested}. Extend the gate before "
        "trusting it again."
    )


def test_every_data_file_a_pack_holds_is_one_a_wheel_would_carry() -> None:
    """A document in the tree that no install receives is the defect this catches."""
    pack_dirs = _pack_dirs()
    checked = 0
    missing: dict[str, dict[str, list[str]]] = {}
    for pack_dir in pack_dirs:
        src = pack_dir / "src"
        if src.is_dir():
            for package_dir in sorted(p for p in src.iterdir() if p.is_dir()):
                checked += len(_data_files(package_dir))
        found = uncovered_data_files(pack_dir)
        if found:
            missing[pack_dir.name] = found

    population = f"checked {checked} data files across {len(pack_dirs)} packs"
    print(f"partner pack packaging: {population}")
    assert pack_dirs, "no packs found, so this gate measured nothing and must not read as a pass"
    assert checked, "no data files found, so this gate measured nothing and must not read as a pass"
    assert not missing, (
        f"{population}. These are on disk and no wheel would carry them, because no package-data "
        f"glob in the pack's pyproject.toml matches: {missing}. Add the glob, then rebuild the "
        "wheel and list it to confirm."
    )


def test_the_gate_reports_a_pack_whose_glob_is_missing(tmp_path: Path) -> None:
    """The predicate has to fail in both directions, so run it on both.

    Built against a pack shaped like the real ones, once without the
    ``rule_packs`` glob and once with it. A predicate that passes the repo but
    cannot tell these two apart is not measuring what this file claims.
    """

    def build(pack: Path, globs: list[str]) -> Path:
        package = pack / "src" / "openconstructionerp_fixture"
        (package / "rule_packs").mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "onboarding.yaml").write_text("steps: []\n", encoding="utf-8")
        (package / "rule_packs" / "a.json").write_text("{}", encoding="utf-8")
        (package / "rule_packs" / "b.json").write_text("{}", encoding="utf-8")
        declared = "".join(f'    "{g}",\n' for g in globs)
        (pack / "pyproject.toml").write_text(
            "[tool.setuptools.package-data]\nopenconstructionerp_fixture = [\n" + declared + "]\n",
            encoding="utf-8",
        )
        return pack

    without = uncovered_data_files(build(tmp_path / "without", ["onboarding.yaml"]))
    assert without == {"openconstructionerp_fixture": ["rule_packs/a.json", "rule_packs/b.json"]}, (
        f"the gate did not name the documents a wheel would drop: {without}"
    )

    with_glob = uncovered_data_files(build(tmp_path / "with", ["onboarding.yaml", "rule_packs/*.json"]))
    assert with_glob == {}, f"the gate reported a correctly declared pack: {with_glob}"
