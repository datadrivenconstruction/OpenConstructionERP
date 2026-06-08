# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Prompt templates for LLM-assisted clash triage.

WHY THIS FILE IS IN THE REPO
============================
Competitive BIM coordination tools ship "AI clash triage"
as a paid black box - you cannot see the prompt, you cannot tune it,
you cannot reason about why a verdict was produced. OpenConstructionERP
takes the opposite stance: the prompt lives HERE, in version control,
and a coordinator who reads English can audit every word the LLM is
asked to consider.

You can tune the wording for your project (e.g. a hospital project might
want stricter penetration rules, a residential one might want softer
tolerance treatment) by editing the strings below and bumping
``PROMPT_VERSION``. The triage service writes ``prompt_version`` onto
every persisted result so a re-run with a tightened prompt produces a
NEW triage row instead of silently overwriting the audit trail.

STRUCTURE
=========
Two templates are used per LLM call:

* ``SYSTEM_PROMPT_V1`` - sets the assistant's persona, declares the
  STRICT JSON schema the model must return, and lists the
  category-discrimination rules in plain English.
* ``USER_PROMPT_V1`` - interpolates the actual clash's evidence (element
  types, materials, trade pair, clearance, location, prior triage if
  this is a re-run) into a fact sheet for the LLM to reason against.

The model is asked to return JSON ONLY - no prose, no markdown code
fences. The service layer still parses defensively (extract JSON from
markdown fences as a fallback) but a well-behaved model honours the
"no commentary" rule on the very first try.

SAFETY
======
``build_user_prompt`` runs every interpolated value through a strict
sanitiser (``_sanitise``) so a malicious or buggy upstream cannot inject
prompt-control sequences (e.g. ``"Ignore previous instructions and …"``
or backtick-fenced fake JSON) into the LLM's input. Long fields are
truncated at ``_MAX_FIELD_CHARS`` so a 5 MB ``properties`` blob never
blows the model's context budget.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# ── Public constants ────────────────────────────────────────────────────────

#: Prompt version. Bump this when you edit ``SYSTEM_PROMPT_V1`` or
#: ``USER_PROMPT_V1`` so the cache key changes and existing triage rows
#: do NOT silently mask the new behaviour. Free-form string but
#: convention is ``vMAJOR.MINOR`` so the persisted ``prompt_version``
#: column sorts naturally.
PROMPT_VERSION: str = "v1.0"

#: Per-field length cap. Anything longer is truncated with a "… (truncated)"
#: marker so the LLM still sees the start of the value. 600 characters is
#: comfortably under the 4 k-token-per-prompt LLM-input budget on the
#: cheapest tier (haiku/flash) even with all ~10 fields populated.
_MAX_FIELD_CHARS: int = 600


# ── Templates (USER-TUNABLE - edit + bump PROMPT_VERSION) ───────────────────

#: System prompt - sets persona, declares output schema, lists the
#: category-discrimination rules. Read this before you call the LLM -
#: the model will follow these rules verbatim.
SYSTEM_PROMPT_V1: str = (
    "You are a senior BIM coordinator triaging a single clash detected "
    "between two elements in a federated BIM model. Your job: classify "
    "the clash, estimate confidence, and suggest the next action.\n"
    "\n"
    "You output STRICT JSON, no commentary. Schema:\n"
    "{\n"
    '  "category": "real_design_flaw" | "expected_intersection" | '
    '"tolerance_artifact" | "modeling_error" | "duplicate" | '
    '"unclear",\n'
    '  "confidence": 0.0-1.0,\n'
    '  "severity_suggested": "critical"|"high"|"medium"|"low",\n'
    '  "explanation": "<one sentence>",\n'
    '  "suggested_action": "reroute_pipe"|"add_sleeve"|'
    '"accept_intersection"|"ignore_duplicate"|"escalate_to_designer"|'
    '"request_more_info",\n'
    '  "model_evidence_used": ["<key=value>", "..."]\n'
    "}\n"
    "\n"
    "Rules:\n"
    "- expected_intersection = clashes inside designed penetrations "
    "(sleeve, lintel pocket, slab opening).\n"
    "- tolerance_artifact = sub-tolerance overlap likely caused by "
    "modelling precision (<5 mm).\n"
    "- duplicate = same clash appears already triaged at the same "
    "coordinates.\n"
    "- Use ONLY the evidence in the input. Do not invent properties.\n"
    '- If evidence is insufficient, return category="unclear", '
    "confidence<0.4."
)

#: User prompt - interpolated per call with the specific clash evidence.
#: Placeholders are documented inline so a non-developer reading this
#: file knows exactly what each token holds.
USER_PROMPT_V1: str = (
    "Clash to triage:\n"
    "\n"
    "Element A: {ifc_class_a} (id={element_a_id}, material={material_a}, "
    "properties={props_a})\n"
    "Element B: {ifc_class_b} (id={element_b_id}, material={material_b}, "
    "properties={props_b})\n"
    "\n"
    "Trade pair: {trade_pair}\n"
    "Clash type: {clash_type}\n"
    "Clearance: {clearance_mm} mm\n"
    "Tolerance setting: {tolerance_mm} mm\n"
    "Spatial location: x={x:.2f} y={y:.2f} z={z:.2f}\n"
    "Coordinate grid: {grid_label}\n"
    "Storey/level: {storey_label}\n"
    "\n"
    "{prior_triage_section}"
)


# ── Retry / repair prompt (used after invalid JSON) ─────────────────────────

#: Follow-up sent after the LLM returned non-JSON on its first try.
#: Kept terse on purpose - the model already knows the schema from
#: ``SYSTEM_PROMPT_V1``; this just re-asserts the format.
RETRY_PROMPT_V1: str = (
    "Your previous response was not valid JSON. Respond again with the "
    "verdict as STRICT JSON ONLY, no markdown fences, no commentary."
)


# ── Sanitiser helpers ───────────────────────────────────────────────────────


# Characters that can carry prompt-control intent if echoed back into the
# LLM payload. We strip them entirely - they are not load-bearing in
# any of our real evidence fields (IFC GUIDs / materials / floats).
_DANGEROUS_PATTERN = re.compile(
    "[`"
    + chr(0x00)
    + chr(0x01)
    + chr(0x02)
    + chr(0x03)
    + chr(0x04)
    + chr(0x05)
    + chr(0x06)
    + chr(0x07)
    + chr(0x08)
    + chr(0x09)
    + chr(0x0A)
    + chr(0x0B)
    + chr(0x0C)
    + chr(0x0D)
    + chr(0x0E)
    + chr(0x0F)
    + chr(0x10)
    + chr(0x11)
    + chr(0x12)
    + chr(0x13)
    + chr(0x14)
    + chr(0x15)
    + chr(0x16)
    + chr(0x17)
    + chr(0x18)
    + chr(0x19)
    + chr(0x1A)
    + chr(0x1B)
    + chr(0x1C)
    + chr(0x1D)
    + chr(0x1E)
    + chr(0x1F)
    + "]"
)

# Lines starting with these tokens are classic prompt-injection trailers
# (the user controls part of the input - properties blobs, descriptions -
# and an attacker could embed "Ignore previous instructions…"). We don't
# silently drop them (that would hide the attack); we wrap them in a
# visible "[SUSPICIOUS]" prefix so the LLM sees them as data, not as a
# directive.
_INJECTION_TRIGGERS = (
    "ignore previous",
    "disregard the above",
    "you are now",
    "system:",
    "assistant:",
)


def _sanitise(value: Any, *, max_chars: int = _MAX_FIELD_CHARS) -> str:
    """Render ``value`` as a single-line, length-capped, injection-safe string.

    * Non-strings are ``str()``-coerced (so a dict ``properties`` blob
      lands as ``{'k': 'v'}`` - readable enough for the LLM).
    * Backticks and control characters are stripped (no markdown-fence
      injection, no NULL-byte payloads).
    * Lines starting with a known injection trigger are tagged
      ``[SUSPICIOUS]`` so the LLM treats them as data, not directives.
    * Output is truncated to ``max_chars`` with a visible marker.
    """
    if value is None:
        return ""
    s = str(value) if not isinstance(value, str) else value
    s = _DANGEROUS_PATTERN.sub(" ", s)
    # Collapse runs of whitespace so newline-bombs don't pad the prompt.
    s = re.sub(r"\s+", " ", s).strip()
    lower = s.lower()
    for trig in _INJECTION_TRIGGERS:
        if trig in lower:
            s = f"[SUSPICIOUS] {s}"
            break
    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + "… (truncated)"
    return s


def _format_float(value: Any, *, default: float = 0.0) -> float:
    """Coerce a value to float; fall back to ``default`` on garbage."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ── Public builder ──────────────────────────────────────────────────────────


def _build_prior_triage_section(prior: Mapping[str, Any] | None) -> str:
    """Render the optional 'prior triage' paragraph.

    When the clash has never been triaged this returns ``""`` so the
    placeholder collapses to a blank line in the final prompt (clean).
    When there IS a prior verdict the section makes the LLM aware of it
    so the re-run produces a deliberate re-evaluation, not a copy of the
    earlier verdict.
    """
    if not prior:
        return ""
    date_raw = prior.get("date") or prior.get("created_at") or ""
    cat_raw = prior.get("category") or "unclear"
    conf_raw = prior.get("confidence") or 0.0
    date = _sanitise(date_raw, max_chars=64)
    cat = _sanitise(cat_raw, max_chars=48)
    conf = _format_float(conf_raw)
    return f"This clash signature was previously triaged on {date} as {cat} (confidence {conf:.2f}). Re-evaluate."


def build_user_prompt(
    clash: Mapping[str, Any],
    prior: Mapping[str, Any] | None = None,
) -> str:
    """‌⁠‍Render ``USER_PROMPT_V1`` with the supplied clash evidence.

    Args:
        clash: Mapping of clash fields. Required keys are documented
            inline below; any extras are ignored.
        prior: Optional prior-triage summary
            (``{"date": ..., "category": ..., "confidence": ...}``); pass
            ``None`` (or omit) on a first-time triage.

    Returns:
        A fully interpolated user-prompt string, ready to send to the LLM.

    Raises:
        ValueError: If any required clash field is missing. The error
            message names the missing key so the caller knows exactly
            what to supply.
    """
    required = (
        "element_a_id",
        "element_b_id",
        "ifc_class_a",
        "ifc_class_b",
        "trade_pair",
        "clash_type",
        "clearance_mm",
        "tolerance_mm",
        "x",
        "y",
        "z",
    )
    missing = [k for k in required if k not in clash]
    if missing:
        msg = (
            f"Cannot build clash triage prompt: missing required field(s) "
            f"{', '.join(missing)}. Supply them in the ``clash`` mapping."
        )
        raise ValueError(msg)

    return USER_PROMPT_V1.format(
        ifc_class_a=_sanitise(clash.get("ifc_class_a")),
        element_a_id=_sanitise(clash.get("element_a_id"), max_chars=128),
        material_a=_sanitise(clash.get("material_a", "")),
        props_a=_sanitise(clash.get("properties_a", "")),
        ifc_class_b=_sanitise(clash.get("ifc_class_b")),
        element_b_id=_sanitise(clash.get("element_b_id"), max_chars=128),
        material_b=_sanitise(clash.get("material_b", "")),
        props_b=_sanitise(clash.get("properties_b", "")),
        trade_pair=_sanitise(clash.get("trade_pair"), max_chars=64),
        clash_type=_sanitise(clash.get("clash_type"), max_chars=32),
        clearance_mm=_format_float(clash.get("clearance_mm")),
        tolerance_mm=_format_float(clash.get("tolerance_mm")),
        x=_format_float(clash.get("x")),
        y=_format_float(clash.get("y")),
        z=_format_float(clash.get("z")),
        grid_label=_sanitise(clash.get("grid_label", ""), max_chars=64),
        storey_label=_sanitise(clash.get("storey_label", ""), max_chars=64),
        prior_triage_section=_build_prior_triage_section(prior),
    )


__all__ = [
    "PROMPT_VERSION",
    "RETRY_PROMPT_V1",
    "SYSTEM_PROMPT_V1",
    "USER_PROMPT_V1",
    "build_user_prompt",
]
