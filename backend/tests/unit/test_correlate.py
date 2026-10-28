# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure event-reconciliation correlation engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. Tests are
table-driven where it helps and assert each signal in isolation, the signals
combined, code extraction / normalization, subject normalization, the
date-proximity decay curve, symmetric dedup, threshold filtering, deterministic
ordering, empty input, and the optional similarity_fn path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.reconciliation.correlate import (
    DEFAULT_THRESHOLD,
    MAX_WINDOW_DAYS,
    REASON_PARTY_TIME,
    REASON_SHARED_REF,
    REASON_SIMILARITY,
    REASON_SUBJECT,
    RELATION_SAME_EVENT,
    W_PARTY_TIME,
    W_SHARED_REF,
    W_SIMILARITY,
    W_SUBJECT,
    CandidateRecord,
    ScoredLink,
    date_proximity,
    extract_codes,
    find_links,
    normalize_subject,
    record_codes,
    score_pair,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rec(
    record_type: str,
    record_id: str,
    *,
    project_id: str = "P1",
    subject: str = "",
    body: str = "",
    party: str | None = None,
    occurred_at: datetime | None = None,
    refs: tuple[str, ...] = (),
) -> CandidateRecord:
    """Build a CandidateRecord with sensible defaults for terse tests."""
    return CandidateRecord(
        record_type=record_type,
        record_id=record_id,
        project_id=project_id,
        subject=subject,
        body=body,
        party=party,
        occurred_at=occurred_at,
        refs=refs,
    )


_DAY = timedelta(days=1)
_T0 = datetime(2026, 7, 1, 9, 0, 0)


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_relation_and_threshold_constants() -> None:
    assert RELATION_SAME_EVENT == "same_event"
    # A lone shared reference must clear the default threshold; a lone subject or
    # lone party-and-time match must not.
    assert W_SHARED_REF >= DEFAULT_THRESHOLD
    assert W_SUBJECT < DEFAULT_THRESHOLD
    assert W_PARTY_TIME < DEFAULT_THRESHOLD


# ---------------------------------------------------------------------------
# normalize_subject
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Site access", "site access"),
        ("Re: Site access", "site access"),
        ("RE: Site access", "site access"),
        ("Fwd: Site access", "site access"),
        ("FW: Site access", "site access"),
        ("Aw: Site access", "site access"),  # German reply prefix
        ("Re: Fwd: Re: Site access", "site access"),
        ("Re:Re:  Site   access ", "site access"),
        ("   Mixed   Case  Subject ", "mixed case subject"),
        ("", ""),
        ("   ", ""),
        ("Re: ", ""),
    ],
)
def test_normalize_subject(raw: str, expected: str) -> None:
    assert normalize_subject(raw) == expected


def test_normalize_subject_does_not_strip_mid_word_re() -> None:
    # "Renew" must not lose its leading "Re" - the prefix needs the colon.
    assert normalize_subject("Renew permit") == "renew permit"


# ---------------------------------------------------------------------------
# extract_codes / record_codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please action RFI-123 today", {"RFI-123"}),
        ("change order CO-014 approved", {"CO-14"}),  # leading zeros dropped
        ("MoC-7 raised", {"MOC-7"}),
        ("see VO-3 and NCR-9", {"VO-3", "NCR-9"}),
        ("CO 14 with a space", {"CO-14"}),
        ("CO_14 with an underscore", {"CO-14"}),
        ("co-14 lowercase", {"CO-14"}),
        ("no codes here", set()),
        ("", set()),
        ("ISO 9001 is not a tracked code", set()),  # unknown prefix ignored
        ("RFI-1 RFI-1 RFI-2", {"RFI-1", "RFI-2"}),  # de-duplicated
    ],
)
def test_extract_codes(text: str, expected: set[str]) -> None:
    assert set(extract_codes(text)) == expected


def test_extract_codes_across_multiple_texts() -> None:
    assert set(extract_codes("subject RFI-1", "body mentions CO-2")) == {"RFI-1", "CO-2"}


def test_extract_codes_all_zero_keeps_single_zero() -> None:
    assert set(extract_codes("weird CO-000")) == {"CO-0"}


def test_extract_codes_not_inside_larger_token() -> None:
    # A word boundary in front keeps the pattern from firing inside another token.
    assert set(extract_codes("XRFI-123")) == set()


def test_record_codes_unions_text_and_refs() -> None:
    rec = _rec("rfi", "1", subject="about RFI-5", body="ref CO-2", refs=("NCR-9",))
    assert set(record_codes(rec)) == {"RFI-5", "CO-2", "NCR-9"}


def test_record_codes_dedups_ref_and_intext_same_code() -> None:
    # An upstream ref "CO-014" and an in-text "CO-14" are the same normalized code.
    rec = _rec("co", "1", body="references CO-14", refs=("CO-014",))
    assert set(record_codes(rec)) == {"CO-14"}


def test_record_codes_ignores_unrecognised_ref() -> None:
    # A ref that is not a tracked code is dropped rather than guessed at.
    rec = _rec("doc", "1", refs=("just-some-string", "RFI-7"))
    assert set(record_codes(rec)) == {"RFI-7"}


# ---------------------------------------------------------------------------
# date_proximity decay curve
# ---------------------------------------------------------------------------


def test_date_proximity_same_moment_is_one() -> None:
    assert date_proximity(_T0, _T0) == 1.0


def test_date_proximity_at_window_edge_is_zero() -> None:
    far = _T0 + timedelta(days=MAX_WINDOW_DAYS)
    assert date_proximity(_T0, far) == 0.0


def test_date_proximity_beyond_window_is_zero() -> None:
    far = _T0 + timedelta(days=MAX_WINDOW_DAYS + 5)
    assert date_proximity(_T0, far) == 0.0


def test_date_proximity_half_window_is_half() -> None:
    half = _T0 + timedelta(days=MAX_WINDOW_DAYS / 2.0)
    assert date_proximity(_T0, half) == pytest.approx(0.5)


def test_date_proximity_is_symmetric() -> None:
    later = _T0 + timedelta(days=10)
    assert date_proximity(_T0, later) == date_proximity(later, _T0)


def test_date_proximity_linear_decreasing() -> None:
    # Closer pairs always score strictly higher than farther pairs.
    one = date_proximity(_T0, _T0 + _DAY)
    five = date_proximity(_T0, _T0 + 5 * _DAY)
    ten = date_proximity(_T0, _T0 + 10 * _DAY)
    assert one > five > ten > 0.0


def test_date_proximity_sub_day_resolution() -> None:
    # Hours apart should rank above days apart (whole-second resolution).
    hours = date_proximity(_T0, _T0 + timedelta(hours=6))
    days = date_proximity(_T0, _T0 + timedelta(days=6))
    assert hours > days


def test_date_proximity_none_endpoint_is_zero() -> None:
    assert date_proximity(None, _T0) == 0.0
    assert date_proximity(_T0, None) == 0.0
    assert date_proximity(None, None) == 0.0


def test_date_proximity_mixed_aware_naive_is_zero_not_error() -> None:
    aware = _T0.replace(tzinfo=UTC)
    # Must not raise a TypeError; treats the un-comparable pair as no proximity.
    assert date_proximity(_T0, aware) == 0.0


def test_date_proximity_both_aware_compares() -> None:
    a = _T0.replace(tzinfo=UTC)
    b = a + _DAY
    assert 0.0 < date_proximity(a, b) < 1.0


def test_date_proximity_custom_window() -> None:
    # With a 10-day window, a 5-day gap is half.
    assert date_proximity(_T0, _T0 + 5 * _DAY, max_window_days=10.0) == pytest.approx(0.5)


def test_date_proximity_degenerate_window() -> None:
    assert date_proximity(_T0, _T0, max_window_days=0.0) == 1.0
    assert date_proximity(_T0, _T0 + _DAY, max_window_days=0.0) == 0.0


# ---------------------------------------------------------------------------
# score_pair - each signal in isolation
# ---------------------------------------------------------------------------


def test_score_pair_shared_reference_only() -> None:
    a = _rec("rfi", "1", subject="totally different one", body="see CO-14")
    b = _rec("co", "9", subject="unrelated wording", body="this is CO-014")
    link = score_pair(a, b)
    assert link.reasons == (REASON_SHARED_REF,)
    assert link.confidence == pytest.approx(W_SHARED_REF)
    assert link.relation == RELATION_SAME_EVENT


def test_score_pair_subject_only() -> None:
    a = _rec("email", "1", subject="Re: Crane lift on Tuesday")
    b = _rec("rfi", "2", subject="Crane lift on Tuesday")
    link = score_pair(a, b)
    assert link.reasons == (REASON_SUBJECT,)
    assert link.confidence == pytest.approx(W_SUBJECT)


def test_score_pair_party_and_time_only() -> None:
    a = _rec("email", "1", party="Acme Civils", occurred_at=_T0)
    b = _rec("rfi", "2", party="acme civils", occurred_at=_T0 + _DAY)  # case-insensitive
    link = score_pair(a, b)
    assert link.reasons == (REASON_PARTY_TIME,)
    # one day inside a 30-day window -> proximity ~ (1 - 1/30). Confidence is
    # rounded to 6 dp by the engine, so compare at that resolution.
    expected = round(W_PARTY_TIME * (1.0 - 1.0 / MAX_WINDOW_DAYS), 6)
    assert link.confidence == expected


def test_score_pair_party_match_but_undated_does_not_fire() -> None:
    a = _rec("email", "1", party="Acme", occurred_at=None)
    b = _rec("rfi", "2", party="Acme", occurred_at=_T0)
    link = score_pair(a, b)
    assert link.reasons == ()
    assert link.confidence == 0.0


def test_score_pair_party_match_but_outside_window_does_not_fire() -> None:
    a = _rec("email", "1", party="Acme", occurred_at=_T0)
    b = _rec("rfi", "2", party="Acme", occurred_at=_T0 + timedelta(days=MAX_WINDOW_DAYS + 1))
    link = score_pair(a, b)
    assert link.reasons == ()


def test_score_pair_blank_party_does_not_match() -> None:
    a = _rec("email", "1", party="", occurred_at=_T0)
    b = _rec("rfi", "2", party=None, occurred_at=_T0)
    link = score_pair(a, b)
    assert REASON_PARTY_TIME not in link.reasons


def test_score_pair_blank_subjects_do_not_match() -> None:
    a = _rec("email", "1", subject="")
    b = _rec("rfi", "2", subject="   ")
    link = score_pair(a, b)
    assert REASON_SUBJECT not in link.reasons
    assert link.confidence == 0.0


def test_score_pair_no_signals_zero_confidence() -> None:
    a = _rec("email", "1", subject="alpha", body="nothing", party="X", occurred_at=_T0)
    b = _rec("rfi", "2", subject="beta", body="zero codes", party="Y", occurred_at=_T0)
    link = score_pair(a, b)
    assert link.confidence == 0.0
    assert link.reasons == ()


# ---------------------------------------------------------------------------
# score_pair - combined signals
# ---------------------------------------------------------------------------


def test_score_pair_combined_signals_sum_and_order() -> None:
    a = _rec("email", "1", subject="Re: Foundation pour", body="per CO-14", party="Acme", occurred_at=_T0)
    b = _rec("co", "2", subject="Foundation pour", body="CO-014", party="Acme", occurred_at=_T0)
    link = score_pair(a, b)
    # shared ref + subject + party-and-time (same moment -> full proximity)
    assert link.reasons == (REASON_SHARED_REF, REASON_SUBJECT, REASON_PARTY_TIME)
    expected = W_SHARED_REF + W_SUBJECT + W_PARTY_TIME
    assert link.confidence == pytest.approx(min(1.0, expected))


def test_score_pair_confidence_is_clamped_to_one() -> None:
    # Force every signal to fire at full strength; the raw sum exceeds 1.0.
    raw = W_SHARED_REF + W_SUBJECT + W_PARTY_TIME + W_SIMILARITY
    assert raw > 1.0  # precondition: clamping is actually exercised
    a = _rec("email", "1", subject="Same subject", body="CO-1", party="Acme", occurred_at=_T0)
    b = _rec("co", "2", subject="Same subject", body="CO-1", party="Acme", occurred_at=_T0)
    link = score_pair(a, b, similarity_fn=lambda x, y: 1.0)
    assert link.confidence == 1.0


# ---------------------------------------------------------------------------
# score_pair - canonical orientation / symmetry
# ---------------------------------------------------------------------------


def test_score_pair_canonical_orientation_independent_of_arg_order() -> None:
    a = _rec("zeta", "9", body="CO-1")
    b = _rec("alpha", "1", body="CO-1")
    left_first = score_pair(a, b)
    right_first = score_pair(b, a)
    assert left_first == right_first
    # Canonical left is the smaller (type, id) tuple: "alpha" < "zeta".
    assert (left_first.left_type, left_first.left_id) == ("alpha", "1")
    assert (left_first.right_type, left_first.right_id) == ("zeta", "9")


def test_score_pair_same_type_orders_by_id() -> None:
    a = _rec("rfi", "20", body="CO-1")
    b = _rec("rfi", "3", body="CO-1")
    link = score_pair(a, b)
    # String id ordering: "20" < "3".
    assert (link.left_id, link.right_id) == ("20", "3")


# ---------------------------------------------------------------------------
# score_pair - optional similarity_fn path
# ---------------------------------------------------------------------------


def test_score_pair_similarity_skipped_when_none() -> None:
    a = _rec("email", "1", subject="x")
    b = _rec("rfi", "2", subject="y")
    link = score_pair(a, b, similarity_fn=None)
    assert REASON_SIMILARITY not in link.reasons


def test_score_pair_similarity_folds_in_scaled() -> None:
    a = _rec("email", "1", subject="x")
    b = _rec("rfi", "2", subject="y")
    link = score_pair(a, b, similarity_fn=lambda x, y: 0.5)
    assert link.reasons == (REASON_SIMILARITY,)
    assert link.confidence == pytest.approx(W_SIMILARITY * 0.5)


def test_score_pair_similarity_zero_does_not_fire() -> None:
    a = _rec("email", "1")
    b = _rec("rfi", "2")
    link = score_pair(a, b, similarity_fn=lambda x, y: 0.0)
    assert link.reasons == ()
    assert link.confidence == 0.0


def test_score_pair_similarity_clamped() -> None:
    a = _rec("email", "1")
    b = _rec("rfi", "2")
    over = score_pair(a, b, similarity_fn=lambda x, y: 5.0)
    assert over.confidence == pytest.approx(W_SIMILARITY)  # clamped to 1.0 then scaled
    under = score_pair(a, b, similarity_fn=lambda x, y: -3.0)
    assert under.reasons == ()  # negative clamps to 0


def test_score_pair_similarity_called_once_in_canonical_order() -> None:
    calls: list[tuple[str, str]] = []

    def sim(x: CandidateRecord, y: CandidateRecord) -> float:
        calls.append((x.record_type, y.record_type))
        return 0.4

    a = _rec("zeta", "9")
    b = _rec("alpha", "1")
    score_pair(a, b, similarity_fn=sim)
    # Called exactly once, with the canonical (alpha, zeta) ordering regardless
    # of the argument order passed in.
    assert calls == [("alpha", "zeta")]


# ---------------------------------------------------------------------------
# find_links - pairing, project scoping, dedup
# ---------------------------------------------------------------------------


def test_find_links_empty_input() -> None:
    assert find_links([]) == []


def test_find_links_single_record_no_pairs() -> None:
    assert find_links([_rec("rfi", "1", body="CO-1")]) == []


def test_find_links_emits_one_link_per_pair_no_symmetric_dupes() -> None:
    recs = [
        _rec("rfi", "1", body="CO-1"),
        _rec("co", "2", body="CO-1"),
        _rec("ncr", "3", body="CO-1"),
    ]
    links = find_links(recs)
    # 3 records sharing a code -> C(3,2) = 3 links, each unique and undirected.
    assert len(links) == 3
    pairs = {((link.left_type, link.left_id), (link.right_type, link.right_id)) for link in links}
    assert len(pairs) == 3
    # No pair appears with its endpoints swapped.
    for left, right in pairs:
        assert (right, left) not in pairs


def test_find_links_never_links_across_projects() -> None:
    a = _rec("rfi", "1", project_id="P1", body="CO-1")
    b = _rec("co", "2", project_id="P2", body="CO-1")  # same code, different project
    assert find_links([a, b]) == []


def test_find_links_no_self_pairs() -> None:
    # A single record is never paired with itself even with strong self-signals.
    rec = _rec("rfi", "1", subject="Foundation", body="CO-1", party="Acme", occurred_at=_T0)
    assert find_links([rec]) == []


# ---------------------------------------------------------------------------
# find_links - threshold filtering
# ---------------------------------------------------------------------------


def test_find_links_lone_shared_reference_clears_default_threshold() -> None:
    a = _rec("rfi", "1", subject="alpha", body="CO-1")
    b = _rec("co", "2", subject="beta", body="CO-1")
    links = find_links([a, b])
    assert len(links) == 1
    assert links[0].reasons == (REASON_SHARED_REF,)


def test_find_links_lone_subject_below_default_threshold_dropped() -> None:
    a = _rec("email", "1", subject="Crane lift")
    b = _rec("rfi", "2", subject="Re: Crane lift")
    # Subject-only confidence (W_SUBJECT) is below the default threshold.
    assert find_links([a, b]) == []


def test_find_links_subject_plus_party_time_surfaces() -> None:
    # Two sub-threshold signals combine to clear the bar.
    a = _rec("email", "1", subject="Crane lift", party="Acme", occurred_at=_T0)
    b = _rec("rfi", "2", subject="Re: Crane lift", party="Acme", occurred_at=_T0)
    links = find_links([a, b])
    assert len(links) == 1
    assert set(links[0].reasons) == {REASON_SUBJECT, REASON_PARTY_TIME}
    assert links[0].confidence == pytest.approx(W_SUBJECT + W_PARTY_TIME)


def test_find_links_custom_threshold_keeps_weaker_links() -> None:
    a = _rec("email", "1", subject="Crane lift")
    b = _rec("rfi", "2", subject="Re: Crane lift")
    links = find_links([a, b], threshold=0.1)
    assert len(links) == 1
    assert links[0].reasons == (REASON_SUBJECT,)


def test_find_links_threshold_is_inclusive() -> None:
    a = _rec("email", "1", subject="Crane lift")
    b = _rec("rfi", "2", subject="Crane lift")
    # threshold exactly equal to the subject weight keeps the link.
    links = find_links([a, b], threshold=W_SUBJECT)
    assert len(links) == 1


# ---------------------------------------------------------------------------
# find_links - deterministic ordering
# ---------------------------------------------------------------------------


def test_find_links_sorted_by_confidence_desc() -> None:
    # Strong pair (shared ref) and a weaker pair (subject+party) in one project.
    strong_a = _rec("rfi", "1", body="CO-1")
    strong_b = _rec("co", "2", body="CO-1")
    weak_a = _rec("email", "3", subject="Site walk", party="Acme", occurred_at=_T0)
    weak_b = _rec("diary", "4", subject="Site walk", party="Acme", occurred_at=_T0)
    links = find_links([weak_a, weak_b, strong_a, strong_b])
    assert len(links) == 2
    assert links[0].confidence > links[1].confidence
    assert links[0].reasons == (REASON_SHARED_REF,)


def test_find_links_tie_break_by_endpoint_tuples() -> None:
    # Three records, all sharing one code -> three equal-confidence links; the
    # tie-break is left (type,id) then right (type,id), ascending.
    recs = [
        _rec("co", "2", body="CO-9"),
        _rec("alpha", "1", body="CO-9"),
        _rec("alpha", "3", body="CO-9"),
    ]
    links = find_links(recs)
    keys = [(link.left_type, link.left_id, link.right_type, link.right_id) for link in links]
    assert keys == sorted(keys)
    # All identical confidence, so ordering is purely the tuple tie-break.
    assert len({round(link.confidence, 6) for link in links}) == 1


def test_find_links_deterministic_regardless_of_input_order() -> None:
    recs = [
        _rec("rfi", "1", body="CO-1", subject="Pour"),
        _rec("co", "2", body="CO-1", subject="Pour"),
        _rec("ncr", "3", subject="Pour", party="Acme", occurred_at=_T0),
        _rec("diary", "4", subject="Pour", party="Acme", occurred_at=_T0),
    ]
    forward = find_links(recs)
    backward = find_links(list(reversed(recs)))
    assert forward == backward


def test_find_links_similarity_fn_forwarded() -> None:
    # With no native signals, only a supplied similarity_fn can create a link.
    a = _rec("email", "1", subject="alpha")
    b = _rec("rfi", "2", subject="beta")
    assert find_links([a, b]) == []
    links = find_links([a, b], threshold=0.05, similarity_fn=lambda x, y: 1.0)
    assert len(links) == 1
    assert links[0].reasons == (REASON_SIMILARITY,)


# ---------------------------------------------------------------------------
# returned types
# ---------------------------------------------------------------------------


def test_find_links_returns_scoredlinks() -> None:
    links = find_links([_rec("rfi", "1", body="CO-1"), _rec("co", "2", body="CO-1")])
    assert all(isinstance(link, ScoredLink) for link in links)
