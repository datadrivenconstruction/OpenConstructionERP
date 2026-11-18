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
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCheck, Loader2, Save } from 'lucide-react';

import { Button } from '@/shared/ui';
import { WideModal, WideModalSection } from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import {
  listPaymentApplicationLines,
  listWorkPackages,
  updatePaymentApplicationLineQuantities,
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

/** Quantities stay open until finance approves; after that they are what the money was decided on. */
const QTY_OPEN = new Set(['submitted', 'foreman_approved']);
const QTY_FIELDS = ['claimed_qty', 'assessed_qty', 'certified_qty'] as const;
type QtyField = (typeof QTY_FIELDS)[number];
type QtyDraft = Record<string, Record<QtyField, string>>;

const qtyStr = (v: number | string | null | undefined) => String(toNum(v));

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
  const qc = useQueryClient();

  // Claimed / assessed / certified quantity per line, saved together.
  const qtyEditable = QTY_OPEN.has(payment.status) && !busy;
  const [qtyTyped, setQtyTyped] = useState<QtyDraft>({});
  const [qtyFindings, setQtyFindings] = useState<Record<string, string[]>>({});
  useEffect(() => {
    if (!linesQ.data) return;
    setQtyTyped(
      Object.fromEntries(
        linesQ.data.map((ln) => [
          ln.id,
          { claimed_qty: qtyStr(ln.claimed_qty), assessed_qty: qtyStr(ln.assessed_qty), certified_qty: qtyStr(ln.certified_qty) },
        ]),
      ),
    );
  }, [linesQ.data]);
  const changedQty = lines.filter((ln) =>
    QTY_FIELDS.some((f) => (qtyTyped[ln.id]?.[f] ?? qtyStr(ln[f])) !== qtyStr(ln[f])),
  );
  const qtyInvalid = changedQty.some((ln) =>
    QTY_FIELDS.some((f) => {
      const n = Number(qtyTyped[ln.id]?.[f] ?? '');
      return !Number.isFinite(n) || n < 0;
    }),
  );
  const saveQtyMut = useMutation({
    mutationFn: async () => {
      const out: Record<string, string[]> = {};
      for (const ln of changedQty) {
        const draft = qtyTyped[ln.id] ?? { claimed_qty: '0', assessed_qty: '0', certified_qty: '0' };
        const saved = await updatePaymentApplicationLineQuantities(ln.id, {
          claimed_qty: draft.claimed_qty.trim() || '0',
          assessed_qty: draft.assessed_qty.trim() || '0',
          certified_qty: draft.certified_qty.trim() || '0',
        });
        out[ln.id] = (saved.findings ?? []).map((f) => f.message);
      }
      return out;
    },
    onSuccess: (out) => {
      setQtyFindings((prev) => ({ ...prev, ...out }));
      qc.invalidateQueries({ queryKey: ['subcontractors', 'pay-app-lines', payment.id] });
    },
  });
  const qtyCell = (ln: PaymentApplicationLine, field: QtyField, label: string) =>
    qtyEditable ? (
      <input
        type="text"
        inputMode="decimal"
        value={qtyTyped[ln.id]?.[field] ?? ''}
        onChange={(e) =>
          setQtyTyped((prev) => ({
            ...prev,
            [ln.id]: { ...(prev[ln.id] ?? { claimed_qty: '0', assessed_qty: '0', certified_qty: '0' }), [field]: e.target.value },
          }))
        }
        className="oe-input w-24 text-right tabular-nums"
        aria-label={label}
        data-testid={`pay-app-${field}`}
      />
    ) : (
      toNum(ln[field]).toLocaleString()
    );

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
            <table className="oe-table" data-testid="pay-app-lines">
              <thead>
                <tr>
                  <th>
                    {t('subcontractors.pay_app_col_package', { defaultValue: 'Work package' })}
                  </th>
                  <th className="text-right">
                    {t('commercial_control.qty_claimed', { defaultValue: 'Claimed qty' })}
                  </th>
                  <th className="text-right">
                    {t('commercial_control.qty_assessed', { defaultValue: 'Assessed qty' })}
                  </th>
                  <th className="text-right">
                    {t('commercial_control.qty_certified', { defaultValue: 'Certified qty' })}
                  </th>
                  <th className="text-right">
                    {t('subcontractors.pay_app_col_claimed', { defaultValue: 'Claimed' })}
                  </th>
                  <th className="text-right">
                    {t('subcontractors.pay_app_col_approved', { defaultValue: 'Approved' })}
                  </th>
                  <th className="text-right">
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
                    <tr key={ln.id} className="align-top">
                      <td>
                        {name}
                        {(qtyFindings[ln.id] ?? []).length > 0 && (
                          <p className="mt-0.5 flex items-start gap-1 text-xs text-semantic-warning" role="status">
                            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                            <span>{(qtyFindings[ln.id] ?? []).join(' ')}</span>
                          </p>
                        )}
                      </td>
                      <td className="text-right">
                        {qtyCell(ln, 'claimed_qty', t('commercial_control.qty_claimed', { defaultValue: 'Claimed qty' }))}
                      </td>
                      <td className="text-right">
                        {qtyCell(ln, 'assessed_qty', t('commercial_control.qty_assessed', { defaultValue: 'Assessed qty' }))}
                      </td>
                      <td className="text-right">
                        {qtyCell(ln, 'certified_qty', t('commercial_control.qty_certified', { defaultValue: 'Certified qty' }))}
                      </td>
                      <td className="text-right">{money(claimed)}</td>
                      <td className="text-right">
                        {mode === 'approve' ? (
                          <>
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              max={claimed}
                              value={typed[ln.id] ?? ''}
                              onChange={(e) => setTyped((prev) => ({ ...prev, [ln.id]: e.target.value }))}
                              className="oe-input w-32 text-right tabular-nums"
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
                            ? 'px-3 py-2 text-right text-semantic-warning'
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
                <tr className="font-medium">
                  <td colSpan={4}>{t('subcontractors.pay_app_total', { defaultValue: 'Total' })}</td>
                  <td className="text-right">{money(claimedTotal)}</td>
                  <td className="text-right" data-testid="pay-app-approved-total">
                    {approvedKnown ? money(approvedTotal) : '—'}
                  </td>
                  <td className="text-right">
                    {approvedKnown && claimedTotal - approvedTotal > 0.004 ? money(claimedTotal - approvedTotal) : '—'}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
        {!loading && qtyEditable && lines.length > 0 && (
          <div className="mt-2 flex items-center justify-end gap-2">
            {saveQtyMut.isError && (
              <span className="text-xs text-semantic-error" role="alert">
                {t('commercial_control.save_quantities_failed', { defaultValue: 'Could not save the quantities' })}
              </span>
            )}
            <Button
              size="sm"
              variant="secondary"
              icon={<Save size={12} />}
              onClick={() => saveQtyMut.mutate()}
              loading={saveQtyMut.isPending}
              disabled={changedQty.length === 0 || qtyInvalid}
              data-testid="pay-app-save-quantities"
            >
              {t('commercial_control.save_quantities', { defaultValue: 'Save quantities' })}
            </Button>
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
