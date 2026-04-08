# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation ORM models.

Tables:
    oe_validation_report — persisted validation reports with results
"""

import uuid

from sqlalchemy import JSON, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ValidationReport(Base):
    """Persisted validation report for a BOQ, document, or CAD import.

    Stores the full validation result including per-rule outcomes so that
    historical reports can be reviewed without re-running validation.
    """

    __tablename__ = "oe_validation_report"
    __table_args__ = (
        Index("ix_validation_target", "target_type", "target_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type of validated entity: boq, document, cad_import, tender",
    )
    target_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        doc="UUID of the validated entity",
    )
    rule_set: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Rule sets applied, e.g. 'din276+gaeb+boq_quality'",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        doc="Overall status: pending, passed, warnings, errors",
    )
    score: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        doc="Quality score 0.0-1.0 as string (SQLite-safe)",
    )
    total_rules: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    passed_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    warning_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    error_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    results: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        doc="Array of {rule_id, status, message, element_ref, details}",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ValidationReport {self.target_type}:{self.target_id} status={self.status} score={self.score}>"
