# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The community packs have to be packaged, and then they have to be findable.

Nineteen packs sat in the repository and no pip or desktop install had ever
listed one. Two independent defects, either of which alone was enough:

1. ``backend/pyproject.toml`` packaged ``app`` and ``openconstructionerp`` and
   nothing else, so the ``packs/`` tree never entered the wheel.
2. ``app/core/partner_pack/discovery.py`` located the tree by counting five
   parent directories up from its own file. That reaches the repo root in a
   source checkout and the virtualenv's ``Lib`` directory in an install, where
   nothing has ever existed.

Each defect hid the other. Fixing the packaging alone ships bytes nothing
looks at; fixing the resolution alone points at a directory that was never
shipped. So this file checks both halves, and checks them the way the bug
demanded: the resolution half is exercised against a synthetic *installed*
layout, because a check that only ever runs in the source tree is precisely
the blindness that let this survive.

What is deliberately not here: proof that a built wheel contains the files.
Configuration that looks right can still produce an archive that does not, so
that assertion belongs on the artefact and lives in the wheel-inspection step
of ``.github/workflows/pypi-publish.yml``.

Pure filesystem and AST work, no database and no application import beyond the
discovery module itself, so nothing here can be skipped by a database marker.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import NoReturn

import pytest

from app.core.partner_pack.discovery import _packs_dir_for

# backend/tests/unit/<this file> -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKS_DIR = _REPO_ROOT / "packs"
_PYPROJECT = _REPO_ROOT / "backend" / "pyproject.toml"

# The dotted name discovery.py is imported under. The resolver reads its depth
# from this string, so the synthetic layouts below have to use the real one.
_DISCOVERY_MODULE = "app.core.partner_pack.discovery"


def _pack_dirs() -> list[Path]:
    """Every directory under ``packs/`` that holds a loadable pack package."""
    return sorted(d for d in _PACKS_DIR.iterdir() if d.is_dir() and any(d.glob("src/openconstructionerp_*")))


def _manifest_path(pack_dir: Path) -> Path | None:
    for pkg_dir in sorted((pack_dir / "src").glob("openconstructionerp_*")):
        candidate = pkg_dir / "manifest.py"
        if candidate.is_file():
            return candidate
    return None


def _declared_partner_url(manifest_path: Path) -> str | None:
    """Return the pack's ``partner_url``, read without executing the manifest.

    ``None`` means the pack names no outside rights holder. A string means it
    does. The manifest is parsed rather than imported: this file must stay
    runnable with no database and no import side effects, and nineteen
    ``exec_module`` calls to read one keyword would be neither.
    """
    tree = ast.parse(manifest_path.read_text(encoding="utf-8"), str(manifest_path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "partner_url":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and (value.value is None or isinstance(value.value, str)):
                return value.value
            raise AssertionError(
                f"{manifest_path} declares partner_url as {ast.dump(value)}, which this reader "
                f"cannot evaluate. It is the signal that decides whether the pack goes out in a "
                f"community artefact, so extend the reader rather than letting it guess."
            )
    raise AssertionError(
        f"{manifest_path} declares no partner_url at all. Every pack manifest states it, and the "
        f"absence would silently read as 'no outside rights holder' here."
    )


def _is_deprecated(pack_dir: Path) -> bool:
    """Mirror the skip discovery.py already applies to a deprecated pack."""
    return any(pack_dir.rglob("DEPRECATED.txt"))


def _shippable_slugs() -> set[str]:
    """The packs a community artefact may carry, computed from the tree itself.

    Two disqualifying signals, both properties of the pack rather than of a
    list someone maintains:

    * a ``DEPRECATED.txt`` anywhere under the pack, which discovery.py already
      refuses to load, so shipping it would ship bytes nothing can use;
    * a ``partner_url``, which is a pack naming an outside rights holder. Those
      carry a third party's name, logo and colours under a partnership
      agreement, and an AGPL community wheel is not the artefact that
      redistributes them.

    Computed rather than written down so that adding a pack does not silently
    change what ships in either direction.
    """
    slugs = set()
    for pack_dir in _pack_dirs():
        if _is_deprecated(pack_dir):
            continue
        manifest_path = _manifest_path(pack_dir)
        assert manifest_path is not None, f"{pack_dir.name} has a package dir but no manifest.py"
        if _declared_partner_url(manifest_path) is not None:
            continue
        slugs.add(pack_dir.name)
    return slugs


def _force_included_slugs() -> set[str]:
    """Pack slugs the wheel force-include map ships, read from pyproject.toml."""
    with open(_PYPROJECT, "rb") as handle:
        data = tomllib.load(handle)
    force_include = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    slugs = set()
    for source in force_include:
        parts = Path(source).as_posix().split("/")
        if len(parts) >= 3 and parts[0] == ".." and parts[1] == "packs":
            slugs.add(parts[2])
    return slugs


def test_the_pack_tree_is_readable_at_all() -> None:
    """Guard the instrument before the comparisons that lean on it.

    Every assertion below is a set difference, and two empty sets agree. If the
    tree moved or the layout changed, this says so instead of reporting a clean
    sweep over nothing.
    """
    packs = _pack_dirs()
    print(f"\n{len(packs)} pack packages under {_PACKS_DIR}: {[p.name for p in packs]}")
    assert len(packs) >= 10, (
        f"only {len(packs)} pack directories were found under {_PACKS_DIR}. The repository carries "
        f"far more than that, so this reader is no longer looking at the tree it thinks it is."
    )


def test_every_shippable_pack_is_force_included() -> None:
    """The direction that reproduces the original defect: packs that never ship."""
    missing = _shippable_slugs() - _force_included_slugs()
    assert not missing, (
        f"{len(missing)} pack(s) carry no disqualifying signal and are not force-included into the "
        f"wheel, so no pip or desktop install can list them: {sorted(missing)}. Add "
        f'\'"../packs/<slug>/src" = "packs/<slug>/src"\' to '
        f"[tool.hatch.build.targets.wheel.force-include] in backend/pyproject.toml, and the matching "
        f"entry to _COMMUNITY_PACKS in desktop/pyinstaller.spec."
    )


def test_no_withheld_pack_is_force_included() -> None:
    """The other direction, which matters more: a release cannot be taken back."""
    surplus = _force_included_slugs() - _shippable_slugs()
    assert not surplus, (
        f"{len(surplus)} pack(s) are force-included into the community wheel while carrying a "
        f"signal that says they should not be: {sorted(surplus)}. Either the pack is deprecated, or "
        f"it declares a partner_url and so names an outside rights holder. Remove the force-include "
        f"line, or change the signal in the pack if the decision has genuinely changed."
    )


@pytest.mark.parametrize("slug", sorted(_force_included_slugs()))
def test_every_shipped_pack_declares_an_open_licence(slug: str) -> None:
    """A pack in the community wheel has to say it is AGPL, in its own metadata."""
    pyproject = _PACKS_DIR / slug / "pyproject.toml"
    assert pyproject.is_file(), f"{slug} is force-included into the wheel and has no pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "AGPL-3.0-or-later" in text, (
        f"packs/{slug}/pyproject.toml does not declare AGPL-3.0-or-later, and the pack is shipped "
        f"inside the AGPL community wheel. Sort the licence out before the next release."
    )


def _desktop_bundled_slugs() -> set[str]:
    """Pack slugs the PyInstaller spec bundles, read out of the spec itself.

    A spec file is Python, and this reads it by AST like everything else here.
    Importing it is not an option: it runs at PyInstaller's mercy, expecting
    globals no unit test has.

    Returns:
        Every slug in ``_COMMUNITY_PACKS``.

    Raises:
        AssertionError: If the spec is gone, or the list has stopped being a
            literal this reader can resolve.
    """
    spec = _REPO_ROOT / "desktop" / "pyinstaller.spec"
    assert spec.is_file(), f"{spec} is gone, so the desktop bundle's pack list cannot be read at all"
    for node in ast.walk(ast.parse(spec.read_text(encoding="utf-8"), str(spec))):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "_COMMUNITY_PACKS" for target in node.targets):
            continue
        value = node.value
        assert isinstance(value, ast.Tuple | ast.List), (
            f"_COMMUNITY_PACKS in {spec} is no longer a literal tuple or list, so this reader cannot "
            f"see which packs the desktop bundle ships. Extend the reader rather than leaving the "
            f"two lists uncompared."
        )
        slugs = set()
        for element in value.elts:
            assert isinstance(element, ast.Constant) and isinstance(element.value, str), (
                f"_COMMUNITY_PACKS in {spec} holds an entry this reader cannot resolve to a slug."
            )
            slugs.add(element.value)
        return slugs
    raise AssertionError(f"no _COMMUNITY_PACKS assignment in {spec}; the desktop bundle's pack list has moved")


def test_the_desktop_bundle_ships_the_same_packs_as_the_wheel() -> None:
    """One registry, two hand-written copies of it, and nothing comparing them.

    ``backend/pyproject.toml`` decides which packs ship. The spec then repeats
    those slugs in ``_COMMUNITY_PACKS`` because PyInstaller cannot read a hatch
    force-include map, which is a fair reason for the second list to exist and
    no reason at all for it to go unchecked. A pack added to one and not the
    other ships to pip users and not to desktop users, or the reverse, and the
    only symptom is a pack that is missing on one platform. Nobody diffs two
    files in different languages on the strength of that.

    Both directions matter and they fail differently, so the message says which
    way round it is rather than printing a symmetric difference.
    """
    wheel = _force_included_slugs()
    desktop = _desktop_bundled_slugs()
    assert desktop, (
        "the spec reader returned no slugs at all, which is the instrument failing rather than the "
        "desktop bundle shipping nothing, and would make the comparison below read as clean."
    )
    assert desktop == wheel, (
        f"the wheel and the desktop bundle ship different packs. In the wheel and not the desktop "
        f"bundle: {sorted(wheel - desktop) or 'none'}. In the desktop bundle and not the wheel: "
        f"{sorted(desktop - wheel) or 'none'}. backend/pyproject.toml is the decision; bring "
        f"_COMMUNITY_PACKS in desktop/pyinstaller.spec back in line with it, or change both."
    )


# ── The third mirror: the Docker build context ──────────────────────────────
#
# A pack reaches a user by three routes, not two. The wheel's force-include map
# and the PyInstaller spec are held against each other above. The third is
# ``deploy/docker/Dockerfile.unified``, which names every pack in a COPY line of
# its own, and nothing in this file had ever looked at it.
#
# It fails differently from the other two, and harder. A COPY naming a path the
# build context does not carry aborts ``docker build`` outright, so a pack added
# to the map and not here does not ship a thinner image, it ships no image at
# all. That is not hypothetical: v16.2.0 published its PyPI package and its
# release page and produced no container, for precisely this reason.
#
# The directives are parsed rather than searched for, and the parser is the one
# scripts/check_docker_force_include_context.py already runs in the Repo hygiene
# lane rather than a second copy of it. A second parser is a second thing to
# drift, and that one already knows the distinctions that decide the answer.
#
# What is new here, and the reason these tests are not that script repeated:
# the script holds the Dockerfile against the force-include MAP. These hold it
# against the licence signals in the TREE, and against the other two mirrors. If
# the map and the Dockerfile ever move together, set equality between them stays
# green and only the tree can say that a pack is shipped or withheld wrongly.

_DOCKERFILE = _REPO_ROOT / "deploy" / "docker" / "Dockerfile.unified"
_DOCKER_CONTEXT_GATE = _REPO_ROOT / "scripts" / "check_docker_force_include_context.py"


@lru_cache(maxsize=1)
def _docker_copy_parser():
    """Load the Dockerfile COPY reader the Repo hygiene lane already uses.

    Imported by path rather than reimplemented. It already makes the three
    distinctions that decide which paths a build really carries: only the shared
    ``backend-base`` stage counts, a ``COPY --from=`` reads another stage rather
    than the build context, and a directive continued over several physical
    lines is one instruction.

    Raises:
        AssertionError: If the script has moved, which would otherwise surface
            as an import error rather than as the missing instrument it is.
    """
    assert _DOCKER_CONTEXT_GATE.is_file(), (
        f"{_DOCKER_CONTEXT_GATE} is gone. The Dockerfile's COPY directives are read with its "
        f"parser, so the comparisons below have no instrument and would sweep clean over nothing."
    )
    spec = importlib.util.spec_from_file_location("_docker_context_gate", _DOCKER_CONTEXT_GATE)
    assert spec is not None and spec.loader is not None, f"cannot load {_DOCKER_CONTEXT_GATE}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dockerfile_copied_slugs() -> set[str]:
    """Pack slugs the Docker build context carries, read from the COPY directives.

    Returns:
        Every slug copied by the shared base stage.

    Raises:
        AssertionError: If a copy from the packs tree is not one pack's ``src``.
            A whole-tree or glob copy is the shape the Dockerfile's own comment
            forbids, because it bakes the held-back packs into a public image
            layer permanently, and it would read here as no packs at all.
    """
    slugs = set()
    for path in _docker_copy_parser().copied_context_paths(str(_DOCKERFILE)):
        parts = Path(path).as_posix().split("/")
        if parts[0] != "packs":
            continue
        assert len(parts) == 3 and parts[2] == "src", (
            f"{_DOCKERFILE} copies {path!r} out of the packs tree, and this reader understands only "
            f"'packs/<slug>/src'. Copying the tree or a glob would ship whichever pack lands in it "
            f"next, and would be counted here as no packs at all. Extend the reader rather than "
            f"letting the shape go unchecked."
        )
        slugs.add(parts[1])
    return slugs


def test_the_docker_reader_sees_the_copy_directives_it_is_about_to_check() -> None:
    """Guard the instrument before the three comparisons that lean on it.

    Each of them is a set difference, and an empty set agrees with everything. A
    parser that stopped matching, or a stage that was renamed, would report the
    Dockerfile perfectly in line with both other mirrors.
    """
    slugs = _dockerfile_copied_slugs()
    print(f"\n{len(slugs)} pack slugs copied into the Docker build context by {_DOCKERFILE.name}")
    assert len(slugs) >= 10, (
        f"only {len(slugs)} pack slugs were read out of {_DOCKERFILE}: {sorted(slugs)}. The file "
        f"names far more than that, so the reader is no longer looking at what it thinks it is."
    )


def test_every_shippable_pack_is_copied_into_the_docker_image() -> None:
    """The direction that stops the image building at all."""
    missing = _shippable_slugs() - _dockerfile_copied_slugs()
    assert not missing, (
        f"{len(missing)} pack(s) carry no disqualifying signal and are not copied into the Docker "
        f"build context: {sorted(missing)}. Every one of them is force-included by the wheel, which "
        f"pip builds inside the image, so this does not ship an image missing those packs - "
        f"hatchling aborts with 'Forced include not found' and the build produces no image. Add "
        f"'COPY packs/<slug>/src/ packs/<slug>/src/' to the backend-base stage of "
        f"deploy/docker/Dockerfile.unified."
    )


def test_every_pack_the_dockerfile_copies_exists_on_disk() -> None:
    """A COPY naming a path that is not there is a broken build, not a licence error.

    This would also surface as a surplus below, because the shippable set is
    computed from the tree and a directory that is not in it cannot join. It
    gets its own assertion because that message would misdiagnose it, sending
    the reader to look for a DEPRECATED.txt or a partner_url inside a pack that
    does not exist, and because the consequence differs in kind: a withheld pack
    ships something it should not, an absent path ships nothing at all.

    Unlike the wheel and the spec, this failure mode is specific to a
    Dockerfile. COPY has no tolerant glob to fall back on; the daemon refuses
    the instruction and the build stops there.
    """
    absent = sorted(_dockerfile_copied_slugs() - {d.name for d in _pack_dirs()})
    assert not absent, (
        f"{len(absent)} slug(s) are copied by deploy/docker/Dockerfile.unified and hold no pack in "
        f"the tree: {absent}. COPY refuses a source the build context does not carry, so this stops "
        f"'docker build' on that line and no image is produced. Either the pack was removed and the "
        f"COPY line outlived it, or the slug is misspelt."
    )


def test_no_withheld_pack_is_copied_into_the_docker_image() -> None:
    """The other direction, which a public registry makes permanent.

    Restricted to slugs that really hold a pack, so that a line naming nothing
    is reported by the test above and by this one, each in its own terms.

    Worse here than in the wheel. Deleting a file in a later layer does not
    remove it from the layer that added it, and these images are published to a
    public registry, so a pack copied in once stays fetchable from that layer
    for as long as the tag exists. Nothing fails: the image builds, passes its
    healthcheck and ships.
    """
    surplus = sorted((_dockerfile_copied_slugs() & {d.name for d in _pack_dirs()}) - _shippable_slugs())
    assert not surplus, (
        f"{len(surplus)} pack(s) are copied into the Docker build context while carrying a signal "
        f"that says they should not be: {surplus}. Either the pack is deprecated, or it declares a "
        f"partner_url and so names an outside rights holder. Remove the COPY line, or change the "
        f"signal in the pack if the decision has genuinely changed."
    )


def test_the_three_mirrors_of_the_pack_list_agree() -> None:
    """One decision, three hand-written copies of it, in three languages.

    A hatch force-include map, a Python tuple and a set of COPY directives
    cannot read each other, so each is maintained by hand and any pair can drift
    apart. Until this test two of them were compared and the third was not, and
    a pack added to the map and the spec but not the Dockerfile passed every
    gate in this file while breaking the container build.

    The pairs are reported separately rather than as one symmetric difference,
    because which file is behind is the whole of what the reader needs.
    """
    wheel = _force_included_slugs()
    desktop = _desktop_bundled_slugs()
    docker = _dockerfile_copied_slugs()
    print(f"\nwheel {len(wheel)}, desktop {len(desktop)}, docker {len(docker)}")
    assert wheel and desktop and docker, (
        f"one of the three readers returned nothing at all - wheel {len(wheel)}, desktop "
        f"{len(desktop)}, docker {len(docker)}. That is an instrument failing rather than a mirror "
        f"shipping no packs, and it would make the comparison below read as clean."
    )
    assert wheel == desktop == docker, (
        f"the three mirrors of the pack list disagree. In the wheel and not the Docker image: "
        f"{sorted(wheel - docker) or 'none'}. In the Docker image and not the wheel: "
        f"{sorted(docker - wheel) or 'none'}. In the wheel and not the desktop bundle: "
        f"{sorted(wheel - desktop) or 'none'}. In the desktop bundle and not the wheel: "
        f"{sorted(desktop - wheel) or 'none'}. backend/pyproject.toml is the decision; bring "
        f"desktop/pyinstaller.spec and deploy/docker/Dockerfile.unified back in line with it."
    )


# ── The files a manifest names ──────────────────────────────────────────────
#
# A manifest does not only configure, it also names files: one JSON per entry
# in ``additional_locales``, a logo, a favicon, an onboarding script, and one
# reference document per ``validation_rule_packs`` entry. Nothing in the tree
# ever resolved one of those names against a file, and four of them pointed at
# nothing: china-gbt50500 named a zh locale, a logo and an onboarding script
# and carried none of the three, and retail-grocery-dach named a logo it did
# not carry. The packaging half of this file was gated and the asset half was
# not, so the packs shipped as configured and arrived incomplete.
#
# This is the captions.json defect again, the one recorded in
# .github/workflows/pypi-publish.yml: an artefact carrying a manifest for files
# it does not contain. That one is caught on the archive, on a tag. This one is
# caught in the tree, on every run, which is the half that can still stop a
# commit.
#
# Read by parsing and not by importing, the same way ``partner_url`` is read
# above, so this file keeps the no-database no-side-effect property its module
# docstring claims.

# Keywords whose value is one path, verbatim.
_SCALAR_PATH_KEYWORDS = ("logo_path", "favicon_path", "onboarding_script_path")

# The manifest calls this reader is willing to read keywords out of. Named
# rather than "any call", so a keyword that happens to share a name with
# something else in the module cannot be mistaken for a declaration.
_MANIFEST_CALLS = frozenset({"PartnerPackManifest", "PartnerBranding"})

# ``git ls-files`` needs a repository. An sdist unpacked somewhere is not one,
# and the tracked-ness question is meaningless there rather than failing.
_HAS_GIT = (_REPO_ROOT / ".git").exists()


def _declared_asset_paths(manifest_path: Path) -> list[tuple[str, str]]:
    """Every ``(field, pack-relative path)`` the manifest names, without executing it.

    A keyword that is absent declares nothing, and that is the legal, intended
    state: a pack with no logo says so by not writing ``logo_path`` at all.
    This is the one place where this reader deliberately differs from
    ``_declared_partner_url``, which treats absence as a fault because every
    pack has to state that one.

    A keyword that IS present but holds something static reading cannot
    evaluate - an f-string, a name, a call - raises rather than being skipped.
    A path the reader cannot see is a path the gate is not checking, and
    passing quietly over it is the exact blindness this block exists to end.

    Args:
        manifest_path: The pack's ``manifest.py``.

    Returns:
        Field label and pack-relative path, in declaration order. The label is
        for the failure message and is not itself a path.

    Raises:
        AssertionError: If a declared value cannot be read statically.
    """
    tree = ast.parse(manifest_path.read_text(encoding="utf-8"), str(manifest_path))
    found: list[tuple[str, str]] = []

    def _refuse(field: str, node: ast.AST) -> NoReturn:
        raise AssertionError(
            f"{manifest_path} declares {field} as {ast.dump(node)}, which this reader cannot "
            f"evaluate. It names a file that has to ship inside the pack, so extend the reader "
            f"rather than letting the path go unchecked."
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        call_name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if call_name not in _MANIFEST_CALLS:
            continue
        for keyword in node.keywords:
            field, value = keyword.arg, keyword.value
            if field in _SCALAR_PATH_KEYWORDS:
                if not isinstance(value, ast.Constant) or not (value.value is None or isinstance(value.value, str)):
                    _refuse(field, value)
                if isinstance(value.value, str):
                    found.append((field, value.value))
            elif field == "additional_locales":
                if not isinstance(value, ast.Dict):
                    _refuse(field, value)
                for code_node, path_node in zip(value.keys, value.values, strict=True):
                    if (
                        not isinstance(code_node, ast.Constant)
                        or not isinstance(path_node, ast.Constant)
                        or not isinstance(path_node.value, str)
                    ):
                        _refuse(field, value)
                    found.append((f"additional_locales[{code_node.value}]", path_node.value))
            elif field == "validation_rule_packs":
                if not isinstance(value, ast.List):
                    _refuse(field, value)
                for element in value.elts:
                    if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                        _refuse(field, value)
                    # The field holds document ids, one per file stem, and the
                    # engine reads them from ``rule_packs/<id>.json``. The
                    # manifest schema documents that shape; it is the only
                    # declared path that is derived rather than written out.
                    found.append((f"validation_rule_packs[{element.value}]", f"rule_packs/{element.value}.json"))
    return found


def _package_dir(slug: str) -> Path:
    """The ``src/openconstructionerp_*`` directory declared paths are relative to."""
    manifest_path = _manifest_path(_PACKS_DIR / slug)
    assert manifest_path is not None, f"{slug} is force-included into the wheel and has no manifest.py"
    return manifest_path.parent


@lru_cache(maxsize=1)
def _tracked_pack_files() -> frozenset[str]:
    """Every path under ``packs/`` that git holds, as posix paths from the root.

    Disk and index have to be asked separately because force-include copies
    from the working tree: a file that exists here and is not committed ships
    out of one developer's build and is absent from every CI checkout and from
    every release built from a clean clone.
    """
    result = subprocess.run(
        ["git", "ls-files", "packs/"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(line.strip() for line in result.stdout.splitlines() if line.strip())


def test_the_asset_reader_sees_the_declarations_it_is_about_to_check() -> None:
    """Guard the instrument before the two comparisons that lean on it.

    Both assertions below pass trivially over an empty list, so a reader that
    silently stops matching would report every pack clean. Assert that it still
    finds declarations, and that it finds them for every shipped pack rather
    than for most of them.
    """
    per_pack = {
        slug: _declared_asset_paths(_manifest_path(_PACKS_DIR / slug)) for slug in sorted(_force_included_slugs())
    }
    total = sum(len(v) for v in per_pack.values())
    speaking = sorted(slug for slug, paths in per_pack.items() if paths)
    print(f"\n{total} declared asset paths across {len(per_pack)} shipped packs, {len(speaking)} of which declare one")

    # Deliberately not "every pack declares something". A pack that carries no
    # logo, no locale overlay and no onboarding script declares none of them
    # and is correct to; china-gbt50500 is exactly that. Asserting per pack
    # would have made this guard fail the moment a pack told the truth.
    assert total >= 100, (
        f"the asset reader found only {total} declared paths across {len(per_pack)} packs. The tree "
        f"carries well over a hundred, so the reader has stopped seeing what it thinks it is and "
        f"both checks below would sweep clean over nothing."
    )
    assert len(speaking) >= 10, (
        f"only {len(speaking)} of {len(per_pack)} packs yielded any declaration at all: {speaking}. "
        f"One silent pack is a pack with no assets; nearly all of them silent is the reader having "
        f"stopped matching the manifests."
    )


@pytest.mark.parametrize("slug", sorted(_force_included_slugs()))
def test_every_declared_asset_is_carried_by_the_pack(slug: str) -> None:
    """A manifest may not name a file the pack does not ship."""
    pkg_dir = _package_dir(slug)
    absent = [
        (field, rel)
        for field, rel in _declared_asset_paths(_manifest_path(_PACKS_DIR / slug))
        if not (pkg_dir / rel).is_file()
    ]
    assert not absent, (
        f"packs/{slug} declares {len(absent)} file(s) it does not carry: "
        f"{[f'{field} -> {rel}' for field, rel in absent]}. The pack still loads and the frontend "
        f"still falls back, so nothing here raises at runtime; the user simply gets less than the "
        f"manifest promised. Either ship the file, or stop declaring it."
    )


@pytest.mark.skipif(not _HAS_GIT, reason="no .git here, so tracked-ness has no meaning to check")
@pytest.mark.parametrize("slug", sorted(_force_included_slugs()))
def test_every_declared_asset_is_tracked_in_git(slug: str) -> None:
    """...and it has to be committed, because a CI checkout has nothing else.

    The disk check above passes on a file sitting untracked in a working tree.
    Force-include copies it into that developer's wheel and into no one else's,
    which is a defect that reproduces nowhere and ships anyway.
    """
    tracked = _tracked_pack_files()
    assert tracked, (
        "git ls-files returned nothing under packs/, in a tree that has packs on disk. That is the "
        "instrument failing, not the packs being untracked, and every comparison below it would "
        "read as clean."
    )
    pkg_dir = _package_dir(slug)
    untracked = []
    for field, rel in _declared_asset_paths(_manifest_path(_PACKS_DIR / slug)):
        repo_rel = (pkg_dir / rel).relative_to(_REPO_ROOT).as_posix()
        if repo_rel not in tracked:
            untracked.append((field, repo_rel))
    assert not untracked, (
        f"packs/{slug} declares {len(untracked)} file(s) that git does not track: "
        f"{[f'{field} -> {rel}' for field, rel in untracked]}. force-include ships from the working "
        f"tree, so these reach a wheel built here and no wheel built from a clean checkout."
    )


def _plant_pack(packs_dir: Path) -> None:
    """Create the smallest tree that counts as a real pack tree."""
    pkg = packs_dir / "demo-pack" / "src" / "openconstructionerp_demo_pack"
    pkg.mkdir(parents=True)
    (pkg / "manifest.py").write_text("MANIFEST = {}\n", encoding="utf-8")


def _discovery_at(root: Path) -> Path:
    """Path discovery.py would occupy under an install root holding ``app``."""
    return root / "app" / "core" / "partner_pack" / "discovery.py"


def test_the_packs_dir_resolves_in_an_installed_layout(tmp_path: Path) -> None:
    """The case that was broken for every user and that nothing measured.

    In a wheel install discovery.py sits at
    ``site-packages/app/core/partner_pack/discovery.py`` and the packs are
    force-included beside the package at ``site-packages/packs``. The old code
    counted five parents from the file, walked out of site-packages entirely
    and landed on the virtualenv's ``Lib``, where no packs directory has ever
    existed, so the UI reported none. No source-tree test could see it.
    """
    site_packages = tmp_path / "Lib" / "site-packages"
    _plant_pack(site_packages / "packs")

    resolved = _packs_dir_for(_discovery_at(site_packages), _DISCOVERY_MODULE)

    assert resolved == (site_packages / "packs").resolve(), (
        f"an installed layout resolved to {resolved}, not the packs directory shipped beside the "
        f"app package. This is the exact shape of the defect this test exists for."
    )


def test_the_packs_dir_resolves_in_a_source_checkout(tmp_path: Path) -> None:
    """The layout that worked before must keep working. Both, or neither."""
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    _plant_pack(repo / "packs")

    resolved = _packs_dir_for(_discovery_at(repo / "backend"), _DISCOVERY_MODULE)

    assert resolved == (repo / "packs").resolve(), (
        f"a source checkout resolved to {resolved}, not the repo's packs tree. The fix for the "
        f"install layout must not cost the checkout the behaviour it already had."
    )


def test_a_directory_that_only_has_the_name_is_not_the_tree(tmp_path: Path) -> None:
    """Shape, not existence. Existence alone is how the original arithmetic lied.

    An install root can hold an unrelated ``packs`` directory, and accepting it
    would leave discovery scanning the wrong place while reporting that it
    found somewhere to scan. The candidate has to contain a pack.
    """
    repo = tmp_path / "repo"
    (repo / "backend" / "packs" / "not-a-pack").mkdir(parents=True)
    _plant_pack(repo / "packs")

    resolved = _packs_dir_for(_discovery_at(repo / "backend"), _DISCOVERY_MODULE)

    assert resolved == (repo / "packs").resolve(), (
        f"resolved to {resolved}. A directory named 'packs' holding no pack was accepted over the "
        f"real tree one level up, so the shape check is not doing its job."
    )


def test_no_pack_tree_anywhere_resolves_to_none(tmp_path: Path) -> None:
    """An install carrying no packs must say so, not point somewhere arbitrary."""
    resolved = _packs_dir_for(_discovery_at(tmp_path / "site-packages"), _DISCOVERY_MODULE)
    assert resolved is None, f"expected None for a layout with no packs anywhere, got {resolved}"


def test_the_resolver_reads_its_depth_from_the_module_name(tmp_path: Path) -> None:
    """Pin the derivation itself, which is what stops the arithmetic drifting again.

    The depth comes from the dotted name, so a module at a different nesting
    resolves differently with no constant edited anywhere.

    Stated exactly, because the loose version of this claim is false and was
    measured to be: the resolver tries two candidates, the install root and one
    directory above it, so a depth constant that is wrong by a single level is
    absorbed by that window and this test cannot see it. What it does catch is a
    written-down depth that no longer matches where the module actually sits,
    which is the shape of the original defect. Hence a module nested two levels
    deeper than the real one rather than one.
    """
    site_packages = tmp_path / "site-packages"
    _plant_pack(site_packages / "packs")

    deeper = site_packages / "app" / "core" / "partner_pack" / "one" / "two" / "discovery.py"
    resolved = _packs_dir_for(deeper, "app.core.partner_pack.one.two.discovery")

    assert resolved == (site_packages / "packs").resolve(), (
        f"a six-component module name resolved to {resolved}. The depth is supposed to come from "
        f"the module's own name rather than a written-down number of directory levels."
    )
