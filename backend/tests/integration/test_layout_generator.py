"""Mock-based unit tests for the ACAP layout generator.

No network, no DB — monkeypatches ``call_ai`` and
``resolve_provider_key_model`` at module scope.
"""

from __future__ import annotations

import asyncio
import json

import pytest

# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

VALID_PLAN_JSON = {
    "kavling": {"width_m": 10.0, "length_m": 15.0},
    "levels": [
        {
            "level": 1,
            "rooms": [
                {
                    "name": "R. Tamu",
                    "type": "ruang_tamu",
                    "polygon": [
                        {"x": 0.0, "y": 0.0},
                        {"x": 4.0, "y": 0.0},
                        {"x": 4.0, "y": 4.0},
                        {"x": 0.0, "y": 4.0},
                    ],
                    "area_m2": 16.0,
                },
                {
                    "name": "K. Tidur Utama",
                    "type": "kamar_tidur_utama",
                    "polygon": [
                        {"x": 4.0, "y": 0.0},
                        {"x": 7.0, "y": 0.0},
                        {"x": 7.0, "y": 3.0},
                        {"x": 4.0, "y": 3.0},
                    ],
                    "area_m2": 9.0,
                },
                {
                    "name": "K. Mandi",
                    "type": "kamar_mandi",
                    "polygon": [
                        {"x": 7.0, "y": 0.0},
                        {"x": 8.5, "y": 0.0},
                        {"x": 8.5, "y": 1.5},
                        {"x": 7.0, "y": 1.5},
                    ],
                    "area_m2": 2.25,
                },
            ],
        }
    ],
    "jumlah_lantai": 1,
}

INVALID_OVERLAP_JSON = {
    "kavling": {"width_m": 10.0, "length_m": 10.0},
    "levels": [
        {
            "level": 1,
            "rooms": [
                {
                    "name": "A",
                    "type": "ruang_tamu",
                    "polygon": [
                        {"x": 0.0, "y": 0.0},
                        {"x": 4.0, "y": 0.0},
                        {"x": 4.0, "y": 4.0},
                        {"x": 0.0, "y": 4.0},
                    ],
                    "area_m2": 16.0,
                },
                {
                    "name": "B",
                    "type": "kamar_tidur",
                    "polygon": [
                        {"x": 2.0, "y": 2.0},
                        {"x": 6.0, "y": 2.0},
                        {"x": 6.0, "y": 6.0},
                        {"x": 2.0, "y": 6.0},
                    ],
                    "area_m2": 16.0,
                },
            ],
        }
    ],
    "jumlah_lantai": 1,
}


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _stub_resolve(settings=None):
    """Monkeypatch replacement for resolve_provider_key_model."""
    return ("anthropic", "test-key", "claude-sonnet")


async def _stub_ai_settings(session, user_id):
    """Monkeypatch replacement for _load_ai_settings."""
    return ("anthropic", "test-key", "claude-sonnet")


async def _stub_call_ai_valid(provider, api_key, system, prompt, **kwargs):
    return (json.dumps(VALID_PLAN_JSON), 100)


async def _stub_call_ai_invalid(provider, api_key, system, prompt, **kwargs):
    return (json.dumps(INVALID_OVERLAP_JSON), 100)


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_generate_success(monkeypatch):
    """call_ai returns valid JSON → generate_layout returns a FloorPlan."""
    monkeypatch.setattr(
        "app.modules.acap.layout.generator._load_ai_settings",
        _stub_ai_settings,
    )
    monkeypatch.setattr(
        "app.modules.acap.layout.generator.call_ai",
        _stub_call_ai_valid,
    )

    from app.modules.acap.layout.generator import generate_layout
    from app.modules.acap.layout.validator import validate_plan

    plan = asyncio.run(
        generate_layout(
            session=None,
            requirement_text="Test house",
            kavling_width_m=10,
            kavling_length_m=15,
        )
    )

    # Must not raise
    validate_plan(plan)
    assert plan.requirement_text == "Test house"
    assert plan.jumlah_lantai == 1


def test_generate_retries_then_succeeds(monkeypatch):
    """First call returns invalid plan, second returns valid → succeeds."""
    call_count = [0]

    async def flaky_call_ai(provider, api_key, system, prompt, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return (json.dumps(INVALID_OVERLAP_JSON), 100)
        return (json.dumps(VALID_PLAN_JSON), 100)

    monkeypatch.setattr(
        "app.modules.acap.layout.generator._load_ai_settings",
        _stub_ai_settings,
    )
    monkeypatch.setattr(
        "app.modules.acap.layout.generator.call_ai",
        flaky_call_ai,
    )

    from app.modules.acap.layout.generator import generate_layout
    from app.modules.acap.layout.validator import validate_plan

    plan = asyncio.run(
        generate_layout(
            session=None,
            requirement_text="Test",
            kavling_width_m=10,
            kavling_length_m=15,
        )
    )

    validate_plan(plan)
    assert call_count[0] == 2


def test_generate_all_invalid_raises(monkeypatch):
    """call_ai always returns invalid → raises LayoutGenerationError."""
    monkeypatch.setattr(
        "app.modules.acap.layout.generator._load_ai_settings",
        _stub_ai_settings,
    )
    monkeypatch.setattr(
        "app.modules.acap.layout.generator.call_ai",
        _stub_call_ai_invalid,
    )

    from app.modules.acap.layout.generator import LayoutGenerationError, generate_layout

    with pytest.raises(LayoutGenerationError) as exc_info:
        asyncio.run(
            generate_layout(
                session=None,
                requirement_text="Test",
                kavling_width_m=10,
                kavling_length_m=10,
                max_retries=2,
            )
        )

    assert exc_info.value.attempts == 2
    assert len(exc_info.value.reasons) > 0


def test_no_key_raises(monkeypatch):
    """resolve_provider_key_model raises ValueError → LayoutGenerationError with attempts=0."""

    async def raise_no_key(session, user_id):
        raise ValueError("No AI API key configured")

    monkeypatch.setattr(
        "app.modules.acap.layout.generator._load_ai_settings",
        raise_no_key,
    )

    from app.modules.acap.layout.generator import LayoutGenerationError, generate_layout

    with pytest.raises(LayoutGenerationError) as exc_info:
        asyncio.run(
            generate_layout(
                session=None,
                requirement_text="Test",
                kavling_width_m=10,
                kavling_length_m=10,
            )
        )

    assert exc_info.value.attempts == 0
    assert "No AI API key" in str(exc_info.value.reasons[0])
