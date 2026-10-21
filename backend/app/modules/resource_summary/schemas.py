# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Pydantic schemas for the Resource Summary API.

Money and quantities are ``Decimal`` and serialise to fixed-precision strings
(money 2dp, quantities 4dp) so a JSON consumer never loses cents or drifts a
takeoff figure through a float. The builders map the pure aggregation dataclasses
(:mod:`app.modules.resource_summary.aggregate`) onto the wire shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.price_breakdown import ResourceKind, kind_i18n_key
from app.modules.resource_summary.aggregate import (
    BuyListItem,
    BuyListSource,
    MaterialBuyList,
    ResourceKindGroup,
    ResourceLine,
    ResourceStatement,
)

_2P = Decimal("0.01")
_4P = Decimal("0.0001")


def _money(value: Decimal) -> str:
    return str(Decimal(value).quantize(_2P, rounding=ROUND_HALF_UP))


def _qty(value: Decimal) -> str:
    return str(Decimal(value).quantize(_4P, rounding=ROUND_HALF_UP))


class ResourceStatementLine(BaseModel):
    """One aggregated procurement line: a distinct resource across the estimate."""

    kind: str
    kind_i18n_key: str
    name: str
    unit: str
    quantity: Decimal
    cost: Decimal
    position_count: int

    @field_serializer("quantity", when_used="json")
    def _ser_quantity(self, v: Decimal) -> str:
        return _qty(v)

    @field_serializer("cost", when_used="json")
    def _ser_cost(self, v: Decimal) -> str:
        return _money(v)

    @classmethod
    def from_line(cls, line: ResourceLine) -> ResourceStatementLine:
        return cls(
            kind=line.kind.value,
            kind_i18n_key=kind_i18n_key(line.kind),
            name=line.name,
            unit=line.unit,
            quantity=line.quantity,
            cost=line.cost,
            position_count=line.position_count,
        )


class ResourceStatementGroup(BaseModel):
    """All aggregated lines of one category (labour, material, ...) with totals."""

    kind: str
    kind_i18n_key: str
    label: str
    line_count: int
    total_cost: Decimal
    # Labour only: the hours a buyer reads as one figure. ``None`` for other kinds.
    total_hours: Decimal | None = None
    lines: list[ResourceStatementLine] = Field(default_factory=list)

    @field_serializer("total_cost", when_used="json")
    def _ser_total_cost(self, v: Decimal) -> str:
        return _money(v)

    @field_serializer("total_hours", when_used="json")
    def _ser_total_hours(self, v: Decimal | None) -> str | None:
        return None if v is None else _qty(v)

    @classmethod
    def from_group(cls, group: ResourceKindGroup) -> ResourceStatementGroup:
        total_hours = group.total_quantity if group.kind is ResourceKind.LABOUR else None
        return cls(
            kind=group.kind.value,
            kind_i18n_key=kind_i18n_key(group.kind),
            label=group.label,
            line_count=len(group.lines),
            total_cost=group.total_cost,
            total_hours=total_hours,
            lines=[ResourceStatementLine.from_line(line) for line in group.lines],
        )


class ResourceStatementResponse(BaseModel):
    """The whole procurement statement for a project."""

    project_id: uuid.UUID
    generated_at: datetime
    currency: str
    labor_hours: Decimal
    total_cost: Decimal
    line_count: int
    position_count: int
    groups: list[ResourceStatementGroup] = Field(default_factory=list)

    @field_serializer("labor_hours", when_used="json")
    def _ser_labor_hours(self, v: Decimal) -> str:
        return _qty(v)

    @field_serializer("total_cost", when_used="json")
    def _ser_total_cost(self, v: Decimal) -> str:
        return _money(v)

    @classmethod
    def from_statement(
        cls,
        statement: ResourceStatement,
        *,
        project_id: uuid.UUID,
        generated_at: datetime,
    ) -> ResourceStatementResponse:
        return cls(
            project_id=project_id,
            generated_at=generated_at,
            currency=statement.currency,
            labor_hours=statement.labor_hours,
            total_cost=statement.total_cost,
            line_count=statement.line_count,
            position_count=statement.position_count,
            groups=[ResourceStatementGroup.from_group(group) for group in statement.groups],
        )


class MaterialBuyListSource(BaseModel):
    """One BOQ resource line folded into a buy-list row.

    ``position_id`` is the BOQ position, ``resource_key`` the resource within
    its split, and ``quantity``/``unit`` what this line contributes, as the
    source states it. A requisition raised from the row carries these through.
    """

    position_id: str
    resource_key: str
    quantity: Decimal
    unit: str
    code: str = ""
    catalog_item_id: str | None = None
    # The supplier suggested on the BOQ for this resource (``resource``) or its
    # position (``position``). Sources of one row may disagree (issue #516).
    suggested_vendor_id: str | None = None
    suggested_vendor_origin: str | None = None
    # The resource's own rate per ``unit`` and its currency, for an indicative
    # cost on a requisition line. ``unit_rate`` is null when the BOQ has none.
    unit_rate: str | None = None
    currency: str = ""
    # What submitted and later requisitions already hold of this resource, in
    # ``unit`` only (other units are never added in), and what is left of
    # ``quantity``. Negative remaining means more is held than the BOQ now
    # needs. Both null when coverage could not be read.
    covered_quantity: Decimal | None = None
    remaining_quantity: Decimal | None = None

    @field_serializer("quantity", "covered_quantity", "remaining_quantity", when_used="json")
    def _ser_quantity(self, v: Decimal | None) -> str | None:
        return None if v is None else _qty(v)


class MaterialBuyListItem(BaseModel):
    """One material purchase line in the procurement buy-list.

    ``quantity`` is the gross (waste-inclusive) amount to purchase and ``cost``
    the estimated spend, both summed across every position that uses the material
    and both Decimal-serialised as strings. ``currency`` is carried on the line so
    a client-side CSV export can print the money verbatim without a lookup.
    """

    name: str
    unit: str
    quantity: Decimal
    cost: Decimal
    position_count: int
    currency: str
    # Sum of the sources' covered and remaining quantities; null when coverage
    # could not be read.
    covered_quantity: Decimal | None = None
    remaining_quantity: Decimal | None = None
    sources: list[MaterialBuyListSource] = Field(default_factory=list)

    @field_serializer("quantity", when_used="json")
    def _ser_quantity(self, v: Decimal) -> str:
        return _qty(v)

    @field_serializer("covered_quantity", "remaining_quantity", when_used="json")
    def _ser_optional_quantity(self, v: Decimal | None) -> str | None:
        return None if v is None else _qty(v)

    @field_serializer("cost", when_used="json")
    def _ser_cost(self, v: Decimal) -> str:
        return _money(v)

    @classmethod
    def from_item(
        cls, item: BuyListItem, *, currency: str, covered: dict[tuple[str, str], dict[str, Decimal]] | None = None
    ) -> MaterialBuyListItem:
        def _held(source: BuyListSource) -> Decimal | None:
            if covered is None:
                return None
            return covered.get((source.position_id, source.resource_key), {}).get(
                str(source.unit or "").strip().lower(), Decimal("0")
            )

        held = [_held(source) for source in item.sources]
        known = covered is not None
        return cls(
            name=item.name,
            unit=item.unit,
            quantity=item.quantity,
            cost=item.cost,
            position_count=item.position_count,
            currency=currency,
            covered_quantity=sum((h for h in held if h is not None), Decimal("0")) if known else None,
            remaining_quantity=item.quantity - sum((h for h in held if h is not None), Decimal("0")) if known else None,
            sources=[
                MaterialBuyListSource(
                    position_id=source.position_id,
                    resource_key=source.resource_key,
                    quantity=source.quantity,
                    unit=source.unit,
                    code=source.code,
                    catalog_item_id=source.catalog_item_id,
                    suggested_vendor_id=source.suggested_vendor_id,
                    suggested_vendor_origin=source.suggested_vendor_origin,
                    unit_rate=None if source.unit_rate is None else str(source.unit_rate),
                    currency=source.currency or currency,
                    covered_quantity=held_qty,
                    remaining_quantity=None if held_qty is None else source.quantity - held_qty,
                )
                for source, held_qty in zip(item.sources, held, strict=True)
            ],
        )


class MaterialBuyListResponse(BaseModel):
    """The material procurement buy-list for a project.

    Degrades gracefully: a project with no material resource lines returns an
    empty ``items`` list, a zero ``total_cost`` and ``position_count`` 0.
    """

    project_id: uuid.UUID
    generated_at: datetime
    currency: str
    total_cost: Decimal
    item_count: int
    position_count: int
    items: list[MaterialBuyListItem] = Field(default_factory=list)

    @field_serializer("total_cost", when_used="json")
    def _ser_total_cost(self, v: Decimal) -> str:
        return _money(v)

    @classmethod
    def from_buy_list(
        cls,
        buy_list: MaterialBuyList,
        *,
        project_id: uuid.UUID,
        generated_at: datetime,
        covered: dict[tuple[str, str], dict[str, Decimal]] | None = None,
    ) -> MaterialBuyListResponse:
        return cls(
            project_id=project_id,
            generated_at=generated_at,
            currency=buy_list.currency,
            total_cost=buy_list.total_cost,
            item_count=buy_list.item_count,
            position_count=buy_list.position_count,
            items=[
                MaterialBuyListItem.from_item(item, currency=buy_list.currency, covered=covered)
                for item in buy_list.items
            ],
        )


class ResourceSnapshotSummary(BaseModel):
    """A saved statement, listed without its full payload."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generated_at: datetime
    currency: str
    total_cost: Decimal
    line_count: int

    @field_serializer("total_cost", when_used="json")
    def _ser_total_cost(self, v: Decimal) -> str:
        return _money(v)


class ResourceSnapshotDetail(ResourceSnapshotSummary):
    """A saved statement including the frozen procurement payload."""

    payload: dict[str, Any] = Field(default_factory=dict)
