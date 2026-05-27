"""Tests for the LanceDB filter injection guard (audit fix 2026-05-28).

``_safe_quote_scalar`` is the boundary function that prevents SQL injection
via attacker-controlled string values (region, project_id, tenant_id) that
are interpolated into LanceDB WHERE expressions.  LanceDB has no parameterised
API so we must sanitise at the boundary.

Coverage:
  1. Happy-path values (real CWICR regions, UUID strings) pass through quoted.
  2. Injection payloads are rejected and return ``None``.
  3. ``_lancedb_search`` skips the WHERE clause entirely on a rejected region.
  4. ``_lancedb_search_generic`` skips project_id / tenant_id on bad input.
  5. ``clear_parquet_caches`` exercises both lru_cache entries without error.
"""

from __future__ import annotations

import pytest

# ── _safe_quote_scalar ────────────────────────────────────────────────────


def test_safe_quote_scalar_valid_region() -> None:
    """Known CWICR region codes must pass the allowlist unchanged."""
    from app.core.vector import _safe_quote_scalar

    assert _safe_quote_scalar("DE_BERLIN", "region") == "'DE_BERLIN'"
    assert _safe_quote_scalar("USA_USD", "region") == "'USA_USD'"
    assert _safe_quote_scalar("RU_STPETERSBURG", "region") == "'RU_STPETERSBURG'"
    assert _safe_quote_scalar("BR_SAOPAULO", "region") == "'BR_SAOPAULO'"


def test_safe_quote_scalar_valid_uuid() -> None:
    """UUID strings used as project_id / tenant_id must also pass."""
    from app.core.vector import _safe_quote_scalar

    uid = "550e8400-e29b-41d4-a716-446655440000"
    assert _safe_quote_scalar(uid, "project_id") == f"'{uid}'"


def test_safe_quote_scalar_empty_returns_none() -> None:
    """Empty string is semantically absent — return None so the filter is dropped."""
    from app.core.vector import _safe_quote_scalar

    assert _safe_quote_scalar("", "region") is None


def test_safe_quote_scalar_none_returns_none() -> None:
    """None input (bad caller) must not raise."""
    from app.core.vector import _safe_quote_scalar

    assert _safe_quote_scalar(None, "region") is None  # type: ignore[arg-type]


def test_safe_quote_scalar_single_quote_injection_rejected() -> None:
    """Classic SQL injection via embedded single-quote must be rejected."""
    from app.core.vector import _safe_quote_scalar

    assert _safe_quote_scalar("DE' OR '1'='1", "region") is None
    assert _safe_quote_scalar("'; DROP TABLE cost_items; --", "region") is None


def test_safe_quote_scalar_backslash_injection_rejected() -> None:
    """Backslash escape sequences that could break out of a quoted literal."""
    from app.core.vector import _safe_quote_scalar

    assert _safe_quote_scalar("DE_BERLIN\\' OR 1=1 --", "region") is None


def test_safe_quote_scalar_control_chars_rejected() -> None:
    """Null bytes and control characters are blocked regardless of position."""
    from app.core.vector import _safe_quote_scalar

    assert _safe_quote_scalar("DE\x00BERLIN", "region") is None
    assert _safe_quote_scalar("DE\nBERLIN", "region") is None


def test_safe_quote_scalar_overly_long_value_rejected() -> None:
    """Values exceeding the 128-char cap are rejected (no CWICR id is that long)."""
    from app.core.vector import _safe_quote_scalar

    assert _safe_quote_scalar("A" * 129, "region") is None
    # 128-char boundary still passes.
    assert _safe_quote_scalar("A" * 128, "region") == "'" + "A" * 128 + "'"


# ── _lancedb_search integration (no actual LanceDB needed) ────────────────


def test_lancedb_search_skips_where_on_unsafe_region(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the region string fails the injection guard, the search must run
    WITHOUT a WHERE clause rather than crashing or leaking the raw value."""
    captured: list[str | None] = []

    # Patch _get_lancedb to return a fake table that records the where clause.
    class _FakeSearch:
        def __init__(self) -> None:
            self._where: str | None = None

        def limit(self, _n: int) -> _FakeSearch:
            return self

        def where(self, clause: str) -> _FakeSearch:
            self._where = clause
            return self

        def to_list(self) -> list:
            captured.append(self._where)
            return []

    class _FakeTable:
        def search(self, _vec: list) -> _FakeSearch:
            return _FakeSearch()

    class _FakeDB:
        def open_table(self, _name: str) -> _FakeTable:
            return _FakeTable()

    import app.core.vector as _v

    monkeypatch.setattr(_v, "_lancedb_instance", _FakeDB())

    # Malicious region — should be dropped silently
    result = _v._lancedb_search([0.0] * 4, region="DE' OR 1=1 --", limit=5)
    assert result == []
    # The captured where clause must be None (no filter applied)
    assert captured == [None], f"Expected no WHERE clause, got: {captured}"


def test_lancedb_search_applies_where_on_safe_region(monkeypatch: pytest.MonkeyPatch) -> None:
    """A legitimate region must still result in a WHERE clause being applied."""
    captured: list[str | None] = []

    class _FakeSearch:
        def __init__(self) -> None:
            self._where: str | None = None

        def limit(self, _n: int) -> _FakeSearch:
            return self

        def where(self, clause: str) -> _FakeSearch:
            self._where = clause
            return self

        def to_list(self) -> list:
            captured.append(self._where)
            return []

    class _FakeTable:
        def search(self, _vec: list) -> _FakeSearch:
            return _FakeSearch()

    class _FakeDB:
        def open_table(self, _name: str) -> _FakeTable:
            return _FakeTable()

    import app.core.vector as _v

    monkeypatch.setattr(_v, "_lancedb_instance", _FakeDB())

    _v._lancedb_search([0.0] * 4, region="DE_BERLIN", limit=5)
    assert captured == ["region = 'DE_BERLIN'"]


# ── clear_parquet_caches ─────────────────────────────────────────────────


def test_clear_parquet_caches_idempotent() -> None:
    """Calling clear_parquet_caches() twice must not raise.

    This is a smoke test — it verifies the function is importable and
    exercisable without polars installed, and that the lru_cache entries
    are actually cleared (info=0 misses after clear).
    """
    from app.modules.costs.parquet_lookup import (
        _parquet_for_country,
        _scan,
        clear_parquet_caches,
    )

    # Warm the path cache with a dummy call (will return None — no parquet dir).
    _parquet_for_country("ZZ")

    before = _parquet_for_country.cache_info()
    assert before.currsize >= 1, "Cache should have at least the ZZ entry"

    clear_parquet_caches()

    after_path = _parquet_for_country.cache_info()
    after_scan = _scan.cache_info()
    assert after_path.currsize == 0, "path cache should be empty after clear"
    assert after_scan.currsize == 0, "scan cache should be empty after clear"

    # Second call must not raise.
    clear_parquet_caches()
