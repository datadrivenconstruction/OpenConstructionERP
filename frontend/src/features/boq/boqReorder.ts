// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Orders sent to the reorder endpoint. The server writes `sort_order` = index
 * for exactly the ids it receives, so a partial list leaves the others at
 * their old numbers and the moved rows land between them or fall back.
 * Both helpers therefore always return every position of the bill.
 * Pure functions, no React.
 */

import { isSection, type Position } from './api';

type Row = Pick<Position, 'id' | 'parent_id' | 'sort_order' | 'ordinal' | 'unit'>;

function byOrder(a: Row, b: Row): number {
  if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
  return (a.ordinal ?? '').localeCompare(b.ordinal ?? '', undefined, { numeric: true });
}

function parentOf(p: Row, ids: Set<string>): string | null {
  return p.parent_id && ids.has(p.parent_id) ? p.parent_id : null;
}

/**
 * The section a drop on `overId` means, at the level of the moved section:
 * `overId` itself when it is a sibling, otherwise its nearest ancestor that
 * is. A row outside the moved section's parent has no such ancestor.
 */
export function siblingDropTarget(positions: Row[], movedId: string, overId: string): string | null {
  const byId = new Map(positions.map((p) => [p.id, p]));
  const ids = new Set(byId.keys());
  const moved = byId.get(movedId);
  if (!moved || !byId.has(overId)) return null;
  const level = parentOf(moved, ids);
  const seen = new Set<string>();
  let cur: Row | undefined = byId.get(overId);
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    if (cur.id !== movedId && isSection(cur) && parentOf(cur, ids) === level) return cur.id;
    if (cur.id === movedId) return null;
    const up = parentOf(cur, ids);
    cur = up ? byId.get(up) : undefined;
  }
  return null;
}

/**
 * Every position id in document order after section `movedId` takes the place
 * of its sibling `targetId` (after it when moving down, before it when moving
 * up). The section keeps its sub-sections and lines.
 */
export function orderAfterSectionMove(positions: Row[], movedId: string, targetId: string): string[] | null {
  const ids = new Set(positions.map((p) => p.id));
  const kids = new Map<string | null, Row[]>();
  for (const p of [...positions].sort(byOrder)) {
    const key = parentOf(p, ids);
    kids.set(key, [...(kids.get(key) ?? []), p]);
  }
  const moved = positions.find((p) => p.id === movedId);
  if (!moved) return null;
  const siblings = kids.get(parentOf(moved, ids)) ?? [];
  const from = siblings.findIndex((p) => p.id === movedId);
  const to = siblings.findIndex((p) => p.id === targetId);
  if (from < 0 || to < 0 || from === to) return null;
  const next = [...siblings];
  const [item] = next.splice(from, 1);
  if (item) next.splice(to, 0, item);
  kids.set(parentOf(moved, ids), next);

  const out: string[] = [];
  const walk = (parent: string | null, guard: Set<string>) => {
    for (const child of kids.get(parent) ?? []) {
      if (guard.has(child.id)) continue;
      guard.add(child.id);
      out.push(child.id);
      walk(child.id, guard);
    }
  };
  walk(null, new Set());
  return out;
}

/**
 * Every position id after the lines in `visibleOrder` were rearranged in the
 * grid. They take over, in their new order, the slots they held in the bill's
 * current order; sections and lines the grid did not show keep theirs.
 */
export function orderAfterLineMove(positions: Row[], visibleOrder: string[]): string[] {
  const current = [...positions].sort(byOrder).map((p) => p.id);
  const moving = new Set(visibleOrder.filter((id) => current.includes(id)));
  const queue = visibleOrder.filter((id) => moving.has(id));
  let i = 0;
  return current.map((id) => (moving.has(id) ? (queue[i++] ?? id) : id));
}
