#!/usr/bin/env python3
"""Fail when a locale value loses its diacritics against its own earlier self.

The sibling check, ``check_locale_stripped_diacritics.py``, judges a value by
looking around it: a bare word is evidence only when the rest of the file, or
the rest of the catalogue outside its namespace, spells that word accented. Two
populations sit outside what such a rule can see. A value of one or two words
never reaches its minimum word count, so ``Ukoly`` and ``Schuzky`` are invisible
no matter how plainly wrong they are. And damage spread across several
namespaces supplies its own bare spelling as a second form, which switches the
cross-namespace rule off for exactly the strings it exists to catch.

This check asks a question the file cannot answer about itself and the damage
cannot suppress: did this key say something else in the commit before? A value
whose letters are unchanged and whose combining marks are fewer than the value
the same key carried a commit earlier has lost its accents, whatever the rest of
the file happens to spell. One key, two commits, no thresholds.

It found its first ten the day it was written: ten Czech module names reached
main as ``Rizeni projektu`` and ``Seznam nedodelku`` while the file spelled
those words with accents 46 and 290 times elsewhere, and both existing rules
stayed green through it.

Every commit in the window is examined against its own parent, rather than the
two ends of the window against each other. That distinction is the whole design.
Those ten accents were added after the previous release and removed before the
next one, so the two ends of that window agree and a comparison between them
reports nothing at all. Damage that arrives and departs inside one release is
still damage while it is there, and a rule that only reads the endpoints is
blind to precisely the case that prompted it.

The window is the most recent tag reachable from HEAD up to HEAD, so it resets
when the next release is cut and a regression stays visible on every run until
it is repaired.

A change that removes a diacritic on purpose, correcting a word that was
accented wrongly, belongs in the allowlist beside this file. The failure output
prints the entry to paste.

Usage::

    python scripts/check_locale_value_lost_diacritics.py
    python scripts/check_locale_value_lost_diacritics.py --base v16.8.3
    python scripts/check_locale_value_lost_diacritics.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = "frontend/src/app/locales/"
ALLOWLIST = Path(__file__).resolve().parent / "locale_lost_diacritics_allowlist.json"

#: ``    "some.key": "some value",`` and nothing else, with the leading diff
#: marker already removed. A value carrying an escaped quote is read too; a
#: value spanning several lines is not, and the report counts what it could not
#: read so a narrowed population cannot pass itself off as a clean one.
LINE = re.compile(r'^\s+"((?:[^"\\]|\\.)+)":\s*"((?:[^"\\]|\\.)*)",?\s*$')
ANY_KEY = re.compile(r'^\s+"[^"]+":')


def git(*args: str) -> str:
    """Run git in the repository and return stdout, raising on failure."""
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, encoding="utf-8")
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def marks(text: str) -> int:
    """How many combining marks ``text`` carries."""
    return sum(1 for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) == "Mn")


def skeleton(text: str) -> str:
    """``text`` with every combining mark removed, case preserved."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def lost_accents(old_value: str, new_value: str) -> bool:
    """True when the letters are unchanged and combining marks have gone."""
    return skeleton(old_value) == skeleton(new_value) and marks(old_value) > marks(new_value)


def read_diff(diff: str) -> tuple[list[tuple[str, str, str, str]], int, int]:
    """Pair removed and added values by key across one commit's locale diff.

    Returns the pairs as (locale, key, old value, new value), how many changed
    key lines were read, and how many were seen. The two numbers differ by the
    multi line values, which this reader does not attempt.
    """
    pairs: list[tuple[str, str, str, str]] = []
    seen = read = 0
    locale = ""
    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    def flush() -> None:
        for key, new_value in added.items():
            old_value = removed.get(key)
            if old_value is not None and old_value != new_value:
                pairs.append((locale, key, old_value, new_value))
        removed.clear()
        added.clear()

    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            flush()
            locale = Path(line.rsplit(" b/", 1)[-1]).stem
            continue
        if line.startswith(("+++", "---", "@@", "index ", "new file", "deleted file", "similarity ")):
            continue
        if not line or line[0] not in "+-":
            continue
        body = line[1:]
        if not ANY_KEY.match(body):
            continue
        seen += 1
        match = LINE.match(body)
        if not match:
            continue
        read += 1
        (removed if line[0] == "-" else added)[match.group(1)] = match.group(2)
    flush()
    return pairs, read, seen


def default_base() -> str:
    """The most recent tag reachable from HEAD, or the previous commit."""
    try:
        return git("describe", "--tags", "--abbrev=0").strip()
    except RuntimeError:
        return "HEAD~1"


def load_allowlist() -> dict[str, dict[str, str]]:
    if not ALLOWLIST.exists():
        return {}
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))


def value_at(rev: str, locale: str, key: str, cache: dict[str, dict[str, str]]) -> str | None:
    """The value ``key`` carries in ``locale`` at ``rev``, or None if it is gone."""
    if locale not in cache:
        try:
            text = git("show", f"{rev}:{LOCALES}{locale}.ts")
        except RuntimeError:
            text = ""
        values: dict[str, str] = {}
        for line in text.split("\n"):
            match = LINE.match(line)
            if match:
                values[match.group(1)] = match.group(2)
        cache[locale] = values
    return cache[locale].get(key)


def compare(base: str, head: str) -> tuple[list[tuple[str, str, str, str, str]], int, int, int]:
    """Walk every commit in base..head that touches a locale file.

    Returns the losses still standing at ``head``, as (commit, locale, key, old
    value, new value), the number of commits examined, and the changed key lines
    read against seen. A loss a later commit repaired is not reported: the rule
    is there to keep bare spellings out of the release, not to grade history.
    """
    commits = [c for c in git("log", "--format=%H", "--reverse", f"{base}..{head}", "--", LOCALES).split("\n") if c]
    allowed = load_allowlist()

    losses: list[tuple[str, str, str, str, str]] = []
    total_read = total_seen = 0
    for commit in commits:
        try:
            diff = git("diff", "--no-color", "-U0", f"{commit}^", commit, "--", LOCALES)
        except RuntimeError:
            continue  # a root commit has no parent to compare against
        pairs, read, seen = read_diff(diff)
        total_read += read
        total_seen += seen
        for locale, key, old_value, new_value in pairs:
            if not lost_accents(old_value, new_value):
                continue
            if allowed.get(locale, {}).get(key) == new_value:
                continue
            losses.append((commit[:9], locale, key, old_value, new_value))

    if losses:
        cache: dict[str, dict[str, str]] = {}
        standing = []
        for commit, locale, key, old_value, new_value in losses:
            current = value_at(head, locale, key, cache)
            if current is None or not lost_accents(old_value, current):
                continue
            standing.append((commit, locale, key, old_value, current))
        losses = standing
    return losses, len(commits), total_read, total_seen


def selftest() -> int:
    """Prove the predicate answers on the shapes the other rules miss."""
    cases = [
        ("Úkoly", "Ukoly", True, "one word, below every word count threshold"),
        ("Řízení změn", "Rizeni zmen", True, "two words, damaged in one edit"),
        ("Schůzky", "Schůzky", False, "unchanged"),
        ("Schuzky", "Schůzky", False, "a repair, not a loss"),
        ("Řízení změn", "Sprava zmen", False, "a different word, not this rule's business"),
        ("Infrastruktura", "Infrastruktura", False, "correct with no accent to lose"),
        ("naïve", "naive", True, "a mark inside a word"),
        ("Байланыш", "Байланыш", False, "Cyrillic left alone"),
        ("Ой", "Ои", True, "Cyrillic short i is a combining mark too"),
    ]
    bad = 0
    for old, new, want, why in cases:
        got = lost_accents(old, new)
        if got != want:
            bad += 1
            print(f"  selftest FAILED: {old!r} -> {new!r} gave {got}, expected {want} ({why})")

    diff = "\n".join(
        [
            "diff --git a/frontend/src/app/locales/cs.ts b/frontend/src/app/locales/cs.ts",
            "@@ -1,1 +1,1 @@",
            '-    "modules.catalog.tasks": "Úkoly",',
            '+    "modules.catalog.tasks": "Ukoly",',
        ]
    )
    pairs, read, seen = read_diff(diff)
    if [(p[0], p[1]) for p in pairs] != [("cs", "modules.catalog.tasks")] or read != seen != 2:
        bad += 1
        print(f"  selftest FAILED: the diff reader returned {pairs}, read {read} of {seen}")

    if bad:
        print(f"selftest: {bad} case(s) wrong")
        return 1
    print(f"selftest: {len(cases)} values and one diff, the rule answers as documented")
    return 0


def main() -> int:
    # The findings are accented text by definition, and a Windows console
    # defaults to a code page that cannot encode them. Without this the check
    # dies on its own first finding, which reads as a broken script rather than
    # as the defect it just caught.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=None, help="revision to start from (default: the most recent tag)")
    parser.add_argument("--head", default="HEAD", help="revision to check (default: HEAD)")
    parser.add_argument("--selftest", action="store_true", help="check the rule and exit")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    base = args.base or default_base()
    try:
        losses, commits, read, seen = compare(base, args.head)
    except RuntimeError as error:
        # Deliberately a failure and not a pass. This rule reads history, and
        # the job that runs it checks out at fetch-depth 0 precisely so that it
        # can. If the range will not resolve, the guard is not running, and a
        # guard that has stopped running must not be indistinguishable from a
        # guard that found nothing.
        print(f"locale value diacritics: cannot read {base}..{args.head}, so nothing was checked.")
        print(f"  {error}")
        print("  A shallow checkout is the usual cause; this guard needs fetch-depth 0 and the tags.")
        return 1

    population = (
        f"{commits} commit(s) touching a locale between {base} and {args.head}, {read} of {seen} changed key lines read"
    )

    if not losses:
        print(f"locale values keep their diacritics: {population}")
        return 0

    print(f"{len(losses)} locale value(s) lost their diacritics inside this release window.")
    print(f"  Population: {population}")
    for commit, locale, key, old_value, new_value in losses:
        print(f"  {commit} {locale}.ts: {key}")
        print(f"      was: {old_value}")
        print(f"      now: {new_value}")
    print()
    print("  Restore the accented spelling. If the removal is deliberate, add it to")
    print(f"  {ALLOWLIST.name} and say why in the commit message:")
    entry: dict[str, dict[str, str]] = {}
    for _, locale, key, _, new_value in losses:
        entry.setdefault(locale, {})[key] = new_value
    for line in json.dumps(entry, ensure_ascii=False, indent=2).split("\n"):
        print(f"      {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
