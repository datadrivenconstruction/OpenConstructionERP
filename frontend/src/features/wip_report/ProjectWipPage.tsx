// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** One project's WIP: live figures, validation findings, closed month-end periods and the estimated-cost override. */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Lock, Undo2 } from 'lucide-react';
import { Button, Card, ConfirmDialog, EmptyState } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { formatCurrency } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import {
  barPercent,
  billingPosition,
  closePeriod,
  fadeClass,
  fadeTone,
  isValidAmount,
  isValidPeriod,
  latestPeriod,
  previousMonth,
  reopenPeriod,
  ruleKey,
  saveForecast,
  useWipForecast,
  useWipLive,
  useWipMutation,
  useWipPeriods,
  useWipValidation,
  type WipFinding,
} from './api';

const inputCls =
  'h-9 w-full rounded-md border border-border-light bg-surface-primary px-2.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

const RULE_DEFAULTS: Record<string, string> = {
  billed_exceeds_contract: 'Billed to date exceeds the contract value',
  percent_complete_over_100: 'Cost to date is above the estimated total cost',
  eac_below_cost_to_date: 'Estimated total cost is below the cost already spent',
  large_fade: 'Projected profit fell sharply since the last closed month',
  loss_job: 'The job is forecast to finish at a loss',
};

function severityClass(s: WipFinding['severity']): string {
  if (s === 'error') return 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-400';
  if (s === 'warning') return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400';
  return 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-400';
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <Card padding="md">
      <div className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${tone ?? 'text-content-primary'}`}>{value}</div>
    </Card>
  );
}

export function ProjectWipPage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const liveQ = useWipLive(projectId);
  const validationQ = useWipValidation(projectId);
  const periodsQ = useWipPeriods(projectId);
  const forecastQ = useWipForecast(projectId);

  const [period, setPeriod] = useState(previousMonth());
  const [notes, setNotes] = useState('');
  const [estimate, setEstimate] = useState('');
  const [note, setNote] = useState('');

  useEffect(() => {
    if (forecastQ.data) {
      setEstimate(forecastQ.data.estimated_cost ?? '');
      setNote(forecastQ.data.note ?? '');
    }
  }, [forecastQ.data]);

  const onError = (err: unknown) =>
    addToast({ type: 'error', title: t('wip_report.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });

  const closeMut = useWipMutation((vars: { period: string; notes?: string }) => closePeriod(projectId, vars));
  const reopenMut = useWipMutation((p: string) => reopenPeriod(projectId, p));
  const forecastMut = useWipMutation((body: { estimated_cost: string | null; note: string }) => saveForecast(projectId, body));

  const row = liveQ.data;
  const periods = periodsQ.data ?? [];
  const latest = latestPeriod(periods);
  const findings = validationQ.data?.findings ?? [];
  const cur = row?.currency ?? '';
  const pos = row ? billingPosition(row) : 'even';
  const money = (v: string | null | undefined) => formatCurrency(v ?? '0', cur);

  const handleReopen = async () => {
    if (!latest) return;
    const ok = await confirm({
      title: t('wip_report.reopen_title', { defaultValue: 'Reopen the latest month?' }),
      message: t('wip_report.reopen_msg', { defaultValue: 'The closed figures for {{period}} are deleted. Fade is then measured against the month before.', period: latest.period }),
      confirmLabel: t('wip_report.reopen', { defaultValue: 'Reopen latest' }),
      variant: 'danger',
    });
    if (ok) reopenMut.mutate(latest.period, { onError });
  };

  const forecastValid = estimate.trim() === '' || isValidAmount(estimate);

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('wip_report.title', { defaultValue: 'WIP report' })}
        subtitle={row?.project_name ?? t('wip_report.project_subtitle', { defaultValue: 'Work in progress for this project' })}
        actions={
          <Link to="/portfolio/wip">
            <Button variant="secondary" size="sm" icon={<ArrowLeft size={14} />}>
              {t('wip_report.back', { defaultValue: 'All projects' })}
            </Button>
          </Link>
        }
      />

      {liveQ.isLoading ? (
        <Card padding="lg" className="text-center text-sm text-content-tertiary">{t('wip_report.loading', { defaultValue: 'Loading...' })}</Card>
      ) : !row ? (
        <EmptyState title={t('wip_report.load_error', { defaultValue: 'The WIP report could not be loaded' })} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="wip-kpis">
            <Kpi label={t('wip_report.col_contract', { defaultValue: 'Contract value' })} value={money(row.contract_value)} />
            <Kpi label={t('wip_report.col_earned', { defaultValue: 'Earned revenue' })} value={money(row.earned_revenue)} />
            <Kpi label={t('wip_report.col_billed', { defaultValue: 'Billed to date' })} value={money(row.billed_to_date)} />
            <Kpi
              label={pos === 'under' ? t('wip_report.col_under', { defaultValue: 'Under-billing' }) : t('wip_report.col_over', { defaultValue: 'Over-billing' })}
              value={money(pos === 'under' ? row.under_billing : row.over_billing)}
              tone={pos === 'over' ? 'text-amber-700 dark:text-amber-400' : pos === 'under' ? 'text-sky-700 dark:text-sky-400' : undefined}
            />
            <Kpi label={t('wip_report.col_cost_to_date', { defaultValue: 'Cost to date' })} value={money(row.cost_to_date)} />
            <Kpi label={t('wip_report.col_estimated_cost', { defaultValue: 'Estimated total cost' })} value={money(row.estimated_cost)} />
            <Kpi label={t('wip_report.col_profit', { defaultValue: 'Projected profit' })} value={`${money(row.projected_gross_profit)} (${row.projected_margin_pct}%)`} tone={row.loss_job ? 'text-rose-600' : undefined} />
            <Kpi
              label={t('wip_report.col_fade', { defaultValue: 'Fade / gain' })}
              value={row.fade == null ? '-' : money(row.fade)}
              tone={fadeClass(fadeTone(row.fade))}
            />
          </div>

          <Card padding="md">
            <div className="flex items-baseline justify-between text-xs text-content-secondary">
              <span>{t('wip_report.col_percent', { defaultValue: '% complete' })}</span>
              <span className="tabular-nums">{row.percent_complete}%</span>
            </div>
            <div className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-surface-secondary">
              <div className="h-full rounded-full bg-oe-blue" style={{ width: `${barPercent(row.percent_complete)}%` }} />
            </div>
            <p className="mt-2 text-2xs text-content-tertiary">
              {t('wip_report.explainer_short', { defaultValue: 'Percent complete = cost to date / estimated total cost.' })}
            </p>
          </Card>

          <Card padding="md">
            <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('wip_report.findings', { defaultValue: 'Findings' })}</h3>
            {findings.length === 0 ? (
              <p className="text-sm text-content-tertiary">{t('wip_report.findings_empty', { defaultValue: 'No findings. The figures pass every check.' })}</p>
            ) : (
              <ul className="space-y-2" data-testid="wip-findings">
                {findings.map((f, i) => (
                  <li key={`${f.rule_id}-${i}`} className={`rounded-md px-3 py-2 text-sm ${severityClass(f.severity)}`}>
                    <div className="font-medium">
                      {t(`wip_report.rule_${ruleKey(f.rule_id)}`, { defaultValue: RULE_DEFAULTS[ruleKey(f.rule_id)] ?? f.rule_id })}
                    </div>
                    {f.message && <div className="text-xs opacity-80">{f.message}</div>}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card padding="md">
            <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('wip_report.forecast_title', { defaultValue: 'Estimated total cost override' })}</h3>
            <p className="mb-3 text-xs text-content-tertiary">
              {t('wip_report.forecast_hint', { defaultValue: 'Leave empty to use the cost forecast from the project. A value here replaces it in the WIP figures.' })}
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="text-xs text-content-secondary">
                {t('wip_report.forecast_estimate', { defaultValue: 'Estimated total cost' })}
                <input className={`${inputCls} mt-1`} inputMode="decimal" value={estimate} onChange={(e) => setEstimate(e.target.value)} data-testid="wip-estimate" />
              </label>
              <label className="text-xs text-content-secondary sm:col-span-2">
                {t('wip_report.forecast_note', { defaultValue: 'Note' })}
                <input className={`${inputCls} mt-1`} value={note} onChange={(e) => setNote(e.target.value)} />
              </label>
            </div>
            <div className="mt-3 flex gap-2">
              <Button
                variant="primary"
                size="sm"
                loading={forecastMut.isPending}
                disabled={!forecastValid}
                onClick={() => forecastMut.mutate({ estimated_cost: estimate.trim() || null, note: note.trim() }, { onError })}
              >
                {t('wip_report.forecast_save', { defaultValue: 'Save override' })}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={forecastMut.isPending || (forecastQ.data?.estimated_cost == null && !forecastQ.data?.note)}
                onClick={() => {
                  setEstimate('');
                  setNote('');
                  forecastMut.mutate({ estimated_cost: null, note: '' }, { onError });
                }}
              >
                {t('wip_report.forecast_clear', { defaultValue: 'Clear override' })}
              </Button>
            </div>
          </Card>

          <Card padding="md">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <h3 className="text-sm font-semibold text-content-primary">{t('wip_report.periods_title', { defaultValue: 'Closed months' })}</h3>
              <div className="flex flex-wrap items-end gap-2">
                <label className="text-xs text-content-secondary">
                  {t('wip_report.period', { defaultValue: 'Month' })}
                  <input type="month" className={`${inputCls} mt-1`} value={period} onChange={(e) => setPeriod(e.target.value)} data-testid="wip-period" />
                </label>
                <label className="text-xs text-content-secondary">
                  {t('wip_report.period_notes', { defaultValue: 'Notes' })}
                  <input className={`${inputCls} mt-1`} value={notes} onChange={(e) => setNotes(e.target.value)} />
                </label>
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Lock size={14} />}
                  loading={closeMut.isPending}
                  disabled={!isValidPeriod(period)}
                  onClick={() =>
                    closeMut.mutate({ period, notes: notes.trim() || undefined }, { onSuccess: () => setNotes(''), onError })
                  }
                >
                  {t('wip_report.close_month', { defaultValue: 'Close month' })}
                </Button>
                <Button variant="secondary" size="sm" icon={<Undo2 size={14} />} disabled={!latest || reopenMut.isPending} onClick={handleReopen}>
                  {t('wip_report.reopen', { defaultValue: 'Reopen latest' })}
                </Button>
              </div>
            </div>
            {periods.length === 0 ? (
              <p className="text-sm text-content-tertiary">{t('wip_report.periods_empty', { defaultValue: 'No month closed yet. Close a month to freeze its figures and measure fade from it.' })}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[800px] text-sm" data-testid="wip-periods">
                  <thead>
                    <tr className="border-b border-border-light text-2xs uppercase tracking-wide text-content-tertiary">
                      <th className="px-2 py-2 text-left font-medium">{t('wip_report.period', { defaultValue: 'Month' })}</th>
                      <th className="px-2 py-2 text-right font-medium">{t('wip_report.col_percent', { defaultValue: '% complete' })}</th>
                      <th className="px-2 py-2 text-right font-medium">{t('wip_report.col_earned', { defaultValue: 'Earned revenue' })}</th>
                      <th className="px-2 py-2 text-right font-medium">{t('wip_report.col_billed', { defaultValue: 'Billed to date' })}</th>
                      <th className="px-2 py-2 text-right font-medium">{t('wip_report.col_over', { defaultValue: 'Over-billing' })}</th>
                      <th className="px-2 py-2 text-right font-medium">{t('wip_report.col_under', { defaultValue: 'Under-billing' })}</th>
                      <th className="px-2 py-2 text-right font-medium">{t('wip_report.col_profit', { defaultValue: 'Projected profit' })}</th>
                      <th className="px-2 py-2 text-left font-medium">{t('wip_report.closed_on', { defaultValue: 'Closed' })}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-light">
                    {periods.map((p) => (
                      <tr key={p.id}>
                        <td className="px-2 py-2 font-medium">{p.period}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{p.percent_complete}%</td>
                        <td className="px-2 py-2 text-right tabular-nums">{formatCurrency(p.earned_revenue, p.currency)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{formatCurrency(p.billed_to_date, p.currency)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{formatCurrency(p.over_billing, p.currency)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{formatCurrency(p.under_billing, p.currency)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{formatCurrency(p.projected_gross_profit, p.currency)}</td>
                        <td className="px-2 py-2 text-content-secondary"><DateDisplay value={p.created_at} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

export default ProjectWipPage;
