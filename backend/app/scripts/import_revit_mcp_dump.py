# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Turn a ``revit-mcp`` dump into a BIM Hub bulk-import payload.

``revit-mcp`` / ``mcp-server-for-revit`` are stdio MCP servers that only
work on the workstation running Revit, so the backend cannot call them.
This script closes that gap offline:

1. On the Revit workstation, run the MCP read tools and save the raw JSON
   responses keyed by tool name::

       {
         "get_current_view_info":     { ... },
         "get_current_view_elements": { ... },
         "get_material_quantities":   { ... },
         "analyze_model_statistics":  { ... }
       }

2. Convert it here::

       python -m app.scripts.import_revit_mcp_dump revit_dump.json \\
           --out payload.json --units imperial

3. POST the payload to the model you created for it::

       POST /api/v1/bim/models/{model_id}/elements/   (body = payload.json)

The script is read-only: it touches no database and performs no network
call, so it is safe to run against a production dump. Exit code is 1 when
the dump yields no elements at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.modules.bim_hub.revit_mcp_dump import (
    UNITS_IMPERIAL,
    UNITS_RAW,
    ConversionResult,
    convert_dump,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="import_revit_mcp_dump",
        description="Convert a revit-mcp tool dump into a BIM Hub bulk-import payload.",
    )
    parser.add_argument(
        "dump",
        type=Path,
        help="Path to the dump JSON (keys are MCP tool names).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the bulk-import payload here. Defaults to stdout-only summary.",
    )
    parser.add_argument(
        "--model-out",
        type=Path,
        default=None,
        help="Write the suggested BIMModel field values here.",
    )
    parser.add_argument(
        "--units",
        choices=(UNITS_RAW, UNITS_IMPERIAL),
        default=UNITS_RAW,
        help=(
            "How to read area/volume numbers. 'raw' (default) keeps them verbatim "
            "as area_raw/volume_raw; 'imperial' reads the Revit internal ft2/ft3 "
            "and emits area_m2/volume_m3."
        ),
    )
    parser.add_argument(
        "--include-annotation",
        action="store_true",
        help=(
            "Keep drafting/view categories (tags, title blocks, sheets, dimensions). "
            "Off by default - BIMElement doubles as the asset register."
        ),
    )
    return parser.parse_args(argv)


def _report(result: ConversionResult, units: str) -> None:
    """Print a human summary of the conversion to stdout."""
    model = result.model
    print(f"project      : {model.get('name')}")
    print(f"format       : {model.get('model_format')}  discipline: {model.get('discipline')}")
    print(f"storeys      : {model.get('storey_count')}")
    print(f"units        : {model.get('metadata', {}).get('units')}  (--units {units})")
    print(f"element rows : {len(result.elements)}")
    for tier, count in sorted(result.tier_counts.items()):
        print(f"  {tier:9s}: {count}")

    totals = model.get("metadata", {}).get("revit_totals") or {}
    if totals:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(totals.items()))
        print(f"revit totals : {rendered}")
        print(
            "  note: totalElements counts every Revit element including "
            "annotation and system rows; it will not equal the row count above.",
        )

    if result.warnings:
        print(f"\nwarnings ({len(result.warnings)}):")
        for warning in result.warnings:
            print(f"  - {warning}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.dump.is_file():
        print(f"error: dump not found: {args.dump}", file=sys.stderr)
        return 2
    try:
        dump = json.loads(args.dump.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {args.dump}: {exc}", file=sys.stderr)
        return 2

    try:
        result = convert_dump(
            dump,
            units=args.units,
            include_annotation=args.include_annotation,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    _report(result, args.units)

    if args.out:
        _write_json(args.out, {"elements": result.elements})
    if args.model_out:
        _write_json(args.model_out, result.model)

    if not result.elements:
        print("\nerror: no elements produced - nothing to import.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
