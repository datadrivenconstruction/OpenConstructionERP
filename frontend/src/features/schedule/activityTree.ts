// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tree helpers for the schedule Table view.
 *
 * The API returns activities in one flat order (``sort_order``, then WBS
 * code). A row created inside a section before the server placed children in
 * their section's block sits at the bottom of that flat order, so the table
 * re-reads the flat list as a tree: every row directly under its parent, with
 * siblings kept in the order the server sent them.
 *
 * Collapsing lives here too. Which sections CAN be collapsed is read from the
 * whole list, never from the list with collapsed rows removed: a collapsed
 * section has no visible children, and deriving "has children" from what is
 * visible removed the very chevron that expands it again.
 */

interface TreeNode {
  id: string;
  parent_id?: string | null;
}

/**
 * Order ``items`` depth first: each row followed by its children.
 *
 * Siblings keep their incoming order. A row whose parent is not in the list
 * (filtered out, or a dangling id) is treated as a root at its own position,
 * so a filter never drops rows. A parent cycle cannot loop: each row is
 * emitted once.
 */
export function orderAsTree<T extends TreeNode>(items: readonly T[]): T[] {
  const present = new Set(items.map((a) => a.id));
  const children = new Map<string, T[]>();
  const roots: T[] = [];
  for (const a of items) {
    const pid = a.parent_id ?? null;
    if (pid && pid !== a.id && present.has(pid)) {
      const list = children.get(pid);
      if (list) list.push(a);
      else children.set(pid, [a]);
    } else {
      roots.push(a);
    }
  }
  const out: T[] = [];
  const seen = new Set<string>();
  const visit = (a: T) => {
    if (seen.has(a.id)) return;
    seen.add(a.id);
    out.push(a);
    for (const c of children.get(a.id) ?? []) visit(c);
  };
  for (const r of roots) visit(r);
  // Rows caught in a parent cycle are reachable from no root; keep them.
  for (const a of items) visit(a);
  return out;
}

/** Ids of every row that has at least one child in ``items``. */
export function parentIdsOf(items: readonly TreeNode[]): Set<string> {
  const set = new Set<string>();
  for (const a of items) if (a.parent_id) set.add(a.parent_id);
  return set;
}

/** Drop every row that sits, at any depth, under a collapsed section. */
export function hideCollapsed<T extends TreeNode>(items: readonly T[], collapsedIds: ReadonlySet<string>): T[] {
  if (collapsedIds.size === 0) return [...items];
  const parentOf = new Map<string, string>();
  for (const a of items) if (a.parent_id) parentOf.set(a.id, a.parent_id);
  const hidden = new Map<string, boolean>();
  const isHidden = (id: string, depth = 0): boolean => {
    const known = hidden.get(id);
    if (known !== undefined) return known;
    const pid = parentOf.get(id);
    // The depth cap stops a parent cycle from recursing forever.
    const result = !!pid && depth < items.length && (collapsedIds.has(pid) || isHidden(pid, depth + 1));
    hidden.set(id, result);
    return result;
  };
  return items.filter((a) => !isHidden(a.id));
}

/** ``id`` and every ancestor above it, nearest first. */
export function ancestorsOf(id: string, items: readonly TreeNode[]): string[] {
  const parentOf = new Map<string, string>();
  for (const a of items) if (a.parent_id) parentOf.set(a.id, a.parent_id);
  const out: string[] = [];
  let cur: string | undefined = id;
  while (cur && !out.includes(cur)) {
    out.push(cur);
    cur = parentOf.get(cur);
  }
  return out;
}
