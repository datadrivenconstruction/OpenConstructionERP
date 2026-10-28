#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Locale escape guard, second direction: block escapes stripped to bare letters.

`check_locale_escapes.py` guards one way an escape sequence can be corrupted:
a doubled backslash, where `\\n` in the source becomes two literal backslashes
and renders as visible garbage. This guards the other way, where the backslash
is removed entirely and the escape body survives as an ordinary letter.

The result is worse than the doubled form, because it does not look like
corruption. bg `boq.lock_confirm`, a confirmation dialog, reads:

    Да се заключи ли тази оферта?nnЗаключените оферти не могат да се редактират.

against an English original of `Lock this estimate?\\n\\nLocked estimates
cannot be edited.` The paragraph break is gone and a bare `nn` sits inside a
Bulgarian sentence. Measured 2026-08-04: 24 values across 12 locales, all of
them strings a user reads - confirmation dialogs, onboarding subtitles, input
placeholders.

Nothing else sees this. The doubled-escape guard is looking for a backslash
and there is no backslash to find, which is the whole shape of the miss: a
guard written for one escape class is blind to its siblings. The key exists,
the value is translated, the file parses, `npm run build` is green.

The rule is deliberately conservative. It fires only when the English value
carries an escape and the translated value contains **no backslash at all**.
A translation that restructures a sentence and ends up with a different
number of breaks still passes, because arguing about how many paragraphs a
language needs is not this script's business. Losing every one of them is not
a translation decision.

Left unwired from CI until the 24 known values are repaired; wire it into the
`Repo hygiene` workflow in the same commit that makes it green, never before,
because a gate that is red on arrival teaches people to skip it.

Usage:
    python scripts/check_locale_lost_escapes.py

Exit code 0 means no value lost its escapes. Exit code 1 names every offending
file, line and key, with the English original beside it.
"""

from __future__ import annotations

import glob
import os
import re
import sys

LOCALE_GLOB = "frontend/src/app/locales/*.ts"
REFERENCE = "en"

_KEY_LINE = re.compile(r'^\s*"([a-zA-Z0-9_.\-]+)":\s*"(.*)",?\s*$')

# A single backslash followed by n or t. Written from chr(92) rather than as a
# literal so the pattern survives being pasted through a shell, which is how
# the first version of this scan lost its own backslashes and briefly reported
# nothing at all.
_BACKSLASH = chr(92)
_REAL_ESCAPE = re.compile(re.escape(_BACKSLASH) + r"[nt]")


def _entries(path: str) -> list[tuple[int, str, str]]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            match = _KEY_LINE.match(line)
            if match:
                rows.append((lineno, match.group(1), match.group(2)))
    return rows


def main() -> int:
    paths = sorted(glob.glob(LOCALE_GLOB))
    if not paths:
        print(f"ERROR: no files matched {LOCALE_GLOB!r}", file=sys.stderr)
        return 1

    reference_path = next((p for p in paths if os.path.basename(p) == f"{REFERENCE}.ts"), None)
    if reference_path is None:
        print(f"ERROR: reference locale {REFERENCE}.ts not found", file=sys.stderr)
        return 1

    english = {key: value for _, key, value in _entries(reference_path)}
    escaped_keys = {key for key, value in english.items() if _REAL_ESCAPE.search(value)}

    hits: list[tuple[str, int, str, str]] = []
    for path in paths:
        if path == reference_path:
            continue
        for lineno, key, value in _entries(path):
            if key in escaped_keys and _BACKSLASH not in value:
                hits.append((path, lineno, key, english[key]))

    if hits:
        print(f"ERROR: {len(hits)} value(s) lost every escape backslash:", file=sys.stderr)
        for path, lineno, key, original in hits:
            print(f"  {path}:{lineno}: {key}", file=sys.stderr)
            print(f"      en: {original[:120]}", file=sys.stderr)
        print(
            f"\nThe English value carries a {_BACKSLASH}n or {_BACKSLASH}t and the translation "
            "carries no backslash at all, so the escape body is rendering as an "
            "ordinary letter in the middle of a sentence. Restore the escape with "
            "ONE backslash. Two is the opposite corruption and check_locale_escapes.py "
            "will fail on it. In a Latin-script language read the sentence before "
            "editing: n and t are real letters there, and a find-and-replace on the "
            "letter is how this class of damage is made in the first place.",
            file=sys.stderr,
        )
        return 1

    print(f"locale lost-escape OK: {len(escaped_keys)} escaped key(s), {len(paths) - 1} locales, none stripped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
