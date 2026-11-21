// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tracks which optional modules are enabled/disabled.
 *
 * Core modules (Projects, BOQ, Costs) are always visible.
 * Optional modules (Sustainability, Takeoff, etc.) can be toggled
 * from the Modules page.
 *
 * Persists to localStorage and syncs with the server when available.
 */

import { create } from 'zustand';
import { getModuleDefaults, getModuleDependents, getModuleDependencies } from '@/modules/_registry';
import { apiGet, apiPatch } from '@/shared/lib/api';

const STORE_KEY = 'oe_enabled_modules';

/**
 * localStorage key for the set of sidebar nav GROUPS (whole sections) the
 * user has hidden via the sidebar "Edit menu". Mirrors STORE_KEY's strategy:
 * a single JSON blob, read once at store init and rewritten on every change.
 *
 * Group hiding is a pure client-side convenience layer - it never disables a
 * backend module, it only collapses an entire nav section out of view - so,
 * unlike module ENABLE state, it is intentionally NOT mirrored to the server:
 * there is no server-side field for it and this store must not reach into the
 * backend for it. A missing or malformed key yields an empty list, so state
 * persisted by older builds (which never wrote this key) loads unchanged.
 */
const HIDDEN_GROUPS_KEY = 'oe_hidden_groups';

/** Modules that are ALWAYS shown in sidebar — cannot be disabled. */
const CORE_MODULES = new Set([
  'dashboard',
  'ai-estimate',
  'projects',
  'boq',
  'costs',
  'settings',
  'modules',
]);

/**
 * Backend package keys whose frontend module id is spelled differently. The
 * onboarding presets write the package key; the registry uses the hyphenated
 * id, so both spellings resolve to the same flag.
 */
export const MODULE_ID_ALIASES: Readonly<Record<string, string>> = {
  setting_out: 'setting-out',
  land_parcels: 'land-parcels',
};

/** The registry id for a module key, following MODULE_ID_ALIASES. */
export function canonicalModuleId(key: string): string {
  return MODULE_ID_ALIASES[key] ?? key;
}

/** Copy every aliased key onto its registry id; the registry spelling wins when both are present. */
function withCanonicalIds(prefs: Record<string, boolean>): Record<string, boolean> {
  const out = { ...prefs };
  for (const [alias, id] of Object.entries(MODULE_ID_ALIASES)) {
    if (alias in prefs && !(id in prefs)) out[id] = prefs[alias]!;
  }
  return out;
}

/** Optional modules with their default enabled state. */
const OPTIONAL_DEFAULTS: Record<string, boolean> = {
  templates: true,
  // Plugin module defaults are auto-merged from MODULE_REGISTRY
  ...getModuleDefaults(),
};

/**
 * One-time migration: merge old `oe_installed_plugins` into `oe_enabled_modules`
 * so users who previously "installed" a plugin keep it enabled.
 */
function migrateInstalledPlugins(): void {
  try {
    const raw = localStorage.getItem('oe_installed_plugins');
    if (!raw) return;
    const plugins: string[] = JSON.parse(raw);
    if (!Array.isArray(plugins) || plugins.length === 0) {
      localStorage.removeItem('oe_installed_plugins');
      return;
    }
    const enabledRaw = localStorage.getItem(STORE_KEY);
    const enabled: Record<string, boolean> = enabledRaw ? JSON.parse(enabledRaw) : {};
    for (const pluginId of plugins) {
      enabled[pluginId] = true;
    }
    localStorage.setItem(STORE_KEY, JSON.stringify(enabled));
    localStorage.removeItem('oe_installed_plugins');
    // Clean up legacy custom modules key
    localStorage.removeItem('oe_custom_modules');
  } catch {
    // ignore
  }
}

// Run migration once at module load time
migrateInstalledPlugins();

function readState(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return { ...OPTIONAL_DEFAULTS, ...JSON.parse(raw) };
  } catch {
    // ignore
  }
  return { ...OPTIONAL_DEFAULTS };
}

/** Read the persisted hidden-groups list. Backward compatible: a missing or
 *  malformed key returns an empty list rather than throwing. */
function readHiddenGroups(): string[] {
  try {
    const raw = localStorage.getItem(HIDDEN_GROUPS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.filter((g): g is string => typeof g === 'string');
    }
  } catch {
    // ignore
  }
  return [];
}

function writeHiddenGroups(list: string[]): void {
  try {
    localStorage.setItem(HIDDEN_GROUPS_KEY, JSON.stringify(list));
  } catch {
    // ignore
  }
}

/* ── Server sync helpers ─────────────────────────────────────────────── */

/** Debounce timer for saving preferences to server. */
let saveTimer: ReturnType<typeof setTimeout> | null = null;
/** The sync in flight, shared by every caller that asks while it runs. */
let inflight: Promise<void> | null = null;

/* ── Store interface ──────────────────────────────────────────────────── */

interface ModuleStore {
  enabledModules: Record<string, boolean>;
  isModuleEnabled: (moduleKey: string) => boolean;
  setModuleEnabled: (moduleKey: string, enabled: boolean) => void;

  /* ── Sidebar group visibility (Edit menu) ──────────────────────────── */
  /** Nav group ids the user has hidden as whole sections via the sidebar
   *  "Edit menu". Persisted to localStorage (see HIDDEN_GROUPS_KEY). */
  hiddenGroups: string[];
  /** True when the given nav group id is in the hidden set. */
  isGroupHidden: (groupId: string) => boolean;
  /** Hide or restore a single nav group (persists immediately). */
  setGroupHidden: (groupId: string, hidden: boolean) => void;
  /** Flip a single nav group's hidden state (persists immediately). */
  toggleGroupHidden: (groupId: string) => void;
  /** Replace the whole hidden-groups list at once. Used by the Edit menu
   *  Save action, mirroring how `setHiddenModules` commits hidden rows. */
  setHiddenGroups: (groupIds: string[]) => void;

  /** Get enabled modules that depend on the given module key. */
  getEnabledDependents: (moduleKey: string) => string[];
  /** Get modules that the given module depends on. */
  getDependencies: (moduleKey: string) => string[];
  /** Check if disabling this module would break other enabled modules. */
  canDisable: (moduleKey: string) => { allowed: boolean; blockedBy: string[] };

  /** Fetch module preferences from server and merge with local state. */
  syncFromServer: () => Promise<void>;
  /** Persist current module preferences to server (debounced internally). */
  saveToServer: () => void;
  /** Whether a server sync is in progress. */
  isSyncing: boolean;
  /**
   * True once this session has heard from the server (or failed to). Until
   * then a module that is off locally may be on for the account, so its routes
   * wait instead of answering 404 or the setup page.
   */
  serverLoaded: boolean;
  /** Forget the server answer (sign-out), so the next account loads its own. */
  resetServerLoaded: () => void;
}

export const useModuleStore = create<ModuleStore>((set, get) => ({
  enabledModules: readState(),

  isModuleEnabled: (key: string) => {
    if (CORE_MODULES.has(key)) return true;
    return get().enabledModules[canonicalModuleId(key)] ?? get().enabledModules[key] ?? true;
  },

  setModuleEnabled: (rawKey: string, enabled: boolean) => {
    const key = canonicalModuleId(rawKey);
    if (CORE_MODULES.has(key)) return; // Can't disable core
    set((state) => {
      const next = { ...state.enabledModules, [key]: enabled };
      try {
        localStorage.setItem(STORE_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return { enabledModules: next };
    });
    // Persist to server (debounced)
    get().saveToServer();
  },

  /* ── Sidebar group visibility (Edit menu) ──────────────────────────── */

  hiddenGroups: readHiddenGroups(),

  isGroupHidden: (groupId: string) => get().hiddenGroups.includes(groupId),

  setGroupHidden: (groupId: string, hidden: boolean) => {
    set((state) => {
      const has = state.hiddenGroups.includes(groupId);
      if (hidden === has) return state; // no-op: keep the same reference
      const next = hidden
        ? [...state.hiddenGroups, groupId]
        : state.hiddenGroups.filter((g) => g !== groupId);
      writeHiddenGroups(next);
      return { hiddenGroups: next };
    });
  },

  toggleGroupHidden: (groupId: string) => {
    set((state) => {
      const next = state.hiddenGroups.includes(groupId)
        ? state.hiddenGroups.filter((g) => g !== groupId)
        : [...state.hiddenGroups, groupId];
      writeHiddenGroups(next);
      return { hiddenGroups: next };
    });
  },

  setHiddenGroups: (groupIds: string[]) => {
    // De-dupe and drop empties / non-strings so a runaway caller can't
    // bloat localStorage or persist junk group ids.
    const seen = new Set<string>();
    const cleaned: string[] = [];
    for (const g of groupIds) {
      if (typeof g !== 'string') continue;
      const v = g.trim();
      if (!v || seen.has(v)) continue;
      seen.add(v);
      cleaned.push(v);
    }
    writeHiddenGroups(cleaned);
    set({ hiddenGroups: cleaned });
  },

  /* ── Dependency tracking ───────────────────────────────────────────── */

  getEnabledDependents: (moduleKey: string) => {
    const dependents = getModuleDependents(moduleKey);
    return dependents.filter((dep) => get().isModuleEnabled(dep));
  },

  getDependencies: (moduleKey: string) => {
    return getModuleDependencies(moduleKey);
  },

  canDisable: (moduleKey: string) => {
    if (CORE_MODULES.has(moduleKey)) return { allowed: false, blockedBy: [] };
    const enabledDeps = get().getEnabledDependents(moduleKey);
    return { allowed: enabledDeps.length === 0, blockedBy: enabledDeps };
  },

  /* ── Server sync ─────────────────────────────────────────────────── */

  isSyncing: false,
  serverLoaded: false,

  resetServerLoaded: () => set({ serverLoaded: false }),

  syncFromServer: () => {
    if (inflight) return inflight;
    const run = async () => {
      set({ isSyncing: true });
      try {
        const resp = await apiGet<{ modules: Record<string, boolean> }>(
          '/v1/users/me/module-preferences/',
        );
        const serverPrefs = resp.modules ?? resp;
        set((state) => {
          const merged = { ...state.enabledModules, ...withCanonicalIds(serverPrefs) };
          try {
            localStorage.setItem(STORE_KEY, JSON.stringify(merged));
          } catch {
            // ignore
          }
          return { enabledModules: merged, isSyncing: false, serverLoaded: true };
        });
      } catch {
        // Server may not support this endpoint yet — silently fall back to local
        set({ isSyncing: false, serverLoaded: true });
      }
    };
    inflight = run().finally(() => {
      inflight = null;
    });
    return inflight;
  },

  saveToServer: () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const prefs = get().enabledModules;
      apiPatch('/v1/users/me/module-preferences/', { modules: prefs }).catch(() => {
        // Server may not support this endpoint yet — ignore
      });
    }, 1000);
  },
}));

export { CORE_MODULES };
