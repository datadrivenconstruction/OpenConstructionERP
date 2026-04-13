"""Migrate existing BIM blobs from the local filesystem to S3.

Walks ``data/bim/{project_id}/{model_id}/*`` and uploads every file to
the configured S3 bucket using :mod:`app.core.storage`.  Preserves the
``bim/{project_id}/{model_id}/{filename}`` key layout so
:mod:`app.modules.bim_hub.file_storage` finds everything afterwards.

Usage::

    # 1. Configure S3 credentials in your .env (or as env vars)
    #    STORAGE_BACKEND=s3
    #    S3_ENDPOINT=http://localhost:9000      (or AWS/B2/DO endpoint)
    #    S3_ACCESS_KEY=...
    #    S3_SECRET_KEY=...
    #    S3_BUCKET=openestimate
    #    S3_REGION=us-east-1
    #
    # 2. Install the optional dependency
    #    pip install 'openconstructionerp[s3]'
    #
    # 3. Run the migration (from the backend/ directory)
    #    python scripts/migrate_bim_to_s3.py

Idempotent: re-uploads the same bytes if you run it twice.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure ``backend/`` is importable when running the script directly.
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.core.storage import S3StorageBackend, build_storage_backend  # noqa: E402


def _bim_root() -> Path:
    """Local root for BIM blobs: ``<repo>/data/bim``."""
    return _BACKEND_DIR.parent / "data" / "bim"


async def _migrate() -> None:
    settings = get_settings()
    if settings.storage_backend != "s3":
        print(
            "ERROR: settings.storage_backend is "
            f"{settings.storage_backend!r}, expected 's3'."
        )
        print("Set STORAGE_BACKEND=s3 in your environment first.")
        sys.exit(2)

    backend = build_storage_backend(settings)
    if not isinstance(backend, S3StorageBackend):
        print(f"ERROR: expected S3StorageBackend, got {type(backend).__name__}")
        sys.exit(2)

    root = _bim_root()
    if not root.is_dir():
        print(f"Nothing to do — {root} does not exist.")
        return

    uploaded = 0
    skipped = 0
    total_bytes = 0

    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        project_id = project_dir.name
        for model_dir in sorted(project_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            model_id = model_dir.name
            for blob_path in sorted(model_dir.rglob("*")):
                if not blob_path.is_file():
                    continue
                rel = blob_path.relative_to(model_dir).as_posix()
                key = f"bim/{project_id}/{model_id}/{rel}"
                size = blob_path.stat().st_size
                try:
                    content = blob_path.read_bytes()
                except OSError as exc:
                    print(f"  skip  {key}  (read error: {exc})")
                    skipped += 1
                    continue
                await backend.put(key, content)
                uploaded += 1
                total_bytes += size
                print(f"  push  {key}  ({size:,} bytes)")

    print()
    print(
        f"Done: uploaded={uploaded} skipped={skipped} "
        f"bytes={total_bytes:,}"
    )


def main() -> None:
    asyncio.run(_migrate())


if __name__ == "__main__":
    main()
