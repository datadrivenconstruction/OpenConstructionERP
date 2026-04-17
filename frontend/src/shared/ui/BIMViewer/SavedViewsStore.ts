/**
 * SavedViewsStore — localStorage-backed camera bookmarks per BIM model.
 *
 * Stores camera position + target plus an optional filter snapshot so the user
 * can jump back to a specific inspection angle after panning away. RFC 19 §4.1.
 *
 * Quota cap: 100 views per model. When exceeded, the oldest view is evicted
 * before the new one is written, and `addViewpoint` returns `quotaExceeded`
 * so the caller can surface a warning in the UI.
 */

const MAX_VIEWS_PER_MODEL = 100;

/** Snapshot of the filter panel's state — opaque to the store. */
export type BIMFilterState = Record<string, unknown>;

export interface Viewpoint {
  id: string;
  name: string;
  cameraPos: [number, number, number];
  target: [number, number, number];
  filterState?: BIMFilterState;
  createdAt: string;
}

export interface AddViewpointResult {
  viewpoint: Viewpoint;
  quotaExceeded: boolean;
}

const storageKey = (modelId: string): string => `oe_bim_views_${modelId}`;

function randomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `vp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

function readAll(modelId: string): Viewpoint[] {
  try {
    const raw = localStorage.getItem(storageKey(modelId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (v): v is Viewpoint =>
        !!v &&
        typeof v === 'object' &&
        typeof (v as Viewpoint).id === 'string' &&
        Array.isArray((v as Viewpoint).cameraPos) &&
        Array.isArray((v as Viewpoint).target),
    );
  } catch {
    return [];
  }
}

function writeAll(modelId: string, views: Viewpoint[]): void {
  try {
    localStorage.setItem(storageKey(modelId), JSON.stringify(views));
  } catch {
    // Quota or serialization error — callers treat this as a best-effort op.
  }
}

export function listViewpoints(modelId: string): Viewpoint[] {
  return readAll(modelId);
}

export function getViewpoint(modelId: string, viewpointId: string): Viewpoint | null {
  return readAll(modelId).find((v) => v.id === viewpointId) ?? null;
}

export function addViewpoint(
  modelId: string,
  input: Omit<Viewpoint, 'id' | 'createdAt'>,
): AddViewpointResult {
  const all = readAll(modelId);
  let quotaExceeded = false;
  // Drop the oldest entry (first in list — we preserve insertion order).
  if (all.length >= MAX_VIEWS_PER_MODEL) {
    all.shift();
    quotaExceeded = true;
  }
  const viewpoint: Viewpoint = {
    ...input,
    id: randomId(),
    createdAt: new Date().toISOString(),
  };
  all.push(viewpoint);
  writeAll(modelId, all);
  return { viewpoint, quotaExceeded };
}

export function removeViewpoint(modelId: string, viewpointId: string): boolean {
  const all = readAll(modelId);
  const next = all.filter((v) => v.id !== viewpointId);
  if (next.length === all.length) return false;
  writeAll(modelId, next);
  return true;
}

export const __test__ = {
  storageKey,
  MAX_VIEWS_PER_MODEL,
};
