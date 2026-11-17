# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontract documents and the required-documents rule.

The default list asks for signed terms and conditions and a safety plan. A
role passes on one valid file, so a renewal works; a file expiring on the
as-of date is still valid on it. The rule warns, and an installation that sets
enforcement to ``block`` turns the same findings into errors, which refuse
activation and approval.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.validation.engine import rule_registry, validation_engine
from app.core.validation.rules import register_builtin_rules
from app.modules.subcontractors import validators as checks
from app.modules.subcontractors.progress_service import ProgressBillingMixin
from app.modules.subcontractors.schemas import DocumentPolicy

TODAY = date(2026, 11, 17)
DEFAULT = [dict(d) for d in checks.DEFAULT_REQUIRED_DOCUMENTS]


def _doc(role: str, *, signed: str | None = None, until: str | None = None) -> dict:
    return {"role": role, "title": role, "signed_date": signed, "valid_until": until}


def _payload(documents: list[dict], required: list[dict] | None = None, enforcement: str = "warn") -> dict:
    return {
        "id": "agr-1",
        "title": "Concrete works",
        "as_of": TODAY.isoformat(),
        "required_documents": DEFAULT if required is None else required,
        "enforcement": enforcement,
        "documents": documents,
    }


def test_default_list_is_signed_terms_and_a_safety_plan() -> None:
    assert DEFAULT == [{"role": "terms_and_conditions", "signed": True}, {"role": "safety_plan", "signed": False}]


def test_nothing_on_file_misses_both() -> None:
    states = {f.details["role"]: f.details["state"] for f in checks.check_required_documents(_payload([]))}
    assert states == {"terms_and_conditions": "missing", "safety_plan": "missing"}


def test_unsigned_terms_do_not_count_but_an_unsigned_safety_plan_does() -> None:
    docs = [_doc("terms_and_conditions"), _doc("safety_plan")]
    [finding] = checks.check_required_documents(_payload(docs))
    assert finding.details == {"role": "terms_and_conditions", "state": "unsigned"}


def test_expiry_boundary_is_inclusive_and_a_renewal_passes() -> None:
    signed = "2026-01-05"
    on_the_day = [_doc("terms_and_conditions", signed=signed), _doc("safety_plan", until="2026-11-17")]
    assert checks.check_required_documents(_payload(on_the_day)) == []
    lapsed = [_doc("terms_and_conditions", signed=signed), _doc("safety_plan", until="2026-11-16")]
    [finding] = checks.check_required_documents(_payload(lapsed))
    assert finding.details == {"role": "safety_plan", "state": "expired"}
    renewed = [*lapsed, _doc("safety_plan", until="2027-06-30")]
    assert checks.check_required_documents(_payload(renewed)) == []


def test_a_free_role_can_be_required_and_an_empty_list_requires_nothing() -> None:
    required = [{"role": "osha_safety_program", "signed": False}]
    [finding] = checks.check_required_documents(_payload([], required))
    assert finding.details["role"] == "osha_safety_program"
    assert checks.check_required_documents(_payload([], [])) == []


async def _run(payload: dict, locale: str = "en"):
    register_builtin_rules()
    assert "subcontract.required_documents" in {r.rule_id for r in rule_registry.get_rules_for_sets(["subcontract"])}
    return await validation_engine.validate(
        data=payload,
        rule_sets=["subcontract_pay_app"],
        target_type="subcontract_agreement",
        target_id="agr-1",
        metadata={"locale": locale},
    )


@pytest.mark.asyncio
async def test_a_gap_warns_by_default_and_blocks_when_the_policy_says_so() -> None:
    warn = await _run(_payload([]))
    gaps = [r for r in warn.results if r.rule_id == "subcontract.required_documents" and not r.passed]
    assert {r.severity.value for r in gaps} == {"warning"}
    assert "Terms and conditions" in gaps[0].message and "missing" in gaps[0].message
    block = await _run(_payload([], enforcement="block"))
    assert {r.severity.value for r in block.results if r.rule_id == "subcontract.required_documents"} == {"error"}


@pytest.mark.asyncio
async def test_the_message_is_in_the_requested_language() -> None:
    report = await _run(_payload([]), locale="de")
    message = next(r.message for r in report.results if r.rule_id == "subcontract.required_documents")
    assert message.startswith("Erforderliches Dokument") and "Vertragsbedingungen" in message


@pytest.mark.asyncio
async def test_a_complete_file_passes_with_one_green_row() -> None:
    docs = [_doc("terms_and_conditions", signed="2026-01-05"), _doc("safety_plan")]
    report = await _run(_payload(docs))
    rows = [r for r in report.results if r.rule_id == "subcontract.required_documents"]
    assert [r.passed for r in rows] == [True]


class _Policy:
    def __init__(self, row: object | None) -> None:
        self.row = row

    async def get_installation(self) -> object | None:
        return self.row


class _Docs:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    async def list_for_agreement(self, _agreement_id: object) -> list[object]:
        return self.rows


def _service(enforcement: str | None, docs: list[object]) -> ProgressBillingMixin:
    from types import SimpleNamespace

    svc = ProgressBillingMixin()
    row = None if enforcement is None else SimpleNamespace(required=DEFAULT, enforcement=enforcement)
    svc.document_policy_repo = _Policy(row)
    svc.agreement_documents = _Docs(docs)
    return svc


@pytest.mark.asyncio
async def test_activation_and_approval_are_refused_only_when_the_policy_blocks() -> None:
    from types import SimpleNamespace

    agreement = SimpleNamespace(id="agr-1", title="Concrete works")
    await _service(None, []).enforce_required_documents(agreement, operation="activate")
    await _service("warn", []).enforce_required_documents(agreement, operation="activate")
    with pytest.raises(HTTPException) as refused:
        await _service("block", []).enforce_required_documents(agreement, operation="approve_payment", today=TODAY)
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "required_documents_missing"
    assert {g["role"] for g in refused.value.detail["gaps"]} == {"terms_and_conditions", "safety_plan"}
    held = [
        SimpleNamespace(doc_role="terms_and_conditions", title="T", signed_date=date(2026, 1, 5), valid_until=None),
        SimpleNamespace(doc_role="safety_plan", title="S", signed_date=None, valid_until=date(2027, 1, 1)),
    ]
    await _service("block", held).enforce_required_documents(agreement, operation="activate", today=TODAY)


@pytest.mark.asyncio
async def test_a_policy_cannot_list_a_role_twice() -> None:
    svc = _service(None, [])
    with pytest.raises(HTTPException) as refused:
        await svc.set_document_policy(
            DocumentPolicy(required=[{"role": "safety_plan"}, {"role": "safety_plan", "signed": True}]), "u1"
        )
    assert refused.value.status_code == 422


def test_every_validation_locale_answers_the_new_keys_with_the_same_placeholders() -> None:
    folder = Path(__file__).resolve().parents[2] / "app" / "core" / "validation" / "messages"
    english = json.loads((folder / "en.json").read_text(encoding="utf8"))["subcontract"]
    keys = {
        "pay_app_over_complete": ("fail", "suggestion"),
        "pay_app_line_negative": ("fail",),
        "pay_app_within_agreement": ("fail",),
        "pay_app_correct": ("suggestion",),
        "required_documents": ("fail", "suggestion"),
    }
    files = sorted(folder.glob("*.json"))
    assert len(files) >= 38
    for path in files:
        block = json.loads(path.read_text(encoding="utf8"))["subcontract"]
        for key, leaves in keys.items():
            for leaf in leaves:
                got, want = block[key][leaf], english[key][leaf]
                assert set(re.findall(r"\{(\w+)\}", got)) == set(re.findall(r"\{(\w+)\}", want)), (path.name, key, leaf)
        assert set(block["required_documents"]["states"]) == {"missing", "unsigned", "expired"}, path.name
        assert set(block["document_roles"]) == set(checks.DOCUMENT_ROLES), path.name
