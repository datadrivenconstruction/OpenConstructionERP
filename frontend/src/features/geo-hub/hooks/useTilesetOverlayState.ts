// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Per-project visibility + opacity state for 3D tilesets in /geo-hub.
 *
 * Stored under ``localStorage[geoHub.overlayState.<projectId>]`` with the
 * shape ``Record<tilesetId, { visible: boolean; opacity: number }>``.
 * Entries are sparse — only tilesets the user has touched have a record;
 * untouched tilesets render with the implicit default ``{ visible: true,
 * opacity: 1 }`` (see ``getTilesetEntry``).
 *
 * Persistence is best-effort — a disabled / full localStorage never breaks
 * the UX, the state just doesn't survive reloads.
 *
 * Distinct from the raster-overlay panel state which lives on the backend
 * (``GeoRasterOverlay.visible`` + ``.opacity`` columns). 3D tilesets are
 * heavier (potentially several hundred MB) and re-uploading is expensive,
 * so the show/hide + dimming preference is a personal view setting kept
 * client-side rather than a project-scoped DB column.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

/** Per-tileset overlay knobs. */
export interface TilesetOverlayEntry {
  /** Whether the tileset should render. Defaults to ``true``. */
  visible: boolean;
  /** Opacity in [0, 1]. Defaults to ``1``. */
  opacity: number;
}

/** Sparse map keyed by Tileset.id. */
export type TilesetOverlayState = Record<string, TilesetOverlayEntry>;

const STORAGE_PREFIX = 'geoHub.overlayState.';
const DEFAULT_ENTRY: Readonly<TilesetOverlayEntry> = Object.freeze({
  visible: true,
  opacity: 1,
});

function storageKey(projectId: string): string {
  return `${STORAGE_PREFIX}${projectId}`;
}

function clampOpacity(v: unknown): number {
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n)) return 1;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

function readState(projectId: string | null | undefined): TilesetOverlayState {
  if (!projectId) return {};
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(storageKey(projectId));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return {};
    const out: TilesetOverlayState = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (!v || typeof v !== 'object') continue;
      const obj = v as Record<string, unknown>;
      out[k] = {
        visible: obj.visible !== false, // default true
        opacity: clampOpacity(obj.opacity),
      };
    }
    return out;
  } catch {
    // Corrupt JSON, localStorage disabled / quota — fall back to empty.
    return {};
  }
}

function writeState(
  projectId: string | null | undefined,
  state: TilesetOverlayState,
): void {
  if (!projectId) return;
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(storageKey(projectId), JSON.stringify(state));
  } catch {
    /* localStorage disabled / quota full — UX still works in-memory */
  }
}

/**
 * Resolve the effective entry for one tileset id, applying defaults for
 * any keys missing from the persisted state.
 */
export function getTilesetEntry(
  state: TilesetOverlayState,
  tilesetId: string,
): TilesetOverlayEntry {
  return state[tilesetId] ?? DEFAULT_ENTRY;
}

export interface UseTilesetOverlayStateResult {
  /** Current sparse state. Defaults are NOT pre-filled. */
  state: TilesetOverlayState;
  /** True iff ``state[id]`` exists OR the implicit default says hidden. */
  isVisible: (tilesetId: string) => boolean;
  /** Effective opacity in [0, 1] for a tileset id. */
  getOpacity: (tilesetId: string) => number;
  /** Flip the ``visible`` flag (defaulting from ``true`` if absent). */
  toggleVisible: (tilesetId: string) => void;
  /** Set the ``visible`` flag explicitly. */
  setVisible: (tilesetId: string, visible: boolean) => void;
  /** Clamp + set opacity. */
  setOpacity: (tilesetId: string, opacity: number) => void;
  /** Reset one tileset to defaults (removes the entry from storage). */
  reset: (tilesetId: string) => void;
}

/**
 * Hook bundle for the per-project tileset overlay state.
 *
 * Stable callback identities so consumers passing them into
 * memoised children (TilesetSidebar / CesiumViewer) don't re-render
 * every parent update.
 */
export function useTilesetOverlayState(
  projectId: string | null | undefined,
): UseTilesetOverlayStateResult {
  const [state, setState] = useState<TilesetOverlayState>(() =>
    readState(projectId),
  );

  // Re-read whenever the project id changes — important when the same
  // hook instance is reused across SPA navigation (rare but possible) so
  // the wrong project's prefs never leak into the new view.
  const lastProjectIdRef = useRef(projectId);
  useEffect(() => {
    if (lastProjectIdRef.current === projectId) return;
    lastProjectIdRef.current = projectId;
    setState(readState(projectId));
  }, [projectId]);

  const persist = useCallback(
    (updater: (prev: TilesetOverlayState) => TilesetOverlayState) => {
      setState((prev) => {
        const next = updater(prev);
        writeState(projectId, next);
        return next;
      });
    },
    [projectId],
  );

  const toggleVisible = useCallback(
    (tilesetId: string) => {
      persist((prev) => {
        const cur = prev[tilesetId] ?? DEFAULT_ENTRY;
        return {
          ...prev,
          [tilesetId]: { ...cur, visible: !cur.visible },
        };
      });
    },
    [persist],
  );

  const setVisible = useCallback(
    (tilesetId: string, visible: boolean) => {
      persist((prev) => {
        const cur = prev[tilesetId] ?? DEFAULT_ENTRY;
        return {
          ...prev,
          [tilesetId]: { ...cur, visible },
        };
      });
    },
    [persist],
  );

  const setOpacity = useCallback(
    (tilesetId: string, opacity: number) => {
      const clamped = clampOpacity(opacity);
      persist((prev) => {
        const cur = prev[tilesetId] ?? DEFAULT_ENTRY;
        return {
          ...prev,
          [tilesetId]: { ...cur, opacity: clamped },
        };
      });
    },
    [persist],
  );

  const reset = useCallback(
    (tilesetId: string) => {
      persist((prev) => {
        if (!(tilesetId in prev)) return prev;
        const { [tilesetId]: _drop, ...rest } = prev;
        return rest;
      });
    },
    [persist],
  );

  const isVisible = useCallback(
    (tilesetId: string) =>
      (state[tilesetId] ?? DEFAULT_ENTRY).visible,
    [state],
  );

  const getOpacity = useCallback(
    (tilesetId: string) => (state[tilesetId] ?? DEFAULT_ENTRY).opacity,
    [state],
  );

  return useMemo(
    () => ({
      state,
      isVisible,
      getOpacity,
      toggleVisible,
      setVisible,
      setOpacity,
      reset,
    }),
    [state, isVisible, getOpacity, toggleVisible, setVisible, setOpacity, reset],
  );
}
