import { describe, it, expect } from 'vitest';
import { planToMeshes } from './planTo3d';
import type { FloorPlan } from '@/acap/planTypes';

const TWO_STOREY_PLAN: FloorPlan = {
  kavling: { width_m: 10, length_m: 10 },
  levels: [
    {
      level: 1,
      rooms: [
        {
          name: 'Room A',
          type: 'ruang_tamu',
          polygon: [
            { x: 0, y: 0 },
            { x: 5, y: 0 },
            { x: 5, y: 4 },
            { x: 0, y: 4 },
          ],
          area_m2: 20,
        },
        {
          name: 'Room B',
          type: 'kamar_tidur',
          polygon: [
            { x: 0, y: 4 },
            { x: 5, y: 4 },
            { x: 5, y: 8 },
            { x: 0, y: 8 },
          ],
          area_m2: 20,
        },
      ],
      walls: [],
      openings: [],
    },
    {
      level: 2,
      rooms: [
        {
          name: 'Room C',
          type: 'kamar_tidur_utama',
          polygon: [
            { x: 0, y: 0 },
            { x: 5, y: 0 },
            { x: 5, y: 4 },
            { x: 0, y: 4 },
          ],
          area_m2: 20,
        },
      ],
      walls: [],
      openings: [],
    },
  ],
  requirement_text: '',
  jumlah_lantai: 2,
  generated_by: 'test',
  notes: '',
};

describe('planToMeshes', () => {
  it('produces one slab per room at z=0 for ground floor', () => {
    const { floors } = planToMeshes(TWO_STOREY_PLAN);
    expect(floors).toHaveLength(3);
    const groundFloors = floors.filter((s) => s.z === 0);
    expect(groundFloors).toHaveLength(2);
  });

  it('stacks the level-2 slab at z = (level-1) * wall height', () => {
    const { floors } = planToMeshes(TWO_STOREY_PLAN);
    // Room C lives on level 2; its slab z = (2-1) * WALL_HEIGHT_M (3.0) = 3.0.
    // (The level-2 WALL base is 3.2 — WALL_HEIGHT_M + SLAB_THICKNESS_M — but the
    //  slab top itself sits at 3.0, on top of the ground-floor walls.)
    const level2Slabs = floors.filter((s) => s.z > 0);
    expect(level2Slabs).toHaveLength(1);
    expect(level2Slabs[0]!.z).toBe(3.0);
  });

  it('deduplicates shared edges into one wall', () => {
    const { walls } = planToMeshes(TWO_STOREY_PLAN);
    // Room A: 4 edges, Room B: 4 edges, shared edge (0,4)-(5,4) deduped → 7 unique
    // Room C (level 2): 4 edges (no shared edge on its level) → 4 unique
    // Total unique walls: 7 + 4 = 11
    expect(walls).toHaveLength(11);
  });

  it('places level-2 walls at z-base 3.2', () => {
    const { walls } = planToMeshes(TWO_STOREY_PLAN);
    const level2Walls = walls.filter((w) => w.cz > 1.6);
    expect(level2Walls.length).toBeGreaterThanOrEqual(4);
    // z-center at 3.2 + 1.5 = 4.7
    level2Walls.forEach((w) => {
      expect(Math.abs(w.cz - 4.7)).toBeLessThan(0.01);
      expect(w.height).toBe(3.0);
    });
  });

  it('ground-floor walls have z-center 1.5', () => {
    const { walls } = planToMeshes(TWO_STOREY_PLAN);
    const groundWalls = walls.filter((w) => w.cz < 2.0);
    expect(groundWalls.length).toBeGreaterThanOrEqual(7);
    groundWalls.forEach((w) => {
      expect(Math.abs(w.cz - 1.5)).toBeLessThan(0.01);
    });
  });
});
