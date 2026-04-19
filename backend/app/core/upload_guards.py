"""Shared upload safety guards.

Centralises the size/format checks that live on every multipart upload
endpoint so the policy (and the error surface) stays identical across
modules.

Current guards:

* :func:`reject_if_xlsx_bomb` — rejects ``.xlsx`` whose uncompressed XML
  payload exceeds the cap (``openpyxl`` materialises the full decompressed
  sheet, so a 10 MB compressed file can expand to 10+ GB).
"""

from __future__ import annotations

import io
import zipfile

from fastapi import HTTPException, status

# 50 MB decompressed is well above any realistic CWICR / GAEB / procurement
# spreadsheet and still small enough to keep a worker from OOM-ing. Tune
# per endpoint via the ``max_uncompressed`` kwarg if needed.
DEFAULT_MAX_UNCOMPRESSED_XLSX = 50 * 1024 * 1024


def reject_if_xlsx_bomb(
    content: bytes,
    *,
    max_uncompressed: int = DEFAULT_MAX_UNCOMPRESSED_XLSX,
) -> None:
    """Raise 413 when the sum of uncompressed entries exceeds the cap.

    Silent no-op for non-zip payloads (plain CSV, corrupt bytes) — the
    downstream parser produces the appropriate error in those cases.
    """
    if not content.startswith(b"PK"):
        return

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            total = sum(max(info.file_size, 0) for info in zf.infolist())
    except zipfile.BadZipFile:
        return

    if total > max_uncompressed:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Uncompressed spreadsheet size ({total // (1024 * 1024)} MB) "
                f"exceeds the {max_uncompressed // (1024 * 1024)} MB limit."
            ),
        )
