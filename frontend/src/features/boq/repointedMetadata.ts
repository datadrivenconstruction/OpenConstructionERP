// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The metadata of a bill line re-pointed at a cost item picked from the grid's
 * autocomplete.
 *
 * What said where the old rate came from (the link, the price list it was
 * published in, its cost shares) holds only while the line still comes from the
 * same item. Picked from another item, those keys go, and the link to the new
 * item is set when the server named its id; the server then copies that item's
 * price-list block onto the line.
 */

/** Keys that describe the item a line was priced from, not the line itself. */
export const LINE_PROVENANCE_KEYS = ['prezzario', 'cost_shares', 'xpwe_ep_id', 'safety_item'] as const;

export function repointedMetadata(
  current: Record<string, unknown> | null | undefined,
  item: { id?: string; code: string },
): Record<string, unknown> {
  const meta: Record<string, unknown> = { ...(current ?? {}), cost_item_code: item.code, source: 'cost_database' };
  const sameItem = item.id
    ? current?.cost_item_id === item.id
    : !!current && current.cost_item_code === item.code;
  if (sameItem) return meta;
  for (const key of LINE_PROVENANCE_KEYS) delete meta[key];
  if (item.id) meta.cost_item_id = item.id;
  else delete meta.cost_item_id;
  return meta;
}
