// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Adopt the currency of the market a first-run reader set up as the account's
 * currency, unless the account already has one.
 *
 * The preferences store defaults to EUR, so before this a reader who set up
 * the United Kingdom, India or Brazil finished the wizard with every money
 * surface outside a project in euros. An explicit account choice always wins:
 * the server's `currency_code` is only written while it is still empty.
 */
import { apiGet, apiPatch } from '@/shared/lib/api';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

const ISO_4217 = /^[A-Z]{3}$/;

/** Currency of each market a curated preset serves, keyed by ISO 3166-1 alpha-2. */
const CURRENCY_BY_COUNTRY: Record<string, string> = {
  us: 'USD', gb: 'GBP', de: 'EUR', fr: 'EUR', br: 'BRL', ae: 'AED', sa: 'SAR', in: 'INR',
  cn: 'CNY', ca: 'CAD', au: 'AUD', nz: 'NZD', it: 'EUR', es: 'EUR', nl: 'EUR', pl: 'PLN',
  tr: 'TRY', ru: 'RUB', jp: 'JPY', kr: 'KRW', mx: 'MXN', za: 'ZAR',
};

/**
 * The account currency for a market: the market country's own, never the cost
 * base's, which can be a neighbour's stand-in (a Saudi reader on the Dubai base).
 * Falls back to ``baseCurrency`` only for a country this table does not know.
 */
export function marketCurrencyFor(country: string | null | undefined, baseCurrency?: string | null): string | null {
  return CURRENCY_BY_COUNTRY[(country ?? '').toLowerCase()] ?? baseCurrency ?? null;
}

/** Resolves to true when the account now uses ``currency``; never rejects. */
export async function adoptMarketCurrency(currency: string | null | undefined): Promise<boolean> {
  if (!currency || !ISO_4217.test(currency)) return false;
  try {
    const current = await apiGet<{ currency_code?: string | null }>('/v1/users/me/preferences/');
    if (current.currency_code && ISO_4217.test(current.currency_code)) return current.currency_code === currency;
    await apiPatch('/v1/users/me/preferences/', { currency_code: currency });
    usePreferencesStore.getState().setPreferences({ currency, defaultCurrency: currency });
    return true;
  } catch {
    return false;
  }
}
