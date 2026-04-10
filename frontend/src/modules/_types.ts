/**
 * Module system type definitions.
 *
 * Each optional module lives in `frontend/src/modules/<name>/` and exports
 * a `ModuleManifest` from its `manifest.ts`.  The central `_registry.ts`
 * collects all manifests so the app can lazily load routes, inject sidebar
 * nav-items, and populate the command-palette — without eagerly importing
 * the module's page components.
 */

import type { LucideIcon } from 'lucide-react';
import type { LazyExoticComponent, ComponentType } from 'react';

/* ── Route registered by a module ──────────────────────────────────── */

export interface ModuleRoute {
  /** URL path, e.g. `/sustainability` */
  path: string;
  /** Page title shown in AppLayout header */
  title: string;
  /** React.lazy(() => import('./Page')) — loaded only when navigated to */
  component: LazyExoticComponent<ComponentType<unknown>>;
}

/* ── Sidebar navigation item ───────────────────────────────────────── */

export interface ModuleNavItem {
  /** i18n key for the label */
  labelKey: string;
  /** Route path, e.g. `/sustainability` */
  to: string;
  /** Lucide icon component */
  icon: LucideIcon;
  /** Sidebar group id this item belongs to (estimation | planning | procurement | tools | regional) */
  group: string;
  /** Only visible when advanced view-mode is on */
  advancedOnly?: boolean;
}

/* ── Command-palette / search entry ────────────────────────────────── */

export interface ModuleSearchEntry {
  /** Human-readable label shown in search results */
  label: string;
  /** Navigation path */
  path: string;
  /** Extra keywords for fuzzy matching */
  keywords: string[];
}

/* ── Module manifest ───────────────────────────────────────────────── */

export interface ModuleManifest {
  /** Unique id — must match the key used in useModuleStore, e.g. `sustainability` */
  id: string;
  /** Display name (i18n key) */
  name: string;
  /** Short description (i18n key) */
  description: string;
  /** SemVer version string */
  version: string;
  /** Lucide icon for marketplace / module listing */
  icon: LucideIcon;
  /** Sidebar category */
  category: 'estimation' | 'planning' | 'procurement' | 'tools' | 'regional' | 'converter';
  /** Routes this module registers */
  routes: ModuleRoute[];
  /** Sidebar nav items */
  navItems: ModuleNavItem[];
  /** Command-palette entries (optional) */
  searchEntries?: ModuleSearchEntry[];
  /** Whether the module is enabled by default for new users */
  defaultEnabled: boolean;
  /** Module IDs this module depends on (e.g. ['boq', 'costs']) */
  depends?: string[];
  /**
   * Module-bundled translations.
   * Keys are language codes (e.g. 'en', 'de'), values are flat key→string maps.
   * These get merged into the default i18next namespace on module load.
   * Example: `{ en: { 'mymod.title': 'My Module' }, de: { 'mymod.title': 'Mein Modul' } }`
   */
  translations?: Record<string, Record<string, string>>;
}
