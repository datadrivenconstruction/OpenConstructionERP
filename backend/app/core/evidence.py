# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tamper-evident export headers for register / report downloads.

Why this exists
===============
Across the platform a user can export a register "for the record" - a report,
a correspondence log, a signed-document manifest, an approval timeline. When
such a file is later attached to a claim, a submission or a dispute, two
questions always come up: *when* was it produced, and *is this the exact data
that was in the system at that moment*. A bare "Generated: <date>" line answers
the first but not the second - the file could have been edited after download.

This module gives every exporter one small, jurisdiction-neutral helper that
stamps a header with the generation time **and** a SHA-256 digest of the
content itself. Re-exporting the same underlying data yields the same digest,
so a recipient can recompute it and confirm the file was not altered. It makes
no legal claim - it is a tamper-evident audit trail, not a "court-grade"
signature (that is what the signing workflow is for).

Design
======
- **Pure and deterministic.** No DB, no network, no clock. The caller passes
  the already-resolved ``generated_at`` string; the digest is computed over a
  canonical JSON serialisation of the content payload with sorted keys, so the
  same data always hashes to the same value regardless of dict ordering,
  platform or export format.
- **Timestamp is excluded from the digest.** The digest identifies the
  *dataset*, not the moment of export, so two exports of unchanged data match.
- **Format-agnostic.** Returns plain ``(label, value)`` pairs; each exporter
  (CSV / XLSX / PDF, or any future register export) renders them in its own
  header style. Labels resolve through the shared ``translate()`` so the header
  can be localised without touching call sites.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = [
    "DIGEST_ALGORITHM",
    "content_digest",
    "evidence_header",
    "short_digest",
]

# The one algorithm every export header uses. Named in the header value so a
# recipient knows exactly how to recompute it.
DIGEST_ALGORITHM = "SHA-256"

# How many hex characters of the digest to show in a human-facing header. The
# full 64-char digest is available via ``content_digest`` for machine checks;
# the header shows a readable prefix that is still collision-safe in practice.
_SHORT_DIGEST_LEN = 16


def content_digest(payload: Any) -> str:
    """Return the full lowercase hex SHA-256 of *payload*.

    The payload is canonicalised to JSON with sorted keys and no insignificant
    whitespace before hashing, so logically-equal data hashes identically no
    matter how the dict was built. Non-JSON scalars (``Decimal``, ``datetime``,
    ``UUID``) are coerced via ``str`` so money and ids hash by their exact
    textual value rather than raising.

    Args:
        payload: Any JSON-serialisable structure - typically the export's
            content dict (title, project, currency, section snapshot).

    Returns:
        64-character lowercase hex digest.
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def short_digest(digest: str, length: int = _SHORT_DIGEST_LEN) -> str:
    """Return the leading *length* hex chars of a full digest for display."""
    return (digest or "")[:length]


def evidence_header(
    *,
    generated_at: str,
    payload: Any,
    locale: str = "en",
) -> list[tuple[str, str]]:
    """Build the ``(label, value)`` header rows for a tamper-evident export.

    Args:
        generated_at: Already-resolved generation timestamp (ISO string). It is
            shown to the reader but deliberately NOT folded into the digest.
        payload: The content to fingerprint (excludes the timestamp).
        locale: UI locale for the row labels; falls back to English.

    Returns:
        Ordered list of ``(label, value)`` pairs: the generation time and the
        content digest line (``"<16-hex>… (SHA-256)"``), ready for any format's
        header block.
    """
    from app.core.validation.messages import translate

    digest = content_digest(payload)
    generated_label = translate("export.generated", locale=locale)
    digest_label = translate("export.content_digest", locale=locale)
    digest_value = f"{short_digest(digest)}… ({DIGEST_ALGORITHM})"
    return [
        (generated_label, generated_at),
        (digest_label, digest_value),
    ]
