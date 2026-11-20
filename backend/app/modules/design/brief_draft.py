"""Candidates -> ``ddc-brief/1`` draft with provenance, clarifying questions, and answers.

Pure Python, no ERP imports. Rules this module enforces:
- a value is written only with at least one cited source (document, page, quote);
- contradicting values are never resolved silently: the field stays empty and a question is raised;
- a value that is only readable in two ways (ambiguous number format) is a question, not a value;
- values already confirmed by a person are never overwritten;
- every required field that ends up empty gets a question; answers become ``confirmed``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .brief_fields import FIELDS, REQUIRED, FieldError, coerce, drop_at, get_at, options_for, set_at
from .brief_parse import Candidate
from .brief_texts import question_text

SCHEMA_ID = "ddc-brief/1"
MAX_SOURCES = 3
NOTE_ORIGIN = {"model": "AI reading of the documents", "rule": "pattern match in the documents"}


@dataclass
class Rejected:
    pointer: str
    reason: str  # not_found | value_not_in_quote | out_of_range | invalid | unknown_document | incomplete_pair
    detail: str
    value: Any = None
    document_id: str | None = None
    page: int | None = None
    quote: str | None = None


@dataclass
class Ambiguity:
    """Something the reader could not settle; becomes a question."""

    pointer: str
    reason: str  # contradiction | out_of_range | ambiguous
    options: list[Any] = field(default_factory=list)
    detail: str = ""
    default: Any = None


@dataclass
class DraftContext:
    project_id: str
    brief_id: str
    version: int = 1
    locale: str = "en"
    defaults: dict[str, Any] = field(default_factory=dict)  # pointer -> value from project settings
    doc_names: dict[str, str] = field(default_factory=dict)
    base: dict | None = None  # existing brief: confirmed values are kept


@dataclass
class Draft:
    brief: dict
    rejected: list[Rejected]
    notes: list[str]
    # read again, but the brief already has them confirmed: kept as they are
    confirmed: list[str] = field(default_factory=list)


class AnswerError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(f"{e['pointer']}: {e['message']}" for e in errors))
        self.errors = errors


def _same(a: Any, b: Any) -> bool:
    if (
        isinstance(a, (int, float))
        and isinstance(b, (int, float))
        and not isinstance(a, bool)
        and not isinstance(b, bool)
    ):
        return abs(a - b) <= max(1e-9, 1e-6 * max(abs(a), abs(b)))
    return a == b


def _source(c: Candidate) -> dict:
    src: dict[str, Any] = {"kind": c.kind}
    if c.document_id:
        src["document_id"] = c.document_id
    src["page"] = c.page
    src["quote"] = c.quote[:1000]
    if c.region:
        src["region"] = c.region
    return src


def _merge_sources(sources: list[dict], new: dict) -> None:
    for i, old in enumerate(sources):
        if old.get("document_id") == new.get("document_id") and old.get("page") == new.get("page"):
            a, b = old.get("quote", ""), new.get("quote", "")
            if a in b:
                return
            if b in a:
                sources[i] = new
                return
    if len(sources) < MAX_SOURCES:
        sources.append(new)


def _qid(pointer: str, reason: str) -> str:
    return "q-" + hashlib.sha1(f"{pointer}|{reason}".encode()).hexdigest()[:8]


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _confirmed(base: dict | None, pointer: str) -> bool:
    prov = ((base or {}).get("provenance") or {}).get(pointer)
    return isinstance(prov, dict) and prov.get("status") == "confirmed"


def build_draft(
    ctx: DraftContext,
    candidates: list[Candidate],
    *,
    rejected: list[Rejected] | None = None,
    ambiguities: list[Ambiguity] | None = None,
    notes: list[str] | None = None,
) -> Draft:
    rejected = list(rejected or [])
    ambiguities = list(ambiguities or [])
    notes = list(notes or [])
    doc: dict[str, Any] = copy.deepcopy(ctx.base) if ctx.base else {}
    doc.update(schema=SCHEMA_ID, brief_id=ctx.brief_id, project_id=ctx.project_id, version=ctx.version)
    prov: dict[str, dict] = doc.setdefault("provenance", {})
    # unconfirmed values of an earlier run are replaced by this one
    for pointer in list(prov):
        if pointer in FIELDS and prov[pointer].get("status") != "confirmed":
            drop_at(doc, pointer)
            prov.pop(pointer)
    doc["questions"] = []
    doc.setdefault("programme", {})  # required by the schema; an empty programme is valid

    for pointer, value in ctx.defaults.items():
        if pointer in FIELDS and get_at(doc, pointer) is None:
            try:
                set_at(doc, pointer, coerce(pointer, value))
            except FieldError:
                continue
            prov[pointer] = {"status": "default", "sources": [{"kind": "user"}], "note": "From the project settings."}

    by_pointer: dict[str, list[Candidate]] = {}
    known: set[str] = set()
    for c in candidates:
        if _confirmed(doc, c.pointer):
            known.add(c.pointer)
            continue
        by_pointer.setdefault(c.pointer, []).append(c)

    mixed = by_pointer.get("/use/category")
    if mixed and any(c.value == "mixed_use" for c in mixed):
        by_pointer["/use/category"] = [c for c in mixed if c.value == "mixed_use"]

    for pointer, group in by_pointer.items():
        clear = [c for c in group if not c.alternatives]
        for c in group:
            if c.alternatives:
                opts = [c.value, *c.alternatives]
                ambiguities.append(
                    Ambiguity(
                        pointer,
                        "ambiguous",
                        opts,
                        f"{_cite(c, ctx)}: the number can be read as {' or '.join(str(o) for o in opts)}",
                    )
                )
        if not clear:
            continue
        groups: list[list[Candidate]] = []
        for c in clear:
            for g in groups:
                if _same(g[0].value, c.value):
                    g.append(c)
                    break
            else:
                groups.append([c])
        if len(groups) > 1:
            reason = "ambiguous" if pointer == "/use/category" else "contradiction"
            ranked = sorted(groups, key=lambda g: -len(g))
            top = len(ranked[0]) > len(ranked[1])
            ambiguities.append(
                Ambiguity(
                    pointer,
                    reason,
                    [g[0].value for g in ranked if isinstance(g[0].value, (str, int, float, bool))],
                    "; ".join(_cite(g[0], ctx) + f" = {g[0].value}" for g in ranked[:4]),
                    ranked[0][0].value if top and isinstance(ranked[0][0].value, (str, int, float, bool)) else None,
                )
            )
            continue
        group = groups[0]
        sources: list[dict] = []
        origins = set()
        for c in group:
            _merge_sources(sources, _source(c))
            origins.add("model" if c.origin == "model" else "rule")
        set_at(doc, pointer, group[0].value)
        entry: dict[str, Any] = {
            "status": "proposed",
            "sources": sources,
            "note": "Found by: " + ", ".join(NOTE_ORIGIN[o] for o in sorted(origins)) + ".",
        }
        extra = next((c.note for c in group if c.note), None)
        if extra:
            entry["note"] = (entry["note"] + " " + extra)[:500]
        prov[pointer] = entry

    _drop_partial_pairs(doc, prov, rejected)
    doc["questions"] = build_questions(doc, ambiguities, ctx)
    if not prov:
        doc.pop("provenance")
    if not doc["questions"]:
        doc.pop("questions")
    return Draft(doc, rejected, notes, sorted(known))


def _cite(c: Candidate, ctx: DraftContext) -> str:
    name = ctx.doc_names.get(c.document_id or "", "text")
    return f"{name}, p.{c.page}: «{c.quote[:120]}»"


def _drop_partial_pairs(doc: dict, prov: dict, rejected: list[Rejected]) -> None:
    w, d = get_at(doc, "/massing/footprint/width_m"), get_at(doc, "/massing/footprint/depth_m")
    if (w is None) != (d is None):
        for p in ("/massing/footprint/width_m", "/massing/footprint/depth_m"):
            if get_at(doc, p) is not None:
                rejected.append(
                    Rejected(
                        p, "incomplete_pair", "footprint needs both width and depth; only one was found", get_at(doc, p)
                    )
                )
                drop_at(doc, p)
                prov.pop(p, None)


def build_questions(doc: dict, ambiguities: list[Ambiguity], ctx: DraftContext) -> list[dict]:
    questions: list[dict] = []
    seen: set[str] = set()

    def add(pointer: str, reason: str, options: list[Any], default: Any, detail: str = "") -> None:
        qid = _qid(pointer, reason)
        if qid in seen or _confirmed(doc, pointer):
            return
        seen.add(qid)
        q: dict[str, Any] = {
            "id": qid,
            "pointer": pointer,
            "text": question_text(ctx.locale, pointer, reason, detail),
            "options": options,
            "reason": reason,
        }
        if default is not None and default in options:
            q["default"] = default
        questions.append(q)

    for pointer in REQUIRED:
        if get_at(doc, pointer) is None and not any(a.pointer == pointer for a in ambiguities):
            add(pointer, "missing", options_for(pointer), None)
    if get_at(doc, "/budget/amount") is not None and get_at(doc, "/budget/currency") is None:
        add("/budget/currency", "missing", [], None)
    for a in ambiguities:
        if a.pointer in FIELDS:
            add(a.pointer, a.reason, a.options, a.default, a.detail)
    order = {p: i for i, p in enumerate(REQUIRED)}
    questions.sort(key=lambda q: (order.get(q["pointer"], len(order)), q["pointer"]))
    return questions


def apply_answers(brief: dict, answers: list[dict], *, user_id: str, at: datetime | None = None) -> dict:
    """A copy of ``brief`` with each answered question's value set and confirmed by ``user_id``.

    ``answers``: ``{"question_id": ..., "value": ...}`` or ``{"question_id": ..., "use_default": true}``.
    All answers are validated first; one bad answer rejects the batch."""
    at = at or datetime.now(UTC)
    out = copy.deepcopy(brief)
    by_id = {q["id"]: q for q in out.get("questions") or []}
    errors: list[dict] = []
    todo: list[tuple[dict, Any]] = []
    for a in answers:
        q = by_id.get(a.get("question_id"))
        if q is None:
            errors.append({"pointer": "", "message": f"no open question {a.get('question_id')!r}"})
            continue
        if a.get("use_default"):
            if "default" not in q:
                errors.append({"pointer": q["pointer"], "message": "the question has no default"})
                continue
            raw = q["default"]
        elif "value" in a:
            raw = a["value"]
        else:
            errors.append({"pointer": q["pointer"], "message": "an answer needs 'value' or 'use_default'"})
            continue
        try:
            todo.append((q, coerce(q["pointer"], raw)))
        except FieldError as exc:
            errors.append({"pointer": exc.pointer, "message": exc.message})
    if errors:
        raise AnswerError(errors)
    prov = out.setdefault("provenance", {})
    for q, value in todo:
        set_at(out, q["pointer"], value)
        prov[q["pointer"]] = {
            "status": "confirmed",
            "confirmed_by": user_id,
            "confirmed_at": _stamp(at),
            "sources": [{"kind": "user"}],
            "note": "Answer to a clarifying question.",
        }
        by_id.pop(q["id"], None)
    out["questions"] = list(by_id.values())
    if not out["questions"]:
        out.pop("questions")
    return out


def summarize(draft: Draft) -> dict:
    """Compact figures for the UI and for tests."""
    prov = draft.brief.get("provenance", {})
    return {
        "proposed": sorted(p for p, e in prov.items() if e.get("status") == "proposed"),
        "defaults": sorted(p for p, e in prov.items() if e.get("status") == "default"),
        "questions": [q["pointer"] for q in draft.brief.get("questions", [])],
        "rejected": len(draft.rejected),
        "confirmed": list(draft.confirmed),
    }


def canonical(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False)
