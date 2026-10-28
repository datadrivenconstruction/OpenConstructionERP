#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠i18n nesting guard: block a locale key that is a sibling of the dictionary.

Every locale file is one object with one member:

    const resource = {
      "translation": {
        "boq.title": "Bill of quantities",
        ...
      }
    } as { translation: Record<string, string> };

`app/i18n.ts` hands i18next `resource.translation`, once per language through
`addResourceBundle(code, 'translation', resource.translation, ...)` and once
more for English through `resources: { en: enResource }`. Only the members of
that inner object are ever looked up. A key written one level higher, as a
sibling of `translation` rather than inside it, parses, type-checks, builds and
is never found.

Nothing else we own can see it, and that is the point of this guard:

  * the orphan guard reads locale files with a line regex and asks whether a
    key appears at all, not where it appears, so a sibling reads as present
  * the leak, escape and mixed-script guards ask about the value, and the
    value is a correct translation
  * `tsc` and the build are satisfied, because the file is a valid object
    literal either way, and the trailing `as` assertion is not a check
  * a screen looks normal, because every call site passes the English as
    `defaultValue`, so a failed lookup renders English rather than a raw key

That combination is the worst case. Thirty translated files, six thousand
keys, every gate green, every language showing English. It shipped that way
once already: the keys for three statutory modules went in after
`const resource = {` instead of after `"translation": {`, and the difference
is two lines of context in a file of thirty six thousand.

So the question here is only about position, and the answer is absolute rather
than baselined. There is no such thing as a legitimate sibling key, and a
baseline would only record how many were wrong on the day it was written.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "frontend" / "src" / "app" / "locales"
NOT_LOCALES = {"index.ts", "types.ts"}

OPEN_TRANSLATION = re.compile(rb'^\s*"?translation"?\s*:\s*\{')
KEY_LINE = re.compile(rb'^\s*"([^"]+)"\s*:')


def translation_span(lines: list[bytes]) -> tuple[int, int] | None:
    """Line indices of the `translation` opener and its matching close."""
    opener = next((i for i, line in enumerate(lines) if OPEN_TRANSLATION.match(line)), None)
    if opener is None:
        return None
    depth = 0
    for i in range(opener, len(lines)):
        depth += lines[i].count(b"{") - lines[i].count(b"}")
        if i > opener and depth <= 0:
            return opener, i
    return opener, len(lines) - 1


def misplaced(path: Path) -> tuple[list[tuple[int, str]], str | None]:
    """Keys outside the translation object, and why the file could not be read."""
    lines = path.read_bytes().splitlines()
    span = translation_span(lines)
    if span is None:
        return [], "no translation object"
    opener, closer = span

    out: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if opener < i < closer:
            continue
        match = KEY_LINE.match(line)
        if match and match.group(1) != b"translation":
            out.append((i + 1, match.group(1).decode("utf-8", "replace")))
    return out, None


def main() -> int:
    files = sorted(p for p in LOCALES.glob("*.ts") if p.name not in NOT_LOCALES)
    if not files:
        print(f"no locale files under {LOCALES}", file=sys.stderr)
        return 1

    total = 0
    for path in files:
        found, problem = misplaced(path)
        if problem:
            print(f"{path.name}: {problem}", file=sys.stderr)
            total += 1
            continue
        if not found:
            continue
        total += len(found)
        shown = found[:5]
        print(
            f"\n{path.name}: {len(found)} keys outside the translation object",
            file=sys.stderr,
        )
        for line_no, key in shown:
            print(f"  line {line_no}: {key}", file=sys.stderr)
        if len(found) > len(shown):
            print(f"  and {len(found) - len(shown)} more", file=sys.stderr)

    if total:
        print(
            f"\n{total} locale keys sit beside the translation object instead of inside it, "
            f"across {len(files)} files.\ni18next reads resource.translation and will never "
            "find them, so every one of these renders the English defaultValue.\nMove the block "
            'so it begins immediately after the `"translation": {` line.',
            file=sys.stderr,
        )
        return 1

    print(f"i18n nesting: {len(files)} locale files, every key inside the translation object")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
