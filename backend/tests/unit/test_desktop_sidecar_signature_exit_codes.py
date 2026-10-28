"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The three answers ``scripts/inspect_desktop_sidecar_signatures.py`` can give.

The census is a release gate: it reads the Mach-O members sealed inside the onefile
sidecar and fails the build when one of them disagrees with the wrapper about a Team ID.
A gate is only worth its exit code, and this one used to spend 0 on two unrelated states.
On a runner that is not macOS it returned 0 without opening the file, and the workflow
step that reads that 0 writes the word "clean" into the job summary. So "there is no
codesign here to ask" and "every member agrees with the wrapper" arrived at a human
reader as the same sentence.

What keeps that from being live today is a condition at the call site, not the script:
both invocations in ``desktop-release.yml`` are closed by ``runner.os == 'macOS'``. A
third one added without it would produce a cleared census over an artifact nobody opened.
That is the same silhouette as a build-output test that passes because the build output
is absent, and it is why the answer belongs in the script.

So the codes are asserted exactly, never as ``!= 0``. ``!= 0`` passes on 1 as readily as
on 2, which is the collapse this file exists to detect one number over.

Cases:
    * the platform is wrong, the file is there - exit 2, and no census line to misread
    * the file is missing - exit 1, on macOS and off it, because existence is asked first
    * a darwin run over agreeing members - exit 0 and a census line with a real count
    * a darwin run over a disagreeing member under the gate flag - exit 1
    * the three states do not share an exit code
    * no PyInstaller to open the archive with - exit 2, not an accusation about members
    * a reader that refuses the file itself - exit 1, because that is about the file
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "inspect_desktop_sidecar_signatures.py"

EXE_NAME = "openconstructionerp-server"

# Enough of a Mach-O for the magic-number test in the census; nothing reads further,
# because describe() is what interprets the file and it is stubbed here.
MACHO = b"\xcf\xfa\xed\xfe" + b"the rest is never parsed"


def _load_script():
    """Import the script by path. It lives in scripts/, which is not a package."""
    spec = importlib.util.spec_from_file_location("inspect_desktop_sidecar_signatures", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


@pytest.fixture
def executable(tmp_path):
    path = tmp_path / EXE_NAME
    path.write_bytes(MACHO)
    return path


def _argv(monkeypatch, script, executable, *flags):
    monkeypatch.setattr(sys, "argv", ["inspect_desktop_sidecar_signatures.py", *flags, str(executable)])
    return script


def _stub_archive(monkeypatch, script, *, wrapper_team, member_teams):
    """Put a readable archive behind the reader so main() reaches its verdict.

    ``member_teams`` maps a member's base name to the Team ID describe() reports for it,
    which is the only thing the comparison against the wrapper reads.
    """
    monkeypatch.setattr(script, "open_archive", lambda _path: (object(), script.EXIT_CLEAN))
    monkeypatch.setattr(script, "member_names", lambda _reader: list(member_teams))
    monkeypatch.setattr(script, "extract", lambda _reader, _name: MACHO)

    def describe(path):
        name = Path(path).name
        team = wrapper_team if name == EXE_NAME else member_teams[name]
        return {"team": team, "signature": "adhoc", "flags": "0x2(adhoc)"}

    monkeypatch.setattr(script, "describe", describe)


def test_script_exists():
    """A rename would make every assertion below vacuous rather than failing."""
    assert SCRIPT_PATH.is_file(), SCRIPT_PATH


def test_the_codes_are_three_distinct_numbers(script):
    """The whole fix is that these are not equal. Asserted before anything uses them."""
    assert {script.EXIT_CLEAN, script.EXIT_ALARM, script.EXIT_UNKNOWN} == {0, 1, 2}


def test_a_non_darwin_run_over_a_real_file_is_unknown(script, monkeypatch, executable, capsys):
    """The state the fix is for: the file is there, the instrument is not."""
    monkeypatch.setattr(sys, "platform", "win32")
    _argv(monkeypatch, script, executable)

    assert script.main() == script.EXIT_UNKNOWN

    out = capsys.readouterr().out
    assert "UNKNOWN" in out
    # The workflow reads its denominator out of a line starting "census:". A run that
    # opened nothing must not emit one, or the summary gets a number to sound measured
    # with. Absence of the line is what makes the shell read 0 there.
    assert "census:" not in out


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_a_missing_file_is_an_alarm_on_every_platform(script, monkeypatch, tmp_path, capsys, platform):
    """Existence is asked before the platform, so absence cannot hide behind win32."""
    monkeypatch.setattr(sys, "platform", platform)
    _argv(monkeypatch, script, tmp_path / "was-never-built")

    assert script.main() == script.EXIT_ALARM
    assert "no such file" in capsys.readouterr().out


def test_a_darwin_run_over_agreeing_members_is_clean_and_says_how_many(script, monkeypatch, executable, capsys):
    """The positive case. Without it the suite would pass by refusing everything."""
    monkeypatch.setattr(sys, "platform", "darwin")
    _stub_archive(
        monkeypatch,
        script,
        wrapper_team="unsigned",
        member_teams={"libssl.dylib": "unsigned", "Python": "unsigned"},
    )
    _argv(monkeypatch, script, executable, "--fail-on-foreign-team-id")

    assert script.main() == script.EXIT_CLEAN

    out = capsys.readouterr().out
    # The count, not just the word. "clean" over zero members and "clean" over all of
    # them reach the summary as the same adjective, and this is what separates them.
    assert "census: 2 member(s) inspected" in out


def test_a_darwin_run_over_a_disagreeing_member_is_an_alarm(script, monkeypatch, executable, capsys):
    """The failure the gate exists for, so exit 1 is reached by a real finding."""
    monkeypatch.setattr(sys, "platform", "darwin")
    _stub_archive(
        monkeypatch,
        script,
        wrapper_team="unsigned",
        member_teams={"Python": "ABCDE12345", "libssl.dylib": "unsigned"},
    )
    _argv(monkeypatch, script, executable, "--fail-on-foreign-team-id")

    assert script.main() == script.EXIT_ALARM
    assert "MISMATCH" in capsys.readouterr().out


def test_the_three_states_do_not_share_an_exit_code(script, monkeypatch, executable, tmp_path):
    """One assertion over all three, because pairwise equality is the defect itself.

    Read separately, three passing tests each say a number was produced. Only the set
    says the numbers are three.
    """
    codes = []

    monkeypatch.setattr(sys, "platform", "darwin")
    _stub_archive(monkeypatch, script, wrapper_team="unsigned", member_teams={"Python": "unsigned"})
    _argv(monkeypatch, script, executable, "--fail-on-foreign-team-id")
    codes.append(script.main())

    _argv(monkeypatch, script, tmp_path / "was-never-built", "--fail-on-foreign-team-id")
    codes.append(script.main())

    monkeypatch.setattr(sys, "platform", "win32")
    _argv(monkeypatch, script, executable, "--fail-on-foreign-team-id")
    codes.append(script.main())

    assert len(set(codes)) == 3, codes


def _fake_pyinstaller(monkeypatch, reader_factory):
    """Install a PyInstaller whose CArchiveReader is ours, present or not on this machine."""
    package = types.ModuleType("PyInstaller")
    archive = types.ModuleType("PyInstaller.archive")
    readers = types.ModuleType("PyInstaller.archive.readers")
    readers.CArchiveReader = reader_factory
    package.archive = archive
    archive.readers = readers
    monkeypatch.setitem(sys.modules, "PyInstaller", package)
    monkeypatch.setitem(sys.modules, "PyInstaller.archive", archive)
    monkeypatch.setitem(sys.modules, "PyInstaller.archive.readers", readers)


def test_no_pyinstaller_is_unknown_rather_than_a_finding(script, monkeypatch, executable, capsys):
    """A missing reader says nothing about the members, so it must not be filed as one."""
    # None in sys.modules is what CPython raises ImportError on, and it does so whether
    # or not PyInstaller is installed in the environment running this suite.
    monkeypatch.setitem(sys.modules, "PyInstaller", None)

    reader, code = script.open_archive(executable)

    assert reader is None
    assert code == script.EXIT_UNKNOWN
    assert "UNKNOWN" in capsys.readouterr().out


def test_a_reader_that_refuses_the_file_is_an_alarm(script, monkeypatch, executable, capsys):
    """Refusing this file is a fact about this file, which is the other exit code."""

    def refuse(_path):
        raise ValueError("not a PyInstaller archive")

    _fake_pyinstaller(monkeypatch, refuse)

    reader, code = script.open_archive(executable)

    assert reader is None
    assert code == script.EXIT_ALARM
    assert "could not open" in capsys.readouterr().out
