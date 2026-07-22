// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Estimate rollup card.
 *
 * A compact, read-only headline of the whole estimate: the measured-works BOQ
 * base, plus the preliminaries total, plus the allowances still carried, summed
 * into one estimate total. The component lines come straight from the backend
 * and always sum exactly to the total, so this only formats and localises them.
 *
 * It is deliberately unobtrusive: it renders nothing while loading, on error, or
 * when the project has nothing to roll up yet, so it can sit at the top of the
 * preliminaries and allowances pages without getting in the way of a fresh
 * project or a user who lacks read access to the rollup.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Calculator, Info } from 'lucide-react';
import { Card } from '@/shared/ui';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { fetchEstimateRollup, type RollupLine } from './api';

/** English fallbacks for the four known line keys (localised off the key). */
const LINE_LABEL_FALLBACK: Record<string, string> = {
  boq_base: 'BOQ base',
  preliminaries: 'Preliminaries',
  allowances: 'Provisional and prime-cost sums',
  contingency: 'Contingency',
};

export function EstimateRollupCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  const { data, isError } = useQuery({
    queryKey: ['estimate-rollup', projectId],
    queryFn: () => fetchEstimateRollup(projectId),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  // Stay out of the way: nothing while loading, on error (e.g. no read access),
  // or before there is any figure to compose.
  if (isError || !data) return null;

  const hasAnything =
    toNum(data.estimate_total) !== 0 ||
    toNum(data.boq_base) !== 0 ||
    data.preliminaries.item_count > 0 ||
    data.allowances.allowance_count > 0;
  if (!hasAnything) return null;

  const currency = data.base_currency;
  const lineLabel = (line: RollupLine): string =>
    t(`estimate_rollup.line_${line.key}`, {
      defaultValue: LINE_LABEL_FALLBACK[line.key] ?? line.label,
    });

  return (
    <Card padding="md">
      <div className="mb-3 flex items-center gap-2">
        <Calculator size={16} className="shrink-0 text-oe-blue" />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('estimate_rollup.title', { defaultValue: 'Estimate rollup' })}
          </h2>
          <p className="text-2xs text-content-tertiary">
            {t('estimate_rollup.subtitle', {
              defaultValue: 'Measured works plus preliminaries and the allowances still carried.',
            })}
          </p>
        </div>
      </div>

      <dl className="divide-y divide-border-light">
        {data.lines.map((line) => (
          <div key={line.key} className="flex items-center justify-between gap-4 py-1.5">
            <dt className="text-sm text-content-secondary">{lineLabel(line)}</dt>
            <dd className="text-sm tabular-nums text-content-primary">
              {formatCurrency(line.amount, currency)}
            </dd>
          </div>
        ))}
        <div className="flex items-center justify-between gap-4 pt-2.5">
          <dt className="text-sm font-semibold text-content-primary">
            {t('estimate_rollup.total', { defaultValue: 'Estimate total' })}
          </dt>
          <dd className="text-lg font-bold tabular-nums text-content-primary">
            {formatCurrency(data.estimate_total, currency)}
          </dd>
        </div>
      </dl>

      {data.allowances.unconverted_currencies.length > 0 && (
        <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-amber-50 p-2 text-2xs text-amber-700 dark:bg-amber-950/30 dark:text-amber-400">
          <Info size={12} className="mt-0.5 shrink-0" />
          <span>
            {t('estimate_rollup.unconverted_note', {
              defaultValue:
                'Allowances in a currency with no exchange rate are added in their own units.',
            })}{' '}
            {data.allowances.unconverted_currencies.join(', ')}
          </span>
        </p>
      )}
    </Card>
  );
}

export default EstimateRollupCard;
