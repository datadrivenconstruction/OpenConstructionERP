"""Floor-plan JSON -> image-render prompt (pure, deterministic).

Deliberately THIN: an architectural render is a factual scene description of
the plan (storeys, lot, rooms). Per the project's image-gen doctrine, creative
hook/visual-identity rules do NOT live in app code — they belong to the
``ai-image-carousel-prompt-gen`` bundle. For an architectural still that is
mostly a faithful description of the building, so this stays minimal and never
invents rooms or dimensions the plan doesn't have.
"""

from __future__ import annotations

from app.modules.acap.layout.schema import FloorPlan

# Fixed render-style suffix — a house exterior still. Kept as one reviewable
# constant, not a per-topic creative layer.
_STYLE_SUFFIX = (
    "Photorealistic architectural exterior rendering, tropical daylight, "
    "natural materials, modern minimalist Indonesian house, clean composition, "
    "three-quarter front view."
)


def build_render_prompt(plan: FloorPlan) -> str:
    """Compose a factual render prompt from *plan*.

    Lists every room (name, human-readable type, area) across all levels plus
    the storey count and lot size — nothing the plan doesn't state.
    """
    rooms = [
        f"{room.name} ({room.type.replace('_', ' ')}, {room.area_m2:.0f} m2)"
        for level in plan.levels
        for room in level.rooms
    ]
    room_desc = "; ".join(rooms) if rooms else "no rooms defined"
    lot = f"{plan.kavling.width_m:.0f}x{plan.kavling.length_m:.0f} m lot"

    return (
        f"A {plan.jumlah_lantai}-storey house on a {lot}. "
        f"Rooms: {room_desc}. {_STYLE_SUFFIX}"
    )


# ── Self-check (pure, no deps) ────────────────────────────────────────────
if __name__ == "__main__":
    from app.modules.acap.layout.schema import Kavling, Level, Point, Room

    r = Room(
        name="Kamar Tidur",
        type="kamar_tidur",
        polygon=[Point(x=0, y=0), Point(x=3, y=0), Point(x=3, y=4), Point(x=0, y=4)],
        area_m2=12.0,
    )
    p = FloorPlan(kavling=Kavling(width_m=8.0, length_m=10.0), levels=[Level(level=1, rooms=[r])])
    out = build_render_prompt(p)
    assert "kamar tidur" in out and "12 m2" in out and "1-storey" in out and "8x10 m lot" in out, out
    print("prompt self-check OK:", out)
