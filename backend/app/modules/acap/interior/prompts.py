"""Interior render prompt builder — composes GeminiGen prompts per room + style."""

from __future__ import annotations

STYLES: dict[str, str] = {
    "minimalis": "Minimalist interior: clean lines, neutral white and beige palette, minimal furniture, open space, uncluttered surfaces, soft indirect lighting.",
    "skandinavia": "Scandinavian interior: bright white walls, light wood floors, cozy textiles, simple functional furniture, warm hygge atmosphere, plenty of natural light.",
    "japandi": "Japandi interior: warm wood, low furniture, soft neutral palette, paper lantern lighting, clean lines, subtle wabi-sabi texture, zen atmosphere.",
    "industrial": "Industrial interior: exposed concrete walls, dark metal accents, high ceilings, large windows, Edison bulb lighting, raw materials, urban loft feel.",
    "klasik": "Classic interior: ornate moldings, warm beige and cream palette, crystal chandelier, dark hardwood floors, elegant furniture, rich drapery, timeless luxury.",
}

ROOM_HINTS: dict[str, str] = {
    "kamar_tidur_utama": "master bedroom with queen bed",
    "kamar_tidur": "small bedroom with single bed",
    "kamar_mandi": "bathroom with shower and vanity",
    "dapur": "kitchen with counter and cabinets",
    "ruang_tamu": "living room with sofa set",
    "ruang_keluarga": "family room with TV area",
    "ruang_makan": "dining room with dining table",
    "carport": "carport with parked car",
    "garasi": "garage with storage",
    "musholla": "small prayer room with prayer mat",
    "gudang": "storage room with shelves",
    "teras": "terrace with outdoor furniture",
    "taman": "garden with plants and pathway",
    "sirkulasi": "hallway corridor",
    "other": "room interior",
}


def build_interior_prompt(
    room_name: str,
    room_type: str,
    area_m2: float,
    style: str,
) -> str:
    """Compose a photoreal interior render prompt for GeminiGen.

    Args:
        room_name: Human-readable room name (e.g. "Kamar Tidur Utama").
        room_type: One of the ROOM_TYPES literals.
        area_m2: Room area in square meters.
        style: One of the known style keys (minimalis/skandinavia/japandi/industrial/klasik).

    Returns:
        A prompt string ready for ``generate_render_image``.

    Raises:
        ValueError: *style* is not in STYLES.
    """
    style_fragment = STYLES.get(style)
    if style_fragment is None:
        raise ValueError(f"Unknown interior style: {style!r}. Known: {list(STYLES.keys())}")

    room_hint = ROOM_HINTS.get(room_type, "room interior")
    # Defense-in-depth: room_name is bounded by Room.name (max_length=120) at the
    # schema, but hard-cap here too so a raw/legacy plan can't inflate the prompt
    # sent to the paid image provider.
    room_name = (room_name or "")[:120]
    return (
        f"Photoreal interior render of a {room_hint} named \"{room_name}\" "
        f"in an Indonesian tropical residence in Batam, ~{area_m2} m2. "
        f"{style_fragment} "
        f"Eye-level camera, natural daylight, 4:3 aspect ratio, highly detailed."
    )
