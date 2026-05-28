"""‌⁠‍DWG Takeoff service — business logic.

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

from app.database import async_session_factory
from app.modules.dwg_takeoff.models import (
    DwgAnnotation,
    DwgDrawing,
    DwgDrawingVersion,
    DwgEntityGroup,
)
from app.modules.dwg_takeoff.repository import (
    DwgAnnotationRepository,
    DwgDrawingRepository,
    DwgDrawingVersionRepository,
    DwgEntityGroupRepository,
)
from app.modules.dwg_takeoff.schemas import (
    DwgAnnotationCreate,
    DwgAnnotationUpdate,
    DwgEntityGroupCreate,
)

logger = logging.getLogger(__name__)


# ── DWG version sniff & gating (Indian-user stability ticket 2026-05-13) ────


# AutoCAD R14 (1997) is the oldest format we will hand to DDC. Older
# versions are exotic and DDC genuinely cannot read them. Anything
# between R14 and R18 sometimes works and sometimes does not — we
# used to pre-emptively reject R14-R17 to spare users a misleading
# "empty output" error, but the 2026-05-14 bench showed several
# R16/R17 files DO convert successfully, so we now let DDC have a
# go and surface its real error if it fails.
_DWG_MIN_SUPPORTED_VERSION_CODE = "AC1014"

# Human-readable labels for the DWG magic-byte version codes we care
# about. The mapping comes from Open Design Alliance's specs.
_DWG_VERSION_LABELS: dict[str, str] = {
    "AC1014": "AutoCAD R14 (1997)",
    "AC1015": "AutoCAD 2000 (R15)",
    "AC1018": "AutoCAD 2004 (R16)",
    "AC1021": "AutoCAD 2007 (R17)",
    "AC1024": "AutoCAD 2010 (R18)",
    "AC1027": "AutoCAD 2013 (R19)",
    "AC1032": "AutoCAD 2018 (R22)",
}


def _sniff_dwg_version(path: str) -> tuple[str | None, str]:
    """Read the 6-byte DWG magic prefix and return ``(code, label)``.

    Returns ``(None, "")`` for anything that doesn't match the
    ``AC\\d{4}`` pattern — that includes:

    * Renamed PDFs (start with ``%PDF-``)
    * Renamed ZIPs (start with ``PK\\x03\\x04``)
    * Empty / truncated files
    * Files whose first 6 bytes are non-ASCII or arbitrary text

    Without this guard, the upstream DDC DwgExporter spends 90+ s
    chewing on the garbage input and then returns a misleading "empty
    output" error to the user. The Indian-user ticket (2026-05-13)
    traced 4 of 5 reported failures to PDF/ZIP files renamed with a
    ``.dwg`` extension by mistake.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(6)
    except OSError:
        return None, ""

    if len(head) < 6:
        return None, ""

    # Must be ASCII first, then match the AC#### pattern.
    try:
        text = head.decode("ascii")
    except UnicodeDecodeError:
        return None, ""

    if not (text.startswith("AC") and text[2:].isdigit()):
        return None, ""

    label = _DWG_VERSION_LABELS.get(text, f"DWG ({text})")
    return text, label


def _looks_like_dxf(head: bytes) -> bool:
    """Return True if a 64-byte header looks like an ASCII or binary DXF.

    Binary DXF files start with the literal ``AutoCAD Binary DXF\\r\\n``
    sentinel (22 bytes, per the DXF reference). ASCII DXF files always
    begin with a group code line — the very first non-whitespace token
    is ``0`` followed by the line break and the ``SECTION`` keyword. We
    accept the broader ``0\\r?\\n\\s*SECTION`` shape because some CAD
    exporters use ``LF`` line endings on Linux and pad with spaces.

    A renamed PDF (``%PDF-``), ZIP (``PK\\x03\\x04``) or DWG (``AC####``)
    will fail this check, so the upload endpoint can return a clean 400
    instead of writing garbage to disk and waiting for the parse failure.
    """
    if not head:
        return False
    # Binary DXF sentinel — case-sensitive per the spec.
    if head.startswith(b"AutoCAD Binary DXF"):
        return True
    # ASCII DXF: skip leading whitespace, then group code "0", newline,
    # then "SECTION" within the first ~60 bytes. ezdxf is more lenient
    # than this but we only need to disambiguate from "this is clearly
    # something else" (PDF / ZIP / DWG / random text).
    stripped = head.lstrip()
    if not stripped.startswith(b"0"):
        return False
    # Scan a small window for the SECTION keyword to handle whitespace /
    # comment variations without bringing in a real DXF parser.
    return b"SECTION" in head[:128]


def _validate_cad_magic_bytes(content: bytes, file_format: str) -> tuple[bool, str]:
    """Sniff the first bytes of an upload and confirm the declared format.

    Returns ``(True, "")`` if the content matches the declared format, or
    ``(False, reason)`` with a user-friendly message otherwise. The upload
    endpoint surfaces this as a 400 so renamed PDFs / ZIPs / images never
    reach disk or the DDC subprocess.

    No i18n here — the message is consumed by the existing error wrapper
    which translates at render time.
    """
    head = content[:128] if content else b""
    if file_format == "dwg":
        code, _ = _sniff_dwg_version_bytes(head)
        if code is None:
            return False, (
                "This file does not look like a valid DWG. If you renamed "
                "a PDF / ZIP / image to .dwg, please upload the original "
                "CAD file instead."
            )
        return True, ""
    if file_format == "dxf":
        if not _looks_like_dxf(head):
            return False, (
                "This file does not look like a valid DXF. The file must "
                "start with a DXF group code (ASCII) or the "
                "'AutoCAD Binary DXF' sentinel."
            )
        return True, ""
    # Unknown format slips through — caller has already rejected by
    # extension by the time we get here.
    return True, ""


def _sniff_dwg_version_bytes(head: bytes) -> tuple[str | None, str]:
    """In-memory variant of :func:`_sniff_dwg_version` for upload streams.

    Operates on already-read bytes so we don't have to write the file to
    disk before deciding whether to accept it.
    """
    if len(head) < 6:
        return None, ""
    try:
        text = head[:6].decode("ascii")
    except UnicodeDecodeError:
        return None, ""
    if not (text.startswith("AC") and text[2:].isdigit()):
        return None, ""
    label = _DWG_VERSION_LABELS.get(text, f"DWG ({text})")
    return text, label


def _dwg_version_too_old(code: str | None) -> bool:
    """Return True if a sniffed DWG version code predates R18 (2010).

    ``None`` is the "couldn't sniff" sentinel — we say False (not too
    old) so the caller's downstream "is this a real DWG at all?"
    check fires first with the friendlier error message. Non-numeric
    tails are also tolerated as forward-compat: a future AC#### we
    don't recognise gets a chance instead of a blanket refusal.
    """
    if code is None:
        return False
    if not (code.startswith("AC") and code[2:].isdigit()):
        return False
    try:
        version_num = int(code[2:])
        floor_num = int(_DWG_MIN_SUPPORTED_VERSION_CODE[2:])
    except ValueError:
        return False
    return version_num < floor_num


def _normalize_entity(raw: dict[str, Any], index: int) -> dict[str, Any]:
    """‌⁠‍Flatten stored entity format to the shape the frontend DxfViewer expects.

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
    """‌⁠‍Get the upload directory for DWG files."""
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
    thumb_dir = os.path.join(os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data")), "dwg_thumbnails")
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
        self.group_repo = DwgEntityGroupRepository(session)

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

        # Magic-byte validation — reject renamed PDFs/ZIPs/images BEFORE
        # writing them to disk or burning a DB row. The extension check
        # above only confirms the user typed ``.dwg`` / ``.dxf``; this
        # confirms the bytes match. Closes the class of "90+s DDC chew
        # on garbage input" reports from the 2026-05-13 stability ticket
        # for the DXF path too (the previous sniff fired only on DWG).
        ok, reason = _validate_cad_magic_bytes(content, file_format)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=reason,
            )

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

        # Trigger processing.
        #
        # DXF: parsed locally with ezdxf — fast (<2 s for typical
        # drawings), runs inline so the response carries final
        # status=ready / entity counts.
        #
        # DWG: handed to the DDC DwgExporter binary which can take
        # 30-120 s and occasionally hangs / crashes. Awaiting it
        # inline used to exhaust the uvicorn worker pool — a single
        # stuck conversion would queue subsequent uploads behind it
        # until they hit the client's read timeout (observed
        # 2026-05-14: one R16 crash poisoned the next 5+ uploads with
        # HTTP 500 / ReadTimeout). We commit the upload row first so
        # a fresh AsyncSession in the background task can see it,
        # then fire-and-forget the conversion. The frontend already
        # polls /drawings/{id} to observe status transition
        # uploaded → processing → ready/error.
        if file_format == "dxf":
            await self._process_drawing(drawing_id, file_path)
        elif file_format == "dwg":
            await self.session.commit()
            asyncio.create_task(
                _run_dwg_conversion_in_background(drawing_id, file_path),
            )

        await self.session.refresh(drawing)
        return drawing

    async def _process_drawing(self, drawing_id: uuid.UUID, file_path: str) -> None:
        """Process a DXF file: parse layers/entities, generate thumbnail."""
        await self.drawing_repo.update_fields(drawing_id, status="processing")

        # Prepare storage keys
        entities_key = f"{drawing_id}/entities.json"
        thumbnail_key = f"{drawing_id}/thumbnail.svg"

        try:
            result = await asyncio.to_thread(_process_dxf_sync, file_path, entities_key, thumbnail_key)

            # Create drawing version
            version_number = await self.version_repo.get_next_version_number(drawing_id)
            # Treat 0-entity DXFs as a user-visible failure rather than a
            # silent ``ready`` row. Without this the frontend mounts the
            # canvas, sees an empty entity list, and shows an indefinite
            # loading spinner — there's nothing to render and no banner to
            # explain. Surfaced as ``empty`` so an explicit message is
            # shown ("This DXF contains no entities"). DDC- and ezdxf-
            # generated empty files (e.g. mozman/ezdxf empty_handles.dxf
            # fixture, 1.3 KB) both land here.
            entity_count_val = int(result.get("entity_count") or 0)
            is_empty = entity_count_val == 0
            version = DwgDrawingVersion(
                drawing_id=drawing_id,
                version_number=version_number,
                layers=result["layers"],
                entities_key=entities_key,
                entity_count=entity_count_val,
                extents=result["extents"],
                units=result["units"],
                status="empty" if is_empty else "ready",
                metadata_={},
            )
            await self.version_repo.create(version)

            # Update drawing status
            await self.drawing_repo.update_fields(
                drawing_id,
                status="empty" if is_empty else "ready",
                thumbnail_key=thumbnail_key,
                error_message=(
                    "This DXF/DWG contains no drawable entities — the file is empty or contains only metadata."
                    if is_empty
                    else None
                ),
            )

            if is_empty:
                logger.warning(
                    "Drawing %s parsed as empty (0 entities, %d layers) — surfacing status=empty to the user",
                    drawing_id,
                    len(result["layers"]),
                )
            else:
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
        """Process DWG via DDC DwgExporter → Excel → parse entities.

        Pre-conversion stability guards (Indian-user ticket 2026-05-13):

        1. ``_sniff_dwg_version`` checks the 6-byte ``AC####`` magic
           prefix. Renamed PDFs/ZIPs and truncated files are rejected
           here with a clean 422 instead of being handed to the
           converter (which spends 90+ s on them and then returns a
           confusing "empty output" error).

        2. ``_dwg_version_too_old`` rejects DWGs older than AutoCAD
           2010 (R18). DDC's DwgExporter occasionally produces silent
           empty output for R14/R15/R16/R17 files; the upgrade hint
           is a much better UX than "no entities found".
        """
        version_code, version_label = _sniff_dwg_version(file_path)
        if version_code is None:
            await self.drawing_repo.update_fields(
                drawing_id,
                status="error",
                error_message=(
                    "This file does not look like a valid DWG. "
                    "If you renamed a PDF or ZIP archive to .dwg, please "
                    "upload the original CAD file instead."
                ),
            )
            return
        if _dwg_version_too_old(version_code):
            await self.drawing_repo.update_fields(
                drawing_id,
                status="error",
                error_message=(
                    f"{version_label} is older than the supported DWG "
                    f"format. Re-save the file as AutoCAD 2010 (R18) "
                    f"or newer and upload again."
                ),
            )
            return

        try:
            from app.modules.boq.cad_import import (
                build_ddc_args,
                detect_converter_capabilities,
                find_converter,
            )

            converter = find_converter("dwg")
        except ImportError:
            converter = None
            build_ddc_args = None  # type: ignore[assignment]
            detect_converter_capabilities = None  # type: ignore[assignment]

        if converter is None:
            # Actionable install path — the previous message ("Please upload
            # DXF format") hid the fact that DWG conversion is supported and
            # just needs a one-time install. Surfacing the Quantities-page
            # link + the GitHub manual fallback closes the support loop the
            # multi-user reports landed in (the Offline Ready pill on the
            # /dwg-takeoff page also offers a one-click install via the
            # same /v1/takeoff/converters/dwg/install/ endpoint).
            await self.drawing_repo.update_fields(
                drawing_id,
                status="error",
                error_message=(
                    "DWG conversion requires the DDC DwgExporter binary, "
                    "which was not found on this server. Click the "
                    "\"Install converter\" pill at the top right of /dwg-takeoff, "
                    "or download manually from "
                    "https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN. "
                    "DXF files work without the converter."
                ),
            )
            return

        await self.drawing_repo.update_fields(drawing_id, status="processing")

        import subprocess
        from pathlib import Path as _Path

        # DDC DwgExporter → Excel. Compose the CLI through the same
        # capability-aware builder the takeoff router uses so we don't
        # hand v18 flag-driven binaries the legacy positional shape
        # (``<input> <output> -no-collada``) — that returns exit 15 with
        # ``arguments were not expected: ... -no-collada``, the same root
        # cause that previously surfaced as "CAD conversion failed for
        # .rvt" in the CAD/BIM Data Explorer. Once DDC ships a v18
        # DwgExporter this code keeps working without any further patch.
        xlsx_path = file_path.rsplit(".", 1)[0] + "_dwg.xlsx"
        try:
            caps = detect_converter_capabilities("dwg")
            args = build_ddc_args(
                converter,
                _Path(file_path).resolve(),
                caps=caps,
                xlsx_out=_Path(xlsx_path).resolve(),
                # DWG converters historically do not support a mode preset
                # (the takeoff router only emits ``standard`` for RVT/IFC).
                # build_ddc_args' v18 path emits ``-m standard`` only when
                # ``caps.accepts_flag_mode`` is True, which currently fires
                # for RVT — harmless on DWG should DDC adopt it later.
                mode="standard",
                include_no_dae=True,
            )
            proc = await asyncio.to_thread(
                lambda: subprocess.run(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(converter.parent),
                    input=b"\n",
                    timeout=120,
                )
            )
            if not os.path.exists(xlsx_path) or os.path.getsize(xlsx_path) < 100:
                stderr_msg = proc.stderr.decode(errors="replace")[:300] if proc.stderr else ""
                # "Error: converter crashed." is the DDC binary's generic
                # catch-all when it can't initialise (missing runtime,
                # incompatible DWG version DDC's parser doesn't yet
                # support, or an internal exception). Surface an actionable
                # alternative — DXF upload via ezdxf works without DDC.
                if "converter crashed" in stderr_msg.lower():
                    nice_msg = (
                        "The DWG converter could not process this file. "
                        "Try saving the drawing as DXF (AutoCAD → File → "
                        "Save As → AutoCAD DXF) and upload that instead — "
                        "DXF is handled directly without requiring DDC."
                    )
                else:
                    nice_msg = f"DDC DwgExporter produced no output: {stderr_msg}".strip()
                await self.drawing_repo.update_fields(
                    drawing_id,
                    status="error",
                    error_message=nice_msg[:500],
                )
                return
        except subprocess.TimeoutExpired:
            await self.drawing_repo.update_fields(
                drawing_id,
                status="error",
                error_message="DWG conversion timed out (120s limit)",
            )
            return
        except Exception as exc:
            await self.drawing_repo.update_fields(
                drawing_id,
                status="error",
                error_message=f"DWG conversion error: {exc}"[:500],
            )
            return

        # Parse DDC Excel → entities (same format as ezdxf output)
        try:
            from app.modules.dwg_takeoff.ddc_dwg_parser import parse_ddc_dwg_excel

            result = await asyncio.to_thread(parse_ddc_dwg_excel, xlsx_path)

            if result["entity_count"] == 0:
                await self.drawing_repo.update_fields(
                    drawing_id,
                    status="error",
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
                drawing_id,
                result["entity_count"],
                len(result["layers"]),
            )

        except Exception as exc:
            await self.drawing_repo.update_fields(
                drawing_id,
                status="error",
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

    async def update_drawing_scale(
        self,
        drawing_id: uuid.UUID,
        *,
        scale_denominator: float,
        scale_mode: str,
    ) -> DwgDrawing:
        """Persist a drawing's scale denominator + mode.

        The frontend also mirrors this in localStorage for instant feedback,
        but the DB value is the source of truth across devices and users —
        so a takeoff calibrated on a desktop reads correctly when the same
        drawing is opened on a tablet.
        """
        drawing = await self.get_drawing(drawing_id)
        await self.drawing_repo.update_fields(
            drawing_id,
            scale_denominator=scale_denominator,
            scale_mode=scale_mode,
        )
        await self.session.refresh(drawing)
        return drawing

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
        thumb_dir = os.path.join(os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data")), "dwg_thumbnails")
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
                "Corrupt entities JSON for drawing %s: %s",
                drawing_id,
                exc,
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

        thumb_dir = os.path.join(os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data")), "dwg_thumbnails")
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
            thickness=data.thickness,
            layer_name=data.layer_name,
            measurement_value=data.measurement_value,
            measurement_unit=data.measurement_unit,
            scale_override=data.scale_override,
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

        await self.annotation_repo.update_fields(annotation_id, linked_boq_position_id=position_id)
        await self.session.refresh(item)

        logger.info("Annotation %s linked to BOQ position %s", annotation_id, position_id)
        return item

    # ── Pins (task/punchlist) ───────────────────────────────────────────

    async def get_pins(self, drawing_id: uuid.UUID) -> list[DwgAnnotation]:
        """Get annotations linked to tasks or punchlist items for a drawing."""
        return await self.annotation_repo.list_pins_for_drawing(drawing_id)

    # ── Entity Groups (RFC 11) ──────────────────────────────────────────

    async def create_entity_group(
        self,
        data: DwgEntityGroupCreate,
        user_id: str,
    ) -> DwgEntityGroup:
        """Create a saved group of DWG entity ids on a drawing."""
        await self.get_drawing(data.drawing_id)

        item = DwgEntityGroup(
            drawing_id=data.drawing_id,
            name=data.name,
            entity_ids=list(data.entity_ids),
            metadata_=data.metadata,
            created_by=user_id,
        )
        item = await self.group_repo.create(item)
        logger.info(
            "Entity group created: %s drawing=%s n=%d",
            item.id,
            data.drawing_id,
            len(data.entity_ids),
        )
        return item

    async def get_entity_group(self, group_id: uuid.UUID) -> DwgEntityGroup:
        """Get entity group by ID. Raises 404 if not found."""
        item = await self.group_repo.get_by_id(group_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Entity group not found",
            )
        return item

    async def list_entity_groups(
        self,
        drawing_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[DwgEntityGroup], int]:
        """List saved entity groups for a drawing."""
        return await self.group_repo.list_for_drawing(
            drawing_id,
            offset=offset,
            limit=limit,
        )

    async def delete_entity_group(self, group_id: uuid.UUID) -> None:
        """Delete an entity group."""
        await self.get_entity_group(group_id)
        await self.group_repo.delete(group_id)
        logger.info("Entity group deleted: %s", group_id)

    # ── Offline readiness (R3 #9) ───────────────────────────────────────

    @staticmethod
    def get_offline_readiness() -> dict[str, Any]:
        """Probe local DWG converter availability.

        The parser itself (ezdxf + ddc_dwg_parser) is fully local, so the
        only thing that could push the user online is the ``DwgExporter``
        binary needed for the ``.dwg`` path. DXF files already work without
        it. Returns a dict matching :class:`DwgOfflineReadinessResponse`.
        """
        try:
            from app.modules.boq.cad_import import find_converter

            converter = find_converter("dwg")
        except ImportError:
            converter = None

        if converter is None:
            return {
                "ready": False,
                "converter_available": False,
                "version": None,
                "message": ("Install dwg2data to enable offline DWG conversion. DXF files already work without it."),
            }

        version: str | None = None
        try:
            version = converter.name
        except Exception:  # noqa: BLE001 — defensive: filesystem quirks
            version = None

        return {
            "ready": True,
            "converter_available": True,
            "version": version,
            "message": "DWG conversion runs locally on this machine.",
        }


async def _run_dwg_conversion_in_background(
    drawing_id: uuid.UUID,
    file_path: str,
) -> None:
    """Detached DDC conversion task with its own DB session.

    Decouples the slow / occasionally-hanging DDC DwgExporter
    subprocess from the HTTP upload request. The request returns
    immediately with status=uploaded and the conversion progresses
    in the background, persisting status transitions (uploaded →
    processing → ready/error) on a fresh AsyncSession.

    Without this isolation, a single DDC crash or timeout pinned a
    uvicorn worker for up to 120 s and the next 5+ DWG uploads
    queued behind it eventually 500-d on the client side. The
    upload row is committed before this task is spawned so the
    fresh session here can find the row.
    """
    async with async_session_factory() as session:
        try:
            svc = DwgTakeoffService(session)
            await svc._handle_dwg(drawing_id, file_path)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "Background DDC conversion failed for drawing %s",
                drawing_id,
            )
