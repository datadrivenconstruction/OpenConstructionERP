#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Locale escape guard: block doubled single-character escapes in translations.

A TypeScript string literal escapes a Unicode code point as a single
backslash followed by `u` and four hex digits, e.g. `"\\u2013"` in the source
file decodes to an en dash at runtime, and the same single-backslash rule
applies to `\\n`, `\\t` and `\\r`. If a translation pass (script, find/replace,
or an LLM re-emitting escaped text) doubles that leading backslash, the
source ends up with two literal backslashes before the escape body.
TypeScript then parses the first backslash pair as an escaped backslash and
leaves the rest as literal characters, so the string renders on screen as
garbage - `–` instead of an en dash, or a literal backslash-n instead of a
line break.

This is invisible to every other gate: it is a syntactically valid string, the
key is present, `tsc` and `npm run build` stay green, and key-count / missing-
key checks stay silent. Only a human looking at the rendered page catches it.
Originally written for `\\u` only, after 4 keys / 78 values across 28 locale
files were found doubled (fixed in a023d1e42 and c452e3ecd). The same bug in
`\n`/`\t`/`\r` stayed invisible to this guard until a full scan found 216 more
cells across 26 locales (fixed in 09ae5c27d and a22535fbf); the regex now
covers all four escape bodies so the next occurrence fails the commit instead
of waiting for another sweep.

`ai.paste_placeholder` was the one entry in `_KEY_EXCEPTIONS`, held open on
the question of whether its doubled `\\t` was a defect or a deliberate way of
showing an escape sequence as documentation. Settled 2026-08-04 from evidence
inside the string rather than by a ruling: the same value carries a *single*
backslash on `\n`. Doubling only the escape that draws the columns, and only
in 19 of 29 files, is not a documentation choice, and the inline
`defaultValue` the key falls back to (`QuickEstimatePage.tsx`) writes single
backslashes throughout. The textarea renders in a monospace font, which is
worth nothing unless the tabs are real. All 19 were collapsed to one
backslash and the exception was removed.

`_KEY_EXCEPTIONS` is kept, empty, for keys with a written, dated reason they
cannot be resolved by this guard alone. It must never be used to silence an
unexplained or merely-inconvenient hit, and an entry that has sat there long
enough to feel permanent is a question nobody answered, not a rule.

Usage:
    python scripts/check_locale_escapes.py

Exit code 0 means clean (no unexplained doubled escapes; any excepted key is
listed by name). Exit code 1 means an unexcepted doubled escape was found and
the output names every offending file, line and match.
"""

from __future__ import annotations

import glob
import re
import sys

# Two literal backslashes followed by an escape body: `n`, `t`, `r`, or a
# four-hex-digit Unicode body. A correctly encoded value has exactly one
# backslash here; a doubled one is always the corruption, never an
# intentional value - locale strings are prose, not code, and never need to
# describe a literal backslash followed by one of these escape bodies.
_DOUBLED_ESCAPE = re.compile(r"\\\\[ntr]|\\\\u[0-9a-fA-F]{4}")

# Matches a single `"key": "value"` line, same shape every locale file uses
# one entry per line for. Lets a hit be attributed to its JSON/TS key so
# _KEY_EXCEPTIONS can name an exact key rather than a file or a line number.
_KEY_LINE = re.compile(r'^\s*"([a-zA-Z0-9_.\-]+)":\s*"')

LOCALE_GLOB = "frontend/src/app/locales/*.ts"

# Named, single-key exceptions with a written reason each. Enumerated by key,
# not a numeric tolerance - a count-based allowance would hide how many and
# which keys it covers; naming the key here means the exception is exactly
# as wide as the sentence explaining it, no wider.
_KEY_EXCEPTIONS: dict[str, str] = {}


def _scan(
    paths: list[str],
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """Return (unexcepted_hits, excepted_hits), both as (path, lineno, key)."""
    unexcepted: list[tuple[str, int, str]] = []
    excepted: list[tuple[str, int, str]] = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                if not _DOUBLED_ESCAPE.search(line):
                    continue
                key_match = _KEY_LINE.match(line)
                key = key_match.group(1) if key_match else None
                bucket = excepted if key in _KEY_EXCEPTIONS else unexcepted
                bucket.append((path, lineno, key or "<unattributed line>"))
    return unexcepted, excepted


def main() -> int:
    paths = sorted(glob.glob(LOCALE_GLOB))
    if not paths:
        print(f"ERROR: no files matched {LOCALE_GLOB!r}", file=sys.stderr)
        return 1

    unexcepted, excepted = _scan(paths)
    if unexcepted:
        print(
            f"ERROR: doubled escape found in {len(unexcepted)} place(s):",
            file=sys.stderr,
        )
        for path, lineno, key in unexcepted:
            print(f"  {path}:{lineno}: {key}", file=sys.stderr)
        print(
            "\nA doubled backslash before \\n, \\t, \\r or a \\uXXXX escape renders "
            "as literal garbage instead of the intended character or whitespace. "
            "Fix the escaping only (one backslash, not two) - do not change which "
            "character it decodes to. If this is a new, deliberately unresolved "
            "case like ai.paste_placeholder, add it to _KEY_EXCEPTIONS by name "
            "with a written reason - do not silence it any other way.",
            file=sys.stderr,
        )
        return 1

    print(f"locale escapes OK: {len(paths)} files, no unexplained doubled escapes")
    if excepted:
        by_key: dict[str, list[str]] = {}
        for path, _lineno, key in excepted:
            by_key.setdefault(key, []).append(path)
        for key, key_paths in sorted(by_key.items()):
            print(f"  EXCEPTED: {key} ({len(key_paths)} file(s)) - {_KEY_EXCEPTIONS[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
