#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commit attribution guard: forbid AI co-author / generated-by trailers.

Project policy (see CLAUDE.md): commits are authored solely by
DataDrivenConstruction. An automated assistant must never be recorded as a
contributor, so a commit message must not carry a ``Co-authored-by:`` trailer
naming an AI assistant, nor a "Generated with ..." advertising footer.

This guard scans commit messages and fails if any forbidden trailer is present.
It runs three ways:

    python scripts/check_commit_trailers.py                # all commits from HEAD (CI)
    python scripts/check_commit_trailers.py --range A..B   # a revision range
    python scripts/check_commit_trailers.py <msgfile>      # one message file (commit-msg hook)

Real human or bot co-authors (for example dependabot) are preserved: only a
trailer that names an AI assistant is rejected, and only on a dedicated trailer
or footer line, so ordinary prose that happens to mention a vendor is never
flagged.

Exit code 0 means clean. Exit code 1 lists every offending commit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# Forbidden ONLY on dedicated attribution lines, never in free prose:
#   * a Co-authored-by trailer that names an AI assistant, and
#   * a "Generated with <AI>" advertising footer (with or without the robot emoji).
# Requiring the name on a trailer/footer line is what keeps a commit whose subject
# legitimately discusses, say, an AI provider from being flagged.
_COAUTHOR_RX = re.compile(r"^\s*co-authored-by:.*\b(claude|anthropic)\b", re.IGNORECASE | re.MULTILINE)
_GENERATED_RX = re.compile(r"^\s*(?:\U0001f916\s*)?generated with\s+\[?\s*claude", re.IGNORECASE | re.MULTILINE)

_RECORD_SEP = "\x00"
_FIELD_SEP = "\x1f"


def _reasons(message: str) -> list[str]:
    reasons: list[str] = []
    for match in _COAUTHOR_RX.finditer(message):
        reasons.append(f"AI co-author trailer: {match.group(0).strip()!r}")
    for match in _GENERATED_RX.finditer(message):
        reasons.append(f"AI generated-by footer: {match.group(0).strip()!r}")
    return reasons


def _commits(rev_range: str | None) -> list[tuple[str, str]]:
    """Return ``(sha, message)`` for each commit, framed by git's own escapes.

    The format argument uses ``%x1f`` / ``%x00`` (printable text) so no NUL byte
    sits in the command line, which Windows forbids; git expands them to the real
    0x1f / 0x00 bytes in its output, which we split on below. Output is decoded as
    UTF-8 so a non-ASCII author or message survives on any platform.
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
        description="Forbid AI co-author / generated-by trailers in commit messages.",
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
        offenders.extend(f"(staged commit message): {reason}" for reason in _reasons(message))
        where, scanned = f"message file {args.message_file}", 1
    else:
        commits = _commits(args.rev_range)
        scanned = len(commits)
        for sha, message in commits:
            offenders.extend(f"{sha[:12]}: {reason}" for reason in _reasons(message))
        where = args.rev_range or "all commits reachable from HEAD"

    if offenders:
        print(
            f"ERROR: forbidden AI attribution trailer in {where} ({len(offenders)}):",
            file=sys.stderr,
        )
        for line in offenders:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nProject policy: commits are authored solely by DataDrivenConstruction "
            "and must not record an AI assistant as a contributor. Remove the "
            "Co-authored-by / Generated-with line from the commit message (amend the "
            "commit, or rebase to drop the trailer) and try again.",
            file=sys.stderr,
        )
        return 1

    print(f"commit attribution OK: {scanned} message(s) in {where}, no forbidden trailers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
