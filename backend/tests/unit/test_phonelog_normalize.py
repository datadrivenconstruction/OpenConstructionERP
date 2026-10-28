# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the phonelog normalization engine."""

from __future__ import annotations

from app.modules.phonelog.normalize import (
    INSTRUCTION_CUES,
    NormalizedPhoneLog,
    PhoneLogInput,
    derive_duration,
    extract_instructions,
    normalize,
    normalize_channel,
    normalize_direction,
    split_parties,
    summarize,
)

# --------------------------------------------------------------------------------------
# normalize_direction
# --------------------------------------------------------------------------------------


def test_direction_blank_is_unknown():
    assert normalize_direction("") == "unknown"


def test_direction_unrecognised_is_unknown():
    assert normalize_direction("sideways") == "unknown"


def test_direction_inbound_synonyms():
    for raw in ("in", "inbound", "incoming", "received", "from-them"):
        assert normalize_direction(raw) == "inbound"


def test_direction_outbound_synonyms():
    for raw in ("out", "outbound", "outgoing", "called", "to-them"):
        assert normalize_direction(raw) == "outbound"


def test_direction_internal_synonyms():
    for raw in ("internal", "team", "us"):
        assert normalize_direction(raw) == "internal"


def test_direction_is_case_insensitive_and_trimmed():
    assert normalize_direction("  INCOMING  ") == "inbound"
    assert normalize_direction("OutGoing") == "outbound"


# --------------------------------------------------------------------------------------
# normalize_channel
# --------------------------------------------------------------------------------------


def test_channel_blank_defaults_to_phone():
    assert normalize_channel("") == "phone"


def test_channel_phone_synonyms():
    for raw in ("phone", "call", "telephone"):
        assert normalize_channel(raw) == "phone"


def test_channel_voice_note_synonyms():
    for raw in ("voice", "voice_note", "voicenote", "voicemail", "audio"):
        assert normalize_channel(raw) == "voice_note"


def test_channel_chat_synonyms():
    for raw in ("chat", "im", "message", "sms", "whatsapp"):
        assert normalize_channel(raw) == "chat"


def test_channel_unknown_is_other():
    assert normalize_channel("carrier-pigeon") == "other"


def test_channel_is_case_insensitive_and_trimmed():
    assert normalize_channel("  VoiceMail ") == "voice_note"


# --------------------------------------------------------------------------------------
# split_parties
# --------------------------------------------------------------------------------------


def test_split_parties_blank_is_empty():
    assert split_parties("") == ()


def test_split_parties_mixed_separators():
    raw = "John Doe (us) -> Acme site office, Jane Roe; Bob/Sam | Pat\nQuinn"
    assert split_parties(raw) == (
        "John Doe (us)",
        "Acme site office",
        "Jane Roe",
        "Bob",
        "Sam",
        "Pat",
        "Quinn",
    )


def test_split_parties_from_list():
    assert split_parties(["Alice", "Bob", "Carol"]) == ("Alice", "Bob", "Carol")


def test_split_parties_dedupe_keeps_first_spelling():
    # "JOHN DOE" is a case-variant of "John Doe"; the first spelling is kept.
    assert split_parties("John Doe, JOHN DOE, Jane") == ("John Doe", "Jane")


def test_split_parties_collapses_internal_whitespace():
    assert split_parties("John    Doe") == ("John Doe",)
    assert split_parties(["  Jane\tRoe  "]) == ("Jane Roe",)


def test_split_parties_drops_empties():
    assert split_parties("Alice,,  ; / Bob") == ("Alice", "Bob")


def test_split_parties_caps_at_twenty():
    names = [f"Person {i}" for i in range(30)]
    result = split_parties(names)
    assert len(result) == 20
    assert result[0] == "Person 0"
    assert result[-1] == "Person 19"


# --------------------------------------------------------------------------------------
# derive_duration
# --------------------------------------------------------------------------------------


def test_duration_explicit_wins_over_timestamps():
    # Explicit 42s is returned even though the timestamps imply 3600s.
    assert derive_duration("2026-01-01T10:00:00", "2026-01-01T11:00:00", 42) == 42


def test_duration_explicit_zero_is_kept():
    assert derive_duration(None, None, 0) == 0


def test_duration_explicit_negative_is_none():
    assert derive_duration(None, None, -5) is None


def test_duration_from_two_iso_timestamps():
    assert derive_duration("2026-01-01T10:00:00", "2026-01-01T10:02:30", None) == 150


def test_duration_reversed_timestamps_is_none():
    assert derive_duration("2026-01-01T10:05:00", "2026-01-01T10:00:00", None) is None


def test_duration_non_iso_string_is_none():
    assert derive_duration("not-a-date", "also-bad", None) is None


def test_duration_single_timestamp_is_none():
    assert derive_duration("2026-01-01T10:00:00", None, None) is None
    assert derive_duration(None, "2026-01-01T10:00:00", None) is None


def test_duration_all_none_is_none():
    assert derive_duration(None, None, None) is None


# --------------------------------------------------------------------------------------
# summarize
# --------------------------------------------------------------------------------------


def test_summarize_blank_is_empty():
    assert summarize("", "") == ""


def test_summarize_explicit_beats_transcript():
    assert summarize("A long transcript about many things.", "  Short note  ") == "Short note"


def test_summarize_explicit_truncates_with_ellipsis():
    explicit = "x" * 400
    result = summarize("", explicit)
    assert len(result) == 280
    assert result.endswith("...")
    assert result[:277] == "x" * 277


def test_summarize_explicit_exactly_280_not_truncated():
    explicit = "y" * 280
    result = summarize("", explicit)
    assert result == explicit
    assert not result.endswith("...")


def test_summarize_first_sentence_of_transcript():
    transcript = "Please raise the slab level. Then call me back tomorrow."
    assert summarize(transcript, "") == "Please raise the slab level"


def test_summarize_long_single_run_caps_at_280():
    transcript = "z" * 500  # no sentence break at all
    result = summarize(transcript, "")
    assert len(result) == 280
    assert result.endswith("...")


def test_summarize_long_first_sentence_caps_at_280():
    # A first "sentence" longer than 280 chars (no early break) is capped.
    transcript = "a" * 350 + ". short tail."
    result = summarize(transcript, "")
    assert len(result) == 280
    assert result.endswith("...")


# --------------------------------------------------------------------------------------
# extract_instructions
# --------------------------------------------------------------------------------------


def test_extract_instructions_blank_is_empty():
    assert extract_instructions("") == ()


def test_extract_instructions_picks_cue_sentences():
    transcript = (
        "Hi there, how are you. Please change the door schedule. "
        "The weather is nice today. Make sure to send the revised drawing."
    )
    result = extract_instructions(transcript)
    assert result == (
        "Please change the door schedule",
        "Make sure to send the revised drawing",
    )


def test_extract_instructions_ignores_small_talk():
    transcript = "How are you doing. Nice weather we are having. Talk soon."
    assert extract_instructions(transcript) == ()


def test_extract_instructions_handles_newlines():
    transcript = "Confirm the order\nThanks a lot\nHold the delivery"
    assert extract_instructions(transcript) == (
        "Confirm the order",
        "Hold the delivery",
    )


def test_extract_instructions_dedupes():
    transcript = "Please confirm. PLEASE CONFIRM. Please confirm."
    assert extract_instructions(transcript) == ("Please confirm",)


def test_extract_instructions_respects_limit():
    sentences = ". ".join(f"Please do task {i}" for i in range(20))
    result = extract_instructions(sentences, limit=3)
    assert len(result) == 3
    assert result[0] == "Please do task 0"


def test_extract_instructions_word_boundary_no_false_positive():
    # "address" contains "add" but must NOT be treated as the cue "add".
    assert extract_instructions("We will address that later") == ()


def test_extract_instructions_apostrophe_cue():
    assert extract_instructions("Do not pour the slab. Don't touch the rebar.") == (
        "Do not pour the slab",
        "Don't touch the rebar",
    )


def test_extract_instructions_multiword_cue():
    assert extract_instructions("Need to revise the layout by tomorrow") == ("Need to revise the layout by tomorrow",)


def test_instruction_cues_is_frozenset():
    assert isinstance(INSTRUCTION_CUES, frozenset)
    assert "please" in INSTRUCTION_CUES


# --------------------------------------------------------------------------------------
# normalize (end to end)
# --------------------------------------------------------------------------------------


def test_normalize_empty_input():
    result = normalize(PhoneLogInput())
    assert isinstance(result, NormalizedPhoneLog)
    assert result.direction == "unknown"
    assert result.channel == "phone"
    assert result.duration_seconds is None
    assert result.summary == ""
    assert result.instructions == ()
    assert result.parties == ()
    assert result.word_count == 0


def test_normalize_realistic_call():
    item = PhoneLogInput(
        raw_parties="John Doe (us) -> Acme site office",
        direction="incoming",
        started_at="2026-01-15T09:00:00",
        ended_at="2026-01-15T09:03:20",
        transcript=(
            "Good morning. Please change the column spacing on grid B. "
            "Make sure to send the revised drawing by tomorrow. Thanks."
        ),
        channel="call",
    )
    result = normalize(item)
    assert result.parties == ("John Doe (us)", "Acme site office")
    assert result.direction == "inbound"
    assert result.channel == "phone"
    assert result.duration_seconds == 200
    assert result.summary == "Good morning"
    assert result.instructions == (
        "Please change the column spacing on grid B",
        "Make sure to send the revised drawing by tomorrow",
    )
    assert result.word_count == 20


def test_normalize_explicit_duration_and_summary_override():
    item = PhoneLogInput(
        raw_parties=["Alice", "Bob"],
        direction="called",
        started_at="2026-01-15T09:00:00",
        ended_at="2026-01-15T10:00:00",
        duration_seconds=15,
        transcript="Please hold the pour.",
        summary="Agreed to hold the concrete pour.",
        channel="voicemail",
    )
    result = normalize(item)
    assert result.direction == "outbound"
    assert result.channel == "voice_note"
    assert result.duration_seconds == 15  # explicit wins over the 3600s timestamp span
    assert result.summary == "Agreed to hold the concrete pour."
    assert result.instructions == ("Please hold the pour",)
    assert result.word_count == 4


def test_normalized_record_is_frozen():
    result = normalize(PhoneLogInput())
    try:
        result.direction = "inbound"  # type: ignore[misc]
    except Exception as exc:  # noqa: BLE001 - we only care that it raised
        assert exc is not None
    else:
        raise AssertionError("NormalizedPhoneLog should be frozen")
