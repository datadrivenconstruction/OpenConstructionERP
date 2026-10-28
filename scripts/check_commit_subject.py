#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commit subject guard: reject a shell quoting artefact in the subject line.

Twelve commits in this history open with ``@ `` before their real subject,
among them the v14.6.0 release commit. None of that was intended. A PowerShell
here-string opener (``@'``) written on the same line as ``git commit -m`` is
consumed as the start of the message, so git takes it as the subject and the
sentence the author wrote lands underneath it. The message reads fine in the
editor and wrong in ``git log``, and nothing between the two says so.

The rule this guards is narrow on purpose. It does not ask a subject to be a
conventional commit: several hundred subjects in this history are not, and
retrofitting that is a separate decision. It asks only that the subject not be
a fragment of the shell that produced it, which is never a style preference and
always a corrupted message.

Two rules, deliberately scoped differently:

  * The artefact rule runs in every mode. The twelve commits that already carry
    it are published and one of them is the target of the v14.6.0 tag, so they
    are listed below as history that cannot be rewritten rather than treated as
    failures.
  * The dash rule runs only on a message being written. Long dashes are against
    project style, but 2094 existing messages use one, so a scan of history
    would report a decision nobody has taken rather than a defect.

Three ways to run it, matching check_commit_trailers.py:

    python scripts/check_commit_subject.py                # all commits from HEAD (CI)
    python scripts/check_commit_subject.py --range A..B   # a revision range
    python scripts/check_commit_subject.py <msgfile>      # one message file (commit-msg hook)

Exit code 0 means clean. Exit code 1 lists every offending commit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# Subjects that are a piece of the shell rather than a sentence. Each rule is
# anchored so an ordinary subject cannot trip it: a subject may contain an @ or a
# backtick anywhere, it just may not begin or end as an unterminated quote.
_ARTEFACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # @' or @" swallowed into -m. Two shapes, and both have to match: the opener
    # can end the line, or the real subject can follow it on the same line, which
    # is why the twelve below read almost correctly and got pushed.
    (
        re.compile(r"^@[\"']?(?=\s|$)"),
        "PowerShell here-string opener leaked into the subject",
    ),
    # The matching closer, alone on the line git took as the subject.
    (re.compile(r"^[\"']@\s*$"), "PowerShell here-string closer used as the subject"),
    (re.compile(r"^<<"), "shell heredoc operator leaked into the subject"),
    (
        re.compile(r"^(?:EOF|EOM|END|PY|SQL|MSG)[\"']?\s*$"),
        "heredoc delimiter used as the subject",
    ),
]

_DANGLING_BACKTICK_WHY = "PowerShell line-continuation backtick at the end of the subject"


def _has_dangling_backtick(subject: str) -> bool:
    """A trailing backtick is an artefact only when nothing opened it.

    "stop the flag breaking `--help`" ends in a backtick and is a fine subject,
    so the test is parity rather than position: a continuation backtick is the
    odd one out, a code span closes what it opened.
    """
    return subject.rstrip().endswith("`") and subject.count("`") % 2 == 1


# Em dash and en dash. Project style is a hyphen, a comma or a full stop.
_LONG_DASH_RX = re.compile(r"[—–]")

# Published commits whose subject already carries the artefact. They are all
# reachable from origin/main and 769714adb is what the v14.6.0 tag points at, so
# rewriting them would move a released tag off the tree it shipped. Recorded here
# so the guard can run over the whole history without reporting them every time.
# Nothing may be added to this list: a new offender means the hook was skipped.
_PUBLISHED_OFFENDERS = frozenset(
    {
        "f3962132d15049a6702614e2cdaa56ad25c5c178",
        "317abb9803e1047343a84e5c88192816b5f39bec",
        "1af2c5b1cbb642b850405f3c15b9ffc47fb9f2fe",
        "ab7ad351c3ac45ad2a3cbca7698ac613b959a91d",
        "92acc847a768c05d2af9e9b0f6e61c0d1e87e354",
        "0d37da30f705620401139e0219d569f43a5286b3",
        "9585387f6625ed9e85e0a89cf4d1995a7cddb1ea",
        "e914945189c767c98fbbedbe66bc2a8dd3850b92",
        "769714adb3e2f5685ded3b1397558af9e48bd28e",  # the v14.6.0 release commit
        "9e0866bfb7c8a99e464783ce96b599d16ff8e0cc",
        "c828c606b484da9f1bf874afe91dcba5b10ad6e5",
        "51356bbde5c4c791e2b823a445f7c1f351bf868f",
    }
)

_RECORD_SEP = "\x00"
_FIELD_SEP = "\x1f"


def _subject_of(message: str) -> str:
    """The subject is the first non-empty line, which is what git log shows."""
    for line in message.splitlines():
        if line.strip():
            return line
    return ""


def _artefact_reasons(subject: str) -> list[str]:
    reasons = [f"{why}: {subject[:72]!r}" for pattern, why in _ARTEFACT_PATTERNS if pattern.search(subject)]
    if _has_dangling_backtick(subject):
        reasons.append(f"{_DANGLING_BACKTICK_WHY}: {subject[:72]!r}")
    return reasons


def _dash_reasons(message: str) -> list[str]:
    """Only ever applied to a message being written; see the module docstring."""
    return [
        f"long dash in the commit message, project style is a hyphen: {line.strip()[:72]!r}"
        for line in message.splitlines()
        if _LONG_DASH_RX.search(line)
    ]


def _commits(rev_range: str | None) -> list[tuple[str, str]]:
    """Return ``(sha, message)`` for each commit, framed by git's own escapes.

    Same framing as check_commit_trailers.py: %x1f / %x00 keep a NUL byte off the
    command line, which Windows forbids, and git expands them in its output.
    """
    cmd = ["git", "log", "--format=%H%x1f%B%x00"]
    if rev_range:
        cmd.append(rev_range)
    out = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=True).stdout
    commits: list[tuple[str, str]] = []
    for record in out.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, message = record.partition(_FIELD_SEP)
        commits.append((sha, message))
    return commits


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reject a shell quoting artefact in a commit subject line.",
    )
    parser.add_argument(
        "message_file",
        nargs="?",
        help="a single commit-message file to scan (commit-msg hook mode)",
    )
    parser.add_argument(
        "--range",
        dest="rev_range",
        help="a git revision range to scan, e.g. origin/main..HEAD",
    )
    args = parser.parse_args()

    offenders: list[str] = []
    if args.message_file:
        with open(args.message_file, encoding="utf-8", errors="replace") as handle:
            message = handle.read()
        # A comment line is git's own scaffolding and is stripped before the
        # commit is made, so it must not be read as the subject or scanned.
        message = "\n".join(line for line in message.splitlines() if not line.startswith("#"))
        reasons = _artefact_reasons(_subject_of(message)) + _dash_reasons(message)
        offenders.extend(f"(staged commit message): {reason}" for reason in reasons)
        where, scanned = f"message file {args.message_file}", 1
    else:
        commits = _commits(args.rev_range)
        scanned = len(commits)
        for sha, message in commits:
            if sha in _PUBLISHED_OFFENDERS:
                continue
            offenders.extend(f"{sha[:12]}: {reason}" for reason in _artefact_reasons(_subject_of(message)))
        where = args.rev_range or "all commits reachable from HEAD"

    if offenders:
        print(
            f"ERROR: commit message rejected in {where} ({len(offenders)}):",
            file=sys.stderr,
        )
        for line in offenders:
            print(f"  {line}", file=sys.stderr)
        # Two rules with two different remedies, so print only the advice that
        # fits what actually failed.
        if any("dash" in line for line in offenders):
            print(
                "\nProject style writes a hyphen, a comma or a full stop where a long "
                "dash would go, in commits as in everything else public. Replace the "
                "character and commit again.",
                file=sys.stderr,
            )
        if any("dash" not in line for line in offenders):
            print(
                "\nThe subject is the first line of the message, and a shell fragment "
                "there is what git log will show forever. This usually means a "
                "here-string opener was written on the same line as 'git commit -m'. "
                "Write the message to a file and pass 'git commit -F <file>' instead, "
                "then confirm with 'git log -1 --format=%s'.",
                file=sys.stderr,
            )
        return 1

    print(f"commit subjects OK: {scanned} message(s) in {where}, no shell artefacts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
