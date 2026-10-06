# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI Estimation Pydantic schemas - request/response models.

Defines schemas for AI settings management, quick/photo estimate requests,
and estimate job responses with generated BOQ items.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Money fields are stored / accepted as ``Decimal`` but emitted as plain
# decimal *strings* in JSON. ``float`` silently drops precision past ~15
# significant digits; emitting a string keeps totals exact and locale-neutral.
# Mirrors backend/app/modules/boq/schemas.py::_serialise_money.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# ── AI Settings schemas ──────────────────────────────────────────────────────


class AISettingsUpdate(BaseModel):
    """Update per-user AI configuration (API keys, preferred model)."""

    # NOTE: extra='forbid' deliberately NOT set - the onboarding wizard and the
    # AI settings page both POST a ``provider`` field that this schema does not
    # define (only ``preferred_model`` is read), so forbidding extras would 422
    # those existing callers. Keyless-provider key vanishing (issue #244) is
    # fixed on the frontend by not sending ``<provider>_api_key`` for them.
    model_config = ConfigDict(str_strip_whitespace=True)

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    kimi_api_key: str | None = None
    openrouter_api_key: str | None = None
    mistral_api_key: str | None = None
    groq_api_key: str | None = None
    deepseek_api_key: str | None = None
    together_api_key: str | None = None
    fireworks_api_key: str | None = None
    perplexity_api_key: str | None = None
    cohere_api_key: str | None = None
    ai21_api_key: str | None = None
    xai_api_key: str | None = None
    zhipu_api_key: str | None = None
    baidu_api_key: str | None = None
    yandex_api_key: str | None = None
    gigachat_api_key: str | None = None
    # Self-hosted endpoints (Ollama / vLLM); accepts a host root such as
    # "http://host:11434" and the path is appended downstream.
    ollama_base_url: str | None = None  # Ollama host root
    vllm_base_url: str | None = None  # OpenAI-compatible endpoint root (provider id "vllm")
    # Optional bearer key for the OpenAI-compatible endpoint (issue #499). An
    # empty string clears it.
    vllm_api_key: str | None = None
    # Per self-hosted endpoint: offer the assistant's tool schema ("auto" tries
    # and falls back if refused, "on" always sends it, "off" never). An empty
    # value returns the endpoint to the server default.
    tool_calling: dict[str, str] | None = None
    # Per-provider AI timeout in seconds (10..1800); null clears the override.
    timeouts: dict[str, int | None] | None = None
    preferred_model: str | None = Field(default=None, max_length=100)
    # Per-provider model-id override, e.g. {"gemini": "gemini-2.5-flash",
    # "openrouter": "anthropic/claude-sonnet-4"}. Lets users track provider
    # model renames/retirements without an app release (issue #129). A blank
    # value for a provider clears the override (falls back to the default).
    model_overrides: dict[str, str] | None = Field(
        default=None,
        description="Per-provider model id override (provider -> model id).",
    )

    @field_validator("ollama_base_url", "vllm_base_url")
    @classmethod
    def _reject_unsafe_base_url(cls, v: str | None) -> str | None:
        """SSRF guard for self-hosted AI endpoints.

        A user-supplied Ollama / vLLM URL is fetched server-side, so it may not
        point at a link-local or cloud-metadata address, and must satisfy the
        provider allowlist when one is configured. Loopback / private hosts stay
        allowed so a local runtime works out of the box. Runs at write time
        (422 on reject); ``ai_client`` re-checks after DNS at dispatch time.
        """
        if v is None or not v.strip():
            return v
        from app.config import get_settings
        from app.core.url_safety import UnsafeUrlError, validate_ai_provider_url

        try:
            validate_ai_provider_url(v.strip(), get_settings().ai_provider_allowlist_hosts)
        except UnsafeUrlError as exc:
            raise ValueError(str(exc)) from exc
        return v

    @field_validator("tool_calling")
    @classmethod
    def _known_tool_modes(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        """Only self-hosted endpoints are configurable, and only to a known mode."""
        if v is None:
            return v
        from app.modules.ai.ai_client import SELF_HOSTED_PROVIDERS, TOOL_CALLING_MODES

        for provider, mode in v.items():
            if provider not in SELF_HOSTED_PROVIDERS:
                msg = f"Tool calling is configurable only for {', '.join(SELF_HOSTED_PROVIDERS)}, not {provider!r}"
                raise ValueError(msg)
            if mode and mode not in TOOL_CALLING_MODES:
                msg = f"Tool calling mode must be one of {', '.join(TOOL_CALLING_MODES)}, not {mode!r}"
                raise ValueError(msg)
        return v

    @field_validator("timeouts")
    @classmethod
    def _bounded_timeouts(cls, v: dict[str, int | None] | None) -> dict[str, int | None] | None:
        """A timeout names a known provider and lies in the supported range."""
        if v is None:
            return v
        from app.config import AI_TIMEOUT_MAX_S, AI_TIMEOUT_MIN_S
        from app.modules.ai.ai_client import DEFAULT_MODELS

        for provider, seconds in v.items():
            if provider not in DEFAULT_MODELS:
                msg = f"Unknown AI provider {provider!r}"
                raise ValueError(msg)
            if seconds is not None and not AI_TIMEOUT_MIN_S <= seconds <= AI_TIMEOUT_MAX_S:
                msg = f"Timeout must be between {AI_TIMEOUT_MIN_S:g} and {AI_TIMEOUT_MAX_S:g} seconds"
                raise ValueError(msg)
        return v


class AISettingsResponse(BaseModel):
    """AI settings returned from the API.

    API keys are masked - only the last 4 characters are shown.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    user_id: UUID
    anthropic_api_key_set: bool = False
    openai_api_key_set: bool = False
    gemini_api_key_set: bool = False
    kimi_api_key_set: bool = False
    openrouter_api_key_set: bool = False
    mistral_api_key_set: bool = False
    groq_api_key_set: bool = False
    deepseek_api_key_set: bool = False
    together_api_key_set: bool = False
    fireworks_api_key_set: bool = False
    perplexity_api_key_set: bool = False
    cohere_api_key_set: bool = False
    ai21_api_key_set: bool = False
    xai_api_key_set: bool = False
    zhipu_api_key_set: bool = False
    baidu_api_key_set: bool = False
    yandex_api_key_set: bool = False
    gigachat_api_key_set: bool = False
    vllm_api_key_set: bool = False
    # Echo back any saved self-hosted endpoints so the UI can prefill them.
    ollama_base_url: str | None = None  # saved Ollama host root
    vllm_base_url: str | None = None  # saved OpenAI-compatible endpoint root
    # Saved per-endpoint tool calling modes and per-provider timeouts (issue
    # #499), plus the server defaults the UI shows when none is saved.
    tool_calling: dict[str, str] = Field(default_factory=dict)
    tool_calling_defaults: dict[str, str] = Field(default_factory=dict)
    timeouts: dict[str, int] = Field(default_factory=dict)
    default_timeout_seconds: float = 240.0
    # Authoritative "is AI usable" flag computed server-side. True when a
    # usable cloud key is set OR a local provider (Ollama / vLLM) is configured
    # via its base_url - local runtimes legitimately need no api_key. The
    # frontend reads this instead of re-deriving readiness from individual
    # key flags, so chat / estimate gating stays in sync with the backend.
    ai_ready: bool = False
    preferred_model: str
    # Effective per-provider model id the platform will send (override if the
    # user set one, otherwise the built-in default). Drives the editable
    # "Model name" field in Settings > AI.
    model_overrides: dict[str, str] = Field(default_factory=dict)
    default_models: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Estimate request schemas ─────────────────────────────────────────────────


class QuickEstimateRequest(BaseModel):
    """Text-based quick estimation request.

    The AI analyses the description and generates a full BOQ.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=10, max_length=5000, description="Project description")
    project_type: str | None = Field(
        default=None,
        max_length=100,
        description="Building type: office, residential, warehouse, etc.",
    )
    area_m2: float | None = Field(default=None, gt=0, le=1_000_000, description="Total area in m2")
    location: str | None = Field(default=None, max_length=200, description="City or country for pricing context")
    currency: str | None = Field(default=None, max_length=10, description="Currency code: EUR, USD, GBP, etc.")
    standard: str | None = Field(
        default=None,
        max_length=50,
        description="Classification standard: din276, nrm, masterformat",
    )
    project_id: UUID | None = Field(default=None, description="Optional project to link the estimate job to")


class PhotoEstimateRequest(BaseModel):
    """Photo-based estimation request metadata.

    The photo file is uploaded separately via multipart form data.
    This schema captures the additional context fields.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    location: str | None = Field(default=None, max_length=200)
    currency: str | None = Field(default=None, max_length=10)
    standard: str | None = Field(default=None, max_length=50)
    project_id: UUID | None = None


# ── Estimate result schemas ──────────────────────────────────────────────────


class EstimateItem(BaseModel):
    """A single work item generated by AI estimation.

    v3 §10 - ``unit_rate`` (money) is Decimal-as-string in JSON. ``total``
    is kept as ``float`` here because it is a UI-side preview value the
    frontend can recompute from ``quantity * unit_rate``; sibling
    ``CreateBOQFromEstimateRequest`` writes the persistent line totals
    via the boq service which is already Decimal-correct.
    """

    ordinal: str = ""
    description: str
    unit: str = "m2"
    quantity: float = 0.0
    unit_rate: Decimal = Decimal("0")
    total: float = 0.0
    classification: dict[str, str] = Field(default_factory=dict)
    category: str = "General"
    confidence: float | None = None

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class EstimateJobResponse(BaseModel):
    """Full AI estimation job response - status, items, and metadata.

    v3 §10 - money fields (``grand_total``, ``cost_usd_estimate``) are
    Decimal-as-string in JSON. The underlying DB column for
    ``cost_usd_estimate`` is Float (small USD values, no precision risk),
    but we still emit Decimal-as-string on the wire so the contract is
    uniform with every other money field.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    user_id: UUID
    project_id: UUID | None = None
    input_type: str
    input_text: str | None = None
    input_filename: str | None = None
    status: str
    items: list[EstimateItem] = Field(default_factory=list)
    # Resolved currency the items were priced in (ISO code or empty when the
    # currency is unknown). The frontend must show this ISO code rather than a
    # hard-coded EUR symbol, and never blend it with foreign-currency rates.
    currency: str = ""
    error_message: str | None = None
    model_used: str | None = None
    tokens_used: int = 0
    duration_ms: int = 0
    cost_usd_estimate: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")
    created_at: datetime
    updated_at: datetime

    @field_serializer("grand_total", "cost_usd_estimate", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class CreateBOQFromEstimateRequest(BaseModel):
    """Request to create a real BOQ from an AI estimate job."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    boq_name: str = Field(default="AI Estimate", min_length=1, max_length=255)
    # When true, run cost-DB enrichment during BOQ creation and replace each
    # line's AI rate with the best same-currency CWICR match (recording the
    # match code on the position). Lets the user persist the regional rates
    # they reviewed in the UI instead of the raw AI guesses. Off by default so
    # the legacy "save AI rates as-is" behaviour is unchanged.
    apply_enriched: bool = False
    # Region used for the cost-DB lookup when ``apply_enriched`` is set
    # (e.g. "DE_BERLIN"). Empty = search across all regions.
    region: str = Field(default="", max_length=64)


# ── Estimate history (server-side job list) ──────────────────────────────────


class EstimateJobSummary(BaseModel):
    """Lightweight summary of an estimate job for the history list.

    Excludes the full ``items`` payload (which can be large) so the list
    endpoint stays cheap to page through. The frontend fetches the full job
    via ``GET /ai/estimate/{id}`` when the user reopens one.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    input_type: str
    input_text: str | None = None
    input_filename: str | None = None
    status: str
    items_count: int = 0
    currency: str = ""
    grand_total: Decimal = Decimal("0")
    model_used: str | None = None
    tokens_used: int = 0
    cost_usd_estimate: Decimal = Decimal("0")
    duration_ms: int = 0
    error_message: str | None = None
    created_at: datetime

    @field_serializer("grand_total", "cost_usd_estimate", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class EstimateJobListResponse(BaseModel):
    """Paginated list of estimate-job summaries for the current user."""

    items: list[EstimateJobSummary] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0
