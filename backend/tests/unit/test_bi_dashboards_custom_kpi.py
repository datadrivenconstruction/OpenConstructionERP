# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Custom KPI definitions - issue #441.

The module shipped 35 built-in KPIs and no way to add a 36th without
shipping Python. These tests pin the way in that was added for the people
who cannot ship Python: a declarative spec over a whitelisted entity,
checked when the definition is created rather than when it is computed.

The three specs exercised here are the ones the reporter asked for, an
estimating SME with a per-position confidence score:

* amount-weighted bid confidence, ``sum(confidence * amount) / sum(amount)``
* the largest position of each bid
* how many positions are scored below a confidence threshold

Test isolation: a transaction-isolated PostgreSQL session on the shared
schema-loaded ``oe_test_unit`` database, rolled back on teardown.

Run:
    cd backend
    python -m pytest tests/unit/test_bi_dashboards_custom_kpi.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards import kpi_spec, kpis
from app.modules.bi_dashboards.models import DashboardWidget, KPIDefinition
from app.modules.bi_dashboards.schemas import KPIDefinitionCreate
from app.modules.bi_dashboards.service import (
    BIDashboardsService,
    CustomKPICodeInUse,
    CustomKPIInUse,
    CustomKPIIsSystem,
)
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"kpi-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="O",
            ),
        )
        await s.flush()
        yield s


async def _seed_two_bids(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """One project, two bids, four priced positions.

    Bid A: 100 x 10 at confidence 0.9, 200 x 20 at confidence 0.4
        -> weighted confidence (900 + 1600) / 5000 = 0.5, top amount 4000
    Bid B: 10 x 100 at confidence 0.2, 1 x 3000 with confidence unset
        -> weighted confidence 200 / 1000 = 0.2, top amount 3000

    The unscored position in bid B is the interesting one: it must be left
    out of the average rather than read as a zero score, and it must not
    answer to "confidence below 0.5" either.

    Returns ``(project_id, bid_a_id, bid_b_id)``.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name="Custom KPI project",
            owner_id=OWNER_ID,
            currency="EUR",
        ),
    )
    await session.flush()

    bid_a = BOQ(id=uuid.uuid4(), project_id=project_id, name="Bid A")
    bid_b = BOQ(id=uuid.uuid4(), project_id=project_id, name="Bid B")
    session.add_all([bid_a, bid_b])
    await session.flush()

    session.add_all(
        [
            Position(
                id=uuid.uuid4(),
                boq_id=bid_a.id,
                ordinal="A.001",
                description="Excavation",
                unit="m3",
                quantity="100",
                unit_rate="10",
                total="1000",
                confidence="0.9",
                sort_order=1,
            ),
            Position(
                id=uuid.uuid4(),
                boq_id=bid_a.id,
                ordinal="A.002",
                description="Concrete",
                unit="m3",
                quantity="200",
                unit_rate="20",
                total="4000",
                confidence="0.4",
                sort_order=2,
            ),
            Position(
                id=uuid.uuid4(),
                boq_id=bid_b.id,
                ordinal="B.001",
                description="Formwork",
                unit="m2",
                quantity="10",
                unit_rate="100",
                total="1000",
                confidence="0.2",
                sort_order=1,
            ),
            Position(
                id=uuid.uuid4(),
                boq_id=bid_b.id,
                ordinal="B.002",
                description="Provisional sum",
                unit="item",
                quantity="1",
                unit_rate="3000",
                total="3000",
                confidence=None,
                sort_order=2,
            ),
        ],
    )
    await session.flush()
    return project_id, bid_a.id, bid_b.id


def _weighted_confidence_payload(
    code: str = "bid_confidence",
    *,
    project_id: uuid.UUID | None = None,
) -> KPIDefinitionCreate:
    return KPIDefinitionCreate(
        code=code,
        name="Amount-weighted bid confidence",
        description="Confidence of the estimate, weighted by what each line is worth.",
        unit="ratio",
        category="quality",
        project_id=project_id,
        spec={
            "entity": "boq_position",
            "aggregation": "weighted_avg",
            "field": "confidence",
            "weight_field": "amount",
            "group_by": "boq_id",
        },
    )


# ── The whitelist itself ───────────────────────────────────────────────


def test_catalog_and_bindings_describe_the_same_fields() -> None:
    """The documented whitelist and the executable one must not drift.

    A field declared in the catalog but not built is a promise the API
    advertises and then rejects; a field built but not declared is a
    column reachable without ever being documented. Both are the kind of
    gap that survives review because each half reads correctly alone.
    """
    assert kpi_spec.check_catalog_binding_parity() == {}


def test_catalog_never_offers_a_measure_as_a_grouping_key() -> None:
    for entry in kpi_spec.ENTITY_CATALOG.values():
        overlap = set(entry.numeric_fields()) & set(entry.groupable_fields())
        assert overlap == set(), f"{entry.name} offers {sorted(overlap)} as both measure and key"


# ── Validation at creation time ────────────────────────────────────────


def test_unknown_field_is_rejected_and_the_error_names_it() -> None:
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "sum",
                "field": "profit_margin",
            },
        )
    err = exc_info.value
    assert err.path == "spec.field"
    assert err.value == "profit_margin"
    assert "profit_margin" in str(err)
    # The rejection has to tell the caller what would have worked.
    assert "amount" in (err.allowed or [])
    assert "profit_margin" not in (err.allowed or [])


def test_unknown_entity_is_rejected_by_name() -> None:
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec({"entity": "oe_users_user", "aggregation": "count"})
    assert exc_info.value.path == "spec.entity"
    assert exc_info.value.allowed == sorted(kpi_spec.ENTITY_CATALOG)


def test_unknown_aggregation_is_rejected_by_name() -> None:
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {"entity": "boq_position", "aggregation": "stddev", "field": "amount"},
        )
    assert exc_info.value.path == "spec.aggregation"
    assert exc_info.value.value == "stddev"


def test_text_field_cannot_be_summed() -> None:
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {"entity": "boq_position", "aggregation": "sum", "field": "description"},
        )
    assert exc_info.value.path == "spec.field"
    assert "numeric" in str(exc_info.value)


def test_field_valid_on_one_entity_is_rejected_on_another() -> None:
    """The whitelist is per entity, not one flat pool of column names."""
    kpi_spec.validate_spec({"entity": "boq_position", "aggregation": "sum", "field": "amount"})
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec({"entity": "boq", "aggregation": "sum", "field": "amount"})
    assert exc_info.value.path == "spec.field"
    assert exc_info.value.value == "amount"


def test_filter_operator_outside_the_whitelist_is_rejected_with_its_index() -> None:
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "count",
                "filters": [
                    {"field": "unit", "op": "eq", "value": "m3"},
                    {"field": "description", "op": "like", "value": "%concrete%"},
                ],
            },
        )
    assert exc_info.value.path == "spec.filters[1].op"
    assert exc_info.value.value == "like"


def test_filter_field_outside_the_whitelist_is_rejected() -> None:
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "count",
                "filters": [{"field": "hashed_password", "op": "eq", "value": "x"}],
            },
        )
    assert exc_info.value.path == "spec.filters[0].field"


def test_ordering_operator_needs_a_numeric_field() -> None:
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "count",
                "filters": [{"field": "unit", "op": "gt", "value": 3}],
            },
        )
    assert exc_info.value.path == "spec.filters[0].op"


def test_count_must_not_name_a_field() -> None:
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {"entity": "boq_position", "aggregation": "count", "field": "amount"},
        )
    assert exc_info.value.path == "spec.field"


def test_weighted_avg_without_a_weight_is_rejected() -> None:
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {"entity": "boq_position", "aggregation": "weighted_avg", "field": "confidence"},
        )
    assert exc_info.value.path == "spec.weight_field"


@pytest.mark.parametrize(
    ("aggregation", "extra"),
    [
        ("sum", {}),
        ("avg", {}),
        ("weighted_avg", {"weight_field": "amount"}),
        ("top_by", {}),
    ],
)
def test_a_breakdown_can_be_labelled_whatever_the_aggregation(
    aggregation: str,
    extra: dict[str, Any],
) -> None:
    """A grouped breakdown gets to say what each group is called.

    ``label_field`` used to be the private property of ``top_by``, so the
    reporter's amount-weighted confidence per bid came back keyed by raw
    ``boq_id`` values with the one field that would have named them
    refused. What decides now is whether there are rows to label.
    """
    spec = kpi_spec.validate_spec(
        {
            "entity": "boq_position",
            "aggregation": aggregation,
            "field": "amount" if aggregation != "weighted_avg" else "confidence",
            "group_by": "boq_id",
            "label_field": "boq_name",
            **extra,
        },
    )
    assert spec["label_field"] == "boq_name"


def test_a_label_field_needs_something_to_label() -> None:
    """The counterweight: a headline number has no rows to name."""
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "sum",
                "field": "amount",
                "label_field": "boq_name",
            },
        )
    assert exc_info.value.path == "spec.label_field"


def test_validation_drops_keys_it_does_not_understand() -> None:
    """What is stored is what validation looked at, and nothing else."""
    normalised = kpi_spec.validate_spec(
        {
            "entity": "boq_position",
            "aggregation": "sum",
            "field": "amount",
            "having": "1=1",
            "raw_sql": "DROP TABLE oe_boq_position",
        },
    )
    assert normalised == {
        "entity": "boq_position",
        "aggregation": "sum",
        "field": "amount",
        "filters": [],
    }


# ── Creation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_custom_kpi_persists_a_validated_spec(session: AsyncSession) -> None:
    service = BIDashboardsService(session)
    row = await service.create_custom_kpi(_weighted_confidence_payload())

    assert row.code == "bid_confidence"
    assert row.is_system is False
    # ``formula_ref`` names no Python function on purpose - the lookup in
    # KPI_FORMULAS is meant to miss so the spec path runs.
    assert row.formula_ref not in kpis.KPI_FORMULAS
    assert row.spec_json["entity"] == "boq_position"
    # The source module is derived from the entity, never taken on trust.
    assert row.source_modules == ["oe_boq"]


@pytest.mark.asyncio
async def test_create_refuses_a_code_a_builtin_already_owns(session: AsyncSession) -> None:
    """Otherwise the spec would be stored and never consulted.

    ``kpis.compute`` looks in ``KPI_FORMULAS`` first, so a custom row
    named ``cpi`` would sit in the table while every surface kept showing
    the built-in cost performance index.
    """
    service = BIDashboardsService(session)
    payload = _weighted_confidence_payload(code="cpi")
    with pytest.raises(CustomKPICodeInUse) as exc_info:
        await service.create_custom_kpi(payload)
    assert exc_info.value.code == "cpi"


@pytest.mark.asyncio
async def test_create_refuses_a_duplicate_custom_code(session: AsyncSession) -> None:
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    with pytest.raises(CustomKPICodeInUse):
        await service.create_custom_kpi(_weighted_confidence_payload())


# ── Computation, through the same entry point every surface uses ───────


@pytest.mark.asyncio
async def test_weighted_confidence_computes_per_bid(session: AsyncSession) -> None:
    project_id, bid_a, bid_b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())

    result = await kpis.compute("bid_confidence", session, project_id=project_id)

    # (0.9*1000 + 0.4*4000 + 0.2*1000) / (1000 + 4000 + 1000) = 2700/6000
    assert result.value == pytest.approx(Decimal("0.45"), abs=Decimal("0.0001"))
    assert result.unit == "ratio"
    # The spec names no label and still gets one: ``boq_id`` is an id the
    # catalog knows the name of, so the breakdown reads as bids rather
    # than as uuids. See test_bi_dashboards_a_breakdown_by_id_reads_as_names.
    assert result.breakdown[str(bid_a)]["label"] == "Bid A"
    assert Decimal(result.breakdown[str(bid_a)]["value"]) == pytest.approx(Decimal("0.5"), abs=Decimal("0.0001"))
    # Bid B's unscored provisional sum is excluded rather than counted as
    # zero confidence, which would have dragged the bid to 0.1.
    assert result.breakdown[str(bid_b)]["label"] == "Bid B"
    assert Decimal(result.breakdown[str(bid_b)]["value"]) == pytest.approx(Decimal("0.2"), abs=Decimal("0.0001"))
    assert result.source_record_count == 3


@pytest.mark.asyncio
async def test_top_position_by_amount_per_bid(session: AsyncSession) -> None:
    project_id, bid_a, bid_b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(
        KPIDefinitionCreate(
            code="top_position_amount",
            name="Largest position per bid",
            unit="currency",
            category="financial",
            spec={
                "entity": "boq_position",
                "aggregation": "top_by",
                "field": "amount",
                "label_field": "description",
                "group_by": "boq_id",
            },
        ),
    )

    result = await kpis.compute("top_position_amount", session, project_id=project_id)

    assert result.value == pytest.approx(Decimal("4000"), abs=Decimal("0.01"))
    assert result.breakdown[str(bid_a)]["label"] == "Concrete"
    assert result.breakdown[str(bid_b)]["label"] == "Provisional sum"
    assert Decimal(result.breakdown[str(bid_b)]["value"]) == pytest.approx(
        Decimal("3000"),
        abs=Decimal("0.01"),
    )


@pytest.mark.asyncio
async def test_a_grouped_breakdown_names_each_group_it_returns(session: AsyncSession) -> None:
    """The reporter's KPI, with its ids turned into names.

    Two halves had to meet for this to work. The label was refused for
    every aggregation but ``top_by``, and the entity had no field holding
    the parent document's name, so even an accepted label had nothing
    readable to point at. The label resolves through the join
    ``boq_position`` already carries for project scoping, and it is
    aggregated rather than grouped by, so one group stays one row.

    Asking for the label by name is still the way to point it somewhere
    the entity does not choose for you. Where the catalog declares which
    field names an id, leaving ``label_field`` out now resolves to that
    field when the definition is created, so the label here is the
    explicit spelling of what a group by ``boq_id`` gets anyway - see
    test_bi_dashboards_a_breakdown_by_id_reads_as_names. A group keyed by
    something with no declared name, and a stored spec written before the
    default existed, both keep the plain ``{key: value}`` shape.
    """
    project_id, bid_a, bid_b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(
        KPIDefinitionCreate(
            code="bid_confidence_named",
            name="Amount-weighted bid confidence, per bid",
            unit="ratio",
            category="quality",
            spec={
                "entity": "boq_position",
                "aggregation": "weighted_avg",
                "field": "confidence",
                "weight_field": "amount",
                "group_by": "boq_id",
                "label_field": "boq_name",
            },
        ),
    )

    result = await kpis.compute("bid_confidence_named", session, project_id=project_id)

    assert result.breakdown[str(bid_a)]["label"] == "Bid A"
    assert result.breakdown[str(bid_b)]["label"] == "Bid B"
    assert Decimal(result.breakdown[str(bid_a)]["value"]) == pytest.approx(
        Decimal("0.5"),
        abs=Decimal("0.0001"),
    )


@pytest.mark.asyncio
async def test_a_breakdown_can_be_keyed_by_the_document_name(session: AsyncSession) -> None:
    """The other way to read a bid: group by the name itself."""
    project_id, _a, _b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(
        KPIDefinitionCreate(
            code="amount_per_bid_name",
            name="Amount per bid",
            unit="currency",
            category="financial",
            spec={
                "entity": "boq_position",
                "aggregation": "sum",
                "field": "amount",
                "group_by": "boq_name",
            },
        ),
    )

    result = await kpis.compute("amount_per_bid_name", session, project_id=project_id)

    assert Decimal(result.breakdown["Bid A"]) == pytest.approx(Decimal("5000"), abs=Decimal("0.01"))
    assert Decimal(result.breakdown["Bid B"]) == pytest.approx(Decimal("4000"), abs=Decimal("0.01"))


@pytest.mark.asyncio
async def test_low_confidence_count_leaves_unscored_positions_out(session: AsyncSession) -> None:
    """An unset confidence is not a low confidence.

    ``numeric_value`` reads a NULL text column as 0 on PostgreSQL, so
    without an explicit NULL guard "below 0.5" would sweep in every
    position nobody has scored yet - three instead of two here.
    """
    project_id, _bid_a, _bid_b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(
        KPIDefinitionCreate(
            code="low_confidence_positions",
            name="Positions below 0.5 confidence",
            unit="count",
            category="quality",
            spec={
                "entity": "boq_position",
                "aggregation": "count",
                "filters": [{"field": "confidence", "op": "lt", "value": 0.5}],
            },
        ),
    )

    result = await kpis.compute("low_confidence_positions", session, project_id=project_id)
    assert result.value == Decimal("2")
    assert result.unit == "count"


@pytest.mark.asyncio
async def test_portfolio_call_honours_the_callers_accessible_projects(session: AsyncSession) -> None:
    """A custom KPI is not allowed to be the read that ignores scoping.

    Same ``allowed_project_ids`` narrowing the built-in formulas get: an
    empty set means the caller can reach nothing, which must read as zero
    rather than as every project in the deployment.
    """
    project_id, _a, _b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(
        KPIDefinitionCreate(
            code="portfolio_bid_value",
            name="Portfolio bid value",
            unit="currency",
            category="financial",
            spec={"entity": "boq_position", "aggregation": "sum", "field": "amount"},
        ),
    )

    unrestricted = await kpis.compute("portfolio_bid_value", session, allowed_project_ids=None)
    assert unrestricted.value >= Decimal("9000")

    permitted = await kpis.compute(
        "portfolio_bid_value",
        session,
        allowed_project_ids={project_id},
    )
    assert permitted.value == pytest.approx(Decimal("9000"), abs=Decimal("0.01"))

    blind = await kpis.compute("portfolio_bid_value", session, allowed_project_ids=set())
    assert blind.value == Decimal("0")
    assert blind.source_record_count == 0

    stranger = await kpis.compute(
        "portfolio_bid_value",
        session,
        allowed_project_ids={uuid.uuid4()},
    )
    assert stranger.value == Decimal("0")


@pytest.mark.asyncio
async def test_a_code_with_neither_formula_nor_spec_still_reads_zero(session: AsyncSession) -> None:
    """The pre-existing contract for a misconfigured widget is unchanged."""
    result = await kpis.compute("no_such_kpi_anywhere", session)
    assert result.value == Decimal("0")
    assert result.source_record_count == 0


# ── Starter pack isolation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_starter_pack_reinstall_leaves_custom_definitions_intact(
    session: AsyncSession,
) -> None:
    """Reinstalling the 35 built-ins must not touch a user's own KPI.

    The starter pack upserts by code and only ever names the codes it
    owns, so the isolation is structural rather than a flag anybody has to
    remember to check. This test is what keeps it structural.
    """
    from app.modules.bi_dashboards.seed import seed_all

    service = BIDashboardsService(session)
    await service.bootstrap_system_kpis()

    created = await service.create_custom_kpi(_weighted_confidence_payload())
    custom_id = created.id

    await seed_all(session)
    await seed_all(session)

    row = await service.repo.get_kpi_definition_by_code("bid_confidence")
    assert row is not None
    assert row.id == custom_id
    assert row.is_system is False
    assert row.spec_json["aggregation"] == "weighted_avg"
    assert row.spec_json["weight_field"] == "amount"

    # And the built-ins are still marked as such, so the two populations
    # stay separable after the reinstall.
    systems = (
        (await session.execute(select(KPIDefinition.code).where(KPIDefinition.is_system.is_(True)))).scalars().all()
    )
    assert "cpi" in systems
    assert "bid_confidence" not in systems


# ── Deletion ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_is_refused_while_a_widget_points_at_the_kpi(
    session: AsyncSession,
) -> None:
    """Nothing in the schema stops the delete, so the service does.

    ``DashboardWidget.kpi_code`` is a plain string with no foreign key -
    it has to be, because a code may equally be served by a Python formula
    that owns no row. Letting the definition go would leave the tile
    rendering a permanent zero that looks exactly like a measurement.
    """
    from app.modules.bi_dashboards.schemas import DashboardCreate

    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())

    dashboard = await service.create_dashboard(
        DashboardCreate(name="Bids", scope="personal"),
        owner_user_id=OWNER_ID,
    )
    widget = DashboardWidget(
        dashboard_id=dashboard.id,
        widget_type="kpi_card",
        kpi_code="bid_confidence",
    )
    session.add(widget)
    await session.flush()

    with pytest.raises(CustomKPIInUse) as exc_info:
        await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))
    assert exc_info.value.referrers["widgets"] == [widget.id]
    assert exc_info.value.referrers["alerts"] == []
    assert str(widget.id) not in str(exc_info.value)  # the message counts, the payload names
    assert "1 widget(s)" in str(exc_info.value)

    # Still there, still computable.
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is not None

    # Repointing the widget releases the KPI.
    widget.kpi_code = "cpi"
    await session.flush()
    await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is None


@pytest.mark.asyncio
async def test_delete_is_refused_while_an_alert_rule_points_at_the_kpi(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.models import AlertRule

    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    alert = AlertRule(
        name="Bid confidence dropped",
        kpi_code="bid_confidence",
        condition="below",
        threshold_value=Decimal("0.6"),
    )
    session.add(alert)
    await session.flush()

    with pytest.raises(CustomKPIInUse) as exc_info:
        await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))
    assert exc_info.value.referrers["alerts"] == [alert.id]


@pytest.mark.asyncio
async def test_delete_refuses_a_builtin_definition(session: AsyncSession) -> None:
    service = BIDashboardsService(session)
    await service.bootstrap_system_kpis()
    with pytest.raises(CustomKPIIsSystem):
        await service.delete_custom_kpi("cpi", user_id=str(OWNER_ID))
    assert await service.repo.get_kpi_definition_by_code("cpi") is not None


@pytest.mark.asyncio
async def test_deleted_custom_kpi_stops_computing(session: AsyncSession) -> None:
    project_id, _a, _b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    assert (await kpis.compute("bid_confidence", session, project_id=project_id)).source_record_count == 3

    await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))
    after = await kpis.compute("bid_confidence", session, project_id=project_id)
    assert after.value == Decimal("0")
    assert after.source_record_count == 0


# ── Reach: the surfaces the reporter named ─────────────────────────────


async def _dashboard_with_custom_widget(
    session: AsyncSession,
    service: BIDashboardsService,
    widget_type: str,
) -> tuple[uuid.UUID, DashboardWidget]:
    from app.modules.bi_dashboards.schemas import DashboardCreate

    dashboard = await service.create_dashboard(
        DashboardCreate(name=f"Bids {widget_type}", scope="personal"),
        owner_user_id=OWNER_ID,
    )
    widget = DashboardWidget(
        dashboard_id=dashboard.id,
        widget_type=widget_type,
        kpi_code="bid_confidence",
    )
    session.add(widget)
    await session.flush()
    return dashboard.id, widget


@pytest.mark.asyncio
async def test_custom_kpi_reaches_a_kpi_card_widget(session: AsyncSession) -> None:
    """Surface 1 of 3 - a rendered kpi_card carries the custom value."""
    project_id, _a, _b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    dashboard_id, widget = await _dashboard_with_custom_widget(session, service, "kpi_card")

    rendered = await service.render_dashboard(dashboard_id, allowed_project_ids={project_id})

    assert rendered is not None
    tile = next(w for w in rendered.widgets if w.widget.id == widget.id)
    assert tile.value == pytest.approx(Decimal("0.45"), abs=Decimal("0.0001"))
    assert tile.unit == "ratio"
    assert tile.breakdown != {}


@pytest.mark.asyncio
async def test_custom_kpi_reaches_a_chart_widget_headline_and_series(
    session: AsyncSession,
) -> None:
    """Surface 2 of 3, with the caveat the code actually carries.

    A chart's headline value comes from ``kpis.compute`` and works at
    once. Its ``series`` does not: ``evaluate_dashboard`` reads the series
    from stored ``KPIValue`` history, so it is empty until something has
    persisted a point. That is not a custom-KPI limitation - a built-in
    with no history behaves identically - but it does mean a custom chart
    looks flat until the KPI has been computed with ``persist=True`` at
    least once.
    """
    project_id, _a, _b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    dashboard_id, widget = await _dashboard_with_custom_widget(session, service, "line_chart")

    first = await service.evaluate_dashboard(dashboard_id, allowed_project_ids={project_id})
    assert first is not None
    chart = next(w for w in first.widgets if w.id == widget.id)
    assert chart.value == pytest.approx(Decimal("0.45"), abs=Decimal("0.0001"))
    assert chart.series == []

    await service.compute_kpi(
        "bid_confidence",
        project_id=project_id,
        persist=True,
        include_trend=False,
        include_benchmark=False,
    )

    second = await service.evaluate_dashboard(dashboard_id, allowed_project_ids={project_id})
    assert second is not None
    chart = next(w for w in second.widgets if w.id == widget.id)
    assert len(chart.series) == 1
    assert Decimal(chart.series[0]["value"]) == pytest.approx(Decimal("0.45"), abs=Decimal("0.0001"))


@pytest.mark.asyncio
async def test_custom_kpi_reaches_an_alert_rule(session: AsyncSession) -> None:
    """Surface 3 of 3 - a threshold alert fires on the custom value."""
    from app.modules.bi_dashboards.models import AlertRule

    project_id, _a, _b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())

    below = AlertRule(
        name="Bid confidence below 0.6",
        kpi_code="bid_confidence",
        condition="below",
        threshold_value=Decimal("0.6"),
        scope_project_id=project_id,
        throttle_seconds=0,
    )
    above = AlertRule(
        name="Bid confidence above 0.9",
        kpi_code="bid_confidence",
        condition="above",
        threshold_value=Decimal("0.9"),
        scope_project_id=project_id,
        throttle_seconds=0,
    )
    session.add_all([below, above])
    await session.flush()

    # 0.45 is below 0.6 and not above 0.9 - the rule reads the real value
    # rather than the zero an unresolved code would have produced.
    assert await service.evaluate_alert(below) is True
    assert await service.evaluate_alert(above) is False


@pytest.mark.asyncio
async def test_custom_kpi_reaches_a_report_run(session: AsyncSession) -> None:
    """Not one of the three named, but the same entry point serves it."""
    from app.modules.bi_dashboards.schemas import ReportDefinitionCreate

    project_id, _a, _b = await _seed_two_bids(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    report = await service.create_report(
        ReportDefinitionCreate(
            code=f"bids_{uuid.uuid4().hex[:6]}",
            name="Bid confidence",
            query_spec_json={"kpis": ["bid_confidence"], "project_id": str(project_id)},
            output_format="csv",
        ),
        owner_user_id=OWNER_ID,
    )

    run = await service.run_report(report.id, produce_file=False)
    assert run is not None
    row = next(r for r in run.rows if r["kpi_code"] == "bid_confidence")
    assert Decimal(row["value"]) == pytest.approx(Decimal("0.45"), abs=Decimal("0.0001"))


# ── Deletion: the referrers a scalar column cannot see ─────────────────


async def _report_naming_kpis(
    session: AsyncSession,
    service: BIDashboardsService,
    codes: list[str],
    **extra_spec: Any,
) -> Any:
    """A report definition whose query spec runs the given KPI codes."""
    from app.modules.bi_dashboards.schemas import ReportDefinitionCreate

    return await service.create_report(
        ReportDefinitionCreate(
            code=f"rep_{uuid.uuid4().hex[:8]}",
            name="Monthly client pack",
            query_spec_json={"kpis": codes, **extra_spec},
            output_format="pdf",
        ),
        owner_user_id=OWNER_ID,
    )


@pytest.mark.asyncio
async def test_delete_is_refused_while_a_report_definition_runs_the_kpi(
    session: AsyncSession,
) -> None:
    """The report is the referrer whose failure reaches a client.

    ``run_report`` reads ``query_spec_json["kpis"]`` and hands every code
    to ``kpis.compute``, so a definition deleted out from under it does
    not break the run - it prints 0.0000 into a client-facing PDF, which
    is worse. The delete has to see the report, and the refusal has to
    name it: a message that counts widgets and alerts only would report
    "0 widget(s) and 0 alert rule(s)" while refusing.
    """
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    report = await _report_naming_kpis(session, service, ["cpi", "bid_confidence"])

    with pytest.raises(CustomKPIInUse) as exc_info:
        await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))

    assert exc_info.value.referrers["reports"] == [report.id]
    assert exc_info.value.referrers["widgets"] == []
    assert exc_info.value.referrers["alerts"] == []
    # The refusal has to say what is holding the KPI, and must not claim
    # the two kinds that are not.
    assert "1 report definition(s)" in str(exc_info.value)
    assert "widget(s)" not in str(exc_info.value)
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is not None

    # Dropping the code from the report releases the KPI.
    report.query_spec_json = {"kpis": ["cpi"]}
    await session.flush()
    await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is None


@pytest.mark.asyncio
async def test_delete_is_refused_while_a_composite_alert_expression_reads_the_kpi(
    session: AsyncSession,
) -> None:
    """A composite rule reads its KPI from the tree, not from the column.

    ``expression_json`` takes precedence over ``condition`` /
    ``threshold_value`` when it is non-empty, and its ``kpi`` leaf may sit
    at any depth. This rule's ``kpi_code`` column names a built-in, so
    nothing but the tree walk can find it - and the leaf is two levels
    down, so a check that only looked at the root would miss it too.
    """
    from app.modules.bi_dashboards.models import AlertRule

    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    rule = AlertRule(
        name="Weak bid in an executing project",
        kpi_code="cpi",
        condition="below",
        threshold_value=Decimal("0.95"),
        expression_json={
            "op": "and",
            "operands": [
                {"op": "field", "source": "project", "path": "phase", "compare": "eq", "value": "execution"},
                {
                    "op": "or",
                    "operands": [
                        {"op": "kpi", "code": "cpi", "compare": "lt", "value": "0.95"},
                        {"op": "kpi", "code": "bid_confidence", "compare": "lt", "value": "0.5"},
                    ],
                },
            ],
        },
    )
    session.add(rule)
    await session.flush()

    with pytest.raises(CustomKPIInUse) as exc_info:
        await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))

    assert exc_info.value.referrers["alerts"] == [rule.id]
    assert "1 alert rule(s)" in str(exc_info.value)
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is not None


@pytest.mark.asyncio
async def test_an_alert_naming_the_kpi_twice_is_counted_once(
    session: AsyncSession,
) -> None:
    """The column and the tree can name the same code; the rule is one rule."""
    from app.modules.bi_dashboards.models import AlertRule

    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    rule = AlertRule(
        name="Bid confidence, both ways",
        kpi_code="bid_confidence",
        condition="below",
        threshold_value=Decimal("0.5"),
        expression_json={
            "op": "not",
            "operands": [{"op": "kpi", "code": "bid_confidence", "compare": "gte", "value": "0.5"}],
        },
    )
    session.add(rule)
    await session.flush()

    referrers = await service.repo.list_kpi_code_referrers("bid_confidence")
    assert referrers["alerts"] == [rule.id]
    assert "1 alert rule(s)" in str(CustomKPIInUse("bid_confidence", referrers))


@pytest.mark.asyncio
async def test_a_code_that_is_only_mentioned_does_not_block_the_delete(
    session: AsyncSession,
) -> None:
    """The scan is structural, so a textual mention is not a reference.

    Both JSON columns are narrowed by a LIKE over their text, which is a
    prefilter and nothing more. If the confirmation step were dropped -
    or written as a substring test - every one of these rows would count
    as a referrer and the KPI would become undeletable for reasons its
    owner could never act on. Each row here contains the exact string
    ``"bid_confidence"`` inside its JSON and none of them reads the KPI.
    """
    from app.modules.bi_dashboards.models import AlertRule

    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())

    # A report that names the code somewhere other than its kpis list.
    await _report_naming_kpis(session, service, ["cpi"], title="bid_confidence over time")
    # An alert comparing a project field against the code as a string.
    session.add(
        AlertRule(
            name="Not a KPI reference",
            kpi_code="cpi",
            condition="below",
            threshold_value=Decimal("1"),
            expression_json={
                "op": "field",
                "source": "project",
                "path": "phase",
                "compare": "eq",
                "value": "bid_confidence",
            },
        ),
    )
    # A code the prefilter must not confuse with ours in either direction.
    await service.create_custom_kpi(_weighted_confidence_payload("bid_confidence_v2"))
    await _report_naming_kpis(session, service, ["bid_confidence_v2"])
    await session.flush()

    referrers = await service.repo.list_kpi_code_referrers("bid_confidence")
    assert referrers == {"widgets": [], "alerts": [], "reports": []}
    await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is None
    # The neighbour is untouched and still guarded by its own report.
    with pytest.raises(CustomKPIInUse):
        await service.delete_custom_kpi("bid_confidence_v2", user_id=str(OWNER_ID))


# ── Filter values: the kinds that are not numeric ──────────────────────


def _count_payload(code: str, entity: str, filters: list[dict[str, Any]]) -> KPIDefinitionCreate:
    return KPIDefinitionCreate(
        code=code,
        name="Counted with a filter",
        unit="count",
        category="operational",
        spec={"entity": entity, "aggregation": "count", "filters": filters},
    )


@pytest.mark.parametrize(
    ("entity", "filter_item", "expected_path"),
    [
        # ``isinstance(True, int)`` is True, so a flag walked straight
        # through the numeric check and became ``Decimal("True")``.
        ("boq_position", {"field": "quantity", "op": "gt", "value": True}, "spec.filters[0].value"),
        # A boolean field had no value check at all; the driver refuses
        # to encode 'yes' for a boolean parameter.
        ("boq", {"field": "is_locked", "op": "eq", "value": "yes"}, "spec.filters[0].value"),
        ("boq", {"field": "is_locked", "op": "eq", "value": 1}, "spec.filters[0].value"),
        # A text column compared against a number.
        ("boq_position", {"field": "unit", "op": "eq", "value": 3}, "spec.filters[0].value"),
        # An id that is not one matches no row, so the KPI reads zero.
        ("boq_position", {"field": "boq_id", "op": "eq", "value": "not-a-uuid"}, "spec.filters[0].value"),
    ],
)
def test_a_filter_value_outside_its_field_kind_is_refused(
    entity: str,
    filter_item: dict[str, Any],
    expected_path: str,
) -> None:
    """Every kind gets a value check, not just the numeric one.

    Each of these was accepted at creation and died at compute time, and
    the compute path catches everything and returns an empty computation.
    So the definition stayed in the table and the tile read zero forever -
    indistinguishable from a real measurement of nothing.
    """
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {"entity": entity, "aggregation": "count", "filters": [filter_item]},
        )
    assert exc_info.value.path == expected_path
    assert exc_info.value.value == filter_item["value"]


@pytest.mark.parametrize(
    "value",
    ["NaN", "nan", "sNaN", "Infinity", "-Infinity", float("nan"), float("inf")],
)
def test_a_numeric_filter_value_that_is_not_finite_is_refused(value: Any) -> None:
    """A number arithmetic cannot use is worse than one that is not a number.

    ``Decimal`` parses every spelling below, and ``json.loads`` accepts
    the bare ``NaN`` and ``Infinity`` tokens, so all of them walked
    through the numeric check. Each then failed in a way nothing reports:
    a comparison against NaN is never true and the filter keeps no row, an
    infinity empties it from the other end, and ``sNaN`` raises inside the
    compute path, which catches everything and returns an empty
    computation. Three spellings, one symptom - a tile reading zero
    forever, indistinguishable from a real measurement of nothing.
    """
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "count",
                "filters": [{"field": "quantity", "op": "gt", "value": value}],
            },
        )
    assert exc_info.value.path == "spec.filters[0].value"
    assert "finite" in str(exc_info.value)


def test_an_in_list_cannot_smuggle_a_non_finite_number() -> None:
    """A list is not a way past the finiteness check either."""
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "count",
                "filters": [{"field": "quantity", "op": "in", "value": [1, "Infinity"]}],
            },
        )
    assert exc_info.value.path == "spec.filters[0].value[1]"


def test_an_in_list_is_type_checked_member_by_member() -> None:
    """A list is not a way past the check its scalar sibling gets."""
    with pytest.raises(kpi_spec.KPISpecError) as exc_info:
        kpi_spec.validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "count",
                "filters": [{"field": "boq_id", "op": "in", "value": [str(uuid.uuid4()), "not-a-uuid"]}],
            },
        )
    assert exc_info.value.path == "spec.filters[0].value[1]"


def test_the_values_each_kind_does_accept_survive_validation() -> None:
    """The counterweight: a check that refused everything would be worse.

    A numeric field keeps taking a numeric string, because
    ``_apply_filters`` coerces one and that path works. A UUID comes back
    in its canonical spelling: an uppercase id is equally valid input and
    would have matched no row at all, which is the same silent zero by a
    different route.
    """
    ident = uuid.uuid4()
    spec = kpi_spec.validate_spec(
        {
            "entity": "boq_position",
            "aggregation": "count",
            "filters": [
                {"field": "confidence", "op": "lt", "value": "0.5"},
                {"field": "quantity", "op": "gte", "value": 3},
                {"field": "unit", "op": "in", "value": ["m3", "m2"]},
                {"field": "boq_id", "op": "eq", "value": str(ident).upper()},
                {"field": "parent_id", "op": "is_null"},
            ],
        },
    )
    assert [f["value"] for f in spec["filters"]] == ["0.5", 3, ["m3", "m2"], str(ident), None]

    bool_spec = kpi_spec.validate_spec(
        {
            "entity": "boq",
            "aggregation": "count",
            "filters": [{"field": "is_locked", "op": "eq", "value": False}],
        },
    )
    assert bool_spec["filters"][0]["value"] is False


@pytest.mark.asyncio
async def test_an_accepted_filter_value_actually_computes(session: AsyncSession) -> None:
    """The check is only right if what survives it reaches a real number.

    Validation is a claim about the database, so it is worth one round
    trip: these are the two kinds that had no check, run against the real
    driver on the real column types. A bool bound to a boolean column and
    an id bound to an id column both have to come back with a count.
    """
    project_id, bid_a, _b = await _seed_two_bids(session)
    service = BIDashboardsService(session)

    await service.create_custom_kpi(
        _count_payload("open_bids", "boq", [{"field": "is_locked", "op": "eq", "value": False}])
    )
    await service.create_custom_kpi(
        _count_payload(
            "lines_of_bid_a", "boq_position", [{"field": "boq_id", "op": "eq", "value": str(bid_a).upper()}]
        ),
    )

    open_bids = await kpis.compute("open_bids", session, project_id=project_id)
    assert open_bids.value == Decimal("2")

    lines = await kpis.compute("lines_of_bid_a", session, project_id=project_id)
    assert lines.value == Decimal("2")


# ── Deletion: the project the KPI belongs to ───────────────────────────


async def _stranger_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A project owned by somebody who is not ``OWNER_ID``.

    Returns ``(project_id, stranger_user_id)``. The owner is a real user
    row with the default ``editor`` role - ``verify_project_access`` lets
    an admin through unconditionally, so an admin on either side of this
    would make the test pass for a reason that is not the fix.
    """
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    stranger_id = uuid.uuid4()
    session.add(
        User(
            id=stranger_id,
            email=f"stranger-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="S",
        ),
    )
    await session.flush()
    project_id = uuid.uuid4()
    session.add(
        Project(id=project_id, name="Somebody else's job", owner_id=stranger_id, currency="EUR"),
    )
    await session.flush()
    return project_id, stranger_id


@pytest.mark.asyncio
async def test_delete_refuses_a_caller_who_cannot_reach_the_project(
    session: AsyncSession,
) -> None:
    """Create checks the project it pins to; delete has to check it too.

    KPI codes are globally unique, so a definition pinned to a project is
    reachable by code alone from anywhere. Without this check any holder
    of ``bi.kpi.write`` could delete another project's KPI - the write
    permission was doing the work of a tenancy boundary.
    """
    from fastapi import HTTPException

    project_id, _stranger = await _stranger_project(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload(project_id=project_id))

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))
    assert exc_info.value.status_code == 404
    # The project is what was refused, not the KPI - a 404 raised for the
    # other reason would pass a bare status-code assertion.
    assert exc_info.value.detail == "Project not found"
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is not None


@pytest.mark.asyncio
async def test_the_projects_own_people_can_still_delete_its_kpi(
    session: AsyncSession,
) -> None:
    """The counterweight - a check that refused everyone would be worse."""
    project_id, stranger_id = await _stranger_project(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload(project_id=project_id))

    await service.delete_custom_kpi("bid_confidence", user_id=str(stranger_id))
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is None


@pytest.mark.asyncio
async def test_a_company_wide_kpi_needs_no_project_to_be_deleted(
    session: AsyncSession,
) -> None:
    """A definition pinned to nothing is nobody's project to check."""
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload())
    await service.delete_custom_kpi("bid_confidence", user_id=str(uuid.uuid4()))
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is None


@pytest.mark.asyncio
async def test_an_unreachable_project_hides_whether_the_kpi_is_in_use(
    session: AsyncSession,
) -> None:
    """Order matters: the access answer comes before the referrer answer.

    Run the other way round, a caller outside the project would get a 409
    naming the widgets and alert rules that hold the KPI - ids from a
    project they were just told they cannot see.
    """
    from fastapi import HTTPException

    from app.modules.bi_dashboards.schemas import DashboardCreate

    project_id, _stranger = await _stranger_project(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload(project_id=project_id))
    dashboard = await service.create_dashboard(
        DashboardCreate(name="Theirs", scope="personal"),
        owner_user_id=OWNER_ID,
    )
    session.add(DashboardWidget(dashboard_id=dashboard.id, widget_type="kpi_card", kpi_code="bid_confidence"))
    await session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_custom_kpi("bid_confidence", user_id=str(OWNER_ID))
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Project not found"


@pytest.mark.asyncio
async def test_the_delete_route_hands_the_caller_to_the_service(
    session: AsyncSession,
) -> None:
    """The check lives in the service, so the route has to supply the caller.

    ``user_id`` is a required keyword argument there, which turns a route
    that forgets it into a loud TypeError rather than a silent bypass -
    but only if something actually calls the route. Nothing else in this
    module's tests does, so the wiring is exercised here, in both
    directions: refused for an outsider, and through for the owner.
    """
    from fastapi import HTTPException

    from app.modules.bi_dashboards.router import delete_kpi

    project_id, stranger_id = await _stranger_project(session)
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_weighted_confidence_payload(project_id=project_id))

    with pytest.raises(HTTPException) as exc_info:
        await delete_kpi("bid_confidence", str(OWNER_ID), session, service)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Project not found"

    await delete_kpi("bid_confidence", str(stranger_id), session, service)
    assert await service.repo.get_kpi_definition_by_code("bid_confidence") is None
