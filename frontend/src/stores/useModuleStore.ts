/**
 * Tracks which optional modules are enabled/disabled,
 * and available module updates.
 *
 * Core modules (Projects, BOQ, Costs) are always visible.
 * Optional modules (Sustainability, Takeoff, etc.) can be toggled
 * from the Modules page.
 *
 * Persists to localStorage so the sidebar reflects user choices.
 */

import { create } from 'zustand';
import { getModuleDefaults, getModuleDependents, getModuleDependencies } from '@/modules/_registry';

const STORE_KEY = 'oe_enabled_modules';
const CUSTOM_MODULES_KEY = 'oe_custom_modules';

/** Shape of a custom (user-uploaded) module manifest. */
export interface CustomModuleManifest {
  name: string;
  version: string;
  displayName: string;
  description?: string;
  author?: string;
  category?: string;
  installedAt: string; // ISO date
}

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

function readCustomModules(): CustomModuleManifest[] {
  try {
    const raw = localStorage.getItem(CUSTOM_MODULES_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed as CustomModuleManifest[];
    }
  } catch {
    // ignore
  }
  return [];
}

/* ── Module update types ──────────────────────────────────────────────── */

export interface ModuleUpdateInfo {
  currentVersion: string;
  latestVersion: string;
  changelog: string;
}

/* ── Store interface ──────────────────────────────────────────────────── */

interface ModuleStore {
  enabledModules: Record<string, boolean>;
  isModuleEnabled: (moduleKey: string) => boolean;
  setModuleEnabled: (moduleKey: string, enabled: boolean) => void;

  /** Tracks available updates per module key. */
  moduleUpdates: Record<string, ModuleUpdateInfo>;
  /** True if any module has a pending update. */
  hasUpdates: () => boolean;
  /** Simulate checking for updates (mock — no real backend). */
  checkForUpdates: () => Promise<void>;
  /** Clear the update notification for a single module (simulates "Update"). */
  dismissUpdate: (moduleKey: string) => void;
  /** Whether a check-for-updates request is in progress. */
  isCheckingUpdates: boolean;

  /** Get enabled modules that depend on the given module key. */
  getEnabledDependents: (moduleKey: string) => string[];
  /** Get modules that the given module depends on. */
  getDependencies: (moduleKey: string) => string[];
  /** Check if disabling this module would break other enabled modules. */
  canDisable: (moduleKey: string) => { allowed: boolean; blockedBy: string[] };

  /** User-uploaded custom modules persisted in localStorage. */
  customModules: CustomModuleManifest[];
  /** Install a custom module from an uploaded zip manifest. */
  installCustomModule: (manifest: {
    name: string;
    version: string;
    displayName: string;
    description?: string;
    author?: string;
    category?: string;
  }) => void;
  /** Remove a custom module by name. */
  removeCustomModule: (name: string) => void;
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

  /* ── Update tracking ──────────────────────────────────────────────── */

  moduleUpdates: {},
  isCheckingUpdates: false,

  hasUpdates: () => Object.keys(get().moduleUpdates).length > 0,

  checkForUpdates: async () => {
    set({ isCheckingUpdates: true });

    // Simulate network delay
    await new Promise((resolve) => setTimeout(resolve, 1200));

    // Mock update data for 3 modules
    const mockUpdates: Record<string, ModuleUpdateInfo> = {
      sustainability: {
        currentVersion: '1.0.0',
        latestVersion: '1.2.0',
        changelog:
          'Added EPD database for 200+ new materials. Improved GWP calculation accuracy. New benchmark comparison chart.',
      },
      'cost-benchmark': {
        currentVersion: '1.0.0',
        latestVersion: '1.1.0',
        changelog:
          'Regional cost indices updated to Q1 2026. Added BKI 2026 dataset. Performance improvements for large projects.',
      },
      collaboration: {
        currentVersion: '1.0.0',
        latestVersion: '2.0.0',
        changelog:
          'Major release: offline-first sync, presence awareness overhaul, conflict resolution UI, and 3x faster initial load.',
      },
    };

    // Only include updates for modules that haven't been dismissed
    const current = get().moduleUpdates;
    const next: Record<string, ModuleUpdateInfo> = {};
    for (const [key, info] of Object.entries(mockUpdates)) {
      // Keep existing dismissed state — if the key is already absent, add it
      if (!(key in current) || current[key]) {
        next[key] = info;
      }
    }

    set({ moduleUpdates: next, isCheckingUpdates: false });
  },

  dismissUpdate: (moduleKey: string) => {
    set((state) => {
      const next = { ...state.moduleUpdates };
      delete next[moduleKey];
      return { moduleUpdates: next };
    });
  },

  /* ── Custom (user-uploaded) modules ──────────────────────────────────── */

  customModules: readCustomModules(),

  installCustomModule: (manifest) => {
    set((state) => {
      // Prevent duplicates
      if (state.customModules.some((m) => m.name === manifest.name)) {
        return state;
      }
      const entry: CustomModuleManifest = {
        ...manifest,
        installedAt: new Date().toISOString(),
      };
      const next = [...state.customModules, entry];
      try {
        localStorage.setItem(CUSTOM_MODULES_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return { customModules: next };
    });
  },

  removeCustomModule: (name: string) => {
    set((state) => {
      const next = state.customModules.filter((m) => m.name !== name);
      try {
        localStorage.setItem(CUSTOM_MODULES_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return { customModules: next };
    });
  },
}));

export { CORE_MODULES };
