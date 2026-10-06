# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The spreadsheet a built module with ``export`` on hands out.

A generated router selects the rows exactly as its list does, with the same
project access rule, and passes them here. This module only turns rows into a
file: it decides nothing about who may see which row, so the file can never
hold more than the list would have shown.

What it does add is readability. A link column holds an id, which means
nothing in a spreadsheet, so it is written as the linked record's name -
but only where the caller may see that record, through the same
:func:`~app.modules.module_builder.links.labels_for` the list screen uses.
Where they may not, the id is written, which is what the list API returns
for that row anyway. Status codes are written as their labels.

Every text cell passes :func:`~app.core.csv_safety.neutralise_formula`: the
values are whatever users typed, and a cell starting with ``=`` is a formula
to whoever opens the file. Numbers do not: ``-5.00`` is a credit, not a
formula, and an apostrophe in front of it turns it into text. A workbook
cannot hold most control characters at all, so those are dropped from its
text cells first; a vertical tab pasted from a word processor would otherwise
fail the whole download.

:func:`export_response` and :data:`MAX_EXPORT_ROWS` are imported by name by
modules installed on servers. Their signatures only ever gain optional
arguments.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csv_safety import neutralise_formula
from app.modules.module_builder import links

# The most rows one export writes. A register past this is not read in a
# spreadsheet, and the cap keeps one request from holding the whole table in
# memory on a 3 GB server. A response that hit it says so in a header.
MAX_EXPORT_ROWS = 10_000

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TRUNCATED_HEADER = "X-Export-Truncated"

# The characters a workbook refuses, as openpyxl's ``ILLEGAL_CHARACTERS_RE``
# lists them (a test keeps the two equal). Copied rather than imported, so
# that loading a module with export on does not load openpyxl.
_NOT_IN_A_WORKBOOK = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")


async def export_response(
    session: AsyncSession,
    user_id: object,
    spec_path: Path,
    rows: Sequence[Any],
    fmt: str,
    *,
    total: int | None = None,
) -> Response:
    """Render ``rows`` of the module described by ``spec_path`` as a download.

    Args:
        session: The request's database session.
        user_id: The caller, for the link labels they may see.
        spec_path: The module's ``spec.json``.
        rows: The records, already selected under the list's access rule.
        fmt: ``"csv"`` or ``"xlsx"``.
        total: How many rows matched before the cap, to flag a cut file.
    """
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    key = str(spec.get("key") or "export")
    header, table = await rows_for_export(session, user_id, spec, rows, native=fmt == "xlsx")
    if fmt == "xlsx":
        content = _xlsx(header, table, title=key)
        media_type = XLSX_MEDIA_TYPE
    else:
        content = _csv(header, table)
        media_type = "text/csv; charset=utf-8"
    headers = {"Content-Disposition": f'attachment; filename="{key}.{"xlsx" if fmt == "xlsx" else "csv"}"'}
    if total is not None and total > len(rows):
        headers[TRUNCATED_HEADER] = f"{len(rows)}/{total}"
    return Response(content=content, media_type=media_type, headers=headers)


async def rows_for_export(
    session: AsyncSession,
    user_id: object,
    spec: dict[str, Any],
    rows: Sequence[Any],
    *,
    native: bool,
) -> tuple[list[str], list[list[Any]]]:
    """The header and the cells, in field order.

    ``native`` keeps dates, numbers and booleans as values for a workbook;
    otherwise every cell is text for CSV.
    """
    entity = spec.get("entity") or {}
    fields: list[dict[str, Any]] = list(entity.get("fields") or [])
    scoped = bool(entity.get("project_scoped"))
    status = ((spec.get("features") or {}).get("status")) or None
    state_labels = {s["code"]: s["label"] for s in status["states"]} if status else {}

    labels: dict[str, dict[uuid.UUID, str]] = {}
    for field in fields:
        if field.get("type") != "link" or not field.get("target"):
            continue
        ids = {getattr(r, field["name"], None) for r in rows} - {None}
        labels[field["name"]] = await links.labels_for(session, user_id, field["target"], ids) if ids else {}

    projects: dict[Any, str] = {}
    if scoped and rows:
        projects = await _project_names(session, {r.project_id for r in rows})

    header: list[str] = []
    if scoped:
        header.append("Project")
    header += [str(f.get("label") or f["name"]) for f in fields]
    if status:
        header.append("Status")
    header += ["Created", "Updated"]

    table: list[list[Any]] = []
    for row in rows:
        cells: list[Any] = []
        if scoped:
            cells.append(projects.get(row.project_id, str(row.project_id)))
        for field in fields:
            value = getattr(row, field["name"], None)
            if field.get("type") == "link" and value is not None:
                value = labels.get(field["name"], {}).get(value, str(value))
            cells.append(value)
        if status:
            code = getattr(row, "status", None)
            cells.append(state_labels.get(code, code))
        cells += [row.created_at, row.updated_at]
        table.append([_cell(c, native=native) for c in cells])
    return [_text(h, native=native) for h in header], table


async def _project_names(session: AsyncSession, ids: set[Any]) -> dict[Any, str]:
    """Names of the projects the rows sit in. The rows were already access-checked."""
    from app.modules.projects.models import Project

    result = await session.execute(select(Project.id, Project.name).where(Project.id.in_(list(ids))))
    return {pid: name for pid, name in result.all()}


def _cell(value: Any, *, native: bool) -> Any:
    if value is None:
        return "" if not native else None
    if isinstance(value, str):
        return _text(value, native=native)
    if native:
        if isinstance(value, datetime):
            # Workbooks hold no time zone; write the UTC wall time.
            return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, bool | int | float | Decimal | date):
            return value
        return _text(str(value), native=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, int | float | Decimal):
        # A stored number, not text someone typed, so never a formula.
        return str(value)
    return _text(str(value), native=False)


def _text(value: str, *, native: bool) -> str:
    """Text as it may go into the file.

    Control characters go before the formula check, not after: dropped
    afterwards, a leading one would hide an ``=`` behind it from the check and
    then uncover it in the file.
    """
    if native:
        value = _NOT_IN_A_WORKBOOK.sub("", value)
    return neutralise_formula(value)


def _csv(header: list[str], table: list[list[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(table)
    # With a byte order mark, so a spreadsheet opened by double click reads
    # the labels and values people typed in their own script as UTF-8.
    return buffer.getvalue().encode("utf-8-sig")


def _xlsx(header: list[str], table: list[list[Any]], *, title: str) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    # A sheet title is at most 31 characters; a module key is an identifier,
    # so it carries none of the characters a title may not.
    sheet.title = title[:31]
    sheet.append(header)
    for line in table:
        # rows_for_export already dropped these; a direct caller may not have.
        sheet.append([_NOT_IN_A_WORKBOOK.sub("", c) if isinstance(c, str) else c for c in line])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()
