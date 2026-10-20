// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Block definitions: grouping them off the wire, and placing them in the world.
 *
 * The wire is a flat list. An entity carries either `layout` (it is placed on a
 * sheet) or `block` (it is a member of a definition), never both. A definition
 * member's coordinates are in the block's own space and mean nothing until an
 * INSERT places them, which is why nothing here may go straight to the canvas.
 *
 * `expandBlockReferences` turns each INSERT into placed copies of its
 * definition, in world coordinates, so the rest of the viewer needs no idea
 * blocks exist: the fit box, the culling, the layer filter and the text clamp
 * all work on the copies exactly as they work on ordinary geometry.
 */

import type { DxfEntity } from '../api';

/** Definition name -> its member entities, in wire order. */
export type BlockDefs = ReadonlyMap<string, DxfEntity[]>;

/**
 * Deepest chain of INSERT-inside-definition we will follow.
 *
 * A definition may contain an INSERT of another block, and an export can be
 * self-referential. Depth alone does not stop a two-block cycle from costing
 * 2^8 placements, so the visited set below stops cycles and this stops honest
 * but absurd nesting. A hung canvas in a takeoff tool reads as a crash.
 */
const MAX_BLOCK_DEPTH = 8;

/** Group definition members by the block they belong to. */
export function groupBlockDefinitions(entities: DxfEntity[]): BlockDefs {
  const defs = new Map<string, DxfEntity[]>();
  for (const e of entities) {
    if (!e.block) continue;
    const members = defs.get(e.block);
    if (members) members.push(e);
    else defs.set(e.block, [e]);
  }
  return defs;
}

/** An accumulated block-to-world transform. Angles are radians, CCW. */
interface Placement {
  x: number;
  y: number;
  rot: number;
  xs: number;
  ys: number;
}

const IDENTITY: Placement = { x: 0, y: 0, rot: 0, xs: 1, ys: 1 };

/** Map a point from block space into world space. */
function place(p: Placement, x: number, y: number): { x: number; y: number } {
  const sx = x * p.xs;
  const sy = y * p.ys;
  const cos = Math.cos(p.rot);
  const sin = Math.sin(p.rot);
  return { x: p.x + sx * cos - sy * sin, y: p.y + sx * sin + sy * cos };
}

/**
 * Compose an INSERT's own transform onto the placement that contains it.
 *
 * Exact when the outer placement scales uniformly or the inner INSERT is
 * unrotated, and an approximation otherwise, because a rotation and a
 * non-uniform scale do not commute - the honest general form is a full 3x3
 * matrix per entity. Nested inserts under an anisotropic outer scale are rare
 * enough that carrying a matrix through every entity type costs more than it
 * returns here; the approximation is documented rather than hidden.
 */
function compose(outer: Placement, insert: DxfEntity): Placement {
  const pos = place(outer, insert.start?.x ?? 0, insert.start?.y ?? 0);
  return {
    x: pos.x,
    y: pos.y,
    rot: outer.rot + (insert.rotation ?? 0),
    xs: outer.xs * (insert.x_scale ?? 1),
    ys: outer.ys * (insert.y_scale ?? 1),
  };
}

/** True when the placement scales both axes by the same magnitude. */
function isUniform(p: Placement): boolean {
  return Math.abs(Math.abs(p.xs) - Math.abs(p.ys)) < 1e-9;
}

/** True when the placement reverses orientation (an odd number of mirrors). */
function isMirrored(p: Placement): boolean {
  return p.xs * p.ys < 0;
}

/**
 * Map an angle from block space to world space under `p`.
 *
 * Only meaningful for a similarity, i.e. `isUniform(p)`. A mirror reverses the
 * sense of the angle before the rotation is added, which is why an arc drawn
 * through a mirrored insert also has to swap its endpoints - reflecting a
 * counter-clockwise sweep gives a clockwise one, and the renderer only draws
 * counter-clockwise.
 */
function placeAngle(p: Placement, a: number): number {
  if (p.xs < 0 && p.ys > 0) return p.rot + Math.PI - a;
  if (p.ys < 0 && p.xs > 0) return p.rot - a;
  if (p.xs < 0 && p.ys < 0) return p.rot + Math.PI + a;
  return p.rot + a;
}

/**
 * One definition member, moved into world space under `p`.
 *
 * Returns null for the members this placement cannot draw honestly. That is a
 * deliberate silence: an arc under a non-uniform scale is an elliptical arc,
 * which the renderer has no shape for, and drawing it as a circular one bulges
 * it the wrong way. A missing arc inside an otherwise correct block is a
 * smaller lie than a wrong one, and unlike a wrong one it is visible as
 * missing.
 */
function placeEntity(member: DxfEntity, p: Placement, insert: DxfEntity, id: string): DxfEntity | null {
  const scale = Math.abs(p.xs);
  const uniform = isUniform(p);

  // A member authored on ACI 0 is ByBlock: it takes the reference's colour.
  // Its layer always comes from the reference, because a block's visibility is
  // governed by the INSERT that places it rather than by the layer its parts
  // were drawn on - usually "0", which the user never sees in the layer panel.
  const placed: DxfEntity = {
    ...member,
    id,
    layer: insert.layer,
    color: member.color === 0 ? insert.color : member.color,
    layout: insert.layout,
  };
  delete placed.block;

  if (member.start) {
    placed.start = { ...member.start, ...place(p, member.start.x, member.start.y) };
  }
  if (member.end) {
    placed.end = { ...member.end, ...place(p, member.end.x, member.end.y) };
  }
  if (member.vertices) {
    placed.vertices = member.vertices.map((v) => ({ ...v, ...place(p, v.x, v.y) }));
  }

  switch (member.type) {
    case 'CIRCLE':
      if (member.radius == null) break;
      if (uniform) {
        placed.radius = member.radius * scale;
      } else {
        // A circle under an anisotropic scale is an ellipse, and the renderer
        // already draws that shape from explicit radii.
        placed.type = 'ELLIPSE';
        placed.major_radius = member.radius * Math.abs(p.xs);
        placed.minor_radius = member.radius * Math.abs(p.ys);
        placed.rotation = p.rot;
        delete placed.radius;
      }
      break;
    case 'ARC': {
      if (member.radius == null) break;
      if (!uniform) {
        // An arc under an anisotropic scale is an elliptical arc: axes along the
        // insert's own x and y, the circle angle becoming the ellipse parameter.
        const t1 = placeAngle(p, member.start_angle ?? 0) - p.rot;
        const t2 = placeAngle(p, member.end_angle ?? Math.PI * 2) - p.rot;
        placed.type = 'ELLIPSE';
        placed.major_radius = member.radius * Math.abs(p.xs);
        placed.minor_radius = member.radius * Math.abs(p.ys);
        placed.rotation = p.rot;
        placed.start_angle = isMirrored(p) ? t2 : t1;
        placed.end_angle = isMirrored(p) ? t1 : t2;
        delete placed.radius;
        break;
      }
      placed.radius = member.radius * scale;
      const a1 = placeAngle(p, member.start_angle ?? 0);
      const a2 = placeAngle(p, member.end_angle ?? Math.PI * 2);
      // A mirror turns a CCW sweep into a CW one; swapping the endpoints
      // states the same arc in the CCW sense the renderer expects.
      placed.start_angle = isMirrored(p) ? a2 : a1;
      placed.end_angle = isMirrored(p) ? a1 : a2;
      break;
    }
    case 'ELLIPSE': {
      if (!uniform) return null;
      if (member.major_radius != null) placed.major_radius = member.major_radius * scale;
      if (member.minor_radius != null) placed.minor_radius = member.minor_radius * scale;
      if (member.major_axis) {
        const o = place(p, 0, 0);
        const tip = place(p, member.major_axis.x, member.major_axis.y);
        placed.major_axis = { x: tip.x - o.x, y: tip.y - o.y };
      }
      placed.rotation = placeAngle(p, member.rotation ?? 0);
      if (isMirrored(p) && member.start_angle != null && member.end_angle != null) {
        // A mirror reverses the parameter: t -> -t, and the CCW range swaps ends.
        placed.start_angle = -member.end_angle;
        placed.end_angle = -member.start_angle;
      }
      break;
    }
    case 'TEXT':
      // Text is never mirrored on screen even when its block is: a backwards
      // label carries less than a readable one, and this viewer is read.
      placed.height = (member.height ?? 2.5) * Math.abs(p.ys);
      placed.rotation = (member.rotation ?? 0) + p.rot;
      break;
    default:
      if (member.rotation != null) placed.rotation = member.rotation + p.rot;
      break;
  }

  return placed;
}

/**
 * Replace every resolvable INSERT with placed copies of its definition.
 *
 * Returns only the placed geometry. The caller keeps its original list and
 * appends this, so an INSERT whose definition never arrived still reaches the
 * renderer and still draws its marker - a definition can be genuinely absent,
 * and a marker there is better than nothing at all.
 */
export function expandBlockReferences(entities: DxfEntity[], blockDefs: BlockDefs): DxfEntity[] {
  if (blockDefs.size === 0) return [];
  const out: DxfEntity[] = [];

  const walk = (insert: DxfEntity, p: Placement, depth: number, chain: Set<string>): void => {
    const name = insert.block_name;
    if (!name || depth >= MAX_BLOCK_DEPTH || chain.has(name)) return;
    const members = blockDefs.get(name);
    if (!members || members.length === 0) return;

    // Per-chain, not global: a block placed twice at the same depth is two
    // legitimate placements, and a shared set would silently drop the second.
    chain.add(name);
    for (const member of members) {
      const id = `${insert.id}/${member.id}`;
      if (member.type === 'INSERT') {
        walk({ ...member, id, layer: insert.layer, layout: insert.layout }, compose(p, member), depth + 1, chain);
        continue;
      }
      const placed = placeEntity(member, p, insert, id);
      if (placed) out.push(placed);
    }
    chain.delete(name);
  };

  for (const e of entities) {
    if (e.type !== 'INSERT' || e.block) continue;
    walk(e, compose(IDENTITY, e), 0, new Set<string>());
  }

  return out;
}

/** True when this INSERT resolved to geometry, so its marker is redundant. */
export function isResolvedInsert(entity: DxfEntity, blockDefs: BlockDefs): boolean {
  if (entity.type !== 'INSERT' || !entity.block_name) return false;
  const members = blockDefs.get(entity.block_name);
  return !!members && members.length > 0;
}
