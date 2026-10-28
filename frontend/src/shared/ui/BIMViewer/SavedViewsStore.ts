// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SavedViewsStore — localStorage-backed camera bookmarks per BIM model.
 *
 * Stores camera position + target plus an optional filter snapshot so the user
 * can jump back to a specific inspection angle after panning away. RFC 19 §4.1.
 *
 * v3.12.0 — extended viewpoint capture (Stream D):
 *   - filterState     : storey / type / discipline / isolation selections from
 *                       BIMFilterPanel, serialised as plain arrays so they
 *                       round-trip through JSON (Sets do not).
 *   - clipState       : section-box / clipping-plane mode + extent + axis
 *                       (mirrors ClipManager state — restoring a view brings
 *                       back the exact cut the user had open).
 *   - screenshotDataUrl: optional base64 PNG thumbnail captured from the
 *                       renderer at save time. Renders as a 96×64 preview on
 *                       the saved-view card. Stripped out of the payload when
 *                       absent so existing localStorage entries still parse.
 *
 * Quota cap: 100 views per model. When exceeded, the oldest view is evicted
 * before the new one is written, and `addViewpoint` returns `quotaExceeded`
 * so the caller can surface a warning in the UI.
 *
 * NOTE: server persistence (sync to ``oe_bim_saved_view`` table) is deferred
 * to v3.13.0 — it requires an alembic migration which is out of scope for
 * Stream D. The localStorage path is the source of truth until then.
 */

import type { SceneManager } from './SceneManager';
import { uuid } from '@/shared/lib/browser';

const MAX_VIEWS_PER_MODEL = 100;

/** Default tween duration when restoring a saved view (W6.6). */
export const DEFAULT_RESTORE_DURATION_MS = 600;

/**
 * Snapshot of the BIM filter panel state, serialised for storage.
 *
 * Named ``SavedBIMFilterState`` (not ``BIMFilterState``) because the live
 * panel state in ``features/bim/BIMFilterPanel.tsx`` already uses that
 * shorter name and shapes its selections as ``Set<string>``. This shape
 * here is the JSON-friendly variant — Sets become arrays so the payload
 * survives ``JSON.stringify``. All keys are optional — older viewpoints
 * that pre-date Stream D will only carry ``cameraPos`` + ``target``.
 */
export interface SavedBIMFilterState {
  /** Free-text search term applied to element names / types. */
  search?: string;
  /** Storey names selected in the panel (empty array = show all). */
  storeys?: string[];
  /** Element types selected in the panel (empty array = show all). */
  types?: string[];
  /** Disciplines selected in the panel (architectural / structural / MEP / …). */
  disciplines?: string[];
  /** Element IDs currently isolated (hidden-rest mode). Null = no isolation. */
  isolatedIds?: string[] | null;
  /** "Buildings only" toggle — strips analytical / annotation categories. */
  buildingsOnly?: boolean;
}

/** Snapshot of the ClipManager state (section box / single plane). */
export interface BIMClipState {
  mode: 'none' | 'box' | 'plane';
  /** Box extent as normalised [0, 1] per face. */
  boxExtent?: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
    minZ: number;
    maxZ: number;
  };
  /** Single-plane state — axis (x/y/z), offset 0..1, and flipped half-space. */
  plane?: {
    axis: 'x' | 'y' | 'z';
    offset: number;
    flipped: boolean;
  };
}

export interface Viewpoint {
  id: string;
  name: string;
  cameraPos: [number, number, number];
  target: [number, number, number];
  /** Filter panel snapshot. */
  filterState?: SavedBIMFilterState;
  /** Section-box / clipping-plane snapshot. */
  clipState?: BIMClipState;
  /**
   * Optional base64-encoded PNG thumbnail captured from the renderer when the
   * view was saved. Used to render a 96×64 preview on the saved-view card.
   *
   * Size budget: roughly 30–60 KB per JPEG-quality PNG at 320×180; 100 views
   * × 60 KB ≈ 6 MB per model in localStorage. Browsers cap at ~5–10 MB per
   * origin, so callers should pass a *thumbnail* (320×180), not a full-res
   * screenshot. ``SceneManager.getScreenshot({ width, height })`` enforces
   * that bound.
   */
  screenshotDataUrl?: string;
  createdAt: string;
}

export interface AddViewpointResult {
  viewpoint: Viewpoint;
  quotaExceeded: boolean;
}

const storageKey = (modelId: string): string => `oe_bim_views_${modelId}`;

function randomId(): string {
  return uuid();
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

/**
 * Rename a stored viewpoint in place.  Empty / whitespace-only names are
 * rejected (we keep the previous label).  Returns true on success, false
 * if the viewpoint id wasn't found.
 */
export function renameViewpoint(
  modelId: string,
  viewpointId: string,
  newName: string,
): boolean {
  const trimmed = newName.trim().slice(0, 80);
  if (!trimmed) return false;
  const all = readAll(modelId);
  const idx = all.findIndex((v) => v.id === viewpointId);
  if (idx < 0) return false;
  const next = all.slice();
  next[idx] = { ...next[idx]!, name: trimmed };
  writeAll(modelId, next);
  return true;
}

/**
 * Attach (or replace) a screenshot thumbnail on an existing viewpoint.
 * Returns true on success, false if the id wasn't found. Callers should pass
 * a small-resolution PNG (320×180 recommended) to stay under the localStorage
 * quota — see ``SceneManager.getScreenshot({ width, height })``.
 */
export function setViewpointScreenshot(
  modelId: string,
  viewpointId: string,
  screenshotDataUrl: string | null,
): boolean {
  const all = readAll(modelId);
  const idx = all.findIndex((v) => v.id === viewpointId);
  if (idx < 0) return false;
  const next = all.slice();
  const current = next[idx]!;
  if (screenshotDataUrl) {
    next[idx] = { ...current, screenshotDataUrl };
  } else {
    // Strip the field entirely so the payload doesn't carry an empty string.
    const { screenshotDataUrl: _drop, ...rest } = current;
    next[idx] = rest as Viewpoint;
  }
  writeAll(modelId, next);
  return true;
}

/**
 * Restore a stored viewpoint by flying the camera into it (W6.6).
 *
 * Previously the consumer (`BIMRightPanelTabs.onApplyViewpoint`) snapped
 * the camera instantly via `SceneManager.setViewpoint`. This helper
 * delegates to `SceneManager.flyTo` so the restore is animated unless
 * the caller opts in to an instant snap via ``options.instant``.
 *
 * Filter + clip restoration are intentionally NOT touched here — those
 * are owned by the parent (it carries direct handles on the filter
 * panel + ClipManager). Callers can still hook the filter/clip apply
 * after the returned promise resolves.
 *
 * Returns the located viewpoint on success, or null when the id wasn't
 * found in storage. Rejects if the tween is cancelled by a newer one.
 */
export async function restoreView(
  modelId: string,
  viewpointId: string,
  sceneManager: SceneManager,
  options?: { instant?: boolean; durationMs?: number },
): Promise<Viewpoint | null> {
  const vp = getViewpoint(modelId, viewpointId);
  if (!vp) return null;
  const instant = options?.instant === true;
  if (instant) {
    sceneManager.setViewpoint(
      { x: vp.cameraPos[0], y: vp.cameraPos[1], z: vp.cameraPos[2] },
      { x: vp.target[0], y: vp.target[1], z: vp.target[2] },
    );
    return vp;
  }
  const duration = options?.durationMs ?? DEFAULT_RESTORE_DURATION_MS;
  await sceneManager.flyTo(
    {
      position: vp.cameraPos,
      target: vp.target,
    },
    duration,
  );
  return vp;
}

export const __test__ = {
  storageKey,
  MAX_VIEWS_PER_MODEL,
};
