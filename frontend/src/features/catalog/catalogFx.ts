import { REGION_MAP } from '@/stores/useCostDatabaseStore';

/** Mirrors `CatalogFxView` from `GET /v1/catalog/fx-view/`. */
export interface CatalogFxRate {
  currency: string;
  rate: string | null;
  source: string;
  as_of: string;
  reason: string;
}

export interface CatalogFxView {
  project_currency: string;
  rates: Record<string, CatalogFxRate>;
}

/**
 * The region a catalogue should open on inside a project: the first loaded
 * region quoted in the project's currency, else the first loaded region.
 * Loaded regions arrive biggest first, so a project with no matching market
 * keeps the previous behaviour.
 */
export function pickRegionForProject(loaded: string[], projectCurrency?: string | null): string {
  const want = (projectCurrency ?? '').trim().toUpperCase();
  if (want) {
    const match = loaded.find((r) => REGION_MAP[r]?.currency === want);
    if (match) return match;
  }
  return loaded[0] ?? '';
}

export type ConvertedPrice =
  | { kind: 'same' }
  | { kind: 'converted'; amount: number; currency: string; asOf: string; source: string }
  | { kind: 'unpriced'; currency: string };

/**
 * How a rate quoted in `currency` reads in the project's currency.
 * `same` when no conversion applies (no project, same code, or an unlabelled
 * rate); `unpriced` when the currencies differ and no rate is on file, so the
 * caller shows a "different currency" marker rather than a guessed number.
 */
export function convertedPrice(
  price: number,
  currency: string | null | undefined,
  view: CatalogFxView | null | undefined,
): ConvertedPrice {
  const from = (currency ?? '').trim().toUpperCase();
  const to = (view?.project_currency ?? '').trim().toUpperCase();
  if (!view || !from || !to || from === to) return { kind: 'same' };
  const entry = view.rates[from];
  const rate = entry?.rate ? Number(entry.rate) : NaN;
  if (!entry || !Number.isFinite(rate) || rate <= 0) return { kind: 'unpriced', currency: to };
  return { kind: 'converted', amount: price * rate, currency: to, asOf: entry.as_of, source: entry.source };
}
