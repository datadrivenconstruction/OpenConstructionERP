#!/usr/bin/env python3
"""Locale umlaut guard: block a word from being spelled two ways in one file.

German writes an umlaut either as the letter itself or, where the letter is
unavailable, as the ASCII digraph that stands in for it: `ue` for u-umlaut,
`oe`, `ae`, and `ss` for the sz-ligature. Both spellings are readable, so a
locale file can drift into carrying both and nothing complains: `fuer` sat in
`de.ts` four times beside 1761 spellings of the same word with the umlaut.

The damaging half is what happens when someone notices and fixes it with a
find/replace. The digraph is not a marker, it is two ordinary letters, and it
occurs inside perfectly normal German words that were never folded at all -
Steuer, Quelle, neue, bauen, zuerst, aktuell, manuell, Mauerwerk, Feuer,
dauerhaft, genau, grau, trauen, Konto+einstellungen. A mechanical pass eats
those too and leaves behind non-words: Steur, Qulle, neu, baun, zurst, aktull
(each with an umlaut where the vowels were). 91 such occurrences shipped in
the German UI, and 35 more spellings of the fold kind sat beside them.

Invisible to every other gate, and to every mechanical reviewer: the key is
present, the placeholder count is unchanged, the file parses, `npm run build`
is green, and locale coverage checks count a string that is there. Only a
German reader looking at the rendered page sees that the word is not a word.

The invariant here is language-neutral and needs no dictionary: within a
single locale file, a word must not appear both with an umlaut and in its
folded spelling. Whichever side is wrong, the file disagrees with itself, and
the disagreement is what a human has to settle. Measured across all 43 locale
files plus the backend validation messages when this was written, it fired on
German alone, so it is not a source of routine noise.

Diaeresis and vowel-cluster languages are unaffected by construction: Dutch
`coordinatie` and `geupload` (with diaeresis), Finnish `tekoaly`, Swedish
`poang`, Estonian `igauks` and Turkish `masaustu` never carry the folded twin
in the same file, so the pair never forms.

`_ALLOWED_PAIRS` holds spellings that differ by a fold and are genuinely two
different words, or two accepted orthographies. Each needs a written reason.
It must never be used to silence a hit that is simply inconvenient.

Usage:
    python scripts/check_locale_umlaut_folding.py

Exit code 0 means clean (no file disagrees with itself; any allowed pair is
listed by name). Exit code 1 means a word is spelled two ways and the output
names every file, both spellings and how often each occurs.
"""

from __future__ import annotations

import collections
import glob
import re
import sys

#: Locale text this guard reads. The backend validation messages are included
#: deliberately: half the German defect that prompted this guard lived there,
#: and a check scoped to the frontend would have reported the file clean.
_LOCALE_GLOBS = (
    "frontend/src/app/locales/*.ts",
    "backend/app/core/validation/messages/*.json",
)

#: Folded spelling -> the umlaut it stands for.
_FOLDS = {"ae": "ä", "oe": "ö", "ue": "ü", "ss": "ß"}

#: Pairs that differ by a fold and are both correct. Keyed by the folded form.
_ALLOWED_PAIRS = {
    ("fi.ts", "haen"): (
        "Finnish, and the one language here where the pair forms by accident. "
        "haen is the first person singular of hakea, 'I fetch', and han with "
        "an umlaut is the pronoun 'he or she'. Two unrelated words that happen "
        "to fold onto each other."
    ),
    ("de.ts", "Masse"): (
        "Masse is mass and Masse-with-sz is dimensions. Both are real words and "
        "both are used correctly here: 'Masse pro Meter' prices a steel profile "
        "by weight, while the sz spelling is a measured size."
    ),
    ("de.ts", "Massen"): (
        "Same pair in the plural. 'in Massen' means in bulk, which is what the "
        "BCF export and the room-creation strings mean."
    ),
    ("de.ts", "Geschoss"): (
        "Storey. The sz spelling is the pre-reform and still-current Austrian "
        "orthography; the ss spelling is the German one. Both are correct, and "
        "which to prefer is an audience question, not a defect."
    ),
}

_WORD = re.compile(r"[0-9A-Za-zÀ-ɏ]+")

#: Only the value side of `"key": "value"` is prose. Keys are identifiers, and
#: folding one renames it: all 31 occurrences of `gross` in de.ts are keys
#: (payportal.gross, certified_payroll.col.gross), so a guard that read whole
#: lines would demand a rename that breaks every lookup at runtime.
_VALUE = re.compile(r'^\s*"(?:[^"\\]|\\.)*"\s*:\s*("(?:[^"\\]|\\.)*")')

#: An interpolation placeholder is an identifier too, carried inside the
#: value: `{{gross}} - {{openings}} Openings =` names the variable the code
#: passes in, and spelling it `{{groß}}` would print the raw braces. Cut out
#: before counting, like keys are.
_PLACEHOLDER = re.compile(r"\{\{[^{}]*\}\}")


def _fold(word: str) -> set[str]:
    """Every spelling of ``word`` with one umlaut written as its digraph."""
    out = set()
    for i, ch in enumerate(word):
        for digraph, umlaut in _FOLDS.items():
            if ch == umlaut:
                out.add(word[:i] + digraph + word[i + 1 :])
            elif ch == umlaut.upper() and umlaut != "ß":
                out.add(word[:i] + digraph.capitalize() + word[i + 1 :])
    return out


def _words(path: str) -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            match = _VALUE.match(line)
            if match:
                counts.update(_WORD.findall(_PLACEHOLDER.sub(" ", match.group(1))))
    return counts


def main() -> int:
    paths = sorted(path for pattern in _LOCALE_GLOBS for path in glob.glob(pattern))
    if not paths:
        print("no locale files found - has the layout changed?", file=sys.stderr)
        return 1

    disagreements: list[tuple[str, str, int, str, int]] = []
    allowed: list[tuple[str, str]] = []
    for path in paths:
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        counts = _words(path)
        for word, count in counts.items():
            for folded in _fold(word):
                if folded not in counts:
                    continue
                if (name, folded) in _ALLOWED_PAIRS:
                    allowed.append((name, folded))
                    continue
                disagreements.append((path, word, count, folded, counts[folded]))

    if disagreements:
        print(
            f"{len(disagreements)} word(s) spelled two ways inside one locale file:",
            file=sys.stderr,
        )
        for path, word, count, folded, folded_count in sorted(disagreements):
            print(
                f"  {path}: {word} ({count}x) vs {folded} ({folded_count}x)",
                file=sys.stderr,
            )
        print(
            "\nOne of the two spellings is wrong and a reader has to decide which. "
            "Do NOT fix this with a find/replace on the digraph: ue, oe, ae and ss "
            "occur inside ordinary words that were never folded (Steuer, Quelle, "
            "neue, bauen, zuerst, aktuell), and a mechanical pass turns those into "
            "non-words. Substitute whole words only, on the value side of the "
            "colon, never inside a placeholder. If the two spellings are genuinely "
            "different words, add the pair to _ALLOWED_PAIRS with a written reason.",
            file=sys.stderr,
        )
        return 1

    print(f"locale umlaut folding OK: {len(paths)} files, no file disagrees with itself")
    for name, folded in sorted(set(allowed)):
        print(f"  ALLOWED: {name}: {folded} - {_ALLOWED_PAIRS[(name, folded)]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
