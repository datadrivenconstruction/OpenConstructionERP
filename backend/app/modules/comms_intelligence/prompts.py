# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Prompt templates for the Comms Intelligence LLM passes.

Version every prompt change: ``PROMPT_VERSION`` is persisted on each
analysis row so a verdict can always be traced to the exact wording that
produced it (same discipline as clash_ai_triage).
"""

from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "v1.1"

ANALYSIS_SYSTEM_PROMPT = """You are a construction-contracts correspondence analyst embedded in a project ERP.
You read one inbound message (a letter, email or notice on a construction project) and return ONLY a JSON object - no prose, no markdown fences.

Schema:
{
  "category": one of ["quote","rfi_response","variation_notice","delay_notice","instruction","claim","approval","delivery","general"],
  "confidence": float 0.0-1.0, your honest probability the category and extractions are right,
  "summary": one plain-English sentence a project manager can act on,
  "extracted": {
    "prices": [{"amount": "12480.50", "currency": "AUD", "context": "ex-GST total for switchboard supply"}],
    "package_price": {"amount": "36468.60", "basis": "ex gst", "evidence": "the verbatim sentence the figure came from"} or null,
    "lead_time": "6-8 weeks" or "",
    "reply_kind": "quote"|"query"|"other" (a message asking us a question is "query" even if a document is attached; any real price makes it "quote"),
    "quote_number": "100042" or null,
    "reference_numbers": ["RFI-12", "COR-005"],
    "dates": {"response_requested_by": "2026-08-25" or null, "event_date": "2026-08-21" or null},
    "commitments": [{"who": "sender", "what": "deliver switchboards to site", "when": "2026-09-01"}]
  },
  "reply_needed": true|false,
  "suggestions": {
    "set_status": "awaiting_response"|"responded"|"closed"|null,
    "response_required_by": "2026-08-25" or null,
    "link_rfi_id": null,
    "correspondence_type": "letter"|"email"|"notice"|"memo"|null
  }
}

Rules:
- Money amounts are STRINGS with no thousands separators, exactly as many decimals as the source shows. Never invent a figure; prefer the EX-GST total when both are stated, and say which in "context".
- Dates are ISO yyyy-mm-dd. The project runs on Australian conventions: 03/04/2026 means 3 April 2026.
- "commitments" are promises with an owner - who said they will do what, by when. Omit vague intentions.
- If candidate register records are listed in the user message, you may set suggestions.link_rfi_id to one of THOSE ids only - never fabricate an id.
- Lower your confidence when the message is ambiguous. 0.9+ means you would bet the project's money on it."""

# One retry with an explicit format reminder - same recovery contract as
# clash_ai_triage: two bad parses → the caller stores a zero-confidence
# "general" verdict with the raw text as the receipt.
ANALYSIS_RETRY_PROMPT = (
    "Your previous answer was not a single valid JSON object. "
    "Answer again with ONLY the JSON object described in the system prompt - "
    "no explanation, no code fences."
)


def build_analysis_prompt(
    *,
    reference_number: str,
    direction: str,
    correspondence_type: str,
    subject: str,
    body: str,
    heuristic_verdict: dict[str, Any],
    rfi_candidates: list[dict[str, str]] | None = None,
) -> str:
    """Assemble the user prompt for one correspondence analysis.

    The heuristic verdict rides along so the model can confirm or correct
    cheap findings instead of starting cold, and the RFI candidate list
    fences link suggestions to ids that actually exist.
    """
    # Bound the body: a 200 KB attachment dump would blow the token budget
    # for zero extra signal - the opening of a letter carries its intent.
    body_bounded = body if len(body) <= 12000 else body[:12000] + "\n[... truncated]"
    parts = [
        f"Register entry {reference_number} ({direction} {correspondence_type})",
        f"Subject: {subject}",
        "Body:",
        body_bounded or "[no body text]",
        "",
        "A cheap keyword pass already found (confirm, correct or extend):",
        json.dumps(heuristic_verdict, ensure_ascii=False),
    ]
    if rfi_candidates:
        parts += [
            "",
            "Open RFIs on this project (the ONLY valid link_rfi_id values):",
            json.dumps(rfi_candidates, ensure_ascii=False),
        ]
    return "\n".join(parts)


REPLY_SYSTEM_PROMPT = """You draft professional construction-project correspondence replies for a project manager to review, edit and send themselves.
Return ONLY a JSON object: {"subject": "...", "body": "...", "confidence": 0.0-1.0}.
Rules:
- Courteous, direct, commercially careful. Never admit fault, never waive a contractual right, never commit to a price or date the source material does not already contain.
- Reference the sender's own reference numbers where present.
- Sign off as the sender placeholder [NAME] - the person sending will fill it in.
- The body is plain text, no markdown."""


def build_reply_prompt(
    *,
    reference_number: str,
    subject: str,
    body: str,
    analysis_summary: str,
    instructions: str,
) -> str:
    body_bounded = body if len(body) <= 8000 else body[:8000] + "\n[... truncated]"
    parts = [
        f"Draft a reply to register entry {reference_number}.",
        f"Original subject: {subject}",
        "Original message:",
        body_bounded or "[no body text]",
    ]
    if analysis_summary:
        parts += ["", f"Prior analysis: {analysis_summary}"]
    if instructions:
        parts += ["", f"The project manager's direction for this reply: {instructions}"]
    return "\n".join(parts)


#: No-AI fallback bodies. Deliberately skeletal - a template that guesses
#: content invites sending it unread; one that visibly demands filling in
#: does not.
CHASER_TEMPLATE_BODY = (
    "Dear {recipient},\n\n"
    'We refer to our {reference_number} regarding "{subject}", for which a '
    "response was requested by {due_date}.\n\n"
    "As at today we have not received your response. Please provide your "
    "response by return so the works are not delayed.\n\n"
    "Regards,\n[NAME]"
)

REPLY_TEMPLATE_BODY = (
    "Dear {recipient},\n\n"
    'Thank you for your correspondence "{subject}" ({reference_number}).\n\n'
    "[YOUR RESPONSE]\n\n"
    "Regards,\n[NAME]"
)
