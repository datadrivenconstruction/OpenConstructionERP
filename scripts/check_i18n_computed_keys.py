#!/usr/bin/env python3
"""i18n computed-key guard: the t() call sites whose key is not a literal.

check_i18n_orphan_keys.py closes the hole where `t('key', {defaultValue})`
names a key no locale file can answer. Its call-site regex requires a quoted
string for the key, and that is not a limitation of its implementation but
the boundary of what it can resolve. Every call site that builds its key at
runtime sits outside it:

    t(`price_breakdown.kind.${c.kind}`, { defaultValue: c.kind })
    t(item.labelKey, { defaultValue: item.defaultLabel })

Both render the English defaultValue in all 40 languages when the key is
missing. That is the same silent failure the orphan guard exists to stop,
arriving through a door it cannot watch. nav.credentials reached production
through the second shape: a sidebar entry whose key existed in no locale
file, invisible to the orphan scan and to the locale-gap scan alike, reading
correct English to every reviewer who opened the page.

This guard started by asking only about en.ts, on the reasoning that "is this
key answered by every locale" belonged to the orphan guard and a second script
answering the same question would give two baselines for one fact. That split
held only while the keys were unresolvable. A key absent from en.ts is still
the unambiguous case, it exists nowhere and the English default is all anyone
will ever see, but wherever this script recovers a CONCRETE key the orphan
guard cannot reach, the locale question is this script's to ask too, because
no other script can reach that key either. The member check below already
works this way, and so does the `<x>Default` pair class. There is one baseline
per question, never two baselines for one fact.

Five shapes, and the difference between them is the whole design.

  * Template literal, static head. `price_breakdown.kind.${kind}` cannot be
    resolved to its members without knowing the union, and c.kind arrives
    from the wire as a string, so no amount of cleverness recovers them. But
    "does en.ts hold ANY key beginning with `price_breakdown.kind.`" is
    decidable without knowing a single member, and an empty answer proves
    the entire family is unanswerable. That is the first check.

    It used to stop there, on the claim that a populated prefix might still
    be missing individual members and this guard could say nothing about
    those. That claim was one step short of true. Once en.ts answers a
    prefix, its members are no longer hypothetical: they are literal
    dictionary entries sitting in the file this script has already parsed.
    schedule_advanced.rnc.manpower is exactly as literal as any key the
    orphan guard resolves from a call site, and asking whether every OTHER
    locale carries it is the same question the orphan guard already knows
    how to ask, just fed a key list gathered from en.ts instead of from a
    quoted call site. So the second check enumerates the concrete members of
    every prefix en.ts answers, and asks each of the other locales for each
    of them, exactly as the orphan guard would. A family being "answered"
    used to mean en.ts alone; it now means every locale that has to.
    schedule_advanced.rnc reached 38 of 38 locales that need their own copy
    only because someone measured it by hand outside this script - this
    check exists so the next family like it does not need a human to notice.

  * Literal key paired with a default in a table. `{ labelKey: 'nav.x',
    defaultLabel: 'X' }` is fully resolvable even though the call site that
    consumes it is not, because the key is right there as a literal. This is
    the nav.credentials shape and it is checked exactly. The same prop is
    written under six names in this tree (defaultLabel, defaultName,
    defaultDesc, defaultText, defaultTitle, defaultHelp) and all six pair,
    because a guard keyed to one of them would report the class clean while
    its siblings went unread.

  * Literal key paired with its English in a `<x>Default` field. `{ titleKey:
    'guide.dashboard.title', titleDefault: 'Dashboard' }` is the same class as
    the one above and was in none of this script's buckets, not even the NOT
    CHECKED census below, because the pairing anchored on the PREFIX spelling
    `default` plus a capital and this shape writes the suffix. `titleDefault`
    is not `defaultTitle`, and the sibling rule in the next bullet looks for a
    bare `title` field, which a guide does not have either. So 5050 pairs, the
    whole `guide.*` namespace among them, went unread while the script printed
    a clean exit and a census that did not mention them.

    It is the nav.credentials failure a second time. Every one of the 104
    *Guide.ts files is written this way, the call site in
    shared/ui/ModuleGuide.tsx is `t(content.titleKey, { defaultValue:
    content.titleDefault })`, and none of those keys are in en.ts. Until the
    guides were translated that meant every reader in every language got the
    English default; the other locale files carry the keys now, so it is the
    English reader who gets the inline default, and any locale file missing a
    key hands its reader English without a word. The key is a literal where
    the table declares it, which is why this is decidable at all.

    Two questions are asked of it, and they are kept apart because the answers
    are nothing alike. Is the key in en.ts: 1520 are not, every one of them a
    guide, recorded per family in i18n_suffix_pair_baseline.json as a count
    matched exactly, so it fails when the debt grows and equally when it
    shrinks without the entry coming down with it, since a count left high is
    slack the next addition spends unseen. Can every locale answer the ones
    en.ts DOES hold: all 736 can, so that half gets no baseline and the next
    break of it fails on arrival rather than being absorbed by a list.

    The `cases.<slug>.*` keys are excluded from the en.ts question only, on the
    reason the next bullet already gives: they keep their English in the case
    data file deliberately, so asking en.ts about them is the wrong question,
    and the 2793 of them would have buried the 1520 real findings. They are
    counted and named in the census rather than dropped.

  * Literal key paired with its English in a SIBLING field. `{ moduleLabel:
    'Payment Clock', moduleLabelKey: 'nav.payment_clock' }` looks like the
    class above and is not reachable by it, because the pair is anchored on
    the English field and this one is not named default-anything. Adding a
    seventh name would not fix it either: the same widening pulls in the
    `cases.<slug>.*` content keys, and those keep their English in the data
    file on purpose and are deliberately absent from en.ts, so the one
    question this script asks would be the wrong question to ask about them.
    They are counted and named below, and the module chips among them are
    checked by check_case_module_chip_locales.py, which asks locale coverage
    instead. Before that script existed this shape was in no scan at all and
    three chip keys reached 31 locales in English.

  * Everything else. A bare variable (`t(job.stage, {defaultValue})`), a
    template whose interpolation comes first and leaves no prefix. These
    cannot be resolved at all. They are counted, named, and printed under a
    heading that says they were not checked. A gate that drops what it
    cannot resolve is worse than no gate, because the clean exit reads as
    coverage over ground nobody looked at.

Known debt lives in the baseline file and may only shrink. The prop-shaped
class had no findings when this was written, so it contributes nothing to the
baseline and any new break of that shape fails on arrival.

The baseline arrived at 118 entries. It passed through 188 while the families
were being worked, but that intermediate never existed on main, so the seventy
reasons taken off it are not recoverable from history and would have to be
re-derived from the call sites. Each remaining entry carries its reason because
a bare list of prefixes decays into a list nobody can audit: the reason is the
only thing that tells a later reader whether a family may come off.

The member-completeness check has its own baseline, i18n_computed_member_
baseline.json, and it is a worklist rather than an allowlist for a reason a
plain list of prefixes would not give it. Each entry names the prefix, the
member count and the locale coverage it was frozen at, for example
`"schedule_advanced.rnc.": {"members": 9, "locales_ok": 38, "locales_total":
43, "missing": {"uz": [...]}}`. A prefix recorded only by name tells a later
reader nothing about whether the debt is one locale short of done or has
barely started; the count is what turns the entry into a thing someone can
work down instead of a permanent excuse. The `missing` map is the same shape
i18n_orphan_baseline.json already uses for literal keys, key by key rather
than a plain locale count, because a count cannot tell a repaired locale from
a newly broken one and this baseline may only shrink in the same sense the
orphan baseline does: fewer locales missing each member, never more.

This script, that baseline and the repo-hygiene job that runs it are one change
and cannot be split into three. The job names this file by path, and both this
file and the baseline arrived untracked, so any commit carrying the workflow
without them is red the moment it lands.

One thing to know before correcting English anywhere this guard points. Once a
family has members in en.ts, i18next never reaches its defaultValue, so the
label table at the call site stops being what anyone reads and becomes the
fallback for values outside the declared set. Fixing wording in that table alone
therefore changes the code and not the screen, which is exactly what happened to
the ROM reconciliation band: the table was corrected, the keys had landed hours
earlier, and the panel went on showing the older wording. Worse, the test over
that panel mocks react-i18next, so t() hands back the defaultValue and the
assertions are about the table. It was green throughout. A test written that way
proves the fallback correct and says nothing at all about what renders, so the
place to check a string this guard has landed is en.ts.

Parser desync is a failure, not a pass, on the same reasoning as the sibling
guards: en.ts parsing to zero keys, or a source tree yielding no call sites,
exits 2 rather than reporting a clean scan of nothing.

The member-completeness check shares one more piece of machinery with the
orphan guard: a locale outside SUPPORTED_LANGUAGES is not enforced the same
way a listed one is. frontend/src/app/i18n.ts decides which languages a real
reader can pick, and this check reads how much of an unlisted locale's file
still matches English word for word (identical_fraction, against
IN_PROGRESS_IDENTICAL_FRACTION) to tell a file mid-translation from one that
reads finished but was never listed. A locale in SUPPORTED_LANGUAGES gets no
exception regardless: every member it is missing is a hard error. See
check_i18n_orphan_keys.py, which carries the fuller reasoning and the
measurement this threshold was set from; the two guards duplicate the
mechanism rather than share it, on the same one-script-per-concern grounds
they already duplicate _options_body and _KEY_LINE.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

DEFAULT_EN_PATH = "frontend/src/app/locales/en.ts"
DEFAULT_SOURCE_GLOB = "frontend/src/**/*.ts*"
DEFAULT_BASELINE_PATH = "scripts/i18n_computed_key_baseline.json"
DEFAULT_LOCALE_GLOB = "frontend/src/app/locales/*.ts"
DEFAULT_MEMBER_BASELINE_PATH = "scripts/i18n_computed_member_baseline.json"
DEFAULT_SUFFIX_BASELINE_PATH = "scripts/i18n_suffix_pair_baseline.json"
DEFAULT_I18N_TS_PATH = "frontend/src/app/i18n.ts"

_CLDR_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")

# Above this share of a locale's shared keys sitting byte-identical to en.ts,
# a locale outside SUPPORTED_LANGUAGES reads as still under construction
# rather than finished. See check_i18n_orphan_keys.py for how this was
# measured; duplicated rather than imported, like everything else this file
# shares with that one.
IN_PROGRESS_IDENTICAL_FRACTION = 0.10

# `"key": ` at the head of a line, the shape the locale files are generated
# in. Double-quote only, like the sibling guards; the zero-key tripwire below
# turns a change in that shape into a failure instead of a smaller scan.
_KEY_LINE = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)"\s*:', re.MULTILINE)

# Same shape as _KEY_LINE, with the value captured too. Only used for the
# identical-fraction heuristic, so a value this misses (wrapped across lines,
# which the generator does not produce) only narrows that sample and never
# affects which keys count as missing.
_KEY_VALUE_LINE = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', re.MULTILINE)

# `{ code: 'xx', ... }` entries inside SUPPORTED_LANGUAGES.
_SUPPORTED_CODE = re.compile(r"code:\s*'([A-Za-z0-9\-]+)'")

# The opening of `t(` with a template-literal key.
_TPL_HEAD = re.compile(r"\bt\(\s*`")

# The opening of `t(` with a variable key: an identifier or property path,
# never a quoted literal (the orphan guard owns those).
_VAR_HEAD = re.compile(r"\bt\(\s*([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z0-9_$]+)*)\s*,\s*\{")

# A table entry naming its key: any `<something>Key` or `key` field holding a
# literal. Broad on purpose; the tree calls these labelKey, i18nKey, ariaKey
# and titleKey, and a guard keyed to one name would miss the next one.
_KEY_FIELD = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*[Kk]ey)\s*:\s*(['\"])([A-Za-z0-9_][A-Za-z0-9_.\-]*)\2")
# The English standing in for the key. `defaultLabel` is the common name but
# the tree also writes defaultName, defaultDesc, defaultText, defaultTitle and
# defaultHelp for the same job, and a guard keyed to one of them would call the
# prop class clean while its siblings went unread. `defaultValue` is excluded
# because that is the t() option itself, handled by the call-site scan above;
# pairing on it would let an unrelated key field three lines away form a
# spurious pair.
_DEFAULT_FIELD = re.compile(r"\b(default(?!Value\b)[A-Z][A-Za-z0-9_]*)\s*:\s*(['\"])(.*?)\2")

# A `<x>Key` field whose English sits in a sibling `<x>` field rather than in
# a default* one, so _DEFAULT_FIELD never anchors and no pair forms. The case
# playbooks are written this way throughout: `moduleLabel` beside
# `moduleLabelKey`, `label` beside `labelKey`. Counted and named below rather
# than paired, because the two populations underneath this shape answer to
# different questions and one check cannot hold both. See the docstring.
_SIBLING_KEY = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)Key\s*:\s*(['\"])([A-Za-z0-9_][A-Za-z0-9_.\-]*)\2")

# A `<x>Key` field whose English sits in a `<x>Default` field. _DEFAULT_FIELD
# anchors on the PREFIX spelling, `default` then a capital, so it never fires
# on this one: `titleDefault` is not `defaultTitle`, and `_SIBLING_KEY` above
# does not reach it either because that one looks for a bare `<x>` sibling and
# the sibling here is `<x>Default`. The shape therefore landed in no bucket at
# all, not even the NOT CHECKED census, which is the one outcome this file's
# docstring says is worse than having no gate.
#
# It is the shape every module guide is written in (`titleKey`/`titleDefault`,
# `introKey`/`introDefault`, `bodyKey`/`bodyDefault` in the 104 *Guide.ts
# files), and it is the nav.credentials failure again: the call site in
# shared/ui/ModuleGuide.tsx is `t(content.titleKey, { defaultValue:
# content.titleDefault })`, a variable key, so the orphan guard cannot see it,
# and a locale file that lacks the key shows its reader the English default.
#
# Anchored on the Key field and looking for that field's OWN `<x>Default`
# sibling, rather than pairing whatever key happens to sit near a default.
# A guide section puts titleKey, titleDefault, bodyKey and bodyDefault inside
# the same three-line window, so a window-wide search would hand bodyDefault
# the titleKey and count one key twice while never reading the other.
_SUFFIX_PAIR_KEY = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)Key\s*:\s*(['\"])([A-Za-z0-9_][A-Za-z0-9_.\-]*)\2")

# The one family excluded from the en.ts question below, for the reason the
# docstring already gives about the `cases.<slug>.*` content keys: they keep
# their English in the case data file on purpose and are deliberately absent
# from en.ts, so "is this in en.ts" is the wrong question to ask about them
# and asking it anyway would bury the 1520 real findings under 2793 false
# ones. Their locale coverage is owned by check_case_module_chip_locales.py.
_SUFFIX_PAIR_EXCLUDED = ("cases.",)

# How far above or below a defaultLabel its key field may sit. Entries are
# written on one line in this tree; the window catches the wrapped ones.
_PAIR_WINDOW = 3


@dataclass
class Sites:
    """Every computed-key call site, split by what can be decided about it."""

    template: list[tuple[str, str]] = field(default_factory=list)
    """(file, raw template source) for keys with a defaultValue."""

    headless: list[tuple[str, str]] = field(default_factory=list)
    """Templates whose interpolation comes first, leaving no prefix."""

    variable: list[tuple[str, str]] = field(default_factory=list)
    """(file, expression) for `t(expr, {defaultValue})` with a variable key."""

    pairs: list[tuple[str, int, str, str]] = field(default_factory=list)
    """(file, line, literal key, default) from a resolvable table entry."""

    unpaired: list[tuple[str, int]] = field(default_factory=list)
    """default* lines with no key field near them."""

    sibling: list[tuple[str, int, str, str]] = field(default_factory=list)
    """(file, line, literal key, sibling field name) for the `<x>Key` beside
    `<x>` shape, which _DEFAULT_FIELD cannot anchor on and this guard does
    not resolve."""

    suffix_pairs: list[tuple[str, int, str, str]] = field(default_factory=list)
    """(file, line, literal key, prop stem) for the `<x>Key` beside
    `<x>Default` shape. Fully resolvable, the key is a literal, and checked
    exactly like sites.pairs."""


def _close_template(text: str, start: int) -> int | None:
    """Index of the backtick closing the template literal opened at `start`.

    Walks `${...}` by depth rather than stopping at the first `}`, and recurses
    into nested templates, because a defaultValue is very often itself a
    template and a naive scan would end the key in the middle of one.
    """
    i = start + 1
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "`":
            return i
        if char == "$" and i + 1 < len(text) and text[i + 1] == "{":
            depth = 1
            i += 2
            while i < len(text) and depth:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                elif text[i] == "`":
                    nested = _close_template(text, i)
                    if nested is None:
                        return None
                    i = nested
                i += 1
            continue
        i += 1
    return None


def _options_body(text: str, brace_index: int) -> str | None:
    """The source between the options `{` and its matching `}`."""
    depth = 0
    for i in range(brace_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index + 1 : i]
    return None


def static_prefix(raw: str) -> str:
    """The literal head of a template key, up to its first interpolation."""
    cut = raw.find("${")
    return raw if cut < 0 else raw[:cut]


def family_prefix(key: str) -> str:
    """The family a literal key belongs to, for baselining suffix pairs.

    Two segments and a trailing dot, so `guide.dashboard.actions.title` and
    `guide.dashboard.intro` land on `guide.dashboard.`, one entry per guide
    file rather than one per string. A key with only two segments keeps its
    first, so `iso.mm` families under `iso.`.

    Deliberately not the template-prefix idiom above: that one is handed the
    literal head the source already wrote, while these keys carry no marker
    saying where the family stops, and a per-key baseline of 1520 entries is
    a list nobody audits.
    """
    parts = key.split(".")
    return ".".join(parts[:2]) + "." if len(parts) > 2 else parts[0] + "."


def _iter_sources(source_glob: str):
    for path in sorted(glob.glob(source_glob, recursive=True)):
        posix = path.replace(os.sep, "/")
        if "/app/locales/" in posix or ".test." in posix or ".spec." in posix:
            continue
        with open(path, encoding="utf-8") as fh:
            yield posix, fh.read()


def collect(source_glob: str) -> Sites:
    """Every computed-key call site under the glob, classified."""
    sites = Sites()
    for posix, text in _iter_sources(source_glob):
        for match in _TPL_HEAD.finditer(text):
            tick = match.end() - 1
            end = _close_template(text, tick)
            if end is None:
                continue
            raw = text[tick + 1 : end]
            rest = text[end + 1 :]
            opening = re.match(r"\s*,\s*\{", rest)
            if not opening:
                # No options object, so no defaultValue: a missing key renders
                # raw on screen, which reports itself. Out of scope, like the
                # orphan guard's own out-of-scope rule and for the same reason.
                continue
            body = _options_body(rest, opening.end() - 1)
            if body is None or "defaultValue" not in body:
                continue
            if static_prefix(raw):
                sites.template.append((posix, raw))
            else:
                sites.headless.append((posix, raw))

        for match in _VAR_HEAD.finditer(text):
            body = _options_body(text, match.end() - 1)
            if body is None or "defaultValue" not in body:
                continue
            sites.variable.append((posix, match.group(1)))

        lines = text.splitlines()
        for i, line in enumerate(lines):
            window = "\n".join(lines[max(0, i - _PAIR_WINDOW) : i + _PAIR_WINDOW + 1])
            for match in _SUFFIX_PAIR_KEY.finditer(line):
                stem = match.group(1)
                # No quote required after the colon: a guide writes the English
                # on the line below its `introDefault:`, and demanding the
                # opening quote on the same line would drop exactly the long
                # values most worth checking.
                if re.search(rf"\b{re.escape(stem)}Default\s*:", window):
                    sites.suffix_pairs.append((posix, i + 1, match.group(3), stem))

            for match in _SIBLING_KEY.finditer(line):
                stem = match.group(1)
                if re.search(rf"\b{re.escape(stem)}\s*:\s*['\"]", window):
                    sites.sibling.append((posix, i + 1, match.group(3), stem))

            default = _DEFAULT_FIELD.search(line)
            if default is None:
                continue
            keyfield = _KEY_FIELD.search(line) or _KEY_FIELD.search(window)
            if keyfield:
                sites.pairs.append((posix, i + 1, keyfield.group(3), default.group(3)))
            else:
                sites.unpaired.append((posix, i + 1))
    return sites


def read_en(en_path: str) -> set[str]:
    with open(en_path, encoding="utf-8") as fh:
        return set(_KEY_LINE.findall(fh.read()))


def _base_of(stem: str, by_locale: dict[str, set[str]]) -> str | None:
    """The language file a regional variant resolves through, if there is one.

    Duplicated from check_i18n_orphan_keys.py rather than imported: the two
    scripts already duplicate _options_body and _KEY_LINE for the same
    reason, one script per concern, neither depending on the other's shape.
    """
    if "-" not in stem:
        return None
    base = stem.split("-", 1)[0]
    return base if base in by_locale else None


def read_locale_keys(locale_glob: str) -> dict[str, set[str]]:
    """Map locale stem to the set of keys that locale file declares."""
    by_locale: dict[str, set[str]] = {}
    for path in sorted(glob.glob(locale_glob)):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in {"index", "types"}:
            continue
        with open(path, encoding="utf-8") as fh:
            by_locale[stem] = set(_KEY_LINE.findall(fh.read()))
    return by_locale


def _reach(key: str, by_locale: dict[str, set[str]]) -> set[str]:
    """Locales that can answer this key, bare form or any CLDR plural form.

    A member found in en.ts can itself be one plural form, `x_one`, because
    the template prefix matches every form English declares. The reader's
    i18next never asks for `x_one` by that name: it asks for `x` with a count
    and picks the form its own language uses. ja, ko, th, vi, zh and id have
    only `other`, so a member `x_one` is answered there by `x_other`, and
    demanding `x_one` would ask those files for a form their language never
    looks up. Whether a language holds every category it needs is
    check_i18n_plural_forms.py's question, not this one's.
    """
    base = next((key[: -len(s)] for s in _CLDR_SUFFIXES if key.endswith(s)), key)
    forms = (key, base, *(base + suffix for suffix in _CLDR_SUFFIXES))
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
    not, the same rule the orphan guard applies to literal keys.

    A locale classified as in-progress (see classify_locales) is excluded the
    same way: not because the gap is answered, but because it is not this
    check's job to enforce a file nobody has finished and nobody is showing.
    downgraded_locales reports exactly what was excluded, so the exclusion is
    never silent even though it is not an error.
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
    """In-progress locales this key's English default would still reach."""
    reach = _reach(key, by_locale)
    return sorted(stem for stem in in_progress if stem not in reach and bases[stem] not in reach)


def read_supported_languages(path: str = DEFAULT_I18N_TS_PATH) -> set[str]:
    """Locale codes the language picker actually offers.

    Duplicated from check_i18n_orphan_keys.py rather than imported, for the
    same reason the rest of this file's helpers are.

    A locale can leave SUPPORTED_LANGUAGES two ways, and both have to read as
    absent here. mn's entry was deleted outright. uz's was commented out in
    place, `// { code: 'uz', ... },`, so the literal text `code: 'uz'` is
    still sitting in the file. A regex blind to `//` would match it anyway
    and keep enforcing uz as supported for the wrong reason. Each line is cut
    at its first `//` before matching, which is safe for this array because
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


def read_en_values(en_path: str) -> dict[str, str]:
    with open(en_path, encoding="utf-8") as fh:
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
    locale_glob: str,
) -> tuple[set[str], dict[str, float], set[str]]:
    """Split locales outside SUPPORTED_LANGUAGES into in-progress and abandoned.

    A locale in SUPPORTED_LANGUAGES is not classified at all: it is offered to
    a user today, so every gap in it stays a hard error no matter how
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--en", default=DEFAULT_EN_PATH)
    parser.add_argument("--src", default=DEFAULT_SOURCE_GLOB)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--locales", default=DEFAULT_LOCALE_GLOB)
    parser.add_argument("--member-baseline", default=DEFAULT_MEMBER_BASELINE_PATH)
    parser.add_argument("--suffix-baseline", default=DEFAULT_SUFFIX_BASELINE_PATH)
    parser.add_argument("--i18n-ts", default=DEFAULT_I18N_TS_PATH)
    args = parser.parse_args(argv)

    try:
        keys = read_en(args.en)
    except FileNotFoundError:
        print(f"ERROR: no English bundle at {args.en!r}", file=sys.stderr)
        return 2
    if not keys:
        print(
            f"ERROR: {args.en} parsed to zero keys. The key regex is double-quote "
            "only; a file written any other way drops out of this scan silently, "
            "so an empty parse is a broken scan rather than a clean one.",
            file=sys.stderr,
        )
        return 2

    by_locale = read_locale_keys(args.locales)
    if not by_locale:
        print(f"ERROR: no files matched {args.locales!r}", file=sys.stderr)
        return 2
    empty_locales = sorted(stem for stem, ks in by_locale.items() if not ks)
    if empty_locales:
        print(
            f"ERROR: {len(empty_locales)} locale file(s) parsed to zero keys: "
            f"{', '.join(empty_locales)}. Same double-quote-only blind spot as "
            "en.ts above; an empty parse is a broken scan, not a clean one.",
            file=sys.stderr,
        )
        return 2

    sites = collect(args.src)
    if not (sites.template or sites.variable or sites.pairs or sites.headless):
        print(
            f"ERROR: no computed-key call sites found under {args.src!r}. "
            "Finding nothing and not having looked must not print the same result.",
            file=sys.stderr,
        )
        return 2

    try:
        with open(args.baseline, encoding="utf-8") as fh:
            baseline = set(json.load(fh))
    except FileNotFoundError:
        baseline = set()

    # ---- decidable: a template prefix no key in en.ts begins with ----
    where: dict[str, list[str]] = {}
    for posix, raw in sites.template:
        where.setdefault(static_prefix(raw), []).append(posix)

    empty = {p: files for p, files in where.items() if not any(k.startswith(p) for k in keys)}
    new_prefixes = sorted(set(empty) - baseline)

    # A prefix leaves the debt list for two unrelated reasons and the message has
    # to say which, because it is the instruction someone follows when editing
    # the baseline. `empty` is built from the prefixes found at call sites right
    # now, so `baseline - empty` would report a family whose last call site was
    # deleted as "answered by en.ts", which is a false statement about the locale
    # file. Ask en.ts directly for that claim, and call the other case what it is.
    answered = sorted(p for p in baseline if any(k.startswith(p) for k in keys))
    vanished = sorted(p for p in baseline - set(answered) if p not in where)

    # ---- decidable, and previously left unchecked: for a prefix en.ts DOES
    # answer, does every OTHER locale carry every one of its concrete members
    # ----
    answered_prefixes = sorted(p for p in where if p not in empty)
    bases = {stem: _base_of(stem, by_locale) for stem in by_locale}

    supported = read_supported_languages(args.i18n_ts)
    if "en" not in supported:
        # "en" is structurally the first entry of SUPPORTED_LANGUAGES, so its
        # absence means the array was not found or nothing inside it parsed,
        # not that English was ever dropped from the picker. A silent empty
        # set would classify every locale as unsupported and start
        # downgrading member gaps this check exists to keep enforced, uz
        # among them, which would go green for exactly the wrong reason.
        print(
            f"ERROR: could not read SUPPORTED_LANGUAGES from {args.i18n_ts}. "
            "An empty or unparsed read here is not a clean read: it would "
            "classify every locale as unsupported and start downgrading "
            "member gaps this check exists to enforce.",
            file=sys.stderr,
        )
        return 2
    en_values = read_en_values(args.en)
    in_progress, fractions, abandoned = classify_locales(by_locale, supported, en_values, args.locales)
    in_progress = frozenset(in_progress)

    member_gaps: dict[str, dict[str, list[str]]] = {}  # prefix -> locale -> keys
    member_counts: dict[str, int] = {}
    downgraded: dict[str, list[str]] = {}
    for prefix in answered_prefixes:
        members = sorted(k for k in keys if k.startswith(prefix))
        member_counts[prefix] = len(members)
        for key in members:
            for stem in missing_locales(key, by_locale, bases, in_progress):
                member_gaps.setdefault(prefix, {}).setdefault(stem, []).append(key)
            for stem in downgraded_locales(key, by_locale, bases, in_progress):
                downgraded.setdefault(stem, []).append(key)

    try:
        with open(args.member_baseline, encoding="utf-8") as fh:
            member_baseline: dict[str, dict] = json.load(fh)
    except FileNotFoundError:
        member_baseline = {}

    new_member_gaps: list[tuple[str, dict[str, list[str]]]] = []
    widened_member_gaps: list[tuple[str, dict[str, list[str]]]] = []
    for prefix, by_stem in member_gaps.items():
        entry = member_baseline.get(prefix)
        if entry is None:
            new_member_gaps.append((prefix, by_stem))
            continue
        declared = {stem: set(ks) for stem, ks in entry.get("missing", {}).items()}
        widened = {stem: sorted(set(ks) - declared.get(stem, set())) for stem, ks in by_stem.items()}
        widened = {stem: ks for stem, ks in widened.items() if ks}
        if widened:
            widened_member_gaps.append((prefix, widened))

    member_healed = sorted(p for p in member_baseline if p not in member_gaps)

    # ---- decidable: a table key absent from en.ts ----
    missing_pairs = [p for p in sites.pairs if p[2] not in keys]

    # ---- decidable, and previously in no bucket at all: the `<x>Key` beside
    # `<x>Default` shape. Two questions, asked separately because the answers
    # are nothing alike: is the key in en.ts, and can every locale answer it.
    # ----
    suffix_scope = [p for p in sites.suffix_pairs if not p[2].startswith(_SUFFIX_PAIR_EXCLUDED)]
    suffix_absent: dict[str, set[str]] = {}  # family prefix -> keys absent from en.ts
    suffix_present: set[str] = set()
    for _posix, _line, key, _stem in suffix_scope:
        if key in keys:
            suffix_present.add(key)
        else:
            suffix_absent.setdefault(family_prefix(key), set()).add(key)

    try:
        with open(args.suffix_baseline, encoding="utf-8") as fh:
            suffix_baseline: dict[str, dict] = json.load(fh)
    except FileNotFoundError:
        suffix_baseline = {}

    # A count rather than the key list: 1520 keys spelled out is a file nobody
    # reads, and the count is a property of the family alone, so it survives a
    # rename inside the family the way an exact set would not. What it does NOT
    # catch is a swap, one key out and one in, which leaves the count
    # untouched; that is the same blind spot the leak guard's own ceiling
    # documents, and the diff is where a swap stays visible.
    new_suffix_families: list[tuple[str, list[str]]] = []
    for prefix, family in sorted(suffix_absent.items()):
        if prefix not in suffix_baseline:
            new_suffix_families.append((prefix, sorted(family)))

    # Every baselined family is asked one question, how many of its keys en.ts
    # still fails to answer, and any answer other than the recorded one is an
    # error whichever way it moved. A count left at 15 after 10 of those keys
    # landed in en.ts is 10 slots a later addition would spend in silence,
    # which is what the leak guard's ceiling fails on `<` to prevent. The
    # reason belongs in the message because it is the instruction someone
    # follows when editing the baseline, and a family drops out of
    # `suffix_absent` for two unrelated reasons: en.ts answered its keys, or
    # the call sites that declared them are gone. `suffix_absent` is built from
    # the tree as it stands, so calling the second case the first would print a
    # false statement about en.ts, which is the trap the prefix baseline above
    # had to sidestep in the same way.
    suffix_seen = {family_prefix(key) for _posix, _line, key, _stem in suffix_scope}
    stale_suffix_families: list[tuple[str, int, int, str]] = []
    for prefix, entry in sorted(suffix_baseline.items()):
        was = int(entry.get("keys", 0))
        now = len(suffix_absent.get(prefix, ()))
        if now == was:
            continue
        if prefix in suffix_absent:
            reason = "grew" if now > was else "shrank"
        else:
            # Decided on the call sites rather than on en.ts, because "gone" is
            # a claim about the code and only `suffix_seen` can carry it. The
            # two are not interchangeable: a family whose guide file was
            # deleted has no absent keys either, and announcing that as en.ts
            # having answered it would be a false statement about a locale file
            # nobody touched.
            reason = "answered" if prefix in suffix_seen else "gone"
        stale_suffix_families.append((prefix, was, now, reason))

    # The second question. A key the English bundle DOES answer is a literal
    # like any other, so every locale that has to carry it is asked for it,
    # exactly as the orphan guard asks. This one gets no baseline: it had zero
    # findings when it was written, so the next break of this shape fails on
    # arrival rather than being absorbed by a list.
    suffix_locale_gaps: dict[str, list[str]] = {}
    for key in sorted(suffix_present):
        gap = missing_locales(key, by_locale, bases, in_progress)
        if gap:
            suffix_locale_gaps[key] = gap

    # ---- what could not be decided, printed rather than dropped ----
    print(
        f"computed-key scan: {len(sites.template)} template call site(s) over "
        f"{len(where)} prefix(es), {len(sites.variable)} variable-key call site(s), "
        f"{len(sites.pairs)} resolvable key/default pair(s), "
        f"{len(sites.suffix_pairs)} <x>Key/<x>Default pair(s), against "
        f"{len(keys)} keys in {args.en}"
    )
    print("\nNOT CHECKED, and no clean exit below covers any of it:")
    print(
        f"  {len(sites.variable):5d} call site(s) take their key from a variable. The key "
        "is not\n        knowable here at all unless it also appears in a table below."
    )
    for expr, n in Counter(e for _, e in sites.variable).most_common(10):
        print(f"          {n:4d}  t({expr}, {{ defaultValue ... }})")
    print(f"  {len(sites.headless):5d} template key(s) begin with an interpolation and so have no static prefix.")
    for posix, raw in sites.headless[:5]:
        print(f"          {posix}: `{raw}`")
    incomplete = sorted(set(member_gaps))
    print(
        f"  {len(where) - len(empty):5d} prefix(es) DO have members in en.ts.\n"
        f"  {len(incomplete):5d} of those have a member some other locale does "
        "not answer, checked below like a literal key."
    )
    print(
        f"  {len(sites.unpaired):5d} default* line(s) carry no key field within "
        f"{_PAIR_WINDOW} lines. Sampled and mostly\n        benign: the key is a template at the "
        "call site, already counted above."
    )
    for posix, line in sites.unpaired[:5]:
        print(f"          {posix}:{line}")
    print(
        f"  {len(sites.sibling):5d} key field(s) keep their English in a sibling field rather "
        "than a\n        default* one, so no pair forms here and none of them are counted above."
    )
    for stem, n in Counter(s for _, _, _, s in sites.sibling).most_common(5):
        print(f"          {n:4d}  {stem}Key beside {stem}")
    print("        The module chips among those are owned by check_case_module_chip_locales.py.")
    excluded = len(sites.suffix_pairs) - len(suffix_scope)
    print(
        f"  {excluded:5d} <x>Key/<x>Default pair(s) are cases.* content keys, "
        "deliberately absent from\n        en.ts and not asked about here; their locale "
        "coverage is owned by\n        check_case_module_chip_locales.py."
    )

    # Printed unconditionally, pass or fail, same as the orphan guard: a
    # locale excluded here is a gap that is not being enforced, and that must
    # never look the same as a gap that does not exist.
    if in_progress:
        print(
            f"\n{len(in_progress)} locale(s) outside SUPPORTED_LANGUAGES read as "
            "mid-translation and are not enforced by this check:"
        )
        for stem in sorted(in_progress):
            n = len(downgraded.get(stem, []))
            print(
                f"  {stem}: {fractions[stem] * 100:.1f}% of shared keys still "
                f"identical to English, {n} member gap(s) not enforced"
            )
    else:
        print("\n0 locale(s) outside SUPPORTED_LANGUAGES read as mid-translation.")
    if abandoned:
        print(
            f"{len(abandoned)} locale(s) outside SUPPORTED_LANGUAGES read as finished "
            "but are not offered to anyone; their gaps are enforced below like any "
            f"other locale, since nothing else is tracking that file's completion: "
            f"{', '.join(sorted(abandoned))}"
        )
    else:
        print("0 locale(s) outside SUPPORTED_LANGUAGES read as an abandoned, unoffered file.")

    if answered:
        print(
            f"\n{len(answered)} baselined prefix(es) now have members in en.ts; "
            f"remove them from {args.baseline}: {', '.join(answered)}"
        )
    if vanished:
        print(
            f"\n{len(vanished)} baselined prefix(es) no longer appear at any call site, so "
            "nothing renders them and they are not evidence about en.ts either way; remove "
            f"them from {args.baseline}: {', '.join(vanished)}"
        )
    if member_healed:
        shown = ", ".join(member_healed[:12])
        more = f", and {len(member_healed) - 12} more" if len(member_healed) > 12 else ""
        print(
            f"\n{len(member_healed)} member-baselined prefix(es) now have every member in "
            f"every locale that needs one; remove them from {args.member_baseline}: "
            f"{shown}{more}"
        )

    if (
        not new_prefixes
        and not missing_pairs
        and not new_member_gaps
        and not widened_member_gaps
        and not new_suffix_families
        and not stale_suffix_families
        and not suffix_locale_gaps
    ):
        # Say how much was compared, not just that it passed. A gate that prints
        # OK without a count reads the same whether it checked everything or
        # walked an empty tree, and this repo has already had a tree walk that
        # visited zero files and exited clean.
        still_short = len(member_baseline) - len(member_healed)
        print(
            f"\ncomputed i18n keys OK: {len(where)} template prefix(es) checked, "
            f"{len(where) - len(empty)} answered by en.ts and {len(empty)} still baselined, "
            f"no new ones; {len(sites.pairs)} key/default pair(s) verified against "
            f"{len(keys)} keys in {args.en}; {len(answered_prefixes)} answered prefix(es) "
            f"checked member by member against {len(by_locale)} locales, {still_short} "
            "still short of full coverage per the member baseline, no new gaps; "
            f"{len(suffix_scope)} <x>Key/<x>Default pair(s) over "
            f"{len(suffix_present)} key(s) en.ts answers, each checked against "
            f"{len(by_locale)} locales, and {sum(len(f) for f in suffix_absent.values())} "
            f"key(s) in {len(suffix_absent)} family(ies) it does not, all baselined, "
            "every recorded count still exact."
        )
        return 0

    for prefix in new_prefixes:
        files = sorted(set(empty[prefix]))
        print(
            f"ERROR: no key in {args.en} begins with {prefix!r}, so every member of "
            f"that family falls back to its English default ({len(empty[prefix])} call site(s))",
            file=sys.stderr,
        )
        for name in files[:3]:
            print(f"  called from {name}", file=sys.stderr)

    for posix, line, key, default in missing_pairs:
        print(
            f"ERROR: {key} is paired with the default {default!r} but no key by that name is in {args.en}",
            file=sys.stderr,
        )
        print(f"  declared at {posix}:{line}", file=sys.stderr)

    where_declared = {key: (p, ln) for p, ln, key, _ in suffix_scope}
    for prefix, family in new_suffix_families:
        posix, ln = where_declared[family[0]]
        print(
            f"ERROR: {len(family)} key(s) under {prefix!r} pair a <x>Key with an "
            f"<x>Default and no key by those names is in {args.en}, so the family "
            "renders its English default in every language",
            file=sys.stderr,
        )
        print(f"  first declared at {posix}:{ln}, e.g. {family[0]}", file=sys.stderr)

    for prefix, was, now, reason in stale_suffix_families:
        if reason == "grew":
            what = (
                f"grew from {was} to {now} key(s) absent from {args.en}. "
                f"{args.suffix_baseline} records existing debt only and may only shrink."
            )
        elif reason == "shrank":
            what = (
                f"is down to {now} key(s) absent from {args.en} from the {was} recorded. "
                f"Lower `keys` to {now} in {args.suffix_baseline} now that "
                f"{was - now} of them landed, so the entry carries no slack a later "
                "addition could spend in silence."
            )
        elif reason == "answered":
            what = (
                f"is answered by {args.en} in full, so none of its {was} recorded key(s) "
                f"are still absent. Remove the entry from {args.suffix_baseline}."
            )
        else:
            what = (
                f"is declared at no call site any more, so its {was} recorded key(s) are "
                f"debt this tree no longer carries. Remove the entry from "
                f"{args.suffix_baseline}. This is not a statement that {args.en} answers "
                "them: it says the code that read them is gone."
            )
        print(f"ERROR: {prefix!r} {what}", file=sys.stderr)

    for key, gap in suffix_locale_gaps.items():
        posix, ln = where_declared[key]
        print(
            f"ERROR: {key} is in {args.en} but {len(gap)} locale(s) cannot answer it, "
            f"so those readers get its English default: {', '.join(gap)}",
            file=sys.stderr,
        )
        print(f"  declared at {posix}:{ln}", file=sys.stderr)

    if new_suffix_families or stale_suffix_families or suffix_locale_gaps:
        print(
            "\nThese keys are read through a variable at the call site, "
            "`t(content.titleKey, { defaultValue: content.titleDefault })`, so the "
            "orphan guard cannot see them: its regex requires a literal key. The key "
            "is still a literal where the table declares it, which is why it can be "
            "checked here at all. Add the family to en.ts and then to the other "
            "locales. Do not silence this by dropping the defaultValue, which turns a "
            "silent English string into a raw key on screen.",
            file=sys.stderr,
        )

    if new_prefixes or missing_pairs:
        print(
            "\nA key built at runtime and answered by no English bundle renders its "
            "defaultValue in every one of our languages, and the orphan guard cannot "
            "see it: its call-site regex requires a literal key, which is exactly what "
            "these call sites do not have. Add the family to en.ts and then to the other "
            "locales. Do not silence this by dropping the defaultValue, which turns a "
            f"silent English string into a raw key on screen. {args.baseline} records "
            "existing debt only and may only shrink.",
            file=sys.stderr,
        )

    for prefix, by_stem in new_member_gaps:
        key_to_missing: dict[str, list[str]] = {}
        for stem, member_keys in by_stem.items():
            for key in member_keys:
                key_to_missing.setdefault(key, []).append(stem)
        for key in sorted(key_to_missing):
            missing = sorted(key_to_missing[key])
            print(
                f"ERROR: {key} is one of {member_counts[prefix]} member(s) of "
                f"{prefix!r}, answered by {args.en}, but is answered by no locale "
                f"file it needs ({len(by_locale) - len(missing)}/{len(by_locale)})",
                file=sys.stderr,
            )
            print(f"  missing: {', '.join(missing)}", file=sys.stderr)

    for prefix, widened in widened_member_gaps:
        for stem, member_keys in widened.items():
            print(
                f"ERROR: {prefix!r} lost coverage {args.member_baseline} did not record: "
                f"{stem} no longer answers {', '.join(sorted(member_keys))}",
                file=sys.stderr,
            )

    if new_member_gaps or widened_member_gaps:
        print(
            "\nOnce en.ts answers a computed-key family, its members stop being "
            "hypothetical: they are literal dictionary entries, and every other "
            "locale owes each of them exactly as it owes a literal call-site key. "
            '"Answered" used to mean en.ts alone; a member missing from any other '
            "locale falls back to English there just as silently as an unanswered "
            f"prefix does. Add the member to the locales named above. "
            f"{args.member_baseline} records existing debt only and may only shrink.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
