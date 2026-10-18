// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One cost line, opened: where its forecast comes from, the figures behind it,
// a place to enter your own forecast (only with a reason), and the history that
// explains how the line got here - saved forecasts, approved changes and every
// manual forecast with who said it and why.
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, GitCommitHorizontal, PenLine, Save } from 'lucide-react';

import { Button, Skeleton } from '@/shared/ui';
import { SideDrawer } from '@/shared/ui/SideDrawer';
import { fmtCurrency, fmtDate } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { parseMoneyInput, stripCurrencySigns, toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { useToastStore } from '@/stores/useToastStore';
import { costControlApi, num, type CostControlRow, type LineHistory } from './api';
import { methodHelp, sourceExplanation, sourceLabel, sourceTone, stageLabel } from './labels';
import { LineMethodSection } from './LineMethodSection';

interface TimelineEntry {
  date: string;
  kind: 'snapshot' | 'change' | 'override' | 'override_removed';
  title: string;
  amount: string | null;
  detail: string;
}

function buildTimeline(t: ReturnType<typeof useTranslation>['t'], h: LineHistory): TimelineEntry[] {
  const out: TimelineEntry[] = [];
  for (const s of h.snapshots) {
    out.push({
      date: s.taken_on,
      kind: 'snapshot',
      title: s.label || stageLabel(t, s.stage),
      amount: s.forecast,
      detail: sourceLabel(t, s.forecast_source),
    });
  }
  for (const c of h.changes) {
    out.push({
      date: c.approved_on ?? '',
      kind: 'change',
      title: t('cost_control.history_change', {
        defaultValue: 'Change {{code}} approved',
        code: c.source_code || '',
      }),
      amount: c.amount,
      detail: c.contract_code,
    });
  }
  for (const o of h.overrides) {
    out.push({
      date: (o.created_at ?? '').slice(0, 10),
      kind: 'override',
      title: t('cost_control.history_override', { defaultValue: 'Own forecast entered' }),
      amount: o.amount,
      detail: [o.reason, o.document_ref].filter(Boolean).join(' · '),
    });
    if (o.closed_at) {
      out.push({
        date: o.closed_at.slice(0, 10),
        kind: 'override_removed',
        title: t('cost_control.history_override_closed', { defaultValue: 'Own forecast replaced or removed' }),
        amount: null,
        detail: '',
      });
    }
  }
  return out.sort((a, b) => b.date.localeCompare(a.date));
}

export interface LineDrawerProps {
  projectId: string;
  row: CostControlRow | null;
  currency: string;
  canEdit: boolean;
  onClose: () => void;
}

export function LineDrawer({ projectId, row, currency, canEdit, onClose }: LineDrawerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [documentRef, setDocumentRef] = useState('');
  const [editing, setEditing] = useState(false);

  const lineId = row?.key ?? '';
  const { data: history, isLoading } = useQuery({
    queryKey: ['cost-control', 'history', lineId],
    queryFn: () => costControlApi.lineHistory(lineId),
    enabled: !!row && row.kind === 'cost_line',
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['cost-control', 'report', projectId] });
    queryClient.invalidateQueries({ queryKey: ['cost-control', 'history', lineId] });
    queryClient.invalidateQueries({ queryKey: ['cost-control', 'forecast-panel', projectId] });
  };

  const save = useMutation({
    mutationFn: () =>
      costControlApi.setForecast(lineId, {
        amount: toDecimalPayloadString(stripCurrencySigns(amount)),
        reason: reason.trim(),
        document_ref: documentRef.trim(),
      }),
    onSuccess: () => {
      refresh();
      setEditing(false);
      setAmount('');
      setReason('');
      setDocumentRef('');
      addToast({ type: 'success', title: t('cost_control.override_saved', { defaultValue: 'Forecast saved' }) });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.override_failed', { defaultValue: 'Could not save the forecast' }),
        message: getErrorMessage(err),
      }),
  });

  const clear = useMutation({
    mutationFn: () => costControlApi.clearForecast(lineId),
    onSuccess: () => {
      refresh();
      addToast({
        type: 'success',
        title: t('cost_control.override_cleared', { defaultValue: 'Back to the automatic forecast' }),
      });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.override_clear_failed', { defaultValue: 'Could not remove the forecast' }),
        message: getErrorMessage(err),
      }),
  });

  const current = history?.current ?? row;
  const timeline = useMemo(() => (history ? buildTimeline(t, history) : []), [history, t]);
  const amountValid = parseMoneyInput(amount) !== null;
  const reasonValid = reason.trim().length >= 3;

  const figures: { label: string; value: string; strong?: boolean }[] = current
    ? [
        { label: t('cost_control.col_planned', { defaultValue: 'Planned' }), value: current.planned },
        { label: t('cost_control.col_awarded', { defaultValue: 'Awarded' }), value: current.awarded },
        { label: t('cost_control.col_changes', { defaultValue: 'Changes' }), value: current.changes },
        { label: t('cost_control.col_measured', { defaultValue: 'Measured' }), value: current.measured },
        { label: t('cost_control.col_certified', { defaultValue: 'Certified' }), value: current.certified },
        { label: t('cost_control.col_invoiced', { defaultValue: 'Invoiced' }), value: current.invoiced },
        { label: t('cost_control.col_paid', { defaultValue: 'Paid' }), value: current.paid },
      ]
    : [];

  return (
    <SideDrawer
      open={!!row}
      onClose={onClose}
      title={row ? `${row.code} ${row.description}`.trim() : ''}
      subtitle={t('cost_control.drawer_subtitle', { defaultValue: 'Where the forecast comes from and how it moved' })}
      widthClass="w-full max-w-xl"
    >
      {current && (
        <div className="space-y-6">
          <section className="rounded-xl border border-border-light p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {t('cost_control.col_forecast', { defaultValue: 'Forecast' })}
                </div>
                <div className="text-2xl font-bold tabular-nums text-content-primary">
                  {fmtCurrency(current.forecast, currency)}
                </div>
              </div>
              <span className={`rounded px-2 py-0.5 text-xs font-medium ${sourceTone(current.forecast_source)}`}>
                {sourceLabel(t, current.forecast_source)}
              </span>
            </div>
            {/* A line read with the highest figure or projected from progress is explained by its
                method: the source sentence would say why that figure is the most reliable one. */}
            <p className="mt-2 text-sm text-content-secondary">
              {(current.forecast_method === 'maximum' || current.forecast_method === 'evm_cpi') && current.method_applied
                ? methodHelp(t, current.forecast_method)
                : sourceExplanation(t, current.forecast_source)}
            </p>
            {current.override && (
              <p className="mt-2 text-xs text-content-tertiary">
                {t('cost_control.automatic_would_be', {
                  defaultValue: 'Without your forecast it would be {{amount}} ({{source}}).',
                  amount: fmtCurrency(current.automatic_forecast, currency),
                  source: sourceLabel(t, current.automatic_source),
                })}
              </p>
            )}
            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
              {figures.map((f) => (
                <div key={f.label}>
                  <dt className="text-2xs text-content-tertiary">{f.label}</dt>
                  <dd className="tabular-nums text-content-primary">{fmtCurrency(f.value, currency)}</dd>
                </div>
              ))}
            </dl>
          </section>

          {history && history.methods.length > 0 && (
            <LineMethodSection projectId={projectId} history={history} currency={currency} canEdit={canEdit} />
          )}

          {canEdit && (
            <section>
              {!editing ? (
                <div className="flex flex-wrap gap-2">
                  <Button variant="secondary" size="sm" icon={<PenLine size={14} />} onClick={() => setEditing(true)}>
                    {current.override
                      ? t('cost_control.override_change', { defaultValue: 'Change your forecast' })
                      : t('cost_control.override_set', { defaultValue: 'Enter your own forecast' })}
                  </Button>
                  {current.override && (
                    <Button variant="ghost" size="sm" onClick={() => clear.mutate()} disabled={clear.isPending}>
                      {t('cost_control.override_clear', { defaultValue: 'Use the automatic forecast again' })}
                    </Button>
                  )}
                </div>
              ) : (
                <form
                  className="space-y-3 rounded-xl border border-border-light p-4"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (amountValid && reasonValid) save.mutate();
                  }}
                >
                  <p className="text-xs text-content-secondary">
                    {t('cost_control.override_explain', {
                      defaultValue:
                        'Use this when you know more than the data, for example a new offer or work still to be let. The reason is kept in the history.',
                    })}
                  </p>
                  <label className="block text-sm">
                    <span className="text-content-secondary">
                      {t('cost_control.override_amount', { defaultValue: 'Expected final cost' })}
                    </span>
                    <input
                      className="mt-1 h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-right tabular-nums"
                      inputMode="decimal"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      placeholder={String(num(current.forecast))}
                      autoFocus
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="text-content-secondary">
                      {t('cost_control.override_reason', { defaultValue: 'Why (required)' })}
                    </span>
                    <textarea
                      className="mt-1 w-full rounded-lg border border-border bg-surface-primary px-3 py-2"
                      rows={2}
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder={t('cost_control.override_reason_placeholder', {
                        defaultValue: 'e.g. second offer from the tiler is 4% higher',
                      })}
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="text-content-secondary">
                      {t('cost_control.override_document', { defaultValue: 'Document (optional)' })}
                    </span>
                    <input
                      className="mt-1 h-9 w-full rounded-lg border border-border bg-surface-primary px-3"
                      value={documentRef}
                      onChange={(e) => setDocumentRef(e.target.value)}
                      placeholder={t('cost_control.override_document_placeholder', {
                        defaultValue: 'e.g. offer of 12.10., email of 05.06.',
                      })}
                    />
                  </label>
                  <div className="flex justify-end gap-2">
                    <Button variant="ghost" size="sm" type="button" onClick={() => setEditing(false)}>
                      {t('common.cancel', { defaultValue: 'Cancel' })}
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      type="submit"
                      icon={<Save size={14} />}
                      disabled={!amountValid || !reasonValid || save.isPending}
                    >
                      {t('cost_control.override_save', { defaultValue: 'Save forecast' })}
                    </Button>
                  </div>
                </form>
              )}
            </section>
          )}

          <section>
            <h3 className="mb-3 text-sm font-semibold text-content-primary">
              {t('cost_control.history_title', { defaultValue: 'History' })}
            </h3>
            {isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : timeline.length === 0 ? (
              <p className="text-sm text-content-tertiary">
                {t('cost_control.history_empty', {
                  defaultValue: 'Nothing yet. Saved forecasts, approved changes and your own forecasts appear here.',
                })}
              </p>
            ) : (
              <ol className="space-y-3 border-l border-border-light pl-4">
                {timeline.map((e, i) => (
                  <li key={`${e.kind}-${e.date}-${i}`} className="relative">
                    <span className="absolute -left-[22px] top-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-surface-primary">
                      {e.kind === 'change' ? (
                        <GitCommitHorizontal size={12} className="text-indigo-500" />
                      ) : e.kind === 'snapshot' ? (
                        <FileText size={12} className="text-sky-500" />
                      ) : (
                        <PenLine size={12} className="text-violet-500" />
                      )}
                    </span>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-sm text-content-primary">{e.title}</span>
                      {e.amount !== null && (
                        <span className="shrink-0 text-sm font-medium tabular-nums text-content-primary">
                          {e.kind === 'change' && num(e.amount) > 0 ? '+' : ''}
                          {fmtCurrency(e.amount, currency)}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-content-tertiary">
                      {e.date ? fmtDate(e.date) : ''}
                      {e.detail ? ` · ${e.detail}` : ''}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      )}
    </SideDrawer>
  );
}
