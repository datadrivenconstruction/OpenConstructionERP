#!/usr/bin/env python3
"""i18n plural guard: block a counted key missing a form its language needs.

The orphan guard answers "can this key be reached at all", and says so in
its own comments: a Russian file carrying only `_other` counts as reachable
there, because "reachable" and "complete" are different questions. This
guard asks the second one.

Why it matters, and it is not theoretical. i18next resolves a counted key
through the CLDR category its language returns for that number. When the
form is absent, it does NOT quietly fall back to `_other` in the same
language - it walks the fallback chain and prints the English. So a Turkish
file holding `_other` but no `_one` shows an English sentence on a Turkish
screen for every count of one, and every other gate we own reports green:
the key is reachable, the value is not byte-identical to English, no escape
was dropped, tsc and the build never look at locale content at all.

Three things worth knowing about how it counts.

  * Categories come from the language, never from English. English has two
    and would let Arabic ship four holes and Polish two. The table below is
    generated from the same source i18next consults, `Intl.PluralRules`.
    Six languages here have a single category, `other`, and for those an
    absent `_one` is the correct answer rather than a gap.

  * A suffix is not always a plural, and this is the whole difficulty.
    `assembly.params.err_div_by_zero` is division by zero and
    `agents.pick_one` is an instruction to pick one; neither is a form of
    anything. Grouping by suffix alone cannot tell those from a real
    plural, so this guard does not try. It asks the call sites instead: a
    key is counted only where the source calls `t(key, {... count ...})`,
    which is precisely the condition under which i18next consults CLDR at
    all. Keys nothing calls with a count are left alone, and a key named
    literally with its suffix is excluded outright.

    That makes the guard deliberately narrow. A count passed through a
    spread or a variable is invisible here and such a key goes unchecked.
    A gate that misses a case is repairable; one that cries wolf on 500
    ordinary keys gets switched off, and then it catches nothing at all.

    One narrowness was not deliberate and has been removed. The option scan
    required a colon after `count`, so it saw `{ count: n }` and was blind
    to the ES6 shorthand `{ defaultValue: ..., count }`, which is neither a
    spread nor a variable and so was not the limitation named above. It hid
    exactly sixteen rows of the same class the baseline already tracks, on
    `assemblies.bulk_delete_title` and `assemblies.bulk_tag_title`, leaving
    the gate green over half of a symmetric pair while reporting the other
    half. A blind spot that splits a pair is worse than one that drops both,
    because the half it does report reads as the whole population.

  * A group is only judged where the language already answers it. A key
    absent from a locale entirely is the orphan guard's business, not this
    one, and reporting it here would fail two gates for one cause and make
    both messages less trustworthy.

Regenerating the category table, when a locale is added:

    node -e "const l=['ar','bg',...];const o={};for(const x of l)
      o[x]=new Intl.PluralRules(x).resolvedOptions().pluralCategories;
      console.log(JSON.stringify(o,null,1))"

Known debt lives in scripts/i18n_plural_baseline.json and may only shrink.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

LOCALE_GLOB = "frontend/src/app/locales/*.ts"
SOURCE_GLOB = "frontend/src/**/*.ts*"
BASELINE_PATH = "scripts/i18n_plural_baseline.json"

# Generated from Intl.PluralRules, which is what i18next asks at runtime.
# Order within a list is CLDR's and is not significant to this guard.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "ar": ("zero", "one", "two", "few", "many", "other"),
    "bg": ("one", "other"),
    "bn": ("one", "other"),
    "cs": ("one", "few", "many", "other"),
    "da": ("one", "other"),
    "de": ("one", "other"),
    "el": ("one", "other"),
    "en": ("one", "other"),
    "en-US": ("one", "other"),
    "es": ("one", "many", "other"),
    "es-CO": ("one", "many", "other"),
    "es-CL": ("one", "many", "other"),
    "es-MX": ("one", "many", "other"),
    "et": ("one", "other"),
    "fa": ("one", "other"),
    "fi": ("one", "other"),
    "fil": ("one", "other"),
    "fr": ("one", "many", "other"),
    "he": ("one", "two", "other"),
    "hi": ("one", "other"),
    "hr": ("one", "few", "other"),
    "hu": ("one", "other"),
    "id": ("other",),
    "it": ("one", "many", "other"),
    "ja": ("other",),
    "kk": ("one", "other"),
    "ko": ("other",),
    "ky": ("one", "other"),
    "mn": ("one", "other"),
    "nl": ("one", "other"),
    "no": ("one", "other"),
    "pl": ("one", "few", "many", "other"),
    "pt": ("one", "many", "other"),
    "pt-BR": ("one", "many", "other"),
    "ro": ("one", "few", "other"),
    "ru": ("one", "few", "many", "other"),
    "sv": ("one", "other"),
    "th": ("other",),
    "tr": ("one", "other"),
    # Ukrainian takes the same four categories as Russian, so a counted key
    # translated by pattern-matching against ru.ts arrives with the right
    # shape; one translated against a two-form neighbour arrives one form
    # short and i18next answers it in English, because it does not fall back
    # from a missing plural form to another form of the same language.
    "uk": ("one", "few", "many", "other"),
    "ur": ("one", "other"),
    "uz": ("one", "other"),
    "vi": ("other",),
    "zh": ("other",),
}

_SUFFIXES = ("zero", "one", "two", "few", "many", "other")
_KEY_LINE = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)"\s*:', re.MULTILINE)
_ANY_T_KEY = re.compile(r"""\bt\(\s*(['"])([A-Za-z0-9_][A-Za-z0-9_.\-]*)\1""")
_CALL_HEAD = re.compile(r"""\bt\(\s*(['"])([A-Za-z0-9_][A-Za-z0-9_.\-]*)\1\s*,\s*\{""")
#: `count` as an options key, in both spellings JavaScript allows: `count: n`
#: and the ES6 shorthand `count` closed by a comma or the options brace. The
#: left guard keeps `itemCount` and `countdown` out.
_COUNT_OPTION = re.compile(r"(^|[{,\s])count\s*(?::|[,}]|$)")


def _options_body(text: str, brace_index: int) -> str | None:
    """The source between the options `{` and its matching `}`.

    Brace-matched rather than regex-matched, for the same reason the orphan
    guard does it: a defaultValue is often a template literal and `[^}]*`
    stops at the first `}` of an interpolation.
    """
    depth = 0
    for i in range(brace_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index + 1 : i]
    return None


def _read_locales() -> dict[str, set[str]]:
    by_locale: dict[str, set[str]] = {}
    for path in sorted(glob.glob(LOCALE_GLOB)):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in {"index", "types"}:
            continue
        with open(path, encoding="utf-8") as fh:
            by_locale[stem] = set(_KEY_LINE.findall(fh.read()))
    return by_locale


def _call_sites() -> tuple[set[str], set[str]]:
    """``(keys named literally, keys called with a count)``.

    The second set is the one that matters: it is exactly the population
    where i18next consults CLDR, so it is exactly the population where a
    missing form prints English.
    """
    literal: set[str] = set()
    counted: set[str] = set()
    for path in glob.glob(SOURCE_GLOB, recursive=True):
        posix = path.replace(os.sep, "/")
        if "/app/locales/" in posix:
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if "t(" not in text:
            continue
        for match in _ANY_T_KEY.finditer(text):
            literal.add(match.group(2))
        if "count" not in text:
            continue
        for match in _CALL_HEAD.finditer(text):
            body = _options_body(text, match.end() - 1)
            if body is not None and _COUNT_OPTION.search(body):
                counted.add(match.group(2))
    return literal, counted


def _split(key: str) -> tuple[str, str] | None:
    for suffix in _SUFFIXES:
        tail = "_" + suffix
        if key.endswith(tail) and len(key) > len(tail):
            return key[: -len(tail)], suffix
    return None


def main() -> int:
    by_locale = _read_locales()
    if not by_locale:
        print(f"ERROR: no locale files under {LOCALE_GLOB!r}.", file=sys.stderr)
        return 2

    unknown = sorted(set(by_locale) - set(CATEGORIES))
    if unknown:
        print(
            f"ERROR: locale file(s) {', '.join(unknown)} have no entry in CATEGORIES. "
            "A new locale must be added to the table in this file before it can be "
            "checked; see the regeneration snippet in the docstring.",
            file=sys.stderr,
        )
        return 2

    named_literally, counted_keys = _call_sites()
    if not counted_keys:
        print(
            f"ERROR: found no t(key, {{count}}) call sites under {SOURCE_GLOB!r}. "
            "Either the call shape changed or this ran from the wrong directory; "
            "either way a pass here would mean nothing.",
            file=sys.stderr,
        )
        return 2

    try:
        with open(BASELINE_PATH, encoding="utf-8") as fh:
            baseline = set(json.load(fh))
    except FileNotFoundError:
        baseline = set()

    findings: list[str] = []
    for locale in sorted(by_locale):
        wanted = set(CATEGORIES[locale])
        keys = by_locale[locale]
        groups: dict[str, set[str]] = {}
        for key in keys:
            parts = _split(key)
            if parts is None:
                continue
            base, suffix = parts
            # Named literally at a call site, so the suffix belongs to the
            # name rather than to a plural of `base`.
            if key in named_literally:
                continue
            # Only a key some call site passes a count to is resolved
            # through CLDR. Everything else that merely ends in a category
            # word is an ordinary key with an unlucky name.
            if base not in counted_keys:
                continue
            groups.setdefault(base, set()).add(suffix)
        for base, have in sorted(groups.items()):
            missing = wanted - have
            if not missing:
                continue
            findings.append(f"{locale}:{base}")
            if f"{locale}:{base}" in baseline:
                continue
            print(
                f"ERROR: {base} in {locale} has {', '.join(sorted(have))} but "
                f"{locale} needs {', '.join(sorted(wanted))} - missing "
                f"{', '.join(sorted(missing))}"
            )

    new = sorted(set(findings) - baseline)
    gone = sorted(baseline - set(findings))
    if gone:
        print(f"\n{len(gone)} baselined plural hole(s) fixed; remove them from {BASELINE_PATH}.")
    if new:
        print(
            f"\n{len(new)} counted key(s) are missing a form their language needs. "
            "i18next does not fall back to _other inside a language: it walks the "
            "fallback chain and prints English, so the screen shows an English "
            "sentence for those counts and no other gate can see it. Add the form, "
            "grounded in that language's own CLDR categories rather than English's."
        )
        return 1

    print(f"i18n plural forms OK: {len(by_locale)} locales, {len(findings)} baselined hole(s) still open, no new ones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
