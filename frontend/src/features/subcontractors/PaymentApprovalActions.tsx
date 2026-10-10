// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PaymentApprovalActions — the next step of one subcontractor pay application's
// approval chain, on its row in the Payments tab.
//
// The chain is the backend's: submitted, then foreman approved ("the work was
// done"), then finance approved ("we will pay it"), then paid, and reject is
// open until it is paid. Each button offers exactly the step the pay
// application is at, to the roles the backend accepts for it. The role check
// here only decides what to OFFER; the backend still decides what is allowed.
//
// Finance approval and mark-paid are refused while the agreement requires a
// lien waiver and none covering the net is on file. The button says so before
// the click, from the same release check the row's waiver badge reads, rather
// than letting the person find out from a refusal.
//
// Finance approval is also where the amount approved on each line is set, and
// that figure is what the GC claim bills, so "Approve payment" opens the lines
// to confirm first. "Lines" shows the same table read-only to anyone who can
// see the row, claimed next to approved.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, CheckCheck, Banknote, X, ListTree, FileText } from 'lucide-react';
import type { TFunction } from 'i18next';

import { Button } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { normalizeRole, ROLE_RANK } from '@/shared/lib/roles';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  approvePaymentFinance,
  approvePaymentForeman,
  getPaymentReleaseCheck,
  markPaymentPaid,
  rejectPaymentApplication,
  type ApprovedLineAmount,
  type PaymentApplication,
} from './api';
import { PayAppLinesDialog } from './PayAppLinesDialog';
import {
  HakedisDialog,
  hakedisBaseKey,
  recordHakedisRefusal,
  type HakedisSource,
} from '@/features/contracts/hakedis';

type Step = 'approve_foreman' | 'approve_finance' | 'mark_paid' | 'reject';

// What each step asks of the caller's role, as in subcontractors/permissions.py:
// approve_payment_foreman (foreman step and reject) is EDITOR, and
// approve_payment_finance (finance step and mark-paid) is MANAGER.
const REQUIRED_RANK: Record<Step, number> = {
  approve_foreman: ROLE_RANK.editor,
  reject: ROLE_RANK.editor,
  approve_finance: ROLE_RANK.manager,
  mark_paid: ROLE_RANK.manager,
};

function rankOf(role: string | null | undefined): number {
  const rank = (ROLE_RANK as Readonly<Record<string, number>>)[normalizeRole(role)];
  // An unknown role gets no rank, so it is offered nothing.
  return rank ?? Number.NEGATIVE_INFINITY;
}

/** The pay application page's words for a refusal the approval routes answer with. */
function refusalMessage(err: unknown, t: TFunction): string {
  const detail =
    err instanceof ApiError && err.body && typeof err.body === 'object'
      ? (err.body as { detail?: { code?: string } }).detail
      : undefined;
  if (detail?.code === 'missing_waiver' || detail?.code === 'waiver_amount_mismatch') {
    return t('subcontractors.pay_app_waiver_blocks', {
      defaultValue: 'A signed lien waiver covering the net amount must be on file first.',
    });
  }
  if (detail?.code === 'approved_above_claimed') {
    return t('subcontractors.pay_app_above_claimed', { defaultValue: 'Cannot exceed the amount claimed.' });
  }
  if (detail?.code === 'hakedis_amounts_differ') {
    return t('hakedis.error.hakedis_amounts_differ', {
      defaultValue:
        'The certificate was prepared on the claimed amounts. Approve it as claimed, or reject it and have it submitted again.',
    });
  }
  return getErrorMessage(err);
}

export interface PaymentApprovalActionsProps {
  payment: PaymentApplication;
  /** Whether the agreement holds payment until a lien waiver is on file. */
  requiresWaiver: boolean;
  /** The agreement's retention percent, for the payable the dialog shows. */
  retentionPercent?: number | string;
  /** The agreement's contract has a payment certificate layout, so the row offers the certificate. */
  hakedisAvailable?: boolean;
}

export function PaymentApprovalActions({
  payment,
  requiresWaiver,
  retentionPercent,
  hakedisAvailable = false,
}: PaymentApprovalActionsProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const rank = rankOf(useAuthStore((s) => s.userRole));
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [dialog, setDialog] = useState<'view' | 'approve' | null>(null);
  const [certificateOpen, setCertificateOpen] = useState(false);
  const hakedisSource: HakedisSource = { kind: 'sub_payment_application', id: payment.id };

  const may = (step: Step) => rank >= REQUIRED_RANK[step];
  const waiverGated = payment.status === 'foreman_approved' || payment.status === 'finance_approved';
  // Same cache entry as the row's waiver badge, so both read one answer.
  const checkQ = useQuery({
    queryKey: ['subcontractors', 'releaseCheck', payment.id],
    queryFn: () => getPaymentReleaseCheck(payment.id),
    enabled: requiresWaiver && waiverGated && may('approve_finance'),
  });
  const waiverBlocked = !!checkQ.data?.blocked;

  const stepMut = useMutation({
    mutationFn: ({ step, lines }: { step: Step; lines?: ApprovedLineAmount[] }) => {
      switch (step) {
        case 'approve_foreman':
          return approvePaymentForeman(payment.id);
        case 'approve_finance':
          return approvePaymentFinance(payment.id, lines);
        case 'mark_paid':
          return markPaymentPaid(payment.id);
        case 'reject':
          return rejectPaymentApplication(payment.id, reason.trim());
      }
    },
    onSuccess: () => {
      setRejecting(false);
      setReason('');
      setDialog(null);
      qc.invalidateQueries({ queryKey: ['subcontractors', 'payments', payment.agreement_id] });
      qc.invalidateQueries({ queryKey: ['subcontractors', 'releaseCheck', payment.id] });
      qc.invalidateQueries({ queryKey: ['subcontractors', 'pay-app-lines', payment.id] });
      // Every GC claim rollup shows its pay applications' status.
      qc.invalidateQueries({ queryKey: ['subcontractors', 'claim-rollup'] });
      // An approval certifies the payment certificate, which freezes it.
      qc.invalidateQueries({ queryKey: hakedisBaseKey(hakedisSource) });
      addToast({
        type: 'success',
        title: t('subcontractors.pay_app_updated', { defaultValue: 'Payment application updated' }),
      });
    },
    onError: (err) => {
      // An approval refused over the payment certificate is shown on the
      // certificate itself, against the lines it names.
      if (recordHakedisRefusal(qc, hakedisSource, err)) {
        setDialog(null);
        setCertificateOpen(true);
        addToast({
          type: 'error',
          title: t('hakedis.certify.refused', {
            defaultValue: 'The payment certificate is not ready to certify. See what is missing on the certificate.',
          }),
        });
        return;
      }
      addToast({ type: 'error', title: refusalMessage(err, t) });
    },
  });

  const open = payment.status === 'submitted' || waiverGated;
  const busy = stepMut.isPending;
  const pending = (step: Step) => busy && stepMut.variables?.step === step;

  const linesDialog = dialog && (
    <PayAppLinesDialog
      payment={payment}
      mode={dialog}
      retentionPercent={retentionPercent}
      busy={pending('approve_finance')}
      onClose={() => setDialog(null)}
      onApprove={(lines) => stepMut.mutate({ step: 'approve_finance', lines })}
    />
  );
  const linesButton = (
    <>
      <Button
        variant="ghost"
        size="sm"
        icon={<ListTree size={12} />}
        onClick={() => setDialog('view')}
        data-testid="pay-app-lines-open"
      >
        {t('subcontractors.pay_app_lines', { defaultValue: 'Lines' })}
      </Button>
      {hakedisAvailable && (
        <Button
          variant="ghost"
          size="sm"
          icon={<FileText size={12} />}
          onClick={() => setCertificateOpen(true)}
          data-testid="pay-app-hakedis-open"
        >
          {t('hakedis.open', { defaultValue: 'Certificate' })}
        </Button>
      )}
      {certificateOpen && (
        <HakedisDialog
          source={hakedisSource}
          reference={payment.application_number}
          onClose={() => setCertificateOpen(false)}
        />
      )}
    </>
  );

  // Past approval, or for a role that may not act, the lines are still worth
  // reading: that is where an approval below the claim shows.
  if (!open || !may('reject')) {
    return (
      <>
        {linesButton}
        {linesDialog}
      </>
    );
  }

  const waiverTitle = waiverBlocked
    ? t('subcontractors.pay_app_waiver_blocks', {
        defaultValue: 'A signed lien waiver covering the net amount must be on file first.',
      })
    : undefined;

  if (rejecting) {
    return (
      <div className="flex items-center gap-1">
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={255}
          className="h-7 w-40 rounded-md border border-border-light bg-surface-primary px-2 text-xs"
          aria-label={t('subcontractors.pay_app_reject_reason', { defaultValue: 'Reason for rejecting' })}
          placeholder={t('subcontractors.pay_app_reject_reason', { defaultValue: 'Reason for rejecting' })}
          disabled={busy}
          autoFocus
          data-testid="pay-app-reject-reason"
        />
        <Button
          variant="danger"
          size="sm"
          disabled={!reason.trim()}
          loading={busy}
          onClick={() => stepMut.mutate({ step: 'reject' })}
          data-testid="pay-app-reject-confirm"
        >
          {t('subcontractors.pay_app_reject', { defaultValue: 'Reject' })}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          icon={<X size={12} />}
          onClick={() => {
            setRejecting(false);
            setReason('');
          }}
          disabled={busy}
          aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      {payment.status === 'submitted' && may('approve_foreman') && (
        <Button
          variant="secondary"
          size="sm"
          icon={<Check size={12} />}
          loading={pending('approve_foreman')}
          disabled={busy}
          onClick={() => stepMut.mutate({ step: 'approve_foreman' })}
          title={t('subcontractors.pay_app_approve_work_hint', {
            defaultValue: 'Foreman sign-off: the work billed was done on site.',
          })}
          data-testid="pay-app-approve-work"
        >
          {t('subcontractors.pay_app_approve_work', { defaultValue: 'Approve work' })}
        </Button>
      )}
      {payment.status === 'foreman_approved' && may('approve_finance') && (
        <Button
          variant="primary"
          size="sm"
          icon={<CheckCheck size={12} />}
          disabled={busy || waiverBlocked}
          // The amounts are confirmed in the dialog, which makes the call.
          onClick={() => setDialog('approve')}
          title={
            waiverTitle ??
            t('subcontractors.pay_app_approve_payment_hint', {
              defaultValue: 'Finance sign-off: this pay application will be paid.',
            })
          }
          data-testid="pay-app-approve-payment"
        >
          {t('subcontractors.pay_app_approve_payment', { defaultValue: 'Approve payment' })}
        </Button>
      )}
      {payment.status === 'finance_approved' && may('mark_paid') && (
        <Button
          variant="secondary"
          size="sm"
          icon={<Banknote size={12} />}
          loading={pending('mark_paid')}
          disabled={busy || waiverBlocked}
          onClick={() => stepMut.mutate({ step: 'mark_paid' })}
          title={waiverTitle}
          data-testid="pay-app-mark-paid"
        >
          {t('subcontractors.pay_app_mark_paid', { defaultValue: 'Mark paid' })}
        </Button>
      )}
      <Button
        variant="ghost"
        size="sm"
        disabled={busy}
        onClick={() => setRejecting(true)}
        data-testid="pay-app-reject"
      >
        {t('subcontractors.pay_app_reject', { defaultValue: 'Reject' })}
      </Button>
      {linesButton}
      {linesDialog}
    </div>
  );
}


/**
 * One amount of a pay application in the list: the approved figure once
 * finance has set one, with the claimed figure beneath it when they differ.
 * The claimed figure alone would read as what the sub is paid.
 */
export function PayAppAmount({
  claimed,
  approved,
  currency,
}: {
  claimed: number | string;
  approved?: number | string | null;
  currency?: string;
}) {
  const { t } = useTranslation();
  const claimedN = Number(claimed) || 0;
  const hasApproved = approved !== null && approved !== undefined && approved !== '';
  const approvedN = hasApproved ? Number(approved) || 0 : claimedN;
  const lowered = hasApproved && Math.round(approvedN * 100) !== Math.round(claimedN * 100);
  return (
    <>
      <MoneyDisplay amount={approvedN} currency={currency || undefined} />
      {lowered && (
        <div className="text-2xs font-normal text-content-tertiary" data-testid="pay-app-claimed-figure">
          {t('subcontractors.pay_app_col_claimed', { defaultValue: 'Claimed' })}{' '}
          <MoneyDisplay amount={claimedN} currency={currency || undefined} />
        </div>
      )}
    </>
  );
}
