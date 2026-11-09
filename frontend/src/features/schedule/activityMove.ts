import type { Activity, ActivityMoveRequest } from './api';
import { orderAsTree } from './activityTree';

export interface SiblingMoves {
  up: ActivityMoveRequest | null;
  down: ActivityMoveRequest | null;
}

/** The request that moves `id` one place up or down among its siblings; null when it is already first or last. */
export function siblingMoves(id: string, outline: readonly Activity[]): SiblingMoves {
  const me = outline.find((a) => a.id === id);
  if (!me) return { up: null, down: null };
  const parent = me.parent_id ?? null;
  const present = new Set(outline.map((a) => a.id));
  const siblings = orderAsTree(outline).filter((a) => {
    const p = a.parent_id && present.has(a.parent_id) ? a.parent_id : null;
    return p === (parent && present.has(parent) ? parent : null);
  });
  const i = siblings.findIndex((a) => a.id === id);
  const prev = i > 0 ? siblings[i - 1] : undefined;
  const next = i >= 0 ? siblings[i + 1] : undefined;
  return {
    up: prev ? { target_id: prev.id, position: 'before' } : null,
    down: next ? { target_id: next.id, position: 'after' } : null,
  };
}
