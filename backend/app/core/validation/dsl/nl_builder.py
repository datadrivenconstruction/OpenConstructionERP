# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Natural-language → Compliance DSL builder (T13).

Bridges plain-English (and DE/RU) authoring with the strict YAML DSL
shipped in T08. The flow is:

1. The user types a plain sentence — *"all walls must have a fire-rating
   property"*.
2. :func:`parse_nl_to_dsl` runs a deterministic pattern matcher first.
   This is intentionally fast, predictable, and offline — every match
   carries a confidence score.
3. If pattern matching is uncertain *and* an AI client is available,
   the function falls back to LLM generation. The generated YAML is
   then re-parsed via :mod:`app.core.validation.dsl.parser`; on parse
   failure the AI result is rejected.

The pattern matcher knows nothing about the user's project schema — it
only emits valid DSL skeletons. Users always confirm the generated
YAML before saving (the router never auto-persists). This keeps the
"AI-augmented, human-confirmed" principle intact.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.validation.dsl.parser import (
    DSLError,
    parse_definition,
)

logger = logging.getLogger(__name__)


# ── Public DTO ─────────────────────────────────────────────────────────────


@dataclass
class NlBuildResult:
    """Outcome of an NL → DSL conversion.

    Attributes:
        dsl_definition: A dict that *should* parse cleanly through
            :func:`parse_definition`. Empty dict if no pattern matched.
        confidence: 0..1. Pattern hits start at 0.85+, AI fallbacks at
            0.6, ambiguous fallbacks at 0.3.
        used_method: Which pipeline produced the result.
        errors: Human-readable issues. Non-empty when the result is
            unusable.
        matched_pattern: ID of the pattern that fired (None for AI/fallback).
        suggestions: Hints the UI can show — e.g. "rephrase as 'all <X>
            must have <Y>'".
    """

    dsl_definition: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    used_method: str = "fallback"  # "pattern" | "ai" | "fallback"
    errors: list[str] = field(default_factory=list)
    matched_pattern: str | None = None
    suggestions: list[str] = field(default_factory=list)


# ── Pattern descriptors ────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Pattern:
    """One NL → DSL conversion pattern.

    Each pattern owns a compiled regex and a builder callable that turns
    the regex match into a DSL dict. Patterns are evaluated in priority
    order; the first match wins.
    """

    pattern_id: str
    name_key: str  # i18n key — e.g. "compliance.nl.pattern.must_have"
    confidence: float
    regex: re.Pattern[str]
    builder: Any  # Callable[[re.Match[str]], dict[str, Any]]


_MAX_INPUT_LEN = 2_000

# Identifier extraction: lowercase letters/digits/underscore, normalised
# from user input. We strip pluralisation (s, es) and convert spaces to
# underscores so "fire rating" and "fire_rating" both become
# "fire_rating".
_PLURAL_SUFFIXES = ("ies", "es", "s")


def _slug(text: str) -> str:
    """Normalise an English/DE/RU noun phrase into a DSL identifier."""
    s = text.strip().lower()
    # Strip surrounding punctuation/quotes.
    s = s.strip("'\"`.,;:!?()[]{}")
    # Replace spaces / dashes with underscores.
    s = re.sub(r"[\s\-]+", "_", s)
    # Drop characters outside [a-z0-9_].
    s = re.sub(r"[^a-z0-9_]", "", s)
    # Collapse repeated underscores.
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _singular(slug: str) -> str:
    """Best-effort singularisation for English plurals."""
    for suffix in _PLURAL_SUFFIXES:
        if slug.endswith(suffix) and len(slug) > len(suffix) + 1:
            stripped = slug[: -len(suffix)]
            if suffix == "ies":
                return stripped + "y"
            return stripped
    return slug


def _gen_rule_id(prefix: str, entity: str, field_: str) -> str:
    """Compose a stable rule_id from parts."""
    parts = [p for p in (prefix, entity, field_) if p]
    candidate = ".".join(parts).strip(".")
    # rule_id allows [a-z0-9_.] only.
    candidate = re.sub(r"[^a-z0-9_.]", "_", candidate.lower())
    candidate = re.sub(r"\.+", ".", candidate).strip(".")
    return candidate or "custom.rule"


def _coerce_number(text: str) -> int | float | str:
    """Try int, then float, fallback to a quoted string literal."""
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    # Strip optional surrounding quotes from user input.
    if (text.startswith("'") and text.endswith("'")) or (
        text.startswith('"') and text.endswith('"')
    ):
        text = text[1:-1]
    return f"'{text}'"


# ── Pattern builders ───────────────────────────────────────────────────────


def _b_must_have(m: re.Match[str]) -> dict[str, Any]:
    """``all <entity> must have <field>`` →  forEach + assert != null."""
    entity = _singular(_slug(m.group("entity")))
    field_ = _slug(m.group("field"))
    rule_id = _gen_rule_id("custom", entity, f"has_{field_}")
    return {
        "rule_id": rule_id,
        "name": f"All {entity} must have {field_.replace('_', ' ')}",
        "severity": "warning",
        "scope": entity,
        "expression": {
            "forEach": entity,
            "assert": {"!=": [f"{entity}.{field_}", None]},
        },
    }


def _b_must_not_have(m: re.Match[str]) -> dict[str, Any]:
    """``no <entity> can have <field> = <value>`` → forEach + not(==)."""
    entity = _singular(_slug(m.group("entity")))
    field_ = _slug(m.group("field"))
    value = _coerce_number(m.group("value"))
    rule_id = _gen_rule_id("custom", entity, f"no_{field_}_eq")
    return {
        "rule_id": rule_id,
        "name": f"No {entity} can have {field_.replace('_', ' ')} = {value}",
        "severity": "error",
        "scope": entity,
        "expression": {
            "forEach": entity,
            "assert": {"not": [{"==": [f"{entity}.{field_}", value]}]},
        },
    }


def _b_value_equals(m: re.Match[str]) -> dict[str, Any]:
    """``every <entity> must have <field> equal to <value>`` → ==."""
    entity = _singular(_slug(m.group("entity")))
    field_ = _slug(m.group("field"))
    value = _coerce_number(m.group("value"))
    rule_id = _gen_rule_id("custom", entity, f"{field_}_eq")
    return {
        "rule_id": rule_id,
        "name": f"Every {entity} must have {field_.replace('_', ' ')} = {value}",
        "severity": "warning",
        "scope": entity,
        "expression": {
            "forEach": entity,
            "assert": {"==": [f"{entity}.{field_}", value]},
        },
    }


def _b_value_greater(m: re.Match[str]) -> dict[str, Any]:
    """``every <entity> must have <field> greater than <N>`` → >."""
    entity = _singular(_slug(m.group("entity")))
    field_ = _slug(m.group("field"))
    value = _coerce_number(m.group("value"))
    rule_id = _gen_rule_id("custom", entity, f"{field_}_gt")
    return {
        "rule_id": rule_id,
        "name": f"Every {entity} must have {field_.replace('_', ' ')} > {value}",
        "severity": "warning",
        "scope": entity,
        "expression": {
            "forEach": entity,
            "assert": {">": [f"{entity}.{field_}", value]},
        },
    }


def _b_value_at_least(m: re.Match[str]) -> dict[str, Any]:
    """``every <entity> must have <field> >= <N>`` (or ``at least``)."""
    entity = _singular(_slug(m.group("entity")))
    field_ = _slug(m.group("field"))
    value = _coerce_number(m.group("value"))
    rule_id = _gen_rule_id("custom", entity, f"{field_}_gte")
    return {
        "rule_id": rule_id,
        "name": f"Every {entity} must have {field_.replace('_', ' ')} >= {value}",
        "severity": "warning",
        "scope": entity,
        "expression": {
            "forEach": entity,
            "assert": {">=": [f"{entity}.{field_}", value]},
        },
    }


def _b_value_less(m: re.Match[str]) -> dict[str, Any]:
    """``every <entity> must have <field> less than <N>`` → <."""
    entity = _singular(_slug(m.group("entity")))
    field_ = _slug(m.group("field"))
    value = _coerce_number(m.group("value"))
    rule_id = _gen_rule_id("custom", entity, f"{field_}_lt")
    return {
        "rule_id": rule_id,
        "name": f"Every {entity} must have {field_.replace('_', ' ')} < {value}",
        "severity": "warning",
        "scope": entity,
        "expression": {
            "forEach": entity,
            "assert": {"<": [f"{entity}.{field_}", value]},
        },
    }


def _b_count_at_least(m: re.Match[str]) -> dict[str, Any]:
    """``there must be at least <N> <entity>`` → single assert count >= N."""
    entity = _singular(_slug(m.group("entity")))
    value = _coerce_number(m.group("value"))
    rule_id = _gen_rule_id("custom", entity, "count_min")
    return {
        "rule_id": rule_id,
        "name": f"At least {value} {entity} required",
        "severity": "warning",
        "scope": entity,
        "expression": {
            "assert": {">=": [{"count": "*"}, value]},
        },
    }


def _b_count_zero(m: re.Match[str]) -> dict[str, Any]:
    """``there must be no <entity>`` → single assert count == 0."""
    entity = _singular(_slug(m.group("entity")))
    rule_id = _gen_rule_id("custom", entity, "count_zero")
    return {
        "rule_id": rule_id,
        "name": f"No {entity} allowed",
        "severity": "error",
        "scope": entity,
        "expression": {
            "assert": {"==": [{"count": "*"}, 0]},
        },
    }


# ── Pattern table — order matters (longest / most specific first) ──────────


_PATTERNS: tuple[_Pattern, ...] = (
    # "every wall must have fire_rating >= 60"
    _Pattern(
        pattern_id="value_at_least",
        name_key="compliance.nl.pattern.value_at_least",
        confidence=0.92,
        regex=re.compile(
            r"^\s*(?:all|every|each)\s+(?P<entity>[\w\s\-]+?)\s+"
            r"(?:must|should|need(?:s)?\s+to|has\s+to)\s+(?:have|contain)\s+"
            r"(?:a\s+|an\s+|the\s+)?(?P<field>[\w\s\-]+?)\s+"
            r"(?:>=|at\s+least|of\s+at\s+least|no\s+less\s+than|"
            r"greater\s+(?:than\s+)?or\s+equal\s+to)\s+"
            r"(?P<value>[\-+]?\d+(?:\.\d+)?)\s*$",
            re.IGNORECASE,
        ),
        builder=_b_value_at_least,
    ),
    # "every wall must have fire_rating greater than 60"
    _Pattern(
        pattern_id="value_greater_than",
        name_key="compliance.nl.pattern.value_greater_than",
        confidence=0.9,
        regex=re.compile(
            r"^\s*(?:all|every|each)\s+(?P<entity>[\w\s\-]+?)\s+"
            r"(?:must|should|need(?:s)?\s+to|has\s+to)\s+(?:have|contain)\s+"
            r"(?:a\s+|an\s+|the\s+)?(?P<field>[\w\s\-]+?)\s+"
            r"(?:>|greater\s+than|more\s+than|above)\s+"
            r"(?P<value>[\-+]?\d+(?:\.\d+)?)\s*$",
            re.IGNORECASE,
        ),
        builder=_b_value_greater,
    ),
    # "every wall must have fire_rating less than 30"
    _Pattern(
        pattern_id="value_less_than",
        name_key="compliance.nl.pattern.value_less_than",
        confidence=0.9,
        regex=re.compile(
            r"^\s*(?:all|every|each)\s+(?P<entity>[\w\s\-]+?)\s+"
            r"(?:must|should|need(?:s)?\s+to|has\s+to)\s+(?:have|contain)\s+"
            r"(?:a\s+|an\s+|the\s+)?(?P<field>[\w\s\-]+?)\s+"
            r"(?:<|less\s+than|under|below|smaller\s+than)\s+"
            r"(?P<value>[\-+]?\d+(?:\.\d+)?)\s*$",
            re.IGNORECASE,
        ),
        builder=_b_value_less,
    ),
    # "every wall must have material equal to concrete"
    _Pattern(
        pattern_id="value_equals",
        name_key="compliance.nl.pattern.value_equals",
        confidence=0.88,
        regex=re.compile(
            r"^\s*(?:all|every|each)\s+(?P<entity>[\w\s\-]+?)\s+"
            r"(?:must|should|need(?:s)?\s+to|has\s+to)\s+(?:have|contain)\s+"
            r"(?:a\s+|an\s+|the\s+)?(?P<field>[\w\s\-]+?)\s+"
            r"(?:=|==|equal\s+to|equals|of)\s+"
            r"(?P<value>[\-+]?\d+(?:\.\d+)?|'[^']+'|\"[^\"]+\"|[a-z0-9_]+)"
            r"\s*$",
            re.IGNORECASE,
        ),
        builder=_b_value_equals,
    ),
    # "no wall can have status = draft"
    _Pattern(
        pattern_id="must_not_have",
        name_key="compliance.nl.pattern.must_not_have",
        confidence=0.88,
        regex=re.compile(
            r"^\s*no\s+(?P<entity>[\w\s\-]+?)\s+"
            r"(?:can|may|should|must)\s+have\s+"
            r"(?:a\s+|an\s+|the\s+)?(?P<field>[\w\s\-]+?)\s+"
            r"(?:=|==|equal\s+to|equals|of)\s+"
            r"(?P<value>[\-+]?\d+(?:\.\d+)?|'[^']+'|\"[^\"]+\"|[a-z0-9_]+)"
            r"\s*$",
            re.IGNORECASE,
        ),
        builder=_b_must_not_have,
    ),
    # "there must be at least 3 walls"
    _Pattern(
        pattern_id="count_at_least",
        name_key="compliance.nl.pattern.count_at_least",
        confidence=0.86,
        regex=re.compile(
            r"^\s*(?:there\s+(?:must|should)\s+be|require[sd]?)\s+"
            r"(?:at\s+least\s+)?(?P<value>\d+)\s+"
            r"(?P<entity>[\w\s\-]+?)\s*$",
            re.IGNORECASE,
        ),
        builder=_b_count_at_least,
    ),
    # "there must be no walls" / "no walls allowed"
    _Pattern(
        pattern_id="count_zero",
        name_key="compliance.nl.pattern.count_zero",
        confidence=0.85,
        regex=re.compile(
            r"^\s*(?:there\s+(?:must|should)\s+be\s+no|no)\s+"
            r"(?P<entity>[\w\s\-]+?)\s+(?:allowed|permitted)\s*$",
            re.IGNORECASE,
        ),
        builder=_b_count_zero,
    ),
    # "all walls must have a fire-rating property" — generic must-have.
    # Keep this pattern *last* among universal-quantifier rules because
    # value-based forms above are more specific.
    _Pattern(
        pattern_id="must_have",
        name_key="compliance.nl.pattern.must_have",
        confidence=0.9,
        regex=re.compile(
            r"^\s*(?:all|every|each)\s+(?P<entity>[\w\s\-]+?)\s+"
            r"(?:must|should|need(?:s)?\s+to|has\s+to)\s+(?:have|contain)\s+"
            r"(?:a\s+|an\s+|the\s+)?(?P<field>[\w\s\-]+?)"
            r"(?:\s+(?:property|field|attribute|value))?\s*\.?\s*$",
            re.IGNORECASE,
        ),
        builder=_b_must_have,
    ),
)


# ── Localised aliases — trivial pre-pass to English ────────────────────────

_DE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\balle\b", "all"),
    (r"\bjede(?:r|s)?\b", "every"),
    (r"\bmüssen\b", "must"),
    (r"\bmuss\b", "must"),
    (r"\bsollte(?:n)?\b", "should"),
    (r"\bhaben\b", "have"),
    (r"\bhat\b", "have"),
    (r"\bkein(?:e|er|en)?\b", "no"),
    (r"\bdarf\b", "can"),
    (r"\bdürfen\b", "can"),
    (r"\bgleich\b", "equal to"),
    (r"\bgrößer\s+als\b", "greater than"),
    (r"\bkleiner\s+als\b", "less than"),
    (r"\bmindestens\b", "at least"),
    (r"\bes\s+muss\b", "there must be"),
    (r"\bes\s+müssen\b", "there must be"),
)

_RU_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bвсе\b", "all"),
    (r"\bкаждая\b", "every"),
    (r"\bкаждый\b", "every"),
    (r"\bкаждое\b", "every"),
    (r"\bдолжен\b", "must"),
    (r"\bдолжна\b", "must"),
    (r"\bдолжно\b", "must"),
    (r"\bдолжны\b", "must"),
    (r"\bиметь\b", "have"),
    (r"\bсодержать\b", "contain"),
    (r"\bбольше\b", "greater than"),
    (r"\bменьше\b", "less than"),
    (r"\bне\s+менее\b", "at least"),
    (r"\bравно\b", "equal to"),
    (r"\bне\s+может\b", "can not"),
    (r"\bни\s+один\b", "no"),
    (r"\bникакой\b", "no"),
)


# Bound the inner field length so the regex cannot exhibit polynomial
# backtracking (CodeQL `py/polynomial-redos`). The inner class includes `\s`
# AND the outer suffix is `\s+have` — without an explicit upper bound an
# adversarial input like "must " + "a"*N + " havz" would force quadratic
# scanning. 100 chars is well above any real DSL phrase length.
_DE_V2_REORDER = re.compile(
    r"\bmust\s+(?P<field>[a-zäöüß0-9_\s\-]{1,100}?)\s+have\b",
    re.IGNORECASE,
)


def _translate_to_en(text: str, lang: str) -> str:
    """Cheap word-level mapping so the English regex pool fires for DE/RU."""
    rules: tuple[tuple[str, str], ...]
    is_de = lang.lower().startswith("de")
    is_ru = lang.lower().startswith("ru")
    if is_de:
        rules = _DE_REPLACEMENTS
    elif is_ru:
        rules = _RU_REPLACEMENTS
    else:
        return text
    out = text
    for pat, repl in rules:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    if is_de:
        # German V2 word order: "müssen X haben" → "must have X".
        out = _DE_V2_REORDER.sub(lambda m: f"must have {m.group('field').strip()}", out)
    return out


# ── Pattern matcher entry point ────────────────────────────────────────────


def _try_patterns(
    text: str, lang: str,
) -> tuple[_Pattern, dict[str, Any]] | None:
    """Run the deterministic pattern table; return match + dict.

    Returns ``None`` if nothing fires.
    """
    candidate = _translate_to_en(text, lang)
    # Strip trailing dots and surrounding whitespace.
    candidate = candidate.strip().rstrip(".").strip()
    for pat in _PATTERNS:
        match = pat.regex.match(candidate)
        if match is None:
            continue
        try:
            return pat, pat.builder(match)
        except Exception:  # pragma: no cover — defensive
            logger.exception("NL pattern '%s' builder crashed", pat.pattern_id)
            continue
    return None


# ── AI fallback ────────────────────────────────────────────────────────────


_AI_SYSTEM_PROMPT = """\
You are a Compliance DSL author for OpenConstructionERP. Convert the
user's plain-English construction validation rule into a YAML document
that matches this schema:

  rule_id: <lowercase dotted identifier>
  name: <human-readable rule name>
  severity: error | warning | info
  scope: <singular entity, e.g. wall, position>
  expression:
    forEach: <iter_var>
    assert: <expression>

OR a single-assert form:

  expression:
    assert: <expression>

Only respond with the YAML in a code fence — no prose. Identifiers
must be lowercase ASCII with underscores. Allowed comparison operators:
==, !=, <, <=, >, >=, in. Allowed logical operators: and, or, not.
Aggregations: count, sum, avg, min, max.
"""


def _strip_yaml_fence(text: str) -> str:
    """Pluck the YAML out of a Markdown fence if the AI added one."""
    cleaned = text.strip()
    fence = re.search(
        r"```(?:yaml|yml)?\s*\n(?P<body>.*?)\n```",
        cleaned,
        re.DOTALL | re.IGNORECASE,
    )
    if fence is not None:
        return fence.group("body").strip()
    return cleaned


async def _ai_fallback(
    text: str,
    *,
    lang: str,
    ai_caller: Any | None,
) -> tuple[dict[str, Any], list[str]] | None:
    """Optional LLM call — returns a parsed dict or ``None`` on failure.

    ``ai_caller`` is a coroutine ``(system, prompt) -> str``. The
    function never raises — failures degrade to ``None`` so the caller
    can keep the deterministic pattern result if any.
    """
    if ai_caller is None:
        return None

    user_prompt = (
        f"User language: {lang}\n"
        f"User rule: {text}\n\n"
        f"Return the YAML rule definition only."
    )
    try:
        raw = await ai_caller(_AI_SYSTEM_PROMPT, user_prompt)
    except Exception as exc:  # broad — providers raise diverse errors
        logger.warning("NL builder AI call failed: %s", exc)
        return None

    if not isinstance(raw, str) or not raw.strip():
        return None

    yaml_text = _strip_yaml_fence(raw)
    try:
        # Validate via the strict T08 parser. parse_definition returns
        # a typed AST but we re-serialise to dict via the loader path
        # to keep the public DTO simple (router can lint independently).
        import yaml  # lazy — keeps import cheap when AI is disabled.

        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return None
        # Round-trip through the parser to confirm validity. We discard
        # the typed AST — the dict itself is what the UI shows.
        parse_definition(data)
        return data, []
    except DSLError as exc:
        return None, [f"AI output rejected: {exc}"]  # type: ignore[return-value]
    except Exception as exc:  # YAMLError or other
        logger.warning("AI YAML parse failed: %s", exc)
        return None


# ── Public API ─────────────────────────────────────────────────────────────


def list_supported_patterns() -> list[dict[str, Any]]:
    """Return metadata for the UI's pattern hints panel.

    Stable IDs and i18n keys; no example strings (the frontend renders
    them so they can be translated).
    """
    return [
        {
            "pattern_id": p.pattern_id,
            "name_key": p.name_key,
            "confidence": p.confidence,
        }
        for p in _PATTERNS
    ]


async def parse_nl_to_dsl(
    text: str,
    *,
    lang: str = "en",
    use_ai: bool = False,
    ai_caller: Any | None = None,
) -> NlBuildResult:
    """Convert a natural-language sentence into a Compliance DSL dict.

    Args:
        text: User sentence (English / German / Russian).
        lang: ISO-639-1 code — used to pick the alias table. Falls back
            to English-only matching for unknown values.
        use_ai: When ``True`` *and* ``ai_caller`` is provided, low-
            confidence pattern misses trigger an AI call. Without an
            AI caller the flag is a no-op so the function never crashes
            on missing API keys.
        ai_caller: Async callable ``(system, prompt) -> str``. Inject
            from the router so the DSL module stays free of HTTP deps.

    Returns:
        :class:`NlBuildResult`. Always non-None — even on error the
        caller can render ``errors`` and ``suggestions``.
    """
    if not isinstance(text, str):
        return NlBuildResult(
            errors=["Input must be a string."],
        )
    stripped = text.strip()
    if not stripped:
        return NlBuildResult(
            errors=["Input is empty."],
        )
    if len(stripped) > _MAX_INPUT_LEN:
        return NlBuildResult(
            errors=[f"Input exceeds {_MAX_INPUT_LEN} characters."],
        )

    lang_norm = (lang or "en").strip().lower() or "en"

    # 1. Deterministic pattern matcher.
    matched = _try_patterns(stripped, lang_norm)
    if matched is not None:
        pat, dsl = matched
        # Sanity-check: confirm our generated dict actually parses.
        try:
            parse_definition(dsl)
        except DSLError as exc:
            logger.warning(
                "NL pattern '%s' produced invalid DSL: %s", pat.pattern_id, exc,
            )
        else:
            return NlBuildResult(
                dsl_definition=dsl,
                confidence=pat.confidence,
                used_method="pattern",
                matched_pattern=pat.pattern_id,
            )

    # 2. AI fallback — only if requested and a caller was injected.
    if use_ai and ai_caller is not None:
        ai_result = await _ai_fallback(
            stripped, lang=lang_norm, ai_caller=ai_caller,
        )
        if ai_result is not None:
            data, ai_errors = ai_result
            if data:
                return NlBuildResult(
                    dsl_definition=data,
                    confidence=0.6,
                    used_method="ai",
                    errors=ai_errors,
                )
            # data is empty but errors populated — invalid AI output.
            return NlBuildResult(
                used_method="ai",
                confidence=0.0,
                errors=ai_errors or [
                    "AI response could not be parsed as a DSL document.",
                ],
                suggestions=_default_suggestions(),
            )

    # 3. Nothing matched — return a low-confidence empty result with
    #    actionable hints.
    return NlBuildResult(
        used_method="fallback",
        confidence=0.0,
        errors=["No pattern matched the input sentence."],
        suggestions=_default_suggestions(),
    )


def _default_suggestions() -> list[str]:
    """Hints rendered when nothing matched — kept intent-free of locale."""
    return [
        "Try: 'all <entity> must have <field>'",
        "Try: 'every <entity> must have <field> >= <number>'",
        "Try: 'no <entity> can have <field> = <value>'",
        "Try: 'there must be at least <N> <entity>'",
    ]


__all__ = [
    "NlBuildResult",
    "list_supported_patterns",
    "parse_nl_to_dsl",
]
