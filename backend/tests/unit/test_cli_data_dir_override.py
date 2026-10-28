"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The CLI's data directory must obey the same overrides as everything else.

``OE_DATA_DIR``, then ``DATA_DIR``, then ``OE_CLI_DATA_DIR`` is the order the
uploads root, the JWT secret, the demo seed and the partner pack state all
resolve in. The CLI did not: it took the home directory and nothing else. An
operator who pointed ``OE_DATA_DIR`` at a mounted volume therefore got their
uploads and their signing secret on the volume, and their database, their
cluster and their config file left in the home directory, which on a container
is the layer that disappears on redeploy.

Half honouring a documented override is worse than ignoring it, because the
half that was ignored is silent. The last test here is the one that matters:
it puts the CLI and the storage resolver side by side under the same
environment and fails if they ever disagree again.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from app import cli
from app.core import storage

VARS = ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")


@pytest.fixture(autouse=True)
def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an environment that names none of the three."""
    for v in VARS:
        monkeypatch.delenv(v, raising=False)


def test_the_platform_override_is_honoured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The regression, and the case a container actually hits."""
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "volume"))

    assert cli._default_data_dir() == tmp_path / "volume"


def test_the_generic_override_is_honoured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "generic"))

    assert cli._default_data_dir() == tmp_path / "generic"


def test_the_cli_override_is_honoured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Set by a desktop launcher that has already decided where the data lives."""
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path / "fromlauncher"))

    assert cli._default_data_dir() == tmp_path / "fromlauncher"


def test_the_platform_override_beats_the_others(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "first"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "second"))
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path / "third"))

    assert cli._default_data_dir() == tmp_path / "first"


def test_the_generic_override_beats_the_cli_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "second"))
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path / "third"))

    assert cli._default_data_dir() == tmp_path / "second"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_override_is_not_an_override(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    """An empty variable is how a compose file spells "unset", not a path to the root."""
    monkeypatch.setenv("OE_DATA_DIR", blank)

    assert cli._default_data_dir() == Path.home() / ".openestimate"


def test_the_default_is_still_the_per_user_directory() -> None:
    """With nothing set, nothing changes for the ordinary desktop install."""
    assert cli._default_data_dir() == Path.home() / ".openestimate"


def test_a_surrounding_space_is_trimmed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OE_DATA_DIR", f"  {tmp_path / 'padded'}  ")

    assert cli._default_data_dir() == tmp_path / "padded"


@pytest.mark.parametrize(
    "env",
    [
        {"OE_DATA_DIR": "volume"},
        {"DATA_DIR": "generic"},
        {"OE_CLI_DATA_DIR": "launcher"},
        {"OE_DATA_DIR": "first", "DATA_DIR": "second"},
        {"DATA_DIR": "second", "OE_CLI_DATA_DIR": "third"},
        {"OE_DATA_DIR": "first", "DATA_DIR": "second", "OE_CLI_DATA_DIR": "third"},
    ],
)
def test_the_cli_and_the_storage_root_never_disagree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: dict[str, str]
) -> None:
    """The point of the fix. One environment, two resolvers, one answer.

    Storage is the resolver the rest of the platform reaches through, so if
    these two ever part company again the operator's uploads and the operator's
    database land in different places and nothing says so.
    """
    for k, v in env.items():
        monkeypatch.setenv(k, str(tmp_path / v))

    assert cli._default_data_dir() == storage.resolve_data_dir(), (
        f"the CLI and the storage root disagree under {sorted(env)}"
    )


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_both_resolvers_treat_a_blank_override_as_unset(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """A compose file spells "not set" as an empty value.

    Taken literally it resolves to a directory named a space, and the two
    resolvers used to take it differently: one fell back, the other did not.
    """
    monkeypatch.setenv("OE_DATA_DIR", value)

    assert cli._default_data_dir() == Path.home() / ".openestimate"
    assert storage.resolve_data_dir() != Path(value)


def test_both_resolvers_trim_an_override_the_same_way(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OE_DATA_DIR", f" {tmp_path / 'padded'} ")

    assert cli._default_data_dir() == tmp_path / "padded"
    assert storage.resolve_data_dir() == tmp_path / "padded"


def test_with_no_override_the_two_are_allowed_to_differ_in_a_checkout() -> None:
    """Not an oversight, and not something to "fix" by making them equal.

    With nothing set, storage answers the repository's own ``data`` tree when
    it is running from a checkout and the per-user directory when it is running
    from an installed wheel, because an installed package directory is wiped on
    upgrade. The CLI answers the per-user directory either way. So on a user's
    machine, which is always the installed case, they already agree, and the
    difference is confined to a source tree. Pinning it here keeps someone from
    reading the test above as a rule that covers this case too.
    """
    from_a_checkout = "site-packages" not in str(Path(storage.__file__).resolve()).lower()

    if from_a_checkout:
        assert cli._default_data_dir() != storage.resolve_data_dir()
    else:
        assert cli._default_data_dir() == storage.resolve_data_dir()


def test_the_version_line_names_a_directory_that_holds_the_package(capsys: pytest.CaptureFixture[str]) -> None:
    """It used to be labelled site-packages while showing the interpreter's directory.

    That line is what someone pastes when an install is misbehaving, so it has
    to point at a real location rather than at the neighbouring folder.
    """
    cli.cmd_version(argparse.Namespace())

    out = capsys.readouterr().out
    line = next((line for line in out.splitlines() if line.startswith("Installed at:")), None)
    assert line, f"the version output no longer says where it is installed:\n{out}"
    where = Path(line.split(":", 1)[1].strip())
    assert (where / "app" / "cli.py").is_file(), f"{where} does not hold the package that printed it"
    assert "Site-packages:" not in out, "the mislabelled line is back"
    assert os.path.basename(str(where)) not in {"Scripts", "bin"}, "that is the interpreter's directory"
