// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Slide-out drawer launched from the preview pane. Shows the workflow's
// ordered approval steps as a vertical timeline (avatar + status badge
// + decision_at + decision_note). The active approver sees inline
// Approve / Reject buttons.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  X,
  Check,
  XCircle,
  Clock,
  UserCheck,
  Download,
  Undo2,
} from 'lucide-react';
import clsx from 'clsx';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

import {
  useApproval,
  useDecideApprovalStep,
  useWithdrawApproval,
} from './hooks';
import type { ApprovalStep } from './types';

interface ApprovalDrawerProps {
  open: boolean;
  workflowId: string | null;
  onClose: () => void;
}

const DECISION_VARIANT: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  pending: 'neutral',
  approved: 'success',
  rejected: 'error',
  delegated: 'warning',
};

const DECISION_ICON: Record<string, typeof Check> = {
  pending: Clock,
  approved: Check,
  rejected: XCircle,
  delegated: UserCheck,
};

export function ApprovalDrawer({ open, workflowId, onClose }: ApprovalDrawerProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  // Auth payload contains the current user sub (UUID).
  // ``useAuthStore`` is the project's canonical source for the access
  // token; the user-id is decoded on demand.
  const accessToken = useAuthStore((s) => s.accessToken);
  const currentUserId = useMemo(() => decodeSubFromJwt(accessToken), [accessToken]);

  const { data: workflow, isLoading } = useApproval(workflowId);
  const decide = useDecideApprovalStep();
  const withdraw = useWithdrawApproval();

  const [decisionNote, setDecisionNote] = useState('');
  const [activeStepId, setActiveStepId] = useState<string | null>(null);

  useEffect(() => {
    setDecisionNote('');
    setActiveStepId(null);
  }, [workflowId]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const sortedSteps: ApprovalStep[] = workflow?.steps
    ? [...workflow.steps].sort((a, b) => a.sort_order - b.sort_order)
    : [];

  // The first ``pending`` step is the actionable one.
  const actionableStep = sortedSteps.find((s) => s.decision === 'pending');

  async function handleDecision(stepId: string, decision: 'approved' | 'rejected') {
    if (!workflowId) return;
    try {
      await decide.mutateAsync({
        workflowId,
        stepId,
        payload: { decision, decision_note: decisionNote.trim() || null },
      });
      addToast({
        type: 'success',
        title:
          decision === 'approved'
            ? t('files.approvals.step_approved', {
                defaultValue: 'Step approved',
              })
            : t('files.approvals.step_rejected', {
                defaultValue: 'Step rejected',
              }),
      });
      setDecisionNote('');
      setActiveStepId(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('files.approvals.decision_failed', {
          defaultValue: 'Decision failed',
        }),
        message: err instanceof Error ? err.message : undefined,
      });
    }
  }

  async function handleWithdraw() {
    if (!workflowId) return;
    try {
      await withdraw.mutateAsync(workflowId);
      addToast({
        type: 'success',
        title: t('files.approvals.withdrew', { defaultValue: 'Withdrawn' }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('files.approvals.withdraw_failed', {
          defaultValue: 'Withdraw failed',
        }),
        message: err instanceof Error ? err.message : undefined,
      });
    }
  }

  async function handleDownloadStamped() {
    if (!workflowId) return;
    const url = `/api/v1/file-approvals/${workflowId}/stamped/`;
    const token = useAuthStore.getState().accessToken;
    const headers = new Headers({ Accept: 'application/pdf, application/json' });
    if (token) headers.set('Authorization', `Bearer ${token}`);
    try {
      const res = await fetch(url, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const disposition = res.headers.get('Content-Disposition') ?? '';
      const match = /filename="?([^";]+)"?/i.exec(disposition);
      const filename = match?.[1] ?? `approval-${workflowId}.pdf`;
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objUrl;
      a.download = filename;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(objUrl);
      }, 500);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('files.approvals.download_failed', {
          defaultValue: 'Download failed',
        }),
        message: err instanceof Error ? err.message : undefined,
      });
    }
  }

  const workflowStatusVariant =
    workflow?.status === 'approved'
      ? 'success'
      : workflow?.status === 'rejected'
        ? 'error'
        : workflow?.status === 'withdrawn'
          ? 'neutral'
          : 'blue';

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={t('files.approvals.drawer_title', {
          defaultValue: 'Approval workflow',
        })}
        className={clsx(
          'fixed inset-y-0 right-0 z-50 w-full max-w-md',
          'bg-surface-elevated border-l border-border-light shadow-2xl',
          'flex flex-col animate-slide-in-right',
        )}
      >
        <header className="flex items-start justify-between gap-3 px-5 py-4 border-b border-border-light">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-content-primary">
              {t('files.approvals.drawer_title', {
                defaultValue: 'Approval workflow',
              })}
            </h2>
            {workflow && (
              <div className="flex items-center gap-2 mt-1">
                <Badge variant={workflowStatusVariant} dot>
                  {t(`files.approvals.status.${workflow.status}`, {
                    defaultValue:
                      workflow.status.charAt(0).toUpperCase() +
                      workflow.status.slice(1).replace('_', ' '),
                  })}
                </Badge>
                <span className="text-xs text-content-tertiary">
                  <DateDisplay value={workflow.submitted_at} />
                </span>
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="text-content-tertiary hover:text-content-primary"
          >
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading && (
            <p className="text-sm text-content-tertiary text-center py-6">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </p>
          )}

          {workflow && (
            <>
              {workflow.notes && (
                <section className="mb-4 p-3 rounded-md bg-surface-secondary/50 border border-border-light">
                  <p className="text-xs text-content-secondary uppercase mb-1">
                    {t('files.approvals.submitter_notes', {
                      defaultValue: 'Submitter notes',
                    })}
                  </p>
                  <p className="text-sm whitespace-pre-wrap">{workflow.notes}</p>
                </section>
              )}

              <ol className="relative border-l-2 border-border-light pl-5 space-y-5">
                {sortedSteps.map((step) => {
                  const Icon = DECISION_ICON[step.decision] ?? Clock;
                  const variant = DECISION_VARIANT[step.decision] ?? 'neutral';
                  const isActionable =
                    actionableStep?.id === step.id &&
                    workflow.status === 'in_review' &&
                    currentUserId === step.approver_id;
                  return (
                    <li key={step.id} className="relative">
                      <span
                        className={clsx(
                          'absolute -left-[28px] top-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full border-2 bg-surface-elevated',
                          step.decision === 'approved'
                            ? 'border-semantic-success text-semantic-success'
                            : step.decision === 'rejected'
                              ? 'border-semantic-error text-semantic-error'
                              : 'border-border text-content-tertiary',
                        )}
                        aria-hidden
                      >
                        <Icon size={10} />
                      </span>
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-sm font-medium">
                            {step.role_label ??
                              t('files.approvals.approver_step', {
                                defaultValue: 'Approver #{{n}}',
                                n: step.sort_order + 1,
                              })}
                          </p>
                          <p className="text-xs text-content-tertiary font-mono truncate">
                            {step.approver_id}
                          </p>
                        </div>
                        <Badge variant={variant} size="sm">
                          {t(`files.approvals.decision.${step.decision}`, {
                            defaultValue:
                              step.decision.charAt(0).toUpperCase() +
                              step.decision.slice(1),
                          })}
                        </Badge>
                      </div>
                      {step.decision_at && (
                        <p className="text-xs text-content-tertiary mt-1">
                          <DateDisplay value={step.decision_at} />
                        </p>
                      )}
                      {step.decision_note && (
                        <p className="text-xs text-content-secondary mt-1 italic whitespace-pre-wrap">
                          “{step.decision_note}”
                        </p>
                      )}
                      {isActionable && (
                        <div className="mt-3 p-3 rounded-md border border-oe-blue/40 bg-oe-blue-subtle/30 space-y-2">
                          <p className="text-xs font-semibold text-oe-blue">
                            {t('files.approvals.your_turn', {
                              defaultValue: 'Your decision is needed',
                            })}
                          </p>
                          {activeStepId === step.id ? (
                            <>
                              <textarea
                                value={decisionNote}
                                onChange={(e) => setDecisionNote(e.target.value)}
                                rows={2}
                                placeholder={t('files.approvals.note_placeholder', {
                                  defaultValue:
                                    'Optional decision note (visible on the workflow)',
                                })}
                                maxLength={4000}
                                className="w-full px-2 py-1 text-xs rounded-md border border-border bg-surface-primary"
                              />
                              <div className="flex gap-2">
                                <Button
                                  variant="primary"
                                  onClick={() => handleDecision(step.id, 'approved')}
                                  loading={decide.isPending}
                                  icon={<Check size={14} />}
                                >
                                  {t('files.approvals.approve', {
                                    defaultValue: 'Approve',
                                  })}
                                </Button>
                                <Button
                                  variant="danger"
                                  onClick={() => handleDecision(step.id, 'rejected')}
                                  loading={decide.isPending}
                                  icon={<XCircle size={14} />}
                                >
                                  {t('files.approvals.reject', {
                                    defaultValue: 'Reject',
                                  })}
                                </Button>
                                <Button
                                  variant="ghost"
                                  onClick={() => setActiveStepId(null)}
                                >
                                  {t('common.cancel', { defaultValue: 'Cancel' })}
                                </Button>
                              </div>
                            </>
                          ) : (
                            <Button
                              variant="primary"
                              onClick={() => setActiveStepId(step.id)}
                            >
                              {t('files.approvals.decide', {
                                defaultValue: 'Record decision',
                              })}
                            </Button>
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </div>

        <footer className="shrink-0 px-5 py-3 border-t border-border-light bg-surface-primary/30 flex items-center justify-between gap-2">
          {workflow?.status === 'in_review' &&
          workflow.submitted_by_id === currentUserId ? (
            <Button
              variant="secondary"
              onClick={handleWithdraw}
              loading={withdraw.isPending}
              icon={<Undo2 size={14} />}
            >
              {t('files.approvals.withdraw', { defaultValue: 'Withdraw' })}
            </Button>
          ) : (
            <span />
          )}
          {workflow?.stamped_artifact_path && (
            <Button
              variant="primary"
              onClick={handleDownloadStamped}
              icon={<Download size={14} />}
            >
              {t('files.approvals.download_stamped', {
                defaultValue: 'Download stamped',
              })}
            </Button>
          )}
        </footer>
      </aside>
    </>
  );
}

/**
 * Decode the ``sub`` claim from a JWT without verifying the signature.
 *
 * Tests + the drawer only need to know "is this user the approver" so
 * the un-verified claim is fine — the backend re-hydrates identity on
 * every request anyway.
 */
function decodeSubFromJwt(token: string | null): string | null {
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length < 2) return null;
  try {
    const payload = parts[1] ?? '';
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const json = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
    const parsed = JSON.parse(json) as { sub?: string };
    return parsed.sub ?? null;
  } catch {
    return null;
  }
}
