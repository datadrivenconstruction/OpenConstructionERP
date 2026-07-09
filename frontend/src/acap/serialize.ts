/**
 * Pure round-trip helpers between the schema's 4-corner CCW polygon and a
 * plain axis-aligned rect, used by the SVG editor for drag/resize math.
 *
 * Coordinate system matches the backend schema: origin at the kavling
 * south-west corner, x -> east, y -> north, meters.
 */

import type { FloorPlan, Point, Room } from './planTypes';

/** Round to a stable precision so repeated edits don't drift float noise. */
const PRECISION = 1e-6;
function round(n: number): number {
  return Math.round(n / PRECISION) * PRECISION;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Bounding-box rect of an axis-aligned room polygon. */
export function roomRect(room: Room): Rect {
  const xs = room.polygon.map((p) => p.x);
  const ys = room.polygon.map((p) => p.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  return {
    x: minX,
    y: minY,
    w: Math.max(...xs) - minX,
    h: Math.max(...ys) - minY,
  };
}

/**
 * The 4 CCW corners of an axis-aligned rect, exactly as the schema defines
 * a room polygon (first point not repeated).
 */
export function rectToPolygon(x: number, y: number, w: number, h: number): Point[] {
  return [
    { x: round(x), y: round(y) },
    { x: round(x + w), y: round(y) },
    { x: round(x + w), y: round(y + h) },
    { x: round(x), y: round(y + h) },
  ];
}

/**
 * Return a new FloorPlan with the room at [levelIndex, roomIndex]'s polygon
 * replaced by `rect`, and area_m2 recomputed as w*h. Immutable: the input
 * plan (and every level/room not touched) is left untouched.
 */
export function withRoomRect(
  plan: FloorPlan,
  levelIndex: number,
  roomIndex: number,
  rect: Rect,
): FloorPlan {
  return {
    ...plan,
    levels: plan.levels.map((level, li) => {
      if (li !== levelIndex) return level;
      return {
        ...level,
        rooms: level.rooms.map((room, ri) => {
          if (ri !== roomIndex) return room;
          return {
            ...room,
            polygon: rectToPolygon(rect.x, rect.y, rect.w, rect.h),
            area_m2: round(rect.w * rect.h),
          };
        }),
      };
    }),
  };
}
