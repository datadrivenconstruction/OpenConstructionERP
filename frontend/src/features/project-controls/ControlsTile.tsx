// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';

import type { ControlsKPI } from './api';
import { formatControlsValue, kpiCurrency, statusClasses } from './format';
import { MultiCurrencyBadge } from './MultiCurrencyBadge';

/**
 * One KPI tile: label, formatted value, traffic-light status, source record
 * count, and (for money KPIs) a per-currency breakdown. Clicking opens the
 * drill drawer for the KPI.
 */
export function ControlsTile({
  kpi,
  onDrill,
}: {
  kpi: ControlsKPI;
  onDrill: (kpi: ControlsKPI) => void;
}) {
  const { t } = useTranslation();
  const colours = statusClasses(kpi.status);
  const currency = kpiCurrency(kpi.breakdown);
  const hasData = kpi.source_record_count > 0;

  return (
    <button
      type="button"
      onClick={() => onDrill(kpi)}
      aria-label={`${kpi.label}: ${kpi.value} ${kpi.unit}`}
      className={clsx(
        'flex w-full flex-col rounded-lg border border-l-4 bg-surface-secondary p-3 text-left transition',
        'border-border-subtle hover:border-border-strong hover:bg-surface-tertiary',
        colours.border,
        'focus:outline-none focus:ring-2 focus:ring-accent/40',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-content-secondary">
          {kpi.label}
        </span>
        <span
          className={clsx('mt-1 h-2.5 w-2.5 shrink-0 rounded-full', colours.dot)}
          aria-hidden
        />
      </div>
      <span
        className={clsx(
          'mt-1 text-xl font-semibold tabular-nums',
          hasData ? colours.text : 'text-content-tertiary',
        )}
      >
        {hasData ? formatControlsValue(kpi.value, kpi.unit, currency) : '—'}
      </span>
      <span className="mt-0.5 text-2xs text-content-tertiary">
        {hasData
          ? t('controls.source_records', {
              defaultValue: '{{count}} record',
              defaultValue_other: '{{count}} records',
              count: kpi.source_record_count,
            })
          : t('controls.no_data', { defaultValue: 'no data' })}
      </span>
      {kpi.unit === 'currency' && (
        <MultiCurrencyBadge breakdown={kpi.breakdown} unit={kpi.unit} />
      )}
    </button>
  );
}
