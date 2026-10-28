// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What holds a storage location or a stock item in place, and how to say it.
 *
 * Both delete endpoints refuse with 409 rather than let the database do what
 * it would otherwise do quietly. A movement's `item_id` cascades, so deleting
 * an item takes its entire ledger with it; both of a movement's location
 * columns are SET NULL, so deleting a location turns a record of where
 * material went into a record of nowhere. Either delete reports success while
 * destroying the history, which is why the refusal exists at all.
 *
 * The refusal reaches the browser as one English sentence the server composed,
 * not as a payload: `detail` is prose. There is no holder list in it to read,
 * so it cannot be shown to somebody working in another language. This module
 * therefore counts the holders itself, from the rows the server counts, and
 * the page renders the sentence from those counts through i18n.
 *
 * The counts are the server's counts by construction, not an approximation of
 * them. The item guard counts movements filtered by `item_id`; the location
 * guard counts movements filtered by `location_id`, whose backend filter ORs
 * the source and destination legs exactly as the guard's own query does, plus
 * the items defaulting to it and the balances still standing there. So one
 * probe answers both questions a delete control has to answer: what would be
 * destroyed if this went ahead, and - when nothing would be - why this row is
 * the removable one.
 */
import { useTranslation } from 'react-i18next';

import { fmtList } from '@/shared/lib/formatters';
import { fetchMovementsFor, fetchStockOnHandAt, type StockItem } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

/** A kind of record that points at the row being deleted. */
export type HolderKind = 'stocked' | 'movements' | 'defaulting';

export interface Holder {
  kind: HolderKind;
  /** How many records of this kind hold the row. Never zero: see {@link held}. */
  count: number;
}

/** The row a delete control is aimed at. `name` is what the reader called it. */
export interface DeleteTarget {
  kind: 'item' | 'location';
  id: string;
  name: string;
}

/** Drop the kinds that hold nothing, so an empty list means "nothing holds it".
 *
 *  A holder counted at zero is not a weaker holder, it is not a holder, and
 *  leaving it in would turn the removable case into a sentence listing three
 *  reasons the row cannot go, all of them zero. */
function held(holders: readonly Holder[]): Holder[] {
  return holders.filter((h) => h.count > 0);
}

/** Parse a decimal string balance; anything unreadable counts as no stock. */
function balance(value: string | null | undefined): number {
  if (value == null || value.trim() === '') return 0;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

/**
 * What holds a stock item: the movements booked against it, and nothing else.
 *
 * A link to a BoQ position or to a requisition line does not hold an item -
 * those are references the item makes, not history that would be lost - so an
 * item linked to the bill and never moved is still removable.
 */
export async function probeItemHolders(projectId: string, itemId: string): Promise<Holder[]> {
  const movements = await fetchMovementsFor(projectId, { itemId });
  return held([{ kind: 'movements', count: movements.length }]);
}

/**
 * What holds a storage location.
 *
 * Three kinds, ordered as the server orders them, because the first is the one
 * an operator recognises: stock is still standing there, movements name it, or
 * items point at it as their default. The items are the list the page already
 * loaded - every item on the project is in it, so that count is exact without
 * a request of its own.
 */
export async function probeLocationHolders(
  projectId: string,
  locationId: string,
  items: readonly StockItem[],
): Promise<Holder[]> {
  const [movements, onHand] = await Promise.all([
    fetchMovementsFor(projectId, { locationId }),
    fetchStockOnHandAt(projectId, locationId),
  ]);
  // A zero row is an item that passed through and left, not stock standing
  // there; a negative one is a booking error and is still something to look at
  // before the location disappears. The server draws the line the same way.
  const stocked = onHand.rows.filter((r) => balance(r.on_hand) !== 0).length;
  const defaulting = items.filter((i) => i.default_location_id === locationId).length;
  return held([
    { kind: 'stocked', count: stocked },
    { kind: 'movements', count: movements.length },
    { kind: 'defaulting', count: defaulting },
  ]);
}

/** Run whichever probe fits the target. */
export function probeHolders(
  projectId: string,
  target: DeleteTarget,
  items: readonly StockItem[],
): Promise<Holder[]> {
  return target.kind === 'item'
    ? probeItemHolders(projectId, target.id)
    : probeLocationHolders(projectId, target.id, items);
}

/** One holder as the reader's language words it: "3 recorded movements". */
export function holderPhrase(holder: Holder, t: Translate): string {
  switch (holder.kind) {
    case 'stocked':
      return t('site_inventory.holder_stocked', {
        count: holder.count,
        defaultValue_one: '{{count}} item with stock still on hand there',
        defaultValue_other: '{{count}} items with stock still on hand there',
      });
    case 'defaulting':
      return t('site_inventory.holder_defaulting', {
        count: holder.count,
        defaultValue_one: '{{count}} item that defaults to it',
        defaultValue_other: '{{count}} items that default to it',
      });
    default:
      return t('site_inventory.holder_movements', {
        count: holder.count,
        defaultValue_one: '{{count}} recorded movement',
        defaultValue_other: '{{count}} recorded movements',
      });
  }
}

/**
 * The holders as one phrase: "2 items with stock still on hand there, 14
 * recorded movements and 1 item that defaults to it".
 *
 * Joined through `fmtList` and never through `join(', ')`, because the word
 * between the last two is a word in the reader's language, not punctuation.
 */
export function holderList(holders: readonly Holder[], t: Translate): string {
  return fmtList(
    holders.map((h) => holderPhrase(h, t)),
    'prose',
  );
}
