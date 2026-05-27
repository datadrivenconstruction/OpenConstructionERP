"""‌⁠‍Stdlib-only file-signature (magic-byte) sniffer.

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
    """‌⁠‍Return a symbolic type token for *head* (first bytes of a file).

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

    # ISO-BMFF (HEIC/HEIF) — bytes 4..8 == "ftyp", brand at 8..12. Brand
    # whitelist split: HEIC brands → "heic", HEIF/AVIF-style brands → "heif".
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"hevx", b"heis", b"hevm"):
            return "heic"
        if brand in (b"mif1", b"msf1", b"avif", b"avis"):
            return "heif"

    # — TIFF — both endiannesses are valid magic; matters because cameras
    # in the wild emit either depending on architecture.
    if head[:4] == b"II*\x00" or head[:4] == b"MM\x00*":
        return "tiff"

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
ALLOWED_DOCUMENT_TYPES: Final[frozenset[str]] = frozenset({"pdf", "png", "jpeg", "gif", "webp", "zip", "ole", "xml"})
ALLOWED_BIM_TYPES: Final[frozenset[str]] = frozenset({"ole", "zip", "ifc", "glb", "xml"})
ALLOWED_DWG_TYPES: Final[frozenset[str]] = frozenset({"dwg", "dxf", "ole"})
ALLOWED_CAD_TYPES: Final[frozenset[str]] = ALLOWED_BIM_TYPES | ALLOWED_DWG_TYPES
ALLOWED_GAEB_TYPES: Final[frozenset[str]] = frozenset({"xml"})
ALLOWED_PHOTO_TYPES: Final[frozenset[str]] = frozenset({"jpeg", "png", "gif", "webp", "heic", "heif", "tiff"})

# Signature tokens that must NEVER be stored even if the surrounding
# allow-list would tolerate them. ``detect`` does not currently surface
# PE/ELF/Mach-O/script types as named tokens — unknown blobs return
# ``None`` so that plain text (CSV/JSON/TXT) still uploads — but listing
# the names here keeps the policy contract explicit and lets us tighten
# the detector later (e.g. add an ``exe`` token) without touching the
# upload sites.
BANNED_SIGNATURE_TOKENS: Final[frozenset[str]] = frozenset({"exe", "elf", "mach-o", "shellscript", "batch", "msi"})

# Mapping from detector tokens to canonical IANA MIME types. Used by
# upload paths that want to store an attacker-resistant MIME on the
# Document/Photo row: the request ``Content-Type`` header is fully
# controlled by the client, so we derive the stored value from the
# magic bytes we actually inspected.
_SIGNATURE_TO_MIME: Final[dict[str, str]] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "heic": "image/heic",
    "heif": "image/heif",
    "tiff": "image/tiff",
    "zip": "application/zip",
    "ole": "application/x-ole-storage",
    "ifc": "application/x-step",
    "dwg": "image/vnd.dwg",
    "dxf": "image/vnd.dxf",
    "glb": "model/gltf-binary",
    "xml": "application/xml",
}


def mime_for_signature(detected: str | None) -> str:
    """Return the canonical MIME for a detector token.

    ``None`` and unknown tokens map to ``application/octet-stream``
    so the stored ``mime_type`` is never attacker-controlled.
    """
    if detected is None:
        return "application/octet-stream"
    return _SIGNATURE_TO_MIME.get(detected, "application/octet-stream")


class FileSignatureMismatch(ValueError):
    """‌⁠‍Raised when an upload's magic bytes don't match the allowed set."""


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


if __name__ == "__main__":
    cases = [
        (b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00", "heic"),
        (b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00", "heif"),
        (b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00", "heif"),
        (b"II*\x00\x08\x00\x00\x00", "tiff"),
        (b"MM\x00*\x00\x00\x00\x08", "tiff"),
        (b"%PDF-1.7\n", "pdf"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xff\xd8\xff\xe0", "jpeg"),
        (b"random nonsense", None),
        (b"<?xml version='1.0'?><svg/>", "xml"),
    ]
    failures = 0
    for head, expected in cases:
        got = detect(head)
        if got != expected:
            failures += 1
            print(f"FAIL: head={head!r} expected={expected!r} got={got!r}")
        else:
            print(f"ok:   head[:12]={head[:12]!r} -> {got!r}")
    if failures:
        raise SystemExit(f"{failures} failures")
    print("all signature self-tests pass")
