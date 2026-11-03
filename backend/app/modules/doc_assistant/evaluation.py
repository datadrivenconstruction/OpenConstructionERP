# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deterministic evaluation harness for the document assistant.

Runs the fixture corpus in ``eval_corpus.json`` through the same chunker,
ranker, confidence gate and extractive citation path production uses, and
scores it: retrieval hit@1 / hit@3 / MRR on answerable questions, the share
of unanswerable questions correctly refused, and citation precision (every
cited passage must belong to an expected source and page). A restricted
document in the corpus is filtered out exactly as a viewer's request would
be, so a leak shows up as a wrong answer.

Run ``python -m app.modules.doc_assistant.evaluation`` to print the scores.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.doc_assistant.core import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    BM25Index,
    Passage,
    chunk_document,
    confidence_of,
    extractive_claims,
    record_passages,
)

CORPUS_PATH = Path(__file__).with_name("eval_corpus.json")


def load_corpus(path: Path = CORPUS_PATH, *, include_restricted: bool = False) -> tuple[list[Passage], list[dict]]:
    """Fixture passages (restricted documents dropped unless asked) and questions."""
    data = json.loads(path.read_text(encoding="utf-8"))
    passages: list[Passage] = []
    for doc in data["documents"]:
        if doc.get("restricted") and not include_restricted:
            continue
        sheets = {int(k): v for k, v in (doc.get("sheets") or {}).items()}
        passages += chunk_document(
            source_kind=doc["source_kind"],
            source_id=doc["source_id"],
            title=doc["title"],
            content_text="\f".join(doc["pages"]),
            document_id=doc["source_id"],
            revision=doc.get("revision"),
            sheets_by_page=sheets,
        )
    for rec in data["records"]:
        passages += record_passages(
            source_kind=rec["source_kind"],
            source_id=rec["source_id"],
            title=rec["title"],
            text=rec["text"],
            deep_link="",
            section=rec.get("section"),
        )
    return passages, data["questions"]


def _matches(passage: Passage, expected: list[list[Any]]) -> bool:
    return any(passage.source_id == sid and (page is None or passage.page == page) for sid, page in expected)


def evaluate(threshold: float = DEFAULT_CONFIDENCE_THRESHOLD, k: int = 3) -> dict[str, Any]:
    """Score the fixture corpus; returns the metrics dict."""
    passages, questions = load_corpus()
    index = BM25Index(passages)
    pos = [q for q in questions if q["expect"]]
    neg = [q for q in questions if not q["expect"]]
    hit1 = hitk = 0
    rr = 0.0
    answered = 0
    cited = cited_ok = 0
    failures: list[str] = []
    for q in pos:
        hits = index.search(q["q"], k=max(k, 5))
        ranks = [i for i, h in enumerate(hits, start=1) if _matches(h.passage, q["expect"])]
        if ranks and ranks[0] == 1:
            hit1 += 1
        if ranks and ranks[0] <= k:
            hitk += 1
        else:
            failures.append(q["q"])
        rr += 1.0 / ranks[0] if ranks else 0.0
        if confidence_of(hits) >= threshold:
            answered += 1
            for claim in extractive_claims(q["q"], hits[:k]):
                for ref in claim["citations"]:
                    cited += 1
                    cited_ok += int(_matches(hits[ref - 1].passage, q["expect"]))
    refused = sum(1 for q in neg if confidence_of(index.search(q["q"], k=5)) < threshold)
    return {
        "questions": len(questions),
        "answerable": len(pos),
        "hit_at_1": round(hit1 / len(pos), 3),
        f"hit_at_{k}": round(hitk / len(pos), 3),
        "mrr": round(rr / len(pos), 3),
        "answered_rate": round(answered / len(pos), 3),
        "refusal_rate": round(refused / len(neg), 3) if neg else 1.0,
        "citation_precision": round(cited_ok / cited, 3) if cited else 0.0,
        "citations": cited,
        "misses": failures,
    }


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(evaluate(), indent=2, ensure_ascii=False))
