# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""EAC v2 platform module.

The EAC (Estimation, Audit & Compliance) v2 engine implements the
"one engine, four output modes" architecture from RFC 35:

    aggregate | boolean | clash | issue

Rules are stored as declarative JSON definitions (``EacRuleDefinition``
schema v2.0) and evaluated through DuckDB on canonical Parquet data.
This module provides the foundational ORM layer, JSON Schema, Pydantic
mirrors, and CRUD API surface (Wave EAC-1.1 + EAC-1.2).
"""
