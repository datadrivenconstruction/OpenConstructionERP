# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shipped staffing catalogues, the validator, and the privacy shape of the schema.

Catalogue (SPEC 8.1): every shipped file loads, every role's document kinds
exist, every ``credential_type`` is in the credentials registry, every
retention rule has a source or says ``unconfirmed``, every label key exists in
the English and German message files.

Privacy (SPEC 8.3, section 10, lead decisions 5, 6, 8, 11): no staffing table
has a medical, diagnosis, nationality, birth date, address, full document
number, expiry or person-name column. A field that must stay empty is a leak
waiting to happen, so the test fails if one is added.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.credentials.schemas import CREDENTIAL_TYPES
from app.modules.project_governance.catalogue import ReviewStatus
from app.modules.staffing.catalogue import (
    STAFFING_MODEL_KIND,
    StaffingModelCatalogue,
    register_kinds,
    validate_staffing_model,
)
from app.modules.staffing.models import ALL_MODELS, PersonnelDocument

_MODULE = Path(__file__).resolve().parents[2] / "app" / "modules" / "staffing"


def _shipped():
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    register_kinds()
    return get_catalogue_kind(STAFFING_MODEL_KIND).shipped()


def _messages(locale: str) -> dict[str, str]:
    return json.loads((_MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8"))


def test_four_shipped_catalogues_load_and_validate() -> None:
    shipped = {c.id: c for c in _shipped()}
    assert set(shipped) == {"neutral", "de", "uk", "us"}
    for c in shipped.values():
        assert validate_staffing_model(c, "shipped") == []
    # The role list is shared: the country files differ only in documents and retention.
    assert {r.code for r in shipped["de"].roles} == {r.code for r in shipped["neutral"].roles}
    assert shipped["uk"].jurisdiction_countries == ("GB",)


def test_every_reference_resolves() -> None:
    for c in _shipped():
        kinds = {d.code for d in c.document_kinds}
        rules = {r.code for r in c.retention_rules}
        for role in c.roles:
            assert set(role.required_document_kinds) <= kinds, role.code
        for d in c.document_kinds:
            assert d.credential_type in CREDENTIAL_TYPES, d.code
            assert d.retention_rule in rules, d.code
        for r in c.retention_rules:
            assert r.source_url or r.review_status is ReviewStatus.unconfirmed, r.code


def test_spec_role_list_present() -> None:
    neutral = next(c for c in _shipped() if c.id == "neutral")
    spec = {
        "project_director",
        "project_manager",
        "design_manager",
        "cost_manager",
        "scheduler",
        "contract_manager",
        "document_controller",
        "hse_manager",
        "quality_manager",
        "site_manager",
        "site_supervisor_civil",
        "site_supervisor_mep",
        "commissioning_manager",
        "operator_plant_manager",
        "operator_shift_lead",
        "operator_technician",
        "consultant_legal",
        "consultant_permit",
        "consultant_geotech",
        "consultant_cost",
    }
    assert {r.code for r in neutral.roles} == spec
    health = neutral.document_kind("occupational_health_certificate")
    assert health.special_category and not health.store_number


def test_label_keys_exist_in_en_and_de() -> None:
    en, de = _messages("en"), _messages("de")
    for c in _shipped():
        body = c.model_dump(mode="json")
        keys = [body["name_key"]]
        for group in ("organisations", "roles", "document_kinds", "retention_rules", "leave_types"):
            keys += [item["name_key"] for item in body[group]]
        keys += [r["basis_text_key"] for r in body["retention_rules"]]
        missing = [k for k in keys if k not in en or k not in de]
        assert not missing, missing


def _body(**changes):
    neutral = next(c for c in _shipped() if c.id == "neutral").model_dump(mode="json")
    neutral.update(changes)
    return neutral


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda b: b["document_kinds"][0].update(credential_type="no_such_type"),
            "credential_type_unknown",
        ),
        (lambda b: b["roles"][0].update(required_document_kinds=["nope"]), "role_document_kind_unknown"),
        (lambda b: b["roles"][0].update(organisation="nope"), "role_organisation_unknown"),
        (lambda b: b["roles"][0].update(default_fte="1.5"), "role_fte_invalid"),
        (lambda b: b["roles"][0].update(phases=["maintenance"]), "role_phase_unknown"),
        (
            lambda b: b["retention_rules"][0].update(review_status="verified", source_url=""),
            "retention_without_source",
        ),
        (lambda b: b.update(default_retention_rule="nope"), "default_retention_rule_unknown"),
        (lambda b: b["roles"].append(dict(b["roles"][0])), "duplicate_role"),
    ],
)
def test_validator_rejects(mutate, error) -> None:
    body = _body()
    mutate(body)
    errors = validate_staffing_model(StaffingModelCatalogue.model_validate(body), "tenant")
    assert any(e.startswith(error) for e in errors), errors


def test_tenant_label_without_key_or_text_is_rejected() -> None:
    body = _body()
    body["roles"][0]["name_key"] = ""
    errors = validate_staffing_model(StaffingModelCatalogue.model_validate(body), "tenant")
    assert any(e.startswith("label_missing") for e in errors)


# ── privacy shape ──────────────────────────────────────────────────────────

_FORBIDDEN = (
    "nationality",
    "citizenship",
    "birth",
    "dob",
    "address",
    "religion",
    "diagnosis",
    "medical",
    "condition",
    "illness",
    "reason",
    "passport_number",
    "document_number",
    "identifier",
    "valid_until",
    "expires",
    "display_name",
    "first_name",
    "last_name",
    "full_name",
    "person_name",
    "email",
    "phone",
)


def test_no_staffing_table_has_a_forbidden_column() -> None:
    hits = [
        f"{m.__tablename__}.{col.name}"
        for m in ALL_MODELS
        for col in m.__table__.columns
        if any(word in col.name for word in _FORBIDDEN) and col.name != "nationality_required"
    ]
    assert hits == []


def test_health_record_is_date_and_fit_flag_only() -> None:
    """Rule 11: the document row keeps the fit flag; dates live on the credential; nothing else health-related."""
    cols = {c.name for c in PersonnelDocument.__table__.columns}
    assert "fit_for_role" in cols
    assert cols <= {
        "id",
        "created_at",
        "updated_at",
        "project_id",
        "personnel_file_id",
        "document_kind",
        "credential_id",
        "number_last4",
        "recorded_by",
        "verified_by",
        "verified_at",
        "waived",
        "waiver_rationale",
        "fit_for_role",
    }
    assert PersonnelDocument.__table__.columns["number_last4"].type.length == 4


def test_leave_has_no_reason_and_file_no_nationality_value() -> None:
    from app.modules.staffing.models import LeaveRecord, PersonnelFile

    assert not any("reason" in c.name or "note" in c.name for c in LeaveRecord.__table__.columns)
    file_cols = {c.name for c in PersonnelFile.__table__.columns}
    assert "nationality_required" in file_cols
    assert str(PersonnelFile.__table__.columns["nationality_required"].type) == "BOOLEAN"
