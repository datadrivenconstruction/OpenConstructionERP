// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ProgressClaimDetailPage — full detail view for a single progress claim.
//
// Route: /projects/:projectId/contracts/claims/:claimId
//
// Shows the claim header (totals + status pipeline), the editable line-item
// table, the "Populate from progress observations" action (Gap I bridge), and
// the lifecycle transition buttons (Submit → Approve → Certify → Mark paid /
// Reject) gated by status + role. Certify and Mark-paid are MANAGER-gated on
// the backend, so the affordances are hidden for editors/viewers. While the
// claim is editable, the submission check (ClaimValidationPanel) sits under
// the header.

import { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Send,
  CheckCircle2,
  XCircle,
  DollarSign,
  Download,
} from 'lucide-react';

import {
  Button,
  Card,
  Badge,
  Breadcrumb,
  DismissibleInfo,
  IntroRichText,
  RecoveryCard,
  SkeletonTable,
} from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  getProgressClaim,
  listClaimLines,
  listContractLines,
  submitClaim,
  approveClaim,
  certifyClaim,
  rejectClaim,
  markClaimPaid,
  type ProgressClaimItem,
  type ClaimStatus,
} from './api';
import { ClaimValidationPanel, claimValidationKey } from './ClaimValidationPanel';
import { ClaimPeriod } from './ClaimPeriod';
import { invalidateClaimAfterLineWrite } from './claimQueries';
import { contractsTabHref } from './contractsTabs';
import { PopulatePreviewModal } from './PopulatePreviewModal';
import { ProgressClaimLineTable } from './ProgressClaimLineTable';
import { AIAApplicationPanel } from './AIAApplicationPanel';
import { SubRollupPanel } from './SubRollupPanel';
import { ClaimInvoicePreview } from '@/features/finance';
import { projectsApi } from '@/features/projects/api';

const CLAIM_STATUS_VARIANT: Record<
  ClaimStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  draft: 'neutral',
  submitted: 'blue',
  approved: 'success',
  certified: 'success',
  paid: 'success',
  rejected: 'error',
};

const CLAIM_STATUS_LABELS: Record<ClaimStatus, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  approved: 'Approved',
  certified: 'Certified',
  paid: 'Paid',
  rejected: 'Rejected',
};

function claimStatusLabel(t: TFunction, status: ClaimStatus): string {
  return t(`contracts.claim_status_${status}`, {
    defaultValue: CLAIM_STATUS_LABELS[status] ?? status,
  });
}

function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

/** The claim is still being decided: draft or out for approval, not settled.
 *  Its lines are a narrower question, see `linesEditable` below. */
function isEditable(status: ClaimStatus): boolean {
  return status === 'draft' || status === 'submitted';
}

export function ProgressClaimDetailPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId, claimId } = useParams<{ projectId: string; claimId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const canManageClaim = userRole === 'admin' || userRole === 'manager';

  const [populateOpen, setPopulateOpen] = useState(false);

  const claimQ = useQuery<ProgressClaimItem>({
    queryKey: ['contracts', 'claim', claimId],
    queryFn: () => getProgressClaim(claimId as string),
    enabled: !!claimId,
  });

  const linesQ = useQuery({
    queryKey: ['contracts', 'claim-lines', claimId],
    queryFn: () => listClaimLines(claimId as string),
    enabled: !!claimId,
  });

  // The contract's schedule of values. The line table names a line by its
  // description rather than the head of a UUID, and a line can only be billed
  // by hand if the screen knows what there is to bill. Same key the register
  // uses, so the two share one cached read.
  const sovQ = useQuery({
    queryKey: ['contracts', 'lines', claimQ.data?.contract_id],
    queryFn: () => listContractLines(claimQ.data?.contract_id as string),
    enabled: !!claimQ.data?.contract_id,
  });

  // Load the project so we can country-gate the AIA G702/G703 panel. The flag
  // is computed server-side (US/CA/AU only); the panel renders only when true,
  // and the AIA endpoints independently 404 elsewhere.
  const projectQ = useQuery({
    queryKey: ['projects', 'detail', projectId],
    queryFn: () => projectsApi.get(projectId as string),
    enabled: !!projectId,
  });

  const claim = claimQ.data;
  const aiaEligible = projectQ.data?.is_aia_eligible === true;

  // Everything the claim's lines feed, the stored totals among them. Named in
  // one place so a screen that writes a line cannot keep figures from before it.
  const invalidate = () => invalidateClaimAfterLineWrite(qc, claimId as string);

  const transitionMut = (
    fn: (id: string) => Promise<ProgressClaimItem>,
    okMsg: string,
  ) =>
    useMutation({
      mutationFn: () => fn(claimId as string),
      onSuccess: () => {
        invalidate();
        addToast({ type: 'success', title: okMsg });
      },
      onError: (err) => {
        // A refused Submit is when the report matters most, and the claim may
        // have changed since the panel last read it.
        qc.invalidateQueries({ queryKey: claimValidationKey(claimId as string) });
        addToast({ type: 'error', title: getErrorMessage(err) });
      },
    });

  const submit = transitionMut(
    submitClaim,
    t('contracts.claim_submitted', { defaultValue: 'Claim submitted' }),
  );
  const approve = transitionMut(
    approveClaim,
    t('contracts.claim_approved', { defaultValue: 'Claim approved' }),
  );
  const certify = transitionMut(
    certifyClaim,
    t('contracts.claim_certified', { defaultValue: 'Claim certified' }),
  );
  const reject = transitionMut(
    rejectClaim,
    t('contracts.claim_rejected', { defaultValue: 'Claim rejected' }),
  );
  const paid = transitionMut(
    markClaimPaid,
    t('contracts.claim_paid', { defaultValue: 'Claim marked paid' }),
  );

  const contractsHref = projectId
    ? `/projects/${projectId}/contracts`
    : '/contracts';
  // Back and the breadcrumb return to the list the claim was opened from. The
  // bare register opens on its Contracts tab, one more click from the claims.
  const claimsHref = contractsTabHref('claims', projectId);

  if (claimQ.isLoading) {
    return (
      <div className="space-y-4">
        <SkeletonTable rows={6} columns={4} />
      </div>
    );
  }

  if (claimQ.isError || !claim) {
    return (
      <RecoveryCard error={claimQ.error} onRetry={() => void claimQ.refetch()} />
    );
  }

  const editable = isEditable(claim.status);
  // Lines are a draft's to change. Once the claim is out for approval its
  // breakdown is what was billed on, and the server refuses a write to it.
  const linesEditable = claim.status === 'draft';

  return (
    <div className="space-y-5" data-testid="progress-claim-detail">
      <Breadcrumb
        items={[
          ...(projectQ.data
            ? [{ label: projectQ.data.name, to: `/projects/${projectQ.data.id}` }]
            : []),
          { label: t('nav.contracts', { defaultValue: 'Contracts' }), to: claimsHref },
          { label: claim.claim_number || t('contracts.claim', { defaultValue: 'Claim' }) },
        ]}
      />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <Link
              to={claimsHref}
              className="text-content-tertiary hover:text-oe-blue"
              aria-label={t('common.back', { defaultValue: 'Back' })}
            >
              <ArrowLeft size={18} />
            </Link>
            <h1 className="text-2xl font-semibold text-content-primary">
              {t('contracts.claim_title', {
                number: claim.claim_number,
                defaultValue: 'Progress claim {{number}}',
              })}
            </h1>
            <Badge variant={CLAIM_STATUS_VARIANT[claim.status]} dot>
              {claimStatusLabel(t, claim.status)}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-content-secondary" data-testid="claim-period">
            {/* The same component the claims list uses, so the two agree. */}
            <ClaimPeriod claim={claim} />
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {linesEditable && (
            <Button
              variant="primary"
              icon={<Download size={14} />}
              onClick={() => setPopulateOpen(true)}
              data-testid="populate-button"
            >
              {t('contracts.populate_from_progress', {
                defaultValue: 'Populate from progress',
              })}
            </Button>
          )}
          {claim.status === 'draft' && (
            <Button
              variant="secondary"
              icon={<Send size={14} />}
              onClick={() => submit.mutate()}
              loading={submit.isPending}
            >
              {t('contracts.submit', { defaultValue: 'Submit' })}
            </Button>
          )}
          {claim.status === 'submitted' && (
            <>
              <Button
                variant="secondary"
                icon={<CheckCircle2 size={14} />}
                onClick={() => approve.mutate()}
                loading={approve.isPending}
              >
                {t('contracts.approve', { defaultValue: 'Approve' })}
              </Button>
              <Button
                variant="ghost"
                icon={<XCircle size={14} />}
                onClick={() => reject.mutate()}
                loading={reject.isPending}
              >
                {t('contracts.reject', { defaultValue: 'Reject' })}
              </Button>
            </>
          )}
          {claim.status === 'approved' && canManageClaim && (
            <Button
              variant="secondary"
              onClick={() => certify.mutate()}
              loading={certify.isPending}
            >
              {t('contracts.certify', { defaultValue: 'Certify' })}
            </Button>
          )}
          {claim.status === 'certified' && canManageClaim && (
            <Button
              variant="primary"
              icon={<DollarSign size={14} />}
              onClick={() => paid.mutate()}
              loading={paid.isPending}
            >
              {t('contracts.mark_paid', { defaultValue: 'Mark paid' })}
            </Button>
          )}
        </div>
      </div>

      {editable && (
        <ClaimValidationPanel
          claimId={claimId as string}
          awaitingSubmit={claim.status === 'draft'}
          aiaEligible={aiaEligible}
        />
      )}

      <DismissibleInfo
        storageKey="contracts-claim"
        title={t('contracts_claim.intro_title', {
          defaultValue: 'Bill exactly what was built this period',
        })}
        more={
          t('contracts_claim.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('contracts_claim.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.contracts', { defaultValue: 'Contracts' }),
            onClick: () => navigate(contractsHref),
          },
          {
            label: t('nav.finance', { defaultValue: 'Finance' }),
            onClick: () => navigate('/finance'),
          },
        ]}
      >
        {t('contracts_claim.intro_body', {
          defaultValue:
            'Enter the percent or value complete against each schedule-of-values line, or pull it straight from progress observations, and the claim totals gross, retention and net due for you. Walk it through Submit, Approve, Certify and Mark paid, and the certified amount flows back to the contract and into Finance as a payable.',
        })}
      </DismissibleInfo>

      {/* Totals */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KPI
          label={t('contracts.gross', { defaultValue: 'Gross' })}
          value={
            <MoneyDisplay
              amount={toNum(claim.gross_amount)}
              currency={claim.currency || undefined}
            />
          }
        />
        <KPI
          label={t('contracts.retention', { defaultValue: 'Retention' })}
          value={
            <MoneyDisplay
              amount={toNum(claim.retention_amount)}
              currency={claim.currency || undefined}
            />
          }
        />
        <KPI
          label={t('contracts.prior_claims', { defaultValue: 'Prior claims' })}
          value={
            <MoneyDisplay
              amount={toNum(claim.prior_claims_total)}
              currency={claim.currency || undefined}
            />
          }
        />
        <KPI
          label={t('contracts.net_due', { defaultValue: 'Net due' })}
          value={
            <MoneyDisplay
              amount={toNum(claim.net_due)}
              currency={claim.currency || undefined}
            />
          }
        />
      </div>

      {/* Line items */}
      <Card padding="sm">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
          {t('contracts.claim_lines', { defaultValue: 'Claim lines' })}
          <span className="ml-2 normal-case text-content-tertiary">
            ({(linesQ.data ?? []).length})
          </span>
        </p>
        {!linesEditable && (
          <p className="mb-2 text-xs text-content-tertiary" data-testid="claim-lines-locked">
            {t('contracts.claim_lines_locked', {
              defaultValue: "Only a draft claim's lines can be changed.",
            })}
            {/* Only while Reject is on this screen. An approved, certified,
                rejected or paid claim cannot be sent back from here, and an
                instruction nobody can follow is worse than none. */}
            {claim.status === 'submitted' && (
              <>
                {' '}
                {t('contracts.claim_lines_locked_reopen', {
                  defaultValue: 'Reject it and raise a new draft claim for the corrected figures.',
                })}
              </>
            )}
          </p>
        )}
        <ProgressClaimLineTable
          claimId={claimId as string}
          lines={linesQ.data ?? []}
          currency={claim.currency}
          editable={linesEditable}
          isLoading={linesQ.isLoading}
          contractLines={sovQ.data ?? []}
        />
      </Card>

      <SubRollupPanel
        claimId={claimId as string}
        contractId={claim.contract_id}
        currency={claim.currency}
        editable={editable}
      />

      {/* The receivable invoice this claim spawns. The component names this
          panel as its home ("drops into the contracts claim detail panel");
          mounting it here closes the gap where the raise-from-claim endpoint
          existed and no screen could reach it. It gates its own action on the
          certified status and shows the invoice once one exists (including
          the one auto-raised by the certification event). */}
      <ClaimInvoicePreview
        claimId={claimId as string}
        certified={claim.status === 'certified' || claim.status === 'paid'}
        onInvoiced={() =>
          addToast({
            type: 'success',
            title: t('finance.claimInvoice.raisedToast', {
              defaultValue: 'Receivable invoice raised from this claim',
            }),
          })
        }
      />

      {/* AIA G702/G703 — US/CA/AU only (gated on project.is_aia_eligible). */}
      {aiaEligible && (
        <AIAApplicationPanel claimId={claimId as string} currency={claim.currency} />
      )}

      {populateOpen && (
        <PopulatePreviewModal
          claimId={claimId as string}
          currency={claim.currency}
          onClose={() => setPopulateOpen(false)}
          onCommitted={invalidate}
        />
      )}
    </div>
  );
}

function KPI({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
        {label}
      </p>
      <p className="mt-0.5 text-sm font-semibold text-content-primary">{value}</p>
    </div>
  );
}
