// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Keyboard shortcuts for palette actions.
 *
 * Two shapes:
 *  - a chord with a modifier, `Mod+Shift+E` (Mod is Ctrl, or Cmd on macOS);
 *  - a two-key sequence without modifiers, `G B` (press G, then B), which is
 *    what the defaults use: sequences never collide with the browser, the OS
 *    or AltGr layouts, and they are ignored while typing in a field.
 *
 * Chords the browser or OS keeps for itself are refused, as are the app's own
 * launcher keys. The user's bindings are a per-browser preference.
 */
import { create } from 'zustand';

export const SHORTCUTS_STORAGE_KEY = 'oe_action_shortcuts_v1';
/** Time allowed between the two keys of a sequence. */
export const SEQUENCE_TIMEOUT_MS = 1200;

const MODIFIERS = ['Mod', 'Alt', 'Shift'] as const;

export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || '');
}

function normKey(key: string): string {
  if (key.length === 1) return key.toUpperCase();
  const k = key.trim();
  const named: Record<string, string> = { esc: 'Escape', del: 'Delete', ' ': 'Space', space: 'Space' };
  return named[k.toLowerCase()] ?? k.charAt(0).toUpperCase() + k.slice(1);
}

/** Canonical text of a binding: `Mod+Shift+E`, `G B`, or '' when unreadable. */
export function normalizeShortcut(raw: string): string {
  const text = raw.trim();
  if (!text) return '';
  if (!text.includes('+') && text.includes(' ')) {
    const keys = text.split(/\s+/).map(normKey);
    return keys.length === 2 && keys.every((k) => /^[A-Z0-9]$/.test(k)) ? keys.join(' ') : '';
  }
  const parts = text.split('+').map((p) => p.trim()).filter(Boolean);
  if (parts.length === 0) return '';
  const key = normKey(parts[parts.length - 1]!);
  const mods = new Set<string>();
  for (const p of parts.slice(0, -1)) {
    const m = p.toLowerCase();
    if (m === 'mod' || m === 'ctrl' || m === 'control' || m === 'cmd' || m === 'meta') mods.add('Mod');
    else if (m === 'alt' || m === 'option') mods.add('Alt');
    else if (m === 'shift') mods.add('Shift');
    else return '';
  }
  return [...MODIFIERS.filter((m) => mods.has(m)), key].join('+');
}

/**
 * Chords the browser or the OS owns (tabs, windows, reload, address bar,
 * find, print, save, zoom, history, devtools, clipboard and undo, layout
 * switching) plus the app's own launchers (Mod+K palette, Mod+Shift+K search).
 */
const RESERVED = new Set(
  [
    ...'TWNQRLPSFGHJDOUEKACVXZYB0123456789'.split('').map((k) => `Mod+${k}`),
    'Mod+Tab', 'Mod+Shift+Tab', 'Mod+=', 'Mod+-', 'Mod+Plus', 'Mod+Minus', 'Mod+Enter', 'Mod+,', 'Mod+.',
    ...'TNWIJCRQBPKDOAGHMS'.split('').map((k) => `Mod+Shift+${k}`),
    'Mod+Shift+Delete', 'Mod+Alt+Delete', 'Mod+Alt+I', 'Mod+Alt+J',
    'Alt+F4', 'Alt+Tab', 'Alt+Shift', 'Alt+Space', 'Alt+ArrowLeft', 'Alt+ArrowRight', 'Alt+Home', 'Alt+D', 'Alt+F', 'Alt+E',
    'F1', 'F3', 'F5', 'F6', 'F7', 'F10', 'F11', 'F12', 'Shift+F10', 'Mod+F5', 'Shift+F5',
  ].map(normalizeShortcut),
);

export type ShortcutProblem = 'invalid' | 'reserved' | 'needs_modifier' | 'conflict';

/**
 * Why a binding cannot be used, or null when it can.
 * `taken` maps each binding in use to the action that holds it.
 */
export function checkShortcut(
  raw: string,
  actionId: string,
  taken: ReadonlyMap<string, string>,
): { problem: ShortcutProblem; holder?: string } | null {
  const sc = normalizeShortcut(raw);
  if (!sc) return { problem: 'invalid' };
  if (RESERVED.has(sc)) return { problem: 'reserved' };
  const isSequence = sc.includes(' ');
  const hasMod = sc.includes('Mod+') || sc.includes('Alt+');
  // A bare key or Shift+key would fire while typing anywhere outside a field.
  if (!isSequence && !hasMod && !/^F([2-9]|1[0-9])$/.test(sc)) return { problem: 'needs_modifier' };
  // Alt+letter alone types characters on macOS and opens menus on Windows.
  if (!isSequence && /^Alt\+[A-Z0-9]$/.test(sc)) return { problem: 'reserved' };
  const holder = taken.get(sc);
  if (holder && holder !== actionId) return { problem: 'conflict', holder };
  return null;
}

/** The chord a keyboard event spells, e.g. `Mod+Shift+E`, or '' for a bare modifier press. */
export function eventToChord(e: Pick<KeyboardEvent, 'key' | 'code' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'>): string {
  if (['Control', 'Meta', 'Alt', 'Shift', 'AltGraph'].includes(e.key)) return '';
  // Prefer the physical key for letters/digits so Alt and Shift layers do not change the name.
  let key = e.key;
  if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3);
  else if (/^Digit[0-9]$/.test(e.code)) key = e.code.slice(5);
  const mods: string[] = [];
  if (e.ctrlKey || e.metaKey) mods.push('Mod');
  if (e.altKey) mods.push('Alt');
  if (e.shiftKey && (mods.length > 0 || key.length > 1)) mods.push('Shift');
  return normalizeShortcut([...mods, key].join('+'));
}

/** How a binding reads to people: `Ctrl+Shift+E` / `⌘⇧E`, `G then B` style stays `G B`. */
export function formatShortcut(sc: string, mac = isMacPlatform()): string {
  if (!sc || sc.includes(' ')) return sc;
  if (!mac) return sc.replace('Mod', 'Ctrl');
  return sc
    .split('+')
    .map((p) => ({ Mod: '⌘', Alt: '⌥', Shift: '⇧' })[p] ?? p)
    .join('');
}

/* ── User bindings ─────────────────────────────────────────────────────── */

/** actionId → binding, or null for "no shortcut". Absent means "use the default". */
type Overrides = Record<string, string | null>;

function readOverrides(): Overrides {
  try {
    const raw = localStorage.getItem(SHORTCUTS_STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    if (!parsed || typeof parsed !== 'object') return {};
    const out: Overrides = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (v === null) out[k] = null;
      else if (typeof v === 'string' && normalizeShortcut(v)) out[k] = normalizeShortcut(v);
    }
    return out;
  } catch {
    return {};
  }
}

function writeOverrides(o: Overrides): void {
  try {
    localStorage.setItem(SHORTCUTS_STORAGE_KEY, JSON.stringify(o));
  } catch {
    // Private mode: bindings last for this tab only.
  }
}

interface ShortcutState {
  overrides: Overrides;
  setBinding: (actionId: string, shortcut: string | null) => void;
  resetBinding: (actionId: string) => void;
}

export const useShortcutStore = create<ShortcutState>((set, get) => ({
  overrides: typeof window === 'undefined' ? {} : readOverrides(),
  setBinding: (actionId, shortcut) => {
    const next = { ...get().overrides, [actionId]: shortcut === null ? null : normalizeShortcut(shortcut) };
    set({ overrides: next });
    writeOverrides(next);
  },
  resetBinding: (actionId) => {
    const next = { ...get().overrides };
    delete next[actionId];
    set({ overrides: next });
    writeOverrides(next);
  },
}));

/**
 * The binding in force for every action: the user's override, else the
 * default, minus any default that the user has since given to another action
 * (the user's choice wins a clash; the default steps aside).
 */
export function effectiveBindings(
  actions: readonly { id: string; defaultShortcut?: string }[],
  overrides: Overrides,
): Map<string, string> {
  const byAction = new Map<string, string>();
  const taken = new Set<string>();
  for (const a of actions) {
    const o = overrides[a.id];
    if (typeof o === 'string' && o && !taken.has(o)) {
      byAction.set(a.id, o);
      taken.add(o);
    }
  }
  for (const a of actions) {
    if (a.id in overrides) continue;
    const d = a.defaultShortcut ? normalizeShortcut(a.defaultShortcut) : '';
    if (d && !taken.has(d) && !RESERVED.has(d)) {
      byAction.set(a.id, d);
      taken.add(d);
    }
  }
  return byAction;
}

/** binding → actionId, the inverse of `effectiveBindings`. */
export function bindingOwners(bindings: ReadonlyMap<string, string>): Map<string, string> {
  return new Map([...bindings].map(([id, sc]) => [sc, id]));
}

/** Pairs of actions whose defaults collide, for the registry test and dev warnings. */
export function defaultConflicts(actions: readonly { id: string; defaultShortcut?: string }[]): string[] {
  const seen = new Map<string, string>();
  const out: string[] = [];
  for (const a of actions) {
    if (!a.defaultShortcut) continue;
    const sc = normalizeShortcut(a.defaultShortcut);
    const problem = checkShortcut(sc, a.id, seen);
    if (problem) out.push(`${a.id}: ${a.defaultShortcut} ${problem.problem}${problem.holder ? ` with ${problem.holder}` : ''}`);
    else seen.set(sc, a.id);
  }
  return out;
}
