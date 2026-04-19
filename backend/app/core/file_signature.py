"""Stdlib-only file-signature (magic-byte) sniffer.

Filename extensions are fully controlled by the uploader, so they provide
zero security guarantee. This module inspects the first few bytes of an
uploaded file and returns the detected format — or rejects mismatches
against the allowed set.

Covers the formats we actually accept across upload endpoints:
BIM / CAD (RVT, IFC, DWG, DXF, GLB, DGN), Documents (PDF, PNG, JPEG,
ZIP-based Office: XLSX / DOCX / PPTX), tabular (CSV, plain XML).

Design constraints:
- Pure stdlib — no python-magic / filetype / libmagic (libmagic on
  Windows is a pain; python-magic pulls native deps).
- Reads at most 16 bytes. Safe to call on arbitrarily large files.
- Returns a symbolic type token ("pdf", "zip", "ifc", …) rather than a
  MIME string so callers can match against a small enumerated set.
"""

from __future__ import annotations

from typing import Final

# Minimum bytes needed to identify every format we check. Callers can
# read this many upfront and pass the slice to ``detect``.
SIGNATURE_BYTES_REQUIRED: Final[int] = 16


def detect(head: bytes) -> str | None:
    """Return a symbolic type token for *head* (first bytes of a file).

    Returns ``None`` if the signature is not recognised. ``head`` shorter
    than :data:`SIGNATURE_BYTES_REQUIRED` is tolerated — the function
    simply returns ``None`` for signatures that would need more bytes.
    """
    if not head:
        return None

    # — PDF — "%PDF-" at offset 0 (allows for a few bytes of leading
    # whitespace / BOM which some scanners emit).
    stripped = head.lstrip(b"\x00\xef\xbb\xbf \t\r\n")
    if stripped.startswith(b"%PDF-"):
        return "pdf"

    # — PNG — 89 50 4E 47 0D 0A 1A 0A
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    # — JPEG — FF D8 FF
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"

    # — GIF —
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "gif"

    # — WebP — RIFF....WEBP
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"

    # — ZIP container (xlsx, docx, pptx, glb containers, some RVT
    # variants). Caller must inspect central directory for the exact
    # OOXML flavour if needed. We accept ``PK\x03\x04`` (local file
    # header) and the rarer ``PK\x05\x06`` / ``PK\x07\x08`` empty
    # / spanned signatures.
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"

    # — OLE compound document (legacy Office, RVT, many CAD files).
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole"

    # — IFC step file — starts with "ISO-10303-21" (may have BOM).
    if stripped.startswith(b"ISO-10303-21"):
        return "ifc"

    # — DWG AutoCAD — "AC" followed by 4-digit version.
    if head[:2] == b"AC" and head[2:6].isdigit():
        return "dwg"

    # — DXF ASCII — optional leading whitespace then "0\nSECTION" or
    # "999\n" comment. Vector AutoCAD-exchange text format.
    stripped_dxf = head.lstrip(b" \t\r\n\xef\xbb\xbf")
    if stripped_dxf[:2] == b"0\n" or stripped_dxf[:4] == b"999\n":
        return "dxf"

    # — GLB binary glTF — magic 0x46546C67 ("glTF").
    if head[:4] == b"glTF":
        return "glb"

    # — plain XML (GAEB files, IDS, BCF manifest, etc.).
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<") and b">" in stripped[:256]:
        return "xml"

    return None


# Common upload-endpoint allow-lists. Keep them at the module level so
# they're easy to review — each endpoint imports the constant it needs
# rather than sprinkling magic literals through handlers.
ALLOWED_DOCUMENT_TYPES: Final[frozenset[str]] = frozenset(
    {"pdf", "png", "jpeg", "gif", "webp", "zip", "ole", "xml"}
)
ALLOWED_BIM_TYPES: Final[frozenset[str]] = frozenset(
    {"ole", "zip", "ifc", "glb", "xml"}
)
ALLOWED_DWG_TYPES: Final[frozenset[str]] = frozenset(
    {"dwg", "dxf", "ole"}
)
ALLOWED_CAD_TYPES: Final[frozenset[str]] = (
    ALLOWED_BIM_TYPES | ALLOWED_DWG_TYPES
)
ALLOWED_GAEB_TYPES: Final[frozenset[str]] = frozenset({"xml"})


class FileSignatureMismatch(ValueError):
    """Raised when an upload's magic bytes don't match the allowed set."""


def require(head: bytes, allowed: frozenset[str], *, filename: str | None = None) -> str:
    """Detect *head* and raise :class:`FileSignatureMismatch` if not allowed.

    Returns the detected type token on success. ``filename`` (if given)
    is included in the error message for operator-friendly diagnostics.
    """
    detected = detect(head)
    if detected is None or detected not in allowed:
        label = f" ({filename})" if filename else ""
        raise FileSignatureMismatch(
            f"Uploaded file content does not match any allowed format{label}. "
            f"Detected signature: {detected or 'unknown'}. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )
    return detected
