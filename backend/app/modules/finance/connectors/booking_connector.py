# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Connector entries for booking batch writers, so they appear beside the file connector."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.modules.finance.connectors.base import Connector, ConnectorField, PushPayload, SyncResult
from app.modules.finance.connectors.registry import connector_registry

if TYPE_CHECKING:
    from app.modules.finance.booking_export import BookingWriter


class BookingConnector(Connector):
    """Config holder for a booking writer; files are produced by booking export batches."""

    supported_directions: ClassVar[tuple[str, ...]] = ("push",)
    required_markets: ClassVar[tuple[str, ...]] = ()
    setting_fields: ClassVar[tuple[ConnectorField, ...]] = (
        ConnectorField("account_map", "Account map", kind="textarea"),
        ConnectorField("creditor_accounts", "Creditor accounts", kind="textarea"),
    )

    async def validate_config(self) -> list[str]:
        return []

    async def push(self, payload: PushPayload, *, dry_run: bool) -> SyncResult:
        return SyncResult(direction="push", warnings=["booking_export_uses_batches"])

    async def pull(self, *, dry_run: bool) -> SyncResult:
        return SyncResult(direction="pull", warnings=["pull_not_supported"])


def register_booking_connector(
    writer: type[BookingWriter], display_name: str, extra_fields: tuple[ConnectorField, ...] = ()
) -> type[BookingConnector]:
    cls = type(
        f"{writer.__name__}Connector",
        (BookingConnector,),
        {
            "connector_type": writer.connector_type,
            "display_name": display_name,
            "required_markets": writer.required_markets,
            "setting_fields": (*BookingConnector.setting_fields, *extra_fields),
        },
    )
    connector_registry.register(cls)
    return cls
