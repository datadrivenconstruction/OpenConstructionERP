"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every CLI command has to land in the data directory, not in the directory it was started from.

A path that resolves against the working directory works everywhere it is
developed and tested. It fails only where the product is actually installed:
under a program directory the process may not write to. So the interesting
property is not "does this command work here", it is "is this path anchored on
the data directory, whatever the working directory happens to be".

These tests drive the FULL list of declarations the parser carries rather than
one command each, because a fix applied once per caller is only ever tested at
the caller that was already right. The sweep prints what it examined, so a
matcher that quietly stops matching shows up as a shrinking list instead of a
passing test.

Two exceptions are pinned here on purpose rather than left to look like
oversights: ``pack new`` scaffolds into the working directory because that is
what its ``--out`` help promises, and ``_default_data_dir`` returns a relative
path when no home directory can be resolved at all, which beats aborting.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from app import cli

#: Argument destinations that name a filesystem location. Used to decide which
#: declared defaults the relative-path sweep has to look at.
PATHISH_SUFFIXES = ("_dir", "_path", "_file", "out")

#: Commands that must offer a data directory. Membership is a ratchet: a new
#: command joining the list is fine, one leaving it is a regression.
COMMANDS_THAT_MUST_TAKE_A_DATA_DIR = frozenset({"serve", "doctor", "init-db", "init", "seed", "upgrade"})


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """Map every subcommand path ("module install") to its parser, recursively."""
    found: dict[str, argparse.ArgumentParser] = {}
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            found[name] = sub
            for child_name, child in _subcommands(sub).items():
                found[f"{name} {child_name}"] = child
    return found


def _declares_data_dir(parser: argparse.ArgumentParser) -> bool:
    return any(a.dest == "data_dir" for a in parser._actions)


def _path_defaults(parser: argparse.ArgumentParser) -> list[tuple[str, str]]:
    """Every declared default in this parser that names a filesystem location."""
    out: list[tuple[str, str]] = []
    for action in parser._actions:
        default = action.default
        if not isinstance(default, str):
            continue
        looks_pathish = action.dest.endswith(PATHISH_SUFFIXES) or os.sep in default or "/" in default
        if looks_pathish:
            out.append((action.dest, default))
    return out


@pytest.fixture
def anchored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A writable data directory, and a working directory that is somewhere else.

    This is the shape of a real install: the process is started from a place it
    does not own, and everything it writes has to go somewhere else.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    started_from = tmp_path / "program files" / "OpenConstructionERP"
    started_from.mkdir(parents=True)
    monkeypatch.setattr(cli, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.chdir(started_from)
    return data_dir


def test_every_command_that_takes_a_data_dir_resolves_it_under_that_directory(anchored: Path) -> None:
    """The whole list, not one sample of it.

    Each of these used to resolve its own copy of the same expression. One of
    them not resolving at all is invisible next to the ones that do.
    """
    parser = cli._build_parser()
    commands = {name: sub for name, sub in _subcommands(parser).items() if _declares_data_dir(sub)}

    missing = sorted(COMMANDS_THAT_MUST_TAKE_A_DATA_DIR - set(commands))
    assert not missing, f"a command stopped offering --data-dir: {missing}"

    cwd = Path.cwd()
    for name in sorted(commands):
        args = parser.parse_args(name.split())
        resolved = cli._data_dir_from_args(args)
        assert resolved == anchored, f"{name} resolved its data directory to {resolved}, not {anchored}"
        assert resolved.is_absolute(), f"{name} resolved a relative path: {resolved}"
        assert cwd not in resolved.parents and resolved != cwd, (
            f"{name} anchored its data directory on the working directory ({cwd})"
        )


def test_a_command_without_the_flag_still_lands_in_the_data_directory(anchored: Path) -> None:
    """The bare ``openconstructionerp`` invocation declares no flags at all."""
    resolved = cli._data_dir_from_args(argparse.Namespace())

    assert resolved == anchored
    assert Path.cwd() not in resolved.parents


def test_an_explicit_data_dir_wins_over_the_default(anchored: Path, tmp_path: Path) -> None:
    parser = cli._build_parser()
    elsewhere = tmp_path / "volume"

    args = parser.parse_args(["serve", "--data-dir", str(elsewhere)])

    assert cli._data_dir_from_args(args) == elsewhere.resolve()


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_data_dir_is_not_the_working_directory(anchored: Path, blank: str) -> None:
    """``Path("")`` is the working directory, which is the bug in one character.

    A compose file, a launcher script and a start.bat all spell "not set" as an
    empty value, and ``_default_data_dir`` already treats it that way.
    """
    parser = cli._build_parser()

    args = parser.parse_args(["serve", "--data-dir", blank])
    resolved = cli._data_dir_from_args(args)

    assert resolved == anchored, f"a blank --data-dir resolved to {resolved}"
    assert resolved != Path.cwd()


def test_no_declaration_defaults_to_a_bare_relative_path(anchored: Path) -> None:
    """The guard against the next declaration, not just the current ones.

    Sweeps every default on every subparser. The count is asserted as well as
    the property: a matcher that stops recognising path defaults would pass this
    vacuously, and vacuous is what a completed fix and an undetected one look
    like from the outside.
    """
    parser = cli._build_parser()
    examined: list[str] = []

    for name, sub in sorted(_subcommands(parser).items()):
        for dest, default in _path_defaults(sub):
            examined.append(f"{name}.{dest}={default}")
            assert Path(default).is_absolute(), (
                f"{name} --{dest.replace('_', '-')} defaults to a relative path: {default!r}"
            )

    assert len(examined) >= len(COMMANDS_THAT_MUST_TAKE_A_DATA_DIR), (
        f"the sweep only found {len(examined)} path defaults, so it is no longer looking at all of them: {examined}"
    )


def test_the_relative_path_sweep_can_actually_fail(anchored: Path) -> None:
    """The negative control for the sweep above.

    Without this, a matcher that recognises nothing reports every declaration
    as anchored.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")

    found = _path_defaults(parser)

    assert found == [("data_dir", "data")]
    assert not Path(found[0][1]).is_absolute()


def test_every_data_dir_declaration_offers_the_same_default(anchored: Path) -> None:
    """One declaration site means they cannot drift; this is what proves it."""
    parser = cli._build_parser()
    defaults = {
        name: next(a.default for a in sub._actions if a.dest == "data_dir")
        for name, sub in _subcommands(parser).items()
        if _declares_data_dir(sub)
    }

    assert set(defaults.values()) == {str(anchored)}, f"the data directory defaults disagree: {defaults}"


def test_the_upgrade_guard_can_be_pointed_at_a_data_directory(anchored: Path, tmp_path: Path) -> None:
    """``upgrade`` refuses to run while a cluster is up, and looks in the data directory.

    It read the default one and nothing else, so an operator whose data lives
    elsewhere was told nothing was running while it was.
    """
    parser = cli._build_parser()
    elsewhere = tmp_path / "volume"

    args = parser.parse_args(["upgrade", "--data-dir", str(elsewhere)])

    assert cli._data_dir_from_args(args) == elsewhere.resolve()


def test_pack_new_writes_to_the_working_directory_on_purpose() -> None:
    """The one command that is supposed to, and says so in its own help."""
    parser = cli._build_parser()
    pack_new = _subcommands(parser)["pack new"]
    out = next(a for a in pack_new._actions if a.dest == "out")

    assert out.default is None, "pack new grew a path default; it scaffolds relative to the caller on purpose"
    assert "current directory" in (out.help or "")


def test_the_only_relative_default_is_the_documented_no_home_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no home directory at all the CLI still starts, and that is deliberate."""
    monkeypatch.delenv("OE_DATA_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("OE_CLI_DATA_DIR", raising=False)

    def _no_home() -> Path:
        raise RuntimeError("no home directory")

    monkeypatch.setattr(Path, "home", staticmethod(_no_home))

    assert cli._default_data_dir() == Path(".openestimate")


def test_the_config_probe_reads_the_data_directory_it_was_given(tmp_path: Path) -> None:
    """``doctor --data-dir X`` reported on a config file belonging to somewhere else."""
    given = tmp_path / "given"
    given.mkdir()
    (given / "config.json").write_text('{"anthropic_api_key": "sk-test"}', encoding="utf-8")

    check = cli.check_ai_provider_keys(given)

    assert check.status == "ok"
    assert "Anthropic" in check.message


def test_the_config_probe_does_not_read_another_data_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The other polarity: keys in the default directory are not the given one's keys."""
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for var in ("MISTRAL_API_KEY", "GROQ_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    default_dir = tmp_path / "default"
    default_dir.mkdir()
    (default_dir / "config.json").write_text('{"anthropic_api_key": "sk-test"}', encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_DATA_DIR", default_dir)

    empty = tmp_path / "empty"
    empty.mkdir()

    check = cli.check_ai_provider_keys(empty)

    assert check.status == "warn", f"the probe read {default_dir} while it was asked about {empty}"


def test_the_preflight_hands_its_data_directory_to_the_checks_that_read_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The chain, not just its ends: doctor -> run_preflight -> the file-reading checks."""
    seen: list[Path | None] = []

    def _record(data_dir: Path | None = None) -> list[cli.Check]:
        seen.append(data_dir)
        return []

    monkeypatch.setattr(cli, "check_optional_extras", _record)

    cli.run_preflight("127.0.0.1", 8931, tmp_path, verbose=True)

    assert seen == [tmp_path], f"run_preflight passed {seen} instead of the directory it was given"


def test_the_module_group_still_prints_its_own_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Guards the parser split: the group parsers are reachable from their commands."""
    parser = cli._build_parser()

    args = parser.parse_args(["module"])
    cli.cmd_module(args)

    out = capsys.readouterr().out
    assert "install" in out and "uninstall" in out


def test_the_pack_group_still_prints_its_own_help(capsys: pytest.CaptureFixture[str]) -> None:
    parser = cli._build_parser()

    args = parser.parse_args(["pack"])
    cli.cmd_pack(args)

    out = capsys.readouterr().out
    assert "new" in out
