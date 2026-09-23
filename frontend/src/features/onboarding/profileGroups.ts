// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * How the onboarding profile step splits the preset catalogue.
 *
 * The backend serves one flat list (`COMPANY_PRESETS` in
 * `backend/app/core/onboarding_presets.py`), and that list mixes two kinds of
 * answer. Most entries name a business: a general contractor, a developer, a
 * design office. Eight name a job inside a business: a planner, a BIM
 * coordinator, an HSE lead. Asked "what does your company do?", only the first
 * kind is an answer, so the step leads with those, in the order a reader looks
 * for them (builders, then the people who commission and design, then the
 * specialist firms), and folds the job profiles into a secondary group for the
 * person who is setting the tool up for their own job rather than for a firm.
 *
 * The lists below hold keys only. Label, description and module set still come
 * from the endpoint, so the step and the Modules page cannot disagree about
 * what a profile is. A key the backend adds later and nobody files here lands
 * in the company group, after the ordered ones: shown in the wrong place is a
 * cosmetic bug, hidden would be a missing profile. `profileGroups.test.ts`
 * reads the Python file and fails when a key is in neither list, so that
 * fallback is a safety net rather than the plan.
 */

import { ALL_MODULES, CORE_MODULE_KEYS } from './modules';

/** Business profiles, in the order the step shows them. */
export const COMPANY_PROFILE_ORDER: readonly string[] = [
  'general_contractor',
  'subcontractor',
  'mep_contractor',
  'civil_infrastructure',
  'homebuilder',
  'design_build',
  'real_estate_developer',
  'owner_client',
  'architecture_engineering',
  'estimator',
  'construction_manager',
  'facility_manager',
  'government_agency',
];

/** Job profiles: one person's role rather than what the firm does. */
export const ROLE_PROFILE_KEYS: ReadonlySet<string> = new Set([
  'commercial_manager',
  'procurement_manager',
  'scheduler_planner',
  'site_supervisor',
  'quality_manager',
  'hse_manager',
  'bim_vdc',
  'sustainability_esg',
]);

/** The catch-all profile, drawn as its own wide card under the businesses. */
export const EVERYTHING_PROFILE_KEY = 'full_enterprise';

export interface ProfileGroups<T extends { key: string }> {
  companies: T[];
  roles: T[];
  everything: T | null;
}

/** Split the served presets into the step's three places. */
export function groupProfilePresets<T extends { key: string }>(presets: readonly T[]): ProfileGroups<T> {
  const rank = new Map(COMPANY_PROFILE_ORDER.map((key, i) => [key, i]));
  const companies: T[] = [];
  const roles: T[] = [];
  let everything: T | null = null;

  for (const preset of presets) {
    if (preset.key === EVERYTHING_PROFILE_KEY) everything = preset;
    else if (ROLE_PROFILE_KEYS.has(preset.key)) roles.push(preset);
    else companies.push(preset);
  }

  // Ordered keys first, in the declared order; anything unfiled keeps the
  // backend's order behind them. Array.prototype.sort is stable.
  const unfiled = COMPANY_PROFILE_ORDER.length;
  companies.sort((a, b) => (rank.get(a.key) ?? unfiled) - (rank.get(b.key) ?? unfiled));
  return { companies, roles, everything };
}

/**
 * Every module the catch-all profile stands for, as the wizard knows them.
 * Regional packs are left out: the server writes no flag for them under any
 * profile, so a pack switched off on the module step changes nothing there.
 */
const EVERYTHING_MODULE_KEYS: readonly string[] = ALL_MODULES.filter(
  (m) => !m.core && m.group !== 'regional',
).map((m) => m.key);

/**
 * The `company_type` the wizard saves for what the user picked and then kept
 * switched on.
 *
 * A picked profile is saved as picked, whatever was switched on or off after
 * it. The catch-all is different, because the server pins it to its own full
 * module list: sent for a set the user trimmed on the module step, it would
 * switch every one of those modules back on after Finish. So the catch-all,
 * and no pick at all (straight to the module list, or skipping the setup),
 * are saved as the catch-all only while every module is still on, and as no
 * profile (`null`) otherwise, which the server stores exactly as chosen.
 */
export function companyTypeToSave(
  picked: string | null,
  enabledModules: ReadonlySet<string>,
): string | null {
  if (picked !== null && picked !== EVERYTHING_PROFILE_KEY) return picked;
  return EVERYTHING_MODULE_KEYS.every((key) => enabledModules.has(key))
    ? EVERYTHING_PROFILE_KEY
    : null;
}

/** How many modules are on for a set of picked ones: those plus the core
 *  modules everybody has, each counted once. Several presets re-list a core
 *  module, so adding the two sizes counts those twice. */
export function activeModuleCount(enabledModules: Iterable<string>): number {
  return new Set([...enabledModules, ...CORE_MODULE_KEYS]).size;
}
