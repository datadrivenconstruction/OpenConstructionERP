# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request types as data: presets, numbering, required fields and catalogue rules.

Pure tests, no database. The PostgreSQL half (catalogue rows, numbering per
type through the real MAX scan, the API, the migration backfill) lives in
``tests/pg/test_rfi_request_types_on_pg.py``.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.rfi import request_types as rt
from app.modules.rfi.models import RFI, RFIRequestType
from app.modules.rfi.request_types import RequestTypeSpec
from app.modules.rfi.schemas import RequestTypeCreate, RFICreate, RFIUpdate
from app.modules.rfi.service import RFIService
from app.modules.rfi.validators import (
    RequestTypeCatalogueConsistent,
    RequestTypeRequiredFields,
    register_rfi_rules,
)

# ── Presets ─────────────────────────────────────────────────────────────


def test_both_presets_ship_and_general_comes_first() -> None:
    codes = [p.code for p in rt.list_presets()]
    assert codes == ["general_construction", "epc_oil_gas"]


def test_general_preset_carries_the_everyday_types() -> None:
    general = rt.get_preset("general_construction")
    assert [t.code for t in general.types] == ["RFI", "SQ", "DQ", "SBQ", "CLR", "DEC"]


def test_epc_preset_carries_the_process_industry_types() -> None:
    epc = {t.code for t in rt.get_preset("epc_oil_gas").types}
    assert {"RFI", "TQ", "VQ", "FQ", "SQ", "IQ", "TDR", "CON", "KDCN", "HAZ", "CIP"} <= epc


@pytest.mark.parametrize("preset", rt.list_presets(), ids=lambda p: p.code)
def test_every_shipped_preset_passes_the_catalogue_rules(preset: rt.Preset) -> None:
    assert rt.catalogue_problems(preset.types) == []


@pytest.mark.parametrize("preset", rt.list_presets(), ids=lambda p: p.code)
def test_every_shipped_type_is_named_in_english_and_german(preset: rt.Preset) -> None:
    for spec in preset.types:
        assert spec.name_i18n.get("en"), spec.code
        assert spec.name_i18n.get("de"), spec.code
    assert preset.name_i18n.get("en") and preset.name_i18n.get("de")


def test_deviation_and_concession_types_demand_the_specification_they_cite() -> None:
    epc = {t.code: t for t in rt.get_preset("epc_oil_gas").types}
    assert "linked_drawing_ids" in epc["TDR"].required_fields
    assert "linked_drawing_ids" in epc["CON"].required_fields


def test_rfi_is_identical_in_both_presets() -> None:
    """A project that loads both presets must not get two RFI shapes; the second load skips by code."""
    general = {t.code: t for t in rt.get_preset("general_construction").types}["RFI"]
    epc = {t.code: t for t in rt.get_preset("epc_oil_gas").types}["RFI"]
    assert (general.number_prefix, general.number_digits) == (epc.number_prefix, epc.number_digits)
    assert general.required_fields == epc.required_fields


def test_unknown_preset_raises_key_error() -> None:
    with pytest.raises(KeyError):
        rt.get_preset("no_such_preset")


# ── Built-in default ────────────────────────────────────────────────────


def test_builtin_default_numbers_exactly_as_the_register_did_before_types() -> None:
    spec = rt.builtin_default_type()
    assert spec.code == "RFI"
    assert spec.is_builtin
    assert rt.format_request_number(spec.number_prefix, 1, spec.number_digits) == "RFI-001"
    assert spec.response_days == 14
    assert spec.required_fields == ()


# ── Numbering ───────────────────────────────────────────────────────────


def test_numbers_are_padded_per_type() -> None:
    assert rt.format_request_number("TQ", 1, 4) == "TQ-0001"
    assert rt.format_request_number("KDCN", 12, 4) == "KDCN-0012"
    assert rt.format_request_number("RFI", 7, 3) == "RFI-007"


def test_a_number_wider_than_its_padding_is_kept_whole() -> None:
    assert rt.format_request_number("RFI", 1234, 3) == "RFI-1234"


def test_number_regex_matches_only_its_own_prefix() -> None:
    import re

    pattern = re.compile(rt.number_regex("SQ"))
    assert pattern.match("SQ-0001")
    assert not pattern.match("SBQ-0001")
    assert not pattern.match("SQ-")


def test_number_regex_refuses_a_prefix_that_could_inject_into_the_pattern() -> None:
    with pytest.raises(ValueError):
        rt.number_regex("A.*")


# ── Required fields ─────────────────────────────────────────────────────


def _spec(**kw) -> RequestTypeSpec:
    base = {"code": "TQ", "number_prefix": "TQ", "name_i18n": {"en": "Technical Query"}}
    base.update(kw)
    return RequestTypeSpec(**base)


def test_missing_required_fields_lists_empty_values_in_type_order() -> None:
    spec = _spec(required_fields=("assigned_to", "discipline", "linked_drawing_ids"))
    missing = rt.missing_required_fields(spec, {"assigned_to": "  ", "discipline": "civil", "linked_drawing_ids": []})
    assert missing == ["assigned_to", "linked_drawing_ids"]


def test_zero_and_false_count_as_answers() -> None:
    spec = _spec(required_fields=("schedule_impact_days",))
    assert rt.missing_required_fields(spec, {"schedule_impact_days": 0}) == []


# ── Localized names ─────────────────────────────────────────────────────


def test_localized_text_falls_back_from_region_to_language_to_english() -> None:
    names = {"en": "Site Query", "de": "Baustellenanfrage"}
    assert rt.localized_text(names, "de-AT", "SQ") == "Baustellenanfrage"
    assert rt.localized_text(names, "fr", "SQ") == "Site Query"
    assert rt.localized_text({}, "de", "SQ") == "SQ"


# ── Catalogue rules ─────────────────────────────────────────────────────


def test_a_prefix_shared_by_two_types_is_a_problem() -> None:
    problems = rt.catalogue_problems([_spec(code="TQ"), _spec(code="TQ2", number_prefix="TQ")])
    assert [p.code for p in problems] == ["duplicate_prefix"]


def test_bad_shapes_are_each_named() -> None:
    problems = rt.catalogue_problems(
        [
            _spec(code="tq", number_prefix="t-q", number_digits=9, required_fields=("nope",), name_i18n={}),
        ]
    )
    assert {p.code for p in problems} == {
        "invalid_code",
        "invalid_prefix",
        "invalid_digits",
        "unknown_required_field",
        "missing_english_name",
    }


# ── Model and schemas ───────────────────────────────────────────────────


def test_request_type_column_backfills_existing_rows_through_its_server_default() -> None:
    """The boot heal adds a NOT NULL column only with a literal default; the default IS the backfill."""
    column = RFI.__table__.c.request_type
    assert column.nullable is False
    assert column.server_default is not None
    assert column.server_default.arg == "RFI"


def test_catalogue_identifiers_fit_postgres() -> None:
    table = RFIRequestType.__table__
    names = [table.name] + [c.name for c in table.constraints if c.name] + [i.name for i in table.indexes]
    names += [i.name for i in RFI.__table__.indexes]
    assert all(len(str(n)) < 63 for n in names), names


def test_rfi_create_defaults_to_the_rfi_type() -> None:
    data = RFICreate(project_id=uuid.uuid4(), subject="s", question="q")
    assert data.request_type == "RFI"


def test_rfi_create_upper_cases_the_type_code() -> None:
    data = RFICreate(project_id=uuid.uuid4(), subject="s", question="q", request_type="tq")
    assert data.request_type == "TQ"


def test_rfi_update_cannot_change_the_type() -> None:
    """The number carries the type's prefix; a type change would leave TQ-0001 numbered as an RFI."""
    assert "request_type" not in RFIUpdate.model_fields


def test_type_create_refuses_an_unknown_required_field() -> None:
    with pytest.raises(ValueError):
        RequestTypeCreate(
            project_id=uuid.uuid4(),
            code="TQ",
            number_prefix="TQ",
            name_i18n={"en": "Technical Query"},
            required_fields=["favourite_colour"],
        )


def test_type_create_needs_an_english_name() -> None:
    with pytest.raises(ValueError):
        RequestTypeCreate(project_id=uuid.uuid4(), code="TQ", number_prefix="TQ", name_i18n={"de": "Technische"})


# ── Service with the built-in catalogue (no database) ──────────────────


class _Repo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, RFI] = {}
        self.asked: list[tuple[str, int]] = []

    async def next_rfi_number(self, project_id: uuid.UUID, *, prefix: str = "RFI", digits: int = 3) -> str:
        self.asked.append((prefix, digits))
        return rt.format_request_number(prefix, len(self.rows) + 1, digits)

    async def create(self, rfi: RFI) -> RFI:
        from datetime import UTC, datetime

        rfi.id = uuid.uuid4()
        rfi.created_at = rfi.updated_at = datetime.now(UTC)
        self.rows[rfi.id] = rfi
        return rfi


def _service() -> RFIService:
    svc = RFIService.__new__(RFIService)
    svc.session = object()  # type: ignore[assignment]
    svc.repo = _Repo()  # type: ignore[assignment]
    return svc


@pytest.mark.asyncio
async def test_a_project_without_a_catalogue_still_files_rfis() -> None:
    svc = _service()
    rfi = await svc.create_rfi(RFICreate(project_id=uuid.uuid4(), subject="s", question="q"))
    assert rfi.request_type == "RFI"
    assert rfi.rfi_number == "RFI-001"


@pytest.mark.asyncio
async def test_a_project_without_a_catalogue_refuses_other_types() -> None:
    from fastapi import HTTPException

    svc = _service()
    with pytest.raises(HTTPException) as exc:
        await svc.create_rfi(RFICreate(project_id=uuid.uuid4(), subject="s", question="q", request_type="TQ"))
    assert exc.value.status_code == 422


# ── Validation rules ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_required_fields_rule_flags_an_issued_request_with_a_gap() -> None:
    from app.core.validation.engine import ValidationContext

    tq = _spec(required_fields=("assigned_to",))
    data = {
        "types": [tq],
        "requests": [
            {"id": "a", "rfi_number": "TQ-0001", "request_type": "TQ", "status": "open", "assigned_to": None},
            {"id": "b", "rfi_number": "TQ-0002", "request_type": "TQ", "status": "draft", "assigned_to": None},
        ],
    }
    results = await RequestTypeRequiredFields().validate(ValidationContext(data=data))
    failed = [r for r in results if not r.passed]
    assert [r.element_ref for r in failed] == ["a"]
    assert failed[0].details["missing"] == ["assigned_to"]


@pytest.mark.asyncio
async def test_required_fields_rule_passes_once_when_nothing_is_missing() -> None:
    from app.core.validation.engine import ValidationContext

    results = await RequestTypeRequiredFields().validate(ValidationContext(data={"types": [], "requests": []}))
    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_catalogue_rule_flags_a_request_whose_type_left_the_catalogue() -> None:
    from app.core.validation.engine import ValidationContext

    data = {
        "types": [rt.builtin_default_type()],
        "requests": [{"id": "x", "rfi_number": "TQ-0001", "request_type": "TQ", "status": "open"}],
    }
    results = await RequestTypeCatalogueConsistent().validate(ValidationContext(data=data))
    assert any(not r.passed and r.details.get("problem") == "unknown_type" for r in results)


def test_rules_register_under_the_rfi_rule_set() -> None:
    from app.core.validation.engine import rule_registry

    register_rfi_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets(["rfi"])}
    assert {"rfi.request_type_required_fields", "rfi.request_type_catalogue_consistent"} <= ids
