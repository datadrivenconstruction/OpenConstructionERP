# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design management catalogues and drawing numbers, without a database (SPEC rules 5-10, section 2).

Every shipped scheme is loaded through module 1's kind registry, composes a
number, validates it and parses it back into exactly the parts it was built
from. Each field is broken once to show the validator names that field.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.modules.design_management import numbering as nb
from app.modules.design_management.catalogue import (
    CATALOGUE_ROOT,
    NUMBERING_KIND,
    REPORT_KINDS_V1,
    REPORTS_KIND,
    DesignReports,
    DrawingNumbering,
    register_kinds,
    validate_numbering,
    validate_reports,
)
from app.modules.project_governance.catalogue import InvalidCatalogueError, ReviewStatus
from app.modules.project_governance.catalogue_kinds import get_catalogue_kind


@pytest.fixture(scope="module")
def schemes() -> dict[str, DrawingNumbering]:
    register_kinds()
    return {s.id: s for s in get_catalogue_kind(NUMBERING_KIND).shipped()}


@pytest.fixture(scope="module")
def reports() -> DesignReports:
    register_kinds()
    return get_catalogue_kind(REPORTS_KIND).get_shipped("default")


# ── catalogues ──


def test_every_shipped_scheme_is_registered_and_valid(schemes) -> None:
    assert set(schemes) == {
        "iso19650_generic",
        "iso19650_uk_na",
        "us_ncs_sheet",
        "de_planschluessel",
        "simple_sequential",
    }
    for s in schemes.values():
        assert validate_numbering(s, "shipped") == []


def test_unverified_schemes_say_so(schemes) -> None:
    for sid in ("iso19650_uk_na", "us_ncs_sheet", "de_planschluessel"):
        assert schemes[sid].review_status == ReviewStatus.unconfirmed
    for s in schemes.values():
        assert s.review_status == ReviewStatus.unconfirmed or s.source_url


def test_every_code_list_is_unique(schemes) -> None:
    for s in schemes.values():
        for f in s.fields:
            if f.code_list != "free":
                codes = [c.code for c in f.code_list]
                assert len(codes) == len(set(codes)), (s.id, f.code)


def test_reports_catalogue_has_the_v1_kinds_with_valid_spine_keys(reports) -> None:
    assert {k.code for k in reports.report_kinds} == set(REPORT_KINDS_V1)
    assert validate_reports(reports, "shipped") == []
    assert {p.code for p in reports.permit_steps} == {
        "neutral",
        "de_bauantrag",
        "uk_planning_building_regs",
        "us_building_permit",
    }


def test_every_country_rule_has_a_source_or_is_unconfirmed(reports) -> None:
    rules = [r for k in reports.report_kinds for r in k.country_rules]
    assert rules, "the DE independent structural check hint ships per Land"
    for r in rules:
        assert r.source_url or r.review_status == ReviewStatus.unconfirmed
        assert r.review_status == ReviewStatus.unconfirmed


def test_validator_refuses_a_bad_spine_key_and_a_verified_rule_without_source(reports) -> None:
    body = reports.model_dump(mode="json")
    body["report_kinds"][0]["typical_phase"] = "lph5"
    body["report_kinds"][1]["country_rules"] = [{"country": "DE", "review_status": "verified"}]
    errors = validate_reports(DesignReports.model_validate(body), "tenant")
    assert any(e.startswith("typical_phase_unknown") for e in errors)
    assert any(e.startswith("country_rule_without_source") for e in errors)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda b: b["fields"].append(dict(b["fields"][0])), "field_duplicate"),
        (lambda b: b["fields"][-1].update(pad=None), "number_field_without_pad"),
        (lambda b: b["fields"][0].update(pattern="[A-"), "pattern_invalid"),
        (lambda b: b["fields"][0].update(source_field="nowhere"), "source_field_unknown"),
        (lambda b: b.update(number_scope=["number"]), "number_scope_unknown"),
        (lambda b: b.update(metadata_fields=[{"code": "status", "code_list": ["S9"]}]), "status_codes_outside_cde"),
        (lambda b: b.update(separator="_"), "separator_not_allowed"),
    ],
)
def test_scheme_validator_rejects_broken_bodies(schemes, mutate, expected) -> None:
    body = json.loads(schemes["iso19650_generic"].model_dump_json())
    mutate(body)
    errors = validate_numbering(DrawingNumbering.model_validate(body), "tenant")
    assert any(e.startswith(expected) for e in errors), errors


def test_a_glued_field_needs_a_fixed_width(schemes) -> None:
    body = json.loads(schemes["us_ncs_sheet"].model_dump_json())
    body["fields"][1].pop("length_min")
    body["fields"][1].pop("length_max")
    errors = validate_numbering(DrawingNumbering.model_validate(body), "tenant")
    assert any(e.startswith("glued_field_without_length") for e in errors)


def test_kind_parse_raises_on_invalid_body(schemes) -> None:
    body = json.loads(schemes["simple_sequential"].model_dump_json())
    body["fields"] = [f for f in body["fields"] if f["code"] != "number"]
    with pytest.raises(InvalidCatalogueError):
        get_catalogue_kind(NUMBERING_KIND).parse_body(body, source="tenant", origin="t")


async def _first_setup(monkeypatch, country: str | None, pin) -> tuple[object, list[tuple]]:
    """``set_setup`` on a project of ``country`` with the governance port answering ``pin``; no database."""
    from types import SimpleNamespace

    from app.modules.design_management.service import DesignService
    from app.modules.project_governance import public

    asked: list[tuple] = []

    def port(kind, country_code, subdivision_code=None):
        asked.append((kind, country_code))
        return pin if kind == NUMBERING_KIND else None

    async def no_setup(_project_id, **_kw):
        return None

    async def project(_project_id):
        return SimpleNamespace(country_code=country)

    async def pinnable(_tenant, _source, _cid, version, _kind):
        return version or 1

    async def add(row):
        return row

    async def audit(*_a, **_kw):
        return None

    monkeypatch.setattr(public, "default_catalogue_pin", port)
    svc = DesignService.__new__(DesignService)
    for name, fake in (
        ("get_setup", no_setup),
        ("_project", project),
        ("_pinnable", pinnable),
        ("_add", add),
        ("_audit", audit),
        ("_publish", lambda *_a, **_kw: None),
    ):
        monkeypatch.setattr(svc, name, fake, raising=False)
    setup = await svc.set_setup(uuid.uuid4(), actor_id=uuid.uuid4(), tenant_id=None)
    return setup, asked


@pytest.mark.asyncio
async def test_the_governance_port_is_the_only_country_default(monkeypatch) -> None:
    """With the port silent a German project pins the ISO generic scheme: no country rule of this module's own is left."""
    from types import SimpleNamespace

    from app.modules.design_management import catalogue, service
    from app.modules.design_management.catalogue import DEFAULT_REPORTS_ID, DEFAULT_SCHEME_ID, REPORTS_KIND

    silent, asked = await _first_setup(monkeypatch, "DE", None)
    assert (silent.scheme_source, silent.scheme_id) == ("shipped", DEFAULT_SCHEME_ID)
    assert (silent.reports_source, silent.reports_id) == ("shipped", DEFAULT_REPORTS_ID)
    assert asked == [(NUMBERING_KIND, "DE"), (REPORTS_KIND, "DE")], "the port is asked once per kind, with the country"
    named = SimpleNamespace(source="shipped", catalogue_id="de_planschluessel", version=3)
    pinned, _asked = await _first_setup(monkeypatch, "DE", named)
    assert (pinned.scheme_source, pinned.scheme_id, pinned.scheme_version) == ("shipped", "de_planschluessel", 3)
    assert not hasattr(catalogue, "default_scheme_id_for_country")
    assert not hasattr(service, "default_scheme_id_for_country")


def test_shipped_json_is_written_with_keys_not_text() -> None:
    for path in (CATALOGUE_ROOT / NUMBERING_KIND).glob("*.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        for f in raw["fields"]:
            assert f["label_key"].startswith("design.catalogue."), (path.name, f["code"])


# ── compose, validate, parse (rules 5, 6, 7, 10) ──

EXAMPLES = {
    "iso19650_generic": (
        {
            "project": "PRJ1",
            "originator": "ABC",
            "functional": "ZZ",
            "spatial": "01",
            "form": "DR",
            "discipline": "A",
        },
        1,
        "PRJ1-ABC-ZZ-01-DR-A-0001",
    ),
    "iso19650_uk_na": (
        {"project": "PRJ1", "originator": "ABC", "functional": "ZZ", "spatial": "01", "form": "DR", "discipline": "S"},
        12,
        "PRJ1-ABC-ZZ-01-DR-S-0012",
    ),
    "us_ncs_sheet": ({"discipline": "A", "custom_sheet_type": "1"}, 1, "A-101"),
    "de_planschluessel": (
        {"project": "P123", "discipline": "AR", "phase": "lph5", "form": "GR", "spatial": "EG"},
        12,
        "P123-AR-LPH5-GR-EG-0012",
    ),
    "simple_sequential": ({"discipline": "A"}, 12, "A-012"),
}


@pytest.mark.parametrize("scheme_id", sorted(EXAMPLES))
def test_compose_validate_parse_round_trip(schemes, scheme_id) -> None:
    scheme = schemes[scheme_id]
    values, seq, expected = EXAMPLES[scheme_id]
    code = nb.compose(scheme, values, seq)
    assert code == expected
    result = nb.validate(scheme, code)
    assert result.valid, result.issues
    parts = nb.parse(scheme, code)
    assert parts is not None
    assert parts["number"] == nb.format_number(scheme, seq)
    for k, v in values.items():
        assert parts[k] == v.upper()
    assert nb.sequence_of(scheme, code) == seq


@pytest.mark.parametrize("scheme_id", sorted(EXAMPLES))
def test_every_field_broken_once_names_that_field(schemes, scheme_id) -> None:
    scheme = schemes[scheme_id]
    values, seq, _ = EXAMPLES[scheme_id]
    for f in scheme.fields:
        if f.code == "number":
            continue
        bad = dict(values)
        bad[f.code] = "Q" * 9 if f.code_list == "free" else "QQ"
        if f.length_min and f.length_max and f.length_min == f.length_max:
            bad[f.code] = "Q" * f.length_max if f.code_list != "free" else "#"
        code = nb.compose(scheme, bad, seq)
        result = nb.validate(scheme, code)
        assert not result.valid, (scheme_id, f.code, code)
        named = {i.field for i in result.issues}
        assert f.code in named or any(i.code == "numbering_structure_invalid" for i in result.issues), (
            scheme_id,
            f.code,
            result.issues,
        )


def test_issue_codes_for_length_chars_case_and_structure(schemes) -> None:
    s = schemes["iso19650_generic"]
    too_long = nb.validate(s, "PRJ1-ABC-ZZ-01-DR-A-" + "1" * 60)
    assert any(i.code == "numbering_too_long" for i in too_long.issues)
    chars = nb.validate(s, "PRJ1-ABC-ZZ-01-DR-A-00_1")
    assert any(i.code == "numbering_chars_invalid" for i in chars.issues)
    lower = nb.validate(s, "prj1-abc-zz-01-dr-a-0001")
    assert any(i.code == "numbering_case_invalid" for i in lower.issues)
    short = nb.validate(s, "PRJ1-ABC-0001")
    assert any(i.code == "numbering_structure_invalid" for i in short.issues)
    assert nb.validate(s, "").issues[0].code == "numbering_empty"


def test_code_list_violation_is_its_own_code(schemes) -> None:
    s = schemes["iso19650_uk_na"]
    r = nb.validate(s, "PRJ1-ABC-ZZ-01-XX-S-0012")
    assert [(i.code, i.field) for i in r.issues] == [("numbering_code_not_in_list", "form")]


def test_number_shorter_than_its_padding_is_refused(schemes) -> None:
    r = nb.validate(schemes["iso19650_generic"], "PRJ1-ABC-ZZ-01-DR-A-01")
    assert ("numbering_field_invalid", "number") in [(i.code, i.field) for i in r.issues]


@pytest.mark.parametrize("segment", ["S2", "A1", "P01", "C02", "P.01.01"])
def test_status_or_revision_in_the_number_is_refused(schemes, segment) -> None:
    s = schemes["iso19650_generic"]
    appended = nb.validate(s, f"PRJ1-ABC-ZZ-01-DR-A-0001-{segment}")
    assert any(i.code == "numbering_metadata_in_number" for i in appended.issues), appended.issues
    if "." not in segment:
        inside = nb.validate(s, f"PRJ1-ABC-ZZ-{segment}-DR-A-0001")
        assert ("numbering_metadata_in_number", "spatial") in [(i.code, i.field) for i in inside.issues]


def test_parts_mismatch_lists_the_disagreeing_container_column(schemes) -> None:
    s = schemes["iso19650_generic"]
    code = "PRJ1-ABC-ZZ-01-DR-A-0001"
    stored = {
        "originator_code": "ABC",
        "functional_breakdown": "ZZ",
        "spatial_breakdown": "01",
        "form_code": "DR",
        "discipline_code": "A",
        "sequence_number": "0001",
    }
    assert nb.parts_mismatch(s, code, stored) == []
    assert nb.parts_mismatch(s, code, {**stored, "discipline_code": "S"}) == ["discipline"]
    assert nb.parts_mismatch(s, "garbage", stored) == ["number"]


def test_scope_key_ignores_the_number_and_follows_number_scope(schemes) -> None:
    s = schemes["iso19650_generic"]
    a = nb.scope_key(s, {"project": "PRJ1", "originator": "ABC", "form": "DR", "discipline": "a"})
    b = nb.scope_key(s, {"project": "PRJ1", "originator": "ABC", "form": "DR", "discipline": "A"})
    assert a == b
    de = schemes["de_planschluessel"]
    assert nb.scope_key(de, {"discipline": "AR", "form": "GR", "spatial": "EG"}) == nb.scope_key(
        de, {"discipline": "AR", "form": "GR", "spatial": "OG1"}
    )


def test_missing_required_values_are_listed_before_allocation(schemes) -> None:
    s = schemes["iso19650_generic"]
    assert nb.missing_values(s, {"project": "PRJ1"}) == ["originator", "functional", "spatial", "form", "discipline"]
