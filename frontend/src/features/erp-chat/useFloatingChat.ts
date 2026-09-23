// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Floating chat widget store.
 *
 * Holds the open/closed state of the bottom-right floating chat panel and a
 * pointer to the active session (so the user can resume the most recent
 * conversation across route changes and even page reloads). Also tracks an
 * "unread" counter for the badge on the floating button — every time the
 * assistant produces a message while the panel is closed, the counter ticks
 * up; opening the panel resets it.
 *
 * Persists to localStorage so the user's last-used session is restored on
 * reload, matching how `useProjectContextStore` keeps the active project
 * sticky across navigations.
 *
 * The second half of this file is the DOCK: the panel sits on the
 * inline-end side of the screen and either PUSHES the page aside (wide
 * screens, the page reflows next to it) or floats OVER the page with a
 * backdrop (everything else). The geometry is pure functions so it can be
 * tested without a browser; the hooks below wire it to the window, the
 * sidebar width and the two variables the layout reads
 * (`--oe-ai-dock-offset` for the page, `--oe-ai-dock-widget-offset` for the
 * fixed widgets).
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type RefObject,
} from 'react';
import { create } from 'zustand';

const STORAGE_KEY = 'oe_floating_chat_v1';

// ── Dock constants ─────────────────────────────────────────────────────────

/** Width the dock opens at before the user resizes it, in CSS px. */
export const DOCK_DEFAULT_WIDTH = 440;
/** Narrowest the dock may get; below this the proposal cards stop fitting. */
export const DOCK_MIN_WIDTH = 360;
/** Widest the dock may get on any screen. */
export const DOCK_MAX_WIDTH = 720;
/** Push mode needs at least the `lg` breakpoint, where the sidebar docks too. */
export const DOCK_PUSH_MIN_VIEWPORT = 1024;
/** The page never gets narrower than this next to a pushing dock. */
export const DOCK_MIN_PAGE_WIDTH = 560;
/** Below this viewport width the dock covers the whole screen. */
export const DOCK_FULL_WIDTH_BELOW = 640;
/** One arrow-key press on the resize handle moves it this far. */
export const DOCK_KEYBOARD_STEP = 16;
/**
 * Duration of the slide in and out. It matches the page's padding
 * transition (index.css `.oe-ai-dock-shell`) so that in push mode the edge
 * of the dock and the edge of the page move together.
 */
export const DOCK_ANIMATION_MS = 250;
/** The dock width lives in its own key so session writes never clobber it. */
export const DOCK_WIDTH_STORAGE_KEY = 'oe_ai_dock_width_v1';
/** CSS variable on `:root` that the app shell pads itself by (push mode only). */
export const DOCK_OFFSET_VAR = '--oe-ai-dock-offset';
/**
 * CSS variable on `:root` that fixed widgets (`.oe-dock-aware`) step aside
 * by: the dock width while it is open in EITHER mode. In overlay mode the
 * page stays where it is, but the pills, prompts and toasts that paint above
 * the backdrop (z-60 and higher) would otherwise sit on the dock's composer
 * and header.
 */
export const DOCK_WIDGET_OFFSET_VAR = '--oe-ai-dock-widget-offset';
/** Attribute on `<html>`: `push` or `overlay` while the dock is open, absent otherwise. */
export const DOCK_MODE_ATTR = 'data-ai-dock';
/** Attribute on `<html>` while the resize handle is being dragged. */
export const DOCK_RESIZING_ATTR = 'data-ai-dock-resizing';
/** The stylesheet default of `--oe-sidebar-width` (index.css). */
const DEFAULT_SIDEBAR_WIDTH = 248;

export type DockMode = 'push' | 'overlay';

/**
 * Routes that host a chat of their own (or sit outside the app shell). The
 * floating button hides there and the dock stays closed there, so the full
 * page chat is never shown twice.
 */
export const FLOATING_CHAT_HIDDEN_PREFIXES = [
  '/chat', // full-page chat - don't duplicate
  '/login',
  '/onboarding',
  '/license-request',
];

export function isFloatingChatHiddenOn(pathname: string): boolean {
  return FLOATING_CHAT_HIDDEN_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

interface PersistedState {
  activeSessionId: string | null;
  lastReadAt: string; // ISO timestamp
}

interface FloatingChatState {
  isOpen: boolean;
  activeSessionId: string | null;
  lastReadAt: string;
  unreadCount: number;
  /**
   * Session-only flag: when the user clicks "Skip" on the "Configure AI"
   * onboarding banner we hide the banner for the rest of this browser
   * session. We intentionally DO NOT persist this to localStorage — the
   * onboarding nudge should reappear next visit so the user is reminded
   * they still need to configure their key.
   */
  onboardingBannerDismissed: boolean;
  /**
   * One-shot text to drop into the composer the next time the panel is open.
   * Set by `seedPrompt` (e.g. the BIM viewer's "Ask AI about this element"
   * action) and consumed once by the panel, which prefills the input and
   * clears it. Deliberately NOT persisted: it is a transient hand-off, not a
   * draft to survive reloads. We prefill rather than auto-send so the user
   * reviews and submits, matching the platform's human-confirmed AI stance.
   */
  pendingPrompt: string | null;
  /**
   * The dock width the user chose, in CSS px, clamped to
   * [DOCK_MIN_WIDTH, DOCK_MAX_WIDTH] and persisted under
   * DOCK_WIDTH_STORAGE_KEY. It is a preference: the width actually shown is
   * `useDockGeometry().width`, which also respects the screen.
   */
  width: number;
  /**
   * Set the preferred dock width. Clamped. Pass `{ persist: false }` while a
   * drag is still moving so storage is written once, on release.
   */
  setWidth: (width: number, options?: { persist?: boolean }) => void;
  /** Back to DOCK_DEFAULT_WIDTH (double-click on the resize handle). */
  resetWidth: () => void;
  open: () => void;
  close: () => void;
  toggle: () => void;
  setActiveSession: (id: string | null) => void;
  markRead: () => void;
  bumpUnread: () => void;
  dismissOnboardingBanner: () => void;
  resetOnboardingBanner: () => void;
  /** Open the panel and stage `prompt` to prefill the composer. */
  seedPrompt: (prompt: string) => void;
  /** Clear the staged prompt (called by the panel once it has consumed it). */
  clearPendingPrompt: () => void;
}

function readPersisted(): PersistedState {
  if (typeof window === 'undefined') {
    return { activeSessionId: null, lastReadAt: new Date(0).toISOString() };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { activeSessionId: null, lastReadAt: new Date(0).toISOString() };
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    return {
      activeSessionId:
        typeof parsed.activeSessionId === 'string' ? parsed.activeSessionId : null,
      lastReadAt:
        typeof parsed.lastReadAt === 'string' ? parsed.lastReadAt : new Date(0).toISOString(),
    };
  } catch {
    return { activeSessionId: null, lastReadAt: new Date(0).toISOString() };
  }
}

function writePersisted(state: PersistedState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Quota exceeded / privacy mode — non-fatal.
  }
}

/**
 * Clamp a dock width to whole pixels inside [DOCK_MIN_WIDTH, cap], where the
 * cap is `maxWidth` limited to DOCK_MAX_WIDTH. The minimum wins when the cap
 * is below it. Anything that is not a finite number becomes the default.
 */
export function clampDockWidth(width: unknown, maxWidth: number = DOCK_MAX_WIDTH): number {
  const n = typeof width === 'number' ? width : Number.NaN;
  const value = Number.isFinite(n) ? n : DOCK_DEFAULT_WIDTH;
  const cap = Math.max(DOCK_MIN_WIDTH, Math.min(DOCK_MAX_WIDTH, maxWidth));
  return Math.round(Math.min(Math.max(value, DOCK_MIN_WIDTH), cap));
}

/** The stored dock width, clamped, or the default when nothing usable is stored. */
export function readDockWidth(): number {
  try {
    const raw = localStorage.getItem(DOCK_WIDTH_STORAGE_KEY);
    if (raw === null) return DOCK_DEFAULT_WIDTH;
    const parsed = Number.parseFloat(raw);
    return clampDockWidth(Number.isFinite(parsed) ? parsed : Number.NaN);
  } catch {
    return DOCK_DEFAULT_WIDTH;
  }
}

function writeDockWidth(width: number): void {
  try {
    localStorage.setItem(DOCK_WIDTH_STORAGE_KEY, String(width));
  } catch {
    // Quota exceeded / privacy mode - the dock simply opens at the default.
  }
}

const initial = readPersisted();

export const useFloatingChatStore = create<FloatingChatState>((set, get) => ({
  isOpen: false,
  activeSessionId: initial.activeSessionId,
  lastReadAt: initial.lastReadAt,
  unreadCount: 0,
  onboardingBannerDismissed: false,
  pendingPrompt: null,
  width: typeof window === 'undefined' ? DOCK_DEFAULT_WIDTH : readDockWidth(),

  setWidth: (width: number, options?: { persist?: boolean }) => {
    const next = clampDockWidth(width);
    if (next !== get().width) set({ width: next });
    if (options?.persist !== false) writeDockWidth(next);
  },

  resetWidth: () => {
    set({ width: DOCK_DEFAULT_WIDTH });
    writeDockWidth(DOCK_DEFAULT_WIDTH);
  },

  open: () => {
    const now = new Date().toISOString();
    set({ isOpen: true, lastReadAt: now, unreadCount: 0 });
    writePersisted({ activeSessionId: get().activeSessionId, lastReadAt: now });
  },

  close: () => {
    set({ isOpen: false });
  },

  toggle: () => {
    const s = get();
    if (s.isOpen) {
      set({ isOpen: false });
    } else {
      const now = new Date().toISOString();
      set({ isOpen: true, lastReadAt: now, unreadCount: 0 });
      writePersisted({ activeSessionId: s.activeSessionId, lastReadAt: now });
    }
  },

  setActiveSession: (id: string | null) => {
    set({ activeSessionId: id });
    writePersisted({ activeSessionId: id, lastReadAt: get().lastReadAt });
  },

  markRead: () => {
    const now = new Date().toISOString();
    set({ lastReadAt: now, unreadCount: 0 });
    writePersisted({ activeSessionId: get().activeSessionId, lastReadAt: now });
  },

  bumpUnread: () => {
    // Only bump when the panel is actually closed — the caller is responsible
    // for the open check too, but defending here keeps the store honest.
    if (get().isOpen) return;
    set((s) => ({ unreadCount: s.unreadCount + 1 }));
  },

  dismissOnboardingBanner: () => {
    set({ onboardingBannerDismissed: true });
  },

  resetOnboardingBanner: () => {
    set({ onboardingBannerDismissed: false });
  },

  seedPrompt: (prompt: string) => {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    // Open the panel and stage the text; the panel consumes it on the next
    // render. Mirrors `open()` so the unread badge and read-marker stay
    // consistent whether the user opened the panel or the seed did.
    const now = new Date().toISOString();
    set({ pendingPrompt: trimmed, isOpen: true, lastReadAt: now, unreadCount: 0 });
    writePersisted({ activeSessionId: get().activeSessionId, lastReadAt: now });
  },

  clearPendingPrompt: () => {
    if (get().pendingPrompt !== null) set({ pendingPrompt: null });
  },
}));

/**
 * Small helper that returns `true` after the component has mounted on the
 * client. We use this to defer reading `window.matchMedia` until after
 * hydration / first paint — Vite SSR is not in play here, but it also keeps
 * the initial render deterministic and avoids re-render flashes.
 */
export function useIsMobileViewport(breakpointPx = 640): boolean {
  const subscribe = (callback: () => void): (() => void) => {
    if (typeof window === 'undefined') return () => {};
    const mq = window.matchMedia(`(max-width: ${breakpointPx - 1}px)`);
    mq.addEventListener('change', callback);
    return () => mq.removeEventListener('change', callback);
  };
  const getSnapshot = (): boolean => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(`(max-width: ${breakpointPx - 1}px)`).matches;
  };
  const getServerSnapshot = (): boolean => false;
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

/**
 * Returns `true` once the component has mounted on the client. Used to avoid
 * rendering portals (and the floating button itself) before the auth store
 * has hydrated from sessionStorage — without this the button briefly flashes
 * on /login on a hard reload.
 */
export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  return mounted;
}

// ── Dock geometry (pure) ───────────────────────────────────────────────────

export interface DockGeometry {
  /** `push`: the page reflows next to the dock. `overlay`: backdrop, modal. */
  mode: DockMode;
  /** The width actually shown, in CSS px: the preference, capped by the screen. */
  width: number;
  /** The widest the dock may be on this screen right now (resize handle max). */
  maxWidth: number;
  /** True below DOCK_FULL_WIDTH_BELOW: the dock covers the whole screen. */
  fullWidth: boolean;
}

/**
 * Push or overlay. Depends on the SCREEN only, never on the dock width the
 * user dragged to: push needs the `lg` breakpoint and enough room for the
 * page (DOCK_MIN_PAGE_WIDTH) next to the sidebar and the NARROWEST dock. In
 * push mode the dock gives up width instead of flipping (see dockMaxWidth),
 * so no drag and no arrow key can turn push into overlay under the cursor.
 * Text direction plays no part: RTL mirrors the sides, not the arithmetic.
 */
export function computeDockMode({
  viewportWidth,
  sidebarWidth,
}: {
  viewportWidth: number;
  sidebarWidth: number;
}): DockMode {
  if (viewportWidth < DOCK_PUSH_MIN_VIEWPORT) return 'overlay';
  return viewportWidth - sidebarWidth - DOCK_MIN_WIDTH >= DOCK_MIN_PAGE_WIDTH ? 'push' : 'overlay';
}

/**
 * The widest the dock may be: DOCK_MAX_WIDTH, at most half the screen, and in
 * push mode also no wider than what leaves the page DOCK_MIN_PAGE_WIDTH.
 * Never below DOCK_MIN_WIDTH.
 */
export function dockMaxWidth({
  viewportWidth,
  sidebarWidth,
  mode,
}: {
  viewportWidth: number;
  sidebarWidth: number;
  mode: DockMode;
}): number {
  let cap = Math.min(DOCK_MAX_WIDTH, Math.floor(viewportWidth / 2));
  if (mode === 'push') {
    cap = Math.min(cap, Math.floor(viewportWidth - sidebarWidth - DOCK_MIN_PAGE_WIDTH));
  }
  return Math.max(DOCK_MIN_WIDTH, cap);
}

export function resolveDockGeometry({
  viewportWidth,
  sidebarWidth,
  preferredWidth,
}: {
  viewportWidth: number;
  sidebarWidth: number;
  preferredWidth: number;
}): DockGeometry {
  const mode = computeDockMode({ viewportWidth, sidebarWidth });
  const maxWidth = dockMaxWidth({ viewportWidth, sidebarWidth, mode });
  return {
    mode,
    maxWidth,
    width: clampDockWidth(preferredWidth, maxWidth),
    fullWidth: viewportWidth < DOCK_FULL_WIDTH_BELOW,
  };
}

/**
 * The sidebar width as the sidebar itself last wrote it on the root element
 * (Sidebar.tsx sets `--oe-sidebar-width` inline on `:root`). Reads the inline
 * style, not `getComputedStyle`, so calling it on every render forces no
 * style recalculation. Falls back to the stylesheet default.
 */
export function readSidebarWidthPx(root?: HTMLElement): number {
  const el = root ?? (typeof document === 'undefined' ? null : document.documentElement);
  if (!el) return DEFAULT_SIDEBAR_WIDTH;
  const raw = el.style.getPropertyValue('--oe-sidebar-width').trim();
  const px = Number.parseFloat(raw);
  return Number.isFinite(px) && raw.endsWith('px') ? px : DEFAULT_SIDEBAR_WIDTH;
}

// ── Page offset writer ─────────────────────────────────────────────────────

export interface DockLayoutState {
  open: boolean;
  mode: DockMode;
  width: number;
  /** The dock covers the whole screen (below DOCK_FULL_WIDTH_BELOW). */
  fullWidth?: boolean;
}

/** What the page pads itself by: the dock width while open in push mode, else 0. */
export function dockOffsetFor({ open, mode, width }: DockLayoutState): string {
  return open && mode === 'push' ? `${Math.round(width)}px` : '0px';
}

/**
 * What fixed widgets step aside by: the dock width while it is open, in
 * either mode, else 0. Also 0 when the dock covers the whole screen, where
 * there is no side left to step to.
 */
export function dockWidgetOffsetFor({ open, width, fullWidth = false }: DockLayoutState): string {
  return open && !fullWidth ? `${Math.round(width)}px` : '0px';
}

/**
 * Tell the page about the dock, the same way Sidebar.tsx tells it about the
 * sidebar: CSS variables on `:root` (`--oe-ai-dock-offset`, read by
 * `.oe-ai-dock-shell`, and `--oe-ai-dock-widget-offset`, read by
 * `.oe-dock-aware`, both in index.css) plus
 * `html[data-ai-dock="push"|"overlay"]` while the dock is open.
 */
export function applyDockLayout(root: HTMLElement, state: DockLayoutState): void {
  root.style.setProperty(DOCK_OFFSET_VAR, dockOffsetFor(state));
  root.style.setProperty(DOCK_WIDGET_OFFSET_VAR, dockWidgetOffsetFor(state));
  if (state.open) root.setAttribute(DOCK_MODE_ATTR, state.mode);
  else root.removeAttribute(DOCK_MODE_ATTR);
}

/** Undo everything applyDockLayout wrote (the shell unmounts, e.g. on logout). */
export function clearDockLayout(root: HTMLElement): void {
  root.style.removeProperty(DOCK_OFFSET_VAR);
  root.style.removeProperty(DOCK_WIDGET_OFFSET_VAR);
  root.removeAttribute(DOCK_MODE_ATTR);
  root.removeAttribute(DOCK_RESIZING_ATTR);
}

// ── Resizing (pure) ────────────────────────────────────────────────────────

/**
 * Width while dragging the handle on the dock's inline-start edge. Moving
 * away from the dock widens it: to the left in LTR (dock on the right), to
 * the right in RTL (dock on the left).
 */
export function widthFromDrag({
  startWidth,
  startX,
  currentX,
  rtl,
  maxWidth,
}: {
  startWidth: number;
  startX: number;
  currentX: number;
  rtl: boolean;
  maxWidth: number;
}): number {
  const delta = (startX - currentX) * (rtl ? -1 : 1);
  return clampDockWidth(startWidth + delta, maxWidth);
}

/**
 * Width after a key press on the focused resize handle, or null when the key
 * is not a resize key. The arrow pointing at the page widens the dock, so
 * the arrows swap in RTL. Home and End jump to the narrowest and widest.
 */
export function widthFromKey(
  key: string,
  { width, maxWidth, rtl }: { width: number; maxWidth: number; rtl: boolean },
): number | null {
  const towardsPage = rtl ? 'ArrowRight' : 'ArrowLeft';
  const awayFromPage = rtl ? 'ArrowLeft' : 'ArrowRight';
  if (key === towardsPage) return clampDockWidth(width + DOCK_KEYBOARD_STEP, maxWidth);
  if (key === awayFromPage) return clampDockWidth(width - DOCK_KEYBOARD_STEP, maxWidth);
  if (key === 'Home') return DOCK_MIN_WIDTH;
  if (key === 'End') return clampDockWidth(maxWidth, maxWidth);
  return null;
}

// ── Shortcut (Alt+A) ───────────────────────────────────────────────────────

/**
 * The keys shown for the shortcut (FAB title, `aria-keyshortcuts`). The
 * shortcuts dialog (shared/ui/ShortcutsDialog.tsx) lists the same pair.
 */
export const DOCK_SHORTCUT_KEYS = ['Alt', 'A'] as const;
export const DOCK_SHORTCUT_ARIA = 'Alt+A';

/** The parts of a keyboard event the shortcut decision reads. */
export interface DockShortcutKey {
  key?: string;
  code?: string;
  altKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  repeat?: boolean;
  isComposing?: boolean;
  getModifierState?: (keyArg: string) => boolean;
}

/**
 * Alt+A (Option+A on a Mac) toggles the dock. Free across the app: the BOQ
 * editor binds Alt+I and Ctrl+/, the launchers bind Ctrl+K and Ctrl+Shift+K,
 * and the single-key navigation ignores every event with a modifier.
 *
 * Plain Alt only. Windows reports AltGr as Ctrl+Alt, and AltGr+A types a
 * letter on several layouts (Polish `ą`), so Ctrl, Cmd and AltGraph all
 * disqualify. On a Mac, Option+A types a character (`å`) too, so inside a
 * text field it is left to the field. Matched on the letter AND the physical
 * key, like the BOQ shortcuts, so layouts that move the letter still reach it.
 */
export function isDockShortcut(
  e: DockShortcutKey,
  { applePlatform, typingInField }: { applePlatform: boolean; typingInField: boolean },
): boolean {
  if (e.altKey !== true) return false;
  if (e.ctrlKey === true || e.metaKey === true || e.shiftKey === true) return false;
  if (e.repeat === true || e.isComposing === true) return false;
  if (typeof e.getModifierState === 'function' && e.getModifierState('AltGraph') === true) {
    return false;
  }
  if (applePlatform && typingInField) return false;
  return (e.key ?? '').toLowerCase() === 'a' || e.code === 'KeyA';
}

export function isApplePlatform(): boolean {
  if (typeof navigator === 'undefined') return false;
  const uaData = (navigator as Navigator & { userAgentData?: { platform?: string } })
    .userAgentData;
  const platform = uaData?.platform || navigator.platform || '';
  return /mac|iphone|ipad|ipod/i.test(platform);
}

/** True when `el` takes typed text. */
export function isEditableElement(el: Element | null | undefined): boolean {
  if (!el) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  return (el as HTMLElement).isContentEditable === true;
}

/**
 * True when a modal other than the dock is open (shortcuts help, a confirm
 * dialog, a wide modal). The shortcut then does nothing, so it never pulls
 * focus out from under a dialog that sits above the dock.
 */
export function isAnotherModalOpen(dock: Element | null): boolean {
  if (typeof document === 'undefined') return false;
  const modals = Array.from(document.querySelectorAll<HTMLElement>('[aria-modal="true"]'));
  return modals.some((m) => {
    if (dock && (m === dock || dock.contains(m))) return false;
    if (m.hidden || m.closest('[aria-hidden="true"]') !== null) return false;
    // A dialog kept mounted but hidden by CSS must not disable the shortcut
    // for good. `checkVisibility` answers that where the engine has it.
    const el = m as HTMLElement & { checkVisibility?: () => boolean };
    return typeof el.checkVisibility === 'function' ? el.checkVisibility() : true;
  });
}

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

// ── Dock hooks ─────────────────────────────────────────────────────────────

interface DockEnvironment {
  mode: DockMode;
  maxWidth: number;
  fullWidth: boolean;
}

const SERVER_DOCK_ENVIRONMENT: DockEnvironment = {
  mode: 'overlay',
  maxWidth: DOCK_MAX_WIDTH,
  fullWidth: false,
};
let dockEnvironmentCache: DockEnvironment = SERVER_DOCK_ENVIRONMENT;

/**
 * Snapshot for useSyncExternalStore. Returns the SAME object until one of the
 * three derived values changes, so the panel re-renders when the mode or the
 * cap moves, not on every pixel of a window resize.
 */
function readDockEnvironment(): DockEnvironment {
  if (typeof window === 'undefined') return SERVER_DOCK_ENVIRONMENT;
  const viewportWidth = window.innerWidth;
  const sidebarWidth = readSidebarWidthPx();
  const mode = computeDockMode({ viewportWidth, sidebarWidth });
  const maxWidth = dockMaxWidth({ viewportWidth, sidebarWidth, mode });
  const fullWidth = viewportWidth < DOCK_FULL_WIDTH_BELOW;
  const cached = dockEnvironmentCache;
  if (cached.mode === mode && cached.maxWidth === maxWidth && cached.fullWidth === fullWidth) {
    return cached;
  }
  dockEnvironmentCache = { mode, maxWidth, fullWidth };
  return dockEnvironmentCache;
}

/**
 * Module-level on purpose: a subscribe function created per render would make
 * React resubscribe on every render, and the panel renders on every streamed
 * chunk. Listens to window resizes and to style writes on `<html>`, which is
 * where the sidebar publishes its width when it is collapsed to icons.
 */
function subscribeDockEnvironment(onChange: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  window.addEventListener('resize', onChange);
  let observer: MutationObserver | null = null;
  if (typeof MutationObserver !== 'undefined') {
    observer = new MutationObserver(onChange);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['style'] });
  }
  return () => {
    window.removeEventListener('resize', onChange);
    observer?.disconnect();
  };
}

function getServerDockEnvironment(): DockEnvironment {
  return SERVER_DOCK_ENVIRONMENT;
}

/**
 * Mode and width of the dock for the current screen and sidebar, for the
 * stored width preference (or for `preferredWidth` when given). Re-renders
 * the caller when the mode, the cap or the full-width flag changes.
 */
export function useDockGeometry(preferredWidth?: number): DockGeometry {
  const storedWidth = useFloatingChatStore((s) => s.width);
  const env = useSyncExternalStore(
    subscribeDockEnvironment,
    readDockEnvironment,
    getServerDockEnvironment,
  );
  const preferred = preferredWidth ?? storedWidth;
  return useMemo(
    () => ({
      mode: env.mode,
      maxWidth: env.maxWidth,
      fullWidth: env.fullWidth,
      width: clampDockWidth(preferred, env.maxWidth),
    }),
    [env, preferred],
  );
}

/**
 * Keep the two offsets and `html[data-ai-dock]` in step with the dock, and
 * clear them when the owner unmounts (the shell goes away on logout, and a
 * stale offset would pad whatever renders next).
 */
export function useDockLayoutSync({ open, mode, width, fullWidth = false }: DockLayoutState): void {
  useEffect(() => {
    applyDockLayout(document.documentElement, { open, mode, width, fullWidth });
  }, [open, mode, width, fullWidth]);
  useEffect(() => () => clearDockLayout(document.documentElement), []);
}

/**
 * Keeps the dock mounted while it animates out. `rendered` is true while open
 * and during the exit; `closing` is true only during the exit. The exit ends
 * on the dock's own `animationend` (call `finishExit`) or, as a fallback for
 * environments that never fire it, after the animation time plus a margin.
 * With reduced motion there is no exit phase at all.
 *
 * The closing flag is derived during render (not in an effect) so there is
 * no frame in which the dock disappears and then reappears to animate out.
 */
export function useDockPresence(open: boolean): {
  rendered: boolean;
  closing: boolean;
  finishExit: () => void;
} {
  const [prevOpen, setPrevOpen] = useState(open);
  const [closing, setClosing] = useState(false);
  if (open !== prevOpen) {
    setPrevOpen(open);
    setClosing(!open && !prefersReducedMotion());
  }
  useEffect(() => {
    if (!closing) return;
    const id = window.setTimeout(() => setClosing(false), DOCK_ANIMATION_MS + 120);
    return () => window.clearTimeout(id);
  }, [closing]);
  const finishExit = useCallback(() => setClosing(false), []);
  return { rendered: open || closing, closing: !open && closing, finishExit };
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function focusableIn(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) =>
      !el.hasAttribute('disabled') &&
      el.getAttribute('aria-hidden') !== 'true' &&
      (el.offsetParent !== null || el === document.activeElement),
  );
}

/**
 * Focus rules for the dock.
 *
 * - Push mode is NOT modal: Tab moves freely between the page and the dock.
 * - Overlay mode is modal: Tab wraps inside the dock, and focus is pulled in
 *   when the dock becomes modal (open in overlay, or the window shrinks).
 *   A dialog opened over the dock (any other `aria-modal="true"`, such as a
 *   confirm from a proposal card) keeps Tab to itself.
 * - On close, focus goes back to where it was before it entered the dock
 *   (the button that opened it, or the page spot Alt+A jumped from), but
 *   only when focus is still inside the dock. A user who clicked back into
 *   the page keeps their place.
 *
 * This replaces `useFocusTrap` for the dock because that hook restores focus
 * whenever it deactivates, which would yank focus out of the composer the
 * moment a window resize turns overlay into push.
 */
export function useDockFocus(
  containerRef: RefObject<HTMLElement>,
  { open, modal }: { open: boolean; modal: boolean },
): void {
  const focusInsideRef = useRef(false);
  // Where the user was before focus went into the dock: the element to hand
  // focus back to on close. Tracked continuously rather than read once at
  // open, because (a) the round button hides the moment the dock opens and a
  // browser may already have moved focus off it to <body>, and (b) in push
  // mode the user may work in the page and jump back in with Alt+A, and then
  // "back" means the page spot they jumped from, not the original opener.
  const returnToRef = useRef<HTMLElement | null>(null);

  // `focusin` fires for every focus change that lands on an element. Focus
  // falling back to <body> fires none; restoring on close is harmless then.
  useEffect(() => {
    const onFocusIn = (e: FocusEvent) => {
      const container = containerRef.current;
      const target = e.target;
      const inside = !!container && target instanceof Node && container.contains(target);
      focusInsideRef.current = inside;
      // A dialog layered over the dock (the confirm a card inside it opens,
      // portalled to <body>) is not where the user came from: it hands focus
      // back into the dock when it closes, and would leave a detached
      // element behind as the place to return to.
      if (!inside && target instanceof HTMLElement && !target.closest('[aria-modal="true"]')) {
        returnToRef.current = target;
      }
    };
    document.addEventListener('focusin', onFocusIn);
    return () => document.removeEventListener('focusin', onFocusIn);
  }, [containerRef]);

  useEffect(() => {
    if (!open) return;
    const active = document.activeElement;
    if (
      active instanceof HTMLElement &&
      active !== document.body &&
      !containerRef.current?.contains(active)
    ) {
      returnToRef.current = active;
    }
    return () => {
      if (!focusInsideRef.current) return;
      focusInsideRef.current = false;
      const target = returnToRef.current;
      if (target && target.isConnected && !containerRef.current?.contains(target)) {
        try {
          target.focus({ preventScroll: true });
        } catch {
          // Detached SVG and friends throw on focus(); fall through to blur.
        }
        if (document.activeElement === target) return;
      }
      const current = document.activeElement;
      if (current instanceof HTMLElement && containerRef.current?.contains(current)) {
        current.blur();
      }
    };
  }, [open, containerRef]);

  useEffect(() => {
    if (!open || !modal) return;
    const container = containerRef.current;
    if (!container) return;
    if (!container.contains(document.activeElement) && !isAnotherModalOpen(container)) {
      container.focus({ preventScroll: true });
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      // A dialog opened over the dock (a confirm from a card inside it) runs
      // its own focus trap. This listener fires first (capture phase), so
      // without this line Tab in that dialog would land back in the dock.
      if (isAnotherModalOpen(container)) return;
      const focusable = focusableIn(container);
      if (focusable.length === 0) {
        e.preventDefault();
        container.focus();
        return;
      }
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      const current = document.activeElement as HTMLElement | null;
      if (e.shiftKey) {
        if (current === first || !container.contains(current)) {
          e.preventDefault();
          last.focus();
        }
      } else if (current === last || !container.contains(current)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown, true);
    return () => document.removeEventListener('keydown', onKeyDown, true);
  }, [open, modal, containerRef]);
}
