"""Replayed field captures must be queued by the user the session belongs to."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.field_diary.queue_owner import check_queue_owner


def test_matching_owner_passes() -> None:
    uid = uuid.uuid4()
    check_queue_owner(uid, str(uid).upper())


def test_missing_header_passes_for_older_clients() -> None:
    check_queue_owner(uuid.uuid4(), None)
    check_queue_owner(uuid.uuid4(), "  ")


def test_other_user_is_refused_with_code() -> None:
    with pytest.raises(HTTPException) as exc:
        check_queue_owner(uuid.uuid4(), str(uuid.uuid4()))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "queue_owner_mismatch"
