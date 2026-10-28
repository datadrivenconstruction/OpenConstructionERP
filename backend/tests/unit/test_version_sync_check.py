"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The release gate that reads every version literal in the tree.

``scripts/check_version_sync.py`` is the only thing standing between a release
and a build whose parts disagree about which version they are. It grew one
literal at a time and the newest one, the Tauri crate manifest, was added after
that manifest had already drifted eleven minor releases behind everything else
without a single gate noticing.

Two things are worth testing here and they fail differently.

The first is how the Cargo version is located. A Cargo manifest carries a
``version`` for the package and another for every dependency, and the reader
has to be anchored on the ``[package]`` table. A first-match scan happens to be
right today only because ``[package]`` is conventionally written first and the
dependencies use inline tables; both of those are conventions, not rules, and
when either changes the scan starts validating a dependency's version and
passes forever while checking a literal nobody bumps. That is not a check that
gets worse, it is a check that reports all-clear on a tree it never read. The
cases below reorder the tables and take the package version away to show the
anchor holding where a first-match scan would not.

The second is whether the literals actually agree right now. That one reads
the real tree, so it is a statement about the repository rather than about the
code, and it is the assertion the release depends on.

Cases:
    * the reader returns the package version, not a dependency's
    * a dependency table written before ``[package]`` does not capture it
    * an inherited ``version.workspace`` fails loudly instead of falling
      through to the first dependency below it
    * a manifest with no ``[package]`` table fails rather than passing
    * the live manifest reads the same as a real TOML parser reads it
    * the lockfile entry is found by crate name, past 538 decoy entries
    * a lockfile missing the crate fails by name instead of checking nothing
    * the live lockfile reads the same as a real TOML parser reads it

Deliberately not here: an assertion that the literals in the tree agree right
now. ``Repo hygiene`` runs ``scripts/check_version_sync.py`` against the real
files on every push, with no branch filter, so a copy of that assertion in this
file would be a second check of one thing. What is left here is what the script
run cannot cover, namely the reader's behaviour on manifest and lockfile shapes
that do not exist in the tree and would not until the day they broke it.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_version_sync.py"

# A manifest in the shape the project actually uses: package first, inline
# dependency tables. The dependency versions are deliberately plausible enough
# to be mistaken for a release version by a reader that is not anchored.
CONVENTIONAL = """\
[package]
name = "openconstructionerp-desktop"
version = "9.9.9"

[dependencies]
tauri = { version = "2", features = ["tray-icon"] }
reqwest = { version = "0.12", features = ["json"] }
"""

# The same crate with one dependency written as a section rather than an inline
# table, and placed above [package]. TOML does not care about table order, so
# this manifest is as valid as the one above and builds the same crate. A scan
# that takes the first `version = "..."` in the file returns "0.12" here.
DEPENDENCY_TABLE_FIRST = """\
[dependencies.reqwest]
version = "0.12"
features = ["json"]

[package]
name = "openconstructionerp-desktop"
version = "9.9.9"
"""

# A crate that inherits its version from a workspace. There is no version under
# [package] at all, so there is nothing correct to return and the only safe
# answer is to fail. A first-match scan answers "0.12" and calls it the release.
WORKSPACE_INHERITED = """\
[package]
name = "openconstructionerp-desktop"
version.workspace = true

[dependencies.reqwest]
version = "0.12"
"""

NO_PACKAGE_TABLE = """\
[workspace]
members = ["src-tauri"]
"""


def _load_script():
    """Import the script by path. It lives in scripts/, which is not a package.

    Both the spec and its loader are Optional in the stdlib signature, and this
    codebase has already been bitten by a spec that resolved where the import
    behind it did not. An unguarded dereference turns that into an AttributeError
    on a line that says nothing about the cause, so it is checked here instead.
    """
    spec = importlib.util.spec_from_file_location("check_version_sync", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not build an import spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


def _read(script, tmp_path: Path, text: str) -> str:
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text(text, encoding="utf-8")
    return script._read_cargo_toml_version(manifest)


def test_script_exists():
    """A rename or a move would make every other test here silently vacuous."""
    assert SCRIPT_PATH.is_file(), SCRIPT_PATH


def test_reads_the_package_version_not_a_dependency(script, tmp_path):
    assert _read(script, tmp_path, CONVENTIONAL) == "9.9.9"


def test_a_dependency_table_above_package_does_not_capture_the_read(script, tmp_path):
    """The case that makes the anchor load-bearing rather than decorative."""
    assert _read(script, tmp_path, DEPENDENCY_TABLE_FIRST) == "9.9.9"


def test_an_inherited_version_fails_instead_of_reading_the_next_table(script, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        _read(script, tmp_path, WORKSPACE_INHERITED)
    assert "[package]" in str(excinfo.value)


def test_a_manifest_without_a_package_table_fails(script, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        _read(script, tmp_path, NO_PACKAGE_TABLE)
    assert "[package]" in str(excinfo.value)


def test_the_real_manifest_agrees_with_a_real_toml_parser(script):
    """Guards the live file, against an oracle that cannot share the bug.

    The script reads the manifest with a regex on purpose, to stay free of a
    TOML dependency. A test that checked that regex with the same regex, or
    with an assertion about the shape of what came back, would pass for the
    wrong reason: ``"11.11.1"`` and ``"0.12.3"`` are both three numbers and a
    reader that drifted onto the wrong table would satisfy either.

    ``tomllib`` is stdlib on the 3.12 this project requires, so the test can
    afford the parser the script cannot, and compare against ground truth.
    """
    with script.CARGO_TOML.open("rb") as handle:
        manifest = tomllib.load(handle)
    expected = manifest["package"]["version"]
    assert script._read_cargo_toml_version(script.CARGO_TOML) == expected


def test_the_lockfile_entry_is_found_by_name_not_by_position(script, tmp_path):
    """The decoy field is the point.

    A manifest has a handful of dependency versions. The lockfile has one entry
    per resolved crate, 538 of them, so an unanchored reader there is not
    unlikely to be wrong, it is almost certain to be, and it fails green.
    ``bbb-dep`` is placed first on purpose: a first-match scan returns 2.0.1.
    """
    lock = tmp_path / "Cargo.lock"
    lock.write_text(
        '[[package]]\nname = "bbb-dep"\nversion = "2.0.1"\n\n'
        '[[package]]\nname = "openconstructionerp-desktop"\nversion = "14.3.0"\n'
        '\n[[package]]\nname = "zzz-dep"\nversion = "0.4.0"\n',
        encoding="utf-8",
    )
    found = script._read_cargo_lock_version(lock, "openconstructionerp-desktop")
    assert found == "14.3.0"


def test_a_lockfile_without_the_crate_fails_by_name(script, tmp_path):
    """A rename must scream rather than quietly check nothing."""
    lock = tmp_path / "Cargo.lock"
    lock.write_text('[[package]]\nname = "bbb-dep"\nversion = "2.0.1"\n', encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        script._read_cargo_lock_version(lock, "openconstructionerp-desktop")
    assert "openconstructionerp-desktop" in str(excinfo.value)


def test_the_real_lockfile_agrees_with_a_real_toml_parser(script):
    """Same oracle as the manifest, over the file with the decoys."""
    with script.CARGO_LOCK.open("rb") as handle:
        lock = tomllib.load(handle)
    crate = script._read_cargo_toml_name(script.CARGO_TOML)
    expected = [p["version"] for p in lock["package"] if p["name"] == crate]
    assert expected, f"{crate} has no entry in the lockfile"
    assert script._read_cargo_lock_version(script.CARGO_LOCK, crate) == expected[0]


def test_security_md_names_the_current_major(script):
    """The supported-versions table goes stale on a major bump without this."""
    backend_major = script._read_pyproject_version(script.PYPROJECT).split(".")[0]
    assert script._security_md_supported_major(script.SECURITY_MD) == backend_major


def test_security_md_reader_sees_a_stale_major(script, tmp_path):
    security = tmp_path / "SECURITY.md"
    security.write_text("| Latest release (17.x)   | Yes |\n", encoding="utf-8")
    assert script._security_md_supported_major(security) == "17"
    security.write_text("no table\n", encoding="utf-8")
    assert script._security_md_supported_major(security) is None
