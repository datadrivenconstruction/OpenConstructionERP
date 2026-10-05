# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The probe registry is the closed list, and every probed field has one unit.

A probe type the loader accepts but the checker cannot run would leave a task
that no learner can pass; a field without a unit would be compared as money by
accident. Both are caught here, from the frozen args models themselves.
"""

from __future__ import annotations

import typing
from decimal import Decimal

import pytest

from app.core.validation.messages import is_key_present
from app.modules.trainer.checker.matching import UNIT_SLIP_DIAGNOSIS_ID
from app.modules.trainer.checker.registry import (
    OPEN_LEVELING_KEY,
    PROBE_REGISTRY,
    Probe,
    ProbeContext,
    ProbeReading,
    get_probe,
    register_probe,
    registered_probe_types,
)
from app.modules.trainer.checker.units import (
    format_decimal,
    format_value,
    parse_panel_number,
    probe_field_kind,
    quantize_money,
    rate_to_percent,
)
from app.modules.trainer.probe_types import PROBE_TYPE_NAMES, PROBE_TYPES
from app.modules.trainer.spec import (
    PERCENT_PROBE_FIELDS,
    PROBE_ARGS_MODELS,
    TEXT_PROBE_FIELDS,
    BoqMarkupArgs,
)


def _fields(type_name: str) -> list[str]:
    model = PROBE_ARGS_MODELS[type_name]
    annotation = model.model_fields.get("field")
    if annotation is None:
        return [""]
    return list(typing.get_args(annotation.annotation))


def test_the_registry_is_exactly_the_closed_probe_list() -> None:
    assert registered_probe_types() == PROBE_TYPE_NAMES


@pytest.mark.parametrize("type_name", sorted(PROBE_TYPE_NAMES))
def test_each_probe_reads_its_frozen_args_model(type_name: str) -> None:
    assert get_probe(type_name).args_model is PROBE_ARGS_MODELS[type_name]


def test_reads_erp_agrees_with_the_probe_type_list() -> None:
    for probe_type in PROBE_TYPES:
        assert get_probe(probe_type.name).reads_erp is probe_type.reads_erp, probe_type.name


def test_every_field_of_every_probe_has_exactly_one_kind() -> None:
    seen: dict[tuple[str, str], str] = {}
    for type_name in PROBE_TYPE_NAMES:
        for field in _fields(type_name):
            seen[(type_name, field)] = probe_field_kind(type_name, field)
    assert set(seen.values()) <= {"money", "percent", "number", "text", "date", "bool"}
    for key in PERCENT_PROBE_FIELDS:
        assert seen[key] == "percent", key
    for key, kind in seen.items():
        if kind == "percent":
            assert key in PERCENT_PROBE_FIELDS, key
    for key in TEXT_PROBE_FIELDS:
        assert seen[key] in ("text", "date"), key
    assert seen[("boq.section_total", "")] == "money"
    assert seen[("bid.submission", "is_valid")] == "bool"
    assert seen[("bid.leveling", "rank")] == "number"


def test_a_probe_outside_the_closed_list_is_refused() -> None:
    class Rogue(Probe):
        args_model = BoqMarkupArgs

        async def read(self, session, ctx, args):  # type: ignore[no-untyped-def]
            return ProbeReading.of(Decimal(1))

    with pytest.raises(ValueError, match="not in probe_types"):
        register_probe("boq.everything")(Rogue)


def test_a_second_probe_for_one_type_is_refused() -> None:
    class Twin(Probe):
        args_model = BoqMarkupArgs

        async def read(self, session, ctx, args):  # type: ignore[no-untyped-def]
            return ProbeReading.of(Decimal(1))

    get_probe("boq.markup")
    with pytest.raises(ValueError, match="registered twice"):
        register_probe("boq.markup")(Twin)
    assert type(PROBE_REGISTRY["boq.markup"]).__name__ == "BoqMarkupProbe"


def test_a_probe_on_another_args_model_is_refused() -> None:
    PROBE_REGISTRY.pop("panel.answer", None)
    try:

        class Wrong(Probe):
            args_model = BoqMarkupArgs

            async def read(self, session, ctx, args):  # type: ignore[no-untyped-def]
                return ProbeReading.of(Decimal(1))

        with pytest.raises(ValueError, match="frozen args model"):
            register_probe("panel.answer")(Wrong)
    finally:
        from app.modules.trainer.checker.probes import PanelAnswerProbe

        PROBE_REGISTRY["panel.answer"] = PanelAnswerProbe()


def test_a_ref_resolves_only_to_an_id() -> None:
    import uuid

    good = uuid.uuid4()
    ctx = ProbeContext(project_id=uuid.uuid4(), seeded_refs={"boq.main": str(good), "contract.main": "not-an-id"})
    assert ctx.ref_id("boq.main") == good
    assert ctx.ref_id("contract.main") is None
    assert ctx.ref_id("bid_package.main") is None


def test_a_fraction_rate_becomes_percent_exactly() -> None:
    assert rate_to_percent(Decimal("0.05"), "fraction") == Decimal("5.00")
    assert rate_to_percent(Decimal("5"), "percent") == Decimal("5")
    assert rate_to_percent(Decimal("5"), None) == Decimal("5")


def test_money_is_quantised_to_the_currency_minor_unit() -> None:
    assert quantize_money(Decimal("606.905"), "GBP") == Decimal("606.91")
    assert quantize_money(Decimal("1234.5"), "JPY") == Decimal("1235")
    assert quantize_money(Decimal("1.0005"), "KWD") == Decimal("1.001")


def test_a_typed_percent_accepts_the_sign_and_nothing_else() -> None:
    assert parse_panel_number("3") == Decimal("3")
    assert parse_panel_number(" 3% ") == Decimal("3")
    assert parse_panel_number("3.00") == Decimal("3.00")
    assert parse_panel_number("") is None
    assert parse_panel_number("three") is None
    assert parse_panel_number(None) is None


def test_values_are_written_as_plain_decimals_never_scientific() -> None:
    assert format_decimal(Decimal("0E-4")) == "0.0000"
    assert format_decimal(Decimal("1E+2")) == "100"
    assert format_decimal(Decimal("-0.00")) == "0.00"
    assert format_value(Decimal("12138.0000"), "money", "GBP") == "12138.00"
    assert format_value(Decimal("5.0"), "percent", "GBP") == "5.0"
    assert format_value(True, "bool", "GBP") == "true"
    assert format_value("Brackenfold Roofs", "text", "GBP") == "Brackenfold Roofs"
    assert format_value(None, "money", "GBP") is None


@pytest.mark.parametrize("locale", ["en", "de", "es", "ru"])
@pytest.mark.parametrize("key", [UNIT_SLIP_DIAGNOSIS_ID, OPEN_LEVELING_KEY])
def test_the_checkers_own_messages_exist_in_every_validation_locale(key: str, locale: str) -> None:
    assert is_key_present(key, locale)
