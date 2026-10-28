// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — index.
//
// Flattens the per-domain catalog files into one ordered list and exposes the
// grouping helper the hub page renders from. Each domain lives in its own file
// under ./catalog/* so the catalog can be authored in parallel without merge
// conflicts.

import { HOW_IT_WORKS_CATEGORIES } from './types';
import type { HowItWorksCategory, ModuleExplanation } from './types';

import { overviewEstimatingModules } from './catalog/overview-estimating';
import { takeoffRealityModules } from './catalog/takeoff-reality';
import { costDataControlModules } from './catalog/cost-data-control';
import { coordinationModules } from './catalog/coordination';
import { commercialProcurementModules } from './catalog/commercial-procurement';
import { fieldResourcesModules } from './catalog/field-resources';
import { qualitySafetyModules } from './catalog/quality-safety';
import { communicationDocumentsModules } from './catalog/communication-documents';
import { realestateFinanceControlsModules } from './catalog/realestate-finance-controls';
import { automationIntegrationsAdminModules } from './catalog/automation-integrations-admin';

// Per-module gap-fill cards, one file each under ./catalog/modules/*. Listed
// explicitly rather than via import.meta.glob so the Node-side i18n extract
// tooling (which bundles this file with esbuild) can read them; esbuild does
// not implement Vite's import.meta.glob. To add a card: drop its file here,
// then add one import below and one spread in MODULE_EXPLANATIONS. The
// `category` field on each entry (not the file) decides its on-page section.
import { bcfModules } from './catalog/modules/bcf';
import { changeIntelligenceModules } from './catalog/modules/change_intelligence';
import { claimsEvidenceModules } from './catalog/modules/claims_evidence';
import { complianceModules } from './catalog/modules/compliance';
import { constructionControlModules } from './catalog/modules/construction_control';
import { costRecoveryModules } from './catalog/modules/cost_recovery';
import { enterpriseWorkflowsModules } from './catalog/modules/enterprise_workflows';
import { fullEvmModules } from './catalog/modules/full_evm';
import { scheduleProgressModules } from './catalog/modules/progress';
import { savedViewsModules } from './catalog/modules/saved_views';
import { searchModules } from './catalog/modules/search';
import { smartViewsModules } from './catalog/modules/smart_views';
import { teamsModules } from './catalog/modules/teams';
import { valueModules } from './catalog/modules/value';

export const MODULE_EXPLANATIONS: ModuleExplanation[] = [
  ...overviewEstimatingModules,
  ...takeoffRealityModules,
  ...costDataControlModules,
  ...coordinationModules,
  ...commercialProcurementModules,
  ...fieldResourcesModules,
  ...qualitySafetyModules,
  ...communicationDocumentsModules,
  ...realestateFinanceControlsModules,
  ...automationIntegrationsAdminModules,
  ...bcfModules,
  ...changeIntelligenceModules,
  ...claimsEvidenceModules,
  ...complianceModules,
  ...constructionControlModules,
  ...costRecoveryModules,
  ...enterpriseWorkflowsModules,
  ...fullEvmModules,
  ...scheduleProgressModules,
  ...savedViewsModules,
  ...searchModules,
  ...smartViewsModules,
  ...teamsModules,
  ...valueModules,
];

export { HOW_IT_WORKS_CATEGORIES };
export type { ModuleExplanation, HowItWorksCategory, CategoryId, HowToStep } from './types';

export interface CategoryGroup {
  category: HowItWorksCategory;
  modules: ModuleExplanation[];
}

/**
 * Group the given modules by category, preserving the canonical category
 * order and dropping empty categories. Within each section modules sort by
 * their optional `order` (ascending) and then by their original catalog index,
 * so an author can make the reading order intentional without numbering every
 * entry. The `|| ai - bi` fallback also covers two unordered modules (whose
 * `Infinity - Infinity` is NaN), keeping the sort stable.
 */
export function groupByCategory(
  mods: ModuleExplanation[] = MODULE_EXPLANATIONS,
): CategoryGroup[] {
  return HOW_IT_WORKS_CATEGORIES.map((category) => ({
    category,
    modules: mods
      .map((m, i) => [m, i] as const)
      .filter(([m]) => m.category === category.id)
      .sort(([a, ai], [b, bi]) => (a.order ?? Infinity) - (b.order ?? Infinity) || ai - bi)
      .map(([m]) => m),
  })).filter((g) => g.modules.length > 0);
}
