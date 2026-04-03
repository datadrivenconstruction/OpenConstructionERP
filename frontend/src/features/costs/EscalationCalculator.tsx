import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { TrendingUp, Calculator, Info } from 'lucide-react';
import clsx from 'clsx';

/* ── Published construction cost indices (annual % change) ────────────── */

/** Regional escalation index data (average annual % change by period).
 *  Sources: BKI (DE), BCIS (UK), ENR (US), Eurostat (EU).
 *  These are representative averages — actual project indices may differ. */
const ESCALATION_INDICES: Record<string, { label: string; rates: Record<string, number> }> = {
  DE: {
    label: 'Germany (BKI)',
    rates: { '2020': 3.2, '2021': 5.1, '2022': 14.6, '2023': 7.8, '2024': 4.2, '2025': 3.5, '2026': 3.0 },
  },
  AT: {
    label: 'Austria',
    rates: { '2020': 2.8, '2021': 4.9, '2022': 12.3, '2023': 6.5, '2024': 3.8, '2025': 3.2, '2026': 2.8 },
  },
  CH: {
    label: 'Switzerland',
    rates: { '2020': 1.5, '2021': 2.8, '2022': 6.2, '2023': 3.4, '2024': 2.5, '2025': 2.0, '2026': 1.8 },
  },
  UK: {
    label: 'United Kingdom (BCIS)',
    rates: { '2020': 2.0, '2021': 8.5, '2022': 10.2, '2023': 4.8, '2024': 3.5, '2025': 3.0, '2026': 2.8 },
  },
  US: {
    label: 'United States (ENR)',
    rates: { '2020': 1.2, '2021': 6.3, '2022': 11.5, '2023': 3.2, '2024': 2.8, '2025': 2.5, '2026': 2.3 },
  },
  EU: {
    label: 'EU Average',
    rates: { '2020': 2.5, '2021': 5.8, '2022': 11.0, '2023': 6.0, '2024': 3.5, '2025': 3.0, '2026': 2.5 },
  },
};

const YEARS = Array.from({ length: 11 }, (_, i) => 2020 + i); // 2020-2030

interface EscalationCalculatorProps {
  /** Base amount to escalate */
  baseAmount?: number;
  /** Callback when escalated amount is computed */
  onApply?: (escalatedAmount: number, factor: number) => void;
  className?: string;
}

export function EscalationCalculator({
  baseAmount: propBaseAmount,
  onApply,
  className,
}: EscalationCalculatorProps) {
  const { t } = useTranslation();
  const [region, setRegion] = useState('DE');
  const [baseYear, setBaseYear] = useState(2023);
  const [targetYear, setTargetYear] = useState(2026);
  const [manualRate, setManualRate] = useState<string>('');
  const [useManual, setUseManual] = useState(false);
  const [amount, setAmount] = useState(propBaseAmount?.toString() || '100000');

  const baseAmountNum = useMemo(() => parseFloat(amount) || 0, [amount]);

  /** Calculate compound escalation factor between base and target year. */
  const escalation = useMemo(() => {
    if (baseYear >= targetYear) {
      return { factor: 1, yearlyRates: [] as { year: number; rate: number }[] };
    }

    const regionData = ESCALATION_INDICES[region];
    const yearlyRates: { year: number; rate: number }[] = [];
    let factor = 1;

    for (let y = baseYear; y < targetYear; y++) {
      const yearKey = String(y);
      let rate: number;

      if (useManual && manualRate) {
        rate = parseFloat(manualRate) || 0;
      } else {
        // Use published rate if available, else use last known rate
        rate = regionData?.rates[yearKey] ?? regionData?.rates[String(Math.min(y, 2026))] ?? 3.0;
      }

      factor *= 1 + rate / 100;
      yearlyRates.push({ year: y, rate });
    }

    return { factor, yearlyRates };
  }, [baseYear, targetYear, region, useManual, manualRate]);

  const escalatedAmount = useMemo(
    () => Math.round(baseAmountNum * escalation.factor * 100) / 100,
    [baseAmountNum, escalation.factor],
  );

  const totalPctChange = useMemo(
    () => ((escalation.factor - 1) * 100).toFixed(1),
    [escalation.factor],
  );

  const fmt = useMemo(
    () => new Intl.NumberFormat(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
    [],
  );

  const handleApply = useCallback(() => {
    onApply?.(escalatedAmount, escalation.factor);
  }, [onApply, escalatedAmount, escalation.factor]);

  return (
    <div className={clsx('rounded-xl border border-border bg-surface-primary p-5', className)}>
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-100 dark:bg-amber-900/30">
          <TrendingUp size={16} className="text-amber-600" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('costs.escalation_calculator', { defaultValue: 'Cost Escalation Calculator' })}
          </h3>
          <p className="text-2xs text-content-tertiary">
            {t('costs.escalation_desc', {
              defaultValue: 'Adjust costs for inflation using published construction indices',
            })}
          </p>
        </div>
      </div>

      {/* Controls */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        {/* Region */}
        <div>
          <label className="block text-2xs font-medium text-content-secondary mb-1">
            {t('common.region', { defaultValue: 'Region' })}
          </label>
          <select
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            className="w-full h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            {Object.entries(ESCALATION_INDICES).map(([key, val]) => (
              <option key={key} value={key}>
                {val.label}
              </option>
            ))}
          </select>
        </div>

        {/* Base year */}
        <div>
          <label className="block text-2xs font-medium text-content-secondary mb-1">
            {t('costs.base_year', { defaultValue: 'Base year' })}
          </label>
          <select
            value={baseYear}
            onChange={(e) => setBaseYear(Number(e.target.value))}
            className="w-full h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            {YEARS.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>

        {/* Target year */}
        <div>
          <label className="block text-2xs font-medium text-content-secondary mb-1">
            {t('costs.target_year', { defaultValue: 'Target year' })}
          </label>
          <select
            value={targetYear}
            onChange={(e) => setTargetYear(Number(e.target.value))}
            className="w-full h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            {YEARS.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>

        {/* Amount */}
        <div>
          <label className="block text-2xs font-medium text-content-secondary mb-1">
            {t('costs.base_amount', { defaultValue: 'Base amount' })}
          </label>
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-full h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        </div>
      </div>

      {/* Manual rate override */}
      <div className="flex items-center gap-3 mb-4 p-2 rounded-lg bg-surface-secondary/50">
        <label className="flex items-center gap-2 text-xs text-content-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={useManual}
            onChange={(e) => setUseManual(e.target.checked)}
            className="rounded border-border text-oe-blue focus:ring-oe-blue/30"
          />
          {t('costs.manual_rate', { defaultValue: 'Manual rate (% p.a.)' })}
        </label>
        {useManual && (
          <input
            type="number"
            step="0.1"
            value={manualRate}
            onChange={(e) => setManualRate(e.target.value)}
            placeholder="5.0"
            className="w-20 h-7 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        )}
      </div>

      {/* Year-by-year breakdown */}
      {escalation.yearlyRates.length > 0 && (
        <div className="mb-4">
          <div className="flex items-center gap-1.5 mb-2">
            <span className="text-2xs font-medium text-content-secondary uppercase tracking-wide">
              {t('costs.yearly_breakdown', { defaultValue: 'Year-by-year breakdown' })}
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {escalation.yearlyRates.map(({ year, rate }) => (
              <div
                key={year}
                className="flex items-center gap-1 rounded-md bg-surface-secondary px-2 py-1"
              >
                <span className="text-2xs text-content-tertiary">{year}</span>
                <span className="text-2xs font-medium text-amber-600">+{rate.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Result */}
      <div className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50/50 dark:bg-amber-900/10 p-4">
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-2xs text-content-tertiary mb-0.5">
              {t('costs.base_cost', { defaultValue: 'Base cost' })} ({baseYear})
            </p>
            <p className="text-sm font-semibold text-content-primary tabular-nums">
              {fmt.format(baseAmountNum)}
            </p>
          </div>
          <div className="text-center">
            <p className="text-2xs text-content-tertiary mb-0.5">
              {t('costs.escalation_factor', { defaultValue: 'Factor' })}
            </p>
            <p className="text-sm font-semibold text-amber-600 tabular-nums">
              {escalation.factor.toFixed(4)}x
              <span className="text-2xs ml-1">(+{totalPctChange}%)</span>
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xs text-content-tertiary mb-0.5">
              {t('costs.escalated_cost', { defaultValue: 'Escalated cost' })} ({targetYear})
            </p>
            <p className="text-sm font-bold text-content-primary tabular-nums">
              {fmt.format(escalatedAmount)}
            </p>
          </div>
        </div>
      </div>

      {/* Info + Apply */}
      <div className="flex items-center justify-between mt-3">
        <div className="flex items-center gap-1 text-2xs text-content-tertiary">
          <Info size={11} />
          <span>
            {t('costs.escalation_disclaimer', {
              defaultValue: 'Based on published indices. Verify with project-specific data.',
            })}
          </span>
        </div>
        {onApply && (
          <button
            onClick={handleApply}
            disabled={baseYear >= targetYear}
            className="flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50 transition-colors"
          >
            <Calculator size={13} />
            {t('costs.apply_escalation', { defaultValue: 'Apply' })}
          </button>
        )}
      </div>
    </div>
  );
}
