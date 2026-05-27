"""Re-ingest a single BIM model from its on-disk ``original.{ext}``.

Background
----------
The v3.x snapshot-loader produced placeholder rows for the 14 showcase
BIM models: 380 synthetic ``"Walls 1".."Walls 64"`` rows per RVT, all
with ``mesh_ref=NULL`` so the 3D viewer could never bind any of the
5440 numeric Revit ElementIds carved into the DAE.  This script runs
the *real* DDC RvtExporter against the ``original.rvt`` blob that lives
alongside ``geometry.glb`` and replaces the placeholders with the
properly-keyed element rows that should have been there from day one.

Usage
-----
::

    python -m app.scripts.reingest_bim_model <model_id> [--dry-run] \
        [--backup-rows]

* ``--dry-run`` parses the file and reports the new row count without
  touching the database.
* ``--backup-rows`` writes a JSON dump of the current rows to
  ``data/reingest_backup_<model_id>_<timestamp>.json`` BEFORE any DB
  mutation so a botched run is still recoverable.

Exit codes
----------
* ``0`` — success (or dry-run completed).
* ``1`` — model not found in DB.
* ``2`` — ``original.{ext}`` blob missing on disk.
* ``3`` — DDC conversion failed (returned zero elements).
* ``4`` — DB transaction failed.

The script is intentionally self-contained: it reuses the existing
column-mapping logic from :func:`app.modules.boq.cad_import.parse_cad_excel`
and :func:`app.modules.bim_hub.ifc_processor._excel_elements_to_bim_result`
so the re-ingest path is byte-for-byte identical to a fresh upload.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("reingest_bim_model")


# ── Helpers ────────────────────────────────────────────────────────────────


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _serialise_for_backup(value: Any) -> Any:
    """Make a SQLAlchemy row column JSON-serialisable."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# ── Core re-ingest logic ───────────────────────────────────────────────────


async def _resolve_original_path(model_id: uuid.UUID) -> tuple[dict, Path] | None:
    """Look up the model row and locate its ``original.{ext}`` blob.

    Returns ``(model_info_dict, abs_path_to_original)`` or ``None`` when
    the model row is missing.  Raises ``FileNotFoundError`` when the row
    exists but the blob does not.
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.bim_hub import file_storage as bim_file_storage
    from app.modules.bim_hub.models import BIMModel

    async with async_session_factory() as session:
        model = (await session.execute(select(BIMModel).where(BIMModel.id == model_id))).scalar_one_or_none()
        if model is None:
            return None
        info = {
            "id": str(model.id),
            "project_id": str(model.project_id),
            "name": model.name,
            "model_format": (model.model_format or "rvt").lower(),
            "element_count": model.element_count,
            "status": model.status,
        }

    ext = info["model_format"]
    key = bim_file_storage.original_cad_key(info["project_id"], info["id"], ext)
    backend = bim_file_storage._backend()  # noqa: SLF001 — script-only
    if not await backend.exists(key):
        raise FileNotFoundError(
            f"Original CAD blob not found at storage key={key} "
            f"(model_id={info['id']}, ext={ext}). "
            f"Re-upload the file before retrying."
        )
    # LocalStorageBackend exposes _path_for; fall through to bytes-read
    # for any other backend.
    try:
        abs_path = backend._path_for(key)  # noqa: SLF001
        return info, abs_path
    except AttributeError:
        # Non-local backend (S3, etc) — materialise to a temp file.
        raw = await backend.get(key)
        tmp = Path(tempfile.gettempdir()) / f"reingest_{info['id']}{ext}"
        tmp.write_bytes(raw)
        return info, tmp


def _ddc_invocation_v18(
    converter: Path,
    input_path: Path,
    xlsx_out: Path,
    dae_out: Path,
) -> list[tuple[list[str], Path]]:
    """Build the v18.3+ DDC RvtExporter invocations.

    The flag-based CLI introduced in v18.3 supersedes the legacy
    ``[converter, input, output, mode]`` positional form that
    ``_try_cad2data`` still emits.  We invoke twice — once for Excel
    (no geometry) and once for the COLLADA pass (no Excel) — which
    matches ``ifc_processor._try_cad2data``'s two-pass design.
    """
    return [
        (
            [
                str(converter),
                str(input_path),
                "-x",
                str(xlsx_out),
                "--no-dae",
                "-m",
                "standard",
            ],
            xlsx_out,
        ),
        (
            [
                str(converter),
                str(input_path),
                "-d",
                str(dae_out),
                "--no-xlsx",
            ],
            dae_out,
        ),
    ]


def _ddc_invocation_legacy(
    converter: Path,
    input_path: Path,
    xlsx_out: Path,
    dae_out: Path,
) -> list[tuple[list[str], Path]]:
    """Build the legacy DDC ``[exe, input, output, mode]`` invocations."""
    return [
        ([str(converter), str(input_path), str(xlsx_out), "standard"], xlsx_out),
        ([str(converter), str(input_path), str(dae_out)], dae_out),
    ]


def _probe_ddc_cli_style(converter: Path) -> str:
    """Return ``"v18"`` (flag-based) or ``"legacy"`` (positional)."""
    import subprocess

    try:
        proc = subprocess.run(
            [str(converter), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(converter.parent),
            input=b"\n",
            timeout=8,
        )
        text = (proc.stdout + b"\n" + proc.stderr).decode("utf-8", errors="replace")
        if "--no-dae" in text or "--no-xlsx" in text or "-m,     --mode" in text:
            return "v18"
    except Exception:  # noqa: BLE001 — probe failure is non-fatal
        pass
    return "legacy"


def _run_ddc_extraction(
    original_path: Path,
    tmp_dir: Path,
) -> dict[str, Any]:
    """Synchronous DDC + Excel parse + result-shaping pipeline.

    Tries the existing :func:`process_ifc_file` bridge first (which knows
    how to deal with placeholder geometry, DAE bboxes, GLB conversion,
    etc.).  When that returns zero elements we fall back to a direct DDC
    invocation that supports the v18.3+ flag-based CLI — the bridge's
    capability probe over-reports modern support and trips exit-15 on
    v18.3 binaries.  We then feed the resulting xlsx + dae back through
    the existing :func:`_excel_elements_to_bim_result` so the column
    mapping stays in one place.

    Returns the same dict shape :func:`process_ifc_file` produces.
    """
    import subprocess

    from app.modules.bim_hub.ifc_processor import (
        _excel_elements_to_bim_result,
        process_ifc_file,
    )
    from app.modules.boq.cad_import import find_converter, parse_cad_excel

    result = process_ifc_file(original_path, tmp_dir, "standard")
    if result.get("element_count", 0) > 0:
        return result

    ext = original_path.suffix.lower().lstrip(".")
    converter = find_converter(ext)
    if converter is None:
        logger.warning("No DDC converter found for ext=%s — cannot fall back", ext)
        return result

    cli_style = _probe_ddc_cli_style(converter)
    logger.info(
        "Fallback DDC invocation: cli_style=%s, converter=%s",
        cli_style,
        converter,
    )
    xlsx_out = (tmp_dir / "ddc_direct.xlsx").resolve()
    dae_out = (tmp_dir / "geometry.dae").resolve()
    invocations = (_ddc_invocation_v18 if cli_style == "v18" else _ddc_invocation_legacy)(
        converter, original_path, xlsx_out, dae_out
    )

    for args, expected_output in invocations:
        logger.info("Direct DDC call: %s", args)
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(converter.parent),
            input=b"\n",
            timeout=600,
        )
        if proc.returncode != 0:
            logger.warning(
                "Direct DDC call exit %d: %s",
                proc.returncode,
                proc.stderr.decode(errors="replace")[:400],
            )
            # Excel pass is mandatory; DAE pass failure is degraded but OK.
            if expected_output == xlsx_out:
                return {"elements": [], "element_count": 0, "storeys": []}

    if not xlsx_out.exists() or xlsx_out.stat().st_size == 0:
        logger.error("DDC produced no xlsx at %s", xlsx_out)
        return {"elements": [], "element_count": 0, "storeys": []}

    raw_elements = parse_cad_excel(xlsx_out)
    logger.info("Direct DDC: parsed %d raw rows from xlsx", len(raw_elements))

    real_dae_path: Path | None = None
    if dae_out.exists() and dae_out.stat().st_size > 0:
        real_dae_path = dae_out

    shaped = _excel_elements_to_bim_result(
        raw_elements,
        tmp_dir,
        real_dae_path=real_dae_path,
    )
    shaped.setdefault("element_count", len(shaped.get("elements") or []))
    shaped.setdefault("storeys", [])
    shaped.setdefault("disciplines", [])
    return shaped


async def _replace_elements(
    model_id: uuid.UUID,
    result: dict[str, Any],
    *,
    dry_run: bool,
    backup_path: Path | None,
) -> dict[str, Any]:
    """Atomically replace the model's elements with the parsed result."""
    from sqlalchemy import delete, select

    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel

    new_elements = result.get("elements") or []
    new_count = len(new_elements)
    if new_count == 0:
        return {
            "status": "no_elements",
            "old_count": None,
            "new_count": 0,
        }

    async with async_session_factory() as session:
        # 1) Count + (optionally) back up existing rows.
        existing = (await session.execute(select(BIMElement).where(BIMElement.model_id == model_id))).scalars().all()
        old_count = len(existing)
        old_null_mesh_ref = sum(1 for e in existing if e.mesh_ref is None)

        if backup_path is not None and existing:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "id": str(e.id),
                    "model_id": str(e.model_id),
                    "stable_id": e.stable_id,
                    "element_type": e.element_type,
                    "name": e.name,
                    "storey": e.storey,
                    "discipline": e.discipline,
                    "properties": e.properties,
                    "quantities": e.quantities,
                    "geometry_hash": e.geometry_hash,
                    "bounding_box": e.bounding_box,
                    "mesh_ref": e.mesh_ref,
                    "asset_info": e.asset_info,
                    "is_tracked_asset": e.is_tracked_asset,
                }
                for e in existing
            ]
            backup_path.write_text(
                json.dumps(rows, default=_serialise_for_backup, indent=2),
                encoding="utf-8",
            )
            logger.info("Backed up %d existing rows to %s", len(rows), backup_path)

        # 2) Build a representative sample BEFORE mutating anything.
        sample = [
            {
                "stable_id": el.get("stable_id"),
                "name": (el.get("name") or "")[:80],
                "element_type": el.get("element_type"),
                "mesh_ref": el.get("mesh_ref"),
                "family": (el.get("properties") or {}).get("family"),
                "type_name": (el.get("properties") or {}).get("type_name"),
            }
            for el in new_elements[:5]
        ]
        new_null_mesh_ref = sum(1 for el in new_elements if not el.get("mesh_ref"))

        summary = {
            "status": "ok",
            "old_count": old_count,
            "old_null_mesh_ref": old_null_mesh_ref,
            "new_count": new_count,
            "new_null_mesh_ref": new_null_mesh_ref,
            "new_with_mesh_ref": new_count - new_null_mesh_ref,
            "sample": sample,
        }

        if dry_run:
            await session.rollback()
            summary["status"] = "dry_run"
            return summary

        # 3) Mutate inside one transaction.
        try:
            await session.execute(delete(BIMElement).where(BIMElement.model_id == model_id))
            for el in new_elements:
                session.add(
                    BIMElement(
                        model_id=model_id,
                        stable_id=el["stable_id"],
                        element_type=el.get("element_type"),
                        name=el.get("name"),
                        storey=el.get("storey"),
                        discipline=el.get("discipline"),
                        properties=el.get("properties") or {},
                        quantities=el.get("quantities") or {},
                        geometry_hash=el.get("geometry_hash"),
                        bounding_box=el.get("bounding_box"),
                        mesh_ref=el.get("mesh_ref"),
                    )
                )

            # 4) Refresh the model row's denormalised counts.
            model = (await session.execute(select(BIMModel).where(BIMModel.id == model_id))).scalar_one_or_none()
            if model is not None:
                model.element_count = new_count
                model.storey_count = len(result.get("storeys") or [])
                model.import_date = datetime.now(UTC).isoformat()
                meta = dict(model.metadata_ or {})
                meta["reingested_at"] = datetime.now(UTC).isoformat()
                meta["reingest_source"] = "scripts.reingest_bim_model"
                # Drop any leftover degraded-state warnings — we just
                # imported real data, the model is no longer degraded.
                if model.status in ("degraded", "needs_converter"):
                    model.status = "ready"
                    model.error_message = None
                    for stale in (
                        "degraded",
                        "warning",
                        "error_code",
                        "suggested_actions",
                    ):
                        meta.pop(stale, None)
                model.metadata_ = meta

            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return summary


# ── CLI entrypoint ─────────────────────────────────────────────────────────


async def reingest_one(
    model_id_str: str,
    *,
    dry_run: bool,
    backup_rows: bool,
) -> int:
    try:
        model_id = uuid.UUID(model_id_str)
    except ValueError:
        print(f"ERROR: not a valid UUID: {model_id_str}", file=sys.stderr)
        return 1

    try:
        resolved = await _resolve_original_path(model_id)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if resolved is None:
        print(f"ERROR: model {model_id} not found in DB.", file=sys.stderr)
        return 1

    info, original_path = resolved
    logger.info(
        "Re-ingesting model %s (%s, format=%s) from %s",
        info["id"],
        info["name"],
        info["model_format"],
        original_path,
    )

    backup_path: Path | None = None
    if backup_rows:
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        # Repo data/ dir — same location used by other admin scripts.
        backup_path = Path(__file__).resolve().parents[3] / "data" / f"reingest_backup_{info['id']}_{ts}.json"

    with tempfile.TemporaryDirectory(prefix="oe-reingest-") as tmp_str:
        tmp_dir = Path(tmp_str)
        # process_ifc_file expects the CAD blob *named* original.{ext}
        # to live in the working dir alongside the would-be outputs, so
        # copy it in.  symlinks would be cheaper but Windows + non-admin
        # cannot create them reliably.
        ext = info["model_format"]
        local_input = tmp_dir / f"original.{ext}"
        local_input.write_bytes(original_path.read_bytes())

        result = await asyncio.to_thread(_run_ddc_extraction, local_input, tmp_dir)
        element_count = result.get("element_count", 0)
        logger.info(
            "DDC extraction produced %d elements (geometry_quality=%s)",
            element_count,
            result.get("geometry_quality"),
        )

        if element_count == 0:
            print(
                "ERROR: DDC extraction produced zero elements — aborting.",
                file=sys.stderr,
            )
            return 3

        try:
            summary = await _replace_elements(
                model_id,
                result,
                dry_run=dry_run,
                backup_path=backup_path,
            )
        except Exception:
            logger.exception("DB replacement failed")
            return 4

    # ── Final summary ────────────────────────────────────────────────────
    old = summary.get("old_count")
    old_null = summary.get("old_null_mesh_ref")
    new = summary.get("new_count")
    new_with_mesh = summary.get("new_with_mesh_ref")
    print()
    print("-" * 72)
    safe_name = (info.get("name") or "").encode("ascii", "replace").decode("ascii")
    print(f"  Model:    {info['id']}  ({safe_name})")
    print(f"  Format:   {info['model_format']}")
    print(f"  Status:   {summary['status']}")
    print(f"  OLD:      {old} rows (mesh_ref=NULL: {old_null})")
    print(f"  NEW:      {new} rows (mesh_ref populated: {new_with_mesh})")
    if backup_path and not dry_run:
        print(f"  Backup:   {backup_path}")
    print()
    print("  Sample of new rows:")
    for row in summary.get("sample", []):
        sample_name = (str(row.get("name") or "")).encode("ascii", "replace").decode("ascii")
        sample_family = (str(row.get("family") or "")).encode("ascii", "replace").decode("ascii")
        sample_type = (str(row.get("type_name") or "")).encode("ascii", "replace").decode("ascii")
        print(
            f"    - stable_id={row['stable_id']}  "
            f"mesh_ref={row['mesh_ref']}  "
            f"name={sample_name!r}  "
            f"family={sample_family!r}  "
            f"type_name={sample_type!r}"
        )
    print("-" * 72)
    if dry_run:
        print("(dry-run — no changes were committed)")
    print()
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.reingest_bim_model",
        description="Re-run DDC ingest against an existing BIM model.",
    )
    parser.add_argument("model_id", help="UUID of the oe_bim_model row to re-ingest.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction + print new-row stats without touching the DB.",
    )
    parser.add_argument(
        "--backup-rows",
        action="store_true",
        help=(
            "Before mutating the DB, dump the existing oe_bim_element rows "
            "for this model to data/reingest_backup_<model>_<timestamp>.json."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    _setup_logging(args.verbose)
    try:
        return asyncio.run(
            reingest_one(
                args.model_id,
                dry_run=args.dry_run,
                backup_rows=args.backup_rows,
            )
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover — direct CLI invocation
    raise SystemExit(main())
