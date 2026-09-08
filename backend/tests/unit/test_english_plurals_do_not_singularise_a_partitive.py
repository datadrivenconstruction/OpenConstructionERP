"""English cannot singularise the noun inside a partitive, and a locale file did.

**The defect this file exists to prevent.**

``benchmarks.portfolio_note_cost_and_area`` and its two siblings are rendered by
``frontend/src/modules/cost-benchmark/BenchmarkModule.tsx`` with a ``count``.
Someone added ``_one`` forms for them that read "Based on 1 of your project with
cost and area." English does not work that way: in "N of your projects" the noun
is the set being drawn from, so it stays plural at every count, including one.

The server had already written that down. ``backend/app/modules/costs/service.py``
composes the same sentence and carries a comment two lines above it saying the
partitive stays plural at every count and there is no singular form to switch to.
The locale file then overrode the correct server text with an incorrect singular,
so the comment was not merely ignored, it was ignored while producing exactly the
string it warned against.

Reachability is not theoretical: ``count`` is the number of the reader's own
qualifying projects, guarded only by a check that the list is non-empty, so every
account with exactly one qualifying project met it, in the default language.

**Why a gate rather than just the fix.**

``scripts/check_i18n_plural_forms.py`` is the right instrument for plural
completeness and cannot see these keys at all. Its call-site scan matches literal
keys, and this call builds its key from a backend enum
(``t(`benchmarks.portfolio_note_${note_code}`, ...)``), so the three stems are
invisible to it. Nothing would have caught a mechanical re-add.

**What this asserts, and what it deliberately does not.**

It does not ban partitives in a singular form. That would be wrong, and there is
a live counter-example in the same file: ``full_evm.curve_unmeasured_one`` reads
"1 of these points carries no measurement", which is correct, because what moves
between the two forms there is the verb rather than the noun.

The assertion is narrower and is about one specific mutation: an English ``_one``
form whose ``_other`` sibling is the same sentence with a plural noun after
"of your" or "of these", differing only by that noun losing its "s". That is the
mistake, stated as the shape of the mistake rather than as a list of key names,
so it also catches the next family somebody writes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCALES = REPO_ROOT / "frontend" / "src" / "app" / "locales"

#: Every file written in English. The regional overlays carry only the keys
#: they spell differently, but a ``_one`` form in an overlay is exactly as
#: reachable as one in en.ts: en-US.ts shipped the same singular partitive and
#: kept it for a day after en.ts lost it, because this gate read one file. Each
#: overlay is read the way i18next resolves it, its own keys over en.ts.
ENGLISH = ("en", "en-GB", "en-US")

#: Quote-agnostic on purpose: the repo has no frontend autoformatter, so a file
#: may carry either quoting style and a gate keyed to one of them goes quiet on
#: the other rather than failing.
_ENTRY = re.compile(r"""^\s*["']([A-Za-z0-9_.\-]+)["']\s*:\s*["'](.*?)["'],?\s*$""")

#: The partitive heads we ship. The noun that follows one of these is the set
#: being drawn from, so it does not become singular when the count is one.
_PARTITIVE_HEAD = re.compile(r"\bof (?:your|these|those|the) (\w+)\b")


def _read_locale(code: str) -> dict[str, str]:
    """Every key and value in one locale file, read off disk."""
    entries: dict[str, str] = {}
    for line in (LOCALES / f"{code}.ts").read_text(encoding="utf-8").splitlines():
        match = _ENTRY.match(line)
        if match:
            entries[match.group(1)] = match.group(2)
    return entries


def _read_english(code: str = "en") -> dict[str, str]:
    """The English a reader of ``code`` sees: the overlay's keys over en.ts."""
    return {**_read_locale("en"), **_read_locale(code)}


def _singularised_partitives(one: str, other: str) -> list[tuple[str, str]]:
    """Nouns that lost their plural between the ``_other`` and ``_one`` forms."""
    singular = _PARTITIVE_HEAD.findall(one)
    plural = _PARTITIVE_HEAD.findall(other)
    return [(s, p) for s, p in zip(singular, plural, strict=False) if p == f"{s}s"]


@pytest.mark.parametrize("code", ENGLISH)
def test_no_english_one_form_singularises_the_noun_in_a_partitive(code: str) -> None:
    entries = _read_english(code)
    # Population printed beside the verdict: a gate whose denominator is not the
    # whole set can be satisfied by narrowing the set instead of fixing the tree.
    pairs = {key[: -len("_one")]: key for key in entries if key.endswith("_one")}
    partitive_pairs = {
        stem: one for stem, one in pairs.items() if f"{stem}_other" in entries and _PARTITIVE_HEAD.search(entries[one])
    }
    offenders = {
        one: found
        for stem, one in partitive_pairs.items()
        if (found := _singularised_partitives(entries[one], entries[f"{stem}_other"]))
    }

    print(
        f"english partitives ({code}): {len(entries)} keys read, {len(pairs)} with a _one form, "
        f"{len(partitive_pairs)} of those carrying a partitive, {len(offenders)} singularised"
    )
    assert not offenders, (
        "An English _one form singularised the noun inside a partitive. "
        "In 'N of your projects' the noun is the set being drawn from and stays "
        "plural at every count, so there is no singular form to write. Delete the "
        "_one key and let the bare key answer count=1. Offenders: "
        + "; ".join(f"{key} ({found})" for key, found in sorted(offenders.items()))
    )


def test_the_gate_would_fail_if_the_defect_came_back() -> None:
    """Red in the other direction, using the exact strings that shipped."""
    one = "Based on {{count}} of your project with cost and area."
    other = "Based on {{count}} of your projects with cost and area."
    assert _singularised_partitives(one, other) == [("project", "projects")]


def test_a_correct_singular_partitive_is_not_reported() -> None:
    """The control that keeps this gate narrow.

    ``full_evm.curve_unmeasured`` keeps its partitive plural and changes the verb
    instead, which is right. A gate that flagged this would be worse than no gate,
    because the obvious way to silence it is to break the English.
    """
    one = "1 of these points carries no measurement"
    other = "{{count}} of these points carry no measurement"
    assert _singularised_partitives(one, other) == []


@pytest.mark.parametrize("code", ENGLISH)
def test_the_three_keys_that_shipped_the_defect_are_gone(code: str) -> None:
    """The specific regression, named, so the general rule is not the only record."""
    entries = _read_english(code)
    for stem in (
        "benchmarks.portfolio_note_cost_and_area",
        "benchmarks.portfolio_note_budget_and_boq",
        "benchmarks.portfolio_note_recovery_ledger",
    ):
        assert f"{stem}_one" not in entries, f"{stem}_one is back; count=1 must fall to the bare key"
        # The bare key is what answers count=1 once _one is absent, so its
        # absence would turn this fix into a raw key on screen.
        assert stem in entries, f"{stem} is missing; nothing would answer count=1"
