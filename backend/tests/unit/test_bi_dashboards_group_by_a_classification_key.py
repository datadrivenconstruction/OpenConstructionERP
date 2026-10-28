# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A custom KPI can break down by a key inside ``classification``.

``classification`` is the only place a BOQ position records what KIND of work
it is, and an estimator's own vocabulary lives there: labour, material,
equipment, subcontract, indirect. Until now the KPI catalogue did not offer it,
so the nearest reachable field was ``source``, which answers a different
question entirely - how the row was entered. That column defaults to ``manual``
and every ordinary create path in the tree writes it literally; only the CAD and
AI import paths ever write anything else. So on an installation where the BOQs
were typed or imported from a workbook, a breakdown by it renders one bar and
looks like a working cost analysis. A KPI that reads a plausible number for the
wrong reason is harder to catch than one that reads zero.

The column is JSON, so there is no finite list of field names to whitelist: the
keys are ``din276`` or ``masterformat`` or ``nrm`` or whatever the estimator's
workbook calls its cost types, and a catalogue that had to know them in advance
would have to be edited before a deployment could read its own data. So the
catalogue declares the COLUMN and the spec supplies the key, which is the one
name in a spec that is not already a key in a table in the module.

That widening is what most of this file tests. The key is bounded by a pattern,
an undeclared column is refused, and the two refusals say different things
because they are different mistakes.
"""

from __future__ import annotations

import pytest

from app.modules.bi_dashboards.kpi_spec import (
    ENTITY_CATALOG,
    KIND_TEXT,
    KPISpecError,
    bind_entity,
    catalog_as_dict,
    check_catalog_binding_parity,
    validate_spec,
)


class TestTheCatalogueOffersIt:
    def test_the_column_is_declared_on_boq_position(self) -> None:
        entry = ENTITY_CATALOG["boq_position"]
        assert entry.json_fields == {"classification": KIND_TEXT}

    def test_a_path_resolves_to_the_kind_of_the_column(self) -> None:
        entry = ENTITY_CATALOG["boq_position"]
        assert entry.kind_of("classification.tipo") == KIND_TEXT
        # A plain field still resolves the way it always did.
        assert entry.kind_of("unit") == KIND_TEXT
        # And a name that is neither is a miss rather than a KeyError.
        assert entry.kind_of("classification") is None
        assert entry.kind_of("nope") is None

    def test_the_api_serves_the_column_so_a_picker_can_offer_it(self) -> None:
        served = {e["name"]: e for e in catalog_as_dict()}
        paths = served["boq_position"]["json_path_fields"]
        assert paths == [{"name": "classification", "kind": KIND_TEXT, "example": "classification.<key>"}]

    def test_the_column_is_not_listed_as_a_plain_groupable_field(self) -> None:
        # There is no finite list of paths to advertise, and offering the bare
        # column would promise a breakdown keyed by a whole JSON object.
        entry = ENTITY_CATALOG["boq_position"]
        assert "classification" not in entry.groupable_fields()
        assert "classification" not in entry.fields


class TestASpecCanUseIt:
    def test_a_breakdown_by_a_classification_key_is_accepted(self) -> None:
        spec = validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "sum",
                "field": "amount",
                "group_by": "classification.tipo",
                "filters": [],
            }
        )
        assert spec["group_by"] == "classification.tipo"

    def test_the_scheme_does_not_have_to_be_one_the_catalogue_knows(self) -> None:
        # din276, masterformat, nrm and an estimator's own word all reach the
        # same way, which is the whole point of declaring the column instead
        # of the keys.
        for key in ("din276", "masterformat", "nrm", "cost_type", "tipo"):
            spec = validate_spec(
                {
                    "entity": "boq_position",
                    "aggregation": "count",
                    "group_by": f"classification.{key}",
                }
            )
            assert spec["group_by"] == f"classification.{key}"

    def test_it_can_be_filtered_on_as_well_as_grouped_by(self) -> None:
        spec = validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "sum",
                "field": "amount",
                "filters": [{"field": "classification.tipo", "op": "eq", "value": "Mano de obra"}],
            }
        )
        assert spec["filters"][0]["field"] == "classification.tipo"


class TestTheWideningStaysNarrow:
    @pytest.mark.parametrize(
        "key",
        [
            "",  # classification. with nothing after it
            "1tipo",  # must start with a letter
            "ti-po",  # no hyphens
            "ti po",  # no spaces
            "ti.po",  # no nesting, one level only
            "x" * 65,  # bounded
            "'; DROP TABLE oe_boq_position; --",
        ],
    )
    def test_a_key_outside_the_pattern_is_refused(self, key: str) -> None:
        with pytest.raises(KPISpecError):
            validate_spec(
                {
                    "entity": "boq_position",
                    "aggregation": "count",
                    "group_by": f"classification.{key}",
                }
            )

    def test_a_path_on_a_column_that_is_not_json_is_refused(self) -> None:
        with pytest.raises(KPISpecError) as excinfo:
            validate_spec(
                {
                    "entity": "boq_position",
                    "aggregation": "count",
                    "group_by": "description.tipo",
                }
            )
        # The two refusals have to read differently. Neither mistake is visible
        # in the list of allowed names - the column is in it, the path is not -
        # so the message is the only thing that tells the author which one they
        # made.
        assert "not a JSON column" in str(excinfo.value)

    def test_a_bad_key_says_so_rather_than_blaming_the_column(self) -> None:
        with pytest.raises(KPISpecError) as excinfo:
            validate_spec(
                {
                    "entity": "boq_position",
                    "aggregation": "count",
                    "group_by": "classification.ti-po",
                }
            )
        assert "not a usable key" in str(excinfo.value)

    def test_an_entity_with_no_json_column_refuses_every_path(self) -> None:
        with pytest.raises(KPISpecError):
            validate_spec({"entity": "boq", "aggregation": "count", "group_by": "classification.tipo"})

    def test_a_path_cannot_be_summed(self) -> None:
        # The values are read as text whatever they hold, so an aggregation
        # that needs a number must refuse one rather than coercing it.
        with pytest.raises(KPISpecError):
            validate_spec(
                {
                    "entity": "boq_position",
                    "aggregation": "sum",
                    "field": "classification.tipo",
                }
            )


class TestTheBindingAgreesWithTheCatalogue:
    def test_parity_holds_including_the_json_columns(self) -> None:
        # A JSON column declared and not bound is worse than a plain field in
        # the same state: validation reads the catalogue, so the definition is
        # accepted and stored, and the failure only arrives at compute time on
        # a KPI already sitting on somebody's dashboard.
        assert check_catalog_binding_parity() == {}

    def test_the_binder_builds_an_expression_for_an_arbitrary_key(self) -> None:
        bound = bind_entity("boq_position")
        field = bound.resolve_field("classification.tipo")
        assert field.kind == KIND_TEXT
        assert field.expr is not None

    def test_the_key_is_a_bound_parameter_and_not_spliced_into_sql(self) -> None:
        # The reason an arbitrary key is safe at all. If the key were
        # concatenated it would appear in the compiled text; it must appear in
        # the parameters instead.
        bound = bind_entity("boq_position")
        compiled = bound.resolve_field("classification.tipo").expr.compile()
        assert "tipo" not in str(compiled)
        assert "tipo" in list(compiled.params.values())

    def test_a_plain_field_still_resolves(self) -> None:
        bound = bind_entity("boq_position")
        assert bound.resolve_field("unit").kind == KIND_TEXT

    def test_an_unbound_name_raises_rather_than_returning_something(self) -> None:
        bound = bind_entity("boq_position")
        with pytest.raises(KeyError):
            bound.resolve_field("nope")
        with pytest.raises(KeyError):
            bound.resolve_field("description.tipo")
