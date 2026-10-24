// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Module system type definitions.
 *
 * Each optional module lives in `frontend/src/modules/<name>/` and exports
 * a `ModuleManifest` from its `manifest.ts`.  The central `_registry.ts`
 * collects all manifests so the app can lazily load routes and inject sidebar
 * nav-items — without eagerly importing the module's page components.
 */

import type { LucideIcon } from 'lucide-react';
import type { PaletteAction } from '@/shared/lib/actions/registry';
import type { LazyExoticComponent, ComponentType } from 'react';

/* ── Route registered by a module ──────────────────────────────────── */

export interface ModuleRoute {
  /** URL path, e.g. `/sustainability` */
  path: string;
  /**
   * Page title shown in the AppLayout header (i18n key).
   * Resolved through `translateManifestText`, so a literal from a module that
   * has not migrated still renders as itself.
   */
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

/* ── Module manifest ───────────────────────────────────────────────── */

export interface ModuleManifest {
  /** Unique id — must match the key used in useModuleStore, e.g. `sustainability` */
  id: string;
  /**
   * Display name (i18n key).
   * Either a key the locale files already carry, or one this manifest defines
   * itself in `translations` below. Resolved through `translateManifestText`.
   */
  name: string;
  /** Short description (i18n key), resolved the same way as `name`. */
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
  /** Whether the module is enabled by default for new users */
  defaultEnabled: boolean;
  /**
   * Palette actions this module offers ("Import GAEB file"). Registered while
   * the module is enabled; see shared/lib/actions/registry.ts. Ids carry the
   * module's prefix so they never clash with core ones.
   */
  actions?: PaletteAction[];
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
