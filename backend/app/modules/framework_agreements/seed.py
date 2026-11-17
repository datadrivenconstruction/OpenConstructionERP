# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo framework agreements: the three worked examples of the domain spec, one per demo project.

* residential-berlin: gas house connections for a municipal utility (DE), index-linked from
  2026, the agreement at 96.20 % of its cap after order A-2026-0147.
* office-london: water network term contract (GB), Task Order TO-0231 with an approved extra.
* medical-us: IDIQ job order contract (US), 17 issued orders and TO-0007 held as a draft that
  the cap blocks.

Demo estate only (``demo_id`` in the project metadata) and once per project: a project that
already holds a framework agreement is left alone. Every price is built with the same
functions an order uses, so the seeded orders read exactly as a typed one would.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal as D
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_commercial import is_demo_project
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.framework_agreements import pricing
from app.modules.framework_agreements.models import FrameworkAdjustment, FrameworkRateItem, FrameworkRatePeriod

logger = logging.getLogger(__name__)

_DE_SERIES = "DE Destatis road and civil works price index (demo sample)"


@dataclass
class _Item:
    code: str
    description: str
    unit: str
    rate: D
    flags: tuple[str, ...] = ()
    max_qty: D | None = None
    est: D | None = None


@dataclass
class _Order:
    code: str
    ordered_at: date
    site: str
    lines: list[tuple[str, D]]
    tags: list[str] = field(default_factory=list)
    status: str = "issued"
    measured: bool = False
    claim: str | None = None
    extra: tuple[str, D] | None = None


@dataclass
class _Story:
    demo_id: str
    code: str
    title: str
    client: str
    currency: str
    start: date
    end: date
    cap: D
    minimum: D | None
    rounding: str
    pattern: str
    items: list[_Item]
    adjustments: list[dict[str, Any]]
    period: dict[str, Any]
    orders: list[_Order]
    target_committed: D | None = None
    filler_site: str = ""
    filler_date: date | None = None
    filler_code: str = ""
    pack_values: dict[str, Any] = field(default_factory=dict)


def _de_story() -> _Story:
    items = [
        _Item(
            "01.010",
            "Hausanschluss Gas DN32 PE bis 10 m, komplett",
            "St",
            D("1850.00"),
            max_qty=D("2100"),
            est=D("1900"),
        ),
        _Item("01.020", "Mehrlänge Rohrgraben Hausanschluss", "m", D("96.50"), est=D("9000")),
        _Item("01.030", "Asphaltwiederherstellung Gehweg und Fahrbahn", "m2", D("78.40"), est=D("14000")),
        _Item("01.040", "Kernbohrung und Mauerdurchführung", "St", D("312.00"), est=D("1900")),
        _Item("01.050", "Pflasterarbeiten Gehweg, Wiederherstellung", "m2", D("64.20"), est=D("6000")),
    ]
    sites = ["Hauptstr. 12", "Lindenweg 3", "Bahnhofstr. 40", "Gartenstr. 7", "Schillerplatz 2"]
    orders: list[_Order] = []
    # 2025: fixed prices, one collective call-off per new estate street block plus single connections.
    for i in range(1, 25):
        month = 1 + (i - 1) // 2
        site = sites[i % len(sites)]
        orders.append(
            _Order(
                f"A-2025-{i:04d}",
                date(2025, month, 6 + (i % 2) * 12),
                site,
                [
                    ("01.010", D("1")),
                    ("01.020", D(str(4 + i % 9))),
                    ("01.030", D(str(10 + i % 13))),
                    ("01.040", D("1")),
                ],
                tags=["weekend"] if i % 7 == 0 else [],
                measured=i <= 20,
                claim="certified" if i <= 18 else None,
            )
        )
    # 2026: index-linked; the agreement project's own street.
    for n, seq in enumerate(range(133, 147)):
        month = 1 + n // 5
        orders.append(
            _Order(
                f"A-2026-{seq:04d}",
                date(2026, month, 3 + (n % 5) * 5),
                sites[n % len(sites)],
                [("01.010", D("1")), ("01.020", D(str(6 + n % 8))), ("01.030", D(str(12 + n % 10)))],
                tags=["weekend"] if n % 6 == 0 else [],
                measured=n in (1, 4, 7),
                claim="certified" if n in (1, 4) else None,
                extra=("Leitungskreuzung Telekom, Handschachtung", D("845.00")) if n == 7 else None,
            )
        )
    orders.append(
        _Order(
            "A-2026-0147",
            date(2026, 3, 12),
            "Hauptstr. 12",
            [("01.010", D("1")), ("01.020", D("14")), ("01.030", D("22"))],
            tags=["weekend"],
        )
    )
    orders.append(
        _Order(
            "A-2026-0148", date(2026, 3, 20), "Lindenweg 3", [("01.010", D("1")), ("01.020", D("8"))], status="draft"
        )
    )
    return _Story(
        demo_id="residential-berlin",
        code="A",
        title="Rahmenvertrag Hausanschlüsse Gas 2025-2028",
        client="Stadtwerke Musterstadt",
        currency="EUR",
        start=date(2025, 1, 1),
        end=date(2028, 12, 31),
        cap=D("4000000.00"),
        minimum=D("1000000.00"),
        rounding="per_rate",
        pattern="{agreement}-{yyyy}-{seq4}",
        items=items,
        adjustments=[
            {
                "code": "WE",
                "label": "Wochenendzuschlag",
                "kind": "multiplier",
                "value": D("1.15"),
                "condition": "weekend",
            },
            {
                "code": "NA",
                "label": "Nachtarbeit",
                "kind": "multiplier",
                "value": D("1.25"),
                "condition": "out_of_hours",
            },
        ],
        period={
            "label": "2025-01",
            "method": "index_ratio",
            "base_period": "2025-01",
            "fixed_price_until": date(2025, 12, 31),
            "series_refs": [{"series": _DE_SERIES}],
        },
        orders=orders,
        target_committed=D("3842150.00"),
        filler_site="Neubaugebiet Am Mühlbach",
        filler_date=date(2025, 6, 2),
        filler_code="A-2025-0100",
        pack_values={"leitweg_id": "991-12345-67", "measurement_preset": "REB 23.003"},
    )


def _uk_story() -> _Story:
    items = [
        _Item("PL-101", "Burst main repair up to 150 mm", "nr", D("1240.00"), flags=("out_of_hours",)),
        _Item("PL-102", "Valve replacement up to 150 mm", "nr", D("980.00"), flags=("out_of_hours",)),
        _Item("PL-205", "Carriageway reinstatement", "m2", D("112.60")),
        _Item("PL-220", "Footway reinstatement", "m2", D("74.30")),
        _Item("PL-310", "Two-way traffic signals", "day", D("385.00")),
    ]
    roads = ["Victoria Road", "Mill Lane", "Station Approach", "Church Street"]
    orders = [
        _Order(
            f"TO-{seq:04d}",
            date(2026, 5 + (seq - 220) // 3, 4 + (seq % 3) * 7),
            roads[seq % len(roads)],
            [("PL-101" if seq % 2 else "PL-102", D("1")), ("PL-205", D(str(3 + seq % 5))), ("PL-310", D("1"))],
            tags=["out_of_hours"] if seq % 4 == 0 else [],
            measured=seq < 226,
            claim="certified" if seq < 224 else None,
        )
        for seq in range(220, 231)
    ]
    orders.append(
        _Order(
            "TO-0231",
            date(2026, 9, 14),
            "High Street",
            [("PL-101", D("1")), ("PL-205", D("6.5")), ("PL-310", D("2"))],
            tags=["out_of_hours"],
            measured=True,
            extra=("Unrecorded telecom duct: 6 h gang at 68.00, materials 214.00, fee 12 %", D("696.64")),
        )
    )
    return _Story(
        demo_id="office-london",
        code="TC-WN",
        title="Water network repairs term contract 2024-2028",
        client="Thames Valley Water",
        currency="GBP",
        start=date(2024, 4, 1),
        end=date(2028, 3, 31),
        cap=D("1500000.00"),
        minimum=None,
        rounding="per_rate",
        pattern="TO-{seq4}",
        items=items,
        adjustments=[
            {
                "code": "OOH",
                "label": "Out of hours",
                "kind": "multiplier",
                "value": D("1.30"),
                "scope": "flagged",
                "condition": "out_of_hours",
            },
        ],
        period={"label": "Price List 2024", "method": "none"},
        orders=orders,
        pack_values={"price_list_reference": "PL-2024 rev B", "tendered_percentage": "-4.5"},
    )


def _us_story() -> _Story:
    items = [
        _Item("31 23 16.13", "Trench excavation, 4 ft deep, common earth", "CY", D("14.20")),
        _Item("33 14 13.15", "Ductile iron water pipe, 8 in, mechanical joint", "LF", D("68.50")),
        _Item("32 12 16.13", "Asphalt paving, 3 in, base course", "SY", D("31.75")),
        _Item("03 30 53.40", "Cast-in-place concrete, pads and curbs", "CY", D("612.00")),
        _Item("26 56 13.10", "Site lighting pole, 20 ft, with base", "EA", D("4850.00")),
    ]
    orders = []
    for seq in [*range(1, 7), *range(8, 19)]:
        orders.append(
            _Order(
                f"TO-{seq:04d}",
                date(2025, 1 + seq % 12, 9),
                f"Campus building {chr(64 + seq % 6 + 1)}",
                [
                    ("31 23 16.13", D(str(300 + seq * 10))),
                    ("33 14 13.15", D(str(200 + seq * 15))),
                    ("32 12 16.13", D("180")),
                ],
                tags=["normal_hours"],
                measured=seq < 12,
                claim="certified" if seq < 10 else None,
            )
        )
    orders.append(
        _Order(
            "TO-0007",
            date(2026, 10, 20),
            "Campus building G",
            [("31 23 16.13", D("420")), ("33 14 13.15", D("360")), ("32 12 16.13", D("210"))],
            tags=["normal_hours"],
            status="draft",
        )
    )
    return _Story(
        demo_id="medical-us",
        code="IDIQ-JOC",
        title="Job order contract, medical campus IDIQ",
        client="State University Health System",
        currency="USD",
        start=date(2025, 1, 1),
        end=date(2029, 12, 31),
        cap=D("5000000.00"),
        minimum=D("250000.00"),
        rounding="per_total",
        pattern="TO-{seq4}",
        items=items,
        adjustments=[
            {
                "code": "NH",
                "label": "Normal hours coefficient",
                "kind": "multiplier",
                "value": D("1.0850"),
                "condition": "normal_hours",
            },
            {
                "code": "OTN",
                "label": "Other than normal hours coefficient",
                "kind": "multiplier",
                "value": D("1.2350"),
                "condition": "other_than_normal_hours",
            },
        ],
        period={"label": "Unit price book 2025", "method": "none"},
        orders=orders,
        target_committed=D("4968000.00"),
        filler_site="Campus central plant",
        filler_date=date(2025, 6, 30),
        filler_code="TO-0019",
        pack_values={"joc_coefficients": {"normal_hours": "1.0850", "other_than_normal_hours": "1.2350"}},
    )


_STORIES = {s.demo_id: s for s in (_de_story(), _uk_story(), _us_story())}


def _de_index_points() -> dict[str, D]:
    """Monthly sample points: 118.4 in 2025-01, 123.1 in 2026-03 (the worked example), then on."""
    points: dict[str, D] = {}
    step = (D("123.1") - D("118.4")) / 14
    for n in range(0, 24):
        year, month = 2025 + n // 12, 1 + n % 12
        points[f"{year:04d}-{month:02d}"] = (D("118.4") + step * n).quantize(D("0.1"))
    points["2025-01"], points["2026-03"] = D("118.4"), D("123.1")
    return points


# Contracts seeding skips contracts carrying this marker, so a reinstall does not backfill
# claims and lines into agreements and orders this seeder already completed.
DEMO_SEED_MARKER = "framework_agreements_demo"


async def _ensure_series(session: AsyncSession) -> None:
    from app.modules.price_index.models import CostIndexPoint, CostIndexSeries

    found = (
        await session.execute(select(CostIndexSeries).where(CostIndexSeries.name == _DE_SERIES))
    ).scalar_one_or_none()
    if found is not None:
        return
    series = CostIndexSeries(
        name=_DE_SERIES,
        description=(
            "Producer price index for road and civil works in Germany, shaped like the Destatis series; "
            "load the published figures before indexing a live contract."
        ),
    )
    session.add(series)
    await session.flush()
    session.add_all(CostIndexPoint(series_id=series.id, period=p, factor=v) for p, v in _de_index_points().items())


def _price(story: _Story, order: _Order, items: dict[str, FrameworkRateItem]) -> pricing.PricedOrder:
    period = story.period
    factor = pricing.period_factor(
        method=period["method"],
        ordered_at=order.ordered_at,
        base_period=period.get("base_period"),
        fixed_price_until=period.get("fixed_price_until"),
        series_refs=period.get("series_refs") or [],
        fixed_part=None,
        index_points={_DE_SERIES: {k: str(v) for k, v in _de_index_points().items()}},
    ).factor
    specs = [
        pricing.AdjustmentSpec(
            a["code"], a["kind"], a["value"], a.get("scope", "all"), (), None, a.get("condition", "")
        )
        for a in story.adjustments
    ]
    lines = [
        (pricing.ItemSpec(code, items[code].base_rate, tuple(items[code].surcharge_flags or ())), qty)
        for code, qty in order.lines
    ]
    priced = pricing.price_order(lines, factor=factor, adjustments=specs, tags=order.tags, rounding=story.rounding)
    for ln in priced.lines:
        ln.rate_build["period"] = period["label"]
        ln.rate_build["fixed_price"] = bool(
            period.get("fixed_price_until") and order.ordered_at <= period["fixed_price_until"]
        )
    return priced


def _filler(story: _Story, items: dict[str, FrameworkRateItem], remainder: D) -> _Order | None:
    """A collective call-off whose quantities make the issued orders add up to the story's figure.

    Whole units of the first item take the bulk; two metre-measured items with quantities to two
    decimals close the gap to the cent, found by a short deterministic search.
    """
    codes = [i.code for i in items.values()]
    big, a, b = codes[0], codes[1], codes[2]
    probe = _Order(story.filler_code, story.filler_date or story.start, story.filler_site, [], tags=[])

    def total(lines: list[tuple[str, D]]) -> D:
        probe.lines = lines
        return _price(story, probe, items).net

    unit_big = total([(big, D("1"))])
    n_big = int((remainder * D("0.85")) // unit_big)
    rest = remainder - total([(big, D(n_big))])
    unit_b = total([(b, D("1"))])
    for step in range(0, 20000):
        qb = (rest * D("0.3") / unit_b).quantize(D("0.01")) + D(step) / 100
        target_a = rest - total([(b, qb)])
        unit_a = total([(a, D("1"))])
        qa = (target_a / unit_a).quantize(D("0.01"))
        lines = [(big, D(n_big)), (a, qa), (b, qb)]
        if qa > 0 and total(lines) == remainder:
            probe.lines = lines
            return _Order(story.filler_code, probe.ordered_at, probe.site, lines, measured=True, claim="paid")
    logger.warning("framework demo: no exact filler for %s, remainder %s", story.demo_id, remainder)
    return None


async def _write_order(
    session: AsyncSession,
    story: _Story,
    agreement: Contract,
    order: _Order,
    items: dict[str, FrameworkRateItem],
    period_id: uuid.UUID,
) -> tuple[Contract, D]:
    priced = _price(story, order, items)
    extra_value = order.extra[1] if order.extra else D("0")
    issued = order.status != "draft"
    row = Contract(
        code=order.code,
        title=f"{order.code} {order.site}",
        contract_type="call_off",
        counterparty_type="client",
        project_id=agreement.project_id,
        parent_contract_id=agreement.id,
        start_date=order.ordered_at.isoformat(),
        currency=story.currency,
        retention_percent=D("0"),
        status="active" if issued else "draft",
        signed_at=order.ordered_at.isoformat() if issued else None,
        total_value=priced.net + extra_value,
        original_contract_value=priced.net if issued else None,
        terms={
            "order_no": order.code,
            "ordered_at": order.ordered_at.isoformat(),
            "site_label": order.site,
            "tags": order.tags,
            "order_status": "issued" if issued else "draft",
            "rounding": story.rounding,
            "period_label": story.period["label"],
            "demo": True,
        },
        metadata_={"demo_seed": DEMO_SEED_MARKER},
    )
    session.add(row)
    await session.flush()
    measured_value = D("0")
    for i, ln in enumerate(priced.lines):
        item = items[ln.code]
        meta: dict[str, Any] = {"rate_build": {**ln.rate_build, "period_id": str(period_id)}}
        if order.measured:
            # Measured as ordered, except one trench line that ran longer than ordered.
            qty = ln.quantity + (D("2.5") if order.extra and ln.code == story.items[1].code else D("0"))
            meta["measured_qty"] = format(qty, "f")
            measured_value += pricing.round2(qty * ln.unit_rate)
        session.add(
            ContractLine(
                contract_id=row.id,
                code=ln.code,
                description=item.description,
                unit=item.unit,
                quantity=ln.quantity,
                unit_rate=ln.unit_rate,
                total_value=ln.total,
                order_index=i,
                origin="framework_item",
                source_key=f"framework_item:{item.id}@{period_id}",
                original_value=ln.total if issued else None,
                metadata_=meta,
            )
        )
    if order.extra:
        await _write_extra(session, row, order.extra, len(priced.lines))
    if order.claim:
        session.add(
            ProgressClaim(
                contract_id=row.id,
                claim_number="1",
                period_start=order.ordered_at.isoformat(),
                period_end=order.ordered_at.isoformat(),
                claim_date=order.ordered_at.isoformat(),
                period_from=order.ordered_at,
                period_to=order.ordered_at,
                gross_amount=measured_value,
                retention_amount=D("0"),
                prior_claims_total=D("0"),
                net_due=measured_value,
                status=order.claim,
                currency=story.currency,
            )
        )
    return row, row.total_value if issued else D("0")


async def _write_extra(session: AsyncSession, order: Contract, extra: tuple[str, D], index: int) -> None:
    from app.modules.variations.models import VariationRequest

    title, amount = extra
    vr = VariationRequest(
        project_id=order.project_id,
        code=f"VR-{order.code}"[:50],
        title=title,
        classification="extra_item",
        estimated_cost_impact=amount,
        agreed_cost_impact=amount,
        currency=order.currency,
        status="approved",
        metadata_={"contract_id": str(order.id), "framework_order": order.code, "demo": True},
    )
    session.add(vr)
    await session.flush()
    session.add(
        ContractLine(
            contract_id=order.id,
            code=vr.code,
            description=title,
            unit="LS",
            quantity=D("1"),
            unit_rate=amount,
            total_value=amount,
            order_index=index,
            origin="variation",
            source_key=f"variation_request:{vr.id}",
            metadata_={"variation_request_id": str(vr.id)},
        )
    )


async def _seed_story(session: AsyncSession, project_id: uuid.UUID, story: _Story) -> int:
    agreement = Contract(
        code=story.code if not await _code_taken(session, story.code) else f"{story.code}-{str(project_id)[:4]}",
        title=story.title,
        contract_type="framework",
        counterparty_type="client",
        project_id=project_id,
        start_date=story.start.isoformat(),
        end_date=story.end.isoformat(),
        currency=story.currency,
        retention_percent=D("0"),
        status="active",
        signed_at=story.start.isoformat(),
        total_value=story.cap,
        original_contract_value=story.cap,
        terms={
            "client_name": story.client,
            "cap_value": str(story.cap),
            "min_value": str(story.minimum) if story.minimum is not None else None,
            "cap_basis": "committed",
            "threshold_pct": "80",
            "rounding": story.rounding,
            "override_policy": "block",
            "numbering_pattern": story.pattern,
            "client_kind": "classic",
            "pack_values": story.pack_values,
        },
        metadata_={"demo": True, "demo_seed": DEMO_SEED_MARKER},
    )
    session.add(agreement)
    await session.flush()
    items: dict[str, FrameworkRateItem] = {}
    for i, it in enumerate(story.items):
        row = FrameworkRateItem(
            agreement_id=agreement.id,
            code=it.code,
            description=it.description,
            unit=it.unit,
            base_rate=it.rate,
            max_qty=it.max_qty,
            estimated_qty=it.est,
            surcharge_flags=list(it.flags),
            source="manual",
            sort_order=i,
        )
        session.add(row)
        items[it.code] = row
    period = FrameworkRatePeriod(
        agreement_id=agreement.id,
        label=story.period["label"],
        effective_from=story.start,
        effective_to=story.end,
        method=story.period["method"],
        base_period=story.period.get("base_period"),
        fixed_price_until=story.period.get("fixed_price_until"),
        series_refs=story.period.get("series_refs") or [],
    )
    session.add(period)
    for adj in story.adjustments:
        session.add(FrameworkAdjustment(agreement_id=agreement.id, **{"scope": "all", **adj}))
    await session.flush()

    committed = D("0")
    count = 0
    for order in story.orders:
        _row, value = await _write_order(session, story, agreement, order, items, period.id)
        committed += value
        count += 1
    if story.target_committed is not None:
        # The worked example's own order is the last one issued; the agreement stands where it says.
        last = next((o for o in story.orders if o.code in ("A-2026-0147",)), None)
        last_net = _price(story, last, items).net if last else D("0")
        remainder = story.target_committed - (committed - last_net)
        filler = _filler(story, items, remainder) if remainder > 0 else None
        if filler is not None:
            await _write_order(session, story, agreement, filler, items, period.id)
            count += 1
    return count


async def _code_taken(session: AsyncSession, code: str) -> bool:
    return (await session.execute(select(Contract.id).where(Contract.code == code))).first() is not None


async def seed_framework_agreements_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed the three demo framework agreements into their demo projects; the caller commits."""
    from app.modules.projects.models import Project

    counts = {"agreements": 0, "orders": 0}
    ids = list(project_ids)
    if not ids:
        return counts
    rows = (await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(ids)))).all()
    seeded = set(
        (
            await session.execute(
                select(Contract.project_id).where(Contract.project_id.in_(ids), Contract.contract_type == "framework")
            )
        )
        .scalars()
        .all()
    )
    for project_id, metadata in rows:
        if project_id in seeded or not is_demo_project(metadata):
            continue
        story = _STORIES.get(str((metadata or {}).get("demo_id") or ""))
        if story is None:
            continue
        if story.demo_id == "residential-berlin":
            await _ensure_series(session)
        counts["orders"] += await _seed_story(session, project_id, story)
        counts["agreements"] += 1
    await session.flush()
    return counts
