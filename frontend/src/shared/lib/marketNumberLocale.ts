// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The market this workspace serves, expressed as the locale tag its documents
 * group numbers in - or `null` when nothing says.
 *
 * This is an INPUT to `resolveNumberLocale`, not a second answer to the
 * question that function asks. `intlLocale` is the same shape and exists for
 * the same reason: the resolver needs a fact that lives outside the
 * preferences store, and importing the store from the place that owns the
 * fact would close a cycle. There is still exactly one function that decides
 * which locale a number is written in; it now has two inputs instead of one,
 * and the reader's own preference still outranks both.
 *
 * What it is for. `'auto'` used to mean "follow the UI language", and the UI
 * language of an Indian workspace is usually English, which resolves to
 * `en-US`. So an Indian bill of quantities printed `476,579,722.78` where its
 * reader expects `47,65,79,722.78`. The grouping belongs to the document's
 * market rather than to whoever opened it, which is why this is consulted
 * before the UI language and why a German reviewing an Indian bill sees the
 * Indian grouping.
 *
 * Why a module variable rather than the preferences store. Writing the tag
 * into `numberLocale` was tried and is actively wrong: every account carries
 * the seeded `1.234,56` server default, and `adoptServerNumberFormat` maps
 * that onto `de-DE` for any local value other than `'auto'`. A stored
 * `en-IN` would therefore be overwritten with German separators on the next
 * boot, leaving an Indian workspace worse off than before the fix. Resolving
 * at read time cannot be clobbered because nothing is stored.
 *
 * Deliberately NOT per project. `useProjectContextStore` carries an id and a
 * name and no country, and its setter is called from sites that do not have
 * the project in hand (`setActiveProject(model.project_id, '')`), so a
 * per-project answer is not reachable from here without widening that call.
 * The workspace's applied regional pack is the granularity this product
 * actually has.
 */
import { useSyncExternalStore } from 'react';

/** The active market's number locale, or `null` when no pack is applied. */
let marketTag: string | null = null;

const listeners = new Set<() => void>();

/** Returns the market's number-locale tag, or `null`. */
export function getMarketNumberLocale(): string | null {
  return marketTag;
}

/**
 * Record (or clear) the market's number locale.
 *
 * Called from `usePartnerPackLocale` when a pack activates, and from
 * `resetPackLocale` with `null` when one is un-applied. Clearing matters as
 * much as setting: nothing persists this tag, so a stale value would outlive
 * the pack that justified it for the rest of the session with no control in
 * the UI able to reach it.
 *
 * A no-op when the tag has not actually changed, so an effect that re-runs on
 * every render of its owner does not wake every money surface in the app.
 */
export function setMarketNumberLocale(tag: string | null): void {
  if (marketTag === tag) return;
  marketTag = tag;
  listeners.forEach((cb) => cb());
}

const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
};

/**
 * `getMarketNumberLocale` for a component that has to re-render when it moves.
 *
 * The pack manifest arrives over the network well after first paint, so the
 * money already on screen was formatted before the market was known. Without
 * this subscription those figures keep the Western grouping until an
 * unrelated prop repaints them - the same defect `useIntlLocale` exists to
 * prevent for a language switch. The snapshot is a string or `null`, so
 * React's identity check on it is a value comparison.
 */
export function useMarketNumberLocale(): string | null {
  return useSyncExternalStore(subscribe, getMarketNumberLocale, getMarketNumberLocale);
}
