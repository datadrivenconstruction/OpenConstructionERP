"""Brief extraction: documents -> ``ddc-brief/1`` draft (values `proposed`, each cited) + clarifying questions.

Orchestrates the deterministic reading (``brief_parse``), the model reading (``brief_model``, optional),
and draft assembly (``brief_draft``). Pure Python; the ERP-facing parts live in ``brief_sources`` and
``brief_api``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .brief_draft import Ambiguity, Draft, DraftContext, Rejected, build_draft, summarize
from .brief_model import Completer, SourceDoc, read_with_model
from .brief_parse import Candidate, detect_language, extract_candidates


@dataclass
class Extraction:
    draft: Draft
    tokens: int = 0
    used_model: bool = False
    candidates: list[Candidate] = field(default_factory=list)

    def view(self) -> dict:
        return {
            "brief": self.draft.brief,
            "rejected": [r.__dict__ for r in self.draft.rejected],
            "notes": self.draft.notes,
            "summary": summarize(self.draft),
            "used_model": self.used_model,
            "tokens": self.tokens,
        }


MAX_SCAN_CHARS = 2_000_000


def _within_limit(pages: list[str]) -> tuple[list[str], int]:
    total = 0
    for i, text in enumerate(pages):
        total += len(text)
        if total > MAX_SCAN_CHARS and i > 0:
            return pages[:i], len(pages) - i
    return pages, 0


async def extract_brief(docs: list[SourceDoc], ctx: DraftContext, complete: Completer | None = None) -> Extraction:
    ctx.doc_names.update({d.id: d.name for d in docs if d.id})
    notes = [d.note for d in docs if d.note]
    candidates: list[Candidate] = []
    if not any(d.images or any(p.strip() for p in d.pages) for d in docs):
        notes.append("Nothing readable was provided; no value was proposed and every required field is a question.")
    for d in docs:
        if d.pages:
            pages, skipped = _within_limit(d.pages)
            if skipped:
                notes.append(
                    f"'{d.name}': {skipped} page(s) beyond the first {len(pages)} were not searched "
                    f"(limit {MAX_SCAN_CHARS:,} characters per document)."
                )
            language = detect_language("\n".join(pages))
            # pattern matching is CPU-bound; keep the event loop free for other requests
            candidates.extend(
                await asyncio.to_thread(extract_candidates, pages, document_id=d.id, kind=d.kind, language=language)
            )
    if complete is None:
        for d in docs:
            if d.images and not any(p.strip() for p in d.pages):
                notes.append(
                    f"'{d.name}' has no text layer; its pages can only be read by an AI provider, "
                    "and none is configured. Nothing was read from it."
                )
    ambs: list[Ambiguity] = []
    rejected: list[Rejected] = []
    tokens = 0
    used = False
    if complete is not None and any(d.pages or d.images for d in docs):
        c, ambs, rejected, model_notes, tokens = await read_with_model(docs, complete)
        candidates.extend(c)
        notes.extend(model_notes)
        used = True
    elif complete is None:
        notes.append("No AI provider is configured: only pattern matching was used.")
    draft = build_draft(ctx, candidates, rejected=rejected, ambiguities=ambs, notes=notes)
    return Extraction(draft, tokens, used, candidates)
