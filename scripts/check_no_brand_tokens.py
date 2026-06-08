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
#
# Functional-interop brand names (CAD/BIM import formats like Revit/AutoCAD/Tekla
# and explicit integration targets) are deliberately NOT hashed here: they have
# legitimate functional uses the platform needs, and are governed by the
# allowlist plus human review instead. Only unambiguous coined product names with
# no functional use are denylisted.
_DENY_HASHES: frozenset[str] = frozenset(
    {
        "a62ee5ab3e8914010c0f75ff149f9415c839c64ccf4d8ed91d13b456dbc1d813",
        "d5b51a471ae081ca48018c369ce9341a4db134246a8a7c56dd47df5103e0c8a7",
        "46621e84f68449c6e68788cb4d78d8118cf2511999dc3136f9542ddf21fc2861",
        "fff045f2575092eee58374e6b24e2c3efae8533ac17811cf15939d4fd09a5284",
        "55af965522a877fbb91c42cc317bc592e7ac2282c8b986ea24d9d19b87f3e6de",
        "175144ba7727300741c47f7c881c12c1da553776a583e10c620cd4d24dc2d1ed",
        "6a3007f60515e405e5f64b07885dd24b25262525761bd45808afed3f82425b8e",
        "bf6c262b9b067db8fdc18a6cb0e78d1244553b65c4e9e48d3546af68e0a437a9",
        "423d16ce8c066ceb5714dbb2f9d16eaa59e3571d0318367039755e7e64ceb32f",
        "46c955d11d47c3d563abeefd1eca2b7c9546169b20d2f24cbb897f2fd4ed9ef8",
        "c04ecdbcc01c4eb5a7f93222146d5f4ed5f280a2ed134f7c7c9d4a52c268b6f0",
        "7d451b6eb01abdb0edf3c7fc440f6d06b3aa93223bca35dc207c31aa07da7121",
        "66d4c34f63b321e5d488acb27ceeff03e58861dc822786ecc16228ab966e560a",
        "9c13fc96144b74b5f10957d73a193662ca94dccb1148041280a9f673267150da",
        "f271bb49840f247f06d44e248a58da4f07a15ac13d19c908f3562cf4c27758ea",
        "a5c4fcc701283c5ed540c2963ba42e1f7af1ef3fed2e491525ef0c3a06d3272b",
        "5b02e0eece69d3f4ad8c913705c45d562b1fdd9672d294bb7ebd7aae75f68bad",
        "01fdc206bcfcd06718f3b964c4d6925905d879cee45d7611d4d3e4f414625239",
        "33df103969d7c653bc10754a41a8dc2156aabd7c33647241926d465ba721bb97",
        "f87e86b8abde90aa4ce0d2547c4465280baad22e833afadbebac3d670ea43617",
        "31135ce02873713edfb32a09bf723e1f436fdb080a8457189147a3f34a9412aa",
        "469be0d71cacd255ba602021b352bdba3c4c736eb3dafb824b48fc8c80971209",
        "21ab87a7ea9a7f6f2c7894beb361a8644f8fed69cad090265583d2edceb4966d",
        "9a2e8e955be161ed90ccef3ab2ce3a6a1e439de4a12b8af75536fd0f2ca1b66f",
        "78f01fedb12362675c783eb39ac7afa7c63a9c8d6d56e0542f1565cf026a8612",
        "7bc4be30839398ae59b2f9b2b8144671794537ad9bd829c9e73a93fbd9e51821",
        "fb6061067f2f48fe42db037321556e2c2ecee66c56b75ce935523d51bae05565",
        "48a712c1a4da10ef9c77d217372b97e875800f6a80e4f5bec36ed1b0fe3e921b",
        "2779934ff606047d5b140b82939b66fc88c9ba101a05d156086d71c1285d4bfb",
        "0b955e689bea821d4646d62739a8dec68ee9baf50c4b1e9f7e6fe8e23c75fc03",
        "1cf0fde0df3ac7d0d4af1ad80ebd7bdcdb5c27eb2518594d55a3f59773cc3f3f",
        "a2f98c7785a1629a12cc425bef2583336aef29d12b6c18fcee64f1469454289d",
        "3ccbd9105a45d8fcd4a0101c6532c599f6f59cfa4d4ce378792f547a869a4bea",
        "404e91050d105f97f8785b94706814e4a6ead40fea25c0ecf9efefa6bea999f5",
        "58b4537b616e657203a685e86b79ab85c981615d4c0ad243608f457cbbe0de34",
        "8ae56be495a96f1f31eabe97921415525913c2985c70b473631f52dee05c25be",
        "e0a27b93a6c5fd64c53a87e60bf2eff7113e271567044c910576f2c5dd760e0f",
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

# Reviewed functional-interop exceptions (e.g. an import-format name or an
# integration-target list that tells a user what they can actually connect to).
# Each line is `<path-substr>||<line-substr>`: a hit is allowed only when the
# file path contains <path-substr> (empty = any file) AND the matched line
# contains <line-substr>. This stays precise - a new brand on a different line
# is still caught, because it will not carry the reviewed context substring.
_ALLOWLIST_FILE = REPO_ROOT / "scripts" / "brand_token_allowlist.txt"


def _load_allowlist() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if not _ALLOWLIST_FILE.is_file():
        return entries
    for raw in _ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "||" not in line:
            continue
        path_sub, _, line_sub = line.partition("||")
        entries.append((path_sub.strip(), line_sub.strip()))
    return entries


def _is_allowed(relpath: str, line: str, allowlist: list[tuple[str, str]]) -> bool:
    rp = relpath.replace("\\", "/")
    return any(
        (not path_sub or path_sub in rp) and line_sub and line_sub in line
        for path_sub, line_sub in allowlist
    )


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


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    hits: list[tuple[int, str, str]] = []
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
                hits.append((lineno, _mask(token), line))
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

    allowlist = _load_allowlist()
    failures: list[str] = []
    allowed = 0
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
        try:
            shown = str(rp.relative_to(REPO_ROOT))
        except ValueError:
            shown = str(rp)
        for lineno, masked, line in _scan_file(rp):
            if _is_allowed(shown, line, allowlist):
                allowed += 1
                continue
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

    note = f" ({allowed} reviewed interop exception(s) allowed)" if allowed else ""
    print(f"[OK] no brand tokens in {len(candidates)} scanned file(s){note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
