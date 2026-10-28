// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Preview-only regional cost-index adjustment panel.  Lets the
// estimator see what a base rate would cost in another region/city
// without applying anything — feeds into the wider "Cost Intelligence"
// surface launched in v3.12.0.

import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { MapPin, Calculator, Info } from 'lucide-react';
import clsx from 'clsx';

import { Card } from '@/shared/ui';
import { previewRegionalAdjust, type RegionalAdjustResponse } from './api';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';

/** Seed regions populated by ``app.scripts.seed_regional_indices``.  Match
 *  the seed pipeline so the picker never points at an empty region. */
const SEED_REGIONS: Array<{ code: string; label: string; currency: string }> = [
  { code: 'DE_BERLIN', label: 'Berlin', currency: 'EUR' },
  { code: 'DE_MUNICH', label: 'Munich', currency: 'EUR' },
  { code: 'UK_LONDON', label: 'London', currency: 'GBP' },
  { code: 'UK_MANCHESTER', label: 'Manchester', currency: 'GBP' },
  { code: 'US_NYC', label: 'New York', currency: 'USD' },
  { code: 'US_LA', label: 'Los Angeles', currency: 'USD' },
  { code: 'FR_PARIS', label: 'Paris', currency: 'EUR' },
  { code: 'ES_MADRID', label: 'Madrid', currency: 'EUR' },
];

const CATEGORIES: Array<{ key: string; label: string }> = [
  { key: 'concrete', label: 'Concrete' },
  { key: 'steel', label: 'Steel' },
  { key: 'labor', label: 'Labor' },
  { key: 'mep', label: 'MEP' },
  { key: 'finishes', label: 'Finishes' },
  { key: 'sitework', label: 'Sitework' },
];

interface RegionalAdjustPanelProps {
  /** Optional seed base rate (e.g. the row the user just selected). */
  initialBaseRate?: number;
  /** Optional callback if the parent wants to act on the preview value. */
  onApplyPreview?: (preview: RegionalAdjustResponse) => void;
  className?: string;
}

export function RegionalAdjustPanel({
  initialBaseRate = 100,
  onApplyPreview,
  className,
}: RegionalAdjustPanelProps) {
  const { t } = useTranslation();
  const [region, setRegion] = useState<string>(SEED_REGIONS[1]!.code); // Munich default
  const [category, setCategory] = useState<string>(CATEGORIES[0]!.key);
  const [baseRate, setBaseRate] = useState<string>(String(initialBaseRate));

  const baseRateNum = useMemo(() => {
    const parsed = parseFloat(baseRate);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
  }, [baseRate]);

  const { data, isLoading, isError } = useQuery<RegionalAdjustResponse>({
    queryKey: ['costs', 'regional-adjust', region, category, baseRateNum],
    queryFn: () =>
      previewRegionalAdjust({
        region,
        category,
        baseRate: baseRateNum,
      }),
    staleTime: 30_000,
    enabled: Boolean(region && category) && baseRateNum >= 0,
  });

  const handleApply = useCallback(() => {
    if (data && onApplyPreview) onApplyPreview(data);
  }, [data, onApplyPreview]);

  const deltaPct = useMemo(() => {
    if (!data) return 0;
    // Money fields arrive as Decimal strings on the wire (DecimalMoney
    // serializer in backend/app/modules/costs/schemas.py), so coerce to
    // numbers before any arithmetic or .toFixed formatting.
    const base = Number(data.base_rate);
    const adjusted = Number(data.adjusted_rate);
    if (!base) return 0;
    return ((adjusted - base) / base) * 100;
  }, [data]);

  return (
    <Card className={clsx('p-4', className)}>
      <div className="flex items-center gap-2 mb-3">
        <MapPin size={16} className="text-oe-blue" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('costs.regional_adjust.title', { defaultValue: 'Regional Adjust' })}
        </h3>
        <span className="text-2xs text-content-tertiary">
          {t('costs.regional_adjust.subtitle', {
            defaultValue: 'Preview the same rate in a different region',
          })}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="block">
          <span className="block text-2xs font-medium text-content-secondary mb-1">
            {t('costs.regional_adjust.region', { defaultValue: 'Region' })}
          </span>
          <select
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            {SEED_REGIONS.map((r) => (
              <option key={r.code} value={r.code}>
                {r.label} ({r.currency})
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="block text-2xs font-medium text-content-secondary mb-1">
            {t('costs.regional_adjust.category', { defaultValue: 'Category' })}
          </span>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            {CATEGORIES.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="block text-2xs font-medium text-content-secondary mb-1">
            {t('costs.regional_adjust.base_rate', { defaultValue: 'Base rate' })}
          </span>
          <input
            type="number"
            min={0}
            step={0.01}
            value={baseRate}
            onChange={(e) => setBaseRate(e.target.value)}
            className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        </label>
      </div>

      <div className="mt-4 flex items-center justify-between rounded-md bg-surface-secondary/50 p-3">
        <div className="flex items-center gap-3">
          <Calculator size={20} className="text-oe-blue" />
          <div>
            <div className="text-2xs text-content-tertiary">
              {t('costs.regional_adjust.adjusted', { defaultValue: 'Adjusted rate' })}
            </div>
            <div className="text-lg font-semibold tabular-nums text-content-primary">
              {isLoading
                ? '…'
                : isError || !data
                  ? '—'
                  : fmtFixed(Number(data.adjusted_rate), 2)}
            </div>
          </div>
        </div>

        {data && (
          <div className="text-right">
            <div className="text-2xs text-content-tertiary">
              {t('costs.regional_adjust.factor', { defaultValue: 'Factor' })}
              {' × '}
              <span className="font-mono tabular-nums">{fmtFixed(Number(data.factor_applied), 4)}</span>
            </div>
            <div
              className={clsx(
                'text-xs tabular-nums',
                deltaPct > 0
                  ? 'text-semantic-error'
                  : deltaPct < 0
                    ? 'text-semantic-success'
                    : 'text-content-tertiary',
              )}
            >
              {deltaPct >= 0 ? '+' : ''}
              {fmtPercent(deltaPct)}
            </div>
          </div>
        )}
      </div>

      {data && (
        <div className="mt-2 flex items-center gap-1.5 text-2xs text-content-tertiary">
          <Info size={11} />
          <span>
            {data.source === 'baseline'
              ? t('costs.regional_adjust.no_index', {
                  defaultValue:
                    'No index on file for this region - passthrough (factor 1.0).',
                })
              : t('costs.regional_adjust.source_line', {
                  defaultValue: 'Source: {{source}} · effective {{date}}',
                  source: data.source,
                  date: data.effective_date ?? '—',
                })}
          </span>
        </div>
      )}

      {onApplyPreview && (
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={handleApply}
            disabled={!data || isLoading}
            className="rounded-md bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('costs.regional_adjust.apply', { defaultValue: 'Use this rate' })}
          </button>
        </div>
      )}
    </Card>
  );
}
