"""R5 deterministic parts and the model path (replayed fixture). No ERP app and no live model needed:
runs inside the ERP tree (app.modules.design) and standalone from this repo (design package)."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

try:
    from app.modules.design import brief_draft, brief_fields, brief_model, brief_parse
    from app.modules.design.brief_extract import extract_brief
except ImportError:  # standalone run from ddc-erp-link
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from design import brief_draft, brief_fields, brief_model, brief_parse  # type: ignore[no-redef]
    from design.brief_extract import extract_brief  # type: ignore[no-redef]

FIX = Path(__file__).parent / "fixtures" / "brief"
DOC = "2344d010-88d8-4e0c-811d-219134150421"
PROJECT = "746402cb-14a8-430c-b3b9-9c6908fa75d7"
BRIEF = "d687671c-a6c3-4a73-8aa1-230664a927be"


def pages(name: str) -> list[str]:
    return (FIX / name).read_text(encoding="utf-8").split("\f")


def ctx(locale="de", defaults=None, base=None) -> brief_draft.DraftContext:
    return brief_draft.DraftContext(PROJECT, BRIEF, locale=locale, defaults=defaults or {}, base=base)


def run(coro):
    return asyncio.run(coro)


def values(draft) -> dict:
    prov = draft.brief.get("provenance", {})
    return {p: brief_fields.get_at(draft.brief, p) for p in prov}


# ── numbers ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,hint,expected,alt",
    [
        ("1.250,5", None, 1250.5, []),
        ("1,250.5", None, 1250.5, []),
        ("1 250,5", None, 1250.5, []),
        ("1'250.5", None, 1250.5, []),
        ("4.250.000", None, 4250000, []),
        ("3,0", None, 3.0, []),
        ("12.5", None, 12.5, []),
        ("1.250", ",", 1250, []),
        ("1.250", ".", 1.25, []),
        ("1,250", ".", 1250, []),
        ("1.250", None, 1250, [1.25]),
    ],
)
def test_parse_number(raw, hint, expected, alt):
    value, alternatives = brief_parse.parse_number(raw, hint)
    assert value == pytest.approx(expected) and alternatives == pytest.approx(alt)


def test_language_and_decimal_hint():
    assert brief_parse.detect_language((FIX / "leipzig_de.txt").read_text(encoding="utf-8")) == "de"
    assert brief_parse.detect_language((FIX / "office_en.txt").read_text(encoding="utf-8")) == "en"
    assert brief_parse.detect_language((FIX / "house_ru.txt").read_text(encoding="utf-8")) == "ru"
    assert brief_parse.detect_language("zu kurz") is None
    assert brief_parse.decimal_hint("de") == "," and brief_parse.decimal_hint("en") == "."


# ── anchoring ───────────────────────────────────────────────────────────────


def test_anchor_finds_quote_across_whitespace_and_corrects_page():
    pg = ["erste  Seite\nmit   Text", "Anzahl der\nGeschosse: 5 – oberirdisch"]
    assert brief_parse.anchor_quote(pg, "Anzahl der Geschosse: 5", page_hint=1) == (2, "Anzahl der Geschosse: 5")
    assert brief_parse.anchor_quote(pg, "ERSTE SEITE mit text", page_hint=2) == (1, "erste Seite mit Text")
    assert brief_parse.anchor_quote(pg, "5 - oberirdisch") == (2, "5 – oberirdisch")


def test_anchor_refuses_invented_or_elided_quotes():
    pg = ["Geschosse: 5"]
    assert brief_parse.anchor_quote(pg, "Geschosse: 6") is None
    assert brief_parse.anchor_quote(pg, "Geschosse ... 5") is None
    assert brief_parse.anchor_quote(pg, "") is None
    assert brief_parse.anchor_quote([], "x y z") is None


def test_every_rule_quote_is_found_on_its_page():
    for name in ("leipzig_de.txt", "office_en.txt", "house_ru.txt"):
        pg = pages(name)
        for c in brief_parse.extract_candidates(pg, document_id=DOC):
            assert brief_parse.anchor_quote(pg, c.quote, c.page) == (c.page, c.quote), (name, c)


def test_value_supported():
    assert brief_parse.value_supported("/massing/floors_above", 5, "Anzahl der Geschosse: 5")
    assert brief_parse.value_supported("/massing/floors_above", 5, "fünf Vollgeschosse")
    assert not brief_parse.value_supported("/massing/floors_above", 6, "Anzahl der Geschosse: 5")
    assert brief_parse.value_supported("/budget/amount", 4500000, "Budget: 4,5 Mio. €")
    assert brief_parse.value_supported("/massing/gross_floor_area_m2", 116.13, "1.250 sq ft")
    assert brief_parse.value_supported("/site/site_coverage_max", 0.4, "GRZ 40 %")
    assert brief_parse.value_supported("/use/category", "office", "Bürogebäude")


# ── rules on the fixture documents (known answers) ──────────────────────────

LEIPZIG = {
    "/massing/floors_above": 5,
    "/massing/floors_below": 1,
    "/massing/floor_height_m": 3.0,
    "/massing/gross_floor_area_m2": 4250,
    "/programme/parking_spaces": 40,
    "/structure/system": "masonry",
    "/structure/foundation": "raft",
    "/envelope/roof": "flat",
    "/massing/lift": True,
    "/budget/amount": 4500000,
    "/budget/currency": "EUR",
    "/budget/includes_vat": True,
    "/site/max_height_m": 16.5,
    "/site/site_coverage_max": 0.4,
    "/site/floor_area_ratio_max": 1.2,
    "/use/category": "residential_multi",
    "/country": "DE",
    "/massing/footprint/width_m": 34,
    "/massing/footprint/depth_m": 12,
}


def test_leipzig_precision_and_recall():
    draft = run(
        extract_brief([brief_model.SourceDoc(DOC, "leipzig.txt", "document", pages("leipzig_de.txt"))], ctx())
    ).draft
    got = values(draft)
    wrong = {p: (got[p], v) for p, v in LEIPZIG.items() if p in got and got[p] != pytest.approx(v)}
    assert not wrong
    assert set(LEIPZIG) <= set(got), set(LEIPZIG) - set(got)
    assert set(got) - set(LEIPZIG) == {"/site/address"}  # nothing else, and the bicycle spaces are not parking
    assert got["/programme/parking_spaces"] == 40


def test_every_value_has_a_citation_and_is_proposed():
    draft = run(
        extract_brief([brief_model.SourceDoc(DOC, "leipzig.txt", "document", pages("leipzig_de.txt"))], ctx())
    ).draft
    for pointer, entry in draft.brief["provenance"].items():
        assert entry["status"] == "proposed"
        src = entry["sources"][0]
        assert src["document_id"] == DOC and src["page"] in (1, 2) and src["quote"]
        assert brief_parse.anchor_quote(pages("leipzig_de.txt"), src["quote"], src["page"])


def test_english_units_and_ambiguous_currency():
    cands = {c.pointer: c for c in brief_parse.extract_candidates(pages("office_en.txt"), document_id=DOC)}
    assert cands["/massing/floors_above"].value == 8 and cands["/massing/floors_below"].value == 2
    assert cands["/massing/gross_floor_area_m2"].value == 1250 or cands["/massing/gross_floor_area_m2"].alternatives
    assert cands["/massing/floor_height_m"].value == pytest.approx(3.658, abs=1e-3)
    assert cands["/site/max_height_m"].value == pytest.approx(13.716, abs=1e-3)
    assert cands["/budget/amount"].value == 2_500_000
    assert "/budget/currency" not in cands  # a bare dollar sign does not name a currency


def test_english_draft_asks_for_currency_and_missing_required():
    draft = run(
        extract_brief([brief_model.SourceDoc(DOC, "o.txt", "document", pages("office_en.txt"))], ctx("en"))
    ).draft
    qs = {q["pointer"]: q for q in draft.brief["questions"]}
    assert qs["/budget/currency"]["reason"] == "missing"
    assert {"/country", "/locale", "/depth_level"} <= set(qs)
    assert qs["/country"]["options"][0] == "DE" and qs["/depth_level"]["options"] == list(brief_fields.DEPTH_LEVELS)
    assert "country" in qs["/country"]["text"]


def test_russian_document():
    cands = {c.pointer: c for c in brief_parse.extract_candidates(pages("house_ru.txt"), document_id=DOC)}
    assert cands["/massing/floors_above"].value == 9
    assert cands["/massing/gross_floor_area_m2"].value == pytest.approx(6250.5)
    assert cands["/programme/parking_spaces"].value == 60
    assert cands["/budget/amount"].value == 120_000_000 and cands["/budget/currency"].value == "RUB"
    assert cands["/use/category"].value == "residential_multi"


def test_ambiguous_number_becomes_a_question_not_a_value():
    pg = ["BGF: 1.250 m2"]  # too short for a language, so the separator is unsettled
    draft = run(extract_brief([brief_model.SourceDoc(DOC, "x.txt", "document", pg)], ctx("en"))).draft
    assert "/massing/gross_floor_area_m2" not in draft.brief.get("provenance", {})
    q = next(q for q in draft.brief["questions"] if q["pointer"] == "/massing/gross_floor_area_m2")
    assert q["reason"] == "ambiguous" and q["options"] == [1250, 1.25]


def test_contradiction_between_documents_is_a_question():
    docs = [
        brief_model.SourceDoc("a" * 8 + DOC[8:], "a.txt", "document", pages("conflict_a.txt")),
        brief_model.SourceDoc("b" * 8 + DOC[8:], "b.txt", "document", pages("conflict_b.txt")),
    ]
    draft = run(extract_brief(docs, ctx("de"))).draft
    assert "/massing/floors_above" not in draft.brief.get("provenance", {})
    q = next(q for q in draft.brief["questions"] if q["pointer"] == "/massing/floors_above")
    assert q["reason"] == "contradiction" and sorted(q["options"]) == [5, 6]
    assert "a.txt" in q["text"] and "b.txt" in q["text"] and "Geschosse" in q["text"]
    assert "default" not in q  # a tie is not settled for the person


def test_same_value_in_two_documents_merges_sources():
    a = brief_model.SourceDoc("a" * 8 + DOC[8:], "a.txt", "document", pages("conflict_a.txt"))
    b = brief_model.SourceDoc("b" * 8 + DOC[8:], "b.txt", "document", ["Geschosse: 5"])
    draft = run(extract_brief([a, b], ctx())).draft
    assert len(draft.brief["provenance"]["/massing/floors_above"]["sources"]) == 2


def test_pasted_text_cites_as_text_without_document_id():
    doc = brief_model.SourceDoc(None, "Pasted description", "text", ["Bürogebäude mit 12 Geschossen"])
    draft = run(extract_brief([doc], ctx())).draft
    src = draft.brief["provenance"]["/massing/floors_above"]["sources"][0]
    assert src == {"kind": "text", "page": 1, "quote": "12 Geschossen"}


def test_ordinal_floor_and_basement_are_not_floor_counts():
    pg = ["Büro im 2. Obergeschoss, Lager im 1. Untergeschoss, Keller im Basement 2 floors"]
    got = [
        c
        for c in brief_parse.extract_candidates(pg, document_id=DOC, language="de")
        if c.pointer == "/massing/floors_above"
    ]
    assert got == []


def test_defaults_from_project_settings_and_confirmed_values_survive():
    base = {
        "schema": "ddc-brief/1",
        "massing": {"floors_above": 7},
        "provenance": {
            "/massing/floors_above": {
                "status": "confirmed",
                "confirmed_by": DOC,
                "confirmed_at": "2026-11-12T10:00:00Z",
            }
        },
    }
    draft = run(
        extract_brief(
            [brief_model.SourceDoc(DOC, "l.txt", "document", pages("leipzig_de.txt"))],
            ctx(defaults={"/country": "DE", "/locale": "de", "/name": "Wohnhaus"}, base=base),
        )
    ).draft
    assert draft.brief["massing"]["floors_above"] == 7
    assert draft.brief["provenance"]["/massing/floors_above"]["status"] == "confirmed"
    assert draft.brief["provenance"]["/locale"]["status"] == "default"
    assert draft.brief["country"] == "DE"
    assert draft.brief["provenance"]["/country"]["status"] == "proposed"  # sourced beats the default
    asked = {q["pointer"] for q in draft.brief["questions"]}
    assert asked == {"/depth_level"}  # country, locale, use and floors are all settled
    # the floors were read again and left as confirmed: the summary says so, so the screen does not say "nothing found"
    assert brief_draft.summarize(draft)["confirmed"] == ["/massing/floors_above"]


def test_rerun_replaces_unconfirmed_values_of_the_earlier_run():
    first = run(extract_brief([brief_model.SourceDoc(DOC, "l.txt", "document", pages("leipzig_de.txt"))], ctx())).draft
    second = run(
        extract_brief([brief_model.SourceDoc(DOC, "o.txt", "document", pages("office_en.txt"))], ctx(base=first.brief))
    ).draft
    assert second.brief["massing"]["floors_above"] == 8
    assert "structure" not in second.brief  # no stale value from the first run


# ── questions and answers ────────────────────────────────────────────────────


def test_question_ids_are_stable_and_texts_localised():
    docs = [brief_model.SourceDoc(DOC, "x.txt", "document", ["nichts Brauchbares hier"])]
    d1 = run(extract_brief(docs, ctx("de"))).draft
    d2 = run(extract_brief(docs, ctx("ru"))).draft
    d3 = run(extract_brief(docs, ctx("fr"))).draft
    assert [q["id"] for q in d1.brief["questions"]] == [q["id"] for q in d2.brief["questions"]]
    assert [q["pointer"] for q in d1.brief["questions"]] == list(brief_fields.REQUIRED)
    texts = {q["pointer"]: q["text"] for q in d1.brief["questions"]}
    assert "Land des Projekts" in texts["/country"]
    assert "страна проекта" in {q["pointer"]: q["text"] for q in d2.brief["questions"]}["/country"]
    assert "country of the project" in d3.brief["questions"][0]["text"]  # unshipped locale falls back to English


def test_answers_confirm_fields_and_close_questions():
    draft = run(extract_brief([brief_model.SourceDoc(DOC, "x.txt", "document", ["leer"])], ctx("en"))).draft
    ids = {q["pointer"]: q["id"] for q in draft.brief["questions"]}
    at = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    out = brief_draft.apply_answers(
        draft.brief,
        [
            {"question_id": ids["/country"], "value": "de"},
            {"question_id": ids["/massing/floors_above"], "value": "5"},
            {"question_id": ids["/use/category"], "value": "office"},
        ],
        user_id=BRIEF,
        at=at,
    )
    assert out["country"] == "DE" and out["massing"]["floors_above"] == 5 and out["use"]["category"] == "office"
    entry = out["provenance"]["/country"]
    assert (
        entry["status"] == "confirmed"
        and entry["confirmed_by"] == BRIEF
        and entry["confirmed_at"] == "2026-11-12T12:00:00Z"
    )
    assert {q["pointer"] for q in out["questions"]} == {"/locale", "/depth_level"}
    assert draft.brief["questions"]  # input untouched


def test_bad_answer_rejects_the_whole_batch():
    draft = run(extract_brief([brief_model.SourceDoc(DOC, "x.txt", "document", ["leer"])], ctx("en"))).draft
    ids = {q["pointer"]: q["id"] for q in draft.brief["questions"]}
    with pytest.raises(brief_draft.AnswerError) as err:
        brief_draft.apply_answers(
            draft.brief,
            [
                {"question_id": ids["/country"], "value": "DE"},
                {"question_id": ids["/massing/floors_above"], "value": 500},
                {"question_id": "q-nope", "value": 1},
                {"question_id": ids["/depth_level"], "use_default": True},
            ],
            user_id=BRIEF,
        )
    assert len(err.value.errors) == 3


def test_answer_by_default_needs_a_default():
    docs = [brief_model.SourceDoc(DOC, "c.txt", "document", ["Mehrfamilienhaus", "Hotel", "Hotel"])]
    draft = run(extract_brief(docs, ctx("en"))).draft
    q = next(q for q in draft.brief["questions"] if q["pointer"] == "/use/category")
    assert q["reason"] == "ambiguous" and q["default"] == "hotel"
    out = brief_draft.apply_answers(draft.brief, [{"question_id": q["id"], "use_default": True}], user_id=BRIEF)
    assert out["use"]["category"] == "hotel" and out["provenance"]["/use/category"]["status"] == "confirmed"


# ── model path with a replayed reply ─────────────────────────────────────────


class Replay:
    """Returns a recorded reply for every request and keeps what it was asked."""

    def __init__(self, reply: str):
        self.reply, self.calls = reply, []

    async def __call__(self, *, system, prompt, image_base64=None, image_media_type="image/png"):
        self.calls.append((system, prompt, image_base64))
        return self.reply, 123


def test_model_reply_is_verified_before_it_becomes_a_proposal():
    reply = (FIX / "model_reply_leipzig.json").read_text(encoding="utf-8")
    replay = Replay("Here is the result:\n```json\n" + reply + "\n```")
    source = brief_model.SourceDoc(DOC, "leipzig.txt", "document", pages("leipzig_de.txt"))
    result = run(extract_brief([source], ctx(), replay))
    draft = result.draft
    assert result.used_model and result.tokens == 123 and len(replay.calls) == 1
    system, prompt, _ = replay.calls[0]
    assert f"document_id={DOC}" in prompt and "page=2" in prompt and "Anzahl der Geschosse" in prompt
    assert "/massing/floors_above" in system and "/depth_level" not in system
    prov = draft.brief["provenance"]
    # accepted: page was wrong in the reply, the citation is moved to the page that holds the quote
    assert prov["/structure/system"]["sources"][0]["page"] == 2
    assert draft.brief["programme"]["units"][0]["name"] == "Wohnung"
    # same value from rules and model: one value, notes name both origins
    assert (
        "AI reading" in prov["/massing/floors_above"]["note"]
        and "pattern match" in prov["/massing/floors_above"]["note"]
    )
    assert "/quality_level" in prov  # quote exists, value is a closed choice; stays proposed for a person
    reasons = {(r.pointer, r.reason) for r in draft.rejected}
    assert ("/massing/lift", "not_found") in reasons  # invented quote
    assert ("/country", "invalid") in reasons  # not a country code
    assert ("/envelope/roof", "unknown_document") in reasons  # document not attached
    assert ("/massing/floors_below", "value_not_in_quote") in reasons  # 3 is not in "Untergeschosse: 1"
    assert ("/massing/floor_height_m", "out_of_range") in reasons
    assert draft.brief["massing"]["floors_below"] == 1  # the rules' value, not the model's
    qs = {q["pointer"]: q for q in draft.brief["questions"]}
    assert qs["/massing/floor_height_m"]["reason"] == "out_of_range"
    assert qs["/use/category"]["options"] == ["residential_multi", "mixed_use"]  # 'bogus' dropped
    for entry in prov.values():
        assert entry["sources"] and entry["status"] in ("proposed", "default")


def test_unreadable_model_reply_is_reported_not_fatal():
    source = brief_model.SourceDoc(DOC, "l.txt", "document", pages("leipzig_de.txt"))
    result = run(extract_brief([source], ctx(), Replay("I cannot help with that.")))
    assert any("no readable answer" in n for n in result.draft.notes)
    assert result.draft.brief["massing"]["floors_above"] == 5  # rules still delivered


def test_without_provider_only_rules_run_and_say_so():
    source = brief_model.SourceDoc(DOC, "l.txt", "document", pages("leipzig_de.txt"))
    result = run(extract_brief([source], ctx(), None))
    assert not result.used_model and any("No AI provider" in n for n in result.draft.notes)


def test_image_reading_keeps_region_and_flags_unverified_quote():
    sketch = brief_model.SourceDoc(DOC, "skizze.png", "sketch", pages=[""], images=[(1, "QUJD", "image/png")])
    reply = json.dumps(
        {
            "fields": [
                {
                    "pointer": "/massing/floors_above",
                    "value": 4,
                    "document_id": DOC,
                    "page": 1,
                    "quote": "4 OG",
                    "region": [0.1, 0.2, 0.3, 0.4],
                },
                {"pointer": "/massing/lift", "value": True, "document_id": DOC, "page": 1},
            ]
        }
    )
    replay = Replay(reply)
    draft = run(extract_brief([sketch], ctx(), replay)).draft
    assert replay.calls[0][2] == "QUJD"
    entry = draft.brief["provenance"]["/massing/floors_above"]
    assert entry["sources"][0]["kind"] == "sketch" and entry["sources"][0]["region"] == [0.1, 0.2, 0.3, 0.4]
    assert "not text-verified" in entry["note"]
    assert "/massing/lift" not in draft.brief["provenance"]  # neither quote nor region: no citation


def test_long_text_is_chunked_and_limits_are_reported():
    big = brief_model.SourceDoc(DOC, "big.txt", "document", ["x " * 4000] * 8)
    chunks, notes = brief_model.build_prompts([big])
    assert len(chunks) > 1 and all(len(c) <= brief_model.CHUNK_CHARS + 200 for c in chunks)
    huge = brief_model.SourceDoc(DOC, "huge.txt", "document", ["y " * 4000] * 80)
    chunks, notes = brief_model.build_prompts([huge])
    assert len(chunks) == brief_model.MAX_CHUNKS and any("not sent" in n for n in notes)


def test_field_coercion_bounds():
    c = brief_fields.coerce
    assert c("/massing/floors_above", "5") == 5 and c("/site/site_coverage_max", 0.5) == 0.5
    for pointer, bad in (
        ("/massing/floors_above", 0),
        ("/massing/floors_above", 2.5),
        ("/massing/lift", "yes"),
        ("/country", "Germany"),
        ("/site/site_coverage_max", 1.5),
        ("/structure/system", "brick"),
        ("/nonexistent", 1),
        ("/programme/units", [{"name": "x", "count": 1, "rooms": []}]),
    ):
        with pytest.raises(brief_fields.FieldError):
            c(pointer, bad)
