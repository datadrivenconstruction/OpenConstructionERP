# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure correspondence-thread digest engine (runs on py3.11)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.modules.change_intelligence.thread_digest import (
    AWAITING_NONE,
    AWAITING_THEM,
    AWAITING_US,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    CommsDigest,
    Message,
    build_digest,
    effective_key,
    normalize_subject,
    parse_dt,
)

NOW = datetime(2026, 6, 24, 12, 0, 0)


def _msg(
    *,
    ref_id: str = "m1",
    subject: str = "Site access",
    sender: str = "them@example.com",
    sent_at: str | None = "2026-06-20T09:00:00",
    direction: str = DIRECTION_INBOUND,
    requires_reply: bool = False,
    thread_key: str = "",
) -> Message:
    return Message(
        ref_id=ref_id,
        subject=subject,
        sender=sender,
        sent_at=sent_at,
        direction=direction,
        requires_reply=requires_reply,
        thread_key=thread_key,
    )


# --- normalize_subject -----------------------------------------------------


def test_normalize_subject_strips_single_prefix() -> None:
    assert normalize_subject("Re: Site access") == "site access"


def test_normalize_subject_strips_multiple_prefixes() -> None:
    assert normalize_subject("Re: Fwd: Re: Site access") == "site access"


@pytest.mark.parametrize("prefix", ["Re", "RE", "re", "Fw", "FW", "Fwd", "FWD", "fwd"])
def test_normalize_subject_prefix_case_insensitive(prefix: str) -> None:
    assert normalize_subject(prefix + ": Topic") == "topic"


def test_normalize_subject_collapses_internal_whitespace() -> None:
    assert normalize_subject("Re:   Site    access  here") == "site access here"


def test_normalize_subject_lowercases_and_strips_ends() -> None:
    assert normalize_subject("   MIXED Case Subject   ") == "mixed case subject"


def test_normalize_subject_handles_tabs_and_newlines() -> None:
    assert normalize_subject("Re:\tSite\naccess") == "site access"


def test_normalize_subject_no_prefix_unchanged_apart_from_case() -> None:
    assert normalize_subject("Quarterly report") == "quarterly report"


def test_normalize_subject_empty_string() -> None:
    assert normalize_subject("") == ""


# --- parse_dt --------------------------------------------------------------


def test_parse_dt_valid_datetime() -> None:
    assert parse_dt("2026-06-20T09:00:00") == datetime(2026, 6, 20, 9, 0, 0)


def test_parse_dt_valid_date_only() -> None:
    assert parse_dt("2026-06-20") == datetime(2026, 6, 20)


def test_parse_dt_trailing_z() -> None:
    parsed = parse_dt("2026-06-20T09:00:00Z")
    assert parsed is not None
    assert parsed.year == 2026 and parsed.hour == 9
    assert parsed.utcoffset() is not None


def test_parse_dt_datetime_with_garbage_tail_falls_back_to_date() -> None:
    # The full string will not parse, but the leading date will.
    assert parse_dt("2026-06-20 not a real time") == datetime(2026, 6, 20)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_parse_dt_blank_is_none(value: str | None) -> None:
    assert parse_dt(value) is None


@pytest.mark.parametrize("value", ["not-a-date", "tomorrow", "20/06/2026", "abcdefghij"])
def test_parse_dt_garbage_is_none(value: str) -> None:
    assert parse_dt(value) is None


# --- effective_key ---------------------------------------------------------


def test_effective_key_uses_thread_key_when_set() -> None:
    assert effective_key(_msg(subject="Re: Anything", thread_key="THREAD-7")) == "THREAD-7"


def test_effective_key_falls_back_to_normalized_subject() -> None:
    assert effective_key(_msg(subject="Re: Site access", thread_key="")) == "site access"


# --- grouping --------------------------------------------------------------


def test_same_normalized_subject_groups_into_one_thread() -> None:
    msgs = [
        _msg(ref_id="a", subject="Site access", sent_at="2026-06-20T09:00:00"),
        _msg(ref_id="b", subject="Re: Site access", sent_at="2026-06-21T09:00:00"),
        _msg(ref_id="c", subject="RE: Fwd: Site access", sent_at="2026-06-22T09:00:00"),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.thread_count == 1
    assert digest.threads[0].message_count == 3


def test_explicit_thread_key_groups_independently_of_subject() -> None:
    # Same subject, but two different explicit thread keys -> two threads.
    msgs = [
        _msg(ref_id="a", subject="Site access", thread_key="K1"),
        _msg(ref_id="b", subject="Site access", thread_key="K2"),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.thread_count == 2
    assert {t.thread_key for t in digest.threads} == {"K1", "K2"}


def test_different_subjects_make_different_threads() -> None:
    msgs = [
        _msg(ref_id="a", subject="Site access"),
        _msg(ref_id="b", subject="Crane delivery"),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.thread_count == 2


# --- awaiting computation --------------------------------------------------


def test_awaiting_us_when_latest_inbound_requires_reply() -> None:
    msgs = [
        _msg(ref_id="a", sent_at="2026-06-20T09:00:00", direction=DIRECTION_OUTBOUND),
        _msg(
            ref_id="b",
            sent_at="2026-06-21T09:00:00",
            direction=DIRECTION_INBOUND,
            requires_reply=True,
        ),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.threads[0].awaiting == AWAITING_US
    assert digest.threads[0].is_open is True


def test_awaiting_them_when_latest_outbound_requires_reply() -> None:
    msgs = [
        _msg(ref_id="a", sent_at="2026-06-20T09:00:00", direction=DIRECTION_INBOUND),
        _msg(
            ref_id="b",
            sent_at="2026-06-21T09:00:00",
            direction=DIRECTION_OUTBOUND,
            requires_reply=True,
        ),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.threads[0].awaiting == AWAITING_THEM
    assert digest.threads[0].is_open is True


def test_awaiting_none_when_latest_requires_no_reply() -> None:
    msgs = [
        _msg(
            ref_id="a",
            sent_at="2026-06-20T09:00:00",
            direction=DIRECTION_INBOUND,
            requires_reply=True,
        ),
        _msg(
            ref_id="b",
            sent_at="2026-06-21T09:00:00",
            direction=DIRECTION_OUTBOUND,
            requires_reply=False,
        ),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.threads[0].awaiting == AWAITING_NONE
    assert digest.threads[0].is_open is False


def test_awaiting_uses_latest_not_earliest_message() -> None:
    # An earlier inbound asked for a reply; the later outbound answered and asks
    # nothing -> nothing outstanding.
    msgs = [
        _msg(ref_id="late", sent_at="2026-06-22T09:00:00", direction=DIRECTION_OUTBOUND),
        _msg(
            ref_id="early",
            sent_at="2026-06-20T09:00:00",
            direction=DIRECTION_INBOUND,
            requires_reply=True,
        ),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.threads[0].last_sender == "them@example.com"
    assert digest.threads[0].awaiting == AWAITING_NONE


# --- participants ----------------------------------------------------------


def test_participants_deduped_and_sorted() -> None:
    msgs = [
        _msg(ref_id="a", sender="carol@example.com", sent_at="2026-06-20T09:00:00"),
        _msg(ref_id="b", sender="alice@example.com", sent_at="2026-06-21T09:00:00"),
        _msg(ref_id="c", sender="carol@example.com", sent_at="2026-06-22T09:00:00"),
        _msg(ref_id="d", sender="bob@example.com", sent_at="2026-06-23T09:00:00"),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.threads[0].participants == (
        "alice@example.com",
        "bob@example.com",
        "carol@example.com",
    )


# --- first_at / last_at and ordering --------------------------------------


def test_first_at_and_last_at_track_span() -> None:
    msgs = [
        _msg(ref_id="mid", sent_at="2026-06-21T09:00:00"),
        _msg(ref_id="first", sent_at="2026-06-20T09:00:00"),
        _msg(ref_id="last", sent_at="2026-06-23T09:00:00"),
    ]
    digest = build_digest(msgs, NOW)
    thread = digest.threads[0]
    assert thread.first_at == "2026-06-20T09:00:00"
    assert thread.last_at == "2026-06-23T09:00:00"


def test_subject_taken_from_earliest_dated_message() -> None:
    # All pinned to one thread; the headline subject is the earliest dated
    # message's verbatim subject, not a later (re-prefixed) one, and not in
    # input order.
    msgs = [
        _msg(ref_id="b", subject="Re: Site access", sent_at="2026-06-21T09:00:00", thread_key="K"),
        _msg(ref_id="a", subject="Site access ORIGINAL", sent_at="2026-06-20T09:00:00", thread_key="K"),
        _msg(ref_id="c", subject="Re: Re: later", sent_at="2026-06-22T09:00:00", thread_key="K"),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.thread_count == 1
    assert digest.threads[0].subject == "Site access ORIGINAL"


def test_undated_messages_sort_last_within_thread() -> None:
    # The undated message must not become the "latest" - the dated outbound is.
    msgs = [
        _msg(
            ref_id="dated",
            sent_at="2026-06-20T09:00:00",
            direction=DIRECTION_OUTBOUND,
            requires_reply=True,
            thread_key="K",
        ),
        _msg(
            ref_id="undated",
            sent_at=None,
            direction=DIRECTION_INBOUND,
            requires_reply=False,
            thread_key="K",
        ),
    ]
    digest = build_digest(msgs, NOW)
    thread = digest.threads[0]
    # Latest in order is the undated one (sorts last), so awaiting is none.
    assert thread.last_sender == "them@example.com"
    assert thread.awaiting == AWAITING_NONE
    # Span still reflects only the dated message.
    assert thread.first_at == "2026-06-20T09:00:00"
    assert thread.last_at == "2026-06-20T09:00:00"


def test_all_undated_thread_has_none_span_and_first_subject() -> None:
    msgs = [
        _msg(ref_id="a", subject="First subject", sent_at=None, thread_key="K"),
        _msg(ref_id="b", subject="Second subject", sent_at="", thread_key="K"),
    ]
    digest = build_digest(msgs, NOW)
    thread = digest.threads[0]
    assert thread.first_at is None
    assert thread.last_at is None
    assert thread.subject == "First subject"


def test_threads_open_first_then_recent_last_at_first() -> None:
    msgs = [
        # Closed thread, very recent.
        _msg(ref_id="c1", subject="Closed recent", sent_at="2026-06-23T09:00:00", requires_reply=False),
        # Open thread, older.
        _msg(
            ref_id="o1",
            subject="Open older",
            sent_at="2026-06-10T09:00:00",
            direction=DIRECTION_INBOUND,
            requires_reply=True,
        ),
        # Open thread, newer than the other open one.
        _msg(
            ref_id="o2",
            subject="Open newer",
            sent_at="2026-06-15T09:00:00",
            direction=DIRECTION_INBOUND,
            requires_reply=True,
        ),
    ]
    digest = build_digest(msgs, NOW)
    subjects = [t.subject for t in digest.threads]
    # Both open threads come first (newer open before older open), closed last.
    assert subjects == ["Open newer", "Open older", "Closed recent"]


def test_undated_thread_sorts_after_dated_threads() -> None:
    msgs = [
        _msg(ref_id="u", subject="Undated topic", sent_at=None, requires_reply=False),
        _msg(ref_id="d", subject="Dated topic", sent_at="2026-06-20T09:00:00", requires_reply=False),
    ]
    digest = build_digest(msgs, NOW)
    assert [t.subject for t in digest.threads] == ["Dated topic", "Undated topic"]


def test_thread_key_breaks_ties_for_undated_threads() -> None:
    msgs = [
        _msg(ref_id="b", subject="Z", sent_at=None, thread_key="K-zebra"),
        _msg(ref_id="a", subject="A", sent_at=None, thread_key="K-alpha"),
    ]
    digest = build_digest(msgs, NOW)
    assert [t.thread_key for t in digest.threads] == ["K-alpha", "K-zebra"]


# --- counts and generated_at ----------------------------------------------


def test_counts_thread_open_and_awaiting_us() -> None:
    msgs = [
        # awaiting us
        _msg(ref_id="a", subject="Need from us", direction=DIRECTION_INBOUND, requires_reply=True),
        # awaiting them
        _msg(ref_id="b", subject="Need from them", direction=DIRECTION_OUTBOUND, requires_reply=True),
        # closed
        _msg(ref_id="c", subject="All done", direction=DIRECTION_OUTBOUND, requires_reply=False),
    ]
    digest = build_digest(msgs, NOW)
    assert digest.thread_count == 3
    assert digest.open_count == 2
    assert digest.awaiting_us_count == 1


def test_generated_at_is_supplied_now_isoformat() -> None:
    digest = build_digest([_msg()], NOW)
    assert digest.generated_at == NOW.isoformat()


def test_generated_at_does_not_read_the_clock() -> None:
    # A fixed past "now" must be echoed verbatim - proves determinism.
    fixed = datetime(2000, 1, 2, 3, 4, 5)
    digest = build_digest([_msg()], fixed)
    assert digest.generated_at == "2000-01-02T03:04:05"


# --- empty input -----------------------------------------------------------


def test_empty_input_yields_empty_digest() -> None:
    digest = build_digest([], NOW)
    assert isinstance(digest, CommsDigest)
    assert digest.thread_count == 0
    assert digest.open_count == 0
    assert digest.awaiting_us_count == 0
    assert digest.threads == ()
    assert digest.generated_at == NOW.isoformat()


def test_accepts_a_generator_not_just_a_list() -> None:
    # build_digest takes an Iterable - feed it a generator.
    gen = (_msg(ref_id=str(i), subject=f"Topic {i}") for i in range(3))
    digest = build_digest(gen, NOW)
    assert digest.thread_count == 3
