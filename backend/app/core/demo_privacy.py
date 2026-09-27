# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Identity redaction for the public hosted demo (``OE_DEMO_MODE``).

On the hosted demo anybody can sign in, and real people register there to
try the product. Every endpoint that shows one user another user's identity
runs it through these helpers so a visitor sees an opaque stand-in instead of
a registrant's email and name. The caller's own record is never redacted.
Self-hosted installs leave ``OE_DEMO_MODE`` unset and nothing changes.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any


def demo_mode_enabled() -> bool:
    """True on the public hosted demo (env ``OE_DEMO_MODE``)."""
    return os.environ.get("OE_DEMO_MODE", "").lower() in ("1", "true", "yes")


def anonymize_email(email: str | None) -> str:
    """Replace the local part with a short stable hash, keeping the domain.

    ``alice@acme.com`` becomes ``user-1a2b3c@acme.com``: the same person
    always maps to the same stand-in, so lists stay readable, and only the
    domain stays visible.
    """
    value = (email or "").strip()
    if "@" not in value:
        return value
    local, domain = value.split("@", 1)
    short = hashlib.sha1(local.encode("utf-8"), usedforsecurity=False).hexdigest()[:6]
    return f"user-{short}@{domain}"


def _same_user(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    try:
        return uuid.UUID(str(a)) == uuid.UUID(str(b))
    except (TypeError, ValueError):
        return False


def should_redact(subject_id: Any, viewer_id: Any = None) -> bool:
    """True when demo mode is on and ``subject_id`` is not the viewer."""
    return demo_mode_enabled() and not _same_user(subject_id, viewer_id)


def redact_identity(
    data: dict[str, Any],
    *,
    subject_id: Any,
    viewer_id: Any = None,
    email_key: str = "email",
    name_keys: tuple[str, ...] = ("full_name",),
) -> dict[str, Any]:
    """Blank the name fields and hash the email of ``data`` in demo mode.

    Mutates and returns ``data``. A no-op outside demo mode or when the
    subject is the viewer.
    """
    if not should_redact(subject_id, viewer_id):
        return data
    if email_key in data and data[email_key]:
        data[email_key] = anonymize_email(data[email_key])
    for key in name_keys:
        if key in data and data[key]:
            data[key] = ""
    return data


def redact_model(model: Any, *, subject_id: Any, viewer_id: Any = None, **kwargs: Any) -> Any:
    """Pydantic variant of :func:`redact_identity`, returning a new instance."""
    if not should_redact(subject_id, viewer_id):
        return model
    data = redact_identity(model.model_dump(), subject_id=subject_id, viewer_id=viewer_id, **kwargs)
    return type(model).model_validate(data)
