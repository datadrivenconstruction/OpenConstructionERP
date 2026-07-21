// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CrossBaseCompare - side-by-side view of one metric (typically a unit
// rate) across several loaded cost bases.
//
// Currency honesty is the whole point of this component:
//
//   * DEFAULT is native currencies side by side. When two or more bases
//     quote in different currencies the view shows a mixed-currency banner
//     and does NOT rank them, because comparing 120 EUR against 4,300 TRY
//     as bare numbers is meaningless.
//   * An explicit, display-only "One currency" toggle converts every row to
//     a single currency using a static, dated, indicative rate table
//     (see fxDisplay.ts). That view is clearly labelled an approximate
//     estimate, shows the "as of" date, keeps each native value visible as
//     a caption, and is NEVER written back to a BOQ Decimal or any store.
//   * Ranking (Lowest / Highest chips) only appears where it is honest:
//     when a single currency is already in play, or inside the converted
//     one-currency estimate view. Never across raw mixed currencies.
//
// The component is presentational and prop-driven. A data helper such as
// `compareBases` produces the rows; this file only renders them. It
// self-hides below two bases so a single loaded base gets no new chrome.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowRightLeft, Coins, AlertTriangle, Info } from 'lucide-react';
import { Badge, CountryFlag } from '@/shared/ui';
import { REGION_MAP } from '@/stores/useCostDatabaseStore';
import { getIntlLocale } from '@/shared/lib/formatters';
import {
  convertAmount,
  isFxSupported,
  pickDefaultTarget,
  targetCurrencyOptions,
  FX_RATES_AS_OF,
} from './fxDisplay';

/* ── Types ────────────────────────────────────────────────────────────── */

/** One base's value in the comparison. `value` is a display number in
 *  `currency` - it is never a BOQ Decimal and is never mutated here. */
export interface CrossBaseCompareRow {
  /** Region / base key, e.g. "DE_BERLIN" or "TR_NATIONAL". Drives the flag
   *  and, when `label` / `currency` are omitted, their defaults via
   *  REGION_MAP. */
  region: string;
  /** Native numeric value for this base (display only). */
  value: number;
  /** ISO 4217 currency of `value`. Falls back to the region's currency when
   *  omitted; an unknown/empty currency renders as a bare number. */
  currency?: string;
  /** Human label override (defaults to the region's name). */
  label?: string;
  /** Optional secondary caption under the label (e.g. "5 matched items"). */
  caption?: string;
}

export interface CrossBaseCompareProps {
  /** The bases to compare. Fewer than two rows renders nothing. */
  rows: CrossBaseCompareRow[];
  /** Heading for the card (e.g. the position description). */
  title?: string;
  className?: string;
  'data-testid'?: string;
}

/* ── Helpers ──────────────────────────────────────────────────────────── */

/** Locale-aware currency formatter. Never substitutes a guessed symbol: an
 *  empty or invalid currency renders a bare grouped number. Large-magnitude
 *  currencies (JPY, KRW, VND, ...) drop minor units so the column lines up. */
function formatAmount(value: number, currency: string): string {
  const locale = getIntlLocale();
  const safe = Number.isFinite(value) ? value : 0;
  const digits = Math.abs(safe) >= 1000 ? 0 : 2;
  const code = (currency || '').trim().toUpperCase();
  const plain = () =>
    new Intl.NumberFormat(locale, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(safe);
  if (!/^[A-Z]{3}$/.test(code)) return plain();
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: code,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(safe);
  } catch {
    return `${plain()} ${code}`;
  }
}

/* ── Component ────────────────────────────────────────────────────────── */

export function CrossBaseCompare({
  rows,
  title,
  className = '',
  'data-testid': testId = 'cross-base-compare',
}: CrossBaseCompareProps) {
  const { t } = useTranslation();

  // Display-only view state. DEFAULT is native side-by-side (off).
  const [oneCurrency, setOneCurrency] = useState(false);
  const [target, setTarget] = useState('');

  const model = useMemo(() => {
    const resolved = rows.map((r, i) => {
      const info = REGION_MAP[r.region];
      const currency = ((r.currency || info?.currency || '').trim()).toUpperCase();
      const label = r.label || info?.name || info?.label || r.region;
      return {
        key: `${r.region}-${i}`,
        region: r.region,
        label,
        caption: r.caption,
        currency,
        value: r.value,
      };
    });
    const currencies = resolved.map((r) => r.currency).filter((c) => c.length > 0);
    const distinct = Array.from(new Set(currencies));
    const isMixed = distinct.length >= 2;
    const supportedTargets = targetCurrencyOptions(currencies);
    const defaultTarget = pickDefaultTarget(currencies);
    const anyConvertible = resolved.some((r) => isFxSupported(r.currency));
    return { resolved, distinct, isMixed, supportedTargets, defaultTarget, anyConvertible };
  }, [rows]);

  const { resolved, distinct, isMixed, supportedTargets, defaultTarget, anyConvertible } = model;

  // Only offer the one-currency view when currencies actually differ AND at
  // least one row can be converted. A clamp keeps the chosen target valid
  // even if `rows` changes underneath us.
  const canOfferOneCurrency = isMixed && anyConvertible;
  const effectiveTarget =
    target && supportedTargets.includes(target) ? target : defaultTarget;
  const showOneCurrency = oneCurrency && canOfferOneCurrency;

  // Self-hide entirely below two bases: a single loaded base gets no new
  // chrome (hooks above already ran, so this early return is hook-safe).
  if (resolved.length < 2) return null;

  const display = resolved.map((r) => ({
    ...r,
    converted: showOneCurrency ? convertAmount(r.value, r.currency, effectiveTarget) : null,
  }));

  // Comparable value per row: the native value when one currency is already
  // in play, the converted estimate in one-currency view, otherwise null so
  // no ranking is attempted across raw mixed currencies.
  type Row = (typeof display)[number];
  const comparableOf = (d: Row): number | null => {
    if (!isMixed) return Number.isFinite(d.value) ? d.value : null;
    if (showOneCurrency && d.converted) return d.converted.value;
    return null;
  };
  const comparable = display
    .map(comparableOf)
    .filter((v): v is number => v != null && Number.isFinite(v));
  const lo = comparable.length >= 2 ? Math.min(...comparable) : null;
  const hi = comparable.length >= 2 ? Math.max(...comparable) : null;
  const rankable = lo != null && hi != null && lo !== hi;

  const seg = (active: boolean) =>
    'inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium transition-colors ' +
    (active ? 'bg-oe-blue text-white' : 'bg-surface-primary text-content-secondary hover:bg-surface-hover');

  return (
    <div
      className={`rounded-xl border border-border-light bg-surface-primary overflow-hidden ${className}`}
      data-testid={testId}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-border-light flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <Coins size={16} className="text-oe-blue shrink-0" />
          <h4 className="text-sm font-semibold truncate">
            {title || t('costBases.compare.title', { defaultValue: 'Cross-base comparison' })}
          </h4>
          <Badge variant="neutral" size="sm">
            {t('costBases.compare.count', {
              defaultValue: '{{n}} bases',
              n: resolved.length,
            })}
          </Badge>
        </div>

        {canOfferOneCurrency && (
          <div className="flex items-center gap-2">
            <div
              className="inline-flex rounded-lg border border-border-light overflow-hidden"
              role="group"
              aria-label={t('costBases.compare.mode_label', {
                defaultValue: 'Currency display mode',
              })}
            >
              <button
                type="button"
                aria-pressed={!oneCurrency}
                onClick={() => setOneCurrency(false)}
                className={seg(!oneCurrency)}
                data-testid="cross-base-compare-native"
              >
                {t('costBases.compare.native', { defaultValue: 'Native' })}
              </button>
              <button
                type="button"
                aria-pressed={oneCurrency}
                onClick={() => setOneCurrency(true)}
                className={seg(oneCurrency)}
                data-testid="cross-base-compare-one-currency"
              >
                <ArrowRightLeft size={12} />
                {t('costBases.compare.one_currency', { defaultValue: 'One currency' })}
              </button>
            </div>

            {showOneCurrency && supportedTargets.length > 1 && (
              <select
                value={effectiveTarget}
                onChange={(e) => setTarget(e.target.value)}
                aria-label={t('costBases.compare.target_label', { defaultValue: 'Convert to' })}
                className="text-xs rounded-lg border border-border-light bg-surface-primary px-2 py-1 text-content-secondary"
                data-testid="cross-base-compare-target"
              >
                {supportedTargets.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
      </div>

      {/* Banners - mutually exclusive */}
      {isMixed && !showOneCurrency && (
        <div
          className="px-4 py-2.5 flex items-start gap-2 text-xs bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-200 border-b border-amber-200/60 dark:border-amber-900/40"
          data-testid="cross-base-compare-mixed-banner"
        >
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            {t('costBases.compare.mixed_banner', {
              defaultValue:
                'These bases quote in different currencies ({{list}}). Each value stays in its own currency and they are not directly comparable. Switch to one-currency view for a rough estimate.',
              list: distinct.join(', '),
            })}
          </span>
        </div>
      )}
      {showOneCurrency && (
        <div
          className="px-4 py-2.5 flex items-start gap-2 text-xs bg-blue-50 dark:bg-blue-950/30 text-blue-800 dark:text-blue-200 border-b border-blue-200/60 dark:border-blue-900/40"
          data-testid="cross-base-compare-estimate-banner"
        >
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            {t('costBases.compare.estimate_banner', {
              defaultValue:
                'Approximate conversion to {{target}} using indicative rates as of {{asOf}}. For visual comparison only. It is an estimate and is never saved to a bill of quantities.',
              target: effectiveTarget,
              asOf: FX_RATES_AS_OF,
            })}
          </span>
        </div>
      )}

      {/* Rows */}
      <ul className="divide-y divide-border-light">
        {display.map((d) => {
          const cv = comparableOf(d);
          const isLow = rankable && cv != null && cv === lo;
          const isHigh = rankable && cv != null && cv === hi && cv !== lo;
          const mainValue =
            showOneCurrency && d.converted
              ? `≈ ${formatAmount(d.converted.value, effectiveTarget)}`
              : formatAmount(d.value, d.currency);
          return (
            <li
              key={d.key}
              className="px-4 py-2.5 flex items-center gap-3"
              data-testid={`cross-base-compare-row-${d.region}`}
            >
              <CountryFlag code={d.region} size={20} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate" title={d.label}>
                  {d.label}
                </div>
                {d.caption && (
                  <div className="text-[11px] text-content-tertiary truncate">{d.caption}</div>
                )}
                {showOneCurrency && d.converted && (
                  <div className="text-[11px] text-content-tertiary">
                    {t('costBases.compare.native_caption', {
                      defaultValue: 'Native {{v}}',
                      v: formatAmount(d.value, d.currency),
                    })}
                  </div>
                )}
              </div>
              <div className="text-end shrink-0">
                <div className="flex items-center gap-1.5 justify-end">
                  {showOneCurrency && !d.converted && (
                    <span
                      className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-surface-secondary text-content-tertiary"
                      title={t('costBases.compare.no_rate_hint', {
                        defaultValue: 'No indicative rate for this currency - shown in native currency',
                      })}
                    >
                      {t('costBases.compare.no_rate', { defaultValue: 'no rate' })}
                    </span>
                  )}
                  <span className="text-sm font-mono font-semibold tabular-nums">{mainValue}</span>
                </div>
                {(isLow || isHigh) && (
                  <div className="flex items-center gap-1 justify-end mt-0.5">
                    {isLow && (
                      <span className="text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                        {t('costBases.compare.lowest', { defaultValue: 'Lowest' })}
                      </span>
                    )}
                    {isHigh && (
                      <span className="text-[10px] font-medium text-rose-600 dark:text-rose-400">
                        {t('costBases.compare.highest', { defaultValue: 'Highest' })}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
