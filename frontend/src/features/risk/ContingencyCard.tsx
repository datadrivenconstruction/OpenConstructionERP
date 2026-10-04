// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Contingency card on the risk register: what the register expects (EMV and
 * a deterministic P80) against the contingency the finance budget holds, what
 * has been drawn for risks that occurred, and what is left.
 *
 * A risk that occurs is never drawn on its own. It is listed as pending with
 * a proposed amount, and a manager confirms the drawdown here, choosing the
 * line and the real figure. A mistaken confirmation can be reversed.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, CheckCircle2, PiggyBank, Undo2 } from 'lucide-react';
import { Badge, Button, Card, ConfirmDialog, WideModal, WideModalField } from '@/shared/ui';
import { fmtCurrency, fmtDate } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  canDrawContingency,
  confirmDrawdown,
  contingencyQueryKey,
  fetchContingency,
  lineRemaining,
  money,
  parseAmountInput,
  reverseDrawdown,
  type ContingencyPending,
  type ContingencyPosition,
  type ContingencyState,
} from './contingency';

const FINANCE_BUDGETS_HREF = '/finance?tab=budgets';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const STATE_BADGE: Record<ContingencyState, 'neutral' | 'success' | 'warning' | 'error'> = {
  no_allocation: 'neutral',
  covered: 'success',
  shortfall: 'warning',
  overdrawn: 'error',
};

function useStateLabel(): (state: ContingencyState) => string {
  const { t } = useTranslation();
  return (state) => {
    switch (state) {
      case 'covered':
        return t('risk.cont_state_covered', { defaultValue: 'Covered' });
      case 'shortfall':
        return t('risk.cont_state_shortfall', { defaultValue: 'Shortfall' });
      case 'overdrawn':
        return t('risk.cont_state_overdrawn', { defaultValue: 'Overdrawn' });
      default:
        return t('risk.cont_state_no_allocation', { defaultValue: 'Not allocated' });
    }
  };
}

/** Invalidate everything a drawdown changes, on both sides of the link. */
function useInvalidateContingency(projectId: string): () => void {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: contingencyQueryKey(projectId) });
    qc.invalidateQueries({ queryKey: ['finance-budgets', projectId] });
    qc.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
  };
}

/* ── Confirm dialog ───────────────────────────────────────────────────── */

function DrawdownDialog({
  projectId,
  position,
  pending,
  onClose,
}: {
  projectId: string;
  position: ContingencyPosition;
  pending: ContingencyPending;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const invalidate = useInvalidateContingency(projectId);
  const [budgetId, setBudgetId] = useState<string>(pending.proposed_budget_id ?? position.lines[0]?.budget_id ?? '');
  const [amount, setAmount] = useState<string>(
    pending.proposed_amount != null ? String(money(pending.proposed_amount)) : '',
  );
  const [note, setNote] = useState('');

  const line = position.lines.find((l) => l.budget_id === budgetId);
  const lineCurrency = line?.currency || position.currency;
  const parsed = parseAmountInput(amount);
  const remaining = lineRemaining(position.lines, budgetId);
  const exceeds = parsed != null && remaining != null && Number(parsed) > remaining;

  const mut = useMutation({
    mutationFn: () =>
      confirmDrawdown(projectId, pending.risk_id, {
        amount: parsed ?? '0',
        budget_id: budgetId || null,
        note: note.trim(),
      }),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('risk.cont_drawdown_confirmed', { defaultValue: 'Drawdown confirmed' }),
      });
      onClose();
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      size="md"
      busy={mut.isPending}
      title={t('risk.cont_dialog_title', { defaultValue: 'Confirm contingency drawdown' })}
      subtitle={`${pending.risk_code} · ${pending.risk_title}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={() => mut.mutate()} disabled={parsed == null || !budgetId || mut.isPending}>
            {mut.isPending
              ? t('common.saving', { defaultValue: 'Saving...' })
              : t('risk.cont_confirm_action', { defaultValue: 'Confirm drawdown' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-content-secondary">
          {t('risk.cont_dialog_body', {
            defaultValue:
              'The risk has occurred. Enter the amount it actually draws from contingency. The proposal is its cost impact; nothing is drawn until you confirm.',
          })}
        </p>
        {position.lines.length > 1 && (
          <WideModalField label={t('risk.cont_line', { defaultValue: 'Contingency line' })} htmlFor="cont-line" required>
            <select id="cont-line" value={budgetId} onChange={(e) => setBudgetId(e.target.value)} className={inputCls}>
              {position.lines.map((l) => (
                <option key={l.budget_id} value={l.budget_id}>
                  {(l.wbs_id || t('risk.cont_line_unnamed', { defaultValue: 'Contingency' })) +
                    ' · ' +
                    t('risk.cont_line_remaining', {
                      defaultValue: '{{amount}} left',
                      amount: fmtCurrency(money(l.remaining), l.currency || position.currency),
                    })}
                </option>
              ))}
            </select>
          </WideModalField>
        )}
        <WideModalField
          label={t('risk.cont_amount', { defaultValue: 'Amount ({{currency}})', currency: lineCurrency || '-' })}
          htmlFor="cont-amount"
          required
          hint={t('risk.cont_amount_hint', {
            defaultValue: 'Cost impact on the register: {{amount}}',
            amount: fmtCurrency(money(pending.impact_cost), pending.currency),
          })}
          error={
            amount.trim() && parsed == null
              ? t('risk.cont_amount_invalid', { defaultValue: 'Enter an amount greater than zero' })
              : undefined
          }
        >
          <input
            id="cont-amount"
            type="number"
            min={0}
            step="any"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        {exceeds && (
          <p className="flex items-start gap-1.5 text-xs text-semantic-warning" role="status">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            {t('risk.cont_exceeds', {
              defaultValue: 'This is more than the line has left ({{amount}}). The line will show as overdrawn.',
              amount: fmtCurrency(remaining ?? 0, lineCurrency),
            })}
          </p>
        )}
        <WideModalField label={t('risk.cont_note', { defaultValue: 'Note' })} htmlFor="cont-note">
          <textarea
            id="cont-note"
            value={note}
            maxLength={1000}
            rows={2}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t('risk.cont_note_placeholder', { defaultValue: 'e.g. dewatering subcontract, order 4711' })}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
          />
        </WideModalField>
      </div>
    </WideModal>
  );
}

/* ── Card ─────────────────────────────────────────────────────────────── */

export function ContingencyCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const canDraw = canDrawContingency(userRole);
  const stateLabel = useStateLabel();
  const invalidate = useInvalidateContingency(projectId);
  const [confirming, setConfirming] = useState<ContingencyPending | null>(null);
  const [reversing, setReversing] = useState<string | null>(null);

  const { data: position, isLoading, isError } = useQuery({
    queryKey: contingencyQueryKey(projectId),
    queryFn: () => fetchContingency(projectId),
    enabled: !!projectId,
  });

  const reverseMut = useMutation({
    mutationFn: (riskId: string) => reverseDrawdown(projectId, riskId),
    onSuccess: () => {
      invalidate();
      setReversing(null);
      addToast({ type: 'success', title: t('risk.cont_drawdown_reversed', { defaultValue: 'Drawdown reversed' }) });
    },
    onError: (e: Error) => {
      setReversing(null);
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message });
    },
  });

  const unconverted = useMemo(
    () => Object.entries(position?.unconverted_emv ?? {}).filter(([, v]) => money(v) !== 0),
    [position],
  );

  if (isLoading || isError || !position) return null;

  const cur = position.currency;
  const fmt = (v: Parameters<typeof money>[0], c: string = cur) => fmtCurrency(money(v), c);
  const remainingNum = money(position.remaining);
  const gapNum = money(position.coverage_gap);

  const stats: { label: string; value: string; sub?: string; cls: string }[] = [
    {
      label: t('risk.cont_emv', { defaultValue: 'Risk-based (EMV)' }),
      value: fmt(position.emv),
      sub:
        position.percentile_method === 'exact'
          ? t('risk.cont_p80_exact', { defaultValue: 'P80 {{amount}}', amount: fmt(position.p80) })
          : t('risk.cont_p80_approx', { defaultValue: 'P80 about {{amount}}', amount: fmt(position.p80) }),
      cls: 'text-content-primary',
    },
    {
      label: t('risk.cont_allocated', { defaultValue: 'Allocated' }),
      value: fmt(position.allocated),
      cls: 'text-content-primary',
    },
    {
      label: t('risk.cont_drawn', { defaultValue: 'Drawn' }),
      value: fmt(position.drawn),
      cls: 'text-content-primary',
    },
    {
      label: t('risk.cont_remaining', { defaultValue: 'Remaining' }),
      value: fmt(position.remaining),
      cls:
        position.state === 'overdrawn'
          ? 'text-semantic-error'
          : position.state === 'shortfall'
            ? 'text-semantic-warning'
            : 'text-semantic-success',
    },
  ];

  let verdict: string;
  if (position.state === 'no_allocation') {
    verdict = t('risk.cont_verdict_none', {
      defaultValue:
        'The finance budget has no contingency line yet. Add a budget line with the category Contingency to set money aside for these risks.',
    });
  } else if (position.state === 'overdrawn') {
    verdict = t('risk.cont_verdict_overdrawn', {
      defaultValue: 'Contingency is overdrawn by {{amount}}.',
      amount: fmtCurrency(Math.abs(remainingNum), cur),
    });
  } else if (position.state === 'shortfall') {
    verdict = t('risk.cont_verdict_shortfall', {
      defaultValue: 'The contingency left is {{amount}} short of the open risk exposure.',
      amount: fmtCurrency(Math.abs(gapNum), cur),
    });
  } else {
    verdict = t('risk.cont_verdict_covered', {
      defaultValue: 'The contingency left covers the open risk exposure, with {{amount}} to spare.',
      amount: fmtCurrency(gapNum, cur),
    });
  }

  const reversingRecord = position.drawdowns.find((d) => d.risk_id === reversing);

  return (
    <Card className="p-4" data-testid="risk-contingency-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary">
            <PiggyBank size={16} className="text-oe-blue" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('risk.cont_title', { defaultValue: 'Contingency' })}
            </h3>
            <p className="text-2xs text-content-tertiary">
              {t('risk.cont_subtitle', {
                defaultValue: 'Expected value of the open risks against the contingency in the finance budget.',
              })}
            </p>
          </div>
          <Badge variant={STATE_BADGE[position.state]}>{stateLabel(position.state)}</Badge>
        </div>
        <Link
          to={FINANCE_BUDGETS_HREF}
          className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue-text hover:underline"
        >
          {t('risk.cont_open_finance', { defaultValue: 'Open finance budget' })}
          <ArrowRight size={12} />
        </Link>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
            <p className="text-2xs uppercase tracking-wide text-content-tertiary">{s.label}</p>
            <p className={`mt-0.5 text-lg font-semibold tabular-nums ${s.cls}`}>{s.value}</p>
            {s.sub && (
              <p
                className="text-2xs text-content-tertiary tabular-nums"
                title={
                  position.percentile_method === 'exact'
                    ? t('risk.cont_p80_exact_hint', {
                        defaultValue:
                          'Exact 80th percentile of the register, each risk either happening at its full cost or not. Not the Monte Carlo result.',
                      })
                    : t('risk.cont_p80_approx_hint', {
                        defaultValue:
                          'Normal approximation of the 80th percentile, used for large registers. Not the Monte Carlo result.',
                      })
                }
              >
                {s.sub}
              </p>
            )}
          </div>
        ))}
      </div>

      <p className="mt-3 text-xs text-content-secondary">{verdict}</p>

      {position.missing_fx_rates.length > 0 && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-semantic-warning">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            {t('risk.cont_missing_fx', {
              defaultValue:
                'No exchange rate to {{currency}} for {{codes}}. Those amounts are left out of the totals; add the rate in the project settings.',
              currency: cur || '-',
              codes: position.missing_fx_rates.join(', '),
            })}
            {unconverted.length > 0 && (
              <span className="ml-1 tabular-nums">
                ({unconverted.map(([c, v]) => fmtCurrency(money(v), c)).join(', ')})
              </span>
            )}
          </span>
        </p>
      )}

      {position.lines.length > 1 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-content-tertiary">
                <th className="py-1 text-left font-medium">{t('risk.cont_line', { defaultValue: 'Contingency line' })}</th>
                <th className="py-1 text-right font-medium">{t('risk.cont_allocated', { defaultValue: 'Allocated' })}</th>
                <th className="py-1 text-right font-medium">{t('risk.cont_drawn', { defaultValue: 'Drawn' })}</th>
                <th className="py-1 text-right font-medium">{t('risk.cont_remaining', { defaultValue: 'Remaining' })}</th>
              </tr>
            </thead>
            <tbody>
              {position.lines.map((l) => (
                <tr key={l.budget_id} className="border-t border-border-light">
                  <td className="py-1 text-content-secondary">
                    {l.wbs_id || t('risk.cont_line_unnamed', { defaultValue: 'Contingency' })}
                  </td>
                  <td className="py-1 text-right tabular-nums">{fmt(l.allocated, l.currency)}</td>
                  <td className="py-1 text-right tabular-nums">{fmt(l.drawn, l.currency)}</td>
                  <td className="py-1 text-right tabular-nums">{fmt(l.remaining, l.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {position.pending.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-semibold text-content-primary">
            {t('risk.cont_pending_title', { defaultValue: 'Occurred, waiting for a drawdown' })}
          </p>
          <ul className="mt-1.5 divide-y divide-border-light rounded-lg border border-border-light">
            {position.pending.map((p) => (
              <li key={p.risk_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <span className="min-w-0 text-sm">
                  <span className="font-mono text-xs text-content-tertiary">{p.risk_code}</span>{' '}
                  <span className="text-content-primary">{p.risk_title}</span>
                </span>
                <span className="flex items-center gap-3">
                  <span className="text-xs tabular-nums text-content-secondary">
                    {t('risk.cont_impact', { defaultValue: 'Impact {{amount}}', amount: fmt(p.impact_cost, p.currency) })}
                  </span>
                  {canDraw && position.lines.length > 0 ? (
                    <Button size="sm" variant="secondary" onClick={() => setConfirming(p)}>
                      {t('risk.cont_confirm_action', { defaultValue: 'Confirm drawdown' })}
                    </Button>
                  ) : (
                    <span className="text-2xs text-content-tertiary">
                      {position.lines.length === 0
                        ? t('risk.cont_needs_line', { defaultValue: 'Needs a contingency line' })
                        : t('risk.cont_needs_manager', { defaultValue: 'A manager confirms the drawdown' })}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {position.drawdowns.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-semibold text-content-primary">
            {t('risk.cont_drawdowns_title', { defaultValue: 'Confirmed drawdowns' })}
          </p>
          <ul className="mt-1.5 divide-y divide-border-light rounded-lg border border-border-light">
            {position.drawdowns.map((d) => (
              <li
                key={`${d.budget_id}:${d.risk_id ?? d.risk_code}`}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
              >
                <span className="min-w-0 text-sm">
                  <CheckCircle2 size={13} className="mr-1 inline text-semantic-success" />
                  <span className="font-mono text-xs text-content-tertiary">{d.risk_code}</span>{' '}
                  <span className="text-content-primary">{d.risk_title}</span>
                  {d.note && <span className="ml-1 text-xs text-content-tertiary">· {d.note}</span>}
                </span>
                <span className="flex items-center gap-3">
                  <span className="text-xs tabular-nums text-content-primary">{fmt(d.amount, d.currency)}</span>
                  {d.confirmed_at && (
                    <span className="text-2xs text-content-tertiary">{fmtDate(d.confirmed_at)}</span>
                  )}
                  {canDraw && d.risk_id && (
                    <button
                      type="button"
                      onClick={() => setReversing(d.risk_id)}
                      className="inline-flex items-center gap-1 text-2xs font-medium text-content-tertiary hover:text-semantic-error"
                    >
                      <Undo2 size={12} />
                      {t('risk.cont_reverse', { defaultValue: 'Reverse' })}
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {confirming && (
        <DrawdownDialog
          projectId={projectId}
          position={position}
          pending={confirming}
          onClose={() => setConfirming(null)}
        />
      )}

      <ConfirmDialog
        open={reversing !== null}
        onConfirm={() => reversing && reverseMut.mutate(reversing)}
        onCancel={() => setReversing(null)}
        title={t('risk.cont_reverse_title', { defaultValue: 'Reverse this drawdown?' })}
        message={t('risk.cont_reverse_message', {
          defaultValue: '{{amount}} goes back to the contingency line and the risk waits for a new confirmation.',
          amount: reversingRecord ? fmt(reversingRecord.amount, reversingRecord.currency) : '',
        })}
        confirmLabel={t('risk.cont_reverse', { defaultValue: 'Reverse' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="warning"
        loading={reverseMut.isPending}
      />
    </Card>
  );
}
