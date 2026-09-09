"""The second question ``scripts/inspect_desktop_sidecar_signatures.py`` asks of a member.

Issue #480. The macOS desktop app installed, started, started its backend, and then could
not create its own database: initdb, unpacked out of the onefile sidecar and run as its own
process, was refused ``pginstall/lib/libpq.5.dylib`` with a message about the two of them
having different Team IDs. Neither of them had one.

The cause was a flag, not an identity. ``desktop/pyinstaller.spec`` named ``"-"`` as a
signing identity, meaning "sign ad-hoc", and PyInstaller reads any truthy identity as a real
Developer ID: ``sign_binary`` takes the else branch and adds ``--options=runtime``. Every
binary collected into the archive was therefore ad-hoc, hardened, and carrying no
entitlements. The hardened runtime turns on library validation; library validation accepts
only a library carrying the loading process's Team ID or a platform identity; an ad-hoc
binary carries neither. So the process is refused the files unpacked beside it, and the
refusal is worded as a Team ID disagreement even though no Team ID exists on either side.

The gate that was already there could not see it, and the first test below is the one that
says so. ``--fail-on-foreign-team-id`` asks whether members agree with the wrapper, and on
the broken artifact they all did: every one of them was ad-hoc with no Team ID. Agreement
was never the question. That is why this is a second predicate rather than a widening of the
first, and why a third same-Team-ID check would be worth nothing.

The predicate is deliberately the pair "hardened runtime AND no Team ID" rather than the
hardened runtime alone. Hardened with a real Developer ID is the correct end state described
in docs/desktop/MACOS_NOTARIZATION.md, so a check that fired on the runtime flag by itself
would have to be switched off on the day that work lands, which is the day it is most worth
having.

The Mach-O bodies here are built rather than fixtures, because the property under test is a
single word inside a code signature and a checked-in binary would hide which word it is.
"""

from __future__ import annotations

import importlib.util
import re
import struct
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "inspect_desktop_sidecar_signatures.py"
SPEC_PATH = REPO_ROOT / "desktop" / "pyinstaller.spec"

EXE_NAME = "openconstructionerp-server"

CS_ADHOC = 0x00000002
CS_RUNTIME = 0x00010000


def _code_directory(flags: int, team: str | None) -> bytes:
    """A CodeDirectory blob of the version that carries a Team ID, with these two values."""
    ident = b"a.test.binary\x00"
    header = 52  # nine uint32s, four bytes of hash parameters, spare2, scatterOffset, teamOffset
    ident_offset = header
    team_bytes = b"" if team is None else team.encode() + b"\x00"
    team_offset = 0 if team is None else ident_offset + len(ident)
    body = ident + team_bytes
    length = header + len(body)
    return (
        struct.pack(
            ">9I",
            0xFADE0C02,  # CSMAGIC_CODEDIRECTORY
            length,
            0x20200,  # the version at which teamOffset exists
            flags,
            0,  # hashOffset
            ident_offset,
            0,  # nSpecialSlots
            0,  # nCodeSlots
            0,  # codeLimit
        )
        + bytes([32, 2, 0, 12])  # hashSize, hashType, platform, pageSize
        + struct.pack(">3I", 0, 0, team_offset)  # spare2, scatterOffset, teamOffset
        + body
    )


def _signature(flags: int, team: str | None) -> bytes:
    """An embedded signature superblob holding one CodeDirectory."""
    directory = _code_directory(flags, team)
    offset = 20  # superblob header plus one index entry
    return struct.pack(">3I", 0xFADE0CC0, offset + len(directory), 1) + struct.pack(">2I", 0, offset) + directory


def macho(flags: int = CS_ADHOC, team: str | None = None, *, signed: bool = True) -> bytes:
    """A 64-bit little-endian Mach-O whose only load command is its code signature."""
    if not signed:
        return struct.pack("<7I", 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0) + b"\x00\x00\x00\x00"
    body = _signature(flags, team)
    header = struct.pack("<7I", 0xFEEDFACF, 0x0100000C, 0, 2, 1, 16, 0) + b"\x00\x00\x00\x00"
    command = struct.pack("<4I", 0x1D, 16, len(header) + 16, len(body))
    return header + command + body


@pytest.fixture
def script():
    """Import the script by path. It lives in scripts/, which is not a package."""
    spec = importlib.util.spec_from_file_location("inspect_desktop_sidecar_signatures", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_built_body_is_read_back_the_way_it_was_written(script):
    """The instrument before the measurements. A builder nobody checks proves nothing."""
    assert script.code_directories(macho(CS_ADHOC | CS_RUNTIME, "ABCDE12345")) == [
        {"state": "parsed", "flags": CS_ADHOC | CS_RUNTIME, "team": "ABCDE12345"}
    ]


def test_an_adhoc_member_without_the_runtime_is_the_shape_we_ship(script):
    """The state a correct build leaves behind, so the gate cannot pass by refusing nothing."""
    assert script.hardened_without_team(macho(CS_ADHOC)) == (False, [])


def test_an_adhoc_member_with_the_runtime_is_the_defect(script):
    """Exactly what 14.5.0 through 17.1.0 shipped: no identity, and a runtime demanding one."""
    flagged, unreadable = script.hardened_without_team(macho(CS_ADHOC | CS_RUNTIME))

    assert flagged is True
    assert unreadable == []


def test_a_developer_id_member_with_the_runtime_is_left_alone(script):
    """The notarized end state must not trip this, or it gets removed when it starts to matter."""
    assert script.hardened_without_team(macho(CS_RUNTIME, "ABCDE12345")) == (False, [])


def test_a_member_with_no_signature_at_all_settles_the_question_rather_than_opening_it(script):
    """No signature means no runtime flag. That is an answer, and it is not the same as a doubt."""
    assert script.code_directories(macho(signed=False)) == [{"state": "unsigned"}]
    assert script.hardened_without_team(macho(signed=False)) == (False, [])


def test_a_signature_that_cannot_be_walked_is_reported_and_not_filed_as_clean(script):
    """The failure mode the Team ID census had: what could not be read was counted as innocent."""
    truncated = macho(CS_ADHOC | CS_RUNTIME)[:60]

    flagged, unreadable = script.hardened_without_team(truncated)

    assert flagged is False, "a body this short cannot support a finding either way"
    assert unreadable, "and it must not leave here silently, because silence reads as clean"


def test_bytes_that_are_not_a_macho_are_unreadable_rather_than_unsigned(script):
    """Two different answers. Only one of them is allowed to look like a pass."""
    (state,) = script.code_directories(b"this is not a Mach-O" * 8)

    assert state["state"] == "unreadable"


def _stub_archive(monkeypatch, script, members):
    """Put a readable archive of ``{name: bytes}`` behind the reader so main() reaches a verdict."""
    monkeypatch.setattr(script, "open_archive", lambda _path: (object(), script.EXIT_CLEAN))
    monkeypatch.setattr(script, "member_names", lambda _reader: list(members))
    monkeypatch.setattr(script, "extract", lambda _reader, name: members[name])
    monkeypatch.setattr(
        script,
        "describe",
        lambda _path: {"team": "unsigned", "signature": "adhoc", "flags": "0x2(adhoc)"},
    )


HARDENED_ARCHIVE = {
    "Python.framework/Versions/3.12/Python": macho(CS_ADHOC),
    "pixeltable_pgserver/pginstall/bin/initdb": macho(CS_ADHOC | CS_RUNTIME),
    "pixeltable_pgserver/pginstall/lib/libpq.5.dylib": macho(CS_ADHOC | CS_RUNTIME),
}


def test_the_team_id_gate_alone_passes_the_artifact_that_broke(script, monkeypatch, tmp_path, capsys):
    """Why there is a second flag at all.

    Every member of the shipped archive agreed with the wrapper about the Team ID, all of them
    having none, so the gate that was already in the release workflow was green on the build a
    user could not start. This test fails the day someone decides the existing check covers
    this, which is the assumption that let eleven releases go out.
    """
    executable = tmp_path / EXE_NAME
    executable.write_bytes(macho(CS_ADHOC))
    monkeypatch.setattr(sys, "platform", "darwin")
    _stub_archive(monkeypatch, script, HARDENED_ARCHIVE)
    monkeypatch.setattr(
        sys, "argv", ["inspect_desktop_sidecar_signatures.py", "--fail-on-foreign-team-id", str(executable)]
    )

    assert script.main() == script.EXIT_CLEAN
    assert "census: 3 member(s) inspected" in capsys.readouterr().out


def test_the_new_gate_fails_the_same_artifact_and_names_the_members(script, monkeypatch, tmp_path, capsys):
    """Same archive, same run, one more flag. Exit 1, and the names a maintainer needs."""
    executable = tmp_path / EXE_NAME
    executable.write_bytes(macho(CS_ADHOC))
    monkeypatch.setattr(sys, "platform", "darwin")
    _stub_archive(monkeypatch, script, HARDENED_ARCHIVE)
    monkeypatch.setattr(
        sys, "argv", ["inspect_desktop_sidecar_signatures.py", "--fail-on-hardened-adhoc", str(executable)]
    )

    assert script.main() == script.EXIT_ALARM

    out = capsys.readouterr().out
    assert "HARDENED AD-HOC" in out
    assert "pixeltable_pgserver/pginstall/bin/initdb" in out
    # The denominator travels with the verdict here for the same reason it does above.
    assert "census: 3 member(s) inspected" in out


def test_the_new_gate_passes_an_archive_signed_the_way_the_fix_leaves_it(script, monkeypatch, tmp_path, capsys):
    """The positive case, without which every assertion above is satisfied by refusing everything."""
    executable = tmp_path / EXE_NAME
    executable.write_bytes(macho(CS_ADHOC))
    monkeypatch.setattr(sys, "platform", "darwin")
    _stub_archive(monkeypatch, script, {name: macho(CS_ADHOC) for name in HARDENED_ARCHIVE})
    monkeypatch.setattr(
        sys, "argv", ["inspect_desktop_sidecar_signatures.py", "--fail-on-hardened-adhoc", str(executable)]
    )

    assert script.main() == script.EXIT_CLEAN
    assert "HARDENED AD-HOC" not in capsys.readouterr().out


def test_a_member_the_gate_could_not_read_fails_it_rather_than_passing_it(script, monkeypatch, tmp_path):
    """A census narrower than the archive cannot clear the archive. Same rule as the other gate."""
    executable = tmp_path / EXE_NAME
    executable.write_bytes(macho(CS_ADHOC))
    monkeypatch.setattr(sys, "platform", "darwin")
    _stub_archive(monkeypatch, script, {"truncated.dylib": macho(CS_ADHOC)[:60]})
    monkeypatch.setattr(
        sys, "argv", ["inspect_desktop_sidecar_signatures.py", "--fail-on-hardened-adhoc", str(executable)]
    )

    assert script.main() == script.EXIT_ALARM


def test_the_spec_does_not_name_an_ad_hoc_identity_again(script):
    """The fix itself, guarded at its source.

    ``codesign_identity = None`` and ``codesign_identity = "-"`` look like the same request and
    are not: PyInstaller ad-hoc signs either way, and only the second one also asks for the
    hardened runtime.

    A macOS build log does distinguish them, in one line, ``Code signing identity: None``
    against ``Code signing identity: -`` (PyInstaller ``building/api.py``, printed under
    ``if is_darwin``). That line is worth knowing when reading a CI log by hand, but it is
    weak as a gate: it only appears on macOS runners, it says nothing about what the runtime
    flag ended up as, and a build nobody reads the log of emits it just the same. The line in
    the spec is the thing that decides, so the line in the spec is what is asserted here.
    """
    assignments = [
        line.split("=", 1)[1].strip()
        for line in SPEC_PATH.read_text(encoding="utf-8").splitlines()
        if re.match(r"^codesign_identity\s*=", line)
    ]

    assert assignments == ["None"], (
        f"desktop/pyinstaller.spec assigns codesign_identity {assignments}. On the ad-hoc path it "
        "must be None. PyInstaller signs collected binaries ad-hoc with no identity named, and reads "
        'any truthy identity, "-" included, as a real Developer ID for which it turns on the '
        "hardened runtime. See issue #480 and the comment above that line. If you are reading this "
        "while switching the build to a real Developer ID, widen this assertion, do not delete it: "
        "the property worth keeping is that a truthy identity never travels without an "
        "entitlements_file, because the runtime it turns on needs one."
    )
