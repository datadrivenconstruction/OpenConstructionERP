# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A pack derived from another pack is only a pack while its parent is there.

``turkey-tr-mep`` builds its manifest from the ``turkey-tr`` manifest when it
is loaded and states only its own fields. Everything that ships packs was
written before a pack could depend on another one: three hand-written lists
each name the packs one at a time, and discovery loads each ``manifest.py`` on
its own and skips, with a log line, any that fails to load. Put together, a
derived pack that reaches a user without its parent does not fail anything. It
is simply missing from the list of packs, on that platform only.

Four things are held here, for every derived pack the tree carries, so the
next one comes under them without being added to a list:

1. Wherever the derived pack ships, its parent ships: the wheel force-include
   map, the Docker build context and the desktop bundle.
2. The derived manifest really loads from the layout those three produce,
   ``packs/<slug>/src`` beside the ``app`` package, in a clean interpreter
   that holds nothing but that layout. All three artefacts produce the same
   layout, so one copy of it stands for the three.
3. Without the parent the derived pack is absent and the log says why. That is
   the designed outcome, and it is also what proves case 2 read the parent
   from the copied layout and not from somewhere else on the machine.
4. The derived manifest imports nothing the frozen desktop build would lack.
   Pack manifests are bundled as data files and loaded by path, so PyInstaller
   never analyses their imports; a module only they import is a module the
   bundle does not contain.

Plus the declaration every pack makes when it names a file: the installed
wheel gate (``scripts/check_wheel_ships_every_pack.py``) reads every file a
manifest object names through that pack's own files. Its tree-side twin in
``test_community_packs_ship.py`` reads the manifest source, and a field built
by derivation is not in the source, so the same question is asked here of the
manifest object.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

import pytest

from app.core.partner_pack.manifest import PartnerPackManifest
from tests._pack_manifest_source import declared_parent, manifest_sources
from tests.unit.test_community_packs_ship import (
    _desktop_bundled_slugs,
    _dockerfile_copied_slugs,
    _force_included_slugs,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"
PACKS_DIR = REPO_ROOT / "packs"
CORE_PACK_MODULES = (
    BACKEND / "app" / "core" / "partner_pack" / "discovery.py",
    BACKEND / "app" / "core" / "partner_pack" / "manifest.py",
)


def _derived_packs() -> dict[str, str]:
    """Derived pack slug -> parent slug, read from the manifest sources."""
    return {slug: parent for slug, path in manifest_sources(PACKS_DIR).items() if (parent := declared_parent(path))}


DERIVED = sorted(_derived_packs().items())


def test_the_tree_carries_a_derived_pack_to_measure() -> None:
    """Every test below is parametrised over this list, and an empty list passes."""
    assert DERIVED, (
        "no pack in the tree declares DERIVED_FROM, so nothing in this file measures anything. "
        "turkey-tr-mep is one; if it stopped being derived, this file goes with it."
    )


# ── 1. The three shipping lists ─────────────────────────────────────────────


@pytest.mark.parametrize(("slug", "parent"), DERIVED)
def test_the_parent_ships_wherever_the_derived_pack_ships(slug: str, parent: str) -> None:
    mirrors = {
        "the wheel force-include map (backend/pyproject.toml)": _force_included_slugs(),
        "the Docker build context (deploy/docker/Dockerfile.unified)": _dockerfile_copied_slugs(),
        "the desktop bundle (desktop/pyinstaller.spec)": _desktop_bundled_slugs(),
    }
    orphaned = [name for name, slugs in mirrors.items() if slug in slugs and parent not in slugs]
    assert not orphaned, (
        f"packs/{slug} is derived from packs/{parent} and ships without it in: {orphaned}. Discovery "
        f"would skip {slug} there with a log line and the pack would be missing on that platform only."
    )


@pytest.mark.parametrize(("slug", "parent"), DERIVED)
def test_the_derived_distribution_depends_on_the_parents(slug: str, parent: str) -> None:
    """Installed from its own wheel there is no neighbouring directory, only this dependency."""
    own = tomllib.loads((PACKS_DIR / slug / "pyproject.toml").read_text(encoding="utf-8"))
    parents = tomllib.loads((PACKS_DIR / parent / "pyproject.toml").read_text(encoding="utf-8"))
    parent_distribution = parents["project"]["name"]
    requirements = [str(item).replace(" ", "") for item in own["project"].get("dependencies", [])]
    assert any(item.startswith(f"{parent_distribution}>=") for item in requirements), (
        f"packs/{slug}/pyproject.toml does not depend on {parent_distribution}, the distribution of "
        f"the pack it is derived from: {requirements}"
    )


# ── 2 and 3. The shipped layout, in a clean interpreter ─────────────────────

_LAYOUT_PROBE = """
import json, logging, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")

root = Path(sys.argv[1])
# A pack that happens to be pip-installed on this machine must not stand in
# for the layout under test: make every pack package unimportable by name.
for name in sys.argv[2:]:
    sys.modules[name] = None

from app.core.partner_pack import discovery

tree = discovery._packs_dir_for(
    root / "app" / "core" / "partner_pack" / "discovery.py", "app.core.partner_pack.discovery"
)
discovery._packs_dir = lambda: tree
messages = []


class _Keep(logging.Handler):
    def emit(self, record):
        messages.append(record.getMessage())


discovery.logger.addHandler(_Keep())
found = discovery._discover_filesystem_packs()
print(json.dumps({
    "tree": str(tree) if tree else None,
    "messages": messages,
    "packs": {
        m.slug: {
            "rule_sets": list(m.validation_rule_sets),
            "documents": list(m.validation_rule_packs),
            "currency": m.default_currency,
            "locale": m.default_locale,
            "methodology": m.default_methodology,
            "cost_regions": list(m.cwicr_regions),
            "country": m.market_country_code,
            "derived_from": m.metadata.get("derived_from"),
        }
        for m in found
    },
}))
"""


def _package_names(*slugs: str) -> list[str]:
    return sorted(path.parent.name for slug, path in manifest_sources(PACKS_DIR).items() if slug in slugs)


def _ship(site: Path, *slugs: str) -> None:
    """Copy ``packs/<slug>/src`` under ``site``, the way each artefact lays it out."""
    for slug in slugs:
        shutil.copytree(
            PACKS_DIR / slug / "src",
            site / "packs" / slug / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
        )


def _discover_in(site: Path, *blocked_packages: str) -> dict:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _LAYOUT_PROBE, str(site), *blocked_packages],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"the layout probe would not run: {result.stderr[-2000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(("slug", "parent"), DERIVED)
def test_the_derived_manifest_loads_from_the_shipped_layout(tmp_path: Path, slug: str, parent: str) -> None:
    site = tmp_path / "site-packages"
    _ship(site, parent, slug)

    measured = _discover_in(site, *_package_names(slug, parent))

    assert measured["tree"] == str((site / "packs").resolve()), (
        f"discovery resolved the pack tree to {measured['tree']}, not the copied layout, so nothing "
        f"below describes a shipped install"
    )
    assert sorted(measured["packs"]) == sorted([parent, slug]), (
        f"the shipped layout holds {parent} and {slug} and discovery listed {sorted(measured['packs'])}. "
        f"Log: {measured['messages']}"
    )
    derived, base = measured["packs"][slug], measured["packs"][parent]
    assert derived["derived_from"] == parent
    assert base["rule_sets"], f"{parent} declares no rule set, so equality below would compare two empties"
    for inherited in ("rule_sets", "currency", "locale", "methodology", "cost_regions", "country"):
        assert derived[inherited] == base[inherited], (
            f"{slug} loaded from the shipped layout with {inherited}={derived[inherited]!r}, and its "
            f"parent declares {base[inherited]!r}"
        )
    assert measured["messages"] == [], f"discovery logged while loading a complete layout: {measured['messages']}"


@pytest.mark.parametrize(("slug", "parent"), DERIVED)
def test_without_its_parent_the_derived_pack_is_absent_and_the_log_says_why(
    tmp_path: Path, slug: str, parent: str
) -> None:
    site = tmp_path / "site-packages"
    _ship(site, slug)

    measured = _discover_in(site, *_package_names(slug, parent))

    assert measured["tree"] == str((site / "packs").resolve())
    assert measured["packs"] == {}, (
        f"{slug} loaded with no {parent} in the layout and none importable, so it took its parent "
        f"from somewhere this test did not put one: {measured['packs']}"
    )
    assert any(slug in message and parent in message.replace(slug, "") for message in measured["messages"]), (
        f"{slug} was skipped without a log line naming the missing {parent}: {measured['messages']}"
    )


# ── 4. Imports the frozen desktop build carries ─────────────────────────────


def _imported_modules(path: Path) -> set[str]:
    """Dotted names a module imports, each with its parent packages."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        found: list[str] = []
        if isinstance(node, ast.Import):
            found = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found = [node.module]
        for name in found:
            parts = name.split(".")
            names.update(".".join(parts[: index + 1]) for index in range(len(parts)))
    return names


@pytest.mark.parametrize(("slug", "parent"), DERIVED)
def test_the_derived_manifest_imports_only_what_the_core_already_imports(slug: str, parent: str) -> None:
    """PyInstaller bundles a manifest as data and never reads its imports."""
    carried = set().union(*(_imported_modules(path) for path in CORE_PACK_MODULES))
    wanted = _imported_modules(manifest_sources(PACKS_DIR)[slug])
    extra = sorted(name for name in wanted - carried if not name.startswith("app"))
    assert extra == [], (
        f"packs/{slug}/.../manifest.py imports {extra}, which neither app/core/partner_pack/discovery.py "
        f"nor manifest.py imports. In the desktop bundle the manifest is a data file, so nothing puts "
        f"those modules in the bundle for it. Use what the core imports, or add a hidden import to "
        f"desktop/pyinstaller.spec and to this test's list."
    )


# ── Every file a manifest object names is a file of that pack ───────────────


@lru_cache(maxsize=1)
def _manifest_objects() -> dict[str, tuple[Path, PartnerPackManifest]]:
    out: dict[str, tuple[Path, PartnerPackManifest]] = {}
    for slug, path in manifest_sources(PACKS_DIR).items():
        name = f"_pack_manifest_for_derived_gate_{path.parent.name}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader, f"{path} could not be loaded as a module"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out[slug] = (path.parent, module.MANIFEST)
    return out


def _named_files(manifest: PartnerPackManifest) -> list[str]:
    """Pack-relative paths the manifest names, the list the installed-wheel gate reads."""
    wanted = [manifest.onboarding_script_path, manifest.branding.logo_path, manifest.branding.favicon_path]
    wanted += list(manifest.additional_locales.values())
    wanted += [f"rule_packs/{document}.json" for document in manifest.validation_rule_packs]
    return [path for path in wanted if path]


def test_the_object_reader_sees_files_to_check() -> None:
    named = sum(len(_named_files(manifest)) for _package, manifest in _manifest_objects().values())
    assert named >= 100, f"only {named} named files were read from every manifest object in the tree"


@pytest.mark.parametrize("slug", sorted(manifest_sources(PACKS_DIR)))
def test_every_file_a_manifest_object_names_is_in_that_packs_own_package(slug: str) -> None:
    """Asked of the object, so a name that arrived by derivation is asked too."""
    package, manifest = _manifest_objects()[slug]
    absent = [path for path in _named_files(manifest) if not (package / path).is_file()]
    assert not absent, (
        f"packs/{slug} names {len(absent)} file(s) its own package does not carry: {absent}. A pack "
        f"derived from another one inherits the parent's names and none of its files; state the field "
        f"empty in the derived manifest, or carry the file."
    )
