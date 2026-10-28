// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PayAppLinesDialog — one subcontractor pay application's lines, claimed next
// to approved.
//
// Two uses. Opened to approve the payment, it asks for the amount approved on
// each line, starting at what was claimed; a person can lower a figure, never
// raise it past the claim, and nothing is approved until they confirm. That
// per-line figure is what the GC progress claim bills for the sub's work.
// Opened to look, it shows the same table read-only, so a line approved below
// its claim stays visible as the difference rather than disappearing into a
// total.
//
// Either way it ends on what is payable: the claimed gross less what was not
// approved, less retention at the agreement's rate. The claimed header stays
// as the sub sent it, because the lien waiver gate reads that net; paying it
// would pay the sub for what finance did not approve.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { CheckCheck, Loader2 } from 'lucide-react';

import { Button } from '@/shared/ui';
import { WideModal, WideModalSection } from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import {
  listPaymentApplicationLines,
  listWorkPackages,
  type ApprovedLineAmount,
  type PaymentApplication,
  type PaymentApplicationLine,
} from './api';

function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined || v === '') return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

/** A typed amount is usable when it is a number from zero up to the claim. */
function amountProblem(raw: string, claimed: number): 'invalid' | 'above' | null {
  if (raw.trim() === '') return 'invalid';
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return 'invalid';
  // Compared in cents, so 1800.00 typed against a 1800 claim is not "above".
  if (Math.round(n * 100) > Math.round(claimed * 100)) return 'above';
  return null;
}

const cents = (v: number) => Math.round(v * 100);

/** The retention rate the claimed header was worked out at, for when the agreement's is not to hand. */
function headerRate(payment: PaymentApplication): number {
  const gross = toNum(payment.gross_amount);
  return gross > 0 ? (toNum(payment.retention_amount) / gross) * 100 : 0;
}

export interface PayAppLinesDialogProps {
  payment: PaymentApplication;
  mode: 'view' | 'approve';
  busy?: boolean;
  /** The agreement's retention percent, which the payable is worked out at. */
  retentionPercent?: number | string;
  onClose: () => void;
  /** Approve mode: called with every line's confirmed amount. */
  onApprove?: (lines: ApprovedLineAmount[]) => void;
}

export function PayAppLinesDialog({
  payment,
  mode,
  busy = false,
  retentionPercent,
  onClose,
  onApprove,
}: PayAppLinesDialogProps) {
  const { t } = useTranslation();
  const linesQ = useQuery({
    queryKey: ['subcontractors', 'pay-app-lines', payment.id],
    queryFn: () => listPaymentApplicationLines(payment.id),
  });
  const packagesQ = useQuery({
    queryKey: ['subcontractors', 'workPackages', payment.agreement_id],
    queryFn: () => listWorkPackages(payment.agreement_id),
  });
  const packageName = useMemo(
    () => new Map((packagesQ.data ?? []).map((wp) => [wp.id, wp.name])),
    [packagesQ.data],
  );
  const lines: PaymentApplicationLine[] = linesQ.data ?? [];

  // Approve mode starts each line at what it already has approved, or at the
  // claim when nothing is set yet, which is how the portal submits a line.
  const [typed, setTyped] = useState<Record<string, string>>({});
  useEffect(() => {
    if (mode !== 'approve' || !linesQ.data) return;
    setTyped(
      Object.fromEntries(
        linesQ.data.map((ln) => {
          const approved = toNum(ln.approved_amount);
          return [ln.id, String(approved > 0 ? ln.approved_amount : ln.claimed_amount)];
        }),
      ),
    );
  }, [mode, linesQ.data]);

  // Before finance approval a line has no approved figure to show yet.
  const approvedKnown = mode === 'approve' || payment.status === 'finance_approved' || payment.status === 'paid';
  const approvedOf = (ln: PaymentApplicationLine) =>
    mode === 'approve' ? toNum(typed[ln.id]) : toNum(ln.approved_amount);
  const problems = mode === 'approve'
    ? lines.map((ln) => amountProblem(typed[ln.id] ?? '', toNum(ln.claimed_amount)))
    : [];
  const blocked = problems.some((p) => p !== null);
  const claimedTotal = lines.reduce((acc, ln) => acc + toNum(ln.claimed_amount), 0);
  const approvedTotal = lines.reduce((acc, ln) => acc + approvedOf(ln), 0);
  const money = (v: number) => <MoneyDisplay amount={v} currency={payment.currency || undefined} />;
  const loading = linesQ.isLoading || packagesQ.isLoading;

  // The same arithmetic the server does on approval, in cents. Once it has
  // approved, its stored figure is shown instead; a pay application approved
  // before that figure existed was paid as claimed.
  const payable = (() => {
    if (mode === 'view') {
      if (payment.approved_net_amount !== null && payment.approved_net_amount !== undefined) {
        return toNum(payment.approved_net_amount);
      }
      return approvedKnown ? toNum(payment.net_amount) : null;
    }
    if (blocked) return null;
    const notApproved = lines.reduce(
      (acc, ln) => acc + Math.max(cents(toNum(ln.claimed_amount)) - cents(approvedOf(ln)), 0),
      0,
    );
    const gross = Math.max(cents(toNum(payment.gross_amount)) - notApproved, 0);
    const rate = retentionPercent !== undefined ? toNum(retentionPercent) : headerRate(payment);
    return (gross - Math.round((gross * rate) / 100)) / 100;
  })();

  const confirm = () =>
    onApprove?.(lines.map((ln) => ({ line_id: ln.id, approved_amount: (typed[ln.id] ?? '').trim() })));

  return (
    <WideModal
      open
      onClose={onClose}
      size="lg"
      busy={busy}
      title={
        mode === 'approve'
          ? t('subcontractors.pay_app_approve_title', {
              number: payment.application_number,
              defaultValue: 'Approve payment {{number}}',
            })
          : t('subcontractors.pay_app_lines_title', {
              number: payment.application_number,
              defaultValue: 'Lines of {{number}}',
            })
      }
      subtitle={
        mode === 'approve'
          ? t('subcontractors.pay_app_approve_subtitle', {
              defaultValue:
                'Confirm the amount approved on each line. It starts at the amount claimed and can be lowered, never raised. What is not approved stays visible on the line.',
            })
          : undefined
      }
      footer={
        mode === 'approve' ? (
          <>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              onClick={confirm}
              loading={busy}
              disabled={loading || blocked}
              icon={<CheckCheck size={14} />}
              data-testid="pay-app-approve-confirm"
            >
              {t('subcontractors.pay_app_approve_payment', { defaultValue: 'Approve payment' })}
            </Button>
          </>
        ) : undefined
      }
    >
      <WideModalSection>
        {loading ? (
          <p className="py-6 text-center text-sm text-content-tertiary">
            <Loader2 size={16} className="mr-2 inline animate-spin" />
            {t('common.loading', { defaultValue: 'Loading…' })}
          </p>
        ) : lines.length === 0 ? (
          <p className="text-sm text-content-secondary" role="status" data-testid="pay-app-no-lines">
            {t('subcontractors.pay_app_no_lines', {
              defaultValue: 'This pay application has no lines. Approving it approves its gross amount.',
            })}{' '}
            {t('subcontractors.pay_app_no_lines_not_billed', {
              defaultValue: 'It will not feed a progress claim until it has lines.',
            })}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="pay-app-lines">
              <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-content-tertiary">
                <tr>
                  <th className="px-3 py-2 text-left">
                    {t('subcontractors.pay_app_col_package', { defaultValue: 'Work package' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('subcontractors.pay_app_col_claimed', { defaultValue: 'Claimed' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('subcontractors.pay_app_col_approved', { defaultValue: 'Approved' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('subcontractors.pay_app_col_not_approved', { defaultValue: 'Not approved' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {lines.map((ln, i) => {
                  const name = packageName.get(ln.work_package_id) ?? ln.work_package_id.slice(0, 8);
                  const claimed = toNum(ln.claimed_amount);
                  const gap = claimed - approvedOf(ln);
                  const problem = problems[i];
                  return (
                    <tr key={ln.id} className="border-t border-border-light align-top">
                      <td className="px-3 py-2 text-content-primary">{name}</td>
                      <td className="px-3 py-2 text-right">{money(claimed)}</td>
                      <td className="px-3 py-2 text-right">
                        {mode === 'approve' ? (
                          <>
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              max={claimed}
                              value={typed[ln.id] ?? ''}
                              onChange={(e) => setTyped((prev) => ({ ...prev, [ln.id]: e.target.value }))}
                              className="h-8 w-32 rounded-md border border-border-light bg-surface-primary px-2 text-right text-sm tabular-nums"
                              aria-label={t('subcontractors.pay_app_approved_label', {
                                name,
                                defaultValue: 'Approved amount for {{name}}',
                              })}
                              aria-invalid={problem !== null}
                              disabled={busy}
                              data-testid="pay-app-approved-input"
                            />
                            {problem === 'above' && (
                              <p className="mt-0.5 text-xs text-semantic-error" role="alert">
                                {t('subcontractors.pay_app_above_claimed', {
                                  defaultValue: 'Cannot exceed the amount claimed.',
                                })}
                              </p>
                            )}
                          </>
                        ) : approvedKnown ? (
                          money(approvedOf(ln))
                        ) : (
                          '—'
                        )}
                      </td>
                      <td
                        className={
                          approvedKnown && gap > 0.004
                            ? 'px-3 py-2 text-right text-amber-700 dark:text-amber-300'
                            : 'px-3 py-2 text-right text-content-tertiary'
                        }
                        data-testid="pay-app-line-gap"
                      >
                        {approvedKnown && gap > 0.004 ? money(gap) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t border-border-light font-medium">
                  <td className="px-3 py-2">{t('subcontractors.pay_app_total', { defaultValue: 'Total' })}</td>
                  <td className="px-3 py-2 text-right">{money(claimedTotal)}</td>
                  <td className="px-3 py-2 text-right" data-testid="pay-app-approved-total">
                    {approvedKnown ? money(approvedTotal) : '—'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {approvedKnown && claimedTotal - approvedTotal > 0.004 ? money(claimedTotal - approvedTotal) : '—'}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
        {!loading && (
          <p
            className="mt-3 flex items-center justify-between border-t border-border-light pt-2 text-sm font-medium"
            data-testid="pay-app-payable"
          >
            <span>{t('subcontractors.pay_app_payable', { defaultValue: 'Payable after retention' })}</span>
            <span>{payable === null ? '—' : money(payable)}</span>
          </p>
        )}
      </WideModalSection>
    </WideModal>
  );
}
