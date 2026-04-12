"""BIM Requirements service -- business logic for import/export.

Handles file import orchestration, parser selection, DB persistence,
and export generation.
"""

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_requirements.classifier import FormatClassifier
from app.modules.bim_requirements.models import BIMRequirement, BIMRequirementSet
from app.modules.bim_requirements.parsers.base import ParseResult, UniversalRequirement

logger = logging.getLogger(__name__)

_classifier = FormatClassifier()


def _get_parser(format_name: str) -> Any:
    """Return the appropriate parser instance for a detected format."""
    if format_name == "IDS":
        from app.modules.bim_requirements.parsers.ids_parser import IDSParser

        return IDSParser()
    elif format_name in ("COBie",):
        from app.modules.bim_requirements.parsers.cobie_parser import COBieParser

        return COBieParser()
    elif format_name in ("Excel", "CSV"):
        from app.modules.bim_requirements.parsers.excel_parser import ExcelCSVParser

        return ExcelCSVParser()
    elif format_name == "RevitSP":
        from app.modules.bim_requirements.parsers.revit_sp_parser import RevitSPParser

        return RevitSPParser()
    elif format_name == "BIMQ":
        from app.modules.bim_requirements.parsers.bimq_parser import BIMQParser

        return BIMQParser()
    else:
        raise ValueError(f"No parser available for format: {format_name}")


class BIMRequirementService:
    """Business logic for BIM requirements import/export."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Import ─────────────────────────────────────────────────────────────

    async def import_file(
        self,
        project_id: uuid.UUID,
        file_content: bytes,
        filename: str,
        *,
        name: str | None = None,
        user_id: str = "",
    ) -> tuple[BIMRequirementSet, ParseResult]:
        """Import a BIM requirements file: detect format, parse, persist.

        Args:
            project_id: Project to associate the requirement set with.
            file_content: Raw file content as bytes.
            filename: Original filename (used for format detection).
            name: Optional name for the requirement set.
            user_id: ID of the importing user.

        Returns:
            Tuple of (created BIMRequirementSet, ParseResult with details).

        Raises:
            HTTPException: If file format is unsupported or parsing fails completely.
        """
        # Write to temp file for classifier and parser
        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = Path(tmp.name)

        try:
            # Classify format
            try:
                format_name = _classifier.classify(tmp_path)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc

            # Get parser and parse
            try:
                parser = _get_parser(format_name)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc

            parse_result: ParseResult = parser.parse(tmp_path)
            parse_result.metadata["format_detected"] = format_name

        finally:
            # Clean up temp file
            try:
                tmp_path.unlink()
            except OSError:
                pass

        if not parse_result.success:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"No requirements could be parsed from '{filename}' "
                    f"(format: {format_name}). "
                    f"Errors: {parse_result.errors}"
                ),
            )

        # Create the requirement set
        set_name = name or f"{Path(filename).stem} ({format_name})"
        req_set = BIMRequirementSet(
            project_id=project_id,
            name=set_name,
            description=f"Imported from {filename}",
            source_format=format_name,
            source_filename=filename,
            created_by=user_id,
            metadata_=parse_result.metadata,
        )
        self.session.add(req_set)
        await self.session.flush()

        # Persist individual requirements
        for req in parse_result.requirements:
            db_req = BIMRequirement(
                requirement_set_id=req_set.id,
                element_filter=req.element_filter,
                property_group=req.property_group,
                property_name=req.property_name,
                constraint_def=req.constraint_def,
                context=req.context,
                source_format=format_name,
                is_active=True,
            )
            self.session.add(db_req)

        await self.session.flush()

        logger.info(
            "Imported %d BIM requirements from '%s' (format=%s) into set %s",
            len(parse_result.requirements),
            filename,
            format_name,
            req_set.id,
        )
        return req_set, parse_result

    # ── CRUD ───────────────────────────────────────────────────────────────

    async def list_sets(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[BIMRequirementSet]:
        """List requirement sets for a project."""
        stmt = (
            select(BIMRequirementSet)
            .where(BIMRequirementSet.project_id == project_id)
            .order_by(BIMRequirementSet.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_set(self, set_id: uuid.UUID) -> BIMRequirementSet:
        """Get a requirement set by ID. Raises 404 if not found."""
        item = await self.session.get(BIMRequirementSet, set_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM requirement set not found",
            )
        return item

    async def list_requirements(
        self,
        set_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[BIMRequirement]:
        """List requirements for a set."""
        stmt = (
            select(BIMRequirement)
            .where(BIMRequirement.requirement_set_id == set_id)
            .order_by(BIMRequirement.created_at)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_set(self, set_id: uuid.UUID) -> None:
        """Delete a requirement set and all its requirements (cascade)."""
        item = await self.get_set(set_id)
        await self.session.delete(item)
        await self.session.flush()
        logger.info("BIM requirement set deleted: %s", set_id)

    # ── Export ─────────────────────────────────────────────────────────────

    async def export_excel(
        self,
        set_id: uuid.UUID,
        language: str = "en",
    ) -> bytes:
        """Export a requirement set as a formatted Excel file."""
        from app.modules.bim_requirements.exporters.excel_exporter import export_excel

        req_set = await self.get_set(set_id)
        reqs = await self._load_requirements_as_universal(set_id)
        return export_excel(reqs, title=req_set.name, language=language)

    async def export_ids(
        self,
        set_id: uuid.UUID,
    ) -> str:
        """Export a requirement set as IDS XML."""
        from app.modules.bim_requirements.exporters.ids_exporter import export_ids_xml

        req_set = await self.get_set(set_id)
        reqs = await self._load_requirements_as_universal(set_id)
        return export_ids_xml(reqs, title=req_set.name)

    async def _load_requirements_as_universal(
        self, set_id: uuid.UUID
    ) -> list[UniversalRequirement]:
        """Load DB requirements and convert to UniversalRequirement objects."""
        stmt = (
            select(BIMRequirement)
            .where(BIMRequirement.requirement_set_id == set_id)
            .order_by(BIMRequirement.created_at)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        return [
            UniversalRequirement(
                element_filter=row.element_filter or {},
                property_group=row.property_group,
                property_name=row.property_name,
                constraint_def=row.constraint_def or {},
                context=row.context,
            )
            for row in rows
        ]
