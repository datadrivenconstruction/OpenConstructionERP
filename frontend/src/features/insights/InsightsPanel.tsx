// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The Insights panel a module embeds under its header. It renders the module's
 * built-in KPIs and charts and lets the user add their own from the same data,
 * all client-side off the rows the module already loaded - no extra request.
 * The page owns the open/hide state (see useModuleInsights) and passes it in so
 * the header toggle and this panel stay in lock-step.
 */
import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BarChart3, ChevronUp, FlaskConical, Plus } from 'lucide-react';
import { Button } from '@/shared/ui';
import { computeKpi, measureFormat } from './aggregate';
import { KpiTile } from './charts';
import { CardControls, InsightCard } from './InsightCard';
import { InsightBuilder } from './InsightBuilder';
import type { InsightDataset, InsightDef } from './types';

interface InsightsPanelProps {
  open: boolean;
  title?: string;
  subtitle?: string;
  datasets: InsightDataset[];
  builtins: InsightDef[];
  custom: InsightDef[];
  onAdd: (def: InsightDef) => void;
  onUpdate: (def: InsightDef) => void;
  onRemove: (id: string) => void;
  /**
   * Closes the panel. Required rather than optional so the compiler, not a
   * reviewer's eye, guarantees every module offers the footer control: a page
   * that forgets it would look finished and quietly lack the affordance.
   */
  onCollapse: () => void;
}

export function InsightsPanel({
  open,
  title,
  subtitle,
  datasets,
  builtins,
  custom,
  onAdd,
  onUpdate,
  onRemove,
  onCollapse,
}: InsightsPanelProps) {
  const { t } = useTranslation();
  const [building, setBuilding] = useState(false);
  const [editing, setEditing] = useState<InsightDef | null>(null);
  const sectionRef = useRef<HTMLElement>(null);

  const dsMap = useMemo(() => {
    const m: Record<string, InsightDataset> = {};
    for (const d of datasets) m[d.id] = d;
    return m;
  }, [datasets]);

  const all = useMemo(() => [...builtins, ...custom], [builtins, custom]);
  const kpis = all.filter((d) => d.chart === 'kpi');
  const charts = all.filter((d) => d.chart !== 'kpi');
  // Only rows that are genuinely the user's own count as something to draw.
  // A dataset flagged `sample` is illustrative, and a panel full of invented
  // figures reads as if the project already held that work. We would rather
  // show nothing: an empty register is a fact about the project, whereas a
  // fabricated chart is a claim nobody can act on.
  const real = useMemo(
    () => datasets.filter((d) => !d.sample && d.rows.length > 0),
    [datasets],
  );
  const hasData = real.length > 0;

  if (!open) return null;

  const openEditor = (def: InsightDef) => {
    setEditing(def);
    setBuilding(true);
  };
  const closeEditor = () => {
    setBuilding(false);
    setEditing(null);
  };
  const save = (def: InsightDef) => {
    if (editing && !editing.builtin) onUpdate(def);
    else onAdd(def);
  };

  const collapse = () => {
    // The control that brings the panel back sits in the page header, above
    // this section. A reader who scrolled down through tall charts would lose
    // both the panel and every visible way to restore it in the same click, so
    // pull the top edge back into view first. When the panel is already on
    // screen this does nothing, which is why it is a condition and not a
    // scroll: aligning unconditionally would push that same header out of view.
    const el = sectionRef.current;
    if (el && el.getBoundingClientRect().top < 0) el.scrollIntoView({ block: 'start' });
    onCollapse();
  };

  return (
    <section
      ref={sectionRef}
      className="animate-fade-in overflow-hidden rounded-2xl border border-border-light bg-surface-secondary/30"
      aria-label={title ?? t('insights.toggle', { defaultValue: 'Insights' })}
    >
      {/* Header strip */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-light bg-surface-primary/60 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
            <BarChart3 size={16} />
          </span>
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
              {title ?? t('insights.toggle', { defaultValue: 'Insights' })}
            </h2>
            <p className="truncate text-xs text-content-tertiary">
              {subtitle ??
                t('insights.subtitle', {
                  defaultValue: 'Live charts from this module. Build your own and hide the panel any time.',
                })}
            </p>
          </div>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={() => {
            setEditing(null);
            setBuilding(true);
          }}
          disabled={!hasData}
        >
          {t('insights.new_chart', { defaultValue: 'New chart' })}
        </Button>
      </div>

      <div className="space-y-4 p-4">
        {/* No records in this module yet, so there is nothing honest to draw. */}
        {!hasData && (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <FlaskConical size={26} className="text-content-tertiary" strokeWidth={1.5} />
            <p className="text-sm text-content-secondary">
              {t('insights.no_data_title', { defaultValue: 'No data to chart yet' })}
            </p>
            <p className="max-w-sm text-xs text-content-tertiary">
              {t('insights.no_data_desc', {
                defaultValue:
                  'Charts appear here as soon as this module holds records. Until then the panel stays empty rather than showing made-up figures.',
              })}
            </p>
          </div>
        )}

        {/* KPI row */}
        {hasData && kpis.length > 0 && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {kpis.map((def) => {
              const ds = dsMap[def.datasetId];
              return (
                <div key={def.id} className="group relative">
                  <KpiTile
                    label={def.title}
                    value={ds ? computeKpi(ds, def) : 0}
                    format={ds ? measureFormat(ds, def) : 'number'}
                    currency={ds?.currency}
                    color={def.color ?? 0}
                  />
                  {!def.builtin && (
                    <div className="absolute right-1.5 top-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                      <CardControls onEdit={() => openEditor(def)} onRemove={() => onRemove(def.id)} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Chart grid */}
        {hasData && charts.length > 0 && (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {charts.map((def) => (
              <InsightCard
                key={def.id}
                def={def}
                dataset={dsMap[def.datasetId]}
                onEdit={def.builtin ? undefined : () => openEditor(def)}
                onRemove={def.builtin ? undefined : () => onRemove(def.id)}
              />
            ))}
          </div>
        )}

        {/* There is data, but the user has removed every chart. */}
        {hasData && all.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <BarChart3 size={26} className="text-content-tertiary" strokeWidth={1.5} />
            <p className="text-sm text-content-secondary">
              {t('insights.empty_title', { defaultValue: 'No charts yet' })}
            </p>
            <p className="max-w-sm text-xs text-content-tertiary">
              {t('insights.empty_desc', {
                defaultValue: 'Add a chart to visualise this module. You can build as many as you like.',
              })}
            </p>
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setBuilding(true)}
              disabled={datasets.length === 0}
              className="mt-1"
            >
              {t('insights.new_chart', { defaultValue: 'New chart' })}
            </Button>
          </div>
        )}
      </div>

      {/* Footer strip. Full width so it reads as the bottom edge of the block
          rather than one more control competing with the charts, and it is the
          same action as the header toggle so the two can never disagree. */}
      <button
        type="button"
        onClick={collapse}
        aria-expanded
        className="group flex w-full items-center justify-center gap-2 border-t border-border-light bg-surface-primary/50 px-4 py-2.5 text-xs font-medium text-content-tertiary transition-colors hover:bg-surface-secondary/70 hover:text-content-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-oe-blue/40"
      >
        <ChevronUp
          size={14}
          className="transition-transform duration-200 group-hover:-translate-y-0.5"
        />
        {t('insights.collapse', { defaultValue: 'Collapse insights' })}
      </button>

      {building && datasets.length > 0 && (
        <InsightBuilder
          datasets={datasets}
          initial={editing}
          nextColor={(all.length % 7) + 1}
          onSave={save}
          onClose={closeEditor}
        />
      )}
    </section>
  );
}
