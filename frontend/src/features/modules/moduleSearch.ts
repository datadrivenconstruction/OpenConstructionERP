// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Finding one named module among the ~190 the server loads.
 *
 * The registry page listed every system module as a flat, unsearchable grid on
 * a tab nobody lands on first, so a reader looking for one module by name
 * concluded it was not installed. Nothing was broken; the list simply could not
 * be interrogated. This file is the interrogation.
 *
 * The one decision worth stating: the haystack carries the *translated* name,
 * not only the manifest English and the `oe_` id. A German reader sees
 * "Regionalpaket - China" on the card, so "Regionalpaket" is the word they type,
 * and neither the English `display_name` ("Regional Pack - China") nor the raw
 * name (`oe_china_pack`) contains it. A filter built on the raw fields alone
 * looks correct in English and is blind in every other language, which is the
 * same shape of defect as the page that showed English names to everyone.
 *
 * Kept as pure functions rather than inlined into the page so the claim above
 * can be asserted against the real locale files without standing up a browser.
 */

import { resolveModuleDisplayName, type TranslatableModule } from './moduleDisplayName';

/** Translate function shape, narrowed to what this file uses. */
type Translate = (key: string, options: { defaultValue: string }) => string;

/** A backend module as far as searching is concerned. */
export interface SearchableModule extends TranslatableModule {
  description?: string;
  category?: string;
}

/**
 * Everything the caller has to know to build a module's searchable text.
 *
 * `categoryLabel` is injected rather than imported because the label map lives
 * with the page that renders the chips. Omitting it means categories match by
 * their raw backend value only.
 */
export interface ModuleSearchContext {
  t: Translate;
  language: string;
  categoryLabel?: (category: string) => string;
}

/** The `all` sentinel for the category filter, matching the marketplace tab. */
export const ALL_CATEGORIES = 'all';

/**
 * The text a query is matched against, lowercased.
 *
 * The raw name goes in twice, once verbatim and once with the `oe_` prefix
 * dropped and underscores opened out to spaces, so both `oe_china_pack` and
 * `china pack` are typeable.
 */
export function moduleSearchText(mod: SearchableModule, ctx: ModuleSearchContext): string {
  const parts: string[] = [
    resolveModuleDisplayName(mod, ctx.t, ctx.language),
    mod.display_name,
    mod.name,
    mod.name.replace(/^oe_/, '').replace(/_/g, ' '),
  ];
  if (mod.description) parts.push(mod.description);
  if (mod.category) {
    parts.push(mod.category);
    const label = ctx.categoryLabel?.(mod.category);
    if (label) parts.push(label);
  }
  return parts.join('\n').toLowerCase();
}

/**
 * Does a module answer to this query?
 *
 * An empty query matches everything, which keeps the unfiltered list the
 * default rather than a special case at every call site.
 */
export function matchesModuleSearch(
  mod: SearchableModule,
  query: string,
  ctx: ModuleSearchContext,
): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return moduleSearchText(mod, ctx).includes(needle);
}

/** Query and category applied together, in the order a reader thinks of them. */
export function filterModules<T extends SearchableModule>(
  modules: readonly T[],
  query: string,
  category: string,
  ctx: ModuleSearchContext,
): T[] {
  return modules.filter(
    (mod) =>
      (category === ALL_CATEGORIES || mod.category === category) &&
      matchesModuleSearch(mod, query, ctx),
  );
}

export interface ModuleCategoryTally {
  category: string;
  count: number;
}

/**
 * How many modules sit in each category, in display order.
 *
 * Derived from the modules themselves, never from a hand-written label map.
 * The server ships categories the page has no label for - `business`,
 * `extension`, `controls` and five more account for a quarter of the list - and
 * a chip row built from the label map would drop those modules out of the
 * filter without anything going red. `preferredOrder` only sorts what is
 * present; anything it does not name still gets a chip, sorted after the rest.
 */
export function tallyModuleCategories(
  modules: readonly SearchableModule[],
  preferredOrder: readonly string[] = [],
): ModuleCategoryTally[] {
  const counts = new Map<string, number>();
  for (const mod of modules) {
    const category = mod.category;
    if (!category) continue;
    counts.set(category, (counts.get(category) ?? 0) + 1);
  }
  const rank = (category: string): number => {
    const at = preferredOrder.indexOf(category);
    return at === -1 ? preferredOrder.length : at;
  };
  return [...counts.entries()]
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => rank(a.category) - rank(b.category) || a.category.localeCompare(b.category));
}
