// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What-If Impact Simulator (TOP-30 #11).
 *
 * A read-only, collapsible panel on the change-order detail view that shows
 * the cost, finish-date, earned-value and BOQ consequences of approving a
 * change order *before* anyone commits to it. The projection is deterministic
 * (computed server-side from the project's budget and FX rates, never an LLM),
 * so it always works. Optional cost / extra-days overrides let a reviewer model
 * an alternative; "Publish scenario" snapshots the projection into the audit
 * trail. Nothing here mutates the change order itself.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Calculator,
  TrendingUp,
  CalendarClock,
  Layers,
  RefreshCw,
  Save,
  ChevronDown,
  ChevronUp,
  Info,
  History,
} from 'lucide-react';
import { Button, Card, Badge } from '@/shared/ui';
import { fmtDate, fmtPercent } from '@/shared/lib/formatters';

/** Locale-aware "12. Aug. 2026, 21:16" datetime, matching DateDisplay's
 *  datetime format so the forecast stamp and the register tables agree. */
function fmtDateTime(iso: string): string {
  try {
    return fmtDate(iso, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}
import { useToastStore } from '@/stores/useToastStore';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import {
  simulateImpact,
  publishScenario,
  type SimulateImpactResponse,
} from './api';

function fmtMoney(value: string, currency: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  const code = (currency || '').trim().toUpperCase();
  try {
    if (code && /^[A-Z]{3}$/.test(code)) {
      return new Intl.NumberFormat(getNumberLocale(), {
        style: 'currency',
        currency: code,
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(n);
    }
  } catch {
    /* fall through to plain formatting */
  }
  return new Intl.NumberFormat(getNumberLocale(), {
    maximumFractionDigits: 0,
  }).format(n);
}

/** A before -> after row with a coloured delta. */
function DeltaRow({
  label,
  before,
  after,
  worseWhenUp = true,
  currency,
}: {
  label: string;
  before: string;
  after: string;
  worseWhenUp?: boolean;
  currency: string;
}) {
  const delta = Number(after) - Number(before);
  const moved = Math.abs(delta) > 0.005;
  const isUp = delta > 0;
  const tone = !moved
    ? 'text-content-tertiary'
    : (isUp ? worseWhenUp : !worseWhenUp)
      ? 'text-semantic-error'
      : 'text-semantic-success';
  return (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="text-content-secondary">{label}</span>
      <span className="flex items-center gap-2 font-medium tabular-nums">
        <span className="text-content-tertiary">{fmtMoney(before, currency)}</span>
        <span className="text-content-tertiary">&rarr;</span>
        <span className={tone}>{fmtMoney(after, currency)}</span>
      </span>
    </div>
  );
}

/** One saved what-if scenario from the CO metadata (service.publish_scenario). */
export interface SavedScenario {
  at?: string;
  snapshot?: Partial<SimulateImpactResponse>;
}

export function ImpactSimulator({
  orderId,
  defaultCost,
  defaultDays,
  canPublish,
  savedScenarios = [],
}: {
  orderId: string;
  defaultCost: string;
  defaultDays: number;
  canPublish: boolean;
  /** Previously published scenarios from order.metadata.simulations (newest
   *  last, max 10). Shown as a small read-only history so "Save scenario"
   *  has a visible, lasting effect. */
  savedScenarios?: SavedScenario[];
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(true);
  const [showAdjust, setShowAdjust] = useState(false);
  // Draft override inputs (what the user is typing).
  const [costInput, setCostInput] = useState('');
  const [daysInput, setDaysInput] = useState('');
  // Committed overrides that actually drive the query (via "Re-run").
  const [applied, setApplied] = useState<{ cost?: string; days?: number }>({});

  const queryBody = useMemo(() => {
    const body: { cost_impact?: string; schedule_impact_days?: number } = {};
    if (applied.cost !== undefined && applied.cost !== '') body.cost_impact = applied.cost;
    if (applied.days !== undefined) body.schedule_impact_days = applied.days;
    return body;
  }, [applied]);

  const { data, isLoading, isError, refetch, isFetching } = useQuery<SimulateImpactResponse>({
    queryKey: ['co-impact', orderId, queryBody],
    queryFn: () => simulateImpact(orderId, queryBody),
    enabled: open,
  });

  const publishMut = useMutation({
    mutationFn: () => publishScenario(orderId, queryBody),
    onSuccess: () => {
      // The backend appends to order.metadata.simulations; invalidate the
      // detail query so the saved scenario shows up in the history below
      // without a manual reload.
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      addToast({
        type: 'success',
        title: t('changeorders.scenario_published', {
          defaultValue: 'Scenario saved to the audit trail',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const runOverrides = () => {
    setApplied({
      cost: costInput.trim() === '' ? undefined : costInput.trim(),
      days: daysInput.trim() === '' ? undefined : Math.max(0, Math.round(Number(daysInput) || 0)),
    });
  };

  const resetOverrides = () => {
    setCostInput('');
    setDaysInput('');
    setApplied({});
  };

  const ccy = data?.base_currency || '';

  // The two shapes of "this scope does not land in a bill": several unlocked
  // bills, which the approval refuses to choose between, and no unlocked bill
  // at all. They are different sentences and the same warning, because to the
  // reader they mean the same thing - the preview is not promising a write.
  const boqNotPlaceable = Boolean(
    data && data.boq.item_count > 0 && (data.boq.target_boq_ambiguous || !data.boq.target_boq_name),
  );

  return (
    <Card className="mb-6 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-surface-secondary"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          <Calculator size={18} className="text-oe-blue" />
          <span className="text-base font-semibold text-content-primary">
            {t('changeorders.impact_title', { defaultValue: 'What-If Impact' })}
          </span>
          <Badge variant="blue" size="sm">
            {t('changeorders.impact_readonly', { defaultValue: 'Forecast' })}
          </Badge>
        </span>
        {open ? (
          <ChevronUp size={18} className="text-content-tertiary" />
        ) : (
          <ChevronDown size={18} className="text-content-tertiary" />
        )}
      </button>

      {open && (
        <div className="border-t border-border-light px-4 py-4">
          <p className="mb-4 text-xs text-content-tertiary">
            {t('changeorders.impact_intro', {
              defaultValue:
                'See the budget, finish date and earned-value effect of approving this change order. Nothing is saved.',
            })}
          </p>

          {isLoading ? (
            <p className="py-6 text-center text-sm text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </p>
          ) : isError || !data ? (
            <div className="flex items-center justify-between rounded-md bg-surface-secondary px-3 py-4">
              <span className="text-sm text-content-secondary">
                {t('changeorders.impact_error', {
                  defaultValue: 'Could not compute the projection right now.',
                })}
              </span>
              <Button variant="secondary" size="sm" onClick={() => refetch()}>
                {t('common.retry', { defaultValue: 'Retry' })}
              </Button>
            </div>
          ) : (
            <div className="space-y-5">
              {/* Cost */}
              <section>
                <h4 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                  <TrendingUp size={14} /> {t('changeorders.impact_cost', { defaultValue: 'Project budget' })}
                </h4>
                <DeltaRow
                  label={t('changeorders.impact_budget', { defaultValue: 'Revised budget' })}
                  before={data.cost.budget_before}
                  after={data.cost.budget_after}
                  currency={ccy}
                />
                <div className="mt-1 flex items-center gap-2 text-xs text-content-tertiary">
                  <span>
                    {t('changeorders.impact_delta', { defaultValue: 'This change order' })}:{' '}
                    <span className="font-medium text-content-secondary">
                      {fmtMoney(data.co_cost_base, ccy)}
                    </span>
                  </span>
                  {data.cost.pct_of_budget > 0 && (
                    <Badge variant="neutral" size="sm">
                      {fmtPercent(data.cost.pct_of_budget)}{' '}
                      {t('changeorders.impact_of_budget', { defaultValue: 'of budget' })}
                    </Badge>
                  )}
                  {!data.fx_converted && (
                    <Badge variant="warning" size="sm">
                      {t('changeorders.impact_no_fx', { defaultValue: 'No FX rate' })}
                    </Badge>
                  )}
                </div>
              </section>

              {/* Schedule */}
              <section>
                <h4 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                  <CalendarClock size={14} /> {t('changeorders.impact_schedule', { defaultValue: 'Schedule' })}
                </h4>
                {data.schedule.current_end_date ? (
                  <div className="flex items-center justify-between py-1.5 text-sm">
                    <span className="text-content-secondary">
                      {t('changeorders.impact_finish', { defaultValue: 'Project finish' })}
                    </span>
                    <span className="flex items-center gap-2 font-medium tabular-nums">
                      <span className="text-content-tertiary">{data.schedule.current_end_date}</span>
                      <span className="text-content-tertiary">&rarr;</span>
                      <span className={data.schedule.finish_moves ? 'text-semantic-error' : 'text-content-tertiary'}>
                        {data.schedule.projected_end_date}
                      </span>
                    </span>
                  </div>
                ) : (
                  <p className="py-1.5 text-sm text-content-secondary">
                    {data.schedule.finish_moves
                      ? t('changeorders.impact_days_only', {
                          defaultValue: 'Adds {{n}} days (no project end date set).',
                          n: data.schedule.days_added,
                        })
                      : t('changeorders.impact_no_sched', { defaultValue: 'No schedule change.' })}
                  </p>
                )}
                {data.schedule.finish_moves && data.schedule.current_end_date && (
                  <p className="text-xs text-semantic-error">
                    {t('changeorders.impact_slip', {
                      defaultValue: 'Finish moves out by {{n}} days.',
                      n: data.schedule.days_added,
                    })}
                  </p>
                )}
              </section>

              {/* EVM */}
              <section>
                <h4 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                  <TrendingUp size={14} /> {t('changeorders.impact_evm', { defaultValue: 'Earned value (EVM)' })}
                </h4>
                <DeltaRow
                  label={t('changeorders.impact_bac', { defaultValue: 'Budget at completion (BAC)' })}
                  before={data.evm.bac_before}
                  after={data.evm.bac_after}
                  currency={ccy}
                />
                <DeltaRow
                  label={t('changeorders.impact_eac', { defaultValue: 'Estimate at completion (EAC)' })}
                  before={data.evm.eac_before}
                  after={data.evm.eac_after}
                  currency={ccy}
                />
                <DeltaRow
                  label={t('changeorders.impact_vac', { defaultValue: 'Variance at completion (VAC)' })}
                  before={data.evm.vac_before}
                  after={data.evm.vac_after}
                  worseWhenUp={false}
                  currency={ccy}
                />
                <div className="mt-1 flex gap-2 text-xs">
                  <Badge variant="neutral" size="sm">SPI {data.evm.spi}</Badge>
                  <Badge variant="neutral" size="sm">CPI {data.evm.cpi}</Badge>
                </div>
              </section>

              {/* BOQ */}
              <section>
                <h4 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                  <Layers size={14} /> {t('changeorders.impact_boq', { defaultValue: 'Bill of quantities' })}
                </h4>
                {/* Three different facts used to share one sentence, and two
                    of them were rendered as the third. A nameless target fell
                    back to "the project BOQ", which reads as a promise: with
                    several unlocked bills the approval refuses to pick one,
                    and with none it writes nowhere at all. Either way the
                    preview promised a write that the action would not make.
                    Named bill, several bills, no bill - one sentence each,
                    and the middle one points at what resolves it. */}
                <p
                  className={
                    boqNotPlaceable
                      ? 'flex items-start gap-2 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning-strong'
                      : 'text-sm text-content-secondary'
                  }
                >
                  {boqNotPlaceable && <Info size={14} className="mt-0.5 shrink-0" />}
                  <span>
                  {data.boq.item_count === 0
                    ? t('changeorders.impact_boq_empty', {
                        defaultValue: 'No line items yet, so nothing would be written to the BOQ.',
                      })
                    : data.boq.target_boq_ambiguous
                    ? t('changeorders.impact_boq_ambiguous', {
                        defaultValue:
                          'This project has more than one unlocked bill of quantities, so the {{positions}} {{posLabel}} cannot be placed automatically. Name the bill when you approve this change order.',
                        positions: data.boq.positions_added,
                        posLabel:
                          data.boq.positions_added === 1
                            ? t('changeorders.impact_position', { defaultValue: 'position' })
                            : t('changeorders.impact_positions', { defaultValue: 'positions' }),
                      })
                    : !data.boq.target_boq_name
                    ? t('changeorders.impact_boq_none', {
                        defaultValue:
                          'This project has no unlocked bill of quantities, so the {{positions}} {{posLabel}} would not be written into one.',
                        positions: data.boq.positions_added,
                        posLabel:
                          data.boq.positions_added === 1
                            ? t('changeorders.impact_position', { defaultValue: 'position' })
                            : t('changeorders.impact_positions', { defaultValue: 'positions' }),
                      })
                    : t('changeorders.impact_boq_add', {
                        defaultValue: 'Will add 1 new section with {{positions}} {{posLabel}} to {{boq}}.',
                        positions: data.boq.positions_added,
                        posLabel:
                          data.boq.positions_added === 1
                            ? t('changeorders.impact_position', { defaultValue: 'position' })
                            : t('changeorders.impact_positions', { defaultValue: 'positions' }),
                        boq: data.boq.target_boq_name,
                      })}
                  </span>
                </p>
              </section>

              {/* Notes / caveats */}
              {data.notes.length > 0 && (
                <ul className="space-y-1 rounded-md bg-surface-secondary px-3 py-2">
                  {data.notes.map((n, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-content-tertiary">
                      <Info size={13} className="mt-0.5 shrink-0" />
                      <span>{n}</span>
                    </li>
                  ))}
                </ul>
              )}

              {/* Saved scenarios — read-only audit history of what reviewers
                  have published. Newest first. */}
              {savedScenarios.length > 0 && (
                <section>
                  <h4 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    <History size={14} />{' '}
                    {t('changeorders.impact_saved_scenarios', { defaultValue: 'Saved scenarios' })}
                    <Badge variant="neutral" size="sm">{savedScenarios.length}</Badge>
                  </h4>
                  <ul className="divide-y divide-border-light rounded-md border border-border-light">
                    {savedScenarios
                      .slice()
                      .reverse()
                      .map((s, i) => {
                        const snap = s.snapshot ?? {};
                        const ccyS = snap.base_currency || ccy;
                        return (
                          <li
                            key={`${s.at ?? 'scenario'}-${i}`}
                            className="flex items-center justify-between gap-3 px-3 py-2 text-xs"
                          >
                            <span className="text-content-tertiary">
                              {s.at
                                ? fmtDateTime(s.at)
                                : t('changeorders.impact_saved_unknown_date', { defaultValue: 'Saved scenario' })}
                            </span>
                            <span className="flex items-center gap-3 tabular-nums">
                              {snap.co_cost_base !== undefined && (
                                <span className="text-content-secondary">
                                  {t('changeorders.impact_delta', { defaultValue: 'This change order' })}:{' '}
                                  <span className="font-medium">{fmtMoney(snap.co_cost_base, ccyS)}</span>
                                </span>
                              )}
                              {snap.schedule?.days_added !== undefined && snap.schedule.days_added > 0 && (
                                <span className="text-content-secondary">
                                  +{snap.schedule.days_added}
                                  {t('changeorders.impact_days_suffix', { defaultValue: 'd' })}
                                </span>
                              )}
                            </span>
                          </li>
                        );
                      })}
                  </ul>
                </section>
              )}

              {/* Adjust + actions */}
              <div className="border-t border-border-light pt-3">
                <button
                  type="button"
                  onClick={() => setShowAdjust((v) => !v)}
                  className="text-xs font-medium text-oe-blue hover:underline"
                >
                  {showAdjust
                    ? t('changeorders.impact_hide_adjust', { defaultValue: 'Hide what-if controls' })
                    : t('changeorders.impact_show_adjust', { defaultValue: 'Try a what-if (adjust cost / days)' })}
                </button>
                {showAdjust && (
                  <div className="mt-3 flex flex-wrap items-end gap-3">
                    <label className="flex flex-col gap-1 text-xs text-content-tertiary">
                      {t('changeorders.impact_cost_override', { defaultValue: 'Cost impact override' })}
                      <input
                        type="number"
                        value={costInput}
                        placeholder={defaultCost}
                        onChange={(e) => setCostInput(e.target.value)}
                        className="w-40 rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-content-tertiary">
                      {t('changeorders.impact_days_override', { defaultValue: 'Extra days' })}
                      <input
                        type="number"
                        value={daysInput}
                        placeholder={String(defaultDays)}
                        onChange={(e) => setDaysInput(e.target.value)}
                        className="w-28 rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
                      />
                    </label>
                    <Button variant="secondary" size="sm" onClick={runOverrides} disabled={isFetching}>
                      <RefreshCw size={14} className={`mr-1 ${isFetching ? 'animate-spin' : ''}`} />
                      {t('changeorders.impact_rerun', { defaultValue: 'Re-run' })}
                    </Button>
                    {(applied.cost !== undefined || applied.days !== undefined) && (
                      <Button variant="ghost" size="sm" onClick={resetOverrides}>
                        {t('changeorders.impact_reset', { defaultValue: 'Reset' })}
                      </Button>
                    )}
                  </div>
                )}

                <div className="mt-3 flex items-center justify-between">
                  <span className="text-2xs text-content-tertiary">
                    {t('changeorders.impact_as_of', { defaultValue: 'Forecast as of' })}{' '}
                    {fmtDateTime(data.as_of)}
                  </span>
                  {canPublish && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => publishMut.mutate()}
                      disabled={publishMut.isPending}
                    >
                      <Save size={14} className="mr-1" />
                      {t('changeorders.impact_publish', { defaultValue: 'Save scenario' })}
                    </Button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
