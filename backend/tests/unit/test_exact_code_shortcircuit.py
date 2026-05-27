# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the §4.1.5 ``exact_code`` short-circuit.

When the upstream extractor (today: BoQ adapter, tomorrow: any ingestor
that knows the rate verbatim) populates ``attributes["exact_code"]``,
the matcher must:

1. Forward the code through ``_envelope_from_group`` into
   ``ElementEnvelope.exact_code``.
2. In ``ranker_qdrant.rank()``, detect a non-empty ``envelope.exact_code``
   and call ``lookup_full_rows`` directly — bypassing Qdrant, the
   reranker, the soft-boost stack, and the auto-link gate (an exact
   code is unconditionally auto-linked when auto-link is on).
3. Fall through cleanly when the code isn't in the catalogue (stale
   code, wrong catalogue, typo) — the caller still gets a result via
   the normal vector path.

These tests pin the wiring so a refactor of the envelope / ranker
can't silently regress the short-circuit. The hot integration path
(actual Qdrant + parquet lookup) is covered separately by the smoke
endpoint at ``/api/v1/costs/qdrant-search/``.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.core.match_service.envelope import (
    ElementEnvelope,
    MatchCandidate,
    MatchRequest,
)
from app.core.match_service.ranker_qdrant import (
    _EXACT_CODE_TIER_SENTINEL,
    _build_exact_candidate,
    _try_exact_code_short_circuit,
)
from app.modules.match_elements.service import _envelope_from_group

# ── ElementEnvelope carries the field ─────────────────────────────────────


def test_envelope_accepts_exact_code_field() -> None:
    """Smoke: the field must exist with the right shape, default None."""
    env = ElementEnvelope(source="bim", description="Beton C25/30")
    assert env.exact_code is None
    env2 = ElementEnvelope(source="bim", description="Beton", exact_code="FER46-001")
    assert env2.exact_code == "FER46-001"


# ── _envelope_from_group forwards exact_code from attributes ──────────────


def _fake_source_element(attributes: dict, category: str = "IfcWall"):
    """Duck-typed SourceElement — only ``category`` and ``attributes``
    are read by ``_envelope_from_group``."""
    return SimpleNamespace(category=category, attributes=attributes)


def test_envelope_from_group_extracts_exact_code_from_boq_attributes() -> None:
    """A BoQ adapter sets ``attributes["exact_code"]`` (boq_adapter.py:279).
    The envelope builder must forward it verbatim."""
    elements = [
        _fake_source_element(
            attributes={
                "type_name": "Concrete C25/30",
                "exact_code": "FER46-01-001",
            },
            category="IfcWall",
        ),
    ]
    env = _envelope_from_group(
        group_key="g1",
        elements=elements,
        quantities={"m3": 12.5},
        source="bim",
    )
    assert env.exact_code == "FER46-01-001"


def test_envelope_from_group_falls_back_to_rate_code_then_code() -> None:
    """The forwarder also accepts ``rate_code`` and ``code`` as aliases —
    BoQ adapters from different vintages used different attribute
    names; we read all three."""
    e1 = _fake_source_element(attributes={"rate_code": "DIN-001"}, category="IfcWall")
    env1 = _envelope_from_group(
        group_key="g",
        elements=[e1],
        quantities={"m3": 1},
        source="bim",
    )
    assert env1.exact_code == "DIN-001"

    e2 = _fake_source_element(attributes={"code": "GAEB-X-42"}, category="IfcWall")
    env2 = _envelope_from_group(
        group_key="g",
        elements=[e2],
        quantities={"m3": 1},
        source="bim",
    )
    assert env2.exact_code == "GAEB-X-42"


def test_envelope_from_group_omits_exact_code_when_absent() -> None:
    """No ``exact_code`` / ``rate_code`` / ``code`` in attributes →
    envelope.exact_code stays None so the short-circuit is skipped."""
    e = _fake_source_element(attributes={"type_name": "Wall"}, category="IfcWall")
    env = _envelope_from_group(
        group_key="g",
        elements=[e],
        quantities={"m2": 5},
        source="bim",
    )
    assert env.exact_code is None


# ── _build_exact_candidate produces the right MatchCandidate shape ────────


def test_build_exact_candidate_pins_score_and_band() -> None:
    """A direct rate_code hit is by definition the best match — score 1.0
    and HIGH band, with ``boosts_applied={"exact_code": 1.0}`` so the UI
    can render "matched by source-supplied code" instead of a similarity %."""
    row = {
        "rate_original_name": "Бетон В25 W6 F150",
        "rate_unit": "м3",
        "rate_total": 5311.86,
        "currency": "RUB",
        "country": "RU",
        "language": "ru",
        "classification_din276": "330.10",
    }
    cand = _build_exact_candidate(rate_code="FER46-001", row=row, catalog_id="RU_MOSCOW")
    assert isinstance(cand, MatchCandidate)
    assert cand.code == "FER46-001"
    assert cand.score == 1.0
    assert cand.vector_score == 1.0
    assert cand.confidence_band == "high"
    assert cand.boosts_applied == {"exact_code": 1.0}
    assert cand.unit == "м3"
    assert cand.unit_rate == pytest.approx(5311.86)
    assert cand.currency == "RUB"
    assert cand.region_code == "RU"
    assert cand.source == "exact_code"
    assert cand.classification == {"din276": "330.10"}


def test_build_exact_candidate_handles_missing_fields_gracefully() -> None:
    """Stale parquet rows may be missing rate_total / rate_unit. The
    helper must not crash — defaults are 0.0 / empty string."""
    cand = _build_exact_candidate(
        rate_code="X",
        row={"rate_original_name": "Generic"},
        catalog_id="DE",
    )
    assert cand.unit_rate == 0.0
    assert cand.unit == ""
    assert cand.currency == ""
    assert cand.description == "Generic"


# ── _try_exact_code_short_circuit happy path + fall-through ──────────────


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _fake_request(envelope: ElementEnvelope) -> MatchRequest:
    """Real MatchRequest — MatchResponse validates ``request`` is the
    actual Pydantic class, not a duck type."""
    return MatchRequest(
        project_id=uuid.uuid4(),
        envelope=envelope,
        top_k=10,
        use_reranker=False,
    )


def test_short_circuit_returns_response_when_code_in_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path — lookup_full_rows returns a row, short-circuit yields
    a single HIGH-band candidate auto-linked at score 1.0."""

    async def fake_lookup(*, country: str, rate_codes: list[str]):
        assert country == "RU_MOSCOW"
        assert rate_codes == ["FER46-001"]
        return [
            {
                "rate_code": "FER46-001",
                "rate_original_name": "Бетон В25",
                "rate_unit": "м3",
                "rate_total": 5311.86,
                "currency": "RUB",
                "country": "RU",
            }
        ]

    monkeypatch.setattr(
        "app.core.match_service.ranker_qdrant.lookup_full_rows",
        fake_lookup,
    )
    # Stub _write_search_log so the test doesn't need a real DB session.
    written: list[dict] = []

    async def fake_write_log(**kwargs):
        written.append(kwargs)

    monkeypatch.setattr(
        "app.core.match_service.ranker_qdrant._write_search_log",
        fake_write_log,
    )

    env = ElementEnvelope(
        source="bim",
        description="Бетон C25/30",
        exact_code="FER46-001",
    )
    req = _fake_request(env)

    resp = _run(
        _try_exact_code_short_circuit(
            envelope=env,
            req=req,
            catalog_id="RU_MOSCOW",
            catalog_count=100,
            catalog_vec=100,
            cost_usd=0.0,
            started=0.0,
        )
    )
    assert resp is not None
    assert resp.status == "ok"
    assert len(resp.candidates) == 1
    assert resp.candidates[0].code == "FER46-001"
    assert resp.candidates[0].score == 1.0
    assert resp.candidates[0].confidence_band == "high"
    assert resp.auto_linked is not None
    assert resp.auto_linked.code == "FER46-001"
    # Search log row was written with the exact_code sentinel.
    assert len(written) == 1
    assert written[0]["status"] == "exact_code"
    assert written[0]["tier_used"] == _EXACT_CODE_TIER_SENTINEL
    assert written[0]["bge_used"] is False
    assert written[0]["llm_used"] is False


def test_short_circuit_returns_none_when_code_missing_from_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When lookup_full_rows returns []: caller falls back to the normal
    vector path. No log row written here — the fall-through path will
    log on its own."""

    async def fake_lookup(*, country: str, rate_codes: list[str]):
        return []

    monkeypatch.setattr(
        "app.core.match_service.ranker_qdrant.lookup_full_rows",
        fake_lookup,
    )

    env = ElementEnvelope(source="bim", description="Stale", exact_code="STALE-X")
    resp = _run(
        _try_exact_code_short_circuit(
            envelope=env,
            req=_fake_request(env),
            catalog_id="DE_BERLIN",
            catalog_count=10,
            catalog_vec=10,
            cost_usd=0.0,
            started=0.0,
        )
    )
    assert resp is None


def test_short_circuit_returns_none_for_empty_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive: empty exact_code OR empty catalog_id → None without I/O."""
    called = {"n": 0}

    async def fake_lookup(*, country: str, rate_codes: list[str]):
        called["n"] += 1
        return []

    monkeypatch.setattr(
        "app.core.match_service.ranker_qdrant.lookup_full_rows",
        fake_lookup,
    )

    env_empty = ElementEnvelope(source="bim", description="x", exact_code="")
    resp = _run(
        _try_exact_code_short_circuit(
            envelope=env_empty,
            req=_fake_request(env_empty),
            catalog_id="DE",
            catalog_count=0,
            catalog_vec=0,
            cost_usd=0.0,
            started=0.0,
        )
    )
    assert resp is None

    env_with = ElementEnvelope(source="bim", description="x", exact_code="X")
    resp2 = _run(
        _try_exact_code_short_circuit(
            envelope=env_with,
            req=_fake_request(env_with),
            catalog_id=None,
            catalog_count=0,
            catalog_vec=0,
            cost_usd=0.0,
            started=0.0,
        )
    )
    assert resp2 is None
    # Neither call reached the parquet lookup.
    assert called["n"] == 0


def test_short_circuit_swallows_lookup_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parquet root missing on the deploy — the helper must fall through
    with None rather than 500-ing the whole match request."""

    async def boom(**_):
        raise RuntimeError("parquet root not configured")

    monkeypatch.setattr(
        "app.core.match_service.ranker_qdrant.lookup_full_rows",
        boom,
    )
    env = ElementEnvelope(source="bim", description="x", exact_code="ANY")
    resp = _run(
        _try_exact_code_short_circuit(
            envelope=env,
            req=_fake_request(env),
            catalog_id="DE",
            catalog_count=0,
            catalog_vec=0,
            cost_usd=0.0,
            started=0.0,
        )
    )
    assert resp is None
