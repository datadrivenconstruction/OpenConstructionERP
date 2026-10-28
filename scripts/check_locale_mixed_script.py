#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Locale homoglyph guard: block Cyrillic and Latin letters inside one word.

A translation value may freely contain both scripts - "Excel файл" is two
words in two scripts and is correct. What is never correct is one *word*
built from both, because the only ways to produce one are a homoglyph
substitution or a fragment of another language left behind by a partial
edit. Both render as something a reader in that language cannot search for,
sort, or in some cases even tell apart from the correct form.

Measured 2026-08-04 across all 29 locale files, 75 words in 14 locales, two
distinct shapes:

  - A Latin letter standing in for its Cyrillic twin in a Cyrillic-script
    locale. bg `sheets.is_current_no` read "Заменен" plus U+0061 LATIN SMALL
    LETTER A where Bulgarian needs U+0430. On screen the two are the same
    glyph, so no amount of reading the page finds it.
  - Cyrillic sitting inside a Latin-script word. da carried "ændringsordrе"
    with a Cyrillic е in seven keys, and "alvorlighedsvarmeкарта", which
    ends in the Russian word for map inside a Danish compound.

Nothing else we run can see this class. `check_locale_escapes.py` reads byte
forms of escapes, `check_i18n_leak_baseline.py` compares a value against
en.ts and these values differ from English, `check_i18n_orphan_keys.py` asks
whether a key has a locale behind it and every one of these keys does. The
string is present, translated, correctly quoted and wrong.

One pattern is legitimate and is excluded by shape rather than by name: in
an agglutinative Cyrillic-script language a Latin acronym or filename takes
a native suffix directly, so ky writes "RFIге", "BOQдон", "Excelден" and
"dwgга". That is correct orthography and there are 241 of them in ky alone,
which is why the exclusion has to be a rule and cannot be a list. It is
deliberately narrow: the word must be one Latin run, then at most one
underscore or hyphen, then one Cyrillic run, in that order, in a
Cyrillic-script locale. The joining character admits the localised U-value,
`u_стойност` in bg and `u_маанси` in ky, which are the ordinary spellings of
a building-physics term rather than a machine identifier somebody translated
by mistake. A Cyrillic run followed by a Latin one is not covered, because
that is what "Нachtrag" and "болon" and "тамpon" look like, and those are
defects.

Only Cyrillic against Latin is measured. Greek, Armenian and Georgian
homoglyphs are not in any locale we ship today and are not scanned, so a
clean run says nothing about them.

Usage:
    python scripts/check_locale_mixed_script.py

Exit code 0 means no word mixes the two scripts. Exit code 1 names every
offending file, line, key and word.
"""

from __future__ import annotations

import glob
import re
import sys
import unicodedata

LOCALE_GLOB = "frontend/src/app/locales/*.ts"

# The locales written in Cyrillic. Only these get the acronym-plus-suffix
# exclusion, because only in these is a Latin run followed by a Cyrillic one
# the normal way to inflect a borrowed token. In a Latin-script locale the
# same shape is a defect, which is what "kreslите" and "verkorт" are.
_CYRILLIC_LOCALES = frozenset({"bg", "ky", "mn", "ru"})

_KEY_LINE = re.compile(r'^\s*"([a-zA-Z0-9_.\-]+)":\s*"(.*)",?\s*$')

# Interpolation braces and escape sequences are stripped before splitting into
# words. Without this the backslash in `\n` splits as a non-word character and
# glues a bare `n` onto the Cyrillic word after it, which reads as a Latin
# letter inside a Cyrillic word and is the single largest source of false
# positives in this scan - 600-odd of them on the first pass.
_INTERPOLATION = re.compile(r"\{\{[^}]*\}\}")
_ESCAPE = re.compile(r"\\[ntru]")

# One Latin run then one Cyrillic run, nothing else: RFIге, Excelден, dwgга.
# An underscore or hyphen may join the two. That admits the localised form of a
# symbol from building physics: en.ts offers `u_value` as an example row in a
# paste placeholder, and the U-value is a real term with a real translation in
# each language rather than a machine identifier that must stay put. de writes
# `u_wert`, which is the standard German spelling; bg writes `u_стойност` and
# ky `u_маанси`, which are likewise the normal spellings in those languages,
# while fr, es and ru leave `u_value` in English. All five are defensible and
# none is a homoglyph. The shape stays tight on purpose: one Latin run, at most
# one joining character, one Cyrillic run, in that order. `тамpon` is Cyrillic
# then Latin and is still caught, which is what this scan is for.
_LATIN_THEN_CYRILLIC = re.compile(r"^[A-Za-z0-9]+[_\-]?[Ѐ-ӿ]+$")


def _script_of(char: str) -> str:
    name = unicodedata.name(char, "")
    if "CYRILLIC" in name:
        return "C"
    if "LATIN" in name:
        return "L"
    return ""


def _mixed_words(value: str, locale: str) -> list[str]:
    text = _ESCAPE.sub(" ", _INTERPOLATION.sub(" ", value))
    found = []
    for word in re.split(r"[^\w]+", text, flags=re.UNICODE):
        scripts = {_script_of(c) for c in word if c.isalpha()}
        if not {"C", "L"} <= scripts:
            continue
        if locale in _CYRILLIC_LOCALES and _LATIN_THEN_CYRILLIC.match(word):
            continue
        found.append(word)
    return found


def _describe(word: str) -> str:
    """Name every character, so a homoglyph can be told from its twin."""
    return " ".join(f"U+{ord(c):04X}({_script_of(c) or '-'})" for c in word)


def main() -> int:
    paths = sorted(glob.glob(LOCALE_GLOB))
    if not paths:
        print(f"ERROR: no files matched {LOCALE_GLOB!r}", file=sys.stderr)
        return 1

    hits: list[tuple[str, int, str, str]] = []
    for path in paths:
        locale = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][: -len(".ts")]
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                match = _KEY_LINE.match(line)
                if not match:
                    continue
                key, value = match.group(1), match.group(2)
                for word in _mixed_words(value, locale):
                    hits.append((path, lineno, key, word))

    if hits:
        print(
            f"ERROR: {len(hits)} word(s) mix Cyrillic and Latin letters:",
            file=sys.stderr,
        )
        for path, lineno, key, word in hits:
            print(f"  {path}:{lineno}: {key}", file=sys.stderr)
            print(f"      {word}", file=sys.stderr)
            print(f"      {_describe(word)}", file=sys.stderr)
        print(
            "\nOne word cannot be in two alphabets. Either a letter was replaced "
            "by its twin from the other script, which renders identically and is "
            "invisible to every other check we run, or a fragment of another "
            "language survived a partial edit. Fix the character, not the "
            "sentence. If a genuinely new legitimate shape appears, widen the "
            "rule in this file with the reasoning written down - do not add the "
            "key to a list, because the one exclusion here covers 241 correct "
            "words in ky and a list could never have held them.",
            file=sys.stderr,
        )
        return 1

    print(f"locale mixed-script OK: {len(paths)} files, no word mixes Cyrillic and Latin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
