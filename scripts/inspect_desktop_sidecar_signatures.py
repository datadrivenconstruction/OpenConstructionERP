"""Report the code signature of every Mach-O the onefile sidecar carries inside itself.

Why this exists
---------------
The 14.4.0 desktop build failed to start on macOS with

    code signature in '.../_MEIxxxx/Python.framework/Versions/3.12/Python' not valid
    for use in process: mapping process and mapped file (non-platform) have different
    Team IDs

The onefile bootloader unpacks its archive at launch and dyld then maps those files into
the running process. So the property that decides whether the app starts is not the
signature on the executable a reader sees, it is the signature on the members sealed
inside it. Signing the wrapper says nothing about them, and running the binary on a
build machine says nothing either: enforcement of Team ID matching depends on the
policy applied to the process, and a locally built, never quarantined binary is judged
more leniently than the same file after a user downloads it.

This script reads the archive of the executable that will actually be shipped and prints
what each Mach-O member is signed with. A member carrying a real Team ID while the
process carries none is the exact mismatch dyld refuses, whether or not this machine
happens to enforce it today.

What it measured, and how far that reaches
------------------------------------------
Not the cause of the 14.4.0 failure. The 14.4.0 sidecar was read alongside two later
builds that differ only in the spec's codesign_identity line, and all three came back the
same: 402 Mach-O members, every one ad-hoc with no Team ID. PyInstaller rewrites rpaths
in the binaries it collects, which invalidates their original signatures, and re-signs
them ad-hoc on its own, so that result is what one would expect.

That result was then read more widely than it can carry, and this file was part of why.
The count covers only members this script could open and whose signature it could parse.
A member the reader failed to extract used to drop out of the total silently, and a
member whose codesign output did not yield a TeamIdentifier line was filed under "no Team
ID" rather than "could not tell". Either one would remove a framework binary from the
census without leaving a mark - and a framework binary is precisely what the failure
names. So "402, all ad-hoc" supported "every member we opened is ad-hoc", not "every
member is". Both gaps are now reported, both fail the gate, and --require-member makes a
run fail unless a named member was genuinely inspected.

Whether the shipped archive is clean is therefore still open. What is settled is that the
spec's codesign_identity line does not change this property either way.

That leaves the Team ID half of this script as a tripwire rather than a fix: it fails the
build the day a dependency or a packer upgrade starts sealing a vendor-signed binary inside
the archive, which would introduce that failure for real. The other half, added for issue
#480 and described below, is not a tripwire. It fires on a defect that shipped.

Both directions of the mismatch count
-------------------------------------
dyld does not ask whether a mapped file carries a Team ID, it asks whether the file's Team
ID is the process's. So the property this script checks is agreement with the wrapper, and
disagreement has two shapes. The one the 14.4.0 report named is a wrapper with no Team ID
and a member with one. The other is a wrapper with a real Team ID and members without one,
which is what any later signing pass over the finished executable would produce, because
PyInstaller re-signs the members it collects ad-hoc and nothing downstream re-signs them
again: they are sealed inside the file by then, not files on disk. That second shape used
to pass here, and worse, it printed "no member carries a Team ID, so no member can
disagree with the process about one" on its way out. It now fails like the first.

The same file is therefore worth reading at more than one point in a build. Anything that
signs the executable after it was measured changes the value every member is compared
against without touching a single member, so a reading taken before that step says nothing
about the artifact that ships.

A Team ID census cannot answer the second question
--------------------------------------------------
Agreement about a Team ID is not the only way this failure arrives, and the other way is
what shipped. Issue #480, against 17.1.0: the app started, the backend started, and the
embedded cluster did not, because initdb, extracted from this archive and run as its own
process, was refused ``pginstall/lib/libpq.5.dylib`` with the same words about differing
Team IDs. Every member of that archive was ad-hoc and every one agreed with the wrapper,
so the census above was green on it and had nothing to add.

What was wrong was a flag, not an identity. ``desktop/pyinstaller.spec`` set
``codesign_identity = "-"``, and PyInstaller reads any truthy identity as a real Developer
ID: ``sign_binary`` adds ``--options=runtime`` in that branch. Every collected binary was
therefore signed ad-hoc, hardened, and with no entitlements. The hardened runtime turns on
library validation, library validation accepts only a library carrying the loading
process's Team ID or a platform identity, and an ad-hoc binary carries neither, so such a
process is refused the payload unpacked beside it. The wrapper is the one file later
signing passes reach, the workflow's own codesign step and Tauri's bundling, and from
14.7.0 neither of them asks for the runtime any more, so the wrapper is healthy while the
children spawned out of the extraction directory are not. Nothing reaches the members: by
that point they are bytes inside a file rather than files on disk.

``--fail-on-hardened-adhoc`` is that question. It reads the flags word out of each member's
own bytes rather than writing the member out and asking codesign, and it fires on the pair
"hardened runtime, no Team ID" rather than on the hardened runtime alone: hardened with a
real Developer ID is the correct end state described in docs/desktop/MACOS_NOTARIZATION.md,
and a check that fired on it would be switched off exactly when it is most useful.

Usage:
    python scripts/inspect_desktop_sidecar_signatures.py desktop/dist/openconstructionerp-server

The path may be the raw PyInstaller output or the same binary sitting inside a bundle, for
example OpenConstructionERP.app/Contents/MacOS/openconstructionerp-server. Nothing here
treats a bundle specially: the member census reads the archive appended to the file, and
codesign reports the file's own signature, both of which are the same questions wherever
the file lives.

Exit codes
----------
    0   the archive was read and there is a verdict. Either nothing is wrong under the
        gates that were asked for, or neither --fail-on-foreign-team-id nor
        --fail-on-hardened-adhoc was passed and this ran as plain evidence without
        deciding anything by itself.
    1   the archive was read and the answer is bad: a member disagrees with the wrapper
        about a Team ID, a member is hardened while carrying none, the census was too
        narrow to support a claim about the whole archive, a --require-member name was
        never opened, or the path given is not a file.
    2   nothing was read and there is no verdict of any kind. This is not macOS, so there
        is no codesign to ask, or PyInstaller is not importable, so the archive cannot be
        opened. Never 0.

The line between 1 and 2 is what this file exists to hold, and it is not decided by any
flag: --fail-on-foreign-team-id turns the gate on, and a flag that turns a gate on cannot
also be what decides whether an unmeasured run looks measured. "I could not look" reported
as 0 is a success message about zero objects, and the step summary downstream turns it
into the word "clean". 2 is unreachable by any run that opened the archive, so a
misconfigured runner cannot produce a green one.
"""

from __future__ import annotations

import argparse
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

# Mach-O and universal-binary magic numbers, in the byte order they appear on disk.
MACHO_MAGIC = (
    b"\xcf\xfa\xed\xfe",  # 64-bit little endian
    b"\xce\xfa\xed\xfe",  # 32-bit little endian
    b"\xfe\xed\xfa\xcf",  # 64-bit big endian
    b"\xfe\xed\xfa\xce",  # 32-bit big endian
    b"\xca\xfe\xba\xbe",  # universal
    b"\xbe\xba\xfe\xca",  # universal, swapped
)

# The pieces of a Mach-O needed to read a code-signing flags word out of member
# bytes, without asking codesign about a file on disk. See Apple's cs_blobs.h.
LC_CODE_SIGNATURE = 0x1D
CSMAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
CSMAGIC_CODEDIRECTORY = 0xFADE0C02
CSSLOT_CODEDIRECTORY = 0
# The two flags this file has an opinion about. CS_ADHOC is not read directly:
# an ad-hoc signature is one with no Team ID, and the Team ID is what the rest of
# the script already compares, so absence of a team is what "ad-hoc" means below.
CS_RUNTIME = 0x00010000
# Offsets inside a CodeDirectory blob, from its own start. The first nine fields
# are uint32 (36 bytes), then hashSize, hashType, platform and pageSize as single
# bytes (40), then spare2 (44), then scatterOffset (48) and teamOffset, each of
# which only exists from the version noted beside it.
CD_FIXED_FIELDS = ">9I"
CD_TEAM_OFFSET = 48
CD_VERSION_WITH_TEAM_ID = 0x20200

# Exit codes, named after what they say rather than after pass and fail. 0 and 1 both
# belong to a run that opened the archive; 2 belongs to a run that did not, and it exists
# because 0 and 2 used to be the same number. See the exit code table in the docstring.
EXIT_CLEAN = 0
EXIT_ALARM = 1
EXIT_UNKNOWN = 2

TEAM_ID = re.compile(r"^TeamIdentifier=(.+)$", re.MULTILINE)
SIGNATURE = re.compile(r"^Signature=(.+)$", re.MULTILINE)
FLAGS = re.compile(r"^CodeDirectory .*?flags=(\S+)", re.MULTILINE)


def open_archive(path: Path):
    """Return a CArchiveReader over the onefile executable, or None and the exit code to use.

    The two ways this fails are different answers and used to share one. No PyInstaller
    on this machine means no instrument: nothing about the file was read, so the caller
    exits 2. A reader that refuses the file is a fact about the file, so the caller exits
    1. Reported as one number, the first would have accused the artifact of the second.
    """
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError as exc:
        print(f"UNKNOWN: PyInstaller is not importable here, so the archive was never opened: {exc}")
        return None, EXIT_UNKNOWN
    try:
        return CArchiveReader(str(path)), EXIT_CLEAN
    except Exception as exc:  # noqa: BLE001 - any reader failure is equally uninformative
        print(f"could not open {path} as a PyInstaller archive: {exc!r}")
        return None, EXIT_ALARM


def member_names(reader) -> list[str]:
    """List archive member names across the reader shapes PyInstaller has shipped."""
    toc = getattr(reader, "toc", None)
    if isinstance(toc, dict):
        return list(toc.keys())
    if isinstance(toc, list):
        names = []
        for entry in toc:
            if isinstance(entry, (list, tuple)) and entry:
                names.append(str(entry[-1]) if isinstance(entry[-1], str) else str(entry[0]))
            else:
                names.append(str(entry))
        return names
    print(f"unfamiliar reader shape, attributes: {sorted(a for a in dir(reader) if not a.startswith('_'))}")
    return []


def extract(reader, name: str) -> bytes | None:
    for attempt in ("extract", "extract_file", "open_embedded_archive"):
        fn = getattr(reader, attempt, None)
        if fn is None:
            continue
        try:
            data = fn(name)
        except Exception:  # noqa: BLE001 - try the next shape
            continue
        if isinstance(data, tuple) and len(data) == 2:
            data = data[1]
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
    return None


def _macho_slices(data: bytes) -> list[bytes]:
    """Split universal binary bytes into its architecture slices; a thin one is a list of one."""
    if data[:4] == b"\xca\xfe\xba\xbe":
        (count,) = struct.unpack_from(">I", data, 4)
        out = []
        for i in range(count):
            _cputype, _cpusubtype, offset, size, _align = struct.unpack_from(">5I", data, 8 + 20 * i)
            out.append(data[offset : offset + size])
        return out
    return [data]


def _code_signature_blob(sl: bytes) -> bytes | None:
    """Return the embedded signature of one Mach-O slice, or None when it carries none."""
    magic = sl[:4]
    if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        endian = "<"
        wide = magic == b"\xcf\xfa\xed\xfe"
    elif magic in (b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"):
        endian = ">"
        wide = magic == b"\xfe\xed\xfa\xcf"
    else:
        raise ValueError(f"not a thin Mach-O slice: {magic!r}")
    (ncmds,) = struct.unpack_from(endian + "I", sl, 16)
    offset = 32 if wide else 28
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from(endian + "2I", sl, offset)
        if cmdsize == 0:
            raise ValueError("load command of zero length, the header is not walkable")
        if cmd == LC_CODE_SIGNATURE:
            dataoff, datasize = struct.unpack_from(endian + "2I", sl, offset + 8)
            return sl[dataoff : dataoff + datasize]
        offset += cmdsize
    return None


def _code_directory(signature: bytes) -> dict[str, object]:
    """Read the flags word and Team ID out of an embedded signature's CodeDirectory."""
    magic, _length, count = struct.unpack_from(">3I", signature, 0)
    if magic != CSMAGIC_EMBEDDED_SIGNATURE:
        raise ValueError(f"not an embedded signature superblob: 0x{magic:08x}")
    for i in range(count):
        slot, offset = struct.unpack_from(">2I", signature, 12 + 8 * i)
        (blob_magic,) = struct.unpack_from(">I", signature, offset)
        if slot != CSSLOT_CODEDIRECTORY or blob_magic != CSMAGIC_CODEDIRECTORY:
            continue
        cd = signature[offset:]
        _m, _len, version, flags, _hash_off, _ident_off, _nss, _ncs, _limit = struct.unpack_from(CD_FIXED_FIELDS, cd, 0)
        team = None
        if version >= CD_VERSION_WITH_TEAM_ID:
            (team_offset,) = struct.unpack_from(">I", cd, CD_TEAM_OFFSET)
            if team_offset:
                end = cd.index(b"\0", team_offset)
                team = cd[team_offset:end].decode("utf-8", "replace")
        return {"state": "parsed", "flags": flags, "team": team}
    raise ValueError("the signature carries no CodeDirectory")


def code_directories(data: bytes) -> list[dict[str, object]]:
    """Report the signing state of every architecture slice in the given Mach-O bytes.

    Each entry is one of three states, and they are three different answers rather
    than degrees of one. ``parsed`` carries the flags word and the Team ID.
    ``unsigned`` means the slice has no LC_CODE_SIGNATURE at all, which settles the
    hardened question in the negative rather than leaving it open. ``unreadable``
    means there is a signature here that this code could not walk, which settles
    nothing and has to be reported as such.

    Read from the member's own bytes rather than by writing it out and asking
    codesign, so the answer does not depend on the machine reading it. That matters
    for what this predicate is for: the property travels inside the archive to a
    user's Mac, and it is decided at build time on a runner that never enforces it.
    """
    out: list[dict[str, object]] = []
    try:
        parts = _macho_slices(data)
    except Exception as exc:  # noqa: BLE001 - a header we cannot walk is one answer
        return [{"state": "unreadable", "why": f"the universal header did not parse: {exc}"}]
    for sl in parts:
        try:
            signature = _code_signature_blob(sl)
        except Exception as exc:  # noqa: BLE001
            out.append({"state": "unreadable", "why": f"the load commands did not parse: {exc}"})
            continue
        if signature is None:
            out.append({"state": "unsigned"})
            continue
        try:
            out.append(_code_directory(signature))
        except Exception as exc:  # noqa: BLE001
            out.append({"state": "unreadable", "why": f"the signature did not parse: {exc}"})
    return out


def hardened_without_team(data: bytes) -> tuple[bool, list[str]]:
    """Answer the second question this file asks of a member, and say when it cannot.

    Returns whether any slice is signed with the hardened runtime while carrying no
    Team ID, and the reasons any slice could not be read. That pairing is what makes
    a process refuse its own payload: the hardened runtime turns on library
    validation, library validation accepts only a library carrying the loading
    process's Team ID or a platform identity, and an ad-hoc binary carries neither.
    Both sides of the load are then refused for disagreeing about a Team ID that
    neither of them has.

    Deliberately narrower than "no member may be hardened". A member signed with a
    real Developer ID and the hardened runtime is the correct end state described in
    docs/desktop/MACOS_NOTARIZATION.md, and a check that fired on it would have to be
    turned off the day that work lands, which is the day it is most worth having.
    """
    bad = False
    reasons: list[str] = []
    for entry in code_directories(data):
        if entry["state"] == "unreadable":
            reasons.append(str(entry.get("why", "unreadable")))
        elif entry["state"] == "parsed" and int(entry["flags"]) & CS_RUNTIME and not entry["team"]:
            bad = True
    return bad, reasons


def describe(path: Path) -> dict[str, str]:
    proc = subprocess.run(
        ["codesign", "-dvvv", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = proc.stdout + proc.stderr
    team = TEAM_ID.search(text)
    sig = SIGNATURE.search(text)
    flags = FLAGS.search(text)
    return {
        "team": team.group(1).strip() if team else ("unsigned" if "not signed" in text else "unknown"),
        "signature": sig.group(1).strip() if sig else "none",
        "flags": flags.group(1).strip() if flags else "-",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("executable", type=Path)
    parser.add_argument(
        "--limit",
        type=int,
        default=600,
        help="stop after this many Mach-O members; the count skipped is always printed",
    )
    parser.add_argument(
        "--fail-on-foreign-team-id",
        action="store_true",
        help=(
            "exit non-zero when any member's Team ID differs from the wrapper's, "
            "in either direction, and also when any member could not be read, "
            "parsed or reached - a census that skipped members cannot support a "
            "claim about all of them"
        ),
    )
    parser.add_argument(
        "--fail-on-hardened-adhoc",
        action="store_true",
        help=(
            "exit non-zero when any member is signed with the hardened runtime "
            "while carrying no Team ID. That pair is unsatisfiable: it turns on "
            "library validation in a process that has no identity able to pass "
            "it, so the member is refused the rest of the payload it unpacks "
            "beside it. A member could not be read counts too"
        ),
    )
    parser.add_argument(
        "--require-member",
        action="append",
        metavar="SUBSTRING",
        help=(
            "fail unless a member whose name contains SUBSTRING was actually "
            "inspected. Repeatable. Use it to name the file in a failure report "
            "(for example Python.framework) so a run cannot clear it by silently "
            "never opening it."
        ),
    )
    args = parser.parse_args()

    # Existence is checked before the platform, and each answer leaves through
    # its own exit code. The order came first: the other way round, a call on a
    # non-macOS runner returned without opening anything, so "the artifact is
    # absent" and "the artifact is clean" were the same result.
    #
    # The order alone was not enough. "Not macOS" still returned 0, and 0 is
    # the number the workflow prints the word "clean" on, so a run with no
    # codesign to ask still reached the step summary as a cleared census - over
    # nothing. Those are the two claims this pair of branches has to keep
    # apart, and neither is a matter of degree: a run that asked no question
    # has no answer to report, and it exits 2 so that no reader downstream has
    # to infer that from a count.
    #
    # Absence keeps exit 1 rather than joining it. A file that is not there is
    # a fact about this build - the artifact that was supposed to be produced
    # was not - while the wrong platform is a fact about the runner. Folding
    # them together would rebuild the same collapse one level up.
    if not args.executable.is_file():
        print(f"no such file: {args.executable}")
        return EXIT_ALARM
    if sys.platform != "darwin":
        print(f"UNKNOWN: codesign only exists on macOS, so nothing here read {args.executable}")
        print("This run has no opinion about the archive. It is not a clean census, it is no census.")
        return EXIT_UNKNOWN

    wrapper = describe(args.executable)
    print(f"wrapper: Signature={wrapper['signature']} TeamIdentifier={wrapper['team']} flags={wrapper['flags']}")
    print()

    reader, reader_rc = open_archive(args.executable)
    if reader is None:
        return reader_rc

    names = member_names(reader)
    print(f"archive members: {len(names)}")

    workdir = Path(tempfile.mkdtemp(prefix="sidecar-inspect-"))
    try:
        checked = 0
        skipped_over_limit = 0
        unreadable_names: list[str] = []
        inspected_names: list[str] = []
        by_team: dict[str, list[str]] = {}
        hardened_adhoc: list[str] = []
        unreadable_flags: list[str] = []
        for name in names:
            data = extract(reader, name)
            if data is None:
                # Keep the name, not just a tally. A member the reader cannot
                # open is not a member without a Team ID: it is a member nobody
                # looked at, and it drops out of every count below. The 402
                # figure this script produced was read as "every member is
                # ad-hoc" when what it could support was "every member we could
                # open is ad-hoc" - and the one file named in the failure is
                # precisely the one whose absence from the census would be
                # invisible.
                unreadable_names.append(name)
                continue
            if data[:4] not in MACHO_MAGIC:
                continue
            if checked >= args.limit:
                skipped_over_limit += 1
                continue
            # The second question, asked of the same bytes and before they are
            # written anywhere. It is a different property from the Team ID
            # census below and neither one implies the other: every member of
            # the 17.1.0 archive agreed with the wrapper about the Team ID, all
            # of them having none, and every one of them was hardened, which is
            # the state that made the app unusable. See issue #480.
            bad_flags, why = hardened_without_team(data)
            if bad_flags:
                hardened_adhoc.append(name)
            unreadable_flags.extend(f"{name}: {reason}" for reason in why)

            target = workdir / Path(name).name
            target.write_bytes(data)
            info = describe(target)
            by_team.setdefault(info["team"], []).append(name)
            inspected_names.append(name)
            checked += 1
            target.unlink(missing_ok=True)

        print(f"Mach-O members inspected: {checked}")
        if skipped_over_limit:
            print(f"Mach-O members NOT inspected because --limit {args.limit} was reached: {skipped_over_limit}")
        if unreadable_names:
            print(f"members the reader could not extract: {len(unreadable_names)}")
            for name in sorted(unreadable_names)[:12]:
                print(f"    {name}")
            if len(unreadable_names) > 12:
                print(f"    ... and {len(unreadable_names) - 12} more")
        print()
        for team in sorted(by_team):
            members = by_team[team]
            print(f"TeamIdentifier={team}: {len(members)} member(s)")
            for name in sorted(members)[:12]:
                print(f"    {name}")
            if len(members) > 12:
                print(f"    ... and {len(members) - 12} more")

        # What dyld compares is the mapped file's Team ID against the process's,
        # so a member is foreign when it disagrees with the wrapper, not when it
        # merely carries an identity. Reading it as "carries one" made this
        # script blind in the other direction: a wrapper signed with a real Team
        # ID over members PyInstaller left ad-hoc disagrees just as completely,
        # and used to leave here printing an all-clear.
        wrapper_team = None if wrapper["team"] in ("not set", "unsigned", "unknown") else wrapper["team"]
        foreign = {
            t: m
            for t, m in by_team.items()
            if t != "unknown" and (None if t in ("not set", "unsigned") else t) != wrapper_team
        }
        # "unknown" means codesign printed something this script could not parse
        # a TeamIdentifier out of. Folding it into "no Team ID" is how a member
        # whose signature could not be read came to be counted as evidence that
        # no member has one. It is inconclusive, and it belongs with the members
        # that could not be extracted at all, and with the ones the reader never
        # reached because --limit stopped it: all three are members nobody
        # measured, and a verdict cannot be wider than the census under it.
        inconclusive = list(by_team.get("unknown", [])) + unreadable_names
        if skipped_over_limit:
            inconclusive.append(f"<{skipped_over_limit} member(s) never reached, --limit {args.limit}>")
        # The wrapper is one end of every comparison below. If its own signature
        # did not parse, there is no value to compare members against, and a
        # verdict either way would be about a number this run never read.
        if wrapper["team"] == "unknown":
            inconclusive.append(f"<the wrapper itself: {args.executable}>")
        if inconclusive:
            print()
            print(
                f"INCONCLUSIVE: {len(inconclusive)} item(s) were not read or not parsed, "
                "so no statement about the archive as a whole is supported by this run."
            )
            # Name them here rather than only counting them. This is the message
            # a red build is read from, and a count alone sends the reader back
            # to the runner to find out which of three unrelated reasons fired.
            for item in sorted(inconclusive)[:12]:
                print(f"    {item}")
            if len(inconclusive) > 12:
                print(f"    ... and {len(inconclusive) - 12} more")

        missing_required = [pat for pat in (args.require_member or []) if not any(pat in n for n in inspected_names)]
        if missing_required:
            print()
            for pat in missing_required:
                print(f"NOT INSPECTED: no member whose name contains {pat!r} was measured.")
            print("A census that never opened the file named in the failure cannot clear it.")

        if foreign and wrapper_team is None:
            print()
            print("MISMATCH: the wrapper carries no Team ID and these members do.")
            print("This is the shape that makes dyld refuse to map them into the process.")
        elif foreign:
            print()
            print(f"MISMATCH: the wrapper carries Team ID {wrapper_team} and these members do not.")
            print(
                "The wrapper is the process at launch, so every member it unpacks is compared "
                "against that Team ID and refused for disagreeing with it. Signing the wrapper "
                "alone produces this: the members are sealed inside the file by then and no "
                "later signing pass reaches them."
            )
        elif not inconclusive and not missing_required:
            print()
            if wrapper_team is None:
                print("No member carries a Team ID, so no member can disagree with the process about one.")
            else:
                print(
                    f"Every inspected member carries the wrapper's Team ID {wrapper_team}, "
                    "so none disagrees with the process."
                )

        # The second verdict, printed whether or not its gate is on, because a
        # run that measured the property and said nothing about it is how this
        # one went unnoticed for eleven releases. describe() has always read the
        # flags word; only the wrapper's was ever printed, and the wrapper is
        # the one file in the artifact that something re-signs afterwards.
        wrapper_hardened = "runtime" in wrapper["flags"] and wrapper_team is None
        print()
        if wrapper_hardened:
            print(
                f"HARDENED AD-HOC: the wrapper itself is signed {wrapper['flags']} with no Team ID. "
                "Library validation is on and nothing it unpacks can satisfy it."
            )
        if hardened_adhoc:
            print(f"HARDENED AD-HOC: {len(hardened_adhoc)} member(s) carry the hardened runtime and no Team ID.")
            print(
                "Each of these runs, or is loaded into something that runs, under library validation "
                "with no identity able to pass it. A member spawned as its own process out of the "
                "extraction directory is refused the libraries sitting next to it, and the loader "
                "words that refusal as a Team ID disagreement even though neither side has one."
            )
            for member in sorted(hardened_adhoc)[:12]:
                print(f"    {member}")
            if len(hardened_adhoc) > 12:
                print(f"    ... and {len(hardened_adhoc) - 12} more")
        if unreadable_flags:
            print(f"flags not readable on {len(unreadable_flags)} slice(s):")
            for item in sorted(unreadable_flags)[:12]:
                print(f"    {item}")
            if len(unreadable_flags) > 12:
                print(f"    ... and {len(unreadable_flags) - 12} more")
        if not wrapper_hardened and not hardened_adhoc and not unreadable_flags:
            print(
                f"No member of the {len(inspected_names)} inspected is hardened without a Team ID, "
                "so none is running under a library validation it cannot satisfy."
            )

        # Under the gate, a disagreeing member, an unread member and an
        # unmeasured required member are each failures in their own right: the
        # gate's whole claim is that nothing in there disagrees with the process,
        # and that claim is only as wide as what was opened.
        # The denominator, printed next to the verdict rather than left to the
        # reader. A census that opened nothing and a census that opened every
        # member otherwise reach the summary as the same word, and "clean" over
        # zero objects is a different statement from "clean" over many.
        print()
        print(f"census: {len(inspected_names)} member(s) inspected")

        # A partial census is an alarm, not an unknown. Exit 2 is reserved for
        # a run that read nothing at all, and this one did: it opened the
        # archive, measured some members and can name the ones it could not.
        # The claim the gate makes is about the whole archive, so a census
        # narrower than the archive fails it - but the run still has facts to
        # report, which is exactly what separates it from the branches above.
        if args.fail_on_foreign_team_id and (foreign or inconclusive or missing_required):
            return EXIT_ALARM
        # The same rule for the second question. A census narrower than the
        # archive cannot clear the archive of this either, so the shared
        # inconclusive list counts here as well as above.
        if args.fail_on_hardened_adhoc and (
            hardened_adhoc or wrapper_hardened or unreadable_flags or inconclusive or missing_required
        ):
            return EXIT_ALARM
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
