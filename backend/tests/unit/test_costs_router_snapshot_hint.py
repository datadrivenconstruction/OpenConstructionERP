"""Tests for the snapshot-restore error → user-hint mapper.

The hint mapper exists because Qdrant's verbatim recover-from-URL error
is good for debugging but unactionable for end users — especially on
Windows where ``os error 5`` on ``newest_clocks.json`` looks like a
"network problem" but is actually Defender locking the WAL clock file
during fsync. The router surfaces both: Qdrant's raw message *and* a
concrete next step.

These tests pin the mapping so the next person who tweaks the helper
keeps the Windows AV / disk full / 404 / timeout branches working —
those are the four buckets nearly every recover-from-URL failure falls
into in the field.
"""

from app.modules.costs.router import _snapshot_error_hint


def test_hint_windows_access_denied_returns_defender_exclusion_advice() -> None:
    err = (
        "Service internal error: failed to sync file "
        "`C:\\Users\\X\\.openestimator\\qdrant\\storage\\tmp\\"
        "col-cwicr_en_v3-recovery-tq6L8g\\0\\newest_clocks.json`: "
        "Access is denied. (os error 5)"
    )
    hint = _snapshot_error_hint(err)
    assert hint is not None
    assert "Defender" in hint
    assert ".openestimator" in hint


def test_hint_disk_full_returns_free_space_advice() -> None:
    hint = _snapshot_error_hint("io error: No space left on device")
    assert hint is not None
    assert "free up" in hint.lower() or "disk" in hint.lower()


def test_hint_404_returns_publish_advice() -> None:
    hint = _snapshot_error_hint("Failed to download snapshot from https://hf.co/x: status - 404 Not Found")
    assert hint is not None
    assert "huggingface.co" in hint.lower() or "publish" in hint.lower()


def test_hint_timeout_returns_network_advice() -> None:
    hint = _snapshot_error_hint("connection refused while reading body")
    assert hint is not None
    assert "huggingface" in hint.lower() or "outbound" in hint.lower()


def test_hint_unknown_error_returns_none() -> None:
    assert _snapshot_error_hint("") is None
    assert _snapshot_error_hint("some unrelated Qdrant noise") is None
