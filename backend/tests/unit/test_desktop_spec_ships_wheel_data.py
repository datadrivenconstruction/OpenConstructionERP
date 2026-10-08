"""The desktop bundle must ship the runtime data the wheel force-includes.

A wheel and a frozen sidecar are two ways of shipping one backend, and they
collect files by two unrelated mechanisms. Hatchling walks the ``app`` package
and adds whatever ``force-include`` names on top of it; PyInstaller adds only
what ``desktop/pyinstaller.spec`` lists. Anything the runtime reads from a path
that resolves OUTSIDE the ``app`` package therefore has to be named twice, once
in each file, and until this test there was nothing that made the second naming
happen.

It is written against a failure that reached users. ``app/core/i18n.py``
resolves its catalogue as a ``locales`` directory sitting NEXT TO the ``app``
package, the wheel force-included it, and the spec never did, so no desktop
build had ever carried it. That stayed invisible while a missing catalogue was
a warning that refilled the directory from an embedded copy, and became a
sidecar that exits during startup the moment refilling was correctly replaced
by a hard error. Both halves were defensible on their own; nothing compared
them.

The spec is executed rather than read. A test that greps the spec for a path
passes on a spec that computes the same path and then never appends it, which
is the failure mode being guarded against, so the real module runs with the
PyInstaller API stubbed out and the assertions read the list it actually built.

Blind spot, stated here rather than left to be rediscovered: the denominator is
the wheel's force-include map. A path the runtime reads that is missing from
BOTH files has no anchor and is invisible to this test.

A path may be force-included into the wheel and deliberately left out of the
frozen bundle. Those live in ``_NOT_FROZEN_INTO_THE_DESKTOP_BUNDLE`` below,
each with its reason attached to the entry rather than described here. That
placement is deliberate too: this docstring used to carry the reasoning for the
alembic case, it went stale the day the wheel started force-including the tree,
and a stale docstring is exactly how a decision becomes invisible. Reasons that
have to stay true belong next to the thing that makes them testable.
"""

from __future__ import annotations

import sys
import tomllib
import types
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
SPEC = ROOT / "desktop" / "pyinstaller.spec"
PYPROJECT = BACKEND / "pyproject.toml"

# Paths the wheel force-includes that the desktop bundle deliberately does not
# freeze, each mapped to why. Exact names only, never a prefix or a pattern:
# this gate exists to catch the file that gained a force-include and never
# gained a spec line, which is how a desktop build shipped with no translation
# catalogue and started for nobody, and an exemption anything could join would
# disarm exactly that. Adding an entry here is a decision about what a release
# ships and reads like one in review.
#
# The two entries below are one decision, not two. The ini names the tree in
# ``script_location``, so they ship together or not at all.
_NOT_FROZEN_INTO_THE_DESKTOP_BUNDLE = {
    "alembic": (
        "The desktop has no path that runs a migration. It installs with create_all plus "
        "postgres_auto_migrate and records the position with a stamp, so freezing the script "
        "tree in would not make a revision run. It would only make alembic_head_matches answer "
        "confidently and wrongly, in both directions: true on a database create_all built and "
        "the stamp put at head, where no revision ever ran, and false on an older install where "
        "postgres_auto_migrate added the columns and left the stamp where it was, which is a "
        "permanent degraded on a healthy machine. Without the tree the head cannot be determined "
        "and app/main.py reports None, which is the honest answer and the one the desktop can "
        "stand behind."
    ),
    "alembic.ini": (
        "Goes with the tree it points at, and is harmful without it. The ini sets "
        "script_location to %(here)s/alembic, so shipping it into a bundle with no alembic/ "
        "beside it turns ScriptDirectory.from_config into CommandError: Path doesn't exist. In "
        "stamp_head_if_unstamped that raise lands after ensure_wide_version_table has issued its "
        "ALTER, inside the one engine.begin() block main.py wraps them in, so the version-table "
        "widening of issue #399 is rolled back on every boot of an upgraded database."
    ),
}


def _wheel_force_include() -> dict[str, str]:
    """Return the wheel's force-include map, keyed by path relative to backend/."""
    with open(PYPROJECT, "rb") as handle:
        data = tomllib.load(handle)
    targets = data["tool"]["hatch"]["build"]["targets"]
    return dict(targets["wheel"]["force-include"])


def _spec_datas() -> list[tuple[str, str]]:
    """Execute the spec with the PyInstaller API stubbed out and return its ``datas``.

    The spec imports ``collect_submodules`` and calls ``Analysis``/``PYZ``/``EXE``
    at module level. None of that can run here, and none of it decides what the
    bundle carries, so each is replaced by the smallest stand-in that lets the
    module reach the end: the point is to run the real path/append logic above
    them and read the result.
    """
    # Written through __dict__ rather than as attributes because that is what
    # populating a module object actually is, and a type checker reading
    # ModuleType has no way to know these names are meant to exist.
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.__dict__["collect_submodules"] = lambda _package: []
    utils = types.ModuleType("PyInstaller.utils")
    utils.__dict__["hooks"] = hooks
    pyinstaller = types.ModuleType("PyInstaller")
    pyinstaller.__dict__["utils"] = utils

    captured: dict[str, list[tuple[str, str]]] = {}

    class _Analysis:
        def __init__(self, *_args, **kwargs):
            captured["datas"] = [tuple(entry) for entry in (kwargs.get("datas") or [])]
            # EXE() folds these three into the single file; PYZ() reads .pure.
            self.pure = []
            self.scripts = []
            self.binaries = []
            self.zipfiles = []
            self.datas = captured["datas"]

    namespace: dict[str, object] = {
        "__file__": str(SPEC),
        "__name__": "openconstructionerp_desktop_spec",
        "SPECPATH": str(SPEC.parent),
        "DISTPATH": str(SPEC.parent / "dist"),
        "workpath": str(SPEC.parent / "build"),
        "Analysis": _Analysis,
        "PYZ": lambda *_a, **_kw: None,
        "EXE": lambda *_a, **_kw: None,
        "COLLECT": lambda *_a, **_kw: None,
    }

    fakes = {
        "PyInstaller": pyinstaller,
        "PyInstaller.utils": utils,
        "PyInstaller.utils.hooks": hooks,
    }
    source = SPEC.read_text(encoding="utf-8")
    with patch.dict(sys.modules, fakes):
        exec(compile(source, str(SPEC), "exec"), namespace)  # noqa: S102

    if "datas" not in captured:
        pytest.fail("the spec ran without ever calling Analysis, so it declared no data files")
    return captured["datas"]


def test_the_spec_declares_data_files_at_all() -> None:
    """Guard the instrument before the assertions that lean on it.

    A stub that swallows the call, or a spec that stops building its list part
    way through, would leave every comparison below vacuously true. Saying how
    many entries were read is what separates "checked and agreed" from "found
    nothing to check".
    """
    datas = _spec_datas()
    print(f"\ndesktop spec declares {len(datas)} data entries")
    assert len(datas) >= 3, (
        f"the spec declared {len(datas)} data entries. It is expected to ship the frontend dist, "
        f"the app package, the locale catalogue and pyproject.toml, so a number this small means "
        f"the spec changed shape and this test is no longer reading what it thinks it is."
    )


def test_the_bundle_ships_what_the_wheel_force_includes() -> None:
    """Every path the wheel force-includes must also reach the frozen bundle.

    Force-include exists precisely for files the package walk cannot see, which
    makes it the register of things the frozen build is most likely to miss:
    they sit outside ``app``, so the one line that ships ``app`` does not carry
    them and no error appears until the runtime reaches for one.
    """
    force_include = _wheel_force_include()
    datas = _spec_datas()
    by_source = {Path(source).resolve(): dest for source, dest in datas}

    verified: list[str] = []
    unverifiable: list[str] = []
    exempt: list[str] = []
    for relative, wheel_dest in sorted(force_include.items()):
        source = (BACKEND / relative).resolve()
        if relative in _NOT_FROZEN_INTO_THE_DESKTOP_BUNDLE:
            # Held out on purpose. Assert the omission is still real rather than
            # skipping quietly: an entry that stops describing what the bundle
            # does is a hole in this gate, so it has to fail here and be read
            # again rather than sit forever.
            assert source not in by_source, (
                f"{relative!r} is listed in _NOT_FROZEN_INTO_THE_DESKTOP_BUNDLE as deliberately "
                f"withheld from the frozen bundle, and desktop/pyinstaller.spec now ships it to "
                f"{by_source.get(source)!r}. One of the two is wrong. The reason the entry gives is: "
                f"{_NOT_FROZEN_INTO_THE_DESKTOP_BUNDLE[relative]} If that reason no longer holds, "
                f"delete the entry and let this test require the path like any other."
            )
            exempt.append(relative)
            continue
        if not source.exists():
            # The frontend dist is absent on a tree nobody has built yet. That
            # is not this test's business to fail on, but it is its business to
            # say so, because a silent skip is how a check reports success over
            # something it never looked at.
            unverifiable.append(f"{relative} (not present on this machine)")
            continue
        assert source in by_source, (
            f"backend/pyproject.toml force-includes {relative!r} into the wheel at {wheel_dest!r}, "
            f"and desktop/pyinstaller.spec never adds it, so the frozen sidecar ships without it. "
            f"Force-included paths sit outside the app package, which is why shipping app/ does not "
            f"carry them. Add datas.append((str(BACKEND / {relative!r}), {wheel_dest!r})) to the spec."
        )
        assert by_source[source] == wheel_dest, (
            f"{relative!r} lands at {wheel_dest!r} in the wheel and at {by_source[source]!r} in the "
            f"frozen bundle. The runtime computes one path for both, so the two destinations have to "
            f"agree or the desktop build looks for the files somewhere they are not."
        )
        verified.append(f"{relative} -> {wheel_dest}")

    print(f"\nverified {len(verified)} of {len(force_include)} force-included paths: {verified}")
    if unverifiable:
        print(f"could not verify {len(unverifiable)}: {unverifiable}")
    if exempt:
        print(f"deliberately not frozen, {len(exempt)}: {exempt}")
    assert verified, (
        "no force-included path could be checked, so this test proved nothing. Either the "
        "force-include map is empty, every source it names is missing from this checkout, or "
        "everything left in it has been exempted."
    )


def test_every_deliberate_omission_is_still_a_deliberate_omission() -> None:
    """An exemption that cannot expire is a hole, so make this one expire.

    Each entry above claims the wheel force-includes a path that the desktop
    bundle deliberately does not carry. Remove the force-include and that claim
    stops being about anything: the exemption would go on suppressing a check
    for a file no longer in the denominator, and the next path to be added under
    one of these names would inherit the exemption without anyone deciding it
    should.

    So the entries have to earn their place on every run. This is the failing
    direction of the exemption, and without it the list above would only ever be
    able to make this file quieter.
    """
    force_include = _wheel_force_include()

    for relative in sorted(_NOT_FROZEN_INTO_THE_DESKTOP_BUNDLE):
        assert relative in force_include, (
            f"{relative!r} is listed in _NOT_FROZEN_INTO_THE_DESKTOP_BUNDLE, and "
            f"backend/pyproject.toml no longer force-includes it into the wheel, so the entry "
            f"describes a decision nobody is making any more. Delete it. Leaving it costs the "
            f"gate a name it will silently forgive if that path ever comes back."
        )

    print(f"\n{len(_NOT_FROZEN_INTO_THE_DESKTOP_BUNDLE)} deliberate omissions, all still force-included")


def test_the_locale_catalogue_lands_where_the_runtime_looks_for_it() -> None:
    """Pin the invariant itself, not just the agreement between two files.

    The test above compares the spec against the wheel, which is one step removed
    from what actually matters: that the directory arrives at the path
    ``load_translations`` computes. This one asks ``i18n.py`` where that is and
    checks the bundle against the answer, so the check survives the wheel map
    being edited and states plainly why a sibling directory needs its own line.
    """
    from app.core.i18n import LOCALES_DIR

    app_package = Path(__import__("app").__file__).resolve().parent
    locales = LOCALES_DIR.resolve()

    assert locales.parent == app_package.parent, (
        f"the catalogue resolves to {locales}, which is no longer a sibling of the app package at "
        f"{app_package}. If it moved inside the package it is carried by the one line that ships "
        f"app/ and both this test and the spec entry should go; if it moved elsewhere the spec "
        f"destination has to move with it."
    )

    expected_dest = locales.name
    dests = {dest for _source, dest in _spec_datas()}
    assert expected_dest in dests, (
        f"load_translations() reads its catalogue from a directory named {expected_dest!r} sitting "
        f"beside the app package, which in a frozen bundle is sys._MEIPASS/{expected_dest}. The spec "
        f"declares destinations {sorted(dests)} and none of them puts it there, so the sidecar will "
        f"raise FileNotFoundError during startup and the launcher will report only that the backend "
        f"did not start in time."
    )


# ── The one path that must stay empty ────────────────────────────────────────

# Destination prefix of the regional resource catalogue. It is data the runtime
# reads from beside the app package, so it looks exactly like locales, alembic
# and the packs, and it is the one such directory that a release artefact must
# NOT carry.
_CATALOGUE_PATH_FRAGMENT = "data/catalog"


def test_no_release_artefact_ships_the_regional_catalogue() -> None:
    """The licensing decision, pinned in the direction a release cannot undo.

    Two documents state it and nothing enforced it. The header of
    ``desktop/pyinstaller.spec`` says ``data/catalog`` stays out of the
    installer because bundling it is a licensing decision and not a packaging
    one, and NOTICE records the licensing basis of the largest base in the
    catalogue as PENDING. Roughly three quarters of the bytes sit on that base.

    This became worth a gate the moment the catalogue resolver was taught to
    look beside the app package. Before that, a force-include of
    ``data/catalog/regions`` would have shipped bytes nothing read, which is
    inert; now it would work, so the wrong line in either packaging file would
    quietly put the data into a wheel on PyPI, which cannot be withdrawn.

    The other half of the same decision is pinned in
    ``test_catalog_offline_lookup.test_catalog_regions_are_not_bundled_in_the_package``,
    which covers the catalogue appearing INSIDE the app package, where the one
    line that ships ``app/`` would carry it with no entry naming it. Between the
    two, both ways in are watched.

    Removing this test is a decision about what a release contains and should
    read like one in review. If the licensing basis is settled and the answer is
    that the data may ship, delete it in the same commit that records the basis
    in NOTICE.
    """
    offenders: list[str] = []
    for source, dest in _wheel_force_include().items():
        if _CATALOGUE_PATH_FRAGMENT in Path(source).as_posix() or _CATALOGUE_PATH_FRAGMENT in Path(dest).as_posix():
            offenders.append(f"backend/pyproject.toml force-include: {source} -> {dest}")
    for source, dest in _spec_datas():
        if _CATALOGUE_PATH_FRAGMENT in Path(source).as_posix() or _CATALOGUE_PATH_FRAGMENT in Path(dest).as_posix():
            offenders.append(f"desktop/pyinstaller.spec datas: {source} -> {dest}")

    assert not offenders, (
        "a release artefact would carry the regional resource catalogue:\n  "
        + "\n  ".join(offenders)
        + "\nThat data is derived from national norm systems and NOTICE records the basis for the "
        "largest base in it as PENDING. A wheel on PyPI and a signed installer cannot be taken "
        "back, so it stays out until the basis is written down. See the header of "
        "desktop/pyinstaller.spec and the Data Sources section of NOTICE."
    )
