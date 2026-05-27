"""Tests for ranker_qdrant's payload-derived fallbacks.

When the snapshot install populates Qdrant vectors but the SQL/parquet
side is empty (the v3.0.x default — only metadata in the snapshot),
``_hit_to_candidate`` must still produce a non-empty description and a
currency tag derived from the country head; otherwise the BGE
cross-encoder reranker collapses the score to ≈0 and the operator sees
empty rate fields. These tests pin the fallback behaviour.
"""

from __future__ import annotations

import pytest

from app.core.match_service.ranker_qdrant import (
    _COUNTRY_DEFAULT_CURRENCY,
    _description_from_payload,
    _hit_to_candidate,
)


class _Hit:
    """Minimal QdrantHit double — the function only reads .payload / .score / etc."""

    def __init__(self, payload: dict, rate_code: str = "ABC_DEF", country: str = "US", score: float = 0.42):
        self.payload = payload
        self.rate_code = rate_code
        self.country = country
        self.score = score


# ── _description_from_payload ────────────────────────────────────────────


def test_description_from_payload_concatenates_known_fields():
    desc = _description_from_payload(
        {
            "collection_name": "Stucco work",
            "material_class": "Cement-based",
            "ifc_class": "IfcCovering",
            "category_type": "REPAIR AND CONSTRUCTION WORKS",
            "masterformat_division": "09 24 00",
        }
    )
    assert "Stucco work" in desc
    assert "Cement-based" in desc
    assert "IfcCovering" in desc
    # category_type is title-cased so ALL-CAPS payload doesn't read as shouting
    assert "Repair And Construction Works" in desc
    assert "MasterFormat 09 24 00" in desc


def test_description_from_payload_empty_payload_returns_empty():
    assert _description_from_payload({}) == ""


def test_description_from_payload_partial_payload_uses_available_fields():
    desc = _description_from_payload({"collection_name": "Walls", "category_type": "CONSTRUCTION"})
    assert desc == "Walls — Construction"


def test_description_from_payload_skips_none_and_empty_values():
    desc = _description_from_payload(
        {
            "collection_name": "Walls",
            "material_class": None,
            "ifc_class": "",
            "category_type": "BUILDING",
        }
    )
    assert desc == "Walls — Building"


# ── _hit_to_candidate with empty parquet (typical snapshot install) ──────


def test_hit_to_candidate_falls_back_when_full_row_empty():
    hit = _Hit(
        payload={
            "rate_code": "NEPU_METO_KAKATO_KAPU",
            "country": "US",
            "collection_name": "Stucco work",
            "category_type": "REPAIR AND CONSTRUCTION WORKS",
            "masterformat_division": "09 24 00",
            "ifc_class": "IfcCovering",
            "rate_unit": "100 SF",
            "unit_type": "Area",
        },
        rate_code="NEPU_METO_KAKATO_KAPU",
        country="US",
        score=0.5385,
    )
    cand = _hit_to_candidate(hit, full_row=None)

    # Description was payload-synthesised, not empty
    assert cand.description, "description must not be empty when payload carries metadata"
    assert "Stucco work" in cand.description
    # Unit comes verbatim from payload
    assert cand.unit == "100 SF"
    # Currency derived from country head when parquet missing
    assert cand.currency == "USD"
    # Region preserved
    assert cand.region_code == "US"
    # MasterFormat surfaced into classification dict
    assert cand.classification.get("masterformat") == "09 24 00"
    # Score is the raw RRF score (boosts applied later)
    assert cand.score == pytest.approx(0.5385)


def test_hit_to_candidate_parquet_wins_over_payload():
    hit = _Hit(
        payload={
            "rate_code": "X",
            "country": "DE",
            "category_type": "FALLBACK",
            "rate_unit": "100 SF",
        },
        rate_code="X",
        country="DE",
    )
    full = {
        "description": "Real description from parquet",
        "rate_unit": "m2",
        "unit_cost": 42.5,
        "currency": "EUR",
        "country": "DE",
    }
    cand = _hit_to_candidate(hit, full_row=full)

    assert cand.description == "Real description from parquet"
    assert cand.unit == "m2"
    assert cand.unit_rate == pytest.approx(42.5)
    assert cand.currency == "EUR"


def test_hit_to_candidate_unknown_country_leaves_currency_empty():
    hit = _Hit(payload={"country": "XX"}, country="XX")
    cand = _hit_to_candidate(hit, full_row=None)
    # XX isn't in the default-currency map → empty so the UI can flag the gap
    assert cand.currency == ""


def test_country_default_currency_map_covers_major_markets():
    # Sanity: the markets we ship CWICR snapshots for must all map.
    must_have = ("US", "GB", "DE", "FR", "ES", "BR", "MX", "RU", "CN", "JP", "IN", "AE", "ZA", "AU", "TR", "BG")
    missing = [c for c in must_have if c not in _COUNTRY_DEFAULT_CURRENCY]
    assert not missing, f"missing currency map for: {missing}"


def test_hit_to_candidate_never_fabricates_unit_rate():
    """Rate is the operator's load-bearing number — never invent one."""
    hit = _Hit(payload={"country": "US"}, country="US")
    cand = _hit_to_candidate(hit, full_row=None)
    assert cand.unit_rate == 0.0
