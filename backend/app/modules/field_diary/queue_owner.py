"""Owner check for replayed offline captures."""

from __future__ import annotations

from fastapi import HTTPException, status


def check_queue_owner(session_user_id: object, claimed: str | None) -> None:
    """Reject a replayed capture whose device-side owner is not the token's user.

    The header is optional so older clients keep working; when present it must
    name the user the field session was issued to.
    """
    if claimed is None or not claimed.strip():
        return
    if claimed.strip().lower() != str(session_user_id).lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "queue_owner_mismatch",
                "message": "This capture was queued by a different user than the one signed in.",
            },
        )
