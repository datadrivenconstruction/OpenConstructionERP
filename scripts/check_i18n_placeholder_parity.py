#!/usr/bin/env python3
"""i18n placeholder guard: block a translation that renamed a variable.

i18next substitutes by name. `t('boq.outline_count', { count: 12 })` fills
`{{count}}` and nothing else, so a locale whose value says `{{Pays}}` renders
the braces to the user, verbatim, forever. Nothing else we own can see it. The
key is present, so the orphan guard is happy. Both plural forms are present, so
the plural guard is happy. The value is not byte-identical to English, so the
leak baseline is happy. No escape was doubled. tsc and the build never read
locale content at all, and a string literal cannot fail to compile.

This is not hypothetical and it is not rare. Two ways it has happened here:

  * A spell-normalising pass walked the file and rewrote American spellings to
    British ones. It could not tell prose from a variable name, so `{{labor}}`
    became `{{labour}}` and `{{catalog}}` became `{{catalogue}}` in all
    forty-two translations and in `en.ts`. `en-US.ts` was the only file left
    holding the name the call site actually passes, which made the majority
    look correct and the single correct file look like the outlier.

  * A glossary pass replaced words with their translations and reached inside
    the braces, turning `{{count}}` into `{{Pays}}` across thirty-seven strings
    in one language, plural forms among them. A counted key with no `count` in
    it does not fall back to a sensible form, it has no number to switch on.

Both were mechanical, both were invisible to every other gate, and in both the
damage was proportional to how carefully the pass had been run everywhere.

What this checks, and deliberately no more. For each key, a locale may not ask
for a variable the source does not have. Not the order, which translation is
free to change, and not the formatter suffix in `{{value, currency}}`, which is
a rendering choice a locale may legitimately differ on. Only whether the string
demands something the call site was never written to pass.

The two directions are not the same defect and this guard treats them
differently, which is the whole of its accuracy.

  * A name the source does not have is unresolvable. There is no value to put
    there, so the reader gets braces. That is always broken and it blocks.

  * A name the source has and the locale omits still renders correctly; the
    string simply does not show that value. Sometimes it is a real loss and
    sometimes it is the right translation: in a language whose `_one` form
    means exactly one, Arabic among them, writing the word for "one" instead
    of `{{count}}` is better prose than the source has. A guard that failed on
    those would be wrong twice out of three times, measured on this tree, and a
    guard that is usually wrong gets switched off. So omissions are counted and
    printed on a passing run, where a person can look at them, and they do not
    fail the build.

Keys absent from the source are skipped: the source is what the call sites are
written against, and a key that exists only in a translation is the orphan
guard's business. Reporting it here would fail two gates for one cause.

There is no baseline file. There is nothing to grandfather: the parity holds
across every locale today, and a debt list here would be a place for exactly
the defect this guard exists to catch to sit and look approved.
"""

from __future__ import annotations

import glob
import os
import re
import sys

LOCALE_GLOB = "frontend/src/app/locales/*.ts"

# `en`, not `en-US`. i18n.ts registers `resources: { en: enResource }` with
# `fallbackLng: 'en'`, so `en.ts` is what every unresolved key falls back to and
# what the call sites are written against. `en-US.ts` is an override layer
# holding only the words that differ in American spelling, about 1580 of the
# 35255, and pointing this guard at it silently reduced its reach to those and
# reported the result as a clean run over everything.
SOURCE = "en"

# The value is always a plain double-quoted literal on one line in these files.
# An escaped quote inside a key has never occurred and would be a separate bug.
_KEY_LINE = re.compile(r'^\s*"([^"]+)"\s*:')
_PLACEHOLDER = re.compile(r"[{][{]([^}]+)[}][}]")

# JavaScript template syntax. i18next never evaluates it, so every one of these
# characters reaches the reader. It gets into a locale exactly one way: a call
# site writes `defaultValue: \`${n} items\``, which is correct JavaScript and
# correct in the code, and whoever seeds the locale files copies that source
# text instead of the string it evaluates to. That happened here to
# `boq.autocomplete_tooltip_variants_available` in 41 languages at once, and the
# one translator who noticed replaced it with i18next syntax but guessed the
# variable name, so the language that spotted the bug was broken too.
_TEMPLATE_LITERAL = re.compile(r"[\$][{]")

# A file that parses to fewer keys than this is not a locale we understand, and
# every comparison below would then be a loop over nothing that reports success.
# Full locales carry around 38000. `en-US.ts` is a spelling override and carries
# about 1580, so the floor sits below that rather than at a full file's size.
_MIN_KEYS = 900

# Overlays that legitimately parse to far fewer keys than a locale. Named here
# rather than accommodated by lowering the floor above, which would retire the
# guard for every file to let two through. Each carries only the words its
# region spells differently and inherits the rest, so a small key count is a
# fact about the file and not evidence of a broken reader: `en-GB.ts` is 9 keys
# and `en-US.ts` about 1580. The parity comparison still runs over every key
# they do carry; only the floor is waived, and it is replaced by a floor of one
# rather than by nothing, so a reader that breaks on these files still says so
# instead of reporting a green loop over an empty dictionary.
_OVERLAYS = frozenset({"en-GB", "en-US"})


def _names(value: str) -> set[str]:
    """Variable names only: `{{count}}` and `{{count, number}}` are one slot."""
    return {raw.split(",")[0].strip() for raw in _PLACEHOLDER.findall(value)}


def _parse(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            match = _KEY_LINE.match(line)
            if not match:
                continue
            rest = line[match.end() :].strip()
            if not rest.startswith('"'):
                continue  # nested object or a non-string value, not our business
            body = rest[1:]
            if body.endswith(","):
                body = body[:-1]
            if body.endswith('"'):
                body = body[:-1]
            values[match.group(1)] = body
    return values


def main() -> int:
    paths = sorted(glob.glob(LOCALE_GLOB))
    if not paths:
        print(f"ERROR: no files matched {LOCALE_GLOB!r}", file=sys.stderr)
        return 1

    source_path = os.path.join(os.path.dirname(paths[0]), f"{SOURCE}.ts")
    if source_path not in paths:
        print(f"ERROR: source locale {source_path!r} is missing", file=sys.stderr)
        return 1

    source = _parse(source_path)
    if len(source) < _MIN_KEYS:
        print(
            f"ERROR: {source_path} parsed to {len(source)} keys, which is too few "
            f"to be the real file. Every check below would pass vacuously, so this "
            f"is a failure rather than a green run.",
            file=sys.stderr,
        )
        return 1

    counted = sum(1 for value in source.values() if _names(value))
    failures: list[tuple[str, str, str, str]] = []
    omissions: list[tuple[str, str, list[str]]] = []
    templated: list[tuple[str, str, str]] = []
    checked = 0

    for path in paths:
        code = os.path.basename(path)[:-3]
        locale = source if code == SOURCE else _parse(path)

        # Checked in every file, the source included: the source is where this
        # particular mistake starts, and skipping it would leave the origin of
        # the defect as the one place the guard cannot see.
        for key, value in locale.items():
            if _TEMPLATE_LITERAL.search(value):
                templated.append((path, key, value))

        if code == SOURCE:
            continue
        floor = 1 if code in _OVERLAYS else _MIN_KEYS
        if len(locale) < floor:
            print(
                f"ERROR: {path} parsed to {len(locale)} keys. Either the file shape "
                f"changed or this reader is broken; both mean the parity check did "
                f"not happen.",
                file=sys.stderr,
            )
            return 1
        for key, value in locale.items():
            if key not in source:
                continue  # orphan guard's territory
            checked += 1
            want, got = _names(source[key]), _names(value)
            if got - want:
                failures.append((path, key, source[key], value))
            elif want - got:
                omissions.append((path, key, sorted(want - got)))

    if templated:
        print(
            f"ERROR: {len(templated)} locale value(s) contain JavaScript template "
            f"syntax, which i18next never evaluates. Every one of these characters "
            f"reaches the reader:",
            file=sys.stderr,
        )
        for path, key, value in templated:
            print(f"  {path}: {key}", file=sys.stderr)
            print(f"      {value}", file=sys.stderr)
        print(
            "\nRead the call site, find the name it actually passes, and write that "
            "as {{name}}. Do not copy the text of a `defaultValue` template literal "
            "into a locale: it is correct where it is, because JavaScript evaluates "
            "it there, and it is dead text here.",
            file=sys.stderr,
        )
        return 1

    if failures:
        print(
            f"ERROR: {len(failures)} value(s) ask for a variable the call site does not pass:",
            file=sys.stderr,
        )
        for path, key, want, got in failures:
            print(f"  {path}: {key}", file=sys.stderr)
            print(f"      {SOURCE}: {want}", file=sys.stderr)
            print(f"      here:  {got}", file=sys.stderr)
        print(
            "\nFix the variable name in the translation, never the call site and "
            "never the source locale, unless you have read the call site and it is "
            "the one that is wrong. The visible words around the braces are yours "
            "to translate; the text inside them is code and has to match exactly. "
            "If a translation genuinely does not need a variable the source passes, "
            "that is a product question about the string, not something to silence "
            "here.",
            file=sys.stderr,
        )
        return 1

    print(
        f"i18n placeholder parity OK: {len(paths)} files, {checked} values compared "
        f"against {SOURCE}, {counted} source strings carry a placeholder"
    )
    if omissions:
        print(
            f"  {len(omissions)} translation(s) drop a placeholder the source passes. "
            f"These render, so they do not fail the build, but each is either good "
            f"prose or a lost value and only a reader of that language can tell which:"
        )
        for path, key, lost in omissions:
            print(f"    {path}: {key} does not use {', '.join(lost)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
