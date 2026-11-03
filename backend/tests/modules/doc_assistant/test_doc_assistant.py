# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document assistant: evaluation harness, citation checks, permission scope, service flow."""

from __future__ import annotations

import json
import uuid

import pytest

from app.modules.doc_assistant import service as svc
from app.modules.doc_assistant.core import (
    BM25Index,
    chunk_document,
    confidence_of,
    split_sections,
    tokenize,
    verify_claims,
)
from app.modules.doc_assistant.evaluation import evaluate, load_corpus
from app.modules.doc_assistant.sources import can_read_classified
from app.modules.doc_assistant.validators import SavedAnswerHasCitations

# ── Evaluation harness: quality is measured on the fixture corpus ───────────


def test_eval_harness_meets_quality_bar() -> None:
    m = evaluate()
    assert m["answerable"] >= 15
    assert m["hit_at_1"] >= 0.9, m
    assert m["hit_at_3"] == 1.0, m
    assert m["mrr"] >= 0.95, m
    assert m["answered_rate"] >= 0.9, m
    assert m["refusal_rate"] == 1.0, m
    assert m["citation_precision"] >= 0.9, m


def test_restricted_document_never_reaches_a_viewer_index() -> None:
    passages, _ = load_corpus()
    assert all(p.source_id != "doc-restricted" for p in passages)
    hits = BM25Index(passages).search("What did the lowest bidder price for the facade package?")
    assert confidence_of(hits) < 0.6
    full, _ = load_corpus(include_restricted=True)
    assert any(p.source_id == "doc-restricted" for p in full)


def test_classified_documents_need_manager_or_uploader() -> None:
    assert can_read_classified("viewer", None, "", "u1")
    assert not can_read_classified("viewer", "Confidential", "u2", "u1")
    assert not can_read_classified("editor", "restricted", "u2", "u1")
    assert can_read_classified("editor", "restricted", "u1", "u1")
    assert can_read_classified("manager", "confidential", "", "u1")
    assert can_read_classified("admin", "secret", "", "u1")


# ── Chunking ────────────────────────────────────────────────────────────────


def test_pages_and_sections_are_addressed() -> None:
    text = "SECTION 03 30 00 CONCRETE\n1.1 Summary\nScope text.\f2.2 Reinforcement cover\nCover shall be 50 mm."
    ps = chunk_document(source_kind="specification", source_id="d", title="Spec", content_text=text, document_id="d")
    assert {p.page for p in ps} == {1, 2}
    cover = next(p for p in ps if "50 mm" in p.text)
    assert cover.page == 2
    assert cover.section == "2.2 Reinforcement cover"


def test_section_carries_over_a_page_break() -> None:
    text = "3.1 Curing\nCure for 7 days.\fcontinued: protect from frost."
    ps = chunk_document(source_kind="specification", source_id="d", title="S", content_text=text)
    assert ps[-1].page == 2 and ps[-1].section == "3.1 Curing"


def test_sheet_register_labels_drawing_pages() -> None:
    ps = chunk_document(
        source_kind="document",
        source_id="d",
        title="Set",
        content_text="plan notes\froof notes",
        sheets_by_page={2: {"sheet_number": "A-501", "sheet_title": "Roof", "revision": "P3"}},
        link_for_page=lambda page: f"/plan-room?doc=d&page={page}",
    )
    roof = ps[1]
    assert (roof.source_kind, roof.sheet_number, roof.revision, roof.deep_link) == (
        "drawing",
        "A-501",
        "P3",
        "/plan-room?doc=d&page=2",
    )


def test_split_sections_ignores_long_numbered_sentences() -> None:
    runs = split_sections(
        "1 The contractor shall do a great many things before the start of the works on site today ok"
    )
    assert runs[0][0] is None


def test_tokenizer_folds_case_accents_and_cyrillic_endings() -> None:
    assert tokenize("Kelleraußenwände") == tokenize("KELLERAUSSENWÄNDE".replace("SS", "ß"))
    assert tokenize("панелей")[0] == tokenize("панели")[0]
    assert "the" not in tokenize("the concrete")


# ── Citation verification ──────────────────────────────────────────────────


def _hits():
    passages, _ = load_corpus()
    return BM25Index(passages).search("strength class suspended slabs", k=3)


def test_uncited_out_of_range_and_ungrounded_claims_are_dropped() -> None:
    hits = _hits()
    raw = [
        {"text": "Suspended slabs are class C30/37.", "citations": [1]},
        {"text": "Slabs are class C30/37.", "citations": []},
        {"text": "Slabs are class C30/37.", "citations": [9]},
        {"text": "The roof uses green sedum tiles from Norway.", "citations": [1]},
        "not a dict",
    ]
    kept = verify_claims(raw, hits)
    assert [k["text"] for k in kept] == ["Suspended slabs are class C30/37."]


def test_claim_in_another_language_is_grounded_by_its_verbatim_quote() -> None:
    hits = _hits()
    kept = verify_claims(
        [
            {
                "text": "Decken müssen der Festigkeitsklasse C30/37 entsprechen.",
                "citations": ["[1]"],
                "quote": "suspended slabs and columns shall be strength class C30/37",
            },
            {"text": "Erfunden.", "citations": [1], "quote": "slabs shall be made of timber"},
        ],
        hits,
    )
    assert len(kept) == 1 and kept[0]["quote"]


# ── Service flow (no database: passages and the model are injected) ────────


@pytest.fixture
def corpus(monkeypatch):
    passages, _ = load_corpus()

    async def fake_collect(session, project_id, *, role, user_id, kinds=None):
        return [p for p in passages if not kinds or p.source_kind in kinds]

    monkeypatch.setattr(svc, "collect_passages", fake_collect)
    return passages


def _llm(answer: dict | None = None, expansion: dict | None = None):
    calls: list[str] = []

    async def call(system: str, prompt: str):
        calls.append(system)
        if system is svc._EXPAND_SYSTEM:
            return json.dumps(expansion or {"queries": []}), 20
        return json.dumps(answer or {"claims": []}), 100

    return call, calls


async def _ask(llm, question: str, **kw):
    return await svc.DocAssistantService(session=None, llm=llm).ask(  # type: ignore[arg-type]
        project_id=uuid.uuid4(), user_id=uuid.uuid4(), role="viewer", question=question, **kw
    )


async def test_generated_answer_keeps_only_grounded_claims_and_renumbers(corpus) -> None:
    llm, _ = _llm(
        {
            "claims": [
                {
                    "text": "Cover against earth is 50 mm.",
                    "citations": [1],
                    "quote": "50 mm for concrete cast against earth",
                },
                {"text": "Cover is 90 mm.", "citations": [1], "quote": "90 mm everywhere"},
            ]
        }
    )
    out = await _ask(llm, "What is the nominal cover to reinforcement for concrete cast against earth?")
    assert out["status"] == "answered" and out["mode"] == "generated"
    assert len(out["claims"]) == 1 and out["claims"][0]["citations"] == [1]
    cite = out["citations"][0]
    assert cite["source_id"] == "doc-spec-03" and cite["page"] == 2 and cite["revision"] == "C"
    assert cite["section"].startswith("2.2")
    assert out["answer"].endswith("[1]")


async def test_weak_retrieval_is_not_found_and_the_model_never_answers(corpus) -> None:
    llm, calls = _llm({"claims": [{"text": "Lifts run at 1.6 m/s.", "citations": [1]}]})
    out = await _ask(llm, "What elevator speed is specified for the passenger lifts?")
    assert out["status"] == "not_found" and out["claims"] == [] and out["citations"] == []
    assert svc._ANSWER_SYSTEM not in calls


async def test_ungrounded_model_answer_falls_back_to_cited_quotes(corpus) -> None:
    llm, _ = _llm({"claims": [{"text": "Roofs are sedum.", "citations": [1], "quote": "sedum roof"}]})
    out = await _ask(llm, "What is the parapet upstand height on the roof?")
    assert out["mode"] == "extractive" and out["claims"][0]["quoted"] is True
    assert out["citations"][0]["sheet_number"] == "A-501"


async def test_without_a_provider_the_answer_is_extractive(corpus) -> None:
    out = await _ask(None, "How much retention is deducted from interim payments?", use_ai=False)
    assert out["status"] == "answered" and out["mode"] == "extractive"
    assert "5 percent" in out["claims"][0]["text"]


async def test_query_rewrite_rescues_a_question_in_another_language(corpus) -> None:
    llm, _ = _llm(
        answer={"claims": []},
        expansion={"queries": ["liquidated damages per day delay", "Vertragsstrafe pro Tag"]},
    )
    out = await _ask(llm, "Wie hoch ist die Vertragsstrafe pro Tag Verzug?", locale="de")
    assert out["status"] == "answered"
    assert out["citations"][0]["source_id"] == "doc-contract" and out["citations"][0]["page"] == 2


async def test_source_kind_filter_limits_the_answer(corpus) -> None:
    out = await _ask(None, "How thick are the stair core walls?", use_ai=False, kinds={"rfi"})
    assert {c["source_kind"] for c in out["citations"]} == {"rfi"}


async def test_empty_project_reports_no_documents(monkeypatch) -> None:
    async def none(*a, **k):
        return []

    monkeypatch.setattr(svc, "collect_passages", none)
    out = await _ask(None, "anything at all")
    assert out["status"] == "no_documents"


# ── Validation rule ─────────────────────────────────────────────────────────


async def test_saved_answer_without_citations_warns_in_the_callers_language() -> None:
    from app.core.validation.engine import Severity, ValidationContext

    rule = SavedAnswerHasCitations()
    bad = await rule.validate(ValidationContext(data={"citations": []}, metadata={"locale": "de"}))
    assert not bad[0].passed and bad[0].severity == Severity.WARNING
    assert "Projektdokument" in bad[0].message
    ok = await rule.validate(ValidationContext(data={"citations": [{"source_id": "x"}]}))
    assert ok[0].passed
