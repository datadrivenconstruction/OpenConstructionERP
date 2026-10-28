"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free tests for the main cost-browser multilingual synonym predicate.

``synonym_text_predicate`` wires the shared construction-vocabulary matcher
(:func:`app.modules.cost_explorer.search.match_terms`) into the primary cost
database ``search`` / ``list`` / ``autocomplete`` queries, so a search for
``rebar`` also reaches ``reinforcement`` / ``Bewehrung`` / ``armatura`` in the
main browser - the same forgiving matching the Cost Explorer already shipped.

These tests compile the built predicate to PostgreSQL SQL (no database
connection) and assert the synonym expansion, the word-boundary guard that
keeps a short cross-language synonym from hiding inside an unrelated word, and
the LIKE-wildcard escaping. They are pure and DB-free: nothing here opens a
session, so the suite runs without a live cluster.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.modules.costs.repository import _escape_like, synonym_text_predicate


def _compiled(query: str) -> str:
    """Compile the predicate for ``query`` to lowercased PostgreSQL SQL text."""
    predicate = synonym_text_predicate(query)
    assert predicate is not None, f"expected a predicate for {query!r}"
    return str(
        predicate.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


# ── blank input ─────────────────────────────────────────────────────────────


def test_blank_query_returns_no_predicate() -> None:
    """A blank / whitespace query yields no filter so the caller can skip it."""
    assert synonym_text_predicate("") is None
    assert synonym_text_predicate("   ") is None


# ── multilingual synonym expansion ──────────────────────────────────────────


def test_rebar_expands_to_multilingual_synonyms() -> None:
    """'rebar' reaches its cross-language reinforcement synonyms in the SQL."""
    sql = _compiled("rebar")
    # The user's own word is matched as a substring (partial ILIKE).
    assert "rebar" in sql
    assert "ilike" in sql
    # Cross-language synonyms from the same construction group are injected.
    for synonym in ("reinforcement", "bewehrung", "armatura"):
        assert synonym in sql, f"expected synonym {synonym!r} in the expanded predicate"


def test_accent_free_query_reaches_concrete_group() -> None:
    """An accent-free 'beton' reaches the English 'concrete' synonym."""
    assert "concrete" in _compiled("beton")


# ── poisoning guard: synonyms match on word boundaries ──────────────────────


def test_cross_language_synonyms_matched_on_word_boundaries() -> None:
    """A short foreign synonym uses a boundary regex, never a naked substring.

    French 'porte' (door) must be anchored on word boundaries (PostgreSQL
    ``~*`` with ``\\y``) so it cannot hide inside an unrelated word such as
    'supported'. The word the user typed ('door') stays a substring match.
    """
    sql = _compiled("door")
    assert "~*" in sql  # whole-word synonyms use the regex operator
    assert "yporte" in sql  # \yporte\y - boundary anchored (tolerant of backslash rendering)
    assert "%porte%" not in sql  # never a naked substring for the injected synonym
    assert "%door%" in sql  # the user's own word IS a substring match


# ── LIKE wildcard escaping ──────────────────────────────────────────────────


def test_like_wildcards_are_escaped_in_predicate() -> None:
    """A literal '%' produces an ESCAPE clause so it does not match everything."""
    sql = _compiled("50%")
    assert "escape" in sql


def test_escape_like_helper_escapes_wildcards() -> None:
    """The escaping helper turns LIKE metacharacters into literals."""
    assert _escape_like("50%") == "50\\%"
    assert _escape_like("a_b") == "a\\_b"
    # The escape character itself is escaped first so it stays literal.
    assert _escape_like("x\\y") == "x\\\\y"
    # A plain term is untouched.
    assert _escape_like("plain") == "plain"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} synonym-predicate tests passed")
