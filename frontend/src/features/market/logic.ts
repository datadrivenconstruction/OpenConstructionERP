// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pure helpers for the market scope (no React, easy to test). */
import type { MarketScope } from './api';

const bare = (name: string) => name.replace(/^oe_/, '');

/** Whether a module belongs to another market. Fail-open while the scope loads. */
export function isModuleOtherMarket(module: string, scope: MarketScope | undefined): boolean {
  // A scope without the list (still loading, or a mocked answer) hides nothing.
  const hidden = scope?.hidden_modules;
  return Array.isArray(hidden) && hidden.includes(bare(module));
}

/** Whether a route owned by `owner` (one module or all of several) belongs to another market. */
export function isRouteHiddenByMarket(
  owner: string | readonly string[] | undefined,
  scope: MarketScope | undefined,
): boolean {
  if (!owner || !scope) return false;
  if (typeof owner === 'string') return isModuleOtherMarket(owner, scope);
  return owner.length > 0 && owner.every((m) => isModuleOtherMarket(m, scope));
}

/** Rule sets for a validation run: the server's market answer, else the universal set. */
export function ruleSetsFromScope(scope: MarketScope | undefined): string[] {
  return Array.isArray(scope?.rule_sets) && scope.rule_sets.length ? scope.rule_sets : ['boq_quality'];
}

/** Whether AIA G702/G703 documents apply: a market whose packs offer AIA contract forms. */
export function marketOffersAia(scope: MarketScope | undefined): boolean {
  const forms = scope?.options?.contract_forms;
  return Array.isArray(forms) && forms.some((code) => String(code).toUpperCase().startsWith('AIA'));
}

/** Modules a profile change shows, hides, and leaves visible (among market-tagged modules). */
export function diffHidden(
  currentHidden: readonly string[],
  nextHidden: readonly string[],
  tagged: readonly string[],
): { appear: string[]; disappear: string[]; unchanged: number } {
  const now = new Set(currentHidden);
  const next = new Set(nextHidden);
  return {
    appear: currentHidden.filter((m) => !next.has(m)),
    disappear: nextHidden.filter((m) => !now.has(m)),
    unchanged: tagged.filter((m) => !now.has(m) && !next.has(m)).length,
  };
}

/** AIA G702/G703 applies when the tenant's market offers AIA forms and the project's country is eligible. */
export function showAiaForProject(scope: MarketScope | undefined, projectEligible: boolean): boolean {
  return projectEligible && marketOffersAia(scope);
}

/** Whether a country belongs to the tenant's markets. Fail-open while loading or when every market is active. */
export function isCountryInScope(code: string, scope: MarketScope | undefined): boolean {
  const markets = scope?.expanded_markets;
  if (!Array.isArray(markets) || markets.length === 0 || scope?.all_markets || markets.includes('*')) return true;
  return markets.includes(code.toUpperCase());
}
