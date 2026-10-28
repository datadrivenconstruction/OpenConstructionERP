# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the BIM-LV container API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelReferenceOut(BaseModel):
    """The IFC/BIM model reference carried by an imported container."""

    filename: str = ""
    model_id: str = ""
    # ``schema`` shadows a Pydantic BaseModel attribute, so the IFC schema is
    # exposed as ``ifc_schema`` on the wire.
    ifc_schema: str = ""
    guid: str = ""
    checksum: str = ""


class BimLvImportResponse(BaseModel):
    """Result of importing a BIM-LV container and materializing its links."""

    created: int = Field(0, description="New BOQ<->BIM link rows created")
    skipped_existing: int = Field(0, description="Links that already existed (idempotent re-import)")
    matched_ordinals: int = Field(0, description="Container ordinals matched to a BOQ position")
    total_ordinals: int = Field(0, description="Ordinals present in the container link table")
    unmatched_ordinals: list[str] = Field(
        default_factory=list,
        description="Container ordinals with no matching BOQ position in the project",
    )
    unmatched_guids: list[str] = Field(
        default_factory=list,
        description="Container element GUIDs with no matching BIM element in the project",
    )
    position_count: int = Field(0, description="LV positions found in the container")
    model_reference: ModelReferenceOut = Field(default_factory=ModelReferenceOut)
    warnings: list[str] = Field(default_factory=list)
