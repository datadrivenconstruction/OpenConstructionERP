// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DesignOptionComparisonTable - an N-column side-by-side comparison of the
 * options in a set. It clones the tendering bid-comparison layout (sticky first
 * column, one column per option, a marked baseline column and a TOTAL foot) and
 * layers in the design-option specifics: a set-level fairness banner, an
 * AI-suggested recommendation, a mixed-currency notice, per-option traffic-light
 * validation chips, a by-trade delta table and a cost-per-area strip.
 *
 * A design option is a whole alternative, so the foot also carries the
 * programme and embodied-carbon rows, sourced from the schedule and carbon
 * inventory each option links. Both appear only when at least one option in the
 * set answers them, and an option that does not answer reads "-" rather than
 * zero: an unanswered question dressed as a measurement would rank the option
 * nobody has planned as the fastest and cleanest one on the page.
 *
 * The comparison is computed authoritatively on the backend with exact Decimal
 * and FX rebase to the set currency. This component is a thin, well-typed view:
 * it parses the Decimal-as-string fields to numbers for display and sign only,
 * never for anything that feeds a bill of quantities.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowDownRight,
  ArrowUpRight,
  Minus,
  Award,
  AlertTriangle,
  CheckCircle2,
  ShieldAlert,
  Scale,
} from 'lucide-react';
import { Badge, EmptyState } from '@/shared/ui';
import { fmtList, fmtPercent } from '@/shared/lib/formatters';
import { classifyCell } from '@/features/tendering/analysis';
import { CostPerAreaBenchmark } from '@/features/boq/CostPerAreaBenchmark';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { formatCurrency } from '@/shared/lib/money';
import type {
  DesignOptionComparisonResponse,
  OptionValidationStatus,
  FairnessStatus,
  DesignOptionFairnessWarning,
} from './api';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

/** One by-trade row of the comparison (structural alias for the `colFor` helper). */
type TradeCells = DesignOptionComparisonResponse['by_trade'][number];

/* ── Number / money helpers ────────────────────────────────────────────── */

/** Parse a backend Decimal-as-string into a finite number (0 on nullish/NaN). */
function num(v: string | number | null | undefined): number {
  if (v == null) return 0;
  const n = typeof v === 'number' ? v : parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

/** Format a comparison amount with its option's currency.
 *
 *  This used to build its own formatter pinned to zero decimals. Every cell of
 *  the table and every row of its foot went through it, so the column agreed
 *  with itself - and agreed with nothing else. A euro option showed its direct
 *  cost, its markups and its grand total without cents, and a dinar option lost
 *  a thousandth that currency actually has. Two figures agreeing with each
 *  other is not the standard; agreeing with the currency is, and how many minor
 *  units a currency has is a property of the currency, which is why the shared
 *  formatter reads it from CLDR rather than accepting a literal.
 *
 *  The rest of the policy is unchanged and is the shared formatter's policy
 *  too: an unknown or blank code renders a plain grouped number and never a
 *  substituted symbol, because a euro sign on a project priced in reais is a
 *  worse answer than no sign at all. */
function formatMoney(amount: string | number, currency?: string): string {
  return formatCurrency(amount, currency);
}

function formatQty(amount: string | number, unit?: string): string {
  const value = num(amount);
  const n = new Intl.NumberFormat(getNumberLocale(), {
    maximumFractionDigits: 2,
  }).format(value);
  return unit ? `${n} ${unit}` : n;
}

/** A whole-day or whole-unit count in the reader's locale. */
function formatCount(amount: string | number): string {
  return new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 0 }).format(num(amount));
}

/* ── Small presentational atoms ────────────────────────────────────────── */

/** Signed percentage badge. A cheaper option (negative delta) reads green. */
function DeltaBadge({ pct }: { pct: number }) {
  if (!Number.isFinite(pct) || Math.abs(pct) < 0.1) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs text-content-tertiary">
        <Minus size={10} /> 0%
      </span>
    );
  }
  if (pct < 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs font-medium text-semantic-success">
        <ArrowDownRight size={12} /> {fmtPercent(pct)}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-medium text-semantic-error">
      <ArrowUpRight size={12} /> +{fmtPercent(pct)}
    </span>
  );
}

/**
 * Signed day badge. Finishing sooner (negative delta) reads green, the same
 * direction as spending less, so the two rows can be scanned together without
 * the reader having to re-learn which way is good.
 */
function DayDeltaBadge({ days }: { days: number }) {
  // Above the early return on purpose: a hook behind a branch makes React
  // render fewer hooks than it expects on exactly the zero-delta option.
  const { t } = useTranslation();
  const rounded = Math.round(days);
  // ``days`` rather than ``count``: the value is a unit abbreviation, not a
  // counted noun, so triggering i18next's plural machinery here would demand a
  // form per CLDR category in every language for a string that has one form.
  const label = t('designOptions.dayDelta', {
    defaultValue: '{{days}} d',
    days: formatCount(Math.abs(rounded)),
  });
  if (!Number.isFinite(rounded) || rounded === 0) return null;
  if (rounded < 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs font-medium text-semantic-success">
        <ArrowDownRight size={12} /> {label}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-medium text-semantic-error">
      <ArrowUpRight size={12} /> +{label}
    </span>
  );
}

const VALIDATION_VARIANT: Record<OptionValidationStatus, BadgeVariant> = {
  pending: 'neutral',
  passed: 'success',
  warnings: 'warning',
  errors: 'error',
};

function ValidationChip({ status }: { status: OptionValidationStatus }) {
  const { t } = useTranslation();
  const label: Record<OptionValidationStatus, string> = {
    pending: t('designOptions.validation.pending', { defaultValue: 'Not checked' }),
    passed: t('designOptions.validation.passed', { defaultValue: 'Passed' }),
    warnings: t('designOptions.validation.warnings', { defaultValue: 'Warnings' }),
    errors: t('designOptions.validation.errors', { defaultValue: 'Errors' }),
  };
  return (
    <Badge variant={VALIDATION_VARIANT[status]} size="sm" dot>
      {label[status]}
    </Badge>
  );
}

/** Human label for a classification system key (standards may be named). */
function classificationLabel(system: string): string {
  switch (system) {
    case 'din276':
      return 'DIN 276';
    case 'masterformat':
      return 'MasterFormat';
    case 'nrm':
      return 'NRM';
    case 'uniformat':
      return 'UniFormat';
    case 'trade':
    case '':
      return '';
    default:
      return system.toUpperCase();
  }
}

/* ── Fairness banner ───────────────────────────────────────────────────── */

const FAIRNESS_STYLE: Record<
  FairnessStatus,
  { palette: string; icon: typeof CheckCircle2 }
> = {
  ok: {
    palette: 'border-semantic-success/20 bg-semantic-success-bg/30 text-semantic-success',
    icon: CheckCircle2,
  },
  warnings: {
    palette: 'border-semantic-warning/20 bg-semantic-warning-bg/30 text-semantic-warning',
    icon: AlertTriangle,
  },
  error: {
    palette: 'border-semantic-error/20 bg-semantic-error-bg/30 text-semantic-error',
    icon: ShieldAlert,
  },
};

/** Best-effort English for each fairness notice key; the localised string wins
 *  when present, and any unmapped key still renders a human sentence. */
const FAIRNESS_DEFAULTS: Record<string, string> = {
  'designOptions.fairness.singleOption':
    'Only one option so far, so there is nothing to compare against yet.',
  'designOptions.fairness.noBaseline':
    'No baseline is set, so deltas are measured against the first option.',
  'designOptions.fairness.unpricedOptions':
    '{{count}} option(s) are not priced yet, so the comparison is incomplete.',
  'designOptions.fairness.mixedCurrencyOption':
    '{{count}} option(s) price in more than one currency, so the total is approximate.',
  'designOptions.fairness.comparisonCurrency':
    'The requested comparison currency could not be applied to every option.',
  'designOptions.fairness.missingGfa':
    'A gross floor area is missing, so cost per m2 is not shown for every option.',
  'designOptions.fairness.mixedGfa':
    'Options report different gross floor areas, so cost per m2 is not strictly like for like.',
  'designOptions.fairness.validationPending':
    'Some options have not been validated yet.',
};

function FairnessBanner({
  status,
  warnings,
}: {
  status: FairnessStatus;
  warnings: DesignOptionFairnessWarning[];
}) {
  const { t } = useTranslation();
  const style = FAIRNESS_STYLE[status] ?? FAIRNESS_STYLE.warnings;
  const Icon = style.icon;
  const heading: Record<FairnessStatus, string> = {
    ok: t('designOptions.fairness.okTitle', {
      defaultValue: 'Options are a fair, like-for-like comparison',
    }),
    warnings: t('designOptions.fairness.warningsTitle', {
      defaultValue: 'Compare with care',
    }),
    error: t('designOptions.fairness.errorTitle', {
      defaultValue: 'These options are not comparable yet',
    }),
  };
  return (
    <div className={`rounded-xl border p-3 ${style.palette}`}>
      <div className="flex items-start gap-2.5">
        <Icon size={18} className="mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-semibold">{heading[status]}</p>
          {status === 'ok' ? (
            <p className="mt-0.5 text-xs text-content-secondary">
              {t('designOptions.fairness.okBody', {
                defaultValue:
                  'Every option is priced in the same currency against the same scope, so the totals below can be read side by side.',
              })}
            </p>
          ) : (
            warnings.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-xs text-content-secondary">
                {warnings.map((w, i) => (
                  <li key={`${w.key}-${i}`} className="flex gap-1.5">
                    <span aria-hidden="true">-</span>
                    <span>
                      {t(w.key, {
                        defaultValue:
                          FAIRNESS_DEFAULTS[w.key] ??
                          'One or more checks need your attention.',
                        ...w.context,
                      })}
                    </span>
                  </li>
                ))}
              </ul>
            )
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Recommendation banner ─────────────────────────────────────────────── */

function RecommendationBanner({
  comparison,
}: {
  comparison: DesignOptionComparisonResponse;
}) {
  const { t } = useTranslation();
  const { recommendation, options } = comparison;
  if (!recommendation || !recommendation.option_id) return null;
  const winner = options.find((o) => o.option_id === recommendation.option_id);
  if (!winner) return null;

  // `confidence` is a 0..1 decimal string (the winner's margin over the runner
  // up); band it for the badge palette and label so a clear winner reads green
  // and a near tie reads amber.
  const confidenceNum = num(recommendation.confidence);
  const band: 'high' | 'medium' | 'low' =
    confidenceNum >= 0.66 ? 'high' : confidenceNum < 0.34 ? 'low' : 'medium';
  const palette =
    band === 'high'
      ? 'border-semantic-success/20 bg-semantic-success-bg/30 text-semantic-success'
      : band === 'low'
        ? 'border-semantic-warning/20 bg-semantic-warning-bg/30 text-semantic-warning'
        : 'border-oe-blue/20 bg-oe-blue-subtle text-oe-blue-text';
  const confidenceLabel =
    band === 'high'
      ? t('designOptions.confidence.high', { defaultValue: 'High confidence' })
      : band === 'low'
        ? t('designOptions.confidence.low', {
            defaultValue: 'Low confidence - review carefully',
          })
        : t('designOptions.confidence.medium', { defaultValue: 'Medium confidence' });

  // The backend `reason_key` is already a full i18n key
  // (designOptions.recommendation.*); resolve it with an honest English default
  // so a not-yet-translated key never renders raw.
  const REASON_DEFAULTS: Record<string, string> = {
    'designOptions.recommendation.lowestCostPerM2':
      'Lowest cost per m2 across the set.',
    'designOptions.recommendation.lowestTotal':
      'Lowest grand total for comparable scope.',
    'designOptions.recommendation.onlyOption':
      'The only fully priced option so far.',
    'designOptions.recommendation.none': 'No option can be recommended yet.',
  };
  const reasonText = t(recommendation.reason_key || 'designOptions.reason.generic', {
    defaultValue:
      REASON_DEFAULTS[recommendation.reason_key] ??
      'Recommended based on the current comparison.',
  });

  return (
    <div className={`rounded-xl border p-3 ${palette}`}>
      <div className="flex items-start gap-2.5">
        <Award size={18} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold">
              {t('designOptions.recommendationTitle', { defaultValue: 'Recommendation' })}
            </p>
            <Badge
              variant={
                band === 'high' ? 'success' : band === 'low' ? 'warning' : 'blue'
              }
              size="sm"
            >
              {confidenceLabel}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-content-secondary">
            <strong>{winner.name}</strong>{' '}
            {t('designOptions.at', { defaultValue: 'at' })}{' '}
            {formatMoney(winner.grand_total, winner.currency)}{' '}
            (<span className="align-middle"><DeltaBadge pct={num(winner.delta_pct)} /></span>{' '}
            {t('designOptions.vsBaseline', { defaultValue: 'vs baseline' })})
          </p>
          <p className="mt-1 text-xs text-content-tertiary">{reasonText}</p>
        </div>
      </div>
    </div>
  );
}

/* ── Main table ────────────────────────────────────────────────────────── */

export interface DesignOptionComparisonTableProps {
  comparison: DesignOptionComparisonResponse;
}

export function DesignOptionComparisonTable({
  comparison,
}: DesignOptionComparisonTableProps) {
  const { t } = useTranslation();
  const locale = getNumberLocale();

  const { options, by_trade, baseline_option_id, comparison_currency } = comparison;

  // Currency spread across the columns. A comparison that mixes currencies (or
  // whose columns differ from the set currency) cannot be read as directly
  // comparable, so we surface the same notice pattern as the cost-base compare.
  const currencies = useMemo(() => {
    const set = new Set<string>();
    for (const o of options) {
      const c = (o.currency || '').trim().toUpperCase();
      if (c) set.add(c);
    }
    if (comparison_currency) set.add(comparison_currency.trim().toUpperCase());
    return Array.from(set);
  }, [options, comparison_currency]);
  const mixedCurrency = currencies.length > 1;
  const dominantCurrency =
    (comparison_currency || options[0]?.currency || '').trim().toUpperCase();

  // The baseline column anchors the cost-per-area strip and the row deltas.
  const baselineColumn = useMemo(
    () =>
      options.find((o) => o.option_id === baseline_option_id) ?? options[0] ?? null,
    [options, baseline_option_id],
  );

  // Whether the set answers the programme and carbon questions at all. Rows for
  // a question nobody in the set has answered are worse than absent: a row of
  // dashes reads like a measurement that came back empty.
  const anyProgramme = useMemo(() => options.some((o) => o.has_programme), [options]);
  const anyCarbon = useMemo(() => options.some((o) => o.has_carbon), [options]);

  if (options.length === 0) {
    return (
      <EmptyState
        icon={<Scale size={28} strokeWidth={1.5} />}
        title={t('designOptions.compare.emptyTitle', {
          defaultValue: 'Nothing to compare yet',
        })}
        description={t('designOptions.compare.emptyDesc', {
          defaultValue:
            'Add at least two options, attach a model to each and generate their priced bills of quantities to see them side by side.',
        })}
      />
    );
  }

  const stickyCol =
    'sticky left-0 z-10 bg-surface-primary shadow-[2px_0_3px_-2px_rgba(0,0,0,0.1)]';

  const colFor = (row: TradeCells, optionId: string) =>
    row.per_option.find((p) => p.option_id === optionId) ?? null;

  return (
    <div className="space-y-4">
      <FairnessBanner
        status={comparison.fairness?.status ?? 'ok'}
        warnings={comparison.fairness?.warnings ?? []}
      />

      {mixedCurrency && (
        <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning/10 px-3 py-2 text-xs text-content-secondary">
          <AlertTriangle
            className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning"
            aria-hidden
          />
          <span>
            {t('designOptions.mixedCurrency', {
              defaultValue:
                'These options price in different currencies ({{list}}), so the totals are not directly comparable.',
              list: fmtList(currencies),
            })}
          </span>
        </div>
      )}

      <RecommendationBanner comparison={comparison} />

      <div className="overflow-x-auto relative rounded-lg border border-border-light">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-surface-primary">
            <tr className="border-b border-border-light">
              <th
                className={`whitespace-nowrap px-3 py-2.5 text-left font-semibold text-content-primary ${stickyCol} z-20`}
              >
                {t('designOptions.tradeHeader', { defaultValue: 'Trade / element' })}
              </th>
              {options.map((o) => {
                const isBaseline = o.option_id === baseline_option_id;
                return (
                  <th
                    key={o.option_id}
                    className="whitespace-nowrap px-3 py-2.5 text-right align-bottom font-semibold text-content-primary"
                  >
                    <div className="flex flex-col items-end gap-1">
                      <span className="flex items-center gap-1.5">
                        {isBaseline && (
                          <Badge variant="blue" size="sm">
                            {t('designOptions.baseline', { defaultValue: 'Baseline' })}
                          </Badge>
                        )}
                        {o.name}
                      </span>
                      <ValidationChip status={o.validation_status} />
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>

          <tbody>
            {by_trade.length === 0 ? (
              <tr>
                <td
                  colSpan={options.length + 1}
                  className="px-3 py-6 text-center text-sm text-content-tertiary"
                >
                  {t('designOptions.compare.noTradeRows', {
                    defaultValue:
                      'No trade breakdown yet. Generate the priced bills of quantities to see a by-trade split.',
                  })}
                </td>
              </tr>
            ) : (
              by_trade.map((row) => {
                const baselineCost = num(row.baseline_cost);
                const rowCosts = options.map((o) => num(colFor(row, o.option_id)?.cost));
                const sys = classificationLabel(row.classification_system);
                return (
                  <tr
                    key={row.key}
                    className="group border-b border-border-light/50 transition-colors hover:bg-surface-secondary/30"
                  >
                    <td
                      className={`px-3 py-2.5 ${stickyCol} z-20 group-hover:bg-surface-secondary/30`}
                    >
                      <span className="text-content-primary">
                        {t(`designOptions.trade.${row.key}`, { defaultValue: row.label || '-' })}
                      </span>
                      {sys && (
                        <span className="ml-2 text-xs text-content-tertiary">{sys}</span>
                      )}
                    </td>
                    {options.map((o) => {
                      const cell = colFor(row, o.option_id);
                      const cost = num(cell?.cost);
                      const isBaseline = o.option_id === baseline_option_id;
                      const flag = classifyCell(cost, rowCosts);
                      const flagCls =
                        flag === 'high'
                          ? 'bg-semantic-error-bg/50'
                          : flag === 'low'
                            ? 'bg-semantic-warning-bg/40'
                            : '';
                      const flagLabel =
                        flag === 'high'
                          ? t('designOptions.outlierHigh', {
                              defaultValue: 'Higher than the median for this trade',
                            })
                          : flag === 'low'
                            ? t('designOptions.outlierLow', {
                                defaultValue: 'Lower than the median for this trade',
                              })
                            : undefined;
                      const pct =
                        baselineCost > 0 ? ((cost - baselineCost) / baselineCost) * 100 : 0;
                      return (
                        <td
                          key={o.option_id}
                          className={`whitespace-nowrap px-3 py-2.5 text-right align-top tabular-nums ${flagCls}`}
                          title={flagLabel}
                          aria-label={flagLabel}
                        >
                          {cell ? (
                            <>
                              <span className="text-content-primary">
                                {formatMoney(cell.cost, o.currency)}
                              </span>
                              <div className="mt-0.5 flex items-center justify-end gap-1.5 text-2xs text-content-tertiary">
                                <span>{formatQty(cell.quantity, cell.unit)}</span>
                              </div>
                              {!isBaseline && baselineCost > 0 && (
                                <div className="mt-0.5 flex justify-end">
                                  <DeltaBadge pct={pct} />
                                </div>
                              )}
                            </>
                          ) : (
                            <span className="text-content-quaternary">-</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })
            )}
          </tbody>

          <tfoot>
            {/* Direct cost */}
            <tr className="border-t border-border-light bg-surface-secondary/20">
              <td className={`px-3 py-2 text-content-secondary ${stickyCol} z-20 bg-surface-secondary`}>
                {t('designOptions.directCost', { defaultValue: 'Direct cost' })}
              </td>
              {options.map((o) => (
                <td
                  key={o.option_id}
                  className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-content-secondary"
                >
                  {formatMoney(o.direct_cost, o.currency)}
                </td>
              ))}
            </tr>
            {/* Markups */}
            <tr className="bg-surface-secondary/20">
              <td className={`px-3 py-2 text-content-secondary ${stickyCol} z-20 bg-surface-secondary`}>
                {t('designOptions.markups', { defaultValue: 'Markups' })}
              </td>
              {options.map((o) => (
                <td
                  key={o.option_id}
                  className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-content-secondary"
                >
                  {formatMoney(o.markups_total, o.currency)}
                </td>
              ))}
            </tr>
            {/* Grand total */}
            <tr className="border-t-2 border-border bg-surface-secondary/40">
              <td
                className={`px-3 py-3 font-bold text-content-primary sticky left-0 z-20 bg-surface-secondary shadow-[2px_0_3px_-2px_rgba(0,0,0,0.1)]`}
              >
                {t('designOptions.total', { defaultValue: 'TOTAL' })}
              </td>
              {options.map((o) => {
                const isBaseline = o.option_id === baseline_option_id;
                return (
                  <td
                    key={o.option_id}
                    className="whitespace-nowrap px-3 py-3 text-right tabular-nums"
                  >
                    <span className="font-bold text-content-primary">
                      {formatMoney(o.grand_total, o.currency)}
                    </span>
                    {!isBaseline && (
                      <span className="ml-1.5 inline-block align-middle">
                        <DeltaBadge pct={num(o.delta_pct)} />
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
            {/* Cost per m2 */}
            <tr className="bg-surface-secondary/20">
              <td className={`px-3 py-2 text-content-tertiary ${stickyCol} z-20 bg-surface-secondary`}>
                {t('designOptions.costPerM2', { defaultValue: 'Cost per m2' })}
              </td>
              {options.map((o) => (
                <td
                  key={o.option_id}
                  className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-content-tertiary"
                >
                  {num(o.cost_per_m2) > 0 ? formatMoney(o.cost_per_m2, o.currency) : '-'}
                </td>
              ))}
            </tr>

            {/* Programme and carbon. The rows appear only when at least one
                option answers them: a set nobody has programmed would otherwise
                grow two rows of dashes that say nothing. A cell reads "-" when
                THAT option has no answer, which is not the same as zero and must
                never be rendered as one. */}
            {anyProgramme && (
              <>
                <tr className="border-t border-border-light bg-surface-secondary/20">
                  <td className={`px-3 py-2 text-content-tertiary ${stickyCol} z-20 bg-surface-secondary`}>
                    {t('designOptions.durationDays', { defaultValue: 'Duration (days)' })}
                  </td>
                  {options.map((o) => (
                    <td
                      key={o.option_id}
                      className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-content-tertiary"
                    >
                      {o.has_programme ? (
                        <>
                          {formatCount(o.duration_days)}
                          {o.delta_days_vs_baseline !== null &&
                            o.option_id !== baseline_option_id &&
                            num(o.delta_days_vs_baseline) !== 0 && (
                              <span className="ml-1.5 inline-block align-middle">
                                <DayDeltaBadge days={num(o.delta_days_vs_baseline)} />
                              </span>
                            )}
                        </>
                      ) : (
                        '-'
                      )}
                    </td>
                  ))}
                </tr>
                <tr className="bg-surface-secondary/20">
                  <td className={`px-3 py-2 text-content-tertiary ${stickyCol} z-20 bg-surface-secondary`}>
                    {t('designOptions.finishDate', { defaultValue: 'Finish date' })}
                  </td>
                  {options.map((o) => (
                    <td
                      key={o.option_id}
                      className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-content-tertiary"
                    >
                      {o.has_programme && o.finish_date ? o.finish_date : '-'}
                    </td>
                  ))}
                </tr>
              </>
            )}
            {anyCarbon && (
              <tr className="border-t border-border-light bg-surface-secondary/20">
                <td className={`px-3 py-2 text-content-tertiary ${stickyCol} z-20 bg-surface-secondary`}>
                  {t('designOptions.embodiedCarbon', { defaultValue: 'Embodied carbon A1-A5' })}
                </td>
                {options.map((o) => (
                  <td
                    key={o.option_id}
                    className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-content-tertiary"
                  >
                    {o.has_carbon ? formatQty(o.embodied_carbon_kg, o.carbon_unit || 'kgCO2e') : '-'}
                  </td>
                ))}
              </tr>
            )}
          </tfoot>
        </table>
      </div>

      {/* Cost-per-area benchmark for the baseline option, positioned against the
          tenant's own past projects. Self-hides when the option has no area. */}
      {baselineColumn && !mixedCurrency && (
        <CostPerAreaBenchmark
          directCost={num(baselineColumn.direct_cost)}
          currencyCode={dominantCurrency}
          grossFloorArea={num(baselineColumn.gfa) > 0 ? num(baselineColumn.gfa) : null}
          locale={locale}
        />
      )}
    </div>
  );
}

export default DesignOptionComparisonTable;
