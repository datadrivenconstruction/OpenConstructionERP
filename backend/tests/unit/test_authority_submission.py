# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure engine tests for the authority-submission factory.

Pins the three jurisdiction-neutral engine functions with no DB and no clock:

- validate_payload: the clean path, missing required fields, type mismatches and
  nested (array-of-objects) required checks, plus the shared quality score.
- build_submission_xml: deterministic byte-stable output (independent of payload
  dict order), correct escaping of hostile input, boolean coercion, arrays and
  the ``schemaVersion`` / ``format`` root attributes.
- render_payload: the human-readable single source next to the XML.
- intl labels: localised with an English fallback, never a raw code.
"""

from __future__ import annotations

from app.modules.authority_submission import intl
from app.modules.authority_submission.profiles import BUILTIN_PROFILES
from app.modules.authority_submission.service import (
    build_submission_xml,
    render_payload,
    validate_payload,
)

# A small spec exercising scalars, a required field and an array of objects.
_SPEC = [
    {"name": "project_name", "type": "string", "required": True, "xml_tag": "ProjectName"},
    {"name": "currency", "type": "string", "required": True, "xml_tag": "Currency"},
    {"name": "count", "type": "integer", "required": False, "xml_tag": "Count"},
    {"name": "approved", "type": "boolean", "required": False, "xml_tag": "Approved"},
    {
        "name": "positions",
        "type": "array",
        "required": True,
        "xml_tag": "Positions",
        "item_tag": "Position",
        "fields": [
            {"name": "ordinal", "type": "string", "required": True, "xml_tag": "Ordinal"},
            {"name": "quantity", "type": "number", "required": True, "xml_tag": "Quantity"},
        ],
    },
]


def _clean_payload() -> dict:
    return {
        "project_name": "Bridge 7",
        "currency": "EUR",
        "count": 3,
        "approved": True,
        "positions": [
            {"ordinal": "01.01", "quantity": 12.5},
            {"ordinal": "01.02", "quantity": 4.0},
        ],
    }


# ── validate_payload ────────────────────────────────────────────────────────


def test_validate_clean_payload_passes() -> None:
    report = validate_payload(_clean_payload(), _SPEC)
    assert report["status"] == "passed"
    assert report["errors"] == 0
    assert report["score"] == 1.0
    assert report["missing_required"] == []


def test_validate_missing_required_fields() -> None:
    payload = {"count": 2, "positions": [{"ordinal": "01", "quantity": 1.0}]}
    report = validate_payload(payload, _SPEC)
    assert report["status"] == "errors"
    assert "project_name" in report["missing_required"]
    assert "currency" in report["missing_required"]
    assert report["score"] < 1.0


def test_validate_type_mismatch() -> None:
    payload = _clean_payload()
    payload["count"] = "not-a-number"
    report = validate_payload(payload, _SPEC)
    assert report["status"] == "errors"
    mismatched = {m["field"] for m in report["type_mismatches"]}
    assert "count" in mismatched


def test_validate_bool_is_not_a_number() -> None:
    # bool is an int in Python; an integer field must reject it.
    payload = _clean_payload()
    payload["count"] = True
    report = validate_payload(payload, _SPEC)
    assert report["status"] == "errors"
    assert any(m["field"] == "count" for m in report["type_mismatches"])


def test_validate_nested_required_missing() -> None:
    payload = _clean_payload()
    payload["positions"] = [{"ordinal": "01.01"}]  # missing quantity
    report = validate_payload(payload, _SPEC)
    assert report["status"] == "errors"
    assert any("positions[0].quantity" in f for f in report["missing_required"])


def test_validate_empty_spec_is_vacuously_clean() -> None:
    report = validate_payload({"anything": 1}, [])
    assert report["status"] == "passed"
    assert report["score"] == 1.0


# ── build_submission_xml ────────────────────────────────────────────────────


def test_xml_is_deterministic_regardless_of_payload_order() -> None:
    p1 = _clean_payload()
    p2 = {
        "positions": p1["positions"],
        "approved": p1["approved"],
        "currency": p1["currency"],
        "count": p1["count"],
        "project_name": p1["project_name"],
    }
    xml1 = build_submission_xml("TenderExchange", _SPEC, p1, schema_version="3.3", format_key="gaeb_x83")
    xml2 = build_submission_xml("TenderExchange", _SPEC, p2, schema_version="3.3", format_key="gaeb_x83")
    assert xml1 == xml2
    # And repeated builds are byte-identical.
    assert xml1 == build_submission_xml("TenderExchange", _SPEC, p1, schema_version="3.3", format_key="gaeb_x83")


def test_xml_structure_and_attributes() -> None:
    xml = build_submission_xml("TenderExchange", _SPEC, _clean_payload(), schema_version="3.3", format_key="gaeb_x83")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    assert '<TenderExchange schemaVersion="3.3" format="gaeb_x83">' in xml
    assert "<ProjectName>Bridge 7</ProjectName>" in xml
    assert "<Positions><Position>" in xml
    assert "<Ordinal>01.01</Ordinal>" in xml
    # Field-spec order fixes element order: ProjectName precedes Currency.
    assert xml.index("<ProjectName>") < xml.index("<Currency>")


def test_xml_escapes_hostile_input() -> None:
    payload = {
        "project_name": "<script>alert('x')</script> & \"co\"",
        "currency": "EUR",
        "positions": [{"ordinal": "01", "quantity": 1.0}],
    }
    xml = build_submission_xml("TenderExchange", _SPEC, payload)
    assert "<script>" not in xml
    assert "&lt;script&gt;" in xml
    assert "&amp;" in xml


def test_xml_boolean_coercion() -> None:
    xml = build_submission_xml("TenderExchange", _SPEC, _clean_payload())
    assert "<Approved>true</Approved>" in xml


def test_xml_omits_absent_optional_fields() -> None:
    payload = {
        "project_name": "P",
        "currency": "EUR",
        "positions": [{"ordinal": "01", "quantity": 1.0}],
    }
    xml = build_submission_xml("TenderExchange", _SPEC, payload)
    assert "<Count>" not in xml
    assert "<Approved>" not in xml


# ── render_payload ──────────────────────────────────────────────────────────


def test_render_produces_readable_rows_and_text() -> None:
    rendered = render_payload(_SPEC, _clean_payload(), title="Tender 7", root_element="TenderExchange")
    assert rendered["title"] == "Tender 7"
    labels = {row["label"] for row in rendered["fields"]}
    assert "Project Name" in labels
    assert "Bridge 7" in rendered["text"]
    assert "Approved: Yes" in rendered["text"]


# ── builtin profiles ────────────────────────────────────────────────────────


def test_builtin_profiles_are_jurisdiction_neutral() -> None:
    # The three original engine profiles must remain jurisdiction-neutral.
    # Regional profiles (Bauantrag DE, etc.) added via OC-19 carry a
    # jurisdiction deliberately and are not tested here.
    neutral = [p for p in BUILTIN_PROFILES if p["jurisdiction"] is None]
    assert len(neutral) >= 3
    keys = {p["format_key"] for p in neutral}
    assert {"generic_xml", "gaeb_x83", "cobie"} <= keys


def test_builtin_gaeb_profile_generates_valid_xml() -> None:
    gaeb = next(p for p in BUILTIN_PROFILES if p["format_key"] == "gaeb_x83")
    payload = {
        "project_name": "Demo",
        "currency": "EUR",
        "positions": [{"ordinal": "1", "description": "Concrete", "unit": "m3", "quantity": 10, "unit_rate": 120}],
    }
    report = validate_payload(payload, gaeb["field_spec"])
    assert report["status"] == "passed"
    xml = build_submission_xml(
        gaeb["root_element"],
        gaeb["field_spec"],
        payload,
        schema_version=gaeb["schema_version"],
        format_key=gaeb["format_key"],
    )
    assert "<TenderExchange" in xml
    assert "<Description>Concrete</Description>" in xml


# ── intl labels ─────────────────────────────────────────────────────────────


def test_format_labels_localise() -> None:
    assert intl.describe_format("gaeb_x83", "en") == "Tender exchange (GAEB X83)"
    assert intl.describe_format("cobie", "de") == "Anlagenübergabe (COBie)"


def test_status_labels_localise() -> None:
    assert intl.describe_status("submitted", "ru") == "Подан"
    assert intl.describe_status("rejected", "es") == "Rechazado"


def test_unknown_locale_and_code_fall_back() -> None:
    assert intl.describe_format("generic_xml", "zz") == "Generic XML document"
    assert intl.describe_status("some_new_state", "en") == "Some New State"
