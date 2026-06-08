#!/usr/bin/env python3
"""Fail the build if a competitor or vendor brand token leaks into the repo.

Founder rule (strict): competitor and vendor product names must never appear in
any commit, code, UI string, changelog, or build artifact. Internal research
stays internal; everything shippable uses neutral generic names.

This gate enforces that automatically so it does not rely on a reviewer
remembering. It is wired into both the local pre-commit hook and CI, exactly
like ``check_version_sync.py``.

Brand-safe by design: this file stores only SHA-256 hashes of the lowercased
brand tokens, never the literal brand strings, so the denylist itself does not
put a brand name in the repo. Because SHA-256 collisions are infeasible, the gate
matches ONLY the exact brand tokens, which means it cannot raise a false positive
on an unrelated word. Generic dictionary words that happen to also be product
names are intentionally left out of the automated list (they would match the
ordinary English word) and are covered by human review instead.

When a match is found the report prints the file, line, and a MASKED form of the
token (first and last character plus length) so a developer can locate and remove
it without the log reproducing the full brand string.

Exit codes:
    0  no brand token found in the scanned files
    1  at least one brand token found (with file:line locations)

Usage::

    python scripts/check_no_brand_tokens.py                # scan all tracked text files (full audit)
    python scripts/check_no_brand_tokens.py path/a path/b  # scan given files (pre-commit)
    python scripts/check_no_brand_tokens.py --since origin/main   # scan only files changed vs a ref (CI guard)

The ``--since`` mode guards against NEW leaks without failing on pre-existing
debt, which is the right way to turn the gate on while a one-time legacy cleanup
proceeds separately. Run with no args for the full audit that drives that cleanup.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# SHA-256 of the lowercased brand tokens. No literal brand strings in this file.
# Add a hash here (python -c "import hashlib;print(hashlib.sha256(b'<token>').hexdigest())")
# to extend coverage. Keep to unambiguous coined brand tokens to avoid matching
# ordinary words.
_DENY_HASHES: frozenset[str] = frozenset(
    {
        "a62ee5ab3e8914010c0f75ff149f9415c839c64ccf4d8ed91d13b456dbc1d813",
        "d5b51a471ae081ca48018c369ce9341a4db134246a8a7c56dd47df5103e0c8a7",
        "46621e84f68449c6e68788cb4d78d8118cf2511999dc3136f9542ddf21fc2861",
        "fff045f2575092eee58374e6b24e2c3efae8533ac17811cf15939d4fd09a5284",
        "55af965522a877fbb91c42cc317bc592e7ac2282c8b986ea24d9d19b87f3e6de",
        "175144ba7727300741c47f7c881c12c1da553776a583e10c620cd4d24dc2d1ed",
    }
)

# Brand tokens are coined names 5 to 12 characters long. Only hash candidate
# runs in that range so the scan stays fast on large files.
_MIN_LEN = 5
_MAX_LEN = 14
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Only scan source and content file types; skip binaries and vendored trees.
_TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".md", ".mdx",
    ".html", ".css", ".scss", ".yml", ".yaml", ".toml", ".txt", ".sql", ".sh",
    ".env", ".cfg", ".ini", ".rs", ".vue", ".svelte",
}
_SKIP_PARTS = {
    ".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".ruff_cache", "target", "_frontend_dist",
}
# This gate stores hashes, never literals, so it never matches itself, but skip
# it anyway to keep the report clean.
_SELF = Path(__file__).resolve()


def _git_files(args: list[str]) -> list[Path]:
    out = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = []
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        p = REPO_ROOT / rel
        if p.suffix.lower() in _TEXT_SUFFIXES:
            files.append(p)
    return files


def _tracked_text_files() -> list[Path]:
    return _git_files(["ls-files"])


def _changed_text_files(ref: str) -> list[Path]:
    # Files changed vs the ref (committed diff) plus anything staged/unstaged,
    # so the CI guard catches a leak whether it is committed or in flight.
    seen: dict[str, Path] = {}
    for spec in (["diff", "--name-only", f"{ref}...HEAD"], ["diff", "--name-only", "HEAD"]):
        try:
            for p in _git_files(spec):
                seen[str(p)] = p
        except subprocess.CalledProcessError:
            pass
    return list(seen.values())


def _mask(token: str) -> str:
    if len(token) <= 2:
        return "*" * len(token)
    return f"{token[0]}{'*' * (len(token) - 2)}{token[-1]} (len {len(token)})"


def _scan_file(path: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return hits  # binary or unreadable - nothing to check
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _TOKEN_RE.finditer(line.lower()):
            token = match.group(0)
            if not (_MIN_LEN <= len(token) <= _MAX_LEN):
                continue
            if hashlib.sha256(token.encode("utf-8")).hexdigest() in _DENY_HASHES:
                hits.append((lineno, _mask(token)))
    return hits


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--since":
        if len(argv) < 2:
            print("[FAIL] --since needs a git ref, e.g. --since origin/main")
            return 1
        candidates = _changed_text_files(argv[1])
    elif argv:
        candidates = [Path(a).resolve() for a in argv]
    else:
        candidates = _tracked_text_files()

    failures: list[str] = []
    for path in candidates:
        rp = path.resolve()
        if rp == _SELF:
            continue
        if any(part in _SKIP_PARTS for part in rp.parts):
            continue
        if rp.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if not rp.is_file():
            continue
        for lineno, masked in _scan_file(rp):
            try:
                shown = rp.relative_to(REPO_ROOT)
            except ValueError:
                shown = rp
            failures.append(f"{shown}:{lineno}: brand token {masked}")

    if failures:
        print("[FAIL] competitor/vendor brand token(s) found - remove and use a neutral name:")
        for f in failures:
            print(f"  {f}")
        print(
            "\nThese product names must never appear in the repo. Replace with the "
            "neutral generic term used elsewhere in the codebase."
        )
        return 1

    print(f"[OK] no brand tokens in {len(candidates)} scanned file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
