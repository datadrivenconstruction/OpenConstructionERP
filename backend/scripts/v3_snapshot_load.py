"""‌⁠‍v3 snapshot loader — restore DDC CWICR v3 snapshots into a Qdrant server.

Usage::

    python scripts/v3_snapshot_load.py <snapshots_dir> [--dry-run]
                                       [--url URL] [--api-key KEY]

``<snapshots_dir>`` can point at:

* A clone of ``OpenConstructionEstimate-DDC-CWICR`` — every
  ``*_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot``
  found recursively will be restored into ``cwicr_<lang>_v3``.
* A single language directory (``RU___DDC_CWICR/``).
* Any directory containing one or more DDC v3 snapshot files.

``--url`` overrides the configured ``CWICR_QDRANT_URL`` setting. Without
it the loader reads from ``app.config`` so the same env var that the
runtime adapter uses also drives the loader.

``--dry-run`` walks the directory and prints what would be restored,
without contacting any Qdrant server. Useful for previewing a multi-GB
repo before committing to a real restore.

The script is intentionally **not** a Click/Typer command so it can run
from a fresh checkout with only ``backend`` requirements installed —
no extra CLI framework needed. The argument surface is small (3 flags)
and stable.

Pre-flight check: queries ``/collections`` before and after so the
operator sees which ``cwicr_*_v3`` collections appeared. Embedded
``QdrantClient(path=...)`` is rejected at the loader layer with a
helpful error — see ``qdrant_adapter`` module docstring for the
"server-mode required" rationale.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow ``python scripts/v3_snapshot_load.py …`` from the ``backend/``
# root: Python only adds the script's own dir to sys.path when invoked
# directly, so we have to bring in the parent (``backend/``) ourselves
# for the ``app.*`` imports to resolve.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.modules.costs.qdrant_snapshot_loader import (  # noqa: E402
    load_ddc_snapshot_dir,
    server_collections,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="v3_snapshot_load",
        description="Restore DDC CWICR v3 BGE-M3 snapshots into a Qdrant server.",
    )
    p.add_argument(
        "snapshots_dir",
        type=Path,
        help="Path to a DDC repo clone, language sub-dir, or any dir of .snapshot files",
    )
    p.add_argument(
        "--url",
        default=None,
        help="Qdrant server URL (overrides CWICR_QDRANT_URL setting)",
    )
    p.add_argument(
        "--api-key",
        default=None,
        help="Optional Qdrant Cloud API key (sent as `api-key` header)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk the directory and resolve targets without contacting a server",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="DEBUG-level logging from the loader",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.snapshots_dir.is_dir():
        print(f"FAIL: {args.snapshots_dir} is not a directory", file=sys.stderr)
        return 2

    url = args.url
    if url is None:
        try:
            from app.config import get_settings

            url = getattr(get_settings(), "cwicr_qdrant_url", None)
        except Exception as exc:  # pragma: no cover — defensive
            print(f"WARN: could not read settings: {exc}", file=sys.stderr)
            url = None

    if not args.dry_run and not url:
        print(
            "FAIL: no Qdrant URL — set CWICR_QDRANT_URL or pass --url. "
            "Use --dry-run to preview targets without a server.",
            file=sys.stderr,
        )
        return 3

    if url and not args.dry_run:
        print(f"Pre-flight: collections currently on {url}")
        for name in server_collections(qdrant_url=url, api_key=args.api_key):
            print(f"  - {name}")

    summary = load_ddc_snapshot_dir(
        args.snapshots_dir,
        qdrant_url=url,
        api_key=args.api_key,
        dry_run=args.dry_run,
    )

    print()
    print(f"Loaded ({len(summary.loaded)}):")
    for line in summary.loaded:
        print(f"  + {line}")
    print(f"Skipped ({len(summary.skipped)}):")
    for line in summary.skipped:
        print(f"  - {line}")
    if summary.errors:
        print(f"Errors ({len(summary.errors)}):")
        for line in summary.errors:
            print(f"  ! {line}")

    if url and not args.dry_run:
        print()
        print(f"Post: collections now on {url}")
        for name in server_collections(qdrant_url=url, api_key=args.api_key):
            print(f"  - {name}")

    if summary.errors:
        return 1
    if not summary.loaded and not args.dry_run:
        # Walked the directory but nothing valid landed — likely the
        # operator pointed at a sub-tree without v3 snapshots.
        print(
            "WARN: zero snapshots restored. Check that the directory contains *_BGEM3_V3_DDC_CWICR.snapshot files.",
            file=sys.stderr,
        )
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
