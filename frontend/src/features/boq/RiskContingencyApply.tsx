// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Loader2, Undo2 } from 'lucide-react';
import { boqApi, type RiskContingencyStatus } from './api';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { fmtFixed, fmtPercent } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

const PRESETS = [50, 80] as const;

function money(v: string | number | null | undefined, fmt: Intl.NumberFormat): string {
  const n = typeof v === 'number' ? v : parseFloat(String(v ?? ''));
  return Number.isFinite(n) ? fmt.format(n) : '-';
}

/**
 * Turn the Monte Carlo result into a contingency line in the estimate.
 *
 * The estimator picks a percentile, reads the suggested amount with the run's
 * confidence, and confirms; the server recomputes the amount and refuses when
 * the bill moved since the preview. The applied line shows its run, whether
 * the risk inputs changed since (stale), and how far a re-run would move it.
 */
export function RiskContingencyApply({
  boqId,
  correlation,
  fmt,
}: {
  boqId: string;
  correlation: number;
  fmt: Intl.NumberFormat;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [percentile, setPercentile] = useState<number>(80);
  const [custom, setCustom] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [asPercentage, setAsPercentage] = useState(false);

  const queryKey = ['boq-risk-contingency', boqId, percentile, correlation];
  const { data, isFetching } = useQuery<RiskContingencyStatus>({
    queryKey,
    queryFn: () => boqApi.getRiskContingency(boqId, percentile, correlation),
    enabled: !!boqId,
    placeholderData: keepPreviousData,
  });

  const refresh = (next: RiskContingencyStatus) => {
    queryClient.setQueryData(queryKey, next);
    queryClient.invalidateQueries({ queryKey: ['boq-risk-contingency', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq-markups', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
  };

  const apply = useMutation({
    mutationFn: () =>
      boqApi.applyRiskContingency(boqId, {
        percentile,
        correlation,
        iterations: data?.suggestion?.iterations,
        expected_amount: data?.suggestion?.amount,
        ...(asPercentage ? { mode: 'percentage' as const } : {}),
        name: t('boq.risk_contingency_line_name', { defaultValue: 'Risk contingency P{{p}}', p: percentile }),
      }),
    onSuccess: (next) => {
      setConfirming(false);
      refresh(next);
      addToast({
        type: 'success',
        title: t('boq.risk_contingency_applied', {
          defaultValue: 'Contingency at P{{p}} added to the estimate',
          p: percentile,
        }),
      });
    },
    onError: (err) => {
      setConfirming(false);
      const moved = err instanceof ApiError && err.status === 409;
      queryClient.invalidateQueries({ queryKey: ['boq-risk-contingency', boqId] });
      addToast({
        type: 'error',
        title: moved
          ? t('boq.risk_contingency_moved', {
              defaultValue: 'The estimate changed since the preview. Check the new amount and confirm again.',
            })
          : getErrorMessage(err),
      });
    },
  });

  const undo = useMutation({
    mutationFn: () => boqApi.undoRiskContingency(boqId),
    onSuccess: (next) => {
      refresh(next);
      addToast({
        type: 'success',
        title: next.applied
          ? t('boq.risk_contingency_restored', {
              defaultValue: 'Previous contingency P{{p}} restored',
              p: next.applied.percentile,
            })
          : t('boq.risk_contingency_removed', { defaultValue: 'Contingency line removed from the estimate' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const s = data?.suggestion;
  const applied = data?.applied;
  const isPreset = (PRESETS as readonly number[]).includes(percentile);
  const confidenceLabel =
    s?.convergence_status === 'converged'
      ? t('boq.cost_risk_converged', { defaultValue: 'Converged' })
      : s?.convergence_status === 'marginal'
        ? t('boq.cost_risk_marginal', { defaultValue: 'Marginal' })
        : t('boq.cost_risk_low_confidence', { defaultValue: 'Low confidence' });

  const pickCustom = (raw: string) => {
    setCustom(raw);
    const n = Math.round(Number(raw));
    if (Number.isFinite(n) && n >= 50 && n <= 99) setPercentile(n);
  };

  return (
    <div className="rounded-lg border border-border-light px-4 py-3 space-y-3" data-testid="risk-contingency-apply">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-content-primary">
          {t('boq.risk_contingency_title', { defaultValue: 'Apply as contingency in the estimate' })}
        </span>
        <div className="flex items-center gap-1 ml-auto" role="group">
          {PRESETS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => {
                setPercentile(p);
                setCustom('');
                setConfirming(false);
              }}
              aria-pressed={percentile === p}
              className={`px-2 py-0.5 rounded text-2xs font-medium border ${
                percentile === p
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border-light text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              P{p}
            </button>
          ))}
          <label className="flex items-center gap-1 text-2xs text-content-secondary">
            {t('boq.risk_contingency_custom', { defaultValue: 'Custom P' })}
            <input
              type="number"
              min={50}
              max={99}
              value={isPreset ? custom : custom || String(percentile)}
              onChange={(e) => {
                setConfirming(false);
                pickCustom(e.target.value);
              }}
              aria-label={t('boq.risk_contingency_custom_hint', { defaultValue: 'Custom percentile, 50 to 99' })}
              className="w-12 rounded border border-border-light bg-surface-primary px-1 py-0.5 text-2xs tabular-nums"
            />
          </label>
        </div>
      </div>

      {s && (
        <div className="text-xs text-content-secondary space-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-base font-bold text-content-primary tabular-nums">{money(s.amount, fmt)}</span>
            <span className="tabular-nums">(+{fmtPercent(s.pct_of_base)})</span>
            <span
              className="tabular-nums"
              title={t('boq.risk_contingency_confidence_hint', {
                defaultValue: 'How stable the percentile is between the two halves of the run',
              })}
            >
              {confidenceLabel} · {fmtFixed(s.confidence * 100, 0)}%
            </span>
            {isFetching && <Loader2 size={12} className="animate-spin" aria-hidden />}
          </div>
          <div className="text-2xs text-content-tertiary">
            {t('boq.risk_contingency_basis', {
              defaultValue:
                'Lifts the direct cost of {{base}} to the P{{p}} budget of {{budget}}. Run: {{iterations}} iterations, seed {{seed}}.',
              base: money(s.base_total, fmt),
              budget: money(s.budget, fmt),
              p: s.percentile,
              iterations: s.iterations,
              seed: s.seed,
            })}
          </div>
          {s.below_base && (
            <div className="text-2xs text-content-tertiary">
              {t('boq.risk_contingency_below_base', {
                defaultValue: 'The base estimate already sits above P{{p}}, so no contingency is needed at this level.',
                p: s.percentile,
              })}
            </div>
          )}
        </div>
      )}

      {confirming ? (
        <div className="flex flex-wrap items-center gap-2 rounded bg-surface-secondary px-3 py-2 text-xs">
          <span className="text-content-primary">
            {t('boq.risk_contingency_confirm', {
              defaultValue: 'Add {{amount}} as a contingency line to the estimate? You can undo it.',
              amount: money(s?.amount, fmt),
            })}
          </span>
          <label className="inline-flex items-center gap-1.5 text-2xs text-content-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={asPercentage}
              onChange={(e) => setAsPercentage(e.target.checked)}
              className="h-3.5 w-3.5 accent-oe-blue"
            />
            {t('boq.risk_contingency_as_percentage', {
              defaultValue: 'Keep as a percentage of the direct cost, so it follows quantity edits',
            })}
          </label>
          {(data?.other_contingency?.length ?? 0) > 0 && (
            <span className="basis-full text-2xs text-amber-600" data-testid="risk-contingency-double-count">
              {t('boq.risk_contingency_double_count', {
                defaultValue: 'Another contingency line is active ({{names}}): the same risk may be counted twice.',
                names: (data?.other_contingency ?? []).join(', '),
              })}
            </span>
          )}
          <button
            type="button"
            onClick={() => apply.mutate()}
            disabled={apply.isPending}
            className="ml-auto rounded bg-oe-blue px-2.5 py-1 text-2xs font-medium text-white disabled:opacity-50"
          >
            {t('boq.risk_contingency_confirm_button', { defaultValue: 'Confirm' })}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded border border-border-light px-2.5 py-1 text-2xs text-content-secondary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          disabled={!s || s.below_base || isFetching}
          className="rounded bg-oe-blue px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
        >
          {applied
            ? t('boq.risk_contingency_replace', { defaultValue: 'Replace with P{{p}}', p: percentile })
            : t('boq.risk_contingency_apply', { defaultValue: 'Apply P{{p}} contingency', p: percentile })}
        </button>
      )}

      {applied && (
        <div
          className={`rounded border px-3 py-2 text-xs space-y-1 ${
            data?.stale ? 'border-amber-400/60 bg-amber-50/50 dark:bg-amber-950/20' : 'border-border-light'
          }`}
          data-testid="risk-contingency-applied"
        >
          <div className="flex flex-wrap items-center gap-2">
            {data?.stale ? (
              <AlertTriangle size={13} className="text-amber-500" aria-hidden />
            ) : (
              <CheckCircle2 size={13} className="text-semantic-success" aria-hidden />
            )}
            <span className="font-medium text-content-primary">
              {t('boq.risk_contingency_applied_line', {
                defaultValue: 'In the estimate: {{name}}, {{amount}}',
                name: applied.name,
                amount: money(applied.line_amount, fmt),
              })}
            </span>
            <button
              type="button"
              onClick={() => undo.mutate()}
              disabled={undo.isPending}
              className="ml-auto inline-flex items-center gap-1 rounded border border-border-light px-2 py-0.5 text-2xs text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
            >
              <Undo2 size={11} aria-hidden />
              {applied.can_undo_to_previous
                ? t('boq.risk_contingency_undo_previous', { defaultValue: 'Undo to previous' })
                : t('boq.risk_contingency_undo', { defaultValue: 'Remove' })}
            </button>
          </div>
          <div className="text-2xs text-content-tertiary">
            {t('boq.risk_contingency_provenance', {
              defaultValue: 'P{{p}}, seed {{seed}}, {{iterations}} iterations, applied {{date}} by {{who}}',
              p: applied.percentile,
              seed: applied.seed ?? '-',
              iterations: applied.iterations ?? '-',
              date: applied.applied_at ? new Date(applied.applied_at).toLocaleDateString() : '-',
              who: applied.applied_by_email || applied.applied_by || '-',
            })}
          </div>
          {data?.stale && (
            <div className="text-2xs text-amber-700 dark:text-amber-400">
              {t('boq.risk_contingency_stale', {
                defaultValue:
                  'Line totals changed since this was applied. A re-run at the same settings gives {{drift}} ({{pct}}). Re-apply to bring it up to date.',
                drift: `${Number(data.drift_amount) > 0 ? '+' : ''}${money(data.drift_amount, fmt)}`,
                pct: data.drift_pct == null ? '-' : fmtPercent(data.drift_pct),
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
