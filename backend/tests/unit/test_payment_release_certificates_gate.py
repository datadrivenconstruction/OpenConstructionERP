# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rule V19: a payment waits for the certificate the law makes a condition of paying.

Egypt suspends each interim and the final payment on a construction contract
until the contractor shows a social insurance clearance (MoSS Decree
152/2019, Art. 206(3)). The pack lists the requirement and opts it into the
payment release gate; the contract's payment terms may block, warn or switch
the gate off. These tests hold each answer: a missing, expired, revoked or
not-yet-issued certificate is reported, a valid one is not, ``block`` makes
the finding an error (which stops the release), and an invoice already
released or of a kind the requirement does not cover is never reported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.payment_release.release_certificates import (
    effective_severity,
    gated_requirements,
    normalise_enforcement,
)
from app.modules.payment_release.validators import PAYLOAD_KEY, ReleaseCertificatesRule

_MESSAGES = Path(__file__).resolve().parents[2] / "app/core/validation/messages"
_REQUIREMENT = {
    "code": "social_insurance_clearance",
    "cert_type": "social_security_clearance",
    "release_effect": "warn",
    "applies_to_kinds": ["interim", "final"],
    "statute_reference": "MoSS Decree 152/2019, Art. 206(3)",
    "needs_expert_review": True,
}


def _cert(**kw: Any) -> dict[str, Any]:
    base = {
        "cert_type": "social_security_clearance",
        "issue_date": "2026-09-01",
        "valid_until": "2026-12-31",
        "status": "valid",
        "revoked": False,
    }
    base.update(kw)
    return base


def _ctx(
    certificates: list[dict[str, Any]],
    *,
    enforcement: str = "pack",
    invoices: list[dict[str, Any]] | None = None,
    as_of: str = "2026-10-19",
    locale: str = "en",
) -> ValidationContext:
    contract = {
        "id": "c1",
        "code": "SC-01",
        "invoices": invoices
        if invoices is not None
        else [{"id": "i1", "number": "IPC-3", "kind": "interim", "released": False}],
        "release_certificates": {
            "enforcement": enforcement,
            "requirements": [_REQUIREMENT],
            "certificates": certificates,
        },
    }
    return ValidationContext(
        data={PAYLOAD_KEY: {"currency": "EGP", "as_of": as_of, "contracts": [contract]}},
        metadata={"locale": locale},
    )


@pytest.mark.asyncio
async def _fails(context: ValidationContext) -> list:
    return [r for r in await ReleaseCertificatesRule().validate(context) if not r.passed]


@pytest.mark.asyncio
async def test_a_valid_clearance_lets_the_payment_through() -> None:
    assert await _fails(_ctx([_cert()])) == []


@pytest.mark.parametrize(
    "certificates",
    [
        [],
        [_cert(valid_until="2026-10-18")],
        [_cert(revoked=True)],
        [_cert(status="revoked")],
        [_cert(issue_date="2026-10-20")],
        [_cert(cert_type="insurance")],
    ],
    ids=["none", "expired_the_day_before", "revoked_flag", "revoked_status", "issued_after_release", "other_type"],
)
@pytest.mark.asyncio
async def test_without_a_clearance_valid_on_the_release_date_the_payment_is_held(certificates: list) -> None:
    (found,) = await _fails(_ctx(certificates))
    assert found.element_ref == "i1"
    # The Egyptian pack ships the gate as a warning until an expert confirms the decree is in force.
    assert found.severity == Severity.WARNING
    assert found.details["certificate"] == "social insurance clearance certificate"
    assert "IPC-3" in found.message and "2026-10-19" in found.message
    assert "Decree 152/2019" in found.message


@pytest.mark.asyncio
async def test_a_clearance_valid_until_the_release_day_still_counts() -> None:
    assert await _fails(_ctx([_cert(valid_until="2026-10-19")])) == []


@pytest.mark.asyncio
async def test_a_contract_set_to_block_makes_the_finding_an_error() -> None:
    (found,) = await _fails(_ctx([], enforcement="block"))
    assert found.severity == Severity.ERROR


@pytest.mark.asyncio
async def test_a_contract_set_to_off_is_silent() -> None:
    assert await _fails(_ctx([], enforcement="off")) == []


@pytest.mark.asyncio
async def test_released_invoices_and_uncovered_kinds_are_not_reported() -> None:
    invoices = [
        {"id": "paid", "number": "IPC-1", "kind": "interim", "released": True},
        {"id": "dw", "number": "DW-1", "kind": "daywork", "released": False},
        {"id": "cn", "number": "CN-1", "kind": "credit_note", "released": False},
        {"id": "fin", "number": "FIN", "kind": "final", "released": False},
    ]
    found = await _fails(_ctx([], invoices=invoices))
    assert [r.element_ref for r in found] == ["fin"]


@pytest.mark.asyncio
async def test_without_a_release_date_or_a_gate_the_rule_says_nothing() -> None:
    context = _ctx([])
    del context.data[PAYLOAD_KEY]["as_of"]
    assert await _fails(context) == []
    context = _ctx([])
    del context.data[PAYLOAD_KEY]["contracts"][0]["release_certificates"]
    assert await _fails(context) == []


@pytest.mark.asyncio
async def test_the_message_is_translated() -> None:
    (found,) = await _fails(_ctx([], locale="de"))
    assert "IPC-3" in found.message
    assert "social insurance clearance" not in found.message


# ── The pieces the rule is built from ────────────────────────────────────────


def test_enforcement_follows_the_contract_then_the_pack() -> None:
    assert effective_severity(_REQUIREMENT, "pack") == "warning"
    assert effective_severity({**_REQUIREMENT, "release_effect": "block"}, "pack") == "error"
    assert effective_severity(_REQUIREMENT, "block") == "error"
    assert effective_severity({**_REQUIREMENT, "release_effect": "block"}, "warn") == "warning"
    assert effective_severity(_REQUIREMENT, "off") is None
    assert normalise_enforcement("BLOCK") == "block"
    assert normalise_enforcement("whatever") == "pack"
    assert normalise_enforcement(None) == "pack"


def test_only_a_requirement_that_opts_in_is_gated() -> None:
    billing = {
        "sub_payment_requirements": {
            "requirements": [
                {"code": "a", "evidence": "certificate", "cert_type": "insurance"},
                {"code": "b", "evidence": "document", "cert_type": "x", "gates": ["payment_release"]},
                {"code": "c", "evidence": "certificate", "cert_type": "license", "gates": ["payment_release"]},
            ]
        }
    }
    (gated,) = gated_requirements(billing)
    assert gated["cert_type"] == "license"
    assert gated["release_effect"] == "warn"
    assert gated["applies_to_kinds"] == ["interim", "final"]
    assert gated_requirements(None) == []


def test_every_bundle_carries_the_new_keys_with_their_placeholders() -> None:
    en = json.loads((_MESSAGES / "en.json").read_text(encoding="utf-8"))["payment_release_certificate_types"]
    for path in sorted(_MESSAGES.glob("*.json")):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        labels = bundle["payment_release_certificate_types"]
        assert set(labels) == set(en), path.name
        assert all(label.strip() for label in labels.values()), path.name
        for placeholder in ("{number}", "{contract}", "{certificate}", "{on}", "{reference}"):
            assert placeholder in bundle["payment_release"]["certificate_missing"]["fail"], (path.name, placeholder)
