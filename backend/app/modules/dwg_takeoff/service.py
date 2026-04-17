"""DWG Takeoff service — business logic.

Stateless service layer. Handles:
- Drawing upload, processing, and retrieval
- DXF parsing via ezdxf (layers, entities, SVG thumbnail)
- Annotation CRUD and BOQ position linking
- Task/punchlist pin queries
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dwg_takeoff.models import DwgAnnotation, DwgDrawing, DwgDrawingVersion
from app.modules.dwg_takeoff.repository import (
    DwgAnnotationRepository,
    DwgDrawingRepository,
    DwgDrawingVersionRepository,
)
from app.modules.dwg_takeoff.schemas import (
    DwgAnnotationCreate,
    DwgAnnotationUpdate,
)

logger = logging.getLogger(__name__)


def _normalize_entity(raw: dict[str, Any], index: int) -> dict[str, Any]:
    """Flatten stored entity format to the shape the frontend DxfViewer expects.

    Stored format: {entity_type, layer, color, geometry_data: {…}}
    Frontend format: {id, type, layer, color, start?, end?, vertices?, …}
    """
    gd = raw.get("geometry_data", {})
    entity_type = raw.get("entity_type", "")
    # Map MTEXT → TEXT for the frontend renderer
    front_type = "TEXT" if entity_type == "MTEXT" else entity_type

    result: dict[str, Any] = {
        "id": f"e_{index}",
        "type": front_type,
        "layer": raw.get("layer", "0"),
        "color": raw.get("color", "#cccccc"),
    }

    # Pass through layout field (DXF layout name or DWG BlockId)
    if "layout" in raw:
        result["layout"] = raw["layout"]

    if entity_type == "LINE":
        result["start"] = gd.get("start")
        result["end"] = gd.get("end")
    elif entity_type in ("LWPOLYLINE", "POLYLINE"):
        result["vertices"] = gd.get("points", [])
        result["closed"] = gd.get("closed", False)
    elif entity_type == "CIRCLE":
        result["start"] = gd.get("center")
        result["radius"] = gd.get("radius")
    elif entity_type == "ARC":
        result["start"] = gd.get("center")
        result["radius"] = gd.get("radius")
        result["start_angle"] = gd.get("start_angle", 0)
        result["end_angle"] = gd.get("end_angle", 6.283185307179586)
    elif entity_type == "ELLIPSE":
        result["start"] = gd.get("center")
        result["major_radius"] = gd.get("major_radius")
        result["minor_radius"] = gd.get("minor_radius")
        result["rotation"] = gd.get("rotation", 0)
        result["start_angle"] = gd.get("start_angle", 0)
        result["end_angle"] = gd.get("end_angle", 0)
        # Also provide major_axis for ezdxf-style format
        if "major_axis" in gd:
            result["major_axis"] = gd["major_axis"]
            result["ratio"] = gd.get("ratio", 1.0)
    elif entity_type in ("TEXT", "MTEXT"):
        result["start"] = gd.get("insert") or gd.get("insertion_point")
        result["text"] = gd.get("text", "")
        result["height"] = gd.get("height", 2.5)
        result["rotation"] = gd.get("rotation", 0)
    elif entity_type == "INSERT":
        result["start"] = gd.get("insert") or gd.get("insertion_point")
        result["block_name"] = gd.get("block_name") or gd.get("name", "")
        result["rotation"] = gd.get("rotation", 0)
        result["x_scale"] = gd.get("x_scale", 1.0)
        result["y_scale"] = gd.get("y_scale", 1.0)
    elif entity_type == "HATCH":
        result["vertices"] = gd.get("points", [])
        result["closed"] = gd.get("closed", True)
        result["pattern_name"] = gd.get("pattern_name", "SOLID")
        result["is_solid"] = gd.get("is_solid", False)
    elif entity_type == "SPLINE":
        result["type"] = "LWPOLYLINE"
        result["vertices"] = gd.get("control_points", [])
        result["closed"] = False
    elif entity_type == "DIMENSION":
        result["start"] = gd.get("start")
        result["end"] = gd.get("end")

    return result


def _get_upload_dir() -> str:
    """Get the upload directory for DWG files."""
    base = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
    upload_dir = os.path.join(base, "dwg_uploads")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _get_entities_dir() -> str:
    """Get the storage directory for parsed entity JSON files."""
    base = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
    entities_dir = os.path.join(base, "dwg_entities")
    os.makedirs(entities_dir, exist_ok=True)
    return entities_dir


def _process_dxf_sync(file_path: str, entities_key: str, thumbnail_key: str) -> dict[str, Any]:
    """Synchronous DXF processing — runs in a thread via asyncio.to_thread.

    Parses the DXF file, saves entities JSON, and generates SVG thumbnail.
    Returns a dict with parse results and storage keys.
    """
    from app.modules.dwg_takeoff.dxf_processor import generate_svg_thumbnail, parse_dxf

    result = parse_dxf(file_path)

    # Save entities JSON to disk
    entities_path = os.path.join(_get_entities_dir(), entities_key)
    os.makedirs(os.path.dirname(entities_path), exist_ok=True)
    with open(entities_path, "w", encoding="utf-8") as f:
        json.dump(result["entities"], f)

    # Generate and save SVG thumbnail
    svg_content = generate_svg_thumbnail(file_path)
    thumb_dir = os.path.join(
        os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data")), "dwg_thumbnails"
    )
    thumb_path = os.path.join(thumb_dir, thumbnail_key)
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
    with open(thumb_path, "w", encoding="utf-8") as f:
        f.write(svg_content)

    return result


class DwgTakeoffService:
    """Business logic for DWG drawings, versions, and annotations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.drawing_repo = DwgDrawingRepository(session)
        self.version_repo = DwgDrawingVersionRepository(session)
        self.annotation_repo = DwgAnnotationRepository(session)

    # ── Drawing upload & processing ─────────────────────────────────────

    async def upload_drawing(
        self,
        project_id: uuid.UUID,
        file: UploadFile,
        user_id: str,
        *,
        name: str | None = None,
        discipline: str | None = None,
        sheet_number: str | None = None,
    ) -> DwgDrawing:
        """Upload a DWG/DXF file and create a database record.

        The file is saved to disk and processing is triggered in a background thread.
        """
        filename = file.filename or "drawing.dxf"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".dwg", ".dxf"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only .dwg and .dxf files are supported",
            )

        file_format = ext.lstrip(".")
        content = await file.read()
        size_bytes = len(content)

        # Create drawing record FIRST (before writing file to disk)
        upload_dir = _get_upload_dir()
        file_id = str(uuid.uuid4())
        file_path = os.path.join(upload_dir, f"{file_id}{ext}")

        drawing = DwgDrawing(
            project_id=project_id,
            name=name or os.path.splitext(filename)[0],
            filename=filename,
            file_format=file_format,
            file_path=file_path,
            size_bytes=size_bytes,
            status="uploaded",
            discipline=discipline,
            sheet_number=sheet_number,
            created_by=user_id,
            metadata_={},
        )
        drawing = await self.drawing_repo.create(drawing)
        drawing_id = drawing.id

        # Save file to disk AFTER DB record exists; clean up on failure
        try:
            with open(file_path, "wb") as f:
                f.write(content)
        except Exception:
            await self.drawing_repo.delete(drawing_id)
            raise

        logger.info(
            "Drawing uploaded: %s (%s, %d bytes) project=%s",
            filename,
            file_format,
            size_bytes,
            project_id,
        )

        # Cross-link: create a Document row pointing at the same file on
        # disk so the drawing also appears in the Documents hub.  This is
        # best-effort — failure here MUST NOT break the drawing upload.
        # The document is NOT a copy: ``file_path`` references the same
        # blob already persisted by the dwg_takeoff module.
        try:
            from app.modules.documents.models import Document

            xlink_doc = Document(
                project_id=project_id,
                name=filename,
                description=f"DWG/DXF drawing: {name or filename}",
                category="drawing",
                file_size=size_bytes,
                mime_type=f"image/vnd.{file_format}",
                file_path=file_path,
                version=1,
                uploaded_by=user_id or "",
                tags=["dwg-takeoff", file_format] + ([discipline] if discipline else []),
                metadata_={
                    "source_module": "dwg_takeoff",
                    "source_id": str(drawing_id),
                },
            )
            self.session.add(xlink_doc)
            await self.session.flush()
            logger.info(
                "Cross-linked DWG drawing %s → document %s",
                drawing_id,
                xlink_doc.id,
            )
        except Exception as exc:
            logger.warning("Failed to cross-link DWG to documents hub: %s", exc)

        # Trigger processing
        if file_format == "dxf":
            await self._process_drawing(drawing_id, file_path)
        elif file_format == "dwg":
            await self._handle_dwg(drawing_id, file_path)

        await self.session.refresh(drawing)
        return drawing

    async def _process_drawing(self, drawing_id: uuid.UUID, file_path: str) -> None:
        """Process a DXF file: parse layers/entities, generate thumbnail."""
        await self.drawing_repo.update_fields(drawing_id, status="processing")

        # Prepare storage keys
        entities_key = f"{drawing_id}/entities.json"
        thumbnail_key = f"{drawing_id}/thumbnail.svg"

        try:
            result = await asyncio.to_thread(
                _process_dxf_sync, file_path, entities_key, thumbnail_key
            )

            # Create drawing version
            version_number = await self.version_repo.get_next_version_number(drawing_id)
            version = DwgDrawingVersion(
                drawing_id=drawing_id,
                version_number=version_number,
                layers=result["layers"],
                entities_key=entities_key,
                entity_count=result["entity_count"],
                extents=result["extents"],
                units=result["units"],
                status="ready",
                metadata_={},
            )
            await self.version_repo.create(version)

            # Update drawing status
            await self.drawing_repo.update_fields(
                drawing_id,
                status="ready",
                thumbnail_key=thumbnail_key,
            )

            logger.info(
                "Drawing processed: %s — %d entities, %d layers",
                drawing_id,
                result["entity_count"],
                len(result["layers"]),
            )

        except ImportError:
            await self.drawing_repo.update_fields(
                drawing_id,
                status="error",
                error_message="ezdxf is not installed — cannot process DXF files",
            )
            logger.error("ezdxf not installed — cannot process drawing %s", drawing_id)

        except Exception as exc:
            await self.drawing_repo.update_fields(
                drawing_id,
                status="error",
                error_message=str(exc)[:500],
            )
            logger.exception("Failed to process drawing %s: %s", drawing_id, exc)

    async def _handle_dwg(self, drawing_id: uuid.UUID, file_path: str) -> None:
        """Process DWG via DDC DwgExporter → Excel → parse entities."""
        try:
            from app.modules.boq.cad_import import find_converter

            converter = find_converter("dwg")
        except ImportError:
            converter = None

        if converter is None:
            await self.drawing_repo.update_fields(
                drawing_id,
                status="error",
                error_message=(
                    "DWG conversion requires DDC DwgExporter. "
                    "Please upload DXF format or install the converter."
                ),
            )
            return

        await self.drawing_repo.update_fields(drawing_id, status="processing")

        import subprocess
        from pathlib import Path as _Path

        # DDC DwgExporter → Excel (dispatched by output file extension)
        xlsx_path = file_path.rsplit(".", 1)[0] + "_dwg.xlsx"
        try:
            proc = await asyncio.to_thread(
                lambda: subprocess.run(
                    [str(converter), str(_Path(file_path).resolve()), str(_Path(xlsx_path).resolve()), "-no-collada"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(converter.parent),
                    input=b"\n",
                    timeout=120,
                )
            )
            if not os.path.exists(xlsx_path) or os.path.getsize(xlsx_path) < 100:
                stderr_msg = proc.stderr.decode(errors="replace")[:300] if proc.stderr else ""
                await self.drawing_repo.update_fields(
                    drawing_id,
                    status="error",
                    error_message=f"DDC DwgExporter produced no output: {stderr_msg}".strip()[:500],
                )
                return
        except subprocess.TimeoutExpired:
            await self.drawing_repo.update_fields(
                drawing_id, status="error",
                error_message="DWG conversion timed out (120s limit)",
            )
            return
        except Exception as exc:
            await self.drawing_repo.update_fields(
                drawing_id, status="error",
                error_message=f"DWG conversion error: {exc}"[:500],
            )
            return

        # Parse DDC Excel → entities (same format as ezdxf output)
        try:
            from app.modules.dwg_takeoff.ddc_dwg_parser import parse_ddc_dwg_excel

            result = await asyncio.to_thread(parse_ddc_dwg_excel, xlsx_path)

            if result["entity_count"] == 0:
                await self.drawing_repo.update_fields(
                    drawing_id, status="error",
                    error_message="No drawable entities found in DWG file",
                )
                return

            # Store entities JSON
            entities_key = f"{drawing_id}/entities.json"
            entities_path = os.path.join(os.path.dirname(file_path), f"{drawing_id}_entities.json")
            import json
            with open(entities_path, "w", encoding="utf-8") as f:
                json.dump(result["entities"], f)

            # Create drawing version
            version_number = await self.version_repo.get_next_version_number(drawing_id)
            version = DwgDrawingVersion(
                drawing_id=drawing_id,
                version_number=version_number,
                layers=result["layers"],
                entities_key=entities_path,
                entity_count=result["entity_count"],
                extents=result["extents"],
                units=result.get("units", "unitless"),
                status="ready",
            )
            self.session.add(version)
            await self.drawing_repo.update_fields(
                drawing_id,
                status="ready",
                error_message=None,
            )
            await self.session.flush()

            logger.info(
                "DWG processed via DDC: %s — %d entities, %d layers",
                drawing_id, result["entity_count"], len(result["layers"]),
            )

        except Exception as exc:
            await self.drawing_repo.update_fields(
                drawing_id, status="error",
                error_message=f"DWG parsing error: {exc}"[:500],
            )
            logger.exception("Failed to parse DWG %s: %s", drawing_id, exc)

    # ── Drawing CRUD ────────────────────────────────────────────────────

    async def get_drawing(self, drawing_id: uuid.UUID) -> DwgDrawing:
        """Get drawing by ID. Raises 404 if not found."""
        item = await self.drawing_repo.get_by_id(drawing_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Drawing not found",
            )
        return item

    async def list_drawings(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[DwgDrawing], int]:
        """List drawings for a project with pagination and filters."""
        return await self.drawing_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status_filter=status_filter,
        )

    async def delete_drawing(self, drawing_id: uuid.UUID) -> None:
        """Delete a drawing and all associated files (upload, entities, thumbnails)."""
        drawing = await self.get_drawing(drawing_id)

        # Remove the uploaded drawing file
        if drawing.file_path and os.path.exists(drawing.file_path):
            try:
                os.remove(drawing.file_path)
            except OSError:
                logger.warning("Could not delete file: %s", drawing.file_path)

        # Remove entities and thumbnail files for all versions
        versions = await self.version_repo.list_for_drawing(drawing_id)
        entities_dir = _get_entities_dir()
        thumb_dir = os.path.join(
            os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data")), "dwg_thumbnails"
        )
        for version in versions:
            if version.entities_key:
                ent_path = os.path.join(entities_dir, version.entities_key)
                if os.path.exists(ent_path):
                    try:
                        os.remove(ent_path)
                    except OSError:
                        logger.warning("Could not delete entities file: %s", ent_path)

        # Remove thumbnail file referenced by the drawing
        if drawing.thumbnail_key:
            thumb_path = os.path.join(thumb_dir, drawing.thumbnail_key)
            if os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except OSError:
                    logger.warning("Could not delete thumbnail file: %s", thumb_path)

        await self.drawing_repo.delete(drawing_id)
        logger.info("Drawing deleted: %s", drawing_id)

    # ── Drawing version & entities ──────────────────────────────────────

    async def get_latest_version(self, drawing_id: uuid.UUID) -> DwgDrawingVersion | None:
        """Get the latest version for a drawing."""
        return await self.version_repo.get_latest_for_drawing(drawing_id)

    async def get_entities(
        self,
        drawing_id: uuid.UUID,
        *,
        visible_layers: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Load parsed entities from storage, optionally filtered by visible layers."""
        version = await self.version_repo.get_latest_for_drawing(drawing_id)
        if version is None or version.entities_key is None:
            return []

        entities_path = os.path.join(_get_entities_dir(), version.entities_key)
        if not os.path.exists(entities_path):
            return []

        try:
            with open(entities_path, encoding="utf-8") as f:
                entities = json.load(f)
        except FileNotFoundError:
            logger.warning("Entities file missing for drawing %s: %s", drawing_id, entities_path)
            return []
        except json.JSONDecodeError as exc:
            logger.error(
                "Corrupt entities JSON for drawing %s: %s", drawing_id, exc,
            )
            return []
        except Exception:
            logger.exception("Failed to load entities for drawing %s", drawing_id)
            return []

        # Filter by visible layers if specified
        if visible_layers is not None:
            visible_set = set(visible_layers)
            entities = [e for e in entities if e.get("layer", "0") in visible_set]

        # Normalize entity format for frontend consumption:
        # Backend stores {entity_type, geometry_data: {…}} but frontend
        # expects flat {type, id, start, end, vertices, …} structure.
        return [_normalize_entity(e, i) for i, e in enumerate(entities)]

    async def get_thumbnail_svg(self, drawing_id: uuid.UUID) -> str | None:
        """Load SVG thumbnail content for a drawing."""
        drawing = await self.get_drawing(drawing_id)
        if not drawing.thumbnail_key:
            return None

        thumb_dir = os.path.join(
            os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data")), "dwg_thumbnails"
        )
        thumb_path = os.path.join(thumb_dir, drawing.thumbnail_key)
        if not os.path.exists(thumb_path):
            return None

        try:
            with open(thumb_path, encoding="utf-8") as f:
                return f.read()
        except Exception:
            logger.exception("Failed to load thumbnail for drawing %s", drawing_id)
            return None

    async def update_layer_visibility(
        self,
        drawing_id: uuid.UUID,
        layer_updates: dict[str, bool],
    ) -> DwgDrawingVersion | None:
        """Toggle layer visibility in the latest drawing version."""
        version = await self.version_repo.get_latest_for_drawing(drawing_id)
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No drawing version found",
            )

        # Normalize layers to list format (legacy data may be stored as dict)
        raw = version.layers
        if isinstance(raw, dict):
            layers_list = list(raw.values()) if raw else []
        else:
            layers_list = list(raw) if raw else []

        for layer_info in layers_list:
            name = layer_info.get("name", "")
            if name in layer_updates:
                layer_info["visible"] = layer_updates[name]

        await self.version_repo.update_fields(version.id, layers=layers_list)
        await self.session.refresh(version)
        return version

    # ── Annotation CRUD ─────────────────────────────────────────────────

    async def create_annotation(
        self,
        data: DwgAnnotationCreate,
        user_id: str,
    ) -> DwgAnnotation:
        """Create a new annotation on a drawing."""
        # Verify drawing exists
        await self.get_drawing(data.drawing_id)

        item = DwgAnnotation(
            project_id=data.project_id,
            drawing_id=data.drawing_id,
            drawing_version_id=data.drawing_version_id,
            annotation_type=data.annotation_type,
            geometry=data.geometry,
            text=data.text,
            color=data.color,
            line_width=data.line_width,
            measurement_value=data.measurement_value,
            measurement_unit=data.measurement_unit,
            linked_boq_position_id=data.linked_boq_position_id,
            linked_task_id=data.linked_task_id,
            linked_punch_item_id=data.linked_punch_item_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        item = await self.annotation_repo.create(item)
        logger.info(
            "Annotation created: %s type=%s drawing=%s",
            item.id,
            data.annotation_type,
            data.drawing_id,
        )
        return item

    async def get_annotation(self, annotation_id: uuid.UUID) -> DwgAnnotation:
        """Get annotation by ID. Raises 404 if not found."""
        item = await self.annotation_repo.get_by_id(annotation_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation not found",
            )
        return item

    async def list_annotations(
        self,
        drawing_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        annotation_type: str | None = None,
    ) -> tuple[list[DwgAnnotation], int]:
        """List annotations for a drawing with pagination and filters."""
        return await self.annotation_repo.list_for_drawing(
            drawing_id,
            offset=offset,
            limit=limit,
            annotation_type=annotation_type,
        )

    async def update_annotation(
        self,
        annotation_id: uuid.UUID,
        data: DwgAnnotationUpdate,
    ) -> DwgAnnotation:
        """Update annotation fields."""
        item = await self.get_annotation(annotation_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return item

        await self.annotation_repo.update_fields(annotation_id, **fields)
        await self.session.refresh(item)

        logger.info("Annotation updated: %s (fields=%s)", annotation_id, list(fields.keys()))
        return item

    async def delete_annotation(self, annotation_id: uuid.UUID) -> None:
        """Delete an annotation."""
        await self.get_annotation(annotation_id)  # Raises 404 if not found
        await self.annotation_repo.delete(annotation_id)
        logger.info("Annotation deleted: %s", annotation_id)

    async def link_annotation_to_boq(
        self,
        annotation_id: uuid.UUID,
        position_id: str,
    ) -> DwgAnnotation:
        """Link an annotation to a BOQ position."""
        item = await self.get_annotation(annotation_id)

        await self.annotation_repo.update_fields(
            annotation_id, linked_boq_position_id=position_id
        )
        await self.session.refresh(item)

        logger.info("Annotation %s linked to BOQ position %s", annotation_id, position_id)
        return item

    # ── Pins (task/punchlist) ───────────────────────────────────────────

    async def get_pins(self, drawing_id: uuid.UUID) -> list[DwgAnnotation]:
        """Get annotations linked to tasks or punchlist items for a drawing."""
        return await self.annotation_repo.list_pins_for_drawing(drawing_id)
