#!/usr/bin/env python3
"""i18n leak guard: block new locale values that are byte-identical to en.ts.

On 2026-07-26, six commits added 422 keys across 11 modules to all 29 locale
files (five titled "translate the X panel...", one an ordinary feature commit,
feat(progress), that happened to add keys along the way — the mechanism is any
commit that adds locale keys, not a labelled i18n commit). Each wrote a real
Russian value and copied the literal English source string into the other 27
locale files. Two of the six commit bodies self-admitted it ("English
everywhere and Russian in ru.ts"); the other four said nothing about it at
all, so commit text is not a reliable way to find this class of bug. Every
key existed and every coverage check passed, because the string was present -
it was just the wrong string. 11360 cells shipped this way and sat unnoticed
until #181's translation work found the first one by hand.

The fingerprint that finds this class of bug without knowing any of the 27
languages: a genuine translation produces uneven, locale-specific counts of
values that happen to equal English (0-6, varying key to key and locale to
locale - short technical nouns, codes, abbreviations coincide sometimes). A
leak produces the same count in every affected locale, with translated ru
the sole exception. Uniformity is the signal. Generalised threshold: flag any
key identical to en.ts in at least 24 of the 28 non-en locales.

This guard runs that scan across the WHOLE of en.ts on every run, not just a
recheck of already-known debt, and requires every flagged key to land in
exactly one of two separate, never-merged lists:

  * i18n_leak_allowlist.json - keys identical to en on purpose (abbreviations,
    standards codes, product names, template-only strings, shortcuts, regex
    patterns...). Its tell is identical in EVERY locale, ru included. Each
    entry carries a reason_category and, where the category alone doesn't
    explain it, a free-text note. Permanent; may only grow.

  * i18n_leak_baseline.json - the leaked cells as declared debt, each key
    mapped to the explicit SET of locales still leaked (not a count - a count
    cannot tell a repaired cell from a newly leaked one, and not a bare key
    list - a bare key goes green on the first repaired locale). May only
    shrink; more locales leaked than recorded is a regression and fails.

A flagged key in neither list is a NEW leak (or a previously-undiscovered
one) and fails the build. A third file, i18n_leak_pending_review.json, holds
a NAMED list of keys that don't fit either tell cleanly. Its entries are not
one shape: some are almost-universal matches where only 1-4 locales
genuinely differ (e.g. a founder's name transliterated in ar/ky but left in
Latin script everywhere else); others are the reverse, a short or ambiguous
term where only 1-2 locales happen to coincide with en and the rest of the
file genuinely differs, closer in shape to an allowlist candidate than to a
leak. Both shapes were filed here rather than triaged by content at the
time, and this file does not resolve which is which - see reason/added_by
below for what is actually known about each entry versus what is only
inferred from the commit that added it. Membership is checked by KEY NAME
against this list, never by recomputing
the shape (ru identical, a handful of others not) - a shape-based exemption
would silently wave through any future leak that happens to land in that
band, which defeats the guard's whole purpose. A flagged key that looks
pending-shaped but is not named in the list is unclassified and fails,
exactly like any other unrecognised hit. Named membership is informational
only: reported every run, never failing a key on its own, until a human
reclassifies it into baseline or allowlist, or fixes it for real.

Membership here is not free, though. Every entry carries a reason and an
added_by; this guard fails if either is missing or empty, because an entry
with neither is a claim nobody actually made. The list's own size is capped
by PENDING_REVIEW_CEILING below, a ratchet in the same idiom as
UNDER_TRANSLATION: adding an entry means raising that constant in the same
diff, a change a reviewer sees and can question, and removing an entry
(translated for real, reclassified into baseline or allowlist, or found not
to be a real ambiguity) means lowering it to match, so the ceiling never
carries slack a future addition could hide behind. For its first three
weeks (2026-08-02 to 2026-08-17) this list had none of that: it grew across
eight separate commits, 119 keys to 184, and never once shrank, because
nothing capped it and no entry recorded why it was there or who put it
there - a third state that read as neither a solved problem nor an open
one, and made the other two lists look more decided than they were just by
existing next to it. These two rules exist so that cannot happen again
unnoticed.

Two failure modes beyond "new leak" this guard also catches:

  * False repair by deletion. A key leaving a baseline entry's leaked-locale
    set only proves it stopped being byte-identical to en - and with
    fallbackLng=en, deleting the key from that locale file also stops the
    match while the user still sees English. A "healed" cell is only accepted
    if the key is still PRESENT in that locale file.

  * Parser desync. The key/value regex here is double-quote-only, the same
    blind spot tsc's own TS1117 duplicate check has (single-quoted or
    multi-line entries are invisible to it). If a locale file ever picks up
    such an entry, its keys silently drop out of this scan and the lane goes
    green on missing data - "found nothing" and "did not look" must not
    produce the same output. Locale files legitimately carry different key
    counts from en.ts (ru.ts alone parses ~3600 more keys than en.ts, because
    Russian's four CLDR plural categories - one/few/many/other - outnumber
    English's two - one/other - and every locale shows the same kind of
    gap), so cross-locale count comparison cannot be the check: it cannot
    tell "richer language" from "parser ate a third of the file." Instead,
    within EACH file, this guard matches a looser single-OR-double-quote
    pattern and fails on any KEY the strict double-quote parser missed,
    unless that exact key is named in _KNOWN_SINGLE_QUOTE_KEYS - an
    enumeration, not a count tolerance, because a count cannot tell a known
    exception from a new one hiding behind it.

Second detector: locale-set coherence, forward-only. The count threshold
above assumes a leak is still near-uniform; a leak whose repair stalled
partway, or that never reached 24/28 to begin with, sits below it and is
invisible to that scan. It was found anyway on 2026-08-02 by a different
tell: independent coincidence does not reproduce the same SET of locales
across multiple unrelated keys, a shared mechanism does. 9 costExplorer.*
keys shared one identical 14-locale set (found in the 12-23/28 band); a
follow-up pass restricted to prose values (>=5 words or a sentence
terminator - the property that actually separates real leaked prose from
short coincidental terms, not locale-set size) found a second cluster, 24
pipeline.* keys sharing an identical 5-locale set {bg, da, fi, no, sv},
traced to v3.12.1's own release notes ("Deferred to v3.12.2: Native i18n
pass for 17 placeholder locales" - a self-documented, partially-completed
deferral, the same honesty-in-the-commit-body-nobody-reads pattern as the
six 2026-07-26 commits). Both are now baseline debt.

Run without a floor, this rule is not a clean gate: across the whole
keyspace it produces ~140 clusters and ~2600 keys, and checking the large
ones by value showed most are not leaks - "Status" kept unchanged by
several unrelated locales across five unrelated modules, a day abbreviation
several locales coincidentally share, notification-template punctuation -
genuine coincidence at scale, structurally the same as an allowlisted
abbreviation, just clustered instead of solitary. Content, not set size,
separates the two classes, and content is not mechanically checkable at
scan time. So this detector does not re-triage the whole keyspace on every
run: i18n_leak_cluster_snapshot.json freezes the *shape* of every
locale-set that had >=3 non-listed member keys as of the seed date as
accepted, already-reviewed state. Going forward, a NEW locale-set crossing
the >=3-key threshold - one that was not part of the snapshot - fails,
naming the set and its members, so a future incident like costExplorer or
pipeline.* is caught in days, not weeks, at the moment 3 keys converge
rather than after dozens do. Growth of an already-accepted set (more
ordinary loanwords sharing an old, reviewed pattern) does not fail; that
would just be re-litigating a decision already made. A key that graduates
into allowlist/baseline/pending later drops out of both detectors
automatically, the same as any other classified key.

This guard does not repair anything and does not scan for real text in the
wrong sense (a byte comparison is structurally blind to e.g. mn's
field_jurisdiction, which holds real Mongolian text in the wrong sense - see
MEMORY) - that is a separately scoped, unbounded problem.

Not built here, design only, pending founder authorisation: a forward
check scoped to a commit's own diff rather than either detector's whole-
keyspace scan - any key a commit adds or changes must be present and
non-identical (or explicitly listed) in all 27 non-en locales, failing the
commit that introduces the gap instead of a later scan finding it. It
would reuse this file's parsing and the same three lists, comparing staged
en.ts against HEAD to find touched keys, with pending excluded from the
pass-path (pending resolves existing ambiguity, it should not wave through
a brand-new key). One trap already found: it must not require a literal
key-name match. Locale files legitimately carry keys en.ts has no
counterpart for - CLDR plural categories (e.g. an en `one`/`other` pair has
no `few`/`many` sibling to be "identical to", because en does not have
those categories at all) - so a name-for-name presence check would fail
every plural key anyone ever adds. It must match the CLDR plural FAMILY
(the shared base key stripped of its plural suffix), not the literal key
string, the same enumeration-not-tolerance discipline as
_KNOWN_SINGLE_QUOTE_KEYS below, or it will cry wolf on ordinary correct
work within a week of shipping.

Usage:
    python scripts/check_i18n_leak_baseline.py
    python scripts/check_i18n_leak_baseline.py --update-baseline

Exit code 0 means every flagged key is accounted for, no baseline entry
regressed, and no new locale-set cluster has formed. Exit code 1 means a new
leak, a baseline regression, a false repair, a parser-parity gap, a new
coherence cluster, a pending-review entry missing its reason or added_by, or
a pending-review ceiling out of step with the list's actual size was found.

--update-baseline rewrites the baseline to the currently observed leaked set
for keys already in it (shrink direction only - a key whose observed set grew
still fails first). Use this only after a deliberate, reviewed decision to
accept a repair - never as a way to turn a red check green without looking at
what it found.
"""

from __future__ import annotations

import glob
import json
import sys

LOCALE_GLOB = "frontend/src/app/locales/*.ts"
BASELINE_PATH = "scripts/i18n_leak_baseline.json"
ALLOWLIST_PATH = "scripts/i18n_leak_allowlist.json"
PENDING_PATH = "scripts/i18n_leak_pending_review.json"
CLUSTER_SNAPSHOT_PATH = "scripts/i18n_leak_cluster_snapshot.json"

THRESHOLD = 24  # hard count of locales rendering the en string, out of 42 non-en
CLUSTER_MIN_KEYS = 3  # locale-set coherence detector: >=N keys sharing one exact set

# A locale part-way through its first translation pass, and the number of en
# keys it already renders in its own words, measured by this file's own parser
# so the number means what this file means by it.
#
# Such a locale is majority-identical to en by construction rather than by any
# leak mechanism, and it breaks the coherence detector in a way that has nothing
# to do with the locale itself: that detector matches on the EXACT frozenset of
# locales sharing en's value, so one new half-translated locale joins the set of
# ~18k keys at once and every previously accepted cluster reads as brand new. uz
# arriving turned 92 reviewed clusters into 92 unrecognised ones covering 18289
# keys. Baselining those would have declared 18289 cells permanent debt to
# silence an artefact of set identity.
#
# So the coherence detector, and only that detector, computes its sets without
# these locales. The threshold detector still sees them, because a key identical
# to en in 24 of 28 locales is worth reading whoever is in the set.
#
# The recorded count is a ratchet and it counts TRANSLATED keys, which may only
# rise. Counting the leaked ones instead reads naturally and is wrong: en.ts
# grows, and every key added to it that the exempt locale already carries in
# English raises the leaked count without anyone having touched that locale. The
# first version of this ratchet did exactly that and went red in CI on other
# people's work within the hour. How many keys the locale renders in its own
# words is a property of the locale alone. It rises when translation lands and
# falls only when somebody removes a translation, which is the one thing worth
# forbidding here.
#
# Measure the number on the COMMITTED tree, which is what this guard reads when
# CI runs it. Taken off a working tree it is whatever that tree happens to hold,
# and this one was written from a disk carrying 1919 uz translations nobody had
# committed yet, so CI read a locale 1919 values poorer than the number claimed
# and the guard failed on a repository that had done nothing wrong:
#   git show HEAD:frontend/src/app/locales/uz.ts
UNDER_TRANSLATION: dict[str, int] = {
    "uz": 13878,
}

# How many named keys i18n_leak_pending_review.json may hold. This is the
# same idiom as UNDER_TRANSLATION above, applied to a list that has no live
# signal to ratchet against (a key's presence there is decided by name, not
# recomputed from any locale value), so the ceiling has to live here instead
# of being derived from the data. Adding an entry raises the file's actual
# count without touching this constant, which is exactly the silent growth
# this ceiling exists to catch - the person adding a key has to also raise
# this number, in the same diff, where a reviewer sees it change. It may
# only fall: resolving, reclassifying, or fixing an entry for real must
# lower this number to match, so it never carries slack a later addition
# could spend silently. From 2026-08-02 to 2026-08-17, with no ceiling and
# no required reason, this list went 119 -> 184 across eight commits without
# ever once shrinking; measure this on the COMMITTED tree, the same
# working-tree trap UNDER_TRANSLATION's own comment already names.
#
# What this constant does NOT catch, said here rather than only in the commit
# that introduced it: a swap. Remove one entry and add a different one in the
# same diff and the count is unchanged, so the ceiling stays satisfied and the
# new key arrives without anyone raising anything. What forces that key to
# justify itself is the reason and added_by requirement below, not this number.
# Closing the gap with the ceiling alone would mean pinning the set rather than
# its size, which is a digest a human has to recompute on every legitimate edit,
# or reading git history, which this guard does nowhere else. Neither was judged
# worth it while the swap is still visible in the diff to anyone reading it. If
# a swap ever does get through unnoticed, that judgement is the thing to revisit.
PENDING_REVIEW_CEILING = 188

import re

_PAIR = re.compile(r'^\s*"([a-zA-Z0-9_.\-]+)":\s*"((?:[^"\\]|\\.)*)"', re.MULTILINE)
# Same key position, but the opening/closing quote on either side may be
# single OR double, and the key is captured so a hit can be checked by name
# against _KNOWN_SINGLE_QUOTE_KEYS below. Used only to detect entries the
# strict parser above would miss (single-quoted keys/values, which are valid
# TypeScript and invisible to _PAIR) - never to extract values, since it does
# not know how to un-escape a single-quoted body.
_LOOSE_PAIR = re.compile(r"""^\s*['"]([a-zA-Z0-9_.\-]+)['"]:\s*['"]""", re.MULTILINE)
_ESCAPE = re.compile(r"\\(.)")

# Two keys, in exactly these two locale files, are legitimately written with
# a single-quoted value because the value itself contains a double-quoted
# substring (e.g. 'No steps match "{{query}}"') - every other locale escapes
# the inner quote instead and stays strict-parseable. This is the ONLY
# tolerance the parity guard below grants; a hidden entry anywhere else, or
# a third hidden key in these two files, fails outright. Enumerated by name
# rather than by count, because a count cannot tell a known exception from a
# new one hiding behind it.
_KNOWN_SINGLE_QUOTE_KEYS = {
    "en": {"pipeline.palette.no_match", "pipeline.inspector.summary_stub"},
    "ky": {"pipeline.palette.no_match", "pipeline.inspector.summary_stub"},
}


def _unescape(raw: str) -> str:
    return _ESCAPE.sub(lambda m: m.group(1), raw)


def _extract_pairs(text: str) -> dict[str, str]:
    return {k: _unescape(v) for k, v in _PAIR.findall(text)}


def _locale_stem(path: str) -> str:
    # "frontend/src/app/locales/es-MX.ts" -> "es-MX"
    return path.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".ts")


def _load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def _load_json_list(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return []


def _compute_clusters(
    pairs_by_locale: dict[str, dict[str, str]],
    en_pairs: dict[str, str],
    non_en: list[str],
    known_keys: set[str],
) -> dict[frozenset[str], list[str]]:
    """Group keys not already in one of the three named lists by the exact
    frozenset of non-en locales whose value is byte-identical to en. Keep
    only sets with >=CLUSTER_MIN_KEYS member keys - independent coincidence
    does not reproduce the same set across several keys, a shared mechanism
    does. Ignores set size entirely; content judgment happens once, at seed
    time (see i18n_leak_cluster_snapshot.json and the module docstring),
    not by recomputing a size or content rule on every run.
    """
    scanned = [s for s in non_en if s not in UNDER_TRANSLATION]
    by_set: dict[frozenset[str], list[str]] = {}
    for key, en_val in en_pairs.items():
        if key in known_keys:
            continue
        identical = frozenset(s for s in scanned if pairs_by_locale[s].get(key) == en_val)
        if not identical:
            continue
        by_set.setdefault(identical, []).append(key)
    return {s: sorted(ks) for s, ks in by_set.items() if len(ks) >= CLUSTER_MIN_KEYS}


def main() -> int:  # noqa: PLR0912, PLR0915 - one linear check, splitting it hides the sequencing
    update = "--update-baseline" in sys.argv

    paths = sorted(glob.glob(LOCALE_GLOB))
    if not paths:
        print(f"ERROR: no files matched {LOCALE_GLOB!r}", file=sys.stderr)
        return 1

    pairs_by_locale = {}
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            pairs_by_locale[_locale_stem(path)] = _extract_pairs(fh.read())
    if "en" not in pairs_by_locale:
        print("ERROR: en.ts not found among locale files", file=sys.stderr)
        return 1
    en_pairs = pairs_by_locale["en"]
    non_en = [s for s in pairs_by_locale if s != "en"]

    # The ratchet on every locale exempted from the coherence detector. It is
    # allowed to be mostly English today; it is not allowed to become more
    # English than it was when the exemption was written. Checked before
    # anything else, so an exemption that has started going backwards is the
    # first thing reported rather than something found after the detectors it
    # was meant to quieten.
    ratchet_failures: list[str] = []
    for locale, recorded in sorted(UNDER_TRANSLATION.items()):
        if locale not in pairs_by_locale:
            ratchet_failures.append(
                f"{locale} is named in UNDER_TRANSLATION but has no locale file; "
                f"remove the entry, an exemption for a file that is not here exempts nothing"
            )
            continue
        pairs = pairs_by_locale[locale]
        translated = sum(1 for key, en_val in en_pairs.items() if key in pairs and pairs[key] != en_val)
        leaked = sum(1 for key, en_val in en_pairs.items() if pairs.get(key) == en_val)
        if translated < recorded:
            ratchet_failures.append(
                f"{locale} now renders {translated} of en.ts's keys in its own words, down from the {recorded} "
                f"recorded when it was exempted. A translation in progress may only move forward; something "
                f"has replaced {recorded - translated} translated value(s) with the English."
            )
        elif leaked == 0:
            ratchet_failures.append(
                f"{locale} no longer holds any key identical to en.ts, so its translation pass is done; "
                f"remove it from UNDER_TRANSLATION so the coherence detector covers it again"
            )
    if ratchet_failures:
        print(f"ERROR: {len(ratchet_failures)} locale(s) exempted from the coherence detector are out of step:")
        for f in ratchet_failures:
            print(f"    {f}")
        return 1

    # --- parser parity guard: within each file, not across locales ------
    # Cross-locale count comparison would false-positive on legitimate CLDR
    # plural richness: ru.ts alone parses ~3600 more keys than en.ts because
    # Russian has four plural categories (one/few/many/other) where English
    # has two (one/other), and every other locale shows the same kind of
    # gap. Comparing counts between locale files cannot distinguish "this
    # locale is richer than English" from "this locale's parser silently ate
    # a third of the file" - both produce a big number. What this guard
    # checks instead: does the loose, quote-agnostic pattern find a KEY in a
    # file that the strict double-quote parser does not? If so, that entry
    # uses a quoting style _PAIR can't see, and this scan is silently blind
    # to it - the same blind spot tsc's TS1117 duplicate check has. Every
    # hidden key must be named in _KNOWN_SINGLE_QUOTE_KEYS above; nothing
    # else is tolerated, at any count, in any file.
    parity_failures: list[tuple[str, str]] = []
    for path in paths:
        stem = _locale_stem(path)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        strict_keys = set(pairs_by_locale[stem])
        loose_keys = set(_LOOSE_PAIR.findall(text))
        hidden = loose_keys - strict_keys
        unexpected = hidden - _KNOWN_SINGLE_QUOTE_KEYS.get(stem, set())
        for key in sorted(unexpected):
            parity_failures.append((stem, key))
    if parity_failures:
        print(
            "ERROR: locale file entries are invisible to the strict double-quote "
            "scan this guard relies on, and are not one of the named, known "
            "exceptions:",
            file=sys.stderr,
        )
        for stem, key in parity_failures:
            print(f"  {stem}: {key!r}", file=sys.stderr)
        print(
            "\nThis usually means a single-quoted or multi-line entry (valid "
            "TypeScript, invisible to this regex and to tsc's TS1117 duplicate "
            "check alike). Either fix the entry's quoting, or - if it is "
            "deliberately single-quoted for the same reason as the two keys "
            "already named above - add it to _KNOWN_SINGLE_QUOTE_KEYS by name, "
            "not by raising a count. This guard cannot see what it did not "
            "parse, so trust nothing it reports until this is resolved.",
            file=sys.stderr,
        )
        return 1

    allowlist: dict[str, dict] = _load_json(ALLOWLIST_PATH)
    baseline: dict[str, dict] = _load_json(BASELINE_PATH)
    pending: dict[str, dict] = _load_json(PENDING_PATH)

    # --- pending-review integrity: reason/added_by required, ceiling enforced --
    # Checked before the general scan, and before anything in pending is used to
    # exempt a flagged key, so a malformed or drifted list is reported on its
    # own rather than mixed in with unrelated leak findings.
    pending_failures: list[str] = []
    for key in sorted(pending):
        entry = pending[key]
        if not entry.get("reason"):
            pending_failures.append(
                f"{key}: missing or empty 'reason' - an entry with no reason is a claim nobody made"
            )
        if not entry.get("added_by"):
            pending_failures.append(f"{key}: missing or empty 'added_by' - record who put it there")
    if len(pending) > PENDING_REVIEW_CEILING:
        pending_failures.append(
            f"list holds {len(pending)} keys, above the recorded ceiling of {PENDING_REVIEW_CEILING} - a new "
            "entry joined without raising PENDING_REVIEW_CEILING in the same diff. If it is a real new "
            "ambiguity: give it a reason and an added_by, and raise the constant to match, in this commit."
        )
    elif len(pending) < PENDING_REVIEW_CEILING:
        pending_failures.append(
            f"list holds {len(pending)} keys, below the recorded ceiling of {PENDING_REVIEW_CEILING} - lower "
            "PENDING_REVIEW_CEILING in scripts/check_i18n_leak_baseline.py to match now that one or more "
            "entries left, so the ceiling carries no slack a future addition could spend silently."
        )
    if pending_failures:
        print(f"ERROR: {len(pending_failures)} problem(s) with {PENDING_PATH}:", file=sys.stderr)
        for f in pending_failures:
            print(f"    {f}", file=sys.stderr)
        return 1

    # --- general scan across the whole of en.ts -------------------------
    flagged: dict[str, list[str]] = {}
    for key, en_val in en_pairs.items():
        identical = [s for s in non_en if pairs_by_locale[s].get(key) == en_val]
        if len(identical) >= THRESHOLD:
            flagged[key] = identical

    unclassified: list[tuple[str, list[str]]] = []
    new_leaks: list[tuple[str, str]] = []
    false_repairs: list[tuple[str, str]] = []
    healed: list[tuple[str, str]] = []

    for key, identical in flagged.items():
        if key in allowlist:
            continue  # permanent, no shrink/growth requirement
        if key in baseline:
            entry = baseline[key]
            known_leaked = set(entry.get("leaked_locales", []))
            current_leaked = {s for s in identical if s != "ru"}
            for stem in sorted(current_leaked - known_leaked):
                new_leaks.append((key, stem))
            for stem in sorted(known_leaked - current_leaked):
                # A cell leaving the leaked set only proves it stopped matching
                # en - confirm the key is still present in that locale, or a
                # deletion (not a translation) is masquerading as a repair.
                if key not in pairs_by_locale[stem]:
                    false_repairs.append((key, stem))
                else:
                    healed.append((key, stem))
            continue
        if key in pending:
            continue  # informational only, reported below
        unclassified.append((key, identical))

    # --- second detector: locale-set coherence, forward-only ------------
    known_keys = set(allowlist) | set(baseline) | set(pending)
    clusters = _compute_clusters(pairs_by_locale, en_pairs, non_en, known_keys)
    cluster_snapshot = _load_json_list(CLUSTER_SNAPSHOT_PATH)
    known_sets = {frozenset(entry["locale_set"]) for entry in cluster_snapshot}
    new_clusters = {s: ks for s, ks in clusters.items() if s not in known_sets}

    if healed:
        print(f"{len(healed)} baseline cell(s) no longer byte-identical to en (repaired, not a failure):")
        for key, stem in healed[:20]:
            print(f"  {key} / {stem}")
        if len(healed) > 20:
            print(f"  ... and {len(healed) - 20} more")
        print()

    if pending:
        print(f"{len(pending)} key(s) in the pending-review list (informational, not gated):")
        for key in sorted(pending)[:10]:
            print(f"  {key}")
        if len(pending) > 10:
            print(f"  ... and {len(pending) - 10} more")
        print()

    failed = False

    if false_repairs:
        failed = True
        print(
            f"ERROR: {len(false_repairs)} baseline cell(s) left the leaked set by DELETION, not translation:",
            file=sys.stderr,
        )
        for key, stem in false_repairs:
            print(f"  {key} / {stem} - key no longer present in that locale file", file=sys.stderr)
        print(
            "\nWith fallbackLng=en the user still sees English either way. "
            "Translate the key in that locale; do not remove it.",
            file=sys.stderr,
        )

    if new_leaks:
        failed = True
        print(f"ERROR: {len(new_leaks)} baseline cell(s) regressed (leaked in a locale not recorded):", file=sys.stderr)
        for key, stem in new_leaks:
            print(f"  {key} / {stem} = {en_pairs[key]!r}", file=sys.stderr)

    if unclassified:
        failed = True
        print(
            f"ERROR: {len(unclassified)} key(s) identical to en.ts in >= {THRESHOLD}/{len(non_en)} "
            "locales and not in any of the three lists:",
            file=sys.stderr,
        )
        for key, identical in sorted(unclassified):
            print(f"  {key}  n={len(identical)}  en={en_pairs[key]!r}", file=sys.stderr)
        print(
            "\nIf this is a real new leak: translate it (and its whole family - a "
            "leak this shape has never come alone) for real, in every locale, or "
            "add it to i18n_leak_baseline.json as declared debt with its exact "
            "leaked-locale set.\n"
            "If this is deliberately-identical text (unit abbreviation, standards "
            "code, product name, template-only string): add it to "
            "i18n_leak_allowlist.json with a reason_category, but only if it is "
            "identical in every locale including ru - if not, it belongs in "
            "i18n_leak_pending_review.json instead, unresolved.",
            file=sys.stderr,
        )

    if new_clusters:
        failed = True
        total_new_keys = sum(len(ks) for ks in new_clusters.values())
        print(
            f"ERROR: {len(new_clusters)} new locale-set cluster(s) ({total_new_keys} key(s)) "
            f"not present in {CLUSTER_SNAPSHOT_PATH} - {CLUSTER_MIN_KEYS}+ keys now share an "
            "identical-to-en locale set this repo has not seen before:",
            file=sys.stderr,
        )
        for s, ks in sorted(new_clusters.items(), key=lambda x: -len(x[1])):
            print(f"  set={sorted(s)}  n_keys={len(ks)}", file=sys.stderr)
            for k in ks:
                print(f"    {k} = {en_pairs[k]!r}", file=sys.stderr)
        print(
            "\nIndependent coincidence does not reproduce the same locale set across "
            "several keys; a shared mechanism does (this is how the costExplorer and "
            "pipeline.* leaks were found, both below the count threshold). Pull actual "
            "values in a member locale and a non-member locale before deciding: "
            "multi-sentence prose that matches byte-for-byte across unrelated scripts "
            "cannot coincide and belongs in i18n_leak_baseline.json; a short term or "
            "template convention several locales happen to share belongs in "
            "i18n_leak_allowlist.json (with the evidence, not just the count) or, if "
            "still ambiguous, i18n_leak_pending_review.json. Once classified, rerun "
            "with the keys removed from the unclassified set - they drop out of this "
            "detector automatically - or, if this cluster really is as harmless as most "
            "of the ~140 in the full unfiltered scan, add its locale_set to "
            f"{CLUSTER_SNAPSHOT_PATH} as accepted, reviewed state.",
            file=sys.stderr,
        )

    if failed:
        return 1

    if update:
        rebuilt = {}
        for key, entry in baseline.items():
            en_val = en_pairs.get(key)
            if en_val is None:
                continue
            current_leaked = sorted(s for s in non_en if s != "ru" and pairs_by_locale[s].get(key) == en_val)
            if current_leaked:
                rebuilt[key] = {"en_value": en_val, "leaked_locales": current_leaked}
        with open(BASELINE_PATH, "w", encoding="utf-8") as fh:
            json.dump(rebuilt, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print(f"Baseline rewritten: {len(rebuilt)} keys (was {len(baseline)}).")

    print(
        f"i18n leak guard OK: {len(baseline)} baseline keys, {len(allowlist)} allowlist keys, "
        f"{len(pending)} pending review, {len(cluster_snapshot)} accepted clusters, "
        "no new leaks, no regressions, no false repairs, no new clusters"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
