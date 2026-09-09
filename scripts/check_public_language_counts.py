"""Check that the language counts in the public documents match the code.

README.md told the world the interface ships in 42 languages for as long as it
took two more to be added, and DEVELOPING.md carried a paragraph whose whole
subject was how to count them correctly, itself counting 43 files and 41
offered when the tree held 45 and 44. Both numbers were right when they were
written. Neither had anything that could notice they had stopped being right,
because a number in prose is not a symbol: nothing imports it, nothing renders
it, and the build has no opinion about it.

The DEVELOPING.md case is the one worth keeping in mind. That paragraph exists
to warn a reader that the two obvious counts disagree and that inheriting a
single number leaves you wrong about one of the two questions. It was itself
wrong about both, and it also still said Uzbek was commented out of the picker
months after Uzbek was offered. A document that explains how to count is not
more reliable than one that just counts; it is more expensive to be wrong in,
because it is the one a reader trusts instead of measuring.

WHAT COUNTS AS WHAT

Three numbers, and they are genuinely different questions:

  offered   entries in SUPPORTED_LANGUAGES in frontend/src/app/i18n.ts, which
            is what a user can pick. Regional variants are separate entries
            here, so Spanish and Spanish (Mexico) count twice, which is right
            for "what can I select" and wrong for "how many languages".
  files     locale bundles on disk in frontend/src/app/locales. A language can
            have a file before it is offered, so this is always >= offered.
  base      distinct base languages among the offered entries, es-MX folded
            into es. The honest answer to "how many languages", and the
            smallest of the three.

This guard does not decide which one a sentence ought to use. It reads the
sentence, works out which question it is asking, and checks the digit against
that question's answer. A claim about the picker is checked against `offered`,
a claim about locale files against `files`.

WHAT IT WILL NOT CATCH

A claim written in a shape none of the rules below match. That is why each rule
carries a floor: if a rule that used to find three claims finds none, the guard
fails rather than passing quietly, because a claim that has been reworded out of
reach of its own check is exactly the state this exists to prevent. Every claim
found is printed next to the verdict, so a reader can see the population the
verdict was reached over rather than trusting the word "ok".

CHANGELOG.md is deliberately out of scope. A changelog records what was true at
a release and correcting it would be falsifying it.

Exit codes: 0 when the documents and the tree agree, 1 when they have drifted,
2 when the guard could not prove it still refuses.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "frontend" / "src" / "app" / "i18n.ts"
LOCALE_DIR = ROOT / "frontend" / "src" / "app" / "locales"

# Files that are not a language bundle even though they sit in the folder.
NOT_A_BUNDLE = {"index.ts", "types.ts"}

DOCUMENTS = ("README.md", "DEVELOPING.md")


class Rule:
    """One shape a language count is written in, and the question it asks.

    Attributes:
        name: what to call it when it is wrong.
        pattern: a regex whose first group is the digits being claimed.
        answers: which of the three counts the claim is about.
        floor: how many matches this rule must still find across all the
            documents. A rule that finds fewer has lost sight of its claim.
    """

    def __init__(self, name: str, pattern: str, answers: str, floor: int) -> None:
        self.name = name
        self.pattern = re.compile(pattern)
        self.answers = answers
        self.floor = floor


RULES = [
    Rule("shields badge", r"/badge/languages-(\d+)-", "offered", 1),
    Rule("headline stat cell", r"<b>(\d+)</b><br/><sub>languages</sub>", "offered", 1),
    Rule("comparison table row", r"<b>UI languages</b>.*?<b>(\d+)</b>", "offered", 1),
    Rule("prose count of languages", r"(?<![\d.,])(\d+) languages\b", "offered", 3),
    Rule("count of locale bundles", r"(?<![\d.,])(\d+) locale files\b", "files", 3),
    Rule("offered in the picker", r"(?<![\d.,])(\d+)(?: of them)? offered\b", "offered", 2),
    Rule("entries in the language list", r"(?<![\d.,])(\d+) entries in the `SUPPORTED_LANGUAGES`", "offered", 1),
    Rule("distinct languages", r"(?<![\d.,])(\d+) distinct\s+languages\b", "base", 1),
]


def offered_codes() -> list[str]:
    """Return the language codes SUPPORTED_LANGUAGES offers, in file order.

    Read from the `code:` field alone. The entries also carry a name, an
    English name, a flag and a country, so scraping every quoted string in the
    block reports well over a hundred languages.
    """
    src = I18N.read_text(encoding="utf-8")
    start = src.index("export const SUPPORTED_LANGUAGES")
    end = src.index("\n];", start)
    return re.findall(r"\bcode:\s*'([A-Za-z-]+)'", src[start:end])


def bundle_codes() -> list[str]:
    """Return the locale bundles present on disk."""
    return sorted(p.stem for p in LOCALE_DIR.glob("*.ts") if p.name not in NOT_A_BUNDLE)


def counts() -> dict[str, int]:
    """Return the three counts the documents are checked against."""
    offered = offered_codes()
    return {
        "offered": len(offered),
        "files": len(bundle_codes()),
        "base": len({c.split("-")[0] for c in offered}),
    }


def claims_in(text: str, path: str) -> list[tuple[Rule, int, int, str]]:
    """Return every claim the rules can see, as (rule, line, number, line text)."""
    found = []
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            line = text.splitlines()[line_no - 1]
            found.append((rule, line_no, int(m.group(1)), line.strip()[:100]))
    found.sort(key=lambda c: (path, c[1]))
    return found


def derived_remainder(text: str, path: str, offered: int) -> list[str]:
    """Check a claim of the form "A, B, C, and N more" against the names before it.

    This one is not a bare count, it is arithmetic: eleven languages are named
    and the sentence promises the rest. Bumping the total without touching the
    remainder leaves a sentence that is wrong by exactly the amount the total
    moved, and no count-matching rule can see it because the digits it carries
    are not the total.
    """
    problems = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = re.search(r":\s*(.+?),\s*and (\d+) more\b", line)
        if not m:
            continue
        named = [part.strip() for part in m.group(1).split(",") if part.strip()]
        remainder = int(m.group(2))
        if len(named) + remainder != offered:
            problems.append(
                f"{path}:{i}: names {len(named)} languages and promises {remainder} more, "
                f"which is {len(named) + remainder}, but {offered} are offered"
            )
    return problems


def check(quiet: bool = False) -> int:
    """Read the tree, read the documents, and report every disagreement."""
    n = counts()
    if not quiet:
        print(f"offered in the picker : {n['offered']}")
        print(f"locale bundles        : {n['files']}")
        print(f"distinct languages    : {n['base']}")
        print("")

    problems: list[str] = []
    seen_per_rule: dict[str, int] = {r.name: 0 for r in RULES}

    for name in DOCUMENTS:
        path = ROOT / name
        if not path.exists():
            problems.append(f"{name} is gone, so its language counts are unchecked")
            continue
        text = path.read_text(encoding="utf-8")
        for rule, line_no, claimed, line in claims_in(text, name):
            seen_per_rule[rule.name] += 1
            want = n[rule.answers]
            verdict = "ok" if claimed == want else f"WRONG, {rule.answers} is {want}"
            if not quiet:
                print(f"  {name}:{line_no:<5} {rule.name:24s} says {claimed:3d}  {verdict}")
                print(f"        {line}")
            if claimed != want:
                problems.append(
                    f"{name}:{line_no}: {rule.name} says {claimed}, but {rule.answers} is {n[rule.answers]}"
                )
        problems.extend(derived_remainder(text, name, n["offered"]))

    for rule in RULES:
        if seen_per_rule[rule.name] < rule.floor:
            problems.append(
                f"the rule for {rule.name} found {seen_per_rule[rule.name]} claim(s) and expects "
                f"at least {rule.floor}. Either a claim was deleted, or it was reworded out of "
                f"reach of the only thing that checks it. Widen the rule or lower its floor "
                f"deliberately, in the same commit that reworded the sentence."
            )

    if not problems:
        total = sum(seen_per_rule.values())
        print("")
        print(f"public language counts: {total} claim(s) across {len(DOCUMENTS)} documents, all current")
        return 0

    print("")
    print("  ================================================================")
    print("  STALE LANGUAGE COUNTS in a document the public reads.")
    print("  ================================================================")
    print("")
    for p in problems:
        print(f"    {p}")
    print("")
    print("  These are the numbers a reader takes for the size of the product,")
    print("  and nothing renders them, so nothing else can notice they moved.")
    print("")
    return 1


SELF_TEST_DOC = """\
![Languages](https://img.shields.io/badge/languages-7-orange)
<td align="center"><b>7</b><br/><sub>languages</sub></td>
<tr><td><b>UI languages</b></td><td align="center"><b>7</b></td></tr>
The interface ships in 7 languages, and there are 9 locale files, 7 of them offered.
There are 7 entries in the `SUPPORTED_LANGUAGES` list and 5 distinct languages.
Full UI translation: English, German, and 4 more.
"""


def self_test() -> int:
    """Prove the guard reads each shape, and that the arithmetic rule refuses.

    The fixture claims seven where the truth is eight, so every rule has to
    fire; and it names two languages and promises four more, which is six and
    not eight, so the remainder rule has to fire on numbers that no
    count-matching rule would look at twice.
    """
    claims = claims_in(SELF_TEST_DOC, "fixture")
    by_rule = {}
    for rule, _line, number, _text in claims:
        by_rule.setdefault(rule.name, []).append(number)

    expected = {
        "shields badge": [7],
        "headline stat cell": [7],
        "comparison table row": [7],
        "prose count of languages": [7],
        "count of locale bundles": [9],
        "offered in the picker": [7],
        "entries in the language list": [7],
        "distinct languages": [5],
    }
    if by_rule != expected:
        print(f"SELF-TEST FAIL: the rules read the fixture as {by_rule!r}, expected {expected!r}.")
        return 2

    problems = derived_remainder(SELF_TEST_DOC, "fixture", 8)
    if len(problems) != 1 or "6" not in problems[0]:
        print(f"SELF-TEST FAIL: the remainder rule said {problems!r} about a sentence that is short by two.")
        return 2

    if derived_remainder(SELF_TEST_DOC, "fixture", 6):
        print("SELF-TEST FAIL: the remainder rule complained about a sentence that adds up.")
        return 2

    print("self-test: every claim shape is read, and the remainder rule refuses arithmetic that does not add up")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="prove the guard can still refuse")
    parser.add_argument("--quiet", action="store_true", help="print the verdict without the population")
    args = parser.parse_args()
    if args.selftest:
        return self_test()
    return check(quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
