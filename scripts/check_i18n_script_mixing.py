#!/usr/bin/env python3
"""i18n script guard: block a locale value written in someone else's alphabet.

Found 10.08.2026 on the live site. `th/cases/build-an-all-in-labour-rate`
served the Korean title 종합 노무 단가 산정 under Thai chrome, because 42 of
the 197 `cases.*` slugs in `th.ts` hold Korean values - 1031 keys copied
whole out of `ko.ts`. Nine other locales carry the smaller shape of the
same defect: one wrong-language word inside an otherwise correct sentence,
`Режим на群добавяне` in Bulgarian, `キャッシュフロー데이터` in Japanese,
`Жалпы בפועל` in Kyrgyz, `Onge番号` in Dutch, `Включения` in Polish.

Nothing we own could see it. The orphan guard asks whether a key is
reachable and these are. The plural guard asks whether a counted key has
its forms and these do. `tsc` and the build never read locale content.
Byte-comparison against English passes trivially, because Korean is not
English either. The string is present, well-formed, correctly escaped, and
in the wrong language, and only a human who reads Thai would notice.

So this guard asks the one question the others cannot: is the value
written in a script this language actually uses.

Three things worth knowing about how it counts.

  * Latin is allowed everywhere and is never flagged. Product names, units,
    file extensions and standard codes (`.xlsx`, `C30/37`, `DIN 276`, `BIM`)
    are Latin in every locale we ship. The consequence is that this guard
    cannot see French sitting in `de.ts` - both are Latin - and it is not
    trying to. It catches alphabet mismatches, not translation quality.

  * Some foreign script is in the source string itself, not in the
    translation. `dwg_compare.col_delta` is the character Δ in all 37
    locales; `match_elements.new_excel.hint` deliberately lists the column
    name in several languages so a user can recognise theirs. Flagging
    those would mean 8787 findings, and a guard that reports 8787 things
    gets switched off. So a (key, script) pair carried by SHARED_AT_LEAST
    locales is treated as coming from the source string. That is a real
    hole: the same bad value pasted into enough locales would hide inside
    it. It is the price of the guard existing at all, and the threshold is
    deliberately far above the 1-to-7 locales every genuine finding hit.

  * Two characters live in one script's Unicode block and are ordinary
    punctuation in another's writing, so they are excluded outright rather
    than counted. The danda U+0964 sits in the Devanagari block and ends a
    Bengali sentence too - counting it reported 7282 phantom findings in
    `bn.ts`, more than the real Thai defect, from a locale that is entirely
    correct. The katakana middle dot U+30FB separates items in Korean and
    Chinese as well as Japanese.

Adding a locale means adding its row to SCRIPTS below. An unknown locale
file is an error rather than a pass, because silence about a language
nobody checked is what let this defect live.

Known debt lives in scripts/i18n_script_baseline.json and may only shrink.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

LOCALE_GLOB = "frontend/src/app/locales/*.ts"
BASELINE_PATH = "scripts/i18n_script_baseline.json"

# A (key, script) pair this many locales share came from the source string
# rather than from any one translation. See the docstring.
SHARED_AT_LEAST = 8

# Ranges are exclusive of the punctuation that other scripts borrow, so the
# borrowed characters never have to be special-cased at the call site.
#   U+0964/U+0965 danda and double danda: Devanagari block, used by Bengali.
#   U+30FB katakana middle dot: kana block, used by Korean and Chinese.
BLOCKS: dict[str, str] = {
    "cyrillic": r"Ѐ-ӿ",
    "greek": r"Ͱ-Ͽ",
    "hebrew": r"֐-׿",
    "arabic": r"؀-ۿݐ-ݿ",
    "devanagari": r"ऀ-ॣ०-ॿ",
    "bengali": r"ঀ-৿",
    "thai": r"฀-๿",
    "hangul": r"가-힯ᄀ-ᇿ",
    "kana": r"぀-ヺー-ヿ",
    "han": r"一-鿿",
}
PATTERNS = {name: re.compile("[" + rng + "]") for name, rng in BLOCKS.items()}

# What each locale writes in, beyond Latin. An empty tuple means Latin only.
SCRIPTS: dict[str, tuple[str, ...]] = {
    "ar": ("arabic",),
    "bg": ("cyrillic",),
    "bn": ("bengali",),
    "cs": (),
    "da": (),
    "de": (),
    "el": ("greek",),
    "en": (),
    "en-US": (),
    "es": (),
    "es-CO": (),
    "es-CL": (),
    "es-MX": (),
    "et": (),
    "fa": ("arabic",),
    "fi": (),
    "fil": (),
    "fr": (),
    "he": ("hebrew",),
    "hi": ("devanagari",),
    "hr": (),
    "hu": (),
    "id": (),
    "it": (),
    "ja": ("kana", "han"),
    "kk": ("cyrillic",),
    "ko": ("hangul", "han"),
    "ky": ("cyrillic",),
    "mn": ("cyrillic",),
    "nl": (),
    "no": (),
    "pl": (),
    "pt": (),
    "pt-BR": (),
    "ro": (),
    "ru": ("cyrillic",),
    "sv": (),
    "th": ("thai",),
    "tr": (),
    "uk": ("cyrillic",),
    # Uzbek writes in Latin. The Cyrillic orthography still exists in print but
    # the official alphabet has been Latin since 1993, and the construction and
    # procurement documents this product is read beside use it, so a Cyrillic
    # character in uz.ts is a mistake rather than a variant.
    "uz": (),
    "ur": ("arabic",),
    "vi": (),
    "zh": ("han",),
}

# One key and its value on one line, which is how these files are written.
_ENTRY = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)"\s*:\s*"(.*)"\s*,?\s*$')
_KEY_ONLY = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)"\s*:')


def _read(path: str) -> tuple[dict[str, str], int]:
    """``(values by key, count of key lines whose value did not parse)``.

    The second number is returned rather than ignored so that a change in
    how these files are written shows up as a number in the output instead
    of as a quietly smaller scan.
    """
    values: dict[str, str] = {}
    unparsed = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            entry = _ENTRY.match(line)
            if entry is not None:
                values[entry.group(1)] = entry.group(2)
            elif _KEY_ONLY.match(line):
                unparsed += 1
    return values, unparsed


def _foreign(value: str, allowed: set[str]) -> set[str]:
    return {name for name, pat in PATTERNS.items() if name not in allowed and pat.search(value)}


def _offenders(value: str, script: str, limit: int = 6) -> str:
    """The actual characters that tripped the check, with their codepoints.

    Printed rather than left to the reader to find, because the whole shape
    of this defect is one wrong character inside a correct sentence, and
    hunting for it by eye in a right-to-left or dense-script value is how a
    real finding gets dismissed as noise.
    """
    seen: list[str] = []
    for ch in PATTERNS[script].findall(value):
        if ch not in seen:
            seen.append(ch)
        if len(seen) == limit:
            break
    return " ".join(f"{ch} U+{ord(ch):04X}" for ch in seen)


def main() -> int:
    paths = sorted(glob.glob(LOCALE_GLOB))
    locales = {os.path.splitext(os.path.basename(p))[0]: p for p in paths}
    locales = {k: v for k, v in locales.items() if k not in {"index", "types"}}
    if not locales:
        print(f"ERROR: no locale files under {LOCALE_GLOB!r}.", file=sys.stderr)
        return 2

    unknown = sorted(set(locales) - set(SCRIPTS))
    if unknown:
        print(
            f"ERROR: locale file(s) {', '.join(unknown)} have no entry in SCRIPTS. "
            "A new locale must name the script it writes in before it can be checked; "
            "an unchecked language is how the Thai defect survived.",
            file=sys.stderr,
        )
        return 2

    hits: dict[str, set[tuple[str, str]]] = {}
    samples: dict[str, dict[str, str]] = {}
    shared: dict[tuple[str, str], int] = {}
    unparsed_total = 0
    scanned = 0
    for locale, path in sorted(locales.items()):
        values, unparsed = _read(path)
        unparsed_total += unparsed
        scanned += len(values)
        allowed = set(SCRIPTS[locale])
        found = {(key, script) for key, value in values.items() for script in _foreign(value, allowed)}
        hits[locale] = found
        for pair in found:
            shared[pair] = shared.get(pair, 0) + 1
        samples[locale] = values

    if not scanned:
        print(
            f"ERROR: parsed 0 values out of {unparsed_total} key line(s). The entry "
            "shape changed, and a pass here would mean nothing.",
            file=sys.stderr,
        )
        return 2

    try:
        with open(BASELINE_PATH, encoding="utf-8") as fh:
            baseline = set(json.load(fh))
    except FileNotFoundError:
        baseline = set()

    findings: list[str] = []
    for locale in sorted(hits):
        own = sorted(pair for pair in hits[locale] if shared[pair] < SHARED_AT_LEAST)
        for key, script in own:
            ident = f"{locale}:{key}:{script}"
            findings.append(ident)
            if ident in baseline:
                continue
            chars = _offenders(samples[locale][key], script)
            print(f"ERROR: {locale} value for {key} contains {script}, which {locale} does not write in: {chars}")

    new = sorted(set(findings) - baseline)
    gone = sorted(baseline - set(findings))
    if gone:
        print(f"\n{len(gone)} baselined script mix(es) fixed; remove them from {BASELINE_PATH}.")
    if new:
        print(
            f"\n{len(new)} value(s) are written in a script their language does not use. "
            "The string is present, escaped and not English, so every other gate passes "
            "it; only a reader of that language sees it. Translate the value into the "
            "locale's own language rather than deleting the foreign characters."
        )
        return 1

    print(
        f"i18n script mixing OK: {len(locales)} locales, {scanned} values scanned, "
        f"{len(findings)} baselined mix(es) still open, no new ones."
        + (f" ({unparsed_total} key line(s) carried no single-line value.)" if unparsed_total else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
