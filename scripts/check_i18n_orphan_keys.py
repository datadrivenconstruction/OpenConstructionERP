#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠i18n orphan guard: block t() keys that no locale file can answer.

The two existing locale guards both start from a key that exists. The escape
guard reads locale files; the leak guard compares a locale's value against
en.ts. Neither can see the case where a key is in NO locale file at all,
because there is no value to read and nothing to compare against - the leak
guard exits 0 on it, the escape guard never visits it, tsc is happy, vitest
is happy and `npm run build` is happy.

The call site still renders, because `t(key, {defaultValue})` falls back to
the defaultValue when the key resolves nowhere. So the string reaches every
language in English, and every gate we own reports green. #175 shipped
exactly this way: service.sla_breached and service.sla_late were converted
from English literals into keys, the keys were never added to any locale
file, and the SLA chip read in English in every language through a full
release with three hygiene gates passing on it.

This guard closes that hole. It reads every `t(key, {..., defaultValue, ...})`
call site under frontend/src, resolves each key against every bundle, and
fails on any key fewer than all of them can answer. The locale count is
never written down here: it is whatever LOCALE_GLOB finds, because the count
has grown four times since this was written and a number in a comment is a
claim nobody re-checks.

Four things worth knowing about how it counts:

  * Plural forms. i18next resolves a counted key through its CLDR category,
    so `meetings.attachment_n` need never exist as a bare key if
    `meetings.attachment_n_one` and `_other` do. A key is reachable in a
    locale if the bare form OR any CLDR-suffixed form is present there.
    Ignoring this reports 23 orphans where there are 8. What it deliberately
    does NOT check is plural COMPLETENESS - a Russian file carrying only
    `_other` counts as reachable here, because "reachable at all" and "has
    every form this language needs" are different questions and conflating
    them would let this guard fail for a reason its message does not state.

  * Regional variants. es-MX, es-CL, es-CO, pt-BR and en-US carry only the
    words that differ from their base language, by design, so a key they do
    not declare is answered by es, pt or en and the reader sees their own
    language rather than a fallback. Those are not holes and counting them
    as holes made one 1499-key overlay print 25280 errors. A variant is only
    missing a key when its base is missing it too.

  * Scope. Keys called WITHOUT a default are out of scope. A missing one of
    those renders the raw key on screen, which is loud, self-reporting and
    gets fixed the day someone opens the page. A default is the silent one,
    and silence is what needs a machine watching it.

    i18next takes a default in two shapes and both are silent: the options
    object this guard was written around, and a bare string as the second
    argument, `t(key, 'Some English')`. For a long time only the first was
    read, so the second was out of scope by accident rather than by the
    reasoning above - the same defect the guard exists to catch, in the shape
    it happened not to match. Measured when that was fixed: 1120 keys were
    called only in the positional shape, and 20 of them had a real gap. Eight
    were answered by no locale at all and had been English in every language
    since they were written - `people.no_login` and its neighbours in the
    project people picker, and three subtotal lines in the assembly library.
    `positionalDefaultIsADefaultValue.test.ts` asserts the runtime behaviour
    this scope now rests on, so an i18next that stopped honouring the
    positional form would fail there rather than turn this guard back into a
    formality.

  * Baseline, not allowlist. Known debt lives in i18n_orphan_baseline.json
    as an explicit map of key to the SET of locales that cannot answer it,
    the same shape the leak guard uses and for the same reason: a count
    cannot tell a repaired locale from a newly broken one, and a bare key
    list goes green the moment the first locale is filled in. The set may
    only shrink. More locales missing than recorded is a regression.

Parser desync is a failure, not a pass. The key regex here is double-quote
only, matching the shape every locale file is written in; if a file ever
picks up single-quoted or multi-line entries its keys drop out of the scan
and the guard would go green on missing data. A locale file that parses to
no keys, or a source tree that yields no call sites, fails rather than
reporting success on nothing.

A gap in a locale outside SUPPORTED_LANGUAGES is not always the same defect
as a gap in one that is. frontend/src/app/i18n.ts decides which languages a
real reader can pick, and a file that exists on disk but is not on that list
is not being shown to anyone - a translator can be partway through it, or it
can be a build nobody finished, and those are different states. A locale in
SUPPORTED_LANGUAGES gets no exception here regardless of which: it is being
offered today, so every gap in it stays a hard error, exactly as before this
mechanism existed. Outside that list, the guard reads how much of the file
still matches English word for word (identical_fraction, against
IN_PROGRESS_IDENTICAL_FRACTION) rather than trusting a flag someone could set
once and never revisit: a file still mostly English downgrades to a loud,
counted line instead of an error, and a file that reads as finished but was
never added to SUPPORTED_LANGUAGES is its own anomaly and gets said
explicitly rather than passed in silence. The threshold was set by measuring
the committed tree, not guessed: every finished locale sat under 5% identical
(nl highest, at 4.83%, from ordinary overlap like numbers and codes and
acronyms such as BOQ or MEP), en-US sat at 0% because it inherits everything,
and the one locale genuinely mid-translation at the time sat at 47.23%.
Whether a given locale belongs in SUPPORTED_LANGUAGES at all is a product
decision this guard does not make; it only enforces whichever way that list
currently reads.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections.abc import Container

LOCALE_GLOB = "frontend/src/app/locales/*.ts"
SOURCE_GLOB = "frontend/src/**/*.ts*"
BASELINE_PATH = "scripts/i18n_orphan_baseline.json"
I18N_TS_PATH = "frontend/src/app/i18n.ts"
EN_PATH = "frontend/src/app/locales/en.ts"

# Above this share of a locale's shared keys sitting byte-identical to en.ts,
# a locale outside SUPPORTED_LANGUAGES reads as still under construction
# rather than finished. See the module docstring for how this was measured.
IN_PROGRESS_IDENTICAL_FRACTION = 0.10

# `"key": ` at the head of a line, the one-entry-per-line shape the locale
# files are generated in. Same double-quote-only blind spot the leak guard
# documents, and desync is caught by the zero-key check rather than tolerated.
_KEY_LINE = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)"\s*:', re.MULTILINE)

# Same shape as _KEY_LINE, with the value captured too. Only used for the
# identical-fraction heuristic below, so a value this misses (wrapped across
# lines, which the generator does not produce) only narrows that sample and
# never affects which keys count as missing.
_KEY_VALUE_LINE = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', re.MULTILINE)

# `{ code: 'xx', ... }` entries inside SUPPORTED_LANGUAGES.
_SUPPORTED_CODE = re.compile(r"code:\s*'([A-Za-z0-9\-]+)'")

# Opening of a t() call with a string-literal key, up to the `{` of its
# options object. The options object itself is brace-matched afterwards
# rather than regex-matched: a defaultValue is very often a template literal
# and `[^}]*` stops at the first `}` of an interpolation, which would drop
# real call sites and make this guard quietly narrower than it claims.
_CALL_HEAD = re.compile(r"""\bt\(\s*(['"])([A-Za-z0-9_][A-Za-z0-9_.\-]*)\1\s*,\s*\{""")

# The other defaultValue shape: `t(key, 'English')`. i18next reads a bare
# string second argument as the default, so these fail exactly as silently as
# the object form and belong in the same scope. Nothing is brace-matched here
# because there is no options object to match; the key is what this guard
# needs and the default itself is never read.
#
# The opening quote of the default is enough to tell this shape from the
# others. A second argument that is a variable, a call or an object is not a
# default this guard can name, and `t(key)` alone is the loud case the scope
# paragraph excludes on purpose.
_CALL_HEAD_STRING_DEFAULT = re.compile(r"""\bt\(\s*(['"])([A-Za-z0-9_][A-Za-z0-9_.\-]*)\1\s*,\s*['"`]""")

_CLDR_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")


def _base_of(stem: str, by_locale: Container[str]) -> str | None:
    """The language file a regional variant resolves through, if there is one.

    i18next expands a two-part code into ``['es-MX', 'es', ...]`` on its own,
    before it ever consults the fallback map in ``frontend/src/app/i18n.ts``,
    so this is derived from the code rather than mirrored from that map. A
    mirrored table is a second copy of a decision, and the copy is the one
    that goes stale: en-US was added to the app and this guard did not know.

    ``zh-TW`` with no ``zh.ts`` beside it would resolve straight to English
    and therefore has no base as far as this guard is concerned.
    """
    if "-" not in stem:
        return None
    base = stem.split("-", 1)[0]
    return base if base in by_locale else None


# The public name for the rule above. scripts/audit_i18n_coverage.py imports
# this rather than growing another copy of it: a second definition of "which
# file answers a variant" is exactly the thing that drifts, and this repo has
# already paid for that drift once. The parameter is only ever tested for
# membership, so a set of locale stems works as well as a stem-to-keys map.
base_of = _base_of


def read_supported_languages(path: str = I18N_TS_PATH) -> set[str]:
    """Locale codes the language picker actually offers.

    Deliberately not "every *.ts file under locales/": mn.ts sits on disk
    today, invented rather than translated, and was removed from this list
    for it while the file stayed so the work resumes from where it stopped.
    This guard's strictness has to follow what a user can select, not what
    happens to exist on disk.

    A locale can leave this list two ways, and both have to read as absent
    here. mn's entry was deleted outright. uz's was commented out in place,
    `// { code: 'uz', ... },`, so the literal text `code: 'uz'` is still
    sitting in the file. A regex blind to `//` would match it anyway and
    keep enforcing uz as supported for the wrong reason, which is exactly
    the failure this guard exists to avoid one layer up. Each line is cut at
    its first `//` before matching, which is safe for this array because
    none of its fields ever contain that sequence.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    start = text.find("SUPPORTED_LANGUAGES")
    end = text.find("\n];", start) if start >= 0 else -1
    if end < 0:
        return set()
    active = "\n".join(line.split("//", 1)[0] for line in text[start:end].splitlines())
    return set(_SUPPORTED_CODE.findall(active))


def read_en_values(path: str = EN_PATH) -> dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        return dict(_KEY_VALUE_LINE.findall(fh.read()))


def identical_fraction(locale_path: str, en_values: dict[str, str]) -> float:
    """Share of a locale's keys whose value is byte-identical to en.ts.

    A coarse signal, not a translation-quality check: a finished locale still
    matches English on numbers, unit codes and acronyms like BOQ or MEP, so
    some identical fraction is normal everywhere. See IN_PROGRESS_IDENTICAL_
    FRACTION for how the cutoff was set.
    """
    with open(locale_path, encoding="utf-8") as fh:
        pairs = dict(_KEY_VALUE_LINE.findall(fh.read()))
    shared = [k for k in pairs if k in en_values]
    if not shared:
        return 0.0
    return sum(1 for k in shared if pairs[k] == en_values[k]) / len(shared)


def classify_locales(
    by_locale: dict[str, set[str]],
    supported: set[str],
    en_values: dict[str, str],
    locale_glob: str = LOCALE_GLOB,
) -> tuple[set[str], dict[str, float], set[str]]:
    """Split locales outside SUPPORTED_LANGUAGES into in-progress and abandoned.

    A locale in SUPPORTED_LANGUAGES is not classified at all: it is offered
    to a user today, so every gap in it stays a hard error no matter how
    translated the file otherwise is. Outside that list, a high share of
    values still identical to English reads as a file mid-translation, which
    is expected and downgrades; a low share reads as a file nobody is
    building and nobody is showing, which is its own anomaly and stays
    enforced, just named for what it is.
    """
    in_progress: set[str] = set()
    abandoned: set[str] = set()
    fractions: dict[str, float] = {}
    for stem in by_locale:
        if stem in supported:
            continue
        path = locale_glob.replace("*", stem)
        frac = identical_fraction(path, en_values)
        fractions[stem] = frac
        (in_progress if frac > IN_PROGRESS_IDENTICAL_FRACTION else abandoned).add(stem)
    return in_progress, fractions, abandoned


def _options_body(text: str, brace_index: int) -> str | None:
    """Return the source between the options `{` and its matching `}`."""
    depth = 0
    for i in range(brace_index, len(text)):
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index + 1 : i]
    return None


def _read_locales() -> dict[str, set[str]]:
    """Map locale stem to the set of keys that locale file declares."""
    by_locale: dict[str, set[str]] = {}
    for path in sorted(glob.glob(LOCALE_GLOB)):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in {"index", "types"}:
            continue
        with open(path, encoding="utf-8") as fh:
            by_locale[stem] = set(_KEY_LINE.findall(fh.read()))
    return by_locale


def _read_call_sites() -> dict[str, str]:
    """Map each key called with a default to the first file calling it.

    Both default shapes count. The file-level skip is on ``t(`` rather than on
    ``defaultValue``, because a file whose every default is positional never
    contains that word and used to be skipped whole - which is how the
    positional shape stayed out of scope twice over, once in the regex and
    once before the regex ever ran.
    """
    sites: dict[str, str] = {}
    for path in sorted(glob.glob(SOURCE_GLOB, recursive=True)):
        posix = path.replace(os.sep, "/")
        if "/app/locales/" in posix or ".test." in posix or ".spec." in posix:
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if "t(" not in text:
            continue
        for match in _CALL_HEAD.finditer(text):
            body = _options_body(text, match.end() - 1)
            if body is None or "defaultValue" not in body:
                continue
            sites.setdefault(match.group(2), posix)
        for match in _CALL_HEAD_STRING_DEFAULT.finditer(text):
            sites.setdefault(match.group(2), posix)
    return sites


def _reach(key: str, by_locale: dict[str, set[str]]) -> set[str]:
    """Locales that can answer this key, bare form or any CLDR plural form."""
    forms = (key, *(key + suffix for suffix in _CLDR_SUFFIXES))
    return {stem for stem, keys in by_locale.items() if any(f in keys for f in forms)}


def missing_locales(
    key: str,
    by_locale: dict[str, set[str]],
    bases: dict[str, str | None],
    in_progress: frozenset[str] = frozenset(),
) -> list[str]:
    """Locales whose reader would see this key's English default.

    A regional variant is answered by its base language, so it counts as
    covered when the base declares the key even though the variant file does
    not. Falling back to the base is the designed behaviour; falling back past
    it into English is the defect this guard exists to catch.

    A locale classified as in-progress (see classify_locales) is excluded the
    same way a variant's base is: not because the gap is answered, but because
    it is not this guard's job to enforce a file nobody has finished and
    nobody is showing. downgraded_locales reports exactly what was excluded
    here, so the exclusion is never silent even though it is not an error.
    """
    reach = _reach(key, by_locale)
    return sorted(
        stem for stem in by_locale if stem not in reach and bases[stem] not in reach and stem not in in_progress
    )


def downgraded_locales(
    key: str,
    by_locale: dict[str, set[str]],
    bases: dict[str, str | None],
    in_progress: frozenset[str],
) -> list[str]:
    """In-progress locales this key's English default would still reach.

    The mirror of the exclusion missing_locales makes: everything counted
    here is a gap that is NOT enforced, and it exists so that exclusion is
    reported with a number instead of disappearing from the guard's output.
    """
    reach = _reach(key, by_locale)
    return sorted(stem for stem in in_progress if stem not in reach and bases[stem] not in reach)


def main() -> int:
    by_locale = _read_locales()
    if not by_locale:
        print(f"ERROR: no files matched {LOCALE_GLOB!r}", file=sys.stderr)
        return 1
    empty = sorted(stem for stem, keys in by_locale.items() if not keys)
    if empty:
        print(
            f"ERROR: {len(empty)} locale file(s) parsed to zero keys: {', '.join(empty)}.\n"
            "The key regex is double-quote only. A file written any other way "
            "drops out of this scan silently, so an empty parse is treated as a "
            "broken scan rather than a clean one.",
            file=sys.stderr,
        )
        return 1

    sites = _read_call_sites()
    if not sites:
        print(
            f"ERROR: no t(key, {{defaultValue}}) call sites found under {SOURCE_GLOB!r}. "
            "Finding nothing and not having looked must not print the same result.",
            file=sys.stderr,
        )
        return 1

    with open(BASELINE_PATH, encoding="utf-8") as fh:
        baseline: dict[str, dict[str, object]] = json.load(fh)

    all_locales = set(by_locale)
    # A regional variant carries only the words that actually differ from its
    # base language, so a key it does not declare is not a hole: the reader
    # gets Spanish on a Chilean screen, or English on an American one, which
    # is the right answer in both cases. Counting those as missing turned one
    # deliberate 1499-key overlay into 25280 errors and would have pushed
    # whoever met it into pasting a full copy of English into en-US.ts.
    bases = {stem: _base_of(stem, by_locale) for stem in all_locales}
    variants = {stem: base for stem, base in bases.items() if base}

    supported = read_supported_languages()
    if "en" not in supported:
        # "en" is structurally the first entry of SUPPORTED_LANGUAGES, so its
        # absence means the array was not found or nothing inside it parsed,
        # not that English was ever dropped from the picker. Refusing here
        # matters more than the other zero-parse tripwires in this file: a
        # silent empty set would classify every locale as unsupported and
        # start downgrading gaps this guard exists to keep enforced, uz among
        # them, which would go green for exactly the wrong reason.
        print(
            f"ERROR: could not read SUPPORTED_LANGUAGES from {I18N_TS_PATH}. "
            "An empty or unparsed read here is not a clean read: it would "
            "classify every locale as unsupported and start downgrading gaps "
            "this guard exists to enforce.",
            file=sys.stderr,
        )
        return 1
    en_values = read_en_values()
    in_progress, fractions, abandoned = classify_locales(by_locale, supported, en_values)

    new_gaps: list[tuple[str, str, list[str]]] = []
    widened: list[tuple[str, list[str]]] = []
    healed: list[str] = []
    downgraded: dict[str, list[str]] = {}

    for key, first_file in sorted(sites.items()):
        missing = missing_locales(key, by_locale, bases, frozenset(in_progress))
        for stem in downgraded_locales(key, by_locale, bases, frozenset(in_progress)):
            downgraded.setdefault(stem, []).append(key)
        entry = baseline.get(key)
        declared = sorted(entry["missing_locales"]) if entry else []  # type: ignore[index,arg-type]
        if not missing:
            if key in baseline:
                healed.append(key)
            continue
        if key not in baseline:
            new_gaps.append((key, first_file, missing))
        elif set(missing) - set(declared):
            widened.append((key, sorted(set(missing) - set(declared))))

    # Printed unconditionally, pass or fail: a locale excluded here is a gap
    # that is not being enforced, and that must never look the same as a gap
    # that does not exist.
    if in_progress:
        print(
            f"{len(in_progress)} locale(s) outside SUPPORTED_LANGUAGES read as "
            "mid-translation and are not enforced by this guard:"
        )
        for stem in sorted(in_progress):
            n = len(downgraded.get(stem, []))
            print(
                f"  {stem}: {fractions[stem] * 100:.1f}% of shared keys still "
                f"identical to English, {n} gap(s) not enforced"
            )
    else:
        print("0 locale(s) outside SUPPORTED_LANGUAGES read as mid-translation.")
    if abandoned:
        print(
            f"{len(abandoned)} locale(s) outside SUPPORTED_LANGUAGES read as finished "
            "but are not offered to anyone; their gaps are enforced below like any "
            f"other locale, since nothing else is tracking that file's completion: "
            f"{', '.join(sorted(abandoned))}"
        )
    else:
        print("0 locale(s) outside SUPPORTED_LANGUAGES read as an abandoned, unoffered file.")

    if new_gaps or widened:
        for key, first_file, missing in new_gaps:
            print(
                f"ERROR: {key} is answered by no locale file it needs "
                f"({len(all_locales) - len(missing)}/{len(all_locales)}), "
                f"called from {first_file}",
                file=sys.stderr,
            )
            print(f"  missing: {', '.join(missing)}", file=sys.stderr)
        for key, extra in widened:
            print(
                f"ERROR: {key} lost locales the baseline did not record: {', '.join(extra)}",
                file=sys.stderr,
            )
        print(
            "\nA key called with a defaultValue and answered by no locale file "
            "renders its English default in every language, and no other gate "
            "we own can see it: there is no value to compare against, so the "
            "leak guard passes, tsc passes and the build passes. Add the key to "
            "every locale, grounded in what that language's own units and plural "
            "forms substitute into the sentence. Do not silence this by dropping "
            "the defaultValue - that turns a silent English string into a raw "
            f"key on screen. {BASELINE_PATH} records existing debt only and may "
            "only shrink.",
            file=sys.stderr,
        )
        return 1

    print(
        f"i18n orphan keys OK: {len(sites)} keys called with a defaultValue "
        f"across {len(by_locale)} locales, {len(baseline)} in the baseline"
    )
    # Printed rather than assumed: if the derivation ever stops finding a base,
    # this guard silently starts demanding a full keyspace of every variant,
    # and the message it prints would still read like an ordinary gap.
    print(
        "  regional variants resolving through a base language: "
        + (", ".join(f"{stem} via {base}" for stem, base in sorted(variants.items())) or "none")
    )
    if healed:
        shown = ", ".join(healed[:12])
        more = f", and {len(healed) - 12} more" if len(healed) > 12 else ""
        print(f"  {len(healed)} baseline key(s) now fully answered, drop them: {shown}{more}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
