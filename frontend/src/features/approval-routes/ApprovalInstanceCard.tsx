// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ApprovalInstanceCard — drop-in approval-workflow surface.
//
// Any feature (markups, submittals, RFIs, …) can mount this and pass
// ``targetKind`` + ``targetId`` to render the running approval state for
// that record. Three rendering modes:
//
//   1. No instance exists for the target →
//      compact "Start approval" card (only shown when an active route
//      template exists for this kind, otherwise nothing renders).
//   2. Running / closed instance(s) exist →
//      step-ladder with status pills + decision actions for the active
//      approver.
//   3. Loading / error → skeleton + recovery card.
//
// The backend instance row is flat: it carries `step_states` (one
// decision row per approver per step) plus a 1-based
// `current_step_ordinal`. We join those decisions against the route's
// `steps` (fetched via getRoute) to reconstruct the ladder, since the
// engine never expands roles into a per-step assignee list.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import {
  CheckCircle2,
  XCircle,
  Circle,
  Clock,
  PlayCircle,
  ChevronDown,
  ChevronUp,
  Ban,
} from 'lucide-react';
import clsx from 'clsx';

import { Badge, Button, Card, Skeleton } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  approvalRoutesKeys,
  cancelInstance,
  decideInstance,
  getRoute,
  listInstances,
  listRoutes,
  startInstance,
} from './api';
import { EscalationNotice } from './EscalationNotice';
import type {
  ApprovalInstance,
  ApprovalRoute,
  RouteStep,
  RouteStepMode,
  StepDecision,
  StepState,
} from './types';
import { getIntlLocale } from '@/shared/lib/formatters';

interface MeResponse {
  id?: string;
  user_id?: string;
  email?: string;
  role?: string;
}

/** Derived per-step status used purely for the visual ladder. */
type LadderStepStatus = 'pending' | 'active' | 'approved' | 'rejected';

const STATUS_BADGE: Record<
  LadderStepStatus,
  { variant: 'neutral' | 'blue' | 'success' | 'warning' | 'error'; icon: typeof Circle }
> = {
  pending: { variant: 'neutral', icon: Circle },
  active: { variant: 'blue', icon: Clock },
  approved: { variant: 'success', icon: CheckCircle2 },
  rejected: { variant: 'error', icon: XCircle },
};

export interface ApprovalInstanceCardProps {
  /** Target kind discriminator — e.g. "markup", "submittal", "rfi". */
  targetKind: string;
  /** UUID of the specific target row. */
  targetId: string;
  /** Project the target belongs to — required when starting a new
   *  instance so the route picker can scope by project_id. */
  projectId?: string | null;
  /** Show even when no instance exists and no route template is
   *  configured (renders a muted "no workflow" hint instead of nothing).
   *  Default: false — empty slots collapse cleanly. */
  showEmpty?: boolean;
  /** Extra class applied to the outer Card wrapper. */
  className?: string;
}

/** View-model for one rung of the ladder: the template step joined with
 *  its decision rows for this instance. */
export interface LadderStep {
  step: RouteStep;
  states: StepState[];
  status: LadderStepStatus;
  isCurrent: boolean;
}

export function buildLadder(
  route: ApprovalRoute | undefined,
  instance: ApprovalInstance,
): LadderStep[] {
  if (!route) return [];
  const byStep = new Map<string, StepState[]>();
  for (const s of instance.step_states) {
    const arr = byStep.get(s.step_id) ?? [];
    arr.push(s);
    byStep.set(s.step_id, arr);
  }
  const steps = [...route.steps].sort((a, b) => a.ordinal - b.ordinal);
  return steps.map((step) => {
    const states = byStep.get(step.id) ?? [];
    const hasReject = states.some((s) => s.decision === 'rejected');
    const hasApprove = states.some((s) => s.decision === 'approved');
    const isCurrent =
      instance.status === 'pending' &&
      step.ordinal === instance.current_step_ordinal;
    let status: LadderStepStatus;
    if (hasReject) {
      status = 'rejected';
    } else if (step.ordinal < instance.current_step_ordinal) {
      // The cursor moved past this step — it was cleared.
      status = 'approved';
    } else if (isCurrent) {
      status = hasApprove ? 'approved' : 'active';
    } else {
      status = 'pending';
    }
    return { step, states, status, isCurrent };
  });
}

export function ApprovalInstanceCard({
  targetKind,
  targetId,
  projectId,
  showEmpty = false,
  className,
}: ApprovalInstanceCardProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [expanded, setExpanded] = useState(true);
  const [comments, setComments] = useState<Record<string, string>>({});
  const [showStartPicker, setShowStartPicker] = useState(false);

  // Live current-user lookup so we can decide whether to show the
  // approve/reject buttons. ``staleTime`` is generous because role/id
  // do not change mid-session.
  const { data: me } = useQuery({
    queryKey: ['me'],
    queryFn: () => apiGet<MeResponse>('/v1/users/me/'),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const currentUserId = me?.id ?? me?.user_id ?? null;

  const instancesQuery = useQuery({
    queryKey: approvalRoutesKeys.instances(targetKind, targetId),
    queryFn: () => listInstances({ targetKind, targetId }),
    enabled: Boolean(targetKind && targetId),
    staleTime: 10_000,
  });

  const instances = instancesQuery.data ?? [];
  // The single active workflow (the engine rejects a second pending
  // instance on the same target). ``pending`` IS the active state.
  const activeInstance = instances.find((i) => i.status === 'pending');
  const historicalInstances = instances.filter((i) => i !== activeInstance);

  // Fetch the active instance's route so we can render the step ladder —
  // the instance row only carries step_states, not the template steps.
  const routeQuery = useQuery({
    queryKey: activeInstance
      ? approvalRoutesKeys.route(activeInstance.route_id)
      : ['approval-routes', 'route', 'none'],
    queryFn: () => getRoute(activeInstance!.route_id),
    enabled: Boolean(activeInstance),
    staleTime: 60_000,
  });

  // Only fetch route templates when we need to show the start picker —
  // saves a request on the hot read path where an instance already
  // exists. Only active templates can start a workflow.
  const wantsRoutes = !activeInstance && (showStartPicker || showEmpty);
  const routesQuery = useQuery({
    queryKey: approvalRoutesKeys.routes(projectId, targetKind),
    queryFn: () =>
      listRoutes({ projectId, targetKind, includeInactive: false }),
    enabled: Boolean(targetKind && wantsRoutes),
    staleTime: 60_000,
  });

  // OC-15: resolve user UUIDs to readable names. The same query key
  // is shared with RouteEditor and RFIDetailPage, so the request fires
  // once per page and comes from cache afterwards.
  const { data: userList = [] } = useQuery<{ id: string; email: string; full_name: string }[]>({
    queryKey: ['users-search'],
    queryFn: () => apiGet('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
  });
  const userMap = useMemo(
    () => new Map(userList.map((u) => [u.id, u.full_name || u.email])),
    [userList],
  );

  const startMut = useMutation({
    mutationFn: (routeId: string) =>
      startInstance({ route_id: routeId, target_kind: targetKind, target_id: targetId }),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: approvalRoutesKeys.instances(targetKind, targetId),
      });
      setShowStartPicker(false);
      addToast({
        type: 'success',
        title: t('approvalRoutes.toast_started', { defaultValue: 'Approval started' }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      });
    },
  });

  const decideMut = useMutation({
    mutationFn: ({
      instanceId,
      stepId,
      decision,
      comment,
    }: {
      instanceId: string;
      stepId: string;
      decision: StepDecision;
      comment: string;
    }) =>
      decideInstance(instanceId, {
        step_id: stepId,
        decision,
        comment: comment.trim() || null,
      }),
    onSuccess: (updated, vars) => {
      void qc.invalidateQueries({
        queryKey: approvalRoutesKeys.instances(targetKind, targetId),
      });
      setComments((prev) => {
        const next = { ...prev };
        delete next[vars.stepId];
        return next;
      });
      addToast({
        type: 'success',
        title:
          updated.status === 'approved'
            ? t('approvalRoutes.toast_approved', { defaultValue: 'Approved' })
            : updated.status === 'rejected'
              ? t('approvalRoutes.toast_rejected', { defaultValue: 'Rejected' })
              : t('approvalRoutes.toast_recorded', {
                  defaultValue: 'Decision recorded',
                }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const cancelMut = useMutation({
    mutationFn: (instanceId: string) => cancelInstance(instanceId, {}),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: approvalRoutesKeys.instances(targetKind, targetId),
      });
      addToast({
        type: 'success',
        title: t('approvalRoutes.toast_cancelled', {
          defaultValue: 'Approval cancelled',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const ladder = useMemo(
    () =>
      activeInstance ? buildLadder(routeQuery.data, activeInstance) : [],
    [activeInstance, routeQuery.data],
  );

  /* ── Render branches ────────────────────────────────────────────── */

  if (instancesQuery.isLoading) {
    return (
      <Card padding="sm" className={className} data-testid="approval-instance-card-loading">
        <Skeleton className="h-4 w-32 mb-2" />
        <Skeleton className="h-3 w-full" />
      </Card>
    );
  }

  if (instancesQuery.isError) {
    return (
      <Card padding="sm" className={className}>
        <p className="text-sm text-semantic-error">
          {t('approvalRoutes.load_error', {
            defaultValue: 'Failed to load approval workflow.',
          })}
        </p>
      </Card>
    );
  }

  // No running instance — render the "start" affordance.
  if (!activeInstance) {
    const availableRoutes = routesQuery.data ?? [];
    const canStart = availableRoutes.length > 0;
    if (!showEmpty && !showStartPicker && !canStart && instances.length === 0) {
      // Lazy mode: nothing to show until user clicks the button below.
      return (
        <Card
          padding="sm"
          className={className}
          data-testid="approval-instance-card-empty-lazy"
        >
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-content-tertiary">
              {t('approvalRoutes.noActiveInstance', {
                defaultValue: 'No approval workflow running.',
              })}
            </p>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setShowStartPicker(true)}
              icon={<PlayCircle size={14} />}
            >
              {t('approvalRoutes.startApproval', { defaultValue: 'Start approval' })}
            </Button>
          </div>
          {historicalInstances.length > 0 && (
            <HistoryList instances={historicalInstances} />
          )}
        </Card>
      );
    }

    return (
      <Card padding="sm" className={className} data-testid="approval-instance-card-empty">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-content-primary">
              {t('approvalRoutes.startApproval', {
                defaultValue: 'Start approval',
              })}
            </p>
            {!canStart && (
              <p className="mt-0.5 text-xs text-content-tertiary">
                {t('approvalRoutes.noRoutesConfigured', {
                  defaultValue:
                    'No approval route configured for this kind yet. Create one under Settings → Approval Routes.',
                })}
              </p>
            )}
          </div>
        </div>

        {canStart && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {availableRoutes.map((route) => (
              <Button
                key={route.id}
                size="sm"
                variant="primary"
                onClick={() => startMut.mutate(route.id)}
                loading={startMut.isPending && startMut.variables === route.id}
                disabled={startMut.isPending}
                icon={<PlayCircle size={14} />}
              >
                {route.name}
              </Button>
            ))}
          </div>
        )}

        {historicalInstances.length > 0 && (
          <HistoryList instances={historicalInstances} />
        )}
      </Card>
    );
  }

  // Running instance.
  return (
    <Card padding="sm" className={className} data-testid="approval-instance-card">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <p className="text-sm font-semibold text-content-primary truncate">
            {routeQuery.data?.name ||
              t('approvalRoutes.title', { defaultValue: 'Approval' })}
          </p>
          <InstanceStatusBadge status={activeInstance.status} />
        </div>
        <button
          onClick={() => setExpanded((p) => !p)}
          className="p-1 rounded-md hover:bg-surface-secondary text-content-tertiary"
          aria-label={
            expanded
              ? t('common.collapse', { defaultValue: 'Collapse' })
              : t('common.expand', { defaultValue: 'Expand' })
          }
        >
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>

      <EscalationNotice instanceId={activeInstance.id} />

      {expanded && (
        <div className="mt-3 space-y-2">
          {routeQuery.isLoading ? (
            <Skeleton className="h-12 w-full" />
          ) : (
            ladder.map((rung, idx) => (
              <StepRow
                key={rung.step.id}
                rung={rung}
                index={idx}
                total={ladder.length}
                currentUserId={currentUserId}
                userMap={userMap}
                comment={comments[rung.step.id] ?? ''}
                onCommentChange={(value) =>
                  setComments((p) => ({ ...p, [rung.step.id]: value }))
                }
                onDecide={(decision) =>
                  decideMut.mutate({
                    instanceId: activeInstance.id,
                    stepId: rung.step.id,
                    decision,
                    comment: comments[rung.step.id] ?? '',
                  })
                }
                deciding={
                  decideMut.isPending &&
                  decideMut.variables?.stepId === rung.step.id
                }
              />
            ))
          )}

          <div className="flex items-center justify-end pt-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => cancelMut.mutate(activeInstance.id)}
              loading={cancelMut.isPending}
              icon={<Ban size={13} />}
            >
              {t('approvalRoutes.cancel', { defaultValue: 'Cancel workflow' })}
            </Button>
          </div>
        </div>
      )}

      {historicalInstances.length > 0 && (
        <HistoryList instances={historicalInstances} />
      )}
    </Card>
  );
}

/* ── Helpers ────────────────────────────────────────────────────────── */

export function InstanceStatusBadge({ status }: { status: ApprovalInstance['status'] }) {
  const { t } = useTranslation();
  const variant: 'neutral' | 'blue' | 'success' | 'warning' | 'error' =
    status === 'approved'
      ? 'success'
      : status === 'rejected'
        ? 'error'
        : status === 'cancelled'
          ? 'neutral'
          : 'blue';
  const label = t(`approvalRoutes.status_${status}`, {
    defaultValue: status.charAt(0).toUpperCase() + status.slice(1),
  });
  return (
    <Badge variant={variant} size="sm">
      {label}
    </Badge>
  );
}

export interface StepRowProps {
  rung: LadderStep;
  index: number;
  total: number;
  currentUserId: string | null;
  userMap: Map<string, string>;
  comment: string;
  onCommentChange: (value: string) => void;
  onDecide: (decision: StepDecision) => void;
  deciding: boolean;
}

export function StepRow({
  rung,
  index,
  total,
  currentUserId,
  userMap,
  comment,
  onCommentChange,
  onDecide,
  deciding,
}: StepRowProps) {
  const { t } = useTranslation();
  const { step, states, status, isCurrent } = rung;
  const cfg = STATUS_BADGE[status] ?? STATUS_BADGE.pending;
  const StatusIcon = cfg.icon;

  // Whether the current user already recorded a decision on this step.
  const myDecision = useMemo(
    () =>
      currentUserId
        ? states.find((s) => s.approver_user_id === currentUserId) ?? null
        : null,
    [states, currentUserId],
  );

  // The current user can act when the step is the active one and they
  // have not already decided. For a user-pinned step only the named user
  // may act; role steps are open to any approver with the decide
  // permission (the backend is the authority — a 403 surfaces as a toast).
  const isNamedApprover =
    step.approver_user_id != null && step.approver_user_id === currentUserId;
  const isRoleStep = step.approver_user_id == null;
  const canAct =
    isCurrent &&
    !myDecision &&
    (isNamedApprover || isRoleStep);

  const approverLabel =
    step.approver_role ||
    (step.approver_user_id && userMap.get(step.approver_user_id)) ||
    (step.approver_user_id ? step.approver_user_id.slice(0, 8) + '...' : null) ||
    t('approvalRoutes.approver_unassigned', { defaultValue: 'Unassigned' });

  return (
    <div
      className={clsx(
        'rounded-lg border px-3 py-2 transition-colors',
        isCurrent
          ? 'border-oe-blue/60 bg-oe-blue-subtle/40'
          : 'border-border-light bg-surface-primary',
      )}
    >
      <div className="flex items-center gap-2">
        <StatusIcon
          size={14}
          className={clsx(
            'shrink-0',
            status === 'approved' && 'text-semantic-success',
            status === 'rejected' && 'text-semantic-error',
            status === 'active' && 'text-oe-blue',
            status === 'pending' && 'text-content-tertiary',
          )}
        />
        <span className="text-xs font-medium text-content-secondary tabular-nums">
          {t('approvalRoutes.step_n_of_m', {
            defaultValue: 'Step {{n}}/{{m}}',
            n: index + 1,
            m: total,
          })}
        </span>
        <span className="text-sm text-content-primary truncate">
          {approverLabel}
        </span>
        <Badge variant={cfg.variant} size="sm" className="ml-auto">
          {t(`approvalRoutes.step_status_${status}`, {
            defaultValue: status.charAt(0).toUpperCase() + status.slice(1),
          })}
        </Badge>
      </div>

      <p className="mt-1 text-2xs text-content-tertiary">
        {t(`approvalRoutes.mode_${step.mode}`, {
          defaultValue: modeDefault(step.mode),
        })}
        {step.sla_hours != null && (
          <>
            {' · '}
            <span
              title={t('approvalRoutes.sla_informational_hint', {
                defaultValue:
                  'Target turnaround. Once overdue past a grace window the approval escalates to the next approver in the route.',
              })}
            >
              {t('approvalRoutes.sla_target_value', {
                defaultValue: 'Target SLA {{h}}h',
                h: step.sla_hours,
              })}
            </span>
          </>
        )}
      </p>

      {canAct && (
        <div className="mt-2 space-y-2">
          <textarea
            value={comment}
            onChange={(e) => onCommentChange(e.target.value)}
            placeholder={t('approvalRoutes.commentPlaceholder', {
              defaultValue: 'Optional comment…',
            })}
            rows={2}
            className="w-full rounded-md border border-border bg-surface-primary px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            data-testid={`approval-comment-${step.id}`}
          />
          <div className="flex items-center justify-end gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => onDecide('rejected')}
              loading={deciding}
              icon={<XCircle size={13} />}
              data-testid={`approval-reject-${step.id}`}
            >
              {t('approvalRoutes.rejectButton', { defaultValue: 'Reject' })}
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => onDecide('approved')}
              loading={deciding}
              icon={<CheckCircle2 size={13} />}
              data-testid={`approval-approve-${step.id}`}
            >
              {t('approvalRoutes.approveButton', { defaultValue: 'Approve' })}
            </Button>
          </div>
        </div>
      )}

      {/* Per-decision audit rows (visible once recorded). */}
      {states.some((s) => s.decision !== 'pending') && (
        <ul className="mt-2 space-y-0.5">
          {states
            .filter((s) => s.decision !== 'pending')
            .map((s) => (
              <li
                key={s.id}
                className="flex items-center gap-1.5 text-2xs text-content-tertiary"
              >
                {s.decision === 'approved' ? (
                  <CheckCircle2 size={11} className="text-semantic-success" />
                ) : (
                  <XCircle size={11} className="text-semantic-error" />
                )}
                <span className="truncate">
                  {s.approver_user_id ??
                    t('approvalRoutes.approver_unassigned', {
                      defaultValue: 'Unassigned',
                    })}
                </span>
                {s.comment && (
                  <span className="text-content-tertiary truncate">
                    — {s.comment}
                  </span>
                )}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

function modeDefault(mode: RouteStepMode): string {
  if (mode === 'all') return 'All approvers';
  if (mode === 'any') return 'Any approver';
  return 'Majority';
}

function HistoryList({ instances }: { instances: ApprovalInstance[] }) {
  const { t } = useTranslation();
  if (instances.length === 0) return null;
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-2xs font-medium text-content-tertiary uppercase tracking-wide">
        {t('approvalRoutes.history', { defaultValue: 'History' })} ({instances.length})
      </summary>
      <ul className="mt-1 space-y-1">
        {instances.map((i) => (
          <li
            key={i.id}
            className="flex items-center gap-2 text-xs text-content-secondary"
          >
            <InstanceStatusBadge status={i.status} />
            <span className="truncate">{i.id.slice(0, 8)}</span>
            {i.completed_at && (
              <span className="text-content-tertiary text-2xs ml-auto">
                {new Date(i.completed_at).toLocaleDateString(getIntlLocale())}
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
