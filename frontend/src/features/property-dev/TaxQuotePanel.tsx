// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * TaxQuotePanel — jurisdiction-aware tax / VAT / stamp-duty breakdown
 * for a SalesContract.
 *
 * Designed to live inside the SalesContract drawer/edit page. Renders a
 * compact form (jurisdiction, region subcode, buyer-profile flags) and
 * a line-item breakdown table sourced from
 * ``POST /api/v1/property-dev/sales-contracts/{id}/tax-quote``.
 *
 * Backend dispatcher is in ``backend/app/modules/property_dev/tax_engine.py``;
 * rates live in ``backend/app/modules/property_dev/data/tax_rates.yaml``.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2 } from 'lucide-react';

import { fetchContractTaxQuote } from './api';
import type { ContractTaxQuote, TaxQuotePayload } from './api';
import { formatCurrency } from '@/shared/lib/money';

interface Props {
  /** SalesContract.id to quote. */
  contractId: string;
  /** Optional default jurisdiction (e.g. derived from governing_law). */
  defaultJurisdiction?: string;
  /** Optional default subcode (DE state, IN state, AU state, US state). */
  defaultRegionSubcode?: string;
  /** Optional currency to render the totals in (read from the contract). */
  currency?: string;
  /**
   * When true the panel auto-runs the quote on mount with the defaults.
   * When false the user clicks "Compute".
   */
  autoload?: boolean;
}

/** Curated dropdown of supported jurisdictions — mirrors data/tax_rates.yaml. */
const JURISDICTIONS: Array<{ code: string; label: string }> = [
  { code: 'GB', label: 'United Kingdom (SDLT)' },
  { code: 'DE', label: 'Germany (Grunderwerbsteuer)' },
  { code: 'AT', label: 'Austria' },
  { code: 'CH', label: 'Switzerland' },
  { code: 'AE', label: 'United Arab Emirates (DLD)' },
  { code: 'SA', label: 'Saudi Arabia (RETT)' },
  { code: 'IN', label: 'India (GST + state stamp duty)' },
  { code: 'RU', label: 'Russia (госпошлина)' },
  { code: 'BR', label: 'Brazil (ITBI)' },
  { code: 'SG', label: 'Singapore (BSD + ABSD)' },
  { code: 'US', label: 'United States (state transfer tax)' },
  { code: 'AU', label: 'Australia (state stamp duty)' },
];

/** Subcode pickers per jurisdiction — only the most-requested set. */
const REGION_SUBCODES: Record<string, Array<{ code: string; label: string }>> = {
  DE: [
    { code: 'BW', label: 'Baden-Württemberg (5%)' },
    { code: 'BY', label: 'Bayern (3.5%)' },
    { code: 'BE', label: 'Berlin (6%)' },
    { code: 'BB', label: 'Brandenburg (6.5%)' },
    { code: 'HE', label: 'Hessen (6%)' },
    { code: 'NW', label: 'NRW (6.5%)' },
    { code: 'SH', label: 'Schleswig-Holstein (6.5%)' },
  ],
  IN: [
    { code: 'MH', label: 'Maharashtra (6%)' },
    { code: 'DL', label: 'Delhi (6%)' },
    { code: 'KA', label: 'Karnataka (5%)' },
    { code: 'UP', label: 'Uttar Pradesh (7%)' },
    { code: 'TN', label: 'Tamil Nadu (7%)' },
  ],
  AU: [
    { code: 'NSW', label: 'New South Wales' },
    { code: 'VIC', label: 'Victoria' },
    { code: 'QLD', label: 'Queensland' },
    { code: 'WA', label: 'Western Australia' },
    { code: 'SA', label: 'South Australia' },
  ],
  US: [
    { code: 'NY', label: 'New York (0.4%)' },
    { code: 'CA', label: 'California (0.11%)' },
    { code: 'FL', label: 'Florida (0.7%)' },
    { code: 'TX', label: 'Texas (0%)' },
    { code: 'WA', label: 'Washington (1.28%)' },
  ],
  CH: [
    { code: 'ZH', label: 'Zürich (0%)' },
    { code: 'BE', label: 'Bern (1.8%)' },
    { code: 'GE', label: 'Genève (3.3%)' },
    { code: 'VD', label: 'Vaud (3.3%)' },
  ],
};

const EMIRATES: Array<{ code: string; label: string }> = [
  { code: 'dubai', label: 'Dubai (4%)' },
  { code: 'abu_dhabi', label: 'Abu Dhabi (2%)' },
  { code: 'sharjah', label: 'Sharjah (2%)' },
  { code: 'ajman', label: 'Ajman (2%)' },
];

const ABSD_PROFILES: Array<{ code: string; label: string }> = [
  { code: 'sc_first', label: 'SG Citizen (first home, 0%)' },
  { code: 'sc_second', label: 'SG Citizen (second, 20%)' },
  { code: 'spr_first', label: 'PR (first, 5%)' },
  { code: 'spr_second', label: 'PR (second, 30%)' },
  { code: 'foreigner', label: 'Foreigner (60%)' },
  { code: 'entity', label: 'Entity / company (65%)' },
];

const VAT_RATE_CLASSES: Array<{ code: string; label: string }> = [
  { code: 'standard', label: 'Standard' },
  { code: 'reduced', label: 'Reduced' },
  { code: 'zero_rated', label: 'Zero-rated' },
  { code: 'affordable', label: 'Affordable (IN)' },
  { code: 'premium', label: 'Premium (IN)' },
  { code: 'commercial', label: 'Commercial (IN)' },
];

// A tax line is money, so it is formatted by the module that owns money.
//
// This built its own formatter with a ceiling of two decimals and no floor,
// which is not a rounding preference but a claim that every currency a quote
// can arrive in has at most two minor units. A yen quote of 1234.50 printed
// "1.234,5 ¥", a fraction the yen has no unit for, and a dinar quote lost its
// third digit - on an engine that predates the ES2023 clamping it did not
// print anything at all, because a default floor of three against a ceiling of
// two is the `RangeError` out of a render path that `fractionDigits.ts` exists
// to stop. `formatCurrency` asks the engine what the currency's minor units
// actually are, and it never throws.
//
// A blank currency now renders a bare grouped number rather than a fabricated
// dollar sign. `displayCurrency` falls back to '' when neither the quote nor
// the contract names one, and a US symbol on a Singapore stamp duty is a
// wrong answer stated confidently.
function formatMoney(value: string | number, currency: string): string {
  const n = typeof value === 'string' ? parseFloat(value) : value;
  if (!Number.isFinite(n)) return String(value);
  return formatCurrency(n, currency);
}

export function TaxQuotePanel({
  contractId,
  defaultJurisdiction = '',
  defaultRegionSubcode = '',
  currency = '',
  autoload = true,
}: Props) {
  const { t } = useTranslation();

  const [jurisdiction, setJurisdiction] = useState(defaultJurisdiction);
  const [regionSubcode, setRegionSubcode] = useState(defaultRegionSubcode);
  const [vatRateClass, setVatRateClass] = useState('standard');
  const [isFirstHome, setIsFirstHome] = useState(false);
  const [isAdditionalProperty, setIsAdditionalProperty] = useState(false);
  const [emirate, setEmirate] = useState('');
  const [absdProfile, setAbsdProfile] = useState('');
  const [includeOverdue, setIncludeOverdue] = useState(true);

  const [quote, setQuote] = useState<ContractTaxQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const subcodeOptions = REGION_SUBCODES[jurisdiction] ?? [];
  const showEmirate = jurisdiction === 'AE';
  const showAbsd = jurisdiction === 'SG';
  const showFirstHome = jurisdiction === 'GB';

  const computeQuote = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload: TaxQuotePayload = {
        include_overdue: includeOverdue,
        vat_rate_class: vatRateClass,
      };
      if (jurisdiction) payload.jurisdiction = jurisdiction;
      if (regionSubcode) payload.region_subcode = regionSubcode;
      if (showFirstHome) {
        payload.is_first_home = isFirstHome;
        payload.is_additional_property = isAdditionalProperty;
      }
      if (showEmirate && emirate) payload.emirate = emirate;
      if (showAbsd && absdProfile) payload.absd_buyer_profile = absdProfile;

      const result = await fetchContractTaxQuote(contractId, payload);
      setQuote(result);
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : t('propdev.tax.compute_error', 'Failed to compute tax quote');
      setError(message);
      setQuote(null);
    } finally {
      setLoading(false);
    }
  }, [
    contractId,
    jurisdiction,
    regionSubcode,
    vatRateClass,
    isFirstHome,
    isAdditionalProperty,
    emirate,
    absdProfile,
    includeOverdue,
    showFirstHome,
    showEmirate,
    showAbsd,
    t,
  ]);

  useEffect(() => {
    if (autoload && contractId) {
      computeQuote();
    }
    // We deliberately don't depend on computeQuote so the panel only
    // auto-runs once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoload, contractId]);

  const displayCurrency = useMemo(
    () => quote?.currency || currency || '',
    [quote, currency],
  );

  return (
    <section
      className="rounded-xl border border-border-light bg-surface-primary p-4 space-y-3"
      aria-labelledby="taxquote-heading"
    >
      <header className="flex items-baseline justify-between">
        <h3
          id="taxquote-heading"
          className="text-sm font-semibold text-content-primary"
        >
          {t('propdev.tax.title', 'Tax / VAT / Stamp-duty breakdown')}
        </h3>
        {quote && (
          <span className="text-xs text-content-tertiary">
            {quote.jurisdiction}
            {quote.region_subcode ? `-${quote.region_subcode}` : ''}
          </span>
        )}
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
        <label className="flex flex-col gap-1">
          <span className="text-content-secondary">
            {t('propdev.tax.jurisdiction', 'Jurisdiction')}
          </span>
          <select
            value={jurisdiction}
            onChange={(e) => {
              setJurisdiction(e.target.value);
              setRegionSubcode('');
              setEmirate('');
              setAbsdProfile('');
            }}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
          >
            <option value="">{t('propdev.tax.auto_detect', 'Auto-detect from contract')}</option>
            {JURISDICTIONS.map((j) => (
              <option key={j.code} value={j.code}>
                {j.label}
              </option>
            ))}
          </select>
        </label>

        {subcodeOptions.length > 0 && (
          <label className="flex flex-col gap-1">
            <span className="text-content-secondary">
              {t('propdev.tax.region_subcode', 'Region / state')}
            </span>
            <select
              value={regionSubcode}
              onChange={(e) => setRegionSubcode(e.target.value)}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
            >
              <option value="">{t('propdev.tax.select_region', 'Select region')}</option>
              {subcodeOptions.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="flex flex-col gap-1">
          <span className="text-content-secondary">
            {t('propdev.tax.vat_rate_class', 'VAT / GST class')}
          </span>
          <select
            value={vatRateClass}
            onChange={(e) => setVatRateClass(e.target.value)}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
          >
            {VAT_RATE_CLASSES.map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </select>
        </label>

        {showEmirate && (
          <label className="flex flex-col gap-1">
            <span className="text-content-secondary">
              {t('propdev.tax.emirate', 'Emirate')}
            </span>
            <select
              value={emirate}
              onChange={(e) => setEmirate(e.target.value)}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
            >
              <option value="">{t('propdev.tax.select_emirate', 'Select emirate')}</option>
              {EMIRATES.map((em) => (
                <option key={em.code} value={em.code}>
                  {em.label}
                </option>
              ))}
            </select>
          </label>
        )}

        {showAbsd && (
          <label className="flex flex-col gap-1">
            <span className="text-content-secondary">
              {t('propdev.tax.absd_profile', 'ABSD buyer profile')}
            </span>
            <select
              value={absdProfile}
              onChange={(e) => setAbsdProfile(e.target.value)}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
            >
              <option value="">{t('propdev.tax.no_absd', 'No ABSD')}</option>
              {ABSD_PROFILES.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
        )}

        {showFirstHome && (
          <>
            <label className="flex items-center gap-2 col-span-1">
              <input
                type="checkbox"
                checked={isFirstHome}
                onChange={(e) => setIsFirstHome(e.target.checked)}
              />
              <span className="text-content-secondary">
                {t('propdev.tax.first_home', 'First-time buyer (UK SDLT relief)')}
              </span>
            </label>
            <label className="flex items-center gap-2 col-span-1">
              <input
                type="checkbox"
                checked={isAdditionalProperty}
                onChange={(e) => setIsAdditionalProperty(e.target.checked)}
              />
              <span className="text-content-secondary">
                {t('propdev.tax.additional_property', 'Additional property (+3%)')}
              </span>
            </label>
          </>
        )}

        <label className="flex items-center gap-2 col-span-1 md:col-span-2">
          <input
            type="checkbox"
            checked={includeOverdue}
            onChange={(e) => setIncludeOverdue(e.target.checked)}
          />
          <span className="text-content-secondary">
            {t('propdev.tax.include_overdue', 'Include late-interest on overdue instalments')}
          </span>
        </label>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={computeQuote}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue/90 disabled:opacity-50"
        >
          {loading ? (
            <Loader2 size={12} className="animate-spin" aria-hidden="true" />
          ) : null}
          {t('propdev.tax.compute', 'Compute taxes')}
        </button>
        {error && (
          <span
            role="alert"
            className="inline-flex items-center gap-1 text-xs text-semantic-error"
          >
            <AlertCircle size={12} aria-hidden="true" />
            {error}
          </span>
        )}
      </div>

      {quote && (
        <div
          className="rounded-md border border-border-light overflow-hidden"
          data-testid="taxquote-breakdown"
        >
          <table className="w-full text-xs">
            <thead className="bg-surface-secondary/50">
              <tr>
                <th className="text-left px-3 py-1.5 font-medium text-content-secondary">
                  {t('propdev.tax.line', 'Line item')}
                </th>
                <th className="text-right px-3 py-1.5 font-medium text-content-secondary">
                  {t('propdev.tax.amount', 'Amount')}
                </th>
              </tr>
            </thead>
            <tbody>
              {quote.breakdown.map((row, idx) => (
                <tr key={idx} className="border-t border-border-light">
                  <td className="px-3 py-1.5 text-content-primary">{row.line}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {formatMoney(row.amount, displayCurrency)}
                  </td>
                </tr>
              ))}
              <tr className="border-t border-border-light bg-surface-secondary/30">
                <td className="px-3 py-1.5 font-medium text-content-primary">
                  {t('propdev.tax.subtotal', 'Subtotal taxes')}
                </td>
                <td className="px-3 py-1.5 text-right font-medium tabular-nums">
                  {formatMoney(quote.subtotal_taxes, displayCurrency)}
                </td>
              </tr>
              <tr className="border-t border-border-light bg-surface-secondary/60">
                <td className="px-3 py-1.5 font-semibold text-content-primary">
                  {t('propdev.tax.grand_total', 'Grand total')}
                </td>
                <td className="px-3 py-1.5 text-right font-semibold tabular-nums">
                  {formatMoney(quote.grand_total, displayCurrency)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
