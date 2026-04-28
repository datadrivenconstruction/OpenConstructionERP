import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * Global FX rates store — keyed by ISO 4217 currency code, values are
 * "1 unit of <code> in USD". Persists to localStorage so an estimator's
 * tweaks (or downloaded snapshot) survive across BOQs.
 *
 * The rates here are SEED defaults — approximate, deliberately not
 * live-fetched. An estimator who needs accuracy can edit any rate
 * inline from a resource row, and the new value sticks for every BOQ
 * on this device. A future patch can add a "refresh from upstream"
 * action if the team wires up a rates API.
 *
 * Project-level `fx_rates` (per-BOQ, set by the BOQ owner) still take
 * priority for conversion — this store is only the fallback.
 */
const SEED_RATES_VS_USD: Record<string, number> = {
  USD: 1.0,
  EUR: 1.07,
  GBP: 1.27,
  CHF: 1.13,
  JPY: 0.0064,
  CNY: 0.139,
  RUB: 0.011,
  INR: 0.012,
  CAD: 0.73,
  AUD: 0.66,
  NZD: 0.61,
  SGD: 0.74,
  HKD: 0.128,
  KRW: 0.00074,
  BRL: 0.197,
  MXN: 0.058,
  ZAR: 0.054,
  TRY: 0.029,
  PLN: 0.252,
  CZK: 0.043,
  HUF: 0.0028,
  SEK: 0.094,
  NOK: 0.092,
  DKK: 0.144,
  RON: 0.215,
  AED: 0.272,
  SAR: 0.267,
  QAR: 0.275,
  ILS: 0.273,
  THB: 0.029,
  IDR: 0.0000631,
  MYR: 0.221,
  PHP: 0.0177,
  VND: 0.0000405,
};

interface FxRatesState {
  /** Rate for 1 unit of `code` expressed in USD. */
  ratesVsUsd: Record<string, number>;
  setRate: (code: string, ratePerUsd: number) => void;
  removeRate: (code: string) => void;
  reset: () => void;
}

export const useFxRatesStore = create<FxRatesState>()(
  persist(
    (set) => ({
      ratesVsUsd: { ...SEED_RATES_VS_USD },
      setRate: (code, ratePerUsd) =>
        set((s) => ({
          ratesVsUsd: { ...s.ratesVsUsd, [code.toUpperCase()]: ratePerUsd },
        })),
      removeRate: (code) =>
        set((s) => {
          const next = { ...s.ratesVsUsd };
          delete next[code.toUpperCase()];
          return { ratesVsUsd: next };
        }),
      reset: () => set({ ratesVsUsd: { ...SEED_RATES_VS_USD } }),
    }),
    { name: 'oe-fx-rates-v1' },
  ),
);

/**
 * Get the rate for converting `from` → `to` using the global store.
 * Returns undefined when either currency has no entry.
 *
 * Math: rate(from→to) = rateVsUsd(from) / rateVsUsd(to)
 *   so 1 unit of `from` = (that result) units of `to`.
 */
export function getFxRate(
  from: string,
  to: string,
  ratesVsUsd: Record<string, number>,
): number | undefined {
  if (from === to) return 1;
  const fromUsd = ratesVsUsd[from];
  const toUsd = ratesVsUsd[to];
  if (typeof fromUsd !== 'number' || typeof toUsd !== 'number' || toUsd === 0) {
    return undefined;
  }
  return fromUsd / toUsd;
}
