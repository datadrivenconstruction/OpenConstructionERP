# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure logic for minutes from audio: glossary, transcript clean-up, proposals.

Nothing here touches a database, the network or FastAPI, so every rule the
recording flow relies on is unit-testable on plain dicts:

* the project glossary - folding, de-duplicating seeded terms, building the
  vocabulary hint for the speech provider and the spelling block for the AI;
* transcript clean-up - known mis-hearings replaced, near-miss spellings
  offered as corrections, speaker labels resolved to names;
* proposals - the AI (or heuristic) output cleaned into one reviewable list
  of summary, decisions, actions, open questions and corrections, each with a
  confidence, the action owner matched to a project person, a relative due date
  resolved against the meeting date and a mention of an RFI or BOQ position
  linked to the record it names.

Nothing is applied here. The service applies only what a person confirmed.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Any

GLOSSARY_KINDS: tuple[str, ...] = ("person", "company", "abbreviation", "term", "boq", "place")
GLOSSARY_SOURCES: tuple[str, ...] = ("manual", "contacts", "attendees", "stakeholders", "boq", "project")
RECORDING_SOURCES: tuple[str, ...] = ("upload", "browser_record", "browser_speech", "manual")
PROPOSAL_KINDS: tuple[str, ...] = ("summary", "decision", "action", "question", "correction")
PROPOSAL_STATUSES: tuple[str, ...] = ("pending", "confirmed", "rejected")
LINKABLE_ENTITIES: tuple[str, ...] = ("rfi", "boq_position", "task")

#: Sources that capture live speech and therefore need the participants' consent.
CONSENT_SOURCES: frozenset[str] = frozenset({"upload", "browser_record", "browser_speech"})

#: The hosted speech endpoint reads at most a few hundred tokens of hints.
TRANSCRIPTION_HINT_CHARS = 800
#: The minutes AI gets a longer spelling list, still bounded.
LLM_GLOSSARY_TERMS = 200
MAX_TERM_CHARS = 120
#: Confidence a heuristic (no AI) proposal carries: low on purpose.
HEURISTIC_CONFIDENCE = 0.35
#: Near-miss spellings below this similarity are not offered.
CORRECTION_MIN_RATIO = 0.84

# Kinds the speech hint lists first: names are what a speech model gets wrong.
_HINT_ORDER = {"person": 0, "company": 1, "abbreviation": 2, "place": 3, "term": 4, "boq": 5}

# Language names a verbose transcription reports, mapped to ISO 639-1.
_LANGUAGE_NAMES: dict[str, str] = {
    "english": "en",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "portuguese": "pt",
    "dutch": "nl",
    "polish": "pl",
    "czech": "cs",
    "russian": "ru",
    "ukrainian": "uk",
    "bulgarian": "bg",
    "croatian": "hr",
    "romanian": "ro",
    "hungarian": "hu",
    "greek": "el",
    "turkish": "tr",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
    "estonian": "et",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "vietnamese": "vi",
    "thai": "th",
    "indonesian": "id",
    "hindi": "hi",
    "bengali": "bn",
    "arabic": "ar",
    "persian": "fa",
    "hebrew": "he",
    "urdu": "ur",
    "kazakh": "kk",
    "uzbek": "uz",
    "tagalog": "fil",
    "filipino": "fil",
}

_WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_RFI_RE = re.compile(r"\bRFI[\s#:\-]*0*(\d{1,6})\b", re.IGNORECASE)
_ORDINAL_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,4}){1,4})\b")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WORD_RE = re.compile(r"[\w][\w'\-]*", re.UNICODE)


# ── Glossary ─────────────────────────────────────────────────────────────────


def term_key(term: str) -> str:
    """Case-, accent-width- and whitespace-folded key used for uniqueness."""
    folded = unicodedata.normalize("NFKC", str(term or "")).casefold()
    return " ".join(folded.split())[:200]


def clean_term(term: Any) -> str:
    """Trim a candidate term; empty when it is unusable as a glossary entry."""
    text = " ".join(str(term or "").split())
    if len(text) < 2 or len(text) > MAX_TERM_CHARS:
        return ""
    if text.replace(".", "").replace(" ", "").isdigit():
        return ""
    return text


def clean_aliases(value: Any, *, term: str = "") -> list[str]:
    """Normalise a list (or comma string) of known mis-hearings."""
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        return []
    own = term_key(term)
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        text = clean_term(item)
        key = term_key(text)
        if not text or key == own or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= 20:
            break
    return out


def merge_seed_terms(candidates: list[dict[str, Any]], existing_keys: set[str] | None = None) -> list[dict[str, Any]]:
    """De-duplicate seed candidates by folded key, keeping the first occurrence.

    ``existing_keys`` holds keys already in the glossary, which are skipped so
    a re-seed never duplicates or overwrites a term.
    """
    taken = set(existing_keys or set())
    out: list[dict[str, Any]] = []
    for cand in candidates:
        text = clean_term(cand.get("term"))
        if not text:
            continue
        key = term_key(text)
        if key in taken:
            continue
        taken.add(key)
        kind = cand.get("kind") if cand.get("kind") in GLOSSARY_KINDS else "term"
        source = cand.get("source") if cand.get("source") in GLOSSARY_SOURCES else "manual"
        out.append(
            {
                "term": text,
                "term_key": key,
                "kind": kind,
                "source": source,
                "expansion": (str(cand.get("expansion") or "").strip()[:500] or None),
                "contact_id": (str(cand.get("contact_id")) if cand.get("contact_id") else None),
            }
        )
    return out


def _sorted_terms(terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (t for t in terms if str(t.get("term") or "").strip()),
        key=lambda t: (_HINT_ORDER.get(str(t.get("kind")), 9), str(t.get("term")).casefold()),
    )


def build_transcription_hint(terms: list[dict[str, Any]], *, limit: int = TRANSCRIPTION_HINT_CHARS) -> str:
    """Comma-separated vocabulary hint for the speech provider, bounded in size."""
    parts: list[str] = []
    used = 0
    for item in _sorted_terms(terms):
        text = str(item["term"]).strip()
        cost = len(text) + 2
        if used + cost > limit:
            break
        parts.append(text)
        used += cost
    return ", ".join(parts)


def build_glossary_block(terms: list[dict[str, Any]], *, limit: int = LLM_GLOSSARY_TERMS) -> str:
    """One line per term for the minutes AI: correct spelling, kind, meaning."""
    lines: list[str] = []
    for item in _sorted_terms(terms)[:limit]:
        line = f"- {item['term']} ({item.get('kind') or 'term'})"
        if item.get("expansion"):
            line += f": {item['expansion']}"
        aliases = [a for a in (item.get("aliases") or []) if isinstance(a, str)]
        if aliases:
            line += f" [often misheard as: {', '.join(aliases[:5])}]"
        lines.append(line)
    return "\n".join(lines)


def _alias_pattern(alias: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w]){re.escape(alias)}(?![\w])", re.IGNORECASE)


def apply_aliases(text: str, terms: list[dict[str, Any]]) -> tuple[str, int]:
    """Replace every known mis-hearing with the glossary spelling.

    Aliases are entered by a person, so applying them is a confirmed rule, not
    an AI guess. Returns the new text and how many replacements were made.
    """
    out = text or ""
    count = 0
    for item in terms:
        correct = str(item.get("term") or "").strip()
        if not correct:
            continue
        for alias in item.get("aliases") or []:
            if not isinstance(alias, str) or not alias.strip():
                continue
            out, n = _alias_pattern(alias.strip()).subn(correct, out)
            count += n
    return out, count


def apply_correction(text: str, heard: str, term: str) -> tuple[str, int]:
    """Replace one confirmed correction (whole words, any case)."""
    if not heard.strip() or not term.strip():
        return text, 0
    return _alias_pattern(heard.strip()).subn(term.strip(), text or "")


def suggest_corrections(text: str, terms: list[dict[str, Any]], *, limit: int = 30) -> list[dict[str, Any]]:
    """Offer near-miss spellings of glossary terms found in ``text``.

    Compares every run of words as long as a term against the term itself and
    keeps close but not exact matches. Short terms are skipped: a three-letter
    abbreviation is near half the dictionary.
    """
    words = _WORD_RE.findall(text or "")
    if not words:
        return []
    lowered = [w.casefold() for w in words]
    suggestions: dict[tuple[str, str], dict[str, Any]] = {}
    for item in terms:
        correct = str(item.get("term") or "").strip()
        if len(correct) < 4:
            continue
        target = correct.casefold()
        n = len(_WORD_RE.findall(correct)) or 1
        for i in range(0, len(words) - n + 1):
            window = " ".join(lowered[i : i + n])
            if window == target or abs(len(window) - len(target)) > 3:
                continue
            ratio = difflib.SequenceMatcher(None, window, target).ratio()
            if ratio < CORRECTION_MIN_RATIO:
                continue
            heard = " ".join(words[i : i + n])
            key = (heard.casefold(), correct)
            prev = suggestions.get(key)
            if prev is None or prev["confidence"] < ratio:
                suggestions[key] = {"heard": heard, "term": correct, "confidence": round(ratio, 2)}
    ranked = sorted(suggestions.values(), key=lambda s: -s["confidence"])
    return ranked[:limit]


# ── Language, speakers, segments ─────────────────────────────────────────────


def language_code(value: Any) -> str | None:
    """Reduce a language name or tag (``German``, ``de-DE``) to ISO 639-1."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().lower()
    if raw in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[raw]
    primary = raw.replace("_", "-").split("-")[0]
    if primary == "tl":
        return "fil"
    if 2 <= len(primary) <= 3 and primary.isalpha():
        return primary
    return None


def normalize_segments(value: Any, *, limit: int = 5000) -> list[dict[str, Any]]:
    """Clean user- or provider-supplied segments into ``{start, end, text, speaker}``."""
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in value[:limit]:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue

        def _num(v: Any) -> float | None:
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None

        out.append(
            {
                "start": _num(raw.get("start")),
                "end": _num(raw.get("end")),
                "text": text[:4000],
                "speaker": str(raw.get("speaker") or "").strip()[:100],
            }
        )
    return out


def speaker_labels(segments: list[dict[str, Any]]) -> list[str]:
    """Distinct speaker labels in order of first appearance."""
    seen: list[str] = []
    for seg in segments:
        label = str(seg.get("speaker") or "").strip()
        if label and label not in seen:
            seen.append(label)
    return seen


def normalize_speakers(value: Any, labels: list[str] | None = None) -> dict[str, dict[str, str | None]]:
    """Clean the ``{label: {name, contact_id}}`` map, optionally to known labels only."""
    if not isinstance(value, dict):
        return {}
    allowed = set(labels) if labels is not None else None
    out: dict[str, dict[str, str | None]] = {}
    for label, info in value.items():
        key = str(label).strip()[:100]
        if not key or (allowed is not None and key not in allowed):
            continue
        if isinstance(info, str):
            info = {"name": info}
        if not isinstance(info, dict):
            continue
        name = str(info.get("name") or "").strip()[:200]
        contact = str(info.get("contact_id") or "").strip()[:36] or None
        if name or contact:
            out[key] = {"name": name, "contact_id": contact}
    return out


def speaker_name(label: str, speakers: dict[str, Any]) -> str:
    """The person a label stands for, else the label itself."""
    info = speakers.get(label) if isinstance(speakers, dict) else None
    if isinstance(info, dict) and str(info.get("name") or "").strip():
        return str(info["name"]).strip()
    return label


def render_transcript(segments: list[dict[str, Any]], speakers: dict[str, Any], fallback: str = "") -> str:
    """Transcript text with speaker names resolved, one turn per line."""
    if not segments:
        return (fallback or "").strip()
    lines: list[str] = []
    for seg in segments:
        label = str(seg.get("speaker") or "").strip()
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{speaker_name(label, speakers)}: {text}" if label else text)
    return "\n".join(lines)


# ── Owners, dates, links ─────────────────────────────────────────────────────


def match_owner(raw_owner: str, people: list[dict[str, Any]]) -> dict[str, Any]:
    """Match a spoken owner name to a project person.

    ``people`` items carry ``name`` and optionally ``contact_id``. Returns the
    matched ``owner_name``/``owner_contact_id`` with an ``owner_confidence``:
    1.0 exact, 0.85 unique first- or last-name match, the fuzzy ratio for a
    close spelling, and the raw name with 0.0 when nobody matches.
    """
    name = " ".join(str(raw_owner or "").split())
    if not name:
        return {"owner_name": "", "owner_contact_id": None, "owner_confidence": 0.0}
    key = name.casefold()
    for person in people:
        if str(person.get("name") or "").casefold() == key:
            return {
                "owner_name": person["name"],
                "owner_contact_id": person.get("contact_id"),
                "owner_confidence": 1.0,
            }
    partial = [
        p for p in people if key in [part.casefold() for part in str(p.get("name") or "").split()] and len(key) >= 3
    ]
    if len(partial) == 1:
        p = partial[0]
        return {"owner_name": p["name"], "owner_contact_id": p.get("contact_id"), "owner_confidence": 0.85}
    best: tuple[float, dict[str, Any] | None] = (0.0, None)
    for person in people:
        ratio = difflib.SequenceMatcher(None, key, str(person.get("name") or "").casefold()).ratio()
        if ratio > best[0]:
            best = (ratio, person)
    if best[1] is not None and best[0] >= 0.8:
        return {
            "owner_name": best[1]["name"],
            "owner_contact_id": best[1].get("contact_id"),
            "owner_confidence": round(best[0], 2),
        }
    return {"owner_name": name[:200], "owner_contact_id": None, "owner_confidence": 0.0}


def resolve_due_date(raw: Any, meeting_date: Any) -> str | None:
    """Turn a spoken due date into ISO ``YYYY-MM-DD`` relative to the meeting.

    Accepts ISO dates and the English phrases a model or heuristic returns
    (tomorrow, a weekday, next week, end of week / month, in N days / weeks).
    Anything else is None so a person sets the date.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().lower()
    if _ISO_RE.match(text):
        try:
            date.fromisoformat(text)
        except ValueError:
            return None
        return text
    base = _parse_date(meeting_date) or datetime.now(UTC).date()
    if text in ("today", "eod", "end of day"):
        return base.isoformat()
    if text == "tomorrow":
        return (base + timedelta(days=1)).isoformat()
    for name, idx in _WEEKDAYS.items():
        if text in (name, f"by {name}", f"next {name}", f"on {name}"):
            # The next such weekday strictly after the meeting.
            delta = (idx - base.weekday()) % 7 or 7
            return (base + timedelta(days=delta)).isoformat()
    if text in ("next week",):
        return (base + timedelta(days=7)).isoformat()
    if text in ("end of week", "eow", "end of the week"):
        return (base + timedelta(days=(4 - base.weekday()) % 7)).isoformat()
    if text in ("end of month", "eom", "end of the month"):
        nxt = (base.replace(day=28) + timedelta(days=4)).replace(day=1)
        return (nxt - timedelta(days=1)).isoformat()
    if text in ("next month",):
        nxt = (base.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt.isoformat()
    m = re.match(r"^in\s+(\d{1,3})\s+(day|days|week|weeks)$", text)
    if m:
        n = int(m.group(1))
        days = n * 7 if m.group(2).startswith("week") else n
        return (base + timedelta(days=days)).isoformat()
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def detect_entity_link(
    text: str,
    rfis: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    hint: Any = None,
) -> dict[str, Any] | None:
    """Find the RFI or BOQ position an action talks about.

    ``hint`` is the model's own reference (``RFI-12``, ``03.02.010``); the text
    is searched when there is none. Only references that exist in the project
    are linked, so a link never points at nothing.
    """
    haystacks = [str(hint)] if isinstance(hint, str) and hint.strip() else []
    haystacks.append(text or "")
    by_number = {str(r.get("number") or "").lstrip("0") or "0": r for r in rfis}
    by_ordinal = {str(p.get("ordinal") or ""): p for p in positions if p.get("ordinal")}
    for hay in haystacks:
        for m in _RFI_RE.finditer(hay):
            rfi = by_number.get(m.group(1).lstrip("0") or "0")
            if rfi is not None:
                label = f"RFI {rfi.get('number')}"
                if rfi.get("subject"):
                    label += f" - {str(rfi['subject'])[:80]}"
                return {"type": "rfi", "id": str(rfi["id"]), "label": label}
        for m in _ORDINAL_RE.finditer(hay):
            pos = by_ordinal.get(m.group(1))
            if pos is not None:
                label = f"{pos['ordinal']} {str(pos.get('description') or '')[:80]}".strip()
                return {"type": "boq_position", "id": str(pos["id"]), "label": label}
    return None


def clean_link(value: Any) -> dict[str, Any] | None:
    """Validate a human-edited entity link."""
    if not isinstance(value, dict):
        return None
    kind = str(value.get("type") or "")
    ident = str(value.get("id") or "").strip()
    if kind not in LINKABLE_ENTITIES or not ident:
        return None
    return {"type": kind, "id": ident[:36], "label": str(value.get("label") or "").strip()[:200]}


# ── Proposals ────────────────────────────────────────────────────────────────


def _conf(value: Any, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(max(0.0, min(1.0, float(value))), 2)
    return round(default, 2)


def _text(value: Any, limit: int = 2000) -> str:
    if isinstance(value, dict):
        for key in ("text", "decision", "question", "task", "description", "summary"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()[:limit]
        return ""
    return str(value or "").strip()[:limit] if isinstance(value, (str, int, float)) else ""


def _first(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        val = data.get(key)
        if val not in (None, ""):
            return val
    return None


def build_proposals(
    llm_result: dict[str, Any] | None,
    *,
    heuristic: dict[str, Any] | None,
    people: list[dict[str, Any]],
    rfis: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    meeting_date: Any,
    transcript: str,
    glossary: list[dict[str, Any]],
    language: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the reviewable proposal set.

    Uses the model's output when there is one (``ai_generated`` True) and the
    keyword heuristic otherwise, at a low confidence so the reviewer reads it
    as a starting point. Every action gets an owner match, a resolved due date
    and an entity link when one is named; glossary near-misses become
    ``correction`` items. Every item starts ``pending``.
    """
    ai = isinstance(llm_result, dict)
    src: dict[str, Any] = llm_result if ai else {}
    base_conf = _conf(src.get("confidence"), 0.7) if ai else HEURISTIC_CONFIDENCE
    items: list[dict[str, Any]] = []

    def add(kind: str, **fields: Any) -> None:
        items.append({"id": f"{kind[0]}{len(items) + 1}", "kind": kind, "status": "pending", **fields})

    if ai:
        summary = _text(src.get("summary"), 6000)
        if summary:
            add("summary", text=summary, confidence=_conf(src.get("summary_confidence"), base_conf))
        for raw in (src.get("decisions") or [])[:30]:
            text = _text(raw, 1000)
            if text:
                conf = raw.get("confidence") if isinstance(raw, dict) else None
                quote = _text(raw.get("quote"), 500) if isinstance(raw, dict) else ""
                add("decision", text=text, confidence=_conf(conf, base_conf), source_quote=quote)
        raw_actions = src.get("action_items") or src.get("actions") or []
        for raw in raw_actions[:50]:
            if isinstance(raw, str):
                raw = {"task": raw}
            if not isinstance(raw, dict):
                continue
            text = _text(_first(raw, ("task", "action", "description", "text")), 1000)
            if not text:
                continue
            owner = match_owner(str(_first(raw, ("owner", "assignee", "responsible")) or ""), people)
            due_raw = _first(raw, ("due", "due_date", "deadline"))
            add(
                "action",
                text=text,
                confidence=_conf(raw.get("confidence"), base_conf),
                due_date=resolve_due_date(due_raw, meeting_date),
                due_hint=(str(due_raw)[:100] if due_raw else None),
                linked_entity=detect_entity_link(
                    text, rfis, positions, _first(raw, ("linked_ref", "reference", "ref"))
                ),
                source_quote=_text(raw.get("quote"), 500),
                **owner,
            )
        for raw in (src.get("open_questions") or src.get("questions") or [])[:30]:
            text = _text(raw, 1000)
            if text:
                conf = raw.get("confidence") if isinstance(raw, dict) else None
                add("question", text=text, confidence=_conf(conf, base_conf))
    elif heuristic:
        for dec in (heuristic.get("decisions") or [])[:20]:
            text = _text(dec, 1000)
            if text:
                add("decision", text=text, confidence=HEURISTIC_CONFIDENCE, source_quote=text[:500])
        for act in (heuristic.get("action_items") or [])[:30]:
            if not isinstance(act, dict):
                continue
            text = _text(act.get("description"), 1000)
            if not text:
                continue
            owner = match_owner(str(act.get("owner_name") or ""), people)
            add(
                "action",
                text=text,
                confidence=HEURISTIC_CONFIDENCE,
                due_date=resolve_due_date(act.get("due_date"), meeting_date),
                due_hint=(str(act.get("due_date"))[:100] if act.get("due_date") else None),
                linked_entity=detect_entity_link(text, rfis, positions),
                source_quote=text[:500],
                **owner,
            )

    seen_corrections: set[tuple[str, str]] = set()
    for raw in (src.get("spelling_corrections") or [])[:30]:
        if not isinstance(raw, dict):
            continue
        heard = _text(raw.get("heard"), 200)
        term = _text(raw.get("term"), 200)
        if heard and term and heard.casefold() != term.casefold() and heard.casefold() in transcript.casefold():
            seen_corrections.add((heard.casefold(), term))
            add(
                "correction",
                text=f"{heard} -> {term}",
                heard=heard,
                term=term,
                confidence=_conf(raw.get("confidence"), base_conf),
            )
    for sug in suggest_corrections(transcript, glossary):
        key = (sug["heard"].casefold(), sug["term"])
        if key in seen_corrections:
            continue
        seen_corrections.add(key)
        add(
            "correction",
            text=f"{sug['heard']} -> {sug['term']}",
            heard=sug["heard"],
            term=sug["term"],
            confidence=sug["confidence"],
        )

    return {
        "generated_at": (now or datetime.now(UTC)).isoformat(),
        "ai_generated": ai,
        "language": language,
        "items": items,
    }


def proposal_counts(proposals: dict[str, Any]) -> dict[str, int]:
    """How many proposals are pending, confirmed and rejected."""
    counts = dict.fromkeys(PROPOSAL_STATUSES, 0)
    for item in proposals.get("items") or [] if isinstance(proposals, dict) else []:
        status = item.get("status") if isinstance(item, dict) else None
        if status in counts:
            counts[status] += 1
    return counts


def action_confirm_problems(item: dict[str, Any]) -> list[str]:
    """Why a proposed action cannot become a tracked action yet (empty when it can)."""
    problems: list[str] = []
    if not str(item.get("text") or "").strip():
        problems.append("The action has no description.")
    if not str(item.get("owner_name") or "").strip() and not item.get("owner_contact_id"):
        problems.append("The action needs an owner.")
    due = item.get("due_date")
    if not isinstance(due, str) or not _ISO_RE.match(due):
        problems.append("The action needs a due date (YYYY-MM-DD).")
    return problems


def merge_review(item: dict[str, Any], edit: dict[str, Any]) -> dict[str, Any]:
    """Apply a reviewer's edits to one proposal (only the editable fields)."""
    merged = dict(item)
    for key in ("text", "owner_name", "due_date", "heard", "term"):
        if key in edit and edit[key] is not None:
            merged[key] = str(edit[key]).strip()[: 6000 if key == "text" else 1000]
    if "owner_contact_id" in edit:
        merged["owner_contact_id"] = (
            (str(edit["owner_contact_id"]).strip()[:36] or None) if edit["owner_contact_id"] else None
        )
    if "linked_entity" in edit:
        merged["linked_entity"] = clean_link(edit["linked_entity"])
    return merged


# ── Consent and retention ────────────────────────────────────────────────────


def consent_required(source: str, has_audio: bool) -> bool:
    """Live speech capture or stored audio needs the participants' consent."""
    return has_audio or source in CONSENT_SOURCES


def audio_expiry(created_at: datetime, retention_days: int | None) -> datetime | None:
    """When stored audio expires; None keeps it until someone deletes it."""
    if retention_days is None or retention_days <= 0:
        return None
    return created_at + timedelta(days=retention_days)


def audio_overdue(row: dict[str, Any], now: datetime) -> bool:
    """True when audio is still stored past its expiry."""
    if not row.get("audio_storage_key"):
        return False
    expires = row.get("audio_expires_at")
    if isinstance(expires, str):
        try:
            expires = datetime.fromisoformat(expires)
        except ValueError:
            return False
    if not isinstance(expires, datetime):
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires < now
