# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Profile photo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ validation and normalisation.

The upload is checked on the server, never trusted from the client: an allowed
image type (PNG, JPEG or WebP), a 2 MB cap, bytes that really decode as that
type, and a pixel cap against decompression bombs. The image is rotated by its
EXIF tag, cropped to a centred square, scaled to 256 px and re-encoded as PNG,
which also strips metadata (GPS, camera) from the stored file.

Each rule has a stable id that travels in the 422 detail.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

AVATAR_RULES: dict[str, str] = {
    "users.avatar.type": "The photo must be a PNG, JPEG or WebP image.",
    "users.avatar.size": "The photo is larger than 2 MB.",
    "users.avatar.content": "The file content is not a readable image of that type.",
    "users.avatar.empty": "The file is empty.",
}

ALLOWED_AVATAR_TYPES = ("image/png", "image/jpeg", "image/webp")
MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_SIZE = 256
#: Decompression-bomb guard: refuse anything that would decode to more pixels.
MAX_AVATAR_PIXELS = 40_000_000

_FORMAT_TO_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class AvatarValidationError(ValueError):
    """An avatar failed one of :data:`AVATAR_RULES`."""

    def __init__(self, rule: str) -> None:
        super().__init__(AVATAR_RULES[rule])
        self.rule = rule
        self.message = AVATAR_RULES[rule]


def sniff_mime(data: bytes) -> str | None:
    """Return the image MIME type the leading bytes declare, or None."""
    if data.startswith(bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])):
        return "image/png"
    if data.startswith(bytes([0xFF, 0xD8, 0xFF])):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def process_avatar(data: bytes, declared_type: str | None = None) -> bytes:
    """Validate an uploaded photo and return the 256 px square PNG to store.

    Args:
        data: The raw uploaded bytes.
        declared_type: The client-declared content type, if any. It must be an
            allowed type and agree with the real bytes.

    Raises:
        AvatarValidationError: naming the first rule that failed.
    """
    if not data:
        raise AvatarValidationError("users.avatar.empty")
    if len(data) > MAX_AVATAR_BYTES:
        raise AvatarValidationError("users.avatar.size")
    declared = (declared_type or "").split(";")[0].strip().lower()
    if declared and declared not in ALLOWED_AVATAR_TYPES:
        raise AvatarValidationError("users.avatar.type")
    real = sniff_mime(data)
    if real is None:
        raise AvatarValidationError("users.avatar.type")
    if declared and declared != real:
        raise AvatarValidationError("users.avatar.content")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if _FORMAT_TO_MIME.get(probe.format or "") != real:
                raise AvatarValidationError("users.avatar.content")
            width, height = probe.size
            if width * height > MAX_AVATAR_PIXELS:
                raise AvatarValidationError("users.avatar.size")
            image = ImageOps.exif_transpose(probe)
            image.load()
    except AvatarValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AvatarValidationError("users.avatar.content") from exc

    has_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
    image = image.convert("RGBA" if has_alpha else "RGB")
    image = ImageOps.fit(image, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()
