# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document assistant service: retrieve, gate on confidence, answer with citations, save.

Flow of :meth:`DocAssistantService.ask`:

1. Collect the passages this user may read (``sources.collect_passages``).
2. Rank them with BM25. When the first pass is weak and an AI provider is
   configured, the model rewrites the question into search keywords in the
   documents' languages (a question asked in German over English specs) and
   the search runs again with those as half-weight terms.
3. Below the confidence threshold the answer is "not found in project
   documents". The model is never asked to answer from weak retrieval.
4. Otherwise the model writes claims in the user's language, each with the
   passage numbers it rests on and a verbatim quote. ``core.verify_claims``
   drops any claim that cites nothing, cites a passage that was not retrieved,
   or quotes text the passage does not contain. Without a provider, or when
   nothing survives, the answer is extractive: quoted sentences, cited.

The answer is a suggestion with a confidence score; saving it to a note or
an RFI draft is the human's step.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import validation_engine
from app.modules.doc_assistant.core import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    BM25Index,
    Hit,
    confidence_of,
    extractive_claims,
    verify_claims,
)
from app.modules.doc_assistant.models import SavedAnswer
from app.modules.doc_assistant.sources import collect_passages
from app.modules.doc_assistant.validators import DOC_ASSISTANT_RULE_SET

logger = logging.getLogger(__name__)

LLMCall = Callable[[str, str], Awaitable[tuple[str, int]]]

RETRIEVE_K = 6
MAX_PASSAGE_CHARS = 1_200

_ANSWER_SYSTEM = (
    "You answer questions about one construction project using ONLY the numbered passages provided. "
    'Return JSON: {"claims": [{"text": "...", "citations": [1], "quote": "..."}]}. '
    "Each claim is one factual sentence written in the language given as LOCALE. "
    "citations lists the passage numbers that state the fact. quote is a short verbatim excerpt "
    "copied exactly from the first cited passage, in its original language. "
    'Do not use outside knowledge. If the passages do not answer the question, return {"claims": []}.'
)
_EXPAND_SYSTEM = (
    "Rewrite the user's question about construction project documents as short keyword search queries. "
    'Return JSON {"queries": [...]} with up to 3 queries of 3 to 6 essential terms each: one in English, '
    "one in the question's own language, and one using the technical terms a specification would use. "
    "No sentences, no explanations."
)


async def resolve_llm(session: AsyncSession, user_id: uuid.UUID) -> LLMCall | None:
    """A one-shot completion callable over the user's configured AI provider, or None."""
    try:
        from app.modules.ai.ai_client import call_ai, resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository

        settings = await AISettingsRepository(session).get_by_user_id(user_id)
        provider, api_key, model = resolve_provider_key_model(settings)
    except Exception:  # noqa: BLE001 - no provider configured is a normal state
        return None

    async def _call(system: str, prompt: str) -> tuple[str, int]:
        return await call_ai(provider, api_key, system, prompt, max_tokens=1200, model=model)

    return _call


def _json(text: str) -> Any:
    try:
        from app.modules.ai.ai_client import extract_json

        return extract_json(text)
    except Exception:  # noqa: BLE001
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return None


def _passages_prompt(question: str, hits: list[Hit], locale: str) -> str:
    blocks = []
    for ref, hit in enumerate(hits, start=1):
        p = hit.passage
        where = ", ".join(
            x
            for x in (
                p.title,
                f"rev {p.revision}" if p.revision else "",
                f"sheet {p.sheet_number}" if p.sheet_number else "",
                f"page {p.page}" if p.page else "",
                p.section or "",
            )
            if x
        )
        blocks.append(f"[{ref}] ({where})\n{p.text[:MAX_PASSAGE_CHARS]}")
    return f"LOCALE: {locale}\nQUESTION: {question}\n\nPASSAGES:\n" + "\n\n".join(blocks)


def build_answer(claims: list[dict[str, Any]], hits: list[Hit]) -> tuple[str, list[dict[str, Any]], list[dict]]:
    """Renumber the cited passages 1..n in order of first use and render the answer text."""
    order: dict[int, int] = {}
    for claim in claims:
        for ref in claim["citations"]:
            order.setdefault(ref, len(order) + 1)
    citations = [hits[old - 1].passage.citation(new, hits[old - 1].score) for old, new in order.items()]
    out_claims = []
    lines = []
    for claim in claims:
        refs = [order[r] for r in claim["citations"]]
        out_claims.append({**claim, "citations": refs})
        lines.append(claim["text"] + " " + "".join(f"[{r}]" for r in refs))
    return " ".join(lines), citations, out_claims


class DocAssistantService:
    """Ask the project's documents, and keep the answers worth keeping."""

    def __init__(self, session: AsyncSession, llm: LLMCall | None = None) -> None:
        self.session = session
        self._llm = llm

    async def ask(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        question: str,
        locale: str = "en",
        kinds: set[str] | None = None,
        threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        use_ai: bool = True,
    ) -> dict[str, Any]:
        """Answer *question* from the passages the caller may read; see the module docstring."""
        question = (question or "").strip()
        passages = await collect_passages(self.session, project_id, role=role, user_id=str(user_id), kinds=kinds)
        base = {
            "question": question,
            "locale": locale,
            "threshold": threshold,
            "searched_passages": len(passages),
            "tokens": 0,
            "claims": [],
            "citations": [],
            "answer": "",
            "nearest": [],
        }
        if not passages:
            return {**base, "status": "no_documents", "mode": "none", "confidence": 0.0}

        llm = (self._llm or await resolve_llm(self.session, user_id)) if use_ai else None
        index = BM25Index(passages)
        hits = index.search(question, k=RETRIEVE_K)
        retrieval_query = question
        confidence = confidence_of(hits)
        tokens = 0
        if confidence < threshold and llm is not None:
            try:
                text, used = await llm(_EXPAND_SYSTEM, question)
                tokens += used
                data = _json(text)
                queries = [str(q) for q in (data or {}).get("queries", [])][:3] if isinstance(data, dict) else []
                # Each rewrite is scored on its own: German words have zero coverage in English specs.
                for rewrite in queries:
                    expanded = index.search(rewrite, k=RETRIEVE_K)
                    exp_conf = confidence_of(expanded)
                    if expanded and exp_conf > confidence:
                        hits, confidence, retrieval_query = expanded, exp_conf, rewrite
            except Exception:  # noqa: BLE001 - expansion is best effort
                logger.info("Query expansion failed", exc_info=True)

        base["tokens"] = tokens
        if confidence < threshold:
            nearest = [h.passage.citation(i, h.score) for i, h in enumerate(hits[:3], start=1)]
            return {**base, "status": "not_found", "mode": "none", "confidence": confidence, "nearest": nearest}

        claims: list[dict[str, Any]] = []
        mode = "extractive"
        if llm is not None:
            try:
                text, used = await llm(_ANSWER_SYSTEM, _passages_prompt(question, hits, locale))
                tokens += used
                data = _json(text)
                raw = data.get("claims", []) if isinstance(data, dict) else []
                claims = verify_claims(raw, hits)
                mode = "generated" if claims else mode
            except Exception:  # noqa: BLE001 - fall back to the extractive answer
                logger.info("Answer generation failed; falling back to extractive", exc_info=True)
        if not claims:
            claims = extractive_claims(retrieval_query, hits)
        if not claims:
            return {**base, "tokens": tokens, "status": "not_found", "mode": "none", "confidence": confidence}
        answer, citations, out_claims = build_answer(claims, hits)
        return {
            **base,
            "tokens": tokens,
            "status": "answered",
            "mode": mode,
            "confidence": confidence,
            "answer": answer,
            "claims": out_claims,
            "citations": citations,
        }

    async def save(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        question: str,
        answer: str,
        claims: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        confidence: float,
        locale: str,
        target: str,
        rfi_subject: str | None = None,
    ) -> SavedAnswer:
        """Keep an answer as a note or an RFI draft; citations are re-checked against what the user may read."""
        readable = {
            p.passage_id for p in await collect_passages(self.session, project_id, role=role, user_id=str(user_id))
        }
        kept = [c for c in citations if isinstance(c, dict) and c.get("passage_id") in readable]
        report_findings: list[dict[str, Any]] = []
        try:
            report = await validation_engine.validate(
                data={"citations": kept, "target_id": None},
                rule_sets=[DOC_ASSISTANT_RULE_SET],
                target_type="doc_assistant_answer",
                project_id=str(project_id),
                metadata={"locale": locale},
            )
            report_findings = [
                {"rule_id": r.rule_id, "severity": str(r.severity), "message": r.message, "suggestion": r.suggestion}
                for r in report.results
                if not r.passed and not r.is_engine_error
            ]
        except Exception:  # noqa: BLE001 - validation must not block keeping the text
            logger.warning("Saved-answer validation failed to run", exc_info=True)

        target_id: str | None = None
        if target == "rfi":
            target_id = await self._create_rfi_draft(
                project_id=project_id,
                user_id=user_id,
                subject=(rfi_subject or question)[:500],
                question=question,
                answer=answer,
                citations=kept,
            )
        row = SavedAnswer(
            project_id=project_id,
            user_id=user_id,
            question=question,
            answer=answer,
            claims=claims,
            citations=kept,
            confidence=float(confidence),
            locale=locale[:12],
            target_kind=target,
            target_id=target_id,
            validation={"status": "warnings" if report_findings else "passed", "findings": report_findings},
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _create_rfi_draft(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        subject: str,
        question: str,
        answer: str,
        citations: list[dict[str, Any]],
    ) -> str:
        from app.modules.rfi.schemas import RFICreate
        from app.modules.rfi.service import RFIService

        refs = "\n".join(
            f"[{c.get('ref')}] {c.get('title')}"
            + (f", rev {c['revision']}" if c.get("revision") else "")
            + (f", sheet {c['sheet_number']}" if c.get("sheet_number") else "")
            + (f", page {c['page']}" if c.get("page") else "")
            + (f", {c['section']}" if c.get("section") else "")
            for c in citations
        )
        body = f"{question}\n\n{answer}" + (f"\n\n{refs}" if refs else "")
        rfi = await RFIService(self.session).create_rfi(
            RFICreate(
                project_id=project_id,
                subject=subject or question[:500],
                question=body[:10000],
                status="draft",
                metadata={"source": "doc_assistant", "citations": citations},
            ),
            user_id=str(user_id),
        )
        return str(rfi.id)

    async def list_saved(
        self, project_id: uuid.UUID, user_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> tuple[list[SavedAnswer], int]:
        """The caller's kept answers on a project, newest first, with the full count."""
        where = (SavedAnswer.project_id == project_id, SavedAnswer.user_id == user_id)
        stmt = select(SavedAnswer).where(*where).order_by(SavedAnswer.created_at.desc()).limit(limit).offset(offset)
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = (await self.session.execute(select(func.count()).select_from(SavedAnswer).where(*where))).scalar_one()
        return rows, int(total)
