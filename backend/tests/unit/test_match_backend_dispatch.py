# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the match-backend selector in ``app.core.match_service``.

Historically this file pinned the LanceDB-vs-Qdrant dispatcher. The
LanceDB ranker was removed in v3 (Phase 5 cleanup), so the selector now
unconditionally returns the Qdrant ranker. The remaining test pins that
behaviour so a future regression that re-introduces a legacy path is
caught immediately.
"""

from __future__ import annotations

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Clear the lru_cache between tests so monkeypatched env vars stick."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_selector_returns_qdrant_ranker(monkeypatch):
    """The selector always returns the Qdrant ranker post-v3."""
    monkeypatch.delenv("MATCH_BACKEND", raising=False)
    get_settings.cache_clear()

    from app.core.match_service import _select_ranker

    rank_fn = _select_ranker()
    assert rank_fn.__module__ == "app.core.match_service.ranker_qdrant"


def test_public_rank_export_resolves_to_qdrant_ranker():
    """``app.core.match_service.rank`` is the Qdrant ranker post-v3.

    Direct importers of the public name pick up the new path without a
    code change.
    """
    from app.core.match_service import rank

    assert rank.__module__ == "app.core.match_service.ranker_qdrant"


def test_lancedb_match_backend_env_is_rejected_at_settings_load(monkeypatch):
    """An old ``MATCH_BACKEND=lancedb`` env value must surface clearly.

    The Settings validator rejects the legacy value at boot so a stale
    .env doesn't silently route through dead code (the legacy ranker no
    longer exists).
    """
    monkeypatch.setenv("MATCH_BACKEND", "lancedb")
    get_settings.cache_clear()

    from app.config import Settings

    with pytest.raises(ValueError, match="MATCH_BACKEND=lancedb"):
        Settings()
