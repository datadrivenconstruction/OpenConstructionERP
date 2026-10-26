# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure rules behind minutes from audio: glossary, corrections, proposals, retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.meetings import audio_logic as al

PEOPLE = [
    {"name": "Anna Berg", "contact_id": "c-anna"},
    {"name": "Tomasz Nowak", "contact_id": "c-tom"},
    {"name": "Mueller Bau GmbH", "contact_id": None},
]
RFIS = [{"id": "rfi-12", "number": "012", "subject": "Rebar at grid C"}]
POSITIONS = [{"id": "pos-1", "ordinal": "03.02.010", "description": "Reinforced concrete slab C30/37"}]


# ── Glossary ─────────────────────────────────────────────────────────────────


def test_seed_terms_fold_duplicates_and_skip_existing() -> None:
    merged = al.merge_seed_terms(
        [
            {"term": "Anna  Berg", "kind": "person", "source": "attendees"},
            {"term": "anna berg", "kind": "person", "source": "contacts"},
            {"term": "Site office", "kind": "bogus", "source": "bogus"},
            {"term": "x"},
            {"term": "12.5"},
            {"term": "Kran 2", "kind": "term", "source": "project"},
        ],
        existing_keys={"kran 2"},
    )
    assert [m["term"] for m in merged] == ["Anna Berg", "Site office"]
    assert merged[0]["source"] == "attendees"
    assert merged[1]["kind"] == "term" and merged[1]["source"] == "manual"


def test_transcription_hint_puts_names_first_and_stays_bounded() -> None:
    terms = [{"term": f"Term {i}", "kind": "term"} for i in range(200)] + [{"term": "Anna Berg", "kind": "person"}]
    hint = al.build_transcription_hint(terms, limit=100)
    assert hint.startswith("Anna Berg")
    assert len(hint) <= 100


def test_glossary_block_lists_meaning_and_mishearings() -> None:
    block = al.build_glossary_block(
        [{"term": "WU", "kind": "abbreviation", "expansion": "watertight concrete", "aliases": ["view"]}]
    )
    assert "WU (abbreviation): watertight concrete" in block
    assert "often misheard as: view" in block


def test_aliases_replace_whole_words_only() -> None:
    terms = [{"term": "Müller", "aliases": ["Mueler", "Miller"]}]
    text, n = al.apply_aliases("Mueler said Millerstrasse is closed, ask miller.", terms)
    assert text == "Müller said Millerstrasse is closed, ask Müller."
    assert n == 2


def test_near_miss_spellings_are_offered_not_exact_ones() -> None:
    terms = [{"term": "Tomasz Nowak"}, {"term": "WU"}]
    suggestions = al.suggest_corrections("Tomas Nowak will check. Tomasz Nowak agreed.", terms)
    assert suggestions == [
        {"heard": "Tomas Nowak", "term": "Tomasz Nowak", "confidence": pytest.approx(0.96, abs=0.02)}
    ]


def test_clean_aliases_drops_the_term_itself_and_duplicates() -> None:
    assert al.clean_aliases("Mueler, mueler, Müller, , x", term="Müller") == ["Mueler"]


# ── Language and speakers ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "code"),
    [("german", "de"), ("de-DE", "de"), ("Tagalog", "fil"), ("pt_BR", "pt"), ("", None), ("klingon!", None)],
)
def test_language_code(raw: str, code: str | None) -> None:
    assert al.language_code(raw) == code


def test_render_transcript_uses_speaker_names() -> None:
    segs = al.normalize_segments([{"speaker": "S1", "text": " Pour on Friday "}, {"text": ""}, {"text": "ok"}])
    speakers = al.normalize_speakers({"S1": {"name": "Anna Berg"}, "S9": "Ghost"}, al.speaker_labels(segs))
    assert speakers == {"S1": {"name": "Anna Berg", "contact_id": None}}
    assert al.render_transcript(segs, speakers) == "Anna Berg: Pour on Friday\nok"


# ── Owners, dates, links ─────────────────────────────────────────────────────


def test_owner_matching_exact_partial_fuzzy_and_unknown() -> None:
    assert al.match_owner("anna berg", PEOPLE)["owner_contact_id"] == "c-anna"
    partial = al.match_owner("Tomasz", PEOPLE)
    assert partial["owner_contact_id"] == "c-tom" and partial["owner_confidence"] == 0.85
    fuzzy = al.match_owner("Ana Berg", PEOPLE)
    assert fuzzy["owner_name"] == "Anna Berg" and 0.8 <= fuzzy["owner_confidence"] < 1
    unknown = al.match_owner("Site office", PEOPLE)
    assert unknown == {"owner_name": "Site office", "owner_contact_id": None, "owner_confidence": 0.0}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-11-03", "2026-11-03"),
        ("2026-02-30", None),
        ("tomorrow", "2026-10-22"),
        ("Friday", "2026-10-23"),
        ("by wednesday", "2026-10-28"),
        ("next week", "2026-10-28"),
        ("end of week", "2026-10-23"),
        ("end of month", "2026-10-31"),
        ("in 2 weeks", "2026-11-04"),
        ("when the crane is free", None),
    ],
)
def test_due_dates_resolve_against_the_meeting_date(raw: str, expected: str | None) -> None:
    # 2026-10-21 is a Wednesday.
    assert al.resolve_due_date(raw, "2026-10-21") == expected


def test_entity_links_only_point_at_existing_records() -> None:
    assert al.detect_entity_link("answer RFI-12 by Friday", RFIS, POSITIONS)["id"] == "rfi-12"
    assert al.detect_entity_link("re-measure 03.02.010", RFIS, POSITIONS)["type"] == "boq_position"
    assert al.detect_entity_link("RFI 99 and 01.01.001", RFIS, POSITIONS) is None
    assert al.detect_entity_link("text", RFIS, POSITIONS, hint="RFI #12")["label"].startswith("RFI 012")


# ── Proposals ────────────────────────────────────────────────────────────────


def _build(llm: dict | None, heuristic: dict | None = None, transcript: str = "") -> dict:
    return al.build_proposals(
        llm,
        heuristic=heuristic,
        people=PEOPLE,
        rfis=RFIS,
        positions=POSITIONS,
        meeting_date="2026-10-21",
        transcript=transcript,
        glossary=[{"term": "Tomasz Nowak"}],
        language="de",
        now=datetime(2026, 10, 21, tzinfo=UTC),
    )


def test_ai_proposals_are_pending_with_confidence_owner_due_and_link() -> None:
    result = _build(
        {
            "summary": "Slab pour moved.",
            "decisions": [{"text": "Pour on Friday", "confidence": 0.9, "quote": "we pour Friday"}, "", None],
            "action_items": [
                {"task": "Answer RFI-12", "owner": "Anna", "due": "next week", "confidence": 1.7},
                {"task": ""},
                "Order formwork",
            ],
            "open_questions": ["Who pays the crane?"],
            "spelling_corrections": [
                {"heard": "Tomas Nowak", "term": "Tomasz Nowak"},
                {"heard": "absent", "term": "X"},
            ],
            "confidence": 0.8,
        },
        transcript="Tomas Nowak asked about RFI-12.",
    )
    assert result["ai_generated"] is True and result["language"] == "de"
    kinds = [i["kind"] for i in result["items"]]
    assert kinds == ["summary", "decision", "action", "action", "question", "correction"]
    assert all(i["status"] == "pending" for i in result["items"])
    assert len({i["id"] for i in result["items"]}) == len(result["items"])
    action = result["items"][2]
    assert action["owner_contact_id"] == "c-anna"
    assert action["due_date"] == "2026-10-28" and action["due_hint"] == "next week"
    assert action["linked_entity"]["id"] == "rfi-12"
    assert action["confidence"] == 1.0
    assert result["items"][3]["confidence"] == 0.8
    # The model's correction and the glossary near-miss are the same; listed once.
    assert [i["heard"] for i in result["items"] if i["kind"] == "correction"] == ["Tomas Nowak"]


def test_heuristic_proposals_are_low_confidence() -> None:
    result = _build(
        None,
        heuristic={
            "decisions": [{"decision": "We agreed to pour Friday", "made_by": ""}],
            "action_items": [
                {"description": "Anna will send drawings", "owner_name": "Anna Berg", "due_date": "Friday"}
            ],
        },
    )
    assert result["ai_generated"] is False
    assert {i["confidence"] for i in result["items"]} == {al.HEURISTIC_CONFIDENCE}
    assert result["items"][1]["due_date"] == "2026-10-23"


def test_no_ai_and_no_heuristic_gives_no_items() -> None:
    assert _build(None)["items"] == []


def test_action_needs_owner_and_iso_due_date_to_be_confirmed() -> None:
    assert al.action_confirm_problems({"text": "x", "owner_name": "Anna", "due_date": "2026-10-30"}) == []
    problems = al.action_confirm_problems({"text": "x", "owner_name": "", "due_date": "Friday"})
    assert len(problems) == 2


def test_merge_review_keeps_kind_and_validates_links() -> None:
    item = {"id": "a1", "kind": "action", "text": "old", "confidence": 0.5}
    merged = al.merge_review(
        item, {"text": " new ", "linked_entity": {"type": "invoice", "id": "1"}, "kind": "summary"}
    )
    assert merged["text"] == "new" and merged["kind"] == "action" and merged["linked_entity"] is None
    assert item["text"] == "old"


def test_proposal_counts() -> None:
    counts = al.proposal_counts({"items": [{"status": "pending"}, {"status": "confirmed"}, {"status": "pending"}, "x"]})
    assert counts == {"pending": 2, "confirmed": 1, "rejected": 0}


# ── Consent and retention ────────────────────────────────────────────────────


def test_consent_is_needed_for_audio_and_live_capture_only() -> None:
    assert al.consent_required("upload", True)
    assert al.consent_required("browser_speech", False)
    assert not al.consent_required("manual", False)


def test_audio_expiry_and_overdue() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    assert al.audio_expiry(now, 0) is None
    assert al.audio_expiry(now, 30) == now + timedelta(days=30)
    assert al.audio_overdue({"audio_storage_key": "k", "audio_expires_at": now - timedelta(days=1)}, now)
    assert not al.audio_overdue({"audio_storage_key": "", "audio_expires_at": now - timedelta(days=1)}, now)
    assert not al.audio_overdue({"audio_storage_key": "k", "audio_expires_at": None}, now)
    assert al.audio_overdue({"audio_storage_key": "k", "audio_expires_at": "2026-10-01T00:00:00"}, now)
