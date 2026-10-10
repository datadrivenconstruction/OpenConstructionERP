// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The Variations page's tab ids, as ?tab= carries them (/variations?tab=eot).
 * Kept apart from VariationsPage so a menu row or a guide test can check a
 * link names a real tab without loading the page.
 */

export type VariationsTab = 'notices' | 'requests' | 'orders' | 'daywork' | 'eot';

export const VARIATIONS_TABS: readonly VariationsTab[] = ['notices', 'requests', 'orders', 'daywork', 'eot'];

/** The tab shown for a missing or unknown ?tab= value. */
export const DEFAULT_VARIATIONS_TAB: VariationsTab = 'notices';

/** The extension of time claims tab, the one a menu row opens directly. */
export const VARIATIONS_EOT_TAB: VariationsTab = 'eot';

export function isVariationsTab(value: string | null): value is VariationsTab {
  return value !== null && (VARIATIONS_TABS as readonly string[]).includes(value);
}
