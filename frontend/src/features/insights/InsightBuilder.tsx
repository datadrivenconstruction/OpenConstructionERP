// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Create your own" chart. A compact form - chart type, dataset, what to
 * measure, how to group and how to aggregate - with a live preview so the user
 * sees the result before saving. Produces a plain {@link InsightDef} the panel
 * stores; nothing here is module-specific, so the same builder serves every
 * module that embeds the panel.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { computeKpi } from './aggregate';
import { KpiTile } from './charts';
import { CHART_META, InsightCard } from './InsightCard';
import { newInsightId } from './useModuleInsights';
import type { Aggregation, ChartKind, InsightDataset, InsightDef } from './types';

const CHART_ORDER: ChartKind[] = ['kpi', 'bar', 'donut', 'line', 'area'];
const AGG_ORDER: Aggregation[] = ['count', 'sum', 'avg', 'min', 'max'];

interface InsightBuilderProps {
  datasets: InsightDataset[];
  initial?: InsightDef | null;
  nextColor?: number;
  onSave: (def: InsightDef) => void;
  onClose: () => void;
}

export function InsightBuilder({ datasets, initial, nextColor = 1, onSave, onClose }: InsightBuilderProps) {
  const { t } = useTranslation();

  const first = datasets[0];
  const seedDataset = datasets.find((d) => d.id === initial?.datasetId) ?? first;
  const seedDims = seedDataset?.fields.filter((f) => f.kind === 'dimension') ?? [];
  const seedMeasures = seedDataset?.fields.filter((f) => f.kind === 'measure') ?? [];

  const [chart, setChart] = useState<ChartKind>(initial?.chart ?? 'bar');
  const [datasetId, setDatasetId] = useState<string>(seedDataset?.id ?? '');
  const [dimension, setDimension] = useState<string>(initial?.dimension ?? seedDims[0]?.key ?? '');
  const [measure, setMeasure] = useState<string>(initial?.measure ?? seedMeasures[0]?.key ?? '');
  const [agg, setAgg] = useState<Aggregation>(initial?.agg ?? 'sum');
  const [title, setTitle] = useState<string>(initial?.title ?? '');

  const dataset = useMemo(() => datasets.find((d) => d.id === datasetId) ?? first, [datasets, datasetId, first]);
  const dims = dataset?.fields.filter((f) => f.kind === 'dimension') ?? [];
  const measures = dataset?.fields.filter((f) => f.kind === 'measure') ?? [];

  const aggLabel = (a: Aggregation) =>
    ({
      count: t('insights.agg_count', { defaultValue: 'Count' }),
      sum: t('insights.agg_sum', { defaultValue: 'Sum' }),
      avg: t('insights.agg_avg', { defaultValue: 'Average' }),
      min: t('insights.agg_min', { defaultValue: 'Min' }),
      max: t('insights.agg_max', { defaultValue: 'Max' }),
    })[a];

  // A readable default title from the current selection - used until the user
  // types their own.
  const autoTitle = useMemo(() => {
    const m = measures.find((f) => f.key === measure);
    const d = dims.find((f) => f.key === dimension);
    const measurePart = agg === 'count' ? t('insights.agg_count', { defaultValue: 'Count' }) : `${aggLabel(agg)} ${m?.label ?? ''}`.trim();
    if (chart === 'kpi' || !d) return measurePart;
    return t('insights.by_join', { defaultValue: '{{measure}} by {{dimension}}', measure: measurePart, dimension: d.label });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agg, measure, dimension, chart, measures, dims, t]);

  const draft: InsightDef = {
    id: initial?.id ?? 'preview',
    title: (title.trim() || autoTitle) as string,
    datasetId: dataset?.id ?? '',
    chart,
    dimension: chart === 'kpi' ? undefined : dimension || undefined,
    measure: agg === 'count' ? measure || undefined : measure || undefined,
    agg,
    color: initial?.color ?? nextColor,
    builtin: false,
  };

  const measureNeeded = agg !== 'count';
  const dimensionNeeded = chart !== 'kpi';
  const valid =
    !!dataset &&
    (!measureNeeded || !!measure) &&
    (!dimensionNeeded || !!dimension) &&
    (draft.title?.length ?? 0) > 0;

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
  const labelCls = 'mb-1 block text-2xs font-medium uppercase tracking-wider text-content-tertiary';

  const save = () => {
    if (!valid) return;
    onSave({ ...draft, id: initial?.id ?? newInsightId() });
    onClose();
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={
        initial
          ? t('insights.edit_title', { defaultValue: 'Edit chart' })
          : t('insights.new_title', { defaultValue: 'New chart' })
      }
      subtitle={t('insights.builder_subtitle', {
        defaultValue: 'Pick what to measure and how to show it. The preview updates as you choose.',
      })}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" disabled={!valid} onClick={save}>
            {initial
              ? t('common.save', { defaultValue: 'Save' })
              : t('insights.add_chart', { defaultValue: 'Add chart' })}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* Controls */}
        <div className="space-y-4">
          {/* Chart type - segmented */}
          <div>
            <span className={labelCls}>{t('insights.chart_type', { defaultValue: 'Chart type' })}</span>
            <div className="grid grid-cols-5 gap-1.5">
              {CHART_ORDER.map((k) => {
                const Icon = CHART_META[k].icon;
                const active = chart === k;
                return (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setChart(k)}
                    className={`flex flex-col items-center gap-1 rounded-lg border px-1 py-2 text-2xs transition-all ${
                      active
                        ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                        : 'border-border-light text-content-tertiary hover:border-content-tertiary hover:text-content-secondary'
                    }`}
                    aria-pressed={active}
                  >
                    <Icon size={16} />
                    {t(CHART_META[k].labelKey, { defaultValue: CHART_META[k].labelDefault })}
                  </button>
                );
              })}
            </div>
          </div>

          {datasets.length > 1 && (
            <div>
              <label className={labelCls}>{t('insights.dataset', { defaultValue: 'Data' })}</label>
              <select className={fieldCls} value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>{t('insights.measure', { defaultValue: 'Measure' })}</label>
              <select
                className={fieldCls}
                value={measure}
                onChange={(e) => setMeasure(e.target.value)}
                disabled={measures.length === 0}
              >
                {agg === 'count' && <option value="">{t('insights.rows', { defaultValue: 'Rows' })}</option>}
                {measures.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>{t('insights.aggregation', { defaultValue: 'Aggregate' })}</label>
              <select className={fieldCls} value={agg} onChange={(e) => setAgg(e.target.value as Aggregation)}>
                {AGG_ORDER.map((a) => (
                  <option key={a} value={a}>
                    {aggLabel(a)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className={chart === 'kpi' ? 'opacity-40' : ''}>
            <label className={labelCls}>{t('insights.group_by', { defaultValue: 'Group by' })}</label>
            <select
              className={fieldCls}
              value={dimension}
              onChange={(e) => setDimension(e.target.value)}
              disabled={chart === 'kpi' || dims.length === 0}
            >
              {dims.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className={labelCls}>{t('insights.title', { defaultValue: 'Title' })}</label>
            <input
              className={fieldCls}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={autoTitle}
            />
          </div>
        </div>

        {/* Live preview */}
        <div>
          <span className={labelCls}>{t('insights.preview', { defaultValue: 'Preview' })}</span>
          <div className="rounded-xl border border-dashed border-border bg-surface-secondary/40 p-3">
            {chart === 'kpi' ? (
              <KpiTile
                label={draft.title || t('insights.preview', { defaultValue: 'Preview' })}
                value={dataset ? computeKpi(dataset, draft) : 0}
                format={dataset?.fields.find((f) => f.key === measure)?.format ?? 'number'}
                currency={dataset?.currency}
                color={draft.color ?? 1}
                caption={agg === 'count' ? t('insights.rows', { defaultValue: 'Rows' }) : undefined}
              />
            ) : (
              <InsightCard def={draft} dataset={dataset} />
            )}
          </div>
        </div>
      </div>
    </WideModal>
  );
}
