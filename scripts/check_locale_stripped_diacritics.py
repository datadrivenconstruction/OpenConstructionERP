#!/usr/bin/env python3
"""Locale diacritic ratchet: stop a new sentence shipping with its marks stripped.

Ten locale files ship strings that are the right words in the right order with
every diacritic deleted. The Swedish reads "En driftsattningskontroll utan ett
overenskommet godkannandevarde ar ett grael i vantan"; the French, "Arreter le
decompte final et liberer la retenue de garantie"; the Romanian, "Aceasta
inregistreaza plata ca o intrare imuabila in registru si inchide factura". They
were born that way - `git log -S` on the accented spelling returns nothing - so
they arrived in bulk translation commits and no gate has ever objected. Nothing
renders wrong, nothing fails to parse, the key is present and every coverage
check counts a string that is there. Only a reader of that language sees that
the text is not the language.

Repairing them is translation work and cannot be mechanical: a find/replace is
exactly what turned the German locale into `Qulle`, `Steur` and `zurst` (each
with an umlaut), which is what `check_locale_umlaut_folding.py` now guards. So
this gate does not try to fix anything. It holds the line: the strings already
in the baseline are declared debt, and no new one may join them.

How a string is judged
----------------------
Per file, and with no dictionary. A word counts as evidence when its unaccented
skeleton appears in this same file *only* ever spelled with the accent - if
`fran` and `från` both occur, `fran` proves nothing, because the file itself
uses the bare spelling somewhere. A value is reported when it carries no
diacritic at all, runs to at least six words, and at least three of them are
that kind of evidence. Both thresholds are conservative on purpose: this is a
heuristic and it is aimed at prose, not at "OK" or a units label.

The honest limit
----------------
That evidence rule is what makes the detector precise, and it is also what
makes it under-report, worst in the files that are worst damaged. A file's own
stripped strings supply the bare twins that disqualify words in its other
stripped strings. Measured instance: the Swedish
`cases.run_a_soft_landings_performance_handover.step.targets.why` is 32 words
of fully stripped Swedish that this detector does not report, because only
`overlamnandet` and `gor` qualified - `mal`, `ar` and `fran` each have a bare
twin elsewhere in `sv.ts`. Relaxing the rule is not the fix; without the
every-other-spelling condition it returns 2886 hits for `de.ts` and 3713 for
`es.ts`, neither of which is damaged at anything like that scale.

So a green run means "no new string crossed this detector's bar". It never
means "no new string was stripped".

The second rule: ask the rest of the file
-----------------------------------------
The limit above is not a reason to accept the blindness, because the file
carries a second, independent witness. Every key is filed under a top level
namespace, and the damage arrives per namespace, in whatever block a bulk
translation pass touched. So for each namespace the dictionary is every OTHER
namespace: a word is evidence when the rest of the file spells that skeleton
only ever accented, only ever one way, at least three times, and the namespace
under test writes it bare. The damaged strings never vote on their own
spelling, which is exactly what the first rule lets them do.

This is what the first rule cannot see, measured: `it.ts` shipped 689 stripped
words while the first rule reported nothing, because `attivita` occurs bare 44
times and those 44 disqualify it in all of them. The wider the damage, the
better it hides. The second rule does not care how often the damaged half
writes a word, only what the healthy half writes.

The two rules are complementary, and the numbers say so. Run against each file
as it stood at the commit before its repair, the first rule reports 1 string of
the French damage and the second 86; Romanian 0 and 112; Czech 0 and 248. The
Swedish is the other way round, 442 and 290, which is why the Swedish was the
damage that got noticed first.

What neither rule sees
----------------------
Both rules need the damage to be LOCAL: the first needs a clean twin somewhere
in the file, the second needs a clean namespace. Damage spread evenly over a
whole file defeats both, and that is not hypothetical. `it.ts` at the commit
before its repair scores 0 and 0, while actually shipping 689 stripped words,
because the Italian pass touched every namespace at once so no half of the file
was left clean enough to act as the dictionary.

The method that did find the Italian is a third one this script does not
implement: ask the language rather than the file, using a closed list of forms
that do not exist unaccented (`attivita`, `piu`, `perche`). It needs a
hand-checked word list per language and a homograph guard - `meta`, `unita`,
`sara` and the clitics are all real Italian words - so it is a different kind of
check with a different failure mode, and it is not a ratchet. If a locale is
ever repaired at that scale again, this is the gap to close.

When a repair makes this gate fail
----------------------------------
Repairing strings in a file removes bare twins from it, which promotes more
skeletons to evidence, which can make the detector see damage in that file it
could not see before. The newly listed strings are not false positives and the
gate is not misfiring: those strings were always broken and the repair is what
uncovered them. Fix them in the same pass if you can, or record them with
--update-baseline and read the diff. A locale that both lost and gained keys in
one run is this case, and the output says so.

Usage::

    python scripts/check_locale_stripped_diacritics.py
    python scripts/check_locale_stripped_diacritics.py --update-baseline

Exit code 0 means no key entered the set. Exit code 1 means at least one did,
and the output names every locale, key and string.
"""

from __future__ import annotations

import collections
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "frontend" / "src" / "app" / "locales"
BASELINE = Path(__file__).resolve().parent / "locale_stripped_diacritics_baseline.json"
NS_BASELINE = Path(__file__).resolve().parent / "locale_namespace_diacritics_baseline.json"

#: A value must be at least this many words before it is judged. Short values
#: are labels and units, where an absent accent is usually correct.
MIN_WORDS = 6

#: How many words of evidence a value needs. Three keeps single coincidences out.
MIN_EVIDENCE = 3

#: Cross namespace rule: how letters a word needs before it is judged. Below
#: four sit the articles and clitics, where the bare spelling is usually a
#: different real word - Portuguese `e` (and) against `é` (is), Italian the
#: same. A skeleton that collides with another real word cannot be judged by
#: spelling at all, only by reading, so this rule does not try.
NS_MIN_LEN = 4

#: Cross namespace rule: how often the rest of the file must spell a skeleton,
#: always accented and always the same single way, before its bare twin inside
#: one namespace counts as evidence.
NS_MIN_EVIDENCE = 3

#: Cross namespace rule: how many such words one value needs. Two keeps single
#: loanwords and proper nouns out.
NS_MIN_HITS = 2

_LINE = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"')
_WORD = re.compile(r"[0-9A-Za-zÀ-ɏ]+")

#: Placeholders and markup are code, not language, and their names are ASCII by
#: construction. The Danish `about.thanks_cta` reads "<star>Stjernemarkér
#: projektet</star>", where the tag name `star` is not a bare spelling of `står`
#: and counting it as one both invented a hit and, worse, disqualified the real
#: word everywhere else in the file.
_MARKUP = re.compile(r"\{\{.*?\}\}|<[^<>]*>")


def _words(value: str) -> list[str]:
    """The words of ``value``, with placeholders and markup removed first."""
    return _WORD.findall(_MARKUP.sub(" ", value))


def _skeleton(word: str) -> str:
    """``word`` lowercased with every combining mark removed."""
    return "".join(c for c in unicodedata.normalize("NFD", word.lower()) if not unicodedata.combining(c))


def _has_diacritic(text: str) -> bool:
    return any(unicodedata.combining(c) for c in unicodedata.normalize("NFD", text))


def _entries(path: Path) -> list[tuple[str, str]]:
    out = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            match = _LINE.match(line)
            if match:
                out.append((match.group(1), match.group(2)))
    return out


def stripped_keys(entries: list[tuple[str, str]]) -> dict[str, str]:
    """Keys whose value looks like prose with its diacritics removed."""
    spellings: dict[str, set[str]] = collections.defaultdict(set)
    for _, value in entries:
        if _has_diacritic(value):
            for word in _words(value):
                spellings[_skeleton(word)].add(word)
    # Evidence: this file only ever spells the word with its accent.
    evidence = {skel for skel, forms in spellings.items() if all(_has_diacritic(f) for f in forms)}

    found = {}
    for key, value in entries:
        if _has_diacritic(value):
            continue
        words = _words(value)
        if len(words) < MIN_WORDS:
            continue
        if sum(1 for w in words if _skeleton(w) in evidence) >= MIN_EVIDENCE:
            found[key] = value
    return found


def namespace_stripped_keys(entries: list[tuple[str, str]]) -> dict[str, str]:
    """Keys spelled bare where every other namespace spells that word accented.

    The rule above asks whether this file ever writes the skeleton bare, and a
    file damaged in bulk answers yes out of its own damage. This asks the one
    question the damaged text cannot answer for itself, by taking the rest of
    the file as the dictionary and never letting a namespace speak for itself.
    """
    total: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    per_ns: dict[str, dict[str, collections.Counter[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter)
    )
    rows = []
    for key, value in entries:
        namespace = key.split(".")[0]
        words = _words(value)
        rows.append((key, value, namespace, words))
        for word in words:
            skel = _skeleton(word)
            total[skel][word.lower()] += 1
            per_ns[namespace][skel][word.lower()] += 1

    # A word repeats heavily inside one namespace, so decide each (namespace,
    # word) once. Without this the run is minutes rather than seconds.
    verdict: dict[tuple[str, str], str | None] = {}

    def accented_twin(namespace: str, word: str) -> str | None:
        cached = verdict.get((namespace, word))
        if (namespace, word) in verdict:
            return cached
        skel = _skeleton(word)
        outside = collections.Counter(total[skel])
        outside.subtract(per_ns[namespace][skel])
        forms = {f: c for f, c in outside.items() if c > 0}
        answer = None
        if len(forms) == 1 and sum(forms.values()) >= NS_MIN_EVIDENCE and all(_has_diacritic(f) for f in forms):
            answer = next(iter(forms))
        verdict[(namespace, word)] = answer
        return answer

    found = {}
    for key, value, namespace, words in rows:
        hits = 0
        for word in words:
            if len(word) < NS_MIN_LEN or _has_diacritic(word):
                continue
            if any(c.isdigit() for c in word):
                continue
            if accented_twin(namespace, word.lower()):
                hits += 1
        if hits >= NS_MIN_HITS:
            found[key] = value
    return found


#: The two rules, in the order they are reported. Each is a name, the finder,
#: its baseline file, and the sentence that says what it actually asked.
RULES = (
    (
        "own-file",
        stripped_keys,
        BASELINE,
        "no other string in the same file writes that word bare",
    ),
    (
        "cross-namespace",
        namespace_stripped_keys,
        NS_BASELINE,
        "every other namespace in the file writes that word accented",
    ),
)


def _untracked_locales() -> set[str]:
    """Locale file names that are on disk but in no commit.

    CI reads a checkout, so a file git does not track cannot reach it. Reading
    such a file here makes the local verdict differ from the CI verdict for
    reasons that have nothing to do with the code, which is how a guard teaches
    people to ignore it: hu.ts alone accounted for 52 findings that CI never saw
    once, while the one finding that mattered sat underneath them.
    """
    try:
        done = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "--", str(LOCALES_DIR)],
            cwd=REPO_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        return set()
    if done.returncode != 0:
        return set()
    return {Path(line).name for line in done.stdout.split("\n") if line.strip().endswith(".ts")}


def observe() -> tuple[dict[str, dict[str, dict[str, str]]], int, int, list[str]]:
    """Run both rules over every tracked locale, reading each file once.

    Returns the findings per rule, the population they were drawn from, and the
    files skipped for not being in any commit, so the verdict can be printed
    next to how much was examined to reach it. A green line naming no
    denominator is how a narrowed run passes for a clean one.
    """
    out: dict[str, dict[str, dict[str, str]]] = {name: {} for name, _, _, _ in RULES}
    keys = 0
    files = 0
    untracked = _untracked_locales()
    skipped = []
    for path in sorted(LOCALES_DIR.glob("*.ts")):
        if path.name in untracked:
            skipped.append(path.name)
            continue
        entries = _entries(path)
        keys += len(entries)
        files += 1
        for name, finder, _, _ in RULES:
            found = finder(entries)
            if found:
                out[name][path.name] = dict(sorted(found.items()))
    return out, keys, files, sorted(skipped)


def main() -> int:
    if not LOCALES_DIR.is_dir():
        print(
            f"no locale directory at {LOCALES_DIR} - has the layout changed?",
            file=sys.stderr,
        )
        return 1

    observed, keys, files, skipped = observe()
    if skipped:
        names = ", ".join(skipped)
        print(f"not read, in no commit so CI never sees them: {names}")

    if "--update-baseline" in sys.argv:
        for name, _, path, _ in RULES:
            payload = {locale: sorted(found) for locale, found in observed[name].items()}
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8",
            )
            total = sum(len(v) for v in payload.values())
            print(f"{name} baseline rewritten: {total} strings across {len(payload)} locales")
            for locale, found in payload.items():
                print(f"  {locale}: {len(found)}")
        print("\nRead the diff before committing. A number going UP is the gate telling you something.")
        return 0

    failed = False
    summary: list[str] = []
    for name, _, path, asked in RULES:
        if not path.exists():
            print(
                f"no {name} baseline at {path}; create it with --update-baseline",
                file=sys.stderr,
            )
            return 1
        baseline = {locale: set(found) for locale, found in json.loads(path.read_text(encoding="utf-8")).items()}
        found_by_locale = observed[name]
        observed_total = sum(len(v) for v in found_by_locale.values())
        baseline_total = sum(len(v) for v in baseline.values())

        added: list[tuple[str, str, str]] = []
        unmasking: set[str] = set()
        for locale, found in found_by_locale.items():
            new = set(found) - baseline.get(locale, set())
            if new:
                added.extend((locale, key, found[key]) for key in sorted(new))
                if baseline.get(locale, set()) - set(found):
                    unmasking.add(locale)

        if added:
            failed = True
            print(
                f"\n[{name}] {len(added)} locale string(s) newly detected as stripped of their "
                f"diacritics.\nThis rule asks: {asked}.\n"
                f"Baseline {baseline_total}, observed {observed_total} across "
                f"{len(found_by_locale)} locales, drawn from {keys} keys in {files} files:",
                file=sys.stderr,
            )
            for locale, key, value in added:
                shown = value if len(value) <= 110 else value[:107] + "..."
                print(f"  {locale}: {key}\n      {shown}", file=sys.stderr)
            if unmasking:
                print(
                    "\n"
                    + ", ".join(sorted(unmasking))
                    + " also LOST keys in this run, so this is very likely a repair uncovering damage the\n"
                    "detector could not see before: fixing strings removes the bare spellings that were\n"
                    "hiding others. Those strings were always broken. Fix them too if you can, or accept\n"
                    "them with --update-baseline and read the diff.",
                    file=sys.stderr,
                )
        else:
            line = (
                f"  [{name}] {observed_total} declared across {len(found_by_locale)} locales, "
                f"nothing new (baseline {baseline_total})"
            )
            if baseline_total > observed_total:
                line += (
                    f"\n      {baseline_total - observed_total} fewer than the baseline - "
                    "run --update-baseline to bank the repair"
                )
            summary.append(line)

    if failed:
        print(
            "\nWrite the accented text; do NOT run a find/replace to restore marks. That is the exact\n"
            "pass that turned the German locale into non-words (see check_locale_umlaut_folding.py).\n"
            "If a listed string is genuinely correct without diacritics, record it with\n"
            "--update-baseline and say why in the commit message.",
            file=sys.stderr,
        )
        return 1

    print(f"locale diacritic ratchet OK: {keys} keys examined in {files} locale files")
    for line in summary:
        print(line)
    print("  a green run means no new string crossed either detector's bar, not that none was stripped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
