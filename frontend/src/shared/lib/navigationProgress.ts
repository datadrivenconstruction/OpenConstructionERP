// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * navigationProgress — visible feedback for slow route transitions.
 *
 * Why this exists: React Router commits a navigation inside a transition. That
 * was the opt-in `v7_startTransition` flag on v6 and is plain behaviour on v7,
 * so grep will no longer find the flag anywhere and the reason below still
 * holds. Under a transition React keeps the OLD page on screen while a
 * lazy route chunk downloads/compiles, so a click on the sidebar produced
 * zero visual change for 1-3 seconds (founder report 2026-06-06) — no
 * Suspense fallback, no active-state flip, nothing. The user cannot tell
 * the click registered.
 *
 * The reliable pending signal: React Router updates `window.history`
 * SYNCHRONOUSLY on navigate, then commits the React location state inside
 * `startTransition`. So between `pushState` and the `useLocation()` commit
 * the app is provably "navigating". We bridge that window:
 *
 *   pushState/replaceState/popstate  →  markPending(target)
 *   useLocation() commit             →  clearPending()
 *
 * History patching is the standard integration point for this (nprogress,
 * Sentry and analytics SDKs use the same hook); it catches EVERY navigation
 * source — sidebar NavLinks, breadcrumbs, command palette, programmatic
 * `navigate()` — with no per-callsite wiring and no click sniffing (which
 * cannot distinguish a Link's own preventDefault from a swallowed click).
 *
 * Consumers of the pending state:
 *   - GlobalProgress top bar (starts after a 150 ms grace so instant
 *     navigations never flash it)
 *   - Sidebar row spinner on the exact item being navigated to
 *   - `html.oe-nav-pending` class → `cursor: progress` (index.css)
 */
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { create } from 'zustand';
import { useProgressStore } from '@/shared/ui/GlobalProgress';

interface NavPendingStore {
  /** pathname+search of the navigation target, null when idle */
  pendingPath: string | null;
  markPending: (path: string) => void;
  clearPending: () => void;
}

/** Failsafe: a chunk fetch that dies without a location commit must not
 *  leave the UI in "loading" forever. vite:preloadError (main.tsx) reloads
 *  the tab for the stale-chunk case; this covers everything else. */
const PENDING_FAILSAFE_MS = 15_000;
let failsafeTimer: ReturnType<typeof setTimeout> | null = null;

export const useNavPendingStore = create<NavPendingStore>((set, get) => ({
  pendingPath: null,

  markPending: (path: string) => {
    if (failsafeTimer) clearTimeout(failsafeTimer);
    failsafeTimer = setTimeout(() => get().clearPending(), PENDING_FAILSAFE_MS);
    document.documentElement.classList.add('oe-nav-pending');
    useProgressStore.getState().start();
    set({ pendingPath: path });
  },

  clearPending: () => {
    if (failsafeTimer) {
      clearTimeout(failsafeTimer);
      failsafeTimer = null;
    }
    if (get().pendingPath === null) return;
    document.documentElement.classList.remove('oe-nav-pending');
    useProgressStore.getState().done();
    set({ pendingPath: null });
  },
}));

/** The committed (React-rendered) location, mirrored by NavigationProgress
 *  so the history listener can tell real navigations from same-URL pushes. */
let committedKey = `${window.location.pathname}${window.location.search}`;

function onHistoryChange() {
  // Only ROUTER navigations open the pending window. React Router stamps
  // history.state with { key, idx } on every push/replace/pop; pages that
  // sync UI state straight into the URL via raw history.replaceState
  // (BIM camera params, file-manager path, …) never produce a React
  // location commit, so treating them as pending would strand the
  // spinner until the failsafe. Skip anything without the router stamp.
  const state = window.history.state as { key?: unknown; idx?: unknown } | null;
  if (!state || typeof state !== 'object' || !('key' in state) || !('idx' in state)) return;
  const target = `${window.location.pathname}${window.location.search}`;
  if (target === committedKey) return; // hash-only / same-URL push — instant
  useNavPendingStore.getState().markPending(target);
}

let patched = false;

/** Patch pushState/replaceState once so SPA navigations emit an event.
 *  popstate (back/forward) is a native event already. Idempotent. */
function ensureHistoryPatched() {
  if (patched) return;
  patched = true;
  for (const method of ['pushState', 'replaceState'] as const) {
    const original = window.history[method].bind(window.history);
    window.history[method] = ((...args: Parameters<History['pushState']>) => {
      original(...args);
      onHistoryChange();
    }) as History['pushState'];
  }
  window.addEventListener('popstate', onHistoryChange);
}

/**
 * Mount once inside the Router (App.tsx). Renders nothing; binds the
 * "location committed" side of the pending window.
 */
export function NavigationProgress() {
  const location = useLocation();

  useEffect(() => {
    ensureHistoryPatched();
  }, []);

  useEffect(() => {
    committedKey = `${location.pathname}${location.search}`;
    useNavPendingStore.getState().clearPending();
  }, [location.pathname, location.search]);

  return null;
}
