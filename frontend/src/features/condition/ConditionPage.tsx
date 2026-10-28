// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Condition & Maintenance Plan.
 *
 * Ratings of assets and building elements on a configurable scale, and the
 * multi-year maintenance plan derived from them. Derived actions are proposals
 * with a confidence; a manager approves them before they count in the plan.
 */
import { Fragment, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  ArrowRight,
  CalendarRange,
  CheckCircle2,
  ClipboardCheck,
  Download,
  Gauge,
  Network,
  Plus,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wand2,
  XCircle,
} from 'lucide-react';
import { Badge, Button, Card, CollapsibleSection, EmptyState, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtCurrency, fmtDate, fmtNumber, fmtPercent } from '@/shared/lib/formatters';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { listSeries } from '@/features/price-index/api';
import {
  applyPlanToAssets,
  deleteAssessment,
  derivePlan,
  downloadPlanCsv,
  fetchActions,
  fetchAssessments,
  fetchPlan,
  fetchScales,
  updateAction,
  validateCondition,
  type ConditionScale,
  type MaintenanceAction,
  type PlanQuery,
} from './api';
import { AssessmentModal } from './AssessmentModal';
import { actionStatusLabel, actionTypeLabel, levelLabel, levelOf } from './conditionLabels';

type Tab = 'ratings' | 'plan' | 'checks';

function HowItWorks() {
  const { t } = useTranslation();
  const steps = [
    {
      icon: <ClipboardCheck size={14} className="text-oe-blue" />,
      title: t('condition.flow_1_title', { defaultValue: 'Rate on inspection' }),
      desc: t('condition.flow_1_desc', {
        defaultValue: 'Record severity, extent and intensity of what you find; the rating is proposed and you decide.',
      }),
    },
    {
      icon: <Wand2 size={14} className="text-oe-blue" />,
      title: t('condition.flow_2_title', { defaultValue: 'Derive the plan' }),
      desc: t('condition.flow_2_desc', {
        defaultValue: 'Each rating proposes the action its scale level calls for: repair, replace or recurring maintenance.',
      }),
    },
    {
      icon: <ShieldCheck size={14} className="text-oe-blue" />,
      title: t('condition.flow_3_title', { defaultValue: 'Approve and price' }),
      desc: t('condition.flow_3_desc', {
        defaultValue: 'A manager approves the proposals and checks the unit costs; only approved work counts.',
      }),
    },
    {
      icon: <CalendarRange size={14} className="text-oe-blue" />,
      title: t('condition.flow_4_title', { defaultValue: 'Budget by year' }),
      desc: t('condition.flow_4_desc', {
        defaultValue: 'See the cost per year with inflation from your price index, export it, and write it to the asset register for whole-life cost.',
      }),
    },
  ];
  return (
    <CollapsibleSection
      storageKey="condition.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('condition.flow_title', { defaultValue: 'How condition and maintenance planning fit together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('condition.flow_intro', {
          defaultValue:
            'Rate what you inspect on one scale, turn the ratings into a costed maintenance plan, and keep the asset register and the whole-life cost in step with it.',
        })}
      </p>
      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li aria-hidden="true" className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex">
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>
      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">{t('condition.flow_connects', { defaultValue: 'Connects with:' })}</span>{' '}
        <Link className="text-oe-blue hover:underline" to="/inspections">
          {t('condition.mod_inspections', { defaultValue: 'Inspections' })}
        </Link>{' '}
        ·{' '}
        <Link className="text-oe-blue hover:underline" to="/assets">
          {t('condition.mod_assets', { defaultValue: 'Asset register' })}
        </Link>{' '}
        ·{' '}
        <Link className="text-oe-blue hover:underline" to="/price-index">
          {t('condition.mod_price_index', { defaultValue: 'Price index' })}
        </Link>{' '}
        ·{' '}
        <Link className="text-oe-blue hover:underline" to="/carbon">
          {t('condition.mod_lcc', { defaultValue: 'Whole-life cost' })}
        </Link>
      </div>
    </CollapsibleSection>
  );
}

function RatingChip({ scale, rating }: { scale: ConditionScale | undefined; rating: number }) {
  const { t } = useTranslation();
  const level = scale ? levelOf(scale.levels, rating) : undefined;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-content-primary">
      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: level?.color ?? '#94a3b8' }} />
      {rating}
      {level && scale ? ` · ${levelLabel(t, scale.key, level)}` : ''}
    </span>
  );
}

export function ConditionPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const canCreate = useHasPermission('condition.create');
  const canApprove = useHasPermission('condition.approve');
  const [tab, setTab] = useState<Tab>('ratings');
  const [showModal, setShowModal] = useState(false);
  const thisYear = new Date().getFullYear();
  const [startYear, setStartYear] = useState(thisYear);
  const [horizon, setHorizon] = useState(10);
  const [inflationPct, setInflationPct] = useState('');
  const [seriesId, setSeriesId] = useState('');
  const [discountPct, setDiscountPct] = useState('');
  const [includeProposed, setIncludeProposed] = useState(false);

  const planQuery: PlanQuery = useMemo(
    () => ({
      start_year: startYear,
      horizon_years: horizon,
      inflation_rate: inflationPct.trim() ? String(Number(inflationPct) / 100) : undefined,
      index_series_id: !inflationPct.trim() && seriesId ? seriesId : undefined,
      discount_rate: discountPct.trim() ? String(Number(discountPct) / 100) : undefined,
      include_proposed: includeProposed,
    }),
    [startYear, horizon, inflationPct, seriesId, discountPct, includeProposed],
  );

  const scalesQ = useQuery({ queryKey: ['condition-scales', projectId], queryFn: () => fetchScales(projectId), enabled: !!projectId });
  const assessmentsQ = useQuery({ queryKey: ['condition-assessments', projectId], queryFn: () => fetchAssessments(projectId), enabled: !!projectId });
  const actionsQ = useQuery({ queryKey: ['condition-actions', projectId], queryFn: () => fetchActions(projectId), enabled: !!projectId && tab === 'plan' });
  const planQ = useQuery({
    queryKey: ['condition-plan', projectId, planQuery],
    queryFn: () => fetchPlan(projectId, planQuery),
    enabled: !!projectId && tab === 'plan',
  });
  const seriesQ = useQuery({ queryKey: ['price-index-series'], queryFn: listSeries, enabled: tab === 'plan' });
  const checksQ = useQuery({ queryKey: ['condition-checks', projectId], queryFn: () => validateCondition(projectId), enabled: !!projectId && tab === 'checks' });

  const scalesByKey = useMemo(() => new Map((scalesQ.data ?? []).map((s) => [s.key, s])), [scalesQ.data]);
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['condition-assessments', projectId] });
    qc.invalidateQueries({ queryKey: ['condition-actions', projectId] });
    qc.invalidateQueries({ queryKey: ['condition-plan', projectId] });
    qc.invalidateQueries({ queryKey: ['condition-checks', projectId] });
  };
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const deriveMut = useMutation({
    mutationFn: () => derivePlan(projectId, startYear),
    onSuccess: (r) => {
      invalidate();
      addToast({
        type: 'success',
        title: t('condition.derived', {
          defaultValue: '{{created}} actions proposed, {{skipped}} ratings needed none or were already planned',
          created: r.created,
          skipped: r.skipped,
        }),
      });
    },
    onError,
  });
  const actionMut = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Parameters<typeof updateAction>[1] }) => updateAction(id, patch),
    onSuccess: invalidate,
    onError,
  });
  const deleteMut = useMutation({ mutationFn: (id: string) => deleteAssessment(id), onSuccess: invalidate, onError });
  const applyMut = useMutation({
    mutationFn: () => applyPlanToAssets(projectId, planQuery),
    onSuccess: (r) =>
      addToast({
        type: 'success',
        title: t('condition.applied', { defaultValue: '{{count}} assets updated in the asset register', count: r.updated }),
      }),
    onError,
  });
  const exportMut = useMutation({ mutationFn: () => downloadPlanCsv(projectId, planQuery), onError });

  const plan = planQ.data;
  const currency = plan?.currencies.length === 1 ? plan.currencies[0] : null;
  const maxYear = useMemo(() => Math.max(1, ...(plan?.years ?? []).map((y) => Number(y.cost_inflated))), [plan]);
  const money = (v: string) => (currency ? fmtCurrency(v, currency) : fmtNumber(v, 2));

  const actionRow = (a: MaintenanceAction) => (
    <tr key={a.id} className="border-t border-border-light text-sm">
      <td className="py-2 pr-2">
        <div className="font-medium text-content-primary">{a.element_name}</div>
        <div className="text-2xs text-content-tertiary">{[a.area, a.asset_ref].filter(Boolean).join(' · ')}</div>
      </td>
      <td className="py-2 pr-2">{actionTypeLabel(t, a.action_type)}</td>
      <td className="py-2 pr-2 tabular-nums">
        {a.first_year}
        {a.interval_years ? (
          <span className="text-2xs text-content-tertiary">
            {' '}
            {t('condition.every_years', { defaultValue: 'every {{count}} years', count: a.interval_years })}
          </span>
        ) : null}
      </td>
      <td className="py-2 pr-2 tabular-nums">
        {a.quantity ? `${fmtNumber(a.quantity, 2)} ${a.unit ?? ''}` : '-'}
      </td>
      <td className="py-2 pr-2">
        {a.unit_cost ? (
          <span className="tabular-nums">{a.currency ? fmtCurrency(a.unit_cost, a.currency) : fmtNumber(a.unit_cost, 2)}</span>
        ) : (
          <Badge variant="warning" size="sm">
            {t('condition.unpriced', { defaultValue: 'No unit cost' })}
          </Badge>
        )}
      </td>
      <td className="py-2 pr-2">
        <Badge variant={a.status === 'approved' ? 'success' : a.status === 'rejected' ? 'error' : a.status === 'done' ? 'blue' : 'neutral'} size="sm">
          {actionStatusLabel(t, a.status)}
        </Badge>
        {a.source === 'derived' && a.confidence != null && (
          <span className="ml-1 inline-flex items-center gap-0.5 text-2xs text-content-tertiary" title={t('condition.confidence', { defaultValue: 'Confidence of the proposal' })}>
            <Sparkles size={10} />
            {fmtPercent(a.confidence * 100, 0)}
          </span>
        )}
      </td>
      <td className="py-2 text-right">
        {a.status === 'proposed' && canApprove && (
          <span className="inline-flex gap-1">
            <Button size="sm" variant="secondary" icon={<CheckCircle2 size={13} />} onClick={() => actionMut.mutate({ id: a.id, patch: { status: 'approved' } })}>
              {t('condition.approve', { defaultValue: 'Approve' })}
            </Button>
            <Button size="sm" variant="ghost" icon={<XCircle size={13} />} onClick={() => actionMut.mutate({ id: a.id, patch: { status: 'rejected' } })}>
              {t('condition.reject', { defaultValue: 'Reject' })}
            </Button>
          </span>
        )}
        {a.status === 'approved' && canCreate && (
          <Button size="sm" variant="ghost" onClick={() => actionMut.mutate({ id: a.id, patch: { status: 'done' } })}>
            {t('condition.mark_done', { defaultValue: 'Mark done' })}
          </Button>
        )}
      </td>
    </tr>
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('condition.title', { defaultValue: 'Condition & Maintenance Plan' })}
        subtitle={t('condition.subtitle', {
          defaultValue:
            'Rate assets and building elements on a configurable condition scale and turn the ratings into a costed multi-year maintenance plan.',
        })}
        actions={
          canCreate && projectId ? (
            <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setShowModal(true)} data-testid="condition-new">
              {t('condition.new_rating', { defaultValue: 'Record condition' })}
            </Button>
          ) : undefined
        }
      />
      <HowItWorks />
      {!projectId ? (
        <RequiresProject>{null}</RequiresProject>
      ) : (
        <>
          <div className="inline-flex rounded-lg border border-border bg-surface-secondary p-0.5">
            {(['ratings', 'plan', 'checks'] as Tab[]).map((v) => (
              <button
                key={v}
                onClick={() => setTab(v)}
                className={clsx(
                  'flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium',
                  tab === v ? 'bg-surface-elevated text-content-primary shadow-xs' : 'text-content-tertiary hover:text-content-primary',
                )}
                data-testid={`condition-tab-${v}`}
              >
                {v === 'ratings' ? <Gauge size={14} /> : v === 'plan' ? <CalendarRange size={14} /> : <ShieldCheck size={14} />}
                {v === 'ratings'
                  ? t('condition.tab_ratings', { defaultValue: 'Ratings' })
                  : v === 'plan'
                    ? t('condition.tab_plan', { defaultValue: 'Maintenance plan' })
                    : t('condition.tab_checks', { defaultValue: 'Checks' })}
              </button>
            ))}
          </div>

          {tab === 'ratings' &&
            (assessmentsQ.isLoading ? (
              <SkeletonTable rows={5} columns={5} />
            ) : (assessmentsQ.data ?? []).length === 0 ? (
              <EmptyState
                icon={<Gauge size={28} strokeWidth={1.5} />}
                title={t('condition.empty_title', { defaultValue: 'No condition ratings yet' })}
                description={t('condition.empty_desc', {
                  defaultValue: 'Rate an asset or element here, or from an inspection, to start the maintenance plan.',
                })}
                action={canCreate ? { label: t('condition.new_rating', { defaultValue: 'Record condition' }), onClick: () => setShowModal(true) } : undefined}
              />
            ) : (
              <Card padding="none" className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm">
                  <thead className="bg-surface-secondary text-left text-xs text-content-tertiary">
                    <tr>
                      <th className="px-4 py-2 font-medium">{t('condition.element', { defaultValue: 'Asset or element' })}</th>
                      <th className="px-2 py-2 font-medium">{t('condition.rating', { defaultValue: 'Rating' })}</th>
                      <th className="px-2 py-2 font-medium">{t('condition.col_record', { defaultValue: 'Severity / extent / intensity' })}</th>
                      <th className="px-2 py-2 font-medium">{t('condition.assessed_at', { defaultValue: 'Assessed on' })}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {(assessmentsQ.data ?? []).map((a) => (
                      <tr key={a.id} className="border-t border-border-light">
                        <td className="px-4 py-2">
                          <div className="font-medium text-content-primary">{a.element_name}</div>
                          <div className="text-2xs text-content-tertiary">{[a.area, a.asset_ref, a.defect_description].filter(Boolean).join(' · ')}</div>
                        </td>
                        <td className="px-2 py-2">
                          <RatingChip scale={scalesByKey.get(a.scale_key)} rating={a.rating} />
                          {a.suggested_rating != null && a.suggested_rating !== a.rating && (
                            <div className="text-2xs text-content-tertiary">
                              {t('condition.suggested_was', { defaultValue: 'suggested {{rating}}', rating: a.suggested_rating })}
                            </div>
                          )}
                        </td>
                        <td className="px-2 py-2 text-xs tabular-nums text-content-secondary">
                          {a.severity ?? '-'} / {a.extent_pct != null ? fmtPercent(a.extent_pct, 0) : '-'} / {a.intensity ?? '-'}
                        </td>
                        <td className="px-2 py-2 text-xs text-content-secondary">{a.assessed_at ? fmtDate(a.assessed_at) : '-'}</td>
                        <td className="px-2 py-2 text-right">
                          {canApprove && (
                            <button
                              type="button"
                              className="text-content-tertiary hover:text-semantic-error"
                              aria-label={t('common.delete', { defaultValue: 'Delete' })}
                              onClick={() => deleteMut.mutate(a.id)}
                            >
                              <Trash2 size={14} />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            ))}

          {tab === 'plan' && (
            <div className="space-y-4">
              <Card className="grid gap-3 p-4 md:grid-cols-6">
                <label className="text-xs font-medium text-content-secondary">
                  {t('condition.start_year', { defaultValue: 'First year' })}
                  <input type="number" className="mt-1 h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm" value={startYear} onChange={(e) => setStartYear(Number(e.target.value) || thisYear)} />
                </label>
                <label className="text-xs font-medium text-content-secondary">
                  {t('condition.horizon', { defaultValue: 'Years' })}
                  <input type="number" min={1} max={100} className="mt-1 h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm" value={horizon} onChange={(e) => setHorizon(Math.min(100, Math.max(1, Number(e.target.value) || 10)))} />
                </label>
                <label className="text-xs font-medium text-content-secondary">
                  {t('condition.inflation_pct', { defaultValue: 'Inflation per year (%)' })}
                  <input inputMode="decimal" className="mt-1 h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm" value={inflationPct} onChange={(e) => setInflationPct(e.target.value)} />
                </label>
                <label className="text-xs font-medium text-content-secondary md:col-span-2">
                  {t('condition.index_series', { defaultValue: 'or from price index' })}
                  <select className="mt-1 h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm" value={seriesId} onChange={(e) => setSeriesId(e.target.value)} disabled={inflationPct.trim() !== ''}>
                    <option value="">-</option>
                    {(seriesQ.data ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs font-medium text-content-secondary">
                  {t('condition.discount_pct', { defaultValue: 'Discount rate (%)' })}
                  <input inputMode="decimal" className="mt-1 h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm" value={discountPct} onChange={(e) => setDiscountPct(e.target.value)} />
                </label>
                <div className="flex flex-wrap items-center gap-2 md:col-span-6">
                  <label className="flex items-center gap-2 text-sm text-content-secondary">
                    <input type="checkbox" checked={includeProposed} onChange={(e) => setIncludeProposed(e.target.checked)} />
                    {t('condition.include_proposed', { defaultValue: 'Include proposals not yet approved' })}
                  </label>
                  <span className="flex-1" />
                  {canCreate && (
                    <Button size="sm" variant="secondary" icon={<Wand2 size={14} />} loading={deriveMut.isPending} onClick={() => deriveMut.mutate()} data-testid="condition-derive">
                      {t('condition.derive', { defaultValue: 'Propose actions from ratings' })}
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" icon={<Download size={14} />} loading={exportMut.isPending} onClick={() => exportMut.mutate()}>
                    {t('condition.export_csv', { defaultValue: 'Export CSV' })}
                  </Button>
                  {canApprove && (
                    <Button size="sm" variant="secondary" icon={<ShieldCheck size={14} />} loading={applyMut.isPending} onClick={() => applyMut.mutate()}>
                      {t('condition.apply_assets', { defaultValue: 'Write to asset register' })}
                    </Button>
                  )}
                </div>
              </Card>

              {plan && (
                <Card className="p-4" data-testid="condition-plan">
                  <div className="mb-3 grid gap-3 sm:grid-cols-4">
                    <div>
                      <p className="text-2xs uppercase text-content-tertiary">{t('condition.total', { defaultValue: 'Total at today\'s prices' })}</p>
                      <p className="text-lg font-semibold tabular-nums">{money(plan.totals.cost)}</p>
                    </div>
                    <div>
                      <p className="text-2xs uppercase text-content-tertiary">{t('condition.total_inflated', { defaultValue: 'Total with inflation' })}</p>
                      <p className="text-lg font-semibold tabular-nums">{money(plan.totals.cost_inflated)}</p>
                      <p className="text-2xs text-content-tertiary">
                        {fmtPercent(Number(plan.inflation_rate) * 100, 1)}{' '}
                        {plan.inflation_source === 'price_index'
                          ? t('condition.inflation_from_index', { defaultValue: 'per year, from the price index' })
                          : t('condition.inflation_per_year', { defaultValue: 'per year' })}
                      </p>
                    </div>
                    <div>
                      <p className="text-2xs uppercase text-content-tertiary">{t('condition.present_value', { defaultValue: 'Present value' })}</p>
                      <p className="text-lg font-semibold tabular-nums">{money(plan.totals.present_value)}</p>
                    </div>
                    <div>
                      <p className="text-2xs uppercase text-content-tertiary">{t('condition.annual', { defaultValue: 'Average per year' })}</p>
                      <p className="text-lg font-semibold tabular-nums">{money(plan.totals.annual_equivalent)}</p>
                    </div>
                  </div>
                  {plan.totals.unpriced_actions > 0 && (
                    <p className="mb-2 text-xs text-amber-600">
                      {t('condition.unpriced_note', {
                        defaultValue: '{{count}} actions have no unit cost and are not in the totals.',
                        count: plan.totals.unpriced_actions,
                      })}
                    </p>
                  )}
                  {plan.currencies.length > 1 && (
                    <p className="mb-2 text-xs text-amber-600">
                      {t('condition.mixed_currencies', { defaultValue: 'Actions are priced in more than one currency; totals add them as plain numbers.' })}
                    </p>
                  )}
                  <div className="space-y-1">
                    {plan.years.map((y) => (
                      <div key={y.year} className="flex items-center gap-3 text-xs">
                        <span className="w-12 tabular-nums text-content-secondary">{y.year}</span>
                        <div className="h-4 flex-1 rounded bg-surface-secondary">
                          <div className="h-4 rounded bg-oe-blue/70" style={{ width: `${(Number(y.cost_inflated) / maxYear) * 100}%` }} />
                        </div>
                        <span className="w-32 text-right tabular-nums">{money(y.cost_inflated)}</span>
                        <span className="w-10 text-right text-content-tertiary">{y.items.length}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              <Card padding="none" className="overflow-x-auto">
                <table className="w-full min-w-[860px]">
                  <thead className="bg-surface-secondary text-left text-xs text-content-tertiary">
                    <tr>
                      <th className="px-4 py-2 font-medium">{t('condition.element', { defaultValue: 'Asset or element' })}</th>
                      <th className="py-2 font-medium">{t('condition.col_action', { defaultValue: 'Action' })}</th>
                      <th className="py-2 font-medium">{t('condition.col_year', { defaultValue: 'Year' })}</th>
                      <th className="py-2 font-medium">{t('condition.quantity', { defaultValue: 'Quantity of the element' })}</th>
                      <th className="py-2 font-medium">{t('condition.unit_cost', { defaultValue: 'Unit cost of the work' })}</th>
                      <th className="py-2 font-medium">{t('condition.col_status', { defaultValue: 'Status' })}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody className="[&>tr>td:first-child]:px-4">{(actionsQ.data ?? []).map(actionRow)}</tbody>
                </table>
                {(actionsQ.data ?? []).length === 0 && !actionsQ.isLoading && (
                  <p className="p-4 text-sm text-content-tertiary">
                    {t('condition.no_actions', { defaultValue: 'No actions yet. Propose them from the ratings.' })}
                  </p>
                )}
              </Card>
            </div>
          )}

          {tab === 'checks' && (
            <Card className="p-4" data-testid="condition-checks">
              {checksQ.data ? (
                checksQ.data.results.length === 0 ? (
                  <p className="flex items-center gap-2 text-sm text-semantic-success">
                    <CheckCircle2 size={16} />
                    {t('condition.checks_passed', { defaultValue: 'All condition checks passed' })}
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {checksQ.data.results.map((r, i) => (
                      <li key={`${r.rule_id}-${i}`} className="flex items-start gap-2 text-sm">
                        <Badge variant={r.severity === 'error' ? 'error' : r.severity === 'warning' ? 'warning' : 'neutral'} size="sm">
                          {r.severity === 'error'
                            ? t('closeout.dossier.severity_error', { defaultValue: 'Error' })
                            : r.severity === 'warning'
                              ? t('closeout.dossier.severity_warning', { defaultValue: 'Warning' })
                              : t('closeout.dossier.severity_info', { defaultValue: 'Info' })}
                        </Badge>
                        <span>
                          {r.message}
                          {r.suggestion && <span className="text-content-tertiary"> {r.suggestion}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )
              ) : (
                <SkeletonTable rows={3} columns={2} />
              )}
            </Card>
          )}
        </>
      )}
      {showModal && projectId && (
        <AssessmentModal
          projectId={projectId}
          onClose={() => setShowModal(false)}
          onSaved={() => {
            setShowModal(false);
            invalidate();
          }}
        />
      )}
    </div>
  );
}

export default ConditionPage;
