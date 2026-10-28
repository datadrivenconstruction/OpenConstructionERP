# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the compliance_ai module.

Mirrors the public DTO shape of :mod:`app.core.validation.dsl.nl_builder`
so the router stays a thin envelope and the upstream library remains the
single source of truth for the NL → DSL contract.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# Hard cap on the input sentence - kept in lock-step with
# ``app.core.validation.dsl.nl_builder._MAX_INPUT_LEN`` so a request that
# would later be rejected by the library is rejected at the schema layer
# with a 422 instead of bubbling out as an empty NlBuildResult. Also
# closes the LLM-cost runaway hole: an unbounded ``text`` field would let
# a caller send 1 MB of "rule" prose, the AI fallback would forward it,
# and provider tokens would burn - by the time rate-limit kicks in the
# damage is done.
_MAX_INPUT_LEN = 2_000

# Restrict lang to ISO-639-1 / -2 shapes the NL builder actually handles
# today (en/de/ru). Other values fall through to English in the library;
# we still allow them through at the schema level so the contract stays
# forward-compatible - the verdict log records the requested lang so
# coverage gaps are visible from prod telemetry.
_MAX_LANG_LEN = 12


class NlVerifyRequest(BaseModel):
    """Body for ``POST /v1/compliance-ai/from-nl``.

    Attributes:
        text: User sentence (plain language). Capped at 2_000 chars to
            bound LLM token cost - see module docstring.
        lang: Locale hint for the deterministic pattern matcher.
        use_ai: When ``True`` and an API key is configured, allow the
            LLM fallback for low-confidence pattern misses. Defaults to
            ``False`` so a typo never costs money.
    """

    text: str = Field(..., min_length=1, max_length=_MAX_INPUT_LEN)
    lang: str = Field("en", min_length=2, max_length=_MAX_LANG_LEN)
    use_ai: bool = False


class NlVerifyResponse(BaseModel):
    """Result envelope - canonical NL-builder verdict.

    Fields mirror :class:`app.core.validation.dsl.nl_builder.NlBuildResult`
    plus the rendered YAML for UI convenience.
    """

    dsl_definition: dict[str, Any] = Field(default_factory=dict)
    dsl_yaml: str | None = None
    confidence: float = 0.0
    used_method: str = "fallback"
    matched_pattern: str | None = None
    errors: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


__all__ = [
    "NlVerifyRequest",
    "NlVerifyResponse",
]
