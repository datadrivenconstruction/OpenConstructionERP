# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``oe_match`` — element-to-CWICR matcher API surface.

This module is a thin HTTP wrapper around :mod:`app.core.match_service`.
The heavy lifting (translation, vector search, boost stack, reranker,
audit-log feedback) lives in the core service so the eval harness and
non-HTTP callers can use the same code path.
"""
