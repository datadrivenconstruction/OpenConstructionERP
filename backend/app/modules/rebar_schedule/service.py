# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rebar schedule business logic.

Two ways in, and the difference is deliberate. :meth:`RebarScheduleService.preview`
parses and validates and stores nothing, so an estimator can look at what a
file says and what is wrong with it before committing to it.
:meth:`RebarScheduleService.import_file` does the same work and then stores the
result together with its findings.

A file that fails validation is still stored. Refusing it would leave the
operator with a report and nothing to point it at; storing it lets each finding
sit against the shape it came from, and ``validation_status`` on the import row
says plainly that the file is not clean.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.validation.engine import Severity, ValidationEngine, ValidationReport, rule_registry
from app.modules.rebar_schedule import events
from app.modules.rebar_schedule.abs_format import (
    AbsError,
    AbsFile,
    AbsRecord,
    parse_file,
    read_coordinates,
    read_segments,
    read_turns,
)
from app.modules.rebar_schedule.models import RebarScheduleImport, RebarShape
from app.modules.rebar_schedule.repository import RebarImportRepository, RebarShapeRepository
from app.modules.rebar_schedule.validators import RULE_SET

logger = logging.getLogger(__name__)

#: Findings carried back to the caller. A file of a thousand shapes produces
#: nine passing rows per shape, and none of them tells anyone anything.
MAX_FINDINGS_RETURNED = 500


class RebarScheduleError(Exception):
    """A rebar schedule operation could not be completed."""


def _as_decimal(value: str | None) -> Decimal | None:
    """Coerce an ABS field value to a number, or ``None``."""
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


def _as_int(value: str | None) -> int | None:
    """Coerce an ABS field value to a whole number, or ``None``."""
    number = _as_decimal(value)
    if number is None:
        return None
    try:
        return int(number)
    except (ValueError, OverflowError):
        return None


def geometry_payload(record: AbsRecord) -> dict[str, Any] | None:
    """Render a record's geometry into a shape a viewer can draw.

    The three geometries the standard defines are genuinely different, so they
    are tagged rather than flattened into one list: a planar shape is legs and
    angles, a spatial bar is a run of vertices, a helix is a planar shape plus
    turn/pitch pairs.

    Args:
        record: A parsed record.

    Returns:
        The geometry as JSON-safe data, or ``None`` when the record carries no
        geometry block. A record with no geometry is legitimate - the standard
        asks that a shape it cannot describe still be exported, with the header
        and the checksum and no geometry block.
    """
    block = record.geometry
    if block is None:
        return None
    if record.group == "BF3D":
        return {
            "kind": "coordinates",
            "vertices": [[str(x), str(y), str(z)] for x, y, z in read_coordinates(block)],
        }
    segments = [
        {
            "length_mm": None if seg.length_mm is None else str(seg.length_mm),
            "radius_mm": None if seg.radius_mm is None else str(seg.radius_mm),
            "angle_deg": None if seg.angle_deg is None else str(seg.angle_deg),
            "trailing_angle_deg": (None if seg.trailing_angle_deg is None else str(seg.trailing_angle_deg)),
        }
        for seg in read_segments(block)
    ]
    if record.group == "BFWE":
        return {
            "kind": "turns",
            "segments": segments,
            "turns": [[str(count), str(pitch)] for count, pitch in read_turns(block)],
        }
    payload: dict[str, Any] = {"kind": "segments", "segments": segments}
    if block.axis:
        payload["bent_axis"] = block.axis
    return payload


def block_layout(record: AbsRecord) -> str:
    """The record's block identifiers in order, e.g. ``"HGC"`` or ``"HGyYYXXC"``."""
    return "".join(block.kind + (block.axis or "") for block in record.blocks)


class RebarScheduleService:
    """Import, validate, read back and re-export rebar bending schedules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.imports = RebarImportRepository(session)
        self.shapes = RebarShapeRepository(session)
        self.engine = ValidationEngine(rule_registry)

    # ── Parsing and validation ────────────────────────────────────────────

    @staticmethod
    def parse(content: bytes | str) -> AbsFile:
        """Parse ABS content.

        Args:
            content: File bytes, or already-decoded text.

        Returns:
            The parsed file.

        Raises:
            RebarScheduleError: The content is not readable as ABS. The message
                names the line, so the caller can point at it.
        """
        try:
            return parse_file(content)
        except AbsError as exc:
            raise RebarScheduleError(str(exc)) from exc

    async def validate(
        self,
        parsed: AbsFile,
        *,
        project_id: uuid.UUID | None = None,
        target_id: str = "",
        locale: str | None = None,
    ) -> ValidationReport:
        """Run the ``bvbs_abs`` rule set over parsed records.

        Args:
            parsed: A parsed file.
            project_id: Project the file belongs to, for project-scoped rules.
            target_id: Identifier recorded on the report.
            locale: Locale for the rule messages.

        Returns:
            The validation report.
        """
        return await self.engine.validate(
            data={"records": parsed.records, "encoding": parsed.encoding},
            rule_sets=[RULE_SET],
            target_type="rebar_schedule",
            target_id=target_id,
            project_id=None if project_id is None else str(project_id),
            metadata={"locale": locale} if locale else {},
        )

    @staticmethod
    def summarise(report: ValidationReport) -> dict[str, Any]:
        """Reduce a report to counts plus the failing rows.

        Args:
            report: A validation report.

        Returns:
            ``status``, the per-severity counts, and the failing results as
            plain dictionaries, capped at :data:`MAX_FINDINGS_RETURNED`.
        """
        failing = [item for item in report.results if not item.passed and not item.is_engine_error]
        counts = {Severity.ERROR: 0, Severity.WARNING: 0, Severity.INFO: 0}
        for item in failing:
            counts[item.severity] = counts.get(item.severity, 0) + 1
        if counts[Severity.ERROR]:
            status = "errors"
        elif counts[Severity.WARNING]:
            status = "warnings"
        elif counts[Severity.INFO]:
            status = "info"
        else:
            status = "passed"
        return {
            "status": status,
            "error_count": counts[Severity.ERROR],
            "warning_count": counts[Severity.WARNING],
            "info_count": counts[Severity.INFO],
            "findings": [
                {
                    "rule_id": item.rule_id,
                    "rule_name": item.rule_name,
                    "severity": str(item.severity),
                    "category": str(item.category),
                    "passed": item.passed,
                    "message": item.message,
                    "element_ref": item.element_ref,
                    "suggestion": item.suggestion,
                }
                for item in failing[:MAX_FINDINGS_RETURNED]
            ],
        }

    @staticmethod
    def total_weight(parsed: AbsFile) -> Decimal | None:
        """Total steel weight of a file, in kg.

        The header carries the weight of one shape and the number of shapes, so
        the total is the sum of their products. Returns ``None`` when no record
        carries both, rather than a misleading zero.
        """
        total = Decimal(0)
        seen = False
        for record in parsed.records:
            each = record.header_number("e")
            count = record.header_number("n")
            if each is None or count is None:
                continue
            total += each * count
            seen = True
        return total if seen else None

    # ── Import ────────────────────────────────────────────────────────────

    async def preview(self, content: str, *, locale: str | None = None) -> dict[str, Any]:
        """Parse and validate without storing anything.

        Args:
            content: The file's text.
            locale: Locale for the rule messages.

        Returns:
            The record count, the encoding, the total weight, a row per shape
            and the validation summary.
        """
        parsed = self.parse(content)
        report = await self.validate(parsed, locale=locale)
        return {
            "record_count": len(parsed),
            "encoding": parsed.encoding,
            "total_weight_kg": self.total_weight(parsed),
            "shapes": [
                {
                    "line_no": record.line_no,
                    "super_group": record.group,
                    "drawing_ref": record.header_value("r"),
                    "position": record.header_value("p"),
                    "length_mm": _as_decimal(record.header_value("l")),
                    "quantity": _as_int(record.header_value("n")),
                    "weight_kg": _as_decimal(record.header_value("e")),
                    "diameter_mm": _as_decimal(record.header_value("d")),
                    "steel_grade": record.header_value("g"),
                    "checksum_ok": record.checksum_ok,
                    "block_layout": block_layout(record),
                }
                for record in parsed.records
            ],
            "validation": self.summarise(report),
        }

    async def import_file(
        self,
        project_id: uuid.UUID,
        filename: str,
        content: bytes,
        *,
        created_by: str | None = None,
        locale: str | None = None,
    ) -> dict[str, Any]:
        """Import an ABS file into a project.

        Re-importing bytes already imported into this project returns the
        existing import untouched, flagged as a duplicate. Bending schedules
        get re-sent as a matter of routine and a second copy of four hundred
        shapes is worse than no import at all.

        Args:
            project_id: Project to import into.
            filename: The uploaded file's name, kept for the audit trail.
            content: The uploaded bytes.
            created_by: Id of the user importing.
            locale: Locale for the rule messages.

        Returns:
            The stored import, the validation summary and whether the file was
            a duplicate.

        Raises:
            RebarScheduleError: The content is not readable as ABS.
        """
        digest = hashlib.sha256(content).hexdigest()
        existing = await self.imports.get_by_content(project_id, digest)
        if existing is not None:
            return {
                "import_record": existing,
                "validation": {
                    "status": existing.validation_status,
                    "error_count": existing.error_count,
                    "warning_count": existing.warning_count,
                    "info_count": 0,
                    "findings": [],
                },
                "duplicate": True,
            }

        parsed = self.parse(content)
        report = await self.validate(parsed, project_id=project_id, target_id=filename, locale=locale)
        summary = self.summarise(report)

        record = RebarScheduleImport(
            project_id=project_id,
            filename=filename,
            content_sha256=digest,
            encoding=parsed.encoding,
            record_count=len(parsed),
            total_weight_kg=self.total_weight(parsed),
            validation_status=summary["status"],
            error_count=summary["error_count"],
            warning_count=summary["warning_count"],
            created_by=created_by,
        )
        await self.imports.add(record)

        await self.shapes.add_all(
            [self._to_shape(record.id, project_id, parsed_record) for parsed_record in parsed.records]
        )

        event_bus.publish_detached(
            events.SCHEDULE_IMPORTED,
            data={
                "import_id": str(record.id),
                "project_id": str(project_id),
                "filename": filename,
                "record_count": record.record_count,
                "validation_status": record.validation_status,
                "user_id": created_by,
            },
            source_module="rebar_schedule",
        )
        if summary["error_count"]:
            event_bus.publish_detached(
                events.SCHEDULE_HAS_ERRORS,
                data={
                    "import_id": str(record.id),
                    "project_id": str(project_id),
                    "error_count": summary["error_count"],
                },
                source_module="rebar_schedule",
            )
        return {"import_record": record, "validation": summary, "duplicate": False}

    @staticmethod
    def _to_shape(import_id: uuid.UUID, project_id: uuid.UUID, record: AbsRecord) -> RebarShape:
        """Map one parsed record onto a persistable shape row."""
        return RebarShape(
            import_id=import_id,
            project_id=project_id,
            line_no=record.line_no,
            super_group=record.group,
            project_ref=record.header_value("j"),
            drawing_ref=record.header_value("r"),
            drawing_index=record.header_value("i"),
            position=record.header_value("p"),
            length_mm=_as_decimal(record.header_value("l")),
            quantity=_as_int(record.header_value("n")),
            weight_kg=_as_decimal(record.header_value("e")),
            diameter_mm=_as_decimal(record.header_value("d")),
            steel_grade=record.header_value("g"),
            bending_roller_mm=_as_decimal(record.header_value("s")),
            mesh_type=record.header_value("m"),
            width_mm=_as_decimal(record.header_value("b")),
            height_mm=_as_decimal(record.header_value("h")),
            layer=_as_int(record.header_value("a")),
            stagger_group=record.header_value("c"),
            geometry=geometry_payload(record),
            block_layout=block_layout(record),
            checksum_ok=record.checksum_ok,
            raw=record.raw,
        )

    # ── Read back ─────────────────────────────────────────────────────────

    async def get_import(self, import_id: uuid.UUID) -> RebarScheduleImport:
        """Get one import, or raise when it does not exist."""
        record = await self.imports.get_by_id(import_id)
        if record is None:
            raise RebarScheduleError(f"Import {import_id} not found")
        return record

    async def list_imports(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        validation_status: str | None = None,
    ) -> tuple[list[RebarScheduleImport], int]:
        """List a project's imports."""
        return await self.imports.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            validation_status=validation_status,
        )

    async def list_shapes(
        self,
        import_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        super_group: str | None = None,
    ) -> tuple[list[RebarShape], int]:
        """List one import's shapes, in source order."""
        return await self.shapes.list_for_import(
            import_id,
            offset=offset,
            limit=limit,
            super_group=super_group,
        )

    async def cutting_summary(self, import_id: uuid.UUID) -> list[dict[str, Any]]:
        """Bars and steel weight per diameter, for ordering and cutting.

        Returns:
            One row per bar diameter: ``diameter_mm``, ``bars``, ``weight_kg``.
        """
        return [
            {"diameter_mm": diameter, "bars": bars, "weight_kg": weight}
            for diameter, bars, weight in await self.shapes.weight_by_diameter(import_id)
        ]

    async def delete_import(self, import_id: uuid.UUID) -> None:
        """Delete an import and its shapes."""
        record = await self.get_import(import_id)
        project_id = record.project_id
        filename = record.filename
        await self.imports.delete(record)
        event_bus.publish_detached(
            events.SCHEDULE_DELETED,
            data={
                "import_id": str(import_id),
                "project_id": str(project_id),
                "filename": filename,
            },
            source_module="rebar_schedule",
        )

    # ── Export ────────────────────────────────────────────────────────────

    async def export(self, import_id: uuid.UUID, *, super_group: str | None = None) -> bytes:
        """Write an import's shapes back out as an ABS file.

        Each shape is written from the source line it was parsed from, so a
        file exported without filtering is byte-for-byte the file that came in.
        That is the point: the checksum covers exact characters, and a bending
        shop that receives a re-rendered file cannot tell a normalisation from
        an edit.

        Args:
            import_id: The import to export.
            super_group: Export only one super-group, e.g. only the meshes.

        Returns:
            The file's bytes, with CRLF record terminators.
        """
        rows, _ = await self.shapes.list_for_import(import_id, limit=1_000_000, super_group=super_group)
        text = "".join(f"{row.raw}\r\n" for row in rows)
        try:
            return text.encode("ascii")
        except UnicodeEncodeError:
            logger.warning("Rebar schedule export for %s holds non-ASCII characters", import_id)
            return text.encode("cp1252", errors="replace")


__all__ = [
    "MAX_FINDINGS_RETURNED",
    "RebarScheduleError",
    "RebarScheduleService",
    "block_layout",
    "geometry_payload",
]
