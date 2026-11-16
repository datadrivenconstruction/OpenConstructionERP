# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DACH pack hooks: contribute the EXTF booking batch writer to the finance connectors."""

from __future__ import annotations

from app.modules.dach_pack.datev import DatevWriter
from app.modules.finance.booking_export import register_writer
from app.modules.finance.connectors.base import ConnectorField
from app.modules.finance.connectors.booking_connector import register_booking_connector

register_writer(DatevWriter)
register_booking_connector(
    DatevWriter,
    "Export in DATEV format (EXTF)",
    (
        ConnectorField("advisor", "Advisor number"),
        ConnectorField("client", "Client number"),
        ConnectorField("fiscal_year_start", "Fiscal year start (YYYYMMDD)"),
        ConnectorField("account_length", "G/L account length"),
        ConnectorField("format_version", "Format version", kind="select", options=("13", "12")),
    ),
)
