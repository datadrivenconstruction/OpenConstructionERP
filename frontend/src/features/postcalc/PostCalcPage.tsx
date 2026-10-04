// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Post-calculation (Nachkalkulation): where the job beat the estimate and where
 * it lost.
 *
 * The module reconciles the estimate against what the site actually did, and it
 * shipped with an API and no page at all while the module catalogue advertised
 * the capability to users. This is that page.
 *
 * It is built around one question a foreman or a quantity surveyor asks per
 * position: how much did we install, how many hours did that take against the
 * norm the estimate priced, and what did the material cost against what the
 * estimate allowed for the quantity installed. Quantity and money sit in one
 * row, grouped under their own headings, because reading them apart is what
 * lets a crew that beat the labour norm hide a position that lost the money on
 * material.
 *
 * Two rules run through the whole page. Every comparison is against EARNED -
 * the estimate's allowance for the quantity really installed - never against
 * the whole line as priced, because a half-built position has spent about half
 * its budget and that is not a saving. And an unknown is drawn as an unknown: a
 * category the platform cannot price says so instead of showing a zero that
 * reads as money nobody spent.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  Download,
  Gauge,
  Layers,
  ListChecks,
  Package,
  Ruler,
  Timer,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  CollapsibleSection,
  EmptyState,
  SkeletonTable,
  StatCard,
  TabBar,
} from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { formatValue } from '@/shared/lib/numberFormat';
import { localizedUnitCode } from '@/shared/lib/unitLabels';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import {
  downloadProductivityMarkdown,
  fetchProductivity,
  type FeedbackFactor,
  type ProductivityLine,
  type ProductivityReport,
  type ResourceRollup,
} from './api';
import { kindLabel, statusLabel } from './labels';
import { buildPostCalcInsights } from './postcalcInsights';
import { QuantityCheckPanel } from './QuantityCheckPanel';

/* -- Small helpers --------------------------------------------------------- */

type TabId = 'positions' | 'resources' | 'feedback' | 'quantities';
type SortId = 'ref' | 'money' | 'factor';
type FilterId = 'all' | 'compared' | 'deviating';

const DEVIATING = new Set(['under_productive', 'over_productive']);
const COMPARED = new Set(['under_productive', 'over_productive', 'on_plan']);

/** Badge colour per verdict. Red is over the norm, green under it, grey unknown. */
const STATUS_VARIANT: Record<string, BadgeVariant> = {
  on_plan: 'success',
  under_productive: 'error',
  over_productive: 'blue',
  no_baseline: 'neutral',
  no_actuals: 'neutral',
  no_progress: 'warning',
};

/** Decimal string to a finite number, or NaN when the figure is absent. */
function num(value: string | null | undefined): number {
  if (value === null || value === undefined || value === '') return Number.NaN;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

/** A money delta, coloured: over the allowance is bad, under it is good. */
function VarianceCell({
  value,
  currency,
  unknown,
}: {
  value: string | null;
  currency: string;
  unknown: string;
}) {
  const parsed = num(value);
  if (Number.isNaN(parsed)) {
    return <span className="text-content-tertiary">{unknown}</span>;
  }
  return (
    <span
      className={clsx(
        'tabular-nums',
        parsed > 0 && 'text-semantic-error',
        parsed < 0 && 'text-semantic-success',
        parsed === 0 && 'text-content-secondary',
      )}
    >
      {parsed > 0 ? '+' : ''}
      {formatCurrency(parsed, currency)}
    </span>
  );
}

/** A plain figure, or the unknown marker when the platform has no source. */
function Figure({
  value,
  kind,
  currency,
  unknown,
  digits,
}: {
  value: string | null;
  kind: 'number' | 'currency';
  currency?: string;
  unknown: string;
  digits?: number;
}) {
  const parsed = num(value);
  if (Number.isNaN(parsed)) return <span className="text-content-tertiary">{unknown}</span>;
  return (
    <span className="tabular-nums">
      {kind === 'currency'
        ? formatCurrency(parsed, currency ?? '')
        : formatValue(parsed, 'number', { maximumFractionDigits: digits ?? 2 })}
    </span>
  );
}

/* -- Explainer ------------------------------------------------------------- */

function Explainer() {
  const { t } = useTranslation();
  // Keys written out in full rather than built from an index, so a scan for a
  // key finds it in the source and keeps it translated.
  const steps = [
    { icon: <Layers size={13} className="text-oe-blue" />, title: t('postcalc.step_1_title'), desc: t('postcalc.step_1_desc') },
    { icon: <Timer size={13} className="text-oe-blue" />, title: t('postcalc.step_2_title'), desc: t('postcalc.step_2_desc') },
    { icon: <Package size={13} className="text-oe-blue" />, title: t('postcalc.step_3_title'), desc: t('postcalc.step_3_desc') },
    { icon: <ListChecks size={13} className="text-oe-blue" />, title: t('postcalc.step_4_title'), desc: t('postcalc.step_4_desc') },
  ];

  return (
    <CollapsibleSection
      storageKey="postcalc.how"
      icon={<Gauge size={15} className="text-oe-blue" />}
      title={t('postcalc.how_title')}
    >
      <p className="text-xs text-content-tertiary">{t('postcalc.how_intro')}</p>
      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((step, index) => (
          <li key={step.title} className="flex-1 rounded-lg border border-border-light bg-surface-primary p-3">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
                {step.icon}
              </span>
              <span className="text-xs font-semibold text-content-primary">
                {index + 1}. {step.title}
              </span>
            </div>
            <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{step.desc}</p>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-2xs text-content-tertiary">{t('postcalc.how_related')}</p>
    </CollapsibleSection>
  );
}

/* -- Headline figures ------------------------------------------------------ */

function Headline({ report }: { report: ProductivityReport }) {
  const { t } = useTranslation();
  const unknown = t('postcalc.unknown');
  const currency = report.currency;

  const factor = num(report.overall_productivity_factor);
  const hoursDelta = num(report.total_actual_hours) - num(report.total_earned_hours);
  // Both money tiles subtract the *compared* earned total, the one covering the
  // same lines as the actual beside it. Against the full earned total, a project
  // that priced three lines out of forty would report the other thirty-seven as
  // a saving, and the bigger the unmeasured part the better the news would look.
  const materialActual = num(report.total_actual_material_cost);
  const materialEarned = num(report.total_earned_material_cost_compared);
  const materialDelta = materialActual - materialEarned;
  const labourActual = num(report.total_actual_labour_cost);
  const labourEarned = num(report.total_earned_labour_cost_compared);
  const labourDelta = labourActual - labourEarned;

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard
        label={t('postcalc.kpi_factor')}
        value={
          Number.isNaN(factor) ? unknown : formatValue(factor, 'number', { maximumFractionDigits: 3 })
        }
        sub={t('postcalc.kpi_factor_sub', {
          compared: report.compared_line_count,
          total: report.line_count,
        })}
        icon={Gauge}
        tone={Number.isNaN(factor) ? 'default' : factor > 1 ? 'danger' : 'success'}
        tintValue
      />
      <StatCard
        label={t('postcalc.kpi_hours')}
        value={
          Number.isNaN(hoursDelta)
            ? unknown
            : formatValue(hoursDelta, 'number', { maximumFractionDigits: 1 })
        }
        sub={t('postcalc.kpi_hours_sub', {
          earned: formatValue(num(report.total_earned_hours), 'number', { maximumFractionDigits: 1 }),
          actual: formatValue(num(report.total_actual_hours), 'number', { maximumFractionDigits: 1 }),
        })}
        icon={hoursDelta > 0 ? TrendingUp : TrendingDown}
        tone={hoursDelta > 0 ? 'danger' : 'success'}
        tintValue
      />
      <StatCard
        label={t('postcalc.kpi_labour_money')}
        value={Number.isNaN(labourActual) ? unknown : formatCurrency(labourDelta, currency)}
        sub={
          Number.isNaN(labourActual)
            ? t('postcalc.kpi_no_source_labour')
            : t('postcalc.kpi_money_priced_sub', {
                priced: report.labour_priced_line_count,
                total: report.line_count,
                earned: formatCurrency(labourEarned, currency),
                actual: formatCurrency(labourActual, currency),
              })
        }
        icon={Timer}
        tone={Number.isNaN(labourActual) ? 'default' : labourDelta > 0 ? 'danger' : 'success'}
        tintValue={!Number.isNaN(labourActual)}
      />
      <StatCard
        label={t('postcalc.kpi_material_money')}
        value={Number.isNaN(materialActual) ? unknown : formatCurrency(materialDelta, currency)}
        sub={
          Number.isNaN(materialActual)
            ? t('postcalc.kpi_no_source_material')
            : t('postcalc.kpi_money_priced_sub', {
                priced: report.material_priced_line_count,
                total: report.line_count,
                earned: formatCurrency(materialEarned, currency),
                actual: formatCurrency(materialActual, currency),
              })
        }
        icon={Package}
        tone={Number.isNaN(materialActual) ? 'default' : materialDelta > 0 ? 'danger' : 'success'}
        tintValue={!Number.isNaN(materialActual)}
      />
    </div>
  );
}

/* -- Positions ------------------------------------------------------------- */

/** Money lost on a line, labour and material together. Both halves or neither.
 *
 *  Adding a known labour overrun to an unknown material spend would state a
 *  total the data cannot support, so a line the site never metered reports no
 *  total rather than reporting its labour half under a heading that says both.
 */
function totalDelta(line: ProductivityLine): number {
  const labour = num(line.labour_cost_variance_earned);
  const material = num(line.material_cost_variance_earned);
  if (Number.isNaN(labour) || Number.isNaN(material)) return Number.NaN;
  return labour + material;
}

function PositionsTable({ report }: { report: ProductivityReport }) {
  const { t, i18n } = useTranslation();
  const [sort, setSort] = useState<SortId>('ref');
  const [filter, setFilter] = useState<FilterId>('all');
  const unknown = t('postcalc.unknown');
  const currency = report.currency;

  const rows = useMemo(() => {
    const filtered = report.lines.filter((line) => {
      if (filter === 'compared') return COMPARED.has(line.status);
      if (filter === 'deviating') return DEVIATING.has(line.status);
      return true;
    });
    const sorted = [...filtered];
    if (sort === 'money') {
      sorted.sort((a, b) => {
        const left = totalDelta(a);
        const right = totalDelta(b);
        if (Number.isNaN(left) && Number.isNaN(right)) return 0;
        if (Number.isNaN(left)) return 1;
        if (Number.isNaN(right)) return -1;
        return right - left;
      });
    } else if (sort === 'factor') {
      sorted.sort((a, b) => {
        const left = num(a.productivity_factor);
        const right = num(b.productivity_factor);
        if (Number.isNaN(left) && Number.isNaN(right)) return 0;
        if (Number.isNaN(left)) return 1;
        if (Number.isNaN(right)) return -1;
        return right - left;
      });
    }
    return sorted;
  }, [report.lines, sort, filter]);

  const selectCls =
    'h-9 rounded-lg border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

  if (report.lines.length === 0) {
    return (
      <EmptyState
        icon={<Layers size={40} className="text-content-tertiary" />}
        title={t('postcalc.empty_title')}
        description={t('postcalc.empty_desc')}
      />
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-light px-4 py-3">
        <p className="text-xs text-content-tertiary">
          {t('postcalc.table_hint', { shown: rows.length, total: report.lines.length })}
        </p>
        <div className="flex items-center gap-2">
          <label className="text-2xs text-content-tertiary" htmlFor="postcalc-filter">
            {t('postcalc.filter_label')}
          </label>
          <select
            id="postcalc-filter"
            className={selectCls}
            value={filter}
            onChange={(e) => setFilter(e.target.value as FilterId)}
          >
            <option value="all">{t('postcalc.filter_all')}</option>
            <option value="compared">{t('postcalc.filter_compared')}</option>
            <option value="deviating">{t('postcalc.filter_deviating')}</option>
          </select>
          <label className="text-2xs text-content-tertiary" htmlFor="postcalc-sort">
            {t('postcalc.sort_label')}
          </label>
          <select
            id="postcalc-sort"
            className={selectCls}
            value={sort}
            onChange={(e) => setSort(e.target.value as SortId)}
          >
            <option value="ref">{t('postcalc.sort_ref')}</option>
            <option value="money">{t('postcalc.sort_money')}</option>
            <option value="factor">{t('postcalc.sort_factor')}</option>
          </select>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[1180px] text-xs">
          <thead>
            <tr className="border-b border-border-light text-2xs uppercase tracking-wide text-content-tertiary">
              <th className="px-3 py-2 text-left" colSpan={3}>
                {t('postcalc.group_position')}
              </th>
              <th className="border-l border-border-light px-3 py-2 text-center" colSpan={3}>
                {t('postcalc.group_quantity')}
              </th>
              <th className="border-l border-border-light px-3 py-2 text-center" colSpan={3}>
                {t('postcalc.group_hours')}
              </th>
              <th className="border-l border-border-light px-3 py-2 text-center" colSpan={4}>
                {t('postcalc.group_money')}
              </th>
              <th className="border-l border-border-light px-3 py-2 text-center">
                {t('postcalc.col_status')}
              </th>
            </tr>
            <tr className="border-b border-border-light text-2xs text-content-tertiary">
              <th className="px-3 py-2 text-left">{t('postcalc.col_ref')}</th>
              <th className="px-3 py-2 text-left">{t('postcalc.col_description')}</th>
              <th className="px-3 py-2 text-left">{t('postcalc.col_unit')}</th>
              <th className="border-l border-border-light px-3 py-2 text-right">
                {t('postcalc.col_planned_qty')}
              </th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_installed_qty')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_progress')}</th>
              <th className="border-l border-border-light px-3 py-2 text-right">
                {t('postcalc.col_earned_hours')}
              </th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_actual_hours')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_factor')}</th>
              <th className="border-l border-border-light px-3 py-2 text-right">
                {t('postcalc.col_labour_delta')}
              </th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_material_earned')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_material_actual')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_total_delta')}</th>
              <th className="border-l border-border-light px-3 py-2 text-center" />
            </tr>
          </thead>
          <tbody>
            {rows.map((line, index) => {
              const factor = num(line.productivity_factor);
              const total = totalDelta(line);
              return (
                <tr
                  key={`${line.ref}-${index}`}
                  className="border-b border-border-light last:border-0 hover:bg-surface-secondary/60"
                >
                  <td className="px-3 py-2 font-mono text-2xs text-content-secondary">{line.ref || '-'}</td>
                  <td className="max-w-[280px] truncate px-3 py-2 text-content-primary" title={line.description}>
                    {line.description || '-'}
                  </td>
                  <td className="px-3 py-2 text-content-tertiary">{line.unit ? localizedUnitCode(line.unit, i18n.language) : '-'}</td>
                  <td className="border-l border-border-light px-3 py-2 text-right">
                    <Figure value={line.planned_quantity} kind="number" unknown={unknown} digits={3} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Figure value={line.actual_quantity} kind="number" unknown={unknown} digits={3} />
                  </td>
                  <td className="px-3 py-2 text-right text-content-secondary">
                    {Number.isNaN(num(line.progress_pct))
                      ? unknown
                      : t('postcalc.pct_value', {
                          value: formatValue(num(line.progress_pct), 'number', {
                            maximumFractionDigits: 1,
                          }),
                        })}
                  </td>
                  <td className="border-l border-border-light px-3 py-2 text-right">
                    <Figure value={line.earned_hours} kind="number" unknown={unknown} digits={1} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Figure value={line.actual_hours} kind="number" unknown={unknown} digits={1} />
                  </td>
                  <td
                    className={clsx(
                      'px-3 py-2 text-right tabular-nums',
                      factor > 1 && 'text-semantic-error',
                      factor < 1 && 'text-semantic-success',
                    )}
                  >
                    {Number.isNaN(factor)
                      ? unknown
                      : formatValue(factor, 'number', { maximumFractionDigits: 3 })}
                  </td>
                  <td className="border-l border-border-light px-3 py-2 text-right">
                    <VarianceCell
                      value={line.labour_cost_variance_earned}
                      currency={currency}
                      unknown={unknown}
                    />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Figure
                      value={line.actual_material_cost === null ? null : line.earned_material_cost}
                      kind="currency"
                      currency={currency}
                      unknown={unknown}
                    />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Figure
                      value={line.actual_material_cost}
                      kind="currency"
                      currency={currency}
                      unknown={unknown}
                    />
                  </td>
                  <td className="px-3 py-2 text-right font-medium">
                    <VarianceCell
                      value={Number.isNaN(total) ? null : String(total)}
                      currency={currency}
                      unknown={unknown}
                    />
                  </td>
                  <td className="border-l border-border-light px-3 py-2 text-center">
                    <Badge variant={STATUS_VARIANT[line.status] ?? 'neutral'}>
                      {statusLabel(line.status, t)}
                    </Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-border-light px-4 py-2 text-2xs text-content-tertiary">
        {t('postcalc.table_legend', { unknown })}
      </p>
    </Card>
  );
}

/* -- Resource categories --------------------------------------------------- */

function ResourceTable({ resources, currency }: { resources: ResourceRollup[]; currency: string }) {
  const { t } = useTranslation();
  const unknown = t('postcalc.unknown');

  if (resources.length === 0) {
    return (
      <EmptyState
        icon={<Layers size={40} className="text-content-tertiary" />}
        title={t('postcalc.resources_empty_title')}
        description={t('postcalc.resources_empty_desc')}
      />
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-xs">
          <thead>
            <tr className="border-b border-border-light text-2xs text-content-tertiary">
              <th className="px-3 py-2 text-left">{t('postcalc.col_category')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_earned_hours')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_actual_hours')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_factor')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_planned_cost')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_earned_cost')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_actual_cost')}</th>
              <th className="px-3 py-2 text-right">{t('postcalc.col_cost_delta')}</th>
            </tr>
          </thead>
          <tbody>
            {resources.map((row) => (
              <tr key={row.kind} className="border-b border-border-light last:border-0">
                <td className="px-3 py-2 font-medium text-content-primary">
                  {kindLabel(row.kind, row.label, t)}
                </td>
                <td className="px-3 py-2 text-right">
                  {row.is_hour_based ? (
                    <Figure value={row.earned_hours} kind="number" unknown={unknown} digits={1} />
                  ) : (
                    <span className="text-content-tertiary">{t('postcalc.not_applicable')}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {row.is_hour_based ? (
                    <Figure value={row.actual_hours} kind="number" unknown={unknown} digits={1} />
                  ) : (
                    <span className="text-content-tertiary">{t('postcalc.not_applicable')}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  <Figure value={row.productivity_factor} kind="number" unknown={unknown} digits={3} />
                </td>
                <td className="px-3 py-2 text-right">
                  <Figure value={row.planned_cost} kind="currency" currency={currency} unknown={unknown} />
                </td>
                <td className="px-3 py-2 text-right">
                  {/* The earned figure that covers the same lines as the actual
                      next to it, so Earned minus Actual is the delta shown at
                      the end of the row. Falls back to the full earned total
                      where there is no actual to compare against. */}
                  <Figure
                    value={row.earned_cost_compared ?? row.earned_cost}
                    kind="currency"
                    currency={currency}
                    unknown={unknown}
                  />
                </td>
                <td className="px-3 py-2 text-right">
                  <Figure value={row.actual_cost} kind="currency" currency={currency} unknown={unknown} />
                </td>
                <td className="px-3 py-2 text-right font-medium">
                  <VarianceCell value={row.cost_variance_earned} currency={currency} unknown={unknown} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-border-light px-4 py-2 text-2xs text-content-tertiary">
        {t('postcalc.resources_legend')}
      </p>
    </Card>
  );
}

/* -- Feedback to estimating ------------------------------------------------ */

function FeedbackTable({ factors }: { factors: FeedbackFactor[] }) {
  const { t, i18n } = useTranslation();

  if (factors.length === 0) {
    return (
      <EmptyState
        icon={<ListChecks size={40} className="text-content-tertiary" />}
        title={t('postcalc.feedback_empty_title')}
        description={t('postcalc.feedback_empty_desc')}
      />
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-content-tertiary">{t('postcalc.feedback_intro')}</p>
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-xs">
            <thead>
              <tr className="border-b border-border-light text-2xs text-content-tertiary">
                <th className="px-3 py-2 text-left">{t('postcalc.col_ref')}</th>
                <th className="px-3 py-2 text-left">{t('postcalc.col_description')}</th>
                <th className="px-3 py-2 text-right">{t('postcalc.col_current_norm')}</th>
                <th className="px-3 py-2 text-right">{t('postcalc.col_observed_norm')}</th>
                <th className="px-3 py-2 text-right">{t('postcalc.col_confidence')}</th>
                <th className="px-3 py-2 text-left">{t('postcalc.col_recommendation')}</th>
              </tr>
            </thead>
            <tbody>
              {factors.map((factor, index) => {
                const current = formatValue(num(factor.current_hours_per_unit), 'number', {
                  maximumFractionDigits: 3,
                });
                const observed = formatValue(num(factor.observed_hours_per_unit), 'number', {
                  maximumFractionDigits: 3,
                });
                const variance = formatValue(Math.abs(num(factor.variance_pct)), 'number', {
                  maximumFractionDigits: 1,
                });
                const unit = factor.unit ? localizedUnitCode(factor.unit, i18n.language) : t('postcalc.norm_unit_fallback');
                const overran = num(factor.productivity_factor) > 1;
                return (
                  <tr key={`${factor.ref}-${index}`} className="border-b border-border-light last:border-0">
                    <td className="px-3 py-2 font-mono text-2xs text-content-secondary">
                      {factor.ref || '-'}
                    </td>
                    <td className="max-w-[240px] truncate px-3 py-2" title={factor.description}>
                      {factor.description || '-'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {t('postcalc.norm_value', { value: current, unit })}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {t('postcalc.norm_value', { value: observed, unit })}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Badge variant={num(factor.confidence) >= 0.6 ? 'success' : 'warning'}>
                        {t('postcalc.pct_value', {
                          value: formatValue(num(factor.confidence) * 100, 'number', {
                            maximumFractionDigits: 0,
                          }),
                        })}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-content-secondary">
                      {overran
                        ? t('postcalc.advice_raise', { variance, current, observed, unit })
                        : t('postcalc.advice_tighten', { variance, current, observed, unit })}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* -- Page ------------------------------------------------------------------ */

export function PostCalcPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
  const addToast = useToastStore((s) => s.addToast);
  const [activeTab, setActiveTab] = useState<TabId>('positions');
  const [downloading, setDownloading] = useState(false);

  const isQuantityTab = activeTab === 'quantities';
  const query = useQuery({
    queryKey: ['postcalc', 'productivity', projectId],
    queryFn: () => fetchProductivity(projectId),
    enabled: Boolean(projectId) && !isQuantityTab,
  });

  const report = query.data;
  // Every hook stays above the first conditional return, so the hook order is
  // the same on the loading, error and loaded branches.
  const insights = useModuleInsights('postcalc', { defaultOpen: false });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildPostCalcInsights(report?.lines ?? [], report?.currency ?? '', t),
    [report?.lines, report?.currency, t],
  );

  const onDownload = async () => {
    if (!projectId) return;
    setDownloading(true);
    try {
      await downloadProductivityMarkdown(projectId);
    } catch (err) {
      addToast({ type: 'error', title: t('postcalc.export_failed'), message: getErrorMessage(err) });
    } finally {
      setDownloading(false);
    }
  };

  const tabs = [
    {
      id: 'positions' as const,
      label: t('postcalc.tab_positions'),
      icon: <Layers size={15} />,
    },
    {
      id: 'resources' as const,
      label: t('postcalc.tab_resources'),
      icon: <Package size={15} />,
    },
    {
      id: 'feedback' as const,
      label: t('postcalc.tab_feedback'),
      icon: <ListChecks size={15} />,
    },
    {
      // Contract quantity against measured quantity, per bill position. It
      // has its own query, so it opens even when the productivity report is
      // loading or failed.
      id: 'quantities' as const,
      label: t('postcalc.qc.tab', { defaultValue: 'Quantity check' }),
      icon: <Ruler size={15} />,
    },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('postcalc.title')}
        subtitle={t('postcalc.subtitle')}
        actions={
          <>
            {activeTab === 'positions' && (
              <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={onDownload}
              disabled={!projectId || downloading || !report || isQuantityTab}
            >
              <Download size={15} />
              {t('postcalc.export_markdown')}
            </Button>
          </>
        }
      />

      <RequiresProject emptyHint={t('postcalc.select_project')}>
        <Explainer />

        <TabBar<TabId>
          tabs={tabs}
          activeId={activeTab}
          onChange={(id) => setActiveTab(id)}
          ariaLabel={t('postcalc.tabs_aria')}
          variant="underline"
        />

        {isQuantityTab && (
          <div role="tabpanel">
            <QuantityCheckPanel projectId={projectId} />
          </div>
        )}

        {!isQuantityTab && query.isLoading && <SkeletonTable rows={8} />}

        {!isQuantityTab && query.isError && (
          <EmptyState
            icon={<Gauge size={40} className="text-semantic-error" />}
            title={t('postcalc.load_failed')}
            description={getErrorMessage(query.error)}
            action={
              <Button variant="secondary" size="sm" onClick={() => query.refetch()}>
                {t('postcalc.retry')}
              </Button>
            }
          />
        )}

        {!isQuantityTab && report && (
          <div className="space-y-4">
            <Headline report={report} />

            <div role="tabpanel">
              {activeTab === 'positions' && (
                <div className="space-y-4">
                  <InsightsPanel
                    open={insights.open}
                    title={t('postcalc.insights.title')}
                    datasets={insightDatasets}
                    builtins={insightBuiltins}
                    custom={insights.custom}
                    onAdd={insights.addCustom}
                    onUpdate={insights.updateCustom}
                    onRemove={insights.removeCustom}
                    onCollapse={() => insights.setOpen(false)}
                  />
                  <PositionsTable report={report} />
                </div>
              )}
              {activeTab === 'resources' && (
                <ResourceTable resources={report.resources} currency={report.currency} />
              )}
              {activeTab === 'feedback' && <FeedbackTable factors={report.feedback_factors} />}
            </div>
          </div>
        )}
      </RequiresProject>
    </div>
  );
}

export default PostCalcPage;
