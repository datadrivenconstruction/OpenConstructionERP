#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Locale gate: fail a locale file that is still mostly English placeholder.

The Hungarian bundle was assembled and passed every locale gate this repository
has while 30746 of its 41903 values were byte-identical to their English source.
Not partially translated: the same bytes, because `scripts/i18n_new_locale.py
extract` seeds every batch value with the English text as the translator's
starting point, and a batch nobody ever opened is indistinguishable from a
finished one. `assemble` and `verify` both check the shape of the key set -
non-empty, matches _order.json, no key in two batches - and neither of them
looks at what language a value is written in. `tsc -b` and `npm run build` were
green on the file, because English in a Hungarian bundle is valid TypeScript.

This is not a second copy of scripts/check_i18n_leak_baseline.py and must not be
folded into it. That guard runs down the key axis: for one key, how many of the
locales answer it with the English string, flagging at 24 of 28 because a leak
copies one string into every locale at once. A single locale that is 74% English
never reaches that count in any locale-set, so it is invisible there, and it has
to be, or the two lists that guard would need would have to carry 30000 keys.
This guard runs down the other axis: for one locale, how much of the whole
corpus is English. Neither axis sees what the other sees, and a consolidation
would silently drop one of them.

Population. Each value is compared against its RESOLVED English source, the same
english_sources() the extraction tool uses, not against en.ts. en.ts answers
about 36000 keys while the corpus is about 43500: English is supplied inline at
the call site as t('key', { defaultValue: 'English' }), through <Trans defaults>,
and as the English field beside a key field in the case playbooks and the module
guides. A check that knew only en.ts would quietly excuse some 7700 keys, and it
would report a clean verdict while doing it. So the numbers are printed beside
the verdict: keys in the file, keys actually compared, and keys excluded because
nothing in the tree says what their English is. A green line whose compared
column is far below its keys column is not a pass, it is a narrow question, and
POPULATION_FLOOR below turns that into a failure rather than leaving it to a
reader to notice.

English and its regional variants are the one thing this guard does not ask
about, for the reason in is_english_variant(): a value in en-US that agrees with
en.ts agrees on purpose, so the question is meaningless there rather than
merely passing. The report names the files it skipped on that ground.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from i18n_new_locale import (
    KEY_VAL_MULTILINE,
    LOCALES,
    english_sources,
    locale_paths,
    read,
    unescape,
)  # noqa: E402

# The share of a locale's values that may be byte-identical to their English
# source before the locale reads as unfinished rather than as translated.
#
# Measured on 2026-09-02 across the 42 non-English locale files in the tree, all
# of them shipped and in use. The whole finished population lies between 0.65%
# (fa, he) and 3.72% (fr); the cluster at the top is exactly what you would
# expect it to be, the languages that share the most vocabulary and the most
# proper nouns with English (fr 3.72, nl 3.56, da 3.40, id 3.12). Hungarian
# assembled from untouched batches measured 74.01%. There is no locale anywhere
# between 3.72% and 74.01%, so the line is not being drawn through a crowd.
#
# 10% sits about 2.7x above the highest finished locale, and the distance from
# fr to the threshold (6.3 points) is twice the entire spread of the finished
# population (3.07 points), so a new language with more untranslatable terms
# than any language we currently ship still has room. In the units of the defect
# it exists to catch: the corpus is around 41000 keys and extract writes batches
# of about 1000, so 10% is roughly three untouched batches above the ordinary
# baseline. Fewer than three untouched batches is not what this gate is for -
# individual leaked keys are the key-axis guard's job, described above.
THRESHOLD = 0.10

# Keys carrying a resolvable, non-blank English source, as a share of the keys
# in the locale file. This is the denominator check, and it is here because a
# denominator that quietly shrinks is how the defect above survived: a check
# that examines 300 keys of 41903 and calls them all translated prints exactly
# the same "OK" as one that examines all of them. Every locale in the tree on
# 2026-09-02 was above 99.1%, so the floor costs nothing today; what it buys is
# that a regression in english_sources() fails here instead of turning the gate
# green by giving it less to look at.
POPULATION_FLOOR = 0.95


def locale_values(path: Path) -> dict[str, str]:
    return {m.group(1): unescape(m.group(3)) for m in KEY_VAL_MULTILINE.finditer(read(path))}


def is_english_variant(code: str) -> bool:
    """Whether this bundle is English, or a regional variant of English.

    en.ts is the comparison source, so asking whether it equals itself is the
    one question this guard cannot ask. A variant is subtler and is the reason
    this is a named, tested rule rather than a bare `!= "en"`. en-US exists to
    override the keys an American reader would otherwise read wrong, and a value
    in it that agrees with en.ts agrees on purpose: identity with English is the
    correct content for an English bundle, not an untouched placeholder. It
    measures 0.00% today only because it currently holds nothing but genuine
    overrides, which is a fact about its contents and not about what the file is
    for, and its population is 1584 keys, small enough that one editing session
    could move it. Left in, the guard would eventually go red at somebody for
    doing the right thing, and a red that is wrong is how a gate gets switched
    off. The exemption is narrow, by base subtag only, and the selftest pins it.
    """
    return code == "en" or code.startswith("en-")


class Row:
    """One locale's counts. Kept as an object so the verdict and the numbers
    behind it are printed from the same place and cannot drift apart."""

    def __init__(self, code: str, values: dict[str, str], sources: dict[str, tuple[str, str]]) -> None:
        self.code = code
        self.keys = len(values)
        self.unresolved = 0
        self.blank_english = 0
        self.compared = 0
        self.identical = 0
        self.examples: list[str] = []
        for key, value in values.items():
            source = sources.get(key)
            if source is None:
                self.unresolved += 1
                continue
            english = source[0]
            if not english.strip():
                # Deliberately blank in English, e.g. an unlabelled table
                # column. "Equal to English" is meaningless for these.
                self.blank_english += 1
                continue
            self.compared += 1
            if value == english:
                self.identical += 1
                if len(self.examples) < 5:
                    self.examples.append(f"{key} = {english[:60]!r}")

    @property
    def share(self) -> float:
        return self.identical / self.compared if self.compared else 0.0

    @property
    def coverage(self) -> float:
        return self.compared / self.keys if self.keys else 0.0

    def problems(self) -> list[str]:
        found = []
        if self.share > THRESHOLD:
            found.append(
                f"{self.identical} of {self.compared} compared values ({self.share:.2%}) are byte-identical "
                f"to their English source, over the {THRESHOLD:.0%} threshold. The bundle is not translated."
            )
        if self.coverage < POPULATION_FLOOR:
            found.append(
                f"only {self.compared} of {self.keys} keys ({self.coverage:.2%}) could be compared at all, "
                f"under the {POPULATION_FLOOR:.0%} floor. {self.unresolved} key(s) have no English anywhere, "
                f"so this verdict covers less of the file than it looks like it does."
            )
        return found


def rows_for(sources: dict[str, tuple[str, str]]) -> tuple[list[Row], list[str]]:
    rows, skipped = [], []
    for path in locale_paths():
        if is_english_variant(path.stem):
            skipped.append(path.name)
            continue
        rows.append(Row(path.stem, locale_values(path), sources))
    return rows, skipped


def report(rows: list[Row], skipped: list[str], sources: dict[str, tuple[str, str]]) -> int:
    from_en = sum(1 for v in sources.values() if v[1] == "en.ts")
    print(f"English source map: {len(sources)} key(s), {from_en} from en.ts, {len(sources) - from_en} from call sites.")
    print(f"Threshold {THRESHOLD:.0%} identical, population floor {POPULATION_FLOOR:.0%} of a file's keys.")
    print(f"Not asked, English and its regional variants: {', '.join(skipped) if skipped else 'none'}.\n")
    print(f"{'code':<8}{'keys':>8}{'compared':>10}{'no-english':>12}{'blank-en':>10}{'identical':>11}{'share':>9}")
    for row in sorted(rows, key=lambda r: -r.share):
        print(
            f"{row.code:<8}{row.keys:>8}{row.compared:>10}{row.unresolved:>12}"
            f"{row.blank_english:>10}{row.identical:>11}{row.share:>8.2%}"
        )

    failed = [(row, problems) for row in rows if (problems := row.problems())]
    print(f"\n{len(rows)} locale file(s) examined, {sum(r.compared for r in rows)} value(s) compared.")
    if not failed:
        worst = max(rows, key=lambda r: r.share)
        print(f"OK highest is {worst.code} at {worst.share:.2%}, under the {THRESHOLD:.0%} threshold.")
        return 0
    for row, problems in failed:
        for problem in problems:
            print(f"\nFAIL {row.code}.ts: {problem}")
        for example in row.examples:
            print(f"    {example}")
    return 1


def check_locale(code: str) -> tuple[str, list[str]]:
    """One locale's population line and whatever is wrong with it.

    scripts/i18n_new_locale.py verify calls this, because verify is the command
    anyone finishing a locale already runs and it went green on a bundle that
    was three quarters English. A check placed somewhere that invocation does
    not reach would leave the trap exactly where it was.
    """
    sources = english_sources()
    row = Row(code, locale_values(LOCALES / f"{code}.ts"), sources)
    line = (
        f"{code}.ts: {row.keys} key(s) in the file, {row.compared} compared against their resolved English, "
        f"{row.unresolved} with no English anywhere in the tree, {row.blank_english} blank in English. "
        f"{row.identical} byte-identical ({row.share:.2%}, threshold {THRESHOLD:.0%})."
    )
    return line, row.problems()


def selftest() -> int:
    """Prove the guard can fail, on both of the things it decides.

    A guard that has only ever been seen passing is a guard nobody has read the
    failing branch of. These run the same Row and the same thresholds the real
    check runs, over locales small enough to state by hand.
    """
    sources = {f"k{i}": (f"English {i}", "en.ts") for i in range(100)}
    sources["blank"] = ("", "en.ts")

    cases: list[tuple[str, dict[str, str], bool]] = [
        (
            "a finished locale, 3 of 100 values left in English",
            {
                **{f"k{i}": f"Forditas {i}" for i in range(100)},
                "k0": "English 0",
                "k1": "English 1",
                "k2": "English 2",
            },
            True,
        ),
        (
            "a locale assembled from untouched batches, 74 of 100 still English",
            {
                **{f"k{i}": f"Forditas {i}" for i in range(100)},
                **{f"k{i}": f"English {i}" for i in range(74)},
            },
            False,
        ),
        (
            "exactly on the threshold, 10 of 100, passes",
            {
                **{f"k{i}": f"Forditas {i}" for i in range(100)},
                **{f"k{i}": f"English {i}" for i in range(10)},
            },
            True,
        ),
        (
            "one over the threshold, 11 of 100, fails",
            {
                **{f"k{i}": f"Forditas {i}" for i in range(100)},
                **{f"k{i}": f"English {i}" for i in range(11)},
            },
            False,
        ),
        (
            "a narrow population: 90 of 100 keys have no English, so the verdict is refused",
            {
                **{f"k{i}": f"Forditas {i}" for i in range(10)},
                **{f"absent{i}": "whatever" for i in range(90)},
            },
            False,
        ),
        (
            "a key blank in English is not counted as identical",
            {**{f"k{i}": f"Forditas {i}" for i in range(100)}, "blank": ""},
            True,
        ),
    ]

    failures = 0
    for name, values, should_pass in cases:
        row = Row("xx", values, sources)
        passed = not row.problems()
        if passed != should_pass:
            want = "pass" if should_pass else "fail"
            print(f"FAIL selftest expected {name} to {want}: share {row.share:.2%}, coverage {row.coverage:.2%}")
            for problem in row.problems():
                print(f"    {problem}")
            failures += 1

    # The exemption, pinned rather than assumed. An English bundle that is 100%
    # identical to English is right, and any other bundle at 100% is the defect
    # this guard exists for, so both directions are asserted.
    exempt = [
        ("en", True),
        ("en-US", True),
        ("en-GB", True),
        ("hu", False),
        ("eng", False),
        ("enum", False),
    ]
    for code, expected in exempt:
        if is_english_variant(code) != expected:
            verb = "should be skipped" if expected else "must be judged"
            print(f"FAIL selftest: {code} {verb} by is_english_variant()")
            failures += 1

    total = len(cases) + len(exempt)
    if failures:
        print(f"{failures} of {total} selftest case(s) wrong")
        return 1
    print(f"OK {total} selftest case(s): the guard passes, fails and abstains where it says it does.")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    sources = english_sources()
    rows, skipped = rows_for(sources)
    return report(rows, skipped, sources)


if __name__ == "__main__":
    raise SystemExit(main())
