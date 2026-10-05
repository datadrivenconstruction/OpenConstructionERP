// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PaymentPlanPanel - the instalments a client pays on this contract, and the
// work each one waits for.
//
// It replaces the read-only milestone schedule that used to sit among the
// analytics panels. That table listed planned dates the contract printed and
// nothing moved them; a plan whose stage slipped six weeks still showed the
// client the old day. Here a line can follow a schedule milestone, and the
// server works out its expected due date from that milestone's live finish
// every time the plan is read. The panel shows the result, never a date of its
// own making:
//
//   * the expected due date and how far it moved from the contract's date;
//   * the state as the client will read it (upcoming / due / invoiced / paid /
//     overdue), from the server, so the panel and the portal agree;
//   * the plan's rule findings (over the contract sum, a gap, an unlinked
//     completion payment, a deposit above a statutory limit). The server words
//     the message; the panel adds a short translated heading per rule, since
//     the server speaks only some of our languages.
//
// A reached line with no claim gets one button that raises the draft claim.
// Nothing is submitted or invoiced by it; the claim then lives in the claim
// history like any other.
//
// Every write is gated on the permission its route checks, mirrored in
// shared/lib/permissionGates.ts, so a viewer reads the plan and is not offered
// buttons that always answer 403.

import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  CalendarClock,
  Eye,
  Info,
  Link2,
  Pencil,
  Plus,
  Receipt,
  Trash2,
  Wallet,
  XCircle,
} from 'lucide-react';
import { Badge, Button, ConfirmDialog } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { PaymentPlanStatusBadge } from '@/shared/ui/PaymentPlanStatusBadge';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { fmtPercent } from '@/shared/lib/formatters';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { findingKeys } from './findingKeys';
import { CLAIMS_LIST_KEY } from './claimQueries';
import {
  deleteContractMilestone,
  getPaymentPlan,
  paymentPlanKey,
  raiseMilestoneClaim,
  updateContractMilestone,
  type PaymentPlan,
  type PaymentPlanFinding,
  type PaymentPlanLine,
} from './api';
import { PaymentPlanLineForm, kindLabel, triggerLabel } from './PaymentPlanLineForm';

/** The `error` code a 409 / 422 from the raise-claim route carries, if any. */
function errorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: { error?: unknown } } | null;
  const code = body?.detail && typeof body.detail === 'object' ? body.detail.error : null;
  return typeof code === 'string' ? code : null;
}

function claimErrorMessage(t: TFunction, err: unknown): string {
  switch (errorCode(err)) {
    case 'milestone_not_reached':
      return t('contracts.plan_error_not_reached', {
        defaultValue: 'This instalment is not reached yet, so it cannot be claimed.',
      });
    case 'milestone_already_claimed':
      return t('contracts.plan_error_already_claimed', {
        defaultValue: 'A claim already bills this instalment.',
      });
    case 'milestone_has_no_value':
      return t('contracts.plan_error_no_value', {
        defaultValue: 'This instalment has no amount or percentage, so there is nothing to claim.',
      });
    case 'contract_billed_by_progress':
      return t('contracts.plan_error_billed_by_progress', {
        defaultValue:
          'This contract is already billed by measured progress. A claim for an instalment would bill the same work twice.',
      });
    default:
      return getErrorMessage(err);
  }
}

/** A short translated heading per payment_plan rule; the server's message sits under it. */
function findingTitle(t: TFunction, ruleId: string): string {
  switch (ruleId) {
    case 'payment_plan.total_within_contract':
      return t('contracts.plan_rule_total_within_contract', {
        defaultValue: 'The instalments add up to more than the contract',
      });
    case 'payment_plan.percent_sum':
      return t('contracts.plan_rule_percent_sum', {
        defaultValue: 'Part of the contract has no instalment',
      });
    case 'payment_plan.completion_trigger_linked':
      return t('contracts.plan_rule_completion_trigger_linked', {
        defaultValue: 'An instalment waits for work but is not linked to the schedule',
      });
    case 'payment_plan.client_visible_requires_active':
      return t('contracts.plan_rule_client_visible_requires_active', {
        defaultValue: 'The client would see a plan for a contract not yet in force',
      });
    case 'payment_plan.consumer_deposit_cap':
      return t('contracts.plan_rule_consumer_deposit_cap', {
        defaultValue: 'The deposit may be above the legal limit',
      });
    case 'payment_plan.schedule_done_plan_pending':
      return t('contracts.plan_rule_schedule_done_plan_pending', {
        defaultValue: 'The schedule says the work is done, but the instalment is still waiting',
      });
    default:
      return t('contracts.plan_rule_other', { defaultValue: 'Check this' });
  }
}

function claimStatusLabel(t: TFunction, status: string): string {
  switch (status) {
    case 'draft':
      return t('contracts.claim_status_draft', { defaultValue: 'Draft' });
    case 'submitted':
      return t('contracts.claim_status_submitted', { defaultValue: 'Submitted' });
    case 'approved':
      return t('contracts.claim_status_approved', { defaultValue: 'Approved' });
    case 'certified':
      return t('contracts.claim_status_certified', { defaultValue: 'Certified' });
    case 'paid':
      return t('contracts.claim_status_paid', { defaultValue: 'Paid' });
    case 'rejected':
      return t('contracts.claim_status_rejected', { defaultValue: 'Rejected' });
    default:
      return status;
  }
}

/** Moved later / earlier against the contract's own date. Nothing for zero or unknown. */
function SlipBadge({ days }: { days: number | null }) {
  const { t } = useTranslation();
  if (!days) return null;
  const title = t('contracts.plan_moved_hint', {
    defaultValue: 'Compared with the date in the contract',
  });
  return (
    <span title={title}>
      <Badge variant={days > 0 ? 'warning' : 'blue'} size="sm">
        {days > 0
          ? t('contracts.plan_moved_later', {
              count: days,
              defaultValue_one: '{{count}} day later',
              defaultValue_other: '{{count}} days later',
            })
          : t('contracts.plan_moved_earlier', {
              count: -days,
              defaultValue_one: '{{count}} day earlier',
              defaultValue_other: '{{count}} days earlier',
            })}
      </Badge>
    </span>
  );
}

function FindingsList({ findings }: { findings: PaymentPlanFinding[] }) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  const keys = findingKeys(findings);
  return (
    <div className="mb-3 rounded-md border border-border-light bg-surface-secondary px-3 py-2">
      <p className="mb-1 text-xs font-semibold text-content-secondary">
        {t('contracts.plan_findings_title', { defaultValue: 'Worth checking' })}
      </p>
      <ul className="space-y-2">
        {findings.map((f, i) => {
          const Icon = f.severity === 'error' ? XCircle : f.severity === 'warning' ? AlertTriangle : Info;
          const tone =
            f.severity === 'error'
              ? 'text-semantic-error'
              : f.severity === 'warning'
                ? 'text-semantic-warning'
                : 'text-content-tertiary';
          return (
            <li key={keys[i]} className="flex gap-2 text-sm">
              <Icon size={14} className={`mt-0.5 shrink-0 ${tone}`} />
              <div className="min-w-0">
                <p className="font-medium text-content-primary">{findingTitle(t, f.rule_id)}</p>
                <p className="text-xs text-content-secondary">{f.message}</p>
                {f.suggestion && (
                  <p className="text-xs text-content-tertiary">{f.suggestion}</p>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function PaymentPlanPanel({
  contractId,
  projectId,
  currency,
}: {
  contractId: string;
  projectId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const canCreate = useHasPermission('contracts.create');
  const canUpdate = useHasPermission('contracts.update');
  const canDelete = useHasPermission('contracts.delete');
  const canClaim = useHasPermission('contracts.submit_claim');

  const [editing, setEditing] = useState<string | 'new' | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PaymentPlanLine | null>(null);

  const q = useQuery<PaymentPlan>({
    queryKey: paymentPlanKey(contractId),
    queryFn: () => getPaymentPlan(contractId),
    retry: false,
  });

  const plan = q.data;
  const lines = plan?.lines ?? [];
  const findings = plan?.findings ?? [];
  const cur = plan?.currency || currency;
  const editingLine = editing && editing !== 'new' ? lines.find((l) => l.id === editing) ?? null : null;

  const invalidatePlan = () => qc.invalidateQueries({ queryKey: paymentPlanKey(contractId) });

  const reachMut = useMutation({
    mutationFn: (lineId: string) => updateContractMilestone(lineId, { status: 'reached' }),
    onSuccess: () => {
      invalidatePlan();
      addToast({
        type: 'success',
        title: t('contracts.plan_marked_reached', { defaultValue: 'Marked as reached' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  // A second click lands before the mutation reports itself pending, so the
  // disabled button alone does not stop a double click raising two drafts.
  const claimInFlight = useRef(false);
  const raiseClaim = (lineId: string) => {
    if (claimInFlight.current) return;
    claimInFlight.current = true;
    claimMut.mutate(lineId);
  };

  const claimMut = useMutation({
    mutationFn: (lineId: string) => raiseMilestoneClaim(lineId),
    onSettled: () => {
      claimInFlight.current = false;
    },
    onSuccess: (claim) => {
      invalidatePlan();
      // The new draft shows in the claim history and the claims register,
      // and the drawer's dashboard counts it.
      qc.invalidateQueries({ queryKey: CLAIMS_LIST_KEY });
      qc.invalidateQueries({ queryKey: ['contracts', 'claim-history', contractId] });
      qc.invalidateQueries({ queryKey: ['contracts', 'dashboard', contractId] });
      addToast({
        type: 'success',
        title: t('contracts.plan_claim_created', {
          number: claim.claim_number,
          defaultValue: 'Draft claim {{number}} created. Nothing is sent until you submit it.',
        }),
      });
    },
    onError: (err) => {
      // Someone else may have claimed it meanwhile: the plan should show that.
      if (errorCode(err) === 'milestone_already_claimed') invalidatePlan();
      addToast({ type: 'error', title: claimErrorMessage(t, err) });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (lineId: string) => deleteContractMilestone(lineId),
    onSuccess: () => {
      invalidatePlan();
      setPendingDelete(null);
      addToast({
        type: 'success',
        title: t('contracts.plan_deleted', { defaultValue: 'Instalment deleted' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const readOnly = !canCreate && !canUpdate && !canDelete && !canClaim;

  let body: ReactNode;
  if (q.isLoading) {
    body = (
      <p className="text-sm text-content-tertiary">
        {t('contracts.plan_loading', { defaultValue: 'Loading the payment plan...' })}
      </p>
    );
  } else if (q.isError) {
    const forbidden = q.error instanceof ApiError && q.error.status === 403;
    body = (
      <p className={forbidden ? 'text-sm text-content-tertiary' : 'text-sm text-semantic-error'}>
        {forbidden
          ? t('contracts.plan_no_access', {
              defaultValue: 'You do not have access to this payment plan.',
            })
          : t('contracts.plan_error', { defaultValue: 'The payment plan could not be loaded.' })}
      </p>
    );
  } else if (lines.length === 0) {
    body = (
      <p className="text-sm text-content-tertiary">
        {t('contracts.plan_empty', {
          defaultValue:
            'No instalments yet. Add what the client pays and when: a deposit, a payment per stage of the work, a final payment.',
        })}
      </p>
    );
  } else {
    body = (
      <ul className="divide-y divide-border-light">
        {lines.map((line) => (
          <li key={line.id} className="py-2.5" data-testid={`plan-line-${line.id}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium text-content-primary">
                  {line.name || line.code}
                </p>
                <p className="text-2xs text-content-tertiary">
                  {kindLabel(t, line.kind)} · {triggerLabel(t, line.trigger)}
                </p>
              </div>
              <div className="flex flex-col items-end gap-1">
                <span className="text-sm font-medium tabular-nums text-content-primary">
                  <MoneyDisplay amount={line.amount} currency={cur || undefined} />
                </span>
                {line.value == null && line.percent_of_contract != null && (
                  <span className="text-2xs tabular-nums text-content-tertiary">
                    {t('contracts.plan_percent_of_contract', {
                      percent: fmtPercent(line.percent_of_contract),
                      defaultValue: '{{percent}} of the contract',
                    })}
                  </span>
                )}
              </div>
            </div>

            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-secondary">
              <span className="inline-flex items-center gap-1">
                <Link2 size={12} className="text-content-tertiary" />
                {line.activity_missing ? (
                  <span className="text-semantic-warning">
                    {t('contracts.plan_activity_missing', {
                      defaultValue: 'The linked schedule activity was deleted',
                    })}
                  </span>
                ) : line.activity_id ? (
                  <span>
                    {t('contracts.plan_waits_for', {
                      milestone: line.activity_name ?? '',
                      defaultValue: 'Waits for: {{milestone}}',
                    })}
                  </span>
                ) : (
                  <span className="text-content-tertiary">
                    {t('contracts.plan_not_linked', { defaultValue: 'Not linked to the schedule' })}
                  </span>
                )}
              </span>
              <span className="inline-flex items-center gap-1">
                <CalendarClock size={12} className="text-content-tertiary" />
                {line.forecast_due_date ? (
                  <>
                    <span>{t('contracts.plan_expected_due', { defaultValue: 'Expected due' })}</span>
                    <DateDisplay value={line.forecast_due_date} />
                  </>
                ) : (
                  <span className="text-content-tertiary">
                    {t('contracts.plan_no_date', { defaultValue: 'No date yet' })}
                  </span>
                )}
              </span>
              <SlipBadge days={line.days_moved} />
              <PaymentPlanStatusBadge status={line.client_status} size="sm" />
              {line.client_visible && (
                <span className="inline-flex items-center gap-1 text-2xs text-content-tertiary">
                  <Eye size={12} />
                  {t('contracts.plan_client_sees', { defaultValue: 'Client sees it' })}
                </span>
              )}
              {line.claim_id && line.claim_status && (
                <span className="inline-flex items-center gap-1 text-2xs">
                  <Receipt size={12} className="text-content-tertiary" />
                  {t('contracts.plan_claim_label', { defaultValue: 'Claim' })}
                  <Badge variant="neutral" size="sm">
                    {claimStatusLabel(t, line.claim_status)}
                  </Badge>
                </span>
              )}
            </div>

            {!readOnly && editing === null && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {canClaim && line.status === 'reached' && !line.claim_id && (
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<Receipt size={14} />}
                    onClick={() => raiseClaim(line.id)}
                    disabled={claimMut.isPending}
                    title={t('contracts.plan_raise_claim_hint', {
                      defaultValue:
                        'Creates a draft claim for this amount. Nothing is sent to the client until you submit it.',
                    })}
                  >
                    {t('contracts.plan_raise_claim', { defaultValue: 'Create claim' })}
                  </Button>
                )}
                {canUpdate && line.status === 'pending' && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => reachMut.mutate(line.id)}
                    disabled={reachMut.isPending}
                    title={t('contracts.plan_mark_reached_hint', {
                      defaultValue:
                        'The work this instalment waits for is done, so it can be claimed. Linked lines are marked when the schedule reports the milestone done.',
                    })}
                  >
                    {t('contracts.plan_mark_reached', { defaultValue: 'Mark as reached' })}
                  </Button>
                )}
                {canUpdate && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Pencil size={14} />}
                    onClick={() => setEditing(line.id)}
                  >
                    {t('common.edit', { defaultValue: 'Edit' })}
                  </Button>
                )}
                {canDelete && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 size={14} />}
                    aria-label={t('contracts.plan_delete', { defaultValue: 'Delete instalment' })}
                    onClick={() => setPendingDelete(line)}
                    disabled={deleteMut.isPending}
                  />
                )}
              </div>
            )}

            {editing === line.id && editingLine && (
              <PaymentPlanLineForm
                contractId={contractId}
                projectId={projectId}
                currency={cur}
                contractTotal={plan?.contract_total ?? 0}
                defaultTermsDays={plan?.default_payment_terms_days ?? null}
                line={editingLine}
                onDone={() => setEditing(null)}
              />
            )}
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className="rounded-lg border border-border-light" data-testid="payment-plan-panel">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-border-light px-4 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Wallet size={15} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
              {t('contracts.plan_title', { defaultValue: 'Payment plan' })}
            </span>
          </div>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {t('contracts.plan_subtitle', {
              defaultValue:
                'What the client pays and when. An instalment linked to a schedule milestone moves when that milestone moves.',
            })}
          </p>
          {plan && lines.length > 0 && (
            <p className="mt-1 text-xs text-content-secondary">
              {t('contracts.plan_scheduled_of_total', {
                scheduled: formatCurrency(plan.scheduled_total, cur),
                total: formatCurrency(plan.contract_total, cur),
                defaultValue: 'In the plan: {{scheduled}} of {{total}}',
              })}
              {plan.percent_scheduled != null && (
                <span className="ms-1 text-content-tertiary">
                  ({fmtPercent(plan.percent_scheduled)})
                </span>
              )}
            </p>
          )}
        </div>
        {canCreate && editing === null && !q.isError && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setEditing('new')}
          >
            {t('contracts.plan_add', { defaultValue: 'Add instalment' })}
          </Button>
        )}
      </header>

      <div className="px-4 py-3">
        <FindingsList findings={findings} />
        {body}
        {editing === 'new' && (
          <PaymentPlanLineForm
            contractId={contractId}
            projectId={projectId}
            currency={cur}
            contractTotal={plan?.contract_total ?? 0}
            defaultTermsDays={plan?.default_payment_terms_days ?? null}
            line={null}
            onDone={() => setEditing(null)}
          />
        )}
        {readOnly && lines.length > 0 && (
          <p className="mt-2 text-2xs text-content-tertiary">
            {t('contracts.plan_read_only', {
              defaultValue: 'You can read this plan. Changing it needs editor rights.',
            })}
          </p>
        )}
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        onConfirm={() => pendingDelete && deleteMut.mutate(pendingDelete.id)}
        onCancel={() => setPendingDelete(null)}
        title={t('contracts.plan_delete_title', { defaultValue: 'Delete this instalment?' })}
        message={t('contracts.plan_delete_body', {
          name: pendingDelete?.name ?? '',
          defaultValue:
            '"{{name}}" is removed from the payment plan. A claim already raised from it stays as it is.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        loading={deleteMut.isPending}
      />
    </div>
  );
}
