"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The match tuning data has to be found from an installed layout, not just a checkout.

``data/match`` holds four files that tune matching, and all four are optional:
every reader falls back to hardcoded constants when they are absent. That
makes the failure this file guards completely silent. Three readers resolved
the directory by counting parent directories, which reaches the repo root from
a source checkout and the virtualenv's ``Lib`` after a ``pip install``, so no
packaged install ever loaded the tuning, nothing raised, and the only trace
was a debug line nobody had switched on.

The reason it survived long enough to be fixed three times in this codebase is
written into how these tests are built. In a source checkout the old
arithmetic and the new resolver return the same directory, so any test run
from the repo passes either way and proves nothing about the case that was
broken. Only :func:`app.core.match_service.data_paths.match_data_dir_for`
takes the layout as an argument, and only the tests that build a synthetic
install below can fail for the original defect. The checkout test is here as
an instrument guard, and it says so.

The other half is packaging. Fixing the resolver without shipping the bytes
leaves a pip install with a correct pointer at an absent directory, so
``test_the_wheel_destination_is_a_layout_the_resolver_can_read`` ties the
force-include destination in backend/pyproject.toml to the layout the resolver
accepts. The wheel and the frozen bundle are compared against each other
separately, in test_desktop_spec_ships_wheel_data.py.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from app.core.match_service.data_paths import (
    KNOWN_DATA_FILES,
    _package_dir_of,
    match_data_dir,
    match_data_dir_for,
)

ROOT = Path(__file__).resolve().parents[3]
TRACKED_DATA = ROOT / "data" / "match"
PYPROJECT = ROOT / "backend" / "pyproject.toml"

# Two real readers at two different depths. The pair is the point: a resolver
# that hardcoded either depth would serve one of them and quietly mislead the
# other, which is the state this codebase was actually in.
_MODULE_NAME = "app.core.match_service.data_paths"
_DEEPER_MODULE_NAME = "app.core.match_service.boosts.region"


def _module_file(package_dir: Path, dotted: str) -> Path:
    """Create the file ``dotted`` would occupy if its top package sat at ``package_dir``.

    Args:
        package_dir: Directory standing in for the installed ``app`` package.
        dotted: Dotted module name, whose first component is ``package_dir``.

    Returns:
        The created file. It is empty and never imported; only its position
        matters, and it is created rather than merely named so the directory
        walk it implies is real.
    """
    parts = dotted.split(".")
    path = package_dir.joinpath(*parts[1:-1]) / f"{parts[-1]}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _plant_data(directory: Path, names: tuple[str, ...] = KNOWN_DATA_FILES) -> Path:
    """Create ``directory`` holding ``names``, and return it resolved."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("{}\n", encoding="utf-8")
    return directory.resolve()


def test_a_pip_install_layout_resolves(tmp_path: Path) -> None:
    """The case that has been broken for the whole life of the feature.

    After ``pip install`` the package sits directly under ``site-packages``
    and the force-included data sits beside it. The old count of five parents
    from a four-component module reached ``Lib``, one level above
    ``site-packages``, where nothing is. That miss is asserted here as well as
    the hit, so the test states which layout it is about rather than only that
    the answer came out right.
    """
    site_packages = tmp_path / "Lib" / "site-packages"
    module_file = _module_file(site_packages / "app", _MODULE_NAME)
    planted = _plant_data(site_packages / "data" / "match")

    stale = module_file.resolve().parents[4] / "data" / "match"
    assert not stale.exists(), (
        f"this test is meant to stand on a layout where the old arithmetic misses, and {stale} "
        f"exists, so it would have passed before the fix too."
    )
    assert match_data_dir_for(module_file, _MODULE_NAME) == planted


def test_a_source_checkout_layout_resolves(tmp_path: Path) -> None:
    """The package is one level deeper in a checkout, so a second candidate is needed.

    ``backend/app`` has ``backend`` above it and the data at the repo root
    above that, while an install has the data directly beside the package.
    One candidate cannot serve both, which is why the resolver tries two.
    """
    repo = tmp_path / "repo"
    module_file = _module_file(repo / "backend" / "app", _MODULE_NAME)
    planted = _plant_data(repo / "data" / "match")

    assert match_data_dir_for(module_file, _MODULE_NAME) == planted


def test_two_readers_at_different_depths_land_on_the_same_directory(tmp_path: Path) -> None:
    """The depth has to come from the module name, because the readers disagree on it.

    ``boosts/region.py`` sits one directory deeper than the other two readers
    and therefore carried a different constant, which is exactly why it looked
    as correct as they did. Any resolver that fixes on one depth fails one of
    these two assertions.
    """
    assert len(_MODULE_NAME.split(".")) != len(_DEEPER_MODULE_NAME.split(".")), (
        "both names have the same number of components, so this test could not tell a derived "
        "depth from a hardcoded one. Pick two readers at genuinely different depths."
    )

    site_packages = tmp_path / "site-packages"
    shallow = _module_file(site_packages / "app", _MODULE_NAME)
    deeper = _module_file(site_packages / "app", _DEEPER_MODULE_NAME)
    planted = _plant_data(site_packages / "data" / "match")

    # A wrong depth of exactly one is absorbed by the second candidate root,
    # measured: hardcoding this resolver to the shallow reader's depth leaves
    # every assertion in this file green, because the deeper reader then lands
    # one level low and its second candidate is the right directory anyway.
    # A populated ``app/data`` is what removes that cover, and it is not a
    # hypothetical shape: ``app/data/cwicr`` is a real directory in this tree.
    # With one there, a counted depth reaches the decoy and stops.
    decoy = _plant_data(site_packages / "app" / "data" / "match")
    assert decoy != planted

    assert match_data_dir_for(shallow, _MODULE_NAME) == planted
    assert match_data_dir_for(deeper, _DEEPER_MODULE_NAME) == planted


def test_a_directory_with_the_right_name_and_none_of_the_files_is_not_ours(tmp_path: Path) -> None:
    """Candidates are checked for content, and the first one wins only if it has some.

    Without that, the first candidate to exist answers, and a ``data/match``
    left behind by anything else takes precedence over the real directory one
    level up. The failure would be an empty overlay rather than an error,
    which is the same silence this whole file is about.
    """
    repo = tmp_path / "repo"
    module_file = _module_file(repo / "backend" / "app", _MODULE_NAME)

    decoy = repo / "backend" / "data" / "match"
    decoy.mkdir(parents=True)
    (decoy / "README.md").write_text("nothing the match service reads\n", encoding="utf-8")

    real = _plant_data(repo / "data" / "match")

    assert match_data_dir_for(module_file, _MODULE_NAME) == real


def test_an_install_without_the_data_answers_none_rather_than_guessing(tmp_path: Path) -> None:
    """A minimal install is a supported state and must not produce a wrong path."""
    module_file = _module_file(tmp_path / "site-packages" / "app", _MODULE_NAME)

    assert match_data_dir_for(module_file, _MODULE_NAME) is None


def test_a_module_name_with_no_package_answers_none(tmp_path: Path) -> None:
    """``__main__`` carries no package, so there is no depth to derive and no guess to make.

    Asserted one level down as well as at the public function, because the
    public answer alone cannot tell the guard from luck. A one-component name
    makes the subtraction produce ``parents[-1]``, which is a valid index and
    resolves to the filesystem root; the search below it then finds nothing on
    this machine and returns ``None`` for the wrong reason. On a machine with a
    ``data/match`` at the root of the drive, the same code would hand every
    ``__main__`` module a directory belonging to nobody.
    """
    module_file = _module_file(tmp_path / "app", _MODULE_NAME)

    assert _package_dir_of(module_file, "__main__") is None, (
        "a name with no package must yield no package directory. Falling through to parents[-1] "
        "answers with the filesystem root, which looks like a miss here only because nothing "
        "happens to be planted there."
    )
    assert match_data_dir_for(module_file, "__main__") is None


def test_this_checkout_resolves_and_holds_every_known_file() -> None:
    """Instrument guard, and deliberately not the load-bearing test in this file.

    It passed before the fix as well, because a source checkout is the one
    layout the old arithmetic got right. What it is for is the opposite
    direction: if it ever fails, the tests above are building layouts against
    a resolver that cannot find the real thing, and their agreement would mean
    nothing.
    """
    directory = match_data_dir()

    assert directory == TRACKED_DATA.resolve(), (
        f"the resolver answered {directory} and the tracked data is at {TRACKED_DATA}. Either the "
        f"data moved or this test is running against an installed copy of app rather than the tree."
    )
    missing = [name for name in KNOWN_DATA_FILES if not (directory / name).is_file()]
    assert not missing, f"tracked data directory is missing {missing}"


def test_the_known_file_list_and_the_tracked_directory_agree() -> None:
    """Both directions, because the shape check is only as good as this list.

    A tuning file added to the tree without a line in ``KNOWN_DATA_FILES``
    weakens the content check silently, and a name left in the list after its
    file is deleted makes a directory holding nothing useful look real.
    """
    on_disk = {path.name for path in TRACKED_DATA.iterdir() if path.is_file()}

    assert set(KNOWN_DATA_FILES) == on_disk, (
        f"KNOWN_DATA_FILES says {sorted(KNOWN_DATA_FILES)} and data/match holds {sorted(on_disk)}. "
        f"The list decides whether a candidate directory is recognised as ours, so it has to be "
        f"the whole set. A new file also needs a reader; it needs nothing further to ship, because "
        f"the force-include names the directory rather than the files in it."
    )


def test_the_wheel_destination_is_a_layout_the_resolver_can_read(tmp_path: Path) -> None:
    """Tie the packaging string to the resolver, because neither alone is enough.

    Fixing the resolver and not shipping the bytes leaves a correct pointer at
    an absent directory; shipping the bytes to a destination the resolver does
    not try leaves them unread. This builds the layout the wheel actually
    produces, from the destination the wheel actually declares, and asks the
    resolver to find it.
    """
    with open(PYPROJECT, "rb") as handle:
        force_include = tomllib.load(handle)["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    destinations = [dest for source, dest in force_include.items() if Path(source).as_posix().endswith("data/match")]
    assert len(destinations) == 1, (
        f"expected exactly one force-include entry for data/match and found {destinations}. Without "
        f"it a pip install ships none of the tuning data, which is the state this fix ends."
    )

    install_root = tmp_path / "site-packages"
    module_file = _module_file(install_root / "app", _MODULE_NAME)
    planted = _plant_data(install_root / destinations[0])

    assert match_data_dir_for(module_file, _MODULE_NAME) == planted, (
        f"the wheel lands the data at {destinations[0]!r} relative to the install root and the "
        f"resolver does not look there, so a pip install would ship the files and never read them."
    )


def test_the_config_readers_return_the_shipped_files_verbatim() -> None:
    """The readers are wired to the resolver, checked against the bytes on disk.

    Compared against the tracked file rather than against expected values, so
    this stays a statement about the wiring and does not have to be edited
    every time a threshold is tuned.
    """
    from app.core.match_service.config import _load_encoder_profiles_raw, _load_lex_profiles_raw

    _load_encoder_profiles_raw.cache_clear()
    _load_lex_profiles_raw.cache_clear()
    try:
        encoder = _load_encoder_profiles_raw()
        lex = _load_lex_profiles_raw()
    finally:
        _load_encoder_profiles_raw.cache_clear()
        _load_lex_profiles_raw.cache_clear()

    assert encoder == json.loads((TRACKED_DATA / "encoder_profiles.json").read_text(encoding="utf-8"))
    assert lex == json.loads((TRACKED_DATA / "lex_thresholds.json").read_text(encoding="utf-8"))


def test_the_yaml_readers_return_the_shipped_overlays() -> None:
    """The other two readers, which take their path from the same resolver."""
    from app.core.match_service.boosts.region import _load_region_groups_from_yaml
    from app.core.match_service.region_language import REGION_LANGUAGE, _load_region_language_yaml_overlay

    groups = _load_region_groups_from_yaml()
    assert groups, "region_groups.yaml is tracked and readable, so the overlay must not come back empty"

    _load_region_language_yaml_overlay()
    assert REGION_LANGUAGE, "the region language map must not be empty after the overlay merges"


def test_a_reader_falls_back_quietly_when_the_data_is_not_shipped(monkeypatch) -> None:
    """The absent case stays supported, which is why the failure was silent to begin with.

    A minimal install ships no ``data/match`` and must keep working on the
    hardcoded constants. This exercises the branch the readers grew for a
    resolver that answers ``None``, so the fix cannot have turned a quiet
    fallback into a raise.
    """
    from app.core.match_service import config as config_module

    monkeypatch.setattr(config_module, "match_data_file", lambda _name: None)
    config_module._load_lex_profiles_raw.cache_clear()
    config_module._load_encoder_profiles_raw.cache_clear()
    try:
        assert config_module._load_lex_profiles_raw() == {}
        assert config_module._load_encoder_profiles_raw() == {}
    finally:
        config_module._load_lex_profiles_raw.cache_clear()
        config_module._load_encoder_profiles_raw.cache_clear()
