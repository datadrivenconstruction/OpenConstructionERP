// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Central module registry.
 *
 * Every optional module must be registered here.  Only the tiny `manifest`
 * objects are imported eagerly — the actual page components use React.lazy()
 * inside the manifest, so they are code-split automatically by Vite.
 *
 * To add a new module:
 *   1. Create `frontend/src/modules/<name>/manifest.ts`
 *   2. Import it here and add to MODULE_REGISTRY
 *   3. Done — routes and sidebar pick it up automatically
 */

import type {
  ModuleManifest,
  ModuleRoute,
  ModuleNavItem,
} from './_types';

/* ── Module manifest imports ───────────────────────────────────────── */

import { manifest as assemblies } from './assemblies/manifest';
import { manifest as methodology } from './methodology/manifest';
import { manifest as validation } from './validation/manifest';
import { manifest as schedule } from './schedule/manifest';
import { manifest as fiveDCostModel } from './5d-cost-model/manifest';
import { manifest as tendering } from './tendering/manifest';
import { manifest as reports } from './reports/manifest';
import { manifest as sustainability } from './sustainability/manifest';
import { manifest as costBenchmark } from './cost-benchmark/manifest';
import { manifest as pdfTakeoff } from './pdf-takeoff/manifest';
import { manifest as collaboration } from './collaboration/manifest';
import { manifest as riskAnalysis } from './risk-analysis/manifest';
import { manifest as gaebExchange } from './gaeb-exchange/manifest';
// Wave 5 Epic I — 20 country exchange modules collapsed into one polymorphic
// module. Each old route slug (au-boq-exchange, …, us-masterformat-exchange)
// is still mounted as a back-compat route by `regional-exchange/manifest.tsx`.
import { manifest as regionalExchange } from './regional-exchange/manifest';
import { manifest as ddcIfcConverter } from './ddc-ifc-converter/manifest';
import { manifest as ddcRvtConverter } from './ddc-rvt-converter/manifest';
import { manifest as pipelines } from './pipelines/manifest';
import { manifest as teamStandup } from './team-standup/manifest';
import { manifest as commsIntelligence } from './comms-intelligence/manifest';
import { manifest as workRequests } from './work-requests/manifest';

/* ── Registry ──────────────────────────────────────────────────────── */

export const MODULE_REGISTRY: ModuleManifest[] = [
  assemblies,
  methodology,
  validation,
  schedule,
  fiveDCostModel,
  tendering,
  reports,
  sustainability,
  costBenchmark,
  pdfTakeoff,
  collaboration,
  riskAnalysis,
  gaebExchange,
  regionalExchange,
  ddcIfcConverter,
  ddcRvtConverter,
  pipelines,
  teamStandup,
  commsIntelligence,
  workRequests,
];

/* ── Helper functions ──────────────────────────────────────────────── */

/** All routes from all registered modules (flat list). */
export function getAllModuleRoutes(): ModuleRoute[] {
  return MODULE_REGISTRY.flatMap((m) => m.routes);
}

/** Nav items for a specific sidebar group id. */
export function getModuleNavItems(groupId: string): ModuleNavItem[] {
  return MODULE_REGISTRY.flatMap((m) =>
    m.navItems.filter((item) => item.group === groupId),
  );
}

/** Default enabled state for all modules (used by useModuleStore). */
export function getModuleDefaults(): Record<string, boolean> {
  const defaults: Record<string, boolean> = {};
  for (const m of MODULE_REGISTRY) {
    defaults[m.id] = m.defaultEnabled;
  }
  return defaults;
}

/** Get all module IDs that depend on a given module key. */
export function getModuleDependents(moduleKey: string): string[] {
  return MODULE_REGISTRY
    .filter((m) => m.depends?.includes(moduleKey))
    .map((m) => m.id);
}

/** Get the dependency list for a specific module. */
export function getModuleDependencies(moduleId: string): string[] {
  const mod = MODULE_REGISTRY.find((m) => m.id === moduleId);
  return mod?.depends ?? [];
}

/** Group modules by their category field. */
export function getModulesByCategory(): Record<string, ModuleManifest[]> {
  const groups: Record<string, ModuleManifest[]> = {};
  for (const m of MODULE_REGISTRY) {
    if (!groups[m.category]) groups[m.category] = [];
    groups[m.category]!.push(m);
  }
  return groups;
}

/**
 * Collect all module-bundled translations, merged by language code.
 * Returns `{ en: { 'collab.title': 'Collaboration', ... }, de: { ... } }`.
 */
export function getModuleTranslations(): Record<string, Record<string, string>> {
  const merged: Record<string, Record<string, string>> = {};
  for (const mod of MODULE_REGISTRY) {
    if (!mod.translations) continue;
    for (const [lang, keys] of Object.entries(mod.translations)) {
      if (!merged[lang]) merged[lang] = {};
      Object.assign(merged[lang], keys);
    }
  }
  return merged;
}