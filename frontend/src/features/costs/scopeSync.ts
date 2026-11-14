/**
 * One scope for the costs page: the "All" counter, the category tree, the
 * category list and the item list are all derived from (region, catalogId).
 * A catalogue is its own scope, so a region tag that merely repeats a
 * catalogue name must never survive as a hidden region filter.
 */

export interface CostScope {
  region: string;
  catalogId: string;
}

/** Region tags the import flow names after a catalogue are not region scopes. */
export function isCatalogueRegionTag(region: string, catalogueNames: Iterable<string>): boolean {
  if (!region) return false;
  for (const name of catalogueNames) if (name === region) return true;
  return false;
}

/** A persisted region naming a catalogue falls back to the explicit "All" view. */
export function healScope(scope: CostScope, catalogueNames: Iterable<string>): CostScope {
  if (scope.catalogId) return { region: '', catalogId: scope.catalogId };
  if (isCatalogueRegionTag(scope.region, catalogueNames)) return { region: '', catalogId: '' };
  return scope;
}

/** Query-key tail shared by every scope-dependent query so none can drift. */
export function scopeKey(scope: CostScope): [string, string] {
  return [scope.region, scope.catalogId];
}
