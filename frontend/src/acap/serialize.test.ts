import { describe, it, expect } from 'vitest';
import { roomRect, rectToPolygon, withRoomRect } from './serialize';
import type { FloorPlan } from './planTypes';

const FIXTURE_PLAN: FloorPlan = {
  kavling: { width_m: 8, length_m: 15 },
  levels: [
    {
      level: 1,
      rooms: [
        {
          name: 'K. Tidur',
          type: 'kamar_tidur',
          polygon: [
            { x: 0, y: 0 },
            { x: 3, y: 0 },
            { x: 3, y: 3 },
            { x: 0, y: 3 },
          ],
          area_m2: 9,
        },
        {
          name: 'Sirkulasi',
          type: 'sirkulasi',
          polygon: [
            { x: 3, y: 0 },
            { x: 5, y: 0 },
            { x: 5, y: 2 },
            { x: 3, y: 2 },
          ],
          area_m2: 4,
        },
      ],
      walls: [],
      openings: [],
    },
  ],
  requirement_text: 'test',
  jumlah_lantai: 1,
  generated_by: 'test',
  notes: '',
};

const FIXTURE_ROOMS = FIXTURE_PLAN.levels[0]!.rooms;
const FIXTURE_ROOM_0 = FIXTURE_ROOMS[0]!;

describe('roomRect / rectToPolygon round-trip', () => {
  for (const room of FIXTURE_ROOMS) {
    it(`is lossless for room "${room.name}"`, () => {
      const rect = roomRect(room);
      const polygon = rectToPolygon(rect.x, rect.y, rect.w, rect.h);
      expect(polygon).toEqual(room.polygon);
    });
  }
});

describe('withRoomRect', () => {
  it('is a no-op when given the same rect', () => {
    const rect = roomRect(FIXTURE_ROOM_0);
    const updated = withRoomRect(FIXTURE_PLAN, 0, 0, rect);
    const updatedRoom = updated.levels[0]!.rooms[0]!;
    expect(updatedRoom.polygon).toEqual(FIXTURE_ROOM_0.polygon);
    expect(updatedRoom.area_m2).toBeCloseTo(FIXTURE_ROOM_0.area_m2, 6);
  });

  it('does not mutate the original plan (immutable update)', () => {
    const rect = roomRect(FIXTURE_ROOM_0);
    withRoomRect(FIXTURE_PLAN, 0, 0, { ...rect, x: rect.x + 1 });
    // Original fixture untouched.
    expect(FIXTURE_PLAN.levels[0]!.rooms[0]!.polygon).toEqual(FIXTURE_ROOM_0.polygon);
  });

  it('replaces the polygon and recomputes area_m2 for a moved/resized rect', () => {
    const updated = withRoomRect(FIXTURE_PLAN, 0, 1, { x: 3, y: 2, w: 2, h: 3 });
    const room = updated.levels[0]!.rooms[1]!;
    expect(room.polygon).toEqual([
      { x: 3, y: 2 },
      { x: 5, y: 2 },
      { x: 5, y: 5 },
      { x: 3, y: 5 },
    ]);
    expect(room.area_m2).toBeCloseTo(6, 6);
  });
});
