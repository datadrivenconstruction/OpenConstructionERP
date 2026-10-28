"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for ``FieldReportCreate.signature_data`` validation.

``signature_data`` is a base64 data URI of a hand-drawn signature image.
Pre-fix it was an unbounded ``str | None`` — any authenticated caller
could dump megabytes of arbitrary data (or inline script payloads) into
the field-report row, and that text was later embedded verbatim in the
PDF export. The schema now:

* rejects payloads larger than 2 MB;
* rejects anything that doesn't start with ``data:image/`` (so plain
  text / scripts / arbitrary binaries can't sit in the column);
* rejects MIME subtypes outside the signature-pad allow-list (PNG /
  JPEG / WebP / SVG+xml).

Tests exercise the validator in isolation — no DB / network / session
needed.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.modules.fieldreports.schemas import FieldReportCreate, FieldReportUpdate


def _base_create_payload(**overrides):
    payload = {
        "project_id": uuid.uuid4(),
        "report_date": date(2026, 5, 22),
    }
    payload.update(overrides)
    return payload


# ── Happy paths ──────────────────────────────────────────────────────────


def test_signature_data_accepts_png_data_uri():
    create = FieldReportCreate(
        **_base_create_payload(
            signature_data="data:image/png;base64,iVBORw0KGgo=",
        )
    )
    assert create.signature_data is not None
    assert create.signature_data.startswith("data:image/png")


def test_signature_data_accepts_jpeg_data_uri():
    create = FieldReportCreate(
        **_base_create_payload(
            signature_data="data:image/jpeg;base64,/9j/4AAQ=",
        )
    )
    assert create.signature_data is not None


def test_signature_data_accepts_webp_data_uri():
    create = FieldReportCreate(
        **_base_create_payload(
            signature_data="data:image/webp;base64,UklGRiQAAABXRUJQ=",
        )
    )
    assert create.signature_data is not None


def test_signature_data_none_is_allowed():
    create = FieldReportCreate(**_base_create_payload(signature_data=None))
    assert create.signature_data is None


def test_signature_data_empty_string_is_allowed():
    create = FieldReportCreate(**_base_create_payload(signature_data=""))
    assert create.signature_data == ""


# ── Rejection paths ──────────────────────────────────────────────────────


def test_signature_data_rejects_plain_text():
    """A long free-text blob must not be storable as a signature."""
    with pytest.raises(ValidationError) as exc_info:
        FieldReportCreate(
            **_base_create_payload(
                signature_data="This is just plain text, not an image.",
            )
        )
    msg = str(exc_info.value)
    assert "signature_data" in msg
    assert "data URI" in msg or "data:image" in msg


def test_signature_data_rejects_script_payload():
    with pytest.raises(ValidationError):
        FieldReportCreate(
            **_base_create_payload(
                signature_data="<script>alert(1)</script>",
            )
        )


def test_signature_data_rejects_non_image_data_uri():
    """``data:text/html`` is a valid data URI but not a signature image."""
    with pytest.raises(ValidationError) as exc_info:
        FieldReportCreate(
            **_base_create_payload(
                signature_data="data:text/html;base64,PHA+aGk8L3A+",
            )
        )
    assert "data URI" in str(exc_info.value) or "data:image" in str(exc_info.value)


def test_signature_data_rejects_unsupported_image_mime():
    with pytest.raises(ValidationError) as exc_info:
        FieldReportCreate(
            **_base_create_payload(
                signature_data="data:image/x-icon;base64,AAAB",
            )
        )
    assert "MIME" in str(exc_info.value) or "not allowed" in str(exc_info.value)


def test_signature_data_rejects_oversize_payload():
    """A 3 MB blob must be rejected (cap is 2 MB)."""
    big = "data:image/png;base64," + ("A" * (3 * 1024 * 1024))
    with pytest.raises(ValidationError) as exc_info:
        FieldReportCreate(**_base_create_payload(signature_data=big))
    msg = str(exc_info.value)
    assert "exceed" in msg or "maximum" in msg


def test_update_signature_data_validates_same_way():
    """``FieldReportUpdate`` must apply the same allow-list as create."""
    with pytest.raises(ValidationError):
        FieldReportUpdate(signature_data="plain text")
    # Valid PNG passes
    valid = FieldReportUpdate(signature_data="data:image/png;base64,iVBORw0=")
    assert valid.signature_data is not None
