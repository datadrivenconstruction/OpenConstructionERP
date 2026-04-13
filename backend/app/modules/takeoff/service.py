"""Takeoff business logic."""

import io
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement
from app.modules.takeoff.repository import MeasurementRepository, TakeoffRepository
from app.modules.takeoff.schemas import TakeoffMeasurementCreate, TakeoffMeasurementUpdate

logger = logging.getLogger(__name__)

# Directory where uploaded PDF files are stored on disk
_TAKEOFF_DOCUMENTS_DIR = Path.home() / ".openestimator" / "takeoff_documents"


def _extract_pdf_pages(content: bytes) -> list[dict]:
    """Extract text and tables from each page of a PDF.

    Returns a list of dicts: [{ page: 1, text: "...", tables: [...] }, ...]
    """
    pages: list[dict] = []
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                page_text = ""
                page_tables: list[list[list[str]]] = []

                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        cleaned = [[str(cell or "") for cell in row] for row in table]
                        page_tables.append(cleaned)
                        for row in cleaned:
                            page_text += "\t".join(row) + "\n"
                else:
                    text = page.extract_text()
                    if text:
                        page_text = text

                pages.append(
                    {
                        "page": i,
                        "text": page_text.strip(),
                        "tables": page_tables,
                    }
                )
    except Exception:
        # If pdfplumber fails, try pymupdf as fallback
        try:
            import pymupdf

            doc = pymupdf.open(stream=content, filetype="pdf")
            for i, page in enumerate(doc, start=1):
                text = page.get_text()
                pages.append({"page": i, "text": text.strip(), "tables": []})
            doc.close()
        except Exception:
            logger.warning("PDF extraction failed with both pdfplumber and pymupdf")

    return pages


def _count_pdf_pages(content: bytes) -> int:
    """Count the number of pages in a PDF."""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return len(pdf.pages)
    except Exception:
        try:
            import pymupdf

            doc = pymupdf.open(stream=content, filetype="pdf")
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0


class TakeoffService:
    """Business logic for takeoff operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TakeoffRepository(session)
        self.measurement_repo = MeasurementRepository(session)

    async def upload_document(
        self,
        *,
        filename: str,
        content: bytes,
        size_bytes: int,
        owner_id: str,
        project_id: str | None = None,
    ) -> TakeoffDocument:
        """Upload and process a PDF document for takeoff."""
        # Count pages
        page_count = _count_pdf_pages(content)

        # Extract text from each page
        page_data = _extract_pdf_pages(content)
        full_text = "\n\n".join(p["text"] for p in page_data if p["text"])

        # Save the PDF file to disk so it can be retrieved later for viewing
        _TAKEOFF_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        doc_id = uuid.uuid4()
        file_path = _TAKEOFF_DOCUMENTS_DIR / f"{doc_id}.pdf"
        file_path.write_bytes(content)

        doc = TakeoffDocument(
            id=doc_id,
            filename=filename,
            pages=page_count,
            size_bytes=size_bytes,
            content_type="application/pdf",
            status="uploaded",
            owner_id=uuid.UUID(owner_id),
            project_id=uuid.UUID(project_id) if project_id else None,
            extracted_text=full_text,
            page_data=page_data,
            file_path=str(file_path),
        )

        return await self.repo.create(doc)

    async def get_document(self, doc_id: str) -> TakeoffDocument | None:
        return await self.repo.get_by_id(uuid.UUID(doc_id))

    async def list_documents(
        self,
        owner_id: str,
        project_id: str | None = None,
    ) -> list[TakeoffDocument]:
        return await self.repo.list_for_user(
            uuid.UUID(owner_id),
            project_id=uuid.UUID(project_id) if project_id else None,
        )

    async def extract_tables(self, doc_id: str) -> dict:
        """Extract table data from an already-uploaded document."""
        doc = await self.repo.get_by_id(uuid.UUID(doc_id))
        if doc is None:
            return {"elements": [], "summary": {"total_elements": 0, "categories": {}}}

        elements = []
        idx = 0
        for page in doc.page_data or []:
            for table in page.get("tables", []):
                if len(table) < 2:
                    continue
                # Use first row as header, remaining as data
                headers = [h.lower().strip() for h in table[0]]
                for row in table[1:]:
                    if not any(cell.strip() for cell in row):
                        continue
                    desc = row[0] if len(row) > 0 else ""
                    qty_str = row[1] if len(row) > 1 else "0"
                    unit = row[2] if len(row) > 2 else "pcs"

                    try:
                        qty = float(qty_str.replace(",", "."))
                    except (ValueError, AttributeError):
                        qty = 1.0

                    idx += 1
                    clean_desc = desc.strip()
                    clean_unit = unit.strip() or "pcs"

                    # Compute confidence based on data quality
                    has_real_qty = qty_str.strip() != "" and qty > 0
                    has_description = bool(clean_desc) and clean_desc.lower() not in (
                        "item",
                        "position",
                        "pos",
                        "n/a",
                        "-",
                        "",
                    )

                    if not has_description:
                        confidence = 0.4
                    elif not has_real_qty:
                        confidence = 0.5
                    elif has_description and has_real_qty and clean_unit:
                        confidence = 0.85
                    else:
                        confidence = 0.6

                    elements.append(
                        {
                            "id": f"ext_{idx}",
                            "category": "general",
                            "description": clean_desc or f"Item {idx}",
                            "quantity": qty,
                            "unit": clean_unit,
                            "confidence": confidence,
                        }
                    )

        categories: dict = {}
        for el in elements:
            cat = el["category"]
            if cat not in categories:
                categories[cat] = {"count": 0, "total_quantity": 0, "unit": el["unit"]}
            categories[cat]["count"] += 1
            categories[cat]["total_quantity"] += el["quantity"]

        return {
            "elements": elements,
            "summary": {"total_elements": len(elements), "categories": categories},
        }

    async def delete_document(self, doc_id: str) -> None:
        """Delete a takeoff document and its stored PDF file."""
        doc = await self.repo.get_by_id(uuid.UUID(doc_id))
        if doc is not None and doc.file_path:
            try:
                file_path = Path(doc.file_path)
                if file_path.exists():
                    file_path.unlink()
                    logger.info("Removed takeoff PDF file: %s", file_path)
            except Exception:
                logger.warning("Failed to remove takeoff PDF file: %s", doc.file_path)
        await self.repo.delete(uuid.UUID(doc_id))

    # ── Measurement CRUD ─────────────────────────────────────────────────

    async def create_measurement(
        self,
        data: TakeoffMeasurementCreate,
        *,
        created_by: str = "",
    ) -> TakeoffMeasurement:
        """Create a single takeoff measurement."""
        measurement = TakeoffMeasurement(
            project_id=data.project_id,
            document_id=data.document_id,
            page=data.page,
            type=data.type,
            group_name=data.group_name,
            group_color=data.group_color,
            annotation=data.annotation,
            points=[p.model_dump() for p in data.points],
            measurement_value=data.measurement_value,
            measurement_unit=data.measurement_unit,
            depth=data.depth,
            volume=data.volume,
            perimeter=data.perimeter,
            count_value=data.count_value,
            scale_pixels_per_unit=data.scale_pixels_per_unit,
            linked_boq_position_id=data.linked_boq_position_id,
            metadata_=data.metadata,
            created_by=created_by,
        )
        measurement = await self.measurement_repo.create(measurement)
        logger.info(
            "Measurement created: %s type=%s project=%s",
            measurement.id,
            data.type,
            data.project_id,
        )
        return measurement

    async def get_measurement(self, measurement_id: uuid.UUID) -> TakeoffMeasurement:
        """Get a measurement by ID. Raises 404 if not found."""
        item = await self.measurement_repo.get_by_id(measurement_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Measurement not found",
            )
        return item

    async def list_measurements(
        self,
        project_id: uuid.UUID,
        *,
        document_id: str | None = None,
        page: int | None = None,
        group_name: str | None = None,
        measurement_type: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> list[TakeoffMeasurement]:
        """List measurements for a project with filters."""
        return await self.measurement_repo.list_for_project(
            project_id,
            document_id=document_id,
            page=page,
            group_name=group_name,
            measurement_type=measurement_type,
            offset=offset,
            limit=limit,
        )

    async def update_measurement(
        self,
        measurement_id: uuid.UUID,
        data: TakeoffMeasurementUpdate,
    ) -> TakeoffMeasurement:
        """Update measurement fields."""
        item = await self.get_measurement(measurement_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if "points" in fields and fields["points"] is not None:
            fields["points"] = [p.model_dump() for p in data.points]  # type: ignore[union-attr]

        if not fields:
            return item

        await self.measurement_repo.update_fields(measurement_id, **fields)
        await self.session.refresh(item)

        logger.info("Measurement updated: %s (fields=%s)", measurement_id, list(fields.keys()))
        return item

    async def delete_measurement(self, measurement_id: uuid.UUID) -> None:
        """Delete a measurement."""
        await self.get_measurement(measurement_id)  # Raises 404 if not found
        await self.measurement_repo.delete(measurement_id)
        logger.info("Measurement deleted: %s", measurement_id)

    async def bulk_create_measurements(
        self,
        items: list[TakeoffMeasurementCreate],
        *,
        created_by: str = "",
    ) -> list[TakeoffMeasurement]:
        """Bulk create measurements (e.g. importing from localStorage)."""
        measurements = [
            TakeoffMeasurement(
                project_id=data.project_id,
                document_id=data.document_id,
                page=data.page,
                type=data.type,
                group_name=data.group_name,
                group_color=data.group_color,
                annotation=data.annotation,
                points=[p.model_dump() for p in data.points],
                measurement_value=data.measurement_value,
                measurement_unit=data.measurement_unit,
                depth=data.depth,
                volume=data.volume,
                perimeter=data.perimeter,
                count_value=data.count_value,
                scale_pixels_per_unit=data.scale_pixels_per_unit,
                linked_boq_position_id=data.linked_boq_position_id,
                metadata_=data.metadata,
                created_by=created_by,
            )
            for data in items
        ]
        result = await self.measurement_repo.create_bulk(measurements)
        logger.info("Bulk created %d measurements", len(result))
        return result

    async def get_measurement_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's measurements."""
        items = await self.measurement_repo.all_for_project(project_id)

        by_type: dict[str, int] = {}
        by_group: dict[str, int] = {}
        by_page: dict[int, int] = {}

        for item in items:
            by_type[item.type] = by_type.get(item.type, 0) + 1
            by_group[item.group_name] = by_group.get(item.group_name, 0) + 1
            by_page[item.page] = by_page.get(item.page, 0) + 1

        return {
            "total_measurements": len(items),
            "by_type": by_type,
            "by_group": by_group,
            "by_page": by_page,
        }

    async def export_measurements(
        self,
        project_id: uuid.UUID,
        *,
        fmt: str = "csv",
    ) -> list[dict[str, Any]]:
        """Export measurements for a project as a list of dicts.

        The caller (router) is responsible for converting to the requested
        format (CSV, JSON, etc.).
        """
        items = await self.measurement_repo.all_for_project(project_id)
        rows: list[dict[str, Any]] = []
        for m in items:
            rows.append(
                {
                    "id": str(m.id),
                    "project_id": str(m.project_id),
                    "document_id": m.document_id or "",
                    "page": m.page,
                    "type": m.type,
                    "group_name": m.group_name,
                    "group_color": m.group_color,
                    "annotation": m.annotation or "",
                    "measurement_value": m.measurement_value,
                    "measurement_unit": m.measurement_unit,
                    "depth": m.depth,
                    "volume": m.volume,
                    "perimeter": m.perimeter,
                    "count_value": m.count_value,
                    "scale_pixels_per_unit": m.scale_pixels_per_unit,
                    "linked_boq_position_id": m.linked_boq_position_id or "",
                    "created_by": m.created_by,
                    "created_at": m.created_at.isoformat() if m.created_at else "",
                }
            )
        return rows

    async def link_measurement_to_boq(
        self,
        measurement_id: uuid.UUID,
        boq_position_id: str,
    ) -> TakeoffMeasurement:
        """Link a measurement to a BOQ position."""
        item = await self.get_measurement(measurement_id)
        await self.measurement_repo.update_fields(measurement_id, linked_boq_position_id=boq_position_id)
        await self.session.refresh(item)
        logger.info(
            "Measurement %s linked to BOQ position %s",
            measurement_id,
            boq_position_id,
        )
        return item
