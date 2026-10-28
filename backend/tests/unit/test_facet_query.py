# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure faceted-retrieval engine.

All tests are IO-free and deterministic.  No database, no clock: any
reference time is passed explicitly via ``as_of``.
"""

from __future__ import annotations

from app.modules.retrieval.facet_query import (
    RECENCY_HORIZON_DAYS,
    WEIGHT_BASE,
    FacetQuery,
    RankedResult,
    RetrievableRecord,
    _date_key,
    _days_between,
    _in_window,
    _overlap_fraction,
    _recency_weight,
    _terms,
    run_query,
)

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def rec(
    record_id: str,
    *,
    record_type: str = "letter",
    title: str = "",
    body: str = "",
    source_module: str = "correspondence",
    party: str = "",
    occurred_at: str = "",
    entity_refs: tuple[str, ...] = (),
    base_score: float = 0.0,
) -> RetrievableRecord:
    return RetrievableRecord(
        record_type=record_type,
        record_id=record_id,
        title=title,
        body=body,
        source_module=source_module,
        party=party,
        occurred_at=occurred_at,
        entity_refs=entity_refs,
        base_score=base_score,
    )


def ids(results: tuple[RankedResult, ...]) -> list[str]:
    return [r.record.record_id for r in results]


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------


def test_date_key_truncates_and_guards():
    assert _date_key("2026-06-25T14:30:00Z") == "2026-06-25"
    assert _date_key("2026-06-25") == "2026-06-25"
    assert _date_key("") == ""
    assert _date_key("2026-06") == ""  # too short -> unknown
    assert _date_key("bad") == ""


def test_in_window_inclusive_boundaries():
    # Inclusive at both ends.
    assert _in_window("2026-06-01", "2026-06-01", "2026-06-30") is True
    assert _in_window("2026-06-30", "2026-06-01", "2026-06-30") is True
    # Just outside.
    assert _in_window("2026-05-31", "2026-06-01", "2026-06-30") is False
    assert _in_window("2026-07-01", "2026-06-01", "2026-06-30") is False
    # Open bounds.
    assert _in_window("2026-06-15", "", "2026-06-30") is True
    assert _in_window("2026-06-15", "2026-06-01", "") is True
    # Empty date never in a bounded window.
    assert _in_window("", "2026-06-01", "2026-06-30") is False


def test_terms_filters_and_dedups():
    assert _terms("Notice of Delay delay a") == ("notice", "of", "delay")
    assert _terms("") == ()
    assert _terms("a b c") == ()  # all single char -> dropped


def test_overlap_fraction():
    assert _overlap_fraction(("notice", "delay"), "Notice of long DELAY here") == 1.0
    assert _overlap_fraction(("notice", "delay"), "notice only") == 0.5
    assert _overlap_fraction((), "anything") == 0.0
    assert _overlap_fraction(("zzz",), "nothing matches") == 0.0


def test_days_between():
    assert _days_between("2026-06-01", "2026-06-30") == 29
    assert _days_between("2026-06-30", "2026-06-01") == -29
    assert _days_between("2026-06-01", "2026-06-01") == 0
    # Leap-year boundary: 2024 is a leap year, Feb has 29 days.
    assert _days_between("2024-02-28", "2024-03-01") == 2
    # Non-leap year: 2026 Feb has 28 days.
    assert _days_between("2026-02-28", "2026-03-01") == 1
    assert _days_between("bad", "2026-01-01") is None


def test_recency_weight_decay():
    as_of = "2026-06-25"
    # Same day -> full recency.
    assert _recency_weight("2026-06-25", as_of) == 1.0
    # Future event clamps to 1.0.
    assert _recency_weight("2026-07-01", as_of) == 1.0
    # Horizon or older -> 0.0.
    old = _date_key("2025-06-25")
    assert _recency_weight(old, as_of) == 0.0
    # Empty as_of -> no signal.
    assert _recency_weight("2026-06-25", "") == 0.0
    # Empty occurred_at -> no signal.
    assert _recency_weight("", as_of) == 0.0
    # Monotonic: newer event scores strictly higher than an older one.
    newer = _recency_weight("2026-06-20", as_of)
    older = _recency_weight("2026-01-20", as_of)
    assert newer > older > 0.0


# ---------------------------------------------------------------------------
# Filtering: each facet in isolation
# ---------------------------------------------------------------------------


def test_filter_record_type_isolated():
    records = [
        rec("a", record_type="letter"),
        rec("b", record_type="rfi"),
        rec("c", record_type="submittal"),
    ]
    q = FacetQuery(record_types=frozenset({"rfi", "submittal"}))
    out = run_query(records, q)
    assert set(ids(out)) == {"b", "c"}
    for r in out:
        assert "type" in r.matched_facets


def test_filter_party_case_insensitive():
    records = [
        rec("a", party="Acme Contractors"),
        rec("b", party="Globex"),
        rec("c", party="acme contractors"),
    ]
    q = FacetQuery(parties=frozenset({"ACME CONTRACTORS"}))
    out = run_query(records, q)
    assert set(ids(out)) == {"a", "c"}
    for r in out:
        assert "party" in r.matched_facets


def test_filter_date_window_inclusive():
    records = [
        rec("lo", occurred_at="2026-06-01"),
        rec("mid", occurred_at="2026-06-15T09:00:00"),
        rec("hi", occurred_at="2026-06-30"),
        rec("before", occurred_at="2026-05-31"),
        rec("after", occurred_at="2026-07-01"),
    ]
    q = FacetQuery(date_from="2026-06-01", date_to="2026-06-30")
    out = run_query(records, q)
    assert set(ids(out)) == {"lo", "mid", "hi"}
    for r in out:
        assert "date" in r.matched_facets


def test_filter_entity_intersection_case_insensitive():
    records = [
        rec("a", entity_refs=("WBS-01", "DOC-9")),
        rec("b", entity_refs=("doc-9",)),
        rec("c", entity_refs=("ZZZ",)),
    ]
    q = FacetQuery(entity_refs=frozenset({"DOC-9"}))
    out = run_query(records, q)
    assert set(ids(out)) == {"a", "b"}
    for r in out:
        assert any(f.startswith("entity:") for f in r.matched_facets)


def test_filter_text_term_match():
    records = [
        rec("a", title="Notice of Delay", body="extension of time"),
        rec("b", title="Payment certificate", body="monthly valuation"),
        rec("c", body="", entity_refs=("delay-claim-7",)),
    ]
    q = FacetQuery(text="delay")
    out = run_query(records, q)
    # "delay" appears in a's title and in c's entity ref (haystack includes refs).
    assert set(ids(out)) == {"a", "c"}
    for r in out:
        assert "text" in r.matched_facets


# ---------------------------------------------------------------------------
# Empty-date handling under the date facet
# ---------------------------------------------------------------------------


def test_empty_occurred_at_excluded_when_date_facet_active():
    records = [rec("dated", occurred_at="2026-06-15"), rec("undated", occurred_at="")]
    q = FacetQuery(date_from="2026-06-01", date_to="2026-06-30")
    out = run_query(records, q)
    assert ids(out) == ["dated"]


def test_empty_occurred_at_included_when_no_date_facet():
    records = [rec("dated", occurred_at="2026-06-15"), rec("undated", occurred_at="")]
    q = FacetQuery(record_types=frozenset({"letter"}))
    out = run_query(records, q)
    assert set(ids(out)) == {"dated", "undated"}


# ---------------------------------------------------------------------------
# Combined facets (AND semantics)
# ---------------------------------------------------------------------------


def test_combined_facets_and_semantics():
    records = [
        rec(
            "match",
            record_type="letter",
            party="Acme",
            occurred_at="2026-06-10",
            entity_refs=("EOT-1",),
            title="Notice of delay",
        ),
        # Right text + party but wrong type.
        rec(
            "wrong_type",
            record_type="rfi",
            party="Acme",
            occurred_at="2026-06-10",
            entity_refs=("EOT-1",),
            title="Notice of delay",
        ),
        # Right everything but date out of window.
        rec(
            "wrong_date",
            record_type="letter",
            party="Acme",
            occurred_at="2026-01-01",
            entity_refs=("EOT-1",),
            title="Notice of delay",
        ),
        # Right everything but party differs.
        rec(
            "wrong_party",
            record_type="letter",
            party="Globex",
            occurred_at="2026-06-10",
            entity_refs=("EOT-1",),
            title="Notice of delay",
        ),
    ]
    q = FacetQuery(
        text="delay",
        parties=frozenset({"acme"}),
        date_from="2026-06-01",
        date_to="2026-06-30",
        entity_refs=frozenset({"eot-1"}),
        record_types=frozenset({"letter"}),
    )
    out = run_query(records, q)
    assert ids(out) == ["match"]
    only = out[0]
    # All five facet kinds should be reflected in matched_facets.
    assert "type" in only.matched_facets
    assert "party" in only.matched_facets
    assert "date" in only.matched_facets
    assert "text" in only.matched_facets
    assert any(f.startswith("entity:") for f in only.matched_facets)


# ---------------------------------------------------------------------------
# Scoring monotonicity
# ---------------------------------------------------------------------------


def test_more_text_overlap_scores_higher():
    records = [
        rec("both", title="notice delay", body=""),
        rec("one", title="notice only", body=""),
    ]
    q = FacetQuery(text="notice delay")
    out = run_query(records, q)
    assert ids(out) == ["both", "one"]
    score_by_id = {r.record.record_id: r.score for r in out}
    assert score_by_id["both"] > score_by_id["one"]


def test_entity_match_boosts_score():
    # Same text overlap; one also matches an entity ref so should rank higher.
    records = [
        rec("with_entity", title="delay", entity_refs=("EOT-1",)),
        rec("without_entity", title="delay", entity_refs=("OTHER",)),
    ]
    q = FacetQuery(text="delay", entity_refs=frozenset({"EOT-1"}))
    # Both must still match text; entity facet only keeps with_entity though,
    # because entity facet is an AND filter. Use a query where entity facet is
    # inactive to isolate the *boost* rather than the filter:
    q_boost = FacetQuery(text="delay")
    out = run_query(records, q_boost)
    # No entity facet -> both returned, equal text, equal everything -> tie
    # broken by record_id ascending.
    assert ids(out) == ["with_entity", "without_entity"]

    # Now with the entity facet active, only with_entity survives and its
    # score includes the entity contribution.
    out2 = run_query(records, q)
    assert ids(out2) == ["with_entity"]
    assert out2[0].score > out[0].score  # boosted above the un-faceted score


def test_recency_with_as_of_boosts_newer():
    records = [
        rec("new", title="delay", occurred_at="2026-06-20"),
        rec("old", title="delay", occurred_at="2026-01-01"),
    ]
    q = FacetQuery(text="delay")
    out = run_query(records, q, as_of="2026-06-25")
    assert ids(out) == ["new", "old"]
    score_by_id = {r.record.record_id: r.score for r in out}
    assert score_by_id["new"] > score_by_id["old"]


def test_base_score_respected_when_no_other_signal():
    # "Everything" browse: ranking is base_score then recency.
    records = [
        rec("low", base_score=0.2),
        rec("high", base_score=0.9),
        rec("mid", base_score=0.5),
    ]
    out = run_query(records, FacetQuery())
    assert ids(out) == ["high", "mid", "low"]
    # Score is exactly WEIGHT_BASE * base_score here (no recency without as_of).
    assert abs(out[0].score - WEIGHT_BASE * 0.9) < 1e-9


def test_base_score_clamped_into_unit_interval():
    # An out-of-range upstream score must not blow past the [0,1] clamp.
    records = [rec("over", base_score=5.0, title="delay")]
    out = run_query(records, FacetQuery(text="delay"))
    assert 0.0 <= out[0].score <= 1.0


# ---------------------------------------------------------------------------
# Deterministic ordering and tie-breaks
# ---------------------------------------------------------------------------


def test_tie_break_newer_date_then_id_ascending():
    # All identical base score and text overlap -> equal score.  Tie-break is
    # newer occurred_at first, then record_id ascending.
    records = [
        rec("b2", title="delay", occurred_at="2026-06-10"),
        rec("a1", title="delay", occurred_at="2026-06-10"),  # same date as b2
        rec("c3", title="delay", occurred_at="2026-06-20"),  # newest
        rec("d4", title="delay", occurred_at=""),  # unknown date sorts last
    ]
    q = FacetQuery(text="delay")
    out = run_query(records, q)
    # c3 (newest) first; then the 2026-06-10 pair ordered by id (a1 < b2);
    # then the undated record last.
    assert ids(out) == ["c3", "a1", "b2", "d4"]


def test_ordering_is_stable_and_deterministic():
    records = [
        rec("x", base_score=0.5),
        rec("y", base_score=0.5),
        rec("z", base_score=0.5),
    ]
    out1 = ids(run_query(records, FacetQuery()))
    out2 = ids(run_query(list(reversed(records)), FacetQuery()))
    # Equal scores, no dates -> pure id-ascending tie-break, input order
    # independent.
    assert out1 == out2 == ["x", "y", "z"]


# ---------------------------------------------------------------------------
# Empty query / no-match / provenance
# ---------------------------------------------------------------------------


def test_empty_query_returns_all_ranked():
    records = [rec("a", base_score=0.1), rec("b", base_score=0.7)]
    out = run_query(records, FacetQuery())
    assert set(ids(out)) == {"a", "b"}
    assert ids(out) == ["b", "a"]  # higher base score first
    # No facet contributed to the match.
    for r in out:
        assert r.matched_facets == ()


def test_no_match_returns_empty_tuple():
    records = [rec("a", title="payment certificate")]
    out = run_query(records, FacetQuery(text="zzzznomatch"))
    assert out == ()
    assert isinstance(out, tuple)


def test_text_facet_with_no_candidate_text_excludes():
    # Query has text but the record has nothing matchable -> filtered out.
    records = [rec("blank", title="", body="", entity_refs=())]
    out = run_query(records, FacetQuery(text="delay"))
    assert out == ()


def test_provenance_has_required_keys():
    records = [
        rec(
            "p1",
            record_type="rfi",
            source_module="rfi",
            occurred_at="2026-06-15",
            title="delay",
        )
    ]
    out = run_query(records, FacetQuery(text="delay"))
    assert len(out) == 1
    prov = out[0].provenance
    for key in ("module", "record_type", "record_id", "occurred_at"):
        assert key in prov
    assert prov["module"] == "rfi"
    assert prov["record_type"] == "rfi"
    assert prov["record_id"] == "p1"
    assert prov["occurred_at"] == "2026-06-15"


def test_recency_horizon_constant_is_sane():
    # Guard against accidental zero / negative horizon that would break decay.
    assert RECENCY_HORIZON_DAYS > 0


def test_results_are_ranked_results():
    records = [rec("a", title="delay")]
    out = run_query(records, FacetQuery(text="delay"))
    assert isinstance(out[0], RankedResult)
    assert isinstance(out[0].record, RetrievableRecord)
    assert isinstance(out[0].matched_facets, tuple)
    assert isinstance(out[0].provenance, dict)
