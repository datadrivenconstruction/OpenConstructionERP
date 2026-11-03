# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure drafting logic of the four project catalogue agents.

Each function takes what the agent's read-only tools gathered and returns a
draft: structured fields, a confidence in [0, 1], and the sources every
statement rests on. No database, no model call, so a draft is reproducible
from its inputs and the run audit, and every rule here is unit tested. A
language model, when configured, only adds a ``narrative`` on top of these
fields; it never decides a flag or a status.
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.doc_assistant.core import DEFAULT_CONFIDENCE_THRESHOLD, Hit, confidence_of, tokenize

# ── Contract clause review ─────────────────────────────────────────────────

#: The default checklist. Patterns cover English, German and Russian contract wording;
#: a project replaces or extends it through the agent configuration.
DEFAULT_CLAUSE_CHECKLIST: list[dict[str, Any]] = [
    {
        "key": "payment_terms",
        "label": "Payment terms",
        "patterns": [r"\bpay(ment|able)?\b", r"zahlung", r"оплат"],
        "max_payment_days": 30,
        "risk_patterns": [r"pay[- ]when[- ]paid", r"paid[- ]when[- ]paid", r"pay[- ]if[- ]paid"],
    },
    {
        "key": "liquidated_damages",
        "label": "Liquidated damages",
        "patterns": [r"liquidated damages", r"vertragsstrafe", r"pönale", r"неустойк", r"delay damages"],
        "require_cap": True,
    },
    {
        "key": "indemnity",
        "label": "Indemnity",
        "patterns": [r"indemnif", r"hold harmless", r"freistell", r"возмещ", r"освобо\w* от ответственност"],
        "risk_patterns": [r"\ball claims\b", r"any and all", r"howsoever", r"sämtliche", r"любые"],
    },
    {
        "key": "retention",
        "label": "Retention",
        "patterns": [r"retention", r"einbehalt", r"удержани"],
        "max_retention_percent": 5,
        "release_patterns": [r"releas", r"freigabe", r"auszahl", r"возврат"],
    },
    {
        "key": "termination",
        "label": "Termination",
        "patterns": [r"terminat", r"kündig", r"расторж"],
        "risk_patterns": [r"for convenience", r"without cause", r"ohne (wichtigen )?grund", r"без объяснени"],
    },
]

_CAP_RE = re.compile(r"\bcap(ped)?\b|maximum|not exceed|höchstens|begrenzt|obergrenze|не более|не превыш", re.I)
_DAYS_RE = re.compile(r"(\d{1,3})\s*(?:calendar\s+|working\s+|business\s+)?(?:days|tage|tagen|дней|дня)", re.I)
_PCT_RE = re.compile(r"(\d{1,2}(?:[.,]\d+)?)\s*(?:%|percent|prozent|процент)", re.I)


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def review_clauses(
    hits_by_item: dict[str, list[Hit]],
    checklist: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Flag risk clauses against the checklist; every finding cites the passages it read.

    ``hits_by_item`` maps a checklist key to the contract passages retrieved
    for it. A passage counts as the clause only when one of the item's
    patterns occurs in it, so a retrieval near-miss never becomes a finding.
    A checklist item no passage matches is reported ``missing``: a contract
    silent on retention or termination is itself worth a reviewer's look.
    """
    findings: list[dict[str, Any]] = []
    for item in checklist or DEFAULT_CLAUSE_CHECKLIST:
        if item.get("enabled") is False:
            continue
        key = str(item.get("key"))
        matched = [h for h in hits_by_item.get(key, []) if _any(item.get("patterns", []), h.passage.text)]
        if not matched:
            findings.append(
                {
                    "key": key,
                    "label": item.get("label", key),
                    "status": "missing",
                    "risk": "medium",
                    "reasons": ["not_found"],
                    "citations": [],
                }
            )
            continue
        text = " ".join(h.passage.text for h in matched)
        reasons: list[str] = []
        if _any(item.get("risk_patterns", []), text):
            reasons.append("risk_wording")
        if item.get("require_cap") and not _CAP_RE.search(text):
            reasons.append("no_cap")
        if "max_payment_days" in item:
            days = [int(d) for d in _DAYS_RE.findall(text)]
            if days and max(days) > int(item["max_payment_days"]):
                reasons.append("payment_period_exceeds_limit")
        if "max_retention_percent" in item:
            pcts = [float(p.replace(",", ".")) for p in _PCT_RE.findall(text)]
            if pcts and max(pcts) > float(item["max_retention_percent"]):
                reasons.append("retention_exceeds_limit")
            if not _any(item.get("release_patterns", []), text):
                reasons.append("no_release")
        risk = "high" if {"risk_wording", "no_cap"} & set(reasons) else ("medium" if reasons else "low")
        findings.append(
            {
                "key": key,
                "label": item.get("label", key),
                "status": "flagged" if reasons else "ok",
                "risk": risk,
                "reasons": reasons,
                "citations": [h.passage.citation(i, h.score) for i, h in enumerate(matched[:3], start=1)],
            }
        )
    found = [f for f in findings if f["status"] != "missing"]
    confidence = round(len(found) / len(findings), 3) if findings else 0.0
    return {
        "findings": findings,
        "flagged": sum(1 for f in findings if f["status"] in ("flagged", "missing")),
        "confidence": confidence,
    }


# ── Submittal check ─────────────────────────────────────────────────────────

_REQUIREMENT_RE = re.compile(r"\b(shall|must|submit|required|minimum|maximum|muss|müssen|ist zu|sind zu|должн)", re.I)


def _requirements(hits: list[Hit]) -> list[tuple[str, Hit]]:
    out: list[tuple[str, Hit]] = []
    seen: set[str] = set()
    for hit in hits:
        for sentence in re.split(r"(?<=[.;])\s+|\n+", hit.passage.text):
            s = sentence.strip()
            if len(s) > 15 and _REQUIREMENT_RE.search(s) and s not in seen:
                seen.add(s)
                out.append((s, hit))
    return out[:25]


def check_submittal(submittal: dict[str, Any], spec_hits: list[Hit]) -> dict[str, Any]:
    """Compare a submittal against the requirements of its spec section.

    A requirement is ``addressed`` when most of its content words appear in
    the submittal's text (title, product data, manufacturer, notes) and
    ``unclear`` otherwise. Nothing is marked as failing: the check can only
    tell a reviewer where the submittal is silent, the decision stays theirs.
    """
    sub_text = " ".join(
        str(submittal.get(k) or "") for k in ("title", "spec_section", "manufacturer", "model_reference", "text")
    )
    sub_terms = set(tokenize(sub_text))
    items: list[dict[str, Any]] = []
    for req, hit in _requirements(spec_hits):
        terms = set(tokenize(req))
        share = len(terms & sub_terms) / len(terms) if terms else 0.0
        items.append(
            {
                "requirement": req,
                "status": "addressed" if share >= 0.5 else "unclear",
                "match": round(share, 3),
                "citation": hit.passage.citation(len(items) + 1, hit.score),
            }
        )
    addressed = sum(1 for i in items if i["status"] == "addressed")
    if not items:
        recommendation, confidence = "spec_section_not_found", 0.0
    else:
        recommendation = "ready_for_review" if addressed == len(items) else "request_missing_information"
        confidence = round(min(confidence_of(spec_hits), 1.0) * (0.5 + 0.5 * addressed / len(items)), 3)
    return {
        "spec_section": submittal.get("spec_section"),
        "requirements": items,
        "addressed": addressed,
        "unclear": len(items) - addressed,
        "recommendation": recommendation,
        "confidence": confidence,
    }


# ── Daily report ────────────────────────────────────────────────────────────

DAY_INPUTS = ("timesheets", "photos", "voice_notes", "weather", "deliveries")


def compose_daily_report(day: str, records: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Assemble a daily report draft from one day's site records.

    Every line names the record it came from (``sources``). Confidence is the
    share of the five expected inputs that actually exist for the day, so a
    report built from timesheets alone says so.
    """
    timesheets = records.get("timesheets", [])
    hours = sum(float(t.get("hours") or 0) for t in timesheets)
    workers = len({t.get("resource") or t.get("id") for t in timesheets})
    weather = records.get("weather", [])
    sources = [
        {"kind": kind, "id": str(r.get("id")), "label": r.get("label") or r.get("title") or kind}
        for kind in DAY_INPUTS
        for r in records.get(kind, [])
    ]
    present = [k for k in DAY_INPUTS if records.get(k)]
    return {
        "date": day,
        "labour": {"workers": workers, "hours": round(hours, 2)},
        "weather": [
            {
                "time": w.get("captured_at"),
                "conditions": w.get("conditions"),
                "temperature_c": w.get("temperature_c"),
                "precipitation_mm": w.get("precipitation_mm"),
            }
            for w in weather
        ],
        "deliveries": [
            {"title": d.get("title"), "detail": d.get("description")} for d in records.get("deliveries", [])
        ],
        "notes": [{"title": v.get("title"), "detail": v.get("description")} for v in records.get("voice_notes", [])],
        "photos": [{"id": p.get("id"), "caption": p.get("description")} for p in records.get("photos", [])],
        "inputs_present": present,
        "inputs_missing": [k for k in DAY_INPUTS if k not in present],
        "confidence": round(len(present) / len(DAY_INPUTS), 3),
        "sources": sources,
    }


# ── RFI draft ───────────────────────────────────────────────────────────────


def draft_rfi(question: str, hits: list[Hit], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """An RFI draft: subject, question, and the sheets / spec sections it refers to.

    References are taken only from passages above the assistant's confidence
    gate. Below it the draft still carries the question, with no references
    and a low confidence, so the author knows the documents did not help.
    """
    context = context or {}
    text = (question or "").strip()
    if context.get("markup_label"):
        text = f"{text}\n\nMarkup: {context['markup_label']}"
    first = re.split(r"(?<=[.?!])\s+", (question or "").strip())[0] if question else ""
    subject = first[:120] or "Request for information"
    confidence = confidence_of(hits)
    refs = hits if confidence >= DEFAULT_CONFIDENCE_THRESHOLD else []
    references = [h.passage.citation(i, h.score) for i, h in enumerate(refs[:5], start=1)]
    sheets = sorted({r["sheet_number"] for r in references if r.get("sheet_number")})
    sections = sorted({r["section"] for r in references if r.get("section") and r["source_kind"] == "specification"})
    return {
        "subject": subject,
        "question": text,
        "referenced_sheets": sheets,
        "referenced_sections": sections,
        "references": references,
        "photo_id": context.get("photo_id"),
        "markup_id": context.get("markup_id"),
        "confidence": round(confidence if refs else min(confidence, 0.3), 3),
    }
