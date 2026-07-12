import type { FloorPlan, Point } from '@/acap/planTypes';

export const WALL_HEIGHT_M = 3.0;
export const SLAB_THICKNESS_M = 0.2;
export const WALL_THICKNESS_M = 0.15;

export interface Slab {
  x: number;
  y: number;
  w: number;
  l: number;
  z: number;
}

export interface WallBox {
  cx: number;
  cy: number;
  cz: number;
  lenX: number;
  lenY: number;
  height: number;
}

function edgeKey(a: Point, b: Point): string {
  const pts = [a, b].sort((p, q) => p.x - q.x || p.y - q.y);
  return `${Math.round(pts[0].x * 1000)},${Math.round(pts[0].y * 1000)}-${Math.round(pts[1].x * 1000)},${Math.round(pts[1].y * 1000)}`;
}

export function planToMeshes(plan: FloorPlan): { floors: Slab[]; walls: WallBox[] } {
  const floors: Slab[] = [];
  const walls: WallBox[] = [];

  for (const level of plan.levels) {
    const slabZ = (level.level - 1) * WALL_HEIGHT_M;
    const wallBaseZ = (level.level - 1) * (WALL_HEIGHT_M + SLAB_THICKNESS_M);
    const wallCZ = wallBaseZ + WALL_HEIGHT_M / 2;
    const seenEdges = new Set<string>();

    for (const room of level.rooms) {
      const xs = room.polygon.map((p) => p.x);
      const ys = room.polygon.map((p) => p.y);
      const minX = Math.min(...xs);
      const minY = Math.min(...ys);
      const maxX = Math.max(...xs);
      const maxY = Math.max(...ys);

      floors.push({ x: minX, y: minY, w: maxX - minX, l: maxY - minY, z: slabZ });

      const poly = room.polygon;
      for (let i = 0; i < poly.length; i++) {
        const j = (i + 1) % poly.length;
        const a = poly[i];
        const b = poly[j];
        const key = edgeKey(a, b);
        if (seenEdges.has(key)) continue;
        seenEdges.add(key);

        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const isHorizontal = dy === 0;
        const length = isHorizontal ? Math.abs(dx) : Math.abs(dy);

        walls.push(
          isHorizontal
            ? {
                cx: (a.x + b.x) / 2,
                cy: a.y,
                cz: wallCZ,
                lenX: length,
                lenY: WALL_THICKNESS_M,
                height: WALL_HEIGHT_M,
              }
            : {
                cx: a.x,
                cy: (a.y + b.y) / 2,
                cz: wallCZ,
                lenX: WALL_THICKNESS_M,
                lenY: length,
                height: WALL_HEIGHT_M,
              },
        );
      }
    }
  }

  return { floors, walls };
}
