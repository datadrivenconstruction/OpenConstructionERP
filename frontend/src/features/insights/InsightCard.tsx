// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One chart in the Insights grid: a titled card that resolves its dataset,
 * aggregates the series and draws it. Built-in cards are read-only; a card the
 * user built shows edit and remove controls.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { BarChart3, Gauge, LineChart, Pencil, PieChart, TrendingUp, X, type LucideIcon } from 'lucide-react';
import { computeSeries, measureFormat } from './aggregate';
import { SeriesChart } from './charts';
import type { ChartKind, InsightDataset, InsightDef } from './types';

export const CHART_META: Record<ChartKind, { icon: LucideIcon; labelKey: string; labelDefault: string }> = {
  kpi: { icon: Gauge, labelKey: 'insights.chart_kpi', labelDefault: 'Number' },
  bar: { icon: BarChart3, labelKey: 'insights.chart_bar', labelDefault: 'Bar' },
  line: { icon: LineChart, labelKey: 'insights.chart_line', labelDefault: 'Line' },
  area: { icon: TrendingUp, labelKey: 'insights.chart_area', labelDefault: 'Area' },
  donut: { icon: PieChart, labelKey: 'insights.chart_donut', labelDefault: 'Donut' },
};

export function CardControls({ onEdit, onRemove }: { onEdit?: () => void; onRemove?: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-0.5">
      {onEdit && (
        <button
          type="button"
          onClick={onEdit}
          aria-label={t('insights.edit_chart', { defaultValue: 'Edit chart' })}
          title={t('insights.edit_chart', { defaultValue: 'Edit chart' })}
          className="rounded-md p-1 text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-oe-blue"
        >
          <Pencil size={13} />
        </button>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={t('insights.remove_chart', { defaultValue: 'Remove chart' })}
          title={t('insights.remove_chart', { defaultValue: 'Remove chart' })}
          className="rounded-md p-1 text-content-tertiary transition-colors hover:bg-semantic-error-bg/40 hover:text-semantic-error"
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
}

interface InsightCardProps {
  def: InsightDef;
  dataset?: InsightDataset;
  onEdit?: () => void;
  onRemove?: () => void;
}

export function InsightCard({ def, dataset, onEdit, onRemove }: InsightCardProps) {
  const { t } = useTranslation();
  const Icon = CHART_META[def.chart]?.icon ?? BarChart3;

  const points = useMemo(
    () => (dataset ? computeSeries(dataset, def, t('insights.other', { defaultValue: 'Other' })) : []),
    [dataset, def, t],
  );
  const format = dataset ? measureFormat(dataset, def) : 'number';

  return (
    <div className="flex flex-col rounded-xl border border-border-light bg-surface-primary p-3">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <Icon size={14} className="shrink-0 text-content-tertiary" />
          <span className="truncate text-xs font-semibold text-content-primary" title={def.title}>
            {def.title}
          </span>
        </div>
        {(onEdit || onRemove) && <CardControls onEdit={onEdit} onRemove={onRemove} />}
      </div>
      <SeriesChart
        points={points}
        kind={def.chart === 'kpi' ? 'bar' : def.chart}
        color={def.color ?? 0}
        format={format}
        currency={dataset?.currency}
      />
    </div>
  );
}
