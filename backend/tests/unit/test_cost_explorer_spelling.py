"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Cost Explorer construction-aware spelling correction.

``app.modules.cost_explorer.spelling`` is pure (``re`` + ``unicodedata`` only),
so it is loaded here directly from its file path, independent of the FastAPI
dependency graph (which does not import cleanly on a bare interpreter), and runs
identically here and in CI.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "app" / "modules" / "cost_explorer" / "spelling.py"
_spec = importlib.util.spec_from_file_location("cost_explorer_spelling", _PATH)
assert _spec and _spec.loader
spelling = importlib.util.module_from_spec(_spec)
sys.modules["cost_explorer_spelling"] = spelling
_spec.loader.exec_module(spelling)

correct_token = spelling.correct_token
suggest_from_tokens = spelling.suggest_from_tokens
suggest_query = spelling.suggest_query


# ── correct_token: the seeded typos are corrected ───────────────────────────


def test_named_examples_are_corrected() -> None:
    # The three examples called out for the feature must always work.
    assert correct_token("concreet") == "concrete"
    assert correct_token("plasterbord") == "plasterboard"
    assert correct_token("screeed") == "screed"


def test_more_trade_typos_are_corrected() -> None:
    assert correct_token("reinforcment") == "reinforcement"
    assert correct_token("insualtion") == "insulation"
    assert correct_token("waterprofing") == "waterproofing"
    assert correct_token("scafolding") == "scaffolding"
    assert correct_token("masonary") == "masonry"
    assert correct_token("colmn") == "column"


# ── correct_token: what must never be touched ───────────────────────────────


def test_correctly_spelled_words_are_left_alone() -> None:
    for word in ("concrete", "steel", "formwork", "plaster", "reinforcement"):
        assert correct_token(word) is None


def test_valid_but_out_of_lexicon_word_is_never_guessed() -> None:
    # No fuzzy edit-distance guessing: a real construction word that happens to
    # look like a lexicon word ("pointing" vs "painting") is left untouched.
    assert correct_token("pointing") is None
    assert correct_token("gizmo") is None
    assert correct_token("zzzzznotathing") is None


def test_grades_and_codes_are_never_corrected() -> None:
    # Anything carrying a digit or a slash is a grade or a code, not a word.
    for token in ("C30/37", "C25/30", "B500B", "S355", "Fe500", "20.01.001", "03.30.00"):
        assert correct_token(token) is None


def test_short_tokens_are_ignored() -> None:
    for token in ("mm", "cem", "m2", "no"):
        assert correct_token(token) is None


# ── correct_token: normalisation of the input token ─────────────────────────


def test_case_and_accents_are_folded_before_lookup() -> None:
    assert correct_token("Concreet") == "concrete"
    assert correct_token("CONCREET") == "concrete"


def test_edge_punctuation_is_stripped() -> None:
    assert correct_token("concreet,") == "concrete"
    assert correct_token("(concreet)") == "concrete"
    assert correct_token("screeed.") == "screed"


# ── suggest_query / suggest_from_tokens ─────────────────────────────────────


def test_suggest_query_corrects_only_the_typo_token() -> None:
    assert suggest_query("concreet wall") == "concrete wall"
    assert suggest_query("reinforced concreet") == "reinforced concrete"
    assert suggest_query("plasterbord and screeed") == "plasterboard and screed"


def test_suggest_query_preserves_a_grade_next_to_a_typo() -> None:
    # The typo is fixed but the concrete grade is carried through verbatim.
    assert suggest_query("concreet C30/37") == "concrete C30/37"


def test_suggest_query_returns_none_when_nothing_to_fix() -> None:
    assert suggest_query("concrete wall") is None
    assert suggest_query("") is None
    assert suggest_query("   ") is None


def test_suggest_from_tokens_matches_direct_correction() -> None:
    assert suggest_from_tokens(["concreet"]) == "concrete"
    assert suggest_from_tokens(["steel"]) is None
    assert suggest_from_tokens([]) is None


# ── lexicon integrity (guards future edits) ─────────────────────────────────


def test_lexicon_is_clean_and_terminal() -> None:
    entries = spelling._MISSPELLINGS
    keys = set(entries)
    values = set(entries.values())
    for key, value in entries.items():
        assert key == key.lower() and key.isalpha(), key
        assert value and value == value.lower() and value.isalpha(), value
        assert key != value
    # A correction target is never itself a typo key, so one pass fully corrects
    # and a suggestion can never oscillate or chain into a second rewrite.
    assert not (values & keys)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} spelling tests passed")
