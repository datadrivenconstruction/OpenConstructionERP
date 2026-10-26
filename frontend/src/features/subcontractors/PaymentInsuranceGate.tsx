// Payment insurance gate​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The insurance gate of one pay application. While a mandatory certificate of
 * the subcontractor has lapsed the finance approval and mark-paid steps are
 * held; a manager can lift the hold with a recorded reason, which stays on the
 * pay application with who and when. The backend decides; this only shows it.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, ShieldCheck } from 'lucide-react';

import { Button } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { normalizeRole, ROLE_RANK } from '@/shared/lib/roles';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { getPaymentInsuranceCheck, overridePaymentInsurance, type PaymentApplication } from './api';
import { describeComplianceReasons } from './complianceReasons';
import { PaymentApprovalActions, type PaymentApprovalActionsProps } from './PaymentApprovalActions';

const MIN_REASON = 10;

function overrideError(err: unknown, t: ReturnType<typeof useTranslation>['t']): string {
  if (err instanceof ApiError && err.status === 403) {
    return t('subcontractors.insurance.override_forbidden', {
      defaultValue: 'Only a manager can override the insurance hold.',
    });
  }
  return getErrorMessage(err);
}

export function PaymentInsuranceGate({ paymentId }: { paymentId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const role = useAuthStore((s) => s.userRole);
  const rank = (ROLE_RANK as Readonly<Record<string, number>>)[normalizeRole(role)] ?? Number.NEGATIVE_INFINITY;
  const isManager = rank >= ROLE_RANK.manager;
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');

  const q = useInsuranceCheck(paymentId);
  const overrideMut = useMutation({
    mutationFn: () => overridePaymentInsurance(paymentId, reason.trim()),
    onSuccess: () => {
      setOpen(false);
      setReason('');
      qc.invalidateQueries({ queryKey: ['subcontractors', 'insuranceCheck', paymentId] });
      qc.invalidateQueries({ queryKey: ['subcontractors', 'insuranceProject'] });
      addToast({
        type: 'success',
        title: t('subcontractors.insurance.override_recorded', { defaultValue: 'Insurance override recorded' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: overrideError(err, t) }),
  });

  const data = q.data;
  if (!data) return null;

  if (data.overridden && data.override) {
    return (
      <p className="flex items-start gap-1 text-2xs text-content-secondary" data-testid="insurance-override-note">
        <ShieldCheck size={12} className="mt-0.5 shrink-0" />
        <span>
          {t('subcontractors.insurance.override_note', {
            defaultValue: 'Insurance hold overridden by {{who}} on {{date}}: {{reason}}',
            who: data.override.overridden_by ?? '-',
            date: data.override.overridden_at.slice(0, 10),
            reason: data.override.reason,
          })}
        </span>
      </p>
    );
  }
  if (!data.blocked) return null;

  return (
    <div
      className="rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-2xs text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-200"
      role="alert"
      data-testid="insurance-gate-banner"
    >
      <p className="flex items-start gap-1 font-semibold">
        <ShieldAlert size={12} className="mt-0.5 shrink-0" />
        {t('subcontractors.insurance.gate_title', { defaultValue: 'Payment held: mandatory insurance has lapsed' })}
      </p>
      {data.reasons.length > 0 && <p className="mt-0.5">{describeComplianceReasons(data.reasons, t)}</p>}
      {isManager && (
        <Button
          variant="secondary"
          size="sm"
          className="mt-1"
          onClick={() => setOpen(true)}
          data-testid="insurance-override-open"
        >
          {t('subcontractors.insurance.override_button', { defaultValue: 'Override with reason' })}
        </Button>
      )}
      <WideModal
        open={open}
        onClose={() => setOpen(false)}
        size="sm"
        busy={overrideMut.isPending}
        title={t('subcontractors.insurance.override_title', { defaultValue: 'Override the insurance hold' })}
        subtitle={t('subcontractors.insurance.override_subtitle', {
          defaultValue: 'The reason is kept on the pay application with your name and the time.',
        })}
        testId="insurance-override-dialog"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={overrideMut.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              loading={overrideMut.isPending}
              disabled={reason.trim().length < MIN_REASON}
              onClick={() => overrideMut.mutate()}
              data-testid="insurance-override-confirm"
            >
              {t('subcontractors.insurance.override_confirm', { defaultValue: 'Override' })}
            </Button>
          </>
        }
      >
        <label className="block text-xs font-medium text-content-secondary mb-1" htmlFor={`ins-reason-${paymentId}`}>
          {t('subcontractors.insurance.override_reason', { defaultValue: 'Reason (at least 10 characters)' })}
        </label>
        <textarea
          id={`ins-reason-${paymentId}`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={4}
          maxLength={2000}
          className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm"
          data-testid="insurance-override-reason"
        />
      </WideModal>
    </div>
  );
}

function useInsuranceCheck(paymentId: string) {
  return useQuery({
    queryKey: ['subcontractors', 'insuranceCheck', paymentId],
    queryFn: () => getPaymentInsuranceCheck(paymentId),
    enabled: !!paymentId,
    retry: false,
  });
}

/** The actions cell of a pay application row, with the insurance gate under it. */
export function PaymentRowActions(props: PaymentApprovalActionsProps) {
  const payment: PaymentApplication = props.payment;
  const open = payment.status === 'submitted' || payment.status === 'foreman_approved' || payment.status === 'finance_approved';
  const q = useInsuranceCheck(open ? payment.id : '');
  const held = !!q.data?.blocked && !q.data.overridden;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        <PaymentApprovalActions {...props} insuranceBlocked={held} />
      </div>
      {open && <PaymentInsuranceGate paymentId={payment.id} />}
    </div>
  );
}
