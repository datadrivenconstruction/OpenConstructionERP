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

/* ── Server sync helpers ─────────────────────────────────────────────── */

/** Debounce timer for saving preferences to server. */
let saveTimer: ReturnType<typeof setTimeout> | null = null;

/* ── Store interface ──────────────────────────────────────────────────── */

interface ModuleStore {
  enabledModules: Record<string, boolean>;
  isModuleEnabled: (moduleKey: string) => boolean;
  setModuleEnabled: (moduleKey: string, enabled: boolean) => void;

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
}

export const useModuleStore = create<ModuleStore>((set, get) => ({
  enabledModules: readState(),

  isModuleEnabled: (key: string) => {
    if (CORE_MODULES.has(key)) return true;
    return get().enabledModules[key] ?? true;
  },

  setModuleEnabled: (key: string, enabled: boolean) => {
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

  syncFromServer: async () => {
    set({ isSyncing: true });
    try {
      const resp = await apiGet<{ modules: Record<string, boolean> }>(
        '/v1/users/module-preferences',
      );
      const serverPrefs = resp.modules ?? resp;
      set((state) => {
        const merged = { ...state.enabledModules, ...serverPrefs };
        try {
          localStorage.setItem(STORE_KEY, JSON.stringify(merged));
        } catch {
          // ignore
        }
        return { enabledModules: merged, isSyncing: false };
      });
    } catch {
      // Server may not support this endpoint yet — silently fall back to local
      set({ isSyncing: false });
    }
  },

  saveToServer: () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const prefs = get().enabledModules;
      apiPatch('/v1/users/module-preferences', { modules: prefs }).catch(() => {
        // Server may not support this endpoint yet — ignore
      });
    }, 1000);
  },
}));

export { CORE_MODULES };
