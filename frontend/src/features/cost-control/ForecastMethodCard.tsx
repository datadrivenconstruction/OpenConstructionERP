// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How the project reads its forecast, and when a move needs a reason.
//
// The card says in one sentence per method what each one does, so the choice
// is made by meaning, not by name. Under it the evidence threshold, then the
// documentation checks: a forecast below what is already owed (V19), a large
// move on the open draft without a reason (V20), a line on its own method
// without a comment (V22). Each finding opens its line.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Save, SlidersHorizontal } from 'lucide-react';

import { Button, Skeleton } from '@/shared/ui';
import { fmtCurrency, fmtNumber } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { parseMoneyInput, stripCurrencySigns, toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { useToastStore } from '@/stores/useToastStore';
import { FORECAST_METHODS, costControlApi, type ForecastFinding, type ForecastMethod } from './api';
import { methodHelp, methodLabel, methodWhen } from './labels';

export interface ForecastMethodCardProps {
  projectId: string;
  currency: string;
  canManage: boolean;
  /** Open the line a finding is about. */
  onOpenLine: (key: string) => void;
  /** Open the draft a V20 finding is about. */
  onOpenDraft: (snapshotId: string) => void;
}

function FindingList({
  findings,
  onOpen,
}: {
  findings: ForecastFinding[];
  onOpen: (f: ForecastFinding) => void;
}) {
  const { t } = useTranslation();
  const [all, setAll] = useState(false);
  if (findings.length === 0) {
    return (
      <p className="text-sm text-content-secondary">
        {t('cost_control.method_findings_none', {
          defaultValue: 'Every forecast is explained: nothing below what is owed, no undocumented move.',
        })}
      </p>
    );
  }
  const shown = all ? findings : findings.slice(0, 4);
  return (
    <div>
      <ul className="space-y-1.5">
        {shown.map((f, i) => (
          <li key={`${f.rule_id}-${f.element_ref ?? i}`}>
            <button
              type="button"
              onClick={() => onOpen(f)}
              className="flex w-full items-start gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-surface-secondary/60"
            >
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-500" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm text-content-primary">{f.message}</span>
                <span className="block text-xs text-content-tertiary">{f.suggestion}</span>
              </span>
              <span className="shrink-0 rounded bg-surface-secondary px-1.5 py-px text-2xs font-semibold text-content-tertiary">
                {f.rule_number}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {findings.length > 4 && (
        <button
          type="button"
          className="mt-2 text-xs font-medium text-oe-blue hover:underline"
          onClick={() => setAll((v) => !v)}
        >
          {all
            ? t('cost_control.findings_less', { defaultValue: 'Show fewer' })
            : t('cost_control.findings_more', { defaultValue: 'Show all ({{n}})', n: findings.length })}
        </button>
      )}
    </div>
  );
}

export function ForecastMethodCard({ projectId, currency, canManage, onOpenLine, onOpenDraft }: ForecastMethodCardProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const panel = useQuery({
    queryKey: ['cost-control', 'forecast-panel', projectId],
    queryFn: () => costControlApi.forecastPanel(projectId),
  });

  const settings = panel.data?.settings;
  const [method, setMethod] = useState<ForecastMethod>('best_available');
  const [amount, setAmount] = useState('');
  const [pct, setPct] = useState('');
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (!settings || editing) return;
    setMethod(settings.forecast_method);
    setAmount(Number(settings.evidence_threshold_amount) > 0 ? settings.evidence_threshold_amount : '');
    setPct(settings.evidence_threshold_pct ?? '');
  }, [settings, editing]);

  const save = useMutation({
    mutationFn: () =>
      costControlApi.saveSettings(projectId, {
        forecast_method: method,
        evidence_threshold_amount: amount.trim() ? toDecimalPayloadString(stripCurrencySigns(amount)) : '0',
        evidence_threshold_pct: pct.trim() ? toDecimalPayloadString(pct.replace('%', '')) : null,
      }),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ['cost-control'] });
      addToast({ type: 'success', title: t('cost_control.method_saved', { defaultValue: 'Forecast method saved' }) });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.method_save_failed', { defaultValue: 'Could not save the forecast method' }),
        message: getErrorMessage(err),
      }),
  });

  if (panel.isLoading) return <Skeleton className="h-40 w-full" />;
  if (panel.error || !panel.data || !settings) {
    return <p className="text-sm text-semantic-error">{getErrorMessage(panel.error)}</p>;
  }
  const data = panel.data;
  const amountValid = !amount.trim() || parseMoneyInput(amount) !== null;
  const pctValid = !pct.trim() || (parseMoneyInput(pct.replace('%', '')) ?? -1) >= 0;
  const thresholdAmount = Number(settings.evidence_threshold_amount);
  const thresholdPct = settings.evidence_threshold_pct ? Number(settings.evidence_threshold_pct) : 0;

  const thresholdSentence =
    thresholdAmount > 0 && thresholdPct > 0
      ? t('cost_control.threshold_both', {
          defaultValue:
            'A line that moved by more than {{amount}} and more than {{pct}}% since the last frozen snapshot needs a comment and evidence before the next one can be frozen.',
          amount: fmtCurrency(settings.evidence_threshold_amount, currency),
          pct: fmtNumber(thresholdPct, 1),
        })
      : thresholdAmount > 0
        ? t('cost_control.threshold_amount_only', {
            defaultValue:
              'A line that moved by more than {{amount}} since the last frozen snapshot needs a comment and evidence before the next one can be frozen.',
            amount: fmtCurrency(settings.evidence_threshold_amount, currency),
          })
        : thresholdPct > 0
          ? t('cost_control.threshold_pct_only', {
              defaultValue:
                'A line that moved by more than {{pct}}% since the last frozen snapshot needs a comment and evidence before the next one can be frozen.',
              pct: fmtNumber(thresholdPct, 1),
            })
          : t('cost_control.threshold_any', {
              defaultValue: 'Every line that moved since the last frozen snapshot needs a comment and evidence.',
            });

  const counts = FORECAST_METHODS.filter((m) => (data.method_counts[m] ?? 0) > 0).map((m) =>
    t('cost_control.method_count', {
      defaultValue: '{{method}}: {{n}}',
      method: methodLabel(t, m),
      n: data.method_counts[m] ?? 0,
    }),
  );

  const openFinding = (f: ForecastFinding) => {
    if (f.rule_id === 'cost_forecast.move_without_evidence' && data.open_draft) onOpenDraft(data.open_draft.id);
    else if (f.element_ref) onOpenLine(f.element_ref);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-content-primary">
            {t('cost_control.method_title', { defaultValue: 'How the forecast is read' })}
          </h2>
          <p className="text-xs text-content-tertiary">
            {t('cost_control.method_subtitle', {
              defaultValue: 'One method for the whole project. Any line can still be read another way from its drawer.',
            })}
          </p>
        </div>
        {canManage && !editing && (
          <Button variant="secondary" size="sm" icon={<SlidersHorizontal size={14} />} onClick={() => setEditing(true)}>
            {t('cost_control.method_change', { defaultValue: 'Change method' })}
          </Button>
        )}
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" role="radiogroup">
        {FORECAST_METHODS.map((m) => {
          const active = (editing ? method : settings.forecast_method) === m;
          return (
            <label
              key={m}
              className={`flex flex-col gap-1 rounded-lg border px-3 py-2.5 ${
                active ? 'border-oe-blue bg-oe-blue-subtle/40' : 'border-border-light'
              } ${editing ? 'cursor-pointer' : ''}`}
            >
              <span className="flex items-center gap-2">
                <input
                  type="radio"
                  name="forecast-method"
                  checked={active}
                  disabled={!editing}
                  onChange={() => setMethod(m)}
                />
                <span className="text-sm font-medium text-content-primary">{methodLabel(t, m)}</span>
                {m === 'best_available' && (
                  <span className="text-2xs text-content-tertiary">
                    {t('cost_control.method_default', { defaultValue: 'default' })}
                  </span>
                )}
              </span>
              <span className="text-xs text-content-secondary">{methodHelp(t, m)}</span>
              <span className="text-2xs text-content-tertiary">{methodWhen(t, m)}</span>
            </label>
          );
        })}
      </div>

      {editing ? (
        <form
          className="space-y-3 rounded-xl border border-border-light p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (amountValid && pctValid) save.mutate();
          }}
        >
          <p className="text-sm text-content-secondary">
            {t('cost_control.threshold_explain', {
              defaultValue:
                'When does a move need a reason? Leave a field empty to skip that test. With both filled in, a move must exceed both.',
            })}
          </p>
          <div className="flex flex-wrap gap-4">
            <label className="block text-sm">
              <span className="text-content-secondary">
                {t('cost_control.threshold_amount', { defaultValue: 'More than (amount)' })}
              </span>
              <input
                className="mt-1 h-9 w-40 rounded-lg border border-border bg-surface-primary px-3 text-right tabular-nums"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                aria-invalid={!amountValid}
              />
            </label>
            <label className="block text-sm">
              <span className="text-content-secondary">
                {t('cost_control.threshold_pct', { defaultValue: 'More than (% of the last figure)' })}
              </span>
              <input
                className="mt-1 h-9 w-40 rounded-lg border border-border bg-surface-primary px-3 text-right tabular-nums"
                inputMode="decimal"
                value={pct}
                onChange={(e) => setPct(e.target.value)}
                aria-invalid={!pctValid}
              />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" type="button" onClick={() => setEditing(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              type="submit"
              icon={<Save size={14} />}
              disabled={!amountValid || !pctValid || save.isPending}
            >
              {t('cost_control.method_save', { defaultValue: 'Save' })}
            </Button>
          </div>
        </form>
      ) : (
        <p className="text-sm text-content-secondary">{thresholdSentence}</p>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-content-tertiary">
        {counts.length > 0 && (
          <span>
            {t('cost_control.method_counts', { defaultValue: 'Lines by method:' })} {counts.join(' · ')}
          </span>
        )}
        {data.line_choices > 0 && (
          <span>
            {t('cost_control.method_line_choices', {
              defaultValue: 'Lines on their own method: {{n}}',
              n: data.line_choices,
            })}
          </span>
        )}
        {data.fallback_lines > 0 && (
          <span>
            {t('cost_control.method_fallback', {
              defaultValue: 'Lines with nothing for their method yet, read by the best available source: {{n}}',
              n: data.fallback_lines,
            })}
          </span>
        )}
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('cost_control.method_findings', { defaultValue: 'Documentation checks' })}
        </h3>
        <FindingList findings={data.findings} onOpen={openFinding} />
      </div>
    </div>
  );
}
