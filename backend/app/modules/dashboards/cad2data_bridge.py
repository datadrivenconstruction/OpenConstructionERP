"""Bridge between uploaded CAD/BIM files and the snapshot Parquet layer.

T01 responsibility: take a list of uploaded source files, run each
through the appropriate converter, and produce three DataFrames in the
canonical snapshot shape:

* ``entities_df``    — one row per entity, columns ``entity_guid``,
  ``category``, ``source_file_id``, ``attributes`` (dict).
* ``materials_df``   — one row per (entity, material layer), columns
  ``entity_guid``, ``layer_index``, ``material``, ``thickness_mm``.
* ``source_files_df``— one row per uploaded file, columns ``id``,
  ``original_name``, ``format``, ``discipline``, ``entity_count``,
  ``bytes_size``.

Converter support today:
    IFC / RVT  — reuses :func:`app.modules.bim_hub.ifc_processor.process_ifc_file`
                 (DDC cad2data when installed, text-parser fallback otherwise).
    DWG / DGN  — not yet wired; we raise :class:`UnsupportedFormatError`
                 with a localised message. T10 lights these up.

The bridge is format-pluggable: adding a new format = adding a
``_convert_<ext>`` function and a dispatch entry. Everything stays in
one file so the set of supported formats is greppable.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ── Public types ────────────────────────────────────────────────────────────


@dataclass
class UploadedFile:
    """In-memory representation of an uploaded source file.

    Route code wraps each ``UploadFile`` into this shape so the bridge
    does not have to know about FastAPI.
    """

    original_name: str
    extension: str  # lower-case, without the dot: "ifc", "rvt", "dwg", …
    content: bytes
    discipline: str | None = None


@dataclass
class SnapshotBuildResult:
    """Output of :func:`convert_to_snapshot_frames`.

    The three DataFrames share one invariant: every ``entity_guid`` in
    ``materials_df`` appears in ``entities_df`` (referential integrity
    is enforced at build time, not by a FK).
    """

    entities_df: pd.DataFrame
    materials_df: pd.DataFrame
    source_files_df: pd.DataFrame
    summary_stats: dict[str, int] = field(default_factory=dict)
    converter_notes: dict[str, Any] = field(default_factory=dict)

    @property
    def total_entities(self) -> int:
        return int(len(self.entities_df))

    @property
    def total_categories(self) -> int:
        if self.entities_df.empty or "category" not in self.entities_df.columns:
            return 0
        return int(self.entities_df["category"].nunique())


# ── Errors ──────────────────────────────────────────────────────────────────


class BridgeError(RuntimeError):
    """Base for bridge-level failures. Service layer turns these into HTTP 4xx/5xx."""


class UnsupportedFormatError(BridgeError):
    """Raised when no converter is registered for the file's extension."""


class NoEntitiesExtractedError(BridgeError):
    """Raised when every converter produced zero entities.

    Distinguishable from ``UnsupportedFormatError`` because the caller
    ran through a valid format but the file was empty, corrupted, or
    dropped everything. The response to the user is different: upload
    a different file vs. contact support.
    """


# ── Dispatch ────────────────────────────────────────────────────────────────


_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({"ifc", "rvt"})
"""Extensions the bridge knows how to convert today. Adding a new
format means adding its extension here AND a ``_convert_<ext>``
function below, in one commit — the scaffolding test asserts the two
stay in sync."""


def supported_extensions() -> frozenset[str]:
    return _SUPPORTED_EXTENSIONS


def convert_to_snapshot_frames(
    files: list[UploadedFile],
) -> SnapshotBuildResult:
    """Main entry: convert a list of uploaded files into snapshot frames.

    Runs converters sequentially (not in parallel) — the DDC cad2data
    runner is itself a heavy process; two instances on a laptop will
    thrash the CPU. Parallelism is revisited in T10 when federation
    becomes the common case.
    """
    if not files:
        raise NoEntitiesExtractedError(
            "No source files supplied — nothing to convert."
        )

    all_entities: list[pd.DataFrame] = []
    all_materials: list[pd.DataFrame] = []
    source_file_rows: list[dict[str, Any]] = []
    converter_notes: dict[str, Any] = {}

    for file in files:
        ext = file.extension.lower().lstrip(".")
        if ext not in _SUPPORTED_EXTENSIONS:
            raise UnsupportedFormatError(
                f"Format '.{ext}' is not supported yet (file: {file.original_name}). "
                f"Supported: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}."
            )

        source_file_id = str(uuid.uuid4())
        entities_df, materials_df, notes = _dispatch(file, source_file_id, ext)

        if not entities_df.empty:
            all_entities.append(entities_df)
        if not materials_df.empty:
            all_materials.append(materials_df)

        source_file_rows.append(
            {
                "id": source_file_id,
                "original_name": file.original_name,
                "format": ext,
                "discipline": file.discipline,
                "entity_count": int(len(entities_df)),
                "bytes_size": len(file.content),
            },
        )
        if notes:
            converter_notes[source_file_id] = notes

    entities_df = _concat_or_empty(all_entities, _entities_schema())
    materials_df = _concat_or_empty(all_materials, _materials_schema())
    source_files_df = pd.DataFrame(
        source_file_rows,
        columns=[
            "id", "original_name", "format", "discipline",
            "entity_count", "bytes_size",
        ],
    )

    if entities_df.empty:
        raise NoEntitiesExtractedError(
            "Every uploaded file yielded zero entities after conversion. "
            "Check the converter logs for parser warnings, or try a smaller "
            "test file first."
        )

    summary_stats = _build_summary_stats(entities_df)
    return SnapshotBuildResult(
        entities_df=entities_df,
        materials_df=materials_df,
        source_files_df=source_files_df,
        summary_stats=summary_stats,
        converter_notes=converter_notes,
    )


def _dispatch(
    file: UploadedFile, source_file_id: str, ext: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Route one file to the right converter and normalise its output."""
    if ext in {"ifc", "rvt"}:
        return _convert_ifc_or_rvt(file, source_file_id)
    # Guarded at caller — but re-raise defensively so mypy's
    # exhaustiveness narrows correctly.
    raise UnsupportedFormatError(f"No converter registered for .{ext}")  # pragma: no cover


def _convert_ifc_or_rvt(
    file: UploadedFile, source_file_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Hand the bytes to bim_hub's IFC/RVT processor and canonicalise
    its dict output into our DataFrame shape.

    We never keep the raw bytes around longer than necessary — the
    processor writes to a tempdir which we clean up via the
    ``TemporaryDirectory`` context manager.
    """
    # Late import so the dashboards module does not add a hard import
    # cycle back to bim_hub at startup — the loader only needs bim_hub
    # to be loaded before a conversion runs, which the dependency
    # declaration on ``oe_bim_hub`` does not (yet) provide, so the
    # import happens here to keep module load deterministic.
    from app.modules.bim_hub.ifc_processor import process_ifc_file

    ext = file.extension.lower().lstrip(".")

    with tempfile.TemporaryDirectory(prefix="oe-dashboards-convert-") as tmp:
        tmp_path = Path(tmp)
        input_path = tmp_path / f"{source_file_id}.{ext}"
        input_path.write_bytes(file.content)
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        try:
            result = process_ifc_file(
                input_path, output_dir, conversion_depth="standard",
            )
        except Exception as exc:
            logger.warning(
                "dashboards.cad2data.convert_ifc failed for %s: %s",
                file.original_name, type(exc).__name__, exc_info=True,
            )
            raise BridgeError(
                f"Converter failed on '{file.original_name}': {exc}"
            ) from exc

    elements = result.get("elements") or []
    entities_df = _elements_to_entities_df(elements, source_file_id)
    materials_df = _elements_to_materials_df(elements)
    notes = {
        "converter": result.get("conversion_method", "unknown"),
        "raw_element_count": len(elements),
    }
    return entities_df, materials_df, notes


# ── Canonical-shape helpers ────────────────────────────────────────────────


def _entities_schema() -> list[str]:
    return ["entity_guid", "category", "source_file_id", "attributes"]


def _materials_schema() -> list[str]:
    return ["entity_guid", "layer_index", "material", "thickness_mm"]


def _elements_to_entities_df(
    elements: list[dict[str, Any]], source_file_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for elem in elements:
        guid = (
            elem.get("guid")
            or elem.get("global_id")
            or elem.get("entity_guid")
            or str(uuid.uuid4())
        )
        category = _canonical_category(
            elem.get("category") or elem.get("ifc_type") or elem.get("type"),
        )
        attributes = {
            k: v
            for k, v in elem.items()
            if k not in {"guid", "global_id", "entity_guid", "category", "ifc_type", "type", "layers", "materials"}
            and not isinstance(v, (list, dict))
        }
        # Flatten single-level nested scalars from "properties" / "quantities"
        for nested_key in ("properties", "quantities"):
            nested = elem.get(nested_key)
            if isinstance(nested, dict):
                for k, v in nested.items():
                    if not isinstance(v, (list, dict)):
                        attributes[f"{nested_key}.{k}"] = v
        rows.append(
            {
                "entity_guid": str(guid),
                "category": category,
                "source_file_id": source_file_id,
                "attributes": attributes,
            }
        )
    if not rows:
        return pd.DataFrame(columns=_entities_schema())
    return pd.DataFrame(rows, columns=_entities_schema())


def _elements_to_materials_df(elements: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for elem in elements:
        guid = (
            elem.get("guid")
            or elem.get("global_id")
            or elem.get("entity_guid")
        )
        if not guid:
            continue

        layers = elem.get("layers") or elem.get("materials")
        if not isinstance(layers, list):
            continue
        for idx, layer in enumerate(layers):
            if not isinstance(layer, dict):
                continue
            rows.append(
                {
                    "entity_guid": str(guid),
                    "layer_index": idx,
                    "material": str(
                        layer.get("material")
                        or layer.get("name")
                        or layer.get("layer_name")
                        or "unknown",
                    ),
                    "thickness_mm": _safe_float(
                        layer.get("thickness_mm")
                        or layer.get("thickness")
                        or layer.get("thickness_m"),
                    ),
                }
            )
    if not rows:
        return pd.DataFrame(columns=_materials_schema())
    return pd.DataFrame(rows, columns=_materials_schema())


def _canonical_category(raw: object) -> str:
    """Lower-case, strip ``Ifc`` prefix, snake-ish plural.

    Canonicalisation is intentionally light so we don't silently hide a
    category mismatch between formats. Good enough for the sketch:
    "IfcWall" → "wall"; T02 attribute explorer groups by the canonical
    name.
    """
    if raw is None:
        return "unknown"
    s = str(raw).strip()
    if not s:
        return "unknown"
    if s.lower().startswith("ifc") and len(s) > 3:
        s = s[3:]
    return s.lower()


def _safe_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _concat_or_empty(
    frames: list[pd.DataFrame], columns: list[str],
) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


def _build_summary_stats(entities_df: pd.DataFrame) -> dict[str, int]:
    if entities_df.empty or "category" not in entities_df.columns:
        return {}
    counts = entities_df["category"].value_counts().to_dict()
    return {str(k): int(v) for k, v in counts.items()}
