# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Digest of a record form as the hand-written builders described it, for golden tests.

A PDF is a pure function of the record form it is drawn from (plus the workspace
look), so an equal digest means an identical PDF. The digest fails loudly when a
standard form sets a field only layouts use, so a migrated document cannot drift
into a new look while keeping the old words.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

#: Fields the hand-written forms had; layout-only fields must keep their defaults on a standard form.
FORM_KEYS = (
    "title",
    "number",
    "project_label",
    "status_text",
    "subject",
    "grid",
    "blocks",
    "page_label",
    "generated_label",
    "generated",
    "doc_type",
)
BLOCK_KEYS = ("title", "kind", "text", "empty_text", "rows", "weights", "right_aligned", "keep_together", "total_rows")


def legacy_shape(record: Any) -> dict[str, Any]:
    """The form as the hand-written builders described it; fails if a layout-only field is set."""
    for f in dataclasses.fields(record):
        if f.name not in FORM_KEYS:
            assert getattr(record, f.name) == f.default, f"standard form sets layout field {f.name}"
    data = {key: dataclasses.asdict(record)[key] for key in FORM_KEYS if key != "blocks"}
    blocks = []
    for block in record.blocks:
        for f in dataclasses.fields(block):
            if f.name not in BLOCK_KEYS:
                assert getattr(block, f.name) == f.default, f"standard block sets layout field {f.name}"
        blocks.append({key: dataclasses.asdict(block)[key] for key in BLOCK_KEYS})
    data["blocks"] = blocks
    return data


def digest(record: Any) -> str:
    """SHA-256 of :func:`legacy_shape`."""
    payload = json.dumps(legacy_shape(record), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def regenerate(path: Path, cases: Iterable[tuple[str, Callable[[], Any]]]) -> None:
    """Write the digests of *cases* to *path* (only on an intended change of the printed form)."""
    path.write_text(
        json.dumps({name: digest(build()) for name, build in cases}, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
