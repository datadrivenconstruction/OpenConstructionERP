# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the heuristic delay-signal detector.

Covers per-category detection from representative sentences, the bounded
confidence score and its ordering, the empty / no-match contract, and the
email-driven entry point fed by a parsed message.
"""

from __future__ import annotations

from app.modules.inbound_email.delay_detection import (
    CATEGORY_ACTIVITIES,
    CATEGORY_PHRASES,
    DelaySignal,
    detect_delays,
    detect_from_email,
)
from app.modules.inbound_email.eml_parser import parse_eml


def _categories(signals: list[DelaySignal]) -> set[str]:
    return {s.category for s in signals}


def test_weather_detected() -> None:
    signals = detect_delays("Heavy rain and high winds stopped the pour today.")
    assert "weather" in _categories(signals)
    weather = next(s for s in signals if s.category == "weather")
    assert weather.matched_phrases
    assert weather.suggested_activities == CATEGORY_ACTIVITIES["weather"]


def test_late_information_detected() -> None:
    signals = detect_delays("We are still awaiting information and the RFI overdue list is growing.")
    assert "late_information" in _categories(signals)


def test_unforeseen_ground_detected() -> None:
    signals = detect_delays("Excavation hit rock and groundwater, plus a buried obstruction.")
    assert "unforeseen_ground" in _categories(signals)
    ground = next(s for s in signals if s.category == "unforeseen_ground")
    # rock, groundwater, obstruction, buried obstruction -> saturates at 1.0.
    assert ground.confidence == 1.0


def test_site_access_detected() -> None:
    signals = detect_delays("The employer denied access; the site closed all week.")
    assert "site_access" in _categories(signals)


def test_variation_detected() -> None:
    signals = detect_delays("A variation order was issued for additional works.")
    assert "variation" in _categories(signals)


def test_resource_shortage_detected() -> None:
    signals = detect_delays("A material shortage and plant breakdown halted progress.")
    assert "resource_shortage" in _categories(signals)


def test_statutory_approval_detected() -> None:
    signals = detect_delays("Work is held awaiting permit and planning approval.")
    assert "statutory_approval" in _categories(signals)


def test_design_change_detected() -> None:
    signals = detect_delays("Revised drawings arrived after a late design change.")
    assert "design_change" in _categories(signals)


def test_confidence_is_bounded_and_scales() -> None:
    one = detect_delays("There was rain on site.")
    weather_one = next(s for s in one if s.category == "weather")
    # A single distinct phrase scores 1/3.
    assert abs(weather_one.confidence - (1.0 / 3.0)) < 1e-9

    many = detect_delays("Rain, storm, flooding and snow with frost all week.")
    weather_many = next(s for s in many if s.category == "weather")
    assert weather_many.confidence == 1.0


def test_results_sorted_by_confidence_then_category() -> None:
    # Strong ground signal (>=3 phrases) and a weak single-phrase variation.
    text = "Rock, groundwater and an obstruction were found. One variation noted."
    signals = detect_delays(text)
    assert len(signals) >= 2
    confidences = [s.confidence for s in signals]
    assert confidences == sorted(confidences, reverse=True)
    # Ground (1.0) must rank ahead of the weaker variation signal.
    assert signals[0].category == "unforeseen_ground"


def test_ties_break_on_category_name() -> None:
    # Two categories each fire on a single phrase -> equal confidence; the
    # alphabetically earlier category name must come first.
    signals = detect_delays("There was rain. A variation was issued.")
    pair = [s for s in signals if s.category in {"variation", "weather"}]
    assert [s.category for s in pair] == ["variation", "weather"]
    assert pair[0].confidence == pair[1].confidence


def test_matched_phrases_are_distinct() -> None:
    signals = detect_delays("rain rain rain and more rain")
    weather = next(s for s in signals if s.category == "weather")
    assert weather.matched_phrases.count("rain") == 1


def test_case_insensitive_matching() -> None:
    signals = detect_delays("HEAVY RAIN and a STORM")
    assert "weather" in _categories(signals)


def test_word_boundary_avoids_false_positive() -> None:
    # "icebreaker" must not trigger the "ice" weather phrase, and "rocket"
    # must not trigger the "rock" ground phrase.
    signals = detect_delays("The icebreaker meeting launched the rocket model.")
    assert "weather" not in _categories(signals)
    assert "unforeseen_ground" not in _categories(signals)


def test_multiword_phrase_tolerates_extra_whitespace() -> None:
    signals = detect_delays("We are awaiting    information from the designer.")
    assert "late_information" in _categories(signals)


def test_empty_text_returns_empty_list() -> None:
    assert detect_delays("") == []


def test_no_match_returns_empty_list() -> None:
    assert detect_delays("The weekly meeting went well and everyone agreed.") == []


def test_detect_from_email_uses_subject_and_body() -> None:
    raw = (
        "From: site@contractor.example\r\n"
        "To: pm@employer.example\r\n"
        "Subject: Adverse weather delay\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Excavation hit rock and groundwater this morning.\r\n"
    )
    parsed = parse_eml(raw)
    signals = detect_from_email(parsed)
    cats = _categories(signals)
    # Cause named only in the subject (weather) and one in the body (ground).
    assert "weather" in cats
    assert "unforeseen_ground" in cats


def test_detect_from_email_empty_body_and_subject() -> None:
    raw = (
        "From: x@a.example\r\n"
        "To: y@b.example\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "Routine update with nothing notable.\r\n"
    )
    parsed = parse_eml(raw)
    assert detect_from_email(parsed) == []


def test_every_category_has_phrases_and_activities() -> None:
    # Guard the maps stay aligned: each category has triggers and a fragnet.
    assert set(CATEGORY_PHRASES) == set(CATEGORY_ACTIVITIES)
    for category, phrases in CATEGORY_PHRASES.items():
        assert phrases, f"{category} has no trigger phrases"
        assert CATEGORY_ACTIVITIES[category], f"{category} has no activities"
