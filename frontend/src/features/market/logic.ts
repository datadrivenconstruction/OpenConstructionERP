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
