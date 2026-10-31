// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * useInfoBlockPrefsStore — per-user collapse state for module info cards.
 *
 * Every module page carries a `DismissibleInfo` card ("what this page is for
 * and how it connects"). A user can collapse it into a small button next to
 * "How it works" so it stops taking room, and re-open it when needed. This
 * store remembers, per storageKey, whether the user collapsed the card
 * (`true`) or explicitly kept it open (`false`). Unknown keys default to
 * expanded.
 *
 * Persistence strategy (mirrors useDashboardLayoutStore, 2026-07-23):
 *   1. localStorage (`oce.info-blocks`) — written eagerly via zustand
 *      `persist` for an instant, offline, no-flash first paint.
 *   2. Server (`/api/v1/users/me/info-blocks/`) — fetched once on app boot
 *      via `hydrateInfoBlocksFromServer()`; subsequent toggles are debounced
 *      400 ms and PUT back so the preference follows the user across browsers
 *      and devices, not just one localStorage bucket. This is the "пожелание
 *      пользователя сохранено" the founder asked for.
 *
 * On boot the server value wins when it holds any entries; otherwise the local
 * state is kept (and pushed up) so a user who customised one browser before
 * this feature shipped doesn't lose it. Network failures degrade silently.
 *
 * Backward compatibility: earlier builds stored each card under a per-browser
 * `oce.intro.<storageKey>` localStorage key. `DismissibleInfo` still reads that
 * legacy key as a one-time fallback for cards this store has not seen yet, so
 * existing collapse preferences carry over seamlessly.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { apiGet, apiPut } from '@/shared/lib/api';
import { isDemoReadOnly } from '@/stores/useDemoReadOnlyStore';

interface InfoBlockPrefsState {
  /** storageKey -> collapsed. Only keys the user has toggled appear here. */
  blocks: Record<string, boolean>;
  /** True once the server-side state has been fetched (or failed) at boot. */
  hydrated: boolean;

  /** Set (or clear) a card's collapsed preference. Optimistic + synced. */
  setCollapsed: (storageKey: string, collapsed: boolean) => void;

  /** Internal: replace the map from the server without re-PUTting it. */
  _setFromServer: (blocks: Record<string, boolean>) => void;
}

interface ServerInfoBlocksPayload {
  blocks: Record<string, boolean>;
}

const ENDPOINT = '/v1/users/me/info-blocks/';

/**
 * Suppression flag so server-driven hydration doesn't immediately fire a PUT
 * back. Flipped ON before `_setFromServer` and OFF on the next microtask, so
 * the debounced syncer (registered via `subscribe` below) skips that write.
 */
let suppressSync = false;

export const useInfoBlockPrefsStore = create<InfoBlockPrefsState>()(
  persist(
    (set) => ({
      blocks: {},
      hydrated: false,

      setCollapsed: (storageKey, collapsed) =>
        set((s) => {
          if (s.blocks[storageKey] === collapsed) return s;
          return { blocks: { ...s.blocks, [storageKey]: collapsed } };
        }),

      _setFromServer: (blocks) => {
        suppressSync = true;
        set({ blocks, hydrated: true });
        queueMicrotask(() => {
          suppressSync = false;
        });
      },
    }),
    {
      name: 'oce.info-blocks',
      // `hydrated` is runtime-only; never persist it to localStorage.
      partialize: (state) => ({ blocks: state.blocks }),
    },
  ),
);

/* ── Legacy per-card fallback ──────────────────────────────────────────────
   Cards this store has never seen fall back to the old `oce.intro.<key>`
   localStorage flag so previously-collapsed cards stay collapsed after the
   upgrade. "1" (collapsed) and the legacy "2" (old dismissed) both resolve to
   collapsed; anything else is expanded. */
export function readLegacyCollapsed(storageKey: string): boolean {
  try {
    const raw = localStorage.getItem(`oce.intro.${storageKey}`);
    return raw === '1' || raw === '2';
  } catch {
    return false;
  }
}

/* ── Server hydration + debounced write-through ────────────────────────────── */

let hydrationStarted = false;
let pendingTimer: ReturnType<typeof setTimeout> | null = null;
let lastSentPayload = '';

async function syncToServer(blocks: Record<string, boolean>): Promise<void> {
  const serialised = JSON.stringify(blocks);
  if (serialised === lastSentPayload) return;
  // The read-only demo refuses profile writes; localStorage keeps the change.
  if (isDemoReadOnly()) return;
  try {
    await apiPut<ServerInfoBlocksPayload, ServerInfoBlocksPayload>(ENDPOINT, { blocks });
    lastSentPayload = serialised;
  } catch {
    // Network failures degrade silently; localStorage already has the change.
  }
}

useInfoBlockPrefsStore.subscribe((state, prev) => {
  if (suppressSync) return;
  if (state.blocks === prev.blocks) return;
  if (pendingTimer) clearTimeout(pendingTimer);
  pendingTimer = setTimeout(() => {
    pendingTimer = null;
    void syncToServer(useInfoBlockPrefsStore.getState().blocks);
  }, 400);
});

/**
 * Pull the server-side collapse state once at app boot.
 *
 *   - Server has entries  -> it overwrites local (server wins, so the
 *     preference follows the user across browsers).
 *   - Server is empty but the user has a local map -> keep it AND push it up
 *     so the user's other devices inherit it.
 *   - 401 / offline        -> keep the localStorage state, mark hydrated.
 *
 * Idempotent: only the first call actually fires.
 */
export async function hydrateInfoBlocksFromServer(): Promise<void> {
  if (hydrationStarted) return;
  hydrationStarted = true;

  try {
    const remote = await apiGet<ServerInfoBlocksPayload>(ENDPOINT);
    const remoteBlocks = remote?.blocks ?? {};
    if (Object.keys(remoteBlocks).length > 0) {
      useInfoBlockPrefsStore.getState()._setFromServer(remoteBlocks);
      lastSentPayload = JSON.stringify(remoteBlocks);
      return;
    }
    // Server empty: keep the local map and push it up so future devices match.
    const local = useInfoBlockPrefsStore.getState().blocks;
    if (Object.keys(local).length > 0) {
      void syncToServer(local);
    }
    useInfoBlockPrefsStore.setState({ hydrated: true });
  } catch {
    useInfoBlockPrefsStore.setState({ hydrated: true });
  }
}
