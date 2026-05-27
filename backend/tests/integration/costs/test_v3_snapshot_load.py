# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration test — DDC v3 snapshot upload against a live Qdrant server.

Skipped automatically unless ``CWICR_QDRANT_URL`` is set, so the suite
stays green in CI environments without a Qdrant container. To run::

    docker compose up -d qdrant
    export CWICR_QDRANT_URL=http://localhost:6333
    pytest tests/integration/costs/test_v3_snapshot_load.py -v

The test creates a tiny throw-away collection via the REST API, takes
a snapshot of it, then uses :func:`restore_snapshot_file` to restore
that same snapshot back under a different collection name. This
exercises the full upload code path (multipart POST, response parsing,
error handling) without depending on the multi-hundred-MB DDC files.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest

QDRANT_URL = os.environ.get("CWICR_QDRANT_URL")
QDRANT_API_KEY = os.environ.get("CWICR_QDRANT_API_KEY")

pytestmark = pytest.mark.skipif(
    not QDRANT_URL,
    reason="CWICR_QDRANT_URL not set — skipping live-Qdrant integration test",
)


def _request(
    method: str,
    path: str,
    *,
    json=None,
    timeout: float = 30.0,
):
    """Tiny REST helper so the test doesn't drag in qdrant-client.

    Direct httpx usage keeps the test honest — same surface the loader
    itself uses, so any auth/header drift surfaces here too.
    """
    import httpx

    headers = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
    return httpx.request(
        method,
        QDRANT_URL.rstrip("/") + path,
        json=json,
        headers=headers,
        timeout=timeout,
    )


def _wait_for_collection(name: str, *, timeout_s: float = 30.0) -> None:
    """Poll until the collection exists or timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = _request("GET", f"/collections/{name}")
        if resp.status_code == 200:
            return
        time.sleep(0.5)
    raise AssertionError(f"collection {name} did not appear within {timeout_s}s")


@pytest.fixture
def throwaway_collection():
    """Create + delete a tiny vector collection for the snapshot round-trip."""
    name = f"oe_test_{uuid.uuid4().hex[:8]}"
    create = _request(
        "PUT",
        f"/collections/{name}",
        json={"vectors": {"size": 4, "distance": "Cosine"}},
    )
    assert create.is_success, f"create failed: {create.status_code} {create.text}"
    try:
        yield name
    finally:
        _request("DELETE", f"/collections/{name}")


def test_restore_snapshot_round_trip(throwaway_collection: str, tmp_path: Path) -> None:
    """End-to-end: snapshot a collection, then restore it under a new name.

    Steps:

    1. Upsert one point into the throwaway collection so the snapshot has
       content.
    2. Trigger a server-side snapshot via POST /collections/{name}/snapshots.
    3. Download the snapshot file to the test tmp dir.
    4. Use :func:`restore_snapshot_file` to upload it under a NEW
       collection name (``..._restored``).
    5. Confirm the new collection appears via :func:`server_collections`.

    This is the exact flow operators will run with DDC's pre-built
    snapshots — only the source of the .snapshot file differs.
    """
    from app.modules.costs.qdrant_snapshot_loader import (
        restore_snapshot_file,
        server_collections,
    )

    src = throwaway_collection
    restored = src + "_restored"

    # 1. Insert one point so the snapshot isn't empty.
    upsert = _request(
        "PUT",
        f"/collections/{src}/points?wait=true",
        json={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]},
    )
    assert upsert.is_success, upsert.text

    # 2. Take a server-side snapshot.
    snap_resp = _request("POST", f"/collections/{src}/snapshots")
    assert snap_resp.is_success, snap_resp.text
    snap_name = snap_resp.json()["result"]["name"]

    # 3. Download it to tmp.
    import httpx

    headers = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
    download_url = QDRANT_URL.rstrip("/") + f"/collections/{src}/snapshots/{snap_name}"
    local_path = tmp_path / "round_trip.snapshot"
    with httpx.stream("GET", download_url, headers=headers, timeout=60.0) as r:
        r.raise_for_status()
        with local_path.open("wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
    assert local_path.stat().st_size > 0

    # 4. Restore under a new collection name via the loader.
    ok = restore_snapshot_file(
        qdrant_url=QDRANT_URL,
        collection_name=restored,
        snapshot_path=local_path,
        api_key=QDRANT_API_KEY,
    )
    assert ok, "restore_snapshot_file returned False"

    try:
        # 5. Verify the new collection exists.
        _wait_for_collection(restored)
        names = server_collections(qdrant_url=QDRANT_URL, api_key=QDRANT_API_KEY)
        assert restored in names
    finally:
        _request("DELETE", f"/collections/{restored}")
