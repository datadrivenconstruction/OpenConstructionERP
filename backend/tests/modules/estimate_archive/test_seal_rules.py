# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Immutability, policy, validation rules, receipts and the timestamp request, without a database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import make_transient_to_detached

from app.core.validation.engine import validation_engine
from app.dependencies import get_current_user_id
from app.modules.estimate_archive import engine, fixtures, policy, tsa
from app.modules.estimate_archive.models import EstimateSeal, SealImmutableError, _refuse_content_change
from app.modules.estimate_archive.router import router
from app.modules.estimate_archive.service import receipt_status
from app.modules.estimate_archive.validators import (
    OPENING_RULE_SET,
    PRICING_RULE_SET,
    SEAL_RULE_SET,
    register_estimate_archive_rules,
)


def _persisted_seal() -> EstimateSeal:
    payload = fixtures.example_de_trench()
    seal = EstimateSeal(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        label="Water main - sealed",
        schema_version=engine.SCHEMA,
        payload=payload,
        content_hash=engine.seal_digest(payload),
        sealed_at=datetime.now(UTC),
        award_total=Decimal("1000.00"),
        currency="EUR",
        basis_kind="award",
        status="sealed",
        deposit_mode="platform",
        supersede_reason="",
        profile="de",
        metadata_={},
    )
    make_transient_to_detached(seal)
    return seal


def test_changing_sealed_content_is_refused() -> None:
    seal = _persisted_seal()
    seal.award_total = Decimal("999.00")
    with pytest.raises(SealImmutableError, match="award_total"):
        _refuse_content_change(None, None, seal)


def test_status_and_verification_moves_are_allowed() -> None:
    seal = _persisted_seal()
    seal.status = "opening_requested"
    seal.last_verified_ok = True
    _refuse_content_change(None, None, seal)


def test_every_mutating_verb_on_a_seal_answers_409() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/estimate-archive")
    app.dependency_overrides[get_current_user_id] = lambda: str(uuid.uuid4())
    client = TestClient(app)
    url = f"/api/v1/estimate-archive/seals/{uuid.uuid4()}"
    for verb in ("patch", "put", "delete"):
        resp = getattr(client, verb)(url)
        assert resp.status_code == 409, verb
        assert resp.json()["detail"]["code"] == "ARC_MUTATION_REFUSED"


@pytest.mark.parametrize(
    ("country", "form", "expected"),
    [
        ("DE", "", "de"),
        ("GB", "", "uk"),
        ("AE", "", "fidic"),
        ("US", "", "us"),
        ("FR", "", "neutral"),
        ("FR", "fidic red book 2017", "fidic"),
        ("DE", "jct sbc/q 2016", "uk"),
        (None, "", "neutral"),
    ],
)
def test_profile_follows_country_then_contract_form(country: str | None, form: str, expected: str) -> None:
    assert policy.resolve_profile_id(country, form) == expected


def test_neutral_profile_hides_the_feature_and_markets_enable_it() -> None:
    assert policy.policy_for("neutral")["enabled"] is False
    for pid in ("de", "uk", "fidic", "us"):
        assert policy.policy_for(pid)["enabled"] is True


def test_contract_form_reads_metadata_terms_then_template() -> None:
    contract = SimpleNamespace(metadata_={}, terms={"standard_form": "FIDIC Red 2017"}, template_code="x")
    assert policy.contract_form(contract) == "fidic red 2017"
    assert policy.contract_form(SimpleNamespace(metadata_={}, terms={}, template_code="JCT_SBC")) == "jct_sbc"
    assert policy.contract_form(None) == ""


def test_receipt_status_prefers_the_strongest_receipt() -> None:
    rows = [SimpleNamespace(status="requested"), SimpleNamespace(status="external")]
    assert receipt_status(rows) == "external"
    assert receipt_status([]) == "none"
    assert receipt_status([*rows, SimpleNamespace(status="signed")]) == "signed"


def test_timestamp_request_is_der_with_the_digest() -> None:
    digest = "ab" * 32
    req = tsa.build_request(digest, nonce=12345)
    assert req[0] == 0x30
    assert req[1] == len(req) - 2
    assert bytes.fromhex(digest) in req
    assert bytes.fromhex("0609608648016503040201") in req
    assert req.endswith(b"\x01\x01\xff")


async def _codes(rule_set: str, data: dict, locale: str = "en") -> dict[str, str]:
    register_estimate_archive_rules()
    report = await validation_engine.validate(
        data=data, rule_sets=[rule_set], target_type="t", target_id="x", metadata={"locale": locale}
    )
    return {
        str((r.details or {}).get("code")): r.message for r in report.results if not r.passed and not r.is_engine_error
    }


async def test_tampered_payload_is_reported_as_hash_mismatch() -> None:
    payload = fixtures.example_de_trench()
    sealed = engine.seal_digest(payload)
    payload["positions"][1]["unit_rate"] = "37.00"
    codes = await _codes(
        SEAL_RULE_SET,
        {
            "content_hash": sealed,
            "recomputed_hash": engine.seal_digest(payload),
            "markup_count": 3,
            "receipt_status": "signed",
        },
    )
    assert "ARC_HASH_MISMATCH" in codes
    assert sealed[:8] in codes["ARC_HASH_MISMATCH"]


async def test_total_mismatch_and_missing_breakdown_are_reported() -> None:
    codes = await _codes(
        SEAL_RULE_SET,
        {
            "seal_total": "45200.00",
            "award_value": "45250.00",
            "currency": "EUR",
            "positions_without_breakdown": 2,
            "markup_count": 3,
            "receipt_status": "none",
        },
    )
    assert {"ARC_TOTAL_MISMATCH", "ARC_NO_BREAKDOWN", "ARC_NO_RECEIPT"} <= set(codes)


async def test_one_party_opening_is_flagged_where_both_parties_are_required() -> None:
    data = {
        "reason": "variation",
        "reference_label": "N-07",
        "require_both_parties": True,
        "attendees": [{"name": "A", "side": "internal"}],
    }
    assert "ARC_OPEN_ONE_PARTY" in await _codes(OPENING_RULE_SET, data)
    data["attendees"].append({"name": "B", "side": "counterparty"})
    assert "ARC_OPEN_ONE_PARTY" not in await _codes(OPENING_RULE_SET, data)
    assert "ARC_OPEN_NO_REASON" in await _codes(OPENING_RULE_SET, {"reason": "variation"})


async def test_unexplained_deviation_from_the_seal_is_named_in_german() -> None:
    payload = fixtures.example_uk_trench()
    result = engine.derive_rate(payload, "D20.1", quantity="180", changes=[{"code": "LAB", "consumption": "0.42"}])
    data = {
        "has_seal": True,
        "basis_method": "original_basis",
        "code": "D20.1",
        "deviations": engine.deviations(result),
        "unevidenced": [],
        "sealed_markups": [],
        "claimed_markups": [],
    }
    codes = await _codes(PRICING_RULE_SET, data, locale="de")
    assert "VAR_BASIS_DEVIATION" in codes
    assert "D20.1" in codes["VAR_BASIS_DEVIATION"]
    assert "Vermerk" in codes["VAR_BASIS_DEVIATION"]


async def test_original_basis_without_a_seal_is_flagged() -> None:
    codes = await _codes(PRICING_RULE_SET, {"has_seal": False, "basis_method": "original_basis", "code": "4.07"})
    assert "VAR_BASIS_NO_SEAL" in codes


def test_every_demo_plan_prices_its_change_from_its_own_seal() -> None:
    from app.modules.estimate_archive.seed import _PLAN, demo_change

    for demo_id, (build, profile, _ref, people) in _PLAN.items():
        payload = build()
        picked = demo_change(payload)
        assert picked is not None, demo_id
        result = engine.derive_rate(payload, picked[0], **picked[1])
        assert {m["method"] for m in result["methods"]} >= {"original_basis"}, demo_id
        assert policy.policy_for(profile)["enabled"], demo_id
        assert {p[3] for p in people} == {"internal", "counterparty"}, demo_id
